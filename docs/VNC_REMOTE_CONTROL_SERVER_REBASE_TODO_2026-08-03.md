# VNC Remote Control Server — Rebased Implementation TODO

Date: 2026-08-03
Repository: `ekkus93/vnc-remote-control-server`
Starting point: `master` at reviewed commit `da1d6d636c8ded87471ad7bc0ac493f1ef39e98a`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_REBASE_SPEC_2026-08-03.md`

---

## Status at creation

The repository is not v0.1-complete.

The latest reviewed CI state was red:

```text
Workflow: CI
Run: 30862582334
Attempt: 1
Commit: da1d6d636c8ded87471ad7bc0ac493f1ef39e98a
Problem job: Secured Debian desktop image
Problem step: Run desktop image smoke test
Observed issue: wrong-password TigerVNC probe misclassified authentication failure as a persistent session
```

The immediate next move is to repair the desktop smoke harness and prove the exact SHA is green before advancing into M3/native adapter work.

Do not mark a task complete merely because a type, stub, or placeholder exists. Mark completion only when the implementation, tests, and evidence for that task exist.

---

## R0 — Repair current red CI and rebaseline evidence

### R0.1 Fix wrong-password VNC smoke probe

- [ ] Inspect `tests/desktop/run.sh` `run_viewer_probe` behavior.
- [ ] Preserve captured viewer logs for both success and failure cases.
- [ ] For wrong-password probe, require authentication-failure text such as `Authentication failure` or `Authentication failed`.
- [ ] For wrong-password probe, reject evidence of an authenticated framebuffer/session.
- [ ] Stop treating `timeout 124` alone as proof that wrong-password authentication succeeded.
- [ ] For correct-password probe, require positive connection/authentication evidence.
- [ ] For correct-password probe, reject any authentication-failure text.
- [ ] Keep both probes bounded by timeout.
- [ ] Ensure failure messages print the relevant viewer log.

### R0.2 Re-run desktop smoke locally or in CI-equivalent environment

- [ ] Run `tests/desktop/run.sh` from a clean Docker state.
- [ ] Confirm image builds from the pinned Debian base digest.
- [ ] Confirm wrong-password probe fails closed and is diagnosable.
- [ ] Confirm correct-password probe reaches a persistent authenticated session.
- [ ] Confirm missing secret fails startup closed.
- [ ] Confirm runtime password is absent from image history and logs.
- [ ] Confirm desktop runs as UID `10001`.
- [ ] Confirm display dimensions are `1280x800`.
- [ ] Confirm test app state file is valid.
- [ ] Confirm shutdown behavior is deterministic.

### R0.3 Re-run repository quality gates

- [ ] Run `cargo fmt --all --check`.
- [ ] Run `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`.
- [ ] Run `cargo test --locked --workspace --all-features`.
- [ ] Run `cargo doc --locked --workspace --all-features --no-deps` with `RUSTDOCFLAGS=-Dwarnings`.
- [ ] Run `python -m compileall -q tools/ci_status tests desktop/test-app`.
- [ ] Run `python -m unittest discover -s tests -p 'test_*.py' -v`.
- [ ] Run shell syntax checks for first-party shell scripts.

### R0.4 Record rebaseline evidence

- [ ] Update this file with exact validation commands.
- [ ] Record the new commit SHA after the repair.
- [ ] Record the GitHub Actions run ID and job IDs.
- [ ] Confirm issue #1 reports `completed` / `success` for the exact SHA.
- [ ] Do not proceed to R2/R3 until R0 is green.

Evidence:

```text
Repair commit:
Local commands:
CI run:
CI conclusion:
Desktop job:
Quality job:
Issue #1 observed at:
Known limitations after R0:
```

---

## R1 — Documentation rebaseline

### R1.1 README accuracy

- [ ] Update README status so it no longer says the desktop image is a future milestone.
- [ ] Describe the current implemented baseline accurately.
- [ ] Describe explicit placeholders accurately: native adapter pending, controller API pending, Compose pending.
- [ ] Link to the rebased spec and TODO.
- [ ] Keep product boundary text aligned with v0.1 scope.
- [ ] Keep warning that raw VNC must not be exposed publicly.

### R1.2 TODO/spec linkage

- [ ] Add a short note to the original `docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md` pointing to this rebased TODO, or clearly document which file is now authoritative.
- [ ] Avoid conflicting milestone claims across documents.
- [ ] Preserve the original TODO for historical context unless deliberately superseded.

### R1.3 Operator warnings

- [ ] Document that production raw VNC host publishing is prohibited.
- [ ] Document that debug raw VNC must be loopback-only.
- [ ] Document that API and VNC secrets must come from secret files by default.
- [ ] Document that typed text, clipboard content, passwords, bearer tokens, and screenshots must not be logged.

Evidence:

```text
Docs commit:
Docs reviewed:
Commands:
CI run:
```

---

## R2 — Strengthen Rust/core model before native work

### R2.1 Explicit keyboard API serialization

- [ ] Decide the public JSON representation for symbolic keys.
- [ ] Implement custom serialization/deserialization or wrapper request DTOs so API shape is stable.
- [ ] Ensure printable single-character keys are represented deliberately.
- [ ] Ensure raw numeric keysyms are never accepted by the public API.
- [ ] Add tests for every required symbolic key.
- [ ] Add tests for printable ASCII chord keys.
- [ ] Add tests for unknown key names.
- [ ] Add tests showing derived Serde enum shape is not accidentally exposed.

### R2.2 Text support matrix

- [ ] Document exact supported v0.1 text range.
- [ ] Confirm `\n`, `\r`, `\t`, and printable ASCII handling is intentional.
- [ ] Add fixtures for boundary characters.
- [ ] Add unsupported Unicode fixtures.
- [ ] Add oversized text fixtures.
- [ ] Add test proving unsupported text fails before partial input.

### R2.3 Clipboard validation policy

- [ ] Confirm embedded NUL policy is rejection.
- [ ] Add explicit doc comment or API schema note for embedded NUL behavior.
- [ ] Add tests for byte limit at boundary.
- [ ] Add tests for invalid or unsupported clipboard payloads once HTTP body parsing exists.

### R2.4 Framebuffer domain tests

- [ ] Add known-size RGBA snapshot fixtures.
- [ ] Add edge rectangle tests for every boundary.
- [ ] Add malformed rectangle tests.
- [ ] Add overflow rectangle tests.
- [ ] Add reconnect invalidation model tests once framebuffer store exists.

Evidence:

```text
Core commit:
Commands:
Tests added:
CI run:
```

---

## R3 — Native build and binding strategy

### R3.1 Native package support

- [ ] Add required native development packages to the controller build image or documented dev environment.
- [ ] Include `libvncserver-dev`/LibVNCClient headers as appropriate.
- [ ] Include C compiler and `pkg-config` where needed.
- [ ] Ensure missing native dependencies produce actionable build errors.
- [ ] Ensure release builds do not depend on undeclared host libraries.

### R3.2 Binding strategy decision

- [ ] Decide generated bindings versus reviewed checked-in bindings.
- [ ] Document decision in a new adapter design note or in module-level docs.
- [ ] If generated, add `wrapper.h` containing only required public headers.
- [ ] If generated, add `build.rs` bindgen invocation.
- [ ] If generated, restrict allowlists to required LibVNCClient types/functions/constants.
- [ ] If generated, add rerun directives for `wrapper.h`, `build.rs`, and relevant env changes.
- [ ] If checked-in, commit reviewed minimal bindings and document regeneration/review policy.
- [ ] Add native dependency version capture.

### R3.3 Adapter build tests

- [ ] Add a build-only adapter test that links LibVNCClient.
- [ ] Add CI job coverage for adapter build environment.
- [ ] Ensure `cargo test --workspace --all-features` works in the native-enabled environment.
- [ ] Ensure local missing-dependency failure is clear.

Evidence:

```text
Binding strategy:
Native packages:
LibVNCClient version:
Build command:
CI run:
```

---

## R4 — Minimal LibVNCClient connection spike

### R4.1 Safe allocation and credentials

- [ ] Allocate an `rfbClient` safely.
- [ ] Define ownership for the native client allocation.
- [ ] Configure credential callback state.
- [ ] Read the mounted VNC password without logging it.
- [ ] Ensure callback context lives long enough for the native client lifetime.

### R4.2 Connect to real desktop container

- [ ] Start the real desktop container.
- [ ] Connect to TigerVNC on the private/expected endpoint.
- [ ] Authenticate with the mounted VNC password.
- [ ] Receive server metadata.
- [ ] Record protocol version and dimensions.

### R4.3 Frame/input/clipboard spike

- [ ] Allocate framebuffer through the supported callback path.
- [ ] Process server messages until a complete frame arrives.
- [ ] Capture proof of initial framebuffer dimensions.
- [ ] Send one pointer move.
- [ ] Send one key press and release.
- [ ] Send one clipboard value.
- [ ] Confirm deterministic test app observed pointer/key input where practical.

### R4.4 Cleanup spike

- [ ] Disconnect cleanly.
- [ ] Free all native resources.
- [ ] Verify cleanup completes without crash or hang.
- [ ] Remove throwaway spike code or promote it into production modules with tests.

Evidence:

```text
Spike command:
Output:
Framebuffer dimensions:
Pointer proof:
Key proof:
Clipboard proof:
Cleanup proof:
Native versions:
```

---

## R5 — FFI safety contract and RAII adapter

### R5.1 Module-level safety contract

- [ ] Write adapter safety invariants in module-level documentation.
- [ ] State raw pointer ownership rules.
- [ ] State callback lifetime rules.
- [ ] State panic containment rules.
- [ ] State buffer validation rules.
- [ ] State cleanup ordering.
- [ ] State redaction rules.

### R5.2 RAII wrapper

- [ ] Implement private RAII wrapper for `rfbClient*`.
- [ ] Prevent raw pointers from crossing crate boundaries.
- [ ] Guarantee one owner for every raw allocation.
- [ ] Guard cleanup against double invocation.
- [ ] Define cleanup behavior for partial initialization failures.
- [ ] Add tests/harness for failed initialization at each stage.

### R5.3 Callback safety

- [ ] Store callback context in stable memory for full C-client lifetime.
- [ ] Prevent Rust panics from crossing C callbacks.
- [ ] Validate callback dimensions before memory access.
- [ ] Validate rectangle coordinates before memory access.
- [ ] Use checked arithmetic for all buffer calculations.
- [ ] Convert native failures into typed adapter errors.
- [ ] Redact secrets and payload contents from adapter error formatting.

Evidence:

```text
Adapter commit:
Safety docs:
Failure-stage tests:
Commands:
CI run:
```

---

## R6 — Production worker lifecycle

### R6.1 Worker ownership

- [ ] Create worker type that owns the adapter connection.
- [ ] Spawn exactly one native thread for the configured session.
- [ ] Prevent Axum/Tokio tasks from directly touching adapter state.
- [ ] Use bounded command channel.
- [ ] Use bounded event/broadcast mechanism.
- [ ] Implement worker startup acknowledgement.
- [ ] Implement command completion or enqueue acknowledgement semantics.
- [ ] Implement worker shutdown and thread join.
- [ ] Treat unexpected worker exit as fatal readiness failure.

### R6.2 Connection state machine

- [ ] Implement every public state from the spec.
- [ ] Validate allowed transitions.
- [ ] Publish transition events.
- [ ] Track connection timestamps.
- [ ] Track reconnect attempts.
- [ ] Distinguish authentication, configuration, transport, timeout, and protocol failures.
- [ ] Ensure authentication failure does not retry rapidly.
- [ ] Ensure configuration failure does not masquerade as transient disconnect.

### R6.3 Reconnection

- [ ] Implement exponential backoff.
- [ ] Add bounded jitter.
- [ ] Add configurable min and max delays.
- [ ] Reset backoff after stable connection.
- [ ] Implement rate-limited manual reconnect.
- [ ] Invalidate framebuffer on disconnect.
- [ ] Clear pressed-key and button bookkeeping on disconnect.
- [ ] Request full framebuffer update after reconnect.
- [ ] Require complete frame before readiness returns.
- [ ] Test repeated desktop restart cycles.

### R6.4 Stall detection

- [ ] Track last successful server message time.
- [ ] Define idle desktop versus stalled connection.
- [ ] Use protocol-safe probes or refresh requests where needed.
- [ ] Apply bounded stall timeout.
- [ ] Transition visibly to degraded/reconnecting on confirmed stall.
- [ ] Ensure requests do not wait indefinitely during stall.

Evidence:

```text
Worker commit:
State tests:
Reconnect tests:
Stall tests:
CI run:
```

---

## R7 — Framebuffer and screenshots

### R7.1 Canonical framebuffer store

- [ ] Implement canonical RGBA8 storage.
- [ ] Implement safe stride/allocation calculations.
- [ ] Implement conversion from selected LibVNCClient pixel format.
- [ ] Handle server dimension metadata safely.
- [ ] Reject dimensions above configured memory limits.
- [ ] Implement complete/incomplete state.
- [ ] Implement monotonically increasing process-local revisions.
- [ ] Track update timestamps.

### R7.2 Dirty rectangle updates

- [ ] Validate every rectangle origin and extent.
- [ ] Reject overflow in `x + width` and `y + height`.
- [ ] Reject rectangles outside framebuffer.
- [ ] Copy updates without out-of-bounds access.
- [ ] Decide revision semantics.
- [ ] Document revision semantics.
- [ ] Test selected revision semantics.
- [ ] Publish framebuffer update events only after coherent commit.

### R7.3 Snapshot consistency

- [ ] Implement immutable framebuffer snapshots.
- [ ] Ensure snapshot creation cannot observe partially copied rectangle.
- [ ] Keep locks out of long PNG encoding work.
- [ ] Return unavailable while no complete frame exists.
- [ ] Return stale/incomplete state after disconnect rather than serving old pixels as current.

### R7.4 PNG support

- [ ] Select maintained PNG encoder.
- [ ] Encode RGBA8 snapshots.
- [ ] Add bounded concurrent encode permits.
- [ ] Add encode timeout handling.
- [ ] Generate ETags from process instance and framebuffer revision.
- [ ] Support `If-None-Match` and `304`.
- [ ] Set correct `Content-Type`.
- [ ] Set correct cache-control headers.
- [ ] Test exact dimensions.
- [ ] Test valid PNG structure.

### R7.5 Framebuffer safety tests

- [ ] Add known pixel conversion fixtures.
- [ ] Add edge rectangle tests at every boundary.
- [ ] Add malformed/overflow rectangle tests.
- [ ] Add concurrent update/snapshot stress tests.
- [ ] Add reconnect invalidation tests.
- [ ] Run native sanitizers on update paths where practical.

Evidence:

```text
Framebuffer commit:
PNG encoder:
Revision semantics:
Tests:
CI run:
```

---

## R8 — Pointer, mouse, scrolling, and keyboard control

### R8.1 Pointer movement

- [ ] Implement strict coordinate validation against current dimensions.
- [ ] Reject movement while dimensions are unknown.
- [ ] Send pointer movement with current button mask.
- [ ] Do not silently clamp coordinates.
- [ ] Test all four display edges.
- [ ] Test out-of-range values.

### R8.2 Mouse buttons and clicks

- [ ] Map left, middle, and right buttons to RFB masks.
- [ ] Maintain full current mask, not only latest button.
- [ ] Implement explicit button down and up.
- [ ] Implement atomic click worker commands.
- [ ] Implement atomic double-click worker commands.
- [ ] Bound configurable double-click intervals.
- [ ] Clear local button state on disconnect.
- [ ] Add best-effort release behavior on partial command failure.

### R8.3 Scrolling

- [ ] Verify TigerVNC vertical wheel mask behavior.
- [ ] Verify TigerVNC horizontal wheel mask behavior.
- [ ] If horizontal wheel is not verified, remove it from v0.1 API/spec before release.
- [ ] Convert signed deltas into bounded wheel steps.
- [ ] Reject excessive step counts.
- [ ] Keep scroll sequences atomic inside worker.
- [ ] Confirm deterministic test app receives expected direction/count.

### R8.4 Keyboard map

- [ ] Implement required modifiers.
- [ ] Implement navigation keys.
- [ ] Implement editing keys.
- [ ] Implement arrows.
- [ ] Implement F1-F12.
- [ ] Implement printable ASCII keys needed for chords.
- [ ] Reject unknown symbolic names.
- [ ] Keep raw numeric keysyms out of public API.

### R8.5 Key state and chords

- [ ] Implement explicit key down and up.
- [ ] Track locally pressed keys.
- [ ] Implement chord press order.
- [ ] Implement reverse release order.
- [ ] Bound chord length.
- [ ] Prevent duplicate modifier state corruption.
- [ ] Best-effort release keys after partial failure.
- [ ] Clear key state on disconnect and shutdown.
- [ ] Test `CTRL_LEFT + ALT_LEFT + T` end to end.

Evidence:

```text
Input commit:
Pointer tests:
Mouse tests:
Scroll tests:
Keyboard tests:
E2E proof:
CI run:
```

---

## R9 — Text and clipboard correctness

### R9.1 Text input

- [ ] Define exact v0.1 supported ASCII range.
- [ ] Implement preflight validation for complete string.
- [ ] Ensure unsupported characters fail before any character is sent.
- [ ] Map supported characters to modifier/keysym sequences.
- [ ] Preserve exact character order.
- [ ] Bound text input bytes.
- [ ] Return accepted character count and strategy.
- [ ] Never log typed text.
- [ ] Test supported text through deterministic app.
- [ ] Test unsupported text produces no partial mutation.

### R9.2 Unicode investigation

- [ ] Test TigerVNC Unicode keysym support with representative characters.
- [ ] Test characters outside Latin-1.
- [ ] Document actual interoperability findings.
- [ ] Add only verified Unicode support.
- [ ] Keep unsupported characters explicit.
- [ ] Decide whether clipboard paste is a future explicit strategy.

### R9.3 Outbound clipboard

- [ ] Implement UTF-8 HTTP validation.
- [ ] Enforce clipboard byte limit.
- [ ] Reject embedded NUL unless policy is deliberately changed.
- [ ] Send clipboard content through LibVNCClient.
- [ ] Return success only for accepted send/enqueue operations.
- [ ] Never log clipboard contents.
- [ ] Test API set clipboard and test app paste exact expected text.
- [ ] Test oversized clipboard rejection.

### R9.4 Inbound clipboard

- [ ] Capture server clipboard callbacks.
- [ ] Decode according to verified TigerVNC/RFB behavior.
- [ ] Reject or visibly report invalid encoding.
- [ ] Store text, revision, and timestamp.
- [ ] Return `clipboard_unavailable` before first callback.
- [ ] Publish clipboard revision events without text.
- [ ] Test app copy -> API receives expected snapshot.
- [ ] Test clipboard revision increments predictably.
- [ ] Verify clipboard content absent from logs/metrics/events.

Evidence:

```text
Text/clipboard commit:
Text fixtures:
Clipboard fixtures:
Encoding findings:
CI run:
```

---

## R10 — Authenticated HTTP API

### R10.1 Typed configuration

- [x] Implement typed configuration loading.
- [x] Load non-secret values from env.
- [x] Load API token and VNC password from files by default.
- [x] Permit env secrets only in documented dev mode, if at all.
- [x] Validate socket addresses.
- [x] Validate ports.
- [x] Validate capacities.
- [x] Validate limits.
- [x] Validate timeouts.
- [x] Reject empty secrets.
- [x] Warn/fail on overly broad secret-file permissions according to policy.
- [x] Redact secret values from debug output.

### R10.2 Authentication middleware

- [x] Require `Authorization: Bearer <token>` for all `/v1/*` routes.
- [x] Authenticate WebSocket upgrades.
- [x] Never accept tokens in query parameters.
- [x] Use timing-resistant comparison where practical.
- [x] Return same generic response for missing and invalid tokens.
- [x] Ensure access logs redact authorization header.
- [x] Test missing token.
- [x] Test malformed token.
- [x] Test wrong token.
- [x] Test correct token.
- [x] Test query-string token rejection.

### R10.3 Request IDs and errors

- [x] Accept valid incoming request ID or generate one.
- [x] Return request ID in response headers.
- [x] Return request ID in error body.
- [x] Implement JSON error envelope.
- [x] Map every domain error to stable code/status.
- [x] Prevent raw native errors from reaching clients.
- [x] Prevent secrets/payloads from reaching clients.
- [x] Test representative errors for every endpoint family.

### R10.4 Health/status/display

- [x] Implement `GET /health/live`.
- [x] Implement `GET /health/ready`.
- [x] Ensure liveness does not imply VNC readiness.
- [x] Ensure readiness requires complete framebuffer.
- [x] Implement `GET /v1/status`.
- [x] Implement `GET /v1/display`.
- [x] Verify no secret/password is serialized.

### R10.5 Screenshot route

- [x] Implement `GET /v1/screenshot.png`.
- [x] Add ETag support.
- [x] Add conditional GET support.
- [x] Return JSON error when unavailable.
- [x] Apply encode concurrency limit.
- [x] Apply encode deadline.

### R10.6 Pointer routes

- [x] Implement `POST /v1/pointer/move`.
- [x] Implement `POST /v1/pointer/button`.
- [x] Implement `POST /v1/pointer/click`.
- [x] Implement `POST /v1/pointer/double-click`.
- [x] Implement `POST /v1/pointer/scroll`.
- [x] Validate all payloads before enqueue.
- [x] Return `202` for accepted asynchronous commands.

### R10.7 Keyboard routes

- [x] Implement `POST /v1/keyboard/key`.
- [x] Implement `POST /v1/keyboard/chord`.
- [x] Implement `POST /v1/keyboard/text`.
- [x] Ensure text preflight completes before enqueue.
- [x] Enforce chord limit.
- [x] Enforce text limit.

### R10.8 Clipboard and connection routes

- [x] Implement `GET /v1/clipboard`.
- [x] Implement `PUT /v1/clipboard`.
- [x] Implement `POST /v1/connection/reconnect`.
- [x] Rate-limit manual reconnect.
- [x] Return `202` for accepted reconnect request.

### R10.9 HTTP limits and shutdown behavior

- [x] Enforce global JSON body limit.
- [x] Enforce route-specific text limit.
- [x] Enforce route-specific clipboard limit.
- [x] Add request header timeout.
- [x] Add request body timeout.
- [x] Add operation acknowledgement timeout.
- [x] Reject new control commands during shutdown.
- [x] Test slow requests.
- [x] Test oversized requests.

Evidence:

```text
Master implementation SHA: b3b57b7e98284ad83ef84d0182f6f00d24bba841
Final evidence SHA: fcfef9de44aaaa389805cce00ce65dc422045edb
Routes implemented: health, status, display, screenshot, pointer, keyboard, clipboard, reconnect, authenticated WebSocket upgrade shell
Auth tests: missing, malformed, wrong, correct, query-string rejection, and real WebSocket handshake E2E
Error tests: stable JSON envelope and domain mapping unit tests
Limit tests: body size, header deadline, body deadline, acknowledgement deadline, shutdown rejection
Runtime E2E: authenticated HTTP/WebSocket -> WorkerClient -> LibVNCClient -> TigerVNC
Final R10 executor run: 30954770309
Final R10 executor job: 92145112246 (success)
Final ordinary master CI run: 30955178017
Quality job: 92146417492 (success)
Desktop/native/HTTP E2E job: 92146417477 (success)
```

---

## R11 — WebSocket events, observability, overload

### R11.1 Event envelope

- [x] Implement global process-local event sequence numbers.
- [x] Implement event timestamps.
- [x] Implement required event types.
- [x] Keep clipboard text out of events.
- [x] Keep typed text out of events.
- [x] Keep screenshot pixels out of events.

### R11.2 WebSocket endpoint

- [x] Extend the authenticated `/v1/events` upgrade shell with event delivery.
- [x] Send initial connection-state snapshot.
- [x] Broadcast connection changes.
- [x] Broadcast framebuffer revisions.
- [x] Broadcast framebuffer invalidation.
- [x] Broadcast clipboard revision changes.
- [x] Broadcast overload notifications.
- [x] Broadcast protocol error notifications.
- [x] Bound per-client buffering.
- [x] Disconnect slow clients with clear close code/reason.
- [x] Limit total WebSocket clients.
- [x] Add ping/pong or idle detection.
- [x] Clean up client resources on disconnect.

### R11.3 Structured logs

- [x] Select tracing stack.
- [x] Add request spans and request IDs.
- [x] Add connection spans.
- [x] Add worker spans.
- [x] Log state transitions.
- [x] Log queue saturation.
- [x] Log timeouts.
- [x] Log reconnect attempts/outcomes.
- [x] Add redaction policy.
- [x] Add redaction tests.
- [x] Verify API token absent from logs.
- [x] Verify VNC password absent from logs.
- [x] Verify typed text absent from logs.
- [x] Verify clipboard content absent from logs.
- [x] Verify pixels absent from logs.

### R11.4 Metrics

- [x] Add internal metrics endpoint or listener.
- [x] Track connection state.
- [x] Track reconnect attempts/outcomes.
- [x] Track command totals by bounded command type label.
- [x] Track queue depth/capacity.
- [x] Track framebuffer revisions/update failures.
- [x] Track screenshot encode counts/durations/failures.
- [x] Track WebSocket clients/slow disconnects.
- [x] Track protocol/authentication errors.
- [x] Avoid unbounded labels such as request ID, key, URL, or error message.

### R11.5 Overload and resilience tests

- [x] Saturate worker queue and verify `command_queue_full`.
- [x] Saturate PNG encoding permits and verify bounded behavior.
- [x] Connect maximum WebSocket clients and reject excess clients predictably.
- [x] Simulate slow WebSocket client and verify disconnection.
- [x] Simulate stalled VNC connection and verify API deadlines.
- [x] Verify process memory remains bounded during sustained events.

Evidence:

```text
Implementation: direct master change validated by the R11 completion workflow
Event tests: event envelope, client limit, sequence ordering, lag/slow-client closure, real reconnect delivery
Log redaction tests: unit redaction plus real API/VNC/text/clipboard secret absence checks
Metrics tests: fixed-label unit tests plus authenticated real endpoint E2E
Overload tests: worker queue, PNG permit, broadcast lag, stalled worker, HTTP deadline coverage
Evidence document: docs/VNC_REMOTE_CONTROL_SERVER_R11_EVIDENCE_2026-08-04.md
Final SHA and CI run: appended after exact master validation
```

---

## R12 — Controller image, Compose, and persistence

### R12.1 Controller image

- [x] Create multi-stage controller Dockerfile.
- [x] Build Rust binaries in dedicated build stage.
- [x] Include required LibVNCClient runtime libraries in final image.
- [x] Exclude compiler from final image.
- [x] Exclude Cargo registry from final image.
- [x] Exclude build secrets from final image.
- [x] Run as dedicated non-root user.
- [x] Add minimal init if needed.
- [x] Add liveness/readiness health checks.

### R12.2 Production Compose

- [x] Add `deploy/compose.yaml`.
- [x] Create internal network for desktop-controller traffic.
- [x] Use `expose: 5901` for desktop.
- [x] Do not publish desktop VNC port in production.
- [x] Publish only controller API port.
- [x] Mount API token and VNC password as secrets.
- [x] Enable `no-new-privileges`.
- [x] Make controller root filesystem read-only where practical.
- [x] Add bounded temporary filesystems.
- [x] Do not mount Docker socket.

### R12.3 Debug VNC profile

- [x] Add development-only Compose override/profile.
- [x] Bind raw VNC only to `127.0.0.1:5901:5901`.
- [x] Add prominent not-for-production documentation.
- [x] Verify production Compose has no inherited host VNC binding.

### R12.4 Persistence modes

- [x] Make disposable desktop state the default.
- [x] Add optional named-volume profile for desktop home directory.
- [x] Document which state persists.
- [x] Verify secrets are not copied into persistent home volume.
- [x] Verify disposable recreation clears desktop state.
- [x] Verify persistent recreation preserves expected state.

### R12.5 Compose smoke tests

- [x] Start from clean Docker state.
- [x] Wait for desktop health.
- [x] Wait for controller health.
- [x] Authenticate to API.
- [x] Fetch status.
- [x] Fetch display.
- [x] Fetch screenshot.
- [x] Confirm host port `5901` absent in production mode.
- [x] Confirm `5901` bound only to loopback in debug mode.
- [x] Confirm bounded shutdown and cleanup.

Evidence:

```text
Controller image: controller/Dockerfile
Production Compose: deploy/compose.yaml
Debug override: deploy/compose.debug-vnc.yaml
Persistence override: deploy/compose.persistence.yaml
Static contracts: tests/test_deployment_contract.py
Runtime smoke: tests/compose/run.sh
Evidence document: docs/VNC_REMOTE_CONTROL_SERVER_R12_EVIDENCE_2026-08-04.md
Executor run: 30967019129
Final implementation SHA and ordinary CI: appended after exact master validation
```

---

## R13 — Integration and E2E validation

### R13.1 Integration harness

- [x] Create scripts or Rust tests that launch real Compose stack.
- [x] Allocate collision-free host API ports in CI.
- [x] Generate ephemeral test secrets.
- [x] Wait on readiness with bounded deadline.
- [x] Capture container logs on failure.
- [x] Always tear down containers, volumes, and networks.

### R13.2 Connection tests

- [x] Successful authentication reaches `connected`.
- [x] Wrong VNC password reaches `authentication_failed`.
- [x] Missing VNC secret fails startup closed.
- [x] Desktop restart causes disconnect detection.
- [x] Automatic reconnect succeeds.
- [x] Old framebuffer becomes unavailable during reconnect.
- [x] Full framebuffer returns before readiness.
- [x] Repeated restart cycles do not materially leak threads/memory.

### R13.3 Display/screenshot tests

- [x] Display reports `1280x800`.
- [x] Initial PNG is valid.
- [x] Initial PNG has exact dimensions.
- [x] ETag changes after visible update.
- [x] Conditional GET returns `304` for unchanged revision.
- [x] Screenshot unavailable before first complete frame.
- [x] Concurrent screenshots remain bounded.

### R13.4 Public API input tests

- [x] Move pointer to known coordinates and verify test-app result.
- [x] Left-click known control and verify state change.
- [x] Middle-click target.
- [x] Right-click target.
- [x] Double-click target and verify exactly two clicks.
- [x] Scroll vertically in both directions.
- [x] Scroll horizontally in both directions if supported.
- [x] Send individual key down/up and verify order.
- [x] Send chord and verify press/release ordering.
- [x] Type supported text and verify exact field contents.
- [x] Submit unsupported text and verify no partial mutation.

### R13.5 Public API clipboard tests

- [x] Set desktop clipboard through API.
- [x] Paste into test app and verify exact value.
- [x] Copy from test app.
- [x] Retrieve last-known clipboard snapshot through API.
- [x] Verify clipboard revision.
- [x] Verify clipboard timestamp.
- [x] Verify `clipboard_unavailable` before first inbound update.
- [x] Verify oversized input rejection.

### R13.6 Auth and abuse tests

- [x] Verify all `/v1/*` routes reject no token.
- [x] Verify all `/v1/*` routes reject wrong token.
- [x] Verify WebSocket rejects unauthenticated upgrades.
- [x] Verify token cannot be supplied through query string.
- [x] Verify oversized JSON body rejection.
- [x] Verify coordinate limit rejection.
- [x] Verify scroll limit rejection.
- [x] Verify queue saturation is explicit.
- [x] Verify reconnect rate limiting.
- [x] Verify secrets/payloads absent from captured logs.

### R13.7 Shutdown tests

- [x] Send SIGTERM to controller while idle.
- [x] Send SIGTERM with queued commands.
- [x] Confirm new commands rejected during shutdown.
- [x] Confirm worker connection closes.
- [x] Confirm worker thread joins.
- [x] Confirm process exits within bounded deadline.
- [x] Stop desktop and confirm child processes terminate.

Evidence:

```text
Integration commit: 9323b09dcd0f13dbe0576a599926dd8b13d263b1
Harness command: bash tests/integration/run.sh
Connection tests: real Compose/TigerVNC auth failure, fail-closed secret, disconnect, reconnect, stale-frame invalidation, repeated restart/resource bounds
Screenshot tests: 1280x800 PNG, coherent readiness, ETag/304, visible revision change, unavailable during reconnect, bounded concurrent encoding
Input tests: exact pointer/button/double-click/vertical-scroll counts, explicit horizontal rejection, key/chord ordering, exact text and atomic unsupported-text rejection
Clipboard tests: unavailable-before-first-update, API-to-desktop paste, desktop-to-API copy, revision/timestamp, oversized rejection
Auth/abuse tests: all protected routes, WebSocket/query-token rejection, body/coordinate/scroll/queue/reconnect bounds, log and diagnostic redaction
Shutdown tests: idle and queued SIGTERM, new-work rejection, worker connection close/thread join, bounded process exit, desktop child termination
Evidence document: docs/VNC_REMOTE_CONTROL_SERVER_R13_EVIDENCE_2026-08-05.md
R13 candidate run: 30973938130 (success)
Final assertion/API validation run: 30993609334 (success)
Temporary workflow cleanup commit: 039ac05828f75119b6177c36a91a85bc5c952bb0
Final documentation SHA and ordinary CI: validated after this checklist commit
```

---

## R14 — CI hardening and security policy

### R14.1 CI quality workflow expansion

- [ ] Ensure `.github/workflows/ci.yml` runs `cargo fmt --check`.
- [ ] Ensure Clippy runs all targets/features with warnings denied.
- [ ] Ensure all Rust tests run.
- [ ] Ensure rustdoc warnings are denied.
- [ ] Add ShellCheck.
- [ ] Add Actionlint.
- [ ] Add Dockerfile lint or documented equivalent.
- [ ] Add Compose config validation.
- [ ] Add `cargo deny check`.
- [ ] Cache dependencies without caching secrets.
- [ ] Cancel superseded branch runs safely.
- [ ] Add bounded workflow timeout.

### R14.2 Native safety jobs

- [ ] Add AddressSanitizer coverage for adapter tests where supported.
- [ ] Add UndefinedBehaviorSanitizer coverage where supported.
- [ ] Consider ThreadSanitizer for Rust-only shared-state tests.
- [ ] Document ThreadSanitizer/FFI limitations.
- [ ] Run Miri on compatible core code.
- [ ] Treat sanitizer findings as release blockers.

### R14.3 Dependency and image security

- [ ] Run Rust advisory checks.
- [ ] Run license/source policy checks.
- [ ] Scan controller image.
- [ ] Scan desktop image.
- [ ] Define blocked severity levels.
- [ ] Define exceptions process.
- [ ] Generate SBOM or equivalent inventory.
- [ ] Record LibVNCClient version in build metadata.
- [ ] Verify no secrets introduced in repository history by this implementation.

### R14.4 Integration CI

- [ ] Run Compose smoke tests on Linux.
- [ ] Run real VNC integration suite.
- [ ] Run public API E2E suite.
- [ ] Upload sanitized logs and test reports on failure.
- [ ] Do not upload screenshots unless fixtures are guaranteed non-sensitive.
- [ ] Set bounded workflow timeout.

Evidence:

```text
CI hardening commit:
Quality gates:
Native safety jobs:
Security scans:
Integration CI:
CI run:
```

---

## R15 — README, operator docs, and API docs

### R15.1 README/operator docs

- [ ] Explain product boundary.
- [ ] Include architecture diagram.
- [ ] List prerequisites.
- [ ] Document secret generation.
- [ ] Document local build/startup.
- [ ] Document authenticated API examples without real secrets.
- [ ] Document screenshot usage.
- [ ] Document WebSocket usage.
- [ ] Document production reverse-proxy/TLS expectations.
- [ ] Document disposable mode.
- [ ] Document persistent mode.
- [ ] Document loopback-only debug VNC.
- [ ] Document shutdown behavior.
- [ ] Document recovery behavior.
- [ ] Document known text limitations.
- [ ] Document known clipboard encoding limitations.
- [ ] Document resource limits/tuning.
- [ ] Document troubleshooting for desktop startup.
- [ ] Document troubleshooting for VNC auth.
- [ ] Document troubleshooting for controller connection.
- [ ] Document troubleshooting for framebuffer readiness.

### R15.2 API documentation

- [ ] Add OpenAPI document for HTTP routes.
- [ ] Document bearer authentication.
- [ ] Document every request schema.
- [ ] Document every response schema.
- [ ] Document error codes/statuses.
- [ ] Document asynchronous `202` semantics.
- [ ] Document WebSocket event envelope separately if needed.
- [ ] Add tested curl examples.
- [ ] Ensure docs match actual behavior.

Evidence:

```text
Docs commit:
OpenAPI validation:
Curl example tests:
CI run:
```

---

## R16 — Final v0.1 acceptance gate

Do not mark v0.1 complete until every item below has exact evidence on the same release-candidate SHA.

### R16.1 Architecture and isolation

- [ ] Exactly one desktop session is implemented.
- [ ] Desktop and controller are separate containers.
- [ ] TigerVNC reachable only on private network in production Compose.
- [ ] Optional raw VNC debug access binds only to `127.0.0.1`.
- [ ] Desktop runs non-root.
- [ ] Controller runs non-root.
- [ ] Raw LibVNCClient state confined to adapter and one worker thread.

### R16.2 Observation

- [ ] Controller receives complete framebuffer.
- [ ] Display metadata is correct.
- [ ] PNG screenshots are coherent.
- [ ] Screenshot ETags work.
- [ ] Conditional requests work.
- [ ] Old framebuffer data invalidated on reconnect.
- [ ] Revision events delivered over authenticated WebSocket.

### R16.3 Control

- [ ] Pointer move works.
- [ ] Button down/up works.
- [ ] Left click works.
- [ ] Middle click works.
- [ ] Right click works.
- [ ] Double-click works atomically.
- [ ] Vertical scrolling works.
- [ ] Horizontal scrolling works and is tested, or is removed from v0.1 API/spec.
- [ ] Key down/up works.
- [ ] Chords press/release in required order.
- [ ] Supported text enters exactly.
- [ ] Unsupported text fails before partial input.
- [ ] Outbound clipboard works as documented.
- [ ] Inbound clipboard works as documented.

### R16.4 Reliability

- [ ] Automatic reconnect works after desktop restart.
- [ ] Authentication failure visible and backoff-safe.
- [ ] Worker queue saturation visible.
- [ ] Requests are time-bounded.
- [ ] Shutdown is time-bounded.
- [ ] Slow WebSocket clients cannot consume unbounded memory.
- [ ] Worker failure causes readiness failure.
- [ ] No command silently dropped.

### R16.5 Security

- [ ] API bearer token required on all `/v1/*` routes.
- [ ] VNC authentication mandatory.
- [ ] Tokens/passwords come from secrets, not image layers.
- [ ] No bearer token appears in logs.
- [ ] No VNC password appears in logs.
- [ ] No typed text appears in logs.
- [ ] No clipboard content appears in logs.
- [ ] No framebuffer content appears in logs.
- [ ] No public raw VNC binding exists in production configuration.
- [ ] Container capabilities/resource limits applied.
- [ ] Dependency/image scans satisfy release policy.

### R16.6 Quality evidence

- [ ] Formatting passes.
- [ ] Clippy passes with warnings denied.
- [ ] Unit tests pass.
- [ ] Adapter safety tests pass.
- [ ] Desktop smoke passes.
- [ ] Compose smoke passes.
- [ ] Integration tests pass.
- [ ] End-to-end tests pass.
- [ ] Sanitizer jobs pass.
- [ ] Security scans pass.
- [ ] README matches behavior.
- [ ] API docs match behavior.
- [ ] Exact release commit SHA is recorded.

### R16.7 Final evidence record

```text
Release candidate commit:

Toolchain versions:
- Rust:
- Debian base digest:
- TigerVNC:
- LibVNCClient:
- Docker:

Validation commands:

Results:
- Formatting:
- Clippy:
- Unit tests:
- Desktop smoke:
- Adapter safety tests:
- Compose smoke:
- Integration tests:
- End-to-end tests:
- Sanitizers:
- Security scans:

GitHub Actions:
- CI run:
- Quality job:
- Desktop job:
- Integration job:
- Security job:

Known v0.1 limitations:

Release decision:
```

---

## Post-v0.1 backlog — do not pull into this critical path

- [ ] Dirty-rectangle image streaming.
- [ ] JPEG/WebP live frame streaming.
- [ ] noVNC browser viewer.
- [ ] Human versus automation control leases.
- [ ] Multiple desktop sessions.
- [ ] Per-session container lifecycle API.
- [ ] Multi-user authentication and authorization.
- [ ] AT-SPI accessibility integration.
- [ ] OCR helpers.
- [ ] Computer-vision targeting.
- [ ] Playwright integration.
- [ ] Natural-language or AI task planning.
- [ ] Dynamic screen resizing.
- [ ] Connections to arbitrary external VNC servers.
