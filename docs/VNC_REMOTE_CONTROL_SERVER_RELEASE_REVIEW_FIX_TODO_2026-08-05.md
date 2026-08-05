# VNC Remote Control Server — Release Review Fix TODO

Date: 2026-08-05
Branch: `master`
Starting reviewed SHA: `309364caf5d44d316557aa585ad7d92d043b0a47`
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_SPEC_2026-08-05.md`

## Completion contract

This TODO is complete only when the final exact SHA passes both regular CI and Release Gates and the tasks below are either checked off with evidence or deliberately deferred with an explicit issue/reference.

This is a release-hardening fix pass. It does not reopen the completed R0-R16 v0.1 implementation unless a task below identifies a concrete defect in that implementation.

## F0 — Freeze current evidence and reproduce the release blocker

- [ ] Record the initial reviewed SHA: `309364caf5d44d316557aa585ad7d92d043b0a47`.
- [ ] Confirm CI run `31036432334` passed for the initial reviewed SHA.
- [ ] Confirm Release Gates run `31036432628` failed for the same initial reviewed SHA.
- [ ] Record that the failed Release Gates job was `Static and supply-chain policy`.
- [ ] Record that the failed step was `Scan complete Git history for secrets`.
- [ ] Download or inspect the static-policy evidence/logs needed to identify the exact Gitleaks finding.
- [ ] Add the Gitleaks finding summary to the final evidence document without exposing any real secret value.

Evidence target:

- `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_EVIDENCE_2026-08-05.md`

## F1 — Resolve the Gitleaks finding without broad bypass

- [ ] Classify the Gitleaks finding as one of:
  - [ ] true positive secret;
  - [ ] false positive;
  - [ ] synthetic/non-secret fixture.
- [ ] If true positive:
  - [ ] identify the affected credential type without copying the secret into docs/logs;
  - [ ] rotate or revoke the credential;
  - [ ] document the rotation/revocation evidence;
  - [ ] decide whether history rewrite is required or whether precise allowlisting plus rotation is sufficient;
  - [ ] document the chosen repository policy.
- [ ] If false positive:
  - [ ] add the narrowest possible `.gitleaks.toml` allowlist entry or equivalent supported config;
  - [ ] bind the allowlist to the exact fingerprint/commit/path/line/regex combination where possible;
  - [ ] include a rationale that explains why the value is not a secret.
- [ ] If synthetic fixture:
  - [ ] make the fixture unmistakably synthetic if it is not already;
  - [ ] prefer changing the fixture to avoid the scanner pattern;
  - [ ] add a narrow allowlist only if changing the fixture is not appropriate.
- [ ] Run Gitleaks locally or in CI and verify the full-history scan passes.
- [ ] Confirm no `continue-on-error`, broad path ignore, broad regex ignore, or full-history scan removal was introduced.
- [ ] Update evidence with the final Gitleaks resolution.

Do not mark this task complete if the scanner is merely disabled or made non-blocking.

## F2 — Redesign worker shutdown so it cannot be blocked by the normal command queue

- [ ] Inspect the current shutdown path in `crates/controller-api/src/worker.rs`:
  - [ ] `DesktopWorker::shutdown`;
  - [ ] `impl Drop for DesktopWorker`;
  - [ ] `WorkerClient::submit`;
  - [ ] `run_worker` command receive loop.
- [ ] Choose and document one shutdown design that cannot be blocked behind a full normal command queue:
  - [ ] separate lifecycle/control channel; or
  - [ ] atomic stop flag plus wake mechanism; or
  - [ ] reserved shutdown slot; or
  - [ ] deterministic sender-close termination; or
  - [ ] another explicitly bounded design.
- [ ] Implement the chosen design.
- [ ] Ensure `DesktopWorker::shutdown(timeout)` returns within a bounded duration even when normal commands are saturated.
- [ ] Ensure `Drop` never performs an unbounded join after shutdown submission fails or times out.
- [ ] Preserve best-effort input release before native session destruction when a session exists.
- [ ] Preserve `Stopped` transition for orderly shutdown.
- [ ] Ensure forced/abnormal shutdown does not report orderly success.
- [ ] Add tracing or status evidence for abnormal shutdown only if it does not leak secrets or payloads.

Suggested implementation note:

A separate lifecycle channel is probably the simplest design to reason about. Normal desktop commands remain bounded by `command_capacity`; lifecycle commands use a distinct path that cannot be starved by normal work items.

## F3 — Add saturated-queue shutdown regression tests

- [ ] Add a deterministic unit test that fills the normal command queue and then calls `DesktopWorker::shutdown(timeout)`.
- [ ] Assert shutdown returns before the timeout rather than hanging.
- [ ] Add a deterministic test or scoped-thread guard proving `Drop` of a saturated worker does not hang the test process.
- [ ] Verify tracked buttons/keys are released on orderly shutdown when a session exists.
- [ ] Verify abnormal/forced shutdown paths are distinguishable from orderly shutdown if the implementation has such a path.
- [ ] Ensure the tests do not depend on arbitrary long sleeps.
- [ ] Ensure the tests fail on the old implementation.

Preferred test location:

- `crates/controller-api/src/worker.rs` unit tests

Optional integration coverage:

- Add script-level coverage only if the unit tests cannot prove the lifecycle contract.

## F4 — Tighten controller builder image reproducibility

- [ ] Inspect `controller/Dockerfile` builder stage.
- [ ] Replace tag-only `rust:1.97.1-slim-trixie` with a digest-pinned reference, or document a deliberate deferral.
- [ ] If pinning:
  - [ ] record the selected image digest;
  - [ ] ensure the digest corresponds to the intended Rust version/base;
  - [ ] update the Dockerfile;
  - [ ] verify `docker buildx build --check --file controller/Dockerfile .` still passes;
  - [ ] verify Release Gates image build still passes.
- [ ] If deferring:
  - [ ] create or reference a tracking issue;
  - [ ] explain why digest pinning is not being done in this pass;
  - [ ] keep the release acceptance statement honest about the deferral.

Preferred outcome: pin the builder image by digest.

## F5 — Clarify or tighten secret-file permission policy

- [ ] Inspect `SystemSecretReader` in `crates/controller-api/src/config.rs`.
- [ ] Decide whether the accepted permission model is Docker-oriented or host-strict.
- [ ] If Docker-oriented:
  - [ ] document that read-only broad modes such as `0444` are accepted for Docker secret compatibility;
  - [ ] document that secret values must still come from trusted container secret mounts or protected host paths;
  - [ ] keep the existing test that accepts read-only secrets.
- [ ] If host-strict:
  - [ ] add a configuration distinction or deployment-mode distinction;
  - [ ] reject group/other-readable host-local secrets where appropriate;
  - [ ] update tests;
  - [ ] verify Docker Compose secrets still work or update deployment docs accordingly.
- [ ] Ensure config/debug/error output still never includes secret values.

Do not accidentally break the Compose deployment secret mounts without updating deployment docs and tests.

## F6 — Resolve WebSocket event sequence overflow policy

- [ ] Inspect `EventHub::event` in `crates/controller-api/src/events.rs`.
- [ ] Choose one policy:
  - [ ] fail closed on overflow;
  - [ ] mark event source fatal and stop publishing;
  - [ ] extract/test/document practical unreachability;
  - [ ] leave unchanged only with explicit evidence rationale.
- [ ] If changing behavior:
  - [ ] add a test for sequence overflow behavior;
  - [ ] ensure no repeated indistinguishable `u64::MAX` sequence stream is emitted silently.
- [ ] If documenting only:
  - [ ] add a concise rationale to the evidence document;
  - [ ] explain why this does not weaken the v0.1 release boundary.

Preferred outcome: explicit overflow handling rather than silent saturation.

## F7 — Re-run local and CI quality gates

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

- [ ] Push the fix commit(s) to `master`.
- [ ] Wait for regular CI on the final SHA.
- [ ] Confirm CI conclusion is success.
- [ ] Wait for Release Gates on the final SHA.
- [ ] Confirm Release Gates conclusion is success.
- [ ] Record final CI run ID.
- [ ] Record final Release Gates run ID.
- [ ] Confirm the final Release Gates includes:
  - [ ] ShellCheck;
  - [ ] actionlint;
  - [ ] Dockerfile checks;
  - [ ] Compose config checks;
  - [ ] cargo-deny;
  - [ ] full-history Gitleaks;
  - [ ] native sanitizer/Miri gates;
  - [ ] image vulnerability/SBOM gates;
  - [ ] exact CRITICAL VEX validation.
- [ ] Confirm no release-critical job has `continue-on-error` or equivalent broad bypass.

## F9 — Documentation and evidence update

- [ ] Create or update `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_EVIDENCE_2026-08-05.md`.
- [ ] Include:
  - [ ] final commit SHA;
  - [ ] initial failing Release Gates run ID;
  - [ ] final passing CI run ID;
  - [ ] final passing Release Gates run ID;
  - [ ] Gitleaks finding classification and resolution;
  - [ ] shutdown design summary;
  - [ ] new shutdown regression test names;
  - [ ] builder image pinning or deferral decision;
  - [ ] secret-file permission policy decision;
  - [ ] WebSocket sequence overflow decision;
  - [ ] explicit statement that no broad scanner bypass was added;
  - [ ] remaining deliberate deferrals, if any.
- [ ] Update this TODO with checked boxes and evidence references.
- [ ] Do not mark the pass complete until final exact-SHA CI and Release Gates are both green.

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
