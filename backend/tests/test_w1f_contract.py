"""W1F HIGH integration/recovery RED-first contract.

Sealed nodes bind the W1F backup/restore recovery boundary at the current
Alembic head ``20260808_0017_recipient_guardian_email``. Probes for W1D/W1E/0013/
0014/0015/0016/0017 are dynamic; postcheck/wrapper/W1C checks are static source
evidence.

Preserve W1D downgrade and existing 0011~0016 restore support/markers. Current-
head synthetic backup/restore must seed and full-row-hash 0013 continuing
education and 0014 plan notification, and include recipient 0015 status plus
0016 payer_guardian_id via to_jsonb(recipient) full-row canonical evidence.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
RESTORE_DRILL = SCRIPTS_ROOT / "restore-drill.ps1"
W1B_WRAPPER = SCRIPTS_ROOT / "test-w1b-postgres.ps1"
W1C_WRAPPER = SCRIPTS_ROOT / "test-w1c-postgres.ps1"
W1D_WRAPPER = SCRIPTS_ROOT / "test-w1d-postgres.ps1"
W1F_WRAPPER = SCRIPTS_ROOT / "test-w1f-postgres.ps1"
W1A_RRN_DETECTOR = SCRIPTS_ROOT / "w1a-rrn-detector.ps1"
POSTCHECK = REPO_ROOT / "backend" / "app" / "db" / "postcheck_w1a_vs1.py"
PLAN_NOTIFICATION_E2E = (
    REPO_ROOT / "frontend" / "e2e" / "recipient-plan-notification-real-pg.spec.ts"
)

W1B_REVISION = "20260730_0009_w1b_recipient"
W1C_REVISION = "20260730_0010_w1c_certification_ledgers"
W1D_REVISION = "20260730_0011_w1d_recipient_contract"
W1E_REVISION = "20260801_0012_w1e_care_assignment"
CONTINUING_EDUCATION_REVISION = "20260802_0013_staff_continuing_education"
RECIPIENT_PLAN_NOTIFICATION_REVISION = "20260803_0014_recipient_plan_notification"
RECIPIENT_STATUS_TAG_REVISION = "20260806_0015_recipient_status_tag"
RECIPIENT_PAYER_GUARDIAN_REVISION = "20260808_0016_recipient_payer_guardian"
RECIPIENT_GUARDIAN_EMAIL_REVISION = "20260808_0017_recipient_guardian_email"
CURRENT_HEAD = RECIPIENT_GUARDIAN_EMAIL_REVISION

UNSUPPORTED_REVISION_MARKER = "Unsupported backup Alembic revision"
ARTIFACT_STAGE_MARKER = "Backup dump file is missing"

W1D_MARKER = "W1D_DB_POSTCHECK_OK"
W1E_MARKER = "W1E_DB_POSTCHECK_OK"
CONTINUING_EDUCATION_MARKER = "STAFF_CONTINUING_EDUCATION_DB_POSTCHECK_OK"
RECIPIENT_PLAN_NOTIFICATION_MARKER = "RECIPIENT_PLAN_NOTIFICATION_DB_POSTCHECK_OK"
RECIPIENT_STATUS_TAG_MARKER = "RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK"
RECIPIENT_PAYER_GUARDIAN_MARKER = "RECIPIENT_PAYER_GUARDIAN_DB_POSTCHECK_OK"
RECIPIENT_GUARDIAN_EMAIL_MARKER = "RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK"

# Exact historical E2E fixture value, constructed only from fragments so this
# contract file itself never embeds a detector-visible contiguous RRN candidate.
PLAN_NOTIFICATION_SYNTHETIC_RRN = "90010" + "1-11234" + "99"


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("powershell") or shutil.which("powershell.exe")
    if found:
        return found
    _fail("W1F_HARNESS_POWERSHELL_MISSING: powershell.exe could not be resolved")


def _w1a_rrn_match_count(text: str) -> int:
    """Invoke the sealed W1A RRN detector against an in-memory text surface."""
    if not W1A_RRN_DETECTOR.is_file():
        _fail("W1F_HARNESS_RRN_DETECTOR_MISSING: scripts/w1a-rrn-detector.ps1 absent")
    powershell = _powershell_executable()
    probe = (
        "$ErrorActionPreference = 'Stop'; "
        f". '{W1A_RRN_DETECTOR.as_posix()}'; "
        "$text = [Console]::In.ReadToEnd(); "
        "Write-Output (Get-W1ARRNMatchCount -Text $text)"
    )
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                probe,
            ],
            input=text,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("W1F_HARNESS_RRN_DETECTOR_UNRUNNABLE: W1A RRN detector could not run")
    if completed.returncode != 0:
        _fail(
            "W1F_HARNESS_RRN_DETECTOR_FAILED: "
            + (completed.stdout + "\n" + completed.stderr).strip()
        )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        _fail("W1F_HARNESS_RRN_DETECTOR_EMPTY: detector returned no match count")
    try:
        return int(lines[-1])
    except ValueError:
        _fail(f"W1F_HARNESS_RRN_DETECTOR_NON_INTEGER: {lines[-1]!r}")


def _run_restore_drill_manifest_probe(revision: str) -> tuple[int, str]:
    """Invoke restore-drill.ps1 against a synthetic manifest declaring ``revision``.

    The synthetic backup directory intentionally omits the dump file so that a
    restore that accepts the revision fails at artifact validation before any
    database or filesystem mutation. No real PostgreSQL cluster is touched.
    """

    if not RESTORE_DRILL.is_file():
        _fail("W1F_HARNESS_RESTORE_DRILL_MISSING: scripts/restore-drill.ps1 absent")
    powershell = _powershell_executable()
    with tempfile.TemporaryDirectory(prefix="w1f-restore-probe-") as tmp:
        tmp_path = Path(tmp)
        backup_directory = tmp_path / "backup"
        backup_directory.mkdir()
        manifest = {
            "format_version": 1,
            "database_name": "sswcenter_w1f_probe",
            "alembic_revision": revision,
            "dump_file": "database.dump",
            "dump_sha256": "0" * 64,
            "files": [],
            "restore_target_policy": "*_review only",
        }
        (backup_directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        # A review data root that does not yet exist and matches the sealed prefix
        # so the drill reaches the revision allowlist gate.
        review_data_root = tmp_path / f"sswcenter-restore-review-{uuid.uuid4().hex}"
        admin_url = "postgresql+psycopg://erp_owner@127.0.0.1:1/postgres"
        review_database = "sswcenter_w1f_probe_review"
        try:
            completed = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(RESTORE_DRILL),
                    "-BackupDirectory",
                    str(backup_directory),
                    "-AdminDatabaseUrl",
                    admin_url,
                    "-ReviewDatabaseName",
                    review_database,
                    "-ReviewDataRoot",
                    str(review_data_root),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                # PowerShell 5.1 emits localized (cp949) error formatting whose
                # bytes are not valid UTF-8; decode robustly so the ASCII markers
                # remain observable across locales instead of raising in the reader
                # thread and losing stdout/stderr. This preserves the node meaning.
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail("W1F_HARNESS_RESTORE_PROBE_UNRUNNABLE: restore-drill probe could not run")
        # The probe must never create the review data root before failing.
        if review_data_root.exists():
            _fail("W1F_HARNESS_RESTORE_PROBE_LEFT_DATA_ROOT: probe mutated the review root")
        return completed.returncode, completed.stdout + "\n" + completed.stderr


def test_w1f_restore_drill_accepts_w1d_manifest_revision() -> None:
    """Node 1: restore-drill must accept the W1D revision before artifact checks."""
    returncode, output = _run_restore_drill_manifest_probe(W1D_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_W1D_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_W1D_REVISION_REJECTED: restore-drill rejects "
            + W1D_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_W1D_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + W1D_REVISION
        )


def test_w1f_restore_drill_accepts_w1e_manifest_revision() -> None:
    """Node 2: restore-drill must accept the W1E revision before artifact checks."""
    returncode, output = _run_restore_drill_manifest_probe(W1E_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_W1E_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_W1E_REVISION_REJECTED: restore-drill rejects "
            + W1E_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_W1E_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + W1E_REVISION
        )


def test_w1f_restore_drill_accepts_continuing_education_manifest_revision() -> None:
    """Node 2a: restore-drill must accept the 0013 revision before artifact checks."""
    returncode, output = _run_restore_drill_manifest_probe(CONTINUING_EDUCATION_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_0013_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_0013_REVISION_REJECTED: restore-drill rejects "
            + CONTINUING_EDUCATION_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_0013_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + CONTINUING_EDUCATION_REVISION
        )


def test_w1f_restore_drill_accepts_recipient_plan_notification_manifest_revision() -> None:
    """Node 2b: restore-drill must accept the 0014 revision before artifact checks."""
    returncode, output = _run_restore_drill_manifest_probe(RECIPIENT_PLAN_NOTIFICATION_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_0014_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_0014_REVISION_REJECTED: restore-drill rejects "
            + RECIPIENT_PLAN_NOTIFICATION_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_0014_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + RECIPIENT_PLAN_NOTIFICATION_REVISION
        )


def test_w1f_restore_drill_accepts_recipient_status_tag_manifest_revision() -> None:
    """Node 2c: restore-drill must still accept the historical 0015 revision before artifacts."""
    returncode, output = _run_restore_drill_manifest_probe(RECIPIENT_STATUS_TAG_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_0015_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_0015_REVISION_REJECTED: restore-drill rejects "
            + RECIPIENT_STATUS_TAG_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_0015_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + RECIPIENT_STATUS_TAG_REVISION
        )


def test_w1f_restore_drill_accepts_recipient_payer_guardian_manifest_revision() -> None:
    """Node 2d: restore-drill must still accept the historical 0016 revision before artifacts."""
    returncode, output = _run_restore_drill_manifest_probe(RECIPIENT_PAYER_GUARDIAN_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_0016_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_0016_REVISION_REJECTED: restore-drill rejects "
            + RECIPIENT_PAYER_GUARDIAN_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_0016_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + RECIPIENT_PAYER_GUARDIAN_REVISION
        )


def test_w1f_restore_drill_accepts_recipient_guardian_email_manifest_revision() -> None:
    """Node 2e: restore-drill must accept the 0017 current-head revision before artifacts."""
    returncode, output = _run_restore_drill_manifest_probe(RECIPIENT_GUARDIAN_EMAIL_REVISION)
    if returncode == 0:
        _fail("W1F_RESTORE_0017_PROBE_UNEXPECTED_SUCCESS: probe must fail on missing dump")
    if UNSUPPORTED_REVISION_MARKER in output:
        _fail(
            "W1F_RESTORE_0017_REVISION_REJECTED: restore-drill rejects "
            + RECIPIENT_GUARDIAN_EMAIL_REVISION
            + " before artifact validation"
        )
    if ARTIFACT_STAGE_MARKER not in output:
        _fail(
            "W1F_RESTORE_0017_ARTIFACT_STAGE_NOT_REACHED: restore-drill did not reach "
            "artifact validation for " + RECIPIENT_GUARDIAN_EMAIL_REVISION
        )


def test_w1f_postcheck_declares_w1d_w1e_revision_contract() -> None:
    """Node 3: postcheck must supply exact W1D/W1E/0013/0014/0015/0016/0017 verifiers/markers."""
    if not POSTCHECK.is_file():
        _fail("W1F_POSTCHECK_MODULE_MISSING: backend/app/db/postcheck_w1a_vs1.py absent")
    source = POSTCHECK.read_text(encoding="utf-8")
    required_tokens = {
        "W1F_POSTCHECK_W1D_REVISION_MISSING": f'"{W1D_REVISION}"',
        "W1F_POSTCHECK_W1E_REVISION_MISSING": f'"{W1E_REVISION}"',
        "W1F_POSTCHECK_W1D_MARKER_MISSING": W1D_MARKER,
        "W1F_POSTCHECK_W1E_MARKER_MISSING": W1E_MARKER,
        "W1F_POSTCHECK_W1D_VERIFIER_MISSING": "def _verify_w1d_contract",
        "W1F_POSTCHECK_W1E_VERIFIER_MISSING": "def _verify_w1e_contract",
        "W1F_POSTCHECK_W1D_TABLE_MISSING": "recipient_contract",
        "W1F_POSTCHECK_W1E_TABLE_MISSING": "care_assignment",
        "W1F_POSTCHECK_W1E_RECIPIENT_REVERSE_TRIGGER_MISSING": (
            "ct_recipient_contract_assignment_reverse_guard"
        ),
        "W1F_POSTCHECK_W1E_POSITION_REVERSE_TRIGGER_MISSING": (
            "ct_staff_position_care_assignment_reverse_guard"
        ),
        "W1F_POSTCHECK_W1E_QUALIFICATION_REVERSE_TRIGGER_MISSING": (
            "ct_staff_service_qualification_assignment_reverse_guard"
        ),
        "W1F_POSTCHECK_W1E_TRIGGER_FUNCTION_BINDING_MISSING": "tgfoid",
        "W1F_POSTCHECK_REVISION_TRIGGER_SET_MISSING": "expected_w1a_triggers",
        "W1F_POSTCHECK_0013_REVISION_MISSING": f'"{CONTINUING_EDUCATION_REVISION}"',
        "W1F_POSTCHECK_0013_MARKER_MISSING": CONTINUING_EDUCATION_MARKER,
        "W1F_POSTCHECK_0014_REVISION_MISSING": f'"{RECIPIENT_PLAN_NOTIFICATION_REVISION}"',
        "W1F_POSTCHECK_0014_MARKER_MISSING": RECIPIENT_PLAN_NOTIFICATION_MARKER,
        "W1F_POSTCHECK_0014_VERIFIER_MISSING": "def _verify_recipient_plan_notification_contract",
        "W1F_POSTCHECK_0014_TABLE_MISSING": "recipient_plan_notification",
        "W1F_POSTCHECK_0014_LINEAGE_MISSING": "W1E_LINEAGE_REVISIONS",
        "W1F_POSTCHECK_0015_REVISION_MISSING": f'"{RECIPIENT_STATUS_TAG_REVISION}"',
        "W1F_POSTCHECK_0015_MARKER_MISSING": RECIPIENT_STATUS_TAG_MARKER,
        "W1F_POSTCHECK_0015_VERIFIER_MISSING": "def _verify_recipient_status_tag_contract",
        "W1F_POSTCHECK_0015_COLUMN_MISSING": "recipient_status",
        "W1F_POSTCHECK_0016_REVISION_MISSING": f'"{RECIPIENT_PAYER_GUARDIAN_REVISION}"',
        "W1F_POSTCHECK_0016_MARKER_MISSING": RECIPIENT_PAYER_GUARDIAN_MARKER,
        "W1F_POSTCHECK_0016_VERIFIER_MISSING": "def _verify_recipient_payer_guardian_contract",
        "W1F_POSTCHECK_0016_COLUMN_MISSING": "payer_guardian_id",
        "W1F_POSTCHECK_0017_REVISION_MISSING": f'"{RECIPIENT_GUARDIAN_EMAIL_REVISION}"',
        "W1F_POSTCHECK_0017_MARKER_MISSING": RECIPIENT_GUARDIAN_EMAIL_MARKER,
        "W1F_POSTCHECK_0017_VERIFIER_MISSING": "def _verify_recipient_guardian_email_contract",
        "W1F_POSTCHECK_0017_COLUMN_MISSING": "recipient_guardian.email",
    }
    for marker, token in required_tokens.items():
        if token not in source:
            _fail(f"{marker}: missing {token}")


def test_w1f_restore_drill_fail_closed_markers_for_0011_through_0017() -> None:
    """Preserve exact-revision fail-closed postcheck markers for 0011~0017."""
    if not RESTORE_DRILL.is_file():
        _fail("W1F_HARNESS_RESTORE_DRILL_MISSING: scripts/restore-drill.ps1 absent")
    source = RESTORE_DRILL.read_text(encoding="utf-8")
    required = (
        (W1D_REVISION, W1D_MARKER, "W1F_RESTORE_W1D_MARKER_FAIL_CLOSED_MISSING"),
        (W1E_REVISION, W1E_MARKER, "W1F_RESTORE_W1E_MARKER_FAIL_CLOSED_MISSING"),
        (
            CONTINUING_EDUCATION_REVISION,
            CONTINUING_EDUCATION_MARKER,
            "W1F_RESTORE_0013_MARKER_FAIL_CLOSED_MISSING",
        ),
        (
            RECIPIENT_PLAN_NOTIFICATION_REVISION,
            RECIPIENT_PLAN_NOTIFICATION_MARKER,
            "W1F_RESTORE_0014_MARKER_FAIL_CLOSED_MISSING",
        ),
        (
            RECIPIENT_STATUS_TAG_REVISION,
            RECIPIENT_STATUS_TAG_MARKER,
            "W1F_RESTORE_0015_MARKER_FAIL_CLOSED_MISSING",
        ),
        (
            RECIPIENT_PAYER_GUARDIAN_REVISION,
            RECIPIENT_PAYER_GUARDIAN_MARKER,
            "W1F_RESTORE_0016_MARKER_FAIL_CLOSED_MISSING",
        ),
        (
            RECIPIENT_GUARDIAN_EMAIL_REVISION,
            RECIPIENT_GUARDIAN_EMAIL_MARKER,
            "W1F_RESTORE_0017_MARKER_FAIL_CLOSED_MISSING",
        ),
    )
    for revision, marker, fail_marker in required:
        if revision not in source:
            _fail(f"{fail_marker}: revision {revision} not in restore-drill allowlist")
        if marker not in source:
            _fail(f"{fail_marker}: marker {marker} not enforced")
        # Fail-closed: exact revision equality AND -notcontains marker.
        pattern = (
            rf"\$ManifestRevision\s+-eq\s+\"{re.escape(revision)}\"\s+-and\s+"
            rf"\$PostcheckOutput\s+-notcontains\s+\"{re.escape(marker)}\""
        )
        if re.search(pattern, source) is None:
            _fail(
                f"{fail_marker}: restore-drill does not fail-closed on missing "
                f"{marker} for {revision}"
            )

    # A revision's fail-closed marker check is dead code unless the revision is
    # also a member of the ``-in @( ... )`` allowlist that gates postcheck
    # execution. Verify each revision above is inside that specific array, not
    # merely present somewhere else in the file (e.g. only in $SupportedRevisions).
    membership_match = re.search(
        r"elseif\s*\(\s*\$ManifestRevision\s+-in\s+@\((?P<list>.*?)\)\s*\)\s*\{",
        source,
        flags=re.DOTALL,
    )
    if membership_match is None:
        _fail("W1F_RESTORE_POSTCHECK_MEMBERSHIP_BLOCK_MISSING")
    membership_list = membership_match.group("list")
    for revision, _marker, fail_marker in required:
        if revision not in membership_list:
            _fail(
                f"{fail_marker}: {revision} is not a member of the -in @(...) "
                "allowlist that triggers postcheck execution"
            )


def test_w1f_postgres_gate_contract_is_sealed() -> None:
    """Node 4: the exact-SHA synthetic backup/restore live gate must be sealed."""
    if not W1F_WRAPPER.is_file():
        _fail("W1F_WRAPPER_MISSING: scripts/test-w1f-postgres.ps1 absent")
    source = W1F_WRAPPER.read_text(encoding="utf-8")
    required_tokens = {
        "W1F_WRAPPER_EXPECTED_SHA_MISSING": "$ExpectedSha",
        "W1F_WRAPPER_EXACT_SHA_GATE_MISSING": "W1F_EXACT_SHA_OK",
        "W1F_WRAPPER_BACKUP_STEP_MISSING": "backup-postgres.ps1",
        "W1F_WRAPPER_RESTORE_STEP_MISSING": "restore-drill.ps1",
        "W1F_WRAPPER_W1D_MARKER_MISSING": W1D_MARKER,
        "W1F_WRAPPER_W1E_MARKER_MISSING": W1E_MARKER,
        "W1F_WRAPPER_0017_MARKER_MISSING": RECIPIENT_GUARDIAN_EMAIL_MARKER,
        "W1F_WRAPPER_CURRENT_HEAD_MISSING": f'$CurrentHead = "{CURRENT_HEAD}"',
        "W1F_WRAPPER_W1D_HEAD_MISSING": f'$W1dHead = "{W1D_REVISION}"',
        "W1F_WRAPPER_DOWNGRADE_STEP_MISSING": "W1F_STAGE_DOWNGRADE",
        "W1F_WRAPPER_REUPGRADE_STEP_MISSING": "W1F_STAGE_REUPGRADE",
        "W1F_WRAPPER_OFFLINE_STEP_MISSING": "W1F_STAGE_OFFLINE",
        "W1F_WRAPPER_CANONICAL_HASH_MISSING": "W1F_CANONICAL",
        "W1F_WRAPPER_FILE_HASH_MISSING": "Get-FileHash",
        "W1F_WRAPPER_SYNTHETIC_W1A_MISSING": "staff_service_qualification_period",
        "W1F_WRAPPER_CONTRACT_TABLE_MISSING": "recipient_contract",
        "W1F_WRAPPER_ASSIGNMENT_TABLE_MISSING": "care_assignment",
        "W1F_WRAPPER_0013_SEED_MISSING": "CONTINUING_EDUCATION",
        "W1F_WRAPPER_0013_FACT_TABLE_MISSING": "staff_periodic_training_status",
        "W1F_WRAPPER_0014_SEED_MISSING": "recipient_plan_notification",
        "W1F_WRAPPER_0015_STATUS_SEED_MISSING": "recipient_status",
        "W1F_WRAPPER_CLEANUP_MISSING": "W1F_CLEANUP",
        "W1F_WRAPPER_GREEN_MARKER_MISSING": "W1F_POSTGRES_GREEN",
        "W1F_WRAPPER_PRODUCT_FAILURE_FLAG_NOT_SET": "$script:ProductFailure = $true",
        "W1F_WRAPPER_PRODUCT_FAILURE_BRANCH_MISSING": "elseif ($ProductFailure)",
        "W1F_WRAPPER_STDOUT_UTF8_MISSING": "StandardOutputEncoding = $utf8NoBom",
        "W1F_WRAPPER_STDERR_UTF8_MISSING": "StandardErrorEncoding = $utf8NoBom",
    }
    for marker, token in required_tokens.items():
        if token not in source:
            _fail(f"{marker}: missing {token}")

    # Fresh / re-upgrade / offline must target $CurrentHead, not a stale W1E head.
    for stage_marker, stage_pattern in {
        "W1F_WRAPPER_BASE_UPGRADE_NOT_CURRENT_HEAD": (
            r'Invoke-W1fAlembic\s+-AlembicArgs\s+@\("upgrade",\s*\$CurrentHead\)'
            r"\s+-Marker\s+\"W1F_HARNESS_BASE_UPGRADE_FAILED\""
        ),
        "W1F_WRAPPER_REUPGRADE_NOT_CURRENT_HEAD": (
            r'Invoke-W1fAlembic\s+-AlembicArgs\s+@\("upgrade",\s*\$CurrentHead\)'
            r"\s+-Marker\s+\"W1F_HARNESS_REUPGRADE_FAILED\""
        ),
        "W1F_WRAPPER_OFFLINE_NOT_CURRENT_HEAD": (r"\$OfflineRevision\s+-ne\s+\$CurrentHead"),
        "W1F_WRAPPER_HEAD_REVISION_NOT_CURRENT_HEAD": (r"\$HeadRevision\s+-ne\s+\$CurrentHead"),
        "W1F_WRAPPER_REUPGRADE_REVISION_NOT_CURRENT_HEAD": (
            r"\$ReupgradeRevision\s+-ne\s+\$CurrentHead"
        ),
    }.items():
        if re.search(stage_pattern, source) is None:
            _fail(stage_marker)

    # W1D boundary downgrade is preserved.
    if (
        re.search(
            r'Invoke-W1fAlembic\s+-AlembicArgs\s+@\("downgrade",\s*\$W1dHead\)',
            source,
        )
        is None
    ):
        _fail("W1F_WRAPPER_W1D_DOWNGRADE_LOST")

    # W1D marker presence alone (checked via required_tokens above) does not
    # prove the comparison is fail-closed. Pin the whole if-condition/brace/
    # failure-call structure, mirroring the W1E lock below.
    w1d_failclosed_pattern = (
        r"if\s*\(\s*"
        r"\[int\]\$W1dPostcheckRun\.ExitCode\s+-ne\s+0\s+-or\s+"
        r"\(\[string\]\$W1dPostcheckRun\.Stdout\)\s+-notmatch\s+\""
        + re.escape(W1D_MARKER)
        + r"\"\s*\)\s*\{\s*"
        r"Write-W1fProductFailure\s+\"W1F_W1D_POSTCHECK_MARKER_MISSING\"\s*\}"
    )
    if re.search(w1d_failclosed_pattern, source) is None:
        _fail("W1F_WRAPPER_W1D_MARKER_FAIL_CLOSED_MISSING")

    # W1E exact-revision boundary must be visited (with its marker fail-closed
    # observed) strictly after the W1D downgrade and before the re-upgrade to
    # $CurrentHead -- otherwise W1E_DB_POSTCHECK_OK is never exercised live.
    if (
        re.search(
            r'Invoke-W1fAlembic\s+-AlembicArgs\s+@\("upgrade",\s*\$W1eHead\)',
            source,
        )
        is None
    ):
        _fail("W1F_WRAPPER_W1E_UPGRADE_LOST")

    w1d_downgrade_at = source.find('@("downgrade", $W1dHead)')
    w1e_upgrade_at = source.find('@("upgrade", $W1eHead)')
    w1e_marker_at = source.find(W1E_MARKER)
    reupgrade_at = source.find('-Marker "W1F_HARNESS_REUPGRADE_FAILED"')
    if min(w1d_downgrade_at, w1e_upgrade_at, w1e_marker_at, reupgrade_at) < 0:
        _fail("W1F_WRAPPER_W1E_OBSERVATION_STAGE_MARKERS_INCOMPLETE")
    if not (w1d_downgrade_at < w1e_upgrade_at < w1e_marker_at < reupgrade_at):
        _fail(
            "W1F_WRAPPER_W1E_OBSERVATION_ORDER_INVALID: W1E exact-revision visit "
            "and marker check must come after the W1D downgrade and before the "
            "re-upgrade to $CurrentHead"
        )

    # The W1E marker presence/order checks above only prove the token exists
    # somewhere in the right region; they do not prove the comparison is
    # fail-closed. A loose "marker ... eventually a failure call" pattern can
    # be defeated by inserting an extra always-false condition (e.g. "-and
    # $false") between the marker check and "{" without tripping it. Pin the
    # whole if-condition/brace/failure-call structure and allow only
    # whitespace between tokens so no extra condition can slip in unnoticed.
    w1e_failclosed_pattern = (
        r"if\s*\(\s*"
        r"\[int\]\$W1ePostcheckRun\.ExitCode\s+-ne\s+0\s+-or\s+"
        r"\(\[string\]\$W1ePostcheckRun\.Stdout\)\s+-notmatch\s+\""
        + re.escape(W1E_MARKER)
        + r"\"\s*\)\s*\{\s*"
        r"Write-W1fProductFailure\s+\"W1F_W1E_POSTCHECK_MARKER_MISSING\"\s*\}"
    )
    if re.search(w1e_failclosed_pattern, source) is None:
        _fail("W1F_WRAPPER_W1E_MARKER_FAIL_CLOSED_MISSING")

    seed_match = re.search(
        r"(?ms)^\$SeedSql = @'\r?\n(?P<sql>.*?)\r?\n'@$",
        source,
    )
    if seed_match is None:
        _fail("W1F_WRAPPER_SEED_SQL_BLOCK_MISSING")
    seed_sql = seed_match.group("sql")
    if "CONTINUING_EDUCATION" not in seed_sql:
        _fail("W1F_WRAPPER_0013_SEED_CONTINUING_EDUCATION_MISSING")
    if "staff_periodic_training_status" not in seed_sql:
        _fail("W1F_WRAPPER_0013_SEED_TABLE_MISSING")
    if "recipient_plan_notification" not in seed_sql:
        _fail("W1F_WRAPPER_0014_SEED_TABLE_MISSING")
    if "recipient_status" not in seed_sql:
        _fail("W1F_WRAPPER_0015_RECIPIENT_STATUS_SEED_MISSING")
    if (
        re.search(
            r"INSERT\s+INTO\s+erp\.recipient\b[\s\S]*?recipient_status",
            seed_sql,
            flags=re.IGNORECASE,
        )
        is None
    ):
        _fail("W1F_WRAPPER_0015_RECIPIENT_STATUS_NOT_IN_INSERT")
    guardian_insert_match = re.search(
        r"INSERT\s+INTO\s+erp\.recipient_guardian\s*"
        r"\(\s*recipient_id\s*,\s*name\s*,\s*phone\s*,\s*address\s*,\s*"
        r"relationship_text\s*,\s*email\s*,\s*created_by_account_id\s*,\s*"
        r"updated_by_account_id\s*,\s*row_version\s*\)\s*"
        r"VALUES\s*\(\s*recipient_id\s*,\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'[^']*'\s*,\s*"
        r"'[^']*'\s*,\s*'w1f-guardian@example\.test'\s*,\s*"
        r"account_id\s*,\s*account_id\s*,\s*1\s*\)\s*"
        r"RETURNING\s+id\s+INTO\s+guardian_id\s*;",
        seed_sql,
        flags=re.IGNORECASE,
    )
    if guardian_insert_match is None:
        _fail(
            "W1F_WRAPPER_0016_GUARDIAN_INSERT_NOT_STRUCTURAL: "
            "recipient_guardian insert must carry a non-null email literal "
            "in the email column position and RETURNING id INTO guardian_id"
        )
    guardian_link_match = re.search(
        r"UPDATE\s+erp\.recipient\s+SET\s+payer_guardian_id\s*=\s*guardian_id\s+"
        r"WHERE\s+id\s*=\s*recipient_id\s*;",
        seed_sql,
        flags=re.IGNORECASE,
    )
    if guardian_link_match is None:
        _fail(
            "W1F_WRAPPER_0016_PAYER_GUARDIAN_ID_LINK_NOT_STRUCTURAL: "
            "recipient.payer_guardian_id must be linked to the seeded guardian_id"
        )
    if seed_sql[guardian_insert_match.end() : guardian_link_match.start()].strip() != "":
        _fail(
            "W1F_WRAPPER_0016_GUARDIAN_ID_REASSIGNED: nothing may sit between "
            "RETURNING id INTO guardian_id and the payer_guardian_id UPDATE that "
            "consumes it"
        )
    # Table-level statement counting (not column/SET-syntax matching) so quoted
    # identifiers, multi-column tuple SET targets, etc. cannot hide an extra
    # write: any additional UPDATE naming these tables anywhere in the seed is
    # rejected outright, regardless of what it sets.
    # Relation matching tolerates optional double-quoting of either identifier
    # part and an optional ONLY keyword, since both are valid PostgreSQL syntax
    # that a plain unquoted-name regex would otherwise miss.
    recipient_relation = r'"?erp"?\s*\.\s*"?recipient"?(?!_)'
    guardian_relation = r'"?erp"?\s*\.\s*"?recipient_guardian"?'
    recipient_updates = re.findall(
        rf"UPDATE\s+(?:ONLY\s+)?{recipient_relation}",
        seed_sql,
        flags=re.IGNORECASE,
    )
    if len(recipient_updates) != 1:
        _fail(
            "W1F_WRAPPER_0016_RECIPIENT_UPDATE_COUNT_UNEXPECTED: exactly one "
            "UPDATE erp.recipient statement (the payer_guardian_id link) is "
            f"allowed in the seed (found {len(recipient_updates)})"
        )
    guardian_updates = re.findall(
        rf"UPDATE\s+(?:ONLY\s+)?{guardian_relation}",
        seed_sql,
        flags=re.IGNORECASE,
    )
    if guardian_updates:
        _fail(
            "W1F_WRAPPER_0016_GUARDIAN_UPDATE_FORBIDDEN: erp.recipient_guardian "
            "must only be written by the seed INSERT, never by an UPDATE"
        )
    recipient_insert_at = seed_sql.find("INSERT INTO erp.recipient\n")
    guardian_insert_at = guardian_insert_match.start()
    guardian_link_at = guardian_link_match.start()
    contract_insert_at = seed_sql.find("INSERT INTO erp.recipient_contract")
    if (
        min(
            recipient_insert_at,
            guardian_insert_at,
            guardian_link_at,
            contract_insert_at,
        )
        < 0
    ):
        _fail("W1F_WRAPPER_0016_GUARDIAN_ORDER_MARKERS_INCOMPLETE")
    if not (recipient_insert_at < guardian_insert_at < guardian_link_at < contract_insert_at):
        _fail(
            "W1F_WRAPPER_0016_GUARDIAN_ORDER_INVALID: guardian insert and the "
            "payer_guardian_id link must occur strictly between the recipient "
            "insert and the recipient_contract insert"
        )

    # Beyond the static seed-text checks above (which raw regex can never make
    # fully airtight against arbitrary SQL syntax), the wrapper must also
    # verify the *materialized* database state right after seeding: a runtime
    # query that fails closed if the guardian link or email ends up null no
    # matter how the seed produced that result.
    guardian_invariant_failclosed_pattern = (
        r"if\s*\(\s*\$GuardianInvariantCount\s+-ne\s+\"1\"\s*\)\s*\{\s*"
        r"Write-W1fProductFailure\s+\"W1F_GUARDIAN_SEED_INVARIANT_FAILED\""
    )
    if re.search(guardian_invariant_failclosed_pattern, source) is None:
        _fail("W1F_WRAPPER_GUARDIAN_INVARIANT_FAIL_CLOSED_MISSING")
    guardian_invariant_sql_match = re.search(
        r"\$GuardianInvariantSql\s*=\s*@'\r?\n(?P<sql>.*?)\r?\n'@",
        source,
        flags=re.DOTALL,
    )
    if guardian_invariant_sql_match is None:
        _fail("W1F_WRAPPER_GUARDIAN_INVARIANT_SQL_BLOCK_MISSING")
    guardian_invariant_sql = guardian_invariant_sql_match.group("sql")
    for required_fragment in (
        "g.id = r.payer_guardian_id",
        "g.recipient_id = r.id",
        "g.email IS NOT NULL",
    ):
        if required_fragment not in guardian_invariant_sql:
            _fail(f"W1F_WRAPPER_GUARDIAN_INVARIANT_SQL_INCOMPLETE: missing {required_fragment!r}")

    canonical_match = re.search(
        r"(?ms)^\$CanonicalSql = @'\r?\n(?P<sql>.*?)\r?\n'@$",
        source,
    )
    if canonical_match is None:
        _fail("W1F_WRAPPER_CANONICAL_SQL_BLOCK_MISSING")
    canonical_sql = canonical_match.group("sql")
    required_canonical_tables = (
        "staff",
        "user_account",
        "staff_employment",
        "staff_position_period",
        "staff_license",
        "staff_service_qualification_period",
        "staff_onboarding_training",
        "staff_periodic_training_status",
        "recipient",
        "recipient_guardian",
        "recipient_contract",
        "care_assignment",
        "recipient_plan_notification",
    )
    for table_name in required_canonical_tables:
        full_row_pattern = (
            rf"SELECT\s+'{re.escape(table_name)}:'\s*\|\|\s*"
            rf"to_jsonb\([a-z_][a-z0-9_]*\)::text\s+AS\s+line\s+"
            rf"FROM\s+erp\.{re.escape(table_name)}\s+AS\s+[a-z_][a-z0-9_]*"
        )
        if re.search(full_row_pattern, canonical_sql, flags=re.IGNORECASE) is None:
            _fail(
                "W1F_WRAPPER_CANONICAL_FULL_ROW_MISSING: "
                f"erp.{table_name} is not hashed with to_jsonb(row)"
            )

    # recipient full-row hash necessarily includes 0015 recipient_status column.
    recipient_full_row = re.search(
        r"SELECT\s+'recipient:'\s*\|\|\s*to_jsonb\(([a-z_][a-z0-9_]*)\)::text\s+AS\s+line\s+"
        r"FROM\s+erp\.recipient\s+AS\s+\1",
        canonical_sql,
        flags=re.IGNORECASE,
    )
    if recipient_full_row is None:
        _fail(
            "W1F_WRAPPER_0015_STATUS_NOT_IN_FULL_ROW_HASH: "
            "erp.recipient is not hashed with to_jsonb(row) so recipient_status is not sealed"
        )

    function_start = source.find("function Write-W1fProductFailure {")
    function_end = source.find("function Get-W1fProcessSnapshot {", function_start + 1)
    if function_start < 0 or function_end < 0:
        _fail("W1F_WRAPPER_PRODUCT_FAILURE_FUNCTION_MISSING")
    function_body = source[function_start:function_end]
    flag_position = function_body.find("$script:ProductFailure = $true")
    throw_position = function_body.find("throw $Marker")
    if flag_position < 0 or throw_position < 0 or flag_position > throw_position:
        _fail("W1F_WRAPPER_PRODUCT_FAILURE_FLAG_ORDER_INVALID")

    timed_start = source.find("function Invoke-W1fTimedCommand {")
    timed_end = source.find("function Invoke-W1fDetachedPgCtlStart {", timed_start + 1)
    if timed_start < 0 or timed_end < 0:
        _fail("W1F_WRAPPER_TIMED_COMMAND_FUNCTION_MISSING")
    timed_body = source[timed_start:timed_end]
    for marker, token in {
        "W1F_WRAPPER_STDOUT_UTF8_OUTSIDE_TIMED_COMMAND": ("StandardOutputEncoding = $utf8NoBom"),
        "W1F_WRAPPER_STDERR_UTF8_OUTSIDE_TIMED_COMMAND": ("StandardErrorEncoding = $utf8NoBom"),
    }.items():
        if token not in timed_body:
            _fail(f"{marker}: missing {token}")


def test_w1f_w1c_restore_and_marker_regression() -> None:
    """Node 5 (ABS): existing W1C restore support and marker must be preserved."""
    if not RESTORE_DRILL.is_file():
        _fail("W1F_HARNESS_RESTORE_DRILL_MISSING: scripts/restore-drill.ps1 absent")
    if not POSTCHECK.is_file():
        _fail("W1F_POSTCHECK_MODULE_MISSING: backend/app/db/postcheck_w1a_vs1.py absent")
    restore_source = RESTORE_DRILL.read_text(encoding="utf-8")
    postcheck_source = POSTCHECK.read_text(encoding="utf-8")
    if W1C_REVISION not in restore_source:
        _fail("W1F_W1C_RESTORE_SUPPORT_LOST: restore-drill dropped the W1C revision")
    if "W1C_DB_POSTCHECK_OK" not in restore_source:
        _fail("W1F_W1C_RESTORE_MARKER_LOST: restore-drill dropped the W1C marker enforcement")
    if f'"{W1C_REVISION}"' not in postcheck_source:
        _fail("W1F_W1C_POSTCHECK_SUPPORT_LOST: postcheck dropped the W1C revision")
    if "W1C_DB_POSTCHECK_OK" not in postcheck_source:
        _fail("W1F_W1C_POSTCHECK_MARKER_LOST: postcheck dropped the W1C marker")


def test_w1f_w1c_wrapper_seals_0010_lifecycle_then_upgrades_to_head() -> None:
    """W1C historical wrapper must seal 0010 lifecycle, then upgrade to head before ORM pytest."""
    if not W1C_WRAPPER.is_file():
        _fail("W1F_W1C_WRAPPER_MISSING: scripts/test-w1c-postgres.ps1 absent")
    source = W1C_WRAPPER.read_text(encoding="utf-8")

    required_tokens = {
        "W1F_W1C_WRAPPER_BASE_REVISION_MISSING": f'$BaseRevision = "{W1B_REVISION}"',
        "W1F_W1C_WRAPPER_EXPECTED_REVISION_MISSING": f'$ExpectedRevision = "{W1C_REVISION}"',
        "W1F_W1C_WRAPPER_BASE_UPGRADE_MISSING": "W1C_HARNESS_BASE_UPGRADE_FAILED",
        "W1F_W1C_WRAPPER_UPGRADE_MISSING": "W1C_HARNESS_UPGRADE_FAILED",
        "W1F_W1C_WRAPPER_DOWNGRADE_MISSING": "W1C_HARNESS_DOWNGRADE_FAILED",
        "W1F_W1C_WRAPPER_REUPGRADE_MISSING": "W1C_HARNESS_REUPGRADE_FAILED",
        "W1F_W1C_WRAPPER_REVISION_ASSERT_MISSING": "W1C_HARNESS_REVISION_MISMATCH",
        "W1F_W1C_WRAPPER_HEAD_UPGRADE_FAIL_CLOSED_MISSING": "W1C_HARNESS_HEAD_UPGRADE_FAILED",
        "W1F_W1C_WRAPPER_HEAD_UPGRADE_MARKER_MISSING": "W1C_HEAD_UPGRADE_OK",
        "W1F_W1C_WRAPPER_PYTEST_MISSING": "tests/test_w1c_postgres.py",
        "W1F_W1C_WRAPPER_HEAD_POSTCHECK_MARKER_MISSING": RECIPIENT_GUARDIAN_EMAIL_MARKER,
        "W1F_W1C_WRAPPER_GREEN_MISSING": "W1C_POSTGRES_GREEN",
    }
    for marker, token in required_tokens.items():
        if token not in source:
            _fail(f"{marker}: missing {token}")

    lifecycle_patterns = (
        (
            "W1F_W1C_WRAPPER_BASE_UPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$BaseRevision",
        ),
        (
            "W1F_W1C_WRAPPER_EXPECTED_UPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$ExpectedRevision",
        ),
        (
            "W1F_W1C_WRAPPER_DOWNGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+downgrade\s+\$BaseRevision",
        ),
        (
            "W1F_W1C_WRAPPER_REUPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$ExpectedRevision",
        ),
        (
            "W1F_W1C_WRAPPER_HEAD_UPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+head\b",
        ),
        (
            "W1F_W1C_WRAPPER_EXACT_0010_ASSERT_MISSING",
            r"\$CurrentRevision\s+-join\s+\"\"\)\.Trim\(\)\s+-ne\s+\$ExpectedRevision",
        ),
    )
    for marker, pattern in lifecycle_patterns:
        if re.search(pattern, source) is None:
            _fail(marker)

    revision_assert_at = source.find("W1C_HARNESS_REVISION_MISMATCH")
    head_upgrade_fail_at = source.find("W1C_HARNESS_HEAD_UPGRADE_FAILED")
    head_upgrade_ok_at = source.find("W1C_HEAD_UPGRADE_OK")
    pytest_at = source.find("tests/test_w1c_postgres.py")
    postcheck_at = source.find("app.db.postcheck_w1a_vs1")
    if (
        min(revision_assert_at, head_upgrade_fail_at, head_upgrade_ok_at, pytest_at, postcheck_at)
        < 0
    ):
        _fail("W1F_W1C_WRAPPER_STAGE_MARKERS_INCOMPLETE")
    if not (
        revision_assert_at < head_upgrade_fail_at < head_upgrade_ok_at < pytest_at < postcheck_at
    ):
        _fail(
            "W1F_W1C_WRAPPER_HEAD_UPGRADE_ORDER_INVALID: "
            "exact 0010 assertion must precede fail-closed head upgrade, "
            "W1C_HEAD_UPGRADE_OK, current ORM pytest, and postcheck"
        )

    head_upgrade_block = source[revision_assert_at:pytest_at]
    if "upgrade head" not in head_upgrade_block:
        _fail("W1F_W1C_WRAPPER_HEAD_UPGRADE_NOT_BETWEEN_0010_AND_PYTEST")
    if "W1C_HARNESS_HEAD_UPGRADE_FAILED" not in head_upgrade_block:
        _fail("W1F_W1C_WRAPPER_HEAD_UPGRADE_FAIL_CLOSED_NOT_BETWEEN_0010_AND_PYTEST")
    if "W1C_HEAD_UPGRADE_OK" not in head_upgrade_block:
        _fail("W1F_W1C_WRAPPER_HEAD_UPGRADE_MARKER_NOT_BETWEEN_0010_AND_PYTEST")


def test_w1f_w1b_wrapper_seals_0009_then_upgrades_to_current_head() -> None:
    """Seal exact W1B 0009 + pre-postcheck before current-head ORM/E2E."""
    if not W1B_WRAPPER.is_file():
        _fail("W1F_W1B_WRAPPER_MISSING: scripts/test-w1b-postgres.ps1 absent")
    source = W1B_WRAPPER.read_text(encoding="utf-8")

    required_tokens = {
        "W1F_W1B_WRAPPER_EXPECTED_REVISION_MISSING": f'$ExpectedRevision = "{W1B_REVISION}"',
        "W1F_W1B_WRAPPER_CURRENT_HEAD_MISSING": f'$CurrentHead = "{CURRENT_HEAD}"',
        "W1F_W1B_WRAPPER_HISTORICAL_UPGRADE_MISSING": "alembic-upgrade-w1b",
        "W1F_W1B_WRAPPER_REVISION_MISMATCH_MISSING": "migration revision mismatch",
        "W1F_W1B_WRAPPER_PRE_POSTCHECK_MISSING": 'Invoke-Postcheck -Stage "before"',
        "W1F_W1B_WRAPPER_HEAD_UPGRADE_FAIL_CLOSED_MISSING": "W1B_HARNESS_HEAD_UPGRADE_FAILED",
        "W1F_W1B_WRAPPER_HEAD_UPGRADE_MARKER_MISSING": "W1B_HEAD_UPGRADE_OK",
        "W1F_W1B_WRAPPER_E2E_SPEC_MISSING": "e2e/w1b-recipients-real-pg.spec.ts",
        "W1F_W1B_WRAPPER_POST_POSTCHECK_MISSING": 'Invoke-Postcheck -Stage "after"',
        "W1F_W1B_WRAPPER_BEFORE_POSTCHECK_MARKER_MISSING": "W1B_DB_POSTCHECK_OK",
        "W1F_W1B_WRAPPER_AFTER_POSTCHECK_CURRENT_HEAD_MARKER_MISSING": (
            RECIPIENT_GUARDIAN_EMAIL_MARKER
        ),
        "W1F_W1B_WRAPPER_POSTCHECK_STAGE_EVIDENCE_MISSING": "W1B_POSTCHECK_{0}=1",
    }
    for marker, token in required_tokens.items():
        if token not in source:
            _fail(f"{marker}: missing {token}")

    # Argument-position seals (Invoke-Captured uses quoted argument arrays).
    if re.search(r'"upgrade",\s*\$ExpectedRevision', source) is None:
        _fail("W1F_W1B_WRAPPER_HISTORICAL_UPGRADE_CALL_MISSING")
    if re.search(r'"upgrade",\s*\$CurrentHead', source) is None:
        _fail("W1F_W1B_WRAPPER_HEAD_UPGRADE_CALL_MISSING")

    historical_upgrade_at = source.find('"upgrade", $ExpectedRevision')
    revision_mismatch_at = source.find("migration revision mismatch")
    pre_postcheck_at = source.find('Invoke-Postcheck -Stage "before"')
    head_upgrade_arg_at = source.find('"upgrade", $CurrentHead')
    head_upgrade_fail_at = source.find("W1B_HARNESS_HEAD_UPGRADE_FAILED")
    head_upgrade_ok_at = source.find('Write-Output "W1B_HEAD_UPGRADE_OK"')
    # Call site only: Start-Backend after the success marker (function def is earlier).
    backend_at = source.find("Start-Backend", head_upgrade_ok_at) if head_upgrade_ok_at >= 0 else -1
    e2e_at = source.find("e2e/w1b-recipients-real-pg.spec.ts")
    post_postcheck_at = source.find('Invoke-Postcheck -Stage "after"')
    if (
        min(
            historical_upgrade_at,
            revision_mismatch_at,
            pre_postcheck_at,
            head_upgrade_arg_at,
            head_upgrade_fail_at,
            head_upgrade_ok_at,
            backend_at,
            e2e_at,
            post_postcheck_at,
        )
        < 0
    ):
        _fail("W1F_W1B_WRAPPER_STAGE_MARKERS_INCOMPLETE")
    if not (
        historical_upgrade_at
        < revision_mismatch_at
        < pre_postcheck_at
        < head_upgrade_arg_at
        < head_upgrade_fail_at
        < head_upgrade_ok_at
        < backend_at
        < e2e_at
        < post_postcheck_at
    ):
        _fail(
            "W1F_W1B_WRAPPER_HEAD_UPGRADE_ORDER_INVALID: "
            "exact 0009 upgrade/assert and pre-postcheck must precede fail-closed "
            "current-head upgrade, W1B_HEAD_UPGRADE_OK, backend, E2E, and after postcheck"
        )

    head_block = source[pre_postcheck_at:backend_at]
    if '"upgrade", $CurrentHead' not in head_block:
        _fail("W1F_W1B_WRAPPER_HEAD_UPGRADE_NOT_BETWEEN_0009_AND_BACKEND")
    if "W1B_HARNESS_HEAD_UPGRADE_FAILED" not in head_block:
        _fail("W1F_W1B_WRAPPER_HEAD_UPGRADE_FAIL_CLOSED_NOT_BETWEEN_0009_AND_BACKEND")
    if "W1B_HEAD_UPGRADE_OK" not in head_block:
        _fail("W1F_W1B_WRAPPER_HEAD_UPGRADE_MARKER_NOT_BETWEEN_0009_AND_BACKEND")
    # Exact current-head equality check must remain fail-closed in the same block.
    if re.search(r"\$CurrentHead", head_block) is None:
        _fail("W1F_W1B_WRAPPER_CURRENT_HEAD_NOT_USED_IN_HEAD_UPGRADE_BLOCK")

    # Stage-specific postcheck markers inside Invoke-Postcheck only (static surface).
    fn_start = source.find("function Invoke-Postcheck")
    fn_end = source.find("\nfunction ", fn_start + 1) if fn_start >= 0 else -1
    if fn_start < 0 or fn_end < 0:
        _fail("W1F_W1B_WRAPPER_INVOKE_POSTCHECK_FN_MISSING")
    fn_body = source[fn_start:fn_end]
    before_branch_at = fn_body.find('Stage -eq "before"')
    w1b_marker_at = fn_body.find("W1B_DB_POSTCHECK_OK")
    head_marker_at = fn_body.find(RECIPIENT_GUARDIAN_EMAIL_MARKER)
    stage_evidence_at = fn_body.find("W1B_POSTCHECK_{0}=1")
    if min(before_branch_at, w1b_marker_at, head_marker_at, stage_evidence_at) < 0:
        _fail("W1F_W1B_WRAPPER_POSTCHECK_STAGE_MARKERS_INCOMPLETE")
    if not (before_branch_at < w1b_marker_at < head_marker_at):
        _fail(
            "W1F_W1B_WRAPPER_POSTCHECK_STAGE_MARKER_ORDER_INVALID: "
            "before branch must select W1B_DB_POSTCHECK_OK before "
            "current-head after-postcheck marker"
        )
    if re.search(r"-notmatch\s+\$requiredMarker", fn_body) is None:
        _fail("W1F_W1B_WRAPPER_POSTCHECK_FAIL_CLOSED_MATCH_MISSING")


def test_w1f_w1d_wrapper_seals_0011_lifecycle_then_upgrades_to_current_head() -> None:
    """W1D historical wrapper must seal 0010/0011 lifecycle, then head-upgrade before ORM/E2E."""
    if not W1D_WRAPPER.is_file():
        _fail("W1F_W1D_WRAPPER_MISSING: scripts/test-w1d-postgres.ps1 absent")
    source = W1D_WRAPPER.read_text(encoding="utf-8")

    required_tokens = {
        "W1F_W1D_WRAPPER_EXPECTED_REVISION_MISSING": (f'$ExpectedW1dRevision = "{W1D_REVISION}"'),
        "W1F_W1D_WRAPPER_W1C_HEAD_MISSING": f'$W1cHead = "{W1C_REVISION}"',
        "W1F_W1D_WRAPPER_CURRENT_HEAD_MISSING": f'$CurrentHead = "{CURRENT_HEAD}"',
        "W1F_W1D_WRAPPER_BASE_UPGRADE_MISSING": "W1D_HARNESS_BASE_UPGRADE_FAILED",
        "W1F_W1D_WRAPPER_UPGRADE_MISSING": "W1D_MIGRATION_UPGRADE_FAILED",
        "W1F_W1D_WRAPPER_DOWNGRADE_MISSING": "W1D_MIGRATION_DOWNGRADE_FAILED",
        "W1F_W1D_WRAPPER_REUPGRADE_MISSING": "W1D_MIGRATION_REUPGRADE_FAILED",
        "W1F_W1D_WRAPPER_REVISION_OBSERVED_MISSING": "W1D_REVISION_OBSERVED=",
        "W1F_W1D_WRAPPER_HEAD_UPGRADE_FAIL_CLOSED_MISSING": "W1D_HARNESS_HEAD_UPGRADE_FAILED",
        "W1F_W1D_WRAPPER_HEAD_UPGRADE_MARKER_MISSING": "W1D_HEAD_UPGRADE_OK",
        "W1F_W1D_WRAPPER_RUNTIME_REVISION_ENV_MISSING": ("SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION"),
        "W1F_W1D_WRAPPER_PYTEST_MISSING": "tests/test_w1d_postgres.py",
        "W1F_W1D_WRAPPER_E2E_LIVE_MISSING": "SSWCENTER_W1D_LIVE_E2E",
        "W1F_W1D_WRAPPER_GREEN_MISSING": "W1D_POSTGRES_GREEN",
    }
    for marker, token in required_tokens.items():
        if token not in source:
            _fail(f"{marker}: missing {token}")

    lifecycle_patterns = (
        (
            "W1F_W1D_WRAPPER_BASE_UPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$W1cHead",
        ),
        (
            "W1F_W1D_WRAPPER_EXPECTED_UPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$ExpectedW1dRevision",
        ),
        (
            "W1F_W1D_WRAPPER_DOWNGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+downgrade\s+\$W1cHead",
        ),
        (
            "W1F_W1D_WRAPPER_REUPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$ExpectedW1dRevision",
        ),
        (
            "W1F_W1D_WRAPPER_HEAD_UPGRADE_CALL_MISSING",
            r"alembic\s+-c\s+alembic\.ini\s+upgrade\s+\$CurrentHead",
        ),
        (
            "W1F_W1D_WRAPPER_HEAD_REVISION_EXACT_ASSERT_MISSING",
            r"\$HeadRevisionText\s+-ne\s+\$CurrentHead",
        ),
        (
            "W1F_W1D_WRAPPER_HISTORICAL_REVISION_MISMATCH_MISSING",
            r"\$RevisionText\s+-ne\s+\$ExpectedW1dRevision",
        ),
    )
    for marker, pattern in lifecycle_patterns:
        if re.search(pattern, source) is None:
            _fail(marker)

    observed_at = source.find("W1D_REVISION_OBSERVED=")
    head_upgrade_fail_at = source.find("W1D_HARNESS_HEAD_UPGRADE_FAILED")
    head_upgrade_ok_at = source.find("W1D_HEAD_UPGRADE_OK")
    runtime_env_at = source.find("SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION")
    pytest_at = source.find("tests/test_w1d_postgres.py")
    e2e_at = source.find("SSWCENTER_W1D_LIVE_E2E")
    if (
        min(
            observed_at,
            head_upgrade_fail_at,
            head_upgrade_ok_at,
            runtime_env_at,
            pytest_at,
            e2e_at,
        )
        < 0
    ):
        _fail("W1F_W1D_WRAPPER_STAGE_MARKERS_INCOMPLETE")
    if not (
        observed_at
        < head_upgrade_fail_at
        < head_upgrade_ok_at
        < runtime_env_at
        < pytest_at
        < e2e_at
    ):
        _fail(
            "W1F_W1D_WRAPPER_HEAD_UPGRADE_ORDER_INVALID: "
            "exact 0011 observation must precede fail-closed current-head upgrade, "
            "W1D_HEAD_UPGRADE_OK, runtime revision export, ORM pytest, and live E2E"
        )

    head_block = source[observed_at:pytest_at]
    if "upgrade $CurrentHead" not in head_block:
        _fail("W1F_W1D_WRAPPER_HEAD_UPGRADE_NOT_BETWEEN_0011_AND_PYTEST")
    if "W1D_HARNESS_HEAD_UPGRADE_FAILED" not in head_block:
        _fail("W1F_W1D_WRAPPER_HEAD_UPGRADE_FAIL_CLOSED_NOT_BETWEEN_0011_AND_PYTEST")
    if "W1D_HEAD_UPGRADE_OK" not in head_block:
        _fail("W1F_W1D_WRAPPER_HEAD_UPGRADE_MARKER_NOT_BETWEEN_0011_AND_PYTEST")
    if "SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION" not in head_block:
        _fail("W1F_W1D_WRAPPER_RUNTIME_ENV_NOT_BETWEEN_0011_AND_PYTEST")

    # Runtime revision export must bind the exact current head (no soft default).
    if (
        re.search(
            r"\$env:SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION\s*=\s*\$CurrentHead",
            source,
        )
        is None
    ):
        _fail("W1F_W1D_WRAPPER_RUNTIME_ENV_NOT_BOUND_TO_CURRENT_HEAD")


def test_w1f_plan_notification_e2e_hides_detector_visible_resident_number() -> None:
    """0014 real-PG E2E must keep the fixture RRN without a detector-visible source candidate."""
    if not PLAN_NOTIFICATION_E2E.is_file():
        _fail(
            "W1F_PLAN_NOTIFICATION_E2E_MISSING: "
            "frontend/e2e/recipient-plan-notification-real-pg.spec.ts absent"
        )
    source = PLAN_NOTIFICATION_E2E.read_text(encoding="utf-8")

    # Existing W1A detector must treat the sealed contiguous fixture as sensitive.
    if _w1a_rrn_match_count(PLAN_NOTIFICATION_SYNTHETIC_RRN) < 1:
        _fail(
            "W1F_PLAN_NOTIFICATION_RRN_DETECTOR_BLIND: "
            "sealed synthetic fixture is not detector-visible when contiguous"
        )
    # The tracked E2E source must no longer present that contiguous candidate.
    if _w1a_rrn_match_count(source) != 0:
        _fail(
            "W1F_PLAN_NOTIFICATION_E2E_RRN_CANDIDATE_VISIBLE: "
            "recipient-plan-notification-real-pg.spec.ts still contains a "
            "detector-visible resident-number candidate"
        )

    # Runtime construction remains deterministic from separately quoted fragments.
    fragment_pattern = r"(['\"])90010\1\s*\+\s*(['\"])1-11234\2\s*\+\s*(['\"])99\3"
    if re.search(fragment_pattern, source) is None:
        _fail(
            "W1F_PLAN_NOTIFICATION_E2E_RRN_FRAGMENT_CONSTRUCTION_MISSING: "
            "expected separately quoted fragments that join to the sealed fixture"
        )
    if PLAN_NOTIFICATION_SYNTHETIC_RRN != ("90010" + "1-11234" + "99"):
        _fail("W1F_PLAN_NOTIFICATION_E2E_RRN_FIXTURE_DRIFT")
    if "SYNTHETIC_STAFF_RESIDENT_NUMBER" not in source:
        _fail("W1F_PLAN_NOTIFICATION_E2E_RRN_CONSTANT_MISSING")
    if "resident_number: SYNTHETIC_STAFF_RESIDENT_NUMBER" not in source:
        _fail("W1F_PLAN_NOTIFICATION_E2E_RRN_USAGE_MISSING")


def test_w1f_current_head_and_lineage_constants_contract() -> None:
    """Current-head/marker contract: wrapper + restore/postcheck agree on 0017 head."""
    if not W1F_WRAPPER.is_file():
        _fail("W1F_WRAPPER_MISSING: scripts/test-w1f-postgres.ps1 absent")
    if not RESTORE_DRILL.is_file():
        _fail("W1F_HARNESS_RESTORE_DRILL_MISSING: scripts/restore-drill.ps1 absent")
    if not POSTCHECK.is_file():
        _fail("W1F_POSTCHECK_MODULE_MISSING: backend/app/db/postcheck_w1a_vs1.py absent")

    wrapper = W1F_WRAPPER.read_text(encoding="utf-8")
    restore = RESTORE_DRILL.read_text(encoding="utf-8")
    postcheck = POSTCHECK.read_text(encoding="utf-8")

    if f'$CurrentHead = "{CURRENT_HEAD}"' not in wrapper:
        _fail("W1F_CURRENT_HEAD_WRAPPER_MISMATCH")
    if CURRENT_HEAD not in restore:
        _fail("W1F_CURRENT_HEAD_RESTORE_SUPPORT_MISSING")
    if f'RECIPIENT_GUARDIAN_EMAIL_REVISION = "{CURRENT_HEAD}"' not in postcheck:
        _fail("W1F_CURRENT_HEAD_POSTCHECK_REVISION_MISSING")
    if RECIPIENT_GUARDIAN_EMAIL_MARKER not in postcheck:
        _fail("W1F_CURRENT_HEAD_POSTCHECK_MARKER_MISSING")
    if RECIPIENT_GUARDIAN_EMAIL_MARKER not in restore:
        _fail("W1F_CURRENT_HEAD_RESTORE_MARKER_MISSING")
    if RECIPIENT_GUARDIAN_EMAIL_MARKER not in wrapper:
        _fail("W1F_CURRENT_HEAD_WRAPPER_MARKER_MISSING")
    # Historical 0015 marker/boundary remains available for prior restore manifests.
    if RECIPIENT_STATUS_TAG_REVISION not in restore:
        _fail("W1F_0015_RESTORE_SUPPORT_MISSING")
    if RECIPIENT_STATUS_TAG_MARKER not in restore:
        _fail("W1F_0015_RESTORE_MARKER_MISSING")
    # Historical 0016 marker/boundary remains available for prior restore manifests.
    if RECIPIENT_PAYER_GUARDIAN_REVISION not in restore:
        _fail("W1F_0016_RESTORE_SUPPORT_MISSING")
    if RECIPIENT_PAYER_GUARDIAN_MARKER not in restore:
        _fail("W1F_0016_RESTORE_MARKER_MISSING")

    # Lineage 0011~0014 constants remain present on the wrapper for preservation.
    for name, revision in (
        ("$W1dHead", W1D_REVISION),
        ("$W1eHead", W1E_REVISION),
        ("$ContinuingEducationHead", CONTINUING_EDUCATION_REVISION),
        ("$RecipientPlanNotificationHead", RECIPIENT_PLAN_NOTIFICATION_REVISION),
    ):
        if f'{name} = "{revision}"' not in wrapper:
            _fail(f"W1F_LINEAGE_HEAD_CONSTANT_MISSING: {name}={revision}")
