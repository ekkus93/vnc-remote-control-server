# VNC Remote Control Server Python Client

Typed synchronous Python client for the controller HTTP API, plus optional WebSocket event and MCP support.

The core HTTP client has no third-party runtime dependencies. WebSocket event streaming is optional and uses `websocket-client`. MCP support is also optional and uses the exact-reviewed official Python MCP SDK pin.

For the project-wide documentation index and the distinction between current guides and historical milestone artifacts, see [`../docs/README.md`](../docs/README.md). For the complete MCP transport/configuration/security contract, see [`../docs/MCP_SERVER.md`](../docs/MCP_SERVER.md).

## Where the client connects

The Python client connects to the **Rust controller API**, not directly to the VNC desktop container.

```text
Python VncClient(base_url, api_token)
        |
        | HTTP / WebSocket
        v
Rust controller
        |
        | VRC_VNC_HOST / VRC_VNC_PORT / VRC_VNC_PASSWORD_FILE
        v
project-owned VNC desktop container
```

`base_url` is therefore the controller's HTTP address, such as `http://127.0.0.1:8080` on the host or `http://controller:8080` from another container on a shared Docker network.

The Python client does not need the desktop service name, desktop image name, VNC port, or VNC password. Those are controller/deployment concerns. Swapping a supported custom desktop image behind an unchanged controller does not require changing Python application code. See [`../docs/CUSTOM_DESKTOP_IMAGES.md`](../docs/CUSTOM_DESKTOP_IMAGES.md) for the complete configuration chain.

The optional MCP adapter uses the same typed client and the same controller API. It does not connect to VNC directly or implement a second remote-desktop protocol stack:

```text
MCP host/client -> vnc-remote-control-mcp -> VncRemoteControlClient
                -> authenticated Rust controller -> worker -> VNC desktop
```

A running local controller also exposes Swagger UI at `http://127.0.0.1:8080/docs`, ReDoc at `http://127.0.0.1:8080/redoc`, and the raw OpenAPI document at `http://127.0.0.1:8080/openapi.json`.

## Install

The package name is `vnc-remote-control-client`. The import package is `vnc_remote_control`.

### From a local checkout

From the repository root:

```bash
python -m pip install ./python
```

With WebSocket event support:

```bash
python -m pip install './python[websocket]'
```

With the MCP server entry point:

```bash
python -m pip install './python[mcp]'
```

The MCP extra pins `mcp==2.1.1` and installs `vnc-remote-control-mcp`. The runnable adapter supports stdio by default and explicit SDK-protected loopback Streamable HTTP. The core client remains dependency-free when the extra is not selected. Missing MCP dependencies fail explicitly rather than silently downgrading behavior.

### Directly from GitHub

`pip` can install the package directly from this repository even though the Python project lives in the `python/` subdirectory:

```bash
python -m pip install \
  "vnc-remote-control-client @ git+https://github.com/ekkus93/vnc-remote-control-server.git@master#subdirectory=python"
```

For WebSocket event support:

```bash
python -m pip install \
  "vnc-remote-control-client[websocket] @ git+https://github.com/ekkus93/vnc-remote-control-server.git@master#subdirectory=python"
```

For the MCP server entry point:

```bash
python -m pip install \
  "vnc-remote-control-client[mcp] @ git+https://github.com/ekkus93/vnc-remote-control-server.git@master#subdirectory=python"
```

Installing from `master` is convenient for development, but it is not reproducible because `master` can advance. For deployments, automation, and other reproducible environments, pin the install to a full Git commit SHA:

```bash
COMMIT_SHA=e90a71c238f6e7e01206bce3afcdff1ba74d1e3f
python -m pip install \
  "vnc-remote-control-client[mcp] @ git+https://github.com/ekkus93/vnc-remote-control-server.git@${COMMIT_SHA}#subdirectory=python"
```

