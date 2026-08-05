# VNC Remote Control Server Worker Shutdown Refactor Spec

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`

## 1. Purpose

This spec defines the remaining worker-shutdown hardening work discovered during the release-review Ralph loop. The release-review pass already fixed the Gitleaks false positive, builder image pinning, strict Gitleaks evidence, WebSocket sequence overflow policy, and the R13 desktop healthcheck/restart instability. The remaining unresolved engineering issue is the worker shutdown path.

The current worker still routes `WorkerCommand::Shutdown` through the same bounded command queue used by normal remote-control commands. That means shutdown can fail to enqueue if the queue is full. In the current `Drop` path, the worker may then still attempt to join the thread. That combination creates a hang risk under queue saturation.

The goal of this work is to make worker shutdown independent from normal command queue capacity, while preserving the existing fail-closed API behavior, redaction rules, input cleanup, and CI/release-gate contracts.

## 2. Baseline and known state

Use current `master` as the starting point.

Important commits from the handoff:

- `c70ba3025d511aba347962cabacb3631de88401b` — validated commit that fixed the R13 desktop healthcheck restart failure. CI and Release Gates passed on this SHA.
- `896974fbe4086a8ce93f87dfea8c1990b858132c` — failed draft attempt to add an out-of-band shutdown signal. This is a useful design reference only. It failed at `cargo fmt --check` before Clippy/tests ran and must not be treated as validated.
- `febf71a8b62b4c94d357c7baba0d381f1c273fb3` — restore commit that returned `worker.rs` to the last green worker blob while preserving the R13 healthcheck fix. Treat this as the safe code baseline before this handoff document work.

Claude Code should first check the current HEAD and current CI status. The document commit that adds this spec/TODO will create a newer SHA, so the exact HEAD may differ from the hashes above.

## 3. Current risky behavior

The current worker architecture has these relevant pieces:

- `WorkerClient::submit()` wraps one `WorkerCommand` in a `CommandEnvelope` and pushes it through a bounded `SyncSender<CommandEnvelope>` with `try_send`.
- Queue saturation returns `DesktopError::CommandQueueFull` for ordinary commands.
- `DesktopWorker::shutdown(self, timeout)` currently submits `WorkerCommand::Shutdown`, waits on the returned ticket, and then joins the native worker thread.
- `Drop for DesktopWorker` currently tries to submit `WorkerCommand::Shutdown`, waits briefly if enqueue succeeded, and then joins the worker thread.
- The worker loop processes `WorkerCommand::Shutdown` only after it successfully receives that command from the bounded queue.

Failure mode:

1. The bounded command queue is full.
2. Shutdown starts through `DesktopWorker::shutdown()` or `Drop`.
3. Enqueuing `WorkerCommand::Shutdown` fails because the queue is full.
4. The worker owner still joins the native worker thread.
5. The worker thread may never observe a shutdown command because no shutdown command entered the queue.
6. The process can hang instead of shutting down cleanly.

This is not an acceptable release-hardening state.

## 4. Required shutdown contract

### 4.1 Shutdown signaling

Shutdown must have an out-of-band signal that does not depend on `command_capacity` or on successful enqueue of `WorkerCommand::Shutdown`.

Acceptable designs include:

- `Arc<AtomicBool>` shutdown flag shared between `DesktopWorker`, `WorkerClient`, and the worker loop;
- a dedicated shutdown channel with nonblocking semantics that cannot be starved behind the normal command queue;
- an equivalent mechanism that proves the same properties.

The simplest recommended design is an `Arc<AtomicBool>` named along the lines of `shutdown_requested`.

### 4.2 Queue independence

The following must be true:

- Shutdown request must succeed even when `commands.try_send(...)` would return `TrySendError::Full`.
- Shutdown request must not increment `rejected_commands` as though it were a normal user command.
- Shutdown request must not publish an overload event merely because the normal command queue is full.
- Shutdown request must not log or expose payload data from pending commands.

### 4.3 Worker loop behavior

The worker loop must check the out-of-band shutdown signal:

- before attempting a new VNC connection;
- before processing ordinary queued commands;
- after processing a queued command;
- before or after each native poll cycle;
- while idle with no active session.

When shutdown is observed, the worker must:

- stop accepting new normal work;
- release tracked input state by calling the existing input cleanup path;
- invalidate the framebuffer as today;
- transition to `ConnectionState::Stopped`;
- avoid setting `fatal_exit = true` for an orderly shutdown;
- complete or disconnect pending command tickets so callers do not wait until arbitrary timeouts.

### 4.4 Command submission after shutdown begins

After shutdown is requested, `WorkerClient::submit()` must reject ordinary commands before enqueueing them.

The internal domain error may remain `DesktopError::WorkerUnavailable` to avoid public API churn, unless the implementation deliberately adds a more specific `DesktopError::ShuttingDown` and updates all mappings/tests/docs accordingly.

The externally visible HTTP shutdown contract must remain stable:

- `HttpState::begin_shutdown()` continues to make `/health/ready` fail closed.
- Authenticated mutating routes after HTTP shutdown begins continue returning the existing `shutting_down` error envelope.
- Do not change the public API surface unless required by tests and documentation.

### 4.5 Drop behavior

`Drop for DesktopWorker` must not depend on normal command queue capacity.

Required behavior:

- `Drop` must request shutdown through the out-of-band signal.
- `Drop` may optionally try to enqueue or wake the worker, but enqueue failure must not be the only shutdown mechanism.
- `Drop` must not silently ignore shutdown failure and then block forever behind a full command queue.
- If the implementation still joins in `Drop`, the worker loop must be structured so mocks prove the join can complete with a saturated queue.

Native calls are expected to remain bounded by the existing native adapter timeouts and worker poll interval. Do not introduce unbounded native calls.

### 4.6 Startup timeout behavior

The startup-timeout cleanup path must also use the out-of-band shutdown mechanism or another fail-closed path that does not depend solely on the normal command queue.

If startup times out before `DesktopWorker` is fully constructed, cleanup must not rely on successfully enqueueing a shutdown command into a potentially full or disconnected normal queue.

### 4.7 Input cleanup

Shutdown must preserve the existing safety property: tracked pressed buttons and keys are released before the worker exits when a session exists.

Regression coverage must prove that out-of-band shutdown still calls the input release path.

### 4.8 Metrics and snapshots

The shutdown refactor must preserve existing observable status semantics:

- `WorkerSnapshot.state` eventually becomes `ConnectionState::Stopped`.
- `fatal_exit` remains `false` for requested shutdown.
- `fatal_exit` remains available for unrequested exits and protocol/state-machine failures.
- `rejected_commands` still counts normal command queue saturation only.
- `command_queue_depth` must not be left permanently inflated by commands drained during shutdown.

If pending command envelopes are explicitly drained during shutdown, decrement `command_queue_depth` for each drained envelope and send `Err(DesktopError::WorkerUnavailable)` to each completion sender. Dropping envelopes so callers see `WorkerUnavailable` through disconnected completion receivers is acceptable only if `command_queue_depth` cannot remain misleading after stop.

### 4.9 Logging and redaction

Do not add logs that include command payloads, text input, clipboard contents, bearer tokens, VNC password, or raw framebuffer bytes.

Allowed logs:

- shutdown requested;
- shutdown observed by worker;
- pending command count drained;
- worker joined;
- bounded timeout/failure categories without payloads.

### 4.10 What not to do

Do not:

- increase `command_capacity` to hide the bug;
- retry normal shutdown enqueue in a loop until the queue has space;
- sleep arbitrary fixed delays as the primary shutdown mechanism;
- ignore `CommandQueueFull` and still claim shutdown succeeded;
- add `continue-on-error`, broad CI bypasses, broad scanner allowlists, or test ignores;
- weaken R13, Release Gates, Gitleaks, Trivy, Miri, sanitizer, Clippy, or formatting gates;
- force-push master;
- treat commit `896974fbe4086a8ce93f87dfea8c1990b858132c` as complete without reformatting, compiling, and validating it.

## 5. Recommended implementation shape

This is the recommended design, but Claude Code may choose an equivalent design if it proves the same behavior.

### 5.1 WorkerClient additions

Add a shared shutdown signal:

```rust
shutdown_requested: Arc<AtomicBool>,
```

Add private helper methods inside `worker.rs` if useful:

```rust
fn request_shutdown(&self) {
    self.shutdown_requested.store(true, Ordering::Release);
}

