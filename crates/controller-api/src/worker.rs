//! Single-session desktop worker lifecycle.
//!
//! The worker owns the native adapter on exactly one dedicated thread. HTTP or
//! asynchronous runtime tasks interact only through bounded channels and shared
//! immutable status snapshots.

use libvnc_adapter::{
    NativeClient, NativeClientConfig, NativeDisplayInfo, NativeError, PollOutcome,
};
use remote_desktop_core::{
    ConnectionState, DesktopError, DesktopEventKind, KeyboardKey, MouseButton, WorkerCommand,
    validate_chord, validate_scroll, validate_text,
};
use std::collections::HashSet;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{
    Receiver, RecvTimeoutError, SyncSender, TryRecvError, TrySendError, sync_channel,
};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime};

const MAX_DOUBLE_CLICK_INTERVAL: Duration = Duration::from_secs(1);
const WORKER_THREAD_NAME: &str = "vnc-desktop-worker";

/// Native worker timing and capacity configuration.
#[derive(Clone, PartialEq, Eq)]
pub struct WorkerSettings {
    /// Native VNC connection configuration. Contains the secret password and is
    /// intentionally not `Debug`.
    pub native: NativeClientConfig,
    /// Maximum accepted commands awaiting the worker thread.
    pub command_capacity: usize,
    /// Maximum events awaiting the event consumer.
    pub event_capacity: usize,
    /// Maximum native poll duration before command processing resumes.
    pub poll_interval: Duration,
    /// Maximum wait for the worker thread startup acknowledgement.
    pub startup_timeout: Duration,
    /// Initial automatic reconnect delay.
    pub reconnect_min_delay: Duration,
    /// Maximum automatic reconnect delay.
    pub reconnect_max_delay: Duration,
    /// Maximum positive jitter as per-mille of the base delay.
    pub reconnect_jitter_per_mille: u16,
    /// Connected duration required before reconnect backoff resets.
    pub stable_connection_reset: Duration,
    /// Minimum interval between accepted manual reconnect commands.
    pub manual_reconnect_interval: Duration,
    /// Idle duration before a full-refresh probe is sent.
    pub stall_probe_after: Duration,
    /// Additional duration without a server message after a probe before the
    /// connection is considered stalled.
    pub stall_confirm_after: Duration,
}

impl WorkerSettings {
    /// Validates all bounded worker settings before a thread is spawned.
    pub fn validate(&self) -> Result<(), DesktopError> {
        if self.command_capacity == 0 || self.event_capacity == 0 {
            return Err(DesktopError::Configuration(
                "worker channel capacities must be nonzero".to_owned(),
            ));
        }
        for (name, value) in [
            ("poll_interval", self.poll_interval),
            ("startup_timeout", self.startup_timeout),
            ("reconnect_min_delay", self.reconnect_min_delay),
            ("reconnect_max_delay", self.reconnect_max_delay),
            ("stable_connection_reset", self.stable_connection_reset),
            ("manual_reconnect_interval", self.manual_reconnect_interval),
            ("stall_probe_after", self.stall_probe_after),
            ("stall_confirm_after", self.stall_confirm_after),
        ] {
            if value.is_zero() {
                return Err(DesktopError::Configuration(format!(
                    "{name} must be nonzero"
                )));
            }
        }
        if self.reconnect_min_delay > self.reconnect_max_delay {
            return Err(DesktopError::Configuration(
                "minimum reconnect delay exceeds maximum".to_owned(),
            ));
        }
        if self.reconnect_jitter_per_mille > 500 {
            return Err(DesktopError::Configuration(
                "reconnect jitter must not exceed 500 per-mille".to_owned(),
            ));
        }
        Ok(())
    }
}

/// Coarse failure category safe for status and metrics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerFailureKind {
    /// VNC credentials were rejected during protocol initialization.
    Authentication,
    /// Static configuration is invalid and should not be retried.
    Configuration,
    /// The TCP transport failed or disconnected.
    Transport,
    /// A bounded operation deadline was exceeded.
    Timeout,
    /// The remote protocol or framebuffer contract failed.
    Protocol,
    /// Another bounded native adapter operation failed.
    Native,
}

