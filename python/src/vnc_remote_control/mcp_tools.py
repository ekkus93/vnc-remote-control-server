"""Read-only MCP tool registration over the typed controller client."""

from __future__ import annotations

import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, ParamSpec, Protocol, TypeVar

from .errors import ProtocolError
from .models import (
    ClipboardResponse,
    CommandStatusResponse,
    DisplayResponse,
    ScreenshotResponse,
    StatusResponse,
)

P = ParamSpec("P")
R = TypeVar("R")
McpToolDecorator = Callable[[Callable[..., Any]], Callable[..., Any]]
McpToolRegistrar = Callable[..., McpToolDecorator]
McpImageFactory = Callable[..., Any]
McpCallToolResultFactory = Callable[..., Any]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IHDR = b"IHDR"
_PNG_IDAT = b"IDAT"
_PNG_IEND = b"IEND"
_PNG_RGBA8_IHDR_TAIL = bytes((8, 6, 0, 0, 0))
_CONTROLLER_MAX_FRAMEBUFFER_BYTES = 64 * 1024 * 1024
# The controller caps the decoded RGBA framebuffer at 64 MiB. PNG scanline
# filtering and DEFLATE/chunk framing can make an incompressible encoded image
# larger than the framebuffer, so allow a conservative 2x wire envelope while
# still refusing an unbounded response before the SDK performs base64 expansion.
_MAX_MCP_SCREENSHOT_PNG_BYTES = 2 * _CONTROLLER_MAX_FRAMEBUFFER_BYTES
_MAX_PROCESS_INSTANCE_BYTES = 64
_MAX_REQUEST_ID_BYTES = 64
_EXPECTED_CACHE_CONTROL = "private, no-cache, max-age=0"


class McpReadClient(Protocol):
    """Typed controller methods used by the read-only MCP catalog."""

    def get_status(self) -> StatusResponse:
        """Return controller status."""

    def get_display(self) -> DisplayResponse:
        """Return display metadata."""

    def get_screenshot(self, *, etag: str | None = None) -> ScreenshotResponse:
        """Return the current PNG screenshot."""

    def get_clipboard(self) -> ClipboardResponse:
        """Return clipboard state."""

    def get_command_status(self, command_id: int) -> CommandStatusResponse:
        """Return retained command state."""

    def get_metrics(self) -> str:
        """Return bounded Prometheus metrics text."""


class McpCallExecutor(Protocol):
    """Bounded asynchronous execution surface required by MCP tools."""

    async def call(
        self,
        operation: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Execute one synchronous controller call off the event loop."""

    def close(self) -> None:
        """Close synchronously and wait for admitted work."""

    async def aclose(self) -> None:
        """Close without blocking the event loop."""


@dataclass(slots=True)
class McpReadRuntime:
    """One controller client and one shared bounded executor for all MCP calls."""

    client: McpReadClient
    executor: McpCallExecutor


async def _get_status(runtime: McpReadRuntime) -> StatusResponse:
    """Fetch status through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_status)


async def _get_display(runtime: McpReadRuntime) -> DisplayResponse:
    """Fetch display metadata through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_display)


async def _get_screenshot(runtime: McpReadRuntime) -> ScreenshotResponse:
    """Fetch one unconditional screenshot through the shared bounded executor."""
    return await runtime.executor.call(runtime.client.get_screenshot)


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


def _validate_png(data: bytes) -> None:
    """Validate the bounded PNG structure emitted by the controller encoder."""
    if len(data) > _MAX_MCP_SCREENSHOT_PNG_BYTES:
        raise ProtocolError("screenshot response exceeded the MCP PNG byte limit")
    if len(data) < 33 or not data.startswith(_PNG_SIGNATURE):
        raise ProtocolError("screenshot response was not a valid controller PNG")

    offset = len(_PNG_SIGNATURE)
    first_chunk = True
    saw_idat = False
    saw_iend = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ProtocolError("screenshot response was not a valid controller PNG")
        chunk_length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + chunk_length
        chunk_end = data_end + 4
        if chunk_end > len(data):
            raise ProtocolError("screenshot response was not a valid controller PNG")

        chunk_data = data[data_start:data_end]
        expected_crc = int.from_bytes(data[data_end:chunk_end], "big")
        observed_crc = zlib.crc32(chunk_type)
        observed_crc = zlib.crc32(chunk_data, observed_crc) & 0xFFFFFFFF
        if observed_crc != expected_crc:
            raise ProtocolError("screenshot response was not a valid controller PNG")

        if first_chunk:
            if chunk_type != _PNG_IHDR or chunk_length != 13:
                raise ProtocolError("screenshot response was not a valid controller PNG")
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            if width == 0 or height == 0 or chunk_data[8:13] != _PNG_RGBA8_IHDR_TAIL:
                raise ProtocolError("screenshot response was not a valid controller PNG")
            if width * height * 4 > _CONTROLLER_MAX_FRAMEBUFFER_BYTES:
                raise ProtocolError("screenshot PNG exceeded the controller framebuffer limit")
            first_chunk = False
        elif chunk_type == _PNG_IHDR:
            raise ProtocolError("screenshot response was not a valid controller PNG")

        if chunk_type == _PNG_IDAT:
            saw_idat = True
        if chunk_type == _PNG_IEND:
            if chunk_length != 0 or not saw_idat or chunk_end != len(data):
                raise ProtocolError("screenshot response was not a valid controller PNG")
            saw_iend = True
        elif saw_iend:
            raise ProtocolError("screenshot response was not a valid controller PNG")
        offset = chunk_end

    if first_chunk or not saw_idat or not saw_iend:
        raise ProtocolError("screenshot response was not a valid controller PNG")


def _is_safe_identifier(value: str, maximum: int) -> bool:
    """Return whether value matches the controller's bounded identifier alphabet."""
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return (
        0 < len(encoded) <= maximum
        and all(
            byte in b"._-"
            or ord("0") <= byte <= ord("9")
            or ord("A") <= byte <= ord("Z")
            or ord("a") <= byte <= ord("z")
            for byte in encoded
        )
    )


