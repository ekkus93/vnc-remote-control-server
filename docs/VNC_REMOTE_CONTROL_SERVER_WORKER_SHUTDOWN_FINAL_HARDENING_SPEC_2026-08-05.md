# VNC Remote Control Server Worker Shutdown Final Hardening Spec

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Baseline reviewed for this specification: `7c80b696643629005d5b8e1d7a5c5d0feed12d57`

Companion TODO:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`

Related documents:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_SPEC_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`

## 1. Purpose

The previous two shutdown passes made substantial and correct improvements:

- worker shutdown authority moved out of the bounded command queue into an out-of-band `Arc<AtomicBool>`;
- `DesktopWorker::shutdown(timeout)` now enforces its timeout;
- startup-timeout cleanup and `Drop for DesktopWorker` use bounded worker-exit waits;
- ordinary commands observed after shutdown begins are rejected before native execution;
- deterministic controlled-poll tests were added;
- CI, Release Gates, and R13 passed on the implementation and evidence commits.

A subsequent code review found that the worker-object lifecycle is better, but the complete process lifecycle is not yet fully bounded or race-safe. This specification defines the final hardening pass required before the shutdown work can be considered complete.

This pass must fix the remaining defects rather than repeat or replace the existing out-of-band shutdown architecture.

## 2. Review findings that define this scope

### 2.1 High severity: process shutdown can still hang after worker timeout

`DesktopWorker::shutdown(timeout)` can return `DesktopError::Timeout` and deliberately detach a stuck worker. The process then calls `event_bridge.join()` before propagating that timeout.

The bridge currently blocks on the worker event receiver and its join is unbounded. If the detached worker remains alive and retains the event sender, the event bridge remains blocked, `event_bridge.join()` never returns, and the process never reaches the already-produced worker timeout error.

The complete process shutdown path must therefore have an event-bridge stop mechanism independent of worker exit and a bounded bridge join.

### 2.2 Medium severity: command queue-depth accounting is not race-safe

The current code manually increments and decrements a shared `AtomicUsize`. That design has multiple incorrect interleavings:

1. A compatibility `WorkerCommand::Shutdown` envelope can stop the worker without draining commands queued behind it. Those envelopes are eventually dropped, but their queue-depth increments are not reversed.
2. A submitter can pass the final shutdown check, then enqueue after the worker performs its final drain but before the receiver is dropped. The command is not executed, but the counter can remain stale.
3. Startup cleanup sends `CommandEnvelope::shutdown_without_waiter()` directly without incrementing queue depth, while the worker currently decrements depth for every received envelope. If that internal envelope is received while depth is zero, `fetch_sub(1)` can underflow the counter.

Queue depth must become ownership-based rather than manually balanced across every branch.

### 2.3 Medium severity: final input-release failures are silent

`InputController::release_all()` ignores failed button and key release operations and then clears all tracked pressed state. A live but failing VNC session can therefore retain a pressed modifier or mouse button while the controller forgets what remains pressed. No diagnostic records the failure.

Final release remains best-effort because a disconnected native session cannot guarantee delivery, but failure must be explicit, payload-free, and state-aware.

### 2.4 Medium severity: required tests do not always prove their names

The existing hardening tests are useful, but several test only helper functions rather than complete paths:

- startup cleanup is tested by calling the cleanup helper directly rather than timing out `spawn_with_factory()`;
- receive-side rejection is tested by calling `classify_received_command()` directly rather than driving the worker loop;
- Drop timeout tests prove boundedness but do not assert the structured diagnostic;
- the controlled session's execution counter does not count `RequestFullRefresh`, even though that command is used by the saturated-queue test;
- no test constructs a real event bridge while a worker shutdown times out;
- no deterministic test exercises the queue-depth underflow and enqueue-after-final-drain cases.

The final pass must add full-path, bounded, deterministic evidence.

### 2.5 Low/medium severity: startup cleanup loses error specificity

Startup cleanup logs join failure but returns no result to `spawn_with_factory()`. The startup-disconnected branch also suppresses bounded wait and join results. Meaningful thread panic or cleanup failure must not be silently collapsed into an unrelated result.

### 2.6 Low severity: framebuffer duplicate detection has a potential cost

The R13 repair correctly prevents byte-identical frames from advancing screenshot ETags. Full-frame replacement can compare a large framebuffer while holding the store write lock, and dirty commits clone and compare the complete framebuffer.

