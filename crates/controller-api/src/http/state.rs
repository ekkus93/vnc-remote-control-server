use super::backend::{HttpBackend, WorkerHttpBackend};
use super::ids::{RequestId, valid_process_instance};
use crate::config::ApiToken;
use crate::events::EventHub;
use crate::observability::Metrics;
use crate::screenshot::ScreenshotError;
use crate::worker::WorkerClient;
use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::Duration;

/// HTTP-only production settings after native worker credentials have moved
/// into the worker runtime.
pub struct HttpWorkerSettings {
    /// Static bearer token shared into router state without duplicating bytes.
    pub api_token: ApiToken,
    /// Stable identifier used to namespace screenshot ETags and request IDs.
    pub process_instance: Arc<str>,
    /// Maximum accepted JSON request body size.
    pub maximum_json_bytes: usize,
    /// Maximum wait for worker command completion.
    pub command_ack_timeout: Duration,
    /// Maximum simultaneous screenshot encodes.
    pub screenshot_concurrency: usize,
    /// Screenshot encode deadline.
    pub screenshot_timeout: Duration,
}

/// Shared router state.
#[derive(Clone)]
pub struct HttpState {
    pub(super) backend: Arc<dyn HttpBackend>,
    pub(super) api_token: ApiToken,
    process_instance: Arc<str>,
    request_sequence: Arc<AtomicU64>,
    shutting_down: Arc<AtomicBool>,
    pub(super) maximum_json_bytes: usize,
    pub(super) command_ack_timeout: Duration,
    pub(super) events: EventHub,
    pub(super) metrics: Metrics,
}

impl HttpState {
    /// Creates validated HTTP state over one backend.
    pub fn new(
        backend: Arc<dyn HttpBackend>,
        api_token: ApiToken,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
        command_ack_timeout: Duration,
    ) -> Result<Self, HttpBuildError> {
        let metrics = Metrics::default();
        let events = EventHub::detached(
            16,
            4,
            Duration::from_secs(15),
            Duration::from_secs(45),
            metrics.clone(),
        );
        Self::new_with_observability(
            backend,
            api_token,
            process_instance,
            maximum_json_bytes,
            command_ack_timeout,
            events,
            metrics,
        )
    }

    fn new_with_observability(
        backend: Arc<dyn HttpBackend>,
        api_token: ApiToken,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
        command_ack_timeout: Duration,
        events: EventHub,
        metrics: Metrics,
    ) -> Result<Self, HttpBuildError> {
        if api_token.is_empty() {
            return Err(HttpBuildError::EmptyApiToken);
        }
        if maximum_json_bytes == 0 {
            return Err(HttpBuildError::InvalidBodyLimit);
        }
        if command_ack_timeout.is_zero() {
            return Err(HttpBuildError::InvalidCommandAckTimeout);
        }
        if !valid_process_instance(&process_instance) {
            return Err(HttpBuildError::InvalidProcessInstance);
        }
        Ok(Self {
            backend,
            api_token,
            process_instance,
            request_sequence: Arc::new(AtomicU64::new(1)),
            shutting_down: Arc::new(AtomicBool::new(false)),
            maximum_json_bytes,
            command_ack_timeout,
            events,
            metrics,
        })
    }

    /// Creates production HTTP state after worker-owned configuration has moved
    /// into the desktop worker. Only HTTP-specific values cross this boundary.
    pub fn from_worker(
        client: WorkerClient,
        events: EventHub,
        metrics: Metrics,
        settings: HttpWorkerSettings,
    ) -> Result<Self, HttpBuildError> {
        let backend = WorkerHttpBackend::new(
            client,
            settings.process_instance.as_ref(),
            settings.screenshot_concurrency,
            settings.screenshot_timeout,
        )
        .map_err(HttpBuildError::Screenshot)?;
        Self::new_with_observability(
            Arc::new(backend),
            settings.api_token,
            settings.process_instance,
            settings.maximum_json_bytes,
            settings.command_ack_timeout,
            events,
            metrics,
        )
    }

    /// Marks the application as shutting down so readiness fails closed.
    pub fn begin_shutdown(&self) {
        self.shutting_down.store(true, Ordering::Release);
    }

    /// Returns whether shutdown has begun.
    pub fn is_shutting_down(&self) -> bool {
        self.shutting_down.load(Ordering::Acquire)
    }

    pub(super) fn next_request_id(&self) -> RequestId {
        let sequence = self.request_sequence.fetch_add(1, Ordering::Relaxed);
        RequestId(Arc::from(format!("{}-{sequence}", self.process_instance)))
    }
}

/// HTTP router construction failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpBuildError {
    /// The bearer token is empty.
    EmptyApiToken,
    /// The process instance cannot safely appear in request IDs.
    InvalidProcessInstance,
    /// The configured global body limit is zero.
    InvalidBodyLimit,
    /// The command acknowledgement timeout is zero.
    InvalidCommandAckTimeout,
    /// The screenshot service could not be constructed.
    Screenshot(ScreenshotError),
}

impl fmt::Display for HttpBuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::EmptyApiToken => "API token is empty",
            Self::InvalidProcessInstance => "process instance is invalid",
            Self::InvalidBodyLimit => "HTTP body limit is invalid",
            Self::InvalidCommandAckTimeout => "command acknowledgement timeout is invalid",
            Self::Screenshot(_) => "screenshot service configuration is invalid",
        };
        formatter.write_str(message)
    }
}

impl Error for HttpBuildError {}
