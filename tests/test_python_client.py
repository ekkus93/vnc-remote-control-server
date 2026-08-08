"""Contract tests for the typed Python client (python/src/vnc_remote_control)."""

from __future__ import annotations

import io
import json
import tomllib
import unittest
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit

from vnc_remote_control import ApiError, ProtocolError, VncClient

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"


class FakeResponse:
    """Fake `_HttpResponse`: an in-memory status/body/headers context manager."""

    def __init__(
        self,
        status: int,
        body: bytes,
        headers: Message | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = headers or Message()

    def read(self) -> bytes:
        """Return the fixed response body."""
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


_FIXED_RESPONSE_BODIES: dict[str, bytes] = {
    "/openapi.json": json.dumps({"openapi": "3.1.0", "paths": {}}).encode(),
    "/health/live": b'{"status":"alive"}',
    "/health/ready": b'{"status":"ready"}',
    "/v1/status": json.dumps(
        {
            "state": "connected",
            "started_at_unix_ms": 1,
            "connected_at_unix_ms": 2,
            "last_message_at_unix_ms": 3,
            "reconnect_attempts": 0,
            "last_failure": None,
            "framebuffer_revision": 7,
            "rejected_commands": 0,
            "dropped_events": 0,
            "fatal_exit": False,
            "shutting_down": False,
        }
    ).encode(),
    "/v1/display": (
        b'{"status":"current","width":1280,"height":800,"depth":24,'
        b'"revision":7,"updated_at_unix_ms":4,"complete":true}'
    ),
    "/v1/metrics": b"vrc_ready 1\n",
}


def _routing_http_open() -> tuple[Any, list[tuple[Any, float]]]:
    """Build a fake `HttpOpen` callable plus the list of requests it records.

    A plain closure rather than a class: its only real interface is being
    called, and a class with just one callable method has nowhere to put a
    second public method that isn't contrived.
    """
    requests: list[tuple[Any, float]] = []
    next_command_id = 1

    def opener(request: Any, *, timeout: float) -> FakeResponse:
        nonlocal next_command_id
        requests.append((request, timeout))
        path = urlsplit(request.full_url).path
        method = request.get_method()
        headers = Message()
        headers["X-Request-ID"] = "test-request"

        if path == "/v1/screenshot.png":
            headers["ETag"] = '"process-7"'
            headers["Cache-Control"] = "private, no-cache, max-age=0"
            return FakeResponse(200, b"\x89PNG\r\n", headers)
        if path == "/v1/clipboard" and method == "GET":
            return FakeResponse(
                200, b'{"text":"clipboard","revision":8,"updated_at_unix_ms":5}', headers
            )
        if path in _FIXED_RESPONSE_BODIES:
            return FakeResponse(200, _FIXED_RESPONSE_BODIES[path], headers)

        next_command_id += 1
        return FakeResponse(
            202,
            json.dumps({"command_id": next_command_id, "status": "accepted"}).encode(),
            headers,
        )

    return opener, requests


def _single_json_client(
    expected_path: str, payload: dict[str, Any], *, status: int = 200
) -> VncClient:
    """Return a client whose only HTTP request receives `payload`."""

    def opener(request: Any, *, timeout: float) -> FakeResponse:
        del timeout
        path = urlsplit(request.full_url).path
        if path != expected_path:
            raise AssertionError(f"unexpected test path: {path}")
        return FakeResponse(status, json.dumps(payload).encode())

    return VncClient("http://controller", "token", _http_open=opener)


class FakeWebSocket:
    """Fake `_WebSocket`: replays a fixed message sequence, then closes."""

    def __init__(self) -> None:
        self.messages: list[str] = [
            json.dumps(
                {
                    "sequence": 1,
                    "timestamp_unix_ms": 10,
                    "type": "snapshot",
                    "state": "connected",
                    "framebuffer_revision": 7,
                }
            ),
            json.dumps(
                {
                    "sequence": 2,
                    "timestamp_unix_ms": 11,
                    "type": "framebuffer_revision",
                    "revision": 8,
                }
            ),
            "",
        ]
        self.closed = False

    def recv(self) -> str:
        """Return the next queued message."""
        return self.messages.pop(0)

    def close(self) -> None:
        """Mark this fake socket closed."""
        self.closed = True


class PythonClientTests(unittest.TestCase):
    """Tests for `vnc_remote_control.VncRemoteControlClient`."""

    def test_all_documented_http_endpoints_are_callable(self) -> None:
        """Every client method for a documented endpoint issues the right request."""
        opener, opener_requests = _routing_http_open()
        client = VncClient(
            "http://controller.example:8080",
            "secret-token",
            timeout=3.5,
            _http_open=opener,
        )

        self.assertEqual(client.get_openapi_document()["openapi"], "3.1.0")
        self.assertEqual(client.get_liveness().status, "alive")
        self.assertEqual(client.get_readiness().status, "ready")
        self.assertEqual(client.get_status().state, "connected")
        self.assertEqual(client.get_display().width, 1280)
        screenshot = client.get_screenshot(etag='"process-6"')
        self.assertEqual(screenshot.data, b"\x89PNG\r\n")
        self.assertEqual(screenshot.etag, '"process-7"')
        self.assertFalse(screenshot.not_modified)
        self.assertEqual(client.get_metrics(), "vrc_ready 1\n")
        client.move_pointer(10, 20)
        client.set_pointer_button(10, 20, "left", True)
        client.click_pointer(10, 20)
        client.double_click_pointer(10, 20, interval_ms=90)
        client.scroll_pointer(10, 20, -2)
        client.set_keyboard_key("ENTER", "down")
        client.send_keyboard_chord(["CTRL_LEFT", "a"])
        client.type_keyboard_text("hello")
        self.assertEqual(client.get_clipboard().text, "clipboard")
        client.set_clipboard("new clipboard")
        client.request_reconnect()

        requests = [item[0] for item in opener_requests]
        observed = {(request.get_method(), urlsplit(request.full_url).path) for request in requests}
        expected = {
            ("GET", "/openapi.json"),
            ("GET", "/health/live"),
            ("GET", "/health/ready"),
            ("GET", "/v1/status"),
            ("GET", "/v1/display"),
            ("GET", "/v1/screenshot.png"),
            ("GET", "/v1/metrics"),
            ("POST", "/v1/pointer/move"),
            ("POST", "/v1/pointer/button"),
            ("POST", "/v1/pointer/click"),
            ("POST", "/v1/pointer/double-click"),
            ("POST", "/v1/pointer/scroll"),
            ("POST", "/v1/keyboard/key"),
            ("POST", "/v1/keyboard/chord"),
            ("POST", "/v1/keyboard/text"),
            ("GET", "/v1/clipboard"),
            ("PUT", "/v1/clipboard"),
            ("POST", "/v1/connection/reconnect"),
        }
        self.assertEqual(observed, expected)

        for request in requests:
            path = urlsplit(request.full_url).path
            authorization = request.get_header("Authorization")
            if path.startswith("/v1/"):
                self.assertEqual(authorization, "Bearer secret-token")
            else:
                self.assertIsNone(authorization)
        screenshot_request = next(
            request
            for request in requests
            if urlsplit(request.full_url).path == "/v1/screenshot.png"
        )
        self.assertEqual(screenshot_request.get_header("If-none-match"), '"process-6"')

        command_bodies = {
            urlsplit(request.full_url).path: json.loads(request.data)
            for request in requests
            if request.data is not None
        }
        self.assertEqual(command_bodies["/v1/pointer/move"], {"x": 10, "y": 20})
        self.assertEqual(
            command_bodies["/v1/pointer/double-click"]["interval_ms"], 90
        )
        self.assertEqual(
            command_bodies["/v1/keyboard/chord"]["keys"], ["CTRL_LEFT", "a"]
        )
        self.assertEqual(command_bodies["/v1/clipboard"], {"text": "new clipboard"})

    def test_typed_http_responses_reject_malformed_primitives_and_enums(self) -> None:
        """Typed models never normalize malformed server JSON into valid values."""
        valid_status = json.loads(_FIXED_RESPONSE_BODIES["/v1/status"])
        cases: list[tuple[str, dict[str, Any]]] = []

        for field, invalid in (
            ("fatal_exit", "false"),
            ("shutting_down", 0),
            ("started_at_unix_ms", "1"),
            ("reconnect_attempts", True),
            ("connected_at_unix_ms", "2"),
            ("state", "unknown-state"),
            ("last_failure", "unknown-failure"),
        ):
            payload = dict(valid_status)
            payload[field] = invalid
            cases.append((field, payload))

        missing = dict(valid_status)
        del missing["fatal_exit"]
        cases.append(("missing required", missing))
        extra = dict(valid_status)
        extra["unexpected"] = 1
        cases.append(("unexpected field", extra))

        for label, payload in cases:
            with self.subTest(label=label):
                client = _single_json_client("/v1/status", payload)
                with self.assertRaises(ProtocolError):
                    client.get_status()

        base_display = {
            "status": "current",
            "width": 1280,
            "height": 800,
            "depth": 24,
            "revision": 7,
            "updated_at_unix_ms": 4,
            "complete": True,
        }
        display_cases = (
            {**base_display, "width": "1280"},
            {**base_display, "depth": True},
            {**base_display, "complete": 1},
        )
        for payload in display_cases:
            client = _single_json_client("/v1/display", payload)
            with self.assertRaises(ProtocolError):
                client.get_display()

        client = _single_json_client("/health/live", {"status": 1})
        with self.assertRaises(ProtocolError):
            client.get_liveness()
        client = _single_json_client("/health/live", {"status": "alive", "extra": True})
        with self.assertRaises(ProtocolError):
            client.get_liveness()

        client = _single_json_client(
            "/v1/clipboard",
            {"text": {"not": "text"}, "revision": 1, "updated_at_unix_ms": 2},
        )
        with self.assertRaises(ProtocolError):
            client.get_clipboard()

        client = _single_json_client(
            "/v1/pointer/move", {"command_id": True, "status": "accepted"}, status=202
        )
        with self.assertRaises(ProtocolError):
            client.move_pointer(1, 1)
        client = _single_json_client(
            "/v1/pointer/move", {"command_id": 1, "status": "queued"}, status=202
        )
        with self.assertRaises(ProtocolError):
            client.move_pointer(1, 1)

    def test_nonempty_malformed_api_error_is_protocol_error(self) -> None:
        """Malformed structured error bodies are not silently downgraded."""
        sentinel = "RESPONSE_PAYLOAD_SENTINEL"
        body = json.dumps({"error": {"code": 7, "message": sentinel, "request_id": "id"}}).encode()

        def open_422(request: Any, *, timeout: float) -> FakeResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                422,
                "Unprocessable Entity",
                Message(),
                io.BytesIO(body),
            )

        client = VncClient("http://controller", "token", _http_open=open_422)
        with self.assertRaises(ProtocolError) as captured:
            client.move_pointer(-1, 0)
        self.assertNotIn(sentinel, str(captured.exception))

    def test_empty_documented_runtime_error_remains_api_error(self) -> None:
        """Pre-router empty 400/408/413 responses keep their documented fallback."""

        def open_413(request: Any, *, timeout: float) -> FakeResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                413,
                "Payload Too Large",
                Message(),
                io.BytesIO(b""),
            )

        client = VncClient("http://controller", "token", _http_open=open_413)
        with self.assertRaises(ApiError) as captured:
            client.set_clipboard("value")
        self.assertEqual(captured.exception.status_code, 413)
        self.assertIsNone(captured.exception.code)

    def test_screenshot_304_is_a_non_error_result(self) -> None:
        """A 304 response surfaces as `not_modified=True`, not a raised error."""
        headers = Message()
        headers["ETag"] = '"process-7"'
        headers["X-Request-ID"] = "req-304"

        def open_304(request: Any, *, timeout: float) -> FakeResponse:
            raise HTTPError(
                request.full_url,
                304,
                "Not Modified",
                headers,
                io.BytesIO(b""),
            )

        client = VncClient("http://controller", "token", _http_open=open_304)
        result = client.get_screenshot(etag='"process-7"')
        self.assertTrue(result.not_modified)
        self.assertIsNone(result.data)
        self.assertEqual(result.etag, '"process-7"')
        self.assertEqual(result.request_id, "req-304")

    def test_structured_api_error_preserves_code_and_request_id(self) -> None:
        """`ApiError` carries the error body's code/message/request_id through."""
        headers = Message()
        headers["X-Request-ID"] = "header-id"
        body = json.dumps(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "bad coordinate",
                    "request_id": "body-id",
                }
            }
        ).encode()

        def open_422(request: Any, *, timeout: float) -> FakeResponse:
            raise HTTPError(
                request.full_url,
                422,
                "Unprocessable Entity",
                headers,
                io.BytesIO(body),
            )

        client = VncClient("http://controller", "token", _http_open=open_422)
        with self.assertRaises(ApiError) as captured:
            client.move_pointer(-1, 0)
        error = captured.exception
        self.assertEqual(error.status_code, 422)
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(error.request_id, "body-id")
        self.assertEqual(error.message, "bad coordinate")

    def test_token_is_never_in_repr_or_websocket_url(self) -> None:
        """The bearer token never leaks into `repr()` or the WebSocket URL."""
        calls: list[tuple[str, list[str], float]] = []
        socket = FakeWebSocket()

        def websocket_factory(url: str, *, header: list[str], timeout: float) -> FakeWebSocket:
            calls.append((url, header, timeout))
            return socket

        client = VncClient(
            "https://controller.example/prefix",
            "top-secret-token",
            timeout=4,
            _websocket_factory=websocket_factory,
        )
        self.assertNotIn("top-secret-token", repr(client))
        events = list(client.iter_events())
        self.assertEqual([event.type for event in events], ["snapshot", "framebuffer_revision"])
        self.assertEqual(events[1].payload, {"revision": 8})
        self.assertTrue(socket.closed)

        url, headers, timeout = calls[0]
        self.assertEqual(url, "wss://controller.example/prefix/v1/events")
        self.assertNotIn("top-secret-token", url)
        self.assertEqual(headers, ["Authorization: Bearer top-secret-token"])
        self.assertEqual(timeout, 4.0)

    def test_protected_endpoint_requires_explicit_token(self) -> None:
        """A client built without a token raises on the first protected call."""
        client = VncClient("http://controller")
        self.assertEqual(client.base_url, "http://controller")
        with self.assertRaisesRegex(ValueError, "requires a bearer token"):
            client.get_status()

    def test_base_url_rejects_embedded_credentials(self) -> None:
        """A `base_url` containing `user:password@` is rejected up front."""
        with self.assertRaisesRegex(ValueError, "must not contain credentials"):
            VncClient("http://user:password@controller", "token")

    def test_package_metadata_keeps_http_core_dependency_free(self) -> None:
        """The published package has zero hard dependencies outside the stdlib."""
        metadata = tomllib.loads((PYTHON_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["name"], "vnc-remote-control-client")
        self.assertEqual(project["dependencies"], [])
        self.assertIn("websocket-client>=1.8,<2", project["optional-dependencies"]["websocket"])
        self.assertIn(
            "py.typed", metadata["tool"]["setuptools"]["package-data"]["vnc_remote_control"]
        )


if __name__ == "__main__":
    unittest.main()
