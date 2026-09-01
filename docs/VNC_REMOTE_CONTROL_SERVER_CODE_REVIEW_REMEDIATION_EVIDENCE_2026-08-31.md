# VNC Remote Control Server — Code Review Remediation Evidence

Date: 2026-08-31  
Final implementation validation date: 2026-09-01  
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`  
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`

## Final status

The 2026-08-31 code-review remediation is complete.

- Starting reviewed `master` SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline regular CI: `31265957251` — **success**.
- Baseline Release Gates: `31265957258` — **success**.
- Final implementation `master` SHA: `1cb79d34f0023fc5da429ff3b60c71085224fa4e`.
- Final regular CI: `33516207959` — **success**.
- Final Release Gates: `33516208137` — **success**.

The final implementation SHA is the code-bearing SHA proven by the exact-`master` gates above. This evidence/TODO closeout is documentation-only and does not substitute its later administrative commit SHA for the validated implementation SHA.

MCP implementation remains a separate next phase and was intentionally out of scope for this remediation pass.

## R0 — Reviewed baseline and preserved safety constraints

The remediation preserved the baseline security and bounded-resource constraints while fixing the reviewed defects:

- raw VNC remains isolated on the internal Compose network;
- `/v1/*` remains bearer-authenticated;
- API and VNC credentials remain secret-file based;
- payload/secret logging remains prohibited;
- worker/event channels and screenshot concurrency remain bounded;
- sequence exhaustion, native/framebuffer sizing, and poisoned-authoritative-state paths remain fail closed;
- no automatic retry was added for a side-effecting command with an unknown outcome;
- no release-critical gate was made optional, non-blocking, or `continue-on-error`.

## R1 — Explicit mutation outcomes and reconciliation

R1 was implemented on `ralph/code-review-remediation-20260831-r1` and squash-merged through PR #20 as `992210538befddf7b683bc9539dc31d9ab991583`.

The final validated R1 branch head was `63c3a038fd530c1d4e855ae4d2ae0260ad63411d`:

- regular CI `33438892212`: **success**;
- Release Gates `33438892211`: **success**.

The resulting exact `master` SHA `992210538befddf7b683bc9539dc31d9ab991583` then passed push-triggered regular CI `33439766598` and Release Gates `33439766636`.

### Command lifecycle and status policy

R1 established these invariants:

- command identity is allocated before queue admission and preserved through queueing, execution, completion, timeout, status lookup, diagnostics, and abnormal worker termination;
- `CommandOutcomeRegistry` is process-local and bounded at **4096 records**;
- unresolved accepted commands are not evicted merely to admit another status record;
- terminal records are evicted deterministically when capacity is required;
- retention is capacity/terminal-eviction based rather than relying on an unsafe implicit timeout that could discard unresolved accepted work;
- records contain command ID, lifecycle/retry-safety state, and sanitized failure metadata only — never typed text, clipboard values, credentials, screenshots, or other command payloads;
- authenticated `GET /v1/commands/{command_id}` exposes the retained sanitized state;
- synchronous mutation success returns HTTP 200 with terminal `status: "succeeded"` semantics;
- a caller timeout after admission returns HTTP 504 with the same command ID, `outcome: "unknown"`, and `retry_safe: false`;
- queue-full/disconnected/validation failures that occur before admission remain distinct known failures;
- the Python client represents the unknown-outcome case distinctly and never automatically retries that mutation;
- worker exit or panic turns accepted nonterminal commands into `aborted`.

Representative R1 regression tests include:

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

R2 removed the ignored second wheel-release result. A first release failure followed by a successful retry keeps pointer state known while preserving the original operation failure. If both release attempts fail, pointer state becomes uncertain, sanitized diagnostics are emitted, the affected VNC session is tainted/dropped, and subsequent input is not executed on that session. Normal bounded reconnect establishes a replacement session with clean tracked pointer/key state.

Representative R2 regression tests include:

- `scroll_release_failure_retry_success_keeps_pointer_state_known`;
- `scroll_double_release_failure_marks_pointer_state_uncertain_and_cleanup_recovers`;
- `scroll_double_release_failure_quarantines_session_and_reconnects_cleanly`;
- `release_all_reports_failed_pointer_release_without_silent_clear`;
- `disconnect_release_clears_buttons_and_keys`;
- existing ordinary click/button/key tracking and release tests.

No cleanup failure permits continued input on a session whose remote pointer state is uncertain.

## R3 — Native inbound clipboard callback failure propagation

