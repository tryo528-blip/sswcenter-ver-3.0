"""W2 Phase 1 RED: SERVICE-PLAN-NOTICE DB/contract package.

The product migration/model are intentionally absent at this phase. Harness
checks must pass independently; missing product bytes must fail
with stable W2 markers rather than being softened into a pass.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, ExcludeConstraint

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ALEMBIC_ROOT = BACKEND_ROOT / "alembic"
MIGRATIONS_ROOT = ALEMBIC_ROOT / "versions"

BASIS_SHA = "ffd7a6991de3d56403801262a95b796b98da8907"
W2_PREV_HEAD = "20260808_0017_recipient_guardian_email"
W2_REVISION = "20260809_0018_w2_service_plan_notice"
W2_MIGRATION_FILE = "20260809_0018_w2_service_plan_notice.py"

W2_COLUMNS = (
    "id",
    "recipient_contract_id",
    "notification_date",
    "applied_start_date",
    "applied_end_date",
    "invalidated_at_utc",
    "replacement_service_plan_notice_id",
    "created_by_account_id",
    "created_at_utc",
    "updated_by_account_id",
    "updated_at_utc",
    "row_version",
)

# recipient_certification_period_id MUST NOT exist (§2-4 결정, 2026-08-09 형님 확정)
W2_FORBIDDEN_COLUMNS = frozenset({"recipient_certification_period_id"})

W2_CONSTRAINT_NAMES = frozenset(
    {
        "pk_recipient_service_plan_notice",
        "fk_service_plan_notice_recipient_contract",
        "fk_service_plan_notice_replacement",
        "fk_service_plan_notice_created_by_account",
        "fk_service_plan_notice_updated_by_account",
        "ck_service_plan_notice_date_order",
        "ck_service_plan_notice_row_version_positive",
    }
)

W2_FUNCTION_TARGETS = frozenset(
    {
        "erp.fn_service_plan_notice_within_contract",
        "erp.fn_service_plan_notice_within_certification",
        "erp.fn_service_plan_notice_before_contract_start",
        "erp.fn_recipient_contract_service_plan_reverse_guard",
        "erp.fn_recipient_certification_period_service_plan_reverse_guard",
        "erp.fn_recipient_contract_recipient_id_immutable",
        "erp.fn_recipient_certification_period_recipient_id_immutable",
    }
)
W2_TRIGGER_TARGETS = frozenset(
    {
        "ct_service_plan_notice_within_contract",
        "ct_service_plan_notice_within_certification",
        "ct_service_plan_notice_before_contract_start",
        "ct_recipient_contract_service_plan_reverse_guard",
        "ct_recipient_certification_period_service_plan_reverse_guard",
        "ct_recipient_contract_recipient_id_immutable",
        "ct_recipient_certification_period_recipient_id_immutable",
    }
)

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
    ("20260730_0011_w1d_recipient_contract", "20260730_0010_w1c_certification_ledgers"),
    ("20260801_0012_w1e_care_assignment", "20260730_0011_w1d_recipient_contract"),
    ("20260802_0013_staff_continuing_education", "20260801_0012_w1e_care_assignment"),
    ("20260803_0014_recipient_plan_notification", "20260802_0013_staff_continuing_education"),
    ("20260806_0015_recipient_status_tag", "20260803_0014_recipient_plan_notification"),
    ("20260808_0016_recipient_payer_guardian", "20260806_0015_recipient_status_tag"),
    (W2_PREV_HEAD, "20260808_0016_recipient_payer_guardian"),
)


class _UnsupportedPlpgsql(Exception):
    """Raised when PL/pgSQL content cannot be safely tokenised."""


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _product_absent(marker: str) -> NoReturn:
    _fail("W2_PRODUCT_ABSENT: " + marker)


def _down_revision_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is str:
        return (value,)
    if type(value) in (tuple, list):
        values = tuple(value)
        if not all(type(item) is str for item in values):
            _fail("W2_HARNESS_MIGRATION_GRAPH_INVALID: non-string down_revision")
        return values
    _fail("W2_HARNESS_MIGRATION_GRAPH_INVALID: unsupported down_revision type")


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ALEMBIC_ROOT))
    try:
        return ScriptDirectory.from_config(config)
    except (CommandError, KeyError, OSError) as exc:
        _fail("W2_HARNESS_MIGRATION_GRAPH_MISSING: " + type(exc).__name__)


def _all_revisions(script: ScriptDirectory) -> list[Any]:
    try:
        revisions = list(script.walk_revisions())
    except (CommandError, KeyError, OSError) as exc:
        _fail("W2_HARNESS_MIGRATION_GRAPH_MISSING: " + type(exc).__name__)
    return revisions


def _basis_bytes(relative_path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "show", f"{BASIS_SHA}:{relative_path}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail("W2_HARNESS_BASIS_MISSING: " + type(exc).__name__)
    if result.returncode != 0:
        _fail("W2_HARNESS_BASIS_MISSING: " + relative_path)
    return result.stdout


def _sql_quoted_span(sql: str, index: int) -> tuple[str, int | None] | None:
    """Return (quote kind, exclusive stop), including PostgreSQL E strings."""
    if sql[index] in ("e", "E") and index + 1 < len(sql) and sql[index + 1] == "'":
        kind = "escape_string"
        quote = "'"
        cursor = index + 2
    elif sql[index] == "'":
        kind = "string"
        quote = "'"
        cursor = index + 1
    elif sql[index] == '"':
        kind = "quoted_identifier"
        quote = '"'
        cursor = index + 1
    else:
        return None

    while cursor < len(sql):
        if kind == "escape_string" and sql[cursor] == "\\":
            if cursor + 1 >= len(sql):
                return kind, None
            cursor += 2
            continue
        if sql[cursor] != quote:
            cursor += 1
            continue
        if cursor + 1 < len(sql) and sql[cursor + 1] == quote:
            cursor += 2
            continue
        return kind, cursor + 1
    return kind, None


def _sql_dollar_span(sql: str, index: int) -> tuple[str, int | None] | None:
    """Return (dollar tag, exclusive stop) without inspecting quoted content."""
    match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[index:])
    if match is None:
        return None
    tag = match.group()
    end = sql.find(tag, index + len(tag))
    return tag, None if end < 0 else end + len(tag)


def _sql_block_comment_stop(sql: str, index: int) -> int | None:
    """Return the exclusive stop of a possibly nested PostgreSQL block comment."""
    depth = 1
    cursor = index + 2
    while cursor < len(sql):
        if sql.startswith("/*", cursor):
            depth += 1
            cursor += 2
            continue
        if sql.startswith("*/", cursor):
            depth -= 1
            cursor += 2
            if depth == 0:
                return cursor
            continue
        cursor += 1
    return None


def _masked_sql_fragment(value: str) -> str:
    """Replace lexical content with spaces while preserving newlines and offsets."""
    return "".join("\n" if character == "\n" else " " for character in value)


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL/PLpgSQL comments without treating quoted text as comments."""
    pieces: list[str] = []
    index = 0
    while index < len(sql):
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            if newline < 0:
                break
            pieces.append("\n")
            index = newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                break
            pieces.append(" ")
            index = end + 2
            continue
        quoted = _sql_quoted_span(sql, index)
        if quoted is not None:
            _, stop = quoted
            stop = len(sql) if stop is None else stop
            pieces.append(sql[index:stop])
            index = stop
            continue
        if sql[index] == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[index:])
            if match:
                tag = match.group(0)
                end = sql.find(tag, index + len(tag))
                if end < 0:
                    pieces.append(sql[index:])
                    break
                inner = sql[index + len(tag) : end]
                pieces.append(tag + _strip_sql_comments(inner) + tag)
                index = end + len(tag)
                continue
        pieces.append(sql[index])
        index += 1
    return "".join(pieces)


