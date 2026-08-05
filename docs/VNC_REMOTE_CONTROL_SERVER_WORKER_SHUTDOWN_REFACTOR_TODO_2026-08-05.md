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

- [ ] Check out latest `master`.
- [ ] Confirm the current HEAD SHA.
- [ ] Confirm `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md` exists.
- [ ] Confirm this TODO exists.
- [ ] Confirm `crates/controller-api/src/worker.rs` is currently the safe restored version, not the unvalidated draft from `896974f...`.
- [ ] Review the current worker shutdown implementation:
  - [ ] `WorkerClient::submit()` uses the normal bounded `SyncSender<CommandEnvelope>`.
  - [ ] `DesktopWorker::shutdown()` still submits `WorkerCommand::Shutdown` through that queue.
  - [ ] `Drop for DesktopWorker` still tries normal queue shutdown before joining.
  - [ ] Worker loop only exits for shutdown after receiving `WorkerCommand::Shutdown` or command channel disconnect.
- [ ] Record the starting HEAD SHA in your implementation notes.

Acceptance:

- [ ] You can explain the full-queue shutdown failure mode before editing code.

---

## F1. Inspect the failed draft without trusting it

- [ ] Inspect failed draft commit `896974fbe4086a8ce93f87dfea8c1990b858132c`.
- [ ] Identify useful design pieces, if any:
  - [ ] shared out-of-band shutdown signal;
  - [ ] submit rejection after shutdown request;
  - [ ] worker-loop shutdown checks;
  - [ ] saturated queue tests.
- [ ] Do not cherry-pick blindly.
- [ ] Re-implement cleanly or apply the patch in a local checkout where `cargo fmt` can run.
- [ ] Run formatter before committing.

Acceptance:

- [ ] No unformatted code from the draft reaches `master`.
- [ ] No unvalidated code is claimed complete.

---

## F2. Add out-of-band shutdown state

Recommended implementation:

- [ ] Add a shared `Arc<AtomicBool>` shutdown flag to the worker runtime.
- [ ] Store a clone on `WorkerClient`, likely as:

```rust
shutdown_requested: Arc<AtomicBool>,
```

- [ ] Pass another clone to the worker loop through `WorkerChannels` or as a direct `run_worker` argument.
- [ ] Initialize it to `false` in `DesktopWorker::spawn_with_factory()`.
- [ ] Add private helper methods in `worker.rs` if useful:

```rust
fn request_shutdown(&self) {
    self.shutdown_requested.store(true, Ordering::Release);
}

fn shutdown_requested(&self) -> bool {
    self.shutdown_requested.load(Ordering::Acquire)
}
```

- [ ] Keep helpers private unless a public API is genuinely needed.

Acceptance:

- [ ] Shutdown can be requested without sending any normal command.
- [ ] The design is thread-safe and uses explicit atomic ordering.

---

## F3. Reject new commands after shutdown begins

- [ ] Update `WorkerClient::submit()` so it checks the out-of-band shutdown signal before:
  - [ ] allocating a command ID;
  - [ ] creating a completion channel;
  - [ ] incrementing `command_queue_depth`;
  - [ ] calling `try_send`.
- [ ] Return `DesktopError::WorkerUnavailable` for ordinary commands submitted after shutdown begins, unless you intentionally add a new explicit `DesktopError::ShuttingDown` and update all mappings/docs/tests.
- [ ] Do not increment `rejected_commands` for shutdown-state rejection unless you deliberately define a new metric. The existing `rejected_commands` metric should remain queue-saturation-specific.
- [ ] Consider a second shutdown check immediately before `try_send` to reduce races; if added, maintain queue-depth correctness.

Acceptance:

- [ ] Command submission after shutdown is explicit and nonblocking.
- [ ] Queue depth is not inflated by rejected post-shutdown commands.
- [ ] No command payloads are logged when rejecting post-shutdown commands.

---

## F4. Refactor DesktopWorker shutdown and Drop

- [ ] Update `DesktopWorker::shutdown()` so it does not require normal queue capacity.
- [ ] It must request shutdown through the out-of-band signal first.
- [ ] It may optionally attempt a best-effort wake through the normal queue, but enqueue failure must not fail shutdown and must not be the correctness path.
- [ ] Keep the public signature unless you intentionally update all call sites:

```rust
pub fn shutdown(mut self, timeout: Duration) -> Result<(), DesktopError>
```

- [ ] If `timeout` becomes unused, rename it to `_timeout` or use it meaningfully. Do not leave warnings.
- [ ] Update `Drop for DesktopWorker`:
  - [ ] request out-of-band shutdown;
  - [ ] avoid depending on successful `WorkerCommand::Shutdown` enqueue;
  - [ ] join only after shutdown is requested;
  - [ ] avoid hidden infinite wait caused by full normal queue.
- [ ] Update startup-timeout cleanup so it does not rely solely on enqueueing shutdown into the normal queue.

Acceptance:

- [ ] `DesktopWorker::shutdown()` works when the normal queue is full.
- [ ] `Drop` requests shutdown independently of the normal queue.
- [ ] No normal queue capacity change is used to hide the bug.

---

## F5. Update worker loop shutdown behavior

- [ ] Pass the shutdown signal into `run_worker()`.
- [ ] Check shutdown at the top of the main loop.
- [ ] Check shutdown before starting a new VNC connection attempt.
- [ ] Check shutdown before processing ordinary queued commands.
- [ ] Check shutdown after processing a command.
- [ ] Check shutdown around poll/idle paths as practical.
- [ ] Preserve `WorkerCommand::Shutdown` handling as compatibility if useful, but make it set/observe the same out-of-band shutdown path.
- [ ] Preserve `orderly_shutdown = true` semantics when shutdown was requested.
- [ ] Ensure requested shutdown does not set `fatal_exit = true`.
- [ ] Preserve final cleanup:
  - [ ] input release;
  - [ ] framebuffer invalidation;
  - [ ] transition to `ConnectionState::Stopped`.

Acceptance:

- [ ] Worker exits cleanly after out-of-band shutdown.
- [ ] Worker does not continue reconnecting after shutdown is requested.
- [ ] Worker does not set fatal exit for requested shutdown.

---

## F6. Drain or disconnect pending commands safely

Choose one implementation strategy and prove it with tests.

Preferred strategy:

- [ ] Add a private `drain_pending_commands(...)` helper.
- [ ] On shutdown, drain pending command envelopes from the normal queue.
- [ ] For each drained envelope:
  - [ ] decrement `command_queue_depth`;
  - [ ] send `Err(DesktopError::WorkerUnavailable)` on the completion sender;
  - [ ] do not inspect or log payloads.

Alternative strategy:

- [ ] Allow pending envelopes to be dropped so command tickets see a disconnected completion channel.
- [ ] Prove `CommandTicket::wait()` returns `DesktopError::WorkerUnavailable` rather than timing out.
- [ ] Prove `command_queue_depth` does not remain misleading after stop.

Acceptance:

- [ ] Pending command tickets do not hang until arbitrary caller timeouts during shutdown.
- [ ] Queue depth accounting remains coherent.
- [ ] No pending command payloads are logged or exposed.

---

## F7. Preserve HTTP shutdown behavior

- [ ] Confirm `HttpState::begin_shutdown()` still controls public HTTP shutdown readiness.
- [ ] Confirm `/health/ready` fails closed after HTTP shutdown begins.
- [ ] Confirm authenticated mutating routes after HTTP shutdown begins continue returning existing `shutting_down` error envelopes.
- [ ] Do not change public error codes unless unavoidable.
- [ ] If you add `DesktopError::ShuttingDown`, update:
  - [ ] `remote-desktop-core` error enum;
  - [ ] HTTP domain error mapping;
  - [ ] tests;
  - [ ] docs/OpenAPI if affected.

Acceptance:

- [ ] Existing R13 shutdown expectations still pass.
- [ ] Public API behavior is not weakened.

---

## F8. Add regression tests

Add tests in `crates/controller-api/src/worker.rs`.

Required tests:

- [ ] `shutdown_does_not_require_command_queue_capacity`
  - [ ] Configure small `command_capacity`, preferably `1`.
  - [ ] Saturate or prove saturation of the normal command queue.
  - [ ] Request shutdown.
  - [ ] Assert shutdown completes and worker reaches `Stopped`.
  - [ ] Assert `fatal_exit == false`.

