"""Small pure and near-pure helpers shared across the R13 harness and checks."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from r13_types import Failure, HttpResult

if TYPE_CHECKING:
    from r13_harness import Harness


def free_port() -> int:
    """Return an ephemeral TCP port free at the moment of the call."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def require(condition: bool, message: str) -> None:
    """Raise `Failure(message)` unless `condition` is true."""
    if not condition:
        raise Failure(message)


def error_code(response: HttpResult) -> str | None:
    """Extract `error.code` from a JSON error response, or `None`."""
    if not response.body:
        return None
    try:
        return str(response.json().get("error", {}).get("code"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def wait_until(
    predicate: Callable[[], bool], description: str, deadline_seconds: float = 10
) -> None:
    """Poll `predicate` until true, raising `Failure(description)` on timeout."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise Failure(f"deadline exceeded: {description}")


def parse_png_dimensions(data: bytes) -> tuple[int, int]:
    """Return `(width, height)` parsed from a PNG's IHDR chunk."""
    require(data.startswith(b"\x89PNG\r\n\x1a\n"), "screenshot is not a PNG")
    require(data[12:16] == b"IHDR", "PNG does not begin with IHDR")
    return struct.unpack(">II", data[16:24])


def websocket_status(port: int, path: str, authorization: str | None) -> int:
    """Perform a WebSocket handshake and return its HTTP status line code."""
    key = hashlib.sha256(os.urandom(32)).digest()[:16]
    encoded_key = base64.b64encode(key).decode("ascii")
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {encoded_key}",
        "Sec-WebSocket-Version: 13",
    ]
    if authorization is not None:
        lines.append(f"Authorization: Bearer {authorization}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            require(bool(chunk), "WebSocket handshake closed without response")
            response.extend(chunk)
            require(len(response) < 65536, "WebSocket handshake response exceeded bound")
    status_line = bytes(response).split(b"\r\n", 1)[0].decode("ascii")
    return int(status_line.split()[1])


def post_json(
    harness: Harness, path: str, payload: dict[str, Any], timeout: float = 10
) -> HttpResult:
    """POST `payload` as JSON to `path` via `harness`."""
    return harness.request("POST", path, payload, timeout=timeout)


def read_http_response(sock: socket.socket) -> HttpResult:
    """Read one raw HTTP/1.1 response from an already-connected socket."""
    sock.settimeout(12)
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        require(bool(chunk), "connection closed before HTTP response headers")
        data.extend(chunk)
    headers_raw, _, body = bytes(data).partition(b"\r\n\r\n")
    lines = headers_raw.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body_buffer = bytearray(body)
    while len(body_buffer) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body_buffer.extend(chunk)
    return HttpResult(status, headers, bytes(body_buffer[:length]))
