# VNC Remote Control Server Python Client

Typed synchronous Python client for the controller HTTP API.

The core HTTP client has no third-party runtime dependencies. WebSocket event streaming is optional and uses `websocket-client`.

For the project-wide documentation index and the distinction between current guides and historical milestone artifacts, see [`../docs/README.md`](../docs/README.md).

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

Installing from `master` is convenient for development, but it is not reproducible because `master` can advance. For deployments, automation, and other reproducible environments, pin the install to a full Git commit SHA:

```bash
COMMIT_SHA=cccaee213e0c66b0265ff18cd9675b0d9c24e259
python -m pip install \
  "vnc-remote-control-client @ git+https://github.com/ekkus93/vnc-remote-control-server.git@${COMMIT_SHA}#subdirectory=python"
```

The SHA above is an example known-good repository revision that contains the Python client and demo CLI and passed both permanent CI and Release Gates. Replace it deliberately when upgrading so the deployed Python client version changes only when you choose to move the pin.

Installing directly from GitHub requires `git` to be available on the machine running `pip`.

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
