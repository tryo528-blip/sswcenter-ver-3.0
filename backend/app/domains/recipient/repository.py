from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Recipient,
    RecipientBenefitPeriod,
    RecipientContract,
    RecipientGradePeriod,
    RecipientGuardian,
    RecipientGuardianPrimaryPeriod,
    RecipientPayerSnapshot,
    RecipientPlanNotification,
    ServiceGroup,
    ServiceType,
)

# Exact catalog group / type order for list service presentation (user-frozen).
SERVICE_GROUP_ORDER: tuple[str, ...] = (
    "LONG_TERM_CARE",
    "LOCAL_CARE",
    "BARO_CARE",
)
SERVICE_TYPE_ORDER_BY_GROUP: dict[str, tuple[str, ...]] = {
    "LONG_TERM_CARE": ("HOME_CARE", "HOME_BATH"),
    "LOCAL_CARE": ("TEMP_HOME_CARE", "HOSPITAL_ESCORT"),
    "BARO_CARE": ("BARO_CARE",),
}
SERVICE_GROUP_RANK = {code: index for index, code in enumerate(SERVICE_GROUP_ORDER)}
SERVICE_TYPE_RANK: dict[str, int] = {
    type_code: index
    for type_codes in SERVICE_TYPE_ORDER_BY_GROUP.values()
    for index, type_code in enumerate(type_codes)
}


def contract_effective_on(as_of: date) -> Any:
    """SQLAlchemy predicate: non-invalidated contract covering as_of (inclusive)."""
    return (
        RecipientContract.invalidated_at_utc.is_(None),
        RecipientContract.start_date <= as_of,
        or_(
            RecipientContract.end_date.is_(None),
            RecipientContract.end_date >= as_of,
        ),
    )


