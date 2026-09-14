# VNC Remote Control Server — MCP Fail-Closed Boundary Reconciliation

**Date:** 2026-09-14  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Parent audit:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_UNSAFE_FALLBACK_AUDIT_2026-09-11.md`  
**Parent TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md`

## Purpose

This document reconciles three fail-closed MCP boundary defects that were present on current `master` after the historical MCP-013 closeout and were preserved on stale PR #41. The 2026-09-11 audit remains valid as historical evidence for the source and regression matrix reviewed at that time, but its statement that no production behavior defect remained is superseded for current source by this reconciliation.

## Re-audit basis

The re-audit started from exact `master` SHA:

`4371f1f30c11c7bc72237bc9cf842ebaf04de354`

Stale PR #41 / branch `ralph/mcp-013-unsafe-fallback-audit-20260907` was compared directly against that generation. The branch was not merged wholesale because it predates later MCP-013/finalization/cancellation-bounding work and overlaps current audit/test structure.

The re-audit confirmed three still-relevant production defects.

## Reconciled findings

### F1 — Final transport dispatch did not independently fail closed

`McpConfig.load()` validated `stdio|streamable-http`, but `_run_configured_transport()` treated every non-`stdio` value as Streamable HTTP. A bypassed or directly constructed configuration object could therefore select the network transport through an implicit `else` path.

The fix centralizes transport/host/port validation in `validate_mcp_transport_configuration()`, invokes it both during environment configuration loading and immediately before `server.run()`, and uses explicit `stdio` and `streamable-http` dispatch branches. Invalid injected transport, bind host, port, and boolean-as-port values now fail before the SDK runner is called.

### F2 — Unknown `VRC_MCP_*` environment variables were silently ignored

The adapter previously read only known variables and ignored unknown MCP-prefixed names. A typo or raw-token-shaped alias could therefore be present without startup failure, creating a quiet configuration mismatch even though the value itself was not used as token ingress.

The fix defines the complete current `VRC_MCP_*` vocabulary and rejects every unknown MCP-prefixed variable before configuration parsing. Unrelated process environment variables remain allowed. Error text is value-free and preserves the existing actionable `VRC_MCP_CONTROLLER_TOKEN_FILE` guidance without naming a raw-token alias in production source.

### F3 — Dynamic mutation validation classes could widen handled exceptions

`McpOutcomeToolRegistrar` accepted caller-supplied `mutation_validation_errors` and appended them directly to its handled exception tuple. A future caller could therefore supply a broad built-in exception class and cause unrelated failures to be classified as pre-controller validation failures.

The fix is intentionally stricter than stale PR #41: registration now accepts only application-specific `ValueError` subclasses, rejecting `Exception`, `ValueError`, other built-in classes, non-`ValueError` exception classes, and invalid values. The production `McpMutationValidationError` remains accepted.

## Regression coverage

`tests/test_mcp_fail_closed_boundaries.py` permanently covers:

- unknown MCP-prefixed environment names fail closed without echoing values;
- invalid injected transport/host/port configuration never reaches `server.run()`;
- broad built-in dynamic validation exception classes are rejected; and
- an application-specific validation class remains accepted.

Existing `tests/test_mcp_unsafe_fallback_contract.py` remains authoritative for broad production catches/pass fallbacks, raw-token ingress, transport-security overrides/legacy SSE, cancellation terminal observation, and retry/backoff/sleep regressions. The stale PR #41 static test bundle was therefore not copied forward.

## Candidate history

Fresh implementation branch:

`ralph/mcp-013-fail-closed-reconciliation-20260914`

Initial candidate `45dbf782e719198a16abde16278a935da0baaf96` passed Release Gates `34871286761` but CI `34871286769` failed only because the new white-box regression triggered Pylint `protected-access`. That test-only lint issue was fixed with a scoped suppression.

Candidate `75b82b56f7a259de5db9eeedc970e55e3e3b9ad9` passed Release Gates `34872029534`; CI `34872029477` then exposed one existing config-test expectation requiring the raw-token rejection error to retain the `VRC_MCP_CONTROLLER_TOKEN_FILE` guidance. Production error wording was adjusted without weakening closed-vocabulary behavior.

Final candidate:

`4d0689405f34d068fced58cd8af793007a433599`

- CI `34872815462` — **success**
- Release Gates `34872815475` — **success**

The successful CI included Ruff, Pylint, mypy, Python/workflow contracts, production MCP/TigerVNC E2E, and R13 Compose integration/E2E.

## Merged-master validation

PR #50, `mcp: harden fail-closed adapter boundaries`, was squash-merged to exact `master`:

`c3748230acc6f375ba274e999f85a17ee0be3cda`

Fresh post-merge validation on that exact generation:

- CI `34873573103` — **success**
- Release Gates `34873573179` — **success**
- Publish CI Status `34873575943` — **success**

The merged-master CI again passed the production MCP/TigerVNC E2E and R13 Compose integration/E2E.

## Current conclusion

The three stale PR #41 fail-closed findings are now implemented and validated on current `master`. PR #41 should be treated as superseded by PR #50 rather than merged. Historical MCP-013 statements claiming no production behavior defect was found remain evidence of what the older audit concluded at that time, but they are not the current conclusion for these three boundaries.

The current implementation is fail-closed at configuration vocabulary, final transport dispatch, and dynamic mutation-validation exception registration boundaries, with permanent regressions and exact candidate/merged-master CI evidence.
