"""W2 Phase 1 RED: SERVICE-PLAN-NOTICE PostgreSQL live cases.

No engine or connection is created during import/collection. Live execution is
explicitly gated by SSWCENTER_W2_SVC_PLAN_NOTICE_REAL_PG=1 and uses direct DB
contracts only; API, UI, service, work-card engine, monthly schedule, and
staff-replacement behavior are out of scope.

§6 RED 테스트 범위 — postgres 항목 1~19번 각각에 대응하는 독립 테스트 함수.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

W2_PREV_HEAD = "20260808_0017_recipient_guardian_email"
W2_REVISION = "20260809_0018_w2_service_plan_notice"
SVC_PLAN_TABLE = "erp.recipient_service_plan_notice"
CONTRACT_TABLE = "erp.recipient_contract"
CERT_PERIOD_TABLE = "erp.recipient_certification_period"


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _product_absent(marker: str) -> NoReturn:
    _fail("W2_PRODUCT_ABSENT: " + marker)


def _compact_sql(value: str) -> str:
    return re.sub(r"\s+", "", value.lower()).replace("::text", "")


def _without_sql_comments(value: str) -> str:
    without_line_comments = re.sub(r"--[^\r\n]*", "", value)
    return re.sub(r"/\*.*?\*/", "", without_line_comments, flags=re.DOTALL)


@pytest.fixture(scope="session")
def database_engine() -> Engine:
    if os.environ.get("SSWCENTER_W2_SVC_PLAN_NOTICE_REAL_PG") != "1":
        pytest.skip("requires the isolated W2 service-plan-notice PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W2_HARNESS_DATABASE_URL_MISSING")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def database_connection(database_engine: Engine):
    connection = database_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@dataclass(frozen=True)
class W2Fixture:
    account_id: int
    recipient_id: int
    recipient_id_2: int
    contract_id: int
    contract_id_endless: int
    contract_service_type_id: int
    contract_endless_service_type_id: int
    cert_period_id: int
    cert_period_id_2: int


def _require_catalog(connection: Connection) -> None:
    revision = connection.execute(
        text("SELECT version_num FROM erp.alembic_version")
    ).scalar_one_or_none()
    if revision != W2_REVISION:
        _fail(
            "W2_MIGRATION_REVISION_NOT_APPLIED: expected "
            + W2_REVISION
            + " got "
            + repr(revision)
        )
    present = connection.execute(
        text("SELECT to_regclass(:table) IS NOT NULL"),
        {"table": SVC_PLAN_TABLE},
    ).scalar()
    if present is not True:
        _fail("W2_TABLE_MISSING: " + SVC_PLAN_TABLE)


def _require_shape(connection: Connection) -> None:
    """Verify table column set matches the sealed contract."""
    columns = {
        row[0]
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND table_name = 'recipient_service_plan_notice'
                """
            )
        ).all()
    }
    required_columns = {
        "id",
        "recipient_contract_id",
        "notification_date",
        "applied_start_date",
        "applied_end_date",
        "invalidated_at_utc",
        "replacement_service_plan_notice_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if columns != required_columns:
        missing = sorted(required_columns - columns)
        extra = sorted(columns - required_columns)
        _fail(
            "W2_TABLE_COLUMN_SET_MISMATCH: missing="
            + ",".join(missing)
            + ";extra="
            + ",".join(extra)
        )
    # Forbidden: recipient_certification_period_id (§2-4)
    if "recipient_certification_period_id" in columns:
        _fail("W2_FORBIDDEN_COLUMN_PRESENT: recipient_certification_period_id")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _gen_certification_number() -> str:
    """Generate a certification_number matching ^L[0-9]{10}$."""
    return f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"


def _insert_certification_identity(
    connection: Connection,
    *,
    recipient_id: int,
    certification_number: str,
    account_id: int,
) -> None:
    """Insert a erp.recipient_certification_identity row."""
    connection.execute(
        text(
            """
            INSERT INTO erp.recipient_certification_identity (
                recipient_id, certification_number,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, :certification_number,
                :account_id, :account_id
            )
            """
        ),
        {
            "recipient_id": recipient_id,
            "certification_number": certification_number,
            "account_id": account_id,
        },
    )


def _flush_constraints(connection: Connection) -> None:
    """Force deferred constraint evaluation."""
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _insert_recipient2_short_contract(
    connection: Connection,
    fixture: W2Fixture,
    *,
    end_date: date | None,
) -> int:
    """Insert a short contract for fixture.recipient_id_2 and return its id."""
    return connection.execute(
        text(
            f"""
            INSERT INTO {CONTRACT_TABLE} (
                recipient_id, service_type_id, start_date, end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, :service_type_id, '2026-01-01', :end_date,
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": fixture.recipient_id_2,
            "service_type_id": fixture.contract_service_type_id,
            "end_date": end_date,
            "account_id": fixture.account_id,
        },
    ).scalar_one()


def _insert_recipient2_short_cert_period(
    connection: Connection,
    fixture: W2Fixture,
    *,
    end_date: date,
) -> int:
    """Insert a short certification period for fixture.recipient_id_2 and return its id."""
    return connection.execute(
        text(
            f"""
            INSERT INTO {CERT_PERIOD_TABLE} (
                recipient_id, start_date, end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, '2026-01-01', :end_date,
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": fixture.recipient_id_2,
            "end_date": end_date,
            "account_id": fixture.account_id,
        },
    ).scalar_one()


def _insert_fixture_data(connection: Connection) -> W2Fixture:
    """Create minimal fixture rows needed by the live tests."""
    # (a) Seed erp.staff -> erp.user_account so empty temp DBs have an account.
    label = uuid4().hex
    account_staff_id = connection.execute(
        text(
            """
            INSERT INTO erp.staff
                (name, birth_date, sex_code, display_name, row_version)
            VALUES
                (:name, DATE '1990-01-01', 'TEST', :display_name, 1)
            RETURNING id
            """
        ),
        {
            "name": "W2 ACCOUNT STAFF " + label,
            "display_name": "W2 ACCOUNT " + label,
        },
    ).scalar_one()
    account = connection.execute(
        text(
            """
            INSERT INTO erp.user_account
                (staff_id, account_code, display_name, role_code,
                 pin_hash, pin_lookup_hmac, pin_key_version, row_version)
            VALUES
                (:staff_id, :account_code, :display_name, 'ADMIN',
                 :pin_hash, :pin_lookup_hmac, 1, 1)
            RETURNING id
            """
        ),
        {
            "staff_id": account_staff_id,
            "account_code": "W2_" + label,
            "display_name": "W2 ACCOUNT " + label,
            "pin_hash": "w2-test-pin-hash-" + label,
            "pin_lookup_hmac": uuid4().bytes,
        },
    ).scalar_one()

    # (b) Query two service_type ids by code — 'HOME_CARE' and 'HOME_BATH'
    #     (same LONG_TERM_CARE group).
    home_care_id = connection.execute(
        text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE'")
    ).scalar_one()
    home_bath_id = connection.execute(
        text("SELECT id FROM erp.service_type WHERE code = 'HOME_BATH'")
    ).scalar_one()

    # (c) Recipient inserts: sex_code 'MALE'/'FEMALE', no start_date column,
    # include created_by_account_id/updated_by_account_id.
    recipient = connection.execute(
        text(
            """
            INSERT INTO erp.recipient (
                name, birth_date, sex_code,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                'W2-TEST-1', '1980-06-15', 'MALE',
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {"account_id": account},
    ).scalar_one()
    recipient_2 = connection.execute(
        text(
            """
            INSERT INTO erp.recipient (
                name, birth_date, sex_code,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                'W2-TEST-2', '1985-03-20', 'FEMALE',
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {"account_id": account},
    ).scalar_one()

    # (d) fixture.contract_id uses HOME_CARE with end_date '2026-12-31'.
    contract = connection.execute(
        text(
            f"""
            INSERT INTO {CONTRACT_TABLE} (
                recipient_id, service_type_id, start_date, end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, :service_type_id, '2026-01-01', '2026-12-31',
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": recipient,
            "service_type_id": home_care_id,
            "account_id": account,
        },
    ).scalar_one()

    # (d) fixture.contract_id_endless uses HOME_BATH with end_date NULL.
    contract_endless = connection.execute(
        text(
            f"""
            INSERT INTO {CONTRACT_TABLE} (
                recipient_id, service_type_id, start_date, end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, :service_type_id, '2026-01-01', NULL,
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": recipient,
            "service_type_id": home_bath_id,
            "account_id": account,
        },
    ).scalar_one()

    # (f) For EACH recipient, insert certification identity BEFORE certification period.
    cert_number_1 = _gen_certification_number()
    _insert_certification_identity(
        connection,
        recipient_id=recipient,
        certification_number=cert_number_1,
        account_id=account,
    )
    cert_number_2 = _gen_certification_number()
    _insert_certification_identity(
        connection,
        recipient_id=recipient_2,
        certification_number=cert_number_2,
        account_id=account,
    )

    # (g) erp.recipient_certification_period INSERT must NOT include a
    # certification_number column (it does not exist on that table).
    cert_period = connection.execute(
        text(
            f"""
            INSERT INTO {CERT_PERIOD_TABLE} (
                recipient_id, start_date, end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, '2026-01-01', '2026-12-31',
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": recipient,
            "account_id": account,
        },
    ).scalar_one()

    cert_period_2 = connection.execute(
        text(
            f"""
            INSERT INTO {CERT_PERIOD_TABLE} (
                recipient_id, start_date, end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :recipient_id, '2026-01-01', '2026-12-31',
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": recipient_2,
            "account_id": account,
        },
    ).scalar_one()

    return W2Fixture(
        account_id=account,
        recipient_id=recipient,
        recipient_id_2=recipient_2,
        contract_id=contract,
        contract_id_endless=contract_endless,
        contract_service_type_id=home_care_id,
        contract_endless_service_type_id=home_bath_id,
        cert_period_id=cert_period,
        cert_period_id_2=cert_period_2,
    )


def _insert_valid_plan_notice(
    connection: Connection,
    fixture: W2Fixture,
    *,
    notification_date: date | None = None,
    applied_start_date: date | None = None,
    applied_end_date: date | None = None,
    contract_id: int | None = None,
) -> int:
    """Insert a valid service plan notice and return its id."""
    nd = notification_date or date(2026, 3, 1)
    asd = applied_start_date or date(2026, 1, 1)
    aed = applied_end_date or date(2026, 12, 31)
    cid = contract_id if contract_id is not None else fixture.contract_id
    return connection.execute(
        text(
            f"""
            INSERT INTO {SVC_PLAN_TABLE} (
                recipient_contract_id, notification_date,
                applied_start_date, applied_end_date,
                created_by_account_id, updated_by_account_id
            )
            VALUES (
                :contract_id, :notification_date,
                :applied_start_date, :applied_end_date,
                :account_id, :account_id
            )
            RETURNING id
            """
        ),
        {
            "contract_id": cid,
            "notification_date": nd,
            "applied_start_date": asd,
            "applied_end_date": aed,
            "account_id": fixture.account_id,
        },
    ).scalar_one()


# ===========================================================================
# §6 Item 1: 기본 종료일 계산
# ===========================================================================


def test_default_end_date_jan_jun() -> None:
    """§6 pg-1: 통보월 1~6월 → 같은 해 12월 31일."""
    try:
        from app.domains.recipient.service_plan_notice import default_end_date
    except ImportError:
        _product_absent("W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice")
    assert default_end_date(date(2026, 1, 15)) == date(2026, 12, 31)
    assert default_end_date(date(2026, 3, 1)) == date(2026, 12, 31)
    assert default_end_date(date(2026, 6, 30)) == date(2026, 12, 31)


def test_default_end_date_jul_dec() -> None:
    """§6 pg-1: 통보월 7~12월 → 다음 해 6월 30일."""
    try:
        from app.domains.recipient.service_plan_notice import default_end_date
    except ImportError:
        _product_absent("W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice")
    assert default_end_date(date(2026, 7, 1)) == date(2027, 6, 30)
    assert default_end_date(date(2026, 9, 15)) == date(2027, 6, 30)
    assert default_end_date(date(2026, 12, 31)) == date(2027, 6, 30)


# ===========================================================================
# §6 Item 2: 고정된 applied_end_date / 명시값 우선
# ===========================================================================


def test_fixed_end_date_not_recalculated(database_connection: Connection) -> None:
    """§6 pg-2: 통보월 변경에도 고정된 applied_end_date는 재계산되지 않음.

    통보월 3월에 생성된 계획서의 기본 종료일이 12월 31일이었는데,
    이후 notification_date를 9월로 변경해도 applied_end_date는 그대로.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        notification_date=date(2026, 3, 1),
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    # Update notification_date only — applied_end_date must remain unchanged
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET notification_date = :new_nd,
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {
            "new_nd": date(2026, 9, 1),
            "account_id": fixture.account_id,
            "plan_id": plan_id,
        },
    )

    _flush_constraints(database_connection)

    row = database_connection.execute(
        text(
            f"""
            SELECT notification_date, applied_end_date
            FROM {SVC_PLAN_TABLE}
            WHERE id = :plan_id
            """
        ),
        {"plan_id": plan_id},
    ).one()
    assert row[0] == date(2026, 9, 1)  # notification_date updated
    assert row[1] == date(2026, 12, 31)  # applied_end_date NOT recalculated


def test_explicit_end_date_overrides_default(database_connection: Connection) -> None:
    """§6 pg-2: 사용자 명시 값이 기본 계산값보다 우선."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # March → default would be Dec 31, but explicit value is Oct 31
    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        notification_date=date(2026, 3, 1),
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 10, 31),
    )

    _flush_constraints(database_connection)

    row = database_connection.execute(
        text(
            f"""
            SELECT applied_end_date FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": plan_id},
    ).one()
    assert row[0] == date(2026, 10, 31)


# ===========================================================================
# §6 Item 3: recipient_contract_id 필수 RESTRICT FK
# ===========================================================================


def test_missing_contract_rejected(database_connection: Connection) -> None:
    """§6 pg-3: 존재하지 않는 contract_id로 INSERT 시 FK 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                INSERT INTO {SVC_PLAN_TABLE} (
                    recipient_contract_id, notification_date,
                    applied_start_date, applied_end_date,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :contract_id, :notification_date,
                    :applied_start_date, :applied_end_date,
                    :account_id, :account_id
                )
                """
            ),
            {
                "contract_id": 999999999,
                "notification_date": date(2026, 3, 1),
                "applied_start_date": date(2026, 1, 1),
                "applied_end_date": date(2026, 12, 31),
                "account_id": fixture.account_id,
            },
        )
    assert "fk_service_plan_notice_recipient_contract" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 4: 연결된 계약이 이미 무효화 상태면 INSERT/UPDATE 거부
# ===========================================================================


def test_contract_invalidated_rejects_insert(database_connection: Connection) -> None:
    """§6 pg-4: 이미 무효화된 계약에 계획서 INSERT 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate the contract
    database_connection.execute(
        text(
            f"""
            UPDATE {CONTRACT_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :contract_id
            """
        ),
        {"contract_id": fixture.contract_id, "account_id": fixture.account_id},
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(database_connection, fixture)
        _flush_constraints(database_connection)
    assert "service_plan_contract_invalidated" in str(exc_info.value.orig).lower()


def test_contract_invalidated_rejects_update(database_connection: Connection) -> None:
    """§6 pg-4: 계약 무효화 후 유효 계획서를 되살리는 UPDATE 거부.

    Insert a valid plan, self-invalidate it (exempts from reverse guard),
    invalidate the contract (now succeeds since no live plans reference it),
    then attempt to REVIVE the plan — must reject.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    plan_id = _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    # Self-invalidate the plan (live-filter exempts it from reverse guard)
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {"plan_id": plan_id, "account_id": fixture.account_id},
    )

    _flush_constraints(database_connection)

    # Now invalidate the contract — succeeds because no live plans reference it
    database_connection.execute(
        text(
            f"""
            UPDATE {CONTRACT_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :contract_id
            """
        ),
        {"contract_id": fixture.contract_id, "account_id": fixture.account_id},
    )

    _flush_constraints(database_connection)

    # Attempt to revive the plan — must reject
    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {SVC_PLAN_TABLE}
                SET invalidated_at_utc = NULL,
                    updated_by_account_id = :account_id
                WHERE id = :plan_id
                """
            ),
            {"plan_id": plan_id, "account_id": fixture.account_id},
        )
        _flush_constraints(database_connection)
    assert "service_plan_contract_invalidated" in str(exc_info.value.orig).lower()


def test_contract_invalidated_plan_notice_self_invalidated_skips_check(
    database_connection: Connection,
) -> None:
    """§6 pg-4: 계획서 자신이 무효화 상태면 계약 무효화 검사 제외.

    같은 트랜잭션에서 기존 계획서를 무효화할 때, 그 행은 검사하지 않는다.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Insert valid plan, then invalidate it — this must NOT reject
    # because the plan itself is being invalidated (live-filter)
    plan_id = _insert_valid_plan_notice(database_connection, fixture)

    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {"plan_id": plan_id, "account_id": fixture.account_id},
    )
    _flush_constraints(database_connection)
    # Should succeed — self-invalidation is allowed
    row = database_connection.execute(
        text(
            f"""
            SELECT invalidated_at_utc IS NOT NULL
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": plan_id},
    ).scalar()
    assert row is True


# ===========================================================================
# §6 Item 5: 같은 트랜잭션 무효화+대체 원자적 정정
# ===========================================================================


def test_atomic_correction_invalidate_and_replace(
    database_connection: Connection,
) -> None:
    """§6 pg-5: 같은 트랜잭션에서 기존 계획서 무효화 + 대체 INSERT 성공.

    Also shortens the parent contract in the same transaction to prove the
    replacement plan must fit within the shortened contract bounds.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Insert original plan with applied_end_date 2026-12-31
    original_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    # Shorten the parent contract end_date to 2026-06-30 in the SAME transaction
    database_connection.execute(
        text(
            f"""
            UPDATE {CONTRACT_TABLE}
            SET end_date = :new_end,
                updated_by_account_id = :account_id
            WHERE id = :contract_id
            """
        ),
        {
            "new_end": date(2026, 6, 30),
            "account_id": fixture.account_id,
            "contract_id": fixture.contract_id,
        },
    )

    # Also shorten the cert period end_date to 2026-06-30 in the SAME transaction
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET end_date = :new_end,
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {
            "new_end": date(2026, 6, 30),
            "account_id": fixture.account_id,
            "cert_id": fixture.cert_period_id,
        },
    )

    # Invalidate original
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :original_id
            """
        ),
        {"original_id": original_id, "account_id": fixture.account_id},
    )

    # Insert replacement with applied_end_date 2026-06-30 (fits shortened contract)
    replacement_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 6, 30),
    )

    # Link original → replacement
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET replacement_service_plan_notice_id = :replacement_id,
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {
            "replacement_id": replacement_id,
            "plan_id": original_id,
            "account_id": fixture.account_id,
        },
    )

    _flush_constraints(database_connection)

    # Verify original is invalidated and has replacement link
    original_inv = database_connection.execute(
        text(
            f"""
            SELECT invalidated_at_utc IS NOT NULL,
                   replacement_service_plan_notice_id
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id},
    ).one()
    assert original_inv[0] is True
    assert original_inv[1] == replacement_id

    replacement_valid = database_connection.execute(
        text(
            f"""
            SELECT invalidated_at_utc IS NULL
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": replacement_id},
    ).scalar()
    assert replacement_valid is True


# ===========================================================================
# §6 Item 6: applied_start_date < contract.start_date 거부
# ===========================================================================


def test_start_date_before_contract_start_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-6: applied_start_date가 계약 start_date보다 앞서면 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Contract starts 2026-01-01, but we try applied_start_date 2025-12-01
    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            applied_start_date=date(2025, 12, 1),
            applied_end_date=date(2026, 12, 31),
        )
        _flush_constraints(database_connection)
    assert "service_plan_before_contract_start" in str(exc_info.value.orig).lower()


