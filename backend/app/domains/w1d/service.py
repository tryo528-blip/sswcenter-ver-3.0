"""W1D recipient-contract CRUD service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.core.settings import Settings
from app.db.models import RecipientContract, ServiceGroup, ServiceType
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w1d import clock as w1d_clock
from app.domains.w1d import fault as w1d_fault
from app.domains.w1d.errors import domain_error
from app.domains.w1d.repository import W1DRepository
from app.domains.w1d.schemas import (
    ContractCreateRequest,
    ContractEndRequest,
    ContractListResponse,
    ContractResponse,
)
from app.domains.w1e.errors import is_w1e_advisory_lock_loss, sqlstate_of_dbapi_error


class W1DService:
    def __init__(
        self,
        database_session: Session,
        settings: Settings | None = None,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.session = database_session
        self.settings = settings
        self.request_id = request_id
        self.repo = W1DRepository(database_session)

    @property
    def database_session(self) -> Session:
        return self.session

    @staticmethod
    def _map_integrity_error(error: IntegrityError) -> RecipientDomainError:
        if is_w1e_advisory_lock_loss(error):
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        original = getattr(error, "orig", None)
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        mapping = {
            "ex_recipient_contract_same_service_period": (
                "CONTRACT_SERVICE_PERIOD_CONFLICT",
                409,
            ),
            "trg_recipient_contract_group_period_overlap": (
                "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT",
                409,
            ),
            "ck_recipient_contract_no_reactivation": (
                "CONTRACT_REACTIVATION_FORBIDDEN",
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
        message = str(original or error).lower()
        if "same_service" in message:
            return domain_error("CONTRACT_SERVICE_PERIOD_CONFLICT", 409)
        if "group_period_overlap" in message or "cross-group" in message:
            return domain_error("CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT", 409)
        if "reactivation" in message:
            return domain_error("CONTRACT_REACTIVATION_FORBIDDEN", 409)
        if "care_assignment_contract_orphan_forbidden" in message:
            return domain_error("CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN", 409)
        return domain_error("UNEXPECTED_SERVER_ERROR", 500)

    @staticmethod
    def _sqlstate_of(error: BaseException) -> str | None:
        return sqlstate_of_dbapi_error(error)

    def _map_sqlalchemy_error(self, error: SQLAlchemyError) -> RecipientDomainError:
        # Only the W1E helper RAISE (55P03 + stable message) is a care-assignment
        # conflict.  lock_timeout and other 55P03 outcomes stay unmapped.
        if is_w1e_advisory_lock_loss(error):
            return domain_error("CARE_ASSIGNMENT_CONCURRENT_CONFLICT", 409)
        if isinstance(error, IntegrityError):
            return self._map_integrity_error(error)
        return domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _flush(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise self._map_sqlalchemy_error(exc) from None

    def _commit(self) -> None:
        if self.session.info.get("recipient_detail_batch_defer_commit"):
            try:
                self.session.flush()
            except IntegrityError as exc:
                self.session.rollback()
                raise self._map_integrity_error(exc) from None
            except SQLAlchemyError as exc:
                self.session.rollback()
                raise self._map_sqlalchemy_error(exc) from None
            return
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise self._map_sqlalchemy_error(exc) from None

    def _service_meta(
        self,
    ) -> tuple[dict[int, ServiceType], dict[str, ServiceType], dict[int, str]]:
        types = self.repo.get_service_types()
        groups = {group.id: group.code for group in self.session.query(ServiceGroup).all()}
        return (
            {service_type.id: service_type for service_type in types},
            {service_type.code: service_type for service_type in types},
            {
                service_type.id: groups.get(service_type.service_group_id, "")
                for service_type in types
            },
        )

    @staticmethod
    def _to_response(
        row: RecipientContract,
        *,
        by_id: dict[int, ServiceType],
        group_by_type: dict[int, str],
    ) -> ContractResponse:
        service_type = by_id.get(row.service_type_id)
        return ContractResponse(
            id=row.id,
            recipient_id=row.recipient_id,
            service_type_code=service_type.code if service_type else "",
            service_group_code=group_by_type.get(row.service_type_id) or None,
            start_date=row.start_date,
            end_date=row.end_date,
            service_start_date=row.service_start_date,
            end_reason_text=row.end_reason_text,
            invalidated_at_utc=row.invalidated_at_utc,
            replacement_contract_id=row.replacement_contract_id,
            row_version=row.row_version,
        )

    def list_contracts(self, recipient_id: int) -> ContractListResponse:
        if self.repo.get_recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        by_id, _, group_by_type = self._service_meta()
        return ContractListResponse(
            items=[
                self._to_response(row, by_id=by_id, group_by_type=group_by_type)
                for row in self.repo.list_contracts(recipient_id)
            ]
        )

    def get_contract(self, recipient_id: int, contract_id: int) -> ContractResponse:
        if self.repo.get_recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        row = self.repo.get_contract(recipient_id, contract_id)
        if row is None:
            raise domain_error("CONTRACT_NOT_FOUND", 404)
        by_id, _, group_by_type = self._service_meta()
        return self._to_response(row, by_id=by_id, group_by_type=group_by_type)

    def create_contract(
        self,
        recipient_id: int,
        payload: ContractCreateRequest,
        account: CurrentAccount,
    ) -> ContractResponse:
        if payload.end_date is not None and payload.start_date > payload.end_date:
            raise domain_error("VALIDATION_ERROR", 422, field="end_date")
        try:
            recipient = self.repo.get_recipient_for_update(recipient_id)
            if recipient is None:
                raise domain_error("RECIPIENT_NOT_FOUND", 404)
            by_id, by_code, group_by_type = self._service_meta()
            service_type = by_code.get(payload.service_type_code.value)
            if service_type is None or not service_type.active:
                raise domain_error("SERVICE_TYPE_NOT_FOUND", 422, field="service_type_code")

            issue_no = recipient.recipient_no is None
            counter = self.repo.lock_or_create_recipient_no_counter() if issue_no else None
            now = w1d_clock.now_utc()
            row = RecipientContract(
                recipient_id=recipient_id,
                service_type_id=service_type.id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                service_start_date=payload.service_start_date,
                end_reason_text=payload.end_reason_text,
                invalidated_at_utc=None,
                replacement_contract_id=None,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                created_at_utc=now,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(row)
            self._flush()
            w1d_fault.raise_if("after_contract_insert")

            if issue_no and counter is not None:
                counter.last_sequence = int(counter.last_sequence) + 1
                assigned = f"{counter.last_sequence:06d}"
                recipient.recipient_no = assigned
                recipient.updated_by_account_id = account.id
                recipient.updated_at_utc = now
                recipient.row_version = int(recipient.row_version) + 1
                self._flush()
                self.repo.append_audit(
                    actor_account_id=account.id,
                    action_code="RECIPIENT_NO_ASSIGN",
                    entity_type="RECIPIENT",
                    entity_pk=recipient_id,
                    before_json={"recipient_no": None},
                    after_json={"recipient_no": assigned},
                    reason_code="FIRST_CONTRACT",
                    request_id=self.request_id,
                    occurred_at_utc=now,
                )

            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="RECIPIENT_CONTRACT_CREATE",
                entity_type="RECIPIENT_CONTRACT",
                entity_pk=row.id,
                before_json=None,
                after_json={
                    "id": row.id,
                    "recipient_id": recipient_id,
                    "service_type_code": service_type.code,
                    "start_date": payload.start_date.isoformat(),
                    "end_date": payload.end_date.isoformat() if payload.end_date else None,
                },
                reason_code="USER_CREATE",
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._flush()
            self._commit()
            return self._to_response(row, by_id=by_id, group_by_type=group_by_type)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise

    def end_contract(
        self,
        recipient_id: int,
        contract_id: int,
        payload: ContractEndRequest,
        account: CurrentAccount,
    ) -> ContractResponse:
        try:
            recipient = self.repo.get_recipient_for_update(recipient_id)
            if recipient is None:
                raise domain_error("RECIPIENT_NOT_FOUND", 404)
            row = self.repo.get_contract(recipient_id, contract_id)
            if row is None or row.invalidated_at_utc is not None:
                raise domain_error("CONTRACT_NOT_FOUND", 404)
            if row.row_version != payload.expected_row_version:
                raise domain_error("ROW_VERSION_CONFLICT", 409)
            if row.end_date is not None:
                raise domain_error("CONTRACT_REACTIVATION_FORBIDDEN", 409)
            if payload.end_date < row.start_date:
                raise domain_error("VALIDATION_ERROR", 422, field="end_date")

            now = w1d_clock.now_utc()
            before = {"end_date": None, "row_version": row.row_version}
            row.end_date = payload.end_date
            row.end_reason_text = payload.end_reason_text
            row.updated_by_account_id = account.id
            row.updated_at_utc = now
            row.row_version = int(row.row_version) + 1
            self._flush()
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="RECIPIENT_CONTRACT_END",
                entity_type="RECIPIENT_CONTRACT",
                entity_pk=row.id,
                before_json=before,
                after_json={
                    "end_date": payload.end_date.isoformat(),
                    "row_version": row.row_version,
                },
                reason_code="USER_END",
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._flush()
            self._commit()
            by_id, _, group_by_type = self._service_meta()
            return self._to_response(row, by_id=by_id, group_by_type=group_by_type)
        except Exception:
            if self.session.in_transaction():
                self.session.rollback()
            raise
