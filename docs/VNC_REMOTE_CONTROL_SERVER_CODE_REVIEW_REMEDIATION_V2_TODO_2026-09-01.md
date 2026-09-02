# VNC Remote Control Server — Code Review Remediation V2 TODO

**Date:** 2026-09-01  
**Spec:** `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_SPEC_2026-09-01.md`  
**Evidence:** `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_EVIDENCE_2026-09-01.md`  
**Reviewed baseline:** `2506686ecdd77ddbfcc106d0109d6f7198233808`  
**Working branch:** `ralph/code-review-remediation-v2-20260901`

This TODO is evidence-driven. A checkbox is closed only when source, tests, workflow configuration, documentation, or recorded external validation actually proves it. Historical green runs do not close exact-candidate items. Named regression scenarios that do not yet have one-to-one tests remain open even when the implementation is structurally fail-closed.

## V2-R0 — Baseline and preservation

- [x] Record reviewed baseline SHA `2506686ecdd77ddbfcc106d0109d6f7198233808`.
- [x] Create V2 branch from that exact baseline.
- [x] Record baseline Release Gates `33534939054` as historical baseline evidence only.
- [x] Commit the V2 specification.
- [x] Commit this V2 TODO.
- [x] Inventory all V2-changed files before candidate validation.
- [x] Re-check bearer authentication remains mandatory for `/v1/*`.
- [x] Re-check constant-time bearer comparison remains unchanged.
- [x] Re-check API/VNC secrets remain file-backed and redacted.
- [x] Re-check raw VNC remains isolated from external publication.
- [x] Re-check command/event queues remain bounded.
- [x] Re-check screenshot concurrency remains bounded.
- [x] Re-check WebSocket client/message/frame bounds remain enforced.
- [x] Re-check process shutdown remains bounded.
- [x] Re-check accepted-command unknown-outcome semantics remain non-retry-safe.
- [x] Confirm no existing release/security gate was weakened by the V2 diff.

## V2-R1 — Authoritative remote-input uncertainty and session quarantine

### State model and send semantics

- [x] Replace pointer-only uncertainty with aggregate `Known` / `Uncertain` input state.
- [x] Newly created/replacement controller state starts `Known`.
- [x] `clear()` restores local state only for a non-reusable/absent old native session path.
- [x] `abandon()` records unresolved pointer/key cleanup state before clearing.
- [x] Failed pointer movement is treated as ambiguous remote effect.
- [x] Failed explicit button transition is treated as ambiguous remote effect.
- [x] Failed click/double-click native send is treated as ambiguous remote effect.
- [x] Failed wheel press/release is treated as ambiguous remote effect.
- [x] Failed key-down/key-up is treated as ambiguous remote effect.
- [x] Failed chord press/release/partial cleanup is treated as ambiguous remote effect.
- [x] Failed typed-text press/release/cleanup is treated as ambiguous remote effect.
- [x] No `NativeError` input send failure is interpreted as proof of non-delivery.

### Cleanup and quarantine

- [x] Cleanup is bounded and limited to neutralizing releases.
- [x] Original caller mutation is never replayed as cleanup.
- [x] Successfully released tracked state is removed immediately.
- [x] Failed releases remain represented in aggregate taint/tracked state until abandonment.
- [x] A second failed release is not treated as success or silently cleared; later quarantine cleanup/reporting still sees unresolved state.
- [x] Cleanup diagnostics are payload-free.
- [x] Original command failure remains authoritative whether cleanup succeeds or fails.
- [x] Post-command input uncertainty handling is centralized in `worker/run.rs`.
- [x] Aggregate uncertainty is checked after every ordinary input command, not only scroll.
- [x] Tainted session authority is invalidated before another command-loop iteration.
- [x] Old VNC session is dropped before unresolved local tracking is abandoned.
- [x] Bounded reconnect is scheduled through the existing worker state machine.
- [x] Failed command is marked failed and is never retried by the worker.
- [x] Replacement session/controller state is clean.
- [x] Remove obsolete scroll-only quarantine path.
- [x] Delete the temporary `input_compat.rs` compatibility fallback and module declaration.

### R1 regression coverage

