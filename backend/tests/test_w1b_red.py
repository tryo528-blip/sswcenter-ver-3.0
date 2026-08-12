from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Table, create_engine, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ALEMBIC_ROOT = BACKEND_ROOT / "alembic"
MIGRATIONS_ROOT = ALEMBIC_ROOT / "versions"
BASIS_SHA = "1314b4ce41de5dd55f4996b409a52ed7e24bfbca"

EXISTING_REVISIONS: tuple[tuple[str, str | None], ...] = (
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
)
W1A_HEAD = EXISTING_REVISIONS[-1][0]

W1B_TABLE_NAMES = (
    "recipient",
    "recipient_legacy_mapping",
    "recipient_guardian",
    "recipient_guardian_primary_period",
    "recipient_payer_snapshot",
)
RECIPIENT_COLLECTION_PATH = "/api/v1/recipients"
RECIPIENT_ITEM_PATTERN = re.compile(r"^/api/v1/recipients/\{[^}/]+\}$")
NESTED_OPERATIONS: dict[str, set[str]] = {
    "/api/v1/recipients/{recipient_id}/guardians": {"get", "post"},
    "/api/v1/recipients/{recipient_id}/primary-guardian-periods": {"get", "post"},
    "/api/v1/recipients/{recipient_id}/payer-snapshots": {"get", "post"},
}
NESTED_ITEM_OPERATIONS: dict[str, set[str]] = {
    "/api/v1/recipients/{recipient_id}/guardians": {"get", "patch"},
    "/api/v1/recipients/{recipient_id}/primary-guardian-periods": {"get"},
    "/api/v1/recipients/{recipient_id}/payer-snapshots": {"get"},
}
HISTORY_ACTIONS = ("invalidate", "replacements")
HISTORY_BASE_PATHS = (
    "/api/v1/recipients/{recipient_id}/primary-guardian-periods",
    "/api/v1/recipients/{recipient_id}/payer-snapshots",
)

SYNTHETIC_NAME = "TEST_W1B_RECIPIENT_CANARY"
SYNTHETIC_SOURCE = "TEST_W1B_SOURCE"
SYNTHETIC_LEGACY_KEY = "TEST_W1B_LEGACY_001"
SYNTHETIC_ATTACHMENT_KEY = "TEST_W1B_ATTACHMENT_001"
SYNTHETIC_BIRTH_DATE = date(2000, 1, 1)
SYNTHETIC_SOURCE_MEMO = "TEST_W1B_SOURCE_MEMO_CANARY"
SYNTHETIC_POSTAL_CODE = "TEST_W1B_POSTAL_001"
SYNTHETIC_ADDRESS = "TEST_W1B_ADDRESS_CANARY"
SYNTHETIC_HOME_PHONE = "TEST_W1B_HOME_PHONE_CANARY"
SYNTHETIC_MOBILE_PHONE = "TEST_W1B_MOBILE_PHONE_CANARY"
SYNTHETIC_GUARDIAN_PHONE = "TEST_W1B_GUARDIAN_PHONE_CANARY"
SYNTHETIC_GUARDIAN_ADDRESS = "TEST_W1B_GUARDIAN_ADDRESS_CANARY"
SYNTHETIC_GUARDIAN_RELATIONSHIP = "TEST_W1B_GUARDIAN_RELATIONSHIP_CANARY"
SYNTHETIC_PAYER_PHONE = "TEST_W1B_PAYER_PHONE_CANARY"
SYNTHETIC_PAYER_ADDRESS = "TEST_W1B_PAYER_ADDRESS_CANARY"
SYNTHETIC_PAYER_RELATIONSHIP = "TEST_W1B_PAYER_RELATIONSHIP_CANARY"
SYNTHETIC_500_NAME = "TEST_W1B_500_NAME_CANARY"
SYNTHETIC_500_ADDRESS = "TEST_W1B_500_ADDRESS_CANARY"
SYNTHETIC_500_HOME_PHONE = "TEST_W1B_500_HOME_PHONE_CANARY"
SYNTHETIC_500_MOBILE_PHONE = "TEST_W1B_500_MOBILE_PHONE_CANARY"
UNSAFE_RESPONSE_TERMS = (
    "integrityerror",
    "sqlalchemy",
    "psycopg",
    "traceback",
    "stack",
    "stack trace",
    "select ",
    "insert ",
    "update ",
    "delete ",
    "syntax error",
    "internal server error",
    "constraint",
    "exclusion",
    "duplicate key",
    "violates",
    "sqlstate",
    "psycopg2",
    "driver",
)
_AUDIT_UNSET = object()


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _script_directory() -> ScriptDirectory:
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ALEMBIC_ROOT))
        return ScriptDirectory.from_config(config)
    except Exception:
        _fail("W1B_MIGRATION_GRAPH_HARNESS_MISSING: Alembic ScriptDirectory could not load")


def _all_revisions(script: ScriptDirectory) -> list[Any]:
    try:
        revisions = list(script.walk_revisions())
    except Exception:
        _fail("W1B_MIGRATION_GRAPH_HARNESS_MISSING: Alembic revision graph could not be walked")
    return [revision for revision in revisions if getattr(revision, "revision", None)]


def _down_revision_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _basis_bytes(relative_path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "show", f"{BASIS_SHA}:{relative_path}"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("W1B_MIGRATION_BASIS_HARNESS_MISSING: basis revision cannot be read")
    if result.returncode != 0:
        _fail("W1B_MIGRATION_BASIS_HARNESS_MISSING: basis migration file is absent")
    return result.stdout


def _verify_existing_migration_snapshot(revision: Any) -> None:
    path = Path(str(revision.path)).resolve()
    try:
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        path.relative_to(MIGRATIONS_ROOT.resolve())
    except ValueError:
        _fail("W1B_MIGRATION_GRAPH_INVALID: revision path escapes the migrations directory")
    current_hash = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    basis_hash = hashlib.sha256(_basis_bytes(relative_path)).hexdigest()
    if current_hash != basis_hash:
        _fail("W1B_EXISTING_MIGRATION_MODIFIED: basis migration changed: " + relative_path)


def _require_w1b_revision() -> tuple[ScriptDirectory, Any, frozenset[str]]:
    script = _script_directory()
    revisions = _all_revisions(script)
    revision_by_id = {str(revision.revision): revision for revision in revisions}
    existing_ids = {revision_id for revision_id, _ in EXISTING_REVISIONS}

    for revision_id, expected_down_revision in EXISTING_REVISIONS:
        revision = revision_by_id.get(revision_id)
        if revision is None:
            _fail("W1B_MIGRATION_BASE_CHAIN_MISSING: existing 0001~0008 chain is incomplete")
        actual_down_revision = _down_revision_ids(revision.down_revision)
        expected_down = () if expected_down_revision is None else (expected_down_revision,)
        if actual_down_revision != expected_down:
            _fail("W1B_MIGRATION_BASE_CHAIN_INVALID: existing down_revision chain changed")
        _verify_existing_migration_snapshot(revision)

    w1b_revisions = [
        revision
        for revision in revisions
        if W1A_HEAD in _down_revision_ids(revision.down_revision)
        and str(revision.revision) not in existing_ids
    ]
    if not w1b_revisions:
        _fail(
            "W1B_MIGRATION_MISSING: exactly one new W1B revision after " + W1A_HEAD + " is required"
        )
    if len(w1b_revisions) != 1:
        _fail("W1B_MIGRATION_GRAPH_INVALID: more than one W1B revision follows 0008")

    w1b_revision = w1b_revisions[0]
    if _down_revision_ids(w1b_revision.down_revision) != (W1A_HEAD,):
        _fail("W1B_MIGRATION_GRAPH_INVALID: W1B direct child is not a single 0008 child")

    children: dict[str, list[Any]] = {}
    for revision in revisions:
        for parent_id in _down_revision_ids(revision.down_revision):
            children.setdefault(parent_id, []).append(revision)

    chain_ids: list[str] = []
    current_id = str(w1b_revision.revision)
    while True:
        if current_id in chain_ids:
            _fail("W1B_MIGRATION_GRAPH_INVALID: W1B descendant chain contains a cycle")
        chain_ids.append(current_id)
        descendants = children.get(current_id, [])
        if len(descendants) > 1:
            _fail("W1B_MIGRATION_GRAPH_INVALID: W1B descendants branch")
        if not descendants:
            break
        descendant = descendants[0]
        if _down_revision_ids(descendant.down_revision) != (current_id,):
            _fail("W1B_MIGRATION_GRAPH_INVALID: W1B descendant is a merge")
        current_id = str(descendant.revision)

    try:
        heads = tuple(str(head) for head in script.get_heads())
    except Exception:
        _fail("W1B_MIGRATION_GRAPH_HARNESS_MISSING: Alembic heads could not be resolved")
    if len(heads) != 1 or heads[0] != chain_ids[-1]:
        _fail("W1B_MIGRATION_SINGLE_HEAD_MISSING: sole head must be W1B or its serial descendant")
    return script, w1b_revision, frozenset(chain_ids)


def _run_offline_upgrade(w1b_revision: Any) -> None:
    synthetic_env = os.environ.copy()
    synthetic_env.update(
        {
            "SSWCENTER_DATABASE_URL": (
                "postgresql+psycopg://test_red:test_red@127.0.0.1:5432/sswcenter_red_test"
            ),
            "SSWCENTER_ENVIRONMENT": "development",
        }
    )
    required_tables = (
        "create table erp.recipient",
        "create table erp.recipient_legacy_mapping",
        "create table erp.recipient_guardian",
        "create table erp.recipient_guardian_primary_period",
        "create table erp.recipient_payer_snapshot",
    )

    def offline_sql(target: str, marker: str) -> str:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", target, "--sql"],
                cwd=BACKEND_ROOT,
                env=synthetic_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail(marker + ": offline upgrade command could not run")
        if result.returncode != 0:
            _fail(marker + ": offline upgrade SQL failed")
        return (result.stdout + result.stderr).lower()

    direct_marker = "W1B_ALEMBIC_OFFLINE_DIRECT_CHILD_MISSING"
    direct_sql = offline_sql(str(w1b_revision.revision), direct_marker)
    if any(fragment not in direct_sql for fragment in required_tables):
        _fail(direct_marker + ": W1B direct-child SQL omits a W1B table")
    if str(w1b_revision.revision).lower() not in direct_sql:
        _fail(direct_marker + ": direct-child SQL does not identify the W1B revision")

    head_marker = "W1B_ALEMBIC_OFFLINE_HEAD_COMPATIBILITY_MISSING"
    head_sql = offline_sql("head", head_marker)
    if any(fragment not in head_sql for fragment in required_tables):
        _fail(head_marker + ": head SQL omits a W1B table")


def _fresh_pg_executable(name: str, marker: str) -> Path:
    configured_root = os.environ.get("SSWCENTER_POSTGRES_BIN")
    roots = [] if not configured_root else [Path(configured_root)]
    roots.extend(
        [
            Path(r"C:\Program Files\PostgreSQL\17\bin"),
            Path(r"C:\Program Files\PostgreSQL\16\bin"),
        ]
    )
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            return candidate
    discovered = shutil.which(name)
    if discovered:
        return Path(discovered)
    _fail(marker + ": PostgreSQL executable is absent: " + name)


def _run_fresh_pg_command(
    executable: Path, arguments: list[str], marker: str, *, timeout: int = 90
) -> None:
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            cwd=REPO_ROOT,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail(marker + ": isolated PostgreSQL command could not run")
    if result.returncode != 0:
        _fail(marker + ": isolated PostgreSQL command failed")


def _fresh_w1b_catalog_contract(engine: Engine, expected_revision: str | None, marker: str) -> None:
    try:
        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if expected_revision is not None and current_revision != expected_revision:
                _fail(marker + ": exact direct W1B revision was not applied")
            missing_tables = [
                name
                for name in W1B_TABLE_NAMES
                if connection.execute(
                    text("SELECT to_regclass(:qualified) IS NOT NULL"),
                    {"qualified": f"erp.{name}"},
                ).scalar()
                is not True
            ]
            if missing_tables:
                _fail(marker + ": W1B table catalog is incomplete")
            column_rows = (
                connection.execute(
                    text(
                        """
                    SELECT table_name, column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'erp'
                      AND table_name = ANY(:table_names)
                    """
                    ),
                    {"table_names": list(W1B_TABLE_NAMES)},
                )
                .mappings()
                .all()
            )
            columns = {
                str(row["table_name"]): {
                    str(item["column_name"]): str(item["is_nullable"])
                    for item in column_rows
                    if item["table_name"] == row["table_name"]
                }
                for row in column_rows
            }
            required_columns = {
                "recipient": {
                    "id",
                    "name",
                    "birth_date",
                    "sex_code",
                    "recipient_no",
                    "memo",
                    "postal_code",
                    "address",
                    "home_phone",
                    "mobile_phone",
                    "row_version",
                },
                "recipient_legacy_mapping": {
                    "id",
                    "source_system_code",
                    "legacy_recipient_key",
                    "legacy_attachment_key",
                    "recipient_id",
                    "invalidated_at_utc",
                    "replacement_recipient_legacy_mapping_id",
                    "row_version",
                },
                "recipient_guardian": {
                    "id",
                    "recipient_id",
                    "name",
                    "phone",
                    "address",
                    "relationship_text",
                    "row_version",
                },
                "recipient_guardian_primary_period": {
                    "id",
                    "recipient_id",
                    "guardian_id",
                    "start_date",
                    "end_date",
                    "invalidated_at_utc",
                    "row_version",
                },
                "recipient_payer_snapshot": {
                    "id",
                    "recipient_id",
                    "name",
                    "phone",
                    "address",
                    "relationship_text",
                    "start_date",
                    "end_date",
                    "invalidated_at_utc",
                    "row_version",
                },
            }
            for table_name, names in required_columns.items():
                actual = columns.get(table_name, {})
                missing = sorted(names - set(actual))
                if missing:
                    _fail(
                        marker + ": missing catalog columns " + table_name + "." + ",".join(missing)
                    )
            nullable_columns = {
                "recipient": {
                    "recipient_no",
                    "postal_code",
                    "address",
                    "home_phone",
                    "mobile_phone",
                },
                "recipient_legacy_mapping": {
                    "legacy_recipient_key",
                    "legacy_attachment_key",
                    "invalidated_at_utc",
                    "replacement_recipient_legacy_mapping_id",
                },
                "recipient_guardian": {
                    "phone",
                    "address",
                    "relationship_text",
                },
                "recipient_guardian_primary_period": {
                    "end_date",
                    "invalidated_at_utc",
                },
                "recipient_payer_snapshot": {
                    "phone",
                    "address",
                    "relationship_text",
                    "end_date",
                    "invalidated_at_utc",
                },
            }
            for table_name, names in nullable_columns.items():
                not_nullable = sorted(
                    name for name in names if columns[table_name].get(name) != "YES"
                )
                if not_nullable:
                    _fail(marker + ": nullable catalog contract is broken: " + table_name)
            not_nullable_columns = {
                "recipient": {"name", "birth_date", "sex_code"},
                "recipient_legacy_mapping": {"source_system_code", "recipient_id"},
                "recipient_guardian": {"recipient_id", "name"},
                "recipient_guardian_primary_period": {
                    "recipient_id",
                    "guardian_id",
                    "start_date",
                },
                "recipient_payer_snapshot": {"recipient_id", "name", "start_date"},
            }
            for table_name, names in not_nullable_columns.items():
                nullable = sorted(name for name in names if columns[table_name].get(name) != "NO")
                if nullable:
                    _fail(marker + ": NOT NULL catalog contract is broken: " + table_name)
            for table_name in (
                "recipient_guardian_primary_period",
                "recipient_payer_snapshot",
            ):
                replacement_columns = [
                    name
                    for name in columns[table_name]
                    if "replacement" in name.lower() and name.lower().endswith("_id")
                ]
                if len(replacement_columns) != 1:
                    _fail(
                        marker + ": replacement linkage catalog contract is absent: " + table_name
                    )
                if columns[table_name][replacement_columns[0]] != "YES":
                    _fail(marker + ": replacement linkage must be nullable: " + table_name)

            fk_rows = (
                connection.execute(
                    text(
                        """
                    SELECT rel.relname AS table_name,
                           pg_get_constraintdef(c.oid, true) AS definition
                    FROM pg_constraint AS c
                    JOIN pg_class AS rel ON rel.oid = c.conrelid
                    JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
                    WHERE namespace.nspname = 'erp'
                      AND c.contype = 'f'
                    """
                    )
                )
                .mappings()
                .all()
            )
            flat_fks = {
                str(row["table_name"]): [
                    re.sub(r'["\s]+', "", str(item["definition"] or "").lower())
                    for item in fk_rows
                    if item["table_name"] == row["table_name"]
                ]
                for row in fk_rows
            }
            for table_name in (
                "recipient_guardian",
                "recipient_guardian_primary_period",
                "recipient_payer_snapshot",
            ):
                if not any(
                    "foreignkey(recipient_id)referenceserp.recipient(id)" in definition
                    for definition in flat_fks.get(table_name, [])
                ):
                    _fail(marker + ": recipient FK catalog contract is absent: " + table_name)
            if not any(
                "foreignkey(recipient_id,guardian_id)referenceserp.recipient_guardian(recipient_id,id)"
                in definition
                for definition in flat_fks.get("recipient_guardian_primary_period", [])
            ):
                _fail(marker + ": canonical composite guardian FK catalog contract is absent")

            check_rows = (
                connection.execute(
                    text(
                        """
                    SELECT rel.relname AS table_name,
                           pg_get_constraintdef(c.oid, true) AS definition
                    FROM pg_constraint AS c
                    JOIN pg_class AS rel ON rel.oid = c.conrelid
                    JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
                    WHERE namespace.nspname = 'erp'
                      AND c.contype = 'c'
                    """
                    )
                )
                .mappings()
                .all()
            )
            checks = {
                str(row["table_name"]): [
                    re.sub(r"\s+", " ", str(item["definition"] or "").lower()).strip()
                    for item in check_rows
                    if item["table_name"] == row["table_name"]
                ]
                for row in check_rows
            }
            for table_name in (
                "recipient_guardian_primary_period",
                "recipient_payer_snapshot",
            ):
                if not any(
                    "start_date" in definition
                    and "end_date" in definition
                    and ("<=" in definition or "end_date is null" in definition)
                    for definition in checks.get(table_name, [])
                ):
                    _fail(marker + ": period range CHECK catalog contract is absent: " + table_name)
            if not any(
                "sex_code" in definition
                and all(value in definition for value in ("male", "female", "test"))
                for definition in checks.get("recipient", [])
            ):
                _fail(marker + ": recipient sex_code CHECK catalog contract is absent")

            unique_rows = (
                connection.execute(
                    text(
                        """
                    SELECT rel.relname AS table_name,
                           pg_get_indexdef(idx.indexrelid) AS definition
                    FROM pg_index AS idx
                    JOIN pg_class AS rel ON rel.oid = idx.indrelid
                    JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
                    WHERE namespace.nspname = 'erp'
                      AND idx.indisunique
                    """
                    )
                )
                .mappings()
                .all()
            )
            unique_definitions = {
                str(row["table_name"]): [
                    str(item["definition"] or "").lower()
                    for item in unique_rows
                    if item["table_name"] == row["table_name"]
                ]
                for row in unique_rows
            }
            if not any(
                "recipient_no" in definition
                for definition in unique_definitions.get("recipient", [])
            ):
                _fail(marker + ": recipient_no unique catalog contract is absent")
            mapping_unique_definitions = unique_definitions.get("recipient_legacy_mapping", [])
            if not any(
                "source_system_code" in definition
                and "legacy_recipient_key" in definition
                and "where" in definition
                and "invalidated_at_utc" in definition
                and "is null" in definition
                for definition in mapping_unique_definitions
            ):
                _fail(marker + ": legacy mapping unique catalog contract is absent")
            if not any(
                "source_system_code" in definition
                and "legacy_attachment_key" in definition
                and "where" in definition
                and "invalidated_at_utc" in definition
                and "is null" in definition
                for definition in mapping_unique_definitions
            ):
                _fail(marker + ": legacy attachment active unique catalog contract is absent")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail(marker + ": fresh PostgreSQL catalog inspection failed")

    _period_exclusion_catalog_names(
        engine, "recipient_guardian_primary_period", marker + ": primary exclusion"
    )
    _period_exclusion_catalog_names(
        engine, "recipient_payer_snapshot", marker + ": payer exclusion"
    )
    try:
        with engine.connect() as connection:
            trigger_rows = (
                connection.execute(
                    text(
                        """
                    SELECT pg_get_triggerdef(t.oid, true) AS trigger_definition,
                           pg_get_functiondef(p.oid) AS function_definition
                    FROM pg_trigger AS t
                    JOIN pg_class AS rel ON rel.oid = t.tgrelid
                    JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
                    JOIN pg_proc AS p ON p.oid = t.tgfoid
                    WHERE namespace.nspname = 'erp'
                      AND rel.relname = 'recipient'
                      AND NOT t.tgisinternal
                    """
                    )
                )
                .mappings()
                .all()
            )
    except SQLAlchemyError:
        _fail(marker + ": trigger catalog inspection failed")
    if not any(
        all(
            term in str(row["function_definition"] or "").lower()
            for term in ("old.recipient_no", "new.recipient_no", "is distinct from", "raise")
        )
        for row in trigger_rows
    ):
        _fail(marker + ": recipient_no immutable trigger catalog contract is absent")
    _assert_no_payer_autosync_triggers(engine, marker + ": autosync")


def _run_fresh_postgres_catalog(w1b_revision: Any, allowed_revisions: frozenset[str]) -> None:
    marker = "W1B_FRESH_PG_CATALOG_HARNESS_MISSING"
    if os.environ.get("SSWCENTER_POSTGRES_TEST") != "1":
        _fail(marker + ": isolated PostgreSQL harness is not enabled")
    source_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not source_url:
        _fail(marker + ": source PostgreSQL URL is not configured")
    try:
        source_backend = make_url(source_url).get_backend_name()
    except Exception:
        _fail(marker + ": source PostgreSQL URL is invalid")
    if source_backend != "postgresql":
        _fail(marker + ": source database is not PostgreSQL")

    initdb = _fresh_pg_executable("initdb.exe", marker)
    pg_ctl = _fresh_pg_executable("pg_ctl.exe", marker)
    createdb = _fresh_pg_executable("createdb.exe", marker)
    dropdb = _fresh_pg_executable("dropdb.exe", marker)
    temp_root = Path(tempfile.gettempdir()).resolve()
    cluster_root = temp_root / f"sswcenter-w1b-red-pg-{uuid4().hex}"
    if not cluster_root.is_relative_to(temp_root) or cluster_root.exists():
        _fail(marker + ": test-only PostgreSQL cluster path is unsafe")
    cluster_root.mkdir()
    data_directory = cluster_root / "data"
    data_directory.mkdir()
    log_file = cluster_root / "postgres.log"
    runtime_root = cluster_root / "sswcenter-w1b-red-runtime"
    runtime_root.mkdir()
    database_name = f"sswcenter_w1b_red_{uuid4().hex}_test"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socket_probe:
            socket_probe.bind(("127.0.0.1", 0))
            port = int(socket_probe.getsockname()[1])
    except OSError:
        try:
            shutil.rmtree(cluster_root)
        except OSError:
            _fail(marker + ": test-only cluster cleanup failed after port setup failure")
        _fail(marker + ": isolated PostgreSQL port could not be reserved")

    server_started = False
    database_created = False
    engine: Engine | None = None
    cleanup_errors: list[str] = []
    try:
        _run_fresh_pg_command(
            initdb,
            [
                "--pgdata",
                str(data_directory),
                "--username",
                "postgres",
                "--auth=trust",
                "--encoding=UTF8",
                "--locale=C",
            ],
            marker,
        )
        _run_fresh_pg_command(
            pg_ctl,
            [
                "--pgdata",
                str(data_directory),
                "--log",
                str(log_file),
                "--options",
                f"-h 127.0.0.1 -p {port}",
                "start",
                "--wait",
            ],
            marker,
        )
        server_started = True
        _run_fresh_pg_command(
            createdb,
            ["-h", "127.0.0.1", "-p", str(port), "-U", "postgres", database_name],
            marker,
        )
        database_created = True
        database_url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/{database_name}"
        fresh_env = os.environ.copy()
        fresh_env.update(
            {
                "SSWCENTER_DATABASE_URL": database_url,
                "SSWCENTER_ENVIRONMENT": "test",
                "SSWCENTER_POSTGRES_TEST": "1",
                "SSWCENTER_DATA_ROOT": str(runtime_root),
            }
        )
        try:
            direct_upgrade = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    "alembic.ini",
                    "upgrade",
                    str(w1b_revision.revision),
                ],
                cwd=BACKEND_ROOT,
                env=fresh_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail("W1B_FRESH_PG_DIRECT_UPGRADE_MISSING: direct revision upgrade could not run")
        if direct_upgrade.returncode != 0:
            _fail("W1B_FRESH_PG_DIRECT_UPGRADE_MISSING: direct revision upgrade failed")
        engine = create_engine(database_url, pool_pre_ping=True)
        _fresh_w1b_catalog_contract(
            engine,
            str(w1b_revision.revision),
            "W1B_FRESH_PG_DIRECT_CATALOG_MISSING",
        )
        try:
            head_upgrade = subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                cwd=BACKEND_ROOT,
                env=fresh_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            _fail("W1B_FRESH_PG_HEAD_UPGRADE_MISSING: head upgrade could not run")
        if head_upgrade.returncode != 0:
            _fail("W1B_FRESH_PG_HEAD_UPGRADE_MISSING: head upgrade failed")
        _require_db_revision(engine, allowed_revisions)
        _fresh_w1b_catalog_contract(engine, None, "W1B_FRESH_PG_HEAD_CATALOG_MISSING")
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            try:
                _run_fresh_pg_command(
                    dropdb,
                    [
                        "--if-exists",
                        "--force",
                        "-h",
                        "127.0.0.1",
                        "-p",
                        str(port),
                        "-U",
                        "postgres",
                        database_name,
                    ],
                    marker,
                )
            except pytest.fail.Exception:
                cleanup_errors.append("test database cleanup failed")
        if server_started:
            try:
                _run_fresh_pg_command(
                    pg_ctl,
                    [
                        "--pgdata",
                        str(data_directory),
                        "stop",
                        "--mode",
                        "fast",
                        "--wait",
                    ],
                    marker,
                )
            except pytest.fail.Exception:
                cleanup_errors.append("test cluster shutdown failed")
        try:
            if cluster_root.exists():
                shutil.rmtree(cluster_root)
        except OSError:
            cleanup_errors.append("test cluster directory cleanup failed")
        if cleanup_errors:
            _fail("W1B_FRESH_PG_CLEANUP_MISSING: " + ", ".join(cleanup_errors))


