"""PostgreSQL integration tests for recipient list manual-tag filtering.

Runs only when an isolated harness exports:
  SSWCENTER_REC_LIST_REAL_PG=1
  SSWCENTER_DATABASE_URL=postgresql+psycopg://...
  SSWCENTER_PIN_PEPPER / SSWCENTER_PIN_LOOKUP_KEY (for account seed if used)

Does not fall back to SSWCENTER_W1D_REAL_PG (old W1D schema may lack recipient_status).

These tests exercise exact recipient_status tag filtering (independent of contract
periods), ALL filter, default ACTIVE backfill/default, PATCH status update,
absence of list_status, and preserved service projection from contracts.

Migration 0015 upgrade/downgrade lifecycle is intentionally NOT run here against
the shared REC-LIST harness DB. Use the dedicated disposable harness in
test_recipient_list_contract.py::test_migration_0015_lifecycle_upgrade_downgrade_reupgrade
(SSWCENTER_REC_STATUS_MIG_PG=1 + SSWCENTER_REC_STATUS_MIG_DATABASE_URL).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import CurrentAccount
from app.domains.recipient.schemas import (
    RecipientListStatusFilter,
    RecipientStatus,
    RecipientUpdateRequest,
)
from app.domains.recipient.service import RecipientService, set_today_seoul

if TYPE_CHECKING:
    from app.domains.recipient.schemas import RecipientListResponse


@dataclass(frozen=True)
class SeededCase:
    label: str
    active_open: int
    active_end_today: int
    active_start_today: int
    no_contract: int
    ended_contract: int
    future_only: int
    invalidated: int
    multi: int
    tag_ended: int
    tag_waiting: int
    account_id: int


pytestmark = pytest.mark.skipif(
    os.environ.get("SSWCENTER_REC_LIST_REAL_PG") != "1",
    reason="requires isolated REC-LIST PostgreSQL harness (SSWCENTER_REC_LIST_REAL_PG=1)",
)

AS_OF = date(2026, 8, 6)


def _database_url() -> str:
    value = os.environ.get("SSWCENTER_DATABASE_URL")
    if not value:
        pytest.fail("SSWCENTER_DATABASE_URL missing for REC-LIST postgres tests")
    return value


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    eng = create_engine(_database_url(), pool_pre_ping=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture(autouse=True)
def _restore_today() -> Iterator[None]:
    set_today_seoul(None)
    yield
    set_today_seoul(None)


def _require_catalog(session: Session) -> dict[str, int]:
    rows = (
        session.execute(
            text(
                """
            SELECT st.code AS type_code, st.id AS type_id
              FROM erp.service_type st
             WHERE st.code IN (
               'HOME_CARE', 'HOME_BATH', 'TEMP_HOME_CARE',
               'HOSPITAL_ESCORT', 'BARO_CARE'
             )
            """
            )
        )
        .mappings()
        .all()
    )
    mapping = {str(row["type_code"]): int(row["type_id"]) for row in rows}
    if set(mapping) != {
        "HOME_CARE",
        "HOME_BATH",
        "TEMP_HOME_CARE",
        "HOSPITAL_ESCORT",
        "BARO_CARE",
    }:
        pytest.skip("service catalog fixture incomplete for REC-LIST ordering tests")
    return mapping


def _require_account_id(session: Session) -> int:
    account_id = session.execute(
        text("SELECT id FROM erp.user_account ORDER BY id ASC LIMIT 1")
    ).scalar()
    if account_id is None:
        pytest.skip("no user_account fixture available for REC-LIST seed")
    return int(account_id)


def _require_recipient_status_column(session: Session) -> None:
    exists = session.execute(
        text(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = 'recipient'
               AND column_name = 'recipient_status'
            """
        )
    ).scalar()
    if exists is None:
        pytest.fail(
            "recipient_status column missing: migration "
            "20260806_0015_recipient_status_tag must be applied "
            "(not silently skipped for this harness)"
        )


