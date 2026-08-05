# VNC Remote Control Server Worker Shutdown Refactor TODO

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md`

## Current handoff summary

The release-review Ralph loop is not complete because the worker shutdown queue-saturation issue remains unresolved.

Already completed in the prior release-review pass:

- Gitleaks false positive was classified and resolved with an exact fingerprint, not a broad bypass.
- Static-policy evidence now retains a redacted Gitleaks JSON report.
- Controller Rust builder image was digest-pinned.
- WebSocket event sequence overflow was hardened.
- Desktop healthcheck was hardened so R13 restart/resource-bound checks no longer fail on one transient readiness probe miss.
- CI and Release Gates passed on `c70ba3025d511aba347962cabacb3631de88401b` after the healthcheck fix.

Not completed:

- Worker shutdown still depends on successfully enqueueing `WorkerCommand::Shutdown` into the normal bounded command queue.
- Saturated-command-queue shutdown and drop regression tests do not yet exist.

Failed draft reference:

- Commit `896974fbe4086a8ce93f87dfea8c1990b858132c` attempted an out-of-band shutdown refactor but failed at `cargo fmt --check` before Clippy/tests ran.
- Do not treat that commit as validated.
- You may inspect it as a design reference with:

```bash
git show 896974fbe4086a8ce93f87dfea8c1990b858132c -- crates/controller-api/src/worker.rs
```

Safe baseline reference:

- Commit `febf71a8b62b4c94d357c7baba0d381f1c273fb3` restored `worker.rs` to the last green worker blob while preserving the healthcheck fix.
- Start from current `master`, not from stale local state.

---

## F0. Baseline verification

- [x] Check out latest `master`.
- [x] Confirm the current HEAD SHA.
- [x] Confirm `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md` exists.
- [x] Confirm this TODO exists.
- [x] Confirm `crates/controller-api/src/worker.rs` is currently the safe restored version, not the unvalidated draft from `896974f...`.
- [x] Review the current worker shutdown implementation:
  - [x] `WorkerClient::submit()` uses the normal bounded `SyncSender<CommandEnvelope>`.
  - [x] `DesktopWorker::shutdown()` still submits `WorkerCommand::Shutdown` through that queue.
  - [x] `Drop for DesktopWorker` still tries normal queue shutdown before joining.
  - [x] Worker loop only exits for shutdown after receiving `WorkerCommand::Shutdown` or command channel disconnect.
- [x] Record the starting HEAD SHA in your implementation notes: `d14c59ba8e150d340ab1c84f745314a90e1e0cd1`
  (HEAD after the answers file was pulled in, immediately before this implementation began).

Acceptance:

- [x] You can explain the full-queue shutdown failure mode before editing code.

---

## F1. Inspect the failed draft without trusting it

- [x] Inspect failed draft commit `896974fbe4086a8ce93f87dfea8c1990b858132c`.
- [x] Identify useful design pieces, if any:
  - [x] shared out-of-band shutdown signal;
  - [x] submit rejection after shutdown request;
  - [x] worker-loop shutdown checks;
  - [x] saturated queue tests.
- [x] Do not cherry-pick blindly.
- [x] Re-implement cleanly or apply the patch in a local checkout where `cargo fmt` can run.
- [x] Run formatter before committing.

Acceptance:

- [x] No unformatted code from the draft reaches `master`.
- [x] No unvalidated code is claimed complete.

---

## F2. Add out-of-band shutdown state

Recommended implementation:

- [x] Add a shared `Arc<AtomicBool>` shutdown flag to the worker runtime.
- [x] Store a clone on `WorkerClient`, likely as:

```rust
shutdown_requested: Arc<AtomicBool>,
```

- [x] Pass another clone to the worker loop through `WorkerChannels` or as a direct `run_worker` argument.
- [x] Initialize it to `false` in `DesktopWorker::spawn_with_factory()`.
- [x] Add private helper methods in `worker.rs` if useful:

```rust
fn request_shutdown(&self) {
    self.shutdown_requested.store(true, Ordering::Release);
}

