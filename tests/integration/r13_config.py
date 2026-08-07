"""Fixed, non-sensitive fixtures and paths shared by the R13 integration suite."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "compose.yaml"
FAILURE_DIR_VALUE = os.environ.get("R13_FAILURE_ARTIFACT_DIR", "")
FAILURE_DIR = Path(FAILURE_DIR_VALUE).resolve() if FAILURE_DIR_VALUE else None
_RUN_ID = os.environ.get("GITHUB_RUN_ID", os.getpid())
_RUN_ATTEMPT = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
RUN_SUFFIX = f"{_RUN_ID}-{_RUN_ATTEMPT}"
PROJECT = re.sub(r"[^a-z0-9-]", "", f"vrc-r13-{RUN_SUFFIX}".lower())
MISSING_PROJECT = f"{PROJECT}-missing"
API_TOKEN = f"r13-api-token-{RUN_SUFFIX}"
VNC_PASSWORD = f"r13-vnc-password-{RUN_SUFFIX}"
WRONG_VNC_PASSWORD = f"r13-wrong-vnc-password-{RUN_SUFFIX}"
SUPPORTED_TEXT = "R13 supported text 123"
UNSUPPORTED_TEXT = "R13 blocked snowman ☃"
OUTBOUND_CLIPBOARD = "R13 outbound clipboard"
INBOUND_CLIPBOARD = "R13 inbound clipboard"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CLIPBOARD_BYTES = 1024 * 1024
