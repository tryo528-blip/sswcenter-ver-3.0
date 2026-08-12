from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, status

from app.api.dependencies import (
    RecipientManageAccountDependency,
    RecipientViewAccountDependency,
    W1CServiceDependency,
)
from app.domains.recipient.schemas import HistoryInvalidateRequest, RecipientErrorEnvelope
from app.domains.w1c.schemas import (
    ApprovalAmountPeriodCreateRequest,
    ApprovalAmountPeriodListResponse,
    ApprovalAmountPeriodReplacementRequest,
    ApprovalAmountPeriodReplacementResponse,
    ApprovalAmountPeriodResponse,
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
    GradePeriodCreateRequest,
    GradePeriodListResponse,
    GradePeriodReplacementRequest,
    GradePeriodReplacementResponse,
    GradePeriodResponse,
)

router = APIRouter(prefix="/api/v1", tags=["recipients-w1c"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": RecipientErrorEnvelope},
    403: {"model": RecipientErrorEnvelope},
    404: {"model": RecipientErrorEnvelope},
    409: {"model": RecipientErrorEnvelope},
    422: {"model": RecipientErrorEnvelope},
    500: {"model": RecipientErrorEnvelope},
}


@router.get(
    "/recipients/{recipient_id}/certification-identity",
    response_model=CertificationIdentityResponse,
    responses=ERROR_RESPONSES,
)
def get_certification_identity(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1CServiceDependency,
) -> CertificationIdentityResponse:
    del current_account
    return service.get_identity(recipient_id)


@router.post(
    "/recipients/{recipient_id}/certification-identity",
    response_model=CertificationIdentityResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_certification_identity(
    recipient_id: int,
    payload: CertificationIdentityCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> CertificationIdentityResponse:
    return service.create_identity(recipient_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/certification-periods",
    response_model=CertificationPeriodListResponse,
    responses=ERROR_RESPONSES,
)
def list_certification_periods(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1CServiceDependency,
) -> CertificationPeriodListResponse:
    del current_account
    return service.list_certification_periods(recipient_id)


@router.post(
    "/recipients/{recipient_id}/certification-periods",
    response_model=CertificationPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_certification_period(
    recipient_id: int,
    payload: CertificationPeriodCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> CertificationPeriodResponse:
    return service.create_certification_period(recipient_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/certification-periods/{period_id}/invalidate",
    response_model=CertificationPeriodResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_certification_period(
    recipient_id: int,
    period_id: int,
    payload: HistoryInvalidateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> CertificationPeriodResponse:
    return service.invalidate_certification_period(
        recipient_id,
        period_id,
        payload,
        current_account,
    )


@router.post(
    "/recipients/{recipient_id}/certification-periods/{period_id}/replacements",
    response_model=CertificationPeriodReplacementResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_certification_period(
    recipient_id: int,
    period_id: int,
    payload: CertificationPeriodReplacementRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> CertificationPeriodReplacementResponse:
    return service.replace_certification_period(
        recipient_id,
        period_id,
        payload,
        current_account,
    )


@router.get(
    "/recipients/{recipient_id}/grade-periods",
    response_model=GradePeriodListResponse,
    responses=ERROR_RESPONSES,
)
def list_grade_periods(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1CServiceDependency,
) -> GradePeriodListResponse:
    del current_account
    return service.list_grade_periods(recipient_id)


@router.post(
    "/recipients/{recipient_id}/grade-periods",
    response_model=GradePeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_grade_period(
    recipient_id: int,
    payload: GradePeriodCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> GradePeriodResponse:
    return service.create_grade_period(recipient_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/grade-periods/{period_id}/invalidate",
    response_model=GradePeriodResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_grade_period(
    recipient_id: int,
    period_id: int,
    payload: HistoryInvalidateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> GradePeriodResponse:
    return service.invalidate_grade_period(recipient_id, period_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/grade-periods/{period_id}/replacements",
    response_model=GradePeriodReplacementResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_grade_period(
    recipient_id: int,
    period_id: int,
    payload: GradePeriodReplacementRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> GradePeriodReplacementResponse:
    return service.replace_grade_period(recipient_id, period_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/benefit-periods",
    response_model=BenefitPeriodListResponse,
    responses=ERROR_RESPONSES,
)
def list_benefit_periods(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1CServiceDependency,
) -> BenefitPeriodListResponse:
    del current_account
    return service.list_benefit_periods(recipient_id)


@router.post(
    "/recipients/{recipient_id}/benefit-periods",
    response_model=BenefitPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_benefit_period(
    recipient_id: int,
    payload: BenefitPeriodCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> BenefitPeriodResponse:
    return service.create_benefit_period(recipient_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/benefit-periods/effective",
    response_model=EffectiveBenefitResponse,
    responses=ERROR_RESPONSES,
)
def get_effective_benefit(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1CServiceDependency,
    on_date: date,
) -> EffectiveBenefitResponse:
    del current_account
    return service.get_effective_benefit(recipient_id, on_date)


@router.post(
    "/recipients/{recipient_id}/benefit-periods/{period_id}/invalidate",
    response_model=BenefitPeriodResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_benefit_period(
    recipient_id: int,
    period_id: int,
    payload: HistoryInvalidateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> BenefitPeriodResponse:
    return service.invalidate_benefit_period(recipient_id, period_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/benefit-periods/{period_id}/replacements",
    response_model=BenefitPeriodReplacementResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_benefit_period(
    recipient_id: int,
    period_id: int,
    payload: BenefitPeriodReplacementRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> BenefitPeriodReplacementResponse:
    return service.replace_benefit_period(recipient_id, period_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/approval-amount-periods",
    response_model=ApprovalAmountPeriodListResponse,
    responses=ERROR_RESPONSES,
)
def list_approval_amount_periods(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1CServiceDependency,
) -> ApprovalAmountPeriodListResponse:
    del current_account
    return service.list_approval_amount_periods(recipient_id)


@router.post(
    "/recipients/{recipient_id}/approval-amount-periods",
    response_model=ApprovalAmountPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_approval_amount_period(
    recipient_id: int,
    payload: ApprovalAmountPeriodCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> ApprovalAmountPeriodResponse:
    return service.create_approval_amount_period(recipient_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/approval-amount-periods/{period_id}/invalidate",
    response_model=ApprovalAmountPeriodResponse,
    responses=ERROR_RESPONSES,
)
def invalidate_approval_amount_period(
    recipient_id: int,
    period_id: int,
    payload: HistoryInvalidateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> ApprovalAmountPeriodResponse:
    return service.invalidate_approval_amount_period(
        recipient_id,
        period_id,
        payload,
        current_account,
    )


@router.post(
    "/recipients/{recipient_id}/approval-amount-periods/{period_id}/replacements",
    response_model=ApprovalAmountPeriodReplacementResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def replace_approval_amount_period(
    recipient_id: int,
    period_id: int,
    payload: ApprovalAmountPeriodReplacementRequest,
    current_account: RecipientManageAccountDependency,
    service: W1CServiceDependency,
) -> ApprovalAmountPeriodReplacementResponse:
    return service.replace_approval_amount_period(
        recipient_id,
        period_id,
        payload,
        current_account,
    )
