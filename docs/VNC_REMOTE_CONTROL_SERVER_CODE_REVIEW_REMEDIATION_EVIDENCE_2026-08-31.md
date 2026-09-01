# VNC Remote Control Server — Code Review Remediation Evidence

Date: 2026-08-31  
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`  
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`

## Status

This is the cumulative evidence document for the 2026-08-31 code-review remediation pass.

**R0-R12 are implemented and validated. R13-R15 remain open.** The current implementation candidate is PR #24 head `42b6bd11851821742e1bd6293d5b421b623fe754`. It passed regular CI run `33478155705` and Release Gates run `33478156031`. This is not yet final project sign-off because the completed remediation still has to be merged through the normal workflow and exact-`master` CI/Release Gates must pass before R13-R15 can close.

MCP implementation remains out of scope until this remediation pass is complete.

## R0 — Reviewed baseline and preserved constraints

- Starting reviewed `master` SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline regular CI: run `31265957251`, conclusion `success`.
- Baseline Release Gates: run `31265957258`, conclusion `success`.
- Raw VNC remains isolated on the internal Compose network.
- `/v1/*` remains bearer-authenticated.
- API/VNC credentials remain secret-file based and payload/secret logging remains prohibited.
- Worker/event channels and screenshot concurrency remain bounded.
- Sequence exhaustion, framebuffer/native sizing, poisoned authoritative state, and related invariants remain fail closed.
- No automatic retry was added for a side-effecting command whose outcome is unknown.
- No `continue-on-error`, scanner bypass, broad allowlist, or other release-gate weakening was introduced.

## R1 — Explicit mutation outcomes and reconciliation

R1 was implemented on `ralph/code-review-remediation-20260831-r1` and squash-merged through PR #20 as `992210538befddf7b683bc9539dc31d9ab991583`.

The final validated R1 branch head was `63c3a038fd530c1d4e855ae4d2ae0260ad63411d`:

- regular CI `33438892212`: **success**;
- Release Gates `33438892211`: **success**.

The resulting exact `master` SHA `992210538befddf7b683bc9539dc31d9ab991583` then passed push-triggered regular CI `33439766598` and Release Gates `33439766636`.

R1 established these invariants:

- command identity is allocated before queue admission and preserved through queueing, execution, completion, timeout, inspection, and abnormal termination;
- `CommandOutcomeRegistry` is process-local and bounded at 4096 records;
- terminal records are evicted deterministically as capacity is needed, while unresolved accepted work is not evicted merely to admit another command;
- retained records contain command ID, lifecycle state, retry-safety and sanitized failure metadata only, never typed text, clipboard content, credentials, screenshots, or other command payloads;
- authenticated `GET /v1/commands/{command_id}` exposes retained sanitized state;
- synchronous mutation success is HTTP 200 with `status: "succeeded"`;
- an accepted command whose caller times out is HTTP 504 with the same command ID, `outcome: "unknown"`, and `retry_safe: false`;
- the Python client raises a distinct unknown-outcome error and does not automatically retry the mutation;
- worker exit or panic turns accepted nonterminal commands into `aborted`.

Representative exact regression tests include:

- `pre_admission_rejection_and_post_admission_outcomes_are_distinct`;
- `command_status_is_authenticated_and_reports_sanitized_lifecycle`;
- `command_status_reports_pending_running_failed_and_rejected_states`;
- `timed_out_ticket_remains_inspectable_and_later_succeeds`;
- `timed_out_ticket_remains_inspectable_and_later_fails`;
- `timed_out_accepted_command_is_aborted_when_worker_terminates`;
- `timed_out_accepted_command_is_aborted_after_unexpected_worker_panic`;
- `command_id_exhaustion_is_shared_terminal_and_never_enqueues`;
- `terminal_records_are_evicted_but_pending_records_are_not`;
- `retained_records_never_store_payloads_and_terminate_nonterminal`.

## R2 — Scroll pointer-state uncertainty

R2 was implemented on `ralph/code-review-remediation-20260831-r2` and squash-merged through PR #21 as `d8e604fdfde7ea2fb655c62c3e821ead95371e36`.

The final validated R2 branch head was `34d4b98e77485e2ba7c08cd91d8a52ea52a36e89`:

- regular CI `33442995081`: **success**;
- Release Gates `33442995097`: **success**.

R2 removed the ignored second wheel-release result. A first release failure followed by a successful retry keeps pointer state known while preserving the original operation failure. If both release attempts fail, pointer state becomes uncertain, sanitized diagnostics are emitted, the affected VNC session is invalidated/dropped, local input tracking is abandoned only after the session can no longer be reused, and normal bounded reconnect establishes a replacement clean session.

