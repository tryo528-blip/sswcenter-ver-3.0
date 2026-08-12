from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from app.api.dependencies import (
    RecipientManageAccountDependency,
    RecipientViewAccountDependency,
    W1DServiceDependency,
)
from app.domains.recipient.schemas import RecipientErrorEnvelope
from app.domains.w1d.schemas import (
    CertificationTransitionApplyRequest,
    CertificationTransitionApplyResponse,
    CertificationTransitionPreviewRequest,
    CertificationTransitionPreviewResponse,
    ContractCreateRequest,
    ContractEndRequest,
    ContractListResponse,
    ContractResponse,
)

router = APIRouter(prefix="/api/v1", tags=["recipients-w1d"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": RecipientErrorEnvelope},
    403: {"model": RecipientErrorEnvelope},
    404: {"model": RecipientErrorEnvelope},
    409: {"model": RecipientErrorEnvelope},
    422: {"model": RecipientErrorEnvelope},
    500: {"model": RecipientErrorEnvelope},
}


@router.get(
    "/recipients/{recipient_id}/contracts",
    response_model=ContractListResponse,
    operation_id="listRecipientContracts",
    responses=ERROR_RESPONSES,
)
def list_recipient_contracts(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1DServiceDependency,
) -> ContractListResponse:
    del current_account
    return service.list_contracts(recipient_id)


@router.post(
    "/recipients/{recipient_id}/contracts",
    response_model=ContractResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createRecipientContract",
    responses=ERROR_RESPONSES,
    description=(
        "Create a service contract. Errors: CONTRACT_SERVICE_PERIOD_CONFLICT, "
        "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT, CONTRACT_REACTIVATION_FORBIDDEN."
    ),
)
def create_recipient_contract(
    recipient_id: int,
    payload: ContractCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1DServiceDependency,
) -> ContractResponse:
    return service.create_contract(recipient_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/contracts/{contract_id}",
    response_model=ContractResponse,
    operation_id="getRecipientContract",
    responses=ERROR_RESPONSES,
)
def get_recipient_contract(
    recipient_id: int,
    contract_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1DServiceDependency,
) -> ContractResponse:
    del current_account
    return service.get_contract(recipient_id, contract_id)


@router.post(
    "/recipients/{recipient_id}/contracts/{contract_id}/end",
    response_model=ContractResponse,
    operation_id="endRecipientContract",
    responses=ERROR_RESPONSES,
)
def end_recipient_contract(
    recipient_id: int,
    contract_id: int,
    payload: ContractEndRequest,
    current_account: RecipientManageAccountDependency,
    service: W1DServiceDependency,
) -> ContractResponse:
    return service.end_contract(recipient_id, contract_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/certification-transitions/preview",
    response_model=CertificationTransitionPreviewResponse,
    operation_id="previewCertificationTransition",
    responses=ERROR_RESPONSES,
)
def preview_certification_transition(
    recipient_id: int,
    payload: CertificationTransitionPreviewRequest,
    current_account: RecipientManageAccountDependency,
    service: W1DServiceDependency,
) -> CertificationTransitionPreviewResponse:
    return service.preview_certification_transition(recipient_id, payload, current_account)


@router.post(
    "/recipients/{recipient_id}/certification-transitions/apply",
    response_model=CertificationTransitionApplyResponse,
    operation_id="applyCertificationTransition",
    responses=ERROR_RESPONSES,
    description=(
        "Apply a certification transition. Errors: "
        "CERTIFICATION_TRANSITION_STALE, "
        "CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED, "
        "CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH, "
        "CERTIFICATION_TRANSITION_TOKEN_INVALID, "
        "CERTIFICATION_TRANSITION_PREVIEW_REQUIRED."
    ),
)
def apply_certification_transition(
    recipient_id: int,
    payload: CertificationTransitionApplyRequest,
    current_account: RecipientManageAccountDependency,
    service: W1DServiceDependency,
) -> CertificationTransitionApplyResponse:
    return service.apply_certification_transition(recipient_id, payload, current_account)
