"""Contract tests for the CI status publisher's payload building and rendering.

These tests exercise `tools.ci_status.publish_status` directly: building the
machine-readable status payload from a workflow_run event plus jobs/artifacts
pages, rendering it into a size-bounded issue body, round-tripping it back out
of that body, and deciding whether a new run supersedes a previously
published one.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from tools.ci_status.publish_status import (
    PayloadError,
    build_payload,
    extract_existing_payload,
    render_bounded_issue_body,
    should_publish,
)

MARKER = "<!-- maintained by .github/workflows/publish-ci-status.yml -->"


def event(
    *, status: str = "completed", conclusion: str | None = "success", run_id: int = 101
) -> dict[str, Any]:
    """Build a minimal workflow_run webhook event payload for the given run state."""
    return {
        "workflow_run": {
            "name": "CI",
            "workflow_id": 777,
            "id": run_id,
            "run_attempt": 1,
            "html_url": (
                f"https://github.com/ekkus93/vnc-remote-control-server/actions/runs/{run_id}"
            ),
            "event": "push",
            "status": status,
            "conclusion": conclusion,
            "head_branch": "master",
            "head_sha": "a" * 40,
            "created_at": "2026-08-03T22:00:00Z",
            "updated_at": "2026-08-03T22:05:00Z",
        }
    }


def step(number: int, name: str, conclusion: str = "success") -> dict[str, Any]:
    """Build a single completed job step record."""
    return {
        "number": number,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": "2026-08-03T22:00:00Z",
        "completed_at": "2026-08-03T22:01:00Z",
    }


def job(
    job_id: int,
    name: str,
    conclusion: str | None = "success",
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a job record, defaulting to a single successful "Run tests" step."""
    return {
        "id": job_id,
        "name": name,
        "status": "completed" if conclusion is not None else "in_progress",
        "conclusion": conclusion,
        "started_at": "2026-08-03T22:00:00Z",
        "completed_at": "2026-08-03T22:02:00Z" if conclusion is not None else None,
        "runner_name": "GitHub Actions 1",
        "runner_group_name": "GitHub Actions",
        "steps": steps if steps is not None else [step(1, "Run tests", conclusion or "success")],
    }


def artifact(artifact_id: int = 301) -> dict[str, Any]:
    """Build a single CI evidence artifact record."""
    return {
        "id": artifact_id,
        "name": "ci-evidence",
        "size_in_bytes": 1234,
        "expired": False,
        "created_at": "2026-08-03T22:03:00Z",
        "expires_at": "2026-11-01T22:03:00Z",
    }


