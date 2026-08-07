"""Contract tests asserting living documentation stays current with master."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CURRENT_MARKDOWN_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "OPERATOR_GUIDE.md",
    ROOT / "docs" / "WEBSOCKET_EVENTS.md",
    ROOT / "docs" / "CUSTOM_DESKTOP_IMAGES.md",
    ROOT / "docs" / "CI_STATUS_BRIDGE.md",
    ROOT / "docs" / "VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md",
    ROOT / "docs" / "LIBVNCCLIENT_BINDING_DECISION.md",
    ROOT / "deploy" / "README.md",
    ROOT / "desktop" / "README.md",
    ROOT / "python" / "README.md",
    ROOT / "crates" / "controller-api" / "tests" / "FRAMEBUFFER_MEASUREMENT.md",
    ROOT / "tests" / "measurement" / "framebuffer" / "README.md",
    ROOT / "SECURITY.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CLAUDE.md",
    ROOT / "CODE_OF_CONDUCT.md",
)

LOCAL_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FULL_SHA = re.compile(r"\b[0-9a-f]{40}\b")


class DocumentationFreshnessTests(unittest.TestCase):
    """Asserts documentation files describe the current, non-historical repository state."""

    def test_documentation_index_separates_living_and_historical_material(self) -> None:
        """docs/README.md separates current living docs from historical artifacts."""
        index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        for required in (
            "## Current living documentation",
            "## Current engineering support documentation",
            "## Historical engineering artifacts",
            "point-in-time records",
            "VNC_REMOTE_CONTROL_SERVER_V01_SPEC.md",
            "VNC_REMOTE_CONTROL_SERVER_REBASE_*_2026-08-03.md",
            "openapi.json",
            "WEBSOCKET_EVENTS.md",
            "CUSTOM_DESKTOP_IMAGES.md",
            "../python/README.md",
            "../deploy/README.md",
            "../desktop/README.md",
            "../SECURITY.md",
            "../CONTRIBUTING.md",
            "../CLAUDE.md",
            "../CODE_OF_CONDUCT.md",
            "CI_STATUS_BRIDGE.md",
            "VNC_REMOTE_CONTROL_SERVER_RELEASE_POLICY_2026-08-05.md",
            "LIBVNCCLIENT_BINDING_DECISION.md",
            "../crates/controller-api/tests/FRAMEBUFFER_MEASUREMENT.md",
            "../tests/measurement/framebuffer/README.md",
        ):
            self.assertIn(required, index)

    def test_root_readme_does_not_present_old_milestones_as_current(self) -> None:
        """The root README points at current docs and drops stale milestone references."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", readme)
        self.assertIn("vnc-remote-control-demo", readme)
        self.assertIn("both permanent `CI` and `Release Gates`", readme)
        self.assertNotIn("The authoritative plan remains", readme)
        self.assertNotIn("dd3b14917ad5e239573d584238ff67ded8138203", readme)

    def test_operator_guide_covers_current_hosted_and_python_surfaces(self) -> None:
        """The operator guide documents the current hosted docs and Python client surfaces."""
        guide = (ROOT / "docs" / "OPERATOR_GUIDE.md").read_text(encoding="utf-8")
        for required in (
            "http://127.0.0.1:8080/docs",
            "http://127.0.0.1:8080/redoc",
            "http://127.0.0.1:8080/openapi.json",
            "vnc-remote-control-demo",
            "without waiting for the next heartbeat",
            "python3 -m unittest discover -s tests -p 'test_*.py' -v",
            "Release Gates",
        ):
            self.assertIn(required, guide)
        self.assertNotIn("no later than the next heartbeat wake-up", guide)

    def test_ci_bridge_describes_the_implemented_quality_surface(self) -> None:
        """The CI status bridge doc describes the implemented quality gates, not a future plan."""
        bridge = (ROOT / "docs" / "CI_STATUS_BRIDGE.md").read_text(encoding="utf-8")
        for required in (
            "## Current CI quality surface",
            "Repository quality gates",
            "Secured Debian desktop and native adapter",
            "Python, documentation, client/demo, and workflow contract tests",
            "authenticated HTTP-to-TigerVNC E2E",
            "R13 Compose integration and E2E validation",
            "Release Gates",
            "## Historical bridge-validation record",
        ):
            self.assertIn(required, bridge)
        self.assertNotIn("application implementation has not started yet", bridge)
        self.assertNotIn("As Rust, Docker, and integration-test code is added", bridge)

    def test_security_document_tracks_current_debian_native_dependency(self) -> None:
        """SECURITY.md tracks the Debian base image and libvncclient version actually in use."""
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        dockerfile = (ROOT / "controller" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("debian:13.6-slim", dockerfile)
        self.assertIn("libvncclient1", dockerfile)
        self.assertIn("0.9.15+dfsg-1+deb13u2", security)
        self.assertIn("third-party-owned", security)
        self.assertNotIn("0.9.14+dfsg-1ubuntu0.2", security)

    def test_python_and_deployment_docs_expose_current_entry_points(self) -> None:
        """The Python and deploy READMEs expose the current install and deploy entry points."""
        python_readme = (ROOT / "python" / "README.md").read_text(encoding="utf-8")
        deploy_readme = (ROOT / "deploy" / "README.md").read_text(encoding="utf-8")

        self.assertIn("vnc-remote-control-demo", python_readme)
        self.assertIn("#subdirectory=python", python_readme)
        self.assertIn("http://127.0.0.1:8080/docs", python_readme)
        pins = FULL_SHA.findall(python_readme)
        self.assertTrue(pins, "Python README must include a full-SHA reproducible install example")

        for required in (
            "--detach --wait",
            "openssl rand -hex 32",
            "http://127.0.0.1:8080/docs",
            "vnc-remote-control-demo",
            "CUSTOM_DESKTOP_IMAGES.md",
        ):
            self.assertIn(required, deploy_readme)

    def test_component_and_measurement_docs_track_current_entry_points(self) -> None:
        """Desktop and framebuffer-measurement docs track the current image digest and paths."""
        desktop_readme = (ROOT / "desktop" / "README.md").read_text(encoding="utf-8")
        desktop_dockerfile = (ROOT / "desktop" / "Dockerfile").read_text(encoding="utf-8")
        base = re.search(
            r"FROM debian:13\.6-slim@(sha256:[0-9a-f]{64})",
            desktop_dockerfile,
        )
        self.assertIsNotNone(base)
        assert base is not None
        for required in (
            "Debian 13.6 slim",
            base.group(1),
            "5901/tcp",
            "/run/secrets/vnc_password",
            "/tmp/vnc-test-app-state.json",
        ):
            self.assertIn(required, desktop_readme)

        launcher_doc = (ROOT / "tests" / "measurement" / "framebuffer" / "README.md").read_text(
            encoding="utf-8"
        )
        measurement_doc = (
            ROOT / "crates" / "controller-api" / "tests" / "FRAMEBUFFER_MEASUREMENT.md"
        ).read_text(encoding="utf-8")
        launcher = (ROOT / "tests" / "measurement" / "framebuffer" / "run.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "framebuffer_measurement",
            "measure_representative_frame_pipeline",
            "--ignored",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ):
            self.assertIn(required, measurement_doc)
            self.assertIn(required, launcher)
        self.assertIn("crates/controller-api/tests/framebuffer_measurement.rs", launcher_doc)
        self.assertIn("crates/controller-api/tests/FRAMEBUFFER_MEASUREMENT.md", launcher_doc)
        measurement_test = (
            ROOT / "crates" / "controller-api" / "tests" / "framebuffer_measurement.rs"
        )
        self.assertTrue(measurement_test.is_file())

    def test_contributor_guidance_preserves_historical_docs(self) -> None:
        """CONTRIBUTING.md and CLAUDE.md both preserve historical-artifact guidance."""
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        for document in (contributing, claude):
            self.assertIn("docs/README.md", document)
            self.assertIn("historical", document.lower())
            self.assertIn("python3 -m unittest discover -s tests -p 'test_*.py' -v", document)
        self.assertIn("Ordinary focused changes do not require", contributing)
        self.assertIn("vnc-remote-control-demo", claude)

    def test_contributing_quality_tools_match_current_workflows(self) -> None:
        """CONTRIBUTING.md lists the quality tools that the current CI workflows actually run."""
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        release_gates = (ROOT / ".github" / "workflows" / "release-gates.yml").read_text(
            encoding="utf-8"
        )
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("cargo-deny", contributing)
        self.assertIn("shellcheck", contributing)
        self.assertIn("actionlint", contributing)
        self.assertIn("docker build --check", contributing)
        self.assertNotIn("hadolint", contributing.lower())
        self.assertIn("cargo deny check", makefile)
        for required in ("shellcheck", "actionlint", "docker build --check"):
            self.assertIn(required, release_gates)

    def test_local_markdown_links_in_current_docs_resolve(self) -> None:
        """Every local markdown link in the current documentation set resolves to a real file."""
        failures: list[str] = []
        for document in CURRENT_MARKDOWN_DOCUMENTS:
            text = document.read_text(encoding="utf-8")
            for target in LOCAL_LINK.findall(text):
                target = target.split("#", 1)[0]
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = (document.parent / target).resolve()
                try:
                    resolved.relative_to(ROOT.resolve())
                except ValueError:
                    failures.append(f"{document.relative_to(ROOT)} -> {target} escapes repository")
                    continue
                if not resolved.exists():
                    failures.append(f"{document.relative_to(ROOT)} -> {target} does not exist")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
