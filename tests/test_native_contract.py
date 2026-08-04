from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "crates/libvnc-adapter/build.rs"
SHIM_HEADER = ROOT / "crates/libvnc-adapter/native/vnc_shim.h"
SHIM_SOURCE = ROOT / "crates/libvnc-adapter/native/vnc_shim.c"
ADAPTER = ROOT / "crates/libvnc-adapter/src/lib.rs"
NATIVE_SMOKE = ROOT / "tests/native/run.sh"
DESKTOP_SMOKE = ROOT / "tests/desktop/run.sh"
CI = ROOT / ".github/workflows/ci.yml"
DECISION = ROOT / "docs/LIBVNCCLIENT_BINDING_DECISION.md"


class NativeContractTests(unittest.TestCase):
    def test_native_build_denies_c_warnings_and_uses_pkg_config(self):
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn('"-Wall"', text)
        self.assertIn('"-Wextra"', text)
        self.assertIn('"-Werror"', text)
        self.assertIn('"-pedantic"', text)
        self.assertIn('"libvncclient"', text)
        self.assertIn("VRC_LIBVNCCLIENT_VERSION", text)

    def test_ci_installs_and_exercises_native_dependencies(self):
        text = CI.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("libvncserver-dev"), 2)
        self.assertGreaterEqual(text.count("pkg-config"), 2)
        self.assertIn("tests/native/run.sh", text)
        self.assertIn("cargo clippy --locked --workspace --all-targets --all-features -- -D warnings", text)

    def test_native_boundary_is_opaque_and_has_one_destroy_function(self):
        header = SHIM_HEADER.read_text(encoding="utf-8")
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("typedef struct vrc_client vrc_client;", header)
        self.assertNotIn("rfbClient", header)
        self.assertEqual(source.count("void vrc_client_destroy(vrc_client *client)"), 1)
        self.assertIn("impl Drop for NativeClient", adapter)
        self.assertNotIn("pub fn raw", adapter)

    def test_native_smoke_is_bounded_and_uses_file_mounted_password(self):
        text = NATIVE_SMOKE.read_text(encoding="utf-8")
        self.assertIn("timeout --kill-after=2s 30s", text)
        self.assertIn("VRC_VNC_PASSWORD_FILE", text)
        self.assertNotIn("VRC_VNC_PASSWORD=", text)
        self.assertIn("docker exec -i", text)
        self.assertIn("native-clipboard-proof", text)

    def test_desktop_here_doc_assertions_are_not_discarded(self):
        text = DESKTOP_SMOKE.read_text(encoding="utf-8")
        self.assertIn('docker exec -i "$container_name" python3 -', text)

    def test_binding_decision_records_required_safety_rules(self):
        text = DECISION.read_text(encoding="utf-8")
        for phrase in (
            "opaque native handle",
            "does not free `client->frameBuffer`",
            "no callback from C into Rust",
            "project-owned desktop container",
            "version is captured in CI evidence",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
