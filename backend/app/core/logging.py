from __future__ import annotations

import gzip
import logging
import logging.handlers
import os
import re
import shutil
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.core.settings import Settings
from app.domains.staff.policies import normalize_sensitive_text

MAX_LOG_BYTES = 50 * 1024 * 1024
TOTAL_LOG_CAP_BYTES = 2 * 1024 * 1024 * 1024


class SensitiveDataFilter(logging.Filter):
    _patterns = (
        (
            re.compile(
                r"""(?ix)
                (["'](?:
                    resident_number(?:_ciphertext|_nonce|_lookup_hmac|_key_version)?
                    |current_pin
                )["']\s*:\s*)
                (["'])(.*?)(\2)
                """
            ),
            r"\1\2[REDACTED]\2",
        ),
        (
            re.compile(
                r"(?ix)\b(pin|current_pin)\b"
                r"(\s*(?:->|=>|[-–—=:|/])\s*|\s+)"
                r"([0-9][^\s,;]*)"
            ),
            r"\1\2[REDACTED]",
        ),
        (
            re.compile(
                r"(?i)\b("
                r"resident_number(?:_ciphertext|_nonce|_lookup_hmac|_key_version)?"
                r"|current_pin"
                r")\b(\s*[=:]\s*)([^\s,;]+)"
            ),
            r"\1\2[REDACTED]",
        ),
        (
            re.compile(
                r"""(?ix)
                (["'](?:pin|password|session(?:_token)?|csrf(?:_token)?)["']\s*:\s*)
                (["'])(.*?)(\2)
                """
            ),
            r"\1\2[REDACTED]\2",
        ),
        (
            re.compile(
                r"(?i)\b(pin|password|session(?:_token)?|csrf(?:_token)?)\b"
                r"(\s*[=:]\s*)([^\s,;]+)"
            ),
            r"\1\2[REDACTED]",
        ),
        (
            re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/-]+)"),
            r"\1 [REDACTED]",
        ),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern, replacement in self._patterns:
            message = pattern.sub(replacement, message)
        record.msg = normalize_sensitive_text(message)
        record.args = ()
        if record.exc_info:
            exception_text = "".join(traceback.format_exception(*record.exc_info))
            record.exc_info = None
            record.msg = f"{record.msg}\n{normalize_sensitive_text(exception_text)}"
            record.exc_text = None
        if record.stack_info:
            record.stack_info = normalize_sensitive_text(record.stack_info)
        return True


class DailySizeCompressedFileHandler(logging.handlers.BaseRotatingHandler):
    def __init__(
        self,
        filename: Path,
        *,
        retention_days: int,
        max_bytes: int = MAX_LOG_BYTES,
        total_cap_bytes: int = TOTAL_LOG_CAP_BYTES,
    ) -> None:
        filename.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(filename, mode="a", encoding="utf-8", delay=True)
        self.retention_days = retention_days
        self.max_bytes = max_bytes
        self.total_cap_bytes = total_cap_bytes
        self._opened_date = date.today()

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802
        if date.today() != self._opened_date:
            return True
        if self.max_bytes <= 0:
            return False
        if self.stream is None:
            self.stream = self._open()
        message = f"{self.format(record)}{self.terminator}".encode()
        self.stream.seek(0, os.SEEK_END)
        return self.stream.tell() + len(message) >= self.max_bytes

    def doRollover(self) -> None:  # noqa: N802
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        source = Path(self.baseFilename)
        if source.exists() and source.stat().st_size > 0:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            archive = source.with_name(f"{source.name}.{stamp}.gz")
            with source.open("rb") as input_file, gzip.open(archive, "wb") as output_file:
                shutil.copyfileobj(input_file, output_file)
            source.unlink()
        self._opened_date = date.today()
        self._prune_archives()

    def _prune_archives(self) -> None:
        log_directory = Path(self.baseFilename).parent
        archives = sorted(
            log_directory.glob(f"{Path(self.baseFilename).name}.*.gz"),
            key=lambda path: path.stat().st_mtime,
        )
        cutoff = datetime.now(UTC) - timedelta(days=self.retention_days)
        for archive in archives:
            modified = datetime.fromtimestamp(archive.stat().st_mtime, UTC)
            if modified < cutoff:
                archive.unlink()
        capped_files = sorted(
            (path for path in log_directory.iterdir() if path.is_file()),
            key=lambda path: path.stat().st_mtime,
        )
        total_size = sum(path.stat().st_size for path in capped_files)
        for old_file in capped_files:
            if total_size <= self.total_cap_bytes:
                break
            if old_file.resolve() == Path(self.baseFilename).resolve():
                continue
            file_size = old_file.stat().st_size
            old_file.unlink()
            total_size -= file_size


def _handler(path: Path, retention_days: int, level: int = logging.INFO) -> logging.Handler:
    handler = DailySizeCompressedFileHandler(path, retention_days=retention_days)
    handler.setLevel(level)
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    return handler


def configure_logging(settings: Settings) -> None:
    if settings.data_root is None:
        return
    log_root = settings.data_root / "logs"
    app_handler = _handler(log_root / "app.log", retention_days=30)
    error_handler = _handler(log_root / "error.log", retention_days=90, level=logging.ERROR)
    access_handler = _handler(log_root / "access.log", retention_days=30)
    install_handler = _handler(log_root / "install-update.log", retention_days=180)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [app_handler, error_handler]
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = [access_handler]
    access_logger.propagate = False
    install_logger = logging.getLogger("sswcenter.install")
    install_logger.handlers = [install_handler, error_handler]
    install_logger.propagate = False
