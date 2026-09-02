"""Contract tests for the optional MCP package scaffold and runtime wiring."""

from __future__ import annotations

import base64
import builtins
import importlib
import io
import tomllib
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from vnc_remote_control import mcp_server
from vnc_remote_control.client import VncRemoteControlClient
from vnc_remote_control.mcp_config import McpConfig, McpConfigError
from vnc_remote_control.mcp_execution import BoundedControllerExecutor

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
_MUTATION_TOOL_NAMES = {
    "vnc_move_pointer",
    "vnc_set_pointer_button",
    "vnc_click_pointer",
    "vnc_double_click_pointer",
    "vnc_scroll_pointer",
    "vnc_set_keyboard_key",
    "vnc_send_keyboard_chord",
    "vnc_type_keyboard_text",
    "vnc_set_clipboard",
    "vnc_request_reconnect",
}


def _fake_server_factory(name: str, **kwargs: Any) -> mock.Mock:
    """Return an inspectable fake server accepting the reviewed constructor kwargs."""
    server = mock.Mock()
    server.name = name
    server.lifespan = kwargs.get("lifespan")
    return server


def _fake_annotations_factory(**kwargs: Any) -> SimpleNamespace:
    """Return inspectable annotation data without importing MCP."""
    return SimpleNamespace(**kwargs)


def _fake_field_factory(**kwargs: Any) -> SimpleNamespace:
    """Return inspectable schema metadata without importing Pydantic."""
    return SimpleNamespace(**kwargs)


def _config(*, transport: str = "stdio", allow_mutations: bool = False) -> McpConfig:
    """Return a typed stand-in for validated configuration."""
    client = mock.create_autospec(VncRemoteControlClient, instance=True)
    value = SimpleNamespace(
        transport=transport,
        allow_mutations=allow_mutations,
        max_concurrent_calls=2,
        build_client=mock.Mock(return_value=client),
    )
    return cast(McpConfig, value)


def _components() -> mcp_server.McpSdkComponents:
    """Return dependency-free fake SDK components."""
    return mcp_server.McpSdkComponents(
        server_factory=_fake_server_factory,
        annotations_factory=_fake_annotations_factory,
        field_factory=_fake_field_factory,
        image_factory=mock.Mock,
        call_tool_result_factory=SimpleNamespace,
    )


def _executor_mock() -> Any:
    """Return an autospecced executor without allocating worker threads."""
    return mock.create_autospec(BoundedControllerExecutor, instance=True)


def _registered_tool_names(server: mock.Mock) -> set[str]:
    """Return tool names passed to the fake server's registrar."""
    return {call.kwargs["name"] for call in server.tool.call_args_list}


