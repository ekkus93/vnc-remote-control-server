# R8 Worker Integration Candidate Evidence

Date: 2026-08-04

## Implementation

- Implementation commit: `6997362414336b8ef727c1a5cbabdbb1bc1c4b94`
- Clippy/test-contract repair: `df911e883bff6e52a78b4ddbf00d9d73067ffcf1`
- Branch policy: direct `master`; no implementation branch or pull request
- Temporary validation refs: removed after `master` fast-forward
- Temporary workflows and transformation scripts: absent from final tree

## Implemented contract

- The production worker owns one `InputController` on its existing single native thread.
- `InputSink` delegates pointer and key events to the worker-owned `WorkerSession`.
- Pointer movement, explicit button state, click, double-click, vertical scrolling, explicit key state, and chords route through `InputController`.
- Pointer-bearing commands validate against the canonical complete current framebuffer dimensions before native mutation.
- Horizontal scrolling remains explicitly rejected because interoperability is not yet verified.
- Text input remains explicitly deferred to R9.
- Disconnect and shutdown perform best-effort release of tracked buttons and keys before native session destruction.
- Command completion returns native input failures to the caller.

## Pre-publication validation

Both validated candidates were produced only after all of the following succeeded with Rust `1.97.1`:

```text
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-targets --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
```

Worker-level tests cover:

- full button-mask preservation across compound commands;
- pointer/click/scroll/chord ordering through the worker-owned session;
- invalid-coordinate rejection before native mutation;
- propagation of partial native input failure after release retry;
- release of tracked mouse and keyboard state during orderly shutdown.

## Authoritative CI history

Run `30893582994` on SHA `7748ec0acb97763aba315b66126608a031bffa80` proved the unchanged live desktop/native path remained green, but the quality job correctly failed on two test-contract defects:

- an unused test-only `DisplayInfo` import;
- an assertion using nonexistent `DesktopError::CoordinateOutOfRange` instead of the actual `DesktopError::InvalidCoordinate` contract.

The defects were fixed at their source without warning suppression. This evidence update intentionally triggers a new ordinary `CI` run. Exact final run and job identifiers are pending completion and must be recorded before R8 worker integration is considered closed.
