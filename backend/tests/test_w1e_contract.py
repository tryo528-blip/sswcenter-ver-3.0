"""W1E-A1 Phase 1 RED: GENERAL care-assignment DB/contract package.

The product migration/model are intentionally absent at this phase. Harness
checks must pass independently; missing product bytes must fail
with stable W1E markers rather than being softened into a pass.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

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

BASIS_SHA = "1314b4ce41de5dd55f4996b409a52ed7e24bfbca"
W1D_HEAD = "20260730_0011_w1d_recipient_contract"
W1E_REVISION = "20260801_0012_w1e_care_assignment"
W1E_MIGRATION_FILE = "20260801_0012_w1e_care_assignment.py"

W1E_COLUMNS = (
    "id",
    "recipient_contract_id",
    "staff_id",
    "employment_id",
    "assignment_kind",
    "family_relationship_text",
    "start_date",
    "end_date",
    "assignment_period",
    "invalidated_at_utc",
    "replacement_assignment_id",
    "created_by_account_id",
    "created_at_utc",
    "updated_by_account_id",
    "updated_at_utc",
    "row_version",
)
W1E_CONSTRAINT_NAMES = frozenset(
    {
        "pk_care_assignment",
        "fk_care_assignment_recipient_contract",
        "fk_care_assignment_employment",
        "fk_care_assignment_replacement",
        "fk_care_assignment_created_by_account",
        "fk_care_assignment_updated_by_account",
        "ck_care_assignment_kind",
        "ck_care_assignment_date_order",
        "ck_care_assignment_row_version_positive",
        "ex_care_assignment_same_contract_staff_period",
    }
)

W1E_FUNCTION_TARGETS = frozenset(
    {
        "erp.fn_care_assignment_within_contract",
        "erp.fn_care_assignment_within_employment",
        "erp.fn_care_assignment_within_position",
        "erp.fn_care_assignment_general_care_qualified",
        "erp.fn_recipient_contract_assignment_reverse_guard",
        "erp.fn_staff_employment_child_periods_reverse_guard",
        "erp.fn_staff_position_care_assignment_reverse_guard",
        "erp.fn_staff_service_qualification_assignment_reverse_guard",
    }
)
W1E_TRIGGER_TARGETS = frozenset(
    {
        "ct_care_assignment_within_contract",
        "ct_care_assignment_within_employment",
        "ct_care_assignment_within_position",
        "ct_care_assignment_general_care_qualified",
        "ct_recipient_contract_assignment_reverse_guard",
        "ct_staff_position_care_assignment_reverse_guard",
        "ct_staff_service_qualification_assignment_reverse_guard",
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
    (W1D_HEAD, "20260730_0010_w1c_certification_ledgers"),
)


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _product_absent(marker: str) -> NoReturn:
    _fail("W1E_PRODUCT_ABSENT: " + marker)


def _down_revision_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        values: tuple[object, ...] = tuple(value)
        if not all(type(item) is str for item in values):
            _fail("W1E_HARNESS_MIGRATION_GRAPH_INVALID: non-string down_revision")
        return cast(tuple[str, ...], values)
    _fail("W1E_HARNESS_MIGRATION_GRAPH_INVALID: unsupported down_revision type")


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ALEMBIC_ROOT))
    try:
        return ScriptDirectory.from_config(config)
    except (CommandError, KeyError, OSError) as exc:
        _fail("W1E_HARNESS_MIGRATION_GRAPH_MISSING: " + type(exc).__name__)


def _all_revisions(script: ScriptDirectory) -> list[Any]:
    try:
        revisions = list(script.walk_revisions())
    except (CommandError, KeyError, OSError) as exc:
        _fail("W1E_HARNESS_MIGRATION_GRAPH_MISSING: " + type(exc).__name__)
    return revisions


def _basis_bytes(relative_path: str) -> bytes:
    current_path = REPO_ROOT / relative_path
    if current_path.is_file():
        return current_path.read_bytes().replace(b"\r\n", b"\n")
    try:
        result = subprocess.run(
            ["git", "show", f"{BASIS_SHA}:{relative_path}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail("W1E_HARNESS_BASIS_MISSING: " + type(exc).__name__)
    if result.returncode != 0:
        _fail("W1E_HARNESS_BASIS_MISSING: " + relative_path)
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


def _scan_plpgsql_lexical(sql: str) -> tuple[str, str]:
    """Return (comment-stripped text, opaque-masked scan) after full validation."""
    text_pieces: list[str] = []
    scan_pieces: list[str] = []
    index = 0
    quote_labels = {
        "string": "single-quoted string",
        "escape_string": "escape string",
        "quoted_identifier": "quoted identifier",
    }
    while index < len(sql):
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            comment_stop = len(sql) if newline < 0 else newline
            masked = _masked_sql_fragment(sql[index:comment_stop])
            text_pieces.append(masked)
            scan_pieces.append(masked)
            index = comment_stop
            continue
        if sql.startswith("/*", index):
            block_stop = _sql_block_comment_stop(sql, index)
            if block_stop is None:
                raise _UnsupportedPlpgsql("unterminated block comment")
            masked = _masked_sql_fragment(sql[index:block_stop])
            text_pieces.append(masked)
            scan_pieces.append(masked)
            index = block_stop
            continue
        quoted = _sql_quoted_span(sql, index)
        if quoted is not None:
            kind, quoted_stop = quoted
            if quoted_stop is None:
                raise _UnsupportedPlpgsql("unterminated " + quote_labels[kind])
            text_pieces.append(sql[index:quoted_stop])
            scan_pieces.append(_masked_sql_fragment(sql[index:quoted_stop]))
            index = quoted_stop
            continue
        if sql[index] == "$":
            dollar = _sql_dollar_span(sql, index)
            if dollar is not None:
                _, dollar_stop = dollar
                if dollar_stop is None:
                    raise _UnsupportedPlpgsql("unterminated dollar-quoted string")
                text_pieces.append(sql[index:dollar_stop])
                scan_pieces.append(_masked_sql_fragment(sql[index:dollar_stop]))
                index = dollar_stop
                continue
        text_pieces.append(sql[index])
        scan_pieces.append(sql[index])
        index += 1
    return "".join(text_pieces), "".join(scan_pieces)


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


def _top_level_sql_statement_spans(sql: str) -> tuple[tuple[int, int], ...]:
    """Locate statements after all non-top-level semicolons have been masked."""
    spans: list[tuple[int, int]] = []
    start = 0
    for index, character in enumerate(sql):
        if character != ";":
            continue
        if sql[start:index].strip():
            spans.append((start, index + 1))
        start = index + 1
    if sql[start:].strip():
        spans.append((start, len(sql)))
    return tuple(spans)


def _top_level_sql_statements(sql: str) -> tuple[str, ...]:
    """Split SQL whose string and dollar-quoted bodies have already been masked."""
    statements: list[str] = []
    for start, stop in _top_level_sql_statement_spans(sql):
        statement = sql[start:stop]
        if statement.endswith(";"):
            statement = statement[:-1]
        statements.append(statement.strip())
    return tuple(statements)


def _compact_expression(value: str) -> str:
    compact = re.sub(r"\s+", "", value.lower()).replace("::text", "")
    while compact.startswith("(") and compact.endswith(")"):
        depth = 0
        wraps_whole_expression = True
        for index, character in enumerate(compact):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(compact) - 1:
                    wraps_whole_expression = False
                    break
        if not wraps_whole_expression or depth != 0:
            break
        compact = compact[1:-1]
    return compact


def _parenthesized_sql_body(sql: str, marker: str) -> str:
    start = sql.find(marker)
    if start < 0:
        _fail("W1E_ALEMBIC_CREATE_TABLE_MISSING")
    open_index = sql.find("(", start + len(marker))
    if open_index < 0:
        _fail("W1E_ALEMBIC_CREATE_TABLE_BODY_MISSING")
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
    _fail("W1E_ALEMBIC_CREATE_TABLE_BODY_UNTERMINATED")


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


def _offline_w1e_section(sql: str) -> str:
    marker = re.search(
        r"running\s+upgrade\s+" + re.escape(W1D_HEAD) + r"\s*[-=]>\s*" + re.escape(W1E_REVISION),
        sql,
        flags=re.IGNORECASE,
    )
    if marker is None:
        _fail("W1E_ALEMBIC_OFFLINE_W1E_SECTION_MISSING")
    return _strip_sql_comments(sql[marker.end() :]).lower()


def _verify_existing_snapshot(revision: Any) -> None:
    path = Path(revision.path).resolve()
    try:
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        path.relative_to(MIGRATIONS_ROOT.resolve())
        current = path.read_bytes().replace(b"\r\n", b"\n")
    except (OSError, ValueError) as exc:
        _fail("W1E_HARNESS_MIGRATION_GRAPH_INVALID: " + type(exc).__name__)
    current_hash = hashlib.sha256(current).hexdigest()
    basis_hash = hashlib.sha256(_basis_bytes(relative_path)).hexdigest()
    if current_hash != basis_hash:
        _fail("W1E_EXISTING_MIGRATION_MODIFIED: " + relative_path)


def _require_existing_chain() -> ScriptDirectory:
    script = _script_directory()
    revisions = _all_revisions(script)
    revision_by_id: dict[str, Any] = {}
    for revision in revisions:
        if type(revision.revision) is not str:
            _fail("W1E_HARNESS_MIGRATION_GRAPH_INVALID: non-string revision")
        revision_by_id[revision.revision] = revision

    for revision_id, expected_down in EXISTING_CHAIN:
        revision = revision_by_id.get(revision_id)
        if revision is None:
            _fail("W1E_MIGRATION_BASE_CHAIN_MISSING: " + revision_id)
        expected = () if expected_down is None else (expected_down,)
        if _down_revision_ids(revision.down_revision) != expected:
            _fail("W1E_MIGRATION_BASE_CHAIN_INVALID: " + revision_id)
        _verify_existing_snapshot(revision)
    return script


def _require_w1e_revision() -> tuple[ScriptDirectory, Any, Path]:
    script = _require_existing_chain()
    revisions = _all_revisions(script)
    existing_ids = {revision_id for revision_id, _ in EXISTING_CHAIN}
    children = [
        revision
        for revision in revisions
        if W1D_HEAD in _down_revision_ids(revision.down_revision)
        and revision.revision not in existing_ids
    ]
    if not children:
        _product_absent(
            "W1E_MIGRATION_MISSING: exactly one direct child of "
            + W1D_HEAD
            + " is required ("
            + W1E_REVISION
            + ")"
        )
    if len(children) != 1:
        _fail("W1E_MIGRATION_GRAPH_INVALID: more than one direct W1D child")

    revision = children[0]
    if revision.revision != W1E_REVISION:
        _fail(
            "W1E_MIGRATION_REVISION_ID_MISMATCH: expected "
            + W1E_REVISION
            + " got "
            + str(revision.revision)
        )
    if _down_revision_ids(revision.down_revision) != (W1D_HEAD,):
        _fail("W1E_MIGRATION_GRAPH_INVALID: W1E is not a direct W1D child")

    migration_path = MIGRATIONS_ROOT / W1E_MIGRATION_FILE
    if not migration_path.is_file():
        _product_absent("W1E_MIGRATION_FILE_MISSING: " + W1E_MIGRATION_FILE)
    if Path(revision.path).resolve() != migration_path.resolve():
        _fail("W1E_MIGRATION_FILE_MISMATCH: revision path is not the sealed filename")

    try:
        heads = tuple(script.get_heads())
    except (CommandError, KeyError, OSError) as exc:
        _fail("W1E_HARNESS_MIGRATION_GRAPH_MISSING: heads " + type(exc).__name__)
    if len(heads) != 1:
        _fail("W1E_MIGRATION_SINGLE_HEAD_MISSING: sole head must be " + W1E_REVISION)
    # The sole head must be the tested revision or one of its descendants on the
    # single linear chain that continues past W1E. Ancestry is resolved through
    # the Alembic ScriptDirectory API: iterate_revisions(head, "base") yields the
    # head plus every ancestor, so the tested revision appears iff the head is it
    # or descends from it. A head outside that chain is rejected.
    try:
        head_ancestry = {str(item.revision) for item in script.iterate_revisions(heads[0], "base")}
    except (CommandError, KeyError, OSError) as exc:
        _fail("W1E_HARNESS_MIGRATION_GRAPH_MISSING: head ancestry " + type(exc).__name__)
    if W1E_REVISION not in head_ancestry:
        _fail("W1E_MIGRATION_SINGLE_HEAD_MISSING: sole head must be " + W1E_REVISION)
    return script, revision, migration_path


def test_w1e_00_harness_existing_chain_self_check() -> None:
    """The sealed 0001--0011 graph and migration bytes are the harness basis."""
    _require_existing_chain()


def test_w1e_01_direct_child_revision_is_fixed() -> None:
    """Product RED: the exact 0012 direct child must exist."""
    _require_w1e_revision()


def test_w1e_02_offline_sql_declares_only_the_assignment_contract() -> None:
    """No-connect Alembic SQL must contain the included DB/guard contract only."""
    _require_w1e_revision()
    synthetic_env = {
        **os.environ,
        "SSWCENTER_DATABASE_URL": (
            "postgresql+psycopg://test_red:test_red@127.0.0.1:5432/sswcenter_w1e_red"
        ),
        "SSWCENTER_ENVIRONMENT": "development",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", W1E_REVISION, "--sql"],
            cwd=BACKEND_ROOT,
            env=synthetic_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail("W1E_HARNESS_OFFLINE_SQL_MISSING: " + type(exc).__name__)
    if result.returncode != 0:
        _fail("W1E_ALEMBIC_OFFLINE_SQL_FAILED: exit " + str(result.returncode))
    # Alembic writes SQL to stdout and informational logging to stderr. Mixing
    # those streams would turn non-SQL log records into apparent statements.
    output = result.stdout
    section = _offline_w1e_section(output)
    ddl_scan = _mask_sql_literals(section, dollar_quoted=True)
    plpgsql_scan = _mask_sql_literals(section, dollar_quoted=False)

    if '"' in ddl_scan:
        _fail("W1E_ALEMBIC_QUOTED_IDENTIFIER_FORBIDDEN")
    if re.search(r"\bexecute\s+(?!function\b)", plpgsql_scan):
        _fail("W1E_ALEMBIC_DYNAMIC_SQL_FORBIDDEN")
    allowed_statement_patterns = (
        r"create\s+table\s+erp\.care_assignment\b",
        r"create\s+(?:or\s+replace\s+)?function\s+erp\.[a-z_][a-z0-9_]*\b",
        r"create\s+(?:constraint\s+)?trigger\s+[a-z_][a-z0-9_]*\b",
        r"do\b",
        r"update\s+(?:erp\.)?alembic_version\b",
        r"commit\b",
    )
    statement_spans = _top_level_sql_statement_spans(ddl_scan)
    top_level_statements = _top_level_sql_statements(ddl_scan)
    raw_top_level_statements = tuple(section[start:stop].strip() for start, stop in statement_spans)
    unexpected_statements = [
        re.sub(r"\s+", " ", statement)[:120]
        for statement in top_level_statements
        if not any(re.match(pattern, statement) for pattern in allowed_statement_patterns)
    ]
    if unexpected_statements:
        _fail("W1E_ALEMBIC_SCOPE_STATEMENT: " + repr(unexpected_statements))

    normalized_statements = tuple(
        re.sub(r"\s+", " ", statement).strip() for statement in top_level_statements
    )
    do_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"do\b", statement)
    )
    if len(do_indexes) != 1 or normalized_statements[do_indexes[0]] != "do":
        _fail(
            "W1E_ALEMBIC_DO_STATEMENT_SET: "
            + repr(tuple(normalized_statements[index] for index in do_indexes))
        )
    version_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"update\s+(?:erp\.)?alembic_version\b", statement)
    )
    if len(version_indexes) != 1:
        _fail("W1E_ALEMBIC_VERSION_STATEMENT_COUNT: " + str(len(version_indexes)))
    expected_version_update = re.compile(
        r"update\s+erp\.alembic_version\s+set\s+version_num\s*=\s*'"
        + re.escape(W1E_REVISION)
        + r"'\s+where\s+erp\.alembic_version\.version_num\s*=\s*'"
        + re.escape(W1D_HEAD)
        + r"'\s*;"
    )
    if expected_version_update.fullmatch(raw_top_level_statements[version_indexes[0]]) is None:
        _fail("W1E_ALEMBIC_VERSION_STATEMENT_MISMATCH")
    commit_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"commit\b", statement)
    )
    if (
        len(commit_indexes) != 1
        or normalized_statements[commit_indexes[0]] != "commit"
        or re.fullmatch(r"commit\s*;", raw_top_level_statements[commit_indexes[0]]) is None
    ):
        _fail(
            "W1E_ALEMBIC_COMMIT_STATEMENT_SET: "
            + repr(tuple(normalized_statements[index] for index in commit_indexes))
        )

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
                "W1E_ALEMBIC_FUNCTION_BODY_BINDING_MISMATCH: " + normalized_statements[index][:120]
            )
        signature = re.sub(
            r"\s+", " ", (match.group("header") + " " + match.group("trailer")).strip()
        )
        if (
            re.search(r"\breturns\s+trigger\b", signature) is None
            or re.search(r"\blanguage\s+plpgsql\b", signature) is None
            or re.search(r"\bas\s*$", match.group("header").strip()) is None
        ):
            _fail("W1E_ALEMBIC_FUNCTION_SIGNATURE_MISMATCH: " + match.group("name"))
        function_blocks.append(match)
    function_block_names = [match.group("name") for match in function_blocks]
    if set(function_block_names) != W1E_FUNCTION_TARGETS or any(
        function_block_names.count(target) != 1 for target in W1E_FUNCTION_TARGETS
    ):
        _fail("W1E_ALEMBIC_FUNCTION_BODY_BINDING_MISMATCH: " + repr(function_block_names))
    for match in function_blocks:
        body_scan = _mask_sql_literals(match.group("body"), dollar_quoted=False)
        side_effect = re.search(
            r"\b(?:execute|insert|update|delete|merge|alter|create|drop|truncate|"
            r"grant|revoke|call)\b",
            body_scan,
        )
        if side_effect is not None:
            _fail(
                "W1E_ALEMBIC_GUARD_SIDE_EFFECT_FORBIDDEN: "
                + match.group("name")
                + ":"
                + side_effect.group(0)
            )

    permission_block = re.fullmatch(
        r"do\s+(?P<tag>\$(?:[a-z_][a-z0-9_]*)?\$)"
        r"(?P<body>.*?)(?P=tag)\s*;",
        raw_top_level_statements[do_indexes[0]],
        flags=re.DOTALL,
    )
    if permission_block is None:
        _fail("W1E_ALEMBIC_PERMISSION_BLOCK_BINDING_MISMATCH")
    permission_body = re.sub(r"\s+", "", permission_block.group("body").lower()).removesuffix(";")
    expected_permission_body = (
        "begin"
        "ifexists(select1frompg_roleswhererolname='erp_app')then"
        "grantusageonschemaerptoerp_app;"
        "grantselect,insert,updateontableerp.care_assignmenttoerp_app;"
        "revokedelete,truncateontableerp.care_assignmentfromerp_app;"
        "grantusage,selectonsequenceerp.care_assignment_id_seqtoerp_app;"
        "endif;"
        "ifexists(select1frompg_roleswhererolname='erp_backup')then"
        "grantusageonschemaerptoerp_backup;"
        "grantselectontableerp.care_assignmenttoerp_backup;"
        "revokeinsert,update,delete,truncateontableerp.care_assignmentfromerp_backup;"
        "grantselectonsequenceerp.care_assignment_id_seqtoerp_backup;"
        "revokeusageonsequenceerp.care_assignment_id_seqfromerp_backup;"
        "endif;end"
    )
    if permission_body != expected_permission_body:
        _fail("W1E_ALEMBIC_PERMISSION_BLOCK_MISMATCH")

    table_indexes = tuple(
        index
        for index, statement in enumerate(normalized_statements)
        if re.match(r"create\s+table\b", statement)
    )
    if len(table_indexes) != 1:
        _fail("W1E_ALEMBIC_SCOPE_TABLE_COUNT: " + str(len(table_indexes)))
    table_targets = re.findall(
        r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?([a-z_][a-z0-9_.]*)",
        ddl_scan,
    )
    if table_targets != ["erp.care_assignment"]:
        _fail("W1E_ALEMBIC_SCOPE_TABLE_TARGETS: " + repr(table_targets))
    create_kinds = re.findall(
        r"\bcreate\s+(?:or\s+replace\s+)?(?:constraint\s+)?([a-z_]+)",
        ddl_scan,
    )
    unexpected_create_kinds = sorted(set(create_kinds) - {"table", "function", "trigger"})
    if unexpected_create_kinds:
        _fail("W1E_ALEMBIC_SCOPE_CREATE_KIND: " + ",".join(unexpected_create_kinds))

    table_body = _parenthesized_sql_body(
        raw_top_level_statements[table_indexes[0]],
        "create table erp.care_assignment",
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
                _fail("W1E_ALEMBIC_DUPLICATE_CONSTRAINT: " + constraint_name)
            constraint_clauses[constraint_name] = clause
            continue
        if lowered.startswith(("primary key", "foreign key", "check ", "exclude ", "unique ")):
            _fail("W1E_ALEMBIC_UNNAMED_CONSTRAINT: " + clause)
        parts = clause.split(None, 1)
        if len(parts) != 2:
            _fail("W1E_ALEMBIC_COLUMN_CLAUSE_INVALID: " + clause)
        column_name = parts[0].lower()
        if column_name in column_clauses:
            _fail("W1E_ALEMBIC_DUPLICATE_COLUMN_CLAUSE: " + column_name)
        column_clauses[column_name] = clause
    if tuple(column_clauses) != W1E_COLUMNS:
        _fail("W1E_ALEMBIC_COLUMN_SET_OR_ORDER: " + repr(tuple(column_clauses)))
    if set(constraint_clauses) != W1E_CONSTRAINT_NAMES:
        _fail("W1E_ALEMBIC_CONSTRAINT_SET_MISMATCH: " + repr(tuple(constraint_clauses)))

    compact_constraints = {
        name: re.sub(r"\s+", "", clause.lower()).replace("::text", "")
        for name, clause in constraint_clauses.items()
    }
    expected_constraint_clauses = {
        "pk_care_assignment": "constraintpk_care_assignmentprimarykey(id)",
        "fk_care_assignment_recipient_contract": (
            "constraintfk_care_assignment_recipient_contractforeignkey("
            "recipient_contract_id)referenceserp.recipient_contract(id)ondeleterestrict"
        ),
        "fk_care_assignment_employment": (
            "constraintfk_care_assignment_employmentforeignkey(staff_id,employment_id)"
            "referenceserp.staff_employment(staff_id,id)ondeleterestrict"
        ),
        "fk_care_assignment_replacement": (
            "constraintfk_care_assignment_replacementforeignkey(replacement_assignment_id)"
            "referenceserp.care_assignment(id)ondeleterestrictdeferrableinitiallydeferred"
        ),
        "fk_care_assignment_created_by_account": (
            "constraintfk_care_assignment_created_by_accountforeignkey(created_by_account_id)"
            "referenceserp.user_account(id)ondeleterestrict"
        ),
        "fk_care_assignment_updated_by_account": (
            "constraintfk_care_assignment_updated_by_accountforeignkey(updated_by_account_id)"
            "referenceserp.user_account(id)ondeleterestrict"
        ),
        "ck_care_assignment_kind": (
            "constraintck_care_assignment_kindcheck(assignment_kindin('general','family'))"
        ),
        "ck_care_assignment_date_order": (
            "constraintck_care_assignment_date_ordercheck(end_dateisnullorstart_date<=end_date)"
        ),
        "ck_care_assignment_row_version_positive": (
            "constraintck_care_assignment_row_version_positivecheck(row_version>0)"
        ),
        "ex_care_assignment_same_contract_staff_period": (
            "constraintex_care_assignment_same_contract_staff_periodexcludeusinggist("
            "recipient_contract_idwith=,staff_idwith=,assignment_periodwith&&)"
            "where(invalidated_at_utcisnull)"
        ),
    }
    for name, expected in expected_constraint_clauses.items():
        if compact_constraints[name] != expected:
            _fail(
                "W1E_ALEMBIC_CONSTRAINT_CLAUSE_MISMATCH: "
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
        "staff_id": {"staff_idbigintnotnull"},
        "employment_id": {"employment_idbigintnotnull"},
        "assignment_kind": {"assignment_kindtextnotnull"},
        "family_relationship_text": {"family_relationship_texttext"},
        "start_date": {"start_datedatenotnull"},
        "end_date": {"end_datedate"},
        "assignment_period": {
            "assignment_perioddaterangegeneratedalwaysas("
            "daterange(start_date,end_date+1,'[)'))storednotnull",
            "assignment_perioddaterangegeneratedalwaysas("
            "daterange(start_date,(end_date+1),'[)'))storednotnull",
        },
        "invalidated_at_utc": {"invalidated_at_utctimestampwithtimezone"},
        "replacement_assignment_id": {"replacement_assignment_idbigint"},
        "created_by_account_id": {"created_by_account_idbigintnotnull"},
        "created_at_utc": {"created_at_utctimestampwithtimezonedefaultnow()notnull"},
        "updated_by_account_id": {"updated_by_account_idbigintnotnull"},
        "updated_at_utc": {"updated_at_utctimestampwithtimezonedefaultnow()notnull"},
        "row_version": {"row_versionintegerdefault1notnull"},
    }
    for name, expected_clauses in expected_column_clauses.items():
        if compact_columns[name] not in expected_clauses:
            _fail("W1E_ALEMBIC_COLUMN_CLAUSE_MISMATCH: " + name + ":" + repr(compact_columns[name]))

    function_targets = re.findall(
        r"\bcreate\s+(?:or\s+replace\s+)?function\s+([a-z_][a-z0-9_.]*)\s*\(",
        ddl_scan,
    )
    if set(function_targets) != W1E_FUNCTION_TARGETS or any(
        function_targets.count(target) != 1 for target in W1E_FUNCTION_TARGETS
    ):
        _fail("W1E_ALEMBIC_SCOPE_FUNCTION_TARGETS: " + repr(function_targets))

    trigger_targets = re.findall(
        r"\bcreate\s+(?:constraint\s+)?trigger\s+([a-z_][a-z0-9_]*)\b",
        ddl_scan,
    )
    if set(trigger_targets) != W1E_TRIGGER_TARGETS or any(
        trigger_targets.count(target) != 1 for target in W1E_TRIGGER_TARGETS
    ):
        _fail("W1E_ALEMBIC_SCOPE_TRIGGER_TARGETS: " + repr(trigger_targets))

    required_fragments = (
        "create table erp.care_assignment",
        "recipient_contract_id",
        "service_type_id",
        "assignment_kind",
        "GENERAL",
        "assignment_period",
        "staff_service_qualification_period",
        "ex_care_assignment_same_contract_staff_period",
        "fn_care_assignment_within_contract",
        "fn_care_assignment_within_employment",
        "fn_care_assignment_within_position",
        "fn_care_assignment_general_care_qualified",
        "fn_recipient_contract_assignment_reverse_guard",
        "fn_staff_employment_child_periods_reverse_guard",
        "fn_staff_position_care_assignment_reverse_guard",
        "fn_staff_service_qualification_assignment_reverse_guard",
        "replacement_assignment_id",
        "invalidated_at_utc",
        "row_version",
        "ck_care_assignment_row_version_positive",
        "fk_care_assignment_created_by_account",
        "fk_care_assignment_updated_by_account",
    )
    for fragment in required_fragments:
        if fragment.lower() not in section:
            _fail("W1E_ALEMBIC_OFFLINE_CONTRACT_MISSING: " + fragment)
    compact_section = re.sub(r"\s+", "", section)
    for fragment in (
        "foreignkey(staff_id,employment_id)referenceserp.staff_employment(staff_id,id)"
        "ondeleterestrict",
        "foreignkey(replacement_assignment_id)referenceserp.care_assignment(id)"
        "ondeleterestrictdeferrableinitiallydeferred",
        "foreignkey(created_by_account_id)referenceserp.user_account(id)ondeleterestrict",
        "foreignkey(updated_by_account_id)referenceserp.user_account(id)ondeleterestrict",
        "check(assignment_kindin('general','family'))",
        "check(end_dateisnullorstart_date<=end_date)",
        "check(row_version>0)",
    ):
        if fragment not in compact_section:
            _fail("W1E_ALEMBIC_FOREIGN_KEY_CONTRACT_MISSING: " + fragment)

    forbidden_scope_patterns = (
        (
            "FAMILY",
            r"\b(?:w1[-_]?asg[-_]?02|family_(?:assignment|relationship_snapshot|"
            r"relationship_required|case|guard|period)|assignment_kind\s*=\s*'family')",
        ),
        (
            "CARE_CHANGE_ABS11",
            r"\b(?:w1[-_]?asg[-_]?03|w1[-_]?abs[-_]?11|abs[-_]?11|"
            r"care_change(?:_|$)|staff_change(?:_|$)|assignment_change(?:_|$))",
        ),
        (
            "VISIT_DELETE_ABS12",
            r"\b(?:w1[-_]?abs[-_]?12|abs[-_]?12|visit(?:_|$)|"
            r"assignment_visit|visit_execution|delete_(?:case|assignment)|assignment_delete)",
        ),
        (
            "MONTHLY_PROFESSIONAL",
            r"\b(?:w1[-_]?mon|monthly_professional(?:_|$)|professional_assignment(?:_|$))",
        ),
        (
            "BILLING",
            r"\b(?:billing|invoice|claim|payment|charge)(?:_|$)",
        ),
        (
            "FILE_IMPORT_OCR",
            r"\b(?:file|import|ocr|attachment|upload|document)(?:_|$)",
        ),
    )
    for family, pattern in forbidden_scope_patterns:
        match = re.search(pattern, section, flags=re.IGNORECASE)
        if match is not None:
            _fail("W1E_ALEMBIC_OFFLINE_SCOPE_BREACH: " + family + ":" + match.group(0))


def test_w1e_03_orm_care_assignment_contract_is_exact() -> None:
    """Product RED: ORM shape must match the migration contract when present."""
    try:
        from app.db import models
    except ImportError as exc:
        _fail("W1E_HARNESS_MODELS_IMPORT_MISSING: " + type(exc).__name__)

    model = getattr(models, "CareAssignment", None)
    if model is None:
        _product_absent("W1E_ORM_MODEL_MISSING: CareAssignment")
    table = getattr(model, "__table__", None)
    if table is None:
        _product_absent("W1E_ORM_TABLE_MISSING: CareAssignment.__table__")
    if table.name != "care_assignment" or table.schema != "erp":
        _fail("W1E_ORM_TABLE_IDENTITY_MISMATCH: " + repr((table.schema, table.name)))

    columns = {column.name: column for column in table.columns}
    if tuple(columns) != W1E_COLUMNS:
        _fail("W1E_ORM_COLUMN_SET_OR_ORDER: " + repr(tuple(columns)))

    expected_types = {
        "id": BigInteger,
        "recipient_contract_id": BigInteger,
        "staff_id": BigInteger,
        "employment_id": BigInteger,
        "assignment_kind": Text,
        "family_relationship_text": Text,
        "start_date": Date,
        "end_date": Date,
        "assignment_period": DATERANGE,
        "invalidated_at_utc": DateTime,
        "replacement_assignment_id": BigInteger,
        "created_by_account_id": BigInteger,
        "created_at_utc": DateTime,
        "updated_by_account_id": BigInteger,
        "updated_at_utc": DateTime,
        "row_version": Integer,
    }
    nullable_columns = {
        "family_relationship_text",
        "end_date",
        "invalidated_at_utc",
        "replacement_assignment_id",
    }
    for name, expected_type in expected_types.items():
        column = columns[name]
        if type(column.type) is not expected_type:
            _fail("W1E_ORM_COLUMN_TYPE_MISMATCH: " + name)
        if column.nullable is not (name in nullable_columns):
            _fail("W1E_ORM_COLUMN_NULLABILITY_MISMATCH: " + name)
    for name in ("created_at_utc", "updated_at_utc", "invalidated_at_utc"):
        if columns[name].type.timezone is not True:
            _fail("W1E_ORM_TIMESTAMP_TIMEZONE_MISMATCH: " + name)
    identity = columns["id"].identity
    if identity is None:
        _fail("W1E_ORM_IDENTITY_MISSING")
    identity_signature = (
        identity.always,
        identity.start,
        identity.increment,
        identity.minvalue,
        identity.maxvalue,
        identity.nominvalue,
        identity.nomaxvalue,
        identity.cycle,
        identity.cache,
        identity.order,
        identity.on_null,
    )
    if identity_signature != (False,) + (None,) * 10:
        _fail("W1E_ORM_IDENTITY_OPTIONS_MISMATCH: " + repr(identity_signature))
    for name, column in columns.items():
        if name != "id" and column.identity is not None:
            _fail("W1E_ORM_UNEXPECTED_IDENTITY: " + name)
        if column.default is not None:
            _fail("W1E_ORM_UNEXPECTED_CLIENT_DEFAULT: " + name)
        if column.onupdate is not None:
            _fail("W1E_ORM_UNEXPECTED_CLIENT_ONUPDATE: " + name)

    computed = columns["assignment_period"].computed
    if computed is None or computed.persisted is not True:
        _fail("W1E_ORM_ASSIGNMENT_PERIOD_NOT_STORED")
    if _compact_expression(str(computed.sqltext)) != "daterange(start_date,end_date+1,'[)')":
        _fail("W1E_ORM_ASSIGNMENT_PERIOD_EXPRESSION_MISMATCH")
    for name, column in columns.items():
        if name != "assignment_period" and column.computed is not None:
            _fail("W1E_ORM_UNEXPECTED_COMPUTED_COLUMN: " + name)
        if name == "assignment_period":
            if column.server_default is not computed or column.server_onupdate is not computed:
                _fail("W1E_ORM_ASSIGNMENT_PERIOD_DEFAULT_BINDING_MISMATCH")
        elif column.server_onupdate is not None:
            _fail("W1E_ORM_UNEXPECTED_SERVER_ONUPDATE: " + name)

    expected_server_defaults = {
        "created_at_utc": "now()",
        "updated_at_utc": "now()",
        "row_version": "1",
    }
    for name, column in columns.items():
        if name == "id":
            if column.server_default is not identity:
                _fail("W1E_ORM_IDENTITY_DEFAULT_BINDING_MISMATCH")
            continue
        if name == "assignment_period":
            continue
        default = column.server_default
        expected_default = expected_server_defaults.get(name)
        if expected_default is None:
            if default is not None:
                _fail("W1E_ORM_UNEXPECTED_SERVER_DEFAULT: " + name)
        elif default is None or _compact_expression(str(default.arg)) != expected_default:
            _fail("W1E_ORM_SERVER_DEFAULT_MISMATCH: " + name)

    if any(constraint.name is None for constraint in table.constraints):
        _fail("W1E_ORM_UNNAMED_CONSTRAINT")
    constraints = {constraint.name: constraint for constraint in table.constraints}
    if set(constraints) != W1E_CONSTRAINT_NAMES:
        _fail("W1E_ORM_CONSTRAINT_SET_MISMATCH: " + repr(sorted(constraints)))

    primary_key = constraints["pk_care_assignment"]
    if not isinstance(primary_key, PrimaryKeyConstraint) or tuple(
        column.name for column in primary_key.columns
    ) != ("id",):
        _fail("W1E_ORM_PRIMARY_KEY_MISMATCH")

    def require_fk(
        name: str,
        local_columns: tuple[str, ...],
        targets: tuple[str, ...],
        *,
        deferrable: bool = False,
        initially: str | None = None,
    ) -> None:
        constraint = constraints[name]
        if not isinstance(constraint, ForeignKeyConstraint):
            _fail("W1E_ORM_FOREIGN_KEY_KIND_MISMATCH: " + name)
        if tuple(column.name for column in constraint.columns) != local_columns:
            _fail("W1E_ORM_FOREIGN_KEY_LOCAL_MISMATCH: " + name)
        if tuple(element.target_fullname for element in constraint.elements) != targets:
            _fail("W1E_ORM_FOREIGN_KEY_TARGET_MISMATCH: " + name)
        if (constraint.ondelete or "").upper() != "RESTRICT":
            _fail("W1E_ORM_FOREIGN_KEY_DELETE_ACTION_MISMATCH: " + name)
        if constraint.onupdate is not None or constraint.match is not None:
            _fail("W1E_ORM_FOREIGN_KEY_UPDATE_OR_MATCH_MISMATCH: " + name)
        actual_deferrable = constraint.deferrable is True
        if actual_deferrable is not deferrable:
            _fail("W1E_ORM_FOREIGN_KEY_DEFERRABLE_MISMATCH: " + name)
        if (constraint.initially or "").upper() != (initially or ""):
            _fail("W1E_ORM_FOREIGN_KEY_INITIAL_STATE_MISMATCH: " + name)

    require_fk(
        "fk_care_assignment_recipient_contract",
        ("recipient_contract_id",),
        ("erp.recipient_contract.id",),
    )
    require_fk(
        "fk_care_assignment_employment",
        ("staff_id", "employment_id"),
        ("erp.staff_employment.staff_id", "erp.staff_employment.id"),
    )
    require_fk(
        "fk_care_assignment_replacement",
        ("replacement_assignment_id",),
        ("erp.care_assignment.id",),
        deferrable=True,
        initially="DEFERRED",
    )
    require_fk(
        "fk_care_assignment_created_by_account",
        ("created_by_account_id",),
        ("erp.user_account.id",),
    )
    require_fk(
        "fk_care_assignment_updated_by_account",
        ("updated_by_account_id",),
        ("erp.user_account.id",),
    )

    expected_checks = {
        "ck_care_assignment_kind": "assignment_kindin('general','family')",
        "ck_care_assignment_date_order": "end_dateisnullorstart_date<=end_date",
        "ck_care_assignment_row_version_positive": "row_version>0",
    }
    for name, expected in expected_checks.items():
        constraint = constraints[name]
        if not isinstance(constraint, CheckConstraint):
            _fail("W1E_ORM_CHECK_KIND_MISMATCH: " + name)
        if _compact_expression(str(constraint.sqltext)) != expected:
            _fail("W1E_ORM_CHECK_EXPRESSION_MISMATCH: " + name)

    exclusion = constraints["ex_care_assignment_same_contract_staff_period"]
    if not isinstance(exclusion, ExcludeConstraint):
        _fail("W1E_ORM_EXCLUSION_KIND_MISMATCH")
    render_expressions = tuple((str(item[1]), str(item[2])) for item in exclusion._render_exprs)
    if render_expressions != (
        ("recipient_contract_id", "="),
        ("staff_id", "="),
        ("assignment_period", "&&"),
    ):
        _fail("W1E_ORM_EXCLUSION_KEYS_MISMATCH")
    if exclusion.using != "gist" or _compact_expression(str(exclusion.where)) != (
        "invalidated_at_utcisnull"
    ):
        _fail("W1E_ORM_EXCLUSION_PREDICATE_MISMATCH")
    if exclusion.deferrable not in (None, False) or exclusion.initially is not None:
        _fail("W1E_ORM_EXCLUSION_DEFERRABILITY_MISMATCH")


# --- Bounded PL/pgSQL control-flow model for the reverse-guard boundaries -----
#
# A boundary is sealed only when the migration raises the exact assignment
# integrity message from a REACHABLE RAISE statement whose controlling branch
# ancestry references the required semantic keys. Token presence alone proves
# nothing: comments, string literals, THEN bodies, PERFORM/assignment
# statements, statically false branches (directly or via an ancestor), and other
# functions' bodies must never seal a boundary.
#
# The grammar covered is the canonical guard subset actually used by W1E:
#   statement := IF cond THEN block (ELSIF cond THEN block)* (ELSE block)? END IF
#              | RAISE ... ;
#              | <any other statement> ;
# Anything outside it raises _UnsupportedPlpgsql so an unparsable body surfaces
# as a harness failure instead of silently passing or failing the product.


class _UnsupportedPlpgsql(Exception):
    """The bounded PL/pgSQL subset does not cover this guard body."""


_CONTROL_TOKEN_PATTERN = re.compile(
    r"\bend\s+if\b|\bbegin\b|\bend\b|\belsif\b|\belseif\b|\belse\b|"
    r"\bthen\b|\bif\b|\braise\b|\breturn\b|;",
    flags=re.IGNORECASE,
)
_UNSUPPORTED_PLPGSQL_PATTERN = re.compile(
    r"\b(?:loop|while|for|case|exception|execute|exit|continue)\b",
    flags=re.IGNORECASE,
)


def _control_tokens(scan: str) -> tuple[tuple[str, int, int], ...]:
    """Control tokens of the literal-masked scan as (kind, start, end)."""
    tokens: list[tuple[str, int, int]] = []
    for match in _CONTROL_TOKEN_PATTERN.finditer(scan):
        kind = re.sub(r"\s+", " ", match.group().lower())
        tokens.append(("elsif" if kind == "elseif" else kind, match.start(), match.end()))
    return tuple(tokens)


def _mask_plpgsql_code(sql: str) -> str:
    """Return the validated, offset-preserving executable-code scan."""
    return _scan_plpgsql_lexical(sql)[1]


# Executable delimiter validation. Parentheses and square brackets are only
# structural outside opaque literals/comments, so the masked scan is the sole
# input here: delimiter-looking text inside ordinary/E strings, quoted
# identifiers, dollar strings, line comments and nested block comments stays
# opaque and is therefore ignored.
_DELIMITER_CLOSERS = {")": "(", "]": "["}
_MAX_DELIMITER_DEPTH = 64


def _require_balanced_delimiter_scan(scan: str, label: str) -> None:
    """Raise unless the masked scan has balanced executable ()/[] delimiters."""
    stack: list[str] = []
    for character in scan:
        if character in "([":
            if len(stack) >= _MAX_DELIMITER_DEPTH:
                raise _UnsupportedPlpgsql("delimiter nesting too deep in " + label)
            stack.append(character)
            continue
        opener = _DELIMITER_CLOSERS.get(character)
        if opener is None:
            continue
        if not stack or stack[-1] != opener:
            raise _UnsupportedPlpgsql("unmatched " + character + " in " + label)
        stack.pop()
    if stack:
        raise _UnsupportedPlpgsql("unmatched " + stack[-1] + " in " + label)


def _require_balanced_delimiters(fragment: str, label: str) -> None:
    """Validate delimiters of a raw fragment after lexical masking."""
    _require_balanced_delimiter_scan(_mask_plpgsql_code(fragment), label)


def _controlling_condition(text: str, start: int, stop: int, label: str) -> str:
    """Return one controlling condition slice, delimiter-validated first."""
    condition = text[start:stop]
    _require_balanced_delimiters(condition, label + " condition")
    return condition


def _parse_statements(
    text: str,
    tokens: tuple[tuple[str, int, int], ...],
    index: int,
    scan: str,
    block_start: int = 0,
) -> tuple[tuple[Any, ...], int]:
    """Parse one block; returns (statements, index of the block terminator)."""
    statements: list[Any] = []
    last_end = block_start
    while index < len(tokens):
        kind = tokens[index][0]
        tok_start = tokens[index][1]
        if kind in ("elsif", "else", "end if", "end"):
            if scan[last_end:tok_start].strip():
                raise _UnsupportedPlpgsql("unterminated statement before " + kind)
            return tuple(statements), index
        if kind == ";":
            last_end = tokens[index][2]
            index += 1
            continue
        if scan[last_end:tok_start].strip():
            raise _UnsupportedPlpgsql("unterminated statement before " + kind)
        if kind == "then":
            raise _UnsupportedPlpgsql("unbalanced then")
        if kind == "begin":
            raise _UnsupportedPlpgsql("nested begin")
        if kind == "raise":
            # The stream holds control tokens only, so a well-formed RAISE
            # statement is terminated by the very next token.
            if index + 1 >= len(tokens) or tokens[index + 1][0] != ";":
                raise _UnsupportedPlpgsql("raise statement")
            statements.append(("raise", text[tokens[index][1] : tokens[index + 1][1]]))
            last_end = tokens[index + 1][2]
            index += 2
            continue
        if kind == "return":
            if index + 1 >= len(tokens) or tokens[index + 1][0] != ";":
                raise _UnsupportedPlpgsql("return statement")
            statements.append(("return", text[tokens[index][1] : tokens[index + 1][1]]))
            last_end = tokens[index + 1][2]
            index += 2
            continue
        if kind != "if":
            raise _UnsupportedPlpgsql("unexpected " + kind)
        branches: list[tuple[str | None, tuple[Any, ...]]] = []
        condition_start = tokens[index][2]
        cursor = index + 1
        if cursor >= len(tokens) or tokens[cursor][0] != "then":
            raise _UnsupportedPlpgsql("if condition")
        then_index = cursor
        body, cursor = _parse_statements(text, tokens, cursor + 1, scan, tokens[then_index][2])
        branches.append(
            (
                _controlling_condition(text, condition_start, tokens[then_index][1], "if"),
                body,
            )
        )
        while cursor < len(tokens) and tokens[cursor][0] == "elsif":
            condition_start = tokens[cursor][2]
            cursor += 1
            if cursor >= len(tokens) or tokens[cursor][0] != "then":
                raise _UnsupportedPlpgsql("elsif condition")
            then_index = cursor
            body, cursor = _parse_statements(text, tokens, cursor + 1, scan, tokens[then_index][2])
            branches.append(
                (
                    _controlling_condition(text, condition_start, tokens[then_index][1], "elsif"),
                    body,
                )
            )
        if cursor < len(tokens) and tokens[cursor][0] == "else":
            else_index = cursor
            body, cursor = _parse_statements(text, tokens, cursor + 1, scan, tokens[else_index][2])
            branches.append((None, body))
        if cursor >= len(tokens) or tokens[cursor][0] != "end if":
            raise _UnsupportedPlpgsql("end if")
        end_if_token = tokens[cursor]
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor][0] != ";":
            raise _UnsupportedPlpgsql("missing semicolon after end if")
        if text[end_if_token[2] : tokens[cursor][1]].strip():
            raise _UnsupportedPlpgsql("executable text after end if")
        last_end = tokens[cursor][2]
        cursor += 1
        statements.append(("if", tuple(branches)))
        index = cursor
    return tuple(statements), index


def _parse_guard_body(body: str) -> tuple[Any, ...]:
    """Return the statement tree of a validated, offset-preserving guard body."""
    text, scan = _scan_plpgsql_lexical(body)
    if len(text) != len(body) or len(scan) != len(body):
        raise _UnsupportedPlpgsql("lexical scan offset mismatch")
    _require_balanced_delimiter_scan(scan, "guard body")
    unsupported_scan = re.sub(
        r"\braise\s+exception\b",
        lambda match: " " * len(match.group()),
        scan,
        flags=re.IGNORECASE,
    )
    if _UNSUPPORTED_PLPGSQL_PATTERN.search(unsupported_scan):
        raise _UnsupportedPlpgsql("unsupported control flow")
    tokens = _control_tokens(scan)

    begin_indexes = tuple(index for index, token in enumerate(tokens) if token[0] == "begin")
    if len(begin_indexes) != 1:
        raise _UnsupportedPlpgsql("missing outer begin wrapper")
    begin_index = begin_indexes[0]
    begin_token = tokens[begin_index]
    if begin_index != 0 or scan[: begin_token[1]].strip():
        raise _UnsupportedPlpgsql("missing outer begin wrapper")

    end_indexes = tuple(index for index, token in enumerate(tokens) if token[0] == "end")
    if len(end_indexes) != 1:
        raise _UnsupportedPlpgsql("missing outer end wrapper")
    outer_end_index = end_indexes[0]
    outer_end_token = tokens[outer_end_index]
    if outer_end_index <= begin_index:
        raise _UnsupportedPlpgsql("missing outer end wrapper")
    if re.fullmatch(r"\s*;?\s*", scan[outer_end_token[2] :]) is None:
        raise _UnsupportedPlpgsql("executable text after outer end")

    statements, index = _parse_statements(text, tokens, begin_index + 1, scan, begin_token[2])
    if index != outer_end_index:
        raise _UnsupportedPlpgsql("dangling " + tokens[index][0])
    return statements


def _unwrap_parentheses(value: str) -> str:
    """Remove only parentheses that wrap the complete expression."""
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        wraps_whole_expression = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    wraps_whole_expression = False
                    break
                if depth < 0:
                    wraps_whole_expression = False
                    break
        if not wraps_whole_expression or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def _split_top_level_boolean(value: str, operator: str) -> tuple[str, ...] | None:
    """Split a boolean expression at one top-level AND/OR operator."""
    pieces: list[str] = []
    depth = 0
    start = 0
    scan = _mask_plpgsql_code(value.lower())
    for match in re.finditer(r"[()]|\b(?:and|or)\b", scan):
        token = match.group().lower()
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and token == operator:
            pieces.append(value[start : match.start()])
            start = match.end()
    if depth != 0 or not pieces:
        return None
    pieces.append(value[start:])
    return tuple(pieces)


def _constant_boolean_value(condition: str) -> bool | None:
    """Evaluate only simple constant boolean expressions; unknown means reachable."""
    value = _unwrap_parentheses(_mask_plpgsql_code(condition.lower()).strip())
    while True:
        cast = re.fullmatch(r"(.+?)\s*::\s*(?:boolean|bool)", value)
        if cast is None:
            break
        value = _unwrap_parentheses(cast.group(1))

    disjunction = _split_top_level_boolean(value, "or")
    if disjunction is not None:
        values = tuple(_constant_boolean_value(part) for part in disjunction)
        if any(item is True for item in values):
            return True
        if all(item is False for item in values):
            return False
        return None

    conjunction = _split_top_level_boolean(value, "and")
    if conjunction is not None:
        values = tuple(_constant_boolean_value(part) for part in conjunction)
        if any(item is False for item in values):
            return False
        if all(item is True for item in values):
            return True
        return None

    negation = re.match(r"not(?=\s|\()", value)
    if negation is not None:
        nested = _constant_boolean_value(value[negation.end() :].lstrip())
        return None if nested is None else not nested
    if value == "true":
        return True
    if value == "false":
        return False

    comparison = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(<=|>=|<>|!=|=|<|>)\s*"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))",
        value,
    )
    if comparison is not None:
        left = float(comparison.group(1))
        right = float(comparison.group(3))
        operator = comparison.group(2)
        return {
            "<": left < right,
            "<=": left <= right,
            "=": left == right,
            "!=": left != right,
            "<>": left != right,
            ">=": left >= right,
            ">": left > right,
        }[operator]
    return None


def _statically_false(condition: str) -> bool:
    """True only when the bounded evaluator proves the condition is false."""
    return _constant_boolean_value(condition) is False


def _statically_true(condition: str) -> bool:
    """True only when the bounded evaluator proves the condition is true."""
    return _constant_boolean_value(condition) is True


_RAISE_OPTION_NAMES = frozenset(
    {
        "column",
        "constraint",
        "datatype",
        "detail",
        "errcode",
        "hint",
        "message",
        "schema",
        "table",
    }
)


def _raise_lexemes(raise_text: str) -> tuple[tuple[str, str], ...] | None:
    """Tokenize a bounded RAISE statement without scanning inside literals."""
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(raise_text):
        if raise_text[index].isspace():
            index += 1
            continue
        quoted = _sql_quoted_span(raise_text, index)
        if quoted is not None:
            kind, stop = quoted
            if stop is None:
                return None
            if kind == "string":
                value = raise_text[index + 1 : stop - 1].replace("''", "'")
                tokens.append(("string", value))
            else:
                tokens.append(("opaque", kind))
            index = stop
            continue
        if raise_text[index] == "$":
            dollar = _sql_dollar_span(raise_text, index)
            if dollar is not None:
                _, stop = dollar
                if stop is None:
                    return None
                index = stop
                tokens.append(("opaque", "dollar_string"))
                continue
        word = re.match(r"[A-Za-z_][A-Za-z0-9_]*", raise_text[index:])
        if word:
            tokens.append(("word", word.group().lower()))
            index += len(word.group())
            continue
        tokens.append(("symbol", raise_text[index]))
        index += 1
    return tuple(tokens)


def _raise_using_options(
    tokens: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...] | None:
    """Parse bounded USING name=value clauses split outside expression groups."""
    clauses: list[tuple[tuple[str, str], ...]] = []
    current: list[tuple[str, str]] = []
    delimiters: list[str] = []
    closing = {"(": ")", "[": "]"}
    for token in tokens:
        if token[0] == "symbol" and token[1] in closing:
            delimiters.append(closing[token[1]])
        elif token[0] == "symbol" and token[1] in closing.values():
            if not delimiters or delimiters.pop() != token[1]:
                return None
        if token == ("symbol", ",") and not delimiters:
            if not current:
                return None
            clauses.append(tuple(current))
            current = []
            continue
        current.append(token)
    if delimiters or not current:
        return None
    clauses.append(tuple(current))

    options: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for clause in clauses:
        if (
            len(clause) < 3
            or clause[0][0] != "word"
            or clause[0][1] not in _RAISE_OPTION_NAMES
            or clause[1] != ("symbol", "=")
        ):
            return None
        options.append((clause[0][1], clause[2:]))
    return tuple(options)


def _raise_targets_message(raise_text: str, message: str) -> bool:
    """Match only an explicit EXCEPTION's actual, exact message literal."""
    tokens = _raise_lexemes(raise_text)
    if tokens is None or tokens[:2] != (("word", "raise"), ("word", "exception")):
        return False
    remainder = tokens[2:]
    if not remainder:
        return False

    if remainder[0][0] == "string":
        if remainder[0][1] != message:
            return False
        if len(remainder) == 1:
            return True
        if remainder[1] != ("word", "using"):
            return False
        options = _raise_using_options(remainder[2:])
        return options is not None and all(name != "message" for name, _ in options)

    if remainder[0] != ("word", "using"):
        return False
    options = _raise_using_options(remainder[1:])
    if options is None:
        return False
    message_values = tuple(value for name, value in options if name == "message")
    return len(message_values) == 1 and message_values[0] == (("string", message),)


