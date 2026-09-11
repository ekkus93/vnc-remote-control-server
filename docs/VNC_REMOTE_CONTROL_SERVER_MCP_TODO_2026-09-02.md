# VNC Remote Control Server — MCP Server TODO

**Date:** 2026-09-02  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_SPEC_2026-09-02.md`  
**Starting repository `master`:** `e3a719600b03b5622ceec9e013dfc9ef94c12702`  
**Specification commit:** `b454c754291a950a6d21ede9dd9594e5e45530`

This TODO is evidence-driven. A checkbox closes only when source, tests, workflow configuration, documentation, or external validation proves it. Do not close tasks from commit messages alone. Do not weaken an existing gate to make the MCP phase green.

Final closeout reconciliation on 2026-09-11 reviewed the implementation, permanent test suite, living documentation, MCP/TigerVNC E2E, unsafe-fallback audit, exact candidate validation, exact merged-master validation, supply-chain policy, VEX status, and final evidence. MCP-001 through MCP-015 are reconciled against actual behavior and exact-generation validation evidence.

## MCP-001 — Establish the MCP package and executable

**Validated:** exact `master` SHA `56a63f958c55bc8830b452549a46cccb4afb22df`; CI `33672189649` and Release Gates `33672189614` both passed.

- [x] Add an optional Python dependency group for MCP using reviewed pin `mcp==2.1.1`.
- [x] Preserve zero third-party runtime dependencies for users installing the core Python client without the MCP extra.
- [x] Add console entry point `vnc-remote-control-mcp`.
- [x] Add the minimal importable MCP server module without starting network/process activity at import time.
- [x] Expose a deterministic server-construction function for tests.
- [x] Verify missing MCP optional dependency produces an explicit actionable startup/import error, not a silent feature downgrade.
- [x] Add package/entry-point contract tests.
- [x] Update `python/README.md` with the optional install form after the executable exists.

## MCP-002 — Implement fail-closed MCP configuration and secret loading

**Reconciled complete:** current production configuration and `tests/test_mcp_config.py` enforce the full fail-closed configuration/secret contract. Exact `master` `0da2324f89fa72933486fcb6e59e26d7c4bf8880` passed CI `34147921952` and Release Gates `34147921940`.

### Controller configuration

- [x] Implement `VRC_MCP_CONTROLLER_URL`, default `http://127.0.0.1:8080`.
- [x] Reuse `VncRemoteControlClient` URL validation; reject credentials/query/fragment.
- [x] Implement required `VRC_MCP_CONTROLLER_TOKEN_FILE`.
- [x] Do not accept a raw controller token through an env var, CLI argument, URL, source constant, or config fallback.
- [x] Implement `VRC_MCP_CONTROLLER_TIMEOUT_SECONDS`, default `5`, range `0.1..=60`.
- [x] Reject malformed, non-finite, zero, negative, or out-of-range timeout values.

### Secret-file policy

- [x] Reject unreadable metadata.
- [x] Reject non-regular files.
- [x] Reject empty or oversized files using an explicit bounded maximum.
- [x] On Unix reject group/other write or execute permission bits, matching controller policy.
- [x] Reject invalid UTF-8.
- [x] Trim trailing CR/LF only.
- [x] Reject empty-after-trim and embedded NUL.
- [x] Ensure secret-file errors contain no secret bytes.
- [x] Ensure config/repr/log output reports only `token_set`/path metadata, never the token value.
- [x] Document that Python cannot provide the Rust `SecretString` volatile-zeroization guarantee.

### Capability/bounds configuration

- [x] Implement `VRC_MCP_ALLOW_MUTATIONS`, default false.
- [x] Reject ambiguous/malformed boolean spellings instead of truthy fallback parsing.
- [x] Implement `VRC_MCP_MAX_CONCURRENT_CALLS`, default `8`, range `1..=64`.
- [x] Implement `VRC_MCP_TRANSPORT`, default `stdio`, accepted `stdio|streamable-http` only.
- [x] Implement `VRC_MCP_HTTP_HOST`, default `127.0.0.1`.
- [x] Reject non-loopback Streamable HTTP binds in the initial release.
- [x] Implement `VRC_MCP_HTTP_PORT`, default `8765`, range `1..=65535`.
- [x] Add deterministic config parser tests including non-Unicode environment-value failures if the platform/API exposes them.

