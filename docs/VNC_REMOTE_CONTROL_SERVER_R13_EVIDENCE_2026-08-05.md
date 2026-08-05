# R13 — Integration and E2E Validation Evidence

Date: 2026-08-05

## Scope

R13 adds one permanent, bounded, real-Compose acceptance suite for the production desktop and controller images. The suite drives the public authenticated HTTP API against a real TigerVNC desktop and deterministic Tk test application. It validates connection lifecycle, coherent screenshots, input, clipboard, overload behavior, authentication boundaries, restart recovery, bounded resource growth, redaction, and shutdown.

## Permanent implementation

- Compose launcher: `tests/integration/run.sh`
- Integration driver: `tests/integration/r13_integration.py`
- Repository contracts: `tests/test_integration_contract.py`
- Deterministic desktop surface: `desktop/test-app/test_app.py`
- Authoritative CI wiring: `.github/workflows/ci.yml`
- Native incremental framebuffer contract: `tests/test_native_contract.py`

The launcher allocates collision-free loopback ports, generates ephemeral file-backed secrets, uses bounded readiness and operation deadlines, captures sanitized diagnostics only on failure, and always removes containers, volumes, networks, temporary secrets, and generated Compose overrides.

## Product defects exposed and repaired

### 1. Modifier chord transitions could arrive out of order

Real TigerVNC/X11 validation exposed printable modifier chords arriving with a release before the corresponding press under zero-delay transitions. A public `Ctrl+V` could leave `V` logically pressed.

Repair:

- chord transitions remain one atomic worker command;
- each native transition is separated by a fixed bounded 20 ms interval;
- there is no retry, fallback, or swallowed error;
- exact press order and reverse release order are asserted against the real desktop.

Relevant implementation commit: `5e2411dd88068d9efe1acadc6d29b5fd6f31c9a8`

### 2. Framebuffer delivery stopped after the initial full frame

The native LibVNCClient shim requested the initial full framebuffer but did not arm a subsequent incremental request. The first screenshot was coherent, but visible desktop changes never advanced the native framebuffer revision or screenshot ETag.

Repair:

- `FinishedFrameBufferUpdate` requests the next incremental update after every coherent frame;
- a request failure marks the native connection incomplete and disconnected;
- the failure is propagated through the normal worker reconnect path rather than ignored;
- a permanent native source contract prevents removal of the rearm behavior.

Relevant implementation commit: `c441c0caa6d91cc3b6033f923d4c899d6ecccb92`

### 3. Unsupported horizontal scrolling was silently discarded

`PointerScrollRequest` originally had no `delta_x` member. Serde therefore ignored a caller-supplied `delta_x` field and accepted the request as a zero-horizontal scroll. This was a quiet fallback that concealed unsupported input.

Repair:

- `delta_x` is an explicit default-zero request field;
- omitted `delta_x` remains backward-compatible for vertical-scroll callers;
- nonzero `delta_x` is recognized and rejected through the normal `422 invalid_request` response;
- a Rust regression test covers both omitted/default-zero and supplied/nonzero behavior;
- the real public API integration test verifies the explicit rejection.

Relevant implementation commit: `9323b09dcd0f13dbe0576a599926dd8b13d263b1`

## Connection and readiness evidence

The suite verifies:

- successful VNC authentication reaches `connected`;
- a wrong VNC password reaches `authentication_failed`;
- a missing VNC secret fails startup closed;
- stopping the desktop invalidates the old framebuffer;
- screenshots are unavailable while disconnected/reconnecting;
- automatic reconnect succeeds after desktop recreation;
- a complete current framebuffer exists before readiness returns;
- repeated restart cycles remain within bounded thread, file-descriptor, and resident-memory growth.

## Screenshot evidence

The suite verifies:

- display metadata is exactly `1280x800` and complete;
- the initial screenshot is a valid PNG with exact dimensions;
- a conditional request with the current ETag returns an empty `304`;
- clicking the deterministic Increment control visibly changes the framebuffer and ETag;
- screenshots are unavailable before the first complete frame and during reconnect;
- concurrent screenshot encoding remains bounded and returns explicit capacity/timeout responses rather than unbounded work.

## Input evidence

All input travels through the authenticated public API and the real worker/native/TigerVNC path. The deterministic desktop state proves:

- pointer movement reaches known coordinates;
- a left click activates the known Increment control and changes application state;
- middle and right clicks produce one exact down/up sequence each;
- double-click produces exactly two complete left-click sequences;
- vertical scrolling is delivered in both directions with exact step counts;
- horizontal scrolling is explicitly rejected in v0.1;
- individual key down/up order is preserved;
- multi-key chord press order and reverse release order are preserved;
- supported text is exact;
- unsupported text is rejected before any partial mutation.

## Clipboard evidence

The suite verifies:

- `clipboard_unavailable` before the first inbound desktop clipboard update;
- API-to-desktop clipboard delivery;
- paste through the deterministic desktop Paste control;
- copy through the deterministic desktop Copy control;
- retrieval of the exact last-known clipboard through the API;
- positive revision and timestamp metadata;
- oversized clipboard rejection without partial mutation or payload logging.

## Authentication and abuse evidence

The suite enumerates protected `/v1/*` routes and verifies missing and incorrect bearer tokens are rejected. It also verifies unauthenticated WebSocket rejection and that query-string tokens are not accepted.

Bounded failure behavior includes:

- oversized JSON rejection;
- out-of-range coordinate rejection;
- excessive scroll rejection;
- explicit unsupported horizontal-scroll rejection;
- explicit command-queue saturation with at least one accepted command and at least one `command_queue_full` response;
- explicit reconnect rate limiting;
- bounded concurrent screenshot behavior;
- absence of API token, VNC password, typed text, and clipboard fixture values from captured logs and diagnostics.

## Shutdown evidence

The suite verifies:

- idle SIGTERM exits the controller within a bounded deadline;
- SIGTERM with queued long-running commands rejects new work during shutdown;
- the worker connection closes;
- the worker thread joins as part of process termination;
- the controller exits without requiring SIGKILL;
- stopping the desktop terminates its owned child-process tree;
- final Compose cleanup removes containers, volumes, and networks.

## Validation runs

### Full R13 candidate after native framebuffer repair

- Run: `30973938130`
- Result: success
- Purpose: complete real-Compose R13 lifecycle, including screenshot revision advancement, overload, restart cycles, resource bounds, redaction, and shutdown.

### Final fail-closed assertion and API validation

- Run: `30993609334`
- Result: success
- Validated implementation commit: `9323b09dcd0f13dbe0576a599926dd8b13d263b1`
- Purpose: exact pointer event counts, explicit nonzero-horizontal-scroll rejection, and the complete real-Compose R13 suite.

### Temporary workflow cleanup

- Cleanup commit: `039ac05828f75119b6177c36a91a85bc5c952bb0`
- Temporary candidate, repair, and assertion workflows are not part of the permanent repository state.

## Acceptance conclusion

The permanent R13 suite passes against real production images and a real TigerVNC session. Failures are explicit and bounded. No silent input fallback remains for horizontal scrolling, incremental framebuffer failures fail visibly into reconnect behavior, and no retry was added to hide nondeterministic input ordering.

Ordinary CI on the final documentation/checklist SHA is the final exact-head repository gate.
