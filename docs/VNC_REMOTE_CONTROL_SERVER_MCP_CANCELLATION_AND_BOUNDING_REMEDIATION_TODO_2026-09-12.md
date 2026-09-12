# VNC Remote Control Server — MCP Cancellation and Bounding Remediation TODO

**Date:** 2026-09-12  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_SPEC_2026-09-12.md`  
**Reviewed starting `master`:** `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`  
**Parent MCP TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`

This TODO is evidence-driven. A checkbox is closed only from source, tests, workflow configuration, documentation, audit evidence, or exact-generation external validation. No existing CI/security/release gate was weakened to complete this remediation.

## MCR-001 — Freeze cancellation and outcome semantics

- [x] Define cancellation before controller-call admission versus cancellation after admission.
- [x] Define the externally observable result permitted for pre-admission cancellation.
- [x] Define the externally observable result required for post-admission mutation cancellation.
- [x] State that post-admission cancellation does not prove the mutation did not execute.
- [x] Preserve `retry_safe=false` for every uncertain mutation outcome.
- [x] Preserve trustworthy controller `command_id` values when available.
- [x] Never fabricate a command ID.
- [x] Preserve exactly-one adapter invocation.
- [x] Forbid automatic retry/replay/poll-and-replay.
- [x] Document the selected strategy near executor/outcome code.
- [x] Add architecture comments preventing unsafe future simplification.
- [x] Add deterministic contract tests proving the semantics.

**Result:** executor admission/submission occurs before its first await. Cancellation before a mutation handler is scheduled issues no controller call. Cancellation observed after mutation admission is conservative unknown/non-retry-safe; read-only cancellation remains cancellation after terminal-observation ownership is transferred.

## MCR-002 — Make `BoundedControllerExecutor` cancellation-safe and exception-draining

### Executor ownership

- [x] Give every admitted worker future one defined terminal-observation owner.
- [x] Prevent cancelled awaiters from abandoning later worker exceptions.
- [x] Prevent supported paths from producing `Future exception was never retrieved`.
- [x] Observe terminal state exactly once.
- [x] Preserve results needed for MCP outcome classification.
- [x] Keep cleanup callbacks payload-free and non-logging.

### Capacity semantics

- [x] Preserve admission before submission.
- [x] Preserve bounded concurrency.
- [x] Hold capacity until the synchronous controller call actually exits.
- [x] Release capacity exactly once after terminal completion.
- [x] Prove pre-submission cancellation consumes no worker slot.
- [x] Prove post-submission cancellation does not release the slot early.
- [x] Preserve fail-fast bounded saturation behavior.

### Shutdown/races

- [x] Cover cancellation racing with successful completion.
- [x] Cover cancellation racing with worker failure.
- [x] Cover cancellation racing with executor close.
- [x] Preserve bounded shutdown.
- [x] Prove no executor-owned work is orphaned indefinitely.

## MCR-003 — Preserve truthful mutation outcomes across cancellation

- [x] Prevent post-admission cancellation from surfacing as misleading bare cancellation while the side effect continues invisibly.
- [x] Preserve exactly one typed-client call per admitted mutation.
- [x] Preserve terminal-success handling.
- [x] Preserve controller-known `command_outcome_unknown` handling.
- [x] Preserve no-command-ID `mutation_outcome_unknown` handling.
- [x] Integrate cancellation with conservative unknown-outcome semantics.
- [x] Preserve `retry_safe=false` for uncertain post-admission cancellation.
- [x] Preserve safe request metadata when available.
- [x] Preserve command-status recovery when a trustworthy command ID exists.
- [x] Do not auto-poll-and-replay.
- [x] Do not retry terminal controller failures.
- [x] Keep typed keyboard text out of cancellation/cleanup diagnostics.
- [x] Keep clipboard text out of cancellation/cleanup diagnostics.
- [x] Keep screenshot/raw controller bodies out of asynchronous exception logging.

## MCR-004 — Bound controller response ingestion

### Bounded read primitive

- [x] Add a reusable bounded response-body reader.
- [x] Enforce byte ceilings while reading rather than after unrestricted materialization.
- [x] Use limit-plus-one probing to distinguish valid-at-limit from oversized bodies.
- [x] Do not trust `Content-Length` as the sole bound.
- [x] Support responses without `Content-Length`.
- [x] Fail closed on oversized bodies.
- [x] Keep oversized-body errors free of body contents.

### Screenshot

- [x] Bound screenshot response ingestion before full PNG allocation can exceed the limit.
- [x] Preserve PNG signature/structure/CRC/IHDR/dimension/decompression/IEND validation.
- [x] Preserve native MCP image output.
- [x] Keep transport and MCP screenshot limits intentionally consistent.
- [x] Accept a valid screenshot at the supported boundary.
- [x] Reject one byte over the transport limit.

### JSON/API and metrics/text

