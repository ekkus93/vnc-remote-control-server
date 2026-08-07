use super::*;

async fn body_text(response: axum::response::Response) -> String {
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024)
        .await
        .expect("bounded documentation response");
    String::from_utf8(bytes.to_vec()).expect("UTF-8 documentation response")
}

#[tokio::test]
async fn api_documentation_routes_are_public_and_single_source_the_openapi_contract() {
    let app = router(test_state(true, MockScreenshot::Png));

    let response = app
        .clone()
        .oneshot(request("/openapi.json").body(Body::empty()).expect("request"))
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response.headers().get(CONTENT_TYPE),
        Some(&HeaderValue::from_static("application/json; charset=utf-8"))
    );
    assert!(response.headers().contains_key(&REQUEST_ID_HEADER));
    let body = body_text(response).await;
    let document: Value = serde_json::from_str(&body).expect("valid hosted OpenAPI JSON");
    assert_eq!(document["openapi"], "3.1.0");
    assert_eq!(document["info"]["title"], "VNC Remote Control Server API");
    assert!(document["paths"]["/v1/keyboard/text"].is_object());

    let response = app
        .clone()
        .oneshot(request("/docs").body(Body::empty()).expect("request"))
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response.headers().get(CONTENT_TYPE),
        Some(&HeaderValue::from_static("text/html; charset=utf-8"))
    );
    assert!(response.headers().contains_key("content-security-policy"));
    let body = body_text(response).await;
    assert!(body.contains("swagger-ui-dist@5.32.11"));
    assert!(body.contains("/docs/swagger-initializer.js"));

    let response = app
        .clone()
        .oneshot(
            request("/docs/swagger-initializer.js")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let body = body_text(response).await;
    assert!(body.contains("url: \"/openapi.json\""));
    assert!(body.contains("persistAuthorization: false"));
    assert!(body.contains("validatorUrl: null"));

    let response = app
        .oneshot(request("/redoc").body(Body::empty()).expect("request"))
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    assert!(response.headers().contains_key("content-security-policy"));
    let body = body_text(response).await;
    assert!(body.contains("spec-url=\"/openapi.json\""));
    assert!(body.contains("redoc/v2.5.3/bundles/redoc.standalone.js"));
}
