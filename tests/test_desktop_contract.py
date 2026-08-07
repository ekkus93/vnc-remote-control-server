"""Contract tests for the desktop image, its entrypoints, and the bounded smoke test."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "desktop/Dockerfile"
ENTRYPOINT = ROOT / "desktop/entrypoint.sh"
HEALTHCHECK = ROOT / "desktop/healthcheck.sh"
XSTARTUP = ROOT / "desktop/xstartup"
SMOKE = ROOT / "tests/desktop/run.sh"

BASE_DIGEST = "020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd"


class DesktopContractTests(unittest.TestCase):
    """The desktop image, entrypoints, and smoke test satisfy the security contract."""

    def test_image_is_non_root_and_uses_runtime_secret(self) -> None:
        """The desktop image runs as non-root and reads the VNC password from a runtime secret."""
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertEqual(
            dockerfile.splitlines()[0],
            f"FROM debian:13.6-slim@sha256:{BASE_DIGEST}",
        )
        self.assertIn("USER desktop:desktop", dockerfile)
        self.assertNotIn("VNC_PASSWORD_FILE=", dockerfile)
        self.assertNotIn("VNC_PASSWORD=", dockerfile)
        self.assertIn("tigervnc-standalone-server", dockerfile)
        self.assertIn("tigervnc-tools", dockerfile)
        self.assertIn("xfce4-session", dockerfile)
        self.assertIn("rm -rf /var/lib/apt/lists/*", dockerfile)
        self.assertIn("${VNC_PASSWORD_FILE:-/run/secrets/vnc_password}", entrypoint)

    def test_shell_entrypoints_are_fail_closed(self) -> None:
        """The desktop shell entrypoints are strict-mode and fail closed on VNC auth setup."""
        for path in (ENTRYPOINT, HEALTHCHECK, XSTARTUP, SMOKE):
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"), path)
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('[[ -r "$password_file" ]]', entrypoint)
        self.assertIn('[[ -s "$password_file" ]]', entrypoint)
        self.assertIn("-SecurityTypes VncAuth", entrypoint)
        self.assertNotIn("SecurityTypes None", entrypoint)
        self.assertNotIn('printf "$password"', entrypoint)
        self.assertNotIn("    -fg", entrypoint)

    def test_vnc_is_only_host_published_for_bounded_smoke_test(self) -> None:
        """VNC is only host-published to loopback, and only for the bounded smoke test."""
        text = SMOKE.read_text(encoding="utf-8")
        self.assertIn(BASE_DIGEST, text)
        self.assertIn('chmod 0444 "$temporary_directory/vnc_password"', text)
        self.assertIn("--publish 127.0.0.1:5901:5901", text)
        self.assertNotIn("--publish 0.0.0.0", text)
        self.assertIn("127.0.0.1::5901", text)
        self.assertIn("definitely-wrong", text)


if __name__ == "__main__":
    unittest.main()
