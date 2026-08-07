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
        self.assertIn("bash tests/native/run.sh", text)
        self.assertNotIn("test -x tests/native/run.sh", text)
        self.assertIn(
            "cargo clippy --locked --workspace --all-targets --all-features -- -D warnings",
            text,
        )

    def test_native_boundary_is_opaque_and_has_one_destroy_function(self):
        header = SHIM_HEADER.read_text(encoding="utf-8")
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("typedef struct vrc_client vrc_client;", header)
        self.assertNotIn("rfbClient", header)
        self.assertEqual(source.count("void vrc_client_destroy(vrc_client *client)"), 1)
        self.assertIn("impl Drop for NativeClient", adapter)
        self.assertNotIn("pub fn raw", adapter)

    def test_native_framebuffer_updates_use_library_incremental_rearm(self):
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        callback_start = source.index("static void vrc_finished_framebuffer_update")
        callback_end = source.index("static void vrc_store_clipboard", callback_start)
        callback = source[callback_start:callback_end]
        self.assertNotIn("SendFramebufferUpdateRequest(", callback)
        self.assertIn("client->revision += 1U;", callback)
        self.assertIn("client->complete = 1;", callback)

        connect_start = source.index("vrc_status vrc_client_connect")
        connect_end = source.index("vrc_status vrc_client_poll", connect_start)
        connect = source[connect_start:connect_end]
        for assignment in (
            "client->native->updateRect.x = 0;",
            "client->native->updateRect.y = 0;",
            "client->native->updateRect.w = client->native->width;",
            "client->native->updateRect.h = client->native->height;",
        ):
            self.assertIn(assignment, connect)
        self.assertIn("HandleRFBServerMessage automatically sends", connect)
        self.assertLess(connect.index("updateRect.x = 0"), connect.index("SendFramebufferUpdateRequest("))

    def test_native_initialization_keeps_one_cleanup_owner(self):
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("rfbInitClient(", source)
        self.assertIn("ConnectToRFBServer(", source)
        self.assertIn("InitialiseRFBConnection(", source)
        self.assertIn("SetFormatAndEncodings(", source)
        self.assertEqual(source.count("rfbClientCleanup("), 1)

    def test_project_owned_native_clipboard_buffers_are_scrubbed_before_free(self):
        source = SHIM_SOURCE.read_text(encoding="utf-8")

        helper_start = source.index("static void vrc_release_clipboard")
        helper_end = source.index("static char *vrc_duplicate", helper_start)
        helper = source[helper_start:helper_end]
        self.assertIn("vrc_secure_scrub(*clipboard, *length + 1U);", helper)
        self.assertLess(helper.index("vrc_secure_scrub"), helper.index("free(*clipboard)"))

        store_start = source.index("static void vrc_store_clipboard")
        store_end = source.index("static void vrc_got_clipboard", store_start)
        store = source[store_start:store_end]
        self.assertLess(store.index("clipboard revision overflow"), store.index("copy = malloc"))
        self.assertIn(
            "vrc_release_clipboard(&client->clipboard, &client->clipboard_length);",
            store,
        )

        send_start = source.index("vrc_status vrc_client_send_clipboard")
        send_end = source.index("vrc_status vrc_client_dimensions", send_start)
        send = source[send_start:send_end]
        self.assertIn("vrc_secure_scrub(copy, text_length + 1U);", send)
        self.assertLess(send.index("vrc_secure_scrub"), send.index("free(copy)"))

        destroy_start = source.index("void vrc_client_destroy")
        destroy = source[destroy_start:]
        self.assertIn(
            "vrc_release_clipboard(&client->clipboard, &client->clipboard_length);",
            destroy,
        )

    def test_native_smoke_is_bounded_and_uses_file_mounted_password(self):
        text = NATIVE_SMOKE.read_text(encoding="utf-8")
        self.assertIn("timeout --kill-after=2s 35s", text)
        self.assertIn("VRC_VNC_PASSWORD_FILE", text)
        self.assertNotIn("VRC_VNC_PASSWORD=", text)
        self.assertIn("VRC_PROOF_HOLD_SECONDS=15", text)
        self.assertIn("proof_ready=1", text)
        self.assertIn("while connected", text)
        self.assertIn("docker exec -i", text)
        self.assertIn("native-clipboard-proof", text)

    def test_native_failure_probes_are_bounded_and_fail_cleanly(self):
        text = NATIVE_SMOKE.read_text(encoding="utf-8")
        self.assertIn("run_expected_connection_failure", text)
        self.assertIn("timeout --kill-after=2s 10s", text)
        self.assertIn('[[ "$status" -eq 1 ]]', text)
        self.assertIn("wrong-password", text)
        self.assertIn("unreachable-port", text)
        self.assertIn("native spike failed:", text)
        self.assertIn("unexpectedly reached an authenticated proof state", text)
        self.assertIn("exposed its VNC password in output", text)

    def test_desktop_here_doc_assertions_are_not_discarded(self):
        text = DESKTOP_SMOKE.read_text(encoding="utf-8")
        self.assertIn('docker exec -i "$container_name" python3 -', text)

    def test_binding_decision_records_required_safety_rules(self):
        text = DECISION.read_text(encoding="utf-8").casefold()
        for phrase in (
            "opaque native handle",
            "does not free `client->frameBuffer`",
            "no callback from C into Rust",
            "project-owned desktop container",
            "version is captured in CI evidence",
            "does not call `rfbInitClient`",
            "one cleanup owner",
        ):
            self.assertIn(phrase.casefold(), text)


if __name__ == "__main__":
    unittest.main()
