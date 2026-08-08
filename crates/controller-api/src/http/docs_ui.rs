use axum::body::Body;
use axum::http::header::{CACHE_CONTROL, CONTENT_TYPE};
use axum::http::{HeaderValue, StatusCode};
use axum::response::Response;

const OPENAPI_JSON: &str = include_str!("../../../../docs/openapi.json");

// Vendored exact upstream Swagger UI / ReDoc distribution assets. See
// `../../third_party/MANIFEST.md` for upstream source, version, license,
// and pinned SHA-256 digests. Embedding via `include_str!` means these are
// compiled into the binary; the controller never fetches them over the
// network at startup or at request time.
const SWAGGER_UI_CSS: &str = include_str!("../../third_party/swagger-ui/5.32.11/swagger-ui.css");
const SWAGGER_UI_BUNDLE_JS: &str =
    include_str!("../../third_party/swagger-ui/5.32.11/swagger-ui-bundle.js");
const SWAGGER_UI_STANDALONE_PRESET_JS: &str =
    include_str!("../../third_party/swagger-ui/5.32.11/swagger-ui-standalone-preset.js");
const REDOC_STANDALONE_JS: &str = include_str!("../../third_party/redoc/2.5.3/redoc.standalone.js");

const SWAGGER_UI_HTML: &str = r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VNC Remote Control Server API — Swagger UI</title>
  <link rel="stylesheet" href="/docs/assets/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="/docs/assets/swagger-ui-bundle.js"></script>
  <script src="/docs/assets/swagger-ui-standalone-preset.js"></script>
  <script src="/docs/swagger-initializer.js"></script>
</body>
</html>
"#;

const SWAGGER_INITIALIZER_JS: &str = r##"window.addEventListener("load", () => {
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
"##;

const REDOC_HTML: &str = r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VNC Remote Control Server API — ReDoc</title>
</head>
<body>
  <redoc spec-url="/openapi.json"></redoc>
  <script src="/redoc/assets/redoc.standalone.js"></script>
</body>
</html>
"#;

const SWAGGER_CSP: &str = "default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
// ReDoc injects its component styles as inline `<style>` tags at runtime
// rather than through a stylesheet route, so `style-src` still requires
// `'unsafe-inline'` after local hosting; only script execution is
// restricted to `'self'`. `img-src data:` intentionally omits ReDoc's
// upstream `cdn.redoc.ly` origin (used only for an optional branding badge
// that fails closed via ReDoc's own `onError` handler — see
// `../../third_party/MANIFEST.md`).
const REDOC_CSP: &str = "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

fn static_response(
    body: &'static str,
    content_type: &'static str,
    csp: Option<&'static str>,
) -> Response {
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
        response
            .headers_mut()
            .insert("content-security-policy", HeaderValue::from_static(policy));
    }
    response
}

pub(super) async fn openapi_json() -> Response {
    static_response(OPENAPI_JSON, "application/json; charset=utf-8", None)
}

pub(super) async fn swagger_ui() -> Response {
    static_response(
        SWAGGER_UI_HTML,
        "text/html; charset=utf-8",
        Some(SWAGGER_CSP),
    )
}

pub(super) async fn swagger_initializer() -> Response {
    static_response(
        SWAGGER_INITIALIZER_JS,
        "application/javascript; charset=utf-8",
        None,
    )
}

pub(super) async fn swagger_ui_css_asset() -> Response {
    static_response(SWAGGER_UI_CSS, "text/css; charset=utf-8", None)
}

pub(super) async fn swagger_ui_bundle_js_asset() -> Response {
    static_response(
        SWAGGER_UI_BUNDLE_JS,
        "application/javascript; charset=utf-8",
        None,
    )
}

pub(super) async fn swagger_ui_standalone_preset_js_asset() -> Response {
    static_response(
        SWAGGER_UI_STANDALONE_PRESET_JS,
        "application/javascript; charset=utf-8",
        None,
    )
}

pub(super) async fn redoc() -> Response {
    static_response(REDOC_HTML, "text/html; charset=utf-8", Some(REDOC_CSP))
}

pub(super) async fn redoc_standalone_js_asset() -> Response {
    static_response(
        REDOC_STANDALONE_JS,
        "application/javascript; charset=utf-8",
        None,
    )
}
