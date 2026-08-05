# VNC Remote Control Server — Rebased Implementation TODO

Date: 2026-08-03
Repository: `ekkus93/vnc-remote-control-server`
Starting point: `master` at reviewed commit `da1d6d636c8ded87471ad7bc0ac493f1ef39e98a`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_REBASE_SPEC_2026-08-03.md`

---

## Status at creation

The repository was not v0.1-complete when this TODO was created.

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

The immediate next move was to repair the desktop smoke harness and prove the exact SHA green before advancing into native adapter work.

Do not mark a task complete merely because a type, stub, or placeholder exists. Mark completion only when the implementation, tests, evidence, or an explicit accepted scope resolution exists.

## Completion reconciliation — 2026-08-05

R0 through R16 are complete for the accepted v0.1 product boundary. The final release candidate is `dd3b14917ad5e239573d584238ff67ded8138203`; permanent CI run `31029834071` and Release Gates run `31029833868` both completed successfully on that exact SHA. The authoritative final record is [`docs/VNC_REMOTE_CONTROL_SERVER_R16_EVIDENCE_2026-08-05.md`](VNC_REMOTE_CONTROL_SERVER_R16_EVIDENCE_2026-08-05.md).

This reconciliation closes stale R0–R9 boxes using the retained milestone evidence and final same-SHA acceptance evidence. It records the following deliberate resolutions instead of pretending that a different implementation exists:

- a reviewed project-owned C shim was selected instead of bindgen-generated Rust structure bindings;
- horizontal scrolling remains explicitly unsupported and fails closed in v0.1;
- the destructive desktop-global `CTRL_LEFT + ALT_LEFT + T` fixture was replaced by deterministic `CTRL_LEFT + SHIFT_LEFT + F6` ordering proof;
- direct Unicode key entry remains outside the verified v0.1 contract, while UTF-8 clipboard transport is supported;
- v0.1 FFI failure evidence uses the single RAII cleanup path, live authentication/transport failures, sanitizers, and Miri rather than retaining synthetic per-stage production failure switches.

The post-v0.1 backlog remains intentionally unchecked.

---

## R0 — Repair current red CI and rebaseline evidence

### R0.1 Fix wrong-password VNC smoke probe

- [x] Inspect `tests/desktop/run.sh` `run_viewer_probe` behavior.
- [x] Preserve captured viewer logs for both success and failure cases.
- [x] For wrong-password probe, require authentication-failure text such as `Authentication failure` or `Authentication failed`.
- [x] For wrong-password probe, reject evidence of an authenticated framebuffer/session.
- [x] Stop treating `timeout 124` alone as proof that wrong-password authentication succeeded.
- [x] For correct-password probe, require positive connection/authentication evidence.
- [x] For correct-password probe, reject any authentication-failure text.
- [x] Keep both probes bounded by timeout.
- [x] Ensure failure messages print the relevant viewer log.

### R0.2 Re-run desktop smoke locally or in CI-equivalent environment

- [x] Run `tests/desktop/run.sh` from a clean Docker state.
- [x] Confirm image builds from the pinned Debian base digest.
- [x] Confirm wrong-password probe fails closed and is diagnosable.
- [x] Confirm correct-password probe reaches a persistent authenticated session.
- [x] Confirm missing secret fails startup closed.
- [x] Confirm runtime password is absent from image history and logs.
- [x] Confirm desktop runs as UID `10001`.
- [x] Confirm display dimensions are `1280x800`.
- [x] Confirm test app state file is valid.
- [x] Confirm shutdown behavior is deterministic.

### R0.3 Re-run repository quality gates

- [x] Run `cargo fmt --all --check`.
- [x] Run `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`.
- [x] Run `cargo test --locked --workspace --all-features`.
- [x] Run `cargo doc --locked --workspace --all-features --no-deps` with `RUSTDOCFLAGS=-Dwarnings`.
- [x] Run `python -m compileall -q tools/ci_status tests desktop/test-app`.
- [x] Run `python -m unittest discover -s tests -p 'test_*.py' -v`.
- [x] Run shell syntax checks for first-party shell scripts.

### R0.4 Record rebaseline evidence

- [x] Update this file with exact validation commands.
- [x] Record the new commit SHA after the repair.
- [x] Record the GitHub Actions run ID and job IDs.
- [x] Confirm issue #1 reports `completed` / `success` for the exact SHA.
- [x] Do not proceed to R2/R3 until R0 is green.

Evidence:

```text
Initial repair commit: d620f68cc840f8f83302e9f4ee73a9490bd604d2
Final post-auth evidence repair: 0f268296402b24be2b6c798e8c6d0e300fc85d2d
Validation: tests/desktop/run.sh plus the repository quality commands listed above
CI run: 30874471061
CI conclusion: success
Desktop job: 91883022815 — success
Quality job: 91883022835 — success
Issue #1: completed / success through the permanent CI-status publisher
Final superseding evidence: docs/VNC_REMOTE_CONTROL_SERVER_R16_EVIDENCE_2026-08-05.md
Known limitations after R0: implementation milestones R1-R16 remained at that point; all were subsequently completed
```

---

## R1 — Documentation rebaseline

### R1.1 README accuracy

- [x] Update README status so it no longer says the desktop image is a future milestone.
- [x] Describe the current implemented baseline accurately.
- [x] Describe explicit placeholders accurately while they existed; final README now describes the completed v0.1 implementation.
- [x] Link to the rebased spec and TODO.
- [x] Keep product boundary text aligned with v0.1 scope.
- [x] Keep warning that raw VNC must not be exposed publicly.

### R1.2 TODO/spec linkage

- [x] Add a short note to the original `docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md` pointing to this rebased TODO, or clearly document which file is now authoritative.
- [x] Avoid conflicting milestone claims across documents.
- [x] Preserve the original TODO for historical context unless deliberately superseded.

### R1.3 Operator warnings

- [x] Document that production raw VNC host publishing is prohibited.
- [x] Document that debug raw VNC must be loopback-only.
- [x] Document that API and VNC secrets must come from secret files by default.
- [x] Document that typed text, clipboard content, passwords, bearer tokens, and screenshots must not be logged.

Evidence:

```text
Docs reviewed: README.md, docs/OPERATOR_GUIDE.md, deploy/README.md, original and rebased spec/TODO files
Documentation acceptance: R15 and R16
R15 evidence: docs/VNC_REMOTE_CONTROL_SERVER_R15_EVIDENCE_2026-08-05.md
Final acceptance documentation commit: bb588632e0a4ece42a02e4cff0a7e39299cbf5e9
Release candidate: dd3b14917ad5e239573d584238ff67ded8138203
CI run: 31029834071 — success
Release Gates run: 31029833868 — success
```

---

## R2 — Strengthen Rust/core model before native work

### R2.1 Explicit keyboard API serialization

- [x] Decide the public JSON representation for symbolic keys.
- [x] Implement custom serialization/deserialization or wrapper request DTOs so API shape is stable.
- [x] Ensure printable single-character keys are represented deliberately.
- [x] Ensure raw numeric keysyms are never accepted by the public API.
- [x] Add tests for every required symbolic key.
- [x] Add tests for printable ASCII chord keys.
- [x] Add tests for unknown key names.
- [x] Add tests showing derived Serde enum shape is not accidentally exposed.

### R2.2 Text support matrix

- [x] Document exact supported v0.1 text range.
- [x] Confirm `\n`, `\r`, `\t`, and printable ASCII handling is intentional.
- [x] Add fixtures for boundary characters.
- [x] Add unsupported Unicode fixtures.
- [x] Add oversized text fixtures.
- [x] Add test proving unsupported text fails before partial input.

### R2.3 Clipboard validation policy

- [x] Confirm embedded NUL policy is rejection.
- [x] Add explicit doc comment or API schema note for embedded NUL behavior.
- [x] Add tests for byte limit at boundary.
- [x] Add tests for invalid or unsupported clipboard payloads once HTTP body parsing exists.

### R2.4 Framebuffer domain tests

- [x] Add known-size RGBA snapshot fixtures.
- [x] Add edge rectangle tests for every boundary.
- [x] Add malformed rectangle tests.
- [x] Add overflow rectangle tests.
- [x] Add reconnect invalidation model tests once framebuffer store exists.

Evidence:

```text
Initial engineering baseline: ba7b18a5abfa497ac82a3d9d866bc983209bbe16
Core and API contract coverage: crates/remote-desktop-core plus controller request DTO tests
Text/clipboard live evidence: docs/evidence/R9_WORKER_TEXT_CLIPBOARD_CANDIDATE_2026-08-04.md
Framebuffer and reconnect evidence: R7, R13, and R16 evidence records
Final release candidate: dd3b14917ad5e239573d584238ff67ded8138203
Final CI run: 31029834071 — success
```

---

## R3 — Native build and binding strategy

### R3.1 Native package support

- [x] Add required native development packages to the controller build image or documented dev environment.
- [x] Include `libvncserver-dev`/LibVNCClient headers as appropriate.
- [x] Include C compiler and `pkg-config` where needed.
- [x] Ensure missing native dependencies produce actionable build errors.
- [x] Ensure release builds do not depend on undeclared host libraries.

### R3.2 Binding strategy decision

- [x] Decide generated bindings versus reviewed checked-in bindings: use a reviewed project-owned C shim with an opaque handle.
- [x] Document the decision in `docs/LIBVNCCLIENT_BINDING_DECISION.md` and module-level safety documentation.
- [x] Resolve the generated-`wrapper.h` branch as not applicable; `native/vnc_shim.h` defines the deliberately narrow project ABI.
- [x] Resolve bindgen generation as not applicable; Rust never reproduces the `rfbClient` layout.
- [x] Resolve bindgen allowlists as not applicable; the C shim exports only reviewed required operations.
- [x] Track shim sources, headers, relevant environment, and `pkg-config` changes through `build.rs` rerun directives.
- [x] Commit the reviewed minimal C shim and document its regeneration/review policy.
- [x] Add native dependency version capture.

### R3.3 Adapter build tests

- [x] Add a build-only adapter test that links LibVNCClient.
- [x] Add CI job coverage for adapter build environment.
- [x] Ensure `cargo test --workspace --all-features` works in the native-enabled environment.
- [x] Ensure local missing-dependency failure is clear.

Evidence:

```text
Binding strategy: reviewed project-owned C shim with opaque vrc_client handle
Decision record: docs/LIBVNCCLIENT_BINDING_DECISION.md
Native packages: build-essential, libvncserver-dev, pkg-config
Initial verified LibVNCClient: 0.9.14 on Ubuntu native runner
Release-image LibVNCClient: 0.9.15+dfsg-1+deb13u2
Initial exact-green SHA: 6bef7b854a845590b2ff52662ae1c70caeddf91b
Initial CI run: 30881879425 — success
Evidence: docs/VNC_REMOTE_CONTROL_SERVER_R3_R5_EVIDENCE_2026-08-03.md
Final release validation: CI 31029834071 and Release Gates 31029833868 — success
```

---

## R4 — Minimal LibVNCClient connection spike

### R4.1 Safe allocation and credentials

- [x] Allocate an `rfbClient` safely behind the opaque project-owned shim.
- [x] Define ownership for the native client allocation.
- [x] Configure credential callback state.
- [x] Read the mounted VNC password without logging it.
- [x] Ensure callback context lives long enough for the native client lifetime.

### R4.2 Connect to real desktop container

- [x] Start the real desktop container.
- [x] Connect to TigerVNC on the private/expected endpoint.
- [x] Authenticate with the mounted VNC password.
- [x] Receive server metadata.
- [x] Record protocol version and dimensions.

### R4.3 Frame/input/clipboard spike

- [x] Allocate framebuffer through the supported callback path.
- [x] Process server messages until a complete frame arrives.
- [x] Capture proof of initial framebuffer dimensions.
- [x] Send one pointer move.
- [x] Send one key press and release.
- [x] Send one clipboard value.
- [x] Confirm deterministic test app observed pointer/key input.

### R4.4 Cleanup spike

- [x] Disconnect cleanly.
- [x] Free all native resources.
- [x] Verify cleanup completes without crash or hang.
- [x] Promote the spike path into production modules and retained tests.

Evidence:

```text
Spike command: tests/native/run.sh through the permanent desktop/native CI job
Observed proof: proof_ready=1; protocol_major=3; dimensions=1280x800; revision=1; bytes=4096000
Pointer proof: deterministic desktop test application observation
Key proof: F5 down/up observation
Clipboard proof: outbound clipboard observed while connected
Cleanup proof: bounded successful exit plus wrong-password and unreachable-port failure probes
Native baseline: LibVNCClient 0.9.14
Evidence: docs/VNC_REMOTE_CONTROL_SERVER_R3_R5_EVIDENCE_2026-08-03.md
Final production proof: R13 and R16 evidence records
```

---

## R5 — FFI safety contract and RAII adapter

### R5.1 Module-level safety contract

- [x] Write adapter safety invariants in module-level documentation.
- [x] State raw pointer ownership rules.
- [x] State callback lifetime rules.
- [x] State panic containment rules.
- [x] State buffer validation rules.
- [x] State cleanup ordering.
- [x] State redaction rules.

### R5.2 RAII wrapper

- [x] Implement private RAII wrapper for `rfbClient*` through the opaque shim handle.
- [x] Prevent raw pointers from crossing crate boundaries.
- [x] Guarantee one owner for every raw allocation.
- [x] Guard cleanup against double invocation.
- [x] Define cleanup behavior for partial initialization failures.
- [x] Resolve failure-stage coverage for v0.1 with one RAII destruction path, live authentication and transport failures, ASan, and final native-safety gates; no synthetic production failure switch or ignored failure was retained.

### R5.3 Callback safety

- [x] Store callback context in stable memory for full C-client lifetime.
- [x] Prevent Rust panics from crossing C callbacks by keeping callbacks within the C shim.
- [x] Validate callback dimensions before memory access.
- [x] Validate rectangle coordinates before memory access.
- [x] Use checked arithmetic for all buffer calculations.
- [x] Convert native failures into typed adapter errors.
- [x] Redact secrets and payload contents from adapter error formatting.

Evidence:

```text
Adapter baseline SHA: 6bef7b854a845590b2ff52662ae1c70caeddf91b
Safety docs: crates/libvnc-adapter/src/lib.rs and docs/LIBVNCCLIENT_BINDING_DECISION.md
Failure evidence: wrong-password authentication failure, unreachable transport failure, partial-init RAII cleanup path, bounded shutdown
Native safety: AddressSanitizer; Rust-only ThreadSanitizer; Miri on the pure-Rust core
Initial evidence: docs/VNC_REMOTE_CONTROL_SERVER_R3_R5_EVIDENCE_2026-08-03.md
Final Release Gates: run 31029833868; native-safety job 92387653418 — success
Accepted boundary: distribution LibVNCClient is not rebuilt with sanitizers, as recorded in R16 limitations
```

---

## R6 — Production worker lifecycle

### R6.1 Worker ownership

- [x] Create worker type that owns the adapter connection.
- [x] Spawn exactly one native thread for the configured session.
- [x] Prevent Axum/Tokio tasks from directly touching adapter state.
- [x] Use bounded command channel.
- [x] Use bounded event/broadcast mechanism.
- [x] Implement worker startup acknowledgement.
- [x] Implement command completion or enqueue acknowledgement semantics.
- [x] Implement worker shutdown and thread join.
- [x] Treat unexpected worker exit as fatal readiness failure.

### R6.2 Connection state machine

- [x] Implement every public state from the spec.
- [x] Validate allowed transitions.
- [x] Publish transition events.
- [x] Track connection timestamps.
- [x] Track reconnect attempts.
- [x] Distinguish authentication, configuration, transport, timeout, and protocol failures.
- [x] Ensure authentication failure does not retry rapidly.
- [x] Ensure configuration failure does not masquerade as transient disconnect.

### R6.3 Reconnection

- [x] Implement exponential backoff.
- [x] Add bounded jitter.
- [x] Add configurable min and max delays.
- [x] Reset backoff after stable connection.
- [x] Implement rate-limited manual reconnect.
- [x] Invalidate framebuffer on disconnect.
- [x] Clear pressed-key and button bookkeeping on disconnect.
- [x] Request full framebuffer update after reconnect.
- [x] Require complete frame before readiness returns.
- [x] Test repeated desktop restart cycles.

### R6.4 Stall detection

- [x] Track last successful server message time.
- [x] Define idle desktop versus stalled connection.
- [x] Use protocol-safe probes or refresh requests where needed.
- [x] Apply bounded stall timeout.
- [x] Transition visibly to degraded/reconnecting on confirmed stall.
- [x] Ensure requests do not wait indefinitely during stall.

Evidence:

```text
Worker integration history: 6997362414336b8ef727c1a5cbabdbb1bc1c4b94 and df911e883bff6e52a78b4ddbf00d9d73067ffcf1
Worker exact-green input SHA: 541529640b73235c570ef721bbb83191690783b1
Worker CI run: 30929517821 — success
Lifecycle/reconnect/shutdown proof: tests/integration/run.sh and docs/VNC_REMOTE_CONTROL_SERVER_R13_EVIDENCE_2026-08-05.md
Final release candidate: dd3b14917ad5e239573d584238ff67ded8138203
Final CI run: 31029834071 — success
```

---

## R7 — Framebuffer and screenshots

### R7.1 Canonical framebuffer store

- [x] Implement canonical RGBA8 storage.
- [x] Implement safe stride/allocation calculations.
- [x] Implement conversion from selected LibVNCClient pixel format.
- [x] Handle server dimension metadata safely.
- [x] Reject dimensions above configured memory limits.
- [x] Implement complete/incomplete state.
- [x] Implement monotonically increasing process-local revisions.
- [x] Track update timestamps.

### R7.2 Dirty rectangle updates

- [x] Validate every rectangle origin and extent.
- [x] Reject overflow in `x + width` and `y + height`.
- [x] Reject rectangles outside framebuffer.
- [x] Copy updates without out-of-bounds access.
- [x] Decide revision semantics.
- [x] Document revision semantics.
- [x] Test selected revision semantics.
- [x] Publish framebuffer update events only after coherent commit.

### R7.3 Snapshot consistency

- [x] Implement immutable framebuffer snapshots.
- [x] Ensure snapshot creation cannot observe partially copied rectangle.
- [x] Keep locks out of long PNG encoding work.
- [x] Return unavailable while no complete frame exists.
- [x] Return stale/incomplete state after disconnect rather than serving old pixels as current.

### R7.4 PNG support

- [x] Select maintained PNG encoder.
- [x] Encode RGBA8 snapshots.
- [x] Add bounded concurrent encode permits.
- [x] Add encode timeout handling.
- [x] Generate ETags from process instance and framebuffer revision.
- [x] Support `If-None-Match` and `304`.
- [x] Set correct `Content-Type`.
- [x] Set correct cache-control headers.
- [x] Test exact dimensions.
- [x] Test valid PNG structure.

### R7.5 Framebuffer safety tests

- [x] Add known pixel conversion fixtures.
- [x] Add edge rectangle tests at every boundary.
- [x] Add malformed/overflow rectangle tests.
- [x] Add concurrent update/snapshot stress tests.
- [x] Add reconnect invalidation tests.
- [x] Run native sanitizers on update paths where practical and document the distribution-library boundary.

Evidence:

```text
Canonical framebuffer exact-green SHA: 493a478b8ba3e1a5fb7086003f13c291478c8bbe
PNG exact-green SHA: a70f0b56c844c4bf9b6ac4cb18ee49f1fcc0ca63
PNG crate: png 0.18.1
Evidence: docs/VNC_REMOTE_CONTROL_SERVER_R7_WORKER_FRAMEBUFFER_EVIDENCE_2026-08-03.md
Dependency evidence: docs/VNC_REMOTE_CONTROL_SERVER_R7_PNG_LOCK_EVIDENCE_2026-08-03.md
Real screenshot/reconnect proof: docs/VNC_REMOTE_CONTROL_SERVER_R13_EVIDENCE_2026-08-05.md
Final same-SHA acceptance: CI 31029834071 and Release Gates 31029833868 — success
```

---

## R8 — Pointer, mouse, scrolling, and keyboard control

### R8.1 Pointer movement

- [x] Implement strict coordinate validation against current dimensions.
- [x] Reject movement while dimensions are unknown.
- [x] Send pointer movement with current button mask.
- [x] Do not silently clamp coordinates.
- [x] Test all four display edges.
- [x] Test out-of-range values.

### R8.2 Mouse buttons and clicks

- [x] Map left, middle, and right buttons to RFB masks.
- [x] Maintain full current mask, not only latest button.
- [x] Implement explicit button down and up.
- [x] Implement atomic click worker commands.
- [x] Implement atomic double-click worker commands.
- [x] Bound configurable double-click intervals.
- [x] Clear local button state on disconnect.
- [x] Add best-effort release behavior on partial command failure.

### R8.3 Scrolling

- [x] Verify TigerVNC vertical wheel mask behavior.
- [x] Investigate TigerVNC horizontal wheel behavior and do not claim unverified support.
- [x] Remove horizontal scrolling from the supported v0.1 contract; nonzero horizontal requests fail explicitly.
- [x] Convert signed vertical deltas into bounded wheel steps.
- [x] Reject excessive step counts.
- [x] Keep scroll sequences atomic inside worker.
- [x] Confirm deterministic test app receives expected vertical direction/count.

### R8.4 Keyboard map

- [x] Implement required modifiers.
- [x] Implement navigation keys.
- [x] Implement editing keys.
- [x] Implement arrows.
- [x] Implement F1-F12.
- [x] Implement printable ASCII keys needed for chords.
- [x] Reject unknown symbolic names.
- [x] Keep raw numeric keysyms out of public API.

### R8.5 Key state and chords

- [x] Implement explicit key down and up.
- [x] Track locally pressed keys.
- [x] Implement chord press order.
- [x] Implement reverse release order.
- [x] Bound chord length.
- [x] Prevent duplicate modifier state corruption.
- [x] Best-effort release keys after partial failure.
- [x] Clear key state on disconnect and shutdown.
- [x] Replace the desktop-global `CTRL_LEFT + ALT_LEFT + T` acceptance fixture with deterministic `CTRL_LEFT + SHIFT_LEFT + F6` end-to-end ordering proof.

Evidence:

```text
Implementation history: 6997362414336b8ef727c1a5cbabdbb1bc1c4b94 through 541529640b73235c570ef721bbb83191690783b1
Pointer/mouse/scroll/keyboard proof: tests/worker-e2e/run.sh
Deterministic chord: CTRL_LEFT + SHIFT_LEFT + F6 press order, reverse release order
Horizontal behavior: explicitly unsupported and rejected in v0.1
Evidence: docs/evidence/R8_WORKER_INTEGRATION_CANDIDATE_2026-08-04.md
Exact-green CI run: 30929517821
Quality job: 92060416112 — success
Desktop/native/E2E job: 92060416024 — success
Final public API proof: R13 and R16 evidence records
```

---

## R9 — Text and clipboard correctness

### R9.1 Text input

- [x] Define exact v0.1 supported ASCII range.
- [x] Implement preflight validation for complete string.
- [x] Ensure unsupported characters fail before any character is sent.
- [x] Map supported characters to modifier/keysym sequences.
- [x] Preserve exact character order.
- [x] Bound text input bytes.
- [x] Return accepted character count and strategy.
- [x] Never log typed text.
- [x] Test supported text through deterministic app.
- [x] Test unsupported text produces no partial mutation.

### R9.2 Unicode boundary resolution

- [x] Test a representative non-ASCII value (`U+2603`) through the live TigerVNC worker path and prove atomic rejection.
- [x] Keep characters outside the verified ASCII range, including outside Latin-1, explicitly unsupported for direct key entry in v0.1.
- [x] Document the actual interoperability boundary in the R9 evidence record and operator/API documentation.
- [x] Add only verified direct key-entry support; no unverified Unicode keysym path was added.
- [x] Keep unsupported characters explicit and fail before native mutation.
- [x] Use the clipboard as the verified bounded UTF-8 transport; direct clipboard-paste text entry remains outside v0.1.

### R9.3 Outbound clipboard

- [x] Implement UTF-8 HTTP validation.
- [x] Enforce clipboard byte limit.
- [x] Reject embedded NUL unless policy is deliberately changed.
- [x] Send clipboard content through LibVNCClient.
- [x] Return success only for accepted send/enqueue operations.
- [x] Never log clipboard contents.
- [x] Test API set clipboard and test app paste exact expected text.
- [x] Test oversized clipboard rejection.

### R9.4 Inbound clipboard

- [x] Capture server clipboard callbacks.
- [x] Decode according to verified TigerVNC/RFB behavior.
- [x] Reject or visibly report invalid encoding.
- [x] Store text, revision, and timestamp.
- [x] Return `clipboard_unavailable` before first callback.
- [x] Publish clipboard revision events without text.
- [x] Test app copy -> API receives expected snapshot.
- [x] Test clipboard revision increments predictably.
- [x] Verify clipboard content absent from logs/metrics/events.

Evidence:

```text
Worker implementation: d35d15d06505891385c9d947c6345d8e07022a51
Exact error-taxonomy/final R9 SHA: c02425252c852481f1d810133368b142ed14797e
Text fixtures: printable ASCII plus tab/CR/LF; live exact text "worker text 123"; U+2603 atomic rejection
Clipboard fixtures: worker-to-desktop outbound value and desktop-to-worker inbound snapshot/revision
Encoding finding: direct key entry remains ASCII-only; clipboard is the verified UTF-8 transport; invalid inbound UTF-8 fails visibly
Evidence: docs/evidence/R9_WORKER_TEXT_CLIPBOARD_CANDIDATE_2026-08-04.md
Exact-green CI run: 30933078815
Quality job: 92072327484 — success
Desktop/native/E2E job: 92072327606 — success
Final public API proof: R13 and R16 evidence records
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