def test_start_date_before_contract_start_rejected_on_update(
    database_connection: Connection,
) -> None:
    """§6 pg-6: applied_start_date UPDATE로 계약 start_date보다 앞서면 거부.

    Insert a valid plan_notice first, then attempt to UPDATE its
    applied_start_date to before the contract's start_date.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {SVC_PLAN_TABLE}
                SET applied_start_date = :new_start,
                    updated_by_account_id = :account_id
                WHERE id = :plan_id
                """
            ),
            {
                "new_start": date(2025, 12, 1),
                "account_id": fixture.account_id,
                "plan_id": plan_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_before_contract_start" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 7: 역방향 guard — 계약 start_date 저장 후 늦추기 거부
# ===========================================================================


def test_reverse_guard_contract_start_delayed_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-7: 계약 start_date를 계획서 applied_start_date보다 늦게 이동 시 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    _flush_constraints(database_connection)

    # Delay contract start_date past the plan's applied_start_date
    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET start_date = :new_start,
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {
                "new_start": date(2026, 6, 1),
                "account_id": fixture.account_id,
                "contract_id": fixture.contract_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_before_contract_start" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 8: cap 규칙 — 3가지 조합 + boundary tests
# ===========================================================================


def test_cap_contract_shorter_than_certification(
    database_connection: Connection,
) -> None:
    """§6 pg-8-a: 계약이 인정기간보다 짧은 경우 계약 end_date가 cap."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Contract ends 2026-12-31, cert ends 2026-12-31 — ok at boundary
    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )
    assert plan_id > 0

    _flush_constraints(database_connection)

    # Use helper to create a short contract for recipient_id_2 (avoids GiST collision)
    short_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            contract_id=short_contract_id,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2026, 12, 31),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_contract_period" in str(exc_info.value.orig).lower()


def test_cap_certification_shorter_than_contract(
    database_connection: Connection,
) -> None:
    """§6 pg-8-b: 인정기간이 계약보다 짧은 경우 인정기간 end_date가 cap."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Create a fresh contract for recipient_id_2 with generous end_date
    long_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )

    # Invalidate the existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    # Create a short cert period for recipient_id_2
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 3, 31)
    )

    _flush_constraints(database_connection)

    # Contract ends 2026-12-31, cert ends 2026-03-31
    # applied_end_date=2026-12-31 should exceed cert cap
    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            contract_id=long_contract_id,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2026, 12, 31),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_cap_endless_contract_cert_only_cap(
    database_connection: Connection,
) -> None:
    """§6 pg-8-c: 계약이 무기한(NULL end_date)이면 인정기간 end_date가 유일한 cap."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Create a fresh endless contract for recipient_id_2
    endless_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=None
    )

    # Invalidate the existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    # Create a cert period for recipient_id_2 ending 2026-12-31
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )

    _flush_constraints(database_connection)

    # Contract is endless (NULL end_date), cert ends 2026-12-31
    # applied_end_date=2027-06-30 exceeds cert cap
    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            contract_id=endless_contract_id,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2027, 6, 30),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_cap_boundary_accepted_at_exact_contract_end_date(
    database_connection: Connection,
) -> None:
    """§6 pg-8: applied_end_date exactly at contract end_date must succeed."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    short_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        contract_id=short_contract_id,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 6, 30),
    )
    _flush_constraints(database_connection)
    assert plan_id > 0


