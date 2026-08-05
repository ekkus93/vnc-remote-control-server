#!/usr/bin/env python3
"""R13 real-Compose integration and end-to-end acceptance suite.

Only fixed, non-sensitive fixtures are used. Failure diagnostics are sanitized
before they are written to the optional R13_FAILURE_ARTIFACT_DIR.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "compose.yaml"
FAILURE_DIR_VALUE = os.environ.get("R13_FAILURE_ARTIFACT_DIR", "")
FAILURE_DIR = Path(FAILURE_DIR_VALUE).resolve() if FAILURE_DIR_VALUE else None
RUN_SUFFIX = f"{os.environ.get('GITHUB_RUN_ID', os.getpid())}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
PROJECT = re.sub(r"[^a-z0-9-]", "", f"vrc-r13-{RUN_SUFFIX}".lower())
MISSING_PROJECT = f"{PROJECT}-missing"
API_TOKEN = f"r13-api-token-{RUN_SUFFIX}"
VNC_PASSWORD = f"r13-vnc-password-{RUN_SUFFIX}"
WRONG_VNC_PASSWORD = f"r13-wrong-vnc-password-{RUN_SUFFIX}"
SUPPORTED_TEXT = "R13 supported text 123"
UNSUPPORTED_TEXT = "R13 blocked snowman \u2603"
OUTBOUND_CLIPBOARD = "R13 outbound clipboard"
INBOUND_CLIPBOARD = "R13 inbound clipboard"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CLIPBOARD_BYTES = 1024 * 1024


class Failure(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class Harness:
    def __init__(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="vrc-r13-"))
        self.api_port = free_port()
        self.api_secret = self.temp / "api_token"
        self.vnc_secret = self.temp / "vnc_password"
        self.override = self.temp / "compose.r13.yaml"
        self.api_secret.write_text(API_TOKEN, encoding="utf-8")
        self.vnc_secret.write_text(VNC_PASSWORD, encoding="utf-8")
        os.chmod(self.temp, 0o700)
        os.chmod(self.api_secret, 0o444)
        os.chmod(self.vnc_secret, 0o444)
        self.override.write_text(
            """services:
  controller:
    environment:
      VRC_MAX_JSON_BYTES: \"2097152\"
      VRC_COMMAND_CAPACITY: \"1\"
      VRC_COMMAND_ACK_TIMEOUT_MS: \"8000\"
      VRC_SCREENSHOT_MAX_CONCURRENT: \"1\"
      VRC_RECONNECT_MIN_MS: \"100\"
      VRC_RECONNECT_MAX_MS: \"500\"
      VRC_RECONNECT_JITTER_PER_MILLE: \"0\"
      VRC_STABLE_CONNECTION_RESET_MS: \"500\"
      VRC_MANUAL_RECONNECT_INTERVAL_MS: \"5000\"
      VRC_VNC_CONNECT_TIMEOUT_MS: \"2000\"
      VRC_VNC_READ_TIMEOUT_MS: \"2000\"
      VRC_HTTP_HEADER_TIMEOUT_MS: \"2000\"
      VRC_HTTP_BODY_TIMEOUT_MS: \"5000\"
      VRC_SHUTDOWN_GRACE_MS: \"8000\"
