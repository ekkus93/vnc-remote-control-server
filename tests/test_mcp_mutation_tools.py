"""Contract tests for the explicitly enabled MCP mutation tool catalog."""

from __future__ import annotations

import inspect
import unittest
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated, Any, ParamSpec, TypeVar, get_args, get_origin

from vnc_remote_control.mcp_mutation_tools import (
    McpMutationRuntime,
    McpMutationSchemaMetadata,
    McpMutationValidationError,
    build_mutation_schema_metadata,
    register_mutation_tools,
)
from vnc_remote_control.models import CommandResponse, KeyAction, MouseButton

P = ParamSpec("P")
R = TypeVar("R")
RegisteredTool = tuple[Callable[..., Any], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class FakeAnnotations:
    """Inspectable stand-in for the SDK ToolAnnotations model."""

    read_only_hint: bool
    destructive_hint: bool
    idempotent_hint: bool
    open_world_hint: bool


def _recording_tool_registrar(
    tools: dict[str, RegisteredTool],
) -> Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]:
    """Return a registrar that captures tool functions and registration metadata."""

    def tool(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            tools[kwargs["name"]] = (function, kwargs)
            return function

        return decorator

    return tool


class RecordingExecutor:
    """Execute immediately while recording the exact synchronous call boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def call(
        self,
        operation: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        self.calls.append((operation.__name__, args, dict(kwargs)))
        return operation(*args, **kwargs)

    def close(self) -> None:
        """Satisfy the shared executor protocol."""

    async def aclose(self) -> None:
        """Satisfy the shared executor protocol."""


class FakeMutationClient:
    """Record exact mutation calls and optionally fail one selected operation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.fail_operation: str | None = None
        self.next_command_id = 100

    def _result(self, name: str, *args: Any, **kwargs: Any) -> CommandResponse:
        self.calls.append((name, args, dict(kwargs)))
        if self.fail_operation == name:
            raise RuntimeError("controller mutation failed")
        result = CommandResponse(command_id=self.next_command_id, status="succeeded")
        self.next_command_id += 1
        return result

    def move_pointer(self, x: int, y: int) -> CommandResponse:
        return self._result("move_pointer", x, y)

    def set_pointer_button(
        self,
        x: int,
        y: int,
        button: MouseButton,
        pressed: bool,
    ) -> CommandResponse:
        return self._result("set_pointer_button", x, y, button, pressed)

    def click_pointer(self, x: int, y: int, button: MouseButton) -> CommandResponse:
        return self._result("click_pointer", x, y, button)

    def double_click_pointer(
        self,
        x: int,
        y: int,
        button: MouseButton,
        *,
        interval_ms: int,
    ) -> CommandResponse:
        return self._result(
            "double_click_pointer",
            x,
            y,
            button,
            interval_ms=interval_ms,
        )

    def scroll_pointer(
        self,
        x: int,
        y: int,
        delta_y: int,
        *,
        delta_x: int = 0,
    ) -> CommandResponse:
        return self._result(
            "scroll_pointer",
            x,
            y,
            delta_y,
            delta_x=delta_x,
        )

    def set_keyboard_key(self, key: str, action: KeyAction) -> CommandResponse:
        return self._result("set_keyboard_key", key, action)

    def send_keyboard_chord(self, keys: Sequence[str]) -> CommandResponse:
        return self._result("send_keyboard_chord", keys)

    def type_keyboard_text(self, text: str) -> CommandResponse:
        return self._result("type_keyboard_text", text)

    def set_clipboard(self, text: str) -> CommandResponse:
        return self._result("set_clipboard", text)

    def request_reconnect(self) -> CommandResponse:
        return self._result("request_reconnect")


def _schema() -> McpMutationSchemaMetadata:
    """Return distinct metadata sentinels for signature assertions."""
    return McpMutationSchemaMetadata(
        coordinate=object(),
        boolean=object(),
        interval_ms=object(),
        delta_y=object(),
        keyboard_key=object(),
        chord=object(),
        text=object(),
        clipboard=object(),
    )


def _annotated_metadata(annotation: Any) -> tuple[Any, ...]:
    """Return an Annotated type's metadata after asserting its shape."""
    if get_origin(annotation) is not Annotated:
        raise AssertionError(f"expected Annotated, got {annotation!r}")
    return get_args(annotation)


class McpMutationSchemaBuilderTests(unittest.TestCase):
    """Verify Field metadata mirrors the public controller/MCP bounds exactly."""

    def test_schema_metadata_requests_exact_bounds_and_patterns(self) -> None:
        calls: list[dict[str, Any]] = []

        def field_factory(**kwargs: Any) -> SimpleNamespace:
            calls.append(dict(kwargs))
            return SimpleNamespace(**kwargs)

        build_mutation_schema_metadata(field_factory)
        self.assertEqual(
            calls,
            [
                {
                    "ge": 0,
                    "le": 4_294_967_295,
                    "strict": True,
                    "description": "Unsigned 32-bit desktop coordinate.",
                },
                {
                    "strict": True,
                    "description": (
                        "Strict boolean; string or integer coercion is not accepted."
                    ),
                },
                {
                    "ge": 20,
                    "le": 1000,
                    "strict": True,
                    "description": "Double-click interval in milliseconds.",
                },
                {
                    "ge": -100,
                    "le": 100,
                    "strict": True,
                    "description": (
                        "Bounded vertical wheel steps; horizontal scroll is not exposed."
                    ),
                },
                {
                    "pattern": (
                        r"^(?:CTRL_LEFT|ALT_LEFT|SHIFT_LEFT|META_LEFT|ENTER|TAB|ESCAPE|"
                        r"BACKSPACE|DELETE|HOME|END|PAGE_UP|PAGE_DOWN|ARROW_UP|ARROW_DOWN|"
                        r"ARROW_LEFT|ARROW_RIGHT|F1|F2|F3|F4|F5|F6|F7|F8|F9|F10|F11|"
                        r"F12|[ -~])$"
                    ),
                    "strict": True,
                    "description": (
                        "Controller symbolic key name or one printable ASCII character."
                    ),
                },
                {
                    "min_length": 1,
                    "max_length": 16,
                    "strict": True,
                    "description": "One to sixteen controller-supported keyboard keys.",
                },
                {
                    "max_length": 16_384,
                    "pattern": r"^[\t\r\n -~]*$",
                    "strict": True,
                    "description": (
                        "At most 16 KiB of tab, CR, LF, or printable ASCII text."
                    ),
                },
                {
                    "max_length": 1_048_576,
                    "pattern": "^[^\\x00]*$",
                    "strict": True,
                    "description": (
                        "Valid UTF-8 without NUL; at most 1 MiB encoded bytes."
                    ),
                },
            ],
        )


class McpMutationToolContractTests(unittest.IsolatedAsyncioTestCase):
    """Verify mutation catalog schemas, annotations, preflight, and one-call mapping."""

    def setUp(self) -> None:
        self.tools: dict[str, RegisteredTool] = {}
        self.executor = RecordingExecutor()
        self.client = FakeMutationClient()
        self.schema = _schema()
        register_mutation_tools(
            _recording_tool_registrar(self.tools),
            McpMutationRuntime(client=self.client, executor=self.executor),
            annotations_factory=FakeAnnotations,
            schema=self.schema,
        )

    def test_catalog_contains_exact_initial_mutation_surface(self) -> None:
        self.assertEqual(
            set(self.tools),
            {
                "vnc_move_pointer",
                "vnc_set_pointer_button",
                "vnc_click_pointer",
                "vnc_double_click_pointer",
                "vnc_scroll_pointer",
                "vnc_set_keyboard_key",
                "vnc_send_keyboard_chord",
                "vnc_type_keyboard_text",
                "vnc_set_clipboard",
                "vnc_request_reconnect",
            },
        )
        self.assertTrue(
            all(registration["structured_output"] for _, registration in self.tools.values())
        )

    def test_all_mutation_annotations_are_conservative(self) -> None:
        for _, registration in self.tools.values():
            annotations = registration["annotations"]
            self.assertFalse(annotations.read_only_hint)
            self.assertTrue(annotations.destructive_hint)
            self.assertFalse(annotations.idempotent_hint)
            self.assertTrue(annotations.open_world_hint)

    def test_parameter_annotations_carry_exact_schema_metadata(self) -> None:
        move = inspect.signature(self.tools["vnc_move_pointer"][0]).parameters
        self.assertIs(_annotated_metadata(move["x"].annotation)[1], self.schema.coordinate)
        self.assertIs(_annotated_metadata(move["y"].annotation)[1], self.schema.coordinate)

        button = inspect.signature(self.tools["vnc_set_pointer_button"][0]).parameters
        self.assertEqual(button["button"].annotation, MouseButton)
        self.assertIs(_annotated_metadata(button["pressed"].annotation)[1], self.schema.boolean)

        double_click = inspect.signature(
            self.tools["vnc_double_click_pointer"][0]
        ).parameters
        self.assertIs(
            _annotated_metadata(double_click["interval_ms"].annotation)[1],
            self.schema.interval_ms,
        )

        scroll = inspect.signature(self.tools["vnc_scroll_pointer"][0]).parameters
        self.assertEqual(set(scroll), {"x", "y", "delta_y"})
        self.assertIs(_annotated_metadata(scroll["delta_y"].annotation)[1], self.schema.delta_y)

        keyboard = inspect.signature(self.tools["vnc_set_keyboard_key"][0]).parameters
        self.assertIs(
            _annotated_metadata(keyboard["key"].annotation)[1],
            self.schema.keyboard_key,
        )
        self.assertEqual(keyboard["action"].annotation, KeyAction)

        chord = inspect.signature(self.tools["vnc_send_keyboard_chord"][0]).parameters
        chord_args = _annotated_metadata(chord["keys"].annotation)
        self.assertIs(chord_args[1], self.schema.chord)
        self.assertIs(get_origin(chord_args[0]), list)
        key_args = _annotated_metadata(get_args(chord_args[0])[0])
        self.assertIs(key_args[1], self.schema.keyboard_key)

        text = inspect.signature(self.tools["vnc_type_keyboard_text"][0]).parameters
        self.assertIs(_annotated_metadata(text["text"].annotation)[1], self.schema.text)
        clipboard = inspect.signature(self.tools["vnc_set_clipboard"][0]).parameters
        self.assertIs(
            _annotated_metadata(clipboard["text"].annotation)[1],
            self.schema.clipboard,
        )
        self.assertEqual(
            tuple(inspect.signature(self.tools["vnc_request_reconnect"][0]).parameters),
            (),
        )

    async def test_every_handler_maps_to_exactly_one_typed_client_call(self) -> None:
        invocations = (
            ("vnc_move_pointer", (10, 11), {}),
            ("vnc_set_pointer_button", (12, 13, "left", True), {}),
            ("vnc_click_pointer", (14, 15, "middle"), {}),
            ("vnc_double_click_pointer", (16, 17, "right", 250), {}),
            ("vnc_scroll_pointer", (18, 19, -4), {}),
            ("vnc_set_keyboard_key", ("CTRL_LEFT", "down"), {}),
            ("vnc_send_keyboard_chord", (["CTRL_LEFT", "A"],), {}),
            ("vnc_type_keyboard_text", ("hello\tworld\r\n",), {}),
            ("vnc_set_clipboard", ("clipboard payload",), {}),
            ("vnc_request_reconnect", (), {}),
        )
        for expected_id, (name, args, kwargs) in enumerate(invocations, start=100):
            result = await self.tools[name][0](*args, **kwargs)
            self.assertEqual(result, CommandResponse(expected_id, "succeeded"))

        expected_calls = [
            ("move_pointer", (10, 11), {}),
            ("set_pointer_button", (12, 13, "left", True), {}),
            ("click_pointer", (14, 15, "middle"), {}),
            ("double_click_pointer", (16, 17, "right"), {"interval_ms": 250}),
            ("scroll_pointer", (18, 19, -4), {}),
            ("set_keyboard_key", ("CTRL_LEFT", "down"), {}),
            ("send_keyboard_chord", (["CTRL_LEFT", "A"],), {}),
            ("type_keyboard_text", ("hello\tworld\r\n",), {}),
            ("set_clipboard", ("clipboard payload",), {}),
            ("request_reconnect", (), {}),
        ]
        self.assertEqual(self.executor.calls, expected_calls)
        expected_client_calls = expected_calls.copy()
        expected_client_calls[4] = (
            "scroll_pointer",
            (18, 19, -4),
            {"delta_x": 0},
        )
        self.assertEqual(self.client.calls, expected_client_calls)

    async def test_invalid_inputs_fail_before_executor_or_controller_call(self) -> None:
        invalid_invocations = (
            ("vnc_move_pointer", (-1, 0)),
            ("vnc_move_pointer", (4_294_967_296, 0)),
            ("vnc_set_pointer_button", (1, 2, "left", 1)),
            ("vnc_click_pointer", (1, 2, "side")),
            ("vnc_double_click_pointer", (1, 2, "left", 19)),
            ("vnc_scroll_pointer", (1, 2, 101)),
            ("vnc_set_keyboard_key", ("CTRL_RIGHT", "down")),
            ("vnc_set_keyboard_key", ("A", "press")),
            ("vnc_send_keyboard_chord", ([],)),
            ("vnc_send_keyboard_chord", (["A"] * 17,)),
            ("vnc_type_keyboard_text", ("invalid\x01text",)),
            ("vnc_type_keyboard_text", ("a" * 16_385,)),
            ("vnc_set_clipboard", ("invalid\x00clipboard",)),
            ("vnc_set_clipboard", ("é" * 524_289,)),
        )
        for name, args in invalid_invocations:
            with (
                self.subTest(tool=name, args_shape=tuple(type(value) for value in args)),
                self.assertRaises(McpMutationValidationError),
            ):
                await self.tools[name][0](*args)
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(self.client.calls, [])

    async def test_sensitive_validation_errors_never_echo_payloads(self) -> None:
        cases = (
            ("vnc_type_keyboard_text", "TYPE_SECRET_SENTINEL\x01"),
            ("vnc_set_clipboard", "CLIPBOARD_SECRET_SENTINEL\x00"),
        )
        for name, payload in cases:
            with self.subTest(tool=name):
                with self.assertRaises(McpMutationValidationError) as captured:
                    await self.tools[name][0](payload)
                self.assertNotIn("SECRET_SENTINEL", str(captured.exception))
        self.assertEqual(self.executor.calls, [])

    async def test_controller_failure_is_never_automatically_retried(self) -> None:
        cases = (
            ("vnc_move_pointer", "move_pointer", (1, 2)),
            (
                "vnc_set_pointer_button",
                "set_pointer_button",
                (1, 2, "left", True),
            ),
            ("vnc_click_pointer", "click_pointer", (1, 2, "left")),
            (
                "vnc_double_click_pointer",
                "double_click_pointer",
                (1, 2, "left", 100),
            ),
            ("vnc_scroll_pointer", "scroll_pointer", (1, 2, 1)),
            ("vnc_set_keyboard_key", "set_keyboard_key", ("A", "down")),
            ("vnc_send_keyboard_chord", "send_keyboard_chord", (["A"],)),
            ("vnc_type_keyboard_text", "type_keyboard_text", ("text",)),
            ("vnc_set_clipboard", "set_clipboard", ("clipboard",)),
            ("vnc_request_reconnect", "request_reconnect", ()),
        )
        for tool_name, operation_name, args in cases:
            before_client = len(self.client.calls)
            before_executor = len(self.executor.calls)
            self.client.fail_operation = operation_name
            with self.assertRaisesRegex(RuntimeError, "controller mutation failed"):
                await self.tools[tool_name][0](*args)
            self.assertEqual(len(self.client.calls), before_client + 1)
            self.assertEqual(len(self.executor.calls), before_executor + 1)
        self.client.fail_operation = None


if __name__ == "__main__":
    unittest.main()
