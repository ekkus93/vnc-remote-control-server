#!/usr/bin/env python3
"""Verify the reviewed Python MCP runtime dependency and license closure.

MCP-012 uses this verifier inside a fresh CPython 3.12/Linux virtual
environment after installing ``./python[mcp]`` under committed constraints.
It fails closed on dependency, target, package metadata, or license drift and
emits a deterministic JSON inventory on success.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

_NAME_SEPARATOR = re.compile(r"[-_.]+")
_EXACT_CONSTRAINT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)$"
)
_LICENSE_CLASSIFIER_PREFIX = "License :: "
_LOCAL_PROJECT = "vnc-remote-control-client"
_BOOTSTRAP_DISTRIBUTION = "pip"
_MAX_RAW_LICENSE_LENGTH = 128
_EXPECTED_TARGET = {
    "implementation": "CPython",
    "python_minor": "3.12",
    "platform": "linux",
}


class VerificationError(RuntimeError):
    """A fail-closed MCP runtime supply-chain policy violation."""


def _canonical_name(value: str) -> str:
    """Return a PEP-503-style normalized distribution name."""
    return _NAME_SEPARATOR.sub("-", value).lower()


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    """Require a JSON object-like value and return its typed view."""
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be a JSON object")
    return value


def _require_string(value: Any, label: str) -> str:
    """Require a non-empty string and return it."""
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{label} must be a non-empty string")
    return value


def _validate_package_entry(name: str, raw_entry: Any) -> str:
    """Validate one reviewed package entry and return its license family."""
    entry = _require_dict(raw_entry, f"policy.packages.{name}")
    _require_string(entry.get("version"), f"policy.packages.{name}.version")
    license_name = _require_string(
        entry.get("license"),
        f"policy.packages.{name}.license",
    )
    signals = entry.get("accepted_license_signals")
    if not isinstance(signals, list) or not signals:
        raise VerificationError(
            f"policy.packages.{name}.accepted_license_signals must be non-empty"
        )
    if any(not isinstance(signal, str) or not signal for signal in signals):
        raise VerificationError(
            f"policy.packages.{name}.accepted_license_signals has invalid data"
        )
    if len(set(signals)) != len(signals):
        raise VerificationError(
            f"policy.packages.{name}.accepted_license_signals has duplicates"
        )
    return license_name


def _load_policy(path: Path) -> dict[str, Any]:
    """Load and structurally validate the committed review policy."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    policy = _require_dict(raw, "policy")
    if policy.get("schema_version") != 1:
        raise VerificationError("policy schema_version must be exactly 1")
    if _require_dict(policy.get("target"), "policy.target") != _EXPECTED_TARGET:
        raise VerificationError("policy target must be exact CPython 3.12/Linux")

    _require_string(
        policy.get("direct_requirement"),
        "policy.direct_requirement",
    )
    packages = _require_dict(policy.get("packages"), "policy.packages")
    if not packages:
        raise VerificationError("policy.packages must not be empty")

    reviewed_licenses: set[str] = set()
    for raw_name, raw_entry in packages.items():
        name = _require_string(raw_name, "policy package name")
        if name != _canonical_name(name):
            raise VerificationError(
                f"policy package name must already be normalized: {name}"
            )
        reviewed_licenses.add(_validate_package_entry(name, raw_entry))

    families = policy.get("reviewed_license_families")
    if not isinstance(families, list):
        raise VerificationError("reviewed_license_families must be a string array")
    if any(not isinstance(value, str) or not value for value in families):
        raise VerificationError("reviewed_license_families contains invalid data")
    if families != sorted(reviewed_licenses):
        raise VerificationError(
            "reviewed_license_families must equal sorted package license reviews"
        )
    return policy


def _load_constraints(path: Path) -> dict[str, str]:
    """Parse only exact, marker-free package==version constraints."""
    constraints: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _EXACT_CONSTRAINT.fullmatch(line)
        if match is None:
            raise VerificationError(
                f"constraint line {line_number} is not exact package==version"
            )
        name = _canonical_name(match.group("name"))
        if name in constraints:
            raise VerificationError(f"duplicate constraint for {name}")
        constraints[name] = match.group("version")
    if not constraints:
        raise VerificationError("constraints file contains no runtime packages")
    return constraints