Representative regression tests include:

- `scroll_release_failure_retry_success_keeps_pointer_state_known`;
- `scroll_double_release_failure_marks_pointer_state_uncertain_and_cleanup_recovers`;
- `scroll_double_release_failure_quarantines_session_and_reconnects_cleanly`;
- `release_all_reports_failed_pointer_release_without_silent_clear`;
- `disconnect_release_clears_buttons_and_keys`;
- existing ordinary click/button/key tracking and release tests.

No cleanup failure permits continued input on a session whose remote pointer state is uncertain.

## R3 — Native inbound clipboard callback failure propagation

R3 was implemented on PR #22 / `ralph/code-review-remediation-20260831-r3`. Its exact implementation candidate `76913758ddbf1180f5fe155ca3f7a37ef87dcb21` passed regular CI `33446396479` and Release Gates `33446396335`.

Before R3, a native `GotXCutText` callback could reject a newer clipboard value while `HandleRFBServerMessage()` returned success, allowing the poll boundary to miss the callback failure and risking continued exposure of an older cached clipboard as current.

R3 added explicit per-client callback status, clears that status before processing the next server message, and makes `vrc_client_poll()` return callback-specific non-success even when LibVNCClient's outer message handler reports success. It distinguishes oversize, allocation failure, invalid state, and revision exhaustion; Rust maps those statuses into typed errors.

The selected recovery policy is fail closed: callback failure disconnects the affected native session, invalidates the controller clipboard cache, drops the session, and uses the normal bounded reconnect path. Clipboard GET therefore reports unavailable rather than serving the old value as current. A later valid update on the replacement session becomes authoritative normally.

Structured diagnostics use only fixed categories and safe numeric metadata. Clipboard payloads are never logged.

Deterministic coverage includes `tests/native/vnc_shim_clipboard_callback_test.c`, `tests/test_native_contract.py`, `clipboard_callback_failures_map_to_distinct_domain_errors`, and `rejected_newer_clipboard_invalidates_stale_cache_and_reconnect_recovers`.

## R4 — Duration representability and startup validation

R4 was merged to `master` as `fae8f9b93ccaa3e5cff0c736a5439184d929516b` with its implementation already validated by regular CI `33450129789` and Release Gates `33450129793`.

R4 inventories and validates externally configured durations before worker/native startup. Controller-owned deadlines are bounded from 1 ms through 24 hours. Worker-owned deadlines use the same explicit bounded policy. Native connect/read timeouts remain whole-second fields, so configuration must be positive, no greater than 24 hours, and exactly representable as whole seconds; `1500 ms` is rejected rather than rounded, floored, or ceiled. The native poll interval is checked against the exact `u32` microsecond boundary using checked conversion.

No narrowing `as` conversion is used to make an invalid duration appear valid. Invalid environment-derived duration configuration fails before worker/native client spawn.

Representative boundary tests:

- `controller_duration_minimum_is_one_millisecond`;
- `controller_duration_maximum_is_explicit_and_checked`;
- `environment_derived_native_fractional_seconds_fail_before_startup`;
- `environment_derived_poll_interval_honors_u32_microsecond_boundary`;
- `native_timeouts_must_be_exact_whole_seconds_before_worker_spawn`;
- `poll_interval_respects_exact_native_microsecond_boundary`;
- `worker_deadline_durations_are_bounded`;
- configuration tests covering zero, representative valid values, maximums and one-above-maximum rejection.

Living operator/deployment documentation now states the units, range and whole-second native granularity explicitly.

## R5 — WebSocket inbound hardening

`/v1/events` remains a server-to-client application-data stream. The Axum WebSocket upgrade now sets both maximum inbound message size and maximum inbound frame size to **4096 bytes**. The bound is comfortably above the WebSocket control-frame maximum payload, so Ping/Pong/Close remain supported.

Client Text or Binary application data is rejected rather than interpreted as activity or commands:

- supported-size Text/Binary: close code `1003`, reason `client application data is not supported`;
- application data above 4096 bytes: close code `1009`, reason `client application message is too large`.

Rejected application data does not refresh heartbeat activity. Client permits are released after rejection/close. Authentication and initial snapshot behavior remain unchanged.

Representative tests:

- `client_ping_is_answered_and_pong_and_close_are_allowed`;
- `text_and_binary_application_data_are_rejected_with_1003`;
- `oversized_application_data_is_rejected_with_1009`;
- `websocket_inbound_limits_are_small_and_control_frame_safe`;
- `client_count_and_sustained_event_buffering_are_bounded`;
- authenticated WebSocket/router contract coverage and the real HTTP/Compose integration lane.

The same exact implementation candidate later passed regular CI `33478155705` and Release Gates `33478156031`.

## R6 — XFCE startup fails closed

The correctness-sensitive `xfconf-query ... || true` behavior was removed. `desktop/configure-xfce-session.sh` now uses a bounded retry loop, checks the XFCE process before each attempt, sets `/general/SaveOnExit=false`, reads the property back, requires the exact `false` value, and checks XFCE liveness again after successful readback. Startup exits nonzero if the setting cannot be established and verified within the bound or if XFCE exits during the process.

`desktop/xstartup` invokes the verifier before starting the deterministic test application. Its remaining `kill ... || true` is only the EXIT/TERM/INT cleanup race: an already-exited XFCE process is already in the desired terminal state, so failed cleanup signaling is not a readiness success path.

`tests/test_xfce_startup_policy.py` covers:

- `test_immediate_success`;
- `test_delayed_xfconf_availability`;
- `test_permanent_setter_failure_is_fatal`;
- `test_getter_failure_is_fatal`;
- `test_wrong_final_value_is_fatal`;
- `test_xfce_exit_while_waiting_is_fatal`;
- `test_xfce_exit_during_verified_read_is_fatal`.

Exact-head CI `33478155705` additionally passed shell syntax, desktop image smoke, native smoke, both WorkerHandle E2Es, authenticated HTTP E2E, controller/Compose/persistence smoke, and full Compose integration. Release Gates `33478156031` passed ShellCheck and Dockerfile/Compose validation.

## R7 — Worker shutdown and detach semantics

Worker shutdown is now explicitly outcome-oriented. `DesktopWorker::shutdown()` requests out-of-band shutdown and waits only within the supplied bound:

- confirmed thread exit joins the worker and reports clean `stopped` completion;
- timeout marks the shared snapshot `fatal_exit=true`, logs `outcome="timed_out_detached"`, deliberately detaches the join handle, and returns `DesktopError::Timeout`;
- a timeout never fabricates `ConnectionState::Stopped` or claims the thread terminated;
- `Drop` is bounded by `DROP_SHUTDOWN_TIMEOUT` and uses the same abnormal-detach semantics rather than an unbounded join;
- startup-timeout cleanup also uses one bounded deadline and explicitly reports timeout/detach;
- process shutdown shares one total worker-plus-event-bridge cleanup budget.

The out-of-band atomic shutdown flag is authoritative and does not depend on command-queue capacity. The startup queue nudge is explicitly best effort only; its failure cannot suppress the authoritative shutdown request.

Representative tests:

- `worker_commits_frame_accepts_commands_and_joins_shutdown`;
- `deterministic_saturated_queue_shutdown_still_completes`;
- `shutdown_does_not_require_command_queue_capacity`;
- `shutdown_timeout_is_enforced_when_worker_does_not_exit`;
- `drop_logs_or_records_worker_join_timeout_without_blocking`;
- `startup_timeout_cleanup_does_not_unbounded_join`;
- `process_shutdown_remains_bounded_after_worker_timeout`;
- `submit_rejects_after_shutdown_request_without_queue_mutation`;
- `successful_shutdown_release_clears_all_tracked_input_without_failure_log`.

The event bridge has analogous bounded shutdown, timeout and drop coverage (`event_bridge_shutdown_does_not_require_worker_sender_drop`, `event_bridge_timeout_is_observable`, `event_bridge_drop_is_bounded`, and `event_bridge_panic_is_returned_and_logged`).

## R8 — Authoritative worker failure classification

R8 centralizes domain/native error classification in `worker/helpers.rs` instead of assigning unrelated failures ad hoc as `Protocol`.

`classify_desktop_error()` preserves distinct public categories for:

- `request`;
- `capacity`;
- `unavailable`;
- `rate_limited`;
- `configuration`;
- `authentication`;
- `transport`;
- `timeout`;
- `protocol`;
- `native`.

`classify_native_error()` separately maps native configuration, transport, protocol-content and native/resource failures without matching human-readable error strings. Connected-message/reconnect paths use the authoritative helpers.

During the R9/R10 reconciliation audit, a public-contract drift was found: Rust could emit the four newly separated `request`, `capacity`, `unavailable`, and `rate_limited` categories while the Python `WorkerFailure` Literal and OpenAPI `WorkerFailure` enum still accepted only the older vocabulary. That was corrected before sign-off. `tests/test_worker_failure_contract.py` now pins the Python and OpenAPI vocabularies to the same ten-value set.

Representative tests include:

- `desktop_error_mapping_preserves_representative_failure_families`;
- `protocol_initialization_failure_is_protocol_regardless_of_message_text`;
- `protocol_initialization_failure_reconnects_as_protocol_failure`;
- `matching_native_frame_positive_control_reaches_connected`;
- `mismatched_native_frame_never_reaches_connected`;
- `tests/test_worker_failure_contract.py`.

Metrics, status snapshots and WebSocket snapshot events serialize the corrected bounded categories.

## R9 — Silent-failure and fallback audit

The changed and adjacent Rust, shell and Python surfaces were reviewed for discarded `Result`s, `.ok()` conversions, `unwrap_or*` fallbacks, broad error remapping, `|| true`, broad exception handling, timeout abandonment, side-effect retries and stale-cache fallbacks.

### Unjustified fallbacks removed

Two concrete operational-error erasures were found in `native-spike` and fixed:

1. `VRC_PROOF_HOLD_SECONDS` used `env::var(...).ok().unwrap_or(0)`, which made a non-Unicode environment value indistinguishable from a genuinely absent optional variable. Only `VarError::NotPresent` now selects the documented zero default; non-Unicode values and parse failures propagate as errors.
2. the framebuffer proof loop previously accepted every `display_info()` error as if the framebuffer were merely not ready and eventually relabeled it as a generic deadline. It now retries only `NativeError::FramebufferUnavailable`; every other native error propagates immediately.

The WebSocket session preparation path was also checked for stale/availability masking. `ClipboardUnavailable` is intentionally represented as `clipboard_revision: null` in the initial snapshot, while every other clipboard error is propagated through the typed API error mapping rather than discarded.

### Intentionally non-authoritative ignored results

The remaining ignored results are constrained to cases where failure cannot restore normal service, claim successful mutation, or make stale data authoritative:

- WebSocket close-frame sends after lag, event-source shutdown, unsupported/oversized client data, heartbeat timeout, sequence exhaustion, or invalid timestamp: the connection has already entered a terminal branch and the handler immediately breaks/drops the socket whether close-frame delivery succeeds or the peer has already disappeared. Failure therefore cannot allow continued application traffic or imply that the peer received the close. The initiating operational condition is already represented by fixed logs/metrics or the terminal event-hub invariant.
- `broadcast::Sender::send` for event publication: failure means there are no active receivers. Worker state remains authoritative and a later subscriber receives a fresh initial snapshot; no mutation result or current state is fabricated.
- worker/event-bridge exit-signal `try_send` calls in `Drop`: full means a terminal notification is already pending; disconnected means no waiter remains. Drop cannot usefully recover either case.
- screenshot encoder completion send: failure means the caller already timed out/dropped its receiver. The encoder thread still owns the concurrency permit through completion, so abandoning an undeliverable result cannot create extra capacity or report success to the caller.
- the startup shutdown-envelope `try_send`: the atomic out-of-band shutdown flag is explicitly authoritative; the queue nudge is only a best-effort wakeup and is documented as such.
- Python `ProcessLookupError` and the XFCE trap's `kill ... || true`: both are cleanup races where “process already gone” is the desired terminal condition.
- checked-arithmetic `.ok()` chains convert representability failure into an explicit typed domain error; they do not turn an operational failure into success.
- request-header UTF-8 `.ok()` handling is validation/fallback of untrusted optional header text, not suppression of a backend operation. An invalid optional conditional/request ID value is treated according to the documented request-validation policy rather than as successful backend work.

No automatic retry was added around a side-effecting remote operation whose outcome is uncertain. The scroll double-release logic is deliberate state recovery and quarantines the session when recovery itself fails.

No stale clipboard fallback remains after a rejected newer update.

## R10 — Public/client/operator documentation reconciliation

Living documentation now reflects the remediated behavior:

- command lifecycle, status lookup, unknown post-admission outcome and `retry_safe=false` policy;
- bounded command outcome retention and the rule against blind mutation retry;
- Python client timeout/status handling;
- clipboard invalidation/unavailable behavior after rejected inbound updates;
- duration units, 1 ms/24 h bounds where applicable and whole-second native connect/read granularity;
- the 4096-byte WebSocket inbound frame/message policy, 1003/1009 application-data rejection and supported control frames;
- clean worker stop versus `timed_out_detached` semantics and the total process cleanup budget;
- corrected worker failure taxonomy in WebSocket docs, OpenAPI and Python models.