def test_cap_boundary_rejected_one_day_past_contract_end(
    database_connection: Connection,
) -> None:
    """§6 pg-8: applied_end_date one day past contract end_date must reject."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    short_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            contract_id=short_contract_id,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2026, 7, 1),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_contract_period" in str(exc_info.value.orig).lower()


def test_cap_update_past_cap_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-8: UPDATE applied_end_date past contract cap must reject."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    short_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        contract_id=short_contract_id,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 6, 30),
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {SVC_PLAN_TABLE}
                SET applied_end_date = :new_end,
                    updated_by_account_id = :account_id
                WHERE id = :plan_id
                """
            ),
            {
                "new_end": date(2026, 7, 1),
                "account_id": fixture.account_id,
                "plan_id": plan_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_contract_period" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 8 boundary — cert-shorter combination
# ===========================================================================


def test_cap_boundary_accepted_at_exact_cert_end_date(
    database_connection: Connection,
) -> None:
    """§6 pg-8-b: applied_end_date exactly at cert end_date must succeed."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    long_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        contract_id=long_contract_id,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 6, 30),
    )
    _flush_constraints(database_connection)
    assert plan_id > 0


def test_cap_boundary_rejected_one_day_past_cert_end(
    database_connection: Connection,
) -> None:
    """§6 pg-8-b: applied_end_date one day past cert end_date must reject."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    long_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            contract_id=long_contract_id,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2026, 7, 1),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_cap_update_past_cert_cap_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-8-b: UPDATE applied_end_date past cert cap must reject."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    long_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 6, 30)
    )

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        contract_id=long_contract_id,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 6, 30),
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {SVC_PLAN_TABLE}
                SET applied_end_date = :new_end,
                    updated_by_account_id = :account_id
                WHERE id = :plan_id
                """
            ),
            {
                "new_end": date(2026, 7, 1),
                "account_id": fixture.account_id,
                "plan_id": plan_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 8 boundary — endless-contract cert-only-cap combination
# ===========================================================================


def test_cap_boundary_accepted_at_exact_cert_end_date_endless(
    database_connection: Connection,
) -> None:
    """§6 pg-8-c: applied_end_date exactly at cert end_date must succeed (endless contract)."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    endless_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=None
    )
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        contract_id=endless_contract_id,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )
    _flush_constraints(database_connection)
    assert plan_id > 0


def test_cap_boundary_rejected_one_day_past_cert_end_endless(
    database_connection: Connection,
) -> None:
    """§6 pg-8-c: applied_end_date one day past cert end_date must reject (endless contract)."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    endless_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=None
    )
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            contract_id=endless_contract_id,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2027, 1, 1),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_cap_update_past_cert_cap_rejected_endless(
    database_connection: Connection,
) -> None:
    """§6 pg-8-c: UPDATE applied_end_date past cert cap must reject (endless contract)."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate existing cert_period_id_2 to avoid exclusion overlap
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id_2, "account_id": fixture.account_id},
    )

    endless_contract_id = _insert_recipient2_short_contract(
        database_connection, fixture, end_date=None
    )
    _insert_recipient2_short_cert_period(
        database_connection, fixture, end_date=date(2026, 12, 31)
    )

    plan_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        contract_id=endless_contract_id,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {SVC_PLAN_TABLE}
                SET applied_end_date = :new_end,
                    updated_by_account_id = :account_id
                WHERE id = :plan_id
                """
            ),
            {
                "new_end": date(2027, 1, 1),
                "account_id": fixture.account_id,
                "plan_id": plan_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 9: 유효 인정기간 부재/부분 커버 거부
# ===========================================================================


def test_no_certification_period_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-9-a: 유효 인정기간이 전혀 없는 경우 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate all cert periods for this recipient
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE recipient_id = :recipient_id
            """
        ),
        {"recipient_id": fixture.recipient_id, "account_id": fixture.account_id},
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(database_connection, fixture)
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_partial_certification_coverage_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-9-b: 인정기간이 부분적으로만 커버하는 경우 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Cert period covers 2026-03-01 to 2026-12-31
    # Plan asks for 2026-01-01 to 2026-12-31 — Jan-Feb not covered
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET start_date = :new_start,
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {
            "new_start": date(2026, 3, 1),
            "account_id": fixture.account_id,
            "cert_id": fixture.cert_period_id,
        },
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2026, 12, 31),
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 10: 수급자 범위 검증
# ===========================================================================


