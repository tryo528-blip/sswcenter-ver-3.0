"""Real PostgreSQL tests for the corrected writable service-plan ledger."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import CurrentAccount
from app.core.settings import assert_safe_test_database_url
from app.db.models import AuditEvent
from app.db.postcheck_current_0027 import verify_current_0027
from app.db.w2_models import W2ServicePlanNotice
from app.domains.recipient.errors import RecipientDomainError
from app.domains.recipient.service import RecipientService
from app.domains.w2.schemas import (
    ServicePlanNoticeCreateRequest,
    ServicePlanNoticeReplaceRequest,
)
from app.domains.w2.service import W2Service

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_W2_REAL_PG") != "1",
    reason="requires the dedicated W2 disposable PostgreSQL harness",
)

EXPECTED_REVISION = "20260817_0027_w2_official_card_assignee_and_plan_replacement"


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
            assert (
                connection.scalar(text("SELECT version_num FROM erp.alembic_version"))
                == EXPECTED_REVISION
            )
        yield value
    finally:
        value.dispose()


@pytest.fixture(scope="module")
def seeded(
    engine: Engine,
) -> Iterator[tuple[CurrentAccount, Callable[..., tuple[int, int]]]]:
    suffix = uuid4().hex
    with engine.begin() as connection:
        staff_id = int(
            connection.scalar(
                text(
                    """
                    INSERT INTO erp.staff (name, display_name, birth_date, sex_code)
                    VALUES (:name, :name, DATE '1990-01-01', 'TEST')
                    RETURNING id
                    """
                ),
                {"name": f"W2 service plan actor {suffix}"},
            )
        )
        account_id = int(
            connection.scalar(
                text(
                    """
                    INSERT INTO erp.user_account (
                        staff_id, account_code, display_name, role_code,
                        pin_hash, pin_lookup_hmac, pin_key_version
                    ) VALUES (
                        :staff_id, :account_code, :display_name, 'USER',
                        :pin_hash, :pin_lookup_hmac, 1
                    ) RETURNING id
                    """
                ),
                {
                    "staff_id": staff_id,
                    "account_code": f"W2-SPN-{suffix}",
                    "display_name": f"W2 service plan {suffix}",
                    "pin_hash": f"unused-{suffix}",
                    "pin_lookup_hmac": bytes.fromhex(suffix),
                },
            )
        )
        service_type_id = int(
            connection.scalar(text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE'"))
        )

    counter = 0

    def create_case(
        *,
        contract_end: date = date(2027, 12, 31),
        certification_end: date = date(2027, 3, 31),
    ) -> tuple[int, int]:
        nonlocal counter
        counter += 1
        with engine.begin() as connection:
            recipient_id = int(
                connection.scalar(
                    text(
                        """
                        INSERT INTO erp.recipient (
                            name, mobile_phone, created_by_account_id,
                            updated_by_account_id
                        ) VALUES (
                            :name, :mobile, :account_id, :account_id
                        ) RETURNING id
                        """
                    ),
                    {
                        "name": f"W2 plan recipient {counter} {suffix}",
                        "mobile": f"010{counter:08d}",
                        "account_id": account_id,
                    },
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_certification_identity (
                        recipient_id, certification_number,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :recipient_id, :number, :account_id, :account_id
                    )
                    """
                ),
                {
                    "recipient_id": recipient_id,
                    "number": f"L{counter:010d}",
                    "account_id": account_id,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_certification_period (
                        recipient_id, grade_code, start_date, end_date,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :recipient_id, '3', DATE '2026-01-01', :end_date,
                        :account_id, :account_id
                    )
                    """
                ),
                {
                    "recipient_id": recipient_id,
                    "end_date": certification_end,
                    "account_id": account_id,
                },
            )
            contract_id = int(
                connection.scalar(
                    text(
                        """
                        INSERT INTO erp.recipient_contract (
                            recipient_id, service_type_id, start_date, end_date,
                            created_by_account_id, updated_by_account_id
                        ) VALUES (
                            :recipient_id, :service_type_id, DATE '2026-01-01',
                            :end_date, :account_id, :account_id
                        ) RETURNING id
                        """
                    ),
                    {
                        "recipient_id": recipient_id,
                        "service_type_id": service_type_id,
                        "end_date": contract_end,
                        "account_id": account_id,
                    },
                )
            )
        return recipient_id, contract_id

    yield (
        CurrentAccount(
            id=account_id,
            display_name="W2 service plan test",
            role_code="USER",
        ),
        create_case,
    )

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM erp.audit_event WHERE actor_account_id = :account_id"),
            {"account_id": account_id},
        )
        connection.execute(
            text(
                "DELETE FROM erp.w2_service_plan_notice WHERE created_by_account_id = :account_id"
            ),
            {"account_id": account_id},
        )
        for table in (
            "recipient_contract",
            "recipient_certification_period",
            "recipient_certification_identity",
            "recipient",
        ):
            connection.execute(
                text(f"DELETE FROM erp.{table} WHERE created_by_account_id = :account_id"),
                {"account_id": account_id},
            )
        connection.execute(
            text("DELETE FROM erp.user_account WHERE id = :account_id"),
            {"account_id": account_id},
        )
        connection.execute(
            text("DELETE FROM erp.staff WHERE id = :staff_id"),
            {"staff_id": staff_id},
        )


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def test_legacy_plan_notification_is_selectable_but_fail_closed_read_only(
    engine: Engine,
) -> None:
    with engine.connect() as connection:
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        'erp_app', 'erp.recipient_plan_notification', 'SELECT'
                    ),
                    has_table_privilege(
                        'erp_app', 'erp.recipient_plan_notification', 'INSERT'
                    ),
                    has_table_privilege(
                        'erp_app', 'erp.recipient_plan_notification', 'UPDATE'
                    ),
                    has_table_privilege(
                        'erp_app', 'erp.recipient_plan_notification', 'DELETE'
                    ),
                    has_table_privilege(
                        'erp_app', 'erp.recipient_plan_notification', 'TRUNCATE'
                    )
                """
            )
        ).one()
        assert tuple(privileges) == (True, False, False, False, False)
        assert connection.scalar(text("SELECT count(*) FROM erp.recipient_plan_notification")) >= 0

    blocked_statements = (
        "UPDATE erp.recipient_plan_notification SET row_version = row_version WHERE false",
        "DELETE FROM erp.recipient_plan_notification WHERE false",
        "TRUNCATE erp.recipient_plan_notification",
    )
    for statement in blocked_statements:
        with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="RECIPIENT_PLAN_NOTIFICATION_READ_ONLY"):
                connection.execute(text(statement))
            connection.rollback()


