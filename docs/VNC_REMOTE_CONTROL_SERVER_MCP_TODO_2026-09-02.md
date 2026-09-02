# VNC Remote Control Server — MCP Server TODO

**Date:** 2026-09-02  
**Specification:** `docs/VNC_REMOTE_CONTROL_SERVER_MCP_SPEC_2026-09-02.md`  
**Starting repository `master`:** `e3a719600b03b5622ceec9e013dfc9ef94c12702`  
**Specification commit:** `b454c754291a950a6d21ede9dd9594e5e5e45530`

This TODO is evidence-driven. A checkbox closes only when source, tests, workflow configuration, documentation, or external validation proves it. Do not close tasks from commit messages alone. Do not weaken an existing gate to make the MCP phase green.

## MCP-001 — Establish the MCP package and executable

- [ ] Add an optional Python dependency group for MCP using reviewed pin `mcp==2.1.1`.
- [ ] Preserve zero third-party runtime dependencies for users installing the core Python client without the MCP extra.
- [ ] Add console entry point `vnc-remote-control-mcp`.
- [ ] Add the minimal importable MCP server module without starting network/process activity at import time.
- [ ] Expose a deterministic server-construction function for tests.
- [ ] Verify missing MCP optional dependency produces an explicit actionable startup/import error, not a silent feature downgrade.
- [ ] Add package/entry-point contract tests.
- [ ] Update `python/README.md` with the optional install form after the executable exists.

## MCP-002 — Implement fail-closed MCP configuration and secret loading

### Controller configuration

- [ ] Implement `VRC_MCP_CONTROLLER_URL`, default `http://127.0.0.1:8080`.
- [ ] Reuse `VncRemoteControlClient` URL validation; reject credentials/query/fragment.
- [ ] Implement required `VRC_MCP_CONTROLLER_TOKEN_FILE`.
- [ ] Do not accept a raw controller token through an env var, CLI argument, URL, source constant, or config fallback.
- [ ] Implement `VRC_MCP_CONTROLLER_TIMEOUT_SECONDS`, default `5`, range `0.1..=60`.
- [ ] Reject malformed, non-finite, zero, negative, or out-of-range timeout values.

### Secret-file policy

- [ ] Reject unreadable metadata.
- [ ] Reject non-regular files.
- [ ] Reject empty or oversized files using an explicit bounded maximum.
- [ ] On Unix reject group/other write or execute permission bits, matching controller policy.
- [ ] Reject invalid UTF-8.
- [ ] Trim trailing CR/LF only.
- [ ] Reject empty-after-trim and embedded NUL.
- [ ] Ensure secret-file errors contain no secret bytes.
- [ ] Ensure config/repr/log output reports only `token_set`/path metadata, never the token value.
- [ ] Document that Python cannot provide the Rust `SecretString` volatile-zeroization guarantee.

### Capability/bounds configuration

- [ ] Implement `VRC_MCP_ALLOW_MUTATIONS`, default false.
- [ ] Reject ambiguous/malformed boolean spellings instead of truthy fallback parsing.
- [ ] Implement `VRC_MCP_MAX_CONCURRENT_CALLS`, default `8`, range `1..=64`.
- [ ] Implement `VRC_MCP_TRANSPORT`, default `stdio`, accepted `stdio|streamable-http` only.
- [ ] Implement `VRC_MCP_HTTP_HOST`, default `127.0.0.1`.
- [ ] Reject non-loopback Streamable HTTP binds in the initial release.
- [ ] Implement `VRC_MCP_HTTP_PORT`, default `8765`, range `1..=65535`.
- [ ] Add deterministic config parser tests including non-Unicode environment-value failures if the platform/API exposes them.

## MCP-003 — Build common bounded controller-call execution

- [ ] Create one adapter-owned bounded concurrency limiter for all controller calls.
- [ ] Execute synchronous `VncRemoteControlClient` calls outside the MCP event loop.
- [ ] Ensure waiting work is bounded; do not submit unbounded worker-thread jobs ahead of the limiter.
- [ ] Ensure cancellation releases limiter capacity.
- [ ] Ensure clean/error/unwind paths release limiter capacity.
- [ ] Do not add an adapter retry loop.
- [ ] Add saturation tests proving at most the configured number of controller calls execute concurrently.
- [ ] Add recovery test proving capacity returns after a call exits/fails.
- [ ] Add shutdown test proving no adapter-owned worker work is orphaned indefinitely.

## MCP-004 — Implement read-only MCP tool surface

### `vnc_get_status`

- [ ] Register tool with no input arguments.
- [ ] Map exactly to `VncRemoteControlClient.get_status()`.
- [ ] Return all typed status fields with stable names/types.
- [ ] Add read-only/non-destructive/idempotent/closed-world annotations.

### `vnc_get_display`

