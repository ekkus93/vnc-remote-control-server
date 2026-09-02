"""Contract tests for the optional MCP package scaffold."""

from __future__ import annotations

import builtins
import importlib
import io
import tomllib
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from vnc_remote_control import mcp_server
from vnc_remote_control.mcp_config import McpConfig, McpConfigError

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"


def _fake_server_factory(name: str) -> mock.Mock:
    server = mock.Mock()
    server.name = name
    return server


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
        """Importing the adapter never touches the optional MCP SDK."""
        original_import = builtins.__import__

        def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "mcp" or name.startswith("mcp."):
                raise AssertionError("module import attempted to load optional MCP SDK")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            reloaded = importlib.reload(mcp_server)
        self.assertEqual(reloaded.MCP_EXTRA_REQUIREMENT, "mcp==2.1.1")

    def test_create_mcp_server_uses_injected_factory_without_starting_it(self) -> None:
        """Construction is injectable and never starts a transport implicitly."""
        server = mcp_server.create_mcp_server(factory=_fake_server_factory)
        self.assertEqual(server.name, "VNC Remote Control Server")
        server.run.assert_not_called()

    def test_sdk_loader_uses_exact_v2_module_and_symbol(self) -> None:
        """The reviewed v2 SDK path is explicit rather than compatibility-probed."""
        module = SimpleNamespace(MCPServer=_fake_server_factory)
        with mock.patch.object(mcp_server, "import_module", return_value=module) as loader:
            server = mcp_server.create_mcp_server()
        loader.assert_called_once_with("mcp.server.mcpserver")
        self.assertEqual(server.name, "VNC Remote Control Server")

    def test_missing_optional_dependency_fails_explicitly(self) -> None:
        """Requesting MCP without the extra gives an actionable hard failure."""
        with mock.patch.object(mcp_server, "import_module", side_effect=ImportError("missing")):
            with self.assertRaises(mcp_server.McpDependencyError) as context:
                mcp_server.create_mcp_server()
        message = str(context.exception)
        self.assertIn("mcp==2.1.1", message)
        self.assertIn("vnc-remote-control-client[mcp]", message)

    def test_incompatible_optional_dependency_fails_explicitly(self) -> None:
        """An installed but incompatible SDK never falls back to a fake server."""
        incompatible = SimpleNamespace()
        with mock.patch.object(mcp_server, "import_module", return_value=incompatible):
            with self.assertRaises(mcp_server.McpDependencyError) as context:
                mcp_server.create_mcp_server()
        self.assertIn("expected MCPServer API", str(context.exception))

    def test_main_reports_missing_dependency_on_stderr_and_exits_nonzero(self) -> None:
        """The executable never converts a missing SDK into apparent success."""
        stderr = io.StringIO()
        config = SimpleNamespace(transport="stdio")
        with (
            mock.patch.object(McpConfig, "load", return_value=config),
            mock.patch.object(
                mcp_server,
                "create_mcp_server",
                side_effect=mcp_server.McpDependencyError("missing MCP SDK"),
            ),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as context,
        ):
            mcp_server.main()
        self.assertEqual(context.exception.code, 2)
        self.assertIn("missing MCP SDK", stderr.getvalue())

    def test_main_reports_invalid_config_before_server_construction(self) -> None:
        """Invalid configuration fails closed before any MCP transport can start."""
        stderr = io.StringIO()
        with (
            mock.patch.object(
                McpConfig,
                "load",
                side_effect=McpConfigError("invalid MCP config"),
            ),
            mock.patch.object(mcp_server, "create_mcp_server") as create_server,
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as context,
        ):
            mcp_server.main()
        self.assertEqual(context.exception.code, 2)
        self.assertIn("invalid MCP config", stderr.getvalue())
        create_server.assert_not_called()

    def test_main_rejects_http_transport_until_mcp_009(self) -> None:
        """HTTP configuration cannot accidentally create an unreviewed listener."""
        stderr = io.StringIO()
        config = SimpleNamespace(transport="streamable-http")
        with (
            mock.patch.object(McpConfig, "load", return_value=config),
            mock.patch.object(mcp_server, "create_mcp_server") as create_server,
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as context,
        ):
            mcp_server.main()
        self.assertEqual(context.exception.code, 2)
        self.assertIn("not implemented until MCP-009", stderr.getvalue())
        create_server.assert_not_called()

    def test_main_runs_stdio_once(self) -> None:
        """Validated stdio startup has one explicit non-network transport."""
        server = mock.Mock()
        config = SimpleNamespace(transport="stdio")
        with (
            mock.patch.object(McpConfig, "load", return_value=config),
            mock.patch.object(mcp_server, "create_mcp_server", return_value=server),
        ):
            mcp_server.main()
        server.run.assert_called_once_with(transport="stdio")


if __name__ == "__main__":
    unittest.main()
