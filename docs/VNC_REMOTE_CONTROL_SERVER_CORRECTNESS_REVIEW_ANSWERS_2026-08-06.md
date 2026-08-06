# VNC Remote Control Server Correctness Review Answers

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Responding to: `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_QUESTIONS_AND_ISSUES_2026-08-06.md`

Baseline inspected for these answers: `7ac3552` (`origin/master`), which contains the questions document.

Documents to be revised after these decisions are accepted:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_SPEC_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_TODO_2026-08-06.md`

## Summary of position

The review is correct on substance and I agree with the majority of it. Items 2, 5, 8, 9, 10, 11, and 14 identify genuine defects in my spec and TODO, not merely ambiguities, and I accept those corrections outright. Items 1, 3, 4, 6, 12, and 13 are ambiguities I left open that should have been decided; I decide them below. Item 7 correctly demands values I deferred; those values are supplied.

One correction to the questions document itself: item 6 states that the misleading name appears in "HTTP/status terminology." I verified `StatusResponse` in `crates/controller-api/src/http/responses.rs` and it does **not** carry a queue-depth field. The only externally visible surface is the Prometheus metric. This narrows the rename blast radius considerably and is the basis for my answer to items 6 and 13.

Where an answer depends on a fact I could not execute — LibVNCClient internals, allocator behavior, encoding lossiness — I say so explicitly rather than asserting it. Those become verification steps in the TODO, not claims in the spec.

---

## Item 1: Define the exact meaning of `VRC_SHUTDOWN_TIMEOUT_MS`

Disposition: agree

Answer to each question:

1. One total deadline. My TODO described it three inconsistent ways and that is a defect in the document. A variable named `VRC_SHUTDOWN_TIMEOUT_MS` that can be exceeded by roughly 2x is exactly the kind of misleading contract this whole pass exists to remove; adopting it would have reproduced the defect I filed against the queue-depth metric.
2. Not applicable — it becomes a total deadline, so no rename is needed.
3. Enforce a larger minimum. Recommend against adding a direct wake-up mechanism in this pass, for the reason below.

On the wake-up question specifically. The three dependency-free options are all worse than they look:

- `std::sync::mpsc` has no select, so a genuine select requires `crossbeam-channel`. That is a new dependency in a repository whose Release Gates run `cargo-deny` advisory, license, and source policy and whose release policy pins every tool by immutable version. Buying back 50 ms of shutdown latency is not worth that supply-chain surface.
- Waking `recv()` by pushing a sentinel into the worker event channel is unreliable: the channel is bounded and the bridge does not own the sender, so a full channel would silently defeat the wake-up.
- A `Condvar` handshake would require replacing the worker event channel itself, which is out of scope and touches preserved behavior.

The 50 ms poll interval is already small relative to any sane shutdown budget. The right fix is to stop the configuration from being set into the danger zone, and to derive the floor from the constant rather than hardcoding a second magic number.

Spec changes required:

- Rewrite 2.6 to define `VRC_SHUTDOWN_TIMEOUT_MS` as one total process-cleanup budget with a single deadline established in `finalize_runtime`.
- State that worker shutdown receives the full remaining budget and event-bridge shutdown receives whatever remains after the worker phase returns.
- State that server, then worker, then bridge error precedence is unchanged.
- Record the rejection of a direct bridge wake-up, with the crossbeam dependency and bounded-channel reasons, as a deliberate deferral rather than an oversight.

TODO changes required:

- Replace the "strictly greater than `EVENT_BRIDGE_POLL_INTERVAL`" floor with `max(500 ms, 8 * EVENT_BRIDGE_POLL_INTERVAL)`, expressed in code as a derived constant so it cannot drift if the poll interval changes.
- Add a checklist item that `finalize_runtime` computes remaining budget with saturating arithmetic and passes a non-zero remainder to the bridge phase.
- Add a checklist item asserting the bridge phase still receives a usable budget when the worker phase consumes most of the total, and define the behavior when the remainder is zero: skip the bounded wait, request stop, detach deliberately, and return the bridge timeout as a secondary logged failure.
- Add a checklist item recording the deferred wake-up decision in the operator guide.

Implementation consequence:

- `finalize_runtime` gains a `Instant` deadline and computes `deadline.saturating_duration_since(Instant::now())` before each phase.
- The zero-remainder case must be explicitly handled, because `recv_timeout(Duration::ZERO)` is a legal but immediately-timing-out call and would produce a confusing spurious `event_bridge_shutdown_timeout`.

Remaining uncertainty:

- 500 ms is a judgment call, not a measured value. It is roughly ten poll intervals and comfortably above ordinary scheduler latency on a loaded CI runner, but if the project has a hard SIGTERM-to-exit SLA from the container runtime, that SLA should set the floor instead.

---

## Item 2: CR9's proposed post-destruction password test is unsafe or misleading

Disposition: agree, and the correction is more serious than the questions document says

The test name I wrote is not merely misleading — implementing it literally would require reading freed memory, which is undefined behavior and would be caught by the AddressSanitizer gate. Proposing a test that the repository's own gates would reject is a real defect in my TODO.

Answer to each question:

1. The Rust test should inspect a project-owned zeroizing wrapper while its allocation is still valid. Concretely: construct the wrapper over a heap `String`, take a raw pointer to its buffer, drop the wrapper, and assert on a *separately owned* copy of what the scrub helper wrote — or, cleaner and fully defined, test the scrub helper directly on a live buffer and test the wrapper's `Drop` by instrumenting the helper with a call counter. The second form has no UB at all and is what I recommend. It proves "the scrub runs on the right buffer at the right time" without ever reading freed memory, which is the only claim that is actually testable.
2. LibVNCClient owns and frees it. The `GetPassword` callback contract is that the callback returns a heap-allocated string and the library frees it after authentication. **I could not verify whether the pinned Debian `libvncclient1` scrubs before freeing, and I am not going to assert either way.** That verification is a TODO step, not a spec claim.
3. It cannot be scrubbed by the shim. Once `vrc_get_password` returns, the shim has no further reference to that allocation and no hook that runs before the library frees it. The honest position is that this copy is a **documented residual**, not a closed gap. Two things follow: the spec must not claim "all native copies are scrubbed," and the TODO must require checking the pinned library's behavior and recording the result either way.
4. **`explicit_bzero` will not compile in this project as currently configured.** This is verifiable from the source: `crates/libvnc-adapter/native/vnc_shim.c` opens with `#define _POSIX_C_SOURCE 200809L`, and `crates/libvnc-adapter/build.rs` compiles it with `-std=c11 -Wall -Wextra -Werror -pedantic`. `explicit_bzero` is a GNU/BSD extension, not POSIX, so under a strict `_POSIX_C_SOURCE` feature-test macro glibc does not declare it; with `-Werror` the implicit declaration is a hard compile error. Obtaining it would require adding `_DEFAULT_SOURCE` or `_GNU_SOURCE`, which widens the feature-test surface of a deliberately strict translation unit. `memset_s` is C11 Annex K, optional, and glibc does not implement it. **Therefore: the project must provide its own non-elidable scrub helper.** A `volatile unsigned char *` write loop is correct, portable under `-std=c11 -pedantic -Werror`, and adds no feature-test macros.
5. Out of scope for this pass, but the boundary must be stated. See item 12.

Spec changes required:

- Rewrite 2.9 to distinguish scrubbable copies from the callback-returned copy owned by LibVNCClient.
- State explicitly that the `vrc_get_password` return value is a residual whose disposition depends on the pinned library, and that this pass records rather than closes it.
- Record that `explicit_bzero` is unavailable under the current translation-unit configuration and that a project-owned volatile-write helper is required.
- Note that VNC DES authentication truncates the password to 8 bytes, so any copy the library makes for the auth exchange is also outside the shim's control.

TODO changes required:

- Rename the test to `password_storage_is_zeroized_before_deallocation`.
- Restructure it as: (a) a direct test of the scrub helper on a live buffer; (b) a test that the wrapper's `Drop` invokes the helper on the correct buffer, proved by an instrumented counter, not by reading freed memory.
- Add a verification step: inspect the pinned Debian `libvncclient1` source for whether `GetPassword`'s return value is scrubbed before `free`, and record the finding with the exact version.
- Add a checklist item to implement `vrc_secure_scrub(void *, size_t)` using a `volatile unsigned char *` loop, with a comment stating why `explicit_bzero` and `memset_s` are not used.
- Add a checklist item confirming the helper survives `-Werror -pedantic` and that no new feature-test macro was introduced.
- Add the password-copy inventory from the questions document to the audit checklist verbatim, including the `CString` temporary in `NativeClient::connect`.

Implementation consequence:

- `CString` in `NativeClient::connect` is a real copy that needs handling. `CString::into_bytes` plus explicit scrubbing, or a zeroizing wrapper around the `CString`, is required; simply dropping it leaves the secret in the freed allocation.
- The completion claim changes from "the password is scrubbed everywhere" to "every copy the project owns is scrubbed; one library-owned copy is documented." That is a weaker but true claim.

Remaining uncertainty:

- Whether the pinned `libvncclient1` scrubs its copy. Unverified. Recorded as a TODO step.
- Whether a `volatile` write loop survives aggressive LTO in every future toolchain. It is the standard portable idiom and is correct under the C11 abstract machine, but it is not a hard guarantee the way a compiler intrinsic would be.

---

## Item 3: CR10 should use targeted privacy tests rather than one omnibus shutdown test

Disposition: agree

The objection is precisely right and it is the sharper version of my own finding. My CR10 replaced weak assertions with assertions that are strong-looking but vacuous: asserting that a bearer token does not appear in a worker input-release log proves nothing, because the bearer token never reaches that code. That is worse than the generic-noun assertions it replaces, because it manufactures confidence.

Answer to each question:

1. Multiple path-specific tests. One omnibus test is the defect, not the fix.
2. Mapping each sentinel to a path where its absence is meaningful:
   - **Key value and coordinate** — worker shutdown and input release. Press a key and a button at a distinctive coordinate through the real worker, force release failure, and assert `worker_input_release_incomplete` and `worker_input_release_abandoned` carry counts only. This is the one path my original test actually exercised.
   - **Typed text and clipboard value** — the command failure path. `execute_command` logs `error = %error` on `desktop_command_failed`, and `DesktopError::Configuration` carries a `String`. Submit `TypeText` and `SetClipboard` with sentinel payloads that fail validation, and assert the rendered error does not contain the payload. This is a genuine leak surface, not a hypothetical one.
   - **VNC password** — native error propagation. `NativeError::NativeFailure { message }` is populated from the shim's `vrc_client_last_error` buffer and is rendered into logs through `Display`. A failing connect with a sentinel password must not surface it. This also covers configuration load.
   - **Bearer token** — HTTP access log and authentication rejection. Drive a request with a wrong token and with the correct token through the real middleware, and assert neither the configured token nor the presented one appears; the access log should show only the `[REDACTED]` marker.
3. Yes, parse structured fields. The current `capture_logs` helper in `crates/controller-api/src/test_support.rs` builds a human-formatted subscriber, so tests can only substring-match the rendered string. Add a JSON variant — `tracing_subscriber::fmt().json()` — and have these tests deserialize each record and assert on field *values*. Substring matching over a rendered line cannot distinguish a field name from a field value, which is the root cause of the generic-noun brittleness.

Spec changes required:

- Rewrite 2.10 to state that the defect is twofold: generic-noun assertions are brittle, and sentinel assertions on paths the sentinel never reaches are vacuous.
- Add the requirement that a sentinel is only admissible in a test where the production path demonstrably carries that value.

TODO changes required:

- Split CR10 into four path-specific tests along the mapping above.
- Add a checklist item to introduce `capture_json_logs` in `test_support.rs`.
- Require each test to parse records and assert on field values, retaining a raw-string assertion only as a secondary net.
- Add an explicit checklist item that no sentinel may be asserted in a test unless the path carries it; require the author to name the carrying mechanism for each.

Implementation consequence:

- The `DesktopError::Configuration(String)` and `NativeError::NativeFailure { message }` variants become the load-bearing risk surfaces. If either test fails, the fix is to stop embedding free-form strings in logged errors, which is a larger change than adding a test.

Remaining uncertainty:

- I did not find a current validation error that embeds user text — `crates/remote-desktop-core/src/validate.rs` contains no `format!` calls that interpolate input. So these tests may all pass on the baseline. That is fine: they are regression guards against a future leak, and per item 9 they do not require a failing baseline.

---

## Item 4: Separate ThreadSanitizer and Miri coverage requirements

Disposition: agree

Answer to each question:

1. Expanded Miri coverage is **not** required. The correction is about overstated historical evidence, and my documents conflated the two tools. Miri interprets Rust and cannot execute FFI or real I/O; `controller-api` links LibVNCClient and drives Tokio epoll, so it is out of Miri's reach by construction. Keeping `remote-desktop-core` under Miri and documenting that boundary is the correct end state.
2. `--package controller-api --lib`. That single target covers the worker module tests, the shutdown coordinator tests, the event-bridge tests in `events.rs`, and the framebuffer tests — which is exactly the code both hardening passes changed.
3. Yes, acceptable if the boundary is explicit. **But I expect the feature gate to be unnecessary**, and the TODO should try without it first.

The reasoning on (3) is worth stating, because it changes the expected shape of the work. Every worker test constructs its session through `spawn_with_factory` with a mock implementing `WorkerSession`; `NativeClient` is referenced only in `session.rs` trait forwarding and in `DesktopWorker::spawn`, neither of which any unit test invokes. So the crate *links* LibVNCClient but never *calls* it under test. ThreadSanitizer reports on executed code, not linked code, so uninstrumented library internals should never appear. The likelier obstacle is Tokio: the 19 `#[tokio::test]` cases in `controller-api` exercise the work-stealing runtime, which has historically produced TSan false positives on its intrusive atomics. If that materializes, the right response is a documented `--skip` list for the async tests — which still leaves the entire worker and shutdown surface covered — rather than a feature gate.

Spec changes required:

- Split 2.4 into a ThreadSanitizer requirement and a Miri statement of scope.
- State plainly that Miri cannot cover FFI or Tokio paths and that this is a permanent boundary, not a deferred task.
- State that the historical evidence defect is the coverage claim, not the absence of a Miri run.

TODO changes required:

- Restructure CR4 as an ordered escalation: plain `--package controller-api --lib` first; then a documented `--skip` list if Tokio-specific reports appear; then a suppression file scoped to the library; then a test-only feature as the last resort.
- Require recording which step succeeded and why the earlier ones did not.
- Change the Miri item from "document whether any additional subset can run" to "record the permanent boundary" so it cannot be read as deferred work.
- Remove `Miri` from the CR15 list of gates that must show new coverage.

Implementation consequence:

- The realistic outcome is a new TSan job over `controller-api`, possibly with a short documented skip list. That is a meaningfully stronger gate than the current one for modest effort.

Remaining uncertainty:

- Whether Tokio under `-Zbuild-std` with the pinned `nightly-2026-08-01` produces false positives. Untested. This is the single largest unknown in the whole pass.

---

## Item 5: CR12 misses another sleep-only negative proof

Disposition: agree

Answer to each question:

1. Yes. I verified `authentication_failure_waits_for_manual_reconnect` in `crates/controller-api/src/worker/tests/reconnect.rs`: it reaches `AuthenticationFailed`, sleeps 30 ms, then asserts the factory call count is exactly 1. That is a sleep-only negative proof and I missed it. Good catch.
2. Elapsed time cannot prove a negative here; only causal progress can. Two mechanisms, in order of rigor:

   **Preferred — proof by causal progress.** Add a test-only worker-loop iteration counter. The test then asserts: the worker completed at least *N* further loop iterations after entering `AuthenticationFailed`, and the factory call count is still exactly 1. This replaces "we waited 30 ms" with "the worker had *N* opportunities to retry and did not," which is a real proof and fails immediately on regression instead of flaking under CI load.

   **Supporting — positive control.** After the negative assertion, submit `WorkerCommand::Reconnect` through the real client and assert the factory is called a second time within a bounded deadline. This proves the detector would have fired had a retry occurred, which is what makes the negative assertion trustworthy. A negative test with no positive control cannot distinguish "no retry happened" from "the test cannot observe retries."

   Both should be present. The same iteration-counter mechanism serves `mismatched_native_frame_never_reaches_connected`, so it is one hook for two tests.

Spec changes required:

- Add 2.12 coverage for `authentication_failure_waits_for_manual_reconnect` alongside the mismatched-frame test.
- State the principle that negative concurrency assertions require causal progress plus a positive control, never elapsed time.

TODO changes required:

- Name both tests explicitly in CR12.
- Add a checklist item to introduce the test-only loop-iteration counter.
- Require a positive control for every negative assertion converted under CR12.
- Retain the broader audit, now with two known cases named rather than one.

Implementation consequence:

- The loop-iteration counter is a small `#[cfg(test)]` hook on the worker loop. It must not change production behavior and must not become a synchronization point that alters timing.

Remaining uncertainty:

- Choosing *N*. It should be derived from the fixture rather than picked arbitrarily — for example, "at least three iterations observed" is sufficient because the retry decision is evaluated once per iteration.

---

## Item 6: CR5 needs a metric compatibility decision

Disposition: agree, with one factual correction

Answer to each question:

1. Remove immediately, no alias. See item 13 for the policy basis.
2. No. See item 13.
3. **Correction to the questions document.** I verified `StatusResponse` in `crates/controller-api/src/http/responses.rs`; it contains `state`, `started_at_unix_ms`, `connected_at_unix_ms`, `last_message_at_unix_ms`, `reconnect_attempts`, `last_failure`, `framebuffer_revision`, `rejected_commands`, `dropped_events`, `fatal_exit`, and `shutting_down`. There is **no** queue-depth field. The affected surfaces are exactly:
   - the Prometheus metric `vrc_worker_command_queue_depth` in `crates/controller-api/src/observability.rs`;
   - `WorkerClient::command_queue_depth()` in `crates/controller-api/src/worker/client.rs`, which is `pub`;
   - `HttpBackend::command_queue_depth()` and its `WorkerHttpBackend` implementation in `crates/controller-api/src/http/backend.rs`;
   - `docs/VNC_REMOTE_CONTROL_SERVER_V01_SPEC.md` section 17.1, which lists `queue_depth` as a suggested structured **log** field — a documentation-only mention.

   No HTTP response field changes. I also confirmed the R13 integration checks in `tests/integration/` do not reference any `vrc_` metric name, so the rename cannot break R13.
4. Yes, add `# HELP` and `# TYPE`. I verified the exporter currently emits neither — `Metrics::render` writes bare `name value` lines. This matters for the decision: the TODO's "rename **or** fix the `# HELP` text" alternative was never viable, because there is no `# HELP` text to fix. Adding them is the natural place to state the semantics, and doing it only for the renamed metric would be inconsistent, so it should be done for all of them.

Spec changes required:

- Correct 2.5 to state that no HTTP status field is affected and to enumerate the four real surfaces.
- Remove the "rename or change `# HELP`" alternative and require the rename, since the exporter emits no `# HELP`.
- Add the `# HELP` and `# TYPE` requirement as a distinct outcome covering the full exporter.

TODO changes required:

- Adopt `command_submissions_in_flight` for the Rust API and `vrc_worker_command_submissions_in_flight` for the metric, as proposed.
- Add a checklist item for `# HELP` and `# TYPE` across every exported metric, with correct `counter` versus `gauge` typing.
- Require the new metric's `# HELP` to state that the value may transiently exceed `vrc_worker_command_queue_capacity`.
- Add the V01 spec section 17.1 log-field mention to the documentation update list.
- Add a checklist item confirming no R13 assertion references the old name.

Implementation consequence:

- Adding `# TYPE` requires classifying every metric. Several `_total` names are counters and the state gauges are gauges; a mis-typed metric is worse than an untyped one, so this needs care.

Remaining uncertainty:

- Whether any Grafana dashboard or alert rule outside this repository consumes the old name. Not knowable from the repository; see item 13.

---

## Item 7: CR3 should prescribe the exact pixel-format contract

Disposition: agree

Answer to each question:

1. Proposed values, assigned in `vrc_client_connect` after `rfbGetClient` and before `SetFormatAndEncodings`:

   | Field | Value |
   |---|---|
   | `format.bitsPerPixel` | 32 |
   | `format.depth` | 24 |
   | `format.trueColour` | `TRUE` |
   | `format.bigEndian` | `FALSE` |
   | `format.redMax` | 255 |
   | `format.greenMax` | 255 |
   | `format.blueMax` | 255 |
   | `format.redShift` | 0 |
   | `format.greenShift` | 8 |
   | `format.blueShift` | 16 |

   `appData.requestedDepth` should be set to 24 to stay consistent with `format.depth`.

2. Guaranteed layout: `[R, G, B, X]`, with `X` being bits 24–31 of the pixel value and therefore unused padding.

   Derivation: `bigEndian = FALSE` fixes the on-wire and in-buffer byte order as little-endian for the 32-bit pixel value, independent of the host. `redShift = 0` places red in bits 0–7, which is byte 0 under little-endian; `greenShift = 8` places green in byte 1; `blueShift = 16` places blue in byte 2. This is what `replace_native_rgbx` already assumes when it reads `pixel[0]`, `pixel[1]`, `pixel[2]`.

   Worth noting why this is not the obvious choice: the conventional X11/VNC arrangement is `redShift = 16`, which yields `[B, G, R, X]` in little-endian memory. If the LibVNCClient default happens to be the conventional one, the current code is reading blue as red — which is exactly the defect this item exists to eliminate. Pinning the shifts makes the question moot rather than answering it by inspection.

3. Colors, coordinates, tolerance:
   - **Colors:** pure red `#FF0000` and pure blue `#0000FF`. Two colors are required, as the questions document says — a single red swatch cannot distinguish `[R,G,B,X]` from `[R,B,G,X]`.
   - **Placement:** the test application window is created at `800x600+20+20` with `minsize(800, 600)`, so geometry is stable. Add two `tk.Frame` swatches of at least 64x64 at fixed positions, and sample the **center** pixel of each, well inside the swatch, so that a one-pixel border or anti-aliasing cannot affect the result. Exact coordinates should be recorded in the test app and the test as named constants, not duplicated as literals.
   - **Assertion form:** assert **channel dominance**, not equality. For the red swatch: `r > 200 && g < 60 && b < 60`. For blue: `b > 200 && r < 60 && g < 60`. Dominance is robust to whatever encoding negotiation produces — Tight encoding can select lossy JPEG for photographic regions — while still failing hard on any channel swap, which is the defect under test. An exact-equality assertion with a tight tolerance would be fragile for no additional detection power.
   - If the E2E can pin encodings to a lossless set, tighten to `±8` per channel and record that decision.

4. Two layers, not four:
   - **Canonical RGBA framebuffer** — the primary assertion. This is the layer where the conversion contract lives and where a channel swap actually manifests.
   - **Decoded PNG from `GET /v1/screenshot.png`** — a secondary assertion in the HTTP E2E, decoding the PNG and re-checking dominance. This catches any channel error introduced by the encoder rather than the adapter.
   - Do **not** assert on the raw native framebuffer: it is the input to the contract, so asserting on it would restate the assumption instead of testing it.
   - Do **not** assert on encoded PNG bytes, as the TODO already prohibits.

Spec changes required:

- Replace the "choose shifts during implementation" language in 2.3 with the table above and the derived byte layout.
- State the two-color rationale explicitly.
- State that dominance rather than equality is the assertion form, with the lossy-encoding reason.

TODO changes required:

- Replace the open-ended CR3 format checklist with the specific field assignments.
- Add a checklist item to extend `desktop/test-app/test_app.py` with the two swatches at named constant coordinates.
- Specify the sampling coordinates, the dominance thresholds, and the two assertion layers.
- Add a verification step confirming `SetFormatAndEncodings` transmits `client->format` as assigned and does not override it from `appData`.

Implementation consequence:

- Modifying the test application changes a deterministic E2E fixture. Existing E2E assertions that depend on window layout must be re-checked; the swatches should be placed so they do not overlap the entry field or the control buttons.

Remaining uncertainty:

- Whether `SetFormatAndEncodings` in the pinned LibVNCClient forwards `client->format` unmodified. I believe it does, but I could not execute against the library, so this is a verification step rather than an assertion. The E2E color test is the real proof either way — which is precisely why the test matters more than the table.

---

## Item 8: CR11 presents allocation counts as settled facts before measurement

Disposition: agree

The criticism lands. I wrote "approximately four full-frame passes and three full-frame allocations" as a finding when it was a reading of the code, not a measurement. `Vec<u8>` to `Arc<[u8]>` conversion behavior in particular is a standard-library implementation detail I should not have stated as fact on a pinned toolchain I never ran.

Answer to each question:

1. **No.** CR11 must not block completion. Measurement and the corrected record are required; optimization is conditional on evidence. See item 14, where I go further.
2. Yes, exactly that split.
3. A counting global allocator under `#[cfg(test)]`: a wrapper type around `System` that increments allocation and deallocation counters and accumulates bytes, installed with `#[global_allocator]` in the benchmark or test binary. This measures rather than infers. It is process-wide within that binary, which is acceptable for a dedicated measurement target and is the reason it should not live in the main test binary.
4. A dedicated one-time evidence utility, not a permanent Criterion target. Rationale: a permanent benchmark target is infrastructure that must be maintained, kept green, and eventually wired into CI to have value; adding it to satisfy a documentation correction inverts the cost. If measurement shows a change worth making, a permanent target can be justified then, in the follow-up performance document.

Spec changes required:

- Downgrade every allocation-count statement in 2.11 from finding to hypothesis, with explicit "to be measured" markers.
- State that the confirmed defect is the *incompleteness of the recorded review*, not any specific allocation count.

TODO changes required:

- Restate the measurement items as measurements, not confirmations.
- Add the counting-allocator approach as the required method.
- Specify a one-time evidence utility and state why a permanent Criterion target is deferred.
- Make every optimization item explicitly conditional and non-blocking.

Implementation consequence:

- If measurement shows the conversion loop is negligible relative to the native copy, the correct outcome is a corrected record and no code change. That must be an acceptable completion state.

Remaining uncertainty:

- All of the specific numbers. That is the point of the item.

---

## Item 9: The blanket failing-runtime-test rule is too broad

Disposition: agree

The rule as written would have forced contortions — a "failing runtime test" for removing an unreachable match arm is not a meaningful artifact, and demanding one would encourage writing a fake test to satisfy a checkbox. That is the opposite of the rule's intent.

Answer to each question:

1. Yes, task-specific.
2. Classification:

   | Item | Required evidence |
   |---|---|
   | CR1 pre-`Connected` stall | Failing production-path runtime test |
   | CR2 illegal transition visibility | Failing production-path runtime test |
   | CR3 pixel format | Failing E2E color assertion, or documented static evidence of the current byte layout if the E2E cannot run before the fix |
   | CR4 sanitizer coverage | Failing or absent workflow invocation, with recorded output |
   | CR5 metric semantics | Failing runtime test showing the value exceeding capacity |
   | CR6 shutdown deadline | Failing configuration-validation test plus a documented timing calculation |
   | CR7 startup bound | Documented timing calculation only |
   | CR8 unreachable arms | Static source evidence only |
   | CR9 secret scrubbing | Focused helper test, no production runtime failure required |
   | CR10 privacy assertions | Path-carrying evidence per item 3; the tests are regression guards and may pass on the baseline |
   | CR11 framebuffer performance | Measurement evidence only |
   | CR12 sleep-only tests | Demonstration that the current test passes under an injected fault it should catch |

   CR12 deserves comment: the right baseline evidence for a weak test is not that it fails, but that it *passes when it should not*. Inject a fault the test claims to detect — an automatic retry — and show the sleep-based assertion still passes or flakes. That is the honest reproduction for a test-quality defect.

