"""Console entry point for the `vnc-remote-control-demo` command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

from .client import VncClient
from .errors import VncRemoteControlError
from .models import (
    ClipboardResponse,
    CommandAcceptedResponse,
    DisplayResponse,
    Event,
    HealthResponse,
    KeyAction,
    MouseButton,
    ScreenshotResponse,
    StatusResponse,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TOKEN_FILE = "deploy/secrets/api_token.txt"
TOKEN_FILE_ENV = "VRC_API_TOKEN_FILE"


class _DemoClient(Protocol):
    """The subset of `VncRemoteControlClient`'s interface the demo CLI uses.

    A structural Protocol rather than the concrete class so tests can inject
    a plain duck-typed fake without inheritance or per-call type: ignores.
    """

    def get_liveness(self) -> HealthResponse:
        """Fetch liveness."""

    def get_readiness(self) -> HealthResponse:
        """Fetch readiness."""

    def get_status(self) -> StatusResponse:
        """Fetch worker/connection status."""

    def get_display(self) -> DisplayResponse:
        """Fetch display/framebuffer metadata."""

    def get_metrics(self) -> str:
        """Fetch Prometheus metrics text."""

    def get_screenshot(self, *, etag: str | None = None) -> ScreenshotResponse:
        """Fetch the current screenshot."""

    def move_pointer(self, x: int, y: int) -> CommandAcceptedResponse:
        """Move the pointer."""

    def click_pointer(
        self, x: int, y: int, button: MouseButton = "left"
    ) -> CommandAcceptedResponse:
        """Click a pointer button."""

    def double_click_pointer(
        self, x: int, y: int, button: MouseButton = "left", *, interval_ms: int = 100
    ) -> CommandAcceptedResponse:
        """Double-click a pointer button."""

    def scroll_pointer(
        self, x: int, y: int, delta_y: int, *, delta_x: int = 0
    ) -> CommandAcceptedResponse:
        """Scroll at a pointer location."""

    def set_keyboard_key(self, key: str, action: KeyAction) -> CommandAcceptedResponse:
        """Send one key down/up event."""

    def send_keyboard_chord(self, keys: Sequence[str]) -> CommandAcceptedResponse:
        """Send a key chord."""

    def type_keyboard_text(self, text: str) -> CommandAcceptedResponse:
        """Type text."""

    def get_clipboard(self) -> ClipboardResponse:
        """Fetch the clipboard."""

    def set_clipboard(self, text: str) -> CommandAcceptedResponse:
        """Set the clipboard."""

    def request_reconnect(self) -> CommandAcceptedResponse:
        """Request a VNC reconnect."""

    def iter_events(self) -> Iterator[Event]:
        """Yield WebSocket events."""


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _print_json(value: Any, stdout: TextIO) -> None:
    print(json.dumps(_json_value(value), indent=2, sort_keys=True), file=stdout)


def _read_token_file(path: str) -> str:
    token_path = Path(path)
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"could not read API token file: {token_path}") from exc
    if not token:
        raise ValueError(f"API token file is empty: {token_path}")
    return token


def _read_text(stdin: TextIO, *, prompt: str) -> str:
    if stdin.isatty():
        print(prompt, file=sys.stderr, flush=True)
        return stdin.readline().rstrip("\r\n")
    value = stdin.read()
    return value[:-1] if value.endswith("\n") else value


def build_parser() -> argparse.ArgumentParser:
    """Build the demo CLI's argument parser."""
    parser = argparse.ArgumentParser(
        prog="vnc-remote-control-demo",
        description="Small demo CLI for the VNC Remote Control Server Python client.",
        # Unambiguous long options only: without this, argparse would silently
        # accept "--token" as an abbreviation of "--token-file", defeating the
        # intent of never accepting a raw bearer token as a CLI argument.
        allow_abbrev=False,
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Rust controller base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--token-file",
        default=None,
        help=(
            "API bearer-token file. Defaults to $VRC_API_TOKEN_FILE when set, "
            f"otherwise {DEFAULT_TOKEN_FILE}. Raw bearer tokens are intentionally "
            "not accepted as command-line arguments."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP timeout in seconds (default: 5.0)",
    )

    commands = parser.add_subparsers(dest="command")

    commands.add_parser("overview", help="Show health, connection, and display state.")
    commands.add_parser("status", help="Show controller/VNC status.")
    commands.add_parser("display", help="Show framebuffer/display metadata.")
    commands.add_parser("metrics", help="Print Prometheus metrics.")

    screenshot = commands.add_parser("screenshot", help="Save the current framebuffer as PNG.")
    screenshot.add_argument(
        "output",
        nargs="?",
        default="screenshot.png",
        help="Output PNG path (default: screenshot.png)",
    )

    move = commands.add_parser("move", help="Move the pointer.")
    move.add_argument("x", type=int)
    move.add_argument("y", type=int)

    click = commands.add_parser("click", help="Click a pointer button.")
    click.add_argument("x", type=int)
    click.add_argument("y", type=int)
    click.add_argument("--button", choices=("left", "middle", "right"), default="left")

    double_click = commands.add_parser("double-click", help="Double-click a pointer button.")
    double_click.add_argument("x", type=int)
    double_click.add_argument("y", type=int)
    double_click.add_argument("--button", choices=("left", "middle", "right"), default="left")
    double_click.add_argument("--interval-ms", type=int, default=100)

    scroll = commands.add_parser("scroll", help="Scroll vertically at a pointer location.")
    scroll.add_argument("x", type=int)
    scroll.add_argument("y", type=int)
    scroll.add_argument("delta_y", type=int)

    key = commands.add_parser("key", help="Send one explicit key down/up event.")
    key.add_argument("key")
    key.add_argument("action", choices=("down", "up"))

    chord = commands.add_parser("chord", help="Send a key chord.")
    chord.add_argument("keys", nargs="+")

    commands.add_parser(
        "type-text",
        help="Read text from stdin and type it into the remote desktop.",
    )
    commands.add_parser("clipboard-get", help="Print the remote clipboard text.")
    commands.add_parser(
        "clipboard-set",
        help="Read text from stdin and replace the remote clipboard.",
    )
    commands.add_parser("reconnect", help="Request a VNC reconnect.")

    events = commands.add_parser(
        "events",
        help="Print a bounded number of WebSocket events (requires the websocket extra).",
    )
    events.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of events to print before exiting (default: 10)",
    )

    return parser


