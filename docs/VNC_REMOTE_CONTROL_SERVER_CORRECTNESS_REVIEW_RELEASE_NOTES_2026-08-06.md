# VNC Remote Control Server Correctness Review Release Notes

Date: 2026-08-06

This correctness pass repairs worker recovery, state-transition observability, native pixel negotiation, timeout contracts, sanitizer coverage, metric naming, secret lifecycle, privacy proofs, and race-test causality without changing the public control API.

## Behavior changes

- A confirmed stall before the first complete framebuffer now invalidates session state and schedules reconnect without entering `Degraded`, setting fatal exit, or terminating the worker. Previously connected stalls retain `Connected -> Degraded -> reconnect` semantics.
- Illegal state transitions emit a payload-free `worker_illegal_state_transition` diagnostic and do not mutate health. Final `Stopped` transition failure is explicit rather than discarded.
- LibVNCClient now negotiates a 32-bit little-endian true-colour `[R,G,B,X]` layout; canonical storage remains `[R,G,B,255]`. Native and authenticated HTTP E2E tests verify red and blue at canonical and decoded-PNG layers.
- `VRC_STARTUP_TIMEOUT_MS` now bounds the complete startup operation, including timeout cleanup, rather than allowing a second full cleanup window.
- New `VRC_SHUTDOWN_TIMEOUT_MS` defaults to 5000 ms and supplies one total worker-plus-event-bridge process-cleanup budget. Values below the derived 500 ms floor are rejected.
- `vrc_worker_command_queue_depth` was replaced without alias by `vrc_worker_command_submissions_in_flight`; the implementation and permit-acquisition point are unchanged.

## Safety and evidence changes

- Release Gates execute `controller-api --lib` and `remote-desktop-core --lib` under ThreadSanitizer. Miri remains accurately scoped to `remote-desktop-core`; LibVNCClient is not rebuilt with sanitizers.
- Project-owned VNC password buffers are zeroized before release. The callback allocation owned and freed by LibVNCClient remains an explicit third-party residual.
- Privacy tests parse structured JSON logs on real input-release, text/clipboard, native-password, and bearer-token paths.
- Negative worker tests use causal loop progress and positive controls instead of sleep as proof.
- A committed 1920×1080 counting-allocator utility records framebuffer allocation and timing evidence. No framebuffer optimization was mixed into this pass.

## Deferred follow-ups

- direct event-bridge wake-up instead of bounded polling;
- migration of API bearer-token storage to the shared zeroizing secret type;
- framebuffer optimization only under a separate measured performance specification;
- a compatibility alias only if an external metric consumer is identified.
