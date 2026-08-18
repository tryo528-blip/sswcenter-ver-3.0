"""Static and fake-catalog postcheck contract for W3 0028."""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import readiness
from app.db.postcheck_current_0027 import EXPECTED_REVISION as HISTORICAL_0027_REVISION
from app.db.postcheck_current_0028 import (
    ACTIVE_PARTIAL_UNIQUE,
    CURRENT_0028_MARKER,
    EXPECTED_CHECKS,
    EXPECTED_COLUMN_CATALOG,
    EXPECTED_EXPLICIT_INDEXES,
    EXPECTED_FOREIGN_KEYS,
    EXPECTED_IDENTITY_SEQUENCES,
    EXPECTED_NON_CONSTRAINT_INDEXES,
    EXPECTED_OWNER,
    EXPECTED_PRIMARY_KEYS,
    EXPECTED_REVISION,
    EXPECTED_ROLE_ATTRIBUTES,
    EXPECTED_UNIQUES,
    EXPECTED_W3_RELATION_KINDS,
    FORBIDDEN_GENERIC_COLUMNS,
    HEAD_MARKER,
    IMMUTABLE_TABLES,
    MUTABLE_LINEAGE_TABLES,
    PG16_COLUMN_OWNER_PRIVILEGES,
    PG16_IDENTITY_SEQUENCE_OPTIONS,
    PG16_ORDINARY_FK_TRIGGER_COUNT,
    PG16_ORDINARY_LOCAL_FK_METADATA,
    PG16_SCHEMA_OWNER_PRIVILEGES,
    PG16_SEQUENCE_OWNER_PRIVILEGES,
    PG16_TABLE_OWNER_PRIVILEGES,
    REQUIRED_COLUMNS,
    REQUIRED_RUNTIME_ROLES,
    REQUIRED_SCHEMA_NON_OWNER_ACL,
    REQUIRED_SEQUENCE_NON_OWNER_ACL,
    REQUIRED_STATUS_COLUMN_NON_OWNER_ACL,
    REQUIRED_TABLE_NON_OWNER_ACL,
    REQUIRED_TABLES,
    SET_ROLE_SOURCE_ROLES,
    STATUS_UPDATE_COLUMN,
    W3_NAMESPACE_LIKE_SQL,
    _canonical_check_definition,
    _canonical_predicate,
    _exact_acl_drifts,
    _verify_fk_triggers_and_replication,
    _verify_no_bytea,
    _verify_rls_absent,
    _verify_runtime_roles,
    _verify_tables,
    expected_app_column_update,
    is_expected_active_partial_unique_conflict,
    required_column_non_owner_acl,
    verify_current_0028,
)
from app.db.postcheck_current_0028 import (
    _verify_active_partial_unique as _verify_active_partial_unique_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_checks as _verify_checks_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_columns as _verify_columns_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_explicit_indexes as _verify_explicit_indexes_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_foreign_keys as _verify_foreign_keys_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_identity_sequence_acl_entries as _verify_identity_sequence_acl_entries_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_identity_sequence_options as _verify_identity_sequence_options_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_primary_keys as _verify_primary_keys_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_relation_owners as _verify_relation_owners_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_relation_persistence as _verify_relation_persistence_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_revision as _verify_revision_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_shared_schema_acl as _verify_shared_schema_acl_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_uniques as _verify_uniques_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_w3_column_attacl_entries as _verify_w3_column_attacl_entries_impl,
)
from app.db.postcheck_current_0028 import (
    _verify_w3_table_relacl_entries as _verify_w3_table_relacl_entries_impl,
)
from app.db.postcheck_dispatch import (
    ACTIVE_REVISION,
)
from app.db.postcheck_dispatch import (
    _read_single_revision as _read_single_revision_impl,
)

_TestVerifier = Callable[[object], None]

# The postcheck helpers deliberately require a real SQLAlchemy ``Connection``
# in production.  These unit tests pass small fail-closed duck-typed catalog
# fakes, so adapt only the test call boundary instead of weakening production
# signatures or scattering per-call ignores through the oracle matrix.
_verify_active_partial_unique = cast(_TestVerifier, _verify_active_partial_unique_impl)
_verify_checks = cast(_TestVerifier, _verify_checks_impl)
_verify_columns = cast(_TestVerifier, _verify_columns_impl)
_verify_explicit_indexes = cast(_TestVerifier, _verify_explicit_indexes_impl)
_verify_foreign_keys = cast(_TestVerifier, _verify_foreign_keys_impl)
_verify_identity_sequence_acl_entries = cast(
    _TestVerifier, _verify_identity_sequence_acl_entries_impl
)
_verify_identity_sequence_options = cast(_TestVerifier, _verify_identity_sequence_options_impl)
_verify_primary_keys = cast(_TestVerifier, _verify_primary_keys_impl)
_verify_relation_owners = cast(_TestVerifier, _verify_relation_owners_impl)
_verify_relation_persistence = cast(_TestVerifier, _verify_relation_persistence_impl)
_verify_revision = cast(_TestVerifier, _verify_revision_impl)
_verify_shared_schema_acl = cast(_TestVerifier, _verify_shared_schema_acl_impl)
_verify_uniques = cast(_TestVerifier, _verify_uniques_impl)
_verify_w3_column_attacl_entries = cast(_TestVerifier, _verify_w3_column_attacl_entries_impl)
_verify_w3_table_relacl_entries = cast(_TestVerifier, _verify_w3_table_relacl_entries_impl)
_read_single_revision = cast(Callable[[object], str], _read_single_revision_impl)

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTCHECK_0028 = REPO_ROOT / "backend" / "app" / "db" / "postcheck_current_0028.py"
POSTCHECK_0027 = REPO_ROOT / "backend" / "app" / "db" / "postcheck_current_0027.py"
DISPATCHER = REPO_ROOT / "backend" / "app" / "db" / "postcheck_dispatch.py"
READINESS = REPO_ROOT / "backend" / "app" / "core" / "readiness.py"


class _FakeMappingsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeCatalogConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _statement: object, _params: object | None = None) -> _FakeMappingsResult:
        return _FakeMappingsResult(self._rows)


class _CapturingCatalogConnection(_FakeCatalogConnection):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__(rows)
        self.statements: list[str] = []

    def execute(self, statement: object, params: object | None = None) -> _FakeMappingsResult:
        self.statements.append(str(getattr(statement, "text", statement)))
        return super().execute(statement, params)


class _FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _FakeScalarResult:
        return self

    def all(self) -> list[object]:
        return list(self._values)


class _FakeTableScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def __iter__(self) -> Iterator[object]:
        return iter(self._values)


class _CapturingTableCatalogConnection:
    def __init__(self, values: list[object]) -> None:
        self._values = values
        self.statements: list[str] = []

    def scalars(self, statement: object) -> _FakeTableScalarResult:
        self.statements.append(str(getattr(statement, "text", statement)))
        return _FakeTableScalarResult(self._values)


