//! Structured tracing initialization and bounded-label process metrics.
//!
//! Metrics intentionally expose only fixed labels and redacted aggregate state.
//! Request IDs, URLs, keys, payload text, clipboard contents, pixels, and secret
//! values are never used as labels or metric values.

use crate::screenshot::{ScreenshotError, ScreenshotOutcome};
use crate::worker::{WorkerFailureKind, WorkerSnapshot};
use remote_desktop_core::{ConnectionState, DesktopError, DesktopEventKind, WorkerCommand};
use std::fmt::Write as _;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tracing_subscriber::EnvFilter;

/// Installs the process-wide JSON tracing subscriber.
pub fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .json()
        .with_current_span(true)
        .with_span_list(true)
        .try_init();
}

/// Cloneable process metrics using only bounded, predefined dimensions.
#[derive(Clone, Default)]
pub struct Metrics {
    inner: Arc<MetricsInner>,
}

#[derive(Default)]
struct MetricsInner {
    http_requests: AtomicU64,
    http_errors: AtomicU64,
    auth_failures: AtomicU64,
    command_pointer: AtomicU64,
    command_keyboard: AtomicU64,
    command_text: AtomicU64,
    command_clipboard: AtomicU64,
    command_reconnect: AtomicU64,
    command_other: AtomicU64,
    command_errors: AtomicU64,
    command_timeouts: AtomicU64,
    screenshot_requests: AtomicU64,
    screenshot_success: AtomicU64,
    screenshot_not_modified: AtomicU64,
    screenshot_busy: AtomicU64,
    screenshot_timeouts: AtomicU64,
    screenshot_failures: AtomicU64,
    screenshot_duration_ms: AtomicU64,
    websocket_clients: AtomicU64,
    websocket_rejected: AtomicU64,
    websocket_slow_disconnects: AtomicU64,
    websocket_idle_disconnects: AtomicU64,
    event_connection: AtomicU64,
    event_framebuffer: AtomicU64,
    event_invalidation: AtomicU64,
    event_clipboard: AtomicU64,
    event_overload: AtomicU64,
    event_protocol: AtomicU64,
    reconnect_events: AtomicU64,
    protocol_errors: AtomicU64,
}

impl Metrics {
    /// Records one completed HTTP request without retaining its URL or request ID.
    pub fn record_http(&self, status: u16, _elapsed: Duration) {
        self.inner.http_requests.fetch_add(1, Ordering::Relaxed);
        if status >= 400 {
            self.inner.http_errors.fetch_add(1, Ordering::Relaxed);
        }
    }

    /// Records one rejected authentication attempt.
    pub fn record_auth_failure(&self) {
        self.inner.auth_failures.fetch_add(1, Ordering::Relaxed);
    }

    /// Records one bounded command type without retaining command payloads.
    pub fn record_command(&self, command: &WorkerCommand) {
        let counter = match command {
            WorkerCommand::MovePointer { .. }
            | WorkerCommand::SetButton { .. }
            | WorkerCommand::Click { .. }
            | WorkerCommand::DoubleClick { .. }
            | WorkerCommand::Scroll { .. } => &self.inner.command_pointer,
            WorkerCommand::SetKey { .. } | WorkerCommand::Chord { .. } => {
                &self.inner.command_keyboard
            }
            WorkerCommand::TypeText { .. } => &self.inner.command_text,
            WorkerCommand::SetClipboard { .. } => &self.inner.command_clipboard,
            WorkerCommand::Reconnect => &self.inner.command_reconnect,
            WorkerCommand::RequestFullRefresh | WorkerCommand::Shutdown => {
                &self.inner.command_other
            }
        };
        counter.fetch_add(1, Ordering::Relaxed);
    }

    /// Records one command failure by bounded error class.
    pub fn record_command_failure(&self, error: &DesktopError) {
        self.inner.command_errors.fetch_add(1, Ordering::Relaxed);
        if matches!(error, DesktopError::Timeout) {
            self.inner.command_timeouts.fetch_add(1, Ordering::Relaxed);
        }
        if matches!(error, DesktopError::Protocol) {
            self.inner.protocol_errors.fetch_add(1, Ordering::Relaxed);
        }
    }

