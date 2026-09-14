"""Regression tests for MCP fail-closed configuration and classification boundaries."""

from __future__ import annotations

import os
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


class LocalMutationValidationError(ValueError):
    """Represent one application-specific pre-controller validation failure."""


class McpFailClosedBoundaryTests(unittest.TestCase):
    """Keep security-sensitive adapter dispatch/configuration boundaries fail closed."""

    def test_unknown_mcp_prefixed_environment_names_fail_closed(self) -> None:
        """MCP typos and raw-token-shaped aliases cannot be silently ignored."""
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "controller-token"
            token_file.write_text("controller-secret\n", encoding="utf-8")
            if os.name == "posix":
                token_file.chmod(0o600)

            baseline = {
                "VRC_MCP_CONTROLLER_TOKEN_FILE": str(token_file),
                "VRC_MCP_TRANSPORT": "stdio",
                "HOME": "/tmp/mcp-boundary-test",
            }
            self.assertTrue(McpConfig.load(baseline).token_set)

            for name in ("VRC_MCP_CONTROLLER_TOKEN", "VRC_MCP_TRANPSORT"):
                environment = dict(baseline)
                environment[name] = "SENSITIVE-IGNORED-VALUE"
                with self.subTest(name=name):
                    with self.assertRaisesRegex(
                        McpConfigError,
                        r"unsupported VRC_MCP_\* environment variable",
                    ) as context:
                        McpConfig.load(environment)
                    self.assertNotIn(
                        "SENSITIVE-IGNORED-VALUE",
                        str(context.exception),
                    )

    def test_transport_runner_revalidates_injected_configuration(self) -> None:
        """Bypassed config objects cannot select or parameterize an unsafe listener."""
        cases = (
            ("legacy-sse", "127.0.0.1", 8765),
            ("streamable-http", "0.0.0.0", 8765),
            ("streamable-http", "127.0.0.1", 0),
            ("streamable-http", "127.0.0.1", True),
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
                    mcp_server._run_configured_transport(  # pylint: disable=protected-access
                        server,
                        config,
                    )
                server.run.assert_not_called()

    def test_dynamic_validation_errors_reject_broad_builtin_classes(self) -> None:
        """Broad built-ins cannot become handled preflight validation failures."""
        for error_type in (Exception, ValueError, RuntimeError):
            with self.subTest(error_type=error_type.__name__):
                with self.assertRaises(McpOutcomeRegistrationError):
                    McpOutcomeToolRegistrar(
                        RecordingToolRegistrar({}),
                        call_tool_result_factory=lambda **kwargs: kwargs,
                        text_content_factory=lambda **kwargs: kwargs,
                        mutation_validation_errors=(error_type,),
                    )

    def test_dynamic_validation_errors_accept_specific_application_class(self) -> None:
        """The intended application-specific validation class remains supported."""
        registrar = McpOutcomeToolRegistrar(
            RecordingToolRegistrar({}),
            call_tool_result_factory=lambda **kwargs: kwargs,
            text_content_factory=lambda **kwargs: kwargs,
            mutation_validation_errors=(LocalMutationValidationError,),
        )
        self.assertIsInstance(registrar, McpOutcomeToolRegistrar)


if __name__ == "__main__":
    unittest.main()
