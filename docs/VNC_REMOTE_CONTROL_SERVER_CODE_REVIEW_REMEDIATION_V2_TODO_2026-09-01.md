# VNC Remote Control Server — Code Review Remediation V2 TODO

**Date:** 2026-09-01  
**Spec:** `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_SPEC_2026-09-01.md`  
**Reviewed baseline:** `2506686ecdd77ddbfcc106d0109d6f7198233808`  
**Working branch:** `ralph/code-review-remediation-v2-20260901`

This TODO is evidence-driven. A checkbox may be closed only when the corresponding source/test/workflow/evidence exists on the branch or final `master`. Green runs from an older SHA do not close exact-candidate tasks.

## V2-R0 — Baseline and preservation

- [x] Record reviewed baseline SHA `2506686ecdd77ddbfcc106d0109d6f7198233808`.
- [x] Create V2 branch from that exact baseline.
- [x] Record baseline Release Gates `33534939054` as green baseline evidence only.
- [x] Commit the V2 specification to the branch.
- [x] Commit this V2 TODO to the branch.
- [ ] Inventory all V2-changed files before candidate validation.
- [ ] Re-check bearer authentication remains mandatory for `/v1/*`.
- [ ] Re-check constant-time bearer comparison remains unchanged.
- [ ] Re-check API/VNC secrets remain file-backed and redacted.
- [ ] Re-check raw VNC remains isolated from external publication.
- [ ] Re-check command/event queues remain bounded.
- [ ] Re-check screenshot concurrency remains bounded.
- [ ] Re-check WebSocket client/message/frame bounds remain enforced.
- [ ] Re-check process shutdown remains bounded.
- [ ] Re-check accepted-command unknown-outcome semantics remain non-retry-safe.
- [ ] Confirm no existing release/security gate was weakened.

## V2-R1 — Authoritative remote-input uncertainty and session quarantine

### State model

- [ ] Replace pointer-only uncertainty with one aggregate input certainty state.
- [ ] Define explicit `Known` state.
- [ ] Define explicit `Uncertain` state.
- [ ] Ensure newly connected sessions start `Known`.
- [ ] Ensure `clear()` restores local state only when no reusable native session exists.
- [ ] Ensure `abandon()` records unresolved pointer/key cleanup state before clearing.

### Native send semantics

- [ ] Treat failed pointer movement send as ambiguous remote effect.
- [ ] Treat failed explicit button transition as ambiguous remote effect.
- [ ] Treat failed click move/press/release send as ambiguous remote effect.
- [ ] Treat failed second click path as ambiguous remote effect.
- [ ] Treat failed wheel press/release send as ambiguous remote effect.
- [ ] Treat failed key-down send as ambiguous remote effect.
- [ ] Treat failed key-up send as ambiguous remote effect.
- [ ] Treat failed chord press/release send as ambiguous remote effect.
- [ ] Treat failed typed-text press/release send as ambiguous remote effect.
- [ ] Do not infer non-delivery solely from `NativeError` without an explicit transport guarantee.

### Cleanup

- [ ] Keep cleanup bounded.
- [ ] Never replay the original caller mutation as cleanup.
- [ ] Remove successfully released local tracked state immediately.
- [ ] Keep failed releases observable until session abandonment.
- [ ] Do not silently discard a second failed release.
- [ ] Keep cleanup diagnostics payload-free.
- [ ] Preserve the original command failure if cleanup succeeds.
- [ ] Preserve the original command failure if cleanup fails.

### Worker quarantine

- [ ] Centralize post-command input-uncertainty handling in the worker.
- [ ] Detect uncertainty after every input command arm, not only scroll.
- [ ] Invalidate authoritative session state when input becomes uncertain.
- [ ] Drop the tainted VNC session before later mutations can execute.
- [ ] Abandon unresolved local input tracking only after the session is unusable.
- [ ] Schedule reconnect through the existing bounded reconnect state machine.
- [ ] Ensure the failed command is marked failed, not retried.
- [ ] Ensure a queued next mutation cannot run on the tainted session.
- [ ] Ensure replacement session starts with clean tracked input state.

