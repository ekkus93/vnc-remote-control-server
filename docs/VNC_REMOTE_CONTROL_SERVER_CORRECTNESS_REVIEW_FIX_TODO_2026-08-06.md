# VNC Remote Control Server Correctness Review Fix TODO

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Companion specification:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_SPEC_2026-08-06.md`

Decision documents:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_QUESTIONS_AND_ISSUES_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_ANSWERS_2026-08-06.md`

Code baseline for defect reproduction: `e9be696783e7fdfb90389cd02890d48c3e9bbd2d`

Planning baseline containing the accepted decisions: `c49742a2d1e1c3b55ae3f3f8affec9357b8855f4`

This TODO is the authoritative implementation checklist for the correctness-review fix pass. It preserves the completed shutdown architecture while correcting the state-machine, timeout-contract, native-format, sanitizer, metric, secret-lifecycle, privacy-test, performance-record, and deterministic-test issues defined in the companion spec.

## Completion status

Status: not started.

Do not mark this TODO complete until the exact final repository-tip SHA passes both permanent CI and Release Gates, including unchanged R13.

---

## CR0. Baseline, decisions, and evidence classification

- [ ] Check out the latest `master` with a clean working tree.
- [ ] Record the starting HEAD SHA in the final evidence block.
- [ ] Confirm the companion spec and this TODO exist.
- [ ] Read both decision documents completely.
- [ ] Confirm the spec contains no unresolved “choose one” implementation menus.
- [ ] Read the preserved shutdown chain:
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- [ ] Review all implementation surfaces named by the spec:
  - [ ] `crates/remote-desktop-core/src/connection.rs`
  - [ ] `crates/controller-api/src/worker/loop_state.rs`
  - [ ] `crates/controller-api/src/worker/run.rs`
  - [ ] `crates/controller-api/src/worker/client.rs`
  - [ ] `crates/controller-api/src/worker/desktop_worker.rs`
  - [ ] `crates/controller-api/src/events.rs`
  - [ ] `crates/controller-api/src/framebuffer.rs`
  - [ ] `crates/controller-api/src/observability.rs`
  - [ ] `crates/controller-api/src/config.rs`
  - [ ] `crates/controller-api/src/shutdown.rs`
  - [ ] `crates/controller-api/src/main.rs`
  - [ ] `crates/controller-api/src/http/backend.rs`
  - [ ] `crates/controller-api/src/http/responses.rs`
  - [ ] `crates/libvnc-adapter/native/vnc_shim.c`
  - [ ] `crates/libvnc-adapter/native/vnc_shim.h`
  - [ ] `crates/libvnc-adapter/src/lib.rs`
  - [ ] `.github/workflows/release-gates.yml`
  - [ ] desktop test application and all E2E scripts.
- [ ] Confirm preserved behavior before editing:
  - [ ] out-of-band worker shutdown remains authoritative;
  - [ ] queue permit remains acquired before `try_send`;
  - [ ] event-bridge stop/exit/join/detach model remains intact;
  - [ ] server → worker → bridge error precedence remains intact;
  - [ ] framebuffer byte equality, revisions, timestamps, ETags, and R13 `304` semantics remain intact;
  - [ ] input-release observability remains intact.

Classify and record baseline evidence before each repair:

- [ ] CR1: failing production-path pre-`Connected` stall test.
- [ ] CR2: failing production-path illegal-transition observability/health test.
- [ ] CR3: failing E2E color assertion, or exact static current-layout evidence if pre-fix E2E cannot run.
- [ ] CR4: absent/failing `controller-api` TSan invocation with exact output.
- [ ] CR5: runtime test showing the in-flight value can exceed channel capacity.
- [ ] CR6: failing configuration validation plus timing calculation.
- [ ] CR7: timing calculation and exact source evidence.
- [ ] CR8: static source evidence for unreachable arms.
- [ ] CR9: focused live-buffer/helper evidence; never inspect freed memory.
- [ ] CR10: path-carrying evidence; regression guards may pass on the baseline.
- [ ] CR11: reproducible measurement evidence.
- [ ] CR12: show the old sleep-based test can pass under an injected fault it claims to detect.

Acceptance:

- [ ] No repair precedes its classified evidence.
- [ ] No fake runtime failure is manufactured for a static, workflow, or documentation defect.
- [ ] Implementation notes distinguish this pass from the completed shutdown work.

Evidence:

```text
Starting HEAD SHA:
Working tree clean:
Baseline evidence summary:
```

---

## CR1. Recover pre-`Connected` confirmed stalls

Reproduce first:

- [ ] Add a controlled session that completes native setup but never delivers a complete framebuffer update.
- [ ] Keep the public state in `Connecting` or `Reconnecting` while `poll()` returns `TimedOut`.
- [ ] Drive probe and confirmation through deterministic fixture controls and bounded deadlines.
- [ ] Confirm the baseline terminates the worker, sets `fatal_exit`, and does not reconnect.
- [ ] Record the exact baseline failure.

Implement the prescribed repair:

- [ ] Do not widen `ConnectionState::can_transition_to` with pre-`Connected` → `Degraded` edges.
- [ ] Preserve `Degraded` as “previously connected, now impaired.”
- [ ] For current state `Connected`, retain `Connected -> Degraded -> invalidate -> reconnect`.
- [ ] For current state `Connecting` or `Reconnecting`:
  - [ ] record `WorkerFailureKind::Timeout`;
  - [ ] emit `worker_stall_timeout`;
  - [ ] invalidate session/framebuffer/input state;
  - [ ] schedule reconnect without entering `Degraded`;
  - [ ] keep `fatal_exit == false`;
  - [ ] keep the worker loop alive.

Regression test: `pre_connected_confirmed_stall_reconnects_without_fatal_exit`

- [ ] Drive the real worker loop, not a helper-only path.
- [ ] Assert the session factory is invoked again.
- [ ] Assert `fatal_exit == false` before and after reconnect scheduling.
- [ ] Assert the worker does not reach `Stopped` before explicit shutdown.
- [ ] Assert `worker_stall_timeout` is present and payload-free.
- [ ] Use bounded channels/barriers/deadlines, not sleeps.

Regression preservation:

- [ ] Keep `confirmed_stall_invalidates_reconnects_and_advances_revision` green.
- [ ] Assert the legal `Connected -> Degraded` event remains emitted.
- [ ] Assert framebuffer invalidation and revision behavior remain unchanged.

Acceptance:

- [ ] A pre-`Connected` confirmed stall reconnects without fatal exit.
- [ ] A previously connected stall retains existing `Degraded` semantics.

---

## CR2. Make illegal transitions observable and non-mutating

- [ ] Change `LoopState::transition()` so illegal transitions:
  - [ ] emit `worker_illegal_state_transition`;
  - [ ] include only `from` and `to` state names;
  - [ ] do not change state;
  - [ ] do not set `fatal_exit`;
  - [ ] return `DesktopError::Protocol`.
- [ ] Keep successful transition logging and event publication unchanged.
- [ ] Keep `run_worker` as the owner of fatal exit when the loop ends unexpectedly.
- [ ] Review `LoopState::publish` sequence-overflow handling:
  - [ ] retain its `fatal_exit` write only with an explicit unrecoverable rationale; or
  - [ ] move it to the centralized fatal-exit path.
- [ ] Make `schedule_reconnect()` infallible by selecting a legal target from the current state.
- [ ] Ensure `schedule_reconnect()` from `AuthenticationFailed` does not attempt an illegal intermediate state.
- [ ] Remove every discarded transition result that can hide failure.

Explicit final `Stopped` handling:

- [ ] Replace `let _ = state.transition(ConnectionState::Stopped)` with explicit result handling.
- [ ] Add a `debug_assert!` that every current state can reach `Stopped`.
- [ ] If the final transition fails in production:
  - [ ] emit a dedicated payload-free error diagnostic;
  - [ ] set `fatal_exit` in the explicit finalization path;
  - [ ] do not silently leave stale public state.

Regression tests:

### `illegal_transition_is_logged_and_does_not_mutate_health`

- [ ] Drive an illegal transition through production `LoopState`.
- [ ] Parse structured logs and assert `from`/`to` only.
- [ ] Assert state and `fatal_exit` remain unchanged.

### `schedule_reconnect_from_authentication_failed_is_legal`

- [ ] Start from `AuthenticationFailed`.
- [ ] Assert no illegal-transition diagnostic.
- [ ] Assert the resulting target is legal and reconnectable.

### `final_stopped_transition_failure_is_not_silent`

- [ ] Use a test-only state/invariant fault if required.
- [ ] Assert a diagnostic and fatal disposition instead of ignored failure.

Acceptance:

- [ ] No illegal transition silently poisons externally visible health.
- [ ] No final state-transition failure is ignored.

---

## CR3. Pin and verify native `[R,G,B,X]` format

In `vrc_client_connect`, after `rfbGetClient` and before `SetFormatAndEncodings`:

- [ ] set `format.bitsPerPixel = 32`;
- [ ] set `format.depth = 24`;
- [ ] set `format.trueColour = TRUE`;
- [ ] set `format.bigEndian = FALSE`;
- [ ] set `format.redMax = 255`;
- [ ] set `format.greenMax = 255`;
- [ ] set `format.blueMax = 255`;
- [ ] set `format.redShift = 0`;
- [ ] set `format.greenShift = 8`;
- [ ] set `format.blueShift = 16`;
- [ ] set `appData.requestedDepth = 24`.
- [ ] Add a contract comment: native memory layout is `[R,G,B,X]`.
- [ ] Add the matching contract comment to `replace_native_rgbx()`.
- [ ] Verify the pinned LibVNCClient sends the assigned format and does not overwrite it from `appData`.
- [ ] Keep canonical framebuffer format `[R,G,B,255]` unchanged.

Unit test: `native_rgbx_conversion_preserves_channel_order`

- [ ] Use distinct values in every channel and padding byte.
- [ ] Assert every canonical byte and opaque alpha.

Desktop/E2E fixture:

- [ ] Add fixed pure-red and pure-blue swatches to the test application.
- [ ] Define swatch geometry and center sample coordinates as named constants.
- [ ] Place swatches away from existing controls and text fields.

Canonical framebuffer assertion:

- [ ] Red center: `r > 200`, `g < 60`, `b < 60`.
- [ ] Blue center: `b > 200`, `r < 60`, `g < 60`.

Decoded PNG assertion:

- [ ] Fetch `GET /v1/screenshot.png`.
- [ ] Decode PNG pixels.
- [ ] Apply the same dominance assertions at the named centers.
- [ ] Do not assert on encoded bytes.

- [ ] If lossless encodings are pinned, document them and optionally tighten tolerance to `±8`.
- [ ] Confirm a red/blue channel swap fails both layers.

Acceptance:

- [ ] Pixel layout is negotiated, documented, and proven end to end.

---

## CR4. Expand TSan and correct Miri claims

Baseline:

- [ ] Record that existing TSan/Miri target only `remote-desktop-core`.
- [ ] Attempt `controller-api --lib` under the pinned TSan toolchain and save exact output.

Escalation order:

- [ ] First try all `controller-api --lib` tests unchanged.
- [ ] If Tokio-specific false positives occur, add the smallest documented `--skip` list while retaining worker, shutdown, events, and framebuffer coverage.
- [ ] If still required, evaluate a narrowly scoped suppression file.
- [ ] Use a test-only native-adapter exclusion feature only as the last resort.
- [ ] Record which level succeeded and why earlier levels failed.

Workflow requirements:

- [ ] Add permanent TSan coverage for the achieved `controller-api` subset.
- [ ] Keep existing `remote-desktop-core` TSan and Miri jobs.
- [ ] Keep existing `libvnc-adapter` ASan job.
- [ ] Do not add `continue-on-error`.
- [ ] Do not label linked-but-unexecuted native code as instrumented.

Miri documentation:

- [ ] State permanently that FFI, Tokio, native linkage, and real I/O place `controller-api` outside the Miri boundary.
- [ ] Remove any claim that prior hardening added Miri coverage to concurrent code.
- [ ] Remove Miri from the list of gates expected to gain new coverage in this pass.

Acceptance:

- [ ] TSan meaningfully exercises the concurrent code changed by shutdown hardening.
- [ ] Sanitizer evidence states exactly what runs.

---

## CR5. Rename queue-depth instrumentation to submissions in flight

- [ ] Confirm permit acquisition remains in `CommandEnvelope::new()` before `try_send`.
- [ ] Do not alter increment/decrement/drop behavior.
- [ ] Rename Rust API usage to `command_submissions_in_flight`.
- [ ] Rename Prometheus metric to `vrc_worker_command_submissions_in_flight`.
- [ ] Remove the old metric without alias unless the user identifies an external consumer before implementation.
- [ ] Confirm `/v1/status` has no affected field and requires no schema change.
- [ ] Update `HttpBackend` and `WorkerHttpBackend` names.
- [ ] Update tests and all documentation references.
- [ ] Search and record references in:
  - [ ] `deploy/`;
  - [ ] tests;
  - [ ] dashboards and alert rules;
  - [ ] examples;
  - [ ] operator guide;
  - [ ] V01 spec section 17.1;
  - [ ] release notes/policy.
- [ ] Confirm R13 contains no assertion on the old name.

Prometheus metadata:

- [ ] Add correct `# HELP` and `# TYPE` for every exported metric.
- [ ] Classify counters and gauges correctly.
- [ ] State that submissions in flight may transiently exceed queue capacity.
- [ ] Add exporter-format regression tests.

Runtime regression: `in_flight_submissions_can_exceed_capacity_and_converge_to_zero`

- [ ] Park one or more submitters after permit acquisition and before send.
- [ ] Assert the reported value exceeds channel capacity.
- [ ] Release all submitters.
- [ ] Assert the value converges to zero.

Policy:

- [ ] Add a concise metric/API naming-compatibility rule to the release policy.
- [ ] Record the no-alias v0.1 decision and its repository-local basis.

Acceptance:

- [ ] Exported names and help text describe the actual value.
- [ ] Accounting implementation remains unchanged.

---

## CR6. Add one total process-shutdown budget

Configuration:

- [ ] Add `VRC_SHUTDOWN_TIMEOUT_MS` with a documented default.
- [ ] Define the minimum as `max(500 ms, 8 * EVENT_BRIDGE_POLL_INTERVAL)` through a derived constant.
- [ ] Reject values below the minimum with a non-secret error naming the variable.
- [ ] Keep `command_ack_timeout` exclusively for HTTP command acknowledgement.
- [ ] Update configuration redaction/debug behavior and tests.

Coordinator:

- [ ] Establish one deadline at `finalize_runtime` entry.
- [ ] Pass remaining budget to worker shutdown.
- [ ] Recompute remaining budget with saturating arithmetic.
- [ ] Pass only the remainder to bridge shutdown.
- [ ] Preserve server → worker → bridge error precedence.
- [ ] Attempt both cleanup surfaces within the shared budget.

Zero-remainder bridge path:

- [ ] Request bridge stop.
- [ ] Perform a nonblocking exit-result check.
- [ ] If exit is already observed, join and preserve panic/success disposition.
- [ ] If still active, detach deliberately.
- [ ] Emit a payload-free timeout or secondary-cleanup diagnostic.
- [ ] Do not call a zero-duration blocking wait.
- [ ] Do not discard an already-available exit result.

Tests:

### `shutdown_timeout_below_derived_minimum_is_rejected`

- [ ] Test values below 500 ms and below `8 * poll interval` if those differ.
- [ ] Test the exact minimum is accepted.
- [ ] Assert no secret in error output.

### `process_cleanup_obeys_one_total_budget`

- [ ] Arrange a stuck worker and live bridge.
- [ ] Assert total elapsed cleanup stays within the declared budget plus a documented scheduler tolerance.
- [ ] Assert worker timeout remains primary absent server error.

### `zero_remaining_budget_observes_completed_bridge_before_detach`

- [ ] Arrange bridge exit before zero-budget handling.
- [ ] Assert it is joined and panic/success is retained.
- [ ] Arrange an active bridge and assert deliberate detach.

Documentation:

- [ ] Update operator guide, deployment examples, and release notes.
- [ ] Record direct wake-up as deferred; do not add `crossbeam-channel` or redesign the worker event channel.

Acceptance:

- [ ] Process cleanup has one honest total bound.
- [ ] Zero-budget handling is observable and does not discard completed results.

---

## CR7. Derive startup cleanup from one total budget

- [ ] Establish one startup deadline before acknowledgement wait.
- [ ] On timeout, set shutdown flag first.
- [ ] Send the best-effort permit-counted compatibility nudge.
- [ ] Compute remaining budget with saturating arithmetic.
- [ ] Use only the remainder for exit observation/cleanup.
- [ ] Preserve timeout versus worker panic/join-failure distinction.

Zero-remainder startup path:

- [ ] Perform a nonblocking exit check.
- [ ] Join if the worker already exited.
- [ ] Detach only if still active.
- [ ] Return `DesktopError::Timeout` for an active worker.
- [ ] Do not silently discard an already-available panic.

Tests:

- [ ] Prove total startup latency is bounded by one configured budget plus documented scheduler tolerance.
- [ ] Prove zero remainder detaches an active worker.
- [ ] Prove zero remainder still observes an already-exited/panicked worker.
- [ ] Preserve existing startup-timeout and startup-panic regressions.

Documentation:

- [ ] Update doc comments and operator guide.
- [ ] Audit Compose healthchecks and deployment timing against the shorter effective bound.
- [ ] Add release-note entry for the behavior change.

Acceptance:

- [ ] `startup_timeout` means the complete startup operation budget.

---

## CR8. Remove unreachable shutdown error arms

