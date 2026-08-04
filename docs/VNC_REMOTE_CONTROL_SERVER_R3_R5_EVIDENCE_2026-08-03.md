# Native adapter rebase evidence — R3 through R5 baseline

Date: 2026-08-03
Repository: `ekkus93/vnc-remote-control-server`
Authoritative TODO: `docs/VNC_REMOTE_CONTROL_SERVER_REBASE_TODO_2026-08-03.md`

## Exact verified gate

- Commit: `6bef7b854a845590b2ff52662ae1c70caeddf91b`
- Workflow: `CI`
- Run: `30881879425`
- Attempt: `1`
- Conclusion: `success`
- Quality job: `91904807334`
- Desktop/native job: `91904807363`
- CI status issue: issue #1 reported `completed` / `success`
- Evidence artifact: `ci-evidence-30881879425`

## R3 — native build and binding strategy

The controller build environment installs `build-essential`, `libvncserver-dev`, and `pkg-config`. The adapter build script resolves the system `libvncclient` package, compiles the project-owned C shim with `-Wall -Wextra -Werror -pedantic`, links it into the Rust crate, and records the detected native version in CI evidence.

Binding strategy: a reviewed project-owned C shim with an opaque handle. Rust does not reproduce or expose the `rfbClient` structure layout. The decision and safety rationale are documented in `docs/LIBVNCCLIENT_BINDING_DECISION.md`.

Verified native version:

```text
LibVNCClient 0.9.14
Ubuntu package 0.9.14+dfsg-1ubuntu0.2
```

Verified commands in the quality job:

```text
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-features
RUSTDOCFLAGS=-Dwarnings cargo doc --locked --workspace --all-features --no-deps
python -m compileall -q tools/ci_status tests desktop/test-app
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n desktop/entrypoint.sh desktop/healthcheck.sh desktop/xstartup tests/desktop/run.sh tests/native/run.sh
```

All commands passed on the exact gate SHA.

## R4 — real LibVNCClient connection spike

The native smoke harness starts the project-owned Debian/TigerVNC desktop, mounts the VNC password from a file, connects through the Rust adapter, authenticates, processes server messages until a complete framebuffer is available, and proves input and clipboard behavior against the deterministic desktop test application.

Observed proof:

```text
proof_ready=1 libvncclient_version=0.9.14 protocol_major=3 dimensions=1280x800 revision=1 bytes=4096000
```

The harness verified:

- authenticated RFB 3.x connection;
- complete `1280x800` 32-bit framebuffer;
- pointer movement observed by the deterministic test application;
- F5 key down/up observed by the deterministic test application;
- outbound clipboard value observed while the native client remained connected;
- wrong-password authentication failure was bounded and failed closed;
- unreachable-port transport failure was bounded and failed closed;
- no VNC password appeared in command output or desktop logs;
- native cleanup completed without a crash or hang.

## R5 — safety baseline

Implemented and verified:

- opaque native handle and private Rust raw pointer;
- exactly one Rust RAII owner and one C cleanup path;
- callback context lifetime tied to the native client;
- no C callback enters Rust, so Rust panics cannot cross the callback boundary;
- checked framebuffer dimensions and bounded allocation;
- checked outbound pointer and clipboard arguments;
- framebuffer and clipboard copies validate destination capacity;
- partial connection failures remain owned by the RAII destruction path;
- typed, payload-free adapter errors;
- password, clipboard, typed text, and framebuffer contents excluded from error formatting;
- live wrong-password and unreachable-transport failure probes.

Remaining R5 hardening before declaring the entire milestone complete:

- deterministic injected failure coverage for allocation, framebuffer initialization, format negotiation, and initial update-request stages;
- sanitizer coverage for native callback/update paths;
- an explicit test proving every partial-initialization stage reaches exactly one cleanup path.

These remaining items are not silently marked complete by this evidence record.
