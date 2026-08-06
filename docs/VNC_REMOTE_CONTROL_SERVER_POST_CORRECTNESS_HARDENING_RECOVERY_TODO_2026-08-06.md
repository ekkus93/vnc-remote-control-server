# VNC Remote Control Server Post-Correctness Hardening Recovery TODO

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_RECOVERY_SPEC_2026-08-06.md`

Original TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md`

Recovery starting SHA: `100e4454634a577bf5ffd7b0dbc8913cf5a60cea`

Status: in progress.

---

## R0. Recovery controls

- [x] Confirm default branch is `master`.
- [x] Record recovery starting SHA.
- [x] Confirm the requested recovery TODO did not previously exist.
- [x] Create the recovery spec and TODO on `master`.
- [ ] Read and audit every partial change from `acee2808bae8a97710c881525e78eb6f5d1d6abb` through the recovery starting SHA.
- [ ] Keep the completed correctness-review contracts intact.
- [ ] Do not weaken permanent CI or Release Gates.
- [ ] Do not use broad suppressions, ignored exit codes, force pushes, or older-SHA evidence.

---

## R1. Audit and repair H1 CR12 evidence

- [ ] Inspect the negative mismatched native frame test.
- [ ] Inspect the added matching-frame positive control.
- [ ] Confirm both use the same worker/session observation path.
- [ ] Confirm the negative proof observes causal poll progress.
- [ ] Confirm mismatch never reaches `Connected`, never publishes a current framebuffer, and never sets `fatal_exit`.
- [ ] Confirm the positive fixture reaches `Connected` and publishes distinguishable canonical RGBA content.
- [ ] Repair incorrect revision or pixel assumptions.
- [ ] Run targeted and full controller-api tests.

Acceptance:

- [ ] CR12 has causal negative evidence plus a meaningful positive control.

---

## R2. Audit and repair H2 EventHub sequence exhaustion

- [ ] Inspect every event sequence allocation and publication path.
- [ ] Ensure allocation returns an explicit error at exhaustion.
- [ ] Ensure no wrap, reset, reuse, silent saturation, panic, `unwrap`, or `expect` remains.
- [ ] Ensure only one bounded payload-free exhaustion diagnostic is emitted.
- [ ] Ensure repeated exhausted allocation attempts do not cause log flooding.
- [ ] Ensure bridge worker events are deterministically dropped after exhaustion.
- [ ] Ensure initial snapshot exhaustion returns HTTP 503 before WebSocket upgrade.
- [ ] Ensure the error uses the normal bounded JSON envelope and stable code.
- [ ] Ensure a subscription permit is released if snapshot construction fails.
- [ ] Preserve normal strictly increasing event sequences and WebSocket delivery.
- [ ] Add/update unit and route tests for exhaustion and normal operation.

Acceptance:

- [ ] Event sequence exhaustion is deterministic, observable, payload-free, and non-panicking.

---

## R3. Audit and repair H3 API token lifecycle

- [ ] Inspect the new API-token type and all conversion/constructor paths.
- [ ] Remove production conversions that silently copy token bytes from ordinary long-lived strings.
- [ ] Ensure the token type implements neither secret-revealing `Debug` nor `Display`.
- [ ] Ensure state/config cloning clones only a shared owning handle.
- [ ] Preserve constant-time bearer comparison.
- [ ] Preserve missing/query/malformed/wrong-token rejection and valid Bearer acceptance.
- [ ] Preserve empty-token construction rejection.
- [ ] Preserve config debug and access-log redaction.
- [ ] Ensure tests do not print token sentinels on failure.

Acceptance:

- [ ] No long-lived raw `Arc<str>` or equivalent ordinary API-token storage remains.

---

## R4. Audit and repair H4 secret-file rejection scrubbing

- [ ] Inspect ownership across file read, UTF-8 validation, CR/LF trimming, NUL validation, and secret construction.
- [ ] Ensure invalid UTF-8 bytes are scrubbed before release.
- [ ] Ensure empty-after-trim bytes are scrubbed before release.
- [ ] Ensure embedded-NUL bytes are scrubbed before release.
- [ ] Ensure future parser rejection paths retain one scrub guard.
- [ ] Avoid unnecessary ordinary `String` copies on success.
- [ ] Keep metadata, size, regular-file, and Unix permission checks unchanged.
- [ ] Keep errors redaction-safe.
- [ ] Use deterministic live-buffer instrumentation; do not inspect freed memory.

