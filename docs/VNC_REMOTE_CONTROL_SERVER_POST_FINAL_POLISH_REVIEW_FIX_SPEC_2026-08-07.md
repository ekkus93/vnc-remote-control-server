# VNC Remote Control Server Post-Final-Polish Review Fix Specification

Date: 2026-08-07

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Reviewed baseline SHA: `b1ce8addc846ef8f55f1ffeab5ecd82bfb9b235b`

Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_TODO_2026-08-07.md`

Prior hardening plan audited by this review: `docs/VNC_REMOTE_CONTROL_SERVER_FINAL_POLISH_HARDENING_TODO_2026-08-06.md`

---

## 1. Purpose

The final-polish hardening pass is complete and its P0-P7 requirements were found to be correctly implemented. This specification does **not** reopen that work. It defines a new, bounded correctness and hardening pass for defects and residual risks found while reviewing the current `master` tip after final-polish completion.

The new pass has four primary objectives:

1. fix two confirmed behavioral/protocol defects;
2. remove production paths that silently hide unexpected subsystem failures or invariant violations;
3. reduce unnecessary trust and ambiguity at configuration, documentation, identifier, and native-error boundaries; and
4. add regression evidence proving that these failure modes remain fail-closed without weakening existing CI, release, privacy, native, or integration guarantees.

The implementation must preserve the repository's existing architecture: Rust owns controller/business/runtime logic, the native adapter remains the sole LibVNCClient FFI boundary, the worker remains single-owner for VNC session mutation, HTTP remains a thin validated adapter, and the Python package remains a client of the documented HTTP/WebSocket contract.

---

## 2. Review findings and required disposition

### 2.1 Confirmed defect: text typing can release caller-owned held keys

Current `InputController::type_text()` uses the idempotent `set_key()` helper for each generated down/up pair. If a corresponding key is already present in `pressed_keys`, the down operation is skipped but the subsequent up operation is still sent and removes the pre-existing held state.

Example:

```text
POST key A down
POST type_text "a"
```

The text command must not release the earlier explicit key-down state.

**Required disposition: fix.**

### 2.2 Confirmed defect: the Python typed HTTP client coerces malformed response fields

The Python client currently uses runtime coercions such as `int(value[...])`, `bool(value[...])`, `str(value[...])`, and `typing.cast(...)` when materializing typed response models. These are not validation. Examples of unacceptable behavior include:

```text
"fatal_exit": "false" -> True
"width": "1280"       -> 1280
"state": 123           -> accepted by cast() at runtime
```

A controller/proxy protocol regression must become `ProtocolError`; it must not be normalized into apparently valid typed data.

**Required disposition: fix.**

### 2.3 Unexpected worker event receiver disconnection is silent

`LoopState::publish()` currently warns on a full bounded event queue but ignores `TrySendError::Disconnected(_)` completely. During normal runtime this can allow HTTP control to continue after the worker-to-event subsystem has disappeared, with future worker events silently lost.

**Required disposition: unexpected receiver disconnection is terminal/fail-closed; orderly shutdown disconnection remains expected.**

### 2.4 HTTP connection/task failures are discarded

The HTTP runtime intentionally ignores multiple task/connection results. Routine client disconnects need not become process failures, but a panicked connection task or unexpected server/runtime error must not disappear without a bounded diagnostic.

**Required disposition: classify and observe; do not make ordinary client disconnects fatal.**

### 2.5 Poisoned authoritative mutexes are silently recovered

Production helpers currently recover a poisoned `Mutex` with `poisoned.into_inner()` and continue with no diagnostic. Poisoning means a thread panicked while holding the protected state; silently treating that state as healthy can conceal an invariant violation.

**Required disposition: no normal healthy continuation after poison. Recovery is permitted only for bounded terminal cleanup/diagnostics and must be explicit and observable.**

### 2.6 Non-Unicode `VRC_*` configuration can silently become a default

The main controller `EnvironmentSource` collapses `std::env::VarError::NotUnicode` into the same `None` used for an absent variable. The HTTP runtime already distinguishes `NotPresent` from `NotUnicode` and rejects the latter.

**Required disposition: make all controller configuration fail closed on present-but-non-Unicode values.**

### 2.7 Hosted Swagger/ReDoc pages execute third-party CDN JavaScript in the controller origin

The current documentation UI pins exact package versions and has useful CSP/privacy controls, but the controller still executes remote JavaScript on pages where an operator may enter a real bearer token.

**Required disposition: self-host the exact documentation assets used by the controller. No runtime CDN JavaScript or CSS dependency is permitted for `/docs` or `/redoc`.**

### 2.8 Request-ID missing-state fallback hides an internal invariant failure

A missing request-ID extension is a server/router invariant failure, not an ordinary request condition. It must not be quietly represented as a normal-looking correlation value.

**Required disposition: make the invariant explicit and observable; preserve safe handling of invalid caller-provided IDs.**

### 2.9 Worker command-ID exhaustion is checked but indistinguishable from generic worker loss

The command sequence uses checked arithmetic, which correctly prevents wraparound, but exhaustion currently collapses into generic `WorkerUnavailable` with no terminal state or specific diagnostic.

**Required disposition: command-ID exhaustion becomes explicit, terminal for new command submission, once-only observable, and non-reusable.**

### 2.10 Native authentication classification depends on a generic error string

The worker currently recognizes authentication failure by matching text such as `protocol initialization failed` inside a generic native error. String matching must not determine lifecycle semantics.

**Required disposition: add/use a structured native status for protocol-initialization failure and classify it as protocol/initialization failure unless the native boundary has explicit evidence of authentication rejection. Do not infer authentication from message text.**

### 2.11 Smaller swallowed/fallback paths remain

The review also identified lower-severity cases: tracing setup fallback/ignored initialization errors, timestamp saturation/defaulting, overly broad Python API-error parsing fallback, and assorted ignored results.

**Required disposition: audit individually. Do not mechanically ban best-effort cleanup or ignored sends where ownership has intentionally disappeared.**

---

## 3. Global invariants

The following rules apply to every change in this pass.

### 3.1 Fail-closed correctness

- No malformed protocol field may be silently coerced into a valid-looking value.
- No identifier sequence may wrap, reuse a previously issued normal identifier, silently saturate, or fabricate a normal value after exhaustion.
- No unexpected loss of an authoritative subsystem may be treated as healthy operation.
- No poisoned authoritative state may be silently reused as healthy state.
- No present-but-invalid configuration may be treated as absent.

### 3.2 Privacy

Diagnostics added by this pass must never contain:

- typed text;
- clipboard contents;
- key values when not strictly necessary for a bounded public enum diagnostic;
- pointer coordinates;
- bearer tokens;
- VNC passwords;
- request/response bodies;
- framebuffer/screenshot bytes;
- arbitrary query strings;
- arbitrary native/server error payload text if a bounded classification is available.

Use fixed event names, fixed reason enums/classes, counts, capacities, statuses, and process-local IDs only where already accepted.

### 3.3 No silent gate weakening

This pass must not use or introduce:

- `continue-on-error` for permanent validation;
- broad lint/type/security suppressions;
- broad Gitleaks ignores;
- test deletion or assertion weakening to make CI pass;
- swallowed nonzero exit codes;
- forced-success wrappers;
- force pushes;
- older-SHA evidence as proof for a newer implementation;
- fallback behavior whose only purpose is to keep the process apparently healthy after an invariant failure.

### 3.4 Preserve justified best-effort behavior

The following patterns are not defects merely because an error result can be ignored:

- a completion/result sender may fail after the caller has timed out and intentionally dropped its receiver;
- transient event publication may have no listeners when replay is explicitly not part of the contract;
- cleanup/release may be best-effort when unresolved state remains tracked and the failure is observable;
- a normal shutdown command may be best-effort when the separate out-of-band shutdown signal is authoritative;
- screenshot result delivery may fail after request timeout when the encode permit remains owned until the actual worker exits.

The implementation must distinguish these intentional ownership/lifecycle cases from unexpected subsystem failure.

---

## 4. Input-state correctness

### 4.1 Text-command ownership rule

`TypeText` owns only key transitions that it starts itself. It must never release a key that was already logically held by an earlier explicit key-down operation.

The worker remains serialized, so `pressed_keys` at command start is the authoritative pre-command held-key set.

### 4.2 Required behavior

Before emitting the first native key event for a text command:

1. validate the complete text using the existing text validation rules;
2. map every text character to the exact `KeyboardKey` that the current implementation would synthesize (`Enter`, `Tab`, or `Printable`);
3. compare those synthesized keys against the set already present in `pressed_keys` at command start;
4. if any synthesized key collides with an already-held key, reject the entire text command before sending any native key event.

This preserves the existing "preflight before first side effect" design and avoids inventing ambiguous behavior for generating a character while the exact same logical key is already held.

The error must be a bounded configuration/request error. It must not include the text character or input payload in logs.

### 4.3 Repeated characters within the text

Repeated characters inside the same text command remain valid. A generated key is pressed and released for each occurrence; only keys held **before** the command are collision candidates.

### 4.4 Failure cleanup

If a native key-up fails after a text-generated key-down succeeds, the existing retry/tracked-state cleanup semantics remain in force. The fix must not clear unrelated pre-existing held keys.

### 4.5 Regression evidence

At minimum test:

- explicit printable key down + `TypeText` containing that character -> rejected before any text event and pre-existing key remains held;
- explicit `Enter` down + text containing newline/CR -> same;
- explicit `Tab` down + text containing tab -> same;
- repeated normal character with no pre-existing hold -> still types normally;
- failed key-up during text -> unresolved generated state remains tracked and later release logic can retry;
- existing chord behavior is unchanged.

Where practical, add the failing regression test before the implementation change and record that it detects the baseline defect.

---

## 5. Strict Python HTTP protocol validation

### 5.1 Principle

Typed Python response models must be created only from values that satisfy the documented JSON contract. Conversion functions are not validators.

### 5.2 Required validation primitives

Add narrow reusable helpers for at least:

- object/dictionary values;
- exact strings;
- exact booleans;
- integers that explicitly reject `bool`;
- nullable strings;
- nullable integers;
- enumerated strings;
- required fields;
- optional/unknown fields according to the corresponding OpenAPI schema.

If a schema has `additionalProperties: false`, the client must reject unexpected fields. If the OpenAPI schema intentionally permits additional properties, preserve that allowance.

### 5.3 Numeric rules

`True` and `False` must never be accepted as integers. Apply documented minimum/maximum constraints where they are part of the public contract.

### 5.4 Enum rules

`ConnectionState`, `WorkerFailure`, command status values, framebuffer status values, and other closed vocabularies must be validated at runtime before constructing typed models. `typing.cast()` may still be used after validation for static typing, but never as the validation mechanism.

### 5.5 Coverage

Strict decoding must cover every typed HTTP response returned by the Python package, including at least:

- liveness/readiness;
- status;
- display;
- command acknowledgements;
- clipboard;
- screenshot metadata/header handling where typed assumptions exist;
- hosted OpenAPI response object shape where the package promises a mapping;
- structured API errors.

WebSocket event parsing must retain its existing strict integer/string checks and should reuse compatible validation helpers where doing so improves consistency without weakening event semantics.

### 5.6 Required malformed-response tests

Tests must prove rejection of at least:

- string where boolean required (`"false"`);
- integer where boolean required (`0`/`1`);
- numeric string where integer required (`"1280"`);
- boolean where integer required (`true`);
- integer/object/list where string required;
- unknown enum value;
- invalid nullable type;
- missing required field;
- unexpected field when schema forbids additional properties.

Each must raise `ProtocolError` rather than returning a partially coerced model.

---

## 6. Worker event-channel terminal failure

### 6.1 Full versus disconnected channel

The existing distinction remains important:

- `TrySendError::Full` is a bounded overload condition. Increment `dropped_events`, emit the existing bounded warning, and continue according to the existing contract.
- `TrySendError::Disconnected` means no receiver exists. Outside expected shutdown, this is a subsystem failure and must not be ignored.

### 6.2 Terminal behavior

Refactor worker event publication so an unexpected disconnected receiver can propagate a terminal failure to the worker loop rather than being swallowed.

On the first unexpected disconnection:

- emit one payload-free `error` diagnostic with a fixed event name such as `worker_event_receiver_disconnected`;
- mark the worker as no longer healthy for command/readiness purposes;
- stop accepting new commands;
- invalidate any current framebuffer state as required by the existing disconnect/fatal path;
- release/abandon tracked input according to existing bounded cleanup semantics;
- terminate the worker loop or transition to the repository's established fatal terminal state.

Do not spin, repeatedly log, or continue sending to a known-disconnected event channel.

### 6.3 Orderly shutdown

If the receiver is intentionally gone because shutdown is already authoritative/in progress, no new fatal diagnostic is required. The code must make this distinction explicit rather than relying on timing.

### 6.4 Worker event sequence exhaustion

The worker's own event sequence exhaustion must also be terminal. Once `checked_add` fails:

- emit its payload-free once-only exhaustion diagnostic;
- do not continue normal worker operation as if publication merely dropped one event;
- do not wrap, reset, or reuse the sequence;
- move through the same fatal shutdown boundary used for unexpected event-subsystem loss.

Deterministic test hooks may force the sequence near `u64::MAX`; production behavior must not depend on reaching it naturally.

---

## 7. HTTP connection and task observability

### 7.1 Connection task result

Per-connection runtime tasks must return enough information for the parent `JoinSet` owner to distinguish:

- clean connection completion;
- normal/expected peer disconnect or protocol-close conditions;
- unexpected Hyper/runtime failure;
- task cancellation during bounded shutdown;
- task panic.

### 7.2 Required diagnostics

- A task panic is always an `error` diagnostic and must not be swallowed.
- Unexpected runtime/server errors are bounded diagnostics at an appropriate severity.
- Routine client disconnect/noise may be `debug` or intentionally unlogged if its classification is explicit.
- Diagnostics must not include request bodies, authorization headers, clipboard/text payloads, query values, or screenshots.

This pass does not require turning an isolated malformed client connection into a process-wide fatal error.

### 7.3 Shutdown drain

During graceful shutdown, join/cancellation outcomes must still be inspected. Bounded forced abort after the configured grace period remains acceptable, but the implementation must not hide a panic that occurred before/during drain.

### 7.4 Pre-router terminal HTTP failures

Header/body timeout and body-limit responses occur before normal Axum middleware. Preserve their bounded behavior. If practical without buffering/logging sensitive request data, add fixed metrics/diagnostics for:

- header timeout;
- body timeout;
- body too large;
- malformed body/transport read failure.

Do not force these paths through bearer authentication merely to obtain request middleware metadata.

---

## 8. Mutex poison policy

### 8.1 Prohibition

A generic production helper must not silently implement:

```rust
mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
```

for authoritative mutable application state and then continue normal service as healthy.

### 8.2 Authoritative state

For worker snapshots, framebuffer state, clipboard state, permit counters, shutdown coordination, and similar authoritative structures:

- poison detection must become observable;
- normal command/readiness behavior must fail closed rather than silently trusting possibly half-mutated state;
- the safest available terminal path should be used if the affected state is required to reason about correctness.

### 8.3 Terminal cleanup exception

`PoisonError::into_inner()` may be used during terminal cleanup or diagnostic extraction only when:

- the code is already committed to not resuming normal service;
- a comment explains why the poisoned value is safe enough for that limited cleanup operation;
- a payload-free diagnostic records the invariant failure;
- tests cover the intended behavior where feasible.

### 8.4 No dependency shortcut without justification

Do not replace poisoning with a non-poisoning mutex implementation solely to make the signal disappear. Any synchronization dependency change requires an explicit correctness rationale and must pass existing dependency policy.

---

## 9. Configuration fail-closed semantics

### 9.1 Environment abstraction

Change the main controller environment abstraction so it can represent three states:

1. variable absent;
2. variable present with valid Unicode value;
3. variable present but not valid Unicode.

The third state must produce `ConfigError::InvalidValue(<name>)` or another bounded configuration error. It must never choose a default.

### 9.2 Consistency

Apply the same rule to all `VRC_*` variables read through the controller configuration layer. Keep the HTTP runtime's existing `NotPresent` versus `NotUnicode` behavior consistent with it.

### 9.3 Secret paths

A non-Unicode secret-file path selected through an environment variable is a configuration error. Do not fall back to the default secret path.

### 9.4 Tests

On Unix, use `OsStringExt` to create deterministic non-Unicode environment-source test values without mutating global process environment where possible. Tests must demonstrate:

- absent -> documented default;
- valid Unicode -> configured value;
- invalid Unicode -> error, never default.

---

## 10. Self-hosted API documentation assets

### 10.1 Runtime trust boundary

`/docs` and `/redoc` must not require network access or execute styles/scripts fetched from a third-party origin at runtime.

Preserve the currently selected versions unless an explicit separate upgrade is justified:

- Swagger UI `5.32.11`;
- ReDoc `2.5.3`.

### 10.2 Asset ownership

Vendor or otherwise include the exact required distribution assets in the repository/build context under an explicit third-party path. Include the corresponding upstream license notices required for redistribution.

Repository-owned contract tests must pin expected asset versions and cryptographic digests (SHA-256 or stronger) for vendored minified assets so accidental replacement is detected.

Do not fetch the assets dynamically during controller startup.

### 10.3 Routes

Serve required Swagger/ReDoc JS/CSS from local controller routes such as `/docs/assets/...`. `/openapi.json` remains repository-owned and embedded/local.

### 10.4 CSP

Tighten documentation CSP after local hosting:

- Swagger scripts/styles should use `'self'` rather than external CDN origins;
- ReDoc scripts should use `'self'`;
- retain `connect-src 'self'`;
- retain `frame-ancestors 'none'`;
- retain `base-uri 'none'` and `form-action 'none'`;
- keep Swagger `persistAuthorization: false` and `validatorUrl: null`.

If ReDoc still requires `'unsafe-inline'` style support, document that exact reason; do not broaden script execution.

### 10.5 Deployment/offline test

Add a test proving the hosted docs HTML contains no `http://` or `https://` asset URL and that every referenced script/stylesheet route is served by the controller. Prefer an integration/smoke check that works with external network unavailable.

