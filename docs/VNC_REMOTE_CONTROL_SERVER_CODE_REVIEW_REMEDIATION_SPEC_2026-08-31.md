# VNC Remote Control Server — Code Review Remediation Spec

Date: 2026-08-31
Branch: `master`
Reviewed baseline SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`
Planned evidence document: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

## 1. Purpose

This specification defines the post-review remediation pass for the current VNC Remote Control Server implementation. The reviewed baseline is structurally strong and passed both regular CI and Release Gates, but the review found several correctness and failure-semantics gaps that should be resolved before adding an MCP server or placing more automation on top of the controller API.

The most important theme is **state certainty**. A remote-control server must never tell a caller that an operation failed when it may still execute, silently continue using stale authoritative state after an update was dropped, or pretend that remote input state is known after release operations could not be confirmed. Those cases become materially more dangerous when an autonomous client is added.

This pass therefore focuses on explicit command outcomes, fail-closed handling of uncertain remote state, native callback error propagation, configuration contracts, bounded WebSocket input, deterministic desktop startup, shutdown lifecycle semantics, and accurate failure classification.

MCP implementation is intentionally deferred until this remediation pass is complete and validated.

## 2. Reviewed baseline and existing evidence

Review baseline:

- `master` SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`
- Regular CI run `31265957251`: success
- Release Gates run `31265957258`: success

The passing gates are important evidence that this remediation is not a rewrite of a broken system. Existing strengths that must be preserved include:

- bounded worker command and event channels;
- out-of-band worker shutdown initiation;
- strict request/config validation;
- constant-time bearer-token comparison;
- coherent framebuffer snapshot ownership;
- screenshot concurrency accounting that survives caller timeout;
- project-owned C shim around LibVNCClient;
- explicit framebuffer and clipboard size limits;
- checked native allocation/size arithmetic;
- secret-file handling and redacted logs;
- tracked key/button release behavior;
- raw VNC isolation on the internal Compose network;
- non-root, capability-dropped controller container;
- comprehensive Rust, Python, shell, native, Docker, Compose, E2E, sanitizer, Miri, supply-chain, secret-scan, and vulnerability gates.

The remediation must not weaken any of these properties.

## 3. Findings to remediate

The review identified the following concrete issues.

### R1 — Indeterminate command outcome after acknowledgement timeout — HIGH

`WorkerHttpBackend::execute_command()` submits a command and then waits for its `CommandTicket`. When the wait times out, the caller receives a timeout error, but the queued or already-running command is not cancelled and may still execute afterward.

For side-effecting operations such as click, type, chord, scroll, or clipboard mutation, retrying after that response can duplicate the action. This is unsafe for humans and especially unsafe for an MCP/agent client.

The API currently also uses acceptance-oriented response wording/status while waiting for command execution completion, which makes the lifecycle contract less precise than it should be.

### R2 — Scroll release failure can leave untracked remote pointer state — MEDIUM-HIGH

Scroll sends a transient wheel-button mask and then sends a release. If release fails, the implementation retries, but the second release result is ignored. The transient wheel bit is not represented in the normal tracked `button_mask`, so if both releases fail the local controller can no longer prove the remote pointer state.

Continuing to use that session as though pointer state were known is not acceptable.

### R3 — Native inbound clipboard callback failure can be silently hidden — MEDIUM

The C clipboard callback can reject an inbound server clipboard update because of oversize input, allocation failure, invalid state, or revision exhaustion. The callback records an error string, but the normal LibVNCClient message handler can still report success. Rust then sees no clipboard revision change and may continue serving the previous clipboard value as though it were current.

This is a true silent stale-state failure.

### R4 — Public duration configuration and native representability are inconsistent — MEDIUM

Configuration values are expressed as millisecond durations, but native connection/read timeout conversion currently requires positive whole seconds, while polling has a separate `u32` microsecond boundary. Values can therefore pass initial configuration parsing and fail only later at the native boundary.

Validation must happen once, early, and against the actual runtime/native contract.

### R5 — WebSocket event endpoint accepts unnecessarily large/irrelevant inbound data — MEDIUM-LOW

