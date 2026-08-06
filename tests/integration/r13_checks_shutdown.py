"""Log redaction, idle shutdown, and queued-shutdown checks."""

from __future__ import annotations

import concurrent.futures
import json
import socket
import threading
import time

from r13_config import (
    API_TOKEN,
    INBOUND_CLIPBOARD,
    OUTBOUND_CLIPBOARD,
    SUPPORTED_TEXT,
    UNSUPPORTED_TEXT,
    VNC_PASSWORD,
    WRONG_VNC_PASSWORD,
)
from r13_harness import Harness
from r13_helpers import error_code, post_json, read_http_response, require, wait_until
from r13_types import HttpResult


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
