"""Real PostgreSQL checks for the corrected W1 recipient contract.

The module is inert unless a dedicated disposable database is explicitly
exported. It never falls back to a developer or production URL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.core.settings import assert_safe_test_database_url

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_W1_RECIPIENT_REAL_PG") != "1",
    reason="requires the dedicated W1 recipient disposable PostgreSQL harness",
)

EXPECTED_REVISION = "20260813_0025_w1_relationship_lock_contract_correction"


def _required_url() -> str:
    value = os.getenv("SSWCENTER_W1_RECIPIENT_DATABASE_URL")
    assert value, "SSWCENTER_W1_RECIPIENT_DATABASE_URL must be explicitly exported"
    assert_safe_test_database_url(value)
    return value


def _required_owner_url() -> str:
    value = os.getenv("SSWCENTER_W1_RECIPIENT_OWNER_DATABASE_URL")
    assert value, "SSWCENTER_W1_RECIPIENT_OWNER_DATABASE_URL must be explicitly exported"
    assert_safe_test_database_url(value)
    return value


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    value = create_engine(_required_url(), pool_pre_ping=True)
    try:
        with value.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM erp.alembic_version"))
            assert revision == EXPECTED_REVISION
        yield value
    finally:
        value.dispose()


@pytest.fixture(scope="module")
def owner_engine() -> Iterator[Engine]:
    value = create_engine(_required_owner_url(), pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture(scope="module")
def seeded(engine: Engine, owner_engine: Engine) -> Iterator[dict[str, int | str]]:
    suffix = uuid4().hex
    with engine.begin() as connection:
        staff_id = connection.scalar(
            text(
                """
                INSERT INTO erp.staff (name, display_name, birth_date, sex_code)
                VALUES (:name, :name, DATE '1990-01-01', 'TEST')
                RETURNING id
                """
            ),
            {"name": f"W1 recipient PG actor {suffix}"},
        )
        assert staff_id is not None

        other_staff_id = connection.scalar(
            text(
                """
                INSERT INTO erp.staff (name, display_name, birth_date, sex_code)
                VALUES (:name, :name, DATE '1991-01-01', 'TEST')
                RETURNING id
                """
            ),
            {"name": f"W1 recipient PG other staff {suffix}"},
        )
        assert other_staff_id is not None

        account_id = connection.scalar(
            text(
                """
                INSERT INTO erp.user_account (
                    staff_id, account_code, display_name, role_code,
                    pin_hash, pin_lookup_hmac, pin_key_version
                ) VALUES (
                    :staff_id, :account_code, :display_name, 'USER',
                    :pin_hash, :pin_lookup_hmac, 1
                )
                RETURNING id
                """
            ),
            {
                "staff_id": int(staff_id),
                "account_code": f"W1-RECIPIENT-PG-{suffix}",
                "display_name": f"W1 recipient PG {suffix}",
                "pin_hash": f"unused-{suffix}",
                "pin_lookup_hmac": bytes.fromhex(suffix),
            },
        )
        assert account_id is not None

    values: dict[str, int | str] = {
        "suffix": suffix,
        "staff_id": int(staff_id),
        "other_staff_id": int(other_staff_id),
        "account_id": int(account_id),
    }
    yield values

    with owner_engine.begin() as connection:
        connection.execute(
            text(
                """
                DELETE FROM erp.staff_health_check
                 WHERE created_by_account_id = :account_id
                    OR updated_by_account_id = :account_id
                """
            ),
            values,
        )
        connection.execute(
            text(
                """
                DELETE FROM erp.staff_employment
                 WHERE created_by_account_id = :account_id
                    OR updated_by_account_id = :account_id
                """
            ),
            values,
        )
        connection.execute(
            text(
                """
                UPDATE erp.recipient
                   SET payer_guardian_id = NULL
                 WHERE created_by_account_id = :account_id
                """
            ),
            values,
        )
        connection.execute(
            text(
                """
                DELETE FROM erp.recipient_guardian
                 WHERE recipient_id IN (
                    SELECT id
                      FROM erp.recipient
                     WHERE created_by_account_id = :account_id
                 )
                """
            ),
            values,
        )
        connection.execute(
            text("DELETE FROM erp.audit_event WHERE actor_account_id = :account_id"),
            values,
        )
        connection.execute(
            text("DELETE FROM erp.recipient WHERE created_by_account_id = :account_id"),
            values,
        )
        connection.execute(
            text("DELETE FROM erp.user_account WHERE id = :account_id"),
            values,
        )
        connection.execute(
            text(
                """
                DELETE FROM erp.staff
                 WHERE id IN (:staff_id, :other_staff_id)
                """
            ),
            values,
        )


def _insert_recipient(
    engine: Engine,
    seeded: dict[str, int | str],
    *,
    label: str,
    name: str | None = None,
    birth_date: str | None = None,
    sex_code: str | None = None,
    mobile_phone: str = "010-0000-0000",
) -> int:
    with engine.begin() as connection:
        recipient_id = connection.scalar(
            text(
                """
                INSERT INTO erp.recipient (
                    name, birth_date, sex_code, mobile_phone,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    :name, CAST(:birth_date AS date), :sex_code, :mobile_phone,
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "name": name,
                "birth_date": birth_date,
                "sex_code": sex_code,
                "mobile_phone": mobile_phone,
                "account_id": int(seeded["account_id"]),
            },
        )
        assert recipient_id is not None, label
        return int(recipient_id)


