# VNC Remote Control Server — Code Review Remediation Evidence

Date: 2026-08-31  
Companion spec: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_SPEC_2026-08-31.md`  
Companion TODO: `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_TODO_2026-08-31.md`

## Status

This is the cumulative evidence document for the 2026-08-31 code-review remediation pass.

**R0, R1, R2, and R3 are implemented and validated. R4-R15 remain open.** This document is therefore not final sign-off for the complete remediation pass. MCP implementation remains out of scope until every applicable remediation item is complete and the exact final `master` SHA passes regular CI and Release Gates.

## R0 — Reviewed baseline and preserved constraints

- Starting reviewed `master` SHA: `62fd4cd6c15ea705227fe943eddbaaca26fe4345`.
- Baseline regular CI: run `31265957251`, conclusion `success`.
- Baseline Release Gates: run `31265957258`, conclusion `success`.
- The remediation work remains separate from the future MCP phase.
- Raw VNC isolation, bearer authentication on `/v1/*`, secret-file credentials, payload/secret redaction, bounded queues/concurrency, and fail-closed sequence/native-size behavior remain preserved.
- No automatic retry was added for a side-effecting command whose outcome is unknown.
- No `continue-on-error`, scanner bypass, broad allowlist, or other release-gate weakening was introduced.

## R1 — Explicit mutation outcomes and reconciliation

R1 was implemented on `ralph/code-review-remediation-20260831-r1` and squash-merged through PR #20 as `992210538befddf7b683bc9539dc31d9ab991583`.

The final validated R1 branch head was `63c3a038fd530c1d4e855ae4d2ae0260ad63411d`:

- regular CI `33438892212`: **success**;
- Release Gates `33438892211`: **success**.

The resulting exact `master` SHA `992210538befddf7b683bc9539dc31d9ab991583` then passed push-triggered regular CI `33439766598` and Release Gates `33439766636`.

R1 established these invariants:

- a stable command ID is allocated before queue admission;
- pre-admission rejection is distinct from an accepted command whose caller stopped waiting;
- `CommandOutcomeRegistry` is process-local and bounded at 4096 records;
- terminal records are evicted deterministically as capacity is needed, while unresolved accepted commands are never evicted merely to admit another mutation;
- the registry stores only command ID, lifecycle state, and optional sanitized static failure category, never command payloads or credentials;
- authenticated `GET /v1/commands/{command_id}` exposes retained sanitized state;
- synchronous mutation success is HTTP 200 with `status: "succeeded"`;
- accepted wait timeout is HTTP 504 with the same command ID, `outcome: "unknown"`, and `retry_safe: false`;
- the Python client raises a distinct unknown-outcome error and never automatically retries the mutation;
- worker exit/panic turns accepted nonterminal commands into `aborted` rather than leaving them indefinitely pending.

R1 tests cover success, known failure, validation rejection, queue-full rejection, worker-unavailable rejection, timeout then success, timeout then failure, timeout then worker abort, stable ID continuity, ID exhaustion, bounded retention, status lookup, and payload/secret non-retention.

## R2 — Scroll pointer-state uncertainty

R2 was implemented on `ralph/code-review-remediation-20260831-r2` and squash-merged through PR #21 as `d8e604fdfde7ea2fb655c62c3e821ead95371e36`.

The final validated R2 branch head was `34d4b98e77485e2ba7c08cd91d8a52ea52a36e89`:

- regular CI `33442995081`: **success**;
- Release Gates `33442995097`: **success**.

R2 removed the ignored second wheel-release result. A first release failure followed by a successful retry keeps pointer state known while preserving the original operation error. If both release attempts fail, the worker marks pointer state uncertain, emits sanitized diagnostics, invalidates and drops the affected VNC session, abandons local pointer/key tracking only after that session can no longer be reused, and schedules the normal bounded reconnect path.

The replacement session starts with a clean button mask and key set. Regression coverage includes normal wheel press/release, first-release failure with successful retry, double-release failure, cleanup-release failure, prevention of later input on the tainted session, reconnect, and clean post-reconnect pointer/key state.

No best-effort cleanup failure permits continued use of the tainted session, and no input payload or credential material is logged.

## R3 — Native inbound clipboard callback failure propagation

R3 is implemented on PR #22 / `ralph/code-review-remediation-20260831-r3` from R2 `master` SHA `d8e604fdfde7ea2fb655c62c3e821ead95371e36`.

### Unsafe behavior removed

Before R3, the native `GotXCutText` callback could reject a newer clipboard value while `HandleRFBServerMessage()` still returned success. The callback result was not an authoritative result of `vrc_client_poll()`, so the Rust worker could continue as though the message had been processed successfully and a previously cached clipboard could remain observable as the current value.

R3 makes callback failure part of the native per-client state and poll contract.

### Machine-readable callback status

The native client now stores explicit callback status plus bounded safe metadata. Callback state is cleared immediately before processing the next server message. After `HandleRFBServerMessage()` returns, `vrc_client_poll()` checks callback status; a callback failure therefore produces a non-success poll even when LibVNCClient's message handler itself returned success.

The affected native client is marked disconnected on callback failure. A later poll on a deliberately re-established test client first clears the prior callback status, proving an old callback error cannot silently poison a later valid message.

### Preserved failure classes

The C shim and Rust adapter distinguish the following inbound clipboard failures instead of collapsing them into generic success:

- clipboard too large, including safe byte-count / configured-maximum metadata;
- clipboard allocation failure;
- invalid clipboard/native update state;
- clipboard revision exhaustion.

Rust exposes corresponding typed `NativeError` variants. Allocation, invalid-state, revision-exhaustion, and other native invariant/resource failures remain fail-closed and are classified as native failures rather than being silently treated as protocol success.

### Stale clipboard invalidation and recovery policy

The chosen R3 policy does **not** keep a VNC session alive after a native callback failure. Therefore no additional long-lived “stale but session still active” API state is required.

On a callback failure:

1. the native shim releases any previous native clipboard buffer before recording the rejected update;
2. `vrc_client_poll()` returns the callback-specific failure and marks the native client disconnected;
3. the worker records a sanitized failure category;
4. `LoopState::invalidate()` clears the controller-side cached `ClipboardSnapshot`;
5. the affected session is dropped;
6. the normal bounded reconnect scheduler establishes a replacement session.

Consequently `clipboard_snapshot()` / clipboard GET behavior returns `ClipboardUnavailable` after the failed newer update instead of serving the older value as current.

The same stale-cache rule also applies when a newly observed clipboard payload is rejected at the Rust/controller boundary for invalid payload constraints or invalid UTF-8: the previous cached snapshot is removed before the protocol error is reported.

A later valid clipboard on the replacement session becomes authoritative normally.

### Observability and secrecy

R3 adds structured, payload-free `worker_inbound_clipboard_rejected` diagnostics with fixed categories:

- `too_large`;
- `allocation_failed`;
- `state_invalid`;
- `revision_exhausted`;
- `invalid_payload`;
- `not_utf8`.

The oversize path may include only safe numeric byte-count and maximum-size metadata. Cache invalidation is logged with fixed metadata such as whether a stale snapshot was removed. No clipboard text, typed text, bearer token, VNC password, screenshot data, or other sensitive payload is logged.

### Deterministic R3 regression coverage

`tests/native/vnc_shim_clipboard_callback_test.c` is compiled in the secured native smoke with strict `-Wall -Wextra -Werror -pedantic` flags. Its test-only translation unit substitutes deterministic `WaitForMessage` and `HandleRFBServerMessage` functions without adding fault-injection symbols to the shipped native ABI.

It proves:

- a valid inbound clipboard update is stored with a revision;
- oversize rejection clears the previous native clipboard and records `VRC_STATUS_CLIPBOARD_TOO_LARGE`;
- deterministic allocation failure records `VRC_STATUS_CLIPBOARD_ALLOCATION_FAILED`;
- invalid state records `VRC_STATUS_CLIPBOARD_STATE_INVALID`;
- `UINT64_MAX` revision exhaustion records `VRC_STATUS_CLIPBOARD_REVISION_EXHAUSTED`;
- `HandleRFBServerMessage()` can return success while the callback fails and `vrc_client_poll()` still returns the callback-specific non-success status;
- the callback failure disconnects the affected native client;
- a subsequent valid poll clears stale callback status and succeeds.

The worker regression `rejected_newer_clipboard_invalidates_stale_cache_and_reconnect_recovers` proves an initially valid `"old clipboard"` snapshot becomes unavailable after a newer rejected update, the worker creates a replacement session, and a later valid `"recovered clipboard"` value becomes observable. Those sentinel payloads exist only inside deterministic tests and are not logged by production paths.

`tests/test_native_contract.py` requires the callback-helper smoke coverage, preventing the deterministic native regression from silently disappearing from CI.

### R3 implementation-head validation

Exact R3 implementation candidate before TODO/evidence closeout documentation:

`76913758ddbf1180f5fe155ca3f7a37ef87dcb21`

Regular CI run `33446396479`: **success**.

That run passed:

- `cargo fmt --all --check`;
- Clippy with warnings denied;
- the full Rust test suite, including the R3 stale-cache/reconnect regression;
- rustdoc with warnings denied;
- Python compilation, Ruff, Pylint, and mypy;
- Python/workflow/native contract tests;
- shell syntax;
- desktop image smoke;
- native adapter smoke including the deterministic callback helper;
- WorkerHandle TigerVNC input E2E;
- WorkerHandle TigerVNC text/clipboard E2E;
- authenticated HTTP TigerVNC E2E;
- controller image / Compose / persistence smoke;
- full R13 Compose integration.

Release Gates run `33446396335`: **success**.

That exact-head release run passed:

- full-history secret scanning;
- shell and GitHub Actions linting;
- Dockerfile and Compose validation;
- advisory/license/source/duplicate policy;
- release binary inspection;
- adapter AddressSanitizer;
- controller/core ThreadSanitizer;
- core Miri;
- release image build;
- vulnerability inventories;
- CycloneDX SBOM generation;
- exact CRITICAL VEX enforcement.

No release-critical gate was weakened for R3.

### R3 silent-failure review limited to this slice

The callback result is no longer discarded, stale native/controller clipboard state is no longer retained after a rejected newer update, and the implementation does not continue using a native session after callback failure. The test-only allocation/message-handler hooks are confined to the dedicated C test translation unit and are not exported by the production shim.

The comprehensive cross-cutting silent-failure/fallback audit remains R9 and is not claimed complete here.

## Explicit R3 safety statements

- A native clipboard callback failure is machine-readable and observable through `vrc_client_poll()`.
- A successful LibVNC message-handler return cannot mask a clipboard callback failure.
- Oversize, allocation, invalid-state, and revision-exhaustion conditions remain distinct.
- A rejected newer clipboard cannot leave the previous value authoritative.
- The affected session is invalidated/dropped and recovery uses a replacement session.
- Later valid clipboard data can become authoritative after reconnect.
- Clipboard payload contents and credentials are not logged.
- No release-critical gate was weakened.
- MCP implementation remains out of scope.

## Remaining remediation

R4-R15 remain open. This evidence does **not** claim completion of duration hardening, WebSocket inbound hardening, XFCE startup hardening, shutdown/detach lifecycle hardening, failure classification, the full R9 fallback audit, living-document reconciliation beyond completed slices, or final project-wide exact-`master` sign-off.

The final remediation evidence will extend this file as those slices are completed.
