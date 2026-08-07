"""Contract tests for the `vnc-remote-control-demo` console CLI."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import tomllib
import unittest
from collections.abc import Iterator, Sequence
from pathlib import Path

from vnc_remote_control.demo import _read_token_file, build_parser, execute
from vnc_remote_control.models import (
    ClipboardResponse,
    CommandAcceptedResponse,
    DisplayResponse,
    Event,
    HealthResponse,
    ScreenshotResponse,
    StatusResponse,
)

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
PYTHON_README = PYTHON_ROOT / "README.md"


class FakeDemoClient:
    """Fake `VncRemoteControlClient` recording every call it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.metrics_calls = 0

    def get_liveness(self) -> HealthResponse:
        """Return a fixed alive `HealthResponse`."""
        self.calls.append(("get_liveness",))
        return HealthResponse(status="alive")

    def get_readiness(self) -> HealthResponse:
        """Return a fixed ready `HealthResponse`."""
        self.calls.append(("get_readiness",))
        return HealthResponse(status="ready")

    def get_status(self) -> StatusResponse:
        """Return a fixed connected `StatusResponse`."""
        self.calls.append(("get_status",))
        return StatusResponse(
            state="connected",
            started_at_unix_ms=1,
            connected_at_unix_ms=2,
            last_message_at_unix_ms=3,
            reconnect_attempts=0,
            last_failure=None,
            framebuffer_revision=7,
            rejected_commands=0,
            dropped_events=0,
            fatal_exit=False,
            shutting_down=False,
        )

    def get_display(self) -> DisplayResponse:
        """Return a fixed current `DisplayResponse`."""
        self.calls.append(("get_display",))
        return DisplayResponse(
            status="current",
            width=1280,
            height=800,
            depth=24,
            revision=7,
            updated_at_unix_ms=4,
            complete=True,
        )

    def get_metrics(self) -> str:
        """Return fixed metrics text, tracking how many times it was called."""
        self.calls.append(("get_metrics",))
        self.metrics_calls += 1
        return "vrc_ready 1\n"

    def get_screenshot(self, *, etag: str | None = None) -> ScreenshotResponse:
        """Return a fixed one-pixel-PNG `ScreenshotResponse`."""
        del etag
        self.calls.append(("get_screenshot",))
        return ScreenshotResponse(
            data=b"\x89PNG\r\n",
            etag='"demo-7"',
            cache_control="private, no-cache, max-age=0",
            request_id="demo-request",
            not_modified=False,
        )

    def move_pointer(self, x: int, y: int) -> CommandAcceptedResponse:
        """Record a `move_pointer` call and return a fixed acceptance."""
        self.calls.append(("move_pointer", x, y))
        return CommandAcceptedResponse(command_id=1, status="accepted")

    def click_pointer(self, x: int, y: int, button: str = "left") -> CommandAcceptedResponse:
        """Record a `click_pointer` call and return a fixed acceptance."""
        self.calls.append(("click_pointer", x, y, button))
        return CommandAcceptedResponse(command_id=2, status="accepted")

    def double_click_pointer(
        self, x: int, y: int, button: str = "left", *, interval_ms: int = 100
    ) -> CommandAcceptedResponse:
        """Record a `double_click_pointer` call and return a fixed acceptance."""
        self.calls.append(("double_click_pointer", x, y, button, interval_ms))
        return CommandAcceptedResponse(command_id=3, status="accepted")

    def scroll_pointer(
        self, x: int, y: int, delta_y: int, *, delta_x: int = 0
    ) -> CommandAcceptedResponse:
        """Record a `scroll_pointer` call and return a fixed acceptance."""
        del delta_x
        self.calls.append(("scroll_pointer", x, y, delta_y))
        return CommandAcceptedResponse(command_id=4, status="accepted")

    def set_keyboard_key(self, key: str, action: str) -> CommandAcceptedResponse:
        """Record a `set_keyboard_key` call and return a fixed acceptance."""
        self.calls.append(("set_keyboard_key", key, action))
        return CommandAcceptedResponse(command_id=5, status="accepted")

    def send_keyboard_chord(self, keys: Sequence[str]) -> CommandAcceptedResponse:
        """Record a `send_keyboard_chord` call and return a fixed acceptance."""
        self.calls.append(("send_keyboard_chord", tuple(keys)))
        return CommandAcceptedResponse(command_id=6, status="accepted")

    def type_keyboard_text(self, text: str) -> CommandAcceptedResponse:
        """Record a `type_keyboard_text` call and return a fixed acceptance."""
        self.calls.append(("type_keyboard_text", text))
        return CommandAcceptedResponse(command_id=7, status="accepted")

    def get_clipboard(self) -> ClipboardResponse:
        """Return a fixed `ClipboardResponse`."""
        self.calls.append(("get_clipboard",))
        return ClipboardResponse(text="demo clipboard", revision=8, updated_at_unix_ms=5)

    def set_clipboard(self, text: str) -> CommandAcceptedResponse:
        """Record a `set_clipboard` call and return a fixed acceptance."""
        self.calls.append(("set_clipboard", text))
        return CommandAcceptedResponse(command_id=8, status="accepted")

    def request_reconnect(self) -> CommandAcceptedResponse:
        """Record a `request_reconnect` call and return a fixed acceptance."""
        self.calls.append(("request_reconnect",))
        return CommandAcceptedResponse(command_id=9, status="accepted")

    def iter_events(self) -> Iterator[Event]:
        """Yield a fixed sequence of three events."""
        self.calls.append(("iter_events",))
        yield Event(sequence=1, timestamp_unix_ms=10, type="snapshot", payload={})
        yield Event(
            sequence=2,
            timestamp_unix_ms=11,
            type="framebuffer_revision",
            payload={"revision": 8},
        )
        yield Event(
            sequence=3,
            timestamp_unix_ms=12,
            type="connection_state",
            payload={"state": "connected"},
        )


class PythonDemoTests(unittest.TestCase):
    """Tests for the `vnc-remote-control-demo` CLI's argument parsing and dispatch."""

    def setUp(self) -> None:
        self.parser = build_parser()
        self.client = FakeDemoClient()

    def run_command(self, argv: list[str], stdin_text: str = "") -> tuple[str, FakeDemoClient]:
        """Parse and execute `argv`, returning captured stdout and the fake client."""
        args = self.parser.parse_args(argv)
        stdout = io.StringIO()
        execute(args, self.client, stdin=io.StringIO(stdin_text), stdout=stdout)
        return stdout.getvalue(), self.client

    def test_default_command_is_overview(self) -> None:
        """No subcommand runs `overview`, fetching liveness/readiness/status/display."""
        output, client = self.run_command([])
        document = json.loads(output)
        self.assertEqual(document["liveness"]["status"], "alive")
        self.assertEqual(document["readiness"]["status"], "ready")
        self.assertEqual(document["status"]["state"], "connected")
        self.assertEqual(document["display"]["width"], 1280)
        self.assertEqual(
            client.calls,
            [("get_liveness",), ("get_readiness",), ("get_status",), ("get_display",)],
        )

    def test_metrics_fetches_once(self) -> None:
        """`metrics` prints the raw text and calls the client exactly once."""
        output, client = self.run_command(["metrics"])
        self.assertEqual(output, "vrc_ready 1\n")
        self.assertEqual(client.metrics_calls, 1)

    def test_screenshot_writes_png_and_reports_etag(self) -> None:
        """`screenshot <path>` writes the PNG bytes and reports size/etag."""
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "screen.png"
            output, client = self.run_command(["screenshot", str(output_path)])
            self.assertEqual(output_path.read_bytes(), b"\x89PNG\r\n")
            self.assertIn("saved 6 bytes", output)
            self.assertIn('etag: "demo-7"', output)
            self.assertIn(("get_screenshot",), client.calls)

    def test_pointer_and_keyboard_commands_forward_arguments(self) -> None:
        """Each pointer/keyboard subcommand forwards its parsed arguments verbatim."""
        self.run_command(["move", "12", "34"])
        self.run_command(["click", "12", "34", "--button", "right"])
        self.run_command(
            ["double-click", "12", "34", "--button", "middle", "--interval-ms", "150"]
        )
        self.run_command(["scroll", "12", "34", "-3"])
        self.run_command(["key", "ENTER", "down"])
        self.run_command(["chord", "CTRL_LEFT", "a"])
        self.assertIn(("move_pointer", 12, 34), self.client.calls)
        self.assertIn(("click_pointer", 12, 34, "right"), self.client.calls)
        self.assertIn(("double_click_pointer", 12, 34, "middle", 150), self.client.calls)
        self.assertIn(("scroll_pointer", 12, 34, -3), self.client.calls)
        self.assertIn(("set_keyboard_key", "ENTER", "down"), self.client.calls)
        self.assertIn(("send_keyboard_chord", ("CTRL_LEFT", "a")), self.client.calls)

    def test_text_and_clipboard_writes_use_stdin(self) -> None:
        """`type-text` and `clipboard-set` read their payload from stdin."""
        self.run_command(["type-text"], "hello from stdin\n")
        self.run_command(["clipboard-set"], "clipboard from stdin\n")
        self.assertIn(("type_keyboard_text", "hello from stdin"), self.client.calls)
        self.assertIn(("set_clipboard", "clipboard from stdin"), self.client.calls)

    def test_clipboard_get_is_explicit_and_prints_text(self) -> None:
        """`clipboard-get` prints the raw clipboard text, not JSON."""
        output, client = self.run_command(["clipboard-get"])
        self.assertEqual(output, "demo clipboard\n")
        self.assertIn(("get_clipboard",), client.calls)

    def test_events_stop_at_requested_count(self) -> None:
        """`events --count N` prints exactly N events, then stops."""
        output, client = self.run_command(["events", "--count", "2"])
        self.assertEqual(output.count('"sequence"'), 2)
        self.assertIn(("iter_events",), client.calls)

    def test_events_reject_nonpositive_count(self) -> None:
        """`events --count 0` raises before any event is fetched."""
        args = self.parser.parse_args(["events", "--count", "0"])
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            execute(args, self.client, stdin=io.StringIO(), stdout=io.StringIO())

    def test_token_file_is_trimmed_and_empty_file_is_rejected(self) -> None:
        """A token file's contents are stripped; an empty file is rejected."""
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.txt"
            token_path.write_text("demo-token\n", encoding="utf-8")
            self.assertEqual(_read_token_file(str(token_path)), "demo-token")
            token_path.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                _read_token_file(str(token_path))

    def test_parser_exposes_token_file_but_no_raw_token_argument(self) -> None:
        """--token-file is a real argument; a raw --token is rejected."""
        args = self.parser.parse_args(["--token-file", "/tmp/example-token"])
        self.assertEqual(args.token_file, "/tmp/example-token")
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                self.parser.parse_args(["--token", "secret"])

    def test_package_installs_demo_console_script(self) -> None:
        """`pyproject.toml` registers the `vnc-remote-control-demo` console script."""
        metadata = tomllib.loads((PYTHON_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            metadata["project"]["scripts"]["vnc-remote-control-demo"],
            "vnc_remote_control.demo:main",
        )

    def test_python_readme_documents_demo_and_security_boundary(self) -> None:
        """`python/README.md` documents the demo CLI and its no-raw-token boundary."""
        readme = PYTHON_README.read_text(encoding="utf-8")
        for required in (
            "## Demo CLI",
            "vnc-remote-control-demo --help",
            "--base-url http://127.0.0.1:8080",
            "--token-file deploy/secrets/api_token.txt",
            "VRC_API_TOKEN_FILE",
            "does **not** accept a raw bearer token",
            "screenshot screen.png",
            "type-text",
            "clipboard-set",
            "events --count 10",
            "does not clamp coordinates",
        ):
            self.assertIn(required, readme)


if __name__ == "__main__":
    unittest.main()
