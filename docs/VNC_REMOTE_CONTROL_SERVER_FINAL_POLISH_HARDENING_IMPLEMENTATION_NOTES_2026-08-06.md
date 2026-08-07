# VNC Remote Control Server Final Polish Hardening Implementation Notes

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_SPEC_2026-08-06.md`

TODO: `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_TODO_2026-08-06.md`

Original reviewed baseline SHA: `a541db25624cb9ddf23664606ed89c0522cc75a2`

Final-polish starting SHA: `56df8ee6de95765e9fe92eb2647dda76bf93fc84`

Validated implementation SHA before final completion documentation: `f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55`

## Summary

This final-polish pass closed three low-severity review edges without reopening the completed post-hardening cleanup loop or changing the project architecture. The implementation makes generated HTTP request IDs fail closed on exhaustion, wakes established WebSocket clients promptly when EventHub sequence allocation becomes terminal, and explicitly chooses the safer source-contract strategy for native scrub regression protection.

No CI, Release Gate, sanitizer, secret-scan, dependency-policy, Docker/Compose, Trivy, SBOM, or VEX gate was weakened.

## P0 — Baseline and scope

The historical baseline recorded in the spec was `a541db25624cb9ddf23664606ed89c0522cc75a2`. Before implementation began, `master` had advanced only through the final-polish planning documents, so the actual starting SHA was `56df8ee6de95765e9fe92eb2647dda76bf93fc84`.

The implementation diff from that starting SHA was limited to the request-ID boundary and tests, EventHub and its test, native source-contract tests, README/WebSocket documentation, and documentation contract assertions. No workflow or release-policy file changed.

## P1 — Request ID sequence exhaustion

Generated request IDs previously used unchecked `AtomicU64::fetch_add`, which could theoretically wrap after sequence exhaustion.

The final-polish implementation now:

- uses checked atomic sequence advancement;
- maintains a terminal request-ID exhaustion state;
- never wraps, silently saturates, or reuses a generated normal sequence value;
- reserves `request-id-exhausted` as a non-normal sentinel and rejects that value as a caller-supplied normal request ID;
- checks terminal exhaustion in the outer `assign_request_id` middleware before access logging, authentication, or normal handler execution;
- prevents a caller-provided `X-Request-ID` from bypassing terminal exhaustion;
- returns HTTP `503` with error code `request_id_exhausted`, message `request identifier sequence is exhausted`, and `X-Request-ID: request-id-exhausted`;
- emits `request_id_sequence_exhausted` at most once when the terminal state is first observed;
- does not include request bodies, command payloads, typed text, clipboard text, credentials, framebuffer/screenshot bytes, or query values in that diagnostic.

Tests prove normal generated IDs retain the accepted `process-instance-sequence` format, forced `u64::MAX` exhaustion is terminal and payload-free, the diagnostic appears once, the sentinel cannot be a normal caller ID, and a keyboard-text request cannot reach the backend command queue after exhaustion.

The terminal response is documented as a global routed-request failure boundary in `README.md`. It occurs before normal route operation dispatch rather than being a route-specific handler failure.

## P2 — Prompt EventHub exhaustion wake-up

The accepted pre-upgrade behavior is unchanged: if an initial WebSocket snapshot cannot allocate a unique sequence, the upgrade fails with HTTP `503 event_sequence_exhausted`.

For already-established clients, EventHub now owns an internal `tokio::sync::Notify`. When event sequence allocation first becomes terminal, EventHub:

1. flips the terminal exhaustion flag;
2. emits the existing payload-free `event_hub_sequence_exhausted` diagnostic once;
3. calls `notify_waiters()` so established service loops wake promptly.

Each established loop still closes with WebSocket code `1011` and exact reason `event sequence exhausted`. The notification is internal; it does not introduce a public event type or payload.

The established-client regression test deliberately uses a 30-second heartbeat while requiring the exhaustion close within 200 ms. Therefore an implementation that only wakes on heartbeat cannot pass the test. The test still requires the initial snapshot before forcing exhaustion and rejects sensitive terminology in the close reason.

`docs/WEBSOCKET_EVENTS.md` now records that terminal exhaustion wakes established clients without waiting for the next heartbeat. `tests/test_documentation_contract.py` protects that statement and the internal notification mechanism.

## P3 — Native scrub semantic-test decision

**Decision: Option B — retain and tighten the source-contract strategy.**

A new C observer/test hook was not added. A hook would increase native build/API complexity and create another sensitive-buffer observation mechanism solely to observe memory between scrub and free. The existing strategy is safer: one centralized `vrc_scrub_and_free` primitive defines the ordering, source contracts prove sensitive call sites route through it, and native/E2E/sanitizer execution verifies the surrounding real behavior.

`tests/test_native_contract.py` was tightened to require:

- `vrc_secure_scrub` is called only by the central scrub/free primitive outside its own definition;
- project-owned stored clipboard cleanup does not directly call `free(client->clipboard)`;
- shim-owned persistent password cleanup does not directly call `free(client->password)`;
- outbound clipboard copies do not use direct `free(copy)`;
- the expected sensitive cleanup call sites continue to use `vrc_scrub_and_free`;
- clipboard revision overflow remains checked before replacement allocation.

No test reads freed memory, depends on allocator reuse, or logs clipboard/password contents. The guarantee remains limited to project-owned buffers; no guarantee is claimed for LibVNCClient-, VNC-server-, toolkit-, OS-, allocator-, swap-, reverse-proxy-, or crash-dump-owned copies.

## P4 — Documentation

The pass updates only behavior that changed:

- `README.md` documents terminal request-ID exhaustion and the reserved response sentinel;
- `docs/WEBSOCKET_EVENTS.md` replaces the old heartbeat-bound exhaustion wording with prompt internal wake-up behavior;
- `tests/test_documentation_contract.py` guards both final-polish documentation statements;
- this file records the P1-P3 design and validation evidence.

Historical cleanup and hardening evidence was not rewritten.

## P5 — Local execution disposition

A normal local repository checkout/execution surface was not available in the ChatGPT environment because direct outbound GitHub DNS/network access was unavailable. Therefore no Rust, Python, shell, Docker, VNC, or Compose command is represented as locally passed.

The corresponding permanent exact-SHA workflow stages are the authoritative execution evidence.

## Intermediate validation failure

Candidate `d2f4b38d9d1c76af14500538b0e2fe69c5027c49` failed `cargo fmt --all --check`. Clippy and tests did not run on that red candidate. The exact rustfmt changes were applied; no behavior, assertion, or gate was weakened. This superseded SHA is not completion evidence.

## P6 — Exact-SHA permanent validation

Validated implementation SHA:

`f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55`

CI run `31156125021`: `success`

- formatting: success;
- Clippy with warnings denied: success;
- full Rust workspace tests: success;
- rustdoc with warnings denied: success;
- Python compile and unittest/workflow/native/documentation contracts: success;
- shell syntax: success;
- desktop smoke: success;
- native adapter smoke: success;
- WorkerHandle input E2E: success;
- WorkerHandle text/clipboard E2E: success;
- authenticated HTTP E2E: success;
- controller image/Compose/persistence: success;
- R13 Compose integration/E2E: success.

Release Gates run `31156124982`: `success`

- static and supply-chain policy: success;
- full-history Gitleaks: success;
- ShellCheck/actionlint: success;
- Dockerfile/Compose validation: success;
- advisory/license/source/duplicate policy: success;
- auditable binary metadata verification: success;
- AddressSanitizer: success;
- controller-api ThreadSanitizer: success;
- remote-desktop-core ThreadSanitizer: success;
- Miri: success;
- Trivy/CycloneDX SBOM/VEX: success.

## Deferred boundaries

No P1-P4 requirement is deferred.

Third-party/OS/toolkit/allocator/LibVNCClient/server/reverse-proxy/swap/crash-dump residual-memory boundaries remain explicit non-guarantees, not unfinished implementation work.