def test_other_recipient_certification_not_used(
    database_connection: Connection,
) -> None:
    """§6 pg-10: 다른 수급자 인정기간은 cap/coverage에 사용되지 않음."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    # Invalidate recipient_1's cert period
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"cert_id": fixture.cert_period_id, "account_id": fixture.account_id},
    )

    _flush_constraints(database_connection)

    # recipient_2 has a valid cert period, but it should NOT be used
    # because the contract belongs to recipient_1 (different recipient_id)
    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(database_connection, fixture)
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 11: applied_end_date >= applied_start_date CHECK
# ===========================================================================


def test_end_date_before_start_date_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-11: applied_end_date < applied_start_date CHECK 위반 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        _insert_valid_plan_notice(
            database_connection,
            fixture,
            applied_start_date=date(2026, 12, 31),
            applied_end_date=date(2026, 1, 1),
        )
    assert "ck_service_plan_notice_date_order" in str(exc_info.value.orig).lower()


# ===========================================================================
# §6 Item 12: 역방향 guard — 단축·무효화·대체·DELETE
# ===========================================================================


def test_reverse_guard_contract_shorten_end_date_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12-a: 계약 종료일 단축(당김) 시 유효 계획서가 cap을 초과하면 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    _flush_constraints(database_connection)

    # Shorten contract end_date to 2026-06-30 — plan's end_date now exceeds
    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET end_date = :new_end,
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {
                "new_end": date(2026, 6, 30),
                "account_id": fixture.account_id,
                "contract_id": fixture.contract_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_contract_period" in str(exc_info.value.orig).lower()


def test_reverse_guard_contract_invalidate_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12-b: 계약 무효화 시 유효 계획서가 있으면 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET invalidated_at_utc = now(),
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {"contract_id": fixture.contract_id, "account_id": fixture.account_id},
        )
        _flush_constraints(database_connection)
    assert "service_plan_contract_invalidated" in str(exc_info.value.orig).lower()


def test_reverse_guard_contract_replace_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12: 계약 대체 시 유효 계획서가 있으면 거부.

    Order matters: the exclusion constraint on erp.recipient_contract is NOT
    deferrable, so the old row must be invalidated BEFORE inserting the new
    overlapping row.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        # (1) Invalidate the old contract FIRST
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET invalidated_at_utc = now(),
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {"contract_id": fixture.contract_id, "account_id": fixture.account_id},
        )
        # (2) Insert new overlapping contract row
        new_id = database_connection.execute(
            text(
                f"""
                INSERT INTO {CONTRACT_TABLE} (
                    recipient_id, service_type_id, start_date, end_date,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :recipient_id, :service_type_id, '2026-01-01', '2026-06-30',
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "recipient_id": fixture.recipient_id,
                "service_type_id": fixture.contract_service_type_id,
                "account_id": fixture.account_id,
            },
        ).scalar_one()
        # (3) Link old → new
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET replacement_contract_id = :new_id,
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {
                "new_id": new_id,
                "contract_id": fixture.contract_id,
                "account_id": fixture.account_id,
            },
        )
        _flush_constraints(database_connection)
    assert (
        "service_plan_contract_invalidated" in str(exc_info.value.orig).lower()
        or "service_plan_outside_contract_period" in str(exc_info.value.orig).lower()
    )


def test_reverse_guard_cert_period_delete_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12-c: 인정기간 DELETE 시 유효 계획서가 orphan 되면 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                DELETE FROM {CERT_PERIOD_TABLE}
                WHERE id = :cert_id
                """
            ),
            {"cert_id": fixture.cert_period_id},
        )
        _flush_constraints(database_connection)
    # Should be caught by reverse guard
    assert "orphan" in str(exc_info.value.orig).lower() or (
        "service_plan_outside_certification_period"
        in str(exc_info.value.orig).lower()
    )


def test_reverse_guard_cert_period_shorten_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12: 인정기간 end_date 단축 시 유효 계획서가 cap을 초과하면 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CERT_PERIOD_TABLE}
                SET end_date = :new_end,
                    updated_by_account_id = :account_id
                WHERE id = :cert_id
                """
            ),
            {
                "new_end": date(2026, 6, 30),
                "account_id": fixture.account_id,
                "cert_id": fixture.cert_period_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_reverse_guard_cert_period_invalidate_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12: 인정기간 무효화 시 유효 계획서가 있으면 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CERT_PERIOD_TABLE}
                SET invalidated_at_utc = now(),
                    updated_by_account_id = :account_id
                WHERE id = :cert_id
                """
            ),
            {"cert_id": fixture.cert_period_id, "account_id": fixture.account_id},
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_reverse_guard_cert_period_replace_rejected(
    database_connection: Connection,
) -> None:
    """§6 pg-12: 인정기간 대체 시 유효 계획서가 있으면 거부.

    Invalidate old cert period, insert new shorter one — identity already exists.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        # (1) Invalidate old cert period FIRST (non-deferrable exclusion)
        database_connection.execute(
            text(
                f"""
                UPDATE {CERT_PERIOD_TABLE}
                SET invalidated_at_utc = now(),
                    updated_by_account_id = :account_id
                WHERE id = :cert_id
                """
            ),
            {"cert_id": fixture.cert_period_id, "account_id": fixture.account_id},
        )
        # (2) Insert new shorter cert period (no new identity needed)
        new_cert_id = database_connection.execute(
            text(
                f"""
                INSERT INTO {CERT_PERIOD_TABLE} (
                    recipient_id, start_date, end_date,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :recipient_id, '2026-01-01', '2026-06-30',
                    :account_id, :account_id
                )
                RETURNING id
                """
            ),
            {
                "recipient_id": fixture.recipient_id,
                "account_id": fixture.account_id,
            },
        ).scalar_one()
        # (3) Link old → new
        database_connection.execute(
            text(
                f"""
                UPDATE {CERT_PERIOD_TABLE}
                SET replacement_certification_period_id = :new_id,
                    updated_by_account_id = :account_id
                WHERE id = :cert_id
                """
            ),
            {
                "new_id": new_cert_id,
                "cert_id": fixture.cert_period_id,
                "account_id": fixture.account_id,
            },
        )
        _flush_constraints(database_connection)
    assert "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()


def test_reverse_guard_contract_delete_blocked_by_fk(
    database_connection: Connection,
) -> None:
    """§6 pg-12-d: 계약 DELETE는 RESTRICT FK에 의해 차단됨."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                DELETE FROM {CONTRACT_TABLE}
                WHERE id = :contract_id
                """
            ),
            {"contract_id": fixture.contract_id},
        )
    assert "fk_service_plan_notice_recipient_contract" in str(exc_info.value.orig).lower()


def test_reverse_guard_invalidated_plan_excluded(
    database_connection: Connection,
) -> None:
    """§6 pg-12-e: 이미 무효화된 계획서는 역방향 guard 검사에서 제외."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    plan_id = _insert_valid_plan_notice(database_connection, fixture)

    # Invalidate the plan first
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {"plan_id": plan_id, "account_id": fixture.account_id},
    )

    _flush_constraints(database_connection)

    # Now invalidating the contract should succeed (no valid plans)
    database_connection.execute(
        text(
            f"""
            UPDATE {CONTRACT_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :contract_id
            """
        ),
        {"contract_id": fixture.contract_id, "account_id": fixture.account_id},
    )
    _flush_constraints(database_connection)
    # Should NOT raise


# ===========================================================================
# §6 Item 13: DEFERRABLE — 동일 트랜잭션 원자적 정정 허용
# ===========================================================================


def test_deferrable_atomic_contract_shorten_with_plan_correction(
    database_connection: Connection,
) -> None:
    """§6 pg-13: 계약 단축 + 계획서 동시 정정이 같은 트랜잭션에서 성공.

    DEFERRABLE INITIALLY DEFERRED 지연평가로 최종 상태만 일관되면 통과.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    original_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    # In the same transaction:
    # 1. Shorten contract end_date
    # 2. Shorten cert period end_date
    # 3. Invalidate the old plan
    # 4. Insert a corrected plan within new bounds
    database_connection.execute(
        text(
            f"""
            UPDATE {CONTRACT_TABLE}
            SET end_date = :new_end,
                updated_by_account_id = :account_id
            WHERE id = :contract_id
            """
        ),
        {
            "new_end": date(2026, 6, 30),
            "account_id": fixture.account_id,
            "contract_id": fixture.contract_id,
        },
    )
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET end_date = :new_end,
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {
            "new_end": date(2026, 6, 30),
            "account_id": fixture.account_id,
            "cert_id": fixture.cert_period_id,
        },
    )
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id, "account_id": fixture.account_id},
    )
    new_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 6, 30),
    )
    _flush_constraints(database_connection)
    assert new_id > 0


