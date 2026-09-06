"""Pinned-SDK subprocess acceptance tests for the MCP stdio transport.

The reviewed ``mcp==2.1.1`` stdio shutdown contract is host-owned: close stdin
first, wait boundedly, then escalate if the child does not exit. Signal-only
graceful unwinding is deliberately not emulated by this adapter because the
SDK can have a worker thread blocked on its private stdin duplicate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, TextIO, cast
from wsgiref.simple_server import WSGIServer, make_server

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from mcp_test_support import MUTATION_TOOL_NAMES, READ_ONLY_TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]
_TEST_TOKEN = "stdio-transport-test-token"
_PROCESS_EXIT_TIMEOUT_SECONDS = 5.0
_STATUS_RESPONSE_JSON = (
    '{"state":"connected","started_at_unix_ms":1000,"connected_at_unix_ms":1100,'
    '"last_message_at_unix_ms":1200,"reconnect_attempts":0,"last_failure":null,'
    '"framebuffer_revision":7,"rejected_commands":0,"dropped_events":0,'
    '"fatal_exit":false,"shutting_down":false}'
)
_CONTROLLER_REQUESTS: list[tuple[str, str, dict[str, Any] | None]] = []
StartResponse = Callable[[str, list[tuple[str, str]]], object]


def _json_response(
    start_response: StartResponse,
    status: str,
    payload: dict[str, Any],
) -> list[bytes]:
    """Return one bounded JSON response from the controller stub."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _status_response_payload() -> dict[str, Any]:
    """Decode the fixed status fixture while proving it remains an object."""
    payload: object = json.loads(_STATUS_RESPONSE_JSON)
    if not isinstance(payload, dict) or any(
        not isinstance(key, str) for key in payload
    ):
        raise AssertionError("fixed status fixture must be a JSON object with string keys")
    return cast(dict[str, Any], payload)


def _controller_app(
    environment: dict[str, Any],
    start_response: StartResponse,
) -> list[bytes]:
    """Serve only the authenticated controller routes required by MCP-008."""
    if environment.get("HTTP_AUTHORIZATION") != f"Bearer {_TEST_TOKEN}":
        return _json_response(
            start_response,
            "401 Unauthorized",
            {"error": "unauthorized"},
        )

    method = str(environment.get("REQUEST_METHOD", ""))
    path = str(environment.get("PATH_INFO", ""))
    payload: dict[str, Any] | None = None
    if method == "POST":
        raw_length = str(environment.get("CONTENT_LENGTH", "0") or "0")
        try:
            content_length = int(raw_length, 10)
            raw_body = environment["wsgi.input"].read(content_length)
            decoded = json.loads(raw_body.decode("utf-8"))
        except (KeyError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return _json_response(
                start_response,
                "400 Bad Request",
                {"error": "invalid request"},
            )
        if not isinstance(decoded, dict):
            return _json_response(
                start_response,
                "400 Bad Request",
                {"error": "invalid request"},
            )
        payload = decoded

    _CONTROLLER_REQUESTS.append((method, path, payload))
    if method == "GET" and path == "/v1/status":
        return _json_response(
            start_response,
            "200 OK",
            _status_response_payload(),
        )
    if method == "POST" and path == "/v1/pointer/move":
        return _json_response(
            start_response,
            "200 OK",
            {"command_id": 41, "status": "succeeded"},
        )
    return _json_response(start_response, "404 Not Found", {"error": "not found"})


@contextmanager
def _temporary_directory_path() -> Iterator[Path]:
    """Own one temporary directory and expose only its path."""
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


@contextmanager
def _controller_server() -> Iterator[WSGIServer]:
    """Own the local controller socket through a real context manager."""
    with make_server("127.0.0.1", 0, _controller_app) as server:
        yield server


def _mcp_environment(
    controller_url: str,
    token_path: Path,
    *,
    allow_mutations: bool,
) -> dict[str, str]:
    """Return only explicit MCP configuration for an SDK-spawned child."""
    return {
        "VRC_MCP_CONTROLLER_URL": controller_url,
        "VRC_MCP_CONTROLLER_TOKEN_FILE": str(token_path),
        "VRC_MCP_CONTROLLER_TIMEOUT_SECONDS": "2",
        "VRC_MCP_ALLOW_MUTATIONS": "true" if allow_mutations else "false",
        "VRC_MCP_MAX_CONCURRENT_CALLS": "2",
    }


def _process_environment(mcp_environment: dict[str, str]) -> dict[str, str]:
    """Return a subprocess environment without inheriting unrelated MCP config."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VRC_MCP_")
    }
    environment.update(mcp_environment)
    return environment


@asynccontextmanager
async def _official_stdio_session(
    controller_url: str,
    token_path: Path,
    *,
    allow_mutations: bool,
    errlog: TextIO,
) -> AsyncIterator[ClientSession]:
    """Spawn the real executable through the pinned SDK stdio client."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "vnc_remote_control.mcp_server"],
        env=_mcp_environment(
            controller_url,
            token_path,
            allow_mutations=allow_mutations,
        ),
        cwd=ROOT,
    )
    async with stdio_client(parameters, errlog=errlog) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