The SHA above is a known-good repository revision containing the client, demo, and implemented stdio/loopback Streamable HTTP MCP transports; both permanent CI and Release Gates passed on that exact merged `master` SHA. Replace it deliberately when upgrading so the deployed Python/MCP version changes only when you choose to move the pin.

Installing directly from GitHub requires `git` to be available on the machine running `pip`.

## MCP server

The MCP process requires a path to the controller's bearer-token file. The environment variable contains the **path**, not the token:

```bash
export VRC_MCP_CONTROLLER_TOKEN_FILE="$PWD/deploy/secrets/api_token.txt"
```

Start the default stdio transport with:

```bash
vnc-remote-control-mcp
```

The default catalog is read-only. It exposes status, display, native screenshot image content, clipboard read, command-status inspection, and metrics. Mutation tools are not registered unless the operator deliberately sets:

```bash
export VRC_MCP_ALLOW_MUTATIONS=true
```

Mutation opt-in is process-wide. Do not enable it for an MCP transport/client you do not fully trust.

For explicit Streamable HTTP:

```bash
VRC_MCP_CONTROLLER_TOKEN_FILE="$PWD/deploy/secrets/api_token.txt" \
VRC_MCP_TRANSPORT=streamable-http \
vnc-remote-control-mcp
```

The default endpoint is `http://127.0.0.1:8765/mcp`. The adapter accepts only the SDK-protected loopback host spellings `127.0.0.1`, `localhost`, and `::1`; it cannot be configured to bind publicly. The HTTP listener does not add a project-specific client-authentication protocol, so remote use requires a trusted authenticated tunnel/proxy while the backend remains loopback-only. Do not disable the official SDK Host/Origin/DNS-rebinding checks to work around a deployment topology.

Every controller call uses one shared bounded off-loop executor. There is no unbounded controller-call waiting queue and no adapter retry loop.

### MCP mutation errors and unknown outcomes

The MCP adapter preserves the typed client's conservative mutation semantics. If a mutation outcome is unknown but a trustworthy controller command ID exists, the MCP error reports `kind="command_outcome_unknown"`, preserves the command ID, sets `retry_safe=false`, and directs the caller to `vnc_get_command_status(command_id)`.

If a transport/protocol failure leaves the mutation ambiguous and no trustworthy command ID exists, MCP reports `kind="mutation_outcome_unknown"`, `command_id=null`, and `retry_safe=false`. It never fabricates an ID or treats the missing ID as proof that the controller received nothing.

Do not automatically retry or replay either class of ambiguous mutation. See [`../docs/MCP_SERVER.md`](../docs/MCP_SERVER.md) for the full configuration table, token-file validation, Python token-memory limitation, tool catalog, transport shutdown behavior, sensitive-data logging policy, and remote-access boundary.

## Demo CLI

Installing the package also installs a small command-line demo application:

```bash
vnc-remote-control-demo --help
```

The demo talks to the Rust controller through the same `VncClient` library. By default it connects to `http://127.0.0.1:8080` and reads the API bearer token from `deploy/secrets/api_token.txt`. Override those locations explicitly when needed:

```bash
vnc-remote-control-demo \
  --base-url http://127.0.0.1:8080 \
  --token-file deploy/secrets/api_token.txt \
  overview
```

`--token-file` can also be supplied through `VRC_API_TOKEN_FILE`. The demo intentionally does **not** accept a raw bearer token as a command-line argument, so the token is not placed in the shell history or process argument list by the demo.

Useful commands include:

```bash
# Health, connection state, and display information.
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt overview

# Save the current framebuffer.
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt screenshot screen.png

# Pointer input.
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt move 640 400
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt click 640 400
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt double-click 640 400
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt scroll 640 400 -3

# Keyboard input.
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt key ENTER down
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt key ENTER up
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt chord CTRL_LEFT a
printf '%s\n' 'hello from the demo' | \
  vnc-remote-control-demo --token-file deploy/secrets/api_token.txt type-text

# Clipboard operations.
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt clipboard-get
printf '%s\n' 'clipboard from the demo' | \
  vnc-remote-control-demo --token-file deploy/secrets/api_token.txt clipboard-set

# Reconnect and metrics.
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt reconnect
vnc-remote-control-demo --token-file deploy/secrets/api_token.txt metrics
```