The semantics are correct and must be preserved. This pass should measure or document the cost and optimize only if evidence justifies a change.

### 2.7 Documentation defect: the previous TODO and evidence overstate completion

The original hardening TODO remains unchecked, while a separate evidence document declares completion and states that queue-depth accounting is coherent. The review disproved that claim for several interleavings.

The historical record must be corrected without deleting useful prior evidence.

## 3. Goals

This pass must:

1. bound the complete process shutdown sequence, including the worker event bridge;
2. make queue-depth accounting exact by construction for enqueue, send failure, receive, drain, receiver drop, compatibility shutdown, and shutdown races;
3. make failed input release observable without exposing key, text, coordinate, clipboard, credential, or framebuffer payloads;
4. propagate startup cleanup and join failures meaningfully;
5. replace helper-only evidence with full-path deterministic tests where practical;
6. preserve HTTP shutdown, VNC behavior, framebuffer ETags, R13, and security boundaries;
7. correct the previous TODO/evidence record;
8. require CI and Release Gates on the same final repository-tip SHA.

## 4. Non-goals

Do not:

- remove the out-of-band worker shutdown flag;
- make the normal bounded command queue authoritative for shutdown;
- remove `WorkerCommand::Shutdown` in this pass;
- redesign the complete VNC worker, HTTP router, or WebSocket protocol;
- add a forceful thread-termination mechanism—safe Rust cannot kill an arbitrary stuck native thread;
- weaken R13 conditional screenshot behavior;
- change framebuffer revision semantics back to native-update-count semantics;
- add retry loops that can block indefinitely;
- expose sensitive command or input contents in logs or diagnostics;
- weaken CI, release, dependency, secret, vulnerability, sanitizer, or integration gates.

## 5. Required final architecture

### 5.1 Independently stoppable event bridge

`EventBridge` must no longer depend exclusively on worker event-channel disconnection to terminate.

Recommended shape:

```rust
pub struct EventBridge {
    stop_requested: Arc<AtomicBool>,
    exited: Option<Receiver<()>>,
    join: Option<JoinHandle<()>>,
}
```

An equivalent design using a bounded stop channel is acceptable.

Required behavior:

- `EventBridge::start()` creates a bridge stop signal and bridge-exit notification.
- The bridge thread checks the stop signal independently of worker channel closure.
- The bridge must not remain blocked indefinitely in `WorkerEvents::recv()`.
- The bridge loop should use `WorkerEvents::recv_timeout()` with a small explicit interval, or another bounded wait/select design.
- A bridge-exit guard must notify the owner on normal return and Rust unwinding paths.
- `EventBridge::shutdown(timeout)` must:
  - request bridge stop first;
  - wait for bridge-exit notification using the caller-supplied timeout;
  - join only after exit notification;
  - return an error on timeout or panic;
  - log a payload-free timeout or join-failure event;
  - deliberately detach after timeout so its own `Drop` path cannot unboundedly join.
- `Drop for EventBridge` must never perform an unbounded join. It may use a small internal deadline, log, and detach.

Recommended constants:

```rust
const EVENT_BRIDGE_POLL_INTERVAL: Duration = Duration::from_millis(50);
const EVENT_BRIDGE_DROP_TIMEOUT: Duration = Duration::from_secs(2);
```

Different bounded values are acceptable if justified and covered by tests.

### 5.2 Process shutdown orchestration

The process must perform every cleanup step even if an earlier step fails, but no cleanup may be unbounded.

Required shutdown order:

1. mark `HttpState` as shutting down so readiness and mutating routes fail closed;
2. stop accepting HTTP connections and drain them within the configured HTTP grace period;
3. request and await worker shutdown within the configured worker timeout;
4. request and await event-bridge shutdown within an explicit bridge timeout, regardless of whether worker shutdown succeeded or timed out;
5. report the primary error and log any secondary cleanup failures.

The process must not call an unbounded bridge join after a worker timeout.

Recommended implementation:

- extract the final synchronous cleanup into a small testable coordinator or helper;
- capture `server_result`, `worker_result`, and `bridge_result` separately;
- always attempt worker and bridge cleanup;
- use deterministic error precedence:
  1. server/runtime failure;
  2. worker shutdown failure;
  3. event-bridge shutdown failure;