### R1 tests

- [ ] Test failed pointer movement taints input state.
- [ ] Test failed button press taints input state.
- [ ] Test failed button release taints input state.
- [ ] Test click press failure taints input state.
- [ ] Test click release failure + cleanup success preserves original failure.
- [ ] Test click release double failure leaves uncertainty.
- [ ] Test double-click failure cannot leave reusable uncertain session.
- [ ] Test scroll release failure + cleanup success behavior.
- [ ] Test scroll double release failure quarantines session.
- [ ] Test key-down failure taints input state.
- [ ] Test key-up failure taints input state.
- [ ] Test partial chord failure + cleanup success.
- [ ] Test partial chord failure + cleanup failure quarantines session.
- [ ] Test typed-text key-up failure + cleanup success.
- [ ] Test typed-text double cleanup failure quarantines session.
- [ ] Test worker drops old session before processing next queued mutation.
- [ ] Test reconnect replacement restores normal input service.

## V2-R2 — Immutable GitHub Actions

- [x] Identify mutable permanent third-party Action reference.
- [x] Replace `dtolnay/rust-toolchain@stable` with immutable commit `4360b52568e2003a75bf9bc1d59f33a8e3fc893c`.
- [x] Keep Rust toolchain explicitly set to `1.97.1`.
- [x] Add generic workflow contract scanning `.yml` and `.yaml` files.
- [x] Permit only local `./...` Actions without a SHA.
- [x] Reject mutable third-party tags/branches/aliases.
- [x] Local release-policy contract suite passes for the new rule.
- [ ] Re-run actionlint on final candidate.
- [ ] Re-run complete workflow contract tests on final candidate.
- [ ] Prove immutable pins in exact-candidate Release Gates.
- [ ] Document the immutable Action policy in release/evidence docs.

## V2-R3 — Command outcome identity truthfulness

### Implementation

- [x] Move outcome-capacity reservation before sequence advancement.
- [x] Allocate the command ID while holding the outcome-registry reservation lock.
- [x] Ensure `CommandOutcomeCapacityFull` does not advance `next_command_id`.
- [x] Preserve sequence-exhaustion handling as fail-closed/fatal.
- [x] Preserve terminal-record eviction policy.
- [x] Preserve nonterminal-record no-eviction policy.
- [x] Preserve exact `Found` semantics.
- [x] Preserve exact `Expired` semantics for known evictions.
- [x] Preserve exact `Unknown` semantics for never-retained IDs.

### R3 tests

- [x] Add tiny-capacity regression proving capacity rejection does not advance sequence.
- [x] Assert the unconsumed next ID remains `Unknown` after capacity rejection.
- [x] Assert the same next ID is reserved normally once capacity is available.
- [x] Preserve existing terminal eviction -> `Expired` regression.
- [ ] Add/verify worker-client integration coverage for the failed-reservation gap.
- [ ] Verify authenticated HTTP command status reports corrected semantics.
- [ ] Verify OpenAPI contract remains accurate.
- [ ] Verify Python client behavior remains accurate.
- [ ] Run Rust unit/workspace tests for R3 on exact candidate.

## V2-R4 — Native framebuffer revision exhaustion

### Native boundary

- [ ] Add checked framebuffer revision advancement helper.
- [ ] Prevent `UINT64_MAX` wrap.
- [ ] Set machine-readable native callback failure on exhaustion.
- [ ] Preserve payload-free native diagnostic/error text.
- [ ] Ensure callback failure survives outer LibVNC message-handler success.
- [ ] Make `vrc_client_poll()` return non-success for framebuffer revision exhaustion.
- [ ] Add deterministic test hook/helper for forcing revision exhaustion.

### Rust mapping and worker recovery

- [ ] Add typed `NativeError` variant for framebuffer revision exhaustion.
- [ ] Map the native status code to that typed error.
- [ ] Classify it consistently in worker failure taxonomy.
- [ ] Invalidate current framebuffer authority on the poll failure.
- [ ] Invalidate/drop the native session.
- [ ] Schedule bounded reconnect.
- [ ] Ensure old framebuffer is unavailable before replacement connection succeeds.
- [ ] Ensure replacement framebuffer can become authoritative normally.

