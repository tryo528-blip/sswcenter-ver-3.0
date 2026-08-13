from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.dependencies import (
    RecipientManageAccountDependency,
    RecipientServiceDependency,
    RecipientViewAccountDependency,
    W1CServiceDependency,
    W1DServiceDependency,
)
from app.domains.recipient.detail_batch import (
    RecipientBasicBatchResponse,
    RecipientBasicCreateBatchRequest,
    RecipientBasicUpdateBatchRequest,
    RecipientDetailBatchRequest,
    RecipientDetailBatchResponse,
    RecipientDetailBatchService,
)
from app.domains.recipient.schemas import (
    GuardianCreateRequest,
    GuardianListResponse,
    GuardianResponse,
    GuardianUpdateRequest,
    RecipientCreateRequest,
    RecipientDeadlineListResponse,
    RecipientErrorEnvelope,
    RecipientListResponse,
    RecipientListStatusFilter,
    RecipientResponse,
    RecipientUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["recipients"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": RecipientErrorEnvelope},
    403: {"model": RecipientErrorEnvelope},
    404: {"model": RecipientErrorEnvelope},
    409: {"model": RecipientErrorEnvelope},
    422: {"model": RecipientErrorEnvelope},
    500: {"model": RecipientErrorEnvelope},
}


@router.post(
    "/recipients",
    response_model=RecipientResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_recipient(
    payload: RecipientCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: RecipientServiceDependency,
) -> RecipientResponse:
    return service.create_recipient(payload, current_account)


@router.get(
    "/recipients",
    response_model=RecipientListResponse,
    responses=ERROR_RESPONSES,
)
def list_recipients(
    current_account: RecipientViewAccountDependency,
    service: RecipientServiceDependency,
    search: str | None = Query(default=None, max_length=200),
    status_filter: Annotated[
        RecipientListStatusFilter,
        Query(alias="status"),
    ] = RecipientListStatusFilter.ALL,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> RecipientListResponse:
    del current_account
    return service.list_recipients(
        search=search,
        status=status_filter,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/recipients/deadlines",
    response_model=RecipientDeadlineListResponse,
    responses=ERROR_RESPONSES,
)
def list_recipient_deadlines(
    current_account: RecipientViewAccountDependency,
    service: RecipientServiceDependency,
) -> RecipientDeadlineListResponse:
    del current_account
    return service.list_recipient_deadlines()


@router.get(
    "/recipients/{recipient_id}",
    response_model=RecipientResponse,
    responses=ERROR_RESPONSES,
)
def get_recipient(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: RecipientServiceDependency,
) -> RecipientResponse:
    del current_account
    return service.get_recipient(recipient_id)


@router.patch(
    "/recipients/{recipient_id}",
    response_model=RecipientResponse,
    responses=ERROR_RESPONSES,
)
def update_recipient(
    recipient_id: int,
    payload: RecipientUpdateRequest,
    current_account: RecipientManageAccountDependency,
    service: RecipientServiceDependency,
) -> RecipientResponse:
    return service.update_recipient(recipient_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/guardians",
    response_model=GuardianListResponse,
    responses=ERROR_RESPONSES,
)
def list_guardians(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: RecipientServiceDependency,
) -> GuardianListResponse:
    del current_account
    return service.list_guardians(recipient_id)


@router.post(
    "/recipients/{recipient_id}/guardians",
    response_model=GuardianResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_guardian(
    recipient_id: int,
    payload: GuardianCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: RecipientServiceDependency,
) -> GuardianResponse:
    return service.create_guardian(recipient_id, payload, current_account)


@router.get(
    "/recipients/{recipient_id}/guardians/{guardian_id}",
    response_model=GuardianResponse,
    responses=ERROR_RESPONSES,
)
def get_guardian(
    recipient_id: int,
    guardian_id: int,
    current_account: RecipientViewAccountDependency,
    service: RecipientServiceDependency,
) -> GuardianResponse:
    del current_account
    return service.get_guardian(recipient_id, guardian_id)


@router.patch(
    "/recipients/{recipient_id}/guardians/{guardian_id}",
    response_model=GuardianResponse,
    responses=ERROR_RESPONSES,
)
def update_guardian(
    recipient_id: int,
    guardian_id: int,
    payload: GuardianUpdateRequest,
    current_account: RecipientManageAccountDependency,
    service: RecipientServiceDependency,
) -> GuardianResponse:
    return service.update_guardian(
        recipient_id,
        guardian_id,
        payload,
        current_account,
    )


@router.post(
    "/recipients/{recipient_id}/detail-batch",
    response_model=RecipientDetailBatchResponse,
    responses=ERROR_RESPONSES,
)
def save_recipient_detail_batch(
    recipient_id: int,
    payload: RecipientDetailBatchRequest,
    current_account: RecipientManageAccountDependency,
    recipient_service: RecipientServiceDependency,
    w1c_service: W1CServiceDependency,
    w1d_service: W1DServiceDependency,
) -> RecipientDetailBatchResponse:
    return RecipientDetailBatchService(
        recipient_service=recipient_service,
        w1c_service=w1c_service,
        w1d_service=w1d_service,
    ).save(
        recipient_id=recipient_id,
        payload=payload,
        current_account=current_account,
    )


@router.post(
    "/recipients/basic-batch",
    response_model=RecipientBasicBatchResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_recipient_basic_batch(
    payload: RecipientBasicCreateBatchRequest,
    current_account: RecipientManageAccountDependency,
    recipient_service: RecipientServiceDependency,
    w1c_service: W1CServiceDependency,
    w1d_service: W1DServiceDependency,
) -> RecipientBasicBatchResponse:
    return RecipientDetailBatchService(
        recipient_service=recipient_service,
        w1c_service=w1c_service,
        w1d_service=w1d_service,
    ).create_basic(payload=payload, current_account=current_account)


@router.post(
    "/recipients/{recipient_id}/basic-batch",
    response_model=RecipientBasicBatchResponse,
    responses=ERROR_RESPONSES,
)
def update_recipient_basic_batch(
    recipient_id: int,
    payload: RecipientBasicUpdateBatchRequest,
    current_account: RecipientManageAccountDependency,
    recipient_service: RecipientServiceDependency,
    w1c_service: W1CServiceDependency,
    w1d_service: W1DServiceDependency,
) -> RecipientBasicBatchResponse:
    return RecipientDetailBatchService(
        recipient_service=recipient_service,
        w1c_service=w1c_service,
        w1d_service=w1d_service,
    ).update_basic(
        recipient_id=recipient_id,
        payload=payload,
        current_account=current_account,
    )
