# VNC Remote Control Server Python Client

Typed synchronous Python client for the controller HTTP API.

The core HTTP client has no third-party runtime dependencies. WebSocket event streaming is optional and uses `websocket-client`.

## Install

From this repository:

```bash
python -m pip install ./python
```

With WebSocket event support:

```bash
python -m pip install './python[websocket]'
```

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

## Errors

Non-success controller responses raise `ApiError`, with structured fields when the controller returned the documented error envelope:

```python
from vnc_remote_control import ApiError

try:
    client.move_pointer(-1, 0)
except ApiError as error:
    print(error.status_code, error.code, error.request_id)
```

Transport failures raise `TransportError`. Malformed success responses raise `ProtocolError`. Calling WebSocket events without the optional dependency raises `OptionalDependencyError`.

The server remains authoritative for operation limits and validation. The client does not silently clamp coordinates, scroll deltas, text, clipboard content, or other values.
