//! Authenticated HTTP routing for the controller service.
//!
//! The router deliberately depends on a narrow backend trait. Production wraps
//! `WorkerClient`; unit tests use deterministic in-memory fixtures without
//! starting a native VNC thread. All `/v1/*` routes share one bearer-auth layer,
//! complete request preflight, bounded worker acknowledgements, and payload-free
//! error mapping. Liveness and readiness remain public orchestration endpoints.

use crate::api_contract::{
    ChordRequest, ClipboardRequest, KeyRequest, PointerButtonRequest, PointerClickRequest,
    PointerDoubleClickRequest, PointerMoveRequest, PointerScrollRequest, TextRequest,
};
use crate::config::ControllerConfig;
use crate::events::{EventHub, WebSocketCapacityError};
use crate::framebuffer::{FramebufferMetadata, FramebufferStatus};
use crate::observability::Metrics;
use crate::screenshot::{ScreenshotError, ScreenshotOutcome, ScreenshotService};
use crate::worker::{WorkerClient, WorkerFailureKind, WorkerSnapshot};
use axum::body::Body;
use axum::extract::{
    DefaultBodyLimit, Extension, Request, State, rejection::JsonRejection, ws::WebSocketUpgrade,
};
use axum::http::header::{AUTHORIZATION, CACHE_CONTROL, CONTENT_TYPE, ETAG, IF_NONE_MATCH};
use axum::http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use remote_desktop_core::{
    ClipboardSnapshot, ConnectionState, DesktopError, DisplayInfo, WorkerCommand,
};
use serde::Serialize;
use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use subtle::ConstantTimeEq;
use tracing::Instrument;

const REQUEST_ID_HEADER: HeaderName = HeaderName::from_static("x-request-id");
const MAX_REQUEST_ID_BYTES: usize = 64;
const DEFAULT_ERROR_MESSAGE: &str = "request could not be completed";

/// Backend required by the authenticated HTTP surface.
pub trait HttpBackend: Send + Sync + 'static {
    /// Returns one redacted worker lifecycle snapshot.
    fn snapshot(&self) -> WorkerSnapshot;
    /// Returns coherent framebuffer metadata without copying pixels.
    fn framebuffer_metadata(&self) -> FramebufferMetadata;
    /// Captures or conditionally validates the current PNG screenshot.
    fn capture_screenshot(
        &self,
        if_none_match: Option<&str>,
    ) -> Result<ScreenshotOutcome, ScreenshotError>;
    /// Executes one queued command and waits for bounded worker acknowledgement.
    fn execute_command(
        &self,
        command: WorkerCommand,
        timeout: Duration,
    ) -> Result<u64, DesktopError>;
    /// Returns the last valid inbound clipboard snapshot.
    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError>;
    /// Returns the current bounded command queue depth.
    fn command_queue_depth(&self) -> usize {
        0
    }
    /// Returns the configured bounded command queue capacity.
    fn command_queue_capacity(&self) -> usize {
        0
    }
}

/// Production HTTP backend over one worker client and screenshot service.
pub struct WorkerHttpBackend {
    client: WorkerClient,
    screenshots: ScreenshotService,
}

impl WorkerHttpBackend {
    /// Creates a production backend using validated controller configuration.
    pub fn new(client: WorkerClient, config: &ControllerConfig) -> Result<Self, ScreenshotError> {
        let screenshots = client.screenshot_service(
            &config.process_instance,
            config.screenshot_concurrency,
            config.screenshot_timeout,
        )?;
        Ok(Self {
            client,
            screenshots,
        })
    }
}

impl HttpBackend for WorkerHttpBackend {
    fn snapshot(&self) -> WorkerSnapshot {
        self.client.snapshot()
    }

    fn framebuffer_metadata(&self) -> FramebufferMetadata {
        self.client.framebuffer_metadata()
    }

    fn capture_screenshot(
        &self,
        if_none_match: Option<&str>,
    ) -> Result<ScreenshotOutcome, ScreenshotError> {
        self.screenshots.capture(if_none_match)
    }

    fn execute_command(
        &self,
        command: WorkerCommand,
        timeout: Duration,
    ) -> Result<u64, DesktopError> {
        let ticket = self.client.submit(command)?;
        let command_id = ticket.id();
        ticket.wait(timeout)?;
        Ok(command_id)
    }

    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {
        self.client.clipboard_snapshot()
    }

    fn command_queue_depth(&self) -> usize {
        self.client.command_queue_depth()
    }

    fn command_queue_capacity(&self) -> usize {
        self.client.command_queue_capacity()
    }
}

/// Shared router state.
#[derive(Clone)]
pub struct HttpState {
    backend: Arc<dyn HttpBackend>,
    api_token: Arc<str>,
    process_instance: Arc<str>,
    request_sequence: Arc<AtomicU64>,
    shutting_down: Arc<AtomicBool>,
    maximum_json_bytes: usize,
    command_ack_timeout: Duration,
    events: EventHub,
    metrics: Metrics,
}

impl HttpState {
    /// Creates validated HTTP state over one backend.
    pub fn new(
        backend: Arc<dyn HttpBackend>,
        api_token: Arc<str>,
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
        api_token: Arc<str>,
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

    /// Creates production HTTP state from a worker and validated configuration.
    pub fn from_worker(
        client: WorkerClient,
        events: EventHub,
        metrics: Metrics,
        config: &ControllerConfig,
    ) -> Result<Self, HttpBuildError> {
        let backend = WorkerHttpBackend::new(client, config).map_err(HttpBuildError::Screenshot)?;
        Self::new_with_observability(
            Arc::new(backend),
            Arc::clone(&config.api_token),
            Arc::clone(&config.process_instance),
            config.maximum_json_bytes,
            config.command_ack_timeout,
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

    fn next_request_id(&self) -> RequestId {
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

/// Builds the authenticated controller router.
pub fn router(state: HttpState) -> Router {
    let protected = Router::new()
        .route("/status", get(status))
        .route("/display", get(display))
        .route("/screenshot.png", get(screenshot))
        .route("/events", get(events))
        .route("/metrics", get(metrics_endpoint))
        .route("/pointer/move", post(pointer_move))
        .route("/pointer/button", post(pointer_button))
        .route("/pointer/click", post(pointer_click))
        .route("/pointer/double-click", post(pointer_double_click))
        .route("/pointer/scroll", post(pointer_scroll))
        .route("/keyboard/key", post(keyboard_key))
        .route("/keyboard/chord", post(keyboard_chord))
        .route("/keyboard/text", post(keyboard_text))
        .route("/clipboard", get(clipboard).put(set_clipboard))
        .route("/connection/reconnect", post(reconnect))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            require_bearer,
        ));

    Router::new()
        .route("/health/live", get(liveness))
        .route("/health/ready", get(readiness))
        .nest("/v1", protected)
        .layer(DefaultBodyLimit::max(state.maximum_json_bytes))
        .layer(middleware::from_fn_with_state(state.clone(), access_log))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            assign_request_id,
        ))
        .with_state(state)
}

#[derive(Clone)]
struct RequestId(Arc<str>);

#[derive(Serialize)]
struct HealthResponse {
    status: &'static str,
}

#[derive(Serialize)]
struct StatusResponse {
    state: &'static str,
    started_at_unix_ms: u64,
    connected_at_unix_ms: Option<u64>,
    last_message_at_unix_ms: Option<u64>,
    reconnect_attempts: u32,
    last_failure: Option<&'static str>,
    framebuffer_revision: Option<u64>,
    rejected_commands: u64,
    dropped_events: u64,
    fatal_exit: bool,
    shutting_down: bool,
}

#[derive(Serialize)]
struct DisplayResponse {
    status: &'static str,
    width: u32,
    height: u32,
    depth: u8,
    revision: u64,
    updated_at_unix_ms: u64,
    complete: bool,
}

#[derive(Serialize)]
struct CommandAcceptedResponse {
    command_id: u64,
    status: &'static str,
}

#[derive(Serialize)]
struct ClipboardResponse {
    text: String,
    revision: u64,
    updated_at_unix_ms: u64,
}

#[derive(Serialize)]
struct ErrorEnvelope<'a> {
    error: ErrorBody<'a>,
}

#[derive(Serialize)]
struct ErrorBody<'a> {
    code: &'static str,
    message: &'static str,
    request_id: &'a str,
}

struct ApiError {
    status: StatusCode,
    code: &'static str,
    message: &'static str,
    request_id: RequestId,
}

impl ApiError {
    fn new(
        status: StatusCode,
        code: &'static str,
        message: &'static str,
        request_id: RequestId,
    ) -> Self {
        Self {
            status,
            code,
            message,
            request_id,
        }
    }

    fn unauthorized(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::UNAUTHORIZED,
            "unauthorized",
            "authentication required",
            request_id,
        )
    }

    fn not_ready(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "not_ready",
            "controller is not ready",
            request_id,
        )
    }

    fn framebuffer_unavailable(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "framebuffer_unavailable",
            "current framebuffer is unavailable",
            request_id,
        )
    }

    fn shutting_down(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "shutting_down",
            "controller is shutting down",
            request_id,
        )
    }

    fn invalid_json(request_id: RequestId, payload_too_large: bool) -> Self {
        if payload_too_large {
            Self::new(
                StatusCode::PAYLOAD_TOO_LARGE,
                "payload_too_large",
                "request body exceeds the configured limit",
                request_id,
            )
        } else {
            Self::new(
                StatusCode::BAD_REQUEST,
                "invalid_json",
                "request body is not valid JSON",
                request_id,
            )
        }
    }

    fn internal(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::INTERNAL_SERVER_ERROR,
            "internal_error",
            DEFAULT_ERROR_MESSAGE,
            request_id,
        )
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = Json(ErrorEnvelope {
            error: ErrorBody {
                code: self.code,
                message: self.message,
                request_id: &self.request_id.0,
            },
        });
        let mut response = body.into_response();
        *response.status_mut() = self.status;
        response
    }
}

async fn assign_request_id(
    State(state): State<HttpState>,
    mut request: Request,
    next: Next,
) -> Response {
    let request_id = request
        .headers()
        .get(&REQUEST_ID_HEADER)
        .and_then(|value| value.to_str().ok())
        .filter(|value| valid_request_id(value))
        .map(|value| RequestId(Arc::from(value)))
        .unwrap_or_else(|| state.next_request_id());
    request.extensions_mut().insert(request_id.clone());

    let mut response = next.run(request).await;
    if let Ok(value) = HeaderValue::from_str(&request_id.0) {
        response.headers_mut().insert(REQUEST_ID_HEADER, value);
    }
    response
}

struct AccessLogContext {
    method: Method,
    path: String,
    request_id: RequestId,
    authorization: &'static str,
}

impl AccessLogContext {
    fn from_request(request: &Request) -> Self {
        Self {
            method: request.method().clone(),
            path: request.uri().path().to_owned(),
            request_id: request_id(request),
            authorization: if request.headers().contains_key(AUTHORIZATION) {
                "[REDACTED]"
            } else {
                "absent"
            },
        }
    }
}