- log secondary failures with structured, payload-free events so they are not discarded.

A worker timeout may detach the worker. Once the bounded bridge is stopped and the main function returns the timeout, normal process termination will terminate remaining detached threads. Do not pretend the worker thread was successfully joined.

### 5.3 Ownership-based queue-depth accounting

Replace manual queue-depth increments/decrements with a permit owned by each queued envelope.

Recommended shape:

```rust
struct QueueDepthPermit {
    depth: Arc<AtomicUsize>,
    active: bool,
}

pub(super) struct CommandEnvelope {
    pub(super) command: WorkerCommand,
    pub(super) completion: SyncSender<Result<(), DesktopError>>,
    queue_depth: Option<QueueDepthPermit>,
}
```

Required behavior:

- creating an envelope that will attempt queue insertion acquires exactly one permit and increments depth exactly once;
- `try_send()` failure returns or drops the envelope, causing the permit to decrement automatically;
- immediately after successful `try_recv()`, the worker marks the envelope dequeued and releases its permit before classification/execution;
- draining a queued envelope releases its permit automatically;
- dropping the receiver and all queued envelopes releases every permit automatically;
- compatibility shutdown envelopes use the same counted construction path or another path that cannot be decremented without a matching increment;
- no raw `fetch_add`/`fetch_sub` queue-depth bookkeeping remains outside the permit implementation;
- permit release must detect and log an impossible underflow rather than wrapping silently;
- queue depth may be momentarily approximate during concurrent operations but must converge exactly to the actual number of queued envelopes;
- final depth must be zero after worker exit and queue destruction.

The permit must not inspect or log the command payload.

### 5.4 Compatibility shutdown behavior

`WorkerCommand::Shutdown` remains compatibility-only.

When received:

- release its queue permit as a normal dequeue;
- set the out-of-band shutdown flag;
- acknowledge success where possible;
- drain commands already queued behind it with `WorkerUnavailable`;
- exit through orderly shutdown semantics;
- do not execute or log queued command payloads;
- leave queue depth at zero after queue destruction.

### 5.5 Startup cleanup result propagation

Refactor startup cleanup to return a meaningful result or outcome.

Recommended outcomes:

```rust
enum StartupCleanupOutcome {
    Exited,
    TimedOut,
}
```

with thread panic/join failure represented as `Err(DesktopError::WorkerUnavailable)` or an equivalent existing error.

Required behavior:

- startup acknowledgement timeout stores the out-of-band flag first;
- the queue nudge remains best-effort and uses correct queue-depth ownership;
- cleanup waits for worker exit only for a bounded deadline;
- observed exit is followed by join and panic collection;
- cleanup timeout logs and detaches, then the caller returns `DesktopError::Timeout`;
- observed join panic returns a clear startup failure rather than being hidden behind timeout;
- startup-channel disconnection handles exit wait and join results explicitly;
- no branch uses `_ =` to suppress a meaningful lifecycle wait/join failure.

### 5.6 Observable input-release results

`InputController::release_all()` must return a payload-free report rather than silently clearing all state.

Recommended report:

```rust
struct InputReleaseReport {
    pointer_release_failed: bool,
    key_release_failures: usize,
}
```

Required behavior:

- successful releases are removed from tracked local state;
- failed releases remain tracked until the caller explicitly abandons the session;
- no release loop retries indefinitely;
- `LoopState::release_input()` records a structured warning when any release fails;
- diagnostics may include counts and broad operation type only;
- diagnostics must not include key values, coordinates, text, clipboard data, credentials, framebuffer data, or screenshots;
- when the native session is being irreversibly discarded, the caller may explicitly clear unresolved state only after logging that the releases could not be confirmed;
- normal successful shutdown behavior and existing input-release tests must remain intact.

Suggested event names:

- `worker_input_release_incomplete`
- `worker_input_release_abandoned`

### 5.7 Structured lifecycle diagnostics

Required payload-free events or equivalent diagnostics:

- `desktop_worker_shutdown_timeout`
- `desktop_worker_drop_shutdown_timeout`
- `desktop_worker_startup_cleanup_timeout`
- `desktop_worker_join_failed`
- `event_bridge_shutdown_timeout`
- `event_bridge_drop_shutdown_timeout`
- `event_bridge_join_failed`
- `worker_command_queue_depth_underflow`
- `worker_input_release_incomplete`
- process-level secondary cleanup failure events

