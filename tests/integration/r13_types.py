"""Shared exception and HTTP result types for the R13 integration suite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class Failure(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))
