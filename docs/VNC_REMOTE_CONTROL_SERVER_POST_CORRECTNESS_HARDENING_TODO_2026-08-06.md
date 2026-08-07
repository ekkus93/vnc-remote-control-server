# VNC Remote Control Server Post-Correctness Hardening TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_SPEC_2026-08-06.md`

Implementation notes: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_IMPLEMENTATION_NOTES_2026-08-06.md`

Reviewed baseline SHA: `96836f7ff964813fb727a1f7407fb0b1f448b738`

Status: implementation complete. This documentation-completion commit is considered fully closed only when its own exact-tip CI and Release Gates are green; those future SHA/run IDs are recorded externally after commit rather than falsely embedded here.

---

## H0. Ground rules and baseline protection

- [x] Confirmed work was performed against `master`.
- [x] Recorded the hardening source-edit starting SHA: `acee2808bae8a97710c881525e78eb6f5d1d6abb`.
- [x] Read the post-correctness hardening spec and preserved the accepted correctness-review contracts.
- [x] Historical completed work was not reopened without source/test evidence of regression.
- [x] CI, Release Gates, sanitizers, Gitleaks, ShellCheck, actionlint, Dockerfile/Compose checks, dependency policy, auditable-binary checks, Trivy, SBOM, and VEX enforcement were not weakened.
- [x] No `continue-on-error`, broad ignore, suppressed exit code, or force push was accepted as completion evidence.
- [x] Source work remained scoped to H1-H6 plus directly related validation repairs.

Acceptance:

- [x] Starting SHA is recorded below.
- [x] No unrelated feature or architectural work is mixed into the hardening result.

---

## H1. Repair CR12 mismatched-frame evidence gap

Source:

- `crates/controller-api/src/worker/tests/reconnect.rs`

Completed:

- [x] Inspected and preserved `mismatched_native_frame_never_reaches_connected`.
- [x] Negative fixture observes causal worker poll progress through the channel.
- [x] Mismatched display/framebuffer revision does not reach `ConnectionState::Connected`.
- [x] `fatal_exit` remains false.
- [x] `framebuffer_snapshot()` remains unavailable.
- [x] Added adjacent positive-control fixture `MatchingFrameSession` using the same worker/session observation path.
- [x] Matching native revision is observed and reaches `Connected`.
- [x] Positive control obtains a current framebuffer snapshot.
- [x] Positive control proves non-no-op behavior with worker framebuffer revision `1` and first canonical RGBA pixel `[0x22, 0x22, 0x22, 0xff]`.
- [x] Negative evidence is not sleep-only.
- [x] Existing mismatch assertions were not weakened.

Validation:

- [x] Targeted CR12 repair tests passed during the recovery loop.
- [x] Full `controller-api` library tests passed during the recovery loop and again through permanent workspace tests.

Acceptance:

- [x] CR12 evidence now contains both causal negative proof and a close positive control.

---

## H2. Replace EventHub sequence exhaustion panic with fail-closed behavior

Sources:

- `crates/controller-api/src/events.rs`
- `crates/controller-api/src/http/handlers.rs`
- WebSocket/OpenAPI tests and documentation

Completed:

- [x] Located the process-local EventHub sequence allocation path.
- [x] Removed panic/`expect` behavior for event sequence exhaustion.
- [x] Sequence allocation uses checked atomic increment semantics.
- [x] Exhaustion cannot wrap, reuse a prior public sequence, silently saturate at `u64::MAX`, or panic in the bridge/request path.
- [x] Exhaustion transitions the hub to an explicit terminal exhausted state.
- [x] First transition emits the payload-free `event_hub_sequence_exhausted` diagnostic once.
- [x] Subsequent bridge publication fails closed rather than manufacturing event IDs.
- [x] Initial snapshot exhaustion maps to bounded HTTP `503 event_sequence_exhausted` before WebSocket upgrade.
- [x] Established WebSockets close with code `1011`, reason `event sequence exhausted`, no later than the bounded heartbeat wake-up.
- [x] Normal event sequences remain strictly increasing.
- [x] Snapshot and worker-event bodies remain payload-free.
- [x] Diagnostic/close behavior contains no request body, typed text, clipboard payload, key name, coordinates, framebuffer/screenshot bytes, token, password, or query secret.

Validation:

- [x] Unit test forces sequence exhaustion at `u64::MAX` without panic.
- [x] Pre-upgrade snapshot failure mapping and permit release are tested.
- [x] Existing monotonic and normal-delivery coverage passes.

Acceptance:

- [x] Event sequence exhaustion is explicit, bounded, payload-free, and fail closed.

---

## H3. Move API bearer token storage to an explicit secret type

Sources:

- `crates/controller-api/src/config.rs`
- `crates/controller-api/src/http/state.rs`
- authentication support/middleware/tests
- `SECURITY.md`

Completed:

- [x] Replaced long-lived raw `Arc<str>` API-token ownership with explicit `ApiToken` backed by `Arc<SecretString>`.
- [x] `ApiToken` has no value-exposing `Debug` or `Display` implementation.
- [x] Cloned controller/router state clones only the shared secret owner, not ordinary plaintext token strings.
- [x] Authentication boundary borrows bytes for the existing constant-time comparison.
- [x] Missing bearer header remains rejected.
- [x] Query-token authentication remains rejected.
- [x] Wrong token remains rejected.
- [x] Correct `Authorization: Bearer ...` remains accepted.
- [x] Empty token remains rejected during validated construction.
- [x] Config `Debug` redaction remains explicit.
- [x] Access logging remains redacted and privacy tests do not expose the token.

Validation:

- [x] Config redaction, bearer comparison, auth routing, privacy, HTTP, and WebSocket integration coverage passed in permanent CI.

Acceptance:

- [x] API token is no longer stored as a long-lived ordinary plaintext string owner.
- [x] Public authentication behavior is unchanged except for stronger internal secret ownership.

---

## H4. Scrub secret-file raw bytes on rejection paths

Source:

- `crates/controller-api/src/config.rs`
- safe scrub entry point in `libvnc-adapter`

Completed:

- [x] Secret parsing owns one live raw byte vector through UTF-8 validation and trimming.
- [x] Existing metadata, regular-file, size, and Unix permission checks remain in force.
- [x] Invalid UTF-8 rejection scrubs the live raw buffer before return.
- [x] Empty-after-CR/LF-trim rejection scrubs the live raw buffer before return.
- [x] Embedded-NUL rejection scrubs the live raw buffer before return.
- [x] Parser rejection routes through one scrub-before-error boundary.
- [x] Trailing CR/LF bytes are scrubbed before successful truncation.
- [x] Successful parse transfers the owned allocation into `SecretString` without an unnecessary additional ordinary plaintext copy.
- [x] Error messages remain redaction-safe.
- [x] Tests observe live buffers before ownership ends; no freed-memory inspection is used.

Validation:

- [x] Invalid UTF-8, embedded NUL, empty-after-trim, valid secret, permission, and metadata tests pass.

Acceptance:

- [x] Parser-owned secret-file bytes are explicitly scrubbed before rejection-path drop.

---

## H5. Scrub project-owned native clipboard/transient text buffers and document the boundary

Sources:

- `crates/libvnc-adapter/native/vnc_shim.c`
- `SECURITY.md`
- `docs/OPERATOR_GUIDE.md`
- native/documentation contract tests

Completed:

- [x] Project-owned native clipboard/transient allocations have an explicit scrub-before-free policy.
- [x] `vrc_release_clipboard` scrubs stored clipboard bytes, including the terminating NUL, before free.
- [x] `vrc_store_clipboard` scrubs the old stored clipboard before replacement.
- [x] `vrc_client_destroy` scrubs the active stored clipboard before destruction.
- [x] `vrc_client_send_clipboard` scrubs its outbound temporary C copy before free on success and failure.
- [x] Clipboard revision exhaustion is rejected before allocation/replacement.
- [x] Existing VNC password scrub behavior remains intact.
- [x] Documentation distinguishes project-owned C buffers from Rust request/response values, Axum buffers, Tk/test-app state, LibVNCClient, VNC-server, toolkit/OS clipboard managers, clients, allocator residuals, swap, and crash dumps.
- [x] No broad claim says all clipboard copies are scrubbed.
- [x] Clipboard payloads remain excluded from logs, metrics, and events.

Validation:

- [x] Native/source contract tests protect scrub-before-free ordering.
- [x] Native adapter smoke passed.
- [x] WorkerHandle text/clipboard E2E passed.
- [x] HTTP/privacy/integration coverage passed.

Acceptance:

- [x] Project-owned native clipboard/transient buffers have a tested scrub policy and accurately documented ownership boundary.

---

## H6. Remove silent default metric methods from `HttpBackend`

Sources:

- `crates/controller-api/src/http/backend.rs`
- production and test/mock `HttpBackend` implementations

Completed:

- [x] Removed default implementation of `command_submissions_in_flight()`.
- [x] Removed default implementation of `command_queue_capacity()`.
- [x] Both are required trait methods.
- [x] Production implementation returns explicit worker values.
- [x] Mocks/test backends implement explicit intentional values.
- [x] Metric names remain `vrc_worker_command_submissions_in_flight` and `vrc_worker_command_queue_capacity`.
- [x] Metric help/type metadata remains intact.
- [x] Removed queue-depth metric alias was not restored.
- [x] No `unwrap_or(0)` or equivalent silent production fallback was introduced.

Validation:

- [x] HTTP metrics/workspace tests pass.
- [x] Trait omission is compile-time visible because methods are required.

Acceptance:

- [x] A backend cannot silently report zero by omitting either command metric method.

---

## H7. Documentation updates

Completed:

- [x] `SECURITY.md` documents API-token secret ownership/lifecycle.
- [x] `SECURITY.md` documents rejected secret-file scrubbing.
- [x] `SECURITY.md` and `docs/OPERATOR_GUIDE.md` document the native clipboard ownership/scrub boundary without third-party overclaiming.
- [x] Operator/WebSocket/OpenAPI documentation describes EventHub exhaustion and `503 event_sequence_exhausted` / established-client `1011` behavior.
- [x] Implementation notes record that the CR12 repair is test-evidence hardening rather than an intentional public runtime change.
- [x] Public error-envelope behavior from H2 is documented.
- [x] Explicit residual boundaries/deferrals are recorded in implementation notes.

Acceptance:

- [x] Documentation matches the implemented contracts.
- [x] Documentation does not claim third-party, OS, toolkit, allocator, VNC-server, or LibVNCClient-owned clipboard copies are scrubbed without evidence.

---

## H8. Local validation disposition

The ChatGPT execution container could not obtain a normal local repository checkout because outbound GitHub DNS/direct network access was unavailable. Therefore the commands below were **not** represented as locally passed. The corresponding permanent workflow steps executed successfully on exact SHA `d618d56807c416547ed54cdd95bb4c824abdea84`.

Repository-quality commands, disposition satisfied by permanent CI run `31144227898`:

- [x] `cargo fetch --locked` — permanent CI success; unavailable locally.
- [x] `cargo fmt --all --check` — permanent CI success; unavailable locally.
- [x] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings` — permanent CI success; unavailable locally.
- [x] `cargo test --locked --workspace --all-features` — permanent CI success; unavailable locally.
- [x] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps` — permanent CI success; unavailable locally.
- [x] `python -m compileall -q tools/ci_status tests desktop/test-app` — permanent CI success; unavailable locally.
- [x] `python -m unittest discover -s tests -p 'test_*.py' -v` — permanent CI success; unavailable locally.
- [x] Permanent shell syntax checks — permanent CI success; unavailable locally.

Docker/VNC surfaces, disposition satisfied by permanent CI run `31144227898`:

- [x] `tests/desktop/run.sh` — desktop smoke success; unavailable locally.
- [x] `tests/native/run.sh` — native adapter smoke success; unavailable locally.
- [x] `tests/worker-e2e/run.sh` — WorkerHandle TigerVNC input E2E success; unavailable locally.
- [x] `tests/worker-text-clipboard-e2e/run.sh` — text/clipboard E2E success; unavailable locally.
- [x] `tests/http-e2e/run.sh` — authenticated HTTP TigerVNC E2E success; unavailable locally.
- [x] `tests/compose/run.sh` — controller image/Compose/persistence smoke success; unavailable locally.
- [x] `tests/integration/run.sh` — R13 Compose integration/E2E success; unavailable locally.

- [x] Every unavailable local surface and its reason is recorded.
- [x] No unavailable local command is claimed to have passed locally.

Acceptance:

- [x] All locally available analysis/inspection work completed.
- [x] Unavailable execution surfaces were explicitly deferred to and passed by exact-SHA permanent workflows.

---

## H9. Exact-SHA permanent validation

Validated implementation SHA before documentation finalization:

`d618d56807c416547ed54cdd95bb4c824abdea84`

- [x] Implementation changes were committed intentionally and pushed to `master` without force.
- [x] CI ran on the exact SHA.
- [x] Release Gates ran on the exact SHA.
- [x] CI run `31144227898` concluded `success`.
  - [x] Repository quality gates: success.
  - [x] Secured Debian desktop/native integration job: success.
  - [x] Desktop smoke: success.
  - [x] Native adapter smoke: success.
  - [x] WorkerHandle input E2E: success.
  - [x] WorkerHandle text/clipboard E2E: success.
  - [x] Authenticated HTTP E2E: success.
  - [x] Compose/persistence: success.
  - [x] R13 Compose integration/E2E: success.
- [x] Release Gates run `31144227952` concluded `success`.
  - [x] Static/supply-chain policy: success.
  - [x] Full-history Gitleaks: success.
  - [x] ShellCheck/actionlint: success.
  - [x] Dockerfile/Compose validation: success.
  - [x] Advisory/license/source/duplicate policy: success.
  - [x] Auditable binary metadata verification: success.
  - [x] ASan: success.
  - [x] controller-api TSan: success.
  - [x] remote-desktop-core TSan: success.
  - [x] Miri boundary: success.
  - [x] Trivy/SBOM/VEX: success.
- [x] Validation failures encountered during the loop were repaired at their root; gates/assertions were not weakened.
- [x] Canceled, superseded, older-SHA, and partial runs are not used as completion evidence.

Acceptance:

- [x] The same exact implementation SHA passed CI and Release Gates.

---

## H10. Final evidence and completion report

- [x] Implementation was completed before documentation finalization.
- [x] Evidence block is filled below.
- [x] Added `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_IMPLEMENTATION_NOTES_2026-08-06.md`.
- [x] Documentation/evidence changes are committed intentionally and pushed without force.
- [x] This completion record explicitly requires exact-tip CI and Release Gates for the documentation-completion commit.
- [x] Future final documentation-tip SHA/run IDs are recorded externally after the workflows complete rather than pretending this commit can embed its own future hash or run IDs.

Final evidence:

```text
Reviewed correctness baseline SHA:
96836f7ff964813fb727a1f7407fb0b1f448b738

