"""RED-first contract tests for the current-head 0025 foundation slice."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
DISPATCHER_PATH = BACKEND_ROOT / "app" / "db" / "postcheck_dispatch.py"
INIT_PATH = BACKEND_ROOT / "app" / "db" / "init_development.py"
RESTORE_PATH = REPO_ROOT / "scripts" / "restore-drill.ps1"
HARNESS_PATH = REPO_ROOT / "scripts" / "test-foundation-0025-postgres.ps1"

CURRENT_REVISION = "20260813_0025_w1_relationship_lock_contract_correction"
CURRENT_MARKER = "SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK"
HEAD_MARKER = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"


def _load_dispatcher() -> Any:
    try:
        return importlib.import_module("app.db.postcheck_dispatch")
    except ModuleNotFoundError as exc:  # RED marker before implementation.
        pytest.fail(f"FOUNDATION_0025_DISPATCHER_MISSING: {exc}")


class _RevisionResult:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self) -> _RevisionResult:
        return self

    def all(self) -> list[str]:
        return self._values


class _RevisionConnection:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def execute(self, _statement: object) -> _RevisionResult:
        return _RevisionResult(self.values)


def test_dispatcher_module_and_exact_revision_contract(capsys: pytest.CaptureFixture[str]) -> None:
    dispatcher = _load_dispatcher()
    assert DISPATCHER_PATH.is_file()
    assert dispatcher.CURRENT_REVISION == CURRENT_REVISION

    # Isolate revision routing from the large current catalog checker here.
    dispatcher.verify_current_0025 = lambda _connection: None
    revision = dispatcher.dispatch_current_head(_RevisionConnection([CURRENT_REVISION]))

    assert revision == CURRENT_REVISION
    output = capsys.readouterr().out
    assert CURRENT_MARKER in output
    assert HEAD_MARKER in output


@pytest.mark.parametrize("values", [[], [CURRENT_REVISION, CURRENT_REVISION], ["future_revision"]])
def test_dispatcher_fails_closed_for_missing_multiple_or_future_revision(
    values: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    dispatcher = _load_dispatcher()
    dispatcher.verify_current_0025 = lambda _connection: None

    with pytest.raises(SystemExit):
        dispatcher.dispatch_current_head(_RevisionConnection(values))

    assert CURRENT_MARKER not in capsys.readouterr().out
    assert HEAD_MARKER not in capsys.readouterr().out


def test_development_init_routes_to_current_dispatcher() -> None:
    source = INIT_PATH.read_text(encoding="utf-8")
    assert "postcheck_dispatch" in source
    assert "postcheck_w1a_vs1" not in source
    assert re.search(r"dispatch_current_head|run_current_head_postcheck", source)


def test_restore_drill_has_exact_0025_branch_and_markers() -> None:
    source = RESTORE_PATH.read_text(encoding="utf-8")
    assert CURRENT_REVISION in source
    assert CURRENT_MARKER in source
    assert HEAD_MARKER in source
    assert "20260812_0019_r0_w2_read_only" in source
    assert "20260813_0020_w1_staff_contract_correction" not in source


def test_foundation_harness_contract_is_present() -> None:
    assert HARNESS_PATH.is_file(), "FOUNDATION_0025_HARNESS_MISSING"
    source = HARNESS_PATH.read_text(encoding="utf-8")
    for marker in (
        "FOUNDATION_0025_INIT_GREEN",
        "FOUNDATION_0025_BACKUP_GREEN",
        "FOUNDATION_0025_RESTORE_GREEN",
        "FOUNDATION_0025_CLEANUP",
        "FOUNDATION_0025_POSTGRES_GREEN",
    ):
        assert marker in source
    assert "ExpectedSha" in source
