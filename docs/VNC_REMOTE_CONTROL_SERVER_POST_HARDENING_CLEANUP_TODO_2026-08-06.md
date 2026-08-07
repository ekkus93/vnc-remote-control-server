# VNC Remote Control Server Post-Hardening Cleanup TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_SPEC_2026-08-06.md`

Implementation notes: `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_IMPLEMENTATION_NOTES_2026-08-06.md`

Baseline branch: `master`

Original reviewed baseline SHA: `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`

Cleanup starting SHA: `ce98c39a07b8577945ca65fd8d7067200c88ef1f`

Validated implementation SHA before cleanup-completion documentation: `1edc00be8b0909c86f069a217e2db8871cd93f75`

Status: implementation complete. Final closure requires CI and Release Gates to pass on this exact documentation-completion repository tip; those future run IDs are recorded externally after this commit exists rather than falsely embedded here.

---

## C0. Ground rules and baseline confirmation

- [x] Confirmed the working branch was `master`.
- [x] Confirmed the actual cleanup starting SHA before source edits.
- [x] `master` had advanced beyond the historical spec baseline because the cleanup spec/TODO themselves had been added; actual cleanup starting SHA is `ce98c39a07b8577945ca65fd8d7067200c88ef1f`.
- [x] Inspected the intervening documentation-only commits before editing.
- [x] Read the cleanup spec in full.
- [x] Read the prior post-correctness hardening TODO and implementation notes sufficiently to preserve accepted H1-H6 contracts.
- [x] Did not reopen the prior hardening TODO without evidence of regression.
- [x] Did not weaken CI, Release Gates, sanitizer gates, Gitleaks, ShellCheck, actionlint, Dockerfile/Compose checks, dependency policy, auditable-binary checks, Trivy, SBOM, or VEX gates.
- [x] Did not use `continue-on-error`, broad ignores, forced success, swallowed exit codes, force pushes, or older-SHA evidence.
- [x] Source work remained scoped to C1-C5 plus directly related compile/lint ownership repairs.

Acceptance:

- [x] Starting SHA is recorded in the evidence block below.
- [x] No unrelated feature work is mixed into this cleanup pass.
- [x] Prior accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, R13, CI, and Release Gates contracts are preserved.

---

## C1. Add repository-owned final evidence addendum for prior hardening loop

Target:

- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_FINAL_EVIDENCE_2026-08-06.md`

Completed:

- [x] Created the final evidence addendum.
- [x] Recorded final prior-hardening documentation-completion SHA `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`.
- [x] Recorded final prior-hardening CI run `31145131469`, conclusion `success`, exact head SHA `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`.
- [x] Recorded final prior-hardening Release Gates run `31145131453`, conclusion `success`, exact head SHA `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`.
- [x] Explained why the historical TODO could not embed its own future SHA/run IDs before those workflows existed.
- [x] Referenced the prior hardening TODO and implementation notes.
- [x] Did not claim unavailable local validation ran locally.
- [x] Did not rewrite historical evidence to imply future-run knowledge existed earlier.

Acceptance:

- [x] Repository contains final doc-tip SHA/run evidence from the prior hardening loop.
- [x] Addendum is evidence-only and does not alter accepted implementation evidence.

Do-not-accept verification:

- [x] No wrong run ID or mismatched SHA is used.
- [x] No claim says future workflow IDs were known before commit creation.
- [x] Older implementation-SHA runs are not substituted for final prior documentation-tip evidence.

---

## C2. Add live established-WebSocket EventHub sequence-exhaustion test

Sources:

- `crates/controller-api/src/events.rs`
- existing pre-upgrade HTTP/WebSocket tests

Completed:

- [x] Inspected and preserved the existing pre-upgrade `event_sequence_exhausted` coverage.
- [x] Preserved pre-upgrade `503 event_sequence_exhausted` behavior.
- [x] Preserved normal initial snapshot and event delivery.
- [x] Added `established_client_closes_on_sequence_exhaustion_with_bounded_1011`.
- [x] Production `EventHub::serve` and the deterministic test socket execute the same private `serve_socket` established-client branch.
- [x] The test establishes the subscription and receives the initial snapshot before forcing exhaustion.
- [x] The initial snapshot is proved payload-free before exhaustion is triggered.
- [x] Exhaustion is forced after establishment by moving the sequence to `u64::MAX` and triggering checked allocation failure.
- [x] No arbitrary or unbounded sleep is used; test synchronization uses bounded Tokio timeouts and the heartbeat wake-up.
- [x] Close code `1011` is required.
- [x] Close reason `event sequence exhausted` is required exactly.
- [x] Closure is required within a bounded interval.
- [x] Close reason and initial event assertions reject sensitive payload terminology.
- [x] Production `WebSocket` is boxed only inside the private production/test enum to satisfy strict `clippy::large_enum_variant`; no behavior or public contract changed.

Validation:

- [x] Full Rust workspace tests passed on exact implementation SHA.
- [x] Existing pre-upgrade exhaustion coverage passed.
- [x] Existing normal WebSocket/documentation contracts passed.
- [x] Strict Clippy passed without an allow/suppression.

Acceptance:

- [x] EventHub sequence exhaustion is regression-protected for both pre-upgrade and already-established clients.

Do-not-accept verification:

- [x] Test exercises established-client close behavior, not only `publish_test`.
- [x] Test does not depend on arbitrary long sleeps.
- [x] Test does not log or assert against sensitive command/clipboard/auth/framebuffer content.

---

## C3. Review and harden secret cloning

Sources:

- `crates/libvnc-adapter/src/lib.rs`
- `crates/controller-api/src/config.rs`
- `crates/controller-api/src/worker/settings.rs`
- `crates/controller-api/src/worker/desktop_worker.rs`
- `crates/controller-api/src/main.rs`
- `crates/controller-api/src/http/backend.rs`
- `crates/controller-api/src/http/state.rs`
- native/config contract tests

Completed:

- [x] Inventoried clone behavior for `SecretString`, `NativeClientConfig`, `WorkerSettings`, `ControllerConfig`, `ApiToken`, and test fixtures.
- [x] Determined `ApiToken` requires cheap handle cloning for router state; it remains `Arc<SecretString>` and does not duplicate token bytes.
- [x] Removed implicit `Clone` from `SecretString`.
- [x] Removed implicit `Clone` from `NativeClientConfig`.
- [x] Removed implicit `Clone` from `WorkerSettings`.
- [x] Removed implicit `Clone` from `ControllerConfig`.
- [x] Added the named `duplicate_native_config_for_reconnect_factory` boundary for the reconnect factory's required independently owned native config.
- [x] Strict Clippy exposed a second old `config.worker.clone()` call in `main.rs`; it was repaired structurally rather than restoring blanket cloning.
- [x] `ControllerConfig` is consumed in `main` and `WorkerSettings` moves into `DesktopWorker`.
- [x] Added `HttpWorkerSettings`, which carries HTTP-only values and no VNC password.
- [x] `WorkerHttpBackend` no longer accepts full secret-bearing controller config.
- [x] No secret-bearing type gained value-exposing `Debug` or `Display`.
- [x] Config Debug redaction still hides API token and VNC password.
- [x] Native connection/reconnect paths still receive required credentials.
- [x] Native contract test protects the named reconnect secret-duplication boundary.

Validation:

- [x] `cargo test --locked --workspace --all-features` equivalent permanent CI step passed.
- [x] Config redaction tests passed.
- [x] Native adapter tests/smoke passed.
- [x] Strict Clippy with warnings denied passed.

Acceptance:

- [x] No accidental/general-purpose production secret-byte clone capability remains on the reviewed secret-bearing config chain.
- [x] Required reconnect-factory duplication is explicit and documented.
- [x] API-token shared ownership remains `ApiToken -> Arc<SecretString>`.
- [x] Secret clone policy is explicit in code and implementation notes.

Do-not-accept verification:

- [x] Implicit `SecretString: Clone` was not retained.
- [x] API token was not changed back to raw `Arc<str>`/`String` ownership.
- [x] No secret value was added to debug/test logging.

---

## C4. Strengthen native clipboard scrub regression protection

Sources:

- `crates/libvnc-adapter/native/vnc_shim.c`
- `tests/test_native_contract.py`
- implementation notes

Completed:

- [x] Reviewed existing scrub coverage for release, replacement, outbound send copy, destruction, and revision overflow.
- [x] Determined post-free/allocator-reuse semantic inspection is unsafe/unreliable and explicitly prohibited by this cleanup contract.
- [x] Added one central `vrc_scrub_and_free` primitive that scrubs before `free`.
- [x] Stored clipboard release/replacement/destruction routes through the primitive via `vrc_release_clipboard`.
- [x] Outbound temporary send copies route through the same scrub-before-free primitive.
- [x] Shim-owned persistent VNC password destruction also uses the central primitive.
- [x] Clipboard revision overflow remains rejected before allocation/replacement.
- [x] Source-contract tests protect primitive ordering and all relevant call sites.
- [x] Tests do not log clipboard payloads.
- [x] No test claims third-party/OS/toolkit/allocator/LibVNCClient/server copies are scrubbed.
- [x] Existing WorkerHandle text/clipboard behavior is preserved.

Validation:

- [x] Native/source contract tests passed.
- [x] Native adapter smoke passed.
- [x] WorkerHandle text/clipboard E2E passed.
- [x] Authenticated HTTP and integration coverage passed.

Acceptance:

- [x] Project-owned native clipboard/sensitive cleanup has a centralized, fail-obvious regression guard without freed-memory testing.
- [x] Existing scrub ownership boundaries remain intact.

Do-not-accept verification:

- [x] No test reads freed memory.
- [x] No test depends on allocator reuse.
- [x] Clipboard payloads are not logged.
- [x] Scrub-before-free ordering remains enforced.

---

## C5. Audit temporary/recovery artifacts and policy pins

Completed:

- [x] Listed `.github/workflows/`; only permanent `ci.yml`, `publish-ci-status.yml`, and `release-gates.yml` remain.
- [x] Confirmed no temporary post-correctness recovery workflow remains active.
- [x] Confirmed no temporary post-correctness recovery/patcher script remains active under `.github/`.
- [x] Confirmed permanent workflow action pins remain immutable full SHAs.
- [x] Confirmed workflow-contract constants match the workflow action SHAs.
- [x] Confirmed Release Gates still run full-history Gitleaks.
- [x] Confirmed `.gitleaksignore` contains exact fingerprints only, with no wildcard/path/rule broad ignores.
- [x] Confirmed release-policy contract pins the exact accepted Gitleaks fingerprint set and forbids broad ignores.
- [x] Reviewed the remaining `POST_CORRECTNESS_HARDENING_RECOVERY_*` docs.
- [x] Classified the remaining recovery docs as accurate documentation-only historical evidence and retained them.
- [x] No active executable recovery machinery required deletion.

Validation:

- [x] Python workflow/release-policy contract tests passed.
- [x] ShellCheck/actionlint passed in Release Gates.
- [x] Full-history Gitleaks passed in Release Gates.

Acceptance:

- [x] Repository contains no active temporary recovery machinery.
- [x] Policy pins and exact false-positive handling remain fail closed.

Do-not-accept verification:

- [x] No broad Gitleaks ignore was introduced.
- [x] No workflow pin changed without corresponding contract coverage.
- [x] Useful historical recovery evidence was not removed merely because it mentions recovery.
- [x] No active temporary patcher workflow/script remains.

---

## C6. Documentation updates for this cleanup pass

Completed:

- [x] Documentation changes are limited to behavior/evidence actually changed by this cleanup.
- [x] Added the C1 prior-hardening final evidence addendum.
- [x] Added cleanup implementation notes documenting secret clone policy.
- [x] Implementation notes explain why a freed-memory semantic native test was not added and why the centralized source-contract guard is safer.
- [x] Did not duplicate the prior hardening TODO wholesale.
- [x] Preserved third-party/OS/toolkit/allocator/LibVNCClient/server/swap/crash-dump residual disclaimers.

Acceptance:

- [x] Documentation is accurate, scoped, and does not overclaim guarantees.

---

## C7. Local validation disposition

The ChatGPT execution environment could not obtain/use a normal local repository checkout because outbound GitHub DNS/direct network access was unavailable. Therefore none of the commands below are represented as locally passed. Their corresponding permanent workflow surfaces passed on exact implementation SHA `1edc00be8b0909c86f069a217e2db8871cd93f75`.

Repository-quality commands:

- [x] `cargo fetch --locked` — unavailable locally; exact-SHA CI dependency fetch succeeded.
- [x] `cargo fmt --all --check` — unavailable locally; exact-SHA CI formatting succeeded.
- [x] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings` — unavailable locally; exact-SHA strict Clippy succeeded.
- [x] `cargo test --locked --workspace --all-features` — unavailable locally; exact-SHA workspace tests succeeded.
- [x] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps` — unavailable locally; exact-SHA rustdoc succeeded.
- [x] `python -m compileall -q tools/ci_status tests desktop/test-app` — unavailable locally; exact-SHA Python compile succeeded.
- [x] `python -m unittest discover -s tests -p 'test_*.py' -v` — unavailable locally; exact-SHA Python/workflow contracts succeeded.
- [x] Permanent shell syntax checks — unavailable locally; exact-SHA CI succeeded.

Docker/VNC surfaces:

- [x] `tests/desktop/run.sh` — unavailable locally; exact-SHA desktop smoke succeeded.
- [x] `tests/native/run.sh` — unavailable locally; exact-SHA native smoke succeeded.
- [x] `tests/worker-e2e/run.sh` — unavailable locally; exact-SHA WorkerHandle input E2E succeeded.
- [x] `tests/worker-text-clipboard-e2e/run.sh` — unavailable locally; exact-SHA text/clipboard E2E succeeded.
- [x] `tests/http-e2e/run.sh` — unavailable locally; exact-SHA authenticated HTTP E2E succeeded.
- [x] `tests/compose/run.sh` — unavailable locally; exact-SHA Compose/persistence succeeded.
- [x] `tests/integration/run.sh` — unavailable locally; exact-SHA R13 integration succeeded.

- [x] Every unavailable local surface and reason is recorded.
- [x] No unavailable validation is labeled passed locally.

Acceptance:

- [x] All available source inspection/audit work completed.
- [x] Unavailable execution surfaces were explicitly deferred to and passed by exact-SHA permanent workflows.

---

## C8. Exact-SHA permanent validation

Validated implementation SHA:

`1edc00be8b0909c86f069a217e2db8871cd93f75`

- [x] Implementation changes were committed intentionally to `master` without force.
- [x] CI ran on the exact implementation SHA.
- [x] Release Gates ran on the exact implementation SHA.
- [x] CI run `31148063429` concluded `success` on exact SHA `1edc00be8b0909c86f069a217e2db8871cd93f75`.
  - [x] formatting;
  - [x] Clippy with warnings denied;
  - [x] full Rust workspace tests;
  - [x] rustdoc with warnings denied;
  - [x] Python compile and unittest/workflow contracts;
  - [x] shell syntax;
  - [x] desktop smoke;
  - [x] native adapter smoke;
  - [x] WorkerHandle input E2E;
  - [x] WorkerHandle text/clipboard E2E;
  - [x] authenticated HTTP E2E;
  - [x] Compose/persistence;
  - [x] R13 Compose integration/E2E.
- [x] Release Gates run `31148063423` concluded `success` on the same exact implementation SHA.
  - [x] static/supply-chain policy;
  - [x] full-history Gitleaks;
  - [x] ShellCheck/actionlint;
  - [x] Dockerfile/Compose validation;
  - [x] advisory/license/source/duplicate policy;
  - [x] auditable binary metadata verification;
  - [x] ASan;
  - [x] controller-api TSan;
  - [x] remote-desktop-core TSan;
  - [x] Miri;
  - [x] Trivy/SBOM/VEX.
- [x] Intermediate validation failures were repaired at root; no gate/assertion was weakened.
- [x] Older, red, superseded, canceled, or partial runs are not used as completion evidence.

Acceptance:

- [x] Same exact implementation SHA passed CI and Release Gates.

---

## C9. Final evidence and completion report

- [x] Implementation work was completed and exact-SHA validated before this TODO completion update.
- [x] Evidence block is filled below.
- [x] Added `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_IMPLEMENTATION_NOTES_2026-08-06.md`.
- [x] Documentation/evidence changes are committed intentionally and pushed without force.
- [x] This completion record explicitly requires exact-tip CI and Release Gates for the documentation-completion commit.
- [x] Final documentation-tip SHA/run IDs are recorded externally after this commit exists rather than pretending the commit can embed its own future SHA or run IDs.

Final evidence:

```text
Original reviewed baseline SHA:
59fe5363f5e37e92fbe47c45d3c883c91c8392c8

