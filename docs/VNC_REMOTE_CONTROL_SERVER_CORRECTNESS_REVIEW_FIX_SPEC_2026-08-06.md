# VNC Remote Control Server Correctness Review Fix Spec

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Baseline reviewed for this specification: `e9be696783e7fdfb90389cd02890d48c3e9bbd2d`

Companion TODO:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_TODO_2026-08-06.md`

Related documents:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`
- `docs/LIBVNCCLIENT_BINDING_DECISION.md`

## 1. Purpose

A full static code review of the repository tip found that the completed shutdown work is correct and should not be revisited. The out-of-band shutdown flag, the ownership-based queue-depth permit, the independently stoppable event bridge, the bounded process cleanup coordinator, and the state-aware input-release reporting all hold up under line-by-line reading.

The review did find defects outside the shutdown scope, and two places where the final hardening pass recorded a checkbox that its implementation does not substantively cover. This specification defines the corrective pass.

This pass must not weaken any existing gate, relax any assertion, revert any shutdown behavior, or change the framebuffer duplicate-detection semantics that protect screenshot ETag stability and the R13 conditional `304` contract.

Scope note: the reviewing environment had no Rust toolchain and no Docker runtime. All findings below are derived from static reading and must be confirmed by a failing test before the corresponding fix is written.

## 2. Review findings that define this scope

### 2.1 High severity: a confirmed stall before `Connected` terminates the worker permanently

`LoopState::poll()` handles a confirmed transport stall by transitioning to `ConnectionState::Degraded` and propagating any transition failure:

```rust
self.transition(ConnectionState::Degraded)?;
self.invalidate();
self.schedule_reconnect();
```

`ConnectionState::can_transition_to` permits `Connected -> Degraded`, but not `Connecting -> Degraded` and not `Reconnecting -> Degraded`.

`run_worker` assigns `state.session = Some(session)` as soon as the session factory returns and the initial full refresh succeeds. The snapshot state remains `Connecting` or `Reconnecting` until `connected_message()` observes a complete framebuffer update at a stable native revision. `LoopState::poll()` therefore runs while the worker is still pre-`Connected`.

For a peer that completes RFB initialization and then delivers no framebuffer update — a hung X server, a blanked or locked display, or a server deferring updates — the sequence is:

1. `poll()` returns `PollOutcome::TimedOut` repeatedly, so `last_message` is never refreshed.
2. `stall_probe_after` elapses, a probe refresh is sent, and `probe_sent` is recorded.
3. `stall_confirm_after` elapses.
4. `transition(ConnectionState::Degraded)` is rejected by the state machine, sets `fatal_exit = true` as a side effect, and returns `Err(DesktopError::Protocol)`.
5. `?` propagates the error out of `poll()`.
6. `run_worker` executes `if state.poll().is_err() { break; }` with `orderly_shutdown == false`.
7. The loop exits, `fatal_exit` is set again, and the worker terminates without attempting reconnection.

The stall detector exists specifically to recover half-open connections. In the pre-`Connected` window it produces the opposite outcome: permanent fatal termination with no reconnect.

Existing tests do not cover this. `confirmed_stall_invalidates_reconnects_and_advances_revision` reaches `Connected` before stalling, so it exercises the legal `Connected -> Degraded` edge. `mismatched_native_frame_never_reaches_connected` returns `PollOutcome::MessageProcessed` on every poll, which refreshes `last_message` and prevents the stall path from firing, and it does not assert `fatal_exit`.

The fix must make a pre-`Connected` confirmed stall recover through invalidation and reconnect scheduling, with `fatal_exit == false`.

### 2.2 Medium severity: `transition()` sets `fatal_exit` as a side effect, and its result is discarded

`LoopState::transition()` sets `fatal_exit = true` before returning `Err(DesktopError::Protocol)` on an illegal transition. It is invoked as `let _ = self.transition(..)` twice in `schedule_reconnect()` and three times in `run_worker`.

Any unexpected state sequence therefore poisons `fatal_exit` permanently and silently. `fatal_exit` is published on `/v1/status`, included in the WebSocket snapshot event, and consumed by readiness. A discarded result must not be able to change externally visible health.

The fix must make illegal transitions observable and must stop discarding a result that carries a side effect.

### 2.3 Medium severity: the native pixel format is assumed rather than negotiated or verified

`FramebufferStore::replace_native_rgbx` interprets each native pixel as red, green, blue, padding:

```rust
rgba.extend_from_slice(&[pixel[0], pixel[1], pixel[2], u8::MAX]);
```

