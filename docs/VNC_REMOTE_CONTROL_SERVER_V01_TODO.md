# VNC Remote Control Server v0.1 Implementation TODO

**Status:** Ready for implementation  
**Governing specification:** `docs/VNC_REMOTE_CONTROL_SERVER_V01_SPEC.md`  
**Target release:** v0.1  
**Last updated:** 2026-08-03

## 1. How to use this TODO

This checklist is the implementation contract for v0.1. Complete it in order unless a task explicitly says it may run in parallel.

Rules:

- Do not mark a task complete without code, tests, and evidence where applicable.
- Do not silently weaken the specification to make a test pass.
- Do not expose the raw VNC port publicly.
- Do not allow raw LibVNCClient pointers or callbacks outside the adapter crate.
- Do not add OCR, Playwright, AI planning, multi-session orchestration, or browser-based viewing to v0.1.
- Every failure path must be visible through a typed error, state transition, log, metric, or test assertion.
- Keep commits scoped to coherent milestones.
- Update this document with exact evidence as milestones are completed.

Recommended evidence format under each milestone:

```text
Evidence:
- Commit: <sha>
- Commands: <exact commands>
- Result: <test counts and notable output>
- Notes: <known limitations or follow-up>
```

## 2. Milestone map

| Milestone | Outcome |
|---|---|
| M0 | Repository and engineering baseline |
| M1 | Desktop container boots a secured XFCE/TigerVNC session |
| M2 | Rust workspace and domain model compile cleanly |
| M3 | LibVNCClient feasibility and FFI safety spike passes |
| M4 | Production VNC adapter and worker lifecycle work |
| M5 | Coherent framebuffer and screenshot pipeline work |
| M6 | Pointer, mouse, scrolling, and keyboard control work |
| M7 | Text and clipboard behavior work without silent corruption |
| M8 | Authenticated HTTP API is complete |
| M9 | WebSocket events, observability, and overload behavior work |
| M10 | Docker Compose deployment and persistence modes work |
| M11 | Real integration and end-to-end tests pass |
| M12 | CI, security hardening, and release documentation are complete |
| M13 | Final v0.1 acceptance gate passes |

---

# M0 — Repository and engineering baseline

## M0.1 Repository initialization

- [ ] Add a root `README.md` with a concise project description and current status.
- [ ] Add `.gitignore` for Rust, editor files, test artifacts, secret files, generated bindings, and local Compose overrides.
- [ ] Add `.editorconfig`.
- [ ] Add an explicit project license.
- [ ] Add `SECURITY.md` describing supported versions and private vulnerability reporting.
- [ ] Add `CONTRIBUTING.md` with local prerequisites and quality commands.
- [ ] Add `CODE_OF_CONDUCT.md` if the repository is intended for external contributors.
- [ ] Confirm default branch protection expectations and document them.

## M0.2 Toolchain policy

- [ ] Add `rust-toolchain.toml` with a pinned supported stable toolchain.
- [ ] Add `rustfmt.toml` only if non-default settings are justified.
- [ ] Add workspace lint policy to deny warnings in CI.
- [ ] Decide and document the minimum supported Rust version.
- [ ] Add `cargo-deny` configuration for advisories, bans, sources, and licenses.
- [ ] Add Dependabot or Renovate configuration for Cargo, Docker, and GitHub Actions.
- [ ] Pin GitHub Actions by full commit SHA for the release branch policy.

## M0.3 Development command surface

- [ ] Add a `Makefile`, `justfile`, or `mise` task file with stable commands:
  - [ ] `fmt`
  - [ ] `lint`
  - [ ] `test`
  - [ ] `build`
  - [ ] `compose-up`
  - [ ] `compose-down`
  - [ ] `integration-test`
  - [ ] `e2e-test`
  - [ ] `security-scan`
- [ ] Ensure all tasks fail on the first failing command.
- [ ] Ensure no task prints secrets.

## M0 exit gate

- [ ] A fresh clone has a documented toolchain and deterministic quality commands.
- [ ] Repository policy files are present.
- [ ] No secret or generated artifact is tracked accidentally.

---

# M1 — Secured Debian desktop container

## M1.1 Desktop image

- [ ] Create `desktop/Dockerfile` using the current supported Debian stable base.
- [ ] Pin the base image by digest for release builds.
- [ ] Install TigerVNC standalone server and required common components.
- [ ] Install XFCE with only required supporting packages.
- [ ] Install D-Bus/session dependencies.
- [ ] Install a terminal emulator.
- [ ] Install required fonts and X11 keyboard data.
- [ ] Install health-check utilities.
- [ ] Optionally install Chromium without making it an acceptance dependency.
- [ ] Remove apt caches and package lists from the final layer.
- [ ] Create a dedicated non-root desktop user with a fixed UID/GID strategy.
- [ ] Set a real writable home directory for that user.

## M1.2 VNC startup files