def _insert_guardian(
    engine: Engine,
    seeded: dict[str, int | str],
    *,
    recipient_id: int,
) -> int:
    with engine.begin() as connection:
        guardian_id = connection.scalar(
            text(
                """
                INSERT INTO erp.recipient_guardian (
                    recipient_id, name, relationship_text, phone, address, email,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    :recipient_id, NULL, NULL, NULL, NULL, NULL,
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "recipient_id": recipient_id,
                "account_id": int(seeded["account_id"]),
            },
        )
        assert guardian_id is not None
        return int(guardian_id)


def _assert_integrity_error(
    error: IntegrityError,
    *,
    sqlstate: str,
    constraint_name: str | None = None,
    column_name: str | None = None,
) -> None:
    assert getattr(error.orig, "sqlstate", None) == sqlstate
    diagnostic = getattr(error.orig, "diag", None)
    if constraint_name is not None:
        assert getattr(diagnostic, "constraint_name", None) == constraint_name
    if column_name is not None:
        assert getattr(diagnostic, "column_name", None) == column_name


def test_recipient_mobile_is_required_while_identity_fields_are_nullable(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    recipient_id = _insert_recipient(
        engine,
        seeded,
        label="nullable identity",
        name=None,
        birth_date=None,
        sex_code=None,
        mobile_phone="010-1000-0001",
    )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT name, birth_date, sex_code, mobile_phone
                  FROM erp.recipient
                 WHERE id = :recipient_id
                """
            ),
            {"recipient_id": recipient_id},
        ).one()
    assert tuple(row) == (None, None, None, "010-1000-0001")

    with pytest.raises(IntegrityError) as missing_mobile:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient (
                        name, birth_date, sex_code,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (NULL, NULL, NULL, :account_id, :account_id)
                    """
                ),
                {"account_id": int(seeded["account_id"])},
            )
    _assert_integrity_error(
        missing_mobile.value,
        sqlstate="23502",
        column_name="mobile_phone",
    )

    for invalid_mobile in ("", "   "):
        with pytest.raises(IntegrityError) as blank_mobile:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.recipient (
                            name, birth_date, sex_code, mobile_phone,
                            created_by_account_id, updated_by_account_id
                        ) VALUES (
                            NULL, NULL, NULL, :mobile_phone,
                            :account_id, :account_id
                        )
                        """
                    ),
                    {
                        "mobile_phone": invalid_mobile,
                        "account_id": int(seeded["account_id"]),
                    },
                )
        _assert_integrity_error(
            blank_mobile.value,
            sqlstate="23514",
            constraint_name="ck_recipient_mobile_phone_required",
        )


