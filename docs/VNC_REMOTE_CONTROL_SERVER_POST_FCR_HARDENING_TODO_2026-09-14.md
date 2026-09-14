# VNC Remote Control Server — Post-FCR Hardening TODO

**Date:** 2026-09-14
**Spec:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_SPEC_2026-09-14.md`
**Parent review:** post-FCR code review of `master` at `f5b9cf39bdcca3abc4105ba6cce40a72251d062e`
**Prior closeout:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_TODO_2026-09-14.md`

This checklist tracks a narrow hardening follow-up after the completed MCP Fail-Closed Reconciliation. It does not reopen FCR-001 through FCR-008. The goal is to fix one direct FCR-adjacent constructor-boundary gap and two broader fail-closed validation opportunities found during review.

## PFH-001 — Strict `mutation_validation_errors` container validation

- [x] Require `mutation_validation_errors` to be an actual tuple at `McpOutcomeToolRegistrar` construction.
- [x] Reject lists, generators, strings, bytes, and arbitrary iterables even when they contain otherwise valid exception classes.
- [x] Keep rejecting `Exception`, `BaseException`, `ValueError`, unrelated built-in exception classes, and non-type values.
- [x] Preserve acceptance of `McpMutationValidationError` and other application-specific `ValueError` subclasses when supplied in a tuple.
- [x] Preserve conservative mutation error classification without adding retry/replay fallback.
- [x] Add focused Python regression tests for invalid container types.
- [x] Add focused Python regression tests proving the valid tuple contract still works.

## PFH-002 — Controller-side `VRC_*` closed-vocabulary hardening

- [x] Identify every currently supported controller-side `VRC_*` environment variable.
- [x] Define the supported controller `VRC_*` vocabulary in one place.
- [x] Reject unknown controller-side `VRC_*` variables before startup accepts configuration.
- [x] Preserve unrelated non-`VRC_*` process environment variables.
- [x] Reject raw secret-shaped aliases such as `VRC_API_TOKEN` and `VRC_VNC_PASSWORD` when the supported source remains file-based.
- [x] Ensure diagnostics name unsupported variables but never echo supplied values or secret file contents.
- [x] Preserve supported file-based secret loading behavior.
- [x] Preserve supported non-secret controller configuration behavior and defaults.
- [x] Add Rust config tests for unknown controller `VRC_*` names.
- [x] Add Rust config tests for raw secret-shaped aliases and value non-echo behavior.
- [x] Add Rust config tests proving supported variables still work.

## PFH-003 — Public Python client timeout validation

- [x] Replace the public client timeout boundary with explicit positive finite numeric validation.
- [x] Reject `bool` values even though `bool` is an `int` subclass in Python.
- [x] Reject zero, negative numbers, NaN, and infinity.
- [x] Reject strings, bytes, `None`, and arbitrary nonnumeric objects with stable `ValueError` behavior.
- [x] Preserve accepted positive `int` and positive `float` timeout values.
- [x] Add Python client tests for accepted timeout values.
- [x] Add Python client tests for rejected timeout values and stable diagnostics.

## PFH-004 — Static safety contract preservation

- [x] Preserve `tests/test_mcp_unsafe_fallback_contract.py` without weakening broad-exception, raw-token, retry, transport, SSE, or silent-fallback checks.
- [x] Confirm no new broad `except Exception` or `except BaseException` handling is introduced in MCP mutation/config paths.
- [x] Confirm no new retry, replay, sleep, backoff, or best-effort fallback path is introduced for mutation outcomes.
- [x] Confirm no raw secret environment-variable ingress is introduced.
- [x] Confirm validation errors fail closed rather than being downgraded to warnings or defaults.

## PFH-005 — Local and exact-candidate qualification

- [x] Run focused local validation for changed Python tests where possible.
  - Local targeted Python validation passed: `tests.test_post_fcr_hardening`, `tests.test_mcp_unsafe_fallback_contract`, `tests.test_mcp_outcomes`, and `tests.test_python_client`.
- [x] Run focused local validation for changed Rust tests where possible.
  - Local sandbox has no `cargo`; changed Rust config tests are covered by exact PR-head CI and Release Gates below.
- [ ] Run repository formatting/lint/type/unit gates through CI.
- [ ] Require exact PR-head CI success.
- [ ] Require exact PR-head Release Gates success.
- [ ] Record exact PR-head SHA and CI run IDs in this TODO.

## PFH-006 — Merge and post-merge validation

- [ ] Merge through the repository's approved merge path only after exact candidate qualification is green.
- [ ] Record merged `master` SHA in this TODO.
- [ ] Require fresh CI success on the exact merged `master` SHA.
- [ ] Require fresh Release Gates success on the exact merged `master` SHA.
- [ ] Require fresh Publish CI Status success on the exact merged `master` SHA.
- [ ] Verify merged-master CI includes production MCP/TigerVNC E2E.
- [ ] Verify merged-master CI includes R13 Compose integration/E2E.

## Completion status

PFH-001 through PFH-004 are implemented locally. PFH-005 and PFH-006 remain open for exact PR-head qualification, merge, post-merge validation, and final evidence reconciliation.
