from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "crates/controller-api/src/bin/worker-input-e2e.rs"
HARNESS = ROOT / "tests/worker-e2e/run.sh"
CI = ROOT / ".github/workflows/ci.yml"


class WorkerInputE2EContractTests(unittest.TestCase):
    def test_driver_uses_production_worker_and_all_required_inputs(self):
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn("DesktopWorker::spawn(settings)", text)
        self.assertIn("worker.client()", text)
        self.assertIn("WorkerCommand::MovePointer", text)
        self.assertIn("WorkerCommand::SetButton", text)
        self.assertIn("WorkerCommand::Click", text)
        self.assertIn("WorkerCommand::DoubleClick", text)
        self.assertIn("WorkerCommand::Scroll", text)
        self.assertIn("WorkerCommand::SetKey", text)
        self.assertIn("WorkerCommand::Chord", text)
        self.assertIn("MouseButton::Middle", text)
        self.assertIn("MouseButton::Right", text)
        self.assertIn("delta_y: -1", text)
        self.assertIn("worker.shutdown", text)
        self.assertNotIn("NativeClient::connect", text)

    def test_harness_verifies_deterministic_desktop_state(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn("cargo run --locked --quiet -p controller-api --bin worker-input-e2e", text)
        self.assertIn("docker exec -i", text)
        self.assertIn("/tmp/vnc-test-app-state.json", text)
        self.assertIn("mouse_sequence", text)
        self.assertIn("button_down", text)
        self.assertIn("button_up", text)
        self.assertIn("'middle'", text)
        self.assertIn("'right'", text)
        self.assertIn("positive_vertical_steps == 2", text)
        self.assertIn("negative_vertical_steps == 1", text)
        self.assertIn("Control_L", text)
        self.assertIn("Shift_L", text)
        self.assertIn("F5", text)
        self.assertIn("F6", text)
        self.assertIn("keys_down", text)
        self.assertIn("worker_input_e2e_complete=1", text)

    def test_harness_captures_redacted_failure_diagnostics(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn("WORKER_E2E_FAILURE_ARTIFACT_DIR", text)
        self.assertIn("WORKER_E2E_FORCE_FAILURE_AFTER_INPUT", text)
        self.assertIn("WORKER_E2E_REDACTION_SELF_TEST", text)
        self.assertIn("capture_failure_artifacts", text)
        self.assertIn("worker-input-e2e.log", text)
        self.assertIn("desktop.log", text)
        self.assertIn("desktop-state.json", text)
        self.assertIn("container-state.json", text)
        self.assertIn("failure-manifest.json", text)
        self.assertIn("redaction-self-test.log", text)
        self.assertIn("[REDACTED]", text)
        self.assertIn("if (( exit_status != 0 ))", text)

    def test_authoritative_ci_runs_the_worker_e2e(self):
        text = CI.read_text(encoding="utf-8")
        self.assertIn("tests/worker-e2e/run.sh", text)
        self.assertIn("Run WorkerHandle TigerVNC input E2E test", text)

    def test_authoritative_ci_uploads_failure_only_diagnostics(self):
        text = CI.read_text(encoding="utf-8")
        self.assertIn("id: worker_e2e", text)
        self.assertIn(
            "WORKER_E2E_FAILURE_ARTIFACT_DIR: artifacts/worker-e2e-failure",
            text,
        )
        self.assertIn("Upload WorkerHandle E2E failure artifacts", text)
        self.assertIn(
            "failure() && steps.worker_e2e.outcome == 'failure'",
            text,
        )
        self.assertIn("name: worker-e2e-failure-${{ github.run_id }}", text)
        self.assertIn("path: artifacts/worker-e2e-failure", text)
        self.assertIn("if-no-files-found: error", text)

    def test_authoritative_ci_exercises_and_redacts_failure_diagnostics(self):
        text = CI.read_text(encoding="utf-8")
        self.assertIn("Verify WorkerHandle E2E failure diagnostics", text)
        self.assertIn("WORKER_E2E_FORCE_FAILURE_AFTER_INPUT: \"1\"", text)
        self.assertIn("WORKER_E2E_REDACTION_SELF_TEST: \"1\"", text)
        self.assertIn("redaction-self-test.log", text)
        self.assertIn("grep -Fxq '[REDACTED]'", text)
        self.assertIn("grep -R -Fq 'worker-e2e-vnc-password'", text)
        self.assertIn("captured desktop state contains no input events", text)
        self.assertIn('rm -rf -- "$WORKER_E2E_FAILURE_ARTIFACT_DIR"', text)


if __name__ == "__main__":
    unittest.main()
