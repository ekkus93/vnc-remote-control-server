use super::WorkerSettings;
use super::channels::WorkerChannels;
use super::client::WorkerClient;
use super::command::CommandEnvelope;
use super::run::run_worker;
use super::session::WorkerSession;
use super::snapshot::{WorkerEvents, WorkerSnapshot};
use crate::framebuffer::FramebufferStore;
use libvnc_adapter::{NativeClient, NativeError};
use remote_desktop_core::{ConnectionState, DesktopError};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, sync_channel};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime};

const WORKER_THREAD_NAME: &str = "vnc-desktop-worker";
pub(super) const DROP_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);

/// Owning worker runtime. Dropping it requests shutdown and joins the thread.
pub struct DesktopWorker {
    client: WorkerClient,
    events: Option<WorkerEvents>,
    join: Option<JoinHandle<()>>,
    worker_exited: Option<Receiver<()>>,
}

impl DesktopWorker {
    /// Spawns the production worker and waits for thread startup acknowledgement.
    pub fn spawn(settings: WorkerSettings) -> Result<Self, DesktopError> {
        let native = settings.native.clone();
        Self::spawn_with_factory(settings, move || NativeClient::connect(&native))
    }

    /// Returns a cloneable client handle.
    pub fn client(&self) -> WorkerClient {
        self.client.clone()
    }

    /// Returns the event receiver while it remains owned by the worker.
    pub fn events(&self) -> &WorkerEvents {
        self.events
            .as_ref()
            .expect("worker events already transferred")
    }

    /// Transfers the single event receiver to the asynchronous event bridge.
    pub fn take_events(&mut self) -> Result<WorkerEvents, DesktopError> {
        self.events.take().ok_or(DesktopError::WorkerUnavailable)
    }

    /// Requests out-of-band shutdown and waits no longer than `timeout` for
    /// the worker thread to report exit. The request cannot fail on a
    /// saturated command queue: it does not enqueue `WorkerCommand::Shutdown`,
    /// it stores directly into a shared shutdown flag the worker loop checks
    /// independently of the bounded queue.
    pub fn shutdown(mut self, timeout: Duration) -> Result<(), DesktopError> {
        self.client.request_shutdown();
        match self.wait_for_worker_exit(timeout) {
            Ok(()) => self.join_worker(),
            Err(DesktopError::Timeout) => {
                tracing::warn!(
                    timeout_ms = u64::try_from(timeout.as_millis()).unwrap_or(u64::MAX),
                    "desktop_worker_shutdown_timeout"
                );
                self.detach_worker();
                Err(DesktopError::Timeout)
            }
            Err(error) => Err(error),
        }
    }

    pub(super) fn spawn_with_factory<F, S>(
        settings: WorkerSettings,
        factory: F,
    ) -> Result<Self, DesktopError>
    where
        F: FnMut() -> Result<S, NativeError> + Send + 'static,
        S: WorkerSession + 'static,
    {
        Self::spawn_with_factory_and_startup_hook(settings, factory, || {})
    }

