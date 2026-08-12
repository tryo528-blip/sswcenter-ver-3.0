from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.db.models import (
    AuditEvent,
    Recipient,
    RecipientCertificationPeriod,
    RecipientContract,
    RecipientGuardian,
    RecipientGuardianPrimaryPeriod,
    RecipientPayerSnapshot,
    RecipientPlanNotification,
)
from app.domains.recipient.errors import RecipientDomainError
from app.domains.recipient.policies import (
    clean_optional_text,
    clean_required_text,
    validate_period,
)
from app.domains.recipient.repository import (
    SERVICE_GROUP_ORDER,
    SERVICE_TYPE_ORDER_BY_GROUP,
    RecipientRepository,
)
from app.domains.recipient.schemas import (
    GuardianCreateRequest,
    GuardianListResponse,
    GuardianResponse,
    GuardianUpdateRequest,
    HistoryInvalidateRequest,
    PayerSnapshotCreateRequest,
    PayerSnapshotListResponse,
    PayerSnapshotReplacementRequest,
    PayerSnapshotReplacementResponse,
    PayerSnapshotResponse,
    PlanNotificationCreateRequest,
    PlanNotificationListResponse,
    PlanNotificationResponse,
    PrimaryGuardianPeriodCreateRequest,
    PrimaryGuardianPeriodListResponse,
    PrimaryGuardianPeriodReplacementRequest,
    PrimaryGuardianPeriodReplacementResponse,
    PrimaryGuardianPeriodResponse,
    RecipientCreateRequest,
    RecipientDeadlineItem,
    RecipientDeadlineKind,
    RecipientDeadlineListResponse,
    RecipientListItem,
    RecipientListResponse,
    RecipientListServiceGroupItem,
    RecipientListServiceTypeItem,
    RecipientListStatusFilter,
    RecipientResponse,
    RecipientSexCode,
    RecipientStatus,
    RecipientUpdateRequest,
)

_SEOUL = ZoneInfo("Asia/Seoul")
_TodayFn = Callable[[], date]
_today_override: _TodayFn | None = None


def set_today_seoul(fn: _TodayFn | None) -> None:
    """Test seam: override Asia/Seoul calendar date, or None to restore real clock."""
    global _today_override
    _today_override = fn


def today_seoul() -> date:
    if _today_override is not None:
        return _today_override()
    return datetime.now(_SEOUL).date()


_MESSAGES = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "RECIPIENT_GUARDIAN_NOT_FOUND": "보호자를 찾을 수 없습니다.",
    "PRIMARY_GUARDIAN_PERIOD_NOT_FOUND": "대표 보호자 기간을 찾을 수 없습니다.",
    "PAYER_SNAPSHOT_NOT_FOUND": "납부자 이력을 찾을 수 없습니다.",
    "RECIPIENT_PLAN_NOTIFICATION_NOT_FOUND": "수급자 계획 알림 이력을 찾을 수 없습니다.",
    "PRIMARY_GUARDIAN_PERIOD_CONFLICT": "대표 보호자 기간이 기존 기간과 겹칩니다.",
    "CURRENT_PAYER_CONFLICT": "납부자 기간이 기존 기간과 겹칩니다.",
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.",
    "VALIDATION_ERROR": "입력값을 확인하세요.",
    "UNEXPECTED_SERVER_ERROR": "요청을 처리하지 못했습니다.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _plan_renewal_due_date(notified_date: date) -> date:
    month = notified_date.month + 6
    year = notified_date.year
    if month > 12:
        month -= 12
        year += 1
    _, last_day = monthrange(year, month)
    return date(year, month, last_day)


def _domain_error(
    code: str,
    status_code: int,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> RecipientDomainError:
    field_errors = []
    if field is not None:
        field_errors.append({"field": field, "message": _MESSAGES[code]})
    return RecipientDomainError(
        code=code,
        status_code=status_code,
        message=_MESSAGES[code],
        field_errors=field_errors,
        details=details or {},
    )


class RecipientService:
    def __init__(
        self,
        database_session: Session,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.database_session = database_session
        self.repository = RecipientRepository(database_session)
        self.request_id = request_id

    def _audit(
        self,
        *,
        account_id: int,
        action_code: str,
        entity_type: str,
        entity_pk: int,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        occurred_at_utc: datetime | None = None,
    ) -> None:
        self.repository.add(
            AuditEvent(
                occurred_at_utc=occurred_at_utc or _now(),
                actor_account_id=account_id,
                actor_kind="USER",
                action_code=action_code,
                entity_type=entity_type,
                entity_pk=entity_pk,
                before_json=before,
                after_json=after,
                request_id=self.request_id,
                created_from="API",
            )
        )

    @staticmethod
    def _map_integrity_error(error: IntegrityError) -> RecipientDomainError:
        original = getattr(error, "orig", None)
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        if constraint_name == "ex_recipient_guardian_primary_period":
            return _domain_error("PRIMARY_GUARDIAN_PERIOD_CONFLICT", 409)
        if constraint_name == "ex_recipient_payer_snapshot_period":
            return _domain_error("CURRENT_PAYER_CONFLICT", 409)
        # Composite same-recipient FK / missing guardian target.
        if constraint_name in {
            "fk_recipient_payer_guardian_same_recipient",
            "fk_recipient_payer_guardian_same_recipient_fkey",
        }:
            return _domain_error("RECIPIENT_GUARDIAN_NOT_FOUND", 404)
        return _domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _flush(self) -> None:
        try:
            self.repository.flush()
        except IntegrityError as exc:
            self.database_session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.database_session.rollback()
            raise _domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _commit(self) -> None:
        if self.database_session.info.get("recipient_detail_batch_defer_commit"):
            self.database_session.flush()
            return
        try:
            self.database_session.commit()
        except IntegrityError as exc:
            self.database_session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.database_session.rollback()
            raise _domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    @staticmethod
    def _require_version(actual: int, expected: int, *, entity: str) -> None:
        if actual != expected:
            raise _domain_error(
                "ROW_VERSION_CONFLICT",
                409,
                details={"current_row_version": actual, "entity": entity},
            )

    def _require_recipient(
        self,
        recipient_id: int,
        *,
        for_update: bool = False,
    ) -> Recipient:
        recipient = self.repository.get_recipient(recipient_id, for_update=for_update)
        if recipient is None:
            raise _domain_error("RECIPIENT_NOT_FOUND", 404)
        return recipient

    def _require_guardian(
        self,
        recipient_id: int,
        guardian_id: int,
        *,
        for_update: bool = False,
    ) -> RecipientGuardian:
        guardian = self.repository.get_guardian(
            recipient_id,
            guardian_id,
            for_update=for_update,
        )
        if guardian is None:
            raise _domain_error("RECIPIENT_GUARDIAN_NOT_FOUND", 404)
        return guardian

    def _require_primary_period(
        self,
        recipient_id: int,
        period_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientGuardianPrimaryPeriod:
        period = self.repository.get_primary_period(
            recipient_id,
            period_id,
            for_update=for_update,
            active_only=active_only,
        )
        if period is None:
            historical = self.repository.get_primary_period(recipient_id, period_id)
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "primary_guardian_period",
                    },
                )
            raise _domain_error("PRIMARY_GUARDIAN_PERIOD_NOT_FOUND", 404)
        return period

    def _require_payer_snapshot(
        self,
        recipient_id: int,
        snapshot_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientPayerSnapshot:
        snapshot = self.repository.get_payer_snapshot(
            recipient_id,
            snapshot_id,
            for_update=for_update,
            active_only=active_only,
        )
        if snapshot is None:
            historical = self.repository.get_payer_snapshot(recipient_id, snapshot_id)
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "payer_snapshot",
                    },
                )
            raise _domain_error("PAYER_SNAPSHOT_NOT_FOUND", 404)
        return snapshot

    @staticmethod
    def _recipient_response(recipient: Recipient) -> RecipientResponse:
        return RecipientResponse(
            id=recipient.id,
            name=recipient.name,
            birth_date=recipient.birth_date,
            sex_code=RecipientSexCode(recipient.sex_code),
            recipient_status=RecipientStatus(recipient.recipient_status),
            recipient_no=recipient.recipient_no,
            postal_code=recipient.postal_code,
            address=recipient.address,
            home_phone=recipient.home_phone,
            mobile_phone=recipient.mobile_phone,
            memo=recipient.memo,
            payer_guardian_id=recipient.payer_guardian_id,
            row_version=recipient.row_version,
        )

    @staticmethod
    def _build_service_groups(
        raw_services: list[tuple[str, str, str, str]],
    ) -> list[RecipientListServiceGroupItem]:
        """Group and order current services by frozen catalog order.

        raw_services: (group_code, group_name, type_code, type_name), already unique.
        """
        if not raw_services:
            return []
        by_group: dict[str, tuple[str, list[RecipientListServiceTypeItem]]] = {}
        type_rank = {
            type_code: index
            for type_codes in SERVICE_TYPE_ORDER_BY_GROUP.values()
            for index, type_code in enumerate(type_codes)
        }
        for group_code, group_name, type_code, type_name in raw_services:
            if group_code not in by_group:
                by_group[group_code] = (group_name, [])
            by_group[group_code][1].append(
                RecipientListServiceTypeItem(
                    service_type_code=type_code,
                    display_name=type_name,
                )
            )
        groups: list[RecipientListServiceGroupItem] = []
        ordered_group_codes = sorted(
            by_group.keys(),
            key=lambda code: (
                SERVICE_GROUP_ORDER.index(code) if code in SERVICE_GROUP_ORDER else 999,
                code,
            ),
        )
        for group_code in ordered_group_codes:
            group_name, type_items = by_group[group_code]
            type_items_sorted = sorted(
                type_items,
                key=lambda item: (
                    type_rank.get(item.service_type_code, 999),
                    item.service_type_code,
                ),
            )
            groups.append(
                RecipientListServiceGroupItem(
                    service_group_code=group_code,
                    display_name=group_name,
                    service_types=type_items_sorted,
                )
            )
        return groups

    def _list_item_response(
        self,
        recipient: Recipient,
        *,
        grade_code: str | None,
        benefit_code: str | None,
        raw_services: list[tuple[str, str, str, str]],
    ) -> RecipientListItem:
        return RecipientListItem(
            id=recipient.id,
            name=recipient.name,
            birth_date=recipient.birth_date,
            sex_code=RecipientSexCode(recipient.sex_code),
            recipient_no=recipient.recipient_no,
            postal_code=recipient.postal_code,
            address=recipient.address,
            home_phone=recipient.home_phone,
            mobile_phone=recipient.mobile_phone,
            memo=recipient.memo,
            row_version=recipient.row_version,
            grade_code=grade_code,
            benefit_code=benefit_code,
            # W1C benefit ledger has benefit_code only; no numeric rate column.
            copayment_rate=None,
            services=self._build_service_groups(raw_services),
        )

    @staticmethod
    def _guardian_response(guardian: RecipientGuardian) -> GuardianResponse:
        return GuardianResponse(
            id=guardian.id,
            recipient_id=guardian.recipient_id,
            name=guardian.name,
            phone=guardian.phone,
            email=guardian.email,
            address=guardian.address,
            relationship_text=guardian.relationship_text,
            row_version=guardian.row_version,
        )

    @staticmethod
    def _primary_response(
        period: RecipientGuardianPrimaryPeriod,
    ) -> PrimaryGuardianPeriodResponse:
        return PrimaryGuardianPeriodResponse(
            id=period.id,
            recipient_id=period.recipient_id,
            guardian_id=period.guardian_id,
            start_date=period.start_date,
            end_date=period.end_date,
            invalidated_at_utc=period.invalidated_at_utc,
            replacement_primary_guardian_period_id=(period.replacement_primary_guardian_period_id),
            row_version=period.row_version,
        )

    @staticmethod
    def _payer_response(snapshot: RecipientPayerSnapshot) -> PayerSnapshotResponse:
        return PayerSnapshotResponse(
            id=snapshot.id,
            recipient_id=snapshot.recipient_id,
            name=snapshot.name,
            phone=snapshot.phone,
            address=snapshot.address,
            relationship_text=snapshot.relationship_text,
            start_date=snapshot.start_date,
            end_date=snapshot.end_date,
            invalidated_at_utc=snapshot.invalidated_at_utc,
            replacement_payer_snapshot_id=snapshot.replacement_payer_snapshot_id,
            row_version=snapshot.row_version,
        )

    def create_recipient(
        self,
        payload: RecipientCreateRequest,
        current_account: CurrentAccount,
    ) -> RecipientResponse:
        try:
            name = clean_required_text(payload.name)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="name") from None
        now = _now()
        recipient = Recipient(
            name=name,
            birth_date=payload.birth_date,
            sex_code=payload.sex_code.value,
            recipient_status=RecipientStatus.ACTIVE.value,
            recipient_no=None,
            postal_code=clean_optional_text(payload.postal_code),
            address=clean_optional_text(payload.address),
            home_phone=clean_optional_text(payload.home_phone),
            mobile_phone=clean_optional_text(payload.mobile_phone),
            memo=clean_optional_text(payload.memo),
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(recipient)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_CREATE",
            entity_type="RECIPIENT",
            entity_pk=recipient.id,
            before=None,
            after={
                "name": recipient.name,
                "birth_date": recipient.birth_date.isoformat(),
                "sex_code": recipient.sex_code,
                "row_version": recipient.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._recipient_response(recipient)

    def list_recipients(
        self,
        *,
        search: str | None,
        page: int,
        page_size: int,
        status: RecipientListStatusFilter | str = RecipientListStatusFilter.ALL,
    ) -> RecipientListResponse:
        """Read-only list. Uses Asia/Seoul today; never creates tasks/notifications."""
        as_of = today_seoul()
        status_value = (
            status.value if isinstance(status, RecipientListStatusFilter) else str(status)
        )
        items, total = self.repository.list_recipients(
            search=search,
            status=status_value,
            as_of=as_of,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        recipient_ids = [item.id for item in items]
        contracts_by_id = self.repository.load_effective_contracts_by_recipient(
            recipient_ids,
            as_of,
        )
        grades_by_id = self.repository.load_effective_grade_codes(recipient_ids, as_of)
        benefits_by_id = self.repository.load_effective_benefit_codes(recipient_ids, as_of)

        list_items: list[RecipientListItem] = []
        for item in items:
            raw_services = contracts_by_id.get(item.id, [])
            list_items.append(
                self._list_item_response(
                    item,
                    grade_code=grades_by_id.get(item.id),
                    benefit_code=benefits_by_id.get(item.id),
                    raw_services=raw_services,
                )
            )
        return RecipientListResponse(
            items=list_items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_recipient(self, recipient_id: int) -> RecipientResponse:
        return self._recipient_response(self._require_recipient(recipient_id))

    def update_recipient(
        self,
        recipient_id: int,
        payload: RecipientUpdateRequest,
        current_account: CurrentAccount,
    ) -> RecipientResponse:
        recipient = self._require_recipient(recipient_id, for_update=True)
        self._require_version(
            recipient.row_version,
            payload.expected_row_version,
            entity="recipient",
        )
        before_version = recipient.row_version
        before_payer_guardian_id = recipient.payer_guardian_id
        fields_set = payload.model_fields_set
        if "name" in fields_set:
            try:
                recipient.name = clean_required_text(payload.name or "")
            except ValueError:
                raise _domain_error("VALIDATION_ERROR", 422, field="name") from None
        if "birth_date" in fields_set:
            if payload.birth_date is None:
                raise _domain_error("VALIDATION_ERROR", 422, field="birth_date")
            recipient.birth_date = payload.birth_date
        if "sex_code" in fields_set:
            if payload.sex_code is None:
                raise _domain_error("VALIDATION_ERROR", 422, field="sex_code")
            recipient.sex_code = payload.sex_code.value
        if "recipient_status" in fields_set:
            if payload.recipient_status is None:
                raise _domain_error("VALIDATION_ERROR", 422, field="recipient_status")
            recipient.recipient_status = payload.recipient_status.value
        for field_name in ("postal_code", "address", "home_phone", "mobile_phone", "memo"):
            if field_name in fields_set:
                setattr(
                    recipient,
                    field_name,
                    clean_optional_text(getattr(payload, field_name)),
                )
        # omit = unchanged; explicit null = self; positive id = same-recipient guardian.
        if "payer_guardian_id" in fields_set:
            if payload.payer_guardian_id is None:
                recipient.payer_guardian_id = None
            else:
                # Domain-controlled check before DB: reject missing / cross-recipient guardian.
                self._require_guardian(recipient_id, payload.payer_guardian_id)
                recipient.payer_guardian_id = payload.payer_guardian_id
        now = _now()
        recipient.updated_by_account_id = current_account.id
        recipient.updated_at_utc = now
        recipient.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_UPDATE",
            entity_type="RECIPIENT",
            entity_pk=recipient.id,
            before={
                "row_version": before_version,
                "payer_guardian_id": before_payer_guardian_id,
            },
            after={
                "row_version": recipient.row_version,
                "payer_guardian_id": recipient.payer_guardian_id,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._recipient_response(recipient)

    def create_guardian(
        self,
        recipient_id: int,
        payload: GuardianCreateRequest,
        current_account: CurrentAccount,
    ) -> GuardianResponse:
        self._require_recipient(recipient_id)
        try:
            name = clean_required_text(payload.name)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="name") from None
        now = _now()
        guardian = RecipientGuardian(
            recipient_id=recipient_id,
            name=name,
            phone=clean_optional_text(payload.phone),
            email=clean_optional_text(payload.email),
            address=clean_optional_text(payload.address),
            relationship_text=clean_optional_text(payload.relationship_text),
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(guardian)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_GUARDIAN_CREATE",
            entity_type="RECIPIENT_GUARDIAN",
            entity_pk=guardian.id,
            before=None,
            after={"row_version": guardian.row_version},
            occurred_at_utc=now,
        )
        self._commit()
        return self._guardian_response(guardian)

    def list_guardians(self, recipient_id: int) -> GuardianListResponse:
        self._require_recipient(recipient_id)
        return GuardianListResponse(
            items=[
                self._guardian_response(guardian)
                for guardian in self.repository.list_guardians(recipient_id)
            ]
        )

    def get_guardian(self, recipient_id: int, guardian_id: int) -> GuardianResponse:
        return self._guardian_response(self._require_guardian(recipient_id, guardian_id))

    def update_guardian(
        self,
        recipient_id: int,
        guardian_id: int,
        payload: GuardianUpdateRequest,
        current_account: CurrentAccount,
    ) -> GuardianResponse:
        guardian = self._require_guardian(recipient_id, guardian_id, for_update=True)
        self._require_version(
            guardian.row_version,
            payload.expected_row_version,
            entity="guardian",
        )
        before_version = guardian.row_version
        fields_set = payload.model_fields_set
        if "name" in fields_set:
            try:
                guardian.name = clean_required_text(payload.name or "")
            except ValueError:
                raise _domain_error("VALIDATION_ERROR", 422, field="name") from None
        for field_name in ("phone", "email", "address", "relationship_text"):
            if field_name in fields_set:
                setattr(
                    guardian,
                    field_name,
                    clean_optional_text(getattr(payload, field_name)),
                )
        now = _now()
        guardian.updated_by_account_id = current_account.id
        guardian.updated_at_utc = now
        guardian.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_GUARDIAN_UPDATE",
            entity_type="RECIPIENT_GUARDIAN",
            entity_pk=guardian.id,
            before={"row_version": before_version},
            after={"row_version": guardian.row_version},
            occurred_at_utc=now,
        )
        self._commit()
        return self._guardian_response(guardian)

    def create_primary_period(
        self,
        recipient_id: int,
        payload: PrimaryGuardianPeriodCreateRequest,
        current_account: CurrentAccount,
    ) -> PrimaryGuardianPeriodResponse:
        self._require_recipient(recipient_id)
        self._require_guardian(recipient_id, payload.guardian_id)
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        now = _now()
        period = RecipientGuardianPrimaryPeriod(
            recipient_id=recipient_id,
            guardian_id=payload.guardian_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(period)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_CREATE",
            entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
            entity_pk=period.id,
            before=None,
            after={
                "guardian_id": period.guardian_id,
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat() if period.end_date else None,
                "row_version": period.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._primary_response(period)

    def list_primary_periods(self, recipient_id: int) -> PrimaryGuardianPeriodListResponse:
        self._require_recipient(recipient_id)
        return PrimaryGuardianPeriodListResponse(
            items=[
                self._primary_response(period)
                for period in self.repository.list_primary_periods(recipient_id)
            ]
        )

    def get_primary_period(
        self,
        recipient_id: int,
        period_id: int,
    ) -> PrimaryGuardianPeriodResponse:
        return self._primary_response(self._require_primary_period(recipient_id, period_id))

    def invalidate_primary_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: HistoryInvalidateRequest,
        current_account: CurrentAccount,
    ) -> PrimaryGuardianPeriodResponse:
        period = self._require_primary_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            period.row_version,
            payload.expected_row_version,
            entity="primary_guardian_period",
        )
        before_version = period.row_version
        now = _now()
        period.invalidated_at_utc = now
        period.updated_by_account_id = current_account.id
        period.updated_at_utc = now
        period.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_INVALIDATE",
            entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
            entity_pk=period.id,
            before={"row_version": before_version},
            after={
                "invalidated_at_utc": now.isoformat(),
                "row_version": period.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._primary_response(period)

    def replace_primary_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: PrimaryGuardianPeriodReplacementRequest,
        current_account: CurrentAccount,
    ) -> PrimaryGuardianPeriodReplacementResponse:
        old = self._require_primary_period(
            recipient_id,
            period_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            old.row_version,
            payload.expected_row_version,
            entity="primary_guardian_period",
        )
        self._require_guardian(recipient_id, payload.guardian_id)
        try:
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="end_date") from None
        before_version = old.row_version
        now = _now()
        old.invalidated_at_utc = now
        old.updated_by_account_id = current_account.id
        old.updated_at_utc = now
        old.row_version += 1
        self._flush()
        replacement = RecipientGuardianPrimaryPeriod(
            recipient_id=recipient_id,
            guardian_id=payload.guardian_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
            row_version=1,
        )
        self.repository.add(replacement)
        self._flush()
        old.replacement_primary_guardian_period_id = replacement.id
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_INVALIDATE",
            entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
            entity_pk=old.id,
            before={"row_version": before_version},
            after={
                "replacement_primary_guardian_period_id": replacement.id,
                "row_version": old.row_version,
            },
            occurred_at_utc=now,
        )
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
            entity_pk=replacement.id,
            before=None,
            after={
                "guardian_id": replacement.guardian_id,
                "start_date": replacement.start_date.isoformat(),
                "end_date": (replacement.end_date.isoformat() if replacement.end_date else None),
                "row_version": replacement.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return PrimaryGuardianPeriodReplacementResponse(
            original=self._primary_response(old),
            replacement=self._primary_response(replacement),
        )

    def create_payer_snapshot(
        self,
        recipient_id: int,
        payload: PayerSnapshotCreateRequest,
        current_account: CurrentAccount,
    ) -> PayerSnapshotResponse:
        self._require_recipient(recipient_id)
        try:
            name = clean_required_text(payload.name)
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422) from None
        now = _now()
        snapshot = RecipientPayerSnapshot(
            recipient_id=recipient_id,
            name=name,
            phone=clean_optional_text(payload.phone),
            address=clean_optional_text(payload.address),
            relationship_text=clean_optional_text(payload.relationship_text),
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(snapshot)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_PAYER_SNAPSHOT_CREATE",
            entity_type="RECIPIENT_PAYER_SNAPSHOT",
            entity_pk=snapshot.id,
            before=None,
            after={
                "name": snapshot.name,
                "start_date": snapshot.start_date.isoformat(),
                "end_date": snapshot.end_date.isoformat() if snapshot.end_date else None,
                "row_version": snapshot.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._payer_response(snapshot)

    def list_payer_snapshots(self, recipient_id: int) -> PayerSnapshotListResponse:
        self._require_recipient(recipient_id)
        return PayerSnapshotListResponse(
            items=[
                self._payer_response(snapshot)
                for snapshot in self.repository.list_payer_snapshots(recipient_id)
            ]
        )

    def get_payer_snapshot(
        self,
        recipient_id: int,
        snapshot_id: int,
    ) -> PayerSnapshotResponse:
        return self._payer_response(self._require_payer_snapshot(recipient_id, snapshot_id))

    def invalidate_payer_snapshot(
        self,
        recipient_id: int,
        snapshot_id: int,
        payload: HistoryInvalidateRequest,
        current_account: CurrentAccount,
    ) -> PayerSnapshotResponse:
        snapshot = self._require_payer_snapshot(
            recipient_id,
            snapshot_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            snapshot.row_version,
            payload.expected_row_version,
            entity="payer_snapshot",
        )
        before_version = snapshot.row_version
        now = _now()
        snapshot.invalidated_at_utc = now
        snapshot.updated_by_account_id = current_account.id
        snapshot.updated_at_utc = now
        snapshot.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_PAYER_SNAPSHOT_INVALIDATE",
            entity_type="RECIPIENT_PAYER_SNAPSHOT",
            entity_pk=snapshot.id,
            before={"row_version": before_version},
            after={
                "invalidated_at_utc": now.isoformat(),
                "row_version": snapshot.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._payer_response(snapshot)

    def replace_payer_snapshot(
        self,
        recipient_id: int,
        snapshot_id: int,
        payload: PayerSnapshotReplacementRequest,
        current_account: CurrentAccount,
    ) -> PayerSnapshotReplacementResponse:
        old = self._require_payer_snapshot(
            recipient_id,
            snapshot_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            old.row_version,
            payload.expected_row_version,
            entity="payer_snapshot",
        )
        try:
            name = clean_required_text(payload.name)
            validate_period(payload.start_date, payload.end_date)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422) from None
        before_version = old.row_version
        now = _now()
        old.invalidated_at_utc = now
        old.updated_by_account_id = current_account.id
        old.updated_at_utc = now
        old.row_version += 1
        self._flush()
        replacement = RecipientPayerSnapshot(
            recipient_id=recipient_id,
            name=name,
            phone=clean_optional_text(payload.phone),
            address=clean_optional_text(payload.address),
            relationship_text=clean_optional_text(payload.relationship_text),
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
            row_version=1,
        )
        self.repository.add(replacement)
        self._flush()
        old.replacement_payer_snapshot_id = replacement.id
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_PAYER_SNAPSHOT_INVALIDATE",
            entity_type="RECIPIENT_PAYER_SNAPSHOT",
            entity_pk=old.id,
            before={"row_version": before_version},
            after={
                "replacement_payer_snapshot_id": replacement.id,
                "row_version": old.row_version,
            },
            occurred_at_utc=now,
        )
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_PAYER_SNAPSHOT_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_PAYER_SNAPSHOT",
            entity_pk=replacement.id,
            before=None,
            after={
                "name": replacement.name,
                "phone": replacement.phone,
                "address": replacement.address,
                "relationship_text": replacement.relationship_text,
                "start_date": replacement.start_date.isoformat(),
                "end_date": (replacement.end_date.isoformat() if replacement.end_date else None),
                "row_version": replacement.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return PayerSnapshotReplacementResponse(
            original=self._payer_response(old),
            replacement=self._payer_response(replacement),
        )

    def _require_plan_notification(
        self,
        recipient_id: int,
        notification_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> RecipientPlanNotification:
        notification = self.repository.get_plan_notification(
            recipient_id,
            notification_id,
            for_update=for_update,
            active_only=active_only,
        )
        if notification is None:
            historical = self.repository.get_plan_notification(
                recipient_id,
                notification_id,
            )
            if active_only and historical is not None:
                raise _domain_error(
                    "ROW_VERSION_CONFLICT",
                    409,
                    details={
                        "current_row_version": historical.row_version,
                        "entity": "plan_notification",
                    },
                )
            raise _domain_error("RECIPIENT_PLAN_NOTIFICATION_NOT_FOUND", 404)
        return notification

    @staticmethod
    def _plan_notification_response(
        notification: RecipientPlanNotification,
    ) -> PlanNotificationResponse:
        return PlanNotificationResponse(
            id=notification.id,
            recipient_id=notification.recipient_id,
            notified_date=notification.notified_date,
            invalidated_at_utc=notification.invalidated_at_utc,
            row_version=notification.row_version,
        )

    def create_plan_notification(
        self,
        recipient_id: int,
        payload: PlanNotificationCreateRequest,
        current_account: CurrentAccount,
    ) -> PlanNotificationResponse:
        self._require_recipient(recipient_id)
        now = _now()
        notification = RecipientPlanNotification(
            recipient_id=recipient_id,
            notified_date=payload.notified_date,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
        )
        self.repository.add(notification)
        self._flush()
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_PLAN_NOTIFICATION_CREATE",
            entity_type="RECIPIENT_PLAN_NOTIFICATION",
            entity_pk=notification.id,
            before=None,
            after={
                "notified_date": notification.notified_date.isoformat(),
                "row_version": notification.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._plan_notification_response(notification)

    def list_plan_notifications(
        self,
        recipient_id: int,
    ) -> PlanNotificationListResponse:
        self._require_recipient(recipient_id)
        return PlanNotificationListResponse(
            items=[
                self._plan_notification_response(notification)
                for notification in self.repository.list_plan_notifications(recipient_id)
            ]
        )

    def invalidate_plan_notification(
        self,
        recipient_id: int,
        notification_id: int,
        payload: HistoryInvalidateRequest,
        current_account: CurrentAccount,
    ) -> PlanNotificationResponse:
        notification = self._require_plan_notification(
            recipient_id,
            notification_id,
            for_update=True,
            active_only=True,
        )
        self._require_version(
            notification.row_version,
            payload.expected_row_version,
            entity="plan_notification",
        )
        before_version = notification.row_version
        now = _now()
        notification.invalidated_at_utc = now
        notification.updated_by_account_id = current_account.id
        notification.updated_at_utc = now
        notification.row_version += 1
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_PLAN_NOTIFICATION_INVALIDATE",
            entity_type="RECIPIENT_PLAN_NOTIFICATION",
            entity_pk=notification.id,
            before={"row_version": before_version},
            after={
                "invalidated_at_utc": now.isoformat(),
                "row_version": notification.row_version,
            },
            occurred_at_utc=now,
        )
        self._commit()
        return self._plan_notification_response(notification)

    def list_recipient_deadlines(self) -> RecipientDeadlineListResponse:
        certification_rows = self.database_session.execute(
            select(
                RecipientCertificationPeriod.id,
                RecipientCertificationPeriod.recipient_id,
                RecipientCertificationPeriod.end_date,
                Recipient.name,
            )
            .join(Recipient, Recipient.id == RecipientCertificationPeriod.recipient_id)
            .where(
                RecipientCertificationPeriod.invalidated_at_utc.is_(None),
                RecipientCertificationPeriod.replacement_certification_period_id.is_(None),
            )
        ).all()

        contract_rows = self.database_session.execute(
            select(
                RecipientContract.id,
                RecipientContract.recipient_id,
                RecipientContract.end_date,
                Recipient.name,
            )
            .join(Recipient, Recipient.id == RecipientContract.recipient_id)
            .where(
                RecipientContract.invalidated_at_utc.is_(None),
                RecipientContract.replacement_contract_id.is_(None),
                RecipientContract.end_date.is_not(None),
            )
        ).all()

        plan_rows = self.database_session.execute(
            select(
                RecipientPlanNotification.id,
                RecipientPlanNotification.recipient_id,
                RecipientPlanNotification.notified_date,
                Recipient.name,
            )
            .join(Recipient, Recipient.id == RecipientPlanNotification.recipient_id)
            .where(RecipientPlanNotification.invalidated_at_utc.is_(None))
            .order_by(
                RecipientPlanNotification.recipient_id,
                RecipientPlanNotification.notified_date.desc(),
                RecipientPlanNotification.id.desc(),
            )
        ).all()

        items: list[RecipientDeadlineItem] = []
        for certification_row in certification_rows:
            items.append(
                RecipientDeadlineItem(
                    recipient_id=certification_row.recipient_id,
                    recipient_name=certification_row.name,
                    kind=RecipientDeadlineKind.CERTIFICATION_EXPIRY,
                    source_id=certification_row.id,
                    source_date=certification_row.end_date,
                    due_date=certification_row.end_date,
                )
            )
        for contract_row in contract_rows:
            items.append(
                RecipientDeadlineItem(
                    recipient_id=contract_row.recipient_id,
                    recipient_name=contract_row.name,
                    kind=RecipientDeadlineKind.CONTRACT_EXPIRY,
                    source_id=contract_row.id,
                    source_date=contract_row.end_date,
                    due_date=contract_row.end_date,
                )
            )
        seen_recipient_ids: set[int] = set()
        for plan_row in plan_rows:
            if plan_row.recipient_id in seen_recipient_ids:
                continue
            seen_recipient_ids.add(plan_row.recipient_id)
            items.append(
                RecipientDeadlineItem(
                    recipient_id=plan_row.recipient_id,
                    recipient_name=plan_row.name,
                    kind=RecipientDeadlineKind.PLAN_RENEWAL,
                    source_id=plan_row.id,
                    source_date=plan_row.notified_date,
                    due_date=_plan_renewal_due_date(plan_row.notified_date),
                )
            )
        items.sort(
            key=lambda item: (
                item.recipient_id,
                item.kind.value,
                item.due_date,
                item.source_id,
            )
        )
        return RecipientDeadlineListResponse(items=items)
