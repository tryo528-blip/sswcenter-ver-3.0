from __future__ import annotations

from datetime import date, datetime

import pytest

from app.domains.w3.reconciliation import (
    AppliedFact,
    CandidateFact,
    ReconciliationInput,
    ReconciliationStatus,
    plan_snapshot_reconciliation,
)
from app.domains.w3.supplement import (
    SupplementAction,
    SupplementCommand,
    SupplementResult,
    plan_manual_supplement,
)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_reconciliation_blocks_unconfirmed_review_or_duplicate_candidate_without_writes() -> None:
    base = dict(
        source_type="RFID",
        target_date=date(2026, 7, 6),
        active_snapshot_id=10,
        candidate_snapshot_id=11,
        current_facts=(),
    )
    unconfirmed = plan_snapshot_reconciliation(
        ReconciliationInput(
            **base,
            confirmed=False,
            blocking_count=0,
            review_pending_count=0,
            candidate_facts=(),
        )
    )
    review = plan_snapshot_reconciliation(
        ReconciliationInput(
            **base,
            confirmed=True,
            blocking_count=0,
            review_pending_count=1,
            candidate_facts=(),
        )
    )
    duplicate = plan_snapshot_reconciliation(
        ReconciliationInput(
            **base,
            confirmed=True,
            blocking_count=0,
            review_pending_count=0,
            candidate_facts=(
                CandidateFact("OCCURRENCE-A", "a" * 64),
                CandidateFact("OCCURRENCE-A", "b" * 64),
            ),
        )
    )

    assert unconfirmed.status is ReconciliationStatus.CONFIRM_REQUIRED
    assert review.status is ReconciliationStatus.REVIEW_PENDING
    assert duplicate.status is ReconciliationStatus.BLOCKED
    assert unconfirmed.business_write_count == 0
    assert review.business_write_count == 0
    assert duplicate.business_write_count == 0
    assert duplicate.operations == ()


def test_reconciliation_versions_changed_facts_and_never_deletes_history() -> None:
    result = plan_snapshot_reconciliation(
        ReconciliationInput(
            source_type="RFID",
            target_date=date(2026, 7, 6),
            active_snapshot_id=10,
            candidate_snapshot_id=11,
            confirmed=True,
            blocking_count=0,
            review_pending_count=0,
            current_facts=(
                AppliedFact(101, "OCCURRENCE-KEEP", "a" * 64),
                AppliedFact(102, "OCCURRENCE-CHANGE", "b" * 64),
                AppliedFact(103, "OCCURRENCE-REMOVE", "c" * 64),
            ),
            candidate_facts=(
                CandidateFact("OCCURRENCE-NEW", "d" * 64),
                CandidateFact("OCCURRENCE-CHANGE", "e" * 64),
                CandidateFact("OCCURRENCE-KEEP", "a" * 64),
            ),
        )
    )

    assert result.status is ReconciliationStatus.APPLY_READY
    assert [(operation.kind, operation.business_key) for operation in result.operations] == [
        ("SUPERSEDE", "OCCURRENCE-CHANGE"),
        ("INSERT", "OCCURRENCE-CHANGE"),
        ("KEEP", "OCCURRENCE-KEEP"),
        ("INSERT", "OCCURRENCE-NEW"),
        ("SUPERSEDE", "OCCURRENCE-REMOVE"),
    ]
    assert result.history_delete_count == 0
    assert result.active_snapshot_before == 10
    assert result.active_snapshot_after == 11
    assert result.planned_insert_count == 2
    assert result.planned_supersede_count == 2
    assert result.business_write_count == 0


def test_reconciliation_exact_reapply_is_deterministic_noop() -> None:
    request = ReconciliationInput(
        source_type="RFID",
        target_date=date(2026, 7, 6),
        active_snapshot_id=10,
        candidate_snapshot_id=10,
        confirmed=True,
        blocking_count=0,
        review_pending_count=0,
        current_facts=(AppliedFact(101, "OCCURRENCE-A", "a" * 64),),
        candidate_facts=(CandidateFact("OCCURRENCE-A", "a" * 64),),
    )

    first = plan_snapshot_reconciliation(request)
    second = plan_snapshot_reconciliation(request)

    assert first == second
    assert first.status is ReconciliationStatus.DUPLICATE_NOOP
    assert first.planned_insert_count == first.planned_supersede_count == 0
    assert first.business_write_count == 0


@pytest.mark.parametrize(
    ("action", "current_version", "currently_active", "expected_result"),
    [
        (SupplementAction.CREATE, 0, False, SupplementResult.VERSION_CREATED),
        (SupplementAction.CANCEL, 1, True, SupplementResult.CANCEL_EVENT_CREATED),
        (SupplementAction.REPLACE, 2, True, SupplementResult.REPLACEMENT_VERSION_CREATED),
        (SupplementAction.REPLACE, 3, False, SupplementResult.REPLACEMENT_VERSION_CREATED),
    ],
)
def test_manual_supplement_plans_versioned_append_only_events(
    action: SupplementAction,
    current_version: int,
    currently_active: bool,
    expected_result: SupplementResult,
) -> None:
    command = SupplementCommand(
        source_occurrence_identity="SYNTHETIC-START-ONLY",
        source_event_state="START_ONLY",
        source_actual_start=_ts("2026-07-06T09:00:01+09:00"),
        action=action,
        expected_row_version=current_version,
        current_row_version=current_version,
        currently_active=currently_active,
        proposed_actual_end=(
            None if action is SupplementAction.CANCEL else _ts("2026-07-06T10:00:02+09:00")
        ),
        reason="가명 보완 근거",
        month_finalized=False,
    )

    result = plan_manual_supplement(command)

    assert result.result is expected_result
    assert result.event_to_append is not None
    assert result.event_to_append.row_version == current_version + 1
    assert result.event_to_append.prior_row_version == (current_version or None)
    assert result.source_bytes_changed is False
    assert result.history_delete_count == 0
    assert result.planned_event_count == 1
    assert result.business_write_count == 0


def test_manual_supplement_rejects_stale_or_finalized_month_without_event() -> None:
    stale = plan_manual_supplement(
        SupplementCommand(
            source_occurrence_identity="SYNTHETIC-START-ONLY",
            source_event_state="START_ONLY",
            source_actual_start=_ts("2026-07-06T09:00:01+09:00"),
            action=SupplementAction.REPLACE,
            expected_row_version=2,
            current_row_version=3,
            currently_active=True,
            proposed_actual_end=_ts("2026-07-06T10:00:02+09:00"),
            reason="stale 가명 보완",
            month_finalized=False,
        )
    )
    finalized = plan_manual_supplement(
        SupplementCommand(
            source_occurrence_identity="SYNTHETIC-START-ONLY",
            source_event_state="START_ONLY",
            source_actual_start=_ts("2026-07-06T09:00:01+09:00"),
            action=SupplementAction.CREATE,
            expected_row_version=0,
            current_row_version=0,
            currently_active=False,
            proposed_actual_end=_ts("2026-07-06T10:00:02+09:00"),
            reason="확정월 가명 보완",
            month_finalized=True,
        )
    )

    assert stale.result is SupplementResult.REJECT_409
    assert finalized.result is SupplementResult.REJECT_FINALIZED_MONTH
    assert stale.event_to_append is finalized.event_to_append is None
    assert stale.planned_event_count == finalized.planned_event_count == 0
    assert stale.business_write_count == finalized.business_write_count == 0


def test_manual_supplement_rejects_non_start_only_source() -> None:
    with pytest.raises(ValueError, match="START_ONLY"):
        plan_manual_supplement(
            SupplementCommand(
                source_occurrence_identity="SYNTHETIC-COMPLETE",
                source_event_state="COMPLETE",
                source_actual_start=_ts("2026-07-06T09:00:01+09:00"),
                action=SupplementAction.CREATE,
                expected_row_version=0,
                current_row_version=0,
                currently_active=False,
                proposed_actual_end=_ts("2026-07-06T10:00:02+09:00"),
                reason="불가",
                month_finalized=False,
            )
        )
