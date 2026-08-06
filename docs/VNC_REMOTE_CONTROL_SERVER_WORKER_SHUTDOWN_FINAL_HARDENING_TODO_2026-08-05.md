# VNC Remote Control Server Worker Shutdown Final Hardening TODO

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Companion specification:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`

Review baseline: `7c80b696643629005d5b8e1d7a5c5d0feed12d57`

Spec creation commit: `9cdc0deac9027dd449ab211cd18e89d144ef04f8`

This TODO is the authoritative checklist for the final shutdown hardening pass. It supersedes completion claims in the earlier hardening TODO/evidence where the later review found unresolved process-lifecycle, queue-accounting, input-release, and test-evidence gaps.

## Completion status

Status: not started.

Do not mark this TODO complete until the exact final repository-tip SHA, including documentation/evidence updates, passes both CI and Release Gates.

---

## FH0. Baseline and scope verification

- [ ] Check out the latest `master` with a clean working tree.
- [ ] Record the starting HEAD SHA below.
- [ ] Confirm the companion spec exists.
- [ ] Confirm this TODO exists.
- [ ] Read the prior shutdown documents:
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_SPEC_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md`
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- [ ] Review the current split implementation:
  - [ ] `crates/controller-api/src/main.rs`
  - [ ] `crates/controller-api/src/events.rs`
  - [ ] `crates/controller-api/src/input.rs`
  - [ ] `crates/controller-api/src/worker/client.rs`
  - [ ] `crates/controller-api/src/worker/command.rs`
  - [ ] `crates/controller-api/src/worker/desktop_worker.rs`
  - [ ] `crates/controller-api/src/worker/run.rs`
  - [ ] `crates/controller-api/src/worker/loop_state.rs`
  - [ ] `crates/controller-api/src/worker/tests/`
- [ ] Confirm the completed behavior that must remain:
  - [ ] worker shutdown is authoritative through an out-of-band `Arc<AtomicBool>`;
  - [ ] `DesktopWorker::shutdown(timeout)` is bounded at the worker-object level;
  - [ ] `Drop for DesktopWorker` is bounded;
  - [ ] ordinary commands dequeued after shutdown are rejected before native execution;
  - [ ] requested shutdown keeps `fatal_exit == false`;
  - [ ] input cleanup, framebuffer invalidation, and `Stopped` transition occur;
  - [ ] byte-identical framebuffer updates keep stable ETags;
  - [ ] HTTP shutdown and R13 behavior remain unchanged.
- [ ] Reproduce or explain the remaining defects before editing:
  - [ ] unbounded `EventBridge::join()` after worker timeout;
  - [ ] compatibility shutdown not draining commands behind it;
  - [ ] enqueue-after-final-drain queue-depth race;
  - [ ] uncounted startup shutdown envelope combined with unconditional decrement;
  - [ ] silent failed input releases;
  - [ ] helper-only or incomplete regression tests;
  - [ ] startup cleanup result suppression;
  - [ ] inaccurate historical completion evidence.

Acceptance:

- [ ] The implementation notes distinguish this final pass from the completed out-of-band worker shutdown refactor.
- [ ] No code is changed before the process-level and queue-accounting failure modes are understood.

Evidence:

```text
Starting HEAD SHA: <fill in>
Working tree clean: <yes/no>
```

---

## FH1. Add an independently stoppable event bridge

- [ ] Add an explicit event-bridge stop signal independent of worker event-channel disconnection.
- [ ] Add a bridge-exit notification channel or equivalent bounded exit signal.
- [ ] Add a bridge-exit guard that signals once on normal return and Rust unwinding paths.
- [ ] Replace the bridge's indefinite `WorkerEvents::recv()` loop with a bounded wait/select design.
- [ ] Prefer `WorkerEvents::recv_timeout()` plus a small explicit poll interval if no cleaner standard-library select exists.
- [ ] Handle worker event receiver outcomes explicitly:
  - [ ] event received: publish normally;
  - [ ] timeout: re-check bridge stop;
  - [ ] channel disconnected: exit normally;
  - [ ] bridge stop requested: exit without waiting for worker sender drop.
- [ ] Add an explicit bounded API, such as:

```rust
pub fn shutdown(self, timeout: Duration) -> Result<(), EventBridgeError>
```

