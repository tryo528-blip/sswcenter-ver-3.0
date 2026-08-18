"""Focused W1E phase-1 backend contract tests.

These tests cover the current 0026 head without weakening the sealed 0012
evidence: the forward FAMILY nonblank check must be present in migration and
discoverable ORM metadata, the domain/API surface must exist, and the recipient
TEST sentinel must be read-only while create/update still only accept
MALE/FEMALE.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from typing import Any, cast

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Table

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ALEMBIC_ROOT = BACKEND_ROOT / "alembic"
MIGRATIONS_ROOT = ALEMBIC_ROOT / "versions"

W1E_REVISION = "20260801_0012_w1e_care_assignment"
W1E_0026_REVISION = "20260814_0026_w1e_care_assignment_family_relationship_lock"
W1E_0026_FILE = "20260814_0026_w1e_care_assignment_family_relationship_lock.py"

ASSIGNMENT_COLLECTION = "/api/v1/recipients/{recipient_id}/contracts/{contract_id}/assignments"
ASSIGNMENT_ITEM = (
    "/api/v1/recipients/{recipient_id}/contracts/{contract_id}/assignments/{assignment_id}"
)
REQUIRED_W1E_SCHEMAS = {
    "CareAssignmentCreateRequest",
    "CareAssignmentReplacementRequest",
    "CareAssignmentResponse",
    "CareAssignmentListResponse",
    "CareAssignmentReplacementResponse",
}

FORBIDDEN_ASSIGNMENT_PROPERTIES = {
    "care_change_case_id",
    "staff_replacement_consultation_id",
    "service_visit_id",
    "service_execution_id",
    "billing_run_id",
    "document_id",
    "document_version_id",
    "file_blob_id",
    "import_run_id",
    "ocr_run_id",
    "ocr_apply_run_id",
}


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ALEMBIC_ROOT))
    return ScriptDirectory.from_config(config)


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


def test_current_dispatcher_rejects_historical_0026_without_head_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dispatcher = importlib.import_module("app.db.postcheck_dispatch")
    assert dispatcher.ACTIVE_REVISION != W1E_0026_REVISION

    with pytest.raises(SystemExit, match="W3_0029_UNSUPPORTED_REVISION"):
        dispatcher.dispatch_current_head(_RevisionConnection([W1E_0026_REVISION]))
    output = capsys.readouterr().out
    assert "SSWCENTER_HISTORICAL_0026_DB_POSTCHECK_OK" not in output
    assert "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK" not in output


def test_w1e_0026_linux_harness_binds_exact_live_nodes() -> None:
    postgres_test = BACKEND_ROOT / "tests" / "test_w1e_0026_postgres.py"
    harness = REPO_ROOT / "scripts" / "test-w1e-0026-postgres-linux.ps1"
    source = ast.parse(postgres_test.read_text(encoding="utf-8"))
    test_names = [
        node.name
        for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    harness_nodes = re.findall(
        r"tests/test_w1e_0026_postgres\.py::(test_[A-Za-z0-9_]+)",
        harness.read_text(encoding="utf-8"),
    )
    assert test_names == harness_nodes
    assert test_names == [
        "test_w1e_0026_pg_current_head_and_constraints_exist",
        "test_w1e_0026_pg_family_check_success_and_rejections",
        "test_w1e_0026_pg_general_null_relationship_and_multiple_staff_allowed",
        "test_w1e_0026_pg_same_contract_staff_overlap_rejected",
        "test_w1e_0026_pg_forward_guards_accept_and_reject_exact_boundaries",
        "test_w1e_0026_pg_reverse_guards_reject_parent_mutations",
        "test_w1e_0026_pg_contract_concurrent_assignment_vs_parent_update",
        "test_w1e_0026_pg_employment_concurrent_assignment_vs_parent_update",
        "test_w1e_0026_pg_contract_qualification_reverse_concurrent_no_orphan",
        "test_w1e_0026_pg_multi_edge_employment_parent_no_deadlock",
        "test_w1e_0026_pg_multi_row_assignment_transaction_fine_grained_fail_fast",
        "test_w1e_0026_pg_unrelated_writes_do_not_share_global_mutex",
        "test_w1e_0026_pg_disjoint_domain_writes_overlap_and_commit",
        "test_w1e_0026_pg_employment_lock_helper_always_locks_employment_path",
        "test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment",
        "test_w1e_0026_pg_period_fact_correction_boundary",
        "test_w1e_0026_pg_postcheck_assertions_pass_without_trigger_bypass",
        "test_w1e_0026_pg_lock_function_integer_overload_rejected",
        "test_w1e_0026_pg_lock_function_global_remnant_rejected",
        "test_w1e_0026_pg_care_assignment_sequence_acl_fails_closed",
        "test_w1e_0026_pg_lock_function_catalog_properties_fail_closed",
        "test_w1e_0026_pg_http_create_replace_through_real_service_and_audit",
        "test_w1e_0026_pg_trigger_function_catalog_properties_fail_closed",
    ]
    postgres_source = postgres_test.read_text(encoding="utf-8")
    harness_source = harness.read_text(encoding="utf-8")
    first_upgrade = harness_source.index("alembic -c alembic.ini upgrade $CurrentRevision")
    downgrade = harness_source.index("alembic -c alembic.ini downgrade $PreviousRevision")
    final_upgrade = harness_source.rindex("alembic -c alembic.ini upgrade $CurrentRevision")
    grant = harness_source.index("-f $GrantScript")
    assert first_upgrade < downgrade < final_upgrade < grant
    assert harness_source.count("alembic -c alembic.ini upgrade $CurrentRevision") == 2
    assert harness_source.count("alembic -c alembic.ini downgrade $PreviousRevision") == 1
    assert "W1E_0026_POSTGRES_DOWNGRADE_REVISION_MISMATCH" in harness_source
    assert "W1E_0026_POSTGRES_DOWNGRADE_CONSTRAINT_PRESENT" in harness_source
    assert "W1E_0026_POSTGRES_REUPGRADE_REVISION_MISMATCH" in harness_source
    assert "W1E_0026_POSTGRES_REUPGRADE_CONSTRAINT_MISMATCH" in harness_source
    assert grant < harness_source.index("app.db.postcheck_current_0026")
    assert harness_source.index("app.db.postcheck_current_0026") < harness_source.index(
        "pytest -q -p no:cacheprovider"
    )
    for temp_selector in ("TMPDIR", "TMP", "TEMP"):
        binding = f"$env:{temp_selector} = $TempParent"
        assert binding in harness_source
        assert harness_source.index(binding) < harness_source.index(
            "alembic -c alembic.ini upgrade $CurrentRevision"
        )
    assert "W1E_0026_POSTGRES_CLEANUP_NOT_ZERO" in harness_source
    assert "Get-W1eManifest" in harness_source
    assert "manifest_delta={4}" in harness_source
    assert "W1E_0026_POSTGRES_MANIFEST_FILE_MISSING" in harness_source
    assert "backend/app/db/postcheck_current_0026.py" in harness_source
    assert "SSWCENTER_APP_DATABASE_URL" in harness_source
    assert "W1E_0026_HARNESS_APP_DATABASE_URL_MISSING" in postgres_source
    assert "W1E_0026_APP_ROLE_CAN_SET_REPLICA" in postgres_source
    assert "W1E_0026_APP_ROLE_CAN_DISABLE_TRIGGER" in postgres_source
    assert "42501" in postgres_source
    assert "_expect_app_privilege_denied" in postgres_source
    assert "t.tgenabled <> 'O'" in postgres_source
    assert postgres_source.upper().count("ENABLE REPLICA TRIGGER") == 1
    replica_assigns = re.findall(
        r"SET(?:\s+LOCAL)?\s+session_replication_role\s*=\s*'?replica'?",
        postgres_source,
        flags=re.IGNORECASE,
    )
    assert replica_assigns == ["SET LOCAL session_replication_role = 'replica'"]
    assert postgres_source.upper().count("DISABLE TRIGGER") == 1
    assert "GRANT REFERENCES ON TABLE erp.care_assignment" in postgres_source
    assert "GRANT TRIGGER ON TABLE erp.care_assignment" in postgres_source
    assert "WITH GRANT OPTION" in postgres_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_APP_ACL_MISMATCH" in postgres_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_APP_ACL_MISMATCH" in postgres_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_BACKUP_ACL_MISMATCH" in postgres_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_OWNER_MISMATCH" in postgres_source
    assert "CURRENT_0026_ERP_APP_ROLE_MISSING" in postgres_source
    assert "REVOKE SELECT ON SEQUENCE erp.care_assignment_id_seq FROM erp_app" in postgres_source
    assert "GRANT USAGE ON SEQUENCE erp.care_assignment_id_seq TO erp_backup" in postgres_source
    assert "TO erp_app WITH GRANT OPTION" in postgres_source
    assert "SECURITY DEFINER" in postgres_source
    assert "SET search_path = erp" in postgres_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_EXCLUSION_MISMATCH" in postgres_source
    assert "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) STABLE" in postgres_source
    assert "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) LEAKPROOF" in postgres_source
    assert "GRANT EXECUTE ON FUNCTION erp.fn_w1e_lock_contract_path(bigint)" in postgres_source
    assert "_assert_backend_holds_advisory" in postgres_source
    assert "to_jsonb(pg_proc)::text" in postgres_source
    assert "pg_get_functiondef(pg_proc.oid)" in postgres_source
    assert "pg_get_function_identity_arguments(pg_proc.oid)" in postgres_source
    assert "pg_cancel_backend" in postgres_source
    assert "pg_terminate_backend" in postgres_source
    assert "sswcenter-w1e-0026-pg-" in postgres_source
    assert "W1E_0026_TRANSIENT_EDGE_MISSING_AT_GATE" in postgres_source
    assert "W1E_0026_TRANSIENT_HELPER_HELD_PRODUCTION_C_AT_GATE" in postgres_source
    assert "W1E_0026_TRANSIENT_HELPER_HELD_PRODUCTION_E_AT_GATE" in postgres_source
    assert "W1E_0026_TRANSIENT_UNRELATED_C_BLOCKER_AT_CONFLICT" in postgres_source
    assert "W1E_0026_TRANSIENT_E_BLOCKER_NOT_HELD_AT_CONFLICT" in postgres_source
    assert "W1E_0026_TRANSIENT_DOMAIN_HASH_COLLISION" in postgres_source
    assert "W1E_0026_TRANSIENT_HELPER_LEFT_GATE_BEFORE_RESUME" in postgres_source
    assert "RESTORE_DDL:" in postgres_source
    assert "W1E_0026_MULTI_ROW_FAIL_FAST_ACCEPTED" in postgres_source
    assert "W1E_0026_MULTI_ROW_T1_MISSING_GRANTED_C1" in postgres_source
    assert "W1E_0026_MULTI_ROW_T1_MISSING_GRANTED_E" in postgres_source
    assert "W1E_0026_MULTI_ROW_T1_HELD_GLOBAL" in postgres_source
    assert "W1E_0026_MULTI_ROW_FAIL_FAST_SQLSTATE_MISMATCH" in postgres_source
    assert "W1E_0026_MULTI_ROW_FAIL_FAST_MESSAGE_MISMATCH" in postgres_source


def test_w1e_0026_migration_is_linear_current_head() -> None:
    script = _script_directory()
    heads = [str(head) for head in script.get_heads()]
    assert len(heads) == 1, f"single head required: {heads}"
    ancestry = {str(item.revision) for item in script.iterate_revisions(heads[0], "base")}
    assert W1E_REVISION in ancestry
    assert W1E_0026_REVISION in ancestry

    revisions = {str(item.revision): item for item in script.walk_revisions()}
    migration = revisions[W1E_0026_REVISION]
    down = migration.down_revision
    if isinstance(down, (tuple, list)):
        down_ids = tuple(str(value) for value in down)
    elif down is None:
        down_ids = ()
    else:
        down_ids = (str(down),)
    assert down_ids == ("20260813_0025_w1_relationship_lock_contract_correction",), down_ids

    migration_path = MIGRATIONS_ROOT / W1E_0026_FILE
    assert migration_path.is_file()
    migration_source = migration_path.read_text(encoding="utf-8")
    assert "def upgrade()" in migration_source
    assert "def downgrade()" in migration_source
    assert migration_source.count("op.f(_CONSTRAINT_NAME)") == 2
    assert "from app.db.w1e_family_relationship import" in migration_source
    assert "family_relationship_present_predicate_sql" in migration_source
    assert "family_relationship_trim_sql_literal" in migration_source
    assert "e_string=True" in migration_source
    assert migration_source.count("locked_edge boolean := false;") == 1
    assert migration_source.count("IF NOT locked_edge THEN") == 1
    assert "CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_global" not in migration_source
    assert "PERFORM erp.fn_w1e_lock_global();" not in migration_source
    assert "hashtextextended('erp.w1e.global', 0)" not in migration_source
    assert "pg_try_advisory_xact_lock" in migration_source
    assert migration_source.count("pg_try_advisory_xact_lock(") == 2
    assert "ERRCODE = '55P03'" in migration_source
    assert "MESSAGE = 'CARE_ASSIGNMENT_CONCURRENT_CONFLICT'" in migration_source
    assert "PERFORM erp.fn_w1e_lock_contract_path(p_contract_id);" in migration_source
    assert "PERFORM erp.fn_w1e_lock_employment_path(p_employment_id);" in migration_source
    assert migration_source.count("SELECT DISTINCT assignment.recipient_contract_id") == 2
    assert migration_source.count("SELECT DISTINCT assignment.employment_id") == 1
    assert migration_source.count("ORDER BY assignment.recipient_contract_id") == 2
    assert migration_source.count("ORDER BY assignment.employment_id") == 1


def test_w1e_0026_postcheck_source_locks_family_exclusion_and_acl() -> None:
    postcheck_source = (BACKEND_ROOT / "app" / "db" / "postcheck_current_0026.py").read_text(
        encoding="utf-8"
    )
    assert "family_relationship_present_predicate_sql" in postcheck_source
    assert "FAMILY_RELATIONSHIP_TRIM_CHARS" in postcheck_source
    assert "_FAMILY_RELATIONSHIP_TRIM_CHARS" in postcheck_source
    assert "ex_care_assignment_same_contract_staff_period" in postcheck_source
    assert "EXACT_CARE_ASSIGNMENT_EXCLUSION" in postcheck_source
    assert "EXACT_CARE_ASSIGNMENT_FAMILY_CHECK" in postcheck_source
    assert "EXACT_CARE_ASSIGNMENT_KIND_CHECK" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_FAMILY_CHECK_MISMATCH" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_KIND_CHECK_MISMATCH" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_EXCLUSION_MISMATCH" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_APP_ACL_MISMATCH" in postcheck_source
    assert "CURRENT_0026_ERP_APP_ROLE_MISSING" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_MISSING" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_KIND_MISMATCH" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_OWNER_MISMATCH" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_APP_ACL_MISMATCH" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_BACKUP_ACL_MISMATCH" in postcheck_source
    assert "has_sequence_privilege" in postcheck_source
    assert "USAGE WITH GRANT OPTION" in postcheck_source
    assert "ERP_APP_SEQUENCE_PRIVILEGES" in postcheck_source
    assert "ERP_BACKUP_SEQUENCE_PRIVILEGES" in postcheck_source
    assert "aclexplode" in postcheck_source
    assert "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_ACL_MISMATCH" in postcheck_source
    assert "grantor_oid" in postcheck_source
    assert "missing_grantee" in postcheck_source
    assert "unexpected_grantee" in postcheck_source
    assert "proretset" in postcheck_source
    assert "p.proretset AS returns_set" in postcheck_source
    assert postcheck_source.count("p.proretset AS returns_set") == 2
    assert "returns_set:{table_name}.{trigger_name}" in postcheck_source
    assert "provolatile" in postcheck_source
    assert "proisstrict" in postcheck_source
    assert "proparallel" in postcheck_source
    assert "proleakproof" in postcheck_source
    assert "proacl" in postcheck_source
    assert "EXECUTE WITH GRANT OPTION" in postcheck_source
    assert "CURRENT_0026_W1E_TRIGGER_STATE_MISMATCH" in postcheck_source
    assert "CURRENT_0026_W1E_TRIGGER_CONTRACT_MISMATCH" in postcheck_source
    assert "CURRENT_0026_W1E_FORBIDDEN_LOCK_REMNANT" in postcheck_source
    assert "W1E_FORBIDDEN_LOCK_FUNCTION_NAMES" in postcheck_source
    assert "W1E_FORBIDDEN_LOCK_BODY_MARKERS" in postcheck_source
    assert "_verify_w1e_forbidden_lock_remnants" in postcheck_source
    assert "W1E_TRIGGER_EXPECTATIONS" in postcheck_source
    assert "W1E_LOCK_FUNCTION_ARGUMENT_OIDS" in postcheck_source
    assert "W1E_LOCK_FUNCTION_ARGUMENTS" in postcheck_source
    assert "argument_type_oids" in postcheck_source
    assert "p.proargtypes::text" in postcheck_source
    assert "overloads:" in postcheck_source
    assert "missing:{function_name}" in postcheck_source
    assert "empty-edge parent-domain fallback" in postcheck_source
    assert "_migration_0012_function_bodies" in postcheck_source
    assert "_function_body_is_expected" in postcheck_source
    assert "body:{table_name}.{trigger_name}:normalized_mismatch" in postcheck_source
    assert "unexpected_care_assignment_triggers" in postcheck_source
    assert "pg_get_userbyid(c.relowner)" in postcheck_source
    assert "function_language" in postcheck_source
    assert "function_security_definer" in postcheck_source
    assert "function_proconfig" in postcheck_source
    assert "CURRENT_0026_POSTCHECK_REPLICATION_ROLE_MISMATCH" in postcheck_source
    assert '_privileges(connection, "erp_app", "care_assignment")' in postcheck_source
    assert "'REFERENCES'" in postcheck_source
    assert "'TRIGGER'" in postcheck_source
    for privilege in ("SELECT", "INSERT", "UPDATE"):
        assert f"'{privilege} WITH GRANT OPTION'" in postcheck_source

    postcheck = importlib.import_module("app.db.postcheck_current_0026")
    assert "assignment_kind <> 'FAMILY'" in postcheck.EXACT_CARE_ASSIGNMENT_FAMILY_CHECK
    assert "family_relationship_text IS NOT NULL" in postcheck.EXACT_CARE_ASSIGNMENT_FAMILY_CHECK
    compact = postcheck._compact_constraint(
        "CHECK (assignment_kind <> 'FAMILY'::text OR "
        "family_relationship_text IS NOT NULL AND "
        f"btrim(family_relationship_text, '{postcheck._FAMILY_RELATIONSHIP_TRIM_CHARS}'::text) "
        "<> ''::text)"
    )
    assert compact == postcheck._compact_constraint(postcheck.EXACT_CARE_ASSIGNMENT_FAMILY_CHECK)


def test_w1e_0026_orm_metadata_and_no_recipient_contract_validates() -> None:
    from app.db import models
    from app.db.w1e_family_relationship import family_relationship_present_predicate_sql

    assignment_table = cast(Table, models.CareAssignment.__table__)
    assert (
        assignment_table.info.get("ck_care_assignment_family_relationship_present")
        == family_relationship_present_predicate_sql()
    )
    assert not hasattr(models.RecipientContract, "_validate_family_relationship_text")


def test_w1e_family_relationship_trim_set_is_canonical_across_layers() -> None:
    from app.db.postcheck_current_0026 import (
        _FAMILY_RELATIONSHIP_TRIM_CHARS,
        EXACT_CARE_ASSIGNMENT_FAMILY_CHECK,
    )
    from app.db.w1e_family_relationship import (
        FAMILY_RELATIONSHIP_TRIM_CHARS,
        family_relationship_present_predicate_sql,
        family_relationship_trim_sql_literal,
    )
    from app.domains.w1e.service import W1EService

    assert FAMILY_RELATIONSHIP_TRIM_CHARS == " \t\n\r\f\v"
    assert _FAMILY_RELATIONSHIP_TRIM_CHARS == FAMILY_RELATIONSHIP_TRIM_CHARS
    assert set(FAMILY_RELATIONSHIP_TRIM_CHARS) == {" ", "\t", "\n", "\r", "\f", "\v"}
    assert family_relationship_trim_sql_literal(e_string=True) == r"E' \t\n\r\f\x0b'"
    assert r"\v" not in family_relationship_trim_sql_literal(e_string=True)
    assert EXACT_CARE_ASSIGNMENT_FAMILY_CHECK == (
        "CHECK (" + family_relationship_present_predicate_sql() + ")"
    )

    migration_source = (MIGRATIONS_ROOT / W1E_0026_FILE).read_text(encoding="utf-8")
    service_source = (BACKEND_ROOT / "app" / "domains" / "w1e" / "service.py").read_text(
        encoding="utf-8"
    )
    assert "value.strip()" not in service_source
    assert "value.strip(FAMILY_RELATIONSHIP_TRIM_CHARS)" in service_source
    assert '"40P01"' in service_source
    assert "is_w1e_advisory_lock_loss" in service_source
    assert "_map_sqlalchemy_error" in service_source
    errors_source = (BACKEND_ROOT / "app" / "domains" / "w1e" / "errors.py").read_text(
        encoding="utf-8"
    )
    assert 'W1E_ADVISORY_LOCK_LOSS_SQLSTATE = "55P03"' in errors_source
    assert 'W1E_ADVISORY_LOCK_LOSS_MESSAGE = "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"' in (
        errors_source
    )
    assert "def is_w1e_advisory_lock_loss" in errors_source
    assert "family_relationship_present_predicate_sql(e_string=True)" in migration_source

    assert W1EService._clean_relationship_text("  자녀  ") == "자녀"
    assert W1EService._clean_relationship_text("\t\n\r\f\v") is None
    assert W1EService._clean_relationship_text("\f") is None
    assert W1EService._clean_relationship_text("\v") is None
    assert W1EService._clean_relationship_text("\f자녀\v") == "자녀"
    nbsp_only = "\u00a0"
    assert nbsp_only.strip() == ""
    assert W1EService._clean_relationship_text(nbsp_only) == nbsp_only


def test_w1e_repository_overlap_sql_casts_nullable_exclude_assignment_id() -> None:
    repository_source = (BACKEND_ROOT / "app" / "domains" / "w1e" / "repository.py").read_text(
        encoding="utf-8"
    )
    service_source = (BACKEND_ROOT / "app" / "domains" / "w1e" / "service.py").read_text(
        encoding="utf-8"
    )
    postgres_source = (BACKEND_ROOT / "tests" / "test_w1e_0026_postgres.py").read_text(
        encoding="utf-8"
    )
    assert repository_source.count("CAST(:exclude_assignment_id AS bigint)") == 2
    assert "CAST(:exclude_assignment_id AS bigint) IS NULL" in repository_source
    assert "existing.id <> CAST(:exclude_assignment_id AS bigint)" in repository_source
    assert "exclude_assignment_id: int | None = None" in repository_source
    assert "exclude_assignment_id=exclude_assignment_id" in service_source
    assert "exclude_assignment_id=original.id" in service_source
    assert "W1E_0026_HTTP_SETTINGS_DATABASE_URL_NOT_ERP_APP" in postgres_source
    assert "W1E_0026_HTTP_RUNTIME_ENGINE_NOT_ERP_APP" in postgres_source
    assert "W1E_0026_HTTP_W1E_SERVICE_OVERRIDDEN" in postgres_source
    assert "def pinned_0026_session_override" in postgres_source
    assert "app.db.postcheck_current_0026 directly" in postgres_source
    assert "SELECT current_user" in postgres_source
    assert "W1E_0026_HTTP_APP_CHECK_CURRENT_USER_NOT_ERP_APP" in postgres_source


def test_w1e_schemas_are_fixed() -> None:
    schemas = importlib.import_module("app.domains.w1e.schemas")
    for name in REQUIRED_W1E_SCHEMAS:
        assert hasattr(schemas, name), name

    create_schema = schemas.CareAssignmentCreateRequest.model_json_schema()
    assert set(create_schema["required"]) == {
        "staff_id",
        "employment_id",
        "assignment_kind",
        "start_date",
    }
    properties = create_schema["properties"]
    for forbidden in FORBIDDEN_ASSIGNMENT_PROPERTIES:
        assert forbidden not in properties, forbidden

    response_properties = schemas.CareAssignmentResponse.model_json_schema()["properties"]
    assert "replacement_assignment_id" in response_properties
    assert "invalidated_at_utc" in response_properties
    assert "row_version" in response_properties


def test_recipient_test_sentinel_is_read_only() -> None:
    schemas = importlib.import_module("app.domains.recipient.schemas")
    assert set(schemas.RecipientSexCode.__members__) == {"MALE", "FEMALE"}
    assert set(schemas.RecipientSexCodeRead.__members__) == {"MALE", "FEMALE", "TEST"}

    response = schemas.RecipientResponse(
        id=1,
        name=None,
        birth_date=None,
        sex_code=schemas.RecipientSexCodeRead.TEST,
        recipient_status=schemas.RecipientStatus.ACTIVE,
        recipient_no=None,
        postal_code=None,
        address=None,
        mobile_phone="010-0000-0000",
        memo=None,
        payer_guardian_id=None,
        row_version=1,
    )
    assert response.sex_code is schemas.RecipientSexCodeRead.TEST

    create_props = schemas.RecipientCreateRequest.model_json_schema()["properties"]
    update_props = schemas.RecipientUpdateRequest.model_json_schema()["properties"]
    assert "sex_code" in create_props
    assert "sex_code" in update_props

    from app.main import app

    openapi_schemas = app.openapi()["components"]["schemas"]
    assert set(openapi_schemas["RecipientSexCode"]["enum"]) == {"MALE", "FEMALE"}
    assert set(openapi_schemas["RecipientSexCodeRead"]["enum"]) == {
        "MALE",
        "FEMALE",
        "TEST",
    }


def test_w1e_openapi_routes_and_schemas_are_registered() -> None:
    from app.main import app

    spec = app.openapi()
    paths: dict[str, Any] = spec["paths"]
    assert ASSIGNMENT_COLLECTION in paths
    assert {"get", "post"} <= set(paths[ASSIGNMENT_COLLECTION])
    assert ASSIGNMENT_ITEM in paths
    assert {"get", "put"} <= set(paths[ASSIGNMENT_ITEM])

    schemas: dict[str, Any] = spec["components"]["schemas"]
    missing = sorted(REQUIRED_W1E_SCHEMAS - set(schemas))
    assert not missing, missing

    create_props = schemas["CareAssignmentCreateRequest"]["properties"]
    for forbidden in FORBIDDEN_ASSIGNMENT_PROPERTIES:
        assert forbidden not in create_props, forbidden

    blob = str(spec)
    for code in (
        "CARE_ASSIGNMENT_PERIOD_CONFLICT",
        "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED",
    ):
        assert code in blob, code


def test_w1e_openapi_as_of_query_parameter_contract() -> None:
    from app.main import app

    spec = app.openapi()
    get_operation = spec["paths"][ASSIGNMENT_COLLECTION]["get"]
    parameters = get_operation["parameters"]

    as_of_parameter = next(parameter for parameter in parameters if parameter["name"] == "as_of")
    assert as_of_parameter["in"] == "query"
    assert as_of_parameter["required"] is False

    schema = as_of_parameter["schema"]
    variants = schema.get("anyOf") if isinstance(schema, dict) else None
    if variants:
        date_variant = next(variant for variant in variants if variant.get("type") != "null")
        assert date_variant["type"] == "string"
        assert date_variant["format"] == "date"
    else:
        assert schema["type"] == "string"
        assert schema["format"] == "date"


def test_w1e_openapi_error_descriptions_separate_conflict_statuses() -> None:
    from app.main import app

    spec = app.openapi()
    paths: dict[str, Any] = spec["paths"]
    for path, methods in (
        (ASSIGNMENT_COLLECTION, ("get", "post")),
        (ASSIGNMENT_ITEM, ("get", "put")),
    ):
        for method in methods:
            operation = paths[path][method]
            assert (
                "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
                in operation["responses"]["409"]["description"]
            )
            assert "ROW_VERSION_CONFLICT" in operation["responses"]["409"]["description"]
            assert "CARE_ASSIGNMENT_PERIOD_CONFLICT" in operation["responses"]["422"]["description"]
            assert "VALIDATION_ERROR" in operation["responses"]["422"]["description"]
