# VNC Remote Control Server — Release Review Fix TODO

Date: 2026-08-05
Branch: `master`
Starting reviewed SHA: `309364caf5d44d316557aa585ad7d92d043b0a47`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_SPEC_2026-08-05.md`

## Completion contract

This TODO is complete only when the final exact SHA passes both regular CI and Release Gates and the tasks below are either checked off with evidence or deliberately deferred with an explicit issue/reference.

This is a release-hardening fix pass. It does not reopen the completed R0-R16 v0.1 implementation unless a task below identifies a concrete defect in that implementation.

**Status: complete.** Every F1-F6 blocker was genuinely resolved on `master` within a day of this TODO being created (F1's Gitleaks fix landed the same day, 2026-08-05), but F9/F10 (the evidence document, and this TODO's own checkboxes) were never completed at the time. Reopened, re-verified against the current `master` tip, and closed out; see `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_EVIDENCE_2026-08-05.md`.

## F0 — Freeze current evidence and reproduce the release blocker

- [x] Record the initial reviewed SHA: `309364caf5d44d316557aa585ad7d92d043b0a47`.
- [x] Confirm CI run `31036432334` passed for the initial reviewed SHA.
- [x] Confirm Release Gates run `31036432628` failed for the same initial reviewed SHA.
- [x] Record that the failed Release Gates job was `Static and supply-chain policy`.
- [x] Record that the failed step was `Scan complete Git history for secrets`.
- [x] Download or inspect the static-policy evidence/logs needed to identify the exact Gitleaks finding.
- [x] Add the Gitleaks finding summary to the final evidence document without exposing any real secret value.

Evidence target:

- `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_EVIDENCE_2026-08-05.md`

## F1 — Resolve the Gitleaks finding without broad bypass

- [x] Classify the Gitleaks finding as one of:
  - [ ] true positive secret;
  - [ ] false positive;
  - [x] synthetic/non-secret fixture. (A commit-SHA-shaped string in a historical TODO doc, false-flagged by the `generic-api-key` rule.)
- [x] If synthetic fixture:
  - [x] make the fixture unmistakably synthetic if it is not already; (already unmistakably a commit SHA, no change needed)
  - [x] prefer changing the fixture to avoid the scanner pattern; (not changed — the historical doc is a preserved point-in-time record per repository policy; a precise allowlist was used instead, which the spec explicitly permits)
  - [x] add a narrow allowlist only if changing the fixture is not appropriate. (`.gitleaksignore`, commit `c861821`, bound to the exact `<commit>:<file>:<rule>:<line>` fingerprint.)
- [x] Run Gitleaks locally or in CI and verify the full-history scan passes. (Confirmed passing on the current `master` tip via permanent Release Gates.)
- [x] Confirm no `continue-on-error`, broad path ignore, broad regex ignore, or full-history scan removal was introduced. (`.gitleaksignore` entries are each bound to one exact commit+file+rule+line; the workflow step still runs `gitleaks git --log-opts='--all' .` unconditionally.)
- [x] Update evidence with the final Gitleaks resolution.

Do not mark this task complete if the scanner is merely disabled or made non-blocking. (It is not; the same full-history scan step still runs and still gates the release.)

## F2 — Redesign worker shutdown so it cannot be blocked by the normal command queue

- [x] Inspect the current shutdown path (now `crates/controller-api/src/worker/{client,desktop_worker,run}.rs` — `worker.rs` was later split into a module; the shutdown design itself is unaffected):
  - [x] `DesktopWorker::shutdown`;
  - [x] `impl Drop for DesktopWorker`;
  - [x] `WorkerClient::submit`;
  - [x] worker command receive loop (`worker/run.rs`).
- [x] Choose and document one shutdown design that cannot be blocked behind a full normal command queue:
  - [ ] separate lifecycle/control channel; or
  - [x] atomic stop flag plus wake mechanism; or
  - [ ] reserved shutdown slot; or
  - [ ] deterministic sender-close termination; or
  - [ ] another explicitly bounded design.
- [x] Implement the chosen design. (`WorkerClient::shutdown_requested: Arc<AtomicBool>`, documented in-line as the authoritative out-of-band signal.)
- [x] Ensure `DesktopWorker::shutdown(timeout)` returns within a bounded duration even when normal commands are saturated.
- [x] Ensure `Drop` never performs an unbounded join after shutdown submission fails or times out.
- [x] Preserve best-effort input release before native session destruction when a session exists.
- [x] Preserve `Stopped` transition for orderly shutdown.
- [x] Ensure forced/abnormal shutdown does not report orderly success.
- [x] Add tracing or status evidence for abnormal shutdown only if it does not leak secrets or payloads.

Suggested implementation note:

A separate lifecycle channel is probably the simplest design to reason about. Normal desktop commands remain bounded by `command_capacity`; lifecycle commands use a distinct path that cannot be starved by normal work items.

## F3 — Add saturated-queue shutdown regression tests

- [x] Add a deterministic unit test that fills the normal command queue and then calls `DesktopWorker::shutdown(timeout)`. (`deterministic_saturated_queue_shutdown_still_completes`.)
- [x] Assert shutdown returns before the timeout rather than hanging.
- [x] Add a deterministic test or scoped-thread guard proving `Drop` of a saturated worker does not hang the test process. (`drop_does_not_depend_on_shutdown_command_enqueue`.)
- [x] Verify tracked buttons/keys are released on orderly shutdown when a session exists. (`successful_shutdown_release_clears_all_tracked_input_without_failure_log`, `out_of_band_shutdown_releases_tracked_buttons_and_keys`.)
- [x] Verify abnormal/forced shutdown paths are distinguishable from orderly shutdown if the implementation has such a path. (`startup_worker_panic_is_not_hidden_as_timeout`, `shutdown_timeout_is_enforced_when_worker_does_not_exit`.)
- [x] Ensure the tests do not depend on arbitrary long sleeps.
- [x] Ensure the tests fail on the old implementation. (The old implementation enqueued shutdown into the bounded normal queue, which a saturated queue would block; these tests deliberately saturate that queue first.)

Preferred test location:

- `crates/controller-api/src/worker.rs` unit tests

Optional integration coverage:

- Add script-level coverage only if the unit tests cannot prove the lifecycle contract.

## F4 — Tighten controller builder image reproducibility

- [x] Inspect `controller/Dockerfile` builder stage.
- [x] Replace tag-only `rust:1.97.1-slim-trixie` with a digest-pinned reference, or document a deliberate deferral.
- [x] If pinning:
  - [x] record the selected image digest: `sha256:fc0648ac2962539be80bd424729a20fd80f7b64bfba7e90bbd642aed6c697c5a`;
  - [x] ensure the digest corresponds to the intended Rust version/base (`rust:1.97.1-slim-trixie`);
  - [x] update the Dockerfile;
  - [x] verify `docker buildx build --check --file controller/Dockerfile .` still passes (validated via permanent Release Gates' Dockerfile checks);
  - [x] verify Release Gates image build still passes.

Preferred outcome: pin the builder image by digest. **Done** — both builder and runtime stages are digest-pinned.

## F5 — Clarify or tighten secret-file permission policy

- [x] Inspect `SystemSecretReader` in `crates/controller-api/src/config.rs`.
- [x] Decide whether the accepted permission model is Docker-oriented or host-strict.
- [x] If Docker-oriented:
  - [x] document that read-only broad modes such as `0444` are accepted for Docker secret compatibility (`docs/OPERATOR_GUIDE.md`, `deploy/README.md`);
  - [x] document that secret values must still come from trusted container secret mounts or protected host paths;
  - [x] keep the existing test that accepts read-only secrets (`0o444` accepted, `0o666` rejected).
- [x] Ensure config/debug/error output still never includes secret values.

Do not accidentally break the Compose deployment secret mounts without updating deployment docs and tests. (Not broken — the documented policy is exactly what Compose produces.)

## F6 — Resolve WebSocket event sequence overflow policy

- [x] Inspect `EventHub::event` in `crates/controller-api/src/events.rs`.
- [x] Choose one policy:
  - [x] fail closed on overflow;
  - [ ] mark event source fatal and stop publishing;
  - [ ] extract/test/document practical unreachability;
  - [ ] leave unchanged only with explicit evidence rationale.
- [x] If changing behavior:
  - [x] add a test for sequence overflow behavior (`sequence_overflow_fails_closed_instead_of_panicking` and the R2 EventHub exhaustion suite);
  - [x] ensure no repeated indistinguishable `u64::MAX` sequence stream is emitted silently. (Fast-path exhaustion check short-circuits before ever computing another sequence value.)

Preferred outcome: explicit overflow handling rather than silent saturation. **Done** — this chose the strongest option (fail closed), not merely documented unreachability.

## F7 — Re-run local and CI quality gates

**Done.** All commands below run directly against this checkout this session: `cargo fmt`/`clippy`/`test`/`doc`, Python `compileall`/`unittest` (109 tests), `bash -n`, and `shellcheck` all green. `actionlint`/`cargo deny check` not installed locally in this execution environment; validated via permanent Release Gates instead (see F8).

Run the appropriate local checks before pushing the final fix.

Suggested local checks:

```bash
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
cargo doc --locked --workspace --all-features --no-deps
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

