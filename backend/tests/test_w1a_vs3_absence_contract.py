from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0005_w1a_staff_training.py"
GENERATED_OPENAPI = REPO_ROOT / "frontend" / "src" / "generated" / "sswcenter-api.ts"
FORBIDDEN_TOKENS = (
    "training_hours",
    "duration_minutes",
    "completion_date",
    "completed_date",
    "training_center",
    "completion_center",
    "file_id",
    "evidence_id",
    "task_id",
    "work_card_id",
)


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail(f"W1A_VS3_ABSENCE_HARNESS_FAILURE: could not read {path.name}")


def _backend_training_surface() -> str:
    app_root = REPO_ROOT / "backend" / "app"
    chunks: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        source = _read(path)
        lines = source.splitlines()
        for index, line in enumerate(lines):
            if "training" in line.lower():
                chunks.extend(lines[max(0, index - 5) : index + 35])
    return "\n".join(chunks)


def test_vs3_public_surface_has_no_forbidden_training_fields_or_relations() -> None:
    surface = _backend_training_surface()
    if not surface:
        return
    lowered = surface.lower()
    for token in FORBIDDEN_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            _fail("W1A_VS3_FORBIDDEN_DB_API_FIELD_FOUND: forbidden training field is present")
    if re.search(r"/training[^\n]*(?:file|task|work[-_ ]?card)", lowered):
        _fail("W1A_VS3_FORBIDDEN_ROUTE_FOUND: training file/task route is present")


def test_vs3_migration_and_generated_openapi_have_no_forbidden_structures() -> None:
    migration_surface = _read(MIGRATION) if MIGRATION.is_file() else ""
    generated = _read(GENERATED_OPENAPI)
    training_blocks = "\n".join(
        block for block in (migration_surface, generated) if "training" in block.lower()
    ).lower()
    for token in FORBIDDEN_TOKENS:
        if re.search(rf"\b{re.escape(token)}\b", training_blocks):
            _fail("W1A_VS3_FORBIDDEN_MIGRATION_OPENAPI_FIELD_FOUND: forbidden structure is present")


def test_vs3_absence_contract_does_not_accept_future_health_or_legacy_scope() -> None:
    surface = _read(MIGRATION).lower() if MIGRATION.is_file() else ""
    forbidden_scope = ("health_check", "quarterly_consultation", "legacy_mapping")
    if surface and any(token in surface for token in forbidden_scope):
        _fail("W1A_VS3_FORBIDDEN_SCOPE_FOUND: later micro-slice scope leaked into training")
