# VNC Remote Control Server Post-Final-Polish Review Fix TODO

Date: 2026-08-07

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_SPEC_2026-08-07.md`

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Reviewed code baseline SHA: `b1ce8addc846ef8f55f1ffeab5ecd82bfb9b235b`

Spec planning commit: `9095ecc1d96a010061ca463e05848c11f9e92eaa`

Implementation starting SHA: **record immediately before source changes begin**

Status: **not started**

---

## P0. Ground rules, baseline, and scope control

- [ ] Confirm the working branch is `master`.
- [ ] Fetch/pull current `master` and record the exact implementation starting SHA above.
- [ ] If `master` advanced beyond spec planning commit `9095ecc1d96a010061ca463e05848c11f9e92eaa`, inspect every intervening commit before editing.
- [ ] Read this TODO and the companion spec in full.
- [ ] Read `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_TODO_2026-08-06.md` and its implementation notes sufficiently to preserve all accepted P0-P7 behavior.
- [ ] Confirm the final-polish pass itself is not being reopened; this is a new review-fix pass.
- [ ] Record a baseline diff/file inventory for all source files expected to change.
- [ ] Do not mix unrelated feature work into this pass.
- [ ] Do not weaken CI, Release Gates, sanitizers, Gitleaks, ShellCheck, actionlint, Docker/Compose checks, dependency policy, auditable-binary checks, Trivy, SBOM, or VEX policy.
- [ ] Do not add `continue-on-error`, forced-success wrappers, swallowed nonzero exit codes, broad ignores, force pushes, or older-SHA evidence.
- [ ] Keep all new diagnostics payload-free and secret-free.

Expected source areas include, subject to actual implementation needs:

- `crates/controller-api/src/input.rs`
- `crates/controller-api/src/worker/**`
- `crates/controller-api/src/runtime.rs`
- `crates/controller-api/src/config.rs`
- `crates/controller-api/src/http/**`
- `crates/controller-api/src/observability.rs`
- `crates/libvnc-adapter/native/vnc_shim.[ch]`
- `crates/libvnc-adapter/src/lib.rs`
- `python/src/vnc_remote_control/client.py`
- `python/src/vnc_remote_control/models.py`
- hosted docs asset/source files
- `docs/openapi.json`
- README/operator/security/docs as behavior changes require
- Rust/Python/source-contract/integration tests.

Acceptance:

- [ ] Starting SHA and any intervening commits are explicitly recorded.
- [ ] Scope is limited to the review findings and dependencies required to implement them correctly.
- [ ] Existing accepted shutdown, framebuffer, authentication, request-ID, EventHub, ETag, privacy, native scrub, bounded-capacity, CI, and release contracts remain in force unless this spec explicitly changes one.

Do not accept:

- [ ] No unrelated refactor is justified merely as cleanup convenience.
- [ ] No pre-existing failing gate is ignored as "unrelated" without investigation.
- [ ] No implementation begins from an uninspected moving `master` tip.

---

## P1. Fix `TypeText` ownership of pre-held keys

Primary source:

- `crates/controller-api/src/input.rs`

Likely tests:

- existing input-controller unit tests in `input.rs`
- WorkerHandle input/text E2E tests
- HTTP keyboard tests if useful.

### P1.1 Reproduce the baseline defect

- [ ] Add a regression test in which a printable key is explicitly pressed before `TypeText` is asked to type the same logical key.
- [ ] Prove the reviewed baseline behavior would release/remove that pre-held key or otherwise violate ownership.
- [ ] Add equivalent pre-held `Enter` versus newline/CR coverage.
- [ ] Add equivalent pre-held `Tab` versus tab coverage.
- [ ] Keep regression sentinels out of logs.
- [ ] Record baseline-failing test evidence in implementation notes or commit history before fixing where practical.

### P1.2 Add complete text-key preflight

- [ ] Reuse the existing text validator before any native event.
- [ ] Centralize character-to-`KeyboardKey` mapping so preflight and execution cannot drift.
- [ ] Snapshot/inspect the keys held before the command starts.
- [ ] Reject `TypeText` before its first native event if any synthesized key collides with a pre-command held key.
- [ ] Use a bounded `DesktopError::Configuration` or equivalent request error that does not embed the character/text payload.
- [ ] Do not silently skip the character.
- [ ] Do not synthesize a key-up for a key the text command did not own.

### P1.3 Preserve normal text behavior

- [ ] Repeated characters inside one text command remain valid.
- [ ] Normal newline/CR -> Enter mapping remains unchanged when Enter is not pre-held.
- [ ] Normal tab -> Tab mapping remains unchanged when Tab is not pre-held.
- [ ] Printable-character behavior remains unchanged when no collision exists.
- [ ] Existing unsupported-character and text-size validation remains preflighted.

### P1.4 Preserve failure cleanup

- [ ] A native key-up failure after a text-generated key-down still leaves unresolved generated key state tracked for later cleanup.
- [ ] Retry/best-effort release logic must not clear unrelated pre-held keys.
- [ ] Existing chord ownership semantics remain unchanged.

Tests:

- [ ] `type_text_rejects_preheld_printable_key_without_side_effects` or equivalent.
- [ ] `type_text_rejects_preheld_enter_without_side_effects`.
- [ ] `type_text_rejects_preheld_tab_without_side_effects`.
- [ ] `type_text_allows_repeated_characters_when_not_preheld`.
- [ ] key-up-failure tracking regression test.
- [ ] Existing input unit suite passes unchanged except intentionally updated expectations.
- [ ] Add E2E coverage for held-key/text interaction if deterministic with the existing test desktop.

Acceptance:

- [ ] `TypeText` owns and releases only transitions it created.
- [ ] Collision is rejected atomically before any text-generated native event.
- [ ] Caller-owned held state survives the rejected command unchanged.

Do not accept:

- [ ] Do not "fix" this by clearing `pressed_keys` before typing.
- [ ] Do not automatically release caller-held keys and then restore them afterward.
- [ ] Do not silently skip colliding characters.
- [ ] Do not partially type a prefix before detecting the collision.

---

## P2. Make Python typed HTTP response decoding strict

Primary sources:

- `python/src/vnc_remote_control/client.py`
- `python/src/vnc_remote_control/models.py`
- `python/src/vnc_remote_control/errors.py` if needed.

Primary tests:

- `tests/test_python_client.py`
- `tests/test_python_client_openapi_contract.py`

### P2.1 Inventory unsafe coercions

- [ ] Find all response-model uses of `int(...)`, `bool(...)`, `str(...)`, and `typing.cast(...)` that currently act as protocol validation.
- [ ] Inventory every typed HTTP response model and its OpenAPI schema.
- [ ] Inventory nullable fields and closed enums separately.
- [ ] Confirm WebSocket parser behavior is already stricter and does not regress.

### P2.2 Add reusable exact validators

Implement narrow helpers, naming as appropriate, for:

- [ ] required object/map;
- [ ] required field set;
- [ ] exact string;
- [ ] exact bool;
- [ ] exact integer that rejects Python `bool`;
- [ ] nullable string;
- [ ] nullable integer;
- [ ] closed string enum;
- [ ] integer range constraints where OpenAPI specifies them;
- [ ] unknown-field rejection where OpenAPI has `additionalProperties: false`.

Requirements:

- [ ] Validator failures raise `ProtocolError`.
- [ ] Errors identify the response/field structurally but do not copy arbitrary response payload values into exception text.
- [ ] `typing.cast()` is permitted only after runtime validation, never instead of validation.

### P2.3 Convert every typed HTTP decoder

- [ ] `get_liveness()`.
- [ ] `get_readiness()`.
- [ ] `get_status()`.
- [ ] `get_display()`.
- [ ] command acknowledgement decoder.
- [ ] `get_clipboard()`.
- [ ] screenshot typed metadata/header assumptions.
- [ ] structured API-error envelope.
- [ ] any other typed model added after the reviewed baseline.
- [ ] `get_openapi_document()` retains its promised mapping/object contract without pretending to be a full generated OpenAPI validator.

### P2.4 Add malformed-response tests

At minimum prove `ProtocolError` for:

- [ ] `"false"` where bool required.
- [ ] `0` or `1` where bool required.
- [ ] `"1280"` where integer required.
- [ ] `true` where integer required.
- [ ] integer where string required.
- [ ] object/list where string required.
- [ ] unknown `ConnectionState`.
- [ ] unknown `WorkerFailure`.
- [ ] invalid command status.
- [ ] invalid nullable type.
- [ ] missing required field.
- [ ] extra field when schema forbids additional properties.

### P2.5 Preserve static typing quality

- [ ] Ruff passes with no new broad ignores.
- [ ] Pylint passes with no new broad disables.
- [ ] Mypy passes with no new `# type: ignore` used merely to avoid proper narrowing.
- [ ] Public client method return annotations remain accurate.

Acceptance:

- [ ] Malformed response JSON can no longer be normalized into apparently valid typed values.
- [ ] The Python HTTP parser is at least as type-strict as the existing WebSocket envelope parser for common primitives.

Do not accept:

- [ ] No `bool(value)` for server booleans.
- [ ] No `int(value)` for server integers unless exact integer type was already validated.
- [ ] No `str(value)` for server strings unless exact string type was already validated.
- [ ] No bare `cast()` as runtime protocol validation.

---

## P3. Make unexpected worker event receiver loss fail closed

Primary sources:

- `crates/controller-api/src/worker/loop_state.rs`
- worker loop/run/state files needed to propagate terminal failure
- event bridge/shutdown code as needed.

### P3.1 Refactor event publication result

- [ ] Change `LoopState::publish()` or its replacement so it can report terminal publication failure instead of swallowing it.
- [ ] Keep `TrySendError::Full` as the existing bounded overload/drop condition.
- [ ] Change unexpected `TrySendError::Disconnected` into an explicit terminal error.
- [ ] Do not log repeatedly on every later attempted event.

### P3.2 Terminalize receiver disconnection

On first unexpected disconnection:

- [ ] Emit one fixed payload-free `worker_event_receiver_disconnected` diagnostic or equivalent.
- [ ] Mark the worker unhealthy/fatal for readiness/command service.
- [ ] Stop accepting new commands.
- [ ] Invalidate current framebuffer state where the existing fatal/disconnect path requires it.
- [ ] Perform tracked input release/abandon through existing bounded cleanup semantics.
- [ ] Exit the worker loop or enter the established terminal state.
- [ ] Ensure HTTP does not continue presenting a healthy ready controller after the event subsystem is irrecoverably gone.

### P3.3 Preserve orderly shutdown

- [ ] Explicitly distinguish receiver loss after authoritative shutdown has begun.
- [ ] Do not generate a false fatal event merely because shutdown intentionally tears down the event bridge first/last according to current lifecycle ordering.
- [ ] Add a test for expected shutdown disconnection if race coverage requires it.

### P3.4 Terminalize worker event sequence exhaustion

- [ ] Retain `checked_add`.
- [ ] Add/confirm once-only payload-free `worker_event_sequence_exhausted` diagnostic.
- [ ] On exhaustion, stop normal worker operation rather than returning from a single `publish()` and continuing.
- [ ] Do not wrap, reset, or reuse sequence IDs.
- [ ] Use deterministic test injection/start-near-max state.

Tests:

- [ ] unexpected receiver drop becomes terminal and observable.
- [ ] no further command is accepted after terminal event-subsystem loss.
- [ ] full queue remains nonfatal bounded overload and increments the correct counter.
- [ ] orderly shutdown receiver loss does not emit a false runtime-fatal diagnostic.
- [ ] event sequence exhaustion becomes terminal with no wraparound.
- [ ] diagnostic count is bounded/once-only.

Acceptance:

- [ ] An unexpectedly dead worker event receiver cannot produce silent control-without-events operation.
- [ ] Event sequence exhaustion cannot leave the worker apparently healthy.

Do not accept:

- [ ] No `Err(TrySendError::Disconnected(_)) => {}` in the reviewed production publication path.
- [ ] No retry/spin loop against a permanently disconnected receiver.
- [ ] No new unbounded event queue.

---

## P4. Observe HTTP connection failures and task panics

Primary source:

- `crates/controller-api/src/runtime.rs`

Related:

- `crates/controller-api/src/observability.rs`
- runtime tests.

### P4.1 Return classified connection outcomes

- [ ] Refactor `serve_connection()` to return a bounded outcome/result instead of always `()` while discarding Hyper results.
- [ ] Distinguish clean completion, expected peer/protocol disconnect, unexpected runtime failure, shutdown cancellation/abort, and task panic at the `JoinSet` boundary.
- [ ] Do not include raw request data in the outcome.

### P4.2 Inspect `JoinSet` results

- [ ] Remove blind `let _ = result` for normal connection-task joins.
- [ ] A `JoinError::is_panic()` outcome emits an `error` diagnostic.
- [ ] Expected cancellation during forced bounded shutdown is classified separately.
- [ ] Unexpected task cancellation outside shutdown is observable.
- [ ] Unexpected Hyper/server error is a bounded diagnostic.
- [ ] Routine remote disconnect/noise may remain debug/unlogged when deliberately classified.

### P4.3 Preserve bounded shutdown

- [ ] Retain configured graceful drain timeout.
- [ ] Retain forced abort after grace expiration.
- [ ] Continue draining aborted tasks after `abort_all()`.
- [ ] Inspect already-completed panic/error results instead of erasing them during shutdown.

### P4.4 Pre-router terminal failures

- [ ] Review header timeout, body timeout, body-too-large, and body-read failure paths.
- [ ] Preserve the existing bounded terminal response behavior.
- [ ] Add fixed metrics/diagnostics where useful without reading/logging payloads.
- [ ] Do not route these through auth solely for observability.

Tests:

- [ ] connection task panic is detected/logged by the owner.
- [ ] controlled client disconnect does not become a process-fatal error.
- [ ] graceful shutdown remains bounded.
- [ ] forced abort is classified as shutdown behavior.
- [ ] runtime diagnostics contain no authorization/body/query sentinels.

Acceptance:

- [ ] A panicked connection task can no longer disappear through `let _ = result`.
- [ ] Routine client network behavior does not destabilize the controller.

Do not accept:

- [ ] No logging of raw Hyper error text if it can contain attacker-controlled request material; classify safely.
- [ ] No process-wide crash merely because one client disconnects badly.

---

## P5. Replace silent mutex-poison recovery with explicit terminal policy

Primary areas:

- worker helper locking
- framebuffer locking
- screenshot permit/state locking
- any other production `Mutex` using `into_inner()` after poison.

### P5.1 Inventory poison recovery

- [ ] Search all production Rust for `PoisonError`, `into_inner()`, `unwrap_or_else(|poisoned|`, and mutex lock helpers.
- [ ] Classify each protected value as authoritative state, benign cache/counter, or terminal-cleanup-only state.
- [ ] Record the disposition of each occurrence in implementation notes.

### P5.2 Remove silent healthy continuation

For authoritative state:

- [ ] Detect poison explicitly.
- [ ] Emit a fixed payload-free invariant diagnostic.
- [ ] Fail command/readiness/state operation closed.
- [ ] Trigger the safest existing terminal/fatal path when continued correctness cannot be established.
- [ ] Do not simply recover the guard and return normal data.

### P5.3 Terminal cleanup exception

Where `into_inner()` remains:

- [ ] It is used only after the system is committed to terminal cleanup/diagnostic handling.
- [ ] The code contains a concise comment explaining why reading/mutating the poisoned state is safe enough for that cleanup.
- [ ] Normal service cannot resume afterward.
- [ ] A diagnostic makes the poison visible.

### P5.4 Avoid fake fixes

- [ ] Do not switch to a non-poisoning mutex solely to hide poison signaling.
- [ ] Do not use `unwrap()`/panic everywhere as a shortcut unless a particular invariant proves process termination is the only sound behavior and that decision is documented.

Tests:

- [ ] deterministically poison representative authoritative state in unit tests where feasible.
- [ ] prove the next normal operation does not silently succeed from poisoned state.
- [ ] prove terminal cleanup does not deadlock.
- [ ] privacy-test poison diagnostics for payload-free fields.

Acceptance:

- [ ] No generic production lock helper silently unpoisons authoritative state and resumes healthy operation.

Do not accept:

- [ ] No warning-only behavior followed by normal success when protected invariants may be half-mutated.

---

## P6. Make all controller environment configuration reject non-Unicode values

Primary source:

- `crates/controller-api/src/config.rs`

### P6.1 Change environment abstraction

- [ ] Replace `EnvironmentSource::get(...) -> Option<String>` with a representation that distinguishes absent, Unicode, and non-Unicode values.
- [ ] Production `ProcessEnvironment` maps `VarError::NotPresent` to absent/default eligibility.
- [ ] Production `ProcessEnvironment` maps `VarError::NotUnicode` to a bounded configuration error.
- [ ] Test/mock environment implementation supports deterministic non-Unicode values where the platform permits it.

### P6.2 Apply consistently

- [ ] `VRC_LISTEN_ADDR`.
- [ ] `VRC_API_TOKEN_FILE` path.
- [ ] `VRC_VNC_PASSWORD_FILE` path.
- [ ] `VRC_PROCESS_INSTANCE`.
- [ ] `VRC_VNC_HOST`.
- [ ] all numeric/time/capacity `VRC_*` settings handled by this config loader.
- [ ] confirm HTTP `RuntimeSettings` keeps its existing explicit `NotUnicode` rejection.

### P6.3 Tests

- [ ] absent value uses documented default.
- [ ] valid Unicode value uses configured value.
- [ ] non-Unicode value returns configuration error.
- [ ] non-Unicode secret path never falls back to default secret path.
- [ ] error text names only the configuration key, never secret bytes/path garbage.

Acceptance:

- [ ] Present-but-invalid environment values can no longer masquerade as absent configuration.

Do not accept:

- [ ] No `.ok()` conversion of `env::var()` at the production configuration boundary.

---

## P7. Self-host Swagger UI and ReDoc assets

Primary sources:

- `crates/controller-api/src/http/docs_ui.rs`
- `crates/controller-api/src/http/router.rs`
- controller Docker build context
- hosted docs contract tests
- README/docs.

### P7.1 Vendor exact third-party assets

Keep unless separately justified:

- [ ] Swagger UI `5.32.11`.
- [ ] ReDoc `2.5.3`.

For every vendored runtime asset:

- [ ] store under an explicit third-party/vendor path;
- [ ] include/retain required upstream license notice;
- [ ] record upstream package/version/source in a small manifest or documentation file;
- [ ] record a SHA-256 digest in repository-owned contract data/tests;
- [ ] do not minify/rewrite the vendor file locally unless the transformation is deterministic and documented.

### P7.2 Serve locally

- [ ] Add local routes for Swagger CSS/JS and ReDoc JS.
- [ ] Change `/docs` HTML to local asset URLs only.
- [ ] Change `/redoc` HTML to local asset URLs only.
- [ ] Keep `/openapi.json` local/repository-owned.
- [ ] No controller startup/runtime network fetch.

### P7.3 Tighten CSP

- [ ] Swagger `script-src` uses `'self'` only for required script origin.
- [ ] Swagger `style-src` uses `'self'` as possible.
- [ ] ReDoc `script-src` uses `'self'`.
- [ ] Keep `connect-src 'self'`.
- [ ] Keep `frame-ancestors 'none'`.
- [ ] Keep `base-uri 'none'`.
- [ ] Keep `form-action 'none'`.
- [ ] Keep `persistAuthorization: false`.
- [ ] Keep `validatorUrl: null`.
- [ ] If ReDoc requires `'unsafe-inline'` style, document and test that only style—not script—needs it.

### P7.4 Tests and offline proof

- [ ] Hosted docs source contains no runtime `https://cdn...` or other external script/style URL.
- [ ] HTML references only local controller asset paths.
- [ ] Every referenced asset route returns expected content type and bytes/digest.
- [ ] Asset digest contract catches unreviewed replacement.
- [ ] README no longer says UI assets load from CDNs.
- [ ] Controller image/build includes the vendored files needed to serve docs.
- [ ] Smoke test works without external network access.

Acceptance:

- [ ] Entering a bearer token into hosted Swagger does not require trusting third-party runtime JavaScript delivery.

Do not accept:

- [ ] Version-pinned CDN URLs alone are not sufficient.
- [ ] Do not fetch vendor assets in an entrypoint/startup script.
- [ ] Do not broaden CSP to `script-src *`, `unsafe-eval`, or unrestricted external origins.

---

## P8. Make missing request-ID state an explicit invariant failure

Primary sources:

- `crates/controller-api/src/http/ids.rs`
- request-ID middleware/support/error construction
- HTTP tests/documentation.

### P8.1 Audit current fallback

- [ ] Find every use of `request-id-unavailable` or equivalent missing-extension fallback.
- [ ] Determine whether normal Axum handlers can simply require `Extension<RequestId>` and remove the fallback entirely.
- [ ] Identify any middleware/error path that genuinely needs to construct an error before/without the extension.

### P8.2 Preferred implementation

- [ ] Remove unnecessary fallback helpers.
- [ ] Ensure protected and public routed requests pass through outer request-ID assignment before normal handlers.
- [ ] If a fallback is genuinely required for internal error construction, use an explicitly reserved non-normal invariant sentinel and HTTP `500 internal_error` semantics.
- [ ] Emit one bounded invariant diagnostic.
- [ ] Reject the invariant sentinel as a caller-provided normal ID.

### P8.3 Invalid caller IDs

- [ ] Preserve safe sanitization: invalid caller ID cannot become a response/log header value.
- [ ] Generate a fresh normal server ID when the global sequence is healthy.
- [ ] Do not log the raw invalid caller header.
- [ ] Document/test that invalid caller IDs are replaced rather than accepted.

### P8.4 Preserve final-polish exhaustion behavior

- [ ] terminal checked allocation remains unchanged.
- [ ] caller-provided valid ID cannot bypass terminal exhaustion.
- [ ] `503 request_id_exhausted` remains exact.
- [ ] `request-id-exhausted` remains reserved/non-normal.
- [ ] once-only payload-free diagnostic remains.

Tests:

- [ ] missing-extension/invariant path cannot return a normal successful handler response.
- [ ] invalid caller ID is replaced without raw-value logging.
- [ ] final-polish exhaustion regression tests still pass.

Acceptance:

- [ ] A router/programming invariant failure is no longer disguised as an ordinary correlation ID condition.

Do not accept:

- [ ] No panic containing request data.
- [ ] No caller-controlled fallback sentinel.

---

## P9. Make command-ID exhaustion explicit and terminal

Primary source:

- `crates/controller-api/src/worker/client.rs`

Related:

- `remote_desktop_core::DesktopError`
- HTTP error mapping
- worker snapshot/readiness state
- OpenAPI/Python error-code contracts
- tests/docs.

### P9.1 Add shared terminal allocator state

- [ ] Retain checked `u64` allocation.
- [ ] Add a shared terminal command-ID exhaustion flag/state across all `WorkerClient` clones.
- [ ] First exhausted allocation sets terminal state atomically.
- [ ] Later callers observe terminal state before enqueue.
- [ ] No reset/wrap/saturation/reuse path exists.

### P9.2 Add explicit domain/API error

- [ ] Add `DesktopError::CommandIdExhausted` or an equivalently precise bounded variant.
- [ ] Map to HTTP `503`.
- [ ] Add `error.code = "command_id_exhausted"`.
- [ ] Use message `command identifier sequence is exhausted` unless a better bounded wording is consistently adopted.
- [ ] Update OpenAPI error-code inventory.
- [ ] Update Python/OpenAPI contract tests.

### P9.3 Health and diagnostics

- [ ] Emit `worker_command_id_sequence_exhausted` once when terminal state is first reached.
- [ ] Diagnostic contains no command payload.
- [ ] Mark controller/worker not-ready for new command service.
- [ ] Ensure exhaustion is not confused with `command_queue_full` or transient worker disconnect.

### P9.4 Deterministic tests

- [ ] test hook/constructor starts allocator near `u64::MAX` without massive loops.
- [ ] last normal ID is unique.
- [ ] next allocation returns specific exhaustion error.
- [ ] failed command is not enqueued.
- [ ] later command is also rejected before enqueue.
- [ ] diagnostic occurs once.
- [ ] readiness/fatal state reflects terminal inability to accept commands.

Acceptance:

- [ ] Command sequence exhaustion is as explicit and non-reusable as request/EventHub sequence exhaustion.

Do not accept:

- [ ] No generic `WorkerUnavailable` as the only exhaustion signal.
- [ ] No fabricated/saturated final command ID.

---

## P10. Remove native error-message string matching from lifecycle classification

Primary sources:

- `crates/libvnc-adapter/native/vnc_shim.h`
- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/src/lib.rs`
- `crates/controller-api/src/worker/helpers.rs`
- native/worker privacy and smoke tests.

### P10.1 Add structured shim status

- [ ] Add a distinct `vrc_status` value for `InitialiseRFBConnection(...)` failure, named for what is actually known (for example `VRC_STATUS_PROTOCOL_INITIALIZATION_FAILED`).
- [ ] Return that status from the exact initialization failure path.
- [ ] Keep generic native failure for unrelated operations.
- [ ] Do not name the status `AUTHENTICATION_FAILED` unless the pinned native library exposes explicit trustworthy authentication evidence.

### P10.2 Add structured Rust native error

- [ ] Add corresponding numeric status constant.
- [ ] Add `NativeError::ProtocolInitializationFailed` or equivalent payload-free variant.
- [ ] Map status directly to the structured variant.
- [ ] Keep `last_error()` as diagnostic support only, not lifecycle classification input.

### P10.3 Remove string classification

- [ ] Delete `message.contains("protocol initialization failed")` or equivalent authentication inference.
- [ ] Classify structured initialization failure as `WorkerFailureKind::Protocol` (or a new explicitly justified initialization category), not authentication by default.
- [ ] Keep `AuthenticationFailed` only for genuinely structured authentication evidence if any exists.

### P10.4 Update tests

- [ ] Worker classification remains identical even if human-readable initialization message text changes.
- [ ] Wrong-password native smoke still fails closed and never leaks password.
- [ ] Update tests/docs that previously required an unproven `AuthenticationFailed` label for generic initialization failure.
- [ ] Privacy sentinel test proves message/password contents are not logged.
- [ ] Native status contract test verifies distinct numeric mapping.

Acceptance:

- [ ] Control flow no longer depends on matching generic human-readable native error text.
- [ ] Failure classification says only what the native boundary can actually prove.

Do not accept:

- [ ] No regex/substr matching as a replacement.
- [ ] No parsing of localized/upstream LibVNCClient stderr text.

---

## P11. Tighten smaller silent fallback paths

### P11.1 Tracing initialization

Primary source:

- `crates/controller-api/src/observability.rs`
- `main.rs`.

- [ ] Change tracing initialization to return explicit success/failure.
- [ ] Invalid configured `RUST_LOG`/filter fails process startup rather than silently falling back to `info`.
- [ ] Production failure to install the global tracing subscriber is propagated to startup and not ignored.
- [ ] Test-only capture subscribers remain isolated and deterministic.
- [ ] Error text does not contain secrets/request payloads.

Do not accept:

- [ ] No `try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"))` in production startup.
- [ ] No ignored production `try_init()` result.

### P11.2 Checked Unix timestamp conversion

Primary source:

- HTTP support/time helpers and call sites.

- [ ] Replace public timestamp `duration_since(UNIX_EPOCH).unwrap_or_default()` behavior.
- [ ] Replace `u64::try_from(...).unwrap_or(u64::MAX)` saturation where used for public timestamp semantics.
- [ ] Choose checked error/unavailable representation consistent with existing response schemas.
- [ ] If schema changes are needed, update OpenAPI/Python models/tests together.
- [ ] Add tests for pre-epoch and conversion-overflow test values without depending on the real system clock.

Do not accept:

- [ ] No ordinary `0` timestamp standing in for "clock invalid" unless the schema explicitly defines that sentinel (it currently does not).
- [ ] No ordinary `u64::MAX` saturation standing in for overflow.

### P11.3 Python malformed HTTP error envelopes

- [ ] Preserve empty-body handling for documented pre-router runtime errors.
- [ ] A non-empty malformed JSON/error envelope raises `ProtocolError` rather than silently falling back to a generic `ApiError`.
- [ ] Do not include arbitrary response bytes in exception text.
- [ ] Add tests for empty 400/408/413-style body versus malformed non-empty body.

### P11.4 Production ignored-result audit

Search at least:

- [ ] `let _ =`.
- [ ] `.ok()`.
- [ ] `unwrap_or_default()`.
- [ ] `unwrap_or(...)`.
- [ ] `Err(_) => {}`.
- [ ] ignored `send`/`recv`/`join` results.
- [ ] best-effort cleanup operations.

For each relevant production occurrence:

- [ ] classify as propagate, bounded-observe, terminal/fail-closed, or intentionally ignored;
- [ ] add a concise local comment for intentionally ignored ownership/lifecycle cases when the justification is not obvious;
- [ ] add tests for newly changed behavior where practical;
- [ ] record controversial retained ignores in implementation notes.

Explicitly preserve justified cases such as:

- [ ] completion send after caller timeout/drop;
- [ ] screenshot result send after request timeout while permit remains held;
- [ ] event broadcast with no replay listeners where contract permits it;
- [ ] best-effort input cleanup with unresolved state tracked and observable;
- [ ] normal shutdown queue send when out-of-band shutdown signal is authoritative.

Acceptance:

- [ ] Unexpected loss/invariant failures are not hidden behind generic ignored-result idioms.
- [ ] Intentional ownership-drop behavior remains concise and does not become noisy or over-engineered.

---

## P12. Documentation and public contract updates

Update only where behavior actually changes.

### P12.1 API/OpenAPI

- [ ] Add `command_id_exhausted` to the documented error-code contract.
- [ ] Keep request-ID exhaustion semantics unchanged.
- [ ] Update any status/readiness semantics changed by terminal command/event subsystem failure.
- [ ] Regenerate/update examples manually as appropriate; validate all examples against schema contracts.

### P12.2 Python client documentation

- [ ] Document strict protocol decoding and `ProtocolError` for malformed server responses.
- [ ] Document malformed non-empty error-envelope behavior.
- [ ] Preserve token privacy guidance.

### P12.3 Hosted docs documentation

- [ ] README says Swagger/ReDoc assets are served locally.
- [ ] Remove statements that runtime assets load from jsDelivr/redoc.ly.
- [ ] Document exact vendored versions and update procedure.
- [ ] Record licenses/source/digest verification location.

### P12.4 Operator/security documentation

- [ ] Document fail-closed event-subsystem behavior if operator-visible.
- [ ] Document command-ID terminal exhaustion if operator-visible.
- [ ] Document invalid non-Unicode environment configuration rejection where configuration guidance lists behavior.
- [ ] Document native initialization classification accurately without overclaiming authentication detection.
- [ ] Preserve third-party memory residual/non-guarantee language.

### P12.5 Implementation notes

Create:

- [ ] `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_IMPLEMENTATION_NOTES_2026-08-07.md`

It must record:

- [ ] exact starting SHA;
- [ ] confirmed baseline-failing regression tests;
- [ ] design decisions taken for poison/event/native error handling;
- [ ] justified retained ignored-result sites that might otherwise look suspicious;
- [ ] local validation actually performed;
- [ ] final exact-SHA permanent evidence.

Acceptance:

- [ ] Documentation describes actual implementation and does not claim evidence that was not produced.

Do not accept:

- [ ] No historical hardening document is rewritten to pretend this later pass already existed.

---

## P13. Contract, unit, integration, privacy, and regression tests

### P13.1 Rust unit tests

- [ ] input ownership/preflight tests from P1.
- [ ] worker event receiver disconnect tests from P3.
- [ ] worker event sequence exhaustion tests.
- [ ] runtime JoinSet/panic/error tests from P4.
- [ ] mutex poison behavior tests from P5.
- [ ] non-Unicode config tests from P6.
- [ ] request-ID invariant tests from P8.
- [ ] command-ID exhaustion tests from P9.
- [ ] structured native status/classification tests from P10.
- [ ] tracing/timestamp tests from P11.

### P13.2 Python tests

- [ ] strict primitive field-type tests.
- [ ] enum tests.
- [ ] missing/extra/nullable field tests.
- [ ] malformed error-envelope tests.
- [ ] existing HTTP/WebSocket client happy-path tests remain green.

### P13.3 Privacy tests

Add or update path-specific structured-log tests proving new diagnostics exclude:

- [ ] typed text;
- [ ] clipboard text;
- [ ] key sentinels where not required;
- [ ] pointer coordinate sentinels;
- [ ] bearer token;
- [ ] VNC password;
- [ ] request body/query values;
- [ ] framebuffer/screenshot bytes.

Use sentinels only on paths where the value genuinely reaches the code under test; do not add vacuous privacy assertions.

### P13.4 Native/source contract tests

- [ ] structured protocol-initialization status exists and is mapped.
- [ ] message-string auth classification is absent.
- [ ] native scrub source-contract guarantees from final-polish remain intact.
- [ ] no direct sensitive `free(...)` regression.
- [ ] wrong-password probe remains bounded and leak-free.

### P13.5 Hosted docs contracts

- [ ] no external runtime JS/CSS URLs.
- [ ] exact local asset paths.
- [ ] vendored SHA-256 digests.
- [ ] license/source metadata.
- [ ] CSP tightened to local scripts.
- [ ] Swagger auth persistence remains off.
- [ ] validator remains disabled.

### P13.6 OpenAPI/documentation contracts

- [ ] router operations still match OpenAPI.
- [ ] error-code inventory includes new code exactly once where expected.
- [ ] README/operator/Python docs remain cross-consistent.
- [ ] final-polish request-ID and EventHub wording remains protected.

### P13.7 E2E/smoke

Run and keep green:

- [ ] `tests/desktop/run.sh`.
- [ ] `tests/native/run.sh`.
- [ ] `tests/worker-e2e/run.sh`.
- [ ] `tests/worker-text-clipboard-e2e/run.sh`.
- [ ] `tests/http-e2e/run.sh`.
- [ ] `tests/compose/run.sh`.
- [ ] `tests/integration/run.sh`.
- [ ] offline hosted-doc asset retrieval check.
- [ ] held-key/text E2E if deterministic.

Acceptance:

- [ ] Tests prove both confirmed bugs and every newly terminalized silent-failure boundary.
- [ ] New tests are not merely source-string checks where behavioral tests are practical.

Do not accept:

- [ ] No deletion/weakening of an existing assertion to accommodate the new implementation without documented semantic reason.
- [ ] No giant sleeps when deterministic synchronization is available.
- [ ] No tests reading freed memory or depending on allocator reuse.

---

## P14. Local repository-quality validation

Run from repository root where the environment supports it.

### P14.1 Rust

- [ ] `cargo fetch --locked`
- [ ] `cargo fmt --all --check`
- [ ] `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`
- [ ] `cargo test --locked --workspace --all-features`
- [ ] `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`

### P14.2 Python

Run the repository's canonical quality targets and direct tools as configured:

- [ ] Python compile checks.
- [ ] Ruff.
- [ ] Pylint.
- [ ] Mypy.
- [ ] `python3 -m unittest discover -s tests -p 'test_*.py' -v` or repository-canonical equivalent.
- [ ] Ensure no newly added suppression masks a real finding.

### P14.3 Shell/workflow/contracts

- [ ] shell syntax checks.
- [ ] ShellCheck where locally available.
- [ ] actionlint where locally available.
- [ ] documentation/source/workflow contract tests.

### P14.4 Docker/VNC/integration where locally available

- [ ] desktop smoke.
- [ ] native smoke.
- [ ] WorkerHandle input E2E.
- [ ] WorkerHandle text/clipboard E2E.
- [ ] HTTP E2E.
- [ ] Compose/persistence.
- [ ] R13 integration.

If a local surface is unavailable:

- [ ] record exactly what is unavailable and why;
- [ ] do not label it locally passed;
- [ ] rely on the exact-SHA permanent workflow only after it actually passes.

Acceptance:

- [ ] Every locally runnable canonical quality command is green before permanent validation.

Do not accept:

- [ ] No "works in CI" excuse for a locally reproducible red unit/lint failure.

---

## P15. Permanent CI and Release Gates on exact SHA

### P15.1 Commit discipline

- [ ] Review the final diff against the recorded implementation starting SHA.
- [ ] Confirm only intended source/test/docs/vendor files changed.
- [ ] Confirm vendored third-party assets and licenses are exactly the intended versions/digests.
- [ ] Commit intentionally to `master` without force.
- [ ] Record exact candidate SHA.

### P15.2 CI

On the exact candidate SHA require success for all current CI stages, including:

- [ ] formatting;
- [ ] strict Clippy;
- [ ] full Rust workspace tests;
- [ ] rustdoc warnings denied;
- [ ] Python Ruff/Pylint/Mypy/compile/tests;
- [ ] workflow/native/documentation/contracts;
- [ ] shell syntax;
- [ ] desktop smoke;
- [ ] native adapter smoke;
- [ ] WorkerHandle input E2E;
- [ ] WorkerHandle text/clipboard E2E;
- [ ] authenticated HTTP E2E;
- [ ] Compose/persistence;
- [ ] R13 integration/E2E.

### P15.3 Release Gates

On the same exact candidate SHA require success for:

- [ ] static/supply-chain policy;
- [ ] full-history Gitleaks;
- [ ] ShellCheck/actionlint;
- [ ] Dockerfile/Compose validation;
- [ ] advisory/license/source/duplicate policy;
- [ ] auditable binary metadata verification;
- [ ] ASan;
- [ ] controller-api TSan;
- [ ] remote-desktop-core TSan;
- [ ] Miri on supported subset;
- [ ] Trivy;
- [ ] CycloneDX SBOM/VEX policy.

### P15.4 Failure handling

If any permanent job fails:

- [ ] inspect the actual failing job log;
- [ ] fix the root cause on a new SHA;
- [ ] do not weaken the gate/assertion unless the existing requirement is proved incorrect and the rationale is documented;
- [ ] do not cite the older red/superseded SHA as completion evidence;
- [ ] rerun/allow permanent workflows to validate the new exact SHA.

Acceptance:

- [ ] CI and Release Gates are both green on the same exact implementation SHA.

---

## P16. Final documentation/evidence closure

- [ ] Fill `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_IMPLEMENTATION_NOTES_2026-08-07.md` with final evidence.
- [ ] Update this TODO checkboxes only for work actually completed.
- [ ] Record reviewed baseline SHA.
- [ ] Record implementation starting SHA.
- [ ] Record final implementation SHA.
- [ ] Record exact CI run ID and conclusion.
- [ ] Record exact Release Gates run ID and conclusion.
- [ ] Record any intermediate failed candidate SHA and precise failure.
- [ ] Record local validation disposition.
- [ ] Record any deferred item and why it is safe to defer.
- [ ] Commit final evidence intentionally.
- [ ] If the evidence/doc commit changes the repository tip, require that new exact tip to pass the required permanent workflows before marking this TODO complete.

Final evidence template:

```text
Reviewed code baseline SHA:
b1ce8addc846ef8f55f1ffeab5ecd82bfb9b235b

Spec planning commit:
9095ecc1d96a010061ca463e05848c11f9e92eaa

Implementation starting SHA:
<fill>

Final implementation SHA:
<fill>

Implementation CI run:
<run id> — <conclusion>

Implementation Release Gates run:
<run id> — <conclusion>

Final documentation/evidence SHA:
<fill after commit>

Confirmed baseline-failing regressions:
- TypeText pre-held-key ownership: <evidence>
- Python response type coercion: <evidence>

P3 worker event receiver/sequence terminalization:
<summary>

P4 HTTP task/runtime observability:
<summary>

P5 poison policy:
<summary>

P6 non-Unicode configuration:
<summary>

P7 self-hosted API docs assets:
<versions, digests, license/source metadata>

P8 request-ID invariant handling:
<summary>

P9 command-ID exhaustion:
<summary>

P10 structured native initialization classification:
<summary>

P11 retained intentional ignored-result sites:
<summary>

Local validation:
<commands actually run and results>

Unavailable local validation:
<exact reason, if any>

Deferred follow-ups:
<none, or explicit list/rationale>
```

Acceptance:

- [ ] Final completion claim is tied to an exact green repository tip.
- [ ] Evidence does not imply future run knowledge before the run existed.

---

## Final do-not-accept checklist

Before marking this TODO complete, confirm every item below.

- [ ] No `TypeText` command can release a key held before the command began.
- [ ] No text collision is detected only after partial text was already emitted.
- [ ] No Python typed HTTP response uses unchecked coercion as protocol validation.
- [ ] Python integers reject booleans.
- [ ] Python booleans reject strings/integers.
- [ ] Python enums are runtime-validated before `cast()`.
- [ ] Unexpected worker event receiver disconnection is not silently ignored.
- [ ] Worker event sequence exhaustion is terminal and never wraps/reuses.
- [ ] HTTP connection task panics are not swallowed.
- [ ] Expected client disconnects do not become process-wide fatal failures.
- [ ] No authoritative mutex poison path silently resumes healthy service with `into_inner()`.
- [ ] Present-but-non-Unicode `VRC_*` values cannot silently select defaults.
- [ ] `/docs` and `/redoc` require no third-party runtime JavaScript/CSS fetch.
- [ ] Hosted-doc CSP does not broaden script execution.
- [ ] Missing request-ID state is treated as an invariant failure, not a normal request ID.
- [ ] Final-polish request-ID exhaustion behavior remains exact and fail-closed.
- [ ] Command-ID exhaustion has a specific terminal error and cannot enqueue/reuse IDs afterward.
- [ ] Native worker lifecycle classification does not depend on `message.contains(...)` or other human-text parsing.
- [ ] Invalid tracing configuration/setup cannot silently fall back to a healthy-looking logger state.
- [ ] Invalid public timestamp conversion cannot silently emit ordinary `0` or `u64::MAX` values.
- [ ] Non-empty malformed Python HTTP error envelopes are not silently discarded.
- [ ] Retained ignored results have an actual ownership/lifecycle justification.
- [ ] No new diagnostic logs typed text, clipboard text, key/coordinate payloads, bearer tokens, VNC passwords, request bodies, query secrets, framebuffer bytes, or screenshot bytes.
- [ ] No native scrub guarantee from the prior final-polish pass regressed.
- [ ] No secret-bearing config type regained an implicit general-purpose `Clone`.
- [ ] API bearer token remains shared secret ownership rather than ordinary raw string cloning.
- [ ] No broad Gitleaks/lint/type/sanitizer suppression was introduced.
- [ ] No `continue-on-error`, forced-success wrapper, swallowed exit code, or force push was used.
- [ ] No older, canceled, red, superseded, or partial workflow run is used as completion evidence.
- [ ] Exact final repository tip is green in both CI and Release Gates.
