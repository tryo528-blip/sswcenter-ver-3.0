"""W1D contract structural, OpenAPI, migration graph, and absence regressions."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ALEMBIC_ROOT = BACKEND_ROOT / "alembic"
MIGRATIONS_ROOT = ALEMBIC_ROOT / "versions"
W1C_HEAD = "20260730_0010_w1c_certification_ledgers"
W1D_REVISION = "20260730_0011_w1d_recipient_contract"
W1D_MIGRATION_FILE = "20260730_0011_w1d_recipient_contract.py"

EXISTING_CHAIN: tuple[tuple[str, str | None], ...] = (
    ("20260724_0001", None),
    ("20260724_0002", "20260724_0001"),
    ("20260726_0003_w1a_staff", "20260724_0002"),
    ("20260727_0004_w1a_staff_qualifications", "20260726_0003_w1a_staff"),
    ("20260728_0005_w1a_staff_training", "20260727_0004_w1a_staff_qualifications"),
    ("20260728_0006_w1a_staff_health_check", "20260728_0005_w1a_staff_training"),
    (
        "20260728_0007_w1a_staff_quarterly_consultation",
        "20260728_0006_w1a_staff_health_check",
    ),
    ("20260728_0008_w1a_staff_legacy_mapping", "20260728_0007_w1a_staff_quarterly_consultation"),
    ("20260730_0009_w1b_recipient", "20260728_0008_w1a_staff_legacy_mapping"),
    ("20260730_0010_w1c_certification_ledgers", "20260730_0009_w1b_recipient"),
)

CONTRACT_COLLECTION = "/api/v1/recipients/{recipient_id}/contracts"
CONTRACT_ITEM = "/api/v1/recipients/{recipient_id}/contracts/{contract_id}"
CONTRACT_END = "/api/v1/recipients/{recipient_id}/contracts/{contract_id}/end"
REQUIRED_SCHEMAS = {
    "ContractCreateRequest",
    "ContractEndRequest",
    "ContractResponse",
    "ContractListResponse",
}

FORBIDDEN_CONTRACT_PROPERTIES = {
    "contract_no",
    "contract_sequence",
    "signer_guardian_id",
    "signer_payer_id",
    "signer_birth_date",
    "signer_address",
    "signer_name",
    "signer_relationship_text",
    "signer_phone",
    "end_reason_code",
    "discharge_date",
}

STABLE_ERROR_CODES = {
    "CONTRACT_SERVICE_PERIOD_CONFLICT",
    "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT",
    "CONTRACT_REACTIVATION_FORBIDDEN",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _npm_executable() -> str:
    """Resolve the current runtime npm launcher without assuming Windows.

    The repository is Linux-only in canonical execution and ships npm at
    ``/usr/local/bin/npm``.  ``npm.cmd`` only exists on the retired Windows
    desktop copies, so the historical hard-coded value makes the OpenAPI
    TypeScript generation fail on Ubuntu before any byte assertion runs.
    """

    if os.name == "nt":
        candidates: tuple[str, ...] = ("npm.cmd", "npm.exe", "npm")
    else:
        candidates = ("npm",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    if os.name != "nt":
        canonical_npm = Path("/usr/local/bin/npm")
        if canonical_npm.is_file():
            return str(canonical_npm)
    return candidates[-1]


def test_w1d_npm_launcher_resolution_never_assumes_windows() -> None:
    """Regression: Linux OpenAPI generation must resolve npm, not npm.cmd."""

    if os.name == "nt":
        pytest.skip("Windows-specific npm launcher resolution is out of canonical scope")
    resolved = _npm_executable()
    assert resolved
    assert Path(resolved).name == "npm"
    assert not resolved.endswith("npm.cmd")
    assert Path(resolved).is_file()
    source = Path(__file__).read_text(encoding="utf-8")
    generate_fn = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_w1d_03_openapi_routes_and_named_models_are_registered"
    )
    generate_body = ast.get_source_segment(source, generate_fn) or ""
    assert "openapi-typescript" in generate_body
    assert "W1D_OPENAPI_TEMP_GENERATE_FAILED" in generate_body
    assert "_npm_executable()" in generate_body
    assert "pytest.skip" not in generate_body


def _down_revision_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _script_directory() -> ScriptDirectory:
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ALEMBIC_ROOT))
        return ScriptDirectory.from_config(config)
    except Exception:
        _fail("W1D_HARNESS_MIGRATION_GRAPH_MISSING: Alembic ScriptDirectory could not load")


def _verify_existing_snapshot(revision: Any) -> None:
    path = Path(str(revision.path)).resolve()
    try:
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        path.relative_to(MIGRATIONS_ROOT.resolve())
    except ValueError:
        _fail("W1D_MIGRATION_GRAPH_INVALID: revision path escapes migrations directory")
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", relative_path],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        _fail("W1D_EXISTING_MIGRATION_MODIFIED: basis migration changed: " + relative_path)


def _require_w1d_revision() -> Any:
    script = _script_directory()
    try:
        revisions = [r for r in script.walk_revisions() if getattr(r, "revision", None)]
    except Exception:
        _fail("W1D_HARNESS_MIGRATION_GRAPH_MISSING: revision graph could not be walked")

    revision_by_id = {str(r.revision): r for r in revisions}
    for revision_id, expected_down in EXISTING_CHAIN:
        revision = revision_by_id.get(revision_id)
        if revision is None:
            _fail("W1D_MIGRATION_BASE_CHAIN_MISSING: W1A~W1C chain incomplete: " + revision_id)
        actual = _down_revision_ids(revision.down_revision)
        expected = () if expected_down is None else (expected_down,)
        if actual != expected:
            _fail("W1D_MIGRATION_BASE_CHAIN_INVALID: down_revision drift at " + revision_id)
        _verify_existing_snapshot(revision)

    w1d_children = [
        r
        for r in revisions
        if W1C_HEAD in _down_revision_ids(r.down_revision)
        and str(r.revision) not in {item[0] for item in EXISTING_CHAIN}
    ]
    if not w1d_children:
        _fail(
            "W1D_MIGRATION_MISSING: exactly one direct child of "
            + W1C_HEAD
            + " is required ("
            + W1D_REVISION
            + ")"
        )
    if len(w1d_children) != 1:
        _fail("W1D_MIGRATION_GRAPH_INVALID: more than one W1D revision follows W1C head")

    w1d = w1d_children[0]
    if str(w1d.revision) != W1D_REVISION:
        _fail(
            "W1D_MIGRATION_REVISION_ID_MISMATCH: expected "
            + W1D_REVISION
            + " got "
            + str(w1d.revision)
        )
    if _down_revision_ids(w1d.down_revision) != (W1C_HEAD,):
        _fail("W1D_MIGRATION_GRAPH_INVALID: W1D is not a single direct child of W1C head")

    migration_path = MIGRATIONS_ROOT / W1D_MIGRATION_FILE
    if not migration_path.is_file():
        _fail("W1D_MIGRATION_FILE_MISSING: " + W1D_MIGRATION_FILE)

    try:
        heads = tuple(str(h) for h in script.get_heads())
    except Exception:
        _fail("W1D_HARNESS_MIGRATION_GRAPH_MISSING: heads could not be resolved")
    if len(heads) != 1:
        _fail("W1D_MIGRATION_SINGLE_HEAD_MISSING: sole head must be " + W1D_REVISION)
    # The sole head must be the tested revision or one of its descendants on the
    # single linear chain that continues past W1D. Ancestry is resolved through
    # the Alembic ScriptDirectory API: iterate_revisions(head, "base") yields the
    # head plus every ancestor, so the tested revision appears iff the head is it
    # or descends from it. A head outside that chain is rejected.
    try:
        head_ancestry = {str(r.revision) for r in script.iterate_revisions(heads[0], "base")}
    except Exception:
        _fail("W1D_HARNESS_MIGRATION_GRAPH_MISSING: head ancestry could not be resolved")
    if W1D_REVISION not in head_ancestry:
        _fail("W1D_MIGRATION_SINGLE_HEAD_MISSING: sole head must be " + W1D_REVISION)

    return w1d


def test_w1d_00_alembic_direct_child_revision_is_fixed() -> None:
    """W1-CON / migration gate: single direct child of W1C head."""
    _require_w1d_revision()


def test_w1d_01_offline_sql_mentions_recipient_contract() -> None:
    """Offline SQL must create recipient_contract for the W1D revision."""
    _require_w1d_revision()
    synthetic_env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
        "SSWCENTER_DATABASE_URL": (
            "postgresql+psycopg://test_red:test_red@127.0.0.1:5432/sswcenter_w1d_red"
        ),
        "SSWCENTER_ENVIRONMENT": "development",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", W1D_REVISION, "--sql"],
            cwd=BACKEND_ROOT,
            env=synthetic_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("W1D_HARNESS_OFFLINE_SQL_MISSING: offline upgrade command could not run")
    if result.returncode != 0:
        _fail("W1D_ALEMBIC_OFFLINE_DIRECT_CHILD_MISSING: offline SQL failed")
    body = (result.stdout + result.stderr).lower()
    if "create table erp.recipient_contract" not in body and "recipient_contract" not in body:
        _fail("W1D_ALEMBIC_OFFLINE_DIRECT_CHILD_MISSING: recipient_contract DDL absent")
    if W1D_REVISION.lower() not in body:
        _fail("W1D_ALEMBIC_OFFLINE_DIRECT_CHILD_MISSING: revision id absent from SQL")


def test_w1d_02_domain_module_and_schemas_are_fixed() -> None:
    """The contract domain and its named schemas must exist without retired fields."""
    try:
        from app.domains.w1d import schemas as w1d_schemas
    except Exception:
        _fail("W1D_DOMAIN_MODULE_MISSING: app.domains.w1d.schemas is absent")

    for name in REQUIRED_SCHEMAS:
        if not hasattr(w1d_schemas, name):
            _fail("W1D_SCHEMA_MISSING: " + name)

    create = w1d_schemas.ContractCreateRequest
    create_schema = create.model_json_schema()
    properties = create_schema.get("properties", {})
    required = set(create_schema.get("required", []))
    if required != {"service_type_code", "start_date"}:
        _fail(
            "W1D_CON01_CREATE_REQUIRED_MISMATCH: required must be only "
            "service_type_code and start_date"
        )
    for optional_field in (
        "end_date",
        "service_start_date",
        "end_reason_text",
    ):
        if optional_field not in properties:
            _fail("W1D_CON01_OPTIONAL_FIELD_MISSING: " + optional_field)
        if optional_field in required:
            _fail("W1D_CON01_OPTIONAL_FIELD_REQUIRED: " + optional_field)

    for forbidden in FORBIDDEN_CONTRACT_PROPERTIES:
        if forbidden in properties:
            _fail("W1D_ABS08_FORBIDDEN_CREATE_PROPERTY: " + forbidden)

    response = w1d_schemas.ContractResponse
    response_properties = response.model_json_schema().get("properties", {})
    for forbidden in FORBIDDEN_CONTRACT_PROPERTIES:
        if forbidden in response_properties:
            _fail("W1D_ABS08_FORBIDDEN_RESPONSE_PROPERTY: " + forbidden)

    if "end_reason_code" in response_properties or "end_reason_code" in properties:
        _fail("W1D_ABS09_END_REASON_CODE_PRESENT")
    if "discharge_date" in response_properties or "discharge_date" in properties:
        _fail("W1D_ABS09_DISCHARGE_DATE_PRESENT")

    retired = {
        "CertificationTransitionPreviewRequest",
        "CertificationTransitionPreviewResponse",
        "CertificationTransitionApplyRequest",
        "CertificationTransitionApplyResponse",
        "TransitionReplacementItem",
    }
    present = sorted(name for name in retired if hasattr(w1d_schemas, name))
    if present:
        _fail("W1D_RETIRED_TRANSITION_SCHEMA_PRESENT: " + ",".join(present))


def test_w1d_03_openapi_routes_and_named_models_are_registered() -> None:
    """OpenAPI must expose contract operations and omit retired transition routes."""
    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING: app.main could not import")

    try:
        spec = app.openapi()
    except Exception:
        _fail("W1D_HARNESS_OPENAPI_BUILD_MISSING: openapi() failed")

    paths: dict[str, Any] = spec.get("paths", {})
    if CONTRACT_COLLECTION not in paths:
        _fail("W1D_OPENAPI_PATH_MISSING: " + CONTRACT_COLLECTION)
    collection = paths[CONTRACT_COLLECTION]
    if not {"get", "post"} <= set(collection):
        _fail("W1D_OPENAPI_METHOD_MISSING: contracts collection get/post")

    if CONTRACT_ITEM not in paths or "get" not in paths[CONTRACT_ITEM]:
        _fail("W1D_OPENAPI_PATH_MISSING: " + CONTRACT_ITEM)
    if CONTRACT_END not in paths or "post" not in paths[CONTRACT_END]:
        _fail("W1D_OPENAPI_PATH_MISSING: " + CONTRACT_END)
    transition_paths = sorted(path for path in paths if "transition" in path.lower())
    if transition_paths:
        _fail("W1D_RETIRED_TRANSITION_PATH_PRESENT: " + ",".join(transition_paths))

    # Reactivation must not exist.
    for path, methods in paths.items():
        lowered = path.lower()
        if "reactivat" in lowered or "reopen-contract" in lowered:
            _fail("W1D_CON03_REACTIVATE_OPERATION_FORBIDDEN: " + path)
        if isinstance(methods, dict):
            for _method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                op_id = str(operation.get("operationId", "")).lower()
                if "reactivat" in op_id:
                    _fail("W1D_CON03_REACTIVATE_OPERATION_FORBIDDEN: " + op_id)

    schemas: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    missing = sorted(REQUIRED_SCHEMAS - set(schemas))
    if missing:
        _fail("W1D_OPENAPI_SCHEMA_MISSING: " + ",".join(missing))

    create_props = schemas["ContractCreateRequest"].get("properties", {})
    for forbidden in FORBIDDEN_CONTRACT_PROPERTIES:
        if forbidden in create_props:
            _fail("W1D_ABS08_OPENAPI_FORBIDDEN_PROPERTY: " + forbidden)

    # end_reason_text must be free string without enum/default.
    end_reason = create_props.get("end_reason_text", {})
    if "enum" in end_reason or "default" in end_reason:
        _fail("W1D_ABS09_OPENAPI_END_REASON_ENUM_OR_DEFAULT")

    service_start = create_props.get("service_start_date", {})
    create_required = set(schemas["ContractCreateRequest"].get("required", []))
    if "service_start_date" in create_required:
        _fail("W1D_ABS10_OPENAPI_SERVICE_START_REQUIRED")
    if service_start.get("nullable") is False and "service_start_date" in create_props:
        # nullable false without being optional is still a gate if marked required above.
        pass

    transition_schemas = sorted(name for name in schemas if "transition" in name.lower())
    if transition_schemas:
        _fail("W1D_RETIRED_TRANSITION_OPENAPI_SCHEMA_PRESENT: " + ",".join(transition_schemas))

    # Documented 409/422 codes should appear somewhere in OpenAPI description/examples.
    blob = str(spec)
    for code in (
        "CONTRACT_SERVICE_PERIOD_CONFLICT",
        "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT",
        "CONTRACT_REACTIVATION_FORBIDDEN",
    ):
        if code not in blob:
            _fail("W1D_OPENAPI_ERROR_CODE_UNDOCUMENTED: " + code)

    # J-M07 / J-W1D-R3-M01: exact success status + request/response $ref per op.
    # list 200, item GET 200, create 201, and end 200.
    op_bindings: dict[str, dict[str, tuple[str | None, str, str]]] = {
        CONTRACT_COLLECTION: {
            "get": (None, "ContractListResponse", "200"),
            "post": ("ContractCreateRequest", "ContractResponse", "201"),
        },
        CONTRACT_ITEM: {
            "get": (None, "ContractResponse", "200"),
        },
        CONTRACT_END: {
            "post": ("ContractEndRequest", "ContractResponse", "200"),
        },
    }
    # R8-02: every error status is required and must bind RecipientErrorEnvelope.
    required_error_statuses = ("401", "403", "404", "409", "422", "500")
    for path, methods in op_bindings.items():
        for method, models in methods.items():
            operation = paths.get(path, {}).get(method)
            if not isinstance(operation, dict):
                _fail(f"W1D_OPENAPI_OP_MISSING: {method.upper()} {path}")
            req_name, resp_name, ok_code = models
            if req_name is not None:
                content = (
                    operation.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                ref = content.get("$ref", "")
                if not ref.endswith("/" + req_name):
                    _fail(f"W1D_OPENAPI_REQUEST_REF_MISMATCH: {path} want {req_name} got {ref}")
            if ok_code not in operation.get("responses", {}):
                _fail(f"W1D_OPENAPI_SUCCESS_STATUS_MISSING: {path} {ok_code}")
            for other in ("200", "201"):
                if other != ok_code and other in operation.get("responses", {}):
                    _fail(f"W1D_OPENAPI_AMBIGUOUS_SUCCESS_STATUS: {path} has {other}")
            ok_resp = operation["responses"][ok_code]
            rschema = ok_resp.get("content", {}).get("application/json", {}).get("schema", {})
            rref = rschema.get("$ref", "")
            if not rref.endswith("/" + resp_name):
                _fail(f"W1D_OPENAPI_RESPONSE_REF_MISMATCH: {path} want {resp_name} got {rref}")
            for err_code in required_error_statuses:
                if err_code not in operation.get("responses", {}):
                    _fail(f"W1D_OPENAPI_ERROR_STATUS_MISSING: {method.upper()} {path} {err_code}")
                err_schema = (
                    operation["responses"][err_code]
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                err_ref = err_schema.get("$ref", "")
                if not err_ref.endswith("/RecipientErrorEnvelope"):
                    _fail(
                        f"W1D_OPENAPI_ERROR_ENVELOPE_REF_MISMATCH: {path} {err_code} got {err_ref}"
                    )

    # Generate a fresh temporary client and validate the backend-owned contract.
    # Updating the checked-in frontend client is a separate integration scope.
    generator = REPO_ROOT / "scripts" / "generate-openapi-types.ps1"
    if not generator.is_file():
        _fail("W1D_HARNESS_OPENAPI_GENERATOR_MISSING")
    tracked = REPO_ROOT / "frontend" / "src" / "generated" / "sswcenter-api.ts"
    if not tracked.is_file():
        _fail("W1D_HARNESS_TRACKED_GENERATED_TS_MISSING")
    # Generate into a temporary directory only; never write the tracked frontend file.
    if CONTRACT_COLLECTION in paths:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="w1d-oa-") as tmp:
            tmp_path = Path(tmp)
            oa_json = tmp_path / "openapi.json"
            out_ts = tmp_path / "sswcenter-api.ts"
            try:
                extract = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import json,sys; from app.main import app; "
                        "from pathlib import Path; "
                        "Path(sys.argv[1]).write_text(json.dumps(app.openapi(),"
                        " ensure_ascii=False, indent=2), encoding='utf-8')",
                        str(oa_json),
                    ],
                    cwd=str(BACKEND_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                _fail("W1D_HARNESS_OPENAPI_EXTRACT_FAILED")
            if extract.returncode != 0 or not oa_json.is_file():
                _fail("W1D_HARNESS_OPENAPI_EXTRACT_FAILED")
            try:
                gen = subprocess.run(
                    [
                        _npm_executable(),
                        "exec",
                        "--",
                        "openapi-typescript",
                        str(oa_json),
                        "-o",
                        str(out_ts),
                    ],
                    cwd=str(REPO_ROOT / "frontend"),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                _fail("W1D_HARNESS_OPENAPI_TS_GEN_FAILED")
            if gen.returncode != 0 or not out_ts.is_file():
                _fail("W1D_OPENAPI_TEMP_GENERATE_FAILED")
            generated_text = out_ts.read_text(encoding="utf-8")
            for required_name in REQUIRED_SCHEMAS:
                if required_name not in generated_text:
                    _fail("W1D_OPENAPI_TEMP_GENERATED_SCHEMA_MISSING: " + required_name)


def test_w1d_04_sqlalchemy_metadata_has_recipient_contract() -> None:
    """ORM metadata must define recipient_contract with required absences."""
    try:
        from app.db import models as db_models
    except Exception:
        _fail("W1D_HARNESS_MODELS_IMPORT_MISSING")

    table = getattr(db_models, "RecipientContract", None)
    if table is None:
        _fail("W1D_ORM_MODEL_MISSING: RecipientContract")

    columns = {c.name for c in table.__table__.columns}
    for required in (
        "id",
        "recipient_id",
        "service_type_id",
        "start_date",
        "end_date",
        "service_start_date",
        "end_reason_text",
        "row_version",
        "invalidated_at_utc",
    ):
        if required not in columns:
            _fail("W1D_ORM_COLUMN_MISSING: " + required)

    for forbidden in FORBIDDEN_CONTRACT_PROPERTIES:
        if forbidden in columns:
            _fail("W1D_ABS08_ORM_FORBIDDEN_COLUMN: " + forbidden)

    nullable = {c.name: c.nullable for c in table.__table__.columns}
    for must_null in (
        "end_date",
        "service_start_date",
        "end_reason_text",
    ):
        if nullable.get(must_null) is False:
            _fail("W1D_CON01_ORM_NULLABLE_VIOLATION: " + must_null)
    if nullable.get("start_date") is not False:
        _fail("W1D_CON01_ORM_START_DATE_NOT_REQUIRED")
    if nullable.get("service_start_date") is False:
        _fail("W1D_ABS10_ORM_SERVICE_START_NOT_NULL")


def test_w1d_05_service_exports_contract_operations_only() -> None:
    """Service must expose contract CRUD and omit retired transition operations."""
    try:
        from app.domains.w1d.service import W1DService
    except Exception:
        _fail("W1D_SERVICE_MODULE_MISSING: W1DService")

    for method in (
        "list_contracts",
        "create_contract",
        "get_contract",
        "end_contract",
    ):
        if not hasattr(W1DService, method):
            _fail("W1D_SERVICE_METHOD_MISSING: " + method)
    for retired in ("preview_certification_transition", "apply_certification_transition"):
        if hasattr(W1DService, retired):
            _fail("W1D_RETIRED_TRANSITION_SERVICE_PRESENT: " + retired)


def test_w1d_abs_08_contract_no_surface_is_absent() -> None:
    """W1-ABS-08: contract_no must not exist on public surfaces (PASS-separated)."""
    from app.main import app

    spec = app.openapi()
    # Existing non-contract schemas may mention unrelated tokens; scan contract-named only.
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        if "Contract" not in name and "contract" not in name:
            continue
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if "contract_no" in props or "contract_sequence" in props:
            _fail("W1D_ABS08_CONTRACT_NO_PRESENT: " + name)
    # ORM: if model missing, product RED owns that; ABS only fails if present+forbidden.
    try:
        from app.db.models import RecipientContract

        columns = {c.name for c in RecipientContract.__table__.columns}
        if "contract_no" in columns or "contract_sequence" in columns:
            _fail("W1D_ABS08_CONTRACT_NO_COLUMN_PRESENT")
    except Exception:
        # Model absence is not an ABS failure.
        pass
    assert True


def test_w1d_abs_09_end_reason_and_discharge_surface_is_absent() -> None:
    """W1-ABS-09: fixed end_reason_code / death default / discharge_date absent."""
    from app.main import app

    spec = app.openapi()
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        if not isinstance(schema, dict):
            continue
        if "Contract" not in name and "contract" not in name.lower():
            continue
        props = schema.get("properties", {})
        if "end_reason_code" in props or "discharge_date" in props:
            _fail("W1D_ABS09_FORBIDDEN_FIELD_PRESENT: " + name)
        end_reason = props.get("end_reason_text")
        if isinstance(end_reason, dict) and (
            "enum" in end_reason or end_reason.get("default") == "사망"
        ):
            _fail("W1D_ABS09_END_REASON_ENUM_OR_DEATH_DEFAULT")
    assert True


def test_w1d_abs_10_service_start_not_gated() -> None:
    """W1-ABS-10: service_start_date must not be required / NOT NULL on public contract."""
    from app.main import app

    spec = app.openapi()
    create = spec.get("components", {}).get("schemas", {}).get("ContractCreateRequest")
    if create is None:
        # Schema missing is product RED (test_w1d_03), not ABS fail.
        assert True
        return
    required = set(create.get("required", []))
    if "service_start_date" in required:
        _fail("W1D_ABS10_SERVICE_START_REQUIRED")
    assert True


def test_w1d_stable_error_code_constants_are_exported() -> None:
    """Domain error map should export only the current contract conflict codes."""
    try:
        from app.domains.w1d import errors as w1d_errors
    except Exception:
        _fail("W1D_ERRORS_MODULE_MISSING")

    codes = getattr(w1d_errors, "STABLE_CODES", None) or getattr(w1d_errors, "ERROR_CODES", None)
    if codes is None:
        exported = {
            name: getattr(w1d_errors, name)
            for name in dir(w1d_errors)
            if name.isupper() and isinstance(getattr(w1d_errors, name), str)
        }
        codes = set(exported.values())
    else:
        codes = set(codes)
    missing = sorted(STABLE_ERROR_CODES - codes)
    if missing:
        _fail("W1D_STABLE_ERROR_CODE_MISSING: " + ",".join(missing))
    retired = sorted(code for code in codes if "TRANSITION" in code)
    if retired:
        _fail("W1D_RETIRED_TRANSITION_ERROR_PRESENT: " + ",".join(retired))