fn shutdown_requested(&self) -> bool {
    self.shutdown_requested.load(Ordering::Acquire)
}
```

Update `WorkerClient::submit()` so it checks the flag before assigning command IDs or incrementing queue depth:

```rust
if self.shutdown_requested() {
    return Err(DesktopError::WorkerUnavailable);
}
```

It may also check again immediately before `try_send` to reduce races. If the second check trips after the command ID was allocated, ensure queue depth is not incremented or is corrected.

### 5.2 WorkerChannels additions

Pass the same shutdown signal into the worker loop, either directly or through `WorkerChannels`:

```rust
shutdown_requested: Arc<AtomicBool>,
```

### 5.3 DesktopWorker::shutdown

Change shutdown so it does not require queue space:

```rust
pub fn shutdown(mut self, timeout: Duration) -> Result<(), DesktopError> {
    self.client.request_shutdown();
    // Optional best-effort wake only; failure must not fail shutdown.
    // Do not require WorkerCommand::Shutdown to enqueue.
    self.join_worker()
}
```

The `timeout` parameter may become unused. If it remains part of the public method signature, either keep the parameter name as `_timeout` or use it meaningfully. Avoid warning-suppression hacks.

A better version can use a bounded join mechanism if introduced carefully, but do not overcomplicate the fix.

### 5.4 Drop

Change `Drop` to request out-of-band shutdown before join:

```rust
impl Drop for DesktopWorker {
    fn drop(&mut self) {
        if self.join.is_none() {
            return;
        }
        self.client.request_shutdown();
        let _ = self.join_worker();
    }
}
```

If a wake mechanism is needed, it must be best-effort only and must not be the correctness path.

### 5.5 Worker loop

At the top of each loop iteration:

```rust
if shutdown_requested.load(Ordering::Acquire) {
    orderly_shutdown = true;
    drain_pending_commands(...);
    break;
}
```

Also check before connection attempts and after command processing. Keep `WorkerCommand::Shutdown` support if useful for compatibility, but it should set the same out-of-band signal and no longer be the only shutdown path.

Add a helper if draining is implemented:

```rust
fn drain_pending_commands(
    commands: &Receiver<CommandEnvelope>,
    command_queue_depth: &AtomicUsize,
) {
    while let Ok(envelope) = commands.try_recv() {
        command_queue_depth.fetch_sub(1, Ordering::AcqRel);
        let _ = envelope.completion.send(Err(DesktopError::WorkerUnavailable));
    }
}
```

If this helper is implemented, make it private to `worker.rs` and cover it through worker tests rather than exposing it.

## 6. Required tests

Add targeted Rust unit tests in `crates/controller-api/src/worker.rs`. At minimum:

1. `shutdown_does_not_require_command_queue_capacity`
   - Configure `command_capacity = 1`.
   - Fill/saturate the normal command queue or otherwise prove `WorkerCommand::Shutdown` could not be enqueued through the normal path.
   - Request shutdown.
   - Assert the worker stops and joins.
   - Assert `fatal_exit == false`.

2. `drop_does_not_depend_on_shutdown_command_enqueue`
   - Create a situation where normal command enqueue would fail.
   - Drop the worker.
   - Use a bounded test harness so a hang becomes a test failure.
   - Assert the drop thread returns.

3. `submit_rejects_after_shutdown_request_without_queue_mutation`
   - Request shutdown through the private helper or full worker shutdown path.
   - Attempt a normal command submission.
   - Assert `Err(DesktopError::WorkerUnavailable)` or the chosen explicit shutdown error.
   - Assert queue depth and rejected-command metrics are not incorrectly incremented.

4. `out_of_band_shutdown_releases_tracked_buttons_and_keys`
   - Hold a button/key down.
   - Trigger out-of-band shutdown.
   - Assert release events are recorded before the worker exits.

Existing tests must continue to pass, especially:

- `shutdown_releases_tracked_buttons_and_keys`;
- normal connected worker command execution;
- transport reconnect behavior;
- authentication failure behavior;
- stalled connection invalidation/reconnect behavior;
- bounded command queue rejection behavior.

## 7. Required validation

Before marking this complete, run locally:

```bash
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
RUSTDOCFLAGS="-D warnings" cargo doc --workspace --no-deps
python -m compileall tests scripts
python -m pytest tests
bash -n desktop/*.sh controller/*.sh tests/integration/run.sh
```

Then push to `master` and require exact-SHA GitHub validation:

- CI must pass on the final exact SHA.
- Release Gates must pass on the final exact SHA.
- R13 Compose integration and E2E validation must pass.
- Static policy, full-history Gitleaks, ShellCheck, actionlint, BuildKit Dockerfile checks, Compose validation, cargo-deny policy, native ASan/TSan/Miri gates, image Trivy/SBOM/VEX gates must remain enabled and green.

## 8. Completion definition

This work is complete only when all of the following are true:

- Shutdown no longer depends on normal bounded command queue capacity.
- Saturated-queue shutdown regression tests exist and pass.
- Drop path cannot reproduce the full-queue shutdown hang in tests.
- Input release on shutdown still works.
- No public API behavior is weakened.
- No payload-bearing logs or diagnostics are added.
- Current `master` has final exact-SHA CI success.
- Current `master` has final exact-SHA Release Gates success.
- The companion TODO is updated with exact commit SHA, run IDs, and job conclusions.
