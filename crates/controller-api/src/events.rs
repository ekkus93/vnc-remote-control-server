//! Authenticated WebSocket event fan-out with bounded per-client buffering.
//!
//! One bridge thread drains the worker's bounded synchronous event queue into a
//! Tokio broadcast channel. Each client has a bounded receiver, a global client
//! permit, heartbeat enforcement, and deterministic slow-client cleanup.

use crate::observability::Metrics;
use crate::worker::{WorkerEvent, WorkerEvents, WorkerFailureKind, WorkerSnapshot};
use axum::extract::ws::{CloseFrame, Message, WebSocket};
use remote_desktop_core::{ConnectionState, DesktopEventKind};
use serde::Serialize;
use std::error::Error;
use std::fmt;
use std::io;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, SyncSender, sync_channel};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::{Notify, OwnedSemaphorePermit, Semaphore, broadcast};
use tokio::time::{self, Instant, MissedTickBehavior};

const EVENT_BRIDGE_POLL_INTERVAL_MS: u64 = 50;
const BASE_PROCESS_SHUTDOWN_MINIMUM_MS: u64 = 500;
const PROCESS_SHUTDOWN_POLL_MULTIPLIER: u64 = 8;
const EVENT_SEQUENCE_EXHAUSTED_CLOSE_REASON: &str = "event sequence exhausted";
const EVENT_TIMESTAMP_INVALID_CLOSE_REASON: &str = "event timestamp invalid";
const UNSUPPORTED_CLIENT_DATA_CLOSE_REASON: &str = "client application data is not supported";
const OVERSIZED_CLIENT_DATA_CLOSE_REASON: &str = "client application message is too large";
/// Maximum inbound WebSocket message size. Control frames remain far below this bound.
pub const WEBSOCKET_MAX_MESSAGE_BYTES: usize = 4096;
/// Maximum inbound WebSocket frame size. Event clients never send application frames.
pub const WEBSOCKET_MAX_FRAME_BYTES: usize = 4096;

/// Poll interval used by the dependency-free bridge stop loop.
pub(crate) const EVENT_BRIDGE_POLL_INTERVAL: Duration =
    Duration::from_millis(EVENT_BRIDGE_POLL_INTERVAL_MS);
/// Minimum accepted total process-cleanup budget, derived from the bridge poll interval.
pub(crate) const MIN_PROCESS_SHUTDOWN_TIMEOUT_MS: u64 = {
    let poll_floor = EVENT_BRIDGE_POLL_INTERVAL_MS * PROCESS_SHUTDOWN_POLL_MULTIPLIER;
    if BASE_PROCESS_SHUTDOWN_MINIMUM_MS > poll_floor {
        BASE_PROCESS_SHUTDOWN_MINIMUM_MS
    } else {
        poll_floor
    }
};
const EVENT_BRIDGE_DROP_TIMEOUT: Duration = Duration::from_secs(2);

struct EventBridgeStartSettings {
    event_capacity: usize,
    maximum_clients: usize,
    ping_interval: Duration,
    idle_timeout: Duration,
    metrics: Metrics,
    drop_timeout: Duration,
}

/// Process-wide WebSocket event transport.
#[derive(Clone)]
pub struct EventHub {
    sender: broadcast::Sender<ServerEvent>,
    sequence: Arc<AtomicU64>,
    sequence_exhausted: Arc<AtomicBool>,
    sequence_exhausted_notify: Arc<Notify>,
    timestamp_invalid: Arc<AtomicBool>,
    timestamp_invalid_notify: Arc<Notify>,
    clients: Arc<Semaphore>,
    metrics: Metrics,
    ping_interval: Duration,
    idle_timeout: Duration,
}

impl EventHub {
    /// Starts the worker-event bridge and returns the transport plus its join handle.
    pub fn start(
        worker_events: WorkerEvents,
        event_capacity: usize,
        maximum_clients: usize,
        ping_interval: Duration,
        idle_timeout: Duration,
        metrics: Metrics,
    ) -> io::Result<(Self, EventBridge)> {
        Self::start_with_hook(
            worker_events,
            EventBridgeStartSettings {
                event_capacity,
                maximum_clients,
                ping_interval,
                idle_timeout,
                metrics,
                drop_timeout: EVENT_BRIDGE_DROP_TIMEOUT,
            },
            || {},
        )
    }

    fn start_with_hook<H>(
        worker_events: WorkerEvents,
        settings: EventBridgeStartSettings,
        before_loop: H,
    ) -> io::Result<(Self, EventBridge)>
    where
        H: FnOnce() + Send + 'static,
    {
        let EventBridgeStartSettings {
            event_capacity,
            maximum_clients,
            ping_interval,
            idle_timeout,
            metrics,
            drop_timeout,
        } = settings;
        let hub = Self::detached(
            event_capacity,
            maximum_clients,
            ping_interval,
            idle_timeout,
            metrics,
        );
        let bridge_hub = hub.clone();
        let stop_requested = Arc::new(AtomicBool::new(false));
        let thread_stop_requested = Arc::clone(&stop_requested);
        let (exited_tx, exited_rx) = sync_channel(1);
        let dispatcher = tracing::dispatcher::get_default(Clone::clone);
        let join = thread::Builder::new()
            .name("worker-event-bridge".to_owned())
            .spawn(move || {
                tracing::dispatcher::with_default(&dispatcher, || {
                    let _exit_signal = EventBridgeExitSignal::new(exited_tx);
                    let span = tracing::info_span!("worker_event_bridge");
                    let _entered = span.enter();
                    before_loop();
                    loop {
                        if thread_stop_requested.load(Ordering::Acquire) {
                            break;
                        }
                        match worker_events.recv_timeout(EVENT_BRIDGE_POLL_INTERVAL) {
                            Ok(event) => bridge_hub.publish_worker(event),
                            Err(RecvTimeoutError::Timeout) => {}
                            Err(RecvTimeoutError::Disconnected) => break,
                        }
                    }
                    tracing::info!("worker_event_bridge_stopped");
                })
            })?;
        Ok((
            hub,
            EventBridge {
                join: Some(join),
                stop_requested,
                exited: Some(exited_rx),
                drop_timeout,
            },
        ))
    }

