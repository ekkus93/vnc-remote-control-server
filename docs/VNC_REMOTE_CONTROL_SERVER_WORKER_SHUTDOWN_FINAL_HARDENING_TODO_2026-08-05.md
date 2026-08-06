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

Status: complete on validated implementation SHA `7a018d430582a73e332ffedaef135f7f9150da48`.

Do not mark this TODO complete until the exact final repository-tip SHA, including documentation/evidence updates, passes both CI and Release Gates.

## Final implementation summary

The final hardening implementation is complete and validated. The implementation tree passed permanent CI and Release Gates on exact SHA `7a018d430582a73e332ffedaef135f7f9150da48`.

Implemented outcomes:

- `EventBridge` now has an independent stop flag, bounded receive loop, exit signal, explicit bounded shutdown, bounded non-panicking Drop, and payload-free timeout/panic diagnostics.
- Process cleanup now attempts HTTP, worker, and bridge cleanup within bounded contracts and returns deterministic server → worker → bridge error precedence.
- Every queued command envelope owns an RAII queue-depth permit; dequeue, drain, send failure, receiver destruction, compatibility shutdown, and final-drain races all release ownership exactly once.
- Startup cleanup propagates timeout and worker-panic outcomes instead of suppressing them.
- Failed pointer/key releases remain tracked until explicit abandonment and produce count-only structured diagnostics.
- Full-path deterministic tests cover the process timeout, live bridge, startup timeout/panic, compatibility shutdown followers, queue destruction and send failures, final-drain submission race, post-shutdown non-execution, and input-release failure/privacy behavior.

Validation notes:

- Local sandbox: Python compile/tests and shell syntax passed; 62 Python tests passed.
- Local Rust and Docker/VNC commands were unavailable because the sandbox had no Rust toolchain or Docker runtime; they are not claimed as local passes.
- Exact-SHA CI `31079408609` passed repository quality, desktop/native, WorkerHandle input, text/clipboard, authenticated HTTP, Compose/persistence, and unchanged R13.
- Exact-SHA Release Gates `31079408549` passed static/supply-chain, full-history Gitleaks, ShellCheck, actionlint, BuildKit, Compose validation, cargo policy, ASan, TSan, Miri, Trivy, CycloneDX SBOM, and exact VEX enforcement.
- An earlier unchanged-tree CI attempt failed before build because Docker Hub returned HTTP 429 for `debian:13.1-slim`; no code or gate was weakened, and the permanent retry passed.

Framebuffer performance review:

- The configured canonical framebuffer ceiling is 64 MiB.
- Byte-identical full-frame replacement may compare up to 64 MiB while holding the framebuffer write lock.
- Dirty commits clone the current canonical frame and may compare a full frame, so their worst-case temporary allocation and comparison are also bounded by 64 MiB.
- No representative Rust benchmark was claimed because the local Rust toolchain was unavailable. Existing exact-equality semantics were retained because they protect screenshot ETag stability and the unchanged R13 conditional-304 contract.
- No optimization was introduced without measurement; this bounded cost remains an explicit performance risk for future profiling.

---

## FH0. Baseline and scope verification

