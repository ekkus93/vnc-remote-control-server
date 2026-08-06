# VNC Remote Control Server Correctness Review Fix TODO

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Companion specification:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_SPEC_2026-08-06.md`

Review baseline: `e9be696783e7fdfb90389cd02890d48c3e9bbd2d`

This TODO is the authoritative checklist for the correctness review fix pass. It does not supersede the shutdown work. The out-of-band shutdown flag, queue-depth permit, event-bridge stop path, bounded process cleanup, and input-release reporting are correct and must be preserved unchanged.

## Completion status

Status: not started.

Do not mark this TODO complete until the exact final repository-tip SHA passes both CI and Release Gates.

---

## CR0. Baseline and scope verification

- [ ] Check out the latest `master` with a clean working tree.
- [ ] Record the starting HEAD SHA in the evidence block below.
- [ ] Confirm the companion spec exists.
- [ ] Confirm this TODO exists.
- [ ] Read the prior shutdown chain so preserved behavior is understood before editing:
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- [ ] Review the implementation surfaces this pass touches:
  - [ ] `crates/remote-desktop-core/src/connection.rs`
  - [ ] `crates/controller-api/src/worker/loop_state.rs`
  - [ ] `crates/controller-api/src/worker/run.rs`
  - [ ] `crates/controller-api/src/worker/client.rs`
  - [ ] `crates/controller-api/src/framebuffer.rs`
  - [ ] `crates/controller-api/src/observability.rs`
  - [ ] `crates/controller-api/src/config.rs`
  - [ ] `crates/controller-api/src/shutdown.rs`
  - [ ] `crates/controller-api/src/main.rs`
  - [ ] `crates/libvnc-adapter/native/vnc_shim.c`
  - [ ] `crates/libvnc-adapter/src/lib.rs`
  - [ ] `.github/workflows/release-gates.yml`
- [ ] Confirm the completed shutdown behavior that must remain unchanged:
  - [ ] worker shutdown authority is the out-of-band `Arc<AtomicBool>`;
  - [ ] the queue-depth permit is acquired in `CommandEnvelope::new()` before `try_send`;
  - [ ] `EventBridge` stop, exit signal, bounded join, and deliberate detach are intact;
  - [ ] `finalize_runtime` error precedence is server, then worker, then bridge;
  - [ ] framebuffer byte-equality and ETag semantics are unchanged;
  - [ ] R13 behavior is unchanged.

Acceptance:

- [ ] No code is changed before each targeted defect has a failing reproduction test.
- [ ] The implementation notes distinguish this pass from the completed shutdown work.

Evidence:

```text
Starting HEAD SHA:
Working tree clean:
```

---

## CR1. Fix the pre-`Connected` confirmed-stall fatal exit

Reproduce first:

- [ ] Add a controlled session that returns `PollOutcome::TimedOut` from every poll and never delivers a complete framebuffer update, so the worker stays in `Connecting` or `Reconnecting`.
- [ ] Confirm on the baseline that the confirmed stall causes worker termination with `fatal_exit == true` and no reconnect attempt.
- [ ] Record the observed baseline failure in the evidence block.

Then fix:

- [ ] Choose and document one repair strategy:
  - [ ] extend `ConnectionState::can_transition_to` with `Connecting -> Degraded` and `Reconnecting -> Degraded`; or
  - [ ] handle the confirmed stall without a `Degraded` transition when the current state is pre-`Connected`; or
  - [ ] handle the transition failure locally the way the `connected_message` error path already does, without propagating out of `poll()`.
- [ ] Ensure the chosen strategy still invalidates the framebuffer and schedules reconnect.
- [ ] Ensure `fatal_exit` remains `false` for a stall-driven recovery.
- [ ] Ensure `run_worker` does not break out of the loop for a recoverable stall.
- [ ] Do not remove the `worker_stall_timeout` diagnostic.
- [ ] Do not change `Connected -> Degraded` behavior.

Regression tests:

### `pre_connected_confirmed_stall_reconnects_without_fatal_exit`

- [ ] Drive the real worker loop with a session that never completes a framebuffer update.
- [ ] Assert the session factory is invoked again after the confirmed stall.
- [ ] Assert `fatal_exit == false` throughout.
- [ ] Assert the worker does not reach `ConnectionState::Stopped` before shutdown is requested.
- [ ] Assert the `worker_stall_timeout` diagnostic is emitted.
- [ ] Bound the test with deadlines rather than sleeps.

### `connected_confirmed_stall_behavior_is_unchanged`

- [ ] Preserve the existing `confirmed_stall_invalidates_reconnects_and_advances_revision` expectations.
- [ ] Assert the `Connected -> Degraded` path still transitions, invalidates, and advances revision.

Acceptance:

- [ ] A pre-`Connected` stall recovers instead of terminating.
- [ ] `fatal_exit` is never set by a recoverable stall.
- [ ] The already-correct `Connected` stall path is unchanged.

---

## CR2. Make illegal state transitions observable

- [ ] Emit a structured diagnostic, such as `worker_illegal_state_transition`, whenever `LoopState::transition()` rejects a transition.
- [ ] Include only the `from` and `to` state names; include no payload.
- [ ] Review every `let _ = self.transition(..)` call site:
  - [ ] both call sites in `schedule_reconnect()`;
  - [ ] all call sites in `run_worker`.
- [ ] Replace each discarded result with explicit handling or an explicit documented reason for ignoring it.
- [ ] Decide and document whether `transition()` should continue to set `fatal_exit` as a side effect, or whether the caller should own that decision.
- [ ] Do not allow a discarded result to change `fatal_exit` silently.

Regression test:

### `illegal_transition_is_logged_and_does_not_silently_poison_health`

- [ ] Drive an illegal transition through the production `LoopState`.
- [ ] Assert the structured diagnostic is emitted.
- [ ] Assert the resulting `fatal_exit` value matches the documented decision.
- [ ] Assert no state name leaks any payload field.

Acceptance:

- [ ] No illegal transition changes `/v1/status` health without a diagnostic.
- [ ] No `transition()` result carrying a side effect is discarded without a stated reason.

---

## CR3. Negotiate and verify the native pixel format

- [ ] Set the pixel format explicitly in `vrc_client_connect` before `SetFormatAndEncodings`:
  - [ ] `bitsPerPixel`, `depth`, `trueColour`;
  - [ ] `redMax`, `greenMax`, `blueMax`;
  - [ ] `redShift`, `greenShift`, `blueShift`;
  - [ ] `bigEndian` set so the in-memory byte order is fixed independent of host endianness.
- [ ] Choose shifts that make the in-memory byte order match what `replace_native_rgbx` reads.
- [ ] Document the chosen layout in `vnc_shim.h` or `vnc_shim.c` as a contract comment.
- [ ] Document the same layout on `replace_native_rgbx` and state that it is negotiated, not assumed.
- [ ] Confirm `SetFormatAndEncodings` is still called after the format is assigned.
- [ ] Do not change the canonical RGBA8 store layout.

Regression tests:

### `native_rgbx_conversion_preserves_channel_order`

- [ ] Convert a synthetic native buffer whose channels are individually distinguishable.
- [ ] Assert each canonical RGBA byte, not just the buffer length.
- [ ] Assert the alpha byte is opaque.

### End-to-end color assertion

- [ ] Extend the desktop or native E2E path so the test application renders a known solid color.
- [ ] Assert the canonical framebuffer or decoded screenshot reports that color within an explicit tolerance.
- [ ] Do not assert on encoded PNG bytes.

Acceptance:

- [ ] The byte layout is negotiated in the shim rather than inherited from a library default.
- [ ] A channel swap fails a test.

---

## CR4. Extend ThreadSanitizer coverage to the concurrent crate

- [ ] Attempt a ThreadSanitizer run over `--package controller-api --lib`.
- [ ] Record whether the run succeeds, and if it fails, record the exact failure.
- [ ] If the native link is the obstacle, evaluate and record the disposition of each option:
  - [ ] a test-only feature that excludes the native adapter from the sanitizer build;
  - [ ] a suppression file scoped to the uninstrumented LibVNCClient shared library;
  - [ ] building LibVNCClient from source with the sanitizer enabled.
- [ ] Add the widest coverage that passes without weakening any assertion.
- [ ] Confirm the added job covers the worker, shutdown, events, and framebuffer tests.
- [ ] Record the coverage boundary in the Release Gates evidence step alongside the existing LibVNCClient note.
- [ ] Keep the existing `remote-desktop-core` TSan and Miri jobs.
- [ ] Keep the existing `libvnc-adapter` ASan job.
- [ ] Do not add `continue-on-error`.
- [ ] Do not mark this item complete on the basis of the existing `remote-desktop-core` job.

Acceptance:

- [ ] ThreadSanitizer exercises the code the shutdown passes changed, or the impossibility is documented with evidence.
- [ ] The recorded sanitizer coverage boundary matches what actually runs.

---

## CR5. Correct the queue-depth metric semantics

- [ ] Confirm the permit is still acquired at envelope construction; do not move it.
- [ ] Decide and document the reported semantics: in-flight command submissions, not channel occupancy.
- [ ] Update the Prometheus metric name or its `# HELP` text so the value is not read as queue occupancy.
- [ ] State explicitly that the value can transiently exceed `vrc_worker_command_queue_capacity`.
- [ ] Update the HTTP status or operator documentation wherever the value is described.
- [ ] Update `docs/OPERATOR_GUIDE.md` if it references the old meaning.
- [ ] If the metric name changes, record the rename in the release policy document.
- [ ] Do not change any accounting behavior.

