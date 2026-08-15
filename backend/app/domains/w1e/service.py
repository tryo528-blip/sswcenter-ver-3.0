from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.db.models import CareAssignment
from app.domains.w1e.errors import domain_error
from app.domains.w1e.repository import W1ERepository
from app.domains.w1e.schemas import (
    CareAssignmentCreateRequest,
    CareAssignmentListResponse,
    CareAssignmentReplaceRequest,
    CareAssignmentResponse,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _constraint_name(error: IntegrityError) -> str | None:
    original = getattr(error, "orig", None)
    diagnostics = getattr(original, "diag", None)
    value = getattr(diagnostics, "constraint_name", None)
    return str(value) if value else None


class W1EService:
    def __init__(self, database_session: Session, *, request_id: UUID | None = None) -> None:
        self.session = database_session
        self.request_id = request_id
        self.repo = W1ERepository(database_session)

    @property
    def database_session(self) -> Session:
        return self.session

    @staticmethod
    def _map_integrity_error(error: IntegrityError) -> Exception:
        constraint = _constraint_name(error)
        mapping = {
            "ex_care_assignment_same_contract_staff_period": "CARE_ASSIGNMENT_PERIOD_CONFLICT",
            "ct_care_assignment_within_contract": "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
            "ct_care_assignment_within_employment": "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
            "ct_care_assignment_within_position": "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
            "ct_care_assignment_general_care_qualified": "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
            "ct_recipient_contract_assignment_reverse_guard": (
                "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN"
            ),
            "ct_staff_employment_child_periods_reverse_guard": (
                "CARE_ASSIGNMENT_EMPLOYMENT_ORPHAN_FORBIDDEN"
            ),
            "ct_staff_position_care_assignment_reverse_guard": (
                "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN"
            ),
            "ct_staff_service_qualification_assignment_reverse_guard": (
                "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN"
            ),
        }
        if constraint in mapping:
            return domain_error(mapping[constraint], 409)
        message = str(getattr(error, "orig", error)).lower()
        if "care_assignment_same_contract_staff" in message:
            return domain_error("CARE_ASSIGNMENT_PERIOD_CONFLICT", 409)
        if "outside_contract" in message:
            return domain_error("CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD", 409)
        if "outside_employment" in message:
            return domain_error("CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD", 409)
        if "staff_ineligible" in message or "qualification" in message or "position" in message:
            return domain_error("CARE_ASSIGNMENT_STAFF_INELIGIBLE", 409)
        return domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _flush(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.session.rollback()
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.session.rollback()
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    @staticmethod
    def _response(row: CareAssignment, recipient_id: int) -> CareAssignmentResponse:
        return CareAssignmentResponse(
            id=row.id,
            recipient_id=recipient_id,
            recipient_contract_id=row.recipient_contract_id,
            staff_id=row.staff_id,
            employment_id=row.employment_id,
            assignment_kind=row.assignment_kind,
            family_relationship_text=row.family_relationship_text,
            start_date=row.start_date,
            end_date=row.end_date,
            invalidated_at_utc=row.invalidated_at_utc,
            replacement_assignment_id=row.replacement_assignment_id,
            row_version=row.row_version,
        )

    @staticmethod
    def _audit_payload(row: CareAssignment) -> dict[str, Any]:
        return {
            "id": row.id,
            "recipient_contract_id": row.recipient_contract_id,
            "staff_id": row.staff_id,
            "employment_id": row.employment_id,
            "assignment_kind": row.assignment_kind,
            "family_relationship_text": row.family_relationship_text,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat() if row.end_date else None,
            "invalidated_at_utc": (
                row.invalidated_at_utc.isoformat() if row.invalidated_at_utc else None
            ),
            "replacement_assignment_id": row.replacement_assignment_id,
            "row_version": row.row_version,
        }

    def _require_contract(
        self,
        recipient_id: int,
        contract_id: int,
        *,
        for_update: bool = False,
    ) -> Any:
        if self.repo.get_recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        contract = (
            self.repo.get_contract_for_update(recipient_id, contract_id)
            if for_update
            else self.repo.get_contract(recipient_id, contract_id)
        )
        if contract is None or contract.invalidated_at_utc is not None:
            raise domain_error("CONTRACT_NOT_FOUND", 404)
        return contract

    def list_assignments(self, recipient_id: int, contract_id: int) -> CareAssignmentListResponse:
        self._require_contract(recipient_id, contract_id)
        return CareAssignmentListResponse(
            items=[
                self._response(row, recipient_id)
                for row in self.repo.list_assignments(recipient_id, contract_id)
            ]
        )

    def get_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        assignment_id: int,
    ) -> CareAssignmentResponse:
        self._require_contract(recipient_id, contract_id)
        row = self.repo.get_assignment(recipient_id, contract_id, assignment_id)
        if row is None:
            raise domain_error("CARE_ASSIGNMENT_NOT_FOUND", 404)
        return self._response(row, recipient_id)

    def create_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        payload: CareAssignmentCreateRequest,
        account: CurrentAccount,
    ) -> CareAssignmentResponse:
        try:
            contract = self._require_contract(recipient_id, contract_id, for_update=True)
            now = _now()
            row = CareAssignment(
                recipient_contract_id=contract.id,
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                assignment_kind=payload.assignment_kind.value,
                family_relationship_text=payload.family_relationship_text,
                start_date=payload.start_date,
                end_date=payload.end_date,
                invalidated_at_utc=None,
                replacement_assignment_id=None,
                created_by_account_id=account.id,
                created_at_utc=now,
                updated_by_account_id=account.id,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(row)
            self._flush()
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="RECIPIENT_CARE_ASSIGNMENT_CREATE",
                entity_pk=row.id,
                before_json=None,
                after_json=self._audit_payload(row),
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._commit()
            return self._response(row, recipient_id)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def replace_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        assignment_id: int,
        payload: CareAssignmentReplaceRequest,
        account: CurrentAccount,
    ) -> CareAssignmentResponse:
        try:
            contract = self._require_contract(recipient_id, contract_id, for_update=True)
            current = self.repo.get_assignment(
                recipient_id,
                contract_id,
                assignment_id,
                for_update=True,
            )
            if current is None or current.invalidated_at_utc is not None:
                raise domain_error("CARE_ASSIGNMENT_NOT_FOUND", 404)
            if current.row_version != payload.expected_row_version:
                raise domain_error("ROW_VERSION_CONFLICT", 409)

            now = _now()
            before = self._audit_payload(current)
            current.invalidated_at_utc = now
            current.updated_by_account_id = account.id
            current.updated_at_utc = now
            current.row_version = int(current.row_version) + 1
            self._flush()

            replacement = CareAssignment(
                recipient_contract_id=contract.id,
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                assignment_kind=payload.assignment_kind.value,
                family_relationship_text=payload.family_relationship_text,
                start_date=payload.start_date,
                end_date=payload.end_date,
                invalidated_at_utc=None,
                replacement_assignment_id=None,
                created_by_account_id=account.id,
                created_at_utc=now,
                updated_by_account_id=account.id,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(replacement)
            self._flush()
            current.replacement_assignment_id = replacement.id
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="RECIPIENT_CARE_ASSIGNMENT_REPLACE",
                entity_pk=current.id,
                before_json=before,
                after_json=self._audit_payload(replacement),
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._commit()
            return self._response(replacement, recipient_id)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise
