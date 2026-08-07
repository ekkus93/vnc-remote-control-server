# Contributing

## Branch policy

Project work is performed directly on `master` unless the repository owner explicitly requests another workflow. Do not create a branch or pull request without that instruction.

The intended branch-protection policy is documented even though direct-owner development is currently permitted: CI must pass for the exact candidate SHA, force pushes are prohibited, and destructive history rewrites are not part of normal development.

## Prerequisites

- Rust 1.97.1 through `rustup`;
- Python 3.12 for first-party client, documentation, workflow, and policy contract tests;
- GNU Make;
- Docker Engine with Compose v2 for container milestones;
- a C compiler, `pkg-config`, and Debian's `libvncserver-dev` package for native development;
- `cargo-deny` for `make security-scan`;
- `shellcheck` and `actionlint` for reproducing the release-policy lint checks; Docker BuildKit provides Dockerfile validation through `docker build --check`.

## Quality policy

Warnings are defects. Do not suppress, hide, downgrade, or whitelist a warning merely to pass CI. Fix the underlying code or configuration. Do not weaken tests or convert a failing gate into a non-blocking step.

The permanent `CI` and `Release Gates` workflows are fail-closed. A release-candidate claim requires both workflows to complete successfully on the exact same candidate SHA.

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

Run all first-party Python, documentation, client/demo, workflow, and policy contracts with:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Every command uses fail-fast behavior where applicable and must avoid printing secret contents.

## Documentation discipline

[`docs/README.md`](docs/README.md) separates living/current documentation from historical engineering artifacts.

When behavior, API, deployment, security, or Python-client behavior changes, update the corresponding living documentation in the same change and strengthen contract tests when useful. Do not leave current behavior documented only in a dated TODO or implementation note.

Dated specs, TODOs, review notes, implementation notes, and evidence files are point-in-time project records. Preserve old commit SHAs, run IDs, failures, and then-current implementation descriptions in those records rather than rewriting history to match present `master`.

Substantial planned or hardening milestones may still use dated SPEC/TODO/EVIDENCE documents when that structure is useful. Ordinary focused changes do not require manufacturing a milestone trio merely to satisfy a documentation convention.

## Commit discipline

Keep each commit scoped to a coherent change. For substantial milestones, record exact candidate SHAs, validation commands, required workflow runs, test results, and known limitations in the appropriate evidence or implementation record. For ordinary changes, the relevant living docs and permanent exact-SHA CI/Release evidence are sufficient.