    /// Constructs a transport without a bridge for deterministic router tests.
    pub(crate) fn detached(
        event_capacity: usize,
        maximum_clients: usize,
        ping_interval: Duration,
        idle_timeout: Duration,
        metrics: Metrics,
    ) -> Self {
        assert!(event_capacity > 0, "event capacity must be nonzero");
        assert!(maximum_clients > 0, "client capacity must be nonzero");
        assert!(!ping_interval.is_zero(), "ping interval must be nonzero");
        assert!(!idle_timeout.is_zero(), "idle timeout must be nonzero");
        let (sender, _) = broadcast::channel(event_capacity);
        Self {
            sender,
            sequence: Arc::new(AtomicU64::new(1)),
            sequence_exhausted: Arc::new(AtomicBool::new(false)),
            sequence_exhausted_notify: Arc::new(Notify::new()),
            timestamp_invalid: Arc::new(AtomicBool::new(false)),
            timestamp_invalid_notify: Arc::new(Notify::new()),
            clients: Arc::new(Semaphore::new(maximum_clients)),
            metrics,
            ping_interval,
            idle_timeout,
        }
    }

    #[cfg(test)]
    pub(crate) fn force_sequence_for_test(&self, sequence: u64) {
        self.sequence.store(sequence, Ordering::Release);
        self.sequence_exhausted.store(false, Ordering::Release);
    }

    /// Acquires one bounded client slot and subscribes to future events.
    pub fn subscribe(&self) -> Result<EventSubscription, WebSocketCapacityError> {
        let permit = Arc::clone(&self.clients).try_acquire_owned().map_err(|_| {
            self.metrics.websocket_rejected();
            WebSocketCapacityError
        })?;
        self.metrics.websocket_opened();
        Ok(EventSubscription {
            receiver: self.sender.subscribe(),
            _permit: ClientPermit {
                _permit: permit,
                metrics: self.metrics.clone(),
            },
        })
    }

    /// Creates a payload-free initial status snapshot for one authenticated client.
    pub fn snapshot_event(
        &self,
        snapshot: &WorkerSnapshot,
        clipboard_revision: Option<u64>,
    ) -> Result<ServerEvent, EventSequenceError> {
        self.event(
            SystemTime::now(),
            EventPayload::Snapshot {
                state: connection_state_name(snapshot.state),
                framebuffer_revision: snapshot.framebuffer_revision,
                clipboard_revision,
                reconnect_attempts: snapshot.reconnect_attempts,
                last_failure: snapshot.last_failure.map(worker_failure_name),
                rejected_commands: snapshot.rejected_commands,
                dropped_events: snapshot.dropped_events,
                fatal_exit: snapshot.fatal_exit,
            },
        )
    }

    /// Runs one authenticated WebSocket until client closure or a bounded failure.
    pub async fn serve(
        &self,
        socket: WebSocket,
        subscription: EventSubscription,
        initial: ServerEvent,
    ) {
        self.serve_socket(
            EventSocket::Production(Box::new(socket)),
            subscription,
            initial,
        )
        .await;
    }