def _raise_is_terminal(raise_text: str) -> bool:
    """Only explicit message severities permit the current path to continue."""
    return (
        re.match(
            r"\s*raise\s+(?:debug|log|info|notice|warning)\b",
            raise_text,
            flags=re.IGNORECASE,
        )
        is None
    )


def _block_can_fall_through(statements: tuple[Any, ...]) -> bool:
    """Whether some path through a block can reach its end normally."""
    can_fall_through = True
    for statement in statements:
        if not can_fall_through:
            break
        if statement[0] == "raise":
            if _raise_is_terminal(statement[1]):
                can_fall_through = False
        elif statement[0] == "return":
            can_fall_through = False
        elif statement[0] == "if":
            can_fall_through = _if_can_fall_through(statement[1])
    return can_fall_through


def _if_can_fall_through(branches: tuple[tuple[str | None, tuple[Any, ...]], ...]) -> bool:
    """Whether an IF statement has any normally completing execution path."""
    prior_branch_possible = True
    can_fall_through = False
    for condition, body in branches:
        if not prior_branch_possible:
            break
        if condition is None:
            can_fall_through = _block_can_fall_through(body)
            prior_branch_possible = False
            break
        value = _constant_boolean_value(condition)
        if value is not False and _block_can_fall_through(body):
            can_fall_through = True
        if value is True:
            prior_branch_possible = False
    if prior_branch_possible:
        can_fall_through = True
    return can_fall_through


