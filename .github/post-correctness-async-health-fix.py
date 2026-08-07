from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "crates/controller-api/src/http/tests/health.rs"
text = path.read_text(encoding="utf-8")
old = '''#[test]
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
new = '''#[tokio::test]
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
'''
if text.count(old) != 1:
    raise SystemExit(f"health.rs: expected one generated sync preparation test, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
Path(__file__).unlink()
