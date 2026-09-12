# VNC Remote Control Server — MCP Cancellation and Bounding Remediation Evidence

**Date:** 2026-09-12  
**Starting master:** `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_SPEC_2026-09-12.md`  
**TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_TODO_2026-09-12.md`

## 1. Findings

The 2026-09-12 review reproduced three related defects on the starting generation:

1. post-admission mutation cancellation could outlive its original waiter without a truthful mutation outcome;
2. a worker that later failed could surface through asyncio as `Future exception was never retrieved`; and
3. controller HTTP response bodies were not bounded during ingestion, so screenshot/JSON/text checks happened only after unrestricted materialization.

The findings did not invalidate the historical MCP closeout runs. They exposed cases absent from that regression matrix.

## 2. Final remediation design

### Cancellation ownership

Executor admission remains synchronous and fail-fast before the first await. An admitted worker retains its capacity slot until the synchronous controller call exits.

If its original waiter is cancelled while the worker is still active, terminal-observation ownership transfers to a fixed non-logging done callback. The callback consumes the eventual terminal exception/result only to prevent an abandoned-future diagnostic; it does not replay the call and does not log exception payload text.

Read-only task cancellation remains cancellation after ownership transfer.

Mutation cancellation observed after admission is conservatively returned as:

```text
kind = mutation_outcome_unknown
command_id = null
outcome = unknown
retry_safe = false
```

No mutation is automatically retried, replayed, or poll-and-replayed. A real controller command ID remains authoritative when one is actually available through the existing controller outcome path.

### Bounded response ingestion

The typed Python client now bounds body reads during ingestion using finite ceilings and limit-plus-one probing. `Content-Length` can reject an oversized response early but cannot bypass the bound when absent or dishonest.

Final reviewed wire ceilings:

- JSON/controller responses: 8 MiB;
- screenshot PNG responses: 128 MiB;
- metrics/text responses: 1 MiB;
- HTTP error response bodies: 1 MiB.

The existing screenshot PNG structural, CRC, IHDR, dimension, decompression, framebuffer, and IEND validation remains a second validation layer after the transport bound.

## 3. Permanent regression coverage

Permanent coverage includes:

- `tests/test_mcp_execution.py` — cancellation ownership, capacity, completion/failure/shutdown races;
- `tests/test_mcp_cancellation_contract.py` — registered read/mutation cancellation, exactly-one forwarding, unknown outcome, sensitive payload suppression;
- `tests/test_python_response_bounds.py` — exact limit, over-limit, absent/dishonest `Content-Length`, JSON/screenshot/metrics/error bodies;
- `tests/test_mcp_unsafe_fallback_contract.py` — cancellation/future ownership static contract plus existing no-retry/fail-closed checks;
- `tests/test_mcp_documentation_contract.py` — living documentation remains synchronized with the implementation;
- existing official-SDK stdio/Streamable HTTP acceptance and production MCP/controller/TigerVNC E2E.

## 4. Unsafe-fallback and silent-failure audit

The audit was extended to `asyncio.shield`, `asyncio.wrap_future`, cancellation propagation, future ownership, done callbacks, shutdown races, event-loop exception diagnostics, and response-body ingestion.

No automatic mutation retry/replay was added. No broad production success fallback was introduced. The intentional abandoned-future callback consumes terminal exception state without emitting payload-bearing diagnostics. Sensitive keyboard text, clipboard content, screenshot bytes/base64, Authorization values, controller token bytes, raw controller bodies, and VNC credentials remain excluded from production diagnostic output.

## 5. Candidate failure investigation history

The Ralph loop did not rerun deterministic failures blindly. It corrected, in sequence:

- Ruff B023 late-bound loop captures in cancellation regressions;
- Pylint protocol/test diagnostics without changing global lint policy;
- mypy typing of the asyncio exception callback and intentionally partial mutation fake;
- a living-document contract expecting the literal `legacy SSE` wording; and
- exact VEX drift reported as stale tuples.

The VEX failure contained no unreviewed CRITICAL findings. The verifier showed that previously expected desktop Perl/GLib tuples were no longer present in Trivy's current CRITICAL set while controller Perl and desktop libxml2 findings remained. The VEX inventory was therefore narrowed to the observed exact tuples rather than bypassing the gate or claiming vulnerable Debian source versions were fixed. The review window was refreshed to `reviewed_at: 2026-09-12`, `expires_at: 2026-10-12`, tracking issue `7`.

## 6. Exact implementation candidate validation

Final implementation candidate:

`1cd71c70fc7c63c7ef0c691e2100ab677ca19071`

Fresh pull-request workflows on that exact SHA:

- CI `34710744120`: **success**
- Release Gates `34710744121`: **success**

The exact candidate passed:

- Rust formatting, Clippy, Rust tests, and documentation;
- Python compile, Ruff, Pylint, mypy, and full Python/workflow contract tests;
- core Python installation without MCP;
- cancellation and bounded-response regressions;
- stdio and Streamable HTTP acceptance;
- WorkerHandle/native/HTTP/Compose smoke paths;
- production MCP -> controller -> TigerVNC E2E;
- R13 integration;
- Python MCP dependency/license closure;
- Gitleaks, shell/action/Docker/Compose policy, cargo-deny, auditable binary checks;
- ASan, TSan, and Miri;
- Trivy vulnerability inventory, CycloneDX SBOM generation, and exact CRITICAL VEX enforcement.

## 7. Guarded merge and exact merged-master validation

PR #46 was squash-merged through the repository's guarded merge path.

Exact merged implementation master:

`9a0a6f99ce704e5eac0eba10409b6e2746fe28b0`

Fresh push validation on that exact SHA:

- CI `34711065779`: **success**
- Release Gates `34711065829`: **success**
- Publish CI Status `34711069866`: **success**

The post-merge Release Gates again passed the refreshed exact CRITICAL VEX policy. No release/security gate was weakened for sign-off.

## 8. Completion conclusion

MCR-001 through MCR-011 have been reconciled against source, permanent tests, living documentation, audit records, and exact-generation GitHub Actions evidence.

The runtime remediation is complete:

- admitted executor futures retain terminal-observation ownership;
- supported cancellation paths do not leave unobserved worker exceptions;
- post-admission mutation cancellation cannot imply safe replay or proven non-execution;
- mutation forwarding remains exactly once with no adapter replay loop;
- controller success and error bodies are bounded while being read;
- oversized responses fail closed without echoing response payloads;
- the original MCP closeout remains historical evidence rather than being rewritten.

## 9. Documentation-closeout validation model

This evidence file is committed after the validated implementation merge so it can record the candidate and merged implementation workflow IDs above. A Git commit cannot also contain the future workflow IDs that will validate that same commit after it exists.

Therefore the documentation-only closeout follows the non-recursive evidence model already used by this repository:

1. this closeout candidate must pass regular CI and Release Gates before merge;
2. the resulting documentation-closed `master` must pass fresh regular CI and Release Gates;
3. those later results are external validation of this evidence record and are not written back into the same record merely to create another SHA that would need another self-recording cycle.
