"""Real PostgreSQL W2 locking tests.

The module is inert unless a dedicated disposable database is explicitly
exported.  It never falls back to a developer or production URL.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from typing import Protocol, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import CurrentAccount
from app.core.settings import assert_safe_test_database_url
from app.db.w2_models import (
    MonthlyProfessionalAssignment,
    W2OfficialWorkCard,
    W2PersonalTodo,
    W2Schedule,
    W2ScheduleMonthControl,
)
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w2.policies import OfficialCardSource
from app.domains.w2.schemas import (
    OfficialWorkCardCloseRequest,
    OfficialWorkCardKind,
    OfficialWorkCardReassignRequest,
    PersonalTodoCreateRequest,
    PersonalTodoReorderRequest,
    ProfessionalAssignmentCreateRequest,
    ProfessionalAssignmentReplaceRequest,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleFinalizeRequest,
    ScheduleStaffInput,
)
from app.domains.w2.service import W2Service

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_W2_REAL_PG") != "1",
    reason="requires the dedicated W2 disposable PostgreSQL harness",
)

EXPECTED_REVISION = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
SCHEDULE_MONTH = date(2098, 8, 1)


class _ConstraintDiagnostic(Protocol):
    constraint_name: str


class _ConstraintError(Protocol):
    diag: _ConstraintDiagnostic


def _required_url() -> str:
    value = os.getenv("SSWCENTER_W2_DATABASE_URL")
    assert value, "SSWCENTER_W2_DATABASE_URL must be explicitly exported"
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
def seeded(engine: Engine) -> Iterator[dict[str, int | str]]:
    suffix = uuid4().hex
    with engine.begin() as connection:

        def insert_staff(label: str) -> int:
            value = connection.scalar(
                text(
                    """
                    INSERT INTO erp.staff (name, display_name, birth_date, sex_code)
                    VALUES (:name, :name, DATE '1990-01-01', 'TEST')
                    RETURNING id
                    """
                ),
                {"name": f"W2 {label} {suffix}"},
            )
            assert value is not None
            return int(value)

        actor_staff_id = insert_staff("professional actor")
        invalid_staff_id = insert_staff("outside-range worker")
        care_staff_a_id = insert_staff("care worker A")
        care_staff_b_id = insert_staff("care worker B")
        professional_staff_a_id = insert_staff("professional A")
        professional_staff_b_id = insert_staff("professional B")
        current_reassign_staff_id = insert_staff("current reassign target")
        admin_staff_id = insert_staff("admin linked")

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
                "staff_id": actor_staff_id,
                "account_code": f"W2-RACE-{suffix}",
                "display_name": f"W2 race {suffix}",
                "pin_hash": f"unused-{suffix}",
                "pin_lookup_hmac": bytes.fromhex(suffix),
            },
        )
        assert account_id is not None
        account_id = int(account_id)

        admin_account_id = connection.scalar(
            text(
                """
                INSERT INTO erp.user_account (
                    staff_id, account_code, display_name, role_code,
                    pin_hash, pin_lookup_hmac, pin_key_version
                ) VALUES (
                    :staff_id, :account_code, :display_name, 'ADMIN',
                    :pin_hash, :pin_lookup_hmac, 1
                )
                RETURNING id
                """
            ),
            {
                "staff_id": admin_staff_id,
                "account_code": f"W2-ADMIN-{suffix}",
                "display_name": f"W2 admin {suffix}",
                "pin_hash": f"unused-admin-{suffix}",
                "pin_lookup_hmac": bytes.fromhex(suffix[::-1] if len(suffix) == 32 else suffix),
            },
        )
        assert admin_account_id is not None
        admin_account_id = int(admin_account_id)

        next_sequence = connection.scalar(
            text("SELECT COALESCE(MAX(staff_no_sequence), 0) + 1 FROM erp.staff_employment")
        )
        assert next_sequence is not None

        def insert_employment(
            staff_id: int,
            label: str,
            start_date: date,
            end_date: date,
            offset: int,
        ) -> int:
            value = connection.scalar(
                text(
                    """
                    INSERT INTO erp.staff_employment (
                        staff_id, employment_no, staff_no, staff_no_year,
                        staff_no_sequence, start_date, end_date,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :staff_id, 1, :staff_no, 2098, :staff_no_sequence,
                        :start_date, :end_date, :account_id, :account_id
                    ) RETURNING id
                    """
                ),
                {
                    "staff_id": staff_id,
                    "staff_no": f"W2-{label}-{suffix}",
                    "staff_no_sequence": int(next_sequence) + offset,
                    "start_date": start_date,
                    "end_date": end_date,
                    "account_id": account_id,
                },
            )
            assert value is not None
            return int(value)

        actor_employment_id = insert_employment(
            actor_staff_id,
            "ACTOR",
            date(2020, 1, 1),
            date(2099, 12, 31),
            0,
        )
        invalid_employment_id = insert_employment(
            invalid_staff_id,
            "INVALID",
            date(2097, 1, 1),
            date(2097, 12, 31),
            1,
        )
        care_employment_a_id = insert_employment(
            care_staff_a_id,
            "CARE-A",
            date(2098, 1, 1),
            date(2098, 12, 31),
            2,
        )
        care_employment_b_id = insert_employment(
            care_staff_b_id,
            "CARE-B",
            date(2098, 1, 1),
            date(2098, 12, 31),
            3,
        )
        professional_employment_a_id = insert_employment(
            professional_staff_a_id,
            "PRO-A",
            date(2098, 1, 1),
            date(2098, 12, 31),
            4,
        )
        professional_employment_b_id = insert_employment(
            professional_staff_b_id,
            "PRO-B",
            date(2098, 1, 1),
            date(2098, 12, 31),
            5,
        )
        current_reassign_employment_id = insert_employment(
            current_reassign_staff_id,
            "REASSIGN",
            date(2020, 1, 1),
            date(2099, 12, 31),
            6,
        )
        admin_employment_id = insert_employment(
            admin_staff_id,
            "ADMIN",
            date(2020, 1, 1),
            date(2099, 12, 31),
            7,
        )

        def insert_position(
            staff_id: int,
            employment_id: int,
            position_code: str,
            start_date: date,
            end_date: date,
        ) -> None:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_position_period (
                        staff_id, employment_id, position_code, start_date, end_date,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :staff_id, :employment_id, :position_code, :start_date, :end_date,
                        :account_id, :account_id
                    )
                    """
                ),
                {
                    "staff_id": staff_id,
                    "employment_id": employment_id,
                    "position_code": position_code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "account_id": account_id,
                },
            )

        insert_position(
            actor_staff_id,
            actor_employment_id,
            "SOCIAL_WORKER",
            date(2020, 1, 1),
            date(2099, 12, 31),
        )
        insert_position(
            care_staff_a_id,
            care_employment_a_id,
            "CARE_WORKER",
            date(2098, 1, 1),
            date(2098, 12, 31),
        )
        insert_position(
            care_staff_b_id,
            care_employment_b_id,
            "CARE_WORKER",
            date(2098, 1, 1),
            date(2098, 12, 31),
        )
        insert_position(
            professional_staff_a_id,
            professional_employment_a_id,
            "SOCIAL_WORKER",
            date(2098, 1, 1),
            date(2098, 12, 31),
        )
        insert_position(
            professional_staff_b_id,
            professional_employment_b_id,
            "NURSE",
            date(2098, 1, 1),
            date(2098, 12, 31),
        )
        insert_position(
            current_reassign_staff_id,
            current_reassign_employment_id,
            "NURSE",
            date(2020, 1, 1),
            date(2099, 12, 31),
        )
        insert_position(
            admin_staff_id,
            admin_employment_id,
            "SOCIAL_WORKER",
            date(2020, 1, 1),
            date(2099, 12, 31),
        )

        service_type_ids = {
            str(row.code): int(row.id)
            for row in connection.execute(
                text(
                    """
                    SELECT id, code
                      FROM erp.service_type
                     WHERE code IN ('HOME_CARE', 'HOME_BATH')
                    """
                )
            ).mappings()
        }
        assert set(service_type_ids) == {"HOME_CARE", "HOME_BATH"}

        for staff_id, employment_id in (
            (care_staff_a_id, care_employment_a_id),
            (care_staff_b_id, care_employment_b_id),
        ):
            for service_type_id in service_type_ids.values():
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.staff_service_qualification_period (
                            staff_id, employment_id, service_type_id,
                            start_date, end_date, source_license_id,
                            created_by_account_id, updated_by_account_id
                        ) VALUES (
                            :staff_id, :employment_id, :service_type_id,
                            DATE '2098-01-01', DATE '2098-12-31', NULL,
                            :account_id, :account_id
                        )
                        """
                    ),
                    {
                        "staff_id": staff_id,
                        "employment_id": employment_id,
                        "service_type_id": service_type_id,
                        "account_id": account_id,
                    },
                )

        def insert_recipient(label: str) -> int:
            value = connection.scalar(
                text(
                    """
                    INSERT INTO erp.recipient (
                        name, birth_date, sex_code, mobile_phone,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :name, DATE '1950-01-01', 'TEST', :mobile,
                        :account_id, :account_id
                    ) RETURNING id
                    """
                ),
                {
                    "name": f"W2 {label} {suffix}",
                    "mobile": f"010{str(abs(hash(label)))[:8]:0<8}",
                    "account_id": account_id,
                },
            )
            assert value is not None
            return int(value)

        recipient_id = insert_recipient("recipient A")
        recipient_b_id = insert_recipient("recipient B")
        connection.execute(
            text(
                """
                INSERT INTO erp.monthly_professional_assignment (
                    recipient_id, service_month, staff_id, employment_id,
                    start_date, end_date, created_by_account_id, updated_by_account_id
                ) VALUES (
                    :recipient_id, DATE '2026-08-01', :staff_id, :employment_id,
                    DATE '2026-08-01', DATE '2026-08-31', :account_id, :account_id
                )
                """
            ),
            {
                "recipient_id": recipient_id,
                "staff_id": actor_staff_id,
                "employment_id": actor_employment_id,
                "account_id": account_id,
            },
        )

    values: dict[str, int | str] = {
        "suffix": suffix,
        "account_id": account_id,
        "actor_staff_id": actor_staff_id,
        "actor_employment_id": actor_employment_id,
        # Keep the original keys for the range-outside draft test.
        "staff_id": invalid_staff_id,
        "employment_id": invalid_employment_id,
        "care_staff_a_id": care_staff_a_id,
        "care_employment_a_id": care_employment_a_id,
        "care_staff_b_id": care_staff_b_id,
        "care_employment_b_id": care_employment_b_id,
        "professional_staff_a_id": professional_staff_a_id,
        "professional_employment_a_id": professional_employment_a_id,
        "professional_staff_b_id": professional_staff_b_id,
        "professional_employment_b_id": professional_employment_b_id,
        "current_reassign_staff_id": current_reassign_staff_id,
        "current_reassign_employment_id": current_reassign_employment_id,
        "admin_staff_id": admin_staff_id,
        "admin_employment_id": admin_employment_id,
        "admin_account_id": admin_account_id,
        "recipient_id": recipient_id,
        "recipient_b_id": recipient_b_id,
        "service_type_id": service_type_ids["HOME_CARE"],
        "home_care_service_type_id": service_type_ids["HOME_CARE"],
        "home_bath_service_type_id": service_type_ids["HOME_BATH"],
    }
    yield values
    with engine.begin() as connection:
        parameters = values
        connection.execute(
            text(
                """
                DELETE FROM erp.audit_event
                 WHERE actor_account_id = :account_id
                    OR action_code LIKE 'W2_%'
                       AND (
                           entity_pk IN (
                               SELECT id FROM erp.w2_schedule
                                WHERE created_by_account_id = :account_id
                           )
                           OR entity_pk IN (
                               SELECT id FROM erp.w2_official_work_card
                                WHERE created_by_account_id = :account_id
                           )
                       )
                """
            ),
            parameters,
        )
        for statement in (
            "DELETE FROM erp.w2_official_work_card WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.w2_personal_todo WHERE owner_account_id = :account_id",
            "DELETE FROM erp.w2_personal_todo_list WHERE owner_account_id = :account_id",
            "DELETE FROM erp.monthly_professional_assignment "
            "WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.w2_schedule WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.w2_schedule_month_control WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.staff_service_qualification_period "
            "WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.staff_position_period WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.recipient WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.staff_employment WHERE created_by_account_id = :account_id",
            "DELETE FROM erp.user_account WHERE id IN (:account_id, :admin_account_id)",
            "DELETE FROM erp.staff WHERE name LIKE :staff_name_pattern",
        ):
            connection.execute(
                text(statement),
                {**parameters, "staff_name_pattern": f"W2 %{suffix}"},
            )


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _account(seeded: dict[str, int | str]) -> CurrentAccount:
    return CurrentAccount(
        id=int(seeded["account_id"]),
        display_name="W2 PostgreSQL test",
        role_code="USER",
    )


def _admin_account(seeded: dict[str, int | str]) -> CurrentAccount:
    return CurrentAccount(
        id=int(seeded["admin_account_id"]),
        display_name="W2 PostgreSQL admin",
        role_code="ADMIN",
    )


def _assigned_staff(
    seeded: dict[str, int | str],
    label: str,
) -> ScheduleStaffInput:
    assert label in {"care_a", "care_b"}
    suffix = label[-1]
    return ScheduleStaffInput(
        staff_id=int(seeded[f"care_staff_{suffix}_id"]),
        employment_id=int(seeded[f"care_employment_{suffix}_id"]),
    )


def _schedule_payload(
    seeded: dict[str, int | str],
    *,
    schedule_month: date,
    recipient_id: int,
    service_type_id: int,
    assigned_staff: list[ScheduleStaffInput],
    starts_at_utc: datetime,
    ends_at_utc: datetime,
    expected_month_row_version: int,
) -> ScheduleCreateRequest:
    return ScheduleCreateRequest(
        schedule_month=schedule_month,
        recipient_id=recipient_id,
        service_type_id=service_type_id,
        assigned_staff=assigned_staff,
        starts_at_utc=starts_at_utc,
        ends_at_utc=ends_at_utc,
        expected_month_row_version=expected_month_row_version,
    )


def _audit_request_counts(engine: Engine, request_ids: list[UUID]) -> dict[UUID, int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT request_id, count(*)
                  FROM erp.audit_event
                 WHERE request_id = ANY(CAST(:request_ids AS uuid[]))
                 GROUP BY request_id
                """
            ),
            {"request_ids": [str(value) for value in request_ids]},
        ).all()
    return {row[0]: int(row[1]) for row in rows}


