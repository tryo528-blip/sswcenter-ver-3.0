from __future__ import annotations

import gzip
import json
import logging
import sys

import pytest

from app.core.logging import DailySizeCompressedFileHandler, SensitiveDataFilter
from app.domains.staff.policies import normalize_sensitive_text


def test_sensitive_values_are_redacted() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="pin=123456 session_token=secret csrf_token=csrf-secret",
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert "123456" not in message
    assert "secret" not in message
    assert message.count("[REDACTED]") == 3


def test_structured_sensitive_values_are_redacted() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=json.dumps(
            {
                "pin": "123456",
                "session_token": "session-secret",
                "csrf_token": "csrf-secret",
            },
            separators=(",", ":"),
        ),
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert "123456" not in message
    assert "session-secret" not in message
    assert "csrf-secret" not in message
    assert message.count("[REDACTED]") == 3


def test_structured_numeric_pin_values_are_redacted() -> None:
    for message in ("{'pin': 123456}", '{"current_pin": 654321}'):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )

        assert SensitiveDataFilter().filter(record)
        redacted = record.getMessage()
        assert "123456" not in redacted
        assert "654321" not in redacted
        assert "[REDACTED]" in redacted


@pytest.mark.parametrize(
    ("message", "secret"),
    (
        ("PIN 123456", "123456"),
        ("PIN -> 123456", "123456"),
        ("PIN => 123456", "123456"),
        ("PIN: 123456", "123456"),
        ("PIN|123456", "123456"),
        ("current_pin 654321", "654321"),
        ("PIN 12345", "12345"),
        ("PIN 1234567", "1234567"),
    ),
)
def test_unstructured_pin_separators_are_redacted(message: str, secret: str) -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record)
    redacted = record.getMessage()
    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_pin_word_without_a_numeric_value_is_not_over_redacted() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="PIN rejected by policy",
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record)
    assert record.getMessage() == "PIN rejected by policy"


def test_staff_identity_and_current_pin_are_redacted() -> None:
    resident_number = "90010" + "1-1" + "2345" + "67"
    raw_resident_number = resident_number.replace("-", "")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            f'{{"resident_number":"{resident_number}",'
            '"resident_number_ciphertext":"cipher-material",'
            '"current_pin":"654321"} '
            f"raw={raw_resident_number}"
        ),
        args=(),
        exc_info=None,
    )

    assert SensitiveDataFilter().filter(record)
    message = record.getMessage()
    assert resident_number not in message
    assert raw_resident_number not in message
    assert "cipher-material" not in message
    assert "654321" not in message
    assert "[REDACTED]" in message
    assert "[REDACTED-RRN]" in message


def test_rrn_redaction_covers_all_seventh_digits_and_boundaries() -> None:
    for seventh_digit in "0123456789":
        raw = "900101" + seventh_digit + "234567"
        hyphenated = "900101-" + seventh_digit + "234567"
        for value in (raw, hyphenated, "prefix_" + raw + "_suffix", "prefix-" + hyphenated):
            redacted = normalize_sensitive_text(value)
            assert raw not in redacted
            assert hyphenated not in redacted
            assert "[REDACTED-RRN]" in redacted


def test_normal_epoch_milliseconds_are_not_redacted_without_rrn_context() -> None:
    epoch = "".join(("172", "0000000000"))
    assert normalize_sensitive_text("created_at=" + epoch) == "created_at=" + epoch
    assert "[REDACTED-RRN]" in normalize_sensitive_text("raw=" + epoch)
    assert "[REDACTED-RRN]" in normalize_sensitive_text('resident_number="' + epoch + '"')


def test_rrn_like_epoch_in_created_at_context_is_not_left_plaintext() -> None:
    candidate = "400101" + "1234567"
    redacted = normalize_sensitive_text("created_at " + candidate)
    if candidate in redacted or "[REDACTED-RRN]" not in redacted:
        raise AssertionError("B3_RRN_EPOCH_CONTEXT_REDACTION_MISSING")


def test_exception_traceback_is_redacted_before_file_formatting() -> None:
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
            exc_info=__import__("sys").exc_info(),
        )

    assert SensitiveDataFilter().filter(record)
    assert record.exc_info is None
    assert candidate not in record.getMessage()
    assert "[REDACTED-RRN]" in record.getMessage()


def test_exception_traceback_pin_is_redacted_before_file_formatting() -> None:
    try:
        raise ValueError("PIN -> 123456")
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
    assert "123456" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_exception_traceback_quoted_pin_values_are_redacted() -> None:
    try:
        raise ValueError('{"current_pin":"654321", "pin": 123456}')
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
    assert "654321" not in message
    assert "123456" not in message
    assert message.count("[REDACTED]") >= 2


def test_log_handler_rotates_compresses_and_preserves_redaction(tmp_path: object) -> None:
    from pathlib import Path

    log_path = Path(str(tmp_path)) / "app.log"
    handler = DailySizeCompressedFileHandler(
        log_path,
        retention_days=30,
        max_bytes=80,
        total_cap_bytes=1024,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(SensitiveDataFilter())
    logger = logging.getLogger("test.wave0.rotation")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        logger.info("pin=123456 %s", "x" * 50)
        logger.info("session_token=top-secret %s", "y" * 50)
    finally:
        handler.close()
        logger.handlers = []

    archives = list(log_path.parent.glob("app.log.*.gz"))
    assert archives
    archived_text = "\n".join(gzip.open(path, "rt", encoding="utf-8").read() for path in archives)
    active_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    combined = archived_text + active_text
    assert "123456" not in combined
    assert "top-secret" not in combined
    assert "[REDACTED]" in combined