- [ ] Register tool with no input arguments.
- [ ] Map exactly to `get_display()`.
- [ ] Return width/height/depth/revision/timestamp/completeness.
- [ ] Add read-only/non-destructive/idempotent/closed-world annotations.

### `vnc_get_clipboard`

- [ ] Register tool with no input arguments.
- [ ] Map exactly to `get_clipboard()`.
- [ ] Return text/revision/timestamp without logging the text.
- [ ] Add read-only/non-destructive/idempotent/open-world annotations.

### `vnc_get_command_status`

- [ ] Require integer `command_id >= 1` in the MCP schema.
- [ ] Map exactly to `get_command_status(command_id)`.
- [ ] Preserve command state/failure/retry-safe semantics.
- [ ] Add read-only/non-destructive/idempotent/closed-world annotations.

### `vnc_get_metrics`

- [ ] Register tool with no input arguments.
- [ ] Map exactly to `get_metrics()`.
- [ ] Preserve the controller's bounded metrics text.
- [ ] Add read-only/non-destructive/idempotent/closed-world annotations.

### Catalog truthfulness

- [ ] Read-only tools are always present when server construction succeeds.
- [ ] No mutation tool appears when mutations are disabled.
- [ ] Add tool-list/schema/annotation snapshot or equivalent contract tests.

## MCP-005 — Implement native MCP screenshot output

- [ ] Register `vnc_get_screenshot` with no initial input arguments.
- [ ] Map exactly to `get_screenshot()` without ETag optimization in the initial tool contract.
- [ ] Return PNG bytes as native MCP image content rather than JSON/base64 text.
- [ ] Preserve only sanitized screenshot metadata that the SDK can return alongside image content without duplicating image bytes.
- [ ] Never log screenshot bytes/base64.
- [ ] Reject/propagate malformed screenshot/controller protocol failures; do not return a placeholder image.
- [ ] Add read-only/non-destructive/idempotent/open-world annotations.
- [ ] Add deterministic image-content tests.
- [ ] Add size/boundedness regression consistent with the controller screenshot limit.

## MCP-006 — Implement mutation tool schemas and exact one-call mappings

Mutation tools are registered only when `VRC_MCP_ALLOW_MUTATIONS=true`.

### Pointer

- [ ] `vnc_move_pointer(x>=0, y>=0)` -> `move_pointer`.
- [ ] `vnc_set_pointer_button(x>=0, y>=0, button, pressed)` -> `set_pointer_button`.
- [ ] `vnc_click_pointer(x>=0, y>=0, button)` -> `click_pointer`.
- [ ] `vnc_double_click_pointer(x>=0, y>=0, button, interval_ms=20..1000)` -> `double_click_pointer`.
- [ ] `vnc_scroll_pointer(x>=0, y>=0, delta_y=-100..100)` -> `scroll_pointer`.
- [ ] Do not expose nonzero horizontal scroll.

### Keyboard

- [ ] `vnc_set_keyboard_key(key, action=down|up)` -> `set_keyboard_key`.
- [ ] `vnc_send_keyboard_chord(keys[1..16])` -> `send_keyboard_chord`.
- [ ] `vnc_type_keyboard_text(text)` -> `type_keyboard_text`.
- [ ] Match controller printable-ASCII/tab/CR/LF and 16 KiB text bounds in MCP schema/preflight.
- [ ] Never log typed text.

### Clipboard/reconnect

- [ ] `vnc_set_clipboard(text)` -> `set_clipboard`.
- [ ] Match controller valid-UTF-8/no-NUL/1 MiB encoded-byte bound.
- [ ] Never log clipboard text.
- [ ] `vnc_request_reconnect()` -> `request_reconnect`.

### Mutation annotations

- [ ] Every mutation tool: `readOnlyHint=false`.
- [ ] Every mutation tool: `destructiveHint=true`.
- [ ] Every mutation tool: `idempotentHint=false`.
- [ ] Every mutation tool: `openWorldHint=true`.
- [ ] Add exact one-client-call tests for every mutation tool.
- [ ] Prove no mutation handler contains an automatic retry/replay loop.

## MCP-007 — Preserve fail-closed command-outcome semantics

### Normal success/failure

- [ ] Terminal success returns the controller `command_id` and `status="succeeded"` without inventing a second acceptance state.
- [ ] Structured accepted-command `ApiError` preserves sanitized `command_id`, `outcome`, `retry_safe`, `request_id` where available.
- [ ] A controller-reported terminal failure is never retried.

### Known unknown outcome

- [ ] Map `CommandOutcomeUnknownError` to explicit `kind="command_outcome_unknown"`.
- [ ] Preserve command ID.
- [ ] Preserve/request `request_id` when present.
- [ ] Set `outcome="unknown"`, `retry_safe=false`.
- [ ] Tell the caller to use `vnc_get_command_status(command_id)` before deciding on a next mutation.
- [ ] Do not poll-and-replay automatically.

