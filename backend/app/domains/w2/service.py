"""Transactional W2 core-ledger services."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime
from typing import Any, NoReturn
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.db.w2_models import (
    MonthlyProfessionalAssignment,
    W2OfficialWorkCard,
    W2PersonalTodo,
    W2Schedule,
    W2ScheduleMonthControl,
    W2ScheduleStaff,
    W2ServicePlanNotice,
)
from app.domains.recipient.service_plan_notice import deadline_date, default_end_date
from app.domains.w2.errors import domain_error
from app.domains.w2.policies import (
    OfficialCardSource,
    card_priority,
    clean_required_text,
    plan_notice_source,
    validate_official_source,
)
from app.domains.w2.repository import W2Repository
from app.domains.w2.schemas import (
    OfficialWorkCardCloseRequest,
    OfficialWorkCardDisplay,
    OfficialWorkCardEligibleAssignee,
    OfficialWorkCardEligibleAssigneeListResponse,
    OfficialWorkCardGroup,
    OfficialWorkCardItem,
    OfficialWorkCardKind,
    OfficialWorkCardListResponse,
    OfficialWorkCardReassignRequest,
    PersonalTodoCreateRequest,
    PersonalTodoDeleteRequest,
    PersonalTodoListResponse,
    PersonalTodoReorderRequest,
    PersonalTodoResponse,
    PersonalTodoUpdateRequest,
    ProfessionalAssignmentCreateRequest,
    ProfessionalAssignmentHistoryResponse,
    ProfessionalAssignmentReplaceRequest,
    ProfessionalAssignmentResponse,
    ScheduleAssignedStaffResponse,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleFinalizeRequest,
    ScheduleItemResponse,
    ScheduleMonthResponse,
    ScheduleReplaceRequest,
    ScheduleStaffInput,
    ServicePlanNoticeCreateRequest,
    ServicePlanNoticeHistoryResponse,
    ServicePlanNoticeReplaceRequest,
    ServicePlanNoticeResponse,
)

_SEOUL = ZoneInfo("Asia/Seoul")


def _now() -> datetime:
    return datetime.now(UTC)


def _today_seoul() -> date:
    return datetime.now(_SEOUL).date()


def _constraint_name(error: IntegrityError) -> str | None:
    original = getattr(error, "orig", None)
    diagnostics = getattr(original, "diag", None)
    value = getattr(diagnostics, "constraint_name", None)
    return str(value) if value else None


def _database_message(error: IntegrityError) -> str:
    original = getattr(error, "orig", None)
    diagnostics = getattr(original, "diag", None)
    value = getattr(diagnostics, "message_primary", None)
    return str(value or original or error)


class W2Service:
    def __init__(
        self,
        database_session: Session,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.database_session = database_session
        self.repository = W2Repository(database_session)
        self.request_id = request_id

    def _audit(
        self,
        *,
        actor_account_id: int | None,
        action_code: str,
        entity_type: str,
        entity_pk: int | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        system = actor_account_id is None
        self.repository.append_audit(
            actor_account_id=actor_account_id,
            actor_kind="SYSTEM" if system else "USER",
            action_code=action_code,
            entity_type=entity_type,
            entity_pk=entity_pk,
            before_json=before,
            after_json=after,
            request_id=self.request_id,
            occurred_at_utc=_now(),
            created_from="WORKER" if system else "API",
        )

    def _raise_integrity(
        self,
        error: IntegrityError,
        *,
        schedule_month: date | None = None,
        todo_owner_account_id: int | None = None,
        service_plan_recipient_id: int | None = None,
    ) -> NoReturn:
        constraint = _constraint_name(error)
        message = _database_message(error)
        self.database_session.rollback()
        if schedule_month is not None and (
            constraint
            in {
                "ex_w2_schedule_recipient_overlap",
                "uq_w2_schedule_exact",
                "uq_w2_schedule_staff_distinct",
            }
            or "SCHEDULE_" in message
        ):
            code = "SCHEDULE_OVERLAP"
            if "SCHEDULE_MONTH_FINALIZED" in message:
                code = "SCHEDULE_MONTH_FINALIZED"
            elif "SCHEDULE_STAFF_COUNT_INVALID" in message:
                code = "SCHEDULE_STAFF_COUNT_INVALID"
            elif "SCHEDULE_STAFF_FACT_INVALID" in message:
                code = "SCHEDULE_STAFF_FACT_INVALID"
            elif "SCHEDULE_OUTSIDE_EMPLOYMENT" in message:
                code = "SCHEDULE_OUTSIDE_EMPLOYMENT"
            elif "SCHEDULE_CARE_WORKER_POSITION_REQUIRED" in message:
                code = "SCHEDULE_CARE_WORKER_POSITION_REQUIRED"
            elif "SCHEDULE_OUTSIDE_QUALIFICATION" in message:
                code = "SCHEDULE_OUTSIDE_QUALIFICATION"
            raise domain_error(
                code,
                423
                if code == "SCHEDULE_MONTH_FINALIZED"
                else 409
                if code == "SCHEDULE_OVERLAP"
                else 422,
                details={"latest": self._schedule_snapshot(schedule_month).model_dump(mode="json")},
            ) from None
        if todo_owner_account_id is not None and constraint == (
            "uq_w2_personal_todo_owner_sort_order"
        ):
            raise domain_error(
                "TODO_LIST_REVISION_CONFLICT",
                409,
                details={
                    "latest": self._todo_snapshot(todo_owner_account_id).model_dump(mode="json")
                },
            ) from None
        if constraint == "ex_monthly_professional_assignment_current_period":
            raise domain_error("PROFESSIONAL_ASSIGNMENT_CONFLICT", 409) from None
        if "PROFESSIONAL_ASSIGNMENT_OUTSIDE_EMPLOYMENT" in message:
            raise domain_error("PROFESSIONAL_ASSIGNMENT_OUTSIDE_EMPLOYMENT", 422) from None
        if "PROFESSIONAL_ASSIGNMENT_POSITION_REQUIRED" in message:
            raise domain_error("PROFESSIONAL_ASSIGNMENT_POSITION_REQUIRED", 422) from None
        if constraint in {
            "uq_w2_official_work_card_occurrence_key",
            "uq_w2_official_work_card_open_renewal",
        }:
            raise domain_error("CARD_OCCURRENCE_CONFLICT", 409) from None
        if "W2_SERVICE_PLAN_OUTSIDE_CONTRACT" in message:
            raise domain_error(
                "SERVICE_PLAN_OUTSIDE_CONTRACT",
                422,
                details=(
                    {}
                    if service_plan_recipient_id is None
                    else {
                        "latest": self._service_plan_snapshot(service_plan_recipient_id).model_dump(
                            mode="json"
                        )
                    }
                ),
            ) from None
        if "W2_SERVICE_PLAN_OUTSIDE_CERTIFICATION" in message:
            raise domain_error(
                "SERVICE_PLAN_OUTSIDE_CERTIFICATION",
                422,
                details=(
                    {}
                    if service_plan_recipient_id is None
                    else {
                        "latest": self._service_plan_snapshot(service_plan_recipient_id).model_dump(
                            mode="json"
                        )
                    }
                ),
            ) from None
        if (
            constraint == "fk_w2_service_plan_notice_replacement_same_recipient"
            or "W2_SERVICE_PLAN_REPLACEMENT_CROSS_RECIPIENT" in message
        ):
            raise domain_error(
                "SERVICE_PLAN_REPLACEMENT_CROSS_RECIPIENT",
                422,
                details=(
                    {}
                    if service_plan_recipient_id is None
                    else {
                        "latest": self._service_plan_snapshot(service_plan_recipient_id).model_dump(
                            mode="json"
                        )
                    }
                ),
            ) from None
        raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _flush(
        self,
        *,
        schedule_month: date | None = None,
        todo_owner_account_id: int | None = None,
        service_plan_recipient_id: int | None = None,
    ) -> None:
        try:
            self.database_session.flush()
        except IntegrityError as exc:
            self._raise_integrity(
                exc,
                schedule_month=schedule_month,
                todo_owner_account_id=todo_owner_account_id,
                service_plan_recipient_id=service_plan_recipient_id,
            )
        except SQLAlchemyError:
            self.database_session.rollback()
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _commit(
        self,
        *,
        schedule_month: date | None = None,
        todo_owner_account_id: int | None = None,
        service_plan_recipient_id: int | None = None,
    ) -> None:
        try:
            self.database_session.commit()
        except IntegrityError as exc:
            self._raise_integrity(
                exc,
                schedule_month=schedule_month,
                todo_owner_account_id=todo_owner_account_id,
                service_plan_recipient_id=service_plan_recipient_id,
            )
        except SQLAlchemyError:
            self.database_session.rollback()
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    @staticmethod
    def _require_month_start(value: date) -> None:
        if value.day != 1:
            raise domain_error("VALIDATION_ERROR", 422, field="month")

    @staticmethod
    def _assignment_response(
        row: MonthlyProfessionalAssignment,
    ) -> ProfessionalAssignmentResponse:
        return ProfessionalAssignmentResponse(
            id=row.id,
            recipient_id=row.recipient_id,
            service_month=row.service_month,
            staff_id=row.staff_id,
            employment_id=row.employment_id,
            start_date=row.start_date,
            end_date=row.end_date,
            invalidated_at_utc=row.invalidated_at_utc,
            replacement_assignment_id=row.replacement_assignment_id,
            row_version=row.row_version,
        )

    def _schedule_item(self, row: W2Schedule) -> ScheduleItemResponse:
        return ScheduleItemResponse(
            id=row.id,
            schedule_month=row.schedule_month,
            recipient_id=row.recipient_id,
            service_type_id=row.service_type_id,
            assigned_staff=[
                ScheduleAssignedStaffResponse(
                    staff_id=assigned.staff_id,
                    employment_id=assigned.employment_id,
                )
                for assigned in self.repository.schedule_staff(row.id)
            ],
            starts_at_utc=row.starts_at_utc,
            ends_at_utc=row.ends_at_utc,
            row_version=row.row_version,
        )

    def _schedule_snapshot(
        self,
        schedule_month: date,
        *,
        recipient_id: int | None = None,
        staff_id: int | None = None,
    ) -> ScheduleMonthResponse:
        control = self.repository.schedule_month(schedule_month)
        rows = self.repository.schedules(
            schedule_month,
            recipient_id=recipient_id,
            staff_id=staff_id,
        )
        return ScheduleMonthResponse(
            schedule_month=schedule_month,
            finalized=control is not None and control.finalized_at_utc is not None,
            finalized_at_utc=None if control is None else control.finalized_at_utc,
            row_version=1 if control is None else control.row_version,
            items=[self._schedule_item(row) for row in rows],
        )

    @staticmethod
    def _todo_response(row: W2PersonalTodo) -> PersonalTodoResponse:
        return PersonalTodoResponse(
            id=row.id,
            title=row.title,
            completed=row.completed,
            sort_order=row.sort_order,
            row_version=row.row_version,
        )

    def _todo_snapshot(self, owner_account_id: int) -> PersonalTodoListResponse:
        todo_list = self.repository.todo_list(owner_account_id)
        return PersonalTodoListResponse(
            list_revision=1 if todo_list is None else todo_list.list_revision,
            items=[self._todo_response(row) for row in self.repository.todos(owner_account_id)],
        )

    @staticmethod
    def _card_json(row: W2OfficialWorkCard) -> dict[str, Any]:
        return {
            "id": row.id,
            "kind": row.kind,
            "work_title": row.work_title,
            "target_name": row.target_name,
            "detail": row.detail,
            "due_date": row.due_date.isoformat(),
            "occurrence_key": row.occurrence_key,
            "renewal_key": row.renewal_key,
            "assignee_staff_id": row.assignee_staff_id,
            "closed_at_utc": (None if row.closed_at_utc is None else row.closed_at_utc.isoformat()),
            "row_version": row.row_version,
        }

    def _card_item(self, row: W2OfficialWorkCard, as_of_date: date) -> OfficialWorkCardItem:
        return OfficialWorkCardItem(
            id=row.id,
            row_version=row.row_version,
            kind=OfficialWorkCardKind(row.kind),
            assignee_staff_id=row.assignee_staff_id,
            assignee_staff_name=self.repository.staff_display_name(row.assignee_staff_id),
            display=OfficialWorkCardDisplay(
                work_title=row.work_title,
                target_name=row.target_name,
                detail=row.detail,
                due_date=row.due_date,
                d_day=(row.due_date - as_of_date).days,
            ),
        )

    def _card_conflict_details(
        self,
        current_account: CurrentAccount,
        row: W2OfficialWorkCard,
    ) -> dict[str, Any]:
        return {
            "entity": "official_work_card",
            "current_row_version": row.row_version,
            "latest": self.list_official_cards(current_account).model_dump(mode="json"),
            "card": {
                **self._card_json(row),
                "assignee_staff_name": self.repository.staff_display_name(row.assignee_staff_id),
            },
        }

    def _assignee_snapshot(self, row: W2OfficialWorkCard) -> dict[str, Any]:
        return {
            "card_id": row.id,
            "kind": row.kind,
            "due_date": row.due_date.isoformat(),
            "occurrence_key": row.occurrence_key,
            "renewal_key": row.renewal_key,
            "recipient_id": row.recipient_id,
            "closed_at_utc": (None if row.closed_at_utc is None else row.closed_at_utc.isoformat()),
            "assignee_staff_id": row.assignee_staff_id,
            "assignee_staff_name": self.repository.staff_display_name(row.assignee_staff_id),
            "row_version": row.row_version,
        }

    def _resolve_automatic_assignee(self, recipient_id: int, as_of_date: date) -> int:
        if self.repository.recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        rows = self.repository.current_assignments_covering(
            recipient_id,
            as_of_date,
            for_update=True,
        )
        if len(rows) != 1:
            raise domain_error("CARD_ASSIGNEE_UNRESOLVED", 422)
        staff_id = rows[0].staff_id
        if self.repository.staff_is_admin_account(staff_id):
            raise domain_error("ADMIN_CARD_ASSIGNEE_FORBIDDEN", 422)
        return staff_id

    def _inherited_manual_assignee(
        self,
        renewal_history: list[W2OfficialWorkCard],
    ) -> int | None:
        audit = self.repository.latest_card_reassignment_audit([row.id for row in renewal_history])
        if audit is None or not isinstance(audit.after_json, dict):
            return None
        value = audit.after_json.get("assignee_staff_id")
        if not isinstance(value, int) or value <= 0:
            return None
        return value

    def _require_eligible_reassignment_assignee(
        self,
        staff_id: int,
        as_of_date: date,
    ) -> None:
        if self.repository.staff(staff_id) is None:
            raise domain_error("STAFF_NOT_FOUND", 404)
        if self.repository.staff_is_admin_account(staff_id):
            raise domain_error("ADMIN_CARD_ASSIGNEE_FORBIDDEN", 422)
        if not self.repository.staff_currently_employed(staff_id, as_of_date):
            raise domain_error("CARD_ASSIGNEE_INELIGIBLE", 422, field="assignee_staff_id")
        if not self.repository.staff_has_professional_position(staff_id, as_of_date):
            raise domain_error("CARD_ASSIGNEE_INELIGIBLE", 422, field="assignee_staff_id")

    def _resolve_new_card_assignee(
        self,
        normalized: OfficialCardSource,
        renewal_history: list[W2OfficialWorkCard],
    ) -> int:
        inherited = self._inherited_manual_assignee(renewal_history)
        if inherited is not None:
            # A successful ADMIN reassignment is a recorded fact of this
            # renewal lineage. Do not later re-check employment, position,
            # account linkage, or even staff lookup while replacing a lower
            # priority card: doing so can silently discard a valid manual
            # override after the original request already passed eligibility.
            return inherited
        if normalized.recipient_id is None:
            raise domain_error("CARD_ASSIGNEE_UNRESOLVED", 422)
        return self._resolve_automatic_assignee(normalized.recipient_id, normalized.due_date)

    def _professional_staff_for_account(self, current_account: CurrentAccount) -> int:
        if current_account.role_code == "ADMIN":
            raise domain_error("PROFESSIONAL_ROLE_REQUIRED", 403)
        staff_id = self.repository.account_staff_id(current_account.id)
        if staff_id is None or not self.repository.staff_has_professional_position(
            staff_id,
            _today_seoul(),
        ):
            raise domain_error("PROFESSIONAL_ROLE_REQUIRED", 403)
        return staff_id

    def _require_month_version(
        self,
        control: W2ScheduleMonthControl,
        expected: int,
    ) -> None:
        if control.finalized_at_utc is not None:
            raise domain_error(
                "SCHEDULE_MONTH_FINALIZED",
                423,
                details={
                    "latest": self._schedule_snapshot(control.schedule_month).model_dump(
                        mode="json"
                    )
                },
            )
        if control.row_version != expected:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={
                    "entity": "schedule_month",
                    "current_row_version": control.row_version,
                    "latest": self._schedule_snapshot(control.schedule_month).model_dump(
                        mode="json"
                    ),
                },
            )

    def list_professional_assignments(
        self,
        recipient_id: int,
        service_month: date,
    ) -> ProfessionalAssignmentHistoryResponse:
        self._require_month_start(service_month)
        if self.repository.recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        return ProfessionalAssignmentHistoryResponse(
            items=[
                self._assignment_response(row)
                for row in self.repository.assignment_history(recipient_id, service_month)
            ]
        )

    @staticmethod
    def _validate_assignment_period(
        service_month: date,
        start_date: date,
        end_date: date,
    ) -> None:
        month_end = date(
            service_month.year,
            service_month.month,
            monthrange(service_month.year, service_month.month)[1],
        )
        if start_date > end_date or start_date < service_month or end_date > month_end:
            raise domain_error(
                "PROFESSIONAL_ASSIGNMENT_PERIOD_INVALID",
                422,
                field="start_date",
            )

    def _validate_assignment_fact(
        self,
        *,
        staff_id: int,
        employment_id: int,
        start_date: date,
        end_date: date,
    ) -> None:
        if self.repository.staff(staff_id) is None:
            raise domain_error("STAFF_NOT_FOUND", 404)
        if not self.repository.employment_covers(
            staff_id,
            employment_id,
            start_date,
            end_date,
        ):
            raise domain_error(
                "PROFESSIONAL_ASSIGNMENT_OUTSIDE_EMPLOYMENT",
                422,
                field="employment_id",
            )
        if not self.repository.professional_position_covers(
            staff_id,
            employment_id,
            start_date,
            end_date,
        ):
            raise domain_error(
                "PROFESSIONAL_ASSIGNMENT_POSITION_REQUIRED",
                422,
                field="staff_id",
            )

    def create_professional_assignment(
        self,
        recipient_id: int,
        service_month: date,
        payload: ProfessionalAssignmentCreateRequest,
        current_account: CurrentAccount,
    ) -> ProfessionalAssignmentResponse:
        self._require_month_start(service_month)
        self._validate_assignment_period(
            service_month,
            payload.start_date,
            payload.end_date,
        )
        if self.repository.recipient(recipient_id, for_update=True) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        self.repository.current_assignments_for_update(recipient_id, service_month)
        self._validate_assignment_fact(
            staff_id=payload.staff_id,
            employment_id=payload.employment_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        row = MonthlyProfessionalAssignment(
            recipient_id=recipient_id,
            service_month=service_month,
            staff_id=payload.staff_id,
            employment_id=payload.employment_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=current_account.id,
            updated_by_account_id=current_account.id,
        )
        self.database_session.add(row)
        self._flush()
        response = self._assignment_response(row)
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_MONTHLY_PROFESSIONAL_ASSIGNMENT_CREATED",
            entity_type="monthly_professional_assignment",
            entity_pk=row.id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    def replace_professional_assignment(
        self,
        recipient_id: int,
        service_month: date,
        assignment_id: int,
        payload: ProfessionalAssignmentReplaceRequest,
        current_account: CurrentAccount,
    ) -> ProfessionalAssignmentResponse:
        self._require_month_start(service_month)
        self._validate_assignment_period(
            service_month,
            payload.start_date,
            payload.end_date,
        )
        if self.repository.recipient(recipient_id, for_update=True) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        current_rows = self.repository.current_assignments_for_update(
            recipient_id,
            service_month,
        )
        current = next((row for row in current_rows if row.id == assignment_id), None)
        if current is None:
            history = self.repository.assignment_history(recipient_id, service_month)
            if any(row.id == assignment_id for row in history):
                raise domain_error(
                    "PROFESSIONAL_ASSIGNMENT_CONFLICT",
                    409,
                    details={
                        "latest": [
                            self._assignment_response(row).model_dump(mode="json")
                            for row in history
                        ]
                    },
                )
            raise domain_error("PROFESSIONAL_ASSIGNMENT_NOT_FOUND", 404)
        if current.row_version != payload.expected_row_version:
            raise domain_error(
                "PROFESSIONAL_ASSIGNMENT_CONFLICT",
                409,
                details={"current": self._assignment_response(current).model_dump(mode="json")},
            )
        self._validate_assignment_fact(
            staff_id=payload.staff_id,
            employment_id=payload.employment_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        if (
            current.staff_id == payload.staff_id
            and current.employment_id == payload.employment_id
            and current.start_date == payload.start_date
            and current.end_date == payload.end_date
        ):
            self._commit()
            return self._assignment_response(current)

        now = _now()
        before = self._assignment_response(current).model_dump(mode="json")
        current.invalidated_at_utc = now
        current.updated_by_account_id = current_account.id
        current.updated_at_utc = now
        current.row_version += 1
        self._flush()
        replacement = MonthlyProfessionalAssignment(
            recipient_id=recipient_id,
            service_month=service_month,
            staff_id=payload.staff_id,
            employment_id=payload.employment_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=current_account.id,
            updated_by_account_id=current_account.id,
        )
        self.database_session.add(replacement)
        self._flush()
        current.replacement_assignment_id = replacement.id
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_MONTHLY_PROFESSIONAL_ASSIGNMENT_REPLACED",
            entity_type="monthly_professional_assignment",
            entity_pk=current.id,
            before=before,
            after=self._assignment_response(current).model_dump(mode="json"),
        )
        response = self._assignment_response(replacement)
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_MONTHLY_PROFESSIONAL_ASSIGNMENT_CREATED",
            entity_type="monthly_professional_assignment",
            entity_pk=replacement.id,
            before=None,
            after=response.model_dump(mode="json"),
        )
        self._commit()
        return response

    @staticmethod
    def _service_plan_response(row: W2ServicePlanNotice) -> ServicePlanNoticeResponse:
        return ServicePlanNoticeResponse(
            id=row.id,
            recipient_id=row.recipient_id,
            recipient_contract_id=row.recipient_contract_id,
            notification_date=row.notification_date,
            applied_start_date=row.applied_start_date,
            applied_end_date=row.applied_end_date,
            invalidated_at_utc=row.invalidated_at_utc,
            replacement_service_plan_notice_id=row.replacement_service_plan_notice_id,
            row_version=row.row_version,
        )

    @staticmethod
    def _service_plan_json(row: W2ServicePlanNotice) -> dict[str, Any]:
        return {
            "id": row.id,
            "recipient_id": row.recipient_id,
            "recipient_contract_id": row.recipient_contract_id,
            "notification_date": row.notification_date.isoformat(),
            "applied_start_date": row.applied_start_date.isoformat(),
            "applied_end_date": row.applied_end_date.isoformat(),
            "invalidated_at_utc": (
                None if row.invalidated_at_utc is None else row.invalidated_at_utc.isoformat()
            ),
            "replacement_service_plan_notice_id": (row.replacement_service_plan_notice_id),
            "row_version": row.row_version,
        }

    def _service_plan_snapshot(
        self,
        recipient_id: int,
    ) -> ServicePlanNoticeHistoryResponse:
        return ServicePlanNoticeHistoryResponse(
            items=[
                self._service_plan_response(row)
                for row in self.repository.service_plan_notices(recipient_id)
            ]
        )

    def _prepare_service_plan_period(
        self,
        recipient_id: int,
        payload: ServicePlanNoticeCreateRequest,
    ) -> tuple[Any, date, date]:
        contract = self.repository.recipient_contract(
            payload.recipient_contract_id,
            for_update=True,
        )
        if contract is None:
            raise domain_error("SERVICE_PLAN_CONTRACT_NOT_FOUND", 404)
        if contract.recipient_id != recipient_id:
            raise domain_error("SERVICE_PLAN_CONTRACT_MISMATCH", 422)
        if (
            contract.invalidated_at_utc is not None
            or payload.applied_start_date < contract.start_date
            or (contract.end_date is not None and payload.applied_start_date > contract.end_date)
        ):
            raise domain_error("SERVICE_PLAN_OUTSIDE_CONTRACT", 422)

        certifications = self.repository.recipient_certifications(
            recipient_id,
            for_update=True,
        )
        certification = next(
            (
                item
                for item in certifications
                if item.start_date <= payload.applied_start_date <= item.end_date
            ),
            None,
        )
        if certification is None:
            raise domain_error("SERVICE_PLAN_OUTSIDE_CERTIFICATION", 422)

        if payload.applied_end_date is None:
            caps = [
                default_end_date(payload.notification_date),
                certification.end_date,
            ]
            if contract.end_date is not None:
                caps.append(contract.end_date)
            applied_end_date = min(caps)
        else:
            applied_end_date = payload.applied_end_date

        if applied_end_date < payload.applied_start_date or (
            contract.end_date is not None and applied_end_date > contract.end_date
        ):
            raise domain_error("SERVICE_PLAN_OUTSIDE_CONTRACT", 422)
        if applied_end_date > certification.end_date:
            raise domain_error("SERVICE_PLAN_OUTSIDE_CERTIFICATION", 422)
        return contract, applied_end_date, certification.end_date

    def list_service_plan_notices(
        self,
        recipient_id: int,
    ) -> ServicePlanNoticeHistoryResponse:
        if self.repository.recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        return self._service_plan_snapshot(recipient_id)

    def create_service_plan_notice(
        self,
        recipient_id: int,
        payload: ServicePlanNoticeCreateRequest,
        current_account: CurrentAccount,
    ) -> ServicePlanNoticeResponse:
        if self.repository.recipient(recipient_id, for_update=True) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        contract, applied_end_date, _ = self._prepare_service_plan_period(
            recipient_id,
            payload,
        )
        row = W2ServicePlanNotice(
            recipient_id=recipient_id,
            recipient_contract_id=contract.id,
            notification_date=payload.notification_date,
            applied_start_date=payload.applied_start_date,
            applied_end_date=applied_end_date,
            created_by_account_id=current_account.id,
            updated_by_account_id=current_account.id,
        )
        self.database_session.add(row)
        self._flush(service_plan_recipient_id=recipient_id)
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_SERVICE_PLAN_NOTICE_CREATED",
            entity_type="w2_service_plan_notice",
            entity_pk=row.id,
            before=None,
            after=self._service_plan_json(row),
        )
        self._commit(service_plan_recipient_id=recipient_id)
        return self._service_plan_response(row)

    def replace_service_plan_notice(
        self,
        recipient_id: int,
        notice_id: int,
        payload: ServicePlanNoticeReplaceRequest,
        current_account: CurrentAccount,
    ) -> ServicePlanNoticeResponse:
        self.repository.advisory_lock(f"w2-service-plan-notice:{notice_id}")
        current = self.repository.service_plan_notice_for_update(notice_id)
        if current is None:
            raise domain_error("SERVICE_PLAN_NOTICE_NOT_FOUND", 404)
        if current.recipient_id != recipient_id:
            raise domain_error("SERVICE_PLAN_NOTICE_NOT_FOUND", 404)
        if current.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={
                    "entity": "w2_service_plan_notice",
                    "current_row_version": current.row_version,
                    "latest": self._service_plan_snapshot(recipient_id).model_dump(mode="json"),
                },
            )
        if current.invalidated_at_utc is not None:
            raise domain_error(
                "SERVICE_PLAN_NOTICE_REPLACED",
                409,
                details={
                    "latest": self._service_plan_snapshot(recipient_id).model_dump(mode="json")
                },
            )

        contract, applied_end_date, _ = self._prepare_service_plan_period(
            recipient_id,
            payload,
        )
        before = self._service_plan_json(current)
        now = _now()
        replacement = W2ServicePlanNotice(
            recipient_id=recipient_id,
            recipient_contract_id=contract.id,
            notification_date=payload.notification_date,
            applied_start_date=payload.applied_start_date,
            applied_end_date=applied_end_date,
            created_by_account_id=current_account.id,
            updated_by_account_id=current_account.id,
        )
        self.database_session.add(replacement)
        self._flush(service_plan_recipient_id=recipient_id)
        current.invalidated_at_utc = now
        current.replacement_service_plan_notice_id = replacement.id
        current.updated_by_account_id = current_account.id
        current.updated_at_utc = now
        current.row_version += 1
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_SERVICE_PLAN_NOTICE_REPLACED",
            entity_type="w2_service_plan_notice",
            entity_pk=replacement.id,
            before=before,
            after=self._service_plan_json(replacement),
        )
        self._commit(service_plan_recipient_id=recipient_id)
        return self._service_plan_response(replacement)

    def record_service_plan_notice_card_source(
        self,
        notice_id: int,
        *,
        as_of_date: date,
        actor_account_id: int | None = None,
    ) -> W2OfficialWorkCard | None:
        """Bridge one due plan notice into the sealed internal card sink.

        Assignee is resolved from the monthly professional assignment covering
        the card due date.  This method is not exposed by the HTTP router.
        """
        notice = self.repository.service_plan_notice_for_update(notice_id)
        if notice is None or notice.invalidated_at_utc is not None:
            return None
        contract = self.repository.recipient_contract(notice.recipient_contract_id)
        if contract is None or contract.invalidated_at_utc is not None:
            return None
        certification = next(
            (
                item
                for item in self.repository.recipient_certifications(notice.recipient_id)
                if item.start_date <= notice.applied_start_date
                and item.end_date >= notice.applied_end_date
            ),
            None,
        )
        if certification is None:
            return None
        writing_deadline = deadline_date(
            notice.notification_date,
            contract_end_date=contract.end_date,
            certification_end_date=certification.end_date,
        )
        recipient = self.repository.recipient(notice.recipient_id)
        source = plan_notice_source(
            occurrence_key=f"plan-notice:{notice.id}:{writing_deadline.isoformat()}",
            renewal_key=(f"recipient:{notice.recipient_id}:renewal:{writing_deadline.isoformat()}"),
            writing_deadline=writing_deadline,
            target_name=None if recipient is None else recipient.name,
            detail="급여계획서 갱신 통보",
            recipient_id=notice.recipient_id,
        )
        if source.due_date > as_of_date:
            self.database_session.rollback()
            return None
        return self.record_official_source(
            source,
            actor_account_id=actor_account_id,
        )

    def list_schedules(
        self,
        schedule_month: date,
        *,
        recipient_id: int | None = None,
        staff_id: int | None = None,
    ) -> ScheduleMonthResponse:
        self._require_month_start(schedule_month)
        return self._schedule_snapshot(
            schedule_month,
            recipient_id=recipient_id,
            staff_id=staff_id,
        )

    @staticmethod
    def _validate_schedule_month(
        schedule_month: date,
        starts_at_utc: datetime,
        ends_at_utc: datetime,
    ) -> None:
        start_local = starts_at_utc.astimezone(_SEOUL)
        end_local = ends_at_utc.astimezone(_SEOUL)
        next_month = (
            date(schedule_month.year + 1, 1, 1)
            if schedule_month.month == 12
            else date(schedule_month.year, schedule_month.month + 1, 1)
        )
        if start_local.date() < schedule_month or end_local.date() > next_month:
            raise domain_error("VALIDATION_ERROR", 422, field="schedule_month")
        if start_local.date() >= next_month or end_local <= start_local:
            raise domain_error("VALIDATION_ERROR", 422, field="schedule_month")
        if end_local.date() == next_month and end_local.time() != datetime.min.time():
            raise domain_error("VALIDATION_ERROR", 422, field="schedule_month")

    def _require_schedule_references(
        self,
        recipient_id: int,
        service_type_id: int,
    ) -> str:
        if self.repository.recipient(recipient_id) is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        service_type = self.repository.service_type(service_type_id)
        if service_type is None:
            raise domain_error("SERVICE_TYPE_NOT_FOUND", 404)
        return service_type.code

    def _validate_schedule_staff(
        self,
        service_type_code: str,
        assigned_staff: list[ScheduleStaffInput],
    ) -> None:
        expected_count = 2 if service_type_code == "HOME_BATH" else 1
        if len(assigned_staff) != expected_count:
            raise domain_error(
                "SCHEDULE_STAFF_COUNT_INVALID",
                422,
                field="assigned_staff",
            )
        for assigned in assigned_staff:
            if self.repository.staff(assigned.staff_id) is None:
                raise domain_error("STAFF_NOT_FOUND", 404)
            if (
                self.repository.employment_fact(
                    assigned.staff_id,
                    assigned.employment_id,
                )
                is None
            ):
                raise domain_error(
                    "SCHEDULE_STAFF_FACT_INVALID",
                    422,
                    field="assigned_staff",
                )

    def _add_schedule_staff(
        self,
        *,
        schedule_id: int,
        assigned_staff: list[ScheduleStaffInput],
        actor_account_id: int,
    ) -> None:
        self.database_session.add_all(
            [
                W2ScheduleStaff(
                    schedule_id=schedule_id,
                    staff_id=assigned.staff_id,
                    employment_id=assigned.employment_id,
                    created_by_account_id=actor_account_id,
                    updated_by_account_id=actor_account_id,
                )
                for assigned in assigned_staff
            ]
        )

    def create_schedule(
        self,
        payload: ScheduleCreateRequest,
        current_account: CurrentAccount,
    ) -> ScheduleMonthResponse:
        self._validate_schedule_month(
            payload.schedule_month,
            payload.starts_at_utc,
            payload.ends_at_utc,
        )
        control = self.repository.lock_or_create_schedule_month(
            payload.schedule_month,
            current_account.id,
        )
        self._require_month_version(control, payload.expected_month_row_version)
        service_type_code = self._require_schedule_references(
            payload.recipient_id,
            payload.service_type_id,
        )
        self._validate_schedule_staff(service_type_code, payload.assigned_staff)
        row = W2Schedule(
            schedule_month=payload.schedule_month,
            recipient_id=payload.recipient_id,
            service_type_id=payload.service_type_id,
            starts_at_utc=payload.starts_at_utc,
            ends_at_utc=payload.ends_at_utc,
            created_by_account_id=current_account.id,
            updated_by_account_id=current_account.id,
        )
        self.database_session.add(row)
        self._flush(schedule_month=payload.schedule_month)
        self._add_schedule_staff(
            schedule_id=row.id,
            assigned_staff=payload.assigned_staff,
            actor_account_id=current_account.id,
        )
        self._flush(schedule_month=payload.schedule_month)
        control.updated_by_account_id = current_account.id
        control.updated_at_utc = _now()
        control.row_version += 1
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_SCHEDULE_CREATED",
            entity_type="w2_schedule",
            entity_pk=row.id,
            before=None,
            after=self._schedule_item(row).model_dump(mode="json"),
        )
        self._commit(schedule_month=payload.schedule_month)
        return self._schedule_snapshot(payload.schedule_month)

    def replace_schedule(
        self,
        schedule_id: int,
        payload: ScheduleReplaceRequest,
        current_account: CurrentAccount,
    ) -> ScheduleMonthResponse:
        schedule_month = self.repository.schedule_month_for_id(schedule_id)
        if schedule_month is None:
            raise domain_error("SCHEDULE_NOT_FOUND", 404)
        self._validate_schedule_month(
            schedule_month,
            payload.starts_at_utc,
            payload.ends_at_utc,
        )
        control = self.repository.lock_or_create_schedule_month(
            schedule_month,
            current_account.id,
        )
        self._require_month_version(control, payload.expected_month_row_version)
        row = self.repository.schedule_for_update(schedule_id)
        if row is None or row.schedule_month != schedule_month:
            raise domain_error("SCHEDULE_NOT_FOUND", 404)
        if row.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={
                    "entity": "schedule",
                    "current_row_version": row.row_version,
                    "latest": self._schedule_snapshot(schedule_month).model_dump(mode="json"),
                },
            )
        service_type_code = self._require_schedule_references(
            payload.recipient_id,
            payload.service_type_id,
        )
        self._validate_schedule_staff(service_type_code, payload.assigned_staff)
        before = self._schedule_item(row).model_dump(mode="json")
        existing_staff = self.repository.schedule_staff(row.id, for_update=True)
        row.recipient_id = payload.recipient_id
        row.service_type_id = payload.service_type_id
        row.starts_at_utc = payload.starts_at_utc
        row.ends_at_utc = payload.ends_at_utc
        row.updated_by_account_id = current_account.id
        row.updated_at_utc = _now()
        row.row_version += 1
        control.updated_by_account_id = current_account.id
        control.updated_at_utc = _now()
        control.row_version += 1
        for assigned in existing_staff:
            self.database_session.delete(assigned)
        self._flush(schedule_month=schedule_month)
        self._add_schedule_staff(
            schedule_id=row.id,
            assigned_staff=payload.assigned_staff,
            actor_account_id=current_account.id,
        )
        self._flush(schedule_month=schedule_month)
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_SCHEDULE_UPDATED",
            entity_type="w2_schedule",
            entity_pk=row.id,
            before=before,
            after=self._schedule_item(row).model_dump(mode="json"),
        )
        self._commit(schedule_month=schedule_month)
        return self._schedule_snapshot(schedule_month)

    def delete_schedule(
        self,
        schedule_id: int,
        payload: ScheduleDeleteRequest,
        current_account: CurrentAccount,
    ) -> ScheduleMonthResponse:
        schedule_month = self.repository.schedule_month_for_id(schedule_id)
        if schedule_month is None:
            raise domain_error("SCHEDULE_NOT_FOUND", 404)
        control = self.repository.lock_or_create_schedule_month(
            schedule_month,
            current_account.id,
        )
        self._require_month_version(control, payload.expected_month_row_version)
        row = self.repository.schedule_for_update(schedule_id)
        if row is None:
            raise domain_error("SCHEDULE_NOT_FOUND", 404)
        if row.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={
                    "entity": "schedule",
                    "current_row_version": row.row_version,
                    "latest": self._schedule_snapshot(schedule_month).model_dump(mode="json"),
                },
            )
        before = self._schedule_item(row).model_dump(mode="json")
        self.repository.schedule_staff(row.id, for_update=True)
        self.database_session.delete(row)
        control.updated_by_account_id = current_account.id
        control.updated_at_utc = _now()
        control.row_version += 1
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_SCHEDULE_DELETED",
            entity_type="w2_schedule",
            entity_pk=row.id,
            before=before,
            after=None,
        )
        self._commit(schedule_month=schedule_month)
        return self._schedule_snapshot(schedule_month)

    def finalize_schedule_month(
        self,
        schedule_month: date,
        payload: ScheduleFinalizeRequest,
        current_account: CurrentAccount,
    ) -> ScheduleMonthResponse:
        self._require_month_start(schedule_month)
        control = self.repository.lock_or_create_schedule_month(
            schedule_month,
            current_account.id,
        )
        self._require_month_version(control, payload.expected_month_row_version)
        rows = self.repository.schedules(schedule_month, for_update=True)
        errors = self.repository.schedule_coverage_errors(rows)
        if errors:
            code = str(errors[0]["code"])
            raise domain_error(
                code,
                422,
                details={
                    "invalid_schedules": errors,
                    "latest": self._schedule_snapshot(schedule_month).model_dump(mode="json"),
                },
            )
        before = self._schedule_snapshot(schedule_month).model_dump(mode="json")
        control.finalized_at_utc = _now()
        control.finalized_by_account_id = current_account.id
        control.updated_by_account_id = current_account.id
        control.updated_at_utc = control.finalized_at_utc
        control.row_version += 1
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_SCHEDULE_MONTH_FINALIZED",
            entity_type="w2_schedule_month_control",
            entity_pk=None,
            before=before,
            after={
                "schedule_month": schedule_month.isoformat(),
                "row_version": control.row_version,
                "finalized_at_utc": control.finalized_at_utc.isoformat(),
            },
        )
        self._commit(schedule_month=schedule_month)
        return self._schedule_snapshot(schedule_month)

    def list_personal_todos(self, current_account: CurrentAccount) -> PersonalTodoListResponse:
        self._professional_staff_for_account(current_account)
        return self._todo_snapshot(current_account.id)

    def _lock_todo_list(
        self,
        current_account: CurrentAccount,
        expected_revision: int,
    ) -> Any:
        self._professional_staff_for_account(current_account)
        todo_list = self.repository.lock_or_create_todo_list(current_account.id)
        if todo_list.list_revision != expected_revision:
            raise domain_error(
                "TODO_LIST_REVISION_CONFLICT",
                409,
                details={
                    "current_list_revision": todo_list.list_revision,
                    "latest": self._todo_snapshot(current_account.id).model_dump(mode="json"),
                },
            )
        return todo_list

    def create_personal_todo(
        self,
        payload: PersonalTodoCreateRequest,
        current_account: CurrentAccount,
    ) -> PersonalTodoListResponse:
        todo_list = self._lock_todo_list(current_account, payload.expected_list_revision)
        row = W2PersonalTodo(
            owner_account_id=current_account.id,
            title=clean_required_text(payload.title, field="title"),
            completed=False,
            sort_order=self.repository.next_todo_sort_order(current_account.id),
        )
        self.database_session.add(row)
        self._flush(todo_owner_account_id=current_account.id)
        todo_list.list_revision += 1
        todo_list.updated_at_utc = _now()
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_PERSONAL_TODO_CREATED",
            entity_type="w2_personal_todo",
            entity_pk=row.id,
            before=None,
            after=self._todo_response(row).model_dump(mode="json"),
        )
        self._commit(todo_owner_account_id=current_account.id)
        return self._todo_snapshot(current_account.id)

    def update_personal_todo(
        self,
        todo_id: int,
        payload: PersonalTodoUpdateRequest,
        current_account: CurrentAccount,
    ) -> PersonalTodoListResponse:
        todo_list = self._lock_todo_list(current_account, payload.expected_list_revision)
        row = self.repository.todo_for_update(current_account.id, todo_id)
        if row is None:
            raise domain_error("TODO_NOT_FOUND", 404)
        if row.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={
                    "entity": "personal_todo",
                    "current_row_version": row.row_version,
                    "latest": self._todo_snapshot(current_account.id).model_dump(mode="json"),
                },
            )
        before = self._todo_response(row).model_dump(mode="json")
        if payload.title is not None:
            row.title = clean_required_text(payload.title, field="title")
        if payload.completed is not None:
            row.completed = payload.completed
        row.row_version += 1
        row.updated_at_utc = _now()
        todo_list.list_revision += 1
        todo_list.updated_at_utc = row.updated_at_utc
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_PERSONAL_TODO_UPDATED",
            entity_type="w2_personal_todo",
            entity_pk=row.id,
            before=before,
            after=self._todo_response(row).model_dump(mode="json"),
        )
        self._commit(todo_owner_account_id=current_account.id)
        return self._todo_snapshot(current_account.id)

    def delete_personal_todo(
        self,
        todo_id: int,
        payload: PersonalTodoDeleteRequest,
        current_account: CurrentAccount,
    ) -> PersonalTodoListResponse:
        todo_list = self._lock_todo_list(current_account, payload.expected_list_revision)
        row = self.repository.todo_for_update(current_account.id, todo_id)
        if row is None:
            raise domain_error("TODO_NOT_FOUND", 404)
        if row.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={"latest": self._todo_snapshot(current_account.id).model_dump(mode="json")},
            )
        before = self._todo_response(row).model_dump(mode="json")
        self.database_session.delete(row)
        todo_list.list_revision += 1
        todo_list.updated_at_utc = _now()
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_PERSONAL_TODO_DELETED",
            entity_type="w2_personal_todo",
            entity_pk=row.id,
            before=before,
            after=None,
        )
        self._commit(todo_owner_account_id=current_account.id)
        return self._todo_snapshot(current_account.id)

    def reorder_personal_todos(
        self,
        payload: PersonalTodoReorderRequest,
        current_account: CurrentAccount,
    ) -> PersonalTodoListResponse:
        todo_list = self._lock_todo_list(current_account, payload.expected_list_revision)
        rows = self.repository.todos(current_account.id, for_update=True)
        by_id = {row.id: row for row in rows}
        if set(payload.ordered_ids) != set(by_id):
            raise domain_error(
                "TODO_REORDER_SET_MISMATCH",
                422,
                details={"current_ids": sorted(by_id)},
            )
        now = _now()
        for sort_order, todo_id in enumerate(payload.ordered_ids):
            row = by_id[todo_id]
            if row.sort_order != sort_order:
                row.sort_order = sort_order
                row.row_version += 1
                row.updated_at_utc = now
        todo_list.list_revision += 1
        todo_list.updated_at_utc = now
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_PERSONAL_TODO_REORDERED",
            entity_type="w2_personal_todo_list",
            entity_pk=current_account.id,
            before=None,
            after={"ordered_ids": payload.ordered_ids, "list_revision": todo_list.list_revision},
        )
        self._commit(todo_owner_account_id=current_account.id)
        return self._todo_snapshot(current_account.id)

    def list_official_cards(
        self,
        current_account: CurrentAccount,
    ) -> OfficialWorkCardListResponse:
        as_of = _today_seoul()
        assignee_staff_id = None
        if current_account.role_code != "ADMIN":
            assignee_staff_id = self._professional_staff_for_account(current_account)
        rows = self.repository.open_cards(assignee_staff_id=assignee_staff_id)
        grouped: dict[int, OfficialWorkCardGroup] = {}
        for card, staff in rows:
            group = grouped.get(staff.id)
            if group is None:
                group = OfficialWorkCardGroup(
                    staff_id=staff.id,
                    staff_name=staff.display_name or staff.name,
                    items=[],
                )
                grouped[staff.id] = group
            group.items.append(self._card_item(card, as_of))
        return OfficialWorkCardListResponse(as_of_date=as_of, groups=list(grouped.values()))

    def close_official_card(
        self,
        card_id: int,
        payload: OfficialWorkCardCloseRequest,
        current_account: CurrentAccount,
    ) -> OfficialWorkCardListResponse:
        if current_account.role_code == "ADMIN":
            raise domain_error("ADMIN_CARD_MUTATION_FORBIDDEN", 403)
        staff_id = self._professional_staff_for_account(current_account)
        row = self.repository.card_for_update(card_id)
        if row is None:
            raise domain_error("CARD_NOT_FOUND", 404)
        if row.assignee_staff_id != staff_id:
            raise domain_error("CARD_ACCESS_FORBIDDEN", 403)
        if row.closed_at_utc is not None:
            raise domain_error(
                "CARD_ALREADY_CLOSED",
                409,
                details=self._card_conflict_details(current_account, row),
            )
        if row.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details=self._card_conflict_details(current_account, row),
            )
        before = self._card_json(row)
        row.closed_at_utc = _now()
        row.closed_by_account_id = current_account.id
        row.updated_by_account_id = current_account.id
        row.updated_at_utc = row.closed_at_utc
        row.row_version += 1
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_OFFICIAL_WORK_CARD_CLOSED",
            entity_type="w2_official_work_card",
            entity_pk=row.id,
            before=before,
            after=self._card_json(row),
        )
        self._commit()
        return self.list_official_cards(current_account)

    def list_eligible_assignees(
        self,
        current_account: CurrentAccount,
    ) -> OfficialWorkCardEligibleAssigneeListResponse:
        if current_account.role_code != "ADMIN":
            raise domain_error("CARD_REASSIGN_FORBIDDEN", 403)
        as_of = _today_seoul()
        return OfficialWorkCardEligibleAssigneeListResponse(
            as_of_date=as_of,
            items=[
                OfficialWorkCardEligibleAssignee(
                    staff_id=staff.id,
                    staff_name=staff.display_name or staff.name or "미입력",
                )
                for staff in self.repository.eligible_card_assignees(as_of)
            ],
        )

    def reassign_official_card(
        self,
        card_id: int,
        payload: OfficialWorkCardReassignRequest,
        current_account: CurrentAccount,
    ) -> OfficialWorkCardListResponse:
        if current_account.role_code != "ADMIN":
            raise domain_error("CARD_REASSIGN_FORBIDDEN", 403)
        as_of = _today_seoul()
        row = self.repository.card_for_update(card_id)
        if row is None:
            raise domain_error("CARD_NOT_FOUND", 404)
        if row.closed_at_utc is not None:
            raise domain_error(
                "CARD_ALREADY_CLOSED",
                409,
                details=self._card_conflict_details(current_account, row),
            )
        if row.row_version != payload.expected_row_version:
            raise domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details=self._card_conflict_details(current_account, row),
            )
        if row.assignee_staff_id == payload.assignee_staff_id:
            raise domain_error(
                "CARD_REASSIGN_SAME_ASSIGNEE",
                422,
                field="assignee_staff_id",
            )
        self._require_eligible_reassignment_assignee(payload.assignee_staff_id, as_of)

        before = self._assignee_snapshot(row)
        row.assignee_staff_id = payload.assignee_staff_id
        row.row_version += 1
        self._audit(
            actor_account_id=current_account.id,
            action_code="W2_OFFICIAL_WORK_CARD_REASSIGNED",
            entity_type="w2_official_work_card",
            entity_pk=row.id,
            before=before,
            after=self._assignee_snapshot(row),
        )
        self._commit()
        return self.list_official_cards(current_account)

    def record_official_source(
        self,
        source: OfficialCardSource,
        *,
        actor_account_id: int | None = None,
    ) -> W2OfficialWorkCard:
        """Idempotently accept a trusted internal source; never exposed by the router."""
        try:
            normalized = validate_official_source(source)
        except ValueError as exc:
            raise domain_error(
                "VALIDATION_ERROR",
                422,
                details={"source_error": str(exc)},
            ) from None
        if (
            normalized.recipient_id is not None
            and self.repository.recipient(normalized.recipient_id) is None
        ):
            raise domain_error("RECIPIENT_NOT_FOUND", 404)

        lock_key = normalized.renewal_key or normalized.occurrence_key
        self.repository.advisory_lock(f"w2-official-card:{lock_key}")
        existing_occurrence = self.repository.card_by_occurrence(normalized.occurrence_key)
        if existing_occurrence is not None:
            self._commit()
            return existing_occurrence

        current: W2OfficialWorkCard | None = None
        renewal_history: list[W2OfficialWorkCard] = []
        if normalized.renewal_key is not None:
            renewal_history = self.repository.cards_by_renewal_for_update(normalized.renewal_key)
            dominant = max(
                renewal_history,
                key=lambda item: card_priority(OfficialWorkCardKind(item.kind)),
                default=None,
            )
            if dominant is not None and card_priority(
                OfficialWorkCardKind(dominant.kind)
            ) >= card_priority(normalized.kind):
                self._commit()
                return dominant
            current = next(
                (item for item in renewal_history if item.closed_at_utc is None),
                None,
            )

        assignee_staff_id = self._resolve_new_card_assignee(normalized, renewal_history)

        now = _now()
        if current is not None:
            before = self._card_json(current)
            current.closed_at_utc = now
            current.closed_by_account_id = actor_account_id
            current.updated_by_account_id = actor_account_id
            current.updated_at_utc = now
            current.row_version += 1
            self._audit(
                actor_account_id=actor_account_id,
                action_code="W2_OFFICIAL_WORK_CARD_PRIORITY_REPLACED",
                entity_type="w2_official_work_card",
                entity_pk=current.id,
                before=before,
                after=self._card_json(current),
            )
            self._flush()

        row = W2OfficialWorkCard(
            kind=normalized.kind.value,
            work_title=normalized.work_title,
            recipient_id=normalized.recipient_id,
            target_name=normalized.target_name or "미입력",
            detail=normalized.detail,
            due_date=normalized.due_date,
            occurrence_key=normalized.occurrence_key,
            renewal_key=normalized.renewal_key,
            assignee_staff_id=assignee_staff_id,
            created_by_account_id=actor_account_id,
            updated_by_account_id=actor_account_id,
        )
        self.database_session.add(row)
        self._flush()
        self._audit(
            actor_account_id=actor_account_id,
            action_code="W2_OFFICIAL_WORK_CARD_CREATED",
            entity_type="w2_official_work_card",
            entity_pk=row.id,
            before=None,
            after=self._card_json(row),
        )
        self._commit()
        return row
