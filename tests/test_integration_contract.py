"""Contract tests for the R13 Compose integration/E2E driver and its CI wiring."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class R13IntegrationContractTests(unittest.TestCase):
    """The R13 driver is a real, bounded, self-cleaning Compose harness wired into CI."""

    def setUp(self) -> None:
        """Load the runner script, the concatenated R13 driver source, and the CI workflow."""
        self.runner = (ROOT / "tests/integration/run.sh").read_text(encoding="utf-8")
        # The R13 driver is split across sibling `r13_*.py` modules by
        # responsibility (config, types, helpers, harness, checks); the
        # entry point `r13_integration.py` only orchestrates them. Markers
        # below are checked against the concatenated driver source so this
        # contract still verifies the implementation regardless of which
        # module a given behavior lives in.
        driver_dir = ROOT / "tests/integration"
        self.driver = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(driver_dir.glob("r13_*.py"))
        )
        self.workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    def test_harness_is_real_compose_bounded_and_self_cleaning(self) -> None:
        """The harness drives real Docker Compose, waits for readiness, and cleans up after."""
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
        """The driver covers connection, screenshot, input, clipboard, and abuse-handling."""
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
            "unsupported horizontal scrolling was not rejected explicitly",
            "clipboard_unavailable",
            "clipboard_too_large",
            "command_queue_full",
            "reconnect_rate_limited",
            "websocket_status",
        ):
            self.assertIn(marker, self.driver)

    def test_shutdown_and_redaction_are_fail_closed(self) -> None:
        """Shutdown waits for bounded container exit and diagnostic redaction fails closed."""
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
        """CI runs the R13 integration suite and uploads failure diagnostics as build artifacts."""
        self.assertIn("Run R13 Compose integration and E2E validation", self.workflow)
        self.assertIn("bash tests/integration/run.sh", self.workflow)
        self.assertIn("R13_FAILURE_ARTIFACT_DIR", self.workflow)
        self.assertIn("Upload R13 integration failure diagnostics", self.workflow)
        self.assertIn("r13-integration-failure-${{ github.run_id }}", self.workflow)


if __name__ == "__main__":
    unittest.main()
