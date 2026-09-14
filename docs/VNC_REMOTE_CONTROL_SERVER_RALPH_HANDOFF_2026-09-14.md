# VNC Remote Control Server — Ralph Bridge Handoff

**Date:** 2026-09-14  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Required workflow for the next ChatGPT session:** **Use Ralph Bridge for GitHub access and repository modification. Do not substitute the default GitHub connector.**

## Purpose

This handoff captures the repository state at the end of the current session and the one material code-hardening item that still appears to need reconciliation. It is intended to let a fresh ChatGPT session resume immediately with Ralph Bridge without reconstructing the audit from scratch.

## Current `master`

At handoff time:

- `master` SHA: `52b1b56d3a7c381f0958633ab0cdfb4ead8f0a3a`
- Latest commit before this handoff: `docs: reconcile remediated MCP task status (#49)`
- CI on that SHA was green:
  - CI run `34721735953` — **success**
  - Release Gates run `34721735961` — **success**

The handoff commit itself will advance `master`; the next session should first call Ralph Bridge, read this file from the new `master`, and verify the post-handoff CI state.

## Overall project state

The main MCP implementation and remediation sequence is substantially closed out. The following user-created work was merged into `master`:

- PR #36 — MCP-008 stdio transport
- PR #37 — MCP-009 Streamable HTTP
- PR #38 — MCP-010 living docs/security
- PR #39 — MCP-011 real E2E
- PR #40 — MCP-012 CI and supply-chain integration
- PR #42 — MCP-013 finalization
- PR #43 — MCP-014 / R13 restart race
- PR #44 — MCP-015 final evidence
- PR #45 — closeout evidence correction
- PR #46 — cancellation/bounding remediation
- PR #47 — remediation final evidence
- PR #48 — post-remediation evidence reconciliation
- PR #49 — original MCP TODO reconciliation

Most old `ralph/*` branches are therefore merged or superseded. Some appear graph-theoretically ahead of `master` because the corresponding PRs were squash-merged; do **not** interpret `ahead_by > 0` by itself as evidence that code remains unmerged.

## Material unresolved item: stale PR #41 contains hardening not present on `master`

PR #41 remains open:

- URL: <https://github.com/ekkus93/vnc-remote-control-server/pull/41>
- Title: `audit: harden MCP unsafe-fallback boundaries`
- Branch: `ralph/mcp-013-unsafe-fallback-audit-20260907`
- Head SHA: `d8779130bdb40b79cc319f1041d4ccf3b1bf3b56`
- State: open, mergeable, not merged
- Scope: 1 commit, 5 files, approximately +522/-16

A direct comparison against the current master snapshot found that three production hardenings proposed in PR #41 are **not present** on current `master`:

### 1. Fail-closed MCP transport dispatch

Current `python/src/vnc_remote_control/mcp_server.py` effectively does:

```python
if config.transport == "stdio":
    server.run(transport="stdio")
    return
server.run(
    transport="streamable-http",
    host=config.http_host,
    port=config.http_port,
    stateless_http=True,
)
```

Normal configuration loading validates the transport, but `McpConfig` is directly constructible. An invalid or bypassed internal `config.transport` therefore falls through to Streamable HTTP rather than being rejected at the final dispatch boundary.

PR #41 explicitly revalidated transport/HTTP values immediately before `server.run()` and made `streamable-http` an explicit branch. This hardening should be reconsidered and likely ported.

### 2. Closed vocabulary for `VRC_MCP_*` environment variables

Current `python/src/vnc_remote_control/mcp_config.py` does not reject unknown MCP-prefixed environment variables. PR #41 added rejection for unrecognized `VRC_MCP_*` keys, including raw-token-shaped names such as `VRC_MCP_CONTROLLER_TOKEN`, while leaving unrelated environment variables alone and avoiding secret-value disclosure.

This is a useful fail-closed configuration boundary and should be reconsidered and likely ported.

### 3. Prevent broad exception-class widening in `McpOutcomeToolRegistrar`