Hardening source-edit starting SHA:
acee2808bae8a97710c881525e78eb6f5d1d6abb

Validated implementation SHA before final documentation:
d618d56807c416547ed54cdd95bb4c824abdea84

Implementation-notes commit:
5d3c3f2cd9faea42e288ef8181f8f450bcf84af6

Final documentation-completion SHA:
This TODO completion commit; exact SHA is recorded externally after commit creation.

Final repository-tip SHA:
Same final documentation-completion commit, provided no repair is required by its exact workflows; recorded externally.

Implementation CI run ID and conclusion:
31144227898 — success

Implementation Release Gates run ID and conclusion:
31144227952 — success

Final documentation-tip CI/Release run IDs:
Recorded externally after this commit's exact workflows complete.

H1 CR12 evidence repair:
Causal mismatched-frame negative proof retained; adjacent matching-frame positive control reaches Connected and proves canonical framebuffer content/revision.

H2 EventHub sequence exhaustion:
Checked atomic allocation; no wrap/reuse/silent saturation/panic; one payload-free terminal diagnostic; initial 503 before upgrade; established clients close 1011 within bounded heartbeat wake-up.

H3 API token secret lifecycle:
Long-lived token ownership is ApiToken -> Arc<SecretString>; no value Debug/Display; constant-time auth comparison and redacted logging preserved.

