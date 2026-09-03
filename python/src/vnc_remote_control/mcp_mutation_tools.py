"""Mutation MCP tool registration over the typed controller client."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, cast

from .mcp_tools import McpCallExecutor, McpToolRegistrar
from .models import CommandResponse, KeyAction, MouseButton

_MAX_COORDINATE = (1 << 32) - 1
_MIN_DOUBLE_CLICK_INTERVAL_MS = 20
_MAX_DOUBLE_CLICK_INTERVAL_MS = 1000
_MAX_SCROLL_STEPS = 100
_MAX_CHORD_KEYS = 16
_MAX_TEXT_BYTES = 16 * 1024
_MAX_CLIPBOARD_BYTES = 1024 * 1024
_SYMBOLIC_KEYS = frozenset(
    {
        "CTRL_LEFT",
        "ALT_LEFT",
        "SHIFT_LEFT",
        "META_LEFT",
        "ENTER",
        "TAB",
        "ESCAPE",
        "BACKSPACE",
        "DELETE",
        "HOME",
        "END",
        "PAGE_UP",
        "PAGE_DOWN",
        "ARROW_UP",
        "ARROW_DOWN",
        "ARROW_LEFT",
        "ARROW_RIGHT",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "F7",
        "F8",
        "F9",
        "F10",
        "F11",
        "F12",
    }
)
_KEYBOARD_KEY_PATTERN = (
    r"^(?:CTRL_LEFT|ALT_LEFT|SHIFT_LEFT|META_LEFT|ENTER|TAB|ESCAPE|BACKSPACE|DELETE|"
    r"HOME|END|PAGE_UP|PAGE_DOWN|ARROW_UP|ARROW_DOWN|ARROW_LEFT|ARROW_RIGHT|F1|F2|"
    r"F3|F4|F5|F6|F7|F8|F9|F10|F11|F12|[ -~])$"
)
_TEXT_PATTERN = r"^[\t\r\n -~]*$"
_CLIPBOARD_PATTERN = "^[^\\x00]*$"


class McpMutationValidationError(ValueError):
    """Raised when mutation preflight fails before any controller call."""


class McpMutationClient(Protocol):
    """Typed controller methods used by the mutation MCP catalog."""

    def move_pointer(self, x: int, y: int) -> CommandResponse:
        """Move the pointer."""

    def set_pointer_button(
        self,
        x: int,
        y: int,
        button: MouseButton,
        pressed: bool,
    ) -> CommandResponse:
        """Set one pointer button state."""

    def click_pointer(self, x: int, y: int, button: MouseButton) -> CommandResponse:
        """Click one pointer button."""

    def double_click_pointer(
        self,
        x: int,
        y: int,
        button: MouseButton,
        *,
        interval_ms: int,
    ) -> CommandResponse:
        """Double-click one pointer button."""

    def scroll_pointer(
        self,
        x: int,
        y: int,
        delta_y: int,
        *,
        delta_x: int = 0,
    ) -> CommandResponse:
        """Scroll the pointer vertically."""

    def set_keyboard_key(self, key: str, action: KeyAction) -> CommandResponse:
        """Set one keyboard key state."""

    def send_keyboard_chord(self, keys: Sequence[str]) -> CommandResponse:
        """Send one bounded keyboard chord."""

    def type_keyboard_text(self, text: str) -> CommandResponse:
        """Type one bounded text payload."""

    def set_clipboard(self, text: str) -> CommandResponse:
        """Set one bounded clipboard payload."""

    def request_reconnect(self) -> CommandResponse:
        """Request one manual reconnect."""


@dataclass(slots=True)
class McpMutationRuntime:
    """Mutation client view sharing the adapter-owned bounded executor."""

    client: McpMutationClient
    executor: McpCallExecutor


@dataclass(frozen=True, slots=True)
class McpMutationSchemaMetadata:
    """Injected Pydantic Field metadata for exact mutation input schemas."""

    coordinate: object
    boolean: object
    interval_ms: object
    delta_y: object
    keyboard_key: object
    chord: object
    text: object
    clipboard: object


def build_mutation_schema_metadata(field_factory: Any) -> McpMutationSchemaMetadata:
    """Build exact mutation schema metadata without importing Pydantic here."""
    return McpMutationSchemaMetadata(
        coordinate=field_factory(
            ge=0,
            le=_MAX_COORDINATE,
            strict=True,
            description="Unsigned 32-bit desktop coordinate.",
        ),
        boolean=field_factory(
            strict=True,
            description="Strict boolean; string or integer coercion is not accepted.",
        ),
        interval_ms=field_factory(
            ge=_MIN_DOUBLE_CLICK_INTERVAL_MS,
            le=_MAX_DOUBLE_CLICK_INTERVAL_MS,
            strict=True,
            description="Double-click interval in milliseconds.",
        ),
        delta_y=field_factory(
            ge=-_MAX_SCROLL_STEPS,
            le=_MAX_SCROLL_STEPS,
            strict=True,
            description="Bounded vertical wheel steps; horizontal scroll is not exposed.",
        ),
        keyboard_key=field_factory(
            pattern=_KEYBOARD_KEY_PATTERN,
            strict=True,
            description="Controller symbolic key name or one printable ASCII character.",
        ),
        chord=field_factory(
            min_length=1,
            max_length=_MAX_CHORD_KEYS,
            strict=True,
            description="One to sixteen controller-supported keyboard keys.",
        ),
        text=field_factory(
            max_length=_MAX_TEXT_BYTES,
            pattern=_TEXT_PATTERN,
            strict=True,
            description="At most 16 KiB of tab, CR, LF, or printable ASCII text.",
        ),
        clipboard=field_factory(
            max_length=_MAX_CLIPBOARD_BYTES,
            pattern=_CLIPBOARD_PATTERN,
            strict=True,
            description="Valid UTF-8 without NUL; at most 1 MiB encoded bytes.",
        ),
    )


def _validation_error(message: str) -> McpMutationValidationError:
    """Return one payload-free local validation failure."""
    return McpMutationValidationError(message)


def _require_coordinate(value: Any) -> int:
    """Return one strict unsigned-32-bit coordinate or fail before mutation."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise _validation_error("pointer coordinate must be an integer")
    if not 0 <= value <= _MAX_COORDINATE:
        raise _validation_error("pointer coordinate is outside the supported range")
    return value