class McpStdioTransportTests(unittest.IsolatedAsyncioTestCase):
    """Exercise stdio through a real MCP child process and controller HTTP hop."""

    temporary_directory: Path
    controller: WSGIServer
    controller_thread: threading.Thread
    token_path: Path
    controller_url: str

    def setUp(self) -> None:
        """Start one bounded local controller stub and secret file."""
        _CONTROLLER_REQUESTS.clear()
        self.temporary_directory = self.enterContext(_temporary_directory_path())
        self.token_path = self.temporary_directory / "controller-token.txt"
        self.token_path.write_text(_TEST_TOKEN + "\n", encoding="utf-8")
        if os.name == "posix":
            self.token_path.chmod(0o600)

        self.controller = self.enterContext(_controller_server())
        self.controller_url = f"http://127.0.0.1:{self.controller.server_port}"
        self.controller_thread = threading.Thread(
            target=self.controller.serve_forever,
            name="mcp-stdio-controller-stub",
            daemon=True,
        )
        self.controller_thread.start()
        self.addCleanup(self._stop_controller)

    def _stop_controller(self) -> None:
        """Stop the local controller before its context manager closes the socket."""
        self.controller.shutdown()
        self.controller_thread.join(timeout=2.0)
        self.assertFalse(self.controller_thread.is_alive())

    @contextmanager
    def _raw_stdio_process(
        self,
        *,
        allow_mutations: bool = False,
    ) -> Iterator[subprocess.Popen[str]]:
        """Own one raw child and guarantee bounded cleanup on failed assertions."""
        environment = _process_environment(
            _mcp_environment(
                self.controller_url,
                self.token_path,
                allow_mutations=allow_mutations,
            )
        )
        with subprocess.Popen(
            [sys.executable, "-m", "vnc_remote_control.mcp_server"],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        ) as process:
            try:
                yield process
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=_PROCESS_EXIT_TIMEOUT_SECONDS)

    async def test_default_stdio_catalog_and_read_invocation_use_official_client(self) -> None:
        """Default executable stdio exposes only reads and executes one through HTTP."""
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errlog:
            async with _official_stdio_session(
                self.controller_url,
                self.token_path,
                allow_mutations=False,
                errlog=errlog,
            ) as session:
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                self.assertEqual(names, READ_ONLY_TOOL_NAMES)
                self.assertTrue(names.isdisjoint(MUTATION_TOOL_NAMES))

                result = await session.call_tool("vnc_get_status", {})
                self.assertFalse(result.is_error)
                self.assertIsNotNone(result.structured_content)
                assert result.structured_content is not None
                self.assertEqual(result.structured_content["state"], "connected")
                self.assertEqual(result.structured_content["framebuffer_revision"], 7)

            errlog.seek(0)
            stderr = errlog.read()
        self.assertNotIn(_TEST_TOKEN, stderr)
        self.assertEqual(_CONTROLLER_REQUESTS, [("GET", "/v1/status", None)])

    async def test_mutation_opt_in_invokes_one_real_stdio_mutation(self) -> None:
        """Explicit mutation opt-in exposes the catalog and maps one call exactly once."""
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errlog:
            async with _official_stdio_session(
                self.controller_url,
                self.token_path,
                allow_mutations=True,
                errlog=errlog,
            ) as session:
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                self.assertEqual(names, READ_ONLY_TOOL_NAMES | MUTATION_TOOL_NAMES)

                result = await session.call_tool(
                    "vnc_move_pointer",
                    {"x": 17, "y": 23},
                )
                self.assertFalse(result.is_error)
                self.assertEqual(
                    result.structured_content,
                    {"command_id": 41, "status": "succeeded"},
                )

            errlog.seek(0)
            stderr = errlog.read()
        self.assertNotIn(_TEST_TOKEN, stderr)
        self.assertEqual(
            _CONTROLLER_REQUESTS,
            [("POST", "/v1/pointer/move", {"x": 17, "y": 23})],
        )

    def test_process_eof_exits_cleanly_without_stdout_noise(self) -> None:
        """Closing stdin ends the real executable promptly with no non-protocol stdout."""
        with self._raw_stdio_process() as process:
            self.assertIsNotNone(process.stdin)
            assert process.stdin is not None
            process.stdin.close()
            return_code = process.wait(timeout=_PROCESS_EXIT_TIMEOUT_SECONDS)
            self.assertEqual(return_code, 0)
            self.assertIsNotNone(process.stdout)
            self.assertIsNotNone(process.stderr)
            assert process.stdout is not None and process.stderr is not None
            self.assertEqual(process.stdout.read(), "")
            stderr = process.stderr.read()
            self.assertNotIn("Traceback", stderr)
            self.assertNotIn(_TEST_TOKEN, stderr)


if __name__ == "__main__":
    unittest.main()