- [x] Failed pointer movement taints input state.
- [x] Failed button press taints/tracks input state.
- [ ] Add a dedicated explicit `SetButton` release-failure regression.
- [ ] Add a dedicated click-press failure regression.
- [x] Click release failure + successful neutralizing retry preserves the original failure and taint.
- [ ] Add a dedicated click-release double-failure regression.
- [ ] Add a dedicated double-click second-sequence failure regression.
- [x] Scroll release failure + cleanup success leaves the session tainted.
- [x] Scroll double-release failure cannot make the session reusable.
- [x] Failed key-down is tracked and taints input state.
- [ ] Add a dedicated explicit key-up failure regression.
- [x] Partial chord failure + successful cleanup remains tainted.
- [ ] Add a dedicated partial-chord cleanup-failure regression.
- [x] Typed-text key-up failure + cleanup success remains tainted.
- [x] Typed-text double cleanup failure remains tracked until abandonment.
- [ ] Add a worker regression proving an already-queued next mutation cannot execute on the tainted generation.
- [x] Existing generation-tagged worker regression proves replacement-session input executes on a clean generation.

## V2-R2 — Immutable GitHub Actions

- [x] Identify mutable permanent `dtolnay/rust-toolchain@stable` reference.
- [x] Pin it to `4360b52568e2003a75bf9bc1d59f33a8e3fc893c`.
- [x] Keep Rust toolchain explicitly `1.97.1`.
- [x] Add generic `.yml` / `.yaml` workflow contract.
- [x] Permit local `./...` Actions without SHA.
- [x] Reject mutable third-party tags/branches/aliases.
- [x] Available local release-policy contract suite passed for the new rule.
- [x] Document immutable third-party Action policy in release documentation/evidence.
- [ ] Re-run actionlint on the exact candidate.
- [ ] Re-run complete workflow contract tests on the exact candidate.
- [ ] Prove immutable pins in exact-candidate Release Gates.

## V2-R3 — Command outcome identity truthfulness

### Implementation and semantic review

- [x] Check outcome capacity before sequence advancement.
- [x] Allocate command ID while holding the outcome-registry reservation lock.
- [x] `CommandOutcomeCapacityFull` does not consume `next_command_id`.
- [x] Preserve fail-closed sequence exhaustion.
- [x] Preserve terminal-record eviction and nonterminal no-eviction policy.
- [x] Preserve exact `Found` semantics.
- [x] Preserve `Expired` only for known retained/evicted IDs.
- [x] Preserve `Unknown` for never-retained IDs.
- [x] Review authenticated HTTP status mapping: no wire-format change required.
- [x] Review OpenAPI contract: existing unknown/expired contract remains accurate.
- [x] Review Python client semantics: no client wire-format change required.

### R3 tests

- [x] Tiny-capacity regression proves capacity rejection does not advance sequence.
- [x] Unconsumed next ID remains `Unknown`.
- [x] Same next ID reserves normally once terminal capacity becomes available.
- [x] Existing terminal eviction -> `Expired` regression remains present.
- [ ] Add/verify a worker-client integration regression for a real failed-reservation gap if practical.
- [ ] Run exact-candidate Rust/workspace/HTTP/Python suites.

## V2-R4 — Native framebuffer revision exhaustion

### Native/Rust implementation

- [x] Add checked framebuffer revision advancement helper.
- [x] Prevent `UINT64_MAX` wrap.
- [x] Set machine-readable `VRC_STATUS_FRAMEBUFFER_REVISION_EXHAUSTED` callback failure.
- [x] Preserve fixed payload-free native diagnostic text.
- [x] Callback failure survives outer LibVNC message-handler success.
- [x] `vrc_client_poll()` returns non-success on framebuffer revision exhaustion.
- [x] Add deterministic helper path for forced exhaustion.
- [x] Add typed Rust `NativeError::FramebufferRevisionExhausted`.
- [x] Map native status to typed Rust error.
- [x] Classify it explicitly in worker failure taxonomy.
- [x] Existing poll-error recovery invalidates framebuffer authority and drops session.
- [x] Existing poll-error recovery schedules bounded reconnect.
- [x] Old framebuffer becomes unavailable during invalidation before replacement authority.

### R4 tests

- [x] Native helper: maximum-1 advances to maximum.
- [x] Native helper: maximum fails and does not wrap.
- [x] Native poll propagates callback exhaustion status.
- [x] Rust adapter mapping is covered by typed status mapping/source tests.
- [x] Native source-contract test requires checked helper/status path.
- [ ] Add/identify one dedicated worker-level framebuffer-exhaustion recovery regression rather than relying only on generic poll-error recovery.
- [ ] Run exact-candidate native/Rust tests.

## V2-R5 — Explicit HTTP connection concurrency bound

### Configuration/runtime

- [x] Add `VRC_HTTP_MAX_CONNECTIONS`.
- [x] Default is `256`.
- [x] Minimum is `1`.
- [x] Maximum is `65536`.
- [x] Zero and one-above-maximum fail validation.
- [x] Malformed and non-Unicode configured values fail startup closed in the parser.
- [x] Runtime settings remain redaction-safe; the new value is non-secret numeric configuration.
- [x] Add process-owned Tokio semaphore.
- [x] Each admitted connection task owns exactly one permit for its full lifetime.
- [x] Saturation closes the newly accepted socket and spawns no extra task.
- [x] Permit lifetime includes clean/error/unwind/cancellation/shutdown task exit.
- [x] Request/body timeout cannot release the connection permit while the connection task remains alive.
- [x] Shutdown remains bounded at capacity.

### R5 tests/docs

- [ ] Add an explicit exact-maximum admission test.
- [x] Test one-over-live-limit saturation behavior.
- [x] Test permit recovery after a held connection exits.
- [x] Existing task-outcome coverage classifies clean/peer/runtime/panic/cancellation behavior.
- [x] Test shutdown while all permits are held.
- [ ] Add practical R13/real-runtime saturation assertion if the integration environment supports it.
- [x] Document `VRC_HTTP_MAX_CONNECTIONS` in `README.md`, operator guide, and deployment guide.

## V2-R6 — Cross-cutting silent-failure/fallback audit

### Rust / Python / shell / workflows

- [x] Search changed/adjacent Rust for `let _ =`, ignored `Result`s and `.ok()`.
- [x] Review wildcard error collapsing and operational `unwrap_or*` fallbacks.
- [x] Re-audit side-effecting input retries and cleanup retries.
- [x] Re-audit stale framebuffer/clipboard authority.
- [x] Re-audit sequence/revision exhaustion.
- [x] Re-audit detached task/thread handling and poison behavior.
- [x] Re-audit ignored channel sends/exit notifications and timeout-abandonment paths.
- [x] Search Python for broad exception swallowing/compatibility fallbacks.
- [x] Search shell for correctness-sensitive `|| true` and `set +e`.
- [x] Search workflows for release-critical `continue-on-error`.
- [x] Search workflows for mutable third-party Actions.
- [x] Re-audit scanner/VEX/security bypasses.

### Additional defect found during R6

- [x] Stop silently collapsing termination-listener failure into success.
- [x] Log termination-listener failure with payload-safe error metadata.
- [x] Still perform bounded shutdown after listener failure.
- [x] Return process failure after cleanup rather than false success.
- [ ] Add deterministic termination-listener failure test if a practical injectable seam is introduced.

### Surviving ignores

- [x] Classify surviving production ignores as terminal notification, post-authoritative completion delivery, post-invalidation cleanup, redundant non-authoritative wake-up, or diagnostic-only conversion.
- [x] Keep nearby rationale for non-obvious legitimate ignored results.
- [x] Record final pre-CI audit summary in V2 evidence.

## V2-R7 — Documentation and evidence reconciliation

- [x] Preserve prior V1 spec/TODO/evidence SHAs and run IDs.
- [x] Explicitly correct the V1 R9 fallback-audit overclaim.
- [x] State that V1 R14 evidence inherited that overclaim.
- [x] State that V1 R15 correctness sign-off is superseded for the V2 findings without erasing history.
- [x] Update top-level `README.md` for operator-visible V2 behavior.
- [x] Update `docs/OPERATOR_GUIDE.md` for input quarantine and HTTP connection cap.
- [x] Update `deploy/README.md` for HTTP connection cap/input quarantine.
- [x] Update release policy for immutable third-party Actions and current VEX date.
- [x] Review API/OpenAPI docs; no public status/schema change requires edits.
- [x] Review Python client/docs; no wire-format change requires edits.
- [x] Re-check `SECURITY.md` trust-boundary and VEX statements; no V2 edit required.
- [x] Confirm new diagnostics exclude typed text, clipboard payloads, credentials and screenshots.
- [x] Continue to state MCP is not implemented and remains gated on V2 sign-off.
- [x] Create `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_EVIDENCE_2026-09-01.md`.

## V2-R8 — Complete quality/regression gates

