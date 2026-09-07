"""Static regression contracts for the MCP-013 unsafe-fallback audit."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest import mock

from mcp_test_support import RecordingToolRegistrar
from vnc_remote_control import mcp_server
from vnc_remote_control.mcp_config import McpConfig, McpConfigError
from vnc_remote_control.mcp_outcomes import (
    McpOutcomeRegistrationError,
    McpOutcomeToolRegistrar,
)

ROOT = Path(__file__).resolve().parents[1]
MCP_SOURCE_ROOT = ROOT / "python" / "src" / "vnc_remote_control"
MCP_SOURCE_FILES = tuple(sorted(MCP_SOURCE_ROOT.glob("mcp_*.py")))
MUTATION_CALL_HELPERS = frozenset(
    {
        "_move_pointer",
        "_set_pointer_button",
        "_click_pointer",
        "_double_click_pointer",
        "_scroll_pointer",
        "_set_keyboard_key",
        "_send_keyboard_chord",
        "_type_keyboard_text",
        "_set_clipboard",
        "_request_reconnect",
    }
)
_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "critical", "exception"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(call: ast.Call) -> str:
    return ast.unparse(call.func)


class McpSafetyAuditContractTests(unittest.TestCase):
    """Keep audited MCP failure semantics from regressing silently."""

    def test_mcp_source_has_no_bare_or_literal_broad_exception_handlers_or_pass(self) -> None:
        """Broad catch/pass constructs cannot be introduced into audited MCP modules."""
        for path in MCP_SOURCE_FILES:
            tree = _parse(path)
            for node in ast.walk(tree):
                with self.subTest(path=path.name, line=getattr(node, "lineno", None)):
                    self.assertNotIsInstance(node, ast.Pass)
                    if isinstance(node, ast.ExceptHandler):
                        self.assertIsNotNone(node.type)
                        if isinstance(node.type, ast.Name):
                            self.assertNotIn(node.type.id, {"Exception", "BaseException"})

    def test_mutation_helpers_have_one_executor_call_and_no_retry_loop(self) -> None:
        """Each mutation helper crosses the controller boundary exactly once without loops."""
        tree = _parse(MCP_SOURCE_ROOT / "mcp_mutation_tools.py")
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue(MUTATION_CALL_HELPERS <= functions.keys())
        for name in sorted(MUTATION_CALL_HELPERS):
            function = functions[name]
            calls = [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and _call_name(node) == "runtime.executor.call"
            ]
            loops = [
                node
                for node in ast.walk(function)
                if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
            ]
            with self.subTest(helper=name):
                self.assertEqual(len(calls), 1)
                self.assertEqual(loops, [])

    def test_mcp_logging_uses_fixed_messages_and_never_logs_exception_objects(self) -> None:
        """MCP logs may identify static tool names but never interpolate payload/error objects."""
        for path in MCP_SOURCE_FILES:
            tree = _parse(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in _LOG_METHODS:
                    continue
                if not (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "_LOGGER"
                ):
                    continue
                with self.subTest(path=path.name, line=node.lineno):
                    self.assertGreaterEqual(len(node.args), 1)
                    self.assertIsInstance(node.args[0], ast.Constant)
                    self.assertIsInstance(node.args[0].value, str)
                    for argument in node.args[1:]:
                        self.assertIsInstance(argument, ast.Name)
                        self.assertEqual(argument.id, "tool_name")
                    self.assertFalse(node.keywords)

    def test_streamable_http_never_overrides_sdk_transport_security(self) -> None:
        """The adapter keeps the pinned SDK Host/Origin/DNS-rebinding policy authoritative."""
        path = MCP_SOURCE_ROOT / "mcp_server.py"
        tree = _parse(path)
        streamable_runs: list[ast.Call] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "server.run":
                continue
            transport = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "transport"),
                None,
            )
            if isinstance(transport, ast.Constant) and transport.value == "streamable-http":
                streamable_runs.append(node)
        self.assertEqual(len(streamable_runs), 1)
        keywords = {keyword.arg for keyword in streamable_runs[0].keywords}
        self.assertEqual(keywords, {"transport", "host", "port", "stateless_http"})
        source = path.read_text(encoding="utf-8")
        self.assertIn("validate_mcp_transport_configuration(", source)
        self.assertNotIn("transport_security=", source)

    def test_real_mcp_e2e_keeps_secret_ingress_and_diagnostics_fail_closed(self) -> None:
        """The real E2E harness must not regress to raw-token ingress or traced payloads."""
        path = ROOT / "tests" / "mcp_e2e.py"
        tree = _parse(path)
        constants = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("VRC_MCP_CONTROLLER_TOKEN_FILE", constants)
        self.assertNotIn("VRC_MCP_CONTROLLER_TOKEN", constants)

        forbidden_assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "_FORBIDDEN_LOG_VALUES"
                for target in node.targets
            )
        )
        self.assertIsInstance(forbidden_assignment.value, ast.Tuple)
        forbidden_names = {
            element.id
            for element in forbidden_assignment.value.elts
            if isinstance(element, ast.Name)
        }
        self.assertEqual(
            forbidden_names,
            {"API_TOKEN", "VNC_PASSWORD", "_TYPED_TEXT", "_OUTBOUND_CLIPBOARD"},
        )

        source = path.read_text(encoding="utf-8")
        self.assertIn("_sanitize(text)", source)
        self.assertIn("_audit_runtime_logs(harness, mcp_logs)", source)
        shell = (ROOT / "tests" / "mcp-e2e" / "run.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", shell)
        self.assertNotIn("set -x", shell)
        self.assertNotIn("set -eux", shell)

    def test_mcp_source_contains_no_retry_or_backoff_calls(self) -> None:
        """No MCP module may add an adapter-level retry/backoff operation."""
        forbidden_call_parts = ("retry", "backoff")
        for path in MCP_SOURCE_FILES:
            tree = _parse(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node).lower()
                with self.subTest(path=path.name, line=node.lineno, call=name):
                    self.assertFalse(any(part in name for part in forbidden_call_parts))


class McpFailClosedBehaviorTests(unittest.TestCase):
    """Exercise the concrete silent-failure defects corrected by MCP-013."""

    def _environment(self, token_file: Path, **overrides: str) -> dict[str, str]:
        environment = {
            "VRC_MCP_CONTROLLER_TOKEN_FILE": str(token_file),
            "VRC_MCP_TRANSPORT": "stdio",
        }
        environment.update(overrides)
        return environment

    def test_unknown_mcp_prefixed_environment_names_fail_closed(self) -> None:
        """Raw-token-shaped aliases and MCP typos cannot be silently ignored."""
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "controller-token"
            token_file.write_text("audit-token\n", encoding="utf-8")
            token_file.chmod(0o600)

            baseline = self._environment(token_file, HOME="/tmp/audit-home")
            self.assertTrue(McpConfig.load(baseline).token_set)

            for name in ("VRC_MCP_CONTROLLER_TOKEN", "VRC_MCP_TRANPSORT"):
                environment = dict(baseline)
                environment[name] = "must-not-be-accepted"
                with self.subTest(name=name):
                    with self.assertRaisesRegex(
                        McpConfigError,
                        r"unsupported VRC_MCP_\* environment variable",
                    ) as context:
                        McpConfig.load(environment)
                    self.assertNotIn("must-not-be-accepted", str(context.exception))

    def test_transport_runner_revalidates_injected_configuration(self) -> None:
        """Bypassed/injected config objects cannot fall through to an HTTP listener."""
        cases = (
            ("legacy-sse", "127.0.0.1", 8765),
            ("streamable-http", "0.0.0.0", 8765),
            ("streamable-http", "127.0.0.1", 0),
        )
        for transport, host, port in cases:
            server = mock.Mock()
            config = cast(
                McpConfig,
                SimpleNamespace(
                    transport=transport,
                    http_host=host,
                    http_port=port,
                ),
            )
            with self.subTest(transport=transport, host=host, port=port):
                with self.assertRaises(McpConfigError):
                    mcp_server._run_configured_transport(server, config)
                server.run.assert_not_called()

    def test_dynamic_validation_classification_cannot_widen_to_exception(self) -> None:
        """Registrar configuration cannot turn arbitrary failures into validation errors."""
        with self.assertRaises(McpOutcomeRegistrationError):
            McpOutcomeToolRegistrar(
                RecordingToolRegistrar({}),
                call_tool_result_factory=lambda **kwargs: kwargs,
                text_content_factory=lambda **kwargs: kwargs,
                mutation_validation_errors=(Exception,),
            )


if __name__ == "__main__":
    unittest.main()