def _load_models() -> Any:
    try:
        return importlib.import_module("app.db.models")
    except Exception:
        _fail("W1B_RECIPIENT_MODEL_MISSING: SQLAlchemy model module could not load")


def _table(metadata: Any, name: str, marker: str) -> Table:
    candidate = metadata.tables.get(f"erp.{name}")
    if candidate is None:
        candidate = metadata.tables.get(name)
    if candidate is None:
        _fail(marker + ": missing table " + name)
    return candidate


def _w1b_tables() -> dict[str, Table]:
    models = _load_models()
    metadata = models.Base.metadata
    tables = {
        name: _table(metadata, name, "W1B_RECIPIENT_MODEL_MISSING") for name in W1B_TABLE_NAMES
    }
    return tables


def _has_foreign_key(table: Table, local_columns: set[str], target: set[str]) -> bool:
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        local = {element.parent.name for element in constraint.elements}
        targets = {str(element.target_fullname) for element in constraint.elements}
        if local == local_columns and targets.intersection(target):
            return True
    return False


def _has_composite_guardian_foreign_key(table: Table) -> bool:
    expected_pairs = {
        ("recipient_id", "recipient_guardian.recipient_id"),
        ("guardian_id", "recipient_guardian.id"),
    }
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint) or len(constraint.elements) != 2:
            continue
        actual_pairs = {
            (
                element.parent.name,
                ".".join(str(element.target_fullname).split(".")[-2:]),
            )
            for element in constraint.elements
        }
        if actual_pairs == expected_pairs:
            return True
    return False


def _required_columns(table: Table, names: set[str], marker: str) -> None:
    missing = sorted(names - {column.name for column in table.columns})
    if missing:
        _fail(marker + ": missing columns " + ",".join(missing))


def _replacement_link_column(table: Table, marker: str) -> Any:
    candidates = [
        column
        for column in table.columns
        if "replacement" in column.name.lower() and column.name.lower().endswith("_id")
    ]
    if len(candidates) != 1:
        _fail(marker + ": replacement linkage column is not unique")
    return candidates[0]


def _exact_row_by_id(connection: Any, table: Table, row_id: int, marker: str) -> dict[str, Any]:
    rows = connection.execute(table.select().where(table.c.id == row_id)).mappings().all()
    if len(rows) != 1:
        _fail(marker + f": exact id {row_id} returned count={len(rows)}")
    row = dict(rows[0])
    if row.get("id") != row_id:
        _fail(marker + f": exact id {row_id} returned a different row")
    return row


def _recipient_row_ids(
    connection: Any, table: Table, recipient_id: int, marker: str
) -> tuple[int, ...]:
    rows = connection.execute(
        table.select()
        .with_only_columns(table.c.id)
        .where(table.c.recipient_id == recipient_id)
        .order_by(table.c.id)
    ).all()
    ids = tuple(int(row[0]) for row in rows)
    if len(ids) != len(set(ids)):
        _fail(marker + f": recipient_id {recipient_id} returned duplicate row ids")
    return ids


def _table_row_ids(connection: Any, table: Table, marker: str) -> tuple[int, ...]:
    rows = connection.execute(
        table.select().with_only_columns(table.c.id).order_by(table.c.id)
    ).all()
    ids = tuple(int(row[0]) for row in rows)
    if len(ids) != len(set(ids)):
        _fail(marker + ": table returned duplicate row ids")
    return ids


def _assert_exact_row_unchanged(
    connection: Any,
    table: Table,
    row_id: int,
    before: Mapping[str, Any],
    marker: str,
) -> None:
    after = _exact_row_by_id(connection, table, row_id, marker)
    if after != dict(before):
        _fail(marker + f": exact id {row_id} changed after rejected request")


def _audit_rows(connection: Any, entity_type: str, entity_pk: int) -> tuple[dict[str, Any], ...]:
    rows = (
        connection.execute(
            text(
                """
            SELECT id, occurred_at_utc, actor_account_id, actor_kind, action_code,
                   entity_type, entity_pk, before_json, after_json, reason_code,
                   reason_text, source_run_id, request_id, created_from
            FROM erp.audit_event
            WHERE entity_type = :entity_type
              AND entity_pk = :entity_pk
            ORDER BY id
            """
            ),
            {"entity_type": entity_type, "entity_pk": entity_pk},
        )
        .mappings()
        .all()
    )
    return tuple(dict(row) for row in rows)


def _all_audit_rows(connection: Any) -> tuple[dict[str, Any], ...]:
    rows = (
        connection.execute(
            text(
                """
            SELECT id, occurred_at_utc, actor_account_id, actor_kind, action_code,
                   entity_type, entity_pk, before_json, after_json, reason_code,
                   reason_text, source_run_id, request_id, created_from
            FROM erp.audit_event
            ORDER BY id
            """
            )
        )
        .mappings()
        .all()
    )
    return tuple(dict(row) for row in rows)


def _assert_audit_json_fields(
    value: Any,
    expected: Mapping[str, Any],
    marker: str,
    surface: str,
) -> None:
    if not isinstance(value, Mapping):
        _fail(marker + ": " + surface + " audit JSON is not an object")
    missing_or_wrong = [
        key for key, expected_value in expected.items() if value.get(key) != expected_value
    ]
    if missing_or_wrong:
        _fail(
            marker
            + ": "
            + surface
            + " audit JSON fields are not exact: "
            + ",".join(sorted(missing_or_wrong))
        )


def _audit_action_has_semantics(actual: Any, expected: str) -> bool:
    if not isinstance(actual, str) or not actual.strip():
        return False
    expected_upper = expected.upper()
    actual_upper = actual.upper()
    if expected_upper.endswith("_REPLACEMENT_CREATE"):
        return "REPLACE" in actual_upper or "CREATE" in actual_upper
    if expected_upper.endswith("_INVALIDATE"):
        return "INVALIDATE" in actual_upper or "REPLACE" in actual_upper
    if expected_upper.endswith("_UPDATE"):
        return "UPDATE" in actual_upper
    if expected_upper.endswith("_CREATE"):
        return "CREATE" in actual_upper
    required_tokens = tuple(token for token in expected_upper.split("_") if token)
    return all(token in actual_upper for token in required_tokens)


def _assert_single_audit_event(
    rows: tuple[dict[str, Any], ...],
    *,
    action_code: str,
    entity_type: str,
    entity_pk: int,
    actor_account_id: int,
    marker: str,
    expected_before: Any = _AUDIT_UNSET,
    expected_after: Mapping[str, Any] | None = None,
) -> None:
    if len(rows) != 1:
        _fail(marker + ": expected exactly one audit row, got " + str(len(rows)))
    event = rows[0]
    if (
        not _audit_action_has_semantics(event.get("action_code"), action_code)
        or event.get("entity_type") != entity_type
        or event.get("entity_pk") != entity_pk
        or event.get("actor_account_id") != actor_account_id
        or event.get("actor_kind") != "USER"
        or event.get("created_from") != "API"
    ):
        _fail(marker + ": audit row identity/action semantics are incomplete")
    if expected_before is not _AUDIT_UNSET:
        if expected_before is None:
            if event.get("before_json") is not None:
                _fail(marker + ": create audit row has unexpected before_json")
        else:
            _assert_audit_json_fields(event.get("before_json"), expected_before, marker, "before")
    if expected_after is not None:
        _assert_audit_json_fields(event.get("after_json"), expected_after, marker, "after")


def _assert_audit_append(
    before_rows: tuple[dict[str, Any], ...],
    after_rows: tuple[dict[str, Any], ...],
    *,
    action_code: str,
    entity_type: str,
    entity_pk: int,
    actor_account_id: int,
    marker: str,
    expected_before: Mapping[str, Any] | None = None,
    expected_after: Mapping[str, Any] | None = None,
) -> None:
    if len(after_rows) != len(before_rows) + 1 or after_rows[:-1] != before_rows:
        _fail(marker + ": operation did not append exactly one audit row")
    _assert_single_audit_event(
        (after_rows[-1],),
        action_code=action_code,
        entity_type=entity_type,
        entity_pk=entity_pk,
        actor_account_id=actor_account_id,
        marker=marker,
        expected_before=expected_before if expected_before is not None else _AUDIT_UNSET,
        expected_after=expected_after,
    )


def _assert_no_audit_change(
    before_rows: tuple[dict[str, Any], ...],
    after_rows: tuple[dict[str, Any], ...],
    marker: str,
) -> None:
    if after_rows != before_rows:
        _fail(marker + ": rejected request changed audit rows")


def _has_single_column_unique(table: Table, column_name: str) -> bool:
    for constraint in table.constraints:
        constraint_columns = [column.name for column in constraint.columns]
        if isinstance(constraint, UniqueConstraint) and constraint_columns == [column_name]:
            return True
    for index in table.indexes:
        if index.unique and [column.name for column in index.columns] == [column_name]:
            return True
    return False


def _has_active_composite_unique(
    table: Table,
    column_names: tuple[str, ...],
    *,
    require_non_null: str | None = None,
) -> bool:
    for index in table.indexes:
        if not index.unique or tuple(column.name for column in index.columns) != column_names:
            continue
        options = index.dialect_options.get("postgresql")
        where = options.get("where") if options is not None else None
        predicate = re.sub(
            r"\s+",
            " ",
            str(where if where is not None else "").lower(),
        ).strip()
        if "invalidated_at_utc" not in predicate or not re.search(
            r"\binvalidated_at_utc\s+is\s+null\b", predicate
        ):
            continue
        if require_non_null is not None and not re.search(
            rf"\b{re.escape(require_non_null)}\s+is\s+not\s+null\b", predicate
        ):
            continue
        return True
    return False


def _assert_period_exclusion(table: Table, marker: str) -> None:
    exclusions = [
        constraint for constraint in table.constraints if isinstance(constraint, ExcludeConstraint)
    ]
    for exclusion in exclusions:
        names = set(exclusion.columns.keys())
        operators = {str(operator) for operator in exclusion.operators.values()}
        exclusion_where = getattr(exclusion, "where", None)
        where = str(exclusion_where if exclusion_where is not None else "").lower()
        has_active_predicate = re.search(r"\binvalidated_at_utc\s+is\s+null\b", where) is not None
        has_period = "effective_period" in names or ("start_date" in names and "end_date" in names)
        if "recipient_id" in names and has_period and "&&" in operators and has_active_predicate:
            return
    _fail(marker + ": PostgreSQL GiST exclusion is absent or structurally incomplete")


