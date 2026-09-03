"""Dependency-free contract tests for MCP tool outcome classification."""

from __future__ import annotations

import inspect
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from mcp_test_support import RecordingToolRegistrar, RegisteredTool
from vnc_remote_control.errors import (
    ApiError,
    CommandOutcomeUnknownError,
    ProtocolError,
    TransportError,
)
from vnc_remote_control.mcp_execution import (
    McpCallCapacityError,
    McpExecutorClosedError,
    McpUnexpectedControllerError,
)
from vnc_remote_control.mcp_outcomes import (
    McpOutcomeRegistrationError,
    McpOutcomeToolRegistrar,
)
from vnc_remote_control.models import CommandResponse


@dataclass(frozen=True, slots=True)
class FakeTextContent:
    """Minimal native-text stand-in used by dependency-free tests."""

    type: str
    text: str


@dataclass(frozen=True, slots=True)
class FakeCallToolResult:
    """Minimal CallToolResult stand-in used by dependency-free tests."""

    content: list[FakeTextContent]
    structured_content: dict[str, object] | None = None
    is_error: bool = False


class LocalMutationValidationError(ValueError):
    """Represent pre-controller mutation validation in registrar-only tests."""


def _text_content_factory(**kwargs: Any) -> FakeTextContent:
    """Construct one fake native text block."""
    return FakeTextContent(type=kwargs["type"], text=kwargs["text"])


def _call_tool_result_factory(**kwargs: Any) -> FakeCallToolResult:
    """Construct one fake native call-tool result."""
    return FakeCallToolResult(
        content=kwargs["content"],
        structured_content=kwargs.get("structured_content"),
        is_error=kwargs.get("is_error", False),
    )


def _annotations(*, read_only: bool) -> SimpleNamespace:
    """Return the one annotation field required by the classifier."""
    return SimpleNamespace(read_only_hint=read_only)


def _registrar(
    tools: dict[str, RegisteredTool],
) -> McpOutcomeToolRegistrar:
    """Return one dependency-free classifying tool registrar."""
    return McpOutcomeToolRegistrar(
        RecordingToolRegistrar(tools),
        call_tool_result_factory=_call_tool_result_factory,
        text_content_factory=_text_content_factory,
        mutation_validation_errors=(LocalMutationValidationError,),
    )


def _register_tool(
    *,
    read_only: bool,
    function: Any,
) -> tuple[Any, dict[str, Any]]:
    """Register one function and return the classified callable and metadata."""
    tools: dict[str, RegisteredTool] = {}
    _registrar(tools)(
        name="test_tool",
        description="test tool",
        annotations=_annotations(read_only=read_only),
        structured_output=True,
    )(function)
    return tools["test_tool"]


def _context(result: FakeCallToolResult) -> dict[str, object]:
    """Return one classified result's structured context."""
    if result.structured_content is None:
        raise AssertionError("classified tool error omitted structured content")
    return result.structured_content


def _raising_handler(error: Exception, calls: list[str], label: str) -> Any:
    """Return one async handler bound to an explicit error rather than a loop cell."""

    async def handler() -> CommandResponse:
        calls.append(label)
        raise error

    return handler