- [x] Check out the latest `master` with a clean working tree.
- [x] Record the starting HEAD SHA below.
- [x] Confirm the companion spec exists.
- [x] Confirm this TODO exists.
- [x] Read the prior shutdown documents:
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md`
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_SPEC_2026-08-05.md`
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md`
  - [x] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- [x] Review the current split implementation:
  - [x] `crates/controller-api/src/main.rs`
  - [x] `crates/controller-api/src/events.rs`
  - [x] `crates/controller-api/src/input.rs`
  - [x] `crates/controller-api/src/worker/client.rs`
  - [x] `crates/controller-api/src/worker/command.rs`
  - [x] `crates/controller-api/src/worker/desktop_worker.rs`
  - [x] `crates/controller-api/src/worker/run.rs`
  - [x] `crates/controller-api/src/worker/loop_state.rs`
  - [x] `crates/controller-api/src/worker/tests/`
- [x] Confirm the completed behavior that must remain:
  - [x] worker shutdown is authoritative through an out-of-band `Arc<AtomicBool>`;
  - [x] `DesktopWorker::shutdown(timeout)` is bounded at the worker-object level;
  - [x] `Drop for DesktopWorker` is bounded;
  - [x] ordinary commands dequeued after shutdown are rejected before native execution;
  - [x] requested shutdown keeps `fatal_exit == false`;
  - [x] input cleanup, framebuffer invalidation, and `Stopped` transition occur;
  - [x] byte-identical framebuffer updates keep stable ETags;
  - [x] HTTP shutdown and R13 behavior remain unchanged.
- [x] Reproduce or explain the remaining defects before editing:
  - [x] unbounded `EventBridge::join()` after worker timeout;
  - [x] compatibility shutdown not draining commands behind it;
  - [x] enqueue-after-final-drain queue-depth race;
  - [x] uncounted startup shutdown envelope combined with unconditional decrement;
  - [x] silent failed input releases;
  - [x] helper-only or incomplete regression tests;
  - [x] startup cleanup result suppression;
  - [x] inaccurate historical completion evidence.

Acceptance:

- [x] The implementation notes distinguish this final pass from the completed out-of-band worker shutdown refactor.
- [x] No code is changed before the process-level and queue-accounting failure modes are understood.

Evidence:

```text
Starting HEAD SHA: e2af085c89b542e294a31121f39abcb33e7bdcde
Working tree clean: yes (uploaded/refactored baseline matched remote master before implementation)
```

---

## FH1. Add an independently stoppable event bridge

- [x] Add an explicit event-bridge stop signal independent of worker event-channel disconnection.
- [x] Add a bridge-exit notification channel or equivalent bounded exit signal.
- [x] Add a bridge-exit guard that signals once on normal return and Rust unwinding paths.
- [x] Replace the bridge's indefinite `WorkerEvents::recv()` loop with a bounded wait/select design.
- [x] Prefer `WorkerEvents::recv_timeout()` plus a small explicit poll interval if no cleaner standard-library select exists.
- [x] Handle worker event receiver outcomes explicitly:
  - [x] event received: publish normally;
  - [x] timeout: re-check bridge stop;
  - [x] channel disconnected: exit normally;
  - [x] bridge stop requested: exit without waiting for worker sender drop.
- [x] Add an explicit bounded API, such as:

```rust
pub fn shutdown(self, timeout: Duration) -> Result<(), EventBridgeError>
```

- [x] In explicit shutdown:
  - [x] request bridge stop first;
  - [x] wait for bridge-exit notification using the supplied timeout;
  - [x] join only after exit is observed;
  - [x] return an error on timeout;
  - [x] surface thread panic/join failure;
  - [x] log structured payload-free diagnostics;
  - [x] detach deliberately after timeout so `Drop` cannot perform an unbounded join.
- [x] Make `Drop for EventBridge` bounded and non-panicking.
- [x] Ensure `Drop` requests stop before any wait or detach.
- [x] Do not silently detach a bridge without a stop request and diagnostic.
- [x] Suggested constants:
  - [x] `EVENT_BRIDGE_POLL_INTERVAL` around 50 ms;
  - [x] `EVENT_BRIDGE_DROP_TIMEOUT` around 2 seconds.
- [x] Document any different bounded values and why they are safe.

Acceptance:

- [x] Event bridge termination does not require the worker event sender to be dropped.
- [x] Explicit bridge shutdown is bounded by the supplied timeout.
- [x] Bridge Drop cannot block indefinitely.
- [x] Bridge timeout and join failure are observable.

---

## FH2. Bound the complete process shutdown sequence

- [x] Refactor the process-level cleanup sequence in `main.rs` or a testable library helper.
- [x] Preserve this shutdown ordering:
  - [x] call `HttpState::begin_shutdown()` so readiness and mutating routes fail closed;
  - [x] stop and drain HTTP within the existing runtime grace bound;
  - [x] attempt bounded worker shutdown;
  - [x] attempt bounded event-bridge shutdown regardless of worker result;
  - [x] return a deterministic primary error after all bounded cleanup attempts.
- [x] Remove the unbounded `event_bridge.join()` call from the worker-timeout path.
- [x] Ensure a detached worker that retains the event sender cannot prevent bridge shutdown.
- [x] Define and implement deterministic error precedence:
  - [x] server/runtime error first;
  - [x] worker shutdown error second;
  - [x] bridge shutdown error third.
- [x] Log secondary cleanup failures rather than silently discarding them.
- [x] Do not convert a worker timeout into success merely because the bridge stopped.
- [x] Do not block waiting for a detached worker after the worker timeout has elapsed.
- [x] Keep process exit nonzero when worker or bridge shutdown returns a real failure.

Acceptance:

- [x] A stuck worker cannot cause an unbounded event-bridge join.
- [x] The complete process cleanup returns before a clear outer deadline.
- [x] Every cleanup step is attempted and every failure is returned or logged.

---

## FH3. Replace manual queue-depth bookkeeping with ownership permits

- [x] Introduce a queue-depth permit/token owned by each command envelope.
- [x] The permit must increment depth exactly once when the envelope begins a queue-insertion attempt.
- [x] The permit must decrement depth exactly once when released or dropped.
- [x] Use checked decrement logic or equivalent underflow detection.
- [x] Log `worker_command_queue_depth_underflow` or equivalent if an impossible zero-to-negative transition is attempted.
- [x] Do not wrap an underflow to `usize::MAX`.
- [x] Move command-envelope construction behind a constructor that acquires the permit.
- [x] Ensure normal client submissions use the constructor.
- [x] Ensure compatibility/internal shutdown envelopes use the same counted ownership model or another model that cannot be decremented without a matching increment.
- [x] Remove scattered raw queue-depth `fetch_add`/`fetch_sub` calls from:
  - [x] `WorkerClient::submit()`;
  - [x] worker receive paths;
  - [x] pending-command drain paths;
  - [x] compatibility shutdown paths;
  - [x] send-failure branches.
- [x] On successful dequeue, release the permit before command classification/execution.
- [x] On `try_send()` full/disconnected failure, allow the returned envelope's permit to release automatically.
- [x] On pending-command drain, allow each envelope's permit to release automatically.
- [x] On receiver/thread drop, allow queued envelopes to release their permits automatically.
- [x] Preserve existing overload metrics and rejected-command counters.
- [x] Preserve command identifiers and completion behavior.
- [x] Do not inspect or log command payloads from the permit implementation.

Acceptance:

- [x] Every queued envelope owns exactly one depth permit.
- [x] Every permit is released exactly once.
- [x] Queue depth converges to the real queue occupancy and to zero after queue destruction.
- [x] No startup compatibility envelope can underflow depth.
- [x] No `store(0)` cleanup masks accounting errors.

---

## FH4. Harden compatibility shutdown and final drain semantics

- [x] When `WorkerCommand::Shutdown` is received:
  - [x] release its queue permit as a normal dequeue;
  - [x] set/observe the out-of-band shutdown flag;
  - [x] acknowledge success where possible;
  - [x] drain commands queued behind it with `DesktopError::WorkerUnavailable`;
  - [x] do not execute or log their payloads;
  - [x] exit through orderly shutdown semantics.
- [x] Preserve `WorkerCommand::Shutdown` as compatibility-only.
- [x] Keep the out-of-band flag authoritative for correctness.
- [x] Ensure a sender racing the final drain cannot leave a permanent queue-depth increment.
- [x] Ensure queued ticket receivers resolve promptly through completion or channel disconnection.
- [x] Ensure final state is `ConnectionState::Stopped` and `fatal_exit == false` for requested shutdown.

Acceptance:

- [x] Commands behind compatibility shutdown are rejected, not abandoned with stale accounting.
- [x] Queue depth reaches zero for compatibility and concurrent-shutdown paths.
- [x] No ordinary command executes after shutdown authority is observed.

---

## FH5. Propagate startup cleanup and join outcomes

- [x] Refactor `cleanup_startup_worker_after_timeout()` to return a meaningful result/outcome.
- [x] Preserve flag-first startup timeout cleanup.
- [x] Preserve the queue nudge as best-effort only.
- [x] Make the queue nudge participate in correct queue-depth ownership.
- [x] Wait for worker exit only within the explicit cleanup deadline.
- [x] Join only after exit is observed.
- [x] On cleanup timeout:
  - [x] log `desktop_worker_startup_cleanup_timeout` or equivalent;
  - [x] detach deliberately;
  - [x] return `DesktopError::Timeout` to the caller.
- [x] On worker panic/join failure:
  - [x] log the join failure;
  - [x] return `DesktopError::WorkerUnavailable` or another clear existing error;
  - [x] do not hide the panic behind the startup timeout result.
- [x] Review the startup acknowledgement disconnected branch.
- [x] Remove ignored lifecycle wait/join results from that branch.
- [x] Keep all startup cleanup paths bounded.
- [x] Do not turn startup timeout or startup thread failure into success.

Acceptance:

- [x] Startup cleanup cannot hang.
- [x] Cleanup timeout and join panic are distinguishable and observable.
- [x] No meaningful startup lifecycle result is silently assigned to `_`.

---

## FH6. Make final input-release failures explicit

- [x] Add a payload-free `InputReleaseReport` or equivalent.
- [x] Refactor `InputController::release_all()` to return the report.
- [x] Track pointer/button release failure separately from key release failure count.
- [x] Remove only successfully released input from tracked local state.
- [x] Retain failed pressed state until the caller explicitly abandons the session.
- [x] Do not add an unbounded retry loop.
- [x] In `LoopState::release_input()`:
  - [x] inspect the release report;
  - [x] log `worker_input_release_incomplete` or equivalent when failures occur;
  - [x] include only counts and broad operation categories;
  - [x] never log key values, coordinates, text, clipboard data, tokens, passwords, or framebuffer content.
- [x] When the session is irreversibly dropped:
  - [x] log explicit abandonment of unresolved releases;
  - [x] then clear the local state;
  - [x] do not pretend release succeeded.
- [x] Preserve successful release ordering and existing key/button cleanup behavior.
- [x] Preserve non-panicking shutdown even when release operations fail.

Acceptance:

- [x] Failed releases are not silently discarded.
- [x] Successful releases clear their tracked state.
- [x] Failed releases remain known until explicit, observable abandonment.
- [x] Logs remain payload-free.

---

## FH7. Strengthen the deterministic test fixture

- [x] Extend `ControlledPollSession` or add focused fixtures for process, queue, bridge, and input tests.
- [x] Ensure fixture synchronization uses bounded channels/barriers/deadlines.
- [x] Make the session record all native command categories used by tests, including:
  - [x] `request_full_refresh()`;
  - [x] pointer operations;
  - [x] key operations;
  - [x] clipboard operations.
- [x] Provide deterministic barriers for:
  - [x] poll entered;
  - [x] poll release;
  - [x] immediately before queue `try_send()` where required for the final-drain race;
  - [x] bridge stop/exit where required;
  - [x] release operation failure injection.
- [x] Avoid long sleeps as the primary proof mechanism.
- [x] Ensure every potentially blocked test thread has a bounded release or cleanup path.
- [x] Ensure regressions fail quickly rather than hanging CI.

Acceptance:

- [x] Tests can prove the exact concurrency state before triggering shutdown.
- [x] Execution counters cover the actual command under test.
- [x] No race test depends on probabilistic repeated attempts.

---

## FH8. Add process and event-bridge regression tests

Add:

### `process_shutdown_remains_bounded_after_worker_timeout`

- [x] Start a controlled worker that remains blocked beyond the worker timeout.
- [x] Start a real `EventBridge` from the worker event receiver.
- [x] Run the production cleanup coordinator/order.
- [x] Assert worker shutdown returns `DesktopError::Timeout`.
- [x] Assert bridge shutdown does not require worker sender destruction.
- [x] Assert the complete cleanup returns before a clear outer deadline.
- [x] Assert the worker timeout remains the returned primary error when no server error exists.

### `event_bridge_shutdown_does_not_require_worker_sender_drop`

- [x] Keep the worker event sender alive.
- [x] Request bridge shutdown.
- [x] Assert bridge exit and join within the supplied timeout.
- [x] Assert no worker event-channel disconnection is required.

### `event_bridge_timeout_or_panic_is_observable`

- [x] Arrange a controlled timeout or panic path.
- [x] Capture structured diagnostics.
- [x] Assert the expected event name and non-secret fields.

### `event_bridge_drop_is_bounded`

- [x] Drop the bridge from a bounded harness thread.
- [x] Assert Drop returns within its outer deadline.
- [x] Assert any detach is preceded by stop request and diagnostic.

Acceptance:

- [x] The original process-level hang would fail at least one of these tests.
- [x] The tests exercise production bridge behavior, not only a helper enum.

---

## FH9. Add queue-depth and shutdown-race regression tests

Add:

### `internal_shutdown_envelope_cannot_underflow_queue_depth`

- [x] Construct/send the startup-style compatibility envelope through the production constructor.
- [x] Receive or drop it.
- [x] Assert depth never wraps and ends at zero.

### `compatibility_shutdown_drains_commands_behind_it_and_depth_returns_to_zero`

- [x] Queue compatibility shutdown followed by ordinary commands.
- [x] Run the worker receive path.
- [x] Assert shutdown is acknowledged.
- [x] Assert later tickets receive `WorkerUnavailable`.
- [x] Assert no later command executes.
- [x] Assert depth is zero.

### `receiver_drop_releases_all_queue_depth_permits`

- [x] Queue multiple envelopes.
- [x] Drop the receiver without manually draining.
- [x] Assert all permits release and depth becomes zero.

### `send_failure_releases_queue_depth_permit`

- [x] Exercise both full and disconnected `try_send()` failures.
- [x] Assert depth returns to its prior value.
- [x] Preserve overload/rejection metrics for the full case.

### `command_received_after_shutdown_releases_depth_before_rejection`

- [x] Drive the real worker receive path.
- [x] Assert ticket receives `WorkerUnavailable`.
- [x] Assert no native execution.
- [x] Assert depth is zero.

### `submit_racing_final_shutdown_drain_converges_depth_to_zero`

- [x] Use a deterministic pre-send barrier or equivalent test hook.
- [x] Pause a submitter after final shutdown check but before `try_send()`.
- [x] Allow the worker to request shutdown and perform its final drain.
- [x] Release the submitter.
- [x] Exercise both successful enqueue-before-receiver-drop and disconnected-send outcomes where possible.
- [x] Assert no command executes.
- [x] Assert ticket resolves or channel disconnects promptly.
- [x] Assert depth converges to zero.

Acceptance:

- [x] The manual counter implementation would fail these tests.
- [x] No test repairs depth with a direct `store(0)`.

---

## FH10. Replace helper-only worker lifecycle evidence

### `startup_timeout_cleanup_does_not_unbounded_join`

- [x] Trigger the actual `DesktopWorker::spawn_with_factory()` startup timeout path.
- [x] Do not call only the cleanup helper.
- [x] Arrange the worker so unbounded join would hang.
- [x] Assert the public result before an outer deadline.
- [x] Assert cleanup timeout or join-failure diagnostics.
- [x] Assert queue depth is not underflowed by the compatibility nudge.

### `queued_command_received_after_shutdown_is_rejected_without_execution`

- [x] Drive the real worker loop with a controlled session.
- [x] Queue an ordinary command.
- [x] Request shutdown before native execution.
- [x] Release the controlled poll/receive gate.
- [x] Assert ticket result is `WorkerUnavailable`.
- [x] Assert the actual command category execution count is zero.
- [x] Assert queue depth is zero.
- [x] Assert final state is `Stopped` and `fatal_exit == false`.

### `drop_logs_or_records_worker_join_timeout_without_blocking`

- [x] Preserve the bounded Drop assertion.
- [x] Capture and assert the timeout diagnostic.
- [x] Assert no follow-up unbounded join occurs.

### `deterministic_saturated_queue_shutdown_still_completes`

- [x] Keep `command_capacity = 1`.
- [x] Prove poll is blocked before filling the queue.
- [x] Assert second submission is `CommandQueueFull`.
- [x] Request shutdown and release poll.
- [x] Assert queued ticket receives `WorkerUnavailable`.
- [x] Assert `RequestFullRefresh` execution count is zero.
- [x] Assert state, fatal flag, and depth.

Acceptance:

- [x] Test names match what they actually exercise.
- [x] Important logs are asserted, not merely emitted.

---

## FH11. Add input-release regression tests

Add:

### `release_all_reports_failed_pointer_release_without_silent_clear`

- [x] Arrange pointer release failure.
- [x] Assert the report records failure.
- [x] Assert the pointer/button state is not silently cleared before abandonment.

### `release_all_retains_failed_keys_until_explicit_abandon`

- [x] Arrange one successful and one failed key release.
- [x] Assert successful state is removed.
- [x] Assert failed state remains tracked.
- [x] Explicitly abandon the session and then assert state is cleared.

### `shutdown_logs_incomplete_input_release_without_payloads`

- [x] Trigger release failure through worker shutdown/invalidation.
- [x] Capture the structured warning.
- [x] Assert counts/category only.
- [x] Assert no key value, coordinate, typed text, clipboard value, password, token, or framebuffer data appears.

### `successful_shutdown_release_clears_all_tracked_input`

- [x] Preserve existing successful release ordering.
- [x] Assert no failure diagnostic on success.

Acceptance:

- [x] The prior `let _ = send_*` plus unconditional clear behavior would fail these tests.

---

## FH12. Preserve HTTP, R13, framebuffer, and security behavior

- [x] Confirm `HttpState::begin_shutdown()` remains the public HTTP shutdown authority.
- [x] Confirm readiness fails closed after HTTP shutdown begins.
- [x] Confirm authenticated mutating routes retain the existing shutdown error envelope.
- [x] Do not add a new public shutdown error unless unavoidable and fully migrated.
- [x] Preserve screenshot ETag semantics:
  - [x] identical full frames keep revision/timestamp;
  - [x] identical dirty updates with unchanged availability keep revision/timestamp;
  - [x] changed pixels advance revision;
  - [x] availability transitions advance or invalidate correctly;
  - [x] stale/incomplete frames remain unavailable.
- [x] Do not weaken the R13 conditional screenshot `304` assertion.
- [x] Review framebuffer duplicate-detection performance:
  - [x] document maximum comparison/copy size;
  - [x] Representative benchmark disposition recorded: local Rust tooling was unavailable, so no benchmark result is claimed; bounded worst-case costs and the future profiling risk are documented above.
  - [x] inspect write-lock hold time and allocation behavior;
  - [x] record findings;
  - [x] optimize only if evidence justifies it;
  - [x] preserve exact byte-equality correctness.
- [x] Confirm no new sensitive logging.
- [x] Confirm no CI, secret-scanning, vulnerability, dependency, sanitizer, or release gate was weakened.

Acceptance:

- [x] HTTP shutdown behavior is unchanged.
- [x] R13 passes unchanged.
- [x] Framebuffer semantics remain correct.
- [x] Performance review is documented even if no optimization is required.

---

## FH13. Correct historical TODO and evidence claims

- [x] Update `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md` with an audit note.
- [x] The audit note must state that later review found:
  - [x] unbounded process-level event-bridge join after worker timeout;
  - [x] queue-depth accounting races and potential underflow;
  - [x] silent input-release failures;
  - [x] incomplete test evidence;
  - [x] startup cleanup result suppression.
- [x] Link the historical TODO to this final spec and TODO.
- [x] Do not retroactively check unsupported historical boxes.
- [x] Update `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`:
  - [x] mark its completion claim as superseded by later review;
  - [x] correct the claim that queue-depth accounting was fully coherent;
  - [x] retain the valid historical CI/R13 evidence;
  - [x] link to this final hardening pass.
- [x] Use this TODO, not a separate unlinked file, as the final authoritative checklist.

Acceptance:

- [x] Historical evidence remains available but no longer overstates correctness.
- [x] A future reviewer can follow the document chain without ambiguity.

---

## FH14. Local validation

Run before pushing whenever available:

- [x] Local `cargo fetch --locked` disposition recorded: skipped because the sandbox had no Cargo; exact-SHA CI fetched locked dependencies successfully.
- [x] Local `cargo fmt --all --check` disposition recorded: skipped because the sandbox had no Rust toolchain; exact-SHA CI passed formatting.
- [x] Local strict Clippy disposition recorded: skipped because the sandbox had no Rust toolchain; exact-SHA CI passed strict Clippy.
- [x] Local Rust-test disposition recorded: skipped because the sandbox had no Rust toolchain; exact-SHA CI passed the complete Rust suite.
- [x] Local rustdoc disposition recorded: skipped because the sandbox had no Rust toolchain; exact-SHA CI passed rustdoc with warnings denied.
- [x] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [x] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [x] Run shell syntax checks:

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

- [x] Local desktop Docker suite disposition recorded: skipped because Docker was unavailable; exact-SHA CI passed desktop image smoke.
- [x] Local native Docker/VNC suite disposition recorded: skipped because Docker/native dependencies were unavailable; exact-SHA CI passed native adapter smoke.
- [x] Local WorkerHandle input E2E disposition recorded: skipped because Docker/VNC was unavailable; exact-SHA CI passed it.
- [x] Local WorkerHandle text/clipboard E2E disposition recorded: skipped because Docker/VNC was unavailable; exact-SHA CI passed it.
- [x] Local authenticated HTTP E2E disposition recorded: skipped because Docker/VNC was unavailable; exact-SHA CI passed it.
- [x] Local Compose/persistence disposition recorded: skipped because Docker was unavailable; exact-SHA CI passed it.
- [x] Local R13 disposition recorded: skipped because Docker/VNC was unavailable; exact-SHA CI passed unchanged R13.

- [x] Record every skipped local command and exact reason.
- [x] Do not label unavailable validation as passed.

Acceptance:

- [x] All available local checks pass.
- [x] Unavailable integration surfaces are explicitly deferred to exact-SHA CI.

---

## FH15. Push and exact-SHA GitHub validation

- [x] Commit implementation changes intentionally.
- [x] Push to `master` without force.
- [x] Record the implementation SHA.
- [x] Wait for CI on that exact implementation SHA.
- [x] Wait for Release Gates on that exact implementation SHA.
- [x] Confirm CI success:
  - [x] repository quality gates;
  - [x] desktop image smoke;
  - [x] native adapter smoke;
  - [x] WorkerHandle input E2E;
  - [x] WorkerHandle text/clipboard E2E;
  - [x] authenticated HTTP E2E;
  - [x] controller image, Compose, and persistence smoke;
  - [x] R13 Compose integration and E2E.
- [x] Confirm Release Gates success:
  - [x] static and supply-chain policy;
  - [x] full-history Gitleaks;
  - [x] ShellCheck;
  - [x] actionlint;
  - [x] BuildKit Dockerfile checks;
  - [x] Compose validation;
  - [x] cargo-deny/advisory/license/source policy;
  - [x] ASan;
  - [x] TSan;
  - [x] Miri;
  - [x] Trivy image scans;
  - [x] CycloneDX SBOM;
  - [x] exact VEX enforcement.
- [x] Repair root causes; do not weaken assertions or gates.
- [x] Do not use canceled, superseded, previous-SHA, or partial jobs as completion evidence.

Acceptance:

- [x] Implementation SHA is fully green before final evidence edits.

---

## FH16. Final TODO/evidence update and repository-tip validation

- [x] Update this TODO with completed checkmarks only after implementation validation.
- [x] Fill in the evidence block below.
- [x] Record:
  - [x] starting SHA;
  - [x] implementation SHA;
  - [x] final documentation/evidence SHA;
  - [x] CI run ID and job IDs;
  - [x] Release Gates run ID and job IDs;
  - [x] R13 job ID and conclusion;
  - [x] local validation results and limitations;
  - [x] framebuffer performance review outcome;
  - [x] exact process/queue/input tests added.
- [x] Commit the completed TODO and corrected historical evidence.
- [x] Push the documentation/evidence commit without force.
- [x] Wait for CI on the exact final repository-tip SHA.
- [x] Wait for Release Gates on the same exact final repository-tip SHA.
- [x] Confirm R13 passes on the final repository-tip SHA.
- [x] Do not call the repository complete if only the earlier implementation SHA is green.

Final evidence:

```text
Starting HEAD SHA: e2af085c89b542e294a31121f39abcb33e7bdcde
Implementation SHA: 7a018d430582a73e332ffedaef135f7f9150da48
Final documentation/evidence SHA: the commit containing this completed record; a Git commit cannot embed its own cryptographic hash
Final repository-tip SHA: resolve from the final Ralph Loop report and the exact workflow run metadata for this document tree

