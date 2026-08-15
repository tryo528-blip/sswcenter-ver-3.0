from __future__ import annotations

import logging
import sys

from app.core.logging import SensitiveDataFilter


def test_exception_traceback_preserves_rrn_marker() -> None:
    candidate = "900101-1" + "234567"
    try:
        raise ValueError("traceback resident_number=" + candidate)
    except ValueError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="request failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    assert SensitiveDataFilter().filter(record)
    assert record.exc_info is None
    assert candidate not in record.getMessage()
    assert "[REDACTED-RRN]" in record.getMessage()


def test_exception_traceback_redacts_pin_after_rrn_marker() -> None:
    rrn = "900101-1" + "234567"
    pin = "123" + "456"
    try:
        raise ValueError(f"PIN {rrn} -> {pin}")
    except ValueError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="request failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    assert SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert rrn not in message
    assert "123456" not in message
    assert "[REDACTED-RRN]" in message
    assert "[REDACTED]" in message


def test_ordinary_message_redacts_pin_after_rrn_marker() -> None:
    rrn = "900101-1" + "234567"
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=f"PIN {rrn} -> {'123' + '456'}",
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert rrn not in message
    assert "123456" not in message
    assert "[REDACTED-RRN]" in message
    assert "[REDACTED]" in message
