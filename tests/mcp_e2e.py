#!/usr/bin/env python3
"""MCP-011 real-controller/TigerVNC end-to-end acceptance.

This suite deliberately reuses the production Compose controller and isolated
TigerVNC desktop from the R13 integration harness. The MCP process itself runs
on the host through the exact pinned SDK stdio client so the test covers the
real boundary:

    official MCP client -> MCP adapter -> typed HTTP client -> production
    controller -> worker -> LibVNC -> isolated TigerVNC desktop

Sensitive text, clipboard content, controller bearer tokens, screenshot bytes,
and VNC passwords are never written to progress output or diagnostics. The
suite never retries mutation calls. Polling is limited to read-only state
observation after a single mutation has been issued.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from mcp_test_support import MUTATION_TOOL_NAMES, READ_ONLY_TOOL_NAMES
from r13_config import API_TOKEN, PROJECT, ROOT, VNC_PASSWORD
from r13_harness import Harness
from r13_types import Failure

_TYPED_TEXT = "MCP-E2E-TYPED-PAYLOAD-MUST-NOT-LOG"
_OUTBOUND_CLIPBOARD = "MCP-E2E-OUTBOUND-CLIPBOARD-MUST-NOT-LOG"
_READ_PHASE_TIMEOUT_SECONDS = 60.0
_MUTATION_PHASE_TIMEOUT_SECONDS = 90.0
_STATE_DEADLINE_SECONDS = 12.0
_RECONNECT_DEADLINE_SECONDS = 20.0
_PROCESS_EXIT_SETTLE_SECONDS = 0.05

_FORBIDDEN_LOG_VALUES = (
    API_TOKEN,
    VNC_PASSWORD,
    _TYPED_TEXT,
    _OUTBOUND_CLIPBOARD,
)
_KNOWN_FAILURES = (
    AssertionError,
    Failure,
    OSError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
    binascii.Error,
    TimeoutError,
)
_CLEANUP_FAILURES = (
    AssertionError,
    Failure,
    OSError,
    subprocess.SubprocessError,
    json.JSONDecodeError,
)


def _log(message: str) -> None:
    """Emit one fixed, payload-free progress line."""
    print(f"[mcp-e2e] {message}", file=sys.stderr, flush=True)


def _sanitize(text: str) -> str:
    """Redact every fixed sensitive fixture from diagnostic text."""
    sanitized = text
    for value in _FORBIDDEN_LOG_VALUES:
        sanitized = sanitized.replace(value, "[REDACTED]")
    return sanitized


def _require(condition: bool, message: str) -> None:
    """Raise a fixed assertion when an E2E invariant is false."""
    if not condition:
        raise AssertionError(message)


def _mcp_environment(
    harness: Harness,
    *,
    allow_mutations: bool,
) -> dict[str, str]:
    """Return explicit file-backed stdio MCP configuration for one child."""
    environment = {
        "VRC_MCP_CONTROLLER_URL": f"http://127.0.0.1:{harness.api_port}",
        "VRC_MCP_CONTROLLER_TOKEN_FILE": str(harness.api_secret),
        "VRC_MCP_CONTROLLER_TIMEOUT_SECONDS": "5",
        "VRC_MCP_ALLOW_MUTATIONS": "true" if allow_mutations else "false",
        "VRC_MCP_MAX_CONCURRENT_CALLS": "4",
        "VRC_MCP_TRANSPORT": "stdio",
    }
    _require(
        API_TOKEN not in environment.values(),
        "MCP subprocess environment contained the raw controller token",
    )
    return environment


def _child_pids() -> frozenset[int]:
    """Return direct child PIDs of this Linux E2E process."""
    path = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children")
    raw = path.read_text(encoding="ascii").strip()
    if not raw:
        return frozenset()
    return frozenset(int(value) for value in raw.split())


async def _run_stdio_phase(
    harness: Harness,
    *,
    allow_mutations: bool,
    phase: Callable[[ClientSession], Awaitable[None]],
) -> str:
    """Run one official-SDK stdio session and return stderr after shutdown."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "vnc_remote_control.mcp_server"],
        env=_mcp_environment(
            harness,
            allow_mutations=allow_mutations,
        ),
        cwd=ROOT,
    )
    baseline_children = _child_pids()
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errlog:
        async with stdio_client(parameters, errlog=errlog) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await phase(session)
        errlog.seek(0)
        stderr = errlog.read()
    time.sleep(_PROCESS_EXIT_SETTLE_SECONDS)
    _require(
        _child_pids() == baseline_children,
        "official MCP stdio session left a child process behind",
    )
    return stderr


