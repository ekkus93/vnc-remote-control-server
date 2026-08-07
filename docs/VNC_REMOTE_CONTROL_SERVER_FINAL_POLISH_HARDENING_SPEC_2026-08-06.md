# VNC Remote Control Server Final Polish Hardening Spec

Date: 2026-08-06

Baseline branch: `master`

Baseline SHA: `a541db25624cb9ddf23664606ed89c0522cc75a2`

Status: proposed; not implemented.

Related completed work:

- `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_TODO_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_IMPLEMENTATION_NOTES_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_FINAL_EVIDENCE_2026-08-06.md`

## 1. Purpose

The post-hardening cleanup loop is complete and should not be reopened unless source evidence proves a regression. This specification defines a separate, narrow final-polish hardening pass for the remaining low-severity review findings on the current green repository tip.

The goal is to remove a few theoretical or evidence-quality edges before treating the project as a stable hardened baseline:

1. make HTTP request ID sequence exhaustion fail closed instead of theoretically wrapping;
2. make EventHub established-client sequence exhaustion wake established clients immediately rather than waiting for heartbeat;
3. decide whether a safe pre-free native scrub semantic test hook is practical, while preserving the no-freed-memory-testing rule;
4. document the final polish behavior and exact validation evidence without weakening any existing gate.

## 2. Non-goals

This pass must not become another broad correctness rewrite. It must not rework the architecture, change public API behavior except where explicitly specified, replace the native adapter, alter authentication policy, change deployment topology, or relax release policy.

Specifically, do not:

- reopen completed C1-C5 cleanup requirements;
- remove historical evidence files merely because they describe older recovery work;
- weaken CI, Release Gates, sanitizer gates, Gitleaks, actionlint, ShellCheck, cargo policy, Trivy, SBOM, VEX, Dockerfile checks, or Compose checks;
- introduce `continue-on-error`, broad ignore rules, suppressed exit codes, forced success, or force pushes;
- log command payloads, typed text, clipboard text, key names, coordinates, bearer tokens, VNC passwords, framebuffer bytes, screenshot bytes, query secrets, or raw secret-file contents;
- claim third-party, OS, allocator, toolkit, LibVNCClient, VNC-server, reverse-proxy, swap, or crash-dump copies are scrubbed unless the code actually proves that specific ownership boundary.

## 3. Existing accepted baseline

The starting SHA is the cleanup-completion repository tip:

`a541db25624cb9ddf23664606ed89c0522cc75a2`

That exact SHA passed:

- CI run `31148491095`: success;
- Release Gates run `31148491122`: success.

The completed cleanup loop already established the following accepted state:

- EventHub sequence exhaustion does not wrap, reuse, silently saturate, or panic.
- Pre-upgrade WebSocket EventHub exhaustion returns bounded `503 event_sequence_exhausted`.
- Established WebSocket clients close with `1011` and reason `event sequence exhausted` after sequence exhaustion.
- `SecretString`, `NativeClientConfig`, `WorkerSettings`, and `ControllerConfig` are not generally cloneable.
- `ApiToken` remains cloneable only as `Arc<SecretString>` shared ownership, not token-byte duplication.
- `WorkerSettings` moves into the worker; HTTP state receives only HTTP-specific settings.
- The reconnect-factory VNC credential duplication is explicit and named.
- Native project-owned clipboard/password cleanup is centralized through `vrc_scrub_and_free`.
- Native scrub guarantees remain limited to project-owned buffers.
- Active `.github` workflows are permanent workflows only, and policy pins remain fail closed.

## 4. Requirement P1 — HTTP request ID sequence exhaustion must fail closed

### 4.1 Problem

`HttpState::next_request_id()` currently allocates request IDs with an atomic increment. At ordinary lifetimes this is practically safe, but at the type level it can theoretically wrap. That is inconsistent with the stricter fail-closed posture now used for EventHub sequence IDs.

### 4.2 Required behavior

Request ID allocation must not wrap, reuse a normal sequence value, silently saturate, or panic.

When the request ID sequence reaches exhaustion:

- normal request handling must fail closed before handler execution;
- the process must not issue another normal request ID after exhaustion;
- the response must be bounded, deterministic, and redaction safe;
- diagnostics must not contain any request body, command payload, typed text, clipboard text, bearer token, VNC password, framebuffer bytes, screenshot bytes, or query secret;
- an exhaustion diagnostic should be emitted at most once per process lifetime, unless there is an explicit metric/counter intended to count repeated rejected requests.

If the existing error model requires a request-id-shaped value in the response, a clearly reserved sentinel may be used, but it must not be confused with a normal sequence allocation. The sentinel must not include any user-controlled value.

### 4.3 Implementation constraints

The preferred implementation is an EventHub-style checked atomic update plus a terminal `request_id_exhausted` flag. Equivalent implementations are acceptable only if they prove the same properties.

Recommended shape:

- add an exhaustion flag to `HttpState` or a small request ID allocator type;
- change request ID allocation to return a `Result<RequestId, RequestIdSequenceError>` or equivalent;
- update the request ID middleware/boundary so allocation failure returns a bounded service error before routing to command/screenshot/clipboard handlers;
- add metrics or one-shot log coverage without sensitive fields;
- keep existing request ID format for all non-exhausted requests.

### 4.4 Required tests

Add tests that prove:

- normal request IDs remain monotonic and preserve their accepted format;
- forcing the counter to `u64::MAX` causes allocation failure without panic;
- after exhaustion, no normal request ID wraps to zero, one, or any previously issued normal sequence;
- the exhausted state is terminal for normal allocation;
- the HTTP boundary returns the specified bounded error without reaching a normal handler;
- diagnostics are redaction safe and do not include payloads or secrets.

## 5. Requirement P2 — EventHub sequence exhaustion should wake established clients immediately