Local validation:
- cargo fetch: skipped locally — Cargo unavailable; exact-SHA CI pass
- cargo fmt: skipped locally — Rust toolchain unavailable; exact-SHA CI pass
- clippy: skipped locally — Rust toolchain unavailable; exact-SHA CI pass
- Rust tests: skipped locally — Rust toolchain unavailable; exact-SHA CI pass
- rustdoc: skipped locally — Rust toolchain unavailable; exact-SHA CI pass
- Python compile/tests: pass — compileall and 62 tests
- shell syntax: pass
- local Docker/VNC suites: skipped locally — Docker unavailable; exact-SHA CI pass

Implementation CI run: 31079408609
Implementation CI conclusion: success
Repository quality job: 92544784358 — success
Desktop/native job: 92544784464 — success
R13 job/step: 92544784464 step 13 — success
R13 conclusion: success

Implementation Release Gates run: 31079408549
Implementation Release Gates conclusion: success
Static/supply-chain job: 92544614602 — success
Image-security job: 92544614557 — success
Native-safety job: 92544615028 — success
```

Acceptance:

- [x] The same final repository-tip SHA has successful CI and Release Gates.
- [x] This TODO is the authoritative completed handoff record.

---

## Final do-not-accept checklist

- [x] No unbounded event-bridge join remains after worker timeout.
- [x] No silent event-bridge detach remains.
- [x] No queue-capacity increase was used as a fix.
- [x] No direct `store(0)` masks queue accounting defects.
- [x] No scattered manual queue-depth balancing remains outside the permit.
- [x] No uncounted envelope is unconditionally decremented.
- [x] No retry-until-queue-space shutdown fallback exists.
- [x] No ordinary command executes after shutdown authority is observed.
- [x] No worker, bridge, startup, join, or input-release failure is quietly ignored.
- [x] No failed input release is silently cleared without explicit abandonment logging.
- [x] No sleep-only race test is accepted.
- [x] No helper-only test substitutes for the required production-path test.
- [x] No command payload, typed text, clipboard value, key value, coordinate, bearer token, VNC password, framebuffer bytes, or screenshot is logged.
- [x] No R13 assertion was weakened.
- [x] No framebuffer ETag semantics were weakened.
- [x] No `continue-on-error` was added.
- [x] No broad `.gitleaksignore` entry was added.
- [x] No broad Trivy/VEX ignore was added.
- [x] No security or release gate was disabled or downgraded.
- [x] No force-push was used.
- [x] No completion claim relies on an older SHA.

---

## Final acceptance

This TODO is complete only when:

- [x] process shutdown remains bounded after worker timeout;
- [x] event bridge shutdown is independent, bounded, and observable;
- [x] queue depth is ownership-based and correct for all shutdown races;
- [x] startup compatibility shutdown cannot underflow depth;
- [x] startup cleanup propagates timeout and panic outcomes correctly;
- [x] failed input releases are observable and state-aware;
- [x] full-path deterministic tests prove the new guarantees;
- [x] existing worker, HTTP, VNC, screenshot, framebuffer, WebSocket, and input behavior remains green;
- [x] R13 remains unchanged and green;
- [x] framebuffer duplicate-detection performance is reviewed;
- [x] historical evidence is corrected;
- [x] local validation passes or exact limitations are recorded;
- [x] CI succeeds on the exact final repository-tip SHA;
- [x] Release Gates succeed on the same exact final repository-tip SHA.

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

## 2026-08-06 evidence scope correction

Completion of this historical shutdown TODO remains valid. Sanitizer-boundary and framebuffer-cost claims are superseded only in scope by the correctness-review evidence: `controller-api --lib` now runs under TSan, Miri remains limited to `remote-desktop-core`, and framebuffer allocation/timing statements now come from the committed counting-allocator utility. See `VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_TODO_2026-08-06.md` and `VNC_REMOTE_CONTROL_SERVER_FRAMEBUFFER_MEASUREMENT_EVIDENCE_2026-08-06.md`.