class RecipientRepository:
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

    def list_recipients(
        self,
        *,
        search: str | None,
        status: str | None,
        as_of: date,
        offset: int,
        limit: int,
    ) -> tuple[list[Recipient], int]:
        statement = select(Recipient)
        count_statement = select(func.count()).select_from(Recipient)
        if search:
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            predicate = or_(
                Recipient.name.ilike(pattern, escape="\\"),
                Recipient.recipient_no.ilike(pattern, escape="\\"),
            )
            statement = statement.where(predicate)
            count_statement = count_statement.where(predicate)

        # Manual recipient_status tag equality; ALL/None = no status predicate.
        # as_of remains in the signature for call-site compatibility; list filter
        # does not derive status from contracts (projection loaders use as_of).
        _ = as_of
        if status and status != "ALL":
            tag_predicate = Recipient.recipient_status == status
            statement = statement.where(tag_predicate)
            count_statement = count_statement.where(tag_predicate)

        total = int(self.database_session.scalar(count_statement) or 0)
        items = list(
            self.database_session.scalars(
                statement.order_by(Recipient.name.asc(), Recipient.id.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total

    def load_effective_contracts_by_recipient(
        self,
        recipient_ids: list[int],
        as_of: date,
    ) -> dict[int, list[tuple[str, str, str, str]]]:
        """Map recipient_id -> list of (group_code, group_name, type_code, type_name)."""
        if not recipient_ids:
            return {}
        rows = self.database_session.execute(
            select(
                RecipientContract.recipient_id,
                ServiceGroup.code,
                ServiceGroup.display_name,
                ServiceType.code,
                ServiceType.display_name,
            )
            .join(ServiceType, ServiceType.id == RecipientContract.service_type_id)
            .join(ServiceGroup, ServiceGroup.id == ServiceType.service_group_id)
            .where(
                RecipientContract.recipient_id.in_(recipient_ids),
                *contract_effective_on(as_of),
            )
        ).all()

        by_recipient: dict[int, list[tuple[str, str, str, str]]] = {
            recipient_id: [] for recipient_id in recipient_ids
        }
        for recipient_id, group_code, group_name, type_code, type_name in rows:
            by_recipient.setdefault(int(recipient_id), []).append(
                (str(group_code), str(group_name), str(type_code), str(type_name))
            )

        for recipient_id, services in by_recipient.items():
            # Deduplicate type codes while preserving catalog sort.
            unique: dict[str, tuple[str, str, str, str]] = {}
            for item in services:
                unique[item[2]] = item
            ordered = sorted(
                unique.values(),
                key=lambda item: (
                    SERVICE_GROUP_RANK.get(item[0], 999),
                    SERVICE_TYPE_RANK.get(item[2], 999),
                    item[2],
                ),
            )
            by_recipient[recipient_id] = ordered
        return by_recipient

    def load_effective_grade_codes(
        self,
        recipient_ids: list[int],
        as_of: date,
    ) -> dict[int, str | None]:
        if not recipient_ids:
            return {}
        rows = self.database_session.execute(
            select(
                RecipientGradePeriod.recipient_id,
                RecipientGradePeriod.grade_code,
                RecipientGradePeriod.start_date,
                RecipientGradePeriod.id,
            )
            .where(
                RecipientGradePeriod.recipient_id.in_(recipient_ids),
                RecipientGradePeriod.invalidated_at_utc.is_(None),
                RecipientGradePeriod.start_date <= as_of,
                RecipientGradePeriod.end_date >= as_of,
            )
            .order_by(
                RecipientGradePeriod.recipient_id.asc(),
                RecipientGradePeriod.start_date.desc(),
                RecipientGradePeriod.id.desc(),
            )
        ).all()
        result: dict[int, str | None] = {recipient_id: None for recipient_id in recipient_ids}
        for recipient_id, grade_code, _start, _id in rows:
            key = int(recipient_id)
            if result.get(key) is None:
                result[key] = str(grade_code)
        return result

    def load_effective_benefit_codes(
        self,
        recipient_ids: list[int],
        as_of: date,
    ) -> dict[int, str | None]:
        if not recipient_ids:
            return {}
        rows = self.database_session.execute(
            select(
                RecipientBenefitPeriod.recipient_id,
                RecipientBenefitPeriod.benefit_code,
                RecipientBenefitPeriod.start_date,
                RecipientBenefitPeriod.id,
            )
            .where(
                RecipientBenefitPeriod.recipient_id.in_(recipient_ids),
                RecipientBenefitPeriod.invalidated_at_utc.is_(None),
                RecipientBenefitPeriod.start_date <= as_of,
                or_(
                    RecipientBenefitPeriod.end_date.is_(None),
                    RecipientBenefitPeriod.end_date >= as_of,
                ),
            )
            .order_by(
                RecipientBenefitPeriod.recipient_id.asc(),
                RecipientBenefitPeriod.start_date.desc(),
                RecipientBenefitPeriod.id.desc(),
            )
        ).all()
        result: dict[int, str | None] = {recipient_id: None for recipient_id in recipient_ids}
        for recipient_id, benefit_code, _start, _id in rows:
            key = int(recipient_id)
            if result.get(key) is None:
                result[key] = str(benefit_code)
        return result

    def get_guardian(
        self,
        recipient_id: int,
        guardian_id: int,
        *,
        for_update: bool = False,
    ) -> RecipientGuardian | None:
        statement = select(RecipientGuardian).where(
            RecipientGuardian.id == guardian_id,
            RecipientGuardian.recipient_id == recipient_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_guardians(self, recipient_id: int) -> list[RecipientGuardian]:
        return list(
            self.database_session.scalars(
                select(RecipientGuardian)
                .where(RecipientGuardian.recipient_id == recipient_id)
                .order_by(RecipientGuardian.id.asc())
            )
        )

    def get_primary_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientGuardianPrimaryPeriod | None:
        statement = select(RecipientGuardianPrimaryPeriod).where(
            RecipientGuardianPrimaryPeriod.id == period_id,
            RecipientGuardianPrimaryPeriod.recipient_id == recipient_id,
        )
        if active_only:
            statement = statement.where(RecipientGuardianPrimaryPeriod.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_primary_periods(self, recipient_id: int) -> list[RecipientGuardianPrimaryPeriod]:
        return list(
            self.database_session.scalars(
                select(RecipientGuardianPrimaryPeriod)
                .where(RecipientGuardianPrimaryPeriod.recipient_id == recipient_id)
                .order_by(
                    RecipientGuardianPrimaryPeriod.start_date.desc(),
                    RecipientGuardianPrimaryPeriod.id.desc(),
                )
            )
        )

    def get_payer_snapshot(
        self,
        recipient_id: int,
        snapshot_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientPayerSnapshot | None:
        statement = select(RecipientPayerSnapshot).where(
            RecipientPayerSnapshot.id == snapshot_id,
            RecipientPayerSnapshot.recipient_id == recipient_id,
        )
        if active_only:
            statement = statement.where(RecipientPayerSnapshot.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_payer_snapshots(self, recipient_id: int) -> list[RecipientPayerSnapshot]:
        return list(
            self.database_session.scalars(
                select(RecipientPayerSnapshot)
                .where(RecipientPayerSnapshot.recipient_id == recipient_id)
                .order_by(
                    RecipientPayerSnapshot.start_date.desc(),
                    RecipientPayerSnapshot.id.desc(),
                )
            )
        )

    def get_plan_notification(
        self,
        recipient_id: int,
        notification_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientPlanNotification | None:
        statement = select(RecipientPlanNotification).where(
            RecipientPlanNotification.id == notification_id,
            RecipientPlanNotification.recipient_id == recipient_id,
        )
        if active_only:
            statement = statement.where(RecipientPlanNotification.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_plan_notifications(
        self,
        recipient_id: int,
    ) -> list[RecipientPlanNotification]:
        return list(
            self.database_session.scalars(
                select(RecipientPlanNotification)
                .where(RecipientPlanNotification.recipient_id == recipient_id)
                .order_by(
                    RecipientPlanNotification.notified_date.desc(),
                    RecipientPlanNotification.id.desc(),
                )
            )
        )
