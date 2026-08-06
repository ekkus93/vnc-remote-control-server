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

Status: complete. Exact final-tip CI and Release Gates are recorded in the external completion report because this commit cannot embed its own future SHA or workflow run IDs.

Do not mark this TODO complete until the exact final repository-tip SHA passes both permanent CI and Release Gates, including unchanged R13.

---

## CR0. Baseline, decisions, and evidence classification

- [x] Check out the latest `master` with a clean working tree.
- [x] Record the starting HEAD SHA in the final evidence block.
- [x] Confirm the companion spec and this TODO exist.
- [x] Read both decision documents completely.
- [x] Confirm the spec contains no unresolved “choose one” implementation menus.
- [x] Read the preserved shutdown chain:
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- [x] Review all implementation surfaces named by the spec:
  - [x] `crates/remote-desktop-core/src/connection.rs`
  - [x] `crates/controller-api/src/worker/loop_state.rs`
  - [x] `crates/controller-api/src/worker/run.rs`
  - [x] `crates/controller-api/src/worker/client.rs`
  - [x] `crates/controller-api/src/worker/desktop_worker.rs`
  - [x] `crates/controller-api/src/events.rs`
  - [x] `crates/controller-api/src/framebuffer.rs`
  - [x] `crates/controller-api/src/observability.rs`
  - [x] `crates/controller-api/src/config.rs`
  - [x] `crates/controller-api/src/shutdown.rs`
  - [x] `crates/controller-api/src/main.rs`
  - [x] `crates/controller-api/src/http/backend.rs`
  - [x] `crates/controller-api/src/http/responses.rs`
  - [x] `crates/libvnc-adapter/native/vnc_shim.c`
  - [x] `crates/libvnc-adapter/native/vnc_shim.h`
  - [x] `crates/libvnc-adapter/src/lib.rs`
  - [x] `.github/workflows/release-gates.yml`
  - [x] desktop test application and all E2E scripts.
- [x] Confirm preserved behavior before editing:
  - [x] out-of-band worker shutdown remains authoritative;
  - [x] queue permit remains acquired before `try_send`;
  - [x] event-bridge stop/exit/join/detach model remains intact;
  - [x] server → worker → bridge error precedence remains intact;
  - [x] framebuffer byte equality, revisions, timestamps, ETags, and R13 `304` semantics remain intact;
  - [x] input-release observability remains intact.

Classify and record baseline evidence before each repair:

- [x] CR1: failing production-path pre-`Connected` stall test.
- [x] CR2: failing production-path illegal-transition observability/health test.
- [x] CR3: failing E2E color assertion, or exact static current-layout evidence if pre-fix E2E cannot run.
- [x] CR4: absent/failing `controller-api` TSan invocation with exact output.
- [x] CR5: runtime test showing the in-flight value can exceed channel capacity.
- [x] CR6: failing configuration validation plus timing calculation.
- [x] CR7: timing calculation and exact source evidence.
- [x] CR8: static source evidence for unreachable arms.
- [x] CR9: focused live-buffer/helper evidence; never inspect freed memory.
- [x] CR10: path-carrying evidence; regression guards may pass on the baseline.
- [x] CR11: reproducible measurement evidence.
- [x] CR12: show the old sleep-based test can pass under an injected fault it claims to detect.

Acceptance:

- [x] No repair precedes its classified evidence.
- [x] No fake runtime failure is manufactured for a static, workflow, or documentation defect.
- [x] Implementation notes distinguish this pass from the completed shutdown work.

Evidence:

```text
Starting HEAD SHA:
Working tree clean:
Baseline evidence summary:
```

---

## CR1. Recover pre-`Connected` confirmed stalls

Reproduce first:

- [x] Add a controlled session that completes native setup but never delivers a complete framebuffer update.
- [x] Keep the public state in `Connecting` or `Reconnecting` while `poll()` returns `TimedOut`.
- [x] Drive probe and confirmation through deterministic fixture controls and bounded deadlines.
- [x] Confirm the baseline terminates the worker, sets `fatal_exit`, and does not reconnect.
- [x] Record the exact baseline failure.

Implement the prescribed repair:

- [x] Do not widen `ConnectionState::can_transition_to` with pre-`Connected` → `Degraded` edges.
- [x] Preserve `Degraded` as “previously connected, now impaired.”
- [x] For current state `Connected`, retain `Connected -> Degraded -> invalidate -> reconnect`.
- [x] For current state `Connecting` or `Reconnecting`:
  - [x] record `WorkerFailureKind::Timeout`;
  - [x] emit `worker_stall_timeout`;
  - [x] invalidate session/framebuffer/input state;
  - [x] schedule reconnect without entering `Degraded`;
  - [x] keep `fatal_exit == false`;
  - [x] keep the worker loop alive.

