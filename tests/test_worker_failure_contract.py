"""Cross-language contract tests for the public worker failure taxonomy."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import get_args

from vnc_remote_control.models import WorkerFailure

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WORKER_FAILURES = (
    "authentication configuration request capacity unavailable rate_limited "
    "transport timeout protocol native"
).split()


class WorkerFailureContractTests(unittest.TestCase):
    """Keep the Python type and machine-readable API schema in lockstep."""

    def test_python_and_openapi_worker_failure_vocabularies_match(self) -> None:
        """Every Rust-visible public category is accepted by both client and schema."""
        self.assertEqual(list(get_args(WorkerFailure)), EXPECTED_WORKER_FAILURES)

        openapi = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
        self.assertEqual(
            openapi["components"]["schemas"]["WorkerFailure"]["enum"],
            EXPECTED_WORKER_FAILURES,
        )


if __name__ == "__main__":
    unittest.main()
