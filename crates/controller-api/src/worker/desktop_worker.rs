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
use std::sync::mpsc::{RecvTimeoutError, sync_channel};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime};

const WORKER_THREAD_NAME: &str = "vnc-desktop-worker";

/// Owning worker runtime. Dropping it requests shutdown and joins the thread.
pub struct DesktopWorker {
    client: WorkerClient,
    events: Option<WorkerEvents>,
    join: Option<JoinHandle<()>>,
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

    /// Requests out-of-band shutdown and joins the native thread. The request
    /// cannot fail on a saturated command queue: it does not enqueue
    /// `WorkerCommand::Shutdown`, it stores directly into a shared shutdown
    /// flag the worker loop checks independently of the bounded queue.
    /// Shutdown responsiveness is bounded by the worker's existing native
    /// poll interval and adapter timeouts, not by an additional timeout
    /// here, so `timeout` is currently unused.
    pub fn shutdown(mut self, _timeout: Duration) -> Result<(), DesktopError> {
        self.client.request_shutdown();
        self.join_worker()
    }

    pub(super) fn spawn_with_factory<F, S>(
        settings: WorkerSettings,
        factory: F,
    ) -> Result<Self, DesktopError>
    where
        F: FnMut() -> Result<S, NativeError> + Send + 'static,
        S: WorkerSession + 'static,
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
        let command_queue_depth = Arc::new(AtomicUsize::new(0));
        let thread_command_queue_depth = Arc::clone(&command_queue_depth);
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
        let join = thread::Builder::new()
            .name(WORKER_THREAD_NAME.to_owned())
            .spawn(move || {
                run_worker(
                    settings,
                    factory,
                    WorkerChannels {
                        commands: command_rx,
                        events: event_tx,
                        startup: startup_tx,
                        command_queue_depth: thread_command_queue_depth,
                        pending_overload: thread_pending_overload,
                        shutdown_requested: thread_shutdown_requested,
                    },
                    thread_snapshot,
                    thread_framebuffer,
                    thread_clipboard,
                );
            })
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
            }),
            Err(RecvTimeoutError::Timeout) => {
                // The out-of-band flag is the guaranteed cleanup signal; the
                // queue nudge below is a best-effort extra and its failure
                // must not matter.
                shutdown_requested.store(true, Ordering::Release);
                let _ = command_tx.try_send(CommandEnvelope::shutdown_without_waiter());
                let _ = join.join();
                Err(DesktopError::Timeout)
            }
            Err(RecvTimeoutError::Disconnected) => {
                let _ = join.join();
                Err(DesktopError::WorkerUnavailable)
            }
        }
    }

    fn join_worker(&mut self) -> Result<(), DesktopError> {
        let Some(join) = self.join.take() else {
            return Ok(());
        };
        join.join().map_err(|_| DesktopError::WorkerUnavailable)
    }
}

impl Drop for DesktopWorker {
    fn drop(&mut self) {
        if self.join.is_none() {
            return;
        }
        self.client.request_shutdown();
        let _ = self.join_worker();
    }
}