def _verify_target() -> None:
    """Refuse to claim this Linux/CPython-3.12 review on another target."""
    if platform.python_implementation() != "CPython":
        raise VerificationError("runtime verifier requires CPython")
    if sys.version_info[:2] != (3, 12):
        raise VerificationError("runtime verifier requires Python 3.12 exactly")
    if sys.platform != "linux":
        raise VerificationError("runtime verifier requires Linux")


def _verify_project_metadata(root: Path, direct_requirement: str) -> None:
    """Prove the core remains dependency-free and MCP is the sole exact extra."""
    pyproject_path = root / "python" / "pyproject.toml"
    metadata = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = _require_dict(metadata.get("project"), "pyproject.project")
    if project.get("dependencies") != []:
        raise VerificationError(
            "core Python package must have zero hard dependencies"
        )
    optional = _require_dict(
        project.get("optional-dependencies"),
        "pyproject.project.optional-dependencies",
    )
    if optional.get("mcp") != [direct_requirement]:
        raise VerificationError(
            "project MCP extra must contain only the reviewed direct requirement"
        )


def _single_metadata_value(
    metadata: importlib.metadata.PackageMetadata,
    field: str,
) -> str | None:
    """Return one metadata field while rejecting duplicate or non-string values."""
    values = metadata.get_all(field)
    if values is None:
        return None
    if len(values) != 1:
        raise VerificationError(
            f"installed distribution has repeated {field} metadata"
        )
    value = values[0]
    if not isinstance(value, str):
        raise VerificationError(
            f"installed distribution has non-string {field} metadata"
        )
    return value


def _installed_distributions() -> dict[str, importlib.metadata.Distribution]:
    """Return third-party runtime distributions after two named exclusions."""
    result: dict[str, importlib.metadata.Distribution] = {}
    ignored_seen: set[str] = set()
    ignored = {_LOCAL_PROJECT, _BOOTSTRAP_DISTRIBUTION}
    for distribution in importlib.metadata.distributions():
        raw_name = _single_metadata_value(distribution.metadata, "Name")
        if raw_name is None:
            raise VerificationError(
                "installed distribution is missing Name metadata"
            )
        name = _canonical_name(raw_name)
        if name in ignored:
            ignored_seen.add(name)
            continue
        if name in result:
            raise VerificationError(
                f"duplicate installed distribution metadata: {name}"
            )
        result[name] = distribution

    if _LOCAL_PROJECT not in ignored_seen:
        raise VerificationError(
            "local vnc-remote-control-client distribution is not installed"
        )
    if _BOOTSTRAP_DISTRIBUTION not in ignored_seen:
        raise VerificationError(
            "audit environment is missing pip bootstrap distribution"
        )
    return result


def _license_signals(
    distribution: importlib.metadata.Distribution,
) -> tuple[list[str], bool]:
    """Return bounded license signals and whether PEP 639 is authoritative."""
    expression = _single_metadata_value(
        distribution.metadata, "License-Expression"
    )
    if expression is not None and expression.strip():
        return [expression.strip()], True

    signals: list[str] = []
    raw_license = _single_metadata_value(distribution.metadata, "License")
    if raw_license is not None:
        stripped = raw_license.strip()
        usable_raw = (
            stripped
            and stripped.upper() != "UNKNOWN"
            and len(stripped) <= _MAX_RAW_LICENSE_LENGTH
        )
        if usable_raw:
            signals.append(stripped)

    for classifier in distribution.metadata.get_all("Classifier") or []:
        if classifier.startswith(_LICENSE_CLASSIFIER_PREFIX):
            signals.append(classifier)

    unique_signals = list(dict.fromkeys(signals))
    if not unique_signals:
        name = _single_metadata_value(distribution.metadata, "Name") or "<unknown>"
        raise VerificationError(
            f"installed package {name} has no reviewable license signal"
        )
    return unique_signals, False


def _expected_versions(policy_packages: dict[str, Any]) -> dict[str, str]:
    """Return exact package versions from the already-validated policy."""
    versions: dict[str, str] = {}
    for name, raw_entry in policy_packages.items():
        entry = _require_dict(raw_entry, f"policy.packages.{name}")
        versions[name] = _require_string(
            entry.get("version"),
            f"policy.packages.{name}.version",
        )
    return versions


