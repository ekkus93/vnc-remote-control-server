"""Authentication contract, missing-secret, and wrong-password checks."""

from __future__ import annotations

import os
from typing import Any

from r13_config import API_TOKEN, COMPOSE_FILE, MISSING_PROJECT, VNC_PASSWORD, WRONG_VNC_PASSWORD
from r13_harness import Harness
from r13_helpers import error_code, require, websocket_status


def assert_auth_contract(harness: Harness) -> None:
    """Verify every protected route rejects missing/wrong tokens and query-string tokens."""
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
            require(
                response.status == 401,
                f"{method} {path} accepted token={token!r}: {response.status}",
            )
            require(
                error_code(response) == "unauthorized",
                f"{method} {path} did not return unauthorized",
            )
    query = harness.request("GET", f"/v1/status?token={API_TOKEN}", token=None)
    require(query.status == 401, "query-string API token was accepted")
    require(
        websocket_status(harness.api_port, "/v1/events", None) == 401,
        "unauthenticated WebSocket upgraded",
    )
    require(
        websocket_status(harness.api_port, f"/v1/events?token={API_TOKEN}", None) == 401,
        "query-string WebSocket token was accepted",
    )
    require(
        websocket_status(harness.api_port, "/v1/events", "wrong-token") == 401,
        "wrong-token WebSocket upgraded",
    )


def assert_wrong_password_and_missing_secret(harness: Harness) -> None:
    """Verify a missing VNC secret fails startup closed and a wrong one authenticates-fails."""
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
    os.chmod(harness.vnc_secret, 0o600)
    harness.vnc_secret.write_text(WRONG_VNC_PASSWORD, encoding="utf-8")
    os.chmod(harness.vnc_secret, 0o444)
    harness.compose("up", "--detach", "controller")
    status = harness.wait_status(lambda value: value.get("state") == "authentication_failed", 20)
    require(status.get("last_failure") == "authentication", f"wrong failure class: {status}")
    os.chmod(harness.vnc_secret, 0o600)
    harness.vnc_secret.write_text(VNC_PASSWORD, encoding="utf-8")
    os.chmod(harness.vnc_secret, 0o444)
    harness.compose("rm", "--force", "--stop", "controller")
    harness.compose("up", "--detach", "controller")
    harness.wait_ready()
