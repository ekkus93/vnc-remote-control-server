//! Single-session desktop worker lifecycle.
//!
//! The worker owns the native adapter and canonical framebuffer writer on
//! exactly one dedicated thread. API and asynchronous runtime tasks interact
//! only through bounded channels, shared status snapshots, immutable
//! framebuffer snapshots, and bounded screenshot services.

use crate::framebuffer::{
    FramebufferError, FramebufferMetadata, FramebufferSnapshot, FramebufferStore,
};
use crate::input::{InputController, InputSink};
use crate::screenshot::{ScreenshotError, ScreenshotService};
use libvnc_adapter::{
    NativeClient, NativeClientConfig, NativeClipboard, NativeDisplayInfo, NativeError,
    NativeFramebuffer, PollOutcome,
};
use remote_desktop_core::{
    ClipboardSnapshot, ConnectionState, Coordinate, DesktopError, DesktopEventKind, DisplayInfo,
    KeyboardKey, MAX_FRAMEBUFFER_BYTES, WorkerCommand, validate_clipboard,
};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{
    Receiver, RecvTimeoutError, SyncSender, TryRecvError, TrySendError, sync_channel,
};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime};

const WORKER_THREAD_NAME: &str = "vnc-desktop-worker";

/// Native worker timing and capacity configuration.
#[derive(Clone, PartialEq, Eq)]
pub struct WorkerSettings {
    /// Native VNC connection configuration. It contains the password and is
    /// intentionally not `Debug`.
    pub native: NativeClientConfig,
    /// Maximum commands waiting for the native thread.
    pub command_capacity: usize,
    /// Maximum events waiting for the event consumer.
    pub event_capacity: usize,
    /// Maximum canonical RGBA framebuffer allocation.
    pub maximum_framebuffer_bytes: usize,
    /// Maximum native poll duration before command processing resumes.
    pub poll_interval: Duration,
    /// Maximum wait for thread startup acknowledgement.
    pub startup_timeout: Duration,
    /// Initial automatic reconnect delay.
    pub reconnect_min_delay: Duration,
    /// Maximum automatic reconnect delay.
    pub reconnect_max_delay: Duration,
    /// Maximum positive reconnect jitter in per-mille of the base delay.
    pub reconnect_jitter_per_mille: u16,
    /// Connected duration required before reconnect backoff resets.
    pub stable_connection_reset: Duration,
    /// Minimum interval between accepted manual reconnect requests.
    pub manual_reconnect_interval: Duration,
    /// Idle duration before a full-refresh probe is sent.
    pub stall_probe_after: Duration,
    /// Additional duration without a server message after a probe before the
    /// transport is considered stalled.
    pub stall_confirm_after: Duration,
}

impl WorkerSettings {
    /// Validates all settings before a thread is spawned.
    pub fn validate(&self) -> Result<(), DesktopError> {
        if self.native.host.is_empty() || self.native.password.is_empty() || self.native.port == 0 {
            return Err(DesktopError::Configuration(
                "native worker endpoint and credentials must be nonempty".to_owned(),
            ));
        }
        if self.command_capacity == 0 || self.event_capacity == 0 {
            return Err(DesktopError::Configuration(
                "worker channel capacities must be nonzero".to_owned(),
            ));
        }
        if self.maximum_framebuffer_bytes == 0
            || self.maximum_framebuffer_bytes > MAX_FRAMEBUFFER_BYTES
        {
            return Err(DesktopError::Configuration(
                "worker framebuffer limit is invalid".to_owned(),
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

/// Coarse failure category safe for status, events, and metrics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerFailureKind {
    /// Credentials were rejected during VNC protocol initialization.
    Authentication,
    /// Static configuration is invalid and must not be retried.
    Configuration,
    /// The TCP transport failed or disconnected.
    Transport,
    /// A refresh probe exceeded its deadline.
    Timeout,
    /// The remote framebuffer or protocol contract failed.
    Protocol,
    /// Another bounded native adapter operation failed.
    Native,
}

/// Read-only worker status snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerSnapshot {
    /// Current public lifecycle state.
    pub state: ConnectionState,
    /// Worker start time.
    pub started_at: SystemTime,
    /// Most recent successful connection time.
    pub connected_at: Option<SystemTime>,
    /// Most recent processed server message time.
    pub last_message_at: Option<SystemTime>,
    /// Consecutive reconnect attempts.
    pub reconnect_attempts: u32,
    /// Last bounded failure category.
    pub last_failure: Option<WorkerFailureKind>,
    /// Current coherent process-local framebuffer revision, when available.
    pub framebuffer_revision: Option<u64>,
    /// Commands rejected because the bounded queue was full.
    pub rejected_commands: u64,
    /// Events dropped because the bounded event queue was full.
    pub dropped_events: u64,
    /// Whether the worker exited without an orderly shutdown command.
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

/// Cloneable bounded command, status, and framebuffer-read handle.
#[derive(Clone)]
pub struct WorkerClient {
    commands: SyncSender<CommandEnvelope>,
    snapshot: Arc<Mutex<WorkerSnapshot>>,
    framebuffer: FramebufferStore,
    clipboard: Arc<Mutex<Option<ClipboardSnapshot>>>,
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
            command,
            completion: completion_tx,
        };
        match self.commands.try_send(envelope) {
            Ok(()) => Ok(CommandTicket {
                id,
                completion: completion_rx,
            }),
            Err(TrySendError::Full(_)) => {
                let mut current = lock_unpoisoned(&self.snapshot);
                current.rejected_commands = current.rejected_commands.saturating_add(1);
                Err(DesktopError::CommandQueueFull)
            }
            Err(TrySendError::Disconnected(_)) => Err(DesktopError::WorkerUnavailable),
        }
    }

    /// Returns one coherent status snapshot.
    pub fn snapshot(&self) -> WorkerSnapshot {
        lock_unpoisoned(&self.snapshot).clone()
    }

    /// Returns coherent framebuffer metadata without copying pixels.
    pub fn framebuffer_metadata(&self) -> FramebufferMetadata {
        self.framebuffer.metadata()
    }

    /// Returns one immutable complete current framebuffer snapshot.
    pub fn framebuffer_snapshot(&self) -> Result<FramebufferSnapshot, FramebufferError> {
        self.framebuffer.current_snapshot()
    }

    /// Returns the last valid inbound clipboard snapshot.
    pub fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {
        lock_unpoisoned(&self.clipboard)
            .clone()
            .ok_or(DesktopError::ClipboardUnavailable)
    }

    /// Creates a bounded screenshot service over the worker-owned framebuffer.
    pub fn screenshot_service(
        &self,
        process_instance: &str,
        maximum_concurrent_encodes: usize,
        encode_timeout: Duration,
    ) -> Result<ScreenshotService, ScreenshotError> {
        ScreenshotService::new(
            self.framebuffer.clone(),
            process_instance,
            maximum_concurrent_encodes,
            encode_timeout,
        )
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
        let startup_timeout = settings.startup_timeout;
        let framebuffer = FramebufferStore::new(settings.maximum_framebuffer_bytes)?;
        let thread_framebuffer = framebuffer.clone();
        let clipboard = Arc::new(Mutex::new(None));
        let thread_clipboard = Arc::clone(&clipboard);
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
                },
                events: WorkerEvents { receiver: event_rx },
                join: Some(join),
            }),
            Err(RecvTimeoutError::Timeout) => {
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
        if let Ok(ticket) = self.client.submit(WorkerCommand::Shutdown) {
            let _ = ticket.wait(Duration::from_secs(2));
        }
        let _ = self.join_worker();
    }
}

struct CommandEnvelope {
    command: WorkerCommand,
    completion: SyncSender<Result<(), DesktopError>>,
}

impl CommandEnvelope {
    fn shutdown_without_waiter() -> Self {
        let (completion, _receiver) = sync_channel(1);
        Self {
            command: WorkerCommand::Shutdown,
            completion,
        }
    }
}

trait WorkerSession {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError>;
    fn request_full_refresh(&mut self) -> Result<(), NativeError>;
    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError>;
    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError>;
    fn clipboard(&self) -> Result<NativeClipboard, NativeError>;
    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError>;
    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError>;
    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError>;
}

impl WorkerSession for NativeClient {
    fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
        NativeClient::poll(self, timeout)
    }

    fn request_full_refresh(&mut self) -> Result<(), NativeError> {
        NativeClient::request_full_refresh(self)
    }

    fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
        NativeClient::display_info(self)
    }

    fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
        NativeClient::framebuffer(self)
    }

    fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
        NativeClient::clipboard(self)
    }

    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        NativeClient::send_pointer(self, coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        NativeClient::send_key(self, key, pressed)
    }

    fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
        NativeClient::send_clipboard(self, text)
    }
}

impl<T: WorkerSession> InputSink for T {
    fn send_pointer(&mut self, coordinate: Coordinate, button_mask: u8) -> Result<(), NativeError> {
        WorkerSession::send_pointer(self, coordinate, button_mask)
    }

    fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
        WorkerSession::send_key(self, key, pressed)
    }
}

