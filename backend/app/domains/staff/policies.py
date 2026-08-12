from __future__ import annotations

import re
from datetime import date

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