class _RoutingCatalogConnection:
    """Fail-closed fake: each issued SQL fragment must match exactly one route."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.statements: list[str] = []

    def _lookup(self, statement: object) -> object:
        sql = str(getattr(statement, "text", statement))
        self.statements.append(sql)
        matches = [value for marker, value in self.routes.items() if marker in sql]
        if len(matches) != 1:
            raise SystemExit(
                f"CURRENT_0028_FAKE_CATALOG_QUERY_MISMATCH: matches={len(matches)} sql={sql}"
            )
        return matches[0]

    def execute(self, statement: object, _params: object | None = None) -> _FakeMappingsResult:
        value = self._lookup(statement)
        if not isinstance(value, list):
            raise SystemExit("CURRENT_0028_FAKE_CATALOG_EXECUTE_EXPECTED_ROWS")
        return _FakeMappingsResult(value)

    def scalar(self, statement: object, _params: object | None = None) -> object:
        value = self._lookup(statement)
        if isinstance(value, list):
            raise SystemExit("CURRENT_0028_FAKE_CATALOG_SCALAR_EXPECTED_VALUE")
        return value


class _FakeRevisionConnection:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def execute(self, _statement: object, _params: object | None = None) -> _FakeScalarResult:
        return _FakeScalarResult(self._values)


class _FakeColumnConnection:
    def __init__(self, by_table: dict[str, list[dict[str, Any]]]) -> None:
        self._by_table = by_table

    def execute(
        self, _statement: object, params: dict[str, object] | None = None
    ) -> _FakeMappingsResult:
        table_name = str((params or {})["table_name"])
        return _FakeMappingsResult(self._by_table[table_name])


def _check_definition(name: str) -> str:
    matches = [
        definition
        for (_table, check_name), definition in EXPECTED_CHECKS.items()
        if check_name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _check_rows() -> list[dict[str, Any]]:
    return [
        {
            "table_name": table_name,
            "conname": name,
            "convalidated": True,
            "definition": definition,
        }
        for (table_name, name), definition in EXPECTED_CHECKS.items()
    ]


def _unique_rows() -> list[dict[str, Any]]:
    return [
        {
            "index_name": name,
            "table_name": table_name,
            "relpersistence": "p",
            "indisvalid": True,
            "constraint_type": "u",
            "convalidated": True,
            "condeferrable": False,
            "condeferred": False,
            "columns": list(columns),
        }
        for name, (table_name, columns) in EXPECTED_UNIQUES.items()
    ]


def _partial_unique_rows(*, predicate: str = "status = 'ACTIVE'") -> list[dict[str, Any]]:
    name, table_name, columns, _expected = ACTIVE_PARTIAL_UNIQUE
    return [
        {
            "index_name": name,
            "table_name": table_name,
            "relpersistence": "p",
            "indisunique": True,
            "indisvalid": True,
            "predicate": predicate,
            "columns": list(columns),
        }
    ]


def _column_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        table_name: [
            {
                "column_name": column_name,
                "formatted_type": spec["type"],
                "nullable": spec["nullable"],
                "default_expr": spec["default"],
                "identity": spec["identity"],
            }
            for column_name, spec in columns.items()
        ]
        for table_name, columns in EXPECTED_COLUMN_CATALOG.items()
    }


def _primary_key_rows() -> list[dict[str, Any]]:
    return [
        {
            "constraint_name": name,
            "table_name": table_name,
            "relpersistence": "p",
            "indisvalid": True,
            "convalidated": True,
            "condeferrable": False,
            "condeferred": False,
            "columns": list(columns),
        }
        for name, (table_name, columns) in EXPECTED_PRIMARY_KEYS.items()
    ]


def _explicit_index_rows() -> list[dict[str, Any]]:
    return [
        {
            "index_name": name,
            "table_name": expected["table"],
            "access_method": expected["access_method"],
            "relpersistence": "p",
            "indisunique": expected["unique"],
            "indisvalid": True,
            "predicate": expected["predicate"],
            "key_items": list(expected["columns"]),
            "include_columns": list(expected["include"]),
        }
        for name, expected in EXPECTED_NON_CONSTRAINT_INDEXES.items()
    ]


def _owner_rows(
    *,
    table_owner: str = EXPECTED_OWNER,
    sequence_owner: str = EXPECTED_OWNER,
    owned_column: str = "id",
    identity_deptype: str = "i",
) -> list[dict[str, Any]]:
    return [
        {
            "table_name": table_name,
            "table_owner": table_owner,
            "sequence_owner": sequence_owner,
            "sequence_name": f"{table_name}_id_seq",
            "sequence_kind": "S",
            "owned_sequence": f"erp.{table_name}_id_seq",
            "identity_deptype": identity_deptype,
            "owned_column": owned_column,
        }
        for table_name in sorted(REQUIRED_TABLES)
    ]


def _sequence_acl_rows(
    entries: list[tuple[str, str, str, bool]] | None = None,
    *,
    sequence_owner: str = EXPECTED_OWNER,
) -> list[dict[str, Any]]:
    privileges = entries
    if privileges is None:
        privileges = [
            ("erp_app", EXPECTED_OWNER, "USAGE", False),
            ("erp_app", EXPECTED_OWNER, "SELECT", False),
            ("erp_backup", EXPECTED_OWNER, "SELECT", False),
        ]
    rows: list[dict[str, Any]] = []
    for table_name in sorted(REQUIRED_TABLES):
        sequence_name = f"{table_name}_id_seq"
        if not privileges:
            rows.append(
                {
                    "sequence_name": sequence_name,
                    "sequence_owner": sequence_owner,
                    "grantee": None,
                    "grantor": None,
                    "privilege_type": None,
                    "is_grantable": None,
                }
            )
            continue
        for grantee, grantor, privilege, grantable in privileges:
            rows.append(
                {
                    "sequence_name": sequence_name,
                    "sequence_owner": sequence_owner,
                    "grantee": grantee,
                    "grantor": grantor,
                    "privilege_type": privilege,
                    "is_grantable": grantable,
                }
            )
    return rows


def _schema_acl_rows(
    entries: list[tuple[str, str, str, bool]] | None = None,
    *,
    schema_owner: str = EXPECTED_OWNER,
) -> list[dict[str, Any]]:
    privileges = entries
    if privileges is None:
        privileges = [
            ("erp_app", EXPECTED_OWNER, "USAGE", False),
            ("erp_backup", EXPECTED_OWNER, "USAGE", False),
        ]
    if not privileges:
        return [
            {
                "schema_owner": schema_owner,
                "grantee": None,
                "grantor": None,
                "privilege_type": None,
                "is_grantable": None,
            }
        ]
    return [
        {
            "schema_owner": schema_owner,
            "grantee": grantee,
            "grantor": grantor,
            "privilege_type": privilege,
            "is_grantable": grantable,
        }
        for grantee, grantor, privilege, grantable in privileges
    ]


def _complete_owner_entries(privileges: frozenset[str]) -> list[tuple[str, str, str, bool]]:
    return [(EXPECTED_OWNER, EXPECTED_OWNER, privilege, False) for privilege in sorted(privileges)]


def _table_acl_rows(
    entries: list[tuple[str, str, str, bool]] | None = None,
    *,
    table_owner: str = EXPECTED_OWNER,
) -> list[dict[str, Any]]:
    privileges = entries
    if privileges is None:
        privileges = [
            *_complete_owner_entries(PG16_TABLE_OWNER_PRIVILEGES),
            ("erp_app", EXPECTED_OWNER, "SELECT", False),
            ("erp_app", EXPECTED_OWNER, "INSERT", False),
            ("erp_backup", EXPECTED_OWNER, "SELECT", False),
        ]
    if not privileges:
        return [
            {
                "table_name": table_name,
                "table_owner": table_owner,
                "grantee": None,
                "grantor": None,
                "privilege_type": None,
                "is_grantable": None,
            }
            for table_name in sorted(REQUIRED_TABLES)
        ]
    rows: list[dict[str, Any]] = []
    for table_name in sorted(REQUIRED_TABLES):
        for grantee, grantor, privilege, grantable in privileges:
            rows.append(
                {
                    "table_name": table_name,
                    "table_owner": table_owner,
                    "grantee": grantee,
                    "grantor": grantor,
                    "privilege_type": privilege,
                    "is_grantable": grantable,
                }
            )
    return rows


def _column_acl_rows(
    *,
    table_owner: str = EXPECTED_OWNER,
    include_owner: bool = False,
    extra: list[tuple[str, str, str, str, str, bool]] | None = None,
    replace_status_grantor: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    extras = extra or []
    for table_name in sorted(REQUIRED_TABLES):
        for column_name in REQUIRED_COLUMNS[table_name]:
            emitted = False
            if include_owner:
                for privilege in sorted(PG16_COLUMN_OWNER_PRIVILEGES):
                    rows.append(
                        {
                            "table_name": table_name,
                            "column_name": column_name,
                            "table_owner": table_owner,
                            "grantee": EXPECTED_OWNER,
                            "grantor": EXPECTED_OWNER,
                            "privilege_type": privilege,
                            "is_grantable": False,
                        }
                    )
                emitted = True
            if expected_app_column_update(table_name, column_name):
                rows.append(
                    {
                        "table_name": table_name,
                        "column_name": column_name,
                        "table_owner": table_owner,
                        "grantee": "erp_app",
                        "grantor": replace_status_grantor or EXPECTED_OWNER,
                        "privilege_type": "UPDATE",
                        "is_grantable": False,
                    }
                )
                emitted = True
            for extra_table, extra_column, grantee, grantor, privilege, grantable in extras:
                if extra_table == table_name and extra_column == column_name:
                    rows.append(
                        {
                            "table_name": table_name,
                            "column_name": column_name,
                            "table_owner": table_owner,
                            "grantee": grantee,
                            "grantor": grantor,
                            "privilege_type": privilege,
                            "is_grantable": grantable,
                        }
                    )
                    emitted = True
            if not emitted:
                rows.append(
                    {
                        "table_name": table_name,
                        "column_name": column_name,
                        "table_owner": table_owner,
                        "grantee": None,
                        "grantor": None,
                        "privilege_type": None,
                        "is_grantable": None,
                    }
                )
    return rows


_PG16_CHECK_DEPARSES = {
    "ck_w3_private_content_storage_locator": (
        "CHECK (storage_locator ~ '^w3-private:[0-9a-f]{32,}$'::text "
        "AND storage_locator !~~ 'http%'::text "
        "AND position(('://'::text) IN (storage_locator)) = 0)"
    ),
    "ck_w3_private_content_quarantine_state": (
        "CHECK (quarantine_state = ANY (ARRAY['NONE'::text, 'QUARANTINED'::text]))"
    ),
    "ck_w3_private_content_legal_hold_state": (
        "CHECK (legal_hold_state = ANY (ARRAY['NONE'::text, 'HELD'::text]))"
    ),
    "ck_w3_source_snapshot_source_type": (
        "CHECK (source_type = ANY (ARRAY['RFID'::text, 'NHIS_SCHEDULE'::text]))"
    ),
    "ck_w3_source_snapshot_status": (
        "CHECK (status = ANY (ARRAY['CANDIDATE'::text, 'ACTIVE'::text, 'SUPERSEDED'::text]))"
    ),
    "ck_w3_source_receipt_actor_type": (
        "CHECK (actor_type = ANY (ARRAY['USER_ACCOUNT'::text, 'SYSTEM_RUN'::text]))"
    ),
    "ck_w3_source_receipt_source_context_type": (
        "CHECK (source_context_type = ANY (ARRAY['RFID_FILE'::text, 'NHIS_SCHEDULE_FILE'::text]))"
    ),
    "ck_w3_import_run_status": (
        "CHECK (status = ANY (ARRAY['RECEIVED'::text, 'PARSING'::text, "
        "'PREVIEW_READY'::text, 'CONFIRMED'::text, 'APPLYING'::text, "
        "'APPLIED'::text, 'BLOCKED'::text, 'FAILED'::text]))"
    ),
    "ck_w3_import_attempt_status": (
        "CHECK (status = ANY (ARRAY['SUCCEEDED'::text, 'FAILED_RETRYABLE'::text, 'BLOCKED'::text]))"
    ),
    "ck_w3_source_row_sheet_ref": (
        "CHECK ((btrim(sheet_ref) <> ''::text) AND (position(('://'::text) IN (sheet_ref)) = 0))"
    ),
}


def test_0028_postcheck_constants_are_exact() -> None:
    assert EXPECTED_REVISION == "20260817_0028_w3_source_intake_foundation"
    assert CURRENT_0028_MARKER == "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK"
    assert HEAD_MARKER == "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"
    assert REQUIRED_TABLES == {
        "w3_private_content",
        "w3_source_receipt",
        "w3_source_snapshot",
        "w3_import_run",
        "w3_import_attempt",
        "w3_source_row",
    }
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
    assert REQUIRED_COLUMNS["w3_private_content"]["content_digest"] is False
    assert "parser_profile_version" not in REQUIRED_COLUMNS["w3_source_snapshot"]
    assert REQUIRED_COLUMNS["w3_import_attempt"]["receipt_id"] is False
    assert "target_type" not in REQUIRED_COLUMNS["w3_import_run"]
    assert EXPECTED_UNIQUES["uq_w3_source_snapshot_identity"] == (
        "erp.w3_source_snapshot",
        ("source_type", "target_date", "content_digest"),
    )
    assert ACTIVE_PARTIAL_UNIQUE == (
        "uq_w3_source_snapshot_one_active_per_source_date",
        "erp.w3_source_snapshot",
        ("source_type", "target_date"),
        "status = 'ACTIVE'",
    )
    assert EXPECTED_FOREIGN_KEYS[("w3_import_attempt", "fk_w3_import_attempt_receipt_lineage")][
        "columns"
    ] == (
        "receipt_id",
        "snapshot_id",
        "content_id",
        "content_digest",
    )
    assert EXPECTED_IDENTITY_SEQUENCES == {f"{name}_id_seq" for name in REQUIRED_TABLES}
    assert EXPECTED_W3_RELATION_KINDS["w3_source_row"] == "r"
    assert EXPECTED_W3_RELATION_KINDS["w3_source_row_id_seq"] == "S"
    assert REQUIRED_RUNTIME_ROLES == ("erp_owner", "erp_app", "erp_backup")
    assert SET_ROLE_SOURCE_ROLES == ("erp_app", "erp_backup")
    assert EXPECTED_ROLE_ATTRIBUTES == {
        "rolsuper": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "rolreplication": False,
        "rolbypassrls": False,
        "rolcanlogin": True,
        "rolinherit": True,
    }
    assert W3_NAMESPACE_LIKE_SQL == "LIKE 'w3\\_%' ESCAPE '\\'"
    assert PG16_ORDINARY_FK_TRIGGER_COUNT == 4
    assert PG16_ORDINARY_LOCAL_FK_METADATA == {
        "match_type": "s",
        "is_local": True,
        "inherit_count": 0,
        "no_inherit": True,
        "parent_oid": 0,
    }
    assert PG16_IDENTITY_SEQUENCE_OPTIONS == {
        "seqtypid": 20,
        "seqstart": 1,
        "seqincrement": 1,
        "seqmin": 1,
        "seqmax": 9223372036854775807,
        "seqcache": 1,
        "seqcycle": False,
    }
    assert ("w3_private_content", "ck_w3_private_content_digest_sha256") in EXPECTED_CHECKS
    assert ("w3_import_attempt", "ck_w3_import_attempt_status") in EXPECTED_CHECKS
    assert EXPECTED_PRIMARY_KEYS["pk_w3_source_row"] == ("erp.w3_source_row", ("id",))
    assert EXPECTED_EXPLICIT_INDEXES["ix_w3_source_row_receipt_id"]["columns"] == ("receipt_id",)
    assert EXPECTED_EXPLICIT_INDEXES["ix_w3_source_row_receipt_id"]["access_method"] == "btree"
    assert EXPECTED_EXPLICIT_INDEXES["ix_w3_source_row_receipt_id"]["include"] == ()
    assert EXPECTED_OWNER == "erp_owner"
    assert ACTIVE_PARTIAL_UNIQUE[0] in EXPECTED_NON_CONSTRAINT_INDEXES
    assert EXPECTED_NON_CONSTRAINT_INDEXES[ACTIVE_PARTIAL_UNIQUE[0]]["unique"] is True
    assert REQUIRED_SEQUENCE_NON_OWNER_ACL["erp_app"] == {("SELECT", False), ("USAGE", False)}
    assert REQUIRED_SEQUENCE_NON_OWNER_ACL["erp_backup"] == {("SELECT", False)}
    assert REQUIRED_SCHEMA_NON_OWNER_ACL["erp_app"] == {("USAGE", False)}
    assert REQUIRED_SCHEMA_NON_OWNER_ACL["erp_backup"] == {("USAGE", False)}
    assert REQUIRED_TABLE_NON_OWNER_ACL["erp_app"] == {("SELECT", False), ("INSERT", False)}
    assert REQUIRED_TABLE_NON_OWNER_ACL["erp_backup"] == {("SELECT", False)}
    assert REQUIRED_STATUS_COLUMN_NON_OWNER_ACL == {"erp_app": {("UPDATE", False)}}
    assert PG16_SEQUENCE_OWNER_PRIVILEGES == frozenset({"SELECT", "UPDATE", "USAGE"})
    assert PG16_SCHEMA_OWNER_PRIVILEGES == frozenset({"CREATE", "USAGE"})
    assert PG16_TABLE_OWNER_PRIVILEGES == frozenset(
        {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}
    )
    assert PG16_COLUMN_OWNER_PRIVILEGES == frozenset({"SELECT", "INSERT", "UPDATE", "REFERENCES"})
    assert required_column_non_owner_acl("w3_source_snapshot", "status") == (
        REQUIRED_STATUS_COLUMN_NON_OWNER_ACL
    )
    assert required_column_non_owner_acl("w3_source_receipt", "original_filename") == {}
    assert EXPECTED_COLUMN_CATALOG["w3_import_run"]["status"]["type"] == "text"
    assert EXPECTED_COLUMN_CATALOG["w3_source_row"]["id"]["identity"] == "d"
    assert expected_app_column_update("w3_source_snapshot", "status") is True
    assert expected_app_column_update("w3_import_run", STATUS_UPDATE_COLUMN) is True
    assert expected_app_column_update("w3_import_run", "parser_profile_version") is False
    assert expected_app_column_update("w3_source_receipt", "original_filename") is False
    assert expected_app_column_update("w3_source_snapshot", "created_at_utc") is False


def test_check_canonicalizer_accepts_only_display_equivalent_pg16_forms() -> None:
    expected = _check_definition("ck_w3_source_receipt_actor_pair")
    display_variant = (
        "CHECK (((actor_type = 'USER_ACCOUNT'::text) AND (actor_account_id IS NOT NULL)) "
        "OR ((actor_type = 'SYSTEM_RUN'::text) AND (actor_account_id IS NULL)))"
    )
    assert _canonical_check_definition(display_variant) == _canonical_check_definition(expected)
    assert _canonical_check_definition("CHECK (true)") != _canonical_check_definition(expected)
    assert _canonical_check_definition(
        "CHECK (actor_type = 'USER_ACCOUNT' AND actor_account_id IS NOT NULL)"
    ) != _canonical_check_definition(expected)

    expected_quarantine = _check_definition("ck_w3_private_content_quarantine_state")
    assert _canonical_check_definition(
        _PG16_CHECK_DEPARSES["ck_w3_private_content_quarantine_state"]
    ) == _canonical_check_definition(expected_quarantine)
    assert _canonical_check_definition(
        expected_quarantine.replace("'NONE'", "'none'")
    ) != _canonical_check_definition(expected_quarantine)
    assert _canonical_check_definition(
        _check_definition("ck_w3_source_snapshot_source_type").replace("'RFID'", "'rfid'")
    ) != _canonical_check_definition(_check_definition("ck_w3_source_snapshot_source_type"))
    assert _canonical_check_definition(
        _check_definition("ck_w3_import_attempt_status").replace("'SUCCEEDED'", "'succeeded'")
    ) != _canonical_check_definition(_check_definition("ck_w3_import_attempt_status"))


def test_predicate_canonicalizer_preserves_quoted_active() -> None:
    expected = ACTIVE_PARTIAL_UNIQUE[3]
    assert _canonical_predicate("(status = 'ACTIVE'::text)") == _canonical_predicate(expected)
    assert _canonical_predicate("status = 'ACTIVE'") == _canonical_predicate(expected)
    assert _canonical_predicate("status = 'active'") != _canonical_predicate(expected)
    assert _canonical_predicate("status = 'Active'") != _canonical_predicate(expected)


def _relation_inventory_rows(
    extra: list[dict[str, Any]] | None = None,
    *,
    drop: set[str] | None = None,
) -> list[dict[str, Any]]:
    skipped = drop or set()
    rows = [
        {
            "relname": name,
            "relkind": kind,
            "relispartition": False,
            "relpersistence": "p",
        }
        for name, kind in sorted(EXPECTED_W3_RELATION_KINDS.items())
        if name not in skipped
    ]
    if extra:
        rows.extend(extra)
    return rows


def _inventory_routes(
    rows: list[dict[str, Any]] | None = None,
    inherits: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    return {
        "relation_row.relkind IN ('r', 'p', 'v', 'f', 'm', 'S')": rows
        if rows is not None
        else _relation_inventory_rows(),
        "FROM pg_inherits AS inherit_row": inherits if inherits is not None else [],
    }


def test_fake_catalog_tables_use_pg_catalog_and_reject_hidden_w3_relation() -> None:
    visible = _RoutingCatalogConnection(_inventory_routes())
    _verify_tables(visible)  # type: ignore[arg-type]

    query = " ".join(visible.statements)
    assert "FROM pg_class AS relation_row" in query
    assert "JOIN pg_namespace AS namespace_row" in query
    assert "relation_row.relkind IN ('r', 'p', 'v', 'f', 'm', 'S')" in query
    assert "FROM pg_inherits AS inherit_row" in query
    assert W3_NAMESPACE_LIKE_SQL in query
    assert "LIKE 'w3_%'" not in query
    assert "information_schema.tables" not in query
    assert "last_value" not in query

    with pytest.raises(SystemExit, match="CURRENT_0028_FAKE_CATALOG_QUERY_MISMATCH"):
        _verify_tables(
            _RoutingCatalogConnection(
                {
                    "relation_row.relkind IN ('r', 'p', 'v', 'f', 'm', 'S')": (
                        _relation_inventory_rows()
                    )
                }
            )  # type: ignore[arg-type]
        )

    hidden_no_privilege = _RoutingCatalogConnection(
        _inventory_routes(
            _relation_inventory_rows(
                extra=[
                    {
                        "relname": "w3_hidden_no_privilege",
                        "relkind": "r",
                        "relispartition": False,
                        "relpersistence": "p",
                    }
                ]
            )
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_MISMATCH"):
        _verify_tables(hidden_no_privilege)  # type: ignore[arg-type]

    hidden_matview = _RoutingCatalogConnection(
        _inventory_routes(
            _relation_inventory_rows(
                extra=[
                    {
                        "relname": "w3_hidden_matview",
                        "relkind": "m",
                        "relispartition": False,
                        "relpersistence": "p",
                    }
                ]
            )
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_MISMATCH"):
        _verify_tables(hidden_matview)  # type: ignore[arg-type]

    hidden_sequence = _RoutingCatalogConnection(
        _inventory_routes(
            _relation_inventory_rows(
                extra=[
                    {
                        "relname": "w3_hidden_seq",
                        "relkind": "S",
                        "relispartition": False,
                        "relpersistence": "p",
                    }
                ]
            )
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_MISMATCH"):
        _verify_tables(hidden_sequence)  # type: ignore[arg-type]

    missing_sequence = _RoutingCatalogConnection(
        _inventory_routes(_relation_inventory_rows(drop={"w3_source_row_id_seq"}))
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_MISMATCH"):
        _verify_tables(missing_sequence)  # type: ignore[arg-type]

    partitioned = _relation_inventory_rows()
    for row in partitioned:
        if row["relname"] == "w3_import_attempt":
            row["relispartition"] = True
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_KIND_MISMATCH"):
        _verify_tables(_RoutingCatalogConnection(_inventory_routes(partitioned)))  # type: ignore[arg-type]

    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_INHERITANCE_MISMATCH"):
        _verify_tables(
            _RoutingCatalogConnection(
                _inventory_routes(
                    inherits=[{"child_name": "w3_import_attempt", "parent_name": "w3_parent"}]
                )
            )  # type: ignore[arg-type]
        )


def test_fake_catalog_accepts_pg16_deparse_only_for_exact_w3_check_semantics() -> None:
    rows = _check_rows()
    for row in rows:
        if row["conname"] in _PG16_CHECK_DEPARSES:
            row["definition"] = _PG16_CHECK_DEPARSES[row["conname"]]
    _verify_checks(_FakeCatalogConnection(rows))

    weakened_storage_locator = _check_rows()
    for row in weakened_storage_locator:
        if row["conname"] == "ck_w3_private_content_storage_locator":
            row["definition"] = (
                "CHECK (storage_locator ~ '^w3-private:[0-9a-f]{32,}$'::text "
                "AND storage_locator !~~ 'https%'::text "
                "AND position(('://'::text) IN (storage_locator)) = 0)"
            )
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(weakened_storage_locator))

    narrowed_attempt_status = _check_rows()
    for row in narrowed_attempt_status:
        if row["conname"] == "ck_w3_import_attempt_status":
            row["definition"] = "CHECK (status = ANY (ARRAY['SUCCEEDED'::text]))"
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(narrowed_attempt_status))


def test_fake_catalog_rejects_quoted_literal_case_mutations() -> None:
    none_lowered = _check_rows()
    for row in none_lowered:
        if row["conname"] == "ck_w3_private_content_quarantine_state":
            row["definition"] = "CHECK (quarantine_state = ANY (ARRAY['none', 'QUARANTINED']))"
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(none_lowered))

    rfid_lowered = _check_rows()
    for row in rfid_lowered:
        if row["conname"] == "ck_w3_source_snapshot_source_type":
            row["definition"] = "CHECK (source_type = ANY (ARRAY['rfid', 'NHIS_SCHEDULE']))"
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(rfid_lowered))

    succeeded_lowered = _check_rows()
    for row in succeeded_lowered:
        if row["conname"] == "ck_w3_import_attempt_status":
            row["definition"] = (
                "CHECK (status = ANY (ARRAY['succeeded', 'FAILED_RETRYABLE', 'BLOCKED']))"
            )
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(succeeded_lowered))


def test_fake_catalog_accepts_exact_checks_and_rejects_weakened_actor_pair() -> None:
    _verify_checks(_FakeCatalogConnection(_check_rows()))

    weakened = _check_rows()
    for row in weakened:
        if row["conname"] == "ck_w3_source_receipt_actor_pair":
            row["definition"] = "CHECK (true)"
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(weakened))


def test_fake_catalog_rejects_moved_duplicate_missing_or_extra_checks() -> None:
    unvalidated = _check_rows()
    unvalidated[0]["convalidated"] = False
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(unvalidated))

    extra = _check_rows() + [
        {
            "table_name": "w3_source_row",
            "conname": "ck_w3_source_row_unreviewed",
            "convalidated": True,
            "definition": "CHECK (true)",
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_NAME_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(extra))

    missing = _check_rows()[1:]
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_NAME_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(missing))

    moved = _check_rows()
    for row in moved:
        if row["conname"] == "ck_w3_source_receipt_actor_pair":
            row["table_name"] = "w3_source_row"
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_NAME_MISMATCH"):
        _verify_checks(_FakeCatalogConnection(moved))

    duplicate = _check_rows()
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_DUPLICATE"):
        _verify_checks(_FakeCatalogConnection(duplicate))


def test_fake_catalog_accepts_only_uppercase_active_partial_unique_predicate() -> None:
    _verify_active_partial_unique(_FakeCatalogConnection(_partial_unique_rows()))
    _verify_active_partial_unique(
        _FakeCatalogConnection(_partial_unique_rows(predicate="(status = 'ACTIVE'::text)"))
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_ACTIVE_PARTIAL_UNIQUE_MISMATCH"):
        _verify_active_partial_unique(
            _FakeCatalogConnection(_partial_unique_rows(predicate="status = 'active'"))
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_ACTIVE_PARTIAL_UNIQUE_MISMATCH"):
        _verify_active_partial_unique(
            _FakeCatalogConnection(_partial_unique_rows(predicate="status = 'Active'"))
        )


def test_fake_catalog_rejects_extra_or_plain_unique_index() -> None:
    _verify_uniques(_FakeCatalogConnection(_unique_rows()))

    extra = _unique_rows() + [
        {
            "index_name": "uq_w3_source_row_unreviewed",
            "table_name": "erp.w3_source_row",
            "relpersistence": "p",
            "indisvalid": True,
            "constraint_type": "u",
            "convalidated": True,
            "condeferrable": False,
            "condeferred": False,
            "columns": ["source_row_number"],
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_UNIQUE_MISMATCH"):
        _verify_uniques(_FakeCatalogConnection(extra))

    plain_index = _unique_rows()
    plain_index[0]["constraint_type"] = None
    with pytest.raises(SystemExit, match="CURRENT_0028_UNIQUE_MISMATCH"):
        _verify_uniques(_FakeCatalogConnection(plain_index))


def test_fake_catalog_rejects_column_type_default_and_identity_mutations() -> None:
    _verify_columns(_FakeColumnConnection(_column_rows()))

    missing_default = _column_rows()
    for row in missing_default["w3_source_row"]:
        if row["column_name"] == "created_at_utc":
            row["default_expr"] = None
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        _verify_columns(_FakeColumnConnection(missing_default))

    type_changed = _column_rows()
    for row in type_changed["w3_source_row"]:
        if row["column_name"] == "sheet_ref":
            row["formatted_type"] = "character varying(64)"
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        _verify_columns(_FakeColumnConnection(type_changed))

    identity_dropped = _column_rows()
    for row in identity_dropped["w3_source_row"]:
        if row["column_name"] == "id":
            row["identity"] = ""
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        _verify_columns(_FakeColumnConnection(identity_dropped))


def test_fake_catalog_rejects_missing_pk_and_explicit_index_mutations() -> None:
    _verify_primary_keys(_FakeCatalogConnection(_primary_key_rows()))
    missing_pk = [
        row for row in _primary_key_rows() if row["constraint_name"] != "pk_w3_source_row"
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_PRIMARY_KEY_MISMATCH"):
        _verify_primary_keys(_FakeCatalogConnection(missing_pk))

    _verify_explicit_indexes(_FakeCatalogConnection(_explicit_index_rows()))
    missing_index = [
        row for row in _explicit_index_rows() if row["index_name"] != "ix_w3_source_row_receipt_id"
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        _verify_explicit_indexes(_FakeCatalogConnection(missing_index))

    extra_index = _explicit_index_rows() + [
        {
            "index_name": "ix_w3_source_row_unreviewed",
            "table_name": "erp.w3_source_row",
            "access_method": "btree",
            "relpersistence": "p",
            "indisunique": False,
            "indisvalid": True,
            "predicate": "",
            "key_items": ["id"],
            "include_columns": [],
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        _verify_explicit_indexes(_FakeCatalogConnection(extra_index))


def test_direct_revision_verifier_requires_exact_single_expected_row() -> None:
    _verify_revision(_FakeRevisionConnection([EXPECTED_REVISION]))
    with pytest.raises(SystemExit, match="CURRENT_0028_REVISION_MISMATCH"):
        _verify_revision(_FakeRevisionConnection([EXPECTED_REVISION, "w3_0028_rogue_second_head"]))
    with pytest.raises(SystemExit, match="CURRENT_0028_REVISION_MISMATCH"):
        _verify_revision(_FakeRevisionConnection([]))
    with pytest.raises(SystemExit, match="CURRENT_0028_REVISION_MISMATCH"):
        _verify_revision(
            _FakeRevisionConnection(
                ["20260817_0027_w2_official_card_assignee_and_plan_replacement"]
            )
        )


def test_dispatcher_and_readiness_fetch_all_alembic_version_rows() -> None:
    dispatcher_source = DISPATCHER.read_text(encoding="utf-8")
    readiness_source = READINESS.read_text(encoding="utf-8")
    postcheck_source = POSTCHECK_0028.read_text(encoding="utf-8")
    assert "SELECT version_num FROM erp.alembic_version" in dispatcher_source
    assert "len(values) != 1" in dispatcher_source
    assert "FOUNDATION_0028_REVISION_CARDINALITY" in dispatcher_source
    assert "SELECT version_num FROM erp.alembic_version" in readiness_source
    assert "len(revisions) != 1" in readiness_source
    assert "alembic_revision_cardinality" in readiness_source
    assert "revisions != [EXPECTED_REVISION]" in postcheck_source
    assert readiness.CURRENT_ALEMBIC_REVISION == EXPECTED_REVISION
    with pytest.raises(SystemExit, match="FOUNDATION_0028_REVISION_CARDINALITY"):
        _read_single_revision(
            _FakeRevisionConnection([EXPECTED_REVISION, "w3_0028_rogue_second_head"])
        )


def test_historical_0027_direct_verifier_cannot_emit_head_marker() -> None:
    historical = POSTCHECK_0027.read_text(encoding="utf-8")
    current = POSTCHECK_0028.read_text(encoding="utf-8")
    dispatcher = DISPATCHER.read_text(encoding="utf-8")

    assert HISTORICAL_0027_REVISION == (
        "20260817_0027_w2_official_card_assignee_and_plan_replacement"
    )
    assert "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK" not in historical
    assert 'print("SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK")' in historical
    assert "print(HEAD_MARKER)" in current
    assert "print(CURRENT_0028_MARKER)" in current
    assert ACTIVE_REVISION == EXPECTED_REVISION
    assert dispatcher.count("print(HEAD_MARKER)") == 1
    assert "verify_current_0028(connection)" in dispatcher
    assert "verify_current_0027" not in dispatcher
    assert "verify_current_0026" not in dispatcher
    assert "verify_current_0025" not in dispatcher


def test_0028_postcheck_rejects_weaker_check_and_generic_column_lookalikes() -> None:
    digest_check = _check_definition("ck_w3_private_content_digest_sha256")
    assert "^[0-9a-f]{64}$" in digest_check
    assert digest_check != "CHECK (content_digest IS NOT NULL)"
    attempt_check = _check_definition("ck_w3_import_attempt_status")
    assert "SUCCEEDED" in attempt_check
    assert "FAILED_RETRYABLE" in attempt_check
    assert "BLOCKED" in attempt_check
    assert "IN_PROGRESS" not in attempt_check
    assert "FAILED_NONRETRYABLE" not in attempt_check
    locator_check = _check_definition("ck_w3_private_content_storage_locator")
    assert "w3-private:" in locator_check
    assert "http" in locator_check


def test_race_oracle_accepts_only_23505_on_the_exact_partial_unique() -> None:
    matching = IntegrityError(
        "INSERT",
        {},
        cast(
            BaseException,
            SimpleNamespace(
                sqlstate="23505",
                pgcode="23505",
                diag=SimpleNamespace(constraint_name=ACTIVE_PARTIAL_UNIQUE[0]),
            ),
        ),
    )
    assert is_expected_active_partial_unique_conflict(matching) is True

    wrong_state = IntegrityError(
        "INSERT",
        {},
        cast(
            BaseException,
            SimpleNamespace(
                sqlstate="23503",
                pgcode="23503",
                diag=SimpleNamespace(constraint_name=ACTIVE_PARTIAL_UNIQUE[0]),
            ),
        ),
    )
    assert is_expected_active_partial_unique_conflict(wrong_state) is False

    wrong_index = IntegrityError(
        "INSERT",
        {},
        cast(
            BaseException,
            SimpleNamespace(
                sqlstate="23505",
                pgcode="23505",
                diag=SimpleNamespace(constraint_name="uq_w3_source_snapshot_identity"),
            ),
        ),
    )
    assert is_expected_active_partial_unique_conflict(wrong_index) is False
    assert is_expected_active_partial_unique_conflict(RuntimeError("injected-unexpected")) is False
    assert (
        is_expected_active_partial_unique_conflict(
            IntegrityError("INSERT", {}, cast(BaseException, None))
        )
        is False
    )


def test_fake_catalog_rejects_unexpected_owner_and_unowned_identity() -> None:
    _verify_relation_owners(_FakeCatalogConnection(_owner_rows()))

    with pytest.raises(SystemExit, match="CURRENT_0028_RELATION_OWNER_MISMATCH"):
        _verify_relation_owners(_FakeCatalogConnection(_owner_rows(table_owner="erp_app")))
    with pytest.raises(SystemExit, match="CURRENT_0028_RELATION_OWNER_MISMATCH"):
        _verify_relation_owners(_FakeCatalogConnection(_owner_rows(sequence_owner="erp_app")))
    with pytest.raises(SystemExit, match="CURRENT_0028_RELATION_OWNER_MISMATCH"):
        _verify_relation_owners(_FakeCatalogConnection(_owner_rows(owned_column="receipt_id")))
    with pytest.raises(SystemExit, match="CURRENT_0028_RELATION_OWNER_MISMATCH"):
        _verify_relation_owners(_FakeCatalogConnection(_owner_rows(identity_deptype="a")))

    mixed = _owner_rows()
    for row in mixed:
        if row["table_name"] == "w3_source_row":
            row["table_owner"] = "postgres"
    with pytest.raises(SystemExit, match="CURRENT_0028_RELATION_OWNER_MISMATCH"):
        _verify_relation_owners(_FakeCatalogConnection(mixed))


def test_exact_acl_helper_rejects_partial_surplus_and_foreign_owner_sets() -> None:
    good_sequence = [
        ("erp_app", EXPECTED_OWNER, "USAGE", False),
        ("erp_app", EXPECTED_OWNER, "SELECT", False),
        ("erp_backup", EXPECTED_OWNER, "SELECT", False),
    ]
    complete_sequence_owner = _complete_owner_entries(PG16_SEQUENCE_OWNER_PRIVILEGES)
    assert (
        _exact_acl_drifts(
            owner=EXPECTED_OWNER,
            entries=good_sequence,
            required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
        )
        == []
    )
    assert (
        _exact_acl_drifts(
            owner=EXPECTED_OWNER,
            entries=complete_sequence_owner + good_sequence,
            required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
        )
        == []
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[
            (EXPECTED_OWNER, EXPECTED_OWNER, "SELECT", False),
            (EXPECTED_OWNER, EXPECTED_OWNER, "USAGE", False),
            *good_sequence,
        ],
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[*complete_sequence_owner, (EXPECTED_OWNER, EXPECTED_OWNER, "CREATE", False)]
        + good_sequence,
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=good_sequence + [("PUBLIC", EXPECTED_OWNER, "SELECT", False)],
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=good_sequence + [("w3_0028_third", EXPECTED_OWNER, "SELECT", False)],
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[
            ("erp_app", EXPECTED_OWNER, "USAGE", True),
            ("erp_app", EXPECTED_OWNER, "SELECT", False),
            ("erp_backup", EXPECTED_OWNER, "SELECT", False),
        ],
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[
            ("erp_app", "w3_0028_granter", "USAGE", False),
            ("erp_app", EXPECTED_OWNER, "SELECT", False),
            ("erp_backup", EXPECTED_OWNER, "SELECT", False),
        ],
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[("erp_owner", "w3_0028_granter", "SELECT", False), *good_sequence],
        required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
    )

    good_table = [
        ("erp_app", EXPECTED_OWNER, "SELECT", False),
        ("erp_app", EXPECTED_OWNER, "INSERT", False),
        ("erp_backup", EXPECTED_OWNER, "SELECT", False),
    ]
    assert (
        _exact_acl_drifts(
            owner=EXPECTED_OWNER,
            entries=_complete_owner_entries(PG16_TABLE_OWNER_PRIVILEGES) + good_table,
            required_non_owner=REQUIRED_TABLE_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_TABLE_OWNER_PRIVILEGES,
        )
        == []
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[
            (EXPECTED_OWNER, EXPECTED_OWNER, "SELECT", False),
            (EXPECTED_OWNER, EXPECTED_OWNER, "INSERT", False),
            *good_table,
        ],
        required_non_owner=REQUIRED_TABLE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_TABLE_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[
            ("erp_app", "w3_0028_table_granter", "SELECT", False),
            ("erp_app", EXPECTED_OWNER, "INSERT", False),
            ("erp_backup", EXPECTED_OWNER, "SELECT", False),
        ],
        required_non_owner=REQUIRED_TABLE_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_TABLE_OWNER_PRIVILEGES,
    )

    good_status_column = [("erp_app", EXPECTED_OWNER, "UPDATE", False)]
    assert (
        _exact_acl_drifts(
            owner=EXPECTED_OWNER,
            entries=good_status_column,
            required_non_owner=REQUIRED_STATUS_COLUMN_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_COLUMN_OWNER_PRIVILEGES,
        )
        == []
    )
    assert (
        _exact_acl_drifts(
            owner=EXPECTED_OWNER,
            entries=_complete_owner_entries(PG16_COLUMN_OWNER_PRIVILEGES) + good_status_column,
            required_non_owner=REQUIRED_STATUS_COLUMN_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_COLUMN_OWNER_PRIVILEGES,
        )
        == []
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[
            (EXPECTED_OWNER, EXPECTED_OWNER, "SELECT", False),
            (EXPECTED_OWNER, EXPECTED_OWNER, "UPDATE", False),
            *good_status_column,
        ],
        required_non_owner=REQUIRED_STATUS_COLUMN_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_COLUMN_OWNER_PRIVILEGES,
    )
    assert _exact_acl_drifts(
        owner=EXPECTED_OWNER,
        entries=[("erp_app", "w3_0028_column_granter", "UPDATE", False)],
        required_non_owner=REQUIRED_STATUS_COLUMN_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_COLUMN_OWNER_PRIVILEGES,
    )


def test_fake_catalog_rejects_sequence_and_schema_acl_drift() -> None:
    good_sequence = [
        ("erp_app", EXPECTED_OWNER, "USAGE", False),
        ("erp_app", EXPECTED_OWNER, "SELECT", False),
        ("erp_backup", EXPECTED_OWNER, "SELECT", False),
    ]

    _verify_identity_sequence_acl_entries(_FakeCatalogConnection(_sequence_acl_rows()))
    _verify_identity_sequence_acl_entries(
        _FakeCatalogConnection(
            _sequence_acl_rows(
                _complete_owner_entries(PG16_SEQUENCE_OWNER_PRIVILEGES) + good_sequence
            )
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_ACL_MISMATCH"):
        _verify_identity_sequence_acl_entries(
            _FakeCatalogConnection(
                _sequence_acl_rows(
                    [
                        (EXPECTED_OWNER, EXPECTED_OWNER, "SELECT", False),
                        (EXPECTED_OWNER, EXPECTED_OWNER, "USAGE", False),
                        *good_sequence,
                    ]
                )
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_ACL_MISMATCH"):
        _verify_identity_sequence_acl_entries(
            _FakeCatalogConnection(
                _sequence_acl_rows(good_sequence + [("PUBLIC", EXPECTED_OWNER, "SELECT", False)])
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_ACL_MISMATCH"):
        _verify_identity_sequence_acl_entries(
            _FakeCatalogConnection(
                _sequence_acl_rows(
                    [
                        ("erp_app", EXPECTED_OWNER, "USAGE", True),
                        ("erp_app", EXPECTED_OWNER, "SELECT", False),
                        ("erp_backup", EXPECTED_OWNER, "SELECT", False),
                    ]
                )
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_ACL_MISMATCH"):
        _verify_identity_sequence_acl_entries(
            _FakeCatalogConnection(_sequence_acl_rows(sequence_owner="erp_app"))
        )

    good_schema = [
        ("erp_app", EXPECTED_OWNER, "USAGE", False),
        ("erp_backup", EXPECTED_OWNER, "USAGE", False),
    ]
    assert (
        _exact_acl_drifts(
            owner=EXPECTED_OWNER,
            entries=good_schema,
            required_non_owner=REQUIRED_SCHEMA_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_SCHEMA_OWNER_PRIVILEGES,
        )
        == []
    )
    _verify_shared_schema_acl(_FakeCatalogConnection(_schema_acl_rows()))
    _verify_shared_schema_acl(
        _FakeCatalogConnection(
            _schema_acl_rows(_complete_owner_entries(PG16_SCHEMA_OWNER_PRIVILEGES) + good_schema)
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_ACL_MISMATCH"):
        _verify_shared_schema_acl(
            _FakeCatalogConnection(
                _schema_acl_rows(
                    [
                        (EXPECTED_OWNER, EXPECTED_OWNER, "USAGE", False),
                        *good_schema,
                    ]
                )
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_ACL_MISMATCH"):
        _verify_shared_schema_acl(
            _FakeCatalogConnection(
                _schema_acl_rows(good_schema + [("PUBLIC", EXPECTED_OWNER, "USAGE", False)])
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_ACL_MISMATCH"):
        _verify_shared_schema_acl(
            _FakeCatalogConnection(
                _schema_acl_rows(good_schema + [("w3_0028_third", EXPECTED_OWNER, "USAGE", False)])
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_ACL_MISMATCH"):
        _verify_shared_schema_acl(
            _FakeCatalogConnection(
                _schema_acl_rows(
                    [
                        ("erp_app", EXPECTED_OWNER, "USAGE", True),
                        ("erp_backup", EXPECTED_OWNER, "USAGE", False),
                    ]
                )
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_ACL_MISMATCH"):
        _verify_shared_schema_acl(
            _FakeCatalogConnection(
                _schema_acl_rows(
                    [
                        ("erp_app", "w3_0028_granter", "USAGE", False),
                        ("erp_backup", EXPECTED_OWNER, "USAGE", False),
                    ]
                )
            )
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_OWNER_MISMATCH"):
        _verify_shared_schema_acl(_FakeCatalogConnection(_schema_acl_rows(schema_owner="erp_app")))


def test_fake_catalog_rejects_deferrable_pk_hash_and_extra_indexes() -> None:
    _verify_primary_keys(_FakeCatalogConnection(_primary_key_rows()))
    deferrable = _primary_key_rows()
    for row in deferrable:
        if row["constraint_name"] == "pk_w3_source_row":
            row["condeferrable"] = True
    with pytest.raises(SystemExit, match="CURRENT_0028_PRIMARY_KEY_MISMATCH"):
        _verify_primary_keys(_FakeCatalogConnection(deferrable))

    deferred = _primary_key_rows()
    for row in deferred:
        if row["constraint_name"] == "pk_w3_source_row":
            row["condeferrable"] = True
            row["condeferred"] = True
    with pytest.raises(SystemExit, match="CURRENT_0028_PRIMARY_KEY_MISMATCH"):
        _verify_primary_keys(_FakeCatalogConnection(deferred))

    _verify_explicit_indexes(_FakeCatalogConnection(_explicit_index_rows()))
    hashed = _explicit_index_rows()
    for row in hashed:
        if row["index_name"] == "ix_w3_source_row_receipt_id":
            row["access_method"] = "hash"
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        _verify_explicit_indexes(_FakeCatalogConnection(hashed))

    extra_partial = _explicit_index_rows() + [
        {
            "index_name": "ix_w3_source_row_partial_hostile",
            "table_name": "erp.w3_source_row",
            "access_method": "btree",
            "relpersistence": "p",
            "indisunique": False,
            "indisvalid": True,
            "predicate": "source_row_number > 0",
            "key_items": ["receipt_id"],
            "include_columns": [],
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        _verify_explicit_indexes(_FakeCatalogConnection(extra_partial))

    extra_expression = _explicit_index_rows() + [
        {
            "index_name": "ix_w3_source_row_expr_hostile",
            "table_name": "erp.w3_source_row",
            "access_method": "btree",
            "relpersistence": "p",
            "indisunique": False,
            "indisvalid": True,
            "predicate": "",
            "key_items": ["lower(sheet_ref)"],
            "include_columns": [],
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        _verify_explicit_indexes(_FakeCatalogConnection(extra_expression))

    replaced_expression = _explicit_index_rows()
    for row in replaced_expression:
        if row["index_name"] == "ix_w3_source_row_receipt_id":
            row["key_items"] = ["lower(receipt_id::text)"]
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        _verify_explicit_indexes(_FakeCatalogConnection(replaced_expression))


def test_fake_catalog_rejects_table_relacl_grantor_and_partial_owner_sets() -> None:
    _verify_w3_table_relacl_entries(_FakeCatalogConnection(_table_acl_rows()))
    without_owner = [
        ("erp_app", EXPECTED_OWNER, "SELECT", False),
        ("erp_app", EXPECTED_OWNER, "INSERT", False),
        ("erp_backup", EXPECTED_OWNER, "SELECT", False),
    ]
    _verify_w3_table_relacl_entries(_FakeCatalogConnection(_table_acl_rows(without_owner)))

    partial_owner = [
        (EXPECTED_OWNER, EXPECTED_OWNER, "SELECT", False),
        (EXPECTED_OWNER, EXPECTED_OWNER, "INSERT", False),
        *without_owner,
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_RELACL_MISMATCH"):
        _verify_w3_table_relacl_entries(_FakeCatalogConnection(_table_acl_rows(partial_owner)))

    unexpected_grantor = [
        ("erp_app", "w3_0028_table_granter", "SELECT", False),
        ("erp_app", EXPECTED_OWNER, "INSERT", False),
        ("erp_backup", EXPECTED_OWNER, "SELECT", False),
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_RELACL_MISMATCH"):
        _verify_w3_table_relacl_entries(_FakeCatalogConnection(_table_acl_rows(unexpected_grantor)))

    with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_WIDE_UPDATE_PRESENT"):
        _verify_w3_table_relacl_entries(
            _FakeCatalogConnection(
                _table_acl_rows(
                    [
                        *without_owner,
                        ("erp_app", EXPECTED_OWNER, "UPDATE", False),
                    ]
                )
            )
        )


def test_fake_catalog_rejects_column_attacl_grantor_and_partial_owner_sets() -> None:
    _verify_w3_column_attacl_entries(_FakeCatalogConnection(_column_acl_rows()))
    _verify_w3_column_attacl_entries(_FakeCatalogConnection(_column_acl_rows(include_owner=True)))

    with pytest.raises(SystemExit, match="CURRENT_0028_UNEXPECTED_COLUMN_GRANT"):
        _verify_w3_column_attacl_entries(
            _FakeCatalogConnection(
                _column_acl_rows(replace_status_grantor="w3_0028_column_granter")
            )
        )

    partial_owner_status = _column_acl_rows(
        extra=[
            ("w3_source_snapshot", "status", EXPECTED_OWNER, EXPECTED_OWNER, "SELECT", False),
            ("w3_source_snapshot", "status", EXPECTED_OWNER, EXPECTED_OWNER, "UPDATE", False),
        ]
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_UNEXPECTED_COLUMN_GRANT"):
        _verify_w3_column_attacl_entries(_FakeCatalogConnection(partial_owner_status))

    unexpected_filename = _column_acl_rows(
        extra=[
            (
                "w3_source_receipt",
                "original_filename",
                "erp_app",
                EXPECTED_OWNER,
                "UPDATE",
                False,
            )
        ]
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_UNEXPECTED_COLUMN_GRANT"):
        _verify_w3_column_attacl_entries(_FakeCatalogConnection(unexpected_filename))


def _normalized_sql(source: str) -> str:
    return " ".join(source.split())


def test_acl_expansion_sql_is_null_attacl_safe_and_covers_null_columns() -> None:
    column_sql = _normalized_sql(inspect.getsource(_verify_w3_column_attacl_entries))
    table_sql = _normalized_sql(inspect.getsource(_verify_w3_table_relacl_entries))
    sequence_sql = _normalized_sql(inspect.getsource(_verify_identity_sequence_acl_entries))
    schema_sql = _normalized_sql(inspect.getsource(_verify_shared_schema_acl))
    assert "LEFT JOIN LATERAL aclexplode(attribute_row.attacl) AS acl ON true" in column_sql
    assert "LEFT JOIN LATERAL aclexplode(relation_row.relacl) AS acl ON true" in table_sql
    assert "LEFT JOIN LATERAL aclexplode(sequence_row.relacl) AS acl ON true" in sequence_sql
    assert "LEFT JOIN LATERAL aclexplode(namespace_row.nspacl) AS acl ON true" in schema_sql
    for source in (column_sql, table_sql, sequence_sql, schema_sql):
        assert "COALESCE(" not in source
        assert "'{}'::aclitem[]" not in source
        assert "ARRAY[]::aclitem[]" not in source
    assert "attribute_row.attacl IS NOT NULL" not in column_sql

    null_attacl_rows = _column_acl_rows()
    assert any(row["privilege_type"] is None for row in null_attacl_rows)
    null_columns = {
        (str(row["table_name"]), str(row["column_name"]))
        for row in null_attacl_rows
        if row["privilege_type"] is None
    }
    expected_columns = {
        (table_name, column_name)
        for table_name, columns in REQUIRED_COLUMNS.items()
        for column_name in columns
        if not expected_app_column_update(table_name, column_name)
    }
    assert null_columns == expected_columns

    captured = _CapturingCatalogConnection(null_attacl_rows)
    _verify_w3_column_attacl_entries(captured)
    issued = _normalized_sql(" ".join(captured.statements))
    assert "LEFT JOIN LATERAL aclexplode(attribute_row.attacl) AS acl ON true" in issued
    assert "COALESCE(" not in issued
    assert "'{}'::aclitem[]" not in issued
    assert "attribute_row.attacl IS NOT NULL" not in issued

    table_captured = _CapturingCatalogConnection(_table_acl_rows())
    _verify_w3_table_relacl_entries(table_captured)
    table_issued = _normalized_sql(" ".join(table_captured.statements))
    assert "LEFT JOIN LATERAL aclexplode(relation_row.relacl) AS acl ON true" in table_issued
    assert "COALESCE(" not in table_issued

    sequence_captured = _CapturingCatalogConnection(_sequence_acl_rows())
    _verify_identity_sequence_acl_entries(sequence_captured)
    sequence_issued = _normalized_sql(" ".join(sequence_captured.statements))
    assert "LEFT JOIN LATERAL aclexplode(sequence_row.relacl) AS acl ON true" in sequence_issued
    assert "COALESCE(" not in sequence_issued

    schema_captured = _CapturingCatalogConnection(_schema_acl_rows())
    _verify_shared_schema_acl(schema_captured)
    schema_issued = _normalized_sql(" ".join(schema_captured.statements))
    assert "LEFT JOIN LATERAL aclexplode(namespace_row.nspacl) AS acl ON true" in schema_issued
    assert "COALESCE(" not in schema_issued


def _role_attribute_rows() -> list[dict[str, Any]]:
    return [
        {"rolname": role_name, **EXPECTED_ROLE_ATTRIBUTES} for role_name in REQUIRED_RUNTIME_ROLES
    ]


def _role_routes(
    *,
    attributes: list[dict[str, Any]] | None = None,
    has_set: list[dict[str, Any]] | None = None,
    membership: list[dict[str, Any]] | None = None,
    raw_membership: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    return {
        "FROM pg_roles AS role_row": attributes
        if attributes is not None
        else _role_attribute_rows(),
        "pg_has_role(source_role.oid, target_role.oid, 'SET')": has_set
        if has_set is not None
        else [],
        "FROM pg_auth_members AS membership_row": membership if membership is not None else [],
        "FROM pg_auth_members AS raw_membership_row": (
            raw_membership if raw_membership is not None else []
        ),
    }


def _foreign_key_rows() -> list[dict[str, Any]]:
    return [
        {
            "conname": conname,
            "relation_name": table_name,
            "table_name": expected["table"],
            "referenced_table": expected["referenced_table"],
            "convalidated": True,
            "condeferrable": False,
            "condeferred": False,
            "confdeltype": "r",
            "confupdtype": "a",
            "confmatchtype": "s",
            "conislocal": True,
            "coninhcount": 0,
            "connoinherit": True,
            "conparentid": 0,
            "local_columns": list(expected["columns"]),
            "referenced_columns": list(expected["referenced_columns"]),
        }
        for (table_name, conname), expected in EXPECTED_FOREIGN_KEYS.items()
    ]


def _fk_trigger_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table_name, conname in EXPECTED_FOREIGN_KEYS:
        rows.extend(
            [
                {
                    "table_name": table_name,
                    "conname": conname,
                    "tgisinternal": True,
                    "tgenabled": "O",
                    "tg_on_local": True,
                    "tg_on_referenced": False,
                    "constrrel_is_referenced": True,
                    "constrrel_is_local": False,
                    "tgconstraint_matches": True,
                },
                {
                    "table_name": table_name,
                    "conname": conname,
                    "tgisinternal": True,
                    "tgenabled": "O",
                    "tg_on_local": True,
                    "tg_on_referenced": False,
                    "constrrel_is_referenced": True,
                    "constrrel_is_local": False,
                    "tgconstraint_matches": True,
                },
                {
                    "table_name": table_name,
                    "conname": conname,
                    "tgisinternal": True,
                    "tgenabled": "O",
                    "tg_on_local": False,
                    "tg_on_referenced": True,
                    "constrrel_is_referenced": False,
                    "constrrel_is_local": True,
                    "tgconstraint_matches": True,
                },
                {
                    "table_name": table_name,
                    "conname": conname,
                    "tgisinternal": True,
                    "tgenabled": "O",
                    "tg_on_local": False,
                    "tg_on_referenced": True,
                    "constrrel_is_referenced": False,
                    "constrrel_is_local": True,
                    "tgconstraint_matches": True,
                },
            ]
        )
    return rows


def _trigger_routes(
    *,
    origin: str = "origin",
    parameter_rows: list[dict[str, Any]] | None = None,
    role_defaults: list[dict[str, Any]] | None = None,
    setting_rows: list[dict[str, Any]] | None = None,
    trigger_rows: list[dict[str, Any]] | None = None,
    noninternal: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    if parameter_rows is None:
        parameter_rows = [
            {"role_name": "erp_app", "can_set": False},
            {"role_name": "erp_backup", "can_set": False},
            {"role_name": "public", "can_set": False},
        ]
    if role_defaults is None:
        role_defaults = [
            {"rolname": role_name, "rolconfig": None} for role_name in REQUIRED_RUNTIME_ROLES
        ]
    return {
        "SHOW session_replication_role": origin,
        "has_parameter_privilege(": parameter_rows,
        "SELECT role_row.rolname, role_row.rolconfig": role_defaults,
        "FROM pg_db_role_setting AS setting_row": setting_rows if setting_rows is not None else [],
        "LEFT JOIN pg_trigger AS trigger_row": trigger_rows
        if trigger_rows is not None
        else _fk_trigger_rows(),
        "AND NOT trigger_row.tgisinternal": noninternal if noninternal is not None else [],
    }


def _sequence_option_rows() -> list[dict[str, Any]]:
    return [
        {"sequence_name": name, **PG16_IDENTITY_SEQUENCE_OPTIONS}
        for name in sorted(EXPECTED_IDENTITY_SEQUENCES)
    ]


def _persistence_rows() -> list[dict[str, Any]]:
    return [
        {"relname": name, "relkind": kind, "relpersistence": "p"}
        for name, kind in sorted(EXPECTED_W3_RELATION_KINDS.items())
    ]


def _rls_table_rows() -> list[dict[str, Any]]:
    return [
        {
            "relname": table_name,
            "relrowsecurity": False,
            "relforcerowsecurity": False,
        }
        for table_name in sorted(REQUIRED_TABLES)
    ]


def test_fake_catalog_rejects_set_role_membership_and_unsafe_role_attributes() -> None:
    good = _RoutingCatalogConnection(_role_routes())
    _verify_runtime_roles(good)  # type: ignore[arg-type]
    issued = " ".join(good.statements)
    assert "pg_has_role(source_role.oid, target_role.oid, 'SET')" in issued
    assert "FROM pg_auth_members AS membership_row" in issued
    assert "membership_row.set_option" in issued
    assert "source_role.oid <>" in issued or "granted_role.oid <> member_role.oid" in issued
    assert "role_row.rolinherit" in issued
    assert "role_row.rolcanlogin" in issued
    assert "FROM pg_auth_members AS raw_membership_row" in issued
    assert "granted_role.rolname AS granted_role" in issued
    assert "member_role.rolname AS member_role" in issued
    assert "raw_membership_row.roleid" in issued
    assert "raw_membership_row.member" in issued
    raw_statements = [
        statement for statement in good.statements if "raw_membership_row" in statement
    ]
    assert len(raw_statements) == 1
    raw_sql = raw_statements[0]
    assert "raw_membership_row.set_option" in raw_sql
    assert "WHERE granted_role.rolname = ANY(:roles)" in raw_sql
    assert "OR member_role.rolname = ANY(:roles)" in raw_sql
    assert "AND raw_membership_row.set_option" not in raw_sql
    assert "AND membership_row.set_option" not in raw_sql
    assert "SET_ROLE_SOURCE_ROLES" not in raw_sql

    with pytest.raises(SystemExit, match="CURRENT_0028_FAKE_CATALOG_QUERY_MISMATCH"):
        _verify_runtime_roles(
            _RoutingCatalogConnection({"FROM pg_roles AS role_row": _role_attribute_rows()})  # type: ignore[arg-type]
        )

    superuser = _role_attribute_rows()
    for row in superuser:
        if row["rolname"] == "erp_app":
            row["rolsuper"] = True
    with pytest.raises(SystemExit, match="CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH"):
        _verify_runtime_roles(_RoutingCatalogConnection(_role_routes(attributes=superuser)))  # type: ignore[arg-type]

    nologin = _role_attribute_rows()
    for row in nologin:
        if row["rolname"] == "erp_owner":
            row["rolcanlogin"] = False
    with pytest.raises(SystemExit, match="CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH"):
        _verify_runtime_roles(_RoutingCatalogConnection(_role_routes(attributes=nologin)))  # type: ignore[arg-type]

    noinherit = _role_attribute_rows()
    for row in noinherit:
        if row["rolname"] == "erp_app":
            row["rolinherit"] = False
    with pytest.raises(SystemExit, match="CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH"):
        _verify_runtime_roles(_RoutingCatalogConnection(_role_routes(attributes=noinherit)))  # type: ignore[arg-type]

    missing = [row for row in _role_attribute_rows() if row["rolname"] != "erp_backup"]
    with pytest.raises(SystemExit, match="CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH"):
        _verify_runtime_roles(_RoutingCatalogConnection(_role_routes(attributes=missing)))  # type: ignore[arg-type]

    with pytest.raises(SystemExit, match="CURRENT_0028_SET_ROLE_PATH"):
        _verify_runtime_roles(
            _RoutingCatalogConnection(
                _role_routes(has_set=[{"source_role": "erp_app", "target_role": "erp_owner"}])
            )  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_SET_ROLE_PATH"):
        _verify_runtime_roles(
            _RoutingCatalogConnection(
                _role_routes(membership=[{"source_role": "erp_backup", "target_role": "erp_owner"}])
            )  # type: ignore[arg-type]
        )

    admin_set_false = [
        {
            "granted_role": "erp_owner",
            "member_role": "erp_app",
            "admin_option": True,
            "inherit_option": False,
            "set_option": False,
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_RAW_ROLE_MEMBERSHIP") as admin_caught:
        _verify_runtime_roles(
            _RoutingCatalogConnection(_role_routes(raw_membership=admin_set_false))  # type: ignore[arg-type]
        )
    assert "erp_owner" in str(admin_caught.value)
    assert "erp_app" in str(admin_caught.value)

    inherit_set_false = [
        {
            "granted_role": "erp_owner",
            "member_role": "erp_app",
            "admin_option": False,
            "inherit_option": True,
            "set_option": False,
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_RAW_ROLE_MEMBERSHIP"):
        _verify_runtime_roles(
            _RoutingCatalogConnection(_role_routes(raw_membership=inherit_set_false))  # type: ignore[arg-type]
        )

    reverse_edge = [
        {
            "granted_role": "auditor",
            "member_role": "erp_backup",
            "admin_option": False,
            "inherit_option": False,
            "set_option": False,
        }
    ]
    with pytest.raises(SystemExit, match="CURRENT_0028_RAW_ROLE_MEMBERSHIP") as reverse_caught:
        _verify_runtime_roles(
            _RoutingCatalogConnection(_role_routes(raw_membership=reverse_edge))  # type: ignore[arg-type]
        )
    assert "auditor" in str(reverse_caught.value)
    assert "erp_backup" in str(reverse_caught.value)


def test_fake_catalog_rejects_fk_inventory_collision_and_canonical_metadata() -> None:
    _verify_foreign_keys(_FakeCatalogConnection(_foreign_key_rows()))

    second = dict(_foreign_key_rows()[0])
    second["relation_name"] = "w3_source_row"
    second["table_name"] = "erp.w3_source_row"
    collision = _foreign_key_rows() + [second]
    with pytest.raises(SystemExit, match="CURRENT_0028_FOREIGN_KEY_MISMATCH"):
        _verify_foreign_keys(_FakeCatalogConnection(collision))

    duplicate = _foreign_key_rows()
    duplicate.append(dict(duplicate[0]))
    with pytest.raises(SystemExit, match="CURRENT_0028_FOREIGN_KEY_DUPLICATE"):
        _verify_foreign_keys(_FakeCatalogConnection(duplicate))

    match_full = _foreign_key_rows()
    match_full[0]["confmatchtype"] = "f"
    with pytest.raises(SystemExit, match="CURRENT_0028_FOREIGN_KEY_MISMATCH"):
        _verify_foreign_keys(_FakeCatalogConnection(match_full))

    topology = _foreign_key_rows()
    topology[0]["referenced_table"] = "erp.w3_source_row"
    with pytest.raises(SystemExit, match="CURRENT_0028_FOREIGN_KEY_MISMATCH"):
        _verify_foreign_keys(_FakeCatalogConnection(topology))

    inherited = _foreign_key_rows()
    inherited[0]["conislocal"] = False
    inherited[0]["coninhcount"] = 1
    inherited[0]["connoinherit"] = False
    inherited[0]["conparentid"] = 17
    with pytest.raises(SystemExit, match="CURRENT_0028_FOREIGN_KEY_MISMATCH"):
        _verify_foreign_keys(_FakeCatalogConnection(inherited))

    captured = _CapturingCatalogConnection(_foreign_key_rows())
    _verify_foreign_keys(captured)
    issued = " ".join(captured.statements)
    assert "constraint_row.confmatchtype" in issued
    assert "constraint_row.conislocal" in issued
    assert "constraint_row.conparentid" in issued
    assert "local_relation.relname AS relation_name" in issued


def test_fake_catalog_rejects_trigger_replication_rls_and_sequence_drift() -> None:
    good_triggers = _RoutingCatalogConnection(_trigger_routes())
    _verify_fk_triggers_and_replication(good_triggers)  # type: ignore[arg-type]
    issued = " ".join(good_triggers.statements)
    assert "SHOW session_replication_role" in issued
    assert "has_parameter_privilege(" in issued
    assert "LEFT JOIN pg_trigger AS trigger_row" in issued
    assert "AND NOT trigger_row.tgisinternal" in issued
    assert "indisready" not in issued
    assert "indislive" not in issued

    with pytest.raises(SystemExit, match="CURRENT_0028_FAKE_CATALOG_QUERY_MISMATCH"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection({"SHOW session_replication_role": "origin"})  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_REPLICATION_ROLE_MISMATCH"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection(_trigger_routes(origin="replica"))  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_REPLICATION_PARAMETER_SET"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection(
                _trigger_routes(
                    parameter_rows=[
                        {"role_name": "erp_app", "can_set": True},
                        {"role_name": "erp_backup", "can_set": False},
                        {"role_name": "public", "can_set": False},
                    ]
                )
            )  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_REPLICATION_DEFAULT"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection(
                _trigger_routes(
                    role_defaults=[
                        {"rolname": "erp_app", "rolconfig": ["session_replication_role=replica"]},
                        {"rolname": "erp_owner", "rolconfig": None},
                        {"rolname": "erp_backup", "rolconfig": None},
                    ]
                )
            )  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_REPLICATION_DEFAULT"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection(
                _trigger_routes(
                    setting_rows=[
                        {
                            "database_name": "sswcenter_w3_0028_live_test",
                            "role_name": "",
                            "setconfig": ["session_replication_role=replica"],
                        }
                    ]
                )
            )  # type: ignore[arg-type]
        )

    disabled = _fk_trigger_rows()
    disabled[0]["tgenabled"] = "D"
    with pytest.raises(SystemExit, match="CURRENT_0028_FK_TRIGGER_MISMATCH"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection(_trigger_routes(trigger_rows=disabled))  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_NONINTERNAL_TRIGGER_PRESENT"):
        _verify_fk_triggers_and_replication(
            _RoutingCatalogConnection(
                _trigger_routes(
                    noninternal=[{"table_name": "w3_source_row", "tgname": "w3_hostile_audit"}]
                )
            )  # type: ignore[arg-type]
        )

    _verify_relation_persistence(_FakeCatalogConnection(_persistence_rows()))
    unlogged = _persistence_rows()
    for row in unlogged:
        if row["relname"] == "w3_import_attempt":
            row["relpersistence"] = "u"
    with pytest.raises(SystemExit, match="CURRENT_0028_PERSISTENCE_MISMATCH"):
        _verify_relation_persistence(_FakeCatalogConnection(unlogged))

    _verify_identity_sequence_options(_FakeCatalogConnection(_sequence_option_rows()))
    captured_sequences = _CapturingCatalogConnection(_sequence_option_rows())
    _verify_identity_sequence_options(captured_sequences)
    sequence_sql = " ".join(captured_sequences.statements)
    assert "FROM pg_sequence AS sequence_row" in sequence_sql
    assert "last_value" not in sequence_sql
    mutated = _sequence_option_rows()
    mutated[0]["seqincrement"] = 2
    mutated[0]["seqcycle"] = True
    with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_OPTION_MISMATCH"):
        _verify_identity_sequence_options(_FakeCatalogConnection(mutated))

    rls_routes = {
        "relrowsecurity": _rls_table_rows(),
        "FROM pg_policy AS policy_row": [],
    }
    _verify_rls_absent(_RoutingCatalogConnection(rls_routes))  # type: ignore[arg-type]
    with pytest.raises(SystemExit, match="CURRENT_0028_FAKE_CATALOG_QUERY_MISMATCH"):
        _verify_rls_absent(_RoutingCatalogConnection({"relrowsecurity": _rls_table_rows()}))  # type: ignore[arg-type]
    enabled = _rls_table_rows()
    enabled[0]["relrowsecurity"] = True
    with pytest.raises(SystemExit, match="CURRENT_0028_RLS_PRESENT"):
        _verify_rls_absent(
            _RoutingCatalogConnection(
                {"relrowsecurity": enabled, "FROM pg_policy AS policy_row": []}
            )  # type: ignore[arg-type]
        )
    with pytest.raises(SystemExit, match="CURRENT_0028_RLS_PRESENT"):
        _verify_rls_absent(
            _RoutingCatalogConnection(
                {
                    "relrowsecurity": _rls_table_rows(),
                    "FROM pg_policy AS policy_row": [
                        {"table_name": "w3_source_row", "polname": "w3_deny_all"}
                    ],
                }
            )  # type: ignore[arg-type]
        )


def test_verify_current_0028_wires_new_fail_closed_verifiers_once() -> None:
    source = inspect.getsource(verify_current_0028)
    trigger_source = inspect.getsource(_verify_fk_triggers_and_replication)
    rls_source = inspect.getsource(_verify_rls_absent)
    for name in (
        "_verify_session_replication_origin",
        "_verify_runtime_roles",
        "_verify_fk_triggers_and_replication",
        "_verify_relation_persistence",
        "_verify_identity_sequence_options",
        "_verify_rls_absent",
    ):
        assert source.count(name) == 1
    assert "NOT trigger_row.tgisinternal" in trigger_source
    assert "LEFT JOIN pg_trigger AS trigger_row" in trigger_source
    assert "pg_trigger" not in rls_source
    assert "indisready" not in source
    assert "indislive" not in source
    postcheck_source = POSTCHECK_0028.read_text(encoding="utf-8")
    assert "datconfig" not in postcheck_source
    assert "pg_db_role_setting" in postcheck_source
    assert source.index("_verify_session_replication_origin") < source.index("verify_current_0027")
    assert source.index("_verify_runtime_roles") < source.index("verify_current_0027")


def test_w3_namespace_like_predicate_is_literal_underscore() -> None:
    postcheck_source = POSTCHECK_0028.read_text(encoding="utf-8")
    tables_source = inspect.getsource(_verify_tables)
    bytea_source = inspect.getsource(_verify_no_bytea)
    assert W3_NAMESPACE_LIKE_SQL == "LIKE 'w3\\_%' ESCAPE '\\'"
    assert "W3_NAMESPACE_LIKE_SQL" in tables_source
    assert "W3_NAMESPACE_LIKE_SQL" in bytea_source
    assert 'W3_NAMESPACE_LIKE_SQL = "LIKE' in postcheck_source
    assert "w3\\\\_%" in postcheck_source
    assert "ESCAPE '\\\\'" in postcheck_source
    assert "LIKE 'w3_%'" not in postcheck_source
    assert "LIKE 'w3_%'" not in tables_source
    assert "LIKE 'w3_%'" not in bytea_source
    assert "information_schema.columns" in bytea_source


def test_w3_0028_harness_live_nodes_match_postgres_test_order() -> None:
    postgres_path = REPO_ROOT / "backend" / "tests" / "test_w3_0028_postgres.py"
    harness_path = REPO_ROOT / "scripts" / "test-w3-0028-postgres-linux.ps1"
    postgres_source = postgres_path.read_text(encoding="utf-8")
    harness_source = harness_path.read_text(encoding="utf-8")
    names = [
        node.name
        for node in ast.parse(postgres_source).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    node_ids = re.findall(
        r"tests/test_w3_0028_postgres\.py::(test_w3_0028_pg_[A-Za-z0-9_]+)",
        harness_source,
    )
    assert node_ids == names
    assert "LIKE 'w3\\_%' ESCAPE '\\'" in harness_source
    assert "LIKE 'w3_%'" not in harness_source