- [x] Define finite JSON/controller response maximums.
- [x] Bound success responses.
- [x] Bound HTTP error responses.
- [x] Preserve structured API/transport/protocol classification.
- [x] Reject malformed/oversized JSON as failure.
- [x] Define and enforce a finite metrics/text maximum.
- [x] Preserve valid metrics semantics.

**Final reviewed wire ceilings:** JSON/controller 8 MiB; screenshot PNG 128 MiB; metrics/text 1 MiB; HTTP error bodies 1 MiB.

## MCR-005 — Permanent cancellation and oversized-response regression matrix

### Executor cancellation

- [x] Cancel before admission -> zero underlying calls.
- [x] Cancel after admission -> worker succeeds.
- [x] Cancel after admission -> typed transport failure.
- [x] Cancel after admission -> protocol failure.
- [x] Cancel after admission -> unexpected failure.
- [x] Race cancellation with completion.
- [x] Race cancellation with shutdown.
- [x] Assert no unobserved-future diagnostic.
- [x] Assert capacity remains occupied until worker completion.
- [x] Assert capacity returns exactly once.

### Mutation cancellation

- [x] Exercise a pointer/click mutation through the actual registered path.
- [x] Exercise a payload-bearing mutation through the actual registered path.
- [x] Prove exactly one typed-client mutation invocation.
- [x] Prove cancellation does not imply safe replay after admission.
- [x] Preserve trustworthy command IDs where available.
- [x] Never fabricate command IDs.
- [x] Make unknown outcome explicit where required.
- [x] Keep typed text/clipboard payloads out of diagnostics.

### Read cancellation

- [x] Cancel a read-only call after admission.
- [x] Prove no capacity leak.
- [x] Prove no unobserved future exception.
- [x] Preserve read-error classification.

### Bounded HTTP

- [x] Body exactly at limit.
- [x] Body one byte over limit.
- [x] Missing `Content-Length`.
- [x] Incorrectly small `Content-Length`.
- [x] Oversized success response.
- [x] Oversized error response.
- [x] Oversized screenshot response.
- [x] Valid limit-compatible screenshot.
- [x] Oversized JSON/controller response.
- [x] Oversized metrics/text response.
- [x] Deterministic internet-independent regressions.

## MCR-006 — Re-run unsafe-fallback and silent-failure audit with cancellation in scope

- [x] Review every production `asyncio.shield` use.
- [x] Review every production `asyncio.wrap_future` use.
- [x] Review executor-submitted future lifecycles.
- [x] Review cancellation across side-effect boundaries.
- [x] Review done callbacks and asynchronous cleanup callbacks.
- [x] Review futures/tasks that may outlive their original waiter.
- [x] Review shutdown races.
- [x] Review event-loop default exception-handler exposure.
- [x] Search for broad exception swallowing introduced by remediation.
- [x] Review `.exception()`/`.result()` consumers for semantic correctness.
- [x] Search for ignored results.
- [x] Re-search mutation retry/backoff/replay logic.
- [x] Audit logs for Authorization, tokens, typed text, clipboard, screenshots, raw bodies, and VNC credentials.
- [x] Record intentional ignored/alternate results with rationale.
- [x] Update the MCP unsafe-fallback audit with remediation evidence.
- [x] Extend permanent static contracts.

**Result:** no automatic mutation retry/replay was introduced; the fixed abandoned-future observer consumes terminal state without logging exception payloads.

## MCR-007 — Update living MCP documentation

- [x] Document pre-admission cancellation semantics.
- [x] Document post-admission mutation cancellation semantics.
- [x] Document that admitted mutation cancellation cannot imply non-execution.
- [x] Reiterate no-retry/no-replay.
- [x] Document command-status recovery for trustworthy command IDs.
- [x] Document client-side controller response ceilings.
- [x] Document oversized-response failure behavior.
- [x] Update other living docs only where needed.
- [x] Extend documentation contracts.

## MCR-008 — Reconcile original MCP TODO/evidence without rewriting history

### Original records

- [x] Add remediation notes to MCP-003, MCP-005, MCP-007, MCP-013, and MCP-015.
- [x] Preserve MCP-014 historical exact-generation evidence.
- [x] Preserve prior successful CI runs as factual historical evidence.
- [x] Add a post-closeout remediation section to the original MCP evidence record.
- [x] Record the 2026-09-12 findings and starting master SHA.
- [x] Record the exact remediation implementation candidate.
- [x] Record exact candidate CI/Release Gates results.
- [x] Record exact merged implementation master and post-merge CI/Release Gates results.
- [x] Clearly distinguish original historical closeout evidence from this remediation evidence.

**Validated implementation candidate:** `1cd71c70fc7c63c7ef0c691e2100ab677ca19071`

- CI `34710744120`: **success**
- Release Gates `34710744121`: **success**

