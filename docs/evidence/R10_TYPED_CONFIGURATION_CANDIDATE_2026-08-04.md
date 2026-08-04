# R10 Typed Configuration Candidate Evidence

Date: 2026-08-04

## Scope

This record covers the typed, fail-closed configuration foundation for the authenticated controller API. It does not yet close R10 because the HTTP listener, authentication middleware, routes, request IDs, body limits, and graceful server shutdown remain to be implemented.

## Implementation

```text
Configuration source: crates/controller-api/src/config.rs
Implementation commit: 065bbfb1b5451cf7ebfdea46fd9df90d1fd687c0
Isolated workflow run: 30934526611
Temporary candidate tag: removed
```

The implementation commit atomically:

- enabled the public `controller_api::config` module;
- committed Cargo's exact lockfile update for the existing `tempfile` package becoming a direct `controller-api` test dependency;
- removed the temporary configuration validation workflow.

The lockfile validator parsed the before and after lockfiles and proved:

- no package was added or removed;
- no third-party version, source, checksum, feature, or dependency record changed;
- only the local `controller-api` package dependency list gained `tempfile`.

## Implemented contract

`ControllerConfig` now validates and stores:

- HTTP listen address;
- file-backed API bearer token;
- process instance identifier used for screenshot ETags;
- global JSON body limit;
- worker command acknowledgement timeout;
- screenshot concurrency and timeout limits;
- VNC host and port;
- file-backed VNC password;
- native connection/read timeouts;
- worker queue capacities;
- framebuffer memory limit;
- poll, startup, reconnect, manual reconnect, and stall timing values.

## Secret policy

- API and VNC secret values cannot be supplied directly through environment variables.
- Environment variables may select secret file paths only.
- Secret files must be regular files between 1 byte and 4 KiB.
- Secret contents must be UTF-8, nonempty after newline trimming, and contain no NUL.
- Group/other write permission and all execute permission are rejected.
- Read-only Docker-secret style mode `0444` is accepted.
- `ControllerConfig` implements a manual redacted `Debug`; API token and VNC password values are never rendered.
- Secret read errors contain path and redaction-safe reason only.

## Validation behavior

The configuration loader rejects:

- malformed or zero listen ports;
- zero VNC port;
- empty/oversized VNC host;
- zero or excessive queue/body/framebuffer/screenshot limits;
- zero durations;
- reconnect minimum greater than maximum;
- reconnect jitter above the worker limit;
- malformed process instance identifiers;
- missing, oversized, non-UTF-8, empty, NUL-containing, writable, executable, or non-regular secret files.

All worker settings are revalidated through `WorkerSettings::validate` before use.

## Tests

The Rust tests cover:

- valid defaults;
- selected secret paths and non-secret overrides;
- invalid ports, limits, durations, and reconnect settings;
- direct environment secret values being ignored;
- strict process-instance validation;
- acceptance of read-only secret files;
- rejection of writable secret exposure;
- redacted configuration debug output;
- secret-safe error rendering.

## Isolated validation

The candidate passed with Rust `1.97.1`:

```text
cargo check --workspace --all-targets --all-features
cargo fmt --all
git diff --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --locked --workspace --all-features --no-deps
python -m unittest discover -s tests -p 'test_*.py' -v
```

No warning allowance, lint suppression, unlocked final gate, ignored test, or dependency downgrade was introduced.

## Authoritative CI

Pending the ordinary `master` push created by this evidence record.

## Remaining R10 boundary

Next work:

1. generate and verify the locked Axum/Tokio dependency graph;
2. implement bearer authentication and request IDs;
3. implement liveness, readiness, status, display, and screenshot routes;
4. implement pointer, keyboard, text, clipboard, and reconnect routes;
5. enforce body and operation deadlines;
6. reject new control commands during shutdown;
7. run authenticated HTTP integration tests against the real worker/TigerVNC path.
