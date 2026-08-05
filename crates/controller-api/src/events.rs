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
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::broadcast;
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use tokio::time::{self, Instant, MissedTickBehavior};

/// Process-wide WebSocket event transport.
#[derive(Clone)]
pub struct EventHub {
    sender: broadcast::Sender<ServerEvent>,
    sequence: Arc<AtomicU64>,
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
        let hub = Self::detached(
            event_capacity,
            maximum_clients,
            ping_interval,
            idle_timeout,
            metrics,
        );
        let bridge_hub = hub.clone();
        let join = thread::Builder::new()
            .name("worker-event-bridge".to_owned())
            .spawn(move || {
                let span = tracing::info_span!("worker_event_bridge");
                let _entered = span.enter();
                while let Ok(event) = worker_events.recv() {
                    bridge_hub.publish_worker(event);
                }
                tracing::info!("worker_event_bridge_stopped");
            })?;
        Ok((hub, EventBridge { join: Some(join) }))
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
            clients: Arc::new(Semaphore::new(maximum_clients)),
            metrics,
            ping_interval,
            idle_timeout,
        }
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
    ) -> ServerEvent {
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
        mut socket: WebSocket,
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
            tokio::select! {
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
                        Some(Ok(Message::Pong(_)
                            | Message::Text(_)
                            | Message::Binary(_))) => {
                            last_activity = Instant::now();
                        }
                        Some(Ok(Message::Close(_))) | None => break,
                        Some(Err(error)) => {
                            tracing::debug!(error = %error, "websocket_receive_failed");
                            break;
                        }
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
        let event = self.event(worker.observed_at, payload);
        let _ = self.sender.send(event);
    }

    fn event(&self, observed_at: SystemTime, payload: EventPayload) -> ServerEvent {
        let sequence = self
            .sequence
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .expect("worker event sequence exhausted");
        ServerEvent {
            sequence,
            timestamp_unix_ms: unix_milliseconds(observed_at),
            payload,
        }
    }

    #[cfg(test)]
    fn publish_test(&self, payload: EventPayload) -> ServerEvent {
        let event = self.event(SystemTime::now(), payload);
        let _ = self.sender.send(event.clone());
        event
    }
}

/// Owning bridge thread handle.
pub struct EventBridge {
    join: Option<JoinHandle<()>>,
}

impl EventBridge {
    /// Joins the bridge after worker shutdown closes the source channel.
    pub fn join(mut self) -> Result<(), EventBridgeError> {
        let Some(join) = self.join.take() else {
            return Ok(());
        };
        join.join().map_err(|_| EventBridgeError)
    }
}

/// Bridge thread terminated through a panic.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventBridgeError;

impl fmt::Display for EventBridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("worker event bridge terminated unexpectedly")
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

async fn send_event(socket: &mut WebSocket, event: &ServerEvent) -> Result<(), ()> {
    let serialized = serde_json::to_string(event).map_err(|_| ())?;
    socket
        .send(Message::Text(serialized.into()))
        .await
        .map_err(|_| ())
}

fn unix_milliseconds(value: SystemTime) -> u64 {
    let milliseconds = value
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(milliseconds).unwrap_or(u64::MAX)
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
        let first = hub.snapshot_event(&snapshot(), Some(4));
        let second = hub.publish_test(EventPayload::ProtocolError);
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
    #[should_panic(expected = "worker event sequence exhausted")]
    fn sequence_overflow_panics_instead_of_reusing_max_sequence() {
        let hub = EventHub::detached(
            4,
            2,
            Duration::from_secs(1),
            Duration::from_secs(3),
            Metrics::default(),
        );
        hub.sequence.store(u64::MAX, Ordering::Release);
        let _ = hub.publish_test(EventPayload::ProtocolError);
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
            hub.publish_test(EventPayload::FramebufferRevision { revision });
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
}
