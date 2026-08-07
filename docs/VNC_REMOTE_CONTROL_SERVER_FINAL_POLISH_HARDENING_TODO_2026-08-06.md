# VNC Remote Control Server Final Polish Hardening TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_SPEC_2026-08-06.md`

Implementation notes: `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_IMPLEMENTATION_NOTES_2026-08-06.md`

Baseline branch: `master`

Original reviewed baseline SHA: `a541db25624cb9ddf23664606ed89c0522cc75a2`

Final-polish starting SHA: `56df8ee6de95765e9fe92eb2647dda76bf93fc84`

Validated implementation SHA before completion documentation: `f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55`

Status: implementation and repository-owned evidence record complete. Final closure requires CI and Release Gates to pass on this exact documentation-completion repository tip; those future run IDs are recorded externally after this commit exists rather than falsely embedded here.

---

## P0. Ground rules and baseline confirmation

- [x] Confirmed the working branch was `master`.
- [x] Confirmed the actual starting SHA before implementation edits.
- [x] `master` had advanced beyond historical baseline `a541db25624cb9ddf23664606ed89c0522cc75a2` only through the final-polish planning documents; actual starting SHA was `56df8ee6de95765e9fe92eb2647dda76bf93fc84`.
- [x] Inspected the intervening planning-only commits before editing.
- [x] Read `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_SPEC_2026-08-06.md` in full.
- [x] Read the completed post-hardening cleanup TODO sufficiently to preserve accepted C1-C5 behavior.
- [x] Did not reopen `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_TODO_2026-08-06.md`; no source regression required it.
- [x] Did not weaken CI, Release Gates, sanitizer gates, Gitleaks, ShellCheck, actionlint, Dockerfile/Compose checks, dependency policy, auditable-binary checks, Trivy, SBOM, or VEX gates.
- [x] Did not use `continue-on-error`, broad ignores, forced success, swallowed exit codes, force pushes, or older-SHA evidence.
- [x] Source work remained limited to P1-P4 plus the exact rustfmt repair required by CI.

Acceptance:

- [x] Starting SHA is recorded in the evidence block below.
- [x] No unrelated feature work is mixed into this pass.
- [x] Prior accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, R13, CI, Release Gates, post-correctness hardening, and post-hardening cleanup contracts are preserved.

Diff audit from the actual starting SHA to validated implementation SHA found only these intended files:

- `README.md`;
- `crates/controller-api/src/events.rs`;
- `crates/controller-api/src/http/ids.rs`;
- `crates/controller-api/src/http/middleware.rs`;
- `crates/controller-api/src/http/state.rs`;
- `crates/controller-api/src/http/tests/access_log_and_validation.rs`;
- `docs/WEBSOCKET_EVENTS.md`;
- `tests/test_documentation_contract.py`;
- `tests/test_native_contract.py`.

No workflow or release-policy source was modified.

---

## P1. Make HTTP request ID sequence exhaustion fail closed

Sources:

- `crates/controller-api/src/http/ids.rs`
- `crates/controller-api/src/http/middleware.rs`
- `crates/controller-api/src/http/state.rs`
- `crates/controller-api/src/http/tests/access_log_and_validation.rs`
- `README.md`

Completed:

- [x] Inspected all current `HttpState::next_request_id()` call sites.
- [x] Confirmed the outer `assign_request_id` middleware is the boundary that can fail before access logging, authentication, and normal handler execution.
- [x] Replaced unchecked generated request-ID `fetch_add` wraparound with checked atomic allocation.
- [x] Added terminal `request_id_exhausted` state shared across `HttpState` clones.
- [x] Generated normal request IDs cannot wrap, reuse a sequence through wraparound, silently saturate, or panic on exhaustion.
- [x] Terminal exhaustion is checked before a caller-provided request ID is accepted, so a caller ID cannot bypass the terminal state.
- [x] Exhaustion returns bounded HTTP `503` before normal command/screenshot/clipboard/display/status handler execution.
- [x] Exhaustion response code is `request_id_exhausted` with message `request identifier sequence is exhausted`.
- [x] Reserved sentinel `request-id-exhausted` is returned in the JSON error and `X-Request-ID` header.
- [x] The reserved sentinel is explicitly rejected as a caller-provided normal request ID.
- [x] `request_id_sequence_exhausted` diagnostic is emitted at most once when terminal state is first observed.
- [x] The diagnostic contains no request body, command payload, typed text, clipboard text, bearer token, VNC password, framebuffer/screenshot bytes, or query values.
- [x] Existing non-exhausted generated request-ID format remains `process-instance-sequence`.

Tests:

- [x] `request_id_sequence_is_monotonic_terminal_and_logged_once` proves normal monotonic format, forced `u64::MAX` failure, terminal state, one diagnostic, and secret/payload-free logging.
- [x] `request_id_exhaustion_rejects_before_handler_and_caller_id_cannot_bypass` proves terminal failure is `503`, returns the reserved sentinel, rejects caller-ID bypass, and leaves the backend command list empty.
- [x] Full workspace tests preserve existing request ID, authentication, command, screenshot, metrics, health, and WebSocket behavior outside the terminal test condition.

Acceptance:

- [x] Request ID sequence exhaustion is fail closed and regression-tested.
- [x] No duplicate generated normal request ID can be produced through wraparound.

Do-not-accept verification:

- [x] No unchecked `fetch_add` wraparound remains for generated normal request IDs.
- [x] Exhaustion does not panic the process.
- [x] Exhaustion does not silently reuse, saturate, or fabricate a normal sequence value.
- [x] Exhaustion cannot run the tested normal keyboard-text handler first.
- [x] Exhaustion diagnostics contain no request payloads or secrets.

---

## P2. Wake established WebSocket clients immediately on EventHub sequence exhaustion

Source:

- `crates/controller-api/src/events.rs`
- `docs/WEBSOCKET_EVENTS.md`
- `tests/test_documentation_contract.py`

Completed:

- [x] Preserved pre-upgrade HTTP `503 event_sequence_exhausted` behavior.
- [x] Preserved established close code `1011` and exact reason `event sequence exhausted`.
- [x] Preserved normal initial snapshot and event delivery behavior.
- [x] Preserved heartbeat, idle timeout, slow-client disconnect, and client-capacity behavior.
- [x] Added internal `Arc<tokio::sync::Notify>` wake mechanism to EventHub.
- [x] First transition to terminal sequence exhaustion still logs once and now calls `notify_waiters()`.
- [x] Established service loops select on the internal notification and close promptly when terminal exhaustion is observed.
- [x] Top-of-loop terminal check remains, closing races where exhaustion happened before a waiter registered.
- [x] Wake mechanism creates no user-visible event type or payload.
- [x] Exhaustion close reason remains payload-free and secret-free.
- [x] Test synchronization uses bounded Tokio timeouts rather than broad sleeps.

Tests:

- [x] Existing pre-upgrade exhaustion coverage passes.
- [x] Established-client exhaustion test still requires initial snapshot before exhaustion.
- [x] Test heartbeat was lengthened to 30 seconds while close remains required within 200 ms, so heartbeat-only behavior cannot pass.
- [x] Established client closes with `1011` and exact reason `event sequence exhausted`.
- [x] Test rejects sensitive payload terminology from the close reason.
- [x] Documentation contract requires both prompt-wake wording and the internal Notify/`notify_waiters` source contract.

Acceptance:

- [x] Established WebSocket clients are promptly woken by EventHub sequence exhaustion.
- [x] No accepted WebSocket exhaustion behavior regressed.

Do-not-accept verification:

- [x] Established clients are no longer heartbeat-bound after terminal sequence exhaustion.
- [x] Close code/reason did not drift.
- [x] No sensitive payload is logged or sent by the wake mechanism.
- [x] No new public event type was introduced.

---

## P3. Decide and implement native scrub semantic-test strategy

Decision:

**Option B selected — retain and tighten the source-contract strategy.**

- [x] Evaluated a safe pre-free semantic observer/test hook.
- [x] Chose Option B and documented the rationale in the implementation notes.

Option A was not selected. It would add native build/API complexity and another sensitive-buffer observation mechanism solely to observe memory between scrub and free. No production or test-only observer hook was introduced.

Option B completion:

- [x] Documented why a semantic hook adds more risk/complexity than value for this boundary.
- [x] Reviewed existing source-contract tests for direct-free and call-site gaps.
- [x] Tightened `tests/test_native_contract.py` without weakening existing assertions.
- [x] Preserved native smoke, WorkerHandle text/clipboard E2E, ASan, TSan, and Miri execution evidence.

Required coverage:

- [x] Stored clipboard replacement scrub remains protected through `vrc_release_clipboard` -> `vrc_scrub_and_free`.
- [x] Stored clipboard destruction scrub remains protected through the same central path.
- [x] Outbound temporary clipboard send-copy scrub-before-free remains protected.
- [x] Shim-owned persistent VNC password destruction scrub remains protected.
- [x] Clipboard revision overflow remains rejected before allocation/replacement.
- [x] Contract now forbids direct `free(client->clipboard)`.
- [x] Contract now forbids direct `free(client->password)`.
- [x] Contract now forbids direct `free(copy)` for the reviewed outbound sensitive copy.
- [x] Contract protects the expected centralized scrub and scrub/free call counts.
- [x] No test reads freed memory.
- [x] No test depends on allocator reuse.
- [x] No test logs clipboard text or VNC password bytes.
- [x] Documentation does not claim third-party/OS/toolkit/allocator/LibVNCClient/server scrub guarantees.

Acceptance:

- [x] Native scrub regression strategy is explicit, practical, and evidence-backed.
- [x] Existing project-owned scrub guarantees remain intact.

Do-not-accept verification:

- [x] No freed-memory test was introduced.
- [x] No allocator-reuse-dependent test was introduced.
- [x] No sensitive native buffer logging/printing was introduced.
- [x] Central `vrc_scrub_and_free` remains authoritative.

---

## P4. Documentation updates for final polish pass

Completed:

- [x] Added `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_IMPLEMENTATION_NOTES_2026-08-06.md`.
- [x] `README.md` documents global routed-request ID terminal exhaustion, HTTP `503`, `request_id_exhausted`, and reserved `request-id-exhausted` sentinel.
- [x] `docs/WEBSOCKET_EVENTS.md` replaces the previous heartbeat-bound wording with prompt internal exhaustion notification behavior.
- [x] `tests/test_documentation_contract.py` protects the new request-ID and WebSocket documentation statements.
- [x] Implementation notes document the Option B native scrub decision.
- [x] Preserved third-party/OS/toolkit/allocator/LibVNCClient/server/reverse-proxy/swap/crash-dump residual-memory non-guarantees.
- [x] Did not duplicate the prior cleanup TODO wholesale.
- [x] Did not rewrite historical evidence to imply future-run knowledge existed earlier.

Acceptance:

- [x] Documentation is scoped, accurate, and does not overclaim guarantees.

---

## P5. Local validation disposition

The ChatGPT execution environment did not have a usable normal local repository checkout because direct outbound GitHub DNS/network access was unavailable. None of the commands below is represented as locally passed. Each corresponding permanent workflow surface passed on exact implementation SHA `f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55`.

Repository-quality commands:

- [x] `cargo fetch --locked` — unavailable locally; exact-SHA CI dependency fetch succeeded.
- [x] `cargo fmt --all --check` — unavailable locally; exact-SHA CI formatting succeeded.
- [x] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings` — unavailable locally; exact-SHA strict Clippy succeeded.
- [x] `cargo test --locked --workspace --all-features` — unavailable locally; exact-SHA workspace tests succeeded.
- [x] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps` — unavailable locally; exact-SHA rustdoc succeeded.
- [x] `python -m compileall -q tools/ci_status tests desktop/test-app` — unavailable locally; exact-SHA Python compile succeeded.
- [x] `python -m unittest discover -s tests -p 'test_*.py' -v` — unavailable locally; exact-SHA Python/workflow/native/documentation contracts succeeded.
- [x] Permanent shell syntax checks — unavailable locally; exact-SHA CI shell checks succeeded.

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

## P6. Exact-SHA permanent validation

Validated implementation SHA:

`f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55`

- [x] Implementation changes were committed intentionally to `master` without force.
- [x] CI ran on the exact implementation SHA.
- [x] Release Gates ran on the exact implementation SHA.
- [x] CI run `31156125021` concluded `success` on exact SHA `f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55`.
  - [x] formatting;
  - [x] Clippy with warnings denied;
  - [x] full Rust workspace tests;
  - [x] rustdoc with warnings denied;
  - [x] Python compile and unittest discovery;
  - [x] workflow/release-policy/native/documentation contract tests;
  - [x] shell syntax;
  - [x] desktop smoke;
  - [x] native adapter smoke;
  - [x] WorkerHandle input E2E;
  - [x] WorkerHandle text/clipboard E2E;
  - [x] authenticated HTTP E2E;
  - [x] Compose/persistence;
  - [x] R13 Compose integration/E2E.
- [x] Release Gates run `31156124982` concluded `success` on the same exact implementation SHA.
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
- [x] Intermediate candidate `d2f4b38d9d1c76af14500538b0e2fe69c5027c49` failed formatting only; exact rustfmt output was applied at root.
- [x] No gate or assertion was weakened to repair that failure.
- [x] Older, red, superseded, canceled, or partial runs are not used as completion evidence.

Acceptance:

- [x] Same exact implementation SHA passed CI and Release Gates.

---

## P7. Final evidence and completion report

- [x] Completed this TODO only after exact-SHA implementation validation.
- [x] Filled the evidence block below.
- [x] Added final-polish implementation notes.
- [x] Documentation/evidence changes were committed intentionally and pushed without force.
- [x] This completion record requires exact-tip CI and Release Gates for the documentation-completion commit.
- [x] Final documentation-tip SHA/run IDs are recorded externally after this commit exists rather than pretending this commit can embed its own future SHA or future workflow IDs.

Final evidence:

```text
Original baseline SHA:
a541db25624cb9ddf23664606ed89c0522cc75a2

Final-polish starting SHA:
56df8ee6de95765e9fe92eb2647dda76bf93fc84

Validated implementation SHA before final completion documentation:
f3d1f2cc39965b1f64d4c807cdc76cd74ea68c55

Implementation CI run:
31156125021 — success

Implementation Release Gates run:
31156124982 — success

Implementation-notes commit:
4b2dd5a6cc43203d3bab623502c88ee3e8bd399b

Final documentation/evidence SHA:
This TODO completion commit; exact SHA is recorded externally after commit creation.

Final repository-tip SHA:
Same final documentation/evidence commit if its exact workflows require no repair; recorded externally.

P1 request ID sequence exhaustion:
Checked atomic allocation, terminal exhaustion state, reserved non-normal sentinel, one payload-free diagnostic, and outer-middleware 503 before normal handler execution.

P2 EventHub prompt wake-up:
Internal Notify wakes established service loops when terminal sequence exhaustion first occurs; 30-second-heartbeat test requires exact 1011 close within 200 ms.

P3 native scrub semantic-test decision:
Option B selected. Source-contract strategy tightened; no freed-memory/allocator-reuse observer test or native hook added.

P4 documentation updates:
README request-ID boundary, WebSocket prompt-wake contract, implementation notes, and documentation contract assertions added/updated.

Local validation:
No normal local checkout/execution surface was available in the ChatGPT environment.

Unavailable local validation, with reasons:
Direct outbound GitHub DNS/network access was unavailable; Rust/Python/shell/Docker/VNC/Compose execution was deferred to permanent exact-SHA workflows. No unavailable command is labeled locally passed.

Deferred follow-ups:
No P1-P4 requirement is deferred. Third-party/OS/toolkit/allocator/LibVNCClient/server/reverse-proxy/swap/crash-dump residual-memory boundaries remain explicit non-guarantees.
```

Acceptance condition:

- [x] This TODO is complete only when the exact final documentation-completion repository tip is green in both CI and Release Gates. That condition is verified externally after commit creation.

---

## Final do-not-accept checklist

- [x] No older-SHA, canceled-run, superseded-run, red-run, or partial-run evidence is used for completion.
- [x] No CI or Release Gate is weakened, skipped, or converted to advisory-only.
- [x] No `continue-on-error`, broad ignore, forced success, swallowed exit code, or force push is used.
- [x] No generated request ID sequence can wrap into a normal reused request ID.
- [x] Request ID exhaustion does not panic, silently saturate, or execute the tested normal handler without a valid normal request ID.
- [x] EventHub established clients are not heartbeat-bound after terminal exhaustion.
- [x] WebSocket exhaustion close remains code `1011` with exact reason `event sequence exhausted`.
- [x] No native scrub test reads freed memory or depends on allocator reuse.
- [x] No command payload, typed text, clipboard text, key name, coordinate, bearer token, VNC password, framebuffer byte, screenshot byte, or query secret was introduced into diagnostics/logs.
- [x] No documentation claims third-party, OS, toolkit, allocator, VNC-server, LibVNCClient, reverse-proxy, swap, or crash-dump copies are scrubbed without evidence.
- [x] No secret-bearing config type regained implicit general-purpose `Clone`.
- [x] API bearer token remains `ApiToken -> Arc<SecretString>` shared ownership rather than raw ordinary string ownership.
- [x] `HttpBackend` command metric methods remain explicit with no silent zero defaults.
- [x] Old queue-depth metric alias was not reintroduced.
- [x] No active temporary patcher workflow or recovery script was introduced.
- [x] No broad Gitleaks ignore, path ignore, wildcard ignore, or rule suppression was introduced.