def _period_exclusion_catalog_names(engine: Engine, table_name: str, marker: str) -> frozenset[str]:
    try:
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT c.conname,
                           c.contype,
                           pg_get_constraintdef(c.oid, true) AS definition,
                           COALESCE(
                               pg_get_expr(i.indpred, i.indrelid),
                               ''
                           ) AS predicate,
                           EXISTS (
                               SELECT 1
                               FROM unnest(c.conexclop) AS operator_oid
                               JOIN pg_operator AS op ON op.oid = operator_oid
                               WHERE op.oprname = '&&'
                           ) AS has_overlap_operator
                    FROM pg_constraint AS c
                    JOIN pg_class AS rel ON rel.oid = c.conrelid
                    JOIN pg_namespace AS namespace ON namespace.oid = rel.relnamespace
                    JOIN pg_index AS i ON c.conindid = i.indexrelid
                    WHERE namespace.nspname = 'erp'
                      AND rel.relname = :table_name
                      AND c.contype = 'x'
                    """
                    ),
                    {"table_name": table_name},
                )
                .mappings()
                .all()
            )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail(marker + ": PostgreSQL constraint catalog query failed")

    names: set[str] = set()
    for row in rows:
        definition = re.sub(r"\s+", " ", str(row["definition"] or "").lower()).strip()
        predicate = re.sub(r"\s+", " ", str(row["predicate"] or "").lower()).strip()
        if (
            str(row["contype"]) == "x"
            and bool(row["has_overlap_operator"])
            and "recipient_id" in definition
            and ("start_date" in definition or "effective_period" in definition)
            and re.search(r"\binvalidated_at_utc\s+is\s+null\b", predicate)
        ):
            constraint_name = row.get("conname")
            if isinstance(constraint_name, str) and constraint_name:
                names.add(constraint_name)
    if len(names) != 1:
        _fail(
            marker
            + ": catalog must expose exactly one active exclusion constraint with && and "
            + "invalidated_at_utc IS NULL"
        )
    return frozenset(names)


def _is_named_exclusion_violation(error: SQLAlchemyError, names: frozenset[str]) -> bool:
    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return sqlstate == "23P01" and constraint_name in names


def _schema_ref(document: dict[str, Any], schema: Any, marker: str) -> dict[str, Any]:
    if not isinstance(schema, dict):
        _fail(marker + ": schema is not an object")
    reference = schema.get("$ref")
    if isinstance(reference, str):
        prefix = "#/components/schemas/"
        if not reference.startswith(prefix):
            _fail(marker + ": schema reference is outside components/schemas")
        schemas = document.get("components", {}).get("schemas", {})
        if not isinstance(schemas, dict):
            _fail(marker + ": components.schemas is not an object")
        target = schemas.get(reference.removeprefix(prefix))
        if not isinstance(target, dict):
            _fail(marker + ": referenced schema is absent")
        return _schema_ref(document, target, marker)
    return schema


def _schema_properties(document: dict[str, Any], schema: Any, marker: str) -> dict[str, Any]:
    resolved = _schema_ref(document, schema, marker)
    properties = resolved.get("properties", {})
    if not isinstance(properties, dict):
        _fail(marker + ": schema properties are not an object")
    return properties


def _schema_required(document: dict[str, Any], schema: Any, marker: str) -> set[str]:
    resolved = _schema_ref(document, schema, marker)
    required = resolved.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        _fail(marker + ": schema required is invalid")
    return set(required)


def _schema_nullable(document: dict[str, Any], schema: Any, marker: str) -> bool:
    resolved = _schema_ref(document, schema, marker)
    if resolved.get("nullable") is True:
        return True
    any_of = resolved.get("anyOf") or resolved.get("oneOf")
    if isinstance(any_of, list):
        for item in any_of:
            if isinstance(item, dict) and item.get("type") == "null":
                return True
    return False


def _operation_request_schema(
    document: dict[str, Any], operation: dict[str, Any], marker: str
) -> dict[str, Any]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        _fail(marker + ": mutation has no requestBody")
    content = body.get("content", {})
    if not isinstance(content, dict):
        _fail(marker + ": requestBody content is invalid")
    media = content.get("application/json")
    if not isinstance(media, dict) or "schema" not in media:
        _fail(marker + ": application/json request schema is absent")
    return _schema_ref(document, media["schema"], marker)


def _operation_response_schema(
    document: dict[str, Any], operation: dict[str, Any], statuses: tuple[str, ...], marker: str
) -> dict[str, Any]:
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        _fail(marker + ": responses are not an object")
    for status in statuses:
        response = responses.get(status)
        if not isinstance(response, dict):
            continue
        content = response.get("content", {})
        if not isinstance(content, dict):
            _fail(marker + ": response content is invalid")
        media = content.get("application/json")
        if isinstance(media, dict) and "schema" in media:
            return _schema_ref(document, media["schema"], marker)
    _fail(marker + ": expected JSON response schema is absent")


def _recipient_item_path(paths: Mapping[str, Any], marker: str) -> str:
    candidates = sorted(path for path in paths if RECIPIENT_ITEM_PATTERN.fullmatch(str(path)))
    if not candidates:
        _fail(marker + ": recipient item path is absent")
    if len(candidates) != 1:
        _fail(marker + ": recipient item path is not unique")
    return candidates[0]


def _nested_item_paths(paths: Mapping[str, Any], marker: str) -> dict[str, str]:
    item_paths: dict[str, str] = {}
    for base_path in NESTED_ITEM_OPERATIONS:
        pattern = re.compile(re.escape(base_path) + r"/\{[^}/]+\}$")
        candidates = sorted(str(path) for path in paths if pattern.fullmatch(str(path)))
        if len(candidates) != 1:
            _fail(marker + ": nested item path is not unique: " + base_path + "/{id}")
        item_paths[base_path] = candidates[0]
    return item_paths


def _history_action_paths(paths: Mapping[str, Any], marker: str) -> dict[str, str]:
    action_paths: dict[str, str] = {}
    for base_path in HISTORY_BASE_PATHS:
        for action in HISTORY_ACTIONS:
            pattern = re.compile(re.escape(base_path) + r"/\{[^}/]+\}/" + re.escape(action) + r"$")
            candidates = sorted(str(path) for path in paths if pattern.fullmatch(str(path)))
            if len(candidates) != 1:
                _fail(
                    marker + ": history action path is not unique: " + base_path + "/{id}/" + action
                )
            action_paths[candidates[0]] = action
    return action_paths


def _openapi_document() -> dict[str, Any]:
    try:
        app = importlib.import_module("app.main").app
        document = app.openapi()
    except Exception:
        _fail("W1B_API_HARNESS_MISSING: FastAPI OpenAPI could not be built")
    if not isinstance(document, dict):
        _fail("W1B_API_HARNESS_MISSING: OpenAPI document is not an object")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1B_API_HARNESS_MISSING: OpenAPI paths are not an object")
    return document


def _require_api_operations() -> tuple[dict[str, Any], str]:
    document = _openapi_document()
    paths = document["paths"]
    assert isinstance(paths, dict)
    expected = {RECIPIENT_COLLECTION_PATH: {"get", "post"}, **NESTED_OPERATIONS}
    item_path = _recipient_item_path(paths, "W1B_RECIPIENT_API_MISSING")
    expected[item_path] = {"get", "patch"}
    nested_item_paths = _nested_item_paths(paths, "W1B_RECIPIENT_API_MISSING")
    expected.update(
        {path: NESTED_ITEM_OPERATIONS[base_path] for base_path, path in nested_item_paths.items()}
    )
    history_paths = _history_action_paths(paths, "W1B_RECIPIENT_API_MISSING")
    expected.update({path: {"post"} for path in history_paths})
    for path, methods in expected.items():
        operations = paths.get(path)
        if not isinstance(operations, dict) or not methods.issubset(operations):
            _fail("W1B_RECIPIENT_API_MISSING: operation path/method is absent: " + path)
        for method in methods:
            operation = operations.get(method)
            if not isinstance(operation, dict):
                _fail("W1B_OPENAPI_OPERATION_MISSING: operation is not an object: " + method)
            responses = operation.get("responses")
            if not isinstance(responses, dict) or not responses:
                _fail("W1B_OPENAPI_OPERATION_MISSING: operation response contract is absent")
            if method in {"post", "patch"}:
                _operation_request_schema(document, operation, "W1B_OPENAPI_SCHEMA_MISSING")
            _operation_response_schema(
                document,
                operation,
                ("201", "200") if method == "post" else ("200",),
                "W1B_OPENAPI_SCHEMA_MISSING",
            )
    return document, item_path


def _schema_closure(document: dict[str, Any], schema: Any) -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    collected: list[dict[str, Any]] = []

    def visit(current: Any) -> None:
        if not isinstance(current, dict):
            return
        reference = current.get("$ref")
        if isinstance(reference, str):
            if reference in seen:
                return
            seen.add(reference)
            resolved = _schema_ref(document, current, "W1B_OPENAPI_SCHEMA_MISSING")
            collected.append(resolved)
            visit(resolved)
            return
        collected.append(current)
        properties = current.get("properties", {})
        if isinstance(properties, dict):
            for property_schema in properties.values():
                visit(property_schema)
        for key in ("items", "additionalProperties"):
            visit(current.get(key))
        for key in ("allOf", "anyOf", "oneOf"):
            variants = current.get(key)
            if isinstance(variants, list):
                for variant in variants:
                    visit(variant)

    visit(schema)
    return tuple(collected)


def _schema_keys(closure: tuple[dict[str, Any], ...]) -> set[str]:
    keys: set[str] = set()
    for schema in closure:
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            keys.update(str(key) for key in properties)
    return keys


def _schema_values(closure: tuple[dict[str, Any], ...]) -> set[str]:
    values: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, str):
            values.add(value)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    for schema in closure:
        for keyword in ("enum", "const", "default", "example", "examples"):
            collect(schema.get(keyword))
    return values


def _assert_no_legacy_schema_keys(
    document: dict[str, Any], schema: Any, marker: str, surface: str
) -> None:
    closure = _schema_closure(document, schema)
    forbidden = sorted(key for key in _schema_keys(closure) if key.lower().startswith("legacy_"))
    if forbidden:
        _fail(
            marker
            + ": public "
            + surface
            + " schema exposes legacy parameter(s): "
            + ",".join(forbidden)
        )


def _assert_no_public_legacy_surface(document: dict[str, Any]) -> None:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: OpenAPI paths are not an object")
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    for path, path_item in paths.items():
        path_text = str(path)
        if "legacy" in path_text.lower():
            _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: public legacy route exists")
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in http_methods or not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId") or "")
            if "legacy" in operation_id.lower():
                _fail(
                    "W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: public legacy operation exists: "
                    + operation_id
                )
            parameters = operation.get("parameters", [])
            if not isinstance(parameters, list):
                _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: operation parameters are invalid")
            for parameter in parameters:
                if not isinstance(parameter, dict):
                    continue
                reference = str(parameter.get("$ref") or "")
                resolved_parameter = parameter
                if reference.startswith("#/components/parameters/"):
                    component_name = reference.removeprefix("#/components/parameters/")
                    component_parameters = document.get("components", {}).get("parameters", {})
                    if isinstance(component_parameters, dict):
                        candidate = component_parameters.get(component_name)
                        if isinstance(candidate, dict):
                            resolved_parameter = candidate
                name = str(resolved_parameter.get("name") or "")
                if name.lower().startswith("legacy_") or "legacy_" in reference.lower():
                    _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: public legacy parameter exists")
                parameter_schema = resolved_parameter.get("schema")
                if parameter_schema is not None:
                    _assert_no_legacy_schema_keys(
                        document,
                        parameter_schema,
                        "W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND",
                        "parameter",
                    )
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content = request_body.get("content", {})
                if not isinstance(content, dict):
                    _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: request content is invalid")
                for media in content.values():
                    if not isinstance(media, dict) or "schema" not in media:
                        continue
                    _assert_no_legacy_schema_keys(
                        document,
                        media["schema"],
                        "W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND",
                        "request",
                    )
            responses = operation.get("responses", {})
            if not isinstance(responses, dict):
                _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: operation responses are invalid")
            for status, response in responses.items():
                if not str(status).startswith("2") or not isinstance(response, dict):
                    continue
                content = response.get("content", {})
                if not isinstance(content, dict):
                    _fail("W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND: response content is invalid")
                for media in content.values():
                    if not isinstance(media, dict) or "schema" not in media:
                        continue
                    _assert_no_legacy_schema_keys(
                        document,
                        media["schema"],
                        "W1B_ABS_PUBLIC_LEGACY_SURFACE_FOUND",
                        "2xx response",
                    )


def _assert_error_response_schema(document: dict[str, Any], response: Any, marker: str) -> None:
    if not isinstance(response, dict):
        _fail(marker + ": error response is not an object")
    content = response.get("content", {})
    if not isinstance(content, dict):
        _fail(marker + ": error response content is invalid")
    media = content.get("application/json")
    if not isinstance(media, dict) or "schema" not in media:
        _fail(marker + ": stable JSON error schema is absent")
    envelope_schema = media["schema"]
    expected_envelope_fields = {"error", "field_errors", "details", "request_id"}
    properties = _schema_properties(document, envelope_schema, marker)
    if not expected_envelope_fields.issubset(properties):
        _fail(marker + ": stable error envelope fields are incomplete")
    if not expected_envelope_fields.issubset(_schema_required(document, envelope_schema, marker)):
        _fail(marker + ": stable error envelope fields are not required")
    error_schema = properties["error"]
    expected_error_fields = {"code", "message"}
    error_properties = _schema_properties(document, error_schema, marker)
    if not expected_error_fields.issubset(error_properties):
        _fail(marker + ": stable error code/message fields are incomplete")
    if not expected_error_fields.issubset(_schema_required(document, error_schema, marker)):
        _fail(marker + ": stable error code/message fields are not required")


def _assert_w1b_operation_matrix(document: dict[str, Any], item_path: str) -> None:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1B_OPERATION_MATRIX_MISSING: OpenAPI paths are not an object")
    history_paths = _history_action_paths(paths, "W1B_OPERATION_MATRIX_MISSING")
    nested_item_paths = _nested_item_paths(paths, "W1B_OPERATION_MATRIX_MISSING")
    collection_paths = {
        RECIPIENT_COLLECTION_PATH,
        *NESTED_OPERATIONS,
    }
    expected_paths = {
        RECIPIENT_COLLECTION_PATH,
        item_path,
        *NESTED_OPERATIONS,
        *history_paths,
        *(
            path
            for base_path, path in nested_item_paths.items()
            if "patch" in NESTED_ITEM_OPERATIONS[base_path]
        ),
    }
    mutation_operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, operations in paths.items():
        path_text = str(path)
        if path_text not in expected_paths:
            continue
        if not isinstance(operations, dict):
            continue
        for method in ("post", "patch"):
            operation = operations.get(method)
            if isinstance(operation, dict):
                mutation_operations.append((path_text, method, operation))
    present_paths = {path for path, _, _ in mutation_operations}
    missing_paths = sorted(expected_paths - present_paths)
    if missing_paths:
        _fail(
            "W1B_OPERATION_MATRIX_MISSING: mutation operation missing: " + ",".join(missing_paths)
        )
    for path, method, operation in mutation_operations:
        responses = operation.get("responses", {})
        if not isinstance(responses, dict):
            _fail("W1B_OPERATION_MATRIX_MISSING: responses are not an object: " + path)
        for status in ("401", "403", "409", "422", "500"):
            response = responses.get(status)
            if response is None:
                _fail(
                    "W1B_OPERATION_MATRIX_MISSING: "
                    + path
                    + " "
                    + method.upper()
                    + " lacks "
                    + status
                )
            _assert_error_response_schema(
                document,
                response,
                "W1B_OPERATION_MATRIX_MISSING: " + path + " " + method.upper(),
            )
        request_schema = _operation_request_schema(
            document,
            operation,
            "W1B_OPERATION_MATRIX_MISSING: " + path + " " + method.upper(),
        )
        required = _schema_required(
            document,
            request_schema,
            "W1B_OPERATION_MATRIX_MISSING: " + path + " " + method.upper(),
        )
        properties = _schema_properties(
            document,
            request_schema,
            "W1B_OPERATION_MATRIX_MISSING: " + path + " " + method.upper(),
        )
        collection_create = method == "post" and path in collection_paths
        if collection_create:
            if "expected_row_version" in properties:
                _fail(
                    "W1B_OPERATION_MATRIX_MISSING: collection create invents "
                    "expected_row_version: " + path
                )
        elif "expected_row_version" not in properties or "expected_row_version" not in required:
            _fail(
                "W1B_OPERATION_MATRIX_MISSING: existing-row mutation lacks "
                "required expected_row_version: " + path
            )


def _assert_payer_schema_absent(
    document: dict[str, Any], schema: Any, marker: str, surface: str
) -> None:
    closure = _schema_closure(document, schema)
    keys = _schema_keys(closure)
    forbidden_keys = keys.intersection({"payer_type", "guardian_id", "SELF", "PRIMARY_GUARDIAN"})
    forbidden_values = _schema_values(closure).intersection({"SELF", "PRIMARY_GUARDIAN"})
    if forbidden_keys or forbidden_values:
        details = sorted(forbidden_keys | forbidden_values)
        _fail(
            marker
            + ": payer "
            + surface
            + " exposes forbidden type/guardian surface: "
            + ",".join(details)
        )


def _assert_w1b_public_schema_contract(document: dict[str, Any], item_path: str) -> None:
    _assert_no_public_legacy_surface(document)
    _assert_w1b_operation_matrix(document, item_path)
    paths = document["paths"]
    assert isinstance(paths, dict)
    create_operation = paths[RECIPIENT_COLLECTION_PATH]["post"]
    create_schema = _operation_request_schema(
        document, create_operation, "W1B_RECIPIENT_CREATE_CONTRACT_MISSING"
    )
    if _schema_required(document, create_schema, "W1B_RECIPIENT_CREATE_CONTRACT_MISSING") != {
        "name",
        "birth_date",
        "sex_code",
    }:
        _fail(
            "W1B_RECIPIENT_CREATE_CONTRACT_MISSING: required fields are not exactly canonical three"
        )
    create_properties = _schema_properties(
        document, create_schema, "W1B_RECIPIENT_CREATE_CONTRACT_MISSING"
    )
    recipient_no_request = create_properties.get("recipient_no")
    if recipient_no_request is not None and not (
        isinstance(recipient_no_request, dict) and recipient_no_request.get("readOnly") is True
    ):
        _fail("W1B_RECIPIENT_CREATE_CONTRACT_MISSING: recipient_no is writable in create request")
    sex_schema = create_properties.get("sex_code")
    sex_schema = _schema_ref(document, sex_schema, "W1B_SEX_CODE_CONTRACT_MISSING")
    if set(sex_schema.get("enum", [])) != {"MALE", "FEMALE"}:
        _fail("W1B_SEX_CODE_CONTRACT_MISSING: public sex_code enum is not MALE/FEMALE only")

    create_response = _operation_response_schema(
        document,
        create_operation,
        ("201", "200"),
        "W1B_RECIPIENT_CREATE_CONTRACT_MISSING",
    )
    response_properties = _schema_properties(
        document, create_response, "W1B_RECIPIENT_CREATE_CONTRACT_MISSING"
    )
    if "recipient_no" not in response_properties or not _schema_nullable(
        document,
        response_properties["recipient_no"],
        "W1B_RECIPIENT_CREATE_CONTRACT_MISSING",
    ):
        _fail("W1B_RECIPIENT_CREATE_CONTRACT_MISSING: response recipient_no is not nullable")

    guardian_operation = paths["/api/v1/recipients/{recipient_id}/guardians"]["post"]
    guardian_request = _operation_request_schema(
        document, guardian_operation, "W1B_GUARDIAN_SCHEMA_MISSING"
    )
    guardian_properties = _schema_properties(
        document, guardian_request, "W1B_GUARDIAN_SCHEMA_MISSING"
    )
    guardian_required = _schema_required(document, guardian_request, "W1B_GUARDIAN_SCHEMA_MISSING")
    if guardian_required != {"name"}:
        _fail("W1B_GUARDIAN_SCHEMA_MISSING: guardian required fields are not name only")
    if "name" not in guardian_required:
        _fail("W1B_GUARDIAN_SCHEMA_MISSING: guardian name is not required")
    if {"birth_date", "sex_code"}.intersection(guardian_properties):
        _fail("W1B_GUARDIAN_SCHEMA_MISSING: forbidden birth/sex fields are public")
    for field in ("phone", "address", "relationship_text"):
        if field not in guardian_properties or not _schema_nullable(
            document, guardian_properties[field], "W1B_GUARDIAN_SCHEMA_MISSING"
        ):
            _fail("W1B_GUARDIAN_SCHEMA_MISSING: optional field is not nullable: " + field)
    guardian_response = _operation_response_schema(
        document,
        guardian_operation,
        ("201", "200"),
        "W1B_GUARDIAN_SCHEMA_MISSING",
    )
    guardian_response_properties = _schema_properties(
        document, guardian_response, "W1B_GUARDIAN_SCHEMA_MISSING"
    )
    for field in ("phone", "address", "relationship_text"):
        if field not in guardian_response_properties or not _schema_nullable(
            document, guardian_response_properties[field], "W1B_GUARDIAN_SCHEMA_MISSING"
        ):
            _fail("W1B_GUARDIAN_SCHEMA_MISSING: response optional field is not nullable: " + field)

    payer_path = "/api/v1/recipients/{recipient_id}/payer-snapshots"
    payer_operation = paths[payer_path]["post"]
    payer_request = _operation_request_schema(document, payer_operation, "W1B_PAYER_SCHEMA_MISSING")
    payer_required = _schema_required(document, payer_request, "W1B_PAYER_SCHEMA_MISSING")
    if payer_required != {"name", "start_date"}:
        _fail("W1B_PAYER_SCHEMA_MISSING: payer required fields are not name/start_date only")
    payer_properties = _schema_properties(document, payer_request, "W1B_PAYER_SCHEMA_MISSING")
    for field in ("phone", "address", "relationship_text"):
        if field not in payer_properties or not _schema_nullable(
            document, payer_properties[field], "W1B_PAYER_SCHEMA_MISSING"
        ):
            _fail("W1B_PAYER_SCHEMA_MISSING: optional field is not nullable: " + field)
    _assert_payer_schema_absent(document, payer_request, "W1B_PAYER_SCHEMA_MISSING", "request")
    payer_response = _operation_response_schema(
        document, payer_operation, ("201", "200"), "W1B_PAYER_SCHEMA_MISSING"
    )
    payer_response_properties = _schema_properties(
        document, payer_response, "W1B_PAYER_SCHEMA_MISSING"
    )
    for field in ("phone", "address", "relationship_text"):
        if field not in payer_response_properties or not _schema_nullable(
            document, payer_response_properties[field], "W1B_PAYER_SCHEMA_MISSING"
        ):
            _fail("W1B_PAYER_SCHEMA_MISSING: response optional field is not nullable: " + field)
    _assert_payer_schema_absent(document, payer_response, "W1B_PAYER_SCHEMA_MISSING", "response")

    history_paths = _history_action_paths(paths, "W1B_RECIPIENT_API_MISSING")
    nested_item_paths = _nested_item_paths(paths, "W1B_RECIPIENT_API_MISSING")
    w1b_paths = [
        RECIPIENT_COLLECTION_PATH,
        item_path,
        *NESTED_OPERATIONS,
        *nested_item_paths.values(),
        *history_paths,
    ]
    for path in w1b_paths:
        operations = paths.get(path)
        if not isinstance(operations, dict):
            _fail("W1B_OPENAPI_OPERATION_MISSING: W1B path is not an operation object")
        for method, operation in operations.items():
            if method not in {"get", "post", "patch"} or not isinstance(operation, dict):
                continue
            schemas: list[Any] = []
            request_schema: dict[str, Any] | None = None
            if method in {"post", "patch"}:
                request_schema = _operation_request_schema(
                    document, operation, "W1B_OPENAPI_SCHEMA_MISSING"
                )
                schemas.append(request_schema)
            schemas.append(
                _operation_response_schema(
                    document,
                    operation,
                    ("201", "200") if method == "post" else ("200",),
                    "W1B_OPENAPI_SCHEMA_MISSING",
                )
            )
            for schema in schemas:
                closure = _schema_closure(document, schema)
                if path.startswith(payer_path):
                    _assert_payer_schema_absent(
                        document,
                        schema,
                        "W1B_PAYER_SCHEMA_MISSING",
                        "request/response",
                    )
                forbidden = {
                    key
                    for key in _schema_keys(closure)
                    if key.startswith("legacy_")
                    or key in {"resident_number", "rrn", "signer_token"}
                }
                if forbidden:
                    _fail(
                        "W1B_PUBLIC_PII_OR_LEGACY_LEAK: public schema exposes "
                        + ",".join(sorted(forbidden))
                    )
                for member in closure:
                    if (
                        member.get("type") == "object"
                        and member.get("additionalProperties") is not False
                    ):
                        _fail("W1B_OPENAPI_SCHEMA_MISSING: W1B object schema is not closed")
            if path in history_paths:
                if request_schema is None or "expected_row_version" not in _schema_required(
                    document, request_schema, "W1B_HISTORY_ACTION_REQUEST_MISSING"
                ):
                    _fail(
                        "W1B_HISTORY_ACTION_REQUEST_MISSING: "
                        + path
                        + " request does not require expected_row_version"
                    )
                response_schema = _operation_response_schema(
                    document,
                    operation,
                    ("201", "200"),
                    "W1B_HISTORY_ACTION_SCHEMA_MISSING",
                )
                response_keys = _schema_keys(_schema_closure(document, response_schema))
                replacement_keys = {
                    key
                    for key in response_keys
                    if "replacement" in key.lower() and key.lower().endswith("id")
                }
                if "invalidated_at_utc" not in response_keys or not replacement_keys:
                    _fail(
                        "W1B_HISTORY_ACTION_SCHEMA_MISSING: "
                        + path
                        + " response lacks invalidated_at_utc/replacement linkage"
                    )


def _require_metadata_contract() -> dict[str, Table]:
    tables = _w1b_tables()
    recipient = tables["recipient"]
    guardian = tables["recipient_guardian"]
    primary = tables["recipient_guardian_primary_period"]
    payer = tables["recipient_payer_snapshot"]
    mapping = tables["recipient_legacy_mapping"]

    _required_columns(
        recipient,
        {
            "id",
            "name",
            "birth_date",
            "sex_code",
            "recipient_no",
            "memo",
            "postal_code",
            "address",
            "home_phone",
            "mobile_phone",
            "row_version",
        },
        "W1B_RECIPIENT_MODEL_MISSING",
    )
    _required_columns(
        guardian,
        {
            "id",
            "recipient_id",
            "name",
            "phone",
            "address",
            "relationship_text",
            "row_version",
        },
        "W1B_GUARDIAN_MODEL_MISSING",
    )
    _required_columns(
        primary,
        {
            "id",
            "recipient_id",
            "guardian_id",
            "start_date",
            "end_date",
            "invalidated_at_utc",
            "row_version",
        },
        "W1B_PRIMARY_PERIOD_MODEL_MISSING",
    )
    _required_columns(
        payer,
        {
            "id",
            "recipient_id",
            "name",
            "phone",
            "address",
            "relationship_text",
            "start_date",
            "end_date",
            "invalidated_at_utc",
            "row_version",
        },
        "W1B_PAYER_MODEL_MISSING",
    )
    _required_columns(
        mapping,
        {
            "id",
            "source_system_code",
            "legacy_recipient_key",
            "legacy_attachment_key",
            "recipient_id",
            "row_version",
        },
        "W1B_REC_02_MAPPING_MODEL_MISSING",
    )

    if (
        recipient.c.name.nullable
        or recipient.c.birth_date.nullable
        or recipient.c.sex_code.nullable
    ):
        _fail("W1B_RECIPIENT_MODEL_MISSING: recipient identity columns are nullable")
    if not recipient.c.recipient_no.nullable:
        _fail("W1B_RECIPIENT_MODEL_MISSING: recipient_no must be nullable before W1D issuance")
    if any(
        not recipient.c[name].nullable
        for name in ("postal_code", "address", "home_phone", "mobile_phone")
    ):
        _fail("W1B_RECIPIENT_MODEL_MISSING: optional contact fields must be nullable")
    if not _has_single_column_unique(recipient, "recipient_no"):
        _fail("W1B_RECIPIENT_NO_UNIQUE_MISSING: recipient_no is not uniquely constrained")
    if not mapping.c.legacy_recipient_key.nullable:
        _fail("W1B_REC_02_MAPPING_MODEL_MISSING: legacy_recipient_key must be nullable")
    if not mapping.c.legacy_attachment_key.nullable:
        _fail("W1B_REC_02_MAPPING_MODEL_MISSING: legacy_attachment_key must be nullable")
    if any(not guardian.c[name].nullable for name in ("phone", "address", "relationship_text")):
        _fail("W1B_GUARDIAN_MODEL_MISSING: optional guardian fields must be nullable")
    if not _has_active_composite_unique(mapping, ("source_system_code", "legacy_recipient_key")):
        _fail("W1B_REC_02_MAPPING_MODEL_MISSING: active recipient-key unique is absent")
    if not _has_active_composite_unique(mapping, ("source_system_code", "legacy_attachment_key")):
        _fail("W1B_REC_02_MAPPING_MODEL_MISSING: active attachment-key unique is absent")
    guardian_column_names = {column.name for column in guardian.columns}
    payer_column_names = {column.name for column in payer.columns}
    if {"birth_date", "sex_code"}.intersection(guardian_column_names):
        _fail("W1B_GUARDIAN_MODEL_MISSING: guardian has forbidden birth/sex columns")
    if {"payer_type", "guardian_id"}.intersection(payer_column_names):
        _fail("W1B_PAYER_MODEL_MISSING: payer snapshot has forbidden FK/type columns")
    if not _has_foreign_key(guardian, {"recipient_id"}, {"erp.recipient.id", "recipient.id"}):
        _fail("W1B_GUARDIAN_MODEL_MISSING: guardian recipient FK is absent")
    if not _has_foreign_key(payer, {"recipient_id"}, {"erp.recipient.id", "recipient.id"}):
        _fail("W1B_PAYER_MODEL_MISSING: payer recipient FK is absent")
    if not _has_foreign_key(primary, {"recipient_id"}, {"erp.recipient.id", "recipient.id"}):
        _fail("W1B_PRIMARY_PERIOD_MODEL_MISSING: primary recipient FK is absent")
    if not _has_foreign_key(
        primary, {"guardian_id"}, {"erp.recipient_guardian.id", "recipient_guardian.id"}
    ):
        _fail("W1B_PRIMARY_PERIOD_MODEL_MISSING: primary guardian FK is absent")
    if not _has_composite_guardian_foreign_key(primary):
        _fail(
            "W1B_PRIMARY_PERIOD_COMPOSITE_FK_MISSING: primary period does not use the canonical "
            "(recipient_id, guardian_id) composite FK"
        )
    _assert_period_exclusion(primary, "W1B_POSTGRES_EXCLUSION_MISSING")
    _assert_period_exclusion(payer, "W1B_POSTGRES_EXCLUSION_MISSING")
    return tables


def _postgres_engine() -> Engine:
    if os.environ.get("SSWCENTER_POSTGRES_TEST") != "1":
        _fail("W1B_POSTGRES_HARNESS_MISSING: isolated PostgreSQL harness is not enabled")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W1B_POSTGRES_HARNESS_MISSING: SSWCENTER_DATABASE_URL is not configured")
    try:
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
            ("_test", "_review")
        ):
            _fail("W1B_POSTGRES_HARNESS_MISSING: database URL is not an isolated test database")
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except pytest.fail.Exception:
        raise
    except Exception:
        _fail("W1B_POSTGRES_HARNESS_MISSING: isolated PostgreSQL connection failed")


def _require_db_revision(engine: Engine, allowed_revisions: frozenset[str]) -> None:
    try:
        with engine.connect() as connection:
            current = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if current not in allowed_revisions:
                _fail(
                    "W1B_POSTGRES_FRESH_UPGRADE_MISSING: database revision is not W1B or "
                    "its serial descendant"
                )
            missing = [
                name
                for name in W1B_TABLE_NAMES
                if connection.execute(
                    text("SELECT to_regclass(:qualified) IS NOT NULL"),
                    {"qualified": f"erp.{name}"},
                ).scalar()
                is not True
            ]
            if missing:
                _fail(
                    "W1B_POSTGRES_SCHEMA_MISSING: W1B tables are absent: "
                    + ",".join(sorted(missing))
                )
    except pytest.fail.Exception:
        raise
    except Exception:
        _fail("W1B_POSTGRES_HARNESS_MISSING: revision/table query failed")


def _insert_values(table: Table, base: dict[str, Any], actor_account_id: int) -> dict[str, Any]:
    values = dict(base)
    for column in table.columns:
        if (
            column.name in values
            or column.nullable
            or column.default is not None
            or column.server_default is not None
        ):
            continue
        if column.primary_key and (column.autoincrement or column.identity is not None):
            continue
        if column.computed is not None:
            continue
        name = column.name
        if name.endswith("_by_account_id") or name == "actor_account_id":
            values[name] = actor_account_id
        elif name == "row_version":
            values[name] = 1
        elif name.endswith("_at_utc"):
            values[name] = datetime.now(UTC)
        elif name == "sex_code":
            values[name] = "TEST"
        elif name == "birth_date":
            values[name] = SYNTHETIC_BIRTH_DATE
        elif name.endswith("_date"):
            values[name] = SYNTHETIC_BIRTH_DATE
        elif name.endswith("_id"):
            _fail("W1B_POSTGRES_FIXTURE_MISSING: unknown required FK column " + name)
        else:
            _fail("W1B_POSTGRES_FIXTURE_MISSING: unknown required column " + name)
    return values


def _insert_row(connection: Any, table: Table, base: dict[str, Any], actor_account_id: int) -> int:
    values = _insert_values(table, base, actor_account_id)
    try:
        return int(
            connection.execute(table.insert().values(**values).returning(table.c.id)).scalar_one()
        )
    except pytest.fail.Exception:
        raise
    except Exception:
        _fail("W1B_POSTGRES_FIXTURE_MISSING: synthetic row could not be inserted")


def _expected_insert_failure(
    engine: Engine, table: Table, base: dict[str, Any], actor_id: int, marker: str
) -> None:
    try:
        with engine.begin() as connection:
            values = _insert_values(table, base, actor_id)
            connection.execute(table.insert().values(**values).returning(table.c.id)).scalar_one()
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        return
    _fail(marker)


def _insert_period(
    engine: Engine,
    table: Table,
    *,
    recipient_id: int,
    guardian_id: int | None,
    start_date: date,
    end_date: date | None,
    actor_id: int,
    extra: Mapping[str, Any] | None = None,
) -> int:
    base: dict[str, Any] = {
        "recipient_id": recipient_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if extra:
        base.update(extra)
    if guardian_id is not None:
        base["guardian_id"] = guardian_id
    values = _insert_values(table, base, actor_id)
    try:
        with engine.begin() as connection:
            return int(
                connection.execute(
                    table.insert().values(**values).returning(table.c.id)
                ).scalar_one()
            )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        raise
    except Exception:
        _fail("W1B_POSTGRES_FIXTURE_MISSING: synthetic period could not be inserted")


def _expected_update_failure(engine: Engine, statement: Any, marker: str) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(statement)
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        return
    _fail(marker)


def _synthetic_recipient_no(column: Any, suffix: int) -> int | str:
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        python_type = str
    if python_type is int:
        return 900000000 + suffix
    return f"TEST_W1B_RECIPIENT_NO_{suffix:03d}"


def _payer_snapshot_signature(
    connection: Any, payer: Table, payer_id: int, marker: str
) -> tuple[str, int, dict[str, str]]:
    row = connection.execute(payer.select().where(payer.c.id == payer_id)).mappings().one_or_none()
    if row is None:
        _fail(marker + ": payer snapshot row is absent")
    field_names = ("name", "phone", "address", "relationship_text", "start_date", "end_date")
    fields = {name: str(row[name]) for name in field_names}
    fingerprint = hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    row_version = row.get("row_version")
    if not isinstance(row_version, int):
        _fail(marker + ": payer snapshot row_version is not an integer")
    return fingerprint, row_version, fields


def _assert_no_payer_autosync_triggers(engine: Engine, marker: str) -> None:
    try:
        with engine.connect() as connection:
            trigger_names = (
                connection.execute(
                    text(
                        """
                    SELECT c.relname || ':' || t.tgname
                    FROM pg_trigger AS t
                    JOIN pg_class AS c ON c.oid = t.tgrelid
                    JOIN pg_namespace AS n ON n.oid = c.relnamespace
                    JOIN pg_proc AS p ON p.oid = t.tgfoid
                    WHERE n.nspname = 'erp'
                      AND c.relname IN ('recipient_guardian',
                                        'recipient_guardian_primary_period')
                      AND NOT t.tgisinternal
                      AND (
                          pg_get_functiondef(p.oid) ILIKE '%recipient_payer_snapshot%'
                          OR t.tgname ILIKE '%payer%'
                      )
                    """
                    )
                )
                .scalars()
                .all()
            )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail(marker + ": trigger catalog query failed")
    if trigger_names:
        _fail(marker + ": payer autosync trigger exists: " + ",".join(trigger_names))


def _run_primary_race(
    engine: Engine,
    primary: Table,
    *,
    recipient_id: int,
    guardian_ids: tuple[int, int],
    exclusion_names: frozenset[str],
    actor_id: int,
    marker: str,
) -> None:
    if guardian_ids[0] == guardian_ids[1]:
        _fail(marker + ": race guardians must be distinct")
    barrier = threading.Barrier(2)
    outcomes: list[str | None] = [None, None]
    backend_pids: list[int | None] = [None, None]
    periods = (
        (date(2027, 1, 1), date(2027, 1, 4)),
        (date(2027, 1, 2), date(2027, 1, 5)),
    )

    def worker(slot: int) -> None:
        connection = engine.connect()
        transaction = connection.begin()
        try:
            backend_pids[slot] = int(
                connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            barrier.wait(timeout=15)
            values = _insert_values(
                primary,
                {
                    "recipient_id": recipient_id,
                    "guardian_id": guardian_ids[slot],
                    "start_date": periods[slot][0],
                    "end_date": periods[slot][1],
                },
                actor_id,
            )
            connection.execute(primary.insert().values(**values))
            transaction.commit()
            outcomes[slot] = "success"
        except SQLAlchemyError as error:
            try:
                transaction.rollback()
            except SQLAlchemyError:
                outcomes[slot] = "error:rollback"
            else:
                outcomes[slot] = (
                    "conflict"
                    if _is_named_exclusion_violation(error, exclusion_names)
                    else "error:non_exclusion"
                )
        except BaseException as exc:
            transaction.rollback()
            outcomes[slot] = "error:" + type(exc).__name__
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(slot,)) for slot in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    if any(thread.is_alive() for thread in threads):
        _fail(marker + ": concurrent transactions did not finish")
    if len({pid for pid in backend_pids if pid is not None}) != 2:
        _fail(marker + ": race did not use two independent PostgreSQL connections")
    if (
        outcomes.count("success") != 1
        or outcomes.count("conflict") != 1
        or any(outcome not in {"success", "conflict"} for outcome in outcomes)
    ):
        _fail(marker + ": expected exactly one success and one conflict, got " + repr(outcomes))


@dataclass(frozen=True)
class ActorCase:
    account_id: int
    staff_id: int
    display_name: str
    role_code: str
    permission: str | None


def _make_actor_cases(engine: Engine, token: str) -> dict[str, ActorCase]:
    cases: dict[str, ActorCase] = {}
    try:
        with engine.begin() as connection:
            for label, role, permission in (
                ("admin", "ADMIN", None),
                ("view", "USER", "RECIPIENT_VIEW"),
                ("manage", "USER", "RECIPIENT_MANAGE"),
                ("user", "USER", None),
            ):
                staff_id = int(
                    connection.execute(
                        text(
                            """
                            INSERT INTO erp.staff
                                (name, birth_date, sex_code, phone, phone_normalized,
                                 address, display_name, memo)
                            VALUES (:name, DATE '2000-01-01', 'TEST', NULL, NULL,
                                    NULL, :display_name, 'TEST_W1B synthetic actor')
                            RETURNING id
                            """
                        ),
                        {
                            "name": f"TEST_W1B_ACTOR_{label}_{token}",
                            "display_name": f"TEST_W1B_{label}",
                        },
                    ).scalar_one()
                )
                account_id = int(
                    connection.execute(
                        text(
                            """
                            INSERT INTO erp.user_account
                                (staff_id, account_code, display_name, role_code,
                                 pin_hash, pin_lookup_hmac, pin_key_version)
                            VALUES (:staff_id, :account_code, :display_name, :role_code,
                                    'TEST_W1B synthetic hash', :pin_lookup_hmac, 1)
                            RETURNING id
                            """
                        ),
                        {
                            "staff_id": staff_id,
                            "account_code": f"test_w1b_{label}_{token}",
                            "display_name": f"TEST_W1B_{label}",
                            "role_code": role,
                            "pin_lookup_hmac": f"TEST_W1B_{label}_{token}".encode(),
                        },
                    ).scalar_one()
                )
                if permission is not None:
                    connection.execute(
                        text(
                            """
                            INSERT INTO erp.permission_definition
                                (permission_code, name, description, active)
                            VALUES (:permission, :permission, 'TEST_W1B permission', TRUE)
                            ON CONFLICT (permission_code) DO NOTHING
                            """
                        ),
                        {"permission": permission},
                    )
                cases[label] = ActorCase(
                    account_id,
                    staff_id,
                    f"TEST_W1B_{label}",
                    role,
                    permission,
                )
            for label in ("view", "manage"):
                case = cases[label]
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.account_permission
                            (account_id, permission_code, granted_by_account_id)
                        VALUES (:account_id, :permission, :granted_by)
                        """
                    ),
                    {
                        "account_id": case.account_id,
                        "permission": case.permission,
                        "granted_by": cases["admin"].account_id,
                    },
                )
    except Exception:
        _fail("W1B_POSTGRES_FIXTURE_MISSING: synthetic authorization fixture failed")
    return cases


