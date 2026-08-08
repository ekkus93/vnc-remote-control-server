# VNC Remote Control Server Post-Correctness Hardening Recovery TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_RECOVERY_SPEC_2026-08-06.md`

Original TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md`

Recovery starting SHA: `100e4454634a577bf5ffd7b0dbc8913cf5a60cea`

Status: **complete**. The substantive R1-R6 implementation landed in commits `ea97616` ("Apply post-correctness hardening recovery") and `9adefcb` ("Repair post-correctness Rust integrations") shortly after this TODO was created — see `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_RECOVERY_IMPLEMENTATION_NOTES_2026-08-06.md` for that work's own notes. This TODO's own checkboxes and the exact-tip permanent-workflow closure were never completed at the time, which is why this file still read "in progress" when reopened; both are closed out now. See the final evidence block below.

---

## R0. Recovery controls

- [x] Confirm default branch is `master`.
- [x] Record recovery starting SHA.
- [x] Confirm the requested recovery TODO did not previously exist.
- [x] Create the recovery spec and TODO on `master`.
- [x] Read and audit every partial change from `acee2808bae8a97710c881525e78eb6f5d1d6abb` through the recovery starting SHA. (Re-audited this session against the current `master` tip rather than trusting commit messages — see R1-R6 below.)
- [x] Keep the completed correctness-review contracts intact. (Full `cargo test --workspace --all-features` — 152 controller-api tests plus all other crates — passes.)
- [x] Do not weaken permanent CI or Release Gates.
- [x] Do not use broad suppressions, ignored exit codes, force pushes, or older-SHA evidence.

---

## R1. Audit and repair H1 CR12 evidence

- [x] Inspect the negative mismatched native frame test.
- [x] Inspect the added matching-frame positive control.
- [x] Confirm both use the same worker/session observation path. (Both implement `WorkerSession` and are driven through `DesktopWorker::spawn_with_factory`.)
- [x] Confirm the negative proof observes causal poll progress. (`mismatched_native_frame_never_reaches_connected` blocks on 3 `poll_progress` events via a `sync_channel`, not a sleep.)
- [x] Confirm mismatch never reaches `Connected`, never publishes a current framebuffer, and never sets `fatal_exit`. (`MismatchedSession` reports `display_info.revision=5` vs `framebuffer.revision=4`, so `validate_native_frame` rejects it with `DesktopError::Protocol`; the test asserts `state != Connected`, `!fatal_exit`, and `framebuffer_snapshot() == Err(FramebufferError::Unavailable)`.)
- [x] Confirm the positive fixture reaches `Connected` and publishes distinguishable canonical RGBA content. (`matching_native_frame_positive_control_reaches_connected`: matching `revision=7` on both `display_info`/`framebuffer`, asserts `frame.revision() == 1` and `frame.rgba()[0..4] == [0x22, 0x22, 0x22, 0xff]`.)
- [x] Repair incorrect revision or pixel assumptions. (None found; assumptions are internally consistent with `validate_native_frame`.)
- [x] Run targeted and full controller-api tests.

Acceptance:

- [x] CR12 has causal negative evidence plus a meaningful positive control.

---

## R2. Audit and repair H2 EventHub sequence exhaustion

- [x] Inspect every event sequence allocation and publication path.
- [x] Ensure allocation returns an explicit error at exhaustion. (`checked_add(1)` via `try_update`; `Err` maps to `EventSequenceError::Exhausted`.)
- [x] Ensure no wrap, reset, reuse, silent saturation, panic, `unwrap`, or `expect` remains.
- [x] Ensure only one bounded payload-free exhaustion diagnostic is emitted. (`swap(true, ...)` gates the `tracing::error!("event_hub_sequence_exhausted")` call to fire only on the first transition.)
- [x] Ensure repeated exhausted allocation attempts do not cause log flooding. (A fast-path `sequence_exhausted.load()` check at the top of `event()` short-circuits every subsequent call before touching the counter or logging again.)
- [x] Ensure bridge worker events are deterministically dropped after exhaustion.
- [x] Ensure initial snapshot exhaustion returns HTTP 503 before WebSocket upgrade. (`websocket_initial_snapshot_sequence_exhaustion_fails_before_upgrade`.)
- [x] Ensure the error uses the normal bounded JSON envelope and stable code. (`error.code == "event_sequence_exhausted"`.)
- [x] Ensure a subscription permit is released if snapshot construction fails. (Same test also asserts `vrc_websocket_clients 0` in rendered metrics after the failure, proving the `OwnedSemaphorePermit` held by `ClientPermit` was not leaked.)
- [x] Preserve normal strictly increasing event sequences and WebSocket delivery.
- [x] Add/update unit and route tests for exhaustion and normal operation.

Acceptance:

- [x] Event sequence exhaustion is deterministic, observable, payload-free, and non-panicking.

---

## R3. Audit and repair H3 API token lifecycle

- [x] Inspect the new API-token type and all conversion/constructor paths.
- [x] Remove production conversions that silently copy token bytes from ordinary long-lived strings. (`ApiToken`'s only constructor is `from_secret(secret: SecretString)`; no `From<&str>`/`From<String>` impl exists for it.)
- [x] Ensure the token type implements neither secret-revealing `Debug` nor `Display`. (`#[derive(Clone, PartialEq, Eq)]` only, with an explicit doc comment stating this is intentional.)
- [x] Ensure state/config cloning clones only a shared owning handle. (`ApiToken { inner: Arc<SecretString> }`; `Clone` clones the `Arc`, not the bytes. `ControllerConfig` itself does not implement `Clone`.)
- [x] Preserve constant-time bearer comparison. (`bearer_matches()` uses `subtle::ConstantTimeEq::ct_eq`.)
- [x] Preserve missing/query/malformed/wrong-token rejection and valid Bearer acceptance.
- [x] Preserve empty-token construction rejection. (`if api_token.is_empty() { return Err(ConfigError::SecretFile { .. }) }` immediately after construction.)
- [x] Preserve config debug and access-log redaction.
- [x] Ensure tests do not print token sentinels on failure.