fn shutdown_requested(&self) -> bool {
    self.shutdown_requested.load(Ordering::Acquire)
}
```

- [x] Keep helpers private unless a public API is genuinely needed.

Acceptance:

- [x] Shutdown can be requested without sending any normal command.
- [x] The design is thread-safe and uses explicit atomic ordering.

---

## F3. Reject new commands after shutdown begins

- [x] Update `WorkerClient::submit()` so it checks the out-of-band shutdown signal before:
  - [x] allocating a command ID;
  - [x] creating a completion channel;
  - [x] incrementing `command_queue_depth`;
  - [x] calling `try_send`.
- [x] Return `DesktopError::WorkerUnavailable` for ordinary commands submitted after shutdown begins, unless you intentionally add a new explicit `DesktopError::ShuttingDown` and update all mappings/docs/tests.
- [x] Do not increment `rejected_commands` for shutdown-state rejection unless you deliberately define a new metric. The existing `rejected_commands` metric should remain queue-saturation-specific.
- [x] Consider a second shutdown check immediately before `try_send` to reduce races; if added, maintain queue-depth correctness.

Acceptance:

- [x] Command submission after shutdown is explicit and nonblocking.
- [x] Queue depth is not inflated by rejected post-shutdown commands.
- [x] No command payloads are logged when rejecting post-shutdown commands.

---

## F4. Refactor DesktopWorker shutdown and Drop

- [x] Update `DesktopWorker::shutdown()` so it does not require normal queue capacity.
- [x] It must request shutdown through the out-of-band signal first.
- [x] It may optionally attempt a best-effort wake through the normal queue, but enqueue failure must not fail shutdown and must not be the correctness path.
- [x] Keep the public signature unless you intentionally update all call sites:

```rust
pub fn shutdown(mut self, timeout: Duration) -> Result<(), DesktopError>
```

- [x] If `timeout` becomes unused, rename it to `_timeout` or use it meaningfully. Do not leave warnings.
- [x] Update `Drop for DesktopWorker`:
  - [x] request out-of-band shutdown;
  - [x] avoid depending on successful `WorkerCommand::Shutdown` enqueue;
  - [x] join only after shutdown is requested;
  - [x] avoid hidden infinite wait caused by full normal queue.
- [x] Update startup-timeout cleanup so it does not rely solely on enqueueing shutdown into the normal queue.

Acceptance:

- [x] `DesktopWorker::shutdown()` works when the normal queue is full.
- [x] `Drop` requests shutdown independently of the normal queue.
- [x] No normal queue capacity change is used to hide the bug.

---

## F5. Update worker loop shutdown behavior

- [x] Pass the shutdown signal into `run_worker()`.
- [x] Check shutdown at the top of the main loop.
- [x] Check shutdown before starting a new VNC connection attempt.
- [x] Check shutdown before processing ordinary queued commands.
- [x] Check shutdown after processing a command.
- [x] Check shutdown around poll/idle paths as practical.
- [x] Preserve `WorkerCommand::Shutdown` handling as compatibility if useful, but make it set/observe the same out-of-band shutdown path.
- [x] Preserve `orderly_shutdown = true` semantics when shutdown was requested.
- [x] Ensure requested shutdown does not set `fatal_exit = true`.
- [x] Preserve final cleanup:
  - [x] input release;
  - [x] framebuffer invalidation;
  - [x] transition to `ConnectionState::Stopped`.

Acceptance:

- [x] Worker exits cleanly after out-of-band shutdown.
- [x] Worker does not continue reconnecting after shutdown is requested.
- [x] Worker does not set fatal exit for requested shutdown.

---

## F6. Drain or disconnect pending commands safely

Choose one implementation strategy and prove it with tests.

Preferred strategy:

- [x] Add a private `drain_pending_commands(...)` helper.
- [x] On shutdown, drain pending command envelopes from the normal queue.
- [x] For each drained envelope:
  - [x] decrement `command_queue_depth`;
  - [x] send `Err(DesktopError::WorkerUnavailable)` on the completion sender;
  - [x] do not inspect or log payloads.

Alternative strategy:

Not used — the preferred (explicit-drain) strategy above was implemented instead.

- [ ] N/A: Allow pending envelopes to be dropped so command tickets see a disconnected completion channel.
- [ ] N/A: Prove `CommandTicket::wait()` returns `DesktopError::WorkerUnavailable` rather than timing out.
- [ ] N/A: Prove `command_queue_depth` does not remain misleading after stop.

Acceptance:

- [x] Pending command tickets do not hang until arbitrary caller timeouts during shutdown.
- [x] Queue depth accounting remains coherent.
- [x] No pending command payloads are logged or exposed.

---

## F7. Preserve HTTP shutdown behavior

- [x] Confirm `HttpState::begin_shutdown()` still controls public HTTP shutdown readiness.
- [x] Confirm `/health/ready` fails closed after HTTP shutdown begins.
- [x] Confirm authenticated mutating routes after HTTP shutdown begins continue returning existing `shutting_down` error envelopes.
- [x] Do not change public error codes unless unavoidable.
- [ ] N/A: `DesktopError::ShuttingDown` was not added; post-shutdown rejections continue to use the existing `DesktopError::WorkerUnavailable`, so no error-enum/mapping/test/doc updates were needed.
  - [ ] N/A: `remote-desktop-core` error enum;
  - [ ] N/A: HTTP domain error mapping;
  - [ ] N/A: tests;
  - [ ] N/A: docs/OpenAPI if affected.

Acceptance:

- [x] Existing R13 shutdown expectations still pass.
- [x] Public API behavior is not weakened.

---

## F8. Add regression tests

Add tests in `crates/controller-api/src/worker.rs`.

Required tests:

- [x] `shutdown_does_not_require_command_queue_capacity`
  - [x] Configure small `command_capacity`, preferably `1`.
  - [x] Saturate or prove saturation of the normal command queue.
  - [x] Request shutdown.
  - [x] Assert shutdown completes and worker reaches `Stopped`.
  - [x] Assert `fatal_exit == false`.

- [x] `drop_does_not_depend_on_shutdown_command_enqueue`
  - [x] Arrange a condition where normal shutdown command enqueue would fail or be irrelevant.
  - [x] Drop the worker from a bounded harness/thread.
  - [x] Assert the drop path returns before a clear test deadline.
  - [x] Do not write a test that can hang CI forever.

- [x] `submit_rejects_after_shutdown_request_without_queue_mutation`
  - [x] Request shutdown.
  - [x] Try submitting a normal command.
  - [x] Assert explicit rejection.
  - [x] Assert queue depth is not incremented.
  - [x] Assert rejected-command queue saturation metric is not incorrectly incremented.

- [x] `out_of_band_shutdown_releases_tracked_buttons_and_keys`
  - [x] Use `RecordingSession` or equivalent.
  - [x] Press/hold a button and key.
  - [x] Trigger out-of-band shutdown.
  - [x] Assert release events are recorded.

Also keep existing tests green:

- [x] `worker_commits_frame_accepts_commands_and_joins_shutdown`
- [x] `shutdown_releases_tracked_buttons_and_keys`
- [x] `bounded_command_queue_tracks_depth_and_rejection_without_payload_logging`
- [x] reconnect/authentication/stall tests

Acceptance:

- [x] Tests fail against the old queue-dependent shutdown path, or at least specifically exercise the newly guaranteed behavior.
- [x] Tests are deterministic and do not rely on broad sleeps when a channel/barrier/deadline can be used.

---

## F9. Local validation before push

Run all local gates before pushing:

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps
python -m compileall tests scripts
python -m pytest tests
bash -n desktop/*.sh controller/*.sh tests/integration/run.sh
```