### R4 tests

- [ ] Native helper test: maximum-1 advances to maximum.
- [ ] Native helper test: maximum fails and does not wrap.
- [ ] Native poll test propagates callback exhaustion status.
- [ ] Rust adapter test maps exhaustion to typed error.
- [ ] Worker test proves stale framebuffer invalidation precedes reconnect success.
- [ ] Worker test proves recovery on replacement session.
- [ ] Update native source-contract test for the checked helper.

## V2-R5 — Explicit HTTP connection concurrency bound

### Configuration

- [ ] Add `VRC_HTTP_MAX_CONNECTIONS`.
- [ ] Define a documented default.
- [ ] Define nonzero minimum.
- [ ] Define finite maximum.
- [ ] Reject zero.
- [ ] Reject one-above-maximum.
- [ ] Reject malformed value.
- [ ] Reject non-Unicode configured value.
- [ ] Include the value in redaction-safe config Debug output if appropriate.

### Runtime

- [ ] Add process-owned connection semaphore/capacity primitive.
- [ ] Ensure each live connection task owns exactly one permit.
- [ ] Choose deterministic saturation behavior without unbounded helper tasks.
- [ ] Ensure permit survives until connection task genuinely exits.
- [ ] Release permit on clean close.
- [ ] Release permit on peer/runtime failure.
- [ ] Release permit on task cancellation/panic where applicable.
- [ ] Release permit through graceful shutdown.
- [ ] Preserve bounded shutdown while saturated.
- [ ] Do not let request/body timeout release a permit while connection cleanup is still running.

### R5 tests/docs

- [ ] Test exact configured maximum is admitted.
- [ ] Test one-over-limit behavior.
- [ ] Test permit recovery after clean disconnect.
- [ ] Test permit recovery after failure.
- [ ] Test cancellation/panic permit recovery where applicable.
- [ ] Test shutdown while all permits are held.
- [ ] Add practical R13/real-runtime saturation assertion if environment permits.
- [ ] Document `VRC_HTTP_MAX_CONNECTIONS` in operator/deployment docs.

## V2-R6 — Cross-cutting silent-failure/fallback audit

### Rust

- [ ] Search changed/adjacent Rust for `let _ =`.
- [ ] Search for `.ok()`.
- [ ] Search for ignored `Result` values.
- [ ] Search for broad wildcard error collapsing.
- [ ] Search for operational `unwrap_or*` fallback.
- [ ] Re-audit side-effecting remote-operation retries.
- [ ] Re-audit input cleanup retries.
- [ ] Re-audit stale framebuffer/clipboard fallback.
- [ ] Re-audit sequence/revision exhaustion.
- [ ] Re-audit detached task/thread handling.
- [ ] Re-audit mutex/RwLock poison handling.
- [ ] Re-audit ignored channel sends and exit notifications.
- [ ] Re-audit timeout paths that abandon work.

### Python/shell/workflows

- [ ] Search Python for broad exception swallowing.
- [ ] Search Python for silent compatibility fallbacks.
- [ ] Search shell for correctness-sensitive `|| true`.
- [ ] Search shell for correctness-sensitive `set +e`.
- [ ] Search workflows for `continue-on-error` in release-critical work.
- [x] Search workflows for mutable third-party Action references.
- [ ] Re-audit scanner/VEX/security bypasses.

### Additional defect found during R6

- [x] Stop silently discarding termination signal listener failure.
- [x] Log termination-listener failure with payload-safe error metadata.
- [x] Still perform bounded shutdown after listener failure.
- [x] Return process failure after cleanup rather than false success.
- [ ] Add/verify deterministic test coverage for termination-listener failure if practical.

### Surviving ignores

- [ ] Classify every surviving production ignore as terminal notification, post-invalidation cleanup, redundant non-authoritative wake-up, test-only behavior, or defect.
- [ ] Add nearby comments for non-obvious legitimate ignores.
- [ ] Add regression tests for non-obvious legitimate ignores when practical.
- [ ] Record the final audit summary in V2 evidence.