struct LoopState<'a, S> {
    settings: &'a WorkerSettings,
    snapshot: &'a Arc<Mutex<WorkerSnapshot>>,
    events: &'a SyncSender<WorkerEvent>,
    framebuffer: FramebufferStore,
    clipboard: &'a Arc<Mutex<Option<ClipboardSnapshot>>>,
    event_sequence: u64,
    session: Option<S>,
    last_native_revision: Option<u64>,
    last_native_clipboard_revision: Option<u64>,
    clipboard_revision: u64,
    clipboard_decode_failed: bool,
    input: InputController,
    next_connect: Option<Instant>,
    reconnect_attempt: u32,
    connected_since: Option<Instant>,
    last_message: Instant,
    probe_sent: Option<Instant>,
    last_manual_reconnect: Option<Instant>,
}

impl<S: WorkerSession> LoopState<'_, S> {
    fn transition(&mut self, next: ConnectionState) -> Result<(), DesktopError> {
        {
            let mut current = lock_unpoisoned(self.snapshot);
            if !current.state.can_transition_to(next) {
                current.fatal_exit = true;
                return Err(DesktopError::Protocol);
            }
            current.state = next;
        }
        self.publish(DesktopEventKind::ConnectionState { state: next });
        Ok(())
    }

    fn publish(&mut self, kind: DesktopEventKind) {
        let Some(sequence) = self.event_sequence.checked_add(1) else {
            lock_unpoisoned(self.snapshot).fatal_exit = true;
            return;
        };
        self.event_sequence = sequence;
        let event = WorkerEvent {
            sequence,
            observed_at: SystemTime::now(),
            kind,
        };
        match self.events.try_send(event) {
            Ok(()) => {}
            Err(TrySendError::Full(_)) => {
                let mut current = lock_unpoisoned(self.snapshot);
                current.dropped_events = current.dropped_events.saturating_add(1);
            }
            Err(TrySendError::Disconnected(_)) => {}
        }
    }

    fn record_failure(&self, failure: WorkerFailureKind) {
        lock_unpoisoned(self.snapshot).last_failure = Some(failure);
    }

    fn begin_connect(&mut self) -> Result<(), DesktopError> {
        let state = if self.reconnect_attempt == 0 {
            ConnectionState::Connecting
        } else {
            ConnectionState::Reconnecting
        };
        self.transition(state)
    }

    fn connected_message(&mut self, display: NativeDisplayInfo) -> Result<(), DesktopError> {
        self.last_message = Instant::now();
        self.probe_sent = None;
        lock_unpoisoned(self.snapshot).last_message_at = Some(SystemTime::now());

        if display.complete && self.last_native_revision != Some(display.revision) {
            let native = self
                .session
                .as_ref()
                .ok_or(DesktopError::WorkerUnavailable)?
                .framebuffer()?;
            validate_native_frame(display, &native)?;
            let revision =
                self.framebuffer
                    .replace_native_rgbx(native.width, native.height, &native.bytes)?;
            self.last_native_revision = Some(native.revision);
            lock_unpoisoned(self.snapshot).framebuffer_revision = Some(revision);
            self.publish(DesktopEventKind::FramebufferRevision { revision });
        }

        if display.complete
            && self.last_native_revision == Some(display.revision)
            && lock_unpoisoned(self.snapshot).state != ConnectionState::Connected
        {
            self.transition(ConnectionState::Connected)?;
            let mut current = lock_unpoisoned(self.snapshot);
            current.connected_at = Some(SystemTime::now());
            current.last_failure = None;
            self.connected_since = Some(Instant::now());
        }
        self.refresh_clipboard()?;

        if self.connected_since.is_some_and(|since| {
            Instant::now().saturating_duration_since(since) >= self.settings.stable_connection_reset
        }) {
            self.reconnect_attempt = 0;
            lock_unpoisoned(self.snapshot).reconnect_attempts = 0;
        }
        Ok(())
    }

    fn refresh_clipboard(&mut self) -> Result<(), DesktopError> {
        let clipboard = self
            .session
            .as_ref()
            .ok_or(DesktopError::WorkerUnavailable)?
            .clipboard();
        match clipboard {
            Ok(native) if self.last_native_clipboard_revision == Some(native.revision) => Ok(()),
            Ok(native) => {
                self.last_native_clipboard_revision = Some(native.revision);
                self.clipboard_decode_failed = false;
                if validate_clipboard(&native.text).is_err() {
                    self.record_failure(WorkerFailureKind::Protocol);
                    self.publish(DesktopEventKind::ProtocolError);
                    return Ok(());
                }
                let revision = self
                    .clipboard_revision
                    .checked_add(1)
                    .ok_or(DesktopError::Protocol)?;
                self.clipboard_revision = revision;
                *lock_unpoisoned(self.clipboard) = Some(ClipboardSnapshot {
                    text: Arc::from(native.text),
                    revision,
                    updated_at: SystemTime::now(),
                });
                self.publish(DesktopEventKind::ClipboardRevision { revision });
                Ok(())
            }
            Err(NativeError::ClipboardUnavailable) => Ok(()),
            Err(NativeError::ClipboardNotUtf8) => {
                if !self.clipboard_decode_failed {
                    self.clipboard_decode_failed = true;
                    self.record_failure(WorkerFailureKind::Protocol);
                    self.publish(DesktopEventKind::ProtocolError);
                }
                Ok(())
            }
            Err(error) => Err(error.into()),
        }
    }

    fn release_input(&mut self) {
        if let Some(session) = self.session.as_mut() {
            self.input.release_all(session);
        } else {
            self.input.clear();
        }
    }

    fn invalidate(&mut self) {
        self.release_input();
        self.session = None;
        self.last_native_revision = None;
        self.last_native_clipboard_revision = None;
        self.clipboard_decode_failed = false;
        let store_changed = self.framebuffer.invalidate();
        let had_frame = lock_unpoisoned(self.snapshot)
            .framebuffer_revision
            .take()
            .is_some();
        if store_changed || had_frame {
            self.publish(DesktopEventKind::FramebufferInvalidated);
        }
        self.connected_since = None;
        self.probe_sent = None;
    }

    fn schedule_reconnect(&mut self) {
        self.reconnect_attempt = self.reconnect_attempt.saturating_add(1);
        lock_unpoisoned(self.snapshot).reconnect_attempts = self.reconnect_attempt;
        if lock_unpoisoned(self.snapshot).state != ConnectionState::Disconnected {
            let _ = self.transition(ConnectionState::Disconnected);
        }
        let _ = self.transition(ConnectionState::Reconnecting);
        self.next_connect =
            Some(Instant::now() + reconnect_delay(self.settings, self.reconnect_attempt));
    }

    fn manual_reconnect(&mut self) -> Result<(), DesktopError> {
        let now = Instant::now();
        if self.last_manual_reconnect.is_some_and(|last| {
            now.saturating_duration_since(last) < self.settings.manual_reconnect_interval
        }) {
            return Err(DesktopError::ReconnectRateLimited);
        }
        let state = lock_unpoisoned(self.snapshot).state;
        if matches!(
            state,
            ConnectionState::Starting | ConnectionState::Connecting
        ) {
            return Err(DesktopError::WorkerUnavailable);
        }
        self.last_manual_reconnect = Some(now);
        self.invalidate();
        self.reconnect_attempt = self.reconnect_attempt.saturating_add(1);
        lock_unpoisoned(self.snapshot).reconnect_attempts = self.reconnect_attempt;
        self.transition(ConnectionState::Reconnecting)?;
        self.next_connect = Some(now);
        Ok(())
    }

    fn current_display(&self) -> Result<DisplayInfo, DesktopError> {
        if self.session.is_none() {
            return Err(DesktopError::WorkerUnavailable);
        }
        Ok(self.framebuffer.current_snapshot()?.display_info())
    }

    fn execute(&mut self, command: WorkerCommand) -> Result<(), DesktopError> {
        match command {
            WorkerCommand::MovePointer { coordinate } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.move_pointer(session, coordinate, display)
            }
            WorkerCommand::SetButton {
                coordinate,
                button,
                pressed,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .set_button(session, coordinate, display, button, pressed)
            }
            WorkerCommand::Click { coordinate, button } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.click(session, coordinate, display, button)
            }
            WorkerCommand::DoubleClick {
                coordinate,
                button,
                interval_ms,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .double_click(session, coordinate, display, button, interval_ms)
            }
            WorkerCommand::Scroll {
                coordinate,
                delta_x,
                delta_y,
            } => {
                let display = self.current_display()?;
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input
                    .scroll(session, coordinate, display, delta_x, delta_y)
            }
            WorkerCommand::SetKey { key, pressed } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.set_key(session, key, pressed)
            }
            WorkerCommand::Chord { keys } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.chord(session, &keys)
            }
            WorkerCommand::SetClipboard { text } => {
                validate_clipboard(&text)?;
                self.session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?
                    .send_clipboard(&text)
                    .map_err(DesktopError::from)
            }
            WorkerCommand::RequestFullRefresh => self
                .session
                .as_mut()
                .ok_or(DesktopError::WorkerUnavailable)?
                .request_full_refresh()
                .map_err(DesktopError::from),
            WorkerCommand::TypeText { text } => {
                let session = self
                    .session
                    .as_mut()
                    .ok_or(DesktopError::WorkerUnavailable)?;
                self.input.type_text(session, &text).map(|_| ())
            }
            WorkerCommand::Reconnect | WorkerCommand::Shutdown => Err(DesktopError::Protocol),
        }
    }

    fn poll(&mut self) -> Result<(), DesktopError> {
        let outcome = self
            .session
            .as_mut()
            .ok_or(DesktopError::WorkerUnavailable)?
            .poll(self.settings.poll_interval);
        match outcome {
            Ok(PollOutcome::MessageProcessed) => {
                let display = self
                    .session
                    .as_ref()
                    .ok_or(DesktopError::WorkerUnavailable)?
                    .display_info()?;
                if self.connected_message(display).is_err() {
                    self.record_failure(WorkerFailureKind::Protocol);
                    self.invalidate();
                    self.schedule_reconnect();
                }
                Ok(())
            }
            Ok(PollOutcome::TimedOut) => {
                let now = Instant::now();
                let idle = now.saturating_duration_since(self.last_message);
                if self.probe_sent.is_none() && idle >= self.settings.stall_probe_after {
                    self.session
                        .as_mut()
                        .ok_or(DesktopError::WorkerUnavailable)?
                        .request_full_refresh()?;
                    self.probe_sent = Some(now);
                } else if self.probe_sent.is_some_and(|sent| {
                    now.saturating_duration_since(sent) >= self.settings.stall_confirm_after
                }) {
                    self.record_failure(WorkerFailureKind::Timeout);
                    self.transition(ConnectionState::Degraded)?;
                    self.invalidate();
                    self.schedule_reconnect();
                }
                Ok(())
            }
            Err(error) => {
                self.record_failure(classify_native_error(&error));
                self.invalidate();
                self.schedule_reconnect();
                Ok(())
            }
        }
    }
}

