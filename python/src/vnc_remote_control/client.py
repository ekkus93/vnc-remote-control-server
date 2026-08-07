from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Protocol, cast
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


class _HttpResponse(Protocol):
    status: int
    headers: Any

    def read(self) -> bytes: ...

    def __enter__(self) -> "_HttpResponse": ...

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...


class _WebSocket(Protocol):
    def recv(self) -> str | bytes | None: ...

    def close(self) -> Any: ...


HttpOpen = Callable[..., _HttpResponse]
WebSocketFactory = Callable[..., _WebSocket]


def _require_object(payload: bytes, context: str) -> dict[str, Any]:
    try:
        decoded = payload.decode("utf-8")
        value = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"{context} was not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError(f"{context} was not a JSON object")
    return value


def _require_fields(value: dict[str, Any], fields: Sequence[str], context: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ProtocolError(f"{context} omitted required field(s): {', '.join(missing)}")


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    value = headers.get(name)
    return str(value) if value is not None else None


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
        return self._base_url

    @property
    def timeout(self) -> float:
        return self._timeout

    def _require_token(self) -> str:
        if self._token is None:
            raise ValueError("this endpoint requires a bearer token")
        return self._token

    def _api_error(self, status: int, headers: Any, body: bytes) -> ApiError:
        request_id = _header(headers, "X-Request-ID")
        code: str | None = None
        message = f"controller returned HTTP {status}"
        if body:
            try:
                document = _require_object(body, "error response")
                error = document.get("error")
                if isinstance(error, dict):
                    raw_code = error.get("code")
                    raw_message = error.get("message")
                    raw_request_id = error.get("request_id")
                    if isinstance(raw_code, str):
                        code = raw_code
                    if isinstance(raw_message, str):
                        message = raw_message
                    if isinstance(raw_request_id, str):
                        request_id = raw_request_id
            except ProtocolError:
                # Empty/runtime-generated errors are documented for 400/408/413.
                # A malformed nonempty error body still surfaces as an HTTP error
                # without copying arbitrary response bytes into the exception.
                pass
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
        *,
        expected_statuses: set[int],
        authenticated: bool,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, bytes]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._require_token()}"
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            body = None
        if extra_headers:
            headers.update(extra_headers)

        request = Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._http_open(request, timeout=self._timeout) as response:
                status = int(response.status)
                response_headers = response.headers
                response_body = response.read()
        except HTTPError as exc:
            status = int(exc.code)
            response_headers = exc.headers
            response_body = exc.read()
            if status in expected_statuses:
                return status, response_headers, response_body
            raise self._api_error(status, response_headers, response_body) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"HTTP request failed for {method} {path}") from exc

        if status not in expected_statuses:
            raise self._api_error(status, response_headers, response_body)
        return status, response_headers, response_body

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        authenticated: bool,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _, _, body = self._request(
            method,
            path,
            expected_statuses={expected_status},
            authenticated=authenticated,
            json_body=json_body,
        )
        return _require_object(body, f"{method} {path} response")

    def get_openapi_document(self) -> dict[str, Any]:
        """Fetch the controller-hosted OpenAPI 3.1 document."""
        return self._json_request(
            "GET",
            "/openapi.json",
            expected_status=200,
            authenticated=False,
        )

    def get_liveness(self) -> HealthResponse:
        value = self._json_request(
            "GET", "/health/live", expected_status=200, authenticated=False
        )
        _require_fields(value, ("status",), "liveness response")
        return HealthResponse(status=str(value["status"]))

    def get_readiness(self) -> HealthResponse:
        value = self._json_request(
            "GET", "/health/ready", expected_status=200, authenticated=False
        )
        _require_fields(value, ("status",), "readiness response")
        return HealthResponse(status=str(value["status"]))

    def get_status(self) -> StatusResponse:
        value = self._json_request(
            "GET", "/v1/status", expected_status=200, authenticated=True
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
        _require_fields(value, fields, "status response")
        return StatusResponse(
            state=cast(ConnectionState, value["state"]),
            started_at_unix_ms=int(value["started_at_unix_ms"]),
            connected_at_unix_ms=(
                None
                if value["connected_at_unix_ms"] is None
                else int(value["connected_at_unix_ms"])
            ),
            last_message_at_unix_ms=(
                None
                if value["last_message_at_unix_ms"] is None
                else int(value["last_message_at_unix_ms"])
            ),
            reconnect_attempts=int(value["reconnect_attempts"]),
            last_failure=cast(WorkerFailure | None, value["last_failure"]),
            framebuffer_revision=(
                None
                if value["framebuffer_revision"] is None
                else int(value["framebuffer_revision"])
            ),
            rejected_commands=int(value["rejected_commands"]),
            dropped_events=int(value["dropped_events"]),
            fatal_exit=bool(value["fatal_exit"]),
            shutting_down=bool(value["shutting_down"]),
        )

    def get_display(self) -> DisplayResponse:
        value = self._json_request(
            "GET", "/v1/display", expected_status=200, authenticated=True
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
        _require_fields(value, fields, "display response")
        return DisplayResponse(
            status=str(value["status"]),
            width=int(value["width"]),
            height=int(value["height"]),
            depth=int(value["depth"]),
            revision=int(value["revision"]),
            updated_at_unix_ms=int(value["updated_at_unix_ms"]),
            complete=bool(value["complete"]),
        )

    def get_screenshot(self, *, etag: str | None = None) -> ScreenshotResponse:
        headers = {"Accept": "image/png"}
        if etag is not None:
            headers["If-None-Match"] = etag
        status, response_headers, body = self._request(
            "GET",
            "/v1/screenshot.png",
            expected_statuses={200, 304},
            authenticated=True,
            extra_headers=headers,
        )
        return ScreenshotResponse(
            data=body if status == 200 else None,
            etag=_header(response_headers, "ETag"),
            cache_control=_header(response_headers, "Cache-Control"),
            request_id=_header(response_headers, "X-Request-ID"),
            not_modified=status == 304,
        )

    def get_metrics(self) -> str:
        _, _, body = self._request(
            "GET",
            "/v1/metrics",
            expected_statuses={200},
            authenticated=True,
            extra_headers={"Accept": "text/plain"},
        )
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("metrics response was not valid UTF-8") from exc

    def _command(self, path: str, body: dict[str, Any] | None = None) -> CommandAcceptedResponse:
        value = self._json_request(
            "POST" if path != "/v1/clipboard" else "PUT",
            path,
            expected_status=202,
            authenticated=True,
            json_body=body,
        )
        _require_fields(value, ("command_id", "status"), f"{path} response")
        return CommandAcceptedResponse(
            command_id=int(value["command_id"]),
            status=str(value["status"]),
        )

    def move_pointer(self, x: int, y: int) -> CommandAcceptedResponse:
        return self._command("/v1/pointer/move", {"x": x, "y": y})

    def set_pointer_button(
        self,
        x: int,
        y: int,
        button: MouseButton,
        pressed: bool,
    ) -> CommandAcceptedResponse:
        return self._command(
            "/v1/pointer/button",
            {"x": x, "y": y, "button": button, "pressed": pressed},
        )

    def click_pointer(
        self, x: int, y: int, button: MouseButton = "left"
    ) -> CommandAcceptedResponse:
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
        return self._command(
            "/v1/pointer/scroll",
            {"x": x, "y": y, "delta_x": delta_x, "delta_y": delta_y},
        )

    def set_keyboard_key(
        self, key: str, action: KeyAction
    ) -> CommandAcceptedResponse:
        return self._command("/v1/keyboard/key", {"key": key, "action": action})

    def send_keyboard_chord(self, keys: Sequence[str]) -> CommandAcceptedResponse:
        return self._command("/v1/keyboard/chord", {"keys": list(keys)})

    def type_keyboard_text(self, text: str) -> CommandAcceptedResponse:
        return self._command("/v1/keyboard/text", {"text": text})

    def get_clipboard(self) -> ClipboardResponse:
        value = self._json_request(
            "GET", "/v1/clipboard", expected_status=200, authenticated=True
        )
        _require_fields(
            value, ("text", "revision", "updated_at_unix_ms"), "clipboard response"
        )
        return ClipboardResponse(
            text=str(value["text"]),
            revision=int(value["revision"]),
            updated_at_unix_ms=int(value["updated_at_unix_ms"]),
        )

    def set_clipboard(self, text: str) -> CommandAcceptedResponse:
        return self._command("/v1/clipboard", {"text": text})

    def request_reconnect(self) -> CommandAcceptedResponse:
        return self._command("/v1/connection/reconnect")

    def _event_url(self) -> str:
        parsed = urlsplit(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, f"{parsed.path.rstrip('/')}/v1/events", "", ""))

    def _open_websocket(self) -> _WebSocket:
        token = self._require_token()
        factory = self._websocket_factory
        if factory is None:
            try:
                import websocket  # type: ignore[import-not-found]
            except ImportError as exc:
                raise OptionalDependencyError(
                    "WebSocket events require: pip install 'vnc-remote-control-client[websocket]'"
                ) from exc
            factory = cast(WebSocketFactory, websocket.create_connection)
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
                if isinstance(message, bytes):
                    try:
                        text = message.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise ProtocolError("WebSocket event was not valid UTF-8") from exc
                else:
                    text = message
                try:
                    value = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ProtocolError("WebSocket event was not valid JSON") from exc
                if not isinstance(value, dict):
                    raise ProtocolError("WebSocket event was not a JSON object")
                _require_fields(
                    value,
                    ("sequence", "timestamp_unix_ms", "type"),
                    "WebSocket event",
                )
                sequence = value["sequence"]
                timestamp = value["timestamp_unix_ms"]
                event_type = value["type"]
                if not isinstance(sequence, int) or isinstance(sequence, bool):
                    raise ProtocolError("WebSocket event sequence was not an integer")
                if not isinstance(timestamp, int) or isinstance(timestamp, bool):
                    raise ProtocolError(
                        "WebSocket event timestamp_unix_ms was not an integer"
                    )
                if not isinstance(event_type, str):
                    raise ProtocolError("WebSocket event type was not a string")
                payload = {
                    key: item
                    for key, item in value.items()
                    if key not in {"sequence", "timestamp_unix_ms", "type"}
                }
                yield Event(
                    sequence=sequence,
                    timestamp_unix_ms=timestamp,
                    type=event_type,
                    payload=payload,
                )
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


VncClient = VncRemoteControlClient
