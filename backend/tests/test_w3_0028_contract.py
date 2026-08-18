"""RED-first contract for the 0028 W3 source-intake foundation."""

from __future__ import annotations

import ast
import inspect
import re
from hashlib import sha256
from pathlib import Path
from typing import cast

from sqlalchemy import Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.core import readiness
from app.db import models as wave0_models  # noqa: F401
from app.db import postcheck_dispatch
from app.db.postcheck_current_0028 import (
    CURRENT_0028_MARKER,
    EXPECTED_REVISION,
    FORBIDDEN_GENERIC_COLUMNS,
    HEAD_MARKER,
    IMMUTABLE_TABLES,
    MUTABLE_LINEAGE_TABLES,
    REQUIRED_TABLES,
    W3_0028_REVISION,
)
from app.db.w3_models import (
    FOUNDATION_HAS_TARGET_LINK,
    W3ImportAttempt,
    W3ImportRun,
    W3PrivateContent,
    W3SourceReceipt,
    W3SourceRow,
    W3SourceSnapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "20260817_0028_w3_source_intake_foundation.py"
W3_MODELS = BACKEND_ROOT / "app" / "db" / "w3_models.py"
W3_POSTCHECK = BACKEND_ROOT / "app" / "db" / "postcheck_current_0028.py"
DISPATCHER = BACKEND_ROOT / "app" / "db" / "postcheck_dispatch.py"
READINESS = BACKEND_ROOT / "app" / "core" / "readiness.py"
GRANT_SCRIPT = REPO_ROOT / "infra" / "postgres" / "grant-application-access.sql"
RESTORE_DRILL = REPO_ROOT / "scripts" / "restore-drill.ps1"
W2_HARNESS = REPO_ROOT / "scripts" / "test-w2-0027-postgres-linux.ps1"
W3_HARNESS = REPO_ROOT / "scripts" / "test-w3-0028-postgres-linux.ps1"
SCHEMA_CONTRACT = BACKEND_ROOT / "tests" / "test_schema_contract.py"
ENV_PY = BACKEND_ROOT / "alembic" / "env.py"

PARENT_REVISION = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
ACTIVE_REVISION = "20260817_0028_w3_source_intake_foundation"

EXPECTED_TABLE_NAMES = {
    "w3_private_content",
    "w3_source_receipt",
    "w3_source_snapshot",
    "w3_import_run",
    "w3_import_attempt",
    "w3_source_row",
}


def test_0028_migration_is_exact_child_of_0027() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert f'revision: str = "{ACTIVE_REVISION}"' in source
    assert f'down_revision: str | None = "{PARENT_REVISION}"' in source
    for table_name in sorted(EXPECTED_TABLE_NAMES):
        assert f'"{table_name}"' in source
    assert 'schema="erp"' in source
    upgrade_source = source.split("def upgrade()", maxsplit=1)[1]
    assert "BYTEA" not in upgrade_source
    assert "bytea" not in upgrade_source
    assert "target_type" not in upgrade_source
    assert "target_id" not in upgrade_source
    assert 'ondelete="RESTRICT"' in source
    assert "uq_w3_source_snapshot_identity" in source
    assert "uq_w3_source_snapshot_one_active_per_source_date" in source
    assert "status = 'ACTIVE'" in source
    assert 'name=op.f("ck_w3_private_content_digest_sha256")' in source
    assert 'name=op.f("ck_w3_source_receipt_actor_pair")' in source
    assert 'name=op.f("ck_w3_import_attempt_status")' in source
    assert upgrade_source.count("OWNER TO erp_owner") == 6
    assert 'op.execute("ALTER SEQUENCE' not in upgrade_source
    for table_name in sorted(EXPECTED_TABLE_NAMES):
        assert f"ALTER TABLE erp.{table_name} OWNER TO erp_owner" in upgrade_source


def test_0028_orm_models_match_foundation_identity_and_have_no_target_link() -> None:
    assert FOUNDATION_HAS_TARGET_LINK is False
    assert W3PrivateContent.__tablename__ == "w3_private_content"
    assert W3SourceReceipt.__tablename__ == "w3_source_receipt"
    assert W3SourceSnapshot.__tablename__ == "w3_source_snapshot"
    assert W3ImportRun.__tablename__ == "w3_import_run"
    assert W3ImportAttempt.__tablename__ == "w3_import_attempt"
    assert W3SourceRow.__tablename__ == "w3_source_row"

    snapshot_table = cast(Table, W3SourceSnapshot.__table__)
    receipt_table = cast(Table, W3SourceReceipt.__table__)
    run_table = cast(Table, W3ImportRun.__table__)
    attempt_table = cast(Table, W3ImportAttempt.__table__)
    row_table = cast(Table, W3SourceRow.__table__)
    content_table = cast(Table, W3PrivateContent.__table__)

    snapshot_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in snapshot_table.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_w3_source_snapshot_identity"
    }
    assert snapshot_unique == {("source_type", "target_date", "content_digest")}
    assert "parser_profile_version" not in next(iter(snapshot_unique))
    assert "parser_profile_version" not in snapshot_table.columns
    assert {"content_id", "content_digest"} <= set(snapshot_table.columns.keys())

    receipt_columns = set(receipt_table.columns.keys())
    run_columns = set(run_table.columns.keys())
    attempt_columns = set(attempt_table.columns.keys())
    assert {"snapshot_id", "content_id", "content_digest"} <= receipt_columns
    assert {"receipt_id", "snapshot_id", "content_id", "content_digest"} <= run_columns
    assert {
        "receipt_id",
        "import_run_id",
        "snapshot_id",
        "content_id",
        "content_digest",
    } <= attempt_columns

    row_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in row_table.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_w3_source_row_physical_address"
    }
    assert row_unique == {("receipt_id", "sheet_ref", "source_row_number")}

    content_columns = set(content_table.columns.keys())
    assert "content_bytes" not in content_columns
    assert "public_url" not in content_columns
    assert "target_type" not in content_columns
    assert "target_id" not in content_columns
    assert {"content_digest", "byte_size", "media_type", "storage_locator"} <= content_columns
    assert {"quarantine_state", "legal_hold_state", "automatic_gc_enabled"} <= content_columns

    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    for table in (
        content_table,
        receipt_table,
        snapshot_table,
        run_table,
        attempt_table,
        row_table,
    ):
        compiled = str(CreateTable(table).compile(dialect=dialect))
        assert "BYTEA" not in compiled.upper()
        assert "target_type" not in compiled
        assert "target_id" not in compiled