### Unknown outcome without command ID

- [ ] Mutation `TransportError` -> `kind="mutation_outcome_unknown"`, `command_id=null`, `retry_safe=false`.
- [ ] Mutation timeout without structured command context -> same conservative classification.
- [ ] Mutation `ProtocolError` after request issuance -> same conservative classification.
- [ ] Unexpected adapter failure after mutation issuance -> same conservative classification unless the adapter can prove no request was sent.
- [ ] Error text explicitly warns that replay is unsafe.
- [ ] Never fabricate a command ID.

### Read-only errors

- [ ] Read-only `TransportError` remains `transport_error`, not mutation-unknown.
- [ ] Read-only `ProtocolError` remains `controller_protocol_error`.
- [ ] Read-only errors contain no raw body/secret/payload data.

### Regression matrix

- [ ] Add a no-retry counting fake proving each ambiguous mutation invokes the client exactly once.
- [ ] Add known-command-ID timeout regression and subsequent `vnc_get_command_status` inspection.
- [ ] Add no-command-ID transport regression.
- [ ] Add malformed mutation-response regression.
- [ ] Add terminal failed-command regression.

## MCP-008 — Implement stdio transport

- [ ] Default executable transport is stdio.
- [ ] stdout contains MCP protocol only; diagnostics go to stderr.
- [ ] No startup banner/noise corrupts stdio framing.
- [ ] SIGINT/SIGTERM/process EOF lead to bounded clean shutdown as supported by SDK/runtime.
- [ ] Add official-SDK client smoke for tool discovery.
- [ ] Add stdio read-tool invocation smoke.
- [ ] Add stdio mutation-disabled catalog smoke.
- [ ] Add stdio mutation-enabled invocation smoke.

## MCP-009 — Implement loopback Streamable HTTP transport

- [ ] Explicit `streamable-http` transport starts the same server/tool contract.
- [ ] Default bind is `127.0.0.1:8765`.
- [ ] IPv6 loopback handling is explicit/tested if supported.
- [ ] Non-loopback bind fails startup before listener creation.
- [ ] Preserve official SDK DNS-rebinding protection.
- [ ] Preserve official SDK Host/Origin validation; do not disable it as a deployment workaround.
- [ ] Bound active MCP sessions/connections where the SDK exposes supported controls.
- [ ] Add loopback Streamable HTTP tool-list smoke.
- [ ] Compare stdio and HTTP tool names/schemas/annotations for semantic equivalence.
- [ ] Add bad Host/Origin rejection regression if supported by the SDK test surface.
- [ ] Do not add legacy SSE as a compatibility fallback.

## MCP-010 — Living documentation and security model

- [ ] Create living `docs/MCP_SERVER.md` once runnable functionality exists.
- [ ] Document architecture: MCP -> Python client -> authenticated controller API -> worker/VNC.
- [ ] Document core install vs `[mcp]` optional install.
- [ ] Document `vnc-remote-control-mcp` invocation.
- [ ] Document stdio as default transport.
- [ ] Document Streamable HTTP loopback-only policy.
- [ ] Document remote access through a trusted tunnel/proxy boundary; do not instruct operators to bind publicly without auth.
- [ ] Document read-only default and explicit mutation opt-in.
- [ ] Document every MCP config variable/default/range.
- [ ] Document secret-file-only controller token policy.
- [ ] Document Python token-memory limitation without overstating zeroization.
- [ ] Document sensitive payload no-logging rule.
- [ ] Document unknown-outcome/non-retry-safe mutation behavior and command-status recovery.
- [ ] Update root `README.md`.
- [ ] Update `python/README.md`.
- [ ] Update `docs/OPERATOR_GUIDE.md`.
- [ ] Update `deploy/README.md`.
- [ ] Update `SECURITY.md`.
- [ ] Update `docs/README.md` current living documentation index.
- [ ] Update `CLAUDE.md`/`CONTRIBUTING.md` if MCP-specific development/validation commands become authoritative.
- [ ] Add documentation freshness/contract tests for the MCP living docs.

## MCP-011 — MCP E2E against real controller/TigerVNC

- [ ] Add bounded MCP E2E harness using the production controller and isolated desktop image.
- [ ] Mount controller bearer token through a file, never raw env/CLI.
- [ ] Start MCP adapter only after deterministic dependency setup; no sleep-only readiness assumption.
- [ ] Discover read tools in default mutation-disabled mode.
- [ ] Assert mutation tools are absent by default.
- [ ] Query status/display through MCP.
- [ ] Capture a real screenshot through MCP image content.
- [ ] Start mutation-enabled MCP instance explicitly.
- [ ] Move/click pointer through MCP and verify desktop-side effect using existing test app/state mechanism.
- [ ] Type keyboard text through MCP and verify without logging payload.
- [ ] Set/read clipboard through MCP and verify without logging payload.
- [ ] Inspect command status through MCP.
- [ ] Request reconnect through MCP and verify bounded recovery.
- [ ] Verify raw VNC remains unpublished.
- [ ] Verify MCP/controller teardown is bounded and leaves no test container/process leak.
- [ ] Add negative path proving controller/tool failure does not become MCP success.

