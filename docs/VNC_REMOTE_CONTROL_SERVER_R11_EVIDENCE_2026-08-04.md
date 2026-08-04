# R11 WebSocket Events, Observability, and Overload Evidence — 2026-08-04

## Scope

R11 completes authenticated event delivery, structured tracing, bounded-label metrics, and overload/resource-limit behavior for the single-session controller.

## Event transport

- The existing authenticated `GET /v1/events` upgrade now sends a payload-free initial snapshot.
- Worker events are bridged from the bounded synchronous worker queue into a bounded Tokio broadcast channel.
- Every serialized event contains a process-local monotonically increasing sequence and Unix-millisecond timestamp.
- Delivered event types cover connection state, framebuffer revision, framebuffer invalidation, clipboard revision, overload, and protocol errors.
- Clipboard text, typed text, screenshot pixels, API tokens, and VNC passwords are absent from every event schema.

## WebSocket bounds

- Per-client buffering is bounded by `VRC_WEBSOCKET_EVENT_CAPACITY`.
- Total clients are bounded by `VRC_WEBSOCKET_MAX_CLIENTS`.
- Excess clients receive stable `503 websocket_capacity` before upgrade.
- Lagging clients are closed with code `1013` and a stable reason.
- Ping/pong heartbeat and idle cleanup are controlled by `VRC_WEBSOCKET_PING_INTERVAL_MS` and `VRC_WEBSOCKET_IDLE_TIMEOUT_MS`.
- Client permits and subscriptions are released on every disconnect path.

## Structured tracing and redaction

- The controller uses `tracing` plus JSON `tracing-subscriber` output.
- HTTP request spans include only method, path without query, and validated request ID.
- Access events include response status, bounded duration, and an authorization redaction marker.
- Worker and connection spans record state transitions, bounded failure classes, queue saturation, timeouts, and reconnect scheduling.
- Command logging uses bounded command classes and never retains command payloads.

## Metrics

Authenticated `GET /v1/metrics` emits Prometheus text using only fixed metric and label names. It covers:

- connection state and reconnect attempts/events;
- command totals by bounded command class;
- command queue depth/capacity and rejection totals;
- framebuffer revision and event/update failures;
- screenshot counts, outcomes, and aggregate durations;
- WebSocket clients, capacity rejections, slow-client disconnects, and idle disconnects;
- authentication and protocol errors.

No request ID, URL, key name, payload, clipboard text, typed text, pixel data, token, or password can become a metric label or value.

## Overload and resilience tests

- Direct worker tests saturate the bounded command queue and verify explicit `CommandQueueFull`, depth accounting, rejection accounting, and pending overload notification.
- Existing screenshot tests saturate the encode permit and verify bounded `Busy` behavior while timed-out work retains its permit.
- Event-hub tests publish 10,000 sustained events into a capacity-two client buffer and verify Tokio reports lag rather than allowing unbounded buffering.
- Event-hub tests enforce the configured total-client limit and verify permit cleanup.
- Existing worker stall tests and R10 HTTP deadline tests continue proving bounded behavior during VNC stalls and slow requests.
- The real TigerVNC E2E verifies authenticated snapshot/event delivery, reconnect events, strict sequence ordering, heartbeat handling, client-limit rejection, metrics, structured logs, redaction, and bounded shutdown.

## Validation

The implementation workflow runs:

- `cargo fmt --all --check`;
- `cargo test --workspace --all-features` to update and validate the lockfile;
- locked warning-denied Clippy for all targets and features;
- locked workspace tests;
- warning-denied rustdoc;
- Python compilation and unit tests;
- first-party shell syntax checks;
- the real authenticated HTTP/WebSocket-to-TigerVNC E2E test.

Exact implementation SHA and ordinary `master` CI evidence are appended after validation completes.