The event WebSocket is logically a server-to-client stream, but inbound Text/Binary messages are accepted as activity and default WebSocket message/frame limits are much larger than required for control traffic.

Authenticated clients should not be able to consume unnecessary memory/CPU with large messages on a read-mostly endpoint.

### R6 — XFCE startup contains a silent `SaveOnExit` fallback — LOW-MEDIUM

`desktop/xstartup` suppresses failure from the initial `xfconf-query` with `|| true` and later proceeds after a bounded polling loop even if the desired property was never proven available and false.

The desktop can therefore become ready without proving the deterministic session setting that the script is trying to enforce.

### R7 — Worker shutdown timeout can detach a still-running thread — LOW

The worker uses bounded shutdown, which is preferable to hanging indefinitely. On timeout, however, the join handle can be dropped/detached while the thread may still be running. This is partly an unavoidable consequence of Rust threads not supporting safe forced termination and is defensible during process teardown, but the abstraction must not imply that timeout/detach means the worker has terminated.

This finding requires tightening lifecycle semantics and evidence, not introducing unsafe thread-kill behavior.

### R8 — Worker errors can lose accurate failure classification — LOW

Some errors raised while processing connected-session messages are recorded broadly as `WorkerFailureKind::Protocol`, even when the underlying cause is native, resource, state, clipboard, framebuffer, or another error class.

The failure is not silent, but inaccurate classification weakens diagnostics and operational decisions.

## 4. Scope and non-goals

This pass is specifically for the findings above.

It must not:

- implement an MCP server;
- introduce a second VNC implementation;
- add OCR, browser automation, AI planning, multi-session support, or noVNC;
- weaken bearer authentication or expose VNC/controller credentials;
- make request validation permissive;
- silently clamp coordinates, input sizes, timeouts, or unsupported input;
- auto-retry side-effecting commands after an uncertain outcome;
- replace explicit failures with logs plus success responses;
- add `continue-on-error` to release-critical workflows;
- disable or broadly bypass Gitleaks, cargo-deny, Trivy, ShellCheck, actionlint, sanitizer, Miri, Docker, Compose, or E2E gates;
- use unsafe thread termination to solve R7;
- broaden secret logging or include typed text, clipboard contents, bearer tokens, VNC passwords, screenshots, or other sensitive payloads in diagnostics.

## 5. Global engineering rules

Every remediation task must follow these rules.

### 5.1 Fail closed when authoritative state becomes unknowable

If the controller cannot prove whether a remote input transition or authoritative data update succeeded, it must either:

1. explicitly represent the uncertainty to callers; or
2. invalidate/taint the affected state or session and require recovery before additional dependent operations.

It must not silently keep serving an older value as current or continue operating as though remote state were known.

### 5.2 No unsafe automatic retries of mutations

Queue-full-before-acceptance and validation failures can be retryable because the command was never accepted for execution. A timeout after command acceptance is different: it is an **unknown outcome**, not a known failure.

No HTTP client, Python client, future MCP adapter, or internal helper may automatically retry a side-effecting command whose outcome is unknown.

### 5.3 No ignored error without an explicit invariant-based rationale

New or changed code must not introduce unexamined patterns such as:

- Rust `let _ = fallible_call()`;
- Rust `.ok()`/`unwrap_or*()` that erases an operational failure;
- shell `|| true` on correctness-sensitive operations;
- broad Python `except Exception: pass`;
- best-effort cleanup that is later treated as confirmed success.

Some ignored results are valid for idempotent cleanup races or abandoned completion receivers. Those cases must remain narrow and must not hide correctness-sensitive state transitions.

### 5.4 Bounded resource usage

Any new command-outcome storage, WebSocket buffering, diagnostics, or retry mechanism must be explicitly bounded by capacity, lifetime, or both. A fix must not trade one correctness issue for unbounded memory growth.

### 5.5 API/client behavior must agree

When HTTP semantics change, the Python client, API documentation, examples, tests, and E2E contracts must change in the same remediation task. The server must not have one interpretation of timeout/success while the Python client exposes another.

## 6. R1 design — deterministic command identity and explicit unknown outcomes

R1 is the highest-priority blocker and must be completed before the later MCP phase.

### 6.1 Command ID allocation

