from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_EXACT_LICENSE_RECORDS = {
    ("CARE_WORKER", "요양보호사"),
    ("SOCIAL_WORKER", "사회복지사"),
    ("NURSE", "간호사"),
}
_EXACT_SERVICE_GROUP_RECORDS = {
    ("LONG_TERM_CARE", "장기요양"),
    ("LOCAL_CARE", "지역돌봄 연계"),
    ("BARO_CARE", "바로돌봄"),
}
_EXACT_SERVICE_RECORDS = {
    ("LONG_TERM_CARE", "HOME_CARE", "방문요양"),
    ("LONG_TERM_CARE", "HOME_BATH", "방문목욕"),
    ("LOCAL_CARE", "TEMP_HOME_CARE", "일시재가"),
    ("LOCAL_CARE", "HOSPITAL_ESCORT", "병원동행"),
    ("BARO_CARE", "BARO_CARE", "바로돌봄"),
}
_EXCLUDED_LICENSE_CODES = {
    "CARE_WORKER_LEVEL",
    "SOCIAL_WORKER_LEVEL",
    "NURSING_ASSISTANT",
    "FACILITY_MANAGER",
    "CARE_CENTER_MANAGER",
    "FACILITY_DIRECTOR",
}


def _source_files(root: Path) -> list[Path]:
    excluded = {".venv", ".ruff_cache", ".mypy_cache", "__pycache__"}
    return sorted(
        path for path in root.rglob("*.py") if not any(part in excluded for part in path.parts)
    )


def _source_documents(*roots: Path) -> list[tuple[Path, str]]:
    documents: list[tuple[Path, str]] = []
    for root in roots:
        paths = [root] if root.is_file() else _source_files(root) if root.is_dir() else []
        documents.extend((path, path.read_text(encoding="utf-8")) for path in paths)
    return documents


BACKEND_DOCUMENTS = _source_documents(
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "alembic" / "versions",
)
BACKEND_SOURCE = "\n".join(text for _, text in BACKEND_DOCUMENTS)
GENERATED_OPENAPI = (REPO_ROOT / "frontend" / "src" / "generated" / "sswcenter-api.ts").read_text(
    encoding="utf-8"
)


def _class_blocks(source: str, name_pattern: str) -> list[tuple[str, str]]:
    header_pattern = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\b[^\n]*$", re.MULTILINE)
    headers = list(header_pattern.finditer(source))
    blocks: list[tuple[str, str]] = []
    for index, header in enumerate(headers):
        name = header.group(1)
        if not re.fullmatch(name_pattern, name):
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(source)
        blocks.append((name, source[header.start() : end]))
    return blocks


def _generated_named_schema_blocks() -> list[tuple[str, str]]:
    lines = GENERATED_OPENAPI.splitlines()
    blocks: list[tuple[str, str]] = []
    schema_header = re.compile(r"^\s{8}([A-Za-z_][A-Za-z0-9_]*): \{$")
    for index, line in enumerate(lines):
        match = schema_header.match(line)
        if not match or not re.search(r"License|Qualification", match.group(1)):
            continue
        end = len(lines)
        for next_line in lines[index + 1 :]:
            if schema_header.match(next_line) or next_line == "    };":
                end = index + 1 + lines[index + 1 :].index(next_line)
                break
        blocks.append((match.group(1), "\n".join(lines[index:end])))
    return blocks


def _literal_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for _, source in BACKEND_DOCUMENTS:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                record: dict[str, Any] = {}
                for key, value in zip(node.keys, node.values, strict=False):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        try:
                            record[key.value] = ast.literal_eval(value)
                        except (ValueError, TypeError, SyntaxError):
                            continue
                if record:
                    records.append(record)
            elif isinstance(node, ast.Call):
                record = {}
                for keyword in node.keywords:
                    if keyword.arg is None:
                        continue
                    try:
                        record[keyword.arg] = ast.literal_eval(keyword.value)
                    except (ValueError, TypeError, SyntaxError):
                        continue
                if record:
                    records.append(record)
    return records