- [x] Ensure `.github/workflows/ci.yml` runs `cargo fmt --check`.
- [x] Ensure Clippy runs all targets/features with warnings denied.
- [x] Ensure all Rust tests run.
- [x] Ensure rustdoc warnings are denied.
- [x] Add ShellCheck.
- [x] Add Actionlint.
- [x] Add Dockerfile lint or documented equivalent.
- [x] Add Compose config validation.
- [x] Add `cargo deny check`.
- [x] Cache dependencies without caching secrets.
- [x] Cancel superseded branch runs safely.
- [x] Add bounded workflow timeout.

### R14.2 Native safety jobs

- [x] Add AddressSanitizer coverage for adapter tests where supported.
- [x] Add UndefinedBehaviorSanitizer coverage where supported.
- [x] Consider ThreadSanitizer for Rust-only shared-state tests.
- [x] Document ThreadSanitizer/FFI limitations.
- [x] Run Miri on compatible core code.
- [x] Treat sanitizer findings as release blockers.

### R14.3 Dependency and image security

- [x] Run Rust advisory checks.
- [x] Run license/source policy checks.
- [x] Scan controller image.
- [x] Scan desktop image.
- [x] Define blocked severity levels.
- [x] Define exceptions process.
- [x] Generate SBOM or equivalent inventory.
- [x] Record LibVNCClient version in build metadata.
- [x] Verify no secrets introduced in repository history by this implementation.