def _collect_block_target_raises(
    statements: tuple[Any, ...],
    message: str,
    ancestry: tuple[str, ...],
    reachable: bool,
    found: list[tuple[tuple[str, ...], bool]],
) -> None:
    """Collect target raises while propagating statement-level reachability."""
    path_reachable = reachable
    for statement in statements:
        if statement[0] == "raise":
            if _raise_targets_message(statement[1], message):
                found.append((ancestry, path_reachable))
            if path_reachable and _raise_is_terminal(statement[1]):
                path_reachable = False
            continue
        if statement[0] == "return":
            if path_reachable:
                path_reachable = False
            continue
        if statement[0] != "if":
            continue
        branches = statement[1]
        prior_branch_possible = True
        for condition, body in branches:
            if not prior_branch_possible:
                break
            if condition is None:
                _collect_block_target_raises(body, message, ancestry, path_reachable, found)
                prior_branch_possible = False
                break
            value = _constant_boolean_value(condition)
            branch_reachable = path_reachable and value is not False
            _collect_block_target_raises(
                body, message, ancestry + (condition,), branch_reachable, found
            )
            if value is True:
                prior_branch_possible = False
        if path_reachable:
            path_reachable = _if_can_fall_through(branches)


def _collect_target_raises(
    statements: tuple[Any, ...],
    message: str,
    ancestry: tuple[str, ...],
    reachable: bool,
    found: list[tuple[tuple[str, ...], bool]],
) -> None:
    """Record (controlling conditions, reachability) per RAISE of the message."""
    _collect_block_target_raises(statements, message, ancestry, reachable, found)