- [ ] Add `desktop/xstartup` to launch the XFCE session.
- [ ] Add `desktop/entrypoint.sh` with strict shell options.
- [ ] Validate required environment variables and secret-file paths.
- [ ] Read the VNC password from `/run/secrets/vnc_password` or configured equivalent.
- [ ] Reject missing or empty passwords.
- [ ] Create the TigerVNC password file at runtime with restrictive permissions.
- [ ] Never place the plaintext password in a process argument.
- [ ] Never echo the plaintext password to logs.
- [ ] Detect and handle stale PID, lock, and X socket files safely.
- [ ] Start `Xvnc` on display `:1`.
- [ ] Apply the default `1280x800` geometry and 24-bit depth.
- [ ] Require VNC authentication.
- [ ] Start the XFCE session.
- [ ] Forward SIGTERM and SIGINT to child processes.
- [ ] Reap child processes and exit nonzero on fatal startup failure.

## M1.3 Desktop health checks

- [ ] Add a liveness check that confirms the container supervisor is alive.
- [ ] Add a readiness check that confirms TCP `5901` is accepting connections.
- [ ] Confirm readiness does not succeed before `Xvnc` is usable.
- [ ] Add a bounded startup timeout.
- [ ] Ensure startup failure does not loop forever inside the container.

## M1.4 Deterministic graphical test application

- [ ] Choose a minimal implementation technology suitable for Debian CI.
- [ ] Add a test application with a fixed-size window and deterministic layout.
- [ ] Display current pointer coordinates.
- [ ] Record mouse button down/up events.
- [ ] Record vertical and horizontal scroll events.
- [ ] Record key down/up events.
- [ ] Provide a text input field.
- [ ] Provide copy and paste controls.
- [ ] Provide a visible counter or color change on accepted actions.
- [ ] Persist machine-readable event results to a local file or loopback-only endpoint.
- [ ] Reset test state deterministically between test cases.
- [ ] Launch the test app automatically in the test Compose profile.

## M1.5 Desktop image tests

- [ ] Build the desktop image in CI.
- [ ] Verify no VNC password is present in image history or layers.
- [ ] Verify desktop processes run as non-root.
- [ ] Verify `Xvnc` listens on `5901` inside the container.
- [ ] Verify a wrong password cannot authenticate.
- [ ] Verify a correct password can authenticate with a standard viewer or test client.
- [ ] Verify the framebuffer is `1280x800`.
- [ ] Verify clean shutdown leaves no misleading successful exit state after fatal failure.

## M1 exit gate

- [ ] The desktop container starts from a clean build with a mounted secret.
- [ ] A standard VNC client can authenticate and see XFCE plus the test app.
- [ ] The desktop runs as non-root.
- [ ] No unauthenticated fallback exists.

---

# M2 — Rust workspace and core model

## M2.1 Workspace creation

- [ ] Create the root Cargo workspace.
- [ ] Create `crates/remote-desktop-core`.
- [ ] Create `crates/libvnc-adapter`.
- [ ] Create `crates/controller-api`.
- [ ] Configure shared dependency versions at the workspace level where appropriate.
- [ ] Configure workspace lints.
- [ ] Commit `Cargo.lock`.

## M2.2 Core domain types

- [ ] Implement `DisplayInfo`.
- [ ] Implement validated coordinate types or validation helpers.
- [ ] Implement `MouseButton`.
- [ ] Implement key state and symbolic `KeyboardKey` types.
- [ ] Implement connection state enum.
- [ ] Implement framebuffer metadata and immutable snapshot types.
- [ ] Implement clipboard snapshot and revision types.
- [ ] Implement typed worker command and event enums.
- [ ] Implement public error taxonomy independent of HTTP status codes.
- [ ] Ensure domain types do not depend on Axum or FFI bindings.

## M2.3 Validation tests

- [ ] Test coordinate lower and upper boundaries.
- [ ] Test zero dimensions and unknown display state.
- [ ] Test invalid mouse button input deserialization.
- [ ] Test symbolic key parsing.
- [ ] Test chord length limits.
- [ ] Test text and clipboard byte limits.
- [ ] Test scroll bounds.
- [ ] Test checked framebuffer size calculations.
- [ ] Add property tests for rectangle containment and size arithmetic where useful.

## M2 exit gate

- [ ] Workspace builds with no warnings.
- [ ] Core tests pass.
- [ ] Core crate contains no unsafe code and no network or HTTP dependencies.

---

# M3 — LibVNCClient feasibility and FFI safety spike

This milestone must prove the native integration before the production API is built around it.

## M3.1 Select binding strategy

- [ ] Inspect current LibVNCClient headers and required symbols.
- [ ] Evaluate available Rust crates for maintenance status and client feature coverage.
- [ ] Record the evaluation in `docs/LIBVNCCLIENT_BINDING_DECISION.md`.
- [ ] Prefer a project-owned narrow wrapper around low-level bindings unless a maintained safe crate demonstrably covers all requirements.
- [ ] Select a reviewed LibVNCServer/LibVNCClient version.
- [ ] Record known security advisories and why the selected version is acceptable.
- [ ] Decide whether Linux packages, vendored source, or a source build supplies the library.
- [ ] Pin the selected source or package version.

## M3.2 Binding and build setup

