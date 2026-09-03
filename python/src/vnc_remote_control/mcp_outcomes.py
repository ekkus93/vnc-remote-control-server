"""Fail-closed MCP tool outcome classification and sanitization."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from .errors import ApiError, CommandOutcomeUnknownError, ProtocolError, TransportError
from .mcp_execution import McpCallCapacityError, McpExecutorClosedError
from .mcp_tools import McpToolRegistrar

McpCallToolResultFactory = Callable[..., Any]
McpTextContentFactory = Callable[..., Any]

_MAX_IDENTIFIER_BYTES = 64
_COMMAND_UNKNOWN_INSTRUCTION = (
    "Use vnc_get_command_status(command_id) before deciding on any further mutation; "
    "automatic replay is unsafe."
)
_MUTATION_UNKNOWN_INSTRUCTION = (
    "Automatic replay is unsafe because the controller may already have received the mutation."
)
_ACCEPTED_FAILURE_INSTRUCTION = "Do not automatically retry this mutation."

_LOGGER = logging.getLogger(__name__)


class McpOutcomeRegistrationError(RuntimeError):
    """Raised when a tool cannot be wrapped without changing its contract."""


def _safe_identifier(value: object) -> str | None:
    """Return one bounded public identifier or omit untrusted text."""
    if not isinstance(value, str):
        return None
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return None
    if not 0 < len(encoded) <= _MAX_IDENTIFIER_BYTES:
        return None
    if not all(
        byte in b"._-"
        or ord("0") <= byte <= ord("9")
        or ord("A") <= byte <= ord("Z")
        or ord("a") <= byte <= ord("z")
        for byte in encoded
    ):
        return None
    return value


def _safe_status_code(value: object) -> int | None:
    """Return one real HTTP status code without bool coercion."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if not 100 <= value <= 599:
        return None
    return value


