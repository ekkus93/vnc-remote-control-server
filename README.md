# VNC Remote Control Server

VNC Remote Control Server is a containerized Rust service that observes and controls one isolated Debian graphical desktop through the VNC Remote Framebuffer protocol.

The v0.1 architecture uses:

- a Debian 13 desktop container running XFCE and TigerVNC `Xvnc`;
- a separate Rust controller using a narrow LibVNCClient adapter;
- an authenticated HTTP and WebSocket API for screenshots, input, clipboard state, connection state, and revision events;
- a private container network that never publishes raw VNC in production.

## Status

Implementation is in progress under [`docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md`](docs/VNC_REMOTE_CONTROL_SERVER_V01_TODO.md). The repository currently contains the engineering baseline and core domain model. Later milestones add the desktop image, native adapter, controller API, Compose deployment, and real end-to-end validation.

## Product boundary

v0.1 provides pixel observation and remote desktop input primitives. OCR, Playwright, accessibility-tree automation, AI planning, multiple sessions, and a browser viewer are explicitly outside the v0.1 scope.

## Quality policy

Every first-party compiler warning, Clippy warning, test failure, shell-lint finding, and workflow-contract violation is treated as a defect. CI denies warnings; warnings are fixed rather than suppressed.

## Development

The supported Rust toolchain is pinned in [`rust-toolchain.toml`](rust-toolchain.toml). Run:

```bash
make fmt
make lint
make test
make build
```

Container and integration commands become active as their milestones land. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for prerequisites and the full command surface.

## Security

Do not expose VNC port `5901` publicly. Report suspected vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md).

## License

MIT License. See [`LICENSE`](LICENSE).