- [ ] Add required native development packages to the controller build image.
- [ ] Add `wrapper.h` containing only required public headers.
- [ ] Add binding generation or reviewed checked-in bindings.
- [ ] Restrict generated allowlists to needed types, functions, and constants.
- [ ] Add rerun directives for header and build changes.
- [ ] Make missing native dependencies produce actionable build errors.
- [ ] Ensure release builds do not depend on an undeclared host library.

## M3.3 Minimal connection spike

- [ ] Allocate an `rfbClient` safely.
- [ ] Configure credential callbacks.
- [ ] Connect to the real desktop container.
- [ ] Authenticate with the mounted VNC password.
- [ ] Receive initial server metadata.
- [ ] Allocate a framebuffer through the supported callback path.
- [ ] Process server messages until a complete frame arrives.
- [ ] Send one pointer move.
- [ ] Send one key press and release.
- [ ] Send one clipboard value.
- [ ] Disconnect and free all resources.

## M3.4 FFI safety contract

- [ ] Write the adapter safety invariants in module-level documentation.
- [ ] Guarantee one owner for every raw allocation.
- [ ] Prevent raw pointers from crossing crate boundaries.
- [ ] Store callback context in stable memory for the full C-client lifetime.
- [ ] Prevent Rust panics from crossing C callback boundaries.
- [ ] Validate all callback dimensions and rectangle coordinates before memory access.
- [ ] Use checked arithmetic for all buffer calculations.
- [ ] Define cleanup ordering for partial initialization failures.
- [ ] Confirm cleanup is idempotent or guarded against double invocation.
- [ ] Add tests or a harness for failed initialization at each stage.

## M3.5 Spike evidence

- [ ] Record exact native and Rust dependency versions.
- [ ] Record the successful connect command and output.
- [ ] Capture proof of initial framebuffer dimensions.
- [ ] Capture proof that the test app observed pointer and key input.
- [ ] Capture proof that cleanup completes without crash or hang.
- [ ] Remove throwaway spike code or promote it into production modules with tests.

## M3 exit gate

- [ ] The selected binding strategy is documented.
- [ ] A Rust process connects to the real TigerVNC container and receives a frame.
- [ ] Pointer, key, and clipboard primitives have been demonstrated.
- [ ] No panic crosses FFI and no raw pointer escapes the adapter.

---

# M4 — Production VNC adapter and worker lifecycle

## M4.1 Adapter structure

- [ ] Implement a private RAII wrapper for `rfbClient*`.
- [ ] Implement credential callback state.
- [ ] Implement framebuffer allocation callback.
- [ ] Implement framebuffer update callback.
- [ ] Implement inbound clipboard callback.
- [ ] Implement connection initialization.
- [ ] Implement bounded message waiting and handling.
- [ ] Implement explicit disconnect and cleanup.
- [ ] Map native failures into typed adapter errors.
- [ ] Redact secrets and payload contents from error formatting.

## M4.2 Dedicated worker thread

- [ ] Create a worker type that owns the adapter connection.
- [ ] Spawn exactly one native thread for the configured session.
- [ ] Use a bounded command channel.
- [ ] Use a bounded event/broadcast mechanism.
- [ ] Prevent Axum and Tokio tasks from directly touching the adapter.
- [ ] Implement worker startup acknowledgement.
- [ ] Implement command completion or enqueue acknowledgement semantics.
- [ ] Implement worker shutdown and thread join.
- [ ] Treat unexpected worker exit as a fatal readiness failure.

## M4.3 Connection state machine

- [ ] Implement every state from the specification.
- [ ] Validate allowed transitions.
- [ ] Publish transition events.
- [ ] Track connection timestamps and reconnect attempts.
- [ ] Distinguish authentication, configuration, transport, timeout, and protocol failures.
- [ ] Ensure authentication failure does not retry rapidly.
- [ ] Ensure configuration failure does not masquerade as a transient disconnect.

## M4.4 Reconnection

- [ ] Implement exponential backoff.
- [ ] Add bounded jitter.
- [ ] Add configurable minimum and maximum delays.
- [ ] Reset backoff after a stable connection.
- [ ] Implement rate-limited manual reconnect.
- [ ] Invalidate the framebuffer at disconnect.
- [ ] Clear pressed-key and button bookkeeping.
- [ ] Request a full framebuffer update after reconnect.
- [ ] Require a complete frame before readiness returns.
- [ ] Test repeated server restart cycles.

## M4.5 Stall detection

- [ ] Track last successful server message time.
- [ ] Define the difference between an idle desktop and a stalled connection.
- [ ] Use protocol-safe probes or refresh requests where needed.
- [ ] Apply a bounded stall timeout.
- [ ] Transition visibly to degraded/reconnecting on a confirmed stall.
- [ ] Ensure requests do not wait indefinitely during a stall.

## M4 exit gate

- [ ] Worker owns all native state.
- [ ] Connection, disconnect, restart, authentication failure, and shutdown paths are deterministic.
- [ ] Queue and time limits are enforced.
- [ ] Reconnect produces a fresh complete framebuffer.

---

# M5 — Framebuffer and screenshots

## M5.1 Canonical framebuffer

