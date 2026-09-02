# VNC Remote Control Server — Code Review Remediation V2 Evidence

**Date:** 2026-09-01  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Reviewed baseline:** `2506686ecdd77ddbfcc106d0109d6f7198233808`  
**Working branch:** `ralph/code-review-remediation-v2-20260901`  
**Pre-evidence source/documentation head:** `165a5bc897b9e8810b8d1e9af067e7ce14802e86`  
**Exact candidate SHA:** pending pre-CI TODO reconciliation and PR freeze  
**Candidate CI / Release Gates:** pending  
**Merged master / final master gates:** pending

This file is cumulative V2 evidence. It intentionally does not treat a historical green workflow as proof for a newer candidate. The exact frozen candidate SHA and its workflow run IDs are authoritative only after the final pre-CI TODO reconciliation commit and PR creation.

## 1. Historical baseline preserved, not reused as V2 proof

The V1 remediation remains historical evidence:

- implementation SHA `1cb79d34f0023fc5da429ff3b60c71085224fa4e`;
  - CI `33516207959`: success;
  - Release Gates `33516208137`: success;
- V1 documentation closeout SHA `2506686ecdd77ddbfcc106d0109d6f7198233808`;
  - CI `33534939019`: success;
  - Release Gates `33534939054`: success.

V2 starts from exact baseline `2506686ecdd77ddbfcc106d0109d6f7198233808`. None of the four V1 runs above closes a V2 exact-candidate gate.

### V1 correction

The later independent V2 review found that the V1 R9 fallback audit was incomplete for non-scroll native input failures. V1 correctly hardened the scroll double-release path, but other pointer/key failure paths could still leave remote input state ambiguous while the same VNC session remained reusable. Therefore:

- the V1 R9 claim that the changed/adjacent silent-failure and side-effect retry audit was complete was overstated;
- the V1 R14 evidence inherited that overstatement;
- the V1 R15 final correctness sign-off is superseded by this V2 remediation for those findings.

This correction does not erase or rewrite the historical V1 run IDs, SHAs, or the fixes that were genuinely validated there.

## 2. V2-R1 — Aggregate input uncertainty and session quarantine

`InputController` now has one aggregate `InputState::{Known, Uncertain}`. All native pointer and key sends flow through controller-owned helpers that set `Uncertain` on any `NativeError`. The implementation does not infer that a failed native write had no remote effect.

The controller conservatively tracks state needed for neutralization:

- a failed button press retains the possibly pressed bit;
- a failed key-down is tracked before the native send;
- failed releases remain tracked;
- successfully neutralized tracked state is removed immediately;
- `release_all()` is bounded;
- `abandon()` clears unresolved local tracking only after the worker has made the old native session unusable;
- cleanup success does not restore `Known` on the old session.

Immediate release retries for click, wheel and typed-text paths are bounded and idempotent. A retry failure is not treated as success: aggregate uncertainty remains set and unresolved key/button state remains tracked where applicable. The worker's quarantine cleanup then produces payload-free aggregate release diagnostics (`worker_input_release_incomplete` / `worker_input_release_abandoned`) when neutralization remains incomplete. The original command error remains the caller-visible result regardless of cleanup success or failure.

The worker quarantine decision is centralized in `worker/run.rs` after ordinary command execution. If `input_state_uncertain()` is true, the worker:

1. emits payload-free `worker_input_session_tainted` with command ID;
2. calls `invalidate()`;
3. `invalidate()` attempts bounded tracked-input release while the session still exists;
4. drops the VNC session;
5. abandons any unresolved local input tracking only after the session is no longer reusable;
6. invalidates framebuffer/clipboard authority;
7. schedules bounded reconnect;
8. only then continues the command loop.

The command outcome is recorded from the original command `result`; quarantine never replays the original mutation and does not replace the original failure with cleanup success.

The obsolete V1 scroll-only uncertainty handling has been removed from `loop_state.rs`. A temporary compatibility shim created during the V2 refactor was also deleted before candidate freeze; there is no inert compatibility fallback remaining.

### R1 regression coverage present before candidate CI

Controller unit coverage includes:

- failed pointer send taints the session;
- failed explicit button press is tracked and taints the session;
- failed click release with successful bounded retry still leaves the session tainted and preserves the original failure;
- scroll release retry success still leaves the session tainted;
- scroll double-release failure cannot make the session reusable after cleanup;
- partial chord failure performs bounded reverse release and leaves the session tainted;
- failed key-down is tracked for cleanup and leaves the session tainted;
- typed-text key-up failure is retried, reported and leaves the session tainted;
- typed-text double release failure remains tracked until session abandonment;
- failed `release_all()` pointer/key releases remain represented in `InputReleaseReport` and tracked until abandonment.

Worker-level generation-tagged regression coverage proves that a double-failed scroll release quarantines generation 1, reconnects, and subsequent pointer/key input executes on generation 2 with clean local state. The existing worker input-failure regression was reconciled to expect the final bounded neutralizing release performed during quarantine.

Exact Rust test execution remains pending the frozen candidate CI run.