    async fn serve_socket(
        &self,
        mut socket: EventSocket,
        mut subscription: EventSubscription,
        initial: ServerEvent,
    ) {
        if send_event(&mut socket, &initial).await.is_err() {
            return;
        }
        let mut heartbeat =
            time::interval_at(Instant::now() + self.ping_interval, self.ping_interval);
        heartbeat.set_missed_tick_behavior(MissedTickBehavior::Delay);
        let mut last_activity = Instant::now();

        loop {
            if self.sequence_exhausted.load(Ordering::Acquire) {
                send_sequence_exhausted_close(&mut socket).await;
                break;
            }
            if self.timestamp_invalid.load(Ordering::Acquire) {
                send_timestamp_invalid_close(&mut socket).await;
                break;
            }
            tokio::select! {
                _ = self.sequence_exhausted_notify.notified() => {
                    if self.sequence_exhausted.load(Ordering::Acquire) {
                        send_sequence_exhausted_close(&mut socket).await;
                        break;
                    }
                    if self.timestamp_invalid.load(Ordering::Acquire) {
                        send_timestamp_invalid_close(&mut socket).await;
                        break;
                    }
                }
                _ = self.timestamp_invalid_notify.notified() => {
                    if self.sequence_exhausted.load(Ordering::Acquire) {
                        send_sequence_exhausted_close(&mut socket).await;
                        break;
                    }
                    if self.timestamp_invalid.load(Ordering::Acquire) {
                        send_timestamp_invalid_close(&mut socket).await;
                        break;
                    }
                }
                event = subscription.receiver.recv() => {
                    match event {
                        Ok(event) => {
                            if send_event(&mut socket, &event).await.is_err() {
                                break;
                            }
                        }
                        Err(broadcast::error::RecvError::Lagged(skipped)) => {
                            self.metrics.websocket_slow_disconnect();
                            tracing::warn!(skipped, "websocket_client_lagged");
                            let _ = socket.send(Message::Close(Some(CloseFrame {
                                code: 1013,
                                reason: "client event buffer exhausted".into(),
                            }))).await;
                            break;
                        }
                        Err(broadcast::error::RecvError::Closed) => {
                            let _ = socket.send(Message::Close(Some(CloseFrame {
                                code: 1001,
                                reason: "event source stopped".into(),
                            }))).await;
                            break;
                        }
                    }
                }
                incoming = socket.recv() => {
                    match incoming {
                        Some(Ok(Message::Ping(payload))) => {
                            last_activity = Instant::now();
                            if socket.send(Message::Pong(payload)).await.is_err() {
                                break;
                            }
                        }
                        Some(Ok(Message::Pong(_))) => {
                            last_activity = Instant::now();
                        }
                        Some(Ok(message @ (Message::Text(_) | Message::Binary(_)))) => {
                            let oversized = match &message {
                                Message::Text(text) => text.len() > WEBSOCKET_MAX_MESSAGE_BYTES,
                                Message::Binary(bytes) => bytes.len() > WEBSOCKET_MAX_MESSAGE_BYTES,
                                _ => false,
                            };
                            let (code, reason, category) = if oversized {
                                (
                                    1009,
                                    OVERSIZED_CLIENT_DATA_CLOSE_REASON,
                                    "application_data_too_large",
                                )
                            } else {
                                (
                                    1003,
                                    UNSUPPORTED_CLIENT_DATA_CLOSE_REASON,
                                    "unsupported_application_data",
                                )
                            };
                            tracing::warn!(category, "websocket_inbound_message_rejected");
                            let _ = socket.send(Message::Close(Some(CloseFrame {
                                code,
                                reason: reason.into(),
                            }))).await;
                            break;
                        }
                        Some(Ok(Message::Close(_))) | None => break,
                        Some(Err(())) => break,
                    }
                }
                _ = heartbeat.tick() => {
                    if Instant::now().saturating_duration_since(last_activity) >= self.idle_timeout {
                        self.metrics.websocket_idle_disconnect();
                        let _ = socket.send(Message::Close(Some(CloseFrame {
                            code: 1001,
                            reason: "client heartbeat timeout".into(),
                        }))).await;
                        break;
                    }
                    if socket.send(Message::Ping(Vec::new().into())).await.is_err() {
                        break;
                    }
                }
            }
        }
    }

    fn publish_worker(&self, worker: WorkerEvent) {
        self.metrics.record_event(&worker.kind);
        let payload = match worker.kind {
            DesktopEventKind::ConnectionState { state } => EventPayload::ConnectionState {
                state: connection_state_name(state),
            },
            DesktopEventKind::FramebufferRevision { revision } => {
                EventPayload::FramebufferRevision { revision }
            }
            DesktopEventKind::FramebufferInvalidated => EventPayload::FramebufferInvalidated,
            DesktopEventKind::ClipboardRevision { revision } => {
                EventPayload::ClipboardRevision { revision }
            }
            DesktopEventKind::Overload => EventPayload::Overload,
            DesktopEventKind::ProtocolError => EventPayload::ProtocolError,
        };
        match self.event(worker.observed_at, payload) {
            Ok(event) => {
                let _ = self.sender.send(event);
            }
            Err(EventSequenceError::Exhausted | EventSequenceError::TimestampInvalid) => {}
        }
    }

    fn event(
        &self,
        observed_at: SystemTime,
        payload: EventPayload,
    ) -> Result<ServerEvent, EventSequenceError> {
        if self.sequence_exhausted.load(Ordering::Acquire) {
            return Err(EventSequenceError::Exhausted);
        }
        if self.timestamp_invalid.load(Ordering::Acquire) {
            return Err(EventSequenceError::TimestampInvalid);
        }
        let timestamp_unix_ms = match unix_milliseconds(observed_at) {
            Ok(timestamp) => timestamp,
            Err(error) => {
                self.mark_timestamp_invalid();
                return Err(error);
            }
        };
        let sequence = self
            .sequence
            .try_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            });
        let sequence = match sequence {
            Ok(sequence) => sequence,
            Err(_) => {
                if !self.sequence_exhausted.swap(true, Ordering::AcqRel) {
                    tracing::error!("event_hub_sequence_exhausted");
                    self.sequence_exhausted_notify.notify_waiters();
                }
                return Err(EventSequenceError::Exhausted);
            }
        };
        Ok(ServerEvent {
            sequence,
            timestamp_unix_ms,
            payload,
        })
    }

    fn mark_timestamp_invalid(&self) {
        if !self.timestamp_invalid.swap(true, Ordering::AcqRel) {
            tracing::error!("event_hub_timestamp_invalid");
            self.timestamp_invalid_notify.notify_waiters();
        }
    }

    #[cfg(test)]
    fn publish_test(&self, payload: EventPayload) -> Result<ServerEvent, EventSequenceError> {
        let event = self.event(SystemTime::now(), payload)?;
        let _ = self.sender.send(event.clone());
        Ok(event)
    }
}

enum EventSocket {
    Production(Box<WebSocket>),
    #[cfg(test)]
    Test(TestSocket),
}

impl EventSocket {
    async fn send(&mut self, message: Message) -> Result<(), ()> {
        match self {
            Self::Production(socket) => socket.send(message).await.map_err(|_| ()),
            #[cfg(test)]
            Self::Test(socket) => socket.send(message),
        }
    }