- [ ] `drop_does_not_depend_on_shutdown_command_enqueue`
  - [ ] Arrange a condition where normal shutdown command enqueue would fail or be irrelevant.
  - [ ] Drop the worker from a bounded harness/thread.
  - [ ] Assert the drop path returns before a clear test deadline.
  - [ ] Do not write a test that can hang CI forever.

- [ ] `submit_rejects_after_shutdown_request_without_queue_mutation`
  - [ ] Request shutdown.
  - [ ] Try submitting a normal command.
  - [ ] Assert explicit rejection.
  - [ ] Assert queue depth is not incremented.
  - [ ] Assert rejected-command queue saturation metric is not incorrectly incremented.

- [ ] `out_of_band_shutdown_releases_tracked_buttons_and_keys`
  - [ ] Use `RecordingSession` or equivalent.
  - [ ] Press/hold a button and key.
  - [ ] Trigger out-of-band shutdown.
  - [ ] Assert release events are recorded.

Also keep existing tests green:

- [ ] `worker_commits_frame_accepts_commands_and_joins_shutdown`
- [ ] `shutdown_releases_tracked_buttons_and_keys`
- [ ] `bounded_command_queue_tracks_depth_and_rejection_without_payload_logging`
- [ ] reconnect/authentication/stall tests

Acceptance:

- [ ] Tests fail against the old queue-dependent shutdown path, or at least specifically exercise the newly guaranteed behavior.
- [ ] Tests are deterministic and do not rely on broad sleeps when a channel/barrier/deadline can be used.

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

If `cargo fmt --all --check` fails:

- [ ] Run `cargo fmt --all`.
- [ ] Review the diff.
- [ ] Re-run `cargo fmt --all --check`.
- [ ] Do not push unformatted Rust.

Acceptance:

- [ ] Local formatter, Clippy, tests, docs, Python, and shell syntax all pass before push.

---

## F10. Push and exact-SHA GitHub validation

After pushing:

- [ ] Record the final implementation commit SHA.
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
- [ ] No canceled, superseded, or previous SHA run is used as evidence.

---

## F11. Documentation and evidence update

After final validation:

- [ ] Update this TODO with completion checkmarks.
- [ ] Add final implementation SHA.
- [ ] Add CI run ID and conclusion.
- [ ] Add Release Gates run ID and conclusion.
- [ ] Add short notes describing the shutdown design selected.
- [ ] Add short notes describing how queue saturation is tested.
- [ ] Add short notes confirming no broad fallback/bypass was introduced.

Suggested evidence section to fill in:

```text
Final implementation SHA:
CI run:
CI conclusion:
Release Gates run:
Release Gates conclusion:
Worker shutdown design:
Saturated queue test names:
R13 status:
```

Acceptance:

- [ ] The TODO itself becomes the final handoff/evidence record.

---

## F12. Do-not-do list

Do not:

- [ ] Increase `command_capacity` as the fix.
- [ ] Loop retry normal shutdown enqueue until space appears.
- [ ] Add arbitrary sleeps as the primary correctness mechanism.
- [ ] Ignore `CommandQueueFull` and then claim shutdown succeeded.
- [ ] Remove or weaken R13.
- [ ] Remove or weaken Release Gates.
- [ ] Add broad `.gitleaksignore` patterns.
- [ ] Add broad Trivy/VEX ignores.
- [ ] Add `continue-on-error` to relevant gates.
- [ ] Add payload-bearing logs for text, clipboard, bearer tokens, VNC passwords, or framebuffer data.
- [ ] Force-push `master`.
- [ ] Claim completion before exact-SHA CI and Release Gates pass.

---

## Final completion checklist

- [ ] Out-of-band worker shutdown implemented.
- [ ] Shutdown no longer depends on normal bounded command queue capacity.
- [ ] `DesktopWorker::shutdown()` works under saturated queue conditions.
- [ ] `Drop` works under saturated queue conditions.
- [ ] New submissions after shutdown are rejected explicitly and without queue-depth corruption.
- [ ] Pending queued tickets do not hang indefinitely during shutdown.
- [ ] Input release still occurs on shutdown.
- [ ] Fatal-exit semantics remain correct.
- [ ] Public HTTP shutdown behavior remains stable.
- [ ] Local validation passed.
- [ ] CI passed on final exact SHA.
- [ ] Release Gates passed on final exact SHA.
- [ ] This TODO updated with final evidence.
