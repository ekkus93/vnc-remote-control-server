"""Contract tests for the MCP read-only tool catalog."""

from __future__ import annotations

import inspect
import unittest
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated, Any, ParamSpec, TypeVar, get_args, get_origin
from unittest import mock

from vnc_remote_control import mcp_tools
from vnc_remote_control.errors import ProtocolError
from vnc_remote_control.mcp_tools import McpReadRuntime, register_read_only_tools
from vnc_remote_control.models import (
    ClipboardResponse,
    CommandStatusResponse,
    DisplayResponse,
    ScreenshotResponse,
    StatusResponse,
)

P = ParamSpec("P")
R = TypeVar("R")
RegisteredTool = tuple[Callable[..., Any], dict[str, Any]]
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build one deterministic PNG chunk with a valid CRC."""
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return len(data).to_bytes(4, "big") + chunk_type + data + crc.to_bytes(4, "big")


def _rgba_png(width: int = 2, height: int = 1) -> bytes:
    """Build a small deterministic RGBA8 PNG accepted by the controller contract."""
    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 6, 0, 0, 0))
    )
    raw = b"".join(b"\x00" + b"\x01\x02\x03\xff" * width for _ in range(height))
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _oversized_dimension_png() -> bytes:
    """Build a tiny PNG envelope whose declared RGBA framebuffer exceeds 64 MiB."""
    width = 4097
    height = 4096
    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 6, 0, 0, 0))
    )
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(b""))
        + _png_chunk(b"IEND", b"")
    )


def _corrupt_idat_png() -> bytes:
    """Build a CRC-valid PNG whose IDAT bytes are not a valid zlib stream."""
    ihdr = (2).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes((8, 6, 0, 0, 0))
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", b"MCP_SCREENSHOT_PAYLOAD_SENTINEL")
        + _png_chunk(b"IEND", b"")
    )


def _fake_image_factory(**kwargs: Any) -> SimpleNamespace:
    """Return an SDK-like image helper without encoding image bytes as text."""

    def to_image_content() -> SimpleNamespace:
        return SimpleNamespace(
            type="image",
            data=kwargs["data"],
            mime_type=f"image/{kwargs['format']}",
        )

    return SimpleNamespace(to_image_content=to_image_content)


def _fake_call_tool_result_factory(**kwargs: Any) -> SimpleNamespace:
    """Return an inspectable SDK-like CallToolResult."""
    return SimpleNamespace(**kwargs)


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

    def get_screenshot(self, *, etag: str | None = None) -> ScreenshotResponse:
        """Return deterministic fresh PNG bytes and sanitized metadata."""
        if etag is not None:
            raise AssertionError("MCP-005 must not send an ETag")
        return ScreenshotResponse(
            data=_rgba_png(),
            etag='"process-0000000000000008"',
            cache_control="private, no-cache, max-age=0",
            request_id="request-8",
            not_modified=False,
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
            image_factory=_fake_image_factory,
            call_tool_result_factory=_fake_call_tool_result_factory,
        )

    def test_catalog_contains_initial_read_and_screenshot_tools(self) -> None:
        """Screenshot is present while mutation tools remain absent during MCP-005."""
        self.assertEqual(
            set(self.tools),
            {
                "vnc_get_status",
                "vnc_get_display",
                "vnc_get_screenshot",
                "vnc_get_clipboard",
                "vnc_get_command_status",
                "vnc_get_metrics",
            },
        )
        for name, (_, registration) in self.tools.items():
            self.assertIs(
                registration["structured_output"],
                name != "vnc_get_screenshot",
            )

    def test_no_argument_tools_have_empty_signatures(self) -> None:
        """Five read tools advertise no input arguments."""
        for name in (
            "vnc_get_status",
            "vnc_get_display",
            "vnc_get_screenshot",
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
        """All tools are read-only/idempotent; screenshot and clipboard are open-world."""
        for name, (_, registration) in self.tools.items():
            annotations = registration["annotations"]
            self.assertTrue(annotations.read_only_hint)
            self.assertFalse(annotations.destructive_hint)
            self.assertTrue(annotations.idempotent_hint)
            self.assertEqual(
                annotations.open_world_hint,
                name in {"vnc_get_screenshot", "vnc_get_clipboard"},
            )

    async def test_screenshot_returns_native_image_and_sanitized_metadata(self) -> None:
        """PNG bytes live only in native image content, never structured JSON metadata."""
        result = await self.tools["vnc_get_screenshot"][0]()
        self.assertEqual(len(result.content), 1)
        image = result.content[0]
        self.assertEqual(image.type, "image")
        self.assertEqual(image.mime_type, "image/png")
        self.assertEqual(image.data, _rgba_png())
        self.assertEqual(
            result.structured_content,
            {
                "etag": '"process-0000000000000008"',
                "request_id": "request-8",
            },
        )
        self.assertNotIn("cache_control", result.structured_content)
        self.assertTrue(all(isinstance(value, str) for value in result.structured_content.values()))

    async def test_screenshot_rejects_missing_or_conditional_data_without_placeholder(self) -> None:
        """Unexpected 304-style output fails before any native image is fabricated."""
        response = ScreenshotResponse(
            data=None,
            etag='"process-0000000000000008"',
            cache_control="private, no-cache, max-age=0",
            request_id="request-8",
            not_modified=True,
        )
        image_factory = mock.Mock(side_effect=AssertionError("image must not be created"))
        tools: dict[str, RegisteredTool] = {}
        register_read_only_tools(
            _recording_tool_registrar(tools),
            McpReadRuntime(client=self.client, executor=self.executor),
            annotations_factory=FakeAnnotations,
            positive_command_id_metadata=self.command_id_metadata,
            image_factory=image_factory,
            call_tool_result_factory=_fake_call_tool_result_factory,
        )
        with (
            mock.patch.object(self.client, "get_screenshot", return_value=response),
            self.assertRaisesRegex(ProtocolError, "contained no PNG data"),
        ):
            await tools["vnc_get_screenshot"][0]()
        image_factory.assert_not_called()

    async def test_screenshot_rejects_non_png_and_invalid_metadata(self) -> None:
        """Malformed image bytes or unsafe metadata remain explicit protocol failures."""
        cases = (
            (
                "non-png",
                ScreenshotResponse(
                    data=b"not a png",
                    etag='"process-0000000000000008"',
                    cache_control=None,
                    request_id="request-8",
                    not_modified=False,
                ),
            ),
            (
                "unsafe-etag",
                ScreenshotResponse(
                    data=_rgba_png(),
                    etag='"process-0000000000000008\nleak"',
                    cache_control=None,
                    request_id="request-8",
                    not_modified=False,
                ),
            ),
        )
        for label, response in cases:
            with (
                self.subTest(label=label),
                mock.patch.object(self.client, "get_screenshot", return_value=response),
                self.assertRaises(ProtocolError),
            ):
                await self.tools["vnc_get_screenshot"][0]()

    async def test_screenshot_rejects_crc_valid_corrupt_deflate_without_echoing_payload(
        self,
    ) -> None:
        """CRC-valid corrupt IDAT data still fails with a payload-free protocol error."""
        response = ScreenshotResponse(
            data=_corrupt_idat_png(),
            etag='"process-0000000000000008"',
            cache_control=None,
            request_id="request-8",
            not_modified=False,
        )
        with (
            mock.patch.object(self.client, "get_screenshot", return_value=response),
            self.assertRaises(ProtocolError) as captured,
        ):
            await self.tools["vnc_get_screenshot"][0]()
        message = str(captured.exception)
        self.assertEqual(message, "screenshot response was not a valid controller PNG")
        self.assertNotIn("MCP_SCREENSHOT_PAYLOAD_SENTINEL", message)

    async def test_screenshot_rejects_framebuffer_dimensions_beyond_controller_limit(self) -> None:
        """Declared RGBA dimensions cannot exceed the controller's 64 MiB bound."""
        response = ScreenshotResponse(
            data=_oversized_dimension_png(),
            etag='"process-0000000000000008"',
            cache_control=None,
            request_id="request-8",
            not_modified=False,
        )
        with (
            mock.patch.object(self.client, "get_screenshot", return_value=response),
            self.assertRaisesRegex(ProtocolError, "framebuffer limit"),
        ):
            await self.tools["vnc_get_screenshot"][0]()

    async def test_screenshot_rejects_encoded_body_before_image_expansion(self) -> None:
        """The encoded PNG ceiling is enforced before the SDK can base64-expand bytes."""
        png = _rgba_png()
        response = ScreenshotResponse(
            data=png,
            etag='"process-0000000000000008"',
            cache_control=None,
            request_id="request-8",
            not_modified=False,
        )
        with (
            mock.patch.object(self.client, "get_screenshot", return_value=response),
            mock.patch.object(mcp_tools, "_MAX_MCP_SCREENSHOT_PNG_BYTES", len(png) - 1),
            self.assertRaisesRegex(ProtocolError, "PNG byte limit"),
        ):
            await self.tools["vnc_get_screenshot"][0]()

    async def test_handlers_map_once_to_exact_typed_client_methods(self) -> None:
        """Every handler invokes exactly one intended typed-client method."""
        status = await self.tools["vnc_get_status"][0]()
        display = await self.tools["vnc_get_display"][0]()
        await self.tools["vnc_get_screenshot"][0]()
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
                ("get_screenshot", (), {}),
                ("get_clipboard", (), {}),
                ("get_command_status", (17,), {}),
                ("get_metrics", (), {}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