def test_0028_is_registered_as_current_head_only() -> None:
    assert W3_0028_REVISION == ACTIVE_REVISION
    assert EXPECTED_REVISION == ACTIVE_REVISION
    assert postcheck_dispatch.ACTIVE_REVISION == ACTIVE_REVISION
    assert readiness.CURRENT_ALEMBIC_REVISION == ACTIVE_REVISION
    assert "verify_current_0028" in READINESS.read_text(encoding="utf-8")
    assert "verify_current_0027" not in inspect.getsource(readiness.database_catalog_is_ready)

    dispatcher_source = DISPATCHER.read_text(encoding="utf-8")
    assert f'ACTIVE_REVISION = "{ACTIVE_REVISION}"' in dispatcher_source
    assert "verify_current_0028" in dispatcher_source
    assert CURRENT_0028_MARKER == "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK"
    assert HEAD_MARKER == "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"

    env_source = ENV_PY.read_text(encoding="utf-8")
    assert "w3_models" in env_source
    schema_source = SCHEMA_CONTRACT.read_text(encoding="utf-8")
    assert "w3_models" in schema_source
    for table_name in sorted(EXPECTED_TABLE_NAMES):
        assert f"erp.{table_name}" in schema_source


def test_0028_grant_and_restore_and_w2_harness_split_active_from_historical() -> None:
    grant_source = GRANT_SCRIPT.read_text(encoding="utf-8")
    postcheck_source = W3_POSTCHECK.read_text(encoding="utf-8")
    for table_name in sorted(REQUIRED_TABLES):
        assert f"erp.{table_name}" in grant_source
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE" in grant_source
    assert "erp.w3_import_attempt" in grant_source
    assert "erp.w3_source_snapshot" in grant_source
    assert "erp.w3_import_run" in grant_source
    assert "GRANT UPDATE (status) ON TABLE" in grant_source
    assert "GRANT UPDATE (parser_profile_version)" not in grant_source
    assert "GRANT UPDATE (apply_idempotency_key)" not in grant_source
    assert "GRANT UPDATE (original_filename)" not in grant_source
    assert "GRANT UPDATE (created_at_utc)" not in grant_source
    assert "GRANT UPDATE (received_at_utc)" not in grant_source
    assert "GRANT UPDATE (recorded_at_utc)" not in grant_source
    revoke_block = grant_source.split("IF to_regclass('erp.w3_private_content')", maxsplit=1)[1]
    revoke_block = revoke_block.split("GRANT SELECT ON SEQUENCE", maxsplit=1)[0]
    for table_name in sorted(REQUIRED_TABLES):
        assert f"erp.{table_name}" in revoke_block
    status_grant = grant_source.split("GRANT UPDATE (status) ON TABLE", maxsplit=1)[1]
    status_grant = status_grant.split("TO erp_app;", maxsplit=1)[0]
    for table_name in sorted(MUTABLE_LINEAGE_TABLES):
        assert f"erp.{table_name}" in status_grant
    for table_name in sorted(IMMUTABLE_TABLES):
        assert f"erp.{table_name}" not in status_grant
    assert "acl.grantee <> relation_row.relowner" not in postcheck_source
    assert "_exact_acl_drifts(" in postcheck_source
    assert "_verify_w3_table_relacl_entries(connection)" in postcheck_source
    assert "_verify_w3_column_attacl_entries(connection)" in postcheck_source
    assert "PG16_SEQUENCE_OWNER_PRIVILEGES" in postcheck_source
    assert "PG16_SCHEMA_OWNER_PRIVILEGES" in postcheck_source
    assert "PG16_TABLE_OWNER_PRIVILEGES" in postcheck_source
    assert "PG16_COLUMN_OWNER_PRIVILEGES" in postcheck_source
    assert "WHEN acl.grantor = 0 THEN 'PUBLIC'" in postcheck_source
    assert "LEFT JOIN LATERAL aclexplode(attribute_row.attacl) AS acl ON true" in postcheck_source
    assert "LEFT JOIN LATERAL aclexplode(relation_row.relacl) AS acl ON true" in postcheck_source
    assert "LEFT JOIN LATERAL aclexplode(sequence_row.relacl) AS acl ON true" in postcheck_source
    assert "LEFT JOIN LATERAL aclexplode(namespace_row.nspacl) AS acl ON true" in postcheck_source
    assert "COALESCE(attribute_row.attacl" not in postcheck_source
    assert "COALESCE(relation_row.relacl" not in postcheck_source
    assert "COALESCE(sequence_row.relacl" not in postcheck_source
    assert "COALESCE(namespace_row.nspacl" not in postcheck_source
    assert "'{}'::aclitem[]" not in postcheck_source
    assert "ARRAY[]::aclitem[]" not in postcheck_source
    assert "attribute_row.attacl IS NOT NULL" not in postcheck_source
    postgres_source = (BACKEND_ROOT / "tests" / "test_w3_0028_postgres.py").read_text(
        encoding="utf-8"
    )
    assert "LEFT JOIN LATERAL aclexplode(attribute_row.attacl) AS acl ON true" in postgres_source
    assert "LEFT JOIN LATERAL aclexplode(relation_row.relacl) AS acl ON true" in postgres_source
    assert "LEFT JOIN LATERAL aclexplode(namespace_row.nspacl) AS acl ON true" in postgres_source
    assert "COALESCE(attribute_row.attacl" not in postgres_source
    assert "COALESCE(relation_row.relacl" not in postgres_source
    assert "COALESCE(namespace_row.nspacl" not in postgres_source
    assert "'{}'::aclitem[]" not in postgres_source
    assert (
        '"GRANT SELECT (status), INSERT (status), UPDATE (status), "\n'
        '                "REFERENCES (status) ON TABLE erp.w3_source_snapshot TO erp_owner"'
    ) in postgres_source
    assert "GRANT SELECT, INSERT, UPDATE, REFERENCES (status)" not in postgres_source
    assert "_verify_relation_owners(connection)" in postcheck_source
    owner_before_acl = postcheck_source.split("def verify_current_0028", maxsplit=1)[1]
    assert owner_before_acl.index("_verify_relation_owners(connection)") < owner_before_acl.index(
        "_verify_acl(connection)"
    )
    assert "pg_get_serial_sequence(" in postcheck_source
    assert "identity_depend.deptype = 'i'" in postcheck_source
    assert "CURRENT_0028_RELATION_OWNER_MISMATCH" in postcheck_source
    assert "_verify_identity_sequence_acl_entries(connection)" in postcheck_source
    assert "_verify_shared_schema_acl(connection)" in postcheck_source
    assert "CURRENT_0028_SEQUENCE_ACL_MISMATCH" in postcheck_source
    assert "CURRENT_0028_SCHEMA_ACL_MISMATCH" in postcheck_source
    assert "constraint_row.condeferrable" in postcheck_source
    assert "constraint_row.condeferred" in postcheck_source
    assert "JOIN pg_am AS access_method" in postcheck_source
    assert "EXPECTED_NON_CONSTRAINT_INDEXES" in postcheck_source
    assert "pg_get_indexdef(" in postcheck_source

    restore_source = RESTORE_DRILL.read_text(encoding="utf-8")
    assert ACTIVE_REVISION in restore_source
    assert PARENT_REVISION in restore_source
    assert "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK" in restore_source
    assert "SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK" in restore_source
    assert "Historical 0027 restore emitted a current-head marker" in restore_source
    assert "$PostcheckOutput | Write-Output" in restore_source
    assert (
        """elseif ($ManifestRevision -in @(
        $Historical0025Revision,
        $Historical0026Revision,
        $Historical0027Revision,
        $ActiveRevision
    ))"""
        in restore_source
    )
    assert "app.db.postcheck_current_0027" in restore_source
    assert "app.db.postcheck_dispatch" in restore_source

    w2_harness = W2_HARNESS.read_text(encoding="utf-8")
    assert PARENT_REVISION in w2_harness
    assert ACTIVE_REVISION in w2_harness
    assert "app.db.postcheck_current_0027" in w2_harness
    assert "upgrade head" not in w2_harness.split("browser_database")[0]
    assert "upgrade $ActiveHeadRevision" in w2_harness
    assert "upgrade $CurrentRevision" in w2_harness
    assert "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK" in w2_harness
    assert "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK" in w2_harness
    assert "W2_0027_BROWSER_CURRENT_0028_MARKER_MISSING" in w2_harness
    assert "W2_0027_BROWSER_CURRENT_HEAD_MARKER_MISSING" in w2_harness
    assert "W2_0027_POSTGRES_RESTORE_HISTORICAL_0027_MARKER_MISSING" in w2_harness
    assert "W2_0027_POSTGRES_RESTORE_EMITTED_CURRENT_HEAD_MARKER" in w2_harness
    assert "tests/test_w3_0028_w2_current_http_postgres.py" in w2_harness
    assert "SSWCENTER_READINESS_BYPASS" not in w2_harness

    w3_harness = W3_HARNESS.read_text(encoding="utf-8")
    assert PARENT_REVISION in w3_harness
    assert ACTIVE_REVISION in w3_harness
    assert "0027" in w3_harness and "0028" in w3_harness
    assert "test_w3_0028_postgres.py" in w3_harness
    assert "git_delta" in w3_harness
    assert "--timeout=15" in w3_harness
    assert "W3_0028_POSTGRES_RESTORE_MARKER_MISSING" in w3_harness
    assert "W3_0028_POSTGRES_RESTORE_CURRENT_0028_MARKER_MISSING" in w3_harness
    assert "W3_0028_POSTGRES_RESTORE_HEAD_MARKER_MISSING" in w3_harness
    assert ('$RestoreOutput -notcontains "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK"') in w3_harness
    assert ('$RestoreOutput -notcontains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"') in w3_harness
    assert '$RestoreOutput -notcontains "RESTORE_DRILL_OK $ReviewDatabaseName"' in w3_harness


