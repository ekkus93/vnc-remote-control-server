# VNC Remote Control Server — Code Review Remediation Evidence

Date: 2026-08-31  
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`  
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`

## Status

This is the cumulative evidence document for the 2026-08-31 code-review remediation pass.

**R0, R1, and R2 are implemented and validated. R3-R15 remain open.** This document must therefore not be read as final sign-off for the complete remediation pass. MCP implementation remains out of scope until the remediation TODO is complete.

The R1 implementation was developed on PR #19 / replacement merge PR #20, `ralph/code-review-remediation-20260831-r1`. The R2 implementation is developed on PR #21, `ralph/code-review-remediation-20260831-r2`.

## R0 — Baseline and preserved safety constraints

### Reviewed baseline

- Starting reviewed `master` SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline regular CI: run `31265957251`, conclusion `success`, head SHA `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline Release Gates: run `31265957258`, conclusion `success`, head SHA `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- The companion remediation specification was kept separate from the future MCP phase. No MCP implementation was added in R1 or R2.

### Safety constraints preserved through R1

R1 did not relax the existing security/resource boundaries. The exact R1 implementation candidate `4cbbdcce814c0841eb1c0686b5d7c253be1a394c` passed regular CI run `33436761556` and Release Gates run `33436761617`.

The passing validation preserves the existing raw-VNC internal-network model, bearer authentication for `/v1/*`, secret-file credential handling and payload/secret redaction, bounded worker/event/screenshot resources, fail-closed sequence/native-size handling, and blocking release gates. No `continue-on-error`, broad scanner allowlist, mutation retry fallback, or release-policy bypass was introduced.

During R1 validation the exact CRITICAL VEX gate correctly failed when its reviewed set became stale. `CVE-2026-57433` was re-reviewed against the current Trivy result; because it was no longer CRITICAL, the stale CRITICAL tuples were removed and the VEX review window was renewed. The gate itself was not weakened or bypassed.

## R1 — Command lifecycle and admission boundary

### Lifecycle traced

The R1 review traced the mutation path end to end:

1. `WorkerClient::submit` allocates the stable process-local command ID.
2. The command-outcome registry reserves that ID before the command can be admitted to the bounded worker queue.
3. Queue admission marks the record `queued`; dequeue marks it `running`.
4. The worker records `succeeded` or `failed` before attempting the completion-channel send.
5. `CommandTicket::wait` may time out without changing the authoritative outcome record.
6. `WorkerHttpBackend::execute_command` distinguishes pre-admission rejection, admitted known failure, and admitted unknown timeout.
7. HTTP mutation handlers map those three classes to distinct wire contracts.
8. `GET /v1/commands/{command_id}` reads the retained process-local outcome.
9. The Python client parses the same contract strictly and never automatically retries an unknown mutation.
10. Worker exit/panic marks still-accepted nonterminal commands `aborted` so they cannot remain permanently pending.

### Pre-admission failures

A failure that prevents queue admission has no accepted-command identity in the HTTP error body and is retry-classified by the specific domain error rather than as an unknown execution outcome. Covered cases include:

- request validation/body rejection before worker execution;
- command queue saturation (`command_queue_full`);
- worker/shutdown unavailability (`worker_unavailable` / shutdown rejection);
- command-ID exhaustion;
- command-outcome registry capacity exhaustion before admission.

The worker queue test `bounded_command_queue_tracks_depth_and_rejection_without_payload_logging` proves queue-full rejection. `submit_rejects_after_shutdown_request_without_queue_mutation` proves worker-unavailable rejection without queue mutation. Existing HTTP validation tests prove validation happens before worker execution.

### Post-admission outcomes

Once queue admission occurs, callers must not infer non-execution from a wait timeout. Admitted outcomes are one of the retained lifecycle states:

- `reserved`
- `queued`
- `running`
- `succeeded`
- `failed`
- `aborted`
- `rejected`

`reserved` exists only before successful queue admission; an admitted command is not retry-safe merely because its caller stopped waiting.

## R1 — Stable command identity

The ID is allocated before queue admission and follows the command through queueing, execution, completion, timeout reconciliation, diagnostics, status lookup, and worker-abort handling.

Command-ID exhaustion remains fail closed. The worker lifecycle test `command_id_exhaustion_is_shared_terminal_and_never_enqueues` verifies exhaustion does not wrap or enqueue a new mutation.

The timeout regression tests capture `ticket.id()` before a zero-duration wait, then query the same ID until its eventual terminal state. The HTTP/Python reconciliation tests also require the ID in the timeout error to be the ID used for status lookup.

## R1 — Bounded command-outcome registry

`CommandOutcomeRegistry` is process local and bounded by `COMMAND_OUTCOME_CAPACITY = 4096`.

The chosen R1 retention policy is **strict capacity without a time-based TTL**. This satisfies the TODO's “maximum capacity and/or TTL” requirement while avoiding time-dependent eviction. Terminal records are evicted deterministically when capacity is needed; unresolved/nonterminal accepted commands are never evicted merely to admit another command. If all capacity is occupied by nonterminal records, the next command fails before admission with `CommandOutcomeCapacityFull`.

This design intentionally favors preserving the inspectability of uncertain accepted commands over accepting more work.

The registry stores only:

- command ID;
- lifecycle state;
- an optional sanitized static failure category.

It does **not** retain the original command, typed text, clipboard contents, bearer tokens, VNC credentials, screenshots, coordinates as diagnostic payloads, or other command payload material.

Relevant registry tests include:

- `terminal_records_are_evicted_but_pending_records_are_not`
- `retained_records_never_store_payloads_and_terminate_nonterminal`
- `rejected_command_is_retry_safe_and_classified`

Worker panic/exit coverage additionally proves accepted nonterminal records become `aborted`.

## R1 — Authenticated command-status endpoint

R1 adds authenticated `GET /v1/commands/{command_id}` under the same bearer policy as other `/v1/*` routes.

A retained record returns the command ID, lifecycle status, optional sanitized failure category, and `retry_safe`. Unknown IDs return `404 command_status_unknown`; IDs that are below the retained high-water/eviction boundary return `410 command_status_expired` according to the registry's process-local retention semantics.

HTTP coverage includes:

- bearer authentication;
- queued/pending and running records;
- succeeded records;
- failed records with sanitized failure category;
- aborted records;
- rejected records;
- unknown IDs;
- expired IDs;
- no payload/token leakage.

Relevant tests include `command_status_is_authenticated_and_reports_sanitized_lifecycle` and `command_status_reports_pending_running_failed_and_rejected_states`.

The hosted `docs/openapi.json` and documentation-contract tests include the status route and closed lifecycle vocabulary.

## R1 — Timeout wire contract and retry policy

### Successful mutation

Mutation endpoints remain synchronous-to-terminal-result. A command that finishes successfully before the HTTP wait deadline returns HTTP `200` with:

```json
{
  "command_id": 123,
  "status": "succeeded"
}
```

R1 deliberately removed the previous semantic mismatch in which a synchronous-to-terminal handler returned `202 Accepted` / `"accepted"`.

### Known admitted failure

If an admitted command reaches a known failure before the wait deadline, the normal mapped HTTP error includes command context:

```json
{
  "error": {
    "code": "desktop_operation_failed",
    "message": "...",
    "request_id": "...",
    "command_id": 123,
    "outcome": "failed",
    "retry_safe": false
  }
}
```

The exact status/code still follows the underlying safe domain mapping; the important R1 distinction is that this is a known terminal failure of an admitted command.

### Accepted command whose caller times out

If an admitted command has not reached a terminal result before the HTTP wait deadline, the server returns HTTP `504` with stable identity and explicitly unknown/non-retry-safe semantics:

```json
{
  "error": {
    "code": "command_timeout",
    "message": "desktop command result wait timed out; execution outcome is unknown",
    "request_id": "...",
    "command_id": 123,
    "outcome": "unknown",
    "retry_safe": false
  }
}
```

**The original side-effecting mutation must not be automatically retried.** The caller must inspect `GET /v1/commands/123` and reconcile the retained outcome before deciding whether any further mutation is safe.

The completion receiver may disappear when an HTTP caller times out, but worker outcome state is recorded before the completion send. Therefore an abandoned receiver cannot erase the authoritative result; ignoring a failed completion-channel send remains safe for this specific observer-loss case.

## R1 — Python client

The typed Python client now:

- parses command IDs strictly;
- expects HTTP `200` / `status="succeeded"` for successful synchronous mutations;
- exposes `get_command_status(command_id)` with strict exact-field/status parsing;
- raises `CommandOutcomeUnknownError` for a valid post-admission `504 command_timeout`;
- carries `command_id`, `outcome="unknown"`, and `retry_safe=False` on that exception;
- rejects malformed/inconsistent timeout context as `ProtocolError`;
- represents known admitted failures separately from unknown timeouts;
- performs no automatic mutation retry;
- keeps payload/credential sentinel values out of exception string/repr output.

`python/README.md` documents the required reconciliation pattern: catch `CommandOutcomeUnknownError`, inspect the stable command ID, query status, and do not blindly retry the original mutation.

## R1 — Acceptance regression evidence

The R1 candidate includes coverage for the TODO acceptance matrix:

| Acceptance case | Evidence |
| --- | --- |
| Known success before timeout | HTTP mutation tests and authenticated HTTP TigerVNC E2E require `200` / `succeeded`. |
| Known command failure before timeout | `pre_admission_rejection_and_post_admission_outcomes_are_distinct` covers admitted `Failed` with `outcome=failed`, `retry_safe=false`. |
| Validation failure before admission | `invalid_pointer_request_never_reaches_worker`, keyboard/text/clipboard preflight tests, and oversized/shutdown pre-dispatch tests. |
| Queue full before admission | `bounded_command_queue_tracks_depth_and_rejection_without_payload_logging` plus HTTP queue-full distinction. |
| Worker unavailable before admission | `submit_rejects_after_shutdown_request_without_queue_mutation`. |
| Accepted timeout, then success | `timed_out_ticket_remains_inspectable_and_later_succeeds`. |
| Accepted timeout, then failure | `timed_out_ticket_remains_inspectable_and_later_fails`. |
| Accepted command aborted by worker termination | `timed_out_accepted_command_is_aborted_when_worker_terminates` and unexpected-panic coverage `timed_out_accepted_command_is_aborted_after_unexpected_worker_panic`. |
| Identical ID across timeout/status | Worker timeout tests plus Python reconciliation tests use the timeout command ID for later lookup. |
| Timeout explicitly non-retry-safe | HTTP command-timeout assertions and `CommandOutcomeUnknownError` tests require `retry_safe=false`. |
| Registry bounded | `terminal_records_are_evicted_but_pending_records_are_not`; fixed capacity 4096; capacity refusal before unresolved eviction. |
| No sensitive data in status/events/metrics/logs | registry payload-retention test; HTTP privacy tests; existing fixed-label metrics and log-redaction tests; Python sentinel tests. |

Python-specific reconciliation tests:

- `test_command_timeout_is_distinct_non_retryable_error`
- `test_unknown_timeout_can_later_report_success`
- `test_unknown_timeout_can_later_report_failure`

These tests also prove the original mutation opener is called exactly once.

## R1 — Integration and release validation

Exact implementation candidate before R1 closeout documentation:

`4cbbdcce814c0841eb1c0686b5d7c253be1a394c`

Regular CI run `33436761556`: **success**.

The CI run passed:

- `cargo fmt --all --check`;
- Clippy with warnings denied;
- Rust tests (161 controller tests plus workspace/native/core tests);
- rustdoc with warnings denied;
- Python compilation;
- Ruff;
- Pylint (`10.00/10`);
- mypy;
- Python/workflow documentation-contract tests;
- shell syntax;
- desktop image smoke;
- native adapter smoke;
- WorkerHandle input E2E;
- WorkerHandle text/clipboard E2E;
- authenticated HTTP TigerVNC E2E;
- controller image / Compose / persistence smoke;
- full R13 Compose integration.

Release Gates run `33436761617`: **success**.

The release run retained blocking static/supply-chain policy, secret scanning, native sanitizer/Miri validation, exact image vulnerability/SBOM/VEX validation, and did not add a release bypass.