`crates/libvnc-adapter/native/vnc_shim.c` never assigns `client->format.redShift`, `greenShift`, `blueShift`, `redMax`, `greenMax`, `blueMax`, or `bigEndian`. It calls `rfbGetClient(8, 3, 4)` and then `SetFormatAndEncodings(client->native)`, so the on-wire byte order is whatever the LibVNCClient default produces for the build host.

No test in the repository asserts a pixel value against a known source color. The unit tests use synthetic byte vectors that are equally consistent with any channel order, and neither E2E binary inspects pixels. A channel swap, or an off-by-one that reads the padding byte as red, would pass every current gate including R13.

The fix must remove the assumption. The shim must set the pixel format explicitly so the byte layout is defined and host-endianness-independent, and an end-to-end test must assert a known color.

### 2.4 Medium severity: the ThreadSanitizer and Miri gates do not cover the concurrent code

`.github/workflows/release-gates.yml` runs ThreadSanitizer and Miri against `--package remote-desktop-core --lib`, and AddressSanitizer against `--package libvnc-adapter --lib`.

`remote-desktop-core` contains no threads. Every atomic, bounded channel, queue-depth permit, exit signal, join path, and cross-thread handoff introduced or modified by the shutdown refactor and both hardening passes lives in `controller-api`, which no sanitizer job builds.

The final hardening TODO's `TSan` and `Miri` acceptance boxes are literally accurate about the gate existing and substantively empty about the code the pass changed.

The fix must extend ThreadSanitizer coverage to the `controller-api` worker and shutdown tests, or record an explicit, evidenced justification for why that is not achievable together with whatever narrower coverage is achievable.

### 2.5 Low/medium severity: `command_queue_depth` reports in-flight submissions, not queue occupancy

`CommandEnvelope::new()` acquires the queue-depth permit before `WorkerClient::submit_inner` calls `try_send`. This ordering is deliberate and is what makes the final-drain race safe; it must be preserved.

The consequence is that the counter is not queue occupancy. It can exceed `command_queue_capacity`, and it can be nonzero while the channel is empty whenever a submitter is between envelope construction and `try_send`. That state is exactly what `submit_racing_final_shutdown_drain_converges_depth_to_zero` constructs on purpose.

`vrc_worker_command_queue_depth` is rendered next to `vrc_worker_command_queue_capacity` in the Prometheus output and appears in the HTTP status surface. As an operator signal backing alert thresholds, the current name asserts something the value does not mean.

The fix must correct the reported semantics without changing the accounting.

### 2.6 Low/medium severity: process cleanup reuses an unrelated HTTP timeout

`main.rs` passes `config.command_ack_timeout` to `finalize_runtime`, which applies it twice in sequence:

```rust
let worker_result = worker.shutdown(timeout);
let bridge_result = event_bridge.shutdown(timeout);
```

Three problems follow. The complete cleanup bound is `2 x VRC_COMMAND_ACK_TIMEOUT_MS` rather than a single declared deadline. The bound is controlled by a knob whose documented purpose is the per-command HTTP acknowledgement wait. And `EVENT_BRIDGE_POLL_INTERVAL` is a fixed 50 ms, so any `command_ack_timeout` below roughly 50 ms guarantees a spurious `event_bridge_shutdown_timeout` and a nonzero process exit on an otherwise clean shutdown. Configuration currently rejects only a zero value.

The fix must give process shutdown its own configured deadline with a floor that cannot be set below the bridge poll interval.

### 2.7 Low severity: startup timeout is silently doubled

`spawn_with_factory_and_startup_hook` waits `startup_timeout` for the startup acknowledgement, then passes `startup_timeout` again to `cleanup_startup_worker_after_timeout`. The path is bounded and safe, but the effective worst case is twice the configured value and nothing says so.

The fix is documentation, or an explicitly derived cleanup deadline.

### 2.8 Low severity: unreachable error arms

`EventBridge::shutdown` and `DesktopWorker::shutdown` both end with an `Err(error) => Err(error)` arm. `wait_for_exit` in each type can return only `Ok(())` or the timeout variant, so neither arm is reachable.

These are harmless today and become misleading if either wait path later grows a third outcome that the caller silently forwards without diagnostics.

### 2.9 Low severity: secret material is not scrubbed before release

`vrc_client_destroy` releases the duplicated VNC password with a plain `free`. On the Rust side, `NativeClientConfig.password` is a `String` that is cloned into `WorkerSettings` and moved into the worker thread closure, leaving copies resident for the process lifetime.

