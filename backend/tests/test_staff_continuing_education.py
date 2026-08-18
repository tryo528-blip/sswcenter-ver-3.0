import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db import postcheck_w1a_vs1 as postcheck_w1a_vs1
from app.domains.staff.schemas import TrainingCycleType
from app.domains.staff.service import StaffService

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260802_0013_staff_continuing_education.py"
)
MIGRATION_0014 = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260803_0014_recipient_plan_notification.py"
)
POSTCHECK = REPO_ROOT / "backend" / "app" / "db" / "postcheck_w1a_vs1.py"
RESTORE_DRILL = REPO_ROOT / "scripts" / "restore-drill.ps1"
RPN_WRAPPER = (
    REPO_ROOT / "backend" / "scripts" / "test-0014-recipient-plan-notification-postgres.ps1"
)
FRONTEND_PACKAGE = REPO_ROOT / "frontend" / "package.json"
TEST_SCRIPT = REPO_ROOT / "scripts" / "test.ps1"

RECIPIENT_PLAN_REVISION = "20260803_0014_recipient_plan_notification"
RECIPIENT_PLAN_MARKER = "RECIPIENT_PLAN_NOTIFICATION_DB_POSTCHECK_OK"


def test_continuing_education_migration_extends_catalog_without_rewriting_vs3() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "20260801_0012_w1e_care_assignment" in source
    assert "CONTINUING_EDUCATION" in source
    assert "'보수교육', 'BIENNIAL'" in source
    assert source.count("op.f(_CYCLE_CONSTRAINT)") == 4
    assert TrainingCycleType.BIENNIAL.value == "BIENNIAL"


def test_biennial_training_uses_a_calendar_year_period() -> None:
    course = SimpleNamespace(cycle_type="BIENNIAL")
    assert StaffService._validate_periodic_course_and_period(course, "2026") == "2026"


def test_postcheck_preserves_historical_catalog_and_accepts_new_head() -> None:
    source = POSTCHECK.read_text(encoding="utf-8")
    assert 'CONTINUING_EDUCATION_REVISION = "20260802_0013_staff_continuing_education"' in source
    assert "W1E_LINEAGE_REVISIONS" in source
    assert "include_continuing_education" in source
    assert "STAFF_CONTINUING_EDUCATION_DB_POSTCHECK_OK" in source


def test_0014_migration_descends_from_0013() -> None:
    source = MIGRATION_0014.read_text(encoding="utf-8")
    assert "20260802_0013_staff_continuing_education" in source
    assert RECIPIENT_PLAN_REVISION in source
    assert "recipient_plan_notification" in source


def test_postcheck_declares_0014_revision_and_marker() -> None:
    source = POSTCHECK.read_text(encoding="utf-8")
    assert f'RECIPIENT_PLAN_NOTIFICATION_REVISION = "{RECIPIENT_PLAN_REVISION}"' in source
    assert RECIPIENT_PLAN_MARKER in source
    assert "def _verify_recipient_plan_notification_contract" in source


def test_restore_drill_accepts_0013_and_0014_with_exact_markers() -> None:
    source = RESTORE_DRILL.read_text(encoding="utf-8")
    assert '"20260802_0013_staff_continuing_education"' in source
    assert f'"{RECIPIENT_PLAN_REVISION}"' in source
    assert "STAFF_CONTINUING_EDUCATION_DB_POSTCHECK_OK" in source
    assert RECIPIENT_PLAN_MARKER in source


def test_0014_wrapper_retires_legacy_mode_and_keeps_cleanhead_guards() -> None:
    source = RPN_WRAPPER.read_text(encoding="utf-8")
    assert "[ValidateSet('CleanHead')]" in source
    assert "[ValidateSet('CleanHead','LegacyStaged21')]" not in source

    idx_status = source.index("$InitialGitSnapshot.StatusCount -ne 0")
    idx_staged = source.index("$InitialGitSnapshot.StagedCount -ne 0")
    idx_runtime = source.index("$RuntimeDataRoot = Join-Path")
    assert idx_status < idx_runtime
    assert idx_staged < idx_runtime

    assert '$CandidateMode -eq "CleanHead"' in source
    assert "$finalGit.StagedCount -ne 0" in source

    # -- six-case forms must be present; stale three-case forms must be absent
    assert "expected=6" in source
    assert "$backendPassed -ne 6" in source
    assert r"collected\s+6\s+items?" in source
    assert "expected=3" not in source
    assert "$backendPassed -ne 3" not in source
    assert r"collected\s+3\s+items?" not in source


