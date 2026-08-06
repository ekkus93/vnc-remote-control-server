use super::*;

const BEARER_SENTINEL: &str = "bearer-private-7f4d2c9a";
const TEXT_SENTINEL: &str = "typed-private-a91e5d73";
const CLIPBOARD_SENTINEL: &str = "clipboard-private-c38b6f20";

#[test]
fn access_log_excludes_bearer_sentinel() {
    let mut logged_request = request("/v1/status?token=query-private-41b8e2d0")
        .header(AUTHORIZATION, format!("Bearer {BEARER_SENTINEL}"))
        .body(Body::empty())
        .expect("request");
    logged_request
        .extensions_mut()
        .insert(RequestId(Arc::from("privacy-request")));
    let context = AccessLogContext::from_request(&logged_request);
    let line = format_access_log(&context, StatusCode::UNAUTHORIZED, Duration::from_millis(3));

    assert!(line.contains("authorization=[REDACTED]"));
    assert!(!line.contains(BEARER_SENTINEL));
    assert!(!line.contains("query-private-41b8e2d0"));
}

#[test]
fn command_failure_json_logs_exclude_text_and_clipboard_sentinels() {
    for (method, uri, payload, sentinel) in [
        (
            "POST",
            "/v1/keyboard/text",
            serde_json::json!({"text": TEXT_SENTINEL}),
            TEXT_SENTINEL,
        ),
        (
            "PUT",
            "/v1/clipboard",
            serde_json::json!({"text": CLIPBOARD_SENTINEL}),
            CLIPBOARD_SENTINEL,
        ),
    ] {
        let (state, backend) = test_state_with_backend(true, MockScreenshot::Png);
        *backend
            .execute_error
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(DesktopError::Native);
        let request = authenticated_json_request(method, uri, payload);

        let ((status, body), records) = crate::test_support::capture_json_logs(|| {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("current-thread runtime");
            runtime.block_on(async move {
                let response = router(state)
                    .oneshot(request)
                    .await
                    .expect("command failure response");
                let status = response.status();
                let body = json_body(response).await;
                (status, body)
            })
        });

        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
        assert_eq!(body["error"]["code"], "native_failure");
        assert!(crate::test_support::json_logs_contain(
            &records,
            "desktop_command_failed"
        ));
        assert!(
            !crate::test_support::json_logs_contain(&records, sentinel),
            "structured command-failure log leaked request payload"
        );
    }
}
