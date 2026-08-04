from pathlib import Path
from textwrap import dedent


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


root_manifest = Path("Cargo.toml")
text = root_manifest.read_text(encoding="utf-8")
text = replace_once(
    text,
    'axum = { version = "=0.8.9", default-features = false, features = ["http1", "json", "tokio"] }',
    'axum = { version = "=0.8.9", default-features = false, features = ["http1", "json", "tokio", "ws"] }',
    "enable axum websocket feature",
)
root_manifest.write_text(text, encoding="utf-8")

http_path = Path("crates/controller-api/src/http.rs")
text = http_path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "use axum::extract::{DefaultBodyLimit, Extension, Request, State, rejection::JsonRejection};",
    dedent(
        """\
        use axum::extract::{
            DefaultBodyLimit, Extension, Request, State, rejection::JsonRejection,
            ws::{WebSocket, WebSocketUpgrade},
        };
        """
    ).rstrip(),
    "websocket imports",
)
text = replace_once(
    text,
    "use axum::http::{HeaderMap, HeaderName, HeaderValue, StatusCode};",
    "use axum::http::{HeaderMap, HeaderName, HeaderValue, Method, StatusCode};",
    "method import",
)
text = replace_once(
    text,
    "use std::time::{Duration, SystemTime, UNIX_EPOCH};",
    "use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};",
    "instant import",
)
text = replace_once(
    text,
    '        .route("/screenshot.png", get(screenshot))\n',
    '        .route("/screenshot.png", get(screenshot))\n        .route("/events", get(events))\n',
    "events route",
)
text = replace_once(
    text,
    "        .layer(DefaultBodyLimit::max(state.maximum_json_bytes))\n"
    "        .layer(middleware::from_fn_with_state(\n",
    "        .layer(DefaultBodyLimit::max(state.maximum_json_bytes))\n"
    "        .layer(middleware::from_fn(access_log))\n"
    "        .layer(middleware::from_fn_with_state(\n",
    "access log layer",
)

access_log_code = dedent(
    r'''
    #[derive(Debug)]
    struct AccessLogContext {
        method: Method,
        path: String,
        request_id: RequestId,
        authorization: &'static str,
    }

    impl AccessLogContext {
        fn from_request(request: &Request) -> Self {
            Self {
                method: request.method().clone(),
                path: request.uri().path().to_owned(),
                request_id: request_id(request),
                authorization: if request.headers().contains_key(AUTHORIZATION) {
                    "[REDACTED]"
                } else {
                    "absent"
                },
            }
        }
    }

    async fn access_log(request: Request, next: Next) -> Response {
        let context = AccessLogContext::from_request(&request);
        let started = Instant::now();
        let response = next.run(request).await;
        eprintln!(
            "{}",
            format_access_log(&context, response.status(), started.elapsed())
        );
        response
    }

    fn format_access_log(
        context: &AccessLogContext,
        status: StatusCode,
        elapsed: Duration,
    ) -> String {
        format!(
            "http_access method={} path={} status={} request_id={} authorization={} duration_ms={}",
            context.method,
            context.path,
            status.as_u16(),
            context.request_id.0,
            context.authorization,
            elapsed.as_millis()
        )
    }

    ''')
text = replace_once(
    text,
    "async fn require_bearer(State(state): State<HttpState>, request: Request, next: Next) -> Response {",
    access_log_code
    + "async fn require_bearer(State(state): State<HttpState>, request: Request, next: Next) -> Response {",
    "access log implementation",
)

websocket_code = dedent(
    r'''
    async fn events(websocket: WebSocketUpgrade) -> Response {
        websocket.on_upgrade(drain_authenticated_websocket)
    }

    async fn drain_authenticated_websocket(mut socket: WebSocket) {
        while let Some(message) = socket.recv().await {
            if message.is_err() {
                break;
            }
        }
    }

    ''')
text = replace_once(
    text,
    "async fn liveness() -> Json<HealthResponse> {",
    websocket_code + "async fn liveness() -> Json<HealthResponse> {",
    "websocket handler",
)

access_log_test = dedent(
    r'''
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
            let line = format_access_log(
                &context,
                StatusCode::OK,
                Duration::from_millis(12),
            );

            assert!(line.contains("method=GET"));
            assert!(line.contains("path=/v1/status"));
            assert!(line.contains("status=200"));
            assert!(line.contains("request_id=caller-1"));
            assert!(line.contains("authorization=[REDACTED]"));
            assert!(!line.contains("header-secret"));
            assert!(!line.contains("query-secret"));
            assert!(!line.contains("?token="));
        }

    ''')
text = replace_once(
    text,
    "    #[test]\n    fn state_validation_and_bearer_comparison_fail_closed() {",
    access_log_test
    + "    #[test]\n    fn state_validation_and_bearer_comparison_fail_closed() {",
    "access log redaction test",
)
http_path.write_text(text, encoding="utf-8")