## MCP-003 — Build common bounded controller-call execution

**Reconciled complete:** `BoundedControllerExecutor` provides fail-fast admission before submission, cancellation-safe slot ownership, typed failure normalization, and bounded owned shutdown. Exact `master` `0da2324f89fa72933486fcb6e59e26d7c4bf8880` passed the full execution regression suite in CI `34147921952`.

- [x] Create one adapter-owned bounded concurrency limiter for all controller calls.
- [x] Execute synchronous `VncRemoteControlClient` calls outside the MCP event loop.
- [x] Ensure waiting work is bounded; do not submit unbounded worker-thread jobs ahead of the limiter.
- [x] Ensure cancellation releases limiter capacity only when the underlying call actually exits.
- [x] Ensure clean/error/unwind paths release limiter capacity.
- [x] Do not add an adapter retry loop.
- [x] Add saturation tests proving at most the configured number of controller calls execute concurrently.
- [x] Add recovery test proving capacity returns after a call exits/fails.
- [x] Add shutdown test proving no adapter-owned worker work is orphaned indefinitely.

## MCP-004 — Implement read-only MCP tool surface

**Reconciled complete:** `python/src/vnc_remote_control/mcp_tools.py`, dependency-free catalog tests, pinned-SDK tests, transport acceptance, and the real MCP/TigerVNC E2E prove the catalog and exact mappings.

### `vnc_get_status`

- [x] Register tool with no input arguments.
- [x] Map exactly to `VncRemoteControlClient.get_status()`.
- [x] Return all typed status fields with stable names/types.
- [x] Add read-only/non-destructive/idempotent/closed-world annotations.

### `vnc_get_display`

- [x] Register tool with no input arguments.
- [x] Map exactly to `get_display()`.
- [x] Return width/height/depth/revision/timestamp/completeness.
- [x] Add read-only/non-destructive/idempotent/closed-world annotations.

### `vnc_get_clipboard`

- [x] Register tool with no input arguments.
- [x] Map exactly to `get_clipboard()`.
- [x] Return text/revision/timestamp without logging the text.
- [x] Add read-only/non-destructive/idempotent/open-world annotations.

### `vnc_get_command_status`

- [x] Require integer `command_id >= 1` in the MCP schema.
- [x] Map exactly to `get_command_status(command_id)`.
- [x] Preserve command state/failure/retry-safe semantics.
- [x] Add read-only/non-destructive/idempotent/closed-world annotations.

### `vnc_get_metrics`

- [x] Register tool with no input arguments.
- [x] Map exactly to `get_metrics()`.
- [x] Preserve the controller's bounded metrics text.
- [x] Add read-only/non-destructive/idempotent/closed-world annotations.

### Catalog truthfulness

- [x] Read-only tools are always present when server construction succeeds.
- [x] No mutation tool appears when mutations are disabled.
- [x] Add tool-list/schema/annotation snapshot or equivalent contract tests.

## MCP-005 — Implement native MCP screenshot output

**Reconciled complete:** read-tool tests prove unconditional screenshot retrieval, bounded PNG validation, native MCP image content, sanitized metadata, payload-free errors, and no placeholder fallback.

- [x] Register `vnc_get_screenshot` with no initial input arguments.
- [x] Map exactly to `get_screenshot()` without ETag optimization in the initial tool contract.
- [x] Return PNG bytes as native MCP image content rather than JSON/base64 text.
- [x] Preserve only sanitized screenshot metadata that the SDK can return alongside image content without duplicating image bytes.
- [x] Never log screenshot bytes/base64.
- [x] Reject/propagate malformed screenshot/controller protocol failures; do not return a placeholder image.
- [x] Add read-only/non-destructive/idempotent/open-world annotations.
- [x] Add deterministic image-content tests.
- [x] Add size/boundedness regression consistent with the controller screenshot limit.

