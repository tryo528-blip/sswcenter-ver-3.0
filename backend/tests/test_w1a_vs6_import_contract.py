from __future__ import annotations

import ast
import importlib
import inspect
import json
import logging
import re
import traceback
from copy import copy, deepcopy
from datetime import date
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0008_w1a_staff_legacy_mapping.py"
)
IMPORTER_PATH = REPO_ROOT / "backend" / "app" / "domains" / "staff" / "legacy_import.py"
_IMPORTER_LOGGER_NAME = "app.domains.staff.legacy_import"
_IMPORTER_PROBE_MESSAGE = "W1A_VS6_IMPORTER_CAPTURE_PROBE"
ALLOWED_FIELDS = {
    "legacy_staff_key",
    "name",
    "resident_number",
    "address",
    "phone",
    "employment_start_date",
    "employment_end_date",
    "position",
    "licenses",
    "type",
    "number",
    "issued_date",
}
FORBIDDEN_FIELDS = {
    "alias",
    "alias_name",
    "employment_type",
    "employment_status",
    "account_number",
    "bank_account",
    "salary",
    "payroll",
    "insurance",
    "severance",
    "service_unit_price",
    "unused_column",
    "past_health_check",
    "health_check_id",
    "care_change",
    "attachment",
    "file_id",
    "document_id",
    "ocr_run",
    "import_run",
    "import_row",
    "staging",
    "filebox",
}
REQUIRED_REASONS = {
    "ALREADY_MAPPED",
    "DUPLICATE_SOURCE_KEY",
    "INVALID_REQUIRED_FIELD",
    "INVALID_DATE_RANGE",
    "TOO_MANY_LICENSES",
    "STAFF_MATCH_MISSING",
    "STAFF_MATCH_AMBIGUOUS",
}
PREPARE_INTERFACE_NAMES = (
    "prepare",
    "prepare_batch",
    "prepare_import",
    "validate_import",
    "validate_import_batch",
    "preview_import",
)
APPLY_INTERFACE_NAMES = (
    "apply",
    "apply_batch",
    "apply_import",
    "execute_import",
)
PUBLIC_FORBIDDEN_FRAGMENTS = (
    "legacy_staff_key",
    "staff_legacy_mapping",
    "legacy-import",
    "legacy_import",
)
STAFF_IMPORT_FRAGMENTS = (
    "import-run",
    "import_run",
)


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _synthetic_resident_number(
    birth_date: str,
    serial: str,
    *,
    separator: str = "",
) -> str:
    return "".join((birth_date, separator, serial))


def _read(path: Path, marker: str) -> str:
    if not path.is_file():
        _fail(marker)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail(marker)


def _require_migration() -> None:
    _read(
        MIGRATION_PATH,
        "W1A_VS6_MIGRATION_MISSING: 0008 staff legacy mapping migration is absent",
    )


def _parse(source: str) -> ast.Module:
    try:
        return ast.parse(source)
    except SyntaxError:
        _fail("W1A_VS6_SERVICE_MISSING: legacy importer is not valid Python")