- [ ] In explicit shutdown:
  - [ ] request bridge stop first;
  - [ ] wait for bridge-exit notification using the supplied timeout;
  - [ ] join only after exit is observed;
  - [ ] return an error on timeout;
  - [ ] surface thread panic/join failure;
  - [ ] log structured payload-free diagnostics;
  - [ ] detach deliberately after timeout so `Drop` cannot perform an unbounded join.
- [ ] Make `Drop for EventBridge` bounded and non-panicking.
- [ ] Ensure `Drop` requests stop before any wait or detach.
- [ ] Do not silently detach a bridge without a stop request and diagnostic.
- [ ] Suggested constants:
  - [ ] `EVENT_BRIDGE_POLL_INTERVAL` around 50 ms;
  - [ ] `EVENT_BRIDGE_DROP_TIMEOUT` around 2 seconds.
- [ ] Document any different bounded values and why they are safe.

Acceptance:

- [ ] Event bridge termination does not require the worker event sender to be dropped.
- [ ] Explicit bridge shutdown is bounded by the supplied timeout.
- [ ] Bridge Drop cannot block indefinitely.
- [ ] Bridge timeout and join failure are observable.

---

## FH2. Bound the complete process shutdown sequence

- [ ] Refactor the process-level cleanup sequence in `main.rs` or a testable library helper.
- [ ] Preserve this shutdown ordering:
  - [ ] call `HttpState::begin_shutdown()` so readiness and mutating routes fail closed;
  - [ ] stop and drain HTTP within the existing runtime grace bound;
  - [ ] attempt bounded worker shutdown;
  - [ ] attempt bounded event-bridge shutdown regardless of worker result;
  - [ ] return a deterministic primary error after all bounded cleanup attempts.
- [ ] Remove the unbounded `event_bridge.join()` call from the worker-timeout path.
- [ ] Ensure a detached worker that retains the event sender cannot prevent bridge shutdown.
- [ ] Define and implement deterministic error precedence:
  - [ ] server/runtime error first;
  - [ ] worker shutdown error second;
  - [ ] bridge shutdown error third.
- [ ] Log secondary cleanup failures rather than silently discarding them.
- [ ] Do not convert a worker timeout into success merely because the bridge stopped.
- [ ] Do not block waiting for a detached worker after the worker timeout has elapsed.
- [ ] Keep process exit nonzero when worker or bridge shutdown returns a real failure.

Acceptance:

- [ ] A stuck worker cannot cause an unbounded event-bridge join.
- [ ] The complete process cleanup returns before a clear outer deadline.
- [ ] Every cleanup step is attempted and every failure is returned or logged.

---

## FH3. Replace manual queue-depth bookkeeping with ownership permits

- [ ] Introduce a queue-depth permit/token owned by each command envelope.
- [ ] The permit must increment depth exactly once when the envelope begins a queue-insertion attempt.
- [ ] The permit must decrement depth exactly once when released or dropped.
- [ ] Use checked decrement logic or equivalent underflow detection.
- [ ] Log `worker_command_queue_depth_underflow` or equivalent if an impossible zero-to-negative transition is attempted.
- [ ] Do not wrap an underflow to `usize::MAX`.
- [ ] Move command-envelope construction behind a constructor that acquires the permit.
- [ ] Ensure normal client submissions use the constructor.
- [ ] Ensure compatibility/internal shutdown envelopes use the same counted ownership model or another model that cannot be decremented without a matching increment.
- [ ] Remove scattered raw queue-depth `fetch_add`/`fetch_sub` calls from:
  - [ ] `WorkerClient::submit()`;
  - [ ] worker receive paths;
  - [ ] pending-command drain paths;
  - [ ] compatibility shutdown paths;
  - [ ] send-failure branches.
- [ ] On successful dequeue, release the permit before command classification/execution.
- [ ] On `try_send()` full/disconnected failure, allow the returned envelope's permit to release automatically.
- [ ] On pending-command drain, allow each envelope's permit to release automatically.
- [ ] On receiver/thread drop, allow queued envelopes to release their permits automatically.
- [ ] Preserve existing overload metrics and rejected-command counters.
- [ ] Preserve command identifiers and completion behavior.
- [ ] Do not inspect or log command payloads from the permit implementation.

Acceptance:

- [ ] Every queued envelope owns exactly one depth permit.
- [ ] Every permit is released exactly once.
- [ ] Queue depth converges to the real queue occupancy and to zero after queue destruction.
- [ ] No startup compatibility envelope can underflow depth.
- [ ] No `store(0)` cleanup masks accounting errors.

