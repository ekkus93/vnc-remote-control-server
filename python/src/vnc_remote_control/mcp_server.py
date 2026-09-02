"""Model Context Protocol server entry point for VNC Remote Control Server.

The MCP dependency is optional. Importing this module never imports or starts the
MCP runtime; callers that construct or run the server receive an explicit error
when the ``mcp`` extra is not installed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import import_module
from typing import Any, TypeAlias, cast

from .client import VncRemoteControlClient
from .mcp_config import McpConfig, McpConfigError
from .mcp_execution import BoundedControllerExecutor
from .mcp_tools import McpReadRuntime, register_read_only_tools

MCP_EXTRA_REQUIREMENT = "mcp==2.1.1"
MCP_INSTALL_HINT = 'pip install "vnc-remote-control-client[mcp]"'
MCP_SERVER_MODULE = "mcp.server.mcpserver"
MCP_TYPES_MODULE = "mcp_types"
PYDANTIC_MODULE = "pydantic"


class McpDependencyError(RuntimeError):
    """Raised when MCP support is requested without the optional SDK."""


McpServerFactory: TypeAlias = Callable[..., Any]
McpAnnotationsFactory: TypeAlias = Callable[..., Any]
McpFieldFactory: TypeAlias = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class McpSdkComponents:
    """Exact optional SDK callables needed by the initial MCP adapter."""

    server_factory: McpServerFactory
    annotations_factory: McpAnnotationsFactory
    field_factory: McpFieldFactory


def _load_mcp_sdk_components() -> McpSdkComponents:
    """Load the reviewed optional SDK surface without compatibility fallbacks."""
    try:
        server_module = import_module(MCP_SERVER_MODULE)
        types_module = import_module(MCP_TYPES_MODULE)
        pydantic_module = import_module(PYDANTIC_MODULE)
    except ImportError as exc:
        raise McpDependencyError(
            f"MCP support requires {MCP_EXTRA_REQUIREMENT}; install it with {MCP_INSTALL_HINT}"
        ) from exc

    server_factory = getattr(server_module, "MCPServer", None)
    annotations_factory = getattr(types_module, "ToolAnnotations", None)
    field_factory = getattr(pydantic_module, "Field", None)
    if not all(callable(item) for item in (server_factory, annotations_factory, field_factory)):
        raise McpDependencyError(
            f"installed MCP SDK does not provide the expected MCPServer/ToolAnnotations/Field "
            f"API for {MCP_EXTRA_REQUIREMENT}"
        )
    return McpSdkComponents(
        server_factory=cast(McpServerFactory, server_factory),
        annotations_factory=cast(McpAnnotationsFactory, annotations_factory),
        field_factory=cast(McpFieldFactory, field_factory),
    )


def _runtime_lifespan(runtime: McpReadRuntime) -> Callable[[Any], Any]:
    """Return an SDK lifespan that always closes the adapter-owned executor."""

    @asynccontextmanager
    async def lifespan(_server: Any) -> Any:
        try:
            yield runtime
        finally:
            await runtime.executor.aclose()

    return lifespan


def create_mcp_server(
    *,
    config: McpConfig,
    components: McpSdkComponents | None = None,
    client: VncRemoteControlClient | None = None,
    executor: BoundedControllerExecutor | None = None,
) -> Any:
    """Construct the configured MCP server without starting a transport."""
    if config.allow_mutations:
        raise McpConfigError("mutation tools are not implemented until MCP-006")

    sdk = components or _load_mcp_sdk_components()
    runtime = McpReadRuntime(
        client=client or config.build_client(),
        executor=executor or BoundedControllerExecutor(config.max_concurrent_calls),
    )
    server = sdk.server_factory(
        "VNC Remote Control Server",
        lifespan=_runtime_lifespan(runtime),
    )
    if not callable(getattr(server, "tool", None)):
        runtime.executor.close()
        raise McpDependencyError(
            f"installed MCP SDK does not provide the expected tool registration API for "
            f"{MCP_EXTRA_REQUIREMENT}"
        )

    try:
        positive_command_id_metadata = sdk.field_factory(
            ge=1,
            strict=True,
            description="Positive process-local controller command identifier.",
        )
    except TypeError as exc:
        runtime.executor.close()
        raise McpDependencyError(
            f"installed MCP SDK does not provide the expected schema Field API for "
            f"{MCP_EXTRA_REQUIREMENT}"
        ) from exc

    register_read_only_tools(
        server,
        runtime,
        annotations_factory=sdk.annotations_factory,
        positive_command_id_metadata=positive_command_id_metadata,
    )
    return server


def main() -> None:
    """Load validated configuration and run the initial MCP server over stdio.

    Streamable HTTP configuration is parsed now so invalid/public binds fail
    closed, but the transport itself is intentionally unavailable until MCP-009
    implements and tests the HTTP lifecycle and SDK protections.
    """
    try:
        config = McpConfig.load()
        if config.transport != "stdio":
            raise McpConfigError(
                "streamable-http transport is not implemented until MCP-009"
            )
        server = create_mcp_server(config=config)
    except (McpConfigError, McpDependencyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