e2e_path = Path("tests/http-e2e/run.sh")
text = e2e_path.read_text(encoding="utf-8")
websocket_test = dedent(
    r'''
    log "verifying WebSocket upgrades require bearer authentication"
    python3 - "$api_port" "$api_token" <<'PY'
    import base64
    import hashlib
    import os
    import socket
    import sys

    host = "127.0.0.1"
    port = int(sys.argv[1])
    api_token = sys.argv[2]
    websocket_guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def check_upgrade(path: str, authorization: str | None, expected_status: int) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        lines = [
            f"GET {path} HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        if authorization is not None:
            lines.append(f"Authorization: Bearer {authorization}")
        request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")

        with socket.create_connection((host, port), timeout=5) as sock:
            sock.settimeout(5)
            sock.sendall(request)
            response = bytearray()
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > 65536:
                    raise AssertionError("WebSocket handshake response exceeded limit")

            header_block = bytes(response).split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
            header_lines = header_block.split("\r\n")
            status = int(header_lines[0].split()[1])
            if status != expected_status:
                raise AssertionError(
                    f"{path} returned {status}, expected {expected_status}: {header_block}"
                )
            headers = {}
            for line in header_lines[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    headers[name.strip().lower()] = value.strip()

            if expected_status == 101:
                expected_accept = base64.b64encode(
                    hashlib.sha1((key + websocket_guid).encode("ascii")).digest()
                ).decode("ascii")
                if headers.get("sec-websocket-accept") != expected_accept:
                    raise AssertionError("authenticated upgrade returned invalid accept key")
                if headers.get("upgrade", "").lower() != "websocket":
                    raise AssertionError("authenticated upgrade omitted Upgrade: websocket")
                if "upgrade" not in headers.get("connection", "").lower():
                    raise AssertionError("authenticated upgrade omitted Connection: upgrade")
                sock.sendall(b"\x88\x80" + os.urandom(4))
            elif "sec-websocket-accept" in headers:
                raise AssertionError("unauthorized upgrade returned a WebSocket accept key")

    check_upgrade("/v1/events", None, 401)
    check_upgrade(f"/v1/events?token={api_token}", None, 401)
    check_upgrade("/v1/events", "wrong-token", 401)
    check_upgrade("/v1/events", api_token, 101)
    PY

    ''')
text = replace_once(
    text,
    dedent(
        """\
        grep -Fq '\"code\":\"unauthorized\"' "$temporary_directory/unauthorized.json" || \\
            fail "unauthenticated response did not use the stable error envelope"

        """
    ),
    dedent(
        """\
        grep -Fq '\"code\":\"unauthorized\"' "$temporary_directory/unauthorized.json" || \\
            fail "unauthenticated response did not use the stable error envelope"

        """
    )
    + websocket_test,
    "WebSocket E2E insertion",
)
text = replace_once(
    text,
    dedent(
        """\
        if grep -Fq "$api_token" "$controller_log"; then
            fail "controller log exposed the API token"
        fi

        """
    ),
    dedent(
        """\
        if grep -Fq "$api_token" "$controller_log"; then
            fail "controller log exposed the API token"
        fi
        grep -Fq 'authorization=[REDACTED]' "$controller_log" || \\
            fail "controller access log did not emit the authorization redaction marker"
        grep -Fq 'path=/v1/events status=101' "$controller_log" || \\
            fail "controller access log did not record the authenticated WebSocket upgrade"

        """
    ),
    "access log E2E assertions",
)
e2e_path.write_text(text, encoding="utf-8")

todo_path = Path("docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md")
text = todo_path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "- [ ] Authenticate WebSocket upgrades.",
    "- [x] Authenticate WebSocket upgrades.",
    "WebSocket checklist",
)
text = replace_once(
    text,
    "- [ ] Ensure access logs redact authorization header.",
    "- [x] Ensure access logs redact authorization header.",
    "access log checklist",
)
todo_path.write_text(text, encoding="utf-8")

evidence_path = Path("docs/VNC_REMOTE_CONTROL_SERVER_R10_MUTATING_HTTP_EVIDENCE_2026-08-04.md")
text = evidence_path.read_text(encoding="utf-8")
old_boundary = dedent(
    """\
    ## R10 boundary after this slice

    The requested R10 runtime work is complete. Two checklist entries remain intentionally open because they belong to the later WebSocket/observability slice rather than this HTTP runtime slice:

    - authenticate WebSocket upgrades;
    - ensure future access logs redact the authorization header.
    """
)
new_boundary = dedent(
    """\
    ## R10 completion

    Every R10 checklist item is now implemented on `master`.

    - `GET /v1/events` is an authenticated WebSocket upgrade shell. Missing, malformed, wrong, and query-string credentials fail with the same generic `401` response before upgrade; a correct bearer token completes a standards-compliant `101 Switching Protocols` handshake.
    - The R10 shell drains incoming WebSocket traffic without publishing events. Event envelopes, delivery, buffering, client limits, heartbeats, and slow-client handling remain the explicit R11 scope.
    - The access-log middleware records the HTTP method, URI path without its query string, response status, validated request ID, bounded duration, and either `authorization=[REDACTED]` or `authorization=absent`.
    - Raw bearer values and query-string token attempts are never written to access logs.
    - Unit coverage verifies the formatter cannot expose header or query secrets, and the real HTTP E2E verifies unauthenticated/query/wrong WebSocket attempts fail, an authenticated upgrade succeeds, the redaction marker is emitted, and the API/VNC secrets remain absent from controller logs.

    Exact final `master` CI evidence will be appended after the ordinary CI run completes.
    """
)
text = replace_once(text, old_boundary, new_boundary, "R10 evidence boundary")
evidence_path.write_text(text, encoding="utf-8")
