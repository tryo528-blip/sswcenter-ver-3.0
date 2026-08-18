"""Transactional FILE_ONLY W3 workspace service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from hashlib import sha256
from pathlib import PurePath
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.core.settings import Settings
from app.db.models import AuditEvent
from app.db.w2_models import W2Schedule, W2ScheduleMonthControl
from app.db.w3_models import (
    W3ActualWorkRevision,
    W3ApplyControl,
    W3ImportAttempt,
    W3ImportRun,
    W3ImportRunEvent,
    W3ManualSupplementEvent,
    W3MatchDecision,
    W3NhisGroup,
    W3NhisGroupMember,
    W3NormalizedNhisRow,
    W3NormalizedRfidRow,
    W3PlanAdjustmentEvent,
    W3PrivateContent,
    W3SourceReceipt,
    W3SourceRow,
    W3SourceSnapshot,
)
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w3.errors import domain_error
from app.domains.w3.matching import (
    MatchRequest,
    ScheduleMatchCandidate,
    StableStaffMappingCandidate,
    match_unique_schedule,
)
from app.domains.w3.matching_repository import W3MatchingRepository, W3TypedLink
from app.domains.w3.nhis_grouping import NhisDerivedGroup, derive_nhis_groups
from app.domains.w3.plan_adjustment import (
    PlanAdjustmentInput,
    ProposalStatus,
    propose_plan_adjustment,
)
from app.domains.w3.private_storage import W3PrivateStorage
from app.domains.w3.reconciliation import (
    AppliedFact,
    CandidateFact,
    ReconciliationInput,
    ReconciliationStatus,
    plan_snapshot_reconciliation,
)
from app.domains.w3.schemas import (
    W3ActiveSnapshot,
    W3ApplyRequest,
    W3ConfirmRequest,
    W3DecisionItem,
    W3MatchStatus,
    W3PlanAdjustmentRequest,
    W3PlanAdjustmentResponse,
    W3ResolveDecisionRequest,
    W3RunCounts,
    W3RunStatus,
    W3RunSummary,
    W3SourceType,
    W3SupplementAction,
    W3SupplementRequest,
    W3SupplementResponse,
    W3WorkspaceResponse,
)
from app.domains.w3.supplement import (
    SupplementAction,
    SupplementCommand,
    SupplementResult,
    plan_manual_supplement,
)
from app.domains.w3.workbook_parser import (
    MAX_COMPRESSED_BYTES,
    NHIS_SCHEDULE_PROFILE_V1,
    RFID_PROFILE_V1,
    NhisScheduleRow,
    ParsedWorkbook,
    RawSourceRow,
    RfidRow,
    WorkbookParseBlocked,
    parse_nhis_schedule_workbook,
    parse_rfid_workbook,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return str(value)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _safe_filename(value: str | None) -> str:
    if value is None or not value or value != value.strip() or len(value) > 255:
        raise domain_error("W3_INVALID_FILE", 422, field="file")
    if "\x00" in value or "/" in value or "\\" in value or PurePath(value).name != value:
        raise domain_error("W3_INVALID_FILE", 422, field="file")
    if not value.casefold().endswith(".xlsx"):
        raise domain_error("W3_INVALID_FILE", 422, field="file")
    return value


def _typed_payload(link: W3TypedLink) -> dict[str, int | None]:
    return {
        "recipient_id": link.recipient_id,
        "certification_period_id": link.certification_period_id,
        "staff_id": link.staff_id,
        "employment_id": link.employment_id,
        "staff_legacy_mapping_id": link.staff_legacy_mapping_id,
        "service_type_id": link.service_type_id,
        "recipient_contract_id": link.recipient_contract_id,
        "care_assignment_id": link.care_assignment_id,
        "w2_schedule_id": link.w2_schedule_id,
    }


class W3Service:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.request_id = request_id
        self.matching_repository = W3MatchingRepository(session)

    def _rollback_and_raise(self, error: Exception) -> None:
        self.session.rollback()
        if isinstance(error, RecipientDomainError):
            raise error
        if isinstance(error, IntegrityError):
            raise domain_error("W3_TYPED_LINK_INVALID", 422) from error
        if isinstance(error, SQLAlchemyError):
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from error
        raise error

    def _commit(self) -> None:
        try:
            self.session.commit()
        except Exception as error:
            self._rollback_and_raise(error)

    def _parse(
        self,
        *,
        content: bytes,
        source_type: W3SourceType,
        target_date: date,
        original_filename: str,
    ) -> ParsedWorkbook[NhisScheduleRow] | ParsedWorkbook[RfidRow]:
        try:
            if source_type is W3SourceType.NHIS_SCHEDULE:
                if target_date.day != 1:
                    raise domain_error("VALIDATION_ERROR", 422, field="target_date")
                return parse_nhis_schedule_workbook(
                    content,
                    target_month=target_date,
                    original_filename=original_filename,
                )
            return parse_rfid_workbook(
                content,
                target_date=target_date,
                original_filename=original_filename,
            )
        except WorkbookParseBlocked as error:
            raise domain_error(
                "W3_PARSE_BLOCKED",
                422,
                field="file",
                details={
                    "parser_code": error.code,
                    "source_row_number": error.source_row_number,
                    "column_name": error.column_name,
                    "business_write_count": 0,
                },
            ) from error

    def upload_workbook(
        self,
        *,
        content: bytes,
        original_filename: str | None,
        source_type: W3SourceType,
        target_date: date,
        account: CurrentAccount,
    ) -> W3WorkspaceResponse:
        filename = _safe_filename(original_filename)
        if not content or len(content) > MAX_COMPRESSED_BYTES:
            raise domain_error("W3_INVALID_FILE", 422, field="file")
        parsed = self._parse(
            content=content,
            source_type=source_type,
            target_date=target_date,
            original_filename=filename,
        )
        if self.settings.data_root is None:
            raise domain_error("W3_DATA_ROOT_REQUIRED", 503)
        try:
            stored = W3PrivateStorage(self.settings.data_root).store(content)
        except OSError as error:
            raise domain_error("W3_STORAGE_FAILURE", 500) from error

        try:
            content_row = self.session.scalar(
                select(W3PrivateContent).where(
                    W3PrivateContent.content_digest == stored.content_digest
                )
            )
            if content_row is None:
                content_row = W3PrivateContent(
                    content_digest=stored.content_digest,
                    byte_size=stored.byte_size,
                    media_type=XLSX_MEDIA_TYPE,
                    storage_locator=stored.storage_locator,
                    quarantine_state="NONE",
                    legal_hold_state="NONE",
                    automatic_gc_enabled=False,
                )
                self.session.add(content_row)
                self.session.flush()

            snapshot = self.session.scalar(
                select(W3SourceSnapshot).where(
                    W3SourceSnapshot.source_type == source_type.value,
                    W3SourceSnapshot.target_date == target_date,
                    W3SourceSnapshot.content_digest == stored.content_digest,
                )
            )
            if snapshot is None:
                snapshot = W3SourceSnapshot(
                    content_id=content_row.id,
                    source_type=source_type.value,
                    target_date=target_date,
                    content_digest=stored.content_digest,
                    status="CANDIDATE",
                )
                self.session.add(snapshot)
                self.session.flush()

            receipt = W3SourceReceipt(
                snapshot_id=snapshot.id,
                content_id=content_row.id,
                content_digest=stored.content_digest,
                original_filename=filename,
                actor_type="USER_ACCOUNT",
                actor_account_id=account.id,
                source_context_type=(
                    "NHIS_SCHEDULE_FILE"
                    if source_type is W3SourceType.NHIS_SCHEDULE
                    else "RFID_FILE"
                ),
            )
            self.session.add(receipt)
            self.session.flush()

            existing_run = self.session.scalar(
                select(W3ImportRun).where(
                    W3ImportRun.snapshot_id == snapshot.id,
                    W3ImportRun.parser_profile_version == parsed.profile_version,
                )
            )
            if existing_run is not None:
                self._append_attempt(existing_run, receipt, "SUCCEEDED")
                if existing_run.status == "BLOCKED":
                    self._commit()
                    latest = self.workspace(
                        source_type=source_type,
                        target_date=target_date,
                    )
                    raise domain_error(
                        "W3_RUN_STATE_INVALID",
                        409,
                        details={
                            "entity": "w3_import_run",
                            "run_id": existing_run.id,
                            "status": existing_run.status,
                            "current_row_version": existing_run.row_version,
                            "latest": latest.model_dump(mode="json"),
                        },
                    )
                self._commit()
                return self.workspace(source_type=source_type, target_date=target_date)

            run = W3ImportRun(
                receipt_id=receipt.id,
                snapshot_id=snapshot.id,
                content_id=content_row.id,
                content_digest=stored.content_digest,
                parser_profile_version=parsed.profile_version,
                status="PARSING",
                apply_idempotency_key=_digest(
                    {
                        "snapshot_id": snapshot.id,
                        "profile_version": parsed.profile_version,
                    }
                ),
                row_version=1,
            )
            self.session.add(run)
            self.session.flush()

            source_rows = self._persist_source_rows(receipt.id, parsed.raw_rows)
            if source_type is W3SourceType.NHIS_SCHEDULE:
                assert parsed.profile_version == NHIS_SCHEDULE_PROFILE_V1.profile_version
                self._persist_nhis_preview(
                    run,
                    cast(tuple[NhisScheduleRow, ...], parsed.parsed_rows),
                    source_rows,
                    account,
                )
            else:
                assert parsed.profile_version == RFID_PROFILE_V1.profile_version
                self._persist_rfid_preview(
                    run,
                    cast(tuple[RfidRow, ...], parsed.parsed_rows),
                    tuple(row.occurrence_identity for row in parsed.target_rows),
                    source_rows,
                    account,
                )

            self._append_attempt(run, receipt, "SUCCEEDED")
            run.status = "PREVIEW_READY"
            preview_digest = self._calculate_preview_digest(run.id, parsed.warning_codes)
            self._append_run_event(
                run,
                event_type="PREVIEW_CREATED",
                from_status="PARSING",
                to_status="PREVIEW_READY",
                actor_account_id=account.id,
                event_digest=preview_digest,
            )
            self._commit()
        except Exception as error:
            self._rollback_and_raise(error)
        return self.workspace(source_type=source_type, target_date=target_date)

    def _persist_source_rows(
        self,
        receipt_id: int,
        rows: tuple[RawSourceRow, ...],
    ) -> dict[int, W3SourceRow]:
        result: dict[int, W3SourceRow] = {}
        for row in rows:
            model = W3SourceRow(
                receipt_id=receipt_id,
                sheet_ref=row.sheet_ref,
                source_row_number=row.source_row_number,
            )
            self.session.add(model)
            result[row.source_row_number] = model
        self.session.flush()
        return result

    def _append_attempt(
        self,
        run: W3ImportRun,
        receipt: W3SourceReceipt,
        status: str,
    ) -> W3ImportAttempt:
        ordinal = int(
            self.session.scalar(
                select(func.coalesce(func.max(W3ImportAttempt.attempt_ordinal), 0)).where(
                    W3ImportAttempt.import_run_id == run.id
                )
            )
            or 0
        ) + 1
        attempt = W3ImportAttempt(
            receipt_id=receipt.id,
            import_run_id=run.id,
            snapshot_id=run.snapshot_id,
            content_id=run.content_id,
            content_digest=run.content_digest,
            attempt_ordinal=ordinal,
            status=status,
        )
        self.session.add(attempt)
        return attempt

    def _append_run_event(
        self,
        run: W3ImportRun,
        *,
        event_type: str,
        from_status: str | None,
        to_status: str,
        actor_account_id: int,
        event_digest: str,
        command_idempotency_key: str | None = None,
        command_digest: str | None = None,
    ) -> W3ImportRunEvent:
        ordinal = int(
            self.session.scalar(
                select(func.coalesce(func.max(W3ImportRunEvent.event_ordinal), 0)).where(
                    W3ImportRunEvent.import_run_id == run.id
                )
            )
            or 0
        ) + 1
        event = W3ImportRunEvent(
            import_run_id=run.id,
            event_ordinal=ordinal,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_account_id=actor_account_id,
            event_digest=event_digest,
            command_idempotency_key=command_idempotency_key,
            command_digest=command_digest,
        )
        self.session.add(event)
        return event

    def _persist_nhis_preview(
        self,
        run: W3ImportRun,
        rows: tuple[NhisScheduleRow, ...],
        source_rows: dict[int, W3SourceRow],
        account: CurrentAccount,
    ) -> None:
        normalized_by_row: dict[int, W3NormalizedNhisRow] = {}
        for row in rows:
            normalized_payload = {
                "occurrence_identity": row.occurrence_identity,
                "service_date": row.service_date,
                "planned_start": row.planned_start,
                "planned_end": row.planned_end,
                "declared_minutes": row.declared_minutes,
                "recipient_certification_number": row.recipient_certification_number,
                "staff_external_number": row.staff_external_number,
                "worker_category": row.worker_category,
                "family_flag": row.family_flag,
                "family_relationship": row.family_relationship,
                "service_category": row.service_category,
                "fee_code": row.fee_code,
                "fee_name": row.fee_name,
                "fee_amount": row.fee_amount,
            }
            model = W3NormalizedNhisRow(
                import_run_id=run.id,
                source_row_id=source_rows[row.source_row_number].id,
                occurrence_signature=row.occurrence_signature,
                occurrence_ordinal=row.occurrence_ordinal,
                normalized_digest=_digest(normalized_payload),
                service_date=row.service_date,
                planned_start=row.planned_start,
                planned_end=row.planned_end,
                declared_minutes=row.declared_minutes,
                recipient_certification_number=row.recipient_certification_number,
                staff_external_number=row.staff_external_number,
                worker_category=row.worker_category,
                family_flag=row.family_flag,
                family_relationship=row.family_relationship,
                service_category=row.service_category,
                fee_code=row.fee_code,
                fee_name=row.fee_name,
                fee_amount=row.fee_amount,
            )
            self.session.add(model)
            normalized_by_row[row.source_row_number] = model
        self.session.flush()

        groups = derive_nhis_groups(rows)
        for group in groups:
            group_model = self._persist_nhis_group(run, group)
            for row_number in group.source_row_numbers:
                normalized = normalized_by_row[row_number]
                self.session.add(
                    W3NhisGroupMember(
                        import_run_id=run.id,
                        nhis_group_id=group_model.id,
                        normalized_nhis_row_id=normalized.id,
                        source_row_id=normalized.source_row_id,
                    )
                )
            self._persist_nhis_match_decision(run, group_model, account)

    def _persist_nhis_group(
        self,
        run: W3ImportRun,
        group: NhisDerivedGroup,
    ) -> W3NhisGroup:
        payload = {
            "group_signature": group.group_signature,
            "service_date": group.service_date_iso,
            "planned_start": group.planned_start_iso,
            "planned_end": group.planned_end_iso,
            "declared_minutes": group.declared_minutes,
            "recipient_certification_number": group.recipient_certification_number,
            "staff_external_number": group.staff_external_number,
            "service_category": group.service_category,
            "source_occurrence_identities": group.source_occurrence_identities,
        }
        model = W3NhisGroup(
            import_run_id=run.id,
            group_signature=group.group_signature,
            normalized_digest=_digest(payload),
            service_date=date.fromisoformat(group.service_date_iso),
            planned_start=time.fromisoformat(group.planned_start_iso),
            planned_end=time.fromisoformat(group.planned_end_iso),
            declared_minutes=group.declared_minutes,
            recipient_certification_number=group.recipient_certification_number,
            staff_external_number=group.staff_external_number,
            service_category=group.service_category,
        )
        self.session.add(model)
        self.session.flush()
        return model

    def _persist_nhis_match_decision(
        self,
        run: W3ImportRun,
        group: W3NhisGroup,
        account: CurrentAccount,
    ) -> None:
        links = self.matching_repository.automatic_nhis_links(
            service_date=group.service_date,
            planned_start=group.planned_start,
            planned_end=group.planned_end,
            recipient_certification_number=group.recipient_certification_number,
            staff_external_number=group.staff_external_number,
            service_category=group.service_category,
        )
        mapping_candidates = tuple(
            StableStaffMappingCandidate(
                mapping_id=int(link.staff_legacy_mapping_id or 0),
                staff_id=link.staff_id,
                source_external_number=group.staff_external_number,
                mapping_active=True,
                employment_valid=True,
                care_worker_position_valid=True,
            )
            for link in links
            if link.staff_legacy_mapping_id is not None
        )
        schedule_candidates = tuple(
            ScheduleMatchCandidate(
                schedule_id=link.w2_schedule_id,
                staff_id=link.staff_id,
                recipient_certification_valid=True,
                contract_valid=True,
                assignment_valid=True,
                target_date_valid=True,
                service_valid=True,
                time_window_valid=True,
                conflict_free=True,
                manual_protection_clear=True,
                month_unfinalized=True,
            )
            for link in links
        )
        decision = match_unique_schedule(
            MatchRequest(
                source_occurrence_identity=group.group_signature,
                source_staff_external_number=group.staff_external_number,
                staff_mapping_candidates=mapping_candidates,
                schedule_candidates=schedule_candidates,
            )
        )
        selected = (
            next(
                (
                    link
                    for link in links
                    if link.staff_id == decision.staff_id
                    and link.w2_schedule_id == decision.schedule_id
                ),
                None,
            )
            if decision.status.value == "AUTO_MATCH"
            else None
        )
        typed = _typed_payload(selected) if selected is not None else {}
        payload = {
            "source_type": "NHIS_SCHEDULE",
            "source_occurrence_identity": group.group_signature,
            "status": decision.status.value,
            "reason_code": decision.reason,
            **typed,
        }
        self.session.add(
            W3MatchDecision(
                import_run_id=run.id,
                source_type="NHIS_SCHEDULE",
                source_occurrence_identity=group.group_signature,
                nhis_group_id=group.id,
                normalized_rfid_row_id=None,
                decision_revision=1,
                supersedes_decision_id=None,
                status=decision.status.value,
                reason_code=decision.reason,
                decision_digest=_digest(payload),
                created_by_account_id=account.id,
                **typed,
            )
        )

    def _persist_rfid_preview(
        self,
        run: W3ImportRun,
        rows: tuple[RfidRow, ...],
        selected_occurrences: tuple[str, ...],
        source_rows: dict[int, W3SourceRow],
        account: CurrentAccount,
    ) -> None:
        selected = set(selected_occurrences)
        for row in rows:
            payload = {
                "occurrence_identity": row.occurrence_identity,
                "transmission_kind": row.transmission_kind,
                "recipient_certification_number": row.recipient_certification_number,
                "service_category": row.service_category,
                "reference_minutes": row.reference_minutes,
                "actual_start": row.actual_start,
                "actual_end": row.actual_end,
                "actual_seconds": row.actual_seconds,
                "use_state": row.use_state,
                "event_state": row.event_state.value,
            }
            normalized = W3NormalizedRfidRow(
                import_run_id=run.id,
                source_row_id=source_rows[row.source_row_number].id,
                target_selected=row.occurrence_identity in selected,
                occurrence_signature=row.occurrence_signature,
                occurrence_ordinal=row.occurrence_ordinal,
                normalized_digest=_digest(payload),
                transmission_kind=row.transmission_kind,
                recipient_certification_number=row.recipient_certification_number,
                service_category=row.service_category,
                reference_minutes=row.reference_minutes,
                actual_start=row.actual_start,
                actual_end=row.actual_end,
                actual_seconds=row.actual_seconds,
                use_state=row.use_state,
                event_state=row.event_state.value,
            )
            self.session.add(normalized)
            self.session.flush()
            if not normalized.target_selected:
                continue
            decision = match_unique_schedule(
                MatchRequest(
                    source_occurrence_identity=row.occurrence_identity,
                    source_staff_external_number=None,
                    staff_mapping_candidates=(),
                    schedule_candidates=(),
                )
            )
            decision_payload = {
                "source_type": "RFID",
                "source_occurrence_identity": row.occurrence_identity,
                "status": decision.status.value,
                "reason_code": decision.reason,
            }
            self.session.add(
                W3MatchDecision(
                    import_run_id=run.id,
                    source_type="RFID",
                    source_occurrence_identity=row.occurrence_identity,
                    nhis_group_id=None,
                    normalized_rfid_row_id=normalized.id,
                    decision_revision=1,
                    supersedes_decision_id=None,
                    status=decision.status.value,
                    reason_code=decision.reason,
                    decision_digest=_digest(decision_payload),
                    recipient_id=None,
                    certification_period_id=None,
                    staff_id=None,
                    employment_id=None,
                    staff_legacy_mapping_id=None,
                    service_type_id=None,
                    recipient_contract_id=None,
                    care_assignment_id=None,
                    w2_schedule_id=None,
                    created_by_account_id=account.id,
                )
            )

    def _current_decisions(self, run_id: int) -> list[W3MatchDecision]:
        rows = self.session.scalars(
            select(W3MatchDecision)
            .where(W3MatchDecision.import_run_id == run_id)
            .order_by(
                W3MatchDecision.source_occurrence_identity,
                W3MatchDecision.decision_revision,
                W3MatchDecision.id,
            )
        ).all()
        latest: dict[str, W3MatchDecision] = {}
        for row in rows:
            latest[row.source_occurrence_identity] = row
        return [latest[key] for key in sorted(latest)]

    def _warning_codes(self, run: W3ImportRun) -> list[str]:
        snapshot = self.session.get(W3SourceSnapshot, run.snapshot_id)
        if snapshot is None or snapshot.source_type != "RFID":
            return []
        total = int(
            self.session.scalar(
                select(func.count()).select_from(W3NormalizedRfidRow).where(
                    W3NormalizedRfidRow.import_run_id == run.id
                )
            )
            or 0
        )
        selected = int(
            self.session.scalar(
                select(func.count()).select_from(W3NormalizedRfidRow).where(
                    W3NormalizedRfidRow.import_run_id == run.id,
                    W3NormalizedRfidRow.target_selected.is_(True),
                )
            )
            or 0
        )
        return ["EXPORT_CONTAINS_OTHER_DATES"] if selected != total else []

    def _calculate_preview_digest(
        self,
        run_id: int,
        warning_codes: tuple[str, ...] | list[str] | None = None,
    ) -> str:
        decisions = self._current_decisions(run_id)
        return _digest(
            {
                "run_id": run_id,
                "warnings": sorted(warning_codes or []),
                "decisions": [
                    {
                        "source_occurrence_identity": row.source_occurrence_identity,
                        "decision_revision": row.decision_revision,
                        "decision_digest": row.decision_digest,
                    }
                    for row in decisions
                ],
                "normalized_nhis": int(
                    self.session.scalar(
                        select(func.count()).select_from(W3NormalizedNhisRow).where(
                            W3NormalizedNhisRow.import_run_id == run_id
                        )
                    )
                    or 0
                ),
                "normalized_rfid": int(
                    self.session.scalar(
                        select(func.count()).select_from(W3NormalizedRfidRow).where(
                            W3NormalizedRfidRow.import_run_id == run_id
                        )
                    )
                    or 0
                ),
            }
        )

    def _preview_digest(self, run_id: int) -> str | None:
        event = self.session.scalar(
            select(W3ImportRunEvent)
            .where(
                W3ImportRunEvent.import_run_id == run_id,
                W3ImportRunEvent.event_type.in_({"PREVIEW_CREATED", "MANUAL_DECISION"}),
            )
            .order_by(W3ImportRunEvent.event_ordinal.desc())
            .limit(1)
        )
        return None if event is None else event.event_digest

    def _run_counts(
        self,
        run: W3ImportRun,
        decisions: list[W3MatchDecision],
    ) -> W3RunCounts:
        raw_rows = int(
            self.session.scalar(
                select(func.count()).select_from(W3SourceRow).where(
                    W3SourceRow.receipt_id == run.receipt_id
                )
            )
            or 0
        )
        nhis_rows = int(
            self.session.scalar(
                select(func.count()).select_from(W3NormalizedNhisRow).where(
                    W3NormalizedNhisRow.import_run_id == run.id
                )
            )
            or 0
        )
        rfid_rows = int(
            self.session.scalar(
                select(func.count()).select_from(W3NormalizedRfidRow).where(
                    W3NormalizedRfidRow.import_run_id == run.id
                )
            )
            or 0
        )
        target_rfid = int(
            self.session.scalar(
                select(func.count()).select_from(W3NormalizedRfidRow).where(
                    W3NormalizedRfidRow.import_run_id == run.id,
                    W3NormalizedRfidRow.target_selected.is_(True),
                )
            )
            or 0
        )
        group_count = int(
            self.session.scalar(
                select(func.count()).select_from(W3NhisGroup).where(
                    W3NhisGroup.import_run_id == run.id
                )
            )
            or 0
        )
        statuses = [row.status for row in decisions]
        return W3RunCounts(
            raw_rows=raw_rows,
            normalized_rows=nhis_rows + rfid_rows,
            target_rows=nhis_rows if nhis_rows else target_rfid,
            derived_groups=group_count,
            auto_matches=statuses.count("AUTO_MATCH"),
            manual_matches=statuses.count("MANUAL_MATCH"),
            review_pending=statuses.count("REVIEW_PENDING"),
            blocked=statuses.count("BLOCKED"),
        )

    def _decision_item(self, decision: W3MatchDecision) -> W3DecisionItem:
        if decision.source_type == "NHIS_SCHEDULE":
            group = self.session.get(W3NhisGroup, decision.nhis_group_id)
            if group is None:
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            source_row_number = self.session.scalar(
                select(W3SourceRow.source_row_number)
                .join(
                    W3NhisGroupMember,
                    W3NhisGroupMember.source_row_id == W3SourceRow.id,
                )
                .where(W3NhisGroupMember.nhis_group_id == group.id)
                .order_by(W3SourceRow.source_row_number)
                .limit(1)
            )
            return W3DecisionItem(
                id=decision.id,
                source_occurrence_identity=decision.source_occurrence_identity,
                status=W3MatchStatus(decision.status),
                reason_code=decision.reason_code,
                source_row_number=(int(source_row_number) if source_row_number else None),
                service_date=group.service_date,
                service_category=group.service_category,
                event_state=None,
                end_display=None,
                row_version=decision.decision_revision,
            )

        row = self.session.get(W3NormalizedRfidRow, decision.normalized_rfid_row_id)
        if row is None:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        source_row_number = self.session.scalar(
            select(W3SourceRow.source_row_number).where(W3SourceRow.id == row.source_row_id)
        )
        local_start = row.actual_start.astimezone(ZoneInfo("Asia/Seoul"))
        end_display = (
            f"종료X · {local_start:%H:%M}"
            if row.actual_end is None
            else row.actual_end.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M")
        )
        return W3DecisionItem(
            id=decision.id,
            source_occurrence_identity=decision.source_occurrence_identity,
            status=W3MatchStatus(decision.status),
            reason_code=decision.reason_code,
            source_row_number=(int(source_row_number) if source_row_number else None),
            service_date=local_start.date(),
            service_category=row.service_category,
            event_state=row.event_state,
            end_display=end_display,
            row_version=decision.decision_revision,
        )

    def _run_summary(self, run: W3ImportRun) -> W3RunSummary:
        snapshot = self.session.get(W3SourceSnapshot, run.snapshot_id)
        receipt = self.session.get(W3SourceReceipt, run.receipt_id)
        if snapshot is None or receipt is None:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        decisions = self._current_decisions(run.id)
        counts = self._run_counts(run, decisions)
        preview_digest = self._preview_digest(run.id)
        return W3RunSummary(
            id=run.id,
            source_type=W3SourceType(snapshot.source_type),
            target_date=snapshot.target_date,
            original_filename=receipt.original_filename,
            parser_profile_version=run.parser_profile_version,
            status=W3RunStatus(run.status),
            row_version=run.row_version,
            preview_digest=preview_digest,
            warning_codes=self._warning_codes(run),
            counts=counts,
            decisions=[self._decision_item(row) for row in decisions],
            created_at_utc=run.created_at_utc,
            can_confirm=(
                run.status == "PREVIEW_READY"
                and counts.blocked == 0
                and counts.review_pending == 0
            ),
            can_apply=(
                run.status == "CONFIRMED"
                and counts.blocked == 0
                and counts.review_pending == 0
            ),
        )

    def workspace(
        self,
        *,
        source_type: W3SourceType,
        target_date: date,
    ) -> W3WorkspaceResponse:
        runs = self.session.scalars(
            select(W3ImportRun)
            .join(W3SourceSnapshot, W3SourceSnapshot.id == W3ImportRun.snapshot_id)
            .where(
                W3SourceSnapshot.source_type == source_type.value,
                W3SourceSnapshot.target_date == target_date,
            )
            .order_by(W3ImportRun.id.desc())
            .limit(10)
        ).all()
        control = self.session.get(
            W3ApplyControl,
            {"source_type": source_type.value, "target_date": target_date},
        )
        active = None
        if (
            control is not None
            and control.active_snapshot_id is not None
            and control.active_import_run_id is not None
        ):
            active = W3ActiveSnapshot(
                snapshot_id=control.active_snapshot_id,
                import_run_id=control.active_import_run_id,
                source_type=source_type,
                target_date=target_date,
                row_version=control.row_version,
            )
        summaries = [self._run_summary(run) for run in runs]
        return W3WorkspaceResponse(
            source_type=source_type,
            target_date=target_date,
            active=active,
            latest_run=summaries[0] if summaries else None,
            recent_runs=summaries,
        )

    def _run_context_for_update(
        self,
        run_id: int,
    ) -> tuple[W3ImportRun, W3SourceSnapshot]:
        run = self.session.scalar(
            select(W3ImportRun).where(W3ImportRun.id == run_id).with_for_update()
        )
        if run is None:
            raise domain_error("W3_RUN_NOT_FOUND", 404)
        snapshot = self.session.get(W3SourceSnapshot, run.snapshot_id)
        if snapshot is None:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        return run, snapshot

    def _workspace_for_snapshot(self, snapshot: W3SourceSnapshot) -> W3WorkspaceResponse:
        return self.workspace(
            source_type=W3SourceType(snapshot.source_type),
            target_date=snapshot.target_date,
        )

    def _run_conflict(
        self,
        code: str,
        run: W3ImportRun,
        snapshot: W3SourceSnapshot,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        latest = self._workspace_for_snapshot(snapshot)
        conflict_details: dict[str, object] = {
            "entity": "w3_import_run",
            "current_row_version": run.row_version,
            "latest": latest.model_dump(mode="json"),
        }
        conflict_details.update(details or {})
        raise domain_error(code, 409, details=conflict_details)

    def _version_conflict(
        self,
        run: W3ImportRun,
        snapshot: W3SourceSnapshot,
    ) -> None:
        self._run_conflict("W3_ROW_VERSION_CONFLICT", run, snapshot)

    def _event_by_command_key(
        self,
        run_id: int,
        command_idempotency_key: str,
    ) -> W3ImportRunEvent | None:
        return self.session.scalar(
            select(W3ImportRunEvent).where(
                W3ImportRunEvent.import_run_id == run_id,
                W3ImportRunEvent.command_idempotency_key == command_idempotency_key,
            )
        )

    def confirm_run(
        self,
        run_id: int,
        payload: W3ConfirmRequest,
        account: CurrentAccount,
    ) -> W3WorkspaceResponse:
        try:
            run, snapshot = self._run_context_for_update(run_id)
            command_digest = _digest(
                {
                    "action": "CONFIRM",
                    "run_id": run.id,
                    "payload": payload.model_dump(mode="json"),
                }
            )
            existing = self._event_by_command_key(run.id, payload.command_idempotency_key)
            if existing is not None:
                if (
                    existing.event_type != "CONFIRMED"
                    or existing.command_digest != command_digest
                ):
                    self._run_conflict("W3_IDEMPOTENCY_CONFLICT", run, snapshot)
                return self._workspace_for_snapshot(snapshot)
            if run.row_version != payload.expected_row_version:
                self._version_conflict(run, snapshot)
            if run.status != "PREVIEW_READY":
                self._run_conflict(
                    "W3_RUN_STATE_INVALID",
                    run,
                    snapshot,
                    details={"run_id": run.id, "status": run.status},
                )
            latest_digest = self._preview_digest(run.id)
            if latest_digest != payload.preview_digest:
                self._run_conflict(
                    "W3_PREVIEW_DIGEST_MISMATCH",
                    run,
                    snapshot,
                    details={"latest_preview_digest": latest_digest},
                )
            counts = self._run_counts(run, self._current_decisions(run.id))
            if counts.blocked or counts.review_pending:
                raise domain_error(
                    "W3_REVIEW_PENDING",
                    422,
                    details={
                        "blocked": counts.blocked,
                        "review_pending": counts.review_pending,
                        "business_write_count": 0,
                    },
                )
            run.status = "CONFIRMED"
            run.row_version += 1
            self._append_run_event(
                run,
                event_type="CONFIRMED",
                from_status="PREVIEW_READY",
                to_status="CONFIRMED",
                actor_account_id=account.id,
                event_digest=_digest(
                    {
                        "preview_digest": payload.preview_digest,
                        "expected_row_version": payload.expected_row_version,
                    }
                ),
                command_idempotency_key=payload.command_idempotency_key,
                command_digest=command_digest,
            )
            self._commit()
        except Exception as error:
            self._rollback_and_raise(error)
        return self._workspace_for_snapshot(snapshot)

    def resolve_decision(
        self,
        run_id: int,
        decision_id: int,
        payload: W3ResolveDecisionRequest,
        account: CurrentAccount,
    ) -> W3WorkspaceResponse:
        try:
            run, snapshot = self._run_context_for_update(run_id)
            command_digest = _digest(
                {
                    "action": "RESOLVE_DECISION",
                    "run_id": run.id,
                    "decision_id": decision_id,
                    "payload": payload.model_dump(mode="json"),
                }
            )
            existing_event = self._event_by_command_key(
                run.id, payload.command_idempotency_key
            )
            if existing_event is not None:
                if (
                    existing_event.event_type != "MANUAL_DECISION"
                    or existing_event.command_digest != command_digest
                ):
                    self._run_conflict("W3_IDEMPOTENCY_CONFLICT", run, snapshot)
                return self._workspace_for_snapshot(snapshot)
            if run.row_version != payload.expected_run_row_version:
                self._version_conflict(run, snapshot)
            if run.status != "PREVIEW_READY":
                self._run_conflict("W3_RUN_STATE_INVALID", run, snapshot)
            current = self.session.scalar(
                select(W3MatchDecision)
                .where(
                    W3MatchDecision.id == decision_id,
                    W3MatchDecision.import_run_id == run.id,
                )
            )
            if current is None:
                raise domain_error("W3_RUN_NOT_FOUND", 404)
            latest_revision = self.session.scalar(
                select(func.max(W3MatchDecision.decision_revision)).where(
                    W3MatchDecision.import_run_id == run.id,
                    W3MatchDecision.source_occurrence_identity
                    == current.source_occurrence_identity,
                )
            )
            if current.decision_revision != latest_revision:
                self._version_conflict(run, snapshot)
            if current.status not in {"REVIEW_PENDING", "BLOCKED"}:
                self._run_conflict("W3_RUN_STATE_INVALID", run, snapshot)

            (
                service_date,
                certification_number,
                service_category,
                staff_external_number,
                planned_start,
                planned_end,
            ) = self._decision_source_context(current)
            link = self.matching_repository.validated_manual_link(
                service_date=service_date,
                recipient_certification_number=certification_number,
                service_category=service_category,
                staff_external_number=staff_external_number,
                planned_start=planned_start,
                planned_end=planned_end,
                recipient_id=payload.recipient_id,
                certification_period_id=payload.certification_period_id,
                staff_id=payload.staff_id,
                employment_id=payload.employment_id,
                service_type_id=payload.service_type_id,
                recipient_contract_id=payload.recipient_contract_id,
                care_assignment_id=payload.care_assignment_id,
                w2_schedule_id=payload.w2_schedule_id,
            )
            if link is None:
                raise domain_error("W3_TYPED_LINK_INVALID", 422)
            typed = _typed_payload(link)
            decision_payload = {
                "source_type": current.source_type,
                "source_occurrence_identity": current.source_occurrence_identity,
                "status": "MANUAL_MATCH",
                "reason_code": "USER_VALIDATED_TYPED_LINK",
                **typed,
            }
            replacement = W3MatchDecision(
                import_run_id=run.id,
                source_type=current.source_type,
                source_occurrence_identity=current.source_occurrence_identity,
                nhis_group_id=current.nhis_group_id,
                normalized_rfid_row_id=current.normalized_rfid_row_id,
                decision_revision=current.decision_revision + 1,
                supersedes_decision_id=current.id,
                status="MANUAL_MATCH",
                reason_code="USER_VALIDATED_TYPED_LINK",
                decision_digest=_digest(decision_payload),
                created_by_account_id=account.id,
                **typed,
            )
            self.session.add(replacement)
            self.session.flush()
            run.row_version += 1
            preview_digest = self._calculate_preview_digest(
                run.id,
                self._warning_codes(run),
            )
            self._append_run_event(
                run,
                event_type="MANUAL_DECISION",
                from_status="PREVIEW_READY",
                to_status="PREVIEW_READY",
                actor_account_id=account.id,
                event_digest=preview_digest,
                command_idempotency_key=payload.command_idempotency_key,
                command_digest=command_digest,
            )
            self._commit()
        except Exception as error:
            self._rollback_and_raise(error)
        return self._workspace_for_snapshot(snapshot)

    def _decision_source_context(
        self,
        decision: W3MatchDecision,
    ) -> tuple[date, str, str, str | None, time | None, time | None]:
        if decision.source_type == "NHIS_SCHEDULE":
            group = self.session.get(W3NhisGroup, decision.nhis_group_id)
            if group is None:
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            return (
                group.service_date,
                group.recipient_certification_number,
                group.service_category,
                group.staff_external_number,
                group.planned_start,
                group.planned_end,
            )
        row = self.session.get(W3NormalizedRfidRow, decision.normalized_rfid_row_id)
        if row is None:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        return (
            row.actual_start.astimezone(ZoneInfo("Asia/Seoul")).date(),
            row.recipient_certification_number,
            row.service_category,
            None,
            None,
            None,
        )

    def _revalidate_typed_decisions(
        self,
        decisions: list[W3MatchDecision],
    ) -> None:
        required_fields = (
            "recipient_id",
            "certification_period_id",
            "staff_id",
            "employment_id",
            "service_type_id",
            "recipient_contract_id",
            "care_assignment_id",
            "w2_schedule_id",
        )
        for decision in decisions:
            if decision.status not in {"AUTO_MATCH", "MANUAL_MATCH"}:
                continue
            if any(getattr(decision, field) is None for field in required_fields):
                raise domain_error(
                    "W3_TYPED_LINK_INVALID",
                    422,
                    details={"business_write_count": 0},
                )
            (
                service_date,
                certification_number,
                service_category,
                staff_external_number,
                planned_start,
                planned_end,
            ) = self._decision_source_context(decision)
            link = self.matching_repository.validated_manual_link(
                service_date=service_date,
                recipient_certification_number=certification_number,
                service_category=service_category,
                staff_external_number=staff_external_number,
                planned_start=planned_start,
                planned_end=planned_end,
                recipient_id=cast(int, decision.recipient_id),
                certification_period_id=cast(int, decision.certification_period_id),
                staff_id=cast(int, decision.staff_id),
                employment_id=cast(int, decision.employment_id),
                service_type_id=cast(int, decision.service_type_id),
                recipient_contract_id=cast(int, decision.recipient_contract_id),
                care_assignment_id=cast(int, decision.care_assignment_id),
                w2_schedule_id=cast(int, decision.w2_schedule_id),
            )
            stored_payload = _typed_payload(
                W3TypedLink(
                    recipient_id=cast(int, decision.recipient_id),
                    certification_period_id=cast(int, decision.certification_period_id),
                    staff_id=cast(int, decision.staff_id),
                    employment_id=cast(int, decision.employment_id),
                    staff_legacy_mapping_id=decision.staff_legacy_mapping_id,
                    service_type_id=cast(int, decision.service_type_id),
                    recipient_contract_id=cast(int, decision.recipient_contract_id),
                    care_assignment_id=cast(int, decision.care_assignment_id),
                    w2_schedule_id=cast(int, decision.w2_schedule_id),
                )
            )
            if link is None or _typed_payload(link) != stored_payload:
                raise domain_error(
                    "W3_TYPED_LINK_INVALID",
                    422,
                    details={"business_write_count": 0},
                )

    def _lock_apply_control(
        self,
        snapshot: W3SourceSnapshot,
        account: CurrentAccount,
    ) -> W3ApplyControl:
        self.session.execute(
            postgres_insert(W3ApplyControl)
            .values(
                source_type=snapshot.source_type,
                target_date=snapshot.target_date,
                active_snapshot_id=None,
                active_import_run_id=None,
                row_version=1,
                updated_by_account_id=account.id,
            )
            .on_conflict_do_nothing(
                index_elements=[W3ApplyControl.source_type, W3ApplyControl.target_date]
            )
        )
        control = self.session.scalar(
            select(W3ApplyControl)
            .where(
                W3ApplyControl.source_type == snapshot.source_type,
                W3ApplyControl.target_date == snapshot.target_date,
            )
            .with_for_update()
        )
        if control is None:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        return control

    def apply_run(
        self,
        run_id: int,
        payload: W3ApplyRequest,
        account: CurrentAccount,
    ) -> W3WorkspaceResponse:
        try:
            run, snapshot = self._run_context_for_update(run_id)
            command_digest = _digest(
                {
                    "action": "APPLY",
                    "run_id": run.id,
                    "payload": payload.model_dump(mode="json"),
                }
            )
            existing = self._event_by_command_key(run.id, payload.command_idempotency_key)
            if existing is not None:
                if (
                    existing.event_type != "APPLIED"
                    or existing.command_digest != command_digest
                ):
                    self._run_conflict("W3_IDEMPOTENCY_CONFLICT", run, snapshot)
                return self._workspace_for_snapshot(snapshot)
            if run.row_version != payload.expected_row_version:
                self._version_conflict(run, snapshot)
            if run.status != "CONFIRMED":
                self._run_conflict("W3_RUN_STATE_INVALID", run, snapshot)

            decisions = self._current_decisions(run.id)
            counts = self._run_counts(run, decisions)
            if counts.blocked or counts.review_pending:
                raise domain_error(
                    "W3_REVIEW_PENDING",
                    422,
                    details={
                        "blocked": counts.blocked,
                        "review_pending": counts.review_pending,
                        "business_write_count": 0,
                    },
                )
            control = self._lock_apply_control(snapshot, account)
            self._lock_schedule_month(snapshot.target_date.replace(day=1))
            self._revalidate_typed_decisions(decisions)
            run.status = "APPLYING"
            self._append_run_event(
                run,
                event_type="APPLY_STARTED",
                from_status="CONFIRMED",
                to_status="APPLYING",
                actor_account_id=account.id,
                event_digest=_digest(
                    {
                        "run_id": run.id,
                        "expected_row_version": payload.expected_row_version,
                    }
                ),
            )

            if snapshot.source_type == "RFID":
                self._reconcile_actual_work(run, snapshot, decisions, account)

            active_snapshots = self.session.scalars(
                select(W3SourceSnapshot)
                .where(
                    W3SourceSnapshot.source_type == snapshot.source_type,
                    W3SourceSnapshot.target_date == snapshot.target_date,
                    W3SourceSnapshot.status == "ACTIVE",
                    W3SourceSnapshot.id != snapshot.id,
                )
                .with_for_update()
            ).all()
            if len(active_snapshots) > 1:
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            previous_snapshot = active_snapshots[0] if active_snapshots else None
            allowed_control_ids = {snapshot.id}
            if previous_snapshot is not None:
                allowed_control_ids.add(previous_snapshot.id)
            if (
                control.active_snapshot_id is not None
                and control.active_snapshot_id not in allowed_control_ids
            ):
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            previous_snapshot_id = (
                None if previous_snapshot is None else previous_snapshot.id
            )
            if previous_snapshot is not None:
                previous_snapshot.status = "SUPERSEDED"
                # PostgreSQL checks the one-ACTIVE partial unique index per
                # statement.  Flush the closure first so SQLAlchemy cannot
                # batch the candidate ACTIVE update ahead of it.  Both writes
                # remain inside this APPLY transaction and commit together.
                self.session.flush([previous_snapshot])
            snapshot.status = "ACTIVE"
            control.active_snapshot_id = snapshot.id
            control.active_import_run_id = run.id
            control.row_version += 1
            control.updated_by_account_id = account.id
            control.updated_at_utc = datetime.now(UTC)
            run.status = "APPLIED"
            run.row_version += 1
            self._append_run_event(
                run,
                event_type="APPLIED",
                from_status="APPLYING",
                to_status="APPLIED",
                actor_account_id=account.id,
                event_digest=_digest(
                    {
                        "run_id": run.id,
                        "snapshot_id": snapshot.id,
                        "previous_snapshot_id": previous_snapshot_id,
                        "control_row_version": control.row_version,
                    }
                ),
                command_idempotency_key=payload.command_idempotency_key,
                command_digest=command_digest,
            )
            self.session.flush()
            self._commit()
        except Exception as error:
            self._rollback_and_raise(error)
        return self._workspace_for_snapshot(snapshot)

    def _rfid_candidate_payload(
        self,
        decision: W3MatchDecision,
        row: W3NormalizedRfidRow,
    ) -> dict[str, object]:
        return {
            "source_occurrence_identity": decision.source_occurrence_identity,
            "occurrence_signature": row.occurrence_signature,
            "occurrence_ordinal": row.occurrence_ordinal,
            "recipient_id": decision.recipient_id,
            "certification_period_id": decision.certification_period_id,
            "staff_id": decision.staff_id,
            "employment_id": decision.employment_id,
            "service_type_id": decision.service_type_id,
            "recipient_contract_id": decision.recipient_contract_id,
            "care_assignment_id": decision.care_assignment_id,
            "w2_schedule_id": decision.w2_schedule_id,
            "source_event_state": row.event_state,
            "reference_minutes": row.reference_minutes,
            "actual_start": row.actual_start,
            "actual_end": row.actual_end,
            "actual_seconds": row.actual_seconds,
        }

    def _reconcile_actual_work(
        self,
        run: W3ImportRun,
        snapshot: W3SourceSnapshot,
        decisions: list[W3MatchDecision],
        account: CurrentAccount,
    ) -> None:
        candidate_rows: dict[str, tuple[W3MatchDecision, W3NormalizedRfidRow, str]] = {}
        for decision in decisions:
            if decision.status not in {"AUTO_MATCH", "MANUAL_MATCH"}:
                continue
            row = self.session.get(W3NormalizedRfidRow, decision.normalized_rfid_row_id)
            if row is None or not row.target_selected:
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            fact_digest = _digest(self._rfid_candidate_payload(decision, row))
            if decision.source_occurrence_identity in candidate_rows:
                raise domain_error(
                    "W3_REVIEW_PENDING",
                    422,
                    details={"reason": "DUPLICATE_CANDIDATE_BUSINESS_KEY"},
                )
            candidate_rows[decision.source_occurrence_identity] = (
                decision,
                row,
                fact_digest,
            )

        current = self.session.scalars(
            select(W3ActualWorkRevision)
            .where(
                W3ActualWorkRevision.target_date == snapshot.target_date,
                W3ActualWorkRevision.superseded_at_utc.is_(None),
            )
            .order_by(W3ActualWorkRevision.id)
            .with_for_update()
        ).all()
        current_by_key = {row.source_occurrence_identity: row for row in current}
        active_snapshot_ids = {row.snapshot_id for row in current}
        active_snapshot_id = (
            next(iter(active_snapshot_ids)) if len(active_snapshot_ids) == 1 else None
        )
        if len(active_snapshot_ids) > 1:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        plan = plan_snapshot_reconciliation(
            ReconciliationInput(
                source_type="RFID",
                target_date=snapshot.target_date,
                active_snapshot_id=active_snapshot_id,
                candidate_snapshot_id=snapshot.id,
                confirmed=True,
                blocking_count=0,
                review_pending_count=0,
                current_facts=tuple(
                    AppliedFact(
                        revision_id=row.id,
                        business_key=row.source_occurrence_identity,
                        payload_digest=row.fact_digest,
                    )
                    for row in current
                ),
                candidate_facts=tuple(
                    CandidateFact(business_key=key, payload_digest=value[2])
                    for key, value in sorted(candidate_rows.items())
                ),
            )
        )
        if plan.status not in {
            ReconciliationStatus.APPLY_READY,
            ReconciliationStatus.DUPLICATE_NOOP,
        }:
            raise domain_error(
                "W3_REVIEW_PENDING",
                422,
                details={"reason": plan.reason, "business_write_count": 0},
            )

        now = datetime.now(UTC)
        for operation in plan.operations:
            if operation.kind != "SUPERSEDE":
                continue
            prior = current_by_key.get(operation.business_key)
            if prior is None or prior.id != operation.prior_revision_id:
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            prior.superseded_at_utc = now
        self.session.flush()

        for operation in plan.operations:
            if operation.kind != "INSERT":
                continue
            decision, row, fact_digest = candidate_rows[operation.business_key]
            required = (
                decision.recipient_id,
                decision.certification_period_id,
                decision.staff_id,
                decision.employment_id,
                decision.service_type_id,
                decision.recipient_contract_id,
                decision.care_assignment_id,
                decision.w2_schedule_id,
            )
            if any(value is None for value in required):
                raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
            assert decision.recipient_id is not None
            assert decision.certification_period_id is not None
            assert decision.staff_id is not None
            assert decision.employment_id is not None
            assert decision.service_type_id is not None
            assert decision.recipient_contract_id is not None
            assert decision.care_assignment_id is not None
            assert decision.w2_schedule_id is not None
            self.session.add(
                W3ActualWorkRevision(
                    source_type="RFID",
                    target_date=snapshot.target_date,
                    snapshot_id=snapshot.id,
                    import_run_id=run.id,
                    normalized_rfid_row_id=row.id,
                    match_decision_id=decision.id,
                    source_occurrence_identity=decision.source_occurrence_identity,
                    occurrence_signature=row.occurrence_signature,
                    occurrence_ordinal=row.occurrence_ordinal,
                    recipient_id=int(decision.recipient_id),
                    certification_period_id=int(decision.certification_period_id),
                    staff_id=int(decision.staff_id),
                    employment_id=int(decision.employment_id),
                    service_type_id=int(decision.service_type_id),
                    recipient_contract_id=int(decision.recipient_contract_id),
                    care_assignment_id=int(decision.care_assignment_id),
                    w2_schedule_id=int(decision.w2_schedule_id),
                    source_event_state=row.event_state,
                    reference_minutes=row.reference_minutes,
                    actual_start=row.actual_start,
                    actual_end=row.actual_end,
                    actual_seconds=row.actual_seconds,
                    fact_digest=fact_digest,
                    prior_revision_id=operation.prior_revision_id,
                    superseded_at_utc=None,
                    created_by_account_id=account.id,
                )
            )

    def _actual_work_for_update(self, revision_id: int) -> W3ActualWorkRevision:
        row = self.session.scalar(
            select(W3ActualWorkRevision)
            .where(W3ActualWorkRevision.id == revision_id)
            .with_for_update()
        )
        if row is None:
            raise domain_error("W3_ACTUAL_WORK_NOT_FOUND", 404)
        return row

    def _active_actual_work_for_update(self, revision_id: int) -> W3ActualWorkRevision:
        row = self._actual_work_for_update(revision_id)
        if row.superseded_at_utc is not None:
            raise domain_error("W3_ACTUAL_WORK_NOT_FOUND", 404)
        return row

    def _schedule_month_for_update(self, schedule_month: date) -> W2ScheduleMonthControl:
        control = self.session.scalar(
            select(W2ScheduleMonthControl)
            .where(W2ScheduleMonthControl.schedule_month == schedule_month)
            .with_for_update()
        )
        if control is None:
            raise domain_error("W3_TYPED_LINK_INVALID", 422)
        return control

    def _lock_schedule_month(self, schedule_month: date) -> W2ScheduleMonthControl:
        control = self._schedule_month_for_update(schedule_month)
        if control.finalized_at_utc is not None:
            raise domain_error(
                "W3_MONTH_FINALIZED",
                423,
                details={"business_write_count": 0},
            )
        return control

    def _workspace_for_actual(
        self,
        actual: W3ActualWorkRevision,
    ) -> W3WorkspaceResponse:
        return self.workspace(
            source_type=W3SourceType(actual.source_type),
            target_date=actual.target_date,
        )

    def _actual_conflict(
        self,
        code: str,
        actual: W3ActualWorkRevision,
        *,
        entity: str,
        current_row_version: int,
        details: dict[str, object] | None = None,
    ) -> None:
        conflict_details: dict[str, object] = {
            "entity": entity,
            "current_row_version": current_row_version,
            "latest": self._workspace_for_actual(actual).model_dump(mode="json"),
        }
        conflict_details.update(details or {})
        raise domain_error(code, 409, details=conflict_details)

    def _lock_command_key(self, namespace: str, command_key: str) -> None:
        lock_material = f"sswcenter:w3:{namespace}:{command_key}".encode()
        lock_key = int.from_bytes(
            sha256(lock_material).digest()[:8],
            byteorder="big",
            signed=True,
        )
        self.session.execute(select(func.pg_advisory_xact_lock(lock_key))).one()

    def create_supplement(
        self,
        revision_id: int,
        payload: W3SupplementRequest,
        account: CurrentAccount,
    ) -> W3SupplementResponse:
        try:
            preview_actual = self.session.get(W3ActualWorkRevision, revision_id)
            if preview_actual is None:
                raise domain_error("W3_ACTUAL_WORK_NOT_FOUND", 404)
            schedule_month = preview_actual.target_date.replace(day=1)
            month_control = self._schedule_month_for_update(schedule_month)
            actual = self._actual_work_for_update(revision_id)
            self._lock_command_key(
                "manual-supplement",
                payload.command_idempotency_key,
            )
            events = self.session.scalars(
                select(W3ManualSupplementEvent)
                .where(W3ManualSupplementEvent.actual_work_revision_id == revision_id)
                .order_by(W3ManualSupplementEvent.supplement_version)
            ).all()
            current_event = events[-1] if events else None
            current_version = 0 if current_event is None else current_event.supplement_version
            existing = self.session.scalar(
                select(W3ManualSupplementEvent).where(
                    W3ManualSupplementEvent.command_idempotency_key
                    == payload.command_idempotency_key
                )
            )
            if existing is not None:
                if (
                    existing.actual_work_revision_id != revision_id
                    or existing.supplement_version - 1 != payload.expected_row_version
                    or existing.action != payload.action.value
                    or existing.proposed_actual_end != payload.proposed_actual_end
                    or existing.reason != payload.reason.strip()
                ):
                    self._actual_conflict(
                        "W3_IDEMPOTENCY_CONFLICT",
                        actual,
                        entity="w3_manual_supplement",
                        current_row_version=current_version,
                    )
                return self._supplement_response(existing)

            if month_control.finalized_at_utc is not None:
                raise domain_error(
                    "W3_MONTH_FINALIZED",
                    423,
                    details={"business_write_count": 0},
                )
            if actual.superseded_at_utc is not None:
                raise domain_error("W3_ACTUAL_WORK_NOT_FOUND", 404)
            if actual.source_event_state != "START_ONLY":
                raise domain_error("W3_START_ONLY_REQUIRED", 422)
            currently_active = current_event is not None and current_event.action != "CANCEL"
            if current_version != payload.expected_row_version:
                self._actual_conflict(
                    "W3_SUPPLEMENT_VERSION_CONFLICT",
                    actual,
                    entity="w3_manual_supplement",
                    current_row_version=current_version,
                )
            command = SupplementCommand(
                source_occurrence_identity=actual.source_occurrence_identity,
                source_event_state=actual.source_event_state,
                source_actual_start=actual.actual_start,
                action=SupplementAction(payload.action.value),
                expected_row_version=payload.expected_row_version,
                current_row_version=current_version,
                currently_active=currently_active,
                proposed_actual_end=payload.proposed_actual_end,
                reason=payload.reason.strip(),
                month_finalized=False,
            )
            try:
                result = plan_manual_supplement(command)
            except ValueError:
                raise domain_error(
                    "W3_RUN_STATE_INVALID",
                    422,
                    details={
                        "reason": "INVALID_SUPPLEMENT_TRANSITION",
                        "business_write_count": 0,
                    },
                ) from None
            if result.result is SupplementResult.REJECT_409:
                self._actual_conflict(
                    "W3_SUPPLEMENT_VERSION_CONFLICT",
                    actual,
                    entity="w3_manual_supplement",
                    current_row_version=current_version,
                )
            if result.result is SupplementResult.REJECT_FINALIZED_MONTH:
                raise domain_error("W3_MONTH_FINALIZED", 423)
            if result.event_to_append is None:
                raise domain_error("W3_RUN_STATE_INVALID", 422)
            event_payload = {
                "actual_work_revision_id": actual.id,
                "supplement_version": result.event_to_append.row_version,
                "prior_event_id": None if current_event is None else current_event.id,
                "action": payload.action.value,
                "proposed_actual_end": payload.proposed_actual_end,
                "reason": payload.reason.strip(),
            }
            event = W3ManualSupplementEvent(
                actual_work_revision_id=actual.id,
                supplement_version=result.event_to_append.row_version,
                prior_event_id=None if current_event is None else current_event.id,
                action=payload.action.value,
                proposed_actual_end=payload.proposed_actual_end,
                reason=payload.reason.strip(),
                event_digest=_digest(event_payload),
                command_idempotency_key=payload.command_idempotency_key,
                created_by_account_id=account.id,
            )
            self.session.add(event)
            self.session.flush()
            self._commit()
        except Exception as error:
            self._rollback_and_raise(error)
        return self._supplement_response(event)

    @staticmethod
    def _supplement_response(event: W3ManualSupplementEvent) -> W3SupplementResponse:
        return W3SupplementResponse(
            id=event.id,
            actual_work_revision_id=event.actual_work_revision_id,
            row_version=event.supplement_version,
            action=W3SupplementAction(event.action),
            proposed_actual_end=event.proposed_actual_end,
            reason=event.reason,
            created_at_utc=event.created_at_utc,
        )

    def _effective_actual_end(self, actual: W3ActualWorkRevision) -> datetime | None:
        if actual.actual_end is not None:
            return actual.actual_end
        latest = self.session.scalar(
            select(W3ManualSupplementEvent)
            .where(W3ManualSupplementEvent.actual_work_revision_id == actual.id)
            .order_by(W3ManualSupplementEvent.supplement_version.desc())
            .limit(1)
        )
        if latest is None or latest.action == "CANCEL":
            return None
        return latest.proposed_actual_end

    def adopt_plan_adjustment(
        self,
        revision_id: int,
        payload: W3PlanAdjustmentRequest,
        account: CurrentAccount,
    ) -> W3PlanAdjustmentResponse:
        try:
            preview_actual = self.session.get(W3ActualWorkRevision, revision_id)
            if preview_actual is None:
                raise domain_error("W3_ACTUAL_WORK_NOT_FOUND", 404)
            schedule_month = preview_actual.target_date.replace(day=1)
            month_control = self._schedule_month_for_update(schedule_month)
            schedule = self.session.scalar(
                select(W2Schedule)
                .where(W2Schedule.id == preview_actual.w2_schedule_id)
                .with_for_update()
            )
            actual = self._actual_work_for_update(revision_id)
            self._lock_command_key(
                "plan-adjustment",
                payload.command_idempotency_key,
            )
            existing = self.session.scalar(
                select(W3PlanAdjustmentEvent).where(
                    W3PlanAdjustmentEvent.command_idempotency_key
                    == payload.command_idempotency_key
                )
            )
            if existing is not None:
                if (
                    existing.actual_work_revision_id != revision_id
                    or existing.rule_version != payload.rule_version
                    or existing.reason != payload.reason.strip()
                    or existing.expected_schedule_row_version
                    != payload.expected_schedule_row_version
                    or existing.expected_month_row_version
                    != payload.expected_month_row_version
                ):
                    self._actual_conflict(
                        "W3_IDEMPOTENCY_CONFLICT",
                        actual,
                        entity="w3_plan_adjustment",
                        current_row_version=(
                            0 if schedule is None else schedule.row_version
                        ),
                    )
                return self._plan_adjustment_response(
                    existing,
                    existing.adopted_month_row_version,
                )

            if schedule is None or schedule.schedule_month != schedule_month:
                raise domain_error("W3_TYPED_LINK_INVALID", 422)
            if month_control.finalized_at_utc is not None:
                raise domain_error(
                    "W3_MONTH_FINALIZED",
                    423,
                    details={"business_write_count": 0},
                )
            if actual.superseded_at_utc is not None:
                raise domain_error("W3_ACTUAL_WORK_NOT_FOUND", 404)
            if schedule.row_version != payload.expected_schedule_row_version:
                self._actual_conflict(
                    "W3_ROW_VERSION_CONFLICT",
                    actual,
                    entity="w2_schedule",
                    current_row_version=schedule.row_version,
                )
            if month_control.row_version != payload.expected_month_row_version:
                self._actual_conflict(
                    "W3_ROW_VERSION_CONFLICT",
                    actual,
                    entity="w2_schedule_month_control",
                    current_row_version=month_control.row_version,
                )
            actual_end = self._effective_actual_end(actual)
            if actual_end is None:
                raise domain_error("W3_START_ONLY_REQUIRED", 422)
            try:
                proposal = propose_plan_adjustment(
                    PlanAdjustmentInput(
                        planned_start=schedule.starts_at_utc,
                        planned_end=schedule.ends_at_utc,
                        actual_start=actual.actual_start,
                        actual_end=actual_end,
                        rule_version=payload.rule_version,
                    )
                )
            except ValueError:
                raise domain_error(
                    "W3_RUN_STATE_INVALID",
                    422,
                    details={
                        "reason": "INVALID_PLAN_ADJUSTMENT_INPUT",
                        "business_write_count": 0,
                    },
                ) from None
            if (
                proposal.status is not ProposalStatus.PROPOSED
                or proposal.candidate_start is None
                or proposal.candidate_end is None
            ):
                raise domain_error(
                    "W3_PLAN_REVIEW_PENDING",
                    422,
                    details={
                        "reason": proposal.reason,
                        "candidate_duration_seconds": list(
                            proposal.candidate_duration_seconds
                        ),
                        "candidate_windows": [
                            {
                                "start": item.start.isoformat(),
                                "end": item.end.isoformat(),
                                "total_error_seconds": item.total_error_seconds,
                            }
                            for item in proposal.candidate_windows
                        ],
                        "business_write_count": 0,
                    },
                )

            before_start = schedule.starts_at_utc
            before_end = schedule.ends_at_utc
            schedule.starts_at_utc = proposal.candidate_start
            schedule.ends_at_utc = proposal.candidate_end
            schedule.updated_by_account_id = account.id
            schedule.updated_at_utc = datetime.now(UTC)
            schedule.row_version += 1
            month_control.updated_by_account_id = account.id
            month_control.updated_at_utc = datetime.now(UTC)
            month_control.row_version += 1
            event_payload = {
                "actual_work_revision_id": actual.id,
                "w2_schedule_id": schedule.id,
                "rule_version": payload.rule_version,
                "prior_planned_start": before_start,
                "prior_planned_end": before_end,
                "adopted_planned_start": proposal.candidate_start,
                "adopted_planned_end": proposal.candidate_end,
                "expected_schedule_row_version": payload.expected_schedule_row_version,
                "adopted_schedule_row_version": schedule.row_version,
                "expected_month_row_version": payload.expected_month_row_version,
                "adopted_month_row_version": month_control.row_version,
                "reason": payload.reason.strip(),
            }
            event = W3PlanAdjustmentEvent(
                actual_work_revision_id=actual.id,
                w2_schedule_id=schedule.id,
                rule_version=payload.rule_version,
                prior_planned_start=before_start,
                prior_planned_end=before_end,
                adopted_planned_start=proposal.candidate_start,
                adopted_planned_end=proposal.candidate_end,
                expected_schedule_row_version=payload.expected_schedule_row_version,
                adopted_schedule_row_version=schedule.row_version,
                expected_month_row_version=payload.expected_month_row_version,
                adopted_month_row_version=month_control.row_version,
                reason=payload.reason.strip(),
                event_digest=_digest(event_payload),
                command_idempotency_key=payload.command_idempotency_key,
                created_by_account_id=account.id,
            )
            self.session.add(event)
            self.session.add(
                AuditEvent(
                    occurred_at_utc=datetime.now(UTC),
                    actor_account_id=account.id,
                    actor_kind="USER",
                    action_code="W3_PLAN_ADJUSTMENT_ADOPT",
                    entity_type="w2_schedule",
                    entity_pk=schedule.id,
                    before_json={
                        "starts_at_utc": before_start.isoformat(),
                        "ends_at_utc": before_end.isoformat(),
                        "row_version": payload.expected_schedule_row_version,
                    },
                    after_json={
                        "starts_at_utc": proposal.candidate_start.isoformat(),
                        "ends_at_utc": proposal.candidate_end.isoformat(),
                        "row_version": schedule.row_version,
                        "w3_actual_work_revision_id": actual.id,
                    },
                    reason_code="W3_RFID_ACTUAL_ALIGNMENT",
                    reason_text=payload.reason.strip(),
                    source_run_id=None,
                    request_id=self.request_id,
                    created_from="W3_API",
                )
            )
            self.session.flush()
            self._commit()
        except Exception as error:
            self._rollback_and_raise(error)
        return self._plan_adjustment_response(event, month_control.row_version)

    @staticmethod
    def _plan_adjustment_response(
        event: W3PlanAdjustmentEvent,
        month_row_version: int,
    ) -> W3PlanAdjustmentResponse:
        return W3PlanAdjustmentResponse(
            id=event.id,
            actual_work_revision_id=event.actual_work_revision_id,
            w2_schedule_id=event.w2_schedule_id,
            rule_version=event.rule_version,
            adopted_planned_start=event.adopted_planned_start,
            adopted_planned_end=event.adopted_planned_end,
            schedule_row_version=event.adopted_schedule_row_version,
            month_row_version=month_row_version,
            created_at_utc=event.created_at_utc,
        )