def _verify_constraints(
    constraints: dict[str, str],
    expected_versions: dict[str, str],
) -> None:
    """Require constraints and reviewed versions to be exactly identical."""
    if constraints == expected_versions:
        return
    missing = sorted(set(expected_versions) - set(constraints))
    extra = sorted(set(constraints) - set(expected_versions))
    changed = sorted(
        name
        for name in set(constraints) & set(expected_versions)
        if constraints[name] != expected_versions[name]
    )
    raise VerificationError(
        "constraints and reviewed policy disagree: "
        f"missing={missing} extra={extra} changed={changed}"
    )


def _verify_distribution(
    name: str,
    distribution: importlib.metadata.Distribution,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Verify one exact version/license review and return its evidence row."""
    expected_version = _require_string(
        entry.get("version"),
        f"policy.packages.{name}.version",
    )
    if distribution.version != expected_version:
        raise VerificationError(
            f"installed version drift for {name}: expected "
            f"{expected_version}, got {distribution.version}"
        )

    accepted = entry.get("accepted_license_signals")
    if not isinstance(accepted, list):
        raise VerificationError(
            f"policy.packages.{name}.accepted_license_signals is invalid"
        )
    signals, expression_is_authoritative = _license_signals(distribution)
    if expression_is_authoritative:
        accepted_match = signals[0] in accepted
    else:
        accepted_match = any(signal in accepted for signal in signals)
    if not accepted_match:
        raise VerificationError(
            f"unreviewed license metadata for {name}; "
            "update policy only after review"
        )

    return {
        "name": name,
        "version": distribution.version,
        "reviewed_license": entry["license"],
        "observed_license_signals": signals,
        "pep639_expression_authoritative": expression_is_authoritative,
    }


def _verify_runtime(
    policy: dict[str, Any],
    constraints: dict[str, str],
) -> list[dict[str, Any]]:
    """Match the installed closure exactly against version and license review."""
    policy_packages = _require_dict(policy["packages"], "policy.packages")
    expected_versions = _expected_versions(policy_packages)
    _verify_constraints(constraints, expected_versions)

    installed = _installed_distributions()
    if set(installed) != set(expected_versions):
        missing = sorted(set(expected_versions) - set(installed))
        extra = sorted(set(installed) - set(expected_versions))
        raise VerificationError(
            "installed MCP runtime closure drifted: "
            f"missing={missing} extra={extra}"
        )

    inventory: list[dict[str, Any]] = []
    for name in sorted(expected_versions):
        entry = _require_dict(
            policy_packages[name],
            f"policy.packages.{name}",
        )
        inventory.append(
            _verify_distribution(name, installed[name], entry)
        )
    return inventory


def _parse_args() -> argparse.Namespace:
    """Parse verifier paths without introducing network or resolver options."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("security/python-mcp-runtime-policy.json"),
    )
    parser.add_argument(
        "--constraints",
        type=Path,
        default=Path("security/python-mcp-runtime-constraints.txt"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _rooted_path(root: Path, value: Path) -> Path:
    """Resolve a possibly root-relative CLI path deterministically."""
    if value.is_absolute():
        return value.resolve()
    return (root / value).resolve()


def main() -> int:
    """Verify policy and emit auditable deterministic JSON evidence."""
    args = _parse_args()
    root = args.root.resolve()
    policy_path = _rooted_path(root, args.policy)
    constraints_path = _rooted_path(root, args.constraints)
    output_path = args.output.resolve()

    try:
        _verify_target()
        policy = _load_policy(policy_path)
        constraints = _load_constraints(constraints_path)
        direct_requirement = _require_string(
            policy["direct_requirement"],
            "policy.direct_requirement",
        )
        _verify_project_metadata(root, direct_requirement)
        inventory = _verify_runtime(policy, constraints)
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        tomllib.TOMLDecodeError,
        TypeError,
        VerificationError,
    ) as error:
        print(
            f"python MCP runtime verification failed: {error}",
            file=sys.stderr,
        )
        return 2

    evidence = {
        "schema_version": 1,
        "target": policy["target"],
        "direct_requirement": direct_requirement,
        "package_count": len(inventory),
        "packages": inventory,
        "result": "reviewed-runtime-closure-matched",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"verified Python MCP runtime closure: {len(inventory)} packages"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