struct WorkerChannels {
    commands: Receiver<CommandEnvelope>,
    events: SyncSender<WorkerEvent>,
    startup: SyncSender<()>,
}

fn run_worker<F, S>(
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
    } = channels;
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
        if state.session.is_none()
            && state
                .next_connect
                .is_some_and(|deadline| Instant::now() >= deadline)
        {
            if state.begin_connect().is_err() {
                break;
            }
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

        match commands.try_recv() {
            Ok(envelope) => {
                let result = match envelope.command {
                    WorkerCommand::Shutdown => {
                        orderly_shutdown = true;
                        Ok(())
                    }
                    WorkerCommand::Reconnect => state.manual_reconnect(),
                    command => state.execute(command),
                };
                let _ = envelope.completion.send(result);
                if orderly_shutdown {
                    break;
                }
                continue;
            }
            Err(TryRecvError::Disconnected) => break,
            Err(TryRecvError::Empty) => {}
        }

        if state.session.is_some() {
            if state.poll().is_err() {
                break;
            }
        } else {
            thread::sleep(settings.poll_interval.min(Duration::from_millis(50)));
        }
    }

    state.invalidate();
    let _ = state.transition(ConnectionState::Stopped);
    if !orderly_shutdown {
        lock_unpoisoned(&snapshot).fatal_exit = true;
    }
}

