from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / ".github/workflows/publish-ci-status.yml"
CI = ROOT / ".github/workflows/ci.yml"


class WorkflowContractTests(unittest.TestCase):
    def test_publisher_has_minimum_permissions_and_no_checkout(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn("actions: read", text)
        self.assertIn("contents: read", text)
        self.assertIn("issues: write", text)
        self.assertNotIn("write-all", text)
        self.assertNotIn("actions/checkout", text)

    def test_publisher_handles_all_required_workflow_run_states(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertRegex(text, r"workflows:\s*\n\s*- CI")
        self.assertIn("- requested", text)
        self.assertIn("- in_progress", text)
        self.assertIn("- completed", text)

    def test_publisher_is_branch_and_issue_specific(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn('MONITORED_BRANCH: "master"', text)
        self.assertIn('ISSUE_NUMBER: "1"', text)
        self.assertIn("publish-ci-status-ci-master", text)
        self.assertIn('HEAD_BRANCH" != "$MONITORED_BRANCH', text)

    def test_publisher_has_double_stale_run_check_and_pagination(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("latest_run_id"), 4)
        self.assertIn("latest_run_id_after", text)
        self.assertGreaterEqual(text.count("--paginate --slurp"), 2)

    def test_publisher_fetches_trusted_default_branch_script(self):
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn("SCRIPT_PATH", text)
        self.assertIn("ref=${DEFAULT_BRANCH}", text)
        self.assertIn("base64 --decode", text)

    def test_ci_is_authoritative_for_master_and_uploads_evidence(self):
        text = CI.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("name: CI\n"))
        self.assertRegex(text, r"push:\s*\n\s*branches:\s*\n\s*- master")
        self.assertIn("actions/checkout@v6", text)
        self.assertIn("actions/setup-python@v6", text)
        self.assertNotIn("actions/checkout@v4", text)
        self.assertNotIn("actions/setup-python@v5", text)
        self.assertIn("python -m unittest discover", text)
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn("ci-evidence", text)


if __name__ == "__main__":
    unittest.main()
