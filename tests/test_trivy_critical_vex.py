"""Contract tests for scripts/verify_trivy_critical_vex.py's fail-closed VEX matching."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_trivy_critical_vex.py"


def report(cve: str = "CVE-2099-0001") -> dict[str, Any]:
    """Build a minimal Trivy report payload with one CRITICAL vulnerability."""
    return {
        "Results": [
            {
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": cve,
                        "PkgName": "example-package",
                        "InstalledVersion": "1.2.3",
                        "Severity": "CRITICAL",
                    }
                ]
            }
        ]
    }


def vex(expires: str = "2026-08-31") -> dict[str, Any]:
    """Build a minimal VEX payload with one exact determination for CVE-2099-0001."""
    return {
        "schema_version": 1,
        "reviewed_at": "2026-08-01",
        "expires_at": expires,
        "tracking_issue": 7,
        "entries": [
            {
                "id": "CVE-2099-0001",
                "decision": "not_exploitable",
                "installed_version": "1.2.3",
                "packages": {"controller": ["example-package"]},
                "rationale": (
                    "This deterministic fixture has no path from an external input to the "
                    "synthetic vulnerable operation and exists only to verify exact matching."
                ),
                "source": "https://security-tracker.debian.org/tracker/CVE-2099-0001",
            }
        ],
    }


class CriticalVexTests(unittest.TestCase):
    """Verify the CRITICAL/VEX matching script fails closed on new or stale findings."""

    def run_verifier(
        self, report_payload: dict[str, Any], vex_payload: dict[str, Any]
    ) -> subprocess.CompletedProcess[str]:
        """Run the verifier script against a report/VEX fixture pair and capture the result."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "controller-vulnerabilities.json"
            vex_path = root / "vex.json"
            output_path = root / "result.json"
            report_path.write_text(json.dumps(report_payload), encoding="utf-8")
            vex_path.write_text(json.dumps(vex_payload), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--today",
                    "2026-08-05",
                    "--vex",
                    str(vex_path),
                    "--output",
                    str(output_path),
                    str(report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

    def test_exact_current_determination_passes(self) -> None:
        """An exact, current VEX determination for the only finding should exit 0."""
        completed = self.run_verifier(report(), vex())
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_new_cve_fails_closed(self) -> None:
        """A CRITICAL finding with no matching VEX entry should fail closed with exit 1."""
        completed = self.run_verifier(report("CVE-2099-9999"), vex())
        self.assertEqual(completed.returncode, 1)
        self.assertIn("unreviewed CRITICAL findings", completed.stderr)

    def test_expired_determination_fails_closed(self) -> None:
        """An expired VEX determination should fail closed with exit 2."""
        completed = self.run_verifier(report(), vex("2026-08-04"))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("VEX expired", completed.stderr)


if __name__ == "__main__":
    unittest.main()
