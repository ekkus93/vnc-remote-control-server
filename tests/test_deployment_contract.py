"""Contract tests for the deployment artifacts (Dockerfiles, Compose files, CI)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ControllerImageContractTests(unittest.TestCase):
    """The controller image and deployment Compose files satisfy the security contract."""

    def test_controller_image_is_multistage_and_non_root(self) -> None:
        """The controller image is a non-root, multistage build with no leftover build tools."""
        dockerfile = (ROOT / "controller" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(" AS builder", dockerfile)
        self.assertIn(" AS runtime", dockerfile)
        self.assertIn("cargo build --locked --release", dockerfile)
        self.assertIn("libvncclient1", dockerfile)
        self.assertIn("USER controller:controller", dockerfile)
        self.assertIn("controller-healthcheck", dockerfile)
        runtime = dockerfile.split(" AS runtime", 1)[1]
        self.assertNotIn("COPY --from=builder /usr/local/cargo", runtime)
        self.assertNotIn("build-essential", runtime)
        self.assertNotIn("libvncserver-dev", runtime)

    def test_production_compose_does_not_publish_vnc(self) -> None:
        """The production Compose file keeps VNC internal-only and hardens the container."""
        compose = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn('expose:\n      - "5901"', compose)
        self.assertNotIn("5901:5901", compose)
        self.assertIn("internal: true", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("cap_drop:", compose)
        self.assertNotIn("docker.sock", compose)

    def test_debug_override_is_loopback_only(self) -> None:
        """The debug VNC override only ever binds the VNC port to loopback."""
        debug = (ROOT / "deploy" / "compose.debug-vnc.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("DEVELOPMENT ONLY", debug)
        self.assertIn(
            '"127.0.0.1:${VRC_DEBUG_VNC_PORT:-5901}:5901"',
            debug,
        )
        self.assertNotIn("0.0.0.0", debug)

    def test_persistence_is_opt_in_and_secret_material_is_ephemeral(self) -> None:
        """Persistence is an opt-in volume and secret material stays out of it."""
        persistence = (ROOT / "deploy" / "compose.persistence.yaml").read_text(
            encoding="utf-8"
        )
        entrypoint = (ROOT / "desktop" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("desktop_home:/home/desktop", persistence)
        self.assertIn("/tmp/vnc-runtime", entrypoint)
        self.assertNotIn('${home_dir}/.vnc/passwd', entrypoint)

    def test_ci_runs_compose_smoke(self) -> None:
        """CI runs the Compose smoke test suite."""
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("bash tests/compose/run.sh", workflow)


if __name__ == "__main__":
    unittest.main()