async fn access_log(State(state): State<HttpState>, request: Request, next: Next) -> Response {
    let context = AccessLogContext::from_request(&request);
    let started = Instant::now();
    let span = tracing::info_span!(
        "http_request",
        method = %context.method,
        path = %context.path,
        request_id = %context.request_id.0,
    );
    let response = next.run(request).instrument(span).await;
    let elapsed = started.elapsed();
    state
        .metrics
        .record_http(response.status().as_u16(), elapsed);
    tracing::info!(
        method = %context.method,
        path = %context.path,
        status = response.status().as_u16(),
        request_id = %context.request_id.0,
        authorization = context.authorization,
        duration_ms = u64::try_from(elapsed.as_millis()).unwrap_or(u64::MAX),
        "http_access"
    );
    response
}

#[cfg(test)]
fn format_access_log(context: &AccessLogContext, status: StatusCode, elapsed: Duration) -> String {
    format!(
        "http_access method={} path={} status={} request_id={} authorization={} duration_ms={}",
        context.method,
        context.path,
        status.as_u16(),
        context.request_id.0,
        context.authorization,
        elapsed.as_millis()
    )
}

async fn require_bearer(State(state): State<HttpState>, request: Request, next: Next) -> Response {
    let request_id = request_id(&request);
    let authorized = request
        .headers()
        .get(AUTHORIZATION)
        .is_some_and(|value| bearer_matches(value.as_bytes(), state.api_token.as_bytes()));
    if !authorized {
        state.metrics.record_auth_failure();
        tracing::warn!(request_id = %request_id.0, "authentication_rejected");
        return ApiError::unauthorized(request_id).into_response();
    }
    next.run(request).await
}

async fn events(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    websocket: WebSocketUpgrade,
) -> Result<Response, ApiError> {
    let subscription = state.events.subscribe().map_err(|WebSocketCapacityError| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "websocket_capacity",
            "WebSocket client capacity is exhausted",
            request_id,
        )
    })?;
    let snapshot = state.backend.snapshot();
    let clipboard_revision = state
        .backend
        .clipboard_snapshot()
        .ok()
        .map(|clipboard| clipboard.revision);
    let initial = state.events.snapshot_event(&snapshot, clipboard_revision);
    let events = state.events.clone();
    Ok(websocket.on_upgrade(move |socket| async move {
        events.serve(socket, subscription, initial).await;
    }))
}

async fn metrics_endpoint(State(state): State<HttpState>) -> Response {
    let snapshot = state.backend.snapshot();
    let body = state.metrics.render(
        &snapshot,
        state.backend.command_queue_depth(),
        state.backend.command_queue_capacity(),
    );
    let mut response = Response::new(Body::from(body));
    response.headers_mut().insert(
        CONTENT_TYPE,
        HeaderValue::from_static("text/plain; version=0.0.4; charset=utf-8"),
    );
    response
}

async fn liveness() -> Json<HealthResponse> {
    Json(HealthResponse { status: "alive" })
}

