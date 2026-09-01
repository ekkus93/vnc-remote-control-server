# WebSocket Event Contract

Endpoint: `GET /v1/events`

The endpoint requires the same bearer authentication as every other `/v1/*` route. The bearer token is supplied in the HTTP upgrade request:

```http
Authorization: Bearer <token-from-secret-file>
```

The controller returns `101 Switching Protocols` for an accepted upgrade. Missing or invalid authentication returns the standard JSON `401 unauthorized` response without a WebSocket accept header.

## Envelope

Every server text frame is one JSON object:

```json
{
  "sequence": 1,
  "timestamp_unix_ms": 1785949200000,
  "type": "snapshot"
}
```

- `sequence` is monotonically increasing within one controller process.
- `timestamp_unix_ms` is the observation time in Unix milliseconds.
- `type` selects the event-specific fields.
- Event payloads never contain typed text, clipboard contents, bearer tokens, VNC passwords, or framebuffer bytes.

Sequences are process-local. A controller restart creates a new sequence domain. Clients must not compare sequence numbers across process restarts.

## Initial `snapshot`

The first text frame after a successful upgrade is always a `snapshot`:

```json
{
  "sequence": 1,
  "timestamp_unix_ms": 1785949200000,
  "type": "snapshot",
  "state": "connected",
  "framebuffer_revision": 42,
  "clipboard_revision": 7,
  "reconnect_attempts": 0,
  "last_failure": null,
  "rejected_commands": 0,
  "dropped_events": 0,
  "fatal_exit": false
}
```

`state` is one of:

- `starting`
- `connecting`
- `connected`
- `degraded`
- `reconnecting`
- `disconnected`
- `authentication_failed`
- `stopped`

`last_failure`, when present, is one of:

- `authentication`
- `configuration`
- `request`
- `capacity`
- `unavailable`
- `rate_limited`
- `transport`
- `timeout`
- `protocol`
- `native`

## Event types

### `connection_state`

```json
{
  "sequence": 2,
  "timestamp_unix_ms": 1785949200100,
  "type": "connection_state",
  "state": "reconnecting"
}
```

### `framebuffer_revision`

Published only after a coherent framebuffer commit:

```json
{
  "sequence": 3,
  "timestamp_unix_ms": 1785949200200,
  "type": "framebuffer_revision",
  "revision": 43
}
```

### `framebuffer_invalidated`

Published when the prior frame can no longer be served as current, including disconnect and reconnect transitions:

```json
{
  "sequence": 4,
  "timestamp_unix_ms": 1785949200300,
  "type": "framebuffer_invalidated"
}
```

### `clipboard_revision`

Reports only the revision, never clipboard content:

```json
{
  "sequence": 5,
  "timestamp_unix_ms": 1785949200400,
  "type": "clipboard_revision",
  "revision": 8
}
```

### `overload`

Reports a bounded-capacity rejection or drop without including the rejected command:

```json
{
  "sequence": 6,
  "timestamp_unix_ms": 1785949200500,
  "type": "overload"
}
```

### `protocol_error`

Reports a VNC protocol failure without native payload data:

```json
{
  "sequence": 7,
  "timestamp_unix_ms": 1785949200600,
  "type": "protocol_error"
}
```

## Buffering and recovery

Each authenticated client receives a bounded event buffer. The server does not provide replay from an arbitrary sequence number. A client that reconnects receives a fresh snapshot and then future events.

Clients should treat events as invalidation and state-change signals:

- after `framebuffer_revision`, request `/v1/screenshot.png` conditionally with the previous ETag;
- after `framebuffer_invalidated`, stop treating the previous screenshot as current;
- after reconnecting the WebSocket, replace local state with the new snapshot.

## Client-to-server traffic bounds

`/v1/events` is server-to-client for application data. The controller configures both the inbound WebSocket frame limit and inbound message limit to **4096 bytes**. Ping, Pong, and Close control frames remain supported. Client Text or Binary application data is never accepted as an event command: ordinary application data is rejected with close code `1003`, while application data above the 4096-byte bound is rejected with `1009`. Rejected Text/Binary data does not refresh heartbeat activity.

These small limits bound memory spent on traffic the event protocol does not use while remaining comfortably above the WebSocket control-frame payload maximum.

## Heartbeats and close behavior

The server sends WebSocket ping frames at the configured interval. Clients must respond to ping frames and remain active within the configured idle timeout.

The controller uses these close codes and reasons:

| Code | Reason | Meaning |
|---:|---|---|
| `1001` | `client heartbeat timeout` | Client remained inactive beyond the bounded idle timeout. |
| `1001` | `event source stopped` | Worker event source stopped during controller shutdown or failure. |
| `1003` | `client application data is not supported` | Client sent Text/Binary application data to the server-to-client event stream. |
| `1009` | `client application message is too large` | Client application data exceeded the 4096-byte inbound bound. |
| `1011` | `event sequence exhausted` | The process-local sequence cannot allocate another unique event ID. |
| `1013` | `client event buffer exhausted` | Client was too slow and lagged beyond its bounded event buffer. |

A client-capacity rejection occurs before upgrade and returns HTTP `503` with error code `websocket_capacity`. If the initial snapshot cannot allocate a unique sequence, the controller releases the client permit and returns HTTP `503` with error code `event_sequence_exhausted` before upgrade. When sequence exhaustion becomes terminal after upgrade, an internal notification wakes all established event service loops promptly; each closes with `1011` and exact reason `event sequence exhausted` without waiting for the next heartbeat. This notification is internal and does not introduce a new public event type or payload. The sequence never wraps, resets, saturates, or reuses an earlier value.

## Interactive example

```bash
API_TOKEN="$(cat deploy/secrets/api_token.txt)"
websocat \
  -H="Authorization: Bearer $API_TOKEN" \
  ws://127.0.0.1:8080/v1/events
```

Do not put the bearer token in the URL query string.
