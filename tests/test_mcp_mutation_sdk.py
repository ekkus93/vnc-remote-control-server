"""Pinned-SDK contract tests for MCP mutation input schemas."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast

from mcp_test_support import MUTATION_TOOL_NAMES
from vnc_remote_control.client import VncRemoteControlClient
from vnc_remote_control.mcp_config import McpConfig
from vnc_remote_control.mcp_server import create_mcp_server, load_mcp_sdk_components


class NoopExecutor:
    """Executor stand-in used only for schema construction and listing."""

    async def call(self, *_args: Any, **_kwargs: Any) -> Any:
        """Reject unexpected tool execution during a schema-only test."""
        raise AssertionError("schema test must not execute controller calls")

    def close(self) -> None:
        """Provide the construction cleanup interface without owned resources."""

    async def aclose(self) -> None:
        """Provide the lifespan cleanup interface without owned resources."""


def _mutation_config() -> McpConfig:
    """Return the minimum validated config shape required for construction."""
    return cast(
        McpConfig,
        SimpleNamespace(
            allow_mutations=True,
            max_concurrent_calls=1,
            transport="stdio",
            build_client=lambda: VncRemoteControlClient(token="schema-test-token"),
        ),
    )


def _property(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """Return one property schema after asserting it is an object."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise AssertionError("tool schema omitted properties")
    value = properties.get(name)
    if not isinstance(value, dict):
        raise AssertionError(f"tool schema omitted property {name}")
    return value


class McpMutationPinnedSdkTests(unittest.IsolatedAsyncioTestCase):
    """Verify MCP 2.1.1 publishes the intended mutation schemas and annotations."""

    async def asyncSetUp(self) -> None:
        """Construct a real pinned-SDK server without starting a transport."""
        self.executor = NoopExecutor()
        self.server = create_mcp_server(
            config=_mutation_config(),
            components=load_mcp_sdk_components(),
            client=VncRemoteControlClient(token="schema-test-token"),
            executor=self.executor,
        )
        self.tools = {tool.name: tool for tool in await self.server.list_tools()}

    async def test_pointer_schemas_are_strictly_bounded_and_vertical_only(self) -> None:
        """Pointer schemas expose exact bounds and never advertise horizontal scroll."""
        move = self.tools["vnc_move_pointer"].input_schema
        self.assertEqual(set(move["required"]), {"x", "y"})
        for name in ("x", "y"):
            coordinate = _property(move, name)
            self.assertEqual(coordinate["type"], "integer")
            self.assertEqual(coordinate["minimum"], 0)
            self.assertEqual(coordinate["maximum"], 4_294_967_295)

        button = self.tools["vnc_set_pointer_button"].input_schema
        self.assertEqual(
            _property(button, "button")["enum"],
            ["left", "middle", "right"],
        )
        self.assertEqual(_property(button, "pressed")["type"], "boolean")

        double_click = self.tools["vnc_double_click_pointer"].input_schema
        interval = _property(double_click, "interval_ms")
        self.assertEqual(interval["minimum"], 20)
        self.assertEqual(interval["maximum"], 1000)

        scroll = self.tools["vnc_scroll_pointer"].input_schema
        self.assertEqual(set(scroll["properties"]), {"x", "y", "delta_y"})
        delta_y = _property(scroll, "delta_y")
        self.assertEqual(delta_y["minimum"], -100)
        self.assertEqual(delta_y["maximum"], 100)
        self.assertNotIn("delta_x", scroll["properties"])

    async def test_keyboard_text_and_clipboard_schemas_match_public_contract(self) -> None:
        """Keyboard and sensitive-text schemas publish the reviewed finite bounds."""
        key = self.tools["vnc_set_keyboard_key"].input_schema
        self.assertEqual(_property(key, "action")["enum"], ["down", "up"])
        key_pattern = _property(key, "key")["pattern"]
        self.assertIn("CTRL_LEFT", key_pattern)
        self.assertIn("F12", key_pattern)
        self.assertIn("[ -~]", key_pattern)

        chord = self.tools["vnc_send_keyboard_chord"].input_schema
        keys = _property(chord, "keys")
        self.assertEqual(keys["minItems"], 1)
        self.assertEqual(keys["maxItems"], 16)
        self.assertEqual(keys["items"]["pattern"], key_pattern)

        text = _property(self.tools["vnc_type_keyboard_text"].input_schema, "text")
        self.assertEqual(text["maxLength"], 16_384)
        self.assertEqual(text["pattern"], r"^[\t\r\n -~]*$")

        clipboard = _property(self.tools["vnc_set_clipboard"].input_schema, "text")
        self.assertEqual(clipboard["maxLength"], 1_048_576)
        self.assertEqual(clipboard["pattern"], "^[^\\x00]*$")

    async def test_mutation_annotations_are_conservative_in_real_sdk_catalog(self) -> None:
        """All wire-visible mutation hints match the MCP-006 safety contract."""
        self.assertTrue(MUTATION_TOOL_NAMES.issubset(self.tools))
        for name in MUTATION_TOOL_NAMES:
            annotations = self.tools[name].annotations
            self.assertIsNotNone(annotations)
            self.assertFalse(annotations.read_only_hint)
            self.assertTrue(annotations.destructive_hint)
            self.assertFalse(annotations.idempotent_hint)
            self.assertTrue(annotations.open_world_hint)


if __name__ == "__main__":
    unittest.main()
