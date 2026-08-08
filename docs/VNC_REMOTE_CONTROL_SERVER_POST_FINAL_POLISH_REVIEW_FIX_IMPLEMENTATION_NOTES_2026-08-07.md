# VNC Remote Control Server Post-Final-Polish Review Fix Implementation Notes

Date: 2026-08-07

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_SPEC_2026-08-07.md`

TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_FINAL_POLISH_REVIEW_FIX_TODO_2026-08-07.md`

Reviewed code baseline SHA: `b1ce8addc846ef8f55f1ffeab5ecd82bfb9b235b`

Spec planning commit: `9095ecc1d96a010061ca463e05848c11f9e92eaa`

Implementation starting SHA: `c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8`

Status: implementation in progress.

## Baseline and scope

Immediately before source changes, `master` was `c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8`. The only commit after the spec planning commit was `c0fa89ebc4e32e64e5a4ed0d701f139b905e12f8`, which added the companion TODO. No production code changed between spec planning and implementation start.

The prior final-polish pass remains closed. Its accepted request-ID exhaustion, EventHub exhaustion wake-up, native scrub source-contract strategy, privacy, CI, and release-gate behavior are invariants for this pass.

## Baseline-confirmed defects

### TypeText pre-held-key ownership

Source inspection of the implementation-start baseline confirms that `type_text()` calls idempotent `set_key(key, true)` and then unconditional `set_key(key, false)`. If the key is already present in `pressed_keys`, the down is skipped and the later up releases/removes caller-owned held state. Regression coverage is being added before/with the fix and must prove rejection before any text-generated native event.

### Python typed-response coercion

Source inspection of the implementation-start baseline confirms that typed HTTP response construction uses Python coercions and casts as if they were runtime validation. Regression coverage is being added before/with the fix and must prove malformed primitive/enum fields raise `ProtocolError` rather than being normalized.

## Validation environment

Direct outbound DNS/network access from the local execution container cannot resolve `github.com`, so a normal local clone is unavailable. Source changes are being made through the connected GitHub repository interface. Local Rust/Python/Docker commands will not be represented as passed unless a usable checkout becomes available; permanent exact-SHA CI and Release Gates remain authoritative execution evidence.

## Decisions and evidence

This section will be filled as P1-P16 complete, including event-channel terminalization, HTTP task observability, poison policy, non-Unicode configuration handling, vendored docs assets and digests, request/command identifier handling, structured native initialization classification, retained intentionally ignored results, intermediate failures, and exact final workflow run IDs.
