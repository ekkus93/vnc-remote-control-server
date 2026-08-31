# VNC Remote Control Server — Code Review Remediation Spec

Date: 2026-08-31
Branch target: `master`
Starting reviewed SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`

## 1. Purpose

This specification defines the correctness and hardening remediation pass arising from the 2026-08-31 review of the current `master` branch. The repository is already in a strong state: the architecture is layered, unsafe/native code is isolated, resource bounds are generally explicit, secrets are handled conservatively, the worker command queue is bounded, screenshots are coherence-checked, HTTP errors are structured, and CI/Release Gates are extensive.

The review nevertheless identified several failure-mode defects and ambiguous contracts that should be corrected before adding a Model Context Protocol (MCP) server or otherwise exposing the controller to autonomous agents. The highest-priority issue is command timeout semantics: a caller can currently receive a timeout even though the command may later execute, making a retry potentially duplicate a click, keystroke sequence, text entry, or clipboard mutation.

This remediation pass must preserve the project's existing fail-closed posture. A failure must not be hidden behind best-effort success, an ignored return value, a stale value represented as current, or a retry that can duplicate side effects.

## 2. Scope

This pass covers the following reviewed findings:

- indeterminate command outcome after HTTP acknowledgement timeout;
- scroll-wheel release failures that can leave remote pointer state unknowable without tracking that uncertainty;
- native inbound clipboard callback failures that can be reduced to a stale cached clipboard with no surfaced error;
- millisecond-named configuration values that are accepted by configuration parsing but later rejected or narrowed at the native boundary;
- overly permissive inbound WebSocket event-stream messages and frame/message size limits;
- a silent `xfconf-query ... || true` fallback and incomplete XFCE readiness proof in `desktop/xstartup`;
- worker shutdown paths that can return a timeout while the worker thread continues detached;
- worker error classification that can flatten native or other failures into `Protocol`.

The pass also establishes regression and evidence requirements for silent-failure prevention.

## 3. Explicit non-goals

This remediation pass must not:

- implement an MCP server;
- redesign the public API merely for aesthetic reasons unrelated to a reviewed defect;
- replace LibVNCClient or the project-owned C shim;
- add OCR, browser automation, noVNC, multi-session control, or AI planning;
- weaken authentication, input validation, screenshot coherence checks, event sequencing, queue bounds, secret handling, or release gates;
- introduce broad `catch-all and continue`, `unwrap_or_default`, `or_else` fallback success, `|| true`, `let _ =` error suppression, `continue-on-error`, or equivalent behavior in correctness-critical paths without a documented and tested justification;
- automatically retry non-idempotent desktop mutations after an ambiguous outcome;
- report shutdown completion unless the worker is actually known to have exited.

MCP design work begins only after this remediation pass is complete and its exact final SHA has passed the required gates.

## 4. Cross-cutting correctness policy

### 4.1 Failures must retain semantic meaning

Errors should be represented at the narrowest useful layer and mapped explicitly at boundaries. A native allocation failure, protocol failure, transport failure, timeout, stale state, state uncertainty, overload condition, and clean remote disconnect are not interchangeable.

One authoritative mapping should be used where `DesktopError` or equivalent lower-level errors become worker/API failure classes. Do not duplicate ad hoc mappings in multiple call sites.

### 4.2 Unknown state is not success

If the process can no longer prove the remote input state, clipboard state, command outcome, worker lifecycle state, or framebuffer currency, the API must represent that uncertainty explicitly or invalidate/re-establish the affected session. It must not continue serving old state as though it were known current.

### 4.3 Mutation retries require proof of safety

Clicks, scrolls, key events, chords, typed text, and clipboard writes are non-idempotent or potentially non-idempotent. A timeout after submission is therefore not equivalent to a proven failure-before-execution. The server and clients must not imply that immediate retry is safe unless idempotency/deduplication semantics prove it.

### 4.4 Ignored errors require narrow justification

Ignored return values are acceptable only for operations where the result cannot alter correctness, such as sending a completion to a requester that has already disconnected or racing process cleanup of an already-exited child. The code should make that rationale obvious locally. Errors that can affect authoritative state, security, startup readiness, or remote input state must not be discarded.

## 5. R1 — Make command timeout outcomes explicit and safe

### 5.1 Problem

`WorkerHttpBackend::execute_command()` submits a command and waits on its completion ticket for a configured timeout. If `CommandTicket::wait()` times out, the caller receives a timeout, but the queued or executing command is not cancelled. The command may still execute later.

For a mutation such as click, type, key chord, scroll, or clipboard set, retrying after this response can duplicate the action. This is unacceptable for an MCP or other agent client and is already ambiguous for ordinary API clients.

### 5.2 Required behavior

The system must distinguish at least these outcomes:

- definitely not accepted/submitted;
- queued or executing with final outcome not yet known;
- succeeded;
- failed with a known failure;
- outcome unknown because acknowledgement/status observation timed out or became unavailable.

A timeout that occurs after the command has been assigned a command ID must preserve that ID in the response path.

The server must not return a representation that encourages clients to interpret an ambiguous mutation as safely retryable.

### 5.3 Acceptable design options

Preferred design:

- retain command IDs as durable process-local execution identities for at least a bounded status window;
- expose command status such as `queued`, `executing`, `succeeded`, `failed`, and `outcome_unknown` or an equivalent finite state model;
- on acknowledgement timeout, return the command ID plus explicit outcome uncertainty;
- make retry safety explicit, e.g. `retry_safe: false`, for mutation commands with uncertain outcome.

A smaller initial fix is acceptable if it still preserves the command ID and returns an explicit structured ambiguous-outcome response. However, do not falsely claim cancellation unless cancellation is proved not to race execution.

### 5.4 API semantics

Review the existing HTTP status and response wording. Returning `202 Accepted` only after the worker reports successful completion is semantically confusing. The revised contract should clearly separate submission from final execution outcome.

Any API change must update:

- Rust response/error types;
- handlers/backend tests;
- OpenAPI/docs if present;
- Python client types and tests;
- examples/operator documentation that depends on the old contract.

### 5.5 Tests

Required regression coverage includes:

- command completes before wait timeout;
- command fails before wait timeout;
- command remains queued/executing beyond wait timeout and later succeeds;
- command remains queued/executing beyond wait timeout and later fails;
- caller receives the same command ID in the ambiguous timeout response;
- ambiguous timeout is explicitly not marked retry-safe for mutation commands;
- no automatic client retry occurs for ambiguous mutations;
- command status retention/expiration is deterministic and bounded if a status store is added.

## 6. R2 — Make scroll-wheel pointer state fail closed

### 6.1 Problem

Scroll sends a pointer mask with a transient wheel bit and then sends a release mask. If the first release fails, the implementation makes a second best-effort release whose result is ignored. The transient wheel bit is not represented in the tracked persistent `button_mask`.

If the wheel-down event reached the server and both releases fail, the local process cannot prove the remote pointer state. `release_all()` may also have no tracked wheel bit to correct because ordinary `button_mask` can remain zero.

### 6.2 Required behavior

A failed release must not leave the controller claiming a known-clean pointer state when it cannot prove one.

The implementation must choose and document one of these policies:

1. track actual/uncertain pointer mask state until a release is confirmed; or
2. mark the VNC input/session state uncertain and invalidate/reconnect the VNC session before accepting further input.

The second option is preferred if LibVNCClient/RFB semantics make transient wheel-state tracking unreliable.

Do not silently ignore a second release failure.

### 6.3 Tests

Add deterministic tests for:

- successful scroll press/release;
- first release failure followed by successful corrective release;
- first and corrective release both failing;
- no further input being treated as safe while state is uncertain, if session invalidation is chosen;
- reconnect/reset restores a known-clean state;
- existing key/button release tracking remains unchanged.

## 7. R3 — Propagate inbound native clipboard callback failures

### 7.1 Problem

The native clipboard callback can reject an incoming update because it exceeds the maximum size, allocation fails, the revision cannot advance, or input is invalid. The callback records a native error but does not directly fail `HandleRFBServerMessage()`. `vrc_client_poll()` can therefore return success. If the clipboard revision does not change, Rust sees no update and can continue serving the previous clipboard value as though it were current.

This is a quiet stale-state failure.

### 7.2 Required behavior

A clipboard callback failure must become observable to the polling/worker layer. The old cached clipboard must not continue to be represented as known-current after a rejected newer server clipboard update.

The native shim should expose callback failure state in a way that `vrc_client_poll()` or an adjacent explicit query consumes exactly once or otherwise handles deterministically.

Required policy by failure class:

- oversized clipboard: explicit bounded-input failure; mark clipboard unavailable/stale or invalidate session according to the chosen contract;
- allocation failure: explicit native/resource failure; reconnect or fail the session if state cannot be trusted;
- revision exhaustion: fail closed; do not wrap or silently retain old data;
- invalid callback input: explicit native/protocol failure with no stale-success representation.

Do not log clipboard payload contents.

### 7.3 Tests

Required native/Rust tests should cover each failure class and prove that:

- poll/refresh no longer reports ordinary success while retaining an old authoritative clipboard after a rejected newer update;
- the error is classified correctly;
- no secret or clipboard payload is logged;
- recovery/reconnect behavior is deterministic.

## 8. R4 — Align configuration units with native representability

### 8.1 Problem

Configuration exposes millisecond-named timeout variables such as VNC connect/read timeouts, but native connection setup converts some durations through a whole-seconds helper that rejects fractional seconds. Polling also narrows microseconds into `u32`.

Thus values can parse successfully as configuration but fail only later at the native/runtime boundary.

### 8.2 Required behavior

Configuration validation must prove all externally configurable timeout values are representable by their downstream consumers before worker startup.

Preferred outcome: preserve the documented millisecond contract and update the C shim/native boundary to support millisecond precision where practical.

If an underlying library only supports whole seconds for a specific operation, the public configuration contract must state and validate that granularity explicitly at startup rather than failing during a connection attempt.

Add explicit upper bounds sufficient to prevent narrowing overflow and unsafe deadline arithmetic.

### 8.3 Tests

Cover:

- minimum valid value;
- fractional-second values such as 1500 ms;
- exact second values;
- maximum representable values;
- one-above-maximum rejection;
- zero rejection where zero is invalid;
- no late native conversion rejection for a configuration that startup validation accepted.

Error messages must identify the offending configuration key and constraint without exposing secrets.

## 9. R5 — Harden WebSocket inbound behavior

### 9.1 Problem

`/v1/events` is logically a server-to-client event stream, yet inbound Text/Binary frames are accepted as activity, and no intentionally small per-route frame/message limits were found. Framework defaults are much larger than this endpoint needs.

### 9.2 Required behavior

The endpoint must define and enforce its client-to-server protocol:

- Ping/Pong and Close control behavior may be supported as needed;
- Text and Binary application messages should be rejected because the endpoint has no client application-message protocol;
- inbound message and frame sizes must be intentionally small and documented;
- an authenticated client must not be able to consume large memory/CPU through irrelevant inbound messages;
- event delivery, heartbeat, lag handling, and shutdown behavior must remain correct.

### 9.3 Tests

Cover:

- normal event streaming;
- Ping/Pong behavior;
- graceful Close;
- Text rejection;
- Binary rejection;
- oversized frame/message rejection;
- client-count limits and lag behavior remain intact.

## 10. R6 — Make XFCE startup readiness fail closed

### 10.1 Problem

`desktop/xstartup` currently suppresses failure from the `xfconf-query` that sets `/general/SaveOnExit` to false and then waits in a bounded loop for the property. If the property never becomes available but XFCE remains alive, the loop can exhaust and startup can continue anyway.

That is a real silent fallback and weakens deterministic desktop state, especially when home state is persistent.

### 10.2 Required behavior

Startup must prove the required XFCE property exists and has the intended value before the test application is executed.

The script must:

- not use `|| true` on the correctness-critical SaveOnExit setting;
- distinguish temporary unavailability during startup from final failure;
- after the bounded wait, perform an explicit final verification;
- fail startup with a useful diagnostic if the property is unavailable or not false;
- avoid dumping sensitive environment values.

Cleanup-only `kill ... || true` or `wait ... || true` cases may remain where process-exit races make them intentionally idempotent and correctness is unaffected.

### 10.3 Tests

Add or extend shell/container tests for:

- property eventually available and set to false;
- setter permanently failing;
- getter/property permanently unavailable;
- property resolving to the wrong value;
- startup exits nonzero rather than silently proceeding in failure cases.

## 11. R7 — Tighten worker shutdown lifecycle semantics

### 11.1 Current tradeoff

The existing out-of-band shutdown signal is a correct improvement over queue-based shutdown. However, after a bounded shutdown timeout, `DesktopWorker::shutdown()` and related cleanup can detach the worker thread because Rust cannot safely kill an arbitrary thread. The process-level architecture generally exits afterward, which makes this defensible operationally, but the abstraction does not mean "shutdown timeout implies worker is gone."

### 11.2 Required behavior

At minimum:

- document that a timeout means termination is not confirmed;
- do not expose a state or API result that implies the worker has stopped if the thread is still alive or unknown;
- retain bounded process shutdown;
- record the abnormal lifecycle state without logging secrets/payloads;
- add tests proving the semantic distinction.

The implementation should investigate whether native waits can be interrupted or made short enough that normal shutdown can join reliably without detachment. If this can be implemented safely and portably within the existing architecture, prefer it.

If detachment must remain, document it as a deliberate process-appliance limitation and ensure no reusable-library API promises stronger ownership semantics than it provides.

### 11.3 Tests

Cover:

- orderly worker exit and confirmed join;
- shutdown timeout with worker still alive/unknown;
- no false `Stopped`/clean completion claim for an unconfirmed exit;
- process-level shutdown remains bounded;
- startup-timeout cleanup has the same explicit semantics.

## 12. R8 — Centralize worker failure classification

### 12.1 Problem

Some errors arising while processing a connected-session message are broadly classified as `Protocol`, even when the underlying cause can be native/resource/clipboard-related. This does not hide the failure, but it degrades diagnostics and operational evidence.

### 12.2 Required behavior

Create one authoritative conversion from lower-level desktop/native errors to `WorkerFailureKind` or equivalent. Use it consistently across worker connection, polling, command execution, framebuffer/clipboard processing, and cleanup paths.

Do not classify everything unexpected as protocol failure merely because it occurred while handling an RFB message.

### 12.3 Tests

Add table-driven/unit coverage showing representative lower-level failures map to the intended worker categories, including at least:

- transport/connectivity;
- protocol;
- native/resource;
- timeout;
- invalid input/configuration where applicable;
- clean disconnect versus abnormal disconnect.

## 13. R9 — Silent-fallback audit and policy enforcement

After implementing R1-R8, perform a focused repository audit for constructs that can suppress correctness-relevant failures, including:

- `|| true`;
- `let _ =`;
- `unwrap_or`, `unwrap_or_default`, `unwrap_or_else`;
- broad `match _` fallbacks;
- ignored `Result`s;
- broad Python `except Exception`;
- timeout paths that abandon work;
- stale-cache fallback;
- fallback defaults after parse/validation failure;
- `continue-on-error` in GitHub Actions.

Each occurrence must be classified as:

1. correctness-safe and locally justified;
2. cleanup/idempotency-only and locally justified;
3. deliberate compatibility fallback with explicit observability and tests; or
4. defect requiring remediation.

The goal is not to ban these language constructs. The goal is to prevent quiet state corruption, stale-success behavior, or false completion.

## 14. Existing behavior that must remain intact

The remediation must preserve:

- raw VNC private to the internal Compose network;
- bearer authentication on `/v1/*`;
- constant-time token comparison;
- secret-file based credential loading and redaction;
- framebuffer coherence/staleness guarantees;
- screenshot concurrency bounds and permit retention after caller timeout;
- bounded worker command/event queues;
- out-of-band shutdown initiation independent of normal queue capacity;
- sequence-overflow fail-closed behavior;
- preflight input validation and no silent coordinate/input clamping;
- tracked key/button release behavior;
- clipboard UTF-8/NUL/size validation;
- native buffer overflow checks and maximum sizes;
- non-root/read-only/hardened controller container posture;
- full CI and Release Gates enforcement.

## 15. Documentation and compatibility requirements

Update any living documentation affected by changed behavior, including as applicable:

- README/API examples;
- operator/deployment guide;
- OpenAPI/schema documentation;
- Python client documentation;
- error-code documentation;
- architecture or worker lifecycle notes.

If an API response changes incompatibly, document the compatibility impact and update all in-repository clients/tests in the same remediation task. Do not leave the Python client interpreting a new server error using old retry assumptions.

## 16. Validation requirements

The implementation must run the repository's established local quality gates where available, including Rust formatting, Clippy with warnings denied, full workspace tests, rustdoc warnings denied, Python compilation/tests, shell syntax/ShellCheck, and relevant Docker/container/integration tests.

The final exact SHA must pass both normal CI and Release Gates. No gate may be weakened, made non-blocking, or selectively skipped to make the remediation pass.

The final pass must include evidence containing:

- starting reviewed SHA;
- final implementation SHA;
- list of files changed per remediation item;
- tests added/changed per remediation item;
- final CI run ID and conclusion;
- final Release Gates run ID and conclusion;
- any deliberate remaining limitation, especially worker detachment if retained;
- outcome of the silent-fallback audit;
- explicit statement that no correctness-critical failure was converted into quiet success.

Suggested evidence path:

`docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

## 17. Completion criteria

This remediation pass is complete only when all of the following are true:

- R1-R8 are implemented and regression-tested;
- R9 silent-fallback audit is completed and every relevant occurrence is classified or fixed;
- API/Python/documentation contracts are synchronized;
- no ambiguous command timeout can be mistaken for a safe-to-retry failure;
- no failed scroll release leaves remote state unknowable while the session is treated as clean;
- no rejected inbound clipboard update silently leaves an old value represented as current;
- all accepted timeout configuration values are representable by downstream native code;
- WebSocket inbound traffic is tightly bounded and application data is rejected;
- XFCE startup cannot silently continue without proving SaveOnExit configuration;
- worker shutdown timeout semantics do not falsely imply confirmed termination;
- failure classification preserves meaningful categories;
- exact-final-SHA CI passes;
- exact-final-SHA Release Gates pass;
- final evidence is committed;
- the companion TODO is fully reconciled.

Only after these conditions are met should the project proceed to the MCP server specification and implementation.