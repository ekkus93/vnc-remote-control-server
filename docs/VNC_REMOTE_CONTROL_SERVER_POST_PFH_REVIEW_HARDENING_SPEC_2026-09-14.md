# VNC Remote Control Server — Post-PFH Review Hardening Specification

**Date:** 2026-09-14  
**Review base:** `master` at `6948ce0c522aa3e5ffbba9e402250e2f78457ac8`  
**Prior hardening spec:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_SPEC_2026-09-14.md`  
**Prior hardening TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_TODO_2026-09-14.md`

## 1. Purpose

This specification defines a narrow follow-up hardening pass after the completed Post-FCR Hardening (PFH) work. A fresh code review of the final PFH `master` identified one reproducible public-client bug, two controller configuration contract gaps, one specification inconsistency, and one adjacent public Python API robustness issue.

This work does **not** reopen PFH-001 through PFH-006. Those tasks remain historically complete for the implementation and evidence they recorded. The purpose of this pass is to close newly discovered gaps while preserving the security properties established by FCR and PFH.

The implementation MUST remain fail closed. No task in this specification authorizes compatibility fallbacks, silent ignore behavior, mutation retry/replay, raw secret environment ingress, transport-security weakening, or broad catch-all exception handling.

## 2. Review findings to remediate

### 2.1 Public Python client timeout conversion can escape as `OverflowError`

The public client timeout validator currently accepts `int | float`, converts the value with `float(timeout)`, and then checks `math.isfinite()` and positivity.

A sufficiently large positive integer such as `10**400` raises `OverflowError` during `float()` conversion before the stable validation error policy is reached. This violates the intended public-boundary behavior: invalid timeout inputs should be rejected deterministically with the documented validation exception rather than leaking implementation-specific conversion exceptions.

The earlier PFH wording that all positive integers are accepted is also too broad. Only positive finite numeric timeout values representable by the underlying timeout implementation can be accepted.

### 2.2 Controller `VRC_*` rejection diagnostics are safe but incomplete

The controller now rejects unknown `VRC_*` environment variable names before production startup and does not echo supplied values. That security behavior is correct.

However, the companion PFH specification required operator guidance that the current diagnostic does not provide. The diagnostic should make clear that only documented controller `VRC_*` variables are accepted. When the rejected name is a known raw-secret-shaped alias such as `VRC_API_TOKEN` or `VRC_VNC_PASSWORD`, the diagnostic should point operators toward the supported file-backed variables without disclosing secret values or file contents.

### 2.3 Closed controller environment vocabulary is not enforced by every public loader

The production controller entry point validates the controller `VRC_*` namespace before calling lower-level loaders. However, `RuntimeSettings::load()` remains a public loading entry point and can be invoked directly without the closed-vocabulary validation.

The intended contract is that every public controller configuration-loading path either performs the same namespace validation itself or delegates through one single validated path. Public callers must not be able to bypass the unknown-`VRC_*` rejection simply by selecting a lower-level public loader.

### 2.4 PFH specification wording for empty environment values conflicts with actual fail-closed behavior

Existing controller parsing distinguishes an absent environment variable from a present-but-empty value. Absence uses the configured default. A present empty value is treated as explicit input and generally fails validation.

That existing behavior is safer and should be preserved. The prior PFH specification language implying that both empty and absent optional values preserve defaults is inaccurate and must be reconciled. This follow-up must not introduce empty-string-as-absence fallback semantics.

### 2.5 Adjacent public Python constructor boundaries leak incidental exceptions

The public Python client still relies on downstream operations to reject some malformed constructor argument types. Examples include non-string `token` values producing incidental `TypeError` behavior and non-string `base_url` values producing downstream URL-parsing exceptions such as `AttributeError`.

These failures are fail closed, but they are not deterministic public API validation. Constructor boundaries should explicitly validate these arguments and return stable, documented validation errors without logging or echoing sensitive values.

## 3. Security and behavioral invariants

The following invariants MUST remain true throughout this work:

1. MCP mutation outcomes remain conservative and non-retryable when execution state is ambiguous.
2. No mutation retry, replay, sleep, backoff, or best-effort fallback is introduced.
3. No raw controller or MCP secret may be accepted directly through environment variables.
4. Controller and MCP secrets remain file-backed where currently required.
5. Unsupported `VRC_*` and `VRC_MCP_*` configuration names fail closed rather than being silently ignored.
6. Error messages may identify an unsupported variable name but MUST NOT echo its supplied value or secret-file contents.
7. No broad `except Exception` or `except BaseException` handling may be added to the MCP mutation/configuration paths merely to make validation pass.
8. Official SDK transport security behavior remains intact; no legacy SSE or transport-security bypass is introduced.
9. Existing unsafe-fallback static contract tests MUST NOT be weakened, deleted, bypassed, or rewritten to permit behavior they currently forbid.
10. Existing CI, Release Gates, production MCP/TigerVNC E2E, and R13 Compose integration coverage remain required.

## 4. PRH-001 — Harden public client timeout conversion

### 4.1 Required behavior

