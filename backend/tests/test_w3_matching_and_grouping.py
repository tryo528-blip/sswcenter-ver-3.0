from __future__ import annotations

import inspect
from collections import Counter
from dataclasses import fields
from datetime import date
from pathlib import Path

from app.domains.w3.matching import (
    MatchRequest,
    MatchStatus,
    ScheduleMatchCandidate,
    StableStaffMappingCandidate,
    match_unique_schedule,
)
from app.domains.w3.nhis_grouping import derive_nhis_groups
from app.domains.w3.workbook_parser import parse_nhis_schedule_workbook

WORKBOOK = (
    Path(__file__).parent / "fixtures" / "w3" / "workbooks" / "nhis_schedule_202607_v1.xlsx"
).read_bytes()


def _staff(
    mapping_id: int,
    staff_id: int,
    *,
    active: bool = True,
    source_external_number: str | None = None,
) -> StableStaffMappingCandidate:
    return StableStaffMappingCandidate(
        mapping_id=mapping_id,
        staff_id=staff_id,
        source_external_number=source_external_number or f"SYNTHETIC-{mapping_id}",
        mapping_active=active,
        employment_valid=True,
        care_worker_position_valid=True,
    )


def _schedule(schedule_id: int, staff_id: int, *, valid: bool = True) -> ScheduleMatchCandidate:
    return ScheduleMatchCandidate(
        schedule_id=schedule_id,
        staff_id=staff_id,
        recipient_certification_valid=valid,
        contract_valid=True,
        assignment_valid=True,
        target_date_valid=True,
        service_valid=True,
        time_window_valid=True,
        conflict_free=True,
        manual_protection_clear=True,
        month_unfinalized=True,
    )


def test_nhis_grouping_preserves_all_rows_and_real_240_480_shape() -> None:
    parsed = parse_nhis_schedule_workbook(WORKBOOK, target_month=date(2026, 7, 1))
    groups = derive_nhis_groups(parsed.target_rows)

    assert len(groups) == 887
    assert sum(len(group.source_row_numbers) for group in groups) == 910
    assert Counter(len(group.source_row_numbers) for group in groups) == {1: 864, 2: 23}
    assert sum(group.declared_minutes == 240 for group in groups) == 69
    assert (
        sum(
            group.declared_minutes == 480 and len(group.source_row_numbers) == 2 for group in groups
        )
        == 19
    )
    assert all(group.automatic_row_delete_count == 0 for group in groups)
    assert all(
        len(group.source_occurrence_identities) == len(group.source_row_numbers) for group in groups
    )


def test_nhis_grouping_is_order_independent_without_reusing_row_number_as_identity() -> None:
    parsed = parse_nhis_schedule_workbook(WORKBOOK, target_month=date(2026, 7, 1))
    forward = derive_nhis_groups(parsed.target_rows)
    reverse = derive_nhis_groups(tuple(reversed(parsed.target_rows)))

    assert {group.group_signature for group in forward} == {
        group.group_signature for group in reverse
    }
    assert {
        group.group_signature: set(group.source_occurrence_identities) for group in forward
    } == {group.group_signature: set(group.source_occurrence_identities) for group in reverse}


def test_matcher_is_stable_mapping_only_and_has_no_name_phone_tiebreak_input() -> None:
    staff_fields = {field.name for field in fields(StableStaffMappingCandidate)}
    request_fields = {field.name for field in fields(MatchRequest)}
    source = inspect.getsource(match_unique_schedule)

    assert "name" not in staff_fields
    assert "phone" not in staff_fields
    assert "name" not in request_fields
    assert "phone" not in request_fields
    assert "name" not in source
    assert "phone" not in source


def test_matcher_returns_review_for_zero_or_many_stable_staff_mappings() -> None:
    zero = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-OCCURRENCE-0",
            source_staff_external_number="SYNTHETIC-1",
            staff_mapping_candidates=(),
            schedule_candidates=(_schedule(10, 7),),
        )
    )
    many = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-OCCURRENCE-N",
            source_staff_external_number="SYNTHETIC-1",
            staff_mapping_candidates=(
                _staff(1, 7),
                _staff(2, 7, source_external_number="SYNTHETIC-1"),
            ),
            schedule_candidates=(_schedule(10, 7),),
        )
    )

    assert zero.status is many.status is MatchStatus.REVIEW_PENDING
    assert zero.reason == "STAFF_MATCH_ZERO"
    assert many.reason == "STAFF_MATCH_MANY"
    assert zero.automatic_match_count == many.automatic_match_count == 0
    assert zero.business_write_count == many.business_write_count == 0


def test_matcher_requires_an_exact_source_stable_key_without_name_phone_fallback() -> None:
    missing_key = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-NO-STAFF-KEY",
            source_staff_external_number=None,
            staff_mapping_candidates=(_staff(1, 7),),
            schedule_candidates=(_schedule(10, 7),),
        )
    )
    mismatched_key = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-WRONG-STAFF-KEY",
            source_staff_external_number="SYNTHETIC-OTHER",
            staff_mapping_candidates=(_staff(1, 7),),
            schedule_candidates=(_schedule(10, 7),),
        )
    )

    assert missing_key.status is mismatched_key.status is MatchStatus.REVIEW_PENDING
    assert missing_key.reason == "STAFF_STABLE_KEY_MISSING"
    assert mismatched_key.reason == "STAFF_MATCH_ZERO"
    assert missing_key.automatic_match_count == mismatched_key.automatic_match_count == 0
    assert missing_key.business_write_count == mismatched_key.business_write_count == 0


def test_matcher_auto_matches_exactly_one_fully_valid_schedule() -> None:
    result = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-OCCURRENCE-1",
            source_staff_external_number="SYNTHETIC-1",
            staff_mapping_candidates=(_staff(1, 7),),
            schedule_candidates=(
                _schedule(10, 7, valid=False),
                _schedule(11, 7),
                _schedule(12, 9),
            ),
        )
    )

    assert result.status is MatchStatus.AUTO_MATCH
    assert result.reason == "UNIQUE_VALID_CANDIDATE"
    assert result.staff_id == 7
    assert result.schedule_id == 11
    assert result.automatic_match_count == 1
    assert result.business_write_count == 0


def test_matcher_returns_review_for_zero_or_many_schedule_candidates_without_first_bias() -> None:
    mapping = (_staff(1, 7),)
    zero = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-SCHEDULE-0",
            source_staff_external_number="SYNTHETIC-1",
            staff_mapping_candidates=mapping,
            schedule_candidates=(_schedule(10, 7, valid=False),),
        )
    )
    candidates = (_schedule(12, 7), _schedule(11, 7))
    many = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-SCHEDULE-N",
            source_staff_external_number="SYNTHETIC-1",
            staff_mapping_candidates=mapping,
            schedule_candidates=candidates,
        )
    )
    reversed_many = match_unique_schedule(
        MatchRequest(
            source_occurrence_identity="SYNTHETIC-SCHEDULE-N",
            source_staff_external_number="SYNTHETIC-1",
            staff_mapping_candidates=mapping,
            schedule_candidates=tuple(reversed(candidates)),
        )
    )

    assert zero.status is many.status is MatchStatus.REVIEW_PENDING
    assert zero.reason == "SCHEDULE_MATCH_ZERO"
    assert many.reason == "SCHEDULE_MATCH_MANY"
    assert many == reversed_many
    assert many.schedule_id is None
    assert many.automatic_match_count == 0
    assert many.business_write_count == 0
