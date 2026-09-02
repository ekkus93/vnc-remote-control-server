# VNC Remote Control Server — Code Review Remediation V2 Specification

**Date:** 2026-09-01  
**Repository:** `ekkus93/vnc-remote-control-server`  
**Reviewed baseline:** `2506686ecdd77ddbfcc106d0109d6f7198233808`  
**Companion TODO:** `docs/VNC_REMOTE_CONTROL_SERVER_CODE_REVIEW_REMEDIATION_V2_TODO_2026-09-01.md`

## Purpose

This is a second remediation pass after the 2026-08-31 code-review remediation. The earlier pass remains valid historical evidence, but a later independent review found five additional gaps plus one adjacent silent-failure issue:

1. native input failures can leave keyboard/pointer state uncertain while the same VNC session remains reusable;
2. Release Gates used `dtolnay/rust-toolchain@stable`, a mutable third-party Action reference;
3. command IDs could be consumed before outcome retention was reserved, allowing a never-retained numerical gap to later look `Expired`;
4. native framebuffer revision exhaustion could fail to propagate through polling and leave stale framebuffer authority;
5. accepted HTTP connections had no explicit process-level concurrency cap;
6. termination-signal listener failures were silently collapsed into normal shutdown.

MCP implementation remains out of scope and blocked until this V2 remediation is fully signed off.

## Non-negotiable invariants

- A failed native input send is not proof that the remote side observed no effect.
- Any input failure with ambiguous remote effect taints the current VNC session.
- A tainted session cannot process a later input command.
- Cleanup is bounded and may neutralize tracked input, but the original failed mutation is never replayed automatically.
- Cleanup/reconnect success never overwrites the original command failure.
- `Found`, `Expired`, and `Unknown` retain exact meanings: `Expired` is only for a record known to have existed and later been evicted.
- Monotonic ID/revision exhaustion fails closed and never wraps into stale-current state.
- All externally reachable resource classes are explicitly bounded, including accepted HTTP connections.
- Every permanent third-party GitHub Action is pinned to a full immutable commit SHA.
- No remediation may weaken CI, Release Gates, scanners, VEX enforcement, sanitizer/Miri coverage, secret scanning, or test strictness.

## V2-R0 — Baseline and preservation

Work starts from exact `master` `2506686ecdd77ddbfcc106d0109d6f7198233808`. Preserve bearer authentication, constant-time token comparison, file-backed secret rules, raw-VNC isolation, bounded queues, command unknown-outcome semantics, WebSocket limits, screenshot bounds, shutdown bounds, and all existing security/release gates. Prior remediation evidence is historical; later corrections must be append-only or explicitly superseding, never rewritten as if previous validation did not occur.

## V2-R1 — Input uncertainty and session quarantine

Replace the pointer-only uncertainty concept with one authoritative aggregate input certainty state (`Known`/`Uncertain` or equivalent).

Every native input send path must explicitly account for ambiguous delivery:

- pointer movement;
- explicit button transitions;
- click/double-click press and release;
- wheel press/release;
- key press/release;
- chord press/release and partial cleanup;
- typed-text press/release and cleanup.

Unless the native/transport contract proves non-delivery, a send failure makes input state uncertain. The worker then:

1. preserves the original command error;
2. performs only bounded best-effort neutralizing cleanup;
3. records cleanup failures without payloads;
4. invalidates/drops the current VNC session;
5. abandons unresolved local tracked input only after that session cannot be reused;
6. reconnects through the existing bounded state machine;
7. prevents later input from executing on the tainted session.

The post-command quarantine policy should be centralized rather than implemented only in the scroll arm.

Required regression coverage includes failed pointer move, button press/release, click press/release, double-click, wheel release, key-down, key-up, partial chord and cleanup, typed-text cleanup, cleanup double failure, and proof that the next queued mutation cannot execute on the tainted session.

## V2-R2 — Immutable GitHub Actions

Pin `dtolnay/rust-toolchain` to a reviewed 40-hex commit SHA while retaining the explicit Rust `1.97.1` toolchain. Add a generic workflow contract that scans all permanent `.yml`/`.yaml` workflows and rejects every non-local `uses:` reference that is not a full commit SHA. Local `./...` Actions remain permitted.

## V2-R3 — Truthful command outcome identity

Command identity allocation and outcome-capacity reservation must behave atomically from the caller's perspective. If outcome capacity is full of unresolved work, the submission fails before consuming a command ID. A never-retained identifier can therefore never later be inferred as `Expired`.

Add deterministic tiny-capacity tests proving:

- capacity failure does not advance the sequence;
- the never-retained ID remains `Unknown`;
- once capacity is available, that same next ID is retained normally;
- known terminal evictions still report `Expired`.

HTTP/OpenAPI/Python command-status semantics must remain unchanged except for correcting the misclassification.

## V2-R4 — Native framebuffer revision exhaustion

