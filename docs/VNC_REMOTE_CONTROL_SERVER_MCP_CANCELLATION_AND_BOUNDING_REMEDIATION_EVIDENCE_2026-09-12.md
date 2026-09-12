# VNC Remote Control Server — MCP Cancellation and Bounding Remediation Evidence

**Date:** 2026-09-12  
**Starting master:** `7b69ad82a6939c9619d8b8a0b9146c005bf6889e`  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_SPEC_2026-09-12.md`  
**TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_CANCELLATION_AND_BOUNDING_REMEDIATION_TODO_2026-09-12.md`

## Findings

The review reproduced three related weaknesses on the starting generation: post-admission mutation cancellation could outlive its waiter without a truthful MCP outcome, a later worker exception could reach asyncio as `Future exception was never retrieved`, and controller HTTP response bodies were not bounded during ingestion.

## Remediation design

- Executor admission remains synchronous and fail-fast before the first await.
- An admitted worker retains its capacity slot until the synchronous operation exits.
- If its original waiter is cancelled while the worker is still active, terminal-observation ownership transfers to a non-logging done callback that consumes the eventual result/exception.
- Read-only task cancellation remains cancellation.
- Mutation cancellation observed after admission is returned conservatively as `mutation_outcome_unknown`, `command_id=null`, `outcome=unknown`, `retry_safe=false`; no retry or replay occurs.
- A worker that wins the cancellation race with a terminal result is classified normally so real command/outcome metadata is preserved.
- Shared response limits bound controller reads during ingestion: JSON 8 MiB, screenshot PNG 128 MiB, metrics/text 1 MiB, HTTP error bodies 1 MiB. `Content-Length` can reject early but cannot bypass the limit when absent or dishonest.

## Permanent regression coverage

- `tests/test_mcp_execution.py`
- `tests/test_mcp_cancellation_contract.py`
- `tests/test_python_response_bounds.py`
- `tests/test_mcp_unsafe_fallback_contract.py`
- `tests/test_mcp_documentation_contract.py`

Candidate and merged-master SHA/workflow evidence will be recorded after the corresponding exact-generation validations complete.
