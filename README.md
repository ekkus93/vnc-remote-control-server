# VNC Remote Control Server

[![CI/CD](https://github.com/ekkus93/vnc-remote-control-server/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/ekkus93/vnc-remote-control-server/actions/workflows/ci.yml)

VNC Remote Control Server is a containerized Rust service that observes and controls one isolated Debian graphical desktop through the VNC Remote Framebuffer protocol.

The v0.1 architecture uses:

- a Debian 13 desktop container running XFCE and TigerVNC `Xvnc`;
- a separate Rust controller using a narrow LibVNCClient adapter;
- an authenticated HTTP and WebSocket API for screenshots, input, clipboard state, connection state, and revision events;
- a private container network that never publishes raw VNC in production.

## Status

Implementation is in progress on `master` under the authoritative rebased plan:

- [`docs/VNC_REMOTE_CONTROL_SERVER_REBASE_SPEC_2026-08-03.md`](docs/VNC_REMOTE_CONTROL_SERVER_REBASE_SPEC_2026-08-03.md)
- [`docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md`](docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md)

Implemented and validated so far:

- pinned, warning-denied Rust workspace and committed lockfile;
- safe core model, LibVNCClient adapter, dedicated worker, reconnect/stall behavior, framebuffer store, screenshots, and complete input/clipboard control;
- authenticated HTTP and WebSocket APIs with structured tracing, bounded metrics, and overload controls;
- digest-pinned Debian 13 XFCE/TigerVNC desktop image and deterministic graphical test application;
- multi-stage non-root controller image with only runtime LibVNCClient dependencies;
- production Compose with internal-only raw VNC, file-mounted secrets, read-only controller root filesystem, and bounded temporary storage;
- explicit loopback-only VNC debug override;
- disposable-by-default desktop state plus an opt-in persistent desktop-home volume;
- real desktop, adapter, worker, HTTP/WebSocket, controller-image, Compose, and persistence smoke tests;
- ChatGPT-readable CI status publishing through GitHub issue `#1`.

Remaining release work is tracked in R13 and later milestones: broader integration/restart stress, native safety tooling, dependency and image security gates, API documentation, packaging, and final acceptance evidence.

The original [`docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md`](docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md) is retained as historical planning context. The dated rebased TODO above is authoritative for current implementation work.

## Product boundary

v0.1 provides pixel observation and remote-desktop input primitives for exactly one project-owned Debian desktop. OCR, Playwright, accessibility-tree automation, AI planning, multiple sessions, arbitrary external VNC servers, and a browser viewer are outside the v0.1 scope.

## Quality policy

Every first-party compiler warning, Clippy warning, lint finding, test failure, shell finding, Dockerfile finding, and workflow-contract violation is treated as a defect. Warnings are fixed at their source rather than suppressed, hidden, downgraded, or ignored.

## Development

The supported Rust toolchain is pinned in [`rust-toolchain.toml`](rust-toolchain.toml). Run:

```bash
make fmt
make lint
make test
make build
```

Production and development deployment commands are documented in [`deploy/README.md`](deploy/README.md). The production topology is `deploy/compose.yaml`; raw VNC requires the explicit development-only override. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for prerequisites and the current command surface.

## Security and operator boundaries

- Production must never publish raw VNC port `5901` to the host or public network.
- Development-only raw VNC access must bind to loopback, for example `127.0.0.1:5901:5901`.
- API and VNC credentials must come from secret files by default and must never be baked into images or committed to source control.
- Typed text, clipboard contents, VNC passwords, bearer tokens, and framebuffer screenshots must never be written to application logs, metrics, or event payloads.
- Terminate TLS at a trusted reverse proxy or another explicitly documented trusted network boundary before exposing the future controller API beyond localhost.

Report suspected vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md).

## License

MIT License. See [`LICENSE`](LICENSE).