Spec changes required:

- Rewrite section 5 to require baseline evidence appropriate to the task, enumerating the admissible forms from the questions document.
- Retain "no repair precedes its evidence" as the invariant.

TODO changes required:

- Add the classification table to CR0 so the evidence form is fixed before work starts.
- Amend the do-not-accept list from "no fix without a failing test" to "no fix without its classified baseline evidence."

Implementation consequence:

- CR10's tests may all pass on the baseline. Under the old rule that would have looked like a failure to reproduce; under the new one it is the expected outcome for a regression guard.

Remaining uncertainty:

- None material.

---

## Item 10: Recommended CR1/CR2 state-transition strategy

Disposition: agree

This is the strongest item in the review. Of my three CR1 options, the first — widening the state table — is the one I would have been most tempted by and is the wrong one, for the reason given: it makes `Degraded` mean both "was healthy, now impaired" and "never became healthy," which destroys the state's diagnostic value and would propagate into the `vrc_connection_state` metric and the WebSocket event stream.

Answer to each question:

1. Yes. Pre-`Connected` stalls should record the timeout, invalidate, and schedule reconnect without entering `Degraded`. The state graph is unchanged.
2. Yes. `transition()` should emit `worker_illegal_state_transition` with `from` and `to` only, return the error, and mutate nothing. A function whose failure path silently changes externally visible health is the root cause of the CR2 defect; removing the mutation eliminates the class rather than patching one instance.
3. `run_worker` — and it already does. It sets `fatal_exit = true` when the loop exits with `orderly_shutdown == false`. Concentrating the decision there means `fatal_exit` has exactly one writer on the exit path, which is what makes it auditable. `LoopState::publish` also sets it on sequence overflow; that one is a genuine unrecoverable condition and can remain, but it should be reviewed for the same one-writer principle.
4. **No, and I recommend against it.** Returning `Result` propagates the problem to the caller instead of removing it. `schedule_reconnect()` should be made *unable* to fail: compute the correct target state from the current state rather than blindly attempting `Disconnected` and then `Reconnecting`. The current code does `if state != Disconnected { transition(Disconnected) }` followed by `transition(Reconnecting)`, which can attempt an illegal edge from `AuthenticationFailed` — where only `Reconnecting` and `Stopped` are legal. Selecting the target from the current state makes the illegal attempt unrepresentable, which is strictly better than making it returnable. Fewer `Result`s, not more.
5. It cannot fail as the table stands: `can_transition_to` permits every state to reach `Stopped`, and the trailing `|| self == next` makes it idempotent. So `let _ = state.transition(Stopped)` is safe today. But it is safe by a property of a table that lives in a different crate, which is fragile. Recommend a `debug_assert!` on the transition legality plus the `worker_illegal_state_transition` diagnostic from (2), so a future table edit that breaks the property is caught in debug builds and observable in production rather than silently producing a worker that exits without reaching `Stopped`.

Spec changes required:

- Replace the three-option CR1 menu in 2.1 with the single prescribed strategy.
- Add the reasoning that `Degraded` must retain one meaning, and that this is why the state table is not widened.
- Add to 2.2 that `transition()` becomes side-effect-free on failure and that `fatal_exit` gains a single writer on the exit path.

TODO changes required:

- Remove the strategy menu; prescribe the pre-`Connected` path directly.
- Add a checklist item to make `schedule_reconnect()` select its target from the current state so it cannot attempt an illegal edge.
- Add a checklist item to remove the `fatal_exit` mutation from `transition()`.
- Add a checklist item to review `LoopState::publish`'s overflow-path `fatal_exit` write against the one-writer principle.
- Add the `debug_assert!` plus diagnostic for the final `Stopped` transition.
- Add a regression test that `schedule_reconnect()` from `AuthenticationFailed` performs no illegal transition and emits no diagnostic.

Implementation consequence:

- Removing the `fatal_exit` mutation from `transition()` changes behavior anywhere an illegal transition currently occurs. If any existing test depends on that mutation, that dependency is itself a bug and should be surfaced rather than preserved.

Remaining uncertainty:

- Whether any currently-reachable illegal transition exists besides the two identified. The `schedule_reconnect()` path from `AuthenticationFailed` looks unreachable today because `begin_connect()` always transitions to `Connecting` or `Reconnecting` first, but that is a reachability argument across two functions, which is exactly the kind of reasoning the diagnostic should replace.

---

## Item 11: Clarify the startup-timeout contract

Disposition: agree

Answer to each question:

1. One total startup budget. The same reasoning as item 1: `startup_timeout` reads as the deadline for starting up, and a value that can be exceeded by 2x is a misleading contract.
2. The total-budget interpretation becomes authoritative in the spec, the operator guide, and the doc comment on `spawn_with_factory_and_startup_hook`.

The four-step structure in the questions document is correct and I adopt it as written. One addition: when the acknowledgement wait consumes the entire budget, the cleanup phase receives zero remaining time. That case needs the same explicit handling as item 1 — set the flag, send the counted best-effort nudge, skip the bounded wait, detach deliberately, and return `DesktopError::Timeout` — so that a tight `startup_timeout` degrades predictably instead of producing a confusing second timeout.

Spec changes required:

- Rewrite 2.7 to prescribe the single-budget interpretation rather than offering a choice.
- State the zero-remainder degradation explicitly.

TODO changes required:

- Replace CR7's "document or derive" alternative with the derived single budget.
- Add checklist items for deadline establishment before the acknowledgement wait, remaining-budget computation with saturating arithmetic, and zero-remainder handling.
- Preserve the existing timeout-versus-panic result distinction, which is correct today and must not regress.
- Add the operator-guide update.

Implementation consequence:

- The observable worst-case startup latency roughly halves for a given configured value. Any deployment relying on the current effective 2x behavior would need its `startup_timeout` raised. This is a behavior change and belongs in the release notes.

Remaining uncertainty:

- Whether any Compose healthcheck or deployment timing in `deploy/` was tuned against the current effective 2x bound. Should be checked during implementation.

---

## Item 12: Clarify the scope of secret scrubbing

Disposition: agree

Answer to each question:

1. Yes, deliberately out of scope for this pass — but the spec failed to say so, which is the defect.
2. Yes, and the reason should be recorded rather than implied. The two credentials differ in a way that matters: the VNC password is copied across an FFI boundary into allocations the shim owns and frees, and it is truncated and re-copied by the authentication exchange, so it has a genuine multi-copy lifecycle worth controlling. The API token is a single `Arc<str>` held for the process lifetime, compared in constant time, and never crosses into C. Zeroizing something that is intentionally resident until process exit buys very little.
3. Yes — a common non-`Debug`, zeroizing secret type is the right end state even though the lifetimes differ, because divergent secret-handling policy within one codebase is how inconsistencies start. The recommendation is: build the shared type in this pass, adopt it for the VNC password, and record API-token adoption as an explicitly deferred follow-up with its rationale. That gets the abstraction right without expanding this pass's blast radius into the authentication path, which is the most security-sensitive code in the repository and should not be refactored incidentally.

Spec changes required:

- Add an explicit scope boundary subsection to 2.9 covering both credentials.
- Record the lifecycle difference as the justification, not merely the scope decision.
- State that the shared type is introduced now and the token adoption is deferred.

TODO changes required:

- Add a checklist item to design the secret type for both credentials even though only one adopts it in this pass.
- Add a checklist item to record the deferred token adoption in the follow-up list, with its rationale.
- Add a checklist item confirming the token's `ct_eq` comparison path is untouched.

Implementation consequence:

- The secret type must support the `Arc<str>` sharing pattern the token uses, or the deferral becomes permanent because the type will not fit when it is eventually adopted. Worth designing for now even though it is not used now.

Remaining uncertainty:

- None material.

---

## Item 13: Clarify metric/API compatibility policy before renaming public fields

Disposition: agree

Answer to each question:

1. **No such policy exists.** I checked `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`, which is scoped entirely to security and native-safety gates — vulnerability handling, VEX determinations, toolchain pinning — and says nothing about metric or API naming stability. `docs/openapi.json` documents the HTTP surface but not the Prometheus exposition. So there is no stated commitment to break.
2. Yes. The repository is `v0.1` throughout, the release policy is titled for the v0.1 release candidate, and there are no released consumers documented. A clean rename with no alias is appropriate.
3. Not required. But if the project later concludes an external consumer exists, the safe form is to emit both names from the same source value for one release with the old one marked deprecated in its `# HELP`, then remove it. Emitting both from the same value is what prevents the contradictory-values failure mode; two independently computed metrics would be the mistake.

The absence of a policy is itself worth fixing, since this question will recur every time a metric changes.

Spec changes required:

- Record the finding that no naming-compatibility policy exists and that the rename is safe on that basis.
- Note that R13 asserts no metric names, so the rename cannot affect it.

TODO changes required:

- Add a checklist item to add a short metric and API naming-compatibility statement to the release policy document, so the next rename has a rule to follow.
- Record the no-alias decision and its basis.
- Add a checklist item confirming no `deploy/` dashboard, alert rule, or Compose healthcheck references the old metric name.

Implementation consequence:

- Adding a naming policy is a small documentation change with disproportionate long-term value; it should not be dropped as scope creep.

Remaining uncertainty:

- External consumers outside the repository cannot be ruled out from inside it. That is a decision for you, not an analysis I can complete.

---

## Item 14: Clarify whether CR11 belongs in this correctness pass

Disposition: agree, and I would go further than the questions document

Answer to each question:

1. Yes — measurement and disposition only.
2. Yes, and I would make the split cleaner than the document proposes. Rather than allowing a "trivial, clearly safe improvement" to remain in scope, I recommend **no code optimization in this pass at all**. The reason is that "trivial and clearly safe" is a judgment made mid-pass by whoever is holding the diff, and it is exactly the judgment that lets a framebuffer change land in a state-machine and shutdown-adjacent correctness pass. `replace_native_rgbx` feeds the byte-equality duplicate detection that protects ETag stability and the R13 conditional `304` contract; a rewrite of that loop is never *clearly* safe, however small it looks.

   The cost of deferring is one extra document and one extra CI cycle. The cost of mixing is a correctness pass whose bisection surface includes the framebuffer hot path.

Spec changes required:

- Restate 2.11 as a documentation-completeness defect plus a measurement obligation, with optimization out of scope entirely.
- State the ETag and R13 coupling as the reason optimization is excluded, so the exclusion reads as a technical judgment rather than schedule management.

TODO changes required:

- Reduce CR11 to: measure with the counting allocator; record results; correct the historical performance record; open a follow-up performance document if the measurements justify one.
- Remove every optimization checklist item from CR11.
- Remove the byte-equality-preservation proof item, which becomes unnecessary once no code changes.
- Add the follow-up document to the deferred list alongside the bridge wake-up from item 1 and the token adoption from item 12.

Implementation consequence:

- CR11 becomes cheap and non-blocking, which is the correct weight for a documentation correction.

Remaining uncertainty:

- None material.

---

## Consolidated decision list