### R14.4 Integration CI

- [x] Run Compose smoke tests on Linux.
- [x] Run real VNC integration suite.
- [x] Run public API E2E suite.
- [x] Upload sanitized logs and test reports on failure.
- [x] Do not upload screenshots unless fixtures are guaranteed non-sensitive.
- [x] Set bounded workflow timeout.

Evidence:

```text
Release candidate: dd3b14917ad5e239573d584238ff67ded8138203
CI run 31029834071: success
Release Gates run 31029833868: success
Coverage: fmt, Clippy, tests, rustdoc, ShellCheck, actionlint, Docker/Compose checks, cargo-deny, Gitleaks history, ASan, TSan, Miri, Trivy exact VEX, CycloneDX SBOMs, and real VNC/HTTP/Compose E2E
Policy: docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md
VEX revalidation: issue #7; expires 2026-09-04
```

---

## R15 — README, operator docs, and API docs

### R15.1 README/operator docs

- [x] Explain product boundary.
- [x] Include architecture diagram.
- [x] List prerequisites.
- [x] Document secret generation.
- [x] Document local build/startup.
- [x] Document authenticated API examples without real secrets.
- [x] Document screenshot usage.
- [x] Document WebSocket usage.
- [x] Document production reverse-proxy/TLS expectations.
- [x] Document disposable mode.
- [x] Document persistent mode.
- [x] Document loopback-only debug VNC.
- [x] Document shutdown behavior.
- [x] Document recovery behavior.
- [x] Document known text limitations.
- [x] Document known clipboard encoding limitations.
- [x] Document resource limits/tuning.
- [x] Document troubleshooting for desktop startup.
- [x] Document troubleshooting for VNC auth.
- [x] Document troubleshooting for controller connection.
- [x] Document troubleshooting for framebuffer readiness.

