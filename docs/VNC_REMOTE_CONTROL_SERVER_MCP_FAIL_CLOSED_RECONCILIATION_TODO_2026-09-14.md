# VNC Remote Control Server — MCP Fail-Closed Reconciliation TODO

**Date:** 2026-09-14  
**Parent audit:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_UNSAFE_FALLBACK_AUDIT_2026-09-11.md`  
**Evidence:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_2026-09-14.md`

This checklist records the targeted reconciliation of the three still-relevant fail-closed findings recovered from stale PR #41. It does not reopen unrelated MCP-001 through MCP-015 functionality.

## FCR-001 — Re-audit stale PR #41 against current master

- [x] Resolve exact current `master` before comparison.
- [x] Compare stale branch `ralph/mcp-013-unsafe-fallback-audit-20260907` directly against current source.
- [x] Confirm stale PR #41 should not be merged wholesale because it predates later MCP remediation work.
- [x] Identify only production hardenings still absent from current `master`.

## FCR-002 — Fail-closed final transport dispatch

- [x] Centralize MCP transport/host/port validation.
- [x] Validate configuration during environment loading.
- [x] Revalidate transport/host/port immediately before `server.run()`.
- [x] Keep `stdio` and `streamable-http` as explicit branches.
- [x] Reject invalid injected transport before any SDK runner call.
- [x] Reject unsafe injected HTTP host/port before any SDK runner call.
- [x] Reject boolean-as-integer HTTP port values.
- [x] Add focused regression coverage.

## FCR-003 — Close the `VRC_MCP_*` environment vocabulary

- [x] Define the complete supported MCP-prefixed environment-variable set.
- [x] Reject unknown `VRC_MCP_*` names before normal configuration parsing.
- [x] Preserve unrelated process environment variables.
- [x] Ensure rejection messages never echo supplied values.
- [x] Preserve actionable `VRC_MCP_CONTROLLER_TOKEN_FILE` guidance for token-source mistakes.
- [x] Add regression coverage for typo and raw-token-shaped aliases.

## FCR-004 — Prevent dynamic exception-class widening

- [x] Validate `mutation_validation_errors` at `McpOutcomeToolRegistrar` construction.
- [x] Reject `Exception` and `ValueError` themselves.
- [x] Reject unrelated built-in exception classes.
- [x] Require application-specific `ValueError` subclasses.
- [x] Confirm the production `McpMutationValidationError` contract remains accepted.
- [x] Add focused regression coverage.

## FCR-005 — Exact candidate qualification

- [x] Do not copy stale PR #41's obsolete static audit bundle forward.
- [x] Preserve current `tests/test_mcp_unsafe_fallback_contract.py` as the static MCP-013 contract.
- [x] Fix new test lint failures without weakening repository gates.
- [x] Fix compatibility with the existing raw-token-source regression without weakening closed-vocabulary behavior.
- [x] Final candidate `4d0689405f34d068fced58cd8af793007a433599` passed CI `34872815462`.
- [x] Final candidate `4d0689405f34d068fced58cd8af793007a433599` passed Release Gates `34872815475`.

## FCR-006 — Merge and post-merge validation

- [x] Merge PR #50 through the repository's policy-approved squash path.
- [x] Record merged `master` SHA `c3748230acc6f375ba274e999f85a17ee0be3cda`.
- [x] Require fresh CI on exact merged `master`: `34873573103` — success.
- [x] Require fresh Release Gates on exact merged `master`: `34873573179` — success.
- [x] Verify Publish CI Status: `34873575943` — success.
- [x] Verify merged-master CI includes production MCP/TigerVNC E2E.
- [x] Verify merged-master CI includes R13 Compose integration/E2E.

## FCR-007 — Documentation reconciliation

- [x] Create `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_2026-09-14.md`.
- [x] Add a 2026-09-14 superseding addendum to the historical unsafe-fallback audit.
- [x] Update the MCP evidence record so current security/fail-closed claims match production behavior.
- [x] Preserve older exact-generation evidence as historical rather than rewriting its past conclusions.
- [x] Record this reconciliation checklist.

## FCR-008 — Stale PR/branch housekeeping

- [ ] Close stale PR #41 as superseded by PR #50.
- [ ] Delete obsolete `ralph/*` branches only after confirming no unique work remains.

The Ralph Bridge tool surface available in this session supports branch creation, source writes, PR creation/merge, diffs, repository state, and CI inspection, but does not expose pull-request close or branch-delete operations. FCR-008 therefore remains repository housekeeping rather than an implementation blocker.

## Completion status

All production implementation, regression, qualification, merge, post-merge validation, and documentation-reconciliation work in FCR-001 through FCR-007 is complete. FCR-008 contains only stale-PR/branch housekeeping and does not represent unmerged production functionality.
