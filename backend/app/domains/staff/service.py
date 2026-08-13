from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Protocol, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.core.security import PinProtector
from app.core.settings import Settings
from app.db.models import (
    AccessEvent,
    AuditEvent,
    AuthEvent,
    LicenseType,
    ServiceType,
    Staff,
    StaffEmployment,
    StaffHealthCheck,
    StaffLicense,
    StaffOnboardingTraining,
    StaffOperationalRolePeriod,
    StaffPeriodicTrainingStatus,
    StaffPositionPeriod,
    StaffQuarterlyConsultation,
    StaffSensitiveIdentity,
    StaffServiceQualificationPeriod,
    UserAccount,
)
from app.domains.staff.crypto import decrypt_resident_number, encrypt_resident_number
from app.domains.staff.errors import StaffDomainError
from app.domains.staff.policies import (
    mask_resident_number,
    normalize_phone_number,
    normalize_role_code,
    validate_resident_number,
)
from app.domains.staff.repository import StaffRepository
from app.domains.staff.schemas import (
    EmploymentStatus,
    InitialOperationalRoleRequest,
    InitialPositionRequest,
    LicenseTypeListResponse,
    LicenseTypeResponse,
    PositionCode,
    SensitiveIdentityRevealResponse,
    ServiceCatalogResponse,
    ServiceTypeResponse,
    StaffCreateRequest,
    StaffCreateResponse,
    StaffDetailResponse,
    StaffEmploymentCloseRequest,
    StaffEmploymentCreateRequest,
    StaffEmploymentReplacementRequest,
    StaffEmploymentResponse,
    StaffHealthCheckCreateRequest,
    StaffHealthCheckListResponse,
    StaffHealthCheckResponse,
    StaffHealthCheckUpdateRequest,
    StaffLicenseCreateRequest,
    StaffLicenseInvalidateRequest,
    StaffLicenseListResponse,
    StaffLicenseReplacementRequest,
    StaffLicenseResponse,
    StaffListResponse,
    StaffOnboardingTrainingListResponse,
    StaffOnboardingTrainingResponse,
    StaffOnboardingTrainingUpdateRequest,
    StaffOperationalRoleCreateRequest,
    StaffOperationalRolePeriodResponse,
    StaffOperationalRoleReplacementRequest,
    StaffPeriodCloseRequest,
    StaffPeriodicTrainingCreateRequest,
    StaffPeriodicTrainingInvalidateRequest,
    StaffPeriodicTrainingListResponse,
    StaffPeriodicTrainingResponse,
    StaffPeriodicTrainingUpdateRequest,
    StaffPositionCreateRequest,
    StaffPositionPeriodResponse,
    StaffPositionReplacementRequest,
    StaffQuarterlyConsultationCreateRequest,
    StaffQuarterlyConsultationListResponse,
    StaffQuarterlyConsultationResponse,
    StaffQuarterlyConsultationUpdateRequest,
    StaffResponse,
    StaffServiceQualificationCloseRequest,
    StaffServiceQualificationCreateRequest,
    StaffServiceQualificationInvalidateRequest,
    StaffServiceQualificationListResponse,
    StaffServiceQualificationReplacementRequest,
    StaffServiceQualificationResponse,
    StaffUpdateRequest,
    TrainingCourseListResponse,
    TrainingCourseResponse,
)


class MutablePeriod(Protocol):
    id: int
    start_date: date
    end_date: date | None
    invalidated_at_utc: datetime | None
    replacement_id: int | None
    updated_by_account_id: int
    updated_at_utc: datetime
    row_version: int


class DatedPeriod(Protocol):
    start_date: date
    end_date: date | None


PeriodT = TypeVar("PeriodT", bound=MutablePeriod)
ResponseT = TypeVar("ResponseT")

_MESSAGES = {
    "STAFF_EMPLOYMENT_PERIOD_CONFLICT": "재직기간이 기존 재직기간과 겹칩니다.",
    "STAFF_PERIOD_CONFLICT": "직종 또는 업무역할 기간이 기존 기간과 겹칩니다.",
    "STAFF_PERIOD_OUTSIDE_EMPLOYMENT": "직종 또는 업무역할 기간은 재직기간 안에 있어야 합니다.",
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.",
    "RESIDENT_NUMBER_DUPLICATE": "이미 등록된 주민등록번호입니다.",
    "RESIDENT_NUMBER_INVALID": "주민등록번호와 생년월일 또는 성별을 확인하세요.",
    "PHONE_NUMBER_INVALID": "전화번호 형식을 확인하세요.",
    "CURRENT_PIN_INVALID": "현재 PIN이 올바르지 않습니다.",
    "ACCOUNT_LOCKED": "로그인 실패가 누적되어 계정이 잠겼습니다.",
    "SENSITIVE_IDENTITY_DECRYPTION_FAILED": "민감정보를 안전하게 복호화하지 못했습니다.",
    "SENSITIVE_IDENTITY_NOT_FOUND": "등록된 주민등록번호가 없습니다.",
    "STAFF_NOT_FOUND": "직원을 찾을 수 없습니다.",
    "STAFF_EMPLOYMENT_NOT_FOUND": "직원의 재직 이력을 찾을 수 없습니다.",
    "STAFF_ONBOARDING_TRAINING_NOT_FOUND": "신규직원교육 이력을 찾을 수 없습니다.",
    "STAFF_PERIODIC_TRAINING_NOT_FOUND": "정기교육 이력을 찾을 수 없습니다.",
    "STAFF_TRAINING_COURSE_NOT_FOUND": "교육과목을 찾을 수 없습니다.",
    "STAFF_TRAINING_DUPLICATE": "같은 직원·과목·기간의 교육 이력이 이미 있습니다.",
    "STAFF_TRAINING_INVALID_CYCLE": "교육과목의 주기와 원장 유형이 맞지 않습니다.",
    "STAFF_TRAINING_PERIOD_INVALID": "교육 대상기간 형식을 확인하세요.",
    "STAFF_TRAINING_STAFF_MISMATCH": "교육 이력의 직원이 요청 대상과 다릅니다.",
    "STAFF_LICENSE_NOT_FOUND": "자격증 이력을 찾을 수 없습니다.",
    "STAFF_LICENSE_DUPLICATE": "같은 자격종류와 자격번호가 이미 등록되어 있습니다.",
    "LICENSE_TYPE_NOT_FOUND": "자격종류를 찾을 수 없습니다.",
    "SERVICE_TYPE_NOT_FOUND": "서비스종류를 찾을 수 없습니다.",
    "STAFF_SERVICE_QUALIFICATION_NOT_FOUND": "서비스 제공자격 이력을 찾을 수 없습니다.",
    "STAFF_SERVICE_QUALIFICATION_CONFLICT": "서비스 제공자격 기간이 기존 기간과 겹칩니다.",
    "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH": (
        "근거 자격증은 같은 직원의 유효 자격증이어야 합니다."
    ),
    "EMPLOYMENT_NOT_FOUND": "재직 이력을 찾을 수 없습니다.",
    "PERIOD_NOT_FOUND": "기간 이력을 찾을 수 없습니다.",
    "VALIDATION_ERROR": "입력값을 확인하세요.",
    "UNEXPECTED_SERVER_ERROR": "요청을 처리하지 못했습니다.",
}
_BUSINESS_TIMEZONE = timezone(timedelta(hours=9), "KST")


def _now() -> datetime:
    return datetime.now(UTC)