def _insert_recipient(
    session: Session,
    *,
    name: str,
    account_id: int,
    recipient_status: str | None = None,
) -> int:
    now = datetime.now(UTC)
    if recipient_status is None:
        # Omit column so server default / backfill path is exercised.
        recipient_id = session.execute(
            text(
                """
                INSERT INTO erp.recipient (
                    name, birth_date, sex_code,
                    created_by_account_id, created_at_utc,
                    updated_by_account_id, updated_at_utc, row_version
                ) VALUES (
                    :name, DATE '1950-01-01', 'MALE',
                    :account_id, :now,
                    :account_id, :now, 1
                )
                RETURNING id
                """
            ),
            {"name": name, "account_id": account_id, "now": now},
        ).scalar_one()
    else:
        recipient_id = session.execute(
            text(
                """
                INSERT INTO erp.recipient (
                    name, birth_date, sex_code, recipient_status,
                    created_by_account_id, created_at_utc,
                    updated_by_account_id, updated_at_utc, row_version
                ) VALUES (
                    :name, DATE '1950-01-01', 'MALE', :recipient_status,
                    :account_id, :now,
                    :account_id, :now, 1
                )
                RETURNING id
                """
            ),
            {
                "name": name,
                "recipient_status": recipient_status,
                "account_id": account_id,
                "now": now,
            },
        ).scalar_one()
    return int(recipient_id)


def _insert_contract(
    session: Session,
    *,
    recipient_id: int,
    service_type_id: int,
    start_date: date,
    end_date: date | None,
    account_id: int,
    invalidated: bool = False,
) -> int:
    now = datetime.now(UTC)
    contract_id = session.execute(
        text(
            """
            INSERT INTO erp.recipient_contract (
                recipient_id, service_type_id, start_date, end_date,
                invalidated_at_utc,
                created_by_account_id, created_at_utc,
                updated_by_account_id, updated_at_utc, row_version
            ) VALUES (
                :recipient_id, :service_type_id, :start_date, :end_date,
                :invalidated_at,
                :account_id, :now,
                :account_id, :now, 1
            )
            RETURNING id
            """
        ),
        {
            "recipient_id": recipient_id,
            "service_type_id": service_type_id,
            "start_date": start_date,
            "end_date": end_date,
            "invalidated_at": now if invalidated else None,
            "account_id": account_id,
            "now": now,
        },
    ).scalar_one()
    return int(contract_id)


