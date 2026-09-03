"""Pinned-SDK regressions for MCP command outcome semantics."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, ParamSpec, TypeVar, cast

from vnc_remote_control.client import VncRemoteControlClient
from vnc_remote_control.errors import (
    ApiError,
    CommandOutcomeUnknownError,
    ProtocolError,
    TransportError,
)
from vnc_remote_control.mcp_config import McpConfig
from vnc_remote_control.mcp_server import create_mcp_server, load_mcp_sdk_components
from vnc_remote_control.models import CommandResponse, CommandStatusResponse, StatusResponse

P = ParamSpec("P")
R = TypeVar("R")


class ImmediateExecutor:
    """Run controller methods synchronously while counting exact call boundaries."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(
        self,
        operation: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Invoke one supplied operation exactly once."""
        self.calls.append(operation.__name__)
        return operation(*args, **kwargs)

    def close(self) -> None:
        """Provide the construction cleanup interface without owned resources."""

    async def aclose(self) -> None:
        """Provide the lifespan cleanup interface without owned resources."""


class OutcomeClient:
    """Minimal fake implementing only methods actually invoked by this suite."""

    def __init__(self) -> None:
        self.mutation_mode = "success"
        self.read_mode = "success"
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def click_pointer(self, x: int, y: int, button: str = "left") -> CommandResponse:
        """Record and return/raise one selected pointer mutation outcome."""
        self.calls.append(("click_pointer", (x, y, button)))
        if self.mutation_mode == "success":
            return CommandResponse(command_id=70, status="succeeded")
        if self.mutation_mode == "known_unknown":
            raise CommandOutcomeUnknownError(
                504,
                "SENSITIVE_TIMEOUT_MESSAGE",
                command_id=77,
                request_id="req-77",
            )
        if self.mutation_mode == "transport":
            raise TransportError("SENSITIVE_TRANSPORT_DETAIL")
        if self.mutation_mode == "protocol":
            raise ProtocolError("SENSITIVE_MALFORMED_RESPONSE")
        if self.mutation_mode == "failed":
            raise ApiError(
                500,
                "SENSITIVE_TERMINAL_FAILURE",
                code="command_failed",
                request_id="req-78",
                command_id=78,
                outcome="failed",
                retry_safe=False,
            )
        raise RuntimeError("SENSITIVE_UNEXPECTED_MUTATION_FAILURE")

    def get_command_status(self, command_id: int) -> CommandStatusResponse:
        """Return one terminal status for explicit recovery inspection."""
        self.calls.append(("get_command_status", (command_id,)))
        return CommandStatusResponse(
            command_id=command_id,
            status="succeeded",
            failure=None,
            retry_safe=False,
        )

    def get_status(self) -> StatusResponse:
        """Expose one read-only method for distinct error-classification tests."""
        self.calls.append(("get_status", ()))
        if self.read_mode == "transport":
            raise TransportError("SENSITIVE_READ_TRANSPORT")
        if self.read_mode == "protocol":
            raise ProtocolError("SENSITIVE_READ_PROTOCOL")
        return StatusResponse("connected", 1, 2, 3, 0, None, 4, 0, 0, False, False)


def _config() -> McpConfig:
    """Return the validated config shape needed for mutation-enabled construction."""
    config = SimpleNamespace()
    config.allow_mutations = True
    config.max_concurrent_calls = 1
    config.transport = "stdio"
    config.build_client = lambda: cast(VncRemoteControlClient, OutcomeClient())
    return cast(McpConfig, config)


def _structured(result: Any) -> dict[str, Any]:
    """Return one real SDK structured-content object after asserting its shape."""
    content = result.structured_content
    if not isinstance(content, dict):
        raise AssertionError("MCP tool result omitted structured content")
    return content


class McpOutcomePinnedSdkTests(unittest.IsolatedAsyncioTestCase):
    """Verify real MCP 2.1.1 wire-result semantics and no hidden replay."""

    async def asyncSetUp(self) -> None:
        """Construct one real pinned-SDK server without starting a transport."""
        self.client = OutcomeClient()
        self.executor = ImmediateExecutor()
        self.server = create_mcp_server(
            config=_config(),
            components=load_mcp_sdk_components(),
            client=cast(VncRemoteControlClient, self.client),
            executor=self.executor,
        )

    async def test_terminal_success_preserves_original_structured_contract(self) -> None:
        """Successful mutation returns only command_id and succeeded status."""
        result = await self.server.call_tool(
            "vnc_click_pointer",
            {"x": 10, "y": 11, "button": "left"},
        )
        self.assertFalse(result.is_error)
        self.assertEqual(
            result.structured_content,
            {"command_id": 70, "status": "succeeded"},
        )
        self.assertEqual(self.executor.calls, ["click_pointer"])
        self.assertEqual(self.client.calls, [("click_pointer", (10, 11, "left"))])

    async def test_known_timeout_returns_error_then_status_is_explicitly_inspectable(self) -> None:
        """Known-ID ambiguity never polls/replays and supports caller-driven status recovery."""
        self.client.mutation_mode = "known_unknown"
        result = await self.server.call_tool(
            "vnc_click_pointer",
            {"x": 12, "y": 13, "button": "left"},
        )
        self.assertTrue(result.is_error)
        context = _structured(result)
        self.assertEqual(context["kind"], "command_outcome_unknown")
        self.assertEqual(context["status_code"], 504)
        self.assertEqual(context["code"], "command_timeout")
        self.assertEqual(context["request_id"], "req-77")
        self.assertEqual(context["command_id"], 77)
        self.assertEqual(context["outcome"], "unknown")
        self.assertIs(context["retry_safe"], False)
        self.assertIn("vnc_get_command_status", context["instruction"])
        self.assertIn("automatic replay is unsafe", context["instruction"])
        self.assertEqual(self.executor.calls, ["click_pointer"])
        self.assertEqual(self.client.calls, [("click_pointer", (12, 13, "left"))])

        status = await self.server.call_tool(
            "vnc_get_command_status",
            {"command_id": 77},
        )
        self.assertFalse(status.is_error)
        self.assertEqual(
            status.structured_content,
            {
                "command_id": 77,
                "status": "succeeded",
                "failure": None,
                "retry_safe": False,
            },
        )
        self.assertEqual(self.executor.calls, ["click_pointer", "get_command_status"])
        self.assertEqual(
            self.client.calls,
            [
                ("click_pointer", (12, 13, "left")),
                ("get_command_status", (77,)),
            ],
        )

    async def test_no_id_transport_and_protocol_failures_are_non_retryable_unknown(self) -> None:
        """No-ID ambiguous failures emit identical conservative mutation semantics."""
        for mode in ("transport", "protocol"):
            self.client.mutation_mode = mode
            self.executor.calls.clear()
            self.client.calls.clear()
            with self.subTest(mode=mode):
                result = await self.server.call_tool(
                    "vnc_click_pointer",
                    {"x": 14, "y": 15, "button": "right"},
                )
                self.assertTrue(result.is_error)
                context = _structured(result)
                self.assertEqual(context["kind"], "mutation_outcome_unknown")
                self.assertIsNone(context["command_id"])
                self.assertEqual(context["outcome"], "unknown")
                self.assertIs(context["retry_safe"], False)
                self.assertIn("automatic replay is unsafe", context["instruction"].lower())
                self.assertEqual(self.executor.calls, ["click_pointer"])
                self.assertEqual(
                    self.client.calls,
                    [("click_pointer", (14, 15, "right"))],
                )

    async def test_terminal_failed_command_is_structured_and_never_replayed(self) -> None:
        """Controller-reported terminal failure preserves command context exactly once."""
        self.client.mutation_mode = "failed"
        result = await self.server.call_tool(
            "vnc_click_pointer",
            {"x": 16, "y": 17, "button": "middle"},
        )
        self.assertTrue(result.is_error)
        self.assertEqual(
            result.structured_content,
            {
                "kind": "controller_api_error",
                "status_code": 500,
                "code": "command_failed",
                "request_id": "req-78",
                "command_id": 78,
                "outcome": "failed",
                "retry_safe": False,
                "instruction": "Do not automatically retry this mutation.",
            },
        )
        self.assertEqual(self.executor.calls, ["click_pointer"])
        self.assertEqual(self.client.calls, [("click_pointer", (16, 17, "middle"))])

    async def test_read_only_transport_and_protocol_failures_remain_distinct(self) -> None:
        """Read-only failures never use mutation unknown-outcome classification."""
        expected = {
            "transport": "transport_error",
            "protocol": "controller_protocol_error",
        }
        for mode, kind in expected.items():
            self.client.read_mode = mode
            self.executor.calls.clear()
            self.client.calls.clear()
            with self.subTest(mode=mode):
                result = await self.server.call_tool("vnc_get_status", {})
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content, {"kind": kind})
                self.assertEqual(self.executor.calls, ["get_status"])
                self.assertEqual(self.client.calls, [("get_status", ())])

    async def test_wrapping_preserves_mutation_output_schema(self) -> None:
        """Outcome classification does not erase the MCP-006 success output schema."""
        tools = {tool.name: tool for tool in await self.server.list_tools()}
        schema = tools["vnc_click_pointer"].output_schema
        self.assertIsInstance(schema, dict)
        if not isinstance(schema, dict):
            raise AssertionError("mutation output schema was not an object")
        self.assertEqual(set(schema["required"]), {"command_id", "status"})
        self.assertEqual(schema["properties"]["command_id"]["type"], "integer")
        self.assertEqual(schema["properties"]["status"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
