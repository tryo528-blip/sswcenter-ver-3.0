from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.db.models import (
    AuditEvent,
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationPeriod,
    RecipientContract,
    RecipientGuardian,
)
from app.db.w2_models import W2ServicePlanNotice
from app.domains.recipient.errors import RecipientDomainError
from app.domains.recipient.policies import clean_optional_text, clean_required_text
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
    RecipientSexCodeRead,
    RecipientStatus,
    RecipientUpdateRequest,
)
from app.domains.recipient.service_plan_notice import deadline_date

_SEOUL = ZoneInfo("Asia/Seoul")
_TodayFn = Callable[[], date]
_today_override: _TodayFn | None = None


def set_today_seoul(fn: _TodayFn | None) -> None:
    global _today_override
    _today_override = fn


def today_seoul() -> date:
    if _today_override is not None:
        return _today_override()
    return datetime.now(_SEOUL).date()


_MESSAGES = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "RECIPIENT_GUARDIAN_NOT_FOUND": "보호자를 찾을 수 없습니다.",
    "RECIPIENT_GUARDIAN_LIMIT_REACHED": "보호자는 최대 두 명까지 등록할 수 있습니다.",
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.",
    "VALIDATION_ERROR": "입력값을 확인하세요.",
    "UNEXPECTED_SERVER_ERROR": "요청을 처리하지 못했습니다.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _read_sex_code(value: str | None) -> RecipientSexCodeRead | None:
    if value is None:
        return None
    return RecipientSexCodeRead(value)


def _iso_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


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
        if constraint_name == "ck_recipient_guardian_max_two":
            return _domain_error("RECIPIENT_GUARDIAN_LIMIT_REACHED", 409)
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

    @staticmethod
    def _recipient_response(recipient: Recipient) -> RecipientResponse:
        return RecipientResponse(
            id=recipient.id,
            name=recipient.name,
            birth_date=recipient.birth_date,
            sex_code=_read_sex_code(recipient.sex_code),
            recipient_status=RecipientStatus(recipient.recipient_status),
            recipient_no=recipient.recipient_no,
            postal_code=recipient.postal_code,
            address=recipient.address,
            mobile_phone=recipient.mobile_phone,
            memo=recipient.memo,
            payer_guardian_id=recipient.payer_guardian_id,
            row_version=recipient.row_version,
        )

    @staticmethod
    def _guardian_response(guardian: RecipientGuardian) -> GuardianResponse:
        if guardian.slot_no not in (1, 2):
            raise ValueError("recipient guardian slot is outside the database contract")
        return GuardianResponse(
            id=guardian.id,
            recipient_id=guardian.recipient_id,
            slot_no=cast(Literal[1, 2], guardian.slot_no),
            name=guardian.name,
            phone=guardian.phone,
            email=guardian.email,
            address=guardian.address,
            relationship_text=guardian.relationship_text,
            row_version=guardian.row_version,
        )

    @staticmethod
    def _build_service_groups(
        raw_services: list[tuple[str, str, str, str]],
    ) -> list[RecipientListServiceGroupItem]:
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
        for group_code in sorted(
            by_group,
            key=lambda code: (
                SERVICE_GROUP_ORDER.index(code) if code in SERVICE_GROUP_ORDER else 999,
                code,
            ),
        ):
            group_name, type_items = by_group[group_code]
            groups.append(
                RecipientListServiceGroupItem(
                    service_group_code=group_code,
                    display_name=group_name,
                    service_types=sorted(
                        type_items,
                        key=lambda item: (
                            type_rank.get(item.service_type_code, 999),
                            item.service_type_code,
                        ),
                    ),
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
            sex_code=_read_sex_code(recipient.sex_code),
            recipient_no=recipient.recipient_no,
            postal_code=recipient.postal_code,
            address=recipient.address,
            mobile_phone=recipient.mobile_phone,
            memo=recipient.memo,
            row_version=recipient.row_version,
            grade_code=grade_code,
            benefit_code=benefit_code,
            copayment_rate=None,
            services=self._build_service_groups(raw_services),
        )

    def create_recipient(
        self,
        payload: RecipientCreateRequest,
        current_account: CurrentAccount,
    ) -> RecipientResponse:
        try:
            mobile_phone = clean_required_text(payload.mobile_phone)
        except ValueError:
            raise _domain_error("VALIDATION_ERROR", 422, field="mobile_phone") from None

        now = _now()
        recipient = Recipient(
            name=clean_optional_text(payload.name),
            birth_date=payload.birth_date,
            sex_code=payload.sex_code.value if payload.sex_code is not None else None,
            recipient_status=RecipientStatus.ACTIVE.value,
            recipient_no=None,
            postal_code=clean_optional_text(payload.postal_code),
            address=clean_optional_text(payload.address),
            mobile_phone=mobile_phone,
            memo=clean_optional_text(payload.memo),
            payer_guardian_id=None,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
            row_version=1,
        )
        self.repository.add(recipient)
        self._flush()

        general_benefit = RecipientBenefitPeriod(
            recipient_id=recipient.id,
            benefit_code="GENERAL",
            start_text="",
            invalidated_at_utc=None,
            replacement_benefit_period_id=None,
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
            row_version=1,
        )
        self.repository.add(general_benefit)
        self._flush()

        birth_date_value = _iso_date(recipient.birth_date)
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_CREATE",
            entity_type="RECIPIENT",
            entity_pk=recipient.id,
            before=None,
            after={
                "name": recipient.name,
                "birth_date": birth_date_value,
                "sex_code": recipient.sex_code,
                "mobile_phone": recipient.mobile_phone,
                "row_version": recipient.row_version,
            },
            occurred_at_utc=now,
        )
        self._audit(
            account_id=current_account.id,
            action_code="RECIPIENT_BENEFIT_CREATE",
            entity_type="RECIPIENT_BENEFIT_PERIOD",
            entity_pk=general_benefit.id,
            before=None,
            after={
                "benefit_code": "GENERAL",
                "start_text": "",
                "row_version": general_benefit.row_version,
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
        return RecipientListResponse(
            items=[
                self._list_item_response(
                    item,
                    grade_code=grades_by_id.get(item.id),
                    benefit_code=benefits_by_id.get(item.id),
                    raw_services=contracts_by_id.get(item.id, []),
                )
                for item in items
            ],
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
            recipient.name = clean_optional_text(payload.name)
        if "birth_date" in fields_set:
            recipient.birth_date = payload.birth_date
        if "sex_code" in fields_set:
            recipient.sex_code = payload.sex_code.value if payload.sex_code is not None else None
        if "recipient_status" in fields_set:
            if payload.recipient_status is None:
                raise _domain_error("VALIDATION_ERROR", 422, field="recipient_status")
            recipient.recipient_status = payload.recipient_status.value
        for field_name in ("postal_code", "address", "memo"):
            if field_name in fields_set:
                setattr(
                    recipient,
                    field_name,
                    clean_optional_text(getattr(payload, field_name)),
                )
        if "mobile_phone" in fields_set:
            try:
                recipient.mobile_phone = clean_required_text(payload.mobile_phone or "")
            except ValueError:
                raise _domain_error("VALIDATION_ERROR", 422, field="mobile_phone") from None
        if "payer_guardian_id" in fields_set:
            if payload.payer_guardian_id is None:
                recipient.payer_guardian_id = None
            else:
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
        *,
        slot_no: int | None = None,
    ) -> GuardianResponse:
        self._require_recipient(recipient_id, for_update=True)
        occupied_slots = {
            guardian.slot_no for guardian in self.repository.list_guardians(recipient_id)
        }
        if slot_no is None:
            slot_no = next((value for value in (1, 2) if value not in occupied_slots), None)
        if slot_no not in {1, 2} or slot_no in occupied_slots:
            raise _domain_error("RECIPIENT_GUARDIAN_LIMIT_REACHED", 409)
        now = _now()
        guardian = RecipientGuardian(
            recipient_id=recipient_id,
            slot_no=slot_no,
            name=clean_optional_text(payload.name),
            phone=clean_optional_text(payload.phone),
            email=clean_optional_text(payload.email),
            address=clean_optional_text(payload.address),
            relationship_text=clean_optional_text(payload.relationship_text),
            created_by_account_id=current_account.id,
            created_at_utc=now,
            updated_by_account_id=current_account.id,
            updated_at_utc=now,
            row_version=1,
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
            guardian.name = clean_optional_text(payload.name)
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

    def list_recipient_deadlines(self) -> RecipientDeadlineListResponse:
        certification_rows = self.database_session.execute(
            select(
                RecipientCertificationPeriod.id,
                RecipientCertificationPeriod.recipient_id,
                RecipientCertificationPeriod.start_date,
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
                W2ServicePlanNotice.id,
                RecipientContract.recipient_id,
                W2ServicePlanNotice.notification_date,
                W2ServicePlanNotice.applied_start_date,
                W2ServicePlanNotice.applied_end_date,
                RecipientContract.end_date.label("contract_end_date"),
                Recipient.name,
            )
            .join(
                RecipientContract,
                RecipientContract.id == W2ServicePlanNotice.recipient_contract_id,
            )
            .join(Recipient, Recipient.id == RecipientContract.recipient_id)
            .where(
                W2ServicePlanNotice.invalidated_at_utc.is_(None),
                RecipientContract.invalidated_at_utc.is_(None),
                RecipientContract.replacement_contract_id.is_(None),
            )
            .order_by(
                RecipientContract.recipient_id,
                W2ServicePlanNotice.notification_date.desc(),
                W2ServicePlanNotice.id.desc(),
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
            certification = next(
                (
                    item
                    for item in certification_rows
                    if item.recipient_id == plan_row.recipient_id
                    and item.start_date <= plan_row.applied_start_date
                    and item.end_date >= plan_row.applied_end_date
                ),
                None,
            )
            if certification is None:
                continue
            seen_recipient_ids.add(plan_row.recipient_id)
            items.append(
                RecipientDeadlineItem(
                    recipient_id=plan_row.recipient_id,
                    recipient_name=plan_row.name,
                    kind=RecipientDeadlineKind.PLAN_RENEWAL,
                    source_id=plan_row.id,
                    source_date=plan_row.notification_date,
                    due_date=deadline_date(
                        plan_row.notification_date,
                        contract_end_date=plan_row.contract_end_date,
                        certification_end_date=certification.end_date,
                    ),
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