class McpOutcomeRegistrarTests(unittest.IsolatedAsyncioTestCase):
    """Verify exact error mapping without requiring the optional MCP SDK."""

    async def test_success_passes_through_once_and_preserves_signature(self) -> None:
        """A normal mutation success remains the original CommandResponse contract."""
        calls = 0

        async def mutation(x: int, y: int) -> CommandResponse:
            nonlocal calls
            calls += 1
            return CommandResponse(command_id=x + y, status="succeeded")

        classified, metadata = _register_tool(read_only=False, function=mutation)
        result = await classified(3, 4)
        self.assertEqual(result, CommandResponse(command_id=7, status="succeeded"))
        self.assertEqual(calls, 1)
        self.assertEqual(inspect.signature(classified), inspect.signature(mutation))
        self.assertIs(inspect.unwrap(classified), mutation)
        self.assertTrue(metadata["structured_output"])

    async def test_known_command_timeout_is_explicit_and_non_retryable(self) -> None:
        """Known-ID ambiguity preserves only sanitized recovery context."""
        calls = 0

        async def mutation() -> CommandResponse:
            nonlocal calls
            calls += 1
            raise CommandOutcomeUnknownError(
                504,
                "SENSITIVE_CONTROLLER_MESSAGE",
                command_id=41,
                request_id="req-41",
            )

        classified, _ = _register_tool(read_only=False, function=mutation)
        result = await classified()
        self.assertIsInstance(result, FakeCallToolResult)
        self.assertTrue(result.is_error)
        self.assertEqual(calls, 1)
        self.assertEqual(
            _context(result),
            {
                "kind": "command_outcome_unknown",
                "status_code": 504,
                "code": "command_timeout",
                "request_id": "req-41",
                "command_id": 41,
                "outcome": "unknown",
                "retry_safe": False,
                "instruction": (
                    "Use vnc_get_command_status(command_id) before deciding on any further "
                    "mutation; automatic replay is unsafe."
                ),
            },
        )
        self.assertIn("vnc_get_command_status", result.content[0].text)
        self.assertIn("automatic replay is unsafe", result.content[0].text)
        self.assertNotIn("SENSITIVE_CONTROLLER_MESSAGE", result.content[0].text)

    async def test_terminal_accepted_failure_preserves_sanitized_command_context(self) -> None:
        """A controller-known failed command is authoritative and never replayed."""
        calls = 0

        async def mutation() -> CommandResponse:
            nonlocal calls
            calls += 1
            raise ApiError(
                500,
                "SENSITIVE_FAILURE_MESSAGE",
                code="command_failed",
                request_id="req-42",
                command_id=42,
                outcome="failed",
                retry_safe=False,
            )

        classified, _ = _register_tool(read_only=False, function=mutation)
        result = await classified()
        self.assertEqual(calls, 1)
        self.assertEqual(
            _context(result),
            {
                "kind": "controller_api_error",
                "status_code": 500,
                "code": "command_failed",
                "request_id": "req-42",
                "command_id": 42,
                "outcome": "failed",
                "retry_safe": False,
                "instruction": "Do not automatically retry this mutation.",
            },
        )
        self.assertIn("automatic retry is unsafe", result.content[0].text)
        self.assertNotIn("SENSITIVE_FAILURE_MESSAGE", result.content[0].text)

    async def test_transport_protocol_and_unexpected_mutation_failures_are_unknown(self) -> None:
        """No-ID post-issuance failures all prohibit blind mutation replay."""
        errors = (
            TransportError("SENSITIVE_TRANSPORT_DETAIL"),
            ProtocolError("SENSITIVE_PROTOCOL_BODY"),
            McpUnexpectedControllerError("SENSITIVE_INTERNAL_DETAIL"),
        )
        for error in errors:
            calls: list[str] = []
            classified, _ = _register_tool(
                read_only=False,
                function=_raising_handler(error, calls, "mutation"),
            )
            with self.subTest(error_type=type(error).__name__):
                result = await classified()
                self.assertEqual(calls, ["mutation"])
                self.assertEqual(
                    _context(result),
                    {
                        "kind": "mutation_outcome_unknown",
                        "command_id": None,
                        "outcome": "unknown",
                        "retry_safe": False,
                        "instruction": (
                            "Automatic replay is unsafe because the controller may already have "
                            "received the mutation."
                        ),
                    },
                )
                self.assertIn("automatic replay is unsafe", result.content[0].text)
                self.assertNotIn("SENSITIVE", result.content[0].text)

    async def test_invalid_accepted_command_context_fails_closed_without_fabricated_id(
        self,
    ) -> None:
        """Inconsistent command metadata is downgraded to conservative no-ID ambiguity."""

        async def mutation() -> CommandResponse:
            raise ApiError(
                500,
                "bad command context",
                code="command_failed",
                request_id="req-43",
                command_id=0,
                outcome="failed",
                retry_safe=False,
            )

        classified, _ = _register_tool(read_only=False, function=mutation)
        result = await classified()
        self.assertEqual(_context(result)["kind"], "mutation_outcome_unknown")
        self.assertIsNone(_context(result)["command_id"])
        self.assertNotIn("request_id", _context(result))

    async def test_preflight_and_pre_admission_failures_do_not_claim_unknown_outcome(self) -> None:
        """Provably pre-request failures are distinct from post-issuance ambiguity."""
        cases = (
            (LocalMutationValidationError("bad local input"), "validation_error"),
            (McpCallCapacityError("full"), "adapter_internal_error"),
            (McpExecutorClosedError("closed"), "adapter_internal_error"),
        )
        for error, expected_kind in cases:
            calls: list[str] = []
            classified, _ = _register_tool(
                read_only=False,
                function=_raising_handler(error, calls, "mutation"),
            )
            with self.subTest(error_type=type(error).__name__):
                result = await classified()
                self.assertEqual(calls, ["mutation"])
                self.assertEqual(_context(result), {"kind": expected_kind})
                self.assertNotIn("outcome", _context(result))
                self.assertNotIn("command_id", _context(result))

    async def test_read_only_transport_protocol_and_api_errors_keep_distinct_kinds(self) -> None:
        """Read errors never inherit mutation-unknown semantics."""
        cases = (
            (TransportError("SENSITIVE_TRANSPORT_DETAIL"), "transport_error"),
            (ProtocolError("SENSITIVE_PROTOCOL_BODY"), "controller_protocol_error"),
            (
                ApiError(
                    503,
                    "SENSITIVE_API_MESSAGE",
                    code="unavailable",
                    request_id="req-read",
                ),
                "controller_api_error",
            ),
        )
        for error, expected_kind in cases:
            calls: list[str] = []
            classified, _ = _register_tool(
                read_only=True,
                function=_raising_handler(error, calls, "read"),
            )
            with self.subTest(error_type=type(error).__name__):
                result = await classified()
                self.assertEqual(calls, ["read"])
                self.assertEqual(_context(result)["kind"], expected_kind)
                self.assertNotEqual(expected_kind, "mutation_outcome_unknown")
                self.assertNotIn("SENSITIVE", result.content[0].text)

        api_context = _context(
            await _register_tool(
                read_only=True,
                function=_read_api_failure,
            )[0]()
        )
        self.assertEqual(api_context["status_code"], 503)
        self.assertEqual(api_context["code"], "unavailable")
        self.assertEqual(api_context["request_id"], "req-read")

    async def test_unexpected_read_failure_is_sanitized_adapter_error(self) -> None:
        """Unexpected controller exceptions are observable without exposing cause text."""

        async def read() -> CommandResponse:
            raise McpUnexpectedControllerError("SENSITIVE_INTERNAL_DETAIL")

        classified, _ = _register_tool(read_only=True, function=read)
        with self.assertLogs("vnc_remote_control.mcp_outcomes", level="ERROR") as logs:
            result = await classified()
        self.assertEqual(_context(result), {"kind": "adapter_internal_error"})
        self.assertNotIn("SENSITIVE_INTERNAL_DETAIL", result.content[0].text)
        self.assertNotIn("SENSITIVE_INTERNAL_DETAIL", "\n".join(logs.output))

    async def test_unexpected_mutation_failure_log_never_contains_exception_payload(self) -> None:
        """Unexpected mutation diagnostics use fixed context rather than exception text."""

        async def mutation() -> CommandResponse:
            raise McpUnexpectedControllerError("SENSITIVE_MUTATION_PAYLOAD")

        classified, _ = _register_tool(read_only=False, function=mutation)
        with self.assertLogs("vnc_remote_control.mcp_outcomes", level="ERROR") as logs:
            result = await classified()
        self.assertEqual(_context(result)["kind"], "mutation_outcome_unknown")
        self.assertNotIn("SENSITIVE_MUTATION_PAYLOAD", "\n".join(logs.output))

    async def test_unsafe_api_identifiers_are_omitted_not_echoed(self) -> None:
        """Untrusted request/code strings never bypass the bounded identifier grammar."""

        async def read() -> CommandResponse:
            raise ApiError(
                400,
                "message sentinel",
                code="bad code with spaces",
                request_id="request\nheader-injection",
            )

        classified, _ = _register_tool(read_only=True, function=read)
        result = await classified()
        self.assertEqual(
            _context(result),
            {"kind": "controller_api_error", "status_code": 400},
        )
        self.assertNotIn("bad code", result.content[0].text)
        self.assertNotIn("header-injection", result.content[0].text)

    def test_registration_requires_explicit_name_annotations_and_async_handler(self) -> None:
        """Classifier refuses registrations it cannot classify without guessing."""
        tools: dict[str, RegisteredTool] = {}
        registrar = _registrar(tools)
        with self.assertRaises(McpOutcomeRegistrationError):
            registrar(
                name="missing_annotations",
                description="x",
                structured_output=True,
            )
        with self.assertRaises(McpOutcomeRegistrationError):
            registrar(
                description="x",
                annotations=_annotations(read_only=True),
                structured_output=True,
            )

        def synchronous() -> CommandResponse:
            return CommandResponse(1, "succeeded")

        decorator = registrar(
            name="sync",
            description="x",
            annotations=_annotations(read_only=True),
            structured_output=True,
        )
        with self.assertRaises(McpOutcomeRegistrationError):
            decorator(synchronous)


async def _read_api_failure() -> CommandResponse:
    """Return a fixed structured read API failure for field-preservation assertions."""
    raise ApiError(
        503,
        "SENSITIVE_API_MESSAGE",
        code="unavailable",
        request_id="req-read",
    )


if __name__ == "__main__":
    unittest.main()
