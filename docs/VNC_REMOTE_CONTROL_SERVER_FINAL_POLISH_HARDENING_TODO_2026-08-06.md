# VNC Remote Control Server Final Polish Hardening TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_SPEC_2026-08-06.md`

Baseline branch: `master`

Baseline SHA: `a541db25624cb9ddf23664606ed89c0522cc75a2`

Status: not started.

---

## P0. Ground rules and baseline confirmation

- [ ] Confirm the current branch is `master`.
- [ ] Confirm the current starting SHA before implementation edits.
- [ ] If `master` still equals `a541db25624cb9ddf23664606ed89c0522cc75a2`, record that as the final-polish starting SHA.
- [ ] If `master` has advanced, inspect intervening changes and record the actual starting SHA before editing.
- [ ] Read `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_SPEC_2026-08-06.md` in full.
- [ ] Read the completed cleanup TODO enough to preserve accepted C1-C5 behavior.
- [ ] Do not reopen `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_TODO_2026-08-06.md` unless source evidence proves a real regression.
- [ ] Do not weaken CI, Release Gates, sanitizer gates, Gitleaks, ShellCheck, actionlint, Dockerfile checks, Compose checks, cargo policy, auditable-binary checks, Trivy, SBOM, or VEX gates.
- [ ] Do not use `continue-on-error`, broad ignores, forced success, swallowed exit codes, force pushes, or older-SHA evidence.
- [ ] Keep scope limited to P1-P4 unless a compile/test failure requires a directly related repair.

Acceptance:

- [ ] Starting SHA is recorded in the final evidence block.
- [ ] No unrelated feature work is mixed into this pass.
- [ ] Prior accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, R13, CI, Release Gates, post-correctness hardening, and post-hardening cleanup contracts are preserved.

---

## P1. Make HTTP request ID sequence exhaustion fail closed

Source targets likely involved:

- `crates/controller-api/src/http/state.rs`
- request ID middleware/boundary modules under `crates/controller-api/src/http/`
- `crates/controller-api/src/http/tests/*`
- response/error contract tests as needed
- operator/API docs only if external behavior changes

Tasks:

- [ ] Inspect all current `HttpState::next_request_id()` call sites.
- [ ] Identify the request boundary that can fail before normal handler execution.
- [ ] Replace unchecked request ID sequence increment with checked allocation.
- [ ] Add terminal request ID exhaustion state, or an equivalent fail-closed mechanism.
- [ ] Ensure normal request IDs never wrap, reuse, silently saturate, or panic.
- [ ] Ensure exhausted state does not allow normal command/screenshot/clipboard/display/status handler execution.
- [ ] Return a bounded redaction-safe service error when request ID allocation is exhausted.
- [ ] If a sentinel request ID is required for the error model, ensure it is explicitly reserved and cannot be confused with a normal allocated request ID.
- [ ] Emit at most one exhaustion diagnostic unless a deliberate metric/counter is added.
- [ ] Do not include request bodies, command payloads, typed text, clipboard text, bearer tokens, VNC passwords, framebuffer bytes, screenshot bytes, or query secrets in diagnostics.
- [ ] Preserve existing request ID format and behavior for non-exhausted requests.

Expected tests:

- [ ] Normal request IDs remain monotonic and preserve their accepted format.
- [ ] Forcing the sequence to `u64::MAX` causes a bounded allocation failure without panic.
- [ ] After exhaustion, no normal request ID wraps to zero, one, or any previously issued normal sequence.
- [ ] Exhausted state remains terminal for normal allocation.
- [ ] The HTTP boundary returns the specified bounded error before a normal handler runs.
- [ ] Exhaustion diagnostics are payload-free and secret-free.
- [ ] Existing request ID, authentication, command, screenshot, metrics, health, and WebSocket tests still pass.

Acceptance:

- [ ] Request ID sequence exhaustion is fail closed and regression-tested.
- [ ] No duplicate normal request ID can be produced through wraparound.

Do not accept:

- [ ] `fetch_add` wraparound remains for normal request IDs.
- [ ] Exhaustion panics the process.
- [ ] Exhaustion silently reuses, saturates, or fabricates a normal sequence value.
- [ ] Exhaustion runs a normal handler before failing.
- [ ] Exhaustion diagnostics contain request payloads or secrets.

---

## P2. Wake established WebSocket clients immediately on EventHub sequence exhaustion

Source targets likely involved:

- `crates/controller-api/src/events.rs`
- existing WebSocket/EventHub tests
- HTTP/WebSocket docs only if behavior contract changes

Tasks:

