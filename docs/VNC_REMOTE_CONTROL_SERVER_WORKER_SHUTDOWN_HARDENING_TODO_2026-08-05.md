# VNC Remote Control Server Worker Shutdown Hardening TODO

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Companion spec:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_SPEC_2026-08-05.md`

Starting context:

- Baseline observed while this TODO was written: `42f542e8b0c19af4f01427a717c580ddc8ece8fd`
- Completed worker shutdown refactor implementation: `7bf25d6f7da018174b9caea092743e89efd7e367`
- Completed worker shutdown refactor evidence: `593f7ee9752aad9a8589dbd456e6d7e3d3048211`

This TODO is a hardening pass. Do not redo the completed out-of-band shutdown refactor.

## H0. Baseline verification

- [ ] Check out latest `master`.
- [ ] Record the starting HEAD SHA in implementation notes.
- [ ] Confirm the companion spec exists:
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_SPEC_2026-08-05.md`
- [ ] Confirm this TODO exists.
- [ ] Review `crates/controller-api/src/worker.rs`.
- [ ] Confirm the completed refactor behavior is present:
  - [ ] `WorkerClient` owns/clones an out-of-band `Arc<AtomicBool>` shutdown flag.
  - [ ] `DesktopWorker::shutdown()` requests shutdown by storing to that flag.
  - [ ] `Drop for DesktopWorker` requests shutdown by storing to that flag.
  - [ ] `WorkerCommand::Shutdown` is compatibility-only, not the authoritative shutdown path.
  - [ ] pending queued commands are drained with `DesktopError::WorkerUnavailable`.
