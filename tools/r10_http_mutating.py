from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, found {count}")
    return text.replace(old, new, 1)


def update_api_contract() -> None:
    path = Path("crates/controller-api/src/api_contract.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "use remote_desktop_core::{\n"
        "    DesktopError, KeyAction, KeyboardKey, validate_chord, validate_clipboard, validate_text,\n"
        "};\n",
        "use crate::input::{MAX_DOUBLE_CLICK_INTERVAL_MS, MIN_DOUBLE_CLICK_INTERVAL_MS};\n"
        "use remote_desktop_core::{\n"
        "    DesktopError, DisplayInfo, KeyAction, KeyboardKey, MouseButton, WorkerCommand,\n"
        "    validate_chord, validate_clipboard, validate_scroll, validate_text,\n"
        "};\n",
        "api imports",
    )

    pointer_types = r'''
/// Public pointer movement request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerMoveRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
}

impl PointerMoveRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        Ok(WorkerCommand::MovePointer {
            coordinate: display.validate_coordinate(self.x, self.y)?,
        })
    }
}

/// Public explicit mouse-button transition request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerButtonRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Mouse button to update.
    pub button: MouseButton,
    /// Whether the button must be held after the operation.
    pub pressed: bool,
}

impl PointerButtonRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        Ok(WorkerCommand::SetButton {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            button: self.button,
            pressed: self.pressed,
        })
    }
}

/// Public single-click request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerClickRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Mouse button to click.
    pub button: MouseButton,
}

impl PointerClickRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        Ok(WorkerCommand::Click {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            button: self.button,
        })
    }
}

/// Public atomic double-click request.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerDoubleClickRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Mouse button to click twice.
    pub button: MouseButton,
    /// Bounded delay between complete clicks.
    pub interval_ms: u64,
}

impl PointerDoubleClickRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        if !(MIN_DOUBLE_CLICK_INTERVAL_MS..=MAX_DOUBLE_CLICK_INTERVAL_MS)
            .contains(&self.interval_ms)
        {
            return Err(DesktopError::Configuration(
                "double-click interval is outside the supported range".to_owned(),
            ));
        }
        Ok(WorkerCommand::DoubleClick {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            button: self.button,
            interval_ms: self.interval_ms,
        })
    }
}

/// Public vertical wheel request. Horizontal scrolling is not part of v0.1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PointerScrollRequest {
    /// Horizontal coordinate in the current display.
    pub x: u32,
    /// Vertical coordinate in the current display.
    pub y: u32,
    /// Signed vertical wheel steps.
    pub delta_y: i32,
}

impl PointerScrollRequest {
    /// Converts a completely validated request into a worker command.
    pub fn into_command(self, display: DisplayInfo) -> Result<WorkerCommand, DesktopError> {
        validate_scroll(0, self.delta_y)?;
        Ok(WorkerCommand::Scroll {
            coordinate: display.validate_coordinate(self.x, self.y)?,
            delta_x: 0,
            delta_y: self.delta_y,
        })
    }
}

'''
    text = replace_once(
        text,
        "/// Public key transition request.\n",
        pointer_types + "/// Public key transition request.\n",
        "pointer request insertion",
    )

    text = replace_once(
        text,
        "pub struct KeyRequest {\n"
        "    /// Stable key string.\n"
        "    pub key: ApiKeyboardKey,\n"
        "    /// Requested transition.\n"
        "    pub action: KeyAction,\n"
        "}\n",
        "pub struct KeyRequest {\n"
        "    /// Stable key string.\n"
        "    pub key: ApiKeyboardKey,\n"
        "    /// Requested transition.\n"
        "    pub action: KeyAction,\n"
        "}\n\n"
        "impl KeyRequest {\n"
        "    /// Converts this validated public key request into a worker command.\n"
        "    pub fn into_command(self) -> WorkerCommand {\n"
        "        WorkerCommand::SetKey {\n"
        "            key: self.key.into_domain(),\n"
        "            pressed: self.action == KeyAction::Down,\n"
        "        }\n"
        "    }\n"
        "}\n",
        "key request conversion",
    )

    tests = r'''

    #[test]
    fn pointer_requests_preflight_complete_coordinates_and_bounds() {
        let display = display();
        assert_eq!(
            PointerMoveRequest { x: 1, y: 2 }
                .into_command(display)
                .expect("valid move"),
            WorkerCommand::MovePointer {
                coordinate: display
                    .validate_coordinate(1, 2)
                    .expect("known coordinate"),
            }
        );
        assert!(matches!(
            PointerClickRequest {
                x: display.width,
                y: 0,
                button: MouseButton::Left,
            }
            .into_command(display),
            Err(DesktopError::InvalidCoordinate { .. })
        ));
    }

    #[test]
    fn pointer_double_click_and_vertical_scroll_limits_are_explicit() {
        let display = display();
        assert!(
            PointerDoubleClickRequest {
                x: 0,
                y: 0,
                button: MouseButton::Left,
                interval_ms: MIN_DOUBLE_CLICK_INTERVAL_MS,
            }
            .into_command(display)
            .is_ok()
        );
        assert!(
            PointerDoubleClickRequest {
                x: 0,
                y: 0,
                button: MouseButton::Left,
                interval_ms: MAX_DOUBLE_CLICK_INTERVAL_MS + 1,
            }
            .into_command(display)
            .is_err()
        );
        assert!(
            PointerScrollRequest {
                x: 0,
                y: 0,
                delta_y: remote_desktop_core::MAX_SCROLL_STEPS,
            }
            .into_command(display)
            .is_ok()
        );
        assert!(matches!(
            PointerScrollRequest {
                x: 0,
                y: 0,
                delta_y: remote_desktop_core::MAX_SCROLL_STEPS + 1,
            }
            .into_command(display),
            Err(DesktopError::ScrollTooLarge { .. })
        ));
    }
'''
    closing = text.rfind("\n}\n")
    if closing < 0:
        raise SystemExit("api tests closing brace not found")
    text = text[:closing] + tests + text[closing:]
    path.write_text(text, encoding="utf-8")


def update_http() -> None:
    path = Path("crates/controller-api/src/http.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "//! Authenticated read-only HTTP routing for the controller service.\n",
        "//! Authenticated HTTP routing for the controller service.\n",
        "module heading",
    )
    text = replace_once(
        text,
        "//! The router deliberately depends on a narrow backend trait. Production wraps\n"
        "//! `WorkerClient`; unit tests use deterministic in-memory fixtures without\n"
        "//! starting a native VNC thread. All `/v1/*` routes share one bearer-auth layer,\n"
        "//! while liveness and readiness remain public orchestration endpoints.\n",
        "//! The router deliberately depends on a narrow backend trait. Production wraps\n"
        "//! `WorkerClient`; unit tests use deterministic in-memory fixtures without\n"
        "//! starting a native VNC thread. All `/v1/*` routes share one bearer-auth layer,\n"
        "//! complete request preflight, bounded worker acknowledgements, and payload-free\n"
        "//! error mapping. Liveness and readiness remain public orchestration endpoints.\n",
        "module contract",
    )
    text = replace_once(
        text,
        "use crate::config::ControllerConfig;\n",
        "use crate::api_contract::{\n"
        "    ChordRequest, ClipboardRequest, KeyRequest, PointerButtonRequest,\n"
        "    PointerClickRequest, PointerDoubleClickRequest, PointerMoveRequest,\n"
        "    PointerScrollRequest, TextRequest,\n"
        "};\n"
        "use crate::config::ControllerConfig;\n",
        "HTTP api-contract imports",
    )
    text = replace_once(
        text,
        "use crate::worker::{WorkerClient, WorkerFailureKind, WorkerSnapshot};\n",
        "use crate::worker::{WorkerClient, WorkerFailureKind, WorkerSnapshot};\n",
        "worker imports",
    )
    text = replace_once(
        text,
        "use axum::extract::{DefaultBodyLimit, Request, State};\n",
        "use axum::extract::{DefaultBodyLimit, Extension, Request, State, rejection::JsonRejection};\n",
        "axum extract imports",
    )
    text = replace_once(
        text,
        "use axum::routing::get;\n",
        "use axum::routing::{get, post};\n",
        "axum routing imports",
    )
    text = replace_once(
        text,
        "use remote_desktop_core::ConnectionState;\n",
        "use remote_desktop_core::{\n"
        "    ClipboardSnapshot, ConnectionState, DesktopError, DisplayInfo, WorkerCommand,\n"
        "};\n",
        "domain imports",
    )
    text = replace_once(
        text,
        "use std::time::{SystemTime, UNIX_EPOCH};\n",
        "use std::time::{Duration, SystemTime, UNIX_EPOCH};\n",
        "time imports",
    )

    text = replace_once(
        text,
        "/// Read-only backend required by the first HTTP milestone.\n"
        "pub trait HttpBackend: Send + Sync + 'static {\n"
        "    /// Returns one redacted worker lifecycle snapshot.\n"
        "    fn snapshot(&self) -> WorkerSnapshot;\n"
        "    /// Returns coherent framebuffer metadata without copying pixels.\n"
        "    fn framebuffer_metadata(&self) -> FramebufferMetadata;\n"
        "    /// Captures or conditionally validates the current PNG screenshot.\n"
        "    fn capture_screenshot(\n"
        "        &self,\n"
        "        if_none_match: Option<&str>,\n"
        "    ) -> Result<ScreenshotOutcome, ScreenshotError>;\n"
        "}\n",
        "/// Backend required by the authenticated HTTP surface.\n"
        "pub trait HttpBackend: Send + Sync + 'static {\n"
        "    /// Returns one redacted worker lifecycle snapshot.\n"
        "    fn snapshot(&self) -> WorkerSnapshot;\n"
        "    /// Returns coherent framebuffer metadata without copying pixels.\n"
        "    fn framebuffer_metadata(&self) -> FramebufferMetadata;\n"
        "    /// Captures or conditionally validates the current PNG screenshot.\n"
        "    fn capture_screenshot(\n"
        "        &self,\n"
        "        if_none_match: Option<&str>,\n"
        "    ) -> Result<ScreenshotOutcome, ScreenshotError>;\n"
        "    /// Executes one queued command and waits for bounded worker acknowledgement.\n"
        "    fn execute_command(\n"
        "        &self,\n"
        "        command: WorkerCommand,\n"
        "        timeout: Duration,\n"
        "    ) -> Result<u64, DesktopError>;\n"
        "    /// Returns the last valid inbound clipboard snapshot.\n"
        "    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError>;\n"
        "}\n",
        "HTTP backend trait",
    )

    text = replace_once(
        text,
        "    fn capture_screenshot(\n"
        "        &self,\n"
        "        if_none_match: Option<&str>,\n"
        "    ) -> Result<ScreenshotOutcome, ScreenshotError> {\n"
        "        self.screenshots.capture(if_none_match)\n"
        "    }\n"
        "}\n",
        "    fn capture_screenshot(\n"
        "        &self,\n"
        "        if_none_match: Option<&str>,\n"
        "    ) -> Result<ScreenshotOutcome, ScreenshotError> {\n"
        "        self.screenshots.capture(if_none_match)\n"
        "    }\n\n"
        "    fn execute_command(\n"
        "        &self,\n"
        "        command: WorkerCommand,\n"
        "        timeout: Duration,\n"
        "    ) -> Result<u64, DesktopError> {\n"
        "        let ticket = self.client.submit(command)?;\n"
        "        let command_id = ticket.id();\n"
        "        ticket.wait(timeout)?;\n"
        "        Ok(command_id)\n"
        "    }\n\n"
        "    fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {\n"
        "        self.client.clipboard_snapshot()\n"
        "    }\n"
        "}\n",
        "production backend commands",
    )

    text = replace_once(
        text,
        "    maximum_json_bytes: usize,\n",
        "    maximum_json_bytes: usize,\n    command_ack_timeout: Duration,\n",
        "HTTP state acknowledgement field",
    )
    text = replace_once(
        text,
        "        maximum_json_bytes: usize,\n"
        "    ) -> Result<Self, HttpBuildError> {\n",
        "        maximum_json_bytes: usize,\n"
        "        command_ack_timeout: Duration,\n"
        "    ) -> Result<Self, HttpBuildError> {\n",
        "HTTP state constructor signature",
    )
    text = replace_once(
        text,
        "        if maximum_json_bytes == 0 {\n"
        "            return Err(HttpBuildError::InvalidBodyLimit);\n"
        "        }\n",
        "        if maximum_json_bytes == 0 {\n"
        "            return Err(HttpBuildError::InvalidBodyLimit);\n"
        "        }\n"
        "        if command_ack_timeout.is_zero() {\n"
        "            return Err(HttpBuildError::InvalidCommandAckTimeout);\n"
        "        }\n",
        "HTTP state timeout validation",
    )
    text = replace_once(
        text,
        "            maximum_json_bytes,\n"
        "        })\n",
        "            maximum_json_bytes,\n"
        "            command_ack_timeout,\n"
        "        })\n",
        "HTTP state timeout storage",
    )
    text = replace_once(
        text,
        "            config.maximum_json_bytes,\n"
        "        )\n",
        "            config.maximum_json_bytes,\n"
        "            config.command_ack_timeout,\n"
        "        )\n",
        "production HTTP state timeout",
    )
    text = replace_once(
        text,
        "    /// The screenshot service could not be constructed.\n"
        "    Screenshot(ScreenshotError),\n",
        "    /// The command acknowledgement timeout is zero.\n"
        "    InvalidCommandAckTimeout,\n"
        "    /// The screenshot service could not be constructed.\n"
        "    Screenshot(ScreenshotError),\n",
        "HTTP build error timeout variant",
    )
    text = replace_once(
        text,
        "            Self::InvalidBodyLimit => \"HTTP body limit is invalid\",\n"
        "            Self::Screenshot(_) => \"screenshot service configuration is invalid\",\n",
        "            Self::InvalidBodyLimit => \"HTTP body limit is invalid\",\n"
        "            Self::InvalidCommandAckTimeout => {\n"
        "                \"command acknowledgement timeout is invalid\"\n"
        "            }\n"
        "            Self::Screenshot(_) => \"screenshot service configuration is invalid\",\n",
        "HTTP build error display",
    )

    router = r'''/// Builds the authenticated controller router.
pub fn router(state: HttpState) -> Router {
    let protected = Router::new()
        .route("/status", get(status))
        .route("/display", get(display))
        .route("/screenshot.png", get(screenshot))
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
        .layer(middleware::from_fn_with_state(
            state.clone(),
            assign_request_id,
        ))
        .with_state(state)
}
'''
    start = text.index("/// Builds the read-only authenticated controller router.\n")
    end = text.index("\n#[derive(Clone)]\nstruct RequestId", start)
    text = text[:start] + router + text[end:]

    responses = r'''
#[derive(Serialize)]
struct CommandAcceptedResponse {
    command_id: u64,
    status: &'static str,
}

#[derive(Serialize)]
struct ClipboardResponse {
    text: Arc<str>,
    revision: u64,
    updated_at_unix_ms: u64,
}
'''
    text = replace_once(
        text,
        "#[derive(Serialize)]\nstruct ErrorEnvelope<'a> {\n",
        responses + "\n#[derive(Serialize)]\nstruct ErrorEnvelope<'a> {\n",
        "HTTP response DTOs",
    )

    text = replace_once(
        text,
        "    fn internal(request_id: RequestId) -> Self {\n",
        "    fn shutting_down(request_id: RequestId) -> Self {\n"
        "        Self::new(\n"
        "            StatusCode::SERVICE_UNAVAILABLE,\n"
        "            \"shutting_down\",\n"
        "            \"controller is shutting down\",\n"
        "            request_id,\n"
        "        )\n"
        "    }\n\n"
        "    fn invalid_json(request_id: RequestId, payload_too_large: bool) -> Self {\n"
        "        if payload_too_large {\n"
        "            Self::new(\n"
        "                StatusCode::PAYLOAD_TOO_LARGE,\n"
        "                \"payload_too_large\",\n"
        "                \"request body exceeds the configured limit\",\n"
        "                request_id,\n"
        "            )\n"
        "        } else {\n"
        "            Self::new(\n"
        "                StatusCode::BAD_REQUEST,\n"
        "                \"invalid_json\",\n"
        "                \"request body is not valid JSON\",\n"
        "                request_id,\n"
        "            )\n"
        "        }\n"
        "    }\n\n"
        "    fn internal(request_id: RequestId) -> Self {\n",
        "HTTP command errors",
    )

    text = replace_once(
        text,
        "async fn readiness(\n"
        "    State(state): State<HttpState>,\n"
        "    request: Request,\n"
        ") -> Result<Json<HealthResponse>, ApiError> {\n"
        "    let request_id = request_id(&request);\n",
        "async fn readiness(\n"
        "    State(state): State<HttpState>,\n"
        "    Extension(request_id): Extension<RequestId>,\n"
        ") -> Result<Json<HealthResponse>, ApiError> {\n",
        "readiness request ID extraction",
    )
    text = replace_once(
        text,
        "async fn display(\n"
        "    State(state): State<HttpState>,\n"
        "    request: Request,\n"
        ") -> Result<Json<DisplayResponse>, ApiError> {\n"
        "    let request_id = request_id(&request);\n",
        "async fn display(\n"
        "    State(state): State<HttpState>,\n"
        "    Extension(request_id): Extension<RequestId>,\n"
        ") -> Result<Json<DisplayResponse>, ApiError> {\n",
        "display request ID extraction",
    )
    text = replace_once(
        text,
        "async fn screenshot(\n"
        "    State(state): State<HttpState>,\n"
        "    headers: HeaderMap,\n"
        "    request: Request,\n"
        ") -> Result<Response, ApiError> {\n"
        "    let request_id = request_id(&request);\n",
        "async fn screenshot(\n"
        "    State(state): State<HttpState>,\n"
        "    headers: HeaderMap,\n"
        "    Extension(request_id): Extension<RequestId>,\n"
        ") -> Result<Response, ApiError> {\n",
        "screenshot request ID extraction",
    )

    handlers = r'''
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
        text: snapshot.text,
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
        ApiError::invalid_json(request_id, rejection.status() == StatusCode::PAYLOAD_TOO_LARGE)
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
    let backend = Arc::clone(&state.backend);
    let timeout = state.command_ack_timeout;
    let result = tokio::task::spawn_blocking(move || backend.execute_command(command, timeout))
        .await
        .map_err(|_| ApiError::internal(request_id.clone()))?
        .map_err(|error| domain_error(error, request_id.clone()))?;
    Ok((
        StatusCode::ACCEPTED,
        Json(CommandAcceptedResponse {
            command_id: result,
            status: "accepted",
        }),
    ))
}

'''
    text = replace_once(
        text,
        "fn insert_screenshot_headers(\n",
        handlers + "fn insert_screenshot_headers(\n",
        "mutating HTTP handlers",
    )

    domain_errors = r'''
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

'''
    text = replace_once(
        text,
        "fn ready(state: &HttpState, snapshot: &WorkerSnapshot, framebuffer: FramebufferMetadata) -> bool {\n",
        domain_errors
        + "fn ready(state: &HttpState, snapshot: &WorkerSnapshot, framebuffer: FramebufferMetadata) -> bool {\n",
        "domain error mapping",
    )

    text = replace_once(
        text,
        "    struct MockBackend {\n"
        "        snapshot: WorkerSnapshot,\n"
        "        framebuffer: FramebufferMetadata,\n"
        "        screenshot: Mutex<MockScreenshot>,\n"
        "    }\n",
        "    struct MockBackend {\n"
        "        snapshot: WorkerSnapshot,\n"
        "        framebuffer: FramebufferMetadata,\n"
        "        screenshot: Mutex<MockScreenshot>,\n"
        "        commands: Mutex<Vec<WorkerCommand>>,\n"
        "        execute_error: Mutex<Option<DesktopError>>,\n"
        "        clipboard: Mutex<Option<ClipboardSnapshot>>,\n"
        "        next_command_id: AtomicU64,\n"
        "    }\n",
        "mock backend fields",
    )
    text = replace_once(
        text,
        "            match screenshot {\n"
        "                MockScreenshot::Png => Ok(ScreenshotOutcome::Png {\n"
        "                    headers,\n"
        "                    width: 2,\n"
        "                    height: 2,\n"
        "                    revision: 7,\n"
        "                    bytes: vec![137, 80, 78, 71],\n"
        "                }),\n"
        "                MockScreenshot::NotModified => Ok(ScreenshotOutcome::NotModified { headers }),\n"
        "                MockScreenshot::Unavailable => Err(ScreenshotError::Framebuffer(\n"
        "                    crate::framebuffer::FramebufferError::Unavailable,\n"
        "                )),\n"
        "            }\n"
        "        }\n"
        "    }\n",
        "            match screenshot {\n"
        "                MockScreenshot::Png => Ok(ScreenshotOutcome::Png {\n"
        "                    headers,\n"
        "                    width: 2,\n"
        "                    height: 2,\n"
        "                    revision: 7,\n"
        "                    bytes: vec![137, 80, 78, 71],\n"
        "                }),\n"
        "                MockScreenshot::NotModified => Ok(ScreenshotOutcome::NotModified { headers }),\n"
        "                MockScreenshot::Unavailable => Err(ScreenshotError::Framebuffer(\n"
        "                    crate::framebuffer::FramebufferError::Unavailable,\n"
        "                )),\n"
        "            }\n"
        "        }\n\n"
        "        fn execute_command(\n"
        "            &self,\n"
        "            command: WorkerCommand,\n"
        "            _timeout: Duration,\n"
        "        ) -> Result<u64, DesktopError> {\n"
        "            if let Some(error) = self\n"
        "                .execute_error\n"
        "                .lock()\n"
        "                .unwrap_or_else(|poisoned| poisoned.into_inner())\n"
        "                .clone()\n"
        "            {\n"
        "                return Err(error);\n"
        "            }\n"
        "            self.commands\n"
        "                .lock()\n"
        "                .unwrap_or_else(|poisoned| poisoned.into_inner())\n"
        "                .push(command);\n"
        "            Ok(self.next_command_id.fetch_add(1, Ordering::Relaxed))\n"
        "        }\n\n"
        "        fn clipboard_snapshot(&self) -> Result<ClipboardSnapshot, DesktopError> {\n"
        "            self.clipboard\n"
        "                .lock()\n"
        "                .unwrap_or_else(|poisoned| poisoned.into_inner())\n"
        "                .clone()\n"
        "                .ok_or(DesktopError::ClipboardUnavailable)\n"
        "        }\n"
        "    }\n",
        "mock backend command methods",
    )

    old_test_state_start = text.index("    fn test_state(ready: bool, screenshot: MockScreenshot) -> HttpState {\n")
    old_test_state_end = text.index("\n    fn request(uri: &str)", old_test_state_start)
    new_test_state = r'''    fn test_state_with_backend(
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
'''
    text = text[:old_test_state_start] + new_test_state + text[old_test_state_end:]

    state_test_start = text.index(
        "    #[test]\n    fn state_validation_and_bearer_comparison_fail_closed() {\n"
    )
    state_test_end = text.index("\n    }\n", state_test_start) + len("\n    }\n")
    state_test = r'''    #[test]
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
'''
    text = text[:state_test_start] + state_test + text[state_test_end:]

    tests = r'''

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
            let method = if uri == "/v1/clipboard" { "PUT" } else { "POST" };
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
'''
    closing = text.rfind("\n}\n")
    if closing < 0:
        raise SystemExit("HTTP tests closing brace not found")
    text = text[:closing] + tests + text[closing:]
    path.write_text(text, encoding="utf-8")


update_api_contract()
update_http()