For WebSocket event streaming, install the `websocket` extra and request a bounded number of events:

```bash
vnc-remote-control-demo \
  --token-file deploy/secrets/api_token.txt \
  events --count 10
```

The demo deliberately leaves controller validation authoritative. It does not clamp coordinates, rewrite text, retry rejected commands, or hide API failures.

## Basic usage

```python
from pathlib import Path

from vnc_remote_control import VncClient

api_token = Path("deploy/secrets/api_token.txt").read_text(encoding="utf-8").strip()
client = VncClient("http://127.0.0.1:8080", api_token)

print(client.get_liveness())
print(client.get_readiness())
print(client.get_status())
print(client.get_display())

client.move_pointer(640, 400)
client.click_pointer(640, 400)
client.send_keyboard_chord(["CTRL_LEFT", "a"])
client.type_keyboard_text("hello from Python")
client.set_clipboard("clipboard text")
```

The API token authenticates the Python client to the Rust controller. It is separate from the VNC password that authenticates the Rust controller to the desktop's VNC server.

## Screenshots

`get_screenshot()` returns PNG bytes together with the response ETag. Pass the previous ETag back to avoid downloading an unchanged framebuffer:

```python
shot = client.get_screenshot()
if shot.data is not None:
    Path("screen.png").write_bytes(shot.data)

next_shot = client.get_screenshot(etag=shot.etag)
if next_shot.not_modified:
    print("framebuffer unchanged")
```

## WebSocket events

Install the `websocket` extra, then iterate over parsed event envelopes:

```python
for event in client.iter_events():
    print(event.sequence, event.type, event.payload)
```

The bearer token is sent in the WebSocket HTTP upgrade `Authorization` header. It is never placed in the URL.

## Errors and indeterminate command outcomes

Non-success controller responses raise `ApiError`, with structured fields when the controller returned the documented error envelope:

```python
from vnc_remote_control import ApiError

try:
    client.move_pointer(-1, 0)
except ApiError as error:
    print(error.status_code, error.code, error.request_id)
```

A timeout that happens **after the worker accepted a side-effecting command is different from a known command failure**. The client raises `CommandOutcomeUnknownError`, which carries the stable `command_id` and has `retry_safe == False`. Do not automatically retry the original mutation: it may still execute or may already have executed. Inspect the retained command status instead:

```python
from vnc_remote_control import CommandOutcomeUnknownError

try:
    client.click_pointer(640, 400)
except CommandOutcomeUnknownError as error:
    print("outcome unknown", error.command_id, error.retry_safe)
    status = client.get_command_status(error.command_id)
    print(status.command_id, status.status, status.failure, status.retry_safe)
```

A later status can report `queued`, `running`, `succeeded`, `failed`, `aborted`, or another documented lifecycle state while the bounded process-local record is retained. Unknown or expired command IDs remain explicit API errors; the client never converts them into an apparent successful mutation. The command-status response contains sanitized metadata only and never includes typed text, clipboard content, bearer tokens, VNC credentials, or screenshots.

Transport failures raise `TransportError`. Every typed response is strictly validated: a malformed success response (wrong field type, unknown enum value, missing/unexpected field) raises `ProtocolError` instead of being coerced into an apparently valid value, and a non-empty structured error body that fails to parse as the documented error envelope also raises `ProtocolError` rather than being silently reported as a generic `ApiError`. Calling WebSocket events without the optional dependency raises `OptionalDependencyError`.

The server remains authoritative for operation limits and validation. The client does not silently clamp coordinates, scroll deltas, text, clipboard content, or other values, and it never automatically retries a mutation whose execution outcome is unknown.
