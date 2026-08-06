# VNC Remote Control Server Post-Correctness Hardening TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_SPEC_2026-08-06.md`

Reviewed baseline SHA: `96836f7ff964813fb727a1f7407fb0b1f448b738`

Status: not started.

---

## H0. Ground rules and baseline protection

- [ ] Confirm current branch is `master`.
- [ ] Record starting SHA before edits.
- [ ] Read the post-correctness hardening spec in full.
- [ ] Read the completed correctness-review TODO enough to preserve its accepted
      contracts.
- [ ] Do not mark any historical completed task as incomplete unless the source
      evidence proves a real regression.
- [ ] Do not weaken CI, Release Gates, sanitizer gates, Gitleaks, ShellCheck,
      actionlint, Dockerfile checks, Compose checks, cargo-deny, auditable binary
      checks, Trivy, SBOM, or VEX gates.
- [ ] Do not use `continue-on-error`, broad ignores, suppressed exit codes, force
      pushes, or older-SHA evidence.
- [ ] Keep changes scoped to H1-H6 unless a compile/test failure requires a
      directly related fix.

Acceptance:

- [ ] Starting SHA is recorded in the final evidence block.
- [ ] No unrelated architectural or feature work is mixed into this pass.

---

## H1. Repair CR12 mismatched-frame evidence gap

Source targets:

- `crates/controller-api/src/worker/tests/reconnect.rs`
- Related worker test helpers in `crates/controller-api/src/worker/tests/mod.rs`
  only if needed.

Tasks:

- [ ] Inspect `mismatched_native_frame_never_reaches_connected`.
- [ ] Preserve the existing negative assertions:
  - [ ] causal worker poll progress is observed;
  - [ ] mismatched native display/framebuffer revision does not reach
        `ConnectionState::Connected`;
  - [ ] `fatal_exit` remains false;
  - [ ] `framebuffer_snapshot()` remains unavailable.
- [ ] Add a positive control using the same or adjacent fixture path:
  - [ ] a valid matching native display/framebuffer revision is observed;
  - [ ] the worker reaches `ConnectionState::Connected`;
  - [ ] a current framebuffer snapshot is available;
  - [ ] the observed framebuffer revision/content proves the positive path is
        not a no-op.
- [ ] Ensure the positive control would fail if the observation path were broken.
- [ ] Avoid sleep-only negative proof.
- [ ] Avoid weakening timeout bounds by merely increasing sleeps.
- [ ] Name the test or add comments so the CR12 positive-control requirement is
      easy to trace.

Expected validation:

- [ ] Targeted test command for the repaired test passes.
- [ ] Full `controller-api` library tests pass.

Acceptance:

- [ ] The CR12 mismatch test evidence now has both causal progress and positive
      control.

Do not accept:

- [ ] A test that only sleeps and asserts absence.
- [ ] A positive control that uses a completely unrelated code path.
- [ ] A test that removes or weakens the mismatched-frame negative assertion.

---

## H2. Replace EventHub sequence exhaustion panic with fail-closed behavior

Source targets:

- `crates/controller-api/src/events.rs`
- `crates/controller-api/src/http/handlers.rs`
- `crates/controller-api/src/http/responses.rs`
- `crates/controller-api/src/http/tests/*` as needed.

Tasks:

- [ ] Locate every event sequence allocation path.
- [ ] Replace `expect("worker event sequence exhausted")` with explicit error or
      closed-state handling.
- [ ] Ensure event sequence exhaustion never:
  - [ ] wraps;
  - [ ] reuses a prior sequence;
  - [ ] saturates silently at `u64::MAX`;
  - [ ] panics inside the event bridge;
  - [ ] panics inside a WebSocket request path.
- [ ] Add a bounded diagnostic for sequence exhaustion.
- [ ] Ensure the diagnostic does not include request bodies, typed text,
      clipboard text, key names, coordinates, framebuffer bytes, screenshot
      bytes, bearer tokens, VNC passwords, or URLs with query strings.
- [ ] Define the route behavior when the initial WebSocket snapshot cannot be
      sequenced:
  - [ ] return a bounded HTTP error before upgrade if possible, or
  - [ ] close the WebSocket with a bounded close reason if the upgrade already
        occurred.
- [ ] Ensure bridge-published worker events are dropped/closed in a deterministic
      fail-closed way after sequence exhaustion.
- [ ] Preserve strictly increasing sequences for normal events.
- [ ] Preserve payload-free snapshot and worker event bodies.