Per the answers file (`docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_ANSWERS_2026-08-05.md`,
answer 1), the CI-equivalent commands were run instead of the block above, since the block
above is narrower than what CI actually enforces:

```bash
cargo fmt --all --check
RUSTFLAGS=-Dwarnings cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
RUSTFLAGS=-Dwarnings cargo test --locked --workspace --all-features
RUSTDOCFLAGS=-Dwarnings cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n desktop/entrypoint.sh desktop/healthcheck.sh desktop/xstartup \
  tests/desktop/run.sh tests/native/run.sh tests/worker-e2e/run.sh \
  tests/worker-text-clipboard-e2e/run.sh tests/http-e2e/run.sh \
  controller/healthcheck.sh tests/compose/run.sh tests/integration/run.sh
```

All of the above passed. Docker/VNC-backed integration suites (`tests/desktop/run.sh`,
`tests/native/run.sh`, `tests/worker-e2e/run.sh`, `tests/worker-text-clipboard-e2e/run.sh`,
`tests/http-e2e/run.sh`, `tests/compose/run.sh`, `tests/integration/run.sh`) were not run locally
and were instead verified through CI's `Secured Debian desktop and native adapter` job (F10).

If `cargo fmt --all --check` fails:

- [x] Run `cargo fmt --all`.
- [x] Review the diff.
- [x] Re-run `cargo fmt --all --check`.
- [x] Do not push unformatted Rust.