- [ ] Review current TODO/evidence file:
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`
- [ ] Confirm this pass is addressing only the remaining hardening items.

Acceptance:

- [ ] You can explain the remaining hardening issues before editing code.
- [ ] You can distinguish this pass from the already-completed queue-independent shutdown refactor.

---

## H1. Make `DesktopWorker::shutdown(timeout)` contract honest

Preferred implementation: enforce the timeout.

- [ ] Add a worker-exit notification channel or equivalent bounded exit signal.
  - [ ] The worker thread sends the notification exactly once when it is about to exit.
  - [ ] The notification is sent on both normal and fatal worker exit paths.
  - [ ] Use a guard if needed so panic/early-return paths are handled as well as practical.
- [ ] Store the exit receiver in `DesktopWorker`, likely as an `Option<Receiver<()>>`.
- [ ] Update `DesktopWorker::shutdown(mut self, timeout: Duration)`:
  - [ ] request out-of-band shutdown first;
  - [ ] wait for worker-exit notification using the supplied `timeout`;
  - [ ] join only after exit has been observed;
  - [ ] return `Err(DesktopError::Timeout)` if exit is not observed by the deadline;
  - [ ] log an observable warning/error on timeout;
  - [ ] avoid allowing the consumed `DesktopWorker`'s `Drop` path to perform an unbounded join after a timeout;
  - [ ] surface thread panic/join failure as an error and/or observable log.
- [ ] If the implementation cannot enforce timeout semantics safely, stop and update the spec/TODO with an explicit API-contract alternative instead of leaving `_timeout` ignored.

Acceptance:

- [ ] There is no unused `_timeout` parameter in `DesktopWorker::shutdown()` unless timeout semantics have been deliberately removed everywhere.
- [ ] A caller-supplied timeout bounds the shutdown wait.
- [ ] Shutdown timeout is observable and returns a real error.
- [ ] No unbounded join is reachable from `shutdown()` timeout handling.

---

## H2. Harden startup-timeout cleanup

- [ ] Inspect the `RecvTimeoutError::Timeout` path in `DesktopWorker::spawn_with_factory()`.
- [ ] Ensure it sets the out-of-band shutdown flag before any best-effort queue nudge.
- [ ] Keep any queue nudge best-effort only; enqueue failure must not affect correctness.
- [ ] Replace unbounded startup cleanup join with bounded exit-notification wait.
- [ ] Join only after exit notification is observed.
- [ ] If worker exit is not observed by the cleanup deadline:
  - [ ] log `desktop_worker_startup_cleanup_timeout` or equivalent;
  - [ ] deliberately detach/drop the join handle rather than blocking indefinitely;
  - [ ] return the existing startup timeout failure to the caller.
- [ ] If join observes panic/failure:
  - [ ] log `desktop_worker_join_failed` or equivalent;
  - [ ] return a clear startup failure error.

Acceptance:

- [ ] Startup acknowledgement timeout cannot hang indefinitely during cleanup.
- [ ] Startup cleanup failure is observable, not silently swallowed.
- [ ] Startup timeout does not become a silent success.

---

## H3. Close the receive-side shutdown race

Current submit-side checks reduce but do not fully eliminate the race where shutdown is requested after the final submit-side check and before worker-side execution.

- [ ] In the worker loop, after `commands.try_recv()` succeeds and queue depth is decremented, check the out-of-band shutdown flag before executing any ordinary command.
- [ ] If shutdown has been requested and the received command is ordinary:
  - [ ] complete the command with `Err(DesktopError::WorkerUnavailable)`;
  - [ ] do not execute the command;
  - [ ] do not inspect or log the command payload;
  - [ ] drain remaining pending commands with `WorkerUnavailable`;
  - [ ] exit through orderly shutdown semantics.
- [ ] If the received command is `WorkerCommand::Shutdown`:
  - [ ] set/observe the same out-of-band shutdown flag;
  - [ ] acknowledge success where possible;
  - [ ] continue to treat it as compatibility-only.
- [ ] Preserve queue-depth accounting for all paths.
- [ ] Preserve `fatal_exit == false` for requested shutdown.

Acceptance:

- [ ] An ordinary command received after shutdown request is rejected, not executed.
- [ ] No command payloads are logged in this rejection path.
- [ ] Pending command tickets resolve promptly with `WorkerUnavailable`.

---

## H4. Make `Drop for DesktopWorker` bounded and observable

- [ ] Add an explicit bounded drop deadline, such as:

```rust
const DROP_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
```

- [ ] Update `Drop for DesktopWorker`:
  - [ ] request out-of-band shutdown first;
  - [ ] do not enqueue `WorkerCommand::Shutdown` as the correctness path;
  - [ ] wait for worker-exit notification using the bounded drop deadline;
  - [ ] join only after exit is observed;
  - [ ] log thread panic/join failure if observed;
  - [ ] if the worker does not exit by the deadline, log a warning/error and deliberately detach/drop the join handle;
  - [ ] do not panic from `Drop` during normal runtime shutdown.

Acceptance:

- [ ] `Drop` cannot block forever waiting for worker join.
- [ ] `Drop` failure modes are observable.
- [ ] `Drop` still requests shutdown before detaching.
- [ ] No silent join-result suppression remains for meaningful join failures.

---

## H5. Add deterministic worker-session test fixture

- [ ] Add a test-only `BlockingPollSession`, `ControlledPollSession`, or equivalent.
- [ ] The fixture should implement `WorkerSession`.
- [ ] It should expose deterministic synchronization primitives:
  - [ ] signal when `poll()` is entered;
  - [ ] allow the test to block/release `poll()`;
  - [ ] optionally record whether commands were executed;
  - [ ] optionally simulate no-exit or delayed-exit behavior for timeout tests.
- [ ] Avoid broad sleeps as the primary correctness mechanism.
- [ ] Use bounded `recv_timeout`/deadlines for all test synchronization.

Acceptance:

- [ ] Tests can prove when the worker is blocked in the desired state.
- [ ] Tests fail quickly if the worker regresses.
- [ ] CI cannot hang indefinitely because of a broken test.

---

## H6. Add/replace hardening regression tests

Add or update tests in `crates/controller-api/src/worker.rs` unless another test module is clearly better.

### Required test: `shutdown_timeout_is_enforced_when_worker_does_not_exit`

- [ ] Arrange a worker/test double that does not report exit before the supplied shutdown timeout.
- [ ] Call `DesktopWorker::shutdown(short_timeout)`.
- [ ] Assert it returns `Err(DesktopError::Timeout)`.
- [ ] Assert the call returns before a clear outer test deadline.
- [ ] Assert no unbounded join occurs.
- [ ] Assert timeout is observable through logs or test-visible diagnostics if the project test harness supports it.

### Required test: `startup_timeout_cleanup_does_not_unbounded_join`

- [ ] Arrange startup acknowledgement timeout.
- [ ] Arrange the worker thread so an unbounded join would hang the test if present.
- [ ] Assert `spawn_with_factory()` returns the expected timeout/startup failure.
- [ ] Assert it returns before a clear outer test deadline.
- [ ] Assert cleanup timeout/join failure is observable where feasible.

### Required test: `queued_command_received_after_shutdown_is_rejected_without_execution`

- [ ] Enqueue an ordinary command.
- [ ] Request shutdown before the worker executes it.
- [ ] Allow the worker to receive the envelope.
- [ ] Assert command completion is `Err(DesktopError::WorkerUnavailable)`.
- [ ] Assert the command was not executed by the test session.
- [ ] Assert queue depth remains coherent.

### Required test: `drop_logs_or_records_worker_join_timeout_without_blocking`

- [ ] Arrange a worker/test double that does not exit before the drop deadline.
- [ ] Drop `DesktopWorker` in a bounded harness thread.
- [ ] Assert drop returns before the test deadline.
- [ ] Assert an observable warning/error or test-visible diagnostic records the timeout.

### Required test: `deterministic_saturated_queue_shutdown_still_completes`

- [ ] Use the controlled poll/session fixture to prove the worker is blocked.
- [ ] Set `command_capacity = 1`.
- [ ] Fill the single-slot command queue.
- [ ] Confirm a second ordinary submission returns `CommandQueueFull`.
- [ ] Request shutdown.
- [ ] Release the poll gate if needed.
- [ ] Assert shutdown completes.
- [ ] Assert final state is `ConnectionState::Stopped`.
- [ ] Assert `fatal_exit == false`.
- [ ] Assert the queued ticket resolves with `WorkerUnavailable` rather than timing out.

Acceptance:

- [ ] These tests fail against the previously reviewed hardening gaps or specifically exercise the new guarantees.
- [ ] The existing saturated-queue timing-window tests are replaced or supplemented by deterministic tests.
- [ ] Test names are clear and evidence-friendly.

---

## H7. Preserve existing worker tests

Keep existing tests green, including but not limited to:

- [ ] `shutdown_does_not_require_command_queue_capacity`
- [ ] `drop_does_not_depend_on_shutdown_command_enqueue`
- [ ] `submit_rejects_after_shutdown_request_without_queue_mutation`
- [ ] `out_of_band_shutdown_releases_tracked_buttons_and_keys`
- [ ] `worker_commits_frame_accepts_commands_and_joins_shutdown`
- [ ] `shutdown_releases_tracked_buttons_and_keys`
- [ ] `bounded_command_queue_tracks_depth_and_rejection_without_payload_logging`
- [ ] reconnect tests
- [ ] authentication failure tests
- [ ] stall/reconnect tests

Acceptance:

- [ ] Hardening does not regress the completed out-of-band shutdown refactor.
- [ ] Input release behavior remains covered.
- [ ] Queue-depth and saturation metrics remain covered.

---

## H8. Preserve HTTP/R13 behavior

- [ ] Confirm no public HTTP shutdown contract changes were introduced.
- [ ] Confirm `HttpState::begin_shutdown()` behavior remains the source of public HTTP shutdown readiness.
- [ ] Confirm `/health/ready` still fails closed after HTTP shutdown begins.
- [ ] Confirm authenticated mutating routes after HTTP shutdown begins still return the existing shutdown error envelope.
- [ ] Do not add `DesktopError::ShuttingDown` unless unavoidable.
- [ ] If public error mapping changes are unavoidable, update:
  - [ ] `remote-desktop-core` error definitions;
  - [ ] HTTP domain error mapping;
  - [ ] tests;
  - [ ] docs/OpenAPI if affected;
  - [ ] R13 expectations.

Acceptance:

- [ ] Existing R13 shutdown expectations still pass.
- [ ] Public API behavior is not weakened.

---

## H9. Logging and privacy review

- [ ] Add structured tracing for meaningful lifecycle failures:
  - [ ] shutdown timeout before worker exit;
  - [ ] drop timeout before worker exit;
  - [ ] startup cleanup timeout before worker exit;
  - [ ] worker thread join panic/failure.
- [ ] Suggested event names, or project-style equivalents:
  - [ ] `desktop_worker_shutdown_timeout`
  - [ ] `desktop_worker_drop_shutdown_timeout`
  - [ ] `desktop_worker_startup_cleanup_timeout`
  - [ ] `desktop_worker_join_failed`
- [ ] Confirm logs do not include:
  - [ ] command payloads;
  - [ ] typed text;
  - [ ] clipboard contents;
  - [ ] bearer tokens;
  - [ ] VNC passwords;
  - [ ] framebuffer bytes;
  - [ ] screenshots.

Acceptance:

- [ ] Failure modes are observable without exposing sensitive data.
- [ ] No quiet lifecycle failure remains for timeout/join cases.

---

## H10. Local validation

Run the CI-equivalent local checks before pushing.

- [ ] Run:

```bash
cargo fetch --locked
cargo fmt --all --check
RUSTFLAGS=-Dwarnings cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
RUSTFLAGS=-Dwarnings cargo test --locked --workspace --all-features
RUSTDOCFLAGS=-Dwarnings cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
python -m unittest discover -s tests -p 'test_*.py' -v
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