def _require_button(value: Any) -> MouseButton:
    """Return one exact public mouse-button value."""
    if not isinstance(value, str) or value not in {"left", "middle", "right"}:
        raise _validation_error("pointer button is not supported")
    return cast(MouseButton, value)


def _require_boolean(value: Any) -> bool:
    """Return a strict boolean without truthy coercion."""
    if not isinstance(value, bool):
        raise _validation_error("pointer pressed state must be a boolean")
    return value


def _require_interval_ms(value: Any) -> int:
    """Return one strict bounded double-click interval."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise _validation_error("double-click interval must be an integer")
    if not _MIN_DOUBLE_CLICK_INTERVAL_MS <= value <= _MAX_DOUBLE_CLICK_INTERVAL_MS:
        raise _validation_error("double-click interval is outside the supported range")
    return value


def _require_delta_y(value: Any) -> int:
    """Return one strict bounded vertical scroll delta."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise _validation_error("vertical scroll delta must be an integer")
    if not -_MAX_SCROLL_STEPS <= value <= _MAX_SCROLL_STEPS:
        raise _validation_error("vertical scroll delta is outside the supported range")
    return value


def _require_keyboard_key(value: Any) -> str:
    """Return one supported symbolic key or printable ASCII character."""
    if not isinstance(value, str):
        raise _validation_error("keyboard key must be a string")
    if value in _SYMBOLIC_KEYS:
        return value
    if len(value) == 1 and value.isascii() and " " <= value <= "~":
        return value
    raise _validation_error("keyboard key is not supported")


def _require_key_action(value: Any) -> KeyAction:
    """Return one exact keyboard action without coercion."""
    if not isinstance(value, str) or value not in {"down", "up"}:
        raise _validation_error("keyboard action is not supported")
    return cast(KeyAction, value)


