"""Fail-closed configuration and file-backed secret loading for the MCP adapter."""

from __future__ import annotations

import ipaddress
import math
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from .client import VncRemoteControlClient

DEFAULT_CONTROLLER_URL = "http://127.0.0.1:8080"
DEFAULT_CONTROLLER_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_CONCURRENT_CALLS = 8
DEFAULT_TRANSPORT = "stdio"
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
MAX_SECRET_BYTES = 4 * 1024
MIN_CONTROLLER_TIMEOUT_SECONDS = 0.1
MAX_CONTROLLER_TIMEOUT_SECONDS = 60.0
MIN_MAX_CONCURRENT_CALLS = 1
MAX_MAX_CONCURRENT_CALLS = 64
MIN_HTTP_PORT = 1
MAX_HTTP_PORT = 65_535

McpTransport = Literal["stdio", "streamable-http"]


class McpConfigError(ValueError):
    """Raised when MCP configuration fails validation."""


@dataclass(frozen=True, slots=True, repr=False)
class McpConfig:
    """Validated MCP process configuration with a redacted controller token."""

    controller_url: str
    controller_token_file: Path
    _controller_token: str = field(repr=False)
    controller_timeout_seconds: float
    allow_mutations: bool
    max_concurrent_calls: int
    transport: McpTransport
    http_host: str
    http_port: int

    @classmethod
    def load(cls, environment: Mapping[str, str] | None = None) -> McpConfig:
        """Load and validate MCP configuration from environment and filesystem."""
        source = os.environ if environment is None else environment
        controller_url = _value_or(
            source, "VRC_MCP_CONTROLLER_URL", DEFAULT_CONTROLLER_URL
        )
        timeout = _parse_float(
            source,
            "VRC_MCP_CONTROLLER_TIMEOUT_SECONDS",
            DEFAULT_CONTROLLER_TIMEOUT_SECONDS,
            MIN_CONTROLLER_TIMEOUT_SECONDS,
            MAX_CONTROLLER_TIMEOUT_SECONDS,
        )

        # Reuse the typed client's URL/timeout validation instead of maintaining
        # a second URL parser with subtly different behavior.
        try:
            VncRemoteControlClient(controller_url, token=None, timeout=timeout)
        except ValueError as exc:
            raise McpConfigError("invalid VRC_MCP_CONTROLLER_URL or timeout") from exc

        token_path_value = _required_value(source, "VRC_MCP_CONTROLLER_TOKEN_FILE")
        token_path = Path(token_path_value)
        token = _read_secret_file(token_path)

        # Reuse the client's bearer-token validation as the final token preflight.
        # This catches embedded CR/LF after the secret reader removes trailing
        # line endings, without issuing a controller request.
        try:
            VncRemoteControlClient(controller_url, token=token, timeout=timeout)
        except ValueError as exc:
            raise McpConfigError("invalid controller token contents") from exc

        allow_mutations = _parse_bool(
            source, "VRC_MCP_ALLOW_MUTATIONS", default=False
        )
        max_concurrent_calls = _parse_int(
            source,
            "VRC_MCP_MAX_CONCURRENT_CALLS",
            DEFAULT_MAX_CONCURRENT_CALLS,
            MIN_MAX_CONCURRENT_CALLS,
            MAX_MAX_CONCURRENT_CALLS,
        )
        transport_value = _value_or(source, "VRC_MCP_TRANSPORT", DEFAULT_TRANSPORT)
        if transport_value not in {"stdio", "streamable-http"}:
            raise McpConfigError("invalid VRC_MCP_TRANSPORT")
        transport = cast(McpTransport, transport_value)

        http_host = _value_or(source, "VRC_MCP_HTTP_HOST", DEFAULT_HTTP_HOST)
        _require_loopback_host(http_host)
        http_port = _parse_int(
            source,
            "VRC_MCP_HTTP_PORT",
            DEFAULT_HTTP_PORT,
            MIN_HTTP_PORT,
            MAX_HTTP_PORT,
        )

        return cls(
            controller_url=controller_url,
            controller_token_file=token_path,
            _controller_token=token,
            controller_timeout_seconds=timeout,
            allow_mutations=allow_mutations,
            max_concurrent_calls=max_concurrent_calls,
            transport=transport,
            http_host=http_host,
            http_port=http_port,
        )

    def build_client(self) -> VncRemoteControlClient:
        """Construct the typed controller client without exposing the token."""
        return VncRemoteControlClient(
            self.controller_url,
            token=self._controller_token,
            timeout=self.controller_timeout_seconds,
        )

    @property
    def token_set(self) -> bool:
        """Report token presence without exposing token contents."""
        return bool(self._controller_token)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(controller_url={self.controller_url!r}, "
            f"controller_token_file={str(self.controller_token_file)!r}, "
            f"controller_timeout_seconds={self.controller_timeout_seconds!r}, "
            f"allow_mutations={self.allow_mutations!r}, "
            f"max_concurrent_calls={self.max_concurrent_calls!r}, "
            f"transport={self.transport!r}, http_host={self.http_host!r}, "
            f"http_port={self.http_port!r}, token_set={self.token_set!r})"
        )


