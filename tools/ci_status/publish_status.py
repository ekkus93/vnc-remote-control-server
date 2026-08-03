#!/usr/bin/env python3
"""Render a bounded, deterministic GitHub issue body for the latest CI run.

The workflow_run publisher fetches this file from the repository's trusted
default branch. It never imports or executes code from the triggering branch.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
DEFAULT_MAX_BODY_BYTES = 60_000
ABNORMAL_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}
STATUS_RANK = {
    "requested": 0,
    "queued": 0,
    "waiting": 0,
    "pending": 0,
    "in_progress": 1,
    "completed": 2,
}
JSON_BLOCK_RE = re.compile(r"```json\n(\{.*?\})\n```", re.DOTALL)


class PayloadError(ValueError):
    """Raised when GitHub API or event data does not match the expected shape."""


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PayloadError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PayloadError(f"{label} must be an array")
    return value


def _require_str(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PayloadError(f"{label} must be a string")
    if not allow_empty and not value:
        raise PayloadError(f"{label} must not be empty")
    return value


def _optional_str(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, label, allow_empty=True)


def _require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadError(f"{label} must be an integer")
    return value


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PayloadError(f"invalid ISO-8601 timestamp: {value!r}") from exc


def _flatten_pages(raw_pages: Any, key: str) -> list[dict[str, Any]]:
    pages = _require_list(raw_pages, f"{key} pages")
    flattened: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for page_index, raw_page in enumerate(pages):
        page = _require_dict(raw_page, f"{key} page {page_index}")
        entries = _require_list(page.get(key), f"{key} page {page_index}.{key}")
        for entry_index, raw_entry in enumerate(entries):
            entry = _require_dict(raw_entry, f"{key} entry {entry_index}")
            entry_id = _require_int(entry.get("id"), f"{key} entry {entry_index}.id")
            if entry_id in seen_ids:
                raise PayloadError(f"duplicate {key} id {entry_id}")
            seen_ids.add(entry_id)
            flattened.append(entry)
    return flattened


def _normalize_step(raw: dict[str, Any], job_id: int, index: int) -> dict[str, Any]:
    return {
        "number": _require_int(raw.get("number"), f"job {job_id} step {index}.number"),
        "name": _require_str(raw.get("name"), f"job {job_id} step {index}.name"),
        "status": _require_str(raw.get("status"), f"job {job_id} step {index}.status"),
        "conclusion": _optional_str(raw.get("conclusion"), f"job {job_id} step {index}.conclusion"),
        "started_at": _optional_str(raw.get("started_at"), f"job {job_id} step {index}.started_at"),
        "completed_at": _optional_str(raw.get("completed_at"), f"job {job_id} step {index}.completed_at"),
    }


def _normalize_job(raw: dict[str, Any], index: int) -> dict[str, Any]:
    job_id = _require_int(raw.get("id"), f"job {index}.id")
    raw_steps = _require_list(raw.get("steps", []), f"job {job_id}.steps")
    steps = [
        _normalize_step(_require_dict(step, f"job {job_id} step {step_index}"), job_id, step_index)
        for step_index, step in enumerate(raw_steps)
    ]
    return {
        "id": job_id,
        "name": _require_str(raw.get("name"), f"job {job_id}.name"),
        "status": _require_str(raw.get("status"), f"job {job_id}.status"),
        "conclusion": _optional_str(raw.get("conclusion"), f"job {job_id}.conclusion"),
        "started_at": _optional_str(raw.get("started_at"), f"job {job_id}.started_at"),
        "completed_at": _optional_str(raw.get("completed_at"), f"job {job_id}.completed_at"),
        "runner_name": _optional_str(raw.get("runner_name"), f"job {job_id}.runner_name"),
        "runner_group_name": _optional_str(
            raw.get("runner_group_name"), f"job {job_id}.runner_group_name"
        ),
        "steps": steps,
    }


def _normalize_artifact(raw: dict[str, Any], index: int) -> dict[str, Any]:
    artifact_id = _require_int(raw.get("id"), f"artifact {index}.id")
    expired = raw.get("expired")
    if not isinstance(expired, bool):
        raise PayloadError(f"artifact {artifact_id}.expired must be a boolean")
    return {
        "id": artifact_id,
        "name": _require_str(raw.get("name"), f"artifact {artifact_id}.name"),
        "size_in_bytes": _require_int(
            raw.get("size_in_bytes"), f"artifact {artifact_id}.size_in_bytes"
        ),
        "expired": expired,
        "created_at": _optional_str(raw.get("created_at"), f"artifact {artifact_id}.created_at"),
        "expires_at": _optional_str(raw.get("expires_at"), f"artifact {artifact_id}.expires_at"),
    }


def _event_metadata(event: dict[str, Any], monitored_branch: str) -> dict[str, Any]:
    run = _require_dict(event.get("workflow_run"), "event.workflow_run")
    head_branch = _require_str(run.get("head_branch"), "workflow_run.head_branch")
    if head_branch != monitored_branch:
        raise PayloadError(
            f"event branch {head_branch!r} does not match monitored branch {monitored_branch!r}"
        )
    return {
        "name": _require_str(run.get("name"), "workflow_run.name"),
        "workflow_id": _require_int(run.get("workflow_id"), "workflow_run.workflow_id"),
        "run_id": _require_int(run.get("id"), "workflow_run.id"),
        "run_attempt": _require_int(run.get("run_attempt"), "workflow_run.run_attempt"),
        "run_url": _require_str(run.get("html_url"), "workflow_run.html_url"),
        "event": _require_str(run.get("event"), "workflow_run.event"),
        "status": _require_str(run.get("status"), "workflow_run.status"),
        "conclusion": _optional_str(run.get("conclusion"), "workflow_run.conclusion"),
        "head_branch": head_branch,
        "head_sha": _require_str(run.get("head_sha"), "workflow_run.head_sha"),
        "created_at": _require_str(run.get("created_at"), "workflow_run.created_at"),
        "updated_at": _require_str(run.get("updated_at"), "workflow_run.updated_at"),
    }


def _problem_data(jobs: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    problem_jobs: list[dict[str, Any]] = []
    problem_steps: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("conclusion") in ABNORMAL_CONCLUSIONS:
            problem_jobs.append(
                {
                    "job_id": job["id"],
                    "job": job["name"],
                    "conclusion": job["conclusion"],
                }
            )
        for step in job["steps"]:
            if step.get("conclusion") in ABNORMAL_CONCLUSIONS:
                problem_steps.append(
                    {
                        "job_id": job["id"],
                        "job": job["name"],
                        "step_number": step["number"],
                        "step": step["name"],
                        "conclusion": step["conclusion"],
                    }
                )
    return problem_jobs, problem_steps


def build_payload(
    *,
    event: dict[str, Any],
    jobs_pages: Any,
    artifacts_pages: Any,
    issue_number: int,
    monitored_branch: str,
    publisher_workflow_file: str,
) -> dict[str, Any]:
    workflow = _event_metadata(event, monitored_branch)
    jobs = [
        _normalize_job(raw, index)
        for index, raw in enumerate(_flatten_pages(jobs_pages, "jobs"))
    ]
    if workflow["status"] == "completed":
        artifacts = [
            _normalize_artifact(raw, index)
            for index, raw in enumerate(_flatten_pages(artifacts_pages, "artifacts"))
        ]
        artifacts_data_state = "available"
    else:
        if artifacts_pages not in ([], None):
            raise PayloadError("artifacts must not be supplied before the run completes")
        artifacts = []
        artifacts_data_state = "pending"

    if jobs:
        jobs_data_state = "available"
    elif workflow["status"] == "completed":
        jobs_data_state = "unavailable"
    else:
        jobs_data_state = "pending"

    problem_jobs, problem_steps = _problem_data(jobs)
    return {
        "schema_version": SCHEMA_VERSION,
        "publisher": {
            "workflow_file": publisher_workflow_file,
            "issue_number": issue_number,
            "monitored_branch": monitored_branch,
        },
        "workflow": workflow,
        "jobs_data_state": jobs_data_state,
        "artifacts_data_state": artifacts_data_state,
        "details_compacted": False,
        "compaction_reason": None,
        "problem_jobs": problem_jobs,
        "problem_steps": problem_steps,
        "jobs": jobs,
        "artifacts": artifacts,
        "observed_at": _iso_now(),
    }


def _max_backtick_run(text: str) -> int:
    return max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)


def _code_span(value: Any) -> str:
    text = "null" if value is None else str(value)
    delimiter = "`" * (_max_backtick_run(text) + 1)
    if text.startswith(("`", " ")) or text.endswith(("`", " ")):
        text = f" {text} "
    return f"{delimiter}{text}{delimiter}"


def _job_summary(payload: dict[str, Any]) -> str:
    if payload["jobs_data_state"] != "available":
        return payload["jobs_data_state"].capitalize()
    jobs = payload["jobs"]
    completed = sum(1 for job in jobs if job["status"] == "completed")
    failed = sum(1 for job in jobs if job.get("conclusion") in ABNORMAL_CONCLUSIONS)
    running = sum(1 for job in jobs if job["status"] == "in_progress")
    return f"{completed} completed, {failed} abnormal, {running} running"


def _render_problem_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if payload["problem_steps"]:
        for problem in payload["problem_steps"]:
            lines.append(
                "  - "
                f"{_code_span(problem['job'])} / {_code_span(problem['step'])} — "
                f"{_code_span(problem['conclusion'])} (job {_code_span(problem['job_id'])})"
            )
    elif payload["problem_jobs"]:
        for problem in payload["problem_jobs"]:
            lines.append(
                "  - "
                f"{_code_span(problem['job'])} — {_code_span(problem['conclusion'])} "
                f"(job {_code_span(problem['job_id'])})"
            )
    else:
        lines.append("  - None")
    return lines


def render_issue_body(marker: str, payload: dict[str, Any]) -> str:
    workflow = payload["workflow"]
    artifacts_summary = (
        str(len(payload["artifacts"]))
        if payload["artifacts_data_state"] == "available"
        else payload["artifacts_data_state"].capitalize()
    )
    lines = [
        marker,
        "# Latest CI",
        "",
        f"- **Status:** {_code_span(workflow['status'])}",
        f"- **Conclusion:** {_code_span(workflow['conclusion'] or 'pending')}",
        f"- **Run:** {_code_span(workflow['run_id'])}",
        f"- **Attempt:** {_code_span(workflow['run_attempt'])}",
        f"- **Commit:** {_code_span(workflow['head_sha'])}",
        f"- **Branch/event:** {_code_span(workflow['head_branch'])} / {_code_span(workflow['event'])}",
        f"- **Jobs:** {_code_span(_job_summary(payload))}",
        "- **Problem steps:**",
        *_render_problem_lines(payload),
        f"- **Artifacts:** {_code_span(artifacts_summary)}",
        f"- **Observed:** {_code_span(payload['observed_at'])}",
        "",
        "## Machine-readable status",
        "",
        "```json",
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        "```",
        "",
        "This issue is overwritten whenever the latest applicable run changes state. "
        "It is not a historical log.",
        "",
    ]
    return "\n".join(lines)


def _has_abnormal_step(job: dict[str, Any]) -> bool:
    return any(step.get("conclusion") in ABNORMAL_CONCLUSIONS for step in job["steps"])


def render_bounded_issue_body(
    marker: str,
    payload: dict[str, Any],
    *,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> tuple[str, dict[str, Any]]:
    body = render_issue_body(marker, payload)
    if len(body.encode("utf-8")) <= max_body_bytes:
        return body, payload

    compacted = copy.deepcopy(payload)
    compacted["details_compacted"] = True
    compacted["compaction_reason"] = "issue_body_size_limit"
    for job in compacted["jobs"]:
        if job.get("conclusion") not in ABNORMAL_CONCLUSIONS and not _has_abnormal_step(job):
            job["step_count"] = len(job["steps"])
            job["steps_compacted"] = True
            job["steps"] = []

    body = render_issue_body(marker, compacted)
    if len(body.encode("utf-8")) > max_body_bytes:
        raise PayloadError(
            "issue body remains too large after compacting successful job steps; refusing invalid truncation"
        )
    return body, compacted


def extract_existing_payload(issue_body: str) -> dict[str, Any] | None:
    match = JSON_BLOCK_RE.search(issue_body)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PayloadError("existing issue contains malformed machine-readable JSON") from exc
    return _require_dict(payload, "existing issue payload")


def should_publish(existing_payload: dict[str, Any] | None, incoming_payload: dict[str, Any]) -> tuple[bool, str]:
    if existing_payload is None:
        return True, "initial_publish"

    existing_publisher = _require_dict(existing_payload.get("publisher"), "existing publisher")
    incoming_publisher = incoming_payload["publisher"]
    if existing_publisher.get("issue_number") != incoming_publisher["issue_number"]:
        raise PayloadError("existing issue JSON belongs to a different issue number")
    if existing_publisher.get("monitored_branch") != incoming_publisher["monitored_branch"]:
        raise PayloadError("existing issue JSON belongs to a different monitored branch")

    existing_workflow = _require_dict(existing_payload.get("workflow"), "existing workflow")
    incoming_workflow = incoming_payload["workflow"]
    existing_run_id = _require_int(existing_workflow.get("run_id"), "existing workflow.run_id")
    incoming_run_id = incoming_workflow["run_id"]

    if existing_run_id > incoming_run_id:
        return False, "existing_issue_has_newer_run"
    if existing_run_id < incoming_run_id:
        return True, "newer_run"

    existing_status = _require_str(existing_workflow.get("status"), "existing workflow.status")
    incoming_status = incoming_workflow["status"]
    existing_rank = STATUS_RANK.get(existing_status, -1)
    incoming_rank = STATUS_RANK.get(incoming_status, -1)
    if existing_rank > incoming_rank:
        return False, "same_run_state_regression"
    if existing_rank < incoming_rank:
        return True, "same_run_state_advance"

    existing_updated = _parse_iso(_optional_str(existing_workflow.get("updated_at"), "existing updated_at"))
    incoming_updated = _parse_iso(incoming_workflow.get("updated_at"))
    if existing_updated and incoming_updated and existing_updated >= incoming_updated:
        return False, "duplicate_or_older_same_state_event"
    return True, "same_run_newer_observation"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PayloadError(f"invalid JSON in {path}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file", type=Path, required=True)
    parser.add_argument("--jobs-pages-file", type=Path, required=True)
    parser.add_argument("--artifacts-pages-file", type=Path, required=True)
    parser.add_argument("--current-issue-body-file", type=Path, required=True)
    parser.add_argument("--output-body", type=Path, required=True)
    parser.add_argument("--output-patch", type=Path, required=True)
    parser.add_argument("--output-decision", type=Path, required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--monitored-branch", required=True)
    parser.add_argument("--publisher-workflow-file", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        current_issue_body = args.current_issue_body_file.read_text(encoding="utf-8")
        lines = current_issue_body.splitlines()
        first_line = lines[0] if lines else ""
        if first_line != args.marker:
            raise PayloadError("status issue ownership marker does not match")

        payload = build_payload(
            event=_require_dict(_read_json(args.event_file), "event"),
            jobs_pages=_read_json(args.jobs_pages_file),
            artifacts_pages=_read_json(args.artifacts_pages_file),
            issue_number=args.issue_number,
            monitored_branch=args.monitored_branch,
            publisher_workflow_file=args.publisher_workflow_file,
        )
        existing_payload = extract_existing_payload(current_issue_body)
        publish, reason = should_publish(existing_payload, payload)
        _write_json(args.output_decision, {"publish": publish, "reason": reason})
        if not publish:
            return 0

        body, bounded_payload = render_bounded_issue_body(
            args.marker, payload, max_body_bytes=args.max_body_bytes
        )
        args.output_body.write_text(body, encoding="utf-8")
        _write_json(args.output_patch, {"body": body})
        round_trip = extract_existing_payload(body)
        if round_trip != bounded_payload:
            raise PayloadError("rendered machine-readable JSON did not round-trip")
        return 0
    except (OSError, PayloadError) as exc:
        print(f"publish_status: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
