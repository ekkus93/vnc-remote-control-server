from __future__ import annotations

import io
import json
import sys
import tomllib
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
SRC = PYTHON_ROOT / "src"
sys.path.insert(0, str(SRC))

from vnc_remote_control import ApiError, VncClient  # noqa: E402


class FakeResponse:
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
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class RoutingHttpOpen:
    def __init__(self) -> None:
        self.requests = []
        self.next_command_id = 1

    def __call__(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        path = urlsplit(request.full_url).path
        method = request.get_method()
        headers = Message()
        headers["X-Request-ID"] = "test-request"

        if path == "/openapi.json":
            return FakeResponse(
                200,
                json.dumps({"openapi": "3.1.0", "paths": {}}).encode(),
                headers,
            )
        if path == "/health/live":
            return FakeResponse(200, b'{"status":"alive"}', headers)
        if path == "/health/ready":
            return FakeResponse(200, b'{"status":"ready"}', headers)
        if path == "/v1/status":
            return FakeResponse(
                200,
                json.dumps(
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
                headers,
            )
        if path == "/v1/display":
            return FakeResponse(
                200,
                b'{"status":"current","width":1280,"height":800,"depth":24,'
                b'"revision":7,"updated_at_unix_ms":4,"complete":true}',
                headers,
            )
        if path == "/v1/screenshot.png":
            headers["ETag"] = '"process-7"'
            headers["Cache-Control"] = "private, no-cache, max-age=0"
            return FakeResponse(200, b"\x89PNG\r\n", headers)
        if path == "/v1/metrics":
            return FakeResponse(200, b"vrc_ready 1\n", headers)
        if path == "/v1/clipboard" and method == "GET":
            return FakeResponse(
                200,
                b'{"text":"clipboard","revision":8,"updated_at_unix_ms":5}',
                headers,
            )

        self.next_command_id += 1
        return FakeResponse(
            202,
            json.dumps(
                {"command_id": self.next_command_id, "status": "accepted"}
            ).encode(),
            headers,
        )


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages = [
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

    def recv(self):
        return self.messages.pop(0)

    def close(self):
        self.closed = True


class PythonClientTests(unittest.TestCase):
    def test_all_documented_http_endpoints_are_callable(self) -> None:
        opener = RoutingHttpOpen()
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

        requests = [item[0] for item in opener.requests]
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

    def test_screenshot_304_is_a_non_error_result(self) -> None:
        headers = Message()
        headers["ETag"] = '"process-7"'
        headers["X-Request-ID"] = "req-304"

        def open_304(request, *, timeout):
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

        def open_422(request, *, timeout):
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
        calls = []
        socket = FakeWebSocket()

        def websocket_factory(url, *, header, timeout):
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
        client = VncClient("http://controller")
        self.assertEqual(client.base_url, "http://controller")
        with self.assertRaisesRegex(ValueError, "requires a bearer token"):
            client.get_status()

    def test_base_url_rejects_embedded_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain credentials"):
            VncClient("http://user:password@controller", "token")

    def test_package_metadata_keeps_http_core_dependency_free(self) -> None:
        metadata = tomllib.loads((PYTHON_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["name"], "vnc-remote-control-client")
        self.assertEqual(project["dependencies"], [])
        self.assertIn("websocket-client>=1.8,<2", project["optional-dependencies"]["websocket"])
        self.assertIn("py.typed", metadata["tool"]["setuptools"]["package-data"]["vnc_remote_control"])


if __name__ == "__main__":
    unittest.main()