# ===========================================================================
# §6 Item 14: SERIALIZABLE write-skew
# ===========================================================================


def test_serializable_isolation_accepted(database_connection: Connection) -> None:
    """§6 pg-14-a: SERIALIZABLE 격리수준에서 단일 트랜잭션 정상 동작 확인."""
    database_connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    # Verify the setting took effect
    level = database_connection.execute(text("SHOW transaction_isolation")).scalar()
    assert level == "serializable"

    _require_catalog(database_connection)
    _require_shape(database_connection)


def test_serializable_write_skew_two_transactions(
    database_engine: Engine,
) -> None:
    """§6 pg-14-b: SERIALIZABLE write-skew detection with two threads.

    Seeded plan_notice has applied_end_date 2026-06-30, which is valid under
    both the original contract end_date (2026-12-31) AND T1's shortened
    end_date (2026-06-30).  T1 shortens the contract to 2026-06-30 — this
    alone would succeed because the seeded plan fits.  T2 reads the
    pre-change contract end_date (2026-12-31) and inserts a NEW plan_notice
    with applied_end_date 2026-12-31 (valid under the old snapshot, but
    invalid under T1's shortened end_date).  PostgreSQL SSI must detect the
    read-write anti-dependency cycle and abort one transaction with sqlstate
    40001.  The aborted transaction is retried with its original operation;
    the retry must be genuinely rejected (IntegrityError) because the
    operation is invalid against the final committed state.
    """
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W2_HARNESS_DATABASE_URL_MISSING")

    # Seed fixture + one existing valid plan_notice on a COMMITTED connection first.
    # The seeded plan has applied_end_date 2026-06-30 — valid under both the
    # original end_date (2026-12-31) and T1's shortened end_date (2026-06-30).
    with database_engine.connect() as seed_conn:
        seed_conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        fixture = _insert_fixture_data(seed_conn)
        _insert_valid_plan_notice(
            seed_conn,
            fixture,
            applied_start_date=date(2026, 1, 1),
            applied_end_date=date(2026, 6, 30),
        )
        _flush_constraints(seed_conn)
        seed_conn.execute(text("COMMIT"))

    barrier = threading.Barrier(2, timeout=20)
    results: dict[str, Any] = {}

    def t1_shorten_contract() -> None:
        engine = create_engine(database_url, pool_pre_ping=True)
        conn = None
        tx = None
        try:
            conn = engine.connect()
            conn = conn.execution_options(isolation_level="SERIALIZABLE")
            tx = conn.begin()
            conn.execute(
                text(
                    f"""
                    UPDATE {CONTRACT_TABLE}
                    SET end_date = :new_end,
                        updated_by_account_id = :account_id
                    WHERE id = :contract_id
                    """
                ),
                {
                    "new_end": date(2026, 6, 30),
                    "account_id": fixture.account_id,
                    "contract_id": fixture.contract_id,
                },
            )
            barrier.wait()
            tx.commit()
            results["t1"] = "ok"
        except Exception as exc:
            if tx is not None:
                try:
                    tx.rollback()
                except Exception:
                    pass
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
                getattr(getattr(exc, "orig", None), "diag", None), "sqlstate", None
            )
            if sqlstate == "40001":
                results["t1"] = "40001"
            else:
                results["t1"] = f"err:{sqlstate}:{type(exc).__name__}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            engine.dispose()

    def t2_insert_plan() -> None:
        engine = create_engine(database_url, pool_pre_ping=True)
        conn = None
        tx = None
        try:
            conn = engine.connect()
            conn = conn.execution_options(isolation_level="SERIALIZABLE")
            tx = conn.begin()
            # Read contract row (establishes read dependency on pre-change state)
            conn.execute(
                text(
                    f"""
                    SELECT id, end_date FROM {CONTRACT_TABLE}
                    WHERE id = :contract_id
                    """
                ),
                {"contract_id": fixture.contract_id},
            ).one()
            # Insert new plan valid under OLD end_date (2026-12-31) but
            # invalid under T1's NEW end_date (2026-06-30)
            conn.execute(
                text(
                    f"""
                    INSERT INTO {SVC_PLAN_TABLE} (
                        recipient_contract_id, notification_date,
                        applied_start_date, applied_end_date,
                        created_by_account_id, updated_by_account_id
                    )
                    VALUES (
                        :contract_id, :notification_date,
                        :applied_start_date, :applied_end_date,
                        :account_id, :account_id
                    )
                    """
                ),
                {
                    "contract_id": fixture.contract_id,
                    "notification_date": date(2026, 3, 1),
                    "applied_start_date": date(2026, 1, 1),
                    "applied_end_date": date(2026, 12, 31),
                    "account_id": fixture.account_id,
                },
            )
            barrier.wait()
            tx.commit()
            results["t2"] = "ok"
        except Exception as exc:
            if tx is not None:
                try:
                    tx.rollback()
                except Exception:
                    pass
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(
                getattr(getattr(exc, "orig", None), "diag", None), "sqlstate", None
            )
            if sqlstate == "40001":
                results["t2"] = "40001"
            else:
                results["t2"] = f"err:{sqlstate}:{type(exc).__name__}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            engine.dispose()

    thread1 = threading.Thread(target=t1_shorten_contract, daemon=True)
    thread2 = threading.Thread(target=t2_insert_plan, daemon=True)
    thread1.start()
    thread2.start()
    thread1.join(timeout=60)
    thread2.join(timeout=60)

    t1_result = results.get("t1", "missing")
    t2_result = results.get("t2", "missing")

    # Exactly one must have succeeded, the other must be 40001
    oks = sum(1 for r in (t1_result, t2_result) if r == "ok")
    aborts = sum(1 for r in (t1_result, t2_result) if r == "40001")
    if oks != 1 or aborts != 1:
        _fail(
            "W2_SSI_WRITE_SKEW_RESULT: t1="
            + repr(t1_result)
            + " t2="
            + repr(t2_result)
        )

    # Retry the aborted operation with its ORIGINAL input values.
    # The winner's committed changes make the aborted operation invalid,
    # so the retry must be rejected with IntegrityError.
    aborted = "t1" if results.get("t1") == "40001" else "t2"
    retry_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with retry_engine.connect() as retry_conn:
            retry_conn = retry_conn.execution_options(isolation_level="SERIALIZABLE")
            try:
                with retry_conn.begin():
                    if aborted == "t1":
                        retry_conn.execute(
                            text(
                                f"""
                                UPDATE {CONTRACT_TABLE}
                                SET end_date = :new_end,
                                    updated_by_account_id = :account_id
                                WHERE id = :contract_id
                                """
                            ),
                            {
                                "new_end": date(2026, 6, 30),
                                "account_id": fixture.account_id,
                                "contract_id": fixture.contract_id,
                            },
                        )
                        retry_conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                    else:  # T2
                        retry_conn.execute(
                            text(
                                f"""
                                INSERT INTO {SVC_PLAN_TABLE} (
                                    recipient_contract_id, notification_date,
                                    applied_start_date, applied_end_date,
                                    created_by_account_id, updated_by_account_id
                                )
                                VALUES (
                                    :contract_id, :notification_date,
                                    :applied_start_date, :applied_end_date,
                                    :account_id, :account_id
                                )
                                """
                            ),
                            {
                                "contract_id": fixture.contract_id,
                                "notification_date": date(2026, 3, 1),
                                "applied_start_date": date(2026, 1, 1),
                                "applied_end_date": date(2026, 12, 31),
                                "account_id": fixture.account_id,
                            },
                        )
                        retry_conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                # If we reach here, the retry succeeded — but the operation
                # should have been rejected because the winner's changes made it invalid.
                _fail(
                    "W2_SSI_RETRY_SHOULD_HAVE_BEEN_REJECTED: aborted="
                    + aborted
                    + " t1="
                    + repr(results.get("t1"))
                    + " t2="
                    + repr(results.get("t2"))
                )
            except IntegrityError as exc_info:
                # Expected: the winner's changes make the aborted operation invalid.
                assert "service_plan_outside_contract_period" in str(exc_info.orig).lower()
    finally:
        retry_engine.dispose()


# ===========================================================================
# §6 Item 15: recipient_id immutability
# ===========================================================================


