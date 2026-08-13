from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationIdentity,
    RecipientCertificationPeriod,
    RecipientLocalApprovalAmountPeriod,
)


class W1CRepository:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def add(self, instance: object) -> None:
        self.database_session.add(instance)

    def flush(self) -> None:
        self.database_session.flush()

    def get_recipient(self, recipient_id: int, *, for_update: bool = False) -> Recipient | None:
        statement = select(Recipient).where(Recipient.id == recipient_id)
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_identity(
        self,
        recipient_id: int,
        *,
        for_update: bool = False,
    ) -> RecipientCertificationIdentity | None:
        statement = select(RecipientCertificationIdentity).where(
            RecipientCertificationIdentity.recipient_id == recipient_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_identity_by_number(
        self,
        certification_number: str,
    ) -> RecipientCertificationIdentity | None:
        return self.database_session.scalar(
            select(RecipientCertificationIdentity).where(
                RecipientCertificationIdentity.certification_number == certification_number
            )
        )

    def get_certification_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientCertificationPeriod | None:
        statement = select(RecipientCertificationPeriod).where(
            RecipientCertificationPeriod.id == period_id,
            RecipientCertificationPeriod.recipient_id == recipient_id,
        )
        if active_only:
            statement = statement.where(RecipientCertificationPeriod.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_certification_periods(
        self,
        recipient_id: int,
    ) -> list[RecipientCertificationPeriod]:
        return list(
            self.database_session.scalars(
                select(RecipientCertificationPeriod)
                .where(RecipientCertificationPeriod.recipient_id == recipient_id)
                .order_by(
                    RecipientCertificationPeriod.start_date.desc(),
                    RecipientCertificationPeriod.id.desc(),
                )
            )
        )

    def get_benefit_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientBenefitPeriod | None:
        statement = select(RecipientBenefitPeriod).where(
            RecipientBenefitPeriod.id == period_id,
            RecipientBenefitPeriod.recipient_id == recipient_id,
        )
        if active_only:
            statement = statement.where(RecipientBenefitPeriod.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_benefit_periods(self, recipient_id: int) -> list[RecipientBenefitPeriod]:
        return list(
            self.database_session.scalars(
                select(RecipientBenefitPeriod)
                .where(RecipientBenefitPeriod.recipient_id == recipient_id)
                .order_by(RecipientBenefitPeriod.id.desc())
            )
        )

    def get_approval_amount_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientLocalApprovalAmountPeriod | None:
        statement = select(RecipientLocalApprovalAmountPeriod).where(
            RecipientLocalApprovalAmountPeriod.id == period_id,
            RecipientLocalApprovalAmountPeriod.recipient_id == recipient_id,
        )
        if active_only:
            statement = statement.where(
                RecipientLocalApprovalAmountPeriod.invalidated_at_utc.is_(None)
            )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_approval_amount_periods(
        self,
        recipient_id: int,
    ) -> list[RecipientLocalApprovalAmountPeriod]:
        return list(
            self.database_session.scalars(
                select(RecipientLocalApprovalAmountPeriod)
                .where(RecipientLocalApprovalAmountPeriod.recipient_id == recipient_id)
                .order_by(
                    RecipientLocalApprovalAmountPeriod.start_date.desc(),
                    RecipientLocalApprovalAmountPeriod.id.desc(),
                )
            )
        )
