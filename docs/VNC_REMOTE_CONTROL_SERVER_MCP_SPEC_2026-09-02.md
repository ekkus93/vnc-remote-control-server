# VNC Remote Control Server — MCP Server Specification

**Date:** 2026-09-02  
**Starting repository `master`:** `e3a719600b03b5622ceec9e013dfc9ef94c12702`  
**Validated controller implementation generation:** `4956a624be10ddb4b23aa23bcea23560b9c13a24`  
**Status:** implementation specification

## 1. Purpose

Add a Model Context Protocol (MCP) server that exposes the already-hardened VNC Remote Control Server API to MCP-capable hosts without creating a second remote-control authority or bypassing controller safety semantics.

The MCP server is an adapter. It MUST call the existing typed Python client, which in turn calls the bearer-authenticated controller HTTP API. It MUST NOT talk RFB/VNC directly, call the native LibVNC shim, reach into Rust worker state, or reimplement command execution.

The initial implementation targets the MCP `2026-07-28` protocol generation through the official Python MCP SDK v2. The initial dependency target is `mcp==2.1.1`; dependency updates are deliberate reviewed changes rather than unbounded upgrades.

Reference material:

- MCP specification release: https://blog.modelcontextprotocol.io/posts/2026-07-28/
- Official Python SDK: https://py.sdk.modelcontextprotocol.io/
- PyPI package: https://pypi.org/project/mcp/

## 2. Design principles

1. **One control authority.** The Rust controller remains authoritative for authentication, command admission, queueing, rate limits, VNC session state, framebuffer/clipboard authority, input quarantine, reconnect behavior, and command outcomes.
2. **No blind mutation retry.** An MCP mutation is never automatically replayed after a timeout, transport error, malformed response, protocol error, or unknown command outcome.
3. **Fail closed.** Invalid configuration, unreadable/invalid secret files, unsupported transport configuration, impossible bounds, and internal adapter invariant failures are explicit failures.
4. **Read-only by default.** Mutation tools are absent from the advertised MCP tool catalog unless the operator explicitly enables them.
5. **No payload logging.** Typed text, clipboard contents, screenshots, bearer tokens, and raw MCP tool arguments/results containing those values are never logged.
6. **Bound every resource.** Concurrent tool calls, controller request timeouts, input sizes, screenshot handling, and HTTP listener configuration are bounded.
7. **Transport does not change semantics.** stdio and Streamable HTTP expose the same tool names, schemas, annotations, result shapes, and error behavior.
8. **No compatibility success fallback.** Unsupported SDK/protocol behavior causes an explicit startup/test failure rather than silently dropping annotations, output validation, auth, or error context.

## 3. Architecture

```text
MCP host
   |
   | stdio or Streamable HTTP
   v
vnc-remote-control-mcp
   |
   | typed calls only
   v
VncRemoteControlClient
   |
   | bearer-authenticated HTTP /v1/*
   v
controller-api (Rust)
   |
   v
worker -> libvnc-adapter -> isolated TigerVNC desktop
```

### 3.1 Implementation location

The MCP adapter belongs in the existing Python distribution so it can reuse the validated client and public models:

- `python/src/vnc_remote_control/mcp_server.py` — entry point/server construction;
- `python/src/vnc_remote_control/mcp_config.py` — fail-closed configuration and secret-file loading;
- `python/src/vnc_remote_control/mcp_tools.py` — tool implementations and result/error normalization;
- `python/src/vnc_remote_control/mcp_models.py` — adapter-owned structured output models when useful;
- `python/pyproject.toml` — optional MCP dependency and console entry point.

The concrete file split may be reduced if the implementation stays clearer in fewer modules, but production behavior MUST remain separable into configuration, tool mapping, and transport startup for deterministic tests.

### 3.2 Console entry point

Add:

`vnc-remote-control-mcp = "vnc_remote_control.mcp_server:main"`

The core HTTP client remains third-party-dependency-free. MCP support is an optional install extra, not a mandatory dependency for ordinary Python client users.

Proposed optional dependency:

```toml
mcp = ["mcp==2.1.1"]
```

## 4. Configuration

### 4.1 Controller connection

- `VRC_MCP_CONTROLLER_URL`
  - default: `http://127.0.0.1:8080`;
  - must be absolute `http://` or `https://`;
  - credentials, query strings, and fragments are rejected through the existing client validation.
- `VRC_MCP_CONTROLLER_TOKEN_FILE`
  - required;
  - contains the controller bearer token;
  - the token value MUST NOT be accepted directly from an environment variable, CLI argument, URL, source file, or log field.
- `VRC_MCP_CONTROLLER_TIMEOUT_SECONDS`
  - default: `5`;
  - accepted range: `0.1..=60`;
  - malformed, non-finite, zero, negative, or out-of-range values fail startup.

The adapter secret reader MUST mirror the controller secret-file policy where practical:

- metadata must be readable;
- path must resolve to a regular file;
- file size must be nonzero and bounded;
- on Unix, group/other write or execute permissions are forbidden;
- content must be valid UTF-8;
- trailing CR/LF may be removed;
- empty-after-trim and embedded NUL are rejected;
- errors contain the path and fixed reason only, never secret bytes.

The Python runtime cannot provide the Rust `SecretString` volatile-zeroization guarantee; documentation MUST say so rather than imply otherwise. The process MUST still avoid unnecessary token copies and never expose the token through `repr`, exception text, logs, tool results, or MCP metadata.

### 4.2 Capability mode

- `VRC_MCP_ALLOW_MUTATIONS`
  - default: `0` / false;
  - accepted values are explicit documented booleans only;
  - when false, mutation tools are not registered at all;
  - when true, the complete mutation tool set is registered.

Do not register mutation tools and then return a generic "disabled" error. Tool discovery itself must truthfully represent the configured capability surface.

### 4.3 MCP transport

- `VRC_MCP_TRANSPORT`
  - default: `stdio`;
  - accepted: `stdio`, `streamable-http`;
  - legacy SSE is not part of the initial supported surface.
- `VRC_MCP_HTTP_HOST`
  - default: `127.0.0.1`;
  - initial release permits loopback addresses only;
  - non-loopback bind requests fail startup.
- `VRC_MCP_HTTP_PORT`
  - default: `8765`;
  - accepted range: `1..=65535`.

The first release intentionally does not implement a bespoke public-network MCP authentication protocol. Remote access is expected to use a trusted tunnel/reverse-proxy/authentication boundary. The MCP process itself remains loopback-only until a separate reviewed remote-auth task explicitly changes this rule.

The Streamable HTTP configuration MUST retain the official SDK's DNS-rebinding/Host/Origin protections rather than disabling them to make a deployment work.

### 4.4 Adapter concurrency

- `VRC_MCP_MAX_CONCURRENT_CALLS`
  - default: `8`;
  - accepted range: `1..=64`.

All controller calls share one process-owned bounded semaphore/limiter. The synchronous `VncRemoteControlClient` MUST execute outside the MCP event loop through a bounded worker-thread path. No unbounded executor submission is allowed.

## 5. Tool surface

All tool names are prefixed with `vnc_` so hosts that flatten tools from multiple MCP servers still expose an unambiguous namespace.

### 5.1 Read-only tools

These tools are always registered.

#### `vnc_get_status`

Input: none.  
Returns the typed controller status fields from `/v1/status`.

Annotations:

- `readOnlyHint=true`
- `destructiveHint=false`
- `idempotentHint=true`
- `openWorldHint=false`

#### `vnc_get_display`

Input: none.  
Returns width, height, depth, framebuffer revision, update timestamp, and completeness from `/v1/display`.

Annotations: read-only, non-destructive, idempotent, closed-world.

