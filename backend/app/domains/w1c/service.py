from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.db.models import (
    AuditEvent,
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationIdentity,
    RecipientCertificationPeriod,
    RecipientGradePeriod,
    RecipientLocalApprovalAmountPeriod,
)
from app.domains.recipient.errors import RecipientDomainError
from app.domains.recipient.schemas import HistoryInvalidateRequest
from app.domains.w1c.policies import normalize_certification_number, validate_period
from app.domains.w1c.repository import W1CRepository
from app.domains.w1c.schemas import (
    ApprovalAmountPeriodCreateRequest,
    ApprovalAmountPeriodListResponse,
    ApprovalAmountPeriodReplacementRequest,
    ApprovalAmountPeriodReplacementResponse,
    ApprovalAmountPeriodResponse,
    BenefitCode,
    BenefitPeriodCreateRequest,
    BenefitPeriodListResponse,
    BenefitPeriodReplacementRequest,
    BenefitPeriodReplacementResponse,
    BenefitPeriodResponse,
    CertificationIdentityCreateRequest,
    CertificationIdentityResponse,
    CertificationPeriodCreateRequest,
    CertificationPeriodListResponse,
    CertificationPeriodReplacementRequest,
    CertificationPeriodReplacementResponse,
    CertificationPeriodResponse,
    EffectiveBenefitResponse,
    GradeCode,
    GradePeriodCreateRequest,
    GradePeriodListResponse,
    GradePeriodReplacementRequest,
    GradePeriodReplacementResponse,
    GradePeriodResponse,
)

_MESSAGES = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "CERTIFICATION_IDENTITY_NOT_FOUND": "인정 본번호가 등록되지 않았습니다.",
    "CERTIFICATION_NUMBER_IN_USE": "해당 인정 본번호는 다른 수급자가 사용 중입니다.",
    "RECIPIENT_CERTIFICATION_NUMBER_FIXED": "수급자의 인정 본번호는 변경할 수 없습니다.",
    "CERTIFICATION_PERIOD_NOT_FOUND": "인정기간을 찾을 수 없습니다.",
    "CERTIFICATION_PERIOD_CONFLICT": "인정기간이 기존 기간과 겹칩니다.",
    "GRADE_PERIOD_NOT_FOUND": "등급기간을 찾을 수 없습니다.",
    "GRADE_PERIOD_CONFLICT": "등급기간이 기존 기간과 겹칩니다.",
    "GRADE_PERIOD_OUTSIDE_CERTIFICATION": "등급기간은 유효한 인정기간 안에 있어야 합니다.",
    "BENEFIT_PERIOD_NOT_FOUND": "혜택기간을 찾을 수 없습니다.",
    "BENEFIT_PERIOD_CONFLICT": "혜택기간이 기존 기간과 겹칩니다.",
    "APPROVAL_AMOUNT_PERIOD_NOT_FOUND": "지자체 승인금액 기간을 찾을 수 없습니다.",
    "APPROVED_AMOUNT_PERIOD_CONFLICT": "지자체 승인금액 기간이 기존 기간과 겹칩니다.",
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.",
    "VALIDATION_ERROR": "입력값을 확인하세요.",
    "UNEXPECTED_SERVER_ERROR": "요청을 처리하지 못했습니다.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _domain_error(
    code: str,
    status_code: int,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> RecipientDomainError:
    field_errors = []
    if field is not None:
        field_errors.append({"field": field, "message": _MESSAGES[code]})
    return RecipientDomainError(
        code=code,
        status_code=status_code,
        message=_MESSAGES[code],
        field_errors=field_errors,
        details=details or {},
    )


