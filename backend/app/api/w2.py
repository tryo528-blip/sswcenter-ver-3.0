"""W2 core-ledger API router.

``app.main`` intentionally does not import this module in the isolated slice.
Integration only needs to include ``router`` after the W1 routers.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies import (
    CsrfAccountDependency,
    CurrentAccountDependency,
    DatabaseSession,
    RecipientManageAccountDependency,
    RecipientViewAccountDependency,
)
from app.domains.staff.schemas import ErrorEnvelope
from app.domains.w2.schemas import (
    OfficialWorkCardCloseRequest,
    OfficialWorkCardListResponse,
    PersonalTodoCreateRequest,
    PersonalTodoDeleteRequest,
    PersonalTodoListResponse,
    PersonalTodoReorderRequest,
    PersonalTodoUpdateRequest,
    ProfessionalAssignmentCreateRequest,
    ProfessionalAssignmentHistoryResponse,
    ProfessionalAssignmentReplaceRequest,
    ProfessionalAssignmentResponse,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleFinalizeRequest,
    ScheduleMonthResponse,
    ScheduleReplaceRequest,
    ServicePlanNoticeCreateRequest,
    ServicePlanNoticeHistoryResponse,
    ServicePlanNoticeReplaceRequest,
    ServicePlanNoticeResponse,
)
from app.domains.w2.service import W2Service

router = APIRouter(prefix="/api/v1", tags=["w2-core"])

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}
SCHEDULE_MUTATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    423: {"model": ErrorEnvelope},
}


def get_w2_service(request: Request, database_session: DatabaseSession) -> W2Service:
    request_id = getattr(request.state, "request_id", None)
    return W2Service(
        database_session,
        request_id=request_id if isinstance(request_id, UUID) else None,
    )


W2ServiceDependency = Annotated[W2Service, Depends(get_w2_service)]


@router.get(
    "/professional-assignments/{recipient_id}",
    response_model=ProfessionalAssignmentHistoryResponse,
    operation_id="listW2ProfessionalAssignmentHistory",
    responses=ERROR_RESPONSES,
)
def list_professional_assignments(
    recipient_id: int,
    service_month: date,
    current_account: RecipientViewAccountDependency,
    service: W2ServiceDependency,
) -> ProfessionalAssignmentHistoryResponse:
    del current_account
    return service.list_professional_assignments(recipient_id, service_month)


@router.post(
    "/professional-assignments/{recipient_id}/{service_month}",
    response_model=ProfessionalAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createW2ProfessionalAssignment",
    responses=ERROR_RESPONSES,
)
def create_professional_assignment(
    recipient_id: int,
    service_month: date,
    payload: ProfessionalAssignmentCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ProfessionalAssignmentResponse:
    return service.create_professional_assignment(
        recipient_id,
        service_month,
        payload,
        current_account,
    )


@router.put(
    "/professional-assignments/{recipient_id}/{service_month}/{assignment_id}",
    response_model=ProfessionalAssignmentResponse,
    operation_id="replaceW2ProfessionalAssignment",
    responses=ERROR_RESPONSES,
)
def replace_professional_assignment(
    recipient_id: int,
    service_month: date,
    assignment_id: int,
    payload: ProfessionalAssignmentReplaceRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ProfessionalAssignmentResponse:
    return service.replace_professional_assignment(
        recipient_id,
        service_month,
        assignment_id,
        payload,
        current_account,
    )


@router.get(
    "/recipients/{recipient_id}/service-plan-notices",
    response_model=ServicePlanNoticeHistoryResponse,
    operation_id="listW2ServicePlanNotices",
    responses=ERROR_RESPONSES,
)
def list_service_plan_notices(
    recipient_id: int,
    current_account: RecipientViewAccountDependency,
    service: W2ServiceDependency,
) -> ServicePlanNoticeHistoryResponse:
    del current_account
    return service.list_service_plan_notices(recipient_id)


@router.post(
    "/recipients/{recipient_id}/service-plan-notices",
    response_model=ServicePlanNoticeResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createW2ServicePlanNotice",
    responses=ERROR_RESPONSES,
)
def create_service_plan_notice(
    recipient_id: int,
    payload: ServicePlanNoticeCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ServicePlanNoticeResponse:
    return service.create_service_plan_notice(recipient_id, payload, current_account)


@router.put(
    "/recipients/{recipient_id}/service-plan-notices/{notice_id}",
    response_model=ServicePlanNoticeResponse,
    operation_id="replaceW2ServicePlanNotice",
    responses=ERROR_RESPONSES,
)
def replace_service_plan_notice(
    recipient_id: int,
    notice_id: int,
    payload: ServicePlanNoticeReplaceRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ServicePlanNoticeResponse:
    return service.replace_service_plan_notice(
        recipient_id,
        notice_id,
        payload,
        current_account,
    )


@router.get(
    "/schedules",
    response_model=ScheduleMonthResponse,
    operation_id="listW2Schedules",
    responses=ERROR_RESPONSES,
)
def list_schedules(
    month: date,
    current_account: RecipientViewAccountDependency,
    service: W2ServiceDependency,
    recipient_id: Annotated[int | None, Query(gt=0)] = None,
    staff_id: Annotated[int | None, Query(gt=0)] = None,
) -> ScheduleMonthResponse:
    del current_account
    return service.list_schedules(month, recipient_id=recipient_id, staff_id=staff_id)


@router.post(
    "/schedules",
    response_model=ScheduleMonthResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createW2Schedule",
    responses=SCHEDULE_MUTATION_ERROR_RESPONSES,
)
def create_schedule(
    payload: ScheduleCreateRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ScheduleMonthResponse:
    return service.create_schedule(payload, current_account)


@router.put(
    "/schedules/{schedule_id}",
    response_model=ScheduleMonthResponse,
    operation_id="replaceW2Schedule",
    responses=SCHEDULE_MUTATION_ERROR_RESPONSES,
)
def replace_schedule(
    schedule_id: int,
    payload: ScheduleReplaceRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ScheduleMonthResponse:
    return service.replace_schedule(schedule_id, payload, current_account)


@router.delete(
    "/schedules/{schedule_id}",
    response_model=ScheduleMonthResponse,
    operation_id="deleteW2Schedule",
    responses=SCHEDULE_MUTATION_ERROR_RESPONSES,
)
def delete_schedule(
    schedule_id: int,
    payload: ScheduleDeleteRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ScheduleMonthResponse:
    return service.delete_schedule(schedule_id, payload, current_account)


@router.post(
    "/schedule-months/{schedule_month}/finalize",
    response_model=ScheduleMonthResponse,
    operation_id="finalizeW2ScheduleMonth",
    responses=SCHEDULE_MUTATION_ERROR_RESPONSES,
)
def finalize_schedule_month(
    schedule_month: date,
    payload: ScheduleFinalizeRequest,
    current_account: RecipientManageAccountDependency,
    service: W2ServiceDependency,
) -> ScheduleMonthResponse:
    return service.finalize_schedule_month(schedule_month, payload, current_account)


@router.get(
    "/personal-todos",
    response_model=PersonalTodoListResponse,
    operation_id="listW2PersonalTodos",
    responses=ERROR_RESPONSES,
)
def list_personal_todos(
    current_account: CurrentAccountDependency,
    service: W2ServiceDependency,
) -> PersonalTodoListResponse:
    return service.list_personal_todos(current_account)


@router.post(
    "/personal-todos",
    response_model=PersonalTodoListResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createW2PersonalTodo",
    responses=ERROR_RESPONSES,
)
def create_personal_todo(
    payload: PersonalTodoCreateRequest,
    current_account: CsrfAccountDependency,
    service: W2ServiceDependency,
) -> PersonalTodoListResponse:
    return service.create_personal_todo(payload, current_account)


@router.patch(
    "/personal-todos/{todo_id}",
    response_model=PersonalTodoListResponse,
    operation_id="updateW2PersonalTodo",
    responses=ERROR_RESPONSES,
)
def update_personal_todo(
    todo_id: int,
    payload: PersonalTodoUpdateRequest,
    current_account: CsrfAccountDependency,
    service: W2ServiceDependency,
) -> PersonalTodoListResponse:
    return service.update_personal_todo(todo_id, payload, current_account)


@router.delete(
    "/personal-todos/{todo_id}",
    response_model=PersonalTodoListResponse,
    operation_id="deleteW2PersonalTodo",
    responses=ERROR_RESPONSES,
)
def delete_personal_todo(
    todo_id: int,
    payload: PersonalTodoDeleteRequest,
    current_account: CsrfAccountDependency,
    service: W2ServiceDependency,
) -> PersonalTodoListResponse:
    return service.delete_personal_todo(todo_id, payload, current_account)


@router.post(
    "/personal-todos/reorder",
    response_model=PersonalTodoListResponse,
    operation_id="reorderW2PersonalTodos",
    responses=ERROR_RESPONSES,
)
def reorder_personal_todos(
    payload: PersonalTodoReorderRequest,
    current_account: CsrfAccountDependency,
    service: W2ServiceDependency,
) -> PersonalTodoListResponse:
    return service.reorder_personal_todos(payload, current_account)


@router.get(
    "/official-work-cards",
    response_model=OfficialWorkCardListResponse,
    operation_id="listW2OfficialWorkCards",
    responses=ERROR_RESPONSES,
)
def list_official_work_cards(
    current_account: CurrentAccountDependency,
    service: W2ServiceDependency,
) -> OfficialWorkCardListResponse:
    return service.list_official_cards(current_account)


@router.post(
    "/official-work-cards/{card_id}/close",
    response_model=OfficialWorkCardListResponse,
    operation_id="closeW2OfficialWorkCard",
    responses=ERROR_RESPONSES,
)
def close_official_work_card(
    card_id: int,
    payload: OfficialWorkCardCloseRequest,
    current_account: CsrfAccountDependency,
    service: W2ServiceDependency,
) -> OfficialWorkCardListResponse:
    return service.close_official_card(card_id, payload, current_account)
