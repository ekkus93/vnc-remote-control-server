# VNC Remote Control Server Post-Correctness Hardening Implementation Notes

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_SPEC_2026-08-06.md`

TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md`

Reviewed correctness baseline: `96836f7ff964813fb727a1f7407fb0b1f448b738`

Hardening source-edit starting SHA: `acee2808bae8a97710c881525e78eb6f5d1d6abb`

Validated implementation SHA before this documentation commit: `d618d56807c416547ed54cdd95bb4c824abdea84`

## Summary

This pass closed the post-correctness hardening items without weakening the accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, R13, CI, or Release Gates contracts.

The implementation was recovered from an interrupted partial series, audited against the original hardening TODO, and then validated on permanent workflows. Several validation failures were repaired at their root rather than bypassed: a duplicated CR12 positive-control test, test fixtures that still constructed raw API-token strings, an invalid WebSocket unit-test upgrade harness, a LibVNCClient incremental framebuffer rectangle bug exposed by R13, exact Gitleaks false-positive fingerprints for the RFC6455 sample nonce, and stale immutable GitHub Action pins in the workflow contract test.

## H1 — CR12 mismatched-frame evidence

`crates/controller-api/src/worker/tests/reconnect.rs` retains the causal negative test `mismatched_native_frame_never_reaches_connected` and its assertions that:

- worker poll progress is observed through the fixture channel;
- mismatched display/framebuffer revisions do not reach `Connected`;
- `fatal_exit` remains false;
- no framebuffer snapshot becomes current.

The adjacent `matching_native_frame_positive_control_reaches_connected` fixture uses the same worker/session observation path with matching native revision `7`. It requires causal poll progress, reaches `Connected`, observes worker framebuffer revision `1`, and checks the first canonical RGBA pixel is `[0x22, 0x22, 0x22, 0xff]`.

This is a test-evidence repair; it does not intentionally change the public runtime contract.

## H2 — EventHub sequence exhaustion

Event sequence allocation now returns `Result<ServerEvent, EventSequenceError>` and uses checked atomic increment semantics. Exhaustion at `u64::MAX`:

- does not wrap, reset, reuse, saturate silently, or panic;
- transitions the process-local hub into a terminal exhausted state;
- emits the payload-free `event_hub_sequence_exhausted` diagnostic once;
- makes subsequent bridge publication fail closed rather than manufacture sequence IDs;
- maps initial snapshot failure to bounded HTTP `503 event_sequence_exhausted` before WebSocket upgrade;
- closes established WebSockets with code `1011` and reason `event sequence exhausted` no later than the next bounded heartbeat wake-up.

OpenAPI and WebSocket/operator documentation describe the new bounded failure behavior.

## H3 — API bearer-token lifecycle

The long-lived API token is now an explicit `ApiToken` backed by `Arc<SecretString>` rather than raw `Arc<str>`. The type intentionally has no `Debug` or `Display` implementation. Cloning controller/router state clones only the shared secret owner, while the authentication boundary borrows bytes for the existing constant-time comparison.

Missing, query-string, malformed, wrong, and empty tokens remain rejected. Valid `Authorization: Bearer ...` authentication remains accepted. Configuration debug output and access logs remain redacted.

## H4 — Rejected secret-file scrubbing

Secret parsing now keeps the original owned byte vector through UTF-8 validation and CR/LF trimming. Invalid UTF-8, empty-after-trim input, embedded NUL, and parser rejection paths route through one scrub-before-error boundary. Trailing CR/LF bytes are scrubbed before successful truncation.

Scrubbing uses the safe `libvnc_adapter::scrub_secret_bytes` entry point, which confines the volatile-write implementation to the native-boundary crate. Tests observe the live buffer before ownership ends; no freed-memory inspection is used.

Metadata, regular-file, size, and Unix permission policy remain unchanged.

## H5 — Native clipboard/transient buffer policy

The C shim now treats project-owned clipboard allocations as sensitive transient memory:

- `vrc_release_clipboard` scrubs the stored allocation, including its terminating NUL, before free;
- replacement in `vrc_store_clipboard` uses that helper before installing the new value;
- `vrc_client_destroy` uses the same helper;
- `vrc_client_send_clipboard` scrubs its temporary outbound C copy before free on both send success and failure;
- clipboard revision overflow is rejected before allocating or replacing the prior clipboard value.

The guarantee is deliberately limited to project-owned native allocations. It does not claim that Rust request/response values, Axum buffers, LibVNCClient, VNC servers, desktop applications, Tk/toolkits, OS clipboard managers, client applications, allocators, swap, or crash dumps have no residual copies.

## H6 — Required command metrics

`HttpBackend::command_submissions_in_flight()` and `HttpBackend::command_queue_capacity()` are required trait methods with no default zero implementation. Production and test backends implement them explicitly. The exported metric names remain:

- `vrc_worker_command_submissions_in_flight`
- `vrc_worker_command_queue_capacity`

No compatibility alias for the removed queue-depth metric was restored.

## Validation repairs encountered during the loop

### R13 / LibVNCClient incremental framebuffer requests

Permanent CI exposed malformed incremental framebuffer requests of `0x0 at 65535,0`. LibVNCClient initializes its automatic update rectangle with `x = -1`; the shim had not initialized that rectangle before the library automatically rearmed incremental updates.

The shim now initializes `updateRect` to the full current framebuffer rectangle and relies on LibVNCClient's automatic rearm path rather than issuing a redundant callback request. R13 also establishes a bounded stable framebuffer before asserting conditional screenshot `304` behavior, so ordinary XFCE settling is distinguished from a broken ETag contract.

### Full-history Gitleaks

Release Gates identified two synthetic findings for the standard RFC6455 WebSocket sample nonce `dGhlIHNhbXBsZSBub25jZQ==`. The existing exact-fingerprint ignore mechanism was extended only for those proven historical false positives. The release-policy contract pins the complete explicit fingerprint set and forbids wildcard ignores. Full-history scanning, failure behavior, and the Gitleaks command remain unchanged.

### Workflow action-pin contract

After branch consolidation, immutable `actions/checkout` and `actions/setup-python` pins in `ci.yml` were newer than the constants in `tests/test_workflow_contract.py`. The contract constants were updated to the exact workflow SHAs rather than relaxing the immutable-pin assertion.

## Local execution availability

A normal local repository checkout was unavailable in the ChatGPT execution container because GitHub DNS/direct network access was blocked. Therefore local commands were not represented as locally passed.

The same required Rust, Python, shell, native, desktop, HTTP, Compose, and R13 surfaces were executed by the permanent exact-SHA CI workflow. Native safety and supply-chain/release surfaces were executed by permanent Release Gates.

## Exact-SHA validation before final documentation

Validated implementation SHA: `d618d56807c416547ed54cdd95bb4c824abdea84`

- CI run `31144227898`: `success`
  - Repository quality gates: success
  - Secured Debian desktop and native adapter: success
  - Includes formatting, Clippy with warnings denied, full workspace tests, rustdoc with warnings denied, Python/workflow contracts, shell syntax, desktop smoke, native smoke, WorkerHandle input E2E, text/clipboard E2E, authenticated HTTP E2E, Compose/persistence, and R13.
- Release Gates run `31144227952`: `success`
  - Release static and supply-chain gates: success
  - Release native sanitizer and Miri gates: success
  - Release image vulnerability and SBOM gates: success
  - Includes full-history Gitleaks, ShellCheck/actionlint, Dockerfile/Compose validation, dependency policy, auditable binary verification, ASan, controller/core TSan, Miri, Trivy, CycloneDX SBOM, and VEX enforcement.

Because this implementation-notes file and the completed TODO are documentation changes after implementation validation, the final repository-tip SHA and its CI/Release Gates run IDs are recorded externally after those workflows complete. The documents intentionally do not claim to embed their own future commit SHA or future workflow IDs.

## Deferred boundaries

No H1-H6 requirement is deferred.

The following are explicit residual boundaries rather than unfinished hardening tasks:

- LibVNCClient-owned password memory beyond the proven classic-VNC scrub boundary remains third-party-owned and is documented in `SECURITY.md`.
- Third-party/OS/toolkit/allocator clipboard residuals are not claimed scrubbed.
- Crash dumps, swap, kernel memory, reverse-proxy buffers, and client-side copies remain outside the project-owned live-buffer scrub guarantee.
