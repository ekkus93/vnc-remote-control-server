use super::handlers::{
    clipboard, display, events, keyboard_chord, keyboard_key, keyboard_text, liveness,
    metrics_endpoint, pointer_button, pointer_click, pointer_double_click, pointer_move,
    pointer_scroll, readiness, reconnect, screenshot, set_clipboard, status,
};
use super::middleware::{access_log, assign_request_id, require_bearer};
use super::state::HttpState;
use axum::Router;
use axum::extract::DefaultBodyLimit;
use axum::middleware;
use axum::routing::{get, post};

/// Builds the authenticated controller router.
pub fn router(state: HttpState) -> Router {
    let protected = Router::new()
        .route("/status", get(status))
        .route("/display", get(display))
        .route("/screenshot.png", get(screenshot))
        .route("/events", get(events))
        .route("/metrics", get(metrics_endpoint))
        .route("/pointer/move", post(pointer_move))
        .route("/pointer/button", post(pointer_button))
        .route("/pointer/click", post(pointer_click))
        .route("/pointer/double-click", post(pointer_double_click))
        .route("/pointer/scroll", post(pointer_scroll))
        .route("/keyboard/key", post(keyboard_key))
        .route("/keyboard/chord", post(keyboard_chord))
        .route("/keyboard/text", post(keyboard_text))
        .route("/clipboard", get(clipboard).put(set_clipboard))
        .route("/connection/reconnect", post(reconnect))
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            require_bearer,
        ));

    Router::new()
        .route("/health/live", get(liveness))
        .route("/health/ready", get(readiness))
        .nest("/v1", protected)
        .layer(DefaultBodyLimit::max(state.maximum_json_bytes))
        .layer(middleware::from_fn_with_state(state.clone(), access_log))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            assign_request_id,
        ))
        .with_state(state)
}
