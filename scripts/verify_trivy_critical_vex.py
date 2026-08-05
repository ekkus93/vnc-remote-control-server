#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

Finding = tuple[str, str, str, str]


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 date: {value!r}") from error


def load_findings(paths: list[Path]) -> set[Finding]:
    findings: set[Finding] = set()
    for path in paths:
        suffix = "-vulnerabilities.json"
        if not path.name.endswith(suffix):
            raise ValueError(f"report name must end with {suffix}: {path}")
        image = path.name[: -len(suffix)]
        payload = json.loads(path.read_text(encoding="utf-8"))
        for result in payload.get("Results") or []:
            for vulnerability in result.get("Vulnerabilities") or []:
                if vulnerability.get("Severity") != "CRITICAL":
                    continue
                finding = (
                    image,
                    str(vulnerability.get("VulnerabilityID") or ""),
                    str(vulnerability.get("PkgName") or ""),
                    str(vulnerability.get("InstalledVersion") or ""),
                )
                if not all(finding):
                    raise ValueError(f"incomplete CRITICAL finding in {path}: {finding!r}")
                findings.add(finding)
    return findings


def load_vex(path: Path, today: date) -> tuple[set[Finding], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported VEX schema_version")
    reviewed = parse_date(str(payload.get("reviewed_at") or ""), "reviewed_at")
    expires = parse_date(str(payload.get("expires_at") or ""), "expires_at")
    if expires < today:
        raise ValueError(f"VEX expired on {expires.isoformat()}")
    if expires < reviewed or (expires - reviewed).days > 30:
        raise ValueError("VEX validity window must be between 0 and 30 days")
    if not isinstance(payload.get("tracking_issue"), int):
        raise ValueError("tracking_issue must be an integer")

    expected: set[Finding] = set()
    seen_ids: set[str] = set()
    for entry in payload.get("entries") or []:
        cve = str(entry.get("id") or "")
        if not cve.startswith("CVE-"):
            raise ValueError(f"invalid vulnerability id: {cve!r}")
        if cve in seen_ids:
            raise ValueError(f"duplicate VEX entry: {cve}")
        seen_ids.add(cve)
        if entry.get("decision") not in {"not_affected", "not_exploitable"}:
            raise ValueError(f"unsupported decision for {cve}")
        rationale = str(entry.get("rationale") or "")
        source = str(entry.get("source") or "")
        version = str(entry.get("installed_version") or "")
        if len(rationale) < 80:
            raise ValueError(f"rationale is too short for {cve}")
        if not source.startswith("https://security-tracker.debian.org/tracker/CVE-"):
            raise ValueError(f"untrusted source for {cve}: {source!r}")
        if not version:
            raise ValueError(f"installed_version is required for {cve}")
        packages = entry.get("packages")
        if not isinstance(packages, dict) or not packages:
            raise ValueError(f"packages are required for {cve}")
        for image, names in packages.items():
            if image not in {"controller", "desktop"}:
                raise ValueError(f"unsupported image for {cve}: {image!r}")
            if not isinstance(names, list) or not names:
                raise ValueError(f"package list is empty for {cve}/{image}")
            for package in names:
                finding = (image, cve, str(package), version)
                if finding in expected:
                    raise ValueError(f"duplicate exact VEX tuple: {finding!r}")
                expected.add(finding)
    if not expected:
        raise ValueError("VEX contains no exact findings")
    return expected, payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless every CRITICAL Trivy finding has an exact, current VEX determination."
    )
    parser.add_argument("--vex", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        observed = load_findings(args.reports)
        expected, vex = load_vex(args.vex, args.today)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"critical VEX validation error: {error}", file=sys.stderr)
        return 2

    unreviewed = sorted(observed - expected)
    stale = sorted(expected - observed)
    result = {
        "status": "passed" if not unreviewed and not stale else "failed",
        "reviewed_at": vex["reviewed_at"],
        "expires_at": vex["expires_at"],
        "tracking_issue": vex["tracking_issue"],
        "observed_critical_findings": len(observed),
        "unreviewed": [list(item) for item in unreviewed],
        "stale": [list(item) for item in stale],
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if unreviewed:
        print("unreviewed CRITICAL findings:", file=sys.stderr)
        for item in unreviewed:
            print("  " + " | ".join(item), file=sys.stderr)
    if stale:
        print("stale or mismatched VEX tuples:", file=sys.stderr)
        for item in stale:
            print("  " + " | ".join(item), file=sys.stderr)
    if unreviewed or stale:
        return 1
    print(
        f"validated {len(observed)} exact CRITICAL finding tuples; "
        f"VEX expires {vex['expires_at']} (tracking issue #{vex['tracking_issue']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