def _conditions_reference(conditions: tuple[str, ...], tokens: tuple[str, ...]) -> bool:
    joined = " ".join(_mask_plpgsql_code(condition).lower() for condition in conditions)
    collapsed = re.sub(r"\s*\.\s*", ".", joined)
    return all(
        re.search(r"(?<![a-z0-9_])" + re.escape(token) + r"(?![a-z0-9_])", collapsed) is not None
        for token in tokens
    )


def _rejection_binds_tokens(body: str, message: str, tokens: tuple[str, ...]) -> bool:
    """True iff some REACHABLE RAISE of ``message`` is controlled by a branch
    ancestry that references every required token as executable SQL."""
    found: list[tuple[tuple[str, ...], bool]] = []
    _collect_target_raises(_parse_guard_body(body), message, (), True, found)
    return any(
        reachable and _conditions_reference(conditions, tokens) for conditions, reachable in found
    )


def _binds_or_harness_fail(
    body: str, message: str, tokens: tuple[str, ...], harness_prefix: str
) -> bool:
    try:
        return _rejection_binds_tokens(body, message, tokens)
    except _UnsupportedPlpgsql as exc:
        _fail(harness_prefix + "_UNSUPPORTED_PLPGSQL: " + str(exc))


# --- Deterministic synthetic mutation corpus ---------------------------------
#
# Bodies are structural fixtures for the matcher, not executable migrations.
# ``bound`` references every required token; ``unbound`` references none.