### Rust

- [ ] `cargo fmt --all --check`.
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`.
- [ ] `cargo test --locked --workspace --all-features`.
- [ ] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`.

### Python

- [ ] compileall first-party Python.
- [ ] Ruff.
- [ ] Pylint.
- [ ] mypy.
- [ ] full `unittest` suite on exact candidate.
- [x] Available local Python/workflow/documentation contract suite passed before first candidate publication.

### Shell/workflows/security

- [ ] repository `bash -n` set.
- [ ] ShellCheck.
- [ ] actionlint.
- [ ] cargo-deny advisories/bans/licenses/sources.
- [ ] full-history Gitleaks.
- [ ] auditable release-binary verification.
- [ ] Dockerfile BuildKit checks.
- [ ] Compose config validation.
- [ ] ASan.
- [ ] TSan controller concurrency tests.
- [ ] TSan core shared-state tests.
- [ ] Miri.
- [ ] Trivy vulnerability inventories.
- [ ] CycloneDX SBOM generation.
- [ ] exact CRITICAL VEX enforcement.

### Integration/E2E

- [ ] desktop image smoke.
- [ ] native adapter smoke.
- [ ] WorkerHandle input E2E.
- [ ] WorkerHandle text/clipboard E2E.
- [ ] authenticated HTTP E2E.
- [ ] Compose/persistence smoke.
- [ ] R13 integration/reconnect/resource validation.
- [ ] input-taint/session-replacement integration path beyond unit/generation regression, if required by review.
- [ ] HTTP connection-capacity integration path beyond Tokio runtime tests, if practical.

## V2-R9 — Exact candidate and merged-master validation

### Candidate

- [x] Finish in-scope implementation and living-document changes for the six V2 findings.
- [x] Reconcile pre-CI TODO boxes against actual branch source/tests/evidence.
- [ ] Record exact frozen candidate SHA externally after this reconciliation commit.
- [ ] Open focused PR against `master`.
- [ ] Require regular CI on exact candidate SHA.
- [ ] Record candidate CI run ID and conclusion.
- [ ] Require Release Gates on exact candidate SHA.
- [ ] Record candidate Release Gates run ID and conclusion.
- [ ] Inspect every failed job/step rather than blindly rerun.
- [ ] Fix root cause of any failure without weakening gates.
- [ ] Confirm both workflows are green on the same exact candidate generation.

### Merge and exact master

- [ ] Merge only after exact-candidate CI and Release Gates are green and remaining acceptance-test debt is resolved/explicitly adjudicated.
- [ ] Record exact merged `master` SHA.
- [ ] Require fresh regular CI on exact merged `master` SHA.
- [ ] Record final `master` CI run ID/conclusion.
- [ ] Require fresh Release Gates on exact merged `master` SHA.
- [ ] Record final `master` Release Gates run ID/conclusion.
- [ ] Re-review VEX status/expiry at final validation time.

## V2-R10 — Final evidence and sign-off

### Already recorded in V2 evidence

- [x] Reviewed starting SHA and historical V1 validation provenance.
- [x] Pre-candidate changed-file inventory.
- [x] Input certainty/quarantine policy and no automatic replay rule.
- [x] Exact command `Unknown` / `Expired` policy.
- [x] Native framebuffer exhaustion policy.
- [x] HTTP connection default/min/max and saturation behavior.
- [x] Immutable third-party Action policy.
- [x] Pre-CI fallback audit and surviving ignored-result rationale.
- [x] Confirmation that no release-critical gate was intentionally weakened.
- [x] Current VEX review date (`2026-08-31`) and expiry (`2026-09-30`).
- [x] MCP remains deferred until V2 sign-off.

### Pending external/final evidence

- [ ] Record exact candidate SHA and PR number.
- [ ] Record candidate CI and Release Gates IDs/conclusions.
- [ ] Record exact merged implementation/master SHA.
- [ ] Record final master CI and Release Gates IDs/conclusions.
- [ ] Update final changed-file inventory after all candidate fixes, if any.
- [ ] Re-review every open named regression requirement and either add the test or document an explicit reviewed equivalence/non-applicability decision.
- [ ] Re-review every TODO checkbox against final source/tests/workflows/evidence.
- [ ] Confirm no checkbox is closed solely because a commit message says so.
- [ ] Declare V2 complete only after all applicable R0-R10 requirements are genuinely satisfied.