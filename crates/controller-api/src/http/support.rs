use super::ids::RequestId;
use super::responses::ApiError;
use super::state::HttpState;
use crate::framebuffer::{FramebufferError, FramebufferMetadata, FramebufferStatus};
use crate::screenshot::{ScreenshotError, ScreenshotHeaders};
use crate::worker::{WorkerFailureKind, WorkerSnapshot};
use axum::Json;
use axum::extract::rejection::JsonRejection;
use axum::http::header::{CACHE_CONTROL, CONTENT_TYPE, ETAG};
use axum::http::{HeaderValue, StatusCode};
use axum::response::Response;
use remote_desktop_core::{ConnectionState, DesktopError, DisplayInfo};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use subtle::ConstantTimeEq;

pub(super) fn json_payload<T>(
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

pub(super) fn current_display(
    state: &HttpState,
    request_id: RequestId,
) -> Result<DisplayInfo, ApiError> {
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

pub(super) fn insert_screenshot_headers(
    response: &mut Response,
    headers: &ScreenshotHeaders,
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

pub(super) fn screenshot_error(error: ScreenshotError, request_id: RequestId) -> ApiError {
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

pub(super) fn domain_error(error: DesktopError, request_id: RequestId) -> ApiError {
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
        DesktopError::CommandOutcomeCapacityFull => ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "command_outcome_capacity_full",
            "command outcome capacity is exhausted",
            request_id,
        ),
        DesktopError::CommandIdExhausted => ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "command_id_exhausted",
            "command identifier sequence is exhausted",
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
            "desktop command timed out",
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

pub(super) fn ready(
    state: &HttpState,
    snapshot: &WorkerSnapshot,
    framebuffer: FramebufferMetadata,
) -> bool {
    !state.is_shutting_down()
        && !snapshot.fatal_exit
        && snapshot.state == ConnectionState::Connected
        && framebuffer.status == FramebufferStatus::Current
        && framebuffer.width.is_some()
        && framebuffer.height.is_some()
        && framebuffer.updated_at.is_some()
}

pub(super) fn bearer_matches(header: &[u8], expected: &[u8]) -> bool {
    let Some(candidate) = header.strip_prefix(b"Bearer ") else {
        return false;
    };
    !candidate.is_empty()
        && candidate.len() == expected.len()
        && bool::from(candidate.ct_eq(expected))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum TimestampError {
    BeforeUnixEpoch,
    MillisecondsOverflow,
}

fn duration_milliseconds(value: Duration) -> Result<u64, TimestampError> {
    u64::try_from(value.as_millis()).map_err(|_| TimestampError::MillisecondsOverflow)
}

pub(super) fn unix_milliseconds(value: SystemTime) -> Result<u64, TimestampError> {
    let elapsed = value
        .duration_since(UNIX_EPOCH)
        .map_err(|_| TimestampError::BeforeUnixEpoch)?;
    duration_milliseconds(elapsed)
}

pub(super) const fn connection_state_name(state: ConnectionState) -> &'static str {
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

pub(super) const fn worker_failure_name(failure: WorkerFailureKind) -> &'static str {
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

pub(super) const fn framebuffer_status_name(status: FramebufferStatus) -> &'static str {
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

    #[test]
    fn unix_timestamp_rejects_pre_epoch_and_millisecond_overflow() {
        assert_eq!(
            unix_milliseconds(UNIX_EPOCH - Duration::from_millis(1)),
            Err(TimestampError::BeforeUnixEpoch)
        );
        assert_eq!(
            duration_milliseconds(Duration::from_secs(u64::MAX)),
            Err(TimestampError::MillisecondsOverflow)
        );
        assert_eq!(unix_milliseconds(UNIX_EPOCH), Ok(0));
    }
}
