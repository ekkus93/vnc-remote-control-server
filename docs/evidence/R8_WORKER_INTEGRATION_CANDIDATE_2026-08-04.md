# R8 Worker Integration Evidence

Date: 2026-08-04

## Implementation

- Implementation commit: `6997362414336b8ef727c1a5cbabdbb1bc1c4b94`
- Clippy/test-contract repair: `df911e883bff6e52a78b4ddbf00d9d73067ffcf1`
- Exact-green code/evidence candidate: `55fb359a5b307e49693bde8041a1e7298264bfd0`
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

## Validation commands

Both implementation candidates were produced only after all of the following succeeded with Rust `1.97.1`:

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

## Repair history

Run `30893582994` on SHA `7748ec0acb97763aba315b66126608a031bffa80` proved the unchanged live desktop/native path remained green, but the quality job correctly failed on two test-contract defects:

- an unused test-only `DisplayInfo` import;
- an assertion using nonexistent `DesktopError::CoordinateOutOfRange` instead of the actual `DesktopError::InvalidCoordinate` contract.

The defects were fixed at their source without warning suppression.

## Exact-green authoritative CI

```text
SHA: 55fb359a5b307e49693bde8041a1e7298264bfd0
Run: 30894239655
Attempt: 1
Conclusion: completed / success
Quality job: 91943250678
Desktop/native job: 91943250683
Artifact ID: 8886338149
Artifact name: ci-evidence-30894239655
```

The quality job passed formatting, warning-denied Clippy, all Rust tests, warning-denied rustdoc, Python/workflow contract tests, shell syntax checks, and evidence generation. The independent desktop/native job passed the secured desktop image smoke test and the live LibVNCClient adapter smoke test.

## Remaining R8 evidence boundary

This closes the production worker-integration and worker-level test slice. The separate real TigerVNC end-to-end proof through `WorkerHandle` remains open before the entire R8 milestone can be declared complete.
