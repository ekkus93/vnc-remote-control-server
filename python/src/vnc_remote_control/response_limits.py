"""Shared finite response-size limits for the typed controller client and MCP adapter."""

from __future__ import annotations

MAX_CONTROLLER_FRAMEBUFFER_BYTES = 64 * 1024 * 1024
# A PNG can be larger than its decoded RGBA framebuffer because of scanline
# filters, incompressible DEFLATE data, and PNG chunk framing. Keep one shared
# wire ceiling so the typed client and MCP image validator cannot drift apart.
MAX_SCREENSHOT_RESPONSE_BYTES = 2 * MAX_CONTROLLER_FRAMEBUFFER_BYTES
# Clipboard reads can carry up to 1 MiB of UTF-8 text and JSON escaping can
# expand control-heavy strings substantially. Eight MiB remains finite while
# safely covering every valid controller JSON response.
MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_METRICS_RESPONSE_BYTES = 1 * 1024 * 1024
MAX_ERROR_RESPONSE_BYTES = 1 * 1024 * 1024
HTTP_READ_CHUNK_BYTES = 64 * 1024
