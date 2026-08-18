from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.domains.w3.source_intake import (
    AttemptStatus,
    IntakeClassification,
    SourceIntakeContext,
    classify_source_intake,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "w3"


def _source_cases() -> list[tuple[dict[str, object], dict[str, object]]]:
    inputs = json.loads(
        (FIXTURE_ROOT / "cases" / "source_intake_classification_v2.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "source_intake_classification_v2.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    expected_by_id = {case["case_id"]: case for case in expected}
    return [(case, expected_by_id[case["case_id"]]) for case in inputs]


@pytest.mark.parametrize(("case", "expected"), _source_cases())
def test_source_intake_classification_matches_approved_semantic_fixture(
    case: dict[str, object], expected: dict[str, object]
) -> None:
    context = SourceIntakeContext(
        same_content_digest=bool(case["same_content_digest"]),
        same_parser_profile=bool(case["same_parser_profile"]),
        equivalent_success_exists=bool(case["equivalent_success_exists"]),
        latest_attempt_status=str(case["latest_attempt_status"]),
    )

    result = classify_source_intake(context)

    assert result.classification is IntakeClassification(str(expected["classification"]))
    assert result.snapshot_identity == expected["snapshot_identity"]
    assert result.preserve_new_receipt is True
    assert result.new_apply_count == expected.get(
        "new_apply_count", expected.get("new_apply_count_before_confirm", 0)
    )
    assert result.superseded_count == expected.get(
        "superseded_before_confirm_count",
        expected.get("superseded_before_successful_apply_count", 0),
    )
    if "new_parse_count" in expected:
        assert result.new_parse_count == expected["new_parse_count"]
    if "retry_attempt_allowed" in expected:
        assert result.retry_attempt_allowed is expected["retry_attempt_allowed"]
    if "confirm_required" in expected:
        assert result.confirm_required is expected["confirm_required"]
    if "same_bytes_profile_bypass_allowed" in expected:
        assert (
            result.same_bytes_profile_bypass_allowed
            is expected["same_bytes_profile_bypass_allowed"]
        )
    assert classify_source_intake(context) == result


def test_source_intake_rejects_inconsistent_success_state() -> None:
    with pytest.raises(ValueError, match="success"):
        classify_source_intake(
            SourceIntakeContext(
                same_content_digest=True,
                same_parser_profile=True,
                equivalent_success_exists=True,
                latest_attempt_status="FAILED_RETRYABLE",
            )
        )


def test_source_intake_blocked_cannot_be_reupload_bypassed() -> None:
    result = classify_source_intake(
        SourceIntakeContext(
            same_content_digest=True,
            same_parser_profile=True,
            equivalent_success_exists=False,
            latest_attempt_status="BLOCKED",
        )
    )

    assert result.classification is IntakeClassification.BLOCKED_REUPLOAD_REJECTED
    assert result.same_bytes_profile_bypass_allowed is False
    assert result.new_parse_count == 0
    assert result.new_apply_count == 0
    assert result.superseded_count == 0


def test_source_intake_different_digest_never_supersedes_before_apply() -> None:
    result = classify_source_intake(
        SourceIntakeContext(
            same_content_digest=False,
            same_parser_profile=False,
            equivalent_success_exists=False,
            latest_attempt_status="NO_PRIOR_ATTEMPT",
        )
    )

    assert result.classification is IntakeClassification.CANDIDATE_NEW_SNAPSHOT
    assert result.active_snapshot_preserved is True
    assert result.superseded_count == 0
    assert result.new_apply_count == 0


HOSTILE_ATTEMPT_STATUSES = (
    "unknown",
    "blocked",
    "FAILED",
    "",
    " ",
    "FAILED_NONRETRYABLE",
    "IN_PROGRESS",
    " SUCCEEDED",
    "BLOCKED ",
    "succeeded",
)


@pytest.mark.parametrize("status", HOSTILE_ATTEMPT_STATUSES)
def test_source_intake_same_digest_profile_unknown_status_is_fail_closed(status: str) -> None:
    with pytest.raises(ValueError, match="attempt status"):
        classify_source_intake(
            SourceIntakeContext(
                same_content_digest=True,
                same_parser_profile=True,
                equivalent_success_exists=False,
                latest_attempt_status=status,
            )
        )


@pytest.mark.parametrize("status", HOSTILE_ATTEMPT_STATUSES)
def test_source_intake_hostile_status_does_not_open_new_digest_or_reparse(status: str) -> None:
    with pytest.raises(ValueError, match="attempt status"):
        classify_source_intake(
            SourceIntakeContext(
                same_content_digest=False,
                same_parser_profile=False,
                equivalent_success_exists=False,
                latest_attempt_status=status,
            )
        )
    with pytest.raises(ValueError, match="attempt status"):
        classify_source_intake(
            SourceIntakeContext(
                same_content_digest=True,
                same_parser_profile=False,
                equivalent_success_exists=False,
                latest_attempt_status=status,
            )
        )


def test_source_intake_closed_attempt_enum_has_no_start_profile_fallback() -> None:
    assert "START_PROFILE_RUN" not in IntakeClassification.__members__
    assert set(AttemptStatus) == {
        AttemptStatus.NO_PRIOR_ATTEMPT,
        AttemptStatus.SUCCEEDED,
        AttemptStatus.FAILED_RETRYABLE,
        AttemptStatus.BLOCKED,
    }


def test_source_intake_new_digest_rejects_fabricated_prior_result() -> None:
    for status in ("SUCCEEDED", "FAILED_RETRYABLE", "BLOCKED"):
        with pytest.raises(ValueError, match="no-prior-attempt"):
            classify_source_intake(
                SourceIntakeContext(
                    same_content_digest=False,
                    same_parser_profile=False,
                    equivalent_success_exists=False,
                    latest_attempt_status=status,
                )
            )


def test_source_intake_existing_digest_rejects_no_prior_state() -> None:
    for same_parser_profile in (True, False):
        with pytest.raises(ValueError, match="existing digest"):
            classify_source_intake(
                SourceIntakeContext(
                    same_content_digest=True,
                    same_parser_profile=same_parser_profile,
                    equivalent_success_exists=False,
                    latest_attempt_status="NO_PRIOR_ATTEMPT",
                )
            )


def test_historical_v1_v2_source_intake_fixture_bytes_remain_immutable() -> None:
    historical_hashes = {
        "cases/source_intake_semantic_v1.json": (
            "74e219df5389aa84d510e0a32c84ffd1946a2dad1f83a87b5c2b6ef52542a770"
        ),
        "expected/source_intake_semantic_v1.json": (
            "71a52401bb810ee954345db1710479b4a380b9c992e02d04c033d600c04ab05f"
        ),
        "cases/source_intake_reorder_semantic_v2.json": (
            "b30fe934333409e07aac5f7936733879e9eda784857864ae2dd9df940c04b6a1"
        ),
        "expected/source_intake_reorder_semantic_v2.json": (
            "e2e892da2aca02ba2686e00b27709442dcf53046e40ea1106b2143545fe61c1b"
        ),
    }
    for relative_path, expected_hash in historical_hashes.items():
        actual_hash = sha256((FIXTURE_ROOT / relative_path).read_bytes()).hexdigest()
        assert actual_hash == expected_hash


def test_source_intake_same_digest_profile_succeeded_without_equivalent_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="equivalent success"):
        classify_source_intake(
            SourceIntakeContext(
                same_content_digest=True,
                same_parser_profile=True,
                equivalent_success_exists=False,
                latest_attempt_status="SUCCEEDED",
            )
        )
