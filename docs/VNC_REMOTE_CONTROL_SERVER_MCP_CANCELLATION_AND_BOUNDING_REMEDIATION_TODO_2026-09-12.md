# VNC Remote Control Server — MCP Cancellation and Bounding Remediation TODO

**Date:** 2026-09-12  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_SPEC_2026-09-12.md`  
**Reviewed starting `master`:** `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`  
**Parent MCP TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`

This TODO is evidence-driven. Do not close a checkbox from a commit message alone. Every completed item must be supported by source, tests, workflow configuration, documentation, or exact-generation external validation.

Do not weaken an existing CI/security/release gate to make this remediation green.

---

## MCR-001 — Freeze cancellation and outcome semantics

### Required behavioral contract

- [x] Define the precise distinction between cancellation before controller-call admission and cancellation after admission.
- [x] Define what externally observable result is permitted for pre-admission cancellation.
- [x] Define what externally observable result is required for post-admission mutation cancellation.
- [x] State explicitly that post-admission cancellation does not prove the mutation did not execute.
- [x] Preserve `retry_safe=false` for every uncertain mutation outcome.
- [x] Preserve trustworthy controller `command_id` values when available.
- [x] Never fabricate a command ID.
- [x] Preserve the exactly-one adapter invocation invariant.
- [x] Explicitly forbid automatic retry/replay/poll-and-replay.
- [x] Document the selected implementation strategy near the executor/outcome code.
- [x] Add or update architecture comments so future maintainers do not "simplify" the cancellation logic back into an unsafe form.

### Evidence

- [x] Add deterministic contract tests proving the frozen semantics before closing MCR-001.

---

## MCR-002 — Make `BoundedControllerExecutor` cancellation-safe and exception-draining

### Executor ownership

- [x] Ensure every admitted worker future has one defined terminal-observation owner.
- [x] Ensure a cancelled awaiting task cannot abandon a future whose exception later becomes unobserved.
- [x] Ensure no supported path produces `Future exception was never retrieved`.
- [x] Ensure terminal observation happens exactly once.
- [x] Ensure exception-draining code does not accidentally swallow a result needed for MCP outcome classification.
- [x] Ensure cleanup callbacks do not log raw controller payload/body data.

### Capacity semantics

- [x] Preserve admission before submission.
- [x] Preserve bounded executor concurrency.
- [x] Preserve the invariant that capacity is held until the underlying synchronous controller call actually exits.
- [x] Prove capacity is released exactly once after terminal worker completion.
- [x] Prove cancellation before submission does not consume a worker slot.
- [x] Prove cancellation after submission does not free the slot early.
- [x] Prove saturation remains fail-fast/bounded according to existing behavior.

### Shutdown/races

- [x] Cover cancellation racing with successful worker completion.
- [x] Cover cancellation racing with worker failure.
- [x] Cover cancellation racing with executor `close()`.
- [x] Preserve bounded shutdown.
- [x] Prove no executor-owned work is orphaned indefinitely.

---

## MCR-003 — Preserve truthful mutation outcomes across cancellation

### Mutation execution

- [x] Update mutation wrapper/outcome handling so post-admission cancellation cannot surface as misleading bare cancellation while the side effect continues invisibly.
- [x] Preserve exactly one typed-client call for every admitted mutation.
- [x] Preserve existing terminal-success handling.
- [x] Preserve existing controller-known `command_outcome_unknown` handling.
- [x] Preserve existing no-command-ID `mutation_outcome_unknown` handling.
- [x] Integrate cancellation with the conservative unknown-outcome model where execution cannot be proven absent.
- [x] Preserve `retry_safe=false` for uncertain post-admission cancellation.
- [x] Preserve/request `request_id` where safe and available.
- [x] Direct callers to `vnc_get_command_status(command_id)` when a trustworthy command ID exists.
- [x] Do not auto-poll-and-replay.
- [x] Do not retry terminal controller failures.

### Sensitive mutations

- [x] Verify typed keyboard text is never included in cancellation/cleanup diagnostics.
- [x] Verify clipboard text is never included in cancellation/cleanup diagnostics.
- [x] Verify screenshot/controller raw bodies are never exposed through asynchronous exception logging.

---

## MCR-004 — Bound controller response ingestion

### Bounded read primitive

- [x] Introduce a reusable bounded response-body read helper in the typed Python client or another appropriate shared layer.
- [x] Enforce byte bounds while reading, not only after full `response.read()` materialization.
- [x] Use a `limit + 1` or equivalent strategy to distinguish valid-at-limit from oversized responses.
- [x] Do not trust `Content-Length` as the sole bound.
- [x] Support responses without `Content-Length`.
- [x] Fail closed on bodies exceeding the configured/constant maximum.
- [x] Ensure oversized-body error messages do not include body contents.

### Screenshot

