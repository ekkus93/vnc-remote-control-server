# VNC Remote Control Server Post-Hardening Cleanup Spec

Date: 2026-08-06

Baseline branch: `master`

Baseline SHA: `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`

Related prior work:

- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_SPEC_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md`
- `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_IMPLEMENTATION_NOTES_2026-08-06.md`

## 1. Purpose

This spec defines a narrow follow-up cleanup pass after the post-correctness hardening work. The prior hardening TODO is complete and exact-tip green at the baseline SHA. This pass must not reopen or redo that work unless source evidence proves a regression.

The goal is to improve evidence hygiene and regression protection in four areas found during review:

1. record final documentation-tip CI and Release Gates evidence in repository-owned documentation;
2. add a live established-WebSocket regression test for EventHub sequence exhaustion close behavior;
3. review and reduce implicit secret cloning, especially `SecretString: Clone`, without weakening API-token ownership;
4. strengthen project-owned native clipboard scrub regression protection beyond purely textual source-contract checks where practical.

This is cleanup/hardening, not a feature pass.

## 2. Current accepted baseline

The accepted baseline is current `master` at:

```text
59fe5363f5e37e92fbe47c45d3c883c91c8392c8
```

At that SHA:

- CI run `31145131469` concluded `success`.
- Release Gates run `31145131453` concluded `success`.
- The post-correctness hardening TODO records the implementation SHA `d618d56807c416547ed54cdd95bb4c824abdea84` and its exact-SHA CI/Release evidence.
- The documentation-completion commit intentionally does not embed its own future run IDs; those final run IDs were recorded externally after the commit completed validation.

This cleanup pass should begin by confirming `master` still resolves to the expected baseline or by explicitly recording the newer starting SHA if `master` has advanced.

## 3. Non-goals

Do not use this pass to:

- redesign the HTTP API;
- change public authentication semantics;
- change WebSocket event schemas except for tests/documentation clarity;
- change VNC input, framebuffer, screenshot, ETag, shutdown, R13, or Compose runtime behavior unless a real bug is found;
- weaken or bypass CI/Release Gates;
- relax Gitleaks, ShellCheck, actionlint, Dockerfile, Compose, cargo policy, sanitizer, Miri, Trivy, SBOM, VEX, or workflow-contract enforcement;
- add broad ignores, `continue-on-error`, forced success, swallowed exit codes, or force pushes;
- claim that third-party, OS, toolkit, allocator, LibVNCClient, VNC-server, reverse-proxy, swap, or crash-dump copies of secrets/clipboard data are scrubbed.

## 4. Global invariants

All changes must preserve these existing accepted contracts.

### 4.1 Authentication and secret ownership

- API token values are loaded from files, not direct environment secret values.
- `HttpState` owns an `ApiToken`, and `ApiToken` uses shared secret ownership rather than long-lived raw `Arc<str>` token ownership.
- Missing bearer header, query-token authentication, malformed bearer values, wrong token, and empty token remain rejected.
- Correct `Authorization: Bearer ...` remains accepted.
- Bearer comparison remains constant-time for same-length candidate values.
- Config debug output, access logs, metrics, events, and error bodies remain redacted.

### 4.2 EventHub sequencing

- Public event sequence IDs never wrap, reset, reuse prior IDs, or silently saturate at `u64::MAX`.
- Event sequence exhaustion remains explicit and fail-closed.
- Initial WebSocket snapshot exhaustion fails before upgrade with bounded HTTP `503 event_sequence_exhausted`.
- Established WebSocket clients close with bounded code/reason behavior when the hub is exhausted after upgrade.
- Snapshot and worker event payloads remain payload-free and do not include typed text, clipboard text, key names, coordinates, framebuffer bytes, screenshot bytes, bearer tokens, VNC passwords, or query secrets.

### 4.3 Native clipboard and transient buffer boundary

- Project-owned C clipboard allocations are scrubbed before replacement/free.
- Outbound project-owned C clipboard send copies are scrubbed before free on both send success and failure.
- VNC password scrub behavior remains unchanged.
- Documentation continues to distinguish project-owned native buffers from Rust request/response values, Axum buffers, Tk/test-app state, LibVNCClient, VNC servers, desktop applications, toolkit/OS clipboard managers, client applications, allocators, swap, and crash dumps.

### 4.4 Metrics

- `HttpBackend::command_submissions_in_flight()` and `HttpBackend::command_queue_capacity()` remain required trait methods.
- No default zero implementation, `unwrap_or(0)`, silent metric fallback, or removed queue-depth alias is reintroduced.

## 5. Cleanup requirement C1 — repository-owned final evidence addendum

### Requirement

Add a concise repository-owned evidence addendum that records the final documentation-tip validation from the prior hardening loop.

Recommended path:

```text
docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_FINAL_EVIDENCE_2026-08-06.md
```

The addendum must record:

- prior hardening documentation-completion SHA `59fe5363f5e37e92fbe47c45d3c883c91c8392c8`;
- final documentation-tip CI run `31145131469` and conclusion `success`;
- final documentation-tip Release Gates run `31145131453` and conclusion `success`;
- the fact that the original TODO could not embed these future run IDs before its own commit existed;
- no claim that any unavailable local validation ran locally.

### Acceptance

- The addendum is factual and short.
- It references the prior TODO and implementation notes.
- It does not alter historical source evidence or pretend the original TODO embedded its own future SHA.

## 6. Cleanup requirement C2 — live established-WebSocket EventHub exhaustion test

### Requirement

Add a live async test proving established WebSocket behavior after EventHub sequence exhaustion occurs after upgrade.

The current code already tests pre-upgrade `503 event_sequence_exhausted` and unit-level sequence exhaustion. This pass should add coverage for the established-client path.

The test should:

- construct a router/state with a bounded `EventHub` and mock backend;
- complete a real WebSocket upgrade through the router or a close equivalent that exercises `EventHub::serve`;
- deliver the initial snapshot successfully;
- force or trigger sequence exhaustion after the client is already established;
- prove the server closes with WebSocket close code `1011` and reason `event sequence exhausted`;
- prove the close happens within the configured bounded heartbeat/wake-up behavior, not through an unbounded sleep;
- prove no event payload leaks typed text, clipboard text, key names, coordinates, framebuffer bytes, screenshot bytes, bearer tokens, VNC passwords, or query secrets.

If the router stack makes a full socket test too brittle, a lower-level `EventHub::serve` test may be accepted only if it exercises the same established-client close branch and documents why full-router upgrade coverage is not practical.

### Acceptance

- Existing pre-upgrade exhaustion behavior remains unchanged.
- Existing normal WebSocket snapshot/event delivery tests still pass.
- The new established-client test fails if the `1011` close path is removed, if the reason changes without documentation, or if the close can hang indefinitely.

## 7. Cleanup requirement C3 — explicit secret clone review and hardening

### Requirement

Review all implementations and uses of `Clone` involving project secret types.

At minimum, inspect:

- `libvnc_adapter::SecretString`;
- `libvnc_adapter::NativeClientConfig`;
- `controller_api::config::ApiToken`;
- `controller_api::config::ControllerConfig`;
- test fixtures that clone secrets.

Preferred outcome:

- Keep `ApiToken` cheap to clone by shared ownership if needed by `HttpState`.
- Remove `Clone` from `SecretString` if production code does not need byte duplication.
- If secret byte duplication is genuinely required, replace implicit `#[derive(Clone)]` with an explicit, named method such as `clone_secret_for_native_boundary()` and document the ownership reason.
- Avoid introducing `Debug` or `Display` for secret values.
- Preserve test ergonomics without allowing tests to hide production secret duplication.

