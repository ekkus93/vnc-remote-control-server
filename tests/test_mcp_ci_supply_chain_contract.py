"""MCP-012 contracts for permanent CI and Python MCP supply-chain review."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = ROOT / ".github" / "workflows" / "release-gates.yml"
CONSTRAINTS = ROOT / "security" / "python-mcp-runtime-constraints.txt"
POLICY = ROOT / "security" / "python-mcp-runtime-policy.json"
VERIFIER = ROOT / "scripts" / "verify_python_mcp_runtime.py"
TRANSPORT_TEST = ROOT / "tests" / "test_mcp_transport_acceptance.py"


def _load_constraints() -> dict[str, str]:
    """Return the exact normalized runtime constraints used by permanent CI."""
    result: dict[str, str] = {}
    for raw_line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z0-9][a-z0-9-]*)==([^\s;]+)", line)
        if match is None:
            raise AssertionError(f"non-exact MCP runtime constraint: {line}")
        name, version = match.groups()
        if name in result:
            raise AssertionError(f"duplicate MCP runtime constraint: {name}")
        result[name] = version
    return result


def _load_policy() -> dict[str, Any]:
    """Return the reviewed MCP runtime policy object."""
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("MCP runtime policy must be a JSON object")
    return value


class McpCiSupplyChainContractTests(unittest.TestCase):
    """Keep MCP-012's fail-closed CI and dependency-review boundaries durable."""

    def test_constraints_exactly_match_reviewed_policy_versions(self) -> None:
        """The install constraints and reviewed package/version inventory may not drift."""
        constraints = _load_constraints()
        policy = _load_policy()
        packages = policy["packages"]
        self.assertIsInstance(packages, dict)
        assert isinstance(packages, dict)
        expected = {
            name: entry["version"]
            for name, entry in packages.items()
            if isinstance(name, str) and isinstance(entry, dict)
        }
        self.assertEqual(constraints, expected)
        self.assertEqual(policy["direct_requirement"], "mcp==2.1.1")
        self.assertEqual(
            policy["target"],
            {
                "implementation": "CPython",
                "python_minor": "3.12",
                "platform": "linux",
            },
        )
        self.assertEqual(len(constraints), 28)
        cffi = packages["cffi"]
        self.assertIsInstance(cffi, dict)
        assert isinstance(cffi, dict)
        self.assertEqual(cffi["license"], "MIT-0")
        self.assertEqual(cffi["accepted_license_signals"], ["MIT-0"])
        self.assertIn("MIT-0", policy["reviewed_license_families"])

    def test_regular_ci_proves_core_without_mcp_and_uses_reviewed_closure(self) -> None:
        """Regular CI must separately prove core-only and reviewed MCP installs."""
        text = CI.read_text(encoding="utf-8")
        required = (
            "core_python:",
            "name: Core Python client without MCP",
            "python -m venv .venv-core",
            ".venv-core/bin/python -m pip install -e ./python",
            'importlib.util.find_spec("mcp") is not None',
            "Run core Python client contract tests without MCP installed",
            "security/python-mcp-runtime-constraints.txt",
            "python -m pip check",
            "python -m unittest discover -s tests -p 'test_*.py' -v",
            "Run MCP production controller/TigerVNC E2E",
            "tests/mcp-e2e/run.sh",
            "ruff check .",
            "pylint --rcfile=.pylintrc python/src/vnc_remote_control tests scripts",
            "mypy --config-file mypy.ini python/src/vnc_remote_control tests scripts",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertGreaterEqual(
            text.count("--constraint security/python-mcp-runtime-constraints.txt"),
            2,
        )
        self.assertNotIn("continue-on-error: true", text)

    def test_stdio_and_http_acceptance_remain_in_discovered_suite(self) -> None:
        """The discovered test suite must retain official-client stdio and HTTP smoke."""
        text = TRANSPORT_TEST.read_text(encoding="utf-8")
        required = (
            "from mcp.client.session import ClientSession",
            "from mcp.client.stdio import StdioServerParameters, stdio_client",
            "streamable_http_client",
            "test_stdio_default_catalog_and_read_invocation_use_official_client",
            "test_stdio_mutation_opt_in_invokes_exactly_one_mutation",
            "test_http_catalog_matches_stdio_and_read_invocation_works",
            "test_http_mutation_opt_in_invokes_exactly_one_mutation",
            "test_http_sdk_rejects_bad_host_and_origin",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_release_gates_inventory_python_mcp_runtime_fail_closed(self) -> None:
        """Release Gates must inventory exact MCP deps/licenses and preserve other gates."""
        text = RELEASE.read_text(encoding="utf-8")
        required = (
            "python_mcp_supply_chain:",
            "name: Release Python MCP dependency and license gate",
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
            'python-version: "3.12"',
            "python -m venv .venv-mcp-audit",
            "--constraint security/python-mcp-runtime-constraints.txt",
            "--report artifacts/python-mcp-supply-chain/pip-install-report.json",
            "scripts/verify_python_mcp_runtime.py",
            "runtime-inventory.json",
            "python-mcp-supply-chain-${{ github.run_id }}",
            "tests/mcp-e2e/run.sh",
            "cargo deny check advisories bans licenses sources",
            "gitleaks git",
            "trivy image",
            "--format cyclonedx",
            "-Zsanitizer=address",
            "-Zsanitizer=thread",
            "miri test",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertNotIn("continue-on-error: true", text)
        self.assertNotIn("--ignore-unfixed", text)

    def test_runtime_verifier_has_no_generic_exception_or_silent_exclusion(self) -> None:
        """The verifier must fail closed and name its only two non-runtime exclusions."""
        text = VERIFIER.read_text(encoding="utf-8")
        self.assertIn('_LOCAL_PROJECT = "vnc-remote-control-client"', text)
        self.assertIn('_BOOTSTRAP_DISTRIBUTION = "pip"', text)
        self.assertIn("installed MCP runtime closure drifted", text)
        self.assertIn("unreviewed license metadata", text)
        self.assertIn("runtime verifier requires Python 3.12 exactly", text)
        self.assertIn("core Python package must have zero hard dependencies", text)
        self.assertNotIn("except Exception", text)
        self.assertNotIn("pass\n", text)


if __name__ == "__main__":
    unittest.main()