def _string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _function_names(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _has_interface_name(functions: set[str], candidates: tuple[str, ...], role: str) -> bool:
    if any(candidate in functions for candidate in candidates):
        return True
    for name in functions:
        lowered = name.lower()
        if name.startswith("_"):
            continue
        if role == "prepare" and (
            "prepare" in lowered or "validate" in lowered and "import" in lowered
        ):
            return True
        if role == "apply" and ("apply" in lowered or "execute" in lowered and "import" in lowered):
            return True
    return False


def _resolve_interface(importer: Any, candidates: tuple[str, ...], role: str) -> Any:
    for name in candidates:
        candidate = getattr(importer, name, None)
        if callable(candidate):
            return candidate
    for name in dir(importer):
        if not _has_interface_name({name}, candidates, role):
            continue
        candidate = getattr(importer, name, None)
        if callable(candidate) and not name.startswith("_"):
            return candidate
    _fail(f"W1A_VS6_{role.upper()}_MISSING: equivalent internal interface is absent")


def _invoke_prepare(
    prepare: Any,
    *,
    rows: list[dict[str, Any]],
    source_system_code: str,
    active_legacy_staff_keys: frozenset[str],
) -> object:
    try:
        parameters = inspect.signature(prepare).parameters
    except (TypeError, ValueError):
        _fail("W1A_VS6_PREPARE_MISSING: prepare signature is unavailable")
    aliases = {
        "rows": ("rows", "batch", "records", "items", "input_rows"),
        "source_system_code": ("source_system_code", "source_code", "source"),
        "active_legacy_staff_keys": ("active_legacy_staff_keys", "active_keys", "mapped_keys"),
    }
    values: dict[str, object] = {
        "rows": rows,
        "source_system_code": source_system_code,
        "active_legacy_staff_keys": active_legacy_staff_keys,
    }
    kwargs: dict[str, object] = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    for semantic_name, value in values.items():
        parameter_name = next(
            (alias for alias in aliases[semantic_name] if alias in parameters), None
        )
        if parameter_name is None and accepts_kwargs:
            parameter_name = semantic_name
        if parameter_name is None:
            _fail(f"W1A_VS6_PREPARE_MISSING: prepare does not accept {semantic_name}")
        kwargs[parameter_name] = value
    return prepare(**kwargs)


def _invoke_apply(
    apply: Any,
    *,
    rows: list[dict[str, Any]],
    source_system_code: str,
    database_session: Session | None = None,
    session_factory: Any = None,
    actor_account_id: int,
    settings: Any,
) -> object:
    try:
        parameters = inspect.signature(apply).parameters
    except (TypeError, ValueError):
        _fail("W1A_VS6_APPLY_MISSING: apply signature is unavailable")
    aliases = {
        "rows": ("rows", "batch", "records", "items", "input_rows"),
        "source_system_code": ("source_system_code", "source_code", "source"),
        "database_session": ("database_session", "session", "db_session"),
        "session_factory": ("session_factory", "sessionmaker", "factory"),
        "actor_account_id": ("actor_account_id", "actor_id", "account_id"),
        "settings": ("settings", "config"),
    }
    values: dict[str, object] = {
        "rows": rows,
        "source_system_code": source_system_code,
        "database_session": database_session,
        "session_factory": session_factory,
        "actor_account_id": actor_account_id,
        "settings": settings,
    }
    kwargs: dict[str, object] = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    for semantic_name, value in values.items():
        if value is None:
            continue
        parameter_name = next(
            (alias for alias in aliases[semantic_name] if alias in parameters), None
        )
        if parameter_name is None and accepts_kwargs:
            parameter_name = semantic_name
        if parameter_name is None:
            _fail(f"W1A_VS6_APPLY_MISSING: apply does not accept {semantic_name}")
        kwargs[parameter_name] = value
    return apply(**kwargs)


class _SyntheticErrorSession(Session):
    """Exercise the real importer error boundary with a non-production DB error."""

    def __init__(
        self,
        *args: Any,
        synthetic_error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._synthetic_error = synthetic_error or _synthetic_integrity_error()

    def scalars(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> tuple[object, ...]:
        return ()

    def scalar(self, *args: Any, **kwargs: Any) -> None:
        return None

    def flush(self, *args: Any, **kwargs: Any) -> None:
        raise self._synthetic_error


_LogSnapshot = tuple[str, str, str, str, str, str]


def _snapshot_log_record(record: logging.LogRecord) -> _LogSnapshot:
    exception_text = ""
    if record.exc_info is not None:
        exception_text = "".join(traceback.format_exception(*record.exc_info))
    record_copy = copy(record)
    formatted = logging.Formatter().format(record_copy)
    return (
        record.name,
        record.getMessage(),
        repr(record.args),
        exception_text,
        record.exc_text or "",
        formatted,
    )


class _OuterExcInfoFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.observed_count = 0
        self.pre_redaction_snapshots: list[_LogSnapshot] = []

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "w1a-vs6.tests.outer" and record.exc_info is not None:
            self.observed_count += 1
            record._w1a_outer_exc_info_seen = True
            self.pre_redaction_snapshots.append(_snapshot_log_record(record))
        return True


class _SurfaceCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.snapshots: list[_LogSnapshot] = []
        self.post_redaction_snapshots: list[_LogSnapshot] = []
        self.importer_probe_records = 0

    def emit(self, record: logging.LogRecord) -> None:
        snapshot = _snapshot_log_record(record)
        self.records.append(record)
        self.snapshots.append(snapshot)
        if snapshot[0] == _IMPORTER_LOGGER_NAME and snapshot[1] == _IMPORTER_PROBE_MESSAGE:
            self.importer_probe_records += 1


def _synthetic_error_vectors() -> tuple[str, ...]:
    return (
        _synthetic_resident_number("900201", "1234567", separator="-"),
        "VS6-SYNTHETIC-LEGACY-KEY",
        "VS6 Synthetic Person",
        "SELECT resident_number FROM erp.staff_sensitive_identity",
        "uq_staff_sensitive_identity_lookup_hmac",
        "postgresql://synthetic-user:synthetic-password@db.invalid:5432/synthetic",
        "VS6-SYNTHETIC-PASSWORD",
    )


def _synthetic_integrity_error() -> IntegrityError:
    vectors = _synthetic_error_vectors()
    diagnostic = " | ".join(vectors)
    return IntegrityError(
        "INSERT INTO erp.staff_sensitive_identity VALUES (:resident_number) " + diagnostic,
        {
            "resident_number": vectors[0],
            "legacy_staff_key": vectors[1],
            "name": vectors[2],
            "dsn": vectors[5],
            "password": vectors[6],
        },
        RuntimeError("constraint=" + vectors[4] + " sql=" + diagnostic),
    )


def _synthetic_sqlalchemy_error() -> SQLAlchemyError:
    return SQLAlchemyError("sqlalchemy failure: " + " | ".join(_synthetic_error_vectors()))


def _synthetic_import_row(
    *,
    key: str,
    licenses: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "legacy_staff_key": key,
        "name": "VS6 synthetic import person",
        "resident_number": _synthetic_resident_number("900202", "1234567", separator="-"),
        "address": "VS6 synthetic import address",
        "phone": "010-2000-0202",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": date(2026, 12, 31),
        "position": "CARE_WORKER",
        "licenses": [] if licenses is None else licenses,
    }


def _canonical_license(number: str, *, license_type: str = "CARE_WORKER") -> dict[str, object]:
    return {
        "type": license_type,
        "number": number,
        "issued_date": date(2026, 1, 15),
    }


def _assert_safe_legacy_error(
    raised: Exception,
    records: list[logging.LogRecord],
    *,
    marker: str,
    outer_exc_info_records: int,
    outer_pre_redaction_snapshots: list[_LogSnapshot],
    snapshots: list[_LogSnapshot],
    post_redaction_snapshots: list[_LogSnapshot],
    importer_probe_records: int,
) -> None:
    if raised.__cause__ is not None:
        _fail(marker + "_CAUSE_LINKED")
    if not raised.__suppress_context__:
        _fail(marker + "_CONTEXT_NOT_SUPPRESSED")
    surfaces = [
        str(raised),
        repr(raised),
        repr(raised.args),
        *(repr(argument) for argument in raised.args),
        "".join(traceback.format_exception(raised)),
    ]
    outer_records = [record for record in records if record.name == "w1a-vs6.tests.outer"]
    if (
        len(outer_records) != 1
        or outer_exc_info_records != 1
        or len(outer_pre_redaction_snapshots) != 1
        or not getattr(outer_records[0], "_w1a_outer_exc_info_seen", False)
    ):
        _fail(marker + "_OUTER_LOG_RECORD_MISSING")
    if importer_probe_records != 1:
        _fail(marker + "_IMPORTER_LOG_RECORD_COUNT")
    if len(post_redaction_snapshots) != len(records):
        _fail(marker + "_LOG_SNAPSHOT_MISSING")
    for snapshot in outer_pre_redaction_snapshots + snapshots + post_redaction_snapshots:
        surfaces.extend(snapshot)
    vectors = _synthetic_error_vectors()
    if any(vector in surface for vector in vectors for surface in surfaces):
        _fail(marker + "_RAW_SURFACE_LEAK")


def _run_apply_with_log_capture(
    apply: Any,
    *,
    rows: list[dict[str, object]],
    database_session: Session | None = None,
    session_factory: Any = None,
    marker: str,
) -> None:
    handler = _SurfaceCaptureHandler()
    outer_exc_info_filter = _OuterExcInfoFilter()
    root_logger = logging.getLogger()
    importer_logger = logging.getLogger(_IMPORTER_LOGGER_NAME)
    outer_logger = logging.getLogger("w1a-vs6.tests.outer")
    original_root_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level
    original_importer_level = importer_logger.level
    original_importer_propagate = importer_logger.propagate
    original_outer_level = outer_logger.level
    original_outer_propagate = outer_logger.propagate
    root_logger.addHandler(handler)
    root_logger.handlers.remove(handler)
    root_logger.handlers.insert(0, handler)
    root_logger.setLevel(logging.DEBUG)
    importer_logger.setLevel(logging.DEBUG)
    importer_logger.propagate = True
    outer_logger.addFilter(outer_exc_info_filter)
    outer_logger.setLevel(logging.DEBUG)
    outer_logger.propagate = True
    raised: Exception | None = None
    try:
        kwargs: dict[str, object] = {
            "rows": rows,
            "source_system_code": "VS6_SYNTHETIC_ERROR_SOURCE",
            "actor_account_id": 1,
            "settings": None,
        }
        if database_session is not None:
            kwargs["database_session"] = database_session
        else:
            kwargs["session_factory"] = session_factory
        try:
            _invoke_apply(apply, **kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            raised = exc
        if raised is not None:
            outer_logger.error(
                "outer LegacyImportError boundary",
                exc_info=(type(raised), raised, raised.__traceback__),
            )
        importer_logger.info(_IMPORTER_PROBE_MESSAGE)
        handler.post_redaction_snapshots = [
            _snapshot_log_record(record) for record in handler.records
        ]
    finally:
        outer_logger.removeFilter(outer_exc_info_filter)
        outer_logger.setLevel(original_outer_level)
        outer_logger.propagate = original_outer_propagate
        importer_logger.setLevel(original_importer_level)
        importer_logger.propagate = original_importer_propagate
        root_logger.removeHandler(handler)
        root_logger.handlers[:] = original_root_handlers
        root_logger.setLevel(original_root_level)
    error_type = importlib.import_module("app.domains.staff.legacy_import").LegacyImportError
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail(marker + "_SERVICE_MISSING")
    if raised is None:
        _fail(marker + "_NOT_RAISED")
    if not isinstance(raised, error_type):
        _fail(marker + "_RAW_EXCEPTION_ESCAPED")
    _assert_safe_legacy_error(
        raised,
        handler.records,
        marker=marker,
        outer_exc_info_records=outer_exc_info_filter.observed_count,
        outer_pre_redaction_snapshots=outer_exc_info_filter.pre_redaction_snapshots,
        snapshots=handler.snapshots,
        post_redaction_snapshots=handler.post_redaction_snapshots,
        importer_probe_records=handler.importer_probe_records,
    )


def _load_importer() -> Any:
    _require_migration()
    try:
        return importlib.import_module("app.domains.staff.legacy_import")
    except (ImportError, RuntimeError):
        _fail("W1A_VS6_SERVICE_MISSING: internal legacy importer could not be loaded")


def _summary_payload(summary: object) -> dict[str, Any]:
    model_dump = getattr(summary, "model_dump", None)
    if isinstance(summary, dict):
        payload = summary
    elif callable(model_dump):
        payload = model_dump()
    elif hasattr(summary, "__dict__"):
        payload = vars(summary)
    else:
        _fail("W1A_VS6_SUMMARY_CONTRACT_MISSING: prepare result is not structured")
    if not isinstance(payload, dict):
        _fail("W1A_VS6_SUMMARY_CONTRACT_MISSING: prepare result is not an object")
    return dict(payload)


def test_vs6_00_internal_prepare_apply_and_allowlist_contract() -> None:
    _require_migration()
    source = _read(
        IMPORTER_PATH,
        "W1A_VS6_SERVICE_MISSING: internal legacy importer is absent",
    )
    tree = _parse(source)
    functions = _function_names(tree)
    if not _has_interface_name(functions, PREPARE_INTERFACE_NAMES, "prepare"):
        _fail("W1A_VS6_PREPARE_MISSING: internal prepare contract is absent")
    if not _has_interface_name(functions, APPLY_INTERFACE_NAMES, "apply"):
        _fail("W1A_VS6_APPLY_MISSING: internal apply contract is absent")
    literals = _string_literals(tree)
    missing = sorted(ALLOWED_FIELDS - literals)
    if missing:
        _fail("W1A_VS6_ALLOWLIST_MISSING: allowed input field is absent: " + ",".join(missing))
    present_forbidden = sorted(FORBIDDEN_FIELDS.intersection(literals))
    if present_forbidden:
        _fail("W1A_VS6_FORBIDDEN_IMPORT_FIELD_FOUND: " + ",".join(present_forbidden))
    if "maxItems" in source or "MaxLen" in source:
        if "licenses" not in source or "2" not in source:
            _fail("W1A_VS6_LICENSE_LIMIT_MISSING: import license limit is not exactly two")


def test_vs6_01_prepare_is_summary_only_and_duplicate_rules_are_stable() -> None:
    _require_migration()
    source = _read(
        IMPORTER_PATH,
        "W1A_VS6_SERVICE_MISSING: internal legacy importer is absent",
    )
    tree = _parse(source)
    literals = _string_literals(tree)
    missing = sorted(REQUIRED_REASONS - literals)
    if missing:
        _fail("W1A_VS6_REASON_CODES_MISSING: stable reason code is absent: " + ",".join(missing))
    for fragment in ("included", "excluded", "reason_counts"):
        if fragment not in source.lower():
            _fail("W1A_VS6_SUMMARY_CONTRACT_MISSING: counts/reasons summary is absent")
    if "legacy_staff_key" in source and "ALREADY_MAPPED" not in source:
        _fail("W1A_VS6_RERUN_GUARD_MISSING: active mapping rerun is not guarded")
    if "DUPLICATE_SOURCE_KEY" not in source:
        _fail("W1A_VS6_BATCH_DUPLICATE_GUARD_MISSING: duplicate source key is not excluded")
    if any(fragment in source.lower() for fragment in ("print(", "logger.", "logging.")):
        if any(token in source.lower() for token in ("legacy_staff_key", "resident_number")):
            _fail("W1A_VS6_PII_OUTPUT_RISK: importer logging/output touches input identity")


def test_vs6_02_apply_is_atomic_and_uses_existing_crypto_and_preserves_display_values() -> None:
    _require_migration()
    source = _read(
        IMPORTER_PATH,
        "W1A_VS6_SERVICE_MISSING: internal legacy importer is absent",
    )
    lowered = source.lower()
    if not any(
        fragment in lowered for fragment in ("session.begin", "connection.begin", "transaction")
    ):
        _fail("W1A_VS6_ATOMIC_APPLY_MISSING: apply does not declare a transaction")
    if "rollback" not in lowered:
        _fail("W1A_VS6_ATOMIC_APPLY_MISSING: apply rollback path is absent")
    if not re.search(
        r"(?:encrypt|seal|protect).{0,100}(?:resident|rrn|sensitive)",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        _fail("W1A_VS6_CRYPTO_PATH_MISSING: existing resident-number crypto is not used")
    if "display_name" not in source or "memo" not in source:
        _fail("W1A_VS6_DISPLAY_MEMO_PRESERVE_MISSING: display_name/memo preservation is absent")
    if "staff_legacy_mapping" not in source or "invalidated_at_utc" not in source:
        _fail("W1A_VS6_MAPPING_APPLY_MISSING: mapping ledger is not applied/invalidation-aware")
    if "audit" not in lowered or "STAFF_LEGACY_MAPPING_CREATE" not in source:
        _fail("W1A_VS6_AUDIT_PATH_MISSING: mapping audit write is absent")

    importer = _load_importer()
    apply = _resolve_interface(importer, APPLY_INTERFACE_NAMES, "apply")
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    row = {
        "legacy_staff_key": "VS6-SYNTHETIC-ERROR-ROW",
        "name": "VS6 synthetic error row",
        "resident_number": _synthetic_resident_number("900101", "1234567", separator="-"),
        "address": "VS6 synthetic address",
        "phone": "010-2000-0001",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": None,
        "position": "CARE_WORKER",
        "licenses": [],
    }
    raised: Exception | None = None
    try:
        with _SyntheticErrorSession() as database_session:
            _invoke_apply(
                apply,
                rows=[row],
                source_system_code="VS6_SYNTHETIC_SOURCE",
                database_session=database_session,
                actor_account_id=1,
                settings=None,
            )
    except error_type as exc:
        raised = exc
    except Exception:
        _fail("W1A_VS6_PII_EXCEPTION_CHAIN_LEAK: synthetic SQLAlchemy error escaped importer")
    if raised is None:
        _fail("W1A_VS6_PII_EXCEPTION_CHAIN_LEAK: importer did not return LegacyImportError")
    if raised.__cause__ is not None:
        _fail("W1A_VS6_PII_EXCEPTION_CAUSE_LINKED: SQLAlchemy error is chained as __cause__")
    if not raised.__suppress_context__:
        _fail("W1A_VS6_PII_EXCEPTION_CONTEXT_NOT_SUPPRESSED: error context is not hidden")
    surfaces = [
        str(raised),
        repr(raised),
        "".join(traceback.format_exception(raised)),
    ]
    if any(vector in surface for vector in _synthetic_error_vectors() for surface in surfaces):
        _fail("W1A_VS6_PII_EXCEPTION_CHAIN_LEAK: SQLAlchemy parameter escaped safe error surfaces")


def _openapi_document() -> dict[str, Any]:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI could not be built")
    if not isinstance(document, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI document is not an object")
    return document


def test_vs6_03_internal_import_is_not_public_http_or_openapi() -> None:
    document = _openapi_document()
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI paths are not an object")
    exposed_paths = [
        str(path)
        for path in paths
        if any(fragment in str(path).lower() for fragment in PUBLIC_FORBIDDEN_FRAGMENTS)
        or (
            "/staff" in str(path).lower()
            and any(fragment in str(path).lower() for fragment in STAFF_IMPORT_FRAGMENTS)
        )
    ]
    if exposed_paths:
        _fail("W1A_VS6_PUBLIC_IMPORT_ROUTE_FOUND: " + ",".join(sorted(exposed_paths)))
    serialized = json.dumps(document, ensure_ascii=False).lower()
    exposed_properties = [
        fragment for fragment in PUBLIC_FORBIDDEN_FRAGMENTS if fragment in serialized
    ]
    if exposed_properties:
        _fail("W1A_VS6_PUBLIC_IMPORT_PROPERTY_FOUND: " + ",".join(sorted(exposed_properties)))
    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI schemas are not an object")
    staff_schema = json.dumps(
        {name: schema for name, schema in schemas.items() if "staff" in str(name).lower()},
        ensure_ascii=False,
    ).lower()
    exposed_staff_properties = [
        fragment for fragment in STAFF_IMPORT_FRAGMENTS if fragment in staff_schema
    ]
    if exposed_staff_properties:
        _fail(
            "W1A_VS6_PUBLIC_IMPORT_PROPERTY_FOUND: "
            + ",".join(sorted(exposed_staff_properties))
        )


def test_vs6_04_general_license_contract_has_no_import_maximum() -> None:
    document = _openapi_document()
    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI schemas are not an object")
    for name, schema in schemas.items():
        if "license" not in str(name).lower() or not isinstance(schema, dict):
            continue
        if schema.get("maxItems") == 2:
            _fail(
                "W1A_VS6_GENERAL_LICENSE_MAX_ITEMS_FOUND: general license schema is capped at two"
            )
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for property_schema in properties.values():
                if isinstance(property_schema, dict) and property_schema.get("maxItems") == 2:
                    _fail("W1A_VS6_GENERAL_LICENSE_MAX_ITEMS_FOUND: license list is capped at two")


def test_vs6_05_prepare_executes_duplicate_rerun_limit_and_summary_only_contract() -> None:
    importer = _load_importer()
    prepare = _resolve_interface(importer, PREPARE_INTERFACE_NAMES, "prepare")

    base_row: dict[str, Any] = {
        "legacy_staff_key": "VS6-SYNTHETIC-INCLUDED",
        "name": "VS6 synthetic included",
        "resident_number": _synthetic_resident_number("900101", "1234567", separator="-"),
        "address": "VS6 synthetic address",
        "phone": "010-2000-0001",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": None,
        "position": "CARE_WORKER",
        "licenses": [],
    }
    active_row = deepcopy(base_row)
    active_row["legacy_staff_key"] = "VS6-SYNTHETIC-ACTIVE"
    active_row["resident_number"] = _synthetic_resident_number("900102", "1234567", separator="-")

    duplicate_one = deepcopy(base_row)
    duplicate_one["legacy_staff_key"] = "VS6-SYNTHETIC-DUPLICATE"
    duplicate_one["resident_number"] = _synthetic_resident_number(
        "900103", "1234567", separator="-"
    )
    duplicate_two = deepcopy(duplicate_one)
    duplicate_two["resident_number"] = _synthetic_resident_number(
        "900104", "1234567", separator="-"
    )

    too_many_licenses = deepcopy(base_row)
    too_many_licenses["legacy_staff_key"] = "VS6-SYNTHETIC-TOO-MANY"
    too_many_licenses["resident_number"] = _synthetic_resident_number(
        "900105", "1234567", separator="-"
    )
    too_many_licenses["licenses"] = [
        {
            "type": "CARE_WORKER",
            "number": f"VS6-SYNTHETIC-LICENSE-{number}",
            "issued_date": date(2026, 1, number),
        }
        for number in range(1, 4)
    ]

    summary = _invoke_prepare(
        prepare,
        rows=[
            base_row,
            active_row,
            duplicate_one,
            duplicate_two,
            too_many_licenses,
        ],
        source_system_code="VS6_SYNTHETIC_SOURCE",
        active_legacy_staff_keys=frozenset({"VS6-SYNTHETIC-ACTIVE"}),
    )
    payload = _summary_payload(summary)
    if not {"included_count", "excluded_count", "reason_counts"}.issubset(payload):
        _fail("W1A_VS6_SUMMARY_CONTRACT_MISSING: prepare counts/reasons are incomplete")
    if payload["included_count"] != 1 or payload["excluded_count"] != 4:
        _fail("W1A_VS6_SUMMARY_CONTRACT_MISSING: prepare counts are incorrect")
    reason_counts = payload["reason_counts"]
    if not isinstance(reason_counts, dict) or any(
        reason_counts.get(reason) != count
        for reason, count in {
            "ALREADY_MAPPED": 1,
            "DUPLICATE_SOURCE_KEY": 2,
            "TOO_MANY_LICENSES": 1,
        }.items()
    ):
        _fail("W1A_VS6_REASON_CODES_MISSING: prepare reason counts are incorrect")

    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    for sensitive_value in (
        base_row["legacy_staff_key"],
        base_row["name"],
        base_row["resident_number"],
        active_row["legacy_staff_key"],
        duplicate_one["legacy_staff_key"],
    ):
        if str(sensitive_value) in serialized:
            _fail("W1A_VS6_PII_OUTPUT_RISK: prepare summary exposes an input value")

    forbidden_row = deepcopy(base_row)
    forbidden_row["alias_name"] = "VS6 forbidden alias"
    forbidden_summary = _summary_payload(
        _invoke_prepare(
            prepare,
            rows=[forbidden_row],
            source_system_code="VS6_SYNTHETIC_SOURCE",
            active_legacy_staff_keys=frozenset(),
        )
    )
    forbidden_reasons = forbidden_summary.get("reason_counts")
    if (
        forbidden_summary.get("included_count") != 0
        or forbidden_summary.get("excluded_count") != 1
        or not isinstance(forbidden_reasons, dict)
        or forbidden_reasons.get("INVALID_REQUIRED_FIELD") != 1
    ):
        _fail("W1A_VS6_FORBIDDEN_IMPORT_FIELD_FOUND: forbidden input was not excluded safely")


def _assert_canonical_prepare_success(
    prepare: Any,
    *,
    license_rows: list[dict[str, object]],
    marker: str,
) -> None:
    summary = _summary_payload(
        _invoke_prepare(
            prepare,
            rows=[
                _synthetic_import_row(
                    key="VS6-SYNTHETIC-CANONICAL-PREPARE",
                    licenses=license_rows,
                )
            ],
            source_system_code="VS6_SYNTHETIC_CANONICAL_PREPARE",
            active_legacy_staff_keys=frozenset(),
        )
    )
    if (
        summary.get("included_count") != 1
        or summary.get("excluded_count") != 0
        or summary.get("reason_counts") != {}
    ):
        _fail(marker)


def test_vs6_06_prepare_accepts_zero_canonical_licenses() -> None:
    importer = _load_importer()
    prepare = _resolve_interface(importer, PREPARE_INTERFACE_NAMES, "prepare")
    _assert_canonical_prepare_success(
        prepare,
        license_rows=[],
        marker="W1A_VS6_LICENSE_CANONICAL_PREPARE_ZERO_MISSING",
    )


def test_vs6_07_prepare_accepts_one_canonical_license() -> None:
    importer = _load_importer()
    prepare = _resolve_interface(importer, PREPARE_INTERFACE_NAMES, "prepare")
    _assert_canonical_prepare_success(
        prepare,
        license_rows=[_canonical_license("VS6-SYNTHETIC-CANONICAL-PREPARE-ONE")],
        marker="W1A_VS6_LICENSE_CANONICAL_PREPARE_ONE_MISSING",
    )


def test_vs6_08_prepare_accepts_two_canonical_licenses() -> None:
    importer = _load_importer()
    prepare = _resolve_interface(importer, PREPARE_INTERFACE_NAMES, "prepare")
    _assert_canonical_prepare_success(
        prepare,
        license_rows=[
            _canonical_license("VS6-SYNTHETIC-CANONICAL-PREPARE-TWO-1"),
            _canonical_license(
                "VS6-SYNTHETIC-CANONICAL-PREPARE-TWO-2",
                license_type="SOCIAL_WORKER",
            ),
        ],
        marker="W1A_VS6_LICENSE_CANONICAL_PREPARE_TWO_MISSING",
    )


def test_vs6_09_prepare_rejects_legacy_license_aliases() -> None:
    importer = _load_importer()
    prepare = _resolve_interface(importer, PREPARE_INTERFACE_NAMES, "prepare")
    alias_row = _synthetic_import_row(
        key="VS6-SYNTHETIC-LEGACY-LICENSE-ALIASES",
        licenses=[
            {
                "license_type": "CARE_WORKER",
                "license_number": "VS6-SYNTHETIC-LEGACY-LICENSE",
                "issued_date": date(2026, 1, 15),
            }
        ],
    )
    summary = _summary_payload(
        _invoke_prepare(
            prepare,
            rows=[alias_row],
            source_system_code="VS6_SYNTHETIC_LEGACY_ALIAS",
            active_legacy_staff_keys=frozenset(),
        )
    )
    reasons = summary.get("reason_counts")
    if (
        summary.get("included_count") != 0
        or summary.get("excluded_count") != 1
        or not isinstance(reasons, dict)
        or reasons.get("INVALID_REQUIRED_FIELD") != 1
    ):
        _fail("W1A_VS6_LICENSE_LEGACY_ALIAS_ACCEPTED")


def test_vs6_10_database_session_sqlalchemy_surfaces_are_safe() -> None:
    importer = _load_importer()
    apply = _resolve_interface(importer, APPLY_INTERFACE_NAMES, "apply")
    row = _synthetic_import_row(key="VS6-SYNTHETIC-DATABASE-SESSION-ERROR")
    with _SyntheticErrorSession(synthetic_error=_synthetic_integrity_error()) as database_session:
        _run_apply_with_log_capture(
            apply,
            rows=[row],
            database_session=database_session,
            marker="W1A_VS6_PII_DATABASE_SESSION_EXCEPTION",
        )


def test_vs6_11_session_factory_sqlalchemy_surfaces_are_safe() -> None:
    importer = _load_importer()
    apply = _resolve_interface(importer, APPLY_INTERFACE_NAMES, "apply")
    factory = sessionmaker(
        class_=_SyntheticErrorSession,
        synthetic_error=_synthetic_sqlalchemy_error(),
    )
    row = _synthetic_import_row(key="VS6-SYNTHETIC-SESSION-FACTORY-ERROR")
    _run_apply_with_log_capture(
        apply,
        rows=[row],
        session_factory=factory,
        marker="W1A_VS6_PII_SESSION_FACTORY_EXCEPTION",
    )