Expected tests:

- [ ] Unit test forces the hub sequence to `u64::MAX` and proves event creation
      fails without panic.
- [ ] Unit or route-level test proves initial snapshot sequence exhaustion has a
      bounded failure response.
- [ ] Existing monotonic sequence test is updated to the new behavior.
- [ ] Normal WebSocket snapshot/event delivery still works.

Acceptance:

- [ ] No event infrastructure sequence exhaustion path can panic, wrap, reuse, or
      silently hide the failure.

Do not accept:

- [ ] `unwrap`, `expect`, or panic for event sequence exhaustion.
- [ ] `saturating_add` for public event sequence IDs.
- [ ] Resetting the sequence to zero or one.
- [ ] A log line containing sensitive payloads.

---

## H3. Move API bearer token storage to an explicit secret type

Source targets:

- `crates/controller-api/src/config.rs`
- `crates/controller-api/src/http/state.rs`
- `crates/controller-api/src/http/support.rs`
- `crates/controller-api/src/http/middleware.rs`
- `crates/controller-api/src/http/tests/*`
- `SECURITY.md` if the secret-lifecycle boundary changes.

Tasks:

- [ ] Identify the current long-lived `Arc<str>` API-token storage.
- [ ] Introduce or reuse a non-`Debug`, non-`Display` secret wrapper suitable for
      controller API bearer tokens.
- [ ] Ensure cloned controller state does not clone token bytes into ordinary
      strings.
- [ ] Preserve constant-time bearer-token comparison.
- [ ] Preserve current authentication semantics:
  - [ ] missing header rejected;
  - [ ] query-token rejected;
  - [ ] wrong token rejected;
  - [ ] valid `Authorization: Bearer ...` accepted;
  - [ ] empty token rejected at config/state construction.
- [ ] Preserve redacted access logging.
- [ ] Preserve config `Debug` redaction.
- [ ] Ensure no new `Debug` or `Display` implementation exposes the token.
- [ ] Ensure tests and fixtures do not print token contents on failure.

Expected tests:

- [ ] Config debug redaction test still passes and checks API token redaction.
- [ ] Bearer comparison tests still pass.
- [ ] HTTP auth tests still reject missing/query/wrong token and accept the real
      header token.
- [ ] Privacy tests still prove bearer sentinel is not in access logs.
- [ ] HTTP/WebSocket E2E still proves token does not appear in logs, metrics, or
      event payloads.

Acceptance:

- [ ] The API token is no longer stored as raw `Arc<str>` or equivalent ordinary
      long-lived string storage.
- [ ] Authentication behavior is unchanged from the user/API perspective.

Do not accept:

- [ ] A secret wrapper that implements `Debug` or `Display` with the real value.
- [ ] A comparison that short-circuits on matching prefix content after length is
      known in a way that weakens the existing constant-time property.
- [ ] A fallback that accepts query tokens, empty tokens, or missing bearer
      prefixes.

---

## H4. Scrub secret-file raw bytes on rejection paths

Source targets:

- `crates/controller-api/src/config.rs`
- Any small helper module introduced for secret parsing.

Tasks:

- [ ] Factor secret-file parsing so live raw bytes can be scrubbed on every
      rejection path after file contents are read.
- [ ] Preserve metadata checks before reading:
  - [ ] file exists and metadata is readable;
  - [ ] path is a regular file;
  - [ ] file length is within the accepted bound;
  - [ ] Unix permission policy is unchanged.
- [ ] Scrub live raw bytes before returning errors for:
  - [ ] invalid UTF-8;
  - [ ] empty content after CR/LF trimming;
  - [ ] embedded NUL;
  - [ ] any future parser validation failure inside the helper.
- [ ] Ensure successful parses do not create unnecessary extra ordinary string
      copies before entering the chosen secret type.
- [ ] Keep error messages redaction-safe.
- [ ] Do not add tests that read freed memory.

Expected tests:

- [ ] Invalid UTF-8 sentinel bytes are scrubbed before the parser returns.
- [ ] Embedded-NUL sentinel bytes are scrubbed before the parser returns.
- [ ] Empty-after-trim input is rejected and scrubbed.
- [ ] Valid secret input still loads successfully.
- [ ] Permission/metadata tests still pass.

Acceptance:

- [ ] Every parser-owned raw byte buffer containing secret file contents is
      explicitly scrubbed before being dropped on a rejection path.

Do not accept:

- [ ] A test that relies on allocator reuse or freed-memory inspection.
- [ ] Error messages containing secret bytes.
- [ ] A broad `String::from_utf8(...)?` path that drops invalid bytes without
      explicit scrub.

---

## H5. Scrub project-owned native clipboard/transient text buffers or document exact boundary

Source targets:

- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/src/lib.rs`
- `SECURITY.md`
- `docs/OPERATOR_GUIDE.md` or a release-note file if needed.
- Policy/contract tests under `tests/` or crate tests as appropriate.

Tasks:

- [ ] Decide the exact policy for project-owned clipboard and transient text
      buffers.
- [ ] At minimum, scrub `client->clipboard` before replacement in
      `vrc_store_clipboard`.
- [ ] Scrub `client->clipboard` before free in `vrc_client_destroy`.
- [ ] Scrub outbound `copy` in `vrc_client_send_clipboard` before free.
- [ ] Keep VNC password scrub behavior unchanged.
- [ ] Do not claim toolkit/OS/VNC-server/LibVNCClient/allocator copies are
      scrubbed unless there is direct evidence.
- [ ] Document the boundary between:
  - [ ] project-owned C clipboard buffers;
  - [ ] Rust inbound/outbound clipboard values;
  - [ ] HTTP response bodies;
  - [ ] Tk/test-app clipboard state;
  - [ ] LibVNCClient and VNC server copies;
  - [ ] OS/toolkit clipboard managers;
  - [ ] allocator residuals.
- [ ] Ensure logs still do not contain clipboard payloads.

Expected tests:

- [ ] Source-level or native-unit test fails if `client->clipboard` is freed or
      replaced without scrub.
- [ ] Source-level or native-unit test fails if outbound clipboard `copy` is
      freed without scrub.
- [ ] Existing clipboard/text E2E still passes.
- [ ] Existing privacy tests still prove clipboard sentinels do not appear in
      logs, metrics, or events.
- [ ] Documentation/policy test prevents claiming third-party-owned clipboard
      copies are scrubbed.

Acceptance:

- [ ] Project-owned native clipboard/transient text buffers have a tested scrub
      policy.
- [ ] Documentation accurately distinguishes scrubbed project-owned buffers from
      third-party or OS-owned residuals.

Do not accept:

- [ ] Freed-memory reads as proof.
- [ ] A broad claim that all clipboard copies are scrubbed.
- [ ] Logging clipboard text in a new diagnostic or test failure.

---

## H6. Remove silent default metric methods from `HttpBackend`

Source targets:

- `crates/controller-api/src/http/backend.rs`
- `crates/controller-api/src/http/tests/mod.rs`
- Other test/mock backends implementing `HttpBackend`.

Tasks:

- [ ] Remove default implementations of:
  - [ ] `command_submissions_in_flight()`;
  - [ ] `command_queue_capacity()`.
- [ ] Make both methods required trait methods.
- [ ] Update production implementation explicitly.
- [ ] Update all mocks/test backends explicitly.
- [ ] Ensure mocks use intentional values, not accidental zeros.
- [ ] Preserve metric names:
  - [ ] `vrc_worker_command_submissions_in_flight`;
  - [ ] `vrc_worker_command_queue_capacity`.
- [ ] Preserve metric help text and gauge/counter metadata.
- [ ] Do not restore an alias for the old queue-depth metric.

Expected tests:

- [ ] HTTP metrics tests still pass.
- [ ] A mock/backend omission would fail to compile because the trait method is
      required.
- [ ] Metrics output still includes the two command metric names.

Acceptance:

- [ ] No backend can silently report command metric values as zero by omitting
      methods.

Do not accept:

- [ ] `unwrap_or(0)` fallback for production command metric values.
- [ ] Default trait methods returning zero.
- [ ] Reintroduction of an old metric alias without a named external consumer.

---

## H7. Documentation updates

Source targets:

- `SECURITY.md`
- `docs/OPERATOR_GUIDE.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_SPEC_2026-08-06.md`
- This TODO file.
- Optional release notes file if behavior changes are user-visible.

Tasks:

- [ ] Document API-token secret lifecycle after H3.
- [ ] Document secret-file rejection scrubbing after H4.
- [ ] Document native clipboard/transient text scrub boundary after H5.
- [ ] Document EventHub sequence exhaustion behavior after H2.
- [ ] Document that CR12 evidence repair does not change runtime behavior.
- [ ] Document any public error-envelope behavior change from H2.
- [ ] List explicit deferrals, if any.

Acceptance:

- [ ] Documentation describes the implemented contracts accurately.
- [ ] Documentation does not claim third-party-owned or OS-owned buffers are
      scrubbed without evidence.

---

## H8. Local validation

Run before pushing whenever available:

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`
- [ ] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [ ] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] Shell syntax checks for permanent scripts.