---

## 11. Request-ID invariant handling

### 11.1 Missing extension

A missing `RequestId` after the outer assignment middleware is an internal server invariant failure.

Do not silently convert it into an ordinary normal request ID. Prefer normal Axum extraction that cannot reach handlers without the extension. Any fallback helper retained for error construction must:

- use an explicitly reserved non-normal invariant sentinel;
- produce HTTP `500`/`internal_error`, not a normal application response;
- emit one bounded server-invariant diagnostic;
- never be accepted as a caller-provided request ID.

If the existing fallback helper is unnecessary after refactoring, remove it.

### 11.2 Invalid caller `X-Request-ID`

Preserve the safe policy that an invalid caller-provided request ID cannot poison headers/logs or bypass generated-ID allocation. The server may ignore the invalid value and issue a new generated ID, but this must be documented/tested as a deliberate sanitization policy.

Do not log the raw rejected caller header.

### 11.3 Existing exhaustion contract

Do not regress final-polish behavior:

- checked allocation;
- terminal exhaustion;
- `503 request_id_exhausted`;
- reserved `request-id-exhausted` sentinel;
- no caller-ID bypass;
- once-only payload-free diagnostic.

---

## 12. Worker command-ID exhaustion

### 12.1 Allocation

Retain checked allocation and add explicit terminal state shared by all `WorkerClient` clones.

On the first failed allocation at the terminal limit:

- transition the command-ID allocator into a permanent exhausted state;
- emit one payload-free `worker_command_id_sequence_exhausted` diagnostic;
- reject that submission and all later submissions before enqueue;
- never wrap, reset, saturate, or reuse a normal command ID.

### 12.2 Health/readiness

Command-ID exhaustion means the controller can no longer safely acknowledge new commands. The worker/controller must therefore become not-ready for command service. Use an explicit terminal/fatal indicator rather than pretending this is a transient queue condition.

### 12.3 API error

Add a specific bounded domain/API error for command-ID exhaustion rather than reporting generic `worker_unavailable`.

Recommended HTTP contract:

```text
HTTP 503
error.code = "command_id_exhausted"
message = "command identifier sequence is exhausted"
```

Update OpenAPI, Python client error-code contract tests, README/operator documentation if required, and any public error-code inventory.

### 12.4 Tests

Provide a deterministic test hook/constructor that starts the command sequence near `u64::MAX`. Prove:

- last normal ID is unique;
- next allocation fails;
- no enqueue occurs for the failed or later submission;
- diagnostic occurs at most once;
- readiness becomes false/terminal state is visible as designed;
- no wraparound or ID reuse occurs.

---

## 13. Structured native initialization errors