Cleanup starting SHA:
ce98c39a07b8577945ca65fd8d7067200c88ef1f

Validated implementation SHA before final documentation:
1edc00be8b0909c86f069a217e2db8871cd93f75

Implementation CI run:
31148063429 — success

Implementation Release Gates run:
31148063423 — success

Implementation-notes commit:
23045e6073fa4000cc4710ee19e143feadfe893e

Final documentation/evidence SHA:
This TODO completion commit; exact SHA is recorded externally after commit creation.

Final repository-tip SHA:
Same final documentation/evidence commit if its exact workflows require no repair; recorded externally.

C1 final evidence addendum:
Created repository-owned addendum recording prior hardening final SHA 59fe5363... with CI 31145131469 success and Release Gates 31145131453 success.

C2 established-WebSocket exhaustion test:
Same production established-client service branch is exercised through a deterministic test socket; initial snapshot must arrive first; post-establishment exhaustion must close 1011 with exact bounded reason.

C3 secret clone hardening:
Removed implicit Clone from SecretString/NativeClientConfig/WorkerSettings/ControllerConfig; ApiToken keeps Arc-only clone semantics; main now moves worker credentials instead of cloning them; reconnect duplicate is explicit/named.

C4 native clipboard scrub regression protection:
Central vrc_scrub_and_free owns scrub-before-free ordering for project-owned stored/outbound sensitive buffers; source contracts guard call sites; no unsafe freed-memory test.