A stable command ID must exist **before** a command is admitted to the worker queue. Once the command is accepted for possible execution, every subsequent response/error about that command must retain the same ID.

ID exhaustion must continue to fail closed.

### 6.2 Distinguish pre-acceptance failure from post-acceptance uncertainty

The implementation must distinguish at least these cases:

- request rejected by validation: command never accepted;
- command queue full/disconnected before admission: command never accepted;
- command accepted and completed successfully;
- command accepted and completed with a known failure;
- command accepted but caller wait timed out before a terminal result was observed;
- worker/session terminated while an accepted command had no terminal result.

Only the timeout case is `outcome_unknown` from the immediate caller's perspective. It must never be represented as a known execution failure.

### 6.3 Bounded command outcome registry

Introduce a process-local, bounded command outcome/status registry keyed by command ID. It must retain accepted commands long enough for a caller that receives an unknown outcome to inspect the eventual result.

Required terminal/nonterminal states should cover the observable lifecycle, for example:

- `queued`;
- `running` if the worker can mark execution start reliably;
- `succeeded`;
- `failed` with a typed/sanitized error classification;
- `aborted` when the worker terminates before a normal terminal result can be produced.

Exact names may differ, but known failure, successful execution, still-pending work, and abnormal termination must be distinguishable.

The registry must have a documented capacity and/or TTL. Eviction must never expose secret/payload data. If an accepted command record is expired, the status endpoint must report that explicitly rather than inventing a result.

### 6.4 Status inspection endpoint

Add an authenticated command-status API such as:

`GET /v1/commands/{command_id}`

The endpoint must return a strict schema containing the command ID, lifecycle state, and safe diagnostic metadata needed to determine whether another mutation is appropriate. It must not return typed text, clipboard payloads, bearer tokens, VNC credentials, screenshot data, or other sensitive command arguments.

### 6.5 Timeout response contract

When the HTTP wait expires after command acceptance, return a structured timeout error that includes at least:

```json
{
  "code": "command_timeout",
  "command_id": "...",
  "outcome": "unknown",
  "retry_safe": false
}
```

The precise envelope may follow existing API conventions, but these semantics are mandatory.

The response must state that the acknowledgement/result wait timed out; it must not say or imply that the command did not execute.

### 6.6 Successful mutation response semantics

If the mutation endpoint waits for the command to reach a terminal successful result before responding, use success wording/status that reflects completed execution rather than merely "accepted" asynchronous work.

Preferred outcome: return a normal successful completion status such as HTTP 200 with the command ID and terminal status.

If HTTP 202 is retained, the implementation must become genuinely asynchronous and direct callers to the status endpoint. Do not keep the current semantic mismatch.

### 6.7 Python client behavior

The Python client must expose timeout-after-acceptance as a distinct exception/result carrying the command ID and `retry_safe = False` semantics. It must not transparently retry.

Add a status lookup method and strict response validation.

### 6.8 Required R1 tests

Tests must prove:

- a command that completes before the wait bound returns known success;
- a command that fails before the wait bound returns known failure;
- queue-full/pre-admission failure does not claim unknown execution;
- an accepted command can time out at HTTP level and later succeed;
- the timeout response preserves the same command ID later returned by status lookup;
- the caller is told `retry_safe: false` for the unknown outcome;
- a worker termination marks outstanding accepted commands as aborted or another explicit terminal abnormal state;
- registry capacity/TTL behavior is bounded and deterministic;
- status records never contain secret or command payload content;
- Python client does not auto-retry mutation timeouts.

## 7. R2 design — fail closed on unresolvable scroll release

### 7.1 No ignored second release result

The second wheel-release attempt must be observed and handled. The implementation must not discard its `Result`.

### 7.2 Known vs uncertain pointer state

The code must preserve a conservative model of remote pointer state.

Preferred design for the current architecture:

1. send the transient wheel-button press;
2. send the normal-mask release;
3. if that release fails, retry the release once using the known normal mask;
4. if the retry succeeds, return the original operation error if appropriate but keep pointer state known;
5. if the retry also fails, return a distinct input-state/session-state error indicating that remote pointer state is uncertain;
6. taint/invalidate the current VNC session before accepting further input that assumes known pointer state;
7. reconnect/re-establish a clean session according to the worker's existing recovery policy.

