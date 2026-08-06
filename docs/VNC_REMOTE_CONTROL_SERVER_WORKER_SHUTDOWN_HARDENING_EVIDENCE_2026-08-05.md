# VNC Remote Control Server Worker Shutdown Hardening Evidence

Date: 2026-08-05

Repository: `ekkus93/vnc-remote-control-server`

Target branch: `master`

Companion TODO:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_HARDENING_TODO_2026-08-05.md`

## Final status

Status: historical validation evidence for SHA `f0efed77426c8c9fd3a61190f39fd07b3eefc821`; completion claim superseded by later review.

The recorded SHA did pass the listed CI and Release Gates, and that historical validation remains valid. A later code review found unresolved process-level bridge joining, queue-depth races/underflow, silent input-release failure handling, incomplete full-path test evidence, and startup cleanup result suppression. Therefore this file must not be used as current completion authority.


## Later-review correction

The statement below that queue-depth accounting was fully coherent was too broad. The earlier implementation still had an uncounted startup compatibility envelope, commands behind compatibility shutdown could escape explicit drain accounting, and a submitter racing the final drain could leave stale depth. Those defects, along with the process-level event-bridge hang and input-release observability gaps, are addressed by:

- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_SPEC_2026-08-05.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_WORKER_SHUTDOWN_FINAL_HARDENING_TODO_2026-08-05.md`.

Retain the historical run IDs below as evidence of what those workflows covered; do not infer that they proved the later deterministic race cases.
## Implementation and repair commits

- `40e5e027c6452134edec7fdbd99f3bcd71c650ef` — main worker shutdown lifecycle hardening.
- `eeb3eb154488c73a1f78775beb2eed28e8c959e2` — rustfmt repair for worker shutdown files.
- `24667ed71ae11967373026b2d5d0a735235ea5ee` — rustdoc private-link repair.
- `469b5c695d3d6d95dff8f250f82ac11d05cf472a` — suppress process-local framebuffer revision churn for byte-identical full-frame replacements.
- `2f37ba3b0bb6c7d150ac7d83f09eddfd8b0cde19` — suppress duplicate `FramebufferRevision` events when the canonical framebuffer revision did not advance.
- `1dc8e31944855460783405168369174e8ea49c4f` — rustfmt repair for worker loop style.
- `e61a8c05a63e70e6014363544578ca896a4bfbf6` — suppress process-local framebuffer revision churn for byte-identical dirty-rectangle commits with unchanged availability.
- `f0efed77426c8c9fd3a61190f39fd07b3eefc821` — rustfmt repair for framebuffer duplicate-check style and final validated code SHA.

## Exact validation evidence

```text
Starting implementation baseline: 87424827ce412c0ef2f38af123069796a8134350
Final validated code SHA: f0efed77426c8c9fd3a61190f39fd07b3eefc821
CI run: 31068292461
CI conclusion: success
Release Gates run: 31068292411
Release Gates conclusion: success
R13 status: success on CI run 31068292461, job 92510698696
```

CI run `31068292461` passed:

- Repository quality gates:
  - formatting;
  - strict Clippy;
  - Rust tests;
  - rustdoc with warnings denied;
  - first-party Python compile/tests;
  - shell syntax;
  - CI evidence upload.
- Secured Debian desktop/native job:
  - desktop image smoke;
  - native adapter smoke;
  - WorkerHandle TigerVNC input E2E;
  - WorkerHandle text/clipboard E2E;
  - authenticated HTTP TigerVNC E2E;
  - controller image, Compose, and persistence smoke;
  - R13 Compose integration and E2E validation.

Release Gates run `31068292411` passed:

- static and supply-chain policy;
- full-history Gitleaks;
- ShellCheck;
- actionlint;
- Dockerfile BuildKit checks;
- Compose validation;
- Rust advisory/license/source policy;
- AddressSanitizer;
- ThreadSanitizer;
- Miri;
- Trivy vulnerability inventories;
- CycloneDX SBOM generation;
- exact VEX enforcement.

## Shutdown timeout design

`DesktopWorker::shutdown(timeout)` now requests out-of-band shutdown and waits on a worker-exit notification bounded by the caller-supplied timeout. It joins only after exit is observed. If the worker does not report exit by the deadline, it logs `desktop_worker_shutdown_timeout`, deliberately detaches the join handle, and returns `DesktopError::Timeout`.

This resolves the previous quiet semantic problem where the public timeout argument existed but could be ignored.

## Startup cleanup design

Startup acknowledgement timeout now stores the out-of-band shutdown flag before doing anything else. The legacy shutdown command enqueue is only a best-effort nudge and is not the correctness path. Cleanup waits for worker-exit notification using a bounded deadline, logs `desktop_worker_startup_cleanup_timeout` on timeout, and detaches instead of unbounded-joining.

