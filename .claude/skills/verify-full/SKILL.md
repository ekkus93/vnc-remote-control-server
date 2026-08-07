---
name: verify-full
description: Run the complete local gate battery this repo's CI enforces (fmt check, clippy -D warnings, cargo test, ruff/pylint/mypy, Python contract tests) before considering changes done. Use after making code changes and before telling the user work is complete, or when the user asks to verify, check, or run the full test suite.
---

Run these commands in order and report the actual output of each — do not summarize a command as
passing without showing what it printed. Stop and report on the first failure rather than
continuing past it; per this repo's zero-warning policy, warnings and failing gates are defects
to fix at the source, never to suppress or downgrade. This applies equally to the Python lint
gates: findings in our own code (everything under the paths in steps 4-6) must be fixed for real —
no `# noqa`, `# pylint: disable`, `# type: ignore`, or config threshold changes just to pass.

1. `cargo fmt --all --check`
2. `cargo clippy --workspace --all-targets --all-features -- -D warnings`
3. `cargo test --workspace --all-features`
4. `ruff check .`
5. `pylint --rcfile=.pylintrc python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app`
6. `mypy --config-file mypy.ini python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app`
7. `python -m unittest discover -s tests -p 'test_*.py' -v`

If all seven pass, say so plainly. If any fail, show the failing command's output and fix the
underlying cause before re-running from that step.

This covers the `quality` job of CI (`.github/workflows/ci.yml`). It does NOT run the `desktop`
job's Docker/TigerVNC-backed e2e suites (`tests/{worker-e2e,worker-text-clipboard-e2e,http-e2e,desktop,native,compose}/run.sh`)
or `cargo deny check` (`make security-scan`) — mention these as still-unverified surface if the
change plausibly touches them (native FFI, worker lifecycle, compose/deploy files, or dependencies).