### 13.1 No message-text lifecycle classification

Remove worker logic that decides `Authentication` by searching a generic native error message string.

### 13.2 C shim status

Add an explicit shim status for `InitialiseRFBConnection(...)` failure, separate from the generic native-operation failure used by unrelated send/poll/allocation paths. The status name should describe what is known, for example `VRC_STATUS_PROTOCOL_INITIALIZATION_FAILED`; it must not claim authentication unless LibVNCClient supplies an explicit trustworthy authentication-rejection signal at that point.

### 13.3 Rust error

Map that status to a structured `NativeError` variant such as `ProtocolInitializationFailed`. The variant carries no arbitrary payload text.

### 13.4 Worker classification

Classify structured protocol initialization failure as protocol/initialization failure, not `Authentication`, unless an explicit separate authentication status is implemented from trustworthy native evidence.

The existing `AuthenticationFailed` state/type may remain for genuinely classified authentication failures; do not fabricate that classification from a string.

### 13.5 Diagnostic compatibility

The shim may retain a bounded human-readable `last_error` for debugging, but that string must not determine control flow. Tests should vary/change the message while proving structured classification remains identical.

### 13.6 Wrong-password integration behavior

Update the native wrong-password smoke/E2E expectation to the new truthful classification. The important invariant is fail-closed connection failure with no credential leak; the test must not force an unproven authentication label.