Acceptance:

- [ ] Every parser-owned secret byte buffer is scrubbed before release on rejection.

---

## R5. Complete H5 native clipboard/transient buffer scrubbing

Source: `crates/libvnc-adapter/native/vnc_shim.c`

- [ ] Inspect current clipboard ownership, replacement, destruction, and outbound send paths.
- [ ] Track the exact project-owned clipboard allocation length.
- [ ] Scrub the previous stored clipboard before replacement and free.
- [ ] Scrub the stored clipboard before client destruction and free.
- [ ] Scrub the outbound clipboard copy before free on success.
- [ ] Scrub the outbound clipboard copy before free on failure.
- [ ] Reuse the existing volatile-byte scrub primitive or an equivalently explicit primitive.
- [ ] Preserve VNC password scrubbing and RFB clipboard semantics.
- [ ] Add source-level or native-unit contracts that fail if free occurs without scrub.
- [ ] Keep clipboard payloads out of logs, diagnostics, and test failure text.

Acceptance:

- [ ] Every project-owned native clipboard/transient send allocation is scrubbed before free or replacement.

---

## R6. Audit and repair H6 required backend metrics

- [ ] Confirm both command metric methods are required trait methods.
- [ ] Inspect every production, test, and mock `HttpBackend` implementation.
- [ ] Give every implementation explicit intentional values.
- [ ] Preserve `vrc_worker_command_submissions_in_flight`.
- [ ] Preserve `vrc_worker_command_queue_capacity`.
- [ ] Preserve HELP/TYPE metadata.
- [ ] Ensure no default zero, `unwrap_or(0)`, or old queue-depth alias exists.

Acceptance:

- [ ] Omitting either metric method fails compilation.

---

## R7. Documentation and policy contracts

- [ ] Update `SECURITY.md` for API-token ownership and remaining process-memory limitations.
- [ ] Update `SECURITY.md` for secret-file rejection scrubbing.
- [ ] Update `SECURITY.md` for project-owned native clipboard scrub boundaries.
- [ ] Update `docs/OPERATOR_GUIDE.md` for EventHub exhaustion behavior and stable error code.
- [ ] Document that CR12 positive-control work changes tests, not runtime behavior.
- [ ] Document that toolkit, OS, VNC server, LibVNCClient, allocator, Rust response body, and other third-party copies are not covered without evidence.
- [ ] Add/update documentation or source-policy tests preventing broad zeroization claims.
- [ ] Update the original hardening TODO only for verified completed items.

Acceptance:

- [ ] Documentation matches implemented ownership and failure contracts without overclaiming.

---

## R8. Validation and repair loop

Local environment:

- [x] Attempt local repository checkout.
- [x] Record that local clone failed because the execution container could not resolve `github.com`.
- [ ] Run any available local static checks if repository bytes become available.
- [ ] Do not label unavailable local checks as passed.

Permanent validation:

- [ ] Push implementation changes intentionally to `master` without force.
- [ ] Inspect CI on each relevant exact SHA.
- [ ] Inspect failed job steps and logs rather than guessing.
- [ ] Repair source/test root causes only.
- [ ] Obtain CI success on the exact final tip.
- [ ] Obtain Release Gates success on the same exact final tip.
- [ ] Confirm all permanent release surfaces pass.

---

## R9. Final evidence and closure

- [ ] Update this TODO with exact evidence.
- [ ] Update the original hardening TODO with verified checkbox state and evidence.
- [ ] Record implementation and final documentation SHAs.
- [ ] Record exact CI and Release Gates run IDs and conclusions.
- [ ] Leave no temporary workflows or diagnostic files.
- [ ] Mark complete only when the exact final repository tip is green in both permanent workflows.

Final evidence:

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

- [ ] No unverified partial commit is treated as complete.
- [ ] No EventHub sequence path wraps, resets, reuses, saturates silently, or panics.
- [ ] No API bearer token is stored as long-lived ordinary text.
- [ ] No secret parser rejection drops live secret bytes without scrub.
- [ ] No project-owned native clipboard allocation is freed or replaced without scrub.
- [ ] No broad third-party/OS/allocator zeroization claim exists.
- [ ] No command metric trait method silently defaults to zero.
- [ ] No sleep-only CR12 negative evidence is accepted.
- [ ] No sensitive payload is logged.
- [ ] No permanent validation gate is weakened.
- [ ] No queued, canceled, skipped, partial, superseded, or older-SHA run is completion evidence.
