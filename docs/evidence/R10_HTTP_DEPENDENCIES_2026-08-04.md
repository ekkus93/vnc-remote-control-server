# R10 Locked HTTP Dependency Evidence

Date: 2026-08-04

## Scope

This record covers the dependency foundation for the authenticated Axum controller API. No HTTP route behavior is claimed by this evidence record.

## Locked dependency commit

```text
Commit: 80d1c3c07aa46c529d3f49ba201da45ab97ae94b
Resolver workflow: R10 HTTP Dependency Candidate
Resolver run: 30935178450
Dependency evidence artifact: r10-http-dependencies-30935178450
Artifact ID: 8902824223
Artifact digest: sha256:9d08d9167bd99a86bea71cfe0283bd940fc3825c094de85ff9c310a32543cd61
Temporary tag: removed
```

## Direct dependencies

The workspace pins:

```text
axum 0.8.9
subtle 2.6.1
tokio 1.52.3
tower 0.5.2
```

Axum is built without default features and enables only `http1`, `json`, and `tokio`.

Tokio is built without default features and enables only `macros`, `net`, `rt-multi-thread`, `signal`, `sync`, and `time`.

Tower is a test-only direct dependency and enables only `util`.

`serde_json` moved from a crate-local development declaration to the existing workspace-managed version so production JSON responses and test code share one locked package.

## Lockfile transition proof

The resolver parsed the before and after Cargo lockfiles and failed closed unless all conditions held:

- no existing package key was removed;
- every existing third-party package record remained byte-semantically identical after TOML parsing;
- only the local `controller-api` dependency list gained the expected direct dependencies;
- every newly added package came from the crates.io registry source and contained a checksum;
- the required pinned direct package versions were present exactly.

The resolver added 34 registry packages:

```text
atomic-waker 1.1.2
axum 0.8.9
axum-core 0.5.6
bytes 1.12.1
futures-channel 0.3.33
futures-core 0.3.33
futures-task 0.3.33
futures-util 0.3.33
http 1.5.0
http-body 1.1.0
http-body-util 0.1.4
httparse 1.10.1
httpdate 1.0.3
hyper 1.11.0
hyper-util 0.1.20
matchit 0.8.4
mime 0.3.17
mio 1.2.2
percent-encoding 2.3.2
pin-project-lite 0.2.17
serde_path_to_error 0.1.20
signal-hook-registry 1.4.8
slab 0.4.12
smallvec 1.15.2
socket2 0.6.5
subtle 2.6.1
sync_wrapper 1.0.2
tokio 1.52.3
tokio-macros 2.7.2
tower 0.5.2
tower-layer 0.3.3
tower-service 0.3.3
wasi 0.11.1+wasi-snapshot-preview1
```

## Validation

After resolution, every final gate used the committed lockfile:

```text
cargo fetch --locked
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m unittest discover -s tests -p 'test_*.py' -v
```

No existing dependency was upgraded or downgraded, no checksum was hand-written, and no unlocked final gate was accepted as release evidence.

## Authoritative CI

Pending the ordinary `master` push created by this evidence record.

## Next implementation slice

The next R10 slice will implement:

- application state and shutdown gating;
- request IDs and stable JSON errors;
- bearer authentication using the pinned constant-time comparison utility;
- liveness, readiness, status, display, and screenshot routes;
- unit-level router tests before the control routes are enabled.