Regression test:

### `in_flight_depth_can_exceed_capacity_and_still_converges_to_zero`

- [ ] Park a submitter between envelope construction and `try_send` using the existing before-send hook.
- [ ] Assert the reported value exceeds the configured capacity while parked.
- [ ] Release the submitter and assert the value converges to zero.

Acceptance:

- [ ] The exported metric states what it measures.
- [ ] Accounting behavior is byte-for-byte unchanged.

---

## CR6. Give process shutdown its own bounded deadline

- [ ] Add a dedicated configuration value, for example `VRC_SHUTDOWN_TIMEOUT_MS`, with a documented default.
- [ ] Validate it with a floor strictly greater than `EVENT_BRIDGE_POLL_INTERVAL`.
- [ ] Reject a configured value below that floor at load time, with a non-secret error.
- [ ] Pass the new value to `finalize_runtime` instead of `command_ack_timeout`.
- [ ] Document that worker and bridge cleanup are sequential and that the total bound is the sum.
- [ ] Consider deriving separate worker and bridge budgets from one declared total, and record the decision.
- [ ] Keep `command_ack_timeout` for its documented HTTP purpose only.
- [ ] Preserve the existing server, then worker, then bridge error precedence.
- [ ] Update `docs/OPERATOR_GUIDE.md` and `deploy/` documentation for the new variable.

