# R8 Worker Integration and TigerVNC E2E Evidence

Date: 2026-08-04

## Implementation

- Worker integration commit: `6997362414336b8ef727c1a5cbabdbb1bc1c4b94`
- Clippy/test-contract repair: `df911e883bff6e52a78b4ddbf00d9d73067ffcf1`
- Exact-green worker-integration candidate: `55fb359a5b307e49693bde8041a1e7298264bfd0`
- WorkerHandle E2E implementation and pinned-formatting candidate: `40bb44dad8b45ef5d556fc21fc0b612b386ddf20`
- Branch policy: direct `master`; no implementation branch or pull request
- Temporary validation refs: removed after `master` fast-forward
- Temporary workflows and transformation scripts: absent from final tree

## Implemented worker contract

- The production worker owns one `InputController` on its existing single native thread.
- `InputSink` delegates pointer and key events to the worker-owned `WorkerSession`.
- Pointer movement, explicit button state, click, double-click, vertical scrolling, explicit key state, and chords route through `InputController`.
- Pointer-bearing commands validate against the canonical complete current framebuffer dimensions before native mutation.
- Horizontal scrolling remains explicitly rejected because interoperability is not yet verified.
- Text input remains explicitly deferred to R9.
- Disconnect and shutdown perform best-effort release of tracked buttons and keys before native session destruction.
- Command completion returns native input failures to the caller.

## Real WorkerHandle TigerVNC E2E contract

The authoritative CI job now executes `tests/worker-e2e/run.sh`. The harness:

1. starts the project-owned Debian/XFCE/TigerVNC desktop container with a file-mounted VNC password;
2. runs `crates/controller-api/src/bin/worker-input-e2e.rs` against the dynamically published loopback VNC port;
3. creates the production `DesktopWorker` and obtains its `WorkerClient`;
4. waits for `Connected` state and a complete canonical framebuffer;
5. submits pointer movement, left click, two positive vertical wheel steps, explicit `F5` down/up, and the chord `CTRL_LEFT + SHIFT_LEFT + F6` through `WorkerClient`;
6. waits for every worker acknowledgement and shuts the worker down cleanly;
7. reads `/tmp/vnc-test-app-state.json` from the deterministic Tk desktop application;
8. verifies the exact pointer coordinate, click down/up events, vertical scroll count and direction, standalone key ordering, reverse chord release ordering, empty final key state, and released final button state;
9. fails if the mounted VNC password appears in the worker or desktop logs.

The E2E path is therefore:

```text
WorkerClient
  -> bounded worker command queue
  -> single-owner native worker thread
  -> InputController
  -> LibVNCClient
  -> TigerVNC Xvnc
  -> deterministic Tk application
  -> atomic JSON state verification
```

## Validation commands

The implementation passed the following gates with Rust `1.97.1`:

```text
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-targets --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n tests/worker-e2e/run.sh
bash tests/worker-e2e/run.sh
```

Worker-level tests cover:

- full button-mask preservation across compound commands;
- pointer/click/scroll/chord ordering through the worker-owned session;
- invalid-coordinate rejection before native mutation;
- propagation of partial native input failure after release retry;
- release of tracked mouse and keyboard state during orderly shutdown.

The E2E contract test additionally prevents CI from silently bypassing `DesktopWorker`/`WorkerClient`, omitting a required input category, or dropping deterministic desktop-state verification.

## Repair history

Run `30893582994` on SHA `7748ec0acb97763aba315b66126608a031bffa80` proved the unchanged live desktop/native path remained green, but the quality job correctly failed on two test-contract defects:

- an unused test-only `DisplayInfo` import;
- an assertion using nonexistent `DesktopError::CoordinateOutOfRange` instead of the actual `DesktopError::InvalidCoordinate` contract.

The defects were fixed at their source without warning suppression.

The first WorkerHandle E2E candidate also exposed a pinned-rustfmt difference in the Rust driver. The exact Rust `1.97.1` formatter output was committed before semantic validation. No formatting or lint exception was added.

## Exact-green authoritative CI

```text
SHA: 40bb44dad8b45ef5d556fc21fc0b612b386ddf20
Run: 30897120126
Attempt: 1
Conclusion: completed / success
Quality job: 91952583959
Desktop/native/E2E job: 91952584028
Artifact ID: 8887511088
Artifact name: ci-evidence-30897120126
WorkerHandle E2E step: completed / success
```

The quality job passed formatting, warning-denied Clippy, all Rust tests, warning-denied rustdoc, Python/workflow contract tests, shell syntax checks, and evidence generation. The independent real-container job passed:

- the secured desktop image smoke test;
- the live LibVNCClient adapter smoke test;
- the production WorkerHandle TigerVNC input E2E test.

The E2E runtime log contains the explicit completion evidence:

```text
[worker-e2e] sending input through the production WorkerClient
[worker-e2e] verifying deterministic desktop observations
worker_input_e2e_complete=1
[worker-e2e] WorkerHandle TigerVNC input E2E test passed
```

## Remaining R8 boundary

The general production WorkerHandle input E2E requirement is closed. One separately worded TODO item remains intentionally open: the exact chord `CTRL_LEFT + ALT_LEFT + T` has not yet been exercised end to end. This proof used `CTRL_LEFT + SHIFT_LEFT + F6` so it could verify press and reverse-release ordering without launching a terminal or introducing desktop-environment side effects.
