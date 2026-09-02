"""Read-only MCP tool registration over the typed controller client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from .client import VncRemoteControlClient
from .mcp_execution import BoundedControllerExecutor
from .models import (
    ClipboardResponse,
    CommandStatusResponse,
    DisplayResponse,
    StatusResponse,
)


class McpToolRegistrar(Protocol):
    """Minimal MCP server surface required to register tools."""

    def tool(self, **kwargs: Any) -> Any:
        """Return the SDK tool-registration decorator."""


@dataclass(slots=True)
class McpReadRuntime:
    """One controller client and one shared bounded executor for all MCP calls."""

    client: VncRemoteControlClient
    executor: BoundedControllerExecutor


async def _get_status(runtime: McpReadRuntime) -> StatusResponse:
    """Fetch status through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_status)


async def _get_display(runtime: McpReadRuntime) -> DisplayResponse:
    """Fetch display metadata through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_display)


async def _get_clipboard(runtime: McpReadRuntime) -> ClipboardResponse:
    """Fetch clipboard state through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_clipboard)


async def _get_command_status(
    runtime: McpReadRuntime, command_id: int
) -> CommandStatusResponse:
    """Fetch one command status through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_command_status, command_id)


async def _get_metrics(runtime: McpReadRuntime) -> str:
    """Fetch bounded metrics text through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_metrics)


def register_read_only_tools(
    server: McpToolRegistrar,
    runtime: McpReadRuntime,
    *,
    annotations_factory: Any,
    positive_command_id_metadata: object,
) -> None:
    """Register the initial bounded read-only MCP tool catalog.

    ``annotations_factory`` and the Pydantic ``Field`` metadata are injected by
    :mod:`mcp_server` only after the optional, exact-pinned MCP SDK has loaded.
    This keeps importing the core client free of third-party runtime imports.
    """
    closed_world = annotations_factory(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
    open_world = annotations_factory(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )

    @server.tool(
        name="vnc_get_status",
        description="Return the controller's current connection and lifecycle status.",
        annotations=closed_world,
        structured_output=True,
    )
    async def vnc_get_status() -> StatusResponse:
        """Return controller status without mutating the desktop."""
        return await _get_status(runtime)

    @server.tool(
        name="vnc_get_display",
        description="Return current framebuffer geometry, revision, and completeness.",
        annotations=closed_world,
        structured_output=True,
    )
    async def vnc_get_display() -> DisplayResponse:
        """Return current display metadata without capturing image bytes."""
        return await _get_display(runtime)

    @server.tool(
        name="vnc_get_clipboard",
        description="Return the controller's current clipboard text and revision metadata.",
        annotations=open_world,
        structured_output=True,
    )
    async def vnc_get_clipboard() -> ClipboardResponse:
        """Return clipboard state without logging its text payload."""
        return await _get_clipboard(runtime)

    async def vnc_get_command_status(command_id: int) -> CommandStatusResponse:
        """Return retained lifecycle state for one positive controller command ID."""
        return await _get_command_status(runtime, command_id)

    # The core package deliberately does not depend on Pydantic. The MCP loader
    # supplies exact-pinned SDK Field metadata after optional dependencies load;
    # install it before registration so MCPServer sees minimum=1 in JSON Schema.
    vnc_get_command_status.__annotations__["command_id"] = Annotated[
        int, positive_command_id_metadata
    ]
    server.tool(
        name="vnc_get_command_status",
        description="Return retained lifecycle state for a controller command ID.",
        annotations=closed_world,
        structured_output=True,
    )(vnc_get_command_status)

    @server.tool(
        name="vnc_get_metrics",
        description="Return the controller's bounded Prometheus metrics text.",
        annotations=closed_world,
        structured_output=True,
    )
    async def vnc_get_metrics() -> str:
        """Return bounded controller metrics text without modification."""
        return await _get_metrics(runtime)