def _wait_on_distinct_database_connection(session: Session, barrier: Barrier) -> int:
    backend_pid = session.scalar(text("SELECT pg_backend_pid()"))
    assert backend_pid is not None
    barrier.wait(timeout=10)
    return int(backend_pid)


def _insert_raw_schedule(
    connection: Connection,
    *,
    schedule_month: date,
    recipient_id: int,
    service_type_id: int,
    account_id: int,
    starts_at_utc: datetime,
    ends_at_utc: datetime,
) -> int:
    connection.execute(
        text(
            """
            INSERT INTO erp.w2_schedule_month_control (
                schedule_month, created_by_account_id, updated_by_account_id
            ) VALUES (:schedule_month, :account_id, :account_id)
            ON CONFLICT (schedule_month) DO NOTHING
            """
        ),
        {"schedule_month": schedule_month, "account_id": account_id},
    )
    value = connection.scalar(
        text(
            """
            INSERT INTO erp.w2_schedule (
                schedule_month, recipient_id, service_type_id,
                starts_at_utc, ends_at_utc,
                created_by_account_id, updated_by_account_id
            ) VALUES (
                :schedule_month, :recipient_id, :service_type_id,
                :starts_at_utc, :ends_at_utc,
                :account_id, :account_id
            ) RETURNING id
            """
        ),
        {
            "schedule_month": schedule_month,
            "recipient_id": recipient_id,
            "service_type_id": service_type_id,
            "starts_at_utc": starts_at_utc,
            "ends_at_utc": ends_at_utc,
            "account_id": account_id,
        },
    )
    assert value is not None
    return int(value)


def _insert_raw_schedule_staff(
    connection: Connection,
    *,
    schedule_id: int,
    staff_id: int,
    employment_id: int,
    account_id: int,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO erp.w2_schedule_staff (
                schedule_id, staff_id, employment_id,
                created_by_account_id, updated_by_account_id
            ) VALUES (
                :schedule_id, :staff_id, :employment_id,
                :account_id, :account_id
            )
            """
        ),
        {
            "schedule_id": schedule_id,
            "staff_id": staff_id,
            "employment_id": employment_id,
            "account_id": account_id,
        },
    )


def _card_source(
    seeded: dict[str, int | str],
    *,
    kind: OfficialWorkCardKind,
    occurrence_key: str,
    renewal_key: str,
) -> OfficialCardSource:
    titles = {
        OfficialWorkCardKind.RECOGNITION_EXPIRY: "인정만료",
        OfficialWorkCardKind.CONTRACT_EXPIRY: "계약만료",
        OfficialWorkCardKind.PLAN_NOTICE: "계획서통보",
    }
    return OfficialCardSource(
        kind=kind,
        occurrence_key=occurrence_key,
        renewal_key=renewal_key,
        work_title=titles[kind],
        target_name="W2 카드 대상자",
        detail=f"{titles[kind]} 상세업무",
        due_date=date(2026, 8, 20),
        recipient_id=int(seeded["recipient_id"]),
    )


def test_schedule_staff_cardinality_and_distinctness_have_database_final_defense(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    account_id = int(seeded["account_id"])
    recipient_id = int(seeded["recipient_id"])
    month = date(2098, 1, 1)
    care_a = (
        int(seeded["care_staff_a_id"]),
        int(seeded["care_employment_a_id"]),
    )
    care_b = (
        int(seeded["care_staff_b_id"]),
        int(seeded["care_employment_b_id"]),
    )

    with engine.connect() as connection:
        transaction = connection.begin()
        bath_id = _insert_raw_schedule(
            connection,
            schedule_month=month,
            recipient_id=recipient_id,
            service_type_id=int(seeded["home_bath_service_type_id"]),
            account_id=account_id,
            starts_at_utc=datetime(2098, 1, 5, 1, tzinfo=UTC),
            ends_at_utc=datetime(2098, 1, 5, 2, tzinfo=UTC),
        )
        for staff_id, employment_id in (care_a, care_b):
            _insert_raw_schedule_staff(
                connection,
                schedule_id=bath_id,
                staff_id=staff_id,
                employment_id=employment_id,
                account_id=account_id,
            )
        care_id = _insert_raw_schedule(
            connection,
            schedule_month=month,
            recipient_id=recipient_id,
            service_type_id=int(seeded["home_care_service_type_id"]),
            account_id=account_id,
            starts_at_utc=datetime(2098, 1, 5, 3, tzinfo=UTC),
            ends_at_utc=datetime(2098, 1, 5, 4, tzinfo=UTC),
        )
        _insert_raw_schedule_staff(
            connection,
            schedule_id=care_id,
            staff_id=care_a[0],
            employment_id=care_a[1],
            account_id=account_id,
        )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert (
            connection.scalar(
                text("SELECT count(*) FROM erp.w2_schedule_staff WHERE schedule_id = :schedule_id"),
                {"schedule_id": bath_id},
            )
            == 2
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM erp.w2_schedule_staff WHERE schedule_id = :schedule_id"),
                {"schedule_id": care_id},
            )
            == 1
        )
        transaction.rollback()

    for service_key, workers in (
        ("home_bath_service_type_id", (care_a,)),
        ("home_care_service_type_id", (care_a, care_b)),
    ):
        with engine.connect() as connection:
            transaction = connection.begin()
            schedule_id = _insert_raw_schedule(
                connection,
                schedule_month=month,
                recipient_id=recipient_id,
                service_type_id=int(seeded[service_key]),
                account_id=account_id,
                starts_at_utc=datetime(2098, 1, 6, 1, tzinfo=UTC),
                ends_at_utc=datetime(2098, 1, 6, 2, tzinfo=UTC),
            )
            for staff_id, employment_id in workers:
                _insert_raw_schedule_staff(
                    connection,
                    schedule_id=schedule_id,
                    staff_id=staff_id,
                    employment_id=employment_id,
                    account_id=account_id,
                )
            with pytest.raises(IntegrityError, match="SCHEDULE_STAFF_COUNT_INVALID"):
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        schedule_id = _insert_raw_schedule(
            connection,
            schedule_month=month,
            recipient_id=recipient_id,
            service_type_id=int(seeded["home_bath_service_type_id"]),
            account_id=account_id,
            starts_at_utc=datetime(2098, 1, 7, 1, tzinfo=UTC),
            ends_at_utc=datetime(2098, 1, 7, 2, tzinfo=UTC),
        )
        _insert_raw_schedule_staff(
            connection,
            schedule_id=schedule_id,
            staff_id=care_a[0],
            employment_id=care_a[1],
            account_id=account_id,
        )
        with pytest.raises(IntegrityError) as captured:
            _insert_raw_schedule_staff(
                connection,
                schedule_id=schedule_id,
                staff_id=care_a[0],
                employment_id=care_a[1],
                account_id=account_id,
            )
        assert captured.value.orig is not None
        original = cast(_ConstraintError, captured.value.orig)
        assert original.diag.constraint_name == "uq_w2_schedule_staff_distinct"
        transaction.rollback()


def test_valid_employment_position_and_qualification_allow_month_finalization(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    month = date(2098, 2, 1)
    request_id = uuid4()
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            service = W2Service(session, request_id=request_id)
            draft = service.create_schedule(
                _schedule_payload(
                    seeded,
                    schedule_month=month,
                    recipient_id=int(seeded["recipient_id"]),
                    service_type_id=int(seeded["home_care_service_type_id"]),
                    assigned_staff=[_assigned_staff(seeded, "care_a")],
                    starts_at_utc=datetime(2098, 2, 10, 1, tzinfo=UTC),
                    ends_at_utc=datetime(2098, 2, 10, 2, tzinfo=UTC),
                    expected_month_row_version=1,
                ),
                _account(seeded),
            )
            assert draft.finalized is False
            assert draft.row_version == 2
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

            finalized = service.finalize_schedule_month(
                month,
                ScheduleFinalizeRequest(expected_month_row_version=2),
                _account(seeded),
            )
            assert finalized.finalized is True
            assert finalized.finalized_at_utc is not None
            assert finalized.row_version == 3
            assert len(finalized.items) == 1
            with pytest.raises(RecipientDomainError) as locked_month:
                service.delete_schedule(
                    finalized.items[0].id,
                    ScheduleDeleteRequest(
                        expected_month_row_version=3,
                        expected_row_version=finalized.items[0].row_version,
                    ),
                    _account(seeded),
                )
            assert locked_month.value.code == "SCHEDULE_MONTH_FINALIZED"
            assert locked_month.value.status_code == 423
            assert (
                session.scalar(
                    text(
                        """
                    SELECT count(*)
                     FROM erp.audit_event
                     WHERE request_id = :request_id
                       AND action_code IN (
                           'W2_SCHEDULE_CREATED',
                           'W2_SCHEDULE_MONTH_FINALIZED'
                       )
                    """
                    ),
                    {"request_id": request_id},
                )
                == 2
            )
        finally:
            session.close()
            transaction.rollback()


def test_same_month_first_write_wins_and_loser_gets_latest_snapshot(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    barrier = Barrier(2)
    account = CurrentAccount(
        id=int(seeded["account_id"]),
        display_name="W2 race",
        role_code="USER",
    )

    def write(
        index: int,
    ) -> tuple[str, str | int, dict[str, object] | None, int]:
        with factory() as session:
            service = W2Service(session)
            payload = ScheduleCreateRequest(
                schedule_month=SCHEDULE_MONTH,
                recipient_id=int(seeded["recipient_id"]),
                service_type_id=int(seeded["service_type_id"]),
                assigned_staff=[
                    ScheduleStaffInput(
                        staff_id=int(seeded["staff_id"]),
                        employment_id=int(seeded["employment_id"]),
                    )
                ],
                starts_at_utc=datetime(2098, 8, 3, index * 2, tzinfo=UTC),
                ends_at_utc=datetime(2098, 8, 3, index * 2 + 1, tzinfo=UTC),
                expected_month_row_version=1,
            )
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            try:
                response = service.create_schedule(payload, account)
                return "ok", response.row_version, None, backend_pid
            except RecipientDomainError as exc:
                return "error", exc.code, exc.details, backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, (0, 1)))

    assert len({item[3] for item in results}) == 2
    assert sorted(item[0] for item in results) == ["error", "ok"], results
    winner = next(item for item in results if item[0] == "ok")
    loser = next(item for item in results if item[0] == "error")
    assert winner[1] == 2
    assert loser[1] == "ROW_VERSION_CONFLICT"
    assert loser[2] is not None
    assert loser[2]["current_row_version"] == 2
    assert loser[2]["latest"]["row_version"] == 2  # type: ignore[index]
    assert len(loser[2]["latest"]["items"]) == 1  # type: ignore[index]

    with factory() as session:
        assert (
            session.scalar(
                select(W2ScheduleMonthControl.row_version).where(
                    W2ScheduleMonthControl.schedule_month == SCHEDULE_MONTH
                )
            )
            == 2
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(W2Schedule).where(W2Schedule.schedule_month == SCHEDULE_MONTH)
                    )
                )
            )
            == 1
        )


def test_draft_outside_employment_is_allowed_but_finalize_rechecks_every_row(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    account = CurrentAccount(
        id=int(seeded["account_id"]),
        display_name="W2 race",
        role_code="USER",
    )
    with factory() as session:
        service = W2Service(session)
        with pytest.raises(RecipientDomainError) as captured:
            service.finalize_schedule_month(
                SCHEDULE_MONTH,
                ScheduleFinalizeRequest(expected_month_row_version=2),
                account,
            )
        assert captured.value.code == "SCHEDULE_OUTSIDE_EMPLOYMENT"
        invalid = captured.value.details["invalid_schedules"]
        assert invalid[0]["code"] == "SCHEDULE_OUTSIDE_EMPLOYMENT"

    with factory() as session:
        control = session.get(W2ScheduleMonthControl, SCHEDULE_MONTH)
        assert control is not None
        assert control.finalized_at_utc is None
        assert control.row_version == 2


def test_recipient_and_staff_overlap_are_rejected_by_database_final_defense(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    month = date(2098, 3, 1)
    request_ids = [uuid4(), uuid4(), uuid4()]
    first_payload = _schedule_payload(
        seeded,
        schedule_month=month,
        recipient_id=int(seeded["recipient_id"]),
        service_type_id=int(seeded["home_care_service_type_id"]),
        assigned_staff=[_assigned_staff(seeded, "care_a")],
        starts_at_utc=datetime(2098, 3, 10, 1, tzinfo=UTC),
        ends_at_utc=datetime(2098, 3, 10, 3, tzinfo=UTC),
        expected_month_row_version=1,
    )
    with factory() as session:
        created = W2Service(session, request_id=request_ids[0]).create_schedule(
            first_payload,
            _account(seeded),
        )
        assert created.row_version == 2

    same_recipient_payload = _schedule_payload(
        seeded,
        schedule_month=month,
        recipient_id=int(seeded["recipient_id"]),
        service_type_id=int(seeded["home_care_service_type_id"]),
        assigned_staff=[_assigned_staff(seeded, "care_b")],
        starts_at_utc=datetime(2098, 3, 10, 2, tzinfo=UTC),
        ends_at_utc=datetime(2098, 3, 10, 4, tzinfo=UTC),
        expected_month_row_version=2,
    )
    with factory() as session:
        with pytest.raises(RecipientDomainError) as same_recipient:
            W2Service(session, request_id=request_ids[1]).create_schedule(
                same_recipient_payload,
                _account(seeded),
            )
        assert same_recipient.value.code == "SCHEDULE_OVERLAP"

    same_staff_payload = _schedule_payload(
        seeded,
        schedule_month=month,
        recipient_id=int(seeded["recipient_b_id"]),
        service_type_id=int(seeded["home_care_service_type_id"]),
        assigned_staff=[_assigned_staff(seeded, "care_a")],
        starts_at_utc=datetime(2098, 3, 10, 2, tzinfo=UTC),
        ends_at_utc=datetime(2098, 3, 10, 4, tzinfo=UTC),
        expected_month_row_version=2,
    )
    with factory() as session:
        with pytest.raises(RecipientDomainError) as same_staff:
            W2Service(session, request_id=request_ids[2]).create_schedule(
                same_staff_payload,
                _account(seeded),
            )
        assert same_staff.value.code == "SCHEDULE_OVERLAP"

    with factory() as session:
        control = session.get(W2ScheduleMonthControl, month)
        assert control is not None
        assert control.row_version == 2
        rows = list(session.scalars(select(W2Schedule).where(W2Schedule.schedule_month == month)))
        assert len(rows) == 1

    assert _audit_request_counts(engine, request_ids) == {request_ids[0]: 1}


def test_personal_todo_reorder_race_has_one_winner_no_loser_write_and_atomic_audit(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    revision = 1
    todo_ids: list[int] = []
    for index in range(3):
        with factory() as session:
            response = W2Service(session).create_personal_todo(
                PersonalTodoCreateRequest(
                    title=f"todo-{index}-{seeded['suffix']}",
                    expected_list_revision=revision,
                ),
                _account(seeded),
            )
        revision = response.list_revision
        todo_ids = [item.id for item in response.items]
    assert revision == 4
    assert len(todo_ids) == 3

    requested_orders = (
        [todo_ids[2], todo_ids[1], todo_ids[0]],
        [todo_ids[1], todo_ids[0], todo_ids[2]],
    )
    request_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)

    def reorder(index: int) -> tuple[str, object, UUID, int]:
        with factory() as session:
            service = W2Service(session, request_id=request_ids[index])
            payload = PersonalTodoReorderRequest(
                expected_list_revision=4,
                ordered_ids=requested_orders[index],
            )
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            try:
                response = service.reorder_personal_todos(payload, _account(seeded))
                snapshot = [(item.id, item.sort_order, item.row_version) for item in response.items]
                return "ok", snapshot, request_ids[index], backend_pid
            except RecipientDomainError as exc:
                return "error", exc.code, request_ids[index], backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reorder, (0, 1)))

    assert len({item[3] for item in results}) == 2
    assert sorted(item[0] for item in results) == ["error", "ok"], results
    winner = next(item for item in results if item[0] == "ok")
    loser = next(item for item in results if item[0] == "error")
    assert loser[1] == "TODO_LIST_REVISION_CONFLICT"

    with factory() as session:
        snapshot = W2Service(session).list_personal_todos(_account(seeded))
        assert snapshot.list_revision == 5
        final_rows = [(item.id, item.sort_order, item.row_version) for item in snapshot.items]
        assert final_rows == winner[1]
        assert [item.id for item in snapshot.items] in requested_orders
        database_rows = list(
            session.scalars(
                select(W2PersonalTodo)
                .where(W2PersonalTodo.owner_account_id == int(seeded["account_id"]))
                .order_by(W2PersonalTodo.sort_order, W2PersonalTodo.id)
            )
        )
        assert [row.id for row in database_rows] == [item.id for item in snapshot.items]

    assert _audit_request_counts(engine, request_ids) == {winner[2]: 1}


def test_official_card_occurrence_race_is_idempotent_and_priority_history_is_atomic(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    occurrence = f"w2-occurrence-race-{suffix}"
    renewal = f"w2-renewal-race-{suffix}"
    source = _card_source(
        seeded,
        kind=OfficialWorkCardKind.PLAN_NOTICE,
        occurrence_key=occurrence,
        renewal_key=renewal,
    )
    request_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)

    def record(index: int) -> tuple[int, UUID, int]:
        with factory() as session:
            service = W2Service(session, request_id=request_ids[index])
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            row = service.record_official_source(
                source,
                actor_account_id=int(seeded["account_id"]),
            )
            return row.id, request_ids[index], backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(record, (0, 1)))

    assert len({item[2] for item in results}) == 2
    assert results[0][0] == results[1][0]
    with factory() as session:
        rows = list(
            session.scalars(
                select(W2OfficialWorkCard).where(W2OfficialWorkCard.occurrence_key == occurrence)
            )
        )
        assert len(rows) == 1
        assert rows[0].closed_at_utc is None
    occurrence_audits = _audit_request_counts(engine, request_ids)
    assert sorted(occurrence_audits.values()) == [1]

    priority_renewal = f"w2-priority-{suffix}"
    plan_request_id = uuid4()
    recognition_request_id = uuid4()
    close_request_id = uuid4()
    suppressed_request_id = uuid4()
    plan_source = _card_source(
        seeded,
        kind=OfficialWorkCardKind.PLAN_NOTICE,
        occurrence_key=f"w2-plan-{suffix}",
        renewal_key=priority_renewal,
    )
    recognition_source = _card_source(
        seeded,
        kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
        occurrence_key=f"w2-recognition-{suffix}",
        renewal_key=priority_renewal,
    )
    with factory() as session:
        plan = W2Service(session, request_id=plan_request_id).record_official_source(
            plan_source,
            actor_account_id=int(seeded["account_id"]),
        )
    with factory() as session:
        recognition = W2Service(
            session,
            request_id=recognition_request_id,
        ).record_official_source(
            recognition_source,
            actor_account_id=int(seeded["account_id"]),
        )

    with factory() as session:
        history = list(
            session.scalars(
                select(W2OfficialWorkCard)
                .where(W2OfficialWorkCard.renewal_key == priority_renewal)
                .order_by(W2OfficialWorkCard.id)
            )
        )
        assert [row.kind for row in history] == [
            OfficialWorkCardKind.PLAN_NOTICE.value,
            OfficialWorkCardKind.RECOGNITION_EXPIRY.value,
        ]
        assert history[0].id == plan.id
        assert history[0].closed_at_utc is not None
        assert history[0].closed_by_account_id == int(seeded["account_id"])
        assert history[1].id == recognition.id
        assert history[1].closed_at_utc is None
        assert sum(row.closed_at_utc is None for row in history) == 1

    with factory() as session:
        W2Service(session, request_id=close_request_id).close_official_card(
            recognition.id,
            OfficialWorkCardCloseRequest(expected_row_version=1),
            _account(seeded),
        )
    suppressed_source = _card_source(
        seeded,
        kind=OfficialWorkCardKind.CONTRACT_EXPIRY,
        occurrence_key=f"w2-suppressed-contract-{suffix}",
        renewal_key=priority_renewal,
    )
    with factory() as session:
        returned = W2Service(
            session,
            request_id=suppressed_request_id,
        ).record_official_source(
            suppressed_source,
            actor_account_id=int(seeded["account_id"]),
        )
        assert returned.id == recognition.id
        assert returned.closed_at_utc is not None

    with factory() as session:
        history = list(
            session.scalars(
                select(W2OfficialWorkCard).where(W2OfficialWorkCard.renewal_key == priority_renewal)
            )
        )
        assert len(history) == 2
        assert all(row.closed_at_utc is not None for row in history)
        assert (
            session.scalar(
                select(W2OfficialWorkCard.id).where(
                    W2OfficialWorkCard.occurrence_key == suppressed_source.occurrence_key
                )
            )
            is None
        )

    assert _audit_request_counts(
        engine,
        [
            plan_request_id,
            recognition_request_id,
            close_request_id,
            suppressed_request_id,
        ],
    ) == {
        plan_request_id: 1,
        recognition_request_id: 2,
        close_request_id: 1,
    }


def test_official_card_close_race_has_one_close_and_one_conflict(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    source = _card_source(
        seeded,
        kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
        occurrence_key=f"w2-close-race-{suffix}",
        renewal_key=f"w2-close-renewal-{suffix}",
    )
    with factory() as session:
        card = W2Service(session).record_official_source(
            source,
            actor_account_id=int(seeded["account_id"]),
        )

    request_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)

    def close(index: int) -> tuple[str, str | None, UUID, int]:
        with factory() as session:
            service = W2Service(session, request_id=request_ids[index])
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            try:
                service.close_official_card(
                    card.id,
                    OfficialWorkCardCloseRequest(expected_row_version=1),
                    _account(seeded),
                )
                return "ok", None, request_ids[index], backend_pid
            except RecipientDomainError as exc:
                return "error", exc.code, request_ids[index], backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(close, (0, 1)))

    assert len({item[3] for item in results}) == 2
    assert sorted(item[0] for item in results) == ["error", "ok"], results
    winner = next(item for item in results if item[0] == "ok")
    loser = next(item for item in results if item[0] == "error")
    assert loser[1] == "CARD_ALREADY_CLOSED"
    with factory() as session:
        stored = session.get(W2OfficialWorkCard, card.id)
        assert stored is not None
        assert stored.closed_at_utc is not None
        assert stored.row_version == 2
        assert (
            session.scalar(
                text(
                    """
                SELECT count(*)
                  FROM erp.audit_event
                 WHERE entity_type = 'w2_official_work_card'
                   AND entity_pk = :card_id
                   AND action_code = 'W2_OFFICIAL_WORK_CARD_CLOSED'
                """
                ),
                {"card_id": card.id},
            )
            == 1
        )
    assert _audit_request_counts(engine, request_ids) == {winner[2]: 1}


def test_monthly_professional_midmonth_periods_preserve_replacement_history_and_reject_overlap(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    month = date(2098, 4, 1)
    request_ids = [uuid4(), uuid4(), uuid4(), uuid4()]
    with factory() as session:
        first = W2Service(
            session,
            request_id=request_ids[0],
        ).create_professional_assignment(
            int(seeded["recipient_id"]),
            month,
            ProfessionalAssignmentCreateRequest(
                staff_id=int(seeded["professional_staff_a_id"]),
                employment_id=int(seeded["professional_employment_a_id"]),
                start_date=date(2098, 4, 1),
                end_date=date(2098, 4, 15),
            ),
            _account(seeded),
        )
    with factory() as session:
        second = W2Service(
            session,
            request_id=request_ids[1],
        ).create_professional_assignment(
            int(seeded["recipient_id"]),
            month,
            ProfessionalAssignmentCreateRequest(
                staff_id=int(seeded["professional_staff_b_id"]),
                employment_id=int(seeded["professional_employment_b_id"]),
                start_date=date(2098, 4, 16),
                end_date=date(2098, 4, 30),
            ),
            _account(seeded),
        )
    assert first.end_date < second.start_date

    with factory() as session:
        replacement = W2Service(
            session,
            request_id=request_ids[2],
        ).replace_professional_assignment(
            int(seeded["recipient_id"]),
            month,
            second.id,
            ProfessionalAssignmentReplaceRequest(
                expected_row_version=1,
                staff_id=int(seeded["professional_staff_a_id"]),
                employment_id=int(seeded["professional_employment_a_id"]),
                start_date=date(2098, 4, 16),
                end_date=date(2098, 4, 30),
            ),
            _account(seeded),
        )

    with factory() as session:
        history = (
            W2Service(session)
            .list_professional_assignments(
                int(seeded["recipient_id"]),
                month,
            )
            .items
        )
        assert len(history) == 3
        by_id = {item.id: item for item in history}
        assert by_id[first.id].invalidated_at_utc is None
        assert by_id[second.id].invalidated_at_utc is not None
        assert by_id[second.id].replacement_assignment_id == replacement.id
        assert by_id[second.id].row_version == 2
        assert by_id[replacement.id].invalidated_at_utc is None
        assert [
            (item.start_date, item.end_date) for item in history if item.invalidated_at_utc is None
        ] == [
            (date(2098, 4, 1), date(2098, 4, 15)),
            (date(2098, 4, 16), date(2098, 4, 30)),
        ]

    with factory() as session:
        with pytest.raises(RecipientDomainError) as overlap:
            W2Service(
                session,
                request_id=request_ids[3],
            ).create_professional_assignment(
                int(seeded["recipient_id"]),
                month,
                ProfessionalAssignmentCreateRequest(
                    staff_id=int(seeded["professional_staff_b_id"]),
                    employment_id=int(seeded["professional_employment_b_id"]),
                    start_date=date(2098, 4, 10),
                    end_date=date(2098, 4, 20),
                ),
                _account(seeded),
            )
        assert overlap.value.code == "PROFESSIONAL_ASSIGNMENT_CONFLICT"

    assert _audit_request_counts(engine, request_ids) == {
        request_ids[0]: 1,
        request_ids[1]: 1,
        request_ids[2]: 2,
    }


def test_monthly_professional_overlap_race_has_one_winner_and_one_conflict(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    month = date(2098, 5, 1)
    request_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)
    assignments = (
        (
            int(seeded["professional_staff_a_id"]),
            int(seeded["professional_employment_a_id"]),
        ),
        (
            int(seeded["professional_staff_b_id"]),
            int(seeded["professional_employment_b_id"]),
        ),
    )

    def create(index: int) -> tuple[str, str | int, UUID, int]:
        with factory() as session:
            service = W2Service(session, request_id=request_ids[index])
            staff_id, employment_id = assignments[index]
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            try:
                response = service.create_professional_assignment(
                    int(seeded["recipient_b_id"]),
                    month,
                    ProfessionalAssignmentCreateRequest(
                        staff_id=staff_id,
                        employment_id=employment_id,
                        start_date=date(2098, 5, 1),
                        end_date=date(2098, 5, 31),
                    ),
                    _account(seeded),
                )
                return "ok", response.id, request_ids[index], backend_pid
            except RecipientDomainError as exc:
                return "error", exc.code, request_ids[index], backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, (0, 1)))

    assert len({item[3] for item in results}) == 2
    assert sorted(item[0] for item in results) == ["error", "ok"], results
    winner = next(item for item in results if item[0] == "ok")
    loser = next(item for item in results if item[0] == "error")
    assert loser[1] == "PROFESSIONAL_ASSIGNMENT_CONFLICT"
    with factory() as session:
        rows = list(
            session.scalars(
                select(MonthlyProfessionalAssignment).where(
                    MonthlyProfessionalAssignment.recipient_id == int(seeded["recipient_b_id"]),
                    MonthlyProfessionalAssignment.service_month == month,
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].id == winner[1]
        assert rows[0].invalidated_at_utc is None
    assert _audit_request_counts(engine, request_ids) == {winner[2]: 1}


def test_official_card_uses_dated_monthly_assignment_and_fails_closed_without_unique(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    with factory() as session:
        card = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.PLAN_NOTICE,
                occurrence_key=f"w2-auto-assign-{suffix}",
                renewal_key=f"w2-auto-renewal-{suffix}",
            ),
            actor_account_id=int(seeded["account_id"]),
        )
        assert card.assignee_staff_id == int(seeded["actor_staff_id"])
        listed = W2Service(session).list_official_cards(_account(seeded))
        assert listed.groups[0].items[0].assignee_staff_id == int(seeded["actor_staff_id"])

    missing_source = OfficialCardSource(
        kind=OfficialWorkCardKind.PLAN_NOTICE,
        occurrence_key=f"w2-auto-missing-{suffix}",
        renewal_key=f"w2-auto-missing-renewal-{suffix}",
        work_title="계획서통보",
        target_name="대상",
        detail="담당 없음",
        due_date=date(2026, 8, 20),
        recipient_id=int(seeded["recipient_b_id"]),
    )
    with factory() as session:
        with pytest.raises(RecipientDomainError) as missing:
            W2Service(session).record_official_source(missing_source)
        assert missing.value.code == "CARD_ASSIGNEE_UNRESOLVED"
        session.rollback()
        assert (
            session.scalar(
                select(W2OfficialWorkCard.id).where(
                    W2OfficialWorkCard.occurrence_key == missing_source.occurrence_key
                )
            )
            is None
        )


def test_official_card_uses_source_due_date_at_exact_dated_assignment_boundary(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    """The card's business due date, not request time, selects the assignee."""

    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    recipient_id = int(seeded["recipient_b_id"])
    with factory() as session:
        service = W2Service(session)
        first = service.create_professional_assignment(
            recipient_id,
            date(2026, 8, 1),
            ProfessionalAssignmentCreateRequest(
                staff_id=int(seeded["actor_staff_id"]),
                employment_id=int(seeded["actor_employment_id"]),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 19),
            ),
            _account(seeded),
        )
        second = service.create_professional_assignment(
            recipient_id,
            date(2026, 8, 1),
            ProfessionalAssignmentCreateRequest(
                staff_id=int(seeded["current_reassign_staff_id"]),
                employment_id=int(seeded["current_reassign_employment_id"]),
                start_date=date(2026, 8, 20),
                end_date=date(2026, 8, 31),
            ),
            _account(seeded),
        )
        assert first.end_date == date(2026, 8, 19)
        assert second.start_date == date(2026, 8, 20)

    boundary_source = OfficialCardSource(
        kind=OfficialWorkCardKind.PLAN_NOTICE,
        occurrence_key=f"w2-due-boundary-{suffix}",
        renewal_key=f"w2-due-boundary-renewal-{suffix}",
        work_title="계획서 통보",
        target_name="경계 대상자",
        detail="마감일 기준 담당자 선택",
        due_date=date(2026, 8, 20),
        recipient_id=recipient_id,
    )
    previous_day_source = OfficialCardSource(
        kind=OfficialWorkCardKind.PLAN_NOTICE,
        occurrence_key=f"w2-due-boundary-previous-{suffix}",
        renewal_key=f"w2-due-boundary-previous-renewal-{suffix}",
        work_title="계획서 통보",
        target_name="경계 대상자",
        detail="마감일 전일 담당자 선택",
        due_date=date(2026, 8, 19),
        recipient_id=recipient_id,
    )
    with factory() as session:
        service = W2Service(session)
        at_boundary = service.record_official_source(
            boundary_source,
            actor_account_id=int(seeded["account_id"]),
        )
        before_boundary = service.record_official_source(
            previous_day_source,
            actor_account_id=int(seeded["account_id"]),
        )
        assert at_boundary.due_date == date(2026, 8, 20)
        assert at_boundary.assignee_staff_id == int(seeded["current_reassign_staff_id"])
        assert before_boundary.due_date == date(2026, 8, 19)
        assert before_boundary.assignee_staff_id == int(seeded["actor_staff_id"])


