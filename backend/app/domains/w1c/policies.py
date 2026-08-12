from __future__ import annotations

import re
from datetime import date

_CERTIFICATION_INPUT = re.compile(r"^[lL]([0-9]{10})(?:-[0-9]{3})?$")


def normalize_certification_number(value: str) -> str:
    match = _CERTIFICATION_INPUT.fullmatch(value.strip())
    if match is None:
        raise ValueError("VALIDATION_ERROR")
    return f"L{match.group(1)}"


def validate_period(start_date: date, end_date: date | None) -> None:
    if end_date is not None and start_date > end_date:
        raise ValueError("VALIDATION_ERROR")
