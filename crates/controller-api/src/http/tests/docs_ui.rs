use super::*;

async fn body_text(response: axum::response::Response) -> String {
    let bytes = to_bytes(response.into_body(), 2 * 1024 * 1024)
        .await
        .expect("bounded documentation response");
    String::from_utf8(bytes.to_vec()).expect("UTF-8 documentation response")
}

fn assert_no_external_asset_url(body: &str, context: &str) {
    assert!(
        !body.contains("http://") && !body.contains("https://"),
        "{context} referenced an external network URL: {body}"
    );
}

#[tokio::test]
async fn api_documentation_routes_are_public_and_single_source_the_openapi_contract() {
    let app = router(test_state(true, MockScreenshot::Png));

    let response = app
        .clone()
        .oneshot(
            request("/openapi.json")
                .body(Body::empty())
                .expect("request"),
        )
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
    let csp = response
        .headers()
        .get("content-security-policy")
        .expect("swagger CSP header")
        .to_str()
        .expect("ASCII CSP header")
        .to_owned();
    assert!(csp.contains("script-src 'self'"));
    assert!(csp.contains("style-src 'self'"));
    assert!(!csp.contains("cdn.jsdelivr.net"));
    let body = body_text(response).await;
    assert_no_external_asset_url(&body, "/docs");
    assert!(body.contains("/docs/assets/swagger-ui.css"));
    assert!(body.contains("/docs/assets/swagger-ui-bundle.js"));
    assert!(body.contains("/docs/assets/swagger-ui-standalone-preset.js"));
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

    for (path, content_type, marker) in [
        (
            "/docs/assets/swagger-ui.css",
            "text/css; charset=utf-8",
            ".swagger-ui",
        ),
        (
            "/docs/assets/swagger-ui-bundle.js",
            "application/javascript; charset=utf-8",
            "SwaggerUIBundle",
        ),
        (
            "/docs/assets/swagger-ui-standalone-preset.js",
            "application/javascript; charset=utf-8",
            "SwaggerUIStandalonePreset",
        ),
    ] {
        let response = app
            .clone()
            .oneshot(request(path).body(Body::empty()).expect("request"))
            .await
            .expect("response");
        assert_eq!(response.status(), StatusCode::OK, "{path} status");
        assert_eq!(
            response.headers().get(CONTENT_TYPE),
            Some(&HeaderValue::from_static(content_type)),
            "{path} content-type"
        );
        assert!(
            !response.headers().contains_key("content-security-policy"),
            "{path} is a static asset, not an HTML document"
        );
        // These are unmodified vendored third-party files (see
        // ../../../third_party/MANIFEST.md), so unlike the HTML this
        // controller authors, their content legitimately contains
        // documentation/source https:// links; only the controller-owned
        // markup is checked for external asset references.
        let body = body_text(response).await;
        assert!(!body.is_empty(), "{path} served an empty body");
        assert!(body.contains(marker), "{path} missing expected content");
    }

    let response = app
        .clone()
        .oneshot(request("/redoc").body(Body::empty()).expect("request"))
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    let csp = response
        .headers()
        .get("content-security-policy")
        .expect("redoc CSP header")
        .to_str()
        .expect("ASCII CSP header")
        .to_owned();
    assert!(csp.contains("script-src 'self'"));
    assert!(!csp.contains("cdn.redoc.ly"));
    let body = body_text(response).await;
    assert_no_external_asset_url(&body, "/redoc");
    assert!(body.contains("spec-url=\"/openapi.json\""));
    assert!(body.contains("/redoc/assets/redoc.standalone.js"));

    let response = app
        .oneshot(
            request("/redoc/assets/redoc.standalone.js")
                .body(Body::empty())
                .expect("request"),
        )
        .await
        .expect("response");
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response.headers().get(CONTENT_TYPE),
        Some(&HeaderValue::from_static(
            "application/javascript; charset=utf-8"
        ))
    );
    assert!(!response.headers().contains_key("content-security-policy"));
    // Unmodified vendored third-party file: legitimately contains its own
    // documentation https:// links, so it is not checked for those.
    let body = body_text(response).await;
    assert!(!body.is_empty());
}