    /// Records the start of one screenshot request.
    pub fn screenshot_started(&self) {
        self.inner
            .screenshot_requests
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Records one successful screenshot response.
    pub fn screenshot_succeeded(&self, outcome: &ScreenshotOutcome, elapsed: Duration) {
        self.add_screenshot_duration(elapsed);
        match outcome {
            ScreenshotOutcome::Png { .. } => {
                self.inner
                    .screenshot_success
                    .fetch_add(1, Ordering::Relaxed);
            }
            ScreenshotOutcome::NotModified { .. } => {
                self.inner
                    .screenshot_not_modified
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    /// Records one screenshot failure by fixed category.
    pub fn screenshot_failed(&self, error: Option<ScreenshotError>, elapsed: Duration) {
        self.add_screenshot_duration(elapsed);
        match error {
            Some(ScreenshotError::Busy) => {
                self.inner.screenshot_busy.fetch_add(1, Ordering::Relaxed);
            }
            Some(ScreenshotError::Timeout) => {
                self.inner
                    .screenshot_timeouts
                    .fetch_add(1, Ordering::Relaxed);
            }
            _ => {
                self.inner
                    .screenshot_failures
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    fn add_screenshot_duration(&self, elapsed: Duration) {
        let milliseconds = u64::try_from(elapsed.as_millis()).unwrap_or(u64::MAX);
        self.inner
            .screenshot_duration_ms
            .fetch_add(milliseconds, Ordering::Relaxed);
    }

    /// Records one accepted WebSocket client.
    pub fn websocket_opened(&self) {
        self.inner.websocket_clients.fetch_add(1, Ordering::Relaxed);
    }

    /// Records cleanup of one WebSocket client.
    pub fn websocket_closed(&self) {
        let _ = self.inner.websocket_clients.fetch_update(
            Ordering::Relaxed,
            Ordering::Relaxed,
            |value| value.checked_sub(1),
        );
    }

    /// Records predictable rejection at the configured client limit.
    pub fn websocket_rejected(&self) {
        self.inner
            .websocket_rejected
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Records disconnection of a client that fell behind the bounded queue.
    pub fn websocket_slow_disconnect(&self) {
        self.inner
            .websocket_slow_disconnects
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Records heartbeat/idle disconnection.
    pub fn websocket_idle_disconnect(&self) {
        self.inner
            .websocket_idle_disconnects
            .fetch_add(1, Ordering::Relaxed);
    }

    /// Records one payload-free worker event.
    pub fn record_event(&self, kind: &DesktopEventKind) {
        match kind {
            DesktopEventKind::ConnectionState { state } => {
                self.inner.event_connection.fetch_add(1, Ordering::Relaxed);
                if *state == ConnectionState::Reconnecting {
                    self.inner.reconnect_events.fetch_add(1, Ordering::Relaxed);
                }
            }
            DesktopEventKind::FramebufferRevision { .. } => {
                self.inner.event_framebuffer.fetch_add(1, Ordering::Relaxed);
            }
            DesktopEventKind::FramebufferInvalidated => {
                self.inner
                    .event_invalidation
                    .fetch_add(1, Ordering::Relaxed);
            }
            DesktopEventKind::ClipboardRevision { .. } => {
                self.inner.event_clipboard.fetch_add(1, Ordering::Relaxed);
            }
            DesktopEventKind::Overload => {
                self.inner.event_overload.fetch_add(1, Ordering::Relaxed);
            }
            DesktopEventKind::ProtocolError => {
                self.inner.event_protocol.fetch_add(1, Ordering::Relaxed);
                self.inner.protocol_errors.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    /// Renders Prometheus text with fixed metric and label names only.
    pub fn render(
        &self,
        snapshot: &WorkerSnapshot,
        command_queue_depth: usize,
        command_queue_capacity: usize,
    ) -> String {
        let mut output = String::new();
        let states = [
            ConnectionState::Starting,
            ConnectionState::Connecting,
            ConnectionState::Connected,
            ConnectionState::Degraded,
            ConnectionState::Reconnecting,
            ConnectionState::Disconnected,
            ConnectionState::AuthenticationFailed,
            ConnectionState::Stopped,
        ];
        for state in states {
            let _ = writeln!(
                output,
                "vrc_connection_state{{state=\"{}\"}} {}",
                connection_state_name(state),
                u8::from(snapshot.state == state)
            );
        }
        let failures = [
            WorkerFailureKind::Authentication,
            WorkerFailureKind::Configuration,
            WorkerFailureKind::Transport,
            WorkerFailureKind::Timeout,
            WorkerFailureKind::Protocol,
            WorkerFailureKind::Native,
        ];
        for failure in failures {
            let _ = writeln!(
                output,
                "vrc_worker_last_failure{{kind=\"{}\"}} {}",
                worker_failure_name(failure),
                u8::from(snapshot.last_failure == Some(failure))
            );
        }
        metric(
            &mut output,
            "vrc_http_requests_total",
            self.inner.http_requests.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_http_errors_total",
            self.inner.http_errors.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_auth_failures_total",
            self.inner.auth_failures.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_commands_total",
            "kind",
            "pointer",
            self.inner.command_pointer.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_commands_total",
            "kind",
            "keyboard",
            self.inner.command_keyboard.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_commands_total",
            "kind",
            "text",
            self.inner.command_text.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_commands_total",
            "kind",
            "clipboard",
            self.inner.command_clipboard.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_commands_total",
            "kind",
            "reconnect",
            self.inner.command_reconnect.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_commands_total",
            "kind",
            "other",
            self.inner.command_other.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_command_errors_total",
            self.inner.command_errors.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_command_timeouts_total",
            self.inner.command_timeouts.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_worker_command_queue_depth",
            u64::try_from(command_queue_depth).unwrap_or(u64::MAX),
        );
        metric(
            &mut output,
            "vrc_worker_command_queue_capacity",
            u64::try_from(command_queue_capacity).unwrap_or(u64::MAX),
        );
        metric(
            &mut output,
            "vrc_worker_rejected_commands_total",
            snapshot.rejected_commands,
        );
        metric(
            &mut output,
            "vrc_worker_dropped_events_total",
            snapshot.dropped_events,
        );
        metric(
            &mut output,
            "vrc_worker_reconnect_attempts",
            u64::from(snapshot.reconnect_attempts),
        );
        metric(
            &mut output,
            "vrc_framebuffer_revision",
            snapshot.framebuffer_revision.unwrap_or(0),
        );
        metric(
            &mut output,
            "vrc_screenshot_requests_total",
            self.inner.screenshot_requests.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_screenshot_success_total",
            self.inner.screenshot_success.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_screenshot_not_modified_total",
            self.inner.screenshot_not_modified.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_screenshot_busy_total",
            self.inner.screenshot_busy.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_screenshot_timeouts_total",
            self.inner.screenshot_timeouts.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_screenshot_failures_total",
            self.inner.screenshot_failures.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_screenshot_duration_milliseconds_total",
            self.inner.screenshot_duration_ms.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_websocket_clients",
            self.inner.websocket_clients.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_websocket_rejected_total",
            self.inner.websocket_rejected.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_websocket_slow_disconnects_total",
            self.inner
                .websocket_slow_disconnects
                .load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_websocket_idle_disconnects_total",
            self.inner
                .websocket_idle_disconnects
                .load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_events_total",
            "type",
            "connection_state",
            self.inner.event_connection.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_events_total",
            "type",
            "framebuffer_revision",
            self.inner.event_framebuffer.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_events_total",
            "type",
            "framebuffer_invalidated",
            self.inner.event_invalidation.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_events_total",
            "type",
            "clipboard_revision",
            self.inner.event_clipboard.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_events_total",
            "type",
            "overload",
            self.inner.event_overload.load(Ordering::Relaxed),
        );
        labeled_metric(
            &mut output,
            "vrc_events_total",
            "type",
            "protocol_error",
            self.inner.event_protocol.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_reconnect_events_total",
            self.inner.reconnect_events.load(Ordering::Relaxed),
        );
        metric(
            &mut output,
            "vrc_protocol_errors_total",
            self.inner.protocol_errors.load(Ordering::Relaxed),
        );
        output
    }
}

fn metric(output: &mut String, name: &str, value: u64) {
    let _ = writeln!(output, "{name} {value}");
}

fn labeled_metric(output: &mut String, name: &str, label: &str, value: &str, count: u64) {
    let _ = writeln!(output, "{name}{{{label}=\"{value}\"}} {count}");
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
    use std::time::{SystemTime, UNIX_EPOCH};

    fn snapshot() -> WorkerSnapshot {
        WorkerSnapshot {
            state: ConnectionState::Connected,
            started_at: UNIX_EPOCH,
            connected_at: Some(SystemTime::now()),
            last_message_at: Some(SystemTime::now()),
            reconnect_attempts: 2,
            last_failure: Some(WorkerFailureKind::Protocol),
            framebuffer_revision: Some(7),
            rejected_commands: 3,
            dropped_events: 4,
            fatal_exit: false,
        }
    }

    #[test]
    fn metrics_use_only_bounded_labels_and_never_payload_values() {
        let metrics = Metrics::default();
        metrics.record_command(&WorkerCommand::TypeText {
            text: "typed-secret-value".to_owned(),
        });
        metrics.record_command(&WorkerCommand::SetClipboard {
            text: "clipboard-secret-value".to_owned(),
        });
        metrics.record_event(&DesktopEventKind::ProtocolError);
        let rendered = metrics.render(&snapshot(), 1, 8);
        assert!(rendered.contains("vrc_commands_total{kind=\"text\"} 1"));
        assert!(rendered.contains("vrc_worker_command_queue_capacity 8"));
        assert!(!rendered.contains("typed-secret-value"));
        assert!(!rendered.contains("clipboard-secret-value"));
        assert!(!rendered.contains("request_id"));
        assert!(!rendered.contains("url="));
    }
}
