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
    "transport",
    "timeout",
    "protocol",
    "native",
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
class CommandAcceptedResponse:
    """Body of a 202-Accepted response for a queued command."""

    command_id: int
    status: str


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
    etag: str | None
    cache_control: str | None
    request_id: str | None
    not_modified: bool


@dataclass(frozen=True, slots=True)
class Event:
    """A single parsed `/v1/events` WebSocket message."""

    sequence: int
    timestamp_unix_ms: int
    type: str
    payload: Mapping[str, Any]
