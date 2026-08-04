# R9 Worker Text and Clipboard Candidate Evidence

Date: 2026-08-04

## Scope

This evidence record covers the first R9 implementation slice at the production worker boundary. It does not yet close the complete R9 milestone because real TigerVNC text and clipboard end-to-end tests remain to be added.

## Implementation commit

```text
Code commit: d35d15d06505891385c9d947c6345d8e07022a51
Commit message: Implement R9 worker text and clipboard state
```

The implementation commit was generated and validated as one atomic candidate. It also removed all temporary R9 candidate generators and workflows from the final tree. The temporary candidate tag was deleted after `master` fast-forwarded to the validated commit.

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
- Accepted values are sent through the existing safe LibVNCClient adapter path.
- Clipboard payloads are absent from `WorkerCommand` debug output; only byte length is exposed.

### Inbound clipboard

- The worker polls the adapter's copied UTF-8 clipboard value and native revision.
- The public worker client exposes a last-known `ClipboardSnapshot` containing text, process-local revision, and update timestamp.
- The process-local clipboard revision is monotonic and independent of native revision numbering.
- Payload-free `ClipboardRevision` events are published only for accepted new clipboard values.
- Clipboard text is never included in events.
- Invalid UTF-8 or invalid clipboard content becomes a visible protocol failure/event without exposing payload bytes.
- The last-known valid clipboard snapshot remains readable across a disconnect; native revision bookkeeping resets for the next session.

## Unit and contract tests

The isolated candidate suite proves:

- text order for printable ASCII, newline, and tab;
- complete preflight before unsupported text;
- text key-release retry and error propagation;
- worker routing for text and outbound clipboard;
- embedded-NUL clipboard rejection before native mutation;
- inbound clipboard snapshot creation;
- process-local clipboard revision event publication;
- debug redaction for text and clipboard command payloads;
- every existing worker, framebuffer, screenshot, input, adapter, and core test remains green.

## Isolated validation

```text
Workflow: R9 Worker Candidate V2
Run: 30932049479
Validated commit: d35d15d06505891385c9d947c6345d8e07022a51
Temporary tag: removed
```

The candidate passed:

```text
cargo fmt --all

git diff --check

cargo clippy --locked --workspace --all-targets --all-features -- -D warnings

cargo test --locked --workspace --all-features

RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps

python -m unittest discover -s tests -p 'test_*.py' -v
```

No lint allowance, warning suppression, skipped test, downgraded gate, or failure ignore was added.

## Authoritative CI

Pending the ordinary `master` push created by this evidence record.

## Remaining R9 boundary

Before R9 can close, the repository still needs real TigerVNC tests through `WorkerHandle` for:

- supported text entering the deterministic application exactly;
- unsupported text producing no partial mutation;
- outbound clipboard set followed by desktop paste;
- desktop copy followed by inbound worker clipboard snapshot;
- clipboard revision and timestamp behavior on the live server;
- proof that typed text and clipboard values remain absent from captured logs and events;
- documented Unicode interoperability findings and an explicit v0.1 support decision.
