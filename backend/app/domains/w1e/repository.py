"""W1E care-assignment persistence helpers and deterministic lock points."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    CareAssignment,
    RecipientContract,
    StaffEmployment,
)


class W1ERepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_contract_for_update(
        self,
        recipient_id: int,
        contract_id: int,
    ) -> RecipientContract | None:
        row = self.session.scalar(
            select(RecipientContract)
            .where(
                RecipientContract.id == contract_id,
                RecipientContract.recipient_id == recipient_id,
            )
            .with_for_update()
        )
        return row

    def get_contract(
        self,
        recipient_id: int,
        contract_id: int,
    ) -> RecipientContract | None:
        row = self.session.get(RecipientContract, contract_id)
        if row is None or row.recipient_id != recipient_id:
            return None
        return row

    def list_assignments(
        self,
        contract_id: int,
        *,
        as_of: date | None = None,
    ) -> list[CareAssignment]:
        statement = select(CareAssignment).where(
            CareAssignment.recipient_contract_id == contract_id
        )
        if as_of is not None:
            statement = statement.where(
                CareAssignment.invalidated_at_utc.is_(None),
                CareAssignment.start_date <= as_of,
                or_(
                    CareAssignment.end_date.is_(None),
                    CareAssignment.end_date >= as_of,
                ),
            ).order_by(CareAssignment.start_date.desc(), CareAssignment.id.desc())
        else:
            statement = statement.order_by(CareAssignment.id)
        return list(self.session.scalars(statement).all())

    def get_assignment(
        self,
        contract_id: int,
        assignment_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> CareAssignment | None:
        statement = select(CareAssignment).where(
            CareAssignment.id == assignment_id,
            CareAssignment.recipient_contract_id == contract_id,
        )
        if active_only:
            statement = statement.where(CareAssignment.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_employment(
        self,
        staff_id: int,
        employment_id: int,
    ) -> StaffEmployment | None:
        return self.session.scalar(
            select(StaffEmployment).where(
                StaffEmployment.staff_id == staff_id,
                StaffEmployment.id == employment_id,
                StaffEmployment.invalidated_at_utc.is_(None),
            )
        )

    def care_worker_position_covers(
        self,
        *,
        staff_id: int,
        employment_id: int,
        start_date: date,
        end_date: date | None,
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
                                      AND position.position_code = 'CARE_WORKER'
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

    def qualification_covers(
        self,
        *,
        staff_id: int,
        employment_id: int,
        service_type_id: int,
        start_date: date,
        end_date: date | None,
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
                                   SELECT range_agg(qualification.qualification_period)
                                     FROM erp.staff_service_qualification_period
                                          qualification
                                    WHERE qualification.staff_id = :staff_id
                                      AND qualification.employment_id = :employment_id
                                      AND qualification.service_type_id = :service_type_id
                                      AND qualification.invalidated_at_utc IS NULL
                               ),
                               '{}'::datemultirange
                           )
                    """
                ),
                {
                    "staff_id": staff_id,
                    "employment_id": employment_id,
                    "service_type_id": service_type_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
        )

    def assignment_overlaps_active(
        self,
        *,
        contract_id: int,
        staff_id: int,
        start_date: date,
        end_date: date | None,
        exclude_assignment_id: int | None = None,
    ) -> bool:
        return bool(
            self.session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                          FROM erp.care_assignment existing
                         WHERE existing.recipient_contract_id = :contract_id
                           AND existing.staff_id = :staff_id
                           AND existing.invalidated_at_utc IS NULL
                           AND (
                               CAST(:exclude_assignment_id AS bigint) IS NULL
                               OR existing.id <> CAST(:exclude_assignment_id AS bigint)
                           )
                           AND existing.assignment_period && daterange(
                                   CAST(:start_date AS date),
                                   CAST(:end_date AS date) + 1,
                                   '[)'
                               )
                    )
                    """
                ),
                {
                    "contract_id": contract_id,
                    "staff_id": staff_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "exclude_assignment_id": exclude_assignment_id,
                },
            )
        )

    def append_audit(
        self,
        *,
        actor_account_id: int | None,
        action_code: str,
        entity_type: str,
        entity_pk: int | None,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
        reason_code: str | None,
        request_id: UUID | None,
        occurred_at_utc: Any,
    ) -> AuditEvent:
        event = AuditEvent(
            occurred_at_utc=occurred_at_utc,
            actor_account_id=actor_account_id,
            actor_kind="USER",
            action_code=action_code,
            entity_type=entity_type,
            entity_pk=entity_pk,
            before_json=before_json,
            after_json=after_json,
            reason_code=reason_code,
            reason_text=None,
            source_run_id=None,
            request_id=request_id,
            created_from="API",
        )
        self.session.add(event)
        self.session.flush()
        return event