def _mask_sql_literals(sql: str, *, dollar_quoted: bool) -> str:
    """Mask literals while preserving offsets and executable SQL tokens."""

    def masked(value: str) -> str:
        return "".join("\n" if character == "\n" else " " for character in value)

    pieces: list[str] = []
    index = 0
    while index < len(sql):
        quoted = _sql_quoted_span(sql, index)
        if quoted is not None:
            kind, stop = quoted
            stop = len(sql) if stop is None else stop
            if kind == "quoted_identifier":
                pieces.append(sql[index:stop])
            else:
                pieces.append(masked(sql[index:stop]))
            index = stop
            continue
        if dollar_quoted and sql[index] == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[index:])
            if match:
                tag = match.group(0)
                end = sql.find(tag, index + len(tag))
                if end < 0:
                    pieces.append(masked(sql[index:]))
                    break
                stop = end + len(tag)
                pieces.append(masked(sql[index:stop]))
                index = stop
                continue
        pieces.append(sql[index])
        index += 1
    return "".join(pieces)


def _top_level_sql_statement_spans(ddl_scan: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    quote: str | None = None
    start = 0
    index = 0
    while index < len(ddl_scan):
        character = ddl_scan[index]
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == ";" and depth == 0:
            stop = index + 1
            spans.append((start, stop))
            start = stop
        index += 1
    if start < len(ddl_scan):
        remaining = ddl_scan[start:].strip()
        if remaining and remaining != ";":
            _fail("W2_ALEMBIC_UNTERMINATED_STATEMENT: " + remaining[:80])
    return spans


def _top_level_sql_statements(ddl_scan: str) -> tuple[str, ...]:
    return tuple(
        ddl_scan[start:stop].strip()
        for start, stop in _top_level_sql_statement_spans(ddl_scan)
    )


def _parenthesized_sql_body(sql: str, marker: str) -> str:
    start = sql.find(marker)
    if start < 0:
        _fail("W2_ALEMBIC_CREATE_TABLE_MISSING")
    open_index = sql.find("(", start + len(marker))
    if open_index < 0:
        _fail("W2_ALEMBIC_CREATE_TABLE_BODY_MISSING")
    depth = 0
    quote: str | None = None
    index = open_index
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return sql[open_index + 1 : index]
        index += 1
    _fail("W2_ALEMBIC_CREATE_TABLE_BODY_UNTERMINATED")


def _top_level_clauses(body: str) -> tuple[str, ...]:
    clauses: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(body):
        character = body[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in ("'", '"'):
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            clauses.append(body[start:index].strip())
            start = index + 1
        index += 1
    clauses.append(body[start:].strip())
    return tuple(clause for clause in clauses if clause)


def _offline_w2_section(sql: str) -> str:
    marker = re.search(
        r"running\s+upgrade\s+"
        + re.escape(W2_PREV_HEAD)
        + r"\s*[-=]>\s*"
        + re.escape(W2_REVISION),
        sql,
        flags=re.IGNORECASE,
    )
    if marker is None:
        _product_absent("W2_ALEMBIC_OFFLINE_W2_SECTION_MISSING")
    return _strip_sql_comments(sql[marker.end() :]).lower()


def _verify_existing_snapshot(revision: Any) -> None:
    path = Path(revision.path).resolve()
    try:
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        path.relative_to(MIGRATIONS_ROOT.resolve())
        current = path.read_bytes().replace(b"\r\n", b"\n")
    except (OSError, ValueError) as exc:
        _fail("W2_HARNESS_MIGRATION_GRAPH_INVALID: " + type(exc).__name__)
    current_hash = hashlib.sha256(current).hexdigest()
    basis_hash = hashlib.sha256(_basis_bytes(relative_path)).hexdigest()
    if current_hash != basis_hash:
        _fail("W2_EXISTING_MIGRATION_MODIFIED: " + relative_path)


def _require_existing_chain() -> ScriptDirectory:
    script = _script_directory()
    revisions = _all_revisions(script)
    revision_by_id: dict[str, Any] = {}
    for revision in revisions:
        if type(revision.revision) is not str:
            _fail("W2_HARNESS_MIGRATION_GRAPH_INVALID: non-string revision")
        revision_by_id[revision.revision] = revision

    for revision_id, expected_down in EXISTING_CHAIN:
        revision = revision_by_id.get(revision_id)
        if revision is None:
            _fail("W2_MIGRATION_BASE_CHAIN_MISSING: " + revision_id)
        expected = () if expected_down is None else (expected_down,)
        if _down_revision_ids(revision.down_revision) != expected:
            _fail("W2_MIGRATION_BASE_CHAIN_INVALID: " + revision_id)
        _verify_existing_snapshot(revision)
    return script


def _require_w2_revision() -> tuple[ScriptDirectory, Any, Path]:
    script = _require_existing_chain()
    revisions = _all_revisions(script)
    existing_ids = {revision_id for revision_id, _ in EXISTING_CHAIN}
    children = [
        revision
        for revision in revisions
        if W2_PREV_HEAD in _down_revision_ids(revision.down_revision)
        and revision.revision not in existing_ids
    ]
    if not children:
        _product_absent(
            "W2_MIGRATION_MISSING: exactly one direct child of "
            + W2_PREV_HEAD
            + " is required ("
            + W2_REVISION
            + ")"
        )
    if len(children) != 1:
        _fail("W2_MIGRATION_GRAPH_INVALID: more than one direct W2_PREV_HEAD child")

    revision = children[0]
    if revision.revision != W2_REVISION:
        _fail(
            "W2_MIGRATION_REVISION_ID_MISMATCH: expected "
            + W2_REVISION
            + " got "
            + str(revision.revision)
        )
    if _down_revision_ids(revision.down_revision) != (W2_PREV_HEAD,):
        _fail("W2_MIGRATION_GRAPH_INVALID: W2 is not a direct child of " + W2_PREV_HEAD)

    migration_path = MIGRATIONS_ROOT / W2_MIGRATION_FILE
    if not migration_path.is_file():
        _product_absent("W2_MIGRATION_FILE_MISSING: " + W2_MIGRATION_FILE)
    if Path(revision.path).resolve() != migration_path.resolve():
        _fail("W2_MIGRATION_FILE_MISMATCH: revision path is not the sealed filename")

    try:
        heads = tuple(script.get_heads())
    except (CommandError, KeyError, OSError) as exc:
        _fail("W2_HARNESS_MIGRATION_GRAPH_MISSING: heads " + type(exc).__name__)
    if len(heads) != 1:
        _fail("W2_MIGRATION_SINGLE_HEAD_MISSING: sole head must be " + W2_REVISION)
    try:
        head_ancestry = {
            str(item.revision) for item in script.iterate_revisions(heads[0], "base")
        }
    except (CommandError, KeyError, OSError) as exc:
        _fail("W2_HARNESS_MIGRATION_GRAPH_MISSING: head ancestry " + type(exc).__name__)
    if W2_REVISION not in head_ancestry:
        _fail("W2_MIGRATION_SINGLE_HEAD_MISSING: sole head must be " + W2_REVISION)
    return script, revision, migration_path


# ---------------------------------------------------------------------------
# Harness self-check
# ---------------------------------------------------------------------------


def test_w2_svc_plan_notice_00_harness_existing_chain_self_check() -> None:
    """The sealed 0001--0017 graph and migration bytes are the harness basis."""
    _require_existing_chain()


def test_w2_svc_plan_notice_01_direct_child_revision_is_fixed() -> None:
    """Product RED: the exact 0018 direct child of 0017 must exist.

    Since the W2 migration file does not exist yet (Phase 1 RED-only),
    this test MUST fail with W2_PRODUCT_ABSENT.
    """
    _require_w2_revision()


def test_w2_svc_plan_notice_02_offline_sql_contract() -> None:
    """No-connect Alembic SQL must contain the included DB/guard contract.

    Verifies column set, types, nullability, constraints, function targets,
    trigger targets, and permissions. Explicitly asserts that
    recipient_certification_period_id is NOT present (§2-4 결정 회귀 방지).
    """
    _require_w2_revision()
    synthetic_env = {
        **os.environ,
        "SSWCENTER_DATABASE_URL": (
            "postgresql+psycopg://test_red:test_red@127.0.0.1:5432/sswcenter_w2_red"
        ),
        "SSWCENTER_ENVIRONMENT": "development",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", W2_REVISION, "--sql"],
            cwd=BACKEND_ROOT,
            env=synthetic_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail("W2_HARNESS_OFFLINE_SQL_MISSING: " + type(exc).__name__)
    if result.returncode != 0:
        _fail("W2_ALEMBIC_OFFLINE_SQL_FAILED: exit " + str(result.returncode))

    output = result.stdout
    section = _offline_w2_section(output)
    ddl_scan = _mask_sql_literals(section, dollar_quoted=True)
    plpgsql_scan = _mask_sql_literals(section, dollar_quoted=False)

    if '"' in ddl_scan:
        _fail("W2_ALEMBIC_QUOTED_IDENTIFIER_FORBIDDEN")
    if re.search(r"\bexecute\s+(?!function\b)", plpgsql_scan):
        _fail("W2_ALEMBIC_DYNAMIC_SQL_FORBIDDEN")

    allowed_statement_patterns = (
        r"create\s+table\s+erp\.recipient_service_plan_notice\b",
        r"create\s+(?:or\s+replace\s+)?function\s+erp\.[a-z_][a-z0-9_]*\b",
        r"create\s+(?:constraint\s+)?trigger\s+[a-z_][a-z0-9_]*\b",
        r"do\b",
        r"update\s+(?:erp\.)?alembic_version\b",
        r"commit\b",
    )
    statement_spans = _top_level_sql_statement_spans(ddl_scan)
    top_level_statements = _top_level_sql_statements(ddl_scan)
    raw_top_level_statements = tuple(
        section[start:stop].strip() for start, stop in statement_spans
    )
    unexpected_statements = [
        re.sub(r"\s+", " ", statement)[:120]
        for statement in top_level_statements
        if not any(re.match(pattern, statement) for pattern in allowed_statement_patterns)
    ]
    if unexpected_statements:
        _fail("W2_ALEMBIC_SCOPE_STATEMENT: " + repr(unexpected_statements))

    normalized_statements = tuple(
        re.sub(r"\s+", " ", statement).strip() for statement in top_level_statements
    )

    # Verify DO block (permissions)
    do_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"do\b", statement)
    )
    if len(do_indexes) != 1 or re.fullmatch(r"do\s*;?", normalized_statements[do_indexes[0]]) is None:
        _fail(
            "W2_ALEMBIC_DO_STATEMENT_SET: "
            + repr(tuple(normalized_statements[index] for index in do_indexes))
        )

    # Verify version update
    version_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"update\s+(?:erp\.)?alembic_version\b", statement)
    )
    if len(version_indexes) != 1:
        _fail("W2_ALEMBIC_VERSION_STATEMENT_COUNT: " + str(len(version_indexes)))
    expected_version_update = re.compile(
        r"update\s+erp\.alembic_version\s+set\s+version_num\s*=\s*'"
        + re.escape(W2_REVISION)
        + r"'\s+where\s+erp\.alembic_version\.version_num\s*=\s*'"
        + re.escape(W2_PREV_HEAD)
        + r"'\s*;"
    )
    if expected_version_update.fullmatch(raw_top_level_statements[version_indexes[0]]) is None:
        _fail("W2_ALEMBIC_VERSION_STATEMENT_MISMATCH")

    # Verify commit
    commit_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"commit\b", statement)
    )
    if (
        len(commit_indexes) != 1
        or re.fullmatch(r"commit\s*;?", normalized_statements[commit_indexes[0]]) is None
        or re.fullmatch(r"commit\s*;", raw_top_level_statements[commit_indexes[0]]) is None
    ):
        _fail(
            "W2_ALEMBIC_COMMIT_STATEMENT_SET: "
            + repr(tuple(normalized_statements[index] for index in commit_indexes))
        )

    # Verify function blocks
    function_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"create\s+(?:or\s+replace\s+)?function\b", statement)
    )
    function_pattern = re.compile(
        r"create\s+(?:or\s+replace\s+)?function\s+"
        r"(?P<name>[a-z_][a-z0-9_.]*)\s*\(\s*\)"
        r"(?P<header>[^'$]*?)(?P<tag>\$(?:[a-z_][a-z0-9_]*)?\$)"
        r"(?P<body>.*?)(?P=tag)(?P<trailer>[^'$]*?)\s*;",
        flags=re.DOTALL,
    )
    function_blocks: list[re.Match[str]] = []
    for index in function_indexes:
        match = function_pattern.fullmatch(raw_top_level_statements[index])
        if match is None:
            _fail(
                "W2_ALEMBIC_FUNCTION_BODY_BINDING_MISMATCH: "
                + normalized_statements[index][:120]
            )
        signature = re.sub(
            r"\s+", " ", (match.group("header") + " " + match.group("trailer")).strip()
        )
        if (
            re.search(r"\breturns\s+trigger\b", signature) is None
            or re.search(r"\blanguage\s+plpgsql\b", signature) is None
            or re.search(r"\bas\s*$", match.group("header").strip()) is None
        ):
            _fail("W2_ALEMBIC_FUNCTION_SIGNATURE_MISMATCH: " + match.group("name"))
        function_blocks.append(match)
    function_block_names = [match.group("name") for match in function_blocks]
    if set(function_block_names) != W2_FUNCTION_TARGETS or any(
        function_block_names.count(target) != 1 for target in W2_FUNCTION_TARGETS
    ):
        _fail("W2_ALEMBIC_FUNCTION_BODY_BINDING_MISMATCH: " + repr(function_block_names))
    for match in function_blocks:
        body_scan = _mask_sql_literals(match.group("body"), dollar_quoted=False)
        side_effect = re.search(
            r"\b(?:execute|insert|update|delete|merge"
            r"|alter|create|drop|truncate|"
            r"grant|revoke|call)\b",
            body_scan,
        )
        if side_effect is not None:
            _fail(
                "W2_ALEMBIC_GUARD_SIDE_EFFECT_FORBIDDEN: "
                + match.group("name")
                + ":"
                + side_effect.group(0)
            )

    # Verify permission block
    permission_block = re.fullmatch(
        r"do\s+(?P<tag>\$(?:[a-z_][a-z0-9_]*)?\$)"
        r"(?P<body>.*?)(?P=tag)\s*;",
        raw_top_level_statements[do_indexes[0]],
        flags=re.DOTALL,
    )
    if permission_block is None:
        _fail("W2_ALEMBIC_PERMISSION_BLOCK_BINDING_MISMATCH")
    permission_body = re.sub(
        r"\s+", "", permission_block.group("body").lower()
    ).removesuffix(";")
    expected_permission_body = (
        "begin"
        "ifexists(select1frompg_roleswhererolname='erp_app')then"
        "grantusageonschemaerptoerp_app;"
        "grantselect,insert,updateontableerp.recipient_service_plan_noticetoerp_app;"
        "revokedelete,truncateontableerp.recipient_service_plan_noticefromerp_app;"
        "grantusage,selectonsequenceerp.recipient_service_plan_notice_id_seqtoerp_app;"
        "endif;"
        "ifexists(select1frompg_roleswhererolname='erp_backup')then"
        "grantusageonschemaerptoerp_backup;"
        "grantselectontableerp.recipient_service_plan_noticetoerp_backup;"
        "revokeinsert,update,delete,truncateontableerp.recipient_service_plan_noticefromerp_backup;"
        "grantselectonsequenceerp.recipient_service_plan_notice_id_seqtoerp_backup;"
        "revokeusageonsequenceerp.recipient_service_plan_notice_id_seqfromerp_backup;"
        "endif;end"
    )
    if permission_body != expected_permission_body:
        _fail("W2_ALEMBIC_PERMISSION_BLOCK_MISMATCH")

    # Verify table
    table_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"create\s+table\b", statement)
    )
    if len(table_indexes) != 1:
        _fail("W2_ALEMBIC_SCOPE_TABLE_COUNT: " + str(len(table_indexes)))
    table_targets = re.findall(
        r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.]*)",
        ddl_scan,
    )
    if table_targets != ["erp.recipient_service_plan_notice"]:
        _fail("W2_ALEMBIC_SCOPE_TABLE_TARGETS: " + repr(table_targets))
    create_kinds = re.findall(
        r"\bcreate\s+(?:or\s+replace\s+)?(?:constraint\s+)?([a-z_]+)",
        ddl_scan,
    )
    unexpected_create_kinds = sorted(set(create_kinds) - {"table", "function", "trigger"})
    if unexpected_create_kinds:
        _fail("W2_ALEMBIC_SCOPE_CREATE_KIND: " + ",".join(unexpected_create_kinds))

    table_body = _parenthesized_sql_body(
        raw_top_level_statements[table_indexes[0]],
        "create table erp.recipient_service_plan_notice",
    )
    table_clauses = _top_level_clauses(table_body)
    column_clauses: dict[str, str] = {}
    constraint_clauses: dict[str, str] = {}
    for clause in table_clauses:
        lowered = clause.lower()
        named_constraint = re.match(r"constraint\s+([a-z_][a-z0-9_]*)\b", lowered)
        if named_constraint is not None:
            constraint_name = named_constraint.group(1)
            if constraint_name in constraint_clauses:
                _fail("W2_ALEMBIC_DUPLICATE_CONSTRAINT: " + constraint_name)
            constraint_clauses[constraint_name] = clause
            continue
        if lowered.startswith(("primary key", "foreign key", "check ", "exclude ", "unique ")):
            _fail("W2_ALEMBIC_UNNAMED_CONSTRAINT: " + clause)
        parts = clause.split(None, 1)
        if len(parts) != 2:
            _fail("W2_ALEMBIC_COLUMN_CLAUSE_INVALID: " + clause)
        column_name = parts[0].lower()
        if column_name in column_clauses:
            _fail("W2_ALEMBIC_DUPLICATE_COLUMN_CLAUSE: " + column_name)
        column_clauses[column_name] = clause

    # Column set verification (§6 DB-free item 2)
    if tuple(column_clauses) != W2_COLUMNS:
        _fail("W2_ALEMBIC_COLUMN_SET_OR_ORDER: " + repr(tuple(column_clauses)))

    # recipient_certification_period_id MUST NOT exist (§2-4)
    for forbidden in W2_FORBIDDEN_COLUMNS:
        if forbidden in column_clauses:
            _fail(
                "W2_ALEMBIC_FORBIDDEN_COLUMN_PRESENT: "
                + forbidden
                + " must not exist (§2-4 결정)"
            )

    if set(constraint_clauses) != W2_CONSTRAINT_NAMES:
        _fail("W2_ALEMBIC_CONSTRAINT_SET_MISMATCH: " + repr(tuple(constraint_clauses)))

    compact_constraints = {
        name: re.sub(r"\s+", "", clause.lower()).replace("::text", "")
        for name, clause in constraint_clauses.items()
    }
    expected_constraint_clauses = {
        "pk_recipient_service_plan_notice": (
            "constraintpk_recipient_service_plan_noticeprimarykey(id)"
        ),
        "fk_service_plan_notice_recipient_contract": (
            "constraintfk_service_plan_notice_recipient_contract"
            "foreignkey(recipient_contract_id)"
            "referenceserp.recipient_contract(id)ondeleterestrict"
        ),
        "fk_service_plan_notice_replacement": (
            "constraintfk_service_plan_notice_replacement"
            "foreignkey(replacement_service_plan_notice_id)"
            "referenceserp.recipient_service_plan_notice(id)"
            "ondeleterestrictdeferrableinitiallydeferred"
        ),
        "fk_service_plan_notice_created_by_account": (
            "constraintfk_service_plan_notice_created_by_account"
            "foreignkey(created_by_account_id)"
            "referenceserp.user_account(id)ondeleterestrict"
        ),
        "fk_service_plan_notice_updated_by_account": (
            "constraintfk_service_plan_notice_updated_by_account"
            "foreignkey(updated_by_account_id)"
            "referenceserp.user_account(id)ondeleterestrict"
        ),
        "ck_service_plan_notice_date_order": (
            "constraintck_service_plan_notice_date_order"
            "check(applied_end_date>=applied_start_date)"
        ),
        "ck_service_plan_notice_row_version_positive": (
            "constraintck_service_plan_notice_row_version_positive"
            "check(row_version>0)"
        ),
    }
    for name, expected in expected_constraint_clauses.items():
        if compact_constraints[name] != expected:
            _fail(
                "W2_ALEMBIC_CONSTRAINT_CLAUSE_MISMATCH: "
                + name
                + ":"
                + repr(compact_constraints[name])
            )

    compact_columns = {
        name: re.sub(r"\s+", "", clause.lower()).replace("::text", "")
        for name, clause in column_clauses.items()
    }
    expected_column_clauses = {
        "id": {"idbigintgeneratedbydefaultasidentitynotnull"},
        "recipient_contract_id": {"recipient_contract_idbigintnotnull"},
        "notification_date": {"notification_datedatenotnull"},
        "applied_start_date": {"applied_start_datedatenotnull"},
        "applied_end_date": {"applied_end_datedatenotnull"},
        "invalidated_at_utc": {"invalidated_at_utctimestampwithtimezone"},
        "replacement_service_plan_notice_id": {"replacement_service_plan_notice_idbigint"},
        "created_by_account_id": {"created_by_account_idbigintnotnull"},
        "created_at_utc": {"created_at_utctimestampwithtimezonedefaultnow()notnull"},
        "updated_by_account_id": {"updated_by_account_idbigintnotnull"},
        "updated_at_utc": {"updated_at_utctimestampwithtimezonedefaultnow()notnull"},
        "row_version": {"row_versionintegerdefault1notnull"},
    }
    for name, expected in expected_column_clauses.items():
        if compact_columns[name] not in expected:
            _fail(
                "W2_ALEMBIC_COLUMN_CLAUSE_MISMATCH: "
                + name
                + ":"
                + repr(compact_columns[name])
            )

    # Verify function and trigger targets
    function_targets = re.findall(
        r"\bcreate\s+(?:or\s+replace\s+)?function\s+([a-z_][a-z0-9_.]*)\s*\(",
        ddl_scan,
    )
    if set(function_targets) != W2_FUNCTION_TARGETS or any(
        function_targets.count(target) != 1 for target in W2_FUNCTION_TARGETS
    ):
        _fail("W2_ALEMBIC_SCOPE_FUNCTION_TARGETS: " + repr(function_targets))

    trigger_targets = re.findall(
        r"\bcreate\s+(?:constraint\s+)?trigger\s+([a-z_][a-z0-9_]*)\b",
        ddl_scan,
    )
    if set(trigger_targets) != W2_TRIGGER_TARGETS or any(
        trigger_targets.count(target) != 1 for target in W2_TRIGGER_TARGETS
    ):
        _fail("W2_ALEMBIC_SCOPE_TRIGGER_TARGETS: " + repr(trigger_targets))

    # Required fragments (§6 DB-free item 2 regression anchors)
    required_fragments = (
        "create table erp.recipient_service_plan_notice",
        "recipient_contract_id",
        "notification_date",
        "applied_start_date",
        "applied_end_date",
        "replacement_service_plan_notice_id",
        "invalidated_at_utc",
        "row_version",
        "fn_service_plan_notice_within_contract",
        "fn_service_plan_notice_within_certification",
        "fn_service_plan_notice_before_contract_start",
        "fn_recipient_contract_service_plan_reverse_guard",
        "fn_recipient_certification_period_service_plan_reverse_guard",
        "fn_recipient_contract_recipient_id_immutable",
        "fn_recipient_certification_period_recipient_id_immutable",
        "ck_service_plan_notice_date_order",
        "ck_service_plan_notice_row_version_positive",
    )
    for fragment in required_fragments:
        if fragment.lower() not in section:
            _fail("W2_ALEMBIC_OFFLINE_CONTRACT_MISSING: " + fragment)

    # Forbidden fragment: recipient_certification_period_id MUST NOT appear (§2-4)
    if "recipient_certification_period_id" in section.lower():
        _fail(
            "W2_ALEMBIC_FORBIDDEN_FRAGMENT_PRESENT: "
            "recipient_certification_period_id must not appear (§2-4 결정)"
        )

    compact_section = re.sub(r"\s+", "", section)
    for fragment in (
        "foreignkey(recipient_contract_id)referenceserp.recipient_contract(id)ondeleterestrict",
        "foreignkey(replacement_service_plan_notice_id)"
        "referenceserp.recipient_service_plan_notice(id)"
        "ondeleterestrictdeferrableinitiallydeferred",
        "foreignkey(created_by_account_id)referenceserp.user_account(id)ondeleterestrict",
        "foreignkey(updated_by_account_id)referenceserp.user_account(id)ondeleterestrict",
        "check(applied_end_date>=applied_start_date)",
        "check(row_version>0)",
    ):
        if fragment not in compact_section:
            _fail("W2_ALEMBIC_FOREIGN_KEY_CONTRACT_MISSING: " + fragment)

    # Forbidden scope patterns — W2 must not leak Wave 3+ concerns
    forbidden_scope_patterns = (
        (
            "W2_STAFF_SCHEDULE",
            r"\b(?:staff_schedule|monthly_schedule|employee_schedule|schedule_period)"
            r"(?:_|$)",
        ),
        (
            "W2_WORK_CARD_ENGINE",
            r"\b(?:work_card|upmu_card|task_card|d100|d45|complete|incomplete"
            r"|exempt|waiting|status_transition)\b",
        ),
        (
            "W2_DETERMINED_MONTH",
            r"\b(?:determined_month|confirmed_month|확정월)\b",
        ),
        (
            "W2_STAFF_REPLACEMENT",
            r"\b(?:staff_replacement|assignment_swap|교체)\b",
        ),
        (
            "BILLING",
            r"\b(?:billing|invoice|claim|payment|charge)(?:_|$)",
        ),
    )
    for family, pattern in forbidden_scope_patterns:
        match = re.search(pattern, section, flags=re.IGNORECASE)
        if match is not None:
            _fail("W2_ALEMBIC_OFFLINE_SCOPE_BREACH: " + family + ":" + match.group(0))