R3 was implemented on PR #22 / `ralph/code-review-remediation-20260831-r3`. Its exact implementation candidate `76913758ddbf1180f5fe155ca3f7a37ef87dcb21` passed regular CI `33446396479` and Release Gates `33446396335`.

R3 added explicit per-client native callback failure status, clears the status before each relevant message-processing boundary, and makes `vrc_client_poll()` return callback-specific non-success even when LibVNCClient's outer message handler reports success. The native/Rust boundary distinguishes oversize clipboard rejection, allocation/resource failure, invalid state, and revision exhaustion rather than collapsing them into generic success/protocol behavior.

The chosen recovery policy is fail closed: a callback failure disconnects the affected native session, clears the controller clipboard cache, drops the session, and uses the normal bounded reconnect path. The clipboard API therefore reports unavailable rather than serving an older value as current. A later valid update on the replacement session becomes authoritative normally.

Structured diagnostics use fixed categories and safe numeric metadata only. Clipboard payloads are never logged.

Representative R3 tests include:

- `tests/native/vnc_shim_clipboard_callback_test.c`;
- `tests/test_native_contract.py`;
- `clipboard_callback_failures_map_to_distinct_domain_errors`;
- `rejected_newer_clipboard_invalidates_stale_cache_and_reconnect_recovers`;
- sanitizer/native coverage exercised by Release Gates.

## R4 — Duration representability and startup validation

R4 was merged to `master` as `fae8f9b93ccaa3e5cff0c736a5439184d929516b`; regular CI `33450129789` and Release Gates `33450129793` passed.

R4 inventories and validates externally configured durations before worker/native startup. Controller-owned deadlines are bounded from 1 ms through 24 hours. Worker-owned deadlines use explicit checked bounds. Native connect/read timeouts remain whole-second fields, so configuration must be positive, no greater than 24 hours, and exactly representable as whole seconds. `1500ms` is rejected rather than rounded, floored, or ceiled. Native poll conversion is checked against the exact `u32` microsecond boundary.

No narrowing `as` conversion is used to make an invalid configured duration appear valid. Invalid environment-derived duration configuration fails before worker/native client spawn.

Representative R4 boundary tests include:

- `controller_duration_minimum_is_one_millisecond`;
- `controller_duration_maximum_is_explicit_and_checked`;
- `environment_derived_native_fractional_seconds_fail_before_startup`;
- `environment_derived_poll_interval_honors_u32_microsecond_boundary`;
- `native_timeouts_must_be_exact_whole_seconds_before_worker_spawn`;
- `poll_interval_respects_exact_native_microsecond_boundary`;
- `worker_deadline_durations_are_bounded`;
- configuration coverage for zero, representative valid values, maximums, and one-above-maximum rejection.

Living deployment/operator documentation records units, bounds, and whole-second native granularity.

## R5 — WebSocket inbound hardening

`/v1/events` remains a server-to-client application-data stream. The Axum WebSocket upgrade sets both maximum inbound message size and maximum inbound frame size to **4096 bytes**. This is comfortably above WebSocket control-frame payload requirements, so Ping/Pong/Close remain supported.

Client application data is explicitly rejected:

- supported-size Text/Binary: close code `1003`;
- application data above 4096 bytes: close code `1009`.

Rejected application data does not refresh heartbeat activity. Client permits are released after rejection/close. Authentication and initial snapshot behavior remain unchanged.

Representative R5 tests include:

- `client_ping_is_answered_and_pong_and_close_are_allowed`;
- `text_and_binary_application_data_are_rejected_with_1003`;
- `oversized_application_data_is_rejected_with_1009`;
- `websocket_inbound_limits_are_small_and_control_frame_safe`;
- `client_count_and_sustained_event_buffering_are_bounded`;
- authenticated WebSocket/router and real HTTP/Compose integration coverage.

## R6 — XFCE startup fails closed

The correctness-sensitive `xfconf-query ... || true` behavior was removed. `desktop/configure-xfce-session.sh` uses a bounded retry loop, checks XFCE liveness, sets `/general/SaveOnExit=false`, reads the property back, requires the exact `false` value, and fails nonzero if the state cannot be established/verified within the bound or XFCE exits.

`desktop/xstartup` invokes the verifier before the deterministic test application. Its remaining cleanup `kill ... || true` is an idempotent terminal cleanup race: an already-exited process is already in the desired terminal state and this ignore cannot make readiness succeed.

Representative R6 tests in `tests/test_xfce_startup_policy.py` include:

- `test_immediate_success`;
- `test_delayed_xfconf_availability`;
- `test_permanent_setter_failure_is_fatal`;
- `test_getter_failure_is_fatal`;
- `test_wrong_final_value_is_fatal`;
- `test_xfce_exit_while_waiting_is_fatal`;
- `test_xfce_exit_during_verified_read_is_fatal`.

Final implementation CI `33516207959` also passed shell syntax plus secured desktop/native/WorkerHandle/HTTP/Compose integration. Final Release Gates `33516208137` passed ShellCheck and Dockerfile/Compose validation.

## R7 — Worker shutdown and detach semantics

Worker shutdown is explicitly outcome-oriented:

- confirmed thread exit joins the worker and reports clean `stopped` completion;
- timeout marks the shared snapshot `fatal_exit=true`, records `outcome="timed_out_detached"`, deliberately detaches the join handle, and returns a timeout;
- timeout never fabricates `ConnectionState::Stopped` or claims thread termination;
- `Drop` is bounded and never performs an unbounded join;
- startup-timeout cleanup uses one bounded deadline and reports timeout/detach explicitly;
- process shutdown shares a bounded worker/event-bridge cleanup budget;
- the out-of-band atomic shutdown flag is authoritative and does not depend on command-queue capacity.

Representative R7 tests include:

- `worker_commits_frame_accepts_commands_and_joins_shutdown`;
- `deterministic_saturated_queue_shutdown_still_completes`;
- `shutdown_does_not_require_command_queue_capacity`;
- `shutdown_timeout_is_enforced_when_worker_does_not_exit`;
- `drop_logs_or_records_worker_join_timeout_without_blocking`;
- `startup_timeout_cleanup_does_not_unbounded_join`;
- `process_shutdown_remains_bounded_after_worker_timeout`;
- `submit_rejects_after_shutdown_request_without_queue_mutation`;
- `successful_shutdown_release_clears_all_tracked_input_without_failure_log`;
- event-bridge timeout/drop/panic coverage including `event_bridge_shutdown_does_not_require_worker_sender_drop`, `event_bridge_timeout_is_observable`, and `event_bridge_drop_is_bounded`.

## R8 — Authoritative worker failure classification

R8 centralizes domain/native error classification rather than assigning unrelated failures ad hoc as `Protocol`.

The public worker failure taxonomy is exactly:

- `authentication`;
- `configuration`;
- `request`;
- `capacity`;
- `unavailable`;
- `rate_limited`;
- `transport`;
- `timeout`;
- `protocol`;
- `native`.

`classify_desktop_error()` and `classify_native_error()` are authoritative mappings and connected-message/reconnect paths use them. During reconciliation, Python/OpenAPI vocabulary drift was found and corrected so Rust, Python, and OpenAPI all accept the same ten categories. `tests/test_worker_failure_contract.py` pins that parity.

Representative R8 tests include:

- `desktop_error_mapping_preserves_representative_failure_families`;
- `protocol_initialization_failure_is_protocol_regardless_of_message_text`;
- `protocol_initialization_failure_reconnects_as_protocol_failure`;
- `matching_native_frame_positive_control_reaches_connected`;
- `mismatched_native_frame_never_reaches_connected`;
- `tests/test_worker_failure_contract.py`.

## R9 — Silent-failure and fallback audit

Changed and adjacent Rust, shell, and Python surfaces were reviewed for discarded `Result`s, `.ok()` conversions, `unwrap_or*` runtime fallbacks, broad error remapping, `|| true`, broad exception handlers, timeout abandonment, retries around side-effecting operations, and stale-cache fallback behavior.

### Unjustified fallbacks removed

The audit removed or corrected these correctness-sensitive fallbacks:

1. clipboard session preparation now maps only the explicit `ClipboardUnavailable` state to an absent revision; every other clipboard error propagates;
2. native-spike environment handling defaults only when the variable is genuinely absent; non-Unicode values and parse errors propagate;
3. native-spike display probing retries only `FramebufferUnavailable`; every other display error propagates immediately;
4. XFCE `SaveOnExit` correctness handling no longer uses `|| true`;
5. shutdown duration logging no longer fabricates `u64::MAX` on overflow;
6. R8 Python/OpenAPI failure-taxonomy drift was corrected rather than silently accepting unknown categories.

### Intentionally ignored/non-authoritative results

Remaining ignored results were reviewed and retained only where failure cannot create a false mutation success, keep a poisoned session in service, or make stale state authoritative:

- terminal WebSocket close-frame sends: the session is already on a terminal branch and is dropped whether the peer receives the close frame or has already disappeared;
- event broadcast send with zero receivers: worker state remains authoritative and a later subscriber receives a fresh initial snapshot;
- `Drop`/cleanup `try_send` terminal notifications: full means a terminal notification is already pending; disconnected means no waiter remains;
- screenshot encoder completion send after the receiver timed out/dropped: no response can be fabricated because the receiver is gone;
- startup shutdown-envelope nudge: the atomic shutdown flag is authoritative, so queue notification is only a best-effort wakeup;
- process cleanup kill races such as `ProcessLookupError` / shell `kill ... || true`: an already-dead target is the desired terminal condition;
- optional untrusted-header `to_str().ok()` conversion: invalid optional header text is treated as invalid/absent metadata, not as authorization or mutation success;
- pointer release retry is a tracked recovery attempt; a second failure taints the session and reconnects rather than silently clearing state;
- connection-lifecycle reconnect retries do not replay an unknown side-effecting mutation;
- stale framebuffer/clipboard values are never served as current after invalidation.

No side-effecting command is automatically retried after an unknown outcome.

## R10 — Public/client/operator documentation reconciliation

Living documentation was reconciled with the implementation, including:

- command lifecycle/status lookup and unknown post-admission timeout semantics;
- `retry_safe=false` and the prohibition on blind mutation retry;
- bounded command-status retention behavior;
- Python client timeout/status handling;
- clipboard invalidation/unavailable behavior;
- duration units/ranges/granularity;
- WebSocket inbound 4096-byte bounds and 1003/1009 rejection behavior;
- clean worker stop versus timeout/detach semantics;
- corrected worker failure taxonomy.

Relevant living documents include `docs/OPERATOR_GUIDE.md`, `deploy/README.md`, `docs/WEBSOCKET_EVENTS.md`, `docs/openapi.json`, and the Python public models. Documentation does not claim that the deferred MCP server already exists.

## R11 — Quality gates

The ChatGPT sandbox did not provide the complete pinned Rust/lint/container environment. The remediation therefore used focused locally available checks where possible and the repository's blocking GitHub Actions jobs as the authoritative environment-specific proof. No gate was weakened because it was inconvenient locally.

Focused Python/OpenAPI contract checks were exercised during reconciliation, including 14 Python tests and successful OpenAPI parsing.

The final exact implementation regular CI `33516207959` passed:

- `cargo fmt --all --check`;
- Clippy with warnings denied;
- full Rust workspace tests;
- rustdoc with warnings denied;
- first-party Python compilation/install;
- Ruff;
- Pylint;
- mypy;
- Python/workflow contract tests;
- repository shell syntax;
- CI evidence generation/upload;
- desktop image smoke;
- native adapter smoke;
- WorkerHandle TigerVNC input E2E;
- WorkerHandle TigerVNC text/clipboard E2E;
- authenticated HTTP TigerVNC E2E;
- controller image / Compose / persistence smoke;
- full R13 Compose integration and E2E validation.

The final exact implementation Release Gates `33516208137` passed:

- full-history secret scanning;
- ShellCheck;
- GitHub Actions workflow linting;
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

No check was disabled, bypassed, or made non-blocking to obtain these results.

## R12 — Security/VEX timing

Final implementation validation occurred on 2026-09-01, before the historical 2026-09-04 re-review trigger in the planning checklist. In addition, the authoritative VEX state had already been refreshed:

- `SECURITY.md` records review on 2026-08-31 and expiration on 2026-09-30;
- `security/trivy-critical-vex.json` records `reviewed_at: 2026-08-31` and `expires_at: 2026-09-30`;
- tracked security follow-up remains issue #7;
- final Release Gates `33516208137` passed exact CRITICAL VEX enforcement against the final implementation candidate images.

No VEX bypass or broad allowlist was introduced. The release gate remains fail closed for expiration, package-version changes, stale tuples, and unmatched CRITICAL findings.

## R13 — Final exact-SHA validation and R13 restart correction

The first R5-R12 implementation merge produced exact `master` SHA `3a929c3fe95277886011e8fcf582cf1b21e10106`.

- Release Gates `33481345385`: **success**.
- Regular CI `33481345296`: **failure**, isolated to `Run R13 Compose integration and E2E validation` in job `99771441201`.