The public `VncClient` timeout boundary MUST accept only positive finite numeric values that can be converted to the internal timeout representation.

It MUST:

- accept ordinary positive `int` values;
- accept ordinary positive finite `float` values;
- reject `bool` even though `bool` subclasses `int`;
- reject zero and negative values;
- reject NaN;
- reject positive and negative infinity;
- reject strings, bytes, `None`, and arbitrary nonnumeric objects;
- reject numeric inputs whose conversion to the internal timeout representation overflows or otherwise cannot produce a finite usable value;
- normalize every rejected timeout case to one stable `ValueError` contract.

The preferred diagnostic remains:

`timeout must be a positive finite number`

Conversion-specific exceptions such as `OverflowError`, `TypeError`, or `ValueError` from `float()` MUST NOT escape the public validator when they represent invalid timeout input.

### 4.2 Implementation constraints

The implementation SHOULD keep timeout validation in one helper rather than duplicating validation in constructor and request code. It SHOULD catch only the narrow conversion failures required to normalize invalid input; it MUST NOT introduce a broad `except Exception` fallback.

### 4.3 Regression coverage

Tests MUST include at least:

- accepted positive integer;
- accepted positive float;
- rejected `True` and `False`;
- rejected zero;
- rejected negative number;
- rejected NaN;
- rejected `inf` and `-inf`;
- rejected string;
- rejected bytes;
- rejected `None`;
- rejected arbitrary object;
- rejected huge integer such as `10**400` with the same stable `ValueError` and message.

## 5. PRH-002 — Complete controller `VRC_*` namespace hardening

### 5.1 Single authoritative vocabulary

All supported controller-side `VRC_*` environment variable names MUST be defined from one authoritative vocabulary used by namespace validation. Adding a supported controller environment variable in the future must require updating that authoritative vocabulary in the same change.

Where individual parsers still name variables directly, tests or structure MUST prevent vocabulary/parser drift.

### 5.2 Every public loading entry point must validate

Every public controller configuration-loading entry point that reads controller `VRC_*` environment state MUST either:

1. perform the closed-vocabulary validation before reading settings; or
2. delegate to a single public validated configuration loader.

Direct use of `RuntimeSettings::load()` MUST NOT permit an unknown `VRC_*` variable to be silently ignored.

The implementation may choose to make lower-level loaders non-public if they are implementation details, provided existing intended public API compatibility is considered and tests prove the supported loading path remains intact.

### 5.3 Diagnostics

Unknown controller `VRC_*` variables MUST fail startup/configuration loading with diagnostics that:

- name the unsupported variable;
- do not echo the supplied value;
- do not read or echo secret file contents;
- state that only documented controller `VRC_*` variables are accepted, or equivalent clear guidance.

Known raw-secret-shaped aliases require additional guidance:

- `VRC_API_TOKEN` should direct operators to `VRC_API_TOKEN_FILE`;
- `VRC_VNC_PASSWORD` should direct operators to `VRC_VNC_PASSWORD_FILE`.

The implementation MAY use dedicated error variants for raw-secret aliases or a safe mapping from rejected name to guidance. It MUST NOT construct diagnostics from arbitrary supplied values.

### 5.4 Non-controller environment variables

Unrelated process environment variables that do not begin with the controller `VRC_*` namespace MUST remain unaffected.

### 5.5 Empty-value semantics

The intended controller environment semantics are:

- **absent optional variable:** preserve current default behavior;
- **present empty variable:** treat as explicitly supplied input and validate it normally; do not silently convert it to absence/default unless an existing variable contract explicitly documents empty as valid.

This preserves fail-closed behavior and supersedes any prior PFH wording that implied generic present-empty fallback-to-default behavior.

### 5.6 Regression coverage

Rust tests MUST prove:

- unknown `VRC_*` fails through the top-level controller loader;
- unknown `VRC_*` also fails through every remaining public lower-level loader that can read controller environment settings;
- unrelated non-`VRC_*` environment variables are preserved/ignored as before;
- `VRC_API_TOKEN` fails and guides to `VRC_API_TOKEN_FILE` without echoing the supplied value;
- `VRC_VNC_PASSWORD` fails and guides to `VRC_VNC_PASSWORD_FILE` without echoing the supplied value;
- supported file-backed secret variables continue to work;
- supported non-secret runtime variables continue to work;
- absent optional variables retain defaults;
- present empty values follow their explicit validation behavior and are not silently downgraded to defaults.

Tests that mutate process environment MUST remain serialized or otherwise race-safe.

## 6. PRH-003 — Harden public Python constructor argument types

### 6.1 `base_url`

`VncClient` MUST explicitly validate `base_url` at the public constructor boundary rather than relying on `urllib.parse` or other downstream behavior to reject malformed types.

At minimum:

- a valid string continues through the existing URL validation path;
- non-string inputs fail deterministically with the client validation exception chosen by the project;
- diagnostics describe the argument contract without echoing arbitrary object representations.

A recommended stable error is:

`base_url must be a string`