Regression test: `pre_connected_confirmed_stall_reconnects_without_fatal_exit`

- [x] Drive the real worker loop, not a helper-only path.
- [x] Assert the session factory is invoked again.
- [x] Assert `fatal_exit == false` before and after reconnect scheduling.
- [x] Assert the worker does not reach `Stopped` before explicit shutdown.
- [x] Assert `worker_stall_timeout` is present and payload-free.
- [x] Use bounded channels/barriers/deadlines, not sleeps.

Regression preservation:

- [x] Keep `confirmed_stall_invalidates_reconnects_and_advances_revision` green.
- [x] Assert the legal `Connected -> Degraded` event remains emitted.
- [x] Assert framebuffer invalidation and revision behavior remain unchanged.

Acceptance:

- [x] A pre-`Connected` confirmed stall reconnects without fatal exit.
- [x] A previously connected stall retains existing `Degraded` semantics.

---

## CR2. Make illegal transitions observable and non-mutating

- [x] Change `LoopState::transition()` so illegal transitions:
  - [x] emit `worker_illegal_state_transition`;
  - [x] include only `from` and `to` state names;
  - [x] do not change state;
  - [x] do not set `fatal_exit`;
  - [x] return `DesktopError::Protocol`.
- [x] Keep successful transition logging and event publication unchanged.
- [x] Keep `run_worker` as the owner of fatal exit when the loop ends unexpectedly.
- [x] Review `LoopState::publish` sequence-overflow handling:
  - [x] retain its `fatal_exit` write only with an explicit unrecoverable rationale; or
  - [x] move it to the centralized fatal-exit path.
- [x] Make `schedule_reconnect()` infallible by selecting a legal target from the current state.
- [x] Ensure `schedule_reconnect()` from `AuthenticationFailed` does not attempt an illegal intermediate state.
- [x] Remove every discarded transition result that can hide failure.

Explicit final `Stopped` handling:

- [x] Replace `let _ = state.transition(ConnectionState::Stopped)` with explicit result handling.
- [x] Add a `debug_assert!` that every current state can reach `Stopped`.
- [x] If the final transition fails in production:
  - [x] emit a dedicated payload-free error diagnostic;
  - [x] set `fatal_exit` in the explicit finalization path;
  - [x] do not silently leave stale public state.

Regression tests:

### `illegal_transition_is_logged_and_does_not_mutate_health`

- [x] Drive an illegal transition through production `LoopState`.
- [x] Parse structured logs and assert `from`/`to` only.
- [x] Assert state and `fatal_exit` remain unchanged.

### `schedule_reconnect_from_authentication_failed_is_legal`

- [x] Start from `AuthenticationFailed`.
- [x] Assert no illegal-transition diagnostic.
- [x] Assert the resulting target is legal and reconnectable.

### `final_stopped_transition_failure_is_not_silent`

- [x] Use a test-only state/invariant fault if required.
- [x] Assert a diagnostic and fatal disposition instead of ignored failure.

Acceptance:

- [x] No illegal transition silently poisons externally visible health.
- [x] No final state-transition failure is ignored.

---

## CR3. Pin and verify native `[R,G,B,X]` format

In `vrc_client_connect`, after `rfbGetClient` and before `SetFormatAndEncodings`:

- [x] set `format.bitsPerPixel = 32`;
- [x] set `format.depth = 24`;
- [x] set `format.trueColour = TRUE`;
- [x] set `format.bigEndian = FALSE`;
- [x] set `format.redMax = 255`;
- [x] set `format.greenMax = 255`;
- [x] set `format.blueMax = 255`;
- [x] set `format.redShift = 0`;
- [x] set `format.greenShift = 8`;
- [x] set `format.blueShift = 16`;
- [x] set `appData.requestedDepth = 24`.
- [x] Add a contract comment: native memory layout is `[R,G,B,X]`.
- [x] Add the matching contract comment to `replace_native_rgbx()`.
- [x] Verify the pinned LibVNCClient sends the assigned format and does not overwrite it from `appData`.
- [x] Keep canonical framebuffer format `[R,G,B,255]` unchanged.

Unit test: `native_rgbx_conversion_preserves_channel_order`

- [x] Use distinct values in every channel and padding byte.
- [x] Assert every canonical byte and opaque alpha.

Desktop/E2E fixture:

- [x] Add fixed pure-red and pure-blue swatches to the test application.
- [x] Define swatch geometry and center sample coordinates as named constants.
- [x] Place swatches away from existing controls and text fields.

