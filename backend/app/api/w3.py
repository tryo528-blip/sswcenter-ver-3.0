"""FILE_ONLY W3 import, confirmation, apply, and correction API."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.dependencies import (
    W3ManageAccountDependency,
    W3ServiceDependency,
    W3ViewAccountDependency,
)
from app.domains.staff.schemas import ErrorEnvelope
from app.domains.w3.schemas import (
    W3ApplyRequest,
    W3ConfirmRequest,
    W3PlanAdjustmentRequest,
    W3PlanAdjustmentResponse,
    W3ResolveDecisionRequest,
    W3SourceType,
    W3SupplementRequest,
    W3SupplementResponse,
    W3WorkspaceResponse,
)
from app.domains.w3.workbook_parser import MAX_COMPRESSED_BYTES

router = APIRouter(prefix="/api/v1/w3", tags=["w3-file-workspace"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}
LOCKED_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    423: {"model": ErrorEnvelope},
}


@router.get(
    "/workspace",
    response_model=W3WorkspaceResponse,
    operation_id="getW3Workspace",
    responses=ERROR_RESPONSES,
)
def get_workspace(
    source_type: W3SourceType,
    target_date: date,
    current_account: W3ViewAccountDependency,
    service: W3ServiceDependency,
) -> W3WorkspaceResponse:
    del current_account
    return service.workspace(source_type=source_type, target_date=target_date)


@router.post(
    "/import-runs",
    response_model=W3WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadW3Workbook",
    responses=ERROR_RESPONSES,
)
async def upload_workbook(
    source_type: Annotated[W3SourceType, Form()],
    target_date: Annotated[date, Form()],
    file: Annotated[UploadFile, File()],
    current_account: W3ManageAccountDependency,
    service: W3ServiceDependency,
) -> W3WorkspaceResponse:
    content = await file.read(MAX_COMPRESSED_BYTES + 1)
    try:
        return service.upload_workbook(
            content=content,
            original_filename=file.filename,
            source_type=source_type,
            target_date=target_date,
            account=current_account,
        )
    finally:
        await file.close()


@router.post(
    "/import-runs/{run_id}/confirm",
    response_model=W3WorkspaceResponse,
    operation_id="confirmW3ImportRun",
    responses=ERROR_RESPONSES,
)
def confirm_run(
    run_id: int,
    payload: W3ConfirmRequest,
    current_account: W3ManageAccountDependency,
    service: W3ServiceDependency,
) -> W3WorkspaceResponse:
    return service.confirm_run(run_id, payload, current_account)


@router.post(
    "/import-runs/{run_id}/apply",
    response_model=W3WorkspaceResponse,
    operation_id="applyW3ImportRun",
    responses=ERROR_RESPONSES,
)
def apply_run(
    run_id: int,
    payload: W3ApplyRequest,
    current_account: W3ManageAccountDependency,
    service: W3ServiceDependency,
) -> W3WorkspaceResponse:
    return service.apply_run(run_id, payload, current_account)


@router.post(
    "/import-runs/{run_id}/decisions/{decision_id}/resolve",
    response_model=W3WorkspaceResponse,
    operation_id="resolveW3MatchDecision",
    responses=ERROR_RESPONSES,
)
def resolve_decision(
    run_id: int,
    decision_id: int,
    payload: W3ResolveDecisionRequest,
    current_account: W3ManageAccountDependency,
    service: W3ServiceDependency,
) -> W3WorkspaceResponse:
    return service.resolve_decision(run_id, decision_id, payload, current_account)


@router.post(
    "/actual-work/{revision_id}/supplements",
    response_model=W3SupplementResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createW3ManualSupplement",
    responses=LOCKED_ERROR_RESPONSES,
)
def create_supplement(
    revision_id: int,
    payload: W3SupplementRequest,
    current_account: W3ManageAccountDependency,
    service: W3ServiceDependency,
) -> W3SupplementResponse:
    return service.create_supplement(revision_id, payload, current_account)


@router.post(
    "/actual-work/{revision_id}/plan-adjustments",
    response_model=W3PlanAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="adoptW3PlanAdjustment",
    responses=LOCKED_ERROR_RESPONSES,
)
def adopt_plan_adjustment(
    revision_id: int,
    payload: W3PlanAdjustmentRequest,
    current_account: W3ManageAccountDependency,
    service: W3ServiceDependency,
) -> W3PlanAdjustmentResponse:
    return service.adopt_plan_adjustment(revision_id, payload, current_account)
