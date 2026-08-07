"""Contract tests asserting the CI and CI-status-publisher workflow files stay correct."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.ci_workflow_assertions import assert_baseline_rust_gates

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / ".github/workflows/publish-ci-status.yml"
CI = ROOT / ".github/workflows/ci.yml"

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


class WorkflowContractTests(unittest.TestCase):
    """Asserts the GitHub Actions workflow files carry required behavior and safety properties."""

    def test_publisher_has_minimum_permissions_and_no_checkout(self) -> None:
        """The publisher workflow requests only its minimum required permissions."""
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn("actions: read", text)
        self.assertIn("contents: read", text)
        self.assertIn("issues: write", text)
        self.assertNotIn("write-all", text)
        self.assertNotIn("actions/checkout", text)

    def test_publisher_handles_all_required_workflow_run_states(self) -> None:
        """The publisher workflow reacts to the CI workflow's requested/in_progress/completed
        states."""
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertRegex(text, r"workflows:\s*\n\s*- CI")
        self.assertIn("- requested", text)
        self.assertIn("- in_progress", text)
        self.assertIn("- completed", text)

    def test_publisher_is_branch_and_issue_specific(self) -> None:
        """The publisher workflow is scoped to the master branch and issue #1."""
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn('MONITORED_BRANCH: "master"', text)
        self.assertIn('ISSUE_NUMBER: "1"', text)
        self.assertIn("publish-ci-status-ci-master", text)
        self.assertIn('HEAD_BRANCH" != "$MONITORED_BRANCH', text)

    def test_publisher_has_double_stale_run_check_and_pagination(self) -> None:
        """The publisher workflow double-checks for a stale run and paginates its API calls."""
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("latest_run_id"), 4)
        self.assertIn("latest_run_id_after", text)
        self.assertGreaterEqual(text.count("--paginate --slurp"), 2)

    def test_publisher_fetches_trusted_default_branch_script(self) -> None:
        """The publisher workflow fetches its helper script from the trusted default branch."""
        text = PUBLISHER.read_text(encoding="utf-8")
        self.assertIn("SCRIPT_PATH", text)
        self.assertIn("ref=${DEFAULT_BRANCH}", text)
        self.assertIn("base64 --decode", text)

    def test_ci_is_authoritative_for_master_and_uploads_evidence(self) -> None:
        """The CI workflow runs on master with pinned actions and uploads evidence artifacts."""
        text = CI.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("name: CI\n"))
        self.assertRegex(text, r"push:\s*\n\s*branches:\s*\n\s*- master")
        self.assertIn(f"actions/checkout@{CHECKOUT_SHA}", text)
        self.assertIn(f"actions/setup-python@{SETUP_PYTHON_SHA}", text)
        self.assertIn(f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}", text)
        self.assertNotRegex(text, r"actions/(checkout|setup-python|upload-artifact)@v\d")
        self.assertIn("rustup toolchain install 1.97.1", text)
        self.assertIn("cargo fetch --locked", text)
        assert_baseline_rust_gates(self, text)
        self.assertIn("cargo doc --locked --workspace --all-features --no-deps", text)
        self.assertNotIn("cargo generate-lockfile", text)
        self.assertIn("RUSTDOCFLAGS: -Dwarnings", text)
        self.assertIn("python -m unittest discover", text)
        self.assertIn("ci-evidence", text)


if __name__ == "__main__":
    unittest.main()