def test_default_cap_and_replace_history_are_atomic(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    recipient_id, contract_id = create_case()
    factory = _factory(engine)
    with factory() as session:
        service = W2Service(session)
        created = service.create_service_plan_notice(
            recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_id,
                notification_date=date(2026, 8, 15),
                applied_start_date=date(2026, 9, 1),
            ),
            account,
        )
        assert created.applied_end_date == date(2027, 3, 31)
        replacement = service.replace_service_plan_notice(
            recipient_id,
            created.id,
            ServicePlanNoticeReplaceRequest(
                recipient_contract_id=contract_id,
                notification_date=date(2026, 8, 20),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2027, 2, 28),
                expected_row_version=created.row_version,
            ),
            account,
        )
        history = service.list_service_plan_notices(recipient_id)

    assert replacement.id != created.id
    assert len(history.items) == 2
    assert history.items[0].invalidated_at_utc is not None
    assert history.items[0].replacement_service_plan_notice_id == replacement.id
    assert history.items[1].invalidated_at_utc is None


def test_dashboard_deadline_reads_current_notice_with_parent_caps(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    recipient_id, contract_id = create_case(
        contract_end=date(2027, 1, 31),
        certification_end=date(2026, 12, 31),
    )
    factory = _factory(engine)
    with factory() as session:
        notice = W2Service(session).create_service_plan_notice(
            recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_id,
                notification_date=date(2026, 8, 31),
                applied_start_date=date(2026, 9, 1),
            ),
            account,
        )
        deadline = next(
            item
            for item in RecipientService(session).list_recipient_deadlines().items
            if item.recipient_id == recipient_id and item.kind.value == "PLAN_RENEWAL"
        )

    assert deadline.source_id == notice.id
    assert deadline.source_date == date(2026, 8, 31)
    assert deadline.due_date == date(2026, 12, 31)