def test_recipient_contract_recipient_id_immutable(
    database_connection: Connection,
) -> None:
    """§6 pg-15-i: recipient_contract.recipient_id UPDATE 시 immutability CHECK 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET recipient_id = :new_recipient_id,
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {
                "new_recipient_id": fixture.recipient_id_2,
                "account_id": fixture.account_id,
                "contract_id": fixture.contract_id,
            },
        )
    # Expect 23514 check_violation from immutability trigger
    assert "23514" in str(exc_info.value.orig) or (
        "immutable" in str(exc_info.value.orig).lower()
    )


def test_certification_period_recipient_id_immutable(
    database_connection: Connection,
) -> None:
    """§6 pg-15-i: certification_period.recipient_id UPDATE 시 immutability CHECK 거부."""
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CERT_PERIOD_TABLE}
                SET recipient_id = :new_recipient_id,
                    updated_by_account_id = :account_id
                WHERE id = :cert_id
                """
            ),
            {
                "new_recipient_id": fixture.recipient_id_2,
                "account_id": fixture.account_id,
                "cert_id": fixture.cert_period_id,
            },
        )
    assert "23514" in str(exc_info.value.orig) or (
        "immutable" in str(exc_info.value.orig).lower()
    )


def test_reverse_guard_old_recipient_orphan_detection(
    database_connection: Connection,
) -> None:
    """§6 pg-15-ii: immutability trigger 우회 후 역방향 guard가 OLD 수급자 orphan 감지.

    방어적 RED: trigger를 disable → recipient_id 변경 → re-enable 후,
    역방향 guard가 OLD recipient의 유효 계획서 orphan을 감지·거부.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    _flush_constraints(database_connection)

    # Try to bypass immutability by disabling the trigger
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.recipient_contract "
                "DISABLE TRIGGER ct_recipient_contract_recipient_id_immutable"
            )
        )
    except Exception:
        pytest.skip("cannot disable trigger with current role")

    with pytest.raises(IntegrityError) as exc_info:
        # Reparent the contract to recipient_id_2
        database_connection.execute(
            text(
                f"""
                UPDATE {CONTRACT_TABLE}
                SET recipient_id = :new_recipient_id,
                    updated_by_account_id = :account_id
                WHERE id = :contract_id
                """
            ),
            {
                "new_recipient_id": fixture.recipient_id_2,
                "account_id": fixture.account_id,
                "contract_id": fixture.contract_id,
            },
        )
        # Re-enable the trigger
        database_connection.execute(
            text(
                "ALTER TABLE erp.recipient_contract "
                "ENABLE TRIGGER ct_recipient_contract_recipient_id_immutable"
            )
        )
        _flush_constraints(database_connection)
    assert (
        "orphan" in str(exc_info.value.orig).lower()
        or "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()
        or "service_plan_contract_invalidated" in str(exc_info.value.orig).lower()
    )


def test_reverse_guard_old_recipient_orphan_detection_cert_period(
    database_connection: Connection,
) -> None:
    """§6 pg-15-ii: immutability trigger 우회 후 역방향 guard가 OLD 수급자 orphan 감지 — 인정기간.

    방어적 RED: trigger를 disable → recipient_id 변경 → re-enable 후,
    역방향 guard가 OLD recipient의 유효 계획서 orphan을 감지·거부.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    _insert_valid_plan_notice(database_connection, fixture)

    # recipient_id_2 already has its own active certification period
    # (fixture.cert_period_id_2) covering the same date range as
    # fixture.cert_period_id. The exclusion constraint on
    # erp.recipient_certification_period is NOT deferrable, so reassigning
    # fixture.cert_period_id onto recipient_id_2 below would otherwise be
    # rejected by that exclusion conflict before the reverse guard under
    # test ever runs. Invalidate recipient_id_2's own period first to free
    # the date range.
    database_connection.execute(
        text(
            f"""
            UPDATE {CERT_PERIOD_TABLE}
            SET invalidated_at_utc = now(),
                updated_by_account_id = :account_id
            WHERE id = :cert_id
            """
        ),
        {"account_id": fixture.account_id, "cert_id": fixture.cert_period_id_2},
    )

    _flush_constraints(database_connection)

    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.recipient_certification_period "
                "DISABLE TRIGGER ct_recipient_certification_period_recipient_id_immutable"
            )
        )
    except Exception:
        pytest.skip("cannot disable trigger with current role")

    with pytest.raises(IntegrityError) as exc_info:
        database_connection.execute(
            text(
                f"""
                UPDATE {CERT_PERIOD_TABLE}
                SET recipient_id = :new_recipient_id,
                    updated_by_account_id = :account_id
                WHERE id = :cert_id
                """
            ),
            {
                "new_recipient_id": fixture.recipient_id_2,
                "account_id": fixture.account_id,
                "cert_id": fixture.cert_period_id,
            },
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.recipient_certification_period "
                "ENABLE TRIGGER ct_recipient_certification_period_recipient_id_immutable"
            )
        )
        _flush_constraints(database_connection)
    assert (
        "orphan" in str(exc_info.value.orig).lower()
        or "service_plan_outside_certification_period" in str(exc_info.value.orig).lower()
        or "service_plan_contract_invalidated" in str(exc_info.value.orig).lower()
    )


# ===========================================================================
# §6 Item 16: D-100/D-45 순수함수
# ===========================================================================


def test_d100_calculation() -> None:
    """§6 pg-16: 작성마감일 기준 D-100 계산 순수함수 검증."""
    try:
        from app.domains.recipient.service_plan_notice import d100_date, deadline_date
    except ImportError:
        _product_absent("W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice")
    # Notice date 2026-01-15 → deadline = 2026-07-15 → D-100 = around 2026-04-06
    nd = date(2026, 1, 15)
    dl = deadline_date(nd)
    assert dl == date(2026, 7, 15)
    d100 = d100_date(nd)
    assert d100 == date(2026, 4, 6)


def test_d45_calculation() -> None:
    """§6 pg-16: 작성마감일 기준 D-45 계산 순수함수 검증."""
    try:
        from app.domains.recipient.service_plan_notice import d45_date, deadline_date
    except ImportError:
        _product_absent("W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice")
    nd = date(2026, 1, 15)
    dl = deadline_date(nd)
    assert dl == date(2026, 7, 15)
    d45 = d45_date(nd)
    assert d45 == date(2026, 5, 31)


def test_d100_d45_edge_month_boundary() -> None:
    """§6 pg-16: 월말/월초 경계에서 D-100/D-45 계산 정확성."""
    try:
        from app.domains.recipient.service_plan_notice import d45_date, d100_date
    except ImportError:
        _product_absent("W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice")
    # Aug 31 notice → deadline = Feb 28/29 (end of month handling)
    nd = date(2026, 8, 31)
    d100 = d100_date(nd)
    d45 = d45_date(nd)
    assert d100 > nd
    assert d45 > nd
    assert d100 < d45  # D-100 is earlier than D-45


def test_d100_calculation_capped_by_contract_end() -> None:
    """§6 pg-16: 작성마감일이 계약 종료일로 cap될 때 D-100 계산 순수함수 검증."""
    try:
        from app.domains.recipient.service_plan_notice import d100_date, deadline_date
    except ImportError:
        _product_absent(
            "W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice"
        )
    nd = date(2026, 1, 15)
    contract_end = date(2026, 5, 31)
    cert_end = date(2026, 12, 31)
    dl = deadline_date(nd, contract_end_date=contract_end, certification_end_date=cert_end)
    assert dl == date(2026, 5, 31)  # capped by earlier contract_end_date
    d100 = d100_date(nd, contract_end_date=contract_end, certification_end_date=cert_end)
    assert d100 == date(2026, 2, 20)  # deadline(May 31) − 100 days


def test_d45_calculation_capped_by_contract_end() -> None:
    """§6 pg-16: 작성마감일이 계약 종료일로 cap될 때 D-45 계산 순수함수 검증."""
    try:
        from app.domains.recipient.service_plan_notice import d45_date, deadline_date
    except ImportError:
        _product_absent(
            "W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice"
        )
    nd = date(2026, 1, 15)
    contract_end = date(2026, 5, 31)
    cert_end = date(2026, 12, 31)
    dl = deadline_date(nd, contract_end_date=contract_end, certification_end_date=cert_end)
    assert dl == date(2026, 5, 31)  # capped by earlier contract_end_date
    d45 = d45_date(nd, contract_end_date=contract_end, certification_end_date=cert_end)
    assert d45 == date(2026, 4, 16)  # deadline(May 31) − 45 days


def test_deadline_capped_by_earlier_of_two() -> None:
    """§6 pg-16: 인정기간이 계약보다 더 짧을 때 작성마감일 cap 검증."""
    try:
        from app.domains.recipient.service_plan_notice import deadline_date
    except ImportError:
        _product_absent(
            "W2_SERVICE_PLAN_NOTICE_MODULE_MISSING: app.domains.recipient.service_plan_notice"
        )
    nd = date(2026, 1, 15)
    dl = deadline_date(
        nd, contract_end_date=date(2026, 12, 31), certification_end_date=date(2026, 4, 30)
    )
    assert dl == date(2026, 4, 30)  # capped by earlier certification_end_date


