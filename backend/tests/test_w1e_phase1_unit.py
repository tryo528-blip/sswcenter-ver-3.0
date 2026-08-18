"""Pure unit tests for W1E domain boundary helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy.sql.elements import TextClause

from app.db.w1e_family_relationship import FAMILY_RELATIONSHIP_TRIM_CHARS
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w1e.repository import W1ERepository
from app.domains.w1e.schemas import AssignmentKind
from app.domains.w1e.service import W1EService


def test_period_contains_handles_open_ended_parent_and_child() -> None:
    assert W1EService._period_contains(date(2024, 1, 1), None, date(2024, 1, 1), None)
    assert W1EService._period_contains(
        date(2024, 1, 1),
        date(2024, 12, 31),
        date(2024, 1, 1),
        date(2024, 12, 31),
    )
    assert not W1EService._period_contains(
        date(2024, 1, 1),
        date(2024, 12, 31),
        date(2024, 1, 1),
        None,
    )
    assert not W1EService._period_contains(
        date(2024, 1, 1),
        None,
        date(2023, 12, 31),
        date(2024, 1, 1),
    )


def test_family_relationship_requires_nonblank_at_boundary() -> None:
    assert FAMILY_RELATIONSHIP_TRIM_CHARS == " \t\n\r\f\v"
    assert W1EService._clean_relationship_text("  자녀  ") == "자녀"
    assert W1EService._clean_relationship_text("   ") is None
    assert W1EService._clean_relationship_text("\f") is None
    assert W1EService._clean_relationship_text("\v") is None
    assert W1EService._clean_relationship_text("\t\n\r\f\v") is None
    assert W1EService._clean_relationship_text("\f자녀\v") == "자녀"
    assert W1EService._clean_relationship_text("\u00a0") == "\u00a0"
    assert W1EService._clean_relationship_text("v") == "v"

    W1EService._validate_relationship(AssignmentKind.FAMILY, "자녀")
    with pytest.raises(RecipientDomainError) as excinfo:
        W1EService._validate_relationship(AssignmentKind.FAMILY, None)
    assert excinfo.value.code == "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED"
    assert excinfo.value.status_code == 422

    W1EService._validate_relationship(AssignmentKind.GENERAL, None)


class _CaptureScalarSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.parameters: list[dict[str, Any]] = []

    def scalar(self, statement: Any, parameters: dict[str, Any] | None = None) -> bool:
        self.statements.append(statement)
        self.parameters.append(dict(parameters or {}))
        return False


def test_repository_overlap_sql_casts_none_and_real_exclude_assignment_id() -> None:
    session = _CaptureScalarSession()
    repository = W1ERepository(session)  # type: ignore[arg-type]
    for exclude_assignment_id in (None, 42):
        assert (
            repository.assignment_overlaps_active(
                contract_id=1,
                staff_id=7,
                start_date=date(2030, 2, 1),
                end_date=date(2030, 2, 28),
                exclude_assignment_id=exclude_assignment_id,
            )
            is False
        )
    assert len(session.statements) == 2
    assert len(session.parameters) == 2
    for statement, parameters, exclude_assignment_id in zip(
        session.statements,
        session.parameters,
        (None, 42),
        strict=True,
    ):
        assert isinstance(statement, TextClause)
        sql = str(statement)
        assert sql.count("CAST(:exclude_assignment_id AS bigint)") == 2
        assert "CAST(:exclude_assignment_id AS bigint) IS NULL" in sql
        assert "existing.id <> CAST(:exclude_assignment_id AS bigint)" in sql
        assert parameters["exclude_assignment_id"] is exclude_assignment_id
    create_sql = str(session.statements[0])
    replace_sql = str(session.statements[1])
    assert create_sql == replace_sql
    assert session.parameters[0]["exclude_assignment_id"] is None
    assert session.parameters[1]["exclude_assignment_id"] == 42


def test_period_validation_rejects_reversed_dates() -> None:
    W1EService._validate_period(date(2024, 1, 1), date(2024, 12, 31))
    W1EService._validate_period(date(2024, 1, 1), None)
    with pytest.raises(RecipientDomainError) as excinfo:
        W1EService._validate_period(date(2024, 2, 1), date(2024, 1, 1))
    assert excinfo.value.code == "VALIDATION_ERROR"
    assert excinfo.value.field_errors[0]["field"] == "end_date"
