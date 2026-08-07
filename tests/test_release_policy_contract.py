"""Contract tests asserting the CI and Release Gates workflows enforce release policy.

These tests read the CI workflow, Release Gates workflow, release policy
document, gitleaks ignore list, and auditable-binary verifier as text and
assert on required fail-closed patterns and forbidden compatibility escapes.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.ci_workflow_assertions import assert_baseline_rust_gates

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
RELEASE = ROOT / ".github/workflows/release-gates.yml"
POLICY = ROOT / "docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md"
GITLEAKS_IGNORE = ROOT / ".gitleaksignore"
AUDITABLE_VERIFIER = ROOT / "scripts/verify_auditable_binary.py"
EXPECTED_GITLEAKS_FALSE_POSITIVES = [
    (
        "309364caf5d44d316557aa585ad7d92d043b0a47:"
        "docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md:"
        "generic-api-key:95"
    ),
    (
        "009c94afe1e4fbc7aaf2e3d7a823e5d951052049:"
        "crates/controller-api/src/http/tests/health.rs:"
        "generic-api-key:94"
    ),
    (
        "6420b0fd3a90f9395b5302f0edee3195aa885017:"
        ".github/post-correctness-duplicate-h1-fix.py:"
        "generic-api-key:194"
    ),
]


class ReleasePolicyContractTests(unittest.TestCase):
    """Assert the CI and Release Gates workflows and their supporting docs hold policy."""

    def test_functional_ci_remains_authoritative(self) -> None:
        """CI must remain the authoritative gate: fmt, clippy -D warnings, tests, R13."""
        text = CI.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("name: CI\n"))
        assert_baseline_rust_gates(self, text)
        self.assertIn("Run R13 Compose integration and E2E validation", text)

    def test_release_workflow_contains_fail_closed_jobs(self) -> None:
        """Release Gates must run every required fail-closed job with no escape hatches."""
        text = RELEASE.read_text(encoding="utf-8")
        required = (
            "name: Release Gates",
            "static_policy:",
            "native_safety:",
            "image_security:",
            "cargo deny check advisories bans licenses sources",
            "run: actionlint",
            "shellcheck\n",
            "docker build --check desktop",
            "docker build --check -f controller/Dockerfile .",
            "docker compose -f deploy/compose.yaml config --quiet",
            "gitleaks git\n",
            "--report-path artifacts/static-policy/gitleaks.json",
            "--redact",
            "--log-opts='--all'",
            "--format cyclonedx",
            "-Zsanitizer=address",
            "-Zsanitizer=thread",
            "--package controller-api",
            "controller-tsan.log",
            "MIRIFLAGS: -Zmiri-disable-isolation",
            "miri test",
            "scripts/verify_auditable_binary.py",
            "scripts/verify_trivy_critical_vex.py",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertNotIn("deploy/docker-compose.yml", text)
        self.assertNotIn("--config .gitleaks.toml", text)
        self.assertNotIn("continue-on-error: true", text)
        self.assertNotIn("--ignore-unfixed", text)

    def test_auditable_verifier_is_committed_and_fail_closed(self) -> None:
        """The auditable-binary verifier must enforce its documented fail-closed checks."""
        text = AUDITABLE_VERIFIER.read_text(encoding="utf-8")
        self.assertIn('SECTION_NAME = ".dep-v0"', text)
        self.assertIn("MAX_DECOMPRESSED_BYTES = 8 * 1024 * 1024", text)
        self.assertIn(
            'STANDARD_SOURCES = {"crates.io", "git", "local", "registry"}',
            text,
        )
        self.assertIn("if not isinstance(source, str) or not source:", text)
        self.assertIn("expected exactly one root package", text)
        self.assertIn("dependency graph contains a cycle", text)
        self.assertIn("binary_sha256", text)
        self.assertNotIn('"CratesIo"', text)
        self.assertNotIn("except Exception", text)

    def test_cache_and_actions_are_immutably_pinned(self) -> None:
        """Release Gates actions/cache must be pinned to an immutable commit SHA."""
        text = RELEASE.read_text(encoding="utf-8")
        self.assertIn(
            "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
            text,
        )
        self.assertNotIn("actions/cache@v", text)
        self.assertIn("fetch-depth: 0", text)

    def test_gitleaks_ignore_is_exact_false_positive_fingerprints_only(self) -> None:
        """gitleaksignore must contain only the exact expected false-positive fingerprints."""
        lines = [
            line.strip()
            for line in GITLEAKS_IGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(lines, EXPECTED_GITLEAKS_FALSE_POSITIVES)
        for fingerprint in lines:
            self.assertNotIn("*", fingerprint)
            self.assertNotIn("...", fingerprint)
            self.assertRegex(
                fingerprint,
                r"^[0-9a-f]{40}:(?:docs/|crates/|\.github/)[^:]+:generic-api-key:[0-9]+$",
            )

    def test_security_policy_forbids_silent_exceptions(self) -> None:
        """The release policy doc must explicitly forbid silent/implicit exceptions."""
        text = POLICY.read_text(encoding="utf-8")
        self.assertIn("There are no implicit or silent exceptions", text)
        self.assertIn("Any unmatched CRITICAL tuple is release-blocking", text)
        self.assertIn("`--ignore-unfixed` is prohibited", text)
        self.assertIn("may not be changed to `continue-on-error`", text)
        self.assertIn("must not contain bearer tokens", text)
        self.assertIn("Neither workflow substitutes for the other", text)


if __name__ == "__main__":
    unittest.main()
