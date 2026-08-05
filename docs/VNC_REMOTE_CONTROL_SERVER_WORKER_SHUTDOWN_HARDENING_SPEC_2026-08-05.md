# VNC Remote Control Server Worker Shutdown Hardening Spec

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Baseline observed while writing this spec: `42f542e8b0c19af4f01427a717c580ddc8ece8fd`

Related completed implementation:

- Worker shutdown refactor implementation: `7bf25d6f7da018174b9caea092743e89efd7e367`
- Worker shutdown refactor evidence/TODO completion: `593f7ee9752aad9a8589dbd456e6d7e3d3048211`
- Existing refactor spec: `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md`
- Existing refactor TODO: `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`

## 1. Purpose

The previous worker shutdown refactor correctly moved shutdown authority out of the normal bounded command queue. Shutdown now uses an out-of-band `Arc<AtomicBool>` instead of depending on successful enqueue of `WorkerCommand::Shutdown`, and exact-SHA CI and Release Gates passed for the implementation commit.

This document specifies the next hardening pass. It must not redo the refactor. It must tighten the remaining lifecycle and test-determinism issues found during review:

1. `DesktopWorker::shutdown(timeout)` currently keeps a timeout parameter but does not enforce it.
2. Startup-timeout cleanup sets the out-of-band flag but can still perform an unbounded join and suppress the join result.
3. `WorkerClient::submit()` rejects after shutdown begins, but a command can still race between the final submit-side shutdown check and worker-side execution.
4. `Drop for DesktopWorker` cannot return errors, but join failure or shutdown timeout should be observable rather than silently discarded.
5. Saturated-queue tests should become deterministic instead of depending on a timing window around bounded native poll.

## 2. Non-goals

Do not reopen the entire worker architecture.

Do not remove the completed out-of-band shutdown design.

Do not remove `WorkerCommand::Shutdown` in this pass. It remains compatibility-only unless a later dedicated API cleanup deliberately migrates all call sites, tests, E2E fixtures, and docs.

Do not change the public HTTP shutdown contract unless a direct code-level issue requires it. `/health/ready`, shutdown error envelopes, authentication/authorization, and R13 behavior should remain stable.

Do not add a new public error enum variant unless the implementation genuinely needs it. The existing `DesktopError::WorkerUnavailable` and `DesktopError::Timeout` are sufficient for this hardening pass unless code inspection proves otherwise.

Do not weaken any release, security, or CI gate.

## 3. Existing completed behavior to preserve

The following completed behavior from `7bf25d6f7da018174b9caea092743e89efd7e367` must remain intact:

- `WorkerClient` has an out-of-band shutdown flag.
- `DesktopWorker::shutdown()` and `Drop` request shutdown by storing to that flag, not by enqueueing through the normal bounded queue.
- `WorkerCommand::Shutdown` is retained for compatibility but is no longer authoritative.
- `WorkerClient::submit()` rejects ordinary new submissions after shutdown has been requested.
- Pending queued command envelopes are drained during shutdown and completed with `Err(DesktopError::WorkerUnavailable)`.
- Queue-depth accounting remains coherent during enqueue, saturation rejection, drain, and shutdown.
- Command payloads, text, clipboard contents, VNC passwords, bearer tokens, and framebuffer bytes are not logged.
- Requested shutdown does not set `fatal_exit = true`.
- Final cleanup still releases tracked input, invalidates framebuffer state, and transitions the snapshot to `ConnectionState::Stopped`.
- Existing R13, CI, Release Gates, Gitleaks, Trivy/VEX, cargo-deny, ShellCheck, actionlint, Clippy, fmt, docs, and Miri/sanitizer gates remain active.

## 4. Current hardening issues

### 4.1 Ignored timeout parameter

`DesktopWorker::shutdown(mut self, _timeout: Duration) -> Result<(), DesktopError>` currently accepts a timeout but does not enforce it. That is a quiet API-contract problem. A caller can reasonably assume the shutdown wait is bounded by the supplied `Duration`, while the implementation delegates responsiveness to native poll/adapter timeouts and then joins.

The hardening pass must make this contract honest.

Preferred behavior:

- `DesktopWorker::shutdown(timeout)` requests out-of-band shutdown.
- It waits for a worker-exit notification using the supplied timeout.
- It joins only after worker exit is observed, so the join should be nonblocking except for panic/result collection.
- If the worker does not report exit before the timeout, return `Err(DesktopError::Timeout)`.
- A shutdown timeout must be observable through a warning/error log event.
- The timeout path must not call an unbounded join from `shutdown()` or from the subsequent `Drop` of the consumed `DesktopWorker`.

Implementation hint:

- Add an exit notification channel owned by `DesktopWorker` and signaled by the worker thread immediately before `run_worker()` returns or from a guard that always runs at thread exit.
- Store the receiver in `DesktopWorker` as `worker_exited: Option<Receiver<()>>` or equivalent.
- On successful exit notification, call the existing join path and surface a thread panic or join error as `DesktopError::WorkerUnavailable` or another existing appropriate error.
- On timeout, log the timeout and detach the join handle deliberately by taking and dropping it, rather than allowing `Drop` to perform an unbounded join.

