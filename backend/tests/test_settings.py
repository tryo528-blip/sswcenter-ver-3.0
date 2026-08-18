import base64
import hashlib
import os
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import (
    Environment,
    Settings,
    assert_migration_database_url,
    assert_safe_test_data_root,
    assert_safe_test_database_url,
)


def strong_secret(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


# Valid base64-encoded 32-byte keys for resident-number settings.
_VALID_B64_32_A: str = base64.b64encode(
    hashlib.sha256(b"sswcenter:resident-number-key-v1").digest()
).decode()
_VALID_B64_32_B: str = base64.b64encode(
    hashlib.sha256(b"sswcenter:resident-number-lookup-key").digest()
).decode()

_VALID_DB_PASSWORD: str = strong_secret("sswcenter:database-password")
_PRODUCTION_DATA_ROOT = (
    Path("C:/ProgramData/SSWCenter/data") if os.name == "nt" else Path("/var/lib/sswcenter/data")
)


def _prod_kwargs(**overrides: object) -> dict[str, object]:
    """Return a dict suitable for ``Settings(**kwargs)`` that passes all production checks."""
    base: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "database_url": f"postgresql+psycopg://app:{_VALID_DB_PASSWORD}@127.0.0.1/sswcenter",
        "data_root": _PRODUCTION_DATA_ROOT,
        "cookie_secure": True,
        "pin_pepper": strong_secret("sswcenter:pin-pepper"),
        "pin_lookup_key": strong_secret("sswcenter:pin-lookup-key"),
        "csrf_signing_key": strong_secret("sswcenter:csrf-signing-key"),
        "resident_number_key_v1": _VALID_B64_32_A,
        "resident_number_lookup_key": _VALID_B64_32_B,
        "transition_token_key": strong_secret("sswcenter:transition-token-key"),
    }
    base.update(overrides)
    return base


def test_test_database_guard_accepts_isolated_postgres_names() -> None:
    assert_safe_test_database_url("postgresql+psycopg://user:secret@127.0.0.1/sswcenter_test")
    assert_safe_test_database_url("postgresql+psycopg://user:secret@127.0.0.1/review_review")


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///test.db",
        "postgresql+psycopg://user:secret@127.0.0.1/sswcenter",
        "postgresql+psycopg://user:secret@127.0.0.1/production",
    ],
)
def test_test_database_guard_rejects_unsafe_targets(database_url: str) -> None:
    with pytest.raises(ValueError):
        assert_safe_test_database_url(database_url)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://postgres@127.0.0.1/postgres",
        "postgresql+psycopg://postgres@127.0.0.1/template0",
        "postgresql+psycopg://postgres@127.0.0.1/template1",
    ],
)
def test_alembic_guard_rejects_maintenance_databases(database_url: str) -> None:
    with pytest.raises(ValueError, match="maintenance"):
        assert_migration_database_url(database_url)


def test_production_refuses_development_login_bypass() -> None:
    with pytest.raises(ValidationError, match="development login bypass"):
        Settings(
            environment=Environment.PRODUCTION,
            database_url="postgresql+psycopg://app:secret@127.0.0.1/sswcenter",
            data_root=_PRODUCTION_DATA_ROOT,
            dev_login_bypass=True,
            cookie_secure=True,
            pin_pepper=SecretStr("pepper"),
            pin_lookup_key=SecretStr("lookup"),
            csrf_signing_key=SecretStr("csrf"),
        )


def test_test_data_root_guard_accepts_only_named_temporary_directory(tmp_path: object) -> None:
    from pathlib import Path

    safe_root = Path(str(tmp_path)) / "sswcenter-test-data"
    assert_safe_test_data_root(safe_root)

    with pytest.raises(ValueError, match="temporary directory"):
        assert_safe_test_data_root(Path("C:/ProgramData/SSWCenter/data"))


def test_test_environment_requires_isolated_database_and_file_root(tmp_path: object) -> None:
    from pathlib import Path

    safe_root = Path(str(tmp_path)) / "sswcenter-test-data"
    settings = Settings(
        environment=Environment.TEST,
        database_url="postgresql+psycopg://user:secret@127.0.0.1/sswcenter_test",
        data_root=safe_root,
    )
    assert settings.environment is Environment.TEST

    with pytest.raises(ValidationError, match="SSWCENTER_DATA_ROOT"):
        Settings(
            environment=Environment.TEST,
            database_url="postgresql+psycopg://user:secret@127.0.0.1/sswcenter_test",
        )


# ── production secret fail-closed tests ──────────────────────────────────────