def test_outside_parent_rejected_without_partial_write_or_audit(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    recipient_id, contract_id = create_case(
        contract_end=date(2026, 12, 31),
        certification_end=date(2027, 3, 31),
    )
    factory = _factory(engine)
    with factory() as session:
        before_rows = int(
            session.scalar(select(func.count()).select_from(W2ServicePlanNotice)) or 0
        )
        before_audits = int(
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.actor_account_id == account.id,
                    AuditEvent.action_code == "W2_SERVICE_PLAN_NOTICE_CREATED",
                )
            )
            or 0
        )
        with pytest.raises(RecipientDomainError) as exc_info:
            W2Service(session).create_service_plan_notice(
                recipient_id,
                ServicePlanNoticeCreateRequest(
                    recipient_contract_id=contract_id,
                    notification_date=date(2026, 8, 15),
                    applied_start_date=date(2026, 9, 1),
                    applied_end_date=date(2027, 1, 1),
                ),
                account,
            )
        assert exc_info.value.code == "SERVICE_PLAN_OUTSIDE_CONTRACT"
        session.rollback()
        assert session.scalar(select(func.count()).select_from(W2ServicePlanNotice)) == before_rows
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.actor_account_id == account.id,
                    AuditEvent.action_code == "W2_SERVICE_PLAN_NOTICE_CREATED",
                )
            )
            == before_audits
        )


def test_parent_reverse_guard_reads_final_transaction_state(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    recipient_id, contract_id = create_case()
    factory = _factory(engine)
    with factory() as session:
        created = W2Service(session).create_service_plan_notice(
            recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_id,
                notification_date=date(2026, 1, 1),
                applied_start_date=date(2026, 1, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )

    with factory() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "UPDATE erp.recipient_contract SET end_date = DATE '2026-06-30' "
                "WHERE id = :contract_id"
            ),
            {"contract_id": contract_id},
        )
        session.commit()

    with factory() as session:
        assert session.scalar(
            text("SELECT end_date FROM erp.recipient_contract WHERE id = :id"),
            {"id": contract_id},
        ) == date(2027, 12, 31)
        session.execute(
            text(
                "UPDATE erp.w2_service_plan_notice "
                "SET invalidated_at_utc = now(), row_version = row_version + 1 "
                "WHERE id = :notice_id"
            ),
            {"notice_id": created.id},
        )
        session.execute(
            text(
                "UPDATE erp.recipient_contract SET end_date = DATE '2026-06-30' "
                "WHERE id = :contract_id"
            ),
            {"contract_id": contract_id},
        )
        session.commit()


def test_same_version_concurrent_replace_has_one_winner_and_zero_loser_writes(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    recipient_id, contract_id = create_case()
    factory = _factory(engine)
    with factory() as session:
        created = W2Service(session).create_service_plan_notice(
            recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_id,
                notification_date=date(2026, 2, 1),
                applied_start_date=date(2026, 2, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )

    barrier = Barrier(2, timeout=20)

    def worker(day: int) -> tuple[str, str, bool]:
        with factory() as session:
            barrier.wait()
            try:
                W2Service(session).replace_service_plan_notice(
                    recipient_id,
                    created.id,
                    ServicePlanNoticeReplaceRequest(
                        recipient_contract_id=contract_id,
                        notification_date=date(2026, 2, day),
                        applied_start_date=date(2026, 2, 1),
                        applied_end_date=date(2026, 12, 31),
                        expected_row_version=created.row_version,
                    ),
                    account,
                )
                return "SUCCESS", "", False
            except RecipientDomainError as error:
                session.rollback()
                return "CONFLICT", error.code, "latest" in error.details

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(worker, (2, 3)))

    assert [item[0] for item in results] == ["CONFLICT", "SUCCESS"]
    conflict = next(item for item in results if item[0] == "CONFLICT")
    assert conflict[1] == "ROW_VERSION_CONFLICT"
    assert conflict[2] is True
    with factory() as session:
        rows = list(
            session.scalars(
                select(W2ServicePlanNotice).where(
                    W2ServicePlanNotice.recipient_contract_id == contract_id
                )
            )
        )
        replacement_audits = int(
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.actor_account_id == account.id,
                    AuditEvent.action_code == "W2_SERVICE_PLAN_NOTICE_REPLACED",
                    AuditEvent.before_json["id"].as_integer() == created.id,
                )
            )
            or 0
        )
    assert len(rows) == 2
    assert sum(row.invalidated_at_utc is None for row in rows) == 1
    assert replacement_audits == 1


