from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "crates" / "controller-api" / "src" / "http" / "router.rs"
DOCS_UI = ROOT / "crates" / "controller-api" / "src" / "http" / "docs_ui.rs"
README = ROOT / "README.md"


class HostedDocsContractTests(unittest.TestCase):
    def test_router_exposes_public_documentation_routes(self) -> None:
        source = ROUTER.read_text(encoding="utf-8")
        for route in (
            '.route("/openapi.json", get(openapi_json))',
            '.route("/docs", get(swagger_ui))',
            '.route("/docs/swagger-initializer.js", get(swagger_initializer))',
            '.route("/redoc", get(redoc))',
        ):
            self.assertIn(route, source)
        protected = source.split("let protected = Router::new()", 1)[1].split("Router::new()", 1)[0]
        for route in ("/openapi.json", "/docs", "/redoc"):
            self.assertNotIn(route, protected)

    def test_ui_versions_and_privacy_controls_are_pinned(self) -> None:
        source = DOCS_UI.read_text(encoding="utf-8")
        self.assertIn("swagger-ui-dist@5.32.11", source)
        self.assertIn("redoc/v2.5.3/bundles/redoc.standalone.js", source)
        self.assertNotIn("/latest/", source)
        self.assertIn('url: "/openapi.json"', source)
        self.assertIn("persistAuthorization: false", source)
        self.assertIn("validatorUrl: null", source)
        self.assertIn("connect-src 'self'", source)
        self.assertIn("frame-ancestors 'none'", source)
        self.assertIn('include_str!("../../../../docs/openapi.json")', source)

    def test_readme_documents_hosted_reference_and_external_assets(self) -> None:
        readme = README.read_text(encoding="utf-8")
        for required in (
            "http://127.0.0.1:8080/docs",
            "http://127.0.0.1:8080/redoc",
            "http://127.0.0.1:8080/openapi.json",
            "swagger-ui-dist` 5.32.11",
            "ReDoc 2.5.3",
            "does not persist authorization",
            "external validator disabled",
        ):
            self.assertIn(required, readme)


if __name__ == "__main__":
    unittest.main()
