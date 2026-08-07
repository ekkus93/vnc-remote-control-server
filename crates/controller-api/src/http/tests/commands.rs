use super::*;

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
        let method = if uri == "/v1/clipboard" {
            "PUT"
        } else {
            "POST"
        };
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

#[tokio::test]
async fn authenticated_metrics_use_fixed_labels_and_exclude_secrets() {
    let app = router(test_state(true, MockScreenshot::Png));
    let response = app
        .oneshot(
            request("/v1/metrics")
                .header(AUTHORIZATION, "Bearer test-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let body = to_bytes(response.into_body(), 256 * 1024)
        .await
        .expect("bounded metrics body");
    let body = String::from_utf8(body.to_vec()).expect("UTF-8 metrics");
    assert!(body.contains("vrc_connection_state{state=\"connected\"} 1"));
    assert!(body.contains("vrc_worker_command_queue_capacity 64"));
    assert!(!body.contains("test-token"));
    assert!(!body.contains("request_id"));
}