@dataclass(frozen=True, slots=True)
class _CommandContext:
    """Bundles one demo CLI invocation's parsed args, client, and I/O streams."""

    args: argparse.Namespace
    client: _DemoClient
    stdin: TextIO
    stdout: TextIO


def _cmd_overview(ctx: _CommandContext) -> None:
    _print_json(
        {
            "liveness": asdict(ctx.client.get_liveness()),
            "readiness": asdict(ctx.client.get_readiness()),
            "status": asdict(ctx.client.get_status()),
            "display": asdict(ctx.client.get_display()),
        },
        ctx.stdout,
    )


def _cmd_status(ctx: _CommandContext) -> None:
    _print_json(ctx.client.get_status(), ctx.stdout)


def _cmd_display(ctx: _CommandContext) -> None:
    _print_json(ctx.client.get_display(), ctx.stdout)


def _cmd_metrics(ctx: _CommandContext) -> None:
    metrics = ctx.client.get_metrics()
    print(metrics, end="" if metrics.endswith("\n") else "\n", file=ctx.stdout)


def _cmd_screenshot(ctx: _CommandContext) -> None:
    response = ctx.client.get_screenshot()
    if response.data is None:
        raise RuntimeError("controller returned no screenshot bytes")
    output = Path(ctx.args.output)
    output.write_bytes(response.data)
    print(f"saved {len(response.data)} bytes to {output}", file=ctx.stdout)
    if response.etag is not None:
        print(f"etag: {response.etag}", file=ctx.stdout)


