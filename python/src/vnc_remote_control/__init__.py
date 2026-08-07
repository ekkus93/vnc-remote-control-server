"""Typed Python client for the VNC Remote Control Server HTTP API."""

from .client import VncClient, VncRemoteControlClient
from .errors import (
    ApiError,
    OptionalDependencyError,
    ProtocolError,
    TransportError,
    VncRemoteControlError,
)
from .models import (
    ClipboardResponse,
    CommandAcceptedResponse,
    ConnectionState,
    DisplayResponse,
    Event,
    HealthResponse,
    KeyAction,
    MouseButton,
    ScreenshotResponse,
    StatusResponse,
    WorkerFailure,
)

__all__ = [
    "ApiError",
    "ClipboardResponse",
    "CommandAcceptedResponse",
    "ConnectionState",
    "DisplayResponse",
    "Event",
    "HealthResponse",
    "KeyAction",
    "MouseButton",
    "OptionalDependencyError",
    "ProtocolError",
    "ScreenshotResponse",
    "StatusResponse",
    "TransportError",
    "VncClient",
    "VncRemoteControlClient",
    "VncRemoteControlError",
    "WorkerFailure",
]