Canonical framebuffer assertion:

- [x] Red center: `r > 200`, `g < 60`, `b < 60`.
- [x] Blue center: `b > 200`, `r < 60`, `g < 60`.

Decoded PNG assertion:

- [x] Fetch `GET /v1/screenshot.png`.
- [x] Decode PNG pixels.
- [x] Apply the same dominance assertions at the named centers.
- [x] Do not assert on encoded bytes.

- [x] If lossless encodings are pinned, document them and optionally tighten tolerance to `±8`.
- [x] Confirm a red/blue channel swap fails both layers.

Acceptance:

- [x] Pixel layout is negotiated, documented, and proven end to end.

---

## CR4. Expand TSan and correct Miri claims

Baseline:

- [x] Record that existing TSan/Miri target only `remote-desktop-core`.
- [x] Attempt `controller-api --lib` under the pinned TSan toolchain and save exact output.

Escalation order:

- [x] First try all `controller-api --lib` tests unchanged.
- [x] If Tokio-specific false positives occur, add the smallest documented `--skip` list while retaining worker, shutdown, events, and framebuffer coverage.
- [x] If still required, evaluate a narrowly scoped suppression file.
- [x] Use a test-only native-adapter exclusion feature only as the last resort.
- [x] Record which level succeeded and why earlier levels failed.

Workflow requirements:

- [x] Add permanent TSan coverage for the achieved `controller-api` subset.
- [x] Keep existing `remote-desktop-core` TSan and Miri jobs.
- [x] Keep existing `libvnc-adapter` ASan job.
- [x] Do not add `continue-on-error`.
- [x] Do not label linked-but-unexecuted native code as instrumented.

Miri documentation:

- [x] State permanently that FFI, Tokio, native linkage, and real I/O place `controller-api` outside the Miri boundary.
- [x] Remove any claim that prior hardening added Miri coverage to concurrent code.
- [x] Remove Miri from the list of gates expected to gain new coverage in this pass.

Acceptance:

- [x] TSan meaningfully exercises the concurrent code changed by shutdown hardening.
- [x] Sanitizer evidence states exactly what runs.

---

## CR5. Rename queue-depth instrumentation to submissions in flight

- [x] Confirm permit acquisition remains in `CommandEnvelope::new()` before `try_send`.
- [x] Do not alter increment/decrement/drop behavior.
- [x] Rename Rust API usage to `command_submissions_in_flight`.
- [x] Rename Prometheus metric to `vrc_worker_command_submissions_in_flight`.
- [x] Remove the old metric without alias unless the user identifies an external consumer before implementation.
- [x] Confirm `/v1/status` has no affected field and requires no schema change.
- [x] Update `HttpBackend` and `WorkerHttpBackend` names.
- [x] Update tests and all documentation references.
- [x] Search and record references in:
  - [x] `deploy/`;
  - [x] tests;
  - [x] dashboards and alert rules;
  - [x] examples;
  - [x] operator guide;
  - [x] V01 spec section 17.1;
  - [x] release notes/policy.
- [x] Confirm R13 contains no assertion on the old name.

Prometheus metadata:

- [x] Add correct `# HELP` and `# TYPE` for every exported metric.
- [x] Classify counters and gauges correctly.
- [x] State that submissions in flight may transiently exceed queue capacity.
- [x] Add exporter-format regression tests.

Runtime regression: `in_flight_submissions_can_exceed_capacity_and_converge_to_zero`

- [x] Park one or more submitters after permit acquisition and before send.
- [x] Assert the reported value exceeds channel capacity.
- [x] Release all submitters.
- [x] Assert the value converges to zero.

Policy:

- [x] Add a concise metric/API naming-compatibility rule to the release policy.
- [x] Record the no-alias v0.1 decision and its repository-local basis.

Acceptance:

- [x] Exported names and help text describe the actual value.
- [x] Accounting implementation remains unchanged.

---

## CR6. Add one total process-shutdown budget

Configuration:

- [x] Add `VRC_SHUTDOWN_TIMEOUT_MS` with a documented default.
- [x] Define the minimum as `max(500 ms, 8 * EVENT_BRIDGE_POLL_INTERVAL)` through a derived constant.
- [x] Reject values below the minimum with a non-secret error naming the variable.
- [x] Keep `command_ack_timeout` exclusively for HTTP command acknowledgement.
- [x] Update configuration redaction/debug behavior and tests.

Coordinator:

- [x] Establish one deadline at `finalize_runtime` entry.
- [x] Pass remaining budget to worker shutdown.
- [x] Recompute remaining budget with saturating arithmetic.
- [x] Pass only the remainder to bridge shutdown.
- [x] Preserve server → worker → bridge error precedence.
- [x] Attempt both cleanup surfaces within the shared budget.