- [ ] Implement canonical RGBA8 storage.
- [ ] Implement safe stride and allocation calculations.
- [ ] Implement conversion from the selected LibVNCClient pixel format.
- [ ] Handle server dimension metadata safely.
- [ ] Reject dimensions above configured memory limits.
- [ ] Implement complete/incomplete state.
- [ ] Implement monotonically increasing process-local revisions.
- [ ] Track update timestamps.

## M5.2 Dirty rectangle updates

- [ ] Validate every rectangle origin and extent.
- [ ] Reject overflow in `x + width` and `y + height`.
- [ ] Reject rectangles outside the framebuffer.
- [ ] Copy updates without out-of-bounds access.
- [ ] Decide whether one RFB message increments one revision or each committed rectangle increments it.
- [ ] Document and test the selected revision semantics.
- [ ] Publish framebuffer update events only after a coherent commit.

## M5.3 Snapshot consistency

- [ ] Implement immutable framebuffer snapshots.
- [ ] Ensure snapshot creation cannot observe a partially copied rectangle.
- [ ] Keep locks out of long PNG encoding work.
- [ ] Return unavailable while no complete frame exists.
- [ ] Return stale/incomplete state after disconnect rather than serving old pixels as current.

## M5.4 PNG endpoint support

- [ ] Select a maintained PNG encoder.
- [ ] Encode RGBA8 snapshots.
- [ ] Add bounded concurrent encode permits.
- [ ] Add encode timeout handling.
- [ ] Generate ETags from process instance and framebuffer revision.
- [ ] Support `If-None-Match` and `304`.
- [ ] Set correct `Content-Type` and cache-control headers.
- [ ] Test exact dimensions and valid PNG structure.

## M5.5 Framebuffer tests

- [ ] Add known pixel conversion fixtures.
- [ ] Add edge rectangles at every framebuffer boundary.
- [ ] Add malformed and overflow rectangle tests.
- [ ] Add concurrent update/snapshot stress tests.
- [ ] Add reconnect invalidation tests.
- [ ] Run native sanitizers on update paths where practical.

## M5 exit gate

- [ ] A coherent `1280x800` PNG is available after readiness.
- [ ] Malformed dimensions or rectangles cannot corrupt memory.
- [ ] Reconnect invalidates old framebuffer data until a full refresh arrives.

---

# M6 — Pointer, mouse, scrolling, and keyboard

## M6.1 Pointer movement

- [ ] Implement strict coordinate validation against current dimensions.
- [ ] Reject movement while dimensions are unknown.
- [ ] Send pointer movement with the current button mask.
- [ ] Do not silently clamp coordinates.
- [ ] Test all four display edges and out-of-range values.

## M6.2 Mouse button state

- [ ] Map left, middle, and right buttons to RFB masks.
- [ ] Maintain the full current mask, not only the latest button.
- [ ] Implement explicit button down and up.
- [ ] Implement atomic click worker commands.
- [ ] Implement atomic double-click worker commands.
- [ ] Bound configurable double-click intervals.
- [ ] Clear local button state on disconnect.
- [ ] Add best-effort release behavior on partial command failure.

## M6.3 Scrolling

- [ ] Verify TigerVNC vertical wheel mask behavior.
- [ ] Verify TigerVNC horizontal wheel mask behavior.
- [ ] Convert signed deltas into bounded wheel steps.
- [ ] Reject excessive step counts.
- [ ] Keep scroll sequences atomic inside the worker.
- [ ] Confirm the deterministic test app receives expected direction and count.

## M6.4 Symbolic keyboard map

- [ ] Implement required modifiers.
- [ ] Implement navigation keys.
- [ ] Implement editing keys.
- [ ] Implement arrow keys.
- [ ] Implement function keys F1–F12.
- [ ] Implement printable ASCII keys needed for chords.
- [ ] Reject unknown symbolic names.
- [ ] Keep raw numeric keysyms out of the public API.

## M6.5 Key state and chords

- [ ] Implement explicit key down and key up.
- [ ] Track locally pressed keys.
- [ ] Implement chord press order.
- [ ] Implement reverse release order.
- [ ] Bound chord length.
- [ ] Prevent duplicate modifier state from corrupting bookkeeping.
- [ ] Best-effort release keys after partial failure.
- [ ] Clear key state on disconnect and shutdown.
- [ ] Test `CTRL_LEFT + ALT_LEFT + T` end to end.

## M6 exit gate

- [ ] Test app records correct pointer, button, scroll, key, and chord events.
- [ ] Invalid input returns typed errors.
- [ ] No input sequence can interleave in a way that violates click, scroll, or chord atomicity.

---

# M7 — Text and clipboard correctness

## M7.1 Text support matrix

- [ ] Define the exact v0.1 supported ASCII range.
- [ ] Implement preflight validation for the complete string.
- [ ] Ensure unsupported characters fail before any character is sent.
- [ ] Map supported characters to required modifier and keysym sequences.
- [ ] Preserve exact character order.
- [ ] Bound text input bytes.
- [ ] Return accepted character count and strategy.
- [ ] Never log typed text.

## M7.2 Unicode investigation