/// Read-only worker status snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSnapshot {
    /// Current public lifecycle state.
    pub state: ConnectionState,
    /// Worker process-local start time.
    pub started_at: SystemTime,
    /// Most recent successful connection time.
    pub connected_at: Option<SystemTime>,
    /// Most recent successfully processed server message time.
    pub last_message_at: Option<SystemTime>,
    /// Number of consecutive reconnect attempts.
    pub reconnect_attempts: u32,
    /// Last bounded failure category.
    pub last_failure: Option<WorkerFailureKind>,
    /// Whether a complete current framebuffer is available.
    pub framebuffer_current: bool,
    /// Number of events dropped because the bounded event queue was full.
    pub dropped_events: u64,
    /// Whether the worker exited unexpectedly.
    pub fatal_exit: bool,
}

/// One redacted worker event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerEvent {
    /// Monotonically increasing process-local event sequence.
    pub sequence: u64,
    /// Event observation time.
    pub observed_at: SystemTime,
    /// Payload-free public event kind.
    pub kind: DesktopEventKind,
}

/// Accepted worker command and its completion receiver.
pub struct CommandTicket {
    id: u64,
    completion: Receiver<Result<(), DesktopError>>,
}

impl CommandTicket {
    /// Process-local command identifier.
    pub const fn id(&self) -> u64 {
        self.id
    }

    /// Waits for command execution completion within a caller-supplied deadline.
    pub fn wait(self, timeout: Duration) -> Result<(), DesktopError> {
        match self.completion.recv_timeout(timeout) {
            Ok(result) => result,
            Err(RecvTimeoutError::Timeout) => Err(DesktopError::Timeout),
            Err(RecvTimeoutError::Disconnected) => Err(DesktopError::WorkerUnavailable),
        }
    }
}

/// Cloneable bounded command and status handle.
#[derive(Clone)]
pub struct WorkerClient {
    commands: SyncSender<CommandEnvelope>,
    snapshot: Arc<Mutex<WorkerSnapshot>>,
    next_command_id: Arc<AtomicU64>,
}

impl WorkerClient {
    /// Submits one command without touching native adapter state.
    pub fn submit(&self, command: WorkerCommand) -> Result<CommandTicket, DesktopError> {
        let id = self
            .next_command_id
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| DesktopError::WorkerUnavailable)?;
        let (completion_tx, completion_rx) = sync_channel(1);
        let envelope = CommandEnvelope {
            id,
            command,
            completion: completion_tx,
        };
        match self.commands.try_send(envelope) {
            Ok(()) => Ok(CommandTicket {
                id,
                completion: completion_rx,
            }),
            Err(TrySendError::Full(_)) => Err(DesktopError::CommandQueueFull),
            Err(TrySendError::Disconnected(_)) => Err(DesktopError::WorkerUnavailable),
        }
    }

    /// Returns one coherent status snapshot.
    pub fn snapshot(&self) -> WorkerSnapshot {
        lock_unpoisoned(&self.snapshot).clone()
    }
}

/// Event receiver separated from the cloneable command client.
pub struct WorkerEvents {
    receiver: Receiver<WorkerEvent>,
}

impl WorkerEvents {
    /// Waits for one worker event.
    pub fn recv_timeout(&self, timeout: Duration) -> Result<WorkerEvent, RecvTimeoutError> {
        self.receiver.recv_timeout(timeout)
    }
}

/// Owning worker runtime. Dropping it requests shutdown and joins the thread.
pub struct DesktopWorker {
    client: WorkerClient,
    events: WorkerEvents,
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

    /// Returns the event receiver.
    pub const fn events(&self) -> &WorkerEvents {
        &self.events
    }

    /// Requests orderly shutdown, waits for acknowledgement, and joins the native thread.
    pub fn shutdown(mut self, timeout: Duration) -> Result<(), DesktopError> {
        let ticket = self.client.submit(WorkerCommand::Shutdown)?;
        ticket.wait(timeout)?;
        self.join_worker()
    }

    fn spawn_with_factory<F, S>(settings: WorkerSettings, factory: F) -> Result<Self, DesktopError>
    where
        F: FnMut() -> Result<S, NativeError> + Send + 'static,
        S: WorkerSession + 'static,
    {
        settings.validate()?;
        let (command_tx, command_rx) = sync_channel(settings.command_capacity);
        let (event_tx, event_rx) = sync_channel(settings.event_capacity);
        let (startup_tx, startup_rx) = sync_channel(1);
        let snapshot = Arc::new(Mutex::new(WorkerSnapshot {
            state: ConnectionState::Starting,
            started_at: SystemTime::now(),
            connected_at: None,
            last_message_at: None,
            reconnect_attempts: 0,
            last_failure: None,
            framebuffer_current: false,
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
                    command_rx,
                    event_tx,
                    startup_tx,
                    thread_snapshot,
                );
            })
            .map_err(|error| {
                DesktopError::Configuration(format!("failed to spawn desktop worker: {error}"))
            })?;

        match startup_rx.recv_timeout(settings.startup_timeout) {
            Ok(Ok(())) => Ok(Self {
                client: WorkerClient {
                    commands: command_tx,
                    snapshot,
                    next_command_id: Arc::new(AtomicU64::new(1)),
                },
                events: WorkerEvents { receiver: event_rx },
                join: Some(join),
            }),
            Ok(Err(error)) => {
                let _ = join.join();
                Err(error)
            }
            Err(RecvTimeoutError::Timeout) => Err(DesktopError::Timeout),
            Err(RecvTimeoutError::Disconnected) => Err(DesktopError::WorkerUnavailable),
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
        if let Ok(ticket) = self.client.submit(WorkerCommand::Shutdown) {
            let _ = ticket.wait(Duration::from_secs(2));
        }
        let _ = self.join_worker();
    }
}

struct CommandEnvelope {
    id: u64,
    command: WorkerCommand,
    completion: SyncSender<Result<(), DesktopError>>,
}

trait WorkerSession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError>;
    fn request_full_refresh(&mut self) -> Result<(), NativeError>;
    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError>;
    fn send_pointer(
        &mut self,
        coordinate: remote_desktop_core::Coordinate,
        button_mask: u8,
    ) -> Result<(), NativeError>;
    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError>;
    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError>;
}

impl WorkerSession for NativeClient {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        self.poll(timeout)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        self.request_full_refresh()
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        self.display_info()
    }

    fn send_pointer(
        &mut self,
        coordinate: remote_desktop_core::Coordinate,
        button_mask: u8,
    ) -> Result<(), NativeError> {
        self.send_pointer(coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        self.send_key(key, pressed)
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        self.send_clipboard(text)
    }
}

struct InputState {
    button_mask: u8,
    pressed_keys: HashSet<KeyboardKey>,
}

