# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A containerized Rust service (Cargo workspace, edition 2024) that observes and controls one isolated Debian graphical desktop over VNC/RFB. Three Rust crates: `crates/controller-api` (Axum HTTP/WebSocket API), `crates/libvnc-adapter` (narrow C FFI boundary over LibVNCClient), and `crates/remote-desktop-core` (dependency-light domain model).

The repository also ships an installable typed Python client under `python/`, including the `vnc-remote-control-demo` console application. The controller hosts Swagger UI, ReDoc, and the repository-owned OpenAPI 3.1 document.

Start with `README.md` for architecture and quick start, `docs/README.md` for the current documentation index, and `docs/LIBVNCCLIENT_BINDING_DECISION.md` for the native-binding rationale.

## Commands

- `make fmt` — `cargo fmt --all --check` (check only; use `cargo fmt --all` to actually format)
- `make lint` — `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `make test` — `cargo test --workspace --all-features`
- `make build` — `cargo build --workspace --all-features --locked`
- `make integration-test` / `make e2e-test` — shell-driven suites under `tests/integration/run.sh`, `tests/e2e/run.sh`
- `make security-scan` — `cargo deny check`
- Single Rust test: `cargo test -p controller-api <test_name>`
- Python/client/documentation/workflow/policy contracts:
  `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- Other E2E suites each have their own `run.sh` under `tests/{worker-e2e,worker-text-clipboard-e2e,http-e2e,desktop,native,compose}/`
  — these spin up real Docker/TigerVNC containers.

## Zero-warning and fail-closed policy

`[workspace.lints]` denies all rustc warnings and all Clippy lints workspace-wide. CI and CONTRIBUTING.md both state warnings and failing gates are defects: fix the cause, never suppress, downgrade, or add a broad `#[allow(...)]` merely to pass CI.

Do not add `continue-on-error`, unconditional-success fallbacks, broad ignores, silent exception handling, or compatibility behavior that converts a real failure into apparent success. Release-candidate claims require both permanent `CI` and `Release Gates` to pass on the exact same candidate SHA.

## Secrets convention

Credentials are passed as file paths, not raw values: config env vars use a `*_FILE` suffix (for example `VRC_API_TOKEN_FILE`, `VRC_VNC_PASSWORD_FILE`) pointing at a secret file. Never put a secret value directly in an env var, image, source control, command argument, or URL. Never log typed text, clipboard contents, VNC passwords, bearer tokens, or screenshots. Never publish raw VNC port `5901` from production Compose.

## Documentation sources

`docs/README.md` separates two categories:

- **Living documentation** such as `README.md`, `docs/OPERATOR_GUIDE.md`, `docs/openapi.json`, `docs/WEBSOCKET_EVENTS.md`, `docs/CUSTOM_DESKTOP_IMAGES.md`, `python/README.md`, `deploy/README.md`, and `SECURITY.md`. These must track current `master`.
- **Historical engineering artifacts** such as dated SPEC/TODO/EVIDENCE/review/implementation-note files. These intentionally preserve the repository state, commit SHAs, failures, and decisions from the milestone they recorded and must not be rewritten merely to look current.

When implementation behavior changes, update the relevant living documentation and contract tests in the same change. Do not use an old milestone TODO as the authority for current runtime behavior.

## Workflow

- Work is performed directly on `master` unless the repository owner explicitly requests a branch/PR workflow — do not create a branch or PR without that instruction.
- Substantial planned or hardening milestones may use dated SPEC/TODO/EVIDENCE documents when useful. Ordinary focused changes do not require a synthetic milestone trio.
- Preserve fail-closed behavior and explicit failure visibility. If a test or gate fails, fix the cause rather than weakening the check.
