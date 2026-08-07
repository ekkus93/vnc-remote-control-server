# VNC Remote Control Server Post-Hardening Cleanup TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_SPEC_2026-08-06.md`

Baseline branch: `master`

Baseline SHA: `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`

Status: not started.

---

## C0. Ground rules and baseline confirmation

- [ ] Confirm the current branch is `master`.
- [ ] Confirm the starting SHA before edits.
- [ ] If `master` still equals `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`, record that as the cleanup starting SHA.
- [ ] If `master` has advanced, record the actual starting SHA and inspect intervening changes before editing.
- [ ] Read the cleanup spec in full.
- [ ] Read the prior post-correctness hardening TODO and implementation notes enough to preserve accepted H1-H6 contracts.
- [ ] Do not reopen the prior hardening TODO unless source evidence proves a real regression.
- [ ] Do not weaken CI, Release Gates, sanitizer gates, Gitleaks, ShellCheck, actionlint, Dockerfile checks, Compose checks, cargo policy, auditable-binary checks, Trivy, SBOM, or VEX gates.
- [ ] Do not use `continue-on-error`, broad ignores, forced success, swallowed exit codes, force pushes, or older-SHA evidence.
- [ ] Keep the pass scoped to C1-C5 unless a compile/test failure requires a directly related fix.

Acceptance:

- [ ] Starting SHA is recorded in the final evidence block.
- [ ] No unrelated feature work is mixed into this cleanup pass.
- [ ] Prior accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, R13, CI, and Release Gates contracts are preserved.

---

## C1. Add repository-owned final evidence addendum for prior hardening loop

Target path:

- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_FINAL_EVIDENCE_2026-08-06.md`

Tasks:

- [ ] Create a short final evidence addendum for the completed post-correctness hardening loop.
- [ ] Record final documentation-completion SHA:
  - [ ] `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`
- [ ] Record final documentation-tip CI:
  - [ ] run ID `31145131469`;
  - [ ] conclusion `success`;
  - [ ] exact head SHA `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`.
- [ ] Record final documentation-tip Release Gates:
  - [ ] run ID `31145131453`;
  - [ ] conclusion `success`;
  - [ ] exact head SHA `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`.
- [ ] Explain why the original TODO did not embed these final run IDs before its own commit existed.
- [ ] Reference:
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md`;
  - [ ] `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_IMPLEMENTATION_NOTES_2026-08-06.md`.
- [ ] Do not claim unavailable local validation ran locally.
- [ ] Do not edit historical evidence to imply future-run knowledge existed before workflow completion.

Acceptance:

- [ ] The repository now contains the final doc-tip SHA/run evidence from the prior hardening loop.
- [ ] The addendum is factual, concise, and does not alter the accepted implementation evidence.

Do not accept:

- [ ] A doc that embeds wrong run IDs or omits exact SHA matching.
- [ ] A doc that says the final doc-tip runs were known before the doc-tip commit existed.
- [ ] A doc that uses older implementation-SHA runs as final documentation-tip evidence.

---

## C2. Add live established-WebSocket EventHub sequence-exhaustion test

Source targets:

- `crates/controller-api/src/events.rs`
- `crates/controller-api/src/http/handlers.rs`
- `crates/controller-api/src/http/tests/*`
- `docs/WEBSOCKET_EVENTS.md` only if test work exposes a documentation gap.

Tasks:

- [ ] Inspect the current pre-upgrade `event_sequence_exhausted` test.
- [ ] Preserve pre-upgrade `503 event_sequence_exhausted` behavior.
- [ ] Preserve normal WebSocket initial snapshot and event delivery.
- [ ] Add a live established-client test that exercises the same close branch used after WebSocket upgrade.
- [ ] The test must establish a client before exhaustion is triggered or observed.
- [ ] The test must prove the initial snapshot is delivered successfully before exhaustion close behavior.
- [ ] Force or trigger EventHub sequence exhaustion after establishment without relying on unbounded sleeps.
- [ ] Assert close code `1011`.
- [ ] Assert close reason `event sequence exhausted`.
- [ ] Assert closure occurs within a bounded heartbeat/wake-up interval.
- [ ] Assert no sensitive payload appears in the close reason, event body, or logs used by the test.
- [ ] If full router upgrade testing is too brittle, add the closest lower-level `EventHub::serve` test and document why that still exercises the production established-client branch.

