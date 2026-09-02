"""Contract tests for the optional MCP package scaffold."""

from __future__ import annotations

import importlib.util
import io
import sys
import tomllib
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
SRC_ROOT = PYTHON_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from vnc_remote_control import mcp_server  # noqa: E402


class _FakeMcpServer:
    """Minimal fake matching the runtime surface consumed by the entry point."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run_calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, transport: str = "stdio", **kwargs: Any) -> None:
        """Record one transport invocation."""
        self.run_calls.append((transport, kwargs))


class McpServerScaffoldTests(unittest.TestCase):
    """Verify MCP remains optional and the server is deterministic to construct."""

    def test_package_metadata_keeps_mcp_optional_and_pinned(self) -> None:
        """Core installs stay dependency-free while the MCP extra is exact-pinned."""
        metadata = tomllib.loads((PYTHON_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(project["optional-dependencies"]["mcp"], ["mcp==2.1.1"])
        self.assertEqual(
            project["scripts"]["vnc-remote-control-mcp"],
            "vnc_remote_control.mcp_server:main",
        )

    def test_import_does_not_require_or_start_mcp_runtime(self) -> None:
        """Importing the adapter is safe when the optional MCP SDK is absent."""
        self.assertIsNone(importlib.util.find_spec("mcp"))
        self.assertEqual(mcp_server.MCP_EXTRA_REQUIREMENT, "mcp==2.1.1")

    def test_create_mcp_server_uses_injected_factory_without_starting_it(self) -> None:
        """Construction is injectable and never starts a transport implicitly."""
        server = mcp_server.create_mcp_server(factory=_FakeMcpServer)
        self.assertIsInstance(server, _FakeMcpServer)
        assert isinstance(server, _FakeMcpServer)
        self.assertEqual(server.name, "VNC Remote Control Server")
        self.assertEqual(server.run_calls, [])

    def test_missing_optional_dependency_fails_explicitly(self) -> None:
        """Requesting MCP without the extra gives an actionable hard failure."""
        with self.assertRaises(mcp_server.McpDependencyError) as context:
            mcp_server.create_mcp_server()
        message = str(context.exception)
        self.assertIn("mcp==2.1.1", message)
        self.assertIn("vnc-remote-control-client[mcp]", message)

    def test_main_reports_missing_dependency_on_stderr_and_exits_nonzero(self) -> None:
        """The executable never converts a missing SDK into apparent success."""
        stderr = io.StringIO()
        with mock.patch.object(
            mcp_server,
            "create_mcp_server",
            side_effect=mcp_server.McpDependencyError("missing MCP SDK"),
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as context:
                    mcp_server.main()
        self.assertEqual(context.exception.code, 2)
        self.assertIn("missing MCP SDK", stderr.getvalue())

    def test_main_runs_stdio_once(self) -> None:
        """The initial executable has one explicit non-network transport."""
        server = _FakeMcpServer("VNC Remote Control Server")
        with mock.patch.object(mcp_server, "create_mcp_server", return_value=server):
            mcp_server.main()
        self.assertEqual(server.run_calls, [("stdio", {})])


if __name__ == "__main__":
    unittest.main()
