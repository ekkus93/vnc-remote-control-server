"""Regression tests for the intentional R13 desktop restart health handoff."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = ROOT / "tests" / "integration"
sys.path.insert(0, str(INTEGRATION_DIR))

R13_CHECKS_ABUSE = importlib.import_module("r13_checks_abuse")
R13_HARNESS = importlib.import_module("r13_harness")
R13_TYPES = importlib.import_module("r13_types")
WAIT_DESKTOP_RESTART_HEALTH = R13_CHECKS_ABUSE.wait_desktop_restart_health
FAILURE = R13_TYPES.Failure


def _state(
    status: str,
    health: str,
    *,
    exit_code: int = 0,
    oom_killed: bool = False,
    error: str = "",
) -> dict[str, object]:
    return {
        "Status": status,
        "Health": {"Status": health},
        "ExitCode": exit_code,
        "OOMKilled": oom_killed,
        "Error": error,
    }


class R13DesktopRestartWaitTests(unittest.TestCase):
    """Keep the restart race fix narrow and fail closed for other terminal states."""

    def setUp(self) -> None:
        self.harness = mock.Mock(spec=R13_HARNESS.Harness)

    def test_expected_sigterm_stopped_generation_can_transition_to_healthy(self) -> None:
        """An intentional stop may remain observable briefly after `compose up`."""
        self.harness.service_state.side_effect = [
            _state("exited", "unhealthy", exit_code=143),
            _state("running", "starting"),
        ]
        with mock.patch("r13_checks_abuse.time.sleep", return_value=None):
            WAIT_DESKTOP_RESTART_HEALTH(self.harness, deadline_seconds=1)
        self.assertEqual(self.harness.service_state.call_count, 2)
        self.harness.wait_service_health.assert_called_once()
        args = self.harness.wait_service_health.call_args.args
        self.assertEqual(args[0], "desktop")
        self.assertGreater(args[1], 0)
        self.assertLessEqual(args[1], 1)

    def test_unexpected_terminal_exit_delegates_to_strict_waiter(self) -> None:
        """Arbitrary process failure is never reclassified as an expected restart stop."""
        self.harness.service_state.return_value = _state(
            "exited",
            "unhealthy",
            exit_code=1,
        )
        self.harness.wait_service_health.side_effect = FAILURE("unexpected exit")
        with self.assertRaisesRegex(FAILURE, "unexpected exit"):
            WAIT_DESKTOP_RESTART_HEALTH(self.harness, deadline_seconds=1)
        self.harness.service_state.assert_called_once_with("desktop")
        self.harness.wait_service_health.assert_called_once()

    def test_oom_killed_sigterm_code_delegates_to_strict_waiter(self) -> None:
        """Exit 143 is skipped only when Docker reports a clean intentional stop."""
        self.harness.service_state.return_value = _state(
            "exited",
            "unhealthy",
            exit_code=143,
            oom_killed=True,
        )
        self.harness.wait_service_health.side_effect = FAILURE("oom-killed exit")
        with self.assertRaisesRegex(FAILURE, "oom-killed exit"):
            WAIT_DESKTOP_RESTART_HEALTH(self.harness, deadline_seconds=1)
        self.harness.service_state.assert_called_once_with("desktop")
        self.harness.wait_service_health.assert_called_once()


if __name__ == "__main__":
    unittest.main()
