# ChatGPT-Readable CI Status Bridge

## Purpose

This repository publishes the latest authoritative `CI` result for `master` into a persistent GitHub issue. The issue gives ChatGPT and other connector-based tools a stable discovery point for the exact run ID, commit SHA, job IDs, step results, abnormal steps, timings, and artifact metadata.

The issue is an index into GitHub Actions. It does not replace native checks, job logs, artifacts, or branch protection.

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

## CI quality gates

The authoritative `CI` workflow currently validates the bridge itself because the application implementation has not started yet. It performs:

- Python compilation of the renderer and tests;
- deterministic unit tests for payload generation, malformed input, branch isolation, abnormal-step reporting, same-run state monotonicity, and issue-size compaction;
- static workflow-contract tests for permissions, no-checkout publisher behavior, branch scoping, stale-run checks, pagination, and artifact publication;
- upload of a small `ci-evidence-<run-id>` artifact so artifact indexing is exercised end to end.

As Rust, Docker, and integration-test code is added, their real quality gates must be added to this same authoritative workflow without weakening the bridge tests.

## ChatGPT operating procedure

During an implementation loop:

1. Record the candidate commit SHA.
2. Read issue `#1`.
3. Require its machine JSON `workflow.head_sha` to match the candidate SHA.
4. Use `workflow.run_id` to fetch jobs.
5. Use the exact failed job ID to fetch its log.
6. Fix the first meaningful failure and repeat.
7. Claim CI success only when issue `#1` reports `completed` / `success` for the exact candidate SHA.

## Validation record

Runtime evidence is added here after the first complete publisher validation.
