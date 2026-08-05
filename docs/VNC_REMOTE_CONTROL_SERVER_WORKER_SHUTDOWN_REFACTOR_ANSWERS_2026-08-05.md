# Answers: Worker Shutdown Refactor Handoff Questions

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Responds to: `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_RESPONSES_2026-08-05.md`

Companion documents:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_SPEC_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_REFACTOR_TODO_2026-08-05.md`

## 1. Local validation command authority

Question:

> Spec §7 / TODO F9's local validation commands don't exactly match `Makefile`/CI. Should the actual Makefile/CI commands be run instead when validating locally, or should the spec's commands be followed literally as written?

Answer:

Run the actual Makefile/CI-equivalent commands. Treat the spec/TODO command list as intent-level guidance, not as a narrower authority when it differs from CI.

The authoritative local validation should be a strict local mirror of the CI quality job and, where Docker/VNC is available, the desktop/native job. At minimum, before pushing, run:

```bash
cargo fetch --locked
cargo fmt --all --check
RUSTFLAGS=-Dwarnings cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
RUSTFLAGS=-Dwarnings cargo test --locked --workspace --all-features
RUSTDOCFLAGS=-Dwarnings cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n \
  desktop/entrypoint.sh \
  desktop/healthcheck.sh \
  desktop/xstartup \
  tests/desktop/run.sh \
  tests/native/run.sh \
  tests/worker-e2e/run.sh \
  tests/worker-text-clipboard-e2e/run.sh \
  tests/http-e2e/run.sh \
  controller/healthcheck.sh \
  tests/compose/run.sh \
  tests/integration/run.sh
```

Where local Docker/VNC resources are available, also run the same integration surfaces that CI runs:

```bash
tests/desktop/run.sh
bash tests/native/run.sh
bash tests/worker-e2e/run.sh
bash tests/worker-text-clipboard-e2e/run.sh
bash tests/http-e2e/run.sh
bash tests/compose/run.sh
bash tests/integration/run.sh
```

The `Makefile` is acceptable as a convenience wrapper for `fmt`, `lint`, `test`, and the integration targets, but if there is any mismatch between the Makefile and CI, CI wins. For this refactor, the best practice is to run the exact CI-equivalent commands above, because the previous failed attempt was caught by `cargo fmt --all --check` before Clippy or tests ran.

Do not mark the task complete based only on a narrower command set from the handoff spec.

## 2. Push and monitor sequence

Question:

> TODO F9–F12 call for pushing the final commit straight to `master` and polling exact-SHA CI/Release Gates to completion before marking this done. Should that push-and-monitor sequence happen automatically once local validation is green, or should implementation stop after local validation so the diff can be reviewed before it goes to `master`?

Answer:

Push to `master` automatically after local validation is green, then monitor exact-SHA CI and Release Gates to completion.

This is consistent with the current Ralph-loop workflow for this repository. Do not stop after local validation solely for a pre-push review unless one of the stop conditions below is hit.

Required pre-push checks:

1. Confirm the work is limited to the worker shutdown refactor, tests, and directly necessary docs/evidence updates.
2. Confirm `cargo fmt --all --check` passes.
3. Confirm Clippy/tests/doc/Python/shell checks pass using the CI-equivalent commands from Answer 1.
4. Confirm no broad scanner bypass, `continue-on-error`, gitleaks/VEX weakening, or quiet shutdown fallback was introduced.
5. Confirm the commit message clearly states the worker shutdown hardening scope.

After pushing:

1. Record the final exact SHA.
2. Poll CI for that exact SHA to completion.
3. Poll Release Gates for that exact SHA to completion.
4. If either fails, diagnose and fix the real failure; do not claim completion.
5. Only mark this handoff complete once both exact-SHA CI and Release Gates pass.

Stop before pushing only if the implementation discovers a material scope expansion or security/product decision not covered by the spec, such as changing the public HTTP API contract, weakening fail-closed behavior, changing authentication/authorization semantics, changing VNC exposure, removing current E2E coverage, or requiring a migration in deployment configuration. Formatting, test adjustments, local helper refactors, and implementation details inside the worker shutdown path do not require a pre-push stop as long as they satisfy the spec.

## 3. `WorkerCommand::Shutdown` retention

Question:

> Spec §5.5/TODO F5 leave `WorkerCommand::Shutdown` retention as implementer's discretion. The default plan is to keep it for the two e2e binaries' compatibility unless there's a preference for removing it now that the atomic flag is authoritative. Any preference, or is discretion fine?

Answer:

Keep `WorkerCommand::Shutdown` for now for compatibility with existing tests and E2E binaries, but make it non-authoritative.

The authoritative shutdown mechanism must be the out-of-band shutdown signal. The normal bounded command queue must never be required for shutdown progress.

Recommended semantics:

- `DesktopWorker::shutdown()` sets the out-of-band shutdown flag first.
- `Drop for DesktopWorker` sets the out-of-band shutdown flag first.
- `WorkerClient::submit()` rejects new non-shutdown commands after the flag is set with `DesktopError::WorkerUnavailable` or the existing shutdown-equivalent error mapping.
- `WorkerCommand::Shutdown`, if received by the worker loop, should also set or observe the same out-of-band shutdown flag and return a successful acknowledgement where possible.
- If shutdown was already requested before a queued `WorkerCommand::Shutdown` is processed, acknowledging it as shutdown-complete is fine.
- Failure to enqueue `WorkerCommand::Shutdown` must not matter for `DesktopWorker::shutdown()` or `Drop`.

Do not remove the enum variant in this pass. Removing it would expand the task into API/test compatibility cleanup and would risk distracting from the real bug: shutdown currently depends on normal queue capacity.

A later cleanup pass may remove `WorkerCommand::Shutdown` if all call sites, tests, E2E fixtures, and docs are deliberately migrated. That is out of scope for this refactor.

## 4. Additional implementation guidance

The target design should be boring and easy to prove:

- One shared out-of-band shutdown flag is acceptable.
- The flag must be checked in the worker loop before connection attempts, before processing ordinary commands, after processing commands, and around native poll/backoff waits.
- Because native connect/poll operations are bounded by existing timeouts, it is acceptable for shutdown responsiveness to be bounded by those timeouts, provided tests prove queue saturation cannot prevent eventual exit.
- Do not introduce a best-effort-only shutdown path that logs and proceeds to an unbounded join.
- Do not silently ignore cleanup failures from `release_all`; preserve the existing observable/logged failure behavior.
- Do not treat `TrySendError::Full` for the normal command queue as relevant to shutdown success.
- Add regression tests that would fail on the current implementation.

Minimum new tests expected:

1. Shutdown completes when the normal command queue is full.
2. `Drop` does not hang when the normal command queue is full.
3. Submitting ordinary commands after shutdown request is rejected explicitly.
4. Input cleanup/release behavior is preserved during shutdown.

The tests must not sleep indefinitely. Use bounded channels/timeouts in the tests so a regression fails quickly instead of hanging the test suite.

## 5. Completion criteria

Claude Code should only mark this complete when all of the following are true:

- The out-of-band shutdown mechanism is implemented and formatted.
- `WorkerCommand::Shutdown` is retained for compatibility but is no longer authoritative.
- Saturated-queue shutdown and drop tests exist and pass.
- Local CI-equivalent validation passes.
- The final commit is pushed to `master`.
- CI passes on the final exact SHA.
- Release Gates pass on the final exact SHA.
- The implementation notes or final evidence identify the final SHA and both validation run IDs.

If any exact-SHA validation fails, keep the TODO incomplete and fix the failure rather than documenting around it.