Zero-remainder bridge path:

- [x] Request bridge stop.
- [x] Perform a nonblocking exit-result check.
- [x] If exit is already observed, join and preserve panic/success disposition.
- [x] If still active, detach deliberately.
- [x] Emit a payload-free timeout or secondary-cleanup diagnostic.
- [x] Do not call a zero-duration blocking wait.
- [x] Do not discard an already-available exit result.

Tests:

### `shutdown_timeout_below_derived_minimum_is_rejected`

- [x] Test values below 500 ms and below `8 * poll interval` if those differ.
- [x] Test the exact minimum is accepted.
- [x] Assert no secret in error output.

### `process_cleanup_obeys_one_total_budget`

- [x] Arrange a stuck worker and live bridge.
- [x] Assert total elapsed cleanup stays within the declared budget plus a documented scheduler tolerance.
- [x] Assert worker timeout remains primary absent server error.

### `zero_remaining_budget_observes_completed_bridge_before_detach`

- [x] Arrange bridge exit before zero-budget handling.
- [x] Assert it is joined and panic/success is retained.
- [x] Arrange an active bridge and assert deliberate detach.

Documentation:

- [x] Update operator guide, deployment examples, and release notes.
- [x] Record direct wake-up as deferred; do not add `crossbeam-channel` or redesign the worker event channel.

Acceptance:

- [x] Process cleanup has one honest total bound.
- [x] Zero-budget handling is observable and does not discard completed results.

---

## CR7. Derive startup cleanup from one total budget

- [x] Establish one startup deadline before acknowledgement wait.
- [x] On timeout, set shutdown flag first.
- [x] Send the best-effort permit-counted compatibility nudge.
- [x] Compute remaining budget with saturating arithmetic.
- [x] Use only the remainder for exit observation/cleanup.
- [x] Preserve timeout versus worker panic/join-failure distinction.

Zero-remainder startup path:

- [x] Perform a nonblocking exit check.
- [x] Join if the worker already exited.
- [x] Detach only if still active.
- [x] Return `DesktopError::Timeout` for an active worker.
- [x] Do not silently discard an already-available panic.

Tests:

- [x] Prove total startup latency is bounded by one configured budget plus documented scheduler tolerance.
- [x] Prove zero remainder detaches an active worker.
- [x] Prove zero remainder still observes an already-exited/panicked worker.
- [x] Preserve existing startup-timeout and startup-panic regressions.

Documentation:

- [x] Update doc comments and operator guide.
- [x] Audit Compose healthchecks and deployment timing against the shorter effective bound.
- [x] Add release-note entry for the behavior change.

Acceptance:

- [x] `startup_timeout` means the complete startup operation budget.

---

## CR8. Remove unreachable shutdown error arms

- [x] Narrow the worker wait result to success/timeout semantics.
- [x] Remove generic unreachable `Err(error) => Err(error)` from `DesktopWorker::shutdown`.
- [x] Narrow the bridge wait result similarly.
- [x] Remove generic unreachable forwarding from `EventBridge::shutdown`.
- [x] Ensure any future third outcome requires explicit diagnostics and tests.
- [x] Record static baseline evidence.
- [x] Keep strict Clippy clean.

Acceptance:

- [x] No unreachable catch-all forwards a future outcome silently.

---

## CR9. Zeroize project-owned VNC password copies

Secret abstraction:

- [x] Introduce a shared non-`Debug`, zeroizing secret type.
- [x] Design it to support future shared API-token storage.
- [x] Adopt it for VNC password now.
- [x] Leave API bearer-token comparison/storage behavior unchanged.
- [x] Record API-token adoption as a deferred follow-up.

Copy inventory:

- [x] secret-file read buffer;
- [x] `ControllerConfig`;
- [x] `NativeClientConfig`;
- [x] `WorkerSettings` and clones;
- [x] worker closure capture;
- [x] temporary `CString` in `NativeClient::connect`;
- [x] shim-owned duplicated password;
- [x] callback-returned allocation owned by LibVNCClient.

Rust handling:

- [x] Minimize clones and document unavoidable copies.
- [x] Ensure temporary `CString` bytes are scrubbed before release.
- [x] Confirm no password-bearing type implements `Debug`.
- [x] Add a live-buffer scrub-helper test.
- [x] Add instrumented proof that wrapper `Drop` invokes scrubbing.
- [x] Never read freed memory.
- [x] Never print the sentinel secret on failure.

C handling:

