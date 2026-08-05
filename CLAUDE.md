# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A containerized Rust service (Cargo workspace, edition 2024) that observes and controls one
isolated Debian graphical desktop over VNC/RFB. Three crates: `crates/controller-api` (axum
HTTP/WebSocket API), `crates/libvnc-adapter` (C FFI binding to LibVNCClient), `crates/remote-desktop-core`
(dependency-light domain model). See `README.md` for architecture and `docs/LIBVNCCLIENT_BINDING_DECISION.md`
for the native-binding rationale.

## Commands

- `make fmt` — `cargo fmt --all --check` (check only; use `cargo fmt --all` to actually format)
- `make lint` — `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `make test` — `cargo test --workspace --all-features`
- `make build` — `cargo build --workspace --all-features --locked`
- `make integration-test` / `make e2e-test` — shell-driven suites under `tests/integration/run.sh`, `tests/e2e/run.sh`
- `make security-scan` — `cargo deny check`
- Single Rust test: `cargo test -p controller-api <test_name>`
- Python contract tests (validate CI workflows, docs, and policy files themselves):
  `python -m unittest discover -s tests -p 'test_*.py' -v`
- Other e2e suites each have their own `run.sh` under `tests/{worker-e2e,worker-text-clipboard-e2e,http-e2e,desktop,native,compose}/`
  — these spin up real Docker/TigerVNC containers.

## Zero-warning policy

`[workspace.lints]` denies all rustc warnings and all clippy lints workspace-wide. CI and CONTRIBUTING.md
both state warnings and failing gates are defects: fix the cause, never suppress, downgrade, or
`#[allow(...)]` a warning just to pass CI.

## Secrets convention

Credentials are passed as file paths, not raw values: config env vars use a `*_FILE` suffix
(e.g. `VRC_API_TOKEN_FILE`, `VRC_VNC_PASSWORD_FILE`) pointing at a secret file — never put a
secret value directly in an env var, image, source control, or a URL. Never log typed text,
clipboard contents, VNC passwords, bearer tokens, or screenshots. Never publish the raw VNC
port (5901) from production compose.

## Workflow

- Work is performed directly on `master` unless the repository owner explicitly requests a
  branch/PR workflow — do not create a branch or PR without that instruction.
- Milestones are documented as a trio of dated markdown docs in `docs/`: a SPEC doc, a TODO doc,
  and an EVIDENCE doc (e.g. `..._REFACTOR_SPEC_2026-08-05.md` / `..._TODO_2026-08-05.md`). Follow
  this pattern for substantial changes rather than tracking work only in code comments.
