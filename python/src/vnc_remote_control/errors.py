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
        command_id: int | None = None,
        outcome: str | None = None,
        retry_safe: bool | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.command_id = command_id
        self.outcome = outcome
        self.retry_safe = retry_safe
        self.message = message
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        parts = [f"HTTP {self.status_code}"]
        if self.code:
            parts.append(self.code)
        parts.append(self.message)
        if self.command_id is not None:
            parts.append(f"command_id={self.command_id}")
        if self.outcome is not None:
            parts.append(f"outcome={self.outcome}")
        if self.retry_safe is not None:
            parts.append(f"retry_safe={self.retry_safe}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return ": ".join(parts)


class CommandOutcomeUnknownError(ApiError):
    """An accepted mutation timed out before its terminal outcome was observed.

    The command may still execute after this exception is raised. Callers must
    inspect ``command_id`` with the command-status endpoint before deciding on
    any further mutation; blind automatic retry is explicitly unsafe.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        command_id: int,
        request_id: str | None = None,
    ) -> None:
        super().__init__(
            status_code,
            message,
            code="command_timeout",
            request_id=request_id,
            command_id=command_id,
            outcome="unknown",
            retry_safe=False,
        )