fn run_worker<F, S>(
    settings: WorkerSettings,
    mut factory: F,
    command_rx: Receiver<CommandEnvelope>,
    event_tx: SyncSender<WorkerEvent>,
    startup_tx: SyncSender<Result<(), DesktopError>>,
    snapshot: Arc<Mutex<WorkerSnapshot>>,
) where
    F: FnMut() -> Result<S, NativeError>,
    S: WorkerSession,
{
    let mut event_sequence = 0_u64;
    let mut session: Option<S> = None;
    let mut input = InputState {
        button_mask: 0,
        pressed_keys: HashSet::new(),
    };
    let mut next_connect = Some(Instant::now());
    let mut reconnect_attempt = 0_u32;
    let mut connected_since: Option<Instant> = None;
    let mut last_message = Instant::now();
    let mut probe_sent: Option<Instant> = None;
    let mut last_manual_reconnect: Option<Instant> = None;
    let mut orderly_shutdown = false;

    let _ = startup_tx.send(Ok(()));

    loop {
        if session.is_none()
            && next_connect.is_some_and(|deadline| Instant::now() >= deadline)
        {
            let connecting_state = if reconnect_attempt == 0 {
                ConnectionState::Connecting
            } else {
                ConnectionState::Reconnecting
            };
            if transition(
                &snapshot,
                &event_tx,
                &mut event_sequence,
                connecting_state,
            )
            .is_err()
            {
                break;
            }

            match factory() {
                Ok(mut new_session) => {
                    if let Err(error) = new_session.request_full_refresh() {
                        record_failure(&snapshot, classify_native_error(&error));
                        schedule_reconnect(
                            &settings,
                            &snapshot,
                            &event_tx,
                            &mut event_sequence,
                            &mut next_connect,
                            &mut reconnect_attempt,
                        );
                    } else {
                        session = Some(new_session);
                        last_message = Instant::now();
                        probe_sent = None;
                    }
                }
                Err(error) => {
                    let failure = classify_native_error(&error);
                    record_failure(&snapshot, failure);
                    match failure {
                        WorkerFailureKind::Authentication => {
                            let _ = transition(
                                &snapshot,
                                &event_tx,
                                &mut event_sequence,
                                ConnectionState::AuthenticationFailed,
                            );
                            next_connect = None;
                        }
                        WorkerFailureKind::Configuration => {
                            let _ = transition(
                                &snapshot,
                                &event_tx,
                                &mut event_sequence,
                                ConnectionState::Stopped,
                            );
                            break;
                        }
                        _ => schedule_reconnect(
                            &settings,
                            &snapshot,
                            &event_tx,
                            &mut event_sequence,
                            &mut next_connect,
                            &mut reconnect_attempt,
                        ),
                    }
                }
            }
        }

        match command_rx.try_recv() {
            Ok(envelope) => {
                let command_id = envelope.id;
                let result = if matches!(envelope.command, WorkerCommand::Shutdown) {
                    orderly_shutdown = true;
                    Ok(())
                } else if matches!(envelope.command, WorkerCommand::Reconnect) {
                    handle_manual_reconnect(
                        &settings,
                        &snapshot,
                        &event_tx,
                        &mut event_sequence,
                        &mut session,
                        &mut input,
                        &mut next_connect,
                        &mut reconnect_attempt,
                        &mut last_manual_reconnect,
                    )
                } else if let Some(active) = session.as_mut() {
                    execute_command(active, &mut input, envelope.command)
                } else {
                    Err(DesktopError::WorkerUnavailable)
                };
                let _ = envelope.completion.send(result);
                let _ = command_id;
                if orderly_shutdown {
                    break;
                }
                continue;
            }
            Err(TryRecvError::Disconnected) => break,
            Err(TryRecvError::Empty) => {}
        }

        let Some(active) = session.as_mut() else {
            thread::sleep(settings.poll_interval.min(Duration::from_millis(50)));
            continue;
        };

        match active.poll(settings.poll_interval) {
            Ok(PollOutcome::MessageProcessed) => {
                last_message = Instant::now();
                probe_sent = None;
                {
                    let mut current = lock_unpoisoned(&snapshot);
                    current.last_message_at = Some(SystemTime::now());
                }
                if let Ok(display) = active.display_info()
                    && display.complete
                {
                    let state = lock_unpoisoned(&snapshot).state;
                    if state != ConnectionState::Connected {
                        if transition(
                            &snapshot,
                            &event_tx,
                            &mut event_sequence,
                            ConnectionState::Connected,
                        )
                        .is_err()
                        {
                            break;
                        }
                        let mut current = lock_unpoisoned(&snapshot);
                        current.connected_at = Some(SystemTime::now());
                        current.framebuffer_current = true;
                        current.last_failure = None;
                        connected_since = Some(Instant::now());
                    }
                }
                if connected_since.is_some_and(|since| {
                    Instant::now().saturating_duration_since(since)
                        >= settings.stable_connection_reset
                }) {
                    reconnect_attempt = 0;
                    lock_unpoisoned(&snapshot).reconnect_attempts = 0;
                }
            }
            Ok(PollOutcome::TimedOut) => {
                let idle = Instant::now().saturating_duration_since(last_message);
                if probe_sent.is_none() && idle >= settings.stall_probe_after {
                    match active.request_full_refresh() {
                        Ok(()) => probe_sent = Some(Instant::now()),
                        Err(error) => {
                            record_failure(&snapshot, classify_native_error(&error));
                            invalidate_connection(
                                &snapshot,
                                &event_tx,
                                &mut event_sequence,
                                &mut session,
                                &mut input,
                            );
                            schedule_reconnect(
                                &settings,
                                &snapshot,
                                &event_tx,
                                &mut event_sequence,
                                &mut next_connect,
                                &mut reconnect_attempt,
                            );
                        }
                    }
                } else if probe_sent.is_some_and(|sent| {
                    Instant::now().saturating_duration_since(sent)
                        >= settings.stall_confirm_after
                }) {
                    record_failure(&snapshot, WorkerFailureKind::Timeout);
                    let _ = transition(
                        &snapshot,
                        &event_tx,
                        &mut event_sequence,
                        ConnectionState::Degraded,
                    );
                    invalidate_connection(
                        &snapshot,
                        &event_tx,
                        &mut event_sequence,
                        &mut session,
                        &mut input,
                    );
                    schedule_reconnect(
                        &settings,
                        &snapshot,
                        &event_tx,
                        &mut event_sequence,
                        &mut next_connect,
                        &mut reconnect_attempt,
                    );
                }
            }
            Err(error) => {
                record_failure(&snapshot, classify_native_error(&error));
                invalidate_connection(
                    &snapshot,
                    &event_tx,
                    &mut event_sequence,
                    &mut session,
                    &mut input,
                );
                schedule_reconnect(
                    &settings,
                    &snapshot,
                    &event_tx,
                    &mut event_sequence,
                    &mut next_connect,
                    &mut reconnect_attempt,
                );
            }
        }
    }

    drop(session);
    input.button_mask = 0;
    input.pressed_keys.clear();
    let _ = transition(
        &snapshot,
        &event_tx,
        &mut event_sequence,
        ConnectionState::Stopped,
    );
    if !orderly_shutdown {
        lock_unpoisoned(&snapshot).fatal_exit = true;
    }
}

