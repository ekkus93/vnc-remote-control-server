"""Model Context Protocol server entry point for VNC Remote Control Server.

The MCP dependency is optional. Importing this module never imports or starts the
MCP runtime; callers that construct or run the server receive an explicit error
when the ``mcp`` extra is not installed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import import_module
from typing import Any, TypeAlias, cast

MCP_EXTRA_REQUIREMENT = "mcp==2.1.1"
MCP_INSTALL_HINT = 'pip install "vnc-remote-control-client[mcp]"'


class McpDependencyError(RuntimeError):
    """Raised when MCP support is requested without the optional SDK."""


McpServerFactory: TypeAlias = Callable[[str], Any]


def _load_mcp_server_factory() -> McpServerFactory:
    """Load the optional official MCP SDK only when MCP is actually requested."""
    try:
        module = import_module("mcp.server")
    except ImportError as exc:
        raise McpDependencyError(
            f"MCP support requires {MCP_EXTRA_REQUIREMENT}; install it with {MCP_INSTALL_HINT}"
        ) from exc

    factory = getattr(module, "MCPServer", None)
    if not callable(factory):
        raise McpDependencyError(
            f"installed MCP SDK does not provide the expected MCPServer API for "
            f"{MCP_EXTRA_REQUIREMENT}"
        )
    return cast(McpServerFactory, factory)


def create_mcp_server(*, factory: McpServerFactory | None = None) -> Any:
    """Construct the MCP server without starting transport or network activity."""
    server_factory = factory or _load_mcp_server_factory()
    return server_factory("VNC Remote Control Server")


def main() -> None:
    """Run the initial MCP server over stdio.

    Transport/configuration selection is added by the next MCP implementation
    tranche. Until then stdio is the only entry-point transport, which avoids
    creating a network listener implicitly.
    """
    try:
        server = create_mcp_server()
    except McpDependencyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
