# VNC Remote Control Server Post-Correctness Hardening Recovery Spec

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Recovery starting SHA: `100e4454634a577bf5ffd7b0dbc8913cf5a60cea`

Original hardening TODO: `docs/VNC_REMOTE_CONTROL_SERVER_POST_CORRECTNESS_HARDENING_TODO_2026-08-06.md`

Status: active recovery specification. This file is not completion evidence.

---

## 1. Purpose

A partial post-correctness hardening implementation was pushed directly to
`master` as eight commits after `acee2808bae8a97710c881525e78eb6f5d1d6abb`.
The partial series changed the controller configuration, API-token storage,
secret parsing, EventHub sequence handling, HTTP event route, backend metric
trait, HTTP tests, and worker reconnect tests. The native clipboard scrub work,
documentation, original TODO evidence, and exact-tip validation were not
completed.

This recovery pass must audit rather than trust the partial series, repair every
compile, test, behavior, privacy, or documentation defect it contains, complete
the native clipboard work, and leave one exact repository tip green in both CI
and Release Gates.

The recovery must not weaken any contract accepted by the completed correctness
review.

---

## 2. Authoritative baseline and scope

The accepted pre-hardening baseline is
`acee2808bae8a97710c881525e78eb6f5d1d6abb`. The recovery starts from
`100e4454634a577bf5ffd7b0dbc8913cf5a60cea`.

The recovery scope is limited to:

1. Audit and repair the partial H1, H2, H3, H4, and H6 implementation.
2. Complete H5 native clipboard/transient project-owned buffer scrubbing.
3. Add source, unit, route, privacy, documentation, and policy coverage required
   by the original hardening specification.
4. Update `SECURITY.md`, `docs/OPERATOR_GUIDE.md`, the original hardening TODO,
   and this recovery TODO with exact implemented boundaries and evidence.
5. Obtain CI and Release Gates success on the same exact final repository tip.

Unrelated features, API redesign, queue semantics changes, framebuffer wire
format changes, shutdown authority changes, compatibility aliases, broad
suppressions, and weakened gates are out of scope.

---

## 3. Recovery requirements

### R1. Audit the partial commit series

Inspect every diff from `acee2808...` through `100e4454...`. Do not mark a
partial item complete merely because source text exists. Confirm compilation,
ownership, public visibility, error propagation, test determinism, privacy, and
runtime behavior.

The audit must specifically check:

- whether the new API-token type creates ordinary secret copies through public
  conversion helpers;
- whether successful and rejected secret parsing has one clear owner and
  deterministic live-buffer scrubbing;
- whether EventHub exhaustion closes deterministically without wrap, reuse,
  panic, log flooding, or leaked WebSocket permits;
- whether the WebSocket route returns the established bounded JSON error
  envelope before upgrade;
- whether all `HttpBackend` implementations explicitly supply command metrics;
- whether the CR12 positive control proves the same observation path and does not
  contain false assumptions about framebuffer canonicalization or revisions.

### R2. EventHub fail-closed contract

Event sequence allocation must return an explicit error at exhaustion. It must
never wrap, reset, reuse, saturate silently, panic, or continue publishing
ambiguous events. The first exhaustion transition may emit one bounded,
payload-free diagnostic; repeated attempts must not create unbounded log spam.

Initial WebSocket snapshot exhaustion must fail before upgrade with HTTP 503 and
a stable, bounded JSON error code. A subscription permit acquired before that
failure must be released immediately. Bridge publication after exhaustion must
stop publishing events deterministically.

### R3. API-token secret contract

The long-lived API token must be held by an explicit non-`Debug`, non-`Display`
secret type. Cloning controller state may clone an owning handle but must not
copy token bytes. Production constructors and conversions must not provide a
convenient path from an ordinary `Arc<str>` that silently creates another
long-lived plaintext allocation.

Authentication behavior must remain unchanged and use constant-time comparison:
missing, malformed, query, empty, and incorrect tokens fail; a valid Bearer
header succeeds. Logs, metrics, debug output, error envelopes, and events must
not contain token content.

### R4. Secret-file rejection scrubbing

Once secret bytes are read, every parser-owned byte allocation must be scrubbed
before release on invalid UTF-8, empty-after-CR/LF-trim, embedded NUL, or future
validation failure. Successful parsing must transfer ownership into the secret
type without unnecessary ordinary `String` copies. Tests may instrument live
buffers or helper state but must not inspect freed memory.

### R5. Native clipboard/transient buffer scrubbing

In `crates/libvnc-adapter/native/vnc_shim.c`, project-owned clipboard data must
be scrubbed with the existing volatile-byte scrub primitive before replacement
and destruction. An outbound clipboard send copy must be scrubbed before free
on both success and failure paths.

The implementation must track the allocation length needed for scrubbing rather
than relying on `strlen` after data may contain a terminator. It must not change
RFB clipboard semantics or log clipboard content.

Tests or source contracts must fail if these project-owned allocations are freed
without a preceding scrub. Documentation must state that this guarantee does
not cover Rust response bodies, toolkit/OS clipboard managers, the VNC server,
LibVNCClient-owned copies, or allocator residuals unless direct evidence exists.

### R6. Required metric trait methods

`HttpBackend::command_submissions_in_flight()` and
`HttpBackend::command_queue_capacity()` must be required methods. Production and
all mocks must supply intentional values. No default zero, `unwrap_or(0)`, or old
queue-depth alias is allowed.

### R7. Documentation and evidence

Update security and operator documentation for:

- API-token secret ownership and remaining process-memory limitations;
- secret-file rejection scrubbing;
- EventHub exhaustion behavior;
- native clipboard scrub scope and third-party boundary;
- CR12 positive-control evidence as a test-only change;
- any stable HTTP error code added by the recovery.

Update the original hardening TODO only after evidence exists. The recovery TODO
must record starting SHA, implementation SHA, final tip, validation commands,
workflow run IDs, conclusions, and explicit deferrals.

---

## 4. Validation contract

Run all available local repository checks. Where the execution environment cannot
clone or execute the repository, record that limitation and use permanent GitHub
workflows as the authoritative compiler/test environment.

The same exact final repository tip must pass:

- CI repository quality and secured desktop/native jobs;
- Release Gates static/supply-chain policy;
- full-history Gitleaks;
- ShellCheck and actionlint;
- Dockerfile and Compose validation;
- cargo policy and auditable binary verification;
- ASan;
- controller-api and remote-desktop-core TSan;
- Miri boundary;
- Trivy, SBOM, and VEX checks.

Queued, canceled, skipped, superseded, partial, or older-SHA runs are not
completion evidence.

---

## 5. Do-not-accept rules

Do not accept:

- unchecked assumptions about the eight partial commits;
- panic, `unwrap`, or `expect` on EventHub sequence exhaustion;
- sequence reset, wrap, reuse, or saturation;
- query-token or empty-token fallback;
- ordinary long-lived `Arc<str>` API-token storage;
- invalid UTF-8 secret bytes dropped without explicit scrub;
- native clipboard free/replacement without scrub;
- broad claims that all clipboard or secret copies are zeroized;
- default-zero metric trait methods;
- sleep-only negative evidence;
- sensitive payload logging;
- broad lint/test/security suppression;
- `continue-on-error`, ignored exit codes, force pushes, or older-SHA evidence.