---

## 14. Smaller fallback cleanup

### 14.1 Tracing initialization

Change process tracing setup to return a `Result` or otherwise make setup failure explicit.

- Invalid `RUST_LOG`/filter configuration must fail startup rather than silently replacing the requested value with `info`.
- Failure to install the production global subscriber must not be ignored by `main`.
- Tests that intentionally install local subscribers may continue using isolated capture helpers.

### 14.2 Timestamp conversion

Remove `unwrap_or_default()` / `unwrap_or(u64::MAX)` from public Unix-millisecond conversion where they can turn a broken system clock into plausible data.

Use checked conversion and surface an internal/bounded failure, or explicitly represent unavailable time if the public schema supports it. Do not silently emit `0` or `u64::MAX` as ordinary timestamps.

### 14.3 Python HTTP error-body parsing

The Python client may accept an **empty** body for runtime-generated pre-router HTTP failures whose contract permits it (currently body/header timeout/limit classes as documented). A non-empty malformed structured error body must not be silently ignored.

For non-empty malformed JSON/error envelopes, raise `ProtocolError` (chained from the HTTP failure as appropriate) without copying arbitrary response bytes into the exception text.

### 14.4 Ignored-result audit

Audit production occurrences of at least:

```text
let _ =
.ok()
unwrap_or_default()
unwrap_or(...)
if let Err(_) / Err(_) => {}
ignored channel send/recv/join results
best-effort cleanup calls
```

For each reviewed occurrence choose one of:

1. propagate;
2. log/metric with bounded classification;
3. make terminal/fail-closed;
4. retain as intentionally ignored with a local comment explaining ownership/lifecycle justification.

Do not turn this into mechanical noise: an intentionally dropped reply after caller timeout is not equivalent to losing an authoritative event receiver.

---

## 15. Testing strategy

### 15.1 Baseline-failing tests

For confirmed bugs, add regression tests that fail against the reviewed baseline where practical before applying the fix:

- pre-held key + `TypeText` collision;
- Python malformed bool/int/string/enum response fields.

Record the baseline-failure observation in implementation notes or commit history. Do not manufacture a failing test for a hardening-only change if the baseline behavior is intentionally unspecified.

### 15.2 Rust unit tests

Cover:

- text input ownership/preflight;
- worker event receiver disconnection;
- worker event sequence exhaustion;
- command-ID exhaustion;
- poison/invariant handling where deterministic;
- non-Unicode configuration abstraction;
- request-ID missing-state behavior if any fallback remains;
- structured native initialization classification;
- runtime connection task panic/error observation.

### 15.3 Python tests

Cover all strict response validators and malformed error-envelope behavior under Ruff, Pylint, Mypy, and unittest.

No `# type: ignore`, pylint disable, or Ruff suppression should be added solely to make the new validation code pass unless there is a narrowly documented external typing defect and no cleaner implementation.

### 15.4 Contract tests

Update repository-owned source/documentation contracts for:

- local Swagger/ReDoc asset routes and no external runtime asset URLs;
- vendored asset digests/licenses;
- OpenAPI `command_id_exhausted` error code;
- no native message-string authentication classification;
- configuration non-Unicode rejection if source-contract testing is used;
- retained final-polish request-ID/EventHub/native scrub guarantees.

