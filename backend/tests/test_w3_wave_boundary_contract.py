from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "w3"


def test_w3_decision_seal_records_all_approved_values() -> None:
    seal = (ROOT / "review/evidence/W3_20260817_USER_DECISION_SEAL.md").read_text(encoding="utf-8")
    approved = (
        "FILE_ONLY",
        "SINGLE_STATEFUL_WORKSPACE",
        "STABLE_MAPPING_ONLY",
        "UNIQUE_ONLY_ELSE_REVIEW",
        "DUAL_IDENTITY",
        "RAW_ROWS_PLUS_DERIVED_GROUP",
        "W3_PRIVATE_CONTENT_RECEIPT_TYPED_LINK",
        "VERSIONED_MANUAL_SUPPLEMENT",
        "REVIEW_PENDING",
    )

    assert all(value in seal for value in approved)
    assert "W4 계산·청구·수납" in seal
    assert "W5 범용 파일함·OCR·공식 출력·제품 복구" in seal


def test_missing_workbook_profiles_are_explicitly_blocked() -> None:
    for name in ("nhis_schedule_v0.blocked.json", "rfid_v0.blocked.json"):
        profile = json.loads((FIXTURE_ROOT / "profiles" / name).read_text(encoding="utf-8"))
        assert profile["status"] == "BLOCKED_HEADER_PROFILE_MISSING"
        assert profile["sheet_names"] is None
        assert profile["headers"] is None
        assert profile["required_columns"] is None
        assert profile["macro_execution"] is False
        assert profile["contains_pii"] is False


def test_no_parser_ready_workbook_is_claimed_without_a_profile() -> None:
    assert not list(FIXTURE_ROOT.rglob("*.xlsx"))
    readme = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "실제 외부 workbook shape로" not in readme
    assert "parser-ready `.xlsx`: 없음" in readme


def test_semantic_fixtures_preserve_raw_rows_and_zero_partial_apply() -> None:
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "source_intake_semantic_v1.json").read_text(encoding="utf-8")
    )
    raw_by_id = {case["case_id"]: case for case in expected["raw_row_cases"]}

    assert raw_by_id["W3-NHIS-240-480"]["raw_rows_preserved"] == 3
    assert raw_by_id["W3-NHIS-240-480"]["automatic_row_deletes"] == 0
    assert raw_by_id["W3-RFID-SAME-TIME-OCCURRENCE"]["occurrence_count"] == 2
    assert expected["global"]["blocked_partial_apply_count"] == 0
    assert expected["global"]["generic_target_type_target_id_allowed"] is False


def test_reorder_semantic_v2_preserves_v1_bytes_and_occurrence_meaning() -> None:
    v1_cases = json.loads(
        (FIXTURE_ROOT / "cases" / "source_intake_semantic_v1.json").read_text(encoding="utf-8")
    )
    v1_expected = json.loads(
        (FIXTURE_ROOT / "expected" / "source_intake_semantic_v1.json").read_text(encoding="utf-8")
    )
    v2_cases = json.loads(
        (FIXTURE_ROOT / "cases" / "source_intake_reorder_semantic_v2.json").read_text(
            encoding="utf-8"
        )
    )
    v2_expected = json.loads(
        (FIXTURE_ROOT / "expected" / "source_intake_reorder_semantic_v2.json").read_text(
            encoding="utf-8"
        )
    )

    assert v1_cases["fixture_version"] == "w3-source-intake-cases-v1"
    assert v2_cases["fixture_version"] == "w3-source-intake-reorder-cases-v2"
    assert v2_cases["parent_fixture"] == "source_intake_semantic_v1"

    parent_rows = next(
        case["semantic_rows"]
        for case in v1_cases["raw_row_cases"]
        if case["case_id"] == "W3-NHIS-240-480"
    )
    reordered = next(
        case["semantic_rows"]
        for case in v2_cases["raw_row_cases"]
        if case["case_id"] == "W3-NHIS-240-480-REORDERED"
    )
    assert parent_rows != reordered
    assert sorted(row["receipt_row"] for row in parent_rows) == sorted(
        row["receipt_row"] for row in reordered
    )
    parent_keys = {
        (row["receipt_row"], row["declared_minutes"], row["synthetic_service_key"])
        for row in parent_rows
    }
    reordered_keys = {
        (row["receipt_row"], row["declared_minutes"], row["synthetic_service_key"])
        for row in reordered
    }
    assert parent_keys == reordered_keys

    expected_by_id = {case["case_id"]: case for case in v2_expected["raw_row_cases"]}
    nhis = expected_by_id["W3-NHIS-240-480-REORDERED"]
    rfid = expected_by_id["W3-RFID-SAME-TIME-OCCURRENCE-REORDERED"]
    assert nhis["raw_rows_preserved"] == 3
    assert nhis["automatic_row_deletes"] == 0
    assert nhis["row_number_is_business_key"] is False
    assert nhis["array_index_is_business_key"] is False
    assert nhis["occurrence_meaning_preserved"] is True
    assert nhis["occurrence_by_synthetic_key"] == {"A": 2, "B": 1}
    assert rfid["raw_rows_preserved"] == 2
    assert rfid["automatic_row_deletes"] == 0
    assert rfid["row_number_is_business_key"] is False
    assert rfid["array_index_is_business_key"] is False
    assert rfid["occurrence_count"] == 2
    assert v1_expected["raw_row_cases"][0]["case_id"] == "W3-NHIS-240-480"


