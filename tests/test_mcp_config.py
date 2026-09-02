"""Fail-closed configuration tests for the MCP adapter."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vnc_remote_control import mcp_config
from vnc_remote_control.mcp_config import McpConfig, McpConfigError


class McpConfigTests(unittest.TestCase):
    """Verify MCP configuration never falls back through invalid input."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
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

    def test_secret_reader_trims_only_trailing_crlf(self) -> None:
        self._write_secret(b"secret-value\r\n\n")
        self.assertEqual(mcp_config._read_secret_file(self.token_path), "secret-value")

    def test_raw_token_environment_value_is_never_a_token_source(self) -> None:
        with self.assertRaises(McpConfigError) as context:
            McpConfig.load({"VRC_MCP_CONTROLLER_TOKEN": "raw-secret"})
        self.assertIn("VRC_MCP_CONTROLLER_TOKEN_FILE", str(context.exception))
        self.assertNotIn("raw-secret", str(context.exception))

    def test_missing_empty_and_nonregular_token_files_fail(self) -> None:
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
        self._write_secret(b"a" * mcp_config.MAX_SECRET_BYTES)
        config = McpConfig.load(self._environment())
        self.assertTrue(config.token_set)

        self._write_secret(b"a" * (mcp_config.MAX_SECRET_BYTES + 1))
        with self.assertRaises(McpConfigError) as context:
            McpConfig.load(self._environment())
        self.assertIn("size is outside the accepted bound", str(context.exception))

    def test_secret_file_rejects_invalid_utf8_nul_and_embedded_newline(self) -> None:
        for payload in (b"\xff", b"secret\x00sentinel", b"secret\nvalue"):
            with self.subTest(payload=payload):
                self._write_secret(payload)
                with self.assertRaises(McpConfigError) as context:
                    McpConfig.load(self._environment())
                error = str(context.exception)
                self.assertNotIn("sentinel", error)
                self.assertNotIn("secret", error.replace(str(self.token_path), ""))

    @unittest.skipUnless(os.name == "posix", "Unix permission policy")
    def test_secret_file_permissions_match_controller_policy(self) -> None:
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
        invalid_values = ("", " 5", "5 ", "nan", "inf", "-1", "0", "0.09", "60.1")
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
        expected = {"0": False, "false": False, "1": True, "true": True}
        for value, result in expected.items():
            with self.subTest(value=value):
                config = McpConfig.load(
                    self._environment(VRC_MCP_ALLOW_MUTATIONS=value)
                )
                self.assertEqual(config.allow_mutations, result)

        for value in ("yes", "no", "TRUE", "False", "on", "off", "", " true"):
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(self._environment(VRC_MCP_ALLOW_MUTATIONS=value))

    def test_concurrency_and_port_bounds_are_strict_ascii_integers(self) -> None:
        for name, valid, invalid in (
            ("VRC_MCP_MAX_CONCURRENT_CALLS", ("1", "8", "64"), ("0", "65", "+1", " 1")),
            ("VRC_MCP_HTTP_PORT", ("1", "8765", "65535"), ("0", "65536", "+1", " 1")),
        ):
            for value in valid:
                with self.subTest(name=name, value=value):
                    McpConfig.load(self._environment(**{name: value}))
            for value in invalid:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(McpConfigError):
                        McpConfig.load(self._environment(**{name: value}))

    def test_transport_is_closed_vocabulary(self) -> None:
        for value in ("stdio", "streamable-http"):
            with self.subTest(value=value):
                self.assertEqual(
                    McpConfig.load(self._environment(VRC_MCP_TRANSPORT=value)).transport,
                    value,
                )
        for value in ("sse", "http", "STREAMABLE-HTTP", ""):
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(self._environment(VRC_MCP_TRANSPORT=value))

    def test_http_host_is_loopback_only(self) -> None:
        for value in ("127.0.0.1", "127.42.7.9", "::1", "localhost"):
            with self.subTest(value=value):
                config = McpConfig.load(self._environment(VRC_MCP_HTTP_HOST=value))
                self.assertEqual(config.http_host, value)

        for value in ("0.0.0.0", "::", "192.168.1.10", "example.com", "LOCALHOST", ""):
            with self.subTest(value=value):
                with self.assertRaises(McpConfigError):
                    McpConfig.load(self._environment(VRC_MCP_HTTP_HOST=value))

    def test_non_unicode_environment_surrogate_fails_closed(self) -> None:
        environment = self._environment()
        environment["VRC_MCP_CONTROLLER_URL"] = "http://controller\udcff"
        with self.assertRaises(McpConfigError):
            McpConfig.load(environment)

    def test_config_errors_and_repr_never_expose_token_contents(self) -> None:
        sentinel = "TOP-SECRET-MCP-TOKEN"
        self._write_secret((sentinel + "\ninside").encode())
        with self.assertRaises(McpConfigError) as context:
            McpConfig.load(self._environment())
        self.assertNotIn(sentinel, str(context.exception))

        self._write_secret(sentinel.encode())
        config = McpConfig.load(self._environment())
        self.assertNotIn(sentinel, repr(config))

    def test_opened_file_is_revalidated_before_read(self) -> None:
        real_fstat = os.fstat
        unsafe_stat = os.stat_result((stat_mode := 0o100620, 0, 0, 0, 0, 0, 10, 0, 0, 0))
        with mock.patch("vnc_remote_control.mcp_config.os.fstat", return_value=unsafe_stat):
            with self.assertRaises(McpConfigError) as context:
                McpConfig.load(self._environment())
        self.assertIn("permission is forbidden", str(context.exception))
        self.assertTrue(callable(real_fstat))
        self.assertEqual(stat_mode & 0o022, 0o020)


if __name__ == "__main__":
    unittest.main()