def _cmd_move(ctx: _CommandContext) -> None:
    _print_json(ctx.client.move_pointer(ctx.args.x, ctx.args.y), ctx.stdout)


def _cmd_click(ctx: _CommandContext) -> None:
    _print_json(ctx.client.click_pointer(ctx.args.x, ctx.args.y, ctx.args.button), ctx.stdout)


def _cmd_double_click(ctx: _CommandContext) -> None:
    _print_json(
        ctx.client.double_click_pointer(
            ctx.args.x,
            ctx.args.y,
            ctx.args.button,
            interval_ms=ctx.args.interval_ms,
        ),
        ctx.stdout,
    )


def _cmd_scroll(ctx: _CommandContext) -> None:
    _print_json(ctx.client.scroll_pointer(ctx.args.x, ctx.args.y, ctx.args.delta_y), ctx.stdout)


def _cmd_key(ctx: _CommandContext) -> None:
    _print_json(ctx.client.set_keyboard_key(ctx.args.key, ctx.args.action), ctx.stdout)


def _cmd_chord(ctx: _CommandContext) -> None:
    _print_json(ctx.client.send_keyboard_chord(ctx.args.keys), ctx.stdout)


def _cmd_type_text(ctx: _CommandContext) -> None:
    text = _read_text(ctx.stdin, prompt="Enter one line of text to type:")
    _print_json(ctx.client.type_keyboard_text(text), ctx.stdout)


def _cmd_clipboard_get(ctx: _CommandContext) -> None:
    clipboard = ctx.client.get_clipboard()
    print(clipboard.text, file=ctx.stdout)


def _cmd_clipboard_set(ctx: _CommandContext) -> None:
    text = _read_text(ctx.stdin, prompt="Enter one line of clipboard text:")
    _print_json(ctx.client.set_clipboard(text), ctx.stdout)


def _cmd_reconnect(ctx: _CommandContext) -> None:
    _print_json(ctx.client.request_reconnect(), ctx.stdout)


def _cmd_events(ctx: _CommandContext) -> None:
    if ctx.args.count <= 0:
        raise ValueError("--count must be greater than zero")
    for index, event in enumerate(ctx.client.iter_events(), start=1):
        _print_json(event, ctx.stdout)
        if index >= ctx.args.count:
            break


_COMMAND_HANDLERS: dict[str, Callable[[_CommandContext], None]] = {
    "overview": _cmd_overview,
    "status": _cmd_status,
    "display": _cmd_display,
    "metrics": _cmd_metrics,
    "screenshot": _cmd_screenshot,
    "move": _cmd_move,
    "click": _cmd_click,
    "double-click": _cmd_double_click,
    "scroll": _cmd_scroll,
    "key": _cmd_key,
    "chord": _cmd_chord,
    "type-text": _cmd_type_text,
    "clipboard-get": _cmd_clipboard_get,
    "clipboard-set": _cmd_clipboard_set,
    "reconnect": _cmd_reconnect,
    "events": _cmd_events,
}


def execute(
    args: argparse.Namespace,
    client: _DemoClient,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> None:
    """Run one parsed demo CLI command against `client`."""
    command = args.command or "overview"
    handler = _COMMAND_HANDLERS.get(command)
    if handler is None:
        raise ValueError(f"unsupported demo command: {command}")
    handler(_CommandContext(args=args, client=client, stdin=stdin, stdout=stdout))


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the demo CLI, returning a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    token_file = args.token_file or os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE

    try:
        token = _read_token_file(token_file)
        client = VncClient(args.base_url, token, timeout=args.timeout)
        execute(args, client, stdin=sys.stdin, stdout=sys.stdout)
    except (VncRemoteControlError, OSError, RuntimeError, ValueError) as exc:
        print(f"demo error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
