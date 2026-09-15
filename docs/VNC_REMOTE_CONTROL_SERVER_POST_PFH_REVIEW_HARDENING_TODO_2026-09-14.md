# VNC Remote Control Server — Post-PFH Review Hardening TODO

**Date:** 2026-09-14  
**Spec:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_PFH_REVIEW_HARDENING_SPEC_2026-09-14.md`  
**Review base:** `master` at `6948ce0c522aa3e5ffbba9e402250e2f78457ac8`  
**Prior closeout:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_TODO_2026-09-14.md`

This checklist tracks the follow-up issues found during the post-PFH code review. It does not reopen the historical PFH checklist. Check an item only when the implementation, tests, and evidence required by the companion specification support it.

## PRH-001 — Harden public Python client timeout conversion

- [ ] Update the public timeout validator so conversion failures cannot escape as incidental `OverflowError`, `TypeError`, or conversion-specific `ValueError` for invalid timeout input.
- [ ] Preserve one stable public `ValueError` contract for every rejected timeout input.
- [ ] Preserve rejection of `bool` values.
- [ ] Preserve rejection of zero and negative values.
- [ ] Preserve rejection of NaN and positive/negative infinity.
- [ ] Preserve rejection of strings, bytes, `None`, and arbitrary nonnumeric objects.
- [ ] Accept ordinary positive integer timeout values representable by the internal timeout implementation.
- [ ] Accept ordinary positive finite float timeout values.
- [ ] Reject a huge positive integer such as `10**400` with the stable timeout `ValueError` rather than `OverflowError`.
- [ ] Add focused regression tests for conversion overflow and all existing timeout edge cases.

## PRH-002 — Complete controller-side `VRC_*` namespace hardening

- [ ] Reconfirm every supported controller-side `VRC_*` environment variable and maintain one authoritative supported vocabulary.
- [ ] Prevent the authoritative vocabulary from drifting from the variables actually read by controller/runtime parsers.
- [ ] Ensure the top-level controller loader rejects every unsupported controller `VRC_*` variable before startup accepts configuration.
- [ ] Ensure every other public controller configuration-loading entry point that reads `VRC_*` state performs the same closed-vocabulary validation or delegates through one validated public loader.
- [ ] Specifically close the direct `RuntimeSettings::load()` unknown-`VRC_*` bypass identified in the post-PFH review.
- [ ] Preserve unrelated non-`VRC_*` process environment variables.
- [ ] Preserve file-backed controller secret loading.
- [ ] Preserve rejection of raw `VRC_API_TOKEN` and `VRC_VNC_PASSWORD` aliases.
- [ ] Improve generic unsupported-`VRC_*` diagnostics to explain that only documented controller `VRC_*` variables are accepted, without echoing supplied values.
- [ ] Make `VRC_API_TOKEN` rejection safely point to `VRC_API_TOKEN_FILE` without echoing the token value or secret-file contents.
- [ ] Make `VRC_VNC_PASSWORD` rejection safely point to `VRC_VNC_PASSWORD_FILE` without echoing the password value or secret-file contents.
- [ ] Preserve supported non-secret controller/runtime environment configuration.
- [ ] Preserve default behavior for absent optional variables.
- [ ] Preserve fail-closed explicit validation for present empty values; do not silently convert generic empty values to absence/defaults.
- [ ] Add Rust tests proving unknown `VRC_*` rejection through the top-level loader.
- [ ] Add Rust tests proving unknown `VRC_*` rejection through every remaining public lower-level loader that reads controller environment settings.
- [ ] Add Rust tests for generic unsupported-variable guidance and supplied-value non-echo behavior.
- [ ] Add Rust tests for raw API-token alias guidance and value non-echo behavior.
- [ ] Add Rust tests for raw VNC-password alias guidance and value non-echo behavior.
- [ ] Add Rust tests proving supported file-backed secret variables still work.
- [ ] Add Rust tests proving supported runtime variables still work.
- [ ] Add Rust tests distinguishing absent/default behavior from explicit empty-value validation.
- [ ] Keep process-environment-mutating tests serialized or otherwise race-safe.

## PRH-003 — Harden public Python constructor argument types

### `base_url`

- [ ] Add explicit public-boundary type validation for `base_url` before URL parsing.
- [ ] Preserve existing semantic URL validation for string inputs.
- [ ] Reject non-string `base_url` values with one stable project validation exception/message rather than downstream `AttributeError`/parser-specific behavior.
- [ ] Ensure invalid-object diagnostics do not depend on or echo arbitrary object representations.
- [ ] Add accepted and rejected `base_url` regression tests.

