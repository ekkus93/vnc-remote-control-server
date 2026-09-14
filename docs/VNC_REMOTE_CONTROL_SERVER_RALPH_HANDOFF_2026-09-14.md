# VNC Remote Control Server — Ralph Bridge Handoff

**Date:** 2026-09-14  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Required workflow for the next ChatGPT session:** **Use Ralph Bridge for GitHub access and repository modification. Do not substitute the default GitHub connector.**

## Purpose

This handoff captures the repository state after the stale PR #41 fail-closed findings were re-audited, ported selectively, qualified, merged, and documented. It is intended to let a fresh ChatGPT session resume immediately without reconstructing the MCP-013 reconciliation.

## Current implementation state

The three material fail-closed findings previously preserved only on stale PR #41 have been reconciled through fresh PR #50:

- final MCP transport dispatch now independently validates transport/host/port and cannot fall through from an invalid transport to Streamable HTTP;
- the `VRC_MCP_*` environment namespace is closed-vocabulary, so unsupported MCP-prefixed names fail startup without echoing values; and
- `McpOutcomeToolRegistrar` now prevents broad built-in exception classes from widening mutation preflight classification.

The implementation was deliberately stricter and smaller than stale PR #41. The old branch was not merged wholesale because it predates later MCP finalization and cancellation/bounding remediation work.

## PR #50 qualification and merge

Fresh implementation branch:

`ralph/mcp-013-fail-closed-reconciliation-20260914`

Final candidate:

`4d0689405f34d068fced58cd8af793007a433599`

- CI `34872815462` — **success**
- Release Gates `34872815475` — **success**

PR #50 (`mcp: harden fail-closed adapter boundaries`) was squash-merged to exact `master`:

`c3748230acc6f375ba274e999f85a17ee0be3cda`

Fresh post-merge validation on that exact generation:

- CI `34873573103` — **success**
- Release Gates `34873573179` — **success**
- Publish CI Status `34873575943` — **success**

The merged-master CI passed repository quality gates, Ruff, Pylint, mypy, Python/workflow contracts, production MCP/TigerVNC E2E, and R13 Compose integration/E2E.

## Documentation reconciliation

The current reconciliation is recorded in:

- `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_2026-09-14.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_TODO_2026-09-14.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_MCP_UNSAFE_FALLBACK_AUDIT_2026-09-11.md` — now includes a 2026-09-14 superseding addendum
- `docs/VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md` — updated so current fail-closed claims match production behavior

Historical exact-generation conclusions are preserved as historical evidence rather than rewritten. The current conclusion is that the 2026-09-12 cancellation/response-bounding findings and the 2026-09-14 fail-closed boundary findings have both been remediated under permanent regression coverage.

## Stale PR #41

PR #41 remains stale and should be treated as **superseded by PR #50**, not merged.

Its branch is:

`ralph/mcp-013-unsafe-fallback-audit-20260907`

The available Ralph Bridge tool surface in this session does not expose a pull-request-close operation, so closing PR #41 is housekeeping that may need to be done through another authorized GitHub surface. It is not an implementation blocker and does not contain production hardening still missing from `master` after PR #50.

## Branch housekeeping

Old `ralph/*` branches may still appear graph-theoretically ahead of `master` because historical PRs were squash-merged. Do not use `ahead_by > 0` alone as evidence that code remains unmerged.

Before deleting any stale branch, compare it against current `master` and account for squash merges. The Ralph Bridge surface available in this session does not expose branch deletion, so branch cleanup remains repository housekeeping.

## Dependabot work

The routine dependency-update PRs previously observed are separate from unfinished functional project work. Review and merge them independently according to current CI and compatibility; do not conflate them with MCP-013 reconciliation.

## What remains

There is no known unmerged production implementation from the PR #41 MCP fail-closed audit after PR #50.

The only explicit remaining items from this reconciliation are housekeeping:

1. close stale PR #41 as superseded by PR #50;
2. reconcile/delete obsolete `ralph/*` branches after proving they contain no unique work; and
3. continue routine Dependabot review independently.

The next session should first call `ralph_ping`, resolve current `master`, read this handoff, and verify that any later commits have not changed the conclusions above.