# ===========================================================================
# §6 Item 17: PERIOD_FACT 정정
# ===========================================================================


def test_period_fact_correction_invalidate_new_persist_id(
    database_connection: Connection,
) -> None:
    """§6 pg-17: PERIOD_FACT 정정: 무효화+신규+과거 ID 지속.

    W1D/W1E 공통 규칙 — 기존 행 무효화, 새 행 생성, 과거 ID 지속.
    row_version is caller-incremented; this test verifies each step.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)
    fixture = _insert_fixture_data(database_connection)

    original_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    # Read back after insert
    after_insert = database_connection.execute(
        text(
            f"""
            SELECT row_version, created_by_account_id, updated_by_account_id,
                   created_at_utc, updated_at_utc
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id},
    ).one()
    assert after_insert[0] == 1  # row_version after insert
    assert after_insert[1] == fixture.account_id
    assert after_insert[2] == fixture.account_id

    # Invalidate original with explicit row_version increment
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET invalidated_at_utc = now(),
                replacement_service_plan_notice_id = NULL,
                updated_at_utc = clock_timestamp(),
                row_version = row_version + 1,
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id, "account_id": fixture.account_id},
    )

    # Read back after invalidate
    after_invalidate = database_connection.execute(
        text(
            f"""
            SELECT row_version, created_by_account_id, updated_by_account_id,
                   created_at_utc, updated_at_utc, invalidated_at_utc IS NOT NULL
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id},
    ).one()
    assert after_invalidate[0] == 2  # row_version after invalidate
    assert after_invalidate[1] == fixture.account_id  # created_by unchanged
    assert after_invalidate[2] == fixture.account_id  # updated_by is the same account
    assert after_invalidate[5] is True  # invalidated
    # updated_at_utc strictly increased from insert's updated_at_utc
    assert after_invalidate[4] > after_insert[4]

    # Create replacement
    replacement_id = _insert_valid_plan_notice(
        database_connection,
        fixture,
        applied_start_date=date(2026, 1, 1),
        applied_end_date=date(2026, 12, 31),
    )

    # Read back replacement
    replacement_row = database_connection.execute(
        text(
            f"""
            SELECT row_version, created_by_account_id
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": replacement_id},
    ).one()
    assert replacement_row[0] == 1  # new row starts at 1
    assert replacement_row[1] == fixture.account_id

    # Link original → replacement with explicit row_version increment
    database_connection.execute(
        text(
            f"""
            UPDATE {SVC_PLAN_TABLE}
            SET replacement_service_plan_notice_id = :replacement_id,
                updated_at_utc = clock_timestamp(),
                row_version = row_version + 1,
                updated_by_account_id = :account_id
            WHERE id = :plan_id
            """
        ),
        {
            "replacement_id": replacement_id,
            "plan_id": original_id,
            "account_id": fixture.account_id,
        },
    )

    _flush_constraints(database_connection)

    # Read back after linking
    after_link = database_connection.execute(
        text(
            f"""
            SELECT row_version, updated_by_account_id, updated_at_utc,
                   replacement_service_plan_notice_id
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id},
    ).one()
    assert after_link[0] == 3  # row_version after linking
    assert after_link[1] == fixture.account_id
    assert after_link[2] > after_invalidate[4]  # strictly increased from invalidate
    assert after_link[3] == replacement_id

    _flush_constraints(database_connection)

    # Verify: original is invalidated, replacement is valid
    original = database_connection.execute(
        text(
            f"""
            SELECT id, invalidated_at_utc IS NOT NULL,
                   replacement_service_plan_notice_id
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": original_id},
    ).one()
    assert original[0] == original_id  # ID persists
    assert original[1] is True  # Invalidated
    assert original[2] == replacement_id  # Linked to replacement

    replacement = database_connection.execute(
        text(
            f"""
            SELECT id, invalidated_at_utc IS NULL,
                   row_version
            FROM {SVC_PLAN_TABLE} WHERE id = :plan_id
            """
        ),
        {"plan_id": replacement_id},
    ).one()
    assert replacement[0] == replacement_id
    assert replacement[1] is True  # Valid
    assert replacement[2] >= 1  # row_version >= 1


# ===========================================================================
# §6 Item 18: migration 단일 head
# ===========================================================================


def test_single_head_migration_chain(database_connection: Connection) -> None:
    """§6 pg-18: revision chain이 직속 단일 child이며 branching 없음."""
    _require_catalog(database_connection)
    _require_shape(database_connection)

    # Check that the alembic_version table has exactly one row
    count = database_connection.execute(
        text("SELECT count(*) FROM erp.alembic_version")
    ).scalar()
    assert count == 1, "alembic_version must have exactly one row (single head)"

    # Check that the current revision is W2_REVISION
    current = database_connection.execute(
        text("SELECT version_num FROM erp.alembic_version")
    ).scalar_one()
    assert current == W2_REVISION, (
        f"current revision must be {W2_REVISION}, got {current}"
    )


# ===========================================================================
# §6 Item 19: downgrade 완전 복원
# ===========================================================================


def test_downgrade_restores_clean_state(database_connection: Connection) -> None:
    """§6 pg-19: W2_REVISION 존재 확인 — 실제 downgrade 검증은 lifecycle test에서.

    This test verifies the current state at W2_REVISION and asserts that
    all expected objects exist (so that downgrade can remove them).
    The actual downgrade/absence verification is performed by
    test_downgrade_upgrade_downgrade_reupgrade_lifecycle below.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)

    # Verify table exists
    table_exists = database_connection.execute(
        text("SELECT to_regclass(:table) IS NOT NULL"),
        {"table": SVC_PLAN_TABLE},
    ).scalar()
    assert table_exists is True

    # Verify functions exist
    for func_name in (
        "erp.fn_service_plan_notice_within_contract",
        "erp.fn_service_plan_notice_within_certification",
        "erp.fn_service_plan_notice_before_contract_start",
        "erp.fn_recipient_contract_service_plan_reverse_guard",
        "erp.fn_recipient_certification_period_service_plan_reverse_guard",
        "erp.fn_recipient_contract_recipient_id_immutable",
        "erp.fn_recipient_certification_period_recipient_id_immutable",
    ):
        func_exists = database_connection.execute(
            text(
                "SELECT to_regproc(:func) IS NOT NULL"
            ),
            {"func": func_name},
        ).scalar()
        assert func_exists is True, f"function {func_name} must exist"

    # Verify triggers exist on parent tables
    for trigger_name in (
        "ct_recipient_contract_service_plan_reverse_guard",
        "ct_recipient_certification_period_service_plan_reverse_guard",
        "ct_recipient_contract_recipient_id_immutable",
        "ct_recipient_certification_period_recipient_id_immutable",
    ):
        trigger_exists = database_connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = :trigger_name
                )
                """
            ),
            {"trigger_name": trigger_name},
        ).scalar()
        assert trigger_exists is True, f"trigger {trigger_name} must exist"


def test_downgrade_sequence_cleanup(database_connection: Connection) -> None:
    """§6 pg-19: W2_REVISION 시퀀스 존재 확인 — 실제 downgrade 검증은 lifecycle test에서.

    This test verifies the sequence exists at W2_REVISION.
    The actual downgrade/absence verification is performed by
    test_downgrade_upgrade_downgrade_reupgrade_lifecycle below.
    """
    _require_catalog(database_connection)
    _require_shape(database_connection)

    seq_exists = database_connection.execute(
        text(
            "SELECT to_regclass('erp.recipient_service_plan_notice_id_seq') IS NOT NULL"
        )
    ).scalar()
    assert seq_exists is True, (
        "sequence must exist at W2_REVISION; downgrade removes it"
    )


# ===========================================================================
# §6 Item 19: downgrade upgrade-downgrade-reupgrade lifecycle
# ===========================================================================