def _insert_second_contract(
    engine: Engine,
    *,
    recipient_id: int,
    account_id: int,
    start_date: date,
    end_date: date,
) -> int:
    with engine.begin() as connection:
        service_type_id = int(
            connection.scalar(text("SELECT id FROM erp.service_type WHERE code = 'HOME_BATH'"))
        )
        return int(
            connection.scalar(
                text(
                    """
                    INSERT INTO erp.recipient_contract (
                        recipient_id, service_type_id, start_date, end_date,
                        created_by_account_id, updated_by_account_id
                    ) VALUES (
                        :recipient_id, :service_type_id, :start_date, :end_date,
                        :account_id, :account_id
                    ) RETURNING id
                    """
                ),
                {
                    "recipient_id": recipient_id,
                    "service_type_id": service_type_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "account_id": account_id,
                },
            )
        )


def test_service_plan_replacement_allows_same_recipient_different_contract(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    recipient_id, first_contract_id = create_case()
    second_contract_id = _insert_second_contract(
        engine,
        recipient_id=recipient_id,
        account_id=account.id,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
    )
    factory = _factory(engine)
    with factory() as session:
        created = W2Service(session).create_service_plan_notice(
            recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=first_contract_id,
                notification_date=date(2026, 8, 15),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )
        replacement = W2Service(session).replace_service_plan_notice(
            recipient_id,
            created.id,
            ServicePlanNoticeReplaceRequest(
                recipient_contract_id=second_contract_id,
                notification_date=date(2026, 8, 20),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
                expected_row_version=created.row_version,
            ),
            account,
        )
        stored = session.get(W2ServicePlanNotice, created.id)
    assert replacement.recipient_contract_id == second_contract_id
    assert replacement.recipient_id == recipient_id
    assert stored is not None
    assert stored.replacement_service_plan_notice_id == replacement.id


def test_service_plan_replacement_blocks_cross_recipient_direct_sql(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    account, create_case = seeded
    first_recipient_id, first_contract_id = create_case()
    second_recipient_id, second_contract_id = create_case()
    factory = _factory(engine)
    with factory() as session:
        first = W2Service(session).create_service_plan_notice(
            first_recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=first_contract_id,
                notification_date=date(2026, 8, 15),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )
        second = W2Service(session).create_service_plan_notice(
            second_recipient_id,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=second_contract_id,
                notification_date=date(2026, 8, 16),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )

    with engine.connect() as connection:
        with pytest.raises(
            IntegrityError,
            match="fk_w2_service_plan_notice_replacement_same_recipient",
        ):
            connection.execute(
                text(
                    """
                    UPDATE erp.w2_service_plan_notice
                       SET replacement_service_plan_notice_id = :target_id,
                           invalidated_at_utc = now(),
                           row_version = row_version + 1
                     WHERE id = :source_id
                    """
                ),
                {"source_id": first.id, "target_id": second.id},
            )
            connection.execute(
                text(
                    "SET CONSTRAINTS "
                    "erp.fk_w2_service_plan_notice_replacement_same_recipient IMMEDIATE"
                )
            )
        connection.rollback()
        linked = connection.scalar(
            text(
                """
                SELECT replacement_service_plan_notice_id
                  FROM erp.w2_service_plan_notice
                 WHERE id = :source_id
                """
            ),
            {"source_id": first.id},
        )
        assert linked is None

    with engine.connect() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    UPDATE erp.recipient_contract
                       SET recipient_id = :other_recipient
                     WHERE id = :contract_id
                    """
                ),
                {
                    "other_recipient": second_recipient_id,
                    "contract_id": first_contract_id,
                },
            )
            connection.commit()
        connection.rollback()
        owner = connection.scalar(
            text("SELECT recipient_id FROM erp.recipient_contract WHERE id = :id"),
            {"id": first_contract_id},
        )
        assert int(owner) == first_recipient_id


def test_composite_replacement_fk_allows_same_recipient_and_defers_final_correction(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    """Exercise the 3A edge through direct SQL, not only the service path."""

    account, create_case = seeded
    recipient_a, contract_a = create_case()
    contract_a_second = _insert_second_contract(
        engine,
        recipient_id=recipient_a,
        account_id=account.id,
        start_date=date(2026, 1, 1),
        end_date=date(2027, 12, 31),
    )
    recipient_b, contract_b = create_case()
    factory = _factory(engine)
    with factory() as session:
        source = W2Service(session).create_service_plan_notice(
            recipient_a,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_a,
                notification_date=date(2026, 8, 1),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )
        target = W2Service(session).create_service_plan_notice(
            recipient_a,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_a_second,
                notification_date=date(2026, 8, 2),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE erp.w2_service_plan_notice
                   SET replacement_service_plan_notice_id = :target_id,
                       invalidated_at_utc = now(),
                       row_version = row_version + 1
                 WHERE id = :source_id
                """
            ),
            {"source_id": source.id, "target_id": target.id},
        )

    # A target or source pair cannot be moved to B while the A -> A replacement
    # edge exists. The constraint is deferred, so force its final-state check.
    with engine.connect() as connection:
        with pytest.raises(
            IntegrityError,
            match="fk_w2_service_plan_notice_replacement_same_recipient",
        ):
            connection.execute(
                text(
                    """
                    UPDATE erp.w2_service_plan_notice
                       SET recipient_id = :recipient_b,
                           recipient_contract_id = :contract_b
                     WHERE id = :target_id
                    """
                ),
                {
                    "recipient_b": recipient_b,
                    "contract_b": contract_b,
                    "target_id": target.id,
                },
            )
            connection.execute(
                text(
                    "SET CONSTRAINTS "
                    "erp.fk_w2_service_plan_notice_replacement_same_recipient IMMEDIATE"
                )
            )
        connection.rollback()

    with engine.connect() as connection:
        with pytest.raises(
            IntegrityError,
            match="fk_w2_service_plan_notice_replacement_same_recipient",
        ):
            connection.execute(
                text(
                    """
                    UPDATE erp.w2_service_plan_notice
                       SET recipient_id = :recipient_b,
                           recipient_contract_id = :contract_b
                     WHERE id = :source_id
                    """
                ),
                {
                    "recipient_b": recipient_b,
                    "contract_b": contract_b,
                    "source_id": source.id,
                },
            )
            connection.execute(
                text(
                    "SET CONSTRAINTS "
                    "erp.fk_w2_service_plan_notice_replacement_same_recipient IMMEDIATE"
                )
            )
        connection.rollback()

    # The same deferred mode intentionally allows a single transaction to move
    # both ends to one recipient-local final state.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE erp.w2_service_plan_notice
                   SET recipient_id = :recipient_b,
                       recipient_contract_id = :contract_b
                 WHERE id IN (:source_id, :target_id)
                """
            ),
            {
                "recipient_b": recipient_b,
                "contract_b": contract_b,
                "source_id": source.id,
                "target_id": target.id,
            },
        )
        connection.execute(
            text(
                "SET CONSTRAINTS erp.fk_w2_service_plan_notice_replacement_same_recipient IMMEDIATE"
            )
        )

    with engine.connect() as connection:
        mismatch_count = connection.scalar(
            text(
                """
                SELECT count(*)
                  FROM erp.w2_service_plan_notice AS source_row
                  JOIN erp.w2_service_plan_notice AS target_row
                    ON target_row.id = source_row.replacement_service_plan_notice_id
                 WHERE source_row.recipient_id IS DISTINCT FROM target_row.recipient_id
                """
            )
        )
        assert mismatch_count == 0


def test_composite_link_vs_target_move_race_has_at_most_one_commit(
    engine: Engine,
    seeded: tuple[CurrentAccount, Callable[..., tuple[int, int]]],
) -> None:
    """Two physical connections cannot commit an orphaned replacement graph."""

    account, create_case = seeded
    recipient_a, contract_a = create_case()
    recipient_b, contract_b = create_case()
    factory = _factory(engine)
    with factory() as session:
        source = W2Service(session).create_service_plan_notice(
            recipient_a,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_a,
                notification_date=date(2026, 8, 3),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )
        target = W2Service(session).create_service_plan_notice(
            recipient_a,
            ServicePlanNoticeCreateRequest(
                recipient_contract_id=contract_a,
                notification_date=date(2026, 8, 4),
                applied_start_date=date(2026, 9, 1),
                applied_end_date=date(2026, 12, 31),
            ),
            account,
        )

    barrier = Barrier(2, timeout=15)

    def mutate(kind: str) -> str:
        with engine.connect() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '3000ms'"))
            barrier.wait()
            try:
                if kind == "link":
                    connection.execute(
                        text(
                            """
                            UPDATE erp.w2_service_plan_notice
                               SET replacement_service_plan_notice_id = :target_id,
                                   invalidated_at_utc = now(),
                                   row_version = row_version + 1
                             WHERE id = :source_id
                            """
                        ),
                        {"source_id": source.id, "target_id": target.id},
                    )
                else:
                    connection.execute(
                        text(
                            """
                            UPDATE erp.w2_service_plan_notice
                               SET recipient_id = :recipient_b,
                                   recipient_contract_id = :contract_b
                             WHERE id = :target_id
                            """
                        ),
                        {
                            "recipient_b": recipient_b,
                            "contract_b": contract_b,
                            "target_id": target.id,
                        },
                    )
                connection.commit()
                return "committed"
            except (DBAPIError, IntegrityError):
                connection.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(mutate, kind) for kind in ("link", "move")]
        results = [future.result(timeout=20) for future in futures]

    assert results.count("committed") <= 1, results
    with engine.connect() as connection:
        mismatch_count = connection.scalar(
            text(
                """
                SELECT count(*)
                  FROM erp.w2_service_plan_notice AS source_row
                  JOIN erp.w2_service_plan_notice AS target_row
                    ON target_row.id = source_row.replacement_service_plan_notice_id
                 WHERE source_row.recipient_id IS DISTINCT FROM target_row.recipient_id
                """
            )
        )
        assert mismatch_count == 0


def test_0027_postcheck_rejects_composite_catalog_regressions(engine: Engine) -> None:
    """Mutation-style catalog checks prove the postcheck is not a text smoke."""

    with engine.connect() as connection:
        verify_current_0027(connection)
        connection.rollback()
        outer = connection.begin()
        try:
            savepoint = connection.begin_nested()
            connection.execute(
                text(
                    """
                    ALTER TABLE erp.w2_service_plan_notice
                    DROP CONSTRAINT fk_w2_service_plan_notice_contract_same_recipient
                    """
                )
            )
            with pytest.raises(SystemExit, match="CURRENT_0027_COMPOSITE_FOREIGN_KEY_MISMATCH"):
                verify_current_0027(connection)
            savepoint.rollback()

            savepoint = connection.begin_nested()
            connection.execute(
                text(
                    """
                    CREATE FUNCTION erp.fn_w2_service_plan_replacement_same_recipient()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        RETURN NEW;
                    END
                    $$
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TRIGGER ct_w2_service_plan_replacement_same_recipient
                    BEFORE UPDATE ON erp.w2_service_plan_notice
                    FOR EACH ROW
                    EXECUTE FUNCTION erp.fn_w2_service_plan_replacement_same_recipient()
                    """
                )
            )
            with pytest.raises(SystemExit, match="CURRENT_0027_OBSOLETE_PROCEDURAL_GUARD_PRESENT"):
                verify_current_0027(connection)
            savepoint.rollback()
        finally:
            outer.rollback()
        verify_current_0027(connection)
