"""Shared dependency-free helpers for MCP catalog contract tests."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

RegisteredTool = tuple[Callable[..., Any], dict[str, Any]]

MUTATION_TOOL_NAMES = frozenset(
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
    }
)


def fake_annotations_factory(**kwargs: Any) -> SimpleNamespace:
    """Return inspectable SDK-like annotation data."""
    return SimpleNamespace(**kwargs)


class RecordingToolRegistrar:
    """Capture SDK-style tool registrations into one supplied catalog."""

    def __init__(self, tools: dict[str, RegisteredTool]) -> None:
        self._tools = tools

    def __call__(
        self, **kwargs: Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Return one decorator that records its registration metadata."""

        def record(function: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[kwargs["name"]] = (function, kwargs)
            return function

        return record
