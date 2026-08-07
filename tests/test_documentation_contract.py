from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "docs" / "openapi.json"
OPERATOR_GUIDE_PATH = ROOT / "docs" / "OPERATOR_GUIDE.md"
CUSTOM_DESKTOP_PATH = ROOT / "docs" / "CUSTOM_DESKTOP_IMAGES.md"
WEBSOCKET_PATH = ROOT / "docs" / "WEBSOCKET_EVENTS.md"
README_PATH = ROOT / "README.md"
DEPLOY_README_PATH = ROOT / "deploy" / "README.md"
PYTHON_README_PATH = ROOT / "python" / "README.md"
COMPOSE_PATH = ROOT / "deploy" / "compose.yaml"
DESKTOP_DOCKERFILE_PATH = ROOT / "desktop" / "Dockerfile"
HTTP_SOURCE_PATH = ROOT / "crates" / "controller-api" / "src" / "http" / "router.rs"
HTTP_E2E_PATH = ROOT / "tests" / "http-e2e" / "run.sh"

EXPECTED_OPERATIONS = {
    "/health/live": {"get"},
    "/health/ready": {"get"},
    "/v1/status": {"get"},
    "/v1/display": {"get"},
    "/v1/screenshot.png": {"get"},
    "/v1/events": {"get"},
    "/v1/metrics": {"get"},
    "/v1/pointer/move": {"post"},
    "/v1/pointer/button": {"post"},
    "/v1/pointer/click": {"post"},
    "/v1/pointer/double-click": {"post"},
    "/v1/pointer/scroll": {"post"},
    "/v1/keyboard/key": {"post"},
    "/v1/keyboard/chord": {"post"},
    "/v1/keyboard/text": {"post"},
    "/v1/clipboard": {"get", "put"},
    "/v1/connection/reconnect": {"post"},
}

EXPECTED_EVENT_TYPES = {
    "snapshot",
    "connection_state",
    "framebuffer_revision",
    "framebuffer_invalidated",
    "clipboard_revision",
    "overload",
    "protocol_error",
}

EXPECTED_ERROR_CODES = {
    "unauthorized",
    "not_ready",
    "framebuffer_unavailable",
    "shutting_down",
    "payload_too_large",
    "invalid_json",
    "internal_error",
    "websocket_capacity",
    "event_sequence_exhausted",
    "screenshot_busy",
    "screenshot_timeout",
    "invalid_coordinate",
    "invalid_rectangle",
    "chord_too_long",
    "text_too_large",
    "clipboard_too_large",
    "unsupported_text",
    "invalid_clipboard",
    "scroll_too_large",
    "command_queue_full",
    "worker_unavailable",
    "clipboard_unavailable",
    "command_timeout",
    "reconnect_rate_limited",
    "invalid_request",
    "desktop_operation_failed",
}


