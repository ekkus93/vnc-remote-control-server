use axum::body::Body;
use axum::http::header::{CACHE_CONTROL, CONTENT_TYPE};
use axum::http::{HeaderValue, StatusCode};
use axum::response::Response;

const OPENAPI_JSON: &str = include_str!("../../../../docs/openapi.json");

const SWAGGER_UI_HTML: &str = r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VNC Remote Control Server API — Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.11/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.11/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.11/swagger-ui-standalone-preset.js"></script>
  <script src="/docs/swagger-initializer.js"></script>
</body>
</html>
"#;

const SWAGGER_INITIALIZER_JS: &str = r#"window.addEventListener("load", () => {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    displayRequestDuration: true,
    persistAuthorization: false,
    validatorUrl: null,
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
    layout: "StandaloneLayout"
  });
});
"#;

const REDOC_HTML: &str = r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VNC Remote Control Server API — ReDoc</title>
</head>
<body>
  <redoc spec-url="/openapi.json"></redoc>
  <script src="https://cdn.redoc.ly/redoc/v2.5.3/bundles/redoc.standalone.js"></script>
</body>
</html>
"#;

const SWAGGER_CSP: &str = "default-src 'none'; script-src 'self' https://cdn.jsdelivr.net; style-src https://cdn.jsdelivr.net; img-src data:; font-src https://cdn.jsdelivr.net; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
const REDOC_CSP: &str = "default-src 'none'; script-src https://cdn.redoc.ly; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

fn static_response(body: &'static str, content_type: &'static str, csp: Option<&'static str>) -> Response {
    let mut response = Response::new(Body::from(body));
    *response.status_mut() = StatusCode::OK;
    response
        .headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static(content_type));
    response
        .headers_mut()
        .insert(CACHE_CONTROL, HeaderValue::from_static("no-store"));
    response.headers_mut().insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    response
        .headers_mut()
        .insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    response.headers_mut().insert(
        "cross-origin-opener-policy",
        HeaderValue::from_static("same-origin"),
    );
    if let Some(policy) = csp {
        response.headers_mut().insert(
            "content-security-policy",
            HeaderValue::from_static(policy),
        );
    }
    response
}

pub(super) async fn openapi_json() -> Response {
    static_response(OPENAPI_JSON, "application/json; charset=utf-8", None)
}

pub(super) async fn swagger_ui() -> Response {
    static_response(SWAGGER_UI_HTML, "text/html; charset=utf-8", Some(SWAGGER_CSP))
}

pub(super) async fn swagger_initializer() -> Response {
    static_response(
        SWAGGER_INITIALIZER_JS,
        "application/javascript; charset=utf-8",
        None,
    )
}

pub(super) async fn redoc() -> Response {
    static_response(REDOC_HTML, "text/html; charset=utf-8", Some(REDOC_CSP))
}