An alternative fully tracked transient-mask design is acceptable only if it can prove equivalent safety.

### 7.3 Required R2 tests

Add deterministic tests for:

- wheel press succeeds and release succeeds;
- first release fails and retry succeeds;
- both release attempts fail;
- double failure is not swallowed;
- double failure causes the session/input state to become unusable until recovery;
- subsequent commands do not execute on the tainted session;
- recovery establishes clean tracked pointer state;
- existing normal button/key tracking behavior remains unchanged.

## 8. R3 design — propagate native clipboard callback failures

### 8.1 C callback failure must survive the message-dispatch boundary

The C shim must record callback failures in machine-readable state, not only in a best-effort error string. After `HandleRFBServerMessage()` returns, `vrc_client_poll()` must detect whether an inbound callback failed and return an appropriate non-success status.

The error state must be cleared/consumed deterministically so a previous callback failure cannot contaminate later successful polls.

### 8.2 Failure classes

At minimum distinguish these classes sufficiently for Rust policy decisions:

- inbound clipboard exceeds configured maximum;
- invalid clipboard/update data or native state;
- allocation/resource failure;
- revision/counter exhaustion or internal invariant failure.

Exact status enum expansion is implementation-dependent, but collapsing every case into silent success is forbidden.

### 8.3 Never serve an old clipboard as current after a rejected newer update

If the server delivered a newer clipboard update that the controller could not safely store, the Rust/controller layer must no longer present the previous cached value as current authoritative clipboard state.

Acceptable recovery policies include:

- mark clipboard state unavailable/stale while leaving the session usable for unrelated operations; or
- invalidate/reconnect the session for failures that make connection state unreliable.

Preferred classification:

- policy/data rejection such as oversize clipboard: invalidate current clipboard snapshot, surface a typed clipboard-unavailable/rejected condition, keep unrelated desktop functions available if safe;
- allocation failure or native invariant/revision exhaustion: fail the poll and invalidate the session or mark the worker fatal according to severity.

Whichever policy is chosen must be explicit and tested.

### 8.4 Observability

Emit structured diagnostics/metrics for rejected inbound clipboard updates without logging clipboard contents. Include safe metadata such as category and byte length when useful.

### 8.5 Required R3 tests

Cover the C shim and Rust boundary for:

- valid clipboard update;
- oversize update;
- simulated allocation failure where test hooks permit it;
- invalid/revision failure helper logic;
- callback failure followed by `vrc_client_poll()` returning non-success;
- stale previous clipboard not being served as current;
- recovery after a later valid update or reconnect;
- no clipboard payload contents in logs/errors/status.

## 9. R4 design — centralized duration validation

### 9.1 Validate before worker/native startup

All externally configured duration values must be validated at configuration construction/startup against the constraints of every downstream representation they will use.

A value that cannot be represented by the native shim must fail as a configuration error before the worker thread is started.

### 9.2 Unit and granularity contract

Environment/configuration names expressed in milliseconds must have a documented granularity policy.

Preferred minimal remediation if LibVNCClient connection/read fields remain whole-second values:

- continue accepting millisecond-form configuration values;
- require positive multiples of 1000 ms for native whole-second fields;
- reject values such as 1500 ms immediately with an error that explicitly states the required granularity;
- do not silently floor, ceil, round, or truncate.

If the native shim is changed to provide true millisecond semantics, that is also acceptable, but it must be verified against the underlying LibVNCClient behavior and tested. Silent rounding remains forbidden.

### 9.3 Upper bounds and conversions

Validate all narrower conversions, including poll timeout conversion to `u32` microseconds. Define sensible project-level maximums so extremely large values cannot reach `Instant` arithmetic or native fields unchecked.

Use checked conversion/arithmetic rather than `as` casts for narrowing values.

### 9.4 Required R4 tests

Cover:

- zero;
- minimum valid values;
- non-representable fractional-second values if whole-second native granularity remains;
- normal representative values;
- maximum allowed values;
- one-above-maximum values;
- `u32` microsecond boundary where relevant;
- config errors occurring before worker/native initialization;
- exact error messages or codes remaining payload/secret safe.