- [ ] Narrow the worker wait result to success/timeout semantics.
- [ ] Remove generic unreachable `Err(error) => Err(error)` from `DesktopWorker::shutdown`.
- [ ] Narrow the bridge wait result similarly.
- [ ] Remove generic unreachable forwarding from `EventBridge::shutdown`.
- [ ] Ensure any future third outcome requires explicit diagnostics and tests.
- [ ] Record static baseline evidence.
- [ ] Keep strict Clippy clean.

Acceptance:

- [ ] No unreachable catch-all forwards a future outcome silently.

---

## CR9. Zeroize project-owned VNC password copies

Secret abstraction:

- [ ] Introduce a shared non-`Debug`, zeroizing secret type.
- [ ] Design it to support future shared API-token storage.
- [ ] Adopt it for VNC password now.
- [ ] Leave API bearer-token comparison/storage behavior unchanged.
- [ ] Record API-token adoption as a deferred follow-up.

Copy inventory:

- [ ] secret-file read buffer;
- [ ] `ControllerConfig`;
- [ ] `NativeClientConfig`;
- [ ] `WorkerSettings` and clones;
- [ ] worker closure capture;
- [ ] temporary `CString` in `NativeClient::connect`;
- [ ] shim-owned duplicated password;
- [ ] callback-returned allocation owned by LibVNCClient.

Rust handling:

- [ ] Minimize clones and document unavoidable copies.
- [ ] Ensure temporary `CString` bytes are scrubbed before release.
- [ ] Confirm no password-bearing type implements `Debug`.
- [ ] Add a live-buffer scrub-helper test.
- [ ] Add instrumented proof that wrapper `Drop` invokes scrubbing.
- [ ] Never read freed memory.
- [ ] Never print the sentinel secret on failure.

C handling:

- [ ] Implement `vrc_secure_scrub(void *, size_t)` with a `volatile unsigned char *` loop.
- [ ] Scrub shim-owned password storage before `free`.
- [ ] Scrub every other project-owned native copy before release.
- [ ] Keep `_POSIX_C_SOURCE 200809L`, `-std=c11`, `-pedantic`, and `-Werror` intact.
- [ ] Do not introduce `_GNU_SOURCE`/`_DEFAULT_SOURCE` solely for scrubbing.
- [ ] Do not rely on `explicit_bzero` or optional `memset_s`.

Third-party residual:

- [ ] Inspect exact pinned Debian LibVNCClient source for `GetPassword` ownership/free behavior.
- [ ] Record exact package/source version and relevant source location.
- [ ] Record whether the callback-returned allocation is scrubbed before free.
- [ ] If not scrubbed, document it as a third-party residual rather than claiming closure.
- [ ] Record VNC DES eight-byte password truncation/library-copy implications where relevant.

Documentation:

- [ ] Update `SECURITY.md` or secret-lifecycle documentation.
- [ ] State: all project-owned VNC password copies are scrubbed; third-party behavior is verified and documented separately.

Acceptance:

- [ ] Every project-owned copy is scrubbed before release.
- [ ] No undefined-behavior test or overstated third-party claim remains.

---

## CR10. Replace vacuous privacy assertions with path-specific JSON-log tests

Infrastructure:

- [ ] Add `capture_json_logs` to test support.
- [ ] Parse each JSON record and inspect field values.
- [ ] Keep raw-rendered-string checks only as secondary defense.

Test 1: input release

- [ ] Press a distinctive key and mouse button at a distinctive coordinate through the real worker.
- [ ] Force release failure.
- [ ] Assert expected incomplete/abandoned diagnostics.
- [ ] Assert only counts/booleans are present; key and coordinate sentinels are absent.

Test 2: typed text and clipboard

- [ ] Send distinctive text and clipboard sentinels through real validation/failure paths.
- [ ] Assert no logged error field contains either value.
- [ ] If baseline errors do not carry input, record this as a passing regression guard rather than fabricating a leak.

Test 3: VNC password

- [ ] Drive a failing native connection with a sentinel password.
- [ ] Assert controller/native structured fields contain no sentinel.

Test 4: bearer tokens

- [ ] Drive correct and incorrect sentinel tokens through real HTTP authentication/access middleware.
- [ ] Assert neither configured nor presented token appears.
- [ ] Assert authorization is represented only by the redacted marker or payload-free metadata.

Audit:

- [ ] Remove generic-noun privacy assertions.
- [ ] For every sentinel assertion, document the production mechanism carrying the value.
- [ ] Ensure benign fields such as `framebuffer_revision` or `clipboard_revision` do not fail privacy tests.

Acceptance:

- [ ] A real value leak fails the relevant path test.
- [ ] A sentinel never tested on a path that cannot carry it.

---

## CR11. Measure framebuffer costs reproducibly; do not optimize

Utility:

- [ ] Create a committed measurement utility under `tools/framebuffer_measurement/` or `tests/measurement/framebuffer/`.
- [ ] Include a README with exact build/run commands.
- [ ] Record toolchain, allocator, resolution, repetitions, and output schema.
- [ ] Keep it reproducible even if excluded from normal CI.
- [ ] Do not use an uncommitted one-time script.

Measurement method:

- [ ] Run in a dedicated process with a counting global allocator.
- [ ] Measure at minimum 1920×1080.
- [ ] Measure allocation count and allocated bytes.
- [ ] Measure native framebuffer copy.
- [ ] Measure RGBX-to-RGBA conversion.
- [ ] Measure equality comparison and write-lock hold time.
- [ ] Measure `Vec<u8> -> Arc<[u8]>` behavior on the pinned toolchain.
- [ ] Separate measured facts from source-reading hypotheses.

Disposition:

- [ ] Record results in the correctness evidence.
- [ ] Correct the historical performance record without rewriting valid historical CI claims.
- [ ] Make **no framebuffer code optimization in this pass**.
- [ ] If measurements justify work, create a separate performance spec and TODO.
- [ ] Preserve equality, revisions, timestamps, ETags, and R13 unchanged.

Acceptance:

- [ ] Results are independently reproducible from committed sources.
- [ ] No framebuffer hot-path code change is mixed into this correctness pass.

---

## CR12. Replace both sleep-only negative proofs

Test-only causal-progress hook:

- [ ] Add a `#[cfg(test)]` worker-loop iteration counter or equivalent hook.
- [ ] Ensure it does not affect production builds or timing.
- [ ] Derive the required iteration count from the fixture; do not choose an arbitrary sleep.

Convert `mismatched_native_frame_never_reaches_connected`:

- [ ] Observe multiple post-condition loop iterations.
- [ ] Assert the worker never reaches `Connected`.
- [ ] Assert `fatal_exit == false`.
- [ ] Add a positive control proving the fixture can observe a reconnect/state change when deliberately triggered.

Convert `authentication_failure_waits_for_manual_reconnect`:

- [ ] Observe multiple loop iterations after `AuthenticationFailed`.
- [ ] Assert factory call count remains one.
- [ ] Submit real `WorkerCommand::Reconnect` as positive control.
- [ ] Assert the factory is called again within a bounded deadline.

Weak-test baseline evidence:

- [ ] Inject a fault each old test claims to detect.
- [ ] Show the old sleep-based form can pass or flake under that fault.
- [ ] Record the result before replacement.

Audit:

- [ ] Audit all worker lifecycle/race tests for sleep as primary proof.
- [ ] Convert any additional case or record why a sleep is merely pacing rather than evidence.
- [ ] Give every blocked thread a bounded release path.

Acceptance:

- [ ] Negative behavior is proved by causal progress plus positive control.

---

## CR13. Preserve public, shutdown, framebuffer, and security behavior

- [ ] `HttpState::begin_shutdown()` remains HTTP shutdown authority.
- [ ] Readiness still fails closed after shutdown begins.
- [ ] Mutating routes retain existing shutdown envelope.
- [ ] No new public shutdown error is added.
- [ ] Out-of-band worker authority remains unchanged.
- [ ] Queue permit ownership and acquisition point remain unchanged.
- [ ] Event-bridge model remains unchanged except total-budget orchestration and nonblocking zero-budget observation.
- [ ] Server → worker → bridge error precedence remains unchanged.
- [ ] Identical full frames keep revision/timestamp.
- [ ] Identical dirty updates with unchanged availability keep revision/timestamp.
- [ ] Changed pixels and availability transitions retain current semantics.
- [ ] Stale/incomplete frames remain unavailable.
- [ ] R13 conditional `304` assertion remains byte-for-byte unweakened.
- [ ] API token constant-time comparison remains untouched.
- [ ] No sensitive logging is added.
- [ ] No CI/security/release gate is weakened.
- [ ] No `continue-on-error`, broad ignore, or force push is used.

Acceptance:

- [ ] Preserved behavior is verified through existing and new tests.

---

## CR14. Documentation and policy updates

- [ ] Update `docs/OPERATOR_GUIDE.md` for:
  - [ ] `VRC_SHUTDOWN_TIMEOUT_MS` total-budget semantics and derived floor;
  - [ ] startup total-budget semantics;
  - [ ] deferred direct bridge wake-up;
  - [ ] renamed submissions-in-flight metric.