- [ ] Preserve current pre-upgrade `503 event_sequence_exhausted` behavior.
- [ ] Preserve current established close code `1011` and exact reason `event sequence exhausted`.
- [ ] Preserve normal WebSocket initial snapshot and event delivery behavior.
- [ ] Preserve heartbeat, idle timeout, slow-client disconnect, and client-capacity behavior.
- [ ] Add an internal wake mechanism for established clients when sequence exhaustion first becomes terminal.
- [ ] Ensure the wake mechanism does not create a user-visible payload event unless docs/tests explicitly define that contract.
- [ ] Ensure all established clients waiting in the service loop can observe exhaustion promptly without waiting for heartbeat.
- [ ] Keep close reason payload-free and secret-free.
- [ ] Avoid broad sleeps; tests should use bounded synchronization/timeouts.

Expected tests:

- [ ] Existing pre-upgrade exhaustion test still passes.
- [ ] Existing established-client `1011` exhaustion test still passes or is replaced by a stronger equivalent.
- [ ] New or updated test sets heartbeat interval long enough that heartbeat-only behavior would fail the prompt-close assertion.
- [ ] Established client receives initial snapshot before exhaustion is triggered.
- [ ] Established client closes promptly after exhaustion with code `1011`.
- [ ] Established client close reason is exactly `event sequence exhausted`.
- [ ] Close reason and logs used by the test contain no sensitive payload terms.

Acceptance:

- [ ] Established WebSocket clients are promptly woken by EventHub sequence exhaustion.
- [ ] No accepted WebSocket exhaustion behavior regresses.

Do not accept:

- [ ] Established clients can remain open until heartbeat despite the new prompt-wake requirement.
- [ ] Close code/reason drifts without deliberate doc/test update.
- [ ] Implementation logs or sends sensitive payloads.
- [ ] Implementation adds a public event type accidentally or without documentation.

---

## P3. Decide and implement native scrub semantic-test strategy

Source targets likely involved:

- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/native/vnc_shim.h` only if a test hook is added
- `crates/libvnc-adapter/build.rs` only if test-only C configuration is needed
- `tests/test_native_contract.py`
- native tests under `tests/native/` if practical
- final-polish implementation notes

Decision point:

- [ ] Evaluate whether a safe pre-free semantic hook can be added without exposing unsafe production API.
- [ ] Choose Option A or Option B below and document the rationale.

Option A — safe test-only semantic hook:

- [ ] Add a test-only observer/hook that can inspect project-owned sensitive buffers after scrub and before free.
- [ ] Ensure the hook is unavailable in production builds or impossible to use as a production API.
- [ ] Ensure the hook never observes/logs pre-scrub sensitive payloads.
- [ ] Ensure the hook never reads freed memory.
- [ ] Ensure the hook never depends on allocator reuse.
- [ ] Add semantic tests for stored clipboard replacement/destruction, outbound send-copy cleanup, and shim-owned password destruction where practical.
- [ ] Keep source-contract tests for scrub-before-free ordering and call-site coverage.

Option B — retain and tighten source-contract strategy:

- [ ] Document why a semantic hook would add more risk or complexity than value.
- [ ] Review existing source-contract tests for gaps.
- [ ] Tighten tests if any call site or ordering guarantee is insufficiently protected.
- [ ] Preserve native smoke, WorkerHandle text/clipboard E2E, sanitizer, and Miri coverage as execution evidence.

Required coverage regardless of option:

- [ ] Stored clipboard replacement scrub remains protected.
- [ ] Stored clipboard destruction scrub remains protected.
- [ ] Outbound temporary clipboard send-copy scrub-before-free remains protected.
- [ ] Shim-owned persistent VNC password destruction scrub remains protected.
- [ ] Clipboard revision overflow remains rejected before allocation/replacement.
- [ ] No test reads freed memory.
- [ ] No test depends on allocator reuse.
- [ ] No test logs clipboard text or VNC password bytes.
- [ ] Documentation does not overclaim third-party/OS/toolkit/allocator/LibVNCClient/server scrub guarantees.

Acceptance:

- [ ] Native scrub regression strategy is explicit, practical, and evidence-backed.
- [ ] Existing project-owned scrub guarantees remain intact.

Do not accept:

- [ ] A test that reads freed memory.
- [ ] A test that depends on allocator reuse.
- [ ] Logging or printing sensitive native buffers.
- [ ] Removing the central `vrc_scrub_and_free` scrub-before-free primitive without a stronger replacement.

---

## P4. Documentation updates for final polish pass

Tasks:

- [ ] Add final-polish implementation notes after source work is complete.
- [ ] Document request ID exhaustion behavior if it changes an operator/API-visible response.
- [ ] Document EventHub prompt-wake behavior only if docs currently describe timing or close semantics.
- [ ] Document native scrub semantic-test decision.
- [ ] Preserve third-party/OS/toolkit/allocator/LibVNCClient/server/swap/crash-dump residual-memory non-guarantees.
- [ ] Avoid duplicating the prior cleanup TODO wholesale.
- [ ] Do not rewrite historical evidence to imply future-run knowledge existed earlier.

Acceptance:

- [ ] Documentation is minimal, accurate, and does not overclaim guarantees.

---

## P5. Local validation

Run before pushing whenever available:

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`
- [ ] `python -m compileall -q tools/ci_status tests desktop/test-app`
- [ ] `python -m unittest discover -s tests -p 'test_*.py' -v`
- [ ] Permanent shell syntax checks.

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