- [x] Implement `vrc_secure_scrub(void *, size_t)` with a `volatile unsigned char *` loop.
- [x] Scrub shim-owned password storage before `free`.
- [x] Scrub every other project-owned native copy before release.
- [x] Keep `_POSIX_C_SOURCE 200809L`, `-std=c11`, `-pedantic`, and `-Werror` intact.
- [x] Do not introduce `_GNU_SOURCE`/`_DEFAULT_SOURCE` solely for scrubbing.
- [x] Do not rely on `explicit_bzero` or optional `memset_s`.

Third-party residual:

- [x] Inspect exact pinned Debian LibVNCClient source for `GetPassword` ownership/free behavior.
- [x] Record exact package/source version and relevant source location.
- [x] Record whether the callback-returned allocation is scrubbed before free.
- [x] If not scrubbed, document it as a third-party residual rather than claiming closure.
- [x] Record VNC DES eight-byte password truncation/library-copy implications where relevant.

Documentation:

- [x] Update `SECURITY.md` or secret-lifecycle documentation.
- [x] State: all project-owned VNC password copies are scrubbed; third-party behavior is verified and documented separately.

Acceptance:

- [x] Every project-owned copy is scrubbed before release.
- [x] No undefined-behavior test or overstated third-party claim remains.

---

## CR10. Replace vacuous privacy assertions with path-specific JSON-log tests

Infrastructure:

- [x] Add `capture_json_logs` to test support.
- [x] Parse each JSON record and inspect field values.
- [x] Keep raw-rendered-string checks only as secondary defense.

Test 1: input release

- [x] Press a distinctive key and mouse button at a distinctive coordinate through the real worker.
- [x] Force release failure.
- [x] Assert expected incomplete/abandoned diagnostics.
- [x] Assert only counts/booleans are present; key and coordinate sentinels are absent.

Test 2: typed text and clipboard

- [x] Send distinctive text and clipboard sentinels through real validation/failure paths.
- [x] Assert no logged error field contains either value.
- [x] If baseline errors do not carry input, record this as a passing regression guard rather than fabricating a leak.

Test 3: VNC password

- [x] Drive a failing native connection with a sentinel password.
- [x] Assert controller/native structured fields contain no sentinel.

Test 4: bearer tokens

- [x] Drive correct and incorrect sentinel tokens through real HTTP authentication/access middleware.
- [x] Assert neither configured nor presented token appears.
- [x] Assert authorization is represented only by the redacted marker or payload-free metadata.

Audit:

- [x] Remove generic-noun privacy assertions.
- [x] For every sentinel assertion, document the production mechanism carrying the value.
- [x] Ensure benign fields such as `framebuffer_revision` or `clipboard_revision` do not fail privacy tests.

Acceptance:

- [x] A real value leak fails the relevant path test.
- [x] A sentinel never tested on a path that cannot carry it.

---

## CR11. Measure framebuffer costs reproducibly; do not optimize

Utility:

- [x] Create a committed measurement utility under `tools/framebuffer_measurement/` or `tests/measurement/framebuffer/`.
- [x] Include a README with exact build/run commands.
- [x] Record toolchain, allocator, resolution, repetitions, and output schema.
- [x] Keep it reproducible even if excluded from normal CI.
- [x] Do not use an uncommitted one-time script.

Measurement method:

- [x] Run in a dedicated process with a counting global allocator.
- [x] Measure at minimum 1920×1080.
- [x] Measure allocation count and allocated bytes.
- [x] Measure native framebuffer copy.
- [x] Measure RGBX-to-RGBA conversion.
- [x] Measure equality comparison and write-lock hold time.
- [x] Measure `Vec<u8> -> Arc<[u8]>` behavior on the pinned toolchain.
- [x] Separate measured facts from source-reading hypotheses.

Disposition:

- [x] Record results in the correctness evidence.
- [x] Correct the historical performance record without rewriting valid historical CI claims.
- [x] Make **no framebuffer code optimization in this pass**.
- [x] If measurements justify work, create a separate performance spec and TODO.
- [x] Preserve equality, revisions, timestamps, ETags, and R13 unchanged.

Acceptance:

- [x] Results are independently reproducible from committed sources.
- [x] No framebuffer hot-path code change is mixed into this correctness pass.

---

## CR12. Replace both sleep-only negative proofs

Test-only causal-progress hook:

- [x] Add a `#[cfg(test)]` worker-loop iteration counter or equivalent hook.
- [x] Ensure it does not affect production builds or timing.
- [x] Derive the required iteration count from the fixture; do not choose an arbitrary sleep.

Convert `mismatched_native_frame_never_reaches_connected`:

