"""Contract tests for the hosted API documentation (Swagger UI, ReDoc, OpenAPI JSON)."""

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "crates" / "controller-api" / "src" / "http" / "router.rs"
DOCS_UI = ROOT / "crates" / "controller-api" / "src" / "http" / "docs_ui.rs"
THIRD_PARTY = ROOT / "crates" / "controller-api" / "third_party"
MANIFEST = THIRD_PARTY / "MANIFEST.md"
CONTROLLER_DOCKERFILE = ROOT / "controller" / "Dockerfile"
README = ROOT / "README.md"

# Exact vendored asset digests. Mirrors crates/controller-api/third_party/MANIFEST.md;
# update both together when the pinned version changes.
_VENDORED_ASSET_DIGESTS = {
    "swagger-ui/5.32.11/swagger-ui.css": (
        "ca238f7d7c2cf4480c1e77a9c3b9da915ab216e96ffd354e69076560c650c6de"
    ),
    "swagger-ui/5.32.11/swagger-ui-bundle.js": (
        "fcb81e2c79e7e3b76ddb9bd7fc791552045040fde05c19d3f98f9213e7f7724d"
    ),
    "swagger-ui/5.32.11/swagger-ui-standalone-preset.js": (
        "ea327dbf3a0a047290f6b9cf4e4b86a63bb8534b43d416c6c07ee8d14269d9ff"
    ),
    "redoc/2.5.3/redoc.standalone.js": (
        "1320f442151c57c447d3b70c7ffc6c4f86d08464020fe34c8cc5d3164e9944f0"
    ),
}


class HostedDocsContractTests(unittest.TestCase):
    """The controller hosts unauthenticated docs routes with pinned, privacy-hardened UI assets."""

    def test_router_exposes_public_documentation_routes(self) -> None:
        """The router exposes the docs routes publicly, outside the protected router."""
        source = ROUTER.read_text(encoding="utf-8")
        for route in (
            '.route("/openapi.json", get(openapi_json))',
            '.route("/docs", get(swagger_ui))',
            '.route("/docs/swagger-initializer.js", get(swagger_initializer))',
            '.route("/docs/assets/swagger-ui.css", get(swagger_ui_css_asset))',
            '"/docs/assets/swagger-ui-bundle.js"',
            '"/docs/assets/swagger-ui-standalone-preset.js"',
            '.route("/redoc", get(redoc))',
            '"/redoc/assets/redoc.standalone.js"',
        ):
            self.assertIn(route, source)
        protected = source.split("let protected = Router::new()", 1)[1].split("Router::new()", 1)[0]
        for route in ("/openapi.json", "/docs", "/redoc"):
            self.assertNotIn(route, protected)

    def test_ui_versions_and_privacy_controls_are_pinned(self) -> None:
        """The docs UI pins asset versions and disables auth persistence and validator lookup."""
        source = DOCS_UI.read_text(encoding="utf-8")
        self.assertIn("swagger-ui/5.32.11/swagger-ui.css", source)
        self.assertIn("swagger-ui/5.32.11/swagger-ui-bundle.js", source)
        self.assertIn("swagger-ui/5.32.11/swagger-ui-standalone-preset.js", source)
        self.assertIn("redoc/2.5.3/redoc.standalone.js", source)
        self.assertNotIn("/latest/", source)
        self.assertIn('url: "/openapi.json"', source)
        self.assertIn("persistAuthorization: false", source)
        self.assertIn("validatorUrl: null", source)
        self.assertIn("connect-src 'self'", source)
        self.assertIn("frame-ancestors 'none'", source)
        self.assertIn('include_str!("../../../../docs/openapi.json")', source)

    def test_no_external_runtime_asset_url_is_referenced(self) -> None:
        """No `/docs` or `/redoc` markup/CSP references a third-party runtime script/style URL."""
        source = DOCS_UI.read_text(encoding="utf-8")
        html = source.split("const SWAGGER_UI_HTML", 1)[1].split("const REDOC_HTML", 1)
        swagger_html, remainder = html[0], html[1]
        redoc_html = remainder.split("const SWAGGER_CSP", 1)[0]
        # The CSP constants themselves are the enforced runtime policy; a
        # neighboring comment may still *discuss* the excluded upstream
        # origin (see MANIFEST.md), so only the constant values are checked.
        swagger_csp = source.split('const SWAGGER_CSP: &str = "', 1)[1].split('";', 1)[0]
        redoc_csp = source.split('const REDOC_CSP: &str = "', 1)[1].split('";', 1)[0]
        for markup, label in (
            (swagger_html, "swagger html"),
            (redoc_html, "redoc html"),
            (swagger_csp, "swagger CSP"),
            (redoc_csp, "redoc CSP"),
        ):
            self.assertNotIn("http://", markup, f"{label} referenced an external URL")
            self.assertNotIn("https://", markup, f"{label} referenced an external URL")
        self.assertIn("script-src 'self'", swagger_csp)
        self.assertIn("script-src 'self'", redoc_csp)

    def test_vendored_assets_match_pinned_digests_and_carry_license_notices(self) -> None:
        """Every vendored asset matches its pinned SHA-256 digest and ships a license notice."""
        for relative_path, expected_digest in _VENDORED_ASSET_DIGESTS.items():
            asset = THIRD_PARTY / relative_path
            self.assertTrue(asset.is_file(), f"missing vendored asset: {relative_path}")
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()
            self.assertEqual(digest, expected_digest, f"{relative_path} digest drifted")
        self.assertTrue((THIRD_PARTY / "swagger-ui" / "5.32.11" / "LICENSE").is_file())
        self.assertTrue((THIRD_PARTY / "redoc" / "2.5.3" / "LICENSE").is_file())
        manifest = MANIFEST.read_text(encoding="utf-8")
        for expected_digest in _VENDORED_ASSET_DIGESTS.values():
            self.assertIn(expected_digest, manifest)

    def test_controller_builder_includes_the_embedded_openapi_source(self) -> None:
        """The Dockerfile copies the OpenAPI source before it is embedded at build time."""
        dockerfile = CONTROLLER_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("COPY docs/openapi.json ./docs/openapi.json", dockerfile)
        copy_index = dockerfile.index("COPY docs/openapi.json ./docs/openapi.json")
        build_command = "RUN cargo build --locked --release --package controller-api"
        build_index = dockerfile.index(build_command)
        self.assertLess(copy_index, build_index)
        # The vendored UI assets ship under crates/controller-api/third_party, which the
        # existing `COPY crates ./crates` step already carries into the build context.
        self.assertIn("COPY crates ./crates", dockerfile)
        crates_copy_index = dockerfile.index("COPY crates ./crates")
        self.assertLess(crates_copy_index, build_index)

    def test_readme_documents_hosted_reference_and_local_assets(self) -> None:
        """The README documents the hosted reference endpoints and locally-served UI assets."""
        readme = README.read_text(encoding="utf-8")
        for required in (
            "http://127.0.0.1:8080/docs",
            "http://127.0.0.1:8080/redoc",
            "http://127.0.0.1:8080/openapi.json",
            "swagger-ui-dist` 5.32.11",
            "ReDoc 2.5.3",
            "does not persist authorization",
            "external validator disabled",
            "served locally",
        ):
            self.assertIn(required, readme)
        self.assertNotIn("CDN URLs", readme)


if __name__ == "__main__":
    unittest.main()
