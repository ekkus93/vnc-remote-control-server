"""Regression tests for the intentional R13 desktop restart health handoff."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = ROOT / "tests" / "integration"
sys.path.insert(0, str(INTEGRATION_DIR))

from r13_checks_abuse import _wait_desktop_restart_health  # noqa: E402
from r13_harness import Harness  # noqa: E402
from r13_types import Failure  # noqa: E402


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
        self.harness = mock.Mock(spec=Harness)

    def test_expected_sigterm_stopped_generation_can_transition_to_healthy(self) -> None:
        """An intentional stop may remain observable briefly after `compose up`."""
        self.harness.service_state.side_effect = [
            _state("exited", "unhealthy", exit_code=143),
            _state("running", "starting"),
            _state("running", "healthy"),
        ]
        with mock.patch("r13_checks_abuse.time.sleep", return_value=None):
            _wait_desktop_restart_health(self.harness, deadline_seconds=1)
        self.assertEqual(self.harness.service_state.call_count, 3)

    def test_unexpected_terminal_exit_still_fails_immediately(self) -> None:
        """The restart waiter must not convert arbitrary process failure into a retry."""
        self.harness.service_state.return_value = _state(
            "exited",
            "unhealthy",
            exit_code=1,
        )
        with (
            mock.patch("r13_checks_abuse.time.sleep", return_value=None),
            self.assertRaisesRegex(Failure, "terminal state during restart"),
        ):
            _wait_desktop_restart_health(self.harness, deadline_seconds=1)
        self.harness.service_state.assert_called_once_with("desktop")

    def test_oom_killed_sigterm_code_is_not_tolerated(self) -> None:
        """Exit 143 is tolerated only when Docker reports a clean intentional stop."""
        self.harness.service_state.return_value = _state(
            "exited",
            "unhealthy",
            exit_code=143,
            oom_killed=True,
        )
        with (
            mock.patch("r13_checks_abuse.time.sleep", return_value=None),
            self.assertRaisesRegex(Failure, "terminal state during restart"),
        ):
            _wait_desktop_restart_health(self.harness, deadline_seconds=1)
        self.harness.service_state.assert_called_once_with("desktop")


if __name__ == "__main__":
    unittest.main()
