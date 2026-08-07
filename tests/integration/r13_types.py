"""Shared exception and HTTP result types for the R13 integration suite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class Failure(RuntimeError):
    """Raised when an R13 check's expectation about the running stack fails."""


@dataclass(frozen=True)
class HttpResult:
    """One HTTP response captured by the harness."""

    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        """Decode `body` as UTF-8 JSON."""
        return json.loads(self.body.decode("utf-8"))
