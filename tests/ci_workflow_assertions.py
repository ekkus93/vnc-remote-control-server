"""Shared assertions reused by CI workflow contract tests to avoid duplication."""

from __future__ import annotations

import unittest


def assert_baseline_rust_gates(case: unittest.TestCase, text: str) -> None:
    """Assert the baseline fmt/clippy/test gates are present in workflow YAML `text`."""
    case.assertIn("cargo fmt --all --check", text)
    case.assertIn(
        "cargo clippy --locked --workspace --all-targets --all-features -- -D warnings",
        text,
    )
    case.assertIn("cargo test --locked --workspace --all-features", text)