Acceptable alternative:

- Remove the timeout semantics from the API contract completely, but only if all call sites, docs, tests, and comments are updated to make that explicit. Do not leave a public `timeout` argument that is unused and undocumented.

The preferred behavior is bounded shutdown. Use the acceptable alternative only if the bounded-exit-notification design conflicts with existing architecture in a way that is clearly documented.

### 4.2 Startup-timeout cleanup must not block indefinitely

During `DesktopWorker::spawn_with_factory()`, a startup acknowledgement timeout currently triggers cleanup. The completed refactor correctly sets the out-of-band shutdown flag before the best-effort queue nudge. However, the cleanup path must also avoid unbounded join and silent join-result suppression.

Required behavior:

- On startup acknowledgement timeout, set the out-of-band shutdown flag first.
- A best-effort queue nudge is allowed, but it must not be required for cleanup correctness.
- Wait for the worker-exit notification using the startup timeout or another small, explicit cleanup timeout.
- Join only after exit is observed.
- If exit is not observed, log the timeout and deliberately detach instead of blocking indefinitely.
- If the worker thread panics during startup cleanup, log it and return a clear startup failure error.
- Do not turn startup timeout into a silent success.

### 4.3 Close the receive-side race

`WorkerClient::submit()` checks the shutdown flag before building the envelope and again immediately before enqueue. This reduces but does not eliminate the race where shutdown is requested just after the second check and before successful `try_send()`.

Required behavior:

- After the worker loop receives a `CommandEnvelope` and decrements queue depth, it must check the out-of-band shutdown flag before executing any ordinary command.
- If shutdown has been requested and the envelope is not the compatibility `WorkerCommand::Shutdown`, complete the envelope with `Err(DesktopError::WorkerUnavailable)` and do not execute the payload.
- If the envelope is `WorkerCommand::Shutdown`, continue to treat it as compatibility-only: set/observe the shutdown flag and acknowledge if possible.
- Do not inspect or log the payload of a rejected post-shutdown envelope.
- Drain any remaining pending envelopes with `WorkerUnavailable` as the current design already intends.

### 4.4 Drop observability

`Drop for DesktopWorker` cannot return a `Result`, but it should not hide meaningful failures.

Required behavior:

- `Drop` must request out-of-band shutdown first.
- `Drop` must not depend on successful enqueue of `WorkerCommand::Shutdown`.
- `Drop` must not block indefinitely.
- `Drop` should wait for a bounded, explicit internal deadline for worker exit.
- If the worker exits before the deadline, `Drop` should join the thread and log a panic/join failure if one occurs.
- If the worker does not exit before the deadline, `Drop` should log a warning/error and detach deliberately by dropping the `JoinHandle`.
- Do not panic from `Drop` during normal runtime shutdown.

Recommended constant:

```rust
const DROP_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
```

A different bounded value is acceptable if justified by existing worker timing settings.

### 4.5 Deterministic saturated-queue tests

The existing saturated-queue regression tests passed CI, but they rely on a timing window around `poll_interval = Duration::from_millis(150)`. This is acceptable evidence that the core bug was fixed, but it is weaker than it needs to be.

Required behavior:

- Replace or supplement timing-window tests with a deterministic test session.
- The test session should expose channels/barriers so the test can prove the worker is inside a controlled poll or blocked point before the normal command queue is saturated.
- Do not use long sleeps as the primary proof mechanism.
- Every test must have bounded timeouts so a regression fails quickly rather than hanging CI.

Recommended test fixture:

- A `BlockingPollSession` or equivalent `WorkerSession` test double.
- It sends a signal when `poll()` is entered.
- It waits on a release channel or returns after a bounded timeout.
- Tests can then fill the single-slot command queue while poll is known to be blocked.
- Shutdown tests can release the poll gate and assert the worker exits through the out-of-band path.

## 5. Required tests

Add or update tests in `crates/controller-api/src/worker.rs` unless implementation structure makes a neighboring test module more appropriate.

Minimum required tests:

1. `shutdown_timeout_is_enforced_when_worker_does_not_exit`
   - Arrange a worker/test double that will not report exit before the supplied shutdown timeout.
   - Call `DesktopWorker::shutdown(short_timeout)`.
   - Assert `Err(DesktopError::Timeout)`.
   - Assert the call returns before a clear test deadline.
   - Assert no unbounded join occurs.

2. `startup_timeout_cleanup_does_not_unbounded_join`
   - Arrange startup acknowledgement timeout while the worker thread remains blocked long enough to prove cleanup would hang if it joined unboundedly.
   - Assert `spawn_with_factory()` returns `Err(DesktopError::Timeout)` or the existing expected startup timeout error.
   - Assert the call returns before a clear test deadline.
   - Assert cleanup emits an observable warning/error if the worker cannot be joined.

