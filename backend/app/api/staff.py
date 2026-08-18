from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    StaffManageAccountDependency,
    StaffServiceDependency,
    StaffViewAccountDependency,
    staff_capabilities,
)
from app.domains.staff.schemas import (
    ErrorEnvelope,
    LicenseTypeListResponse,
    SensitiveIdentityRevealRequest,
    SensitiveIdentityRevealResponse,
    ServiceCatalogResponse,
    SessionCapabilitiesResponse,
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
    StaffServiceQualificationCloseRequest,
    StaffServiceQualificationCreateRequest,
    StaffServiceQualificationInvalidateRequest,
    StaffServiceQualificationListResponse,
    StaffServiceQualificationReplacementRequest,
    StaffServiceQualificationResponse,
    StaffUpdateRequest,
    TrainingCourseListResponse,
)

router = APIRouter(prefix="/api/v1", tags=["staff"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {
        "model": ErrorEnvelope,
        "description": (
            "STAFF_EMPLOYMENT_PERIOD_CONFLICT, STAFF_PERIOD_CONFLICT, "
            "STAFF_SERVICE_QUALIFICATION_CONFLICT, STAFF_PERIOD_OUTSIDE_EMPLOYMENT, "
            "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN, "
            "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN, or ROW_VERSION_CONFLICT"
        ),
    },
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}
SENSITIVE_REVEAL_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    423: {"model": ErrorEnvelope},
}

VS2_SERVICE_CATALOG_ROUTE = "/api/v1/catalogs/services"
VS2_LICENSE_TYPE_CATALOG_ROUTE = "/api/v1/catalogs/license-types"
VS2_LICENSE_ROUTE = "/api/v1/staff/{staff_id}/licenses"
VS2_QUALIFICATION_ROUTE = "/api/v1/staff/{staff_id}/service-qualifications"
VS3_TRAINING_COURSE_ROUTE = "/api/v1/staff/training-courses"
VS3_ONBOARDING_ROUTE = "/api/v1/staff/{staff_id}/onboarding-trainings"
VS3_PERIODIC_ROUTE = "/api/v1/staff/{staff_id}/periodic-trainings"
VS5_QUARTERLY_CONSULTATION_ROUTE = "/api/v1/staff/{staff_id}/quarterly-consultations"