`docs/OPERATOR_GUIDE.md`, `deploy/README.md`, `docs/WEBSOCKET_EVENTS.md`, `docs/openapi.json`, and the Python public models were reconciled. Documentation references to MCP describe it as deferred/out of scope; none claims an MCP server already exists.

## R11 — Quality gates

The ChatGPT sandbox used for this remediation does not provide the complete pinned Rust/lint/container environment required by the repository. The TODO explicitly permits environment-specific proof to be deferred to GitHub Actions rather than weakening a check.

The focused Python client/failure-taxonomy contract was exercised locally during reconciliation (14 tests passed and the updated OpenAPI parsed successfully). The authoritative complete proof is exact-head GitHub Actions on PR #24 implementation head `42b6bd11851821742e1bd6293d5b421b623fe754`.

Regular CI run `33478155705`: **success**.

Its repository-quality job passed:

- `cargo fmt --all --check`;
- Clippy with warnings denied;
- full Rust workspace tests (including 177 controller tests plus adapter/core tests);
- rustdoc with warnings denied;
- first-party Python compilation/install;
- Ruff;
- Pylint;
- mypy;
- Python/workflow contract tests;
- repository shell syntax;
- CI evidence generation/upload.

Its secured desktop/native job passed:

- desktop image smoke;
- native adapter smoke;
- WorkerHandle TigerVNC input E2E;
- WorkerHandle TigerVNC text/clipboard E2E;
- authenticated HTTP TigerVNC E2E;
- controller image / Compose / persistence smoke;
- full R13 Compose integration and E2E validation.

Release Gates run `33478156031`: **success**.

It passed:

- full-history secret scanning;
- ShellCheck and GitHub Actions workflow linting;
- Dockerfile BuildKit validation;
- Compose configuration validation;
- advisory/license/source/duplicate policy enforcement;
- auditable release binary inspection;
- adapter AddressSanitizer;
- controller and core ThreadSanitizer;
- core Miri;
- exact-candidate release image builds;
- vulnerability inventories;
- CycloneDX SBOM generation;
- exact CRITICAL VEX enforcement.

No check was disabled or made non-blocking to obtain these results.

## R12 — Security/VEX timing

The old remediation-planning warning referenced determinations expiring on 2026-09-04. The authoritative security state has since been re-reviewed:

- `SECURITY.md` records review on **2026-08-31** and expiration on **2026-09-30**;
- `security/trivy-critical-vex.json` records `reviewed_at: 2026-08-31` and `expires_at: 2026-09-30`;
- Release Gates `33478156031` passed exact CRITICAL VEX enforcement against the candidate images.

Therefore no VEX bypass or emergency renewal is needed for the current finalization window. The gate remains fail closed for expiration, package-version changes, stale tuples, or unmatched CRITICAL findings.

## Current exact implementation-candidate validation

PR #24 implementation head before this evidence-only closeout commit:

`42b6bd11851821742e1bd6293d5b421b623fe754`

- Regular CI `33478155705`: **success**.
- Release Gates `33478156031`: **success**.

This pair is important because it validates the implementation itself before documentary closeout changes. The evidence-only head produced by this document update must still pass its own exact-head checks before PR #24 is merged.

## Explicit safety statements

- Accepted command timeouts preserve command identity and report unknown, non-retry-safe outcomes.
- No side-effecting command is automatically retried after an unknown outcome.
- Scroll double-release failure cannot leave a tainted session in normal service.
- A rejected newer clipboard cannot leave the previous value authoritative.
- Duration values that cannot be represented by their downstream API are rejected before startup.
- WebSocket client application data is bounded and explicitly rejected.
- XFCE readiness cannot silently continue when `SaveOnExit=false` was not verified.
- Worker timeout/detach is distinct from confirmed orderly stop.
- Worker failure classification is centralized and public schemas agree on its vocabulary.
- The changed/adjacent silent-fallback audit is complete through R9; intentionally ignored results are limited to documented terminal/cleanup/notification-only invariants.
- No secret/payload logging was added.
- No release-critical gate was weakened.
- MCP implementation remains a separate next phase.

## Remaining remediation

R13-R15 remain open:

1. validate the evidence-only PR head;
2. merge the completed remediation through the project's normal workflow;
3. record and validate the exact resulting `master` SHA with regular CI and Release Gates;
4. perform the final R0-R14 checkbox re-review and update the TODO/sign-off without claiming completion early.

Until those exact-`master` steps are complete, this document is cumulative evidence rather than final sign-off.