### R15.2 API documentation

- [x] Add OpenAPI document for HTTP routes.
- [x] Document bearer authentication.
- [x] Document every request schema.
- [x] Document every response schema.
- [x] Document error codes/statuses.
- [x] Document asynchronous `202` semantics.
- [x] Document WebSocket event envelope separately if needed.
- [x] Add tested curl examples.
- [x] Ensure docs match actual behavior.

Evidence:

```text
Operator guide commit: 8eb2b2eb832359e30be2b8072eca220ac13d3903
README/OpenAPI/curl-test commit: d913218f12bf91477f2306c15dbd281fb3f0ca54
Evidence record commit: 2c8bc8d6a898a248301c6db12921bb5753930e60
Evidence document: docs/VNC_REMOTE_CONTROL_SERVER_R15_EVIDENCE_2026-08-05.md
OpenAPI validation: python3 -m json.tool docs/openapi.json; tests.test_documentation_contract
Curl example tests: tests/http-e2e/run.sh against production controller and real TigerVNC
Focused validation: run 31009207323, job 92316720636, success
Clean-head CI: run 31009513801 on e55bf28d4dd90259b1c43f90135577393545b150, success
Quality job: 92317766142, success
Secured desktop/native job: 92317766230, success
CI artifact: ci-evidence-31009513801, id 8931824284
```

