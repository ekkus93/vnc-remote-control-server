"""Real-Compose test harness: process/container lifecycle and HTTP client."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from r13_config import (
    API_TOKEN,
    COMPOSE_FILE,
    FAILURE_DIR,
    INBOUND_CLIPBOARD,
    MISSING_PROJECT,
    OUTBOUND_CLIPBOARD,
    PROJECT,
    ROOT,
    SUPPORTED_TEXT,
    UNSUPPORTED_TEXT,
    VNC_PASSWORD,
    WRONG_VNC_PASSWORD,
)
from r13_helpers import free_port, require
from r13_types import Failure, HttpResult


class Harness:
    """Owns one real-Compose stack: secrets, override file, process/HTTP helpers."""

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
        """Print a timestamp-free, prefixed progress line to stderr."""
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
        """Run `command`, raising `Failure` on a nonzero exit unless `check=False`."""
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
        """Run `docker compose <arguments>` against this harness's stack."""
        return self.run(
            [*self.compose_base, *arguments],
            check=check,
            capture=capture,
            timeout=timeout,
        )

    def service_id(self, service: str) -> str:
        """Return `service`'s container id, or `""` if it is not running."""
        return self.compose("ps", "-q", service).stdout.strip()

    def wait_service_health(self, service: str, deadline_seconds: float = 120) -> None:
        """Poll `service` until Docker reports it healthy, or raise `Failure`."""
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
                        "{{if .State.Health}}{{.State.Health.Status}}"
                        "{{else}}{{.State.Status}}{{end}}",
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
        """Poll `/health/ready` until it (and a current display) is true, or raise."""
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

    def wait_status(
        self, predicate: Callable[[dict[str, Any]], bool], deadline_seconds: float = 20
    ) -> dict[str, Any]:
        """Poll `/v1/status` until `predicate` is true, returning that status."""
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
        """Issue one raw HTTP request to the controller and return its result."""
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
        """Read and parse the desktop test-app's current state JSON file."""
        result = self.compose(
            "exec",
            "-T",
            "desktop",
            "cat",
            "/tmp/vnc-test-app-state.json",
        )
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise Failure(f"desktop test-app state was not a JSON object: {result.stdout!r}")
        return value

    def wait_desktop_state(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        deadline_seconds: float = 12,
    ) -> dict[str, Any]:
        """Poll `desktop_state()` until `predicate` is true, returning that state."""
        deadline = time.monotonic() + deadline_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last = self.desktop_state()
            if predicate(last):
                return last
            time.sleep(0.1)
        raise Failure(
            f"desktop-state predicate deadline exceeded; last={json.dumps(last, sort_keys=True)}"
        )

    def controller_metrics(self) -> tuple[int, int]:
        """Return the controller process's `(thread count, RSS KiB)`."""
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
        """Count established VNC (port 5901) connections inside the desktop container."""
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

    def wait_container_exit(
        self, container_id: str, deadline_seconds: float = 15
    ) -> tuple[int, float]:
        """Poll until `container_id` exits, returning `(exit code, elapsed seconds)`."""
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
        """Write sanitized compose/container/desktop-state diagnostics for `reason`."""
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
        except (subprocess.SubprocessError, OSError, Failure, json.JSONDecodeError) as error:
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
        """Tear down the harness's stacks and temp directory, once."""
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