fn validate_native_frame(
    display: NativeDisplayInfo,
    native: &NativeFramebuffer,
) -> Result<(), DesktopError> {
    if !display.complete
        || native.width != display.width
        || native.height != display.height
        || native.revision != display.revision
    {
        return Err(DesktopError::Protocol);
    }
    Ok(())
}

fn reconnect_delay(settings: &WorkerSettings, attempt: u32) -> Duration {
    let exponent = attempt.saturating_sub(1).min(31);
    let multiplier = 1_u128 << exponent;
    let minimum_ms = settings.reconnect_min_delay.as_millis();
    let maximum_ms = settings.reconnect_max_delay.as_millis();
    let base_ms = minimum_ms.saturating_mul(multiplier).min(maximum_ms);
    let jitter_bound =
        base_ms.saturating_mul(u128::from(settings.reconnect_jitter_per_mille)) / 1_000;
    let jitter = if jitter_bound == 0 {
        0
    } else {
        u128::from(attempt.wrapping_mul(1_103_515_245).wrapping_add(12_345)) % (jitter_bound + 1)
    };
    let delay_ms = base_ms.saturating_add(jitter).min(maximum_ms);
    Duration::from_millis(u64::try_from(delay_ms).unwrap_or(u64::MAX))
}

fn classify_native_error(error: &NativeError) -> WorkerFailureKind {
    match error {
        NativeError::InvalidArgument | NativeError::EmbeddedNul => WorkerFailureKind::Configuration,
        NativeError::Disconnected => WorkerFailureKind::Transport,
        NativeError::FramebufferUnavailable
        | NativeError::BufferTooSmall
        | NativeError::ClipboardUnavailable
        | NativeError::ClipboardNotUtf8 => WorkerFailureKind::Protocol,
        NativeError::AllocationFailed => WorkerFailureKind::Native,
        NativeError::NativeFailure { message }
            if message.contains("protocol initialization failed") =>
        {
            WorkerFailureKind::Authentication
        }
        NativeError::NativeFailure { .. } => WorkerFailureKind::Native,
    }
}