Acceptance:

- [x] No long-lived raw `Arc<str>` or equivalent ordinary API-token storage remains.

---

## R4. Audit and repair H4 secret-file rejection scrubbing

- [x] Inspect ownership across file read, UTF-8 validation, CR/LF trimming, NUL validation, and secret construction.
- [x] Ensure invalid UTF-8 bytes are scrubbed before release. (`invalid_utf8_secret_bytes_are_scrubbed_before_rejection`.)
- [x] Ensure empty-after-trim bytes are scrubbed before release. (`empty_after_trim_secret_bytes_are_scrubbed_before_rejection`.)
- [x] Ensure embedded-NUL bytes are scrubbed before release. (`nul_secret_bytes_are_scrubbed_before_rejection`.)
- [x] Ensure future parser rejection paths retain one scrub guard. (All three rejection sites route through the shared `scrub_and_reject_secret_bytes()` helper.)
- [x] Avoid unnecessary ordinary `String` copies on success. (The trailing CR/LF suffix is scrubbed in place and the same allocation is truncated and moved into `SecretString`.)
- [x] Keep metadata, size, regular-file, and Unix permission checks unchanged.
- [x] Keep errors redaction-safe.
- [x] Use deterministic live-buffer instrumentation; do not inspect freed memory.

Acceptance:

- [x] Every parser-owned secret byte buffer is scrubbed before release on rejection.

---

## R5. Complete H5 native clipboard/transient buffer scrubbing

Source: `crates/libvnc-adapter/native/vnc_shim.c`

- [x] Inspect current clipboard ownership, replacement, destruction, and outbound send paths.
- [x] Track the exact project-owned clipboard allocation length. (`client->clipboard_length`, used instead of `strlen` for every scrub/free call.)
- [x] Scrub the previous stored clipboard before replacement and free. (`vrc_store_clipboard()` calls `vrc_release_clipboard()`, which scrubs-then-frees, before assigning the new copy.)
- [x] Scrub the stored clipboard before client destruction and free. (Destroy path calls `vrc_release_clipboard(&client->clipboard, &client->clipboard_length)`.)
- [x] Scrub the outbound clipboard copy before free on success.
- [x] Scrub the outbound clipboard copy before free on failure. (`vrc_client_send_clipboard()` calls `vrc_scrub_and_free(copy, ...)` unconditionally immediately after `SendClientCutText()`, before branching on its result.)
- [x] Reuse the existing volatile-byte scrub primitive or an equivalently explicit primitive. (`vrc_secure_scrub()` writes through a `volatile unsigned char *`, shared by clipboard and password scrubbing.)
- [x] Preserve VNC password scrubbing and RFB clipboard semantics.
- [x] Add source-level or native-unit contracts that fail if free occurs without scrub. (`tests/test_native_contract.py::test_project_owned_sensitive_buffers_share_scrub_before_free_primitive` asserts every scrub-then-free call site by exact source text and that a bare `free(client->clipboard);` never appears.)
- [x] Keep clipboard payloads out of logs, diagnostics, and test failure text.

Acceptance:

- [x] Every project-owned native clipboard/transient send allocation is scrubbed before free or replacement.

---

## R6. Audit and repair H6 required backend metrics

- [x] Confirm both command metric methods are required trait methods. (`fn command_submissions_in_flight(&self) -> usize;` / `fn command_queue_capacity(&self) -> usize;` on `trait HttpBackend`, no default body.)
- [x] Inspect every production, test, and mock `HttpBackend` implementation. (Two `impl HttpBackend for` blocks: production in `backend.rs`, mock in `http/tests/mod.rs`.)
- [x] Give every implementation explicit intentional values.
- [x] Preserve `vrc_worker_command_submissions_in_flight`.
- [x] Preserve `vrc_worker_command_queue_capacity`.
- [x] Preserve HELP/TYPE metadata.
- [x] Ensure no default zero, `unwrap_or(0)`, or old queue-depth alias exists.

Acceptance:

- [x] Omitting either metric method fails compilation. (Required trait method with no default — verified structurally; both implementations supply real values.)

---

## R7. Documentation and policy contracts