Regression tests:

### `process_shutdown_timeout_below_bridge_poll_interval_is_rejected`

- [ ] Assert configuration load fails for a value below the floor.
- [ ] Assert the error names the variable and contains no secret.

### `process_cleanup_returns_within_the_declared_total_bound`

- [ ] Arrange a stuck worker and a live bridge.
- [ ] Assert complete cleanup returns within the documented total.
- [ ] Assert the worker timeout remains the primary error when no server error exists.

Acceptance:

- [ ] Process shutdown no longer depends on an HTTP command knob.
- [ ] A misconfiguration cannot produce a spurious bridge timeout on a clean shutdown.

---

## CR7. Document or derive the startup cleanup bound

- [ ] Document on `spawn_with_factory_and_startup_hook` that the worst case is the acknowledgement wait plus the cleanup wait.
- [ ] Either state the doubling explicitly, or derive the cleanup deadline from a single declared startup budget.
- [ ] If a derived budget is chosen, keep every startup path bounded.
- [ ] Keep the flag-first cleanup ordering.
- [ ] Keep the queue nudge best-effort and permit-counted.
- [ ] Keep the existing timeout and join-failure result distinction.

Acceptance:

- [ ] The effective startup bound is stated where a reader configuring `startup_timeout` will see it.
- [ ] No startup path becomes unbounded.

---

## CR8. Remove unreachable error arms