def _structured_result(result: Any, label: str) -> dict[str, Any]:
    """Return one successful structured result without echoing its contents."""
    _require(
        not bool(result.is_error),
        f"{label} unexpectedly returned an MCP error",
    )
    content = result.structured_content
    _require(
        isinstance(content, dict),
        f"{label} omitted structured content",
    )
    assert isinstance(content, dict)
    return content


def _command_id(result: Any, label: str) -> int:
    """Require terminal mutation success and return its real command ID."""
    content = _structured_result(result, label)
    command_id = content.get("command_id")
    _require(
        content.get("status") == "succeeded",
        f"{label} did not report succeeded",
    )
    _require(
        isinstance(command_id, int)
        and not isinstance(command_id, bool)
        and command_id > 0,
        f"{label} omitted a positive command ID",
    )
    assert isinstance(command_id, int) and not isinstance(command_id, bool)
    return command_id


def _wait_desktop_state(
    harness: Harness,
    predicate: Callable[[dict[str, Any]], bool],
    label: str,
) -> dict[str, Any]:
    """Poll desktop state without dumping payload-bearing state on failure."""
    deadline = time.monotonic() + _STATE_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        state = harness.desktop_state()
        if predicate(state):
            return state
        time.sleep(0.1)
    raise AssertionError(
        f"desktop state deadline exceeded while waiting for {label}"
    )


def _desktop_controls(harness: Harness) -> dict[str, Any]:
    """Return the deterministic control coordinate map after shape checks."""
    controls = harness.desktop_state().get("controls")
    _require(
        isinstance(controls, dict),
        "desktop state omitted deterministic controls",
    )
    assert isinstance(controls, dict)
    for name in ("increment", "copy"):
        point = controls.get(name)
        _require(
            isinstance(point, dict),
            f"desktop control {name} was missing",
        )
        assert isinstance(point, dict)
        _require(
            isinstance(point.get("x"), int)
            and isinstance(point.get("y"), int),
            f"desktop control {name} had invalid coordinates",
        )
    return controls


def _verify_desktop_clipboard_digest(
    harness: Harness,
    expected_text: str,
) -> None:
    """Verify X clipboard content while printing only its SHA-256 digest."""
    script = r'''
import hashlib
import sys
import time
import tkinter as tk

expected = sys.stdin.read()
expected_digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
root = tk.Tk()
root.withdraw()
deadline = time.monotonic() + 10
try:
    while time.monotonic() < deadline:
        root.update()
        try:
            value = root.clipboard_get()
        except tk.TclError:
            value = None
        if value is not None:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            if digest == expected_digest:
                print(expected_digest)
                raise SystemExit(0)
        time.sleep(0.05)
finally:
    root.destroy()
raise SystemExit("clipboard digest deadline exceeded")
'''
    result = harness.run(
        [
            *harness.compose_base,
            "exec",
            "-T",
            "-e",
            "DISPLAY=:1",
            "desktop",
            "python3",
            "-c",
            script,
        ],
        input_text=expected_text,
        timeout=15,
    )
    expected_digest = hashlib.sha256(
        expected_text.encode("utf-8")
    ).hexdigest()
    _require(
        result.stdout.strip() == expected_digest,
        "desktop clipboard digest did not match",
    )


def _verify_secret_file_ingress(harness: Harness) -> None:
    """Prove controller and MCP configuration use paths, not raw token values."""
    _require(
        API_TOKEN not in harness.env.values(),
        "production Compose environment contained the raw controller token",
    )
    controller_id = harness.service_id("controller")
    _require(bool(controller_id), "production controller container was not running")
    result = harness.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            controller_id,
        ]
    )
    environment = json.loads(result.stdout)
    _require(
        isinstance(environment, list),
        "controller container environment metadata was not an array",
    )
    assert isinstance(environment, list)
    rendered = "\n".join(str(value) for value in environment)
    _require(
        API_TOKEN not in rendered,
        "controller container environment exposed the raw bearer token",
    )
    _require(
        "VRC_API_TOKEN_FILE=/run/secrets/api_token" in environment,
        "controller did not receive its bearer token through the secret file",
    )


