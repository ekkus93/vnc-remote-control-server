# VNC Remote Control Server — Code Review Remediation TODO

Date: 2026-08-31
Branch target: `master`
Starting reviewed SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`

## Completion contract

This TODO tracks the remediation work defined by the companion spec. The pass is not complete merely because unit tests are green. Every correctness contract below must be implemented, regression-tested, documented where externally visible, and validated by regular CI and Release Gates on the exact final SHA.

Do not begin MCP server implementation until this TODO is complete. In particular, R1 command timeout/outcome semantics are a prerequisite for exposing mutation tools to an agent.

## P0 — Freeze reviewed baseline and protect scope

- [ ] Record starting `master` SHA `62fd4cd6c15ea705227fe943eddbaaca26fe4345` in final evidence.
- [ ] Confirm the remediation scope is limited to the reviewed findings plus tests/docs needed to prove them.
- [ ] Confirm MCP implementation is out of scope for this pass.
- [ ] Preserve existing security, input-validation, screenshot-coherence, resource-bound, and release-gate behavior unless a task below explicitly changes it.
- [ ] Establish final evidence file at `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md` before final sign-off.

## P1 — Fix indeterminate command timeout semantics

### P1-001 — Trace the current command lifecycle

- [ ] Document the current path from HTTP handler/backend to worker submission, `CommandTicket`, worker execution, completion channel, timeout mapping, and HTTP response.
- [ ] Identify exactly when a command ID is allocated.
- [ ] Identify which timeout cases prove non-execution and which leave execution outcome unknown.
- [ ] Confirm no existing cancellation mechanism can safely claim that timed-out work will not execute.

### P1-002 — Define command outcome state model

- [ ] Define explicit states sufficient to distinguish at least submitted/queued, executing if observable, succeeded, failed, and outcome unknown.
- [ ] Define the semantics of a wait/acknowledgement timeout after submission.
- [ ] Define whether completed command status is retained and for how long.
- [ ] Bound any status-history memory by count, time, or both.
- [ ] Define behavior when a status entry expires.
- [ ] Define `retry_safe` or an equivalent explicit mutation retry contract.
- [ ] Ensure mutation commands with ambiguous outcome are never represented as safely retryable.

### P1-003 — Implement backend/worker changes

- [ ] Preserve the command ID through acknowledgement timeout.
- [ ] Implement the chosen status/outcome representation.
- [ ] Do not falsely claim cancellation when the command may race execution.
- [ ] Ensure command completion updates the same identity exactly once.
- [ ] Ensure status bookkeeping remains correct if the original HTTP requester disconnects.
- [ ] Ensure status-history exhaustion/overflow fails closed or evicts according to an explicit bounded policy.

### P1-004 — Correct HTTP semantics

- [ ] Review whether existing `202 Accepted` wording/status still matches behavior.
- [ ] Separate submission acknowledgement from final execution outcome in the API contract.
- [ ] Return command ID in ambiguous timeout response/results.
- [ ] Return an explicit machine-readable unknown/indeterminate outcome.
- [ ] Return explicit mutation retry safety.
- [ ] Keep error responses structured and non-secret-bearing.
- [ ] Update OpenAPI/API docs if applicable.

### P1-005 — Update Python client

- [ ] Add/adjust strict response models for the new command outcome contract.
- [ ] Ensure unknown fields/types are handled according to existing strict-client policy.
- [ ] Ensure the client does not automatically retry an ambiguous mutation.
- [ ] Expose command ID and unknown outcome to caller code.
- [ ] Keep tokens and typed/clipboard payloads out of repr/logging/errors.

### P1-006 — Regression tests

- [ ] Test success before wait timeout.
- [ ] Test known failure before wait timeout.
- [ ] Test wait timeout followed by eventual success.
- [ ] Test wait timeout followed by eventual failure.
- [ ] Assert command ID is stable across timeout and later status.
- [ ] Assert ambiguous mutation reports retry unsafe.
- [ ] Assert no duplicate command is submitted by server/client timeout handling.
- [ ] Test bounded status retention/expiry if implemented.
- [ ] Test sequence/ID exhaustion remains fail closed.

## P2 — Fix scroll-wheel remote-state uncertainty

### P2-001 — Model pointer state explicitly

- [ ] Inspect current `scroll()`, pointer mask tracking, release paths, `release_all()`, and reconnect/session teardown behavior.
- [ ] Choose one policy:
  - [ ] track transient/uncertain pointer mask until release is confirmed; or
  - [ ] invalidate/reconnect the VNC session when pointer state becomes unknowable.
- [ ] Document why the chosen policy is correct for RFB wheel-button semantics.

### P2-002 — Remove ignored corrective-release failure

- [ ] Remove or replace the correctness-relevant ignored result from the second wheel release.
- [ ] If a corrective release succeeds, restore known-clean state.
- [ ] If corrective release also fails, transition to explicit uncertain/invalidation behavior.
- [ ] Do not continue accepting input as though pointer state is clean when it is not provable.
- [ ] Preserve existing tracked normal button behavior.

### P2-003 — Regression tests

- [ ] Successful scroll press/release.
- [ ] Initial release fails, corrective release succeeds.
- [ ] Initial and corrective release both fail.
- [ ] Further input is blocked or session-invalidated under unknown pointer state.
- [ ] Reconnect/reset establishes clean pointer state.
- [ ] Existing key and normal-button double-release tests still pass.

## P3 — Propagate native inbound clipboard callback failures

### P3-001 — Define native callback error channel

- [ ] Inspect `vrc_store_clipboard`, `GotXCutText` callback integration, `HandleRFBServerMessage`, `vrc_client_poll`, Rust `poll`, and `refresh_clipboard`.
- [ ] Define how callback failures are latched and consumed by the poll/Rust layer.
- [ ] Ensure one callback failure cannot be silently overwritten by a later nominal return before it is observed.
- [ ] Define reset behavior after the error is consumed or session reconnects.

### P3-002 — Implement failure propagation

- [ ] Oversized inbound clipboard produces explicit bounded-input failure/state staleness.
- [ ] Allocation failure produces explicit native/resource failure.
- [ ] Revision exhaustion fails closed and never wraps.
- [ ] Invalid callback input produces explicit failure.
- [ ] Rust does not report ordinary successful refresh while retaining an old authoritative clipboard after a rejected newer update.
- [ ] Decide whether each failure marks clipboard unavailable, invalidates the session, or forces reconnect; document the decision.
- [ ] Never log clipboard contents.

### P3-003 — Regression tests

- [ ] Native test for oversize callback payload.
- [ ] Native test/injection for allocation failure where feasible.
- [ ] Native test for revision exhaustion boundary.
- [ ] Native test for invalid callback input.
- [ ] Rust adapter/worker test proving failure crosses C/Rust boundary.
- [ ] Test old cached clipboard is not served as known-current after rejected update.
- [ ] Test recovery/reconnect clears stale/error state deterministically.

## P4 — Align timeout configuration with native limits

### P4-001 — Inventory duration conversions

- [ ] Inventory every externally configurable duration and every downstream conversion (`seconds`, `milliseconds`, `microseconds`, integer narrowing, deadline arithmetic).
- [ ] Record native/API type widths and granularity.
- [ ] Identify any accepted value that can fail only after startup.

### P4-002 — Decide and implement public unit contract

- [ ] Preserve millisecond semantics where the variable/documentation names promise milliseconds unless technically impossible.
- [ ] If a native operation can only accept whole seconds, validate that restriction at startup and document it explicitly.
- [ ] Prefer updating the shim to millisecond precision when practical.
- [ ] Centralize representability validation.
- [ ] Add explicit upper bounds before any `u32`/other narrowing.
- [ ] Add bounds that keep `Instant`/deadline arithmetic safe.
- [ ] Return configuration-specific startup errors naming the invalid key and constraint.

### P4-003 — Regression tests

- [ ] Zero value rejection where invalid.
- [ ] Minimum valid value.
- [ ] `1500ms` or equivalent fractional-second value behaves according to documented contract.
- [ ] Exact whole-second value.
- [ ] Maximum valid value.
- [ ] One-above-maximum rejected at startup.
- [ ] No startup-accepted value fails later solely due to native duration conversion.

## P5 — Harden `/v1/events` WebSocket inbound protocol

### P5-001 — Define inbound protocol and bounds

- [ ] Document that the endpoint is server-to-client for application data.
- [ ] Choose explicit small maximum frame size.
- [ ] Choose explicit small maximum message size.
- [ ] Preserve required Ping/Pong/Close control behavior.
- [ ] Define rejection/close behavior for inbound Text and Binary frames.

### P5-002 — Implement hardening

- [ ] Apply per-route WebSocket message/frame bounds.
- [ ] Reject Text frames.
- [ ] Reject Binary frames.
- [ ] Do not count rejected application messages as valid heartbeat/activity.
- [ ] Preserve event lag, shutdown, client-count, and heartbeat semantics.

### P5-003 — Regression tests

- [ ] Normal authenticated event stream.
- [ ] Ping/Pong.
- [ ] Close.
- [ ] Text rejection.
- [ ] Binary rejection.
- [ ] Oversized frame rejection.
- [ ] Oversized message rejection.
- [ ] Existing client-capacity and lag tests remain green.

## P6 — Make XFCE startup fail closed

### P6-001 — Remove silent SaveOnExit fallback

- [ ] Inspect `desktop/xstartup` SaveOnExit setter/wait logic.
- [ ] Remove correctness-critical `>/dev/null 2>&1 || true` behavior from the property setter.
- [ ] Permit bounded retry only while XFCE/xfconf is legitimately initializing.
- [ ] Preserve useful diagnostics without excessive noise.

### P6-002 — Prove readiness before launching test app

- [ ] After the bounded wait, explicitly query `/general/SaveOnExit`.
- [ ] Verify the property exists.
- [ ] Verify its value is false.
- [ ] Exit nonzero if verification fails or times out.
- [ ] Do not execute the test app on an unproven XFCE session.
- [ ] Leave cleanup-only `kill/wait ... || true` uses unchanged only where their idempotent race semantics are valid.

### P6-003 — Regression tests

- [ ] Property eventually becomes available and false.
- [ ] Setter permanently fails.
- [ ] Getter/property remains unavailable.
- [ ] Property returns wrong value.
- [ ] Startup does not silently proceed on any required-property failure.

## P7 — Tighten worker shutdown lifecycle semantics

### P7-001 — Document current ownership boundary

- [ ] Document that out-of-band shutdown request is independent of command queue capacity.
- [ ] Document current bounded wait/detach behavior.
- [ ] State explicitly that timeout means worker termination is unconfirmed, not confirmed stopped.
- [ ] Identify all code paths that detach a worker thread after timeout.

### P7-002 — Investigate interruptible native waits

- [ ] Determine whether LibVNCClient/native polling can be interrupted safely.
- [ ] Determine whether poll/read/connect wait granularity can be bounded sufficiently for reliable join.
- [ ] If safe, implement a wake/interruption mechanism and prefer confirmed worker termination.
- [ ] If not safe/practical, document the reason and retain bounded detach as an explicit process-level limitation.

### P7-003 — Correct status/reporting

- [ ] Never report `Stopped`/clean shutdown solely because the caller's wait expired.
- [ ] Record abnormal/unconfirmed termination distinctly.
- [ ] Preserve bounded main-process shutdown.
- [ ] Ensure logs do not contain input/clipboard/secret payloads.
- [ ] Ensure reusable APIs do not promise ownership stronger than implementation provides.

### P7-004 — Regression tests

- [ ] Orderly shutdown confirms worker joined.
- [ ] Forced/slow shutdown times out with termination unconfirmed.
- [ ] No false clean `Stopped` claim for a live/unknown worker.
- [ ] Process shutdown remains bounded.
- [ ] Startup-timeout cleanup follows equivalent semantics.

## P8 — Centralize worker failure classification

### P8-001 — Inventory mappings

- [ ] Find every conversion from native/desktop/session errors to `WorkerFailureKind` or API-visible failure categories.
- [ ] Identify broad/default-to-`Protocol` mappings.
- [ ] Define the authoritative mapping table.

### P8-002 — Implement one mapping

- [ ] Centralize conversion in one helper/trait/function.
- [ ] Apply it consistently to connection, polling, connected-message processing, command execution, framebuffer/clipboard work, and cleanup as applicable.
- [ ] Keep clean remote disconnect distinct from abnormal protocol/native failures.
- [ ] Avoid generic fallback classification when a specific lower-level category exists.

### P8-003 — Regression tests

- [ ] Transport/connectivity mapping.
- [ ] Protocol mapping.
- [ ] Native/resource mapping.
- [ ] Timeout mapping.
- [ ] Configuration/input mapping where applicable.
- [ ] Clean disconnect versus abnormal disconnect.
- [ ] Existing metrics/events continue to expose expected categories.

## P9 — Repository-wide dangerous fallback / silent failure audit

### P9-001 — Search candidate constructs

- [ ] Audit Rust for ignored `Result`s (`let _ =`), broad fallback helpers, `unwrap_or*`, broad wildcard fallback arms, and timeout-abandon paths.
- [ ] Audit C for discarded status/error state and callback failures.
- [ ] Audit Python for broad `except Exception`, fallback return values, implicit retries, and stale cache behavior.
- [ ] Audit shell for `|| true`, output suppression, and best-effort startup checks.
- [ ] Audit workflows for `continue-on-error`, `|| true`, conditional skips, or scanner allowlists that can weaken release enforcement.

### P9-002 — Classify every material occurrence

For each correctness-relevant candidate, mark it as one of:

- [ ] correctness-safe and justified;
- [ ] cleanup/idempotency-only and justified;
- [ ] deliberate compatibility fallback with explicit logging/metrics/tests;
- [ ] defect fixed during this pass.

Known occurrences that must be explicitly revisited:

- [ ] `let _ = shutdown_sender.send(true)` — confirm receiver-liveness rationale remains valid.
- [ ] ignored worker completion-channel sends — confirm requester-drop rationale remains valid.
- [ ] ignored event broadcast sends — confirm no-receiver semantics remain valid.
- [ ] screenshot timeout background encode — confirm permit is retained until actual encoder completion.
- [ ] poisoned mutex handling — confirm it remains fail closed rather than silently recovering.
- [ ] reconnect-delay conversion fallback — confirm unreachable/bounded rationale or simplify it.
- [ ] Python WebSocket broad exception conversion — confirm it always becomes explicit `TransportError` and does not hide success/failure.
- [ ] cleanup `kill/wait ... || true` — confirm idempotent cleanup rationale.
- [ ] XFCE SaveOnExit `|| true` — fix under P6.
- [ ] wheel corrective release ignored result — fix under P2.

### P9-003 — Add local rationale where needed

- [ ] Add concise comments only where an ignored error is non-obviously safe.
- [ ] Avoid comments that merely restate code.
- [ ] Add tests for any fallback whose safety depends on subtle invariants.

## P10 — Documentation and API consistency

- [ ] Update README if observable command semantics change.
- [ ] Update API/OpenAPI schema/docs for command timeout/status behavior.
- [ ] Update Python client docs/examples.
- [ ] Update operator guide for worker shutdown limitation if detachment remains.
- [ ] Update desktop/deployment docs if XFCE readiness behavior changes diagnostics/startup timing.
- [ ] Ensure no documentation tells clients to blindly retry a mutation after timeout.
- [ ] Document any intentionally retained fallback and its invariant when operator-relevant.

## P11 — Local validation

Run all applicable established local checks before final push. At minimum:

```bash
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash -n \
  desktop/entrypoint.sh \
  desktop/healthcheck.sh \
  desktop/xstartup \
  tests/desktop/run.sh \
  tests/native/run.sh \
  tests/worker-e2e/run.sh \
  tests/worker-text-clipboard-e2e/run.sh \
  tests/http-e2e/run.sh \
  controller/healthcheck.sh \
  tests/compose/run.sh \
  tests/integration/run.sh