- [ ] Where local Docker/VNC resources are available, run:

```bash
tests/desktop/run.sh
bash tests/native/run.sh
bash tests/worker-e2e/run.sh
bash tests/worker-text-clipboard-e2e/run.sh
bash tests/http-e2e/run.sh
bash tests/compose/run.sh
bash tests/integration/run.sh
```

- [ ] If local Docker/VNC resources are not available, document that clearly and rely on exact-SHA CI for those suites.

Acceptance:

- [ ] Local formatter, Clippy, tests, docs, Python, and shell syntax pass before push.
- [ ] Any skipped local integration surface is explicitly documented and later covered by CI.

---

## H11. Push and exact-SHA GitHub validation

After local validation passes:

- [ ] Push the implementation commit to `master`.
- [ ] Record the final implementation SHA.
- [ ] Wait for CI on that exact SHA.
- [ ] Wait for Release Gates on that exact SHA.
- [ ] Confirm CI success:
  - [ ] Repository quality gates success.
  - [ ] Secured Debian desktop/native job success.
  - [ ] R13 Compose integration and E2E validation success.
- [ ] Confirm Release Gates success:
  - [ ] Static and supply-chain policy success.
  - [ ] full-history Gitleaks success.
  - [ ] ShellCheck success.
  - [ ] actionlint success.
  - [ ] BuildKit Dockerfile checks success.
  - [ ] Compose validation success.
  - [ ] cargo-deny/advisory/license/source policy success.
  - [ ] native ASan/TSan/Miri success.
  - [ ] Trivy/SBOM/VEX image gates success.

