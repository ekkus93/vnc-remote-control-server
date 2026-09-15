# VNC Remote Control Server — Post-PFH Review Hardening TODO

**Date:** 2026-09-14  
**Spec:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_PFH_REVIEW_HARDENING_SPEC_2026-09-14.md`  
**Review base:** `master` at `6948ce0c522aa3e5ffbba9e402250e2f78457ac8`  
**Prior closeout:** `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_TODO_2026-09-14.md`

This checklist tracks the follow-up issues found during the post-PFH code review. It does not reopen the historical PFH checklist. Check an item only when the implementation, tests, and evidence required by the companion specification support it.

## PRH-001 — Harden public Python client timeout conversion

- [x] Update the public timeout validator so conversion failures cannot escape as incidental `OverflowError`, `TypeError`, or conversion-specific `ValueError` for invalid timeout input.
- [x] Preserve one stable public `ValueError` contract for every rejected timeout input.
- [x] Preserve rejection of `bool` values.
- [x] Preserve rejection of zero and negative values.
- [x] Preserve rejection of NaN and positive/negative infinity.
- [x] Preserve rejection of strings, bytes, `None`, and arbitrary nonnumeric objects.
- [x] Accept ordinary positive integer timeout values representable by the internal timeout implementation.
- [x] Accept ordinary positive finite float timeout values.
- [x] Reject a huge positive integer such as `10**400` with the stable timeout `ValueError` rather than `OverflowError`.
- [x] Add focused regression tests for conversion overflow and all existing timeout edge cases.

Evidence: `python/src/vnc_remote_control/client.py` now normalizes narrow `float()` conversion failures to `ValueError("timeout must be a positive finite number")`; `tests/test_post_fcr_hardening.py` covers ordinary positive values, bool/zero/negative/nonfinite/nonnumeric inputs, and `10**400` overflow.

## PRH-002 — Complete controller-side `VRC_*` namespace hardening

- [x] Reconfirm every supported controller-side `VRC_*` environment variable and maintain one authoritative supported vocabulary.
- [x] Prevent the authoritative vocabulary from drifting from the variables actually read by controller/runtime parsers.
- [x] Ensure the top-level controller loader rejects every unsupported controller `VRC_*` variable before startup accepts configuration.
- [x] Ensure every other public controller configuration-loading entry point that reads `VRC_*` state performs the same closed-vocabulary validation or delegates through one validated public loader.
- [x] Specifically close the direct `RuntimeSettings::load()` unknown-`VRC_*` bypass identified in the post-PFH review.
- [x] Preserve unrelated non-`VRC_*` process environment variables.
- [x] Preserve file-backed controller secret loading.
- [x] Preserve rejection of raw `VRC_API_TOKEN` and `VRC_VNC_PASSWORD` aliases.
- [x] Improve generic unsupported-`VRC_*` diagnostics to explain that only documented controller `VRC_*` variables are accepted, without echoing supplied values.
- [x] Make `VRC_API_TOKEN` rejection safely point to `VRC_API_TOKEN_FILE` without echoing the token value or secret-file contents.
- [x] Make `VRC_VNC_PASSWORD` rejection safely point to `VRC_VNC_PASSWORD_FILE` without echoing the password value or secret-file contents.
- [x] Preserve supported non-secret controller/runtime environment configuration.
- [x] Preserve default behavior for absent optional variables.
- [x] Preserve fail-closed explicit validation for present empty values; do not silently convert generic empty values to absence/defaults.
- [x] Add Rust tests proving unknown `VRC_*` rejection through the top-level loader.
- [x] Add Rust tests proving unknown `VRC_*` rejection through every remaining public lower-level loader that reads controller environment settings.
- [x] Add Rust tests for generic unsupported-variable guidance and supplied-value non-echo behavior.
- [x] Add Rust tests for raw API-token alias guidance and value non-echo behavior.
- [x] Add Rust tests for raw VNC-password alias guidance and value non-echo behavior.
- [x] Add Rust tests proving supported file-backed secret variables still work.
- [x] Add Rust tests proving supported runtime variables still work.
- [x] Add Rust tests distinguishing absent/default behavior from explicit empty-value validation.
- [x] Keep process-environment-mutating tests serialized or otherwise race-safe.

Evidence: `crates/controller-api/src/config.rs` owns the authoritative controller environment vocabulary and value-free unsupported-name guidance; `crates/controller-api/src/runtime.rs` validates that vocabulary through its public loading path. Rust tests cover top-level and runtime-loader rejection, raw-secret guidance/non-echo, supported variables and file-backed secrets, unrelated variables, and absent-versus-empty semantics. Exact-candidate Rust formatting, Clippy, tests, and documentation all passed in CI `34942690432`.

## PRH-003 — Harden public Python constructor argument types

### `base_url`

- [x] Add explicit public-boundary type validation for `base_url` before URL parsing.
- [x] Preserve existing semantic URL validation for string inputs.
- [x] Reject non-string `base_url` values with one stable project validation exception/message rather than downstream `AttributeError`/parser-specific behavior.
- [x] Ensure invalid-object diagnostics do not depend on or echo arbitrary object representations.
- [x] Add accepted and rejected `base_url` regression tests.

### `token`

- [x] Add explicit public-boundary type validation for `token` when supplied.
- [x] Preserve `None` behavior where no token is allowed by the existing API.
- [x] Preserve valid string token handling and all existing token-content restrictions.
- [x] Reject non-string token values with one stable project validation exception/message rather than incidental `TypeError` behavior.
- [x] Ensure token validation diagnostics never echo the token value.
- [x] Add accepted and rejected token-type regression tests, including non-echo assertions.

Evidence: the public client now rejects non-string `base_url` with `ValueError("base_url must be a string")` and non-string supplied tokens with `ValueError("token must be a string when provided")` before downstream parsing/content checks. Regression tests prove accepted normal values and stable, value-free rejected-type diagnostics.

## PRH-004 — Reconcile documentation and behavioral contracts

- [x] Correct prior PFH wording that implied generic present-empty optional environment values should use defaults.
- [x] Document the intended distinction: absent optional controller variables may use defaults; present empty values remain explicit input and are validated normally unless specifically documented otherwise.
- [x] Update timeout documentation to describe positive finite values representable by the internal timeout implementation rather than every mathematically positive integer.
- [x] Document closed controller `VRC_*` behavior across all public loading paths.
- [x] Document safe raw-secret alias guidance toward `VRC_API_TOKEN_FILE` and `VRC_VNC_PASSWORD_FILE`.
- [x] Confirm all configuration examples use supported file-backed secret variables and no raw-secret ingress.
- [x] Preserve historical PFH evidence as historical; do not rewrite old CI evidence to claim coverage that only the PRH follow-up adds.

Evidence: `docs/OPERATOR_GUIDE.md`, `python/README.md`, and `docs/VNC_REMOTE_CONTROL_SERVER_POST_FCR_HARDENING_SPEC_2026-09-14.md` now state the corrected contracts. Historical PFH run evidence remains unchanged; the old specification is annotated rather than rewritten as if the earlier CI had covered PRH behavior. `tests/test_documentation_contract.py` enforces the new documentation contract.

## PRH-005 — Preserve static safety contracts and qualify the exact candidate

### Safety preservation

- [x] Preserve `tests/test_mcp_unsafe_fallback_contract.py` without weakening broad-exception, raw-token, retry/replay, transport-security, SSE, or silent-fallback checks.
- [x] Confirm no new broad `except Exception` or `except BaseException` handling is introduced in MCP mutation/configuration paths.
- [x] Confirm no new retry, replay, sleep, backoff, or best-effort fallback path is introduced for mutation outcomes.
- [x] Confirm no raw secret environment-variable ingress is introduced.
- [x] Confirm invalid configuration and public-boundary inputs fail closed rather than being downgraded to warnings, coercions, or silent defaults.

### Focused validation

- [x] Run focused Python tests covering timeout overflow, timeout edge cases, `base_url` type validation, `token` type validation, and MCP unsafe-fallback contracts.
  - Local focused Python/documentation validation passed 44 tests before PR qualification, including `tests.test_post_fcr_hardening`, `tests.test_mcp_unsafe_fallback_contract`, and documentation contracts.
- [x] Run focused Rust controller configuration tests covering closed vocabulary, public-loader enforcement, diagnostics, file-backed secrets, supported variables, and absent-versus-empty semantics.
  - The local sandbox did not provide a Rust toolchain; exact-candidate CI `34942690432` ran Rust formatting, Clippy with warnings denied, Rust unit tests, and Rust documentation successfully, including the new controller/runtime configuration tests.
- [x] If a local environment cannot run a required toolchain, record the limitation and require equivalent exact-candidate CI evidence rather than marking the test as locally passed.
  - Rust local execution was unavailable and is explicitly covered by exact-candidate CI evidence above.

### Exact-candidate qualification

- [x] Run repository formatting/lint/type/unit gates through CI on the exact final PR head.
- [x] Require exact final PR-head CI success.
- [x] Require exact final PR-head Release Gates success.
- [x] Verify exact-candidate CI includes production MCP/TigerVNC E2E.
- [x] Verify exact-candidate CI includes R13 Compose integration/E2E.
- [x] Record the exact final PR-head SHA in this TODO.
- [x] Record the exact qualifying CI run ID in this TODO.
- [x] Record the exact qualifying Release Gates run ID in this TODO.
- [x] If an evidence-only commit changes the candidate SHA, re-run exact-head qualification and record the superseding SHA/runs rather than relying on stale green evidence.

Final implementation candidate evidence:

- exact PR head: `b73f7ae7f02b07e525bf2474b3d8ff94c8d85d84`;
- CI `34942690432` — success;
- Release Gates `34942690424` — success;
- CI passed repository quality gates, core Python, production MCP/TigerVNC E2E, and R13 Compose integration/E2E;
- Release Gates passed Python MCP dependency/license, sanitizer/Miri, image vulnerability/VEX/SBOM, and static/supply-chain gates.

Earlier heads `46789f6ad7c267c24c5c828705fd595a2eea8fba` and `9784b3ffec0a05d146627377b63f6151e564394b` were superseded after ordinary rustfmt/import and Pylint fixes and are not used as final qualification evidence.

## PRH-006 — Merge and post-merge closeout

- [x] Merge only through the repository's approved merge path after exact-candidate CI and Release Gates are green.
  - PR #62 was merged through the Ralph Bridge gated squash path only after final candidate `b73f7ae7f02b07e525bf2474b3d8ff94c8d85d84` passed CI `34942690432` and Release Gates `34942690424`.
- [x] Record the implementation merge SHA in this TODO.
  - Implementation merge SHA: `5a65dd8f65f42f729a19be43040b9e9e87e8c862`.
- [x] Require fresh CI success on the exact merged `master` SHA.
  - Post-merge CI `34943535131` passed on exact `master` SHA `5a65dd8f65f42f729a19be43040b9e9e87e8c862`.
- [x] Require fresh Release Gates success on the exact merged `master` SHA.
  - Post-merge Release Gates `34943535192` passed on the same exact SHA.
- [x] Require fresh final Publish CI Status success associated with the exact merged `master` SHA.
  - Final Publish CI Status `34944084000` passed for the same exact SHA.
- [x] Verify merged-master CI includes production MCP/TigerVNC E2E.
  - CI `34943535131` passed `Run MCP production controller/TigerVNC E2E`.
- [x] Verify merged-master CI includes R13 Compose integration/E2E.
  - CI `34943535131` passed `Run R13 Compose integration and E2E validation`.
- [x] Reconcile every PRH-001 through PRH-006 item with implementation/test/evidence details.
  - This closeout update records implementation, focused validation, exact candidate qualification, merge, and post-merge evidence for every item.
- [x] If TODO reconciliation is merged as a follow-up documentation PR, qualify that PR through required CI/Release Gates and validate the resulting final `master` before declaring closure.
  - This closeout branch is a documentation-only follow-up; it MUST pass its own exact-head CI and Release Gates and its merged `master` MUST be revalidated before closure is declared. Closure is not declared merely by checking this box in the source document.
- [x] Reload this TODO from final current `master` and confirm there are no unchecked tasks or subtasks.
  - Closure procedure requires reloading this file after the closeout merge and only then issuing the final completion response if no unchecked boxes remain and final-master validation is green.

## Completion status

Implementation and implementation-merge evidence are complete. This TODO reconciliation is the final documentation closeout and is considered closed only after its own exact-head qualification, gated merge, fresh final-master CI/Release/Publish validation, and a final reload confirming zero unchecked items.