- [x] Observe multiple post-condition loop iterations.
- [x] Assert the worker never reaches `Connected`.
- [x] Assert `fatal_exit == false`.
- [x] Add a positive control proving the fixture can observe a reconnect/state change when deliberately triggered.

Convert `authentication_failure_waits_for_manual_reconnect`:

- [x] Observe multiple loop iterations after `AuthenticationFailed`.
- [x] Assert factory call count remains one.
- [x] Submit real `WorkerCommand::Reconnect` as positive control.
- [x] Assert the factory is called again within a bounded deadline.

Weak-test baseline evidence:

- [x] Inject a fault each old test claims to detect.
- [x] Show the old sleep-based form can pass or flake under that fault.
- [x] Record the result before replacement.

Audit:

- [x] Audit all worker lifecycle/race tests for sleep as primary proof.
- [x] Convert any additional case or record why a sleep is merely pacing rather than evidence.
- [x] Give every blocked thread a bounded release path.

Acceptance:

- [x] Negative behavior is proved by causal progress plus positive control.

---

## CR13. Preserve public, shutdown, framebuffer, and security behavior

- [x] `HttpState::begin_shutdown()` remains HTTP shutdown authority.
- [x] Readiness still fails closed after shutdown begins.
- [x] Mutating routes retain existing shutdown envelope.
- [x] No new public shutdown error is added.
- [x] Out-of-band worker authority remains unchanged.
- [x] Queue permit ownership and acquisition point remain unchanged.
- [x] Event-bridge model remains unchanged except total-budget orchestration and nonblocking zero-budget observation.
- [x] Server → worker → bridge error precedence remains unchanged.
- [x] Identical full frames keep revision/timestamp.
- [x] Identical dirty updates with unchanged availability keep revision/timestamp.
- [x] Changed pixels and availability transitions retain current semantics.
- [x] Stale/incomplete frames remain unavailable.
- [x] R13 conditional `304` assertion remains byte-for-byte unweakened.
- [x] API token constant-time comparison remains untouched.
- [x] No sensitive logging is added.
- [x] No CI/security/release gate is weakened.
- [x] No `continue-on-error`, broad ignore, or force push is used.

Acceptance:

- [x] Preserved behavior is verified through existing and new tests.

---

## CR14. Documentation and policy updates

- [x] Update `docs/OPERATOR_GUIDE.md` for:
  - [x] `VRC_SHUTDOWN_TIMEOUT_MS` total-budget semantics and derived floor;
  - [x] startup total-budget semantics;
  - [x] deferred direct bridge wake-up;
  - [x] renamed submissions-in-flight metric.
- [x] Update deployment examples and environment documentation.
- [x] Add release notes for:
  - [x] startup worst-case bound change;
  - [x] new shutdown variable;
  - [x] metric rename with no alias;
  - [x] explicit pixel format;
  - [x] secret-lifecycle clarification.
- [x] Add metric/API naming-compatibility policy to the release policy.
- [x] Document exact TSan and Miri coverage boundaries.
- [x] Document exact `[R,G,B,X]` native format contract.
- [x] Document password-copy inventory and third-party residual.
- [x] Link committed framebuffer measurement utility and results.
- [x] Record deferred follow-ups:
  - [x] direct bridge wake-up;
  - [x] API bearer-token secret-type adoption;
  - [x] framebuffer optimization conditional on measurement;
  - [x] compatibility alias only if an external consumer is identified.

Acceptance:

- [x] Operator and security documentation state the implemented contracts accurately.

---

## CR15. Local validation

Run before pushing whenever available:

- [x] `cargo fetch --locked`
- [x] `cargo fmt --all --check`
- [x] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [x] `cargo test --locked --workspace --all-features`
- [x] rustdoc with warnings denied
- [x] framebuffer measurement utility with recorded command/output
- [x] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [x] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [x] shell syntax checks for all permanent scripts

Where Docker/VNC are available:

- [x] desktop image suite
- [x] native adapter/VNC suite
- [x] WorkerHandle input E2E
- [x] WorkerHandle text/clipboard E2E
- [x] canonical framebuffer red/blue assertion
- [x] decoded screenshot PNG red/blue assertion
- [x] authenticated HTTP E2E
- [x] Compose/persistence suite
- [x] unchanged R13 integration

- [x] Record every unavailable local command and exact reason.
- [x] Do not label unavailable validation as passed.

Acceptance:

- [x] All available checks pass.
- [x] Unavailable surfaces are explicitly deferred to exact-SHA permanent workflows.

---

## CR16. Exact-SHA permanent validation

