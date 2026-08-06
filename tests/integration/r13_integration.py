#!/usr/bin/env python3
"""R13 real-Compose integration and end-to-end acceptance suite.

Only fixed, non-sensitive fixtures are used. Failure diagnostics are sanitized
before they are written to the optional R13_FAILURE_ARTIFACT_DIR.

The suite's implementation is split across sibling modules by responsibility:
fixed configuration and fixtures (`r13_config`), the `Failure`/`HttpResult`
types (`r13_types`), small pure helpers (`r13_helpers`), the real-Compose
process/container/HTTP harness (`r13_harness`), and the acceptance checks
themselves, grouped by concern (`r13_checks_auth`, `r13_checks_state`,
`r13_checks_abuse`, `r13_checks_shutdown`). This file only orchestrates them.
"""

from __future__ import annotations

import sys

from r13_checks_abuse import assert_abuse_and_concurrency, assert_reconnect_and_resource_bounds
from r13_checks_auth import assert_auth_contract, assert_wrong_password_and_missing_secret
from r13_checks_shutdown import assert_idle_shutdown, assert_logs_redacted, assert_queued_shutdown
from r13_checks_state import assert_initial_state_and_screenshots, assert_input_and_clipboard
from r13_harness import Harness


def main() -> int:
    harness = Harness()
    try:
        assert_wrong_password_and_missing_secret(harness)
        assert_auth_contract(harness)
        initial_etag = assert_initial_state_and_screenshots(harness)
        assert_input_and_clipboard(harness, initial_etag)
        assert_abuse_and_concurrency(harness)
        assert_reconnect_and_resource_bounds(harness)
        assert_logs_redacted(harness)
        assert_idle_shutdown(harness)
        assert_queued_shutdown(harness)
        harness.log("R13 integration and E2E validation passed")
        print("r13_integration_e2e_complete=1")
        return 0
    except BaseException as error:
        try:
            harness.capture_diagnostics(error)
        except BaseException as diagnostic_error:
            print(f"[r13-integration] diagnostic capture failed: {diagnostic_error}", file=sys.stderr)
        print(f"[r13-integration] fatal: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        harness.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
