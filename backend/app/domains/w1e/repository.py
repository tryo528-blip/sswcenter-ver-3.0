from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, CareAssignment, Recipient, RecipientContract


class W1ERepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_recipient(self, recipient_id: int) -> Recipient | None:
        return self.session.get(Recipient, recipient_id)

    def get_contract_for_update(
        self,
        recipient_id: int,
        contract_id: int,
    ) -> RecipientContract | None:
        return self.session.scalar(
            select(RecipientContract)
            .where(
                RecipientContract.id == contract_id,
                RecipientContract.recipient_id == recipient_id,
            )
            .with_for_update()
        )

    def get_contract(self, recipient_id: int, contract_id: int) -> RecipientContract | None:
        return self.session.scalar(
            select(RecipientContract).where(
                RecipientContract.id == contract_id,
                RecipientContract.recipient_id == recipient_id,
            )
        )

    def list_assignments(
        self,
        recipient_id: int,
        contract_id: int,
    ) -> list[CareAssignment]:
        return list(
            self.session.scalars(
                select(CareAssignment)
                .join(
                    RecipientContract,
                    RecipientContract.id == CareAssignment.recipient_contract_id,
                )
                .where(
                    RecipientContract.recipient_id == recipient_id,
                    CareAssignment.recipient_contract_id == contract_id,
                )
                .order_by(CareAssignment.id)
            ).all()
        )

    def get_assignment(
        self,
        recipient_id: int,
        contract_id: int,
        assignment_id: int,
        *,
        for_update: bool = False,
    ) -> CareAssignment | None:
        statement = (
            select(CareAssignment)
            .join(
                RecipientContract,
                RecipientContract.id == CareAssignment.recipient_contract_id,
            )
            .where(
                RecipientContract.recipient_id == recipient_id,
                CareAssignment.recipient_contract_id == contract_id,
                CareAssignment.id == assignment_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def append_audit(
        self,
        *,
        actor_account_id: int,
        action_code: str,
        entity_pk: int,
        before_json: dict[str, Any] | None,
        after_json: dict[str, Any] | None,
        request_id: UUID | None,
        occurred_at_utc: Any,
    ) -> AuditEvent:
        event = AuditEvent(
            occurred_at_utc=occurred_at_utc,
            actor_account_id=actor_account_id,
            actor_kind="USER",
            action_code=action_code,
            entity_type="CARE_ASSIGNMENT",
            entity_pk=entity_pk,
            before_json=before_json,
            after_json=after_json,
            reason_code="USER_MUTATION",
            reason_text=None,
            source_run_id=None,
            request_id=request_id,
            created_from="API",
        )
        self.session.add(event)
        self.session.flush()
        return event