def _safe_command_id(value: object) -> int | None:
    """Return one positive command ID without bool coercion."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


def _api_context(error: ApiError) -> dict[str, object]:
    """Return sanitized non-payload controller API metadata."""
    context: dict[str, object] = {"kind": "controller_api_error"}
    status_code = _safe_status_code(error.status_code)
    code = _safe_identifier(error.code)
    request_id = _safe_identifier(error.request_id)
    if status_code is not None:
        context["status_code"] = status_code
    if code is not None:
        context["code"] = code
    if request_id is not None:
        context["request_id"] = request_id
    return context


def _error_result(
    *,
    call_tool_result_factory: McpCallToolResultFactory,
    text_content_factory: McpTextContentFactory,
    text: str,
    structured_content: dict[str, object],
) -> Any:
    """Build one native MCP tool error with model- and machine-readable context."""
    return call_tool_result_factory(
        content=[text_content_factory(type="text", text=text)],
        structured_content=structured_content,
        is_error=True,
    )


class McpOutcomeToolRegistrar:
    """Wrap one SDK registrar with explicit read/mutation outcome semantics."""

    def __init__(
        self,
        registrar: McpToolRegistrar,
        *,
        call_tool_result_factory: McpCallToolResultFactory,
        text_content_factory: McpTextContentFactory,
        mutation_validation_errors: tuple[type[Exception], ...],
    ) -> None:
        self._registrar = registrar
        self._call_tool_result_factory = call_tool_result_factory
        self._text_content_factory = text_content_factory
        self._mutation_validation_errors = mutation_validation_errors

    def _result(self, text: str, context: dict[str, object]) -> Any:
        """Build one classified tool error through exact injected SDK factories."""
        return _error_result(
            call_tool_result_factory=self._call_tool_result_factory,
            text_content_factory=self._text_content_factory,
            text=text,
            structured_content=context,
        )

    def _mutation_unknown(self) -> Any:
        """Return the conservative no-command-ID mutation ambiguity result."""
        return self._result(
            "Mutation outcome is unknown and no trustworthy command ID is available; "
            "automatic replay is unsafe.",
            {
                "kind": "mutation_outcome_unknown",
                "command_id": None,
                "outcome": "unknown",
                "retry_safe": False,
                "instruction": _MUTATION_UNKNOWN_INSTRUCTION,
            },
        )

    def _command_unknown(self, error: CommandOutcomeUnknownError) -> Any:
        """Return a known-command-ID mutation ambiguity result."""
        command_id = _safe_command_id(error.command_id)
        if command_id is None:
            _LOGGER.error(
                "MCP mutation timeout carried an invalid command identifier; "
                "classifying outcome without an identifier"
            )
            return self._mutation_unknown()
        context = _api_context(error)
        context.update(
            {
                "kind": "command_outcome_unknown",
                "command_id": command_id,
                "outcome": "unknown",
                "retry_safe": False,
                "instruction": _COMMAND_UNKNOWN_INSTRUCTION,
            }
        )
        return self._result(
            "Mutation outcome is unknown for a known command ID. "
            "Use vnc_get_command_status(command_id) before any further mutation; "
            "automatic replay is unsafe.",
            context,
        )

    def _mutation_api_error(self, error: ApiError) -> Any:
        """Return one authoritative structured controller mutation failure."""
        context = _api_context(error)
        if error.command_id is None:
            if error.outcome is not None or error.retry_safe is not None:
                _LOGGER.error(
                    "MCP mutation API error carried incomplete command outcome metadata; "
                    "classifying outcome unknown"
                )
                return self._mutation_unknown()
            return self._result("Controller rejected the mutation request.", context)

        command_id = _safe_command_id(error.command_id)
        if command_id is None or error.outcome != "failed" or error.retry_safe is not False:
            _LOGGER.error(
                "MCP mutation API error violated accepted-command outcome invariants; "
                "classifying outcome unknown"
            )
            return self._mutation_unknown()
        context.update(
            {
                "command_id": command_id,
                "outcome": "failed",
                "retry_safe": False,
                "instruction": _ACCEPTED_FAILURE_INSTRUCTION,
            }
        )
        return self._result(
            "Controller reported that the accepted mutation failed; automatic retry is unsafe.",
            context,
        )

    def _read_error(self, error: Exception, *, tool_name: str) -> Any:
        """Classify one read-only failure without mutation ambiguity semantics."""
        if isinstance(error, TransportError):
            return self._result(
                "Read-only controller call failed at the transport boundary.",
                {"kind": "transport_error"},
            )
        if isinstance(error, ProtocolError):
            return self._result(
                "Read-only controller response violated the typed protocol contract.",
                {"kind": "controller_protocol_error"},
            )
        if isinstance(error, ApiError):
            return self._result("Controller rejected the read-only request.", _api_context(error))
        if isinstance(error, McpCallCapacityError | McpExecutorClosedError):
            return self._result(
                "MCP adapter could not admit the read-only controller call.",
                {"kind": "adapter_internal_error"},
            )
        _LOGGER.error(
            "MCP read-only tool %s raised an unexpected adapter failure",
            tool_name,
        )
        return self._result(
            "MCP adapter failed while handling the read-only controller call.",
            {"kind": "adapter_internal_error"},
        )

    def _mutation_error(self, error: Exception, *, tool_name: str) -> Any:
        """Classify one mutation failure conservatively after local preflight."""
        if isinstance(error, self._mutation_validation_errors):
            return self._result(
                "Mutation input failed adapter preflight before any controller request was sent.",
                {"kind": "validation_error"},
            )
        if isinstance(error, CommandOutcomeUnknownError):
            return self._command_unknown(error)
        if isinstance(error, ApiError):
            return self._mutation_api_error(error)
        if isinstance(error, TransportError | ProtocolError):
            return self._mutation_unknown()
        if isinstance(error, McpCallCapacityError | McpExecutorClosedError):
            return self._result(
                "MCP adapter could not admit the mutation controller call; no request was issued.",
                {"kind": "adapter_internal_error"},
            )
        _LOGGER.error(
            "MCP mutation tool %s raised an unexpected adapter failure; "
            "classifying outcome unknown",
            tool_name,
        )
        return self._mutation_unknown()

    def __call__(self, **registration: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Return a registrar decorator that preserves schema/signature metadata."""
        annotations = registration.get("annotations")
        read_only_hint = getattr(annotations, "read_only_hint", None)
        tool_name = registration.get("name")
        if not isinstance(read_only_hint, bool):
            raise McpOutcomeRegistrationError(
                "MCP tool registration omitted an explicit read_only_hint"
            )
        if not isinstance(tool_name, str) or not tool_name:
            raise McpOutcomeRegistrationError("MCP tool registration omitted an explicit name")
        decorator = self._registrar(**registration)
        if not callable(decorator):
            raise McpOutcomeRegistrationError(
                "MCP SDK tool registrar did not return a decorator"
            )

        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            if not inspect.iscoroutinefunction(function):
                raise McpOutcomeRegistrationError(
                    "MCP outcome classification requires asynchronous tool handlers"
                )

            @wraps(function)
            async def classified(*args: Any, **kwargs: Any) -> Any:
                try:
                    return await function(*args, **kwargs)
                except Exception as error:  # Tool failures become explicit MCP error results.
                    if read_only_hint:
                        return self._read_error(error, tool_name=tool_name)
                    return self._mutation_error(error, tool_name=tool_name)

            return decorator(classified)

        return register
