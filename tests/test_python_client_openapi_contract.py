"""Contract test tying the Python client's source to the OpenAPI document."""

import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "docs" / "openapi.json"
CLIENT = ROOT / "python" / "src" / "vnc_remote_control" / "client.py"


class PythonClientOpenApiContractTests(unittest.TestCase):
    """Every documented endpoint is present in the client, and auth stays header-only."""

    def test_every_openapi_path_is_represented_in_client_source(self) -> None:
        """Every OpenAPI path string literally appears in the client's source."""
        document: dict[str, Any] = json.loads(OPENAPI.read_text(encoding="utf-8"))
        client = CLIENT.read_text(encoding="utf-8")
        paths = set(document["paths"])
        self.assertGreater(len(paths), 0)
        for path in sorted(paths):
            self.assertIn(path, client, f"Python client is missing OpenAPI path {path}")

    def test_websocket_endpoint_remains_header_authenticated(self) -> None:
        """The WebSocket client sends the token via header, never a URL query param."""
        client = CLIENT.read_text(encoding="utf-8")
        self.assertIn('header=[f"Authorization: Bearer {token}"]', client)
        events_url = (
            "return urlunsplit((scheme, parsed.netloc, "
            "f\"{parsed.path.rstrip('/')}/v1/events\""
        )
        self.assertIn(events_url, client)
        self.assertNotIn("access_token=", client)
        self.assertNotIn("token=", client)


if __name__ == "__main__":
    unittest.main()