def _cleanup(engine: Engine, cases: Mapping[str, ActorCase], recipient_ids: set[int]) -> None:
    try:
        with engine.begin() as connection:
            for recipient_id in recipient_ids:
                connection.execute(
                    text(
                        "DELETE FROM erp.recipient_legacy_mapping "
                        "WHERE recipient_id = :recipient_id"
                    ),
                    {"recipient_id": recipient_id},
                )
                connection.execute(
                    text(
                        "DELETE FROM erp.recipient_payer_snapshot "
                        "WHERE recipient_id = :recipient_id"
                    ),
                    {"recipient_id": recipient_id},
                )
                connection.execute(
                    text(
                        "DELETE FROM erp.recipient_guardian_primary_period "
                        "WHERE recipient_id = :recipient_id"
                    ),
                    {"recipient_id": recipient_id},
                )
                connection.execute(
                    text("DELETE FROM erp.recipient_guardian WHERE recipient_id = :recipient_id"),
                    {"recipient_id": recipient_id},
                )
                connection.execute(
                    text("DELETE FROM erp.recipient WHERE id = :recipient_id"),
                    {"recipient_id": recipient_id},
                )
            account_ids = [case.account_id for case in cases.values()]
            staff_ids = [case.staff_id for case in cases.values()]
            connection.execute(
                text("DELETE FROM erp.audit_event WHERE actor_account_id = ANY(:ids)"),
                {"ids": account_ids},
            )
            connection.execute(
                text("DELETE FROM erp.account_permission WHERE account_id = ANY(:ids)"),
                {"ids": account_ids},
            )
            connection.execute(
                text("DELETE FROM erp.user_account WHERE id = ANY(:ids)"),
                {"ids": account_ids},
            )
            connection.execute(
                text("DELETE FROM erp.staff WHERE id = ANY(:ids)"),
                {"ids": staff_ids},
            )
    except Exception:
        _fail("W1B_POSTGRES_CLEANUP_MISSING: synthetic fixture cleanup failed")


def _current_account(case: ActorCase) -> Any:
    from app.core.auth import CurrentAccount

    return CurrentAccount(case.account_id, case.display_name, case.role_code)


@contextmanager
def _real_api(engine: Engine, account: Any | None) -> Iterator[None]:
    from app.api.dependencies import get_current_account, get_db_session
    from app.main import app

    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    def db_override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    if account is not None:
        app.dependency_overrides[get_current_account] = lambda account=account: account
    app.dependency_overrides[get_db_session] = db_override
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _csrf_headers(client: TestClient) -> dict[str, str]:
    from app.core.auth import csrf_token_signature
    from app.core.security import generate_csrf_token, generate_session_token
    from app.core.settings import get_settings

    settings = get_settings()
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    signature = csrf_token_signature(
        session_token,
        csrf_token,
        settings.secret_value("csrf_signing_key"),
    )
    csrf_cookie = f"{csrf_token}.{signature}"
    client.cookies.set(settings.session_cookie_name, session_token)
    client.cookies.set(settings.csrf_cookie_name, csrf_cookie)
    return {settings.csrf_header_name: csrf_cookie}


def _assert_safe_response(
    response: Any, marker: str, canary: str | tuple[str, ...] | None = None
) -> None:
    text_body = str(response.text).lower()
    canaries = () if canary is None else (canary,) if isinstance(canary, str) else canary
    if any(value.lower() in text_body for value in canaries):
        _fail(marker + ": synthetic sensitive canary leaked")
    if any(term in text_body for term in UNSAFE_RESPONSE_TERMS):
        _fail(marker + ": SQL/traceback/internal error leaked")
    try:
        payload = response.json()
    except ValueError:
        _fail(marker + ": error response is not structured JSON")
    if not isinstance(payload, (dict, list)):
        _fail(marker + ": error response is not structured")


def _assert_safe_logs(
    caplog: pytest.LogCaptureFixture,
    marker: str,
    canary: str | tuple[str, ...] | None = None,
) -> None:
    formatted_parts: list[str] = []
    formatter = logging.Formatter()
    for record in caplog.records:
        message = record.getMessage()
        transport_status_suffix = ' 500 Internal Server Error"'
        if (
            record.name == "httpx"
            and message.startswith("HTTP Request:")
            and message.endswith(transport_status_suffix)
        ):
            message = message[: -len(transport_status_suffix)] + ' 500 <status-reason>"'
        formatted_parts.extend((message, record.exc_text or ""))
        if record.exc_info:
            try:
                formatted_parts.append(formatter.formatException(record.exc_info))
            except Exception:
                _fail(marker + ": captured record.exc_info could not be formatted")
        if record.stack_info:
            formatted_parts.append(record.stack_info)
    log_body = "\n".join(formatted_parts).lower()
    canaries = () if canary is None else (canary,) if isinstance(canary, str) else canary
    if any(value.lower() in log_body for value in canaries):
        _fail(marker + ": synthetic sensitive canary leaked to captured logs")
    if any(term in log_body for term in UNSAFE_RESPONSE_TERMS):
        _fail(marker + ": SQL/traceback/stack/internal error leaked to captured logs")


def _assert_error_envelope(
    response: Any,
    expected_status: int,
    marker: str,
    *,
    expected_code: str | None = None,
    canary: str | tuple[str, ...] | None = None,
) -> None:
    if response.status_code != expected_status:
        _assert_safe_response(response, marker, canary)
        _fail(marker + f": expected HTTP {expected_status}, got {response.status_code}")
    _assert_safe_response(response, marker, canary)
    try:
        payload = response.json()
    except ValueError:
        _fail(marker + ": error response is not JSON")
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        _fail(marker + ": error response envelope is not an object")
    error = payload["error"]
    if not isinstance(error.get("code"), str) or not error["code"]:
        _fail(marker + ": error envelope code is missing")
    if not isinstance(error.get("message"), str) or not error["message"]:
        _fail(marker + ": error envelope message is missing")
    if not isinstance(payload.get("field_errors"), list):
        _fail(marker + ": error envelope field_errors is not a list")
    if not isinstance(payload.get("details"), dict):
        _fail(marker + ": error envelope details is not an object")
    if not isinstance(payload.get("request_id"), str) or not payload["request_id"]:
        _fail(marker + ": error envelope request_id is missing")
    if expected_code is not None and error["code"] != expected_code:
        _fail(marker + ": expected error code " + expected_code + ", got " + str(error["code"]))