- [ ] Remove or restructure the unreachable `Err(error) => Err(error)` arm in `EventBridge::shutdown`.
- [ ] Remove or restructure the unreachable `Err(error) => Err(error)` arm in `DesktopWorker::shutdown`.
- [ ] Prefer narrowing the `wait_for_exit` return type over silently forwarding a future third outcome.
- [ ] If an arm is retained for forward compatibility, add a diagnostic so a new outcome cannot pass through undiagnosed.
- [ ] Confirm strict Clippy remains clean.

Acceptance:

- [ ] No shutdown path forwards an unreachable error without a diagnostic.

---

## CR9. Scrub secret material before release

- [ ] Zeroize the duplicated password buffer in `vrc_client_destroy` before `free`.
- [ ] Use a construct the compiler cannot elide, such as `explicit_bzero` or an equivalent guarded memset.
- [ ] Zeroize any other shim-owned copy of the password.
- [ ] On the Rust side, wrap the password so it is zeroized on drop.
- [ ] Audit `NativeClientConfig`, `WorkerSettings`, `ControllerConfig`, and the worker thread closure for retained copies.
- [ ] Confirm no password-bearing type gains a `Debug` implementation.
- [ ] Confirm the added dependency, if any, passes `cargo-deny` advisory, license, and source policy.
- [ ] Update `SECURITY.md` if it describes the previous behavior.

Regression test:

### `password_is_not_recoverable_after_client_destruction`

- [ ] Assert the Rust-side wrapper zeroizes on drop.
- [ ] Keep the assertion payload-free; do not print the secret on failure.

Acceptance:

- [ ] The VNC password is scrubbed on both sides of the FFI boundary.
- [ ] No gate is weakened by the change.

---

## CR10. Make log-privacy assertions test real leaks

- [ ] Replace generic-noun substring assertions in `shutdown_logs_incomplete_input_release_without_payloads`.
- [ ] Inject distinctive sentinel values for each category under test:
  - [ ] clipboard text;
  - [ ] typed text;
  - [ ] key value;
  - [ ] coordinate;
  - [ ] bearer token;
  - [ ] VNC password.
- [ ] Assert the absence of each sentinel, not the absence of the category word.
- [ ] Keep the existing `"CtrlLeft"` style assertion where the value itself is the secret.
- [ ] Apply the same correction to any other test asserting on category words.
- [ ] Confirm the tests still assert the presence of `worker_input_release_incomplete` and `worker_input_release_abandoned`.

Acceptance:

- [ ] A real leak fails a test.
- [ ] A benign new structured field name does not.

---

## CR11. Complete the framebuffer performance record and optimize with evidence

- [ ] Benchmark the complete per-frame path at a representative resolution, at minimum 1920x1080.
- [ ] Measure each stage separately:
  - [ ] the native copy allocation and `memcpy` in `NativeClient::framebuffer`;
  - [ ] the per-pixel conversion loop in `replace_native_rgbx`;
  - [ ] the full-frame equality comparison under the store write lock;
  - [ ] the `Vec<u8> -> Arc<[u8]>` conversion allocation and copy.
- [ ] Record measured allocation count and bytes per delivered frame.
- [ ] Record write-lock hold time.
- [ ] Optimize the per-pixel conversion loop only if the benchmark justifies it.
- [ ] If optimized, preserve exact output bytes and prove it with a byte-equality test against the current implementation.
- [ ] Evaluate reducing the number of full-frame allocations per frame and record the disposition.
- [ ] Preserve exact byte-equality duplicate detection.
- [ ] Preserve screenshot ETag stability and the R13 conditional `304` contract.
- [ ] Append the completed measurements to the final hardening record as a correction, without retroactively editing its historical claims.

Acceptance:

- [ ] The performance record accounts for every full-frame pass, not only the comparison.
- [ ] No optimization is introduced without measurement.
- [ ] Framebuffer semantics are unchanged.

---

## CR12. Replace the remaining sleep-only test

- [ ] Convert `mismatched_native_frame_never_reaches_connected` to a bounded barrier.
- [ ] Prove the exact concurrency state before asserting.
- [ ] Add an assertion that `fatal_exit == false` for the mismatched-frame path.
- [ ] Ensure the test fails quickly rather than hanging CI.
- [ ] Audit the remaining worker tests for any other sleep-only proof and record the audit result.

Acceptance:

- [ ] No worker race or lifecycle test relies on a sleep as its primary proof.

---

## CR13. Preserve HTTP, R13, framebuffer, and security behavior

- [ ] Confirm `HttpState::begin_shutdown()` remains the public HTTP shutdown authority.
- [ ] Confirm readiness fails closed after HTTP shutdown begins.
- [ ] Confirm authenticated mutating routes retain the existing shutdown error envelope.
- [ ] Confirm no new public shutdown error was added.
- [ ] Confirm screenshot ETag semantics are unchanged:
  - [ ] identical full frames keep revision and timestamp;
  - [ ] identical dirty updates with unchanged availability keep revision and timestamp;
  - [ ] changed pixels advance revision;
  - [ ] availability transitions advance or invalidate correctly;
  - [ ] stale or incomplete frames remain unavailable.
- [ ] Confirm the R13 conditional `304` assertion is unweakened.
- [ ] Confirm the out-of-band shutdown flag, queue permit, event-bridge stop path, and `finalize_runtime` precedence are unchanged.
- [ ] Confirm no new sensitive logging.
- [ ] Confirm no CI, secret-scanning, vulnerability, dependency, sanitizer, or release gate was weakened.
- [ ] Confirm no `continue-on-error` was added.
- [ ] Confirm no broad `.gitleaksignore`, Trivy, or VEX ignore was added.

Acceptance:

- [ ] All preserved behavior is verified, not assumed.

---

## CR14. Local validation

Run before pushing whenever available:

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] rustdoc with warnings denied
- [ ] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [ ] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] Run shell syntax checks:

```bash
bash -n \
  desktop/entrypoint.sh \
  desktop/healthcheck.sh \
  desktop/xstartup \
  tests/desktop/run.sh \
  tests/native/run.sh \
  tests/worker-e2e/run.sh \
  tests/worker-text-clipboard-e2e/run.sh \
  tests/http-e2e/run.sh \
  controller/healthcheck.sh \
  tests/compose/run.sh \
  tests/integration/run.sh
```

Where Docker and VNC resources are available:

- [ ] desktop Docker suite
- [ ] native Docker and VNC suite
- [ ] WorkerHandle input E2E
- [ ] WorkerHandle text and clipboard E2E, including the new color assertion
- [ ] authenticated HTTP E2E
- [ ] Compose and persistence suite
- [ ] R13 Compose integration and E2E

- [ ] Record every skipped local command and the exact reason.
- [ ] Do not label unavailable validation as passed.

Acceptance:

- [ ] All available local checks pass.
- [ ] Unavailable surfaces are explicitly deferred to exact-SHA CI.

---

## CR15. Push and exact-SHA GitHub validation

- [ ] Commit implementation changes intentionally.
- [ ] Push to `master` without force.
- [ ] Record the implementation SHA.
- [ ] Wait for CI on that exact implementation SHA.
- [ ] Wait for Release Gates on that exact implementation SHA.
- [ ] Confirm CI success across repository quality, desktop image, native adapter, WorkerHandle input, WorkerHandle text and clipboard, authenticated HTTP, controller image and Compose and persistence, and R13.
- [ ] Confirm Release Gates success across static and supply-chain policy, full-history Gitleaks, ShellCheck, actionlint, BuildKit, Compose validation, cargo policy, ASan, TSan including the new `controller-api` coverage, Miri, Trivy, CycloneDX SBOM, and exact VEX enforcement.
- [ ] Repair root causes; do not weaken assertions or gates.
- [ ] Do not use canceled, superseded, previous-SHA, or partial jobs as completion evidence.

Acceptance:

- [ ] The implementation SHA is fully green before final evidence edits.

---

## CR16. Final TODO and evidence update

- [ ] Update this TODO with completed checkmarks only after implementation validation.
- [ ] Fill in the evidence block below.
- [ ] Append a correction note to `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md` stating that a later review found:
  - [ ] the recorded ThreadSanitizer and Miri coverage did not include the crate the pass changed;
  - [ ] the recorded framebuffer performance review omitted per-frame allocation and conversion cost.
