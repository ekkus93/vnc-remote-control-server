from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
RELEASE = ROOT / ".github/workflows/release-gates.yml"
POLICY = ROOT / "docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md"
GITLEAKS_IGNORE = ROOT / ".gitleaksignore"
EXPECTED_GITLEAKS_FALSE_POSITIVE = (
    "309364caf5d44d316557aa585ad7d92d043b0a47:"
    "docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md:"
    "generic-api-key:95"
)


class ReleasePolicyContractTests(unittest.TestCase):
    def test_functional_ci_remains_authoritative(self):
        text = CI.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("name: CI\n"))
        self.assertIn("cargo fmt --all --check", text)
        self.assertIn(
            "cargo clippy --locked --workspace --all-targets --all-features -- -D warnings",
            text,
        )
        self.assertIn("cargo test --locked --workspace --all-features", text)
        self.assertIn("Run R13 Compose integration and E2E validation", text)

    def test_release_workflow_contains_fail_closed_jobs(self):
        text = RELEASE.read_text(encoding="utf-8")
        required = (
            "name: Release Gates",
            "static_policy:",
            "native_safety:",
            "image_security:",
            "cargo deny check",
            "actionlint .github/workflows/*.yml",
            "shellcheck --severity=warning",
            "docker buildx build --check",
            "docker compose -f deploy/compose.yaml config --quiet",
            "gitleaks git . --redact --no-banner --exit-code 1",
            "--format cyclonedx",
            "-Zsanitizer=address",
            "-Zsanitizer=thread",
            "MIRIFLAGS: -Zmiri-disable-isolation",
            "miri test",
            "scripts/verify_trivy_critical_vex.py",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertNotIn("continue-on-error: true", text)
        self.assertNotIn("--ignore-unfixed", text)

    def test_cache_and_actions_are_immutably_pinned(self):
        text = RELEASE.read_text(encoding="utf-8")
        self.assertIn(
            "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
            text,
        )
        self.assertNotIn("actions/cache@v", text)
        self.assertIn("fetch-depth: 0", text)

    def test_gitleaks_ignore_is_exact_false_positive_fingerprint_only(self):
        lines = [
            line.strip()
            for line in GITLEAKS_IGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(lines, [EXPECTED_GITLEAKS_FALSE_POSITIVE])
        fingerprint = lines[0]
        self.assertNotIn("*", fingerprint)
        self.assertNotIn("...", fingerprint)
        self.assertRegex(
            fingerprint,
            r"^[0-9a-f]{40}:docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03\.md:generic-api-key:95$",
        )

    def test_security_policy_forbids_silent_exceptions(self):
        text = POLICY.read_text(encoding="utf-8")
        self.assertIn("There are no implicit or silent exceptions", text)
        self.assertIn("Any unmatched CRITICAL tuple is release-blocking", text)
        self.assertIn("`--ignore-unfixed` is prohibited", text)
        self.assertIn("may not be changed to `continue-on-error`", text)
        self.assertIn("must not contain bearer tokens", text)
        self.assertIn("Neither workflow substitutes for the other", text)


if __name__ == "__main__":
    unittest.main()
