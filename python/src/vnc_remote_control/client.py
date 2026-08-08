"""Synchronous HTTP/WebSocket client for the VNC Remote Control Server API."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, get_args
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .errors import (
    ApiError,
    OptionalDependencyError,
    ProtocolError,
    TransportError,
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

try:
    import websocket as _websocket_module  # type: ignore[import-not-found]
except ImportError:
    _websocket_module = None


# Derived from the `models` Literal types (single source of truth) rather than
# repeating the closed vocabularies here, so the two can never drift apart.
_CONNECTION_STATES = frozenset(get_args(ConnectionState))
_WORKER_FAILURES = frozenset(get_args(WorkerFailure))
_HEALTH_STATUSES = frozenset({"alive", "ready"})
_DISPLAY_STATUSES = frozenset({"current"})
_COMMAND_STATUSES = frozenset({"accepted"})
_EMPTY_RUNTIME_ERROR_STATUSES = frozenset({400, 408, 413})


class _HttpResponse(Protocol):
    status: int
    headers: Any

    def read(self) -> bytes:
        """Return the full response body."""

    def __enter__(self) -> _HttpResponse:
        """Enter the response's context manager."""

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit the response's context manager, releasing the connection."""


class _WebSocket(Protocol):
    def recv(self) -> str | bytes | None:
        """Return the next message, or a falsy value once the socket closes."""

    def close(self) -> Any:
        """Close the WebSocket connection."""


HttpOpen = Callable[..., _HttpResponse]
WebSocketFactory = Callable[..., _WebSocket]


@dataclass(frozen=True, slots=True)
class _RequestOptions:
    """Non-positional knobs shared by `_request` and `_json_request`."""

    authenticated: bool
    json_body: dict[str, Any] | None = None
    extra_headers: dict[str, str] | None = None


def _require_object(payload: bytes, context: str) -> dict[str, Any]:
    try:
        decoded = payload.decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"{context} was not valid UTF-8 JSON") from exc
    return _require_object_value(value, context)