async fn readiness(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<Json<HealthResponse>, ApiError> {
    let snapshot = state.backend.snapshot();
    let framebuffer = state.backend.framebuffer_metadata();
    if ready(&state, &snapshot, framebuffer) {
        Ok(Json(HealthResponse { status: "ready" }))
    } else {
        Err(ApiError::not_ready(request_id))
    }
}

async fn status(State(state): State<HttpState>) -> Json<StatusResponse> {
    let snapshot = state.backend.snapshot();
    Json(StatusResponse {
        state: connection_state_name(snapshot.state),
        started_at_unix_ms: unix_milliseconds(snapshot.started_at),
        connected_at_unix_ms: snapshot.connected_at.map(unix_milliseconds),
        last_message_at_unix_ms: snapshot.last_message_at.map(unix_milliseconds),
        reconnect_attempts: snapshot.reconnect_attempts,
        last_failure: snapshot.last_failure.map(worker_failure_name),
        framebuffer_revision: snapshot.framebuffer_revision,
        rejected_commands: snapshot.rejected_commands,
        dropped_events: snapshot.dropped_events,
        fatal_exit: snapshot.fatal_exit,
        shutting_down: state.is_shutting_down(),
    })
}

async fn display(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<Json<DisplayResponse>, ApiError> {
    let metadata = state.backend.framebuffer_metadata();
    if metadata.status != FramebufferStatus::Current {
        return Err(ApiError::framebuffer_unavailable(request_id));
    }
    let (Some(width), Some(height), Some(updated_at)) =
        (metadata.width, metadata.height, metadata.updated_at)
    else {
        return Err(ApiError::framebuffer_unavailable(request_id));
    };
    Ok(Json(DisplayResponse {
        status: framebuffer_status_name(metadata.status),
        width,
        height,
        depth: 24,
        revision: metadata.revision,
        updated_at_unix_ms: unix_milliseconds(updated_at),
        complete: true,
    }))
}

async fn screenshot(
    State(state): State<HttpState>,
    headers: HeaderMap,
    Extension(request_id): Extension<RequestId>,
) -> Result<Response, ApiError> {
    let if_none_match = headers
        .get(IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    let backend = Arc::clone(&state.backend);
    let started = Instant::now();
    state.metrics.screenshot_started();
    let joined =
        tokio::task::spawn_blocking(move || backend.capture_screenshot(if_none_match.as_deref()))
            .await;
    let result = match joined {
        Ok(Ok(result)) => {
            state
                .metrics
                .screenshot_succeeded(&result, started.elapsed());
            result
        }
        Ok(Err(error)) => {
            state
                .metrics
                .screenshot_failed(Some(error), started.elapsed());
            return Err(screenshot_error(error, request_id));
        }
        Err(_) => {
            state.metrics.screenshot_failed(None, started.elapsed());
            return Err(ApiError::internal(request_id));
        }
    };

    match result {
        ScreenshotOutcome::NotModified { headers } => {
            let mut response = Response::new(Body::empty());
            *response.status_mut() = StatusCode::NOT_MODIFIED;
            insert_screenshot_headers(&mut response, &headers, request_id)?;
            Ok(response)
        }
        ScreenshotOutcome::Png { headers, bytes, .. } => {
            let mut response = Response::new(Body::from(bytes));
            *response.status_mut() = StatusCode::OK;
            insert_screenshot_headers(&mut response, &headers, request_id)?;
            Ok(response)
        }
    }
}

async fn pointer_move(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<PointerMoveRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    let display = current_display(&state, request_id.clone())?;
    let command = payload
        .into_command(display)
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(state, request_id, command).await
}

async fn pointer_button(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<PointerButtonRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    let display = current_display(&state, request_id.clone())?;
    let command = payload
        .into_command(display)
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(state, request_id, command).await
}

async fn pointer_click(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<PointerClickRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    let display = current_display(&state, request_id.clone())?;
    let command = payload
        .into_command(display)
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(state, request_id, command).await
}

async fn pointer_double_click(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<PointerDoubleClickRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    let display = current_display(&state, request_id.clone())?;
    let command = payload
        .into_command(display)
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(state, request_id, command).await
}

async fn pointer_scroll(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<PointerScrollRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    let display = current_display(&state, request_id.clone())?;
    let command = payload
        .into_command(display)
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(state, request_id, command).await
}

async fn keyboard_key(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<KeyRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    execute_command(state, request_id, payload.into_command()).await
}

async fn keyboard_chord(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<ChordRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    let keys = payload
        .into_domain()
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(state, request_id, WorkerCommand::Chord { keys }).await
}

async fn keyboard_text(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<TextRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    payload
        .validate()
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(
        state,
        request_id,
        WorkerCommand::TypeText { text: payload.text },
    )
    .await
}

async fn clipboard(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<Json<ClipboardResponse>, ApiError> {
    let snapshot = state
        .backend
        .clipboard_snapshot()
        .map_err(|error| domain_error(error, request_id))?;
    Ok(Json(ClipboardResponse {
        text: snapshot.text.to_string(),
        revision: snapshot.revision,
        updated_at_unix_ms: unix_milliseconds(snapshot.updated_at),
    }))
}

async fn set_clipboard(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<ClipboardRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    payload
        .validate()
        .map_err(|error| domain_error(error, request_id.clone()))?;
    execute_command(
        state,
        request_id,
        WorkerCommand::SetClipboard { text: payload.text },
    )
    .await
}

async fn reconnect(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    execute_command(state, request_id, WorkerCommand::Reconnect).await
}

fn json_payload<T>(
    payload: Result<Json<T>, JsonRejection>,
    request_id: RequestId,
) -> Result<T, ApiError> {
    payload.map(|Json(value)| value).map_err(|rejection| {
        ApiError::invalid_json(
            request_id,
            rejection.status() == StatusCode::PAYLOAD_TOO_LARGE,
        )
    })
}

fn current_display(state: &HttpState, request_id: RequestId) -> Result<DisplayInfo, ApiError> {
    let metadata = state.backend.framebuffer_metadata();
    if metadata.status != FramebufferStatus::Current {
        return Err(ApiError::framebuffer_unavailable(request_id));
    }
    let (Some(width), Some(height)) = (metadata.width, metadata.height) else {
        return Err(ApiError::framebuffer_unavailable(request_id));
    };
    DisplayInfo::new(width, height, 24, metadata.revision, true)
        .map_err(|error| domain_error(error, request_id))
}

async fn execute_command(
    state: HttpState,
    request_id: RequestId,
    command: WorkerCommand,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    if state.is_shutting_down() {
        return Err(ApiError::shutting_down(request_id));
    }
    state.metrics.record_command(&command);
    let backend = Arc::clone(&state.backend);
    let timeout = state.command_ack_timeout;
    let result = tokio::task::spawn_blocking(move || backend.execute_command(command, timeout))
        .await
        .map_err(|_| ApiError::internal(request_id.clone()))?;
    let result = match result {
        Ok(command_id) => command_id,
        Err(error) => {
            state.metrics.record_command_failure(&error);
            tracing::warn!(error = %error, request_id = %request_id.0, "desktop_command_failed");
            return Err(domain_error(error, request_id));
        }
    };
    Ok((
        StatusCode::ACCEPTED,
        Json(CommandAcceptedResponse {
            command_id: result,
            status: "accepted",
        }),
    ))
}

fn insert_screenshot_headers(
    response: &mut Response,
    headers: &crate::screenshot::ScreenshotHeaders,
    request_id: RequestId,
) -> Result<(), ApiError> {
    let etag = HeaderValue::from_str(&headers.etag).map_err(|_| ApiError::internal(request_id))?;
    response.headers_mut().insert(ETAG, etag);
    response.headers_mut().insert(
        CACHE_CONTROL,
        HeaderValue::from_static(headers.cache_control),
    );
    response
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static(headers.content_type));
    Ok(())
}

fn screenshot_error(error: ScreenshotError, request_id: RequestId) -> ApiError {
    use crate::framebuffer::FramebufferError;
    match error {
        ScreenshotError::Framebuffer(
            FramebufferError::Unavailable
            | FramebufferError::Stale
            | FramebufferError::DimensionsUnavailable,
        ) => ApiError::framebuffer_unavailable(request_id),
        ScreenshotError::Busy => ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "screenshot_busy",
            "screenshot capacity is exhausted",
            request_id,
        ),
        ScreenshotError::Timeout => ApiError::new(
            StatusCode::GATEWAY_TIMEOUT,
            "screenshot_timeout",
            "screenshot encoding timed out",
            request_id,
        ),
        ScreenshotError::Framebuffer(_)
        | ScreenshotError::InvalidConfiguration
        | ScreenshotError::ThreadSpawn
        | ScreenshotError::Encoding => ApiError::internal(request_id),
    }
}

fn domain_error(error: DesktopError, request_id: RequestId) -> ApiError {
    match error {
        DesktopError::InvalidCoordinate { .. } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_coordinate",
            "coordinate is outside the current display",
            request_id,
        ),
        DesktopError::DisplayUnavailable
        | DesktopError::FramebufferUnavailable
        | DesktopError::InvalidFramebufferDimensions => {
            ApiError::framebuffer_unavailable(request_id)
        }
        DesktopError::InvalidRectangle => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_rectangle",
            "framebuffer rectangle is invalid",
            request_id,
        ),
        DesktopError::ChordTooLong { .. } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "chord_too_long",
            "key chord exceeds the configured limit",
            request_id,
        ),
        DesktopError::TextTooLarge { .. } => ApiError::new(
            StatusCode::PAYLOAD_TOO_LARGE,
            "text_too_large",
            "text exceeds the configured limit",
            request_id,
        ),
        DesktopError::ClipboardTooLarge { .. } => ApiError::new(
            StatusCode::PAYLOAD_TOO_LARGE,
            "clipboard_too_large",
            "clipboard exceeds the configured limit",
            request_id,
        ),
        DesktopError::UnsupportedTextCharacter { .. } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "unsupported_text",
            "text contains an unsupported character",
            request_id,
        ),
        DesktopError::ClipboardContainsNul => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_clipboard",
            "clipboard contains a prohibited character",
            request_id,
        ),
        DesktopError::ScrollTooLarge { .. } => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "scroll_too_large",
            "scroll request exceeds the configured limit",
            request_id,
        ),
        DesktopError::CommandQueueFull => ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "command_queue_full",
            "command capacity is exhausted",
            request_id,
        ),
        DesktopError::WorkerUnavailable => ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "worker_unavailable",
            "desktop worker is unavailable",
            request_id,
        ),
        DesktopError::ClipboardUnavailable => ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "clipboard_unavailable",
            "clipboard is unavailable",
            request_id,
        ),
        DesktopError::Timeout => ApiError::new(
            StatusCode::GATEWAY_TIMEOUT,
            "command_timeout",
            "desktop command acknowledgement timed out",
            request_id,
        ),
        DesktopError::ReconnectRateLimited => ApiError::new(
            StatusCode::TOO_MANY_REQUESTS,
            "reconnect_rate_limited",
            "reconnect request is rate limited",
            request_id,
        ),
        DesktopError::Configuration(_) => ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_request",
            "request is not valid for the current operation",
            request_id,
        ),
        DesktopError::AuthenticationFailed
        | DesktopError::Transport
        | DesktopError::Protocol
        | DesktopError::Native => ApiError::new(
            StatusCode::BAD_GATEWAY,
            "desktop_operation_failed",
            "desktop operation failed",
            request_id,
        ),
    }
}