- [ ] Test TigerVNC Unicode keysym support with representative characters.
- [ ] Test characters outside Latin-1.
- [ ] Document actual interoperability findings.
- [ ] Add only verified Unicode support.
- [ ] Keep unsupported characters explicit rather than silently substituting.
- [ ] Decide whether clipboard paste will be a future explicit strategy.

## M7.3 Outbound clipboard

- [ ] Implement UTF-8 HTTP validation.
- [ ] Enforce the clipboard byte limit.
- [ ] Define and test embedded NUL behavior.
- [ ] Send clipboard content through LibVNCClient.
- [ ] Return success only for accepted send operations.
- [ ] Never log clipboard contents.

## M7.4 Inbound clipboard

- [ ] Capture server clipboard callbacks.
- [ ] Decode according to verified TigerVNC/RFB behavior.
- [ ] Reject or visibly report invalid encoding.
- [ ] Store text, revision, and timestamp.
- [ ] Return `clipboard_unavailable` before the first callback.
- [ ] Publish clipboard revision events without including clipboard text.

## M7.5 Clipboard integration tests

- [ ] API sets clipboard and test app pastes exact expected text.
- [ ] Test app copies text and API receives the expected snapshot.
- [ ] Oversized clipboard input is rejected.
- [ ] Invalid input is rejected without partial state changes.
- [ ] Clipboard revision increments predictably.
- [ ] Clipboard content is absent from logs and metrics.

## M7 exit gate

- [ ] Supported text enters exactly.
- [ ] Unsupported text fails before partial input.
- [ ] Clipboard behavior is verified and encoding limitations are documented.

---

# M8 — Authenticated HTTP API

## M8.1 Configuration

- [ ] Implement typed configuration loading.
- [ ] Load non-secret values from environment variables.
- [ ] Load API and VNC secrets from files by default.
- [ ] Permit environment-based secrets only in an explicitly documented development mode if needed.
- [ ] Validate socket addresses, ports, capacities, limits, and timeouts.
- [ ] Reject empty secrets.
- [ ] Warn or fail on overly broad secret-file permissions according to documented policy.
- [ ] Redact secret values from debug output.

## M8.2 Authentication middleware

- [ ] Require `Authorization: Bearer <token>` for all `/v1/*` routes.
- [ ] Authenticate WebSocket upgrades.
- [ ] Never accept tokens in query parameters.
- [ ] Use a timing-resistant comparison where practical.
- [ ] Return the same generic response for missing and invalid tokens.
- [ ] Ensure access logs redact the authorization header.
- [ ] Test missing, malformed, wrong, and correct credentials.

## M8.3 Request IDs and error envelope

- [ ] Accept a valid incoming request ID or generate one.
- [ ] Return request ID in response headers and errors.
- [ ] Implement the specification's JSON error envelope.
- [ ] Map every domain error to a stable code and HTTP status.
- [ ] Prevent raw native errors and secrets from reaching clients.
- [ ] Test representative errors for every endpoint family.

## M8.4 Health and status routes

- [ ] Implement `/health/live`.
- [ ] Implement `/health/ready`.
- [ ] Ensure liveness does not imply VNC readiness.
- [ ] Ensure readiness requires a complete framebuffer.
- [ ] Implement `/v1/status`.
- [ ] Implement `/v1/display`.
- [ ] Verify no secret or connection password is serialized.

## M8.5 Screenshot route

- [ ] Implement `/v1/screenshot.png`.
- [ ] Add ETag and conditional GET support.
- [ ] Return JSON error when unavailable.
- [ ] Apply encode concurrency and deadline limits.

## M8.6 Pointer routes

- [ ] Implement `/v1/pointer/move`.
- [ ] Implement `/v1/pointer/button`.
- [ ] Implement `/v1/pointer/click`.
- [ ] Implement `/v1/pointer/double-click`.
- [ ] Implement `/v1/pointer/scroll`.
- [ ] Validate all payloads before enqueue.
- [ ] Return `202` for accepted asynchronous commands.

## M8.7 Keyboard routes

- [ ] Implement `/v1/keyboard/key`.
- [ ] Implement `/v1/keyboard/chord`.
- [ ] Implement `/v1/keyboard/text`.
- [ ] Ensure text preflight completes before enqueue.
- [ ] Enforce chord and text limits.

## M8.8 Clipboard and connection routes

- [ ] Implement `GET /v1/clipboard`.
- [ ] Implement `PUT /v1/clipboard`.
- [ ] Implement `POST /v1/connection/reconnect`.
- [ ] Rate-limit manual reconnect.
- [ ] Return `202` for an accepted reconnect request.

## M8.9 HTTP body and timeout controls

- [ ] Enforce global JSON body limit.
- [ ] Enforce route-specific text and clipboard limits.
- [ ] Add request header timeout.
- [ ] Add request body timeout.
- [ ] Add operation acknowledgement timeout.
- [ ] Reject new control commands during shutdown.
- [ ] Test slow and oversized requests.

## M8 exit gate

- [ ] Every v0.1 HTTP endpoint exists and follows the specification.
- [ ] Authentication, limits, timeouts, and typed errors are covered by tests.
- [ ] No endpoint blocks indefinitely.