Native framebuffer revision exhaustion must use a machine-readable callback/native failure that propagates through `vrc_client_poll()` even if the outer LibVNC message handler otherwise returns success. Rust maps it to a typed native error; the worker invalidates framebuffer authority, drops the affected session, and reconnects. No previous framebuffer may remain `Current` after exhaustion.

Provide a test-only hook or helper so revision `UINT64_MAX` behavior can be exercised deterministically. Cover the native helper, poll propagation, Rust mapping, stale-state invalidation, and reconnect recovery.

## V2-R5 — HTTP connection concurrency bound

Add `VRC_HTTP_MAX_CONNECTIONS` with an explicit default, nonzero minimum, and finite maximum. The runtime must use process-owned concurrency accounting (preferably a Tokio semaphore). Each live connection task owns exactly one permit until the task actually exits.

The saturation policy must be deterministic and must not spawn unbounded helper tasks. Permit recovery must be covered for clean close, peer failure, task cancellation/panic where applicable, graceful shutdown, and shutdown abort. A saturated pool must not prevent bounded shutdown.

## V2-R6 — Silent-failure/fallback audit

Repeat the cross-cutting audit over changed and adjacent production code for:

- `let _ =` and ignored `Result`s;
- `.ok()`;
- broad wildcard error collapsing;
- `unwrap_or*` operational fallbacks;
- broad Python exceptions;
- shell `|| true` / `set +e`;
- retries around side-effecting mutations;
- cleanup retries;
- stale cache/framebuffer/clipboard fallbacks;
- sequence exhaustion;
- detached tasks/threads;
- poison recovery;
- ignored channel sends;
- timeout paths that abandon work;
- workflow `continue-on-error`, mutable Actions, or scanner bypasses.

Every surviving ignored production result must be classified as terminal notification, best-effort cleanup after guaranteed invalidation, redundant non-authoritative wake-up, test-only behavior, or a defect to remove/propagate. Non-obvious accepted ignores require nearby rationale and tests when practical.

The discovered process termination listener failure is in scope: failure must be logged, bounded shutdown still occurs, and process completion must report failure rather than silently succeed.

## V2-R7 — Documentation and evidence reconciliation

Update living documentation for input-session quarantine, exact command-status semantics, HTTP connection capacity, immutable Action policy, and non-retry-safe accepted mutation failures. Preserve V1 evidence while explicitly noting that the later V2 review found R9/R14/R15 overclaims regarding the completeness of the fallback audit.

MCP remains deferred until V2 final sign-off.

## V2-R8 — Validation

Blocking validation includes the repository's complete Rust, Python, shell/workflow, security/supply-chain, native, image, Compose, and E2E sets. At minimum this includes fmt, Clippy `-D warnings`, workspace tests, rustdoc `-D warnings`, Ruff, Pylint, mypy, Python tests, `bash -n`, ShellCheck, actionlint, cargo-deny, full-history Gitleaks, auditable-binary verification, Docker/Compose checks, ASan, TSan, Miri, Trivy inventories, CycloneDX SBOMs, exact CRITICAL VEX enforcement, native/worker/HTTP E2E, and R13.

The ChatGPT sandbox's missing Rust/container environment is not grounds to weaken checks; GitHub Actions/self-hosted runners provide authoritative proof where required.

## V2-R9 — Exact candidate and merged-master gates

Required order:

1. push the complete candidate;
2. require regular CI success on that exact SHA;
3. require Release Gates success on that exact SHA;
4. merge only after both are green;
5. record exact merged `master` SHA;
6. require fresh regular CI success on that exact `master` SHA;
7. require fresh Release Gates success on that exact `master` SHA.

A previous SHA's green run cannot substitute for the current candidate.

## V2-R10 — Evidence and sign-off

Final V2 evidence records the starting SHA, candidate SHA, merged SHA, all candidate/master CI and Release Gate run IDs, files changed, regression tests for each finding, input quarantine policy, command `Unknown`/`Expired` policy, framebuffer exhaustion behavior, HTTP connection bounds, immutable Action proof, fallback-audit results, rationale for surviving ignored results, VEX status, and explicit confirmation that no release-critical gate was weakened.

Final sign-off is permitted only after every applicable TODO checkbox is re-reviewed against actual final source/tests/workflows/evidence, not commit messages.

## Acceptance criteria

V2 is complete only when:

1. ambiguous native input failure cannot leave a reusable session with unknown remote input state;
2. no later mutation executes on that tainted session;
3. original failed mutations remain failed and are never automatically replayed;
4. all permanent third-party Actions are immutable-SHA pinned;
5. never-retained command IDs cannot report `Expired`;
6. native framebuffer revision exhaustion propagates and invalidates stale authority;
7. accepted HTTP connections are explicitly bounded;
8. the fallback audit has no unexplained correctness-sensitive ignored results;
9. documentation/evidence accurately preserve history and record V2 corrections;
10. exact candidate CI and Release Gates pass;
11. exact merged-master CI and Release Gates pass;
12. all TODO closure claims are supported by final code/tests/evidence;
13. MCP remains deferred until this sign-off is complete.