fn execute_command<S: WorkerSession>(
    session: &mut S,
    input: &mut InputState,
    command: WorkerCommand,
) -> Result<(), DesktopError> {
    match command {
        WorkerCommand::MovePointer { coordinate } => session
            .send_pointer(coordinate, input.button_mask)
            .map_err(DesktopError::from),
        WorkerCommand::SetButton {
            coordinate,
            button,
            pressed,
        } => {
            let mask = if pressed {
                input.button_mask | button.rfb_mask()
            } else {
                input.button_mask & !button.rfb_mask()
            };
            session.send_pointer(coordinate, mask)?;
            input.button_mask = mask;
            Ok(())
        }
        WorkerCommand::Click { coordinate, button } => {
            send_click(session, input, coordinate, button)
        }
        WorkerCommand::DoubleClick {
            coordinate,
            button,
            interval_ms,
        } => {
            let interval = Duration::from_millis(interval_ms);
            if interval > MAX_DOUBLE_CLICK_INTERVAL {
                return Err(DesktopError::Configuration(
                    "double-click interval exceeds one second".to_owned(),
                ));
            }
            send_click(session, input, coordinate, button)?;
            thread::sleep(interval);
            send_click(session, input, coordinate, button)
        }
        WorkerCommand::Scroll {
            coordinate,
            delta_x,
            delta_y,
        } => send_scroll(session, input, coordinate, delta_x, delta_y),
        WorkerCommand::SetKey { key, pressed } => {
            session.send_key(key, pressed)?;
            if pressed {
                input.pressed_keys.insert(key);
            } else {
                input.pressed_keys.remove(&key);
            }
            Ok(())
        }
        WorkerCommand::Chord { keys } => send_chord(session, input, &keys),
        WorkerCommand::TypeText { text } => send_text(session, input, &text),
        WorkerCommand::SetClipboard { text } => {
            session.send_clipboard(&text).map_err(DesktopError::from)
        }
        WorkerCommand::RequestFullRefresh => session
            .request_full_refresh()
            .map_err(DesktopError::from),
        WorkerCommand::Reconnect | WorkerCommand::Shutdown => {
            Err(DesktopError::Configuration("invalid command path".to_owned()))
        }
    }
}

fn send_click<S: WorkerSession>(
    session: &mut S,
    input: &mut InputState,
    coordinate: remote_desktop_core::Coordinate,
    button: MouseButton,
) -> Result<(), DesktopError> {
    let down_mask = input.button_mask | button.rfb_mask();
    session.send_pointer(coordinate, down_mask)?;
    match session.send_pointer(coordinate, input.button_mask) {
        Ok(()) => Ok(()),
        Err(error) => {
            let _ = session.send_pointer(coordinate, input.button_mask);
            Err(error.into())
        }
    }
}

fn send_scroll<S: WorkerSession>(
    session: &mut S,
    input: &InputState,
    coordinate: remote_desktop_core::Coordinate,
    delta_x: i32,
    delta_y: i32,
) -> Result<(), DesktopError> {
    validate_scroll(delta_x, delta_y)?;
    let horizontal_mask = if delta_x < 0 { 32 } else { 64 };
    let vertical_mask = if delta_y > 0 { 8 } else { 16 };
    for _ in 0..delta_x.unsigned_abs() {
        session.send_pointer(coordinate, input.button_mask | horizontal_mask)?;
        session.send_pointer(coordinate, input.button_mask)?;
    }
    for _ in 0..delta_y.unsigned_abs() {
        session.send_pointer(coordinate, input.button_mask | vertical_mask)?;
        session.send_pointer(coordinate, input.button_mask)?;
    }
    Ok(())
}

fn send_chord<S: WorkerSession>(
    session: &mut S,
    input: &mut InputState,
    keys: &[KeyboardKey],
) -> Result<(), DesktopError> {
    validate_chord(keys)?;
    let mut pressed = Vec::with_capacity(keys.len());
    for key in keys {
        if let Err(error) = session.send_key(*key, true) {
            for pressed_key in pressed.iter().rev() {
                let _ = session.send_key(*pressed_key, false);
                input.pressed_keys.remove(pressed_key);
            }
            return Err(error.into());
        }
        input.pressed_keys.insert(*key);
        pressed.push(*key);
    }
    for key in pressed.iter().rev() {
        session.send_key(*key, false)?;
        input.pressed_keys.remove(key);
    }
    Ok(())
}