Tests must capture and assert the important timeout/join diagnostics rather than relying only on visual log inspection.

## 6. Required deterministic tests

Tests may be placed in the existing split worker modules, event tests, or a new lifecycle test module. All synchronization must use explicit channels, barriers, or bounded deadlines. Sleeps may only provide small scheduling margins, not establish the correctness state.

### 6.1 Process and event-bridge tests

Add:

- `process_shutdown_remains_bounded_after_worker_timeout`
  - start a controlled worker that remains blocked beyond its shutdown timeout;
  - start a real `EventBridge` from that worker's event receiver;
  - execute the same worker/bridge cleanup sequence used by production;
  - assert the worker returns `DesktopError::Timeout`;
  - assert bridge shutdown completes or returns its own bounded error;
  - assert the complete coordinator returns before a clear outer deadline.

- `event_bridge_shutdown_does_not_require_worker_sender_drop`
  - keep a worker event sender alive;
  - request bridge shutdown;
  - prove the bridge exits before timeout without requiring channel disconnection.

- `event_bridge_drop_is_bounded_and_observable`
  - arrange a controlled bridge stall if practical;
  - assert Drop returns within its deadline;
  - assert the timeout diagnostic.

### 6.2 Queue-depth tests

Add deterministic tests for:

- `internal_shutdown_envelope_cannot_underflow_queue_depth`
- `compatibility_shutdown_drains_commands_behind_it_and_depth_returns_to_zero`
- `receiver_drop_releases_all_queue_depth_permits`
- `send_failure_releases_queue_depth_permit`
- `command_received_after_shutdown_releases_depth_before_rejection`
- `submit_racing_final_shutdown_drain_converges_depth_to_zero`

The final race test may use a test-only barrier immediately before `try_send()` or an equivalent deterministic queue abstraction. Do not rely on probabilistic repeated loops.

### 6.3 Full worker-path tests

Strengthen or replace helper-only tests:

- `startup_timeout_cleanup_does_not_unbounded_join`
  - trigger the actual `DesktopWorker::spawn_with_factory()` startup timeout path;
  - assert the public result and deadline;
  - assert cleanup timeout/join diagnostics.

- `queued_command_received_after_shutdown_is_rejected_without_execution`
  - drive the real worker loop with a controlled session;
  - assert the ticket result, zero native execution count, coherent queue depth, `Stopped`, and `fatal_exit == false`.

- `drop_logs_or_records_worker_join_timeout_without_blocking`
  - capture and assert `desktop_worker_drop_shutdown_timeout` or the chosen equivalent.

- `deterministic_saturated_queue_shutdown_still_completes`
  - ensure the controlled session counts `RequestFullRefresh` execution as well as pointer/key/clipboard operations;
  - assert the queued command was not executed.

### 6.4 Input-release tests

Add:

- `release_all_reports_failed_pointer_release_without_silent_clear`
- `release_all_retains_failed_keys_until_explicit_abandon`
- `shutdown_logs_incomplete_input_release_without_payloads`
- `successful_shutdown_release_clears_all_tracked_input`

### 6.5 Existing behavior to preserve

Keep all existing worker, HTTP, screenshot, framebuffer, reconnect, authentication, stall, native adapter, input, WebSocket, and R13 tests green.

## 7. Framebuffer performance review

Preserve the current entity semantics:

- byte-identical current full-frame replacements keep revision and timestamp;
- byte-identical dirty updates with unchanged availability keep revision and timestamp;
- changed pixels or availability transitions advance the revision;
- stale and incomplete frames remain fail-closed;
- R13's conditional screenshot `304` assertion remains unchanged.

During implementation:

- document the maximum comparison/copy size for the configured framebuffer bound;
- measure representative full-frame and dirty-update costs locally or with a small opt-in benchmark if practical;
- inspect lock hold time and allocation behavior;
- do not add hashes as correctness authorities unless collision handling preserves exact byte equality;
- do not optimize by weakening revision or ETag semantics;
- if no material regression is demonstrated, record the review and leave the correct implementation unchanged.

This performance review is required, but a framebuffer rewrite is not.

## 8. Documentation and historical evidence correction

The implementation must update the historical record accurately.

Required changes:

- add an audit note to `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md` explaining that the later review found unresolved process-level, queue-accounting, input-release, and test-evidence gaps;
- do not retroactively mark unsupported historical tasks complete;
- update `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md` so it no longer claims final completion or fully coherent queue-depth accounting;
- link both historical files to this final hardening spec and TODO;
- use this new TODO as the authoritative completion checklist;
- record starting SHA, implementation SHA, final documentation/evidence SHA, CI run, Release Gates run, and R13 job;
- require the final repository-tip SHA, including evidence updates, to pass all required workflows.

## 9. Validation requirements

Run the full CI-equivalent local checks before pushing whenever the development environment provides the required toolchain:

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

Where Docker/VNC resources are available, run:

```bash
tests/desktop/run.sh
bash tests/native/run.sh
bash tests/worker-e2e/run.sh
bash tests/worker-text-clipboard-e2e/run.sh
bash tests/http-e2e/run.sh
bash tests/compose/run.sh
bash tests/integration/run.sh
```

If a local tool or service is unavailable, document the exact skipped command and require exact-SHA CI to cover it. Do not describe unavailable local validation as passed.

After pushing, the same exact final repository-tip SHA must pass:

- CI:
  - repository quality gates;
  - secured Debian desktop/native job;
  - WorkerHandle input E2E;
  - text/clipboard E2E;
  - authenticated HTTP E2E;
  - controller/Compose/persistence smoke;
  - R13 Compose integration and E2E validation;
- Release Gates:
  - static and supply-chain policy;
  - full-history Gitleaks;
  - ShellCheck and actionlint;
  - BuildKit and Compose validation;
  - cargo-deny/advisory/license/source policy;
  - ASan, TSan, and Miri;
  - Trivy, SBOM, and exact VEX enforcement.

Do not use an older code SHA plus an unvalidated evidence commit as final completion evidence.

## 10. Do-not-accept list

Do not accept any implementation that:

- leaves `event_bridge.join()` unbounded after worker timeout;
- merely reorders error propagation while leaving a blocking bridge thread alive;
- detaches the bridge silently without a stop request and observable timeout;
- increases queue capacity as a race fix;
- resets queue depth to zero manually at shutdown without making envelope ownership correct;
- uses `store(0)` to hide accounting bugs;
- leaves raw queue-depth `fetch_add`/`fetch_sub` operations scattered across send/receive/drain paths;
- sends an uncounted envelope through a path that unconditionally decrements depth;
- retries queue insertion until space appears;
- executes an ordinary command after shutdown begins;
- ignores worker, bridge, startup, or input-release failure without a payload-free diagnostic;
- clears failed input releases silently;
- uses sleep-only race tests;
- tests only helpers when the production integration path is the real risk;
- weakens R13 conditional screenshot assertions;
- changes framebuffer ETags on byte-identical frames to avoid performance work;
- logs commands, typed text, clipboard content, key values, coordinates, bearer tokens, VNC passwords, framebuffer bytes, or screenshots;
- adds `continue-on-error`, broad secret ignores, broad vulnerability ignores, or scanner suppression;
- force-pushes `master`;
- claims completion before the final repository-tip SHA passes CI and Release Gates.

## 11. Completion criteria

This final hardening pass is complete only when all of the following are true:

- a stuck worker cannot cause an unbounded event-bridge join or unbounded process shutdown;
- the event bridge can be stopped independently of worker event-sender destruction;
- worker and bridge shutdown timeouts are real, bounded, observable errors;
- queue depth is ownership-based and converges to zero for every send, failure, receive, drain, compatibility shutdown, receiver-drop, and shutdown-race path;
- the startup compatibility nudge cannot underflow queue depth;
- startup cleanup returns meaningful join/panic outcomes;
- failed final input releases are reported and never silently forgotten;
- required tests exercise complete worker/process paths and assert diagnostics;
- existing HTTP, VNC, framebuffer, WebSocket, input, screenshot, reconnect, and R13 behavior remains green;
- framebuffer duplicate suppression semantics remain correct and its performance cost is reviewed;
- historical TODO/evidence claims are corrected;
- local validation is run or exact limitations are documented;
- CI passes on the exact final repository-tip SHA;
- Release Gates pass on the same exact final repository-tip SHA;
- the companion final-hardening TODO contains completed checkmarks, exact SHAs, run IDs, and evidence.