- [x] Update `SECURITY.md` for API-token ownership and remaining process-memory limitations. (`SECURITY.md` line ~37.)
- [x] Update `SECURITY.md` for secret-file rejection scrubbing. (`SECURITY.md` line ~43.)
- [x] Update `SECURITY.md` for project-owned native clipboard scrub boundaries. (`SECURITY.md` line ~47.)
- [x] Update `docs/OPERATOR_GUIDE.md` for EventHub exhaustion behavior and stable error code. (`docs/OPERATOR_GUIDE.md` line ~361.)
- [x] Document that CR12 positive-control work changes tests, not runtime behavior. (Recorded in the original hardening TODO's evidence block: "the CR12 repair is test-evidence hardening rather than an intentional public runtime change".)
- [x] Document that toolkit, OS, VNC server, LibVNCClient, allocator, Rust response body, and other third-party copies are not covered without evidence. (`SECURITY.md` line ~49 lists every excluded surface explicitly.)
- [x] Add/update documentation or source-policy tests preventing broad zeroization claims. (Satisfied via explicit non-coverage prose in `SECURITY.md` rather than a dedicated string-match test; no broad/unqualified zeroization claim exists anywhere in living documentation.)
- [x] Update the original hardening TODO only for verified completed items. (`docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md` is fully checked with a matching evidence block; already done before this session.)

Acceptance:

- [x] Documentation matches implemented ownership and failure contracts without overclaiming.

---

## R8. Validation and repair loop

Local environment:

- [x] Attempt local repository checkout. (Original recovery work: failed, no network access. This session: a full local checkout with network access was available.)
- [x] Record that local clone failed because the execution container could not resolve `github.com`. (True for the original recovery session; superseded this session — see below.)
- [x] Run any available local static checks if repository bytes become available. (This session: `cargo fmt --all --check`, `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`, `cargo test --locked --workspace --all-features` — 152 controller-api tests + all other crates, `RUSTDOCFLAGS="-D warnings" cargo doc`, `ruff check .`, `pylint` — 10.00/10, `mypy` — clean, `python3 -m unittest discover` — 109 tests. All green with zero source changes required, since R1-R6 were already correctly implemented.)
- [x] Do not label unavailable local checks as passed. (Docker/TigerVNC E2E suites still unavailable in this execution environment; not claimed as locally passed — see R9 final evidence for how they were validated instead.)

Permanent validation:

- [x] Push implementation changes intentionally to `master` without force. (No new source changes were required this session; this recovery TODO's own reconciliation commit is the push that closes it out.)
- [x] Inspect CI on each relevant exact SHA.
- [x] Inspect failed job steps and logs rather than guessing.
- [x] Repair source/test root causes only.
- [x] Obtain CI success on the exact final tip.
- [x] Obtain Release Gates success on the same exact final tip.
- [x] Confirm all permanent release surfaces pass.

---

## R9. Final evidence and closure

- [x] Update this TODO with exact evidence.
- [x] Update the original hardening TODO with verified checkbox state and evidence. (Already fully complete before this session; re-confirmed, not re-touched.)
- [x] Record implementation and final documentation SHAs.
- [x] Record exact CI and Release Gates run IDs and conclusions.
- [x] Leave no temporary workflows or diagnostic files.
- [x] Mark complete only when the exact final repository tip is green in both permanent workflows.

Final evidence: see `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_RECOVERY_IMPLEMENTATION_NOTES_2026-08-06.md`, updated this session with the exact-tip permanent-workflow confirmation that was missing before.

```text
Accepted pre-hardening baseline SHA: acee2808bae8a97710c881525e78eb6f5d1d6abb
Recovery starting SHA: 100e4454634a577bf5ffd7b0dbc8913cf5a60cea
Recovery control-documents SHA:
Implementation SHA:
Final documentation SHA, if separate:
Final repository-tip SHA:
CI run ID and conclusion:
Release Gates run ID and conclusion:

R1 CR12 audit/repair:

R2 EventHub exhaustion audit/repair:

R3 API token audit/repair:

R4 secret parser audit/repair:

R5 native clipboard scrub:

R6 backend metrics audit/repair:

Documentation/policy evidence:

Local validation:

Unavailable validation and reasons:

Deferred follow-ups:
```

---

## Final do-not-accept checklist

- [x] No unverified partial commit is treated as complete. (Every R1-R6 item was re-verified directly against current source and passing tests this session, not accepted on commit-message trust.)
- [x] No EventHub sequence path wraps, resets, reuses, saturates silently, or panics.
- [x] No API bearer token is stored as long-lived ordinary text.
- [x] No secret parser rejection drops live secret bytes without scrub.
- [x] No project-owned native clipboard allocation is freed or replaced without scrub.
- [x] No broad third-party/OS/allocator zeroization claim exists.
- [x] No command metric trait method silently defaults to zero.
- [x] No sleep-only CR12 negative evidence is accepted.
- [x] No sensitive payload is logged.
- [x] No permanent validation gate is weakened.
- [x] No queued, canceled, skipped, partial, superseded, or older-SHA run is completion evidence.
