# VNC Remote Control Server — Code Review Remediation TODO

Date: 2026-08-31
Branch: `master`
Starting reviewed SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`
Planned evidence: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

## Completion contract

This TODO implements the 2026-08-31 code-review remediation specification. It is complete only when every applicable checkbox below is satisfied, the final evidence document is written, and the exact final SHA passes both regular CI and Release Gates without weakening any gate.

MCP implementation is **out of scope** for this TODO. The MCP phase begins only after this remediation pass is complete because the current command-timeout semantics are unsafe for an autonomous mutation client.

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

R2 evidence, recovery policy, regression test names, and exact implementation-head validation are recorded in `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`. R3-R15 remain intentionally open; this is not overall remediation sign-off.

## R3 — Propagate native clipboard callback failures

### R3.1 — Make callback failure machine-readable

- [ ] Inspect `vrc_store_clipboard`, `GotXCutText`, `HandleRFBServerMessage`, and `vrc_client_poll` in `crates/libvnc-adapter/native/vnc_shim.c`.
- [ ] Add explicit per-client callback failure state/status rather than relying only on an error string.
- [ ] Clear callback error state before processing the next server message in a deterministic place.
- [ ] Make `vrc_client_poll()` return non-success when a callback failed even if LibVNCClient's message handler itself returned success.
- [ ] Ensure stale callback error state cannot poison later successful polls.

### R3.2 — Preserve useful failure classes

- [ ] Distinguish oversize clipboard rejection from allocation/resource failure.
- [ ] Distinguish invalid native/update state where possible.
- [ ] Treat revision/counter exhaustion as an explicit fail-closed condition.
- [ ] Map new native statuses into typed Rust errors without collapsing them into generic success/protocol behavior.

### R3.3 — Never serve a stale old clipboard as current

- [ ] Add controller-side representation for clipboard unavailable/stale if the chosen recovery policy keeps the VNC session alive.
- [ ] Invalidate the previously cached clipboard snapshot when a newer inbound update was rejected.
- [ ] Ensure clipboard GET/read APIs do not return the previous value as current after rejection.
- [ ] For allocation/native invariant failures, invalidate/reconnect or mark fatal according to the documented policy.
- [ ] Ensure recovery after a later valid update or reconnect is explicit.

### R3.4 — Clipboard observability and secrecy

- [ ] Add structured event/metric/log metadata for callback rejection category.
- [ ] Include only safe metadata such as category and byte count where useful.
- [ ] Never log clipboard payload contents.

### R3.5 — R3 tests

- [ ] Valid inbound clipboard update.
- [ ] Oversize inbound clipboard update.
- [ ] Allocation failure path using a deterministic test hook/helper if needed.
- [ ] Invalid/revision failure helper path.
- [ ] Callback error causes `vrc_client_poll()` non-success or explicit clipboard-unavailable signaling.
- [ ] Previous clipboard is not served as current after failed newer update.
- [ ] Subsequent valid update/reconnect recovers correctly.
- [ ] C sanitizer/native tests remain clean.

## R4 — Align duration configuration with native/runtime constraints

### R4.1 — Inventory all duration conversions

- [ ] List every externally configured duration and its final representation.
- [ ] Identify native whole-second fields.
- [ ] Identify `u32` microsecond conversions used by poll.
- [ ] Identify `Instant` deadline arithmetic and any other narrowing conversions.

### R4.2 — Add centralized startup validation

- [ ] Validate all representability constraints before spawning the worker/native client.
- [ ] Use checked conversions instead of narrowing `as` casts.
- [ ] Define explicit minimums and maximums.
- [ ] Return configuration-specific errors for invalid values.

### R4.3 — Define millisecond/granularity contract

- [ ] Decide whether to extend the shim for true millisecond connect/read timeout semantics.
- [ ] If whole-second native semantics remain, require positive multiples of 1000 ms at config validation time.
- [ ] Reject 1500 ms or other non-representable values explicitly; do not floor/ceil/round.
- [ ] Document the rule next to the environment variables and operator guidance.

### R4.4 — R4 tests

- [ ] Zero value.
- [ ] Minimum valid value.
- [ ] Non-representable fractional-second value if applicable.
- [ ] Representative valid values.
- [ ] Maximum valid value.
- [ ] One above maximum.
- [ ] Poll `u32` microsecond boundary.
- [ ] Invalid configuration fails before worker/native startup.
- [ ] No duration conversion panic/overflow.

## R5 — Harden WebSocket event-stream inbound traffic

### R5.1 — Set explicit inbound bounds

- [ ] Configure a small maximum WebSocket message size.
- [ ] Configure a small maximum WebSocket frame size.
- [ ] Document the chosen values and rationale.
- [ ] Confirm the bounds comfortably permit required Ping/Pong/Close control frames.

### R5.2 — Reject application Text/Binary messages

- [ ] Treat the event endpoint as server-to-client application data.
- [ ] Reject inbound Text frames with an explicit protocol close/error.
- [ ] Reject inbound Binary frames with an explicit protocol close/error.
- [ ] Do not count rejected application payloads as legitimate heartbeat activity.
- [ ] Preserve Ping/Pong/Close behavior.

### R5.3 — R5 tests

- [ ] Normal authenticated event subscription/delivery.
- [ ] Ping/Pong liveness behavior.
- [ ] Orderly Close.
- [ ] Text rejection.
- [ ] Binary rejection.
- [ ] Oversized frame/message rejection.
- [ ] Connection/client-count cleanup after rejection.
- [ ] Authentication behavior unchanged.

## R6 — Make XFCE startup fail closed

### R6.1 — Replace silent `SaveOnExit` handling

- [ ] Remove correctness-sensitive `xfconf-query ... || true` behavior from `desktop/xstartup`.
- [ ] Keep retry behavior bounded and explicit to handle xfconf readiness races.
- [ ] Check that XFCE remains alive while waiting.
- [ ] Set `/general/SaveOnExit` to `false`.
- [ ] Read it back and verify the final value is exactly false.
- [ ] Proceed to the test application only after successful verification.
- [ ] Exit nonzero if the property cannot be set/read/verified within the bound.
- [ ] Preserve legitimate idempotent cleanup `kill`/`wait` race handling where justified.

### R6.2 — R6 tests

- [ ] Immediate success.
- [ ] Delayed xfconf availability.
- [ ] Setter permanently fails.
- [ ] Getter/property never becomes available.
- [ ] Wrong final property value.
- [ ] XFCE exits while waiting.
- [ ] `bash -n` passes.
- [ ] ShellCheck passes.
- [ ] Secured desktop smoke/E2E remains green.

## R7 — Tighten worker shutdown/detach lifecycle semantics

### R7.1 — Audit current detach paths

- [ ] Trace `DesktopWorker::shutdown`, `Drop`, startup-timeout cleanup, worker join timeout, and process shutdown.
- [ ] Record every place a `JoinHandle` can be dropped while the thread may still run.
- [ ] Confirm none of those paths currently claim confirmed orderly termination incorrectly.

### R7.2 — Make abnormal outcome explicit

- [ ] Add/retain an explicit timeout/detached shutdown outcome that cannot be confused with `Stopped` orderly shutdown.
- [ ] Ensure timeout returns within the caller bound.
- [ ] Ensure `Drop` remains bounded and never performs an unbounded join.
- [ ] Log/metric abnormal detach exactly once where practical, without secrets.
- [ ] Prevent later normal use of a worker owner after shutdown has entered an abnormal terminal lifecycle state.

### R7.3 — Reduce normal likelihood of detach

- [ ] Verify native poll/read/connect waits are bounded tightly enough for the out-of-band shutdown flag to be observed within the documented shutdown budget.
- [ ] Where feasible, make lifecycle waits interruptible or use shorter bounded poll intervals without introducing busy loops.
- [ ] Do not use unsafe thread termination.
- [ ] Do not redesign into a child-process worker in this pass unless evidence proves it necessary.

### R7.4 — R7 tests

- [ ] Orderly shutdown joins and reports `Stopped`.
- [ ] Saturated command queue cannot block shutdown initiation.
- [ ] Deliberately slow/stuck worker returns timeout within bound.
- [ ] Timeout does not claim thread termination.
- [ ] Drop after timeout remains bounded.
- [ ] Process shutdown remains bounded.
- [ ] Diagnostics distinguish clean stop from timeout/detach.

## R8 — Centralize and correct worker failure classification

### R8.1 — Define authoritative mapping

- [ ] Inventory `DesktopError` variants and current `WorkerFailureKind` variants.
- [ ] Identify every call site that assigns a failure kind manually.
- [ ] Add one authoritative conversion/helper for mapping errors to failure kinds.
- [ ] Extend `WorkerFailureKind` if necessary rather than mislabeling unrelated failures as `Protocol`.
- [ ] Use the mapping in connected-message processing and other relevant worker paths.

### R8.2 — R8 tests

- [ ] Add table-driven mapping tests for each representative error family.
- [ ] Include native/resource errors.
- [ ] Include transport errors.
- [ ] Include authentication errors.
- [ ] Include protocol errors.
- [ ] Include input/state errors.
- [ ] Include clipboard/framebuffer-related errors as applicable.
- [ ] Include the `LoopState::poll()` connected-message path that motivated the finding.
- [ ] Confirm metrics/events now carry the corrected category.

## R9 — Cross-cutting silent-failure and fallback audit

### R9.1 — Audit changed and adjacent code

- [ ] Search changed/adjacent Rust code for `let _ =`.
- [ ] Search for `.ok()` that discards operational errors.
- [ ] Review `unwrap_or`, `unwrap_or_else`, and `unwrap_or_default` used as runtime fallbacks.
- [ ] Review broad error remapping that loses type/cause information.
- [ ] Search shell code for `|| true` and ignored exit statuses.
- [ ] Review Python broad exception handlers.
- [ ] Review timeout paths that abandon work while reporting known failure.
- [ ] Review retries around side-effecting remote operations.
- [ ] Review cache fallback paths that can serve stale state as current.

### R9.2 — Classify every relevant fallback

- [ ] Remove unjustified silent fallbacks.
- [ ] Add explicit error propagation for correctness-sensitive failures.
- [ ] For legitimate cleanup races/abandoned completion receivers, document the invariant that makes ignoring the result safe.
- [ ] Add tests for non-obvious justified fallbacks where practical.
- [ ] Record the audit summary in the final evidence document.

## R10 — Update API/client/operator documentation

- [ ] Update API docs for command lifecycle/status.
- [ ] Document timeout-after-acceptance as unknown outcome and `retry_safe=false`.
- [ ] Document that callers must inspect command status rather than blindly retry mutations.
- [ ] Document bounded status-record retention/expiry.
- [ ] Update Python client examples for timeout/status handling.
- [ ] Document clipboard unavailable/stale behavior after rejected inbound updates.
- [ ] Document timeout units, granularity, minimums, and maximums.
- [ ] Document WebSocket inbound frame/message restrictions.
- [ ] Document abnormal worker shutdown/detach semantics.
- [ ] Update `README.md`, operator guide, deployment docs, or other living docs wherever the affected behavior is currently described.
- [ ] Ensure docs do not imply the MCP server already exists.

## R11 — Run local quality gates

- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`
- [ ] `python -m compileall -q tools/ci_status tests desktop/test-app python`
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] Run the repository's full `bash -n` shell-script set.
- [ ] Run ShellCheck on all repository shell scripts used by CI/Release Gates.
- [ ] Run `actionlint` if available locally.
- [ ] Run `cargo deny check` if available locally.
- [ ] Run Dockerfile build checks for desktop and controller.
- [ ] Run Compose config validation.
- [ ] Run relevant desktop/native/worker/HTTP/Compose/integration E2E locally where the environment supports them.
- [ ] Do not weaken a check simply because it is inconvenient locally; defer final environment-specific proof to GitHub Actions where necessary.