Acceptance:

- [ ] Final exact SHA has CI success.
- [ ] Final exact SHA has Release Gates success.
- [ ] No canceled, superseded, previous-SHA, or partial job result is used as completion evidence.

---

## H12. Evidence update

After final validation:

- [ ] Update this TODO with completion checkmarks.
- [ ] Add final implementation SHA.
- [ ] Add CI run ID and conclusion.
- [ ] Add Release Gates run ID and conclusion.
- [ ] Add notes describing how `DesktopWorker::shutdown(timeout)` is now honest.
- [ ] Add notes describing startup-timeout cleanup behavior.
- [ ] Add notes describing receive-side race closure.
- [ ] Add notes describing `Drop` timeout/join observability.
- [ ] Add notes describing deterministic saturated-queue tests.
- [ ] Add notes confirming no broad fallback/bypass was introduced.

Fill in:

```text
Starting HEAD SHA:
Final implementation SHA:
CI run:
CI conclusion:
Release Gates run:
Release Gates conclusion:
Shutdown timeout design:
Startup cleanup design:
Receive-side race closure:
Drop timeout/join observability:
Deterministic test names:
R13 status:
No broad fallback/bypass confirmation:
```

Acceptance:

- [ ] This TODO becomes the final handoff/evidence record.

---

## H13. Do-not-do checklist

