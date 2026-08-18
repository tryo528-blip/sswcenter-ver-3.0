"""Focused fail-closed revision coverage for the historical W2 0027 postcheck."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.postcheck_current_0027 import EXPECTED_REVISION, _verify_revision

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTCHECK = REPO_ROOT / "backend" / "app" / "db" / "postcheck_current_0027.py"
W2_LIVE_HARNESS = REPO_ROOT / "scripts" / "test-w2-0027-postgres-linux.ps1"


class _FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _FakeScalarResult:
        return self

    def all(self) -> list[object]:
        return list(self._values)


class _FakeRevisionConnection:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def execute(self, _statement: object, _params: object | None = None) -> _FakeScalarResult:
        return _FakeScalarResult(self._values)


def test_0027_revision_verifier_requires_exact_single_expected_row() -> None:
    _verify_revision(_FakeRevisionConnection([EXPECTED_REVISION]))  # type: ignore[arg-type]

    for revisions in (
        [],
        ["20260814_0026_w1e_care_assignment_family_relationship_lock"],
        [EXPECTED_REVISION, "w2_0027_rogue_second_head"],
    ):
        with pytest.raises(SystemExit, match="CURRENT_0027_REVISION_MISMATCH"):
            _verify_revision(_FakeRevisionConnection(revisions))  # type: ignore[arg-type]


def test_0027_historical_harness_rejects_rogue_second_head_without_markers() -> None:
    postcheck = POSTCHECK.read_text(encoding="utf-8")
    harness = W2_LIVE_HARNESS.read_text(encoding="utf-8")

    assert ".scalars()" in postcheck
    assert ".all()" in postcheck
    assert "revisions != [EXPECTED_REVISION]" in postcheck
    assert "CURRENT_0027_REVISION_MISMATCH" in postcheck

    assert '$RogueRevision = "w2_0027_rogue_second_head"' in harness
    assert "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_POSTCHECK_ACCEPTED" in harness
    assert "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_MISMATCH_MARKER_MISSING" in harness
    assert "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_HISTORICAL_MARKER_EMITTED" in harness
    assert "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_CURRENT_HEAD_MARKER_EMITTED" in harness
    assert "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_CLEANUP_FAILED" in harness
    assert "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_REJECTED" in harness

    # Single-row psql output must stay an array under StrictMode (PS 5.1 and 7).
    restored_at = harness.index("$RestoredRevisions = @(")
    foreach_token = "ForEach-Object { $_.ToString().Trim() }"
    where_token = 'Where-Object { $_ -ne "" }'
    foreach_at = harness.index(foreach_token, restored_at)
    where_at = harness.index(where_token, foreach_at)
    after_where = harness[where_at + len(where_token) :].lstrip()
    assert after_where.startswith(")")
    assert (
        "SELECT version_num FROM erp.alembic_version ORDER BY version_num"
        in harness[restored_at:where_at]
    )
    assert "$RestoredRevisions.Count -ne 1" in harness
    assert "$RestoredRevisions[0] -cne $CurrentRevision" in harness