Where Docker/VNC are available:

- [ ] `tests/desktop/run.sh`
- [ ] `tests/native/run.sh`
- [ ] `tests/worker-e2e/run.sh`
- [ ] `tests/worker-text-clipboard-e2e/run.sh`
- [ ] `tests/http-e2e/run.sh`
- [ ] `tests/compose/run.sh`
- [ ] `tests/integration/run.sh`

- [ ] Record every unavailable local command and exact reason.
- [ ] Do not label unavailable validation as passed.

Acceptance:

- [ ] All available local checks pass.
- [ ] Unavailable surfaces are explicitly deferred to exact-SHA permanent
      workflows.

---

## H9. Exact-SHA permanent validation

- [ ] Commit implementation changes intentionally.
- [ ] Push to `master` without force.
- [ ] Record implementation SHA.
- [ ] Wait for CI on that exact SHA.
- [ ] Wait for Release Gates on that exact SHA.
- [ ] Confirm CI success across repository quality and integration surfaces.
- [ ] Confirm Release Gates success across:
  - [ ] static/supply-chain policy;
  - [ ] full-history Gitleaks;
  - [ ] ShellCheck/actionlint;
  - [ ] Dockerfile/Compose validation;
  - [ ] cargo policy;
  - [ ] auditable binary metadata verification;
  - [ ] ASan;
  - [ ] controller-api TSan;
  - [ ] remote-desktop-core TSan;
  - [ ] Miri boundary;
  - [ ] Trivy/SBOM/VEX.
- [ ] Repair root causes only; do not weaken gates or assertions.
- [ ] Do not use previous-SHA, canceled, superseded, or partial jobs as
      completion evidence.

Acceptance:

- [ ] Same exact final tip passes CI and Release Gates.

---

## H10. Final evidence and completion report

- [ ] Complete this TODO only after exact-SHA validation.
- [ ] Fill the evidence block below.
- [ ] Add or update an implementation notes file if the changes are nontrivial.
- [ ] Commit documentation/evidence changes intentionally.
- [ ] Push without force.
- [ ] Wait for CI and Release Gates on the exact final documentation tip if a
      documentation commit follows implementation validation.
- [ ] Record external workflow run IDs; do not claim a commit embeds its own
      future hash or future workflow IDs.

Final evidence:

```text
Starting SHA:
Implementation SHA:
Final documentation SHA, if separate:
Final repository-tip SHA:
CI run ID and conclusion:
Release Gates run ID and conclusion:

H1 CR12 evidence repair:

H2 EventHub sequence exhaustion:

H3 API token secret lifecycle:

H4 secret-file rejection scrubbing:

H5 native clipboard/transient buffer policy:

H6 HttpBackend metric defaults:

Local validation:

Unavailable local validation, with reasons:

Deferred follow-ups:
```

Acceptance:

- [ ] This TODO is marked complete only after the exact final repository tip is
      green in CI and Release Gates.

---

## Final do-not-accept checklist

- [ ] No sleep-only negative proof remains for the CR12 mismatched-frame test.
- [ ] No EventHub event sequence can wrap, reuse, saturate silently, or panic.
- [ ] No API bearer token is stored as long-lived raw `Arc<str>` or equivalent
      ordinary string storage.
- [ ] No secret-file invalid UTF-8 path drops raw secret bytes without scrub.
- [ ] No project-owned native clipboard buffer is replaced or destroyed without
      the chosen scrub policy.
- [ ] No claim says third-party, OS, toolkit, allocator, VNC-server, or
      LibVNCClient-owned clipboard copies are scrubbed without evidence.
- [ ] No `HttpBackend` command metric method silently defaults to zero.
- [ ] No old queue-depth metric alias is reintroduced.
- [ ] No public shutdown, framebuffer, authentication, ETag, WebSocket, input, or
      R13 behavior is weakened.
- [ ] No command payload, typed text, clipboard text, key name, coordinate,
      bearer token, VNC password, framebuffer byte, screenshot byte, or query
      secret is logged.
- [ ] No `continue-on-error`, broad ignore, suppressed exit code, force push, or
      older-SHA evidence is accepted.