@pytest.fixture
def seeded_case(
    session_factory: sessionmaker[Session],
) -> Iterator[SeededCase]:
    label = uuid4().hex[:10]
    set_today_seoul(lambda: AS_OF)
    with session_factory() as session:
        _require_recipient_status_column(session)
        catalog = _require_catalog(session)
        account_id = _require_account_id(session)

        # Default ACTIVE tag + open-ended contract
        active_open = _insert_recipient(session, name=f"RL_A_OPEN_{label}", account_id=account_id)
        _insert_contract(
            session,
            recipient_id=active_open,
            service_type_id=catalog["HOME_CARE"],
            start_date=date(2026, 1, 1),
            end_date=None,
            account_id=account_id,
        )

        active_end_today = _insert_recipient(
            session, name=f"RL_A_END_{label}", account_id=account_id
        )
        _insert_contract(
            session,
            recipient_id=active_end_today,
            service_type_id=catalog["HOME_BATH"],
            start_date=date(2026, 1, 1),
            end_date=AS_OF,
            account_id=account_id,
        )

        active_start_today = _insert_recipient(
            session, name=f"RL_A_START_{label}", account_id=account_id
        )
        _insert_contract(
            session,
            recipient_id=active_start_today,
            service_type_id=catalog["TEMP_HOME_CARE"],
            start_date=AS_OF,
            end_date=None,
            account_id=account_id,
        )

        # ACTIVE tag, no contract (services empty; still ACTIVE filter)
        no_contract = _insert_recipient(session, name=f"RL_A_NONE_{label}", account_id=account_id)

        # ACTIVE tag with ended contract — still ACTIVE by tag, services empty
        ended_contract = _insert_recipient(
            session, name=f"RL_A_ENDED_CT_{label}", account_id=account_id
        )
        _insert_contract(
            session,
            recipient_id=ended_contract,
            service_type_id=catalog["HOME_CARE"],
            start_date=date(2025, 1, 1),
            end_date=date(2026, 8, 5),
            account_id=account_id,
        )

        future_only = _insert_recipient(session, name=f"RL_A_FUTURE_{label}", account_id=account_id)
        _insert_contract(
            session,
            recipient_id=future_only,
            service_type_id=catalog["HOME_CARE"],
            start_date=date(2026, 8, 7),
            end_date=None,
            account_id=account_id,
        )

        invalidated = _insert_recipient(session, name=f"RL_A_INV_{label}", account_id=account_id)
        _insert_contract(
            session,
            recipient_id=invalidated,
            service_type_id=catalog["HOME_CARE"],
            start_date=date(2026, 1, 1),
            end_date=None,
            account_id=account_id,
            invalidated=True,
        )

        multi = _insert_recipient(session, name=f"RL_A_MULTI_{label}", account_id=account_id)
        _insert_contract(
            session,
            recipient_id=multi,
            service_type_id=catalog["HOME_BATH"],
            start_date=date(2026, 1, 1),
            end_date=None,
            account_id=account_id,
        )
        _insert_contract(
            session,
            recipient_id=multi,
            service_type_id=catalog["HOME_CARE"],
            start_date=date(2026, 1, 1),
            end_date=None,
            account_id=account_id,
        )

        # Explicit non-ACTIVE tags with contracts that would have been "active"
        tag_ended = _insert_recipient(
            session,
            name=f"RL_E_TAG_{label}",
            account_id=account_id,
            recipient_status="ENDED",
        )
        _insert_contract(
            session,
            recipient_id=tag_ended,
            service_type_id=catalog["HOME_CARE"],
            start_date=date(2026, 1, 1),
            end_date=None,
            account_id=account_id,
        )
        tag_waiting = _insert_recipient(
            session,
            name=f"RL_W_TAG_{label}",
            account_id=account_id,
            recipient_status="WAITING",
        )
        _insert_contract(
            session,
            recipient_id=tag_waiting,
            service_type_id=catalog["HOME_BATH"],
            start_date=date(2026, 1, 1),
            end_date=None,
            account_id=account_id,
        )

        session.commit()
        case = SeededCase(
            label=label,
            active_open=active_open,
            active_end_today=active_end_today,
            active_start_today=active_start_today,
            no_contract=no_contract,
            ended_contract=ended_contract,
            future_only=future_only,
            invalidated=invalidated,
            multi=multi,
            tag_ended=tag_ended,
            tag_waiting=tag_waiting,
            account_id=account_id,
        )
        try:
            yield case
        finally:
            with session_factory() as cleanup:
                cleanup.execute(
                    text(
                        """
                        DELETE FROM erp.recipient_contract
                         WHERE recipient_id IN (
                            SELECT id FROM erp.recipient
                             WHERE name LIKE :pattern
                         )
                        """
                    ),
                    {"pattern": f"RL_%_{label}"},
                )
                cleanup.execute(
                    text("DELETE FROM erp.recipient WHERE name LIKE :pattern"),
                    {"pattern": f"RL_%_{label}"},
                )
                cleanup.commit()


def _list_for_label(
    session: Session,
    *,
    label: str,
    status: RecipientListStatusFilter,
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
) -> RecipientListResponse:
    service = RecipientService(session)
    return service.list_recipients(
        search=search if search is not None else f"_{label}",
        status=status,
        page=page,
        page_size=page_size,
    )


def test_default_insert_backfills_active_status(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    with session_factory() as session:
        status = session.execute(
            text("SELECT recipient_status FROM erp.recipient WHERE id = :id"),
            {"id": seeded_case.active_open},
        ).scalar_one()
        assert status == "ACTIVE"


def test_exact_tag_filtering_independent_of_contracts(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    label = seeded_case.label
    with session_factory() as session:
        all_resp = _list_for_label(session, label=label, status=RecipientListStatusFilter.ALL)
        all_ids = {item.id for item in all_resp.items}
        assert seeded_case.active_open in all_ids
        assert seeded_case.no_contract in all_ids
        assert seeded_case.ended_contract in all_ids
        assert seeded_case.tag_ended in all_ids
        assert seeded_case.tag_waiting in all_ids
        for item in all_resp.items:
            dumped = item.model_dump()
            assert "list_status" not in dumped
            assert "recipient_status" not in dumped

        active_resp = _list_for_label(session, label=label, status=RecipientListStatusFilter.ACTIVE)
        active_ids = {item.id for item in active_resp.items}
        # ACTIVE tag includes no-contract and ended-contract rows (tag equality).
        assert seeded_case.active_open in active_ids
        assert seeded_case.no_contract in active_ids
        assert seeded_case.ended_contract in active_ids
        assert seeded_case.multi in active_ids
        assert seeded_case.tag_ended not in active_ids
        assert seeded_case.tag_waiting not in active_ids

        ended_resp = _list_for_label(session, label=label, status=RecipientListStatusFilter.ENDED)
        ended_ids = {item.id for item in ended_resp.items}
        assert seeded_case.tag_ended in ended_ids
        assert seeded_case.active_open not in ended_ids
        assert seeded_case.tag_waiting not in ended_ids

        waiting_resp = _list_for_label(
            session, label=label, status=RecipientListStatusFilter.WAITING
        )
        waiting_ids = {item.id for item in waiting_resp.items}
        assert seeded_case.tag_waiting in waiting_ids
        assert seeded_case.no_contract not in waiting_ids
        assert seeded_case.tag_ended not in waiting_ids


def test_service_projection_independent_of_status_tag(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    """ENDED/WAITING tags with effective contracts still project services."""
    label = seeded_case.label
    with session_factory() as session:
        ended = _list_for_label(
            session,
            label=label,
            status=RecipientListStatusFilter.ENDED,
            search=f"RL_E_TAG_{label}",
        )
        assert len(ended.items) == 1
        assert ended.items[0].services
        assert ended.items[0].services[0].service_types[0].service_type_code == "HOME_CARE"

        waiting = _list_for_label(
            session,
            label=label,
            status=RecipientListStatusFilter.WAITING,
            search=f"RL_W_TAG_{label}",
        )
        assert len(waiting.items) == 1
        assert waiting.items[0].services
        assert waiting.items[0].services[0].service_types[0].service_type_code == "HOME_BATH"

        no_ct = _list_for_label(
            session,
            label=label,
            status=RecipientListStatusFilter.ACTIVE,
            search=f"RL_A_NONE_{label}",
        )
        assert len(no_ct.items) == 1
        assert no_ct.items[0].services == []


def test_same_group_multiple_services_catalog_order(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    label = seeded_case.label
    multi_id = seeded_case.multi
    with session_factory() as session:
        response = _list_for_label(
            session,
            label=label,
            status=RecipientListStatusFilter.ACTIVE,
            search=f"RL_A_MULTI_{label}",
        )
        items = [item for item in response.items if item.id == multi_id]
        assert len(items) == 1
        item = items[0]
        assert len(item.services) == 1
        group = item.services[0]
        assert group.service_group_code == "LONG_TERM_CARE"
        assert [svc.service_type_code for svc in group.service_types] == [
            "HOME_CARE",
            "HOME_BATH",
        ]


def test_list_is_read_only_no_plan_notification_or_audit_side_effect(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    label = seeded_case.label
    with session_factory() as session:
        before_notifications = int(
            session.execute(
                text("SELECT COUNT(*) FROM erp.recipient_plan_notification")
            ).scalar_one()
        )
        before_audits = int(
            session.execute(text("SELECT COUNT(*) FROM erp.audit_event")).scalar_one()
        )
        _list_for_label(session, label=label, status=RecipientListStatusFilter.ALL)
        after_notifications = int(
            session.execute(
                text("SELECT COUNT(*) FROM erp.recipient_plan_notification")
            ).scalar_one()
        )
        after_audits = int(
            session.execute(text("SELECT COUNT(*) FROM erp.audit_event")).scalar_one()
        )
        assert after_notifications == before_notifications
        assert after_audits == before_audits


def test_search_and_stable_name_id_ordering(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    label = seeded_case.label
    with session_factory() as session:
        response = _list_for_label(
            session,
            label=label,
            status=RecipientListStatusFilter.ALL,
            search=f"_{label}",
            page=1,
            page_size=100,
        )
        names = [item.name for item in response.items]
        ids = [item.id for item in response.items]
        assert all(name is not None for name in names)
        required_names = [name for name in names if name is not None]
        assert required_names == sorted(required_names)
        paired = list(zip(required_names, ids, strict=True))
        assert paired == sorted(paired, key=lambda pair: (pair[0], pair[1]))
        assert response.total == len(response.items)
        assert all(label in name for name in required_names)


def test_patch_recipient_status_update_and_invalid_status(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    with session_factory() as session:
        service = RecipientService(session)
        account = CurrentAccount(
            id=seeded_case.account_id,
            display_name="test",
            role_code="ADMIN",
        )
        before = service.get_recipient(seeded_case.active_open)
        assert before.recipient_status == RecipientStatus.ACTIVE

        updated = service.update_recipient(
            seeded_case.active_open,
            RecipientUpdateRequest(
                expected_row_version=before.row_version,
                recipient_status=RecipientStatus.ENDED,
            ),
            account,
        )
        assert updated.recipient_status == RecipientStatus.ENDED
        assert updated.row_version == before.row_version + 1

        stored = session.execute(
            text("SELECT recipient_status FROM erp.recipient WHERE id = :id"),
            {"id": seeded_case.active_open},
        ).scalar_one()
        assert stored == "ENDED"

        # List ACTIVE no longer includes this row; ENDED does.
        label = seeded_case.label
        active_ids = {
            item.id
            for item in _list_for_label(
                session, label=label, status=RecipientListStatusFilter.ACTIVE
            ).items
        }
        ended_ids = {
            item.id
            for item in _list_for_label(
                session, label=label, status=RecipientListStatusFilter.ENDED
            ).items
        }
        assert seeded_case.active_open not in active_ids
        assert seeded_case.active_open in ended_ids

        with pytest.raises(ValidationError):
            RecipientUpdateRequest(
                expected_row_version=updated.row_version,
                recipient_status="NOT_A_STATUS",  # type: ignore[arg-type]
            )

        # Restore for cleanup independence of other assertions if any share state
        service.update_recipient(
            seeded_case.active_open,
            RecipientUpdateRequest(
                expected_row_version=updated.row_version,
                recipient_status=RecipientStatus.ACTIVE,
            ),
            account,
        )


def test_contract_period_does_not_change_manual_tag(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    """Moving as_of past contract end leaves ACTIVE tag rows in ACTIVE filter."""
    label = seeded_case.label
    set_today_seoul(lambda: date(2026, 8, 7))
    with session_factory() as session:
        response = _list_for_label(
            session,
            label=label,
            status=RecipientListStatusFilter.ACTIVE,
            search=f"RL_A_END_{label}",
        )
        items = list(response.items)
        assert len(items) == 1
        assert items[0].id == seeded_case.active_end_today
        # Services empty after end; tag still ACTIVE.
        assert items[0].services == []


def test_recipient_status_column_constraints_and_default(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    """Live harness: column NOT NULL, default ACTIVE, check constraint present."""
    with session_factory() as session:
        col = (
            session.execute(
                text(
                    """
                SELECT is_nullable, column_default
                  FROM information_schema.columns
                 WHERE table_schema = 'erp'
                   AND table_name = 'recipient'
                   AND column_name = 'recipient_status'
                """
                )
            )
            .mappings()
            .one()
        )
        assert col["is_nullable"] == "NO"
        assert col["column_default"] is not None
        assert "ACTIVE" in str(col["column_default"])

        check = (
            session.execute(
                text(
                    """
                SELECT conname, pg_get_constraintdef(oid, true) AS definition
                  FROM pg_constraint
                 WHERE conrelid = 'erp.recipient'::regclass
                   AND contype = 'c'
                   AND conname = 'ck_recipient_recipient_status'
                """
                )
            )
            .mappings()
            .one()
        )
        assert check["conname"] == "ck_recipient_recipient_status"
        definition = str(check["definition"])
        assert "ACTIVE" in definition
        assert "ENDED" in definition
        assert "WAITING" in definition

        # Existing seeded rows without explicit status omit path default to ACTIVE.
        status = session.execute(
            text("SELECT recipient_status FROM erp.recipient WHERE id = :id"),
            {"id": seeded_case.no_contract},
        ).scalar_one()
        assert status == "ACTIVE"


def test_list_total_matches_status_predicate_sql_count(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    """Service list total/count must equal SQL count with the same tag predicate."""
    label = seeded_case.label
    with session_factory() as session:
        for status in (
            RecipientListStatusFilter.ALL,
            RecipientListStatusFilter.ACTIVE,
            RecipientListStatusFilter.ENDED,
            RecipientListStatusFilter.WAITING,
        ):
            response = _list_for_label(session, label=label, status=status)
            if status == RecipientListStatusFilter.ALL:
                sql_total = session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM erp.recipient
                         WHERE name LIKE :pattern
                        """
                    ),
                    {"pattern": f"%_{label}"},
                ).scalar_one()
            else:
                sql_total = session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM erp.recipient
                         WHERE name LIKE :pattern
                           AND recipient_status = :status
                        """
                    ),
                    {"pattern": f"%_{label}", "status": status.value},
                ).scalar_one()
            assert response.total == int(sql_total)
            assert (
                len(response.items) == int(sql_total) or len(response.items) <= response.page_size
            )
            if response.total <= response.page_size:
                assert len(response.items) == response.total


def test_patch_rejects_explicit_null_status(
    session_factory: sessionmaker[Session],
    seeded_case: SeededCase,
) -> None:
    with pytest.raises(ValidationError):
        RecipientUpdateRequest.model_validate(
            {
                "expected_row_version": 1,
                "recipient_status": None,
            }
        )
    # Invalid enum still rejected.
    with pytest.raises(ValidationError):
        RecipientUpdateRequest.model_validate(
            {
                "expected_row_version": 1,
                "recipient_status": "NOT_A_STATUS",
            }
        )


def test_migration_0015_present_in_alembic_version_when_column_exists(
    session_factory: sessionmaker[Session],
) -> None:
    """If the column exists, revision head must include 0015 (not an accidental skip)."""
    with session_factory() as session:
        has_column = session.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'erp'
                   AND table_name = 'recipient'
                   AND column_name = 'recipient_status'
                """
            )
        ).scalar()
        assert has_column == 1
        has_erp = session.execute(
            text("SELECT to_regclass('erp.alembic_version') IS NOT NULL")
        ).scalar()
        has_public = session.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar()
        if has_erp:
            revision = session.execute(text("SELECT version_num FROM erp.alembic_version")).scalar()
        elif has_public:
            revision = session.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar()
        else:
            pytest.fail("alembic_version table missing while recipient_status exists")
        assert revision is not None
        # Head may be 0015 itself or a serial descendant (e.g. 0016, 0017) that keeps the column.
        revision_text = str(revision)
        assert (
            "20260806_0015_recipient_status_tag" in revision_text
            or "20260808_0016_recipient_payer_guardian" in revision_text
            or "20260808_0017_recipient_guardian_email" in revision_text
        )


def test_postcheck_0015_source_marker_contract_present() -> None:
    """Source-level (no DB): 0015 postcheck helper + restore marker remain linked.

    Module-level skipif still applies on this file; contract suite owns the full
    pure source assertions. This keeps the postgres allowlist aligned when harness runs.
    """
    from pathlib import Path

    from app.db import postcheck_w1a_vs1 as postcheck_mod

    repo_root = Path(__file__).resolve().parents[2]
    postcheck = repo_root / "backend" / "app" / "db" / "postcheck_w1a_vs1.py"
    source = postcheck.read_text(encoding="utf-8")
    assert 'RECIPIENT_STATUS_TAG_REVISION = "20260806_0015_recipient_status_tag"' in source
    assert "def _verify_recipient_status_tag_contract" in source
    assert 'print("RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK")' in source
    assert "server default must be exactly ACTIVE" in source
    assert "must be validated/convalidated" in source
    assert "must accept exactly" in source
    assert "canonical complete expression" in source
    assert "canonical complete CHECK" in source
    assert "_RECIPIENT_STATUS_CANONICAL_DEFAULTS" in source
    assert "_RECIPIENT_STATUS_CANONICAL_CHECK_DEFS" in source
    # Non-canonical complete expressions must be rejected by allowlist membership.
    normalize = postcheck_mod._normalize_recipient_status_sql
    assert (
        normalize("'ACTIVE'::text OR TRUE")
        not in postcheck_mod._RECIPIENT_STATUS_CANONICAL_DEFAULTS
    )
    assert (
        normalize("CHECK (recipient_status IN ('ACTIVE', 'ENDED', 'WAITING') OR TRUE)")
        not in postcheck_mod._RECIPIENT_STATUS_CANONICAL_CHECK_DEFS
    )
    assert normalize("'ACTIVE'::text") in postcheck_mod._RECIPIENT_STATUS_CANONICAL_DEFAULTS