### 5.1 Problem

The cleanup loop correctly added established-client close behavior, but the service loop observes sequence exhaustion at the top of the loop. If no event or inbound WebSocket message arrives, the close can be heartbeat-bound.

That is safe and bounded, but not ideal for operator visibility or deterministic tests.

### 5.2 Required behavior

When EventHub sequence exhaustion first becomes terminal:

- already-established WebSocket clients must be woken promptly;
- those clients must still close with code `1011` and reason `event sequence exhausted`;
- the close reason must remain payload-free and secret-free;
- pre-upgrade `503 event_sequence_exhausted` behavior must remain unchanged;
- normal event delivery, ping/pong, idle timeout, slow-client cleanup, and client-capacity behavior must remain unchanged;
- no synthetic user-visible payload event should be added unless the API documentation is explicitly updated.

### 5.3 Implementation constraints

The preferred implementation is an internal notification primitive, such as `tokio::sync::Notify`, owned by `EventHub` and triggered exactly when sequence exhaustion becomes terminal.

The established-client select loop should wait on that notification in addition to receiver, inbound socket, and heartbeat branches. On notification, it should use the same close path and same close reason as the existing exhaustion check.

The implementation must avoid sending command, clipboard, screenshot, framebuffer, token, password, key, pointer, or query details in any event, close reason, or diagnostic.

### 5.4 Required tests

Add or update tests to prove:

- an established client closes promptly after exhaustion even when heartbeat interval is intentionally long;
- the prompt close still uses code `1011`;
- the prompt close still uses exact reason `event sequence exhausted`;
- the test would fail if the implementation only woke on heartbeat;
- the existing cleanup-loop established-client test still passes or is replaced by a stronger equivalent;
- the pre-upgrade `503 event_sequence_exhausted` test still passes;
- normal WebSocket delivery tests still pass.

## 6. Requirement P3 — Native scrub semantic-test decision

### 6.1 Problem

The native scrub policy is currently protected by source-contract tests plus integration/E2E tests. This is acceptable and avoids unsafe freed-memory inspection. However, the project should decide whether a safe pre-free semantic hook can strengthen evidence without creating production risk.

### 6.2 Required behavior

The pass must make an explicit decision and record it.

Option A — add a safe test-only semantic hook:

- hook must observe project-owned sensitive buffers only after scrub and before free;
- hook must be compiled or enabled only for tests, not exposed as a production API;
- hook must not log or return sensitive pre-scrub payloads;
- hook must not read freed memory;
- hook must not depend on allocator reuse;
- source-contract tests must still protect scrub-before-free ordering and call sites.

Option B — retain source-contract strategy:

- implementation notes must explain why a semantic hook would add more risk or complexity than value;
- source-contract tests should be tightened if any obvious gap remains;
- native smoke, WorkerHandle text/clipboard E2E, and sanitizer gates must remain authoritative execution evidence.

### 6.3 Required coverage

Regardless of Option A or B, regression protection must continue to cover:

- stored clipboard replacement scrub;
- stored clipboard destruction scrub;
- outbound temporary clipboard send-copy scrub before free;
- shim-owned persistent VNC password scrub on destruction;
- clipboard revision overflow rejection before allocation/replacement;
- no documentation overclaim beyond project-owned buffers.

## 7. Requirement P4 — Documentation and evidence hygiene

This pass must produce minimal documentation updates:

- final polish implementation notes;
- TODO completion evidence after exact-SHA validation;
- any public/operator docs needed for new request ID exhaustion behavior;
- any security notes needed for the native scrub testing decision.

Do not duplicate large prior TODO sections. Do not edit historical evidence to imply future knowledge. If a documentation-completion commit follows implementation validation, that final exact SHA must also pass CI and Release Gates before the TODO is marked closed.

## 8. Required validation

Local validation should be run whenever a normal checkout and toolchain are available:

- `cargo fetch --locked`
- `cargo fmt --all --check`
- `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- `cargo test --locked --workspace --all-features`
- `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`
- `python -m compileall -q tools/ci_status tests desktop/test-app`
- `python -m unittest discover -s tests -p 'test_*.py' -v`
- permanent shell syntax checks

Where Docker/VNC are available:

- `tests/desktop/run.sh`
- `tests/native/run.sh`
- `tests/worker-e2e/run.sh`
- `tests/worker-text-clipboard-e2e/run.sh`
- `tests/http-e2e/run.sh`
- `tests/compose/run.sh`
- `tests/integration/run.sh`

Unavailable local validation must be recorded as unavailable, with reasons. It must not be described as locally passed.

Final acceptance requires both permanent workflows on the same exact final repository tip:

- CI: success;
- Release Gates: success.

## 9. Final do-not-accept checklist

Do not accept the pass if any of the following are true:

- request IDs can wrap into a normal reused sequence value;
- request ID exhaustion panics, silently saturates, or allows normal handler execution without a valid normal request ID;
- EventHub established clients only learn about sequence exhaustion through heartbeat after the prompt-wake requirement is implemented;
- WebSocket exhaustion close code or reason changes without corresponding documentation and tests;
- native scrub tests read freed memory or depend on allocator reuse;
- project documentation claims third-party or OS-owned residual copies are scrubbed;
- secret-bearing config types regain implicit general-purpose `Clone` without a new explicit reviewed need;
- API token ownership regresses from `ApiToken -> Arc<SecretString>` to raw long-lived ordinary string ownership;
- command metrics regain silent default-zero methods;
- old queue-depth aliases return without an explicit external compatibility requirement;
- broad Gitleaks ignore rules, path ignores, wildcard ignores, or rule suppressions are added;
- CI or Release Gates are weakened, skipped, converted to advisory, or satisfied using older/superseded/canceled/partial runs.