def _verify_raw_vnc_unpublished(harness: Harness) -> None:
    """Prove the production desktop has no host-side VNC port binding."""
    desktop_id = harness.service_id("desktop")
    _require(bool(desktop_id), "production desktop container was not running")
    result = harness.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Ports}}",
            desktop_id,
        ]
    )
    ports = json.loads(result.stdout)
    _require(
        isinstance(ports, dict),
        "desktop port metadata was not an object",
    )
    assert isinstance(ports, dict)
    _require(
        ports.get("5901/tcp") is None,
        "raw TigerVNC port 5901 was published to the host",
    )


def _start_real_stack(harness: Harness) -> None:
    """Build and start production Compose with deterministic readiness."""
    _log("building production controller and isolated desktop images")
    harness.compose("build", timeout=240)
    harness.compose(
        "up",
        "--detach",
        "--no-build",
        timeout=60,
    )
    harness.wait_service_health("desktop", 120)
    harness.wait_ready(120)
    _verify_secret_file_ingress(harness)
    _verify_raw_vnc_unpublished(harness)


def _assert_image_result(result: Any) -> None:
    """Require one real native 1280x800 PNG image returned through MCP."""
    _require(
        not bool(result.is_error),
        "screenshot tool returned an MCP error",
    )
    _require(
        len(result.content) == 1,
        "screenshot tool did not return exactly one content item",
    )
    image = result.content[0]
    _require(
        getattr(image, "type", None) == "image",
        "screenshot content was not native image content",
    )
    _require(
        getattr(image, "mime_type", None) == "image/png",
        "screenshot MIME type was not image/png",
    )
    encoded = getattr(image, "data", None)
    _require(
        isinstance(encoded, str),
        "screenshot image data was not base64 text",
    )
    assert isinstance(encoded, str)
    png = base64.b64decode(encoded, validate=True)
    _require(
        png.startswith(b"\x89PNG\r\n\x1a\n"),
        "screenshot image did not contain PNG data",
    )
    _require(len(png) >= 24, "screenshot PNG was truncated")
    width, height = struct.unpack(">II", png[16:24])
    _require(
        (width, height) == (1280, 800),
        "screenshot dimensions were not 1280x800",
    )


async def _read_only_phase(session: ClientSession) -> None:
    """Exercise the real controller through the default read-only catalog."""
    listed = await session.list_tools()
    names = {tool.name for tool in listed.tools}
    _require(
        names == READ_ONLY_TOOL_NAMES,
        "default MCP catalog did not exactly match read tools",
    )
    _require(
        names.isdisjoint(MUTATION_TOOL_NAMES),
        "mutation tools were visible without opt-in",
    )

    status = _structured_result(
        await session.call_tool("vnc_get_status", {}),
        "status read",
    )
    _require(
        status.get("state") == "connected",
        "MCP status did not report connected",
    )

    display = _structured_result(
        await session.call_tool("vnc_get_display", {}),
        "display read",
    )
    _require(
        display.get("width") == 1280
        and display.get("height") == 800
        and display.get("complete") is True,
        "MCP display metadata was not the current 1280x800 framebuffer",
    )

    _assert_image_result(
        await session.call_tool("vnc_get_screenshot", {})
    )


async def _wait_clipboard_from_desktop(session: ClientSession) -> None:
    """Poll reads until the desktop-originated clipboard value arrives."""
    deadline = time.monotonic() + _STATE_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        result = await session.call_tool("vnc_get_clipboard", {})
        if result.is_error:
            context = result.structured_content
            _require(
                isinstance(context, dict),
                "clipboard error omitted structured context",
            )
            assert isinstance(context, dict)
            _require(
                context.get("code") == "clipboard_unavailable",
                "clipboard polling encountered an unexpected MCP error",
            )
        else:
            content = _structured_result(result, "clipboard read")
            if content.get("text") == _TYPED_TEXT:
                revision = content.get("revision")
                _require(
                    isinstance(revision, int)
                    and not isinstance(revision, bool)
                    and revision > 0,
                    "desktop clipboard update omitted a positive revision",
                )
                return
        await asyncio.sleep(0.1)
    raise AssertionError(
        "MCP clipboard did not observe the desktop-originated update"
    )