---

## R16 — Final v0.1 acceptance gate

Do not mark v0.1 complete until every item below has exact evidence on the same release-candidate SHA.

### R16.1 Architecture and isolation

- [x] Exactly one desktop session is implemented.
- [x] Desktop and controller are separate containers.
- [x] TigerVNC reachable only on private network in production Compose.
- [x] Optional raw VNC debug access binds only to `127.0.0.1`.
- [x] Desktop runs non-root.
- [x] Controller runs non-root.
- [x] Raw LibVNCClient state confined to adapter and one worker thread.

### R16.2 Observation

- [x] Controller receives complete framebuffer.
- [x] Display metadata is correct.
- [x] PNG screenshots are coherent.
- [x] Screenshot ETags work.
- [x] Conditional requests work.
- [x] Old framebuffer data invalidated on reconnect.
- [x] Revision events delivered over authenticated WebSocket.

### R16.3 Control

- [x] Pointer move works.
- [x] Button down/up works.
- [x] Left click works.
- [x] Middle click works.
- [x] Right click works.
- [x] Double-click works atomically.
- [x] Vertical scrolling works.
- [x] Nonzero horizontal scrolling is explicitly rejected and tested as unsupported in v0.1.
- [x] Key down/up works.
- [x] Chords press/release in required order.
- [x] Supported text enters exactly.
- [x] Unsupported text fails before partial input.
- [x] Outbound clipboard works as documented.
- [x] Inbound clipboard works as documented.