---

## FH4. Harden compatibility shutdown and final drain semantics

- [ ] When `WorkerCommand::Shutdown` is received:
  - [ ] release its queue permit as a normal dequeue;
  - [ ] set/observe the out-of-band shutdown flag;
  - [ ] acknowledge success where possible;
  - [ ] drain commands queued behind it with `DesktopError::WorkerUnavailable`;
  - [ ] do not execute or log their payloads;
  - [ ] exit through orderly shutdown semantics.
- [ ] Preserve `WorkerCommand::Shutdown` as compatibility-only.
- [ ] Keep the out-of-band flag authoritative for correctness.
- [ ] Ensure a sender racing the final drain cannot leave a permanent queue-depth increment.
- [ ] Ensure queued ticket receivers resolve promptly through completion or channel disconnection.
- [ ] Ensure final state is `ConnectionState::Stopped` and `fatal_exit == false` for requested shutdown.

Acceptance:

- [ ] Commands behind compatibility shutdown are rejected, not abandoned with stale accounting.
- [ ] Queue depth reaches zero for compatibility and concurrent-shutdown paths.
- [ ] No ordinary command executes after shutdown authority is observed.

---

## FH5. Propagate startup cleanup and join outcomes

- [ ] Refactor `cleanup_startup_worker_after_timeout()` to return a meaningful result/outcome.
- [ ] Preserve flag-first startup timeout cleanup.
- [ ] Preserve the queue nudge as best-effort only.
- [ ] Make the queue nudge participate in correct queue-depth ownership.
- [ ] Wait for worker exit only within the explicit cleanup deadline.
- [ ] Join only after exit is observed.
- [ ] On cleanup timeout:
  - [ ] log `desktop_worker_startup_cleanup_timeout` or equivalent;
  - [ ] detach deliberately;
  - [ ] return `DesktopError::Timeout` to the caller.
- [ ] On worker panic/join failure:
  - [ ] log the join failure;
  - [ ] return `DesktopError::WorkerUnavailable` or another clear existing error;
  - [ ] do not hide the panic behind the startup timeout result.
- [ ] Review the startup acknowledgement disconnected branch.
- [ ] Remove ignored lifecycle wait/join results from that branch.
- [ ] Keep all startup cleanup paths bounded.
- [ ] Do not turn startup timeout or startup thread failure into success.

Acceptance:

- [ ] Startup cleanup cannot hang.
- [ ] Cleanup timeout and join panic are distinguishable and observable.
- [ ] No meaningful startup lifecycle result is silently assigned to `_`.

---

## FH6. Make final input-release failures explicit

- [ ] Add a payload-free `InputReleaseReport` or equivalent.
- [ ] Refactor `InputController::release_all()` to return the report.
- [ ] Track pointer/button release failure separately from key release failure count.
- [ ] Remove only successfully released input from tracked local state.
- [ ] Retain failed pressed state until the caller explicitly abandons the session.
- [ ] Do not add an unbounded retry loop.
- [ ] In `LoopState::release_input()`:
  - [ ] inspect the release report;
  - [ ] log `worker_input_release_incomplete` or equivalent when failures occur;
  - [ ] include only counts and broad operation categories;
  - [ ] never log key values, coordinates, text, clipboard data, tokens, passwords, or framebuffer content.
- [ ] When the session is irreversibly dropped:
  - [ ] log explicit abandonment of unresolved releases;
  - [ ] then clear the local state;
  - [ ] do not pretend release succeeded.
- [ ] Preserve successful release ordering and existing key/button cleanup behavior.
- [ ] Preserve non-panicking shutdown even when release operations fail.

Acceptance:

- [ ] Failed releases are not silently discarded.
- [ ] Successful releases clear their tracked state.
- [ ] Failed releases remain known until explicit, observable abandonment.
- [ ] Logs remain payload-free.

---

## FH7. Strengthen the deterministic test fixture

- [ ] Extend `ControlledPollSession` or add focused fixtures for process, queue, bridge, and input tests.
- [ ] Ensure fixture synchronization uses bounded channels/barriers/deadlines.
- [ ] Make the session record all native command categories used by tests, including:
  - [ ] `request_full_refresh()`;
  - [ ] pointer operations;
  - [ ] key operations;
  - [ ] clipboard operations.
