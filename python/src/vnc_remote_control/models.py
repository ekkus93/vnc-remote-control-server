"""Typed response models mirroring the controller's HTTP/WebSocket JSON shapes.

Each dataclass field maps 1:1 to a documented JSON field so callers can rely
on the wire contract without re-parsing raw dictionaries themselves.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

ConnectionState: TypeAlias = Literal[
    "starting",
    "connecting",
    "connected",
    "degraded",
    "reconnecting",
    "disconnected",
    "authentication_failed",
    "stopped",
]
WorkerFailure: TypeAlias = Literal[
    "authentication",
    "configuration",
    "request",
    "capacity",
    "unavailable",
    "rate_limited",
    "transport",
    "timeout",
    "protocol",
    "native",
]
CommandStatus: TypeAlias = Literal[
    "reserved",
    "queued",
    "running",
    "succeeded",
    "failed",
    "aborted",
    "rejected",
]
MouseButton: TypeAlias = Literal["left", "middle", "right"]
KeyAction: TypeAlias = Literal["down", "up"]


@dataclass(frozen=True, slots=True)
class HealthResponse:
    """Body of a `/health/live` or `/health/ready` response."""

    status: str


@dataclass(frozen=True, slots=True)
class StatusResponse:
    """Body of a `/v1/status` response."""

    state: ConnectionState
    started_at_unix_ms: int
    connected_at_unix_ms: int | None
    last_message_at_unix_ms: int | None
    reconnect_attempts: int
    last_failure: WorkerFailure | None
    framebuffer_revision: int | None
    rejected_commands: int
    dropped_events: int
    fatal_exit: bool
    shutting_down: bool


@dataclass(frozen=True, slots=True)
class DisplayResponse:
    """Body of a `/v1/display` response."""

    status: str
    width: int
    height: int
    depth: int
    revision: int
    updated_at_unix_ms: int
    complete: bool


@dataclass(frozen=True, slots=True)
class CommandResponse:
    """Terminal-success response for a synchronous mutation command."""

    command_id: int
    status: str


# Backward-compatible import alias. The server no longer returns HTTP 202 or an
# "accepted" status for these synchronous mutation methods.
CommandAcceptedResponse = CommandResponse


@dataclass(frozen=True, slots=True)
class CommandStatusResponse:
    """Retained lifecycle status for one process-local command identifier."""

    command_id: int
    status: CommandStatus
    failure: str | None
    retry_safe: bool


@dataclass(frozen=True, slots=True)
class ClipboardResponse:
    """Body of a `/v1/clipboard` GET response."""

    text: str
    revision: int
    updated_at_unix_ms: int


@dataclass(frozen=True, slots=True)
class ScreenshotResponse:
    """Body of a `/v1/screenshot.png` response.

    ``data`` is ``None`` exactly when ``not_modified`` is ``True`` (a 304
    response for a matching ``If-None-Match`` etag).
    """

    data: bytes | None
    etag: str
    cache_control: str
    not_modified: bool


@dataclass(frozen=True, slots=True)
class CommandEvent:
    """Base payload shared by every parsed event model."""

    sequence: int
    timestamp_unix_ms: int
    type: str


@dataclass(frozen=True, slots=True)
class SnapshotEvent(CommandEvent):
    """Initial `/v1/events` snapshot."""

    state: ConnectionState
    framebuffer_revision: int | None
    clipboard_revision: int | None
    reconnect_attempts: int
    last_failure: WorkerFailure | None
    rejected_commands: int
    dropped_events: int
    fatal_exit: bool


@dataclass(frozen=True, slots=True)
class ConnectionStateEvent(CommandEvent):
    """Connection-state transition event."""

    state: ConnectionState


@dataclass(frozen=True, slots=True)
class FramebufferRevisionEvent(CommandEvent):
    """Current framebuffer revision event."""

    revision: int


@dataclass(frozen=True, slots=True)
class FramebufferInvalidatedEvent(CommandEvent):
    """Framebuffer invalidation event."""


@dataclass(frozen=True, slots=True)
class ClipboardRevisionEvent(CommandEvent):
    """Clipboard revision event; clipboard content is never included."""

    revision: int


@dataclass(frozen=True, slots=True)
class OverloadEvent(CommandEvent):
    """Bounded-capacity overload event."""


@dataclass(frozen=True, slots=True)
class ProtocolErrorEvent(CommandEvent):
    """Sanitized VNC protocol-error event."""


Event: TypeAlias = (
    SnapshotEvent
    | ConnectionStateEvent
    | FramebufferRevisionEvent
    | FramebufferInvalidatedEvent
    | ClipboardRevisionEvent
    | OverloadEvent
    | ProtocolErrorEvent
)


def require_mapping(value: object, context: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping or fail with a stable type error."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    return value
