from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "crates/controller-api/src/bin/worker-text-clipboard-e2e.rs"
HARNESS = ROOT / "tests/worker-text-clipboard-e2e/run.sh"
CI = ROOT / ".github/workflows/ci.yml"


class WorkerTextClipboardE2EContractTests(unittest.TestCase):
    def test_driver_uses_production_worker_text_and_clipboard_commands(self):
        text = DRIVER.read_text(encoding="utf-8")
        self.assertIn("DesktopWorker::spawn(settings)", text)
        self.assertIn("worker.client()", text)
        self.assertIn("WorkerCommand::TypeText", text)
        self.assertIn("WorkerCommand::SetClipboard", text)
        self.assertIn("DesktopError::UnsupportedText", text)
        self.assertIn("client.clipboard_snapshot()", text)
        self.assertIn("DesktopEventKind::ClipboardRevision", text)
        self.assertIn("worker.shutdown", text)
        self.assertNotIn("NativeClient::connect", text)

    def test_harness_verifies_live_tigervnc_text_and_both_clipboard_directions(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn(
            "cargo run --locked --quiet -p controller-api --bin worker-text-clipboard-e2e",
            text,
        )
        self.assertIn("worker_text_clipboard_outbound_ready=1", text)
        self.assertIn("worker_text_clipboard_e2e_complete=1", text)
        self.assertIn("deterministic app text differs", text)
        self.assertIn("desktop did not observe outbound WorkerClient clipboard", text)
        self.assertIn("publishing desktop clipboard for inbound worker observation", text)
        self.assertIn("clipboard_revision=[1-9][0-9]*", text)
        self.assertIn("worker log exposed a secret or text/clipboard payload", text)
        self.assertIn("desktop log exposed a secret or text/clipboard payload", text)

    def test_harness_uses_only_fixed_non_sensitive_fixtures(self):
        text = HARNESS.read_text(encoding="utf-8")
        self.assertIn("supported_text='worker text 123'", text)
        self.assertIn("unsupported_text='blocked☃'", text)
        self.assertIn("outbound_clipboard='worker outbound clipboard'", text)
        self.assertIn("inbound_clipboard='desktop inbound clipboard'", text)

    def test_authoritative_ci_runs_text_and_clipboard_e2e(self):
        text = CI.read_text(encoding="utf-8")
        self.assertIn("tests/worker-text-clipboard-e2e/run.sh", text)
        self.assertIn("Run WorkerHandle TigerVNC text and clipboard E2E test", text)


if __name__ == "__main__":
    unittest.main()
