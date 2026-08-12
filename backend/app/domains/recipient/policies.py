from __future__ import annotations

from datetime import date


def clean_required_text(value: str, *, code: str = "VALIDATION_ERROR") -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(code)
    return cleaned


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def validate_period(start_date: date, end_date: date | None) -> None:
    if end_date is not None and start_date > end_date:
        raise ValueError("VALIDATION_ERROR")
