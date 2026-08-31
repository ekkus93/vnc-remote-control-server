# VNC Remote Control Server — Code Review Remediation Evidence

Date: 2026-08-31  
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`  
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`

## Status

This is the cumulative evidence document for the 2026-08-31 code-review remediation pass.

**R0 and R1 are implemented and validated. R2-R15 remain open.** This document must therefore not be read as final sign-off for the complete remediation pass. MCP implementation remains out of scope until the remediation TODO is complete.

The R1 implementation was developed on PR #19, `ralph/code-review-remediation-20260831-r1`.

## R0 — Baseline and preserved safety constraints

### Reviewed baseline

- Starting reviewed `master` SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline regular CI: run `31265957251`, conclusion `success`, head SHA `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline Release Gates: run `31265957258`, conclusion `success`, head SHA `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- The companion remediation specification was kept separate from the future MCP phase. No MCP implementation was added in R1.

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

A documentation-only R1 closeout commit will be validated again with both workflows before PR #19 is merged. The resulting merge to `master` will be verified separately. These R1 closeout runs are not the final R13/R14 evidence for the entire R0-R15 remediation pass because R2-R12 remain outstanding.

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

## Remaining remediation

R2-R15 remain open. In particular, this evidence does **not** claim completion of scroll-wheel state recovery, clipboard callback propagation, duration hardening, WebSocket inbound hardening, XFCE startup hardening, shutdown/detach lifecycle hardening, failure classification, the full R9 fallback audit, or final project-wide exact-`master` sign-off.

The final remediation evidence will extend this file as those slices are completed.
