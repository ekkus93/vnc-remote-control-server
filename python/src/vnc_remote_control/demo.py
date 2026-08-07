from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence, TextIO

from .client import VncClient, VncRemoteControlClient
from .errors import VncRemoteControlError

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TOKEN_FILE = "deploy/secrets/api_token.txt"
TOKEN_FILE_ENV = "VRC_API_TOKEN_FILE"


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
    parser = argparse.ArgumentParser(
        prog="vnc-remote-control-demo",
        description="Small demo CLI for the VNC Remote Control Server Python client.",
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


def _overview(client: VncRemoteControlClient, stdout: TextIO) -> None:
    _print_json(
        {
            "liveness": asdict(client.get_liveness()),
            "readiness": asdict(client.get_readiness()),
            "status": asdict(client.get_status()),
            "display": asdict(client.get_display()),
        },
        stdout,
    )


def execute(
    args: argparse.Namespace,
    client: VncRemoteControlClient,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> None:
    command = args.command or "overview"

    if command == "overview":
        _overview(client, stdout)
        return
    if command == "status":
        _print_json(client.get_status(), stdout)
        return
    if command == "display":
        _print_json(client.get_display(), stdout)
        return
    if command == "metrics":
        metrics = client.get_metrics()
        print(metrics, end="" if metrics.endswith("\n") else "\n", file=stdout)
        return
    if command == "screenshot":
        response = client.get_screenshot()
        if response.data is None:
            raise RuntimeError("controller returned no screenshot bytes")
        output = Path(args.output)
        output.write_bytes(response.data)
        print(f"saved {len(response.data)} bytes to {output}", file=stdout)
        if response.etag is not None:
            print(f"etag: {response.etag}", file=stdout)
        return
    if command == "move":
        _print_json(client.move_pointer(args.x, args.y), stdout)
        return
    if command == "click":
        _print_json(client.click_pointer(args.x, args.y, args.button), stdout)
        return
    if command == "double-click":
        _print_json(
            client.double_click_pointer(
                args.x,
                args.y,
                args.button,
                interval_ms=args.interval_ms,
            ),
            stdout,
        )
        return
    if command == "scroll":
        _print_json(client.scroll_pointer(args.x, args.y, args.delta_y), stdout)
        return
    if command == "key":
        _print_json(client.set_keyboard_key(args.key, args.action), stdout)
        return
    if command == "chord":
        _print_json(client.send_keyboard_chord(args.keys), stdout)
        return
    if command == "type-text":
        text = _read_text(stdin, prompt="Enter one line of text to type:")
        _print_json(client.type_keyboard_text(text), stdout)
        return
    if command == "clipboard-get":
        response = client.get_clipboard()
        print(response.text, file=stdout)
        return
    if command == "clipboard-set":
        text = _read_text(stdin, prompt="Enter one line of clipboard text:")
        _print_json(client.set_clipboard(text), stdout)
        return
    if command == "reconnect":
        _print_json(client.request_reconnect(), stdout)
        return
    if command == "events":
        if args.count <= 0:
            raise ValueError("--count must be greater than zero")
        for index, event in enumerate(client.iter_events(), start=1):
            _print_json(event, stdout)
            if index >= args.count:
                break
        return

    raise ValueError(f"unsupported demo command: {command}")


def main(argv: Sequence[str] | None = None) -> int:
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