## V2-R7 — Documentation and evidence reconciliation

- [ ] Preserve prior V1 spec/TODO/evidence run IDs and SHAs.
- [ ] Add explicit V2 correction that V1 R9 fallback audit was incomplete for non-scroll input failures.
- [ ] State that V1 R14 evidence overstated that audit's completeness.
- [ ] State that V1 R15 final correctness claim is superseded by V2 findings without erasing historical validation.
- [ ] Update `README.md` if operator-visible behavior changes.
- [ ] Update `docs/OPERATOR_GUIDE.md` for input quarantine and HTTP connection cap.
- [ ] Update `deploy/README.md` for HTTP connection cap/configuration.
- [ ] Update release-policy documentation for immutable Actions.
- [ ] Update API/OpenAPI docs if any status wording changes.
- [ ] Update Python client docs if any status wording changes.
- [ ] Re-check `SECURITY.md` trust-boundary statements.
- [ ] Confirm new diagnostics never include typed text, clipboard payloads, credentials, or screenshots.
- [ ] Continue to state MCP is not implemented and remains gated on V2 sign-off.
- [ ] Create `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_EVIDENCE_2026-09-01.md`.

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
- [ ] full `unittest` suite.
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
- [ ] new input-taint/session-replacement integration path.
- [ ] new HTTP connection-capacity integration path where practical.

## V2-R9 — Exact candidate and merged-master validation

### Candidate

- [ ] Finish all in-scope implementation and documentation changes.
- [ ] Reconcile all pre-CI TODO boxes against actual branch source/tests.
- [ ] Record exact candidate SHA.
- [ ] Open focused PR against `master`.
- [ ] Require regular CI on exact candidate SHA.
- [ ] Record candidate CI run ID and conclusion.
- [ ] Require Release Gates on exact candidate SHA.
- [ ] Record candidate Release Gates run ID and conclusion.
- [ ] Inspect every failed job/step rather than blindly rerun.
- [ ] Fix root cause of any failure without weakening gates.
- [ ] Confirm both workflows are green on the same exact candidate generation.

### Merge and exact master

- [ ] Merge only after exact-candidate CI and Release Gates are green.
- [ ] Record exact merged `master` SHA.
- [ ] Require fresh regular CI on exact merged `master` SHA.
- [ ] Record final `master` CI run ID/conclusion.
- [ ] Require fresh Release Gates on exact merged `master` SHA.
- [ ] Record final `master` Release Gates run ID/conclusion.
- [ ] Re-review VEX status/expiry at final validation time.

## V2-R10 — Final evidence and sign-off

- [ ] Evidence records reviewed starting SHA.
- [ ] Evidence records candidate SHA.
- [ ] Evidence records merged implementation SHA.
- [ ] Evidence records candidate CI and Release Gates IDs/conclusions.
- [ ] Evidence records final `master` CI and Release Gates IDs/conclusions.
- [ ] Evidence lists all changed files.
- [ ] Evidence lists regression tests for every V2 finding.
- [ ] Evidence states exact input certainty/quarantine policy.
- [ ] Evidence states no tainted session can process later input.
- [ ] Evidence states original failed mutation is never automatically replayed.
- [ ] Evidence states exact `Unknown`/`Expired` policy.
- [ ] Evidence states native framebuffer exhaustion policy.
- [ ] Evidence states HTTP connection default/min/max and saturation behavior.
- [ ] Evidence proves permanent third-party Actions are immutable-SHA pinned.
- [ ] Evidence summarizes the complete fallback audit.
- [ ] Evidence explains every relevant surviving ignored production result.
- [ ] Evidence confirms no release-critical gate was weakened.
- [ ] Evidence records final VEX review status.
- [ ] Re-review every TODO checkbox against final source/tests/workflows/evidence.
- [ ] Confirm no checkbox is closed solely because a commit message says so.
- [ ] Confirm MCP remains deferred until this sign-off.
- [ ] Declare V2 complete only after all applicable R0-R10 requirements are genuinely satisfied.