async def _wait_reconnected(
    session: ClientSession,
    previous_connected_at: int,
) -> None:
    """Observe recovery with reads only; never replay the reconnect mutation."""
    deadline = time.monotonic() + _RECONNECT_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        result = await session.call_tool("vnc_get_status", {})
        content = _structured_result(result, "reconnect status read")
        connected_at = content.get("connected_at_unix_ms")
        if (
            content.get("state") == "connected"
            and isinstance(connected_at, int)
            and connected_at != previous_connected_at
        ):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(
        "controller did not return to a new connected generation after reconnect"
    )


def _point(
    controls: dict[str, Any],
    name: str,
) -> tuple[int, int]:
    point = controls[name]
    assert isinstance(point, dict)
    x = point["x"]
    y = point["y"]
    assert isinstance(x, int) and isinstance(y, int)
    return x, y


async def _mutation_baseline(
    session: ClientSession,
    harness: Harness,
) -> int:
    """Require the full catalog and return the current connection timestamp."""
    listed = await session.list_tools()
    _require(
        {tool.name for tool in listed.tools}
        == READ_ONLY_TOOL_NAMES | MUTATION_TOOL_NAMES,
        "mutation-enabled MCP catalog did not match the reviewed full tool set",
    )
    before = _structured_result(
        await session.call_tool("vnc_get_status", {}),
        "pre-reconnect status",
    )
    connected_at = before.get("connected_at_unix_ms")
    _require(
        isinstance(connected_at, int)
        and not isinstance(connected_at, bool),
        "connected status omitted connected timestamp",
    )
    assert isinstance(connected_at, int) and not isinstance(connected_at, bool)
    _require(
        harness.desktop_state().get("text") == "",
        "deterministic desktop did not start with empty text",
    )
    return connected_at


async def _exercise_pointer_and_text(
    session: ClientSession,
    harness: Harness,
) -> None:
    """Issue one pointer move and one text mutation and prove desktop effects."""
    _command_id(
        await session.call_tool(
            "vnc_move_pointer",
            {"x": 321, "y": 241},
        ),
        "pointer move",
    )
    _wait_desktop_state(
        harness,
        lambda state: state.get("pointer") == {"x": 321, "y": 241},
        "pointer move",
    )

    _command_id(
        await session.call_tool(
            "vnc_type_keyboard_text",
            {"text": _TYPED_TEXT},
        ),
        "keyboard text",
    )
    _wait_desktop_state(
        harness,
        lambda state: state.get("text") == _TYPED_TEXT,
        "keyboard text",
    )


async def _exercise_clipboard_and_status(
    session: ClientSession,
    harness: Harness,
) -> None:
    """Set real desktop clipboard content and inspect retained command status."""
    command_id = _command_id(
        await session.call_tool(
            "vnc_set_clipboard",
            {"text": _OUTBOUND_CLIPBOARD},
        ),
        "clipboard set",
    )
    _verify_desktop_clipboard_digest(
        harness,
        _OUTBOUND_CLIPBOARD,
    )

    command_status = _structured_result(
        await session.call_tool(
            "vnc_get_command_status",
            {"command_id": command_id},
        ),
        "command status",
    )
    _require(
        command_status.get("command_id") == command_id,
        "command status changed command ID",
    )
    _require(
        command_status.get("status") == "succeeded",
        "retained command status was not succeeded",
    )
    _require(
        command_status.get("failure") is None,
        "successful retained command reported failure",
    )
    _require(
        command_status.get("retry_safe") is False,
        "accepted command was incorrectly retry-safe",
    )


