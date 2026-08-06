use super::channels::WorkerChannels;
use super::command::CommandEnvelope;
use super::helpers::{classify_native_error, lock_unpoisoned};
use super::loop_state::LoopState;
use super::session::WorkerSession;
use super::snapshot::WorkerSnapshot;
use super::{WorkerFailureKind, WorkerSettings};
use crate::framebuffer::FramebufferStore;
use crate::input::InputController;
use libvnc_adapter::NativeError;
use remote_desktop_core::{
    ClipboardSnapshot, ConnectionState, DesktopError, DesktopEventKind, WorkerCommand,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, SyncSender, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// Drains queued command envelopes without executing them, resolving each
/// pending caller with `WorkerUnavailable` so command tickets do not hang
/// until an arbitrary timeout during shutdown. Never inspects or logs command
/// payloads. Dequeue ownership releases each envelope's queue-depth permit.
pub(super) fn drain_pending_commands(commands: &Receiver<CommandEnvelope>) {
    while let Ok(mut envelope) = commands.try_recv() {
        envelope.release_queue_depth();
        let _ = envelope
            .completion
            .send(Err(DesktopError::WorkerUnavailable));
    }
}

/// Returns `true` and drains any pending commands if out-of-band shutdown has
/// been requested. Shutdown responsiveness never depends on command-queue
/// capacity or on successfully enqueueing `WorkerCommand::Shutdown`.
pub(super) fn shutdown_now(
    shutdown_requested: &AtomicBool,
    commands: &Receiver<CommandEnvelope>,
) -> bool {
    if !shutdown_requested.load(Ordering::Acquire) {
        return false;
    }
    drain_pending_commands(commands);
    true
}

struct WorkerExitSignal {
    sender: Option<SyncSender<()>>,
}

impl WorkerExitSignal {
    fn new(sender: SyncSender<()>) -> Self {
        Self {
            sender: Some(sender),
        }
    }
}

impl Drop for WorkerExitSignal {
    fn drop(&mut self) {
        if let Some(sender) = self.sender.take() {
            let _ = sender.try_send(());
        }
    }
}

pub(super) enum ReceivedCommandAction {
    Execute(CommandEnvelope),
    Stop,
}

/// Releases queue ownership, then applies receive-side shutdown authority
/// before any ordinary command can reach the native session.
pub(super) fn classify_received_command(
    mut envelope: CommandEnvelope,
    shutdown_requested: &AtomicBool,
    commands: &Receiver<CommandEnvelope>,
) -> ReceivedCommandAction {
    envelope.release_queue_depth();
    if matches!(&envelope.command, WorkerCommand::Shutdown) {
        shutdown_requested.store(true, Ordering::Release);
        let _ = envelope.completion.send(Ok(()));
        drain_pending_commands(commands);
        return ReceivedCommandAction::Stop;
    }
    if shutdown_requested.load(Ordering::Acquire) {
        let _ = envelope
            .completion
            .send(Err(DesktopError::WorkerUnavailable));
        drain_pending_commands(commands);
        return ReceivedCommandAction::Stop;
    }
    ReceivedCommandAction::Execute(envelope)
}

pub(super) fn run_worker<F, S>(
    settings: WorkerSettings,
    mut factory: F,
    channels: WorkerChannels,
    snapshot: Arc<Mutex<WorkerSnapshot>>,
    framebuffer: FramebufferStore,
    clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,
) where
    F: FnMut() -> Result<S, NativeError>,
    S: WorkerSession,
{
    let WorkerChannels {
        commands,
        events,
        startup,
        pending_overload,
        shutdown_requested,
        worker_exited,
    } = channels;
    let _worker_exit_signal = WorkerExitSignal::new(worker_exited);
    let worker_span = tracing::info_span!("desktop_worker");
    let _worker_entered = worker_span.enter();
    let _ = startup.send(());
    let mut state = LoopState {
        settings: &settings,
        snapshot: &snapshot,
        events: &events,
        framebuffer,
        clipboard: &clipboard,
        event_sequence: 0,
        session: None,
        last_native_revision: None,
        last_native_clipboard_revision: None,
        clipboard_revision: 0,
        clipboard_decode_failed: false,
        input: InputController::default(),
        next_connect: Some(Instant::now()),
        reconnect_attempt: 0,
        connected_since: None,
        last_message: Instant::now(),
        probe_sent: None,
        last_manual_reconnect: None,
    };
    let mut orderly_shutdown = false;

    loop {
        if shutdown_now(&shutdown_requested, &commands) {
            orderly_shutdown = true;
            break;
        }

        if pending_overload.swap(0, Ordering::AcqRel) > 0 {
            state.publish(DesktopEventKind::Overload);
        }

        if state.session.is_none()
            && state
                .next_connect
                .is_some_and(|deadline| Instant::now() >= deadline)
        {
            if state.begin_connect().is_err() {
                break;
            }
            let connection_span =
                tracing::info_span!("vnc_connection_attempt", attempt = state.reconnect_attempt);
            let _connection_entered = connection_span.enter();
            match factory() {
                Ok(mut session) => match session.request_full_refresh() {
                    Ok(()) => {
                        state.session = Some(session);
                        state.last_message = Instant::now();
                        state.probe_sent = None;
                        state.next_connect = None;
                    }
                    Err(error) => {
                        state.record_failure(classify_native_error(&error));
                        state.schedule_reconnect();
                    }
                },
                Err(error) => {
                    let failure = classify_native_error(&error);
                    state.record_failure(failure);
                    match failure {
                        WorkerFailureKind::Authentication => {
                            let _ = state.transition(ConnectionState::AuthenticationFailed);
                            state.next_connect = None;
                        }
                        WorkerFailureKind::Configuration => {
                            let _ = state.transition(ConnectionState::Stopped);
                            break;
                        }
                        _ => state.schedule_reconnect(),
                    }
                }
            }
        }

        if shutdown_now(&shutdown_requested, &commands) {
            orderly_shutdown = true;
            break;
        }

        match commands.try_recv() {
            Ok(envelope) => {
                let envelope =
                    match classify_received_command(envelope, &shutdown_requested, &commands) {
                        ReceivedCommandAction::Execute(envelope) => envelope,
                        ReceivedCommandAction::Stop => {
                            orderly_shutdown = true;
                            break;
                        }
                    };
                let result = match envelope.command {
                    WorkerCommand::Shutdown => unreachable!("shutdown handled before execution"),
                    WorkerCommand::Reconnect => state.manual_reconnect(),
                    command => state.execute(command),
                };
                let _ = envelope.completion.send(result);
                if shutdown_now(&shutdown_requested, &commands) {
                    orderly_shutdown = true;
                    break;
                }
                continue;
            }
            Err(TryRecvError::Disconnected) => break,
            Err(TryRecvError::Empty) => {}
        }

        if shutdown_now(&shutdown_requested, &commands) {
            orderly_shutdown = true;
            break;
        }

        if state.session.is_some() {
            if state.poll().is_err() {
                break;
            }
        } else {
            thread::sleep(settings.poll_interval.min(Duration::from_millis(50)));
        }
    }

    // Closing the receiver drops any envelope that raced the final drain. Its
    // queue-depth permit releases automatically, and a racing `try_send()`
    // receives `Disconnected` and drops its returned permit as well.
    drop(commands);
    state.invalidate();
    let _ = state.transition(ConnectionState::Stopped);
    if !orderly_shutdown {
        lock_unpoisoned(&snapshot).fatal_exit = true;
    }
}
