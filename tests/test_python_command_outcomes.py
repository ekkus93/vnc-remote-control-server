"""R1 command-outcome reconciliation tests for the typed Python client."""

from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit

from vnc_remote_control import CommandOutcomeUnknownError, VncClient


class FakeResponse:
    """Small in-memory urllib response used by the command-outcome tests."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body
        self.headers = Message()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def timeout_body(command_id: int) -> bytes:
    return json.dumps(
        {
            "error": {
                "code": "command_timeout",
                "message": "desktop command result wait timed out; execution outcome is unknown",
                "request_id": "timeout-request",
                "command_id": command_id,
                "outcome": "unknown",
                "retry_safe": False,
            }
        }
    ).encode()


class PythonCommandOutcomeTests(unittest.TestCase):
    """Prove an unknown mutation is inspected by ID rather than retried."""

    def _run_reconciliation(self, terminal_status: str, failure: str | None) -> None:
        command_id = 77
        mutation_calls = 0
        status_calls = 0
        typed_sentinel = "R1-TYPED-PAYLOAD-MUST-NOT-APPEAR-IN-ERROR"
        token_sentinel = "R1-BEARER-MUST-NOT-APPEAR-IN-ERROR"

        def opener(request: Any, *, timeout: float) -> FakeResponse:
            nonlocal mutation_calls, status_calls
            del timeout
            path = urlsplit(request.full_url).path
            if path == "/v1/keyboard/text":
                mutation_calls += 1
                raise HTTPError(
                    request.full_url,
                    504,
                    "Gateway Timeout",
                    Message(),
                    io.BytesIO(timeout_body(command_id)),
                )
            if path == f"/v1/commands/{command_id}":
                status_calls += 1
                return FakeResponse(
                    200,
                    json.dumps(
                        {
                            "command_id": command_id,
                            "status": terminal_status,
                            "failure": failure,
                            "retry_safe": False,
                        }
                    ).encode(),
                )
            raise AssertionError(f"unexpected request path: {path}")

        client = VncClient(
            "http://controller",
            token_sentinel,
            _http_open=opener,
        )
        with self.assertRaises(CommandOutcomeUnknownError) as captured:
            client.type_keyboard_text(typed_sentinel)

        error = captured.exception
        self.assertEqual(error.command_id, command_id)
        self.assertEqual(error.outcome, "unknown")
        self.assertFalse(error.retry_safe)
        self.assertNotIn(typed_sentinel, str(error))
        self.assertNotIn(typed_sentinel, repr(error))
        self.assertNotIn(token_sentinel, str(error))
        self.assertNotIn(token_sentinel, repr(error))

        status = client.get_command_status(error.command_id)
        self.assertEqual(status.command_id, command_id)
        self.assertEqual(status.status, terminal_status)
        self.assertEqual(status.failure, failure)
        self.assertFalse(status.retry_safe)
        self.assertEqual(mutation_calls, 1, "unknown mutation must not be automatically retried")
        self.assertEqual(status_calls, 1)

    def test_unknown_timeout_can_later_report_success(self) -> None:
        self._run_reconciliation("succeeded", None)

    def test_unknown_timeout_can_later_report_failure(self) -> None:
        self._run_reconciliation("failed", "transport")


if __name__ == "__main__":
    unittest.main()
