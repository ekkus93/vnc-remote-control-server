# VNC Remote Control Server — Code Review Remediation TODO

Date: 2026-08-31
Branch: `master`
Starting reviewed SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`
Planned evidence: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

## Completion contract

This TODO implements the 2026-08-31 code-review remediation specification. It is complete only when every applicable checkbox below is satisfied, the final evidence document is written, and the exact final SHA passes both regular CI and Release Gates without weakening any gate.

MCP implementation is **out of scope** for this TODO. The MCP phase begins only after this remediation pass is complete because the current command-timeout semantics are unsafe for an autonomous mutation client.

Final implementation validation completed on 2026-09-01:

- implementation `master` SHA: `1cb79d34f0023fc5da429ff3b60c71085224fa4e`;
- regular CI run `33516207959`: **success**;
- Release Gates run `33516208137`: **success**.

The later documentation-only closeout commit records this already-complete validation and is not substituted for the implementation SHA above.

## R0 — Freeze the reviewed baseline and preserve safety constraints

- [x] Record starting `master` SHA `62fd4cd6c15ea705227fe943eddbaaca26fe4345` in the final evidence document.
- [x] Record baseline regular CI run `31265957251` as passing.
- [x] Record baseline Release Gates run `31265957258` as passing.
- [x] Re-read the companion spec before implementation and keep R1-R8 scope separate from MCP work.
- [x] Preserve raw VNC isolation on the internal Compose network.
- [x] Preserve bearer authentication on `/v1/*`.
- [x] Preserve secret-file based credentials and secret/payload redaction.
- [x] Preserve bounded worker/event channels and bounded screenshot concurrency.
- [x] Preserve existing fail-closed sequence-exhaustion/native-size policies.
- [x] Do not add automatic retries for side-effecting commands with uncertain outcomes.
- [x] Do not add `continue-on-error`, broad scanner allowlists, or other release-gate bypasses.

## R1 — Fix indeterminate command timeout semantics

### R1.1 — Map the current command lifecycle

- [x] Trace command ID allocation, `WorkerClient::submit`, `CommandTicket`, worker dequeue/execution, completion send, `WorkerHttpBackend::execute_command`, HTTP handlers, and Python client behavior.
- [x] Document which failures happen before command admission and which can happen after admission.
- [x] Confirm the exact current response status/body for successful mutations, queue-full, worker-disconnected, command failure, and command timeout.
- [x] Identify every caller that could currently retry a timeout as though execution were known not to have happened.

### R1.2 — Allocate stable identity before admission

- [x] Ensure a command ID is allocated before the command can be accepted by the worker queue.
- [x] Preserve the same command ID through queueing, execution, completion, timeout, status lookup, diagnostics, and abnormal worker termination.
- [x] Keep command ID exhaustion fail-closed.
- [x] Add tests for ID continuity and exhaustion behavior.

### R1.3 — Add bounded command outcome tracking

- [x] Design a process-local command outcome/status registry keyed by command ID.
- [x] Define explicit lifecycle states covering pending/queued, optional running, succeeded, failed, and abnormal termination/aborted.
- [x] Define a strict maximum capacity and/or TTL.
- [x] Ensure retention is long enough for a timed-out caller to inspect a realistic eventual outcome.
- [x] Define deterministic eviction/expiry behavior.
- [x] Ensure outcome entries never retain typed text, clipboard values, bearer tokens, VNC credentials, screenshots, or other sensitive command payloads.
- [x] Mark accepted nonterminal commands abnormal/aborted if the worker terminates before normal completion.
- [x] Add unit tests for every lifecycle transition.
- [x] Add bounded-capacity/TTL tests.

### R1.4 — Add authenticated command-status inspection

- [x] Add a strict route such as `GET /v1/commands/{command_id}`.
- [x] Require the same bearer authentication policy as other `/v1/*` routes.
- [x] Return command ID plus lifecycle state and only sanitized diagnostic metadata.
- [x] Define unknown/expired command behavior explicitly.
- [x] Add route/schema tests for valid, unknown, expired, pending, succeeded, failed, and aborted records.
- [x] Add tests proving no command payload/secret is exposed.

### R1.5 — Return unknown outcome on post-admission timeout

- [x] Change timeout handling so a wait timeout after command acceptance returns the command ID.
- [x] Return explicit `outcome: unknown` semantics.
- [x] Return explicit `retry_safe: false` semantics.
- [x] Do not describe this condition as known command failure/non-execution.
- [x] Preserve known pre-admission queue-full/disconnected failures as distinct from unknown execution outcome.
- [x] Add a deterministic test where the HTTP/backend wait times out and the command subsequently succeeds.
- [x] Verify the status endpoint later reports that same command as succeeded.
- [x] Add a deterministic test where the timeout occurs and the worker later terminates abnormally.

### R1.6 — Correct successful mutation response semantics

- [x] Decide whether mutation endpoints are synchronous-to-terminal-result or genuinely asynchronous.
- [x] Preferred: keep current wait-for-result behavior and return a completion-oriented success status/body such as HTTP 200 rather than "accepted" wording.
- [x] If 202 is retained instead, make the endpoint genuinely asynchronous and document status polling; do not retain semantic mismatch.
- [x] Update every mutation handler consistently.
- [x] Update HTTP integration/E2E tests.

### R1.7 — Update Python client

- [x] Add strict parsing for command IDs and command status responses.
- [x] Add a command-status lookup method.
- [x] Represent timeout-after-acceptance with a distinct exception/result carrying command ID and `retry_safe=False` semantics.
- [x] Ensure the Python client never automatically retries such a mutation.
- [x] Add client tests for known failure vs unknown timeout vs eventual success/failure.
- [x] Ensure exception `repr`/messages contain no command payload or credential material.

### R1.8 — R1 acceptance tests

- [x] Known success before timeout.
- [x] Known command failure before timeout.
- [x] Validation failure before admission.
- [x] Queue full before admission.
- [x] Worker disconnected before admission.
- [x] Accepted command times out, then succeeds.
- [x] Accepted command times out, then fails.
- [x] Accepted command is aborted by worker termination.
- [x] Timed-out response and status record use identical command ID.
- [x] Timed-out mutation is explicitly non-retry-safe.
- [x] Registry remains bounded under sustained command volume.
- [x] No sensitive command data appears in status, events, metrics, or logs.

R0/R1 evidence and the exact test/CI references supporting these checks are recorded in `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`.

## R2 — Fix scroll-wheel release state uncertainty

### R2.1 — Remove the silent second-release fallback

- [x] Locate the scroll release/retry path in `crates/controller-api/src/input.rs`.
- [x] Remove the ignored `Result` from the second pointer-release attempt.
- [x] Introduce a typed error/state for unresolved remote pointer state or equivalent fail-closed representation.

### R2.2 — Define recovery after double release failure

- [x] Preserve the normal tracked button mask across the scroll operation.
- [x] If first release fails and retry succeeds, keep pointer state known and report the correct operation result.
- [x] If both release attempts fail, mark the current session/input state uncertain/tainted.
- [x] Do not execute subsequent input commands on that session as though pointer state were known.
- [x] Invalidate/reconnect the VNC session, or implement an equivalently safe fully tracked transient-mask policy.
- [x] Ensure recovery starts with clean tracked pointer/key state.
- [x] Emit sanitized diagnostics for the state-uncertainty transition.

### R2.3 — R2 regression tests

- [x] Wheel press + release success.
- [x] First release fails, retry succeeds.
- [x] First and second releases both fail.
- [x] Second failure is surfaced rather than ignored.
- [x] Double failure prevents further input on the tainted session.
- [x] Recovery/reconnect restores known clean state.
- [x] Existing ordinary button tracking/release tests still pass.
- [x] Existing key tracking/release tests still pass.

R2 evidence, recovery policy, regression test names, and exact implementation-head validation are recorded in `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`. Final exact-`master` validation is recorded in the R13-R15 closeout below.

## R3 — Propagate native clipboard callback failures

### R3.1 — Make callback failure machine-readable

- [x] Inspect `vrc_store_clipboard`, `GotXCutText`, `HandleRFBServerMessage`, and `vrc_client_poll` in `crates/libvnc-adapter/native/vnc_shim.c`.
- [x] Add explicit per-client callback failure state/status rather than relying only on an error string.
- [x] Clear callback error state before processing the next server message in a deterministic place.
- [x] Make `vrc_client_poll()` return non-success when a callback failed even if LibVNCClient's message handler itself returned success.
- [x] Ensure stale callback error state cannot poison later successful polls.

### R3.2 — Preserve useful failure classes

- [x] Distinguish oversize clipboard rejection from allocation/resource failure.
- [x] Distinguish invalid native/update state where possible.
- [x] Treat revision/counter exhaustion as an explicit fail-closed condition.
- [x] Map new native statuses into typed Rust errors without collapsing them into generic success/protocol behavior.

### R3.3 — Never serve a stale old clipboard as current

- [x] Add controller-side representation for clipboard unavailable/stale if the chosen recovery policy keeps the VNC session alive.
- [x] Invalidate the previously cached clipboard snapshot when a newer inbound update was rejected.
- [x] Ensure clipboard GET/read APIs do not return the previous value as current after rejection.
- [x] For allocation/native invariant failures, invalidate/reconnect or mark fatal according to the documented policy.
- [x] Ensure recovery after a later valid update or reconnect is explicit.

### R3.4 — Clipboard observability and secrecy

- [x] Add structured event/metric/log metadata for callback rejection category.
- [x] Include only safe metadata such as category and byte count where useful.
- [x] Never log clipboard payload contents.

### R3.5 — R3 tests

- [x] Valid inbound clipboard update.
- [x] Oversize inbound clipboard update.
- [x] Allocation failure path using a deterministic test hook/helper if needed.
- [x] Invalid/revision failure helper path.
- [x] Callback error causes `vrc_client_poll()` non-success or explicit clipboard-unavailable signaling.
- [x] Previous clipboard is not served as current after failed newer update.
- [x] Subsequent valid update/reconnect recovers correctly.
- [x] C sanitizer/native tests remain clean.

R3 evidence, callback failure classes, stale-cache invalidation/reconnect policy, deterministic poll-propagation tests, secrecy constraints, and exact implementation-head CI/Release Gates are recorded in `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`. The controller-side unavailable/stale representation item is satisfied by the chosen fail-closed policy: callback failure drops the affected session and clears the cached snapshot rather than keeping the session alive. Final exact-`master` validation is recorded in the R13-R15 closeout below.

## R4 — Align duration configuration with native/runtime constraints

### R4.1 — Inventory all duration conversions

- [x] List every externally configured duration and its final representation.
- [x] Identify native whole-second fields.
- [x] Identify `u32` microsecond conversions used by poll.
- [x] Identify `Instant` deadline arithmetic and any other narrowing conversions.

### R4.2 — Add centralized startup validation

- [x] Validate all representability constraints before spawning the worker/native client.
- [x] Use checked conversions instead of narrowing `as` casts.
- [x] Define explicit minimums and maximums.
- [x] Return configuration-specific errors for invalid values.

### R4.3 — Define millisecond/granularity contract

- [x] Decide whether to extend the shim for true millisecond connect/read timeout semantics.
- [x] If whole-second native semantics remain, require positive multiples of 1000 ms at config validation time.
- [x] Reject 1500 ms or other non-representable values explicitly; do not floor/ceil/round.
- [x] Document the rule next to the environment variables and operator guidance.

### R4.4 — R4 tests

- [x] Zero value.
- [x] Minimum valid value.
- [x] Non-representable fractional-second value if applicable.
- [x] Representative valid values.
- [x] Maximum valid value.
- [x] One above maximum.
- [x] Poll `u32` microsecond boundary.
- [x] Invalid configuration fails before worker/native startup.
- [x] No duration conversion panic/overflow.

## R5 — Harden WebSocket event-stream inbound traffic

### R5.1 — Set explicit inbound bounds

- [x] Configure a small maximum WebSocket message size.
- [x] Configure a small maximum WebSocket frame size.
- [x] Document the chosen values and rationale.
- [x] Confirm the bounds comfortably permit required Ping/Pong/Close control frames.

### R5.2 — Reject application Text/Binary messages

- [x] Treat the event endpoint as server-to-client application data.
- [x] Reject inbound Text frames with an explicit protocol close/error.
- [x] Reject inbound Binary frames with an explicit protocol close/error.
- [x] Do not count rejected application payloads as legitimate heartbeat activity.
- [x] Preserve Ping/Pong/Close behavior.

### R5.3 — R5 tests

- [x] Normal authenticated event subscription/delivery.
- [x] Ping/Pong liveness behavior.
- [x] Orderly Close.
- [x] Text rejection.
- [x] Binary rejection.
- [x] Oversized frame/message rejection.
- [x] Connection/client-count cleanup after rejection.
- [x] Authentication behavior unchanged.

## R6 — Make XFCE startup fail closed

### R6.1 — Replace silent `SaveOnExit` handling

- [x] Remove correctness-sensitive `xfconf-query ... || true` behavior from `desktop/xstartup`.
- [x] Keep retry behavior bounded and explicit to handle xfconf readiness races.
- [x] Check that XFCE remains alive while waiting.
- [x] Set `/general/SaveOnExit` to `false`.
- [x] Read it back and verify the final value is exactly false.
- [x] Proceed to the test application only after successful verification.
- [x] Exit nonzero if the property cannot be set/read/verified within the bound.
- [x] Preserve legitimate idempotent cleanup `kill`/`wait` race handling where justified.

### R6.2 — R6 tests

- [x] Immediate success.
- [x] Delayed xfconf availability.
- [x] Setter permanently fails.
- [x] Getter/property never becomes available.
- [x] Wrong final property value.
- [x] XFCE exits while waiting.
- [x] `bash -n` passes.
- [x] ShellCheck passes.
- [x] Secured desktop smoke/E2E remains green.

## R7 — Tighten worker shutdown/detach lifecycle semantics

### R7.1 — Audit current detach paths

- [x] Trace `DesktopWorker::shutdown`, `Drop`, startup-timeout cleanup, worker join timeout, and process shutdown.
- [x] Record every place a `JoinHandle` can be dropped while the thread may still run.
- [x] Confirm none of those paths currently claim confirmed orderly termination incorrectly.

### R7.2 — Make abnormal outcome explicit

- [x] Add/retain an explicit timeout/detached shutdown outcome that cannot be confused with `Stopped` orderly shutdown.
- [x] Ensure timeout returns within the caller bound.
- [x] Ensure `Drop` remains bounded and never performs an unbounded join.
- [x] Log/metric abnormal detach exactly once where practical, without secrets.
- [x] Prevent later normal use of a worker owner after shutdown has entered an abnormal terminal lifecycle state.

### R7.3 — Reduce normal likelihood of detach

- [x] Verify native poll/read/connect waits are bounded tightly enough for the out-of-band shutdown flag to be observed within the documented shutdown budget.
- [x] Where feasible, make lifecycle waits interruptible or use shorter bounded poll intervals without introducing busy loops.
- [x] Do not use unsafe thread termination.
- [x] Do not redesign into a child-process worker in this pass unless evidence proves it necessary.

### R7.4 — R7 tests

- [x] Orderly shutdown joins and reports `Stopped`.
- [x] Saturated command queue cannot block shutdown initiation.
- [x] Deliberately slow/stuck worker returns timeout within bound.
- [x] Timeout does not claim thread termination.
- [x] Drop after timeout remains bounded.
- [x] Process shutdown remains bounded.
- [x] Diagnostics distinguish clean stop from timeout/detach.

## R8 — Centralize and correct worker failure classification

### R8.1 — Define authoritative mapping

- [x] Inventory `DesktopError` variants and current `WorkerFailureKind` variants.
- [x] Identify every call site that assigns a failure kind manually.
- [x] Add one authoritative conversion/helper for mapping errors to failure kinds.
- [x] Extend `WorkerFailureKind` if necessary rather than mislabeling unrelated failures as `Protocol`.
- [x] Use the mapping in connected-message processing and other relevant worker paths.

### R8.2 — R8 tests

- [x] Add table-driven mapping tests for each representative error family.
- [x] Include native/resource errors.
- [x] Include transport errors.
- [x] Include authentication errors.
- [x] Include protocol errors.
- [x] Include input/state errors.
- [x] Include clipboard/framebuffer-related errors as applicable.
- [x] Include the `LoopState::poll()` connected-message path that motivated the finding.
- [x] Confirm metrics/events now carry the corrected category.

## R9 — Cross-cutting silent-failure and fallback audit

### R9.1 — Audit changed and adjacent code

- [x] Search changed/adjacent Rust code for `let _ =`.
- [x] Search for `.ok()` that discards operational errors.
- [x] Review `unwrap_or`, `unwrap_or_else`, and `unwrap_or_default` used as runtime fallbacks.
- [x] Review broad error remapping that loses type/cause information.
- [x] Search shell code for `|| true` and ignored exit statuses.
- [x] Review Python broad exception handlers.
- [x] Review timeout paths that abandon work while reporting known failure.
- [x] Review retries around side-effecting remote operations.
- [x] Review cache fallback paths that can serve stale state as current.

### R9.2 — Classify every relevant fallback

- [x] Remove unjustified silent fallbacks.
- [x] Add explicit error propagation for correctness-sensitive failures.
- [x] For legitimate cleanup races/abandoned completion receivers, document the invariant that makes ignoring the result safe.
- [x] Add tests for non-obvious justified fallbacks where practical.
- [x] Record the audit summary in the final evidence document.

## R10 — Update API/client/operator documentation

- [x] Update API docs for command lifecycle/status.
- [x] Document timeout-after-acceptance as unknown outcome and `retry_safe=false`.
- [x] Document that callers must inspect command status rather than blindly retry mutations.
- [x] Document bounded status-record retention/expiry.
- [x] Update Python client examples for timeout/status handling.
- [x] Document clipboard unavailable/stale behavior after rejected inbound updates.
- [x] Document timeout units, granularity, minimums, and maximums.
- [x] Document WebSocket inbound frame/message restrictions.
- [x] Document abnormal worker shutdown/detach semantics.
- [x] Update `README.md`, operator guide, deployment docs, or other living docs wherever the affected behavior is currently described.
- [x] Ensure docs do not imply the MCP server already exists.

## R11 — Run local quality gates

- [x] `cargo fmt --all --check`
- [x] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [x] `cargo test --locked --workspace --all-features`
- [x] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`
- [x] `python -m compileall -q tools/ci_status tests desktop/test-app python`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- [x] Run the repository's full `bash -n` shell-script set.
- [x] Run ShellCheck on all repository shell scripts used by CI/Release Gates.
- [x] Run `actionlint` if available locally.
- [x] Run `cargo deny check` if available locally.
- [x] Run Dockerfile build checks for desktop and controller.
- [x] Run Compose config validation.
- [x] Run relevant desktop/native/worker/HTTP/Compose/integration E2E locally where the environment supports them.
- [x] Do not weaken a check simply because it is inconvenient locally; defer final environment-specific proof to GitHub Actions where necessary.

R11 closeout note: the ChatGPT sandbox did not provide the complete pinned Rust/lint/container environment. The exact commands and environment-specific checks above were therefore proven by the repository's blocking GitHub Actions jobs rather than weakened or skipped: final implementation CI `33516207959` and Release Gates `33516208137` both succeeded. Focused Python/OpenAPI contract checks were also exercised locally during remediation.

## R12 — Security/VEX timing check

- [x] Before final Release Gates validation, inspect `SECURITY.md` VEX expiration dates.
- [x] If final validation is on or after 2026-09-04, perform the required CRITICAL VEX re-review/renewal according to existing repository policy.
- [x] Do not bypass or loosen exact VEX validation to get a green release run.

R12 closeout note: final implementation validation occurred on 2026-09-01, before the historical 2026-09-04 trigger. In addition, `SECURITY.md` and `security/trivy-critical-vex.json` had already been re-reviewed on 2026-08-31 with expiration extended to 2026-09-30, and exact CRITICAL VEX enforcement passed Release Gates `33516208137`.

## R13 — Final exact-SHA CI and Release Gates

- [x] Push the completed remediation implementation to `master` according to the project's normal workflow.
- [x] Record the exact final SHA.
- [x] Confirm regular CI is associated with that exact SHA.
- [x] Confirm regular CI conclusion is success.
- [x] Record regular CI run ID.
- [x] Confirm Release Gates is associated with that exact SHA.
- [x] Confirm Release Gates conclusion is success.
- [x] Record Release Gates run ID.
- [x] Confirm release-critical jobs remain blocking and contain no new `continue-on-error`/equivalent bypass.
- [x] Confirm full-history secret scanning remains enabled.
- [x] Confirm native sanitizer/Miri, dependency, image, SBOM/vulnerability, and exact VEX gates remain enabled.

## R14 — Write remediation evidence

Create:

`docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

- [x] Record starting SHA.
- [x] Record final SHA.
- [x] Record final regular CI run ID/conclusion.
- [x] Record final Release Gates run ID/conclusion.
- [x] Summarize R1 command lifecycle/status implementation.
- [x] Record command timeout body semantics and retry-safety policy.
- [x] Record command outcome registry capacity/TTL policy.
- [x] List R1 regression test names.
- [x] Summarize R2 pointer uncertainty/recovery policy.
- [x] List R2 regression test names.
- [x] Summarize R3 clipboard callback propagation/recovery policy.
- [x] List R3 native/Rust tests.
- [x] Summarize R4 duration granularity/range policy.
- [x] List R4 boundary tests.
- [x] Record R5 WebSocket inbound limits and rejected frame types.
- [x] List R5 tests.
- [x] Summarize R6 XFCE fail-closed readiness behavior.
- [x] List R6 tests.
- [x] Summarize R7 orderly vs timeout/detached shutdown semantics.
- [x] List R7 tests.
- [x] Summarize R8 authoritative failure mapping.
- [x] List R8 tests.
- [x] Record R9 silent-fallback audit results and rationale for any intentionally ignored results left in place.
- [x] State explicitly that no side-effecting command is automatically retried after an unknown outcome.
- [x] State explicitly that no secret/payload logging was added.
- [x] State explicitly that no release-critical gate was weakened.
- [x] Record any deliberate deferrals with issue/reference and safety rationale.

## R15 — Update this TODO and sign off

- [x] Re-review every R0-R14 checkbox against the actual final code/evidence rather than assuming implementation from commit messages.
- [x] Mark completed boxes only when supported by code/tests/evidence.
- [x] Leave any incomplete item unchecked and explain the blocker/deferral.
- [x] Do not declare the remediation complete until exact-SHA regular CI and Release Gates are both green.

Use this sign-off only when R0-R15 are genuinely complete:

```text
2026-08-31 code-review remediation complete on implementation SHA 1cb79d34f0023fc5da429ff3b60c71085224fa4e.
Final implementation validation completed 2026-09-01.
Regular CI run 33516207959: success.
Release Gates run 33516208137: success.
Accepted command timeouts preserve command identity and report unknown, non-retry-safe outcomes.
Scroll and clipboard failure paths no longer silently preserve uncertain/stale authoritative state.
Configuration, WebSocket, XFCE startup, worker shutdown, and failure classification hardening are complete.
The changed/adjacent silent-fallback audit is complete.
No release-critical gate was weakened.
MCP implementation remains a separate next phase.
```

If any requirement is deliberately deferred, replace the completion statement with a partial-completion statement that names the exact remaining item and tracked reference.
