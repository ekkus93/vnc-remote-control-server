# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A containerized Rust service (Cargo workspace, edition 2024) that observes and controls one isolated Debian graphical desktop over VNC/RFB. Three Rust crates: `crates/controller-api` (Axum HTTP/WebSocket API), `crates/libvnc-adapter` (narrow C FFI boundary over LibVNCClient), and `crates/remote-desktop-core` (dependency-light domain model).

The repository also ships an installable typed Python client under `python/`, including the `vnc-remote-control-demo` console application and optional `vnc-remote-control-mcp` adapter. MCP is a thin layer over `VncRemoteControlClient`; it must not grow a second VNC/RFB implementation, an automatic mutation-retry layer, or a public unauthenticated network surface. The controller hosts Swagger UI, ReDoc, and the repository-owned OpenAPI 3.1 document.

Start with `README.md` for architecture and quick start, `docs/README.md` for the current documentation index, `docs/MCP_SERVER.md` for the current MCP contract, and `docs/LIBVNCCLIENT_BINDING_DECISION.md` for the native-binding rationale.

## Commands

- `make fmt` — `cargo fmt --all --check` (check only; use `cargo fmt --all` to actually format)
- `make lint` — `cargo clippy --workspace --all-targets --all-features -- -D warnings`
- `make lint-python` — runs the repository's Ruff, Pylint, and mypy Python gates
- `make test` — `cargo test --workspace --all-features`
- `make build` — `cargo build --workspace --all-features --locked`
- `make integration-test` — `tests/integration/run.sh` (`make e2e-test` is currently broken — it targets `tests/e2e/run.sh`, which does not exist in this repo; use the per-suite scripts below instead)
- `make security-scan` — `cargo deny check`
- Single Rust test: `cargo test -p controller-api <test_name>`
- Full Python/MCP/client/documentation/workflow/policy contracts (install the exact MCP extra first, once per environment):
  `pip install -e './python[mcp]'`
  `python3 -m unittest discover -s tests -p 'test_*.py' -v`
- Focused MCP living-document contract:
  `python3 -m unittest tests.test_mcp_documentation_contract -v`
- Other E2E suites each have their own `run.sh` under `tests/{worker-e2e,worker-text-clipboard-e2e,http-e2e,desktop,native,compose,measurement/framebuffer}/`
  — these spin up real Docker/TigerVNC containers.
- The `/verify-full` skill runs the local equivalent of CI's `quality` gate (fmt check, clippy, cargo test, Python contract tests) in one pass; it deliberately excludes the Docker/TigerVNC e2e suites and `cargo deny check`.

The core Python client intentionally remains installable without MCP (`pip install -e python/`) and has zero third-party HTTP runtime dependencies. The complete first-party test suite is different: MCP transport tests import the reviewed SDK and therefore require `pip install -e './python[mcp]'`. Do not turn missing MCP dependencies into skipped success in the authoritative full-suite path.

## MCP invariants

The reviewed optional dependency is exactly `mcp==2.1.1`. A change to that pin or to the SDK API surface requires deliberate review; do not add version-detection or compatibility fallbacks.

`vnc-remote-control-mcp` must preserve these boundaries:

- stdio is the default transport;
- Streamable HTTP is explicit and binds only to the exact SDK-protected loopback hosts `127.0.0.1`, `localhost`, or `::1`;
- do not disable or replace the SDK Host/Origin/DNS-rebinding protections to accommodate a deployment;
- legacy SSE is not a compatibility fallback;
- `VRC_MCP_ALLOW_MUTATIONS=false` is the default and mutation tools are absent unless explicitly enabled;
- all controller calls go through the shared bounded off-loop executor and the typed `VncRemoteControlClient`;
- never automatically retry or replay a mutation whose execution outcome may be unknown;
- a known ambiguous command is recovered by inspecting `vnc_get_command_status(command_id)`, not by resending it;
- the controller bearer token enters MCP only through `VRC_MCP_CONTROLLER_TOKEN_FILE`, never as a raw token env/CLI/URL value.

See [`docs/MCP_SERVER.md`](docs/MCP_SERVER.md) before changing MCP configuration, tools, transports, shutdown behavior, or security semantics.

## Zero-warning and fail-closed policy

`[workspace.lints]` denies all rustc warnings and all Clippy lints workspace-wide. CI and CONTRIBUTING.md both state warnings and failing gates are defects: fix the cause, never suppress, downgrade, or add a broad `#[allow(...)]` merely to pass CI.

Do not add `continue-on-error`, unconditional-success fallbacks, broad ignores, silent exception handling, or compatibility behavior that converts a real failure into apparent success. Release-candidate claims require both permanent `CI` and `Release Gates` to pass on the exact same candidate SHA.

## Secrets convention

Credentials are passed as file paths, not raw values: config env vars use a `*_FILE` suffix (for example `VRC_API_TOKEN_FILE`, `VRC_VNC_PASSWORD_FILE`, and `VRC_MCP_CONTROLLER_TOKEN_FILE`) pointing at a secret file. Never put a secret value directly in an env var, image, source control, command argument, or URL. Never log typed text, clipboard contents, VNC passwords, bearer tokens, screenshots, or raw sensitive controller bodies. Never publish raw VNC port `5901` from production Compose.

The MCP controller token is ultimately held in ordinary Python objects, including a Python `str`; unlike Rust `SecretString`, the Python process cannot guarantee zeroization of every live/intermediate copy. Do not overstate that memory property in code comments or documentation.

## Documentation sources

`docs/README.md` separates two categories:

- **Living documentation** such as `README.md`, `docs/OPERATOR_GUIDE.md`, `docs/MCP_SERVER.md`, `docs/openapi.json`, `docs/WEBSOCKET_EVENTS.md`, `docs/CUSTOM_DESKTOP_IMAGES.md`, `python/README.md`, `deploy/README.md`, and `SECURITY.md`. These must track current `master`.
- **Historical engineering artifacts** such as dated SPEC/TODO/EVIDENCE/review/implementation-note files. These intentionally preserve the repository state, commit SHAs, failures, and decisions from the milestone they recorded and must not be rewritten merely to look current.

When implementation behavior changes, update the relevant living documentation and contract tests in the same change. For MCP, `tests/test_mcp_documentation_contract.py` ties configuration names/defaults/ranges, package metadata, catalog/security semantics, and required living-document links back to current source. Do not use an old milestone TODO as the authority for current runtime behavior.

`tests/test_documentation_freshness.py` enforces the wider living-vs-historical split and runs as part of the same Python contract suite.

## Workflow

- Work is performed directly on `master` unless the repository owner explicitly requests a branch/PR workflow — do not create a branch or PR without that instruction.
- Substantial planned or hardening milestones may use dated SPEC/TODO/EVIDENCE documents when useful. Ordinary focused changes do not require a synthetic milestone trio.
- Preserve fail-closed behavior and explicit failure visibility. If a test or gate fails, fix the cause rather than weakening the check.