C5 temporary/recovery artifact audit:
Only permanent workflows remain active; recovery docs retained as historical evidence; exact workflow pins and exact full-history Gitleaks fingerprint policy remain intact.

Local validation:
No normal local checkout/execution surface was available in the ChatGPT environment.

Unavailable local validation, with reasons:
Outbound GitHub DNS/direct network access was unavailable; Rust/Python/shell/Docker/VNC/Compose execution was deferred to permanent exact-SHA workflows. No unavailable command is labeled locally passed.

Deferred follow-ups:
No C1-C5 cleanup requirement is deferred. Third-party/OS/allocator residual-memory boundaries remain explicit non-guarantees.
```

Acceptance condition:

- [x] This TODO is complete only when the exact final documentation-completion repository tip is green in both CI and Release Gates. That condition is verified externally after commit creation.

---

## Final do-not-accept checklist

- [x] No older-SHA, canceled-run, superseded-run, or partial-run evidence is used for completion.
- [x] No CI or Release Gate is weakened, skipped, or converted to advisory-only.
- [x] No `continue-on-error`, broad ignore, forced success, swallowed exit code, or force push is used.
- [x] No WebSocket sequence exhaustion path can wrap, reuse, silently saturate, panic, or leave an established client indefinitely without the bounded close path.
- [x] No API bearer token returns to long-lived raw `Arc<str>` or equivalent ordinary string ownership.
- [x] No reviewed secret byte clone remains implicit and unexplained.
- [x] No secret type exposes values through `Debug` or `Display`.
- [x] No command payload, typed text, clipboard text, key name, coordinate, bearer token, VNC password, framebuffer byte, screenshot byte, or query secret is introduced into diagnostics/logs.
- [x] No native clipboard test reads freed memory or depends on allocator reuse.
- [x] No documentation claims third-party, OS, toolkit, allocator, VNC-server, LibVNCClient, reverse-proxy, swap, or crash-dump copies are scrubbed without evidence.
- [x] No `HttpBackend` command metric method silently defaults to zero.
- [x] No old queue-depth metric alias is reintroduced.
- [x] No active temporary patcher workflow or recovery script remains.
- [x] No broad Gitleaks ignore, path ignore, wildcard ignore, or rule suppression is introduced.
