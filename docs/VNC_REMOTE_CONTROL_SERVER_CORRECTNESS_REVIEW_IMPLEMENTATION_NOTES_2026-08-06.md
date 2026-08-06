# VNC Remote Control Server Correctness Review Implementation Notes

Date: 2026-08-06

Status: implementation and evidence complete; exact final-tip workflow results are recorded externally because a commit cannot embed its own future SHA or run IDs.

Implementation candidate source tree before this anchor: `1081f645b57a1a4b460e1560f5454b2467399c8d`.

Implemented surfaces currently under permanent validation:

- pre-`Connected` confirmed-stall recovery without widening the state graph;
- connected-stall recovery no longer self-deadlocks by retaining the snapshot mutex guard while recursively entering `transition()`;
- non-mutating, observable illegal transition failures and explicit final `Stopped` handling;
- explicit LibVNCClient 32-bit `[R,G,B,X]` negotiation;
- canonical RGBA and decoded-PNG red/blue E2E channel assertions;
- `controller-api --lib` ThreadSanitizer coverage with the Miri boundary recorded;
- `command_submissions_in_flight` metric semantics and Prometheus HELP/TYPE records;
- one total process-shutdown budget and one total startup budget;
- zero-budget nonblocking exit observation before deliberate detach;
- project-owned Rust and C VNC-password scrubbing, with the LibVNCClient-owned callback copy retained as an explicit residual;
- structured path-specific privacy tests for input release, command payloads, bearer logging, and VNC-password failure propagation;
- a deterministic regression proving submissions in flight may exceed channel capacity and converge to zero;
- deterministic replacements for the known sleep-only negative proofs;
- a committed ignored 1920×1080 framebuffer allocation/timing measurement utility and reproducibility contract.

Baseline runtime evidence is recorded in:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_BASELINE_EVIDENCE_2026-08-06.md`.

The connected-stall deadlock repair was reproduced by the existing end-to-end reconnect regression: before the repair, the worker held the snapshot mutex in the stall-state `match` and blocked indefinitely when `transition()` attempted to acquire the same mutex; after copying the state before entering the match, the exact regression completed and observed reconnect plus framebuffer revision advancement.

No TODO checkbox or completion claim should be inferred from this implementation note. Exact-SHA CI, Release Gates, R13, measurement output, operator/security documentation, and the final authoritative TODO evidence remain required.