- [ ] Provide deterministic barriers for:
  - [ ] poll entered;
  - [ ] poll release;
  - [ ] immediately before queue `try_send()` where required for the final-drain race;
  - [ ] bridge stop/exit where required;
  - [ ] release operation failure injection.
- [ ] Avoid long sleeps as the primary proof mechanism.
- [ ] Ensure every potentially blocked test thread has a bounded release or cleanup path.
- [ ] Ensure regressions fail quickly rather than hanging CI.

Acceptance:

- [ ] Tests can prove the exact concurrency state before triggering shutdown.
- [ ] Execution counters cover the actual command under test.
- [ ] No race test depends on probabilistic repeated attempts.

---

## FH8. Add process and event-bridge regression tests

Add:

### `process_shutdown_remains_bounded_after_worker_timeout`

- [ ] Start a controlled worker that remains blocked beyond the worker timeout.
- [ ] Start a real `EventBridge` from the worker event receiver.
- [ ] Run the production cleanup coordinator/order.
- [ ] Assert worker shutdown returns `DesktopError::Timeout`.
- [ ] Assert bridge shutdown does not require worker sender destruction.
- [ ] Assert the complete cleanup returns before a clear outer deadline.
- [ ] Assert the worker timeout remains the returned primary error when no server error exists.

### `event_bridge_shutdown_does_not_require_worker_sender_drop`

- [ ] Keep the worker event sender alive.
- [ ] Request bridge shutdown.
- [ ] Assert bridge exit and join within the supplied timeout.
- [ ] Assert no worker event-channel disconnection is required.

### `event_bridge_timeout_or_panic_is_observable`

- [ ] Arrange a controlled timeout or panic path.
- [ ] Capture structured diagnostics.
- [ ] Assert the expected event name and non-secret fields.

### `event_bridge_drop_is_bounded`

- [ ] Drop the bridge from a bounded harness thread.
- [ ] Assert Drop returns within its outer deadline.
- [ ] Assert any detach is preceded by stop request and diagnostic.

Acceptance:

- [ ] The original process-level hang would fail at least one of these tests.
- [ ] The tests exercise production bridge behavior, not only a helper enum.

---

## FH9. Add queue-depth and shutdown-race regression tests

Add:

### `internal_shutdown_envelope_cannot_underflow_queue_depth`

- [ ] Construct/send the startup-style compatibility envelope through the production constructor.
- [ ] Receive or drop it.
- [ ] Assert depth never wraps and ends at zero.

### `compatibility_shutdown_drains_commands_behind_it_and_depth_returns_to_zero`

- [ ] Queue compatibility shutdown followed by ordinary commands.
- [ ] Run the worker receive path.
- [ ] Assert shutdown is acknowledged.
- [ ] Assert later tickets receive `WorkerUnavailable`.
- [ ] Assert no later command executes.
- [ ] Assert depth is zero.

### `receiver_drop_releases_all_queue_depth_permits`

- [ ] Queue multiple envelopes.
- [ ] Drop the receiver without manually draining.
- [ ] Assert all permits release and depth becomes zero.

### `send_failure_releases_queue_depth_permit`

- [ ] Exercise both full and disconnected `try_send()` failures.
- [ ] Assert depth returns to its prior value.
- [ ] Preserve overload/rejection metrics for the full case.

### `command_received_after_shutdown_releases_depth_before_rejection`

- [ ] Drive the real worker receive path.
- [ ] Assert ticket receives `WorkerUnavailable`.
- [ ] Assert no native execution.
- [ ] Assert depth is zero.

### `submit_racing_final_shutdown_drain_converges_depth_to_zero`

- [ ] Use a deterministic pre-send barrier or equivalent test hook.
- [ ] Pause a submitter after final shutdown check but before `try_send()`.
- [ ] Allow the worker to request shutdown and perform its final drain.
- [ ] Release the submitter.
- [ ] Exercise both successful enqueue-before-receiver-drop and disconnected-send outcomes where possible.
- [ ] Assert no command executes.
- [ ] Assert ticket resolves or channel disconnects promptly.
- [ ] Assert depth converges to zero.

Acceptance:

- [ ] The manual counter implementation would fail these tests.
- [ ] No test repairs depth with a direct `store(0)`.

---

## FH10. Replace helper-only worker lifecycle evidence

### `startup_timeout_cleanup_does_not_unbounded_join`