def test_0014_wrapper_rejects_retired_legacy_mode_before_runtime() -> None:
    if os.name != "nt":
        pytest.skip("PowerShell integration test requires Windows")

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("powershell not found on PATH")

    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(RPN_WRAPPER), "-CandidateMode", "LegacyStaged21"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0

    combined = (result.stdout or "") + (result.stderr or "")
    for marker in (
        "SSWCENTER_0014_PREFLIGHT_GIT",
        "SSWCENTER_0014_DB_CLUSTER_CREATED",
        "SSWCENTER_0014_GREEN",
    ):
        assert marker not in combined


def test_test_profiles_are_explicit_and_truthful() -> None:
    pkg = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))
    scripts = pkg["scripts"]

    # -- exact command aliases ------------------------------------------------
    assert scripts["test"] == "npm run test:supported"
    assert "W1BRecipientsRed" in scripts["test:supported"]
    assert scripts["test:historical"] == "npm run test:red:w1b"
    assert scripts["test:e2e"] == "npm run test:e2e:full"

    # -- e2e smoke vs full ----------------------------------------------------
    smoke = scripts["test:e2e:smoke"]
    full = scripts["test:e2e:full"]
    assert "playwright.smoke.config.ts" in smoke
    assert "playwright.config.ts" in full
    assert smoke != full

    # -- PowerShell test orchestrator -----------------------------------------
    ps1 = TEST_SCRIPT.read_text(encoding="utf-8")
    assert "run test:supported" in ps1
    assert "run test:historical" in ps1
    assert "run test:e2e:smoke" in ps1
    assert "historical" in ps1.lower() and ("fail" in ps1.lower() or "error" in ps1.lower())
    for historical_backend_test in (
        "tests/test_r0_w2_read_only_contract.py",
        "tests/test_w1b_red.py",
        "tests/test_w1d_contract.py",
        "tests/test_w1e_contract.py",
        "tests/test_w1f_contract.py",
    ):
        assert f'"{historical_backend_test}"' in ps1
    assert '"--ignore=$HistoricalBackendTest"' in ps1
    assert (
        "SSWCENTER_TEST_PROFILE" in ps1
        and "backend" in ps1
        and "frontend" in ps1
        and "e2e={2}" in ps1
        and "$E2eProfile" in ps1
        and "postgres" in ps1
        and "historical" in ps1
    )
    # The orchestrator must never invoke the broad "test:e2e" command directly.
    assert not any(line.strip() == "& $NpmExe run test:e2e" for line in ps1.splitlines())


