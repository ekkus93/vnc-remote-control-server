# Contributing

## Branch policy

Project work is performed directly on `master` unless the repository owner explicitly requests another workflow. Do not create a branch or pull request without that instruction.

The intended branch-protection policy is documented even though direct-owner development is currently permitted: CI must pass for the exact candidate SHA, force pushes are prohibited, and destructive history rewrites are not part of normal development.

## Prerequisites

- Rust 1.97.1 through `rustup`;
- GNU Make;
- Docker Engine with Compose v2 for container milestones;
- a C compiler, `pkg-config`, and Debian's `libvncserver-dev` package for native development;
- `shellcheck`, `hadolint`, and `actionlint` for the complete quality surface.

## Quality policy

Warnings are defects. Do not suppress, hide, downgrade, or whitelist a warning merely to pass CI. Fix the underlying code or configuration. Do not weaken tests or convert a failing gate into a non-blocking step.

## Commands

```bash
make fmt
make lint
make test
make build
make compose-up
make compose-down
make integration-test
make e2e-test
make security-scan
```

Every command uses fail-fast shell behavior and must avoid printing secret contents.

## Commit discipline

Keep each commit scoped to a coherent milestone or repair. Update the governing TODO with exact commands, run IDs, job IDs, test results, and known limitations before marking a milestone complete.
