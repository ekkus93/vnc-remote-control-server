#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import r9_worker_patch as candidate

_ORIGINAL = candidate.replace_once


def replace_once(path: Path, old: str, new: str) -> None:
    """Allow only the known duplicated mock-framebuffer insertion target."""
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    duplicated_mock_framebuffer = (
        path.name == "worker.rs"
        and count == 2
        and old.startswith(
            "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
            "            Ok(NativeFramebuffer {\n"
        )
        and old.endswith(
            "        fn framebuffer(&self) -> Result<NativeFramebuffer, NativeError> {\n"
            "            Ok(NativeFramebuffer {\n"
        )
    )
    if duplicated_mock_framebuffer:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    _ORIGINAL(path, old, new)


candidate.replace_once = replace_once
candidate.main()