#### `vnc_get_screenshot`

Input: none in the initial contract.  
Returns the current PNG as MCP image content plus sanitized metadata such as ETag/request ID when the SDK result model permits it without embedding the image into JSON text.

The screenshot bytes MUST NOT be logged. A malformed/non-PNG controller response remains a protocol/tool failure; no placeholder image is returned.

Annotations:

- read-only;
- non-destructive;
- idempotent as an operation, while acknowledging the captured desktop can change between calls;
- `openWorldHint=true` because visible desktop content may originate outside the controller trust boundary.

#### `vnc_get_clipboard`

Input: none.  
Returns current clipboard text plus revision/timestamp.

Clipboard text MUST NOT be logged. The MCP caller is an explicit recipient of this sensitive product data.

Annotations: read-only, non-destructive, idempotent, `openWorldHint=true`.

#### `vnc_get_command_status`

Input:

- `command_id`: integer, minimum `1`.

Returns exact retained command state, failure metadata, and `retry_safe` from `/v1/commands/{command_id}`.

Annotations: read-only, non-destructive, idempotent, closed-world.

#### `vnc_get_metrics`

Input: none.  
Returns the controller's bounded Prometheus text. This tool is operational/debugging data and MUST remain bounded by the controller's existing metrics response contract.

Annotations: read-only, non-destructive, idempotent, closed-world.

### 5.2 Mutation tools

These tools are registered only when `VRC_MCP_ALLOW_MUTATIONS=true`.

#### `vnc_move_pointer`

- `x`: integer >= 0
- `y`: integer >= 0

#### `vnc_set_pointer_button`

- `x`: integer >= 0
- `y`: integer >= 0
- `button`: `left | middle | right`
- `pressed`: boolean

#### `vnc_click_pointer`

- `x`: integer >= 0
- `y`: integer >= 0
- `button`: `left | middle | right`

#### `vnc_double_click_pointer`

- `x`: integer >= 0
- `y`: integer >= 0
- `button`: `left | middle | right`
- `interval_ms`: integer `20..=1000`

#### `vnc_scroll_pointer`

- `x`: integer >= 0
- `y`: integer >= 0
- `delta_y`: integer `-100..=100`

Horizontal scrolling is intentionally not added because the controller public contract does not support nonzero `delta_x`.

#### `vnc_set_keyboard_key`

- `key`: controller-supported keyboard-key vocabulary
- `action`: `down | up`

#### `vnc_send_keyboard_chord`

- `keys`: array of 1..16 controller-supported keyboard keys

#### `vnc_type_keyboard_text`

- `text`: maximum 16 KiB, tab/CR/LF/printable ASCII only, matching the controller contract

The text value MUST NOT appear in logs, diagnostics, tracing attributes, exception messages, or repr output.

#### `vnc_set_clipboard`

- `text`: valid UTF-8, maximum 1 MiB encoded bytes, no embedded NUL

The clipboard value MUST NOT appear in logs, diagnostics, tracing attributes, exception messages, or repr output.

#### `vnc_request_reconnect`

Input: none.  
Requests the controller's existing rate-limited reconnect behavior.

### 5.3 Mutation annotations

All mutation tools use conservative annotations:

- `readOnlyHint=false`;
- `destructiveHint=true` because remote desktop actions may cause destructive downstream effects;
- `idempotentHint=false` even for superficially repeatable operations, because hover/UI state, event handlers, and application state can make a repeated input observably different;
- `openWorldHint=true` because the controlled desktop may interact with external systems.

Annotations are descriptive hints only. They do not replace host approval policy or server-side authorization.

## 6. Mutation outcome semantics

This section is mandatory for correctness.

### 6.1 Terminal success

A normal successful controller mutation returns the existing `CommandResponse` containing `command_id` and `status="succeeded"`. The MCP result returns those fields without inventing a second success state.

### 6.2 Controller-reported accepted-command failure