@router.get(
    VS3_TRAINING_COURSE_ROUTE.removeprefix(router.prefix),
    response_model=TrainingCourseListResponse,
    responses=ERROR_RESPONSES,
)
def list_training_courses(
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> TrainingCourseListResponse:
    del current_account
    return service.list_training_courses()


@router.get(
    VS3_ONBOARDING_ROUTE.removeprefix(router.prefix),
    response_model=StaffOnboardingTrainingListResponse,
    responses=ERROR_RESPONSES,
)
def list_onboarding_trainings(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffOnboardingTrainingListResponse:
    del current_account
    return service.list_onboarding_trainings(staff_id)


@router.patch(
    f"{VS3_ONBOARDING_ROUTE}/{{training_id}}".removeprefix(router.prefix),
    response_model=StaffOnboardingTrainingResponse,
    responses=ERROR_RESPONSES,
)
def update_onboarding_training(
    staff_id: int,
    training_id: int,
    payload: StaffOnboardingTrainingUpdateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffOnboardingTrainingResponse:
    return service.update_onboarding_training(staff_id, training_id, payload, current_account)


@router.get(
    VS3_PERIODIC_ROUTE.removeprefix(router.prefix),
    response_model=StaffPeriodicTrainingListResponse,
    responses=ERROR_RESPONSES,
)
def list_periodic_trainings(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffPeriodicTrainingListResponse:
    del current_account
    return service.list_periodic_trainings(staff_id)


@router.post(
    VS3_PERIODIC_ROUTE.removeprefix(router.prefix),
    response_model=StaffPeriodicTrainingResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_periodic_training(
    staff_id: int,
    payload: StaffPeriodicTrainingCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffPeriodicTrainingResponse:
    return service.create_periodic_training(staff_id, payload, current_account)


@router.patch(
    f"{VS3_PERIODIC_ROUTE}/{{training_id}}".removeprefix(router.prefix),
    response_model=StaffPeriodicTrainingResponse,
    responses=ERROR_RESPONSES,
)
def update_periodic_training(
    staff_id: int,
    training_id: int,
    payload: StaffPeriodicTrainingUpdateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffPeriodicTrainingResponse:
    return service.update_periodic_training(staff_id, training_id, payload, current_account)


@router.post(
    f"{VS3_PERIODIC_ROUTE}/{{training_id}}/invalidate".removeprefix(router.prefix),
    response_model=StaffPeriodicTrainingResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_periodic_training(
    staff_id: int,
    training_id: int,
    payload: StaffPeriodicTrainingInvalidateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffPeriodicTrainingResponse:
    return service.invalidate_periodic_training(staff_id, training_id, payload, current_account)


@router.get(
    VS2_SERVICE_CATALOG_ROUTE.removeprefix(router.prefix),
    response_model=ServiceCatalogResponse,
    responses=ERROR_RESPONSES,
)
def list_service_catalog(
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> ServiceCatalogResponse:
    del current_account
    return service.list_service_catalog()


@router.get(
    VS2_LICENSE_TYPE_CATALOG_ROUTE.removeprefix(router.prefix),
    response_model=LicenseTypeListResponse,
    responses=ERROR_RESPONSES,
)
def list_license_types(
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> LicenseTypeListResponse:
    del current_account
    return service.list_license_types()


@router.post(
    "/staff",
    response_model=StaffCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_staff(
    payload: StaffCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffCreateResponse:
    return service.create_staff(payload, current_account)


@router.get(
    "/staff",
    response_model=StaffListResponse,
    responses=ERROR_RESPONSES,
)
def list_staff(
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
    search: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> StaffListResponse:
    del current_account
    return service.list_staff(search=search, page=page, page_size=page_size)


@router.get(
    "/staff/{staff_id}",
    response_model=StaffDetailResponse,
    responses=ERROR_RESPONSES,
)
def get_staff_detail(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffDetailResponse:
    del current_account
    return service.get_staff_detail(staff_id)


@router.get(
    VS2_LICENSE_ROUTE.removeprefix(router.prefix),
    response_model=StaffLicenseListResponse,
    responses=ERROR_RESPONSES,
)
def list_staff_licenses(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffLicenseListResponse:
    del current_account
    return service.list_licenses(staff_id)


@router.post(
    VS2_LICENSE_ROUTE.removeprefix(router.prefix),
    response_model=StaffLicenseResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_staff_license(
    staff_id: int,
    payload: StaffLicenseCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffLicenseResponse:
    return service.create_license(staff_id, payload, current_account)


@router.post(
    "/staff/{staff_id}/licenses/{license_id}/replacements",
    response_model=StaffLicenseResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_staff_license(
    staff_id: int,
    license_id: int,
    payload: StaffLicenseReplacementRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffLicenseResponse:
    return service.replace_license(staff_id, license_id, payload, current_account)


@router.post(
    "/staff/{staff_id}/licenses/{license_id}/invalidate",
    response_model=StaffLicenseResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_staff_license(
    staff_id: int,
    license_id: int,
    payload: StaffLicenseInvalidateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffLicenseResponse:
    return service.invalidate_license(staff_id, license_id, payload, current_account)


@router.get(
    VS2_QUALIFICATION_ROUTE.removeprefix(router.prefix),
    response_model=StaffServiceQualificationListResponse,
    responses=ERROR_RESPONSES,
)
def list_staff_service_qualifications(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffServiceQualificationListResponse:
    del current_account
    return service.list_service_qualifications(staff_id)


@router.post(
    VS2_QUALIFICATION_ROUTE.removeprefix(router.prefix),
    response_model=StaffServiceQualificationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_staff_service_qualification(
    staff_id: int,
    payload: StaffServiceQualificationCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffServiceQualificationResponse:
    return service.create_service_qualification(staff_id, payload, current_account)


@router.post(
    "/staff/{staff_id}/service-qualifications/{qualification_id}/close",
    response_model=StaffServiceQualificationResponse,
    responses=ERROR_RESPONSES,
)
def close_staff_service_qualification(
    staff_id: int,
    qualification_id: int,
    payload: StaffServiceQualificationCloseRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffServiceQualificationResponse:
    return service.close_service_qualification(
        staff_id,
        qualification_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/service-qualifications/{qualification_id}/replacements",
    response_model=StaffServiceQualificationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_staff_service_qualification(
    staff_id: int,
    qualification_id: int,
    payload: StaffServiceQualificationReplacementRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffServiceQualificationResponse:
    return service.replace_service_qualification(
        staff_id,
        qualification_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/service-qualifications/{qualification_id}/invalidate",
    response_model=StaffServiceQualificationResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_staff_service_qualification(
    staff_id: int,
    qualification_id: int,
    payload: StaffServiceQualificationInvalidateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffServiceQualificationResponse:
    return service.invalidate_service_qualification(
        staff_id,
        qualification_id,
        payload,
        current_account,
    )


VS4_HEALTH_CHECK_ROUTE = "/api/v1/staff/{staff_id}/health-checks"


@router.get(
    VS4_HEALTH_CHECK_ROUTE.removeprefix(router.prefix),
    response_model=StaffHealthCheckListResponse,
    responses=ERROR_RESPONSES,
)
def list_health_checks(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffHealthCheckListResponse:
    del current_account
    return service.list_health_checks(staff_id)


@router.post(
    VS4_HEALTH_CHECK_ROUTE.removeprefix(router.prefix),
    response_model=StaffHealthCheckResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_health_check(
    staff_id: int,
    payload: StaffHealthCheckCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffHealthCheckResponse:
    return service.create_health_check(staff_id, payload, current_account)


@router.patch(
    f"{VS4_HEALTH_CHECK_ROUTE}/{{health_check_id}}".removeprefix(router.prefix),
    response_model=StaffHealthCheckResponse,
    responses=ERROR_RESPONSES,
)
def update_health_check(
    staff_id: int,
    health_check_id: int,
    payload: StaffHealthCheckUpdateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffHealthCheckResponse:
    return service.update_health_check(staff_id, health_check_id, payload, current_account)


@router.post(
    f"{VS4_HEALTH_CHECK_ROUTE}/{{health_check_id}}/invalidate".removeprefix(router.prefix),
    response_model=StaffHealthCheckResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_health_check(
    staff_id: int,
    health_check_id: int,
    payload: StaffHealthCheckUpdateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffHealthCheckResponse:
    return service.invalidate_health_check(staff_id, health_check_id, payload, current_account)


@router.get(
    VS5_QUARTERLY_CONSULTATION_ROUTE.removeprefix(router.prefix),
    response_model=StaffQuarterlyConsultationListResponse,
    responses=ERROR_RESPONSES,
)
def list_quarterly_consultations(
    staff_id: int,
    current_account: StaffViewAccountDependency,
    service: StaffServiceDependency,
) -> StaffQuarterlyConsultationListResponse:
    del current_account
    return service.list_quarterly_consultations(staff_id)


@router.post(
    VS5_QUARTERLY_CONSULTATION_ROUTE.removeprefix(router.prefix),
    response_model=StaffQuarterlyConsultationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_quarterly_consultation(
    staff_id: int,
    payload: StaffQuarterlyConsultationCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffQuarterlyConsultationResponse:
    return service.create_quarterly_consultation(staff_id, payload, current_account)


@router.patch(
    f"{VS5_QUARTERLY_CONSULTATION_ROUTE}/{{consultation_id}}".removeprefix(router.prefix),
    response_model=StaffQuarterlyConsultationResponse,
    responses=ERROR_RESPONSES,
)
def update_quarterly_consultation(
    staff_id: int,
    consultation_id: int,
    payload: StaffQuarterlyConsultationUpdateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffQuarterlyConsultationResponse:
    return service.update_quarterly_consultation(
        staff_id,
        consultation_id,
        payload,
        current_account,
    )


@router.patch(
    "/staff/{staff_id}",
    response_model=StaffDetailResponse,
    responses=ERROR_RESPONSES,
)
def update_staff(
    staff_id: int,
    payload: StaffUpdateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffDetailResponse:
    return service.update_staff(staff_id, payload, current_account)


@router.post(
    "/staff/{staff_id}/employments",
    response_model=StaffEmploymentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_employment(
    staff_id: int,
    payload: StaffEmploymentCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffEmploymentResponse:
    return service.create_employment(staff_id, payload, current_account)


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/close",
    response_model=StaffEmploymentResponse,
    responses=ERROR_RESPONSES,
)
def close_employment(
    staff_id: int,
    employment_id: int,
    payload: StaffEmploymentCloseRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffEmploymentResponse:
    return service.close_employment(
        staff_id,
        employment_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/replacements",
    response_model=StaffEmploymentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_employment(
    staff_id: int,
    employment_id: int,
    payload: StaffEmploymentReplacementRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffEmploymentResponse:
    return service.replace_employment(
        staff_id,
        employment_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/positions",
    response_model=StaffPositionPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_position(
    staff_id: int,
    employment_id: int,
    payload: StaffPositionCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffPositionPeriodResponse:
    return service.create_position(
        staff_id,
        employment_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/positions/{period_id}/close",
    response_model=StaffPositionPeriodResponse,
    responses=ERROR_RESPONSES,
)
def close_position(
    staff_id: int,
    employment_id: int,
    period_id: int,
    payload: StaffPeriodCloseRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffPositionPeriodResponse:
    return service.close_position(
        staff_id,
        employment_id,
        period_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/positions/{period_id}/replacements",
    response_model=StaffPositionPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_position(
    staff_id: int,
    employment_id: int,
    period_id: int,
    payload: StaffPositionReplacementRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffPositionPeriodResponse:
    return service.replace_position(
        staff_id,
        employment_id,
        period_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/operational-roles",
    response_model=StaffOperationalRolePeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_operational_role(
    staff_id: int,
    employment_id: int,
    payload: StaffOperationalRoleCreateRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffOperationalRolePeriodResponse:
    return service.create_operational_role(
        staff_id,
        employment_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/operational-roles/{period_id}/close",
    response_model=StaffOperationalRolePeriodResponse,
    responses=ERROR_RESPONSES,
)
def close_operational_role(
    staff_id: int,
    employment_id: int,
    period_id: int,
    payload: StaffPeriodCloseRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffOperationalRolePeriodResponse:
    return service.close_operational_role(
        staff_id,
        employment_id,
        period_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/employments/{employment_id}/operational-roles/{period_id}/replacements",
    response_model=StaffOperationalRolePeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_operational_role(
    staff_id: int,
    employment_id: int,
    period_id: int,
    payload: StaffOperationalRoleReplacementRequest,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> StaffOperationalRolePeriodResponse:
    return service.replace_operational_role(
        staff_id,
        employment_id,
        period_id,
        payload,
        current_account,
    )


@router.post(
    "/staff/{staff_id}/sensitive-identity/reveal",
    response_model=SensitiveIdentityRevealResponse,
    responses=SENSITIVE_REVEAL_ERROR_RESPONSES,
)
def reveal_sensitive_identity(
    staff_id: int,
    payload: SensitiveIdentityRevealRequest,
    response: Response,
    current_account: StaffManageAccountDependency,
    service: StaffServiceDependency,
) -> SensitiveIdentityRevealResponse:
    response.headers["Cache-Control"] = "no-store"
    return service.reveal_sensitive_identity(
        staff_id,
        payload.current_pin,
        current_account,
    )


@router.get(
    "/session-capabilities",
    response_model=SessionCapabilitiesResponse,
    responses=ERROR_RESPONSES,
)
def get_session_capabilities(
    response: Response,
    capabilities: Annotated[dict[str, bool], Depends(staff_capabilities)],
) -> SessionCapabilitiesResponse:
    response.headers["Cache-Control"] = "no-store"
    return SessionCapabilitiesResponse.model_validate(capabilities)