Current `python/src/vnc_remote_control/mcp_outcomes.py` accepts dynamically supplied `mutation_validation_errors` and adds them to the handled exception tuple without rejecting broad classes. A future caller could therefore widen handling to something as broad as `Exception` even though static audits reject literal broad catches.

PR #41 added constructor validation to reject broad/invalid exception classes. This should be reconsidered and likely ported.

## Why PR #41 should not simply be merged as-is

PR #41 predates the later MCP-013/finalization/remediation work, and its audit/test files overlap work that subsequently landed through PRs #42–#49. The safer approach is **not** to merge the stale branch wholesale.

Its CI history also shows that the implementation was not failing functionally:

- Release Gates `34152505176` — **success**
- CI `34152505084` — **failed only at Python Ruff lint**

The lint failure was in the new test code and consisted of two Ruff `UP038` findings for tuple-form `isinstance` checks. The real MCP/TigerVNC E2E and other substantive jobs passed.

## Recommended next Ralph Loop

From a fresh Ralph Bridge-enabled session:

1. Call `ralph_ping` first and confirm access to `ekkus93/vnc-remote-control-server`.
2. Fetch current `master` and read this handoff file.
3. Verify the handoff commit and current CI/Release Gates.
4. Re-audit the three PR #41 hardenings against current `master` rather than trusting this handoff blindly.
5. Create a **fresh branch from current `master`**.
6. Port only the still-relevant production hardenings from PR #41.
7. Adapt/add regression tests to the current MCP-013 audit/test structure.
8. Fix the historical Ruff `UP038` style problem rather than copying it forward.
9. Run the full current CI and Release Gates.
10. If green, merge the fresh PR into `master`.
11. Close PR #41 as superseded with a link to the replacement PR/commit.
12. Reconcile and delete obsolete `ralph/*` branches after proving they contain no unique work that still matters.

## Branch inventory at the prior audit

There were 25 branches total before this handoff: `master`, 15 `ralph/*` branches, and 9 Dependabot branches.

Ralph branches observed:

- `ralph/mcp-008-stdio-transport-20260906-copy`
- `ralph/mcp-008-stdio-transport-20260906`
- `ralph/mcp-009-streamable-http-20260906`
- `ralph/mcp-010-living-docs-security-20260906`
- `ralph/mcp-011-real-e2e-20260906`
- `ralph/mcp-012-ci-supply-chain-20260907`
- `ralph/mcp-013-finalization`
- `ralph/mcp-013-unsafe-fallback-audit-20260907`
- `ralph/mcp-014-r13-restart-race`
- `ralph/mcp-015-final-evidence`
- `ralph/mcp-closeout-evidence-correction`
- `ralph/mcp-original-todo-reconcile`
- `ralph/mcp-post-mcr-evidence-reconciliation`
- `ralph/mcr-cancellation-bounding-remediation`
- `ralph/mcr-final-evidence-closeout`

`ralph/mcp-008-stdio-transport-20260906-copy` was confirmed fully behind `master` with no unique commits. For the others, account for squash merges before concluding that apparent graph divergence means unmerged code.

## Dependabot work

Nine routine dependency-update PRs were open (#10–#18). These are separate from unfinished functional project work:

- Debian controller image digest
- Debian desktop image digest
- Tokio 1.53.1
- `actions/checkout` 7.0.1
- `http-body-util` 0.1.4
- `tower` 0.5.3
- `tracing` 0.1.44
- `hyper` 1.11.0
- Rust 1.98.0 slim-trixie image

Review/merge these independently according to CI and compatibility; do not conflate them with the PR #41 hardening reconciliation.

## Documentation consistency issue

Current MCP evidence/TODO documentation marks MCP-013 complete and states that no production behavior defect was found. That conclusion should be revisited if any of the three PR #41 hardenings are accepted as necessary. If production changes are made, update the relevant evidence/TODO documentation so the recorded security/fail-closed claims match the actual implementation.

## Important execution instruction for the next session

The user specifically wants the Ralph Bridge workflow. **Do not silently fall back to a different GitHub tool.** If Ralph Bridge is not exposed in the new session, say so immediately before modifying the repository.
