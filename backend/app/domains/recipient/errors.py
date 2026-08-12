from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecipientDomainError(Exception):
    code: str
    status_code: int
    message: str
    field_errors: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.code)