## MCP-012 — CI, supply-chain, and permanent-gate integration

### Regular CI

- [ ] Install Python MCP extra at the reviewed dependency pin in the MCP test job/path.
- [ ] Keep core-client test path capable of running without MCP installed where practical.
- [ ] Run MCP unit/contract tests in permanent CI.
- [ ] Run stdio transport smoke in permanent CI.
- [ ] Run loopback Streamable HTTP smoke in permanent CI.
- [ ] Ensure Ruff/Pylint/mypy cover new modules/tests.

### Release/security

- [ ] Determine whether current dependency/license inventory covers Python MCP runtime dependencies.
- [ ] If not, add explicit auditable Python MCP dependency/license inventory rather than silently excluding it.
- [ ] Review MCP SDK/transitive licenses against project release policy.
- [ ] Preserve immutable third-party GitHub Action pins.
- [ ] Preserve Gitleaks/Trivy/VEX/SBOM/cargo-deny/sanitizer/Miri gates.
- [ ] Add MCP E2E to an appropriate permanent workflow before final sign-off.
- [ ] Do not add `continue-on-error` to MCP gates.

## MCP-013 — Cross-cutting unsafe-fallback and silent-failure audit

- [ ] Search MCP Python code for broad `except Exception` paths and classify every survivor.
- [ ] Reject empty-success returns from exceptions.
- [ ] Search for `pass`, ignored return values, `.get(..., default)` behavior that could hide invalid config/protocol state, and broad compatibility fallbacks.
- [ ] Search for mutation retry loops/backoff wrappers and prove none can replay uncertain input.
- [ ] Search logs/tracing for tool arguments/results, Authorization headers, token values, text, clipboard, and screenshots.
- [ ] Search transport setup for disabled Host/Origin/DNS-rebinding checks.
- [ ] Search configuration for raw secret env/CLI support.
- [ ] Search tests for mocks that accidentally bypass the one-call/no-retry invariant.
- [ ] Review dependency import fallback behavior; missing MCP dependency must be explicit.
- [ ] Record every surviving intentional ignored result/fallback with nearby rationale.

## MCP-014 — Exact candidate and merged-master validation

### Candidate freeze

- [ ] Reconcile all MCP-001 through MCP-013 checkboxes against actual source/tests/docs/workflows.
- [ ] Record exact final candidate SHA.
- [ ] Run regular CI on that exact SHA.
- [ ] Record CI run ID/conclusion.
- [ ] Run Release Gates on that exact SHA.
- [ ] Record Release Gates run ID/conclusion.
- [ ] Inspect every failure and fix root cause without weakening gates.
- [ ] If any fix changes candidate SHA, require both permanent workflows again on the new exact generation.
- [ ] Require both workflows green on one exact candidate SHA before merge/sign-off.

### Exact merged master

- [ ] Record exact merged `master` SHA.
- [ ] Require fresh regular CI on exact merged `master`.
- [ ] Record final master CI run ID/conclusion.
- [ ] Require fresh Release Gates on exact merged `master`.
- [ ] Record final master Release Gates run ID/conclusion.
- [ ] Re-review current VEX status/expiry at final validation time.

## MCP-015 — Final evidence and completion

- [ ] Create `docs/VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md`.
- [ ] Record starting baseline and V2 prerequisite completion.
- [ ] Record final MCP architecture and tool catalog.
- [ ] Record exact SDK version and protocol target.
- [ ] Record config defaults/bounds and mutation-disabled default.
- [ ] Record controller-token secret-file policy and Python memory limitation.
- [ ] Record tool annotations.
- [ ] Record unknown-outcome/no-retry policy and regression evidence.
- [ ] Record both transport validation results.
- [ ] Record real controller/TigerVNC MCP E2E evidence.
- [ ] Record dependency/license/supply-chain review.
- [ ] Record unsafe-fallback/silent-failure audit and surviving intentional ignores.
- [ ] Record exact final candidate SHA plus CI/Release Gates IDs/conclusions.
- [ ] Record exact final merged-master SHA plus CI/Release Gates IDs/conclusions.
- [ ] Re-review every TODO checkbox against final source/tests/workflows/docs/evidence.
- [ ] Confirm no checkbox is closed solely because a commit message says so.
- [ ] Declare MCP phase complete only when all applicable MCP-001 through MCP-015 requirements are genuinely satisfied.