Every other secret-handling decision in the repository is deliberate: no `Debug` on password-bearing types, redacted `Authorization` in the access log, bounded secret-file size, payload-free events. Scrubbing closes the remaining gap.

### 2.10 Low severity: privacy assertions match generic nouns

`shutdown_logs_incomplete_input_release_without_payloads` asserts the absence of substrings including `"clipboard"`, `"framebuffer"`, and `"typed_text"`.

`"CtrlLeft"` is a correct assertion, because it is the actual value under test. The generic nouns are not. They will fail spuriously the first time any structured field is named `framebuffer_revision` or `clipboard_revision`, and they would not catch a real leak that renders a value without the matching noun nearby.

The fix must assert against injected sentinel values rather than category words.

### 2.11 Documentation defect: the framebuffer performance review is incomplete

The final hardening TODO records the framebuffer performance disposition as the 64 MiB worst-case comparison under the write lock plus the dirty-commit clone. That accounting omits the dominant per-frame costs.

Each complete frame currently performs, in order: a full-size `Vec` allocation and `memcpy` in `NativeClient::framebuffer`; a second full-size `Vec` allocation filled by a per-pixel `extend_from_slice` loop in `replace_native_rgbx`; a full-frame equality comparison under the store write lock; and a `Vec<u8> -> Arc<[u8]>` conversion that allocates and copies a third time.

That is approximately four full-frame passes and three full-frame allocations per delivered frame. The per-pixel conversion loop is the cheapest to remove and is not mentioned in the recorded review.

### 2.12 Low severity: one pre-existing sleep-only test

`mismatched_native_frame_never_reaches_connected` sleeps 30 ms and then asserts. The final hardening TODO's do-not-accept list prohibits sleep-only race evidence. This test predates that pass, but it is the same failure mode and should be converted to a bounded barrier.

## 3. Required outcomes

1. A confirmed stall in any pre-`Connected` state recovers through invalidation and reconnect scheduling, and never sets `fatal_exit`.
2. No illegal state transition can change externally visible health without an emitted diagnostic, and no `transition()` result carrying a side effect is discarded.
3. The native pixel format is explicitly negotiated in the shim, and an end-to-end test asserts a known source color through the canonical framebuffer.
4. ThreadSanitizer covers the `controller-api` worker and shutdown tests, or the impossibility is documented with evidence and the achievable subset is added.
5. The queue-depth metric name and help text state what the counter measures.
6. Process shutdown has its own configured deadline with a floor above `EVENT_BRIDGE_POLL_INTERVAL`, and the total cleanup bound is stated.
7. Startup cleanup's effective bound is documented or explicitly derived.
8. Unreachable error arms are removed or made reachable-and-diagnosed.
9. The VNC password is zeroized on both sides of the FFI boundary before release.
10. Log-privacy assertions test injected sentinel values.
11. The framebuffer performance record accounts for per-frame allocation and conversion cost, and the per-pixel conversion loop is removed if a benchmark justifies it.
12. The remaining sleep-only test uses a bounded barrier.

## 4. Non-goals and preservation requirements

This pass must not:

- change the out-of-band `Arc<AtomicBool>` shutdown authority;
- change the queue-depth permit ownership model or the point at which the permit is acquired;
- change `EventBridge` stop, exit-signal, join, or detach semantics;
- change the `finalize_runtime` error precedence of server, then worker, then bridge;
- change framebuffer byte-equality semantics, ETag stability, or the R13 conditional `304` contract;
- weaken any R13 assertion;
- add `continue-on-error`, a broad `.gitleaksignore` entry, or a broad Trivy or VEX ignore;
- disable or downgrade any CI or Release Gates job;
- introduce a new public HTTP shutdown error;
- log any command payload, typed text, clipboard value, key value, coordinate, bearer token, VNC password, framebuffer byte, or screenshot.

## 5. Verification standard

Every behavioral fix in sections 2.1 through 2.10 requires a test that fails on the baseline `e9be696783e7fdfb90389cd02890d48c3e9bbd2d` and passes after the change. Reproduction precedes repair. A fix without a demonstrated failing baseline test is not accepted.

Deterministic tests use bounded channels, barriers, and deadlines. Sleep-only proofs are not accepted. Every potentially blocked test thread has a bounded release path so a regression fails quickly instead of hanging CI.

Both CI and Release Gates must succeed on the exact final repository-tip SHA. Where a commit cannot record its own hash, the TODO records the implementation SHA plus the external run identifier that validated the tip, and does not claim self-referential proof.
