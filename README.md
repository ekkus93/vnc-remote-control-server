# VNC Remote Control Server

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

- pinned Rust workspace and committed lockfile;
- warning-denied `remote-desktop-core` domain model and tests;
- digest-pinned Debian 13 XFCE/TigerVNC desktop image;
- non-root desktop runtime with file-mounted VNC secret;
- deterministic graphical test application;
- real correct-password, wrong-password, missing-secret, health, and shutdown desktop smoke checks;
- ChatGPT-readable CI status publishing through GitHub issue `#1`.

Explicit placeholders remain:

- `libvnc-adapter` does not yet contain the production LibVNCClient binding or worker;
- `controller-api` does not yet contain the production HTTP/WebSocket server;
- production Compose, integration tests, and end-to-end API validation are not yet implemented.

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

Container and integration commands become authoritative only when their backing milestones and CI gates are implemented. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for prerequisites and the current command surface.

## Security and operator boundaries

- Production must never publish raw VNC port `5901` to the host or public network.
- Development-only raw VNC access must bind to loopback, for example `127.0.0.1:5901:5901`.
- API and VNC credentials must come from secret files by default and must never be baked into images or committed to source control.
- Typed text, clipboard contents, VNC passwords, bearer tokens, and framebuffer screenshots must never be written to application logs, metrics, or event payloads.
- Terminate TLS at a trusted reverse proxy or another explicitly documented trusted network boundary before exposing the future controller API beyond localhost.

Report suspected vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md).

## License

MIT License. See [`LICENSE`](LICENSE).
