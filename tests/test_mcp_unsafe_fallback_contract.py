"""Static regression contract for the MCP unsafe-fallback/silent-failure audit."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_SOURCE_DIR = ROOT / "python" / "src" / "vnc_remote_control"


class McpUnsafeFallbackContractTests(unittest.TestCase):
    """Keep MCP-013 fail-closed conclusions enforceable in permanent CI."""

    @staticmethod
    def _sources() -> dict[Path, str]:
        sources = {
            path: path.read_text(encoding="utf-8")
            for path in sorted(MCP_SOURCE_DIR.glob("mcp_*.py"))
        }
        if not sources:
            raise AssertionError("MCP production source inventory is empty")
        return sources

    def test_no_broad_exception_or_pass_fallbacks(self) -> None:
        """Production MCP code has no bare/Exception catches or pass fallbacks."""
        broad_handlers: list[str] = []
        pass_nodes: list[str] = []
        for path, source in self._sources().items():
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    caught = node.type
                    if caught is None:
                        broad_handlers.append(f"{path.name}:{node.lineno}:bare")
                    elif isinstance(caught, ast.Name) and caught.id in {
                        "Exception",
                        "BaseException",
                    }:
                        broad_handlers.append(
                            f"{path.name}:{node.lineno}:{caught.id}"
                        )
                if isinstance(node, ast.Pass):
                    pass_nodes.append(f"{path.name}:{node.lineno}")
        self.assertEqual(broad_handlers, [])
        self.assertEqual(pass_nodes, [])

    def test_mapping_get_calls_are_exactly_the_reviewed_fail_closed_uses(self) -> None:
        """Any new Mapping.get use requires explicit MCP-013 classification."""
        observed: list[str] = []
        for path, source in self._sources().items():
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                ):
                    observed.append(ast.unparse(node))
        self.assertEqual(
            sorted(observed),
            sorted(
                [
                    "environment.get(name)",
                    "registration.get('annotations')",
                    "registration.get('name')",
                ]
            ),
        )

    def test_no_raw_token_ingress_or_transport_security_downgrade(self) -> None:
        """MCP config remains file-secret-only and keeps SDK transport security."""
        sources = self._sources()
        combined = "\n".join(sources.values())
        self.assertIsNone(
            re.search(r"VRC_MCP_CONTROLLER_TOKEN(?!_FILE)", combined)
        )
        server_source = next(
            source for path, source in sources.items() if path.name == "mcp_server.py"
        )
        self.assertIsNone(re.search(r"\btransport_security\s*=", server_source))
        self.assertNotIn('transport="sse"', server_source)
        self.assertNotIn("transport='sse'", server_source)

    def test_cancellation_paths_have_explicit_terminal_observation(self) -> None:
        """Admitted cancellation cannot abandon worker failures or imply replay safety."""
        sources = self._sources()
        execution = next(
            source for path, source in sources.items() if path.name == "mcp_execution.py"
        )
        outcomes = next(
            source for path, source in sources.items() if path.name == "mcp_outcomes.py"
        )
        self.assertIn("except asyncio.CancelledError", execution)
        self.assertIn("add_done_callback(self._observe_abandoned_future)", execution)
        self.assertIn("future.exception()", execution)
        self.assertIn("except asyncio.CancelledError", outcomes)
        self.assertIn('"kind": "mutation_outcome_unknown"', outcomes)
        self.assertIn('"retry_safe": False', outcomes)

    def test_mutation_path_has_no_retry_backoff_or_sleep_api(self) -> None:
        """Mutation handling exposes no adapter retry/backoff timing mechanism."""
        reviewed = {
            "mcp_execution.py",
            "mcp_mutation_tools.py",
            "mcp_outcomes.py",
        }
        forbidden_calls: list[str] = []
        for path, source in self._sources().items():
            if path.name not in reviewed:
                continue
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    continue
                if name in {"retry", "backoff", "sleep"}:
                    forbidden_calls.append(f"{path.name}:{node.lineno}:{name}")
        self.assertEqual(forbidden_calls, [])


if __name__ == "__main__":
    unittest.main()
