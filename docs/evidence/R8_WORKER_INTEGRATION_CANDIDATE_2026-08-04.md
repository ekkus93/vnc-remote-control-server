# R8 Worker Integration and TigerVNC E2E Evidence

Date: 2026-08-04

## Closure status

R8 is complete for the v0.1 vertical-scroll input contract.

The production path is exercised through the real worker, LibVNCClient, TigerVNC, and deterministic desktop application. Horizontal scrolling is deliberately excluded from v0.1 because TigerVNC interoperability has not been verified. The public HTTP schema must expose vertical steps only when R10 is implemented.

The destructive desktop-global shortcut `CTRL_LEFT + ALT_LEFT + T` is not used as an acceptance fixture because XFCE may intercept it and launch a terminal before the deterministic test application can observe the complete sequence. The accepted deterministic chord fixture is `CTRL_LEFT + SHIFT_LEFT + F6`, which proves ordered presses and reverse-order releases without desktop side effects.

## Implementation history

- Worker integration: `6997362414336b8ef727c1a5cbabdbb1bc1c4b94`
- Worker contract repair: `df911e883bff6e52a78b4ddbf00d9d73067ffcf1`
- Initial WorkerHandle E2E: `40bb44dad8b45ef5d556fc21fc0b612b386ddf20`
- Failure-only diagnostics: `3d206de26fb7cea25c0912666375904c2a18bff2`
- Expanded R8 input driver: `fbf380da5acebaf44e6d12ba45090e0c5d99aec3`
- Complete deterministic assertions: `bf25c7a3f646622a274e67e3db830208bd26ae8a`
- Diagnostics redaction sentinel: `67ef848b14a70e503091cb699a8cb9d67fa32d05`
- CI diagnostics self-test: `d58fc8e7bc9e2933bdf573c18aa1d29681b59f34`
- Permanent contract tests: `541529640b73235c570ef721bbb83191690783b1`

No lint, warning, test, timeout, or failure suppression was added.

## Implemented worker contract

- The production worker owns one `InputController` on its existing single native thread.
- `InputSink` delegates pointer and key events to the worker-owned `WorkerSession`.
- Pointer movement, explicit button state, click, double-click, vertical scrolling, explicit key state, and chords route through `InputController`.
- Pointer-bearing commands validate against the canonical complete framebuffer dimensions before native mutation.
- Coordinates are rejected rather than clamped.
- The complete current button mask is preserved.
- Click and double-click sequences are atomic inside the worker.
- Vertical scroll steps are bounded and atomic.
- Horizontal scrolling fails preflight and is outside the v0.1 public contract.
- Chords press in request order and release in reverse order.
- Partial native failures perform best-effort release and return the real command failure.
- Disconnect and shutdown release tracked mouse buttons and keys before native session destruction.
- Text input remains explicitly deferred to R9.

## Real WorkerHandle TigerVNC E2E contract

The authoritative CI job executes `tests/worker-e2e/run.sh`. The harness:

1. starts the project-owned Debian/XFCE/TigerVNC desktop container with a file-mounted VNC password;
2. runs `crates/controller-api/src/bin/worker-input-e2e.rs` against a dynamically published loopback VNC port;
3. creates the production `DesktopWorker` and obtains its `WorkerClient`;
4. waits for `Connected` state and a complete canonical framebuffer;
5. submits all input commands through `WorkerClient` and waits for every acknowledgement;
6. shuts the worker down cleanly;
7. reads `/tmp/vnc-test-app-state.json` from the deterministic Tk application;
8. verifies exact ordered events and released final input state;
9. fails if the VNC password appears in worker or desktop logs.

The E2E path is:

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

## Input operations proven end to end

The permanent E2E sequence proves:

- pointer movement to `(320, 240)`;
- explicit left-button down and up;
- atomic left click;
- atomic middle click;
- atomic right click;
- atomic left double-click with exactly two complete clicks;
- two positive vertical wheel steps;
- one negative vertical wheel step;
- explicit `F5` down and up;
- chord presses `CTRL_LEFT`, `SHIFT_LEFT`, `F6` in order;
- chord releases `F6`, `SHIFT_LEFT`, `CTRL_LEFT` in reverse order;
- final button state has left, middle, and right released;
- final key state is empty;
- final vertical scroll total is `+1`.

The deterministic assertion checks the ordered mouse sequence rather than only aggregate final state, so missing, duplicated, or reordered click transitions fail the test.

## Failure diagnostics contract

On a real WorkerHandle E2E failure, the harness captures before cleanup:

```text
worker-input-e2e.log
desktop.log
desktop-state.json
desktop-state-error.log
container-state.json
failure-manifest.json
```

CI uploads these files only when the normal WorkerHandle E2E step fails. Successful runs create no failure artifact.

A permanent controlled-failure self-test runs the same E2E path, injects a failure only after deterministic input verification, and proves:

- every required diagnostic file exists and is nonempty;
- the failure manifest records exit status `1`;
- captured desktop state is valid schema version `1` and contains input events;
- an injected credential sentinel is replaced exactly with `[REDACTED]`;
- the raw VNC password is absent from every captured file;
- the self-test diagnostics directory is removed after validation.

## Validation commands

The implementation passed with Rust `1.97.1`:

```text
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n tests/worker-e2e/run.sh
bash tests/worker-e2e/run.sh
```

Worker-level tests cover button-mask preservation, event ordering, invalid-coordinate rejection before native mutation, partial-failure cleanup, and disconnect/shutdown release behavior.

## Exact-green authoritative CI

```text
SHA: 541529640b73235c570ef721bbb83191690783b1
Run: 30929517821
Attempt: 1
Conclusion: completed / success
Quality job: 92060416112
Desktop/native/E2E job: 92060416024
Artifact ID: 8900556580
Artifact name: ci-evidence-30929517821
```

The quality job passed formatting, warning-denied Clippy, all Rust tests, warning-denied rustdoc, Python/workflow contract tests, shell syntax checks, and evidence generation.

The real-container job passed:

- secured desktop image smoke;
- live LibVNCClient adapter smoke;
- complete WorkerHandle TigerVNC input E2E;
- controlled failure-diagnostics and redaction self-test.

The normal failure-artifact upload step was correctly skipped because the primary E2E test succeeded.

## R8 release boundary

R8 is closed. R9 is the next implementation milestone.

R9 must add complete-string text preflight, supported-character key mapping, outbound clipboard, inbound clipboard callbacks/snapshots, exact deterministic application verification, and payload-redaction tests.
