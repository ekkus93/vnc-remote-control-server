#!/usr/bin/env python3
"""Verify cargo-auditable metadata embedded in a Linux release binary."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any, NoReturn

SECTION_NAME = ".dep-v0"
MAX_DECOMPRESSED_BYTES = 8 * 1024 * 1024
STANDARD_SOURCES = {"crates.io", "git", "local", "registry"}
KNOWN_KINDS = {"build", "runtime"}


def fail(message: str) -> NoReturn:
    """Abort verification with a prefixed, non-zero-exit failure message."""
    raise SystemExit(f"auditable binary verification failed: {message}")


def extract_section(binary: Path) -> bytes:
    """Extract the raw compressed cargo-auditable metadata section from an ELF binary."""
    with tempfile.TemporaryDirectory(prefix="vrc-auditable-") as directory:
        section_path = Path(directory) / "dep-v0.zlib"
        result = subprocess.run(
            [
                "objcopy",
                "--dump-section",
                f"{SECTION_NAME}={section_path}",
                str(binary),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "objcopy failed"
            fail(f"cannot extract {SECTION_NAME}: {detail}")
        if not section_path.is_file():
            fail(f"objcopy did not produce the {SECTION_NAME} section")
        section = section_path.read_bytes()
    if not section:
        fail(f"the {SECTION_NAME} section is empty")
    return section


def decompress_metadata(compressed: bytes) -> bytes:
    """Decompress the zlib-compressed metadata section, bounding output to a safe size."""
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(compressed, MAX_DECOMPRESSED_BYTES + 1)
    if len(decoded) > MAX_DECOMPRESSED_BYTES or decoder.unconsumed_tail:
        fail(f"decompressed metadata exceeds {MAX_DECOMPRESSED_BYTES} bytes")
    decoded += decoder.flush(MAX_DECOMPRESSED_BYTES + 1 - len(decoded))
    if len(decoded) > MAX_DECOMPRESSED_BYTES:
        fail(f"decompressed metadata exceeds {MAX_DECOMPRESSED_BYTES} bytes")
    if not decoder.eof:
        fail("metadata is not a complete zlib stream")
    if decoder.unused_data:
        fail("metadata contains trailing bytes after the zlib stream")
    return decoded


def validate_source(source: Any, index: int) -> None:
    """Validate that a package's source is a non-empty string per the auditable-serde format."""
    # auditable-serde serializes Source as a string. The four standard values are
    # crates.io, git, local, and registry, but the upstream enum is deliberately
    # extensible, so any non-empty string is structurally valid.
    if not isinstance(source, str) or not source:
        fail(f"package {index} has an invalid source")


def _validate_format_revision(metadata: dict[str, Any]) -> None:
    """Validate that the metadata's format revision is a non-negative integer."""
    format_revision = metadata.get("format", 0)
    if isinstance(format_revision, bool) or not isinstance(format_revision, int):
        fail("format revision must be a non-negative integer")
    if format_revision < 0:
        fail("format revision must be a non-negative integer")


def _validate_package(package: Any, index: int, package_count: int) -> bool:
    """Validate one package entry's fields and return whether it is marked as the root."""
    if not isinstance(package, dict):
        fail(f"package {index} must be an object")
    for field in ("name", "version", "source"):
        if field not in package:
            fail(f"package {index} is missing {field}")
    if not isinstance(package["name"], str) or not package["name"]:
        fail(f"package {index} has an invalid name")
    if not isinstance(package["version"], str) or not package["version"]:
        fail(f"package {index} has an invalid version")
    validate_source(package["source"], index)

    root = package.get("root", False)
    if not isinstance(root, bool):
        fail(f"package {index} has a non-boolean root field")

    kind = package.get("kind", "runtime")
    if not isinstance(kind, str) or kind not in KNOWN_KINDS:
        fail(f"package {index} has an invalid dependency kind")

    dependencies = package.get("dependencies", [])
    if not isinstance(dependencies, list):
        fail(f"package {index} dependencies must be an array")
    for dependency in dependencies:
        if isinstance(dependency, bool) or not isinstance(dependency, int):
            fail(f"package {index} contains a non-integer dependency index")
        if dependency < 0 or dependency >= package_count:
            fail(f"package {index} contains an out-of-range dependency index")
    return root


def _validate_root_package(
    packages: list[dict[str, Any]], root_indices: list[int], expected_root: str
) -> int:
    """Validate that exactly one root package exists and its name matches expectations."""
    if len(root_indices) != 1:
        fail(f"expected exactly one root package, found {len(root_indices)}")
    root_index = root_indices[0]
    if packages[root_index]["name"] != expected_root:
        fail(
            "root package name mismatch: "
            f"expected {expected_root!r}, found {packages[root_index]['name']!r}"
        )
    return root_index


def _check_dependency_cycles(packages: list[dict[str, Any]]) -> None:
    """Fail if the package dependency graph contains a cycle."""
    states = [0] * len(packages)

    def visit(index: int) -> None:
        if states[index] == 1:
            fail("dependency graph contains a cycle")
        if states[index] == 2:
            return
        states[index] = 1
        for dependency in packages[index].get("dependencies", []):
            visit(dependency)
        states[index] = 2

    for index in range(len(packages)):
        visit(index)


def validate_metadata(metadata: Any, expected_root: str) -> tuple[list[dict[str, Any]], int]:
    """Validate decoded auditable-metadata JSON and return its packages and root index."""
    if not isinstance(metadata, dict):
        fail("top-level metadata must be a JSON object")

    _validate_format_revision(metadata)

    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        fail("packages must be a non-empty array")

    root_indices = [
        index
        for index, package in enumerate(packages)
        if _validate_package(package, index, len(packages))
    ]

    root_index = _validate_root_package(packages, root_indices, expected_root)
    _check_dependency_cycles(packages)
    return packages, root_index


def main() -> None:
    """CLI entry point: verify embedded auditable metadata and write an evidence report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--expected-root",
        help="expected root package name; defaults to the binary file name",
    )
    arguments = parser.parse_args()

    binary = arguments.binary.resolve()
    if not binary.is_file():
        fail(f"binary does not exist: {binary}")
    binary_bytes = binary.read_bytes()
    if not binary_bytes.startswith(b"\x7fELF"):
        fail("binary is not an ELF executable")

    compressed = extract_section(binary)
    decoded = decompress_metadata(compressed)
    try:
        metadata = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"metadata is not valid UTF-8 JSON: {error}")

    expected_root = arguments.expected_root or binary.name
    packages, root_index = validate_metadata(metadata, expected_root)
    root = packages[root_index]

    evidence = {
        "schema_version": 1,
        "binary": str(binary),
        "binary_sha256": hashlib.sha256(binary_bytes).hexdigest(),
        "binary_size_bytes": len(binary_bytes),
        "section": SECTION_NAME,
        "compressed_metadata_bytes": len(compressed),
        "decompressed_metadata_bytes": len(decoded),
        "metadata_format": metadata.get("format", 0),
        "package_count": len(packages),
        "root_package": {
            "index": root_index,
            "name": root["name"],
            "version": root["version"],
            "source": root["source"],
        },
        "standard_source_package_count": sum(
            package["source"] in STANDARD_SOURCES for package in packages
        ),
        "metadata": metadata,
    }

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "verified auditable metadata: "
        f"root={root['name']}@{root['version']} packages={len(packages)}"
    )


if __name__ == "__main__":
    main()
