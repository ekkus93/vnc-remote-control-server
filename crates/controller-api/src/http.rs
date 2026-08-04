//! Authenticated read-only HTTP routing for the controller service.
//!
//! The router deliberately depends on a narrow backend trait. Production wraps
//! `WorkerClient`; unit tests use deterministic in-memory fixtures without
//! starting a native VNC thread. All `/v1/*` routes share one bearer-auth layer,
//! while liveness and readiness remain public orchestration endpoints.

use crate::config::ControllerConfig;
use crate::framebuffer::{FramebufferMetadata, FramebufferStatus};
use crate::screenshot::{ScreenshotError, ScreenshotOutcome, ScreenshotService};
use crate::worker::{WorkerClient, WorkerFailureKind, WorkerSnapshot};
use axum::body::Body;
use axum::extract::{DefaultBodyLimit, Request, State};
use axum::http::header::{AUTHORIZATION, CACHE_CONTROL, CONTENT_TYPE, ETAG, IF_NONE_MATCH};
use axum::http::{HeaderMap, HeaderName, HeaderValue, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use remote_desktop_core::ConnectionState;
use serde::Serialize;
use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use subtle::ConstantTimeEq;

const REQUEST_ID_HEADER: HeaderName = HeaderName::from_static("x-request-id");
const MAX_REQUEST_ID_BYTES: usize = 64;
const DEFAULT_ERROR_MESSAGE: &str = "request could not be completed";

/// Read-only backend required by the first HTTP milestone.
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
}

impl HttpState {
    /// Creates validated HTTP state over one backend.
    pub fn new(
        backend: Arc<dyn HttpBackend>,
        api_token: Arc<str>,
        process_instance: Arc<str>,
        maximum_json_bytes: usize,
    ) -> Result<Self, HttpBuildError> {
        if api_token.is_empty() {
            return Err(HttpBuildError::EmptyApiToken);
        }
        if maximum_json_bytes == 0 {
            return Err(HttpBuildError::InvalidBodyLimit);
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
        })
    }

    /// Creates production HTTP state from a worker and validated configuration.
    pub fn from_worker(
        client: WorkerClient,
        config: &ControllerConfig,
    ) -> Result<Self, HttpBuildError> {
        let backend = WorkerHttpBackend::new(client, config).map_err(HttpBuildError::Screenshot)?;
        Self::new(
            Arc::new(backend),
            Arc::clone(&config.api_token),
            Arc::clone(&config.process_instance),
            config.maximum_json_bytes,
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
    /// The screenshot service could not be constructed.
    Screenshot(ScreenshotError),
}

impl fmt::Display for HttpBuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::EmptyApiToken => "API token is empty",
            Self::InvalidProcessInstance => "process instance is invalid",
            Self::InvalidBodyLimit => "HTTP body limit is invalid",
            Self::Screenshot(_) => "screenshot service configuration is invalid",
        };
        formatter.write_str(message)
    }
}

impl Error for HttpBuildError {}

/// Builds the read-only authenticated controller router.
pub fn router(state: HttpState) -> Router {
    let protected = Router::new()
        .route("/status", get(status))
        .route("/display", get(display))
        .route("/screenshot.png", get(screenshot))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            require_bearer,
        ));

    Router::new()
        .route("/health/live", get(liveness))
        .route("/health/ready", get(readiness))
        .nest("/v1", protected)
        .layer(DefaultBodyLimit::max(state.maximum_json_bytes))
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

async fn require_bearer(State(state): State<HttpState>, request: Request, next: Next) -> Response {
    let request_id = request_id(&request);
    let authorized = request
        .headers()
        .get(AUTHORIZATION)
        .is_some_and(|value| bearer_matches(value.as_bytes(), state.api_token.as_bytes()));
    if !authorized {
        return ApiError::unauthorized(request_id).into_response();
    }
    next.run(request).await
}

async fn liveness() -> Json<HealthResponse> {
    Json(HealthResponse { status: "alive" })
}

async fn readiness(
    State(state): State<HttpState>,
    request: Request,
) -> Result<Json<HealthResponse>, ApiError> {
    let request_id = request_id(&request);
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
    request: Request,
) -> Result<Json<DisplayResponse>, ApiError> {
    let request_id = request_id(&request);
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
    request: Request,
) -> Result<Response, ApiError> {
    let request_id = request_id(&request);
    let if_none_match = headers
        .get(IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
        .map(str::to_owned);
    let backend = Arc::clone(&state.backend);
    let result =
        tokio::task::spawn_blocking(move || backend.capture_screenshot(if_none_match.as_deref()))
            .await
            .map_err(|_| ApiError::internal(request_id.clone()))?
            .map_err(|error| screenshot_error(error, request_id.clone()))?;

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
    }

    fn test_state(ready: bool, screenshot: MockScreenshot) -> HttpState {
        let now = UNIX_EPOCH + Duration::from_secs(100);
        let backend = MockBackend {
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
        };
        HttpState::new(
            Arc::new(backend),
            Arc::from("test-token"),
            Arc::from("test-process"),
            4096,
        )
        .expect("valid test state")
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
    fn state_validation_and_bearer_comparison_fail_closed() {
        let backend: Arc<dyn HttpBackend> = Arc::new(MockBackend {
            snapshot: test_state(true, MockScreenshot::Png).backend.snapshot(),
            framebuffer: test_state(true, MockScreenshot::Png)
                .backend
                .framebuffer_metadata(),
            screenshot: Mutex::new(MockScreenshot::Png),
        });
        assert!(
            HttpState::new(Arc::clone(&backend), Arc::from(""), Arc::from("process"), 1,).is_err()
        );
        assert!(
            HttpState::new(
                Arc::clone(&backend),
                Arc::from("token"),
                Arc::from("bad process"),
                1,
            )
            .is_err()
        );
        assert!(HttpState::new(backend, Arc::from("token"), Arc::from("process"), 0).is_err());
        assert!(bearer_matches(b"Bearer token", b"token"));
        assert!(!bearer_matches(b"Bearer Token", b"token"));
        assert!(!bearer_matches(b"Basic token", b"token"));
        assert!(!bearer_matches(b"Bearer", b"token"));
    }
}