def test_admin_reassignment_success_audit_and_invariants(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    with factory() as session:
        card = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.CONTRACT_EXPIRY,
                occurrence_key=f"w2-reassign-{suffix}",
                renewal_key=f"w2-reassign-renewal-{suffix}",
            ),
            actor_account_id=int(seeded["account_id"]),
        )
        original = (
            card.id,
            card.kind,
            card.due_date,
            card.occurrence_key,
            card.renewal_key,
            card.recipient_id,
            card.work_title,
            card.detail,
            card.closed_at_utc,
        )
        listed = W2Service(session).reassign_official_card(
            card.id,
            OfficialWorkCardReassignRequest(
                expected_row_version=1,
                assignee_staff_id=int(seeded["current_reassign_staff_id"]),
            ),
            _admin_account(seeded),
        )
        stored = session.get(W2OfficialWorkCard, card.id)
        assert stored is not None
        assert stored.assignee_staff_id == int(seeded["current_reassign_staff_id"])
        assert stored.row_version == 2
        assert (
            stored.id,
            stored.kind,
            stored.due_date,
            stored.occurrence_key,
            stored.renewal_key,
            stored.recipient_id,
            stored.work_title,
            stored.detail,
            stored.closed_at_utc,
        ) == original
        assert listed.groups[0].staff_id == int(seeded["current_reassign_staff_id"])
        audit = (
            session.execute(
                text(
                    """
                SELECT actor_account_id, before_json, after_json
                  FROM erp.audit_event
                 WHERE entity_type = 'w2_official_work_card'
                   AND entity_pk = :card_id
                   AND action_code = 'W2_OFFICIAL_WORK_CARD_REASSIGNED'
                """
                ),
                {"card_id": card.id},
            )
            .mappings()
            .one()
        )
        assert int(audit["actor_account_id"]) == int(seeded["admin_account_id"])
        assert audit["before_json"]["assignee_staff_id"] == int(seeded["actor_staff_id"])
        assert audit["after_json"]["assignee_staff_id"] == int(seeded["current_reassign_staff_id"])

        with pytest.raises(RecipientDomainError) as same_assignee:
            W2Service(session).reassign_official_card(
                card.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=2,
                    assignee_staff_id=int(seeded["current_reassign_staff_id"]),
                ),
                _admin_account(seeded),
            )
        assert same_assignee.value.code == "CARD_REASSIGN_SAME_ASSIGNEE"
        session.rollback()
        unchanged = session.get(W2OfficialWorkCard, card.id)
        assert unchanged is not None
        assert unchanged.row_version == 2
        assert unchanged.assignee_staff_id == int(seeded["current_reassign_staff_id"])
        assert (
            session.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM erp.audit_event
                     WHERE entity_type = 'w2_official_work_card'
                       AND entity_pk = :card_id
                       AND action_code = 'W2_OFFICIAL_WORK_CARD_REASSIGNED'
                    """
                ),
                {"card_id": card.id},
            )
            == 1
        )

    with factory() as session:
        with pytest.raises(RecipientDomainError) as user_denied:
            W2Service(session).reassign_official_card(
                card.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=2,
                    assignee_staff_id=int(seeded["actor_staff_id"]),
                ),
                _account(seeded),
            )
        assert user_denied.value.code == "CARD_REASSIGN_FORBIDDEN"
        session.rollback()
        with pytest.raises(RecipientDomainError) as admin_close:
            W2Service(session).close_official_card(
                card.id,
                OfficialWorkCardCloseRequest(expected_row_version=2),
                _admin_account(seeded),
            )
        assert admin_close.value.code == "ADMIN_CARD_MUTATION_FORBIDDEN"
        session.rollback()
        with pytest.raises(RecipientDomainError) as admin_linked:
            W2Service(session).reassign_official_card(
                card.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=2,
                    assignee_staff_id=int(seeded["admin_staff_id"]),
                ),
                _admin_account(seeded),
            )
        assert admin_linked.value.code == "ADMIN_CARD_ASSIGNEE_FORBIDDEN"
        session.rollback()
        with pytest.raises(RecipientDomainError) as not_current:
            W2Service(session).reassign_official_card(
                card.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=2,
                    assignee_staff_id=int(seeded["professional_staff_a_id"]),
                ),
                _admin_account(seeded),
            )
        assert not_current.value.code == "CARD_ASSIGNEE_INELIGIBLE"
        session.rollback()
        with pytest.raises(RecipientDomainError) as care_worker:
            W2Service(session).reassign_official_card(
                card.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=2,
                    assignee_staff_id=int(seeded["care_staff_a_id"]),
                ),
                _admin_account(seeded),
            )
        assert care_worker.value.code == "CARD_ASSIGNEE_INELIGIBLE"
        session.rollback()
        eligible = W2Service(session).list_eligible_assignees(_admin_account(seeded))
        ids = {item.staff_id for item in eligible.items}
        assert int(seeded["actor_staff_id"]) in ids
        assert int(seeded["current_reassign_staff_id"]) in ids
        assert int(seeded["admin_staff_id"]) not in ids
        assert int(seeded["care_staff_a_id"]) not in ids
        W2Service(session).reassign_official_card(
            card.id,
            OfficialWorkCardReassignRequest(
                expected_row_version=2,
                assignee_staff_id=int(seeded["actor_staff_id"]),
            ),
            _admin_account(seeded),
        )
        W2Service(session).close_official_card(
            card.id,
            OfficialWorkCardCloseRequest(expected_row_version=3),
            _account(seeded),
        )
        with pytest.raises(RecipientDomainError) as already_closed:
            W2Service(session).reassign_official_card(
                card.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=4,
                    assignee_staff_id=int(seeded["current_reassign_staff_id"]),
                ),
                _admin_account(seeded),
            )
        assert already_closed.value.code == "CARD_ALREADY_CLOSED"
        assert already_closed.value.details.get("latest") is not None


def test_official_card_reassign_race_has_one_success_and_one_conflict(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    with factory() as session:
        card = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
                occurrence_key=f"w2-reassign-race-{suffix}",
                renewal_key=f"w2-reassign-race-renewal-{suffix}",
            ),
            actor_account_id=int(seeded["account_id"]),
        )

    request_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)

    def reassign(index: int) -> tuple[str, str | None, UUID, int]:
        with factory() as session:
            service = W2Service(session, request_id=request_ids[index])
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            try:
                service.reassign_official_card(
                    card.id,
                    OfficialWorkCardReassignRequest(
                        expected_row_version=1,
                        assignee_staff_id=int(seeded["current_reassign_staff_id"]),
                    ),
                    _admin_account(seeded),
                )
                return "ok", None, request_ids[index], backend_pid
            except RecipientDomainError as exc:
                assert exc.details.get("latest") is not None
                return "error", exc.code, request_ids[index], backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reassign, (0, 1)))

    assert len({item[3] for item in results}) == 2
    assert sorted(item[0] for item in results) == ["error", "ok"], results
    loser = next(item for item in results if item[0] == "error")
    assert loser[1] == "ROW_VERSION_CONFLICT"
    with factory() as session:
        stored = session.get(W2OfficialWorkCard, card.id)
        assert stored is not None
        assert stored.assignee_staff_id == int(seeded["current_reassign_staff_id"])
        assert stored.row_version == 2
        assert stored.kind == OfficialWorkCardKind.RECOGNITION_EXPIRY.value
        assert stored.closed_at_utc is None
        assert (
            session.scalar(
                text(
                    """
                    SELECT count(*)
                      FROM erp.audit_event
                     WHERE entity_type = 'w2_official_work_card'
                       AND entity_pk = :card_id
                       AND action_code = 'W2_OFFICIAL_WORK_CARD_REASSIGNED'
                    """
                ),
                {"card_id": card.id},
            )
            == 1
        )


def test_official_card_reassign_versus_close_race(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    with factory() as session:
        card = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.PLAN_NOTICE,
                occurrence_key=f"w2-reassign-close-{suffix}",
                renewal_key=f"w2-reassign-close-renewal-{suffix}",
            ),
            actor_account_id=int(seeded["account_id"]),
        )

    request_ids = [uuid4(), uuid4()]
    barrier = Barrier(2)

    def mutate(index: int) -> tuple[str, str, str | None, UUID, int]:
        with factory() as session:
            service = W2Service(session, request_id=request_ids[index])
            backend_pid = _wait_on_distinct_database_connection(session, barrier)
            try:
                if index == 0:
                    service.reassign_official_card(
                        card.id,
                        OfficialWorkCardReassignRequest(
                            expected_row_version=1,
                            assignee_staff_id=int(seeded["current_reassign_staff_id"]),
                        ),
                        _admin_account(seeded),
                    )
                    return "ok", "reassign", None, request_ids[index], backend_pid
                service.close_official_card(
                    card.id,
                    OfficialWorkCardCloseRequest(expected_row_version=1),
                    _account(seeded),
                )
                return "ok", "close", None, request_ids[index], backend_pid
            except RecipientDomainError as exc:
                action = "reassign" if index == 0 else "close"
                if exc.status_code == 409:
                    assert exc.details.get("latest") is not None
                return "error", action, exc.code, request_ids[index], backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(mutate, (0, 1)))

    assert len({item[4] for item in results}) == 2
    assert sorted(item[0] for item in results) == ["error", "ok"], results
    winner = next(item for item in results if item[0] == "ok")
    loser = next(item for item in results if item[0] == "error")
    assert loser[2] in {
        "ROW_VERSION_CONFLICT",
        "CARD_ALREADY_CLOSED",
        "CARD_ACCESS_FORBIDDEN",
    }
    with factory() as session:
        stored = session.get(W2OfficialWorkCard, card.id)
        assert stored is not None
        if winner[1] == "close":
            assert stored.closed_at_utc is not None
            assert stored.assignee_staff_id == int(seeded["actor_staff_id"])
        else:
            assert stored.closed_at_utc is None
            assert stored.assignee_staff_id == int(seeded["current_reassign_staff_id"])
        assert stored.row_version == 2


def test_priority_replacement_preserves_manual_reassigned_assignee(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    renewal = f"w2-override-{suffix}"
    with factory() as session:
        plan = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.PLAN_NOTICE,
                occurrence_key=f"w2-override-plan-{suffix}",
                renewal_key=renewal,
            ),
            actor_account_id=int(seeded["account_id"]),
        )
        W2Service(session).reassign_official_card(
            plan.id,
            OfficialWorkCardReassignRequest(
                expected_row_version=1,
                assignee_staff_id=int(seeded["current_reassign_staff_id"]),
            ),
            _admin_account(seeded),
        )
    with factory() as session:
        recognition = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
                occurrence_key=f"w2-override-recognition-{suffix}",
                renewal_key=renewal,
            ),
            actor_account_id=int(seeded["account_id"]),
        )
        assert recognition.assignee_staff_id == int(seeded["current_reassign_staff_id"])
        assert recognition.id != plan.id
        stored_plan = session.get(W2OfficialWorkCard, plan.id)
        assert stored_plan is not None
        assert stored_plan.closed_at_utc is not None
        assert stored_plan.assignee_staff_id == int(seeded["current_reassign_staff_id"])


def test_official_card_http_role_csrf_conflict_and_response_contracts(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    """Exercise FastAPI -> real W2 service -> PostgreSQL, not source strings."""

    from fastapi.testclient import TestClient

    from app.api import dependencies as api_dependencies
    from app.core.settings import get_settings
    from app.main import create_app

    app_database_url = os.environ.get("SSWCENTER_APP_DATABASE_URL")
    assert app_database_url, "W2_0027_HTTP_APP_DATABASE_URL_MISSING"
    previous_database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    previous_environment = os.environ.get("SSWCENTER_ENVIRONMENT")
    os.environ["SSWCENTER_DATABASE_URL"] = app_database_url
    os.environ["SSWCENTER_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    api_dependencies._database_runtime.cache_clear()

    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    with factory() as session:
        card = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.PLAN_NOTICE,
                occurrence_key=f"w2-http-reassign-{suffix}",
                renewal_key=f"w2-http-reassign-renewal-{suffix}",
            ),
            actor_account_id=int(seeded["account_id"]),
        )

    app = create_app()
    active_account = [_admin_account(seeded)]

    def override_current_account() -> CurrentAccount:
        return active_account[0]

    def override_csrf_account() -> CurrentAccount:
        return active_account[0]

    app.dependency_overrides[api_dependencies.get_current_account] = override_current_account
    app.dependency_overrides[api_dependencies.require_csrf] = override_csrf_account
    reassign_path = f"/api/v1/official-work-cards/{card.id}/reassign"
    close_path = f"/api/v1/official-work-cards/{card.id}/close"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            candidates = client.get("/api/v1/official-work-cards/eligible-assignees")
            assert candidates.status_code == 200, candidates.text
            assert {
                "as_of_date",
                "items",
            } <= set(candidates.json())
            assert int(seeded["current_reassign_staff_id"]) in {
                item["staff_id"] for item in candidates.json()["items"]
            }

            same = client.post(
                reassign_path,
                json={
                    "expected_row_version": 1,
                    "assignee_staff_id": int(seeded["actor_staff_id"]),
                },
            )
            assert same.status_code == 422
            assert same.json()["error"]["code"] == "CARD_REASSIGN_SAME_ASSIGNEE"

            admin_close = client.post(close_path, json={"expected_row_version": 1})
            assert admin_close.status_code == 403
            assert admin_close.json()["error"]["code"] == "ADMIN_CARD_MUTATION_FORBIDDEN"

            active_account[0] = _account(seeded)
            user_reassign = client.post(
                reassign_path,
                json={
                    "expected_row_version": 1,
                    "assignee_staff_id": int(seeded["current_reassign_staff_id"]),
                },
            )
            assert user_reassign.status_code == 403
            assert user_reassign.json()["error"]["code"] == "CARD_REASSIGN_FORBIDDEN"

            # Restore the real CSRF dependency while retaining only the real
            # HTTP current-account identity override. Missing and mismatched
            # tokens must both return the public ErrorEnvelope.
            active_account[0] = _admin_account(seeded)
            app.dependency_overrides.pop(api_dependencies.require_csrf, None)
            missing_csrf = client.post(
                reassign_path,
                json={
                    "expected_row_version": 1,
                    "assignee_staff_id": int(seeded["current_reassign_staff_id"]),
                },
            )
            assert missing_csrf.status_code == 403
            assert set(missing_csrf.json()) >= {
                "error",
                "field_errors",
                "details",
                "request_id",
            }
            assert missing_csrf.json()["error"]["code"] == "CSRF_REQUIRED"

            settings = get_settings()
            client.cookies.set(settings.session_cookie_name, "test-session")
            client.cookies.set(settings.csrf_cookie_name, "token.signature")
            mismatched_csrf = client.post(
                reassign_path,
                headers={settings.csrf_header_name: "other-token.signature"},
                json={
                    "expected_row_version": 1,
                    "assignee_staff_id": int(seeded["current_reassign_staff_id"]),
                },
            )
            assert mismatched_csrf.status_code == 403
            assert set(mismatched_csrf.json()) >= {
                "error",
                "field_errors",
                "details",
                "request_id",
            }
            assert mismatched_csrf.json()["error"]["code"] == "CSRF_MISMATCH"
            app.dependency_overrides[api_dependencies.require_csrf] = override_csrf_account

            reassigned = client.post(
                reassign_path,
                json={
                    "expected_row_version": 1,
                    "assignee_staff_id": int(seeded["current_reassign_staff_id"]),
                },
            )
            assert reassigned.status_code == 200, reassigned.text
            response = reassigned.json()
            assert {"as_of_date", "groups"} <= set(response)
            assert response["groups"][0]["items"][0]["assignee_staff_id"] == int(
                seeded["current_reassign_staff_id"]
            )

            stale = client.post(
                reassign_path,
                json={
                    "expected_row_version": 1,
                    "assignee_staff_id": int(seeded["actor_staff_id"]),
                },
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "ROW_VERSION_CONFLICT"
            assert stale.json()["details"]["latest"]

            returned = client.post(
                reassign_path,
                json={
                    "expected_row_version": 2,
                    "assignee_staff_id": int(seeded["actor_staff_id"]),
                },
            )
            assert returned.status_code == 200, returned.text
            active_account[0] = _account(seeded)
            closed = client.post(close_path, json={"expected_row_version": 3})
            assert closed.status_code == 200, closed.text
            active_account[0] = _admin_account(seeded)
            already_closed = client.post(
                reassign_path,
                json={
                    "expected_row_version": 4,
                    "assignee_staff_id": int(seeded["current_reassign_staff_id"]),
                },
            )
            assert already_closed.status_code == 409
            assert already_closed.json()["error"]["code"] == "CARD_ALREADY_CLOSED"
            assert already_closed.json()["details"]["latest"]
    finally:
        app.dependency_overrides.clear()
        if previous_database_url is None:
            os.environ.pop("SSWCENTER_DATABASE_URL", None)
        else:
            os.environ["SSWCENTER_DATABASE_URL"] = previous_database_url
        if previous_environment is None:
            os.environ.pop("SSWCENTER_ENVIRONMENT", None)
        else:
            os.environ["SSWCENTER_ENVIRONMENT"] = previous_environment
        get_settings.cache_clear()
        api_dependencies._database_runtime.cache_clear()


def test_priority_replacement_keeps_manual_override_after_later_admin_link(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    """Only the original reassign request evaluates candidate eligibility."""

    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    renewal = f"w2-later-ineligible-override-{suffix}"
    with factory() as session:
        plan = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.PLAN_NOTICE,
                occurrence_key=f"w2-later-ineligible-plan-{suffix}",
                renewal_key=renewal,
            ),
            actor_account_id=int(seeded["account_id"]),
        )
        W2Service(session).reassign_official_card(
            plan.id,
            OfficialWorkCardReassignRequest(
                expected_row_version=1,
                assignee_staff_id=int(seeded["current_reassign_staff_id"]),
            ),
            _admin_account(seeded),
        )

    linked_admin_account_id: int | None = None
    try:
        with engine.begin() as connection:
            value = connection.scalar(
                text(
                    """
                    INSERT INTO erp.user_account (
                        staff_id, account_code, display_name, role_code,
                        pin_hash, pin_lookup_hmac, pin_key_version
                    ) VALUES (
                        :staff_id, :account_code, :display_name, 'ADMIN',
                        :pin_hash, :pin_lookup_hmac, 1
                    ) RETURNING id
                    """
                ),
                {
                    "staff_id": int(seeded["current_reassign_staff_id"]),
                    "account_code": f"W2-LATER-ADMIN-{suffix}",
                    "display_name": f"W2 later admin {suffix}",
                    "pin_hash": f"unused-later-admin-{suffix}",
                    "pin_lookup_hmac": bytes.fromhex(suffix[8:] + suffix[:8]),
                },
            )
            assert value is not None
            linked_admin_account_id = int(value)

        with factory() as session:
            recognition = W2Service(session).record_official_source(
                _card_source(
                    seeded,
                    kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
                    occurrence_key=f"w2-later-ineligible-recognition-{suffix}",
                    renewal_key=renewal,
                ),
                actor_account_id=int(seeded["account_id"]),
            )
            assert recognition.assignee_staff_id == int(seeded["current_reassign_staff_id"])
            assert recognition.closed_at_utc is None
    finally:
        if linked_admin_account_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM erp.user_account WHERE id = :account_id"),
                    {"account_id": linked_admin_account_id},
                )


def test_reassign_vs_priority_replacement_never_loses_successful_manual_override(
    engine: Engine,
    seeded: dict[str, int | str],
) -> None:
    """Two connections serialize an ADMIN override ahead of priority replacement."""

    factory = _factory(engine)
    suffix = str(seeded["suffix"])
    renewal = f"w2-reassign-priority-race-{suffix}"
    with factory() as session:
        plan = W2Service(session).record_official_source(
            _card_source(
                seeded,
                kind=OfficialWorkCardKind.PLAN_NOTICE,
                occurrence_key=f"w2-reassign-priority-plan-{suffix}",
                renewal_key=renewal,
            ),
            actor_account_id=int(seeded["account_id"]),
        )

    priority_source = _card_source(
        seeded,
        kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
        occurrence_key=f"w2-reassign-priority-recognition-{suffix}",
        renewal_key=renewal,
    )
    locked = Barrier(2, timeout=15)

    def reassign() -> tuple[str, int]:
        with factory() as session:
            # Take the exact renewal-card lock first.  The priority writer is
            # released on a different connection while this transaction owns
            # it, then must observe the committed manual audit/assignee.
            session.scalar(
                select(W2OfficialWorkCard).where(W2OfficialWorkCard.id == plan.id).with_for_update()
            )
            backend_pid = _wait_on_distinct_database_connection(session, locked)
            W2Service(session).reassign_official_card(
                plan.id,
                OfficialWorkCardReassignRequest(
                    expected_row_version=1,
                    assignee_staff_id=int(seeded["current_reassign_staff_id"]),
                ),
                _admin_account(seeded),
            )
            return "reassigned", backend_pid

    def replace_with_priority() -> tuple[str, int, int]:
        with factory() as session:
            backend_pid = _wait_on_distinct_database_connection(session, locked)
            card = W2Service(session).record_official_source(
                priority_source,
                actor_account_id=int(seeded["account_id"]),
            )
            return "replaced", card.assignee_staff_id, backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        reassign_future = executor.submit(reassign)
        priority_future = executor.submit(replace_with_priority)
        reassign_result = reassign_future.result(timeout=20)
        priority_result = priority_future.result(timeout=20)

    assert reassign_result[0] == "reassigned"
    assert priority_result[0] == "replaced"
    assert reassign_result[1] != priority_result[2]
    assert priority_result[1] == int(seeded["current_reassign_staff_id"])
    with factory() as session:
        active = session.scalar(
            select(W2OfficialWorkCard)
            .where(
                W2OfficialWorkCard.renewal_key == renewal,
                W2OfficialWorkCard.closed_at_utc.is_(None),
            )
            .with_for_update()
        )
        assert active is not None
        assert active.kind == OfficialWorkCardKind.RECOGNITION_EXPIRY.value
        assert active.assignee_staff_id == int(seeded["current_reassign_staff_id"])
