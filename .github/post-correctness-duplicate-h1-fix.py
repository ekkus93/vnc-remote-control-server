from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Remove the redundant positive control introduced by the recovery helper while
# preserving the pre-existing adjacent matching-frame control.
reconnect = ROOT / "crates/controller-api/src/worker/tests/reconnect.rs"
text = reconnect.read_text(encoding="utf-8")
start = "struct MatchingSession {\n"
end = "#[test]\nfn mismatched_native_frame_never_reaches_connected() {\n"
if text.count(start) != 1:
    raise SystemExit(f"expected one redundant MatchingSession block, found {text.count(start)}")
if text.count(end) != 1:
    raise SystemExit(f"expected one mismatch-test anchor, found {text.count(end)}")
if text.count("fn matching_native_frame_positive_control_reaches_connected()") != 2:
    raise SystemExit("expected exactly two positive-control tests before cleanup")
begin = text.index(start)
finish = text.index(end, begin)
text = text[:begin] + text[finish:]
if text.count("fn matching_native_frame_positive_control_reaches_connected()") != 1:
    raise SystemExit("positive-control cleanup did not leave exactly one test")
fixture_start = text.index("struct MatchingFrameSession {")
fixture_end = text.index(
    "#[test]\nfn matching_native_frame_positive_control_reaches_connected() {",
    fixture_start,
)
fixture = text[fixture_start:fixture_end]
blocking_progress = "        let _ = self.poll_progress.send(self.poll_count);\n"
if fixture.count(blocking_progress) != 1:
    raise SystemExit("expected one blocking MatchingFrameSession progress send")
fixture = fixture.replace(
    blocking_progress,
    "        let _ = self.poll_progress.try_send(self.poll_count);\n",
    1,
)
text = text[:fixture_start] + fixture + text[fixture_end:]
reconnect.write_text(text, encoding="utf-8")

# Keep ServerEvent deliberately non-PartialEq; assert only the error variant.
events = ROOT / "crates/controller-api/src/events.rs"
text = events.read_text(encoding="utf-8")
old = '''        assert_eq!(first, Err(EventSequenceError::Exhausted));
        assert_eq!(second, Err(EventSequenceError::Exhausted));
'''
new = '''        assert!(matches!(first, Err(EventSequenceError::Exhausted)));
        assert!(matches!(second, Err(EventSequenceError::Exhausted)));
'''
if text.count(old) != 1:
    raise SystemExit(f"events.rs: expected one exhaustion assertion block, found {text.count(old)}")
events.write_text(text.replace(old, new, 1), encoding="utf-8")

# HttpState now requires the explicit secret-bearing ApiToken type. Update the
# remaining validation fixtures rather than restoring raw-string conversions.
access = ROOT / "crates/controller-api/src/http/tests/access_log_and_validation.rs"
text = access.read_text(encoding="utf-8")
empty = '            Arc::from(""),\n'
token = '            Arc::from("token"),\n'
if text.count(empty) != 1:
    raise SystemExit(f"access-log tests: expected one empty-token fixture, found {text.count(empty)}")
if text.count(token) != 3:
    raise SystemExit(f"access-log tests: expected three token fixtures, found {text.count(token)}")
text = text.replace(
    empty,
    '            ApiToken::from_secret(SecretString::from("")),\n',
    1,
)
text = text.replace(
    token,
    '            ApiToken::from_secret(SecretString::from("token")),\n',
)
access.write_text(text, encoding="utf-8")

# Metrics must report the backend-provided queue capacity. The mock explicitly
# supplies 64; retaining a zero expectation would reintroduce the H6 fallback.
commands = ROOT / "crates/controller-api/src/http/tests/commands.rs"
text = commands.read_text(encoding="utf-8")
old_metric = '    assert!(body.contains("vrc_worker_command_queue_capacity 0"));\n'
new_metric = '    assert!(body.contains("vrc_worker_command_queue_capacity 64"));\n'
if text.count(old_metric) != 1:
    raise SystemExit(f"commands.rs: expected one stale queue-capacity assertion, found {text.count(old_metric)}")
commands.write_text(text.replace(old_metric, new_metric, 1), encoding="utf-8")

# Factor the event subscription/snapshot preparation from the WebSocket upgrade
# response. Production still performs this before `on_upgrade`; the unit test can
# now exercise the real 503 mapping without Hyper's runtime-only OnUpgrade state.
handlers = ROOT / "crates/controller-api/src/http/handlers.rs"
text = handlers.read_text(encoding="utf-8")
old_import = "use crate::events::WebSocketCapacityError;\n"
new_import = "use crate::events::{EventSubscription, ServerEvent, WebSocketCapacityError};\n"
if text.count(old_import) != 1:
    raise SystemExit("handlers.rs: event import anchor mismatch")