### 15.5 Integration/E2E

Preserve and rerun:

- desktop smoke;
- native adapter smoke;
- WorkerHandle input E2E;
- WorkerHandle text/clipboard E2E;
- authenticated HTTP E2E;
- Compose/persistence;
- R13 Compose integration/E2E.

Add an E2E assertion for held-key/text interaction if the current test desktop can observe it deterministically.

---

## 16. Validation gates

The final implementation SHA must pass all permanent gates applicable to the repository, including at least:

### Repository quality

```bash
cargo fetch --locked
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
```

and the repository's Python quality commands, including Ruff, Pylint, Mypy, compile checks, and full `unittest` discovery.

### Native/runtime/integration

- shell syntax checks;
- desktop smoke;
- native adapter smoke;
- worker input E2E;
- worker text/clipboard E2E;
- HTTP E2E;
- Compose/persistence;
- R13 integration/E2E.

### Release/security

- full-history Gitleaks;
- ShellCheck/actionlint;
- Dockerfile/Compose validation;
- dependency advisory/license/source/duplicate policy;
- auditable binary verification;
- ASan;
- controller-api TSan;
- remote-desktop-core TSan;
- Miri on the supported Rust-only subset;
- Trivy;
- SBOM/VEX policy.

No sanitizer or release gate may be weakened merely because new failure-path tests are difficult.

---

## 17. Exact-SHA evidence and completion

Completion requires a single exact implementation/documentation repository tip to be green in both permanent CI and permanent Release Gates.

The completion record must include:

- reviewed baseline SHA;
- implementation starting SHA if `master` moves before work begins;
- final implementation SHA;
- exact CI run ID and conclusion;
- exact Release Gates run ID and conclusion;
- any intermediate failed candidate SHA and the real reason it failed;
- whether local validation was available and exactly which commands ran locally;
- any intentionally deferred item with rationale.

Older, canceled, red, superseded, or partial runs are not completion evidence for the final SHA.

If documentation/evidence is committed after an already-green implementation SHA, that new documentation tip itself must pass the required permanent workflows before the TODO is marked complete.

---

## 18. Non-goals

This pass does not require:

- redesigning the VNC protocol implementation;
- replacing LibVNCClient;
- introducing TLS termination inside the controller;
- changing the Docker desktop environment;
- adding accounts/multi-user authorization;
- adding arbitrary WebSocket replay;
- changing the accepted framebuffer format;
- changing normal request-ID format;
- changing normal command input semantics except where required for the held-key correctness bug;
- guaranteeing scrubbing of third-party, LibVNCClient, server, OS, toolkit, allocator, swap, reverse-proxy, or crash-dump copies;
- mechanically treating every ignored result as a defect.

Scope expansion beyond this list requires a separately documented reason tied to a failing test, build break, security requirement, or directly necessary implementation dependency.

---

## 19. Final acceptance criteria

This pass is complete only when all of the following are true:

1. `TypeText` cannot release caller-owned pre-held keys and rejects collisions before side effects.
2. Every typed Python HTTP model rejects malformed field types/enums instead of coercing them.
3. Unexpected worker event receiver loss and worker event sequence exhaustion are terminal and observable, not silent.
4. HTTP connection task panics/unexpected runtime errors are observable without logging sensitive request data.
5. Poisoned authoritative mutex state is never silently resumed as healthy normal service.
6. Present-but-non-Unicode controller configuration is rejected rather than replaced by defaults.
7. Swagger/ReDoc runtime assets are served locally with no third-party runtime script/style dependency.
8. Missing request-ID state is treated as an invariant failure; existing request-ID exhaustion guarantees remain intact.
9. Command-ID exhaustion has explicit terminal behavior, diagnostics, public error mapping, and no reuse/wraparound.
10. Native connection lifecycle classification no longer depends on matching generic message text.
11. Invalid tracing configuration/setup, invalid timestamps, malformed non-empty Python error bodies, and other audited fallback paths have explicit dispositions.
12. No privacy, shutdown, framebuffer, authentication, ETag, WebSocket, native scrub, bounded-capacity, or release-policy contract regresses.
13. The exact final repository tip passes CI and Release Gates without suppressions, weakened tests, or older-SHA evidence.
