# Documentation Index

This directory contains both **living documentation for the current `master` branch** and **historical engineering artifacts** created during implementation, review, hardening, and release work.

Use this index to distinguish current operational truth from point-in-time project records.

## Current living documentation

These documents are expected to track the behavior, supported configuration, or current repository guidance of the current repository:

- [`../README.md`](../README.md) — project boundary, architecture, quick start, hosted API reference, Python client, and documentation entry points.
- [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md) — supported deployment lifecycle, API operation, recovery, tuning, validation, and troubleshooting.
- [`openapi.json`](openapi.json) — machine-readable OpenAPI 3.1 contract for the current HTTP API.
- [`WEBSOCKET_EVENTS.md`](WEBSOCKET_EVENTS.md) — current WebSocket event envelope, event types, heartbeat behavior, and close semantics.
- [`CUSTOM_DESKTOP_IMAGES.md`](CUSTOM_DESKTOP_IMAGES.md) — supported project-owned custom desktop workflow and the Python → Rust controller → VNC target configuration chain.
- [`../python/README.md`](../python/README.md) — Python client installation, direct GitHub installation, API usage, and the `vnc-remote-control-demo` CLI.
- [`../deploy/README.md`](../deploy/README.md) — current Docker Compose topology, secrets, persistence, debug VNC, and custom desktop overrides.
- [`../desktop/README.md`](../desktop/README.md) — stock desktop-container contract, TigerVNC lifecycle, secret handling, base-image pin, and deterministic test application.
- [`../SECURITY.md`](../SECURITY.md) — current security boundaries, secret lifecycle guarantees, and explicit residual risks.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — current development prerequisites, quality commands, and documentation discipline.
- [`../CLAUDE.md`](../CLAUDE.md) — current repository guidance for Claude Code and other implementation work that follows the same commands and fail-closed policy.
- [`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) — current contributor conduct and enforcement guidance.
- [`CI_STATUS_BRIDGE.md`](CI_STATUS_BRIDGE.md) — current purpose and operating contract of the GitHub issue-based CI status bridge.
- [`VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`](VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md) — current fail-closed release/security policy unless it is explicitly superseded by a stricter policy.
- [`LIBVNCCLIENT_BINDING_DECISION.md`](LIBVNCCLIENT_BINDING_DECISION.md) — accepted architecture decision for the native LibVNCClient boundary. It is an ADR rather than an operator guide, but the decision remains current until superseded.

When living documentation conflicts with a dated implementation artifact, use the living documentation and current source/tests as authoritative for present behavior.

## Current engineering support documentation

These narrower documents are also maintained against current code even though they are not operator-facing product contracts:

- [`../crates/controller-api/tests/FRAMEBUFFER_MEASUREMENT.md`](../crates/controller-api/tests/FRAMEBUFFER_MEASUREMENT.md) — reproducible framebuffer allocation/timing measurement contract and interpretation boundary.
- [`../tests/measurement/framebuffer/README.md`](../tests/measurement/framebuffer/README.md) — launcher for that committed measurement and pointer to the dated recorded evidence.

The recorded measurement evidence itself is historical: it captures one environment and one point in time. The launcher and measurement procedure must remain current with the executable test they invoke.

## Hosted API documentation

A running controller serves the repository-owned OpenAPI contract at:

- `/openapi.json` — raw OpenAPI 3.1 JSON;
- `/docs` — Swagger UI;
- `/redoc` — ReDoc.

The UI routes are public documentation surfaces. Calls to `/v1/*` still require the normal bearer token.

## Historical engineering artifacts

Files whose names contain dates, milestone identifiers, `SPEC`, `TODO`, `EVIDENCE`, `IMPLEMENTATION_NOTES`, `ANSWERS`, `RESPONSES`, `QUESTIONS`, `REVIEW`, or similar project-stage markers are generally **point-in-time records**.

Examples include:

- `VNC_REMOTE_CONTROL_SERVER_V01_SPEC.md` and `VNC_REMOTE_CONTROL_SERVER_V01_TODO.md` — the initial v0.1 planning baseline;
- `VNC_REMOTE_CONTROL_SERVER_REBASE_*_2026-08-03.md` — the August 3 implementation rebase from the repository state that existed then;
- `VNC_REMOTE_CONTROL_SERVER_R*_EVIDENCE_*.md` and [`evidence/`](evidence/) — milestone evidence captured at particular commits/runs;
- correctness-review, shutdown-hardening, post-correctness-hardening, final-polish, and cleanup spec/TODO/implementation-note sets — the design and execution record for those passes.

These files intentionally retain statements such as old commit SHAs, old CI run IDs, incomplete features, failures, superseded implementation plans, and then-current dependency observations. Those statements are historical evidence, not claims about current `master`.

Do **not** edit historical evidence merely to make old statements match current code. If a historical artifact contains an actual factual error about the state it was intended to record, correct it explicitly and preserve the historical context.

## Documentation maintenance rule

When behavior changes:

1. update the relevant living documentation in the same change;
2. update `openapi.json` and WebSocket documentation when their public contracts change;
3. update the Python client/demo documentation when its install or callable surface changes;
4. update deployment, desktop-component, and security documentation when topology, secrets, dependencies, images, or trust boundaries change;
5. update current engineering-support documentation when its commands, paths, or executable measurement/test contracts change;
6. add or strengthen documentation contract tests when a stale statement could otherwise recur;
7. leave point-in-time historical artifacts intact unless the change is specifically about correcting that historical record.

Current behavior must be derived from source, configuration, tests, and the living documents above—not from an old milestone TODO or evidence file.
