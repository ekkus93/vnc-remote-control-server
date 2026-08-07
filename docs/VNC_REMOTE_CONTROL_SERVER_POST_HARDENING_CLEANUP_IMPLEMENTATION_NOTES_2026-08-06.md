# VNC Remote Control Server Post-Hardening Cleanup Implementation Notes

Date: 2026-08-06

Spec: `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_SPEC_2026-08-06.md`

TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_HARDENING_CLEANUP_TODO_2026-08-06.md`

Cleanup starting SHA: `ce98c39a07b8577945ca65fd8d7067200c88ef1f`

Validated implementation SHA before cleanup-completion documentation: `1edc00be8b0909c86f069a217e2db8871cd93f75`

## Summary

This cleanup pass tightened regression evidence and ownership boundaries without reopening the completed post-correctness hardening work. The implementation preserves the accepted shutdown, framebuffer, authentication, ETag, WebSocket, input, privacy, R13, CI, and Release Gates contracts.

## C1 — Prior hardening final evidence

Created `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_FINAL_EVIDENCE_2026-08-06.md`.

It records the prior hardening documentation tip `59fe5363f5e37e92fbe47c45d3c883c91c8392c8` and its exact permanent validation:

- CI `31145131469`: success;
- Release Gates `31145131453`: success.

The addendum explains why the historical TODO could not truthfully embed its own future commit SHA or future workflow run IDs before those workflows existed. Historical evidence was not rewritten.

## C2 — Established-WebSocket sequence exhaustion

The production event service loop and the deterministic test socket now share the same private `serve_socket` implementation. Production still enters through `EventHub::serve(WebSocket, ...)`; the production WebSocket is boxed only to keep the internal production/test enum compact under strict Clippy.

The new `established_client_closes_on_sequence_exhaustion_with_bounded_1011` test:

- subscribes and receives the initial snapshot first;
- proves the snapshot remains payload-free;
- forces the process-local event sequence to `u64::MAX` only after establishment;
- triggers the existing terminal exhaustion state;
- waits with a bounded timeout rather than arbitrary sleeps;
- requires close code `1011`;
- requires exact reason `event sequence exhausted`;
- rejects sensitive terms in the close reason.

The existing pre-upgrade `503 event_sequence_exhausted` path and normal event delivery remain unchanged.

## C3 — Secret clone hardening

The review found that `SecretString`, `NativeClientConfig`, `WorkerSettings`, and `ControllerConfig` were broadly cloneable even though most production code did not require byte duplication.

The cleanup removes those implicit `Clone` capabilities. `ApiToken` remains cloneable because it shares an `Arc<SecretString>` and does not duplicate token bytes.

`DesktopWorker::spawn` has one named helper, `duplicate_native_config_for_reconnect_factory`, for the reconnect factory's required independently owned VNC connection configuration. That helper makes the password duplication explicit and local.

An intermediate strict-Clippy run exposed a second production duplication in `main.rs`: `config.worker.clone()`. Instead of restoring `Clone`, the ownership model was repaired structurally:

- `ControllerConfig` is consumed in `main`;
- `WorkerSettings` moves into `DesktopWorker`;
- `HttpWorkerSettings` carries only HTTP-specific values and no VNC password;
- `WorkerHttpBackend` no longer accepts the full secret-bearing controller configuration.

This removes the main-process duplicate of the VNC password. The remaining extra password owner is the explicitly named reconnect-factory copy required by the reconnect architecture.

No secret-bearing type gained value-exposing `Debug` or `Display` behavior.

## C4 — Native sensitive-buffer cleanup regression protection

The native shim now centralizes project-owned sensitive cleanup through `vrc_scrub_and_free`, which always scrubs before `free`.

The helper is used for:

- stored clipboard release/replacement/destruction via `vrc_release_clipboard`;
- outbound temporary clipboard send copies;
- the shim-owned persistent VNC password during destruction.

Clipboard revision exhaustion remains checked before allocation or replacement.

`tests/test_native_contract.py` now protects the central scrub-before-free primitive and each relevant call site. It also protects the named reconnect secret-duplication boundary.

A freed-memory/allocator-reuse semantic test was deliberately not added. Reading freed storage is undefined/unreliable and was explicitly forbidden by the cleanup contract. Centralizing cleanup into one primitive, source-contract guarding the call sites, and retaining native/clipboard E2E coverage gives stronger regression protection without unsafe post-free inspection.

The guarantee remains limited to project-owned buffers; no claim is made for LibVNCClient-, server-, toolkit-, OS-, allocator-, swap-, or crash-dump-owned copies.

## C5 — Recovery artifact and policy audit

Active `.github` execution surface contains only permanent configuration/workflows:

- `.github/dependabot.yml`;
- `.github/workflows/ci.yml`;
- `.github/workflows/publish-ci-status.yml`;
- `.github/workflows/release-gates.yml`.

No active post-correctness recovery scripts or temporary recovery workflows remain.

The three remaining `POST_CORRECTNESS_HARDENING_RECOVERY_*` files under `docs/` are documentation-only historical records. They were retained because they preserve useful implementation/evidence history and are not executable or wired into permanent workflows.

Workflow action pins and contract-test constants remain aligned. `.gitleaksignore` remains an exact-fingerprint list; the release-policy contract forbids wildcard/broad ignores and continues to require full-history scanning.

## Intermediate validation failures repaired at root

Several intermediate candidates were intentionally not accepted as evidence:

- `b339db513dd4ef784e8c16e4ce6703b8b3e23de9`: strict Clippy exposed the missed `config.worker.clone()` call site. The ownership model was repaired rather than restoring blanket secret cloning.
- `ee6d0ecc64097e16fae8b2028f3d68aabb8c3d29`: `cargo fmt --check` failed on the new WebSocket test. The exact rustfmt output was applied.
- `eac92ffaab309b5b2f4ab800e7593025808ea36f`: strict Clippy rejected the large internal `EventSocket` enum. The production WebSocket variant was boxed rather than suppressing `clippy::large_enum_variant`.

These red/superseded candidates are not completion evidence.

## Local execution availability

The ChatGPT execution environment did not have a usable local repository checkout because outbound GitHub DNS/direct network access was unavailable. No local Rust, Python, shell, Docker, VNC, or Compose command is represented as locally passed.

The corresponding permanent exact-SHA workflow surfaces are the authoritative execution evidence.

## Exact-SHA implementation validation

Validated implementation SHA:

`1edc00be8b0909c86f069a217e2db8871cd93f75`

CI run `31148063429`: `success`

- repository quality gates: success;
- formatting: success;
- Clippy with warnings denied: success;
- full workspace Rust tests: success;
- rustdoc with warnings denied: success;
- Python/workflow contracts: success;
- shell syntax: success;
- desktop smoke: success;
- native adapter smoke: success;
- WorkerHandle input E2E: success;
- WorkerHandle text/clipboard E2E: success;
- authenticated HTTP E2E: success;
- controller image/Compose/persistence: success;
- R13 Compose integration/E2E: success.

Release Gates run `31148063423`: `success`

- static/supply-chain gates: success;
- full-history Gitleaks: success;
- ShellCheck/actionlint: success;
- Dockerfile/Compose validation: success;
- advisory/license/source/duplicate policy: success;
- auditable binary verification: success;
- AddressSanitizer: success;
- controller ThreadSanitizer: success;
- core ThreadSanitizer: success;
- Miri: success;
- Trivy/CycloneDX SBOM/VEX: success.

## Deferred boundaries

No C1-C5 cleanup requirement is deferred.

Third-party password/clipboard residual-memory boundaries remain explicit non-guarantees rather than unfinished cleanup work.