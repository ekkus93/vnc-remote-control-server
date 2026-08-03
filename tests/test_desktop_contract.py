from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "desktop/Dockerfile"
ENTRYPOINT = ROOT / "desktop/entrypoint.sh"
HEALTHCHECK = ROOT / "desktop/healthcheck.sh"
XSTARTUP = ROOT / "desktop/xstartup"
SMOKE = ROOT / "tests/desktop/run.sh"


class DesktopContractTests(unittest.TestCase):
    def test_image_is_non_root_and_uses_runtime_secret(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("FROM debian:13.6-slim", text)
        self.assertIn("USER desktop:desktop", text)
        self.assertIn("VNC_PASSWORD_FILE=/run/secrets/vnc_password", text)
        self.assertNotIn("VNC_PASSWORD=", text)
        self.assertIn("tigervnc-standalone-server", text)
        self.assertIn("xfce4-session", text)
        self.assertIn("rm -rf /var/lib/apt/lists/*", text)

    def test_shell_entrypoints_are_fail_closed(self) -> None:
        for path in (ENTRYPOINT, HEALTHCHECK, XSTARTUP, SMOKE):
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n"), path)
        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('[[ -r "$password_file" ]]', entrypoint)
        self.assertIn('[[ -s "$password_file" ]]', entrypoint)
        self.assertIn("-SecurityTypes VncAuth", entrypoint)
        self.assertNotIn("SecurityTypes None", entrypoint)
        self.assertNotIn('printf "$password"', entrypoint)

    def test_vnc_is_only_host_published_for_bounded_smoke_test(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")
        self.assertIn("--publish 127.0.0.1:5901:5901", text)
        self.assertNotIn("--publish 0.0.0.0", text)
        self.assertIn("127.0.0.1::5901", text)
        self.assertIn("definitely-wrong", text)


if __name__ == "__main__":
    unittest.main()
