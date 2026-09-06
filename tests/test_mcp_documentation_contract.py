"""Contract tests tying the living MCP guide to current source and packaging."""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from mcp_test_support import MUTATION_TOOL_NAMES, READ_ONLY_TOOL_NAMES
from vnc_remote_control import mcp_config

ROOT = Path(__file__).resolve().parents[1]
MCP_GUIDE_PATH = ROOT / "docs" / "MCP_SERVER.md"
MCP_CONFIG_SOURCE_PATH = (
    ROOT / "python" / "src" / "vnc_remote_control" / "mcp_config.py"
)
PYPROJECT_PATH = ROOT / "python" / "pyproject.toml"

_CONFIG_ENV_PATTERN = re.compile(r'"(VRC_MCP_[A-Z0-9_]+)"')
_DOCUMENTED_ENV_PATTERN = re.compile(r"`(VRC_MCP_[A-Z0-9_]+)`")


class McpDocumentationContractTests(unittest.TestCase):
    """Prevent the runnable MCP surface from drifting away from living docs."""

    def test_guide_documents_every_configuration_variable_from_source(self) -> None:
        """Every VRC_MCP_* variable is documented with current defaults and bounds."""
        guide = MCP_GUIDE_PATH.read_text(encoding="utf-8")
        source = MCP_CONFIG_SOURCE_PATH.read_text(encoding="utf-8")
        source_names = set(_CONFIG_ENV_PATTERN.findall(source))
        documented_names = set(_DOCUMENTED_ENV_PATTERN.findall(guide))
        self.assertEqual(documented_names, source_names)

        expected_default_rows = (
            ("VRC_MCP_CONTROLLER_URL", mcp_config.DEFAULT_CONTROLLER_URL),
            (
                "VRC_MCP_CONTROLLER_TIMEOUT_SECONDS",
                str(mcp_config.DEFAULT_CONTROLLER_TIMEOUT_SECONDS),
            ),
            (
                "VRC_MCP_MAX_CONCURRENT_CALLS",
                str(mcp_config.DEFAULT_MAX_CONCURRENT_CALLS),
            ),
            ("VRC_MCP_TRANSPORT", mcp_config.DEFAULT_TRANSPORT),
            ("VRC_MCP_HTTP_HOST", mcp_config.DEFAULT_HTTP_HOST),
            ("VRC_MCP_HTTP_PORT", str(mcp_config.DEFAULT_HTTP_PORT)),
        )
        for name, value in expected_default_rows:
            self.assertIn(f"| `{name}` | `{value}` |", guide)

        self.assertIn("| `VRC_MCP_CONTROLLER_TOKEN_FILE` | required |", guide)
        self.assertIn("| `VRC_MCP_ALLOW_MUTATIONS` | `false` |", guide)
        self.assertIn(
            f"`{mcp_config.MIN_CONTROLLER_TIMEOUT_SECONDS}` through "
            f"`{mcp_config.MAX_CONTROLLER_TIMEOUT_SECONDS}`",
            guide,
        )
        self.assertIn(
            f"integer `{mcp_config.MIN_MAX_CONCURRENT_CALLS}` through "
            f"`{mcp_config.MAX_MAX_CONCURRENT_CALLS}`",
            guide,
        )
        self.assertIn(
            f"integer `{mcp_config.MIN_HTTP_PORT}` through "
            f"`{mcp_config.MAX_HTTP_PORT}`",
            guide,
        )
        self.assertIn(f"{mcp_config.MAX_SECRET_BYTES} bytes", guide)
        for host in mcp_config.SDK_PROTECTED_HTTP_LOOPBACK_HOSTS:
            self.assertIn(f"`{host}`", guide)

    def test_install_and_entry_point_match_python_package_metadata(self) -> None:
        """The guide install and executable claims match pyproject.toml exactly."""
        guide = MCP_GUIDE_PATH.read_text(encoding="utf-8")
        with PYPROJECT_PATH.open("rb") as handle:
            project = tomllib.load(handle)["project"]

        package_contract = {
            "core_runtime_dependencies": project["dependencies"],
            "mcp_extra_requirements": project["optional-dependencies"]["mcp"],
            "mcp_console_target": project["scripts"]["vnc-remote-control-mcp"],
        }
        self.assertEqual(
            package_contract,
            {
                "core_runtime_dependencies": [],
                "mcp_extra_requirements": ["mcp==2.1.1"],
                "mcp_console_target": "vnc_remote_control.mcp_server:main",
            },
        )
        for required in (
            "zero third-party runtime dependencies",
            package_contract["mcp_extra_requirements"][0],
            "python -m pip install './python[mcp]'",
            "vnc-remote-control-mcp",
        ):
            self.assertIn(required, guide)

    def test_guide_tracks_catalog_and_fail_closed_outcome_semantics(self) -> None:
        """The documented catalog and ambiguity recovery match the implementation."""
        guide = MCP_GUIDE_PATH.read_text(encoding="utf-8")
        for tool_name in READ_ONLY_TOOL_NAMES | MUTATION_TOOL_NAMES:
            self.assertIn(f"`{tool_name}`", guide)

        for required in (
            'kind="command_outcome_unknown"',
            'kind="mutation_outcome_unknown"',
            'outcome="unknown"',
            "retry_safe=false",
            "command_id=null",
            "vnc_get_command_status(command_id)",
            "never fabricates a command ID",
            "Do **not** automatically retry or replay the original mutation",
            "There is no adapter retry loop",
        ):
            self.assertIn(required, guide)

    def test_guide_preserves_transport_and_remote_security_boundaries(self) -> None:
        """HTTP remains loopback-only and retains the SDK security middleware."""
        guide = MCP_GUIDE_PATH.read_text(encoding="utf-8")
        for required in (
            "http://127.0.0.1:8765/mcp",
            "stateless_http=True",
            "DNS-rebinding",
            "Host",
            "Origin",
            "legacy SSE",
            "SSH local-forward",
            "0.0.0.0",
            "does **not** authenticate MCP clients itself",
            "loopback addresses",
        ):
            self.assertIn(required, guide)

    def test_sensitive_data_and_python_zeroization_limit_are_explicit(self) -> None:
        """Living security docs do not overstate Python memory guarantees."""
        guide = MCP_GUIDE_PATH.read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        for required in (
            "typed keyboard text",
            "clipboard contents",
            "screenshot pixels",
            "controller bearer-token bytes",
            "Python `str`",
            "does not guarantee zeroization",
        ):
            self.assertIn(required, guide)
        for required in (
            "MCP Streamable HTTP",
            "Python `str`",
            "does not guarantee zeroization",
            "VRC_MCP_CONTROLLER_TOKEN_FILE",
        ):
            self.assertIn(required, security)

    def test_all_required_living_documents_link_to_the_mcp_guide(self) -> None:
        """Every MCP-010 living-document target points at the current MCP guide."""
        required_links = {
            ROOT / "README.md": "docs/MCP_SERVER.md",
            ROOT / "python" / "README.md": "../docs/MCP_SERVER.md",
            ROOT / "docs" / "OPERATOR_GUIDE.md": "MCP_SERVER.md",
            ROOT / "deploy" / "README.md": "../docs/MCP_SERVER.md",
            ROOT / "SECURITY.md": "docs/MCP_SERVER.md",
            ROOT / "docs" / "README.md": "MCP_SERVER.md",
            ROOT / "CONTRIBUTING.md": "docs/MCP_SERVER.md",
            ROOT / "CLAUDE.md": "docs/MCP_SERVER.md",
        }
        for path, target in required_links.items():
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(target, path.read_text(encoding="utf-8"))

    def test_full_python_validation_command_installs_the_mcp_extra(self) -> None:
        """Contributor guidance installs the dependency needed by the full suite."""
        for path in (ROOT / "CONTRIBUTING.md", ROOT / "CLAUDE.md"):
            document = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("pip install -e './python[mcp]'", document)
                self.assertIn(
                    "python3 -m unittest discover -s tests -p 'test_*.py' -v",
                    document,
                )


if __name__ == "__main__":
    unittest.main()