- [ ] Update deployment examples and environment documentation.
- [ ] Add release notes for:
  - [ ] startup worst-case bound change;
  - [ ] new shutdown variable;
  - [ ] metric rename with no alias;
  - [ ] explicit pixel format;
  - [ ] secret-lifecycle clarification.
- [ ] Add metric/API naming-compatibility policy to the release policy.
- [ ] Document exact TSan and Miri coverage boundaries.
- [ ] Document exact `[R,G,B,X]` native format contract.
- [ ] Document password-copy inventory and third-party residual.
- [ ] Link committed framebuffer measurement utility and results.
- [ ] Record deferred follow-ups:
  - [ ] direct bridge wake-up;
  - [ ] API bearer-token secret-type adoption;
  - [ ] framebuffer optimization conditional on measurement;
  - [ ] compatibility alias only if an external consumer is identified.

Acceptance:

- [ ] Operator and security documentation state the implemented contracts accurately.

---

## CR15. Local validation

Run before pushing whenever available:

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] rustdoc with warnings denied
- [ ] framebuffer measurement utility with recorded command/output
- [ ] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [ ] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] shell syntax checks for all permanent scripts

Where Docker/VNC are available:

- [ ] desktop image suite
- [ ] native adapter/VNC suite
- [ ] WorkerHandle input E2E
- [ ] WorkerHandle text/clipboard E2E
- [ ] canonical framebuffer red/blue assertion
- [ ] decoded screenshot PNG red/blue assertion
- [ ] authenticated HTTP E2E
- [ ] Compose/persistence suite
- [ ] unchanged R13 integration

- [ ] Record every unavailable local command and exact reason.
- [ ] Do not label unavailable validation as passed.

Acceptance:

- [ ] All available checks pass.
- [ ] Unavailable surfaces are explicitly deferred to exact-SHA permanent workflows.

---

## CR16. Exact-SHA permanent validation

- [ ] Commit implementation changes intentionally.
- [ ] Push to `master` without force.
- [ ] Record implementation SHA.
- [ ] Wait for CI on that exact SHA.
- [ ] Wait for Release Gates on that exact SHA.
- [ ] Confirm CI success across:
  - [ ] repository quality;
  - [ ] desktop image;
  - [ ] native adapter;
  - [ ] WorkerHandle input;
  - [ ] WorkerHandle text/clipboard;
  - [ ] authenticated HTTP;
  - [ ] controller image/Compose/persistence;
  - [ ] unchanged R13.
- [ ] Confirm Release Gates success across:
  - [ ] static/supply-chain policy;
  - [ ] full-history Gitleaks;
  - [ ] ShellCheck/actionlint;
  - [ ] BuildKit/Compose validation;
  - [ ] cargo policy;
  - [ ] ASan;
  - [ ] existing core TSan;
  - [ ] new `controller-api` TSan coverage;
  - [ ] accurately scoped core Miri;
  - [ ] Trivy/SBOM/VEX.
- [ ] Repair root causes only; do not weaken gates or assertions.
- [ ] Do not use previous-SHA, canceled, superseded, or partial jobs as completion evidence.

Acceptance:

- [ ] Implementation SHA is fully green before final evidence edits.

---

## CR17. Final evidence and historical corrections

- [ ] Complete this TODO only after implementation validation.
- [ ] Fill the evidence block below.
- [ ] Add correction notes to prior hardening records stating:
  - [ ] prior TSan/Miri claims did not cover the concurrent crate;
  - [ ] prior framebuffer allocation/pass counts were unmeasured/incomplete;
  - [ ] valid historical CI/R13 outcomes remain valid.
- [ ] Do not rewrite historical implementation claims that remain accurate.
- [ ] Link prior records to this spec/TODO and measurement evidence.
- [ ] Commit documentation/evidence changes intentionally.
- [ ] Push without force.
- [ ] Wait for CI and Release Gates on the exact final documentation tip.
- [ ] Record external workflow run IDs; do not claim a commit embeds its own hash.

Final evidence:

```text
Starting HEAD SHA:
Implementation SHA:
Final documentation commit SHA:
Final repository-tip SHA:
Tip-validating CI run ID:
Tip-validating Release Gates run ID:

Baseline evidence:
- CR1 pre-Connected stall:
- CR2 illegal transition:
- CR3 pixel format:
- CR4 controller-api TSan:
- CR5 submissions-in-flight semantics:
- CR6 process total budget:
- CR7 startup total budget:
- CR8 unreachable arms:
- CR9 secret scrubbing:
- CR10 privacy paths:
- CR11 framebuffer measurement:
- CR12 weak sleep tests:

Secret lifecycle:
- Project-owned copies scrubbed:
- LibVNCClient-owned residual disposition:

Framebuffer measurement:
- Utility path:
- Exact command:
- Toolchain/allocator:
- Resolution/repetitions:
- Allocation count/bytes:
- Stage timings:
- Optimization follow-up disposition:

Local validation:

CI run and conclusion:
Release Gates run and conclusion:
R13 job/step and conclusion:
TSan coverage boundary:
Miri coverage boundary:
```

Acceptance:

- [ ] Same exact final tip passes CI and Release Gates.
- [ ] This TODO is the authoritative completed handoff.

---

## Final do-not-accept checklist

- [ ] No state-table widening was used to hide the stall defect.
- [ ] No repair preceded its classified evidence.
- [ ] No side-effecting transition result is discarded.
- [ ] No final `Stopped` failure is silently ignored.
- [ ] No shutdown authority or queue-accounting behavior changed.
- [ ] No permit acquisition point moved.
- [ ] No direct bridge wake-up dependency was added in this pass.
- [ ] No completed zero-budget exit result was discarded before detach.
- [ ] No pixel-format assumption remains implicit.
- [ ] No sanitizer claim exceeds actual execution.
- [ ] No misleading queue-depth name or undocumented metric type remains.
- [ ] No freed-memory zeroization test exists.
- [ ] No claim says third-party-owned password copies are scrubbed without evidence.
- [ ] No privacy sentinel is asserted on a path that cannot carry it.
- [ ] No framebuffer optimization is mixed into this pass.
- [ ] No sleep-only negative proof remains.
- [ ] No framebuffer/ETag/R13 assertion is weakened.
- [ ] No command payload, text, clipboard, key, coordinate, token, password, framebuffer byte, or screenshot is logged.
- [ ] No `continue-on-error`, broad ignore, gate downgrade, force push, or older-SHA evidence is accepted.

---

## Final acceptance

This TODO is complete only when:

- [ ] pre-`Connected` stalls recover without `Degraded`, fatal exit, or worker termination;
- [ ] illegal transitions are diagnosed and non-mutating;
- [ ] final `Stopped` handling is explicit;
- [ ] native `[R,G,B,X]` format is pinned and red/blue verified at canonical and PNG layers;
- [ ] TSan covers the concurrent crate and Miri boundary is stated accurately;
- [ ] submissions-in-flight naming and complete Prometheus metadata are correct;
- [ ] process shutdown and startup each obey one total budget;
- [ ] zero-budget paths observe already-completed exits before detach;
- [ ] unreachable shutdown arms are removed;
- [ ] project-owned VNC password copies are scrubbed and third-party residual is documented;
- [ ] structured privacy tests cover real value-carrying paths;
- [ ] framebuffer costs are measured reproducibly with no optimization in this pass;
- [ ] both known sleep-only tests use causal progress and positive controls;
- [ ] preserved HTTP, worker, framebuffer, WebSocket, input, ETag, and R13 behavior remains green;
- [ ] exact final repository tip passes CI and Release Gates.

## Claude Code final report template

```text
Correctness review fix status: COMPLETE / INCOMPLETE

Starting SHA:
Implementation SHA:
Final documentation SHA:
Final repository-tip SHA:
Tip-validating run IDs:

Baseline evidence by CR item:

Stall recovery:
- Pre-Connected behavior:
- Connected behavior preserved:

State transitions:
- Diagnostic:
- fatal_exit ownership:
- schedule_reconnect legality:
- final Stopped handling:

Pixel format:
- Exact shim fields:
- Canonical red/blue result:
- PNG red/blue result:

Sanitizers:
- controller-api TSan command and result:
- Escalation level used:
- Miri boundary:

Metric semantics:
- Rust/API rename:
- Prometheus rename:
- HELP/TYPE coverage:
- Compatibility decision:

Timeouts:
- Shutdown total budget/floor:
- Zero-budget bridge behavior:
- Startup total budget:
- Zero-budget worker behavior:

Secrets:
- Shared type:
- Project-owned copies scrubbed:
- LibVNCClient residual:
- API token deferral:

Privacy tests:

Framebuffer measurement:
- Utility and command:
- Results:
- Follow-up disposition:

Sleep-only test replacements:

Documentation and policy changes:

Local validation:

CI run and conclusion:
Release Gates run and conclusion:
R13 job and conclusion:

Remaining risks or skipped validation:
```
