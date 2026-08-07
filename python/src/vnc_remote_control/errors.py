"""Exception types raised by the VNC Remote Control Server Python client."""

from __future__ import annotations


class VncRemoteControlError(Exception):
    """Base exception for the Python client."""


class TransportError(VncRemoteControlError):
    """The controller could not be reached or the response transport failed."""


class ProtocolError(VncRemoteControlError):
    """A successful controller response did not match the documented protocol."""


class OptionalDependencyError(VncRemoteControlError):
    """An optional feature was requested without its required dependency."""


class ApiError(VncRemoteControlError):
    """A non-success HTTP response returned by the controller."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.message = message
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        parts = [f"HTTP {self.status_code}"]
        if self.code:
            parts.append(self.code)
        parts.append(self.message)
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return ": ".join(parts)
