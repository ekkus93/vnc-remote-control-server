"""Post-final-polish native-boundary regression contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM_HEADER = ROOT / "crates/libvnc-adapter/native/vnc_shim.h"
SHIM_SOURCE = ROOT / "crates/libvnc-adapter/native/vnc_shim.c"
ADAPTER = ROOT / "crates/libvnc-adapter/src/lib.rs"
WORKER_HELPERS = ROOT / "crates/controller-api/src/worker/helpers.rs"


class PostFinalPolishNativeContractTests(unittest.TestCase):
    """Protect structured protocol-initialization failure classification."""

    def test_protocol_initialization_has_distinct_numeric_status(self) -> None:
        """The shim reports a distinct status for `InitialiseRFBConnection()` failure."""
        header = SHIM_HEADER.read_text(encoding="utf-8")
        source = SHIM_SOURCE.read_text(encoding="utf-8")
        self.assertIn("VRC_STATUS_PROTOCOL_INITIALIZATION_FAILED = 9", header)

        start = source.index("if (!InitialiseRFBConnection")
        block = source[start : source.index("/* Request a host-independent", start)]
        self.assertIn("return VRC_STATUS_PROTOCOL_INITIALIZATION_FAILED;", block)
        self.assertNotIn("return VRC_STATUS_NATIVE_FAILURE;", block)

    def test_rust_adapter_maps_status_to_payload_free_variant(self) -> None:
        """The Rust adapter maps the distinct status to a payload-free error variant."""
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("const STATUS_PROTOCOL_INITIALIZATION_FAILED: c_int = 9;", adapter)
        self.assertIn("ProtocolInitializationFailed", adapter)
        self.assertIn(
            "STATUS_PROTOCOL_INITIALIZATION_FAILED => NativeError::ProtocolInitializationFailed",
            adapter,
        )

    def test_worker_lifecycle_does_not_match_native_error_message_text(self) -> None:
        """Worker lifecycle classification never parses a native error message string."""
        helpers = WORKER_HELPERS.read_text(encoding="utf-8")
        self.assertIn("NativeError::ProtocolInitializationFailed", helpers)
        self.assertNotIn('message.contains("protocol initialization failed")', helpers)
        self.assertNotIn("message.contains(", helpers)


if __name__ == "__main__":
    unittest.main()