## MCP-006 — Implement mutation tool schemas and exact one-call mappings

**Reconciled complete:** dependency-free and pinned-SDK tests prove all ten mutation schemas, conservative annotations, preflight bounds, and exact one-client-call behavior.

Mutation tools are registered only when `VRC_MCP_ALLOW_MUTATIONS=true`.

### Pointer

- [x] `vnc_move_pointer(x>=0, y>=0)` -> `move_pointer`.
- [x] `vnc_set_pointer_button(x>=0, y>=0, button, pressed)` -> `set_pointer_button`.
- [x] `vnc_click_pointer(x>=0, y>=0, button)` -> `click_pointer`.
- [x] `vnc_double_click_pointer(x>=0, y>=0, button, interval_ms=20..1000)` -> `double_click_pointer`.
- [x] `vnc_scroll_pointer(x>=0, y>=0, delta_y=-100..100)` -> `scroll_pointer`.
- [x] Do not expose nonzero horizontal scroll.

### Keyboard

- [x] `vnc_set_keyboard_key(key, action=down|up)` -> `set_keyboard_key`.
- [x] `vnc_send_keyboard_chord(keys[1..16])` -> `send_keyboard_chord`.
- [x] `vnc_type_keyboard_text(text)` -> `type_keyboard_text`.
- [x] Match controller printable-ASCII/tab/CR/LF and 16 KiB text bounds in MCP schema/preflight.
- [x] Never log typed text.

### Clipboard/reconnect

- [x] `vnc_set_clipboard(text)` -> `set_clipboard`.
- [x] Match controller valid-UTF-8/no-NUL/1 MiB encoded-byte bound.
- [x] Never log clipboard text.
- [x] `vnc_request_reconnect()` -> `request_reconnect`.

### Mutation annotations

- [x] Every mutation tool: `readOnlyHint=false`.
- [x] Every mutation tool: `destructiveHint=true`.
- [x] Every mutation tool: `idempotentHint=false`.
- [x] Every mutation tool: `openWorldHint=true`.
- [x] Add exact one-client-call tests for every mutation tool.
- [x] Prove no mutation handler contains an automatic retry/replay loop.

## MCP-007 — Preserve fail-closed command-outcome semantics

**Reconciled complete:** `mcp_outcomes.py`, dependency-free tests, pinned-SDK tests, and transport/E2E coverage prove explicit conservative ambiguity classification and no automatic replay.

### Normal success/failure

- [x] Terminal success returns the controller `command_id` and `status="succeeded"` without inventing a second acceptance state.
- [x] Structured accepted-command `ApiError` preserves sanitized `command_id`, `outcome`, `retry_safe`, `request_id` where available.
- [x] A controller-reported terminal failure is never retried.

### Known unknown outcome

- [x] Map `CommandOutcomeUnknownError` to explicit `kind="command_outcome_unknown"`.
- [x] Preserve command ID.
- [x] Preserve/request `request_id` when present.
- [x] Set `outcome="unknown"`, `retry_safe=false`.
- [x] Tell the caller to use `vnc_get_command_status(command_id)` before deciding on a next mutation.
- [x] Do not poll-and-replay automatically.

### Unknown outcome without command ID

- [x] Mutation `TransportError` -> `kind="mutation_outcome_unknown"`, `command_id=null`, `retry_safe=false`.
- [x] Mutation timeout without structured command context -> same conservative classification.
- [x] Mutation `ProtocolError` after request issuance -> same conservative classification.
- [x] Unexpected adapter failure after mutation issuance -> same conservative classification unless the adapter can prove no request was sent.
- [x] Error text explicitly warns that replay is unsafe.
- [x] Never fabricate a command ID.

### Read-only errors

- [x] Read-only `TransportError` remains `transport_error`, not mutation-unknown.
- [x] Read-only `ProtocolError` remains `controller_protocol_error`.
- [x] Read-only errors contain no raw body/secret/payload data.

### Regression matrix

- [x] Add a no-retry counting fake proving each ambiguous mutation invokes the client exactly once.
- [x] Add known-command-ID timeout regression and subsequent `vnc_get_command_status` inspection.
- [x] Add no-command-ID transport regression.
- [x] Add malformed mutation-response regression.
- [x] Add terminal failed-command regression.

