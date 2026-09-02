"""Shared dependency-free helpers for MCP catalog contract tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class FakeAnnotations:
    """Inspectable stand-in for the optional SDK ToolAnnotations model."""

    read_only_hint: bool
    destructive_hint: bool
    idempotent_hint: bool
    open_world_hint: bool


def recording_tool_registrar(
    tools: dict[str, RegisteredTool],
) -> Callable[..., Callable[[Callable[..., Any]], Callable[..., Any]]]:
    """Return a dependency-free registrar that captures MCP tool metadata."""

    def tool(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Capture one SDK-style tool registration."""

        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            """Store and return the registered function unchanged."""
            tools[kwargs["name"]] = (function, kwargs)
            return function

        return decorator

    return tool