_RAISE = "raise exception using errcode = '23514', message = '{message}';"
_BACKSLASH = chr(92)


def _malformed_lexical_corpus(*, message: str, bound: str) -> tuple[tuple[str, str], ...]:
    """Malformed suffixes that must fail closed before semantic approval."""
    valid = f"begin if {bound} then {_RAISE.format(message=message)} end if; return new; end"
    return (
        ("trailing_unclosed_single_quote", valid + " perform 'unterminated"),
        ("trailing_unclosed_escape_string", valid + " perform E'unterminated"),
        ("trailing_unclosed_block_comment", valid + " /* unterminated"),
        ("trailing_unclosed_dollar_quote", valid + " perform $unterminated$body"),
        ("trailing_unclosed_double_quote", valid + ' perform "unterminated'),
    )


def _malformed_delimiter_corpus(*, message: str, bound: str) -> tuple[tuple[str, str], ...]:
    """Unmatched executable ()/[] delimiters that must fail closed.

    Covers the four malformed forms found by the strict-blind matrix -- an
    unmatched opening parenthesis, an unmatched closing parenthesis, an
    unmatched opening square bracket and an unmatched closing square bracket --
    in the controlling IF condition, in the controlling ELSIF condition and in
    surrounding executable statements, plus one mismatched pairing.
    """
    target = _RAISE.format(message=message)
    prefix = "begin if false then return new; elsif "
    return (
        (
            "if_condition_unmatched_opening_parenthesis",
            f"begin if ({bound} then {target} end if; return new; end",
        ),
        (
            "if_condition_unmatched_closing_parenthesis",
            f"begin if {bound}) then {target} end if; return new; end",
        ),
        (
            "if_condition_unmatched_opening_bracket",
            f"begin if {bound} and tags[1 = 1 then {target} end if; return new; end",
        ),
        (
            "if_condition_unmatched_closing_bracket",
            f"begin if {bound} and tags1] = 1 then {target} end if; return new; end",
        ),
        (
            "elsif_condition_unmatched_opening_parenthesis",
            f"{prefix}({bound} then {target} end if; return new; end",
        ),
        (
            "elsif_condition_unmatched_closing_parenthesis",
            f"{prefix}{bound}) then {target} end if; return new; end",
        ),
        (
            "elsif_condition_unmatched_opening_bracket",
            f"{prefix}{bound} and tags[1 = 1 then {target} end if; return new; end",
        ),
        (
            "elsif_condition_unmatched_closing_bracket",
            f"{prefix}{bound} and tags1] = 1 then {target} end if; return new; end",
        ),
        (
            "statement_unmatched_opening_parenthesis_after_guard",
            f"begin if {bound} then {target} end if; perform lower( ; return new; end",
        ),
        (
            "statement_unmatched_closing_parenthesis_before_guard",
            f"begin perform lower); if {bound} then {target} end if; return new; end",
        ),
        (
            "statement_unmatched_opening_bracket_before_guard",
            f"begin perform tags[1; if {bound} then {target} end if; return new; end",
        ),
        (
            "statement_unmatched_closing_bracket_after_guard",
            f"begin if {bound} then {target} end if; perform tags1]; return new; end",
        ),
        (
            "if_condition_mismatched_delimiter_pairing",
            f"begin if ({bound}] then {target} end if; return new; end",
        ),
    )


def _malformed_statement_boundary_corpus(
    *, message: str, bound: str
) -> tuple[tuple[str, str], ...]:
    """Malformed statement boundaries that must fail closed before approval."""
    target = _RAISE.format(message=message)
    return (
        (
            "missing_semicolon_between_ordinary_and_if",
            f"begin perform 1 if {bound} then {target} end if; return new; end",
        ),
        (
            "perform_if_adjacency",
            f"begin perform if {bound} then {target} end if; return new; end",
        ),
        (
            "missing_semicolon_before_end_if",
            f"begin if {bound} then perform 1 {target} end if; return new; end",
        ),
        (
            "missing_semicolon_after_end_if",
            f"begin if {bound} then {target} end if return new; end",
        ),
        (
            "ordinary_text_between_end_if_and_semicolon",
            f"begin if {bound} then {target} end if perform lower(1); return new; end",
        ),
        (
            "string_between_end_if_and_semicolon",
            f"begin if {bound} then {target} end if 'opaque'; return new; end",
        ),
        (
            "quoted_identifier_between_end_if_and_semicolon",
            f'begin if {bound} then {target} end if "opaque"; return new; end',
        ),
        (
            "dollar_literal_between_end_if_and_semicolon",
            f"begin if {bound} then {target} end if $opaque$text$opaque$; return new; end",
        ),
        (
            "missing_semicolon_before_elsif",
            f"begin if {bound} then return new; elsif {bound} then "
            f"perform 1 {target} end if; return new; end",
        ),
        (
            "missing_semicolon_before_else",
            f"begin if false then return new; else perform 1 "
            f"if {bound} then {target} end if; end if; return new; end",
        ),
        (
            "ordinary_before_outer_end",
            f"begin if {bound} then {target} end if; return new; perform 1 end",
        ),
        (
            "outer_end_word_suffix",
            f"begin if {bound} then {target} end if; return new; weekend",
        ),
        (
            "executable_between_outer_ends",
            f"begin if {bound} then {target} end if; return new; end perform 1 end",
        ),
    )