def load_openapi() -> dict[str, Any]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def resolve_schema(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    prefix = "#/components/schemas/"
    if not reference.startswith(prefix):
        raise AssertionError(f"unsupported schema reference: {reference}")
    return document["components"]["schemas"][reference.removeprefix(prefix)]


def validate_example(document: dict[str, Any], schema: dict[str, Any], value: Any, path: str) -> None:
    schema = resolve_schema(document, schema)
    if "oneOf" in schema:
        failures = []
        for candidate in schema["oneOf"]:
            try:
                validate_example(document, candidate, value, path)
                return
            except AssertionError as error:
                failures.append(str(error))
        raise AssertionError(f"{path} matched no oneOf branch: {failures}")

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        if value is None and "null" in expected_type:
            return
        expected_type = next(item for item in expected_type if item != "null")

    if expected_type == "object":
        if not isinstance(value, dict):
            raise AssertionError(f"{path} must be an object")
        required = set(schema.get("required", []))
        missing = required - value.keys()
        if missing:
            raise AssertionError(f"{path} is missing {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = value.keys() - properties.keys()
            if extra:
                raise AssertionError(f"{path} has extra fields {sorted(extra)}")
        for name, child in value.items():
            if name in properties:
                validate_example(document, properties[name], child, f"{path}.{name}")
        return
    if expected_type == "array":
        if not isinstance(value, list):
            raise AssertionError(f"{path} must be an array")
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if minimum is not None and len(value) < minimum:
            raise AssertionError(f"{path} is shorter than minItems")
        if maximum is not None and len(value) > maximum:
            raise AssertionError(f"{path} is longer than maxItems")
        for index, child in enumerate(value):
            validate_example(document, schema["items"], child, f"{path}[{index}]")
        return
    if expected_type == "string":
        if not isinstance(value, str):
            raise AssertionError(f"{path} must be a string")
        if "enum" in schema and value not in schema["enum"]:
            raise AssertionError(f"{path} is outside enum")
        if "const" in schema and value != schema["const"]:
            raise AssertionError(f"{path} differs from const")
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise AssertionError(f"{path} is shorter than minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise AssertionError(f"{path} is longer than maxLength")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise AssertionError(f"{path} does not match pattern")
        return
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise AssertionError(f"{path} must be an integer")
        if "enum" in schema and value not in schema["enum"]:
            raise AssertionError(f"{path} is outside enum")
        if "const" in schema and value != schema["const"]:
            raise AssertionError(f"{path} differs from const")
        if "minimum" in schema and value < schema["minimum"]:
            raise AssertionError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise AssertionError(f"{path} is above maximum")
        return
    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise AssertionError(f"{path} must be a boolean")
        if "const" in schema and value != schema["const"]:
            raise AssertionError(f"{path} differs from const")
        return
    if expected_type == "null":
        if value is not None:
            raise AssertionError(f"{path} must be null")
        return
    if expected_type is None:
        return
    raise AssertionError(f"{path} uses unsupported test schema type {expected_type}")


class DocumentationContractTests(unittest.TestCase):
    def test_openapi_operations_match_the_router_exactly(self) -> None:
        document = load_openapi()
        self.assertEqual(document["openapi"], "3.1.0")
        self.assertEqual(document["info"]["version"], "0.1.0")
        documented = {
            path: {method for method in item if method in {"get", "post", "put", "delete", "patch"}}
            for path, item in document["paths"].items()
        }
        self.assertEqual(documented, EXPECTED_OPERATIONS)

        source = HTTP_SOURCE_PATH.read_text(encoding="utf-8")
        router = source.split("pub fn router(state: HttpState) -> Router {", 1)[1]
        for path, methods in EXPECTED_OPERATIONS.items():
            source_path = path.removeprefix("/v1") if path.startswith("/v1/") else path
            self.assertIn(f'.route("{source_path}"', router)
            route_line = next(line for line in router.splitlines() if f'.route("{source_path}"' in line)
            for method in methods:
                self.assertRegex(route_line, rf"\b{method}\(")

    def test_openapi_auth_responses_and_examples_are_complete(self) -> None:
        document = load_openapi()
        self.assertEqual(document["components"]["securitySchemes"]["bearerAuth"]["scheme"], "bearer")
        operation_ids: set[str] = set()
        for path, methods in document["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "put"}:
                    continue
                operation_id = operation["operationId"]
                self.assertNotIn(operation_id, operation_ids)
                operation_ids.add(operation_id)
                self.assertIn("responses", operation)
                self.assertTrue(operation["responses"])
                if path.startswith("/v1/"):
                    self.assertEqual(operation["security"], [{"bearerAuth": []}])
                    self.assertIn("401", operation["responses"])
                else:
                    self.assertEqual(operation["security"], [])
                request_body = operation.get("requestBody")
                if request_body is not None:
                    media = request_body["content"]["application/json"]
                    self.assertIn("example", media, f"missing request example for {method} {path}")
                    validate_example(document, media["schema"], media["example"], f"{method} {path}")

        command_schema = document["components"]["schemas"]["CommandAcceptedResponse"]
        self.assertEqual(command_schema["properties"]["status"]["const"], "accepted")
        for path in EXPECTED_OPERATIONS:
            for method, operation in document["paths"][path].items():
                if method in {"post", "put"} and path != "/health/ready":
                    self.assertIn("202", operation["responses"])
                    self.assertIn("acknowledg", operation["responses"]["202"]["description"].lower())

        error_codes = set(document["components"]["schemas"]["ErrorBody"]["properties"]["code"]["enum"])
        self.assertEqual(error_codes, EXPECTED_ERROR_CODES)
        self.assertEqual(document["components"]["schemas"]["PointerScrollRequest"]["properties"]["delta_x"]["enum"], [0])

    def test_readme_and_operator_guide_cover_every_r15_operator_topic(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        guide = OPERATOR_GUIDE_PATH.read_text(encoding="utf-8")
        for required in (
            "```mermaid",
            "docs/OPERATOR_GUIDE.md",
            "docs/openapi.json",
            "docs/WEBSOCKET_EVENTS.md",
            "docs/CUSTOM_DESKTOP_IMAGES.md",
            "127.0.0.1:8080",
            "Product boundary",
            "request_id_exhausted",
            "request-id-exhausted",
        ):
            self.assertIn(required, readme)

        for heading in (
            "## 1. Product and trust boundary",
            "## 3. Prerequisites",
            "## 4. Generate and protect secrets",
            "## 5. Build and start",
            "## 6. API binding and TLS",
            "## 9. Authenticated HTTP examples",
            "## 10. Asynchronous command semantics",
            "## 11. WebSocket events",
            "## 12. Shutdown behavior",
            "## 13. Recovery behavior",
            "## 14. Resource limits and tuning",
            "### Desktop does not start",
            "### VNC authentication fails",
            "### Controller cannot connect",
            "### Liveness passes but readiness does not",
        ):
            self.assertIn(heading, guide)

        for required in (
            "printable ASCII `U+0020` through `U+007E`",
            "inbound bytes must form valid UTF-8",
            "compose.persistence.yaml",
            "compose.debug-vnc.yaml",
            "VRC_SCREENSHOT_MAX_CONCURRENT",
            "VRC_WEBSOCKET_MAX_CLIENTS",
            "VRC_COMMAND_CAPACITY",
            "docker compose -f deploy/compose.yaml down",
        ):
            self.assertIn(required, guide)

        self.assertNotIn("Authorization: Bearer replace", guide)
        self.assertNotRegex(guide, r"Authorization: Bearer [A-Za-z0-9]{16,}")

    def test_custom_desktop_guide_matches_deployment_contract(self) -> None:
        custom = CUSTOM_DESKTOP_PATH.read_text(encoding="utf-8")
        readme = README_PATH.read_text(encoding="utf-8")
        deploy_readme = DEPLOY_README_PATH.read_text(encoding="utf-8")
        python_readme = PYTHON_README_PATH.read_text(encoding="utf-8")
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        desktop_dockerfile = DESKTOP_DOCKERFILE_PATH.read_text(encoding="utf-8")

        for required in (
            "Python VncClient(base_url, api_token)",
            "VRC_VNC_HOST",
            "VRC_VNC_PORT",
            "VRC_VNC_PASSWORD_FILE",
            "VRC_VNC_HOST=desktop",
            "VRC_VNC_PORT=5901",
            "desktop_control",
            "vnc-remote-control-desktop:base",
            "my-firefox-discord-desktop:local",
            "build: null",
            "API token",
            "VNC password",
            "arbitrary external VNC servers",
            "Do not weaken healthchecks",
        ):
            self.assertIn(required, custom)

        self.assertIn("VRC_VNC_HOST: desktop", compose)
        self.assertIn('VRC_VNC_PORT: "5901"', compose)
        self.assertIn("VRC_VNC_PASSWORD_FILE: /run/secrets/vnc_password", compose)
        self.assertIn("desktop_control:\n    internal: true", compose)
        self.assertIn("USER desktop:desktop", desktop_dockerfile)
        self.assertIn("EXPOSE 5901", desktop_dockerfile)
        self.assertIn("desktop-entrypoint", desktop_dockerfile)
        self.assertIn("desktop-healthcheck", desktop_dockerfile)

        for linked_document in (readme, deploy_readme, python_readme):
            self.assertIn("CUSTOM_DESKTOP_IMAGES.md", linked_document)

        self.assertIn('VncClient("http://127.0.0.1:8080", api_token)', python_readme)
        self.assertIn("does not need the desktop service name", python_readme)
        self.assertIn("VRC_VNC_HOST=desktop", deploy_readme)
        self.assertIn("VRC_VNC_PORT=5901", deploy_readme)

    def test_websocket_document_matches_serialized_event_contract(self) -> None:
        document = WEBSOCKET_PATH.read_text(encoding="utf-8")
        source = (ROOT / "crates" / "controller-api" / "src" / "events.rs").read_text(encoding="utf-8")
        for event_type in EXPECTED_EVENT_TYPES:
            self.assertIn(f"`{event_type}`", document)
        self.assertIn("code: 1013", source)
        self.assertIn("code: 1011", source)
        self.assertIn("code: 1001", source)
        self.assertIn("`1013`", document)
        self.assertIn("`1011`", document)
        self.assertIn("`1001`", document)
        self.assertIn("client event buffer exhausted", document)
        self.assertIn("event sequence exhausted", document)
        self.assertIn("client heartbeat timeout", document)
        self.assertIn("without waiting for the next heartbeat", document)
        self.assertIn("sequence_exhausted_notify", source)
        self.assertIn("notify_waiters", source)
        for forbidden in ("clipboard_text", "typed_text", "pixels", "password", "token"):
            self.assertIn(forbidden, source)
        self.assertIn("never contain typed text", document)

    def test_documented_curl_examples_are_exercised_by_real_http_e2e(self) -> None:
        script = HTTP_E2E_PATH.read_text(encoding="utf-8")
        self.assertIn("R15_DOCUMENTED_CURL_EXAMPLES", script)
        for path in (
            "/health/live",
            "/v1/status",
            "/v1/display",
            "/v1/screenshot.png",
            "/v1/pointer/move",
            "/v1/keyboard/text",
            "/v1/clipboard",
            "/v1/connection/reconnect",
        ):
            self.assertIn(path, script)
        self.assertIn("curl --fail-with-body", script)
        self.assertIn("Authorization: Bearer ${api_token}", script)


if __name__ == "__main__":
    unittest.main()