class McpServerScaffoldTests(unittest.TestCase):
    """Verify MCP remains optional and server construction is deterministic."""

    def test_package_metadata_keeps_mcp_optional_and_pinned(self) -> None:
        """Core installs stay dependency-free while the MCP extra is exact-pinned."""
        metadata = tomllib.loads(
            (PYTHON_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
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
            if name == "mcp" or name.startswith("mcp.") or name == "mcp_types":
                raise AssertionError("module import attempted to load optional MCP SDK")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=guarded_import):
            reloaded = importlib.reload(mcp_server)
        self.assertEqual(reloaded.MCP_EXTRA_REQUIREMENT, "mcp==2.1.1")

    def test_create_mcp_server_uses_injected_components_without_starting_transport(
        self,
    ) -> None:
        """Construction registers tools but never starts a transport implicitly."""
        config = _config()
        executor = _executor_mock()
        server = mcp_server.create_mcp_server(
            config=config,
            components=_components(),
            client=config.build_client(),
            executor=executor,
        )
        self.assertEqual(server.name, "VNC Remote Control Server")
        server.run.assert_not_called()
        self.assertIsNotNone(server.lifespan)
        executor.close.assert_not_called()

    def test_construction_failure_closes_executor_before_lifespan_ownership(self) -> None:
        """Tool-registration failure cannot leak adapter-owned worker capacity."""
        executor = _executor_mock()

        def fail_annotations(**_kwargs: Any) -> None:
            """Represent an SDK annotation-construction failure."""
            raise RuntimeError("annotation setup failed")

        components = mcp_server.McpSdkComponents(
            server_factory=_fake_server_factory,
            annotations_factory=fail_annotations,
            field_factory=_fake_field_factory,
            image_factory=mock.Mock,
            call_tool_result_factory=SimpleNamespace,
        )
        with self.assertRaisesRegex(RuntimeError, "annotation setup failed"):
            mcp_server.create_mcp_server(
                config=_config(),
                components=components,
                client=mock.create_autospec(VncRemoteControlClient, instance=True),
                executor=executor,
            )
        executor.close.assert_called_once_with()

    def test_sdk_loader_uses_exact_v2_modules_and_symbols(self) -> None:
        """The reviewed SDK paths are explicit rather than compatibility-probed."""
        image_factory = mock.Mock()
        image_factory.to_image_content = mock.Mock()
        modules = [
            SimpleNamespace(MCPServer=_fake_server_factory),
            SimpleNamespace(Image=image_factory),
            SimpleNamespace(
                ToolAnnotations=_fake_annotations_factory,
                CallToolResult=SimpleNamespace,
            ),
            SimpleNamespace(Field=_fake_field_factory),
        ]
        with mock.patch.object(mcp_server, "import_module", side_effect=modules) as loader:
            components = mcp_server.load_mcp_sdk_components()
        self.assertEqual(
            [call.args[0] for call in loader.call_args_list],
            [
                "mcp.server.mcpserver",
                "mcp.server.mcpserver.utilities.types",
                "mcp_types",
                "pydantic",
            ],
        )
        self.assertIs(components.server_factory, _fake_server_factory)
        self.assertIs(components.image_factory, image_factory)
        self.assertIs(components.call_tool_result_factory, SimpleNamespace)

    def test_exact_sdk_image_helper_produces_native_content(self) -> None:
        """The pinned SDK emits ImageContent and preserves structured metadata."""
        components = mcp_server.load_mcp_sdk_components()
        payload = b"\x89PNG\r\n\x1a\nMCP-NATIVE-IMAGE-CONTRACT"
        image = components.image_factory(data=payload, format="png")
        content = image.to_image_content()
        self.assertEqual(content.type, "image")
        self.assertEqual(content.mime_type, "image/png")
        self.assertEqual(base64.b64decode(content.data, validate=True), payload)

        metadata = {"request_id": "sdk-contract"}
        result = components.call_tool_result_factory(
            content=[content],
            structured_content=metadata,
        )
        self.assertEqual(result.content, [content])
        self.assertEqual(result.structured_content, metadata)

    def test_missing_optional_dependency_fails_explicitly(self) -> None:
        """Requesting MCP without the extra gives an actionable hard failure."""
        with mock.patch.object(
            mcp_server, "import_module", side_effect=ImportError("missing")
        ):
            with self.assertRaises(mcp_server.McpDependencyError) as context:
                mcp_server.load_mcp_sdk_components()
        message = str(context.exception)
        self.assertIn("mcp==2.1.1", message)
        self.assertIn("vnc-remote-control-client[mcp]", message)

    def test_incompatible_optional_dependency_fails_explicitly(self) -> None:
        """An installed but incompatible SDK never falls back to another API."""
        image_factory = mock.Mock()
        image_factory.to_image_content = mock.Mock()
        modules = [
            SimpleNamespace(MCPServer=_fake_server_factory),
            SimpleNamespace(Image=image_factory),
            SimpleNamespace(ToolAnnotations=_fake_annotations_factory),
            SimpleNamespace(Field=_fake_field_factory),
        ]
        with mock.patch.object(mcp_server, "import_module", side_effect=modules):
            with self.assertRaises(mcp_server.McpDependencyError) as context:
                mcp_server.load_mcp_sdk_components()
        self.assertIn(
            "MCPServer/Image/ToolAnnotations/CallToolResult/Field",
            str(context.exception),
        )

    def test_image_helper_without_native_conversion_fails_explicitly(self) -> None:
        """A callable lookalike Image symbol cannot silently downgrade to text output."""
        modules = [
            SimpleNamespace(MCPServer=_fake_server_factory),
            SimpleNamespace(Image=int),
            SimpleNamespace(
                ToolAnnotations=_fake_annotations_factory,
                CallToolResult=SimpleNamespace,
            ),
            SimpleNamespace(Field=_fake_field_factory),
        ]
        with mock.patch.object(mcp_server, "import_module", side_effect=modules):
            with self.assertRaises(mcp_server.McpDependencyError):
                mcp_server.load_mcp_sdk_components()

    def test_mutation_catalog_is_absent_without_explicit_opt_in(self) -> None:
        """Default construction exposes no mutation capability."""
        executor = _executor_mock()
        server = mcp_server.create_mcp_server(
            config=_config(allow_mutations=False),
            components=_components(),
            client=mock.create_autospec(VncRemoteControlClient, instance=True),
            executor=executor,
        )
        self.assertTrue(_registered_tool_names(server).isdisjoint(_MUTATION_TOOL_NAMES))
        executor.close.assert_not_called()

    def test_mutation_opt_in_registers_exact_reviewed_catalog(self) -> None:
        """Explicit mutation opt-in registers all and only reviewed mutation tools."""
        executor = _executor_mock()
        server = mcp_server.create_mcp_server(
            config=_config(allow_mutations=True),
            components=_components(),
            client=mock.create_autospec(VncRemoteControlClient, instance=True),
            executor=executor,
        )
        self.assertEqual(
            _registered_tool_names(server) & _MUTATION_TOOL_NAMES,
            _MUTATION_TOOL_NAMES,
        )
        executor.close.assert_not_called()

    def test_schema_field_factory_receives_strict_positive_bound(self) -> None:
        """Command IDs request integer-only minimum-one SDK schema metadata."""
        field_factory = mock.Mock(return_value=object())
        components = mcp_server.McpSdkComponents(
            server_factory=_fake_server_factory,
            annotations_factory=_fake_annotations_factory,
            field_factory=field_factory,
            image_factory=mock.Mock,
            call_tool_result_factory=SimpleNamespace,
        )
        executor = _executor_mock()
        mcp_server.create_mcp_server(
            config=_config(),
            components=components,
            client=mock.create_autospec(VncRemoteControlClient, instance=True),
            executor=executor,
        )
        field_factory.assert_called_once_with(
            ge=1,
            strict=True,
            description="Positive process-local controller command identifier.",
        )
        executor.close.assert_not_called()

    def test_main_reports_missing_dependency_on_stderr_and_exits_nonzero(self) -> None:
        """The executable never converts a missing SDK into apparent success."""
        stderr = io.StringIO()
        config = _config()
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
        config = _config(transport="streamable-http")
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
        config = _config()
        with (
            mock.patch.object(McpConfig, "load", return_value=config),
            mock.patch.object(
                mcp_server, "create_mcp_server", return_value=server
            ) as create,
        ):
            mcp_server.main()
        create.assert_called_once_with(config=config)
        server.run.assert_called_once_with(transport="stdio")


class McpServerLifespanTests(unittest.IsolatedAsyncioTestCase):
    """Verify successful construction transfers executor cleanup to the lifespan."""

    async def test_lifespan_closes_executor_once(self) -> None:
        """Normal lifespan exit awaits adapter-owned executor shutdown."""
        executor = _executor_mock()
        server = mcp_server.create_mcp_server(
            config=_config(),
            components=_components(),
            client=mock.create_autospec(VncRemoteControlClient, instance=True),
            executor=executor,
        )
        async with server.lifespan(server):
            executor.aclose.assert_not_awaited()
        executor.aclose.assert_awaited_once_with()
        executor.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