- [ ] Trigger the actual `DesktopWorker::spawn_with_factory()` startup timeout path.
- [ ] Do not call only the cleanup helper.
- [ ] Arrange the worker so unbounded join would hang.
- [ ] Assert the public result before an outer deadline.
- [ ] Assert cleanup timeout or join-failure diagnostics.
- [ ] Assert queue depth is not underflowed by the compatibility nudge.

### `queued_command_received_after_shutdown_is_rejected_without_execution`

- [ ] Drive the real worker loop with a controlled session.
- [ ] Queue an ordinary command.
- [ ] Request shutdown before native execution.
- [ ] Release the controlled poll/receive gate.
- [ ] Assert ticket result is `WorkerUnavailable`.
- [ ] Assert the actual command category execution count is zero.
- [ ] Assert queue depth is zero.
- [ ] Assert final state is `Stopped` and `fatal_exit == false`.

### `drop_logs_or_records_worker_join_timeout_without_blocking`

- [ ] Preserve the bounded Drop assertion.
- [ ] Capture and assert the timeout diagnostic.
- [ ] Assert no follow-up unbounded join occurs.

### `deterministic_saturated_queue_shutdown_still_completes`

- [ ] Keep `command_capacity = 1`.
- [ ] Prove poll is blocked before filling the queue.
- [ ] Assert second submission is `CommandQueueFull`.
- [ ] Request shutdown and release poll.
- [ ] Assert queued ticket receives `WorkerUnavailable`.
- [ ] Assert `RequestFullRefresh` execution count is zero.
- [ ] Assert state, fatal flag, and depth.

Acceptance:

- [ ] Test names match what they actually exercise.
- [ ] Important logs are asserted, not merely emitted.

---

## FH11. Add input-release regression tests

Add:

### `release_all_reports_failed_pointer_release_without_silent_clear`

- [ ] Arrange pointer release failure.
- [ ] Assert the report records failure.
- [ ] Assert the pointer/button state is not silently cleared before abandonment.

### `release_all_retains_failed_keys_until_explicit_abandon`

- [ ] Arrange one successful and one failed key release.
- [ ] Assert successful state is removed.
- [ ] Assert failed state remains tracked.
- [ ] Explicitly abandon the session and then assert state is cleared.

### `shutdown_logs_incomplete_input_release_without_payloads`

- [ ] Trigger release failure through worker shutdown/invalidation.
- [ ] Capture the structured warning.
- [ ] Assert counts/category only.
- [ ] Assert no key value, coordinate, typed text, clipboard value, password, token, or framebuffer data appears.

### `successful_shutdown_release_clears_all_tracked_input`

- [ ] Preserve existing successful release ordering.
- [ ] Assert no failure diagnostic on success.

Acceptance:

- [ ] The prior `let _ = send_*` plus unconditional clear behavior would fail these tests.

---

## FH12. Preserve HTTP, R13, framebuffer, and security behavior

- [ ] Confirm `HttpState::begin_shutdown()` remains the public HTTP shutdown authority.
- [ ] Confirm readiness fails closed after HTTP shutdown begins.
- [ ] Confirm authenticated mutating routes retain the existing shutdown error envelope.
- [ ] Do not add a new public shutdown error unless unavoidable and fully migrated.
- [ ] Preserve screenshot ETag semantics:
  - [ ] identical full frames keep revision/timestamp;
  - [ ] identical dirty updates with unchanged availability keep revision/timestamp;
  - [ ] changed pixels advance revision;
  - [ ] availability transitions advance or invalidate correctly;
  - [ ] stale/incomplete frames remain unavailable.
- [ ] Do not weaken the R13 conditional screenshot `304` assertion.
- [ ] Review framebuffer duplicate-detection performance:
  - [ ] document maximum comparison/copy size;
  - [ ] measure representative full-frame and dirty-update operations where practical;
  - [ ] inspect write-lock hold time and allocation behavior;
  - [ ] record findings;
  - [ ] optimize only if evidence justifies it;
  - [ ] preserve exact byte-equality correctness.
- [ ] Confirm no new sensitive logging.
- [ ] Confirm no CI, secret-scanning, vulnerability, dependency, sanitizer, or release gate was weakened.

Acceptance:

- [ ] HTTP shutdown behavior is unchanged.
- [ ] R13 passes unchanged.
- [ ] Framebuffer semantics remain correct.
- [ ] Performance review is documented even if no optimization is required.

---

## FH13. Correct historical TODO and evidence claims