The failure was not ignored or rerun blindly. Diagnostics showed that the third intentional desktop stop/start cycle left the desktop container exited with code 143/SIGTERM. The R13 harness used `docker compose start desktop`, then its `docker compose ps -q` lookup hid stopped containers and degraded the actual failure into a generic 120-second `last=missing` health timeout while the controller could no longer resolve `desktop`.

PR #26 fixed the harness without weakening product assertions:

- restart reconciliation now uses `docker compose up -d --no-deps desktop` to restore configured desired state;
- stopped containers can be inspected explicitly;
- terminal `exited`/`dead` or unhealthy states fail immediately with exit code, OOM flag, Docker error, and health state;
- failure diagnostics include stopped-container state;
- no retry loop, assertion weakening, or deadline increase was added.

Exact PR #26 head `749c938770426991fabadc8324bc6433c57342b8` passed:

- regular CI `33511318943`: **success**, including R13;
- Release Gates `33511318954`: **success**.

PR #26 was squash-merged. The resulting final implementation `master` SHA is:

`1cb79d34f0023fc5da429ff3b60c71085224fa4e`

Exact push-triggered final validation:

- regular CI `33516207959`: **success**, including `Run R13 Compose integration and E2E validation`;
- Release Gates `33516208137`: **success**.

Release-critical jobs remained blocking. Full-history secret scanning, dependency/source policy, ASan, TSan, Miri, image vulnerability inventories, CycloneDX SBOM generation, and exact CRITICAL VEX enforcement all remained enabled and green.

## R14 — Evidence completeness

This document records every R14-required evidence class:

- starting and final implementation SHA;
- final regular CI and Release Gates IDs/conclusions;
- R1 command lifecycle, timeout body/retry policy, bounded outcome retention, and representative tests;
- R2 pointer uncertainty/recovery policy and tests;
- R3 native clipboard callback propagation/recovery policy and tests;
- R4 duration granularity/range policy and boundary tests;
- R5 inbound WebSocket limits, rejected frame types, and tests;
- R6 fail-closed XFCE behavior and tests;
- R7 orderly versus timeout/detached shutdown semantics and tests;
- R8 authoritative worker failure mapping and tests;
- R9 silent-fallback audit and rationale for intentionally ignored terminal/cleanup/notification-only results;
- explicit safety statements below;
- deliberate scope/maintenance items below.

## Explicit safety statements

- Accepted command timeouts preserve command identity and report unknown, non-retry-safe outcomes.
- No side-effecting command is automatically retried after an unknown outcome.
- Scroll double-release failure cannot leave a tainted session in normal service.
- A rejected newer clipboard cannot leave the previous value authoritative.
- Duration values that cannot be represented by their downstream API are rejected before startup.
- WebSocket client application data is bounded and explicitly rejected.
- XFCE readiness cannot silently continue when `SaveOnExit=false` was not verified.
- Worker timeout/detach is distinct from confirmed orderly stop.
- Worker failure classification is centralized and Rust/Python/OpenAPI agree on its vocabulary.
- The changed/adjacent silent-fallback audit is complete; intentionally ignored results are limited to documented terminal/cleanup/notification-only invariants.
- No secret or command/clipboard payload logging was added.
- No release-critical gate was weakened.

## Deliberate scope and ongoing tracked maintenance

No reviewed remediation defect is deliberately left incomplete.

MCP implementation is intentionally a separate next phase, as specified before remediation began. Deferring MCP is not a workaround for an unresolved mutation-safety defect; R1 first established the command-identity/unknown-outcome semantics required for a safer autonomous client.

The repository's CRITICAL VEX maintenance remains tracked under issue #7. Current determinations were reviewed on 2026-08-31, expire on 2026-09-30, and passed exact enforcement on the final implementation Release Gates run.

## R15 — Final sign-off

Every R0-R14 checklist item was re-reviewed against implementation, tests, documentation, and exact-SHA validation rather than inferred from commit messages. The companion TODO contains no remaining unchecked remediation item.

```text
2026-08-31 code-review remediation complete on implementation SHA 1cb79d34f0023fc5da429ff3b60c71085224fa4e.
Final implementation validation completed 2026-09-01.
Regular CI run 33516207959: success.
Release Gates run 33516208137: success.
Accepted command timeouts preserve command identity and report unknown, non-retry-safe outcomes.
Scroll and clipboard failure paths no longer silently preserve uncertain/stale authoritative state.
Configuration, WebSocket, XFCE startup, worker shutdown, and failure classification hardening are complete.
The changed/adjacent silent-fallback audit is complete.
No release-critical gate was weakened.
MCP implementation remains a separate next phase.
```
