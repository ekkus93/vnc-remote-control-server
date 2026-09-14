# VNC Remote Control Server — Post-FCR Hardening Spec

**Date:** 2026-09-14  
**Parent review:** post-FCR code review of `master` at `f5b9cf39bdcca3abc4105ba6cce40a72251d062e`  
**Companion TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_TODO_2026-09-14.md`  
**Prior closeout:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_FAIL_CLOSED_RECONCILIATION_TODO_2026-09-14.md`

## 1. Purpose

The MCP Fail-Closed Reconciliation work is complete and green on `master`. The follow-up review found no reopened MCP transport, environment-loading, or post-merge validation failures. It did identify one direct FCR-adjacent constructor-boundary gap and two broader fail-closed hardening opportunities.

This document specifies a narrow post-FCR hardening pass that fixes those findings without reopening the completed FCR scope, weakening existing gates, replacing the MCP architecture, or changing accepted production behavior beyond stricter validation of invalid inputs.

## 2. Scope

This spec covers three hardening areas:

1. Strict runtime validation for `McpOutcomeToolRegistrar`'s `mutation_validation_errors` container.
2. Closed-vocabulary validation for controller-side `VRC_*` environment variables.
3. Fail-closed validation for public Python client timeout values.

The implementation must preserve all current FCR guarantees:

- MCP transport dispatch remains explicit and fail-closed.
- Unknown `VRC_MCP_*` variables remain rejected.
- Controller credentials remain file-only.
- Mutation execution remains disabled by default.
- No retry/replay fallback is introduced for mutation outcomes.
- No broad `Exception` or `BaseException` catch-all is introduced.
- Diagnostic messages must not echo secret values or arbitrary supplied environment values.

## 3. Non-goals

This pass must not:

- change the supported MCP transports;
- add legacy SSE or transport-security override paths;
- add raw secret environment-variable ingress;
- weaken `tests/test_mcp_unsafe_fallback_contract.py`;
- remove or skip current CI/Release gates;
- add best-effort fallback behavior after validation failures;
- treat historical TODO files as reopened backlog;
- require manual production hardware beyond the existing CI/E2E infrastructure.

## 4. Finding PFH-001 — Strict `mutation_validation_errors` container validation

### 4.1 Problem

`McpOutcomeToolRegistrar.__init__()` validates each supplied exception class but currently assumes the container itself is a tuple. A caller can pass a list containing otherwise valid application-specific `ValueError` subclasses. Construction succeeds, but later `isinstance(error, self._mutation_validation_errors)` can raise `TypeError` because the second argument is not a tuple of types.

The current production call site passes a tuple and is safe, but the registrar boundary should fail closed at construction time for invalid containers.

### 4.2 Required behavior

`McpOutcomeToolRegistrar` must reject `mutation_validation_errors` unless it is an actual tuple.

Accepted examples:

- `(McpMutationValidationError,)`
- a tuple containing only application-specific subclasses of `ValueError`

Rejected examples:

- `list[type[Exception]]`
- generator or iterator objects
- string or bytes values
- arbitrary iterables
- `Exception`
- `BaseException`
- `ValueError` itself
- unrelated built-in exception classes such as `RuntimeError`, `TypeError`, or `OSError`
- non-type values

The rejection type must remain `McpOutcomeRegistrationError`.

### 4.3 Diagnostic requirements

The error message should describe the contract without echoing arbitrary object representations. A suitable message is:

```text
mutation validation errors must be a tuple of application-specific ValueError subclasses
```

### 4.4 Tests

Add or update focused Python tests to cover:

- list of valid application-specific classes is rejected;
- generator yielding valid classes is rejected;
- string or bytes values are rejected;
- tuple with non-type element is rejected;
- tuple with built-in `ValueError` is rejected;
- tuple with unrelated built-in exception class is rejected;
- tuple with `McpMutationValidationError` remains accepted;
- mutation validation errors are still classified conservatively and not retried.

## 5. Finding PFH-002 — Controller-side `VRC_*` closed vocabulary

### 5.1 Problem

FCR-003 closed the MCP-specific `VRC_MCP_*` namespace. The Rust controller configuration still reads known controller environment variables but does not appear to reject unknown controller-side `VRC_*` variables. Existing tests prove raw secret-shaped variables are ignored, but silent ignore behavior can hide operator typos and mistaken raw-secret configuration.