---

# M9 — WebSocket events, observability, and overload behavior

## M9.1 Event envelope

- [ ] Implement global process-local event sequence numbers.
- [ ] Implement event timestamps.
- [ ] Implement required event types.
- [ ] Keep clipboard text and typed text out of events.
- [ ] Keep screenshot pixels out of v0.1 events.

## M9.2 WebSocket endpoint

- [ ] Implement authenticated `/v1/events` upgrade.
- [ ] Send an initial connection-state snapshot.
- [ ] Broadcast connection changes.
- [ ] Broadcast framebuffer revisions.
- [ ] Broadcast framebuffer invalidation.
- [ ] Broadcast clipboard revision changes.
- [ ] Broadcast overload and protocol error notifications.
- [ ] Bound per-client buffering.
- [ ] Disconnect slow clients with a clear close code/reason.
- [ ] Limit total WebSocket clients.
- [ ] Add ping/pong or idle detection.
- [ ] Clean up client resources on disconnect.

## M9.3 Structured logs

- [ ] Select a structured tracing stack.
- [ ] Add request spans and request IDs.
- [ ] Add connection and worker spans.
- [ ] Log state transitions.
- [ ] Log queue saturation and timeouts.
- [ ] Log reconnect attempts and outcomes.
- [ ] Add a redaction policy and tests.
- [ ] Verify API token, VNC password, text input, clipboard content, and pixels never appear.

## M9.4 Metrics

- [ ] Add an internal metrics endpoint or listener.
- [ ] Track connection state.
- [ ] Track reconnect attempts and outcomes.
- [ ] Track command totals by bounded command type label.
- [ ] Track queue depth and capacity.
- [ ] Track framebuffer revisions and update failures.
- [ ] Track screenshot encode counts, duration, and failures.
- [ ] Track WebSocket clients and slow-client disconnects.
- [ ] Track protocol and authentication errors.
- [ ] Avoid unbounded labels such as request ID, key, URL, or error message.

## M9.5 Overload and resilience tests

- [ ] Saturate the worker queue and verify explicit `command_queue_full` errors.
- [ ] Saturate PNG encoding permits and verify bounded behavior.
- [ ] Connect the maximum WebSocket clients and reject excess clients predictably.
- [ ] Simulate a slow WebSocket client and verify disconnection.
- [ ] Simulate a stalled VNC connection and verify API deadlines.
- [ ] Verify process memory remains bounded during sustained events.

## M9 exit gate

- [ ] Clients can observe state and revision changes without polling status continuously.
- [ ] Every queue and client backlog is bounded.
- [ ] Logs and metrics are useful without exposing payloads or secrets.

---

# M10 — Docker Compose and persistence modes

## M10.1 Controller image

- [ ] Create a multi-stage controller Dockerfile.
- [ ] Build Rust binaries in a dedicated build stage.
- [ ] Include only required LibVNCClient runtime libraries in the final image.
- [ ] Run as a dedicated non-root user.
- [ ] Add a minimal init if needed for signal handling.
- [ ] Add liveness and readiness health checks.
- [ ] Ensure the final image contains no compiler, Cargo registry, or build secret.

## M10.2 Production Compose

- [ ] Add `deploy/compose.yaml`.
- [ ] Create an internal network for desktop-controller traffic.
- [ ] Use `expose: 5901` for the desktop without host publishing.
- [ ] Publish only the controller API port.
- [ ] Mount API and VNC secrets through Docker secrets or secret-file mounts.
- [ ] Add health-check dependencies without relying only on startup order.
- [ ] Add CPU, memory, PID, and file-descriptor limits.
- [ ] Drop unnecessary capabilities.
- [ ] Enable `no-new-privileges`.
- [ ] Make the controller root filesystem read-only where practical.
- [ ] Add bounded temporary filesystems.
- [ ] Do not mount the Docker socket.

## M10.3 Debug VNC profile

- [ ] Add a development-only Compose override or profile.
- [ ] Bind `127.0.0.1:5901:5901` only.
- [ ] Add prominent documentation that it is not for public deployment.
- [ ] Verify production Compose has no inherited host port binding.

## M10.4 Persistence modes

- [ ] Make disposable desktop state the default.
- [ ] Add an optional named-volume profile for the desktop home directory.
- [ ] Document which state persists.
- [ ] Verify secrets are not copied into the persistent home volume.
- [ ] Verify disposable recreation clears desktop state.
- [ ] Verify persistent recreation preserves expected application state.

## M10.5 Compose smoke tests

- [ ] Start from a clean Docker state.
- [ ] Wait for desktop and controller health.
- [ ] Authenticate to the API.
- [ ] Fetch status, display, and screenshot.
- [ ] Confirm host port `5901` is absent in production mode.
- [ ] Confirm `5901` is bound only to loopback in debug mode.
- [ ] Stop the stack cleanly.
- [ ] Confirm no orphan containers or networks remain.

## M10 exit gate

- [ ] Production Compose exposes only the authenticated API.
- [ ] Debug VNC is opt-in and loopback-only.
- [ ] Disposable and persistent desktop modes both behave as documented.