""",
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "VRC_API_BIND_ADDRESS": "127.0.0.1",
                "VRC_API_HOST_PORT": str(self.api_port),
                "VRC_API_TOKEN_SOURCE": str(self.api_secret),
                "VRC_VNC_PASSWORD_SOURCE": str(self.vnc_secret),
                "VRC_RUST_LOG": "info",
            }
        )
        self.compose_base = [
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "-f",
            str(COMPOSE_FILE),
            "-f",
            str(self.override),
        ]
        self.cleaned = False

    def log(self, message: str) -> None:
        print(f"[r13-integration] {message}", file=sys.stderr, flush=True)

    def run(
        self,
        command: list[str],
        *,
        check: bool = True,
        capture: bool = True,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=self.env if env is None else env,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            raise Failure(
                f"command failed ({result.returncode}): {' '.join(command)}\n"
                f"stdout:\n{result.stdout or ''}\nstderr:\n{result.stderr or ''}"
            )
        return result

    def compose(
        self,
        *arguments: str,
        check: bool = True,
        capture: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run(
            [*self.compose_base, *arguments],
            check=check,
            capture=capture,
            timeout=timeout,
        )

    def service_id(self, service: str) -> str:
        return self.compose("ps", "-q", service).stdout.strip()

    def wait_service_health(self, service: str, deadline_seconds: float = 120) -> None:
        deadline = time.monotonic() + deadline_seconds
        last = "missing"
        while time.monotonic() < deadline:
            container_id = self.service_id(service)
            if container_id:
                result = self.run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                        container_id,
                    ]
                )
                last = result.stdout.strip()
                if last == "healthy":
                    return
                if last in {"unhealthy", "exited", "dead"}:
                    raise Failure(f"{service} became {last}")
            time.sleep(0.25)
        raise Failure(f"timed out waiting for {service} health; last={last}")

    def wait_ready(self, deadline_seconds: float = 120) -> None:
        deadline = time.monotonic() + deadline_seconds
        last = None
        while time.monotonic() < deadline:
            try:
                last = self.request("GET", "/health/ready", token=None, timeout=2)
            except OSError:
                time.sleep(0.2)
                continue
            if last.status == 200:
                display = self.request("GET", "/v1/display")
                require(display.status == 200, "readiness became true before display was current")
                return
            require(last.status == 503, f"unexpected readiness status {last.status}")
            time.sleep(0.2)
        raise Failure(f"controller readiness deadline exceeded; last={last}")

    def wait_status(self, predicate: Callable[[dict[str, Any]], bool], deadline_seconds: float = 20) -> dict[str, Any]:
        deadline = time.monotonic() + deadline_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                response = self.request("GET", "/v1/status", timeout=2)
            except OSError:
                time.sleep(0.1)
                continue
            if response.status == 200:
                last = response.json()
                if predicate(last):
                    return last
            time.sleep(0.1)
        raise Failure(f"status predicate deadline exceeded; last={last}")

    def request(
        self,
        method: str,
        path: str,
        body: bytes | str | dict[str, Any] | None = None,
        *,
        token: str | None = API_TOKEN,
        timeout: float = 10,
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        request_headers = {} if headers is None else dict(headers)
        payload: bytes | None
        if isinstance(body, dict):
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = body
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        connection = http.client.HTTPConnection("127.0.0.1", self.api_port, timeout=timeout)
        try:
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            response_body = response.read()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            return HttpResult(response.status, response_headers, response_body)
        finally:
            connection.close()

    def desktop_state(self) -> dict[str, Any]:
        result = self.compose(
            "exec",
            "-T",
            "desktop",
            "cat",
            "/tmp/vnc-test-app-state.json",
        )
        return json.loads(result.stdout)

    def wait_desktop_state(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        deadline_seconds: float = 12,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + deadline_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last = self.desktop_state()
            if predicate(last):
                return last
            time.sleep(0.1)
        raise Failure(f"desktop-state predicate deadline exceeded; last={json.dumps(last, sort_keys=True)}")

    def controller_metrics(self) -> tuple[int, int]:
        output = self.compose(
            "exec",
            "-T",
            "controller",
            "sh",
            "-ec",
            "awk '/^Threads:/{t=$2} /^VmRSS:/{r=$2} END{print t, r}' /proc/1/status",
        ).stdout.strip()
        threads, rss_kib = (int(value) for value in output.split())
        return threads, rss_kib

    def desktop_vnc_connections(self) -> int:
        script = r'''
from pathlib import Path
count = 0
for name in ("/proc/net/tcp", "/proc/net/tcp6"):
    path = Path(name)
    if not path.exists():
        continue
    for line in path.read_text(encoding="ascii").splitlines()[1:]:
        fields = line.split()
        local_port = int(fields[1].split(":")[1], 16)
        state = fields[3]
        if local_port == 5901 and state == "01":
            count += 1
print(count)
'''
        return int(
            self.compose(
                "exec",
                "-T",
                "desktop",
                "python3",
                "-c",
                script,
            ).stdout.strip()
        )

    def wait_container_exit(self, container_id: str, deadline_seconds: float = 15) -> tuple[int, float]:
        started = time.monotonic()
        deadline = started + deadline_seconds
        while time.monotonic() < deadline:
            state = self.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}} {{.State.ExitCode}} {{.State.Pid}}",
                    container_id,
                ]
            ).stdout.strip().split()
            if state[0] == "exited":
                require(state[2] == "0", f"exited container retained PID {state[2]}")
                return int(state[1]), time.monotonic() - started
            time.sleep(0.1)
        raise Failure("controller did not exit within bounded deadline")

    def capture_diagnostics(self, reason: BaseException) -> None:
        if FAILURE_DIR is None:
            return
        FAILURE_DIR.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, str] = {
            "failure.txt": f"{type(reason).__name__}: {reason}\n",
        }
        commands = {
            "compose-ps.txt": [*self.compose_base, "ps", "--all"],
            "compose-logs.txt": [*self.compose_base, "logs", "--no-color"],
        }
        for name, command in commands.items():
            result = self.run(command, check=False)
            outputs[name] = (result.stdout or "") + (result.stderr or "")
        for service in ("desktop", "controller"):
            container_id = self.service_id(service)
            if container_id:
                result = self.run(
                    ["docker", "inspect", "--format", "{{json .State}}", container_id],
                    check=False,
                )
                outputs[f"{service}-state.json"] = result.stdout or "{}\n"
        try:
            outputs["desktop-app-state.json"] = json.dumps(
                self.desktop_state(), indent=2, sort_keys=True
            ) + "\n"
        except Exception as error:
            outputs["desktop-app-state-error.txt"] = f"{type(error).__name__}: {error}\n"
        manifest = {
            "schema_version": 1,
            "test": "R13 Integration and E2E validation",
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "project": PROJECT,
        }
        outputs["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        forbidden = [
            API_TOKEN,
            VNC_PASSWORD,
            WRONG_VNC_PASSWORD,
            SUPPORTED_TEXT,
            UNSUPPORTED_TEXT,
            OUTBOUND_CLIPBOARD,
            INBOUND_CLIPBOARD,
        ]
        for name, text in outputs.items():
            sanitized = text
            for secret in forbidden:
                sanitized = sanitized.replace(secret, "[REDACTED]")
            (FAILURE_DIR / name).write_text(sanitized, encoding="utf-8")
        for secret in forbidden:
            for path in FAILURE_DIR.iterdir():
                if secret in path.read_text(encoding="utf-8", errors="replace"):
                    raise Failure(f"diagnostic redaction failed for {path.name}")

    def cleanup(self) -> None:
        if self.cleaned:
            return
        self.cleaned = True
        self.compose("down", "--volumes", "--remove-orphans", check=False)
        missing_env = dict(self.env)
        missing_env["VRC_VNC_PASSWORD_SOURCE"] = str(self.temp / "does-not-exist")
        self.run(
            [
                "docker",
                "compose",
                "--project-name",
                MISSING_PROJECT,
                "-f",
                str(COMPOSE_FILE),
                "down",
                "--volumes",
                "--remove-orphans",
            ],
            check=False,
            env=missing_env,
        )
        shutil.rmtree(self.temp, ignore_errors=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)


def error_code(response: HttpResult) -> str | None:
    if not response.body:
        return None
    try:
        return str(response.json().get("error", {}).get("code"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def wait_until(predicate: Callable[[], bool], description: str, deadline_seconds: float = 10) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise Failure(f"deadline exceeded: {description}")


def parse_png_dimensions(data: bytes) -> tuple[int, int]:
    require(data.startswith(b"\x89PNG\r\n\x1a\n"), "screenshot is not a PNG")
    require(data[12:16] == b"IHDR", "PNG does not begin with IHDR")
    return struct.unpack(">II", data[16:24])


def websocket_status(port: int, path: str, authorization: str | None) -> int:
    key = hashlib.sha256(os.urandom(32)).digest()[:16]
    import base64

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


def post_json(harness: Harness, path: str, payload: dict[str, Any], timeout: float = 10) -> HttpResult:
    return harness.request("POST", path, payload, timeout=timeout)


def assert_auth_contract(harness: Harness) -> None:
    harness.log("verifying all protected routes reject missing and wrong bearer tokens")
    routes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", "/v1/status", None),
        ("GET", "/v1/display", None),
        ("GET", "/v1/screenshot.png", None),
        ("GET", "/v1/events", None),
        ("GET", "/v1/metrics", None),
        ("POST", "/v1/pointer/move", {"x": 1, "y": 1}),
        ("POST", "/v1/pointer/button", {"x": 1, "y": 1, "button": "left", "pressed": True}),
        ("POST", "/v1/pointer/click", {"x": 1, "y": 1, "button": "left"}),
        ("POST", "/v1/pointer/double-click", {"x": 1, "y": 1, "button": "left", "interval_ms": 20}),
        ("POST", "/v1/pointer/scroll", {"x": 1, "y": 1, "delta_y": 1}),
        ("POST", "/v1/keyboard/key", {"key": "F1", "action": "down"}),
        ("POST", "/v1/keyboard/chord", {"keys": ["CTRL_LEFT", "a"]}),
        ("POST", "/v1/keyboard/text", {"text": "x"}),
        ("GET", "/v1/clipboard", None),
        ("PUT", "/v1/clipboard", {"text": "x"}),
        ("POST", "/v1/connection/reconnect", None),
    ]
    for method, path, payload in routes:
        for token in (None, "wrong-token"):
            response = harness.request(method, path, payload, token=token)
            require(response.status == 401, f"{method} {path} accepted token={token!r}: {response.status}")
            require(error_code(response) == "unauthorized", f"{method} {path} did not return unauthorized")
    query = harness.request("GET", f"/v1/status?token={API_TOKEN}", token=None)
    require(query.status == 401, "query-string API token was accepted")
    require(websocket_status(harness.api_port, "/v1/events", None) == 401, "unauthenticated WebSocket upgraded")
    require(
        websocket_status(harness.api_port, f"/v1/events?token={API_TOKEN}", None) == 401,
        "query-string WebSocket token was accepted",
    )
    require(
        websocket_status(harness.api_port, "/v1/events", "wrong-token") == 401,
        "wrong-token WebSocket upgraded",
    )


def assert_wrong_password_and_missing_secret(harness: Harness) -> None:
    harness.log("building R13 production images once")
    harness.compose("build")

    harness.log("verifying missing secret fails startup closed")
    missing_env = dict(harness.env)
    missing_env["VRC_VNC_PASSWORD_SOURCE"] = str(harness.temp / "missing-vnc-password")
    result = harness.run(
        [
            "docker",
            "compose",
            "--project-name",
            MISSING_PROJECT,
            "-f",
            str(COMPOSE_FILE),
            "up",
            "--detach",
            "--no-build",
        ],
        check=False,
        env=missing_env,
        timeout=30,
    )
    require(result.returncode != 0, "stack unexpectedly started with missing VNC secret")

    harness.log("verifying wrong VNC password reaches authentication_failed")
    harness.compose("up", "--detach", "--no-build", "desktop")
    harness.wait_service_health("desktop")
    harness.vnc_secret.write_text(WRONG_VNC_PASSWORD, encoding="utf-8")
    os.chmod(harness.vnc_secret, 0o444)
    harness.compose("up", "--detach", "controller")
    status = harness.wait_status(lambda value: value.get("state") == "authentication_failed", 20)
    require(status.get("last_failure") == "authentication", f"wrong failure class: {status}")
    harness.vnc_secret.write_text(VNC_PASSWORD, encoding="utf-8")
    os.chmod(harness.vnc_secret, 0o444)
    harness.compose("rm", "--force", "--stop", "controller")
    harness.compose("up", "--detach", "controller")
    harness.wait_ready()


def assert_initial_state_and_screenshots(harness: Harness) -> str:
    harness.log("verifying connected state, display metadata, PNG dimensions, ETag, and 304")
    status = harness.request("GET", "/v1/status")
    require(status.status == 200 and status.json().get("state") == "connected", f"not connected: {status.body!r}")
    display = harness.request("GET", "/v1/display")
    require(display.status == 200, f"display failed: {display.status}")
    display_json = display.json()
    require(display_json.get("width") == 1280 and display_json.get("height") == 800, f"bad display: {display_json}")
    require(display_json.get("complete") is True, "display was not complete")
    screenshot = harness.request("GET", "/v1/screenshot.png")
    require(screenshot.status == 200, f"screenshot failed: {screenshot.status}")
    require(parse_png_dimensions(screenshot.body) == (1280, 800), "PNG dimensions were not 1280x800")
    etag = screenshot.headers.get("etag")
    require(bool(etag), "screenshot omitted ETag")
    conditional = harness.request("GET", "/v1/screenshot.png", headers={"If-None-Match": etag})
    require(conditional.status == 304 and not conditional.body, "conditional screenshot did not return empty 304")
    return str(etag)


def assert_input_and_clipboard(harness: Harness, initial_etag: str) -> None:
    harness.log("verifying clipboard_unavailable before first inbound update")
    initial_clipboard = harness.request("GET", "/v1/clipboard")
    require(initial_clipboard.status == 503, f"initial clipboard unexpectedly available: {initial_clipboard.status}")
    require(error_code(initial_clipboard) == "clipboard_unavailable", "initial clipboard used wrong error code")

    harness.log("verifying text preflight, key ordering, and public clipboard flow")
    response = post_json(harness, "/v1/keyboard/text", {"text": SUPPORTED_TEXT})
    require(response.status == 202, f"supported text returned {response.status}")
    state = harness.wait_desktop_state(lambda value: value.get("text") == SUPPORTED_TEXT)
    baseline_text = state["text"]
    unsupported = post_json(harness, "/v1/keyboard/text", {"text": UNSUPPORTED_TEXT})
    require(unsupported.status == 422 and error_code(unsupported) == "unsupported_text", "unsupported text was not rejected atomically")
    time.sleep(0.25)
    require(harness.desktop_state().get("text") == baseline_text, "unsupported text partially mutated the entry")

    for payload in (
        {"key": "F5", "action": "down"},
        {"key": "F5", "action": "up"},
    ):
        response = post_json(harness, "/v1/keyboard/key", payload)
        require(response.status == 202, f"key transition failed: {response.status}")
    response = post_json(harness, "/v1/keyboard/chord", {"keys": ["CTRL_LEFT", "SHIFT_LEFT", "F6"]})
    require(response.status == 202, f"chord failed: {response.status}")

    response = harness.request("PUT", "/v1/clipboard", {"text": OUTBOUND_CLIPBOARD})
    require(response.status == 202, f"outbound clipboard failed: {response.status}")
    clipboard_reader = r'''
import sys, time, tkinter as tk
expected = sys.argv[1]
root = tk.Tk(); root.withdraw()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    root.update()
    try: value = root.clipboard_get()
    except tk.TclError: value = None
    if value == expected: break
    time.sleep(0.05)
else:
    root.destroy(); raise SystemExit("desktop clipboard did not receive API value")
root.destroy()
'''
    harness.compose(
        "exec",
        "-T",
        "-e",
        "DISPLAY=:1",
        "desktop",
        "python3",
        "-c",
        clipboard_reader,
        OUTBOUND_CLIPBOARD,
    )
    for keys in (["CTRL_LEFT", "a"], ["CTRL_LEFT", "v"]):
        response = post_json(harness, "/v1/keyboard/chord", {"keys": keys})
        require(response.status == 202, f"clipboard paste chord failed: {response.status}")
    harness.wait_desktop_state(lambda value: value.get("text") == OUTBOUND_CLIPBOARD)

    response = post_json(harness, "/v1/keyboard/chord", {"keys": ["CTRL_LEFT", "a"]})
    require(response.status == 202, "select-all before copy setup failed")
    response = post_json(harness, "/v1/keyboard/text", {"text": INBOUND_CLIPBOARD})
    require(response.status == 202, "copy fixture typing failed")
    harness.wait_desktop_state(lambda value: value.get("text") == INBOUND_CLIPBOARD)
    response = post_json(harness, "/v1/keyboard/chord", {"keys": ["CTRL_LEFT", "a"]})
    require(response.status == 202, "select-all before copy failed")
    response = post_json(harness, "/v1/keyboard/chord", {"keys": ["CTRL_LEFT", "c"]})
    require(response.status == 202, "copy chord failed")

    inbound: dict[str, Any] | None = None
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        snapshot = harness.request("GET", "/v1/clipboard")
        if snapshot.status == 200 and snapshot.json().get("text") == INBOUND_CLIPBOARD:
            inbound = snapshot.json()
            break
        time.sleep(0.1)
    require(inbound is not None, "API did not receive desktop clipboard")
    require(int(inbound["revision"]) > 0, "clipboard revision was not positive")
    require(int(inbound["updated_at_unix_ms"]) > 0, "clipboard timestamp was not positive")

    oversized = harness.request("PUT", "/v1/clipboard", {"text": "x" * (MAX_CLIPBOARD_BYTES + 1)}, timeout=20)
    require(oversized.status == 413 and error_code(oversized) == "clipboard_too_large", "oversized clipboard used wrong response")

    harness.log("verifying pointer, buttons, clicks, double-click, and vertical scrolling")
    baseline_events = list(harness.desktop_state().get("events", []))
    baseline_sequence = max((int(event.get("sequence", 0)) for event in baseline_events), default=0)
    requests = [
        ("/v1/pointer/move", {"x": 320, "y": 240}),
        ("/v1/pointer/button", {"x": 330, "y": 250, "button": "left", "pressed": True}),
        ("/v1/pointer/button", {"x": 330, "y": 250, "button": "left", "pressed": False}),
        ("/v1/pointer/click", {"x": 420, "y": 430, "button": "left"}),
        ("/v1/pointer/click", {"x": 440, "y": 430, "button": "middle"}),
        ("/v1/pointer/click", {"x": 460, "y": 430, "button": "right"}),
        ("/v1/pointer/double-click", {"x": 480, "y": 430, "button": "left", "interval_ms": 20}),
        ("/v1/pointer/scroll", {"x": 500, "y": 430, "delta_y": 2}),
        ("/v1/pointer/scroll", {"x": 500, "y": 430, "delta_y": -1}),
    ]
    for path, payload in requests:
        response = post_json(harness, path, payload)
        require(response.status == 202, f"{path} returned {response.status}: {response.body!r}")

    def input_complete(value: dict[str, Any]) -> bool:
        events = [event for event in value.get("events", []) if int(event.get("sequence", 0)) > baseline_sequence]
        left_down = sum(event.get("type") == "button_down" and event.get("button") == "left" for event in events)
        left_up = sum(event.get("type") == "button_up" and event.get("button") == "left" for event in events)
        middle_down = sum(event.get("type") == "button_down" and event.get("button") == "middle" for event in events)
        right_down = sum(event.get("type") == "button_down" and event.get("button") == "right" for event in events)
        scroll_up = sum(event.get("type") == "scroll" and event.get("delta_y") == 1 for event in events)
        scroll_down = sum(event.get("type") == "scroll" and event.get("delta_y") == -1 for event in events)
        return (
            value.get("pointer") == {"x": 500, "y": 430}
            and value.get("buttons") == {"left": False, "middle": False, "right": False}
            and left_down >= 4
            and left_up >= 4
            and middle_down >= 1
            and right_down >= 1
            and scroll_up >= 2
            and scroll_down >= 1
        )

    final_state = harness.wait_desktop_state(input_complete)
    events = final_state["events"]
    expected_keys = [
        ("key_down", "F5"),
        ("key_up", "F5"),
        ("key_down", "Control_L"),
        ("key_down", "Shift_L"),
        ("key_down", "F6"),
        ("key_up", "F6"),
        ("key_up", "Shift_L"),
        ("key_up", "Control_L"),
    ]
    index = 0
    for event in events:
        if index < len(expected_keys) and (event.get("type"), event.get("key")) == expected_keys[index]:
            index += 1
    require(index == len(expected_keys), "key/chord event order was not observed")

    def etag_changed() -> bool:
        response = harness.request("GET", "/v1/screenshot.png")
        return response.status == 200 and response.headers.get("etag") not in {None, initial_etag}

    wait_until(etag_changed, "screenshot ETag change after visible input", 12)


def assert_abuse_and_concurrency(harness: Harness) -> None:
    harness.log("verifying body, coordinate, scroll, queue, reconnect, and screenshot bounds")
    oversized_json = b"{" + b"x" * MAX_JSON_BYTES + b"}"
    response = harness.request(
        "POST",
        "/v1/pointer/move",
        oversized_json,
        headers={"Content-Type": "application/json"},
        timeout=20,
    )
    require(response.status == 413, f"oversized JSON returned {response.status}")

    invalid_coordinate = post_json(harness, "/v1/pointer/move", {"x": 1280, "y": 800})
    require(invalid_coordinate.status == 422 and error_code(invalid_coordinate) == "invalid_coordinate", "coordinate limit was not explicit")
    scroll = post_json(harness, "/v1/pointer/scroll", {"x": 1, "y": 1, "delta_y": 101})
    require(scroll.status == 422 and error_code(scroll) == "scroll_too_large", "scroll limit was not explicit")

    barrier = threading.Barrier(12)

    def long_click(index: int) -> HttpResult:
        barrier.wait(timeout=5)
        return post_json(
            harness,
            "/v1/pointer/double-click",
            {"x": 600 + (index % 10), "y": 450, "button": "left", "interval_ms": 1000},
            timeout=15,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(long_click, range(12)))
    require(any(result.status == 202 for result in results), "queue saturation produced no accepted command")
    require(
        any(result.status == 503 and error_code(result) == "command_queue_full" for result in results),
        f"queue saturation was not explicit: {[result.status for result in results]}",
    )

    first = post_json(harness, "/v1/connection/reconnect", {})
    second = post_json(harness, "/v1/connection/reconnect", {})
    require(first.status == 202, f"first reconnect failed: {first.status}")
    require(second.status == 429 and error_code(second) == "reconnect_rate_limited", "reconnect rate limit was not explicit")
    harness.wait_ready()

    screenshot_barrier = threading.Barrier(12)

    def screenshot(_: int) -> HttpResult:
        screenshot_barrier.wait(timeout=5)
        return harness.request("GET", "/v1/screenshot.png", timeout=15)

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        screenshots = list(executor.map(screenshot, range(12)))
    elapsed = time.monotonic() - started
    require(elapsed < 15, f"concurrent screenshots exceeded bounded deadline: {elapsed:.2f}s")
    require(all(result.status in {200, 503} for result in screenshots), "concurrent screenshots returned unexpected status")
    require(any(result.status == 200 for result in screenshots), "no concurrent screenshot succeeded")
    for result in screenshots:
        if result.status == 503:
            require(error_code(result) == "screenshot_busy", "screenshot overload used wrong error")


def assert_reconnect_and_resource_bounds(harness: Harness) -> None:
    harness.log("verifying desktop restart detection, framebuffer invalidation, reconnect, and resource bounds")
    baseline_threads, baseline_rss = harness.controller_metrics()
    previous_etag = harness.request("GET", "/v1/screenshot.png").headers["etag"]
    saw_unready = False
    saw_unavailable = False
    for cycle in range(3):
        harness.compose("stop", "desktop")
        status = harness.wait_status(lambda value: value.get("state") != "connected", 15)
        require(status.get("state") in {"degraded", "disconnected", "reconnecting", "connecting"}, f"unexpected disconnect state: {status}")
        ready = harness.request("GET", "/health/ready", token=None)
        require(ready.status == 503, "readiness remained true after desktop stop")
        saw_unready = True
        display = harness.request("GET", "/v1/display")
        screenshot = harness.request("GET", "/v1/screenshot.png")
        require(display.status == 503 and error_code(display) == "framebuffer_unavailable", "old display remained available")
        require(screenshot.status == 503 and error_code(screenshot) == "framebuffer_unavailable", "old screenshot remained available")
        saw_unavailable = True
        harness.compose("start", "desktop")
        harness.wait_service_health("desktop")
        harness.wait_ready()
        connected = harness.request("GET", "/v1/status").json()
        require(connected.get("state") == "connected", f"cycle {cycle} did not reconnect")
        new_screenshot = harness.request("GET", "/v1/screenshot.png")
        require(new_screenshot.status == 200, "screenshot did not return after reconnect")
        new_etag = new_screenshot.headers.get("etag")
        require(new_etag and new_etag != previous_etag, "ETag did not change after framebuffer invalidation")
        previous_etag = new_etag
    require(saw_unready and saw_unavailable, "reconnect scenario did not observe invalidation")
    threads, rss = harness.controller_metrics()
    require(threads <= baseline_threads + 4, f"worker thread count grew materially: {baseline_threads} -> {threads}")
    rss_allowance = max(32768, baseline_rss // 2)
    require(rss <= baseline_rss + rss_allowance, f"controller RSS grew materially: {baseline_rss} -> {rss} KiB")


def assert_logs_redacted(harness: Harness) -> None:
    harness.log("verifying secrets and payload fixtures are absent from captured service logs")
    logs = harness.compose("logs", "--no-color", "controller", "desktop").stdout
    for forbidden in (
        API_TOKEN,
        VNC_PASSWORD,
        WRONG_VNC_PASSWORD,
        SUPPORTED_TEXT,
        UNSUPPORTED_TEXT,
        OUTBOUND_CLIPBOARD,
        INBOUND_CLIPBOARD,
    ):
        require(forbidden not in logs, "service logs exposed a secret or payload fixture")


def assert_idle_shutdown(harness: Harness) -> None:
    harness.log("verifying idle SIGTERM closes VNC connection, joins worker, and exits bounded")
    wait_until(lambda: harness.desktop_vnc_connections() >= 1, "established controller VNC connection")
    controller_id = harness.service_id("controller")
    require(bool(controller_id), "controller container id missing")
    harness.run(["docker", "kill", "--signal", "TERM", controller_id])
    exit_code, elapsed = harness.wait_container_exit(controller_id)
    require(exit_code == 0, f"idle SIGTERM exit code was {exit_code}")
    require(elapsed < 15, f"idle SIGTERM exceeded bound: {elapsed:.2f}s")
    wait_until(lambda: harness.desktop_vnc_connections() == 0, "VNC connection close after controller shutdown")
    harness.compose("up", "--detach", "controller")
    harness.wait_ready()


def read_http_response(sock: socket.socket) -> HttpResult:
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


def assert_queued_shutdown(harness: Harness) -> None:
    harness.log("verifying SIGTERM with queued commands and in-flight request rejection")
    controller_id = harness.service_id("controller")
    require(bool(controller_id), "controller container id missing before queued shutdown")
    payload = json.dumps({"x": 700, "y": 500}, separators=(",", ":")).encode("utf-8")
    split = len(payload) // 2
    sock = socket.create_connection(("127.0.0.1", harness.api_port), timeout=5)
    request_headers = (
        f"POST /v1/pointer/move HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{harness.api_port}\r\n"
        f"Authorization: Bearer {API_TOKEN}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    sock.sendall(request_headers + payload[:split])

    start_barrier = threading.Barrier(6)

    def queued(index: int) -> HttpResult | Exception:
        try:
            start_barrier.wait(timeout=5)
            return post_json(
                harness,
                "/v1/pointer/double-click",
                {"x": 720 + index, "y": 520, "button": "left", "interval_ms": 1000},
                timeout=15,
            )
        except Exception as error:
            return error

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(queued, index) for index in range(6)]
        time.sleep(0.2)
        harness.run(["docker", "kill", "--signal", "TERM", controller_id])
        sock.sendall(payload[split:])
        response = read_http_response(sock)
        sock.close()
        results = [future.result(timeout=15) for future in futures]
    require(response.status == 503, f"new command during shutdown returned {response.status}")
    require(error_code(response) == "shutting_down", "new command during shutdown used wrong error")
    require(any(isinstance(result, HttpResult) for result in results), "queued-command scenario created no HTTP work")
    exit_code, elapsed = harness.wait_container_exit(controller_id)
    require(exit_code == 0, f"queued SIGTERM exit code was {exit_code}")
    require(elapsed < 15, f"queued SIGTERM exceeded bound: {elapsed:.2f}s")
    wait_until(lambda: harness.desktop_vnc_connections() == 0, "VNC close after queued shutdown")

    desktop_id = harness.service_id("desktop")
    require(bool(desktop_id), "desktop container id missing before stop")
    harness.compose("stop", "desktop")
    state = harness.run(
        ["docker", "inspect", "--format", "{{.State.Status}} {{.State.Pid}}", desktop_id]
    ).stdout.strip()
    require(state == "exited 0", f"desktop child processes did not terminate: {state}")


def main() -> int:
    harness = Harness()
    try:
        assert_wrong_password_and_missing_secret(harness)
        assert_auth_contract(harness)
        initial_etag = assert_initial_state_and_screenshots(harness)
        assert_input_and_clipboard(harness, initial_etag)
        assert_abuse_and_concurrency(harness)
        assert_reconnect_and_resource_bounds(harness)
        assert_logs_redacted(harness)
        assert_idle_shutdown(harness)
        assert_queued_shutdown(harness)
        harness.log("R13 integration and E2E validation passed")
        print("r13_integration_e2e_complete=1")
        return 0
    except BaseException as error:
        try:
            harness.capture_diagnostics(error)
        except BaseException as diagnostic_error:
            print(f"[r13-integration] diagnostic capture failed: {diagnostic_error}", file=sys.stderr)
        print(f"[r13-integration] fatal: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        harness.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
