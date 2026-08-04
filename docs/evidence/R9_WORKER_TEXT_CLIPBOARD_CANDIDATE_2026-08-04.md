# R9 Worker Text and Clipboard Evidence

Date: 2026-08-04

## Scope

This evidence record covers the production worker text and clipboard implementation plus its real TigerVNC end-to-end proof. The v0.1 public text contract remains deliberately limited to printable ASCII plus newline, carriage return, and tab. Broader Unicode text entry is not enabled without separate interoperability evidence.

## Implementation commits

```text
Worker text/clipboard state: d35d15d06505891385c9d947c6345d8e07022a51
Worker-state evidence: 80ecf2eb348daeb6e17920481e7af8d3bd36a888
TigerVNC E2E driver: f2858598f9ad714ca7b73b12a473a7af152a6bf3
Clipboard-event syntax repair: b743f9c457ba8c283ca35287549cc92381f72b1b
TigerVNC E2E harness: 519970346558c69d087bc5eebd408ec2b858a03f
Permanent E2E contracts: d69d48fc63d5e7e978af92daf6116bcfeffb005d
CI wiring: 2b73d39557d038ed2dc10b6d50d20d1e837d9cf9
Exact error-taxonomy repair: c02425252c852481f1d810133368b142ed14797e
```

The worker-state implementation was generated and validated as one atomic candidate. All temporary R9 candidate generators, workflows, and tags were removed from the final tree.

## Implemented contract

### Text input

- The complete string is validated before the first native key event.
- The v0.1 supported range is printable ASCII plus newline, carriage return, and tab.
- Newline and carriage return map to `ENTER`.
- Tab maps to `TAB`.
- Printable ASCII maps to printable symbolic keys.
- Each character is sent as key down followed by key up on the single-owner native worker thread.
- A failed release is retried best-effort and the original failure is returned.
- Unsupported or oversized text produces no partial native mutation.
- Text payloads are absent from `WorkerCommand` debug output; only byte length is exposed.

### Outbound clipboard

- The worker validates the complete clipboard value before native mutation.
- Oversized values and embedded NUL are rejected.
- Accepted values are sent through the safe LibVNCClient adapter path.
- Clipboard payloads are absent from `WorkerCommand` debug output; only byte length is exposed.

### Inbound clipboard

- The worker polls the adapter's copied UTF-8 clipboard value and native revision.
- `WorkerClient::clipboard_snapshot` exposes the last valid `ClipboardSnapshot`, including text, process-local revision, and update timestamp.
- The process-local clipboard revision is monotonic and independent of native revision numbering.
- Payload-free `ClipboardRevision` events are published only for accepted new clipboard values.
- Clipboard text is never included in events.
- Invalid UTF-8 or invalid clipboard content becomes a visible protocol failure/event without exposing payload bytes.
- The last-known valid clipboard snapshot remains readable across a disconnect; native revision bookkeeping resets for the next session.

## Unit and contract tests

The Rust and Python suites prove:

- text order for printable ASCII, newline, and tab;
- complete preflight before unsupported text;
- text key-release retry and error propagation;
- worker routing for text and outbound clipboard;
- embedded-NUL clipboard rejection before native mutation;
- inbound clipboard snapshot creation;
- process-local clipboard revision event publication;
- debug redaction for text and clipboard command payloads;
- the live driver uses `DesktopWorker` and `WorkerClient`, never a direct native client;
- the authoritative CI workflow retains the real TigerVNC text/clipboard test.

## Real TigerVNC end-to-end contract

The permanent CI harness starts the project-owned Debian/XFCE/TigerVNC desktop and exercises this path:

```text
WorkerClient
  -> bounded worker command queue
  -> single-owner native worker thread
  -> InputController / clipboard worker state
  -> LibVNCClient
  -> TigerVNC Xvnc
  -> deterministic Tk application / X clipboard
  -> exact state and revision verification
```

The live test proves:

- supported text `worker text 123` enters the deterministic application exactly;
- unsupported text containing `U+2603` is rejected as `UnsupportedTextCharacter` after complete preflight;
- the unsupported command does not append any partial text;
- no keys remain pressed;
- outbound clipboard text sent through `WorkerClient` becomes the desktop X clipboard value;
- a desktop-owned X clipboard value reaches the worker as an inbound `ClipboardSnapshot`;
- the inbound snapshot has a positive process-local revision;
- the matching payload-free `ClipboardRevision` event is observed;
- the VNC password, supported text fixture, rejected text fixture, outbound clipboard fixture, and inbound clipboard fixture are absent from worker and desktop logs.

## Isolated worker-state validation

```text
Workflow: R9 Worker Candidate V2
Run: 30932049479
Validated source commit: d35d15d06505891385c9d947c6345d8e07022a51
Temporary tag: removed
```

The isolated candidate passed:

```text
cargo fmt --all

git diff --check

cargo clippy --locked --workspace --all-targets --all-features -- -D warnings

cargo test --locked --workspace --all-features

RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps

python -m unittest discover -s tests -p 'test_*.py' -v
```

## Exact-green authoritative CI

```text
SHA: c02425252c852481f1d810133368b142ed14797e
Run: 30933078815
Attempt: 1
Conclusion: completed / success
Quality job: 92072327484
Desktop/native/E2E job: 92072327606
Artifact ID: 8901968713
Artifact name: ci-evidence-30933078815
```

The quality job passed formatting, warning-denied Clippy, all Rust tests, warning-denied rustdoc, Python/workflow contract tests, shell syntax checks, and evidence generation.

The real-container job passed:

- secured desktop image smoke;
- live LibVNCClient adapter smoke;
- complete R8 WorkerHandle input E2E;
- WorkerHandle failure-diagnostics and redaction self-test;
- WorkerHandle TigerVNC text and bidirectional clipboard E2E.

No lint allowance, warning suppression, skipped required test, downgraded gate, or failure ignore was added.

## Unicode boundary

The v0.1 text API remains ASCII-only by design. The live test proves a representative non-ASCII character is rejected before native mutation. Direct TigerVNC Unicode-keysym interoperability is a separate investigation and must not silently broaden the supported API contract. Clipboard remains the verified UTF-8 transport for arbitrary Unicode text values, subject to the clipboard size and embedded-NUL policies.

## R9 closure boundary

The production R9 text and clipboard behavior required for v0.1 is implemented and exact-green. The next implementation milestone is R10: typed configuration and the authenticated HTTP API.