---

# M11 — Integration and end-to-end validation

## M11.1 Integration harness

- [ ] Create scripts or Rust tests that launch the real Compose stack.
- [ ] Allocate collision-free host API ports in CI.
- [ ] Generate ephemeral test secrets.
- [ ] Wait on readiness with a bounded deadline.
- [ ] Capture container logs on failure.
- [ ] Always tear down containers, volumes, and networks in cleanup.

## M11.2 Connection tests

- [ ] Successful authentication reaches `connected`.
- [ ] Wrong VNC password reaches `authentication_failed`.
- [ ] Missing VNC secret fails startup closed.
- [ ] Desktop restart causes disconnect detection.
- [ ] Automatic reconnect succeeds.
- [ ] Old framebuffer becomes unavailable during reconnect.
- [ ] Full framebuffer returns before readiness.
- [ ] Repeated restart cycles do not leak threads or memory materially.

## M11.3 Display and screenshot tests

- [ ] Display reports `1280x800`.
- [ ] Initial PNG is valid and has exact dimensions.
- [ ] ETag changes after a visible update.
- [ ] Conditional GET returns `304` for unchanged revision.
- [ ] Screenshot is unavailable before first complete frame.
- [ ] Concurrent screenshot requests remain bounded.

## M11.4 Input tests through public API

- [ ] Move pointer to known coordinates and verify test-app result.
- [ ] Left-click known control and verify state change.
- [ ] Middle-click and right-click targets.
- [ ] Double-click target and verify exactly two clicks.
- [ ] Scroll vertically in both directions.
- [ ] Scroll horizontally in both directions if verified supported.
- [ ] Send individual key down/up and verify order.
- [ ] Send a chord and verify press/release ordering.
- [ ] Type supported text and verify exact field contents.
- [ ] Submit unsupported text and verify no partial field mutation.

## M11.5 Clipboard tests through public API

- [ ] Set desktop clipboard through API.
- [ ] Paste into test app and verify exact supported value.
- [ ] Copy from test app.
- [ ] Retrieve last-known clipboard snapshot through API.
- [ ] Verify clipboard revision and timestamp.
- [ ] Verify `clipboard_unavailable` before first inbound update.
- [ ] Verify oversized input rejection.

## M11.6 Authentication and abuse tests

- [ ] Verify all `/v1/*` routes reject no token.
- [ ] Verify all `/v1/*` routes reject wrong token.
- [ ] Verify WebSocket rejects unauthenticated upgrades.
- [ ] Verify token cannot be supplied through query string.
- [ ] Verify oversized JSON body rejection.
- [ ] Verify coordinate and scroll limit rejection.
- [ ] Verify queue saturation is explicit.
- [ ] Verify reconnect rate limiting.
- [ ] Verify secrets and payloads are absent from captured logs.

## M11.7 Shutdown tests

- [ ] Send SIGTERM to controller under idle conditions.
- [ ] Send SIGTERM with queued commands.
- [ ] Confirm new commands are rejected during shutdown.
- [ ] Confirm worker connection closes.
- [ ] Confirm worker thread joins.
- [ ] Confirm process exits within a bounded deadline.
- [ ] Stop desktop and confirm its child processes terminate.

## M11 exit gate

- [ ] The complete public API operates a real graphical application through TigerVNC.
- [ ] Recovery, overload, authentication, and shutdown behavior pass real-container tests.
- [ ] Test cleanup is reliable enough for repeated CI runs.

---

# M12 — CI, security hardening, and documentation

## M12.1 GitHub Actions quality workflow

- [ ] Add `.github/workflows/ci.yml`.
- [ ] Run `cargo fmt --check`.
- [ ] Run Clippy for all targets and features with warnings denied.
- [ ] Run all Rust tests.
- [ ] Build documentation with warnings denied where practical.
- [ ] Lint shell scripts.
- [ ] Lint Dockerfiles.
- [ ] Validate Compose configuration.
- [ ] Cache dependencies without caching secrets.
- [ ] Cancel superseded branch runs safely.

## M12.2 Native safety jobs

- [ ] Add AddressSanitizer coverage for adapter tests where supported.
- [ ] Add UndefinedBehaviorSanitizer coverage where supported.
- [ ] Consider ThreadSanitizer for Rust-only shared-state tests, documenting FFI limitations.
- [ ] Run Miri on compatible core code.
- [ ] Treat sanitizer findings as release blockers.

## M12.3 Dependency and image security

- [ ] Run Rust advisory checks.
- [ ] Run license and source policy checks.
- [ ] Scan controller image.
- [ ] Scan desktop image.
- [ ] Define blocked severity levels and exceptions process.
- [ ] Generate an SBOM or equivalent dependency inventory.
- [ ] Record LibVNCClient version in build metadata.
- [ ] Verify no secrets exist in repository history introduced by this implementation.

## M12.4 Integration CI

- [ ] Run Compose smoke tests on Linux.
- [ ] Run the real VNC integration suite.
- [ ] Run the public API end-to-end suite.
- [ ] Upload sanitized logs and test reports on failure.
- [ ] Do not upload screenshots that may contain sensitive test data unless fixtures are guaranteed non-sensitive.
- [ ] Set a bounded workflow timeout.