def test_0028_append_only_permission_oracle_requires_sqlstate_42501() -> None:
    source = (BACKEND_ROOT / "tests" / "test_w3_0028_postgres.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    function = next(
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_w3_0028_pg_receipt_row_and_attempt_are_append_only_for_erp_app"
    )
    body = ast.get_source_segment(source, function)
    assert body is not None
    assert 'assert _sqlstate_of(caught.value) == "42501"' in body
    assert "raises((ProgrammingError, IntegrityError))" not in body
    assert "IntegrityError" not in body
    assert "pytest.raises(ProgrammingError)" in body


def test_0028_required_objects_are_closed_and_have_no_generic_link() -> None:
    assert REQUIRED_TABLES == EXPECTED_TABLE_NAMES
    assert IMMUTABLE_TABLES == {
        "w3_private_content",
        "w3_source_receipt",
        "w3_import_attempt",
        "w3_source_row",
    }
    assert MUTABLE_LINEAGE_TABLES == {"w3_source_snapshot", "w3_import_run"}
    assert FORBIDDEN_GENERIC_COLUMNS == {
        "target_type",
        "target_id",
        "content_bytes",
        "public_url",
    }
    models_source = W3_MODELS.read_text(encoding="utf-8")
    assert "FOUNDATION_HAS_TARGET_LINK = False" in models_source
    parsed = ast.parse(models_source)
    assigned = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in parsed.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "FOUNDATION_HAS_TARGET_LINK"
    }
    assert assigned["FOUNDATION_HAS_TARGET_LINK"] is False