def test_physical_reorder_v3_preserves_prior_receipt_rows_without_row_key_reuse() -> None:
    v1_cases = json.loads(
        (FIXTURE_ROOT / "cases" / "source_intake_semantic_v1.json").read_text(encoding="utf-8")
    )
    v3_cases = json.loads(
        (FIXTURE_ROOT / "cases" / "source_intake_physical_reorder_v3.json").read_text(
            encoding="utf-8"
        )
    )
    v3_expected = json.loads(
        (FIXTURE_ROOT / "expected" / "source_intake_physical_reorder_v3.json").read_text(
            encoding="utf-8"
        )
    )

    assert v3_cases["fixture_version"] == "w3-source-intake-physical-reorder-v3"
    assert v3_cases["parent_fixture"] == "source_intake_semantic_v1"
    assert v3_cases["contains_pii"] is False
    parent_by_id = {case["case_id"]: case for case in v1_cases["raw_row_cases"]}
    expected_by_id = {case["case_id"]: case for case in v3_expected["raw_row_cases"]}

    for case in v3_cases["raw_row_cases"]:
        parent = parent_by_id[case["parent_case_id"]]
        expected = expected_by_id[case["case_id"]]
        parent_rows = parent["semantic_rows"]
        replacement_rows = case["semantic_rows"]
        assert case["new_receipt_ref"].startswith("RECEIPT-REUPLOAD-")
        assert len(parent_rows) == len(replacement_rows) == expected["raw_rows_preserved"]
        assert expected["prior_receipt_raw_rows_preserved"] == len(parent_rows)
        assert {row["receipt_row"] for row in parent_rows}.isdisjoint(
            {row["receipt_row"] for row in replacement_rows}
        )
        assert expected["physical_addresses_changed"] is True
        assert expected["row_number_is_business_key"] is False
        assert expected["array_index_is_business_key"] is False
        assert expected["semantic_occurrence_count_preserved"] is True
        assert expected["business_signature_collapse_allowed"] is False
        assert expected["automatic_row_deletes"] == 0

    nhis = next(
        case
        for case in v3_cases["raw_row_cases"]
        if case["case_id"] == "W3-NHIS-240-480-PHYSICAL-REORDER"
    )
    nhis_values = sorted(
        (row["declared_minutes"], row["synthetic_service_key"]) for row in nhis["semantic_rows"]
    )
    assert nhis_values == [(240, "A"), (240, "A"), (480, "B")]
    assert expected_by_id[nhis["case_id"]]["occurrence_by_synthetic_key"] == {"A": 2, "B": 1}


def test_matching_and_supplement_loader_reads_id_sets_and_core_expected() -> None:
    cases = json.loads(
        (FIXTURE_ROOT / "cases" / "matching_and_supplement_semantic_v1.json").read_text(
            encoding="utf-8"
        )
    )
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "matching_and_supplement_semantic_v1.json").read_text(
            encoding="utf-8"
        )
    )

    matching_case_ids = {case["case_id"] for case in cases["matching_cases"]}
    matching_expected_ids = {case["case_id"] for case in expected["matching_cases"]}
    supplement_case_ids = {case["case_id"] for case in cases["supplement_cases"]}
    supplement_expected_ids = {case["case_id"] for case in expected["supplement_cases"]}

    assert (
        matching_case_ids
        == matching_expected_ids
        == {
            "W3-MATCH-ZERO",
            "W3-MATCH-ONE",
            "W3-MATCH-MANY",
            "W3-STAFF-KEY-REUSED",
        }
    )
    assert (
        supplement_case_ids
        == supplement_expected_ids
        == {
            "W3-SUPPLEMENT-CREATE",
            "W3-SUPPLEMENT-CANCEL",
            "W3-SUPPLEMENT-REPLACE",
            "W3-SUPPLEMENT-STALE",
            "W3-SUPPLEMENT-FINALIZED",
        }
    )

    matching = {case["case_id"]: case for case in expected["matching_cases"]}
    supplement = {case["case_id"]: case for case in expected["supplement_cases"]}
    assert matching["W3-MATCH-ZERO"] == {
        "case_id": "W3-MATCH-ZERO",
        "result": "REVIEW_PENDING",
        "automatic_match_count": 0,
    }
    assert matching["W3-MATCH-ONE"]["automatic_match_count"] == 1
    assert matching["W3-MATCH-MANY"]["automatic_match_count"] == 0
    assert matching["W3-STAFF-KEY-REUSED"]["name_or_phone_tiebreak_allowed"] is False
    assert supplement["W3-SUPPLEMENT-CREATE"]["source_bytes_changed"] is False
    assert supplement["W3-SUPPLEMENT-STALE"]["write_count"] == 0
    assert supplement["W3-SUPPLEMENT-FINALIZED"]["result"] == "REJECT_FINALIZED_MONTH"
    assert cases["contains_pii"] is False
