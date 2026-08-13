from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationPeriod,
    RecipientContract,
    RecipientGuardian,
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
                statement.order_by(Recipient.name.asc().nulls_last(), Recipient.id.asc())
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
                RecipientCertificationPeriod.recipient_id,
                RecipientCertificationPeriod.grade_code,
                RecipientCertificationPeriod.start_date,
                RecipientCertificationPeriod.id,
            )
            .where(
                RecipientCertificationPeriod.recipient_id.in_(recipient_ids),
                RecipientCertificationPeriod.invalidated_at_utc.is_(None),
                RecipientCertificationPeriod.start_date <= as_of,
                RecipientCertificationPeriod.end_date >= as_of,
            )
            .order_by(
                RecipientCertificationPeriod.recipient_id.asc(),
                RecipientCertificationPeriod.start_date.desc(),
                RecipientCertificationPeriod.id.desc(),
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
        # ``as_of`` is intentionally ignored: benefit.start_text is opaque
        # display text and must not participate in date parsing/comparison.
        _ = as_of
        rows = self.database_session.execute(
            select(
                RecipientBenefitPeriod.recipient_id,
                RecipientBenefitPeriod.benefit_code,
                RecipientBenefitPeriod.id,
            )
            .where(
                RecipientBenefitPeriod.recipient_id.in_(recipient_ids),
                RecipientBenefitPeriod.invalidated_at_utc.is_(None),
            )
            .order_by(
                RecipientBenefitPeriod.recipient_id.asc(),
                RecipientBenefitPeriod.id.desc(),
            )
        ).all()
        result: dict[int, str | None] = {recipient_id: None for recipient_id in recipient_ids}
        for recipient_id, benefit_code, _id in rows:
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
                .order_by(RecipientGuardian.slot_no.asc())
            )
        )