def _record_code(record: dict[str, Any]) -> str | None:
    for key in ("code", "license_type_code", "service_type_code"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _record_display_name(record: dict[str, Any]) -> str | None:
    for key in ("display_name", "label", "name"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return None


def _fail(marker: str) -> None:
    pytest.fail(marker, pytrace=False)


def _vs2_public_surface() -> str:
    model_blocks = [
        block
        for _, block in _class_blocks(
            BACKEND_SOURCE, r"[A-Za-z0-9_]*(?:License|Qualification)[A-Za-z0-9_]*"
        )
    ]
    generated_blocks = [block for _, block in _generated_named_schema_blocks()]
    route_lines: list[str] = []
    route_tokens = (
        "/catalogs/services",
        "/catalogs/license-types",
        "/licenses",
        "/service-qualifications",
    )
    backend_lines = BACKEND_SOURCE.splitlines()
    for index, line in enumerate(backend_lines):
        if any(token in line for token in route_tokens):
            route_lines.extend(backend_lines[index : index + 90])
    return "\n".join((*model_blocks, *generated_blocks, *route_lines))


def test_vs2_license_and_qualification_have_separate_named_models_and_routes() -> None:
    license_blocks = _class_blocks(BACKEND_SOURCE, r"[A-Za-z0-9_]*License[A-Za-z0-9_]*")
    qualification_blocks = _class_blocks(
        BACKEND_SOURCE, r"[A-Za-z0-9_]*(?:Qualification|ServiceQualification)[A-Za-z0-9_]*"
    )
    if not license_blocks or not qualification_blocks:
        _fail("W1A_VS2_NAMED_MODELS_MISSING")

    required_routes = (
        "/api/v1/catalogs/services",
        "/api/v1/catalogs/license-types",
        "/api/v1/staff/{staff_id}/licenses",
        "/api/v1/staff/{staff_id}/service-qualifications",
    )
    if not all(route in BACKEND_SOURCE or route in GENERATED_OPENAPI for route in required_routes):
        _fail("W1A_VS2_LICENSE_QUALIFICATION_ROUTES_MISSING")

    has_license_openapi_name = any(
        "License" in name for name, _ in _generated_named_schema_blocks()
    )
    has_qualification_openapi_name = any(
        "Qualification" in name for name, _ in _generated_named_schema_blocks()
    )
    if not has_license_openapi_name or not has_qualification_openapi_name:
        _fail("W1A_VS2_OPENAPI_NAMED_MODELS_MISSING")


def test_vs2_service_catalog_has_exact_three_groups_and_five_services() -> None:
    records = _literal_records()
    group_records = {
        (_record_code(record), _record_display_name(record))
        for record in records
        if _record_code(record) in {code for code, _ in _EXACT_SERVICE_GROUP_RECORDS}
    }
    if not _EXACT_SERVICE_GROUP_RECORDS.issubset(group_records):
        _fail("W1A_VS2_SERVICE_GROUP_CATALOG_MISSING")

    service_records = {
        (
            record.get("group_code") or record.get("service_group_code"),
            _record_code(record),
            _record_display_name(record),
        )
        for record in records
        if _record_code(record) in {code for _, code, _ in _EXACT_SERVICE_RECORDS}
    }
    if not _EXACT_SERVICE_RECORDS.issubset(service_records):
        _fail("W1A_VS2_SERVICE_TYPE_CATALOG_MISSING")


def test_vs2_initial_license_type_seed_has_exact_user_approved_code_display_pairs() -> None:
    records = _literal_records()
    pairs = {
        (_record_code(record), _record_display_name(record))
        for record in records
        if _record_code(record) is not None and _record_display_name(record) is not None
    }
    if not _EXACT_LICENSE_RECORDS.issubset(pairs):
        _fail("W1A_VS2_LICENSE_TYPE_CODE_DISPLAY_MISSING")
    if any(code in _EXCLUDED_LICENSE_CODES for code, _ in pairs):
        _fail("W1A_VS2_LICENSE_TYPE_EXCLUDED_CODE_PRESENT")


def test_vs2_license_fact_has_number_and_issue_date_without_period_or_two_item_limit() -> None:
    fact_blocks = [
        block
        for name, block in _class_blocks(BACKEND_SOURCE, r"[A-Za-z0-9_]*License[A-Za-z0-9_]*")
        if "Type" not in name
    ]
    if not fact_blocks:
        _fail("W1A_VS2_LICENSE_FACT_MODEL_MISSING")
    fact_source = "\n".join(fact_blocks)
    if "license_number" not in fact_source or "issued_date" not in fact_source:
        _fail("W1A_VS2_LICENSE_FACT_FIELDS_MISSING")
    if re.search(r"\b(?:expiry|expiration|start|end)_date\b", fact_source, re.IGNORECASE):
        _fail("W1A_VS2_LICENSE_PERIOD_FIELDS_FORBIDDEN")
    if re.search(r"max[_-]?items\s*[:=]?\s*2", fact_source, re.IGNORECASE):
        _fail("W1A_VS2_LICENSE_TWO_ITEM_LIMIT_FORBIDDEN")


def test_vs2_qualification_period_optional_source_and_no_duplicate_facts() -> None:
    qualification_blocks = _class_blocks(
        BACKEND_SOURCE, r"[A-Za-z0-9_]*(?:Qualification|ServiceQualification)[A-Za-z0-9_]*"
    )
    if not qualification_blocks:
        _fail("W1A_VS2_QUALIFICATION_MODEL_MISSING")
    qualification_source = "\n".join(block for _, block in qualification_blocks)
    required_fields = ("employment_id", "service_type_code", "start_date", "end_date")
    if not all(field in qualification_source for field in required_fields):
        _fail("W1A_VS2_QUALIFICATION_PERIOD_FIELDS_MISSING")
    if "source_license_id" not in qualification_source:
        _fail("W1A_VS2_QUALIFICATION_SOURCE_FIELD_MISSING")
    source_lines = [
        line for line in qualification_source.splitlines() if "source_license_id" in line
    ]
    if not any("None" in line or "Optional" in line or "|" in line for line in source_lines):
        _fail("W1A_VS2_QUALIFICATION_SOURCE_MUST_BE_OPTIONAL")
    if "license_number" in qualification_source or "issued_date" in qualification_source:
        _fail("W1A_VS2_QUALIFICATION_DUPLICATES_LICENSE_FACTS")
    if "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH" not in BACKEND_SOURCE:
        _fail("W1A_VS2_SAME_STAFF_SOURCE_GUARD_MISSING")


def test_vs2_permissions_and_structured_errors_are_named() -> None:
    required_names = (
        "STAFF_VIEW",
        "STAFF_MANAGE",
        "ROW_VERSION_CONFLICT",
        "VALIDATION_ERROR",
        "STAFF_LICENSE_NOT_FOUND",
        "STAFF_LICENSE_DUPLICATE",
        "STAFF_SERVICE_QUALIFICATION_NOT_FOUND",
        "STAFF_SERVICE_QUALIFICATION_CONFLICT",
        "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH",
    )
    if not all(name in BACKEND_SOURCE for name in required_names):
        _fail("W1A_VS2_PERMISSION_OR_ERROR_CONTRACT_MISSING")


def test_vs2_forbidden_relations_are_limited_to_public_vs2_surface() -> None:
    vs2_surface = _vs2_public_surface()
    forbidden_relation_tokens = (
        "schedule_id",
        "assignment_id",
        "file_id",
        "legacy_employee_id",
        "legacy_staff_id",
    )
    if any(
        re.search(rf"\b{re.escape(token)}\b", vs2_surface, re.IGNORECASE)
        for token in forbidden_relation_tokens
    ):
        _fail("W1A_VS2_FORBIDDEN_PUBLIC_RELATION_OR_LEGACY_PROPERTY_FOUND")

    license_blocks = _class_blocks(BACKEND_SOURCE, r"[A-Za-z0-9_]*License[A-Za-z0-9_]*")
    license_source = "\n".join(block for _, block in license_blocks)
    if re.search(
        r"\b(?:license_)?(?:expiry|expiration|start|end)_date\b",
        license_source,
        re.IGNORECASE,
    ):
        _fail("W1A_VS2_LICENSE_PERIOD_PROPERTY_FOUND")