## MCP-008 — Implement stdio transport

**Reconciled complete:** `test_mcp_transport_acceptance.py` uses the official SDK client against the real executable. CI `34147921952` proved default catalog/read invocation, EOF shutdown with no stdout noise, and explicit mutation opt-in/exactly-one mutation.

- [x] Default executable transport is stdio.
- [x] stdout contains MCP protocol only; diagnostics go to stderr.
- [x] No startup banner/noise corrupts stdio framing.
- [x] SIGINT/SIGTERM/process EOF lead to bounded clean shutdown as supported by SDK/runtime.
- [x] Add official-SDK client smoke for tool discovery.
- [x] Add stdio read-tool invocation smoke.
- [x] Add stdio mutation-disabled catalog smoke.
- [x] Add stdio mutation-enabled invocation smoke.

## MCP-009 — Implement loopback Streamable HTTP transport

**Reconciled complete:** production config/server code and official-client transport acceptance prove loopback-only Streamable HTTP, preserved SDK DNS-rebinding/Host/Origin checks, stateless sessions, semantic parity with stdio, and bounded shutdown.

- [x] Explicit `streamable-http` transport starts the same server/tool contract.
- [x] Default bind is `127.0.0.1:8765`.
- [x] IPv6 loopback handling is explicit/tested if supported.
- [x] Non-loopback bind fails startup before listener creation.
- [x] Preserve official SDK DNS-rebinding protection.
- [x] Preserve official SDK Host/Origin validation; do not disable it as a deployment workaround.
- [x] Bound active MCP sessions/connections where the SDK exposes supported controls.
- [x] Add loopback Streamable HTTP tool-list smoke.
- [x] Compare stdio and HTTP tool names/schemas/annotations for semantic equivalence.
- [x] Add bad Host/Origin rejection regression if supported by the SDK test surface.
- [x] Do not add legacy SSE as a compatibility fallback.

## MCP-010 — Living documentation and security model

**Reconciled complete:** `docs/MCP_SERVER.md` is the authoritative living MCP guide. `test_mcp_documentation_contract.py` proves all required living-document targets link to it and that configuration, catalog, security, install, transport, and memory-limit statements track source.

- [x] Create living `docs/MCP_SERVER.md` once runnable functionality exists.
- [x] Document architecture: MCP -> Python client -> authenticated controller API -> worker/VNC.
- [x] Document core install vs `[mcp]` optional install.
- [x] Document `vnc-remote-control-mcp` invocation.
- [x] Document stdio as default transport.
- [x] Document Streamable HTTP loopback-only policy.
- [x] Document remote access through a trusted tunnel/proxy boundary; do not instruct operators to bind publicly without auth.
- [x] Document read-only default and explicit mutation opt-in.
- [x] Document every MCP config variable/default/range.
- [x] Document secret-file-only controller token policy.
- [x] Document Python token-memory limitation without overstating zeroization.
- [x] Document sensitive payload no-logging rule.
- [x] Document unknown-outcome/non-retry-safe mutation behavior and command-status recovery.
- [x] Update root `README.md`.
- [x] Update `python/README.md`.
- [x] Update `docs/OPERATOR_GUIDE.md`.
- [x] Update `deploy/README.md`.
- [x] Update `SECURITY.md`.
- [x] Update `docs/README.md` current living documentation index.
- [x] Update `CLAUDE.md`/`CONTRIBUTING.md` if MCP-specific development/validation commands become authoritative.
- [x] Add documentation freshness/contract tests for the MCP living docs.

## MCP-011 — MCP E2E against real controller/TigerVNC

**Reconciled complete:** `tests/mcp_e2e.py` and `tests/mcp-e2e/run.sh` exercise official MCP client -> MCP adapter -> typed HTTP client -> production controller -> worker -> LibVNC -> isolated TigerVNC. Current exact-master CI `34147921952` passed the permanent E2E step.