def _negative_corpus(
    *, message: str, bound: str, unbound: str, noop: str, literal: str, other: str
) -> tuple[tuple[str, str], ...]:
    target = _RAISE.format(message=message)
    return (
        (
            "tokens_only_in_separate_false_perform_decoy",
            f"begin if false then {noop} end if;"
            f" if {unbound} then {target} end if; return new; end",
        ),
        (
            "direct_false_and_bound_condition",
            f"begin if false and ({bound}) then {target} end if; return new; end",
        ),
        (
            "cast_false_and_bound_condition",
            f"begin if false::boolean and ({bound}) then {target} end if; return new; end",
        ),
        (
            "numeric_false_and_bound_condition",
            f"begin if 2 < 1 and ({bound}) then {target} end if; return new; end",
        ),
        (
            "boolean_or_false_and_bound_condition",
            f"begin if (false or false) and ({bound}) then {target} end if; return new; end",
        ),
        (
            "not_parenthesized_true_and_bound_condition",
            f"begin if not(true) and ({bound}) then {target} end if; return new; end",
        ),
        (
            "bound_raise_nested_under_false_outer",
            f"begin if false then if {bound} then {target} end if; end if; return new; end",
        ),
        (
            "target_message_in_notice",
            f"begin if {bound} then raise notice using message = '{message}';"
            f" end if; return new; end",
        ),
        (
            "target_message_in_warning",
            f"begin if {bound} then raise warning using message = '{message}';"
            f" end if; return new; end",
        ),
        (
            "target_message_in_dollar_quoted_detail_decoy",
            f"begin if {bound} then raise exception using"
            f" detail = $$message = '{message}',$$,"
            f" message = 'other'; end if; return new; end",
        ),
        (
            "target_message_in_dollar_quoted_detail_decoy_after_message",
            f"begin if {bound} then raise exception using message = 'other',"
            f" detail = $decoy$message = '{message}',$decoy$;"
            f" end if; return new; end",
        ),
        (
            "target_message_in_escape_string_detail_decoy",
            f"begin if {bound} then raise exception using"
            f" detail = E'prefix {_BACKSLASH}' message = ''{message}''',"
            f" message = 'other'; end if; return new; end",
        ),
        (
            "target_message_in_perform_or_assignment",
            f"begin if {bound} then perform '{message}';"
            f" guard_message := '{message}'; end if; return new; end",
        ),
        (
            "tokens_in_then_body_literal_and_comment",
            f"begin\n-- {literal}\nif {unbound} and assignment_kind = '{literal}'"
            f" then {noop} {target} end if; return new; end",
        ),
        (
            "duplicate_raise_with_unreachable_decoy",
            f"begin if false and ({bound}) then {target} end if;"
            f" if {unbound} then {target} end if; return new; end",
        ),
        (
            "elsif_after_unconditional_true",
            f"begin if true then return new; elsif {bound} then {target} end if; return new; end",
        ),
        (
            "else_after_unconditional_true",
            f"begin if true then return new; else if {bound} then {target}"
            f" end if; end if; return new; end",
        ),
        (
            "target_raise_after_return",
            f"begin if {bound} then return new; {target} end if; return new; end",
        ),
        (
            "target_raise_after_unconditional_non_target_raise",
            f"begin if {bound} then raise exception using message = 'other';"
            f" {target} end if; return new; end",
        ),
        (
            "target_raise_after_level_omitted_using_raise",
            f"begin if {bound} then raise using message = 'other';"
            f" {target} end if; return new; end",
        ),
        (
            "target_raise_after_level_omitted_format_raise",
            f"begin if {bound} then raise 'other'; {target} end if; return new; end",
        ),
        (
            "target_raise_after_sqlstate_raise",
            f"begin if {bound} then raise sqlstate 'P0001'; {target} end if; return new; end",
        ),
        (
            "target_raise_after_bare_rethrow",
            f"begin if {bound} then raise; {target} end if; return new; end",
        ),
        (
            "target_message_in_level_omitted_raise",
            f"begin if {bound} then raise using message = '{message}'; end if; return new; end",
        ),
        (
            "target_message_in_sqlstate_raise",
            f"begin if {bound} then raise sqlstate 'P0001'"
            f" using message = '{message}'; end if; return new; end",
        ),
        (
            "dollar_quoted_fake_control_flow",
            f"begin perform $fake$ if {bound} then {target} end if; $fake$; return new; end",
        ),
        (
            "escape_string_fake_control_flow",
            f"begin perform E'prefix {_BACKSLASH}'; if {bound} then {target}"
            f" end if;'; return new; end",
        ),
        ("tokens_in_other_function_body", other),
    )


def _positive_corpus(*, message: str, bound: str, unbound: str) -> tuple[tuple[str, str], ...]:
    target = _RAISE.format(message=message)
    return (
        (
            "canonical_if_then_target_raise",
            f"begin if {bound} then {target} end if; return new; end",
        ),
        (
            "direct_target_literal_with_using",
            f"begin if {bound} then raise exception '{message}'"
            f" using errcode = '23514'; end if; return new; end",
        ),
        (
            "single_quoted_double_quote_before_guard",
            f"begin perform '\"'; if {bound} then {target} end if; return new; end",
        ),
        (
            "double_quoted_single_quote_before_guard",
            f'begin perform "guard\'identifier"; if {bound} then {target} end if; return new; end',
        ),
        (
            "doubled_quotes_before_guard",
            f'begin perform \'it\'\'s "safe"\'; perform "guard""\'identifier";'
            f" if {bound} then {target} end if; return new; end",
        ),
        (
            "escape_string_escaped_quote_before_guard",
            f"begin perform E'prefix {_BACKSLASH}' suffix'; if {bound} then"
            f" {target} end if; return new; end",
        ),
        (
            "explicit_nonterminal_raise_levels_before_guard",
            f"begin if {bound} then raise debug 'debug'; raise log 'log';"
            f" raise info 'info'; raise notice 'notice'; raise warning 'warning';"
            f" {target} end if; return new; end",
        ),
        (
            "reachable_elsif_guard",
            f"begin if {unbound} then return new; elsif {bound} then"
            f" {target} end if; return new; end",
        ),
        (
            "reachable_else_nested_guard",
            f"begin if {unbound} then return new; else if {bound} then"
            f" {target} end if; end if; return new; end",
        ),
        (
            "block_comment_between_end_if_and_semicolon",
            f"begin if {bound} then {target} end if /* opaque */; return new; end",
        ),
        (
            "line_comment_between_end_if_and_semicolon",
            f"begin if {bound} then {target} end if -- opaque\n; return new; end",
        ),
        (
            "bound_outer_condition_with_reachable_inner_branch",
            f"begin if {bound} then if new.id is not null then {target}"
            f" end if; end if; return new; end",
        ),
        (
            "opaque_dollar_literal_before_guard",
            f"begin perform $opaque$/* -- ' \" ; if {bound} then {target}"
            f" end if; /* unmatched-looking text$opaque$; if {bound} then"
            f" {target} end if; return new; end",
        ),
        (
            "eof_line_comment_after_guard",
            f"begin if {bound} then {target} end if; return new; end"
            " -- /* $unterminated$ ' \" if false then",
        ),
        (
            "balanced_nested_parentheses_and_casts_guard",
            f"begin if (({bound})) and (coalesce(1, (2))::int = 1) then"
            f" {target} end if; return new; end",
        ),
        (
            "balanced_array_subscript_guard",
            f"begin if ({bound}) and (array[1, 2])[1] = 1 then {target} end if; return new; end",
        ),
        (
            "opaque_delimiter_decoys_before_guard",
            "begin perform '((( [[['; perform \"col)]]\";"
            " perform $decoy$)]( [$decoy$;"
            " -- ((( [[[ ))) ]]]\n"
            " /* ((( /* [[[ */ ))) */"
            f" if {bound} then {target} end if; return new; end",
        ),
        (
            "opaque_delimiter_decoys_inside_guard_condition",
            f"begin if ({bound}) and assignment_kind = '((( ]' then"
            f" {target} end if; return new; end",
        ),
        (
            "ordinary_statement_terminated_before_guard",
            f"begin perform 1; if {bound} then {target} end if; return new; end",
        ),
        (
            "ordinary_statement_terminated_after_guard",
            f"begin if {bound} then {target} end if; perform 1; return new; end",
        ),
        (
            "terminated_ordinary_at_outer_end",
            f"begin if {bound} then {target} end if; return new; perform 1; end",
        ),
        (
            "terminated_ordinary_at_outer_end_with_terminal_semicolon",
            f"begin if {bound} then {target} end if; return new; perform 1; end;",
        ),
        (
            "terminated_ordinary_with_trailing_comment",
            f"begin if {bound} then {target} end if; return new; perform 1; end; -- trailing",
        ),
    )


def _assert_malformed_lexical_fails_closed(
    *, message: str, tokens: tuple[str, ...], harness_prefix: str, bound: str
) -> None:
    """Require malformed lexical tails to surface as unsupported PL/pgSQL."""
    for label, body in _malformed_lexical_corpus(message=message, bound=bound):
        try:
            _rejection_binds_tokens(body, message, tokens)
        except _UnsupportedPlpgsql:
            continue
        _fail(harness_prefix + "_MALFORMED_LEXICAL_NOT_REJECTED: " + label)


def _assert_malformed_delimiters_fail_closed(
    *, message: str, tokens: tuple[str, ...], harness_prefix: str, bound: str
) -> None:
    """Require unmatched executable ()/[] delimiters to surface as unsupported."""
    for label, body in _malformed_delimiter_corpus(message=message, bound=bound):
        try:
            approved = _rejection_binds_tokens(body, message, tokens)
        except _UnsupportedPlpgsql:
            continue
        if approved:
            _fail(harness_prefix + "_MALFORMED_DELIMITER_FALSE_PASS: " + label)
        _fail(harness_prefix + "_MALFORMED_DELIMITER_NOT_REJECTED: " + label)


def _assert_malformed_statement_boundaries_fail_closed(
    *, message: str, tokens: tuple[str, ...], harness_prefix: str, bound: str
) -> None:
    """Require malformed statement boundaries to surface as unsupported PL/pgSQL."""
    for label, body in _malformed_statement_boundary_corpus(message=message, bound=bound):
        try:
            _rejection_binds_tokens(body, message, tokens)
        except _UnsupportedPlpgsql:
            continue
        _fail(harness_prefix + "_MALFORMED_STATEMENT_BOUNDARY_NOT_REJECTED: " + label)