text = text.replace(old_import, new_import, 1)
old_handler = '''pub(super) async fn events(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    websocket: WebSocketUpgrade,
) -> Result<Response, ApiError> {
    let subscription = state.events.subscribe().map_err(|WebSocketCapacityError| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "websocket_capacity",
            "WebSocket client capacity is exhausted",
            request_id.clone(),
        )
    })?;
    let snapshot = state.backend.snapshot();
    let clipboard_revision = state
        .backend
        .clipboard_snapshot()
        .ok()
        .map(|clipboard| clipboard.revision);
    let initial = state
        .events
        .snapshot_event(&snapshot, clipboard_revision)
        .map_err(|_| {
            ApiError::new(
                StatusCode::SERVICE_UNAVAILABLE,
                "event_sequence_exhausted",
                "event sequence is exhausted",
                request_id,
            )
        })?;
    let events = state.events.clone();
    Ok(websocket.on_upgrade(move |socket| async move {
        events.serve(socket, subscription, initial).await;
    }))
}
'''
new_handler = '''pub(super) fn prepare_event_session(
    state: &HttpState,
    request_id: RequestId,
) -> Result<(EventSubscription, ServerEvent), ApiError> {
    let subscription = state.events.subscribe().map_err(|WebSocketCapacityError| {
        ApiError::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "websocket_capacity",
            "WebSocket client capacity is exhausted",
            request_id.clone(),
        )
    })?;
    let snapshot = state.backend.snapshot();
    let clipboard_revision = state
        .backend
        .clipboard_snapshot()
        .ok()
        .map(|clipboard| clipboard.revision);
    let initial = state
        .events
        .snapshot_event(&snapshot, clipboard_revision)
        .map_err(|_| {
            ApiError::new(
                StatusCode::SERVICE_UNAVAILABLE,
                "event_sequence_exhausted",
                "event sequence is exhausted",
                request_id,
            )
        })?;
    Ok((subscription, initial))
}

pub(super) async fn events(
    State(state): State<HttpState>,
    Extension(request_id): Extension<RequestId>,
    websocket: WebSocketUpgrade,
) -> Result<Response, ApiError> {
    let (subscription, initial) = prepare_event_session(&state, request_id)?;
    let events = state.events.clone();
    Ok(websocket.on_upgrade(move |socket| async move {
        events.serve(socket, subscription, initial).await;
    }))
}
'''
if text.count(old_handler) != 1:
    raise SystemExit(f"handlers.rs: expected one events handler block, found {text.count(old_handler)}")
handlers.write_text(text.replace(old_handler, new_handler, 1), encoding="utf-8")

health = ROOT / "crates/controller-api/src/http/tests/health.rs"
text = health.read_text(encoding="utf-8")
old_health = '''#[tokio::test]
async fn websocket_initial_snapshot_sequence_exhaustion_fails_before_upgrade() {
    let state = test_state(true, MockScreenshot::Png);
    state.events.force_sequence_for_test(u64::MAX);
    let app = router(state.clone());

    let response = app
        .oneshot(
            request("/v1/events")
                .header(AUTHORIZATION, "Bearer test-token")
                .header("connection", "upgrade")
                .header("upgrade", "websocket")
                .header("sec-websocket-version", "13")
                .header("sec-websocket-key", "dGhlIHNhbXBsZSBub25jZQ==")
                .body(Body::empty())
                .expect("websocket request"),
        )
        .await
        .expect("response");
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
'''
new_health = '''#[test]
fn websocket_initial_snapshot_sequence_exhaustion_fails_before_upgrade() {
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
    let body = tokio_test_json_body(response);
    assert_eq!(body["error"]["code"], "event_sequence_exhausted");
    let metrics = state.metrics.render(
        &state.backend.snapshot(),
        state.backend.command_submissions_in_flight(),
        state.backend.command_queue_capacity(),
    );
    assert!(metrics.contains("vrc_websocket_clients 0"));
}

fn tokio_test_json_body(response: axum::response::Response) -> Value {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("test runtime");
    runtime.block_on(json_body(response))
}
'''
if text.count(old_health) != 1:
    raise SystemExit(f"health.rs: expected one WebSocket exhaustion test block, found {text.count(old_health)}")
health.write_text(text.replace(old_health, new_health, 1), encoding="utf-8")

for temporary in (
    ROOT / ".github/post-correctness-duplicate-h1-fix.py",
    ROOT / ".github/workflows/post-correctness-fixup.yml",
):
    temporary.unlink()