def test_w2_svc_plan_notice_03_orm_contract_is_exact() -> None:
    """Product RED: ORM shape must match the migration contract when present.

    Explicitly verifies recipient_certification_period_id is NOT present
    (§2-4 결정 회귀 방지, §6 DB-free item 2).
    """
    try:
        from app.db import models
    except ImportError as exc:
        _fail("W2_HARNESS_MODELS_IMPORT_MISSING: " + type(exc).__name__)

    model = getattr(models, "RecipientServicePlanNotice", None)
    if model is None:
        _product_absent("W2_ORM_MODEL_MISSING: RecipientServicePlanNotice")
    table = getattr(model, "__table__", None)
    if table is None:
        _product_absent("W2_ORM_TABLE_MISSING: RecipientServicePlanNotice.__table__")
    if table.name != "recipient_service_plan_notice" or table.schema != "erp":
        _fail("W2_ORM_TABLE_IDENTITY_MISMATCH: " + repr((table.schema, table.name)))

    columns = {column.name: column for column in table.columns}
    if tuple(columns) != W2_COLUMNS:
        _fail("W2_ORM_COLUMN_SET_OR_ORDER: " + repr(tuple(columns)))

    # recipient_certification_period_id MUST NOT exist (§2-4)
    for forbidden in W2_FORBIDDEN_COLUMNS:
        if forbidden in columns:
            _fail(
                "W2_ORM_FORBIDDEN_COLUMN_PRESENT: "
                + forbidden
                + " must not exist (§2-4 결정)"
            )

    expected_types = {
        "id": BigInteger,
        "recipient_contract_id": BigInteger,
        "notification_date": Date,
        "applied_start_date": Date,
        "applied_end_date": Date,
        "invalidated_at_utc": DateTime,
        "replacement_service_plan_notice_id": BigInteger,
        "created_by_account_id": BigInteger,
        "created_at_utc": DateTime,
        "updated_by_account_id": BigInteger,
        "updated_at_utc": DateTime,
        "row_version": Integer,
    }
    nullable_columns = {
        "invalidated_at_utc",
        "replacement_service_plan_notice_id",
    }
    for name, expected_type in expected_types.items():
        column = columns[name]
        if type(column.type) is not expected_type:
            _fail("W2_ORM_COLUMN_TYPE_MISMATCH: " + name)
        if column.nullable is not (name in nullable_columns):
            _fail("W2_ORM_COLUMN_NULLABILITY_MISMATCH: " + name)
    for name in ("created_at_utc", "updated_at_utc", "invalidated_at_utc"):
        if columns[name].type.timezone is not True:
            _fail("W2_ORM_TIMESTAMP_TIMEZONE_MISMATCH: " + name)
    identity = columns["id"].identity
    if identity is None:
        _fail("W2_ORM_IDENTITY_MISSING")

    # Verify constraints
    table_constraints = {c.name: c for c in table.constraints if c.name is not None}
    if set(table_constraints) != W2_CONSTRAINT_NAMES:
        _fail("W2_ORM_CONSTRAINT_SET_MISMATCH: " + repr(tuple(table_constraints)))

    pk = table_constraints["pk_recipient_service_plan_notice"]
    if type(pk) is not PrimaryKeyConstraint or tuple(c.name for c in pk.columns) != ("id",):
        _fail("W2_ORM_PK_MISMATCH")

    fk_contract = table_constraints["fk_service_plan_notice_recipient_contract"]
    if type(fk_contract) is not ForeignKeyConstraint:
        _fail("W2_ORM_FK_CONTRACT_TYPE_MISMATCH")
    if tuple(c.name for c in fk_contract.columns) != ("recipient_contract_id",):
        _fail("W2_ORM_FK_CONTRACT_COLUMNS_MISMATCH")
    if fk_contract.elements[0].column.table.name != "recipient_contract":
        _fail("W2_ORM_FK_CONTRACT_TARGET_MISMATCH")
    if fk_contract.ondelete != "RESTRICT":
        _fail("W2_ORM_FK_CONTRACT_DELETE_ACTION_MISMATCH")

    ck_date = table_constraints["ck_service_plan_notice_date_order"]
    if type(ck_date) is not CheckConstraint:
        _fail("W2_ORM_CK_DATE_TYPE_MISMATCH")

    ck_rv = table_constraints["ck_service_plan_notice_row_version_positive"]
    if type(ck_rv) is not CheckConstraint:
        _fail("W2_ORM_CK_RV_TYPE_MISMATCH")