## 3. V2-R2 — Immutable GitHub Actions

Release Gates no longer use `dtolnay/rust-toolchain@stable`. The action is pinned to:

`dtolnay/rust-toolchain@4360b52568e2003a75bf9bc1d59f33a8e3fc893c`

The Rust toolchain itself remains explicitly `1.97.1`.

`tests/test_release_policy_contract.py` now applies a generic permanent-workflow rule: non-local third-party `uses:` references must use a full immutable 40-hex commit SHA; local `./...` Actions are the intentional exemption. The living release policy records the same requirement.

Actionlint, the complete workflow contract suite, and immutable-pin proof in Release Gates remain pending exact-candidate execution.

## 4. V2-R3 — Truthful command outcome identity

Command outcome capacity reservation and ID allocation are now one registry operation under the outcome-registry lock. Capacity is checked before `next_command_id` advances. If all retained slots are nonterminal, `CommandOutcomeCapacityFull` returns without consuming an identifier.

The existing bounded registry invariants are preserved:

- nonterminal records are not evicted to admit new work;
- terminal records may be evicted;
- a retained record is `Found`;
- only a known evicted retained ID is `Expired`;
- an ID never reserved by this process is `Unknown`;
- command ID exhaustion remains fail-closed.

The deterministic tiny-capacity test `capacity_rejection_does_not_consume_a_never_retained_identifier` proves that a rejected next ID remains numerically unconsumed and `Unknown`, then becomes the same next retained ID once terminal capacity is available. Existing terminal eviction coverage still proves `Expired` for known evictions.

The HTTP/OpenAPI/Python wire semantics do not require a schema change: the correction is internal identity truthfulness behind the existing `404 command_status_unknown` / `410 command_status_expired` contract. Exact workspace/HTTP/Python regression execution remains pending candidate CI.

## 5. V2-R4 — Native framebuffer revision exhaustion

The C shim now uses checked helper `vrc_advance_framebuffer_revision()` instead of incrementing unconditionally. At `UINT64_MAX` it:

- does not wrap;
- sets `VRC_STATUS_FRAMEBUFFER_REVISION_EXHAUSTED`;
- clears `complete`;
- records fixed payload-free diagnostic text;
- leaves the numeric revision at `UINT64_MAX`.

The callback status is machine-readable and survives an outer successful LibVNC message-handler return. `vrc_client_poll()` therefore returns a non-success status and marks the native session disconnected/incomplete.

Rust maps the status to typed `NativeError::FramebufferRevisionExhausted`, and the worker failure classifier handles it explicitly. The existing native-poll error path invalidates authoritative framebuffer and clipboard state, drops the native session, and schedules bounded reconnect before any replacement frame can become current.

Deterministic native coverage proves:

- `UINT64_MAX - 1` advances to `UINT64_MAX`;
- `UINT64_MAX` does not wrap and returns the exhaustion status;
- outer poll success does not hide callback exhaustion;
- connection completeness is cleared and the native client is disconnected;
- source-contract coverage requires the checked helper/status path.

Exact Rust/native execution remains pending candidate CI/Release Gates.

## 6. V2-R5 — Explicit accepted HTTP connection bound

`RuntimeSettings` now includes `maximum_connections`, loaded from `VRC_HTTP_MAX_CONNECTIONS`.

Policy:

- default: `256`;
- minimum: `1`;
- maximum: `65536`;
- zero, above-maximum, malformed, and non-Unicode configured values fail startup closed.

`serve_until_shutdown()` creates one process-owned Tokio semaphore with the configured capacity. Every admitted connection task owns one `OwnedSemaphorePermit` for the full task lifetime. When capacity is saturated, the already accepted new socket is closed immediately and no helper/connection task is spawned for it.

Because the permit is moved into the connection task, it remains held across header/body processing and releases only when the connection task exits, including clean close, peer/runtime failure, unwind/cancellation, or shutdown abort. Request/body timeouts cannot release the process-level connection permit while the connection task remains alive.

Runtime tests cover zero/max+1 rejection, one-connection saturation, prompt excess-socket closure, permit recovery after the held connection exits, and bounded shutdown while capacity is fully occupied. Existing connection-task classification covers clean, peer/runtime failure, panic and cancellation outcomes.

`README.md`, `docs/OPERATOR_GUIDE.md`, and `deploy/README.md` describe the limit and saturation behavior. A larger real-runtime/R13 capacity assertion remains a candidate integration-gate concern rather than a reason to claim local proof that did not run.

## 7. V2-R6 — Silent-failure/fallback audit

The V2 audit re-reviewed changed and adjacent Rust, Python, shell and workflow surfaces for discarded `Result`s, `.ok()`, `unwrap_or*`, wildcard error collapsing, side-effecting retries, cleanup retries, stale cache authority, sequence/revision exhaustion, detached work, poisoned synchronization, channel notifications, timeout abandonment, broad Python exceptions, shell `|| true`/`set +e`, workflow `continue-on-error`, mutable Actions and scanner/VEX bypasses.

### Surviving ignored production results

The relevant surviving ignored results are intentional and non-authoritative:

- worker completion-channel sends are ignored only **after** the command outcome registry has reached its authoritative state; a timed-out/dropped waiter cannot change command truth;
- `WorkerExitSignal` ignores a terminal `try_send` only after worker exit is already authoritative;
- worker startup notification is advisory to the spawning waiter and does not own lifecycle truth;
- HTTP shutdown-watch send ignores receiver absence only when no connection task remains to consume the notification;
- teardown `kill ... || true` shell sites are terminal/best-effort process cleanup, not configuration/readiness success criteria;
- bounded input neutralization retries never restore session trust; failed cleanup remains represented by aggregate taint/tracked state and later payload-free cleanup reports before abandonment;
- diagnostic duration conversion saturation is confined to log/metric representation, not protocol or lifecycle authority;
- checked-arithmetic/header `.ok()` uses convert local parse/conversion failure into explicit validation branches rather than silently continuing an operation.

No V2 audit result justified a compatibility fallback that allows normal service to resume from uncertain authoritative state. The temporary input compatibility shim was removed before candidate freeze.

### Additional R6 defect fixed

The process termination listener previously allowed listener failure to collapse into normal shutdown. `main.rs` now records a payload-safe error, still initiates and completes bounded shutdown cleanup, then returns process failure rather than false success.

No release-critical `continue-on-error`, broad scanner/VEX bypass, weakened Gitleaks/Trivy policy, or mutable third-party Action reference is accepted by the V2 source/workflow review. Exact Release Gates remain the authoritative execution proof.

## 8. V2-R7 — Documentation and security reconciliation

Living documentation now records:

- aggregate input-session quarantine and no automatic mutation replay;
- readiness/reconnect behavior after ambiguous input failure;
- `VRC_HTTP_MAX_CONNECTIONS` default `256`, range `1..=65536`, and saturation semantics;
- immutable third-party GitHub Action SHA policy;
- current VEX review date and expiry.

No public HTTP/OpenAPI status shape changed, so no OpenAPI or Python client wire-format edit is required for R3/R4/R5. The operator guide continues to document exact `Unknown` versus `Expired` HTTP status semantics and accepted mutation non-retry-safety.

`SECURITY.md` was re-read against V2 and remains consistent: `/v1/*` authorization, file-backed secret boundaries, raw-VNC isolation, payload logging prohibitions, TLS boundary, and CRITICAL VEX review/expiry remain accurate. The authoritative VEX file was reviewed `2026-08-31` and expires `2026-09-30`; the release policy was corrected to the same date.

New V2 diagnostics contain command IDs, bounded counts/categories, configured numeric limits or fixed error text only. They do not include typed text, clipboard payloads, framebuffer pixels, bearer tokens or VNC passwords.

MCP remains unimplemented and explicitly deferred until V2 final sign-off.

## 9. Changed-file inventory before evidence/TODO reconciliation

Compared with baseline `2506686ecdd77ddbfcc106d0109d6f7198233808`, the pre-evidence source/documentation head changed these files:

- `.github/workflows/release-gates.yml`
- `README.md`
- `crates/controller-api/src/input.rs`
- `crates/controller-api/src/main.rs`
- `crates/controller-api/src/runtime.rs`
- `crates/controller-api/src/worker/client.rs`
- `crates/controller-api/src/worker/helpers.rs`
- `crates/controller-api/src/worker/loop_state.rs`
- `crates/controller-api/src/worker/outcome.rs`
- `crates/controller-api/src/worker/run.rs`
- `crates/controller-api/src/worker/tests/clipboard_and_input.rs`
- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/native/vnc_shim.h`
- `crates/libvnc-adapter/src/lib.rs`
- `deploy/README.md`
- `docs/OPERATOR_GUIDE.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_SPEC_2026-09-01.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_TODO_2026-09-01.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`
- `tests/native/vnc_shim_clipboard_callback_test.c`
- `tests/test_native_contract.py`
- `tests/test_release_policy_contract.py`

This evidence file and the subsequent reconciled TODO are additional candidate files and must be included in the final PR inventory.

## 10. Candidate-validation contract

The next branch head after evidence/TODO reconciliation is the candidate generation to freeze in the PR. The PR must trigger both permanent workflows because both `CI` and `Release Gates` include `pull_request` triggers.

Acceptance requires both workflows to report success on the **same exact PR-head SHA**. If any job fails, that job/step must be inspected and the root cause fixed without weakening gates. Any fix creates a new candidate SHA, and both workflows must be evaluated again for that new generation.

Until those exact runs exist, all V2-R8 execution boxes and V2-R9 candidate conclusion boxes remain open.

## 11. Final-signoff items intentionally pending

The following evidence cannot truthfully be populated before exact-candidate execution and/or merge:

- frozen candidate SHA and PR number;
- candidate CI run ID/conclusion;
- candidate Release Gates run ID/conclusion;
- exact merged `master` SHA;
- final `master` CI and Release Gates IDs/conclusions;
- final validation-time VEX re-review;
- final V2 completion declaration.

No older workflow run is substituted for those fields.