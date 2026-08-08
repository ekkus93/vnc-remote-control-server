use super::ids::RequestId;
use super::responses::{
    ApiError, ClipboardResponse, CommandAcceptedResponse, DisplayResponse, HealthResponse,
    StatusResponse,
};
use super::state::HttpState;
use super::support::{
    connection_state_name, current_display, domain_error, framebuffer_status_name,
    insert_screenshot_headers, json_payload, ready, screenshot_error, unix_milliseconds,
    worker_failure_name,
};
use crate::api_contract::{
    ChordRequest, ClipboardRequest, KeyRequest, PointerButtonRequest, PointerClickRequest,
    PointerDoubleClickRequest, PointerMoveRequest, PointerScrollRequest, TextRequest,
};
use crate::events::{EventSubscription, ServerEvent, WebSocketCapacityError};
use crate::framebuffer::FramebufferStatus;
use crate::screenshot::ScreenshotOutcome;
use axum::Json;
use axum::body::Body;
use axum::extract::rejection::JsonRejection;
use axum::extract::{Extension, State, ws::WebSocketUpgrade};
use axum::http::header::{CONTENT_TYPE, IF_NONE_MATCH};
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::Response;
use remote_desktop_core::WorkerCommand;
use std::sync::Arc;
use std::time::Instant;

pub(super) fn prepare_event_session(
    state: &HttpState,
    request_id: RequestId,
) -> Result<(EventSubscription, ServerEvent), ApiError> {
    let subscription = state.events.subscribe().map_err(|WebSocketCapacityError| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "websocket_capacity",
            "WebSocket client capacity is exhausted",
            request_id.clone(),
        )
    })?;
    let snapshot = state.backend.snapshot();
    let clipboard_revision = state
        .backend
        .clipboard_snapshot()
        .ok()
        .map(|clipboard| clipboard.revision);
    let initial = state
        .events
        .snapshot_event(&snapshot, clipboard_revision)
        .map_err(|_| {
            ApiError::new(
                StatusCode::SERVICE_UNAVAILABLE,
                "event_sequence_exhausted",
                "event sequence is exhausted",
                request_id,
            )
        })?;
    Ok((subscription, initial))
}

pub(super) async fn events(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    websocket: WebSocketUpgrade,
) -> Result<Response, ApiError> {
    let (subscription, initial) = prepare_event_session(&state, request_id)?;
    let events = state.events.clone();
    Ok(websocket.on_upgrade(move |socket| async move {
        events.serve(socket, subscription, initial).await;
    }))
}

pub(super) async fn metrics_endpoint(State(state): State<HttpState>) -> Response {
    let snapshot = state.backend.snapshot();
    let body = state.metrics.render(
        &snapshot,
        state.backend.command_submissions_in_flight(),
        state.backend.command_queue_capacity(),
    );
    let mut response = Response::new(Body::from(body));
    response.headers_mut().insert(
        CONTENT_TYPE,
        HeaderValue::from_static("text/plain; version=0.0.4; charset=utf-8"),
    );
    response
}

pub(super) async fn liveness() -> Json<HealthResponse> {
    Json(HealthResponse { status: "alive" })
}

pub(super) async fn readiness(
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

pub(super) async fn status(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<Json<StatusResponse>, ApiError> {
    let snapshot = state.backend.snapshot();
    let started_at_unix_ms =
        unix_milliseconds(snapshot.started_at).map_err(|_| ApiError::internal(request_id.clone()))?;
    let connected_at_unix_ms = snapshot
        .connected_at
        .map(unix_milliseconds)
        .transpose()
        .map_err(|_| ApiError::internal(request_id.clone()))?;
    let last_message_at_unix_ms = snapshot
        .last_message_at
        .map(unix_milliseconds)
        .transpose()
        .map_err(|_| ApiError::internal(request_id.clone()))?;
    Ok(Json(StatusResponse {
        state: connection_state_name(snapshot.state),
        started_at_unix_ms,
        connected_at_unix_ms,
        last_message_at_unix_ms,
        reconnect_attempts: snapshot.reconnect_attempts,
        last_failure: snapshot.last_failure.map(worker_failure_name),
        framebuffer_revision: snapshot.framebuffer_revision,
        rejected_commands: snapshot.rejected_commands,
        dropped_events: snapshot.dropped_events,
        fatal_exit: snapshot.fatal_exit,
        shutting_down: state.is_shutting_down(),
    }))
}

pub(super) async fn display(
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
    let updated_at_unix_ms =
        unix_milliseconds(updated_at).map_err(|_| ApiError::internal(request_id.clone()))?;
    Ok(Json(DisplayResponse {
        status: framebuffer_status_name(metadata.status),
        width,
        height,
        depth: 24,
        revision: metadata.revision,
        updated_at_unix_ms,
        complete: true,
    }))
}

pub(super) async fn screenshot(
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

pub(super) async fn pointer_move(
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

pub(super) async fn pointer_button(
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

pub(super) async fn pointer_click(
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

pub(super) async fn pointer_double_click(
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

pub(super) async fn pointer_scroll(
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

pub(super) async fn keyboard_key(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    payload: Result<Json<KeyRequest>, JsonRejection>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    let payload = json_payload(payload, request_id.clone())?;
    execute_command(state, request_id, payload.into_command()).await
}

pub(super) async fn keyboard_chord(
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

pub(super) async fn keyboard_text(
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

pub(super) async fn clipboard(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<Json<ClipboardResponse>, ApiError> {
    let snapshot = state
        .backend
        .clipboard_snapshot()
        .map_err(|error| domain_error(error, request_id.clone()))?;
    let updated_at_unix_ms = unix_milliseconds(snapshot.updated_at)
        .map_err(|_| ApiError::internal(request_id.clone()))?;
    Ok(Json(ClipboardResponse {
        text: snapshot.text.to_string(),
        revision: snapshot.revision,
        updated_at_unix_ms,
    }))
}

pub(super) async fn set_clipboard(
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

pub(super) async fn reconnect(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
) -> Result<(StatusCode, Json<CommandAcceptedResponse>), ApiError> {
    execute_command(state, request_id, WorkerCommand::Reconnect).await
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