If the controller returns an `ApiError` carrying `command_id`, `outcome="failed"`, and `retry_safe=false`, the MCP tool fails with structured sanitized context preserving those fields. It MUST NOT retry.

### 6.3 Controller command timeout / known command ID

`CommandOutcomeUnknownError` is exposed as an explicit MCP tool failure containing:

- `kind="command_outcome_unknown"`;
- `command_id`;
- `request_id` when present;
- `outcome="unknown"`;
- `retry_safe=false`;
- a fixed instruction to inspect `vnc_get_command_status(command_id)` before deciding what to do next.

The adapter MUST NOT poll-and-retry the mutation on the caller's behalf.

### 6.4 Mutation transport/protocol failure without command ID

A transport failure, timeout before a structured controller error is received, malformed response, or adapter protocol failure may occur after the controller received the mutation even when the client never obtained a command ID.

For a mutation call, these failures are conservatively classified as:

- `kind="mutation_outcome_unknown"`;
- `command_id=null`;
- `outcome="unknown"`;
- `retry_safe=false`.

The error text MUST explicitly say that automatic replay is unsafe. This is stricter than the read-only error mapping and prevents the MCP layer from reintroducing the ambiguity that V1/V2 remediation removed.

### 6.5 Preflight/schema rejection

MCP/adapter validation that happens before any controller request is sent may be reported as validation failure. It is not converted into an execution failure and does not claim a command ID.

## 7. Error mapping

Every tool error is sanitized and classified. At minimum distinguish:

- `validation_error` — local schema/config preflight;
- `controller_api_error` — structured HTTP/API failure;
- `command_outcome_unknown` — controller supplied command ID but terminal result is unknown;
- `mutation_outcome_unknown` — mutation may have reached controller but no trustworthy command ID/outcome is available;
- `transport_error` — read-only call could not reach/complete controller transport;
- `controller_protocol_error` — read-only response violated the typed client contract;
- `adapter_internal_error` — unexpected adapter invariant failure.

Do not include Python tracebacks, raw response bodies, Authorization headers, text/clipboard arguments, screenshot bytes, or secrets in MCP-visible error payloads.

Unexpected internal exceptions MUST be logged only with payload-safe type/category/context and converted to an explicit tool error. They MUST NOT become an empty success result.

## 8. MCP resources, prompts, events, and tasks

Initial scope is tools only.

Not in the first implementation:

- MCP prompts;
- MCP resources mirroring the same data already available through tools;
- direct exposure of `/v1/events` as an unbounded stream;
- MCP Tasks extension;
- server-side sampling/LLM calls;
- elicitation/MRTR flows;
- browser/vision planning logic;
- OCR;
- automatic coordinate discovery or GUI-agent policy.

These can be added later only when they provide a concrete capability that cannot be expressed safely with the initial bounded tool surface.

## 9. Testing requirements

### 9.1 Configuration/security tests

Cover:

- missing token file;
- nonregular/empty/oversized token file;
- invalid UTF-8, embedded NUL, trailing newline handling;
- Unix forbidden permission bits;
- malformed controller URL;
- malformed timeout/concurrency/port booleans and bounds;
- non-loopback Streamable HTTP bind rejection;
- mutation tools absent by default and present only when explicitly enabled;
- token/payload redaction in repr/errors/log records.

### 9.2 Tool contract tests

Use injected/fake `VncRemoteControlClient` behavior to prove every tool:

- calls exactly the intended client method once;
- validates and forwards fields exactly;
- returns stable structured output;
- carries correct MCP annotations;
- does not register unsupported controller functionality.

### 9.3 Unknown-outcome regressions

Explicitly test:

- `CommandOutcomeUnknownError` preserves command ID and `retry_safe=false`;
- mutation `TransportError` is not retried and is surfaced as unknown/non-retry-safe;
- mutation `ProtocolError` is not retried and is surfaced as unknown/non-retry-safe;
- generic controller failure with terminal `failed` is not retried;
- read-only transport/protocol errors are not mislabeled as mutation outcomes;
- `vnc_get_command_status` can inspect a known timed-out command ID.

