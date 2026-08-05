from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class R13IntegrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = (ROOT / "tests/integration/run.sh").read_text(encoding="utf-8")
        self.driver = (ROOT / "tests/integration/r13_integration.py").read_text(encoding="utf-8")
        self.workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    def test_harness_is_real_compose_bounded_and_self_cleaning(self) -> None:
        for marker in (
            '"docker",\n            "compose"',
            "free_port()",
            "mkdtemp",
            "wait_service_health",
            "wait_ready",
            "capture_diagnostics",
            'down", "--volumes", "--remove-orphans',
            "R13_FAILURE_ARTIFACT_DIR",
        ):
            self.assertIn(marker, self.driver)
        self.assertIn("exec python3 tests/integration/r13_integration.py", self.runner)

    def test_connection_screenshot_input_clipboard_and_abuse_are_covered(self) -> None:
        for marker in (
            "authentication_failed",
            "missing VNC secret",
            'compose("stop", "desktop")',
            "framebuffer_unavailable",
            "parse_png_dimensions",
            "If-None-Match",
            "unsupported_text",
            "button_down",
            "scroll_too_large",
            "clipboard_unavailable",
            "clipboard_too_large",
            "command_queue_full",
            "reconnect_rate_limited",
            "websocket_status",
        ):
            self.assertIn(marker, self.driver)

    def test_shutdown_and_redaction_are_fail_closed(self) -> None:
        for marker in (
            '"docker", "kill", "--signal", "TERM"',
            "shutting_down",
            "wait_container_exit",
            "desktop_vnc_connections",
            "controller did not exit within bounded deadline",
            "[REDACTED]",
            "diagnostic redaction failed",
        ):
            self.assertIn(marker, self.driver)

    def test_authoritative_ci_runs_and_uploads_failure_diagnostics(self) -> None:
        self.assertIn("Run R13 Compose integration and E2E validation", self.workflow)
        self.assertIn("bash tests/integration/run.sh", self.workflow)
        self.assertIn("R13_FAILURE_ARTIFACT_DIR", self.workflow)
        self.assertIn("Upload R13 integration failure diagnostics", self.workflow)
        self.assertIn("r13-integration-failure-${{ github.run_id }}", self.workflow)


if __name__ == "__main__":
    unittest.main()
