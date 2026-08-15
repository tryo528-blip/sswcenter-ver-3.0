"""Persistence and deterministic locking for W2 core ledgers."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    Recipient,
    RecipientCertificationPeriod,
    RecipientContract,
    ServiceType,
    Staff,
    StaffEmployment,
    StaffPositionPeriod,
    UserAccount,
)
from app.db.w2_models import (
    MonthlyProfessionalAssignment,
    W2OfficialWorkCard,
    W2PersonalTodo,
    W2PersonalTodoList,
    W2Schedule,
    W2ScheduleMonthControl,
    W2ScheduleStaff,
    W2ServicePlanNotice,
)


class W2Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def recipient(self, recipient_id: int, *, for_update: bool = False) -> Recipient | None:
        statement = select(Recipient).where(Recipient.id == recipient_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def staff(self, staff_id: int) -> Staff | None:
        return self.session.get(Staff, staff_id)

    def professional_assignment_staff_options(
        self,
        *,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[
        list[tuple[Staff, list[StaffEmployment], list[StaffPositionPeriod]]],
        int,
    ]:
        professional_staff_ids = select(StaffPositionPeriod.staff_id).where(
            StaffPositionPeriod.position_code.in_(("SOCIAL_WORKER", "NURSE")),
        )
        filters = [Staff.id.in_(professional_staff_ids)]
        if search:
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    Staff.name.ilike(pattern, escape="\\"),
                    Staff.display_name.ilike(pattern, escape="\\"),
                )
            )
        count_statement = select(func.count()).select_from(Staff).where(*filters)
        total = int(self.session.scalar(count_statement) or 0)
        staff_items = list(
            self.session.scalars(
                select(Staff)
                .where(*filters)
                .order_by(Staff.name.asc(), Staff.id.asc())
                .offset(offset)
                .limit(limit)
            ).all()
        )
        options = []
        for staff in staff_items:
            employments = list(
                self.session.scalars(
                    select(StaffEmployment)
                    .where(
                        StaffEmployment.staff_id == staff.id,
                        StaffEmployment.invalidated_at_utc.is_(None),
                    )
                    .order_by(StaffEmployment.start_date.desc(), StaffEmployment.id.desc())
                ).all()
            )
            positions = list(
                self.session.scalars(
                    select(StaffPositionPeriod)
                    .where(
                        StaffPositionPeriod.staff_id == staff.id,
                        StaffPositionPeriod.invalidated_at_utc.is_(None),
                    )
                    .order_by(StaffPositionPeriod.start_date.desc(), StaffPositionPeriod.id.desc())
                ).all()
            )
            options.append((staff, employments, positions))
        return options, total

    def service_type(self, service_type_id: int) -> ServiceType | None:
        return self.session.get(ServiceType, service_type_id)

    def account(self, account_id: int) -> UserAccount | None:
        return self.session.get(UserAccount, account_id)

    def account_staff_id(self, account_id: int) -> int | None:
        return self.session.scalar(
            select(UserAccount.staff_id).where(
                UserAccount.id == account_id,
                UserAccount.active.is_(True),
            )
        )
    def staff_is_admin_account(self, staff_id: int) -> bool:
        return (
            self.session.scalar(
                select(UserAccount.id).where(
                    UserAccount.staff_id == staff_id,
                    UserAccount.active.is_(True),
                    UserAccount.role_code == "ADMIN",
                )
            )
            is not None
        )

    def staff_has_professional_position(
        self,
        staff_id: int,
        start_date: date,
        end_date: date | None = None,
    ) -> bool:
        effective_end = end_date or start_date
        return (
            self.session.scalar(
                select(StaffPositionPeriod.id).where(
                    StaffPositionPeriod.staff_id == staff_id,
                    StaffPositionPeriod.position_code.in_(("SOCIAL_WORKER", "NURSE")),
                    StaffPositionPeriod.invalidated_at_utc.is_(None),
                    StaffPositionPeriod.start_date <= effective_end,
                    or_(
                        StaffPositionPeriod.end_date.is_(None),
                        StaffPositionPeriod.end_date >= start_date,
                    ),
                )
            )
            is not None
        )

    def employment_fact(
        self,
        staff_id: int,
        employment_id: int,
    ) -> StaffEmployment | None:
        return self.session.scalar(
            select(StaffEmployment)
            .where(
                StaffEmployment.staff_id == staff_id,
                StaffEmployment.id == employment_id,
                StaffEmployment.invalidated_at_utc.is_(None),
            )
        )

    def employment_covers(
        self,
        staff_id: int,
        employment_id: int,
        start_date: date,
        end_date: date,
    ) -> bool:
        return (
            self.session.scalar(
                select(StaffEmployment.id).where(
                    StaffEmployment.staff_id == staff_id,
                    StaffEmployment.id == employment_id,
                    StaffEmployment.invalidated_at_utc.is_(None),
                    StaffEmployment.start_date <= start_date,
                    or_(
                        StaffEmployment.end_date.is_(None),
                        StaffEmployment.end_date >= end_date,
                    ),
                )
            )
            is not None
        )

    def professional_position_covers(
        self,
        staff_id: int,
        employment_id: int,
        start_date: date,
        end_date: date,
    ) -> bool:
        return bool(
            self.session.scalar(
                text(
                    """
                    SELECT daterange(
                               CAST(:start_date AS date),
                               CAST(:end_date AS date) + 1,
                               '[)'
                           ) <@ COALESCE(
                               (
                                   SELECT range_agg(position.position_period)
                                     FROM erp.staff_position_period position
                                    WHERE position.staff_id = :staff_id
                                      AND position.employment_id = :employment_id
                                      AND position.position_code IN
                                          ('SOCIAL_WORKER', 'NURSE')
                                      AND position.invalidated_at_utc IS NULL
                               ),
                               '{}'::datemultirange
                           )
                    """
                ),
                {
                    "staff_id": staff_id,
                    "employment_id": employment_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        )

    def current_assignments_for_update(
        self,
        recipient_id: int,
        service_month: date,
    ) -> list[MonthlyProfessionalAssignment]:
        return list(
            self.session.scalars(
                select(MonthlyProfessionalAssignment)
                .where(
                    MonthlyProfessionalAssignment.recipient_id == recipient_id,
                    MonthlyProfessionalAssignment.service_month == service_month,
                    MonthlyProfessionalAssignment.invalidated_at_utc.is_(None),
                )
                .order_by(MonthlyProfessionalAssignment.id)
                .with_for_update()
            ).all()
        )

    def assignment_history(
        self,
        recipient_id: int,
        service_month: date,
    ) -> list[MonthlyProfessionalAssignment]:
        return list(
            self.session.scalars(
                select(MonthlyProfessionalAssignment)
                .where(
                    MonthlyProfessionalAssignment.recipient_id == recipient_id,
                    MonthlyProfessionalAssignment.service_month == service_month,
                )
                .order_by(MonthlyProfessionalAssignment.id)
            ).all()
        )

    def recipient_contract(
        self,
        contract_id: int,
        *,
        for_update: bool = False,
    ) -> RecipientContract | None:
        statement = select(RecipientContract).where(RecipientContract.id == contract_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def recipient_certifications(
        self,
        recipient_id: int,
        *,
        for_update: bool = False,
    ) -> list[RecipientCertificationPeriod]:
        statement = (
            select(RecipientCertificationPeriod)
            .where(
                RecipientCertificationPeriod.recipient_id == recipient_id,
                RecipientCertificationPeriod.invalidated_at_utc.is_(None),
            )
            .order_by(RecipientCertificationPeriod.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(self.session.scalars(statement).all())

    def service_plan_notices(
        self,
        recipient_id: int,
    ) -> list[tuple[W2ServicePlanNotice, RecipientContract]]:
        statement = (
            select(W2ServicePlanNotice, RecipientContract)
            .join(
                RecipientContract,
                RecipientContract.id == W2ServicePlanNotice.recipient_contract_id,
            )
            .where(RecipientContract.recipient_id == recipient_id)
            .order_by(W2ServicePlanNotice.notification_date, W2ServicePlanNotice.id)
        )
        return [
            (notice, contract)
            for notice, contract in self.session.execute(statement).all()
        ]

    def service_plan_notice_for_update(
        self,
        notice_id: int,
    ) -> W2ServicePlanNotice | None:
        return self.session.scalar(
            select(W2ServicePlanNotice)
            .where(W2ServicePlanNotice.id == notice_id)
            .with_for_update()
        )

    def schedule_month(
        self,
        schedule_month: date,
        *,
        for_update: bool = False,
    ) -> W2ScheduleMonthControl | None:
        statement = select(W2ScheduleMonthControl).where(
            W2ScheduleMonthControl.schedule_month == schedule_month
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def lock_or_create_schedule_month(
        self,
        schedule_month: date,
        actor_account_id: int,
    ) -> W2ScheduleMonthControl:
        self.session.execute(
            postgres_insert(W2ScheduleMonthControl)
            .values(
                schedule_month=schedule_month,
                created_by_account_id=actor_account_id,
                updated_by_account_id=actor_account_id,
            )
            .on_conflict_do_nothing(
                index_elements=[W2ScheduleMonthControl.schedule_month]
            )
        )
        self.session.flush()
        row = self.schedule_month(schedule_month, for_update=True)
        if row is None:
            raise RuntimeError("W2_SCHEDULE_MONTH_LOCK_FAILED")
        return row

    def schedules(
        self,
        schedule_month: date,
        *,
        recipient_id: int | None = None,
        staff_id: int | None = None,
        for_update: bool = False,
    ) -> list[W2Schedule]:
        statement = select(W2Schedule).where(W2Schedule.schedule_month == schedule_month)
        if recipient_id is not None:
            statement = statement.where(W2Schedule.recipient_id == recipient_id)
        if staff_id is not None:
            statement = statement.where(
                W2Schedule.id.in_(
                    select(W2ScheduleStaff.schedule_id).where(
                        W2ScheduleStaff.staff_id == staff_id
                    )
                )
            )
        statement = statement.order_by(W2Schedule.id)
        if for_update:
            statement = statement.with_for_update()
        return list(self.session.scalars(statement).all())

    def schedule_for_update(self, schedule_id: int) -> W2Schedule | None:
        return self.session.scalar(
            select(W2Schedule)
            .where(W2Schedule.id == schedule_id)
            .order_by(W2Schedule.id)
            .with_for_update()
        )

    def schedule_month_for_id(self, schedule_id: int) -> date | None:
        return self.session.scalar(
            select(W2Schedule.schedule_month).where(W2Schedule.id == schedule_id)
        )

    def schedule_staff(
        self,
        schedule_id: int,
        *,
        for_update: bool = False,
    ) -> list[W2ScheduleStaff]:
        statement = (
            select(W2ScheduleStaff)
            .where(W2ScheduleStaff.schedule_id == schedule_id)
            .order_by(W2ScheduleStaff.id)
        )
        if for_update:
            statement = statement.with_for_update()
        return list(self.session.scalars(statement).all())

    def schedule_coverage_errors(self, rows: list[W2Schedule]) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for row in sorted(rows, key=lambda item: item.id):
            for assigned in self.schedule_staff(row.id):
                values = self.session.execute(
                    text(
                        """
                        SELECT EXISTS (
                                   SELECT 1
                                     FROM erp.staff_employment employment
                                    WHERE employment.id = :employment_id
                                      AND employment.staff_id = :staff_id
                                      AND employment.invalidated_at_utc IS NULL
                                      AND daterange(
                                          (:starts_at AT TIME ZONE 'Asia/Seoul')::date,
                                          ((:ends_at - INTERVAL '1 microsecond')
                                              AT TIME ZONE 'Asia/Seoul')::date + 1,
                                          '[)'
                                      ) <@ employment.employment_period
                               ) AS employment_ok,
                               daterange(
                                   (:starts_at AT TIME ZONE 'Asia/Seoul')::date,
                                   ((:ends_at - INTERVAL '1 microsecond')
                                       AT TIME ZONE 'Asia/Seoul')::date + 1,
                                   '[)'
                               ) <@ COALESCE(
                                   (
                                       SELECT range_agg(position.position_period)
                                         FROM erp.staff_position_period position
                                        WHERE position.staff_id = :staff_id
                                          AND position.employment_id = :employment_id
                                          AND position.position_code = 'CARE_WORKER'
                                          AND position.invalidated_at_utc IS NULL
                                   ),
                                   '{}'::datemultirange
                               ) AS position_ok,
                               daterange(
                                   (:starts_at AT TIME ZONE 'Asia/Seoul')::date,
                                   ((:ends_at - INTERVAL '1 microsecond')
                                       AT TIME ZONE 'Asia/Seoul')::date + 1,
                                   '[)'
                               ) <@ COALESCE(
                                   (
                                       SELECT range_agg(qualification.qualification_period)
                                         FROM erp.staff_service_qualification_period
                                             qualification
                                        WHERE qualification.staff_id = :staff_id
                                          AND qualification.employment_id = :employment_id
                                          AND qualification.service_type_id = :service_type_id
                                          AND qualification.invalidated_at_utc IS NULL
                                   ),
                                   '{}'::datemultirange
                               ) AS qualification_ok
                        """
                    ),
                    {
                        "staff_id": assigned.staff_id,
                        "employment_id": assigned.employment_id,
                        "service_type_id": row.service_type_id,
                        "starts_at": row.starts_at_utc,
                        "ends_at": row.ends_at_utc,
                    },
                ).mappings().one()
                details = {
                    "schedule_id": row.id,
                    "staff_id": assigned.staff_id,
                    "employment_id": assigned.employment_id,
                }
                if not values["employment_ok"]:
                    errors.append({**details, "code": "SCHEDULE_OUTSIDE_EMPLOYMENT"})
                if not values["position_ok"]:
                    errors.append(
                        {**details, "code": "SCHEDULE_CARE_WORKER_POSITION_REQUIRED"}
                    )
                if not values["qualification_ok"]:
                    errors.append({**details, "code": "SCHEDULE_OUTSIDE_QUALIFICATION"})
        return errors

    def todo_list(
        self,
        owner_account_id: int,
        *,
        for_update: bool = False,
    ) -> W2PersonalTodoList | None:
        statement = select(W2PersonalTodoList).where(
            W2PersonalTodoList.owner_account_id == owner_account_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def lock_or_create_todo_list(self, owner_account_id: int) -> W2PersonalTodoList:
        self.session.execute(
            postgres_insert(W2PersonalTodoList)
            .values(owner_account_id=owner_account_id)
            .on_conflict_do_nothing(index_elements=[W2PersonalTodoList.owner_account_id])
        )
        self.session.flush()
        row = self.todo_list(owner_account_id, for_update=True)
        if row is None:
            raise RuntimeError("W2_PERSONAL_TODO_LIST_LOCK_FAILED")
        return row

    def todos(self, owner_account_id: int, *, for_update: bool = False) -> list[W2PersonalTodo]:
        statement = (
            select(W2PersonalTodo)
            .where(W2PersonalTodo.owner_account_id == owner_account_id)
            .order_by(W2PersonalTodo.id if for_update else W2PersonalTodo.sort_order)
        )
        if not for_update:
            statement = statement.order_by(W2PersonalTodo.id)
        if for_update:
            statement = statement.with_for_update()
        return list(self.session.scalars(statement).all())

    def todo_for_update(self, owner_account_id: int, todo_id: int) -> W2PersonalTodo | None:
        return self.session.scalar(
            select(W2PersonalTodo)
            .where(
                W2PersonalTodo.owner_account_id == owner_account_id,
                W2PersonalTodo.id == todo_id,
            )
            .order_by(W2PersonalTodo.id)
            .with_for_update()
        )

    def next_todo_sort_order(self, owner_account_id: int) -> int:
        current = self.session.scalar(
            select(func.max(W2PersonalTodo.sort_order)).where(
                W2PersonalTodo.owner_account_id == owner_account_id
            )
        )
        return 0 if current is None else int(current) + 1

    def advisory_lock(self, key: str) -> None:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )

    def card_by_occurrence(self, occurrence_key: str) -> W2OfficialWorkCard | None:
        return self.session.scalar(
            select(W2OfficialWorkCard).where(
                W2OfficialWorkCard.occurrence_key == occurrence_key
            )
        )

    def cards_by_renewal_for_update(
        self,
        renewal_key: str,
    ) -> list[W2OfficialWorkCard]:
        return list(
            self.session.scalars(
                select(W2OfficialWorkCard)
                .where(W2OfficialWorkCard.renewal_key == renewal_key)
                .order_by(W2OfficialWorkCard.id)
                .with_for_update()
            ).all()
        )

    def card_for_update(self, card_id: int) -> W2OfficialWorkCard | None:
        return self.session.scalar(
            select(W2OfficialWorkCard)
            .where(W2OfficialWorkCard.id == card_id)
            .with_for_update()
        )

    def open_cards(
        self,
        *,
        assignee_staff_id: int | None = None,
    ) -> list[tuple[W2OfficialWorkCard, Staff]]:
        statement = (
            select(W2OfficialWorkCard, Staff)
            .join(Staff, Staff.id == W2OfficialWorkCard.assignee_staff_id)
            .where(W2OfficialWorkCard.closed_at_utc.is_(None))
        )
        if assignee_staff_id is not None:
            statement = statement.where(
                W2OfficialWorkCard.assignee_staff_id == assignee_staff_id
            )
        statement = statement.order_by(
            Staff.name,
            W2OfficialWorkCard.due_date,
            W2OfficialWorkCard.id,
        )
        return [(card, staff) for card, staff in self.session.execute(statement).all()]

    def append_audit(
        self,
        *,
        actor_account_id: int | None,
        actor_kind: str,
        action_code: str,
        entity_type: str,
        entity_pk: int | None,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
        request_id: UUID | None,
        occurred_at_utc: Any,
        created_from: str,
    ) -> None:
        self.session.add(
            AuditEvent(
                occurred_at_utc=occurred_at_utc,
                actor_account_id=actor_account_id,
                actor_kind=actor_kind,
                action_code=action_code,
                entity_type=entity_type,
                entity_pk=entity_pk,
                before_json=before_json,
                after_json=after_json,
                reason_code=None,
                reason_text=None,
                source_run_id=None,
                request_id=request_id,
                created_from=created_from,
            )
        )
