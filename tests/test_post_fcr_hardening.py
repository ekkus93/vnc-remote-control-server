"""Regression tests for the post-FCR fail-closed hardening pass."""

from __future__ import annotations

import math
import unittest
from typing import Any, cast

from mcp_test_support import RecordingToolRegistrar
from vnc_remote_control import VncClient
from vnc_remote_control.mcp_outcomes import (
    McpOutcomeRegistrationError,
    McpOutcomeToolRegistrar,
)


class LocalMutationValidationError(ValueError):
    """Application-specific pre-controller validation failure for tests."""


def _registrar(*, mutation_validation_errors: Any) -> McpOutcomeToolRegistrar:
    """Construct one registrar with injected validation-error classes."""
    return McpOutcomeToolRegistrar(
        RecordingToolRegistrar({}),
        call_tool_result_factory=lambda **kwargs: kwargs,
        text_content_factory=lambda **kwargs: kwargs,
        mutation_validation_errors=cast(Any, mutation_validation_errors),
    )


class PostFcrHardeningTests(unittest.TestCase):
    """Verify strict boundaries added after the FCR review."""

    def test_mutation_validation_errors_require_exact_tuple_container(self) -> None:
        """Iterable containers cannot defer classification failure to call time."""
        invalid_containers: tuple[Any, ...] = (
            [LocalMutationValidationError],
            (error_type for error_type in (LocalMutationValidationError,)),
            "LocalMutationValidationError",
            b"LocalMutationValidationError",
            {LocalMutationValidationError},
        )
        for invalid_container in invalid_containers:
            with self.subTest(container_type=type(invalid_container).__name__):
                with self.assertRaisesRegex(
                    McpOutcomeRegistrationError,
                    "tuple of application-specific ValueError subclasses",
                ):
                    _registrar(mutation_validation_errors=invalid_container)

    def test_mutation_validation_errors_reject_broad_or_non_application_classes(self) -> None:
        """Broad builtins never become local validation-error classifications."""
        for error_type in (Exception, BaseException, ValueError, RuntimeError, object, 42):
            with self.subTest(error_type=repr(error_type)):
                with self.assertRaisesRegex(
                    McpOutcomeRegistrationError,
                    "tuple of application-specific ValueError subclasses",
                ):
                    _registrar(mutation_validation_errors=(error_type,))

    def test_mutation_validation_errors_accept_application_specific_tuple(self) -> None:
        """The intended tuple contract remains supported."""
        registrar = _registrar(mutation_validation_errors=(LocalMutationValidationError,))
        self.assertIsInstance(registrar, McpOutcomeToolRegistrar)

    def test_public_client_accepts_positive_numeric_timeouts(self) -> None:
        """Positive int and float timeouts are normalized without lossy defaults."""
        for value, expected in ((1, 1.0), (3.5, 3.5)):
            with self.subTest(value=value):
                client = VncClient("http://controller", timeout=value)
                self.assertEqual(client.timeout, expected)

    def test_public_client_rejects_invalid_timeout_values(self) -> None:
        """Timeout validation rejects bools, nonfinite values, and nonnumeric objects."""
        invalid_values = (
            True,
            False,
            0,
            -1,
            0.0,
            -0.1,
            math.nan,
            math.inf,
            -math.inf,
            "5",
            b"5",
            None,
            object(),
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(
                    ValueError,
                    "timeout must be a positive finite number",
                ):
                    VncClient("http://controller", timeout=cast(float, value))


if __name__ == "__main__":
    unittest.main()