async def _exercise_clicks_and_inbound_clipboard(
    session: ClientSession,
    harness: Harness,
) -> None:
    """Click deterministic controls and read a desktop-originated clipboard."""
    controls = _desktop_controls(harness)
    baseline_counter = harness.desktop_state().get("counter")
    _require(
        isinstance(baseline_counter, int)
        and not isinstance(baseline_counter, bool),
        "desktop counter was not an integer",
    )
    assert isinstance(baseline_counter, int)

    increment_x, increment_y = _point(controls, "increment")
    _command_id(
        await session.call_tool(
            "vnc_click_pointer",
            {
                "x": increment_x,
                "y": increment_y,
                "button": "left",
            },
        ),
        "increment click",
    )
    _wait_desktop_state(
        harness,
        lambda state: state.get("counter") == baseline_counter + 1,
        "increment control click",
    )

    copy_x, copy_y = _point(controls, "copy")
    baseline_events = harness.desktop_state().get("events", [])
    _require(
        isinstance(baseline_events, list),
        "desktop events were not an array",
    )
    assert isinstance(baseline_events, list)
    baseline_copy_events = sum(
        isinstance(event, dict) and event.get("type") == "copy"
        for event in baseline_events
    )
    _command_id(
        await session.call_tool(
            "vnc_click_pointer",
            {
                "x": copy_x,
                "y": copy_y,
                "button": "left",
            },
        ),
        "copy click",
    )
    _wait_desktop_state(
        harness,
        lambda state: sum(
            isinstance(event, dict) and event.get("type") == "copy"
            for event in state.get("events", [])
        )
        > baseline_copy_events,
        "copy control click",
    )
    await _wait_clipboard_from_desktop(session)


async def _exercise_reconnect_and_failure(
    session: ClientSession,
    harness: Harness,
    previous_connected_at: int,
) -> None:
    """Issue one reconnect, observe recovery, then prove outage is MCP failure."""
    _command_id(
        await session.call_tool("vnc_request_reconnect", {}),
        "reconnect request",
    )
    await _wait_reconnected(session, previous_connected_at)

    _log(
        "stopping the real controller for negative MCP error propagation proof"
    )
    harness.compose(
        "stop",
        "--timeout",
        "10",
        "controller",
        timeout=20,
    )
    controller_state = harness.service_state("controller")
    _require(
        controller_state is not None
        and controller_state.get("Status") == "exited",
        "production controller did not enter the stopped state",
    )

    failed_read = await session.call_tool("vnc_get_status", {})
    _require(
        bool(failed_read.is_error),
        "controller outage incorrectly became MCP read success",
    )
    _require(
        failed_read.structured_content == {"kind": "transport_error"},
        "controller outage did not preserve the MCP transport-error contract",
    )


async def _mutation_phase(
    session: ClientSession,
    harness: Harness,
) -> None:
    """Exercise reviewed mutations once each against the real desktop."""
    connected_at = await _mutation_baseline(session, harness)
    await _exercise_pointer_and_text(session, harness)
    await _exercise_clipboard_and_status(session, harness)
    await _exercise_clicks_and_inbound_clipboard(session, harness)
    await _exercise_reconnect_and_failure(
        session,
        harness,
        connected_at,
    )


def _audit_runtime_logs(
    harness: Harness,
    mcp_logs: list[str],
) -> None:
    """Prove controller/MCP logs contain none of the sensitive fixtures."""
    compose_logs = harness.compose(
        "logs",
        "--no-color",
        check=False,
        timeout=20,
    )
    combined = (
        (compose_logs.stdout or "")
        + (compose_logs.stderr or "")
        + "".join(mcp_logs)
    )
    for value in _FORBIDDEN_LOG_VALUES:
        _require(
            value not in combined,
            "runtime logs exposed a prohibited MCP payload or secret",
        )


def _diagnostic_directory() -> Path | None:
    value = os.environ.get("MCP_E2E_FAILURE_ARTIFACT_DIR")
    return Path(value).resolve() if value else None