## M12.5 README and operator documentation

- [ ] Explain the product boundary.
- [ ] Include the architecture diagram.
- [ ] List prerequisites.
- [ ] Document secret generation.
- [ ] Document local build and startup.
- [ ] Document authenticated API examples without real secrets.
- [ ] Document screenshot and WebSocket usage.
- [ ] Document production reverse-proxy/TLS expectations.
- [ ] Document disposable and persistent modes.
- [ ] Document loopback-only debug VNC access.
- [ ] Document shutdown and recovery behavior.
- [ ] Document known text and clipboard encoding limitations.
- [ ] Document resource limits and tuning.
- [ ] Document troubleshooting for desktop startup, VNC auth, connection, and framebuffer readiness.

## M12.6 API documentation

- [ ] Add an OpenAPI document for HTTP routes.
- [ ] Document bearer authentication.
- [ ] Document every request and response schema.
- [ ] Document error codes and statuses.
- [ ] Document asynchronous `202` semantics.
- [ ] Document WebSocket event envelope separately if OpenAPI tooling is insufficient.
- [ ] Add tested curl examples.

## M12 exit gate

- [ ] CI enforces code quality, real integration behavior, native safety, and security policy.
- [ ] A new developer can run the system from the README.
- [ ] An operator can deploy it without exposing raw VNC.

---

# M13 — Final v0.1 acceptance gate

Do not call v0.1 complete until every item below is supported by exact evidence.

## M13.1 Architecture and isolation

- [ ] Exactly one desktop session is implemented.
- [ ] Desktop and controller are separate containers.
- [ ] TigerVNC is reachable only on the private network in production Compose.
- [ ] Optional raw VNC debug access binds only to `127.0.0.1`.
- [ ] Desktop and controller workloads run as non-root.
- [ ] Raw LibVNCClient state is confined to the adapter and one worker thread.

## M13.2 Observation

- [ ] Controller receives a complete framebuffer.
- [ ] Display metadata is correct.
- [ ] PNG screenshots are coherent.
- [ ] Screenshot ETags and conditional requests work.
- [ ] Old framebuffer data is invalidated on reconnect.
- [ ] Revision events are delivered over authenticated WebSocket.

## M13.3 Control

- [ ] Pointer move works.
- [ ] Button down/up works.
- [ ] Left, middle, and right click work.
- [ ] Double-click works atomically.
- [ ] Vertical scrolling works.
- [ ] Horizontal scrolling either works and is tested or is explicitly removed from v0.1 API and spec before release.
- [ ] Key down/up works.
- [ ] Chords press and release in the required order.
- [ ] Supported text enters exactly.
- [ ] Unsupported text fails before partial input.
- [ ] Outbound and inbound clipboard behavior work as documented.

## M13.4 Reliability

- [ ] Automatic reconnect works after desktop restart.
- [ ] Authentication failure is visible and backoff-safe.
- [ ] Worker queue saturation is visible.
- [ ] Requests and shutdown are time-bounded.
- [ ] Slow WebSocket clients cannot consume unbounded memory.
- [ ] Worker failure causes readiness failure.
- [ ] No command is silently dropped.

## M13.5 Security

- [ ] API bearer token is required on all `/v1/*` routes.
- [ ] VNC authentication is mandatory.
- [ ] Tokens and passwords come from secrets, not image layers.
- [ ] No bearer token, VNC password, typed text, clipboard content, or framebuffer content appears in logs.
- [ ] No public raw VNC binding exists in production configuration.
- [ ] Container capabilities and resource limits are applied.
- [ ] Dependency and image scans satisfy the release policy.

## M13.6 Quality evidence

- [ ] Formatting passes.
- [ ] Clippy passes with warnings denied.
- [ ] Unit tests pass.
- [ ] Adapter safety tests pass.
- [ ] Integration tests pass.
- [ ] End-to-end tests pass.
- [ ] Sanitizer jobs pass.
- [ ] Compose smoke test passes from a clean environment.
- [ ] README and API documentation match actual behavior.
- [ ] Exact release commit SHA is recorded below.

## M13.7 Final evidence record

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
- Unit tests:
- Integration tests:
- End-to-end tests:
- Sanitizers:
- Security scans:
- Container smoke test:

Known v0.1 limitations:

Release decision:
```

---

# Post-v0.1 backlog — not part of this implementation

Do not pull these into the v0.1 critical path without a deliberate specification revision.

- [ ] Dirty-rectangle image streaming.
- [ ] JPEG/WebP live frame streaming.
- [ ] Human versus automation control leases.
- [ ] Multiple desktop sessions.
- [ ] Per-session container lifecycle API.
- [ ] Multi-user authentication and authorization.
- [ ] AT-SPI accessibility integration.
- [ ] OCR helpers.
- [ ] Computer-vision targeting.
- [ ] Playwright integration.
- [ ] Natural-language or AI task planning.
- [ ] Browser-based viewer.
- [ ] Dynamic screen resizing.
- [ ] Connections to arbitrary external VNC servers.