    async fn recv(&mut self) -> Option<Result<Message, ()>> {
        match self {
            Self::Production(socket) => match socket.recv().await {
                Some(Ok(message)) => Some(Ok(message)),
                Some(Err(error)) => {
                    tracing::debug!(error = %error, "websocket_receive_failed");
                    Some(Err(()))
                }
                None => None,
            },
            #[cfg(test)]
            Self::Test(socket) => socket.recv().await.map(Ok),
        }
    }
}

async fn send_sequence_exhausted_close(socket: &mut EventSocket) {
    let _ = socket
        .send(Message::Close(Some(CloseFrame {
            code: 1011,
            reason: EVENT_SEQUENCE_EXHAUSTED_CLOSE_REASON.into(),
        })))
        .await;
}

async fn send_timestamp_invalid_close(socket: &mut EventSocket) {
    let _ = socket
        .send(Message::Close(Some(CloseFrame {
            code: 1011,
            reason: EVENT_TIMESTAMP_INVALID_CLOSE_REASON.into(),
        })))
        .await;
}

#[cfg(test)]
struct TestSocket {
    outbound: tokio::sync::mpsc::UnboundedSender<Message>,
    inbound: tokio::sync::mpsc::UnboundedReceiver<Message>,
}

#[cfg(test)]
impl TestSocket {
    fn send(&mut self, message: Message) -> Result<(), ()> {
        self.outbound.send(message).map_err(|_| ())
    }

    async fn recv(&mut self) -> Option<Message> {
        self.inbound.recv().await
    }
}

struct EventBridgeExitSignal {
    sender: Option<SyncSender<()>>,
}

impl EventBridgeExitSignal {
    fn new(sender: SyncSender<()>) -> Self {
        Self {
            sender: Some(sender),
        }
    }
}

impl Drop for EventBridgeExitSignal {
    fn drop(&mut self) {
        if let Some(sender) = self.sender.take() {
            let _ = sender.try_send(());
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExitWait {
    Exited,
    TimedOut,
}

/// Owning bridge thread handle with an independent bounded stop path.
pub struct EventBridge {
    join: Option<JoinHandle<()>>,
    stop_requested: Arc<AtomicBool>,
    exited: Option<Receiver<()>>,
    drop_timeout: Duration,
}

impl EventBridge {
    /// Requests bridge stop and waits no longer than `timeout` for exit.
    /// A zero timeout still performs a nonblocking exit observation before
    /// deliberate detach.
    pub fn shutdown(mut self, timeout: Duration) -> Result<(), EventBridgeError> {
        self.request_stop();
        match self.wait_for_exit(timeout) {
            ExitWait::Exited => self.join_bridge(),
            ExitWait::TimedOut => {
                match u64::try_from(timeout.as_millis()) {
                    Ok(timeout_ms) => {
                        tracing::warn!(timeout_ms, "event_bridge_shutdown_timeout");
                    }
                    Err(_) => {
                        tracing::warn!("event_bridge_shutdown_timeout");
                        tracing::error!("event_bridge_shutdown_timeout_value_overflow");
                    }
                }
                self.detach();
                Err(EventBridgeError::Timeout)
            }
        }
    }

    fn request_stop(&self) {
        self.stop_requested.store(true, Ordering::Release);
    }

    fn wait_for_exit(&mut self, timeout: Duration) -> ExitWait {
        let Some(exited) = self.exited.take() else {
            return ExitWait::Exited;
        };
        match exited.recv_timeout(timeout) {
            Ok(()) | Err(RecvTimeoutError::Disconnected) => ExitWait::Exited,
            Err(RecvTimeoutError::Timeout) => ExitWait::TimedOut,
        }
    }

    fn join_bridge(&mut self) -> Result<(), EventBridgeError> {
        let Some(join) = self.join.take() else {
            return Ok(());
        };
        match join.join() {
            Ok(()) => Ok(()),
            Err(_) => {
                tracing::error!("event_bridge_join_failed");
                Err(EventBridgeError::ThreadPanicked)
            }
        }
    }

    fn detach(&mut self) {
        drop(self.exited.take());
        drop(self.join.take());
    }
}

impl Drop for EventBridge {
    fn drop(&mut self) {
        if self.join.is_none() {
            return;
        }
        self.request_stop();
        match self.wait_for_exit(self.drop_timeout) {
            ExitWait::Exited => {
                if let Err(error) = self.join_bridge() {
                    tracing::error!(error = ?error, "event_bridge_drop_join_failed");
                }
            }
            ExitWait::TimedOut => {
                match u64::try_from(self.drop_timeout.as_millis()) {
                    Ok(timeout_ms) => {
                        tracing::warn!(timeout_ms, "event_bridge_drop_shutdown_timeout");
                    }
                    Err(_) => {
                        tracing::warn!("event_bridge_drop_shutdown_timeout");
                        tracing::error!("event_bridge_drop_timeout_value_overflow");
                    }
                }
                self.detach();
            }
        }
    }
}

/// Bounded event-bridge shutdown failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventBridgeError {
    /// The bridge did not report exit by the requested deadline.
    Timeout,
    /// The bridge thread panicked.
    ThreadPanicked,
}

impl fmt::Display for EventBridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Timeout => formatter.write_str("worker event bridge shutdown timed out"),
            Self::ThreadPanicked => {
                formatter.write_str("worker event bridge terminated through a panic")
            }
        }
    }
}

impl Error for EventBridgeError {}