- [x] Add bounded MCP E2E harness using the production controller and isolated desktop image.
- [x] Mount controller bearer token through a file, never raw env/CLI.
- [x] Start MCP adapter only after deterministic dependency setup; no sleep-only readiness assumption.
- [x] Discover read tools in default mutation-disabled mode.
- [x] Assert mutation tools are absent by default.
- [x] Query status/display through MCP.
- [x] Capture a real screenshot through MCP image content.
- [x] Start mutation-enabled MCP instance explicitly.
- [x] Move/click pointer through MCP and verify desktop-side effect using existing test app/state mechanism.
- [x] Type keyboard text through MCP and verify without logging payload.
- [x] Set/read clipboard through MCP and verify without logging payload.
- [x] Inspect command status through MCP.
- [x] Request reconnect through MCP and verify bounded recovery.
- [x] Verify raw VNC remains unpublished.
- [x] Verify MCP/controller teardown is bounded and leaves no test container/process leak.
- [x] Add negative path proving controller/tool failure does not become MCP success.

## MCP-012 — CI, supply-chain, and permanent-gate integration

**Validated:** exact candidate SHA `6d2d41fc0a14f85992c4125f39472fad15aba203`; CI `34141589371` and Release Gates `34141589310` both passed. PR #40 merged that candidate to exact `master` SHA `38f83f5a950392b8464e8b5c98d5f2df945c41ec`; merged-master CI `34145291715` and Release Gates `34145291678` both passed.

### Regular CI

- [x] Install Python MCP extra at the reviewed dependency pin in the MCP test job/path.
- [x] Keep core-client test path capable of running without MCP installed where practical.
- [x] Run MCP unit/contract tests in permanent CI.
- [x] Run stdio transport smoke in permanent CI.
- [x] Run loopback Streamable HTTP smoke in permanent CI.
- [x] Ensure Ruff/Pylint/mypy cover new modules/tests.

### Release/security

- [x] Determine whether current dependency/license inventory covers Python MCP runtime dependencies.
- [x] If not, add explicit auditable Python MCP dependency/license inventory rather than silently excluding it.
- [x] Review MCP SDK/transitive licenses against project release policy.
- [x] Preserve immutable third-party GitHub Action pins.
- [x] Preserve Gitleaks/Trivy/VEX/SBOM/cargo-deny/sanitizer/Miri gates.
- [x] Add MCP E2E to an appropriate permanent workflow before final sign-off.
- [x] Do not add `continue-on-error` to MCP gates.

## MCP-013 — Cross-cutting unsafe-fallback and silent-failure audit

**Validated audit checkpoint:** `5f70bd064c663a00843369f791a2cdf460734737` passed CI `34642850866` and Release Gates `34642850991`. Detailed rationale is in `docs/VNC_REMOTE_CONTROL_SERVER_MCP_UNSAFE_FALLBACK_AUDIT_2026-09-11.md`; `tests/test_mcp_unsafe_fallback_contract.py` keeps the key static conclusions permanent.

- [x] Search MCP Python code for broad `except Exception` paths and classify every survivor.
- [x] Reject empty-success returns from exceptions.
- [x] Search for `pass`, ignored return values, `.get(..., default)` behavior that could hide invalid config/protocol state, and broad compatibility fallbacks.
- [x] Search for mutation retry loops/backoff wrappers and prove none can replay uncertain input.
- [x] Search logs/tracing for tool arguments/results, Authorization headers, token values, text, clipboard, and screenshots.
- [x] Search transport setup for disabled Host/Origin/DNS-rebinding checks.
- [x] Search configuration for raw secret env/CLI support.
- [x] Search tests for mocks that accidentally bypass the one-call/no-retry invariant.
- [x] Review dependency import fallback behavior; missing MCP dependency must be explicit.
- [x] Record every surviving intentional ignored result/fallback with nearby rationale.

## MCP-014 — Exact candidate and merged-master validation

**Final validation:** PR #43 exact final candidate `446bfcf09a4a69b523b0352ff573f34b5a62dd61` passed CI `34647222799` and Release Gates `34647222812`. It was merged through the repository's policy-approved squash path to exact implementation `master` `a31e2f3fdf77085292fe65648d8741613f91cb38`, which passed fresh CI `34658956284` and fresh Release Gates `34658956281`.