The R1 branch was subsequently reconciled, validated again, and squash-merged to `master` as `992210538befddf7b683bc9539dc31d9ab991583` through replacement PR #20 after the installed connector's draft-to-ready GraphQL wrapper failed. The replacement used the identical validated branch head and unchanged base; no code was changed to work around the connector. Push-triggered master CI `33439766598` and Release Gates `33439766636` both passed on that exact SHA.

## R1 — Silent-failure review limited to this slice

R1 specifically reviewed ignored completion sends and timeout abandonment introduced or touched by this change.

The remaining ignored completion sends are intentional observer-loss cases: the worker records the authoritative outcome before attempting to notify the waiter, so a timed-out/dropped requester cannot cause command state to disappear or regress. No command payload is logged on send failure.

R1 adds no automatic retry after uncertain execution. It adds no `.ok()`/`unwrap_or*` operational fallback to the mutation path, no `continue-on-error`, and no scanner exception to force a green release result.

The comprehensive changed/adjacent fallback audit remains R9 and is **not** claimed complete here.

## Explicit R1 safety statements

- No side-effecting command is automatically retried after an unknown outcome.
- No secret or command payload logging was added.
- The command-status registry retains no secret or command payload material.
- Accepted command timeout is represented as unknown and non-retry-safe, never as known non-execution.
- No release-critical gate was weakened.
- MCP implementation was not started as part of R1.

## R2 — Scroll-wheel pointer-state uncertainty and recovery

### Unsafe behavior removed

Before R2, the vertical scroll path attempted to return the tracked base button mask after a transient wheel-button press. If the first release failed, it performed a second release attempt with:

```text
let _ = sink.send_pointer(...)
```

The second result was discarded. If both release attempts failed, the command returned the first native error while the same VNC session remained live. The remote pointer mask could therefore be unknown, yet later input commands could continue on that session as though the pointer state were authoritative.

R2 removes that silent fallback. The second release result is now observed and changes worker-owned state when it also fails.

### Pointer-state representation

`InputController` now carries a typed internal `PointerState` with two states:

- `Known`
- `Uncertain`

The ordinary tracked `button_mask` remains authoritative while pointer state is known. A scroll wheel step still sends the preserved base mask, the transient wheel mask, then the preserved base mask again.

If the first wheel-release attempt fails but the retry succeeds:

- the retry result is observed;
- `PointerState` remains `Known`;
- the remote pointer mask is known to have returned to the preserved base mask;
- the original operation error is still returned to the caller rather than silently turning a partial failure into success;
- the current VNC session remains usable.

If both release attempts fail:

- `PointerState` becomes `Uncertain`;
- the second failure is no longer ignored;
- the caller still receives the original operation error;
- the worker treats the session as unsafe for further input.

### Fail-closed session quarantine

`LoopState::execute` checks the pointer-state flag immediately after the scroll operation returns. Because worker command execution is single-threaded, no later command can be dequeued between the double-release failure and the recovery action.

On `PointerState::Uncertain`, the worker:

1. emits the payload-free sanitized diagnostic `worker_input_pointer_state_uncertain`;
2. calls `invalidate()` before returning from command execution;
3. performs one best-effort tracked-input cleanup pass on the affected session;
4. drops the VNC session even if that cleanup release itself fails;
5. explicitly abandons/clears any unresolved local pointer/key tracking only after the session is no longer retained;
6. invalidates framebuffer/session state;
7. schedules the normal bounded reconnect path.

The cleanup path also reports only safe counters/booleans through `worker_input_release_incomplete` and `worker_input_release_abandoned`; it does not log keys, coordinates, typed text, clipboard data, credentials, or other payloads.

If cleanup succeeds, the old session is still discarded because it had already crossed the uncertainty boundary. If cleanup fails, the session is likewise discarded; the implementation does not use a “best effort, then keep going” fallback.

If an unrelated failure prevents reconnect scheduling or event publication, the unsafe session has already been removed and the unresolved local input state abandoned. The failure mode therefore remains fail closed rather than allowing later input on the tainted session.

### Clean recovery semantics

A newly established VNC session begins with `InputController` pointer state `Known`, button mask `0`, and an empty pressed-key set. The R2 worker regression deliberately holds a key before provoking the scroll uncertainty and also forces the old session's cleanup pointer release to fail. It then verifies that:

- the first session receives no later ordinary pointer command after the double-release failure;
- a second VNC session is created;
- the first post-reconnect pointer event uses mask `0`;
- a key that was held before the failure can be freshly pressed and released on the new session, proving stale key tracking was not carried across the session boundary.

### R2 regression tests

The implementation includes the following focused coverage:

- `vertical_scroll_is_bounded_atomic_and_preserves_mask` — normal wheel press/release behavior and preservation of an already-held ordinary button mask.
- `scroll_release_failure_retry_success_keeps_pointer_state_known` — first release fails, retry succeeds, original error is reported, pointer state remains known, and the session remains usable.
- `scroll_double_release_failure_marks_pointer_state_uncertain_and_cleanup_recovers` — both releases fail, typed pointer state becomes uncertain, and an explicit cleanup release can restore known state.
- `scroll_double_release_failure_quarantines_session_and_reconnects_cleanly` — both releases fail, the cleanup pointer release also fails, the old session is dropped, reconnect occurs, and the fresh session starts with clean pointer/key tracking.
- `release_all_reports_failed_pointer_release_without_silent_clear` — a failed tracked pointer cleanup remains represented until the session is explicitly abandoned rather than being silently cleared.
- `explicit_buttons_preserve_full_mask`, `disconnect_release_clears_buttons_and_keys`, and the existing key/chord/text tests remain part of the full passing Rust suite and protect ordinary button/key tracking semantics.

The integration regression uses generation-tagged test sessions so a post-failure input event on the original session would fail the exact event-sequence assertion. It also forces pointer calls 3 through 5 on generation 1 to fail, covering first release, second release, and subsequent cleanup release failure.

### R2 implementation-head validation

Exact R2 implementation candidate before TODO/evidence closeout documentation:

`f081541e927977ef1dc5506487f2ce586834b2e9`

Regular CI run `33442324230`: **success**.

That run passed the complete repository-quality suite, including rustfmt, Clippy with warnings denied, all Rust tests (including the new R2 regression tests), rustdoc, Python Ruff/Pylint/mypy/contracts, and shell syntax. It also passed the secured desktop/native chain, WorkerHandle input and text/clipboard E2E, authenticated HTTP TigerVNC E2E, controller image/Compose/persistence smoke, and R13 Compose integration.

Release Gates run `33442324185`: **success**.

That run passed full-history secret scanning, shell/action/Docker/Compose policy, dependency/advisory/license/source/duplicate policy, release binary inspection, ASan, TSan, Miri, image vulnerability scanning, CycloneDX SBOM generation, and exact CRITICAL VEX enforcement.

No release-critical gate was weakened for R2.

### R2 silent-failure review limited to this slice

The correctness-sensitive ignored second wheel-release result was removed. The replacement does not silently downgrade uncertainty to success and does not continue using a session after unresolved pointer state.

R2 intentionally retains best-effort cleanup attempts only under an explicit fail-closed invariant: cleanup results are observed and reported; unresolved state remains tracked until the affected session is dropped; after the drop, `abandon()` clears local tracking because that state can no longer be used to drive the discarded native session. A failed cleanup does not permit session reuse.

The separate comprehensive changed/adjacent fallback audit remains R9 and is not claimed complete here.

## Explicit R2 safety statements

- A second failed scroll-wheel release is observed, not discarded.
- Double-release failure marks pointer state uncertain.
- No subsequent input command executes on the tainted VNC session.
- The tainted session is dropped even when best-effort cleanup also fails.
- Recovery uses a fresh session with clean pointer and key tracking.
- R2 diagnostics contain no secret or input payload material.
- No release-critical gate was weakened.
- MCP implementation remains out of scope.

## Remaining remediation

R3-R15 remain open. In particular, this evidence does **not** claim completion of clipboard callback propagation, duration hardening, WebSocket inbound hardening, XFCE startup hardening, shutdown/detach lifecycle hardening, failure classification, the full R9 fallback audit, or final project-wide exact-`master` sign-off.

The final remediation evidence will extend this file as those slices are completed.