- [ ] Update `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md` with an audit note.
- [ ] The audit note must state that later review found:
  - [ ] unbounded process-level event-bridge join after worker timeout;
  - [ ] queue-depth accounting races and potential underflow;
  - [ ] silent input-release failures;
  - [ ] incomplete test evidence;
  - [ ] startup cleanup result suppression.
- [ ] Link the historical TODO to this final spec and TODO.
- [ ] Do not retroactively check unsupported historical boxes.
- [ ] Update `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`:
  - [ ] mark its completion claim as superseded by later review;
  - [ ] correct the claim that queue-depth accounting was fully coherent;
  - [ ] retain the valid historical CI/R13 evidence;
  - [ ] link to this final hardening pass.
- [ ] Use this TODO, not a separate unlinked file, as the final authoritative checklist.

Acceptance:

- [ ] Historical evidence remains available but no longer overstates correctness.
- [ ] A future reviewer can follow the document chain without ambiguity.

---

## FH14. Local validation

Run before pushing whenever available:

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `RUSTFLAGS=-Dwarnings cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `RUSTFLAGS=-Dwarnings cargo test --locked --workspace --all-features`
- [ ] `RUSTDOCFLAGS=-Dwarnings cargo doc --locked --workspace --all-features --no-deps`
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

Where Docker/VNC resources are available:

- [ ] `tests/desktop/run.sh`
- [ ] `bash tests/native/run.sh`
- [ ] `bash tests/worker-e2e/run.sh`
- [ ] `bash tests/worker-text-clipboard-e2e/run.sh`
- [ ] `bash tests/http-e2e/run.sh`
- [ ] `bash tests/compose/run.sh`
- [ ] `bash tests/integration/run.sh`

- [ ] Record every skipped local command and exact reason.
- [ ] Do not label unavailable validation as passed.

Acceptance:

- [ ] All available local checks pass.
- [ ] Unavailable integration surfaces are explicitly deferred to exact-SHA CI.

---

## FH15. Push and exact-SHA GitHub validation

- [ ] Commit implementation changes intentionally.
- [ ] Push to `master` without force.
- [ ] Record the implementation SHA.
- [ ] Wait for CI on that exact implementation SHA.
- [ ] Wait for Release Gates on that exact implementation SHA.
- [ ] Confirm CI success:
  - [ ] repository quality gates;
  - [ ] desktop image smoke;
  - [ ] native adapter smoke;
  - [ ] WorkerHandle input E2E;
  - [ ] WorkerHandle text/clipboard E2E;
  - [ ] authenticated HTTP E2E;
  - [ ] controller image, Compose, and persistence smoke;
  - [ ] R13 Compose integration and E2E.
- [ ] Confirm Release Gates success:
  - [ ] static and supply-chain policy;
  - [ ] full-history Gitleaks;
  - [ ] ShellCheck;
  - [ ] actionlint;
  - [ ] BuildKit Dockerfile checks;
  - [ ] Compose validation;
  - [ ] cargo-deny/advisory/license/source policy;
  - [ ] ASan;
  - [ ] TSan;
  - [ ] Miri;
  - [ ] Trivy image scans;
  - [ ] CycloneDX SBOM;
  - [ ] exact VEX enforcement.
- [ ] Repair root causes; do not weaken assertions or gates.
- [ ] Do not use canceled, superseded, previous-SHA, or partial jobs as completion evidence.

Acceptance:

- [ ] Implementation SHA is fully green before final evidence edits.

---

## FH16. Final TODO/evidence update and repository-tip validation

- [ ] Update this TODO with completed checkmarks only after implementation validation.
- [ ] Fill in the evidence block below.
- [ ] Record:
  - [ ] starting SHA;
  - [ ] implementation SHA;
  - [ ] final documentation/evidence SHA;
  - [ ] CI run ID and job IDs;
  - [ ] Release Gates run ID and job IDs;
  - [ ] R13 job ID and conclusion;
  - [ ] local validation results and limitations;
  - [ ] framebuffer performance review outcome;
  - [ ] exact process/queue/input tests added.
- [ ] Commit the completed TODO and corrected historical evidence.
- [ ] Push the documentation/evidence commit without force.
- [ ] Wait for CI on the exact final repository-tip SHA.
- [ ] Wait for Release Gates on the same exact final repository-tip SHA.
- [ ] Confirm R13 passes on the final repository-tip SHA.
- [ ] Do not call the repository complete if only the earlier implementation SHA is green.

Final evidence:

```text
Starting HEAD SHA: <fill in>
Implementation SHA: <fill in>
Final documentation/evidence SHA: <fill in>
Final repository-tip SHA: <fill in>

