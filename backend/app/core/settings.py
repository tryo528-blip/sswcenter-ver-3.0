from __future__ import annotations

import base64
import binascii
import tempfile
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _database_name(database_url: str) -> str:
    return make_url(database_url).database or ""


def assert_safe_test_database_url(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql":
        raise ValueError("Wave 0 tests require PostgreSQL; SQLite and substitutes are forbidden")
    if url.query:
        raise ValueError("database URL query parameters are not allowed")
    if not database_name.endswith(("_test", "_review")):
        raise ValueError("test database name must end with _test or _review")


def assert_migration_database_url(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql":
        raise ValueError("Alembic migrations require PostgreSQL")
    if url.query:
        raise ValueError("database URL query parameters are not allowed")
    if database_name in {"postgres", "template0", "template1"}:
        raise ValueError("Alembic migrations refuse PostgreSQL maintenance databases")


def assert_safe_test_data_root(data_root: Path) -> None:
    resolved = data_root.expanduser().resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if not resolved.is_relative_to(temporary_root):
        raise ValueError("test data root must stay inside the operating-system temporary directory")
    if not resolved.name.startswith("sswcenter-"):
        raise ValueError("test data root directory name must start with sswcenter-")


_PLACEHOLDER_SECRET_VALUES: frozenset[str] = frozenset(
    {
        "change_me",
        "changeme",
        "change-me",
        "change_me_please",
        "placeholder",
        "your-secret",
        "yoursecret",
        "your_secret",
        "example",
        "secret",
        "password",
        "insert_key_here",
        "your_key_here",
        "your-key-here",
        "insert-key-here",
        "test",
    }
)

_SECRET_SETTING_NAMES: tuple[str, ...] = (
    "pin_pepper",
    "pin_lookup_key",
    "csrf_signing_key",
    "resident_number_key_v1",
    "resident_number_lookup_key",
    "transition_token_key",
)

_MIN_SECRET_LENGTH: int = 32
_MIN_DATABASE_PASSWORD_LENGTH: int = 16

# ---------------------------------------------------------------------------
# Conservative weak-secret detection helpers (raw text + decoded bytes)
# ---------------------------------------------------------------------------

_RAW_WEAK_MARKERS: tuple[str, ...] = (
    "fixture",
    "example",
    "dummy",
    "password",
    "changeme",
    "not-for-production",
    "test-only",
    "development-only",
)


def _has_raw_weak_marker(text: str) -> bool:
    """Return True when *text* contains a known weak marker substring (case-insensitive)."""
    lowered = text.lower()
    return any(marker in lowered for marker in _RAW_WEAK_MARKERS)


def _has_low_char_diversity(text: str, distinct_threshold: int = 8) -> bool:
    """Return True when *text* uses fewer than *distinct_threshold* distinct characters."""
    return len(set(text)) < distinct_threshold


def _has_repeated_short_units(text: str, min_repeats: int = 4) -> bool:
    """Return True when *text* contains a short unit (1–8 characters) repeated at least
    *min_repeats* times consecutively (e.g. ``abababab`` or ``aaaa``)."""
    for unit_len in range(1, 9):
        if len(text) < unit_len * min_repeats:
            continue
        for i in range(len(text) - unit_len * min_repeats + 1):
            unit = text[i : i + unit_len]
            if text[i : i + unit_len * min_repeats] == unit * min_repeats:
                return True
    return False


# ---------------------------------------------------------------------------
# Sequence corpora for cyclic-slice detection
# ---------------------------------------------------------------------------

_ALPHABET_DIGITS: str = "abcdefghijklmnopqrstuvwxyz0123456789"
_DIGITS_ALPHABET: str = "0123456789abcdefghijklmnopqrstuvwxyz"
_HEX: str = "0123456789abcdef"


def _is_cyclic_slice(text: str, corpus: str) -> bool:
    """Return True when *text* (length ≥ 16) matches a cyclic slice of *corpus*.

    The check lowercases *text* and compares it against a window of the same
    length taken from *corpus* repeated enough to cover any full input length.
    This catches sequences like ``abcdefghijklmnopqrstuvwxyz012345``
    (alphabet+digits) and their reverses without rejecting ordinary random hex
    strings.
    """
    if len(text) < 16:
        return False
    lowered = text.lower()
    repeats = (len(lowered) // len(corpus)) + 2
    haystack = corpus * repeats
    for start in range(len(corpus)):
        if haystack[start : start + len(lowered)] == lowered:
            return True
    return False


def _is_full_ascending(text: str) -> bool:
    """Return True when *text* is strictly code-point ascending or a direct
    cyclic-slice match of any known sequence corpus."""
    if len(text) < 2:
        return False
    if all(ord(text[i]) < ord(text[i + 1]) for i in range(len(text) - 1)):
        return True
    for corpus in (_ALPHABET_DIGITS, _DIGITS_ALPHABET, _HEX):
        if _is_cyclic_slice(text, corpus):
            return True
    return False


def _is_full_descending(text: str) -> bool:
    """Return True when *text* is strictly code-point descending or a
    cyclic-slice match of the reversed text against any known sequence
    corpus."""
    if len(text) < 2:
        return False
    if all(ord(text[i]) > ord(text[i + 1]) for i in range(len(text) - 1)):
        return True
    for corpus in (_ALPHABET_DIGITS, _DIGITS_ALPHABET, _HEX):
        if _is_cyclic_slice(text[::-1], corpus):
            return True
    return False


def _bytes_low_diversity(data: bytes, distinct_threshold: int = 8) -> bool:
    """Return True when *data* uses fewer than *distinct_threshold* distinct byte values."""
    return len(set(data)) < distinct_threshold


def _bytes_repeated_short_units(data: bytes, min_repeats: int = 4) -> bool:
    """Return True when *data* contains a short byte unit (1–8 bytes) repeated at least
    *min_repeats* times consecutively."""
    for unit_len in range(1, 9):
        if len(data) < unit_len * min_repeats:
            continue
        for i in range(len(data) - unit_len * min_repeats + 1):
            unit = data[i : i + unit_len]
            if data[i : i + unit_len * min_repeats] == unit * min_repeats:
                return True
    return False


def _bytes_is_full_ascending(data: bytes) -> bool:
    """Return True when every byte in *data* is strictly ascending."""
    if len(data) < 2:
        return False
    return all(data[i] < data[i + 1] for i in range(len(data) - 1))


def _bytes_is_full_descending(data: bytes) -> bool:
    """Return True when every byte in *data* is strictly descending."""
    if len(data) < 2:
        return False
    return all(data[i] > data[i + 1] for i in range(len(data) - 1))


# ---------------------------------------------------------------------------
# Placeholder / resident-number-key validators
# ---------------------------------------------------------------------------


def _is_placeholder_secret(value: str) -> bool:
    """Return True when *value* is an obvious placeholder or example secret."""
    stripped = value.strip()
    if not stripped:
        return True
    if stripped.lower() in _PLACEHOLDER_SECRET_VALUES:
        return True
    if stripped.lower().startswith("sswcenter-"):
        return True
    return False


def _validate_resident_number_key(value: str, setting_name: str) -> bytes:
    """Decode strict canonical base64 → 32 bytes.  Raise ValueError for any weakness.

    Error messages deliberately omit the actual value so that secrets never
    leak into logs or exception text.
    """
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{setting_name} must be valid base64") from exc

    if len(decoded) != 32:
        raise ValueError(f"{setting_name} must decode to exactly 32 bytes")

    # Reject non-canonical encodings (e.g. unpadded or alternate alphabet).
    if base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{setting_name} must use canonical base64 encoding")

    # ---- raw base64-text weakness checks ----
    if _has_raw_weak_marker(value):
        raise ValueError(f"{setting_name} contains a weak marker")
    if _has_low_char_diversity(value):
        raise ValueError(f"{setting_name} has low character diversity")
    if _has_repeated_short_units(value):
        raise ValueError(f"{setting_name} contains repeated short units")
    if _is_full_ascending(value):
        raise ValueError(f"{setting_name} appears to be an ascending sequence")
    if _is_full_descending(value):
        raise ValueError(f"{setting_name} appears to be a descending sequence")

    # ---- decoded-bytes weakness checks ----
    if _bytes_low_diversity(decoded):
        raise ValueError(f"{setting_name} decoded bytes have low diversity")
    if _bytes_repeated_short_units(decoded):
        raise ValueError(f"{setting_name} decoded bytes contain repeated short units")
    if _bytes_is_full_ascending(decoded):
        raise ValueError(f"{setting_name} decoded bytes are an ascending sequence")
    if _bytes_is_full_descending(decoded):
        raise ValueError(f"{setting_name} decoded bytes are a descending sequence")

    return decoded


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SSWCENTER_",
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT
    app_version: str = "3.0.0-alpha"
    database_url: str | None = None
    data_root: Path | None = None

    dev_login_bypass: bool = False
    session_cookie_name: str = "sswcenter_session"
    csrf_cookie_name: str = "sswcenter_csrf"
    device_cookie_name: str = "sswcenter_device"
    csrf_header_name: str = "X-CSRF-Token"
    cookie_secure: bool = False
    session_idle_minutes: int = 30
    session_absolute_minutes: int = 480

    pin_pepper: SecretStr | None = None
    pin_lookup_key: SecretStr | None = None
    csrf_signing_key: SecretStr | None = None
    resident_number_key_v1: SecretStr | None = None
    resident_number_lookup_key: SecretStr | None = None
    resident_number_active_key_version: int = 1
    # Dedicated W1D certification-transition HMAC key (not CSRF/pin/app secret).
    transition_token_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Settings:
        if self.session_idle_minutes <= 0 or self.session_absolute_minutes <= 0:
            raise ValueError("session expiration values must be positive")
        if self.session_idle_minutes > self.session_absolute_minutes:
            raise ValueError("idle session expiration cannot exceed absolute expiration")
        if self.resident_number_active_key_version != 1:
            raise ValueError("only resident-number key version 1 is configured")

        if self.environment is Environment.TEST:
            if self.database_url is None:
                raise ValueError("test environment requires SSWCENTER_DATABASE_URL")
            assert_safe_test_database_url(self.database_url)
            if self.data_root is None:
                raise ValueError("test environment requires SSWCENTER_DATA_ROOT")
            assert_safe_test_data_root(self.data_root)

        if self.environment is Environment.PRODUCTION:
            if self.dev_login_bypass:
                raise ValueError("development login bypass is forbidden in production")
            if self.database_url is None:
                raise ValueError("production requires SSWCENTER_DATABASE_URL")
            assert_migration_database_url(self.database_url)
            url = make_url(self.database_url)
            if url.get_backend_name() != "postgresql":
                raise ValueError("production requires PostgreSQL")
            if url.query:
                raise ValueError("database URL query parameters are not allowed")
            if url.host not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("production PostgreSQL must use a loopback host")
            if self.data_root is None or not self.data_root.is_absolute():
                raise ValueError("production requires an absolute SSWCENTER_DATA_ROOT")
            if not self.cookie_secure:
                raise ValueError("production session cookies must be Secure")
            if self.pin_pepper is None or self.pin_lookup_key is None:
                raise ValueError("production PIN secrets must be configured outside the repository")
            if self.csrf_signing_key is None:
                raise ValueError("production CSRF signing key must be configured")
            if self.resident_number_key_v1 is None or self.resident_number_lookup_key is None:
                raise ValueError(
                    "production resident-number encryption and lookup keys must be configured"
                )
            if self.transition_token_key is None:
                raise ValueError(
                    "production requires SSWCENTER_TRANSITION_TOKEN_KEY "
                    "(dedicated certification-transition token HMAC key)"
                )

            # --- deep secret validation (fail-closed) ---
            secret_pairs: list[tuple[str, str]] = []
            for name in _SECRET_SETTING_NAMES:
                field = getattr(self, name)
                if field is None:  # pragma: no cover – already caught above
                    continue
                raw = field.get_secret_value()
                stripped = raw.strip()
                if not stripped or stripped != raw:
                    raise ValueError(
                        f"{name} must not be blank or have leading/trailing whitespace"
                    )
                if _is_placeholder_secret(raw):
                    raise ValueError(
                        f"{name} appears to be a placeholder or example value; "
                        "a real secret must be configured"
                    )
                if len(raw) < _MIN_SECRET_LENGTH:
                    raise ValueError(
                        f"{name} is too short ({len(raw)} characters); "
                        f"minimum length is {_MIN_SECRET_LENGTH}"
                    )
                # Conservative raw weakness checks for every application secret.
                if _has_raw_weak_marker(raw):
                    raise ValueError(f"{name} contains a weak marker")
                if _has_low_char_diversity(raw):
                    raise ValueError(f"{name} has low character diversity")
                if _has_repeated_short_units(raw):
                    raise ValueError(f"{name} contains repeated short units")
                if _is_full_ascending(raw):
                    raise ValueError(f"{name} appears to be an ascending sequence")
                if _is_full_descending(raw):
                    raise ValueError(f"{name} appears to be a descending sequence")
                secret_pairs.append((name, raw))

            # Resident-number keys must be strict base64 → 32 bytes, with
            # decoded reuse rejected.
            rn_decoded: dict[str, bytes] = {}
            for rn_name in ("resident_number_key_v1", "resident_number_lookup_key"):
                rn_field = getattr(self, rn_name)
                if rn_field is not None:
                    rn_bytes = _validate_resident_number_key(rn_field.get_secret_value(), rn_name)
                    rn_decoded[rn_name] = rn_bytes
            if len(rn_decoded) == 2:
                if rn_decoded["resident_number_key_v1"] == rn_decoded["resident_number_lookup_key"]:
                    raise ValueError(
                        "resident_number_key_v1 and resident_number_lookup_key "
                        "must not decode to the same bytes"
                    )

            # Reject exact secret reuse across independent settings.
            seen: dict[str, str] = {}
            for name, raw in secret_pairs:
                if raw in seen:
                    raise ValueError(
                        f"{name} must not reuse the same value as {seen[raw]}; "
                        "every independent secret setting requires a unique value"
                    )
                seen[raw] = name

            # Production database password must survive conservative checks.
            db_password = url.password
            if db_password is None or db_password.strip() == "":
                raise ValueError("production database URL must include a non-empty password")
            if db_password != db_password.strip():
                raise ValueError(
                    "production database password must not have leading or trailing whitespace"
                )
            if _is_placeholder_secret(db_password):
                raise ValueError(
                    "production database password appears to be a placeholder; "
                    "a real password must be configured"
                )
            if len(db_password) < _MIN_DATABASE_PASSWORD_LENGTH:
                raise ValueError(
                    f"production database password is too short "
                    f"({len(db_password)} characters); "
                    f"minimum length is {_MIN_DATABASE_PASSWORD_LENGTH}"
                )
            if _has_raw_weak_marker(db_password):
                raise ValueError("production database password contains a weak marker")
            if _has_low_char_diversity(db_password):
                raise ValueError("production database password has low character diversity")
            if _has_repeated_short_units(db_password):
                raise ValueError("production database password contains repeated short units")
            if _is_full_ascending(db_password):
                raise ValueError("production database password appears to be an ascending sequence")
            if _is_full_descending(db_password):
                raise ValueError("production database password appears to be a descending sequence")
            if db_password in seen:
                raise ValueError(
                    "production database password must not reuse an application secret value"
                )

        # Non-production: explicit fallback when unset (tests/dev only).
        if self.environment is not Environment.PRODUCTION and self.transition_token_key is None:
            self.transition_token_key = SecretStr(
                "sswcenter-dev-transition-token-key-not-for-production"
            )

        return self

    @property
    def database_name(self) -> str | None:
        if self.database_url is None:
            return None
        return _database_name(self.database_url)

    def secret_value(self, name: str) -> str:
        configured = {
            "pin_pepper": self.pin_pepper,
            "pin_lookup_key": self.pin_lookup_key,
            "csrf_signing_key": self.csrf_signing_key,
        }[name]
        if configured is not None:
            return configured.get_secret_value()
        if self.environment is Environment.PRODUCTION:
            raise RuntimeError(f"{name} is required in production")
        return f"sswcenter-{self.environment.value}-{name}-only"


@lru_cache
def get_settings() -> Settings:
    return Settings()