def test_downgrade_upgrade_downgrade_reupgrade_lifecycle() -> None:
    """Execute real W2_PREV_HEAD→W2_REVISION→W2_PREV_HEAD→W2_REVISION lifecycle.

    Opt-in only:
      SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG=1
      SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_DATABASE_URL=postgresql+psycopg://.../*_test|*_review

    The migration file does not exist yet in Phase 1 — when this opt-in test
    is actually run, it will correctly RED-fail with W2_MIGRATION_MISSING.
    """
    from pathlib import Path

    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.engine.url import make_url

    from app.core.settings import assert_safe_test_database_url, get_settings

    _MIG_OPT_IN = "SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG"
    _MIG_URL_ENV = "SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_DATABASE_URL"

    opt_in_raw = os.environ.get(_MIG_OPT_IN)
    if opt_in_raw is None:
        pytest.skip(
            f"requires {_MIG_OPT_IN}=1 and disposable {_MIG_URL_ENV} "
            "(isolated migration lifecycle harness)"
        )
    if opt_in_raw != "1":
        pytest.fail(
            f"{_MIG_OPT_IN} must be exactly '1' to run the migration lifecycle "
            f"(got {opt_in_raw!r}); use unset to skip as unavailable harness"
        )

    mig_url = os.environ.get(_MIG_URL_ENV)
    if not mig_url:
        pytest.fail(
            f"{_MIG_URL_ENV} is required when {_MIG_OPT_IN}=1 "
            "(must be a disposable database ending in _test or _review)"
        )
    try:
        assert_safe_test_database_url(mig_url)
    except ValueError as exc:
        pytest.fail(f"{_MIG_URL_ENV} is not a disposable test/review database: {exc}")

    def _pg_target_identity(database_url: str) -> tuple[str, int, str]:
        parsed = make_url(database_url)
        host = (parsed.host or "").lower()
        port = int(parsed.port) if parsed.port is not None else 5432
        database = parsed.database or ""
        return (host, port, database)

    rec_list_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if rec_list_url:
        try:
            mig_identity = _pg_target_identity(mig_url)
            app_identity = _pg_target_identity(rec_list_url)
        except Exception as exc:
            pytest.fail(f"unable to normalize database URLs for target comparison: {exc}")
        if mig_identity == app_identity:
            pytest.fail(
                "lifecycle must use a dedicated disposable URL "
                f"({_MIG_URL_ENV}), not the same effective PostgreSQL target as "
                "SSWCENTER_DATABASE_URL "
                f"(host={mig_identity[0]!r} port={mig_identity[1]} db={mig_identity[2]!r})"
            )

    backend_root = Path(__file__).resolve().parents[1]

    def _alembic(target: str, *, direction: str) -> None:
        from alembic.config import Config

        from alembic import command

        previous_url = os.environ.get("SSWCENTER_DATABASE_URL")
        previous_env = os.environ.get("SSWCENTER_ENVIRONMENT")
        old_cwd = os.getcwd()
        try:
            os.environ["SSWCENTER_DATABASE_URL"] = mig_url
            os.environ.setdefault("SSWCENTER_ENVIRONMENT", "development")
            get_settings.cache_clear()
            os.chdir(backend_root)
            cfg = Config(str(backend_root / "alembic.ini"))
            if direction == "upgrade":
                command.upgrade(cfg, target)
            elif direction == "downgrade":
                command.downgrade(cfg, target)
            else:
                raise AssertionError(f"unknown alembic direction {direction}")
        finally:
            os.chdir(old_cwd)
            if previous_url is None:
                os.environ.pop("SSWCENTER_DATABASE_URL", None)
            else:
                os.environ["SSWCENTER_DATABASE_URL"] = previous_url
            if previous_env is None:
                os.environ.pop("SSWCENTER_ENVIRONMENT", None)
            else:
                os.environ["SSWCENTER_ENVIRONMENT"] = previous_env
            get_settings.cache_clear()

    def _revision(connection) -> str | None:
        has_erp = connection.execute(
            text("SELECT to_regclass('erp.alembic_version') IS NOT NULL")
        ).scalar()
        if not has_erp:
            return None
        return connection.execute(
            text("SELECT version_num FROM erp.alembic_version")
        ).scalar()

    engine = _create_engine(mig_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            current = _revision(connection)

        if current is None:
            _alembic(W2_PREV_HEAD, direction="upgrade")
        elif current == W2_REVISION:
            _alembic(W2_PREV_HEAD, direction="downgrade")
        elif current == W2_PREV_HEAD:
            pass
        else:
            pytest.fail(
                "lifecycle disposable DB must start at None, "
                f"{W2_PREV_HEAD}, or {W2_REVISION}; got unexpected revision {current!r}"
            )

        with engine.begin() as connection:
            rev = _revision(connection)
            if rev != W2_PREV_HEAD:
                pytest.fail(
                    f"expected revision {W2_PREV_HEAD} before lifecycle upgrade, got {rev!r}"
                )

        # Upgrade to W2_REVISION
        try:
            _alembic(W2_REVISION, direction="upgrade")
        except Exception as exc:
            # The migration file does not exist yet in Phase 1 — this is the expected RED outcome
            _product_absent("W2_MIGRATION_MISSING_FOR_LIFECYCLE_TEST: " + str(exc))

        with engine.connect() as connection:
            rev = _revision(connection)
            if rev != W2_REVISION:
                pytest.fail(f"upgrade to {W2_REVISION} failed; revision={rev!r}")

            # Assert table exists
            table_exists = connection.execute(
                text("SELECT to_regclass(:table) IS NOT NULL"),
                {"table": SVC_PLAN_TABLE},
            ).scalar()
            assert table_exists is True

            # Assert all 7 functions exist
            for func_name in (
                "erp.fn_service_plan_notice_within_contract",
                "erp.fn_service_plan_notice_within_certification",
                "erp.fn_service_plan_notice_before_contract_start",
                "erp.fn_recipient_contract_service_plan_reverse_guard",
                "erp.fn_recipient_certification_period_service_plan_reverse_guard",
                "erp.fn_recipient_contract_recipient_id_immutable",
                "erp.fn_recipient_certification_period_recipient_id_immutable",
            ):
                func_exists = connection.execute(
                    text("SELECT to_regproc(:func) IS NOT NULL"),
                    {"func": func_name},
                ).scalar()
                assert func_exists is True, f"function {func_name} must exist after upgrade"

            # Assert all triggers exist
            for trigger_name in (
                "ct_service_plan_notice_within_contract",
                "ct_service_plan_notice_within_certification",
                "ct_service_plan_notice_before_contract_start",
                "ct_recipient_contract_service_plan_reverse_guard",
                "ct_recipient_certification_period_service_plan_reverse_guard",
                "ct_recipient_contract_recipient_id_immutable",
                "ct_recipient_certification_period_recipient_id_immutable",
            ):
                trigger_exists = connection.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM pg_trigger
                            WHERE tgname = :trigger_name
                        )
                        """
                    ),
                    {"trigger_name": trigger_name},
                ).scalar()
                assert trigger_exists is True, f"trigger {trigger_name} must exist after upgrade"

        # Downgrade to W2_PREV_HEAD
        _alembic(W2_PREV_HEAD, direction="downgrade")
        with engine.connect() as connection:
            rev = _revision(connection)
            if rev != W2_PREV_HEAD:
                pytest.fail(f"downgrade to {W2_PREV_HEAD} failed; revision={rev!r}")

            # Assert table is absent
            table_gone = connection.execute(
                text("SELECT to_regclass(:table) IS NOT NULL"),
                {"table": SVC_PLAN_TABLE},
            ).scalar()
            assert table_gone is not True, "table must be absent after downgrade"

            # Assert sequence is absent
            seq_gone = connection.execute(
                text("SELECT to_regclass('erp.recipient_service_plan_notice_id_seq') IS NOT NULL")
            ).scalar()
            assert seq_gone is not True, "sequence must be absent after downgrade"

            # Assert all 7 functions are absent
            for func_name in (
                "erp.fn_service_plan_notice_within_contract",
                "erp.fn_service_plan_notice_within_certification",
                "erp.fn_service_plan_notice_before_contract_start",
                "erp.fn_recipient_contract_service_plan_reverse_guard",
                "erp.fn_recipient_certification_period_service_plan_reverse_guard",
                "erp.fn_recipient_contract_recipient_id_immutable",
                "erp.fn_recipient_certification_period_recipient_id_immutable",
            ):
                func_gone = connection.execute(
                    text("SELECT to_regproc(:func) IS NOT NULL"),
                    {"func": func_name},
                ).scalar()
                assert func_gone is not True, f"function {func_name} must be absent after downgrade"

            # Assert all triggers are absent
            for trigger_name in (
                "ct_service_plan_notice_within_contract",
                "ct_service_plan_notice_within_certification",
                "ct_service_plan_notice_before_contract_start",
                "ct_recipient_contract_service_plan_reverse_guard",
                "ct_recipient_certification_period_service_plan_reverse_guard",
                "ct_recipient_contract_recipient_id_immutable",
                "ct_recipient_certification_period_recipient_id_immutable",
            ):
                trigger_gone = connection.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM pg_trigger
                            WHERE tgname = :trigger_name
                        )
                        """
                    ),
                    {"trigger_name": trigger_name},
                ).scalar()
                assert trigger_gone is not True, (
                    f"trigger {trigger_name} must be absent after downgrade"
                )

        # Re-upgrade to W2_REVISION
        _alembic(W2_REVISION, direction="upgrade")
        with engine.connect() as connection:
            rev = _revision(connection)
            if rev != W2_REVISION:
                pytest.fail(f"re-upgrade to {W2_REVISION} failed; revision={rev!r}")

            # Re-assert table exists
            table_back = connection.execute(
                text("SELECT to_regclass(:table) IS NOT NULL"),
                {"table": SVC_PLAN_TABLE},
            ).scalar()
            assert table_back is True, "table must exist after re-upgrade"

    finally:
        engine.dispose()