Expected tests:

- [ ] New established-WebSocket sequence-exhaustion test fails if the `1011` close path is removed.
- [ ] New test fails if the close reason changes without corresponding test/doc updates.
- [ ] New test fails if established clients can hang indefinitely after sequence exhaustion.
- [ ] Existing pre-upgrade `event_sequence_exhausted` test still passes.
- [ ] Existing normal WebSocket delivery tests still pass.

Acceptance:

- [ ] EventHub exhaustion is protected for both pre-upgrade and already-upgraded WebSocket clients.

Do not accept:

- [ ] A test that only checks unit-level `publish_test` and never exercises established-client close behavior.
- [ ] A test that depends on long arbitrary sleeps instead of bounded synchronization/timeouts.
- [ ] A test that logs or asserts against typed text, clipboard text, key names, coordinates, tokens, passwords, framebuffer bytes, screenshot bytes, or query secrets.

---

## C3. Review and harden secret cloning

Source targets:

- `crates/libvnc-adapter/src/lib.rs`
- `crates/controller-api/src/config.rs`
- Native adapter/controller config tests as needed.

Tasks:

- [ ] Inventory every `Clone` implementation or derive involving secret-bearing types:
  - [ ] `SecretString`;
  - [ ] `NativeClientConfig`;
  - [ ] `ApiToken`;
  - [ ] `ControllerConfig`;
  - [ ] test secret fixtures.
- [ ] Identify whether production code requires cloning secret bytes or only cloning handles/config containers.
- [ ] Preserve `ApiToken` cheap clone semantics through shared ownership where needed for HTTP state.
- [ ] If production code does not need `SecretString: Clone`, remove the derive.
- [ ] If production code does need to duplicate secret bytes, replace implicit `Clone` with a named explicit method documenting why byte duplication is required.
- [ ] Ensure no secret type gains a value-exposing `Debug` implementation.
- [ ] Ensure no secret type gains a value-exposing `Display` implementation.
- [ ] Ensure config debug redaction still hides API token and VNC password values.
- [ ] Ensure native connection setup still receives the VNC password it needs.
- [ ] Adjust test fixtures so tests do not hide accidental production secret duplication.

Expected validation:

- [ ] `cargo test --locked --workspace --all-features` passes.
- [ ] Config redaction tests pass.
- [ ] Native adapter tests pass.
- [ ] Clippy with warnings denied passes.

Acceptance:

- [ ] There is no accidental or unexplained production clone of secret bytes.
- [ ] API token state still avoids long-lived ordinary plaintext string ownership.
- [ ] Secret clone policy is explicit in code or documentation.

Do not accept:

- [ ] Keeping implicit `SecretString: Clone` without documenting a production need.
- [ ] Replacing `Arc<SecretString>` API-token ownership with raw `Arc<str>`, `String`, or equivalent long-lived ordinary plaintext ownership.
- [ ] Adding debug/test output that prints secret values.

---

## C4. Strengthen native clipboard scrub regression protection

Source targets:

- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/native/vnc_shim.h` only if a test hook is added.
- `crates/libvnc-adapter/src/lib.rs` only if Rust-side test support is needed.
- `tests/test_native_contract.py`
- `tests/native/*` if semantic native coverage is practical.
- `SECURITY.md` or implementation notes only if test strategy needs explanation.

Tasks:

- [ ] Review current source-contract coverage for `vrc_release_clipboard`, `vrc_store_clipboard`, `vrc_client_send_clipboard`, and `vrc_client_destroy`.
- [ ] Decide whether a semantic native test hook is practical without exposing unsafe production API.
- [ ] If practical, add a test-only hook or native unit that verifies scrub-before-release/replacement/send-copy behavior without reading freed memory.
- [ ] If a semantic hook is not practical, document why allocator/freed-memory constraints make the source-contract test the safer guard.
- [ ] In either case, ensure the regression guard covers:
  - [ ] stored clipboard replacement scrub;
  - [ ] stored clipboard destruction scrub;
  - [ ] outbound temporary send-copy scrub before free;
  - [ ] clipboard revision overflow rejected before allocation/replacement.
- [ ] Ensure tests do not log clipboard payloads.
- [ ] Ensure tests do not claim third-party, OS, toolkit, allocator, LibVNCClient, or VNC-server copies are scrubbed.
- [ ] Preserve existing WorkerHandle text/clipboard E2E behavior.

Expected validation:

- [ ] Native/source contract tests pass.
- [ ] Native adapter smoke passes.
- [ ] WorkerHandle text/clipboard E2E passes.
- [ ] HTTP/privacy/integration tests pass.

Acceptance:

- [ ] Project-owned native clipboard scrub policy has the strongest practical regression guard without unsafe freed-memory testing.
- [ ] Existing scrub boundaries remain intact.

Do not accept:

- [ ] A test that reads freed memory.
- [ ] A test that depends on allocator reuse.
- [ ] Logging clipboard payloads in test output.
- [ ] Weakening `vrc_release_clipboard` or removing scrub-before-free ordering.

---

## C5. Audit temporary/recovery artifacts and policy pins

Source targets:

- `.github/`
- `.github/workflows/`
- `tests/test_workflow_contract.py`
- `tests/test_release_policy_contract.py`
- `.gitleaksignore`
- release-policy documentation
- `docs/`

Tasks:

- [ ] List `.github/workflows/` and confirm only permanent workflows remain.
- [ ] Confirm no temporary post-correctness recovery workflow remains active.
- [ ] Confirm no temporary post-correctness patcher script remains active under `.github/`.
- [ ] Confirm permanent workflow action pins remain immutable full SHAs.
- [ ] Confirm workflow-contract tests pin the same action SHAs used by workflows.
- [ ] Confirm Release Gates still run full-history Gitleaks.
- [ ] Confirm `.gitleaksignore` contains exact fingerprints only, not wildcard/path/rule broad ignores.
- [ ] Confirm release-policy contract pins the exact accepted Gitleaks ignore fingerprint set.
- [ ] Review recovery docs under `docs/` and classify them as historical/useful or stale/confusing.
- [ ] Delete only temporary executable machinery or clearly stale instructions.
- [ ] Do not delete useful historical evidence solely because it mentions recovery.

Expected validation:

- [ ] Python workflow/release-policy contract tests pass.
- [ ] ShellCheck/actionlint pass in Release Gates.
- [ ] Full-history Gitleaks passes in Release Gates.

Acceptance:

- [ ] Repository no longer contains active temporary recovery machinery.
- [ ] Policy pins and exact false-positive handling remain fail-closed.

Do not accept:

- [ ] Broad Gitleaks ignore rules.
- [ ] Workflow action pins changed without corresponding contract-test update.
- [ ] Removing historical docs that are still accurate and useful.
- [ ] Leaving active temporary patcher workflows/scripts in place.

---

## C6. Documentation updates for this cleanup pass

Tasks:

- [ ] Update documentation only for behavior/evidence that actually changes.
- [ ] Add the C1 final evidence addendum.
- [ ] If C3 changes secret clone policy, document the new policy briefly in implementation notes or security docs.
- [ ] If C4 keeps source-contract testing as the best practical guard, document why semantic native testing was not added.
- [ ] Avoid duplicating large sections of the prior hardening TODO.
- [ ] Preserve third-party/OS/allocator clipboard residual disclaimers.

Acceptance:

- [ ] Documentation is accurate, minimal, and does not overclaim guarantees.

---

## C7. Local validation

Run before pushing whenever available:

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`
- [ ] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [ ] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] Shell syntax checks for permanent scripts.

Where Docker/VNC are available:

- [ ] `tests/desktop/run.sh`
- [ ] `tests/native/run.sh`
- [ ] `tests/worker-e2e/run.sh`
- [ ] `tests/worker-text-clipboard-e2e/run.sh`
- [ ] `tests/http-e2e/run.sh`
- [ ] `tests/compose/run.sh`
- [ ] `tests/integration/run.sh`

- [ ] Record every unavailable local command and exact reason.
- [ ] Do not label unavailable validation as passed locally.

Acceptance:

- [ ] All available local checks pass.
- [ ] Unavailable surfaces are explicitly deferred to exact-SHA permanent workflows.

---

## C8. Exact-SHA permanent validation

- [ ] Commit implementation changes intentionally.
- [ ] Push to `master` without force.
- [ ] Record implementation SHA.
- [ ] Wait for CI on that exact SHA.
- [ ] Wait for Release Gates on that exact SHA.
- [ ] Confirm CI success across repository quality and integration surfaces:
  - [ ] formatting;
  - [ ] Clippy with warnings denied;
  - [ ] full Rust workspace tests;
  - [ ] rustdoc with warnings denied;
  - [ ] Python compile and unittest discovery;
  - [ ] workflow/release-policy/native/documentation contract tests;
  - [ ] shell syntax;
  - [ ] desktop smoke;
  - [ ] native adapter smoke;
  - [ ] WorkerHandle input E2E;
  - [ ] WorkerHandle text/clipboard E2E;
  - [ ] authenticated HTTP E2E;
  - [ ] Compose/persistence;
  - [ ] R13 Compose integration/E2E.
- [ ] Confirm Release Gates success across:
  - [ ] static/supply-chain policy;
  - [ ] full-history Gitleaks;
  - [ ] ShellCheck/actionlint;
  - [ ] Dockerfile/Compose validation;
  - [ ] advisory/license/source/duplicate policy;
  - [ ] auditable binary metadata verification;
  - [ ] ASan;
  - [ ] controller-api TSan;
  - [ ] remote-desktop-core TSan;
  - [ ] Miri boundary;
  - [ ] Trivy/SBOM/VEX.
- [ ] Repair root causes only; do not weaken gates or assertions.
- [ ] Do not use previous-SHA, canceled, superseded, or partial jobs as completion evidence.

Acceptance:

- [ ] Same exact final implementation tip passes CI and Release Gates.

---

## C9. Final evidence and completion report

- [ ] Complete this TODO only after exact-SHA validation.
- [ ] Fill the evidence block below.
- [ ] Add or update implementation notes if the cleanup changes are nontrivial.
- [ ] Commit documentation/evidence changes intentionally.
- [ ] Push without force.
- [ ] Wait for CI and Release Gates on the exact final documentation/evidence tip if a documentation commit follows implementation validation.
- [ ] Record external workflow run IDs; do not claim a commit embeds its own future hash or future workflow IDs.

Final evidence:

```text
Starting SHA:
Implementation SHA:
Final documentation/evidence SHA, if separate:
Final repository-tip SHA:
CI run ID and conclusion:
Release Gates run ID and conclusion:

C1 final evidence addendum:

C2 established-WebSocket exhaustion test:

C3 secret clone hardening:

C4 native clipboard scrub regression protection:

C5 temporary/recovery artifact audit:

Local validation:

Unavailable local validation, with reasons:

Deferred follow-ups:
```

Acceptance:

- [ ] This TODO is marked complete only after the exact final repository tip is green in CI and Release Gates.

---

## Final do-not-accept checklist

- [ ] No older-SHA, canceled-run, superseded-run, or partial-run evidence is used for completion.
- [ ] No CI or Release Gate is weakened, skipped, or converted to advisory-only.
- [ ] No `continue-on-error`, broad ignore, forced success, swallowed exit code, or force push is used.
- [ ] No WebSocket sequence exhaustion path can wrap, reuse, silently saturate, panic, or hang an established client indefinitely.
- [ ] No API bearer token returns to long-lived raw `Arc<str>` or equivalent ordinary string ownership.
- [ ] No secret byte clone remains implicit and unexplained if production duplication is not needed.
- [ ] No secret type exposes values through `Debug` or `Display`.
- [ ] No command payload, typed text, clipboard text, key name, coordinate, bearer token, VNC password, framebuffer byte, screenshot byte, or query secret is introduced into diagnostics/logs.
- [ ] No native clipboard test reads freed memory or depends on allocator reuse.
- [ ] No documentation claims third-party, OS, toolkit, allocator, VNC-server, LibVNCClient, reverse-proxy, swap, or crash-dump copies are scrubbed without evidence.
- [ ] No `HttpBackend` command metric method silently defaults to zero.
- [ ] No old queue-depth metric alias is reintroduced without an explicitly named external compatibility requirement.
- [ ] No active temporary patcher workflow or recovery script remains.
- [ ] No broad Gitleaks ignore, path ignore, wildcard ignore, or rule suppression is introduced.
