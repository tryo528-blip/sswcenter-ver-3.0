from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

_PHONE_SEPARATORS = re.compile(r"[\s\-.()]")
_DOMESTIC_PHONE = re.compile(r"^0\d{8,10}$")
_INTERNATIONAL_PHONE = re.compile(r"^(?:\+82|0082)([1-9]\d{7,9})$")
_RESIDENT_NUMBER = re.compile(r"^(?:[0-9]{13}|[0-9]{6}-[0-9]{7})$")
_ROLE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,49}$")
_CENTURY_BY_SEVENTH_DIGIT = {
    "9": 1800,
    "0": 1800,
    "1": 1900,
    "2": 1900,
    "5": 1900,
    "6": 1900,
    "3": 2000,
    "4": 2000,
    "7": 2000,
    "8": 2000,
}


def _is_resident_number_candidate(value: str) -> bool:
    normalized = value.replace("-", "")
    century = _CENTURY_BY_SEVENTH_DIGIT.get(normalized[6])
    if century is None:
        return False
    try:
        date(
            century + int(normalized[:2]),
            int(normalized[2:4]),
            int(normalized[4:6]),
        )
    except ValueError:
        return False
    return True


def normalize_sensitive_text(value: str) -> str:
    """Redact likely resident numbers without treating normal epoch values as RRN."""

    candidate_pattern = re.compile(r"(?<!\d)(?:\d{6}-\d{7}|\d{13})(?!\d)")

    def replace(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if _is_resident_number_candidate(candidate):
            return "[REDACTED-RRN]"
        if "-" not in candidate:
            try:
                numeric = int(candidate)
            except ValueError:
                numeric = -1
            surrounding = value[max(0, match.start() - 32) : min(len(value), match.end() + 32)]
            labelled = any(
                marker in surrounding.lower()
                for marker in (
                    "resident_number",
                    "resident number",
                    "rrn",
                    "주민등록",
                    "주민번호",
                )
            )
            timestamp_context = any(
                marker in surrounding.lower()
                for marker in (
                    "created_at",
                    "updated_at",
                    "timestamp",
                    "epoch",
                    "millis",
                    "milliseconds",
                )
            )
            if (
                946_684_800_000 <= numeric <= 4_102_444_800_000
                and timestamp_context
                and not labelled
            ):
                return candidate
        return "[REDACTED-RRN]"

    return candidate_pattern.sub(replace, value)


def normalize_phone_number(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    original = value.strip()
    if not original:
        return None, None

    compact = _PHONE_SEPARATORS.sub("", original)
    international = _INTERNATIONAL_PHONE.fullmatch(compact)
    if international is not None:
        return original, f"+82{international.group(1)}"
    if _DOMESTIC_PHONE.fullmatch(compact) is not None:
        return original, f"+82{compact[1:]}"
    raise ValueError("W1A_SEM_PHONE_INVALID")


def validate_resident_number(
    *,
    rrn_input: str,
    expected_birth_date: date,
    expected_sex_code: str,
) -> str:
    if _RESIDENT_NUMBER.fullmatch(rrn_input) is None:
        raise ValueError("W1A_SEM_RRN_INVALID")

    normalized = rrn_input.replace("-", "")
    century = _CENTURY_BY_SEVENTH_DIGIT.get(normalized[6])
    if century is None:
        raise ValueError("W1A_SEM_RRN_INVALID")

    year = century + int(normalized[:2])
    try:
        encoded_birth_date = date(year, int(normalized[2:4]), int(normalized[4:6]))
    except ValueError as exc:
        raise ValueError("W1A_SEM_RRN_INVALID") from exc

    encoded_sex = "MALE" if int(normalized[6]) % 2 else "FEMALE"
    if encoded_birth_date != expected_birth_date or encoded_sex != expected_sex_code:
        raise ValueError("W1A_SEM_RRN_INVALID")
    return normalized


def mask_resident_number(birth_date: date) -> str:
    return f"{birth_date:%y%m%d}-*******"


def normalize_role_code(value: str) -> str:
    normalized = value.strip().upper()
    if _ROLE_CODE.fullmatch(normalized) is None:
        raise ValueError("W1A_SEM_ROLE_CODE_INVALID")
    return normalized


def _shift_calendar_year(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # February 29 has no direct counterpart in a non-leap year.
        return date(value.year + years, 2, 28)


def health_check_entry_window(employment_start: date) -> tuple[date, date]:
    """Return the inclusive new-hire/re-entry health-check acceptance window."""

    return (
        _shift_calendar_year(employment_start, -1) + timedelta(days=1),
        _shift_calendar_year(employment_start, 1),
    )


def is_entry_health_check_date(employment_start: date, check_date: date) -> bool:
    window_start, window_end = health_check_entry_window(employment_start)
    return window_start <= check_date <= window_end


def has_entry_health_check(employment_start: date, check_dates: Iterable[date]) -> bool:
    return any(is_entry_health_check_date(employment_start, value) for value in check_dates)


def requires_annual_health_check(
    *,
    employment_start: date,
    employment_end: date | None,
    calendar_year: int,
) -> bool:
    """Return whether an existing employee owes the calendar-year submission."""

    if employment_start.year >= calendar_year:
        return False
    if employment_end is not None and employment_end <= date(calendar_year, 12, 30):
        return False
    return True


def is_annual_health_check_date(calendar_year: int, check_date: date) -> bool:
    return date(calendar_year, 1, 1) <= check_date <= date(calendar_year, 12, 31)


def has_annual_health_check(calendar_year: int, check_dates: Iterable[date]) -> bool:
    return any(is_annual_health_check_date(calendar_year, value) for value in check_dates)
