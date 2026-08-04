# R10 Authenticated Read-Only HTTP Router Evidence

Date: 2026-08-04

## Scope

This record covers the first Axum HTTP implementation slice:

- public liveness and readiness endpoints;
- bearer-authenticated `/v1/status`, `/v1/display`, and `/v1/screenshot.png`;
- process-local request IDs;
- stable JSON error envelopes;
- screenshot ETag and conditional-response adaptation;
- shutdown-aware readiness;
- deterministic router tests over a narrow mockable backend.

Control routes, clipboard routes, reconnect, the TCP listener, signal handling, and full HTTP/TigerVNC integration remain later R10 slices.

## Implementation

```text
Validated source commit: 5cec964ff413ae0eedfb6f24eef8230d9f334958
Second validation commit: d66010a212aa5bf277dfae101fedf254975249c0
Master replay commit: 151053b0d6dccf6422b4cd27b321d0904e46122c
Atomic validation runs: 30936100767 and 30936258782
Temporary candidate tags: removed
Temporary validation and cleanup workflows: removed
```

The first atomic run was based on the temporary workflow's creation commit. A later trigger-only commit caused the validated candidate and `master` to diverge by one temporary workflow edit. The exact validated `http.rs` and `lib.rs` blobs were replayed onto the current `master` tree without a force update. A second atomic run independently validated the trigger-based tree and produced the same product behavior. Both temporary candidate tags were deleted.

## Backend boundary

`HttpBackend` contains only the read-only methods required by this slice:

- worker lifecycle snapshot;
- framebuffer metadata;
- screenshot capture with optional ETag.

`WorkerHttpBackend` is the production adapter over `WorkerClient` and `ScreenshotService`. Router tests use an in-memory mock and never start a native VNC thread.

## Authentication contract

- Every `/v1/*` route in this slice is behind one shared bearer-auth middleware.
- The parser requires the exact `Authorization: Bearer <token>` form.
- Missing, malformed, query-string-only, and incorrect tokens receive the same `401` status, code, and message.
- Tokens are never accepted from query parameters.
- Equal-length token values are compared through `subtle::ConstantTimeEq`.
- No bearer token is serialized into success or error bodies.

## Request ID contract

- A valid incoming `x-request-id` is accepted when it is 1-64 ASCII alphanumeric, dot, underscore, or hyphen bytes.
- Invalid or missing IDs are replaced with `<process-instance>-<sequence>`.
- Every handled response receives an `x-request-id` header.
- JSON error envelopes include the same request ID.
- Process-instance values are validated before router construction.

## Health and readiness

- `GET /health/live` is public and returns `200` while the router is serving.
- `GET /health/ready` is public.
- Readiness requires:
  - shutdown has not begun;
  - no fatal worker exit;
  - worker state is `connected`;
  - framebuffer state is `current`;
  - width, height, and update timestamp are available.
- Non-ready state returns stable JSON `503 not_ready`.
- `HttpState::begin_shutdown` makes readiness fail closed immediately.

## Authenticated observation routes

### `GET /v1/status`

Returns a redacted DTO containing:

- stable connection-state string;
- lifecycle timestamps as Unix milliseconds;
- reconnect attempt count;
- bounded failure category;
- framebuffer revision;
- rejected command and dropped event counts;
- fatal-exit and shutdown flags.

### `GET /v1/display`

Requires a current complete framebuffer and returns:

- width and height;
- depth `24`;
- framebuffer revision;
- update timestamp;
- `current` status and complete flag.

Unavailable, incomplete, or stale display state returns stable JSON `503 framebuffer_unavailable`.

### `GET /v1/screenshot.png`

- Screenshot encoding is executed through `tokio::task::spawn_blocking`.
- A current PNG returns `200`, `image/png`, ETag, and private no-cache policy.
- Matching `If-None-Match` returns `304` with ETag/cache headers.
- Unavailable or stale framebuffer maps to `503 framebuffer_unavailable`.
- Saturated screenshot capacity maps to `503 screenshot_busy`.
- Encoding timeout maps to `504 screenshot_timeout`.
- Internal encoder/native details are never sent to clients.

## Limits and construction checks

- The router installs the configured global Axum body limit.
- Empty API token, invalid process instance, and zero body limit fail router-state construction.
- Screenshot service construction failures remain redaction-safe.

## Tests

The Rust router tests cover:

- public liveness;
- ready and non-ready behavior;
- shutdown readiness failure;
- generic bearer failures for missing, query, malformed, and wrong credentials;
- accepted request-ID echo in both header and error body;
- invalid request-ID replacement;
- authenticated status and display DTOs;
- display-unavailable error mapping;
- PNG response body and headers;
- conditional `304` response;
- screenshot-unavailable JSON error;
- fail-closed state construction and bearer parsing.

## Atomic validation

Both candidate workflows passed:

```text
cargo fmt --all
git diff --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m unittest discover -s tests -p 'test_*.py' -v
```

No lint allowance, warning suppression, ignored test, downgraded error, or force update was used.

## Authoritative CI

Pending the ordinary `master` push created by this evidence record.

## Remaining R10 work

1. control/keyboard/text/clipboard/reconnect routes and typed JSON request DTOs;
2. command acknowledgement deadlines and stable worker error mapping;
3. request-body limit tests on mutating routes;
4. TCP listener and production `main` lifecycle;
5. signal-driven graceful shutdown and rejection of new control commands;
6. authenticated real HTTP/TigerVNC integration tests;
7. API documentation and exact curl fixtures.