### `token`

- [ ] Add explicit public-boundary type validation for `token` when supplied.
- [ ] Preserve `None` behavior where no token is allowed by the existing API.
- [ ] Preserve valid string token handling and all existing token-content restrictions.
- [ ] Reject non-string token values with one stable project validation exception/message rather than incidental `TypeError` behavior.
- [ ] Ensure token validation diagnostics never echo the token value.
- [ ] Add accepted and rejected token-type regression tests, including non-echo assertions.

## PRH-004 — Reconcile documentation and behavioral contracts

- [ ] Correct prior PFH wording that implied generic present-empty optional environment values should use defaults.
- [ ] Document the intended distinction: absent optional controller variables may use defaults; present empty values remain explicit input and are validated normally unless specifically documented otherwise.
- [ ] Update timeout documentation to describe positive finite values representable by the internal timeout implementation rather than every mathematically positive integer.
- [ ] Document closed controller `VRC_*` behavior across all public loading paths.
- [ ] Document safe raw-secret alias guidance toward `VRC_API_TOKEN_FILE` and `VRC_VNC_PASSWORD_FILE`.
- [ ] Confirm all configuration examples use supported file-backed secret variables and no raw-secret ingress.
- [ ] Preserve historical PFH evidence as historical; do not rewrite old CI evidence to claim coverage that only the PRH follow-up adds.

## PRH-005 — Preserve static safety contracts and qualify the exact candidate

### Safety preservation

- [ ] Preserve `tests/test_mcp_unsafe_fallback_contract.py` without weakening broad-exception, raw-token, retry/replay, transport-security, SSE, or silent-fallback checks.
- [ ] Confirm no new broad `except Exception` or `except BaseException` handling is introduced in MCP mutation/configuration paths.
- [ ] Confirm no new retry, replay, sleep, backoff, or best-effort fallback path is introduced for mutation outcomes.
- [ ] Confirm no raw secret environment-variable ingress is introduced.
- [ ] Confirm invalid configuration and public-boundary inputs fail closed rather than being downgraded to warnings, coercions, or silent defaults.

### Focused validation

- [ ] Run focused Python tests covering timeout overflow, timeout edge cases, `base_url` type validation, `token` type validation, and MCP unsafe-fallback contracts.
- [ ] Run focused Rust controller configuration tests covering closed vocabulary, public-loader enforcement, diagnostics, file-backed secrets, supported variables, and absent-versus-empty semantics.
- [ ] If a local environment cannot run a required toolchain, record the limitation and require equivalent exact-candidate CI evidence rather than marking the test as locally passed.

### Exact-candidate qualification

- [ ] Run repository formatting/lint/type/unit gates through CI on the exact final PR head.
- [ ] Require exact final PR-head CI success.
- [ ] Require exact final PR-head Release Gates success.
- [ ] Verify exact-candidate CI includes production MCP/TigerVNC E2E.
- [ ] Verify exact-candidate CI includes R13 Compose integration/E2E.
- [ ] Record the exact final PR-head SHA in this TODO.
- [ ] Record the exact qualifying CI run ID in this TODO.
- [ ] Record the exact qualifying Release Gates run ID in this TODO.
- [ ] If an evidence-only commit changes the candidate SHA, re-run exact-head qualification and record the superseding SHA/runs rather than relying on stale green evidence.

## PRH-006 — Merge and post-merge closeout

- [ ] Merge only through the repository's approved merge path after exact-candidate CI and Release Gates are green.
- [ ] Record the implementation merge SHA in this TODO.
- [ ] Require fresh CI success on the exact merged `master` SHA.
- [ ] Require fresh Release Gates success on the exact merged `master` SHA.
- [ ] Require fresh final Publish CI Status success associated with the exact merged `master` SHA.
- [ ] Verify merged-master CI includes production MCP/TigerVNC E2E.
- [ ] Verify merged-master CI includes R13 Compose integration/E2E.
- [ ] Reconcile every PRH-001 through PRH-006 item with implementation/test/evidence details.
- [ ] If TODO reconciliation is merged as a follow-up documentation PR, qualify that PR through required CI/Release Gates and validate the resulting final `master` before declaring closure.
- [ ] Reload this TODO from final current `master` and confirm there are no unchecked tasks or subtasks.

## Completion status

Open. PRH-001 through PRH-006 remain to be implemented, qualified, merged, post-merge validated, and reconciled.