### R16.4 Reliability

- [x] Automatic reconnect works after desktop restart.
- [x] Authentication failure visible and backoff-safe.
- [x] Worker queue saturation visible.
- [x] Requests are time-bounded.
- [x] Shutdown is time-bounded.
- [x] Slow WebSocket clients cannot consume unbounded memory.
- [x] Worker failure causes readiness failure.
- [x] No command silently dropped.

### R16.5 Security

- [x] API bearer token required on all `/v1/*` routes.
- [x] VNC authentication mandatory.
- [x] Tokens/passwords come from secrets, not image layers.
- [x] No bearer token appears in logs.
- [x] No VNC password appears in logs.
- [x] No typed text appears in logs.
- [x] No clipboard content appears in logs.
- [x] No framebuffer content appears in logs.
- [x] No public raw VNC binding exists in production configuration.
- [x] Container capabilities/resource limits applied.
- [x] Dependency/image scans satisfy release policy.

### R16.6 Quality evidence

- [x] Formatting passes.
- [x] Clippy passes with warnings denied.
- [x] Unit tests pass.
- [x] Adapter safety tests pass.
- [x] Desktop smoke passes.
- [x] Compose smoke passes.
- [x] Integration tests pass.
- [x] End-to-end tests pass.
- [x] Sanitizer jobs pass.
- [x] Security scans pass.
- [x] README matches behavior.
- [x] API docs match behavior.
- [x] Exact release commit SHA is recorded.