- [ ] Do not retroactively uncheck or rewrite that document's historical implementation claims, which remain accurate.
- [ ] Link the historical document to this spec and TODO.
- [ ] Commit the completed TODO and the correction note.
- [ ] Push the documentation commit without force.
- [ ] Wait for CI and Release Gates on the exact final repository-tip SHA.
- [ ] Record the implementation SHA and the external run identifier that validated the tip; do not claim a commit contains its own hash.

Final evidence:

```text
Starting HEAD SHA:
Implementation SHA:
Final documentation SHA:
Tip-validating CI run ID:
Tip-validating Release Gates run ID:

Baseline reproduction results:
- CR1 pre-Connected stall:
- CR2 illegal transition:
- CR3 pixel format:
- CR5 in-flight depth:
- CR6 shutdown deadline:

Local validation:

CI run and conclusion:
Release Gates run and conclusion:
R13 job and conclusion:
TSan coverage after CR4:
Framebuffer benchmark results:
```

Acceptance:

- [ ] The same final repository-tip SHA has successful CI and Release Gates.
- [ ] This TODO is the authoritative completed handoff record for this pass.

---

## Final do-not-accept checklist

- [ ] No fix was written before its failing baseline reproduction was demonstrated.
- [ ] No shutdown architecture was changed.
- [ ] No queue-depth accounting behavior was changed.
- [ ] No permit acquisition point was moved.
- [ ] No framebuffer ETag semantics were weakened.
- [ ] No R13 assertion was weakened.
- [ ] No sleep-only race test was accepted.
- [ ] No helper-only test substituted for a production-path test.
- [ ] No pixel-format assumption remains undocumented or unnegotiated.
- [ ] No sanitizer coverage claim exceeds what the workflow actually runs.
- [ ] No metric claims a meaning its value does not have.
- [ ] No command payload, typed text, clipboard value, key value, coordinate, bearer token, VNC password, framebuffer byte, or screenshot is logged.
- [ ] No `continue-on-error` was added.
- [ ] No broad `.gitleaksignore` entry was added.
- [ ] No broad Trivy or VEX ignore was added.
- [ ] No security or release gate was disabled or downgraded.
- [ ] No force-push was used.
- [ ] No completion claim relies on an older SHA.

---

## Final acceptance

This TODO is complete only when:

- [ ] a pre-`Connected` confirmed stall recovers without fatal exit;
- [ ] illegal state transitions are observable and no side-effecting result is silently discarded;
- [ ] the native pixel format is negotiated and verified end to end;
- [ ] ThreadSanitizer covers the concurrent crate or the limitation is evidenced;
- [ ] the queue-depth metric states what it measures;
- [ ] process shutdown has its own validated deadline;
- [ ] the startup cleanup bound is documented or derived;
- [ ] unreachable error arms are resolved;
- [ ] the VNC password is scrubbed on both sides of the FFI boundary;
- [ ] privacy assertions test sentinel values;
- [ ] the framebuffer performance record is complete and any optimization is evidence-driven;
- [ ] no sleep-only race test remains;
- [ ] existing worker, HTTP, VNC, screenshot, framebuffer, WebSocket, and input behavior remains green;
- [ ] R13 remains unchanged and green;
- [ ] CI and Release Gates succeed on the exact final repository-tip SHA.

## Claude Code final report template

```text
Correctness review fix status: COMPLETE / INCOMPLETE

Starting SHA:
Implementation SHA:
Final documentation SHA:
Tip-validating run IDs:

Stall recovery:
- Repair strategy chosen:
- Baseline reproduction:
- Regression tests:

State transitions:
- Diagnostic added:
- Discarded results resolved:
- fatal_exit ownership decision:

Pixel format:
- Shim format assignment:
- End-to-end color assertion:

Sanitizer coverage:
- controller-api TSan disposition:
- Coverage boundary recorded:

Metric semantics:
- Name or help text change:
- Documentation updated:

Shutdown deadline:
- New variable and floor:
- Total bound documented:

Secret scrubbing:
- Shim:
- Rust:

Privacy assertions:

Framebuffer performance:
- Measurements:
- Optimization disposition:

Tests added or changed:

Local validation:

CI run and conclusion:
Release Gates run and conclusion:
R13 job and conclusion:

Historical document corrections:

Remaining risks or skipped validation:
```