def payload_for(
    *,
    event_value: dict[str, Any] | None = None,
    jobs: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a status payload for the given event/jobs/artifacts, defaulting a completed run."""
    return build_payload(
        event=event_value or event(),
        jobs_pages=[{"total_count": len(jobs or []), "jobs": jobs or []}],
        artifacts_pages=[{"total_count": len(artifacts or []), "artifacts": artifacts or []}],
        issue_number=1,
        monitored_branch="master",
        publisher_workflow_file=".github/workflows/publish-ci-status.yml",
    )


class PublishStatusTests(unittest.TestCase):
    """Assert build_payload, render_bounded_issue_body, and should_publish behavior."""

    def test_completed_success_contains_jobs_steps_and_artifacts(self) -> None:
        """A completed successful run's payload must carry its jobs, steps, and artifacts."""
        payload = payload_for(jobs=[job(201, "quality")], artifacts=[artifact()])
        self.assertEqual(payload["jobs_data_state"], "available")
        self.assertEqual(payload["artifacts_data_state"], "available")
        self.assertEqual(payload["jobs"][0]["id"], 201)
        self.assertEqual(payload["jobs"][0]["steps"][0]["name"], "Run tests")
        self.assertEqual(payload["artifacts"][0]["id"], 301)
        self.assertEqual(payload["problem_steps"], [])

    def test_requested_run_does_not_fabricate_successful_jobs(self) -> None:
        """A queued/requested run must report pending job and artifact data, not empty success."""
        payload = build_payload(
            event=event(status="queued", conclusion=None),
            jobs_pages=[{"total_count": 0, "jobs": []}],
            artifacts_pages=[],
            issue_number=1,
            monitored_branch="master",
            publisher_workflow_file=".github/workflows/publish-ci-status.yml",
        )
        self.assertEqual(payload["jobs_data_state"], "pending")
        self.assertEqual(payload["artifacts_data_state"], "pending")
        self.assertEqual(payload["jobs"], [])
        self.assertEqual(payload["artifacts"], [])

    def test_failed_step_is_reported_with_exact_job_id(self) -> None:
        """A failing step must be reported under its exact job id and step number."""
        failing_job = job(
            202,
            "quality `special`",
            "failure",
            steps=[step(1, "Checkout"), step(2, "Run unit tests", "failure")],
        )
        payload = payload_for(jobs=[failing_job], artifacts=[])
        self.assertEqual(payload["problem_jobs"][0]["job_id"], 202)
        self.assertEqual(payload["problem_steps"][0]["step_number"], 2)
        self.assertEqual(payload["problem_steps"][0]["step"], "Run unit tests")

    def test_wrong_branch_is_rejected(self) -> None:
        """A run reported on an unmonitored branch must be rejected."""
        bad_event = event()
        bad_event["workflow_run"]["head_branch"] = "feature/unrelated"
        with self.assertRaises(PayloadError):
            payload_for(event_value=bad_event, jobs=[], artifacts=[])

    def test_duplicate_job_id_is_rejected(self) -> None:
        """Two jobs sharing the same id must be rejected as malformed input."""
        with self.assertRaises(PayloadError):
            payload_for(jobs=[job(201, "one"), job(201, "two")], artifacts=[])

    def test_successful_steps_are_compacted_without_invalid_json(self) -> None:
        """Oversized successful-job bodies must compact their steps while staying valid JSON."""
        many_steps = [step(i, f"Successful step {i} " + "x" * 100) for i in range(1, 80)]
        payload = payload_for(jobs=[job(201, "quality", steps=many_steps)], artifacts=[artifact()])
        body, compacted = render_bounded_issue_body(MARKER, payload, max_body_bytes=7_000)
        self.assertTrue(compacted["details_compacted"])
        self.assertEqual(compacted["jobs"][0]["steps"], [])
        self.assertEqual(compacted["jobs"][0]["step_count"], 79)
        self.assertEqual(extract_existing_payload(body), compacted)

    def test_abnormal_steps_are_not_compacted_away(self) -> None:
        """A job with a failing step must keep its full step list even when oversized."""
        many_steps = [step(i, f"Step {i}") for i in range(1, 30)]
        many_steps[-1]["conclusion"] = "failure"
        payload = payload_for(jobs=[job(201, "quality", "failure", many_steps)], artifacts=[])
        body, compacted = render_bounded_issue_body(MARKER, payload, max_body_bytes=60_000)
        self.assertFalse(compacted["details_compacted"])
        self.assertIn("Step 29", body)

    def test_same_run_cannot_regress_from_completed_to_in_progress(self) -> None:
        """A stale in-progress update for an already-completed run must not publish."""
        existing = payload_for(jobs=[job(201, "quality")], artifacts=[artifact()])
        incoming = build_payload(
            event=event(status="in_progress", conclusion=None),
            jobs_pages=[{"total_count": 1, "jobs": [job(201, "quality", conclusion=None)]}],
            artifacts_pages=[],
            issue_number=1,
            monitored_branch="master",
            publisher_workflow_file=".github/workflows/publish-ci-status.yml",
        )
        publish, reason = should_publish(existing, incoming)
        self.assertFalse(publish)
        self.assertEqual(reason, "same_run_state_regression")

    def test_newer_run_supersedes_old_run(self) -> None:
        """A newer run id must always supersede an older published run."""
        existing = payload_for(jobs=[job(201, "quality")], artifacts=[artifact()])
        incoming = payload_for(
            event_value=event(run_id=102), jobs=[job(203, "quality")], artifacts=[]
        )
        publish, reason = should_publish(existing, incoming)
        self.assertTrue(publish)
        self.assertEqual(reason, "newer_run")

    def test_existing_issue_identity_mismatch_fails_closed(self) -> None:
        """An existing payload belonging to a different issue must fail closed."""
        existing = copy.deepcopy(payload_for(jobs=[job(201, "quality")], artifacts=[]))
        existing["publisher"]["issue_number"] = 999
        incoming = payload_for(event_value=event(run_id=102), jobs=[], artifacts=[])
        with self.assertRaises(PayloadError):
            should_publish(existing, incoming)

    def test_malformed_existing_json_is_rejected(self) -> None:
        """A malformed machine-readable JSON block in an existing issue must be rejected."""
        body = f"{MARKER}\n```json\n{{not-json}}\n```\n"
        with self.assertRaises(PayloadError):
            extract_existing_payload(body)

    def test_payload_round_trips_as_machine_json(self) -> None:
        """A rendered issue body's payload must round-trip exactly and stay valid JSON."""
        payload = payload_for(jobs=[job(201, "quality")], artifacts=[artifact()])
        body, bounded = render_bounded_issue_body(MARKER, payload)
        parsed = extract_existing_payload(body)
        self.assertEqual(parsed, bounded)
        json.dumps(parsed)


if __name__ == "__main__":
    unittest.main()