def test_0028_check_names_use_project_naming_convention_escape_hatches() -> None:
    migration_source = MIGRATION.read_text(encoding="utf-8")
    models_source = W3_MODELS.read_text(encoding="utf-8")
    for name in (
        "ck_w3_private_content_digest_sha256",
        "ck_w3_source_snapshot_status",
        "ck_w3_source_receipt_actor_pair",
        "ck_w3_import_run_status",
        "ck_w3_import_attempt_status",
        "ck_w3_source_row_number",
    ):
        assert f'name=op.f("{name}")' in migration_source
        assert f'name=conv("{name}")' in models_source


def test_parent_w2_delta_records_intentional_0028_transition_without_unauthorized_drift() -> None:
    manifest_path = (
        REPO_ROOT / "review" / "evidence" / "W2_20260817_CURRENT_CANDIDATE_MANIFEST.sha256"
    )
    w3_manifest_path = (
        REPO_ROOT / "review" / "evidence" / "W3_20260817_CURRENT_CANDIDATE_MANIFEST.sha256"
    )
    delta_path = REPO_ROOT / "review" / "evidence" / "W3_20260817_PARENT_W2_DELTA.md"
    foundation_contract = REPO_ROOT / "backend" / "tests" / "test_foundation_0025_contract.py"
    w1e_contract = REPO_ROOT / "backend" / "tests" / "test_w1e_phase1_contract.py"

    manifest_rows: dict[str, tuple[str, int]] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        _status, digest, nbytes, path = line.split("|", 3)
        manifest_rows[path] = (digest, int(nbytes))
    assert len(manifest_rows) == 98

    w3_manifest_rows: dict[str, tuple[str, int]] = {}
    for line in w3_manifest_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        _status, digest, nbytes, path = line.split("|", 3)
        w3_manifest_rows[path] = (digest, int(nbytes))
    assert len(w3_manifest_rows) == 141
    assert set(manifest_rows) <= set(w3_manifest_rows)

    delta_data = delta_path.read_bytes()
    assert w3_manifest_rows["review/evidence/W3_20260817_PARENT_W2_DELTA.md"] == (
        sha256(delta_data).hexdigest(),
        len(delta_data),
    )

    delta = delta_path.read_text(encoding="utf-8")
    assert "W2_PARENT_REVIEWED_ROWS_EXACT=85/98" in delta
    assert "W3_INTENTIONAL_CANONICAL_CHANGES=13" in delta
    assert "W2_UNAUTHORIZED_DRIFT=0" in delta
    assert "FOUNDATION_0028_UNSUPPORTED_REVISION" in foundation_contract.read_text(encoding="utf-8")
    assert "FOUNDATION_0028_UNSUPPORTED_REVISION" in w1e_contract.read_text(encoding="utf-8")

    intentional: dict[str, tuple[str, int, str, int]] = {}
    row_pattern = re.compile(
        r"\| `INTENTIONAL_CANONICAL_CHANGE` \| `([0-9a-f]{64})` \| (\d+) \| "
        r"`([0-9a-f]{64})` \| (\d+) \| `([^`]+)` \|"
    )
    for match in row_pattern.finditer(delta):
        parent_digest, parent_bytes, current_digest, current_bytes, path = match.groups()
        intentional[path] = (
            parent_digest,
            int(parent_bytes),
            current_digest,
            int(current_bytes),
        )
    assert len(intentional) == 13
    assert "backend/tests/test_foundation_0025_contract.py" in intentional
    assert "backend/tests/test_w1e_phase1_contract.py" in intentional

    unauthorized: list[str] = []
    exact = 0
    for path, (parent_digest, parent_bytes) in manifest_rows.items():
        actual_digest, actual_bytes = w3_manifest_rows[path]
        if path in intentional:
            recorded = intentional[path]
            assert recorded[0] == parent_digest
            assert recorded[1] == parent_bytes
            assert recorded[2] == actual_digest
            assert recorded[3] == actual_bytes
            assert (actual_digest, actual_bytes) != (parent_digest, parent_bytes)
            continue
        if (actual_digest, actual_bytes) == (parent_digest, parent_bytes):
            exact += 1
        else:
            unauthorized.append(path)
    assert exact == 85
    assert unauthorized == []
    assert exact + len(intentional) == 98
