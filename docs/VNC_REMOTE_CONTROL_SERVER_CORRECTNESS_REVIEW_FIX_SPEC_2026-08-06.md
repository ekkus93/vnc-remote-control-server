# VNC Remote Control Server Correctness Review Fix Spec

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Code baseline reviewed for the defects: `e9be696783e7fdfb90389cd02890d48c3e9bbd2d`

Planning baseline containing the review discussion and answers: `c49742a2d1e1c3b55ae3f3f8affec9357b8855f4`

Companion TODO:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_TODO_2026-08-06.md`

Decision documents:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_QUESTIONS_AND_ISSUES_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_ANSWERS_2026-08-06.md`

Related documents:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_EVIDENCE_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`
- `docs/LIBVNCCLIENT_BINDING_DECISION.md`

## 1. Purpose

A static review of the validated shutdown-hardening tree found a serious pre-`Connected` stall-recovery defect and several correctness, observability, native-format, sanitizer-coverage, secret-lifecycle, privacy-test, metric-semantics, timeout-contract, and test-quality issues outside the already-completed shutdown architecture.

The shutdown architecture itself remains preserved:

- the out-of-band `Arc<AtomicBool>` remains authoritative for worker shutdown;
- queue accounting remains ownership-based and the permit remains acquired before `try_send`;
- `EventBridge` retains its stop flag, exit signal, bounded join, and deliberate detach model;
- process error precedence remains server, then worker, then bridge;
- framebuffer byte equality, screenshot ETag stability, and the R13 conditional `304` contract remain unchanged;
- state-aware input-release reporting remains intact.

This revised specification incorporates the decisions in the questions and answers documents. It removes unresolved implementation menus and defines one accepted contract for each issue.

The environment used for the original review had no Rust toolchain and no Docker runtime. Evidence requirements are therefore task-specific: runtime defects require deterministic reproductions, workflow defects require workflow evidence, static-cleanup items require static evidence, secret scrubbing requires focused live-buffer tests, and performance claims require measurement rather than inference.

## 2. Correctness and hardening requirements

### 2.1 Pre-`Connected` confirmed stalls must reconnect without fatal exit

A native session can exist while the public state remains `Connecting` or `Reconnecting`. The current confirmed-stall path always attempts `transition(ConnectionState::Degraded)`. That transition is legal from `Connected`, but illegal from `Connecting` and `Reconnecting`; the error escapes `poll()` and terminates the worker.

The repair is prescribed:

- do **not** add `Connecting -> Degraded` or `Reconnecting -> Degraded` to the state table;
- preserve `Degraded` as meaning “a previously healthy connection became impaired”;
- when a confirmed stall occurs while the state is `Connected`, preserve the existing `Connected -> Degraded -> invalidation -> reconnect` path;
- when a confirmed stall occurs while the state is `Connecting` or `Reconnecting`, record the timeout, invalidate the session/framebuffer, and schedule reconnect without entering `Degraded`;
- the recoverable path must not set `fatal_exit` and must not terminate the worker loop;
- `worker_stall_timeout` remains emitted without payloads.

The production-path regression must drive a real worker session that never delivers a complete framebuffer update, observe at least one reconnect attempt, and prove `fatal_exit == false` and `state != Stopped` until explicit shutdown.

### 2.2 Illegal transitions must be observable and side-effect-free on failure

`LoopState::transition()` currently mutates `fatal_exit` before returning an error. A discarded transition result can therefore poison externally visible health.

The revised contract is:

- an illegal transition emits `worker_illegal_state_transition` with only `from` and `to` state names;
- the state and `fatal_exit` are unchanged when `transition()` returns an error;
- `run_worker` remains the owner of `fatal_exit = true` when the worker exits unexpectedly;
- the sequence-overflow write in `LoopState::publish` must be reviewed and either retained with an explicit unrecoverable rationale or moved to the same centralized fatal-exit policy;
- `schedule_reconnect()` remains infallible but selects its transition target from the current state so an illegal edge is not attempted;
- no `transition()` result may be discarded merely because the current table makes failure unlikely.

Final shutdown-state handling must also be explicit. The implementation must not retain `let _ = state.transition(ConnectionState::Stopped)` as the only handling. If the final transition unexpectedly fails:

- emit a dedicated diagnostic;
- mark the exit fatal in the explicit finalization path;
- retain a `debug_assert!` for the invariant that every state can reach `Stopped`;
- do not silently exit with stale public state.

### 2.3 The LibVNCClient pixel format must be explicit and verified end to end

The shim must assign the following fields after `rfbGetClient` and before `SetFormatAndEncodings`:

| Field | Required value |
|---|---:|
| `format.bitsPerPixel` | `32` |
| `format.depth` | `24` |
| `format.trueColour` | `TRUE` |
| `format.bigEndian` | `FALSE` |
| `format.redMax` | `255` |
| `format.greenMax` | `255` |
| `format.blueMax` | `255` |
| `format.redShift` | `0` |
| `format.greenShift` | `8` |
| `format.blueShift` | `16` |
| `appData.requestedDepth` | `24` |

The negotiated native byte contract is `[R, G, B, X]`, with byte 3 unused padding. `replace_native_rgbx()` continues to convert this to canonical `[R, G, B, 255]`.

The implementation must verify that the pinned LibVNCClient sends the assigned `client->format` and does not overwrite it from `appData`. Static source inspection is supporting evidence; the E2E color assertion is authoritative.

The desktop test application must render two fixed, non-overlapping swatches with named constants:

- pure red `#FF0000`;
- pure blue `#0000FF`.