The controller should match the fail-closed posture used by the MCP loader: supported `VRC_*` variables should be explicit, and unknown names should be rejected before startup proceeds.

### 5.2 Required behavior

Controller configuration loading must reject unknown `VRC_*` environment-variable names before accepting configuration.

The supported vocabulary must be defined in one place and must include every controller-side `VRC_*` variable intentionally supported by the current implementation.

The validation must preserve unrelated process environment variables. Non-`VRC_*` variables must not affect controller configuration loading.

### 5.3 Raw-secret alias behavior

Raw secret-shaped environment names that are not supported file-based sources must fail closed with actionable diagnostics. Examples include:

- `VRC_API_TOKEN`
- `VRC_VNC_PASSWORD`

If the supported credential sources remain file-only, diagnostics should point operators to the supported file variables without echoing either the unsupported variable's value or the loaded file contents.

### 5.4 Diagnostic requirements

Diagnostics must:

- name the unsupported variable name;
- never echo the supplied value;
- identify that only documented `VRC_*` controller variables are accepted;
- provide file-source guidance for mistaken raw-secret aliases.

### 5.5 Tests

Add Rust configuration tests covering:

- unknown `VRC_*` variable fails closed;
- unrelated non-`VRC_*` variable is preserved/ignored;
- raw API-token-shaped alias fails closed without value echo;
- raw VNC-password-shaped alias fails closed without value echo;
- supported file-based secret variables still work;
- supported non-secret controller variables still work;
- empty or absent optional variables preserve current defaults.

If controller config has multiple loading entry points, every public loading entry point must receive the same validation or delegate to a single validated path.

## 6. Finding PFH-003 — Public Python client timeout validation

### 6.1 Problem

The public Python client currently checks `timeout <= 0` and then stores `float(timeout)`. This is too trusting for a public boundary. It may accept boolean values and nonfinite floats, and it can produce inconsistent exception behavior for strings or arbitrary objects.

The MCP wrapper already performs stricter timeout validation, so this is not an MCP-path vulnerability. The public client should still fail closed and provide consistent errors.

### 6.2 Required behavior

The public Python client must accept positive finite numeric timeout values and reject everything else.

Accepted examples:

- positive `int`
- positive `float`

Rejected examples:

- `True` and `False`
- `0`
- negative numbers
- `float("nan")`
- positive or negative infinity
- strings
- bytes
- `None`
- arbitrary nonnumeric objects

### 6.3 Diagnostic requirements

Use a stable `ValueError` for invalid timeout values with a message that does not depend on the offending object's representation. A suitable message is:

```text
timeout must be a positive finite number
```

### 6.4 Tests

Add Python client tests covering the accepted and rejected examples above. The tests should assert stable exception types and messages for invalid values.

## 7. Cross-cutting validation requirements

The implementation must pass, at minimum:

- Rust formatting and Clippy with warnings denied;
- Rust unit tests;
- Python compile validation;
- Ruff;
- Pylint;
- mypy;
- Python unit and workflow contract tests;
- shell syntax checks;
- production MCP/TigerVNC E2E;
- R13 Compose integration/E2E;
- Release native sanitizer and Miri gates;
- Release Python MCP dependency/license gate;
- Release image vulnerability/VEX/SBOM gates;
- Release static and supply-chain gates;
- Publish CI Status.

No failing or skipped required gate may be accepted as qualification evidence.

## 8. Acceptance criteria

This hardening pass is complete only when:

1. PFH-001 through PFH-003 are implemented with focused regression coverage.
2. The companion TODO is updated with exact candidate and merged-master evidence.
3. A PR containing the changes passes exact-head CI and Release Gates.
4. The PR is merged through the repository's approved merge path.
5. The resulting `master` SHA passes fresh CI, Release Gates, and Publish CI Status.
6. The TODO has no unchecked implementation, test, evidence, or qualification tasks.

## 9. Review focus

Reviewers should pay special attention to:

- accidental fallback paths introduced during validation;
- broad exception handling added to smooth over validation failures;
- diagnostics that leak supplied environment values;
- new raw-secret environment-variable ingress;
- weakening of existing MCP static safety contracts;
- tests that assert only happy paths without proving rejection behavior.