def _nested_value(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _nested_value(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _nested_value(value, key)
            if found is not None:
                return found
    return None


def _find_record(payload: Any, record_id: int) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if payload.get("id") == record_id:
            return payload
        for value in payload.values():
            found = _find_record(value, record_id)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_record(value, record_id)
            if found is not None:
                return found
    return None


def _history_replacement_payload(
    document: dict[str, Any],
    collection_path: str,
    expected_row_version: int,
    values: Mapping[str, Any],
    marker: str,
) -> dict[str, Any]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail(marker + ": OpenAPI paths are unavailable")
    action_paths = _history_action_paths(paths, marker)
    candidates = sorted(
        path
        for path, action in action_paths.items()
        if action == "replacements" and path.startswith(collection_path + "/")
    )
    if len(candidates) != 1:
        _fail(marker + ": exact replacements action path is not unique")
    action_path = candidates[0]
    operations = paths.get(action_path)
    if not isinstance(operations, dict) or not isinstance(operations.get("post"), dict):
        _fail(marker + ": exact replacements action operation is unavailable")
    operation = operations["post"]
    schema = _operation_request_schema(document, operation, marker)
    properties = _schema_properties(document, schema, marker)
    required = _schema_required(document, schema, marker)
    if "expected_row_version" not in properties or "expected_row_version" not in required:
        _fail(marker + ": replacements action must require expected_row_version")

    def build(current_schema: Any, candidates: Mapping[str, Any]) -> dict[str, Any]:
        properties = _schema_properties(document, current_schema, marker)
        required = _schema_required(document, current_schema, marker)
        result: dict[str, Any] = {}
        for name in required:
            if name == "expected_row_version":
                result[name] = expected_row_version
                continue
            if name not in candidates or name not in properties:
                _fail(marker + ": replacement request has an unsupported required field: " + name)
            value = candidates[name]
            if isinstance(value, Mapping):
                result[name] = build(properties[name], value)
            else:
                result[name] = value
        for name, value in candidates.items():
            if name in result or name not in properties:
                continue
            if isinstance(value, Mapping):
                result[name] = build(properties[name], value)
            else:
                result[name] = value
        return result

    payload = build(schema, {"expected_row_version": expected_row_version, **values})
    if payload.get("expected_row_version") != expected_row_version:
        _fail(marker + ": payload lost the exact expected_row_version value")
    return payload


def _response_id(response: Any, marker: str) -> int:
    try:
        payload = response.json()
    except ValueError:
        _fail(marker + ": response is not JSON")
    value = _nested_value(payload, "id")
    if not isinstance(value, int):
        _fail(marker + ": response does not contain an integer id")
    return value


def _response_replacement_id(response: Any, marker: str) -> int:
    try:
        payload = response.json()
    except ValueError:
        _fail(marker + ": replacement response is not JSON")
    values: list[int] = []

    def visit(current: Any) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                if "replacement" in str(key).lower() and str(key).lower().endswith("id"):
                    if isinstance(value, int):
                        values.append(value)
                visit(value)
        elif isinstance(current, list):
            for value in current:
                visit(value)

    visit(payload)
    if len(values) != 1:
        _fail(marker + ": response does not contain one replacement linkage id")
    return values[0]


def _response_row_version(response: Any, marker: str) -> int:
    try:
        payload = response.json()
    except ValueError:
        _fail(marker + ": response is not JSON")
    value = _nested_value(payload, "row_version")
    if not isinstance(value, int) or value <= 0:
        _fail(marker + ": response does not contain a positive row_version")
    return value


def _response_error_code(response: Any, marker: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        _fail(marker + ": response is not JSON")
    value = _nested_value(payload, "code")
    if not isinstance(value, str) or not value:
        _fail(marker + ": response does not contain a stable error code")
    return value


def _install_constraint_failure_trigger(
    engine: Engine, canaries: Mapping[str, str]
) -> tuple[str, str]:
    if set(canaries) != {"name", "address", "home_phone", "mobile_phone"} or any(
        not isinstance(value, str) or not value.startswith("TEST_W1B_")
        for value in canaries.values()
    ):
        _fail("W1B_API_500_HARNESS_MISSING: forced-500 canary fields are incomplete")
    suffix = uuid4().hex
    function_name = f"w1b_test_constraint_failure_{suffix}"
    trigger_name = f"w1b_test_constraint_failure_trigger_{suffix}"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    CREATE FUNCTION erp.{function_name}() RETURNS trigger
                    LANGUAGE plpgsql AS $$
                    BEGIN
                        RAISE EXCEPTION USING
                            ERRCODE = 'P0001',
                            MESSAGE = 'TEST_W1B_CONSTRAINT_CANARY',
                            DETAIL = format(
                                'name=%s|address=%s|home_phone=%s|mobile_phone=%s',
                                NEW.name,
                                NEW.address,
                                NEW.home_phone,
                                NEW.mobile_phone
                            );
                    END
                    $$;
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    CREATE TRIGGER {trigger_name}
                    BEFORE INSERT ON erp.recipient
                    FOR EACH ROW EXECUTE FUNCTION erp.{function_name}();
                    """
                )
            )
    except Exception:
        try:
            with engine.begin() as connection:
                connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON erp.recipient"))
                connection.execute(text(f"DROP FUNCTION IF EXISTS erp.{function_name}()"))
        except Exception:
            _fail("W1B_API_500_HARNESS_MISSING: constraint failure trigger cleanup failed")
        _fail("W1B_API_500_HARNESS_MISSING: constraint failure trigger could not be installed")
    return function_name, trigger_name


def _remove_constraint_failure_trigger(engine: Engine, names: tuple[str, str]) -> None:
    function_name, trigger_name = names
    try:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON erp.recipient"))
            connection.execute(text(f"DROP FUNCTION IF EXISTS erp.{function_name}()"))
    except Exception:
        _fail("W1B_API_500_HARNESS_MISSING: constraint failure trigger cleanup failed")


def _load_recipient_import_operations(marker: str) -> tuple[Any, Any, Any, Any]:
    try:
        module = importlib.import_module("app.domains.recipient.legacy_import")
    except Exception:
        _fail(marker + ": W1A-parity recipient legacy_import module is absent")

    operation_names = ("prepare", "apply", "invalidate_mapping", "replace_mapping")
    operations = tuple(getattr(module, name, None) for name in operation_names)
    missing = [
        name
        for name, operation in zip(operation_names, operations, strict=True)
        if not callable(operation)
    ]
    if missing:
        _fail(marker + ": missing W1A-parity importer operations " + ",".join(missing))
    return operations


def _invoke_importer(function: Any, candidates: Mapping[str, Any], marker: str) -> Any:
    try:
        signature = inspect.signature(function)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        kwargs = (
            dict(candidates)
            if accepts_kwargs
            else {name: value for name, value in candidates.items() if name in parameters}
        )
        missing = [
            parameter.name
            for parameter in parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            and parameter.name not in kwargs
        ]
        if missing:
            _fail(marker + ": importer signature has unsupported required fields")
        return function(**kwargs)
    except pytest.fail.Exception:
        raise
    except Exception:
        _fail(marker + ": importer call raised an unsafe or unexpected exception")


def _summary_payload(result: Any, marker: str) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = result
    else:
        model_dump = getattr(result, "model_dump", None)
        payload = model_dump() if callable(model_dump) else None
    if not isinstance(payload, dict):
        _fail(marker + ": prepare result is not a structured summary")
    return payload


def _mapping_row(
    connection: Any,
    mapping: Table,
    source: str,
    key: str | None = None,
    *,
    attachment_key: str | None = None,
    mapping_id: int | None = None,
    active: bool | None = None,
    marker: str = "W1B_REC_02_MAPPING_LOOKUP_MISSING",
) -> dict[str, Any] | None:
    predicates = [mapping.c.source_system_code == source]
    if mapping_id is not None:
        predicates.append(mapping.c.id == mapping_id)
    else:
        predicates.append(
            mapping.c.legacy_recipient_key.is_(None)
            if key is None
            else mapping.c.legacy_recipient_key == key
        )
        if attachment_key is not None:
            predicates.append(mapping.c.legacy_attachment_key == attachment_key)
    if active is True:
        predicates.append(mapping.c.invalidated_at_utc.is_(None))
    elif active is False:
        predicates.append(mapping.c.invalidated_at_utc.is_not(None))
    elif mapping_id is None:
        _fail(marker + ": source/key mapping lookup requires an active state or exact id")
    result = connection.execute(mapping.select().where(*predicates))
    rows = result.mappings().all()
    if len(rows) > 1:
        _fail(marker + ": source/key mapping lookup is ambiguous")
    return dict(rows[0]) if rows else None


def _import_row(
    key: str | None,
    name: str,
    *,
    attachment_key: str | None = None,
    source_memo: str = SYNTHETIC_SOURCE_MEMO,
) -> dict[str, Any]:
    return {
        "legacy_recipient_key": key,
        "legacy_attachment_key": attachment_key,
        "name": name,
        "birth_date": "2000-01-01",
        "sex_code": "MALE",
        "postal_code": None,
        "address": None,
        "home_phone": None,
        "mobile_phone": None,
        "source_memo": source_memo,
    }


def test_w1b_00_alembic_graph_and_existing_chain_are_fixed() -> None:
    _require_w1b_revision()


def test_w1b_01_offline_fresh_upgrade_is_fixed() -> None:
    _, w1b_revision, allowed_revisions = _require_w1b_revision()
    _run_offline_upgrade(w1b_revision)
    _run_fresh_postgres_catalog(w1b_revision, allowed_revisions)


def test_w1b_02_sqlalchemy_metadata_is_structurally_fixed() -> None:
    _require_metadata_contract()


def test_w1b_03_operation_openapi_contract_is_structurally_fixed() -> None:
    document, item_path = _require_api_operations()
    _assert_w1b_public_schema_contract(document, item_path)


def test_w1b_generated_openapi_types_check_is_exact() -> None:
    document, item_path = _require_api_operations()
    _assert_w1b_public_schema_contract(document, item_path)
    generator = REPO_ROOT / "scripts" / "generate-openapi-types.ps1"
    generated = REPO_ROOT / "frontend" / "src" / "generated" / "sswcenter-api.ts"
    if not generator.is_file() or not generated.is_file():
        _fail("W1B_GENERATED_CONTRACT_MISSING: generator or checked-in OpenAPI types are absent")
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "scripts/generate-openapi-types.ps1",
                "-Check",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("W1B_GENERATED_CONTRACT_MISSING: generator check could not run")
    if result.returncode != 0:
        _fail(
            "W1B_GENERATED_CONTRACT_MISSING: checked-in OpenAPI types differ from generator output"
        )


def test_w1b_04_actual_postgres_period_boundaries_are_fixed() -> None:
    _, _, allowed_revisions = _require_w1b_revision()
    tables = _require_metadata_contract()
    engine = _postgres_engine()
    token = uuid4().hex
    cases = _make_actor_cases(engine, token)
    recipient_ids: set[int] = set()
    try:
        _require_db_revision(engine, allowed_revisions)
        recipient = tables["recipient"]
        guardian = tables["recipient_guardian"]
        primary = tables["recipient_guardian_primary_period"]
        payer = tables["recipient_payer_snapshot"]
        primary_exclusion_names = _period_exclusion_catalog_names(
            engine,
            "recipient_guardian_primary_period",
            "W1B_PG_EXCLUSION_CATALOG_MISSING",
        )
        with engine.begin() as connection:
            recipient_id = _insert_row(
                connection,
                recipient,
                {"name": SYNTHETIC_NAME, "birth_date": SYNTHETIC_BIRTH_DATE, "sex_code": "TEST"},
                cases["admin"].account_id,
            )
            guardian_id = _insert_row(
                connection,
                guardian,
                {"recipient_id": recipient_id, "name": "TEST_W1B_GUARDIAN_CANARY"},
                cases["admin"].account_id,
            )
            race_guardian_id = _insert_row(
                connection,
                guardian,
                {"recipient_id": recipient_id, "name": "TEST_W1B_RACE_GUARDIAN_CANARY"},
                cases["admin"].account_id,
            )
            other_recipient_id = _insert_row(
                connection,
                recipient,
                {
                    "name": "TEST_W1B_OTHER_RECIPIENT_CANARY",
                    "birth_date": SYNTHETIC_BIRTH_DATE,
                    "sex_code": "TEST",
                },
                cases["admin"].account_id,
            )
            other_guardian_id = _insert_row(
                connection,
                guardian,
                {
                    "recipient_id": other_recipient_id,
                    "name": "TEST_W1B_OTHER_GUARDIAN_CANARY",
                },
                cases["admin"].account_id,
            )
        recipient_ids.update({recipient_id, other_recipient_id})
        recipient_no_value = _synthetic_recipient_no(recipient.c.recipient_no, 1)
        with engine.connect() as connection:
            initial_numbers = connection.execute(
                recipient.select()
                .with_only_columns(recipient.c.id, recipient.c.recipient_no)
                .where(recipient.c.id.in_([recipient_id, other_recipient_id]))
            ).all()
        if any(row[1] is not None for row in initial_numbers):
            _fail("W1B_RECIPIENT_NO_NULL_CONTRACT_MISSING: fresh recipient_no is not NULL")
        with engine.begin() as connection:
            connection.execute(
                recipient.update()
                .where(recipient.c.id == recipient_id)
                .values(recipient_no=recipient_no_value)
            )
        _expected_update_failure(
            engine,
            recipient.update()
            .where(recipient.c.id == other_recipient_id)
            .values(recipient_no=recipient_no_value),
            "W1B_RECIPIENT_NO_UNIQUE_MISSING: duplicate non-NULL recipient_no was accepted",
        )
        _expected_update_failure(
            engine,
            recipient.update()
            .where(recipient.c.id == recipient_id)
            .values(recipient_no=_synthetic_recipient_no(recipient.c.recipient_no, 2)),
            "W1B_RECIPIENT_NO_IMMUTABLE_MISSING: issued recipient_no changed",
        )
        _expected_update_failure(
            engine,
            recipient.update().where(recipient.c.id == recipient_id).values(recipient_no=None),
            "W1B_RECIPIENT_NO_IMMUTABLE_MISSING: issued recipient_no was cleared",
        )
        base = {"recipient_id": recipient_id, "guardian_id": guardian_id}
        _expected_insert_failure(
            engine,
            primary,
            {
                **base,
                "guardian_id": other_guardian_id,
                "start_date": date(2029, 1, 1),
                "end_date": date(2029, 1, 2),
            },
            cases["admin"].account_id,
            "W1B_PG_COMPOSITE_GUARDIAN_FK_NOT_ENFORCED: cross-recipient guardian was accepted",
        )
        primary_period_id = _insert_period(
            engine,
            primary,
            recipient_id=recipient_id,
            guardian_id=guardian_id,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 3),
            actor_id=cases["admin"].account_id,
        )
        _expected_insert_failure(
            engine,
            primary,
            {**base, "start_date": date(2030, 1, 3), "end_date": date(2030, 1, 3)},
            cases["admin"].account_id,
            "W1B_PG_SAME_DAY_OVERLAP_NOT_BLOCKED: same-day period overlap was accepted",
        )
        try:
            _insert_period(
                engine,
                primary,
                recipient_id=recipient_id,
                guardian_id=guardian_id,
                start_date=date(2030, 1, 4),
                end_date=date(2030, 1, 5),
                actor_id=cases["admin"].account_id,
            )
        except SQLAlchemyError:
            _fail("W1B_PG_NEXT_DAY_ADJACENCY_BLOCKED: next-day adjacency was rejected")
        _insert_period(
            engine,
            primary,
            recipient_id=recipient_id,
            guardian_id=guardian_id,
            start_date=date(2031, 1, 1),
            end_date=None,
            actor_id=cases["admin"].account_id,
        )
        _expected_insert_failure(
            engine,
            primary,
            {**base, "start_date": date(2031, 2, 1), "end_date": None},
            cases["admin"].account_id,
            "W1B_PG_OPEN_ENDED_OVERLAP_NOT_BLOCKED: open-ended overlap was accepted",
        )
        _expected_insert_failure(
            engine,
            primary,
            {**base, "start_date": date(2032, 1, 2), "end_date": date(2032, 1, 1)},
            cases["admin"].account_id,
            "W1B_PG_INVALID_RANGE_ACCEPTED: start greater than end was accepted",
        )
        invalidated_id = _insert_period(
            engine,
            primary,
            recipient_id=recipient_id,
            guardian_id=guardian_id,
            start_date=date(2028, 1, 1),
            end_date=date(2028, 1, 3),
            actor_id=cases["admin"].account_id,
        )
        with engine.begin() as connection:
            if "invalidated_at_utc" not in primary.c:
                _fail("W1B_PG_INVALIDATION_MISSING: period has no invalidation column")
            connection.execute(
                primary.update()
                .where(primary.c.id == invalidated_id)
                .values(invalidated_at_utc=datetime.now(UTC))
            )
        try:
            _insert_period(
                engine,
                primary,
                recipient_id=recipient_id,
                guardian_id=guardian_id,
                start_date=date(2028, 1, 1),
                end_date=date(2028, 1, 3),
                actor_id=cases["admin"].account_id,
            )
        except SQLAlchemyError:
            _fail("W1B_PG_INVALIDATED_ROW_NOT_EXCLUDED: invalidated period still blocks overlap")

        _run_primary_race(
            engine,
            primary,
            recipient_id=recipient_id,
            guardian_ids=(guardian_id, race_guardian_id),
            exclusion_names=primary_exclusion_names,
            actor_id=cases["admin"].account_id,
            marker="W1B_PG_PRIMARY_RACE_MISSING",
        )

        payer_id = _insert_period(
            engine,
            payer,
            recipient_id=recipient_id,
            guardian_id=None,
            start_date=date(2040, 1, 1),
            end_date=date(2040, 1, 3),
            actor_id=cases["admin"].account_id,
            extra={"name": "TEST_W1B_PAYER"},
        )
        with engine.connect() as connection:
            before_fingerprint, before_version, before_fields = _payer_snapshot_signature(
                connection,
                payer,
                payer_id,
                "W1B_PG_PAYER_SNAPSHOT_IMMUTABILITY_MISSING",
            )
        with engine.begin() as connection:
            connection.execute(
                guardian.update()
                .where(guardian.c.id == guardian_id)
                .values(name="TEST_W1B_GUARDIAN_CHANGED")
            )
            connection.execute(
                primary.update()
                .where(primary.c.id == primary_period_id)
                .values(end_date=date(2030, 1, 2), row_version=primary.c.row_version + 1)
            )
        with engine.connect() as connection:
            after_fingerprint, after_version, after_fields = _payer_snapshot_signature(
                connection,
                payer,
                payer_id,
                "W1B_PG_PAYER_SNAPSHOT_IMMUTABILITY_MISSING",
            )
        if (
            before_fingerprint != after_fingerprint
            or before_version != after_version
            or before_fields != after_fields
        ):
            _fail(
                "W1B_PG_PAYER_SNAPSHOT_IMMUTABILITY_MISSING: guardian/primary change mutated "
                "payer snapshot fields, hash, or row_version"
            )
        _assert_no_payer_autosync_triggers(engine, "W1B_PG_PAYER_AUTOSYNC_TRIGGER_FOUND")
        _expected_insert_failure(
            engine,
            payer,
            {
                "recipient_id": recipient_id,
                "start_date": date(2040, 1, 3),
                "end_date": date(2040, 1, 3),
                "name": "TEST_W1B_PAYER",
            },
            cases["admin"].account_id,
            "W1B_PG_PAYER_SAME_DAY_OVERLAP_NOT_BLOCKED: payer overlap was accepted",
        )
        try:
            _insert_period(
                engine,
                payer,
                recipient_id=recipient_id,
                guardian_id=None,
                start_date=date(2040, 1, 4),
                end_date=date(2040, 1, 5),
                actor_id=cases["admin"].account_id,
                extra={"name": "TEST_W1B_PAYER_NEXT_DAY"},
            )
        except SQLAlchemyError:
            _fail("W1B_PG_PAYER_NEXT_DAY_ADJACENCY_BLOCKED: payer adjacency was rejected")
        _insert_period(
            engine,
            payer,
            recipient_id=recipient_id,
            guardian_id=None,
            start_date=date(2041, 1, 1),
            end_date=None,
            actor_id=cases["admin"].account_id,
            extra={"name": "TEST_W1B_PAYER_OPEN"},
        )
        _expected_insert_failure(
            engine,
            payer,
            {
                "recipient_id": recipient_id,
                "start_date": date(2041, 2, 1),
                "end_date": None,
                "name": "TEST_W1B_PAYER_OPEN_CONFLICT",
            },
            cases["admin"].account_id,
            "W1B_PG_PAYER_OPEN_ENDED_OVERLAP_NOT_BLOCKED: payer open-ended overlap was accepted",
        )
        _expected_insert_failure(
            engine,
            payer,
            {
                "recipient_id": recipient_id,
                "start_date": date(2042, 1, 2),
                "end_date": date(2042, 1, 1),
                "name": "TEST_W1B_PAYER_REVERSE",
            },
            cases["admin"].account_id,
            "W1B_PG_PAYER_INVALID_RANGE_ACCEPTED: payer start greater than end was accepted",
        )
        payer_invalidated_id = _insert_period(
            engine,
            payer,
            recipient_id=recipient_id,
            guardian_id=None,
            start_date=date(2039, 1, 1),
            end_date=date(2039, 1, 3),
            actor_id=cases["admin"].account_id,
            extra={"name": "TEST_W1B_PAYER_INVALIDATED"},
        )
        with engine.begin() as connection:
            connection.execute(
                payer.update()
                .where(payer.c.id == payer_invalidated_id)
                .values(invalidated_at_utc=datetime.now(UTC))
            )
        try:
            _insert_period(
                engine,
                payer,
                recipient_id=recipient_id,
                guardian_id=None,
                start_date=date(2039, 1, 1),
                end_date=date(2039, 1, 3),
                actor_id=cases["admin"].account_id,
                extra={"name": "TEST_W1B_PAYER_REUSE"},
            )
        except SQLAlchemyError:
            _fail(
                "W1B_PG_PAYER_INVALIDATED_ROW_NOT_EXCLUDED: invalidated payer still blocked reuse"
            )
    finally:
        _cleanup(engine, cases, recipient_ids)
        engine.dispose()


def test_w1b_05_actual_api_acl_csrf_version_and_safe_errors_are_fixed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    document, item_path = _require_api_operations()
    _assert_w1b_public_schema_contract(document, item_path)
    _, _, allowed_revisions = _require_w1b_revision()
    tables = _require_metadata_contract()
    engine = _postgres_engine()
    token = uuid4().hex
    cases = _make_actor_cases(engine, token)
    recipient_ids: set[int] = set()
    try:
        caplog.set_level(logging.DEBUG)
        _require_db_revision(engine, allowed_revisions)
        guardian_table = tables["recipient_guardian"]
        primary_table = tables["recipient_guardian_primary_period"]
        payer_table = tables["recipient_payer_snapshot"]
        from app.main import app

        with _real_api(engine, None):
            client = TestClient(app, raise_server_exceptions=False)
            unauthenticated = client.get(RECIPIENT_COLLECTION_PATH)
            if unauthenticated.status_code != 401:
                _assert_safe_response(
                    unauthenticated,
                    "W1B_API_UNAUTHENTICATED_MISSING",
                    SYNTHETIC_NAME,
                )
                _fail("W1B_API_UNAUTHENTICATED_MISSING: unauthenticated GET was not 401")

        with _real_api(engine, _current_account(cases["user"])):
            client = TestClient(app, raise_server_exceptions=False)
            forbidden = client.get(RECIPIENT_COLLECTION_PATH)
            if forbidden.status_code != 403:
                _assert_safe_response(forbidden, "W1B_API_PERMISSION_MISSING", SYNTHETIC_NAME)
                _fail("W1B_API_PERMISSION_MISSING: user without permission was not denied")

        with _real_api(engine, _current_account(cases["admin"])):
            client = TestClient(app, raise_server_exceptions=False)
            admin_get = client.get(RECIPIENT_COLLECTION_PATH)
            if admin_get.status_code != 200:
                _assert_safe_response(admin_get, "W1B_API_ADMIN_INHERITANCE_MISSING")
                _fail("W1B_API_ADMIN_INHERITANCE_MISSING: ADMIN GET was not allowed")

        with _real_api(engine, _current_account(cases["view"])):
            client = TestClient(app, raise_server_exceptions=False)
            view_get = client.get(RECIPIENT_COLLECTION_PATH)
            if view_get.status_code != 200:
                _assert_safe_response(view_get, "W1B_API_VIEW_READ_MISSING", SYNTHETIC_NAME)
                _fail("W1B_API_VIEW_READ_MISSING: VIEW GET was not allowed")

        with _real_api(engine, _current_account(cases["view"])):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                RECIPIENT_COLLECTION_PATH,
                json={"name": SYNTHETIC_NAME, "birth_date": "2000-01-01", "sex_code": "MALE"},
                headers=_csrf_headers(client),
            )
            if response.status_code != 403:
                _assert_safe_response(response, "W1B_API_VIEW_MUTATION_MISSING", SYNTHETIC_NAME)
                _fail("W1B_API_VIEW_MUTATION_MISSING: RECIPIENT_VIEW mutation was not denied")

        with _real_api(engine, _current_account(cases["manage"])):
            client = TestClient(app, raise_server_exceptions=False)
            no_csrf = client.post(
                RECIPIENT_COLLECTION_PATH,
                json={"name": SYNTHETIC_NAME, "birth_date": "2000-01-01", "sex_code": "MALE"},
            )
            if no_csrf.status_code != 403:
                _assert_safe_response(no_csrf, "W1B_API_CSRF_MISSING", SYNTHETIC_NAME)
                _fail("W1B_API_CSRF_MISSING: mutation without CSRF was not denied")
            recipient_payload = {
                "name": SYNTHETIC_NAME,
                "birth_date": "2000-01-01",
                "sex_code": "MALE",
                "postal_code": SYNTHETIC_POSTAL_CODE,
                "address": SYNTHETIC_ADDRESS,
                "home_phone": SYNTHETIC_HOME_PHONE,
                "mobile_phone": SYNTHETIC_MOBILE_PHONE,
            }
            created = client.post(
                RECIPIENT_COLLECTION_PATH,
                json=recipient_payload,
                headers=_csrf_headers(client),
            )
            if created.status_code != 201:
                _assert_safe_response(created, "W1B_API_RECIPIENT_CREATE_MISSING", SYNTHETIC_NAME)
                _fail("W1B_API_RECIPIENT_CREATE_MISSING: managed create did not return 201")
            recipient_id = _response_id(created, "W1B_API_RECIPIENT_CREATE_MISSING")
            recipient_ids.add(recipient_id)
            row_version = _response_row_version(created, "W1B_API_ROW_VERSION_MISSING")
            with engine.connect() as connection:
                _assert_single_audit_event(
                    _audit_rows(connection, "RECIPIENT", recipient_id),
                    action_code="RECIPIENT_CREATE",
                    entity_type="RECIPIENT",
                    entity_pk=recipient_id,
                    actor_account_id=cases["manage"].account_id,
                    marker="W1B_API_RECIPIENT_AUDIT_MISSING",
                    expected_before=None,
                    expected_after={"row_version": row_version},
                )
            body = created.json()
            if _nested_value(body, "recipient_no") is not None:
                _fail("W1B_API_RECIPIENT_NO_CONTRACT_MISSING: initial recipient_no is not null")
            item_path = f"/api/v1/recipients/{recipient_id}"
            detail = client.get(item_path)
            listed = client.get(RECIPIENT_COLLECTION_PATH)
            if detail.status_code != 200 or listed.status_code != 200:
                _fail("W1B_API_CONTACT_READBACK_MISSING: list/detail readback was not successful")
            for source_name, payload in (("detail", detail.json()), ("list", listed.json())):
                record = _find_record(payload, recipient_id)
                if record is None or any(
                    record.get(field) != value
                    for field, value in recipient_payload.items()
                    if field != "birth_date" and field != "sex_code"
                ):
                    _fail(
                        "W1B_API_CONTACT_READBACK_MISSING: " + source_name + " lost contact fields"
                    )
            with engine.connect() as connection:
                stored_recipient = (
                    connection.execute(
                        tables["recipient"].select().where(tables["recipient"].c.id == recipient_id)
                    )
                    .mappings()
                    .one_or_none()
                )
            if stored_recipient is None or any(
                stored_recipient.get(field) != value
                for field, value in recipient_payload.items()
                if field in {"postal_code", "address", "home_phone", "mobile_phone"}
            ):
                _fail(
                    "W1B_API_CONTACT_PG_READBACK_MISSING: contact fields were not stored separately"
                )
            if stored_recipient.get("row_version") != row_version:
                _fail(
                    "W1B_API_ROW_VERSION_MISSING: create response and PostgreSQL row_version differ"
                )
            with engine.connect() as connection:
                recipient_audit_before_update = _audit_rows(connection, "RECIPIENT", recipient_id)
            updated = client.patch(
                item_path,
                json={"name": "TEST_W1B_RECIPIENT_UPDATED", "expected_row_version": row_version},
                headers=_csrf_headers(client),
            )
            if updated.status_code != 200:
                _assert_safe_response(updated, "W1B_API_ROW_VERSION_MISSING", SYNTHETIC_NAME)
                _fail("W1B_API_ROW_VERSION_MISSING: managed update did not accept expected version")
            updated_row_version = _response_row_version(updated, "W1B_API_ROW_VERSION_MISSING")
            if updated_row_version != row_version + 1:
                _fail("W1B_API_ROW_VERSION_MISSING: update response did not advance exactly once")
            with engine.connect() as connection:
                recipient_before_stale = _exact_row_by_id(
                    connection,
                    tables["recipient"],
                    recipient_id,
                    "W1B_API_ROW_VERSION_MISSING",
                )
                if (
                    recipient_before_stale.get("row_version") != row_version + 1
                    or recipient_before_stale.get("name") != "TEST_W1B_RECIPIENT_UPDATED"
                ):
                    _fail(
                        "W1B_API_ROW_VERSION_MISSING: PostgreSQL update did not persist "
                        "the exact name and row_version"
                    )
                _assert_audit_append(
                    recipient_audit_before_update,
                    _audit_rows(connection, "RECIPIENT", recipient_id),
                    action_code="RECIPIENT_UPDATE",
                    entity_type="RECIPIENT",
                    entity_pk=recipient_id,
                    actor_account_id=cases["manage"].account_id,
                    marker="W1B_API_RECIPIENT_UPDATE_AUDIT_MISSING",
                    expected_before={"row_version": row_version},
                    expected_after={"row_version": updated_row_version},
                )
                recipient_audit_before_stale = _audit_rows(connection, "RECIPIENT", recipient_id)
                recipient_ids_before_stale = _table_row_ids(
                    connection,
                    tables["recipient"],
                    "W1B_API_STALE_VERSION_MUTATED",
                )
                all_audit_before_stale = _all_audit_rows(connection)
            stale = client.patch(
                item_path,
                json={"name": "TEST_W1B_STALE_CANARY", "expected_row_version": row_version},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                stale,
                409,
                "W1B_API_STALE_VERSION_MISSING",
                expected_code="ROW_VERSION_CONFLICT",
                canary=SYNTHETIC_NAME,
            )
            with engine.connect() as connection:
                _assert_exact_row_unchanged(
                    connection,
                    tables["recipient"],
                    recipient_id,
                    recipient_before_stale,
                    "W1B_API_STALE_VERSION_MUTATED",
                )
                if (
                    _table_row_ids(
                        connection,
                        tables["recipient"],
                        "W1B_API_STALE_VERSION_MUTATED",
                    )
                    != recipient_ids_before_stale
                ):
                    _fail("W1B_API_STALE_VERSION_MUTATED: stale request changed recipient row set")
                _assert_no_audit_change(
                    recipient_audit_before_stale,
                    _audit_rows(connection, "RECIPIENT", recipient_id),
                    "W1B_API_STALE_VERSION_AUDIT_MUTATED",
                )
                _assert_no_audit_change(
                    all_audit_before_stale,
                    _all_audit_rows(connection),
                    "W1B_API_STALE_VERSION_AUDIT_MUTATED",
                )
            guardians_path = f"/api/v1/recipients/{recipient_id}/guardians"
            primary_path = f"/api/v1/recipients/{recipient_id}/primary-guardian-periods"
            payer_path = f"/api/v1/recipients/{recipient_id}/payer-snapshots"
            from app.api.dependencies import get_current_account

            saved_account_override = app.dependency_overrides[get_current_account]
            try:
                app.dependency_overrides[get_current_account] = lambda: _current_account(
                    cases["user"]
                )
                nested_unauthorized = client.get(guardians_path)
                if nested_unauthorized.status_code != 403:
                    _fail("W1B_API_NESTED_PERMISSION_MISSING: no-permission nested GET was allowed")
                app.dependency_overrides[get_current_account] = lambda: _current_account(
                    cases["view"]
                )
                nested_view_mutation = client.post(
                    guardians_path,
                    json={"name": "TEST_W1B_NESTED_VIEW_GUARDIAN"},
                    headers=_csrf_headers(client),
                )
                if nested_view_mutation.status_code != 403:
                    _fail("W1B_API_NESTED_VIEW_MUTATION_MISSING: VIEW nested mutation was allowed")
            finally:
                app.dependency_overrides[get_current_account] = saved_account_override
            nested_no_csrf = client.post(
                guardians_path,
                json={"name": "TEST_W1B_NESTED_NO_CSRF_GUARDIAN"},
            )
            if nested_no_csrf.status_code != 403:
                _fail("W1B_API_NESTED_CSRF_MISSING: nested mutation without CSRF was allowed")
            first_guardian_response = client.post(
                guardians_path,
                json={"name": "TEST_W1B_API_GUARDIAN_NAME_ONLY"},
                headers=_csrf_headers(client),
            )
            second_guardian_response = client.post(
                guardians_path,
                json={
                    "name": "TEST_W1B_API_GUARDIAN_OPTIONAL",
                    "phone": SYNTHETIC_GUARDIAN_PHONE,
                    "address": SYNTHETIC_GUARDIAN_ADDRESS,
                    "relationship_text": SYNTHETIC_GUARDIAN_RELATIONSHIP,
                },
                headers=_csrf_headers(client),
            )
            if (
                first_guardian_response.status_code != 201
                or second_guardian_response.status_code != 201
            ):
                _fail("W1B_API_GUARDIAN_LIFECYCLE_MISSING: name-only guardian create failed")
            first_guardian_id = _response_id(
                first_guardian_response, "W1B_API_GUARDIAN_LIFECYCLE_MISSING"
            )
            second_guardian_id = _response_id(
                second_guardian_response, "W1B_API_GUARDIAN_LIFECYCLE_MISSING"
            )
            for guardian_id, response in (
                (first_guardian_id, first_guardian_response),
                (second_guardian_id, second_guardian_response),
            ):
                with engine.connect() as connection:
                    _assert_single_audit_event(
                        _audit_rows(connection, "RECIPIENT_GUARDIAN", guardian_id),
                        action_code="RECIPIENT_GUARDIAN_CREATE",
                        entity_type="RECIPIENT_GUARDIAN",
                        entity_pk=guardian_id,
                        actor_account_id=cases["manage"].account_id,
                        marker="W1B_API_GUARDIAN_AUDIT_MISSING",
                        expected_before=None,
                        expected_after={
                            "row_version": _response_row_version(
                                response, "W1B_API_GUARDIAN_LIFECYCLE_MISSING"
                            )
                        },
                    )
            second_guardian_item_path = f"{guardians_path}/{second_guardian_id}"
            second_guardian_initial_version = _response_row_version(
                second_guardian_response, "W1B_API_GUARDIAN_UPDATE_MISSING"
            )
            with engine.connect() as connection:
                second_guardian_audit_before_update = _audit_rows(
                    connection, "RECIPIENT_GUARDIAN", second_guardian_id
                )
            second_guardian_response = client.patch(
                second_guardian_item_path,
                json={
                    "name": "TEST_W1B_API_GUARDIAN_OPTIONAL_UPDATED",
                    "phone": SYNTHETIC_GUARDIAN_PHONE + "_UPDATED",
                    "address": SYNTHETIC_GUARDIAN_ADDRESS + "_UPDATED",
                    "relationship_text": SYNTHETIC_GUARDIAN_RELATIONSHIP + "_UPDATED",
                    "expected_row_version": second_guardian_initial_version,
                },
                headers=_csrf_headers(client),
            )
            if second_guardian_response.status_code != 200:
                _assert_safe_response(
                    second_guardian_response,
                    "W1B_API_GUARDIAN_UPDATE_MISSING",
                    SYNTHETIC_GUARDIAN_ADDRESS,
                )
                _fail("W1B_API_GUARDIAN_UPDATE_MISSING: guardian update failed")
            second_guardian_updated_version = _response_row_version(
                second_guardian_response, "W1B_API_GUARDIAN_UPDATE_MISSING"
            )
            if second_guardian_updated_version != second_guardian_initial_version + 1:
                _fail("W1B_API_GUARDIAN_UPDATE_MISSING: row_version did not progress")
            with engine.connect() as connection:
                _assert_audit_append(
                    second_guardian_audit_before_update,
                    _audit_rows(connection, "RECIPIENT_GUARDIAN", second_guardian_id),
                    action_code="RECIPIENT_GUARDIAN_UPDATE",
                    entity_type="RECIPIENT_GUARDIAN",
                    entity_pk=second_guardian_id,
                    actor_account_id=cases["manage"].account_id,
                    marker="W1B_API_GUARDIAN_UPDATE_AUDIT_MISSING",
                    expected_before={"row_version": second_guardian_initial_version},
                    expected_after={"row_version": second_guardian_updated_version},
                )
            guardian_list = client.get(guardians_path)
            if guardian_list.status_code != 200:
                _fail("W1B_API_GUARDIAN_LIFECYCLE_MISSING: guardian readback failed")
            expected_guardians = {
                first_guardian_id: {
                    "name": "TEST_W1B_API_GUARDIAN_NAME_ONLY",
                    "phone": None,
                    "address": None,
                    "relationship_text": None,
                },
                second_guardian_id: {
                    "name": "TEST_W1B_API_GUARDIAN_OPTIONAL_UPDATED",
                    "phone": SYNTHETIC_GUARDIAN_PHONE + "_UPDATED",
                    "address": SYNTHETIC_GUARDIAN_ADDRESS + "_UPDATED",
                    "relationship_text": SYNTHETIC_GUARDIAN_RELATIONSHIP + "_UPDATED",
                },
            }
            for guardian_id, response in (
                (first_guardian_id, first_guardian_response),
                (second_guardian_id, second_guardian_response),
            ):
                guardian_record = _find_record(response.json(), guardian_id)
                if guardian_record is None or any(
                    field not in guardian_record or guardian_record[field] != value
                    for field, value in expected_guardians[guardian_id].items()
                ):
                    _fail(
                        "W1B_API_GUARDIAN_LIFECYCLE_MISSING: guardian response lost optional values"
                    )
            for guardian_id, expected_fields in expected_guardians.items():
                guardian_record = _find_record(guardian_list.json(), guardian_id)
                if guardian_record is None or any(
                    field not in guardian_record or guardian_record[field] != value
                    for field, value in expected_fields.items()
                ):
                    _fail("W1B_API_GUARDIAN_LIFECYCLE_MISSING: guardian optional readback failed")
                guardian_detail = client.get(f"{guardians_path}/{guardian_id}")
                if guardian_detail.status_code != 200:
                    _fail("W1B_API_GUARDIAN_DETAIL_MISSING: guardian detail readback failed")
                guardian_detail_record = _find_record(guardian_detail.json(), guardian_id)
                if guardian_detail_record is None or any(
                    field not in guardian_detail_record or guardian_detail_record[field] != value
                    for field, value in expected_fields.items()
                ):
                    _fail("W1B_API_GUARDIAN_DETAIL_MISSING: guardian detail lost fields")
            with engine.connect() as connection:
                stored_guardians = (
                    connection.execute(
                        guardian_table.select().where(
                            guardian_table.c.id.in_([first_guardian_id, second_guardian_id])
                        )
                    )
                    .mappings()
                    .all()
                )
            stored_by_id = {int(row["id"]): dict(row) for row in stored_guardians}
            if set(stored_by_id) != {first_guardian_id, second_guardian_id}:
                _fail("W1B_API_GUARDIAN_PG_READBACK_MISSING: guardian rows were not stored")
            for guardian_id, expected_fields in expected_guardians.items():
                stored_guardian = stored_by_id[guardian_id]
                if any(
                    stored_guardian.get(field) != value for field, value in expected_fields.items()
                ):
                    _fail("W1B_API_GUARDIAN_PG_READBACK_MISSING: optional values were not stored")
            payer_response = client.post(
                payer_path,
                json={
                    "name": "TEST_W1B_API_PAYER_NAME_ONLY",
                    "start_date": "2051-01-01",
                    "end_date": "2051-01-03",
                },
                headers=_csrf_headers(client),
            )
            if payer_response.status_code != 201:
                _assert_safe_response(payer_response, "W1B_API_PAYER_LIFECYCLE_MISSING")
                _fail("W1B_API_PAYER_LIFECYCLE_MISSING: name-only payer create failed")
            payer_id = _response_id(payer_response, "W1B_API_PAYER_LIFECYCLE_MISSING")
            with engine.connect() as connection:
                _assert_single_audit_event(
                    _audit_rows(connection, "RECIPIENT_PAYER_SNAPSHOT", payer_id),
                    action_code="RECIPIENT_PAYER_SNAPSHOT_CREATE",
                    entity_type="RECIPIENT_PAYER_SNAPSHOT",
                    entity_pk=payer_id,
                    actor_account_id=cases["manage"].account_id,
                    marker="W1B_API_PAYER_AUDIT_MISSING",
                    expected_before=None,
                    expected_after={
                        "row_version": _response_row_version(
                            payer_response, "W1B_API_PAYER_LIFECYCLE_MISSING"
                        )
                    },
                )
            payer_list = client.get(payer_path)
            if payer_list.status_code != 200:
                _fail("W1B_API_PAYER_LIFECYCLE_MISSING: payer readback failed")
            payer_record = _find_record(payer_list.json(), payer_id)
            expected_payer_fields = {
                "name": "TEST_W1B_API_PAYER_NAME_ONLY",
                "phone": None,
                "address": None,
                "relationship_text": None,
            }
            payer_response_record = _find_record(payer_response.json(), payer_id)
            if payer_response_record is None or any(
                field not in payer_response_record or payer_response_record[field] != value
                for field, value in expected_payer_fields.items()
            ):
                _fail("W1B_API_PAYER_LIFECYCLE_MISSING: payer response lost optional values")
            if payer_record is None or any(
                field not in payer_record or payer_record[field] != value
                for field, value in expected_payer_fields.items()
            ):
                _fail("W1B_API_PAYER_LIFECYCLE_MISSING: payer optional readback failed")
            payer_detail = client.get(f"{payer_path}/{payer_id}")
            if payer_detail.status_code != 200:
                _fail("W1B_API_PAYER_DETAIL_MISSING: payer detail readback failed")
            payer_detail_record = _find_record(payer_detail.json(), payer_id)
            if payer_detail_record is None or any(
                field not in payer_detail_record or payer_detail_record[field] != value
                for field, value in expected_payer_fields.items()
            ):
                _fail("W1B_API_PAYER_DETAIL_MISSING: payer detail lost snapshot fields")
            with engine.connect() as connection:
                stored_payer = (
                    connection.execute(payer_table.select().where(payer_table.c.id == payer_id))
                    .mappings()
                    .one_or_none()
                )
            if stored_payer is None or any(
                field not in stored_payer or stored_payer[field] != value
                for field, value in expected_payer_fields.items()
            ):
                _fail(
                    "W1B_API_PAYER_PG_READBACK_MISSING: name-only payer nulls were not "
                    "stored exactly"
                )
            with engine.connect() as connection:
                payer_row_before_guardian_api = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_id,
                    "W1B_API_PAYER_SNAPSHOT_INDEPENDENCE_MISSING",
                )
            guardian_after_payer = client.post(
                guardians_path,
                json={
                    "name": "TEST_W1B_API_GUARDIAN_AFTER_PAYER",
                    "phone": "TEST_W1B_GUARDIAN_AFTER_PAYER_PHONE",
                    "address": "TEST_W1B_GUARDIAN_AFTER_PAYER_ADDRESS",
                    "relationship_text": "TEST_W1B_GUARDIAN_AFTER_PAYER_RELATIONSHIP",
                },
                headers=_csrf_headers(client),
            )
            if guardian_after_payer.status_code != 201:
                _assert_safe_response(guardian_after_payer, "W1B_API_GUARDIAN_LIFECYCLE_MISSING")
                _fail("W1B_API_GUARDIAN_LIFECYCLE_MISSING: post-payer guardian create failed")
            guardian_after_payer_id = _response_id(
                guardian_after_payer, "W1B_API_GUARDIAN_LIFECYCLE_MISSING"
            )
            with engine.connect() as connection:
                _assert_single_audit_event(
                    _audit_rows(connection, "RECIPIENT_GUARDIAN", guardian_after_payer_id),
                    action_code="RECIPIENT_GUARDIAN_CREATE",
                    entity_type="RECIPIENT_GUARDIAN",
                    entity_pk=guardian_after_payer_id,
                    actor_account_id=cases["manage"].account_id,
                    marker="W1B_API_GUARDIAN_AUDIT_MISSING",
                    expected_before=None,
                    expected_after={
                        "row_version": _response_row_version(
                            guardian_after_payer, "W1B_API_GUARDIAN_LIFECYCLE_MISSING"
                        )
                    },
                )
                payer_after_guardian_api = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_id,
                    "W1B_API_PAYER_SNAPSHOT_INDEPENDENCE_MISSING",
                )
            if payer_after_guardian_api != payer_row_before_guardian_api:
                _fail(
                    "W1B_API_PAYER_SNAPSHOT_INDEPENDENCE_MISSING: guardian API mutation changed "
                    "the exact payer row"
                )
            primary_response = client.post(
                primary_path,
                json={
                    "guardian_id": first_guardian_id,
                    "start_date": "2050-01-01",
                    "end_date": "2050-01-03",
                },
                headers=_csrf_headers(client),
            )
            if primary_response.status_code != 201:
                _assert_safe_response(primary_response, "W1B_API_PRIMARY_LIFECYCLE_MISSING")
                _fail("W1B_API_PRIMARY_LIFECYCLE_MISSING: primary period create failed")
            primary_id = _response_id(primary_response, "W1B_API_PRIMARY_LIFECYCLE_MISSING")
            with engine.connect() as connection:
                _assert_single_audit_event(
                    _audit_rows(
                        connection,
                        "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                        primary_id,
                    ),
                    action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_CREATE",
                    entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                    entity_pk=primary_id,
                    actor_account_id=cases["manage"].account_id,
                    marker="W1B_API_PRIMARY_AUDIT_MISSING",
                    expected_before=None,
                    expected_after={
                        "row_version": _response_row_version(
                            primary_response, "W1B_API_PRIMARY_LIFECYCLE_MISSING"
                        )
                    },
                )
            primary_detail = client.get(f"{primary_path}/{primary_id}")
            if primary_detail.status_code != 200:
                _fail("W1B_API_PRIMARY_DETAIL_MISSING: primary-period detail readback failed")
            if _find_record(primary_detail.json(), primary_id) is None:
                _fail("W1B_API_PRIMARY_DETAIL_MISSING: primary-period detail lost row")
            primary_conflict = client.post(
                primary_path,
                json={
                    "guardian_id": second_guardian_id,
                    "start_date": "2050-01-02",
                    "end_date": "2050-01-04",
                },
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                primary_conflict,
                409,
                "W1B_API_PRIMARY_CONFLICT_MISSING",
                expected_code="PRIMARY_GUARDIAN_PERIOD_CONFLICT",
            )
            payer_conflict = client.post(
                payer_path,
                json={
                    "name": "TEST_W1B_API_PAYER_CONFLICT",
                    "start_date": "2051-01-02",
                    "end_date": "2051-01-04",
                },
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                payer_conflict,
                409,
                "W1B_API_PAYER_CONFLICT_MISSING",
                expected_code="CURRENT_PAYER_CONFLICT",
            )
            with engine.connect() as connection:
                primary_row = _exact_row_by_id(
                    connection,
                    primary_table,
                    primary_id,
                    "W1B_API_PRIMARY_LIFECYCLE_MISSING",
                )
                primary_before_ids = _recipient_row_ids(
                    connection,
                    primary_table,
                    recipient_id,
                    "W1B_API_PRIMARY_STALE_REPLACEMENT_MUTATED",
                )
                payer_row = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_id,
                    "W1B_API_PAYER_LIFECYCLE_MISSING",
                )
                payer_before_ids = _recipient_row_ids(
                    connection,
                    payer_table,
                    recipient_id,
                    "W1B_API_PAYER_STALE_REPLACEMENT_MUTATED",
                )
                primary_audit_before_stale = _audit_rows(
                    connection,
                    "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                    primary_id,
                )
                payer_audit_before_stale = _audit_rows(
                    connection,
                    "RECIPIENT_PAYER_SNAPSHOT",
                    payer_id,
                )
            if primary_row is None or not isinstance(primary_row.get("row_version"), int):
                _fail("W1B_API_PRIMARY_LIFECYCLE_MISSING: primary row was not stored")
            if payer_row is None or not isinstance(payer_row.get("row_version"), int):
                _fail("W1B_API_PAYER_LIFECYCLE_MISSING: payer row_version was not stored")
            if payer_row != payer_row_before_guardian_api:
                _fail(
                    "W1B_API_PAYER_SNAPSHOT_INDEPENDENCE_MISSING: primary API create changed "
                    "the exact payer row"
                )
            read_acl_paths = (
                RECIPIENT_COLLECTION_PATH,
                item_path,
                guardians_path,
                f"{guardians_path}/{second_guardian_id}",
                primary_path,
                f"{primary_path}/{primary_id}",
                payer_path,
                f"{payer_path}/{payer_id}",
            )
            saved_read_override = app.dependency_overrides[get_current_account]
            try:
                app.dependency_overrides.pop(get_current_account, None)
                anonymous_read_client = TestClient(app, raise_server_exceptions=False)
                for read_path in read_acl_paths:
                    _assert_error_envelope(
                        anonymous_read_client.get(read_path),
                        401,
                        "W1B_API_READ_ACL_401_MISSING:" + read_path,
                    )
                app.dependency_overrides[get_current_account] = lambda: _current_account(
                    cases["user"]
                )
                no_permission_read_client = TestClient(app, raise_server_exceptions=False)
                for read_path in read_acl_paths:
                    _assert_error_envelope(
                        no_permission_read_client.get(read_path),
                        403,
                        "W1B_API_READ_ACL_403_MISSING:" + read_path,
                    )
                for label in ("view", "manage", "admin"):
                    account = cases[label]
                    app.dependency_overrides[get_current_account] = lambda account=account: (
                        _current_account(account)
                    )
                    allowed_read_client = TestClient(app, raise_server_exceptions=False)
                    for read_path in read_acl_paths:
                        allowed_read_response = allowed_read_client.get(read_path)
                        if allowed_read_response.status_code != 200:
                            marker = "W1B_API_READ_ACL_" + label.upper() + "_MISSING:" + read_path
                            _assert_safe_response(allowed_read_response, marker)
                            _fail(marker + ": permitted read failed")
            finally:
                app.dependency_overrides[get_current_account] = saved_read_override
            primary_replacement_values = {
                "guardian_id": second_guardian_id,
                "start_date": "2052-01-01",
                "end_date": "2052-01-03",
            }
            primary_replacement_values["replacement"] = dict(primary_replacement_values)
            payer_replacement_values = {
                "name": "TEST_W1B_API_PAYER_REPLACEMENT",
                "phone": SYNTHETIC_PAYER_PHONE,
                "address": SYNTHETIC_PAYER_ADDRESS,
                "relationship_text": SYNTHETIC_PAYER_RELATIONSHIP,
                "start_date": "2053-01-01",
                "end_date": "2053-01-03",
            }
            payer_replacement_values["replacement"] = dict(payer_replacement_values)
            with engine.connect() as connection:
                recipient_table = tables["recipient"]
                recipient_before_matrix = _exact_row_by_id(
                    connection,
                    recipient_table,
                    recipient_id,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                recipient_ids_before_matrix = _table_row_ids(
                    connection,
                    recipient_table,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                guardian_ids_before_matrix = _recipient_row_ids(
                    connection,
                    guardian_table,
                    recipient_id,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                guardian_before_matrix = _exact_row_by_id(
                    connection,
                    guardian_table,
                    second_guardian_id,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                recipient_audit_before_matrix = _audit_rows(connection, "RECIPIENT", recipient_id)
                guardian_audit_before_matrix = _audit_rows(
                    connection, "RECIPIENT_GUARDIAN", second_guardian_id
                )
                all_audit_before_matrix = _all_audit_rows(connection)
            mutation_matrix = (
                (
                    "recipient-create",
                    "post",
                    RECIPIENT_COLLECTION_PATH,
                    recipient_payload,
                ),
                (
                    "recipient-update",
                    "patch",
                    item_path,
                    {"name": "TEST_W1B_MATRIX_UPDATE", "expected_row_version": updated_row_version},
                ),
                (
                    "guardian-create",
                    "post",
                    guardians_path,
                    {"name": "TEST_W1B_MATRIX_GUARDIAN"},
                ),
                (
                    "guardian-update",
                    "patch",
                    second_guardian_item_path,
                    {
                        "name": "TEST_W1B_MATRIX_GUARDIAN_UPDATE",
                        "expected_row_version": second_guardian_updated_version,
                    },
                ),
                (
                    "primary-create",
                    "post",
                    primary_path,
                    {"guardian_id": first_guardian_id, "start_date": "2055-01-01"},
                ),
                (
                    "payer-create",
                    "post",
                    payer_path,
                    {"name": "TEST_W1B_MATRIX_PAYER", "start_date": "2056-01-01"},
                ),
                (
                    "primary-invalidate",
                    "post",
                    f"{primary_path}/{primary_id}/invalidate",
                    {"expected_row_version": int(primary_row["row_version"])},
                ),
                (
                    "primary-replacement",
                    "post",
                    f"{primary_path}/{primary_id}/replacements",
                    _history_replacement_payload(
                        document,
                        HISTORY_BASE_PATHS[0],
                        int(primary_row["row_version"]),
                        primary_replacement_values,
                        "W1B_API_MUTATION_MATRIX_PAYLOAD_MISSING",
                    ),
                ),
                (
                    "payer-invalidate",
                    "post",
                    f"{payer_path}/{payer_id}/invalidate",
                    {"expected_row_version": int(payer_row["row_version"])},
                ),
                (
                    "payer-replacement",
                    "post",
                    f"{payer_path}/{payer_id}/replacements",
                    _history_replacement_payload(
                        document,
                        HISTORY_BASE_PATHS[1],
                        int(payer_row["row_version"]),
                        payer_replacement_values,
                        "W1B_API_MUTATION_MATRIX_PAYLOAD_MISSING",
                    ),
                ),
            )

            saved_matrix_override = app.dependency_overrides[get_current_account]
            try:
                app.dependency_overrides.pop(get_current_account, None)
                unauth_matrix_client = TestClient(app, raise_server_exceptions=False)
                for label, method, path, payload in mutation_matrix:
                    response = unauth_matrix_client.request(method, path, json=payload)
                    _assert_error_envelope(
                        response,
                        401,
                        "W1B_API_MUTATION_MATRIX_401_MISSING:" + label,
                    )
                for label, account in (("user", cases["user"]), ("view", cases["view"])):
                    app.dependency_overrides[get_current_account] = lambda account=account: (
                        _current_account(account)
                    )
                    matrix_client = TestClient(app, raise_server_exceptions=False)
                    for operation, method, path, payload in mutation_matrix:
                        response = matrix_client.request(
                            method,
                            path,
                            json=payload,
                            headers=_csrf_headers(matrix_client),
                        )
                        _assert_error_envelope(
                            response,
                            403,
                            "W1B_API_MUTATION_MATRIX_403_"
                            + label.upper()
                            + "_MISSING:"
                            + operation,
                        )
                app.dependency_overrides[get_current_account] = saved_matrix_override
                for operation, method, path, payload in mutation_matrix:
                    response = client.request(method, path, json=payload)
                    _assert_error_envelope(
                        response,
                        403,
                        "W1B_API_MUTATION_MATRIX_CSRF_MISSING:" + operation,
                    )
            finally:
                app.dependency_overrides[get_current_account] = saved_matrix_override
            with engine.connect() as connection:
                recipient_ids_after_matrix = _table_row_ids(
                    connection,
                    recipient_table,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                guardian_ids_after_matrix = _recipient_row_ids(
                    connection,
                    guardian_table,
                    recipient_id,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                primary_ids_after_matrix = _recipient_row_ids(
                    connection,
                    primary_table,
                    recipient_id,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                payer_ids_after_matrix = _recipient_row_ids(
                    connection,
                    payer_table,
                    recipient_id,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                if recipient_ids_after_matrix != recipient_ids_before_matrix:
                    _fail(
                        "W1B_API_MUTATION_MATRIX_MUTATED: unauthorized mutation created a recipient"
                    )
                if guardian_ids_after_matrix != guardian_ids_before_matrix:
                    _fail(
                        "W1B_API_MUTATION_MATRIX_MUTATED: unauthorized mutation created a guardian"
                    )
                if primary_ids_after_matrix != primary_before_ids:
                    _fail(
                        "W1B_API_MUTATION_MATRIX_MUTATED: unauthorized mutation created "
                        "a primary row"
                    )
                if payer_ids_after_matrix != payer_before_ids:
                    _fail(
                        "W1B_API_MUTATION_MATRIX_MUTATED: unauthorized mutation created a payer row"
                    )
                _assert_exact_row_unchanged(
                    connection,
                    recipient_table,
                    recipient_id,
                    recipient_before_matrix,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                _assert_exact_row_unchanged(
                    connection,
                    guardian_table,
                    second_guardian_id,
                    guardian_before_matrix,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                _assert_exact_row_unchanged(
                    connection,
                    primary_table,
                    primary_id,
                    primary_row,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                _assert_exact_row_unchanged(
                    connection,
                    payer_table,
                    payer_id,
                    payer_row,
                    "W1B_API_MUTATION_MATRIX_MUTATED",
                )
                _assert_no_audit_change(
                    all_audit_before_matrix,
                    _all_audit_rows(connection),
                    "W1B_API_MUTATION_MATRIX_AUDIT_MUTATED",
                )
                _assert_no_audit_change(
                    recipient_audit_before_matrix,
                    _audit_rows(connection, "RECIPIENT", recipient_id),
                    "W1B_API_MUTATION_MATRIX_AUDIT_MUTATED",
                )
                _assert_no_audit_change(
                    guardian_audit_before_matrix,
                    _audit_rows(connection, "RECIPIENT_GUARDIAN", second_guardian_id),
                    "W1B_API_MUTATION_MATRIX_AUDIT_MUTATED",
                )
                _assert_no_audit_change(
                    primary_audit_before_stale,
                    _audit_rows(
                        connection,
                        "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                        primary_id,
                    ),
                    "W1B_API_MUTATION_MATRIX_AUDIT_MUTATED",
                )
                _assert_no_audit_change(
                    payer_audit_before_stale,
                    _audit_rows(connection, "RECIPIENT_PAYER_SNAPSHOT", payer_id),
                    "W1B_API_MUTATION_MATRIX_AUDIT_MUTATED",
                )
            missing_recipient_version = client.patch(
                item_path,
                json={"name": "TEST_W1B_MISSING_VERSION"},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                missing_recipient_version,
                422,
                "W1B_API_RECIPIENT_VERSION_REQUIRED_MISSING",
                expected_code="VALIDATION_ERROR",
            )
            missing_guardian_version = client.patch(
                second_guardian_item_path,
                json={"name": "TEST_W1B_GUARDIAN_MISSING_VERSION"},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                missing_guardian_version,
                422,
                "W1B_API_GUARDIAN_VERSION_REQUIRED_MISSING",
                expected_code="VALIDATION_ERROR",
            )
            stale_guardian_version = client.patch(
                second_guardian_item_path,
                json={
                    "name": "TEST_W1B_GUARDIAN_STALE_VERSION",
                    "expected_row_version": second_guardian_initial_version,
                },
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                stale_guardian_version,
                409,
                "W1B_API_GUARDIAN_STALE_VERSION_MISSING",
                expected_code="ROW_VERSION_CONFLICT",
            )
            with engine.connect() as connection:
                _assert_exact_row_unchanged(
                    connection,
                    recipient_table,
                    recipient_id,
                    recipient_before_matrix,
                    "W1B_API_RECIPIENT_REJECTED_MUTATION_CHANGED_ROW",
                )
                _assert_no_audit_change(
                    recipient_audit_before_matrix,
                    _audit_rows(connection, "RECIPIENT", recipient_id),
                    "W1B_API_RECIPIENT_REJECTED_MUTATION_AUDIT_MUTATED",
                )
                _assert_exact_row_unchanged(
                    connection,
                    guardian_table,
                    second_guardian_id,
                    guardian_before_matrix,
                    "W1B_API_GUARDIAN_REJECTED_MUTATION_CHANGED_ROW",
                )
                _assert_no_audit_change(
                    guardian_audit_before_matrix,
                    _audit_rows(connection, "RECIPIENT_GUARDIAN", second_guardian_id),
                    "W1B_API_GUARDIAN_REJECTED_MUTATION_AUDIT_MUTATED",
                )
                _assert_no_audit_change(
                    all_audit_before_matrix,
                    _all_audit_rows(connection),
                    "W1B_API_REJECTED_MUTATION_AUDIT_MUTATED",
                )
            missing_primary_invalidation_version = client.post(
                f"{primary_path}/{primary_id}/invalidate",
                json={},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                missing_primary_invalidation_version,
                422,
                "W1B_API_PRIMARY_VERSION_REQUIRED_MISSING",
                expected_code="VALIDATION_ERROR",
            )
            missing_primary_replacement_payload = _history_replacement_payload(
                document,
                HISTORY_BASE_PATHS[0],
                int(primary_row["row_version"]),
                primary_replacement_values,
                "W1B_API_PRIMARY_VERSION_REQUIRED_MISSING",
            )
            missing_primary_replacement_payload.pop("expected_row_version", None)
            missing_primary_replacement_version = client.post(
                f"{primary_path}/{primary_id}/replacements",
                json=missing_primary_replacement_payload,
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                missing_primary_replacement_version,
                422,
                "W1B_API_PRIMARY_VERSION_REQUIRED_MISSING",
                expected_code="VALIDATION_ERROR",
            )
            missing_payer_invalidation_version = client.post(
                f"{payer_path}/{payer_id}/invalidate",
                json={},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                missing_payer_invalidation_version,
                422,
                "W1B_API_PAYER_VERSION_REQUIRED_MISSING",
                expected_code="VALIDATION_ERROR",
            )
            missing_payer_replacement_payload = _history_replacement_payload(
                document,
                HISTORY_BASE_PATHS[1],
                int(payer_row["row_version"]),
                payer_replacement_values,
                "W1B_API_PAYER_VERSION_REQUIRED_MISSING",
            )
            missing_payer_replacement_payload.pop("expected_row_version", None)
            missing_payer_replacement_version = client.post(
                f"{payer_path}/{payer_id}/replacements",
                json=missing_payer_replacement_payload,
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                missing_payer_replacement_version,
                422,
                "W1B_API_PAYER_VERSION_REQUIRED_MISSING",
                expected_code="VALIDATION_ERROR",
            )
            primary_stale_replacement_payload = _history_replacement_payload(
                document,
                HISTORY_BASE_PATHS[0],
                int(primary_row["row_version"]) + 1000,
                primary_replacement_values,
                "W1B_API_PRIMARY_STALE_REPLACEMENT_MISSING",
            )
            primary_stale_replacement = client.post(
                f"{primary_path}/{primary_id}/replacements",
                json=primary_stale_replacement_payload,
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                primary_stale_replacement,
                409,
                "W1B_API_PRIMARY_STALE_REPLACEMENT_MISSING",
                expected_code="ROW_VERSION_CONFLICT",
            )
            with engine.connect() as connection:
                primary_after_stale_ids = _recipient_row_ids(
                    connection,
                    primary_table,
                    recipient_id,
                    "W1B_API_PRIMARY_STALE_REPLACEMENT_MUTATED",
                )
                if primary_after_stale_ids != primary_before_ids:
                    _fail("W1B_API_PRIMARY_STALE_REPLACEMENT_MUTATED: stale request created a row")
                _assert_exact_row_unchanged(
                    connection,
                    primary_table,
                    primary_id,
                    primary_row,
                    "W1B_API_PRIMARY_STALE_REPLACEMENT_MUTATED",
                )
                _assert_no_audit_change(
                    primary_audit_before_stale,
                    _audit_rows(
                        connection,
                        "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                        primary_id,
                    ),
                    "W1B_API_PRIMARY_STALE_REPLACEMENT_AUDIT_MUTATED",
                )
            primary_replacement_payload = _history_replacement_payload(
                document,
                HISTORY_BASE_PATHS[0],
                int(primary_row["row_version"]),
                primary_replacement_values,
                "W1B_API_PRIMARY_REPLACEMENT_MISSING",
            )
            primary_replacement = client.post(
                f"{primary_path}/{primary_id}/replacements",
                json=primary_replacement_payload,
                headers=_csrf_headers(client),
            )
            if primary_replacement.status_code not in {200, 201}:
                _assert_safe_response(primary_replacement, "W1B_API_PRIMARY_REPLACEMENT_MISSING")
                _fail("W1B_API_PRIMARY_REPLACEMENT_MISSING: primary replacement failed")
            primary_replacement_id = _response_replacement_id(
                primary_replacement, "W1B_API_PRIMARY_REPLACEMENT_MISSING"
            )
            primary_link_column = _replacement_link_column(
                primary_table, "W1B_API_PRIMARY_REPLACEMENT_MISSING"
            )
            with engine.connect() as connection:
                old_primary_row = _exact_row_by_id(
                    connection,
                    primary_table,
                    primary_id,
                    "W1B_API_PRIMARY_REPLACEMENT_MISSING",
                )
                new_primary_row = _exact_row_by_id(
                    connection,
                    primary_table,
                    primary_replacement_id,
                    "W1B_API_PRIMARY_REPLACEMENT_MISSING",
                )
                primary_after_replacement_ids = _recipient_row_ids(
                    connection,
                    primary_table,
                    recipient_id,
                    "W1B_API_PRIMARY_REPLACEMENT_MISSING",
                )
                primary_old_audit_after_replacement = _audit_rows(
                    connection,
                    "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                    primary_id,
                )
                primary_new_audit_after_replacement = _audit_rows(
                    connection,
                    "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                    primary_replacement_id,
                )
            expected_primary_replacement_fields = {
                "guardian_id": second_guardian_id,
                "start_date": date(2052, 1, 1),
                "end_date": date(2052, 1, 3),
            }
            if set(primary_after_replacement_ids) - set(primary_before_ids) != {
                primary_replacement_id
            } or set(primary_after_replacement_ids) != (
                set(primary_before_ids) | {primary_replacement_id}
            ):
                _fail(
                    "W1B_API_PRIMARY_REPLACEMENT_MISSING: replacement row set is not before IDs "
                    "plus exactly one new ID"
                )
            if (
                old_primary_row is None
                or old_primary_row.get("invalidated_at_utc") is None
                or old_primary_row.get(primary_link_column.name) != primary_replacement_id
                or new_primary_row is None
                or new_primary_row.get("invalidated_at_utc") is not None
                or new_primary_row.get(primary_link_column.name) is not None
                or any(
                    new_primary_row.get(field) != value
                    for field, value in expected_primary_replacement_fields.items()
                )
                or any(
                    old_primary_row.get(field) != primary_row.get(field)
                    for field in ("recipient_id", "guardian_id", "start_date", "end_date")
                )
                or old_primary_row.get("row_version") != int(primary_row["row_version"]) + 1
                or new_primary_row.get("row_version") != 1
            ):
                _fail(
                    "W1B_API_PRIMARY_REPLACEMENT_MISSING: exact requested fields, linkage, or "
                    "row-version progression is incorrect"
                )
            _assert_audit_append(
                primary_audit_before_stale,
                primary_old_audit_after_replacement,
                action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_INVALIDATE",
                entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                entity_pk=primary_id,
                actor_account_id=cases["manage"].account_id,
                marker="W1B_API_PRIMARY_REPLACEMENT_AUDIT_MISSING",
                expected_before={"row_version": int(primary_row["row_version"])},
                expected_after={
                    primary_link_column.name: primary_replacement_id,
                    "row_version": int(primary_row["row_version"]) + 1,
                },
            )
            _assert_single_audit_event(
                primary_new_audit_after_replacement,
                action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_REPLACEMENT_CREATE",
                entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                entity_pk=primary_replacement_id,
                actor_account_id=cases["manage"].account_id,
                marker="W1B_API_PRIMARY_REPLACEMENT_AUDIT_MISSING",
                expected_before=None,
                expected_after={
                    "row_version": 1,
                    "guardian_id": second_guardian_id,
                    "start_date": "2052-01-01",
                    "end_date": "2052-01-03",
                },
            )
            primary_stale_invalidation = client.post(
                f"{primary_path}/{primary_replacement_id}/invalidate",
                json={"expected_row_version": int(new_primary_row["row_version"]) + 1000},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                primary_stale_invalidation,
                409,
                "W1B_API_PRIMARY_STALE_INVALIDATION_MISSING",
                expected_code="ROW_VERSION_CONFLICT",
            )
            with engine.connect() as connection:
                primary_after_stale_invalidation_ids = _recipient_row_ids(
                    connection,
                    primary_table,
                    recipient_id,
                    "W1B_API_PRIMARY_STALE_INVALIDATION_MUTATED",
                )
                if primary_after_stale_invalidation_ids != primary_after_replacement_ids:
                    _fail(
                        "W1B_API_PRIMARY_STALE_INVALIDATION_MUTATED: stale request changed row set"
                    )
                unchanged_primary_replacement = _exact_row_by_id(
                    connection,
                    primary_table,
                    primary_replacement_id,
                    "W1B_API_PRIMARY_STALE_INVALIDATION_MUTATED",
                )
                if (
                    unchanged_primary_replacement.get("invalidated_at_utc") is not None
                    or unchanged_primary_replacement.get("row_version")
                    != new_primary_row.get("row_version")
                    or unchanged_primary_replacement != dict(new_primary_row)
                ):
                    _fail(
                        "W1B_API_PRIMARY_STALE_INVALIDATION_MUTATED: active row or version changed"
                    )
                _assert_no_audit_change(
                    primary_new_audit_after_replacement,
                    _audit_rows(
                        connection,
                        "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                        primary_replacement_id,
                    ),
                    "W1B_API_PRIMARY_STALE_INVALIDATION_AUDIT_MUTATED",
                )
            primary_invalidate = client.post(
                f"{primary_path}/{primary_replacement_id}/invalidate",
                json={"expected_row_version": int(new_primary_row["row_version"])},
                headers=_csrf_headers(client),
            )
            if primary_invalidate.status_code not in {200, 201}:
                _assert_safe_response(primary_invalidate, "W1B_API_PRIMARY_INVALIDATION_MISSING")
                _fail("W1B_API_PRIMARY_INVALIDATION_MISSING: primary invalidation failed")
            with engine.connect() as connection:
                invalidated_primary = _exact_row_by_id(
                    connection,
                    primary_table,
                    primary_replacement_id,
                    "W1B_API_PRIMARY_INVALIDATION_MISSING",
                )
                primary_audit_after_invalidation = _audit_rows(
                    connection,
                    "RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                    primary_replacement_id,
                )
            if invalidated_primary is None or invalidated_primary.get("invalidated_at_utc") is None:
                _fail("W1B_API_PRIMARY_INVALIDATION_MISSING: invalidation did not persist")
            if invalidated_primary.get("row_version") != int(new_primary_row["row_version"]) + 1:
                _fail("W1B_API_PRIMARY_INVALIDATION_MISSING: row_version did not progress")
            _assert_audit_append(
                primary_new_audit_after_replacement,
                primary_audit_after_invalidation,
                action_code="RECIPIENT_GUARDIAN_PRIMARY_PERIOD_INVALIDATE",
                entity_type="RECIPIENT_GUARDIAN_PRIMARY_PERIOD",
                entity_pk=primary_replacement_id,
                actor_account_id=cases["manage"].account_id,
                marker="W1B_API_PRIMARY_INVALIDATION_AUDIT_MISSING",
                expected_before={"row_version": int(new_primary_row["row_version"])},
                expected_after={"row_version": int(new_primary_row["row_version"]) + 1},
            )
            with engine.connect() as connection:
                payer_after_primary_mutations = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_id,
                    "W1B_API_PAYER_SNAPSHOT_INDEPENDENCE_MISSING",
                )
            if payer_after_primary_mutations != payer_row:
                _fail(
                    "W1B_API_PAYER_SNAPSHOT_INDEPENDENCE_MISSING: primary API mutation or "
                    "invalidation changed the exact payer row"
                )
            payer_stale_replacement_payload = _history_replacement_payload(
                document,
                HISTORY_BASE_PATHS[1],
                int(payer_row["row_version"]) + 1000,
                payer_replacement_values,
                "W1B_API_PAYER_STALE_REPLACEMENT_MISSING",
            )
            payer_stale_replacement = client.post(
                f"{payer_path}/{payer_id}/replacements",
                json=payer_stale_replacement_payload,
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                payer_stale_replacement,
                409,
                "W1B_API_PAYER_STALE_REPLACEMENT_MISSING",
                expected_code="ROW_VERSION_CONFLICT",
            )
            with engine.connect() as connection:
                payer_after_stale_ids = _recipient_row_ids(
                    connection,
                    payer_table,
                    recipient_id,
                    "W1B_API_PAYER_STALE_REPLACEMENT_MUTATED",
                )
                if payer_after_stale_ids != payer_before_ids:
                    _fail("W1B_API_PAYER_STALE_REPLACEMENT_MUTATED: stale request created a row")
                _assert_exact_row_unchanged(
                    connection,
                    payer_table,
                    payer_id,
                    payer_row,
                    "W1B_API_PAYER_STALE_REPLACEMENT_MUTATED",
                )
                _assert_no_audit_change(
                    payer_audit_before_stale,
                    _audit_rows(connection, "RECIPIENT_PAYER_SNAPSHOT", payer_id),
                    "W1B_API_PAYER_STALE_REPLACEMENT_AUDIT_MUTATED",
                )
            payer_replacement_payload = _history_replacement_payload(
                document,
                HISTORY_BASE_PATHS[1],
                int(payer_row["row_version"]),
                payer_replacement_values,
                "W1B_API_PAYER_REPLACEMENT_MISSING",
            )
            payer_replacement = client.post(
                f"{payer_path}/{payer_id}/replacements",
                json=payer_replacement_payload,
                headers=_csrf_headers(client),
            )
            if payer_replacement.status_code not in {200, 201}:
                _assert_safe_response(payer_replacement, "W1B_API_PAYER_REPLACEMENT_MISSING")
                _fail("W1B_API_PAYER_REPLACEMENT_MISSING: payer replacement failed")
            payer_replacement_id = _response_replacement_id(
                payer_replacement, "W1B_API_PAYER_REPLACEMENT_MISSING"
            )
            payer_link_column = _replacement_link_column(
                payer_table, "W1B_API_PAYER_REPLACEMENT_MISSING"
            )
            try:
                payer_replacement_response_payload = payer_replacement.json()
            except ValueError:
                _fail("W1B_API_PAYER_REPLACEMENT_MISSING: replacement response is not JSON")
            payer_replacement_response_record = _find_record(
                payer_replacement_response_payload, payer_replacement_id
            )
            expected_payer_replacement_response_fields = {
                "name": "TEST_W1B_API_PAYER_REPLACEMENT",
                "phone": SYNTHETIC_PAYER_PHONE,
                "address": SYNTHETIC_PAYER_ADDRESS,
                "relationship_text": SYNTHETIC_PAYER_RELATIONSHIP,
                "start_date": "2053-01-01",
                "end_date": "2053-01-03",
                "row_version": 1,
            }
            if payer_replacement_response_record is None or any(
                field not in payer_replacement_response_record
                or payer_replacement_response_record.get(field) != value
                for field, value in expected_payer_replacement_response_fields.items()
            ):
                _fail(
                    "W1B_API_PAYER_REPLACEMENT_MISSING: response replacement record lacks "
                    "exact requested fields or row version"
                )
            response_invalidated_at = _nested_value(
                payer_replacement_response_payload, "invalidated_at_utc"
            )
            if not isinstance(response_invalidated_at, str) or not response_invalidated_at:
                _fail(
                    "W1B_API_PAYER_REPLACEMENT_MISSING: response does not expose the "
                    "original invalidation timestamp"
                )
            with engine.connect() as connection:
                old_payer_row = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_id,
                    "W1B_API_PAYER_REPLACEMENT_MISSING",
                )
                new_payer_row = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_replacement_id,
                    "W1B_API_PAYER_REPLACEMENT_MISSING",
                )
                payer_after_replacement_ids = _recipient_row_ids(
                    connection,
                    payer_table,
                    recipient_id,
                    "W1B_API_PAYER_REPLACEMENT_MISSING",
                )
                payer_old_audit_after_replacement = _audit_rows(
                    connection,
                    "RECIPIENT_PAYER_SNAPSHOT",
                    payer_id,
                )
                payer_new_audit_after_replacement = _audit_rows(
                    connection,
                    "RECIPIENT_PAYER_SNAPSHOT",
                    payer_replacement_id,
                )
            expected_payer_replacement_fields = {
                "name": "TEST_W1B_API_PAYER_REPLACEMENT",
                "phone": SYNTHETIC_PAYER_PHONE,
                "address": SYNTHETIC_PAYER_ADDRESS,
                "relationship_text": SYNTHETIC_PAYER_RELATIONSHIP,
                "start_date": date(2053, 1, 1),
                "end_date": date(2053, 1, 3),
            }
            if set(payer_after_replacement_ids) - set(payer_before_ids) != {
                payer_replacement_id
            } or set(payer_after_replacement_ids) != (
                set(payer_before_ids) | {payer_replacement_id}
            ):
                _fail(
                    "W1B_API_PAYER_REPLACEMENT_MISSING: replacement row set is not before IDs "
                    "plus exactly one new ID"
                )
            if (
                old_payer_row is None
                or old_payer_row.get("invalidated_at_utc") is None
                or old_payer_row.get(payer_link_column.name) != payer_replacement_id
                or new_payer_row is None
                or new_payer_row.get("invalidated_at_utc") is not None
                or new_payer_row.get(payer_link_column.name) is not None
                or any(
                    new_payer_row.get(field) != value
                    for field, value in expected_payer_replacement_fields.items()
                )
                or any(
                    old_payer_row.get(field) != payer_row.get(field)
                    for field in (
                        "recipient_id",
                        "name",
                        "phone",
                        "address",
                        "relationship_text",
                        "start_date",
                        "end_date",
                    )
                )
                or old_payer_row.get("row_version") != int(payer_row["row_version"]) + 1
                or new_payer_row.get("row_version") != 1
            ):
                _fail(
                    "W1B_API_PAYER_REPLACEMENT_MISSING: exact requested fields, linkage, or "
                    "row-version progression is incorrect"
                )
            _assert_audit_append(
                payer_audit_before_stale,
                payer_old_audit_after_replacement,
                action_code="RECIPIENT_PAYER_SNAPSHOT_INVALIDATE",
                entity_type="RECIPIENT_PAYER_SNAPSHOT",
                entity_pk=payer_id,
                actor_account_id=cases["manage"].account_id,
                marker="W1B_API_PAYER_REPLACEMENT_AUDIT_MISSING",
                expected_before={"row_version": int(payer_row["row_version"])},
                expected_after={
                    payer_link_column.name: payer_replacement_id,
                    "row_version": int(payer_row["row_version"]) + 1,
                },
            )
            _assert_single_audit_event(
                payer_new_audit_after_replacement,
                action_code="RECIPIENT_PAYER_SNAPSHOT_REPLACEMENT_CREATE",
                entity_type="RECIPIENT_PAYER_SNAPSHOT",
                entity_pk=payer_replacement_id,
                actor_account_id=cases["manage"].account_id,
                marker="W1B_API_PAYER_REPLACEMENT_AUDIT_MISSING",
                expected_before=None,
                expected_after={
                    "row_version": 1,
                    "name": "TEST_W1B_API_PAYER_REPLACEMENT",
                    "phone": SYNTHETIC_PAYER_PHONE,
                    "address": SYNTHETIC_PAYER_ADDRESS,
                    "relationship_text": SYNTHETIC_PAYER_RELATIONSHIP,
                    "start_date": "2053-01-01",
                    "end_date": "2053-01-03",
                },
            )
            payer_stale_invalidation = client.post(
                f"{payer_path}/{payer_replacement_id}/invalidate",
                json={"expected_row_version": int(new_payer_row["row_version"]) + 1000},
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                payer_stale_invalidation,
                409,
                "W1B_API_PAYER_STALE_INVALIDATION_MISSING",
                expected_code="ROW_VERSION_CONFLICT",
            )
            with engine.connect() as connection:
                payer_after_stale_invalidation_ids = _recipient_row_ids(
                    connection,
                    payer_table,
                    recipient_id,
                    "W1B_API_PAYER_STALE_INVALIDATION_MUTATED",
                )
                if payer_after_stale_invalidation_ids != payer_after_replacement_ids:
                    _fail("W1B_API_PAYER_STALE_INVALIDATION_MUTATED: stale request changed row set")
                unchanged_payer_replacement = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_replacement_id,
                    "W1B_API_PAYER_STALE_INVALIDATION_MUTATED",
                )
                if (
                    unchanged_payer_replacement.get("invalidated_at_utc") is not None
                    or unchanged_payer_replacement.get("row_version")
                    != new_payer_row.get("row_version")
                    or unchanged_payer_replacement != dict(new_payer_row)
                ):
                    _fail("W1B_API_PAYER_STALE_INVALIDATION_MUTATED: active row or version changed")
                _assert_no_audit_change(
                    payer_new_audit_after_replacement,
                    _audit_rows(connection, "RECIPIENT_PAYER_SNAPSHOT", payer_replacement_id),
                    "W1B_API_PAYER_STALE_INVALIDATION_AUDIT_MUTATED",
                )
            payer_invalidate = client.post(
                f"{payer_path}/{payer_replacement_id}/invalidate",
                json={"expected_row_version": int(new_payer_row["row_version"])},
                headers=_csrf_headers(client),
            )
            if payer_invalidate.status_code not in {200, 201}:
                _assert_safe_response(payer_invalidate, "W1B_API_PAYER_INVALIDATION_MISSING")
                _fail("W1B_API_PAYER_INVALIDATION_MISSING: payer invalidation failed")
            with engine.connect() as connection:
                invalidated_payer = _exact_row_by_id(
                    connection,
                    payer_table,
                    payer_replacement_id,
                    "W1B_API_PAYER_INVALIDATION_MISSING",
                )
                payer_audit_after_invalidation = _audit_rows(
                    connection,
                    "RECIPIENT_PAYER_SNAPSHOT",
                    payer_replacement_id,
                )
            if invalidated_payer is None or invalidated_payer.get("invalidated_at_utc") is None:
                _fail("W1B_API_PAYER_INVALIDATION_MISSING: invalidation did not persist")
            if invalidated_payer.get("row_version") != int(new_payer_row["row_version"]) + 1:
                _fail("W1B_API_PAYER_INVALIDATION_MISSING: row_version did not progress")
            _assert_audit_append(
                payer_new_audit_after_replacement,
                payer_audit_after_invalidation,
                action_code="RECIPIENT_PAYER_SNAPSHOT_INVALIDATE",
                entity_type="RECIPIENT_PAYER_SNAPSHOT",
                entity_pk=payer_replacement_id,
                actor_account_id=cases["manage"].account_id,
                marker="W1B_API_PAYER_INVALIDATION_AUDIT_MISSING",
                expected_before={"row_version": int(new_payer_row["row_version"])},
                expected_after={"row_version": int(new_payer_row["row_version"]) + 1},
            )
            invalid = client.post(
                RECIPIENT_COLLECTION_PATH,
                json={
                    "name": SYNTHETIC_NAME,
                    "birth_date": "not-a-date",
                    "sex_code": "MALE",
                    "TEST_W1B_SECRET_CANARY": "TEST_W1B_SECRET_CANARY",
                },
                headers=_csrf_headers(client),
            )
            _assert_error_envelope(
                invalid,
                422,
                "W1B_API_VALIDATION_MISSING",
                expected_code="VALIDATION_ERROR",
                canary="TEST_W1B_SECRET_CANARY",
            )
            forced_500_canaries = {
                "name": SYNTHETIC_500_NAME,
                "address": SYNTHETIC_500_ADDRESS,
                "home_phone": SYNTHETIC_500_HOME_PHONE,
                "mobile_phone": SYNTHETIC_500_MOBILE_PHONE,
            }
            caplog.clear()
            trigger_names = _install_constraint_failure_trigger(engine, forced_500_canaries)
            try:
                forced_failure = client.post(
                    RECIPIENT_COLLECTION_PATH,
                    json={
                        "name": SYNTHETIC_500_NAME,
                        "birth_date": "2000-01-01",
                        "sex_code": "MALE",
                        "address": SYNTHETIC_500_ADDRESS,
                        "home_phone": SYNTHETIC_500_HOME_PHONE,
                        "mobile_phone": SYNTHETIC_500_MOBILE_PHONE,
                    },
                    headers=_csrf_headers(client),
                )
                _assert_error_envelope(
                    forced_failure,
                    500,
                    "W1B_API_500_CONTRACT_MISSING",
                    expected_code="UNEXPECTED_SERVER_ERROR",
                    canary=(
                        "TEST_W1B_CONSTRAINT_CANARY",
                        SYNTHETIC_500_NAME,
                        SYNTHETIC_500_ADDRESS,
                        SYNTHETIC_500_HOME_PHONE,
                        SYNTHETIC_500_MOBILE_PHONE,
                    ),
                )
            finally:
                _remove_constraint_failure_trigger(engine, trigger_names)
            _assert_safe_logs(
                caplog,
                "W1B_API_LOG_LEAK_MISSING",
                (
                    "TEST_W1B_CONSTRAINT_CANARY",
                    SYNTHETIC_500_NAME,
                    SYNTHETIC_500_ADDRESS,
                    SYNTHETIC_500_HOME_PHONE,
                    SYNTHETIC_500_MOBILE_PHONE,
                ),
            )
    finally:
        _cleanup(engine, cases, recipient_ids)
        engine.dispose()


def test_w1b_06_rec02_actual_synthetic_import_mapping_lifecycle_is_fixed() -> None:
    document, item_path = _require_api_operations()
    _assert_w1b_public_schema_contract(document, item_path)
    _, _, allowed_revisions = _require_w1b_revision()
    tables = _require_metadata_contract()
    prepare, apply, invalidate, replace = _load_recipient_import_operations(
        "W1B_REC_02_IMPORTER_MISSING"
    )

    engine = _postgres_engine()
    token = uuid4().hex
    cases = _make_actor_cases(engine, token)
    recipient_ids: set[int] = set()
    try:
        _require_db_revision(engine, allowed_revisions)
        recipient = tables["recipient"]
        mapping = tables["recipient_legacy_mapping"]
        _required_columns(
            mapping,
            {
                "invalidated_at_utc",
                "replacement_recipient_legacy_mapping_id",
                "legacy_attachment_key",
            },
            "W1B_REC_02_MAPPING_MODEL_MISSING",
        )
        from app.core.settings import get_settings

        settings = get_settings()
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        first_row = _import_row(
            SYNTHETIC_LEGACY_KEY,
            SYNTHETIC_NAME,
            source_memo=SYNTHETIC_SOURCE_MEMO,
        )
        common = {
            "rows": [first_row],
            "source_system_code": SYNTHETIC_SOURCE,
            "active_legacy_recipient_keys": frozenset(),
            "active_legacy_attachment_keys": frozenset(),
            "database_session": None,
            "session": None,
            "session_factory": factory,
            "actor_account_id": cases["admin"].account_id,
            "settings": settings,
        }
        summary = _invoke_importer(prepare, common, "W1B_REC_02_PREPARE_MISSING")
        payload = _summary_payload(summary, "W1B_REC_02_PREPARE_MISSING")
        if payload.get("included_count") != 1 or payload.get("excluded_count") != 0:
            _fail("W1B_REC_02_PREPARE_MISSING: synthetic fixture was not included exactly once")
        with sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)() as session:
            common = {
                **common,
                "database_session": session,
                "session": session,
                "prepared": payload,
            }
            result = _invoke_importer(apply, common, "W1B_REC_02_APPLY_MISSING")
            session.commit()
            if result is None:
                _fail("W1B_REC_02_APPLY_MISSING: synthetic apply returned no result")
        with engine.connect() as connection:
            first_mapping = _mapping_row(
                connection,
                mapping,
                SYNTHETIC_SOURCE,
                SYNTHETIC_LEGACY_KEY,
                active=True,
                marker="W1B_REC_02_MAPPING_CREATE_MISSING",
            )
            if first_mapping is None:
                _fail("W1B_REC_02_MAPPING_CREATE_MISSING: mapping row was not created")
            first_recipient_id = int(first_mapping["recipient_id"])
            recipient_ids.add(first_recipient_id)
            recipient_row = (
                connection.execute(recipient.select().where(recipient.c.id == first_recipient_id))
                .mappings()
                .one_or_none()
            )
            if recipient_row is None:
                _fail("W1B_REC_02_MAPPING_CREATE_MISSING: mapped recipient row is absent")
            memo = str(recipient_row.get("memo") or "")
            if SYNTHETIC_SOURCE not in memo or SYNTHETIC_SOURCE_MEMO not in memo:
                _fail(
                    "W1B_REC_02_SOURCE_MEMO_MISSING: source label and source_memo were not "
                    "stored in recipient memo"
                )
            active_count = connection.execute(
                text(
                    """
                    SELECT count(*) FROM erp.recipient_legacy_mapping
                    WHERE source_system_code = :source
                      AND legacy_recipient_key = :legacy_key
                      AND invalidated_at_utc IS NULL
                    """
                ),
                {"source": SYNTHETIC_SOURCE, "legacy_key": SYNTHETIC_LEGACY_KEY},
            ).scalar_one()
            if active_count != 1:
                _fail("W1B_REC_02_ACTIVE_UNIQUE_MISSING: active mapping is not unique")

        attachment_row = _import_row(
            None,
            "TEST_W1B_ATTACHMENT_ONLY_CANARY",
            attachment_key=SYNTHETIC_ATTACHMENT_KEY,
            source_memo="TEST_W1B_ATTACHMENT_SOURCE_MEMO",
        )
        attachment_common = {
            **common,
            "rows": [attachment_row],
            "active_legacy_recipient_keys": frozenset({SYNTHETIC_LEGACY_KEY}),
            "active_legacy_attachment_keys": frozenset(),
        }
        attachment_summary = _summary_payload(
            _invoke_importer(prepare, attachment_common, "W1B_REC_02_ATTACHMENT_MISSING"),
            "W1B_REC_02_ATTACHMENT_MISSING",
        )
        if attachment_summary.get("included_count") != 1:
            _fail("W1B_REC_02_ATTACHMENT_MISSING: attachment-only fixture was not accepted")
        with factory() as session:
            attachment_common = {
                **attachment_common,
                "database_session": session,
                "session": session,
                "prepared": attachment_summary,
            }
            _invoke_importer(apply, attachment_common, "W1B_REC_02_ATTACHMENT_MISSING")
            session.commit()
        with engine.connect() as connection:
            attachment_mapping = _mapping_row(
                connection,
                mapping,
                SYNTHETIC_SOURCE,
                attachment_key=SYNTHETIC_ATTACHMENT_KEY,
                active=True,
                marker="W1B_REC_02_ATTACHMENT_MISSING",
            )
            if attachment_mapping is None:
                _fail("W1B_REC_02_ATTACHMENT_MISSING: attachment-only mapping was not created")
            if (
                attachment_mapping.get("legacy_recipient_key") is not None
                or attachment_mapping.get("legacy_attachment_key") != SYNTHETIC_ATTACHMENT_KEY
            ):
                _fail("W1B_REC_02_ATTACHMENT_MISSING: attachment-only key nullability is wrong")
            attachment_recipient_id = int(attachment_mapping["recipient_id"])
            recipient_ids.add(attachment_recipient_id)

        duplicate_attachment_common = {
            **attachment_common,
            "rows": [attachment_row],
            "active_legacy_recipient_keys": frozenset({SYNTHETIC_LEGACY_KEY}),
            "active_legacy_attachment_keys": frozenset({SYNTHETIC_ATTACHMENT_KEY}),
        }
        duplicate_attachment_summary = _summary_payload(
            _invoke_importer(
                prepare,
                duplicate_attachment_common,
                "W1B_REC_02_ATTACHMENT_UNIQUE_MISSING",
            ),
            "W1B_REC_02_ATTACHMENT_UNIQUE_MISSING",
        )
        if duplicate_attachment_summary.get("included_count") != 0:
            _fail("W1B_REC_02_ATTACHMENT_UNIQUE_MISSING: duplicate attachment was accepted")
        with engine.connect() as connection:
            attachment_mapping_ids_before_apply = tuple(
                int(value)
                for value in connection.execute(
                    mapping.select()
                    .with_only_columns(mapping.c.id)
                    .where(mapping.c.source_system_code == SYNTHETIC_SOURCE)
                    .order_by(mapping.c.id)
                ).scalars()
            )
        with factory() as session:
            duplicate_attachment_common = {
                **duplicate_attachment_common,
                "database_session": session,
                "session": session,
                "prepared": duplicate_attachment_summary,
            }
            _invoke_importer(
                apply,
                duplicate_attachment_common,
                "W1B_REC_02_ATTACHMENT_APPLY_MISSING",
            )
            session.commit()
        with engine.connect() as connection:
            attachment_mapping_ids_after_apply = tuple(
                int(value)
                for value in connection.execute(
                    mapping.select()
                    .with_only_columns(mapping.c.id)
                    .where(mapping.c.source_system_code == SYNTHETIC_SOURCE)
                    .order_by(mapping.c.id)
                ).scalars()
            )
        if attachment_mapping_ids_after_apply != attachment_mapping_ids_before_apply:
            _fail("W1B_REC_02_ATTACHMENT_APPLY_MUTATED: duplicate apply created a mapping")
        _expected_insert_failure(
            engine,
            mapping,
            {
                "source_system_code": SYNTHETIC_SOURCE,
                "legacy_recipient_key": None,
                "legacy_attachment_key": SYNTHETIC_ATTACHMENT_KEY,
                "recipient_id": attachment_recipient_id,
            },
            cases["admin"].account_id,
            "W1B_REC_02_ATTACHMENT_DB_UNIQUE_MISSING: duplicate attachment was accepted",
        )

        duplicate_common = {
            **common,
            "rows": [first_row],
            "active_legacy_recipient_keys": frozenset({SYNTHETIC_LEGACY_KEY}),
        }
        duplicate_summary = _summary_payload(
            _invoke_importer(prepare, duplicate_common, "W1B_REC_02_ACTIVE_UNIQUE_MISSING"),
            "W1B_REC_02_ACTIVE_UNIQUE_MISSING",
        )
        if duplicate_summary.get("included_count") != 0:
            _fail("W1B_REC_02_ACTIVE_UNIQUE_MISSING: duplicate active key was accepted")
        with engine.connect() as connection:
            active_count = connection.execute(
                text(
                    """
                    SELECT count(*) FROM erp.recipient_legacy_mapping
                    WHERE source_system_code = :source
                      AND legacy_recipient_key = :legacy_key
                      AND invalidated_at_utc IS NULL
                    """
                ),
                {"source": SYNTHETIC_SOURCE, "legacy_key": SYNTHETIC_LEGACY_KEY},
            ).scalar_one()
            if active_count != 1:
                _fail("W1B_REC_02_ACTIVE_UNIQUE_MISSING: active key is not unique")

        with engine.begin() as connection:
            replacement_recipient_id = _insert_row(
                connection,
                recipient,
                {
                    "name": "TEST_W1B_REPLACEMENT_RECIPIENT_CANARY",
                    "birth_date": SYNTHETIC_BIRTH_DATE,
                    "sex_code": "TEST",
                },
                cases["admin"].account_id,
            )
        recipient_ids.add(replacement_recipient_id)
        with engine.connect() as connection:
            first_mapping = _mapping_row(
                connection,
                mapping,
                SYNTHETIC_SOURCE,
                SYNTHETIC_LEGACY_KEY,
                active=True,
                marker="W1B_REC_02_REPLACEMENT_MISSING",
            )
            if first_mapping is None:
                _fail("W1B_REC_02_MAPPING_CREATE_MISSING: original mapping disappeared")
            first_mapping_id = int(first_mapping["id"])
            first_version = int(first_mapping["row_version"])

        replacement_candidates = {
            "mapping_id": first_mapping_id,
            "legacy_mapping_id": first_mapping_id,
            "replacement_recipient_id": replacement_recipient_id,
            "recipient_id": replacement_recipient_id,
            "source_system_code": SYNTHETIC_SOURCE,
            "legacy_recipient_key": SYNTHETIC_LEGACY_KEY,
            "database_session": None,
            "actor_account_id": cases["admin"].account_id,
            "expected_row_version": first_version,
            "session_factory": factory,
            "session": None,
            "settings": settings,
        }
        with factory() as session:
            replacement_candidates = {
                **replacement_candidates,
                "database_session": session,
                "session": session,
            }
            _invoke_importer(replace, replacement_candidates, "W1B_REC_02_REPLACEMENT_MISSING")
            session.commit()
        with engine.connect() as connection:
            updated_first = _mapping_row(
                connection,
                mapping,
                SYNTHETIC_SOURCE,
                SYNTHETIC_LEGACY_KEY,
                mapping_id=first_mapping_id,
                active=False,
                marker="W1B_REC_02_REPLACEMENT_MISSING",
            )
            if updated_first is None or updated_first.get("invalidated_at_utc") is None:
                _fail("W1B_REC_02_REPLACEMENT_MISSING: old mapping was not invalidated")
            replacement_id = updated_first.get("replacement_recipient_legacy_mapping_id")
            if replacement_id is None:
                _fail(
                    "W1B_REC_02_REPLACEMENT_MISSING: replacement mapping relation was not recorded"
                )
            replacement_row = _mapping_row(
                connection,
                mapping,
                SYNTHETIC_SOURCE,
                SYNTHETIC_LEGACY_KEY,
                mapping_id=int(replacement_id),
                active=True,
                marker="W1B_REC_02_REPLACEMENT_MISSING",
            )
            if (
                replacement_row is None
                or int(replacement_row["recipient_id"]) != replacement_recipient_id
                or replacement_row.get("source_system_code") != SYNTHETIC_SOURCE
                or replacement_row.get("legacy_recipient_key") != SYNTHETIC_LEGACY_KEY
            ):
                _fail(
                    "W1B_REC_02_REPLACEMENT_MISSING: replacement did not preserve "
                    "source/original key"
                )
            active_same_key = connection.execute(
                text(
                    """
                    SELECT count(*) FROM erp.recipient_legacy_mapping
                    WHERE source_system_code = :source
                      AND legacy_recipient_key = :legacy_key
                      AND invalidated_at_utc IS NULL
                    """
                ),
                {"source": SYNTHETIC_SOURCE, "legacy_key": SYNTHETIC_LEGACY_KEY},
            ).scalar_one()
            if active_same_key != 1:
                _fail(
                    "W1B_REC_02_REPLACEMENT_MISSING: same-key active replacement count is not one"
                )
            replacement_mapping_id = int(replacement_row["id"])
            replacement_version = int(replacement_row["row_version"])

        invalidation_candidates = {
            "mapping_id": replacement_mapping_id,
            "legacy_mapping_id": replacement_mapping_id,
            "source_system_code": SYNTHETIC_SOURCE,
            "legacy_recipient_key": SYNTHETIC_LEGACY_KEY,
            "database_session": None,
            "actor_account_id": cases["admin"].account_id,
            "expected_row_version": replacement_version,
            "session_factory": factory,
            "session": None,
            "settings": settings,
        }
        with factory() as session:
            invalidation_candidates = {
                **invalidation_candidates,
                "database_session": session,
                "session": session,
            }
            _invoke_importer(invalidate, invalidation_candidates, "W1B_REC_02_INVALIDATION_MISSING")
            session.commit()
        with engine.connect() as connection:
            final_row = _mapping_row(
                connection,
                mapping,
                SYNTHETIC_SOURCE,
                SYNTHETIC_LEGACY_KEY,
                mapping_id=replacement_mapping_id,
                active=False,
                marker="W1B_REC_02_INVALIDATION_MISSING",
            )
            if final_row is None:
                _fail("W1B_REC_02_INVALIDATION_MISSING: replacement mapping row disappeared")
            if final_row.get("invalidated_at_utc") is None:
                _fail("W1B_REC_02_INVALIDATION_MISSING: invalidation did not persist")
            if final_row.get("legacy_recipient_key") != SYNTHETIC_LEGACY_KEY:
                _fail("W1B_REC_02_INVALIDATION_MISSING: invalidation did not use original key")
            active_same_key = connection.execute(
                text(
                    """
                    SELECT count(*) FROM erp.recipient_legacy_mapping
                    WHERE source_system_code = :source
                      AND legacy_recipient_key = :legacy_key
                      AND invalidated_at_utc IS NULL
                    """
                ),
                {"source": SYNTHETIC_SOURCE, "legacy_key": SYNTHETIC_LEGACY_KEY},
            ).scalar_one()
            if active_same_key != 0:
                _fail("W1B_REC_02_INVALIDATION_MISSING: original key remained active")
    finally:
        _cleanup(engine, cases, recipient_ids)
        engine.dispose()


def test_w1b_abs_01_public_legacy_surface_is_absent() -> None:
    document = _openapi_document()
    _assert_no_public_legacy_surface(document)


def test_w1b_abs_02_public_signer_surface_is_absent() -> None:
    document = _openapi_document()
    paths = document["paths"]
    assert isinstance(paths, dict)
    recipient_paths = {
        path: value for path, value in paths.items() if "/api/v1/recipients" in str(path)
    }
    serialized = json.dumps(recipient_paths, ensure_ascii=False).lower()
    if any(token in serialized for token in ("signer", "signature", "signer_token")):
        _fail("W1B_ABS_PUBLIC_SIGNER_SURFACE_FOUND: signer surface exists in W1B API")


def test_w1b_abs_03_leak_checker_self_test_is_separate() -> None:
    class SyntheticResponse:
        text = "SELECT TEST_W1B_SECRET_CANARY"

        @staticmethod
        def json() -> dict[str, str]:
            return {"detail": "TEST_W1B_SECRET_CANARY"}

    with pytest.raises(pytest.fail.Exception):
        _assert_safe_response(
            SyntheticResponse(),
            "W1B_LEAK_GATE_SELF_TEST_FAILED",
            "TEST_W1B_SECRET_CANARY",
        )