def test_guardian_fields_are_optional_and_database_caps_each_recipient_at_two(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    recipient_id = _insert_recipient(
        engine,
        seeded,
        label="sequential guardian cap",
        mobile_phone="010-2000-0001",
    )
    first_guardian_id = _insert_guardian(engine, seeded, recipient_id=recipient_id)
    _insert_guardian(engine, seeded, recipient_id=recipient_id)

    with engine.connect() as connection:
        optional_fields = connection.execute(
            text(
                """
                SELECT name, relationship_text, phone, address, email
                  FROM erp.recipient_guardian
                 WHERE id = :guardian_id
                """
            ),
            {"guardian_id": first_guardian_id},
        ).one()
        assigned_slots = list(
            connection.execute(
                text(
                    """
                    SELECT slot_no
                      FROM erp.recipient_guardian
                     WHERE recipient_id = :recipient_id
                     ORDER BY slot_no
                    """
                ),
                {"recipient_id": recipient_id},
            ).scalars()
        )
    assert tuple(optional_fields) == (None, None, None, None, None)
    assert assigned_slots == [1, 2]

    with pytest.raises(IntegrityError) as third_guardian:
        _insert_guardian(engine, seeded, recipient_id=recipient_id)
    _assert_integrity_error(
        third_guardian.value,
        sqlstate="23514",
        constraint_name="ck_recipient_guardian_max_two",
    )

    concurrent_recipient_id = _insert_recipient(
        engine,
        seeded,
        label="concurrent guardian cap",
        mobile_phone="010-2000-0002",
    )
    _insert_guardian(engine, seeded, recipient_id=concurrent_recipient_id)
    barrier = Barrier(2)

    def insert_concurrent_third() -> tuple[int, str, str | None, str | None]:
        with engine.connect() as connection:
            transaction = connection.begin()
            backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
            assert backend_pid is not None
            barrier.wait(timeout=10)
            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.recipient_guardian (
                            recipient_id, name, relationship_text, phone, address, email,
                            created_by_account_id, updated_by_account_id
                        ) VALUES (
                            :recipient_id, NULL, NULL, NULL, NULL, NULL,
                            :account_id, :account_id
                        )
                        """
                    ),
                    {
                        "recipient_id": concurrent_recipient_id,
                        "account_id": int(seeded["account_id"]),
                    },
                )
                transaction.commit()
                return int(backend_pid), "success", None, None
            except IntegrityError as error:
                transaction.rollback()
                diagnostic = getattr(error.orig, "diag", None)
                return (
                    int(backend_pid),
                    "integrity_error",
                    getattr(error.orig, "sqlstate", None),
                    getattr(diagnostic, "constraint_name", None),
                )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=20)
            for future in [
                executor.submit(insert_concurrent_third),
                executor.submit(insert_concurrent_third),
            ]
        ]

    assert len({result[0] for result in results}) == 2
    assert [result[1] for result in results].count("success") == 1
    failures = [result for result in results if result[1] == "integrity_error"]
    assert failures == [
        (
            failures[0][0],
            "integrity_error",
            "23514",
            "ck_recipient_guardian_max_two",
        )
    ]
    with engine.connect() as connection:
        guardian_count = connection.scalar(
            text(
                """
                SELECT count(*)
                  FROM erp.recipient_guardian
                 WHERE recipient_id = :recipient_id
                """
            ),
            {"recipient_id": concurrent_recipient_id},
        )
    assert guardian_count == 2


def test_payer_null_means_self_and_guardian_must_belong_to_same_recipient(
    engine: Engine,
    owner_engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    recipient_id = _insert_recipient(
        engine,
        seeded,
        label="payer recipient",
        mobile_phone="010-3000-0001",
    )
    other_recipient_id = _insert_recipient(
        engine,
        seeded,
        label="other payer recipient",
        mobile_phone="010-3000-0002",
    )
    own_guardian_id = _insert_guardian(engine, seeded, recipient_id=recipient_id)
    other_guardian_id = _insert_guardian(
        engine,
        seeded,
        recipient_id=other_recipient_id,
    )

    with engine.begin() as connection:
        assert (
            connection.scalar(
                text("SELECT payer_guardian_id FROM erp.recipient WHERE id = :recipient_id"),
                {"recipient_id": recipient_id},
            )
            is None
        )
        connection.execute(
            text(
                """
                UPDATE erp.recipient
                   SET payer_guardian_id = :guardian_id
                 WHERE id = :recipient_id
                """
            ),
            {"guardian_id": own_guardian_id, "recipient_id": recipient_id},
        )
        assert (
            connection.scalar(
                text("SELECT payer_guardian_id FROM erp.recipient WHERE id = :recipient_id"),
                {"recipient_id": recipient_id},
            )
            == own_guardian_id
        )
        connection.execute(
            text(
                """
                UPDATE erp.recipient
                   SET payer_guardian_id = NULL
                 WHERE id = :recipient_id
                """
            ),
            {"recipient_id": recipient_id},
        )

    with pytest.raises(IntegrityError) as cross_recipient_payer:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE erp.recipient
                       SET payer_guardian_id = :guardian_id
                     WHERE id = :recipient_id
                    """
                ),
                {"guardian_id": other_guardian_id, "recipient_id": recipient_id},
            )
    _assert_integrity_error(
        cross_recipient_payer.value,
        sqlstate="23503",
        constraint_name="fk_recipient_payer_guardian_same_recipient",
    )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT payer_guardian_id FROM erp.recipient WHERE id = :recipient_id"),
                {"recipient_id": recipient_id},
            )
            is None
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE erp.recipient
                   SET payer_guardian_id = :guardian_id
                 WHERE id = :recipient_id
                """
            ),
            {"guardian_id": own_guardian_id, "recipient_id": recipient_id},
        )

    with owner_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM erp.recipient_guardian WHERE id = :guardian_id"),
            {"guardian_id": own_guardian_id},
        )
        payer_after_delete = connection.scalar(
            text("SELECT payer_guardian_id FROM erp.recipient WHERE id = :recipient_id"),
            {"recipient_id": recipient_id},
        )
    assert payer_after_delete is None


def test_health_check_employment_link_is_nullable_and_same_staff_only(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    suffix = str(seeded["suffix"])
    sequence_base = 1_000_000_000 + (int(suffix[:7], 16) % 100_000_000)
    with engine.begin() as connection:
        own_employment_id = connection.scalar(
            text(
                """
                INSERT INTO erp.staff_employment (
                    staff_id, employment_no, staff_no, staff_no_year,
                    staff_no_sequence, start_date, end_date,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    :staff_id, 1, :staff_no, 2199,
                    :sequence, DATE '2026-01-01', NULL,
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "staff_id": int(seeded["staff_id"]),
                "staff_no": f"W1-HC-OWN-{suffix}",
                "sequence": sequence_base,
                "account_id": int(seeded["account_id"]),
            },
        )
        other_employment_id = connection.scalar(
            text(
                """
                INSERT INTO erp.staff_employment (
                    staff_id, employment_no, staff_no, staff_no_year,
                    staff_no_sequence, start_date, end_date,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    :staff_id, 1, :staff_no, 2199,
                    :sequence, DATE '2026-01-01', NULL,
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "staff_id": int(seeded["other_staff_id"]),
                "staff_no": f"W1-HC-OTHER-{suffix}",
                "sequence": sequence_base + 1,
                "account_id": int(seeded["account_id"]),
            },
        )
        assert own_employment_id is not None
        assert other_employment_id is not None

        nullable_link_id = connection.scalar(
            text(
                """
                INSERT INTO erp.staff_health_check (
                    staff_id, employment_id, check_date,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    :staff_id, NULL, DATE '2026-08-12',
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "staff_id": int(seeded["staff_id"]),
                "account_id": int(seeded["account_id"]),
            },
        )
        same_staff_link_id = connection.scalar(
            text(
                """
                INSERT INTO erp.staff_health_check (
                    staff_id, employment_id, check_date,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    :staff_id, :employment_id, DATE '2026-08-13',
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "staff_id": int(seeded["staff_id"]),
                "employment_id": int(own_employment_id),
                "account_id": int(seeded["account_id"]),
            },
        )
    assert nullable_link_id is not None
    assert same_staff_link_id is not None

    with pytest.raises(IntegrityError) as mismatched_employment:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_health_check (
                        staff_id, employment_id, check_date,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :staff_id, :employment_id, DATE '2026-08-14',
                        :account_id, :account_id
                    )
                    """
                ),
                {
                    "staff_id": int(seeded["staff_id"]),
                    "employment_id": int(other_employment_id),
                    "account_id": int(seeded["account_id"]),
                },
            )
    _assert_integrity_error(
        mismatched_employment.value,
        sqlstate="23503",
        constraint_name="fk_staff_health_check_employment",
    )


def test_retired_recipient_ledgers_and_columns_are_absent(engine: Engine) -> None:
    with engine.connect() as connection:
        retired_tables = set(
            connection.execute(
                text(
                    """
                    SELECT table_name
                      FROM information_schema.tables
                     WHERE table_schema = 'erp'
                       AND table_name IN (
                           'recipient_guardian_primary_period',
                           'recipient_payer_snapshot',
                           'recipient_grade_period'
                       )
                    """
                )
            ).scalars()
        )
        retired_columns = {
            (str(row.table_name), str(row.column_name))
            for row in connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                      FROM information_schema.columns
                     WHERE table_schema = 'erp'
                       AND (
                           (table_name = 'recipient' AND column_name = 'home_phone')
                           OR (
                               table_name = 'recipient_contract'
                               AND column_name IN (
                                   'signer_name',
                                   'signer_relationship_text',
                                   'signer_phone'
                               )
                           )
                       )
                    """
                )
            )
        }

    assert retired_tables == set()
    assert retired_columns == set()


def test_checked_out_connections_have_distinct_postgresql_backend_pids(
    engine: Engine,
) -> None:
    with engine.connect() as first_connection, engine.connect() as second_connection:
        first_pid = first_connection.scalar(text("SELECT pg_backend_pid()"))
        second_pid = second_connection.scalar(text("SELECT pg_backend_pid()"))

    assert isinstance(first_pid, int)
    assert isinstance(second_pid, int)
    assert first_pid != second_pid
