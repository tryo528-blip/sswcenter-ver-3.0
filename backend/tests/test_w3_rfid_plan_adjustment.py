from __future__ import annotations

import inspect
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.domains.w3.plan_adjustment import (
    PlanAdjustmentInput,
    ProposalStatus,
    propose_plan_adjustment,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "w3"


def _fixture_cases() -> list[tuple[dict[str, object], dict[str, object]]]:
    inputs = json.loads(
        (FIXTURE_ROOT / "cases" / "plan_adjustment_boundaries_v1.json").read_text(encoding="utf-8")
    )["cases"]
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "plan_adjustment_boundaries_v1.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    expected_by_id = {case["case_id"]: case for case in expected}
    return [(case, expected_by_id[case["case_id"]]) for case in inputs]


@pytest.mark.parametrize(("case", "expected"), _fixture_cases())
def test_plan_adjustment_matches_approved_boundary_fixture(
    case: dict[str, object], expected: dict[str, object]
) -> None:
    request = PlanAdjustmentInput(
        planned_start=datetime.fromisoformat(str(case["planned_start"])),
        planned_end=datetime.fromisoformat(str(case["planned_end"])),
        actual_start=datetime.fromisoformat(str(case["actual_start"])),
        actual_end=datetime.fromisoformat(str(case["actual_end"])),
        rule_version=str(case["rule_version"]),
    )
    before = deepcopy(request)

    result = propose_plan_adjustment(request)

    assert result.rule_version == case["rule_version"]
    assert result.status is ProposalStatus(str(expected["status"]))
    assert result.reason == expected["reason"]
    assert result.service_seconds == expected["service_seconds"]
    assert result.shortage_seconds == expected["shortage_seconds"]
    assert list(result.markers) == expected["markers"]
    assert list(result.candidate_duration_seconds) == expected["candidate_duration_seconds"]
    if "candidate_start" in expected:
        assert result.candidate_start == datetime.fromisoformat(str(expected["candidate_start"]))
        assert result.candidate_end == datetime.fromisoformat(str(expected["candidate_end"]))
    else:
        assert result.candidate_start is None
        assert result.candidate_end is None
    assert result.plan_write_count == 0
    assert result.event_write_count == 0
    assert result.audit_write_count == 0
    assert request == before
    assert propose_plan_adjustment(request) == result


def test_plan_adjustment_is_a_pure_proposal_seam() -> None:
    module = inspect.getmodule(propose_plan_adjustment)
    assert module is not None
    source = inspect.getsource(module)
    forbidden = (
        "sqlalchemy",
        "Session",
        "repository",
        "audit_log",
        "event_store",
        "commit(",
        "flush(",
    )

    assert all(token not in source for token in forbidden)
    signature = inspect.signature(propose_plan_adjustment)
    assert tuple(signature.parameters) == ("request",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("planned_start", "2026-08-17T09:00:01+09:00"),
        ("planned_end", "2026-08-17T10:05:00+09:00"),
    ],
)
def test_plan_adjustment_rejects_non_contract_plan_grid(field: str, value: str) -> None:
    planned_start = datetime.fromisoformat("2026-08-17T09:00:00+09:00")
    planned_end = datetime.fromisoformat("2026-08-17T10:00:00+09:00")
    if field == "planned_start":
        planned_start = datetime.fromisoformat(value)
    else:
        planned_end = datetime.fromisoformat(value)

    with pytest.raises(ValueError, match="planned"):
        propose_plan_adjustment(
            PlanAdjustmentInput(
                planned_start=planned_start,
                planned_end=planned_end,
                actual_start=datetime.fromisoformat("2026-08-17T09:00:00+09:00"),
                actual_end=datetime.fromisoformat("2026-08-17T10:00:00+09:00"),
                rule_version="w3-rfid-adjustment-v1",
            )
        )


def test_plan_adjustment_rejects_unknown_rule_version() -> None:
    request = PlanAdjustmentInput(
        planned_start=datetime.fromisoformat("2026-08-17T09:00:00+09:00"),
        planned_end=datetime.fromisoformat("2026-08-17T10:00:00+09:00"),
        actual_start=datetime.fromisoformat("2026-08-17T09:00:00+09:00"),
        actual_end=datetime.fromisoformat("2026-08-17T10:00:00+09:00"),
        rule_version="unknown-rule",
    )

    with pytest.raises(ValueError, match="rule_version"):
        propose_plan_adjustment(request)
