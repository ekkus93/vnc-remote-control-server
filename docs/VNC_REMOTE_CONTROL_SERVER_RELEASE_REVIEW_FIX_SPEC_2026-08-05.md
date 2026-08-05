# VNC Remote Control Server — Release Review Fix Spec

Date: 2026-08-05
Branch: `master`
Review target SHA: `309364caf5d44d316557aa585ad7d92d043b0a47`
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_TODO_2026-08-05.md`

## 1. Purpose

This document defines the release-hardening fix pass required after the code review of the current `master` branch. It does **not** reopen the completed v0.1 R0-R16 implementation plan. Instead, it defines the remaining work required to make the latest `master` tip release-valid after the review found two blockers and several hardening improvements.

The accepted v0.1 implementation remains structurally sound. The current release claim is blocked because:

1. Regular CI passed on `309364caf5d44d316557aa585ad7d92d043b0a47`, but Release Gates failed on the same SHA.
2. The worker shutdown path can depend on the bounded normal command queue and can therefore block indefinitely in a saturated-queue edge case.

The fix pass must preserve the existing fail-closed posture. Do not replace precise failures with broad ignores, quiet fallbacks, or best-effort success paths.

## 2. Current reviewed state

At review time:

- `master` HEAD: `309364caf5d44d316557aa585ad7d92d043b0a47`
- Commit title: `Reconcile R0-R9 TODO completion evidence`
- CI workflow run: `31036432334`
- CI conclusion: success
- Release Gates workflow run: `31036432628`
- Release Gates conclusion: failure
- Failed Release Gates job: `Static and supply-chain policy`
- Failed step: `Scan complete Git history for secrets`
- Gitleaks result: one leak found

The Release Gates failure is a valid release blocker. It must not be waved through merely because the implementation code looks good.

## 3. Non-goals

This fix pass must not:

- rewrite the entire v0.1 architecture;
- replace the project-owned C shim with bindgen;
- add noVNC, OCR, multi-session, Playwright, or AI planning features;
- turn horizontal scrolling into a best-effort operation;
- broaden direct text entry beyond the current ASCII-only contract without a separate design;
- disable Gitleaks, Trivy, ShellCheck, actionlint, cargo-deny, sanitizer, Miri, or E2E gates;
- add blanket scanner allowlists;
- add `continue-on-error` to release-critical jobs;
- hide failures behind logs while returning success to callers.

## 4. Release-blocking requirements

### 4.1 Gitleaks finding resolution

The full-history Gitleaks finding must be investigated and resolved.

Acceptable outcomes:

1. **True positive secret:** rotate/revoke the affected secret, remove or neutralize the leak according to an explicit repository policy, and document the rotation/remediation evidence.
2. **False positive:** add a narrow Gitleaks allowlist entry that matches only the exact false-positive finding, with a clear rationale and test evidence.
3. **Non-secret test fixture:** make the fixture unmistakably synthetic and add a narrow allowlist only if Gitleaks still flags it.

Unacceptable outcomes:

- disabling Gitleaks;
- changing the exit code to success;
- scanning only the current tree instead of full history without a documented decision;
- adding broad path-level or regex-level allowlists that could mask future secrets;
- deleting the failing gate from Release Gates;
- treating the single leak as acceptable without evidence.

The final Release Gates run must pass on the exact final SHA.

### 4.2 Worker shutdown must not depend on normal command queue availability

The worker must have a shutdown path that cannot be blocked behind a full bounded command queue.

The final design must satisfy all of the following:

- Shutdown initiation must not require successful enqueue into the same bounded work queue used for normal desktop commands.
- `DesktopWorker::shutdown(timeout)` must return within a caller-bounded duration under the tested edge cases.
- `Drop` must not call an unbounded `join` after a failed or timed-out shutdown request.
- Shutdown must still attempt to release tracked input state before the native session is destroyed when a session is available.
- Shutdown must remain observable through state transition to `Stopped` when orderly shutdown succeeds.
- Failed or forced shutdown paths must not claim orderly success.

Implementation options are deliberately open. Acceptable approaches include:

- a separate control channel reserved for lifecycle commands;
- a dedicated atomic shutdown flag plus worker wake mechanism;
- a reserved shutdown slot with explicit proof that it cannot be consumed by normal commands;
- closing all command senders and making the worker loop terminate deterministically;
- another design that satisfies the bounded-shutdown contract and is covered by tests.

The chosen design must avoid silent swallowing of shutdown errors. It is acceptable for `Drop` to make a bounded best-effort shutdown, but it must not block indefinitely.

### 4.3 Saturated-queue shutdown regression coverage

Tests must prove the shutdown edge case.

Required coverage:

- A worker with a deliberately saturated normal command queue can still be shut down through the lifecycle path.
- `DesktopWorker::shutdown(timeout)` returns within the timeout or a stricter internal bound.
- Dropping a worker with a saturated normal command queue does not hang the test process.
- If a forced or abnormal shutdown path exists, it records an appropriate non-orderly/failure signal rather than reporting clean success.

Prefer unit-level deterministic tests using `spawn_with_factory` and a mock session. Add integration coverage only if the unit tests cannot exercise the contract.

### 4.4 Controller builder image reproducibility

The controller runtime image already uses a pinned Debian runtime digest, but the builder stage currently uses a tag-only Rust image.

The builder image must be made reproducible by one of the following:

1. pinning `rust:1.97.1-slim-trixie` by digest; or
2. replacing the tag-only builder image with a pinned Debian base plus an explicitly pinned Rust toolchain installation flow; or
3. documenting why digest pinning is intentionally deferred and creating a tracked issue for that decision.

Preferred outcome: pin the builder image by digest.

The Dockerfile check and Release Gates image build must continue to pass.

### 4.5 Secret file permission policy must be explicit

The current secret reader rejects writable or executable secret files, but permits read-only broad modes such as `0444`. This can be valid for Docker secret mounts but is more permissive than a strict host-local secret-file policy.

The final code/docs must make the policy explicit:

- If the project intentionally supports Docker secret mounts with `0444`, document that the permission policy is Docker-oriented.
- If host-local secrets should be stricter, add a mode or configuration distinction and tests.
- Do not accidentally reject Docker secrets used by the Compose deployment unless the deployment is updated at the same time.

This is a hardening/documentation requirement unless the implementation chooses to tighten behavior.

### 4.6 WebSocket event sequence overflow policy

The WebSocket event hub currently saturates to `u64::MAX` if the process-local event sequence overflows. This is practically unreachable but philosophically weaker than the rest of the fail-closed design.

The final behavior must be one of:

1. explicitly fail closed if the event sequence overflows;
2. record a fatal event-source condition and stop accepting/publishing new events;
3. document the practical unreachability and add a focused test around the helper logic, if extracted;
4. leave unchanged only with an explicit rationale in the evidence document.

Do not silently emit repeated indistinguishable sequence values without documenting why that is acceptable.

## 5. Existing behavior that must be preserved

The fix pass must preserve these already-reviewed properties:

- Raw VNC remains private to the Compose internal network.
- `/v1/*` HTTP routes remain bearer-authenticated.
- Liveness/readiness semantics remain fail-closed for readiness.
- Secrets are read from files, not secret-valued environment variables.
- Config and request logging do not expose API tokens, VNC passwords, typed text, clipboard payloads, or screenshot bytes.
- Text input remains preflighted ASCII plus tab/CR/LF.
- Clipboard remains UTF-8 with NUL rejection and byte bounds.
- Horizontal scrolling remains explicitly rejected in v0.1.
- Stale framebuffer pixels are not served as current screenshots.
- Screenshot encoding remains bounded by concurrency and timeout.
- Native pointer/clipboard/framebuffer operations remain behind the project-owned C shim.
- Native cleanup remains RAII-owned from Rust and `vrc_client_destroy`-owned in C.
- Release Gates continue to enforce exact CRITICAL VEX tuple matching.

## 6. Evidence requirements

The final fix must include an evidence document or update an existing one with:

- final commit SHA;
- CI run ID and conclusion for the final SHA;
- Release Gates run ID and conclusion for the final SHA;
- Gitleaks resolution summary;
- whether the Gitleaks finding was true positive, false positive, or synthetic fixture;
- shutdown design summary;
- shutdown edge-case test names;
- builder image pinning decision;
- secret-file permission policy decision;
- WebSocket event sequence overflow decision;
- explicit statement that no broad scanner bypass or `continue-on-error` was introduced.

Suggested evidence path:

`docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_REVIEW_FIX_EVIDENCE_2026-08-05.md`

## 7. Acceptance criteria

The fix pass is complete only when all of the following are true:

- The Gitleaks finding is resolved with narrow evidence.
- Release Gates passes on the exact final SHA.
- CI passes on the exact final SHA.
- Worker shutdown no longer depends on normal command queue capacity.
- Saturated-queue shutdown tests exist and pass.
- The controller builder image reproducibility decision is implemented or explicitly tracked.
- Secret-file permission policy is documented or tightened without breaking Compose secrets.
- WebSocket event sequence overflow behavior is documented, tested, or changed to fail closed.
- The companion TODO is updated to mark completed tasks and preserve any deliberate deferrals.
- No release-critical gate is weakened to make the run pass.

## 8. Review notes

This spec intentionally focuses on correctness under failure. The project already has strong design choices around typed API contracts, C/Rust FFI isolation, bounded buffers, stale-frame rejection, redacted logs, and exact VEX enforcement. The remaining work is to close release-blocking evidence and eliminate the shutdown edge case that normal-path tests can miss.