### R16.7 Final evidence record

```text
Release candidate commit: dd3b14917ad5e239573d584238ff67ded8138203

Toolchain: Rust 1.97.1; nightly 1.99.0-nightly; Debian 13.6 slim pinned digest; TigerVNC 1.15.0+dfsg-2.1~deb13u1; release LibVNCClient 0.9.15+dfsg-1+deb13u2; Docker 28.0.4

Validation:
- CI run 31029834071 — success
- Quality job 92387470896 — success
- Desktop/integration job 92387470858 — success
- Release Gates run 31029833868 — success
- Static/security job 92387653372 — success
- Image/SBOM job 92387653399 — success
- Native sanitizer/Miri job 92387653418 — success

Results: formatting, warning-denied Clippy, unit/rustdoc, desktop/native/Compose smoke, integration/E2E, ASan, TSan, Miri, cargo-deny, Gitleaks history, Trivy exact VEX, and SBOM gates all passed.

Known limitations: one project-owned desktop; no arbitrary VNC targets, multi-user auth, noVNC, OCR, accessibility automation, Playwright, or AI planning; reverse proxy required for TLS beyond localhost; horizontal scroll unsupported; typed text limited to tab/CR/LF and printable ASCII; inbound RFB clipboard must be valid UTF-8; distribution LibVNCClient is not sanitizer-rebuilt; VEX determinations expire 2026-09-04.

Release decision: ACCEPTED FOR v0.1
Evidence: docs/VNC_REMOTE_CONTROL_SERVER_R16_EVIDENCE_2026-08-05.md
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