- [x] Bound screenshot response ingestion before the full PNG can exceed the allowed allocation.
- [x] Preserve existing PNG signature/structure/CRC/IHDR/dimension/decompression/IEND validation.
- [x] Preserve native MCP image output.
- [x] Keep transport-level screenshot limit and MCP PNG limit consistent and documented.
- [x] Verify a valid screenshot at the maximum supported size remains accepted.
- [x] Verify a screenshot one byte over the transport limit is rejected before unbounded materialization.

### JSON/API bodies

- [x] Define an explicit finite maximum for normal JSON/controller responses.
- [x] Apply the bound to success responses.
- [x] Apply the bound to HTTP error responses.
- [x] Preserve structured `ApiError`, transport, and protocol classification after bounded reads.
- [x] Ensure malformed/oversized JSON never becomes success.

### Metrics/text

- [x] Define an explicit finite maximum for metrics/text responses.
- [x] Apply the bound before complete materialization.
- [x] Preserve existing controller metrics semantics for valid responses.

---

## MCR-005 — Add permanent cancellation and oversized-response regression matrix

### Executor cancellation tests

- [x] Cancel before admission -> prove zero underlying client calls.
- [x] Cancel after admission -> worker succeeds.
- [x] Cancel after admission -> worker raises typed transport error.
- [x] Cancel after admission -> worker raises protocol error.
- [x] Cancel after admission -> worker raises unexpected exception.
- [x] Race cancellation with completion.
- [x] Race cancellation with shutdown.
- [x] Assert no unobserved-future diagnostic is emitted.
- [x] Assert capacity remains occupied until worker completion.
- [x] Assert capacity returns exactly once.

### Mutation cancellation tests

- [x] Exercise at least one pointer/click mutation through the actual registered mutation path.
- [x] Exercise at least one payload-bearing mutation through the actual registered mutation path.
- [x] Prove exactly one typed-client mutation invocation.
- [x] Prove cancellation does not imply safe replay after admission.
- [x] Prove trustworthy command IDs are preserved where available.
- [x] Prove command IDs are never fabricated.
- [x] Prove unknown outcome is explicit where required.
- [x] Prove typed text/clipboard payloads do not appear in captured diagnostics.

### Read cancellation tests

- [x] Cancel a read-only call after admission.
- [x] Prove no capacity leak.
- [x] Prove no unobserved future exception.
- [x] Prove read errors remain read errors rather than mutation-unknown errors.

### Bounded HTTP tests

- [x] Valid body exactly at limit.
- [x] Body one byte over limit.
- [x] Missing `Content-Length`.
- [x] Incorrectly small `Content-Length`.
- [x] Oversized success response.
- [x] Oversized error response.
- [x] Oversized screenshot response.
- [x] Valid screenshot at a limit-compatible size.
- [x] Oversized JSON/controller response.
- [x] Oversized metrics/text response.
- [x] Keep all regression tests deterministic and internet-independent.

---

## MCR-006 — Re-run unsafe-fallback and silent-failure audit with cancellation in scope

### Static/dynamic audit

- [x] Review every `asyncio.shield` usage in MCP production code.
- [x] Review every `asyncio.wrap_future` usage.
- [x] Review every executor-submitted future lifecycle.
- [x] Review every explicit `CancelledError` handler or absence thereof where cancellation can cross a side-effect boundary.
- [x] Review every done callback.
- [x] Review every asynchronous cleanup callback.
- [x] Review every future/task that may outlive its original waiter.
- [x] Review shutdown races.
- [x] Review event-loop default exception-handler exposure.
- [x] Search for broad exception swallowing introduced by remediation.
- [x] Search for callbacks that call `.exception()` or `.result()` without preserving required semantic handling.
- [x] Search for new ignored return values.
- [x] Search again for mutation retry/backoff/replay logic.
- [x] Search logs/tracing for Authorization, token values, typed text, clipboard, screenshot bytes, raw controller bodies, and VNC credentials.
- [x] Record every intentional ignored terminal result/fallback with nearby rationale.
- [x] Update the MCP unsafe-fallback audit document with the discovered defects and their remediation evidence.
- [x] Add/extend permanent static contract tests so the same class of defect is harder to reintroduce.

---

## MCR-007 — Update living MCP documentation

- [x] Update `docs/MCP_SERVER.md` with pre-admission cancellation semantics.
- [x] Document post-admission mutation cancellation semantics.
- [x] Document that an admitted mutation cannot be assumed not to have executed merely because the caller was cancelled.
- [x] Reiterate the no-retry/no-replay rule.
- [x] Document command-status recovery for trustworthy command IDs.
- [x] Document client-side controller response-size ceilings.
- [x] Document oversized-response failure behavior.
- [x] Update root/operator/security documentation only where existing text becomes inaccurate.
- [x] Extend documentation contract/freshness tests for the new semantics.

---

## MCR-008 — Reconcile original MCP TODO and evidence without rewriting history

### Original TODO