A prior merged generation `bb4178455a727f7baaebac46a31157f1c3713baa` exposed a race-sensitive R13 restart test in CI `34644165866` even though MCP E2E and Release Gates `34644166258` passed. The root cause was investigated and fixed rather than rerun or gate-weakened: the deliberate restart can briefly expose the intentionally SIGTERM-stopped desktop generation (`exit 143`). The final restart helper tolerates only that exact clean intentional-stop snapshot, then delegates to the existing strict health waiter; unexpected terminal/unhealthy states remain fail-closed.

### Candidate freeze

- [x] Reconcile all MCP-001 through MCP-013 checkboxes against actual source/tests/docs/workflows.
- [x] Record exact final candidate SHA.
- [x] Run regular CI on that exact SHA.
- [x] Record CI run ID/conclusion.
- [x] Run Release Gates on that exact SHA.
- [x] Record Release Gates run ID/conclusion.
- [x] Inspect every failure and fix root cause without weakening gates.
- [x] If any fix changes candidate SHA, require both permanent workflows again on the new exact generation.
- [x] Require both workflows green on one exact candidate SHA before merge/sign-off.

### Exact merged master

- [x] Record exact merged `master` SHA.
- [x] Require fresh regular CI on exact merged `master`.
- [x] Record final master CI run ID/conclusion.
- [x] Require fresh Release Gates on exact merged `master`.
- [x] Record final master Release Gates run ID/conclusion.
- [x] Re-review current VEX status/expiry at final validation time.

VEX re-review on 2026-09-11 confirmed repository metadata `reviewed_at: 2026-08-31`, `expires_at: 2026-09-30`, tracking issue `7`. The metadata was unexpired and exact final candidate/master Release Gates both passed exact CRITICAL VEX enforcement.

## MCP-015 — Final evidence and completion

**Evidence:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md` records the final architecture, catalog, configuration/security model, SDK/protocol target, transport/E2E validation, dependency/license closure, unsafe-fallback audit, exact-generation validation history, VEX review, and completion rationale.

- [x] Create `docs/VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md`.
- [x] Record starting baseline and V2 prerequisite completion.
- [x] Record final MCP architecture and tool catalog.
- [x] Record exact SDK version and protocol target.
- [x] Record config defaults/bounds and mutation-disabled default.
- [x] Record controller-token secret-file policy and Python memory limitation.
- [x] Record tool annotations.
- [x] Record unknown-outcome/no-retry policy and regression evidence.
- [x] Record both transport validation results.
- [x] Record real controller/TigerVNC MCP E2E evidence.
- [x] Record dependency/license/supply-chain review.
- [x] Record unsafe-fallback/silent-failure audit and surviving intentional ignores.
- [x] Record exact final candidate SHA plus CI/Release Gates IDs/conclusions.
- [x] Record exact final merged-master SHA plus CI/Release Gates IDs/conclusions.
- [x] Re-review every TODO checkbox against final source/tests/workflows/docs/evidence.
- [x] Confirm no checkbox is closed solely because a commit message says so.
- [x] Declare MCP phase complete only when all applicable MCP-001 through MCP-015 requirements are genuinely satisfied.

## MCP completion declaration

The MCP implementation phase is complete. Every applicable MCP-001 through MCP-015 checkbox has been reconciled against source, tests, workflow configuration, living documentation, audit records, and exact-generation CI evidence. No item is closed solely from a commit message or historical green run, and no release/security gate was weakened for sign-off.

The authoritative validated implementation generation is `a31e2f3fdf77085292fe65648d8741613f91cb38`, with CI `34658956284` and Release Gates `34658956281` both successful. The final MCP/TigerVNC E2E and the corrected R13 restart/resource validation both passed on that exact `master` SHA.

The CRITICAL VEX metadata remains `reviewed_at: 2026-08-31`, `expires_at: 2026-09-30`; exact CRITICAL VEX enforcement passed the final candidate and merged-master Release Gates. This documentation-only closeout change must itself remain green under the permanent workflows before merge.