H4 secret-file rejection scrubbing:
One owned byte vector is scrubbed on invalid UTF-8, empty-after-trim, embedded NUL, and parser rejection; trailing CR/LF bytes scrubbed before successful truncation; no freed-memory tests.

H5 native clipboard/transient buffer policy:
Project-owned stored and outbound C clipboard buffers scrub before replacement/free; third-party/OS/toolkit/allocator residuals explicitly outside the guarantee.

H6 HttpBackend metric defaults:
Both command metric methods are required with explicit production/mock implementations; no default zero and no old queue-depth alias.

Local validation:
No normal local checkout/execution surface was available in the ChatGPT container.

Unavailable local validation, with reasons:
Outbound GitHub DNS/direct network access was unavailable, so repository execution was deferred to permanent exact-SHA workflows. No unavailable command is labeled locally passed.

Deferred follow-ups:
No H1-H6 requirement is deferred. Documented third-party password/clipboard residual boundaries remain explicit non-guarantees rather than unfinished hardening tasks.
```

Acceptance condition:

- [x] This TODO is complete **only when** the exact final documentation-completion repository tip is green in both CI and Release Gates. The condition is external to this file and is verified after commit creation.

---

## Final do-not-accept checklist

- [x] No sleep-only negative proof remains for the CR12 mismatched-frame test.
- [x] No EventHub event sequence can wrap, reuse, silently saturate, or panic on exhaustion.
- [x] No API bearer token is stored as long-lived raw `Arc<str>` or equivalent ordinary string ownership.
- [x] No invalid-UTF-8 secret-file path drops parser-owned raw secret bytes without explicit scrub.
- [x] No project-owned native clipboard buffer is replaced or destroyed without the scrub policy.
- [x] No documentation claims third-party, OS, toolkit, allocator, VNC-server, or LibVNCClient-owned clipboard copies are scrubbed without evidence.
- [x] No `HttpBackend` command metric method silently defaults to zero.
- [x] No old queue-depth metric alias is reintroduced.
- [x] No accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, or R13 behavior is weakened.
- [x] No command payload, typed text, clipboard text, key name, coordinate, bearer token, VNC password, framebuffer byte, screenshot byte, or query secret is introduced into diagnostics/logs.
- [x] No `continue-on-error`, broad ignore, suppressed exit code, force push, or older-SHA evidence is accepted.