def _capture_failure_diagnostics(
    harness: Harness,
    error: BaseException,
) -> None:
    """Capture sanitized failure evidence, then prove redaction succeeded."""
    directory = _diagnostic_directory()
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {
        "failure.txt": f"{type(error).__name__}: {error}\n",
    }
    commands = {
        "compose-ps.txt": [*harness.compose_base, "ps", "--all"],
        "compose-logs.txt": [
            *harness.compose_base,
            "logs",
            "--no-color",
        ],
    }
    for name, command in commands.items():
        result = harness.run(
            command,
            check=False,
            timeout=20,
        )
        outputs[name] = (result.stdout or "") + (result.stderr or "")
    try:
        outputs["desktop-state.json"] = (
            json.dumps(
                harness.desktop_state(),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except (
        Failure,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as state_error:
        outputs["desktop-state-error.txt"] = (
            f"{type(state_error).__name__}: {state_error}\n"
        )
    outputs["manifest.json"] = (
        json.dumps(
            {
                "schema_version": 1,
                "test": "MCP-011 real controller/TigerVNC E2E",
                "github_run_id": os.environ.get("GITHUB_RUN_ID"),
                "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "github_sha": os.environ.get("GITHUB_SHA"),
                "compose_project": PROJECT,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    for name, text in outputs.items():
        (directory / name).write_text(
            _sanitize(text),
            encoding="utf-8",
        )
    for path in directory.iterdir():
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        for value in _FORBIDDEN_LOG_VALUES:
            _require(
                value not in text,
                f"failure diagnostic redaction failed for {path.name}",
            )


def _strict_cleanup(harness: Harness) -> None:
    """Bound teardown and prove no container/network/temp-dir leak remains."""
    result = harness.compose(
        "down",
        "--volumes",
        "--remove-orphans",
        check=False,
        timeout=30,
    )
    _require(
        result.returncode == 0,
        "production MCP E2E Compose teardown failed",
    )

    containers = harness.run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
        ],
        timeout=10,
    ).stdout.strip()
    _require(
        not containers,
        "MCP E2E teardown left a Compose container behind",
    )

    networks = harness.run(
        [
            "docker",
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
        ],
        timeout=10,
    ).stdout.strip()
    _require(
        not networks,
        "MCP E2E teardown left a Compose network behind",
    )

    shutil.rmtree(harness.temp)
    _require(
        not harness.temp.exists(),
        "MCP E2E temporary directory survived teardown",
    )
    harness.cleaned = True


async def _run_e2e(harness: Harness) -> None:
    """Run both MCP catalog modes against one production controller."""
    _start_real_stack(harness)
    mcp_logs: list[str] = []

    _log("running default read-only MCP phase against the real controller")
    read_log = await asyncio.wait_for(
        _run_stdio_phase(
            harness,
            allow_mutations=False,
            phase=_read_only_phase,
        ),
        timeout=_READ_PHASE_TIMEOUT_SECONDS,
    )
    mcp_logs.append(read_log)

    _log("running explicitly mutation-enabled MCP phase against TigerVNC")

    async def mutation_phase(session: ClientSession) -> None:
        await _mutation_phase(session, harness)

    mutation_log = await asyncio.wait_for(
        _run_stdio_phase(
            harness,
            allow_mutations=True,
            phase=mutation_phase,
        ),
        timeout=_MUTATION_PHASE_TIMEOUT_SECONDS,
    )
    mcp_logs.append(mutation_log)
    _audit_runtime_logs(harness, mcp_logs)


def main() -> int:
    """Run MCP-011 and make primary and cleanup failures independently visible."""
    harness = Harness()
    known_failure: BaseException | None = None
    cleanup_failure: BaseException | None = None
    try:
        try:
            asyncio.run(_run_e2e(harness))
        except _KNOWN_FAILURES as error:
            known_failure = error
            try:
                _capture_failure_diagnostics(harness, error)
            except _KNOWN_FAILURES as diagnostic_error:
                details = _sanitize(
                    f"{type(diagnostic_error).__name__}: {diagnostic_error}"
                )
                _log(f"failure diagnostic capture also failed: {details}")
    finally:
        try:
            _strict_cleanup(harness)
        except _CLEANUP_FAILURES as error:
            cleanup_failure = error
            details = _sanitize(f"{type(error).__name__}: {error}")
            _log(f"strict teardown failed: {details}")

    if known_failure is not None:
        details = _sanitize(
            f"{type(known_failure).__name__}: {known_failure}"
        )
        _log(f"fatal: {details}")
        return 1
    if cleanup_failure is not None:
        return 1

    print("mcp_real_controller_tigervnc_e2e_complete=1")
    _log("MCP-011 real controller/TigerVNC E2E passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