Existing URL semantic validation for malformed strings MUST remain intact.

### 6.2 `token`

`VncClient` MUST explicitly validate `token` when supplied.

At minimum:

- `None` remains valid where it currently means no token;
- a valid string remains accepted subject to existing content checks;
- non-string values fail deterministically rather than producing incidental `TypeError` behavior;
- diagnostics MUST NOT include the token value.

A recommended stable error is:

`token must be a string when provided`

Existing checks for prohibited token contents MUST remain intact.

### 6.3 Scope restraint

This task is not authorization to redesign the public Python client or coerce arbitrary objects into strings. Do not accept `Path`, integers, bytes, or other objects by implicit conversion unless the existing public API explicitly promises that behavior.

### 6.4 Regression coverage

Tests MUST cover accepted normal values and malformed type inputs for both `base_url` and `token`, including stable exception type/message and non-echo of sensitive token contents.

## 7. PRH-004 — Reconcile documentation and contracts

The implementation MUST update documentation so current behavior and security contracts agree.

At minimum:

1. Correct the prior PFH empty-value wording so absent values may use defaults while present empty values remain explicit input unless specifically documented otherwise.
2. Document the public Python timeout contract as positive finite values representable by the internal timeout implementation, not every mathematically positive integer.
3. Document controller unknown-`VRC_*` fail-closed behavior and raw-secret file guidance.
4. Ensure examples use only supported file-backed secret variables.
5. Do not rewrite historical evidence to imply that earlier CI runs tested cases they did not test. Historical PFH evidence remains historical; this follow-up records new evidence separately.

## 8. PRH-005 — Static safety preservation and qualification

### 8.1 Focused validation

Before merge, run focused tests for all changed Python and Rust behavior where locally possible.

Python focused coverage SHOULD include:

- timeout overflow and existing timeout edge cases;
- `base_url` type validation;
- `token` type validation and non-echo behavior;
- existing MCP unsafe-fallback contract tests.

Rust focused coverage SHOULD include:

- controller namespace validation;
- public runtime-loader bypass regression;
- raw-secret guidance/non-echo behavior;
- supported-variable and default/empty semantics.

### 8.2 Repository gates

The exact final PR head MUST pass all applicable required repository CI and Release Gates, including:

- Rust formatting;
- Clippy with warnings denied;
- Rust unit tests;
- Rust documentation with warnings denied;
- Python compilation;
- Ruff;
- Pylint;
- mypy;
- Python/workflow contract tests;
- shell syntax checks;
- Python MCP dependency/license gate;
- native sanitizer and Miri gates;
- image vulnerability/VEX/SBOM gates;
- static and supply-chain gates;
- production controller/TigerVNC/MCP E2E;
- R13 Compose integration/E2E.

No required gate may be skipped, ignored, or treated as advisory for closeout.

### 8.3 Exact evidence

The TODO MUST record the final exact PR-head SHA and the exact CI and Release Gates run IDs used to qualify that head. If an evidence-only commit changes the PR head, the new exact head must be requalified before merge.

## 9. PRH-006 — Merge and post-merge closeout

After exact-candidate qualification:

1. Merge only through the repository's approved merge path with an exact-head compare-and-swap guard.
2. Record the implementation merge SHA.
3. Require fresh CI success on the exact merged `master` SHA.
4. Require fresh Release Gates success on the exact merged `master` SHA.
5. Require fresh final Publish CI Status success associated with that exact merged SHA.
6. Verify merged-master CI includes production MCP/TigerVNC E2E.
7. Verify merged-master CI includes R13 Compose integration/E2E.
8. Reconcile every TODO item with exact evidence.
9. If the TODO reconciliation itself is merged separately, qualify and validate that final documentation merge as current `master` before declaring the work closed.

## 10. Explicit non-goals

This hardening pass does not authorize:

- redesigning the MCP transport architecture;
- changing mutation retry/replay semantics;
- introducing legacy SSE support;
- disabling SDK transport security;
- accepting raw secrets through environment variables;
- broad coercion of malformed Python constructor values;
- treating present empty configuration as absent by default;
- weakening tests to accommodate existing behavior;
- suppressing errors with warnings or silent defaults;
- unrelated refactors without a concrete correctness or safety reason.

## 11. Completion criteria

This specification is complete only when:

- every PRH-001 through PRH-006 TODO item is checked with code/test/evidence support;
- the timeout overflow bug has a deterministic regression test and stable failure contract;
- every public controller environment-loading path enforces the closed `VRC_*` vocabulary;
- raw-secret alias diagnostics safely point to file-backed alternatives;
- Python `base_url` and `token` type boundaries fail deterministically;
- prior empty-value documentation has been reconciled without weakening fail-closed behavior;
- no unsafe fallback or silent-failure path has been added;
- exact-candidate CI and Release Gates pass;
- implementation is merged to `master`;
- exact merged-master CI, Release Gates, Publish CI Status, MCP/TigerVNC E2E, and R13 Compose integration/E2E all pass;
- final TODO evidence accurately describes the SHA and runs that actually qualified and validated the work.