### 9.4 Transport tests

- stdio protocol smoke using official SDK client/test support;
- Streamable HTTP loopback smoke;
- identical tool catalog/schema/result semantics across transports;
- HTTP Host/Origin/DNS-rebinding protection remains enabled;
- bounded concurrent tool execution;
- clean shutdown without orphan worker threads.

### 9.5 Integration/E2E

Add a real controller/TigerVNC MCP E2E tranche that at minimum proves:

1. start isolated desktop/controller;
2. start MCP adapter with file-backed controller token;
3. inspect status/display;
4. capture screenshot through MCP;
5. enable mutations explicitly;
6. perform pointer and keyboard actions through MCP;
7. set/read clipboard through MCP without logging payloads;
8. inspect command status;
9. exercise reconnect;
10. verify mutation-disabled mode omits mutation tools;
11. verify no raw VNC publication is introduced.

The E2E harness MUST be bounded and must fail if MCP returns apparent success after a controller/tool failure.

## 10. Documentation and deployment

Update living documentation in the same implementation series:

- `README.md` — MCP capability and quick-start;
- `python/README.md` — optional extra, console command, stdio examples;
- `docs/OPERATOR_GUIDE.md` — configuration, read-only default, unknown-outcome handling;
- `deploy/README.md` — co-located/tunnel deployment and secret mounts;
- `docs/README.md` — MCP living-document pointer if a dedicated guide is added;
- `SECURITY.md` — MCP trust boundary, Python token-memory limitation, payload/logging policy, remote-listener policy;
- `CLAUDE.md` / `CONTRIBUTING.md` only if development commands or authoritative workflow guidance changes.

A dedicated living guide such as `docs/MCP_SERVER.md` SHOULD be created once the first runnable MCP server exists. This dated specification remains a historical engineering artifact.

## 11. CI and release gates

The MCP phase does not weaken any existing gate.

Required before final MCP sign-off:

- existing Rust fmt/Clippy/tests/rustdoc remain green;
- Python compile/Ruff/Pylint/mypy/unit contracts remain green;
- new MCP tests run in regular CI with the MCP optional dependency installed at the reviewed pin;
- permanent workflow action pins remain immutable;
- shell/actionlint/security/supply-chain gates remain green;
- Python MCP dependency/license inventory is explicitly reviewed if the existing release inventory does not already cover it;
- Docker/TigerVNC integration gates remain green;
- new MCP E2E gate is added to an appropriate permanent workflow before sign-off;
- both permanent `CI` and `Release Gates` pass on the same exact final candidate SHA;
- after merge, fresh `CI` and `Release Gates` pass on exact merged `master` before MCP completion is declared.

## 12. Acceptance criteria

The MCP phase is complete only when all of the following are true:

1. `vnc-remote-control-mcp` is installable through the Python package MCP extra.
2. stdio is operational and Streamable HTTP is operational on loopback.
3. read-only tools are advertised by default; mutation tools require explicit opt-in.
4. every documented tool maps to exactly one existing typed-client/controller capability.
5. screenshot output is native MCP image content, not a logged/base64 text blob.
6. no tool logs secrets, text, clipboard content, or screenshots.
7. all mutation unknown-outcome paths are explicit and non-retry-safe.
8. no mutation path performs automatic replay.
9. tool execution concurrency and controller timeout are bounded.
10. non-loopback direct HTTP bind fails closed in the initial release.
11. tests cover tool schemas, annotations, security configuration, error mapping, concurrency, both transports, and real controller/TigerVNC behavior.
12. living documentation accurately describes the implemented MCP surface.
13. no existing controller/VNC security boundary is weakened.
14. exact-candidate and exact-merged-master CI/Release Gates are green.
