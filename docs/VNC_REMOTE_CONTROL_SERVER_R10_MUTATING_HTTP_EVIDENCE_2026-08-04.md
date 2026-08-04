# R10 Authenticated Mutating HTTP Route Evidence — 2026-08-04

## Scope

This evidence record covers the authenticated mutating HTTP router slice of R10. It does not claim completion of the TCP listener, request-header/body deadlines, graceful process shutdown, or real public HTTP-to-TigerVNC end-to-end testing.

## Implementation commit

```text
de92b71e9160e5f6319ea08029f7919f3660c2e9
```

The implementation commit was produced by a fail-closed isolated workflow and then fast-forwarded onto `master`. Its product diff changes only:

- `crates/controller-api/src/api_contract.rs`
- `crates/controller-api/src/http.rs`

The temporary generator and candidate workflow were deleted in the same commit. The temporary candidate tag was deleted after `master` reached the validated commit.

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

## Tests

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

## Isolated validation

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

## Authoritative master validation

```text
Evidence SHA: 33c8aa36a1da4f29729ac7d91e5bcced472192f9
CI run: 30940021044
Repository quality job: 92095798187
Desktop/native/E2E job: 92095798173
Artifact: ci-evidence-30940021044
Artifact ID: 8904759812
Result: success
```

The ordinary `master` workflow passed formatting, warning-denied Clippy, all Rust tests, warning-denied rustdoc, Python and shell contract gates, desktop image smoke, live native-adapter smoke, WorkerHandle input E2E, failure-diagnostic redaction self-test, and WorkerHandle text/clipboard E2E.

This evidence update is documentation-only and triggers one final ordinary CI run so the repository can close the slice on a SHA containing the completed evidence record.

## Remaining R10 work

- bind and serve the router on the configured TCP listener;
- implement bounded request-header and request-body deadlines;
- implement signal-driven graceful shutdown and stop accepting control requests;
- run authenticated public HTTP-to-worker-to-LibVNCClient-to-TigerVNC end-to-end tests;
- add slow-request tests;
- reconcile the authoritative R10 checklist after the remaining HTTP runtime slice is complete.