def test_recipient_plan_postcheck_rejects_exact_catalog_mutations() -> None:
    fn = postcheck_w1a_vs1._verify_recipient_plan_notification_catalog_snapshot

    # Independently written literal from the 0014 migration contract.
    # The 12-field tuple shape is: (contype, definition, local_columns,
    #   ref_schema, ref_table, ref_columns, confdeltype, confupdtype,
    #   confmatchtype, condeferrable, condeferred, convalidated).
    # PK/CHECK suffix: None, None, False, False, True.
    # FK suffix: 'a', 's', False, False, True.
    expected_constraints: dict[
        str,
        tuple[
            str,
            str | None,
            tuple[str, ...],
            str | None,
            str | None,
            tuple[str, ...],
            str | None,
            str | None,
            str | None,
            bool,
            bool,
            bool,
        ],
    ] = {
        "pk_recipient_plan_notification": (
            "p",
            "PRIMARY KEY (id)",
            ("id",),
            None,
            None,
            (),
            None,
            None,
            None,
            False,
            False,
            True,
        ),
        "ck_recipient_plan_notification_row_version_positive": (
            "c",
            "CHECK (row_version > 0)",
            ("row_version",),
            None,
            None,
            (),
            None,
            None,
            None,
            False,
            False,
            True,
        ),
        "fk_recipient_plan_notification_created_by_account": (
            "f",
            None,
            ("created_by_account_id",),
            "erp",
            "user_account",
            ("id",),
            "r",
            "a",
            "s",
            False,
            False,
            True,
        ),
        "fk_recipient_plan_notification_recipient": (
            "f",
            None,
            ("recipient_id",),
            "erp",
            "recipient",
            ("id",),
            "r",
            "a",
            "s",
            False,
            False,
            True,
        ),
        "fk_recipient_plan_notification_updated_by_account": (
            "f",
            None,
            ("updated_by_account_id",),
            "erp",
            "user_account",
            ("id",),
            "r",
            "a",
            "s",
            False,
            False,
            True,
        ),
    }
    assert postcheck_w1a_vs1._RECIPIENT_PLAN_NOTIFICATION_CONSTRAINTS == expected_constraints

    def snapshots() -> tuple[
        tuple[str, str, str | None],
        list[tuple[Any, ...]],
        dict[str, tuple[Any, ...]],
        dict[str, tuple[Any, ...]],
    ]:
        return (
            cast(
                tuple[str, str, str | None],
                tuple(postcheck_w1a_vs1._RECIPIENT_PLAN_NOTIFICATION_OWNERSHIP),
            ),
            list(postcheck_w1a_vs1._RECIPIENT_PLAN_NOTIFICATION_COLUMNS),
            dict(expected_constraints),
            dict(postcheck_w1a_vs1._RECIPIENT_PLAN_NOTIFICATION_INDEXES),
        )

    # -- no-op: pristine copies must pass -------------------------------------
    own, cols, cons, idxs = snapshots()
    fn(own, cols, cons, idxs)

    # -- 1. table owner -> dbo ------------------------------------------------
    own, cols, cons, idxs = snapshots()
    bad_own = ("dbo", own[1], own[2])
    with pytest.raises(SystemExit, match=r"(?i)owner"):
        fn(bad_own, cols, cons, idxs)

    # -- 2. id identity -> empty ----------------------------------------------
    own, cols, cons, idxs = snapshots()
    for i, col in enumerate(cols):
        if col[0] == "id":
            cols[i] = (col[0], col[1], col[2], "", col[4])
            break
    with pytest.raises(SystemExit, match=r"(?i)ident"):
        fn(own, cols, cons, idxs)

    # -- 3. row_version default -> None ---------------------------------------
    own, cols, cons, idxs = snapshots()
    for i, col in enumerate(cols):
        if col[0] == "row_version":
            cols[i] = (col[0], col[1], col[2], col[3], None)
            break
    with pytest.raises(SystemExit, match=r"(?i)default"):
        fn(own, cols, cons, idxs)

    # -- 4a. FK local_columns mutation ----------------------------------------
    own, cols, cons, idxs = snapshots()
    fk_key = "fk_recipient_plan_notification_recipient"
    fk_val = cons[fk_key]
    cons[fk_key] = (fk_val[0], fk_val[1], ("notified_date",)) + fk_val[3:]
    with pytest.raises(SystemExit, match=r"(?i)local columns"):
        fn(own, cols, cons, idxs)

    # -- 4b. FK referenced schema mutation ------------------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:3] + ("public",) + fk_val[4:]
    with pytest.raises(SystemExit, match=r"(?i)referenced schema"):
        fn(own, cols, cons, idxs)

    # -- 4c. FK referenced table mutation -------------------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:4] + ("user_account",) + fk_val[5:]
    with pytest.raises(SystemExit, match=r"(?i)referenced table"):
        fn(own, cols, cons, idxs)

    # -- 4d. FK referenced columns mutation -----------------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:5] + (("uuid",),) + fk_val[6:]
    with pytest.raises(SystemExit, match=r"(?i)referenced columns"):
        fn(own, cols, cons, idxs)

    # -- 4e. FK delete action mutation ----------------------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:6] + ("c",) + fk_val[7:]
    with pytest.raises(SystemExit, match=r"(?i)delete action"):
        fn(own, cols, cons, idxs)

    # -- 4f. FK definition must be None (fail-closed: non-None definition) ----
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = (
        fk_val[0],
        "FOREIGN KEY (recipient_id) REFERENCES erp.recipient(id)",
    ) + fk_val[2:]
    with pytest.raises(SystemExit, match=r"(?i)definition"):
        fn(own, cols, cons, idxs)

    # -- 4g. FK update action mutation ('a' -> 'c') ---------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:7] + ("c",) + fk_val[8:]
    with pytest.raises(SystemExit, match=r"(?i)update action"):
        fn(own, cols, cons, idxs)

    # -- 4h. FK match type mutation ('s' -> 'f') ------------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:8] + ("f",) + fk_val[9:]
    with pytest.raises(SystemExit, match=r"(?i)match type"):
        fn(own, cols, cons, idxs)

    # -- 4i. FK deferrable mutation (False -> True) ---------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:9] + (True,) + fk_val[10:]
    with pytest.raises(SystemExit, match=r"(?i)deferrable"):
        fn(own, cols, cons, idxs)

    # -- 4j. FK initially deferred mutation (False -> True) -------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:10] + (True,) + fk_val[11:]
    with pytest.raises(SystemExit, match=r"(?i)initially deferred"):
        fn(own, cols, cons, idxs)

    # -- 4k. FK validated mutation (True -> False) ----------------------------
    own, cols, cons, idxs = snapshots()
    fk_val = cons[fk_key]
    cons[fk_key] = fk_val[:11] + (False,)
    with pytest.raises(SystemExit, match=r"(?i)validated"):
        fn(own, cols, cons, idxs)

    # -- 4l. PK with unexpected referenced metadata (fail-closed non-FK path) -
    own, cols, cons, idxs = snapshots()
    pk_key = "pk_recipient_plan_notification"
    pk_val = cons[pk_key]
    cons[pk_key] = pk_val[:3] + ("erp", "recipient", ("id",), "r") + pk_val[7:]
    with pytest.raises(SystemExit, match=r"(?i)referenced schema"):
        fn(own, cols, cons, idxs)

    # -- 5a. notified_date index uniqueness -> True ---------------------------
    own, cols, cons, idxs = snapshots()
    ix_key = "ix_recipient_plan_notification_notified_date"
    ix_val = idxs[ix_key]
    idxs[ix_key] = (True,) + ix_val[1:]
    with pytest.raises(SystemExit, match=r"(?i)index.*uniqueness"):
        fn(own, cols, cons, idxs)

    # -- 5b. notified_date index definition -> created_at_utc -----------------
    own, cols, cons, idxs = snapshots()
    ix_val = idxs[ix_key]
    bad_def = ix_val[4].replace("(notified_date)", "(created_at_utc)")
    idxs[ix_key] = ix_val[:4] + (bad_def,) + ix_val[5:]
    with pytest.raises(SystemExit, match=r"(?i)index.*definition"):
        fn(own, cols, cons, idxs)

    # -- prove runtime queries feed all structured catalog fields -------------
    source = POSTCHECK.read_text(encoding="utf-8")
    assert "pg_get_serial_sequence" in source
    assert "pg_attribute" in source
    # pg_get_constraintdef is only used for PK/CHECK; FK definition is NULL
    assert "pg_get_constraintdef" in source
    assert "pg_get_indexdef" in source
    assert "indisvalid" in source
    assert "indisready" in source
    # Structured FK resolution fields used by the implementation
    assert "c.conkey" in source
    assert "c.confkey" in source
    assert "c.confrelid" in source
    assert "c.confdeltype" in source
    assert "c.confupdtype" in source
    assert "c.confmatchtype" in source
    assert "c.condeferrable" in source
    assert "c.condeferred" in source
    assert "c.convalidated" in source
    assert "WITH ORDINALITY" in source
    assert "pg_namespace" in source
    # CASE that makes FK definition NULL
    assert "CASE WHEN" in source and "THEN NULL" in source
    assert "_verify_recipient_plan_notification_catalog_snapshot" in source