1. **Shutdown-timeout semantics.** `VRC_SHUTDOWN_TIMEOUT_MS` is one total process-cleanup budget. `finalize_runtime` establishes a single deadline; worker shutdown takes the remaining budget, bridge shutdown takes what remains after it. Floor is `max(500 ms, 8 * EVENT_BRIDGE_POLL_INTERVAL)`, derived in code. Zero remainder degrades to stop-request plus deliberate detach. Server, worker, bridge error precedence unchanged. Direct bridge wake-up deferred, with the `crossbeam-channel` supply-chain cost recorded as the reason.

2. **Startup-timeout semantics.** `startup_timeout` is one total startup budget. Deadline established before the acknowledgement wait; cleanup uses only the remainder; zero remainder degrades to flag, counted nudge, detach, `Timeout`. Timeout-versus-panic distinction preserved. Effective worst-case latency roughly halves — a behavior change for the release notes.

3. **CR1/CR2 state-machine strategy.** Do not widen the state table. Pre-`Connected` stalls record the timeout, invalidate, and schedule reconnect without entering `Degraded`. `transition()` emits `worker_illegal_state_transition` with `from` and `to` only and mutates nothing on failure. `run_worker` remains the single writer of `fatal_exit` on the exit path. `schedule_reconnect()` stays infallible and selects its target from the current state so an illegal edge is unrepresentable — it does not return `Result`. Final `Stopped` transition keeps `let _` plus a `debug_assert!` and the diagnostic.

4. **Native pixel-format contract.** `bitsPerPixel` 32, `depth` 24, `trueColour` TRUE, `bigEndian` FALSE, all three `*Max` 255, `redShift` 0, `greenShift` 8, `blueShift` 16, `appData.requestedDepth` 24. Guaranteed layout `[R, G, B, X]`. E2E renders `#FF0000` and `#0000FF` swatches at named constant coordinates, samples swatch centers, and asserts channel dominance (`>200` dominant, `<60` others) at the canonical RGBA layer and again on the decoded PNG. Raw native framebuffer is not asserted.

5. **TSan and Miri boundaries.** TSan escalation: plain `--package controller-api --lib` first; documented `--skip` list for Tokio false positives; library-scoped suppressions; test-only feature last. Record which step succeeded. Miri stays on `remote-desktop-core` permanently — FFI and Tokio place `controller-api` out of reach by construction, and this is a recorded boundary, not deferred work. Miri drops off the CR15 new-coverage list.

6. **Metric rename and compatibility.** Rename to `command_submissions_in_flight` and `vrc_worker_command_submissions_in_flight`. No alias — no compatibility policy exists, the project is v0.1, and R13 asserts no metric names. Add `# HELP` and `# TYPE` to every exported metric, with the new metric's help text stating it may exceed capacity. No HTTP status field is affected. Add a naming-compatibility statement to the release policy so the next rename has a rule.

7. **Secret ownership and zeroization.** Build one shared non-`Debug`, zeroizing secret type; adopt it for the VNC password now; defer API-token adoption with its rationale recorded. Scrub via a project-owned `vrc_secure_scrub` using a `volatile unsigned char *` loop — `explicit_bzero` will not compile under `_POSIX_C_SOURCE 200809L` with `-std=c11 -pedantic -Werror`, and glibc has no `memset_s`. The `vrc_get_password` return value is owned by LibVNCClient and is a documented residual, not a closed gap; verify the pinned library's behavior and record it. The `CString` in `NativeClient::connect` is a real copy requiring explicit handling.

8. **Privacy-test structure.** Four path-specific tests, not one omnibus test: key and coordinate sentinels through worker input release; typed-text and clipboard sentinels through the `desktop_command_failed` error path; VNC-password sentinel through `NativeError::NativeFailure` propagation; bearer-token sentinel through HTTP access and authentication logging. Add `capture_json_logs` to `test_support.rs` and assert on parsed field values. No sentinel may be asserted on a path that does not carry it.

9. **Benchmark scope.** Measurement and record correction only. No code optimization in this pass at all — not even a trivial-looking one — because `replace_native_rgbx` feeds the byte-equality duplicate detection protecting ETag stability and the R13 `304` contract. Measure allocations with a `#[cfg(test)]` counting global allocator in a one-time evidence utility, not a permanent Criterion target. Optimization moves to a follow-up performance document if the numbers justify one.

10. **Sleep-only test replacements.** Both `mismatched_native_frame_never_reaches_connected` and `authentication_failure_waits_for_manual_reconnect` are converted. Mechanism: a test-only worker-loop iteration counter proving causal progress, plus a positive control that submits `Reconnect` and confirms the fixture detects a retry when one occurs. Elapsed time is not admissible as proof of a negative. The broader audit remains, now with two named cases.

Additional decision arising from item 9, not on the original list:

11. **Baseline-evidence standard.** Task-specific rather than blanket. Production-path runtime tests for CR1, CR2, CR5. Workflow evidence for CR4. Configuration test plus timing calculation for CR6. Timing calculation only for CR7. Static evidence for CR8. Focused helper test for CR9. Path-carrying evidence for CR10, which may pass on the baseline. Measurement for CR11. For CR12, the reproduction is that the current test *passes under an injected fault it claims to detect* — a weak test is reproduced by showing it does not fail, not by making it fail.

## Deferred follow-up items

Recorded here so they are not lost when the spec and TODO are revised:

1. Direct event-bridge wake-up to remove the `EVENT_BRIDGE_POLL_INTERVAL` dependency in clean shutdown (item 1).
2. API bearer-token adoption of the shared secret type (item 12).
3. Framebuffer per-frame allocation optimization, conditional on CR11 measurements (items 8 and 14).
4. Metric and API naming-compatibility policy in the release policy document (item 13) — small enough to do in this pass, listed here so it is not dropped as scope creep.