/// The configured maximum number of WebSocket clients is active.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WebSocketCapacityError;

impl fmt::Display for WebSocketCapacityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("WebSocket client capacity is exhausted")
    }
}

impl Error for WebSocketCapacityError {}

/// Event creation failed without fabricating a normal sequence or timestamp.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventSequenceError {
    /// The process-local event sequence reached its maximum value.
    Exhausted,
    /// The event observation time is not representable as Unix milliseconds.
    TimestampInvalid,
}

impl fmt::Display for EventSequenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Exhausted => formatter.write_str("worker event sequence is exhausted"),
            Self::TimestampInvalid => formatter.write_str("worker event timestamp is invalid"),
        }
    }
}

impl Error for EventSequenceError {}

/// One bounded event subscription and its client permit.
pub struct EventSubscription {
    receiver: broadcast::Receiver<ServerEvent>,
    _permit: ClientPermit,
}

struct ClientPermit {
    _permit: OwnedSemaphorePermit,
    metrics: Metrics,
}

impl Drop for ClientPermit {
    fn drop(&mut self) {
        self.metrics.websocket_closed();
    }
}

/// Stable serialized event envelope.
#[derive(Debug, Clone, Serialize)]
pub struct ServerEvent {
    /// Monotonically increasing process-local event sequence.
    pub sequence: u64,
    /// Observation timestamp in Unix milliseconds.
    pub timestamp_unix_ms: u64,
    /// Payload-free event data.
    #[serde(flatten)]
    payload: EventPayload,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum EventPayload {
    Snapshot {
        state: &'static str,
        framebuffer_revision: Option<u64>,
        clipboard_revision: Option<u64>,
        reconnect_attempts: u32,
        last_failure: Option<&'static str>,
        rejected_commands: u64,
        dropped_events: u64,
        fatal_exit: bool,
    },
    ConnectionState {
        state: &'static str,
    },
    FramebufferRevision {
        revision: u64,
    },
    FramebufferInvalidated,
    ClipboardRevision {
        revision: u64,
    },
    Overload,
    ProtocolError,
}

async fn send_event(socket: &mut EventSocket, event: &ServerEvent) -> Result<(), ()> {
    let serialized = serde_json::to_string(event).map_err(|_| ())?;
    socket.send(Message::Text(serialized.into())).await
}

fn unix_milliseconds(value: SystemTime) -> Result<u64, EventSequenceError> {
    let elapsed = value
        .duration_since(UNIX_EPOCH)
        .map_err(|_| EventSequenceError::TimestampInvalid)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| EventSequenceError::TimestampInvalid)
}

const fn connection_state_name(state: ConnectionState) -> &'static str {
    match state {
        ConnectionState::Starting => "starting",
        ConnectionState::Connecting => "connecting",
        ConnectionState::Connected => "connected",
        ConnectionState::Degraded => "degraded",
        ConnectionState::Reconnecting => "reconnecting",
        ConnectionState::Disconnected => "disconnected",
        ConnectionState::AuthenticationFailed => "authentication_failed",
        ConnectionState::Stopped => "stopped",
    }
}

