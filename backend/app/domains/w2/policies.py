"""Pure W2 policy functions and source-ready card interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from app.domains.w2.schemas import OfficialWorkCardKind

RENEWAL_PRIORITY: dict[OfficialWorkCardKind, int] = {
    OfficialWorkCardKind.RECOGNITION_EXPIRY: 3,
    OfficialWorkCardKind.CONTRACT_EXPIRY: 2,
    OfficialWorkCardKind.PLAN_NOTICE: 1,
}


@dataclass(frozen=True)
class OfficialCardSource:
    kind: OfficialWorkCardKind
    occurrence_key: str
    renewal_key: str | None
    work_title: str
    target_name: str | None
    detail: str
    due_date: date
    recipient_id: int | None = None


class OfficialCardSourceSink(Protocol):
    """Future generators call this interface; it is not a public HTTP API."""

    def record_official_source(
        self,
        source: OfficialCardSource,
        *,
        actor_account_id: int | None = None,
    ) -> object: ...


def clean_required_text(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be blank")
    return cleaned


def display_target_name(value: str | None) -> str:
    cleaned = value.strip() if value is not None else ""
    return cleaned or "미입력"


def month_start(value: date) -> date:
    return value.replace(day=1)


def card_priority(kind: OfficialWorkCardKind) -> int:
    return RENEWAL_PRIORITY.get(kind, 0)


def recognition_expiry_source(
    *,
    occurrence_key: str,
    renewal_key: str,
    recognition_end_date: date,
    target_name: str | None,
    detail: str,
    recipient_id: int,
) -> OfficialCardSource:
    return OfficialCardSource(
        kind=OfficialWorkCardKind.RECOGNITION_EXPIRY,
        occurrence_key=occurrence_key,
        renewal_key=renewal_key,
        work_title="인정만료",
        target_name=target_name,
        detail=detail,
        due_date=recognition_end_date - timedelta(days=100),
        recipient_id=recipient_id,
    )


def contract_expiry_source(
    *,
    occurrence_key: str,
    renewal_key: str,
    contract_end_date: date,
    target_name: str | None,
    detail: str,
    recipient_id: int,
) -> OfficialCardSource:
    return OfficialCardSource(
        kind=OfficialWorkCardKind.CONTRACT_EXPIRY,
        occurrence_key=occurrence_key,
        renewal_key=renewal_key,
        work_title="계약만료",
        target_name=target_name,
        detail=detail,
        due_date=contract_end_date - timedelta(days=45),
        recipient_id=recipient_id,
    )


def plan_notice_source(
    *,
    occurrence_key: str,
    renewal_key: str,
    writing_deadline: date,
    target_name: str | None,
    detail: str,
    recipient_id: int,
) -> OfficialCardSource:
    return OfficialCardSource(
        kind=OfficialWorkCardKind.PLAN_NOTICE,
        occurrence_key=occurrence_key,
        renewal_key=renewal_key,
        work_title="계획서통보",
        target_name=target_name,
        detail=detail,
        due_date=writing_deadline - timedelta(days=45),
        recipient_id=recipient_id,
    )


def validate_official_source(source: OfficialCardSource) -> OfficialCardSource:
    if source.recipient_id is not None and source.recipient_id <= 0:
        raise ValueError("recipient_id must be positive")
    occurrence_key = clean_required_text(source.occurrence_key, field="occurrence_key")
    renewal_key = source.renewal_key.strip() if source.renewal_key is not None else None
    if renewal_key == "":
        raise ValueError("renewal_key must not be blank")
    if source.kind in RENEWAL_PRIORITY and renewal_key is None:
        raise ValueError("renewal cards require renewal_key")
    if source.kind not in RENEWAL_PRIORITY and renewal_key is not None:
        raise ValueError("non-renewal cards must not use renewal_key")
    return OfficialCardSource(
        kind=source.kind,
        occurrence_key=occurrence_key,
        renewal_key=renewal_key,
        work_title=clean_required_text(source.work_title, field="work_title"),
        target_name=display_target_name(source.target_name),
        detail=clean_required_text(source.detail, field="detail"),
        due_date=source.due_date,
        recipient_id=source.recipient_id,
    )
