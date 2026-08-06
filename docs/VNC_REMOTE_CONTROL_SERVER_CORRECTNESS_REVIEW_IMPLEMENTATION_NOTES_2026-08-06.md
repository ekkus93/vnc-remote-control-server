# VNC Remote Control Server Correctness Review Implementation Notes

Date: 2026-08-06

Status: implementation in progress; this is not completion evidence.

Implemented surfaces currently under permanent validation:

- pre-`Connected` confirmed-stall recovery without widening the state graph;
- non-mutating, observable illegal transition failures and explicit final `Stopped` handling;
- explicit LibVNCClient 32-bit `[R,G,B,X]` negotiation;
- canonical RGBA and decoded-PNG red/blue E2E channel assertions;
- `controller-api --lib` ThreadSanitizer coverage with the Miri boundary recorded;
- `command_submissions_in_flight` metric semantics and Prometheus HELP/TYPE records;
- one total process-shutdown budget and one total startup budget;
- zero-budget nonblocking exit observation before deliberate detach;
- project-owned Rust and C VNC-password scrubbing, with the LibVNCClient-owned callback copy retained as an explicit residual;
- structured path-specific privacy tests for input release, command payloads, and bearer logging;
- deterministic replacements for the two known sleep-only negative proofs;
- a committed ignored 1920×1080 framebuffer allocation/timing measurement utility.

Baseline runtime evidence is recorded in:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_BASELINE_EVIDENCE_2026-08-06.md`.

No TODO checkbox or completion claim should be inferred from this implementation note. Exact-SHA CI, Release Gates, R13, measurement output, operator/security documentation, and the final authoritative TODO evidence remain required.
