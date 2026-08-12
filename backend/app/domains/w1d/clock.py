"""Injectable UTC clock for W1D transition token expiry (RED seam)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

_ClockFn = Callable[[], datetime]
_override: _ClockFn | None = None


def now_utc() -> datetime:
    if _override is not None:
        return _override()
    return datetime.now(UTC)


def set_clock(fn: _ClockFn | None) -> None:
    """Compatibility: set a zero-arg clock function, or None to restore real UTC."""
    global _override
    _override = fn


def set_now_utc(value: datetime | None) -> None:
    """Approved pg_07 seam: pin now_utc() to an aware datetime, or None to restore.

    A concrete aware datetime must make now_utc() return that same value.
    None restores the real UTC clock.
    """
    global _override
    if value is None:
        _override = None
        return
    if not isinstance(value, datetime):
        raise TypeError("set_now_utc requires datetime | None")
    if value.tzinfo is None:
        raise ValueError("set_now_utc requires an aware datetime")
    fixed = value

    def _fixed() -> datetime:
        return fixed

    _override = _fixed
