use super::ids::RequestId;
use axum::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::Serialize;

const DEFAULT_ERROR_MESSAGE: &str = "request could not be completed";

#[derive(Serialize)]
pub(super) struct HealthResponse {
    pub(super) status: &'static str,
}

#[derive(Serialize)]
pub(super) struct StatusResponse {
    pub(super) state: &'static str,
    pub(super) started_at_unix_ms: u64,
    pub(super) connected_at_unix_ms: Option<u64>,
    pub(super) last_message_at_unix_ms: Option<u64>,
    pub(super) reconnect_attempts: u32,
    pub(super) last_failure: Option<&'static str>,
    pub(super) framebuffer_revision: Option<u64>,
    pub(super) rejected_commands: u64,
    pub(super) dropped_events: u64,
    pub(super) fatal_exit: bool,
    pub(super) shutting_down: bool,
}

#[derive(Serialize)]
pub(super) struct DisplayResponse {
    pub(super) status: &'static str,
    pub(super) width: u32,
    pub(super) height: u32,
    pub(super) depth: u8,
    pub(super) revision: u64,
    pub(super) updated_at_unix_ms: u64,
    pub(super) complete: bool,
}

#[derive(Serialize)]
pub(super) struct CommandResponse {
    pub(super) command_id: u64,
    pub(super) status: &'static str,
}

#[derive(Serialize)]
pub(super) struct CommandStatusResponse {
    pub(super) command_id: u64,
    pub(super) status: &'static str,
    pub(super) failure: Option<&'static str>,
    pub(super) retry_safe: bool,
}

#[derive(Serialize)]
pub(super) struct ClipboardResponse {
    pub(super) text: String,
    pub(super) revision: u64,
    pub(super) updated_at_unix_ms: u64,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    command_id: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    outcome: Option<&'static str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    retry_safe: Option<bool>,
}

pub(super) struct ApiError {
    status: StatusCode,
    code: &'static str,
    message: &'static str,
    request_id: RequestId,
    command_id: Option<u64>,
    outcome: Option<&'static str>,
    retry_safe: Option<bool>,
}

impl ApiError {
    pub(super) fn new(
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
            command_id: None,
            outcome: None,
            retry_safe: None,
        }
    }

    pub(super) fn command_timeout(command_id: u64, request_id: RequestId) -> Self {
        Self {
            status: StatusCode::GATEWAY_TIMEOUT,
            code: "command_timeout",
            message: "desktop command result wait timed out; execution outcome is unknown",
            request_id,
            command_id: Some(command_id),
            outcome: Some("unknown"),
            retry_safe: Some(false),
        }
    }

    pub(super) fn command_status_unknown(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::NOT_FOUND,
            "command_status_unknown",
            "command identifier is not known to this process instance",
            request_id,
        )
    }

    pub(super) fn command_status_expired(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::GONE,
            "command_status_expired",
            "command status record has expired",
            request_id,
        )
    }

    pub(super) fn unauthorized(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::UNAUTHORIZED,
            "unauthorized",
            "authentication required",
            request_id,
        )
    }

    pub(super) fn not_ready(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "not_ready",
            "controller is not ready",
            request_id,
        )
    }

    pub(super) fn framebuffer_unavailable(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "framebuffer_unavailable",
            "current framebuffer is unavailable",
            request_id,
        )
    }

    pub(super) fn shutting_down(request_id: RequestId) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "shutting_down",
            "controller is shutting down",
            request_id,
        )
    }

    pub(super) fn invalid_json(request_id: RequestId, payload_too_large: bool) -> Self {
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

    pub(super) fn internal(request_id: RequestId) -> Self {
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
                command_id: self.command_id,
                outcome: self.outcome,
                retry_safe: self.retry_safe,
            },
        });
        let mut response = body.into_response();
        *response.status_mut() = self.status;
        response
    }
}
