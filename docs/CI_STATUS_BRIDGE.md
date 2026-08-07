# ChatGPT-Readable CI Status Bridge

## Purpose

This repository publishes the latest authoritative `CI` result for `master` into a persistent GitHub issue. The issue gives ChatGPT and other connector-based tools a stable discovery point for the exact run ID, commit SHA, job IDs, step results, abnormal steps, timings, and artifact metadata.

The issue is an index into GitHub Actions. It does not replace native checks, job logs, artifacts, Release Gates, or branch protection.

## Configuration

| Setting | Value |
|---|---|
| Monitored workflow | `CI` |
| Monitored workflow file | `.github/workflows/ci.yml` |
| Monitored branch | `master` |
| Persistent status issue | `#1` — `CI Status: CI — master` |
| Publisher workflow | `.github/workflows/publish-ci-status.yml` |
| Publisher renderer | `tools/ci_status/publish_status.py` |

## Security contract

The publisher has only these permissions:

```yaml
permissions:
  actions: read
  contents: read
  issues: write
```

It does not check out the triggering commit or branch. The deterministic renderer is fetched from the trusted `master` branch through the GitHub Contents API. The publisher does not download or execute artifacts and does not copy job logs, environment variables, or secrets into the issue.

The status issue begins with this ownership marker:

```html
<!-- maintained by .github/workflows/publish-ci-status.yml -->
```

A missing or changed marker causes the publisher to fail closed rather than overwrite an unrelated issue.

## Stale-event and branch isolation

The publisher:

1. Rejects every event whose `head_branch` is not `master`.
2. Queries the latest run for the exact workflow ID and `master` branch before collecting data.
3. Repeats the latest-run check immediately before patching issue `#1`.
4. Uses a workflow-and-branch-specific concurrency group.
5. Prevents a late event for the same run from regressing an issue from `completed` to `in_progress` or `queued`.

## Published data

The issue contains a concise Markdown summary and a fenced JSON document with:

- workflow name and ID;
- run ID and attempt;
- run URL, event, status, and conclusion;
- monitored branch and exact head SHA;
- creation and update timestamps;
- every job ID, state, conclusion, runner, timing, and step;
- all abnormal jobs and steps;
- artifact IDs, names, sizes, expiry state, and timestamps;
- explicit job/artifact availability state;
- explicit compaction metadata when successful step details must be reduced to fit the issue body.

Pagination is enabled for jobs and artifacts. The renderer refuses to silently truncate invalid JSON.

## Current CI quality surface

The authoritative `CI` workflow validates the implemented Rust, Python, native VNC, Docker, API, and documentation surfaces. The exact step set may evolve with the repository, so `.github/workflows/ci.yml` is the machine authority; the current high-level contract is:

### Repository quality gates

- checkout and pinned Python/Rust setup;
- native build dependencies and locked Rust dependency fetch;
- `cargo fmt --check`;
- Clippy with warnings denied;
- complete Rust workspace tests;
- rustdoc with warnings denied;
- compilation of first-party Python;
- Python, documentation, client/demo, and workflow contract tests;
- first-party shell syntax checks;
- construction and upload of sanitized CI evidence.

### Secured Debian desktop and native adapter

- stock desktop image smoke test;
- native LibVNCClient adapter smoke test;
- real TigerVNC WorkerHandle pointer/input E2E;
- failure-diagnostics verification;
- real TigerVNC text and clipboard E2E;
- authenticated HTTP-to-TigerVNC E2E;
- production controller image, Compose, and persistence smoke validation;
- R13 Compose integration and E2E validation.

The bridge publishes this `CI` workflow only. Release acceptance additionally requires the separate permanent `Release Gates` workflow to pass on the exact same candidate SHA; see [`VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md`](VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md).

## ChatGPT operating procedure

During an implementation loop:

1. Record the candidate commit SHA.
2. Read issue `#1`.
3. Require its machine JSON `workflow.head_sha` to match the candidate SHA.
4. Use `workflow.run_id` to fetch jobs.
5. Use the exact failed job ID to fetch its log.
6. Fix the first meaningful failure and repeat.
7. Claim `CI` success only when issue `#1` reports `completed` / `success` for the exact candidate SHA.
8. When release acceptance is required, independently require `Release Gates` to be `completed` / `success` on that same exact SHA.

## Historical bridge-validation record

The records below document the original end-to-end validation of the status bridge itself. They are intentionally retained as point-in-time evidence; they are not the latest application acceptance runs.

### Successful initial bridge path

- Commit: `46aa19ac4e256e16c991878227bf696299e0f3c1`
- CI run: `30859425666`, attempt `1`
- Job: `91837912617` — `Repository quality gates`
- Result: `completed` / `success`
- Artifact: `8873739323` — `ci-evidence-30859425666`
- Artifact digest: `sha256:7b10e64f4fcb3bbbb5552e64786569c7b66fddc9f718c56545f0407668abf08f`
- The downloaded artifact identified the same commit SHA, run ID, attempt, workflow, and successful result.

### Real failure-path probe

A temporary unit-test probe was committed solely to validate failure publication and then removed.

- Probe commit: `be14542314637deec44e5b161fbc7592ae377494`
- CI run: `30859522752`, attempt `1`
- Job: `91838208347` — `Repository quality gates`
- Result: `completed` / `failure`
- Failed step: `Run CI bridge and workflow contract tests`, step `5`
- Issue `#1` published the exact failed job ID and failed step without copying raw logs.
- Probe removal commit: `b6524f77891ae8d7f089010521020aafd4b6d831`

The probe file is not present in the current repository. For present status, always read issue `#1` and require its reported SHA to match the candidate being evaluated.