## R12 — Security/VEX timing check

- [ ] Before final Release Gates validation, inspect `SECURITY.md` VEX expiration dates.
- [ ] If final validation is on or after 2026-09-04, perform the required CRITICAL VEX re-review/renewal according to existing repository policy.
- [ ] Do not bypass or loosen exact VEX validation to get a green release run.

## R13 — Final exact-SHA CI and Release Gates

- [ ] Push the completed remediation implementation to `master` according to the project's normal workflow.
- [ ] Record the exact final SHA.
- [ ] Confirm regular CI is associated with that exact SHA.
- [ ] Confirm regular CI conclusion is success.
- [ ] Record regular CI run ID.
- [ ] Confirm Release Gates is associated with that exact SHA.
- [ ] Confirm Release Gates conclusion is success.
- [ ] Record Release Gates run ID.
- [ ] Confirm release-critical jobs remain blocking and contain no new `continue-on-error`/equivalent bypass.
- [ ] Confirm full-history secret scanning remains enabled.
- [ ] Confirm native sanitizer/Miri, dependency, image, SBOM/vulnerability, and exact VEX gates remain enabled.

## R14 — Write remediation evidence

Create:

`docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

- [ ] Record starting SHA.
- [ ] Record final SHA.
- [ ] Record final regular CI run ID/conclusion.
- [ ] Record final Release Gates run ID/conclusion.
- [ ] Summarize R1 command lifecycle/status implementation.
- [ ] Record command timeout body semantics and retry-safety policy.
- [ ] Record command outcome registry capacity/TTL policy.
- [ ] List R1 regression test names.
- [ ] Summarize R2 pointer uncertainty/recovery policy.
- [ ] List R2 regression test names.
- [ ] Summarize R3 clipboard callback propagation/recovery policy.
- [ ] List R3 native/Rust tests.
- [ ] Summarize R4 duration granularity/range policy.
- [ ] List R4 boundary tests.
- [ ] Record R5 WebSocket inbound limits and rejected frame types.
- [ ] List R5 tests.
- [ ] Summarize R6 XFCE fail-closed readiness behavior.
- [ ] List R6 tests.
- [ ] Summarize R7 orderly vs timeout/detached shutdown semantics.
- [ ] List R7 tests.
- [ ] Summarize R8 authoritative failure mapping.
- [ ] List R8 tests.
- [ ] Record R9 silent-fallback audit results and rationale for any intentionally ignored results left in place.
- [ ] State explicitly that no side-effecting command is automatically retried after an unknown outcome.
- [ ] State explicitly that no secret/payload logging was added.
- [ ] State explicitly that no release-critical gate was weakened.
- [ ] Record any deliberate deferrals with issue/reference and safety rationale.

## R15 — Update this TODO and sign off

- [ ] Re-review every R0-R14 checkbox against the actual final code/evidence rather than assuming implementation from commit messages.
- [ ] Mark completed boxes only when supported by code/tests/evidence.
- [ ] Leave any incomplete item unchecked and explain the blocker/deferral.
- [ ] Do not declare the remediation complete until exact-SHA regular CI and Release Gates are both green.

Use this sign-off only when R0-R15 are genuinely complete:

```text
2026-08-31 code-review remediation complete on <FINAL_SHA>.
Regular CI run <CI_RUN_ID>: success.
Release Gates run <RELEASE_GATES_RUN_ID>: success.
Accepted command timeouts preserve command identity and report unknown, non-retry-safe outcomes.
Scroll and clipboard failure paths no longer silently preserve uncertain/stale authoritative state.
Configuration, WebSocket, XFCE startup, worker shutdown, and failure classification hardening are complete.
The changed/adjacent silent-fallback audit is complete.
No release-critical gate was weakened.
MCP implementation remains a separate next phase.
```

If any requirement is deliberately deferred, replace the completion statement with a partial-completion statement that names the exact remaining item and tracked reference.