```

Where installed/applicable:

```bash
shellcheck --severity=warning \
  desktop/entrypoint.sh \
  desktop/healthcheck.sh \
  desktop/xstartup \
  tests/desktop/run.sh \
  tests/native/run.sh \
  tests/worker-e2e/run.sh \
  tests/worker-text-clipboard-e2e/run.sh \
  tests/http-e2e/run.sh \
  controller/healthcheck.sh \
  tests/compose/run.sh \
  tests/integration/run.sh

actionlint .github/workflows/*.yml
cargo deny check

docker buildx build --check --file desktop/Dockerfile desktop
docker buildx build --check --file controller/Dockerfile .
```

- [ ] Record exact local commands and results in evidence.
- [ ] If a gate is unavailable locally, do not disable it; validate through the permanent CI/Release Gates workflow and say so in evidence.

## P12 — Integration/E2E validation

- [ ] Native adapter smoke passes.
- [ ] Worker TigerVNC input E2E passes.
- [ ] Text/clipboard TigerVNC E2E passes with new clipboard error semantics.
- [ ] Authenticated HTTP TigerVNC E2E passes with new command outcome semantics.
- [ ] Controller image/Compose/persistence smoke passes.
- [ ] Full Compose integration/E2E passes.
- [ ] Add an E2E scenario for ambiguous command timeout if deterministic injection is feasible.
- [ ] Add an E2E/container scenario for XFCE readiness failure if feasible.

## P13 — Exact-SHA CI and Release Gates

- [ ] Push implementation to `master` using normal repository workflow.
- [ ] Record final implementation SHA.
- [ ] Confirm regular CI runs against that exact SHA.
- [ ] Confirm regular CI conclusion is success.
- [ ] Confirm Release Gates runs against that exact SHA.
- [ ] Confirm Release Gates conclusion is success.
- [ ] Confirm no release-critical job was weakened with `continue-on-error` or equivalent bypass.
- [ ] Confirm full-history secret scanning remains enabled.
- [ ] Confirm dependency/license/VEX/image/native safety gates remain enabled.

## P14 — Final evidence and reconciliation

Create/update:

`docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_EVIDENCE_2026-08-31.md`

Evidence must include:

- [ ] starting reviewed SHA;
- [ ] final implementation SHA;
- [ ] implementation summary for P1-P8;
- [ ] exact tests added/changed per finding;
- [ ] dangerous-fallback audit summary and disposition of material occurrences;
- [ ] command timeout/outcome API contract after remediation;
- [ ] pointer-state uncertainty policy;
- [ ] clipboard callback failure policy;
- [ ] duration/config representability policy;
- [ ] WebSocket inbound bounds/protocol;
- [ ] XFCE readiness policy;
- [ ] worker detach/interruption decision and any remaining limitation;
- [ ] centralized worker failure mapping summary;
- [ ] local validation command results;
- [ ] final CI run ID/conclusion;
- [ ] final Release Gates run ID/conclusion;
- [ ] explicit confirmation no correctness-critical gate or failure path was converted to quiet success;
- [ ] any deliberate deferral, with a concrete issue/reference and reason.

Then:

- [ ] Reconcile every checkbox in this TODO against code/tests/evidence rather than commit-message claims.
- [ ] Leave genuinely incomplete items unchecked.
- [ ] Do not mark the pass complete because CI is green if a semantic requirement remains unmet.

## P15 — Completion gate before MCP work

The remediation pass is complete only after all of the following are true:

- [ ] P1 command timeout ambiguity is fixed and safe for agent consumption.
- [ ] P2 scroll release uncertainty is fail closed.
- [ ] P3 clipboard callback failures cannot silently preserve stale authoritative state.
- [ ] P4 configuration values are validated against native representability before runtime use.
- [ ] P5 WebSocket inbound protocol and bounds are explicit.
- [ ] P6 XFCE readiness no longer silently falls through.
- [ ] P7 shutdown timeout does not falsely imply thread termination.
- [ ] P8 worker error classification is authoritative and tested.
- [ ] P9 silent-fallback audit is complete.
- [ ] P10 documentation/client contracts are synchronized.
- [ ] P11/P12 validation is green.
- [ ] P13 exact-SHA CI and Release Gates are green.
- [ ] P14 evidence is committed and this TODO is reconciled.

Only then begin the MCP server specification/design pass.

Suggested completion sign-off:

```text
2026-08-31 code-review remediation complete on <FINAL_SHA>.
Regular CI <CI_RUN_ID>: success.
Release Gates <RELEASE_GATES_RUN_ID>: success.
Ambiguous mutation timeouts are no longer represented as safely retryable failures.
Remote input and clipboard uncertainty fail closed.
No correctness-critical silent fallback or release-gate bypass remains from this review.
The repository is ready for a separate MCP server design/implementation pass.
```