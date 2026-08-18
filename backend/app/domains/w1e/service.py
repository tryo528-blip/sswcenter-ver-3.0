"""W1E care-assignment CRUD and replacement/correction service."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.db.models import CareAssignment, RecipientContract, StaffEmployment
from app.db.w1e_family_relationship import FAMILY_RELATIONSHIP_TRIM_CHARS
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w1e import clock as w1e_clock
from app.domains.w1e.errors import (
    domain_error,
    is_w1e_advisory_lock_loss,
    sqlstate_of_dbapi_error,
)
from app.domains.w1e.repository import W1ERepository
from app.domains.w1e.schemas import (
    AssignmentKind,
    CareAssignmentCreateRequest,
    CareAssignmentListResponse,
    CareAssignmentReplacementRequest,
    CareAssignmentReplacementResponse,
    CareAssignmentResponse,
)


class W1EService:
    def __init__(
        self,
        database_session: Session,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.session = database_session
        self.request_id = request_id
        self.repo = W1ERepository(database_session)

    @property
    def database_session(self) -> Session:
        return self.session

    @staticmethod
    def _clean_relationship_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip(FAMILY_RELATIONSHIP_TRIM_CHARS)
        return cleaned or None

    @staticmethod
    def _validate_relationship(
        assignment_kind: AssignmentKind,
        cleaned: str | None,
    ) -> None:
        if assignment_kind is AssignmentKind.FAMILY and not cleaned:
            raise domain_error(
                "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED",
                422,
                field="family_relationship_text",
            )

    @staticmethod
    def _validate_period(start_date: date, end_date: date | None) -> None:
        if end_date is not None and start_date > end_date:
            raise domain_error("VALIDATION_ERROR", 422, field="end_date")

    @staticmethod
    def _period_contains(
        parent_start: date,
        parent_end: date | None,
        child_start: date,
        child_end: date | None,
    ) -> bool:
        if child_start < parent_start:
            return False
        if child_end is None:
            return parent_end is None
        return parent_end is None or child_end <= parent_end

    @staticmethod
    def _to_response(row: CareAssignment) -> CareAssignmentResponse:
        return CareAssignmentResponse(
            id=row.id,
            recipient_contract_id=row.recipient_contract_id,
            staff_id=row.staff_id,
            employment_id=row.employment_id,
            assignment_kind=AssignmentKind(row.assignment_kind),
            family_relationship_text=row.family_relationship_text,
            start_date=row.start_date,
            end_date=row.end_date,
            invalidated_at_utc=row.invalidated_at_utc,
            replacement_assignment_id=row.replacement_assignment_id,
            row_version=row.row_version,
        )

    @staticmethod
    def _sqlstate_of(error: BaseException) -> str | None:
        return sqlstate_of_dbapi_error(error)

    @staticmethod
    def _map_integrity_error(error: IntegrityError) -> RecipientDomainError:
        original = getattr(error, "orig", None)
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        mapping = {
            "ck_care_assignment_family_relationship_present": (
                "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED",
                422,
            ),
            "ex_care_assignment_same_contract_staff_period": (
                "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
                409,
            ),
            # Application prechecks already reject invalid contract/employment/
            # position/qualification input with 422.  A deferred guard raising
            # these codes during flush/commit therefore means another relevant
            # transaction committed between the precheck and the final save.
            "ct_care_assignment_within_contract": (
                "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
                409,
            ),
            "ct_care_assignment_within_employment": (
                "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
                409,
            ),
            "ct_care_assignment_within_position": (
                "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
                409,
            ),
            "ct_care_assignment_general_care_qualified": (
                "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
                409,
            ),
            "ct_recipient_contract_assignment_reverse_guard": (
                "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
                409,
            ),
        }
        mapped = mapping.get(constraint_name) if isinstance(constraint_name, str) else None
        if mapped is not None:
            return domain_error(mapped[0], mapped[1])
        if is_w1e_advisory_lock_loss(error):
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        sqlstate = W1EService._sqlstate_of(error)
        if sqlstate == "40P01":
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if sqlstate == "23P01":
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        message = str(original or error).lower()
        # Application prechecks already return 422 for invalid input.  The
        # same trigger messages on flush/commit are a committed race, so they
        # keep the 409 concurrent-conflict contract even when the driver
        # omits ``diag.constraint_name``.
        if "outside_contract_period" in message or "outside contract" in message:
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if "outside_employment_period" in message or "outside employment" in message:
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if "staff_ineligible" in message:
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if "care_assignment_contract_orphan_forbidden" in message:
            return domain_error("CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN", 409)
        if "same_contract_staff" in message:
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        return domain_error("UNEXPECTED_SERVER_ERROR", 500)

    @staticmethod
    def _map_sqlalchemy_error(error: SQLAlchemyError) -> RecipientDomainError:
        # Leftover deadlock (40P01) on a W1E write is still a race.  55P03 is
        # a care-assignment conflict only when the helper raised the stable
        # W1E lock-loss message; lock_timeout and NOWAIT stay unmapped.
        if is_w1e_advisory_lock_loss(error):
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if W1EService._sqlstate_of(error) == "40P01":
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if isinstance(error, IntegrityError):
            return W1EService._map_integrity_error(error)
        return domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _flush(self) -> None:
        try:
            self.session.flush()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise self._map_sqlalchemy_error(exc) from None

    def _commit(self) -> None:
        if self.session.info.get("recipient_detail_batch_defer_commit"):
            try:
                self.session.flush()
            except SQLAlchemyError as exc:
                self.session.rollback()
                raise self._map_sqlalchemy_error(exc) from None
            return
        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise self._map_sqlalchemy_error(exc) from None

    def _require_contract(
        self,
        recipient_id: int,
        contract_id: int,
        *,
        for_update: bool,
        active_only: bool = True,
    ) -> RecipientContract:
        contract = (
            self.repo.get_contract_for_update(recipient_id, contract_id)
            if for_update
            else self.repo.get_contract(recipient_id, contract_id)
        )
        if contract is None or (active_only and contract.invalidated_at_utc is not None):
            raise domain_error("CONTRACT_NOT_FOUND", 404)
        return contract

    def _require_active_assignment(
        self,
        contract_id: int,
        assignment_id: int,
        *,
        for_update: bool,
    ) -> CareAssignment:
        row = self.repo.get_assignment(
            contract_id,
            assignment_id,
            for_update=for_update,
            active_only=True,
        )
        if row is not None:
            return row
        historical = self.repo.get_assignment(contract_id, assignment_id)
        if historical is not None:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={
                    "current_row_version": historical.row_version,
                    "entity": "care_assignment",
                },
            )
        raise domain_error("CARE_ASSIGNMENT_NOT_FOUND", 404)

    def _validate_boundary(
        self,
        *,
        contract: RecipientContract,
        payload: CareAssignmentCreateRequest,
        cleaned_relationship: str | None,
        exclude_assignment_id: int | None = None,
    ) -> StaffEmployment:
        self._validate_relationship(payload.assignment_kind, cleaned_relationship)
        self._validate_period(payload.start_date, payload.end_date)

        employment = self.repo.get_employment(payload.staff_id, payload.employment_id)
        if employment is None or not self._period_contains(
            employment.start_date,
            employment.end_date,
            payload.start_date,
            payload.end_date,
        ):
            raise domain_error(
                "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
                422,
                field="start_date",
            )

        if not self._period_contains(
            contract.start_date,
            contract.end_date,
            payload.start_date,
            payload.end_date,
        ):
            raise domain_error(
                "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
                422,
                field="start_date",
            )

        if self.repo.assignment_overlaps_active(
            contract_id=contract.id,
            staff_id=payload.staff_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            exclude_assignment_id=exclude_assignment_id,
        ):
            raise domain_error("CARE_ASSIGNMENT_PERIOD_CONFLICT", 422)

        if payload.assignment_kind is AssignmentKind.GENERAL:
            if not self.repo.care_worker_position_covers(
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
            ):
                raise domain_error(
                    "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
                    422,
                    field="staff_id",
                )
            if not self.repo.qualification_covers(
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                service_type_id=contract.service_type_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
            ):
                raise domain_error(
                    "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
                    422,
                    field="staff_id",
                )
        return employment

    def list_assignments(
        self,
        recipient_id: int,
        contract_id: int,
        *,
        as_of: date | None = None,
    ) -> CareAssignmentListResponse:
        self._require_contract(
            recipient_id,
            contract_id,
            for_update=False,
            active_only=False,
        )
        return CareAssignmentListResponse(
            items=[
                self._to_response(row)
                for row in self.repo.list_assignments(contract_id, as_of=as_of)
            ]
        )

    def get_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        assignment_id: int,
    ) -> CareAssignmentResponse:
        self._require_contract(
            recipient_id,
            contract_id,
            for_update=False,
            active_only=False,
        )
        row = self.repo.get_assignment(contract_id, assignment_id)
        if row is None:
            raise domain_error("CARE_ASSIGNMENT_NOT_FOUND", 404)
        return self._to_response(row)

    def create_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        payload: CareAssignmentCreateRequest,
        account: CurrentAccount,
    ) -> CareAssignmentResponse:
        cleaned_relationship = self._clean_relationship_text(payload.family_relationship_text)
        try:
            contract = self._require_contract(
                recipient_id,
                contract_id,
                for_update=False,
                active_only=True,
            )
            self._validate_boundary(
                contract=contract,
                payload=payload,
                cleaned_relationship=cleaned_relationship,
            )
            now = w1e_clock.now_utc()
            row = CareAssignment(
                recipient_contract_id=contract_id,
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                assignment_kind=payload.assignment_kind.value,
                family_relationship_text=cleaned_relationship,
                start_date=payload.start_date,
                end_date=payload.end_date,
                invalidated_at_utc=None,
                replacement_assignment_id=None,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                created_at_utc=now,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(row)
            self._flush()
            response = self._to_response(row)
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="CARE_ASSIGNMENT_CREATE",
                entity_type="CARE_ASSIGNMENT",
                entity_pk=row.id,
                before_json=None,
                after_json=response.model_dump(mode="json"),
                reason_code="USER_CREATE",
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._flush()
            self._commit()
            return response
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def replace_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        assignment_id: int,
        payload: CareAssignmentReplacementRequest,
        account: CurrentAccount,
    ) -> CareAssignmentReplacementResponse:
        cleaned_relationship = self._clean_relationship_text(payload.family_relationship_text)
        try:
            contract = self._require_contract(
                recipient_id,
                contract_id,
                for_update=False,
                active_only=True,
            )
            original = self._require_active_assignment(
                contract_id,
                assignment_id,
                for_update=True,
            )
            if original.row_version != payload.expected_row_version:
                raise domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": original.row_version,
                        "entity": "care_assignment",
                    },
                )
            self._validate_boundary(
                contract=contract,
                payload=payload,
                cleaned_relationship=cleaned_relationship,
                exclude_assignment_id=original.id,
            )

            changed_at = w1e_clock.now_utc()
            before = self._to_response(original).model_dump(mode="json")
            original.invalidated_at_utc = changed_at
            original.updated_at_utc = changed_at
            original.updated_by_account_id = account.id
            original.row_version = int(original.row_version) + 1
            self._flush()

            replacement = CareAssignment(
                recipient_contract_id=contract_id,
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                assignment_kind=payload.assignment_kind.value,
                family_relationship_text=cleaned_relationship,
                start_date=payload.start_date,
                end_date=payload.end_date,
                invalidated_at_utc=None,
                replacement_assignment_id=None,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                created_at_utc=changed_at,
                updated_at_utc=changed_at,
                row_version=1,
            )
            self.session.add(replacement)
            self._flush()
            original.replacement_assignment_id = replacement.id
            self._flush()

            original_response = self._to_response(original)
            replacement_response = self._to_response(replacement)
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="CARE_ASSIGNMENT_REPLACE",
                entity_type="CARE_ASSIGNMENT",
                entity_pk=original.id,
                before_json=before,
                after_json=original_response.model_dump(mode="json"),
                reason_code="USER_REPLACE",
                request_id=self.request_id,
                occurred_at_utc=changed_at,
            )
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="CARE_ASSIGNMENT_REPLACEMENT_CREATE",
                entity_type="CARE_ASSIGNMENT",
                entity_pk=replacement.id,
                before_json=None,
                after_json=replacement_response.model_dump(mode="json"),
                reason_code="USER_REPLACE",
                request_id=self.request_id,
                occurred_at_utc=changed_at,
            )
            self._flush()
            self._commit()
            return CareAssignmentReplacementResponse(
                original=original_response,
                replacement=replacement_response,
            )
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise
