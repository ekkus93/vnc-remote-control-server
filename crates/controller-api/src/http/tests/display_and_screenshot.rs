use super::*;

#[tokio::test]
async fn authenticated_status_and_display_are_redacted_and_stable() {
    let app = router(test_state(true, MockScreenshot::Png));
    let response = app
        .clone()
        .oneshot(
            request("/v1/status")
                .header(AUTHORIZATION, "Bearer test-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let body = json_body(response).await;
    assert_eq!(body["state"], "connected");
    assert_eq!(body["framebuffer_revision"], 7);
    assert!(!body.to_string().contains("test-token"));

    let response = app
        .oneshot(
            request("/v1/display")
                .header(AUTHORIZATION, "Bearer test-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let body = json_body(response).await;
    assert_eq!(body["width"], 2);
    assert_eq!(body["height"], 2);
    assert_eq!(body["depth"], 24);
    assert_eq!(body["revision"], 7);
    assert_eq!(body["complete"], true);
}

#[tokio::test]
async fn display_unavailable_uses_stable_json_error() {
    let app = router(test_state(false, MockScreenshot::Unavailable));
    let response = app
        .oneshot(
            request("/v1/display")
                .header(AUTHORIZATION, "Bearer test-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    let body = json_body(response).await;
    assert_eq!(body["error"]["code"], "framebuffer_unavailable");
}

#[tokio::test]
async fn screenshot_png_and_conditional_response_preserve_headers() {
    let png_app = router(test_state(true, MockScreenshot::Png));
    let response = png_app
        .oneshot(
            request("/v1/screenshot.png")
                .header(AUTHORIZATION, "Bearer test-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response.headers().get(ETAG),
        Some(&HeaderValue::from_static("\"test-7\""))
    );
    assert_eq!(
        response.headers().get(CONTENT_TYPE),
        Some(&HeaderValue::from_static("image/png"))
    );
    let bytes = to_bytes(response.into_body(), 1024)
        .await
        .expect("PNG body");
    assert_eq!(bytes.as_ref(), &[137, 80, 78, 71]);

    let not_modified_app = router(test_state(true, MockScreenshot::NotModified));
    let response = not_modified_app
        .oneshot(
            request("/v1/screenshot.png")
                .header(AUTHORIZATION, "Bearer test-token")
                .header(IF_NONE_MATCH, "\"test-7\"")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::NOT_MODIFIED);
    assert_eq!(
        response.headers().get(ETAG),
        Some(&HeaderValue::from_static("\"test-7\""))
    );
}

#[tokio::test]
async fn screenshot_unavailable_is_bounded_json_error() {
    let app = router(test_state(false, MockScreenshot::Unavailable));
    let response = app
        .oneshot(
            request("/v1/screenshot.png")
                .header(AUTHORIZATION, "Bearer test-token")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    let body = json_body(response).await;
    assert_eq!(body["error"]["code"], "framebuffer_unavailable");
}