const fn worker_failure_name(failure: WorkerFailureKind) -> &'static str {
    match failure {
        WorkerFailureKind::Authentication => "authentication",
        WorkerFailureKind::Configuration => "configuration",
        WorkerFailureKind::Request => "request",
        WorkerFailureKind::Capacity => "capacity",
        WorkerFailureKind::Unavailable => "unavailable",
        WorkerFailureKind::RateLimited => "rate_limited",
        WorkerFailureKind::Transport => "transport",
        WorkerFailureKind::Timeout => "timeout",
        WorkerFailureKind::Protocol => "protocol",
        WorkerFailureKind::Native => "native",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot() -> WorkerSnapshot {
        WorkerSnapshot {
            state: ConnectionState::Connected,
            started_at: UNIX_EPOCH,
            connected_at: Some(UNIX_EPOCH),
            last_message_at: Some(UNIX_EPOCH),
            reconnect_attempts: 1,
            last_failure: None,
            framebuffer_revision: Some(9),
            rejected_commands: 2,
            dropped_events: 3,
            fatal_exit: false,
        }
    }

    #[test]
    fn snapshot_event_is_monotonic_and_payload_free() {
        let hub = EventHub::detached(
            4,
            2,
            Duration::from_secs(1),
            Duration::from_secs(3),
            Metrics::default(),
        );
        let first = hub
            .snapshot_event(&snapshot(), Some(4))
            .expect("snapshot sequence allocates");
        let second = hub
            .publish_test(EventPayload::ProtocolError)
            .expect("test event sequence allocates");
        assert!(second.sequence > first.sequence);
        let serialized = serde_json::to_string(&first).expect("serialize snapshot");
        assert!(serialized.contains("\"type\":\"snapshot\""));
        assert!(serialized.contains("\"clipboard_revision\":4"));
        for forbidden in [
            "clipboard_text",
            "typed_text",
            "pixels",
            "password",
            "token",
        ] {
            assert!(!serialized.contains(forbidden));
        }
    }

    #[test]
    fn invalid_event_timestamp_is_terminal_and_logged_once() {
        let hub = EventHub::detached(
            4,
            2,
            Duration::from_secs(1),
            Duration::from_secs(3),
            Metrics::default(),
        );
        let invalid = UNIX_EPOCH - Duration::from_millis(1);
        let sequence_before = hub.sequence.load(Ordering::Acquire);
        let ((first, second), logs) = crate::test_support::capture_logs(|| {
            (
                hub.event(invalid, EventPayload::ProtocolError),
                hub.event(SystemTime::now(), EventPayload::ProtocolError),
            )
        });
        assert!(matches!(first, Err(EventSequenceError::TimestampInvalid)));
        assert!(matches!(second, Err(EventSequenceError::TimestampInvalid)));
        assert_eq!(hub.sequence.load(Ordering::Acquire), sequence_before);
        assert!(hub.timestamp_invalid.load(Ordering::Acquire));
        assert_eq!(logs.matches("event_hub_timestamp_invalid").count(), 1);
    }

    #[test]
    fn sequence_overflow_fails_closed_instead_of_panicking() {
        let hub = EventHub::detached(
            4,
            2,
            Duration::from_secs(1),
            Duration::from_secs(3),
            Metrics::default(),
        );
        hub.sequence.store(u64::MAX, Ordering::Release);
        let ((first, second), logs) = crate::test_support::capture_logs(|| {
            (
                hub.publish_test(EventPayload::ProtocolError),
                hub.publish_test(EventPayload::ProtocolError),
            )
        });
        assert!(matches!(first, Err(EventSequenceError::Exhausted)));
        assert!(matches!(second, Err(EventSequenceError::Exhausted)));
        assert!(hub.sequence_exhausted.load(Ordering::Acquire));
        assert_eq!(logs.matches("event_hub_sequence_exhausted").count(), 1);
    }

    #[tokio::test]
    async fn established_client_closes_on_sequence_exhaustion_with_bounded_1011() {
        let hub = EventHub::detached(
            4,
            1,
            Duration::from_secs(30),
            Duration::from_secs(60),
            Metrics::default(),
        );
        let subscription = hub.subscribe().expect("client subscribes");
        let initial = hub
            .snapshot_event(&snapshot(), Some(4))
            .expect("initial snapshot sequence allocates");
        let (outbound_tx, mut outbound_rx) = tokio::sync::mpsc::unbounded_channel();
        let (inbound_tx, inbound_rx) = tokio::sync::mpsc::unbounded_channel();
        let socket = EventSocket::Test(TestSocket {
            outbound: outbound_tx,
            inbound: inbound_rx,
        });
        let serving_hub = hub.clone();

        let server = async move {
            serving_hub
                .serve_socket(socket, subscription, initial)
                .await;
        };
        let client = async move {
            let _keep_inbound_open = inbound_tx;
            let initial_message = time::timeout(Duration::from_millis(100), outbound_rx.recv())
                .await
                .expect("initial snapshot is delivered within the bound")
                .expect("event socket remains open");
            let serialized = match initial_message {
                Message::Text(text) => text.to_string(),
                other => panic!("expected initial text snapshot, got {other:?}"),
            };
            assert!(serialized.contains("\"type\":\"snapshot\""));
            for forbidden in [
                "clipboard_text",
                "typed_text",
                "pixels",
                "password",
                "token",
            ] {
                assert!(!serialized.contains(forbidden));
            }

            hub.force_sequence_for_test(u64::MAX);
            assert!(matches!(
                hub.publish_test(EventPayload::ProtocolError),
                Err(EventSequenceError::Exhausted)
            ));

            let close = time::timeout(Duration::from_millis(200), async {
                loop {
                    match outbound_rx.recv().await {
                        Some(Message::Close(frame)) => {
                            break frame.expect("close frame has detail");
                        }
                        Some(Message::Ping(_)) => {}
                        Some(other) => {
                            panic!("unexpected server message after exhaustion: {other:?}")
                        }
                        None => panic!("event socket closed without an exhaustion close frame"),
                    }
                }
            })
            .await
            .expect("established client closes promptly without waiting for heartbeat");
            assert_eq!(close.code, 1011);
            let reason = close.reason.to_string();
            assert_eq!(reason, EVENT_SEQUENCE_EXHAUSTED_CLOSE_REASON);
            for forbidden in [
                "clipboard",
                "typed",
                "password",
                "token",
                "framebuffer",
                "screenshot",
                "query",
            ] {
                assert!(!reason.contains(forbidden));
            }
        };

        tokio::join!(server, client);
    }

    #[tokio::test]
    async fn established_client_closes_promptly_when_event_clock_is_invalid() {
        let hub = EventHub::detached(
            4,
            1,
            Duration::from_secs(30),
            Duration::from_secs(60),
            Metrics::default(),
        );
        let subscription = hub.subscribe().expect("client subscribes");
        let initial = hub
            .snapshot_event(&snapshot(), None)
            .expect("initial snapshot sequence allocates");
        let (outbound_tx, mut outbound_rx) = tokio::sync::mpsc::unbounded_channel();
        let (inbound_tx, inbound_rx) = tokio::sync::mpsc::unbounded_channel();
        let socket = EventSocket::Test(TestSocket {
            outbound: outbound_tx,
            inbound: inbound_rx,
        });
        let serving_hub = hub.clone();

        let server = async move {
            serving_hub
                .serve_socket(socket, subscription, initial)
                .await;
        };
        let client = async move {
            let _keep_inbound_open = inbound_tx;
            let initial_message = time::timeout(Duration::from_millis(100), outbound_rx.recv())
                .await
                .expect("initial snapshot is delivered within the bound")
                .expect("event socket remains open");
            assert!(matches!(initial_message, Message::Text(_)));

            hub.mark_timestamp_invalid();
            let close = time::timeout(Duration::from_millis(200), async {
                loop {
                    match outbound_rx.recv().await {
                        Some(Message::Close(frame)) => {
                            break frame.expect("close frame has detail");
                        }
                        Some(Message::Ping(_)) => {}
                        Some(other) => panic!("unexpected message after clock failure: {other:?}"),
                        None => panic!("event socket closed without timestamp-invalid close frame"),
                    }
                }
            })
            .await
            .expect("established client closes promptly without waiting for heartbeat");
            assert_eq!(close.code, 1011);
            assert_eq!(
                close.reason.to_string(),
                EVENT_TIMESTAMP_INVALID_CLOSE_REASON
            );
        };

        tokio::join!(server, client);
    }

    #[tokio::test]
    async fn client_count_and_sustained_event_buffering_are_bounded() {
        let metrics = Metrics::default();
        let hub = EventHub::detached(
            2,
            1,
            Duration::from_secs(1),
            Duration::from_secs(3),
            metrics.clone(),
        );
        let mut first = hub.subscribe().expect("first client");
        assert!(hub.subscribe().is_err());
        for revision in 1..=10_000 {
            hub.publish_test(EventPayload::FramebufferRevision { revision })
                .expect("sequence allocates");
        }
        assert!(matches!(
            first.receiver.recv().await,
            Err(broadcast::error::RecvError::Lagged(_))
        ));
        drop(first);
        let rendered = metrics.render(&snapshot(), 0, 4);
        assert!(rendered.contains("vrc_websocket_clients 0"));
        assert!(rendered.contains("vrc_websocket_rejected_total 1"));
    }

    fn socket_pair() -> (
        EventSocket,
        tokio::sync::mpsc::UnboundedSender<Message>,
        tokio::sync::mpsc::UnboundedReceiver<Message>,
    ) {
        let (outbound_tx, outbound_rx) = tokio::sync::mpsc::unbounded_channel();
        let (inbound_tx, inbound_rx) = tokio::sync::mpsc::unbounded_channel();
        (
            EventSocket::Test(TestSocket {
                outbound: outbound_tx,
                inbound: inbound_rx,
            }),
            inbound_tx,
            outbound_rx,
        )
    }

    async fn expect_initial_snapshot(
        outbound_rx: &mut tokio::sync::mpsc::UnboundedReceiver<Message>,
    ) {
        let message = time::timeout(Duration::from_millis(100), outbound_rx.recv())
            .await
            .expect("initial snapshot is delivered within the bound")
            .expect("event socket remains open");
        let Message::Text(text) = message else {
            panic!("expected initial text snapshot");
        };
        assert!(text.contains("\"type\":\"snapshot\""));
    }

    #[tokio::test]
    async fn client_ping_is_answered_and_pong_and_close_are_allowed() {
        let hub = EventHub::detached(
            4,
            1,
            Duration::from_secs(30),
            Duration::from_secs(60),
            Metrics::default(),
        );
        let subscription = hub.subscribe().expect("client subscribes");
        let initial = hub
            .snapshot_event(&snapshot(), None)
            .expect("initial snapshot sequence allocates");
        let (socket, inbound_tx, mut outbound_rx) = socket_pair();
        let serving_hub = hub.clone();
        let server = tokio::spawn(async move {
            serving_hub.serve_socket(socket, subscription, initial).await;
        });

        expect_initial_snapshot(&mut outbound_rx).await;
        inbound_tx
            .send(Message::Ping(vec![1, 2, 3].into()))
            .expect("ping enters socket");
        let pong = time::timeout(Duration::from_millis(100), outbound_rx.recv())
            .await
            .expect("pong is prompt")
            .expect("event socket remains open");
        assert_eq!(pong, Message::Pong(vec![1, 2, 3].into()));

        inbound_tx
            .send(Message::Pong(Vec::new().into()))
            .expect("pong enters socket");
        inbound_tx
            .send(Message::Close(None))
            .expect("close enters socket");
        time::timeout(Duration::from_millis(100), server)
            .await
            .expect("client close terminates service promptly")
            .expect("server task does not panic");
        assert!(
            hub.subscribe().is_ok(),
            "client permit is released after close"
        );
    }

    async fn assert_application_data_rejected(
        message: Message,
        expected_code: u16,
        expected_reason: &str,
    ) {
        let hub = EventHub::detached(
            4,
            1,
            Duration::from_secs(30),
            Duration::from_secs(60),
            Metrics::default(),
        );
        let subscription = hub.subscribe().expect("client subscribes");
        let initial = hub
            .snapshot_event(&snapshot(), None)
            .expect("initial snapshot sequence allocates");
        let (socket, inbound_tx, mut outbound_rx) = socket_pair();
        let serving_hub = hub.clone();
        let server = tokio::spawn(async move {
            serving_hub.serve_socket(socket, subscription, initial).await;
        });

        expect_initial_snapshot(&mut outbound_rx).await;
        inbound_tx.send(message).expect("message enters socket");
        let close = time::timeout(Duration::from_millis(100), outbound_rx.recv())
            .await
            .expect("protocol close is prompt")
            .expect("close frame is emitted");
        let Message::Close(Some(frame)) = close else {
            panic!("expected close frame, got {close:?}");
        };
        assert_eq!(frame.code, expected_code);
        assert_eq!(frame.reason, expected_reason);
        time::timeout(Duration::from_millis(100), server)
            .await
            .expect("rejected client terminates promptly")
            .expect("server task does not panic");
        assert!(
            hub.subscribe().is_ok(),
            "client permit is released after rejection"
        );
    }

    #[tokio::test]
    async fn text_and_binary_application_data_are_rejected_with_1003() {
        assert_application_data_rejected(
            Message::Text("ignored-client-text".into()),
            1003,
            UNSUPPORTED_CLIENT_DATA_CLOSE_REASON,
        )
        .await;
        assert_application_data_rejected(
            Message::Binary(vec![0x41, 0x42].into()),
            1003,
            UNSUPPORTED_CLIENT_DATA_CLOSE_REASON,
        )
        .await;
    }

    #[tokio::test]
    async fn oversized_application_data_is_rejected_with_1009() {
        assert_application_data_rejected(
            Message::Binary(vec![0x41; WEBSOCKET_MAX_MESSAGE_BYTES + 1].into()),
            1009,
            OVERSIZED_CLIENT_DATA_CLOSE_REASON,
        )
        .await;
    }

    #[test]
    fn websocket_inbound_limits_are_small_and_control_frame_safe() {
        const MAX_CONTROL_FRAME_PAYLOAD_BYTES: usize = 125;
        assert_eq!(WEBSOCKET_MAX_MESSAGE_BYTES, 4096);
        assert_eq!(WEBSOCKET_MAX_FRAME_BYTES, 4096);
        assert!(WEBSOCKET_MAX_MESSAGE_BYTES >= MAX_CONTROL_FRAME_PAYLOAD_BYTES);
        assert!(WEBSOCKET_MAX_FRAME_BYTES >= MAX_CONTROL_FRAME_PAYLOAD_BYTES);
    }

    #[test]
    fn event_bridge_shutdown_does_not_require_worker_sender_drop() {
        let (_sender, worker_events) = WorkerEvents::test_channel(4);
        let (_hub, bridge) = EventHub::start(
            worker_events,
            4,
            2,
            Duration::from_secs(1),
            Duration::from_secs(3),
            Metrics::default(),
        )
        .expect("bridge starts");

        bridge
            .shutdown(Duration::from_secs(1))
            .expect("bridge stops while worker sender remains alive");
    }

    #[test]
    fn event_bridge_timeout_is_observable() {
        let (_sender, worker_events) = WorkerEvents::test_channel(4);
        let (release_tx, release_rx) = std::sync::mpsc::sync_channel(1);
        let ((result, elapsed), logs) = crate::test_support::capture_logs(|| {
            let (_hub, bridge) = EventHub::start_with_hook(
                worker_events,
                EventBridgeStartSettings {
                    event_capacity: 4,
                    maximum_clients: 2,
                    ping_interval: Duration::from_secs(1),
                    idle_timeout: Duration::from_secs(3),
                    metrics: Metrics::default(),
                    drop_timeout: Duration::from_millis(25),
                },
                move || {
                    let _ = release_rx.recv();
                },
            )
            .expect("bridge starts");
            let started = std::time::Instant::now();
            let result = bridge.shutdown(Duration::from_millis(25));
            (result, started.elapsed())
        });

        assert_eq!(result, Err(EventBridgeError::Timeout));
        assert!(elapsed < Duration::from_secs(1));
        assert!(logs.contains("event_bridge_shutdown_timeout"));
        release_tx.send(()).expect("release detached bridge");
    }

    #[test]
    fn event_bridge_panic_is_returned_and_logged() {
        let (_sender, worker_events) = WorkerEvents::test_channel(4);
        let (result, logs) = crate::test_support::capture_logs(|| {
            let (_hub, bridge) = EventHub::start_with_hook(
                worker_events,
                EventBridgeStartSettings {
                    event_capacity: 4,
                    maximum_clients: 2,
                    ping_interval: Duration::from_secs(1),
                    idle_timeout: Duration::from_secs(3),
                    metrics: Metrics::default(),
                    drop_timeout: Duration::from_millis(25),
                },
                || panic!("test-only bridge panic"),
            )
            .expect("bridge starts");
            bridge.shutdown(Duration::from_secs(1))
        });

        assert_eq!(result, Err(EventBridgeError::ThreadPanicked));
        assert!(logs.contains("event_bridge_join_failed"));
    }

    #[test]
    fn event_bridge_drop_is_bounded() {
        let (_sender, worker_events) = WorkerEvents::test_channel(4);
        let (release_tx, release_rx) = std::sync::mpsc::sync_channel(1);
        let ((elapsed, done), logs) = crate::test_support::capture_logs(|| {
            let (_hub, bridge) = EventHub::start_with_hook(
                worker_events,
                EventBridgeStartSettings {
                    event_capacity: 4,
                    maximum_clients: 2,
                    ping_interval: Duration::from_secs(1),
                    idle_timeout: Duration::from_secs(3),
                    metrics: Metrics::default(),
                    drop_timeout: Duration::from_millis(25),
                },
                move || {
                    let _ = release_rx.recv();
                },
            )
            .expect("bridge starts");
            let dispatch = crate::test_support::current_dispatch();
            let (done_tx, done_rx) = std::sync::mpsc::channel();
            let started = std::time::Instant::now();
            let drop_thread = std::thread::spawn(move || {
                tracing::dispatcher::with_default(&dispatch, || drop(bridge));
                let _ = done_tx.send(());
            });
            let done = done_rx.recv_timeout(Duration::from_secs(1)).is_ok();
            drop_thread
                .join()
                .expect("bridge drop thread does not panic");
            (started.elapsed(), done)
        });

        assert!(done);
        assert!(elapsed < Duration::from_secs(1));
        assert!(logs.contains("event_bridge_drop_shutdown_timeout"));
        release_tx.send(()).expect("release detached bridge");
    }
}