def _sanitize_etag(value: str | None) -> str | None:
    """Validate the controller's strong process-instance/revision ETag shape."""
    if value is None:
        return None
    if len(value) < 20 or not value.startswith('"') or not value.endswith('"'):
        raise ProtocolError("screenshot ETag metadata was invalid")
    instance_and_revision = value[1:-1]
    instance, separator, revision = instance_and_revision.rpartition("-")
    if (
        separator != "-"
        or not _is_safe_identifier(instance, _MAX_PROCESS_INSTANCE_BYTES)
        or len(revision) != 16
        or any(character not in "0123456789abcdef" for character in revision)
    ):
        raise ProtocolError("screenshot ETag metadata was invalid")
    return value


def _sanitize_request_id(value: str | None) -> str | None:
    """Validate request IDs against the controller's public identifier contract."""
    if value is None:
        return None
    if not _is_safe_identifier(value, _MAX_REQUEST_ID_BYTES):
        raise ProtocolError("screenshot request ID metadata was invalid")
    return value


def _screenshot_metadata(response: ScreenshotResponse) -> dict[str, str]:
    """Return only bounded metadata safe to expose beside native image content."""
    if response.cache_control not in (None, _EXPECTED_CACHE_CONTROL):
        raise ProtocolError("screenshot cache-control metadata was invalid")
    metadata: dict[str, str] = {}
    etag = _sanitize_etag(response.etag)
    request_id = _sanitize_request_id(response.request_id)
    if etag is not None:
        metadata["etag"] = etag
    if request_id is not None:
        metadata["request_id"] = request_id
    return metadata


def _native_screenshot_result(
    response: ScreenshotResponse,
    *,
    image_factory: McpImageFactory,
    call_tool_result_factory: McpCallToolResultFactory,
) -> Any:
    """Convert one fresh controller PNG to native MCP image content."""
    if response.not_modified or response.data is None:
        raise ProtocolError("unconditional screenshot response contained no PNG data")
    _validate_png(response.data)
    metadata = _screenshot_metadata(response)
    image = image_factory(data=response.data, format="png")
    to_image_content = getattr(image, "to_image_content", None)
    if not callable(to_image_content):
        raise ProtocolError("MCP image helper did not provide native image content")
    return call_tool_result_factory(
        content=[to_image_content()],
        structured_content=metadata,
    )


def register_read_only_tools(
    tool: McpToolRegistrar,
    runtime: McpReadRuntime,
    *,
    annotations_factory: Any,
    positive_command_id_metadata: object,
    image_factory: McpImageFactory,
    call_tool_result_factory: McpCallToolResultFactory,
) -> None:
    """Register the initial bounded read-only MCP tool catalog.

    SDK/Pydantic factories are injected by :mod:`mcp_server` only after the
    optional, exact-pinned MCP SDK has loaded. This keeps importing the core
    client free of third-party runtime imports.
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

    @tool(
        name="vnc_get_status",
        description="Return the controller's current connection and lifecycle status.",
        annotations=closed_world,
        structured_output=True,
    )
    async def vnc_get_status() -> StatusResponse:
        """Return controller status without mutating the desktop."""
        return await _get_status(runtime)

    @tool(
        name="vnc_get_display",
        description="Return current framebuffer geometry, revision, and completeness.",
        annotations=closed_world,
        structured_output=True,
    )
    async def vnc_get_display() -> DisplayResponse:
        """Return current display metadata without capturing image bytes."""
        return await _get_display(runtime)

    @tool(
        name="vnc_get_screenshot",
        description="Return the current desktop screenshot as native PNG image content.",
        annotations=open_world,
        structured_output=False,
    )
    async def vnc_get_screenshot() -> Any:
        """Return one fresh screenshot without ETag optimization or mutation."""
        response = await _get_screenshot(runtime)
        return _native_screenshot_result(
            response,
            image_factory=image_factory,
            call_tool_result_factory=call_tool_result_factory,
        )

    @tool(
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
    tool(
        name="vnc_get_command_status",
        description="Return retained lifecycle state for a controller command ID.",
        annotations=closed_world,
        structured_output=True,
    )(vnc_get_command_status)

    @tool(
        name="vnc_get_metrics",
        description="Return the controller's bounded Prometheus metrics text.",
        annotations=closed_world,
        structured_output=True,
    )
    async def vnc_get_metrics() -> str:
        """Return bounded controller metrics text without modification."""
        return await _get_metrics(runtime)