fn ready(state: &HttpState, snapshot: &WorkerSnapshot, framebuffer: FramebufferMetadata) -> bool {
    !state.is_shutting_down()
        && !snapshot.fatal_exit
        && snapshot.state == ConnectionState::Connected
        && framebuffer.status == FramebufferStatus::Current
        && framebuffer.width.is_some()
        && framebuffer.height.is_some()
        && framebuffer.updated_at.is_some()
}

fn request_id(request: &Request) -> RequestId {
    request
        .extensions()
        .get::<RequestId>()
        .cloned()
        .unwrap_or_else(|| RequestId(Arc::from("request-id-unavailable")))
}

fn bearer_matches(header: &[u8], expected: &[u8]) -> bool {
    let Some(candidate) = header.strip_prefix(b"Bearer ") else {
        return false;
    };
    !candidate.is_empty()
        && candidate.len() == expected.len()
        && bool::from(candidate.ct_eq(expected))
}

fn valid_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_REQUEST_ID_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn valid_process_instance(value: &str) -> bool {
    valid_request_id(value)
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

const fn framebuffer_status_name(status: FramebufferStatus) -> &'static str {
    match status {
        FramebufferStatus::Unavailable => "unavailable",
        FramebufferStatus::Incomplete => "incomplete",
        FramebufferStatus::Current => "current",
        FramebufferStatus::Stale => "stale",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::to_bytes;
    use axum::http::Request as HttpRequest;
    use serde_json::Value;
    use std::sync::Mutex;
    use std::time::Duration;
    use tower::ServiceExt;

    #[derive(Debug, Clone, Copy)]
    enum MockScreenshot {
        Png,
        NotModified,
        Unavailable,
    }

    struct MockBackend {
        snapshot: WorkerSnapshot,
        framebuffer: FramebufferMetadata,
        screenshot: Mutex<MockScreenshot>,
        commands: Mutex<Vec<WorkerCommand>>,
        execute_error: Mutex<Option<DesktopError>>,
        clipboard: Mutex<Option<ClipboardSnapshot>>,
        next_command_id: AtomicU64,
    }

    impl HttpBackend for MockBackend {
        fn snapshot(&self) -> WorkerSnapshot {
            self.snapshot.clone()
        }

        fn framebuffer_metadata(&self) -> FramebufferMetadata {
            self.framebuffer
        }

        fn capture_screenshot(
            &self,
            _if_none_match: Option<&str>,
        ) -> Result<ScreenshotOutcome, ScreenshotError> {
            let screenshot = *self
                .screenshot
                .lock()
                .unwrap_or_else(|error| error.into_inner());
            let headers = crate::screenshot::ScreenshotHeaders {
                etag: "\"test-7\"".to_owned(),
                content_type: "image/png",
                cache_control: "private, no-cache, max-age=0",
            };
            match screenshot {
                MockScreenshot::Png => Ok(ScreenshotOutcome::Png {
                    headers,
                    width: 2,
                    height: 2,
                    revision: 7,
                    bytes: vec![137, 80, 78, 71],
                }),
                MockScreenshot::NotModified => Ok(ScreenshotOutcome::NotModified { headers }),
                MockScreenshot::Unavailable => Err(ScreenshotError::Framebuffer(
                    crate::framebuffer::FramebufferError::Unavailable,
                )),
            }
        }

        fn execute_command(
            &self,
            command: WorkerCommand,
            _timeout: Duration,
        ) -> Result<u64, DesktopError> {
            if let Some(error) = self
                .execute_error
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .clone()
            {
                return Err(error);
            }
            self.commands
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .push(command);
            Ok(self.next_command_id.fetch_add(1, Ordering::Relaxed))
        }

        fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {
            self.clipboard
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .clone()
                .ok_or(DesktopError::ClipboardUnavailable)
        }
    }

    fn test_state_with_backend(
        ready: bool,
        screenshot: MockScreenshot,
    ) -> (HttpState, Arc<MockBackend>) {
        let now = UNIX_EPOCH + Duration::from_secs(100);
        let backend = Arc::new(MockBackend {
            snapshot: WorkerSnapshot {
                state: if ready {
                    ConnectionState::Connected
                } else {
                    ConnectionState::Connecting
                },
                started_at: now,
                connected_at: ready.then_some(now),
                last_message_at: ready.then_some(now),
                reconnect_attempts: 0,
                last_failure: None,
                framebuffer_revision: ready.then_some(7),
                rejected_commands: 0,
                dropped_events: 0,
                fatal_exit: false,
            },
            framebuffer: FramebufferMetadata {
                status: if ready {
                    FramebufferStatus::Current
                } else {
                    FramebufferStatus::Unavailable
                },
                width: ready.then_some(2),
                height: ready.then_some(2),
                revision: if ready { 7 } else { 0 },
                updated_at: ready.then_some(now),
            },
            screenshot: Mutex::new(screenshot),
            commands: Mutex::new(Vec::new()),
            execute_error: Mutex::new(None),
            clipboard: Mutex::new(None),
            next_command_id: AtomicU64::new(1),
        });
        let state = HttpState::new(
            backend.clone(),
            Arc::from("test-token"),
            Arc::from("test-process"),
            4096,
            Duration::from_secs(1),
        )
        .expect("valid test state");
        (state, backend)
    }

    fn test_state(ready: bool, screenshot: MockScreenshot) -> HttpState {
        test_state_with_backend(ready, screenshot).0
    }

    fn request(uri: &str) -> axum::http::request::Builder {
        HttpRequest::builder().uri(uri)
    }

    async fn json_body(response: Response) -> Value {
        let bytes = to_bytes(response.into_body(), 64 * 1024)
            .await
            .expect("bounded response body");
        serde_json::from_slice(&bytes).expect("JSON response")
    }

    #[tokio::test]
    async fn health_routes_are_public_and_readiness_fails_closed() {
        let state = test_state(false, MockScreenshot::Unavailable);
        let app = router(state.clone());

        let response = app
            .clone()
            .oneshot(
                request("/health/live")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        assert!(response.headers().contains_key(&REQUEST_ID_HEADER));

        let response = app
            .clone()
            .oneshot(
                request("/health/ready")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "not_ready");

        let ready = router(test_state(true, MockScreenshot::Png));
        let response = ready
            .oneshot(
                request("/health/ready")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);

        state.begin_shutdown();
        let response = app
            .oneshot(
                request("/health/ready")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    }

    #[tokio::test]
    async fn protected_routes_use_one_generic_bearer_failure() {
        let app = router(test_state(true, MockScreenshot::Png));
        for request in [
            request("/v1/status").body(Body::empty()).expect("request"),
            request("/v1/status?token=test-token")
                .body(Body::empty())
                .expect("request"),
            request("/v1/status")
                .header(AUTHORIZATION, "Basic test-token")
                .body(Body::empty())
                .expect("request"),
            request("/v1/status")
                .header(AUTHORIZATION, "Bearer wrong-token")
                .body(Body::empty())
                .expect("request"),
        ] {
            let response = app.clone().oneshot(request).await.expect("response");
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
            let body = json_body(response).await;
            assert_eq!(body["error"]["code"], "unauthorized");
            assert_eq!(body["error"]["message"], "authentication required");
        }
    }

    #[tokio::test]
    async fn accepted_request_id_is_returned_in_error_header_and_body() {
        let app = router(test_state(true, MockScreenshot::Png));
        let response = app
            .oneshot(
                request("/v1/status")
                    .header(&REQUEST_ID_HEADER, "caller-123")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(
            response.headers().get(&REQUEST_ID_HEADER),
            Some(&HeaderValue::from_static("caller-123"))
        );
        let body = json_body(response).await;
        assert_eq!(body["error"]["request_id"], "caller-123");
    }

    #[tokio::test]
    async fn invalid_request_id_is_replaced() {
        let app = router(test_state(true, MockScreenshot::Png));
        let response = app
            .oneshot(
                request("/health/live")
                    .header(&REQUEST_ID_HEADER, "contains space")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        let request_id = response
            .headers()
            .get(&REQUEST_ID_HEADER)
            .expect("request ID")
            .to_str()
            .expect("ASCII request ID");
        assert!(request_id.starts_with("test-process-"));
    }

    #[tokio::test]
    async fn authenticated_status_and_display_are_redacted_and_stable() {
        let app = router(test_state(true, MockScreenshot::Png));
        let response = app
            .clone()
            .oneshot(
                request("/v1/status")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = json_body(response).await;
        assert_eq!(body["state"], "connected");
        assert_eq!(body["framebuffer_revision"], 7);
        assert!(!body.to_string().contains("test-token"));

        let response = app
            .oneshot(
                request("/v1/display")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = json_body(response).await;
        assert_eq!(body["width"], 2);
        assert_eq!(body["height"], 2);
        assert_eq!(body["depth"], 24);
        assert_eq!(body["revision"], 7);
        assert_eq!(body["complete"], true);
    }

    #[tokio::test]
    async fn display_unavailable_uses_stable_json_error() {
        let app = router(test_state(false, MockScreenshot::Unavailable));
        let response = app
            .oneshot(
                request("/v1/display")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "framebuffer_unavailable");
    }

    #[tokio::test]
    async fn screenshot_png_and_conditional_response_preserve_headers() {
        let png_app = router(test_state(true, MockScreenshot::Png));
        let response = png_app
            .oneshot(
                request("/v1/screenshot.png")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers().get(ETAG),
            Some(&HeaderValue::from_static("\"test-7\""))
        );
        assert_eq!(
            response.headers().get(CONTENT_TYPE),
            Some(&HeaderValue::from_static("image/png"))
        );
        let bytes = to_bytes(response.into_body(), 1024)
            .await
            .expect("PNG body");
        assert_eq!(bytes.as_ref(), &[137, 80, 78, 71]);

        let not_modified_app = router(test_state(true, MockScreenshot::NotModified));
        let response = not_modified_app
            .oneshot(
                request("/v1/screenshot.png")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .header(IF_NONE_MATCH, "\"test-7\"")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::NOT_MODIFIED);
        assert_eq!(
            response.headers().get(ETAG),
            Some(&HeaderValue::from_static("\"test-7\""))
        );
    }

    #[tokio::test]
    async fn screenshot_unavailable_is_bounded_json_error() {
        let app = router(test_state(false, MockScreenshot::Unavailable));
        let response = app
            .oneshot(
                request("/v1/screenshot.png")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "framebuffer_unavailable");
    }

    #[test]
    fn access_log_redacts_authorization_and_query_values() {
        let mut logged_request = request("/v1/status?token=query-secret")
            .header(AUTHORIZATION, "Bearer header-secret")
            .body(Body::empty())
            .expect("request");
        logged_request
            .extensions_mut()
            .insert(RequestId(Arc::from("caller-1")));
        let context = AccessLogContext::from_request(&logged_request);
        let line = format_access_log(&context, StatusCode::OK, Duration::from_millis(12));

        assert!(line.contains("method=GET"));
        assert!(line.contains("path=/v1/status"));
        assert!(line.contains("status=200"));
        assert!(line.contains("request_id=caller-1"));
        assert!(line.contains("authorization=[REDACTED]"));
        assert!(!line.contains("header-secret"));
        assert!(!line.contains("query-secret"));
        assert!(!line.contains("?token="));
    }

    #[test]
    fn state_validation_and_bearer_comparison_fail_closed() {
        let (_, concrete) = test_state_with_backend(true, MockScreenshot::Png);
        let backend: Arc<dyn HttpBackend> = concrete;
        assert!(
            HttpState::new(
                Arc::clone(&backend),
                Arc::from(""),
                Arc::from("process"),
                1,
                Duration::from_secs(1),
            )
            .is_err()
        );
        assert!(
            HttpState::new(
                Arc::clone(&backend),
                Arc::from("token"),
                Arc::from("bad process"),
                1,
                Duration::from_secs(1),
            )
            .is_err()
        );
        assert!(
            HttpState::new(
                Arc::clone(&backend),
                Arc::from("token"),
                Arc::from("process"),
                0,
                Duration::from_secs(1),
            )
            .is_err()
        );
        assert!(
            HttpState::new(
                backend,
                Arc::from("token"),
                Arc::from("process"),
                1,
                Duration::ZERO,
            )
            .is_err()
        );
        assert!(bearer_matches(b"Bearer token", b"token"));
        assert!(!bearer_matches(b"Bearer Token", b"token"));
        assert!(!bearer_matches(b"Basic token", b"token"));
        assert!(!bearer_matches(b"Bearer", b"token"));
    }

    fn authenticated_json_request(
        method: &str,
        uri: &str,
        value: serde_json::Value,
    ) -> axum::http::Request<Body> {
        request(uri)
            .method(method)
            .header(AUTHORIZATION, "Bearer test-token")
            .header(CONTENT_TYPE, "application/json")
            .body(Body::from(value.to_string()))
            .expect("request")
    }

    #[tokio::test]
    async fn pointer_routes_return_202_and_preserve_preflighted_commands() {
        let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
        let app = router(state);
        let fixtures = [
            ("/v1/pointer/move", serde_json::json!({"x": 1, "y": 1})),
            (
                "/v1/pointer/button",
                serde_json::json!({"x": 1, "y": 1, "button": "left", "pressed": true}),
            ),
            (
                "/v1/pointer/click",
                serde_json::json!({"x": 1, "y": 1, "button": "middle"}),
            ),
            (
                "/v1/pointer/double-click",
                serde_json::json!({"x": 1, "y": 1, "button": "right", "interval_ms": 50}),
            ),
            (
                "/v1/pointer/scroll",
                serde_json::json!({"x": 1, "y": 1, "delta_y": -2}),
            ),
        ];
        for (index, (uri, payload)) in fixtures.into_iter().enumerate() {
            let response = app
                .clone()
                .oneshot(authenticated_json_request("POST", uri, payload))
                .await
                .expect("response");
            assert_eq!(response.status(), StatusCode::ACCEPTED);
            let body = json_body(response).await;
            assert_eq!(body["status"], "accepted");
            assert_eq!(body["command_id"], u64::try_from(index + 1).unwrap());
        }
        let commands = backend
            .commands
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        assert_eq!(commands.len(), 5);
        assert!(matches!(commands[0], WorkerCommand::MovePointer { .. }));
        assert!(matches!(commands[1], WorkerCommand::SetButton { .. }));
        assert!(matches!(commands[2], WorkerCommand::Click { .. }));
        assert!(matches!(commands[3], WorkerCommand::DoubleClick { .. }));
        assert!(matches!(
            commands[4],
            WorkerCommand::Scroll {
                delta_x: 0,
                delta_y: -2,
                ..
            }
        ));
    }

    #[tokio::test]
    async fn invalid_pointer_request_never_reaches_worker() {
        let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
        let response = router(state)
            .oneshot(authenticated_json_request(
                "POST",
                "/v1/pointer/move",
                serde_json::json!({"x": 2, "y": 0}),
            ))
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "invalid_coordinate");
        assert!(
            backend
                .commands
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .is_empty()
        );
    }

    #[tokio::test]
    async fn keyboard_text_and_clipboard_preflight_before_worker_execution() {
        let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
        let app = router(state);
        for (uri, payload) in [
            (
                "/v1/keyboard/key",
                serde_json::json!({"key": "F5", "action": "down"}),
            ),
            (
                "/v1/keyboard/chord",
                serde_json::json!({"keys": ["CTRL_LEFT", "SHIFT_LEFT", "F6"]}),
            ),
            (
                "/v1/keyboard/text",
                serde_json::json!({"text": "safe text\n"}),
            ),
            (
                "/v1/clipboard",
                serde_json::json!({"text": "clipboard value"}),
            ),
        ] {
            let method = if uri == "/v1/clipboard" {
                "PUT"
            } else {
                "POST"
            };
            let response = app
                .clone()
                .oneshot(authenticated_json_request(method, uri, payload))
                .await
                .expect("response");
            assert_eq!(response.status(), StatusCode::ACCEPTED);
        }
        let count_before = backend
            .commands
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .len();
        let response = app
            .oneshot(authenticated_json_request(
                "POST",
                "/v1/keyboard/text",
                serde_json::json!({"text": "prefix☃suffix"}),
            ))
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "unsupported_text");
        assert_eq!(
            backend
                .commands
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .len(),
            count_before
        );
    }

    #[tokio::test]
    async fn clipboard_snapshot_and_unavailable_error_are_stable() {
        let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
        let app = router(state);
        let response = app
            .clone()
            .oneshot(
                request("/v1/clipboard")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "clipboard_unavailable");

        *backend
            .clipboard
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(ClipboardSnapshot {
            text: Arc::from("inbound clipboard"),
            revision: 9,
            updated_at: UNIX_EPOCH + Duration::from_secs(200),
        });
        let response = app
            .oneshot(
                request("/v1/clipboard")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = json_body(response).await;
        assert_eq!(body["text"], "inbound clipboard");
        assert_eq!(body["revision"], 9);
        assert_eq!(body["updated_at_unix_ms"], 200_000);
    }

    #[tokio::test]
    async fn worker_failures_map_to_stable_payload_free_errors() {
        for (error, status, code) in [
            (
                DesktopError::CommandQueueFull,
                StatusCode::SERVICE_UNAVAILABLE,
                "command_queue_full",
            ),
            (
                DesktopError::WorkerUnavailable,
                StatusCode::SERVICE_UNAVAILABLE,
                "worker_unavailable",
            ),
            (
                DesktopError::Timeout,
                StatusCode::GATEWAY_TIMEOUT,
                "command_timeout",
            ),
            (
                DesktopError::ReconnectRateLimited,
                StatusCode::TOO_MANY_REQUESTS,
                "reconnect_rate_limited",
            ),
        ] {
            let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
            *backend
                .execute_error
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(error);
            let response = router(state)
                .oneshot(
                    request("/v1/connection/reconnect")
                        .method("POST")
                        .header(AUTHORIZATION, "Bearer test-token")
                        .body(Body::empty())
                        .expect("request"),
                )
                .await
                .expect("response");
            assert_eq!(response.status(), status);
            let body = json_body(response).await;
            assert_eq!(body["error"]["code"], code);
            assert!(!body.to_string().contains("test-token"));
        }
    }

    #[tokio::test]
    async fn shutdown_and_oversized_json_fail_before_worker_execution() {
        let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
        state.begin_shutdown();
        let app = router(state);
        let response = app
            .clone()
            .oneshot(authenticated_json_request(
                "POST",
                "/v1/keyboard/key",
                serde_json::json!({"key": "F5", "action": "down"}),
            ))
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "shutting_down");

        let oversized = format!(r#"{{"text":"{}"}}"#, "x".repeat(5000));
        let response = app
            .oneshot(
                request("/v1/keyboard/text")
                    .method("POST")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .header(CONTENT_TYPE, "application/json")
                    .body(Body::from(oversized))
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
        let body = json_body(response).await;
        assert_eq!(body["error"]["code"], "payload_too_large");
        assert!(
            backend
                .commands
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .is_empty()
        );
    }

    #[tokio::test]
    async fn authenticated_metrics_use_fixed_labels_and_exclude_secrets() {
        let app = router(test_state(true, MockScreenshot::Png));
        let response = app
            .oneshot(
                request("/v1/metrics")
                    .header(AUTHORIZATION, "Bearer test-token")
                    .body(Body::empty())
                    .expect("request"),
            )
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK);
        let body = to_bytes(response.into_body(), 256 * 1024)
            .await
            .expect("bounded metrics body");
        let body = String::from_utf8(body.to_vec()).expect("UTF-8 metrics");
        assert!(body.contains("vrc_connection_state{state=\"connected\"} 1"));
        assert!(body.contains("vrc_worker_command_queue_capacity 0"));
        assert!(!body.contains("test-token"));
        assert!(!body.contains("request_id"));
    }
}
