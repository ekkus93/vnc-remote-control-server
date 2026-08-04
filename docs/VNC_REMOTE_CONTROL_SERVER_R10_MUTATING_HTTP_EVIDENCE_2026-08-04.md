# R10 Authenticated HTTP and Runtime Evidence — 2026-08-04

## Scope

This evidence record covers the authenticated HTTP router and the completed R10 runtime slice: the configured TCP listener, bounded header and body reads, signal-driven graceful shutdown, shutdown-time command rejection, and the real authenticated HTTP-to-worker-to-LibVNCClient-to-TigerVNC path.

## Router implementation commit

```text
de92b71e9160e5f6319ea08029f7919f3660c2e9
```

The router implementation commit introduced the authenticated mutating route surface and its fail-closed validation and error behavior.

## Routes implemented

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

All routes remain behind the existing `/v1/*` bearer-authentication middleware.

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

The router maps domain failures to payload-free stable error codes, including:

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

Native error strings, bearer tokens, typed text, and clipboard payloads are not included in error envelopes.

## Router tests

The router and API-contract tests cover:

- all pointer route families returning `202` and preserving preflighted commands;
- invalid coordinates failing before worker mutation;
- key, chord, text, and clipboard request conversion;
- unsupported text failing before enqueue;
- inbound clipboard success and unavailable behavior;
- queue-full, worker-unavailable, acknowledgement-timeout, and reconnect-rate-limit mappings;
- shutdown rejection before worker execution;
- oversized JSON rejection before worker execution;
- configuration rejection for a zero acknowledgement timeout.

## Router validation

```text
Workflow run: 30939727683
Candidate SHA: de92b71e9160e5f6319ea08029f7919f3660c2e9
Result: success
```

Validated gates:

- pinned Rust 1.97.1 formatting;
- whitespace checks;
- Clippy for all workspace targets/features with warnings denied;
- all Rust workspace tests with warnings denied;
- rustdoc for all workspace features with warnings denied;
- all Python contract tests.

## Router evidence validation on master

```text
Evidence SHA: 33c8aa36a1da4f29729ac7d91e5bcced472192f9
CI run: 30940021044
Repository quality job: 92095798187
Desktop/native/E2E job: 92095798173
Artifact: ci-evidence-30940021044
Artifact ID: 8904759812
Result: success
```

That ordinary `master` workflow passed formatting, warning-denied Clippy, all Rust tests, warning-denied rustdoc, Python and shell contract gates, desktop image smoke, live native-adapter smoke, WorkerHandle input E2E, failure-diagnostic redaction self-test, and WorkerHandle text/clipboard E2E.

## Runtime completion implementation

The runtime completion branch adds:

- a real TCP listener bound to `ControllerConfig::listen_address`;
- bounded HTTP/1 header reads (`VRC_HTTP_HEADER_TIMEOUT_MS`);
- bounded, length-limited request-body collection (`VRC_HTTP_BODY_TIMEOUT_MS`);
- SIGINT/SIGTERM-driven shutdown that marks `HttpState` as shutting down before the listener stops accepting sockets;
- bounded active-connection draining (`VRC_SHUTDOWN_GRACE_MS`) followed by worker shutdown and join;
- slow-header, slow-body, and oversized-body runtime tests;
- a real authenticated HTTP -> WorkerClient -> LibVNCClient -> TigerVNC E2E test.

## Runtime pull-request validation

```text
Pull request: #6
Validated head SHA: f0c7d8ee4a95a1cb154b83c87c3cbe8d84b9d494
CI run: 30945615936
Repository quality job: 92114729003
Desktop/native/E2E job: 92114729086
Result: success
```

The exact validated head passed:

- formatting;
- workspace Clippy for all targets and features with warnings denied;
- all Rust workspace tests, including the slow-header and slow-body runtime tests;
- warning-denied rustdoc;
- Python and shell contract gates;
- secured desktop image smoke;
- live native-adapter smoke;
- WorkerHandle input E2E;
- WorkerHandle failure-diagnostic redaction self-test;
- WorkerHandle text/clipboard E2E;
- authenticated HTTP -> worker -> LibVNCClient -> TigerVNC pointer mutation E2E;
- SIGTERM-driven bounded controller shutdown with secret-log checks.

The documentation-only successor containing this reconciled record must also pass ordinary pull-request CI before the branch is considered ready to merge.

## R10 boundary after this slice

The requested R10 runtime work is complete. Two checklist entries remain intentionally open because they belong to the later WebSocket/observability slice rather than this HTTP runtime slice:

- authenticate WebSocket upgrades;
- ensure future access logs redact the authorization header.
