---
name: lint-n-test
description: Lint the files and run all tests for this repo. Use when the user asks to lint the code, run the tests, or both together.
---

Delegate this to a Haiku subagent via the Agent tool (`model: "haiku"`, `subagent_type: "general-purpose"`) rather than running it inline — this is mechanical command execution that doesn't need a stronger model.

Give the subagent this prompt:

> Run these commands in order from the repo root, in this exact sequence. Report the real output
> of each — do not summarize a command as passing without showing what it printed. Stop at the
> first failure rather than continuing past it.
>
> 1. `cargo fmt --all --check`
> 2. `cargo clippy --workspace --all-targets --all-features -- -D warnings`
> 3. `cargo test --workspace --all-features`
> 4. `ruff check .`
> 5. `pylint --rcfile=.pylintrc python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app`
> 6. `mypy --config-file mypy.ini python/src/vnc_remote_control tests scripts tools/ci_status desktop/test-app`
> 7. `python -m unittest discover -s tests -p 'test_*.py' -v`
>
> All lint errors and warnings in our own code (everything under the paths above) are bugs and
> must be fixed — never suggest suppressing them (no `# noqa`, `# pylint: disable`,
> `# type: ignore`, or config threshold changes) merely to get a clean run. Findings in
> third-party/vendor code are out of scope since that code isn't ours to fix.
>
> Return, for each command: which ran, whether it passed or failed, and the output of any command
> that failed (or was skipped because an earlier one failed).

Once the subagent returns, relay its per-command pass/fail results and any failure output to the
user plainly — don't just say "done."