## 10. R5 design — harden inbound WebSocket behavior

### 10.1 Explicit small inbound limits

Configure explicit WebSocket max message/frame sizes appropriate for control frames rather than inheriting large library defaults.

Because RFC 6455 control-frame payloads are at most 125 bytes, a small project limit such as 1 KiB is sufficient unless implementation details require a slightly larger bound. The exact value must be documented and tested.

### 10.2 Allowed inbound message types

The event stream is server-to-client application data. Client Text and Binary messages are not part of the application protocol and must be rejected explicitly, preferably with an appropriate WebSocket close code such as 1003.

Ping/Pong/Close control behavior must continue to work as required for liveness/cleanup.

Do not treat arbitrary Text/Binary payloads as valid heartbeat activity.

### 10.3 Required R5 tests

Cover:

- normal event delivery;
- Ping/Pong behavior;
- orderly Close;
- Text rejection;
- Binary rejection;
- oversized frame/message rejection;
- client-count/resource cleanup after rejection;
- authentication requirements unchanged.

## 11. R6 design — deterministic XFCE startup

### 11.1 Remove correctness-sensitive `|| true`

The `SaveOnExit` configuration must not be silently ignored.

Because XFCE/xfconf may need time to become ready, the script may retry, but each attempt must be explicit and the final outcome must be checked.

### 11.2 Required startup sequence

A robust sequence should:

1. start the XFCE session;
2. while the session remains alive, retry setting `/general/SaveOnExit` to `false` for a bounded number of attempts;
3. read the property back and verify it is exactly false;
4. proceed to the test application only after verification succeeds;
5. fail the startup script nonzero if XFCE exits, the timeout expires, the property cannot be written/read, or the verified value is wrong.

Cleanup-time `kill ... || true`/`wait ... || true` patterns may remain when they are handling normal process-race/idempotent cleanup and are not used to claim successful configuration.

### 11.3 Required R6 tests

Add shell/unit/integration coverage that proves:

- immediate property success;
- delayed property availability succeeds within the bound;
- persistent setter failure fails startup;
- getter never becoming available fails startup;
- wrong final value fails startup;
- XFCE early exit fails startup;
- shell syntax/ShellCheck remain clean.

## 12. R7 design — explicit bounded shutdown outcomes

R7 must preserve bounded shutdown. Do not replace a bounded timeout with an unbounded `join`.

### 12.1 Explicit outcome semantics

A shutdown call that times out while the worker may still be running must return/record an explicit abnormal outcome such as `TimedOut`/`TimedOutDetached`. It must never transition the logical worker state to confirmed orderly `Stopped` solely because the join handle was dropped.

### 12.2 Restrict detach to exceptional teardown

Detaching a still-running worker thread is acceptable only as an explicitly abnormal last-resort path when the process cannot safely block forever. It must be:

- bounded;
- logged/metriced without secrets;
- distinguishable from orderly shutdown;
- covered by tests;
- documented as a process-teardown tradeoff rather than thread termination.

Where feasible, tighten native polling/read bounds so the normal shutdown path can observe the out-of-band shutdown flag and join reliably within its configured lifecycle budget.

### 12.3 Reusable abstraction behavior

Review whether any code path can continue using a `DesktopWorker` owner after a shutdown timeout/detach. The public API must prevent or clearly represent that invalid lifecycle state.

### 12.4 Required R7 tests

Cover:

- orderly shutdown joins and reports `Stopped`;
- saturated command queue still cannot block shutdown initiation;
- deliberately stuck/slow worker returns timeout within the requested bound;
- timeout does not claim thread termination or clean stop;
- dropping after abnormal timeout remains bounded;
- process shutdown remains bounded;
- diagnostics distinguish orderly and detached/timeout outcomes.

## 13. R8 design — authoritative failure classification

### 13.1 One mapping policy

Create one authoritative mapping from `DesktopError` (and any relevant native/input sub-errors) to `WorkerFailureKind` rather than choosing ad hoc categories at individual call sites.

The mapping must distinguish at least the existing meaningful categories such as configuration/startup, transport, authentication, protocol, native/resource, input/state, and shutdown/fatal conditions to the extent the current enum permits.