3. `queued_command_received_after_shutdown_is_rejected_without_execution`
   - Arrange deterministic queue saturation or a controlled queue state.
   - Enqueue an ordinary command.
   - Request shutdown before the worker executes that command.
   - Allow the worker to receive the envelope.
   - Assert the command completion is `Err(DesktopError::WorkerUnavailable)`.
   - Assert the test session did not execute the command payload.

4. `drop_logs_or_records_worker_join_timeout_without_blocking`
   - Arrange a worker/test double that does not exit before the drop deadline.
   - Drop `DesktopWorker` in a bounded test harness thread.
   - Assert drop returns before the test deadline.
   - Assert an observable warning/error or test-visible diagnostic records that the worker failed to exit before the drop deadline.

5. `deterministic_saturated_queue_shutdown_still_completes`
   - Replace or supplement the existing timing-window saturated queue test.
   - Use a barrier-controlled `WorkerSession` to prove the queue is full when shutdown is requested.
   - Assert shutdown succeeds when the worker is released.
   - Assert pending queued tickets resolve with `WorkerUnavailable` rather than hanging.
   - Assert `fatal_exit == false` and final state is `Stopped`.

Also keep these existing tests green:

- `shutdown_does_not_require_command_queue_capacity`
- `drop_does_not_depend_on_shutdown_command_enqueue`
- `submit_rejects_after_shutdown_request_without_queue_mutation`
- `out_of_band_shutdown_releases_tracked_buttons_and_keys`
- `worker_commits_frame_accepts_commands_and_joins_shutdown`
- `shutdown_releases_tracked_buttons_and_keys`
- `bounded_command_queue_tracks_depth_and_rejection_without_payload_logging`
- reconnect/authentication/stall tests

It is acceptable to rename older timing-window tests if the deterministic replacement is clearer, but do not reduce coverage.

## 6. Logging and observability requirements

Use structured `tracing` events. Do not log sensitive payloads.

Required observable events or equivalent diagnostics:

- shutdown timed out before worker exit;
- drop timed out before worker exit;
- startup-timeout cleanup could not observe worker exit before cleanup deadline;
- worker thread join observed a panic or join failure.

Suggested event names:

- `desktop_worker_shutdown_timeout`
- `desktop_worker_drop_shutdown_timeout`
- `desktop_worker_startup_cleanup_timeout`
- `desktop_worker_join_failed`

Names may differ if the project has an existing naming convention. The important requirement is that the conditions are observable and payload-free.

## 7. Validation requirements

Run the actual CI-equivalent commands, not a narrower hand-written subset:

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

Where Docker/VNC resources are available, also run:

```bash
tests/desktop/run.sh
bash tests/native/run.sh
bash tests/worker-e2e/run.sh
bash tests/worker-text-clipboard-e2e/run.sh
bash tests/http-e2e/run.sh
bash tests/compose/run.sh
bash tests/integration/run.sh
```

After pushing to `master`, exact-SHA GitHub validation must pass:

- CI
  - Repository quality gates
  - Secured Debian desktop/native job
  - R13 Compose integration and E2E validation
- Release Gates
  - Static and supply-chain policy
  - full-history Gitleaks
  - ShellCheck
  - actionlint
  - BuildKit Dockerfile checks
  - Compose validation
  - cargo-deny/advisory/license/source policy
  - native ASan/TSan/Miri
  - Trivy/SBOM/VEX image gates

Do not claim completion from an older SHA, canceled run, superseded run, or partial job success.

## 8. Do-not-do list

Do not:

- remove the out-of-band shutdown flag;
- make `WorkerCommand::Shutdown` authoritative again;
- increase `command_capacity` as a fix;
- retry shutdown enqueue until queue space appears;
- leave a public timeout parameter unused and call it done;
- rely on unbounded join in `shutdown()`, startup-timeout cleanup, or `Drop`;
- silently swallow join panic/failure in non-test code;
- add sleeps as the primary correctness mechanism for saturated-queue tests;
- inspect or log command payloads when rejecting/draining commands;
- log text, clipboard contents, bearer tokens, VNC passwords, or framebuffer bytes;
- weaken HTTP shutdown behavior;
- weaken R13;
- weaken Release Gates;
- add broad `.gitleaksignore` patterns;
- add broad Trivy/VEX ignores;
- add `continue-on-error` to relevant gates;
- force-push `master`;
- mark the TODO complete before exact-SHA CI and Release Gates pass.

## 9. Completion criteria

This hardening pass is complete only when:

- `DesktopWorker::shutdown(timeout)` has honest timeout semantics, or the timeout contract is deliberately removed from all code/docs/tests.
- Startup-timeout cleanup cannot block indefinitely and does not silently suppress join failure.
- `Drop for DesktopWorker` cannot block indefinitely and logs timeout/join failure observably.
- The receive-side race is closed so ordinary commands received after shutdown request are rejected rather than executed.
- Saturated-queue shutdown tests are deterministic and bounded.
- Existing worker shutdown, input release, queue depth, HTTP shutdown, R13, and release-policy behavior remains green.
- Local CI-equivalent validation passes.
- Final exact-SHA CI passes.
- Final exact-SHA Release Gates pass.
- The companion TODO is updated with exact SHA, run IDs, and evidence.
