"""Pinned-SDK subprocess acceptance tests for MCP stdio and Streamable HTTP.

The reviewed ``mcp==2.1.1`` stdio shutdown contract is host-owned: close stdin
first, wait boundedly, then escalate if the child does not exit. Signal-only
graceful unwinding is deliberately not emulated by this adapter because the
SDK can have a worker thread blocked on its private stdin duplicate.

Streamable HTTP is tested only on the SDK-protected IPv4 loopback listener. The
production config separately accepts the SDK's exact ``localhost`` and ``::1``
spellings; unit tests prove those values are forwarded without rewriting.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
from typing import Any, TextIO, cast
from wsgiref.simple_server import WSGIServer, make_server

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from mcp_test_support import MUTATION_TOOL_NAMES, READ_ONLY_TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]
_TEST_TOKEN = "transport-acceptance-test-token"
_PROCESS_EXIT_TIMEOUT_SECONDS = 5.0
_HTTP_READY_TIMEOUT_SECONDS = 5.0
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
    """Serve only the authenticated controller routes required by transport tests."""
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
    transport: str = "stdio",
    http_host: str = "127.0.0.1",
    http_port: int = 8765,
) -> dict[str, str]:
    """Return explicit MCP configuration for one child process."""
    environment = {
        "VRC_MCP_CONTROLLER_URL": controller_url,
        "VRC_MCP_CONTROLLER_TOKEN_FILE": str(token_path),
        "VRC_MCP_CONTROLLER_TIMEOUT_SECONDS": "2",
        "VRC_MCP_ALLOW_MUTATIONS": "true" if allow_mutations else "false",
        "VRC_MCP_MAX_CONCURRENT_CALLS": "2",
        "VRC_MCP_TRANSPORT": transport,
    }
    if transport == "streamable-http":
        environment["VRC_MCP_HTTP_HOST"] = http_host
        environment["VRC_MCP_HTTP_PORT"] = str(http_port)
    return environment


def _process_environment(mcp_environment: dict[str, str]) -> dict[str, str]:
    """Return a subprocess environment without inheriting unrelated MCP config."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("VRC_MCP_")
    }
    environment.update(mcp_environment)
    return environment


def _allocate_loopback_port() -> int:
    """Ask the kernel for one currently unused IPv4 loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    if not isinstance(port, int) or port < 1:
        raise AssertionError("kernel returned an invalid loopback port")
    return port


def _wait_for_listener(process: subprocess.Popen[str], host: str, port: int) -> None:
    """Wait for the child TCP listener by probing readiness, never by sleep alone."""
    deadline = time.monotonic() + _HTTP_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("MCP Streamable HTTP child exited before listener readiness")
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError("MCP Streamable HTTP listener did not become ready in time")


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


@asynccontextmanager
async def _official_http_session(url: str) -> AsyncIterator[ClientSession]:
    """Connect to the real HTTP listener through the pinned SDK client."""
    async with streamable_http_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


@contextmanager
def _http_process(
    controller_url: str,
    token_path: Path,
    *,
    port: int,
    allow_mutations: bool,
) -> Iterator[subprocess.Popen[str]]:
    """Own one real Streamable HTTP child with bounded test cleanup."""
    environment = _process_environment(
        _mcp_environment(
            controller_url,
            token_path,
            allow_mutations=allow_mutations,
            transport="streamable-http",
            http_port=port,
        )
    )
    with subprocess.Popen(
        [sys.executable, "-m", "vnc_remote_control.mcp_server"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    ) as process:
        try:
            _wait_for_listener(process, "127.0.0.1", port)
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=_PROCESS_EXIT_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    # Test-only leak prevention. Product HTTP shutdown remains the
                    # pinned SDK/uvicorn lifecycle and never uses this fallback.
                    process.kill()
                    process.wait(timeout=_PROCESS_EXIT_TIMEOUT_SECONDS)


def _tool_contract(session_result: Any) -> dict[str, dict[str, Any]]:
    """Return tool schemas/annotations keyed by name for cross-transport comparison."""
    return {
        tool.name: tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in session_result.tools
    }


def _security_status(
    port: int,
    *,
    host_header: str,
    origin_header: str | None,
) -> int:
    """Send one raw MCP POST and return the SDK security response status."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        separators=(",", ":"),
    ).encode("utf-8")
    with closing(
        http.client.HTTPConnection(
            "127.0.0.1",
            port,
            timeout=2.0,
        )
    ) as connection:
        connection.putrequest("POST", "/mcp", skip_host=True)
        connection.putheader("Host", host_header)
        if origin_header is not None:
            connection.putheader("Origin", origin_header)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Accept", "application/json, text/event-stream")
        connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        with connection.getresponse() as response:
            response.read()
            return response.status


class McpTransportAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """Exercise both initial MCP transports through real child processes."""

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
            name="mcp-transport-controller-stub",
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
    def _raw_stdio_process(self) -> Iterator[subprocess.Popen[str]]:
        """Own one raw stdio child and guarantee bounded cleanup on assertions."""
        environment = _process_environment(
            _mcp_environment(
                self.controller_url,
                self.token_path,
                allow_mutations=False,
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

    async def test_stdio_default_catalog_and_read_invocation_use_official_client(self) -> None:
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

    async def test_stdio_mutation_opt_in_invokes_exactly_one_mutation(self) -> None:
        """Explicit stdio mutation opt-in maps one request exactly once."""
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

    def test_stdio_eof_exits_cleanly_without_stdout_noise(self) -> None:
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

    async def test_http_catalog_matches_stdio_and_read_invocation_works(self) -> None:
        """HTTP uses the exact stdio catalog/schema/annotations and controller mapping."""
        port = _allocate_loopback_port()
        with _http_process(
            self.controller_url,
            self.token_path,
            port=port,
            allow_mutations=False,
        ):
            async with _official_http_session(f"http://127.0.0.1:{port}/mcp") as http_session:
                http_tools = await http_session.list_tools()
                self.assertEqual(
                    {tool.name for tool in http_tools.tools},
                    READ_ONLY_TOOL_NAMES,
                )
                result = await http_session.call_tool("vnc_get_status", {})
                self.assertFalse(result.is_error)
                self.assertIsNotNone(result.structured_content)
                assert result.structured_content is not None
                self.assertEqual(result.structured_content["state"], "connected")

            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as errlog:
                async with _official_stdio_session(
                    self.controller_url,
                    self.token_path,
                    allow_mutations=False,
                    errlog=errlog,
                ) as stdio_session:
                    stdio_tools = await stdio_session.list_tools()

        self.assertEqual(_tool_contract(http_tools), _tool_contract(stdio_tools))
        self.assertEqual(_CONTROLLER_REQUESTS, [("GET", "/v1/status", None)])

    async def test_http_mutation_opt_in_invokes_exactly_one_mutation(self) -> None:
        """Explicit HTTP mutation opt-in exposes and maps the reviewed mutation surface."""
        port = _allocate_loopback_port()
        with _http_process(
            self.controller_url,
            self.token_path,
            port=port,
            allow_mutations=True,
        ):
            async with _official_http_session(f"http://127.0.0.1:{port}/mcp") as session:
                listed = await session.list_tools()
                self.assertEqual(
                    {tool.name for tool in listed.tools},
                    READ_ONLY_TOOL_NAMES | MUTATION_TOOL_NAMES,
                )
                result = await session.call_tool(
                    "vnc_move_pointer",
                    {"x": 31, "y": 47},
                )
                self.assertFalse(result.is_error)
                self.assertEqual(
                    result.structured_content,
                    {"command_id": 41, "status": "succeeded"},
                )

        self.assertEqual(
            _CONTROLLER_REQUESTS,
            [("POST", "/v1/pointer/move", {"x": 31, "y": 47})],
        )

    def test_http_sdk_rejects_bad_host_and_origin(self) -> None:
        """The real listener keeps the SDK's DNS-rebinding Host/Origin middleware."""
        port = _allocate_loopback_port()
        with _http_process(
            self.controller_url,
            self.token_path,
            port=port,
            allow_mutations=False,
        ):
            self.assertEqual(
                _security_status(
                    port,
                    host_header="attacker.example",
                    origin_header=None,
                ),
                421,
            )
            self.assertEqual(
                _security_status(
                    port,
                    host_header=f"127.0.0.1:{port}",
                    origin_header="http://attacker.example",
                ),
                403,
            )

    def test_http_sigterm_shutdown_is_bounded_and_payload_safe(self) -> None:
        """The SDK/uvicorn HTTP listener gracefully unwinds before re-raising SIGTERM."""
        port = _allocate_loopback_port()
        with _http_process(
            self.controller_url,
            self.token_path,
            port=port,
            allow_mutations=False,
        ) as process:
            process.terminate()
            return_code = process.wait(timeout=_PROCESS_EXIT_TIMEOUT_SECONDS)
            self.assertEqual(return_code, -signal.SIGTERM)
            self.assertIsNotNone(process.stdout)
            self.assertIsNotNone(process.stderr)
            assert process.stdout is not None and process.stderr is not None
            stdout = process.stdout.read()
            stderr = process.stderr.read()
            self.assertIn("Shutting down", stderr)
            self.assertIn("Finished server process", stderr)
            self.assertNotIn(_TEST_TOKEN, stdout)
            self.assertNotIn(_TEST_TOKEN, stderr)
            self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