class W1CService:
    def __init__(
        self,
        database_session: Session,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.database_session = database_session
        self.repository = W1CRepository(database_session)
        self.request_id = request_id

    def _audit(
        self,
        *,
        account_id: int,
        action_code: str,
        entity_type: str,
        entity_pk: int,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        occurred_at_utc: datetime | None = None,
    ) -> None:
        self.repository.add(
            AuditEvent(
                occurred_at_utc=occurred_at_utc or _now(),
                actor_account_id=account_id,
                actor_kind="USER",
                action_code=action_code,
                entity_type=entity_type,
                entity_pk=entity_pk,
                before_json=before,
                after_json=after,
                request_id=self.request_id,
                created_from="API",
            )
        )

    @staticmethod
    def _map_integrity_error(error: IntegrityError) -> RecipientDomainError:
        original = getattr(error, "orig", None)
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        mapping = {
            "pk_recipient_certification_identity": (
                "RECIPIENT_CERTIFICATION_NUMBER_FIXED",
                409,
            ),
            "ck_recipient_certification_identity_immutable": (
                "RECIPIENT_CERTIFICATION_NUMBER_FIXED",
                409,
            ),
            "uq_recipient_certification_identity_certification_number": (
                "CERTIFICATION_NUMBER_IN_USE",
                409,
            ),
            "ex_recipient_certification_period": (
                "CERTIFICATION_PERIOD_CONFLICT",
                409,
            ),
            "ex_recipient_grade_period": ("GRADE_PERIOD_CONFLICT", 409),
            "ck_recipient_grade_period_containment": (
                "GRADE_PERIOD_OUTSIDE_CERTIFICATION",
                409,
            ),
            "ck_recipient_certification_period_grade_containment": (
                "GRADE_PERIOD_OUTSIDE_CERTIFICATION",
                409,
            ),
            "fk_recipient_grade_period_certification": (
                "GRADE_PERIOD_OUTSIDE_CERTIFICATION",
                409,
            ),
            "ex_recipient_benefit_period": ("BENEFIT_PERIOD_CONFLICT", 409),
            "ex_recipient_local_approval_amount_period": (
                "APPROVED_AMOUNT_PERIOD_CONFLICT",
                409,
            ),
        }
        mapped = mapping.get(constraint_name) if isinstance(constraint_name, str) else None
        if mapped is not None:
            return _domain_error(mapped[0], mapped[1])
        return _domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _flush(self) -> None:
        try:
            self.repository.flush()
        except IntegrityError as exc:
            self.database_session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.database_session.rollback()
            raise _domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _commit(self) -> None:
        if self.database_session.info.get("recipient_detail_batch_defer_commit"):
            self.database_session.flush()
            return
        try:
            self.database_session.commit()
        except IntegrityError as exc:
            self.database_session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.database_session.rollback()
            raise _domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    @staticmethod
    def _require_version(actual: int, expected: int, *, entity: str) -> None:
        if actual != expected:
            raise _domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={"current_row_version": actual, "entity": entity},
            )

    def _require_recipient(
        self,
        recipient_id: int,
        *,
        for_update: bool = False,
    ) -> Recipient:
        recipient = self.repository.get_recipient(recipient_id, for_update=for_update)
        if recipient is None:
            raise _domain_error("RECIPIENT_NOT_FOUND", 404)
        return recipient

    def _require_identity(
        self,
        recipient_id: int,
        *,
        for_update: bool = False,
    ) -> RecipientCertificationIdentity:
        identity = self.repository.get_identity(recipient_id, for_update=for_update)
        if identity is None:
            raise _domain_error("CERTIFICATION_IDENTITY_NOT_FOUND", 404)
        return identity

    def _require_certification_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientCertificationPeriod:
        period = self.repository.get_certification_period(
            recipient_id,
            period_id,
            for_update=for_update,
            active_only=active_only,
        )
        if period is None:
            historical = self.repository.get_certification_period(recipient_id, period_id)
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "certification_period",
                    },
                )
            raise _domain_error("CERTIFICATION_PERIOD_NOT_FOUND", 404)
        return period

    def _require_grade_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientGradePeriod:
        period = self.repository.get_grade_period(
            recipient_id,
            period_id,
            for_update=for_update,
            active_only=active_only,
        )
        if period is None:
            historical = self.repository.get_grade_period(recipient_id, period_id)
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "grade_period",
                    },
                )
            raise _domain_error("GRADE_PERIOD_NOT_FOUND", 404)
        return period

    def _require_benefit_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientBenefitPeriod:
        period = self.repository.get_benefit_period(
            recipient_id,
            period_id,
            for_update=for_update,
            active_only=active_only,
        )
        if period is None:
            historical = self.repository.get_benefit_period(recipient_id, period_id)
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "benefit_period",
                    },
                )
            raise _domain_error("BENEFIT_PERIOD_NOT_FOUND", 404)
        return period

    def _require_approval_amount_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientLocalApprovalAmountPeriod:
        period = self.repository.get_approval_amount_period(
            recipient_id,
            period_id,
            for_update=for_update,
            active_only=active_only,
        )
        if period is None:
            historical = self.repository.get_approval_amount_period(recipient_id, period_id)
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "approval_amount_period",
                    },
                )
            raise _domain_error("APPROVAL_AMOUNT_PERIOD_NOT_FOUND", 404)
        return period

    @staticmethod
    def _identity_response(
        identity: RecipientCertificationIdentity,
    ) -> CertificationIdentityResponse:
        return CertificationIdentityResponse(
            recipient_id=identity.recipient_id,
            certification_number=identity.certification_number,
            row_version=identity.row_version,
        )

    @staticmethod
    def _certification_response(
        period: RecipientCertificationPeriod,
    ) -> CertificationPeriodResponse:
        return CertificationPeriodResponse(
            id=period.id,
            recipient_id=period.recipient_id,
            start_date=period.start_date,
            end_date=period.end_date,
            invalidated_at_utc=period.invalidated_at_utc,
            replacement_certification_period_id=period.replacement_certification_period_id,
            row_version=period.row_version,
        )

    @staticmethod
    def _grade_response(period: RecipientGradePeriod) -> GradePeriodResponse:
        return GradePeriodResponse(
            id=period.id,
            recipient_id=period.recipient_id,
            certification_period_id=period.certification_period_id,
            grade_code=GradeCode(period.grade_code),
            start_date=period.start_date,
            end_date=period.end_date,
            invalidated_at_utc=period.invalidated_at_utc,
            replacement_grade_period_id=period.replacement_grade_period_id,
            row_version=period.row_version,
        )

    @staticmethod
    def _benefit_response(period: RecipientBenefitPeriod) -> BenefitPeriodResponse:
        return BenefitPeriodResponse(
            id=period.id,
            recipient_id=period.recipient_id,
            benefit_code=BenefitCode(period.benefit_code),
            start_date=period.start_date,
            end_date=period.end_date,
            invalidated_at_utc=period.invalidated_at_utc,
            replacement_benefit_period_id=period.replacement_benefit_period_id,
            row_version=period.row_version,
        )

    @staticmethod
    def _approval_response(
        period: RecipientLocalApprovalAmountPeriod,
    ) -> ApprovalAmountPeriodResponse:
        return ApprovalAmountPeriodResponse(
            id=period.id,
            recipient_id=period.recipient_id,
            amount_krw=period.amount_krw,
            start_date=period.start_date,
            end_date=period.end_date,
            invalidated_at_utc=period.invalidated_at_utc,
            replacement_local_approval_amount_period_id=(
                period.replacement_local_approval_amount_period_id
            ),
            row_version=period.row_version,
        )

    def create_identity(
        self,
        recipient_id: int,
        payload: CertificationIdentityCreateRequest,
        account: CurrentAccount,
    ) -> CertificationIdentityResponse:
        self._require_recipient(recipient_id, for_update=True)
        try:
            canonical = normalize_certification_number(payload.certification_number)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="certification_number") from None

        current = self.repository.get_identity(recipient_id, for_update=True)
        if current is not None:
            if current.certification_number == canonical:
                return self._identity_response(current)
            raise _domain_error(
                "RECIPIENT_CERTIFICATION_NUMBER_FIXED",
                409,
                field="certification_number",
            )
        owner = self.repository.get_identity_by_number(canonical)
        if owner is not None and owner.recipient_id != recipient_id:
            raise _domain_error(
                "CERTIFICATION_NUMBER_IN_USE",
                409,
                field="certification_number",
            )

        identity = RecipientCertificationIdentity(
            recipient_id=recipient_id,
            certification_number=canonical,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(identity)
        self._flush()
        response = self._identity_response(identity)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_CERTIFICATION_IDENTITY_CREATE",
            entity_type="RECIPIENT_CERTIFICATION_IDENTITY",
            entity_pk=recipient_id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    def get_identity(self, recipient_id: int) -> CertificationIdentityResponse:
        self._require_recipient(recipient_id)
        return self._identity_response(self._require_identity(recipient_id))

    def create_certification_period(
        self,
        recipient_id: int,
        payload: CertificationPeriodCreateRequest,
        account: CurrentAccount,
    ) -> CertificationPeriodResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        self._require_recipient(recipient_id)
        self._require_identity(recipient_id)
        period = RecipientCertificationPeriod(
            recipient_id=recipient_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(period)
        self._flush()
        response = self._certification_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_CERTIFICATION_PERIOD_CREATE",
            entity_type="RECIPIENT_CERTIFICATION_PERIOD",
            entity_pk=period.id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    def list_certification_periods(
        self,
        recipient_id: int,
    ) -> CertificationPeriodListResponse:
        self._require_recipient(recipient_id)
        return CertificationPeriodListResponse(
            items=[
                self._certification_response(item)
                for item in self.repository.list_certification_periods(recipient_id)
            ]
        )

    def invalidate_certification_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: HistoryInvalidateRequest,
        account: CurrentAccount,
    ) -> CertificationPeriodResponse:
        period = self._require_certification_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            period.row_version,
            payload.expected_row_version,
            entity="certification_period",
        )
        before = self._certification_response(period).model_dump(mode="json")
        period.invalidated_at_utc = _now()
        period.updated_at_utc = period.invalidated_at_utc
        period.updated_by_account_id = account.id
        period.row_version += 1
        self._flush()
        response = self._certification_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_CERTIFICATION_PERIOD_INVALIDATE",
            entity_type="RECIPIENT_CERTIFICATION_PERIOD",
            entity_pk=period.id,
            before=before,
            after=response.model_dump(mode="json"),
            occurred_at_utc=period.invalidated_at_utc,
        )
        self._commit()
        return response

    def replace_certification_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: CertificationPeriodReplacementRequest,
        account: CurrentAccount,
    ) -> CertificationPeriodReplacementResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        original = self._require_certification_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            original.row_version,
            payload.expected_row_version,
            entity="certification_period",
        )
        before = self._certification_response(original).model_dump(mode="json")
        changed_at = _now()
        original.invalidated_at_utc = changed_at
        original.updated_at_utc = changed_at
        original.updated_by_account_id = account.id
        original.row_version += 1
        self._flush()
        replacement = RecipientCertificationPeriod(
            recipient_id=recipient_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(replacement)
        self._flush()
        original.replacement_certification_period_id = replacement.id
        self._flush()
        original_response = self._certification_response(original)
        replacement_response = self._certification_response(replacement)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_CERTIFICATION_PERIOD_REPLACE",
            entity_type="RECIPIENT_CERTIFICATION_PERIOD",
            entity_pk=original.id,
            before=before,
            after=original_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_CERTIFICATION_PERIOD_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_CERTIFICATION_PERIOD",
            entity_pk=replacement.id,
            before=None,
            after=replacement_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._commit()
        return CertificationPeriodReplacementResponse(
            original=original_response,
            replacement=replacement_response,
        )

    def create_grade_period(
        self,
        recipient_id: int,
        payload: GradePeriodCreateRequest,
        account: CurrentAccount,
    ) -> GradePeriodResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        self._require_recipient(recipient_id)
        certification = self._require_certification_period(
            recipient_id,
            payload.certification_period_id,
            for_update=True,
            active_only=True,
        )
        if (
            payload.start_date < certification.start_date
            or payload.end_date > certification.end_date
        ):
            raise _domain_error("GRADE_PERIOD_OUTSIDE_CERTIFICATION", 409)
        period = RecipientGradePeriod(
            recipient_id=recipient_id,
            certification_period_id=payload.certification_period_id,
            grade_code=payload.grade_code.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(period)
        self._flush()
        response = self._grade_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_GRADE_PERIOD_CREATE",
            entity_type="RECIPIENT_GRADE_PERIOD",
            entity_pk=period.id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    def list_grade_periods(self, recipient_id: int) -> GradePeriodListResponse:
        self._require_recipient(recipient_id)
        return GradePeriodListResponse(
            items=[
                self._grade_response(item)
                for item in self.repository.list_grade_periods(recipient_id)
            ]
        )

    def invalidate_grade_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: HistoryInvalidateRequest,
        account: CurrentAccount,
    ) -> GradePeriodResponse:
        period = self._require_grade_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            period.row_version,
            payload.expected_row_version,
            entity="grade_period",
        )
        before = self._grade_response(period).model_dump(mode="json")
        period.invalidated_at_utc = _now()
        period.updated_at_utc = period.invalidated_at_utc
        period.updated_by_account_id = account.id
        period.row_version += 1
        self._flush()
        response = self._grade_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_GRADE_PERIOD_INVALIDATE",
            entity_type="RECIPIENT_GRADE_PERIOD",
            entity_pk=period.id,
            before=before,
            after=response.model_dump(mode="json"),
            occurred_at_utc=period.invalidated_at_utc,
        )
        self._commit()
        return response

    def replace_grade_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: GradePeriodReplacementRequest,
        account: CurrentAccount,
    ) -> GradePeriodReplacementResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        certification = self._require_certification_period(
            recipient_id,
            payload.certification_period_id,
            for_update=True,
            active_only=True,
        )
        if (
            payload.start_date < certification.start_date
            or payload.end_date > certification.end_date
        ):
            raise _domain_error("GRADE_PERIOD_OUTSIDE_CERTIFICATION", 409)
        original = self._require_grade_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            original.row_version,
            payload.expected_row_version,
            entity="grade_period",
        )
        before = self._grade_response(original).model_dump(mode="json")
        changed_at = _now()
        original.invalidated_at_utc = changed_at
        original.updated_at_utc = changed_at
        original.updated_by_account_id = account.id
        original.row_version += 1
        self._flush()
        replacement = RecipientGradePeriod(
            recipient_id=recipient_id,
            certification_period_id=payload.certification_period_id,
            grade_code=payload.grade_code.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(replacement)
        self._flush()
        original.replacement_grade_period_id = replacement.id
        self._flush()
        original_response = self._grade_response(original)
        replacement_response = self._grade_response(replacement)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_GRADE_PERIOD_REPLACE",
            entity_type="RECIPIENT_GRADE_PERIOD",
            entity_pk=original.id,
            before=before,
            after=original_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_GRADE_PERIOD_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_GRADE_PERIOD",
            entity_pk=replacement.id,
            before=None,
            after=replacement_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._commit()
        return GradePeriodReplacementResponse(
            original=original_response,
            replacement=replacement_response,
        )

    def create_benefit_period(
        self,
        recipient_id: int,
        payload: BenefitPeriodCreateRequest,
        account: CurrentAccount,
    ) -> BenefitPeriodResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        self._require_recipient(recipient_id)
        period = RecipientBenefitPeriod(
            recipient_id=recipient_id,
            benefit_code=payload.benefit_code.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(period)
        self._flush()
        response = self._benefit_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_BENEFIT_PERIOD_CREATE",
            entity_type="RECIPIENT_BENEFIT_PERIOD",
            entity_pk=period.id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    def list_benefit_periods(self, recipient_id: int) -> BenefitPeriodListResponse:
        self._require_recipient(recipient_id)
        return BenefitPeriodListResponse(
            items=[
                self._benefit_response(item)
                for item in self.repository.list_benefit_periods(recipient_id)
            ]
        )

    def get_effective_benefit(
        self,
        recipient_id: int,
        on_date: date,
    ) -> EffectiveBenefitResponse:
        self._require_recipient(recipient_id)
        item = self.repository.get_effective_benefit(recipient_id, on_date)
        return EffectiveBenefitResponse(
            on_date=on_date,
            item=self._benefit_response(item) if item is not None else None,
        )

    def invalidate_benefit_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: HistoryInvalidateRequest,
        account: CurrentAccount,
    ) -> BenefitPeriodResponse:
        period = self._require_benefit_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            period.row_version,
            payload.expected_row_version,
            entity="benefit_period",
        )
        before = self._benefit_response(period).model_dump(mode="json")
        period.invalidated_at_utc = _now()
        period.updated_at_utc = period.invalidated_at_utc
        period.updated_by_account_id = account.id
        period.row_version += 1
        self._flush()
        response = self._benefit_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_BENEFIT_PERIOD_INVALIDATE",
            entity_type="RECIPIENT_BENEFIT_PERIOD",
            entity_pk=period.id,
            before=before,
            after=response.model_dump(mode="json"),
            occurred_at_utc=period.invalidated_at_utc,
        )
        self._commit()
        return response

    def replace_benefit_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: BenefitPeriodReplacementRequest,
        account: CurrentAccount,
    ) -> BenefitPeriodReplacementResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        original = self._require_benefit_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            original.row_version,
            payload.expected_row_version,
            entity="benefit_period",
        )
        before = self._benefit_response(original).model_dump(mode="json")
        changed_at = _now()
        original.invalidated_at_utc = changed_at
        original.updated_at_utc = changed_at
        original.updated_by_account_id = account.id
        original.row_version += 1
        self._flush()
        replacement = RecipientBenefitPeriod(
            recipient_id=recipient_id,
            benefit_code=payload.benefit_code.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(replacement)
        self._flush()
        original.replacement_benefit_period_id = replacement.id
        self._flush()
        original_response = self._benefit_response(original)
        replacement_response = self._benefit_response(replacement)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_BENEFIT_PERIOD_REPLACE",
            entity_type="RECIPIENT_BENEFIT_PERIOD",
            entity_pk=original.id,
            before=before,
            after=original_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_BENEFIT_PERIOD_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_BENEFIT_PERIOD",
            entity_pk=replacement.id,
            before=None,
            after=replacement_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._commit()
        return BenefitPeriodReplacementResponse(
            original=original_response,
            replacement=replacement_response,
        )

    def create_approval_amount_period(
        self,
        recipient_id: int,
        payload: ApprovalAmountPeriodCreateRequest,
        account: CurrentAccount,
    ) -> ApprovalAmountPeriodResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        self._require_recipient(recipient_id)
        period = RecipientLocalApprovalAmountPeriod(
            recipient_id=recipient_id,
            amount_krw=payload.amount_krw,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(period)
        self._flush()
        response = self._approval_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_APPROVAL_AMOUNT_PERIOD_CREATE",
            entity_type="RECIPIENT_LOCAL_APPROVAL_AMOUNT_PERIOD",
            entity_pk=period.id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    def list_approval_amount_periods(
        self,
        recipient_id: int,
    ) -> ApprovalAmountPeriodListResponse:
        self._require_recipient(recipient_id)
        return ApprovalAmountPeriodListResponse(
            items=[
                self._approval_response(item)
                for item in self.repository.list_approval_amount_periods(recipient_id)
            ]
        )

    def invalidate_approval_amount_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: HistoryInvalidateRequest,
        account: CurrentAccount,
    ) -> ApprovalAmountPeriodResponse:
        period = self._require_approval_amount_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            period.row_version,
            payload.expected_row_version,
            entity="approval_amount_period",
        )
        before = self._approval_response(period).model_dump(mode="json")
        period.invalidated_at_utc = _now()
        period.updated_at_utc = period.invalidated_at_utc
        period.updated_by_account_id = account.id
        period.row_version += 1
        self._flush()
        response = self._approval_response(period)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_APPROVAL_AMOUNT_PERIOD_INVALIDATE",
            entity_type="RECIPIENT_LOCAL_APPROVAL_AMOUNT_PERIOD",
            entity_pk=period.id,
            before=before,
            after=response.model_dump(mode="json"),
            occurred_at_utc=period.invalidated_at_utc,
        )
        self._commit()
        return response

    def replace_approval_amount_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: ApprovalAmountPeriodReplacementRequest,
        account: CurrentAccount,
    ) -> ApprovalAmountPeriodReplacementResponse:
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        original = self._require_approval_amount_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            original.row_version,
            payload.expected_row_version,
            entity="approval_amount_period",
        )
        before = self._approval_response(original).model_dump(mode="json")
        changed_at = _now()
        original.invalidated_at_utc = changed_at
        original.updated_at_utc = changed_at
        original.updated_by_account_id = account.id
        original.row_version += 1
        self._flush()
        replacement = RecipientLocalApprovalAmountPeriod(
            recipient_id=recipient_id,
            amount_krw=payload.amount_krw,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        self.repository.add(replacement)
        self._flush()
        original.replacement_local_approval_amount_period_id = replacement.id
        self._flush()
        original_response = self._approval_response(original)
        replacement_response = self._approval_response(replacement)
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_APPROVAL_AMOUNT_PERIOD_REPLACE",
            entity_type="RECIPIENT_LOCAL_APPROVAL_AMOUNT_PERIOD",
            entity_pk=original.id,
            before=before,
            after=original_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._audit(
            account_id=account.id,
            action_code="RECIPIENT_APPROVAL_AMOUNT_PERIOD_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_LOCAL_APPROVAL_AMOUNT_PERIOD",
            entity_pk=replacement.id,
            before=None,
            after=replacement_response.model_dump(mode="json"),
            occurred_at_utc=changed_at,
        )
        self._commit()
        return ApprovalAmountPeriodReplacementResponse(
            original=original_response,
            replacement=replacement_response,
        )