### Acceptance

- There is no accidental or unexplained production clone of secret bytes.
- API token state still clones by handle/shared ownership, not by ordinary plaintext string duplication.
- Native connection setup still receives the password it needs.
- Config loading and native adapter tests still pass.

## 8. Cleanup requirement C4 — stronger native clipboard scrub regression tests

### Requirement

Evaluate whether project-owned native clipboard scrub behavior can be protected by a semantic native test in addition to the existing Python source-contract test.

The current source-contract test is acceptable as a guard, but it is brittle and textual. This pass should either:

1. add a small native/unit test hook that verifies the project-owned scrub-before-free/replacement/send-copy behavior without reading freed memory; or
2. document why a semantic native test would require unsafe allocator/test-only plumbing that is worse than the source-contract test, then tighten the source-contract test enough to cover all current scrub boundaries.

The test must not:

- read freed memory;
- depend on allocator reuse;
- log clipboard payloads;
- claim third-party or OS clipboard copies are scrubbed;
- weaken the existing native smoke/E2E coverage.

### Acceptance

- Replacement, destruction, and outbound send-copy scrub boundaries remain protected.
- Clipboard revision overflow still rejects before allocation/replacement.
- WorkerHandle text/clipboard E2E and privacy tests still pass.
- Documentation still states the exact ownership boundary.