- [x] Add a remediation note to MCP-003 explaining the post-admission cancellation defect and fix.
- [x] Add a remediation note to MCP-005 explaining transport-level response bounding.
- [x] Add a remediation note to MCP-007 explaining cancellation/unknown-outcome semantics.
- [x] Add a remediation note to MCP-013 explaining the reopened unsafe-fallback audit.
- [x] Update MCP-015 completion language to reference this remediation phase.
- [x] Preserve MCP-014's historical candidate/master CI evidence exactly as historical evidence.
- [x] Do not relabel prior successful CI runs as failures.

### Evidence

- [x] Update `docs/VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md` with a post-closeout remediation section.
- [x] Record the code-review finding date and starting master SHA.
- [x] Record the exact defects found.
- [ ] Record the remediation branch/candidate SHA after implementation.
- [ ] Record exact candidate CI/Release Gates results.
- [ ] Record exact merged-master SHA and post-merge CI/Release Gates results.
- [x] Clearly distinguish historical MCP completion evidence from remediation evidence.

### Implementation checkpoint

MCR-001 through MCR-007 and the non-CI portions of MCR-008 are implemented in the remediation working tree. Permanent regression coverage includes executor cancellation races, actual registered mutation cancellation, sensitive-payload failure draining, read cancellation, bounded JSON/screenshot/metrics/error response ingestion, documentation contracts, and the extended unsafe-fallback static contract. Exact remote candidate SHA and workflow evidence remain intentionally open until the branch is committed and GitHub Actions validates that exact generation.

---

## MCR-009 — Exact candidate validation

### Candidate freeze

- [ ] Reconcile MCR-001 through MCR-008 against actual source/tests/docs/workflows.
- [ ] Record exact candidate SHA.
- [ ] Run regular CI on that exact SHA.
- [ ] Record CI run ID and conclusion.
- [ ] Run Release Gates on that exact SHA.
- [ ] Record Release Gates run ID and conclusion.
- [ ] Verify Python compile/lint/type checks pass.
- [ ] Verify core Python client without MCP still passes.
- [ ] Verify new cancellation regression matrix passes.
- [ ] Verify bounded-response regression matrix passes.
- [ ] Verify stdio transport acceptance passes.
- [ ] Verify Streamable HTTP acceptance passes.
- [ ] Verify production MCP -> controller -> TigerVNC E2E passes.
- [ ] Verify R13 integration passes.
- [ ] Verify Python MCP dependency/license gate passes.
- [ ] Verify Gitleaks/cargo-deny/auditable binary gates pass.
- [ ] Verify sanitizer/Miri gates pass.
- [ ] Verify Trivy/SBOM/VEX gates pass.
- [ ] Investigate every failure and fix root cause without weakening gates.
- [ ] If any fix changes candidate SHA, require both permanent workflows again on the new exact generation.
- [ ] Require regular CI and Release Gates green on one exact candidate SHA before merge.

---

## MCR-010 — Guarded merge and exact-master validation

- [ ] Merge only through the repository's policy-approved guarded path.
- [ ] Record exact merged `master` SHA.
- [ ] Require fresh regular CI on exact merged `master`.
- [ ] Record final master CI run ID/conclusion.
- [ ] Require fresh Release Gates on exact merged `master`.
- [ ] Record final master Release Gates run ID/conclusion.
- [ ] Re-review current VEX status/expiry at final validation time.
- [ ] Do not treat merge success as validation success.
- [ ] Investigate any merged-master failure before sign-off.

---

## MCR-011 — Final evidence and completion

- [ ] Create or update a durable remediation evidence section/document.
- [ ] Record starting master `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`.
- [ ] Record final cancellation semantics.
- [ ] Record executor terminal-observation strategy.
- [ ] Record bounded-response design and exact byte ceilings.
- [ ] Record regression test matrix.
- [ ] Record unsafe-fallback audit conclusions.
- [ ] Record exact candidate SHA plus CI/Release Gates IDs and conclusions.
- [ ] Record exact merged-master SHA plus CI/Release Gates IDs and conclusions.
- [ ] Re-review every MCR checkbox against final source/tests/workflows/docs/evidence.
- [ ] Confirm no checkbox is closed solely because a commit message says so.
- [ ] Confirm no security/release gate was weakened.
- [ ] Confirm no automatic mutation retry/replay was introduced.
- [ ] Confirm no `Future exception was never retrieved` is reproducible in the supported cancellation paths.
- [ ] Confirm post-admission mutation cancellation cannot falsely imply non-execution.
- [ ] Confirm controller response ingestion is bounded during read.
- [ ] Declare the remediation complete only after exact merged-master CI and Release Gates are green.

---

## Completion declaration

Do not mark this section complete until all applicable MCR-001 through MCR-011 tasks are genuinely satisfied.

- [ ] MCP cancellation and bounding remediation is complete.
- [ ] Original MCP evidence has been reconciled without rewriting historical validation.
- [ ] The final exact merged `master` generation has passed both regular CI and Release Gates.
