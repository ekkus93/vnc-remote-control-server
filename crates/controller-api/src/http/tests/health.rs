use super::*;

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
async fn websocket_initial_snapshot_sequence_exhaustion_fails_before_upgrade() {
    let state = test_state(true, MockScreenshot::Png);
    state.events.force_sequence_for_test(u64::MAX);

    let error = match crate::http::handlers::prepare_event_session(
        &state,
        RequestId(Arc::from("sequence-exhaustion-test")),
    ) {
        Ok(_) => panic!("sequence exhaustion must fail before WebSocket upgrade use"),
        Err(error) => error,
    };
    let response = axum::response::IntoResponse::into_response(error);
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    let body = json_body(response).await;
    assert_eq!(body["error"]["code"], "event_sequence_exhausted");
    let metrics = state.metrics.render(
        &state.backend.snapshot(),
        state.backend.command_submissions_in_flight(),
        state.backend.command_queue_capacity(),
    );
    assert!(metrics.contains("vrc_websocket_clients 0"));
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