fn lock_unpoisoned<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use remote_desktop_core::MouseButton;
    use std::collections::VecDeque;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct MockSession {
        mode: Arc<Mutex<MockMode>>,
    }

    enum MockMode {
        Healthy,
        FirstMessageThenStall(bool),
    }

    impl WorkerSession for MockSession {
        fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
            thread::sleep(timeout);
            let mut mode = lock_unpoisoned(&self.mode);
            match &mut *mode {
                MockMode::Healthy => Ok(PollOutcome::MessageProcessed),
                MockMode::FirstMessageThenStall(sent) if !*sent => {
                    *sent = true;
                    Ok(PollOutcome::MessageProcessed)
                }
                MockMode::FirstMessageThenStall(_) => Ok(PollOutcome::TimedOut),
            }
        }

        fn request_full_refresh(&mut self) -> Result<(), NativeError> {
            Ok(())
        }

        fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
            Ok(NativeDisplayInfo {
                width: 2,
                height: 2,
                revision: 1,
                complete: true,
            })
        }

        fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
            Err(NativeError::ClipboardUnavailable)
        }

        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
            Ok(NativeFramebuffer {
                width: 2,
                height: 2,
                revision: 1,
                bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
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

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum InputEvent {
        Pointer(Coordinate, u8),
        Key(KeyboardKey, bool),
        Clipboard(String),
    }

    struct RecordingSession {
        events: Arc<Mutex<Vec<InputEvent>>>,
        input_calls: usize,
        fail_on_input_call: Option<usize>,
        clipboard: Option<NativeClipboard>,
    }

    impl RecordingSession {
        fn new(events: Arc<Mutex<Vec<InputEvent>>>, fail_on_input_call: Option<usize>) -> Self {
            Self {
                events,
                input_calls: 0,
                fail_on_input_call,
                clipboard: None,
            }
        }

        fn with_clipboard(events: Arc<Mutex<Vec<InputEvent>>>, text: &str, revision: u64) -> Self {
            Self {
                events,
                input_calls: 0,
                fail_on_input_call: None,
                clipboard: Some(NativeClipboard {
                    text: text.to_owned(),
                    revision,
                }),
            }
        }

        fn record(&mut self, event: InputEvent) -> Result<(), NativeError> {
            self.input_calls += 1;
            if self.fail_on_input_call == Some(self.input_calls) {
                return Err(NativeError::NativeFailure {
                    message: "test-only worker input failure".to_owned(),
                });
            }
            lock_unpoisoned(&self.events).push(event);
            Ok(())
        }
    }

    impl WorkerSession for RecordingSession {
        fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
            thread::sleep(timeout);
            Ok(PollOutcome::MessageProcessed)
        }

        fn request_full_refresh(&mut self) -> Result<(), NativeError> {
            Ok(())
        }

        fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
            Ok(NativeDisplayInfo {
                width: 2,
                height: 2,
                revision: 1,
                complete: true,
            })
        }

        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
            Ok(NativeFramebuffer {
                width: 2,
                height: 2,
                revision: 1,
                bytes: vec![1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 10, 11, 12, 0],
            })
        }

        fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
            self.clipboard
                .clone()
                .ok_or(NativeError::ClipboardUnavailable)
        }

        fn send_pointer(
            &mut self,
            coordinate: Coordinate,
            button_mask: u8,
        ) -> Result<(), NativeError> {
            self.record(InputEvent::Pointer(coordinate, button_mask))
        }

        fn send_key(&mut self, key: KeyboardKey, pressed: bool) -> Result<(), NativeError> {
            self.record(InputEvent::Key(key, pressed))
        }

        fn send_clipboard(&mut self, text: &str) -> Result<(), NativeError> {
            self.record(InputEvent::Clipboard(text.to_owned()))
        }
    }

    fn settings() -> WorkerSettings {
        WorkerSettings {
            native: NativeClientConfig {
                host: "desktop".to_owned(),
                port: 5901,
                password: "test-only".to_owned(),
                connect_timeout: Duration::from_secs(1),
                read_timeout: Duration::from_secs(1),
            },
            command_capacity: 4,
            event_capacity: 16,
            maximum_framebuffer_bytes: MAX_FRAMEBUFFER_BYTES,
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

    fn healthy_session() -> MockSession {
        MockSession {
            mode: Arc::new(Mutex::new(MockMode::Healthy)),
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
    fn settings_reject_zero_capacities_invalid_frame_limit_and_delay_order() {
        let mut candidate = settings();
        candidate.command_capacity = 0;
        assert!(candidate.validate().is_err());

        let mut candidate = settings();
        candidate.maximum_framebuffer_bytes = 0;
        assert!(candidate.validate().is_err());

        let mut candidate = settings();
        candidate.reconnect_min_delay = Duration::from_secs(2);
        candidate.reconnect_max_delay = Duration::from_secs(1);
        assert!(candidate.validate().is_err());
    }

    #[test]
    fn worker_commits_frame_accepts_commands_and_joins_shutdown() {
        let worker = DesktopWorker::spawn_with_factory(settings(), || Ok(healthy_session()))
            .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let snapshot = client.framebuffer_snapshot().expect("current frame");
        assert_eq!(snapshot.width(), 2);
        assert_eq!(snapshot.height(), 2);
        assert_eq!(snapshot.revision(), 1);
        assert_eq!(&snapshot.rgba()[0..4], &[1, 2, 3, 255]);

        let display = snapshot.display_info();
        let coordinate = Coordinate::new(1, 1, display).expect("coordinate");
        client
            .submit(WorkerCommand::MovePointer { coordinate })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("executed");
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
        assert_eq!(client.snapshot().state, ConnectionState::Stopped);
        assert_eq!(
            client.framebuffer_snapshot().err(),
            Some(FramebufferError::Stale)
        );
    }

    #[test]
    fn worker_routes_atomic_input_through_single_owned_session() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let point = Coordinate { x: 1, y: 1 };

        for command in [
            WorkerCommand::SetButton {
                coordinate: point,
                button: MouseButton::Right,
                pressed: true,
            },
            WorkerCommand::Click {
                coordinate: point,
                button: MouseButton::Left,
            },
            WorkerCommand::Scroll {
                coordinate: point,
                delta_x: 0,
                delta_y: 1,
            },
            WorkerCommand::Chord {
                keys: vec![
                    KeyboardKey::CtrlLeft,
                    KeyboardKey::AltLeft,
                    KeyboardKey::Printable('T'),
                ],
            },
            WorkerCommand::SetButton {
                coordinate: point,
                button: MouseButton::Right,
                pressed: false,
            },
        ] {
            client
                .submit(command)
                .expect("accepted")
                .wait(Duration::from_secs(1))
                .expect("executed");
        }

        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 5),
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 4),
                InputEvent::Pointer(point, 12),
                InputEvent::Pointer(point, 4),
                InputEvent::Key(KeyboardKey::CtrlLeft, true),
                InputEvent::Key(KeyboardKey::AltLeft, true),
                InputEvent::Key(KeyboardKey::Printable('T'), true),
                InputEvent::Key(KeyboardKey::Printable('T'), false),
                InputEvent::Key(KeyboardKey::AltLeft, false),
                InputEvent::Key(KeyboardKey::CtrlLeft, false),
                InputEvent::Pointer(point, 0),
            ]
        );
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn worker_routes_preflighted_text_and_clipboard_without_payload_loss() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);

        client
            .submit(WorkerCommand::TypeText {
                text: "A\n".to_owned(),
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("text executed");
        client
            .submit(WorkerCommand::SetClipboard {
                text: "clipboard value".to_owned(),
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("clipboard sent");

        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Key(KeyboardKey::Printable('A'), true),
                InputEvent::Key(KeyboardKey::Printable('A'), false),
                InputEvent::Key(KeyboardKey::Enter, true),
                InputEvent::Key(KeyboardKey::Enter, false),
                InputEvent::Clipboard("clipboard value".to_owned()),
            ]
        );

        lock_unpoisoned(&events).clear();
        client
            .submit(WorkerCommand::TypeText {
                text: "ok☃".to_owned(),
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect_err("unsupported text rejected");
        client
            .submit(WorkerCommand::SetClipboard {
                text: "a\0b".to_owned(),
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect_err("NUL clipboard rejected");
        assert!(lock_unpoisoned(&events).is_empty());

        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn worker_publishes_last_valid_inbound_clipboard_snapshot() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::with_clipboard(
                Arc::clone(&factory_events),
                "from desktop",
                7,
            ))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);

        let deadline = Instant::now() + Duration::from_secs(1);
        let clipboard = loop {
            match client.clipboard_snapshot() {
                Ok(snapshot) => break snapshot,
                Err(DesktopError::ClipboardUnavailable) if Instant::now() < deadline => {
                    thread::sleep(Duration::from_millis(1));
                }
                other => panic!("clipboard snapshot unavailable: {other:?}"),
            }
        };
        assert_eq!(clipboard.text.as_ref(), "from desktop");
        assert_eq!(clipboard.revision, 1);

        let mut saw_revision = false;
        while let Ok(event) = worker.events().recv_timeout(Duration::from_millis(20)) {
            if matches!(
                event.kind,
                DesktopEventKind::ClipboardRevision { revision: 1 }
            ) {
                saw_revision = true;
                break;
            }
        }
        assert!(saw_revision);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn worker_rejects_invalid_coordinate_before_native_mutation() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);

        let error = client
            .submit(WorkerCommand::MovePointer {
                coordinate: Coordinate { x: 2, y: 1 },
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect_err("out-of-range coordinate must fail");
        assert!(matches!(error, DesktopError::InvalidCoordinate { .. }));
        assert!(lock_unpoisoned(&events).is_empty());
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn worker_returns_partial_input_failure_after_release_retry() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), Some(3)))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let point = Coordinate { x: 1, y: 1 };

        client
            .submit(WorkerCommand::Click {
                coordinate: point,
                button: MouseButton::Left,
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect_err("native release failure must reach caller");
        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Pointer(point, 0),
                InputEvent::Pointer(point, 1),
                InputEvent::Pointer(point, 0),
            ]
        );
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn shutdown_releases_tracked_buttons_and_keys() {
        let events = Arc::new(Mutex::new(Vec::new()));
        let factory_events = Arc::clone(&events);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            Ok(RecordingSession::new(Arc::clone(&factory_events), None))
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        let point = Coordinate { x: 1, y: 1 };

        client
            .submit(WorkerCommand::SetButton {
                coordinate: point,
                button: MouseButton::Left,
                pressed: true,
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("button down");
        client
            .submit(WorkerCommand::SetKey {
                key: KeyboardKey::CtrlLeft,
                pressed: true,
            })
            .expect("accepted")
            .wait(Duration::from_secs(1))
            .expect("key down");
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");

        assert_eq!(
            *lock_unpoisoned(&events),
            vec![
                InputEvent::Pointer(point, 1),
                InputEvent::Key(KeyboardKey::CtrlLeft, true),
                InputEvent::Pointer(point, 0),
                InputEvent::Key(KeyboardKey::CtrlLeft, false),
            ]
        );
    }

    #[test]
    fn transport_failure_reconnects_with_bounded_backoff() {
        let calls = Arc::new(AtomicUsize::new(0));
        let calls_for_factory = Arc::clone(&calls);
        let worker = DesktopWorker::spawn_with_factory(settings(), move || {
            if calls_for_factory.fetch_add(1, Ordering::SeqCst) == 0 {
                Err(NativeError::Disconnected)
            } else {
                Ok(healthy_session())
            }
        })
        .expect("worker spawns");
        let client = worker.client();
        wait_for_state(&client, ConnectionState::Connected);
        assert!(calls.load(Ordering::SeqCst) >= 2);
        assert_eq!(client.framebuffer_snapshot().expect("frame").revision(), 1);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn authentication_failure_waits_for_manual_reconnect() {
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
        assert_eq!(
            client.framebuffer_snapshot().err(),
            Some(FramebufferError::Unavailable)
        );
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn confirmed_stall_invalidates_reconnects_and_advances_revision() {
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
        assert_eq!(client.framebuffer_snapshot().expect("frame").revision(), 2);
        worker
            .shutdown(Duration::from_secs(1))
            .expect("worker joins");
    }

    #[test]
    fn mismatched_native_frame_never_reaches_connected() {
        struct MismatchedSession;

        impl WorkerSession for MismatchedSession {
            fn poll(&mut self, timeout: Duration) -> Result<PollOutcome, NativeError> {
                thread::sleep(timeout);
                Ok(PollOutcome::MessageProcessed)
            }

            fn request_full_refresh(&mut self) -> Result<(), NativeError> {
                Ok(())
            }

            fn display_info(&self) -> Result<NativeDisplayInfo, NativeError> {
                Ok(NativeDisplayInfo {
                    width: 2,
                    height: 2,
                    revision: 5,
                    complete: true,
                })
            }

            fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {
                Ok(NativeFramebuffer {
                    width: 2,
                    height: 2,
                    revision: 4,
                    bytes: vec![0; 16],
                })
            }

            fn clipboard(&self) -> Result<NativeClipboard, NativeError> {
                Err(NativeError::ClipboardUnavailable)
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

        let worker = DesktopWorker::spawn_with_factory(settings(), || Ok(MismatchedSession))
            .expect("worker spawns");
        let client = worker.client();
        thread::sleep(Duration::from_millis(30));
        assert_ne!(client.snapshot().state, ConnectionState::Connected);
        assert_eq!(
            client.framebuffer_snapshot().err(),
            Some(FramebufferError::Unavailable)
        );
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