If `WorkerFailureKind` lacks categories needed to avoid lying about the failure source, extend it rather than forcing unrelated failures into `Protocol`.

### 13.2 Required R8 tests

Table-driven tests must exercise representative errors from every meaningful category and assert the resulting failure kind. Include the connected-message path that motivated this finding.

## 14. Cross-cutting regression and fallback audit

Before final sign-off, inspect all changed files and adjacent failure paths for silent fallbacks.

At minimum review occurrences of:

- `let _ =`;
- `.ok()`;
- `unwrap_or`, `unwrap_or_else`, `unwrap_or_default`;
- broad error remapping;
- `|| true`;
- ignored process exit codes;
- broad Python exception catches;
- timeout paths that abandon background work;
- retry loops that can duplicate side effects;
- fallback-to-old-cache behavior.

Do not mechanically remove legitimate cleanup patterns. For every correctness-sensitive ignored/fallback result, either remove it or document the invariant that makes it safe and cover that invariant with a test where practical.

## 15. Documentation and compatibility requirements

Update all affected living documentation and examples, including as applicable:

- root `README.md`;
- operator/deployment documentation;
- HTTP/API contract documentation;
- Python client documentation/examples;
- environment-variable/configuration documentation;
- security/failure-semantics documentation.

The documentation must explain:

- command timeout means unknown outcome after acceptance, not known non-execution;
- callers must inspect command status rather than blindly retrying mutations;
- command-status retention is bounded;
- inbound clipboard state can become unavailable rather than silently stale;
- native timeout granularity/maximums;
- WebSocket inbound protocol restrictions;
- abnormal worker-shutdown semantics.

## 16. Quality gates

Run the repository's normal local checks before pushing implementation changes. At minimum:

```bash
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app python
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Run the repository's shell syntax/ShellCheck set and Docker/Compose checks for all touched shell/deployment files.

The final exact SHA must pass both regular CI and Release Gates. No gate may be weakened to achieve green status.

`SECURITY.md` currently records CRITICAL VEX determinations expiring on 2026-09-04. If final validation occurs on or after that date, renew/re-review the determinations according to the repository's existing policy rather than bypassing the gate.

## 17. Evidence requirements

Create:

`docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

The evidence document must include:

- starting SHA and final SHA;
- final regular CI run ID/conclusion;
- final Release Gates run ID/conclusion;
- implementation summary for R1-R8;
- exact regression test names added for each finding;
- command timeout/status API semantics;
- command registry bound/retention policy;
- pointer-state uncertainty policy;
- clipboard callback failure propagation policy;
- timeout granularity/range policy;
- WebSocket inbound limits and allowed frame types;
- XFCE readiness verification behavior;
- worker detach/shutdown outcome policy;
- failure classification mapping summary;
- fallback/silent-failure audit results;
- statement that no side-effecting command is automatically retried after unknown outcome;
- statement that no release-critical gate was disabled, weakened, or made non-blocking;
- deliberate deferrals, if any.

## 18. Completion criteria

This remediation pass is complete only when all of the following are true:

- R1-R8 are implemented or an item has a documented, evidence-backed design decision that fully resolves the stated risk;
- accepted command timeouts preserve command identity and expose unknown/retry-unsafe semantics;
- callers can inspect eventual command status without sensitive payload exposure;
- scroll double-release failure can no longer leave silently untracked pointer state;
- inbound clipboard callback errors cannot be silently converted into a stale-current clipboard view;
- duration configuration fails early when it cannot be represented safely;
- WebSocket inbound messages are explicitly bounded and application Text/Binary input is rejected;
- XFCE startup cannot proceed without proving `SaveOnExit=false`;
- worker shutdown timeout/detach is explicitly abnormal and never presented as confirmed termination;
- failure kinds accurately reflect representative underlying errors;
- changed/adjacent fallback paths have been audited;
- relevant docs and Python contracts are updated;
- all local quality gates available in the development environment pass;
- regular CI passes on the exact final SHA;
- Release Gates passes on the exact final SHA;
- the evidence document is complete;
- the companion TODO is fully checked with evidence references.

Only after this pass is complete should the project begin the separate MCP-server design/implementation phase.
