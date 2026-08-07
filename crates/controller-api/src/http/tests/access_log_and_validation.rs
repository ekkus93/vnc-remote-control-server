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