def _require_chord(keys: Any) -> list[str]:
    """Return one fully preflighted one-to-sixteen-key chord."""
    if not isinstance(keys, list):
        raise _validation_error("keyboard chord must be an array")
    if not 1 <= len(keys) <= _MAX_CHORD_KEYS:
        raise _validation_error("keyboard chord length is outside the supported range")
    for key in keys:
        _require_keyboard_key(key)
    return keys


def _require_keyboard_text(text: Any) -> str:
    """Return bounded tab/CR/LF/printable-ASCII text without echoing payloads."""
    if not isinstance(text, str):
        raise _validation_error("keyboard text must be a string")
    if len(text) > _MAX_TEXT_BYTES:
        raise _validation_error("keyboard text exceeds the 16 KiB limit")
    if any(
        character not in {"\t", "\r", "\n"} and not " " <= character <= "~"
        for character in text
    ):
        raise _validation_error("keyboard text contains an unsupported character")
    return text


def _require_clipboard_text(text: Any) -> str:
    """Return valid bounded UTF-8 clipboard text without echoing its contents."""
    if not isinstance(text, str):
        raise _validation_error("clipboard text must be a string")
    if "\x00" in text:
        raise _validation_error("clipboard text contains an embedded NUL")
    if len(text) > _MAX_CLIPBOARD_BYTES:
        raise _validation_error("clipboard text exceeds the 1 MiB UTF-8 limit")
    try:
        encoded_length = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise _validation_error("clipboard text is not valid UTF-8") from exc
    if encoded_length > _MAX_CLIPBOARD_BYTES:
        raise _validation_error("clipboard text exceeds the 1 MiB UTF-8 limit")
    return text


async def _move_pointer(runtime: McpMutationRuntime, x: Any, y: Any) -> CommandResponse:
    """Preflight and issue exactly one pointer-move call."""
    return await runtime.executor.call(
        runtime.client.move_pointer,
        _require_coordinate(x),
        _require_coordinate(y),
    )


async def _set_pointer_button(
    runtime: McpMutationRuntime,
    x: Any,
    y: Any,
    button: Any,
    pressed: Any,
) -> CommandResponse:
    """Preflight and issue exactly one pointer-button call."""
    return await runtime.executor.call(
        runtime.client.set_pointer_button,
        _require_coordinate(x),
        _require_coordinate(y),
        _require_button(button),
        _require_boolean(pressed),
    )


async def _click_pointer(
    runtime: McpMutationRuntime,
    x: Any,
    y: Any,
    button: Any,
) -> CommandResponse:
    """Preflight and issue exactly one pointer-click call."""
    return await runtime.executor.call(
        runtime.client.click_pointer,
        _require_coordinate(x),
        _require_coordinate(y),
        _require_button(button),
    )


async def _double_click_pointer(
    runtime: McpMutationRuntime,
    x: Any,
    y: Any,
    button: Any,
    interval_ms: Any,
) -> CommandResponse:
    """Preflight and issue exactly one pointer-double-click call."""
    return await runtime.executor.call(
        runtime.client.double_click_pointer,
        _require_coordinate(x),
        _require_coordinate(y),
        _require_button(button),
        interval_ms=_require_interval_ms(interval_ms),
    )


async def _scroll_pointer(
    runtime: McpMutationRuntime,
    x: Any,
    y: Any,
    delta_y: Any,
) -> CommandResponse:
    """Preflight and issue one vertical-only pointer-scroll call."""
    return await runtime.executor.call(
        runtime.client.scroll_pointer,
        _require_coordinate(x),
        _require_coordinate(y),
        _require_delta_y(delta_y),
    )


async def _set_keyboard_key(
    runtime: McpMutationRuntime,
    key: Any,
    action: Any,
) -> CommandResponse:
    """Preflight and issue exactly one keyboard-key call."""
    return await runtime.executor.call(
        runtime.client.set_keyboard_key,
        _require_keyboard_key(key),
        _require_key_action(action),
    )


async def _send_keyboard_chord(
    runtime: McpMutationRuntime,
    keys: Any,
) -> CommandResponse:
    """Preflight the complete chord before issuing one controller call."""
    return await runtime.executor.call(
        runtime.client.send_keyboard_chord,
        _require_chord(keys),
    )


async def _type_keyboard_text(
    runtime: McpMutationRuntime,
    text: Any,
) -> CommandResponse:
    """Preflight the complete sensitive text before issuing one controller call."""
    return await runtime.executor.call(
        runtime.client.type_keyboard_text,
        _require_keyboard_text(text),
    )


async def _set_clipboard(
    runtime: McpMutationRuntime,
    text: Any,
) -> CommandResponse:
    """Preflight the complete sensitive clipboard before one controller call."""
    return await runtime.executor.call(
        runtime.client.set_clipboard,
        _require_clipboard_text(text),
    )


async def _request_reconnect(runtime: McpMutationRuntime) -> CommandResponse:
    """Issue exactly one controller-managed reconnect request."""
    return await runtime.executor.call(runtime.client.request_reconnect)


def _register(
    tool: McpToolRegistrar,
    function: Any,
    *,
    name: str,
    description: str,
    annotations: Any,
    parameter_annotations: dict[str, Any],
) -> None:
    """Install exact runtime annotations before SDK tool registration."""
    function.__annotations__.update(parameter_annotations)
    function.__annotations__["return"] = CommandResponse
    tool(
        name=name,
        description=description,
        annotations=annotations,
        structured_output=True,
    )(function)


def _register_pointer_tools(
    tool: McpToolRegistrar,
    runtime: McpMutationRuntime,
    *,
    annotations: Any,
    schema: McpMutationSchemaMetadata,
) -> None:
    """Register the five bounded pointer mutation tools."""

    async def vnc_move_pointer(x: int, y: int) -> CommandResponse:
        """Move the remote pointer without changing button state."""
        return await _move_pointer(runtime, x, y)

    _register(
        tool,
        vnc_move_pointer,
        name="vnc_move_pointer",
        description="Move the remote pointer without changing button state.",
        annotations=annotations,
        parameter_annotations={
            "x": Annotated[int, schema.coordinate],
            "y": Annotated[int, schema.coordinate],
        },
    )

    async def vnc_set_pointer_button(
        x: int,
        y: int,
        button: MouseButton,
        pressed: bool,
    ) -> CommandResponse:
        """Move the pointer and set one mouse button state."""
        return await _set_pointer_button(runtime, x, y, button, pressed)

    _register(
        tool,
        vnc_set_pointer_button,
        name="vnc_set_pointer_button",
        description="Move the pointer and set one mouse button pressed or released.",
        annotations=annotations,
        parameter_annotations={
            "x": Annotated[int, schema.coordinate],
            "y": Annotated[int, schema.coordinate],
            "button": MouseButton,
            "pressed": Annotated[bool, schema.boolean],
        },
    )

    async def vnc_click_pointer(
        x: int,
        y: int,
        button: MouseButton,
    ) -> CommandResponse:
        """Move the pointer and click one mouse button once."""
        return await _click_pointer(runtime, x, y, button)

    _register(
        tool,
        vnc_click_pointer,
        name="vnc_click_pointer",
        description="Move the pointer and click one mouse button once.",
        annotations=annotations,
        parameter_annotations={
            "x": Annotated[int, schema.coordinate],
            "y": Annotated[int, schema.coordinate],
            "button": MouseButton,
        },
    )

    async def vnc_double_click_pointer(
        x: int,
        y: int,
        button: MouseButton,
        interval_ms: int,
    ) -> CommandResponse:
        """Move the pointer and double-click with a bounded interval."""
        return await _double_click_pointer(runtime, x, y, button, interval_ms)

    _register(
        tool,
        vnc_double_click_pointer,
        name="vnc_double_click_pointer",
        description="Move the pointer and double-click with a bounded interval.",
        annotations=annotations,
        parameter_annotations={
            "x": Annotated[int, schema.coordinate],
            "y": Annotated[int, schema.coordinate],
            "button": MouseButton,
            "interval_ms": Annotated[int, schema.interval_ms],
        },
    )

    async def vnc_scroll_pointer(x: int, y: int, delta_y: int) -> CommandResponse:
        """Move the pointer and apply bounded vertical wheel steps."""
        return await _scroll_pointer(runtime, x, y, delta_y)

    _register(
        tool,
        vnc_scroll_pointer,
        name="vnc_scroll_pointer",
        description="Move the pointer and apply bounded vertical wheel steps.",
        annotations=annotations,
        parameter_annotations={
            "x": Annotated[int, schema.coordinate],
            "y": Annotated[int, schema.coordinate],
            "delta_y": Annotated[int, schema.delta_y],
        },
    )