def _assert_matcher_is_control_flow_bound(
    *,
    message: str,
    tokens: tuple[str, ...],
    harness_prefix: str,
    bound: str,
    unbound: str,
    noop: str,
    literal: str,
    other: str,
) -> None:
    """Prove the matcher rejects every adversarial decoy and accepts every
    canonical guard shape before any product SQL is inspected."""
    _assert_malformed_lexical_fails_closed(
        message=message,
        tokens=tokens,
        harness_prefix=harness_prefix,
        bound=bound,
    )
    _assert_malformed_delimiters_fail_closed(
        message=message,
        tokens=tokens,
        harness_prefix=harness_prefix,
        bound=bound,
    )
    _assert_malformed_statement_boundaries_fail_closed(
        message=message,
        tokens=tokens,
        harness_prefix=harness_prefix,
        bound=bound,
    )
    for label, body in _negative_corpus(
        message=message,
        bound=bound,
        unbound=unbound,
        noop=noop,
        literal=literal,
        other=other,
    ):
        if _binds_or_harness_fail(body, message, tokens, harness_prefix):
            _fail(harness_prefix + "_DECOY_FALSE_PASS: " + label)
    for label, body in _positive_corpus(message=message, bound=bound, unbound=unbound):
        if not _binds_or_harness_fail(body, message, tokens, harness_prefix):
            _fail(harness_prefix + "_POSITIVE_CONTROL_FALSE_FAIL: " + label)


_POSITION_MESSAGE = "care_assignment_position_orphan_forbidden"
_QUALIFICATION_MESSAGE = "care_assignment_qualification_orphan_forbidden"
_CONTRACT_MESSAGE = "care_assignment_contract_orphan_forbidden"

_POSITION_TOKENS = ("old.staff_id", "old.employment_id")
_QUALIFICATION_TOKENS = ("old.staff_id", "old.employment_id", "old.service_type_id")
_CONTRACT_TOKENS = ("service_type_id", "staff_service_qualification_period")

_POSITION_FIXTURE = {
    "bound": (
        "exists (select 1 from erp.care_assignment a where a.staff_id = old.staff_id"
        " and a.employment_id = old.employment_id and a.invalidated_at_utc is null)"
    ),
    "unbound": (
        "exists (select 1 from erp.care_assignment a where a.staff_id = new.staff_id"
        " and a.employment_id = new.employment_id)"
    ),
    "noop": "perform old.staff_id; perform old.employment_id;",
    "literal": "old.staff_id old.employment_id",
    "other": (
        "begin if exists (select 1 from erp.care_assignment a"
        " where a.staff_id = old.staff_id and a.employment_id = old.employment_id)"
        " then raise exception using errcode = '23514',"
        " message = 'care_assignment_staff_ineligible'; end if; return new; end"
    ),
}
_QUALIFICATION_FIXTURE = {
    "bound": (
        "exists (select 1 from erp.care_assignment a join erp.recipient_contract c"
        " on c.id = a.recipient_contract_id where a.staff_id = old.staff_id"
        " and a.employment_id = old.employment_id"
        " and c.service_type_id = old.service_type_id)"
    ),
    "unbound": (
        "exists (select 1 from erp.care_assignment a join erp.recipient_contract c"
        " on c.id = a.recipient_contract_id where a.staff_id = new.staff_id"
        " and a.employment_id = new.employment_id"
        " and c.service_type_id = new.service_type_id)"
    ),
    "noop": "perform old.staff_id; perform old.employment_id; perform old.service_type_id;",
    "literal": "old.staff_id old.employment_id old.service_type_id",
    "other": (
        "begin if exists (select 1 from erp.care_assignment a"
        " where a.staff_id = old.staff_id and a.employment_id = old.employment_id"
        " and old.service_type_id is not null) then raise exception using"
        " errcode = '23514', message = 'care_assignment_staff_ineligible';"
        " end if; return new; end"
    ),
}
_CONTRACT_FIXTURE = {
    "bound": (
        "exists (select 1 from erp.care_assignment a where"
        " a.recipient_contract_id = new.id and a.invalidated_at_utc is null"
        " and not (a.assignment_period <@ coalesce((select"
        " range_agg(q.qualification_period) from"
        " erp.staff_service_qualification_period q where q.staff_id = a.staff_id"
        " and q.employment_id = a.employment_id"
        " and q.service_type_id = new.service_type_id), '{}'::datemultirange)))"
    ),
    "unbound": (
        "exists (select 1 from erp.care_assignment a where"
        " a.recipient_contract_id = new.id and a.invalidated_at_utc is null"
        " and not (a.assignment_period <@ new.contract_period))"
    ),
    "noop": (
        "perform 1 from erp.staff_service_qualification_period q"
        " where q.service_type_id = new.service_type_id;"
    ),
    "literal": "service_type_id staff_service_qualification_period",
    "other": (
        "begin if exists (select 1 from erp.staff_service_qualification_period q"
        " where q.service_type_id = new.service_type_id) then raise exception using"
        " errcode = '23514', message = 'care_assignment_staff_ineligible';"
        " end if; return new; end"
    ),
}


# --- Offline binding of the product guard bodies -----------------------------

_OFFLINE_FUNCTION_PATTERN = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\s+"
    r"(?P<name>[a-z_][a-z0-9_.]*)\s*\(\s*\)"
    r"(?P<header>[^'$]*?)(?P<tag>\$(?:[a-z_][a-z0-9_]*)?\$)"
    r"(?P<body>.*?)(?P=tag)(?P<trailer>[^'$]*?)\s*;",
    flags=re.DOTALL,
)


@functools.lru_cache(maxsize=1)
def _offline_reverse_guard_bodies() -> dict[str, str]:
    """Return {function_name: body} bound from the no-connect offline SQL.

    Binding mirrors test_w1e_02 so a boundary can never be sealed by text that
    belongs to a differently named function or to a non-function statement.
    """
    _require_w1e_revision()
    synthetic_env = {
        **os.environ,
        "SSWCENTER_DATABASE_URL": (
            "postgresql+psycopg://test_red:test_red@127.0.0.1:5432/sswcenter_w1e_red"
        ),
        "SSWCENTER_ENVIRONMENT": "development",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", W1E_REVISION, "--sql"],
            cwd=BACKEND_ROOT,
            env=synthetic_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail("W1E_REVERSE_HARNESS_OFFLINE_SQL_MISSING: " + type(exc).__name__)
    if result.returncode != 0:
        _fail("W1E_REVERSE_HARNESS_OFFLINE_SQL_FAILED: exit " + str(result.returncode))
    section = _offline_w1e_section(result.stdout)
    ddl_scan = _mask_sql_literals(section, dollar_quoted=True)
    bodies: dict[str, str] = {}
    for start, stop in _top_level_sql_statement_spans(ddl_scan):
        match = _OFFLINE_FUNCTION_PATTERN.fullmatch(section[start:stop].strip())
        if match is None:
            continue
        name = match.group("name")
        if name in bodies:
            _fail("W1E_REVERSE_HARNESS_DUPLICATE_FUNCTION_BODY: " + name)
        bodies[name] = match.group("body")
    return bodies


def _reverse_guard_body(function_name: str, harness_prefix: str) -> str:
    body = _offline_reverse_guard_bodies().get(function_name)
    if body is None:
        _fail(harness_prefix + "_GUARD_BODY_MISSING: " + function_name)
    return body


def test_w1e_04_position_reverse_guard_preserves_old_key() -> None:
    """Product RED: a CARE_WORKER position reparent must re-check the OLD key.

    Reparenting staff_id/employment_id can orphan an active GENERAL assignment
    still bound to the OLD (staff_id, employment_id) key. A reachable RAISE of
    CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN must be controlled by a branch
    ancestry that references the OLD position key, not only the NEW one.
    """
    harness_prefix = "W1E_REVERSE_HARNESS_POSITION"
    _assert_matcher_is_control_flow_bound(
        message=_POSITION_MESSAGE,
        tokens=_POSITION_TOKENS,
        harness_prefix=harness_prefix,
        **_POSITION_FIXTURE,
    )
    body = _reverse_guard_body(
        "erp.fn_staff_position_care_assignment_reverse_guard", harness_prefix
    )
    if not _binds_or_harness_fail(body, _POSITION_MESSAGE, _POSITION_TOKENS, harness_prefix):
        _fail("W1E_REVERSE_POSITION_OLD_KEY_UNSEALED")


def test_w1e_05_qualification_reverse_guard_preserves_old_key() -> None:
    """Product RED: a qualification rekey must re-check the OLD key.

    Changing staff_id/employment_id/service_type_id can orphan an active GENERAL
    assignment whose coverage depended on the OLD qualification key. A reachable
    RAISE of CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN must be controlled
    by a branch ancestry that references the OLD
    (staff_id, employment_id, service_type_id) key, not only the NEW one.
    """
    harness_prefix = "W1E_REVERSE_HARNESS_QUALIFICATION"
    _assert_matcher_is_control_flow_bound(
        message=_QUALIFICATION_MESSAGE,
        tokens=_QUALIFICATION_TOKENS,
        harness_prefix=harness_prefix,
        **_QUALIFICATION_FIXTURE,
    )
    body = _reverse_guard_body(
        "erp.fn_staff_service_qualification_assignment_reverse_guard", harness_prefix
    )
    if not _binds_or_harness_fail(
        body, _QUALIFICATION_MESSAGE, _QUALIFICATION_TOKENS, harness_prefix
    ):
        _fail("W1E_REVERSE_QUALIFICATION_OLD_KEY_UNSEALED")


def test_w1e_06_contract_service_transition_rechecks_qualification() -> None:
    """Product RED: a contract service-type transition must recheck coverage.

    When recipient_contract.service_type_id changes, existing GENERAL
    assignments may lose continuous qualification coverage for the NEW service.
    A reachable RAISE of CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN must be
    controlled by a branch ancestry that references the service_type_id
    dimension and re-checks staff_service_qualification_period coverage, not
    only period containment.
    """
    harness_prefix = "W1E_REVERSE_HARNESS_CONTRACT"
    _assert_matcher_is_control_flow_bound(
        message=_CONTRACT_MESSAGE,
        tokens=_CONTRACT_TOKENS,
        harness_prefix=harness_prefix,
        **_CONTRACT_FIXTURE,
    )
    body = _reverse_guard_body("erp.fn_recipient_contract_assignment_reverse_guard", harness_prefix)
    if not _binds_or_harness_fail(body, _CONTRACT_MESSAGE, _CONTRACT_TOKENS, harness_prefix):
        _fail("W1E_REVERSE_CONTRACT_SERVICE_TYPE_UNSEALED")