Each item below should remain unchecked until final evidence is updated. At final evidence time, mark each item as confirmed not done.

- [ ] Confirmed not done: remove the out-of-band shutdown flag.
- [ ] Confirmed not done: make `WorkerCommand::Shutdown` authoritative again.
- [ ] Confirmed not done: increase `command_capacity` as a fix.
- [ ] Confirmed not done: retry shutdown enqueue until queue space appears.
- [ ] Confirmed not done: leave a public timeout parameter unused and call it done.
- [ ] Confirmed not done: rely on unbounded join in `shutdown()`, startup-timeout cleanup, or `Drop`.
- [ ] Confirmed not done: silently swallow join panic/failure in non-test code.
- [ ] Confirmed not done: add sleeps as the primary correctness mechanism for saturated-queue tests.
- [ ] Confirmed not done: inspect or log command payloads when rejecting/draining commands.
- [ ] Confirmed not done: log text, clipboard contents, bearer tokens, VNC passwords, framebuffer bytes, or screenshots.
- [ ] Confirmed not done: weaken HTTP shutdown behavior.
- [ ] Confirmed not done: weaken R13.
- [ ] Confirmed not done: weaken Release Gates.
- [ ] Confirmed not done: add broad `.gitleaksignore` patterns.
- [ ] Confirmed not done: add broad Trivy/VEX ignores.
- [ ] Confirmed not done: add `continue-on-error` to relevant gates.
- [ ] Confirmed not done: force-push `master`.
- [ ] Confirmed not done: mark completion before exact-SHA CI and Release Gates pass.

---

## Final completion checklist

- [ ] `DesktopWorker::shutdown(timeout)` has honest timeout behavior or the timeout contract is deliberately removed from all code/docs/tests.
- [ ] Startup-timeout cleanup cannot block indefinitely.
- [ ] Startup-timeout cleanup does not silently suppress join failure.
- [ ] `Drop for DesktopWorker` cannot block indefinitely.
- [ ] `Drop for DesktopWorker` logs timeout/join failure observably.
- [ ] Ordinary commands received after shutdown request are rejected before execution.
- [ ] Pending queued command tickets still resolve promptly during shutdown.
- [ ] Saturated-queue tests are deterministic and bounded.
- [ ] Existing worker shutdown tests remain green.
- [ ] Input release still occurs on shutdown.
- [ ] Queue-depth accounting remains coherent.
- [ ] Fatal-exit semantics remain correct.
- [ ] Public HTTP shutdown behavior remains stable.
- [ ] R13 remains green.
- [ ] Local validation passed.
- [ ] CI passed on final exact SHA.
- [ ] Release Gates passed on final exact SHA.
- [ ] This TODO was updated with final evidence.