Local validation:
- cargo fetch: <pass/skipped + reason>
- cargo fmt: <pass/skipped + reason>
- clippy: <pass/skipped + reason>
- Rust tests: <pass/skipped + reason>
- rustdoc: <pass/skipped + reason>
- Python compile/tests: <pass/skipped + reason>
- shell syntax: <pass/skipped + reason>
- local Docker/VNC suites: <pass/skipped + reason>

CI run: <fill in>
CI conclusion: <fill in>
Repository quality job: <fill in>
Desktop/native job: <fill in>
R13 job: <fill in>
R13 conclusion: <fill in>

Release Gates run: <fill in>
Release Gates conclusion: <fill in>
Static/supply-chain job: <fill in>
Image-security job: <fill in>
Native-safety job: <fill in>
```

Acceptance:

- [ ] The same final repository-tip SHA has successful CI and Release Gates.
- [ ] This TODO is the authoritative completed handoff record.

---

## Final do-not-accept checklist

- [ ] No unbounded event-bridge join remains after worker timeout.
- [ ] No silent event-bridge detach remains.
- [ ] No queue-capacity increase was used as a fix.
- [ ] No direct `store(0)` masks queue accounting defects.
- [ ] No scattered manual queue-depth balancing remains outside the permit.
- [ ] No uncounted envelope is unconditionally decremented.
- [ ] No retry-until-queue-space shutdown fallback exists.
- [ ] No ordinary command executes after shutdown authority is observed.
- [ ] No worker, bridge, startup, join, or input-release failure is quietly ignored.
- [ ] No failed input release is silently cleared without explicit abandonment logging.
- [ ] No sleep-only race test is accepted.
- [ ] No helper-only test substitutes for the required production-path test.
- [ ] No command payload, typed text, clipboard value, key value, coordinate, bearer token, VNC password, framebuffer bytes, or screenshot is logged.
- [ ] No R13 assertion was weakened.
- [ ] No framebuffer ETag semantics were weakened.
- [ ] No `continue-on-error` was added.
- [ ] No broad `.gitleaksignore` entry was added.
- [ ] No broad Trivy/VEX ignore was added.
- [ ] No security or release gate was disabled or downgraded.
- [ ] No force-push was used.
- [ ] No completion claim relies on an older SHA.

---

## Final acceptance

This TODO is complete only when:

- [ ] process shutdown remains bounded after worker timeout;
- [ ] event bridge shutdown is independent, bounded, and observable;
- [ ] queue depth is ownership-based and correct for all shutdown races;
- [ ] startup compatibility shutdown cannot underflow depth;
- [ ] startup cleanup propagates timeout and panic outcomes correctly;
- [ ] failed input releases are observable and state-aware;
- [ ] full-path deterministic tests prove the new guarantees;
- [ ] existing worker, HTTP, VNC, screenshot, framebuffer, WebSocket, and input behavior remains green;
- [ ] R13 remains unchanged and green;
- [ ] framebuffer duplicate-detection performance is reviewed;
- [ ] historical evidence is corrected;
- [ ] local validation passes or exact limitations are recorded;
- [ ] CI succeeds on the exact final repository-tip SHA;
- [ ] Release Gates succeed on the same exact final repository-tip SHA.

## Claude Code final report template

```text
Final hardening status: COMPLETE / INCOMPLETE

Starting SHA:
Implementation SHA:
Final documentation/evidence SHA:
Final repository-tip SHA:

Process shutdown:
- Event bridge stop mechanism:
- Worker-timeout behavior:
- Complete cleanup deadline test:

Queue accounting:
- Permit design:
- Compatibility shutdown behavior:
- Underflow prevention:
- Final-drain race test:

Input release:
- Release report design:
- Failure logging:
- Explicit abandonment behavior:

Tests added/changed:
- process/event bridge:
- queue depth/races:
- startup/worker lifecycle:
- input release:

Framebuffer performance review:

Local validation:

CI run and conclusion:
Repository quality job:
Desktop/native job:
R13 job and conclusion:

Release Gates run and conclusion:
Static/supply-chain job:
Image-security job:
Native-safety job:

Historical TODO/evidence corrections:

Remaining risks or skipped validation:
```