Tests sample the center of each swatch at two layers:

1. canonical RGBA framebuffer;
2. decoded PNG returned by `GET /v1/screenshot.png`.

Default assertions use channel dominance:

- red: `r > 200`, `g < 60`, `b < 60`;
- blue: `b > 200`, `r < 60`, `g < 60`.

If the E2E pins a lossless encoding, the implementation may tighten the tolerance to `±8`, but the chosen mode and threshold must be documented. Tests must not assert on encoded PNG bytes and must not use the raw native framebuffer as the primary proof.

### 2.4 ThreadSanitizer must cover the concurrent crate; Miri scope must be stated honestly

The existing ThreadSanitizer and Miri jobs run against `remote-desktop-core`, which does not contain the worker/event/shutdown concurrency changed by the hardening passes.

Required ThreadSanitizer escalation order:

1. run `--package controller-api --lib` directly;
2. if Tokio-specific false positives occur, use a short documented `--skip` list while preserving all worker, shutdown, event-bridge, and framebuffer tests;
3. if required, use a suppression file scoped to the responsible library/runtime;
4. use a test-only feature excluding the native adapter only as the final option;
5. record which level succeeded and why earlier levels did not.

No `continue-on-error` is permitted. The existing core TSan, core Miri, and adapter ASan coverage remain.

Miri is not required to cover `controller-api`. FFI, native linkage, Tokio, and real I/O are a permanent coverage boundary. The corrective action for Miri is to state that boundary accurately and remove any claim that the hardening pass added Miri coverage to the concurrent code.

### 2.5 Rename the queue metric to match its actual semantics

The RAII permit is acquired before `try_send`; this ordering is required for final-drain correctness and must not move. The value therefore measures command submissions/envelopes participating in submission or queue ownership, not literal channel occupancy. It may transiently exceed configured channel capacity.

Required rename:

- Rust API concept: `command_submissions_in_flight`;
- Prometheus metric: `vrc_worker_command_submissions_in_flight`.

There is no queue-depth field in `/v1/status`; no HTTP response schema change is required. The affected surfaces are the Prometheus exporter, `WorkerClient`, `HttpBackend`/`WorkerHttpBackend`, tests, and documentation.

The old metric is removed without an alias because the repository is v0.1, no naming-stability policy exists, no repository-local consumer is documented, and R13 does not assert the old name. Before removal, search `deploy/`, tests, dashboards, alert rules, examples, and documentation. External consumers cannot be discovered from the repository and remain an operator responsibility.

Add valid Prometheus `# HELP` and `# TYPE` records for every exported metric. The new metric’s help text must state that it may transiently exceed `vrc_worker_command_queue_capacity`. Add a short metric/API naming-compatibility rule to the release policy.

No queue accounting behavior changes are permitted.

### 2.6 Process shutdown must use one total configured cleanup budget

Add `VRC_SHUTDOWN_TIMEOUT_MS` as a dedicated process-cleanup budget. It is not a per-phase timeout.

`finalize_runtime` must:

1. establish one deadline before worker cleanup;
2. pass the current remaining duration to worker shutdown;
3. recompute the remaining duration with saturating arithmetic;
4. pass the remainder to bridge shutdown;
5. preserve server → worker → bridge error precedence;
6. attempt both cleanup surfaces even when an earlier surface fails, subject to the shared total budget.

The minimum accepted value is a derived constant:

```text
max(500 ms, 8 * EVENT_BRIDGE_POLL_INTERVAL)
```

Do not add a new channel dependency or redesign the bridge wake-up in this pass. The 50 ms polling dependency is accepted and documented as a deferred performance/latency improvement.

When no budget remains before bridge waiting:

- request bridge stop;
- perform a nonblocking exit check before detaching;
- if exit is already observed, join and preserve a panic result;
- detach only if the bridge is still active;
- record a payload-free timeout/secondary-cleanup diagnostic;
- do not call a zero-duration blocking wait and do not discard an already-available exit result.

`command_ack_timeout` remains exclusively the HTTP command acknowledgement timeout.

### 2.7 Startup timeout must also be one total budget

`startup_timeout` is the complete startup budget, not two sequential equal waits.

The worker spawn path must:

1. establish a deadline before waiting for startup acknowledgement;
2. on timeout, set the shutdown flag first;
3. send the best-effort permit-counted compatibility nudge;
4. use only the remaining duration for cleanup/exit observation;
5. preserve timeout versus panic/join-failure distinction;
6. if no budget remains, perform a nonblocking exit observation, join if already exited, otherwise detach deliberately and return `DesktopError::Timeout`.

The doc comment, operator guide, deployment timing, release notes, and relevant healthcheck assumptions must reflect the single-budget behavior. The effective worst case is reduced from approximately twice the configured value to the configured value.

### 2.8 Remove unreachable shutdown error forwarding

`EventBridge::shutdown` and `DesktopWorker::shutdown` must no longer contain a generic `Err(error) => Err(error)` arm for a wait function that can return only success or timeout.

Prefer a narrower internal wait result. If a third outcome is introduced in the future, it must receive explicit diagnostics and tests rather than silently flowing through a catch-all arm.

### 2.9 Scrub every project-owned VNC password copy; document the library-owned residual

Introduce a shared, non-`Debug`, zeroizing secret abstraction designed to support both owned string storage and future shared token storage. Adopt it for the VNC password in this pass. API bearer-token adoption is deliberately deferred; its constant-time comparison path remains untouched.

Audit and minimize project-owned copies in:

- the secret-file reader;
- `ControllerConfig`;
- `NativeClientConfig`;
- `WorkerSettings` and its clones;
- worker thread closure capture;
- the temporary `CString` used by `NativeClient::connect`;
- the C shim’s duplicated password storage.

The C shim must implement a project-owned scrub helper:

```c
vrc_secure_scrub(void *buffer, size_t length)
```

using a `volatile unsigned char *` write loop. Do not use `explicit_bzero` under the current `_POSIX_C_SOURCE 200809L`, `-std=c11`, `-pedantic`, and `-Werror` translation-unit contract. Do not rely on optional `memset_s`. No new feature-test macro should be introduced solely for scrubbing.

The Rust zeroization tests must not read freed memory. Required evidence:

- direct live-buffer scrub-helper test;
- instrumented proof that the secret wrapper invokes the scrub operation on drop;
- no secret value printed on failure;
- native C build remains warning-free under strict flags.

The allocation returned by `vrc_get_password()` becomes owned by LibVNCClient after callback return. The shim has no post-authentication hook to scrub it. Inspect the exact pinned Debian LibVNCClient source and record whether it scrubs before `free`. This copy is a documented residual if the library does not scrub it; the pass must not claim that every third-party-owned copy is zeroized.

Completion language must be: every project-owned VNC password copy is scrubbed before release, and any library-owned residual is explicitly documented.

### 2.10 Privacy tests must exercise real value-carrying paths

Add `capture_json_logs` to the test support layer and deserialize structured records. Raw-string searches remain a secondary defense, not the primary assertion.

Use separate tests:

1. **Input release:** distinctive key and coordinate values travel through the real worker and forced release failure; logs contain counts only.
2. **Typed text and clipboard:** sentinel values travel through command validation/failure paths that render `DesktopError`; assert no structured field value contains either sentinel.
3. **VNC password:** a sentinel password travels through a failing native connection/error path; assert it does not appear in native or controller logs.
4. **Bearer token:** correct and incorrect sentinel tokens travel through real HTTP authentication/access logging; assert neither token appears and the authorization field is redacted.

A sentinel may be asserted only in a test that names and exercises the production mechanism carrying that value. Generic nouns such as `clipboard` and `framebuffer` are not privacy assertions.

Some privacy tests may pass on the baseline; they are valid regression guards and are not required to manufacture a failing reproduction.

### 2.11 Framebuffer performance work is measurement-only in this pass

The prior performance record inferred allocation counts and omitted major stages. The corrective requirement is measurement and documentation, not optimization.

Create a committed, reproducible measurement utility under a stable path such as:

- `tools/framebuffer_measurement/`; or
- `tests/measurement/framebuffer/`.

It may be excluded from normal CI, but it must include instructions, inputs, output format, and the exact command required to reproduce the results. It must not be a disposable uncommitted script.

Use a dedicated process with a counting global allocator to measure, at minimum, a 1920×1080 complete-frame path:

- allocation count and bytes;
- native framebuffer copy;
- RGBX-to-RGBA conversion;
- equality comparison/write-lock hold time;
- `Vec<u8> -> Arc<[u8]>` conversion behavior on the pinned toolchain.

Treat all current allocation/pass counts as hypotheses until measured.

No framebuffer optimization is allowed in this correctness pass, including apparently trivial loop rewrites. The hot path participates in byte-equality duplicate detection, screenshot ETag stability, and R13 conditional `304` behavior. If the measurements justify optimization, create a separate performance spec/TODO and validate it independently.

### 2.12 Replace both known sleep-only negative tests with causal progress

Convert both:

- `mismatched_native_frame_never_reaches_connected`;
- `authentication_failure_waits_for_manual_reconnect`.

Add a `#[cfg(test)]` worker-loop iteration counter or equivalent non-production hook that observes causal loop progress without changing production timing.

Each negative assertion must prove:

- the worker completed at least a fixture-derived number of further iterations after reaching the relevant state;
- the prohibited retry or transition did not occur;
- a positive control can trigger and observe the corresponding reconnect/retry path within a bounded deadline.

Elapsed sleep is not admissible as proof that something did not happen. Every blocked test thread must have a bounded release path.

## 3. Baseline evidence classification

No repair may precede its classified evidence, but evidence form is task-specific:

| Item | Required baseline evidence |
|---|---|
| CR1 pre-`Connected` stall | Failing production-path runtime test |
| CR2 illegal transition visibility | Failing production-path runtime test |
| CR3 pixel format | Failing E2E color assertion, or exact static current-layout evidence if pre-fix E2E cannot run |
| CR4 sanitizer coverage | Missing/failing workflow invocation with recorded output |
| CR5 metric semantics | Runtime test showing in-flight count can exceed capacity |
| CR6 shutdown deadline | Failing configuration test plus timing calculation |
| CR7 startup bound | Timing calculation and source evidence |
| CR8 unreachable arms | Static source evidence |
| CR9 secret scrubbing | Focused live-buffer/helper evidence; no freed-memory inspection |
| CR10 privacy assertions | Path-carrying evidence; regression guards may pass on baseline |
| CR11 framebuffer performance | Reproducible measurement evidence |
| CR12 sleep-only tests | Demonstration that the old test can pass under an injected fault it claims to detect |

## 4. Required outcomes

1. Pre-`Connected` confirmed stalls reconnect without entering `Degraded`, without fatal exit, and without terminating the worker.
2. Illegal transitions emit a payload-free diagnostic and mutate neither state nor health on failure.
3. Final transition to `Stopped` is handled explicitly and cannot fail silently.
4. Native `[R,G,B,X]` format is pinned and red/blue channel order is verified in canonical RGBA and decoded PNG.
5. TSan exercises `controller-api` concurrency; Miri’s permanent boundary is documented accurately.
6. Queue instrumentation is renamed to submissions-in-flight and all Prometheus metrics have correct `# HELP` and `# TYPE` records.
7. Process shutdown and startup each obey one total configured budget.
8. Zero-budget cleanup observes already-completed exits before deliberate detach.
9. Unreachable shutdown error arms are removed.
10. Every project-owned VNC password copy is scrubbed; third-party residuals are verified and documented.
11. Privacy tests parse structured records and exercise real value-carrying paths.
12. Framebuffer allocation/pass claims are measured with a committed reproducible utility; no optimization is mixed into this pass.
13. Both known sleep-only negative tests use causal progress and positive controls.
14. Existing HTTP, WebSocket, framebuffer, ETag, R13, input, shutdown, and release-gate behavior remains green.

## 5. Non-goals and preservation requirements

This pass must not:

- widen the connection-state table merely to accommodate the stall defect;
- change the out-of-band shutdown authority;
- move queue-permit acquisition or alter accounting behavior;
- redesign event-bridge wake-up or add a new channel dependency;
- change server → worker → bridge error precedence;
- add an HTTP status field for submission depth;
- retain a misleading queue-depth alias unless the user identifies an external consumer requiring a transition period;
- refactor API bearer-token authentication or constant-time comparison;
- claim the LibVNCClient-owned password copy is scrubbed without exact source evidence;
- inspect freed memory in a test;
- optimize the framebuffer hot path;
- change framebuffer equality, revision, timestamp, ETag, or R13 `304` semantics;
- weaken R13 or any CI/security/release assertion;
- add `continue-on-error`, broad ignores, or unpinned dependencies;
- log command payloads, typed text, clipboard values, key values, coordinates, tokens, passwords, framebuffer bytes, or screenshots.

## 6. Validation and documentation requirements

The implementation must pass all available local checks and exact-SHA permanent CI and Release Gates. Unavailable local checks must be recorded as skipped with reasons, not labeled passed.

Permanent validation must include:

- formatting, strict Clippy, Rust tests, and rustdoc;
- Python tests and shell syntax checks;
- desktop image and native adapter suites;
- WorkerHandle input and text/clipboard E2E;
- authenticated HTTP E2E;
- Compose/persistence and unchanged R13;
- static/supply-chain gates;
- ASan, expanded TSan, and the accurately scoped Miri gate;
- Trivy, SBOM, and exact VEX enforcement.

Documentation updates must include:

- operator guide entries for shutdown and startup total budgets;
- release notes for startup-bound behavior change and metric rename;
- release-policy naming compatibility rule;
- exact pixel-layout contract;
- exact TSan/Miri coverage boundary;
- password-copy inventory and third-party residual;
- reproducible framebuffer measurement results;
- corrections to the prior hardening evidence without rewriting valid historical CI results.

## 7. Deferred follow-ups

The following are deliberately excluded from this pass and must be recorded so they are not forgotten:

1. direct event-bridge wake-up that removes polling-dependent clean-shutdown latency;
2. API bearer-token adoption of the shared secret abstraction;
3. framebuffer allocation/throughput optimization, conditional on the reproducible measurements;
4. any compatibility alias for the old metric, only if an external consumer is identified before implementation.

## 8. Completion boundary

This pass is complete only when:

- every required outcome is implemented and evidenced according to section 3;
- the companion TODO is truthfully completed;
- no preserved behavior or security boundary is weakened;
- CI and Release Gates pass on the same exact final repository-tip SHA;
- R13 passes unchanged on that SHA;
- completion evidence distinguishes project-owned secret zeroization from any verified third-party residual;
- the committed framebuffer measurement utility and results are reproducible;
- no completion claim relies on a previous SHA, canceled job, partial job, or self-referential commit hash.
