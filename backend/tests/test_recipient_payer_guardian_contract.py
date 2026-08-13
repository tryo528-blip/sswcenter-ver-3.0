"""Contract tests for recipient.payer_guardian_id (migration 0016 + service).

Covers migration linkage, nullable column, composite same-recipient FK, downgrade
surface, and RecipientService self/null, guardian1, guardian2, cross-recipient
rejection, response mapping, row_version/audit. Does not execute PostgreSQL.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import Table

from app.db.models import Recipient
from app.domains.recipient.errors import RecipientDomainError
from app.domains.recipient.schemas import RecipientResponse, RecipientUpdateRequest
from app.domains.recipient.service import RecipientService

REPO_ROOT = Path(__file__).resolve().parents[2]
_REV_0015 = "20260806_0015_recipient_status_tag"
_REV_0016 = "20260808_0016_recipient_payer_guardian"
_REV_0017 = "20260808_0017_recipient_guardian_email"
_MIGRATION = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260808_0016_recipient_payer_guardian.py"
)


def test_migration_0016_source_is_linked_and_not_silently_skippable() -> None:
    assert _MIGRATION.is_file(), "migration 0016 must exist"
    source = _MIGRATION.read_text(encoding="utf-8")
    assert f'revision: str = "{_REV_0016}"' in source
    assert f'down_revision: str | None = "{_REV_0015}"' in source
    assert "payer_guardian_id" in source
    assert "fk_recipient_payer_guardian_same_recipient" in source
    assert "ON DELETE RESTRICT" in source or 'ondelete="RESTRICT"' in source
    assert "recipient_guardian" in source
    # Downgrade only drops FK + column (no historical data wipe of other tables).
    assert "drop_constraint" in source
    assert "drop_column" in source
    assert "recipient_payer_snapshot" not in source  # independent snapshot API preserved


def test_model_has_payer_guardian_id_and_composite_fk() -> None:
    table = cast(Table, Recipient.__table__)
    column = table.c.payer_guardian_id
    assert column.nullable is True
    fk_names = {fk.name for fk in table.foreign_key_constraints}
    assert "fk_recipient_payer_guardian_same_recipient" in fk_names
    composite = next(
        fk
        for fk in table.foreign_key_constraints
        if fk.name == "fk_recipient_payer_guardian_same_recipient"
    )
    src = [col.name for col in composite.columns]
    assert src == ["id", "payer_guardian_id"]
    ref = sorted((elem.column.table.name, elem.column.name) for elem in composite.elements)
    assert ("recipient_guardian", "id") in ref
    assert ("recipient_guardian", "recipient_id") in ref


def test_update_request_omit_null_and_positive_payer_guardian_id() -> None:
    omitted = RecipientUpdateRequest(expected_row_version=1)
    assert "payer_guardian_id" not in omitted.model_fields_set
    assert omitted.payer_guardian_id is None

    as_self = RecipientUpdateRequest.model_validate(
        {"expected_row_version": 1, "payer_guardian_id": None}
    )
    assert "payer_guardian_id" in as_self.model_fields_set
    assert as_self.payer_guardian_id is None

    as_guardian = RecipientUpdateRequest(expected_row_version=1, payer_guardian_id=42)
    assert as_guardian.payer_guardian_id == 42

    with pytest.raises(ValidationError):
        RecipientUpdateRequest.model_validate({"expected_row_version": 1, "payer_guardian_id": 0})
    with pytest.raises(ValidationError):
        RecipientUpdateRequest.model_validate({"expected_row_version": 1, "payer_guardian_id": -1})


def test_response_maps_payer_guardian_id() -> None:
    response = RecipientResponse(
        id=1,
        name="홍길동",
        birth_date=date(1950, 1, 1),
        sex_code="MALE",  # type: ignore[arg-type]
        recipient_status="ACTIVE",  # type: ignore[arg-type]
        recipient_no=None,
        postal_code=None,
        address=None,
        mobile_phone="010-0000-0000",
        memo=None,
        payer_guardian_id=None,
        row_version=1,
    )
    assert response.payer_guardian_id is None
    response2 = response.model_copy(update={"payer_guardian_id": 7})
    assert response2.payer_guardian_id == 7


def _recipient(
    *,
    recipient_id: int = 1,
    row_version: int = 1,
    payer_guardian_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=recipient_id,
        name="수급자",
        birth_date=date(1950, 1, 1),
        sex_code="MALE",
        recipient_status="ACTIVE",
        recipient_no=None,
        postal_code=None,
        address=None,
        mobile_phone="010-0000-0000",
        memo=None,
        payer_guardian_id=payer_guardian_id,
        row_version=row_version,
        updated_by_account_id=1,
        updated_at_utc=None,
    )


def _guardian(*, guardian_id: int, recipient_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=guardian_id,
        recipient_id=recipient_id,
        name=f"보호자{guardian_id}",
        phone=None,
        address=None,
        relationship_text=None,
        row_version=1,
    )


def _service_with_recipient(
    recipient: SimpleNamespace,
    *,
    guardians: dict[int, SimpleNamespace] | None = None,
) -> tuple[RecipientService, MagicMock, list[Any]]:
    session = MagicMock()
    session.info = {}
    session.commit = MagicMock()
    session.rollback = MagicMock()
    service = RecipientService(session, request_id=None)
    audits: list[Any] = []

    def get_recipient(rid: int, for_update: bool = False) -> SimpleNamespace | None:
        if rid == recipient.id:
            return recipient
        return None

    guardians = guardians or {}

    def get_guardian(rid: int, gid: int, for_update: bool = False) -> SimpleNamespace | None:
        guardian = guardians.get(gid)
        if guardian is None:
            return None
        if guardian.recipient_id != rid:
            return None
        return guardian

    service.repository.get_recipient = get_recipient  # type: ignore[method-assign, assignment]
    service.repository.get_guardian = get_guardian  # type: ignore[method-assign, assignment]
    service.repository.add = audits.append  # type: ignore[method-assign, assignment]
    service.repository.flush = MagicMock()  # type: ignore[method-assign]
    return service, session, audits


def test_update_recipient_self_null_guardian1_guardian2_and_cross_reject() -> None:
    account = SimpleNamespace(id=99)
    g1 = _guardian(guardian_id=11, recipient_id=1)
    g2 = _guardian(guardian_id=22, recipient_id=1)
    foreign = _guardian(guardian_id=99, recipient_id=2)

    # self (explicit null)
    recipient = _recipient(payer_guardian_id=11, row_version=3)
    service, session, audits = _service_with_recipient(
        recipient, guardians={11: g1, 22: g2, 99: foreign}
    )
    result = service.update_recipient(
        1,
        RecipientUpdateRequest.model_validate(
            {"expected_row_version": 3, "payer_guardian_id": None}
        ),
        account,  # type: ignore[arg-type]
    )
    assert recipient.payer_guardian_id is None
    assert result.payer_guardian_id is None
    assert recipient.row_version == 4
    assert result.row_version == 4
    session.commit.assert_called()
    assert (
        any(
            getattr(item, "action_code", None) == "RECIPIENT_UPDATE"
            or (isinstance(item, SimpleNamespace) is False and hasattr(item, "after_json"))
            for item in audits
        )
        or audits
    )  # audit event recorded via repository.add

    # guardian1
    recipient = _recipient(payer_guardian_id=None, row_version=1)
    service, _, _ = _service_with_recipient(recipient, guardians={11: g1, 22: g2})
    result = service.update_recipient(
        1,
        RecipientUpdateRequest(expected_row_version=1, payer_guardian_id=11),
        account,  # type: ignore[arg-type]
    )
    assert recipient.payer_guardian_id == 11
    assert result.payer_guardian_id == 11

    # guardian2
    recipient = _recipient(payer_guardian_id=11, row_version=2)
    service, _, _ = _service_with_recipient(recipient, guardians={11: g1, 22: g2})
    result = service.update_recipient(
        1,
        RecipientUpdateRequest(expected_row_version=2, payer_guardian_id=22),
        account,  # type: ignore[arg-type]
    )
    assert recipient.payer_guardian_id == 22
    assert result.payer_guardian_id == 22

    # cross-recipient rejection (foreign guardian id not under this recipient)
    recipient = _recipient(payer_guardian_id=None, row_version=1)
    service, session, _ = _service_with_recipient(recipient, guardians={11: g1, 99: foreign})
    with pytest.raises(RecipientDomainError) as exc_info:
        service.update_recipient(
            1,
            RecipientUpdateRequest(expected_row_version=1, payer_guardian_id=99),
            account,  # type: ignore[arg-type]
        )
    assert exc_info.value.code == "RECIPIENT_GUARDIAN_NOT_FOUND"
    assert recipient.payer_guardian_id is None
    session.commit.assert_not_called()


def test_update_recipient_omit_payer_guardian_id_leaves_unchanged() -> None:
    account = SimpleNamespace(id=1)
    recipient = _recipient(payer_guardian_id=11, row_version=5)
    service, _, _ = _service_with_recipient(
        recipient, guardians={11: _guardian(guardian_id=11, recipient_id=1)}
    )
    result = service.update_recipient(
        1,
        RecipientUpdateRequest(expected_row_version=5, name="새이름"),
        account,  # type: ignore[arg-type]
    )
    assert recipient.payer_guardian_id == 11
    assert result.payer_guardian_id == 11
    assert result.name == "새이름"


def test_postcheck_0016_source_and_marker_contract() -> None:
    postcheck = (REPO_ROOT / "backend" / "app" / "db" / "postcheck_w1a_vs1.py").read_text(
        encoding="utf-8"
    )
    assert f'RECIPIENT_PAYER_GUARDIAN_REVISION = "{_REV_0016}"' in postcheck
    assert "def _verify_recipient_payer_guardian_contract" in postcheck
    assert "RECIPIENT_PAYER_GUARDIAN_DB_POSTCHECK_OK" in postcheck
    assert "payer_guardian_id" in postcheck
    assert "fk_recipient_payer_guardian_same_recipient" in postcheck
    # 0015 marker/boundary preserved.
    assert f'RECIPIENT_STATUS_TAG_REVISION = "{_REV_0015}"' in postcheck
    assert "RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK" in postcheck


def test_wrappers_and_restore_drill_reference_0016_or_descendant_head() -> None:
    # restore-drill.ps1 keeps the exact 0016 revision in its historical allowlist.
    # test-w1b/w1d/w1f wrappers advance $CurrentHead to descendant heads over time
    # (currently 0017); either the exact 0016 marker or its 0017 descendant proves
    # the payer_guardian lineage remains reachable.
    for relative in (
        "scripts/test-w1b-postgres.ps1",
        "scripts/test-w1d-postgres.ps1",
        "scripts/test-w1f-postgres.ps1",
        "scripts/restore-drill.ps1",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert _REV_0016 in source or _REV_0017 in source, (
            f"{relative} must reference 0016 or its 0017 descendant head"
        )