**Validated merged implementation master:** `9a0a6f99ce704e5eac0eba10409b6e2746fe28b0`

- CI `34711065779`: **success**
- Release Gates `34711065829`: **success**
- Publish CI Status `34711069866`: **success**

## MCR-009 — Exact candidate validation

- [x] Reconcile MCR-001 through MCR-008 against actual source/tests/docs/workflows.
- [x] Record exact implementation candidate SHA.
- [x] Run regular CI on that exact SHA.
- [x] Record CI run ID/conclusion.
- [x] Run Release Gates on that exact SHA.
- [x] Record Release Gates run ID/conclusion.
- [x] Verify Python compile/lint/type checks pass.
- [x] Verify core Python client without MCP passes.
- [x] Verify cancellation regressions pass.
- [x] Verify bounded-response regressions pass.
- [x] Verify stdio transport acceptance passes.
- [x] Verify Streamable HTTP acceptance passes.
- [x] Verify production MCP -> controller -> TigerVNC E2E passes.
- [x] Verify R13 integration passes.
- [x] Verify Python MCP dependency/license gate passes.
- [x] Verify Gitleaks/cargo-deny/auditable-binary gates pass.
- [x] Verify sanitizer/Miri gates pass.
- [x] Verify Trivy/SBOM/VEX gates pass.
- [x] Investigate every failure and fix root cause without weakening gates.
- [x] Re-run both workflows whenever an implementation fix changed the candidate SHA.
- [x] Require regular CI and Release Gates green on one exact candidate before merge.

### Candidate-failure history

The loop fixed Ruff B023 captures, Pylint test/protocol diagnostics, mypy callback/protocol typing, a documentation-contract case mismatch, and a stale exact VEX inventory. None was bypassed or converted to `continue-on-error`. The VEX refresh removed only tuples no longer observed as CRITICAL, retained still-observed controller Perl/libxml2 determinations, and refreshed `reviewed_at` to `2026-09-12` / `expires_at` to `2026-10-12` with tracking issue `7`.

## MCR-010 — Guarded merge and exact-master validation

- [x] Merge only through the repository's policy-approved guarded path.
- [x] Record exact merged implementation `master` SHA.
- [x] Require fresh regular CI on exact merged implementation `master`.
- [x] Record final implementation-master CI run ID/conclusion.
- [x] Require fresh Release Gates on exact merged implementation `master`.
- [x] Record final implementation-master Release Gates run ID/conclusion.
- [x] Re-review VEX status/expiry at final validation time.
- [x] Do not treat merge success as validation success.
- [x] Investigate any merged-master failure before sign-off.

PR #46 was squash-merged through the guarded merge path to `9a0a6f99ce704e5eac0eba10409b6e2746fe28b0`. Fresh push CI `34711065779` and Release Gates `34711065829` both passed that exact SHA. VEX metadata at sign-off is `reviewed_at: 2026-09-12`, `expires_at: 2026-10-12`, tracking issue `7`, and exact CRITICAL enforcement passed both candidate and merged-master Release Gates.

## MCR-011 — Final evidence and completion

- [x] Maintain a durable remediation evidence document.
- [x] Record starting master `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`.
- [x] Record final cancellation semantics.
- [x] Record executor terminal-observation strategy.
- [x] Record bounded-response design and exact byte ceilings.
- [x] Record regression matrix.
- [x] Record unsafe-fallback audit conclusions.
- [x] Record exact candidate SHA plus CI/Release Gates IDs/conclusions.
- [x] Record exact merged implementation master plus CI/Release Gates IDs/conclusions.
- [x] Re-review every MCR checkbox against final source/tests/workflows/docs/evidence.
- [x] Confirm no checkbox is closed solely because a commit message says so.
- [x] Confirm no security/release gate was weakened.
- [x] Confirm no automatic mutation retry/replay was introduced.
- [x] Confirm supported cancellation paths no longer reproduce `Future exception was never retrieved`.
- [x] Confirm post-admission mutation cancellation cannot falsely imply non-execution.
- [x] Confirm controller response ingestion is bounded during read.
- [x] Declare runtime remediation complete only after exact merged implementation master CI and Release Gates are green.

## Completion declaration

- [x] MCP cancellation and bounding runtime remediation is complete.
- [x] Original MCP evidence is reconciled without rewriting historical validation.
- [x] Exact merged implementation `master` `9a0a6f99ce704e5eac0eba10409b6e2746fe28b0` passed CI `34711065779` and Release Gates `34711065829`.

This file is finalized in a documentation-only closeout generation after the validated implementation merge. The closeout commit cannot truthfully contain its own future GitHub Actions run IDs. Therefore the closeout PR must itself pass CI and Release Gates before merge, and the resulting documentation-closed `master` must pass fresh CI and Release Gates as external validation. Those later workflow results validate this evidence record; they do not require another self-referential edit.