## P6. Exact-SHA permanent validation

- [ ] Commit implementation changes intentionally.
- [ ] Push to `master` without force.
- [ ] Record implementation SHA.
- [ ] Wait for CI on that exact SHA.
- [ ] Wait for Release Gates on that exact SHA.
- [ ] Confirm CI success across:
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
  - [ ] Miri;
  - [ ] Trivy/SBOM/VEX.
- [ ] Repair root causes only; do not weaken gates or assertions.
- [ ] Do not use previous-SHA, canceled, superseded, red, or partial jobs as completion evidence.

Acceptance:

- [ ] Same exact implementation SHA passes CI and Release Gates.

---

## P7. Final evidence and completion report

- [ ] Complete this TODO only after exact-SHA implementation validation.
- [ ] Fill the evidence block below.
- [ ] Add or update final-polish implementation notes.
- [ ] Commit documentation/evidence changes intentionally.
- [ ] Push without force.
- [ ] Wait for CI and Release Gates on the exact final documentation/evidence tip if a documentation commit follows implementation validation.
- [ ] Record external workflow run IDs after the final commit exists; do not claim a commit embeds its own future hash or future workflow IDs.

Final evidence:

```text
Original baseline SHA:
Final-polish starting SHA:
Implementation SHA:
Final documentation/evidence SHA, if separate:
Final repository-tip SHA:
Implementation CI run ID and conclusion:
Implementation Release Gates run ID and conclusion:
Final-tip CI run ID and conclusion, if separate:
Final-tip Release Gates run ID and conclusion, if separate:

P1 request ID sequence exhaustion:

P2 EventHub prompt wake-up:

P3 native scrub semantic-test decision:

P4 documentation updates:

Local validation:

Unavailable local validation, with reasons:

Deferred follow-ups:
```

Acceptance:

- [ ] This TODO is marked complete only after the exact final repository tip is green in CI and Release Gates.

---

## Final do-not-accept checklist

- [ ] No older-SHA, canceled-run, superseded-run, red-run, or partial-run evidence is used for completion.
- [ ] No CI or Release Gate is weakened, skipped, or converted to advisory-only.
- [ ] No `continue-on-error`, broad ignore, forced success, swallowed exit code, or force push is used.
- [ ] No request ID sequence can wrap into a normal reused request ID.
- [ ] No request ID exhaustion path panics, silently saturates, or executes a normal handler without a valid normal request ID.
- [ ] No EventHub established client remains heartbeat-bound after the prompt-wake requirement is implemented.
- [ ] No WebSocket exhaustion close code/reason drift occurs without deliberate documentation and tests.
- [ ] No native scrub test reads freed memory or depends on allocator reuse.
- [ ] No command payload, typed text, clipboard text, key name, coordinate, bearer token, VNC password, framebuffer byte, screenshot byte, or query secret is introduced into diagnostics/logs.
- [ ] No documentation claims third-party, OS, toolkit, allocator, VNC-server, LibVNCClient, reverse-proxy, swap, or crash-dump copies are scrubbed without evidence.
- [ ] No secret-bearing config type regains implicit general-purpose `Clone` without a new explicit reviewed need.
- [ ] No API bearer token returns to long-lived raw `Arc<str>` or equivalent ordinary string ownership.
- [ ] No `HttpBackend` command metric method silently defaults to zero.
- [ ] No old queue-depth metric alias is reintroduced without an explicitly named external compatibility requirement.
- [ ] No active temporary patcher workflow or recovery script is introduced.
- [ ] No broad Gitleaks ignore, path ignore, wildcard ignore, or rule suppression is introduced.
