# VNC Remote Control Server Correctness Review Baseline Evidence

Date: 2026-08-06

Defect baseline: `e9be696783e7fdfb90389cd02890d48c3e9bbd2d`

Reproduction-test commit: `f478c50fc783aa4b14fd9c6caca1d8f7a825fb9c`

CI reproduction run: `31089961908`

Repository-quality job: `92578370228`

## Runtime reproductions

The baseline reproduction commit added the permanent production-path regressions before changing the implementation. Formatting and strict Clippy passed. The Rust suite then reported 112 passing tests and exactly two expected failures:

1. `worker::tests::reconnect::pre_connected_confirmed_stall_reconnects_without_fatal_exit`
   - observed failure: the session factory was not invoked a second time;
   - the worker reached the fatal pre-`Connected` transition path instead of scheduling reconnection.
2. `worker::tests::reconnect::illegal_transition_is_logged_and_does_not_silently_poison_health`
   - observed failure: `LoopState::transition()` changed `fatal_exit` while returning `DesktopError::Protocol`;
   - the required `worker_illegal_state_transition` diagnostic was absent.

The tests remained in the suite and are not weakened or deleted by the repairs.

## Static, workflow, and contract evidence

- **CR3 pixel format:** the baseline shim did not assign RGB shifts, maxima, true-colour depth, or endianness before `SetFormatAndEncodings`; the Rust store nevertheless interpreted native bytes as `[R,G,B,X]`.
- **CR4 sanitizer coverage:** Release Gates ran ThreadSanitizer and Miri only against `remote-desktop-core --lib`; the concurrent `controller-api` worker, event bridge, framebuffer, and shutdown code was outside the TSan target.
- **CR5 metric semantics:** `CommandEnvelope::new()` acquired its ownership permit before `try_send`, so the exported value represented command submissions in flight rather than bounded-channel occupancy.
- **CR6 process timeout:** `main.rs` passed `command_ack_timeout` into `finalize_runtime`, which applied the same duration sequentially to worker and bridge cleanup.
- **CR7 startup timeout:** the acknowledgement wait and startup cleanup each received the full configured `startup_timeout`, allowing an approximately doubled bound.
- **CR8 unreachable arms:** both shutdown owners forwarded an impossible third wait error after helpers that could produce only exit or timeout.
- **CR9 secret lifecycle:** project-owned Rust and C password copies used ordinary destruction/free without explicit scrubbing; the password returned by the LibVNCClient callback was library-owned after return.
- **CR10 privacy tests:** the baseline shutdown privacy assertion rejected generic category nouns rather than exact values carried through the tested path.
- **CR11 performance record:** the historical record did not measure the native copy, RGBX conversion allocation, equality comparison, or `Vec` to `Arc` conversion as one reproducible pipeline.
- **CR12 deterministic tests:** `mismatched_native_frame_never_reaches_connected` and `authentication_failure_waits_for_manual_reconnect` used elapsed sleeps as their primary negative proof.

This document records pre-repair evidence only. It does not claim implementation or validation completion.