def _domain_error(
    code: str,
    status_code: int,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> StaffDomainError:
    field_errors = []
    if field is not None:
        field_errors.append({"field": field, "message": _MESSAGES[code]})
    return StaffDomainError(
        code=code,
        status_code=status_code,
        message=_MESSAGES[code],
        field_errors=field_errors,
        details=details or {},
    )


class StaffService:
    def __init__(
        self,
        database_session: Session,
        settings: Settings,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.database_session = database_session
        self.settings = settings
        self.repository = StaffRepository(database_session)
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
    ) -> None:
        self.repository.add(
            AuditEvent(
                occurred_at_utc=_now(),
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

    def _map_integrity_error(self, error: IntegrityError) -> StaffDomainError:
        quarterly_error = self._map_quarterly_integrity_error(error)
        if quarterly_error is not None:
            return quarterly_error
        health_error = self._map_health_integrity_error(error)
        if health_error is not None:
            return health_error
        original = error.orig
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        safe_message = str(original)

        if constraint_name == "uq_staff_sensitive_identity_lookup_hmac":
            return _domain_error("RESIDENT_NUMBER_DUPLICATE", 409, field="resident_number")
        if constraint_name == "uq_staff_license_type_number_active":
            return _domain_error("STAFF_LICENSE_DUPLICATE", 409, field="license_number")
        if constraint_name in {
            "uq_staff_onboarding_training_active",
            "uq_staff_periodic_training_active",
        }:
            return _domain_error("STAFF_TRAINING_DUPLICATE", 409)
        if constraint_name == "ex_staff_service_qualification_period":
            return _domain_error("STAFF_SERVICE_QUALIFICATION_CONFLICT", 409)
        if constraint_name == "ex_staff_employment_period":
            return _domain_error("STAFF_EMPLOYMENT_PERIOD_CONFLICT", 409)
        if constraint_name in {
            "ex_staff_position_period",
            "ex_staff_operational_role_period",
        }:
            return _domain_error("STAFF_PERIOD_CONFLICT", 409)
        if constraint_name == "fk_staff_service_qualification_period_source_license":
            return _domain_error("STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH", 422)
        if "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH" in safe_message:
            return _domain_error("STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH", 422)
        if "STAFF_PERIOD_OUTSIDE_EMPLOYMENT" in safe_message:
            return _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)
        if "STAFF_TRAINING_INVALID_CYCLE" in safe_message:
            return _domain_error("STAFF_TRAINING_INVALID_CYCLE", 409)
        if "STAFF_TRAINING_PERIOD_INVALID" in safe_message:
            return _domain_error("STAFF_TRAINING_PERIOD_INVALID", 422, field="period_key")
        return _domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _commit(self) -> None:
        try:
            self.database_session.commit()
        except IntegrityError as exc:
            self.database_session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.database_session.rollback()
            raise _domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _flush(self) -> None:
        try:
            self.repository.flush()
        except IntegrityError as exc:
            self.database_session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.database_session.rollback()
            raise _domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    @staticmethod
    def _require_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise _domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={"current_row_version": actual},
            )

    def _require_staff(self, staff_id: int, *, for_update: bool = False) -> Staff:
        staff = self.repository.get_staff(staff_id, for_update=for_update)
        if staff is None:
            raise _domain_error("STAFF_NOT_FOUND", 404)
        return staff

    def _require_employment(
        self,
        staff_id: int,
        employment_id: int,
        *,
        for_update: bool = False,
    ) -> StaffEmployment:
        employment = self.repository.get_employment(
            staff_id,
            employment_id,
            for_update=for_update,
        )
        if employment is None:
            raise _domain_error("EMPLOYMENT_NOT_FOUND", 404)
        return employment

    @staticmethod
    def _validate_period(start_date: date, end_date: date | None) -> None:
        if end_date is not None and start_date > end_date:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date")

    @staticmethod
    def _validate_child_period(
        employment: StaffEmployment,
        start_date: date,
        end_date: date | None,
    ) -> None:
        StaffService._validate_period(start_date, end_date)
        if start_date < employment.start_date:
            raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)
        if employment.end_date is not None and (end_date is None or end_date > employment.end_date):
            raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)

    @staticmethod
    def _employment_response(
        employment: StaffEmployment,
        *,
        as_of: date,
    ) -> StaffEmploymentResponse:
        active = employment.start_date <= as_of and (
            employment.end_date is None or employment.end_date >= as_of
        )
        return StaffEmploymentResponse(
            id=employment.id,
            staff_id=employment.staff_id,
            employment_no=employment.employment_no,
            staff_no=employment.staff_no,
            start_date=employment.start_date,
            end_date=employment.end_date,
            end_reason_code=employment.end_reason_code,
            status=EmploymentStatus.ACTIVE if active else EmploymentStatus.ENDED,
            row_version=employment.row_version,
        )

    @staticmethod
    def _position_response(period: StaffPositionPeriod) -> StaffPositionPeriodResponse:
        return StaffPositionPeriodResponse(
            id=period.id,
            staff_id=period.staff_id,
            employment_id=period.employment_id,
            position_code=PositionCode(period.position_code),
            start_date=period.start_date,
            end_date=period.end_date,
            row_version=period.row_version,
        )

    @staticmethod
    def _role_response(
        period: StaffOperationalRolePeriod,
    ) -> StaffOperationalRolePeriodResponse:
        return StaffOperationalRolePeriodResponse(
            id=period.id,
            staff_id=period.staff_id,
            employment_id=period.employment_id,
            role_code=period.role_code,
            start_date=period.start_date,
            end_date=period.end_date,
            row_version=period.row_version,
        )

    def _response_for_staff(self, staff: Staff, *, detail: bool) -> StaffResponse:
        employments = self.repository.list_employments(staff.id)
        positions = self.repository.list_positions(staff.id)
        roles = self.repository.list_operational_roles(staff.id)
        sensitive_identity = self.repository.get_sensitive_identity(staff.id)

        as_of = _now().astimezone(_BUSINESS_TIMEZONE).date()

        def contains(period: DatedPeriod) -> bool:
            return period.start_date <= as_of and (
                period.end_date is None or as_of <= period.end_date
            )

        eligible_employments = [employment for employment in employments if contains(employment)]
        latest_employment = (
            max(eligible_employments, key=lambda employment: (employment.start_date, employment.id))
            if eligible_employments
            else None
        )
        current_positions = (
            [
                period
                for period in positions
                if period.employment_id == latest_employment.id and contains(period)
            ]
            if latest_employment is not None
            else []
        )
        current_roles = (
            [
                period
                for period in roles
                if period.employment_id == latest_employment.id and contains(period)
            ]
            if latest_employment is not None
            else []
        )
        common: dict[str, Any] = {
            "id": staff.id,
            "name": staff.name,
            "birth_date": staff.birth_date,
            "sex_code": staff.sex_code,
            "phone": staff.phone,
            "address": staff.address,
            "display_name": staff.display_name,
            "memo": staff.memo,
            "resident_number_masked": (
                mask_resident_number(staff.birth_date) if sensitive_identity is not None else None
            ),
            "row_version": staff.row_version,
            "current_employment": (
                self._employment_response(latest_employment, as_of=as_of)
                if latest_employment is not None
                else None
            ),
            "current_positions": [self._position_response(period) for period in current_positions],
            "current_operational_roles": [self._role_response(period) for period in current_roles],
        }
        if not detail:
            return StaffResponse(**common)
        return StaffDetailResponse(
            **common,
            employments=[
                self._employment_response(employment, as_of=as_of) for employment in employments
            ],
            positions=[self._position_response(period) for period in positions],
            operational_roles=[self._role_response(period) for period in roles],
        )

    def create_staff(
        self,
        payload: StaffCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffCreateResponse:
        try:
            phone, phone_normalized = normalize_phone_number(payload.phone)
        except ValueError:
            raise _domain_error("PHONE_NUMBER_INVALID", 422, field="phone") from None
        try:
            resident_number = validate_resident_number(
                rrn_input=payload.resident_number,
                expected_birth_date=payload.birth_date,
                expected_sex_code=payload.sex_code.value,
            )
        except ValueError:
            raise _domain_error(
                "RESIDENT_NUMBER_INVALID",
                422,
                field="resident_number",
            ) from None

        initial = payload.initial_employment
        for position in initial.initial_positions:
            self._validate_period(position.start_date, position.end_date)
            if position.start_date < initial.start_date:
                raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)
        for role in initial.initial_operational_roles:
            self._validate_period(role.start_date, role.end_date)
            if role.start_date < initial.start_date:
                raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)

        name = payload.name.strip()
        if not name:
            raise _domain_error("VALIDATION_ERROR", 422, field="name")
        staff = Staff(
            name=name,
            birth_date=payload.birth_date,
            sex_code=payload.sex_code.value,
            phone=phone,
            phone_normalized=phone_normalized,
            address=payload.address,
            display_name=payload.display_name,
            memo=payload.memo,
        )
        self.repository.add(staff)
        self._flush()

        encrypted = encrypt_resident_number(
            staff_id=staff.id,
            resident_number=resident_number,
            settings=self.settings,
        )
        self.repository.add(
            StaffSensitiveIdentity(
                staff_id=staff.id,
                resident_number_ciphertext=encrypted.ciphertext,
                resident_number_nonce=encrypted.nonce,
                resident_number_key_version=encrypted.key_version,
                resident_number_lookup_hmac=encrypted.lookup_hmac,
            )
        )

        employment = self._new_employment(
            staff=staff,
            start_date=initial.start_date,
            current_account=current_account,
        )
        self._flush()
        onboarding = self._new_onboarding_training(
            employment=employment,
            current_account=current_account,
        )
        if onboarding is not None:
            self._flush()
            self._audit(
                account_id=current_account.id,
                action_code="STAFF_ONBOARDING_TRAINING_CREATE",
                entity_type="STAFF_ONBOARDING_TRAINING",
                entity_pk=onboarding.id,
                before=None,
                after={
                    "staff_id": onboarding.staff_id,
                    "employment_id": onboarding.employment_id,
                    "course_code": onboarding.course_code,
                    "completed": onboarding.completed,
                    "row_version": onboarding.row_version,
                },
            )
        for position in initial.initial_positions:
            self.repository.add(
                self._new_position(
                    staff.id,
                    employment.id,
                    position,
                    current_account.id,
                )
            )
        for role in initial.initial_operational_roles:
            self.repository.add(
                self._new_role(
                    staff.id,
                    employment.id,
                    role,
                    current_account.id,
                )
            )
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_CREATE",
            entity_type="STAFF",
            entity_pk=staff.id,
            before=None,
            after={
                "name": staff.name,
                "birth_date": staff.birth_date.isoformat(),
                "sex_code": staff.sex_code,
                "employment_start_date": employment.start_date.isoformat(),
            },
        )
        self._commit()
        response = self._response_for_staff(staff, detail=True)
        return StaffCreateResponse(**response.model_dump())

    def _new_employment(
        self,
        *,
        staff: Staff,
        start_date: date,
        current_account: CurrentAccount,
    ) -> StaffEmployment:
        sequence = self.repository.next_staff_number(start_date.year)
        employment = StaffEmployment(
            staff_id=staff.id,
            employment_no=self.repository.next_employment_number(staff.id),
            staff_no=f"{start_date.year}-{sequence:03d}",
            staff_no_year=start_date.year,
            staff_no_sequence=sequence,
            start_date=start_date,
            created_by_account_id=current_account.id,
            updated_by_account_id=current_account.id,
        )
        self.repository.add(employment)
        return employment

    def _new_onboarding_training(
        self,
        *,
        employment: StaffEmployment,
        current_account: CurrentAccount,
    ) -> StaffOnboardingTraining | None:
        if not self.repository.training_schema_available():
            return None
        course = self.repository.get_training_course("NEW_HIRE_ORIENTATION")
        if course is None:
            raise _domain_error("STAFF_TRAINING_COURSE_NOT_FOUND", 500)
        now = _now()
        training = StaffOnboardingTraining(
            staff_id=employment.staff_id,
            employment_id=employment.id,
            course_code=course.code,
            completed=False,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(training)
        return training

    @staticmethod
    def _new_position(
        staff_id: int,
        employment_id: int,
        payload: InitialPositionRequest,
        account_id: int,
    ) -> StaffPositionPeriod:
        return StaffPositionPeriod(
            staff_id=staff_id,
            employment_id=employment_id,
            position_code=payload.position_code.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
        )

    @staticmethod
    def _new_role(
        staff_id: int,
        employment_id: int,
        payload: InitialOperationalRoleRequest,
        account_id: int,
    ) -> StaffOperationalRolePeriod:
        try:
            role_code = normalize_role_code(payload.role_code)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="role_code") from None
        return StaffOperationalRolePeriod(
            staff_id=staff_id,
            employment_id=employment_id,
            role_code=role_code,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
        )

    def list_staff(
        self,
        *,
        search: str | None,
        page: int,
        page_size: int,
    ) -> StaffListResponse:
        items, total = self.repository.list_staff(
            search=search,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return StaffListResponse(
            items=[self._response_for_staff(item, detail=False) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_staff_detail(self, staff_id: int) -> StaffDetailResponse:
        staff = self._require_staff(staff_id)
        response = self._response_for_staff(staff, detail=True)
        if not isinstance(response, StaffDetailResponse):
            raise RuntimeError("detail response construction failed")
        return response

    def update_staff(
        self,
        staff_id: int,
        payload: StaffUpdateRequest,
        current_account: CurrentAccount,
    ) -> StaffDetailResponse:
        staff = self._require_staff(staff_id, for_update=True)
        self._require_version(staff.row_version, payload.expected_staff_row_version)
        before = {
            "name": staff.name,
            "phone": staff.phone,
            "address": staff.address,
            "display_name": staff.display_name,
            "memo": staff.memo,
            "row_version": staff.row_version,
        }
        fields_set = payload.model_fields_set
        if "name" in fields_set:
            name = (payload.name or "").strip()
            if not name:
                raise _domain_error("VALIDATION_ERROR", 422, field="name")
            staff.name = name
        if "phone" in fields_set:
            try:
                staff.phone, staff.phone_normalized = normalize_phone_number(payload.phone)
            except ValueError:
                raise _domain_error("PHONE_NUMBER_INVALID", 422, field="phone") from None
        for field_name in ("address", "display_name", "memo"):
            if field_name in fields_set:
                setattr(staff, field_name, getattr(payload, field_name))
        staff.row_version += 1
        staff.updated_at_utc = _now()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_UPDATE",
            entity_type="STAFF",
            entity_pk=staff.id,
            before=before,
            after={
                "name": staff.name,
                "phone": staff.phone,
                "address": staff.address,
                "display_name": staff.display_name,
                "memo": staff.memo,
                "row_version": staff.row_version,
            },
        )
        self._commit()
        return self.get_staff_detail(staff.id)

    def create_employment(
        self,
        staff_id: int,
        payload: StaffEmploymentCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffEmploymentResponse:
        staff = self._require_staff(staff_id, for_update=True)
        self._require_version(staff.row_version, payload.expected_staff_row_version)
        employment = self._new_employment(
            staff=staff,
            start_date=payload.start_date,
            current_account=current_account,
        )
        staff.row_version += 1
        staff.updated_at_utc = _now()
        self._flush()
        onboarding = self._new_onboarding_training(
            employment=employment,
            current_account=current_account,
        )
        if onboarding is not None:
            self._flush()
            self._audit(
                account_id=current_account.id,
                action_code="STAFF_ONBOARDING_TRAINING_CREATE",
                entity_type="STAFF_ONBOARDING_TRAINING",
                entity_pk=onboarding.id,
                before=None,
                after={
                    "staff_id": onboarding.staff_id,
                    "employment_id": onboarding.employment_id,
                    "course_code": onboarding.course_code,
                    "completed": onboarding.completed,
                    "row_version": onboarding.row_version,
                },
            )
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_EMPLOYMENT_CREATE",
            entity_type="STAFF_EMPLOYMENT",
            entity_pk=employment.id,
            before=None,
            after={
                "staff_id": staff.id,
                "start_date": employment.start_date.isoformat(),
                "staff_no": employment.staff_no,
            },
        )
        self._commit()
        return self._employment_response(
            employment,
            as_of=_now().astimezone(_BUSINESS_TIMEZONE).date(),
        )

    @staticmethod
    def _version_map(items: list[Any]) -> dict[int, int]:
        return {item.period_id: item.expected_row_version for item in items}

    def close_employment(
        self,
        staff_id: int,
        employment_id: int,
        payload: StaffEmploymentCloseRequest,
        current_account: CurrentAccount,
    ) -> StaffEmploymentResponse:
        employment = self._require_employment(staff_id, employment_id, for_update=True)
        self._require_version(
            employment.row_version,
            payload.expected_employment_row_version,
        )
        if employment.end_date is not None or payload.end_date < employment.start_date:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date")

        positions = [
            period
            for period in self.repository.list_positions(
                staff_id,
                employment_id=employment_id,
                for_update=True,
            )
            if period.end_date is None
        ]
        roles = [
            period
            for period in self.repository.list_operational_roles(
                staff_id,
                employment_id=employment_id,
                for_update=True,
            )
            if period.end_date is None
        ]
        position_versions = self._version_map(payload.open_position_versions)
        role_versions = self._version_map(payload.open_operational_role_versions)
        if set(position_versions) != {period.id for period in positions}:
            raise _domain_error("ROW_VERSION_CONFLICT", 409)
        if set(role_versions) != {period.id for period in roles}:
            raise _domain_error("ROW_VERSION_CONFLICT", 409)

        for position_period in positions:
            self._require_version(
                position_period.row_version,
                position_versions[position_period.id],
            )
            if position_period.start_date > payload.end_date:
                raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)
            position_period.end_date = payload.end_date
            position_period.updated_by_account_id = current_account.id
            position_period.updated_at_utc = _now()
            position_period.row_version += 1
        for role_period in roles:
            self._require_version(
                role_period.row_version,
                role_versions[role_period.id],
            )
            if role_period.start_date > payload.end_date:
                raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)
            role_period.end_date = payload.end_date
            role_period.updated_by_account_id = current_account.id
            role_period.updated_at_utc = _now()
            role_period.row_version += 1

        before = {
            "end_date": None,
            "end_reason_code": employment.end_reason_code,
            "row_version": employment.row_version,
        }
        employment.end_date = payload.end_date
        employment.end_reason_code = payload.end_reason_code
        employment.updated_by_account_id = current_account.id
        employment.updated_at_utc = _now()
        employment.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_EMPLOYMENT_CLOSE",
            entity_type="STAFF_EMPLOYMENT",
            entity_pk=employment.id,
            before=before,
            after={
                "end_date": employment.end_date.isoformat(),
                "end_reason_code": employment.end_reason_code,
                "row_version": employment.row_version,
            },
        )
        self._commit()
        return self._employment_response(
            employment,
            as_of=_now().astimezone(_BUSINESS_TIMEZONE).date(),
        )

    def replace_employment(
        self,
        staff_id: int,
        employment_id: int,
        payload: StaffEmploymentReplacementRequest,
        current_account: CurrentAccount,
    ) -> StaffEmploymentResponse:
        staff = self._require_staff(staff_id, for_update=True)
        old = self._require_employment(staff_id, employment_id, for_update=True)
        self._require_version(old.row_version, payload.expected_employment_row_version)
        self._validate_period(payload.start_date, payload.end_date)

        old_positions = self.repository.list_positions(
            staff_id,
            employment_id=employment_id,
            for_update=True,
        )
        old_roles = self.repository.list_operational_roles(
            staff_id,
            employment_id=employment_id,
            for_update=True,
        )
        position_directives = payload.position_replacements or []
        role_directives = payload.operational_role_replacements or []
        position_ids = [directive.old_period_id for directive in position_directives]
        role_ids = [directive.old_period_id for directive in role_directives]
        if len(position_ids) != len(set(position_ids)) or set(position_ids) != {
            period.id for period in old_positions
        }:
            raise _domain_error("ROW_VERSION_CONFLICT", 409)
        if len(role_ids) != len(set(role_ids)) or set(role_ids) != {
            period.id for period in old_roles
        }:
            raise _domain_error("ROW_VERSION_CONFLICT", 409)

        old_positions_by_id = {period.id: period for period in old_positions}
        old_roles_by_id = {period.id: period for period in old_roles}
        for position_directive in position_directives:
            self._require_version(
                old_positions_by_id[position_directive.old_period_id].row_version,
                position_directive.expected_row_version,
            )
            if position_directive.replacement is not None:
                self._validate_period(
                    position_directive.replacement.start_date,
                    position_directive.replacement.end_date,
                )
                if position_directive.replacement.start_date < payload.start_date or (
                    payload.end_date is not None
                    and (
                        position_directive.replacement.end_date is None
                        or position_directive.replacement.end_date > payload.end_date
                    )
                ):
                    raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)
        for role_directive in role_directives:
            self._require_version(
                old_roles_by_id[role_directive.old_period_id].row_version,
                role_directive.expected_row_version,
            )
            if role_directive.replacement is not None:
                self._validate_period(
                    role_directive.replacement.start_date,
                    role_directive.replacement.end_date,
                )
                if role_directive.replacement.start_date < payload.start_date or (
                    payload.end_date is not None
                    and (
                        role_directive.replacement.end_date is None
                        or role_directive.replacement.end_date > payload.end_date
                    )
                ):
                    raise _domain_error("STAFF_PERIOD_OUTSIDE_EMPLOYMENT", 409)

        now = _now()
        old.invalidated_at_utc = now
        old.updated_by_account_id = current_account.id
        old.updated_at_utc = now
        old.row_version += 1
        for position_period in old_positions:
            position_period.invalidated_at_utc = now
            position_period.updated_by_account_id = current_account.id
            position_period.updated_at_utc = now
            position_period.row_version += 1
        for role_period in old_roles:
            role_period.invalidated_at_utc = now
            role_period.updated_by_account_id = current_account.id
            role_period.updated_at_utc = now
            role_period.row_version += 1

        replacement = self._new_employment(
            staff=staff,
            start_date=payload.start_date,
            current_account=current_account,
        )
        replacement.end_date = payload.end_date
        replacement.end_reason_code = payload.end_reason_code
        self._flush()
        old.replacement_employment_id = replacement.id

        position_links: list[tuple[StaffPositionPeriod, StaffPositionPeriod | None]] = []
        for position_directive in position_directives:
            old_position = old_positions_by_id[position_directive.old_period_id]
            if position_directive.replacement is None:
                position_links.append((old_position, None))
                continue
            new_position = self._new_position(
                staff_id,
                replacement.id,
                position_directive.replacement,
                current_account.id,
            )
            self.repository.add(new_position)
            position_links.append((old_position, new_position))

        role_links: list[tuple[StaffOperationalRolePeriod, StaffOperationalRolePeriod | None]] = []
        for role_directive in role_directives:
            old_role = old_roles_by_id[role_directive.old_period_id]
            if role_directive.replacement is None:
                role_links.append((old_role, None))
                continue
            new_role = self._new_role(
                staff_id,
                replacement.id,
                role_directive.replacement,
                current_account.id,
            )
            self.repository.add(new_role)
            role_links.append((old_role, new_role))

        self._flush()
        for old_position, linked_position in position_links:
            old_position.replacement_id = (
                linked_position.id if linked_position is not None else None
            )
        for old_role, linked_role in role_links:
            old_role.replacement_id = linked_role.id if linked_role is not None else None

        self._audit(
            account_id=current_account.id,
            action_code="STAFF_EMPLOYMENT_REPLACE",
            entity_type="STAFF_EMPLOYMENT",
            entity_pk=old.id,
            before={"row_version": payload.expected_employment_row_version},
            after={
                "replacement_employment_id": replacement.id,
                "old_row_version": old.row_version,
                "replacement_row_version": replacement.row_version,
                "position_replacements": [
                    {
                        "old_period_id": old_position.id,
                        "replacement_id": (new_position.id if new_position is not None else None),
                    }
                    for old_position, new_position in position_links
                ],
                "operational_role_replacements": [
                    {
                        "old_period_id": old_role.id,
                        "replacement_id": new_role.id if new_role is not None else None,
                    }
                    for old_role, new_role in role_links
                ],
                "actor_account_id": current_account.id,
                "updated_at_utc": now.isoformat(),
            },
        )
        self._commit()
        return self._employment_response(
            replacement,
            as_of=_now().astimezone(_BUSINESS_TIMEZONE).date(),
        )

    def create_position(
        self,
        staff_id: int,
        employment_id: int,
        payload: StaffPositionCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffPositionPeriodResponse:
        employment = self._require_employment(staff_id, employment_id, for_update=True)
        self._require_version(
            employment.row_version,
            payload.expected_employment_row_version,
        )
        self._validate_child_period(employment, payload.start_date, payload.end_date)
        period = self._new_position(
            staff_id,
            employment_id,
            InitialPositionRequest(
                position_code=payload.position_code,
                start_date=payload.start_date,
                end_date=payload.end_date,
            ),
            current_account.id,
        )
        self.repository.add(period)
        employment.updated_by_account_id = current_account.id
        employment.updated_at_utc = _now()
        employment.row_version += 1
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_POSITION_CREATE",
            entity_type="STAFF_POSITION_PERIOD",
            entity_pk=period.id,
            before=None,
            after={"position_code": period.position_code},
        )
        self._commit()
        return self._position_response(period)

    def create_operational_role(
        self,
        staff_id: int,
        employment_id: int,
        payload: StaffOperationalRoleCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffOperationalRolePeriodResponse:
        employment = self._require_employment(staff_id, employment_id, for_update=True)
        self._require_version(
            employment.row_version,
            payload.expected_employment_row_version,
        )
        self._validate_child_period(employment, payload.start_date, payload.end_date)
        role_payload = InitialOperationalRoleRequest(
            role_code=payload.role_code,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        period = self._new_role(
            staff_id,
            employment_id,
            role_payload,
            current_account.id,
        )
        self.repository.add(period)
        employment.updated_by_account_id = current_account.id
        employment.updated_at_utc = _now()
        employment.row_version += 1
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_OPERATIONAL_ROLE_CREATE",
            entity_type="STAFF_OPERATIONAL_ROLE_PERIOD",
            entity_pk=period.id,
            before=None,
            after={"role_code": period.role_code},
        )
        self._commit()
        return self._role_response(period)

    def _close_or_replace_period(
        self,
        *,
        getter: Callable[..., PeriodT | None],
        response_factory: Callable[[PeriodT], ResponseT],
        staff_id: int,
        employment_id: int,
        period_id: int,
        expected_version: int,
        current_account: CurrentAccount,
        end_date: date | None = None,
        replacement_factory: Callable[[PeriodT], PeriodT] | None = None,
        action_code: str,
        entity_type: str,
    ) -> ResponseT:
        period = getter(
            staff_id,
            employment_id,
            period_id,
            for_update=True,
        )
        if period is None:
            raise _domain_error("PERIOD_NOT_FOUND", 404)
        self._require_version(period.row_version, expected_version)
        now = _now()
        before = {
            "start_date": period.start_date.isoformat(),
            "end_date": (period.end_date.isoformat() if period.end_date is not None else None),
            "row_version": period.row_version,
        }
        result = period
        if replacement_factory is None:
            if period.end_date is not None or end_date is None:
                raise _domain_error("VALIDATION_ERROR", 422, field="end_date")
            if end_date < period.start_date:
                raise _domain_error("VALIDATION_ERROR", 422, field="end_date")
            period.end_date = end_date
        else:
            period.invalidated_at_utc = now
            result = replacement_factory(period)
            self.repository.add(result)
            self._flush()
            period.replacement_id = result.id
        period.updated_by_account_id = current_account.id
        period.updated_at_utc = now
        period.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code=action_code,
            entity_type=entity_type,
            entity_pk=period.id,
            before=before,
            after={
                "replacement_id": (result.id if replacement_factory is not None else None),
                "end_date": (result.end_date.isoformat() if result.end_date is not None else None),
            },
        )
        self._commit()
        return response_factory(result)

    def close_position(
        self,
        staff_id: int,
        employment_id: int,
        period_id: int,
        payload: StaffPeriodCloseRequest,
        current_account: CurrentAccount,
    ) -> StaffPositionPeriodResponse:
        return self._close_or_replace_period(
            getter=self.repository.get_position,
            response_factory=self._position_response,
            staff_id=staff_id,
            employment_id=employment_id,
            period_id=period_id,
            expected_version=payload.expected_period_row_version,
            current_account=current_account,
            end_date=payload.end_date,
            action_code="STAFF_POSITION_CLOSE",
            entity_type="STAFF_POSITION_PERIOD",
        )

    def replace_position(
        self,
        staff_id: int,
        employment_id: int,
        period_id: int,
        payload: StaffPositionReplacementRequest,
        current_account: CurrentAccount,
    ) -> StaffPositionPeriodResponse:
        employment = self._require_employment(staff_id, employment_id, for_update=True)
        self._validate_child_period(employment, payload.start_date, payload.end_date)

        def replacement(_: StaffPositionPeriod) -> StaffPositionPeriod:
            return StaffPositionPeriod(
                staff_id=staff_id,
                employment_id=employment_id,
                position_code=payload.position_code.value,
                start_date=payload.start_date,
                end_date=payload.end_date,
                created_by_account_id=current_account.id,
                updated_by_account_id=current_account.id,
            )

        return self._close_or_replace_period(
            getter=self.repository.get_position,
            response_factory=self._position_response,
            staff_id=staff_id,
            employment_id=employment_id,
            period_id=period_id,
            expected_version=payload.expected_period_row_version,
            current_account=current_account,
            replacement_factory=replacement,
            action_code="STAFF_POSITION_REPLACE",
            entity_type="STAFF_POSITION_PERIOD",
        )

    def close_operational_role(
        self,
        staff_id: int,
        employment_id: int,
        period_id: int,
        payload: StaffPeriodCloseRequest,
        current_account: CurrentAccount,
    ) -> StaffOperationalRolePeriodResponse:
        return self._close_or_replace_period(
            getter=self.repository.get_operational_role,
            response_factory=self._role_response,
            staff_id=staff_id,
            employment_id=employment_id,
            period_id=period_id,
            expected_version=payload.expected_period_row_version,
            current_account=current_account,
            end_date=payload.end_date,
            action_code="STAFF_OPERATIONAL_ROLE_CLOSE",
            entity_type="STAFF_OPERATIONAL_ROLE_PERIOD",
        )

    def replace_operational_role(
        self,
        staff_id: int,
        employment_id: int,
        period_id: int,
        payload: StaffOperationalRoleReplacementRequest,
        current_account: CurrentAccount,
    ) -> StaffOperationalRolePeriodResponse:
        employment = self._require_employment(staff_id, employment_id, for_update=True)
        self._validate_child_period(employment, payload.start_date, payload.end_date)
        role_code = normalize_role_code(payload.role_code)

        def replacement(_: StaffOperationalRolePeriod) -> StaffOperationalRolePeriod:
            return StaffOperationalRolePeriod(
                staff_id=staff_id,
                employment_id=employment_id,
                role_code=role_code,
                start_date=payload.start_date,
                end_date=payload.end_date,
                created_by_account_id=current_account.id,
                updated_by_account_id=current_account.id,
            )

        return self._close_or_replace_period(
            getter=self.repository.get_operational_role,
            response_factory=self._role_response,
            staff_id=staff_id,
            employment_id=employment_id,
            period_id=period_id,
            expected_version=payload.expected_period_row_version,
            current_account=current_account,
            replacement_factory=replacement,
            action_code="STAFF_OPERATIONAL_ROLE_REPLACE",
            entity_type="STAFF_OPERATIONAL_ROLE_PERIOD",
        )

    @staticmethod
    def _license_response(
        license_fact: StaffLicense,
        license_type: LicenseType,
    ) -> StaffLicenseResponse:
        return StaffLicenseResponse(
            id=license_fact.id,
            staff_id=license_fact.staff_id,
            license_type_code=license_type.code,
            license_type_display_name=license_type.display_name,
            license_number=license_fact.license_number,
            issued_date=license_fact.issued_date,
            invalidated_at_utc=license_fact.invalidated_at_utc,
            replacement_license_id=license_fact.replacement_license_id,
            row_version=license_fact.row_version,
        )

    def _qualification_response(
        self,
        qualification: StaffServiceQualificationPeriod,
    ) -> StaffServiceQualificationResponse:
        service_type = self.repository.get_service_type_by_id(qualification.service_type_id)
        if service_type is None:
            raise _domain_error("SERVICE_TYPE_NOT_FOUND", 404)
        service_group = self.repository.get_service_group_by_id(service_type.service_group_id)
        if service_group is None:
            raise _domain_error("SERVICE_TYPE_NOT_FOUND", 404)
        return StaffServiceQualificationResponse(
            id=qualification.id,
            staff_id=qualification.staff_id,
            employment_id=qualification.employment_id,
            service_type_code=service_type.code,
            service_type_display_name=service_type.display_name,
            service_group_code=service_group.code,
            start_date=qualification.start_date,
            end_date=qualification.end_date,
            source_license_id=qualification.source_license_id,
            invalidated_at_utc=qualification.invalidated_at_utc,
            replacement_qualification_id=qualification.replacement_qualification_id,
            row_version=qualification.row_version,
        )

    def list_service_catalog(self) -> ServiceCatalogResponse:
        return ServiceCatalogResponse(
            items=[
                ServiceTypeResponse(
                    id=service_type.id,
                    code=service_type.code,
                    display_name=service_type.display_name,
                    service_group_code=service_group.code,
                    service_group_display_name=service_group.display_name,
                    active=service_type.active,
                )
                for service_group, service_type in self.repository.list_service_catalog()
            ]
        )

    def list_license_types(self) -> LicenseTypeListResponse:
        return LicenseTypeListResponse(
            items=[
                LicenseTypeResponse(
                    id=license_type.id,
                    code=license_type.code,
                    display_name=license_type.display_name,
                    active=license_type.active,
                )
                for license_type in self.repository.list_license_types()
            ]
        )

    @staticmethod
    def _training_course_response(course: Any) -> TrainingCourseResponse:
        return TrainingCourseResponse(
            code=course.code,
            display_name=course.display_name,
            cycle_type=course.cycle_type,
            sort_order=course.sort_order,
            active=course.active,
        )

    @staticmethod
    def _onboarding_training_response(
        training: StaffOnboardingTraining,
    ) -> StaffOnboardingTrainingResponse:
        return StaffOnboardingTrainingResponse(
            id=training.id,
            staff_id=training.staff_id,
            employment_id=training.employment_id,
            course_code=training.course_code,
            completed=training.completed,
            invalidated_at_utc=training.invalidated_at_utc,
            replacement_onboarding_training_id=training.replacement_onboarding_training_id,
            created_by_account_id=training.created_by_account_id,
            created_at_utc=training.created_at_utc,
            updated_by_account_id=training.updated_by_account_id,
            updated_at_utc=training.updated_at_utc,
            row_version=training.row_version,
        )

    @staticmethod
    def _periodic_training_response(
        training: StaffPeriodicTrainingStatus,
    ) -> StaffPeriodicTrainingResponse:
        return StaffPeriodicTrainingResponse(
            id=training.id,
            staff_id=training.staff_id,
            course_code=training.course_code,
            period_key=training.period_key,
            completed=training.completed,
            invalidated_at_utc=training.invalidated_at_utc,
            replacement_periodic_training_id=training.replacement_periodic_training_id,
            created_by_account_id=training.created_by_account_id,
            created_at_utc=training.created_at_utc,
            updated_by_account_id=training.updated_by_account_id,
            updated_at_utc=training.updated_at_utc,
            row_version=training.row_version,
        )

    def list_training_courses(self) -> TrainingCourseListResponse:
        return TrainingCourseListResponse(
            items=[
                self._training_course_response(course)
                for course in self.repository.list_training_courses()
            ]
        )

    def _require_training_course(self, code: str) -> Any:
        normalized = code.strip().upper()
        course = self.repository.get_training_course(normalized)
        if course is None:
            raise _domain_error(
                "STAFF_TRAINING_COURSE_NOT_FOUND",
                422,
                field="course_code",
            )
        return course

    @staticmethod
    def _validate_periodic_course_and_period(course: Any, period_key: str) -> str:
        normalized_period = period_key.strip().upper()
        if course.cycle_type == "ON_HIRE":
            raise _domain_error("STAFF_TRAINING_INVALID_CYCLE", 409, field="course_code")
        if course.cycle_type == "HALF_YEAR":
            if re.fullmatch(r"\d{4}-H[12]", normalized_period) is None:
                raise _domain_error(
                    "STAFF_TRAINING_PERIOD_INVALID",
                    422,
                    field="period_key",
                )
        elif course.cycle_type in {"ANNUAL", "BIENNIAL"}:
            if re.fullmatch(r"\d{4}", normalized_period) is None:
                raise _domain_error(
                    "STAFF_TRAINING_PERIOD_INVALID",
                    422,
                    field="period_key",
                )
        else:
            raise _domain_error("STAFF_TRAINING_INVALID_CYCLE", 409, field="course_code")
        return normalized_period

    def _require_onboarding_training(
        self,
        staff_id: int,
        training_id: int,
        *,
        for_update: bool = False,
    ) -> StaffOnboardingTraining:
        training = self.repository.get_onboarding_training(
            staff_id,
            training_id,
            for_update=for_update,
        )
        if training is not None:
            return training
        other_staff_training = self.repository.get_onboarding_training_by_id(training_id)
        if other_staff_training is not None and other_staff_training.staff_id != staff_id:
            raise _domain_error("STAFF_TRAINING_STAFF_MISMATCH", 409)
        raise _domain_error("STAFF_ONBOARDING_TRAINING_NOT_FOUND", 404)

    def _require_periodic_training(
        self,
        staff_id: int,
        training_id: int,
        *,
        for_update: bool = False,
    ) -> StaffPeriodicTrainingStatus:
        training = self.repository.get_periodic_training(
            staff_id,
            training_id,
            for_update=for_update,
        )
        if training is not None:
            return training
        other_staff_training = self.repository.get_periodic_training_by_id(training_id)
        if other_staff_training is not None and other_staff_training.staff_id != staff_id:
            raise _domain_error("STAFF_TRAINING_STAFF_MISMATCH", 409)
        raise _domain_error("STAFF_PERIODIC_TRAINING_NOT_FOUND", 404)

    def list_onboarding_trainings(self, staff_id: int) -> StaffOnboardingTrainingListResponse:
        self._require_staff(staff_id)
        return StaffOnboardingTrainingListResponse(
            items=[
                self._onboarding_training_response(training)
                for training in self.repository.list_onboarding_trainings(staff_id)
            ]
        )

    def update_onboarding_training(
        self,
        staff_id: int,
        training_id: int,
        payload: StaffOnboardingTrainingUpdateRequest,
        current_account: CurrentAccount,
    ) -> StaffOnboardingTrainingResponse:
        self._require_staff(staff_id)
        training = self._require_onboarding_training(
            staff_id,
            training_id,
            for_update=True,
        )
        self._require_version(training.row_version, payload.expected_row_version)
        now = _now()
        before = {
            "completed": training.completed,
            "row_version": training.row_version,
        }
        training.completed = payload.completed
        training.updated_by_account_id = current_account.id
        training.updated_at_utc = now
        training.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_ONBOARDING_TRAINING_UPDATE",
            entity_type="STAFF_ONBOARDING_TRAINING",
            entity_pk=training.id,
            before=before,
            after={
                "completed": training.completed,
                "row_version": training.row_version,
            },
        )
        self._commit()
        return self._onboarding_training_response(training)

    def list_periodic_trainings(self, staff_id: int) -> StaffPeriodicTrainingListResponse:
        self._require_staff(staff_id)
        return StaffPeriodicTrainingListResponse(
            items=[
                self._periodic_training_response(training)
                for training in self.repository.list_periodic_trainings(staff_id)
            ]
        )

    def create_periodic_training(
        self,
        staff_id: int,
        payload: StaffPeriodicTrainingCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffPeriodicTrainingResponse:
        self._require_staff(staff_id)
        course = self._require_training_course(payload.course_code)
        period_key = self._validate_periodic_course_and_period(course, payload.period_key)
        now = _now()
        training = StaffPeriodicTrainingStatus(
            staff_id=staff_id,
            course_code=course.code,
            period_key=period_key,
            completed=payload.completed,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(training)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_PERIODIC_TRAINING_CREATE",
            entity_type="STAFF_PERIODIC_TRAINING_STATUS",
            entity_pk=training.id,
            before=None,
            after={
                "course_code": training.course_code,
                "period_key": training.period_key,
                "completed": training.completed,
                "row_version": training.row_version,
            },
        )
        self._commit()
        return self._periodic_training_response(training)

    def update_periodic_training(
        self,
        staff_id: int,
        training_id: int,
        payload: StaffPeriodicTrainingUpdateRequest,
        current_account: CurrentAccount,
    ) -> StaffPeriodicTrainingResponse:
        self._require_staff(staff_id)
        training = self._require_periodic_training(
            staff_id,
            training_id,
            for_update=True,
        )
        self._require_version(training.row_version, payload.expected_row_version)
        now = _now()
        before = {
            "completed": training.completed,
            "row_version": training.row_version,
        }
        training.completed = payload.completed
        training.updated_by_account_id = current_account.id
        training.updated_at_utc = now
        training.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_PERIODIC_TRAINING_UPDATE",
            entity_type="STAFF_PERIODIC_TRAINING_STATUS",
            entity_pk=training.id,
            before=before,
            after={
                "completed": training.completed,
                "row_version": training.row_version,
            },
        )
        self._commit()
        return self._periodic_training_response(training)

    def invalidate_periodic_training(
        self,
        staff_id: int,
        training_id: int,
        payload: StaffPeriodicTrainingInvalidateRequest,
        current_account: CurrentAccount,
    ) -> StaffPeriodicTrainingResponse:
        self._require_staff(staff_id)
        training = self._require_periodic_training(
            staff_id,
            training_id,
            for_update=True,
        )
        self._require_version(training.row_version, payload.expected_row_version)
        now = _now()
        before = {
            "invalidated_at_utc": None,
            "row_version": training.row_version,
        }
        training.invalidated_at_utc = now
        training.updated_by_account_id = current_account.id
        training.updated_at_utc = now
        training.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_PERIODIC_TRAINING_INVALIDATE",
            entity_type="STAFF_PERIODIC_TRAINING_STATUS",
            entity_pk=training.id,
            before=before,
            after={
                "invalidated_at_utc": now.isoformat(),
                "row_version": training.row_version,
            },
        )
        self._commit()
        return self._periodic_training_response(training)

    @staticmethod
    def _clean_license_number(value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise _domain_error("VALIDATION_ERROR", 422, field="license_number")
        return cleaned

    def _require_license_type(self, code: str) -> LicenseType:
        license_type = self.repository.get_license_type(code.strip().upper())
        if license_type is None:
            raise _domain_error("LICENSE_TYPE_NOT_FOUND", 404, field="license_type_code")
        return license_type

    def _require_service_type(self, code: str) -> ServiceType:
        service_type = self.repository.get_service_type(code.strip().upper())
        if service_type is None:
            raise _domain_error("SERVICE_TYPE_NOT_FOUND", 404, field="service_type_code")
        return service_type

    def list_licenses(self, staff_id: int) -> StaffLicenseListResponse:
        self._require_staff(staff_id)
        return StaffLicenseListResponse(
            items=[
                self._license_response(license_fact, license_type)
                for license_fact, license_type in self.repository.list_licenses(staff_id)
            ]
        )

    def create_license(
        self,
        staff_id: int,
        payload: StaffLicenseCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffLicenseResponse:
        staff = self._require_staff(staff_id, for_update=True)
        self._require_version(staff.row_version, payload.expected_row_version)
        license_type = self._require_license_type(payload.license_type_code)
        license_number = self._clean_license_number(payload.license_number)
        now = _now()
        license_fact = StaffLicense(
            staff_id=staff_id,
            license_type_id=license_type.id,
            license_number=license_number,
            issued_date=payload.issued_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(license_fact)
        staff.updated_at_utc = now
        staff.row_version += 1
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_LICENSE_CREATE",
            entity_type="STAFF_LICENSE",
            entity_pk=license_fact.id,
            before=None,
            after={
                "license_type_code": license_type.code,
                "issued_date": payload.issued_date.isoformat(),
                "actor_account_id": current_account.id,
                "updated_at_utc": now.isoformat(),
            },
        )
        self._commit()
        return self._license_response(license_fact, license_type)

    def replace_license(
        self,
        staff_id: int,
        license_id: int,
        payload: StaffLicenseReplacementRequest,
        current_account: CurrentAccount,
    ) -> StaffLicenseResponse:
        old = self.repository.get_license(
            staff_id,
            license_id,
            for_update=True,
            active_only=True,
        )
        if old is None:
            raise _domain_error("STAFF_LICENSE_NOT_FOUND", 404)
        self._require_version(old.row_version, payload.expected_row_version)
        license_type = self._require_license_type(payload.license_type_code)
        license_number = self._clean_license_number(payload.license_number)
        now = _now()
        before = {
            "license_type_id": old.license_type_id,
            "license_number": old.license_number,
            "issued_date": old.issued_date.isoformat(),
            "row_version": old.row_version,
        }
        old.invalidated_at_utc = now
        old.updated_by_account_id = current_account.id
        old.updated_at_utc = now
        old.row_version += 1
        self._flush()
        replacement = StaffLicense(
            staff_id=staff_id,
            license_type_id=license_type.id,
            license_number=license_number,
            issued_date=payload.issued_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(replacement)
        self._flush()
        old.replacement_license_id = replacement.id
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_LICENSE_REPLACE",
            entity_type="STAFF_LICENSE",
            entity_pk=old.id,
            before=before,
            after={
                "replacement_license_id": replacement.id,
                "row_version": old.row_version,
                "actor_account_id": current_account.id,
                "updated_at_utc": now.isoformat(),
            },
        )
        self._commit()
        return self._license_response(replacement, license_type)

    def invalidate_license(
        self,
        staff_id: int,
        license_id: int,
        payload: StaffLicenseInvalidateRequest,
        current_account: CurrentAccount,
    ) -> StaffLicenseResponse:
        license_fact = self.repository.get_license(
            staff_id,
            license_id,
            for_update=True,
            active_only=True,
        )
        if license_fact is None:
            raise _domain_error("STAFF_LICENSE_NOT_FOUND", 404)
        self._require_version(license_fact.row_version, payload.expected_row_version)
        license_type = self.database_session.get(LicenseType, license_fact.license_type_id)
        if license_type is None:
            raise _domain_error("LICENSE_TYPE_NOT_FOUND", 404)
        now = _now()
        before = {
            "invalidated_at_utc": None,
            "row_version": license_fact.row_version,
        }
        license_fact.invalidated_at_utc = now
        license_fact.updated_by_account_id = current_account.id
        license_fact.updated_at_utc = now
        license_fact.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_LICENSE_INVALIDATE",
            entity_type="STAFF_LICENSE",
            entity_pk=license_fact.id,
            before=before,
            after={
                "invalidated_at_utc": now.isoformat(),
                "row_version": license_fact.row_version,
                "actor_account_id": current_account.id,
            },
        )
        self._commit()
        return self._license_response(license_fact, license_type)

    def list_service_qualifications(
        self,
        staff_id: int,
    ) -> StaffServiceQualificationListResponse:
        self._require_staff(staff_id)
        return StaffServiceQualificationListResponse(
            items=[
                self._qualification_response(qualification)
                for qualification, _service_type, _service_group in (
                    self.repository.list_qualifications(staff_id)
                )
            ]
        )

    def _require_source_license(
        self,
        staff_id: int,
        source_license_id: int | None,
    ) -> None:
        if source_license_id is None:
            return
        if self.repository.get_active_license(staff_id, source_license_id) is None:
            raise _domain_error(
                "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH",
                422,
                field="source_license_id",
            )

    def create_service_qualification(
        self,
        staff_id: int,
        payload: StaffServiceQualificationCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffServiceQualificationResponse:
        employment = self._require_employment(
            staff_id,
            payload.employment_id,
            for_update=True,
        )
        self._require_version(employment.row_version, payload.expected_row_version)
        self._validate_child_period(employment, payload.start_date, payload.end_date)
        service_type = self._require_service_type(payload.service_type_code)
        self._require_source_license(staff_id, payload.source_license_id)
        now = _now()
        qualification = StaffServiceQualificationPeriod(
            staff_id=staff_id,
            employment_id=employment.id,
            service_type_id=service_type.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            source_license_id=payload.source_license_id,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(qualification)
        employment.updated_by_account_id = current_account.id
        employment.updated_at_utc = now
        employment.row_version += 1
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_SERVICE_QUALIFICATION_CREATE",
            entity_type="STAFF_SERVICE_QUALIFICATION_PERIOD",
            entity_pk=qualification.id,
            before=None,
            after={
                "employment_id": employment.id,
                "service_type_code": service_type.code,
                "start_date": payload.start_date.isoformat(),
                "end_date": payload.end_date.isoformat() if payload.end_date else None,
                "source_license_id": payload.source_license_id,
                "actor_account_id": current_account.id,
                "updated_at_utc": now.isoformat(),
            },
        )
        self._commit()
        return self._qualification_response(qualification)

    def close_service_qualification(
        self,
        staff_id: int,
        qualification_id: int,
        payload: StaffServiceQualificationCloseRequest,
        current_account: CurrentAccount,
    ) -> StaffServiceQualificationResponse:
        qualification = self.repository.get_qualification(
            staff_id,
            qualification_id,
            for_update=True,
            active_only=True,
        )
        if qualification is None:
            raise _domain_error("STAFF_SERVICE_QUALIFICATION_NOT_FOUND", 404)
        self._require_version(qualification.row_version, payload.expected_row_version)
        employment = self._require_employment(
            staff_id, qualification.employment_id, for_update=True
        )
        if qualification.end_date is not None:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date")
        self._validate_child_period(employment, qualification.start_date, payload.end_date)
        now = _now()
        before = {
            "end_date": None,
            "row_version": qualification.row_version,
        }
        qualification.end_date = payload.end_date
        qualification.updated_by_account_id = current_account.id
        qualification.updated_at_utc = now
        qualification.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_SERVICE_QUALIFICATION_CLOSE",
            entity_type="STAFF_SERVICE_QUALIFICATION_PERIOD",
            entity_pk=qualification.id,
            before=before,
            after={
                "end_date": payload.end_date.isoformat(),
                "row_version": qualification.row_version,
                "actor_account_id": current_account.id,
            },
        )
        self._commit()
        return self._qualification_response(qualification)

    def replace_service_qualification(
        self,
        staff_id: int,
        qualification_id: int,
        payload: StaffServiceQualificationReplacementRequest,
        current_account: CurrentAccount,
    ) -> StaffServiceQualificationResponse:
        old = self.repository.get_qualification(
            staff_id,
            qualification_id,
            for_update=True,
            active_only=True,
        )
        if old is None:
            raise _domain_error("STAFF_SERVICE_QUALIFICATION_NOT_FOUND", 404)
        self._require_version(old.row_version, payload.expected_row_version)
        employment = self._require_employment(staff_id, payload.employment_id, for_update=True)
        self._validate_child_period(employment, payload.start_date, payload.end_date)
        service_type = self._require_service_type(payload.service_type_code)
        self._require_source_license(staff_id, payload.source_license_id)
        now = _now()
        before = {
            "employment_id": old.employment_id,
            "service_type_id": old.service_type_id,
            "start_date": old.start_date.isoformat(),
            "end_date": old.end_date.isoformat() if old.end_date else None,
            "row_version": old.row_version,
        }
        old.invalidated_at_utc = now
        old.updated_by_account_id = current_account.id
        old.updated_at_utc = now
        old.row_version += 1
        self._flush()
        replacement = StaffServiceQualificationPeriod(
            staff_id=staff_id,
            employment_id=employment.id,
            service_type_id=service_type.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            source_license_id=payload.source_license_id,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(replacement)
        self._flush()
        old.replacement_qualification_id = replacement.id
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_SERVICE_QUALIFICATION_REPLACE",
            entity_type="STAFF_SERVICE_QUALIFICATION_PERIOD",
            entity_pk=old.id,
            before=before,
            after={
                "replacement_qualification_id": replacement.id,
                "row_version": old.row_version,
                "actor_account_id": current_account.id,
                "updated_at_utc": now.isoformat(),
            },
        )
        self._commit()
        return self._qualification_response(replacement)

    def invalidate_service_qualification(
        self,
        staff_id: int,
        qualification_id: int,
        payload: StaffServiceQualificationInvalidateRequest,
        current_account: CurrentAccount,
    ) -> StaffServiceQualificationResponse:
        qualification = self.repository.get_qualification(
            staff_id,
            qualification_id,
            for_update=True,
            active_only=True,
        )
        if qualification is None:
            raise _domain_error("STAFF_SERVICE_QUALIFICATION_NOT_FOUND", 404)
        self._require_version(qualification.row_version, payload.expected_row_version)
        now = _now()
        before = {
            "invalidated_at_utc": None,
            "row_version": qualification.row_version,
        }
        qualification.invalidated_at_utc = now
        qualification.updated_by_account_id = current_account.id
        qualification.updated_at_utc = now
        qualification.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_SERVICE_QUALIFICATION_INVALIDATE",
            entity_type="STAFF_SERVICE_QUALIFICATION_PERIOD",
            entity_pk=qualification.id,
            before=before,
            after={
                "invalidated_at_utc": now.isoformat(),
                "row_version": qualification.row_version,
                "actor_account_id": current_account.id,
            },
        )
        self._commit()
        return self._qualification_response(qualification)

    def reveal_sensitive_identity(
        self,
        staff_id: int,
        current_pin: str,
        current_account: CurrentAccount,
    ) -> SensitiveIdentityRevealResponse:
        self._require_staff(staff_id)
        account = self.database_session.scalar(
            select(UserAccount)
            .where(
                UserAccount.id == current_account.id,
                UserAccount.active.is_(True),
                UserAccount.login_allowed.is_(True),
            )
            .with_for_update()
        )
        if account is None:
            raise _domain_error("CURRENT_PIN_INVALID", 422, field="current_pin")
        now = _now()
        if account.locked_until_utc is not None and account.locked_until_utc > now:
            raise _domain_error("ACCOUNT_LOCKED", 423)

        protector = PinProtector(
            self.settings.secret_value("pin_pepper"),
            self.settings.secret_value("pin_lookup_key"),
        )
        try:
            pin_valid = protector.verify_pin(account.pin_hash, current_pin)
        except ValueError:
            pin_valid = False
        if not pin_valid:
            account.failed_count += 1
            if account.failed_count >= 5:
                account.locked_until_utc = now + timedelta(minutes=15)
            self.repository.add(
                AuthEvent(
                    account_id=account.id,
                    event_type="SENSITIVE_IDENTITY_STEP_UP",
                    success=False,
                    occurred_at_utc=now,
                    reason_code="INVALID_CURRENT_PIN",
                )
            )
            self._commit()
            raise _domain_error("CURRENT_PIN_INVALID", 422, field="current_pin")

        sensitive_identity = self.repository.get_sensitive_identity(
            staff_id,
            for_update=True,
        )
        if sensitive_identity is None:
            raise _domain_error("SENSITIVE_IDENTITY_NOT_FOUND", 404)
        try:
            resident_number = decrypt_resident_number(
                staff_id=staff_id,
                ciphertext=sensitive_identity.resident_number_ciphertext,
                nonce=sensitive_identity.resident_number_nonce,
                key_version=sensitive_identity.resident_number_key_version,
                settings=self.settings,
            )
        except ValueError:
            self.database_session.rollback()
            raise _domain_error("SENSITIVE_IDENTITY_DECRYPTION_FAILED", 500) from None

        self.repository.add(
            AccessEvent(
                occurred_at_utc=now,
                account_id=current_account.id,
                access_type="STAFF_RESIDENT_NUMBER_REVEAL",
                entity_type="STAFF",
                entity_pk=staff_id,
            )
        )
        self._commit()
        return SensitiveIdentityRevealResponse(
            resident_number=f"{resident_number[:6]}-{resident_number[6:]}"
        )

    @staticmethod
    def _map_health_integrity_error(error: IntegrityError) -> StaffDomainError | None:
        original = error.orig
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if constraint_name == "fk_staff_health_check_staff_id_staff":
            return _domain_error("STAFF_HEALTH_CHECK_STAFF_MISMATCH", 409)
        return None

    @staticmethod
    def _map_quarterly_integrity_error(error: IntegrityError) -> StaffDomainError | None:
        original = error.orig
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if constraint_name == "uq_staff_quarterly_consultation_staff_year_quarter":
            return _domain_error("STAFF_QUARTERLY_CONSULTATION_DUPLICATE", 409)
        if constraint_name in {
            "ck_staff_quarterly_consultation_quarter_no",
            "ck_staff_quarterly_consultation_row_version_positive",
        }:
            return _domain_error("STAFF_QUARTERLY_CONSULTATION_INVALID", 422)
        if constraint_name == "fk_staff_quarterly_consultation_staff_id_staff":
            return _domain_error("STAFF_QUARTERLY_CONSULTATION_STAFF_MISMATCH", 409)
        return None

    @staticmethod
    def _health_check_response(
        health_check: StaffHealthCheck,
    ) -> StaffHealthCheckResponse:
        return StaffHealthCheckResponse(
            id=health_check.id,
            staff_id=health_check.staff_id,
            check_date=health_check.check_date,
            invalidated_at_utc=health_check.invalidated_at_utc,
            replacement_health_check_id=health_check.replacement_health_check_id,
            created_by_account_id=health_check.created_by_account_id,
            created_at_utc=health_check.created_at_utc,
            updated_by_account_id=health_check.updated_by_account_id,
            updated_at_utc=health_check.updated_at_utc,
            row_version=health_check.row_version,
        )

    def _require_health_check(
        self,
        staff_id: int,
        health_check_id: int,
        *,
        for_update: bool = False,
    ) -> StaffHealthCheck:
        health_check = self.repository.get_health_check(
            staff_id,
            health_check_id,
            for_update=for_update,
        )
        if health_check is not None:
            return health_check
        inactive_health_check = self.repository.get_health_check(
            staff_id,
            health_check_id,
            for_update=for_update,
            active_only=False,
        )
        if inactive_health_check is not None:
            return inactive_health_check
        other_staff_health_check = self.repository.get_health_check_by_id(
            health_check_id,
            active_only=False,
        )
        if other_staff_health_check is not None and other_staff_health_check.staff_id != staff_id:
            raise _domain_error("STAFF_HEALTH_CHECK_STAFF_MISMATCH", 409)
        raise _domain_error("STAFF_HEALTH_CHECK_NOT_FOUND", 404)

    @staticmethod
    def _health_check_snapshot(health_check: StaffHealthCheck) -> dict[str, Any]:
        return {
            "staff_id": health_check.staff_id,
            "employment_id": health_check.employment_id,
            "check_date": health_check.check_date.isoformat(),
            "invalidated_at_utc": (
                health_check.invalidated_at_utc.isoformat()
                if health_check.invalidated_at_utc is not None
                else None
            ),
            "replacement_health_check_id": health_check.replacement_health_check_id,
            "updated_by_account_id": health_check.updated_by_account_id,
            "updated_at_utc": health_check.updated_at_utc.isoformat(),
            "row_version": health_check.row_version,
        }

    def list_health_checks(self, staff_id: int) -> StaffHealthCheckListResponse:
        self._require_staff(staff_id)
        return StaffHealthCheckListResponse(
            items=[
                self._health_check_response(health_check)
                for health_check in self.repository.list_health_checks(staff_id)
            ]
        )

    def create_health_check(
        self,
        staff_id: int,
        payload: StaffHealthCheckCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffHealthCheckResponse:
        self._require_staff(staff_id)
        now = _now()
        health_check = StaffHealthCheck(
            staff_id=staff_id,
            check_date=payload.check_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(health_check)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_HEALTH_CHECK_CREATE",
            entity_type="STAFF_HEALTH_CHECK",
            entity_pk=health_check.id,
            before=None,
            after=self._health_check_snapshot(health_check),
        )
        self._commit()
        return self._health_check_response(health_check)

    def update_health_check(
        self,
        staff_id: int,
        health_check_id: int,
        payload: StaffHealthCheckUpdateRequest,
        current_account: CurrentAccount,
    ) -> StaffHealthCheckResponse:
        self._require_staff(staff_id)
        health_check = self._require_health_check(
            staff_id,
            health_check_id,
            for_update=True,
        )
        self._require_version(health_check.row_version, payload.expected_row_version)
        before = self._health_check_snapshot(health_check)
        fields_set = payload.model_fields_set
        if "check_date" in fields_set:
            if payload.check_date is None:
                raise _domain_error("VALIDATION_ERROR", 422, field="check_date")
            health_check.check_date = payload.check_date
        health_check.updated_by_account_id = current_account.id
        health_check.updated_at_utc = _now()
        health_check.row_version += 1
        after = self._health_check_snapshot(health_check)
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_HEALTH_CHECK_UPDATE",
            entity_type="STAFF_HEALTH_CHECK",
            entity_pk=health_check.id,
            before=before,
            after=after,
        )
        self._commit()
        return self._health_check_response(health_check)

    def invalidate_health_check(
        self,
        staff_id: int,
        health_check_id: int,
        payload: StaffHealthCheckUpdateRequest,
        current_account: CurrentAccount,
    ) -> StaffHealthCheckResponse:
        self._require_staff(staff_id)
        health_check = self._require_health_check(
            staff_id,
            health_check_id,
            for_update=True,
        )
        self._require_version(health_check.row_version, payload.expected_row_version)
        now = _now()
        before = self._health_check_snapshot(health_check)
        health_check.invalidated_at_utc = now
        health_check.updated_by_account_id = current_account.id
        health_check.updated_at_utc = now
        health_check.row_version += 1
        self._flush()
        replacement = StaffHealthCheck(
            staff_id=health_check.staff_id,
            employment_id=health_check.employment_id,
            check_date=health_check.check_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(replacement)
        self._flush()
        health_check.replacement_health_check_id = replacement.id
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_HEALTH_CHECK_INVALIDATE",
            entity_type="STAFF_HEALTH_CHECK",
            entity_pk=health_check.id,
            before=before,
            after=self._health_check_snapshot(health_check),
        )
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_HEALTH_CHECK_REPLACEMENT_CREATE",
            entity_type="STAFF_HEALTH_CHECK",
            entity_pk=replacement.id,
            before=None,
            after=self._health_check_snapshot(replacement),
        )
        self._commit()
        return self._health_check_response(health_check)

    @staticmethod
    def _quarterly_consultation_response(
        consultation: StaffQuarterlyConsultation,
    ) -> StaffQuarterlyConsultationResponse:
        return StaffQuarterlyConsultationResponse(
            id=consultation.id,
            staff_id=consultation.staff_id,
            calendar_year=consultation.calendar_year,
            quarter_no=consultation.quarter_no,
            completed=consultation.completed,
            created_by_account_id=consultation.created_by_account_id,
            created_at_utc=consultation.created_at_utc,
            updated_by_account_id=consultation.updated_by_account_id,
            updated_at_utc=consultation.updated_at_utc,
            row_version=consultation.row_version,
        )

    @staticmethod
    def _quarterly_consultation_snapshot(
        consultation: StaffQuarterlyConsultation,
    ) -> dict[str, Any]:
        return {
            "staff_id": consultation.staff_id,
            "calendar_year": consultation.calendar_year,
            "quarter_no": consultation.quarter_no,
            "completed": consultation.completed,
            "created_by_account_id": consultation.created_by_account_id,
            "created_at_utc": consultation.created_at_utc.isoformat(),
            "updated_by_account_id": consultation.updated_by_account_id,
            "updated_at_utc": consultation.updated_at_utc.isoformat(),
            "row_version": consultation.row_version,
        }

    def _require_quarterly_consultation(
        self,
        staff_id: int,
        consultation_id: int,
        *,
        for_update: bool = False,
    ) -> StaffQuarterlyConsultation:
        consultation = self.repository.get_quarterly_consultation(
            staff_id,
            consultation_id,
            for_update=for_update,
        )
        if consultation is not None:
            return consultation
        other_staff_consultation = self.repository.get_quarterly_consultation_by_id(
            consultation_id,
        )
        if other_staff_consultation is not None and other_staff_consultation.staff_id != staff_id:
            raise _domain_error("STAFF_QUARTERLY_CONSULTATION_STAFF_MISMATCH", 409)
        raise _domain_error("STAFF_QUARTERLY_CONSULTATION_NOT_FOUND", 404)

    def list_quarterly_consultations(
        self,
        staff_id: int,
    ) -> StaffQuarterlyConsultationListResponse:
        self._require_staff(staff_id)
        return StaffQuarterlyConsultationListResponse(
            items=[
                self._quarterly_consultation_response(consultation)
                for consultation in self.repository.list_quarterly_consultations(staff_id)
            ]
        )

    def create_quarterly_consultation(
        self,
        staff_id: int,
        payload: StaffQuarterlyConsultationCreateRequest,
        current_account: CurrentAccount,
    ) -> StaffQuarterlyConsultationResponse:
        self._require_staff(staff_id)
        now = _now()
        consultation = StaffQuarterlyConsultation(
            staff_id=staff_id,
            calendar_year=payload.calendar_year,
            quarter_no=payload.quarter_no,
            completed=payload.completed,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(consultation)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_QUARTERLY_CONSULTATION_CREATE",
            entity_type="STAFF_QUARTERLY_CONSULTATION",
            entity_pk=consultation.id,
            before=None,
            after=self._quarterly_consultation_snapshot(consultation),
        )
        self._commit()
        return self._quarterly_consultation_response(consultation)

    def update_quarterly_consultation(
        self,
        staff_id: int,
        consultation_id: int,
        payload: StaffQuarterlyConsultationUpdateRequest,
        current_account: CurrentAccount,
    ) -> StaffQuarterlyConsultationResponse:
        self._require_staff(staff_id)
        consultation = self._require_quarterly_consultation(
            staff_id,
            consultation_id,
            for_update=True,
        )
        self._require_version(consultation.row_version, payload.expected_row_version)
        before = self._quarterly_consultation_snapshot(consultation)
        consultation.completed = payload.completed
        consultation.updated_by_account_id = current_account.id
        consultation.updated_at_utc = _now()
        consultation.row_version += 1
        after = self._quarterly_consultation_snapshot(consultation)
        self._audit(
            account_id=current_account.id,
            action_code="STAFF_QUARTERLY_CONSULTATION_UPDATE",
            entity_type="STAFF_QUARTERLY_CONSULTATION",
            entity_pk=consultation.id,
            before=before,
            after=after,
        )
        self._commit()
        return self._quarterly_consultation_response(consultation)


_MESSAGES.update(
    {
        "STAFF_QUARTERLY_CONSULTATION_NOT_FOUND": "Quarterly consultation was not found.",
        "STAFF_QUARTERLY_CONSULTATION_STAFF_MISMATCH": (
            "Quarterly consultation does not belong to the requested staff."
        ),
        "STAFF_QUARTERLY_CONSULTATION_DUPLICATE": (
            "A quarterly consultation already exists for this staff, year, and quarter."
        ),
        "STAFF_QUARTERLY_CONSULTATION_INVALID": "Quarterly consultation fields are invalid.",
    }
)

_MESSAGES.update(
    {
        "STAFF_HEALTH_CHECK_NOT_FOUND": "건강검진 사실을 찾을 수 없습니다.",
        "STAFF_HEALTH_CHECK_STAFF_MISMATCH": "건강검진 이력의 직원이 요청 대상과 다릅니다.",
    }
)
