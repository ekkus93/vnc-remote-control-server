# VNC Remote Control Server Correctness Review Questions and Issues

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Review baseline inspected: `94e5bd01910ae2381e5da4899301d30f422bdeff`

Documents reviewed:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_SPEC_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_TODO_2026-08-06.md`

Purpose of this document:

- record questions, ambiguities, and scope corrections found while reviewing the Claude.ai correctness-review spec and TODO;
- give Claude.ai a stable place to respond point by point;
- settle the remaining design decisions before another Ralph Loop begins;
- avoid changing the spec or TODO until the disputed or ambiguous points are resolved.

No implementation change is requested by this document. Claude.ai should respond to each numbered item and state whether the spec/TODO should be revised.

## Overall assessment

The review is strong and the principal correctness findings are credible. In particular, the pre-`Connected` stall defect is real: a native session may exist while the public state remains `Connecting` or `Reconnecting`; the confirmed-stall path attempts `transition(ConnectionState::Degraded)`, which is illegal from those states, sets `fatal_exit`, propagates `DesktopError::Protocol`, and causes `run_worker` to terminate instead of reconnecting.

The following issues should be resolved before implementation.

---

## 1. Define the exact meaning of `VRC_SHUTDOWN_TIMEOUT_MS`

### Issue

CR6 alternately describes the proposed setting as:

- a process shutdown deadline;
- a timeout independently applied to worker shutdown and event-bridge shutdown;
- a value whose complete process-cleanup bound is the sum of two sequential waits.

These are different contracts.

The current code passes one timeout to `worker.shutdown(timeout)` and then the same timeout to `event_bridge.shutdown(timeout)`. The effective maximum is therefore approximately twice the configured value.

A variable named `VRC_SHUTDOWN_TIMEOUT_MS` would be misleading if the process can take nearly `2 × VRC_SHUTDOWN_TIMEOUT_MS` to finish cleanup.

### Recommended decision

Define `VRC_SHUTDOWN_TIMEOUT_MS` as one total process-cleanup budget:

1. `finalize_runtime` establishes one deadline;
2. worker shutdown receives the remaining budget;
3. event-bridge shutdown receives whatever budget remains;
4. server → worker → bridge error precedence remains unchanged.

### Additional concern

The TODO requires only a value strictly greater than the 50 ms bridge polling interval. A value such as 51 ms can still fail on ordinary scheduler latency.

Choose one of these explicitly:

- require a materially larger minimum, such as 250 ms; or
- replace polling-dependent bridge wake-up with a direct stop notification so clean shutdown latency does not depend on `EVENT_BRIDGE_POLL_INTERVAL`.

### Questions for Claude.ai

1. Is `VRC_SHUTDOWN_TIMEOUT_MS` intended to be one total deadline or a per-phase timeout?
2. If it is per-phase, should the variable be renamed to avoid understating the total bound?
3. Should the bridge gain a direct wake-up mechanism, or should configuration enforce a larger minimum?

### Claude.ai response

_To be filled in._

---

## 2. CR9's proposed post-destruction password test is unsafe or misleading

### Issue

The proposed test name `password_is_not_recoverable_after_client_destruction` suggests inspecting memory after deallocation. Reading freed memory is undefined behavior and cannot establish trustworthy zeroization evidence.

### Recommended replacement

Use a test such as:

`password_storage_is_zeroized_before_deallocation`

Test a project-owned scrub helper or secret wrapper while its allocation is still valid, immediately before release.

### Password-copy audit that must be resolved

The current design appears to create several copies:

- secret file contents returned by the configuration secret reader;
- conversion to `NativeClientConfig.password: String`;
- clones of `NativeClientConfig` through `WorkerSettings` and the worker setup path;
- the temporary Rust `CString` in `NativeClient::connect()`;
- the C shim's `client->password` duplicate;
- the additional duplicate returned by `vrc_get_password()` to LibVNCClient.

The ownership and destruction contract for the password returned by `vrc_get_password()` must be verified before claiming all native copies are scrubbed.

`explicit_bzero` portability also should not be assumed without checking the supported build environment.

### Questions for Claude.ai

1. What exact object should the Rust zeroization test inspect before deallocation?
2. Who owns and frees the string returned by `vrc_get_password()`?
3. How will that callback-returned copy be scrubbed?
4. Is `explicit_bzero` guaranteed in the supported Debian/build environment, or should the project provide its own non-elidable scrub helper?
5. Should the API bearer token also move to the same secret-wrapper abstraction, or is this pass intentionally limited to the VNC password?

### Claude.ai response

_To be filled in._

---

## 3. CR10 should use targeted privacy tests rather than one omnibus shutdown test

### Issue

The existing generic-word assertions are weak. Rejecting substrings such as `clipboard` or `framebuffer` can fail on harmless structured field names and does not prove actual values are protected.

However, injecting bearer-token, password, clipboard, typed-text, coordinate, and key sentinels into one input-release shutdown test would also create false confidence if those values never traverse the code exercised by that test.

### Recommended test split

Use targeted tests that exercise the relevant logging path:

- worker shutdown/input-release logs: key and coordinate sentinels;
- command failure logs: typed-text and clipboard sentinels;
- HTTP access/authentication/error logs: bearer-token sentinel;
- configuration/native startup logs: VNC-password sentinel.

Where possible, parse structured JSON log records and inspect field values rather than relying only on raw substring matching.

### Questions for Claude.ai

1. Does CR10 intend one large test or multiple path-specific tests?
2. Which production path will carry each sentinel far enough that its absence is meaningful?
3. Should structured JSON fields be parsed in the tests instead of searching the complete rendered log string?

### Claude.ai response

_To be filled in._

---

## 4. Separate ThreadSanitizer and Miri coverage requirements

### Issue

The sanitizer finding is valid: the current ThreadSanitizer job runs only `remote-desktop-core`, while the worker, atomics, channels, queue permits, event bridge, and shutdown coordinator live in `controller-api`.

The spec and TODO sometimes discuss ThreadSanitizer and Miri together in a way that can imply both should cover the same `controller-api` paths.

Miri commonly cannot execute native FFI and may not support all Tokio or operating-system functionality used by `controller-api`.

### Recommended acceptance wording

- **ThreadSanitizer:** attempt meaningful `controller-api` worker, event, framebuffer, and shutdown coverage; document the exact native-link boundary if full coverage is impossible.
- **Miri:** retain the existing pure-Rust coverage and document whether any additional pure `controller-api` subset can run. Do not imply that FFI-heavy production paths must run under Miri.

### Questions for Claude.ai

1. Is expanded Miri coverage actually required, or is the correction mainly about overstated historical evidence?
2. Which exact `controller-api` test targets are expected to run under TSan?
3. Is a test-only feature excluding the native adapter acceptable, provided the coverage boundary is explicit and the production configuration is still tested normally elsewhere?

### Claude.ai response

_To be filled in._

---

## 5. CR12 misses another sleep-only negative proof

### Issue

The TODO correctly identifies `mismatched_native_frame_never_reaches_connected`, which sleeps for 30 ms before asserting.

The same test module also contains `authentication_failure_waits_for_manual_reconnect`, which sleeps for 30 ms and then concludes that no automatic retry occurred. That is also a sleep-only negative proof.

### Recommended correction

CR12 should explicitly require deterministic conversion of both tests:

- `mismatched_native_frame_never_reaches_connected`;
- `authentication_failure_waits_for_manual_reconnect`.

The broader audit should remain, but these two known cases should be named.

### Questions for Claude.ai

1. Do you agree that the authentication-failure test is also sleep-only evidence?
2. What deterministic synchronization point should prove that automatic retry remains disabled without relying on elapsed sleep?

### Claude.ai response

_To be filled in._

---

## 6. CR5 needs a metric compatibility decision

### Issue

The review correctly observes that the RAII permit is acquired before `try_send`. The counter therefore measures submissions/envelopes participating in the submission or queue-ownership lifecycle, not literal channel occupancy. It can transiently exceed channel capacity.

The existing public name `vrc_worker_command_queue_depth`, displayed beside `vrc_worker_command_queue_capacity`, is misleading.

The TODO currently allows either renaming the metric or changing its `# HELP` text. The exporter currently emits no Prometheus `# HELP` records, and changing documentation alone would leave misleading HTTP/status terminology.

### Recommended decision

Rename the concept consistently, for example:

- Rust/API field: `command_submissions_in_flight`;
- Prometheus metric: `vrc_worker_command_submissions_in_flight`.

The accounting implementation and permit-acquisition point remain unchanged.

### Questions for Claude.ai

1. Should the old metric be removed immediately or retained temporarily as a deprecated alias?
2. Is backward compatibility with existing monitoring consumers a requirement for this repository?
3. Which HTTP/status field or operator documentation currently exposes the same misleading name and must be updated?
4. Should Prometheus `# HELP` and `# TYPE` records be added as part of this correction?

### Claude.ai response

_To be filled in._

---

## 7. CR3 should prescribe the exact pixel-format contract

### Issue

The native pixel-format finding is valid. The C shim does not explicitly assign the format fields before `SetFormatAndEncodings`, while `replace_native_rgbx()` assumes four in-memory bytes in `[R, G, B, X]` order.

The current spec says to choose shifts and endianness during implementation. That leaves a critical FFI contract unresolved in the implementation checklist.

### Required specification detail

The spec should state the selected values before implementation:

- `bitsPerPixel`;
- `depth`;
- `trueColour`;
- `redMax`, `greenMax`, `blueMax`;
- `redShift`, `greenShift`, `blueShift`;
- `bigEndian`;
- the resulting byte layout in memory.

### E2E recommendation

Render at least two strongly distinguishable colors, such as red and blue, in known interior regions and sample decoded canonical pixels. Define a numeric tolerance. One color alone may not detect every channel-order error.

### Questions for Claude.ai

1. What exact LibVNCClient pixel-format values do you propose?
2. What exact four-byte in-memory layout will those values guarantee on the supported host?
3. What colors, sample coordinates, and numeric tolerance should the E2E test use?
4. Will the E2E validate the raw native framebuffer, the canonical RGBA framebuffer, the decoded PNG, or more than one layer?

### Claude.ai response

_To be filled in._

---

## 8. CR11 presents allocation counts as settled facts before measurement

### Issue

The performance concern is legitimate. The current path includes:

1. a Rust `Vec<u8>` allocation and native framebuffer copy;
2. a second RGBA vector populated by a per-pixel loop;
3. a full-frame equality comparison under the framebuffer write lock;
4. conversion from `Vec<u8>` to `Arc<[u8]>`.

The statement that this necessarily produces exactly three full-frame allocations and copies should remain a hypothesis until measured on the pinned Rust toolchain and allocator. Standard-library conversion behavior should not be overstated without evidence.

### Scope concern

The urgent correctness work could be blocked indefinitely by benchmark infrastructure or an optimization that produces no meaningful improvement.

### Recommended split

- require measurement and a corrected performance record in this pass;
- make optimization conditional on evidence;
- do not make a measurable performance improvement a prerequisite for fixing the stall and state-machine defects;
- create a separately tracked performance TODO if substantial architectural work is indicated.

### Questions for Claude.ai

1. Is CR11 intended to block completion of the correctness pass if measurement shows no worthwhile optimization?
2. Should benchmark/documentation completion be required while implementation optimization remains optional?
3. How will allocation count be measured rather than inferred?
4. Should the framebuffer benchmark live in a permanent Criterion-style benchmark target, a dedicated integration utility, or a one-time evidence script?

### Claude.ai response

_To be filled in._

---

## 9. The blanket failing-runtime-test rule is too broad

### Issue

The spec requires every behavioral fix in sections 2.1 through 2.10 to have a test that fails on the baseline before any fix is written.

That is appropriate for the stall defect, state-transition visibility, pixel channel order, metric semantics, configuration timeout validation, and privacy leakage.

It does not map cleanly to every item:

- sanitizer workflow coverage may be demonstrated by a failing workflow command;
- unreachable match-arm removal is primarily static cleanup;
- secure memory scrubbing may require a focused helper test rather than a full production runtime failure;
- startup-bound documentation is a contract clarification rather than a behavior defect.

### Recommended wording

Require a baseline reproduction appropriate to the task, which may be:

- a failing deterministic runtime test;
- a failing workflow or sanitizer invocation;
- a compile-time/static assertion;
- a focused helper test;
- a documented timing/configuration calculation;
- exact static source evidence where no safe runtime observation exists.

No repair should precede its evidence, but not every item needs the same form of evidence.

### Questions for Claude.ai

1. Do you agree that the reproduction standard should be task-specific?
2. Which CR items must have a failing production-path runtime test, and which may use workflow/static/helper evidence?

### Claude.ai response

_To be filled in._

---

## 10. Recommended CR1/CR2 state-transition strategy

### Issue

The TODO lists three possible CR1 repair strategies, including adding:

- `Connecting -> Degraded`;
- `Reconnecting -> Degraded`.

A connection that has never produced a valid complete framebuffer has not yet reached the semantic state represented by `Connected`. Labeling it `Degraded` broadens the state graph and makes `Degraded` mean two different things.

### Recommended strategy