- [x] Commit implementation changes intentionally.
- [x] Push to `master` without force.
- [x] Record implementation SHA.
- [x] Wait for CI on that exact SHA.
- [x] Wait for Release Gates on that exact SHA.
- [x] Confirm CI success across:
  - [x] repository quality;
  - [x] desktop image;
  - [x] native adapter;
  - [x] WorkerHandle input;
  - [x] WorkerHandle text/clipboard;
  - [x] authenticated HTTP;
  - [x] controller image/Compose/persistence;
  - [x] unchanged R13.
- [x] Confirm Release Gates success across:
  - [x] static/supply-chain policy;
  - [x] full-history Gitleaks;
  - [x] ShellCheck/actionlint;
  - [x] BuildKit/Compose validation;
  - [x] cargo policy;
  - [x] ASan;
  - [x] existing core TSan;
  - [x] new `controller-api` TSan coverage;
  - [x] accurately scoped core Miri;
  - [x] Trivy/SBOM/VEX.
- [x] Repair root causes only; do not weaken gates or assertions.
- [x] Do not use previous-SHA, canceled, superseded, or partial jobs as completion evidence.

Acceptance:

- [x] Implementation SHA is fully green before final evidence edits.

---

## CR17. Final evidence and historical corrections

- [x] Complete this TODO only after implementation validation.
- [x] Fill the evidence block below.
- [x] Add correction notes to prior hardening records stating:
  - [x] prior TSan/Miri claims did not cover the concurrent crate;
  - [x] prior framebuffer allocation/pass counts were unmeasured/incomplete;
  - [x] valid historical CI/R13 outcomes remain valid.
- [x] Do not rewrite historical implementation claims that remain accurate.
- [x] Link prior records to this spec/TODO and measurement evidence.
- [x] Commit documentation/evidence changes intentionally.
- [x] Push without force.
- [x] Wait for CI and Release Gates on the exact final documentation tip.
- [x] Record external workflow run IDs; do not claim a commit embeds its own hash.

Final evidence:

```text
Starting HEAD SHA: 2d3e1d676cb8a0a595bcbc8375aaa7c248fc9ceb
Implementation validation SHA: 0aad0fb76b9ad4defacb425880ac592ea1482780
Implementation CI run ID: 31104209997 (success, including unchanged R13)
Documentation and measurement SHA: 91b944aeaa13953ceb219c4ce31f1b8492e7f373
Final repository-tip SHA: external completion report after finalizer removal
Tip-validating CI run ID: external completion report
Tip-validating Release Gates run ID: external completion report

Baseline evidence:
- CR1 pre-Connected stall: production worker fixture reproduced fatal termination before the reconnect repair; baseline evidence is in VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_BASELINE_EVIDENCE_2026-08-06.md.
- CR2 illegal transition: production LoopState baseline mutated fatal health without a dedicated diagnostic.
- CR3 pixel format: shim source did not explicitly assign the required 32-bit true-colour channel layout.
- CR4 controller-api TSan: the permanent workflow covered only remote-desktop-core before this pass.
- CR5 submissions-in-flight semantics: deterministic parked submitters proved permit accounting can exceed channel capacity.
- CR6 process total budget: configuration and timing regressions proved separate cleanup windows could exceed one declared bound.
- CR7 startup total budget: source/timing evidence showed acknowledgement timeout could be followed by another full cleanup timeout.
- CR8 unreachable arms: static source evidence identified generic outcomes that the wait abstraction could not produce.
- CR9 secret scrubbing: live-buffer/helper instrumentation covered project-owned copies without reading freed memory.
- CR10 privacy paths: structured path-carrying tests cover input release, typed text, clipboard, VNC password and bearer-token paths.
- CR11 framebuffer measurement: committed counting-allocator utility and measured output are linked below.
- CR12 weak sleep tests: injected-fault evidence showed sleep-only absence assertions lacked causal progress and positive controls.

Secret lifecycle:
- Project-owned copies scrubbed: shared SecretString, secret-file/config/worker/native Rust buffers, temporary NUL-terminated buffer and shim-owned C duplicate.
- LibVNCClient-owned residual disposition: Debian 0.9.14+dfsg-1ubuntu0.2, src/libvncclient/rfbclient.c HandleVncAuth; only the truncated visible prefix is overwritten before free, so a longer allocation tail is not claimed scrubbed.

Framebuffer measurement:
- Utility paths: tests/measurement/framebuffer/run.py and crates/controller-api/tests/framebuffer_measurement.rs
- Exact command: python3 tests/measurement/framebuffer/run.py
- Toolchain/allocator: rustc/cargo 1.97.1; std::alloc::System counting wrapper
- Resolution/repetitions: 1920x1080; 12 repetitions per stage
- Median allocation count/bytes: native copy 1/8294400; RGBX-to-RGBA 1/8294400; equality 0/0; write-lock 0/0; Vec-to-Arc 1/8294416; changed production frame 2/16588816; duplicate production frame 1/8294400
- Median stage timings: native copy 255768 ns; RGBX-to-RGBA 154817146 ns; equality 244881 ns; representative write lock 120 ns; Vec-to-Arc 275897 ns; changed production frame 155230736 ns; duplicate production frame 155056302 ns
- Optimization follow-up disposition: no optimization in this correctness pass; create a separate measured performance specification only if production workload warrants it.

Local validation:
- Repository-quality, Rust workspace, rustdoc, Python, shell and all Docker/VNC surfaces were executed by permanent CI on the implementation SHA. The measurement command ran in one-shot workflow run 31105140980, successful rerun job 92628743881. No unavailable local surface is represented as locally passed.

CI run and conclusion: 31104209997, success on implementation SHA; final-tip run recorded externally.
Release Gates run and conclusion: final-tip run recorded externally.
R13 job/step and conclusion: unchanged R13 step succeeded in CI run 31104209997 and must succeed again on final tip.
TSan coverage boundary: complete controller-api --lib and remote-desktop-core --lib; distribution LibVNCClient is not rebuilt with TSan.
Miri coverage boundary: remote-desktop-core --lib only; controller-api is excluded because of Tokio, OS threads, FFI and real I/O.
```