    pub(super) fn spawn_with_factory_and_startup_hook<F, S, H>(
        settings: WorkerSettings,
        factory: F,
        before_startup: H,
    ) -> Result<Self, DesktopError>
    where
        F: FnMut() -> Result<S, NativeError> + Send + 'static,
        S: WorkerSession + 'static,
        H: FnOnce() + Send + 'static,
    {
        settings.validate()?;
        let startup_timeout = settings.startup_timeout;
        let command_capacity = settings.command_capacity;
        let framebuffer = FramebufferStore::new(settings.maximum_framebuffer_bytes)?;
        let thread_framebuffer = framebuffer.clone();
        let clipboard = Arc::new(Mutex::new(None));
        let thread_clipboard = Arc::clone(&clipboard);
        let (command_tx, command_rx) = sync_channel(settings.command_capacity);
        let (event_tx, event_rx) = sync_channel(settings.event_capacity);
        let (startup_tx, startup_rx) = sync_channel(1);
        let (worker_exited_tx, worker_exited_rx) = sync_channel(1);
        let command_queue_depth = Arc::new(AtomicUsize::new(0));
        let pending_overload = Arc::new(AtomicU64::new(0));
        let thread_pending_overload = Arc::clone(&pending_overload);
        let shutdown_requested = Arc::new(AtomicBool::new(false));
        let thread_shutdown_requested = Arc::clone(&shutdown_requested);
        let snapshot = Arc::new(Mutex::new(WorkerSnapshot {
            state: ConnectionState::Starting,
            started_at: SystemTime::now(),
            connected_at: None,
            last_message_at: None,
            reconnect_attempts: 0,
            last_failure: None,
            framebuffer_revision: None,
            rejected_commands: 0,
            dropped_events: 0,
            fatal_exit: false,
        }));
        let thread_snapshot = Arc::clone(&snapshot);
        let dispatcher = tracing::dispatcher::get_default(Clone::clone);
        let join = thread::Builder::new()
            .name(WORKER_THREAD_NAME.to_owned())
            .spawn(move || tracing::dispatcher::with_default(&dispatcher, || {
                let channels = WorkerChannels {
                    commands: command_rx,
                    events: event_tx,
                    startup: startup_tx,
                    pending_overload: thread_pending_overload,
                    shutdown_requested: thread_shutdown_requested,
                    worker_exited: worker_exited_tx,
                };
                before_startup();
                run_worker(
                    settings,
                    factory,
                    channels,
                    thread_snapshot,
                    thread_framebuffer,
                    thread_clipboard,
                );
            }))
            .map_err(|error| {
                DesktopError::Configuration(format!("failed to spawn desktop worker: {error}"))
            })?;

        match startup_rx.recv_timeout(startup_timeout) {
            Ok(()) => Ok(Self {
                client: WorkerClient {
                    commands: command_tx,
                    snapshot,
                    framebuffer,
                    clipboard,
                    next_command_id: Arc::new(AtomicU64::new(1)),
                    command_queue_depth,
                    command_queue_capacity: command_capacity,
                    pending_overload,
                    shutdown_requested,
                },
                events: Some(WorkerEvents { receiver: event_rx }),
                join: Some(join),
                worker_exited: Some(worker_exited_rx),
            }),
            Err(RecvTimeoutError::Timeout) => {
                // The out-of-band flag is the guaranteed cleanup signal; the
                // queue nudge below is a best-effort extra and its failure
                // must not matter.
                shutdown_requested.store(true, Ordering::Release);
                let _ = command_tx.try_send(CommandEnvelope::shutdown_without_waiter(
                    Arc::clone(&command_queue_depth),
                ));
                match cleanup_startup_worker_after_timeout(
                    join,
                    worker_exited_rx,
                    startup_timeout,
                ) {
                    Err(DesktopError::WorkerUnavailable) => Err(DesktopError::WorkerUnavailable),
                    Ok(()) | Err(DesktopError::Timeout) => Err(DesktopError::Timeout),
                    Err(error) => Err(error),
                }
            }
            Err(RecvTimeoutError::Disconnected) => {
                shutdown_requested.store(true, Ordering::Release);
                match cleanup_startup_worker_after_timeout(
                    join,
                    worker_exited_rx,
                    startup_timeout,
                ) {
                    Ok(()) => Err(DesktopError::WorkerUnavailable),
                    Err(error) => Err(error),
                }
            }
        }
    }

    fn wait_for_worker_exit(&mut self, timeout: Duration) -> Result<(), DesktopError> {
        let Some(receiver) = self.worker_exited.take() else {
            return Ok(());
        };
        match receiver.recv_timeout(timeout) {
            Ok(()) | Err(RecvTimeoutError::Disconnected) => Ok(()),
            Err(RecvTimeoutError::Timeout) => Err(DesktopError::Timeout),
        }
    }

    fn detach_worker(&mut self) {
        drop(self.worker_exited.take());
        drop(self.join.take());
    }

    fn join_worker(&mut self) -> Result<(), DesktopError> {
        let Some(join) = self.join.take() else {
            return Ok(());
        };
        join_worker_handle(join)
    }
}

fn join_worker_handle(join: JoinHandle<()>) -> Result<(), DesktopError> {
    match join.join() {
        Ok(()) => Ok(()),
        Err(_) => {
            tracing::error!("desktop_worker_join_failed");
            Err(DesktopError::WorkerUnavailable)
        }
    }
}

pub(super) fn cleanup_startup_worker_after_timeout(
    join: JoinHandle<()>,
    worker_exited: Receiver<()>,
    timeout: Duration,
) -> Result<(), DesktopError> {
    match worker_exited.recv_timeout(timeout) {
        Ok(()) | Err(RecvTimeoutError::Disconnected) => {
            let result = join_worker_handle(join);
            if let Err(error) = &result {
                tracing::error!(error = ?error, "desktop_worker_startup_join_failed");
            }
            result
        }
        Err(RecvTimeoutError::Timeout) => {
            tracing::warn!(
                timeout_ms = u64::try_from(timeout.as_millis()).unwrap_or(u64::MAX),
                "desktop_worker_startup_cleanup_timeout"
            );
            drop(join);
            Err(DesktopError::Timeout)
        }
    }
}

impl Drop for DesktopWorker {
    fn drop(&mut self) {
        if self.join.is_none() {
            return;
        }
        self.client.request_shutdown();
        match self.wait_for_worker_exit(DROP_SHUTDOWN_TIMEOUT) {
            Ok(()) => {
                if let Err(error) = self.join_worker() {
                    tracing::error!(error = ?error, "desktop_worker_drop_join_failed");
                }
            }
            Err(DesktopError::Timeout) => {
                tracing::warn!(
                    timeout_ms =
                        u64::try_from(DROP_SHUTDOWN_TIMEOUT.as_millis()).unwrap_or(u64::MAX),
                    "desktop_worker_drop_shutdown_timeout"
                );
                self.detach_worker();
            }
            Err(error) => {
                tracing::error!(error = ?error, "desktop_worker_drop_wait_failed");
                self.detach_worker();
            }
        }
    }
}
