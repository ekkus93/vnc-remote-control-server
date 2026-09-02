"""Contract tests for the MCP read-only tool catalog."""

from __future__ import annotations

import inspect
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, ParamSpec, TypeVar, get_args, get_origin

from vnc_remote_control.mcp_tools import McpReadRuntime, register_read_only_tools
from vnc_remote_control.models import (
    ClipboardResponse,
    CommandStatusResponse,
    DisplayResponse,
    StatusResponse,
)

P = ParamSpec("P")
R = TypeVar("R")
RegisteredTool = tuple[Callable[..., Any], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class FakeAnnotations:
    """Inspectable stand-in for the optional SDK ToolAnnotations model."""

    read_only_hint: bool
    destructive_hint: bool
    idempotent_hint: bool
    open_world_hint: bool


def _recording_tool_registrar(
    tools: dict[str, RegisteredTool],
) -> Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]:
    """Return a dependency-free registrar that captures MCP tool metadata."""

    def tool(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            tools[kwargs["name"]] = (function, kwargs)
            return function

        return decorator

    return tool


class RecordingExecutor:
    """Execute immediately while recording the exact client call boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    async def call(
        self,
        operation: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Record and invoke one synchronous operation exactly once."""
        self.calls.append((operation.__name__, args, dict(kwargs)))
        return operation(*args, **kwargs)

    def close(self) -> None:
        """Record synchronous closure."""
        self.closed = True

    async def aclose(self) -> None:
        """Record asynchronous closure."""
        self.closed = True


class FakeClient:
    """Return deterministic typed controller responses."""

    def get_status(self) -> StatusResponse:
        """Return deterministic status."""
        return StatusResponse(
            state="connected",
            reconnect_attempts=4,
            started_at_unix_ms=1,
            last_failure=None,
            connected_at_unix_ms=2,
            framebuffer_revision=5,
            last_message_at_unix_ms=3,
            rejected_commands=6,
            fatal_exit=False,
            dropped_events=7,
            shutting_down=False,
        )

    def get_display(self) -> DisplayResponse:
        """Return deterministic display metadata."""
        return DisplayResponse(
            status="current",
            width=1920,
            height=1080,
            depth=24,
            revision=8,
            updated_at_unix_ms=9,
            complete=True,
        )

    def get_clipboard(self) -> ClipboardResponse:
        """Return deterministic clipboard state."""
        return ClipboardResponse(
            text="sensitive clipboard",
            revision=10,
            updated_at_unix_ms=11,
        )

    def get_command_status(self, command_id: int) -> CommandStatusResponse:
        """Return deterministic retained command state."""
        return CommandStatusResponse(
            command_id=command_id,
            status="failed",
            failure="native",
            retry_safe=False,
        )

    def get_metrics(self) -> str:
        """Return deterministic bounded metrics text."""
        return "vrc_commands_total 12\n"


class McpReadToolContractTests(unittest.IsolatedAsyncioTestCase):
    """Verify names, schemas, annotations, and exact client-call mappings."""

    def setUp(self) -> None:
        """Register one dependency-free fake MCP catalog."""
        self.tools: dict[str, RegisteredTool] = {}
        self.executor = RecordingExecutor()
        self.client = FakeClient()
        self.command_id_metadata = object()
        runtime = McpReadRuntime(client=self.client, executor=self.executor)
        register_read_only_tools(
            _recording_tool_registrar(self.tools),
            runtime,
            annotations_factory=FakeAnnotations,
            positive_command_id_metadata=self.command_id_metadata,
        )

    def test_catalog_contains_only_initial_read_tools(self) -> None:
        """Screenshot and mutation tools remain absent during MCP-004."""
        self.assertEqual(
            set(self.tools),
            {
                "vnc_get_status",
                "vnc_get_display",
                "vnc_get_clipboard",
                "vnc_get_command_status",
                "vnc_get_metrics",
            },
        )
        for _, registration in self.tools.values():
            self.assertIs(registration["structured_output"], True)

    def test_no_argument_tools_have_empty_signatures(self) -> None:
        """Four read tools advertise no input arguments."""
        for name in (
            "vnc_get_status",
            "vnc_get_display",
            "vnc_get_clipboard",
            "vnc_get_metrics",
        ):
            function, _ = self.tools[name]
            self.assertEqual(tuple(inspect.signature(function).parameters), ())

    def test_command_status_schema_carries_positive_integer_metadata(self) -> None:
        """The command ID annotation carries injected minimum-one SDK metadata."""
        function, _ = self.tools["vnc_get_command_status"]
        parameter = inspect.signature(function).parameters["command_id"]
        annotation = parameter.annotation
        self.assertIs(get_origin(annotation), Annotated)
        annotation_args = get_args(annotation)
        self.assertIs(annotation_args[0], int)
        self.assertIs(annotation_args[1], self.command_id_metadata)

    def test_annotations_match_closed_and_open_world_contract(self) -> None:
        """All tools are read-only/idempotent; only clipboard is open-world."""
        for name, (_, registration) in self.tools.items():
            annotations = registration["annotations"]
            self.assertTrue(annotations.read_only_hint)
            self.assertFalse(annotations.destructive_hint)
            self.assertTrue(annotations.idempotent_hint)
            self.assertEqual(
                annotations.open_world_hint,
                name == "vnc_get_clipboard",
            )

    async def test_handlers_map_once_to_exact_typed_client_methods(self) -> None:
        """Every handler invokes exactly one intended typed-client method."""
        status = await self.tools["vnc_get_status"][0]()
        display = await self.tools["vnc_get_display"][0]()
        clipboard = await self.tools["vnc_get_clipboard"][0]()
        command = await self.tools["vnc_get_command_status"][0](17)
        metrics = await self.tools["vnc_get_metrics"][0]()

        self.assertEqual(status, self.client.get_status())
        self.assertEqual(display, self.client.get_display())
        self.assertEqual(clipboard, self.client.get_clipboard())
        self.assertEqual(command, self.client.get_command_status(17))
        self.assertEqual(metrics, self.client.get_metrics())
        self.assertEqual(
            self.executor.calls,
            [
                ("get_status", (), {}),
                ("get_display", (), {}),
                ("get_clipboard", (), {}),
                ("get_command_status", (17,), {}),
                ("get_metrics", (), {}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
