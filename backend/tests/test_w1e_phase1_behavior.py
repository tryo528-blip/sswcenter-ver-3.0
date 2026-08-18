"""Executable W1E service/API behavior tests without weakening PG gates.

The as_of ordering/inclusion tests execute a real SQLAlchemy SQLite query
against the repository projection so they are mutation-sensitive, not
syntax-only.  The service lineage tests use a deterministic fake session and
repository seam; the real PostgreSQL exclusion/trigger path remains gated by
``SSWCENTER_W1E_0026_REAL_PG=1`` in ``test_w1e_0026_postgres.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, NoReturn, cast

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_current_account,
    get_db_session,
    get_w1e_service,
    require_recipient_manage,
    require_recipient_view,
)
from app.core.auth import CurrentAccount
from app.db.models import CareAssignment
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w1e import clock as w1e_clock
from app.domains.w1e.repository import W1ERepository
from app.domains.w1e.schemas import (
    AssignmentKind,
    CareAssignmentCreateRequest,
    CareAssignmentListResponse,
    CareAssignmentReplacementRequest,
    CareAssignmentReplacementResponse,
)
from app.domains.w1e.service import W1EService
from app.main import app

COLLECTION_PATH = "/api/v1/recipients/1/contracts/1/assignments"
ITEM_PATH = "/api/v1/recipients/1/contracts/1/assignments/1"


def _account(account_id: int = 1, role_code: str = "ADMIN") -> CurrentAccount:
    return CurrentAccount(id=account_id, display_name="W1E Test", role_code=role_code)


def _raise_http(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})


@pytest.fixture(autouse=True)
def _reset_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# as_of behavior: real repository query against SQLite
# ---------------------------------------------------------------------------


def _build_as_of_session() -> Session:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS erp")
        metadata = sa.MetaData()
        table = sa.Table(
            "care_assignment",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("recipient_contract_id", sa.Integer, nullable=False),
            sa.Column("staff_id", sa.Integer, nullable=False),
            sa.Column("employment_id", sa.Integer, nullable=False),
            sa.Column("assignment_kind", sa.Text, nullable=False),
            sa.Column("family_relationship_text", sa.Text),
            sa.Column("start_date", sa.Date, nullable=False),
            sa.Column("end_date", sa.Date),
            sa.Column("assignment_period", sa.Text),
            sa.Column("invalidated_at_utc", sa.DateTime),
            sa.Column("replacement_assignment_id", sa.Integer),
            sa.Column("created_by_account_id", sa.Integer, nullable=False),
            sa.Column("created_at_utc", sa.DateTime, nullable=False),
            sa.Column("updated_by_account_id", sa.Integer, nullable=False),
            sa.Column("updated_at_utc", sa.DateTime, nullable=False),
            sa.Column("row_version", sa.Integer, nullable=False),
            schema="erp",
        )
        table.create(connection)
        created_at = datetime(2024, 1, 1, tzinfo=UTC)
        connection.execute(
            table.insert(),
            [
                {
                    "id": 1,
                    "recipient_contract_id": 1,
                    "staff_id": 7,
                    "employment_id": 8,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": date(2024, 1, 1),
                    "end_date": date(2024, 1, 31),
                    "assignment_period": None,
                    "invalidated_at_utc": None,
                    "replacement_assignment_id": None,
                    "created_by_account_id": 1,
                    "created_at_utc": created_at,
                    "updated_by_account_id": 1,
                    "updated_at_utc": created_at,
                    "row_version": 1,
                },
                {
                    "id": 2,
                    "recipient_contract_id": 1,
                    "staff_id": 7,
                    "employment_id": 8,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": date(2024, 1, 15),
                    "end_date": date(2024, 1, 20),
                    "assignment_period": None,
                    "invalidated_at_utc": datetime(2024, 1, 16, tzinfo=UTC),
                    "replacement_assignment_id": None,
                    "created_by_account_id": 1,
                    "created_at_utc": created_at,
                    "updated_by_account_id": 1,
                    "updated_at_utc": created_at,
                    "row_version": 2,
                },
                {
                    "id": 3,
                    "recipient_contract_id": 1,
                    "staff_id": 7,
                    "employment_id": 8,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": date(2024, 2, 1),
                    "end_date": None,
                    "assignment_period": None,
                    "invalidated_at_utc": None,
                    "replacement_assignment_id": None,
                    "created_by_account_id": 1,
                    "created_at_utc": created_at,
                    "updated_by_account_id": 1,
                    "updated_at_utc": created_at,
                    "row_version": 1,
                },
                {
                    "id": 4,
                    "recipient_contract_id": 1,
                    "staff_id": 7,
                    "employment_id": 8,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": date(2024, 3, 1),
                    "end_date": date(2024, 3, 31),
                    "assignment_period": None,
                    "invalidated_at_utc": None,
                    "replacement_assignment_id": None,
                    "created_by_account_id": 1,
                    "created_at_utc": created_at,
                    "updated_by_account_id": 1,
                    "updated_at_utc": created_at,
                    "row_version": 1,
                },
                {
                    "id": 5,
                    "recipient_contract_id": 1,
                    "staff_id": 7,
                    "employment_id": 8,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": date(2024, 1, 1),
                    "end_date": date(2024, 12, 31),
                    "assignment_period": None,
                    "invalidated_at_utc": None,
                    "replacement_assignment_id": None,
                    "created_by_account_id": 1,
                    "created_at_utc": created_at,
                    "updated_by_account_id": 1,
                    "updated_at_utc": created_at,
                    "row_version": 1,
                },
            ],
        )
    return Session(engine)


def test_w1e_repository_as_of_is_inclusive_and_history_ordered() -> None:
    session = _build_as_of_session()
    try:
        repo = W1ERepository(session)

        assert [row.id for row in repo.list_assignments(1)] == [1, 2, 3, 4, 5]
        assert [row.id for row in repo.list_assignments(1, as_of=date(2024, 1, 1))] == [
            5,
            1,
        ]
        assert [row.id for row in repo.list_assignments(1, as_of=date(2024, 1, 31))] == [
            5,
            1,
        ]
        assert [row.id for row in repo.list_assignments(1, as_of=date(2024, 2, 15))] == [
            3,
            5,
        ]
        assert [row.id for row in repo.list_assignments(1, as_of=date(2024, 12, 31))] == [
            3,
            5,
        ]
        assert [row.id for row in repo.list_assignments(1, as_of=date(2025, 1, 1))] == [
            3,
        ]
    finally:
        session.close()


def test_w1e_service_as_of_uses_repository_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _build_as_of_session()
    service = W1EService(session)
    monkeypatch.setattr(
        service.repo,
        "get_contract",
        lambda recipient_id, contract_id: SimpleNamespace(
            id=contract_id,
            recipient_id=recipient_id,
            invalidated_at_utc=None,
        ),
    )
    try:
        response = service.list_assignments(1, 1, as_of=date(2024, 2, 15))
        assert [item.id for item in response.items] == [3, 5]

        history = service.list_assignments(1, 1)
        assert [item.id for item in history.items] == [1, 2, 3, 4, 5]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# service lineage/conflict behavior
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.added: list[CareAssignment] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self._next_id = 100

    def add(self, obj: CareAssignment) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flush_calls += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def in_transaction(self) -> bool:
        return False


class _IntegritySession(_FakeSession):
    def __init__(self, original: Any) -> None:
        super().__init__()
        self._original = original

    def flush(self) -> None:
        raise IntegrityError("INSERT", {}, self._original)


class _OperationalSession(_FakeSession):
    def __init__(self, original: Any) -> None:
        super().__init__()
        self._original = original

    def flush(self) -> None:
        raise OperationalError("INSERT", {}, self._original)


class _FakeRepository:
    def __init__(
        self,
        *,
        contract: Any,
        employment: Any,
        assignment: CareAssignment | None,
        overlaps: bool = False,
        position_covers: bool = True,
        qualification_covers: bool = True,
    ) -> None:
        self.contract = contract
        self.employment = employment
        self.assignment = assignment
        self.overlaps = overlaps
        self.position_covers = position_covers
        self.qualification_is_covered = qualification_covers
        self.audits: list[dict[str, Any]] = []

    @property
    def audit_actions(self) -> list[str]:
        return [str(item["action_code"]) for item in self.audits]

    def get_contract_for_update(self, recipient_id: int, contract_id: int) -> Any:
        del recipient_id, contract_id
        return self.contract

    def get_contract(self, recipient_id: int, contract_id: int) -> Any:
        del recipient_id, contract_id
        return self.contract

    def get_assignment(
        self,
        contract_id: int,
        assignment_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> CareAssignment | None:
        del for_update
        row = self.assignment
        if row is None or row.id != assignment_id or row.recipient_contract_id != contract_id:
            return None
        if active_only and row.invalidated_at_utc is not None:
            return None
        return row

    def get_employment(self, staff_id: int, employment_id: int) -> Any:
        del staff_id, employment_id
        return self.employment

    def assignment_overlaps_active(
        self,
        *,
        contract_id: int,
        staff_id: int,
        start_date: date,
        end_date: date | None,
        exclude_assignment_id: int | None = None,
    ) -> bool:
        del contract_id, staff_id, start_date, end_date, exclude_assignment_id
        return self.overlaps

    def care_worker_position_covers(
        self,
        *,
        staff_id: int,
        employment_id: int,
        start_date: date,
        end_date: date | None,
    ) -> bool:
        del staff_id, employment_id, start_date, end_date
        return self.position_covers

    def qualification_covers(
        self,
        *,
        staff_id: int,
        employment_id: int,
        service_type_id: int,
        start_date: date,
        end_date: date | None,
    ) -> bool:
        del staff_id, employment_id, service_type_id, start_date, end_date
        return self.qualification_is_covered

    def append_audit(
        self,
        *,
        action_code: str,
        entity_type: str,
        entity_pk: int | None,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
        reason_code: str | None,
        **kwargs: Any,
    ) -> None:
        del kwargs
        self.audits.append(
            {
                "action_code": action_code,
                "entity_type": entity_type,
                "entity_pk": entity_pk,
                "before_json": before_json,
                "after_json": after_json,
                "reason_code": reason_code,
            }
        )


def _contract() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        recipient_id=1,
        start_date=date(2024, 1, 1),
        end_date=None,
        invalidated_at_utc=None,
        service_type_id=20,
    )


def _employment() -> SimpleNamespace:
    return SimpleNamespace(
        id=8,
        staff_id=7,
        start_date=date(2024, 1, 1),
        end_date=None,
    )


def _care_assignment(**overrides: Any) -> CareAssignment:
    values: dict[str, Any] = {
        "id": 1,
        "recipient_contract_id": 1,
        "staff_id": 7,
        "employment_id": 8,
        "assignment_kind": "GENERAL",
        "family_relationship_text": None,
        "start_date": date(2024, 1, 1),
        "end_date": None,
        "invalidated_at_utc": None,
        "replacement_assignment_id": None,
        "created_by_account_id": 1,
        "created_at_utc": datetime(2024, 1, 1, tzinfo=UTC),
        "updated_by_account_id": 1,
        "updated_at_utc": datetime(2024, 1, 1, tzinfo=UTC),
        "row_version": 1,
    }
    values.update(overrides)
    return CareAssignment(**values)


def _create_payload() -> CareAssignmentCreateRequest:
    return CareAssignmentCreateRequest(
        staff_id=7,
        employment_id=8,
        assignment_kind=AssignmentKind.GENERAL,
        start_date=date(2024, 2, 1),
        end_date=None,
    )


def _replacement_payload(expected_row_version: int = 1) -> CareAssignmentReplacementRequest:
    return CareAssignmentReplacementRequest(
        staff_id=7,
        employment_id=8,
        assignment_kind=AssignmentKind.GENERAL,
        start_date=date(2024, 3, 1),
        end_date=None,
        expected_row_version=expected_row_version,
    )


def _service(session: _FakeSession, repo: _FakeRepository) -> W1EService:
    service = W1EService(cast(Session, session))
    service.repo = cast(W1ERepository, repo)
    return service


def test_w1e_service_create_is_active_fact_and_prevalidation_conflict_is_422() -> None:
    session = _FakeSession()
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=None,
    )
    service = _service(session, repo)

    response = service.create_assignment(
        1,
        1,
        _create_payload(),
        _account(),
    )
    assert response.id == 100
    assert response.invalidated_at_utc is None
    assert response.replacement_assignment_id is None
    assert response.row_version == 1
    assert isinstance(session.added[0], CareAssignment)
    assert session.commit_calls == 1
    assert repo.audits == [
        {
            "action_code": "CARE_ASSIGNMENT_CREATE",
            "entity_type": "CARE_ASSIGNMENT",
            "entity_pk": response.id,
            "before_json": None,
            "after_json": response.model_dump(mode="json"),
            "reason_code": "USER_CREATE",
        }
    ]
    assert repo.audits[0]["after_json"]["start_date"] == "2024-02-01"
    assert repo.audits[0]["after_json"]["staff_id"] == 7

    repo.overlaps = True
    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(
            1,
            1,
            _create_payload(),
            _account(),
        )
    assert excinfo.value.code == "CARE_ASSIGNMENT_PERIOD_CONFLICT"
    assert excinfo.value.status_code == 422


def test_w1e_service_replacement_preserves_lineage_and_row_version() -> None:
    session = _FakeSession()
    old = _care_assignment()
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=old,
    )
    service = _service(session, repo)
    now = datetime(2024, 2, 15, tzinfo=UTC)
    w1e_clock.set_now_utc(now)
    try:
        response = service.replace_assignment(
            1,
            1,
            old.id,
            _replacement_payload(),
            _account(),
        )
    finally:
        w1e_clock.set_now_utc(None)

    assert old.invalidated_at_utc == now
    assert old.updated_at_utc == now
    assert old.row_version == 2
    assert old.replacement_assignment_id == 100

    assert response.original.id == old.id
    assert response.original.row_version == 2
    assert response.original.invalidated_at_utc == now
    assert response.replacement.id == 100
    assert response.replacement.invalidated_at_utc is None
    assert response.replacement.replacement_assignment_id is None
    assert response.replacement.row_version == 1
    assert session.commit_calls == 1
    assert repo.audits[0]["action_code"] == "CARE_ASSIGNMENT_REPLACE"
    assert repo.audits[0]["entity_type"] == "CARE_ASSIGNMENT"
    assert repo.audits[0]["entity_pk"] == old.id
    assert repo.audits[0]["reason_code"] == "USER_REPLACE"
    assert repo.audits[0]["before_json"] is not None
    assert repo.audits[0]["before_json"]["row_version"] == 1
    assert repo.audits[0]["before_json"]["invalidated_at_utc"] is None
    assert repo.audits[0]["before_json"]["replacement_assignment_id"] is None
    assert repo.audits[0]["after_json"] == response.original.model_dump(mode="json")
    assert repo.audits[0]["before_json"] != repo.audits[0]["after_json"]
    assert repo.audits[1] == {
        "action_code": "CARE_ASSIGNMENT_REPLACEMENT_CREATE",
        "entity_type": "CARE_ASSIGNMENT",
        "entity_pk": response.replacement.id,
        "before_json": None,
        "after_json": response.replacement.model_dump(mode="json"),
        "reason_code": "USER_REPLACE",
    }
    assert repo.audits[1]["after_json"]["start_date"] == "2024-03-01"
    assert repo.audit_actions == [
        "CARE_ASSIGNMENT_REPLACE",
        "CARE_ASSIGNMENT_REPLACEMENT_CREATE",
    ]


def test_w1e_service_batch_deferred_commit_flushes_without_commit() -> None:
    session = _FakeSession()
    session.info["recipient_detail_batch_defer_commit"] = True
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=None,
    )
    service = _service(session, repo)

    response = service.create_assignment(
        1,
        1,
        _create_payload(),
        _account(),
    )
    assert response.id == 100
    assert response.row_version == 1
    assert session.flush_calls >= 1
    assert session.commit_calls == 0
    assert repo.audit_actions == ["CARE_ASSIGNMENT_CREATE"]


def test_w1e_service_batch_deferred_flush_maps_lock_loss_and_guard_race() -> None:
    class _LockLoss:
        sqlstate = "55P03"
        diag = SimpleNamespace(
            constraint_name="",
            sqlstate="55P03",
            message_primary="CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
        )

        def __str__(self) -> str:
            return "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"

    class _GuardRace:
        sqlstate = "23514"
        diag = SimpleNamespace(
            constraint_name="",
            sqlstate="23514",
            message_primary="CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
        )

        def __str__(self) -> str:
            return "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD"

    for session in (_OperationalSession(_LockLoss()), _IntegritySession(_GuardRace())):
        session.info["recipient_detail_batch_defer_commit"] = True
        repo = _FakeRepository(
            contract=_contract(),
            employment=_employment(),
            assignment=None,
        )
        service = _service(session, repo)
        with pytest.raises(RecipientDomainError) as excinfo:
            service.create_assignment(1, 1, _create_payload(), _account())
        assert excinfo.value.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
        assert excinfo.value.status_code == 409
        assert session.commit_calls == 0
        assert session.rollback_calls >= 1
        assert repo.audit_actions == []


def test_w1e_service_stale_and_invalidated_row_replacements_are_409() -> None:
    session = _FakeSession()
    old = _care_assignment()
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=old,
    )
    service = _service(session, repo)

    with pytest.raises(RecipientDomainError) as excinfo:
        service.replace_assignment(
            1,
            1,
            old.id,
            _replacement_payload(expected_row_version=2),
            _account(),
        )
    assert excinfo.value.code == "ROW_VERSION_CONFLICT"
    assert excinfo.value.status_code == 409
    assert old.invalidated_at_utc is None
    assert old.replacement_assignment_id is None
    assert old.row_version == 1

    old.invalidated_at_utc = datetime(2024, 2, 1, tzinfo=UTC)
    with pytest.raises(RecipientDomainError) as excinfo:
        service.replace_assignment(
            1,
            1,
            old.id,
            _replacement_payload(expected_row_version=1),
            _account(),
        )
    assert excinfo.value.code == "ROW_VERSION_CONFLICT"
    assert excinfo.value.status_code == 409
    assert old.row_version == 1


def test_w1e_service_rejects_outside_employment_and_contract_periods() -> None:
    session = _FakeSession()
    repo = _FakeRepository(
        contract=_contract(),
        employment=SimpleNamespace(
            id=8,
            staff_id=7,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        ),
        assignment=None,
    )
    service = _service(session, repo)

    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(1, 1, _create_payload(), _account())
    assert excinfo.value.code == "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD"
    assert excinfo.value.status_code == 422
    assert session.commit_calls == 0
    assert repo.audit_actions == []

    repo.employment = _employment()
    repo.contract = SimpleNamespace(
        id=1,
        recipient_id=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        invalidated_at_utc=None,
        service_type_id=20,
    )
    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(1, 1, _create_payload(), _account())
    assert excinfo.value.code == "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD"
    assert excinfo.value.status_code == 422
    assert session.commit_calls == 0
    assert repo.audit_actions == []


def test_w1e_service_general_staff_ineligible_is_422() -> None:
    session = _FakeSession()
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=None,
        position_covers=False,
    )
    service = _service(session, repo)

    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(1, 1, _create_payload(), _account())
    assert excinfo.value.code == "CARE_ASSIGNMENT_STAFF_INELIGIBLE"
    assert excinfo.value.status_code == 422
    assert session.commit_calls == 0
    assert repo.audit_actions == []

    repo.position_covers = True
    repo.qualification_is_covered = False
    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(1, 1, _create_payload(), _account())
    assert excinfo.value.code == "CARE_ASSIGNMENT_STAFF_INELIGIBLE"
    assert excinfo.value.status_code == 422
    assert session.commit_calls == 0
    assert repo.audit_actions == []


def test_w1e_service_family_create_requires_relationship_and_is_422() -> None:
    session = _FakeSession()
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=None,
    )
    service = _service(session, repo)
    for blank in ("   ", "\f", "\v", "\t\n\r\f\v"):
        payload = CareAssignmentCreateRequest(
            staff_id=7,
            employment_id=8,
            assignment_kind=AssignmentKind.FAMILY,
            family_relationship_text=blank,
            start_date=date(2024, 2, 1),
            end_date=None,
        )

        with pytest.raises(RecipientDomainError) as excinfo:
            service.create_assignment(1, 1, payload, _account())
        assert excinfo.value.code == "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED"
        assert excinfo.value.status_code == 422
        assert session.commit_calls == 0
        assert repo.audit_actions == []


def test_w1e_service_maps_sqlstate_23p01_to_409_concurrent_conflict() -> None:
    class _Original:
        diag = None
        sqlstate = "23P01"

    session = _IntegritySession(_Original())
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=None,
    )
    service = _service(session, repo)

    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(
            1,
            1,
            _create_payload(),
            _account(),
        )
    assert excinfo.value.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert excinfo.value.status_code == 409
    assert session.rollback_calls == 1


def test_w1e_service_maps_sqlstate_40p01_to_409_concurrent_conflict() -> None:
    class _Original:
        diag = None
        sqlstate = "40P01"

    session = _OperationalSession(_Original())
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=None,
    )
    service = _service(session, repo)

    with pytest.raises(RecipientDomainError) as excinfo:
        service.create_assignment(
            1,
            1,
            _create_payload(),
            _account(),
        )
    assert excinfo.value.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert excinfo.value.status_code == 409
    assert session.rollback_calls == 1


def test_w1e_service_create_replace_have_no_consultation_or_card_side_effects() -> None:
    session = _FakeSession()
    old = _care_assignment()
    repo = _FakeRepository(
        contract=_contract(),
        employment=_employment(),
        assignment=old,
    )
    service = _service(session, repo)

    service.create_assignment(1, 1, _create_payload(), _account())
    service.replace_assignment(
        1,
        1,
        old.id,
        _replacement_payload(),
        _account(),
    )

    assert all(isinstance(obj, CareAssignment) for obj in session.added)
    assert [item["entity_type"] for item in repo.audits] == [
        "CARE_ASSIGNMENT",
        "CARE_ASSIGNMENT",
        "CARE_ASSIGNMENT",
    ]
    assert repo.audit_actions == [
        "CARE_ASSIGNMENT_CREATE",
        "CARE_ASSIGNMENT_REPLACE",
        "CARE_ASSIGNMENT_REPLACEMENT_CREATE",
    ]
    assert repo.audits[0]["before_json"] is None
    assert repo.audits[0]["after_json"] is not None
    assert repo.audits[0]["after_json"]["start_date"] == "2024-02-01"
    assert repo.audits[1]["before_json"] is not None
    assert repo.audits[1]["after_json"] is not None
    assert repo.audits[1]["before_json"] != repo.audits[1]["after_json"]
    assert repo.audits[2]["before_json"] is None
    assert repo.audits[2]["after_json"] is not None
    assert repo.audits[2]["after_json"]["start_date"] == "2024-03-01"
    assert "STAFF_REPLACEMENT_CONSULTATION" not in repo.audit_actions
    assert "WORK_CARD" not in {item["entity_type"] for item in repo.audits}
    assert "WORK_CARD" not in repo.audit_actions


# ---------------------------------------------------------------------------
# API behavior
# ---------------------------------------------------------------------------


class _FakeW1EService:
    def __init__(self) -> None:
        self.list_calls: list[tuple[int, int, date | None]] = []
        self.create_payload: CareAssignmentCreateRequest | None = None
        self.replace_payload: CareAssignmentReplacementRequest | None = None
        self.raise_domain_error: RecipientDomainError | None = None

    def list_assignments(
        self,
        recipient_id: int,
        contract_id: int,
        *,
        as_of: date | None = None,
    ) -> CareAssignmentListResponse:
        self.list_calls.append((recipient_id, contract_id, as_of))
        return CareAssignmentListResponse(items=[])

    def create_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        payload: CareAssignmentCreateRequest,
        account: CurrentAccount,
    ) -> Any:
        del recipient_id, contract_id, account
        self.create_payload = payload
        if self.raise_domain_error is not None:
            raise self.raise_domain_error
        row = _care_assignment(id=100)
        return W1EService._to_response(row)

    def replace_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        assignment_id: int,
        payload: CareAssignmentReplacementRequest,
        account: CurrentAccount,
    ) -> CareAssignmentReplacementResponse:
        del recipient_id, contract_id, assignment_id, account
        self.replace_payload = payload
        original = _care_assignment(
            id=1,
            row_version=2,
            invalidated_at_utc=datetime(2024, 2, 15, tzinfo=UTC),
            replacement_assignment_id=101,
        )
        replacement = _care_assignment(
            id=101,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        return CareAssignmentReplacementResponse(
            original=W1EService._to_response(original),
            replacement=W1EService._to_response(replacement),
        )


class _PermissionSession:
    def scalar(self, statement: Any) -> int:
        del statement
        return 1


def _permission_session_override() -> Iterator[_PermissionSession]:
    yield _PermissionSession()


def _create_payload_json() -> dict[str, Any]:
    return {
        "staff_id": 7,
        "employment_id": 8,
        "assignment_kind": "GENERAL",
        "start_date": "2024-02-01",
    }


def _replace_payload_json() -> dict[str, Any]:
    return {
        "staff_id": 7,
        "employment_id": 8,
        "assignment_kind": "GENERAL",
        "start_date": "2024-03-01",
        "expected_row_version": 1,
    }


def test_w1e_api_list_forwards_as_of_query_parameter() -> None:
    client = TestClient(app)
    service = _FakeW1EService()
    app.dependency_overrides[get_w1e_service] = lambda: service
    app.dependency_overrides[require_recipient_view] = lambda: _account()

    with_as_of = client.get(f"{COLLECTION_PATH}?as_of=2024-02-15")
    assert with_as_of.status_code == 200
    without_as_of = client.get(COLLECTION_PATH)
    assert without_as_of.status_code == 200

    assert service.list_calls == [
        (1, 1, date(2024, 2, 15)),
        (1, 1, None),
    ]


def test_w1e_api_create_returns_201_and_replace_returns_lineage() -> None:
    client = TestClient(app)
    service = _FakeW1EService()
    app.dependency_overrides[get_w1e_service] = lambda: service
    app.dependency_overrides[require_recipient_manage] = lambda: _account()

    created = client.post(COLLECTION_PATH, json=_create_payload_json())
    assert created.status_code == 201
    assert created.json()["id"] == 100
    assert service.create_payload is not None
    assert service.create_payload.start_date == date(2024, 2, 1)

    replaced = client.put(ITEM_PATH, json=_replace_payload_json())
    assert replaced.status_code == 200
    assert replaced.json()["original"]["row_version"] == 2
    assert replaced.json()["replacement"]["id"] == 101
    assert service.replace_payload is not None
    assert service.replace_payload.expected_row_version == 1


def test_w1e_api_error_statuses_separate_period_and_concurrent_conflict() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    service = _FakeW1EService()
    app.dependency_overrides[get_w1e_service] = lambda: service
    app.dependency_overrides[require_recipient_manage] = lambda: _account()

    service.raise_domain_error = RecipientDomainError(
        code="CARE_ASSIGNMENT_PERIOD_CONFLICT",
        status_code=422,
        message="같은 계약·직원의 배정기간이 겹칩니다.",
    )
    period_conflict = client.post(COLLECTION_PATH, json=_create_payload_json())
    assert period_conflict.status_code == 422
    assert period_conflict.json()["error"]["code"] == "CARE_ASSIGNMENT_PERIOD_CONFLICT"

    service.raise_domain_error = RecipientDomainError(
        code="CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
        status_code=409,
        message="다른 요청과 배정기간이 충돌했습니다. 최신 정보를 다시 확인하세요.",
    )
    concurrent_conflict = client.post(COLLECTION_PATH, json=_create_payload_json())
    assert concurrent_conflict.status_code == 409
    assert concurrent_conflict.json()["error"]["code"] == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"


def test_w1e_api_manage_auth_rejections_and_actual_csrf_guard() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_w1e_service] = lambda: _FakeW1EService()

    app.dependency_overrides[require_recipient_manage] = lambda: _raise_http(
        401,
        "session_required",
    )
    unauthenticated = client.post(COLLECTION_PATH, json=_create_payload_json())
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "SESSION_REQUIRED"

    app.dependency_overrides[require_recipient_manage] = lambda: _raise_http(
        403,
        "PERMISSION_REQUIRED",
    )
    forbidden = client.post(COLLECTION_PATH, json=_create_payload_json())
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "PERMISSION_REQUIRED"

    app.dependency_overrides.pop(require_recipient_manage, None)
    app.dependency_overrides[get_current_account] = lambda: _account(
        3,
        "USER",
    )
    app.dependency_overrides[get_db_session] = _permission_session_override
    csrf = client.post(COLLECTION_PATH, json=_create_payload_json())
    assert csrf.status_code == 403
    assert csrf.json()["error"]["code"] == "CSRF_REQUIRED"
