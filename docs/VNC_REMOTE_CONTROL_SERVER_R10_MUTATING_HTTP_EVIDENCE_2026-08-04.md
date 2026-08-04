# R10 Authenticated HTTP and Runtime Evidence — 2026-08-04

## Scope

This evidence record covers the completed R10 authenticated HTTP API and runtime on `master`:

- typed and fail-closed configuration;
- bearer authentication for every `/v1/*` route, including WebSocket upgrades;
- request IDs and stable payload-free error mapping;
- health, status, display, screenshot, pointer, keyboard, clipboard, and reconnect routes;
- bounded header, request-body, command-acknowledgement, screenshot, and shutdown deadlines;
- shutdown-time command rejection and graceful connection draining;
- access-log authorization redaction;
- real authenticated HTTP and WebSocket traffic through the production controller runtime;
- real HTTP-to-worker-to-LibVNCClient-to-TigerVNC control evidence.

## Router implementation

The authenticated mutating route surface and its fail-closed validation and error behavior were introduced at:

```text
Router implementation SHA: de92b71e9160e5f6319ea08029f7919f3660c2e9
Validation run: 30939727683
Result: success
```

The router implementation provides:

Pointer:

- `POST /v1/pointer/move`
- `POST /v1/pointer/button`
- `POST /v1/pointer/click`
- `POST /v1/pointer/double-click`
- `POST /v1/pointer/scroll`

Keyboard:

- `POST /v1/keyboard/key`
- `POST /v1/keyboard/chord`
- `POST /v1/keyboard/text`

Clipboard and connection:

- `GET /v1/clipboard`
- `PUT /v1/clipboard`
- `POST /v1/connection/reconnect`

Observation and health:

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/status`
- `GET /v1/display`
- `GET /v1/screenshot.png`

Every `/v1/*` route is protected by the same bearer-authentication boundary.

## Command semantics

- Request DTOs are deserialized and completely validated before worker submission.
- Pointer coordinates are validated against the current complete framebuffer dimensions.
- Horizontal scrolling remains outside the v0.1 contract; the HTTP request contains only `delta_y`.
- Double-click intervals, chord sizes, text contents, text sizes, clipboard contents, clipboard sizes, and scroll magnitudes are validated before enqueue.
- Production submission uses the bounded `WorkerClient` queue.
- The HTTP adapter waits for the configured bounded worker acknowledgement deadline.
- Success returns `202 Accepted` with a process-local command identifier and no input payload.
- New control operations are rejected after shutdown begins.

## Stable error behavior

The router maps domain failures to stable codes without exposing input payloads or native error strings, including:

- `invalid_coordinate`
- `framebuffer_unavailable`
- `chord_too_long`
- `text_too_large`
- `clipboard_too_large`
- `unsupported_text`
- `invalid_clipboard`
- `scroll_too_large`
- `command_queue_full`
- `worker_unavailable`
- `clipboard_unavailable`
- `command_timeout`
- `reconnect_rate_limited`
- `shutting_down`
- `payload_too_large`
- `invalid_json`
- `desktop_operation_failed`

Native errors, bearer tokens, typed text, clipboard payloads, and framebuffer pixels are not included in error envelopes.

## Runtime implementation

The production runtime on `master` provides:

- a real TCP listener bound to `ControllerConfig::listen_address`;
- bounded HTTP/1 header reads through `VRC_HTTP_HEADER_TIMEOUT_MS`;
- bounded, length-limited request-body collection through `VRC_HTTP_BODY_TIMEOUT_MS`;
- SIGINT/SIGTERM-driven shutdown that marks `HttpState` as shutting down before the listener stops accepting sockets;
- bounded active-connection draining through `VRC_SHUTDOWN_GRACE_MS`, followed by worker shutdown and join;
- slow-header, slow-body, oversized-body, and invalid-timeout tests;
- a real authenticated HTTP -> `WorkerClient` -> LibVNCClient -> TigerVNC pointer-mutation E2E test.

The runtime work was merged into `master` at:

```text
Master merge SHA: a69f8fef5355a8d32cd2986e1b00492238f86104
Validated implementation head: 6947634598c7d3705c6e8aefcb744046aa07f3e2
Validation run: 30946154368
Repository quality job: 92116564617
Desktop/native/HTTP E2E job: 92116564612
Result: success
```

That validation passed formatting, warning-denied Clippy, all Rust workspace tests, warning-denied rustdoc, Python and shell contract gates, secured desktop image smoke, live native-adapter smoke, WorkerHandle input E2E, failure-diagnostic redaction self-test, WorkerHandle text/clipboard E2E, authenticated HTTP-to-TigerVNC mutation, and bounded SIGTERM shutdown.

## Final R10 authentication and access-log completion

The final two R10 requirements were implemented directly on `master` at:

```text
Implementation SHA: b3b57b7e98284ad83ef84d0182f6f00d24bba841
Validation workflow: Complete remaining R10 items
Workflow run: 30954770309
Job: 92145112246
Result: success
```

The successful run validated, in order:

- application of the final implementation;
- Rust formatting;
- all workspace tests with every feature enabled;
- Clippy for all targets and features with warnings denied;
- locked workspace tests;
- rustdoc for all features with warnings denied;
- HTTP E2E shell syntax;
- real authenticated HTTP and WebSocket -> production controller -> worker -> LibVNCClient -> TigerVNC E2E;
- direct commit of the validated result to `master`.

The temporary executor workflow and patch script removed themselves in the validated implementation commit and are not present on `master`.

## Authenticated WebSocket upgrade

`GET /v1/events` now provides the authenticated R10 WebSocket upgrade shell.

- Missing credentials fail with the generic `401` response before upgrade.
- Malformed credentials fail with the same generic `401` response.
- An incorrect bearer token fails with the same generic `401` response.
- A token supplied only in the query string is rejected.
- A correct bearer token completes a standards-compliant `101 Switching Protocols` handshake.
- The authenticated shell drains incoming WebSocket traffic without publishing application events.

Event envelopes, initial state delivery, broadcasts, bounded per-client queues, client limits, heartbeat handling, slow-client handling, and event-resource cleanup remain R11 work. R11 extends the existing authenticated upgrade shell; it does not need to recreate the R10 authentication boundary.

## Access-log redaction

The access-log middleware records only bounded operational metadata:

- HTTP method;
- URI path without the query string;
- response status;
- validated or generated request ID;
- bounded request duration;
- either `authorization=[REDACTED]` or `authorization=absent`.

It does not record:

- raw `Authorization` values;
- query strings or query-string token attempts;
- API bearer tokens;
- VNC passwords;
- typed text;
- clipboard contents;
- framebuffer pixels.

Unit coverage verifies that the formatter cannot expose header or query secrets. The real E2E verifies the redaction marker is emitted, unauthenticated/query/wrong WebSocket attempts fail, an authenticated upgrade succeeds, and API/VNC secrets remain absent from controller logs.

## R10 completion decision

Every R10 checkbox in `docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md` is complete.

R10 is complete. R11 remains open for event delivery, structured observability, metrics, client-overload controls, and resilience testing.

Ordinary `master` CI for the exact documentation/evidence commit is published through the repository CI workflow and the machine-readable CI status issue. That external record is authoritative because a commit cannot contain the future run ID of the workflow that the same commit triggers.