Startup timeout therefore cannot turn into an unbounded join.

## Receive-side shutdown race closure

The worker loop now classifies a received envelope after queue-depth decrement and before command execution. If shutdown has already been requested and the command is ordinary, the worker completes that command with `DesktopError::WorkerUnavailable`, does not execute it, drains remaining pending commands with `WorkerUnavailable`, and exits through orderly shutdown semantics.

`WorkerCommand::Shutdown` remains compatibility-only. It is not the authoritative shutdown path.

## Drop timeout and join observability

`Drop for DesktopWorker` now requests out-of-band shutdown, waits only `DROP_SHUTDOWN_TIMEOUT`, joins only after worker-exit notification, logs timeout/join failures, detaches on timeout, and does not panic during normal runtime shutdown.

This preserves non-panicking destructor behavior while avoiding silent unbounded waits.

## Deterministic tests added

Worker shutdown hardening tests:

- `shutdown_timeout_is_enforced_when_worker_does_not_exit`
- `startup_timeout_cleanup_does_not_unbounded_join`
- `queued_command_received_after_shutdown_is_rejected_without_execution`
- `drop_logs_or_records_worker_join_timeout_without_blocking`
- `deterministic_saturated_queue_shutdown_still_completes`

Framebuffer revision tests added while repairing the R13 conditional screenshot regression:

- `identical_full_frame_replacement_keeps_revision_and_timestamp`
- `identical_dirty_update_keeps_revision_and_timestamp_when_status_unchanged`
- `changed_dirty_update_advances_revision`
- `dirty_update_completing_incomplete_frame_advances_even_with_identical_pixels`

## R13 repair note

The shutdown hardening implementation reached R13, where CI exposed a real integration regression:

```text
conditional screenshot did not return empty 304
```

The fix did not weaken R13. Instead, canonical framebuffer revision semantics were tightened so byte-identical full-frame and dirty-rectangle commits with unchanged availability do not churn HTTP screenshot validators.

Availability transitions, reconnect commits, changed pixels, stale frames, and incomplete-frame fail-closed behavior remain explicit and covered.

## No broad fallback or bypass confirmation

Confirmed not done:

- no `continue-on-error` was added;
- no R13 assertion was weakened;
- no Release Gates were weakened;
- no broad `.gitleaksignore` pattern was added;
- no broad Trivy/VEX ignore was added;
- no command-capacity increase was used as a shutdown fix;
- no retry-until-queue-space shutdown fallback was added;
- no command payloads, typed text, clipboard contents, bearer tokens, VNC passwords, framebuffer bytes, or screenshots are logged by the new lifecycle paths;
- no force-push was used.

## Local validation caveat

The sandbox used for this pass did not have `cargo`, `rustc`, or `rustfmt`. Local sandbox validation before push was limited to Python compile/tests, shell syntax, and structural text checks. Rust formatting, Clippy, Rust tests, rustdoc, Docker/VNC E2E, R13, and Release Gates were validated by exact-SHA GitHub CI/Release Gates instead.

## Completion checklist

- [x] `DesktopWorker::shutdown(timeout)` has honest timeout behavior.
- [x] Startup-timeout cleanup cannot block indefinitely.
- [x] Startup-timeout cleanup does not silently suppress meaningful join failure.
- [x] `Drop for DesktopWorker` cannot block indefinitely.
- [x] `Drop for DesktopWorker` logs timeout/join failure observably.
- [x] Ordinary commands received after shutdown request are rejected before execution.
- [x] Pending queued command tickets resolve promptly during shutdown.
- [x] Saturated-queue tests are deterministic and bounded.
- [x] Existing worker shutdown tests remain green.
- [x] Input release still occurs on shutdown.
- [ ] Historical queue-depth coherence claim superseded; final-drain and startup-envelope defects were corrected in the final hardening pass.
- [x] Fatal-exit semantics remain correct.
- [x] Public HTTP shutdown behavior remains stable.
- [x] R13 remains green on the final validated code SHA.
- [x] CI passed on the final validated code SHA.
- [x] Release Gates passed on the final validated code SHA.

## 2026-08-06 correctness-review correction

The historical CI and R13 outcomes recorded here remain valid. Two coverage/performance descriptions were incomplete: the prior ThreadSanitizer/Miri discussion did not establish sanitizer execution over the concurrent `controller-api` crate, and prior framebuffer allocation/pass-count statements were not based on a committed counting-allocator measurement. The correctness-review pass adds full `controller-api --lib` TSan, retains Miri only for `remote-desktop-core`, and records reproducible framebuffer measurements in `VNC_REMOTE_CONTROL_SERVER_FRAMEBUFFER_MEASUREMENT_EVIDENCE_2026-08-06.md`. No historical green result is being rewritten.
