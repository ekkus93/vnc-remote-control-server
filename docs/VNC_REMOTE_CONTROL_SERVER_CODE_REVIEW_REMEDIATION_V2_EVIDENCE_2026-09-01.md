# VNC Remote Control Server — Code Review Remediation V2 Evidence

**Date:** 2026-09-01  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Reviewed baseline:** `2506686ecdd77ddbfcc106d0109d6f7198233808`  
**Working branch:** `ralph/code-review-remediation-v2-20260901`  
**Exact final implementation candidate SHA:** `4f0904ab1976660eaf23fb4fd2fb1052855503fb` (PR #28)
**Final validated master SHA:** `4956a624be10ddb4b23aa23bcea23560b9c13a24`
**Final master CI:** `33666006266` — success
**Final master Release Gates:** `33666005936` — success

This file is cumulative V2 evidence. Historical or superseded green workflow runs are useful provenance, but they do not substitute for the final exact-candidate pair or the final merged-`master` pair.

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

## 2. Candidate-generation history

PR #28 intentionally records every candidate generation instead of laundering earlier red runs into a later green result.

- `c939b75288d9e3d2887f413f9ca9ccf22b93b67b`
  - CI `33588973602`: failed on rustfmt drift and Rust `E0502` in `InputController::release_all`;
  - Release Gates `33588973555`: failed on the same generation.
- `d24757fcebd71a8c5d2e724d81276281b825ea0f`
  - intermediate rustfmt-only correction before the borrow fix;
  - Release Gates `33589901648`: controller TSan compile and controller image build failed on the same `E0502`; static/supply-chain gates passed.
- `6cc02cfedccb55743d42cb7a8f2f88f15108fddb`
  - fixed `E0502`;
  - CI `33589986013` then exposed a stale partial-chord regression expectation;
  - Release Gates `33589986187` reached the same stale assertion rather than a sanitizer defect.
- `3b371e3f86b2f3cd74c12f67930cd504c68c52c2`
  - corrected only the fail-closed chord regression expectation;
  - CI `33590382054` passed Rust and Ruff gates, then failed Pylint `C0116` for a missing test docstring.
- `323714529f444228bb8cb07d893a9a20739c4779`
  - added only the missing Pylint-required docstring;
  - CI `33590696025`: success;
  - Release Gates `33590695987`: success.

The fully green `32371452...` generation is a strong checkpoint, but it became superseded when the final named acceptance-test debt was closed. The final candidate therefore requires a fresh pair on the post-reconciliation head.

## 3. V2-R1 — Aggregate input uncertainty and session quarantine

`InputController` has one aggregate `InputState::{Known, Uncertain}`. All native pointer and key sends flow through controller-owned helpers that set `Uncertain` on any `NativeError`. The implementation does not infer that a failed native write had no remote effect.

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
3. attempts bounded tracked-input release while the session still exists;
4. drops the VNC session;
5. abandons unresolved local input tracking only after the session is no longer reusable;
6. invalidates framebuffer/clipboard authority;
7. schedules bounded reconnect;
8. only then reaches another command-loop iteration.

The command outcome is recorded from the original command result; quarantine never replays the original mutation and does not replace the original failure with cleanup success.

The obsolete V1 scroll-only uncertainty handling and the temporary V2 `input_compat.rs` shim are removed.

### R1 regression coverage

Controller and worker coverage together now explicitly exercise:

- failed pointer movement;
- failed explicit button press;
- explicit `SetButton` release failure;
- click press failure;
- click release failure with successful bounded neutralization;
- click release plus retry double failure;
- double-click failure in the second click sequence;
- scroll release retry success;
- scroll double-release failure;
- failed key-down;
- explicit key-up failure;
- partial chord failure with successful cleanup;
- partial chord cleanup failure;
- typed-text key-up failure with successful retry;
- typed-text double cleanup failure;
- failed final pointer/key cleanup retained until abandonment;
- generation-tagged reconnect with clean replacement input state;
- an already-queued next mutation held behind an ambiguous native failure, proving it cannot execute on the tainted generation.

The final dedicated cases live in `crates/controller-api/src/worker/tests/v2_regressions.rs`. The queued-next-mutation test deterministically blocks the first native send, queues a second mutation while the first is in flight, then releases the failure and asserts the queued target never appears on generation 1. The second command may fail while the worker is reconnecting or execute after replacement, but it cannot mutate the quarantined session.

A separate real-TigerVNC ambiguous-send fault injector is not required: producing this transport ambiguity deterministically would require a test-only production/native hook, while the worker-generation regression directly exercises the quarantine boundary that owns the safety invariant. Existing TigerVNC E2E remains authoritative for the normal input path.

## 4. V2-R2 — Immutable GitHub Actions

Release Gates no longer use `dtolnay/rust-toolchain@stable`. The action is pinned to:

`dtolnay/rust-toolchain@4360b52568e2003a75bf9bc1d59f33a8e3fc893c`

The Rust toolchain itself remains explicitly `1.97.1`.

`tests/test_release_policy_contract.py` applies a generic permanent-workflow rule: non-local third-party `uses:` references must use a full immutable 40-hex commit SHA; local `./...` Actions are the intentional exemption. The living release policy records the same requirement.

The superseded-but-green `32371452...` generation proved actionlint, the complete workflow contract suite, and immutable pin enforcement in Release Gates. Those checks must pass again on the final post-reconciliation candidate.

## 5. V2-R3 — Truthful command outcome identity

Command outcome capacity reservation and ID allocation are one registry operation under the outcome-registry lock. Capacity is checked before `next_command_id` advances. If all retained slots are nonterminal, `CommandOutcomeCapacityFull` returns without consuming an identifier.

The bounded registry invariants are preserved:

- nonterminal records are not evicted to admit new work;
- terminal records may be evicted;
- a retained record is `Found`;
- only a known evicted retained ID is `Expired`;
- an ID never reserved by this process is `Unknown`;
- command ID exhaustion remains fail-closed.

The deterministic tiny-capacity test `capacity_rejection_does_not_consume_a_never_retained_identifier` proves that a rejected next ID remains numerically unconsumed and `Unknown`, then becomes the same next retained ID once terminal capacity is available. Existing terminal eviction coverage proves `Expired` for known evictions.

A separate public worker-client integration fixture for a full outcome registry is explicitly not added. Creating that state through the public worker would require holding the fixed production-sized registry full of nonterminal commands or exposing a test-only capacity seam. The defect lived in the registry allocation operation itself, and the deterministic tiny-capacity registry test exercises the exact failed-reservation/next-ID transition without widening production API surface. HTTP/OpenAPI/Python status semantics are separately covered by their existing contract suites.

## 6. V2-R4 — Native framebuffer revision exhaustion

The C shim uses checked helper `vrc_advance_framebuffer_revision()` instead of incrementing unconditionally. At `UINT64_MAX` it:

- does not wrap;
- sets `VRC_STATUS_FRAMEBUFFER_REVISION_EXHAUSTED`;
- clears `complete`;
- records fixed payload-free diagnostic text;
- leaves the numeric revision at `UINT64_MAX`.

The callback status is machine-readable and survives an outer successful LibVNC message-handler return. `vrc_client_poll()` therefore returns a non-success status and marks the native session disconnected/incomplete.

Rust maps the status to typed `NativeError::FramebufferRevisionExhausted`, and the worker failure classifier handles it explicitly. The native-poll error path invalidates authoritative framebuffer and clipboard state, drops the native session, and schedules bounded reconnect before replacement authority.

Deterministic native coverage proves maximum-1 advancement, maximum non-wrap failure, and callback-to-poll propagation. `worker::tests::v2_regressions::framebuffer_revision_exhaustion_invalidates_before_replacement_connects` adds the dedicated worker-level proof: generation 2's factory is blocked after exhaustion, the old framebuffer is already `Stale` while replacement is blocked, then the replacement connection is released and becomes current with the next process-local framebuffer revision.

## 7. V2-R5 — Explicit accepted HTTP connection bound

`RuntimeSettings` includes `maximum_connections`, loaded from `VRC_HTTP_MAX_CONNECTIONS`.

Policy:

- default: `256`;
- minimum: `1`;
- maximum: `65536`;
- zero, above-maximum, malformed, and non-Unicode configured values fail startup closed.

`serve_until_shutdown()` creates one process-owned Tokio semaphore with the configured capacity. Every admitted connection task owns one `OwnedSemaphorePermit` for the full task lifetime. At saturation, the already accepted new socket is closed immediately and no connection task is spawned for it.

Because the permit is moved into the connection task, it remains held across header/body processing and releases only when the connection task exits, including clean close, peer/runtime failure, unwind/cancellation, or shutdown abort. Request/body timeouts cannot release the process-level permit while the connection task remains alive.

Coverage now includes:

- zero and maximum+1 rejection;
- exact documented maximum `65536` acceptance in `crates/controller-api/tests/v2_runtime_limits.rs`;
- one-over-live-limit saturation using real Tokio `TcpListener`/`TcpStream` sockets;
- prompt excess-socket closure;
- permit recovery after a held connection exits;
- bounded shutdown while capacity is fully occupied;
- connection-task clean/error/panic/cancellation classification.

A separate Docker/R13 saturation fixture is explicitly not required. The connection semaphore and saturation decision live entirely in the Rust runtime and the existing test exercises that path with real sockets. Docker/Compose/R13 gates still validate deployment/integration behavior, but duplicating the same semaphore assertion there would not exercise another admission implementation.

`README.md`, `docs/OPERATOR_GUIDE.md`, and `deploy/README.md` describe the limit and saturation behavior.

## 8. V2-R6 — Silent-failure/fallback audit

The V2 audit re-reviewed changed and adjacent Rust, Python, shell and workflow surfaces for discarded `Result`s, `.ok()`, `unwrap_or*`, wildcard error collapsing, side-effecting retries, cleanup retries, stale cache authority, sequence/revision exhaustion, detached work, poisoned synchronization, channel notifications, timeout abandonment, broad Python exceptions, shell `|| true`/`set +e`, workflow `continue-on-error`, mutable Actions and scanner/VEX bypasses.

### Surviving ignored production results

The relevant surviving ignored results are intentional and non-authoritative:

- worker completion-channel sends are ignored only after the command outcome registry has reached its authoritative state;
- `WorkerExitSignal` ignores a terminal `try_send` only after worker exit is authoritative;
- worker startup notification is advisory to the spawning waiter and does not own lifecycle truth;
- HTTP shutdown-watch send ignores receiver absence only when no connection task remains to consume the notification;
- teardown `kill ... || true` shell sites are terminal/best-effort process cleanup, not configuration/readiness success criteria;
- bounded input neutralization retries never restore session trust; failed cleanup remains represented by aggregate taint/tracked state and later payload-free cleanup reports before abandonment;
- diagnostic duration conversion saturation is confined to log/metric representation, not protocol or lifecycle authority;
- checked-arithmetic/header `.ok()` uses convert local parse/conversion failure into explicit validation branches rather than silently continuing an operation.

No V2 audit result justified a compatibility fallback that allows normal service to resume from uncertain authoritative state. The temporary input compatibility shim was removed.

### Additional R6 defect fixed

The process termination listener previously allowed listener failure to collapse into normal shutdown. `main.rs` now records a payload-safe error, still performs bounded shutdown cleanup, then returns process failure rather than false success.

No separate termination-listener failure injection seam was introduced. Adding a production/test-only signal-source abstraction solely to force an operating-system listener-construction failure would widen code and lifecycle surface for an edge already expressed as straightforward result propagation. The requirement was conditional on a practical injectable seam; the reviewed decision is that no such seam is warranted.

No release-critical `continue-on-error`, broad scanner/VEX bypass, weakened Gitleaks/Trivy policy, or mutable third-party Action reference is accepted.

## 9. V2-R7 — Documentation and security reconciliation

Living documentation records:

- aggregate input-session quarantine and no automatic mutation replay;
- readiness/reconnect behavior after ambiguous input failure;
- `VRC_HTTP_MAX_CONNECTIONS` default `256`, range `1..=65536`, and saturation semantics;
- immutable third-party GitHub Action SHA policy;
- current VEX review date and expiry.

No public HTTP/OpenAPI status shape changed, so no OpenAPI or Python client wire-format edit is required for R3/R4/R5.

`SECURITY.md` remains consistent: `/v1/*` authorization, file-backed secret boundaries, raw-VNC isolation, payload logging prohibitions, TLS boundary, and CRITICAL VEX review/expiry remain accurate. The authoritative VEX file was reviewed `2026-08-31` and expires `2026-09-30`.

New V2 diagnostics contain command IDs, bounded counts/categories, configured numeric limits or fixed error text only. They do not include typed text, clipboard payloads, framebuffer pixels, bearer tokens or VNC passwords.

MCP remains unimplemented. V2 final sign-off is now complete, so the remediation gate that deferred MCP is satisfied and MCP may proceed as a separate phase.

## 10. Final changed-file inventory before exact-candidate freeze

Compared with baseline `2506686ecdd77ddbfcc106d0109d6f7198233808`, V2 changes include:

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
- `crates/controller-api/src/worker/tests/mod.rs`
- `crates/controller-api/src/worker/tests/lifecycle.rs`
- `crates/controller-api/src/worker/tests/v2_regressions.rs`
- `crates/controller-api/tests/v2_runtime_limits.rs`
- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/native/vnc_shim.h`
- `crates/libvnc-adapter/src/lib.rs`
- `deploy/README.md`
- `docs/OPERATOR_GUIDE.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_SPEC_2026-09-01.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_TODO_2026-09-01.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_EVIDENCE_2026-09-01.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`
- `tests/native/vnc_shim_clipboard_callback_test.c`
- `tests/test_native_contract.py`
- `tests/test_release_policy_contract.py`

The exact final PR diff remains the source of truth if subsequent CI fixes add another file.

## 11. Final candidate-validation contract

The branch head after this evidence update and TODO reconciliation is the final candidate generation. PR #28 must run both permanent workflows because both `CI` and `Release Gates` include `pull_request` triggers.

Acceptance requires both workflows to report success on the **same exact PR-head SHA**. If any job fails, the failing job/step must be inspected and the root cause fixed without weakening gates. Any fix creates a new candidate SHA, and both workflows must be evaluated again for that generation.

The final candidate run must cover at least:

- Rust fmt, Clippy, workspace tests and rustdoc;
- Python compile, Ruff, Pylint, mypy and workflow/unit contracts;
- shell syntax/ShellCheck/actionlint;
- cargo-deny and full-history Gitleaks;
- auditable release binary verification;
- Dockerfile and Compose validation;
- ASan, both TSan suites and Miri;
- Trivy vulnerability inventories, CycloneDX SBOMs and exact CRITICAL VEX enforcement;
- desktop/native/WorkerHandle/HTTP/Compose/R13 integration gates.

No earlier green generation substitutes for the final post-reconciliation head.

## 12. Final validation and closeout

### Accepted PR #28 implementation candidate

The final V2 implementation candidate was `4f0904ab1976660eaf23fb4fd2fb1052855503fb` in PR #28. Both permanent workflows passed on that exact generation:

- CI `33593375859`: **success**;
- Release Gates `33593375791`: **success**.

Those runs cover the complete R8 matrix required by the permanent workflows: Rust formatting/Clippy/workspace tests/rustdoc; Python compile/Ruff/Pylint/mypy/unittest; shell syntax/ShellCheck/actionlint; cargo-deny/Gitleaks/auditable release-binary verification; Dockerfile/Compose checks; ASan, both TSan scopes and Miri; Trivy inventories, CycloneDX SBOM generation and exact CRITICAL VEX enforcement; and desktop/native/WorkerHandle/HTTP/Compose/R13 integration gates.

### First merged-master validation and race-test correction

PR #28 merged as `b11c7c0b6cf7b1386fe740d609b8b5c2539f57a4`. Fresh merged-master validation produced:

- Release Gates `33597230305`: **success**;
- CI `33597230151`: **failure** with 191/192 controller tests passing because `worker::tests::lifecycle::dropped_worker_event_receiver_stops_command_service` assumed only one of two legitimate fail-closed receiver-loss linearizations.

The failure did not expose a production behavior defect. It exposed a race-sensitive test contract: after the event receiver is dropped, either reconnect submission may be admitted and then fail when event publication detects receiver loss, or the worker may detect terminal receiver loss first and reject `submit()` immediately with `DesktopError::WorkerUnavailable`. Both are fail-closed; success or unrelated errors remain invalid.

PR #29 changed only `crates/controller-api/src/worker/tests/lifecycle.rs` to accept those two terminal outcomes. Its exact candidate `fbb9f7fe214e6c95e6eb39ba2b3bacf1212936af` passed both permanent workflows:

- CI `33626101316`: **success**;
- Release Gates `33626101208`: **success**.

No production code or release/security gate changed in PR #29.

### Final exact master

PR #29 merged as `4956a624be10ddb4b23aa23bcea23560b9c13a24`. Fresh workflows on that exact `master` generation both passed:

- CI `33666006266`: **success**;
- Release Gates `33666005936`: **success**.

This is the authoritative final validated V2 implementation generation. Earlier green runs remain provenance and are not substituted for this exact-master pair.

### Final VEX re-review

At final validation time on 2026-09-02, `SECURITY.md` and `security/trivy-critical-vex.json` were re-reviewed for status and expiry. Repository metadata remains:

- `reviewed_at: 2026-08-31`;
- `expires_at: 2026-09-30`.

The VEX is therefore current, and exact CRITICAL VEX enforcement passed final Release Gates `33666005936`. No VEX bypass or release-gate weakening was accepted.

### Completion declaration

Every applicable V2-R0 through V2-R10 requirement has been reconciled against final source, tests, workflow configuration, PR history, and exact-generation external validation. No checkbox is closed solely because a commit message claims completion. The silent-failure/fallback audit remains fail-closed: no compatibility fallback was accepted that permits normal service to continue from uncertain authoritative input, framebuffer, lifecycle, or security state.

**V2 remediation is complete on final validated `master` SHA `4956a624be10ddb4b23aa23bcea23560b9c13a24`.**

MCP remains unimplemented, but the remediation sign-off gate that intentionally deferred MCP is now satisfied. MCP may proceed as a separate next phase.