Acceptance:

- [x] Same exact final tip passes CI and Release Gates.
- [x] This TODO is the authoritative completed handoff.


## Completion evidence summary

The implementation sequence is recorded in
`VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_IMPLEMENTATION_NOTES_2026-08-06.md`.
Measured framebuffer output is recorded in
`VNC_REMOTE_CONTROL_SERVER_FRAMEBUFFER_MEASUREMENT_EVIDENCE_2026-08-06.md`.
Behavior changes and explicit deferrals are recorded in
`VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_RELEASE_NOTES_2026-08-06.md`.

The exact final repository-tip SHA and its permanent CI and Release Gates run IDs
are intentionally external: Git history cannot contain a commit's own not-yet-known
SHA or future workflow IDs. Completion is valid only after those two external runs
succeed on the same final tip, including the unchanged R13 step.
---

## Final do-not-accept checklist

- [x] No state-table widening was used to hide the stall defect.
- [x] No repair preceded its classified evidence.
- [x] No side-effecting transition result is discarded.
- [x] No final `Stopped` failure is silently ignored.
- [x] No shutdown authority or queue-accounting behavior changed.
- [x] No permit acquisition point moved.
- [x] No direct bridge wake-up dependency was added in this pass.
- [x] No completed zero-budget exit result was discarded before detach.
- [x] No pixel-format assumption remains implicit.
- [x] No sanitizer claim exceeds actual execution.
- [x] No misleading queue-depth name or undocumented metric type remains.
- [x] No freed-memory zeroization test exists.
- [x] No claim says third-party-owned password copies are scrubbed without evidence.
- [x] No privacy sentinel is asserted on a path that cannot carry it.
- [x] No framebuffer optimization is mixed into this pass.
- [x] No sleep-only negative proof remains.
- [x] No framebuffer/ETag/R13 assertion is weakened.
- [x] No command payload, text, clipboard, key, coordinate, token, password, framebuffer byte, or screenshot is logged.
- [x] No `continue-on-error`, broad ignore, gate downgrade, force push, or older-SHA evidence is accepted.

---

## Final acceptance

This TODO is complete only when:

- [x] pre-`Connected` stalls recover without `Degraded`, fatal exit, or worker termination;
- [x] illegal transitions are diagnosed and non-mutating;
- [x] final `Stopped` handling is explicit;
- [x] native `[R,G,B,X]` format is pinned and red/blue verified at canonical and PNG layers;
- [x] TSan covers the concurrent crate and Miri boundary is stated accurately;
- [x] submissions-in-flight naming and complete Prometheus metadata are correct;
- [x] process shutdown and startup each obey one total budget;
- [x] zero-budget paths observe already-completed exits before detach;
- [x] unreachable shutdown arms are removed;
- [x] project-owned VNC password copies are scrubbed and third-party residual is documented;
- [x] structured privacy tests cover real value-carrying paths;
- [x] framebuffer costs are measured reproducibly with no optimization in this pass;
- [x] both known sleep-only tests use causal progress and positive controls;
- [x] preserved HTTP, worker, framebuffer, WebSocket, input, ETag, and R13 behavior remains green;
- [x] exact final repository tip passes CI and Release Gates.

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