class TestProductionSecretsFailClosed:
    """Every secret setting must survive deep validation in production."""

    def test_valid_production_passes(self) -> None:
        Settings(**_prod_kwargs())  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "setting_name",
        [
            "pin_pepper",
            "pin_lookup_key",
            "csrf_signing_key",
            "resident_number_key_v1",
            "resident_number_lookup_key",
            "transition_token_key",
        ],
    )
    def test_blank_or_whitespace_secret_rejected(self, setting_name: str) -> None:
        for bad in ("", "   ", "\t\n"):
            with pytest.raises(ValidationError, match="blank"):
                Settings(**_prod_kwargs(**{setting_name: bad}))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "setting_name",
        [
            "pin_pepper",
            "pin_lookup_key",
            "csrf_signing_key",
            "resident_number_key_v1",
            "resident_number_lookup_key",
            "transition_token_key",
        ],
    )
    def test_placeholder_secret_rejected(self, setting_name: str) -> None:
        for placeholder in ("CHANGE_ME", "changeme", "placeholder", "secret", "password"):
            with pytest.raises(ValidationError, match="placeholder"):
                Settings(**_prod_kwargs(**{setting_name: placeholder}))  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "setting_name",
        [
            "pin_pepper",
            "pin_lookup_key",
            "csrf_signing_key",
            "resident_number_key_v1",
            "resident_number_lookup_key",
            "transition_token_key",
        ],
    )
    def test_short_secret_rejected(self, setting_name: str) -> None:
        with pytest.raises(ValidationError, match="too short"):
            Settings(**_prod_kwargs(**{setting_name: "abc123"}))  # type: ignore[arg-type]

    def test_duplicate_secrets_rejected(self) -> None:
        dup = strong_secret("sswcenter:dup-test")
        with pytest.raises(ValidationError, match="reuse"):
            Settings(**_prod_kwargs(pin_pepper=dup, pin_lookup_key=dup))  # type: ignore[arg-type]

    def test_malformed_base64_resident_number_key_rejected(self) -> None:
        bad = strong_secret("sswcenter:malformed-b64")[:63] + "!"
        with pytest.raises(ValidationError, match="base64"):
            Settings(
                **_prod_kwargs(resident_number_key_v1=bad)  # type: ignore[arg-type]
            )

    def test_wrong_decoded_length_resident_number_key_rejected(self) -> None:
        wrong = base64.b64encode(
            hashlib.sha256(b"sswcenter:wrong-length-key").digest()[:24]
        ).decode()
        with pytest.raises(ValidationError, match="32 bytes"):
            Settings(
                **_prod_kwargs(resident_number_key_v1=wrong)  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "pin_pepper,expected_match",
        [
            ("x" * 20 + "FIXTURE_" + "y" * 20, "marker"),
            ("A" * 64, "diversity"),
            ("abcdefgh" * 4, "repeated"),
            ("abcdefghijklmnopqrstuvwxyz012345", "sequence"),
            ("543210zyxwvutsrqponmlkjihgfedcba", "sequence"),
        ],
    )
    def test_raw_secret_weakness_rejected(self, pin_pepper: str, expected_match: str) -> None:
        with pytest.raises(ValidationError, match=expected_match):
            Settings(**_prod_kwargs(pin_pepper=pin_pepper))  # type: ignore[arg-type]

    def test_weak_decoded_resident_key_bytes_rejected(self) -> None:
        """A 32-byte key with fewer than 8 distinct byte values must be rejected."""
        weak_bytes = bytes([i % 4 for i in range(32)])  # 4 distinct bytes
        weak_b64 = base64.b64encode(weak_bytes).decode()
        with pytest.raises(ValidationError, match=r"decoded bytes.*(?:diversity|repeated)"):
            Settings(
                **_prod_kwargs(resident_number_key_v1=weak_b64)  # type: ignore[arg-type]
            )

    def test_noncanonical_pad_bits_resident_key_rejected(self) -> None:
        """Base64 with nonzero pad bits must be rejected even if it decodes identically."""
        original = _VALID_B64_32_A
        decoded = base64.b64decode(original, validate=True)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        last_data_char = original[-2]  # character before the trailing '='
        orig_idx = alphabet.index(last_data_char)
        # Keep the high 4 data bits, flip the lowest pad bit to 1.
        new_idx = (orig_idx & ~3) | 1
        noncanonical = original[:-2] + alphabet[new_idx] + "="
        # strict b64decode ignores pad bits and still returns the same 32 bytes
        assert base64.b64decode(noncanonical, validate=True) == decoded
        with pytest.raises(ValidationError, match="canonical base64"):
            Settings(
                **_prod_kwargs(resident_number_key_v1=noncanonical)  # type: ignore[arg-type]
            )

    def test_resident_key_decoded_reuse_rejected(self) -> None:
        """Setting both resident key fields to the same base64 value must be rejected."""
        with pytest.raises(ValidationError, match="same bytes"):
            Settings(
                **_prod_kwargs(
                    resident_number_key_v1=_VALID_B64_32_A,
                    resident_number_lookup_key=_VALID_B64_32_A,
                )  # type: ignore[arg-type]
            )

    def test_absent_database_password_rejected(self) -> None:
        with pytest.raises(ValidationError, match="password"):
            Settings(
                **_prod_kwargs(
                    database_url="postgresql+psycopg://app@127.0.0.1/sswcenter",
                )  # type: ignore[arg-type]
            )

    def test_placeholder_database_password_rejected(self) -> None:
        with pytest.raises(ValidationError, match="placeholder"):
            Settings(
                **_prod_kwargs(
                    database_url="postgresql+psycopg://app:CHANGE_ME@127.0.0.1/sswcenter",
                )  # type: ignore[arg-type]
            )

    def test_short_database_password_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"too short|minimum length"):
            Settings(
                **_prod_kwargs(
                    database_url="postgresql+psycopg://app:Sh0rt1@127.0.0.1/sswcenter",
                )  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize(
        "db_password,expected_match",
        [
            ("A" * 64, "diversity"),
            ("abcdefgh" * 4, "repeated"),
            ("x" * 20 + "FIXTURE_" + "y" * 20, "marker"),
            ("abcdefghijklmnopqrstuvwxyz012345", "sequence"),
        ],
    )
    def test_database_password_weakness_rejected(
        self, db_password: str, expected_match: str
    ) -> None:
        with pytest.raises(ValidationError, match=expected_match):
            Settings(
                **_prod_kwargs(
                    database_url=f"postgresql+psycopg://app:{db_password}@127.0.0.1/sswcenter",
                )  # type: ignore[arg-type]
            )

    def test_database_password_reuse_with_pin_pepper_rejected(self) -> None:
        reused = strong_secret("sswcenter:database-password")
        with pytest.raises(ValidationError, match="reuse"):
            Settings(
                **_prod_kwargs(
                    pin_pepper=reused,
                    database_url=f"postgresql+psycopg://app:{reused}@127.0.0.1/sswcenter",
                )  # type: ignore[arg-type]
            )

    def test_sswcenter_prefixed_secret_rejected(self) -> None:
        """Secrets that match the dev-fallback pattern must be rejected."""
        with pytest.raises(ValidationError, match="placeholder"):
            Settings(
                **_prod_kwargs(
                    transition_token_key="sswcenter-dev-transition-token-key-not-for-production",
                )  # type: ignore[arg-type]
            )


# ── database URL query-parameter blocking (fail-closed) ──────────────────────


class TestQueryParameterBlocking:
    """Database URLs with any query parameters must be rejected unconditionally."""

    def test_test_guard_rejects_label_suffix(self) -> None:
        with pytest.raises(ValueError, match="query parameters"):
            assert_safe_test_database_url(
                "postgresql+psycopg://user:secret@127.0.0.1/sswcenter_test?label=_test"
            )

    def test_test_guard_rejects_host_override(self) -> None:
        with pytest.raises(ValueError, match="query parameters"):
            assert_safe_test_database_url(
                "postgresql+psycopg://user:secret@127.0.0.1/sswcenter_test?host=evil.example.com"
            )

    def test_test_guard_rejects_dbname_override(self) -> None:
        with pytest.raises(ValueError, match="query parameters"):
            assert_safe_test_database_url(
                "postgresql+psycopg://user:secret@127.0.0.1/sswcenter_test?dbname=production"
            )

    def test_production_rejects_misleading_label_suffix(self) -> None:
        with pytest.raises(ValidationError, match="query parameters"):
            Settings(
                **_prod_kwargs(
                    database_url="postgresql+psycopg://app:realpassword123@127.0.0.1/sswcenter?label=_test",
                )  # type: ignore[arg-type]
            )

    def test_production_rejects_host_override(self) -> None:
        with pytest.raises(ValidationError, match="query parameters"):
            Settings(
                **_prod_kwargs(
                    database_url="postgresql+psycopg://app:realpassword123@127.0.0.1/sswcenter?host=evil.example.com",
                )  # type: ignore[arg-type]
            )

    def test_production_rejects_dbname_override(self) -> None:
        with pytest.raises(ValidationError, match="query parameters"):
            Settings(
                **_prod_kwargs(
                    database_url="postgresql+psycopg://app:realpassword123@127.0.0.1/sswcenter?dbname=production",
                )  # type: ignore[arg-type]
            )