## 9. Cleanup requirement C5 — temporary/recovery artifact audit

### Requirement

Audit repository contents for leftover temporary recovery files, workflows, patchers, diagnostic-only scripts, stale branch-consolidation evidence, or obsolete TODO references.

At minimum, check:

- `.github/workflows/`;
- `.github/` top-level helper scripts;
- `docs/` for obsolete recovery patcher instructions that now conflict with final master;
- tests that pin exact workflow action SHAs;
- Gitleaks ignore fingerprints and the release-policy contract.

Do not delete useful historical docs merely because they mention recovery. Delete only temporary executable machinery or stale instructions that could confuse future implementation.

### Acceptance

- No temporary `post-correctness-*` patcher workflow/script remains active.
- Permanent CI/Release workflows remain pinned and contract-tested.
- Gitleaks ignores remain exact fingerprints only; no wildcard ignore is introduced.
- Any retained recovery docs are clearly historical or still useful.

## 10. Documentation requirements

Update documentation only where behavior or evidence genuinely changes.

Expected documentation changes:

- final evidence addendum for prior hardening loop;
- this cleanup TODO completion evidence when the cleanup pass is complete;
- optional notes explaining secret clone policy if `SecretString` clone behavior changes;
- optional notes explaining native clipboard test strategy if semantic testing is rejected.

Do not duplicate large blocks of prior hardening documentation.

## 11. Validation requirements

Before final completion, the exact final repository tip must pass:

- `cargo fetch --locked`;
- `cargo fmt --all --check`;
- `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`;
- `cargo test --locked --workspace --all-features`;
- `RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps`;
- `python -m compileall -q tools/ci_status tests desktop/test-app`;
- `python -m unittest discover -s tests -p 'test_*.py' -v`;
- permanent shell syntax checks;
- desktop smoke;
- native adapter smoke;
- WorkerHandle input E2E;
- WorkerHandle text/clipboard E2E;
- authenticated HTTP TigerVNC E2E;
- controller image/Compose/persistence smoke;
- R13 Compose integration/E2E;
- Release Gates including static/supply-chain policy, full-history Gitleaks, ShellCheck/actionlint, Dockerfile/Compose validation, advisory/license/source/duplicate policy, auditable binary metadata verification, ASan, controller/core TSan, Miri, Trivy, CycloneDX SBOM, and VEX enforcement.

If local execution is unavailable, record the exact reason and defer only to exact-SHA permanent workflows. Do not mark unavailable commands as locally passed.

## 12. Final evidence requirements

The cleanup TODO must not be marked complete until it records:

```text
Starting SHA:
Implementation SHA:
Final documentation/evidence SHA, if separate:
Final repository-tip SHA:
CI run ID and conclusion:
Release Gates run ID and conclusion:

C1 final evidence addendum:
C2 established-WebSocket exhaustion test:
C3 secret clone hardening:
C4 native clipboard scrub test strengthening:
C5 temporary/recovery artifact audit:

Local validation:
Unavailable local validation, with reasons:
Deferred follow-ups:
```

## 13. Do-not-accept checklist

Do not accept the cleanup pass if any of the following are true:

- final evidence uses an older SHA, canceled run, partial run, or superseded run;
- CI or Release Gates are weakened or bypassed;
- WebSocket sequence exhaustion can wrap, reuse, saturate silently, panic, or hang an established client indefinitely;
- API tokens return to long-lived raw `Arc<str>` or ordinary string ownership;
- `SecretString` cloning remains implicit and unexplained if production byte duplication is not needed;
- clipboard text, typed text, key names, coordinates, tokens, passwords, framebuffer bytes, screenshot bytes, or query secrets are logged;
- native clipboard tests read freed memory or depend on allocator reuse;
- documentation overclaims third-party, OS, toolkit, allocator, LibVNCClient, VNC-server, reverse-proxy, swap, or crash-dump scrubbing;
- `HttpBackend` command metrics regain default zero behavior;
- the old queue-depth metric alias is reintroduced without an explicitly named external compatibility requirement;
- temporary patcher workflows or scripts remain active;
- `continue-on-error`, broad ignore, forced green checks, swallowed exit codes, or force pushes are used as completion evidence.
