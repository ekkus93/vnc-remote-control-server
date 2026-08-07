from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, TypeAlias

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
    status: str


@dataclass(frozen=True, slots=True)
class StatusResponse:
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
    status: str
    width: int
    height: int
    depth: int
    revision: int
    updated_at_unix_ms: int
    complete: bool


@dataclass(frozen=True, slots=True)
class CommandAcceptedResponse:
    command_id: int
    status: str


@dataclass(frozen=True, slots=True)
class ClipboardResponse:
    text: str
    revision: int
    updated_at_unix_ms: int


@dataclass(frozen=True, slots=True)
class ScreenshotResponse:
    data: bytes | None
    etag: str | None
    cache_control: str | None
    request_id: str | None
    not_modified: bool


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    timestamp_unix_ms: int
    type: str
    payload: Mapping[str, Any]