- retain `Connected -> Degraded -> Reconnecting` for a previously healthy connection;
- when the worker is still `Connecting` or `Reconnecting`, record the stall timeout, invalidate state, and schedule reconnect without entering `Degraded`;
- make illegal transitions emit `worker_illegal_state_transition` with `from` and `to` only;
- remove silent `fatal_exit` mutation from `transition()` itself;
- let the top-level worker or explicit caller decide when an illegal transition is genuinely fatal;
- handle every transition result explicitly.

This resolves CR1 and CR2 without broadening the lifecycle graph.

### Questions for Claude.ai

1. Do you agree that pre-`Connected` stalls should skip `Degraded`?
2. Should `transition()` become side-effect-free on failure except for emitting a diagnostic?
3. Which layer should own setting `fatal_exit` for a genuinely fatal state-machine violation?
4. Should `schedule_reconnect()` return `Result<(), DesktopError>` so transition failures cannot be discarded?
5. How should the final `Stopped` transition in `run_worker` be handled if it unexpectedly fails?

### Claude.ai response

_To be filled in._

---

## 11. Clarify the startup-timeout contract

### Issue

CR7 allows either documenting the doubled bound or deriving cleanup from one budget, but it does not select one.

A configured value called `startup_timeout` normally reads as the entire startup operation deadline, not the first of two equal sequential waits.

### Recommended decision

Prefer one total startup budget:

1. establish a deadline before waiting for startup acknowledgement;
2. after timeout, set the shutdown flag first and send the counted best-effort queue nudge;
3. use only the remaining budget for cleanup/join observation;
4. preserve the distinction between timeout and worker panic/join failure.

If the project intentionally retains two waits, rename or document the setting so operators understand the maximum is approximately twice the configured duration.

### Questions for Claude.ai

1. Is `startup_timeout` intended as one total startup budget or as a per-phase timeout?
2. Which interpretation should become authoritative in the spec and operator documentation?

### Claude.ai response

_To be filled in._

---

## 12. Clarify the scope of secret scrubbing

### Issue

The spec correctly focuses on the VNC password, but the repository also keeps the API bearer token in `Arc<str>` for the process lifetime. Introducing a zeroizing secret abstraction only for one credential may leave inconsistent ownership and cloning policy.

This does not necessarily mean the API token must be changed in the same pass, but the boundary should be explicit.

### Questions for Claude.ai

1. Is API-token zeroization deliberately out of scope?
2. If so, should the spec record why the VNC password is handled differently?
3. Should both credentials use a common non-`Debug`, zeroizing secret type even if their lifetimes differ?

### Claude.ai response

_To be filled in._

---

## 13. Clarify metric/API compatibility policy before renaming public fields

### Issue

CR5 may alter Prometheus metric names, status response field names, operator documentation, or all three. That can be an externally visible API change even though the accounting remains unchanged.

### Questions for Claude.ai

1. Does the repository have a stated compatibility policy for Prometheus metric names and `/v1/status` fields?
2. Is this project still pre-release enough to make a clean rename with no alias?
3. If aliases are required, for how long should they remain and how will contradictory values be prevented?

### Claude.ai response

_To be filled in._

---

## 14. Clarify whether CR11 belongs in this correctness pass

### Issue

The performance review correction is valid, but it is materially different from the correctness, security, and observability defects in CR1 through CR10.

A large benchmark-and-optimization effort increases the risk of mixing unrelated framebuffer changes into a state-machine and shutdown-adjacent correctness pass.

### Recommended decision

Either:

- retain only measurement and historical-document correction in CR11, with optimization explicitly optional; or
- move optimization work to a separate performance spec/TODO after this correctness pass is complete.

### Questions for Claude.ai

1. Should the current correctness TODO require only measurement and disposition?
2. Should any code optimization become a separate follow-up document unless the benchmark reveals a trivial, clearly safe improvement?

### Claude.ai response

_To be filled in._

---

## Requested Claude.ai response format

Please answer every numbered item using this structure:

```text
Item N: <title>

Disposition: agree / partially agree / disagree

Answer to each question:
1. ...
2. ...

Spec changes required:
- ...

TODO changes required:
- ...

Implementation consequence:
- ...

Remaining uncertainty:
- ...
```

After the point-by-point responses, provide a consolidated decision list covering:

1. shutdown-timeout semantics;
2. startup-timeout semantics;
3. CR1/CR2 state-machine strategy;
4. exact native pixel-format contract;
5. TSan and Miri coverage boundaries;
6. metric/API rename and compatibility policy;
7. secret ownership and zeroization boundaries;
8. privacy-test structure;
9. benchmark scope and whether optimization blocks completion;
10. deterministic replacements for both known sleep-only tests.

The spec and TODO should be revised only after these decisions are settled.
