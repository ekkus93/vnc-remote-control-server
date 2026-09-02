"""Fail-closed configuration tests for the MCP adapter."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from vnc_remote_control import mcp_config
from vnc_remote_control.mcp_config import McpConfig, McpConfigError


class McpConfigTests(unittest.TestCase):
    """Verify MCP configuration never falls back through invalid input."""

    def setUp(self) -> None:
        """Create one private token-file fixture for each test."""
        self.root = Path(tempfile.mkdtemp(prefix="vrc-mcp-config-test-"))
        self.addCleanup(shutil.rmtree, self.root)
        self.token_path = self.root / "controller-token"
        self._write_secret(b"controller-secret\n")

    def _write_secret(self, value: bytes, *, mode: int = 0o600) -> None:
        self.token_path.write_bytes(value)
        if os.name == "posix":
            self.token_path.chmod(mode)

    def _environment(self, **values: str) -> dict[str, str]:
        environment = {"VRC_MCP_CONTROLLER_TOKEN_FILE": str(self.token_path)}
        environment.update(values)
        return environment

    def test_defaults_are_bounded_loopback_and_read_only(self) -> None:
        """Verify defaults are bounded loopback and read only."""
        config = McpConfig.load(self._environment())
        self.assertEqual(config.controller_url, "http://127.0.0.1:8080")
        self.assertEqual(config.controller_timeout_seconds, 5.0)
        self.assertFalse(config.allow_mutations)
        self.assertEqual(config.max_concurrent_calls, 8)
        self.assertEqual(config.transport, "stdio")
        self.assertEqual(config.http_host, "127.0.0.1")
        self.assertEqual(config.http_port, 8765)
        self.assertTrue(config.token_set)
        self.assertNotIn("controller-secret", repr(config))
        self.assertNotIn("controller-secret", repr(config.build_client()))

    def test_secret_reader_accepts_trailing_crlf_only(self) -> None:
        """Verify secret reader accepts trailing crlf only."""
        self._write_secret(b"secret-value\r\n\n")
        config = McpConfig.load(self._environment())
        self.assertTrue(config.token_set)

    def test_raw_token_environment_value_is_never_a_token_source(self) -> None:
        """Verify raw token environment value is never a token source."""
        with self.assertRaises(McpConfigError) as context:
            McpConfig.load({"VRC_MCP_CONTROLLER_TOKEN": "raw-secret"})
        self.assertIn("VRC_MCP_CONTROLLER_TOKEN_FILE", str(context.exception))
        self.assertNotIn("raw-secret", str(context.exception))

    def test_missing_empty_and_nonregular_token_files_fail(self) -> None:
        """Verify missing empty and nonregular token files fail."""
        missing = self.root / "missing"
        cases = (
            {"VRC_MCP_CONTROLLER_TOKEN_FILE": ""},
            {"VRC_MCP_CONTROLLER_TOKEN_FILE": str(missing)},
            {"VRC_MCP_CONTROLLER_TOKEN_FILE": str(self.root)},
        )
        for environment in cases:
            with self.subTest(environment=environment):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(environment)

        self._write_secret(b"")
        with self.assertRaises(McpConfigError):
            McpConfig.load(self._environment())

    def test_secret_file_size_bound_is_exact(self) -> None:
        """Verify secret file size bound is exact."""
        self._write_secret(b"a" * mcp_config.MAX_SECRET_BYTES)
        config = McpConfig.load(self._environment())
        self.assertTrue(config.token_set)

        self._write_secret(b"a" * (mcp_config.MAX_SECRET_BYTES + 1))
        with self.assertRaises(McpConfigError) as context:
            McpConfig.load(self._environment())
        self.assertIn("size is outside the accepted bound", str(context.exception))

    def test_secret_file_rejects_invalid_utf8_nul_and_embedded_newline(self) -> None:
        """Verify secret file rejects invalid utf8 nul and embedded newline."""
        for payload in (b"\xff", b"token\x00sentinel", b"token\nvalue"):
            with self.subTest(payload=payload):
                self._write_secret(payload)
                with self.assertRaises(McpConfigError) as context:
                    McpConfig.load(self._environment())
                self.assertNotIn("sentinel", str(context.exception))
                self.assertNotIn("token\nvalue", str(context.exception))

    @unittest.skipUnless(os.name == "posix", "Unix permission policy")
    def test_secret_file_permissions_match_controller_policy(self) -> None:
        """Verify secret file permissions match controller policy."""
        for mode in (0o620, 0o602, 0o700, 0o610):
            with self.subTest(mode=oct(mode)):
                self._write_secret(b"controller-secret", mode=mode)
                with self.assertRaises(McpConfigError) as context:
                    McpConfig.load(self._environment())
                self.assertIn("permission is forbidden", str(context.exception))

        for mode in (0o600, 0o640, 0o644, 0o400):
            with self.subTest(mode=oct(mode)):
                self._write_secret(b"controller-secret", mode=mode)
                self.assertTrue(McpConfig.load(self._environment()).token_set)

    def test_controller_url_reuses_typed_client_validation(self) -> None:
        """Verify controller url reuses typed client validation."""
        invalid_urls = (
            "ftp://controller",
            "http://user:password@controller",
            "http://controller?token=x",
            "http://controller#fragment",
            "controller",
        )
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(McpConfigError) as context:
                    McpConfig.load(self._environment(VRC_MCP_CONTROLLER_URL=url))
                self.assertNotIn(url, str(context.exception))

    def test_timeout_rejects_malformed_nonfinite_and_out_of_range_values(self) -> None:
        """Verify timeout rejects malformed nonfinite and out of range values."""
        invalid_values = (
            "",
            " 5",
            "5 ",
            "nan",
            "inf",
            "-1",
            "0",
            "0.09",
            "60.1",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(
                        self._environment(VRC_MCP_CONTROLLER_TIMEOUT_SECONDS=value)
                    )

        for value in ("0.1", "5", "60", "1e-1"):
            with self.subTest(value=value):
                config = McpConfig.load(
                    self._environment(VRC_MCP_CONTROLLER_TIMEOUT_SECONDS=value)
                )
                self.assertGreaterEqual(config.controller_timeout_seconds, 0.1)
                self.assertLessEqual(config.controller_timeout_seconds, 60.0)

    def test_mutation_boolean_has_only_explicit_spellings(self) -> None:
        """Verify mutation boolean has only explicit spellings."""
        expected = {"0": False, "false": False, "1": True, "true": True}
        for value, result in expected.items():
            with self.subTest(value=value):
                config = McpConfig.load(
                    self._environment(VRC_MCP_ALLOW_MUTATIONS=value)
                )
                self.assertEqual(config.allow_mutations, result)

        invalid = ("yes", "no", "TRUE", "False", "on", "off", "", " true")
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(self._environment(VRC_MCP_ALLOW_MUTATIONS=value))

    def test_concurrency_and_port_bounds_are_strict_ascii_integers(self) -> None:
        """Verify concurrency and port bounds are strict ascii integers."""
        cases = (
            (
                "VRC_MCP_MAX_CONCURRENT_CALLS",
                ("1", "8", "64"),
                ("0", "65", "+1", " 1"),
            ),
            (
                "VRC_MCP_HTTP_PORT",
                ("1", "8765", "65535"),
                ("0", "65536", "+1", " 1"),
            ),
        )
        for name, valid, invalid in cases:
            for value in valid:
                with self.subTest(name=name, value=value):
                    McpConfig.load(self._environment(**{name: value}))
            for value in invalid:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(McpConfigError):
                        McpConfig.load(self._environment(**{name: value}))

    def test_transport_is_closed_vocabulary(self) -> None:
        """Verify transport is closed vocabulary."""
        for value in ("stdio", "streamable-http"):
            with self.subTest(value=value):
                config = McpConfig.load(self._environment(VRC_MCP_TRANSPORT=value))
                self.assertEqual(config.transport, value)
        for value in ("sse", "http", "STREAMABLE-HTTP", ""):
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(self._environment(VRC_MCP_TRANSPORT=value))

    def test_http_host_is_loopback_only(self) -> None:
        """Verify http host is loopback only."""
        for value in ("127.0.0.1", "127.42.7.9", "::1", "localhost"):
            with self.subTest(value=value):
                config = McpConfig.load(self._environment(VRC_MCP_HTTP_HOST=value))
                self.assertEqual(config.http_host, value)

        invalid = (
            "0.0.0.0",
            "::",
            "192.168.1.10",
            "example.com",
            "LOCALHOST",
            "",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(self._environment(VRC_MCP_HTTP_HOST=value))

    def test_non_unicode_environment_surrogate_fails_closed(self) -> None:
        """Verify non unicode environment surrogate fails closed."""
        environment = self._environment()
        environment["VRC_MCP_CONTROLLER_URL"] = "http://controller\udcff"
        with self.assertRaises(McpConfigError):
            McpConfig.load(environment)

    def test_config_errors_and_repr_never_expose_token_contents(self) -> None:
        """Verify config errors and repr never expose token contents."""
        sentinel = "TOP-SECRET-MCP-TOKEN"
        self._write_secret((sentinel + "\ninside").encode())
        with self.assertRaises(McpConfigError) as context:
            McpConfig.load(self._environment())
        self.assertNotIn(sentinel, str(context.exception))

        self._write_secret(sentinel.encode())
        config = McpConfig.load(self._environment())
        self.assertNotIn(sentinel, repr(config))


if __name__ == "__main__":
    unittest.main()
