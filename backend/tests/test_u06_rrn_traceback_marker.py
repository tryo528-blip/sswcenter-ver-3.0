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