Acceptance:

- [x] Local formatter, Clippy, tests, docs, Python, and shell syntax all pass before push.

---

## F10. Push and exact-SHA GitHub validation

After pushing:

- [x] Record the final implementation commit SHA.
- [x] Wait for CI on that exact SHA.
- [x] Wait for Release Gates on that exact SHA.
- [x] Confirm CI success (job-level, via `gh run view --json jobs` on the exact SHA):
  - [x] Repository quality gates: job `Repository quality gates` — success.
  - [x] Secured Debian desktop/native job: job `Secured Debian desktop and native adapter` —
    success (this job runs the Docker/TigerVNC-backed suites, including R13 compose/integration).
  - [x] R13 Compose integration and E2E validation success (covered by the job above; not
    individually enumerated step-by-step).
- [x] Confirm Release Gates success (job-level, via `gh run view --json jobs` on the exact SHA):
  - [x] Static and supply-chain policy: job `Static and supply-chain policy` — success
    (covers full-history Gitleaks, ShellCheck, actionlint, BuildKit Dockerfile checks, Compose
    validation, and cargo-deny/advisory/license/source policy as steps within this job; not
    individually enumerated step-by-step).
  - [x] native ASan/TSan/Miri: job `Native sanitizer and Miri gates` — success.
  - [x] Trivy/SBOM/VEX image gates: job `Release image vulnerability and SBOM gates` — success.

Acceptance:

- [x] Final exact SHA has CI success.
- [x] Final exact SHA has Release Gates success.
- [x] No canceled, superseded, or previous SHA run is used as evidence.

---

## F11. Documentation and evidence update

After final validation:

- [x] Update this TODO with completion checkmarks.
- [x] Add final implementation SHA.
- [x] Add CI run ID and conclusion.
- [x] Add Release Gates run ID and conclusion.
- [x] Add short notes describing the shutdown design selected.
- [x] Add short notes describing how queue saturation is tested.
- [x] Add short notes confirming no broad fallback/bypass was introduced.

Evidence:

```text
Starting HEAD SHA: d14c59ba8e150d340ab1c84f745314a90e1e0cd1
Final implementation SHA: 7bf25d6f7da018174b9caea092743e89efd7e367
CI run: https://github.com/ekkus93/vnc-remote-control-server/actions/runs/31050462011
CI conclusion: success (jobs: Repository quality gates = success; Secured Debian desktop and
  native adapter = success)
Release Gates run: https://github.com/ekkus93/vnc-remote-control-server/actions/runs/31050463660
Release Gates conclusion: success (jobs: Static and supply-chain policy = success; Native
  sanitizer and Miri gates = success; Release image vulnerability and SBOM gates = success)
Worker shutdown design: shared Arc<AtomicBool> `shutdown_requested`, cloned onto WorkerClient and
  into the worker loop via WorkerChannels. WorkerClient::request_shutdown()/shutdown_requested()
  are the sole private helpers. DesktopWorker::shutdown() and Drop store into the flag directly
  (a store that cannot fail) instead of enqueueing WorkerCommand::Shutdown, then join
  unconditionally. The worker loop checks the flag at four points per iteration (top of loop,
  before command processing, after command processing, before poll/idle) via a shared
  shutdown_now() helper that also drains any pending command envelopes, resolving each with
  Err(DesktopError::WorkerUnavailable) instead of leaving callers to hang until their own
  timeout. WorkerCommand::Shutdown is kept only for e2e/test compatibility; receiving it now
  just sets the same flag rather than being the shutdown mechanism itself. The startup-timeout
  cleanup path in spawn_with_factory() sets the flag before its (now best-effort, optional)
  queue nudge and join. DesktopWorker::shutdown()'s timeout parameter is renamed `_timeout` and
  currently unused, since shutdown responsiveness is bounded by the worker's existing native
  poll interval/adapter timeouts rather than an additional caller-supplied bound.
Saturated queue test names: shutdown_does_not_require_command_queue_capacity,
  drop_does_not_depend_on_shutdown_command_enqueue,
  submit_rejects_after_shutdown_request_without_queue_mutation,
  out_of_band_shutdown_releases_tracked_buttons_and_keys (all in
  crates/controller-api/src/worker.rs). All four are new; all pre-existing worker.rs tests
  remain green (workspace test count: 95 before this change, 99 after — 83+3+9 pre-refactor to
  87+3+9 post-refactor), including shutdown_releases_tracked_buttons_and_keys,
  worker_commits_frame_accepts_commands_and_joins_shutdown, and
  bounded_command_queue_tracks_depth_and_rejection_without_payload_logging.
R13 status: covered by CI's `Secured Debian desktop and native adapter` job on the final exact
  SHA (success); not independently reproduced locally (no local Docker/TigerVNC run for this
  change).
No broad fallback/bypass: no command_capacity increase, no retry-until-space loop, no arbitrary
  sleep as a correctness mechanism, no CommandQueueFull-ignoring, no continue-on-error additions,
  no .gitleaksignore/Trivy/VEX allowlist changes, no weakened R13/Release Gates/Clippy/fmt gates,
  no force-push. Diff is scoped to crates/controller-api/src/worker.rs only.
```

Acceptance:

- [x] The TODO itself becomes the final handoff/evidence record.

---

## F12. Do-not-do list

Do not. Each `[x]` below confirms the prohibited action was **not** taken (compliance, not
violation):

- [x] Confirmed not done: increase `command_capacity` as the fix.
- [x] Confirmed not done: loop retry normal shutdown enqueue until space appears.
- [x] Confirmed not done: add arbitrary sleeps as the primary correctness mechanism.
- [x] Confirmed not done: ignore `CommandQueueFull` and then claim shutdown succeeded.
- [x] Confirmed not done: remove or weaken R13.
- [x] Confirmed not done: remove or weaken Release Gates.
- [x] Confirmed not done: add broad `.gitleaksignore` patterns.
- [x] Confirmed not done: add broad Trivy/VEX ignores.
- [x] Confirmed not done: add `continue-on-error` to relevant gates.
- [x] Confirmed not done: add payload-bearing logs for text, clipboard, bearer tokens, VNC
  passwords, or framebuffer data.
- [x] Confirmed not done: force-push `master`.
- [x] Confirmed not done: claim completion before exact-SHA CI and Release Gates pass.

---

## Final completion checklist

- [x] Out-of-band worker shutdown implemented.
- [x] Shutdown no longer depends on normal bounded command queue capacity.
- [x] `DesktopWorker::shutdown()` works under saturated queue conditions.
- [x] `Drop` works under saturated queue conditions.
- [x] New submissions after shutdown are rejected explicitly and without queue-depth corruption.
- [x] Pending queued tickets do not hang indefinitely during shutdown.
- [x] Input release still occurs on shutdown.
- [x] Fatal-exit semantics remain correct.
- [x] Public HTTP shutdown behavior remains stable.
- [x] Local validation passed.
- [x] CI passed on final exact SHA.
- [x] Release Gates passed on final exact SHA.
- [x] This TODO updated with final evidence.
