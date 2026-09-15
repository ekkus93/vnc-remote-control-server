"""Regression tests for the post-FCR fail-closed hardening pass."""

from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
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

    def test_public_client_rejects_timeout_conversion_overflow_stably(self) -> None:
        """Huge positive integers fail with the public timeout validation contract."""
        with self.assertRaisesRegex(
            ValueError,
            "timeout must be a positive finite number",
        ):
            VncClient("http://controller", timeout=10**400)

    def test_public_client_rejects_non_string_base_url_stably(self) -> None:
        """Malformed base URL types do not leak parser-specific exceptions or reprs."""
        sensitive_value = SimpleNamespace(secret="SENSITIVE_BASE_URL_REPR")
        with self.assertRaisesRegex(ValueError, "base_url must be a string") as caught:
            VncClient(cast(Any, sensitive_value))
        self.assertNotIn("SENSITIVE_BASE_URL_REPR", str(caught.exception))

    def test_public_client_rejects_non_string_token_without_echo(self) -> None:
        """Malformed token types fail deterministically without echoing sensitive values."""
        sensitive_token = SimpleNamespace(secret="SENSITIVE_TOKEN_REPR")
        with self.assertRaisesRegex(
            ValueError,
            "token must be a string when provided",
        ) as caught:
            VncClient("http://controller", cast(Any, sensitive_token))
        self.assertNotIn("SENSITIVE_TOKEN_REPR", str(caught.exception))

    def test_public_client_preserves_normal_base_url_and_token_values(self) -> None:
        """Explicit type guards preserve accepted normal constructor values."""
        self.assertEqual(VncClient("http://controller").base_url, "http://controller")
        client = VncClient("https://controller.example", "token-value")
        self.assertEqual(client.base_url, "https://controller.example")
        self.assertNotIn("token-value", repr(client))


if __name__ == "__main__":
    unittest.main()
