use super::ids::{RequestId, request_id, valid_request_id};
use super::responses::ApiError;
use super::state::HttpState;
use super::support::bearer_matches;
use axum::extract::{Request, State};
use axum::http::header::AUTHORIZATION;
use axum::http::{HeaderName, HeaderValue, Method};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use std::sync::Arc;
use std::time::Instant;
use tracing::Instrument;
#[cfg(test)]
use {axum::http::StatusCode, std::time::Duration};

pub(super) const REQUEST_ID_HEADER: HeaderName = HeaderName::from_static("x-request-id");

pub(super) async fn assign_request_id(
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

pub(super) struct AccessLogContext {
    pub(super) method: Method,
    pub(super) path: String,
    pub(super) request_id: RequestId,
    pub(super) authorization: &'static str,
}

impl AccessLogContext {
    pub(super) fn from_request(request: &Request) -> Self {
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

pub(super) async fn access_log(
    State(state): State<HttpState>,
    request: Request,
    next: Next,
) -> Response {
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
pub(super) fn format_access_log(
    context: &AccessLogContext,
    status: StatusCode,
    elapsed: Duration,
) -> String {
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

pub(super) async fn require_bearer(
    State(state): State<HttpState>,
    request: Request,
    next: Next,
) -> Response {
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
