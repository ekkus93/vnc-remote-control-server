"""Model Context Protocol server entry point for VNC Remote Control Server.

The MCP dependency is optional. Importing this module never imports or starts the
MCP runtime; callers that construct or run the server receive an explicit error
when the ``mcp`` extra is not installed.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from contextlib import (
    AbstractAsyncContextManager,
    ExitStack,
    asynccontextmanager,
)
from dataclasses import dataclass
from importlib import import_module
from typing import Any, TypeAlias, cast

from .client import VncRemoteControlClient
from .mcp_config import (
    McpConfig,
    McpConfigError,
    validate_mcp_transport_configuration,
)
from .mcp_execution import BoundedControllerExecutor
from .mcp_mutation_tools import (
    McpMutationRuntime,
    McpMutationSchemaMetadata,
    McpMutationValidationError,
    build_mutation_schema_metadata,
    register_mutation_tools,
)
from .mcp_outcomes import McpOutcomeToolRegistrar
from .mcp_tools import (
    McpCallExecutor,
    McpReadRuntime,
    register_read_only_tools,
)

MCP_EXTRA_REQUIREMENT = "mcp==2.1.1"
MCP_INSTALL_HINT = 'pip install "vnc-remote-control-client[mcp]"'
MCP_SERVER_MODULE = "mcp.server.mcpserver"
MCP_IMAGE_MODULE = "mcp.server.mcpserver.utilities.types"
MCP_TYPES_MODULE = "mcp_types"
PYDANTIC_MODULE = "pydantic"


class McpDependencyError(RuntimeError):
    """Raised when MCP support is requested without the optional SDK."""


McpServerFactory: TypeAlias = Callable[..., Any]
McpAnnotationsFactory: TypeAlias = Callable[..., Any]
McpFieldFactory: TypeAlias = Callable[..., Any]
McpImageFactory: TypeAlias = Callable[..., Any]
McpCallToolResultFactory: TypeAlias = Callable[..., Any]
McpTextContentFactory: TypeAlias = Callable[..., Any]
McpLifespan: TypeAlias = Callable[[Any], AbstractAsyncContextManager[McpReadRuntime]]


@dataclass(frozen=True, slots=True)
class McpSdkComponents:
    """Exact optional SDK callables needed by the initial MCP adapter."""

    server_factory: McpServerFactory
    annotations_factory: McpAnnotationsFactory
    field_factory: McpFieldFactory
    image_factory: McpImageFactory
    call_tool_result_factory: McpCallToolResultFactory
    text_content_factory: McpTextContentFactory


def load_mcp_sdk_components() -> McpSdkComponents:
    """Load the reviewed optional SDK surface without compatibility fallbacks."""
    try:
        server_module = import_module(MCP_SERVER_MODULE)
        image_module = import_module(MCP_IMAGE_MODULE)
        types_module = import_module(MCP_TYPES_MODULE)
        pydantic_module = import_module(PYDANTIC_MODULE)
    except ImportError as exc:
        raise McpDependencyError(
            f"MCP support requires {MCP_EXTRA_REQUIREMENT}; install it with {MCP_INSTALL_HINT}"
        ) from exc

    server_factory = getattr(server_module, "MCPServer", None)
    image_factory = getattr(image_module, "Image", None)
    annotations_factory = getattr(types_module, "ToolAnnotations", None)
    call_tool_result_factory = getattr(types_module, "CallToolResult", None)
    text_content_factory = getattr(types_module, "TextContent", None)
    field_factory = getattr(pydantic_module, "Field", None)
    required_callables = (
        server_factory,
        image_factory,
        annotations_factory,
        call_tool_result_factory,
        text_content_factory,
        field_factory,
    )
    if not all(callable(item) for item in required_callables) or not callable(
        getattr(image_factory, "to_image_content", None)
    ):
        raise McpDependencyError(
            "installed MCP SDK does not provide the expected "
            "MCPServer/Image/ToolAnnotations/CallToolResult/TextContent/Field API for "
            f"{MCP_EXTRA_REQUIREMENT}"
        )
    return McpSdkComponents(
        server_factory=cast(McpServerFactory, server_factory),
        annotations_factory=cast(McpAnnotationsFactory, annotations_factory),
        field_factory=cast(McpFieldFactory, field_factory),
        image_factory=cast(McpImageFactory, image_factory),
        call_tool_result_factory=cast(McpCallToolResultFactory, call_tool_result_factory),
        text_content_factory=cast(McpTextContentFactory, text_content_factory),
    )


def _runtime_lifespan(runtime: McpReadRuntime) -> McpLifespan:
    """Return an SDK lifespan that always closes the adapter-owned executor."""

    @asynccontextmanager
    async def lifespan(_server: Any) -> AsyncIterator[McpReadRuntime]:
        try:
            yield runtime
        finally:
            await runtime.executor.aclose()

    return lifespan


def _build_schema_metadata(
    field_factory: McpFieldFactory,
    *,
    allow_mutations: bool,
) -> tuple[object, McpMutationSchemaMetadata | None]:
    """Build reviewed Pydantic Field metadata without compatibility fallbacks."""
    try:
        positive_command_id = field_factory(
            ge=1,
            strict=True,
            description="Positive process-local controller command identifier.",
        )
        mutation_schema = (
            build_mutation_schema_metadata(field_factory) if allow_mutations else None
        )
    except TypeError as exc:
        raise McpDependencyError(
            "installed MCP SDK does not provide the expected schema Field API for "
            f"{MCP_EXTRA_REQUIREMENT}"
        ) from exc
    return positive_command_id, mutation_schema


def create_mcp_server(
    *,
    config: McpConfig,
    components: McpSdkComponents | None = None,
    client: VncRemoteControlClient | None = None,
    executor: McpCallExecutor | None = None,
) -> Any:
    """Construct the configured MCP server without starting a transport."""
    sdk = components if components is not None else load_mcp_sdk_components()
    controller_client = client if client is not None else config.build_client()
    controller_executor = (
        executor
        if executor is not None
        else BoundedControllerExecutor(config.max_concurrent_calls)
    )
    runtime = McpReadRuntime(
        client=controller_client,
        executor=controller_executor,
    )

    # Until construction succeeds, this stack owns runtime cleanup. Successful
    # construction transfers ownership to the MCP lifespan without relying on a
    # broad exception handler or garbage collection to close worker threads.
    with ExitStack() as cleanup:
        cleanup.callback(runtime.executor.close)
        server = sdk.server_factory(
            "VNC Remote Control Server",
            lifespan=_runtime_lifespan(runtime),
        )
        tool_registrar = getattr(server, "tool", None)
        if not callable(tool_registrar):
            raise McpDependencyError(
                f"installed MCP SDK does not provide the expected tool registration API for "
                f"{MCP_EXTRA_REQUIREMENT}"
            )
        classified_tool_registrar = McpOutcomeToolRegistrar(
            tool_registrar,
            call_tool_result_factory=sdk.call_tool_result_factory,
            text_content_factory=sdk.text_content_factory,
            mutation_validation_errors=(McpMutationValidationError,),
        )

        positive_command_id_metadata, mutation_schema = _build_schema_metadata(
            sdk.field_factory,
            allow_mutations=config.allow_mutations,
        )
        register_read_only_tools(
            classified_tool_registrar,
            runtime,
            annotations_factory=sdk.annotations_factory,
            positive_command_id_metadata=positive_command_id_metadata,
            image_factory=sdk.image_factory,
            call_tool_result_factory=sdk.call_tool_result_factory,
        )
        if mutation_schema is not None:
            register_mutation_tools(
                classified_tool_registrar,
                McpMutationRuntime(
                    client=controller_client,
                    executor=controller_executor,
                ),
                annotations_factory=sdk.annotations_factory,
                schema=mutation_schema,
            )
        cleanup.pop_all()
    return server


def _run_configured_transport(server: Any, config: McpConfig) -> None:
    """Run exactly the validated MCP transport without compatibility fallback."""
    validate_mcp_transport_configuration(
        config.transport,
        config.http_host,
        config.http_port,
    )
    if config.transport == "stdio":
        # The pinned SDK owns stdio lifecycle and follows the MCP shutdown contract:
        # the host closes stdin/EOF first, then applies its bounded escalation policy.
        # Do not install adapter signal handlers here; mcp==2.1.1 can have a worker
        # blocked on its private stdin duplicate, so signal-only unwinding can hang.
        server.run(transport="stdio")
        return
    if config.transport != "streamable-http":
        raise McpConfigError("invalid VRC_MCP_TRANSPORT")

    # Config accepts only the three exact loopback spellings for which mcp==2.1.1
    # auto-enables its DNS-rebinding middleware. Deliberately omit
    # ``transport_security`` so the official Host/Origin policy is not replaced or
    # disabled here. Stateless mode prevents persistent HTTP session accumulation;
    # controller calls remain independently bounded by the shared executor.
    server.run(
        transport="streamable-http",
        host=config.http_host,
        port=config.http_port,
        stateless_http=True,
    )


def main() -> None:
    """Load validated configuration and run the selected MCP transport."""
    try:
        config = McpConfig.load()
        server = create_mcp_server(config=config)
    except (McpConfigError, McpDependencyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    _run_configured_transport(server, config)


if __name__ == "__main__":
    main()