def _register_keyboard_tools(
    tool: McpToolRegistrar,
    runtime: McpMutationRuntime,
    *,
    annotations: Any,
    schema: McpMutationSchemaMetadata,
) -> None:
    """Register the three bounded keyboard mutation tools."""

    async def vnc_set_keyboard_key(key: str, action: KeyAction) -> CommandResponse:
        """Press or release one controller-supported keyboard key."""
        return await _set_keyboard_key(runtime, key, action)

    _register(
        tool,
        vnc_set_keyboard_key,
        name="vnc_set_keyboard_key",
        description="Press or release one controller-supported keyboard key.",
        annotations=annotations,
        parameter_annotations={
            "key": Annotated[str, schema.keyboard_key],
            "action": KeyAction,
        },
    )

    async def vnc_send_keyboard_chord(keys: list[str]) -> CommandResponse:
        """Send one bounded controller-supported keyboard chord."""
        return await _send_keyboard_chord(runtime, keys)

    _register(
        tool,
        vnc_send_keyboard_chord,
        name="vnc_send_keyboard_chord",
        description="Press and release one bounded controller-supported keyboard chord.",
        annotations=annotations,
        parameter_annotations={
            "keys": Annotated[
                list[Annotated[str, schema.keyboard_key]],
                schema.chord,
            ],
        },
    )

    async def vnc_type_keyboard_text(text: str) -> CommandResponse:
        """Type bounded tab/CR/LF/printable-ASCII text on the remote desktop."""
        return await _type_keyboard_text(runtime, text)

    _register(
        tool,
        vnc_type_keyboard_text,
        name="vnc_type_keyboard_text",
        description="Type bounded tab/CR/LF/printable-ASCII text on the remote desktop.",
        annotations=annotations,
        parameter_annotations={"text": Annotated[str, schema.text]},
    )


def _register_clipboard_and_reconnect_tools(
    tool: McpToolRegistrar,
    runtime: McpMutationRuntime,
    *,
    annotations: Any,
    schema: McpMutationSchemaMetadata,
) -> None:
    """Register bounded clipboard and reconnect mutation tools."""

    async def vnc_set_clipboard(text: str) -> CommandResponse:
        """Set bounded valid-UTF-8 clipboard text without logging it."""
        return await _set_clipboard(runtime, text)

    _register(
        tool,
        vnc_set_clipboard,
        name="vnc_set_clipboard",
        description="Set bounded valid-UTF-8 clipboard text without logging the payload.",
        annotations=annotations,
        parameter_annotations={"text": Annotated[str, schema.clipboard]},
    )

    @tool(
        name="vnc_request_reconnect",
        description="Request one controller-managed reconnect to the remote desktop.",
        annotations=annotations,
        structured_output=True,
    )
    async def vnc_request_reconnect() -> CommandResponse:
        """Request one controller-managed reconnect."""
        return await _request_reconnect(runtime)


def register_mutation_tools(
    tool: McpToolRegistrar,
    runtime: McpMutationRuntime,
    *,
    annotations_factory: Any,
    schema: McpMutationSchemaMetadata,
) -> None:
    """Register the explicitly enabled bounded mutation MCP catalog."""
    mutation_annotations = annotations_factory(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    )
    _register_pointer_tools(
        tool,
        runtime,
        annotations=mutation_annotations,
        schema=schema,
    )
    _register_keyboard_tools(
        tool,
        runtime,
        annotations=mutation_annotations,
        schema=schema,
    )
    _register_clipboard_and_reconnect_tools(
        tool,
        runtime,
        annotations=mutation_annotations,
        schema=schema,
    )
