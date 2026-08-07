use super::*;

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
            ApiToken::from_secret(SecretString::from("")),
            Arc::from("process"),
            1,
            Duration::from_secs(1),
        )
        .is_err()
    );
    assert!(
        HttpState::new(
            Arc::clone(&backend),
            ApiToken::from_secret(SecretString::from("token")),
            Arc::from("bad process"),
            1,
            Duration::from_secs(1),
        )
        .is_err()
    );
    assert!(
        HttpState::new(
            Arc::clone(&backend),
            ApiToken::from_secret(SecretString::from("token")),
            Arc::from("process"),
            0,
            Duration::from_secs(1),
        )
        .is_err()
    );
    assert!(
        HttpState::new(
            backend,
            ApiToken::from_secret(SecretString::from("token")),
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

#[test]
fn request_id_sequence_is_monotonic_terminal_and_logged_once() {
    let state = test_state(true, MockScreenshot::Png);
    let first = state.next_request_id().expect("first request ID allocates");
    let second = state.next_request_id().expect("second request ID allocates");
    assert_eq!(first.0.as_ref(), "test-process-1");
    assert_eq!(second.0.as_ref(), "test-process-2");

    state.force_request_sequence_for_test(u64::MAX);
    let ((first_failure, second_failure), logs) = crate::test_support::capture_logs(|| {
        (state.next_request_id(), state.next_request_id())
    });
    assert!(first_failure.is_err());
    assert!(second_failure.is_err());
    assert!(state.request_id_sequence_exhausted());
    assert_eq!(logs.matches("request_id_sequence_exhausted").count(), 1);
    for forbidden in [
        "clipboard",
        "typed",
        "password",
        "token",
        "framebuffer",
        "screenshot",
        "query",
    ] {
        assert!(!logs.contains(forbidden));
    }
}

#[tokio::test]
async fn request_id_exhaustion_rejects_before_handler_and_caller_id_cannot_bypass() {
    let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
    state.force_request_sequence_for_test(u64::MAX);
    let app = router(state);
    let request = authenticated_json_request(
        "POST",
        "/v1/keyboard/text",
        serde_json::json!({"text":"should-not-run"}),
    );
    let mut request = request;
    request.headers_mut().insert(
        REQUEST_ID_HEADER,
        HeaderValue::from_static("caller-provided-id"),
    );

    let response = app.oneshot(request).await.expect("router response");
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        response
            .headers()
            .get(REQUEST_ID_HEADER)
            .expect("exhaustion request ID header"),
        "request-id-exhausted"
    );
    let body = json_body(response).await;
    assert_eq!(body["error"]["code"], "request_id_exhausted");
    assert_eq!(body["error"]["request_id"], "request-id-exhausted");
    assert_eq!(
        body["error"]["message"],
        "request identifier sequence is exhausted"
    );
    assert!(
        backend
            .commands
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .is_empty()
    );
}
