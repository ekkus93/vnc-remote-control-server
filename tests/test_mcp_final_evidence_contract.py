"""Contract tests for final MCP evidence truthfulness.

These tests intentionally do not import the optional MCP SDK. They keep the
closeout evidence from drifting back into provisional pre-merge wording after
post-merge validation has already completed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "VNC_REMOTE_CONTROL_SERVER_MCP_EVIDENCE_2026-09-02.md"
TODO = ROOT / "docs" / "VNC_REMOTE_CONTROL_SERVER_MCP_TODO_2026-09-02.md"

IMPLEMENTATION_SHA = "a31e2f3fdf77085292fe65648d8741613f91cb38"
IMPLEMENTATION_CI = "34658956284"
IMPLEMENTATION_RELEASE_GATES = "34658956281"
DOCUMENTATION_CLOSED_SHA = "3a04e0854468ed036affdf07674e095da7c806a6"
DOCUMENTATION_CLOSED_CI = "34660215099"
DOCUMENTATION_CLOSED_RELEASE_GATES = "34660215186"
STALE_FINAL_PHRASES = (
    "Subject to this documentation-only closeout",
    "must itself remain green",
    "must remain green under the permanent workflows before merge",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class McpFinalEvidenceContractTests(unittest.TestCase):
    """Verify final MCP evidence distinguishes implementation and doc closeout."""

    def test_final_evidence_records_documentation_closed_generation(self) -> None:
        """Evidence records both the runtime generation and PR #44 closeout."""
        evidence = _text(EVIDENCE)
        for expected in (
            IMPLEMENTATION_SHA,
            IMPLEMENTATION_CI,
            IMPLEMENTATION_RELEASE_GATES,
            DOCUMENTATION_CLOSED_SHA,
            DOCUMENTATION_CLOSED_CI,
            DOCUMENTATION_CLOSED_RELEASE_GATES,
        ):
            self.assertIn(expected, evidence)

        self.assertIn("authoritative runtime implementation generation", evidence)
        self.assertIn("documentation-closed generation from PR #44", evidence)

    def test_final_evidence_declaration_is_not_provisional(self) -> None:
        """The final declaration must not use stale pre-merge wording."""
        evidence = _text(EVIDENCE)
        final_section = evidence.split("## 15. Final reconciliation and declaration", 1)[1]
        for phrase in STALE_FINAL_PHRASES:
            self.assertNotIn(phrase, final_section)
        self.assertIn("The MCP implementation phase is complete", final_section)

    def test_mcp_todo_records_documentation_closed_generation(self) -> None:
        """The MCP TODO records final PR #44 post-merge validation."""
        todo = _text(TODO)
        for index in range(1, 16):
            self.assertIn(f"## MCP-{index:03d}", todo)
        for expected in (
            IMPLEMENTATION_SHA,
            IMPLEMENTATION_CI,
            IMPLEMENTATION_RELEASE_GATES,
            DOCUMENTATION_CLOSED_SHA,
            DOCUMENTATION_CLOSED_CI,
            DOCUMENTATION_CLOSED_RELEASE_GATES,
        ):
            self.assertIn(expected, todo)

        completion = todo.split("## MCP completion declaration", 1)[1]
        for phrase in STALE_FINAL_PHRASES:
            self.assertNotIn(phrase, completion)
        self.assertIn("documentation/evidence-only", completion)


if __name__ == "__main__":
    unittest.main()
