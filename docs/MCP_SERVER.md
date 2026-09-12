# MCP server

This guide is the living operator/developer reference for the optional MCP adapter exposed by this repository. The dated implementation specification remains in `docs/VNC_REMOTE_CONTROL_SERVER_MCP_SPEC_2026-09-02.md` and its evidence/TODO records remain historical validation artifacts; this document describes the current supported behavior.

## Architecture

The MCP adapter is intentionally thin:

```text
MCP host/client
    -> stdio or loopback Streamable HTTP
vnc-remote-control-mcp
    -> typed VncRemoteControlClient
authenticated Rust controller HTTP API
    -> bounded controller worker
LibVNCClient adapter
    -> isolated/project-owned TigerVNC desktop
```

The MCP process does not speak RFB directly, bypass bearer authentication, reach into Rust worker state, or create a second command authority. Existing controller validation, queueing, command-outcome, reconnect, framebuffer, clipboard, and input-safety semantics remain authoritative.

## Installation

The core Python package intentionally has zero third-party runtime dependencies:

```bash
python -m pip install ./python
```

MCP support is optional and uses the reviewed exact dependency `mcp==2.1.1`:

```bash
python -m pip install './python[mcp]'
```

The console entry point is:

```bash
vnc-remote-control-mcp
```

A missing or incompatible optional MCP SDK fails explicitly with an actionable startup error. There is no silent feature downgrade or alternate-SDK compatibility path.

## Tool catalog

Read-only tools are always registered when server construction succeeds:

- `vnc_get_status`
- `vnc_get_display`
- `vnc_get_screenshot`
- `vnc_get_clipboard`
- `vnc_get_command_status`
- `vnc_get_metrics`

Mutation tools are absent unless `VRC_MCP_ALLOW_MUTATIONS=true`:

- `vnc_move_pointer`
- `vnc_set_pointer_button`
- `vnc_click_pointer`
- `vnc_double_click_pointer`
- `vnc_scroll_pointer`
- `vnc_set_keyboard_key`
- `vnc_send_keyboard_chord`
- `vnc_type_keyboard_text`
- `vnc_set_clipboard`
- `vnc_request_reconnect`

Read tools use `readOnlyHint=true`, `destructiveHint=false`, and `idempotentHint=true`. Screenshot and clipboard reads are open-world because they expose desktop-derived content; the other reads are closed-world. Mutation tools conservatively use `readOnlyHint=false`, `destructiveHint=true`, `idempotentHint=false`, and `openWorldHint=true`.

`vnc_get_screenshot` returns native MCP image content rather than JSON/base64 text.

## Configuration

| Variable | Default | Accepted value / bound |
|---|---|---|
| `VRC_MCP_CONTROLLER_URL` | `http://127.0.0.1:8080` | validated controller base URL; credentials/query/fragment rejected |
| `VRC_MCP_CONTROLLER_TOKEN_FILE` | required | validated regular secret file |
| `VRC_MCP_CONTROLLER_TIMEOUT_SECONDS` | `5.0` | finite `0.1` through `60.0` seconds |
| `VRC_MCP_ALLOW_MUTATIONS` | `false` | exactly `0`, `1`, `false`, or `true` |
| `VRC_MCP_MAX_CONCURRENT_CALLS` | `8` | integer `1` through `64` |
| `VRC_MCP_TRANSPORT` | `stdio` | exactly `stdio` or `streamable-http` |
| `VRC_MCP_HTTP_HOST` | `127.0.0.1` | exactly `127.0.0.1`, `localhost`, or `::1` |
| `VRC_MCP_HTTP_PORT` | `8765` | integer `1` through `65535` |

Present malformed values fail closed rather than falling back to defaults.

The controller token file is limited to 4096 bytes. It must be a readable regular file containing strict UTF-8, no embedded NUL, and nonempty content after trimming trailing CR/LF only. On POSIX, group/other write bits and all execute bits are rejected. Errors identify only path/reason and never echo secret bytes.

Python necessarily retains the decoded controller token in ordinary Python `str`/HTTP-stack objects. Unlike the Rust controller's secret handling, Python does not guarantee zeroization of those objects. Do not treat process memory as scrubbed after use.

## Transport

### stdio

`stdio` is the default. stdout is reserved for MCP framing; diagnostics go to stderr. The official SDK acceptance suite verifies catalog discovery, read invocation, mutation-disabled default, explicit mutation opt-in, exactly-one mutation forwarding, and clean EOF-driven shutdown.

### Streamable HTTP

`streamable-http` uses the same tool contract and defaults to:

```text
http://127.0.0.1:8765/mcp
```

The adapter accepts only the loopback addresses `127.0.0.1`, `localhost`, and `::1`. It does not permit `0.0.0.0` or another public bind in the initial release.

The server is run with `stateless_http=True`. The adapter intentionally does not override the official SDK transport security configuration, so the SDK's DNS-rebinding, Host, and Origin checks remain active. Legacy SSE is not exposed as a fallback.

The MCP Streamable HTTP listener does **not** authenticate MCP clients itself. For remote use, keep MCP bound to loopback and place a trusted access boundary in front of it, for example an SSH local-forward or another authenticated tunnel/proxy. Do not publish the loopback listener directly.

## Bounded controller execution

Controller calls are synchronous in the core Python client, so the adapter executes them outside the MCP event loop through one shared `BoundedControllerExecutor`.

Admission is fail-fast. A slot is reserved before submission, so calls do not pile up in `ThreadPoolExecutor`'s otherwise unbounded queue. When capacity is exhausted, the tool fails explicitly instead of silently queuing an unbounded backlog. Cancelling an MCP caller does not make a still-running synchronous controller call disappear or prematurely free its capacity slot.

Every admitted worker future retains an explicit terminal-observation owner. If a caller is cancelled while synchronous controller work is still running, the executor transfers result/exception observation to a payload-free done callback before propagating cancellation. This prevents `Future exception was never retrieved` diagnostics while keeping the slot occupied until the worker really exits.

For **read-only** tools, post-admission task cancellation keeps ordinary cancellation semantics after terminal-observation ownership has been transferred. For **mutation** tools, cancellation observed after admission is conservatively converted into `kind="mutation_outcome_unknown"`, `command_id=null`, `outcome="unknown"`, and `retry_safe=false`. Mutation preflight and executor admission/submission are synchronous before the first await, so cancellation that reaches the mutation outcome wrapper is post-admission: the controller may still execute the side effect. Do not replay it automatically. Cancellation before the handler is ever scheduled issues no controller call.

There is no adapter retry loop.

### Controller response-size bounds

The typed Python client bounds controller response bodies while bytes are being read; it does not first perform an unrestricted `response.read()`. The reviewed wire ceilings are:

- JSON/controller responses: **8 MiB**;
- screenshot PNG responses: **128 MiB**, matching the MCP image validator's conservative 2x envelope over the controller's 64 MiB decoded RGBA framebuffer ceiling;
- metrics/text responses: **1 MiB**;
- HTTP error response bodies: **1 MiB**.

A valid `Content-Length` larger than the applicable ceiling is rejected before body ingestion. Missing or dishonest smaller `Content-Length` values do not bypass the bound: the reader consumes at most the ceiling plus one probe byte and fails closed if additional data exists. Oversized-response errors contain no response-body payload.

## Mutation outcome and retry safety

A successful mutation returns the controller's real process-local `command_id` and terminal `status="succeeded"`.

When the controller has accepted a command but its terminal outcome is unknown, the adapter returns an explicit structured error with `kind="command_outcome_unknown"`, preserves the real command ID, uses `outcome="unknown"`, and sets `retry_safe=false`. The caller should inspect `vnc_get_command_status(command_id)` before deciding on any later action.

When the adapter cannot obtain a trustworthy command ID after a mutation may already have been issued, it uses `kind="mutation_outcome_unknown"`, `command_id=null`, `outcome="unknown"`, and `retry_safe=false`.

The adapter never fabricates a command ID. Do **not** automatically retry or replay the original mutation after either unknown-outcome result. There is no adapter retry loop.

Controller-known terminal failure remains failure and is never replayed automatically. Read-only transport/protocol failures remain read errors rather than mutation-unknown outcomes.

## Sensitive data and logging

Production MCP code must not log tool arguments/results or the sensitive payloads they can contain. In particular, logs/diagnostics must not contain:

- typed keyboard text;
- clipboard contents;
- screenshot pixels/bytes/base64;
- Authorization headers;
- controller bearer-token bytes;
- VNC credentials;
- raw sensitive controller response bodies.

Cancellation cleanup and response-size failures follow the same rule. The terminal-observation callback consumes a future's exception without logging it.

## Validation

The permanent CI suite covers dependency-free core installation, MCP unit/contract tests, exact-pinned SDK tests, stdio and Streamable HTTP acceptance, production MCP -> controller -> TigerVNC E2E, and R13 Compose integration.

Release Gates additionally enforce the reviewed Python MCP dependency/license closure and retain the repository's Gitleaks, cargo-deny, auditable-binary, sanitizer, Miri, Trivy, VEX, and CycloneDX SBOM controls.
