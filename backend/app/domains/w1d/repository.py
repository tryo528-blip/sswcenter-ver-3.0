"""W1D recipient-contract persistence helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    BusinessNumberCounter,
    Recipient,
    RecipientContract,
    ServiceType,
)


class W1DRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_recipient_for_update(self, recipient_id: int) -> Recipient | None:
        return self.session.scalar(
            select(Recipient).where(Recipient.id == recipient_id).with_for_update()
        )

    def get_recipient(self, recipient_id: int) -> Recipient | None:
        return self.session.get(Recipient, recipient_id)

    def list_contracts(self, recipient_id: int) -> list[RecipientContract]:
        return list(
            self.session.scalars(
                select(RecipientContract)
                .where(RecipientContract.recipient_id == recipient_id)
                .order_by(RecipientContract.id)
            ).all()
        )

    def get_contract(self, recipient_id: int, contract_id: int) -> RecipientContract | None:
        row = self.session.get(RecipientContract, contract_id)
        if row is None or row.recipient_id != recipient_id:
            return None
        return row

    def get_service_types(self) -> list[ServiceType]:
        return list(self.session.scalars(select(ServiceType)).all())

    def lock_or_create_recipient_no_counter(self) -> BusinessNumberCounter:
        row = self.session.scalar(
            select(BusinessNumberCounter)
            .where(
                BusinessNumberCounter.number_type == "RECIPIENT_NO",
                BusinessNumberCounter.number_year == 0,
            )
            .with_for_update()
        )
        if row is not None:
            return row
        self.session.execute(
            text(
                """
                INSERT INTO erp.business_number_counter
                    (number_type, number_year, last_sequence)
                VALUES ('RECIPIENT_NO', 0, 0)
                ON CONFLICT (number_type, number_year) DO NOTHING
                """
            )
        )
        self.session.flush()
        locked = self.session.scalar(
            select(BusinessNumberCounter)
            .where(
                BusinessNumberCounter.number_type == "RECIPIENT_NO",
                BusinessNumberCounter.number_year == 0,
            )
            .with_for_update()
        )
        if locked is None:
            raise RuntimeError("W1D_RECIPIENT_NO_COUNTER_LOCK_FAILED")
        return locked

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
