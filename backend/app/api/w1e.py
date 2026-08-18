from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.dependencies import (
    RecipientManageAccountDependency,
    RecipientViewAccountDependency,
    W1EServiceDependency,
)
from app.domains.recipient.schemas import RecipientErrorEnvelope
from app.domains.w1e.schemas import (
    CareAssignmentCreateRequest,
    CareAssignmentListResponse,
    CareAssignmentReplacementRequest,
    CareAssignmentReplacementResponse,
    CareAssignmentResponse,
)

router = APIRouter(prefix="/api/v1", tags=["recipients-w1e"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": RecipientErrorEnvelope},
    403: {"model": RecipientErrorEnvelope},
    404: {"model": RecipientErrorEnvelope},
    409: {
        "model": RecipientErrorEnvelope,
        "description": (
            "CARE_ASSIGNMENT_CONCURRENT_CONFLICT, "
            "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN, or ROW_VERSION_CONFLICT"
        ),
    },
    422: {
        "model": RecipientErrorEnvelope,
        "description": (
            "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD, "
            "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD, "
            "CARE_ASSIGNMENT_STAFF_INELIGIBLE, "
            "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED, "
            "CARE_ASSIGNMENT_PERIOD_CONFLICT, or VALIDATION_ERROR"
        ),
    },
    500: {"model": RecipientErrorEnvelope},
}


@router.get(
    "/recipients/{recipient_id}/contracts/{contract_id}/assignments",
    response_model=CareAssignmentListResponse,
    operation_id="listCareAssignments",
    responses=ERROR_RESPONSES,
)
def list_care_assignments(
    recipient_id: int,
    contract_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1EServiceDependency,
    as_of: Annotated[date | None, Query()] = None,
) -> CareAssignmentListResponse:
    del current_account
    return service.list_assignments(recipient_id, contract_id, as_of=as_of)


@router.post(
    "/recipients/{recipient_id}/contracts/{contract_id}/assignments",
    response_model=CareAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCareAssignment",
    responses=ERROR_RESPONSES,
)
def create_care_assignment(
    recipient_id: int,
    contract_id: int,
    payload: CareAssignmentCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W1EServiceDependency,
) -> CareAssignmentResponse:
    return service.create_assignment(recipient_id, contract_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/contracts/{contract_id}/assignments/{assignment_id}",
    response_model=CareAssignmentResponse,
    operation_id="getCareAssignment",
    responses=ERROR_RESPONSES,
)
def get_care_assignment(
    recipient_id: int,
    contract_id: int,
    assignment_id: int,
    current_account: RecipientViewAccountDependency,
    service: W1EServiceDependency,
) -> CareAssignmentResponse:
    del current_account
    return service.get_assignment(recipient_id, contract_id, assignment_id)


@router.put(
    "/recipients/{recipient_id}/contracts/{contract_id}/assignments/{assignment_id}",
    response_model=CareAssignmentReplacementResponse,
    operation_id="replaceCareAssignment",
    responses=ERROR_RESPONSES,
)
def replace_care_assignment(
    recipient_id: int,
    contract_id: int,
    assignment_id: int,
    payload: CareAssignmentReplacementRequest,
    current_account: RecipientManageAccountDependency,
    service: W1EServiceDependency,
) -> CareAssignmentReplacementResponse:
    return service.replace_assignment(
        recipient_id,
        contract_id,
        assignment_id,
        payload,
        current_account,
    )