def _require_object_value(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{context} was not a JSON object")
    return value


def _require_fields(value: dict[str, Any], fields: Sequence[str], context: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ProtocolError(f"{context} omitted required field(s): {', '.join(missing)}")


def _require_exact_fields(
    value: dict[str, Any], fields: Sequence[str], context: str
) -> None:
    _require_fields(value, fields, context)
    allowed = frozenset(fields)
    if any(field not in allowed for field in value):
        raise ProtocolError(f"{context} contained unexpected field(s)")


def _require_string(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{context} field {field} was not a string")
    return value


def _require_bool(value: Any, field: str, context: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError(f"{context} field {field} was not a boolean")
    return value


def _require_int(
    value: Any,
    field: str,
    context: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProtocolError(f"{context} field {field} was not an integer")
    if minimum is not None and value < minimum:
        raise ProtocolError(f"{context} field {field} was below its minimum")
    if maximum is not None and value > maximum:
        raise ProtocolError(f"{context} field {field} exceeded its maximum")
    return value


def _require_nullable_int(
    value: Any,
    field: str,
    context: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return None
    return _require_int(value, field, context, minimum=minimum, maximum=maximum)


def _require_enum(
    value: Any, field: str, context: str, allowed: frozenset[str]
) -> str:
    result = _require_string(value, field, context)
    if result not in allowed:
        raise ProtocolError(f"{context} field {field} was not an allowed string value")
    return result


def _require_nullable_enum(
    value: Any, field: str, context: str, allowed: frozenset[str]
) -> str | None:
    if value is None:
        return None
    return _require_enum(value, field, context, allowed)


def _require_http_status(value: Any, context: str) -> int:
    return _require_int(value, "status", context, minimum=100, maximum=599)


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"HTTP response header {name} was not a string")
    return value


def _decode_message(message: str | bytes) -> str:
    """Decode a raw WebSocket text/binary message to text."""
    if isinstance(message, bytes):
        try:
            return message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("WebSocket event was not valid UTF-8") from exc
    return message


def _parse_event(text: str) -> Event:
    """Parse and validate one WebSocket event payload."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("WebSocket event was not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("WebSocket event was not a JSON object")
    _require_fields(value, ("sequence", "timestamp_unix_ms", "type"), "WebSocket event")
    sequence = _require_int(value["sequence"], "sequence", "WebSocket event", minimum=0)
    timestamp = _require_int(
        value["timestamp_unix_ms"], "timestamp_unix_ms", "WebSocket event", minimum=0
    )
    event_type = _require_string(value["type"], "type", "WebSocket event")
    payload = {
        key: item
        for key, item in value.items()
        if key not in {"sequence", "timestamp_unix_ms", "type"}
    }
    return Event(
        sequence=sequence,
        timestamp_unix_ms=timestamp,
        type=event_type,
        payload=payload,
    )


class VncRemoteControlClient:
    """Synchronous typed client for the VNC Remote Control Server API.

    Core HTTP functionality uses only the Python standard library. WebSocket
    events require the optional ``websocket-client`` dependency unless a
    WebSocket factory is injected for testing.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        token: str | None = None,
        *,
        timeout: float = 5.0,
        _http_open: HttpOpen | None = None,
        _websocket_factory: WebSocketFactory | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http:// or https:// URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain a query string or fragment")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if token is not None:
            if not token:
                raise ValueError("token must not be empty")
            if "\r" in token or "\n" in token:
                raise ValueError("token must not contain CR or LF")

        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = float(timeout)
        self._http_open = _http_open or cast(HttpOpen, urlopen)
        self._websocket_factory = _websocket_factory

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self._base_url!r}, "
            f"timeout={self._timeout!r}, token_set={self._token is not None})"
        )

    @property
    def base_url(self) -> str:
        """The base URL requests are issued against."""
        return self._base_url

    @property
    def timeout(self) -> float:
        """The per-request timeout, in seconds."""
        return self._timeout

    def _require_token(self) -> str:
        if self._token is None:
            raise ValueError("this endpoint requires a bearer token")
        return self._token

    def _api_error(self, status: int, headers: Any, body: bytes) -> ApiError:
        request_id = _header(headers, "X-Request-ID")
        if not body:
            if status not in _EMPTY_RUNTIME_ERROR_STATUSES:
                raise ProtocolError("structured HTTP error response was unexpectedly empty")
            return ApiError(
                status,
                f"controller returned HTTP {status}",
                code=None,
                request_id=request_id,
            )

        document = _require_object(body, "error response")
        _require_exact_fields(document, ("error",), "error response")
        error = _require_object_value(document["error"], "error response error field")
        _require_exact_fields(
            error, ("code", "message", "request_id"), "error response error field"
        )
        code = _require_string(error["code"], "code", "error response error field")
        message = _require_string(error["message"], "message", "error response error field")
        request_id = _require_string(
            error["request_id"], "request_id", "error response error field"
        )
        return ApiError(
            status,
            message,
            code=code,
            request_id=request_id,
        )

    def _request(
        self,
        method: str,
        path: str,
        expected_statuses: set[int],
        options: _RequestOptions,
    ) -> tuple[int, Any, bytes]:
        """Issue one HTTP request and return `(status, headers, body)`."""
        headers = {"Accept": "application/json"}
        if options.authenticated:
            headers["Authorization"] = f"Bearer {self._require_token()}"
        if options.json_body is not None:
            body = json.dumps(options.json_body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            body = None
        if options.extra_headers:
            headers.update(options.extra_headers)

        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._http_open(request, timeout=self._timeout) as response:
                status = _require_http_status(response.status, "HTTP response")
                response_headers = response.headers
                response_body = response.read()
        except HTTPError as exc:
            status = _require_http_status(exc.code, "HTTP error response")
            response_headers = exc.headers
            response_body = exc.read()
            if status in expected_statuses:
                return status, response_headers, response_body
            try:
                error = self._api_error(status, response_headers, response_body)
            except ProtocolError as protocol_error:
                raise protocol_error from exc
            raise error from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"HTTP request failed for {method} {path}") from exc

        if status not in expected_statuses:
            error = self._api_error(status, response_headers, response_body)
            raise error
        return status, response_headers, response_body

    def _json_request(
        self,
        method: str,
        path: str,
        expected_status: int,
        options: _RequestOptions,
    ) -> dict[str, Any]:
        """Issue one HTTP request and return its parsed JSON object body."""
        _, _, body = self._request(method, path, {expected_status}, options)
        return _require_object(body, f"{method} {path} response")

    def get_openapi_document(self) -> dict[str, Any]:
        """Fetch the controller-hosted OpenAPI 3.1 document."""
        return self._json_request(
            "GET", "/openapi.json", 200, _RequestOptions(authenticated=False)
        )

    def get_liveness(self) -> HealthResponse:
        """Fetch `/health/live`, which never requires a bearer token."""
        value = self._json_request(
            "GET", "/health/live", 200, _RequestOptions(authenticated=False)
        )
        context = "liveness response"
        _require_exact_fields(value, ("status",), context)
        return HealthResponse(
            status=_require_enum(value["status"], "status", context, _HEALTH_STATUSES)
        )

    def get_readiness(self) -> HealthResponse:
        """Fetch `/health/ready`, which never requires a bearer token."""
        value = self._json_request(
            "GET", "/health/ready", 200, _RequestOptions(authenticated=False)
        )
        context = "readiness response"
        _require_exact_fields(value, ("status",), context)
        return HealthResponse(
            status=_require_enum(value["status"], "status", context, _HEALTH_STATUSES)
        )

    def get_status(self) -> StatusResponse:
        """Fetch the worker's current connection and lifecycle status."""
        value = self._json_request(
            "GET", "/v1/status", 200, _RequestOptions(authenticated=True)
        )
        fields = (
            "state",
            "started_at_unix_ms",
            "connected_at_unix_ms",
            "last_message_at_unix_ms",
            "reconnect_attempts",
            "last_failure",
            "framebuffer_revision",
            "rejected_commands",
            "dropped_events",
            "fatal_exit",
            "shutting_down",
        )
        context = "status response"
        _require_exact_fields(value, fields, context)
        state = _require_enum(value["state"], "state", context, _CONNECTION_STATES)
        last_failure = _require_nullable_enum(
            value["last_failure"], "last_failure", context, _WORKER_FAILURES
        )
        return StatusResponse(
            state=cast(ConnectionState, state),
            started_at_unix_ms=_require_int(
                value["started_at_unix_ms"], "started_at_unix_ms", context, minimum=0
            ),
            connected_at_unix_ms=_require_nullable_int(
                value["connected_at_unix_ms"],
                "connected_at_unix_ms",
                context,
                minimum=0,
            ),
            last_message_at_unix_ms=_require_nullable_int(
                value["last_message_at_unix_ms"],
                "last_message_at_unix_ms",
                context,
                minimum=0,
            ),
            reconnect_attempts=_require_int(
                value["reconnect_attempts"], "reconnect_attempts", context, minimum=0
            ),
            last_failure=cast(WorkerFailure | None, last_failure),
            framebuffer_revision=_require_nullable_int(
                value["framebuffer_revision"],
                "framebuffer_revision",
                context,
                minimum=0,
            ),
            rejected_commands=_require_int(
                value["rejected_commands"], "rejected_commands", context, minimum=0
            ),
            dropped_events=_require_int(
                value["dropped_events"], "dropped_events", context, minimum=0
            ),
            fatal_exit=_require_bool(value["fatal_exit"], "fatal_exit", context),
            shutting_down=_require_bool(value["shutting_down"], "shutting_down", context),
        )

    def get_display(self) -> DisplayResponse:
        """Fetch the current framebuffer geometry and revision."""
        value = self._json_request(
            "GET", "/v1/display", 200, _RequestOptions(authenticated=True)
        )
        fields = (
            "status",
            "width",
            "height",
            "depth",
            "revision",
            "updated_at_unix_ms",
            "complete",
        )
        context = "display response"
        _require_exact_fields(value, fields, context)
        depth = _require_int(value["depth"], "depth", context)
        if depth != 24:
            raise ProtocolError("display response field depth did not match its required value")
        complete = _require_bool(value["complete"], "complete", context)
        if not complete:
            raise ProtocolError("display response field complete did not match its required value")
        return DisplayResponse(
            status=_require_enum(value["status"], "status", context, _DISPLAY_STATUSES),
            width=_require_int(value["width"], "width", context, minimum=1),
            height=_require_int(value["height"], "height", context, minimum=1),
            depth=depth,
            revision=_require_int(value["revision"], "revision", context, minimum=1),
            updated_at_unix_ms=_require_int(
                value["updated_at_unix_ms"], "updated_at_unix_ms", context, minimum=0
            ),
            complete=complete,
        )

    def get_screenshot(self, *, etag: str | None = None) -> ScreenshotResponse:
        """Fetch the current screenshot as PNG bytes.

        Passing the previous response's ``etag`` lets the controller reply
        304-Not-Modified (``data=None``) when the framebuffer is unchanged.
        """
        headers = {"Accept": "image/png"}
        if etag is not None:
            headers["If-None-Match"] = etag
        status, response_headers, body = self._request(
            "GET",
            "/v1/screenshot.png",
            {200, 304},
            _RequestOptions(authenticated=True, extra_headers=headers),
        )
        return ScreenshotResponse(
            data=body if status == 200 else None,
            etag=_header(response_headers, "ETag"),
            cache_control=_header(response_headers, "Cache-Control"),
            request_id=_header(response_headers, "X-Request-ID"),
            not_modified=status == 304,
        )

    def get_metrics(self) -> str:
        """Fetch the controller's Prometheus-format metrics as plain text."""
        _, _, body = self._request(
            "GET",
            "/v1/metrics",
            {200},
            _RequestOptions(authenticated=True, extra_headers={"Accept": "text/plain"}),
        )
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("metrics response was not valid UTF-8") from exc

    def _command(self, path: str, body: dict[str, Any] | None = None) -> CommandAcceptedResponse:
        """POST (or PUT, for clipboard) a command and return its 202 acknowledgement."""
        value = self._json_request(
            "POST" if path != "/v1/clipboard" else "PUT",
            path,
            202,
            _RequestOptions(authenticated=True, json_body=body),
        )
        context = f"{path} response"
        _require_exact_fields(value, ("command_id", "status"), context)
        return CommandAcceptedResponse(
            command_id=_require_int(value["command_id"], "command_id", context, minimum=1),
            status=_require_enum(value["status"], "status", context, _COMMAND_STATUSES),
        )

    def move_pointer(self, x: int, y: int) -> CommandAcceptedResponse:
        """Move the pointer to `(x, y)` without changing button state."""
        return self._command("/v1/pointer/move", {"x": x, "y": y})

    def set_pointer_button(
        self,
        x: int,
        y: int,
        button: MouseButton,
        pressed: bool,
    ) -> CommandAcceptedResponse:
        """Move to `(x, y)` and set `button` to pressed or released."""
        return self._command(
            "/v1/pointer/button",
            {"x": x, "y": y, "button": button, "pressed": pressed},
        )

    def click_pointer(
        self, x: int, y: int, button: MouseButton = "left"
    ) -> CommandAcceptedResponse:
        """Move to `(x, y)` and click `button` once."""
        return self._command(
            "/v1/pointer/click", {"x": x, "y": y, "button": button}
        )

    def double_click_pointer(
        self,
        x: int,
        y: int,
        button: MouseButton = "left",
        *,
        interval_ms: int = 100,
    ) -> CommandAcceptedResponse:
        """Move to `(x, y)` and double-click `button` with the given interval."""
        return self._command(
            "/v1/pointer/double-click",
            {
                "x": x,
                "y": y,
                "button": button,
                "interval_ms": interval_ms,
            },
        )

    def scroll_pointer(
        self,
        x: int,
        y: int,
        delta_y: int,
        *,
        delta_x: int = 0,
    ) -> CommandAcceptedResponse:
        """Move to `(x, y)` and scroll by `(delta_x, delta_y)`."""
        return self._command(
            "/v1/pointer/scroll",
            {"x": x, "y": y, "delta_x": delta_x, "delta_y": delta_y},
        )

    def set_keyboard_key(
        self, key: str, action: KeyAction
    ) -> CommandAcceptedResponse:
        """Press or release a single named keyboard key."""
        return self._command("/v1/keyboard/key", {"key": key, "action": action})

    def send_keyboard_chord(self, keys: Sequence[str]) -> CommandAcceptedResponse:
        """Press and release `keys` together as a chord."""
        return self._command("/v1/keyboard/chord", {"keys": list(keys)})

    def type_keyboard_text(self, text: str) -> CommandAcceptedResponse:
        """Type `text` via per-character key events."""
        return self._command("/v1/keyboard/text", {"text": text})

    def get_clipboard(self) -> ClipboardResponse:
        """Fetch the desktop's current clipboard snapshot."""
        value = self._json_request(
            "GET", "/v1/clipboard", 200, _RequestOptions(authenticated=True)
        )
        context = "clipboard response"
        _require_exact_fields(
            value, ("text", "revision", "updated_at_unix_ms"), context
        )
        return ClipboardResponse(
            text=_require_string(value["text"], "text", context),
            revision=_require_int(value["revision"], "revision", context, minimum=1),
            updated_at_unix_ms=_require_int(
                value["updated_at_unix_ms"], "updated_at_unix_ms", context, minimum=0
            ),
        )

    def set_clipboard(self, text: str) -> CommandAcceptedResponse:
        """Set the desktop's clipboard to `text`."""
        return self._command("/v1/clipboard", {"text": text})

    def request_reconnect(self) -> CommandAcceptedResponse:
        """Request the worker manually reconnect to the desktop."""
        return self._command("/v1/connection/reconnect")

    def _event_url(self) -> str:
        """Return the `/v1/events` WebSocket URL derived from `base_url`."""
        parsed = urlsplit(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, f"{parsed.path.rstrip('/')}/v1/events", "", ""))

    def _open_websocket(self) -> _WebSocket:
        """Open (or construct via the injected factory) the events WebSocket."""
        token = self._require_token()
        factory = self._websocket_factory
        if factory is None:
            if _websocket_module is None:
                raise OptionalDependencyError(
                    "WebSocket events require: pip install 'vnc-remote-control-client[websocket]'"
                )
            factory = cast(WebSocketFactory, _websocket_module.create_connection)
        try:
            return factory(
                self._event_url(),
                header=[f"Authorization: Bearer {token}"],
                timeout=self._timeout,
            )
        except Exception as exc:
            raise TransportError("WebSocket upgrade failed for /v1/events") from exc

    def iter_events(self) -> Iterator[Event]:
        """Yield parsed controller events until the WebSocket closes.

        The optional WebSocket dependency receives the bearer token in the
        upgrade request header. The token is never added to the URL.
        """
        websocket = self._open_websocket()
        primary_error: BaseException | None = None
        try:
            while True:
                try:
                    message = websocket.recv()
                except Exception as exc:
                    raise TransportError("WebSocket receive failed for /v1/events") from exc
                if message is None or message == "":
                    return
                yield _parse_event(_decode_message(message))
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                websocket.close()
            except Exception as close_exc:
                if primary_error is None:
                    raise TransportError("WebSocket close failed for /v1/events") from close_exc
                primary_error.add_note(
                    f"additional WebSocket close failure: {type(close_exc).__name__}"
                )
                raise primary_error from close_exc


VncClient = VncRemoteControlClient