def _environment_value(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name)
    if value is None:
        return None
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise McpConfigError(f"invalid {name}") from exc
    return value


def _value_or(environment: Mapping[str, str], name: str, default: str) -> str:
    value = _environment_value(environment, name)
    return default if value is None else value


def _required_value(environment: Mapping[str, str], name: str) -> str:
    value = _environment_value(environment, name)
    if value is None or not value:
        raise McpConfigError(f"missing or empty {name}")
    return value


def _parse_bool(environment: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = _environment_value(environment, name)
    if value is None:
        return default
    if value in {"1", "true"}:
        return True
    if value in {"0", "false"}:
        return False
    raise McpConfigError(f"invalid {name}")


def _parse_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = _environment_value(environment, name)
    if raw is None:
        return default
    if not raw or not raw.isascii() or not raw.isdigit():
        raise McpConfigError(f"invalid {name}")
    value = int(raw, 10)
    if value < minimum or value > maximum:
        raise McpConfigError(f"invalid {name}")
    return value


def _parse_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = _environment_value(environment, name)
    if raw is None:
        return default
    if not raw or not raw.isascii() or raw != raw.strip():
        raise McpConfigError(f"invalid {name}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise McpConfigError(f"invalid {name}") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise McpConfigError(f"invalid {name}")
    return value


def _require_loopback_host(host: str) -> None:
    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise McpConfigError("invalid VRC_MCP_HTTP_HOST; loopback address required") from exc
    if not address.is_loopback:
        raise McpConfigError("invalid VRC_MCP_HTTP_HOST; loopback address required")


def _secret_error(path: Path, reason: str) -> McpConfigError:
    return McpConfigError(f"secret file {str(path)!r}: {reason}")


def _validate_secret_stat(path: Path, stat_result: os.stat_result) -> None:
    if not stat.S_ISREG(stat_result.st_mode):
        raise _secret_error(path, "not a regular file")
    if stat_result.st_size == 0 or stat_result.st_size > MAX_SECRET_BYTES:
        raise _secret_error(path, "size is outside the accepted bound")
    if os.name == "posix":
        mode = stat.S_IMODE(stat_result.st_mode)
        if mode & 0o022 != 0 or mode & 0o111 != 0:
            raise _secret_error(
                path, "group/other write or execute permission is forbidden"
            )


def _read_secret_file(path: Path) -> str:
    try:
        initial_stat = path.stat()
    except OSError as exc:
        raise _secret_error(path, "cannot read metadata") from exc
    _validate_secret_stat(path, initial_stat)

    try:
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            _validate_secret_stat(path, opened_stat)
            raw = handle.read(MAX_SECRET_BYTES + 1)
    except McpConfigError:
        raise
    except OSError as exc:
        raise _secret_error(path, "cannot read contents") from exc

    if len(raw) == 0 or len(raw) > MAX_SECRET_BYTES:
        raise _secret_error(path, "size is outside the accepted bound")
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _secret_error(path, "contents are not UTF-8") from exc
    value = value.rstrip("\r\n")
    if not value or "\x00" in value:
        raise _secret_error(path, "contents are empty or contain NUL")
    return value
