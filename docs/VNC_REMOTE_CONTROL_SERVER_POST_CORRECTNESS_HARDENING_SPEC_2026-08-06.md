# VNC Remote Control Server Post-Correctness Hardening Spec

Date: 2026-08-06

Repository: `ekkus93/vnc-remote-control-server`

Reviewed baseline SHA: `96836f7ff964813fb727a1f7407fb0b1f448b738`

Status: proposed follow-up hardening pass. This file is not completion evidence.

---

## 1. Purpose

The correctness-review Ralph Loop completed the main worker, shutdown, framebuffer,
privacy, measurement, and release-gate work. This specification defines a smaller
follow-up pass for residual hardening discovered during the post-completion code
review.

The goal is not to reopen or relitigate the completed correctness review. The goal
is to remove the remaining evidence gap and tighten a few defensive edges before
future feature work builds on the current architecture.

This pass must preserve the accepted v0.1 behavior unless this file explicitly
requires a change.

---

## 2. Baseline facts

The current accepted baseline has these properties:

- `docs/VNC_REMOTE_CONTROL_SERVER_CORRECTNESS_REVIEW_FIX_TODO_2026-08-06.md`
  is complete.
- Final reviewed repository tip: `96836f7ff964813fb727a1f7407fb0b1f448b738`.
- Final CI and Release Gates were successful on that exact tip.
- The worker no longer depends on normal command queue capacity for shutdown.
- Pre-`Connected` stalls reconnect without `Degraded`, fatal exit, or worker
  termination.
- Native framebuffer bytes are explicitly negotiated as `[R,G,B,X]` and
  canonicalized to RGBA with opaque alpha.
- The misleading queue-depth metric was renamed to submissions-in-flight.
- Project-owned VNC password copies are scrubbed; LibVNCClient-owned residual is
  documented as outside the project-owned scrub guarantee.

This follow-up must not weaken those accepted properties.

---

## 3. Scope

### H1. Repair the CR12 evidence gap

`crates/controller-api/src/worker/tests/reconnect.rs` contains
`mismatched_native_frame_never_reaches_connected`. The test uses causal poll
progress, which is good, but it does not include the positive control requested
by CR12.

Requirement:

- Strengthen the mismatched-frame negative proof with a positive control.
- The positive control must prove that the same observation path can detect a
  successful complete frame and a transition to `Connected` when the fixture is
  made valid.
- Do not replace this with elapsed-time sleep assertions.
- Do not weaken the existing negative assertions that a mismatched native frame
  never reaches `Connected`, does not set `fatal_exit`, and does not publish a
  current framebuffer.

Acceptable implementation patterns:

1. Extend the existing fixture so the first connection/poll path presents a
   mismatched display/framebuffer revision, then a later fixture phase presents a
   matching complete frame. The test should first prove the mismatch does not
   connect and then prove the valid phase does connect.
2. Split into two tests using the same harness helpers: one negative test for
   mismatch and one explicit positive-control test for a matching frame using the
   same causal poll-progress observation mechanism.

The positive control must be close enough to the negative test that a broken
observation path would fail both surfaces.

### H2. Replace EventHub sequence exhaustion panic with fail-closed behavior

`crates/controller-api/src/events.rs` currently treats event sequence exhaustion
as an intentional panic. Reusing or wrapping a sequence is unacceptable, but a
panic in event infrastructure is still a harsh failure mode.

Requirement:

- Replace the panic path with explicit fail-closed handling.
- The sequence must never wrap or be reused.
- The bridge and WebSocket request paths must not panic on sequence exhaustion.
- Sequence exhaustion must be logged with a bounded, payload-free diagnostic.
- Authenticated WebSocket clients must either receive no further events and be
  closed or receive a bounded service failure path. Do not emit malformed or
  duplicate-sequence events.
- If an initial snapshot event cannot be created because the sequence is
  exhausted, the HTTP/WebSocket route must fail explicitly rather than panic.

Implementation constraints:

- Do not put command payloads, clipboard text, pixels, bearer tokens, passwords,
  request bodies, or framebuffer bytes in the diagnostic.
- Do not introduce an unbounded queue, unbounded retry loop, or sleep-based
  recovery.
- Do not hide exhaustion by saturating at `u64::MAX` or by resetting to zero.

Expected tests:

- A unit test that forces the internal sequence to `u64::MAX` and proves event
  creation returns an error or closed condition without panic.
- A WebSocket or route-level test proving the initial snapshot path fails with a
  bounded response if the hub cannot allocate a sequence.
- A regression test proving normal event sequences remain strictly increasing.

### H3. Move API bearer token storage to an explicit secret type

`ControllerConfig` currently stores the API token as `Arc<str>` after reading it
from a zeroizing file-backed secret. The original `SecretString` is scrubbed, but
the long-lived API-token copy is not itself a secret type.

Requirement:

- Store the API bearer token in an explicit non-`Debug`, non-`Display` secret
  wrapper rather than raw `Arc<str>`.
- Preserve constant-time comparison semantics for `Authorization: Bearer ...`.
- Preserve current public authentication behavior and error envelopes.
- Preserve redacted access logging.
- Avoid copying the token into ordinary `String` or `Arc<str>` except at a
  tightly scoped boundary that is itself scrubbed before release.

Implementation notes:

- Reuse `libvnc_adapter::SecretString` only if the ownership and API shape remain
  sensible outside the native adapter. Otherwise introduce a controller-owned
  `SecretString`/`ApiToken` abstraction in `controller-api` and migrate both API
  token and VNC secret loading through clear types.
- `bearer_matches` should accept a borrowed secret view and compare candidate
  bytes with `subtle::ConstantTimeEq` without logging either side.
- Tests must prove `ControllerConfig` debug output and access logs still redact
  the token.

### H4. Scrub secret-file raw bytes on invalid UTF-8 and other rejection paths

`SystemSecretReader` reads secret files as bytes and converts them to UTF-8. If
UTF-8 parsing fails, the raw byte vector may be dropped without explicit
scrubbing.

Requirement:

- Ensure raw secret bytes are scrubbed before drop on every rejection path after
  file contents have been read.
- Covered rejection paths must include invalid UTF-8, empty content after CR/LF
  trimming, embedded NUL, overlarge content if contents were read, and any future
  validation failure in this parsing function.
- Preserve current secret-file metadata and permission checks.
- Preserve redaction-safe error messages.

Implementation constraints:

- Do not read files larger than the existing maximum secret size.
- Do not include secret contents in error messages, logs, panics, test names, or
  artifacts.
- Do not add a freed-memory inspection test.

Expected tests:

- A deterministic test with a sentinel byte vector that forces an invalid UTF-8
  parse failure and proves the live buffer is scrubbed before the error returns.
- A test for embedded NUL or empty-after-trim rejection that also verifies scrub
  behavior without reading freed memory.

If direct observation through `SystemSecretReader` would require exposing too
much internals, factor parsing into a small injectable helper that accepts an
owned byte buffer and reports scrub state before returning.

### H5. Decide and implement native clipboard/transient sensitive-buffer cleanup

The completed correctness pass scoped scrubbing to VNC passwords. Clipboard text
and typed text can also be sensitive, but they are product data and are currently
handled differently from credentials.

Requirement:

- Make an explicit policy decision for native clipboard and transient native text
  buffers.
- At minimum, scrub project-owned C clipboard buffers before replacement and
  destruction.
- Scrub outbound clipboard send copies before free.
- Do not claim third-party library-owned clipboard or text copies are scrubbed
  without evidence.
- Document the exact boundary: project-owned buffers versus toolkit, OS, VNC
  server, LibVNCClient, or allocator residuals.

Source targets:

- `crates/libvnc-adapter/native/vnc_shim.c`
- `crates/libvnc-adapter/src/lib.rs`
- `SECURITY.md`
- `docs/OPERATOR_GUIDE.md` or release notes if user-visible behavior changes.

Expected tests:

- A source-level or native-unit regression that fails if `client->clipboard` is
  freed or replaced without a preceding scrub call.
- A source-level or native-unit regression that fails if outbound clipboard send
  copies are freed without a preceding scrub call.
- A documentation test or policy test that prevents broad claims about
  third-party-owned buffers.

Do not use freed-memory reads as proof.

### H6. Remove silent default metric implementations from `HttpBackend`

`HttpBackend` has default implementations for
`command_submissions_in_flight()` and `command_queue_capacity()` that return
zero. Production overrides them, but the defaults make it easy for a future mock
or alternate backend to silently report false metrics.

Requirement:

- Make both methods required trait methods.
- Update every test/mock backend to provide explicit values.
- Preserve production metric names and semantics.
- Add a regression or compile-time consequence that prevents omission from
  compiling.

Implementation constraints:

- Do not change public HTTP metric names in this task.
- Do not reintroduce aliases for the old metric name.
- Do not use default zeros, `unwrap_or(0)`, or fallback values for production
  queue/submission metrics.

---

## 4. Non-goals

This pass must not do the following:

- Reopen or rewrite the completed correctness-review TODO as incomplete.
- Change the public HTTP API surface except where H2 requires a bounded failure
  path for sequence exhaustion.
- Add framebuffer hot-path optimization.
- Change the accepted `[R,G,B,X]` native wire-format contract.
- Change shutdown authority back to queue-based shutdown.
- Add direct event-bridge wakeup unless it is explicitly required by a future
  performance or shutdown specification.
- Add compatibility aliases for old metric names.
- Claim total secret zeroization for third-party-owned buffers.
- Introduce broad `allow`, `ignore`, `continue-on-error`, suppressed exit codes,
  force pushes, or older-SHA evidence.

---

## 5. Validation requirements

Run all available local checks before pushing:

```bash
cargo fetch --locked
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
python -m unittest discover -s tests -p 'test_*.py' -v
```

Run Docker/VNC checks when available:

```bash
tests/desktop/run.sh
tests/native/run.sh
tests/worker-e2e/run.sh
tests/worker-text-clipboard-e2e/run.sh
tests/http-e2e/run.sh
tests/compose/run.sh
tests/integration/run.sh
```

Permanent validation on the exact final SHA must include:

- CI success.
- Release Gates success.
- Static policy gates.
- Full-history Gitleaks.
- ShellCheck and actionlint.
- Dockerfile and Compose validation.
- cargo-deny.
- cargo-auditable metadata verification.
- ASan adapter coverage.
- controller-api TSan coverage.
- remote-desktop-core TSan and Miri coverage.
- image vulnerability, SBOM, and VEX gates.

Unavailable local surfaces must be listed with exact reasons. Do not mark an
unavailable check as passed.

---

## 6. Acceptance criteria

This pass is complete only when:

- The CR12 mismatched-frame evidence gap is closed with a real positive control.
- EventHub sequence exhaustion cannot panic, wrap, reuse, or silently drop into an
  ambiguous state.
- API bearer-token storage uses an explicit secret type and preserves constant
  time comparison.
- Secret-file parser rejection paths scrub live raw bytes before return.
- Project-owned native clipboard/transient text buffers are scrubbed or the
  boundary is explicitly documented with tests enforcing the policy.
- `HttpBackend` can no longer silently default command metric values to zero.
- All new behavior has targeted regression tests.
- Existing worker, shutdown, framebuffer, HTTP, WebSocket, privacy, ETag, and
  release-gate behavior remains green.
- CI and Release Gates pass on the same exact final SHA.

---

## 7. Final evidence requirements

The final implementation report must record:

- Starting SHA.
- Implementation SHA.
- Final documentation SHA if separate.
- Final repository-tip SHA.
- CI run ID and conclusion for the final exact SHA.
- Release Gates run ID and conclusion for the final exact SHA.
- Per-item summary for H1-H6.
- Explicit list of any intentionally deferred follow-ups.

Do not claim that a commit embeds its own future SHA or future workflow run IDs.