fn send_text<S: WorkerSession>(
    session: &mut S,
    input: &mut InputState,
    text: &str,
) -> Result<(), DesktopError> {
    validate_text(text)?;
    for character in text.chars() {
        let key = match character {
            '\n' | '\r' => KeyboardKey::Enter,
            '\t' => KeyboardKey::Tab,
            value => KeyboardKey::Printable(value),
        };
        session.send_key(key, true)?;
        input.pressed_keys.insert(key);
        match session.send_key(key, false) {
            Ok(()) => {
                input.pressed_keys.remove(&key);
            }
            Err(error) => {
                let _ = session.send_key(key, false);
                input.pressed_keys.remove(&key);
                return Err(error.into());
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn handle_manual_reconnect<S: WorkerSession>(
    settings: &WorkerSettings,
    snapshot: &Arc<Mutex<WorkerSnapshot>>,
    event_tx: &SyncSender<WorkerEvent>,
    event_sequence: &mut u64,
    session: &mut Option<S>,
    input: &mut InputState,
    next_connect: &mut Option<Instant>,
    reconnect_attempt: &mut u32,
    last_manual_reconnect: &mut Option<Instant>,
) -> Result<(), DesktopError> {
    let now = Instant::now();
    if last_manual_reconnect.is_some_and(|last| {
        now.saturating_duration_since(last) < settings.manual_reconnect_interval
    }) {
        return Err(DesktopError::ReconnectRateLimited);
    }
    *last_manual_reconnect = Some(now);
    invalidate_connection(snapshot, event_tx, event_sequence, session, input);
    *reconnect_attempt = reconnect_attempt.saturating_add(1);
    lock_unpoisoned(snapshot).reconnect_attempts = *reconnect_attempt;
    transition(
        snapshot,
        event_tx,
        event_sequence,
        ConnectionState::Reconnecting,
    )?;
    *next_connect = Some(now);
    Ok(())
}

fn invalidate_connection<S>(
    snapshot: &Arc<Mutex<WorkerSnapshot>>,
    event_tx: &SyncSender<WorkerEvent>,
    event_sequence: &mut u64,
    session: &mut Option<S>,
    input: &mut InputState,
) {
    *session = None;
    input.button_mask = 0;
    input.pressed_keys.clear();
    lock_unpoisoned(snapshot).framebuffer_current = false;
    publish_event(
        snapshot,
        event_tx,
        event_sequence,
        DesktopEventKind::FramebufferInvalidated,
    );
}

#[allow(clippy::too_many_arguments)]
fn schedule_reconnect(
    settings: &WorkerSettings,
    snapshot: &Arc<Mutex<WorkerSnapshot>>,
    event_tx: &SyncSender<WorkerEvent>,
    event_sequence: &mut u64,
    next_connect: &mut Option<Instant>,
    reconnect_attempt: &mut u32,
) {
    *reconnect_attempt = reconnect_attempt.saturating_add(1);
    lock_unpoisoned(snapshot).reconnect_attempts = *reconnect_attempt;
    let state = lock_unpoisoned(snapshot).state;
    if state != ConnectionState::Disconnected {
        let _ = transition(
            snapshot,
            event_tx,
            event_sequence,
            ConnectionState::Disconnected,
        );
    }
    let _ = transition(
        snapshot,
        event_tx,
        event_sequence,
        ConnectionState::Reconnecting,
    );
    *next_connect = Some(Instant::now() + reconnect_delay(settings, *reconnect_attempt));
}

fn reconnect_delay(settings: &WorkerSettings, attempt: u32) -> Duration {
    let exponent = attempt.saturating_sub(1).min(31);
    let multiplier = 1_u128 << exponent;
    let minimum_ms = settings.reconnect_min_delay.as_millis();
    let maximum_ms = settings.reconnect_max_delay.as_millis();
    let base_ms = minimum_ms.saturating_mul(multiplier).min(maximum_ms);
    let jitter_bound = base_ms
        .saturating_mul(u128::from(settings.reconnect_jitter_per_mille))
        / 1_000;
    let jitter = if jitter_bound == 0 {
        0
    } else {
        u128::from(attempt.wrapping_mul(1_103_515_245).wrapping_add(12_345))
            % (jitter_bound + 1)
    };
    let delay_ms = base_ms.saturating_add(jitter).min(maximum_ms);
    Duration::from_millis(u64::try_from(delay_ms).unwrap_or(u64::MAX))
}

fn classify_native_error(error: &NativeError) -> WorkerFailureKind {
    match error {
        NativeError::InvalidArgument | NativeError::EmbeddedNul => WorkerFailureKind::Configuration,
        NativeError::Disconnected => WorkerFailureKind::Transport,
        NativeError::FramebufferUnavailable | NativeError::BufferTooSmall => {
            WorkerFailureKind::Protocol
        }
        NativeError::ClipboardUnavailable | NativeError::ClipboardNotUtf8 => {
            WorkerFailureKind::Protocol
        }
        NativeError::AllocationFailed => WorkerFailureKind::Native,
        NativeError::NativeFailure { message }
            if message.contains("protocol initialization failed") =>
        {
            WorkerFailureKind::Authentication
        }
        NativeError::NativeFailure { .. } => WorkerFailureKind::Native,
    }
}

fn record_failure(snapshot: &Arc<Mutex<WorkerSnapshot>>, failure: WorkerFailureKind) {
    lock_unpoisoned(snapshot).last_failure = Some(failure);
}

fn transition(
    snapshot: &Arc<Mutex<WorkerSnapshot>>,
    event_tx: &SyncSender<WorkerEvent>,
    event_sequence: &mut u64,
    next: ConnectionState,
) -> Result<(), DesktopError> {
    {
        let mut current = lock_unpoisoned(snapshot);
        if !current.state.can_transition_to(next) {
            current.fatal_exit = true;
            return Err(DesktopError::Protocol);
        }
        current.state = next;
    }
    publish_event(
        snapshot,
        event_tx,
        event_sequence,
        DesktopEventKind::ConnectionState { state: next },
    );
    Ok(())
}

fn publish_event(
    snapshot: &Arc<Mutex<WorkerSnapshot>>,
    event_tx: &SyncSender<WorkerEvent>,
    event_sequence: &mut u64,
    kind: DesktopEventKind,
) {
    let Some(sequence) = event_sequence.checked_add(1) else {
        lock_unpoisoned(snapshot).fatal_exit = true;
        return;
    };
    *event_sequence = sequence;
    let event = WorkerEvent {
        sequence,
        observed_at: SystemTime::now(),
        kind,
    };
    match event_tx.try_send(event) {
        Ok(()) => {}
        Err(TrySendError::Full(_)) => {
            let mut current = lock_unpoisoned(snapshot);
            current.dropped_events = current.dropped_events.saturating_add(1);
        }
        Err(TrySendError::Disconnected(_)) => {}
    }
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use remote_desktop_core::{Coordinate, DisplayInfo};
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[derive(Clone)]
    struct MockSession {
        mode: Arc<Mutex<MockMode>>,
    }

    enum MockMode {
        Healthy,
        FirstMessageThenStall(bool),
    }

    impl WorkerSession for MockSession {
        fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
            let mut mode = lock_unpoisoned(&self.mode);
            match &mut *mode {
                MockMode::Healthy => Ok(PollOutcome::MessageProcessed),
                MockMode::FirstMessageThenStall(sent) if !*sent => {
                    *sent = true;
                    Ok(PollOutcome::MessageProcessed)
                }
                MockMode::FirstMessageThenStall(_) => {
                    thread::sleep(timeout);
                    Ok(PollOutcome::TimedOut)
                }
            }
        }

        fn request_full_refresh(&mut self) -> Result<(), NativeError> {
            Ok(())
        }

        fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
            Ok(NativeDisplayInfo {
                width: 1_280,
                height: 800,
                revision: 1,
                complete: true,
            })
        }

        fn send_pointer(
            &mut self,
            _coordinate: Coordinate,
            _button_mask: u8,
        ) -> Result<(), NativeError> {
            Ok(())
        }

        fn send_key(&mut self, _key: KeyboardKey, _pressed: bool) -> Result<(), NativeError> {
            Ok(())
        }

        fn send_clipboard(&mut self, _text: &str) -> Result<(), NativeError> {
            Ok(())
        }
    }

    fn native_config() -> NativeClientConfig {
        NativeClientConfig {
            host: "desktop".to_owned(),
            port: 5901,
            password: "test-only".to_owned(),
            connect_timeout: Duration::from_secs(1),
            read_timeout: Duration::from_secs(1),
        }
    }

    fn settings() -> WorkerSettings {
        WorkerSettings {
            native: native_config(),
            command_capacity: 4,
            event_capacity: 16,
            poll_interval: Duration::from_millis(1),
            startup_timeout: Duration::from_secs(1),
            reconnect_min_delay: Duration::from_millis(2),
            reconnect_max_delay: Duration::from_millis(20),
            reconnect_jitter_per_mille: 100,
            stable_connection_reset: Duration::from_millis(20),
            manual_reconnect_interval: Duration::from_millis(50),
            stall_probe_after: Duration::from_millis(5),
            stall_confirm_after: Duration::from_millis(5),
        }
    }

    fn wait_for_state(client: &WorkerClient, expected: ConnectionState) {
        let deadline = Instant::now() + Duration::from_secs(1);
        while Instant::now() < deadline {
            if client.snapshot().state == expected {
                return;
            }
            thread::sleep(Duration::from_millis(1));
        }
        panic!("worker did not reach {expected:?}: {:?}", client.snapshot());
    }

    #[test]
    fn settings_reject_zero_capacities_and_invalid_delay_order() {
        let mut candidate = settings();
        candidate.command_capacity = 0;
        assert!(candidate.validate().is_err());

        let mut candidate = settings();
        candidate.reconnect_min_delay = Duration::from_secs(2);
        candidate.reconnect_max_delay = Duration::from_secs(1);
        assert!(candidate.validate().is_err());
    }

    #[test]
    fn worker_connects_accepts_commands_and_joins_shutdown() {
        let worker = DesktopWorker::spawn_with_factory(settings(), || {
            Ok(MockSession {
                mode: Arc::new(Mutex::new(MockMode::Healthy)),
            })
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let display = DisplayInfo::new(1_280, 800, 24, 1, true).expect("display");
        let coordinate = Coordinate::new(10, 10, display).expect("coordinate");
        client
            .submit(WorkerCommand::MovePointer { coordinate })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("executed");
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
        assert_eq!(client.snapshot().state, ConnectionState::Stopped);
    }

    #[test]
    fn transport_failure_reconnects_with_bounded_backoff() {
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_for_factory = Arc::clone(&calls);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            if calls_for_factory.fetch_add(1, Ordering::SeqCst) == 0 {
                Err(NativeError::Disconnected)
            } else {
                Ok(MockSession {
                    mode: Arc::new(Mutex::new(MockMode::Healthy)),
                })
            }
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        assert!(calls.load(Ordering::SeqCst) >= 2);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn authentication_failure_does_not_retry_rapidly() {
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_for_factory = Arc::clone(&calls);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            calls_for_factory.fetch_add(1, Ordering::SeqCst);
            Err::<MockSession, _>(NativeError::NativeFailure {
                message: "VNC protocol initialization failed".to_owned(),
            })
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::AuthenticationFailed);
        thread::sleep(Duration::from_millis(30));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn confirmed_stall_invalidates_and_reconnects() {
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_for_factory = Arc::clone(&calls);
        let modes = Arc::new(Mutex::new(VecDeque::from([
            MockMode::FirstMessageThenStall(false),
            MockMode::Healthy,
        ])));
        let modes_for_factory = Arc::clone(&modes);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            calls_for_factory.fetch_add(1, Ordering::SeqCst);
            let mode = lock_unpoisoned(&modes_for_factory)
                .pop_front()
                .unwrap_or(MockMode::Healthy);
            Ok(MockSession {
                mode: Arc::new(Mutex::new(mode)),
            })
        })
        .expect("worker spawns");
        let client = worker.client();
        let deadline = Instant::now() + Duration::from_secs(1);
        while Instant::now() < deadline && calls.load(Ordering::SeqCst) < 2 {
            thread::sleep(Duration::from_millis(1));
        }
        assert!(calls.load(Ordering::SeqCst) >= 2);
        wait_for_state(&client, ConnectionState::Connected);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn reconnect_delay_is_exponential_jittered_and_bounded() {
        let settings = settings();
        let first = reconnect_delay(&settings, 1);
        let second = reconnect_delay(&settings, 2);
        let far = reconnect_delay(&settings, 30);
        assert!(first >= settings.reconnect_min_delay);
        assert!(second >= settings.reconnect_min_delay * 2);
        assert!(first <= settings.reconnect_max_delay);
        assert!(second <= settings.reconnect_max_delay);
        assert!(far <= settings.reconnect_max_delay);
    }
}
