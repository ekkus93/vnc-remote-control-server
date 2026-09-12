"""Regression tests for finite controller HTTP response ingestion."""

# This module intentionally exercises the private bounded-read primitive as a
# transport-boundary unit in addition to the public VncClient endpoint tests.
# pylint: disable=protected-access

from __future__ import annotations

import io
import unittest
from email.message import Message
from typing import Any
from unittest import mock
from urllib.error import HTTPError

import vnc_remote_control.client as client_module
from vnc_remote_control import ProtocolError, VncClient


class ChunkedResponse:
    """In-memory response that records every bounded read request."""

    def __init__(
        self,
        status: int,
        body: bytes,
        headers: Message | None = None,
        *,
        max_chunk: int | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or Message()
        self._stream = io.BytesIO(body)
        self._max_chunk = max_chunk
        self.read_amounts: list[int | None] = []

    def read(self, amt: int | None = None) -> bytes:
        """Read at most the requested amount while recording the request."""
        self.read_amounts.append(amt)
        if amt is not None and self._max_chunk is not None:
            amt = min(amt, self._max_chunk)
        return self._stream.read(-1 if amt is None else amt)

    def __enter__(self) -> ChunkedResponse:
        """Enter the fake response context."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Exit the fake response context."""
        return None


class PythonResponseBoundsTests(unittest.TestCase):
    """Verify bodies are bounded before full materialization."""

    def test_bounded_reader_accepts_exact_limit_without_content_length(self) -> None:
        """Accept a body exactly at the byte ceiling without Content-Length."""
        response = ChunkedResponse(200, b"12345678")
        body = client_module._bounded_response_body(
            response,
            response.headers,
            limit=8,
            context="test response",
        )
        self.assertEqual(body, b"12345678")
        self.assertTrue(response.read_amounts)
        self.assertTrue(all(amount is not None and amount <= 9 for amount in response.read_amounts))

    def test_bounded_reader_rejects_one_byte_over_even_with_dishonest_small_length(self) -> None:
        """Reject a one-byte overrun despite a dishonest small Content-Length."""
        headers = Message()
        headers["Content-Length"] = "3"
        response = ChunkedResponse(200, b"123456789", headers)
        with self.assertRaisesRegex(ProtocolError, "response byte limit"):
            client_module._bounded_response_body(
                response,
                response.headers,
                limit=8,
                context="test response",
            )

    def test_chunked_short_reads_still_detect_eventual_overflow(self) -> None:
        """Detect eventual overflow across multiple short reads."""
        response = ChunkedResponse(200, b"123456789", max_chunk=2)
        with self.assertRaisesRegex(ProtocolError, "response byte limit"):
            client_module._bounded_response_body(
                response,
                response.headers,
                limit=8,
                context="test response",
            )
        self.assertGreater(len(response.read_amounts), 1)

    def test_declared_oversize_is_rejected_before_body_read(self) -> None:
        """Reject a declared oversized body before reading any bytes."""
        headers = Message()
        headers["Content-Length"] = "9"
        response = ChunkedResponse(200, b"", headers)
        with self.assertRaisesRegex(ProtocolError, "response byte limit"):
            client_module._bounded_response_body(
                response,
                response.headers,
                limit=8,
                context="test response",
            )
        self.assertEqual(response.read_amounts, [])

    def test_invalid_content_length_fails_closed(self) -> None:
        """Reject malformed Content-Length rather than guessing."""
        headers = Message()
        headers["Content-Length"] = "not-a-number"
        response = ChunkedResponse(200, b"{}", headers)
        with self.assertRaisesRegex(ProtocolError, "Content-Length was invalid"):
            client_module._bounded_response_body(
                response,
                response.headers,
                limit=8,
                context="test response",
            )

    def test_json_endpoint_uses_finite_transport_limit(self) -> None:
        """Apply the finite JSON body ceiling to controller endpoints."""
        response = ChunkedResponse(200, b"123456789")

        def opener(request: Any, *, timeout: float) -> ChunkedResponse:
            del request, timeout
            return response

        client = VncClient("http://controller", "token", _http_open=opener)
        with (
            mock.patch.object(client_module, "MAX_JSON_RESPONSE_BYTES", 8),
            self.assertRaisesRegex(ProtocolError, "response byte limit"),
        ):
            client.get_status()

    def test_metrics_endpoint_uses_finite_transport_limit(self) -> None:
        """Apply the finite text ceiling to the metrics endpoint."""
        response = ChunkedResponse(200, b"123456789")

        def opener(request: Any, *, timeout: float) -> ChunkedResponse:
            del request, timeout
            return response

        client = VncClient("http://controller", "token", _http_open=opener)
        with (
            mock.patch.object(client_module, "MAX_METRICS_RESPONSE_BYTES", 8),
            self.assertRaisesRegex(ProtocolError, "response byte limit"),
        ):
            client.get_metrics()
        self.assertLessEqual(max(amount for amount in response.read_amounts if amount), 9)

    def test_screenshot_endpoint_accepts_body_exactly_at_transport_limit(self) -> None:
        """Accept screenshot wire data exactly at its transport ceiling."""
        response = ChunkedResponse(200, b"12345678")

        def opener(request: Any, *, timeout: float) -> ChunkedResponse:
            del request, timeout
            return response

        client = VncClient("http://controller", "token", _http_open=opener)
        with mock.patch.object(client_module, "MAX_SCREENSHOT_RESPONSE_BYTES", 8):
            screenshot = client.get_screenshot()
        self.assertEqual(screenshot.data, b"12345678")

    def test_screenshot_endpoint_rejects_wire_body_before_unbounded_read(self) -> None:
        """Reject oversized screenshot wire data during bounded ingestion."""
        response = ChunkedResponse(200, b"123456789")

        def opener(request: Any, *, timeout: float) -> ChunkedResponse:
            del request, timeout
            return response

        client = VncClient("http://controller", "token", _http_open=opener)
        with (
            mock.patch.object(client_module, "MAX_SCREENSHOT_RESPONSE_BYTES", 8),
            self.assertRaisesRegex(ProtocolError, "response byte limit"),
        ):
            client.get_screenshot()
        self.assertLessEqual(max(amount for amount in response.read_amounts if amount), 9)

    def test_oversized_http_error_body_is_sanitized_and_bounded(self) -> None:
        """Bound oversized HTTP error bodies without echoing their payload."""
        secret = b"ERROR_BODY_SECRET_SENTINEL"

        def opener(request: Any, *, timeout: float) -> ChunkedResponse:
            del timeout
            raise HTTPError(
                request.full_url,
                500,
                "Internal Server Error",
                Message(),
                io.BytesIO(secret),
            )

        client = VncClient("http://controller", "token", _http_open=opener)
        with mock.patch.object(client_module, "MAX_ERROR_RESPONSE_BYTES", 8):
            with self.assertRaises(ProtocolError) as captured:
                client.get_status()
        self.assertIn("response byte limit", str(captured.exception))
        self.assertNotIn(secret.decode(), str(captured.exception))


if __name__ == "__main__":
    unittest.main()