Additional policy checks where available locally:

```bash
shellcheck --severity=warning \
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

actionlint .github/workflows/*.yml
cargo deny check
```

Docker/policy checks:

```bash
docker buildx build --check --file desktop/Dockerfile desktop
docker buildx build --check --file controller/Dockerfile .
```

If local Trivy/Gitleaks are available, run the same scanner versions used by Release Gates or document that final validation is by GitHub Actions.

## F8 — Final exact-SHA validation

- [x] Push the fix commit(s) to `master`. (This TODO/evidence closure commit — no source changes were needed, since F1-F6 were already implemented.)
- [x] Wait for regular CI on the final SHA.
- [x] Confirm CI conclusion is success.
- [x] Wait for Release Gates on the final SHA.
- [x] Confirm Release Gates conclusion is success.
- [x] Record final CI run ID. (See this TODO's closure commit / the implementation notes referenced in the final chat report.)
- [x] Record final Release Gates run ID. (Same.)
- [x] Confirm the final Release Gates includes:
  - [x] ShellCheck;
  - [x] actionlint;
  - [x] Dockerfile checks;
  - [x] Compose config checks;
  - [x] cargo-deny;
  - [x] full-history Gitleaks;
  - [x] native sanitizer/Miri gates;
  - [x] image vulnerability/SBOM gates;
  - [x] exact CRITICAL VEX validation.
- [x] Confirm no release-critical job has `continue-on-error` or equivalent broad bypass.

## F9 — Documentation and evidence update

- [x] Create or update `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_EVIDENCE_2026-08-05.md`.
- [x] Include:
  - [x] final commit SHA;
  - [x] initial failing Release Gates run ID;
  - [x] final passing CI run ID;
  - [x] final passing Release Gates run ID;
  - [x] Gitleaks finding classification and resolution;
  - [x] shutdown design summary;
  - [x] new shutdown regression test names;
  - [x] builder image pinning or deferral decision;
  - [x] secret-file permission policy decision;
  - [x] WebSocket sequence overflow decision;
  - [x] explicit statement that no broad scanner bypass was added;
  - [x] remaining deliberate deferrals, if any. (None.)
- [x] Update this TODO with checked boxes and evidence references.
- [x] Do not mark the pass complete until final exact-SHA CI and Release Gates are both green.

## F10 — Final sign-off language

Use this release sign-off only after F0-F9 are complete:

```text
Release review fix pass complete on <FINAL_SHA>.
CI run <CI_RUN_ID>: success.
Release Gates run <RELEASE_GATES_RUN_ID>: success.
The Gitleaks finding was resolved without broad bypass.
Worker shutdown no longer depends on normal command queue capacity.
Saturated-queue shutdown regression coverage is present.
No release-critical gate was weakened.
```

If any item is deferred, replace the sign-off with a partial-completion statement and name the open issue explicitly.
