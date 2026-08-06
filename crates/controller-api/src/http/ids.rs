use axum::extract::Request;
use std::sync::Arc;

const MAX_REQUEST_ID_BYTES: usize = 64;

/// Caller-visible or generated request identifier, safe to log and echo.
#[derive(Clone)]
pub(super) struct RequestId(pub(super) Arc<str>);

pub(super) fn request_id(request: &Request) -> RequestId {
    request
        .extensions()
        .get::<RequestId>()
        .cloned()
        .unwrap_or_else(|| RequestId(Arc::from("request-id-unavailable")))
}

pub(super) fn valid_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_REQUEST_ID_BYTES
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

pub(super) fn valid_process_instance(value: &str) -> bool {
    valid_request_id(value)
}
