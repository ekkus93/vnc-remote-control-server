"""Contract tests asserting the C/Rust native VNC binding's safety invariants.

These tests read the build script, native shim source, Rust adapter, CI
workflow, and smoke-test scripts as text and assert on the presence (or
absence) of specific patterns that encode the project's native-binding
safety rules, as recorded in docs/LIBVNCCLIENT_BINDING_DECISION.md.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "crates/libvnc-adapter/build.rs"
SHIM_HEADER = ROOT / "crates/libvnc-adapter/native/vnc_shim.h"
SHIM_SOURCE = ROOT / "crates/libvnc-adapter/native/vnc_shim.c"
ADAPTER = ROOT / "crates/libvnc-adapter/src/lib.rs"
DESKTOP_WORKER = ROOT / "crates/controller-api/src/worker/desktop_worker.rs"
NATIVE_SMOKE = ROOT / "tests/native/run.sh"
DESKTOP_SMOKE = ROOT / "tests/desktop/run.sh"
CI = ROOT / ".github/workflows/ci.yml"
DECISION = ROOT / "docs/LIBVNCCLIENT_BINDING_DECISION.md"


class NativeContractTests(unittest.TestCase):
    """Assert the native VNC binding's build, shim, and CI safety rules hold."""

    def test_native_build_denies_c_warnings_and_uses_pkg_config(self) -> None:
        """build.rs must compile the shim with strict warnings and pkg-config."""
        text = BUILD.read_text(encoding="utf-8")
        self.assertIn('"-Wall"', text)
        self.assertIn('"-Wextra"', text)
        self.assertIn('"-Werror"', text)
        self.assertIn('"-pedantic"', text)
        self.assertIn('"libvncclient"', text)
        self.assertIn("VRC_LIBVNCCLIENT_VERSION", text)

    def test_ci_installs_and_exercises_native_dependencies(self) -> None:
        """CI must install libvncserver-dev/pkg-config and run the native smoke test."""
        text = CI.read_text(encoding="utf-8")
        self.assertGreaterEqual(text.count("libvncserver-dev"), 2)
        self.assertGreaterEqual(text.count("pkg-config"), 2)
        self.assertIn("bash tests/native/run.sh", text)
        self.assertNotIn("test -x tests/native/run.sh", text)
        self.assertIn(
            "cargo clippy --locked --workspace --all-targets --all-features -- -D warnings",
            text,
        )

    def test_native_boundary_is_opaque_and_has_one_destroy_function(self) -> None:
        """The FFI boundary must hide rfbClient behind an opaque handle with one destroy."""
        header = SHIM_HEADER.read_text(encoding="utf-8")
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("typedef struct vrc_client vrc_client;", header)
        self.assertNotIn("rfbClient", header)
        self.assertEqual(source.count("void vrc_client_destroy(vrc_client *client)"), 1)
        self.assertIn("impl Drop for NativeClient", adapter)
        self.assertNotIn("pub fn raw", adapter)

    def test_native_framebuffer_updates_use_library_incremental_rearm(self) -> None:
        """Framebuffer updates must rely on libvncclient's automatic rearm, not manual resends."""
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
        self.assertLess(
            connect.index("updateRect.x = 0"),
            connect.index("SendFramebufferUpdateRequest("),
        )

    def test_native_initialization_keeps_one_cleanup_owner(self) -> None:
        """Client init must use the documented sequence and free the client exactly once."""
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("rfbInitClient(", source)
        self.assertIn("ConnectToRFBServer(", source)
        self.assertIn("InitialiseRFBConnection(", source)
        self.assertIn("SetFormatAndEncodings(", source)
        self.assertEqual(source.count("rfbClientCleanup("), 1)

    def test_project_owned_sensitive_buffers_share_scrub_before_free_primitive(self) -> None:
        """Clipboard/password buffers must be scrubbed before free via one shared primitive."""
        source = SHIM_SOURCE.read_text(encoding="utf-8")

        primitive_start = source.index("static void vrc_scrub_and_free")
        primitive_end = source.index("static void vrc_release_clipboard", primitive_start)
        primitive = source[primitive_start:primitive_end]
        self.assertIn("vrc_secure_scrub(buffer, length);", primitive)
        self.assertIn("free(buffer);", primitive)
        self.assertLess(primitive.index("vrc_secure_scrub"), primitive.index("free(buffer)"))
        self.assertEqual(source.count("vrc_secure_scrub("), 2)

        helper_start = source.index("static void vrc_release_clipboard")
        helper_end = source.index("static char *vrc_duplicate", helper_start)
        helper = source[helper_start:helper_end]
        self.assertIn("vrc_scrub_and_free(*clipboard, *length + 1U);", helper)

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
        self.assertIn("vrc_scrub_and_free(copy, text_length + 1U);", send)
        self.assertNotIn("free(copy);", send)

        destroy_start = source.index("void vrc_client_destroy")
        destroy = source[destroy_start:]
        self.assertIn(
            "vrc_release_clipboard(&client->clipboard, &client->clipboard_length);",
            destroy,
        )
        self.assertIn(
            "vrc_scrub_and_free(client->password, strlen(client->password) + 1U);",
            destroy,
        )
        self.assertNotIn("free(client->clipboard);", source)
        self.assertNotIn("free(client->password);", source)
        self.assertNotIn("free(copy);", source)
        self.assertEqual(source.count("vrc_scrub_and_free("), 4)

    def test_reconnect_secret_duplication_is_named_and_local(self) -> None:
        """Reconnect config duplication must use a named factory, not a bare settings clone."""
        source = DESKTOP_WORKER.read_text(encoding="utf-8")
        self.assertNotIn("settings.native.clone()", source)
        self.assertIn("duplicate_native_config_for_reconnect_factory", source)
        self.assertIn(
            "password: SecretString::from(config.password.expose_secret()),",
            source,
        )
        self.assertIn("requires one additional owned", source)

    def test_native_smoke_is_bounded_and_uses_file_mounted_password(self) -> None:
        """The native smoke test must be time-bounded and read the VNC password from a file."""
        text = NATIVE_SMOKE.read_text(encoding="utf-8")
        self.assertIn("timeout --kill-after=2s 35s", text)
        self.assertIn("VRC_VNC_PASSWORD_FILE", text)
        self.assertNotIn("VRC_VNC_PASSWORD=", text)
        self.assertIn("VRC_PROOF_HOLD_SECONDS=15", text)
        self.assertIn("proof_ready=1", text)
        self.assertIn("while connected", text)
        self.assertIn("docker exec -i", text)
        self.assertIn("native-clipboard-proof", text)

    def test_native_failure_probes_are_bounded_and_fail_cleanly(self) -> None:
        """Expected-failure probes must be time-bounded and never leak the VNC password."""
        text = NATIVE_SMOKE.read_text(encoding="utf-8")
        self.assertIn("run_expected_connection_failure", text)
        self.assertIn("timeout --kill-after=2s 10s", text)
        self.assertIn('[[ "$status" -eq 1 ]]', text)
        self.assertIn("wrong-password", text)
        self.assertIn("unreachable-port", text)
        self.assertIn("native spike failed:", text)
        self.assertIn("unexpectedly reached an authenticated proof state", text)
        self.assertIn("exposed its VNC password in output", text)

    def test_desktop_here_doc_assertions_are_not_discarded(self) -> None:
        """The desktop smoke test's in-container Python assertions must run under -i."""
        text = DESKTOP_SMOKE.read_text(encoding="utf-8")
        self.assertIn('docker exec -i "$container_name" python3 -', text)

    def test_binding_decision_records_required_safety_rules(self) -> None:
        """The binding decision doc must record every required native safety rule."""
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
