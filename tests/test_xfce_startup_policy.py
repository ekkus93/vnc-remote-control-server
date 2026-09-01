"""Regression tests for fail-closed XFCE session startup policy."""

import os
import signal
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "configure-xfce-session.sh"


class XfceStartupPolicyTests(unittest.TestCase):
    """Exercise bounded SaveOnExit setup and XFCE liveness checks."""

    def run_scenario(
        self, scenario: str, *, live_process: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run one mocked xfconf scenario against a supervised XFCE fixture."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            state = directory / "state"
            mock = directory / "xfconf-query"
            mock.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    count=0
                    if [[ -f "$MOCK_STATE" ]]; then count="$(cat "$MOCK_STATE")"; fi
                    count=$((count + 1))
                    printf '%s' "$count" > "$MOCK_STATE"
                    is_get=1
                    for argument in "$@"; do
                        if [[ "$argument" == "-s" || "$argument" == "-n" ]]; then is_get=0; fi
                    done
                    case "$MOCK_SCENARIO" in
                        immediate)
                            if (( is_get == 1 )); then printf 'false\\n'; fi
                            exit 0
                            ;;
                        delayed)
                            if (( count <= 4 )); then exit 1; fi
                            if (( is_get == 1 )); then printf 'false\\n'; fi
                            exit 0
                            ;;
                        setter_fail)
                            if (( is_get == 0 )); then exit 1; fi
                            printf 'false\\n'
                            ;;
                        getter_fail)
                            if (( is_get == 1 )); then exit 1; fi
                            exit 0
                            ;;
                        wrong_value)
                            if (( is_get == 1 )); then printf 'true\\n'; fi
                            exit 0
                            ;;
                        exit_during_verify)
                            if (( is_get == 1 )); then
                                kill -TERM "$XFCE_PID"
                                for _ in {1..100}; do
                                    if ! kill -0 "$XFCE_PID" 2>/dev/null; then break; fi
                                    sleep 0.01
                                done
                                printf 'false\\n'
                            fi
                            exit 0
                            ;;
                        *) exit 2 ;;
                    esac
                    """
                ),
                encoding="utf-8",
            )
            mock.chmod(0o755)

            pid_file = directory / "xfce-pid"
            with subprocess.Popen(
                [
                    "bash",
                    "-c",
                    'sleep 30 & child=$!; printf "%s" "$child" > "$1"; wait "$child"',
                    "xfce-supervisor",
                    str(pid_file),
                ]
            ) as supervisor:
                xfce_pid: int | None = None
                try:
                    for _ in range(100):
                        if pid_file.exists():
                            value = pid_file.read_text(encoding="utf-8")
                            if value:
                                xfce_pid = int(value)
                                break
                        time.sleep(0.01)
                    if xfce_pid is None:
                        raise RuntimeError("supervised XFCE fixture did not publish its PID")

                    if not live_process:
                        os.kill(xfce_pid, signal.SIGTERM)
                        supervisor.wait(timeout=2)

                    environment = os.environ.copy()
                    environment.update(
                        {
                            "PATH": f"{directory}:{environment['PATH']}",
                            "MOCK_STATE": str(state),
                            "MOCK_SCENARIO": scenario,
                            "XFCE_PID": str(xfce_pid),
                            "XFCE_SAVE_ON_EXIT_ATTEMPTS": "3",
                            "XFCE_SAVE_ON_EXIT_RETRY_DELAY_SECONDS": "0.01",
                        }
                    )
                    return subprocess.run(
                        ["bash", str(SCRIPT)],
                        cwd=ROOT,
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                finally:
                    if xfce_pid is not None:
                        try:
                            os.kill(xfce_pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    if supervisor.poll() is None:
                        supervisor.terminate()
                    supervisor.wait(timeout=2)

    def test_immediate_success(self) -> None:
        """Accept an immediately writable/readable false property."""
        self.assertEqual(self.run_scenario("immediate").returncode, 0)

    def test_delayed_xfconf_availability(self) -> None:
        """Retry boundedly when xfconf becomes available after startup."""
        self.assertEqual(self.run_scenario("delayed").returncode, 0)

    def test_permanent_setter_failure_is_fatal(self) -> None:
        """Fail startup when SaveOnExit cannot be written within the bound."""
        self.assertNotEqual(self.run_scenario("setter_fail").returncode, 0)

    def test_getter_failure_is_fatal(self) -> None:
        """Fail startup when SaveOnExit cannot be read back."""
        self.assertNotEqual(self.run_scenario("getter_fail").returncode, 0)

    def test_wrong_final_value_is_fatal(self) -> None:
        """Fail startup when verification observes a value other than false."""
        self.assertNotEqual(self.run_scenario("wrong_value").returncode, 0)

    def test_xfce_exit_while_waiting_is_fatal(self) -> None:
        """Fail immediately when XFCE exits before configuration succeeds."""
        result = self.run_scenario("immediate", live_process=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("XFCE session exited", result.stderr)

    def test_xfce_exit_during_verified_read_is_fatal(self) -> None:
        """Reject the race where XFCE exits during a successful readback."""
        result = self.run_scenario("exit_during_verify")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("XFCE session exited during SaveOnExit verification", result.stderr)


if __name__ == "__main__":
    unittest.main()
