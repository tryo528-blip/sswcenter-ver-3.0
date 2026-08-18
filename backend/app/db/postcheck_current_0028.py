"""Fail-closed current-head postcheck for the 0028 W3 source-intake foundation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict, cast

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.core.settings import get_settings
from app.db.postcheck_current_0026 import (
    ERP_APP_READ_ONLY_PRIVILEGES,
    ERP_APP_SEQUENCE_PRIVILEGES,
    ERP_BACKUP_SEQUENCE_PRIVILEGES,
    _compact_constraint,
    _privileges,
    _scan_quoted,
    _sequence_privileges,
    _strip_harmless_display_casts,
)
from app.db.postcheck_current_0027 import verify_current_0027
from app.db.session import create_postgres_engine

EXPECTED_REVISION = "20260817_0028_w3_source_intake_foundation"
W3_0028_REVISION = EXPECTED_REVISION
CURRENT_0028_MARKER = "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK"
HEAD_MARKER = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"
STATUS_UPDATE_COLUMN = "status"

REQUIRED_TABLES = {
    "w3_private_content",
    "w3_source_receipt",
    "w3_source_snapshot",
    "w3_import_run",
    "w3_import_attempt",
    "w3_source_row",
}

# Receipts, attempts, private content, and raw rows are facts. Snapshot and run
# projections may change only the status column; table-wide UPDATE stays revoked.
IMMUTABLE_TABLES = {
    "w3_private_content",
    "w3_source_receipt",
    "w3_import_attempt",
    "w3_source_row",
}

MUTABLE_LINEAGE_TABLES = {
    "w3_source_snapshot",
    "w3_import_run",
}

FORBIDDEN_GENERIC_COLUMNS = {
    "target_type",
    "target_id",
    "content_bytes",
    "public_url",
}

EXPECTED_OWNER = "erp_owner"
# PG16 implicit owner privileges. Catalog may omit owner rows or materialize
# this complete set; a partial or surplus owner set is drift.
PG16_SEQUENCE_OWNER_PRIVILEGES: frozenset[str] = frozenset({"SELECT", "UPDATE", "USAGE"})
PG16_SCHEMA_OWNER_PRIVILEGES: frozenset[str] = frozenset({"CREATE", "USAGE"})
PG16_TABLE_OWNER_PRIVILEGES: frozenset[str] = frozenset(
    {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"}
)
PG16_COLUMN_OWNER_PRIVILEGES: frozenset[str] = frozenset(
    {"SELECT", "INSERT", "UPDATE", "REFERENCES"}
)
REQUIRED_SEQUENCE_NON_OWNER_ACL: dict[str, set[tuple[str, bool]]] = {
    "erp_app": {("SELECT", False), ("USAGE", False)},
    "erp_backup": {("SELECT", False)},
}
REQUIRED_SCHEMA_NON_OWNER_ACL: dict[str, set[tuple[str, bool]]] = {
    "erp_app": {("USAGE", False)},
    "erp_backup": {("USAGE", False)},
}
REQUIRED_TABLE_NON_OWNER_ACL: dict[str, set[tuple[str, bool]]] = {
    "erp_app": {("SELECT", False), ("INSERT", False)},
    "erp_backup": {("SELECT", False)},
}
REQUIRED_STATUS_COLUMN_NON_OWNER_ACL: dict[str, set[tuple[str, bool]]] = {
    "erp_app": {("UPDATE", False)},
}


class ColumnSpec(TypedDict):
    type: str
    nullable: bool
    default: str | None
    identity: str


class ExplicitIndexSpec(TypedDict):
    table: str
    access_method: str
    columns: tuple[str, ...]
    include: tuple[str, ...]
    unique: bool
    predicate: str


# PG16 format_type / pg_get_expr / attidentity contract. Defaults store the
# canonical `now()` form; display-only casts are stripped before compare.
EXPECTED_COLUMN_CATALOG: dict[str, dict[str, ColumnSpec]] = {
    "w3_private_content": {
        "id": {"type": "bigint", "nullable": False, "default": None, "identity": "d"},
        "content_digest": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "byte_size": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "media_type": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "storage_locator": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "quarantine_state": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "legal_hold_state": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "automatic_gc_enabled": {
            "type": "boolean",
            "nullable": False,
            "default": None,
            "identity": "",
        },
        "created_at_utc": {
            "type": "timestamp with time zone",
            "nullable": False,
            "default": "now()",
            "identity": "",
        },
    },
    "w3_source_snapshot": {
        "id": {"type": "bigint", "nullable": False, "default": None, "identity": "d"},
        "content_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "source_type": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "target_date": {"type": "date", "nullable": False, "default": None, "identity": ""},
        "content_digest": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "status": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "created_at_utc": {
            "type": "timestamp with time zone",
            "nullable": False,
            "default": "now()",
            "identity": "",
        },
    },
    "w3_source_receipt": {
        "id": {"type": "bigint", "nullable": False, "default": None, "identity": "d"},
        "snapshot_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "content_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "content_digest": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "original_filename": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "actor_type": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "actor_account_id": {"type": "bigint", "nullable": True, "default": None, "identity": ""},
        "source_context_type": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "received_at_utc": {
            "type": "timestamp with time zone",
            "nullable": False,
            "default": "now()",
            "identity": "",
        },
    },
    "w3_import_run": {
        "id": {"type": "bigint", "nullable": False, "default": None, "identity": "d"},
        "receipt_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "snapshot_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "content_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "content_digest": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "parser_profile_version": {
            "type": "text",
            "nullable": False,
            "default": None,
            "identity": "",
        },
        "status": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "apply_idempotency_key": {
            "type": "text",
            "nullable": False,
            "default": None,
            "identity": "",
        },
        "created_at_utc": {
            "type": "timestamp with time zone",
            "nullable": False,
            "default": "now()",
            "identity": "",
        },
    },
    "w3_import_attempt": {
        "id": {"type": "bigint", "nullable": False, "default": None, "identity": "d"},
        "receipt_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "import_run_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "snapshot_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "content_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "content_digest": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "attempt_ordinal": {"type": "integer", "nullable": False, "default": None, "identity": ""},
        "status": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "recorded_at_utc": {
            "type": "timestamp with time zone",
            "nullable": False,
            "default": "now()",
            "identity": "",
        },
    },
    "w3_source_row": {
        "id": {"type": "bigint", "nullable": False, "default": None, "identity": "d"},
        "receipt_id": {"type": "bigint", "nullable": False, "default": None, "identity": ""},
        "sheet_ref": {"type": "text", "nullable": False, "default": None, "identity": ""},
        "source_row_number": {
            "type": "integer",
            "nullable": False,
            "default": None,
            "identity": "",
        },
        "created_at_utc": {
            "type": "timestamp with time zone",
            "nullable": False,
            "default": "now()",
            "identity": "",
        },
    },
}

REQUIRED_COLUMNS: dict[str, dict[str, bool]] = {
    table_name: {column_name: spec["nullable"] for column_name, spec in columns.items()}
    for table_name, columns in EXPECTED_COLUMN_CATALOG.items()
}

# Keyed by (table, constraint name). A moved same-name CHECK is not the contract.
EXPECTED_CHECKS: dict[tuple[str, str], str] = {
    ("w3_private_content", "ck_w3_private_content_digest_sha256"): (
        "CHECK (content_digest ~ '^[0-9a-f]{64}$')"
    ),
    ("w3_private_content", "ck_w3_private_content_byte_size"): "CHECK (byte_size >= 0)",
    ("w3_private_content", "ck_w3_private_content_media_type"): ("CHECK (btrim(media_type) <> '')"),
    ("w3_private_content", "ck_w3_private_content_storage_locator"): (
        "CHECK (storage_locator ~ '^w3-private:[0-9a-f]{32,}$' "
        "AND storage_locator !~~ 'http%' "
        "AND position(('://') in (storage_locator)) = 0)"
    ),
    ("w3_private_content", "ck_w3_private_content_quarantine_state"): (
        "CHECK (quarantine_state = ANY (ARRAY['NONE', 'QUARANTINED']))"
    ),
    ("w3_private_content", "ck_w3_private_content_legal_hold_state"): (
        "CHECK (legal_hold_state = ANY (ARRAY['NONE', 'HELD']))"
    ),
    ("w3_private_content", "ck_w3_private_content_automatic_gc_off"): (
        "CHECK (automatic_gc_enabled IS FALSE)"
    ),
    ("w3_source_snapshot", "ck_w3_source_snapshot_source_type"): (
        "CHECK (source_type = ANY (ARRAY['RFID', 'NHIS_SCHEDULE']))"
    ),
    ("w3_source_snapshot", "ck_w3_source_snapshot_status"): (
        "CHECK (status = ANY (ARRAY['CANDIDATE', 'ACTIVE', 'SUPERSEDED']))"
    ),
    ("w3_source_receipt", "ck_w3_source_receipt_filename"): (
        "CHECK (btrim(original_filename) <> '')"
    ),
    ("w3_source_receipt", "ck_w3_source_receipt_actor_type"): (
        "CHECK (actor_type = ANY (ARRAY['USER_ACCOUNT', 'SYSTEM_RUN']))"
    ),
    ("w3_source_receipt", "ck_w3_source_receipt_actor_pair"): (
        "CHECK ((actor_type = 'USER_ACCOUNT' AND actor_account_id IS NOT NULL) "
        "OR (actor_type = 'SYSTEM_RUN' AND actor_account_id IS NULL))"
    ),
    ("w3_source_receipt", "ck_w3_source_receipt_source_context_type"): (
        "CHECK (source_context_type = ANY (ARRAY['RFID_FILE', 'NHIS_SCHEDULE_FILE']))"
    ),
    ("w3_import_run", "ck_w3_import_run_parser_profile_version"): (
        "CHECK (btrim(parser_profile_version) <> '')"
    ),
    ("w3_import_run", "ck_w3_import_run_status"): (
        "CHECK (status = ANY (ARRAY['RECEIVED', 'PARSING', 'PREVIEW_READY', "
        "'CONFIRMED', 'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED']))"
    ),
    ("w3_import_run", "ck_w3_import_run_apply_idempotency_key"): (
        "CHECK (btrim(apply_idempotency_key) <> '')"
    ),
    ("w3_import_attempt", "ck_w3_import_attempt_ordinal"): "CHECK (attempt_ordinal > 0)",
    ("w3_import_attempt", "ck_w3_import_attempt_status"): (
        "CHECK (status = ANY (ARRAY['SUCCEEDED', 'FAILED_RETRYABLE', 'BLOCKED']))"
    ),
    ("w3_source_row", "ck_w3_source_row_sheet_ref"): (
        "CHECK (btrim(sheet_ref) <> '' AND position(('://') in (sheet_ref)) = 0)"
    ),
    ("w3_source_row", "ck_w3_source_row_number"): "CHECK (source_row_number > 0)",
}

EXPECTED_UNIQUES = {
    "uq_w3_private_content_content_digest": (
        "erp.w3_private_content",
        ("content_digest",),
    ),
    "uq_w3_private_content_id_digest": (
        "erp.w3_private_content",
        ("id", "content_digest"),
    ),
    "uq_w3_source_snapshot_identity": (
        "erp.w3_source_snapshot",
        ("source_type", "target_date", "content_digest"),
    ),
    "uq_w3_source_snapshot_content_identity": (
        "erp.w3_source_snapshot",
        ("id", "content_id", "content_digest"),
    ),
    "uq_w3_source_receipt_lineage": (
        "erp.w3_source_receipt",
        ("id", "snapshot_id", "content_id", "content_digest"),
    ),
    "uq_w3_import_run_snapshot_profile": (
        "erp.w3_import_run",
        ("snapshot_id", "parser_profile_version"),
    ),
    "uq_w3_import_run_apply_idempotency_key": (
        "erp.w3_import_run",
        ("apply_idempotency_key",),
    ),
    "uq_w3_import_run_lineage": (
        "erp.w3_import_run",
        ("id", "snapshot_id", "content_id", "content_digest"),
    ),
    "uq_w3_import_attempt_ordinal": (
        "erp.w3_import_attempt",
        ("import_run_id", "attempt_ordinal"),
    ),
    "uq_w3_source_row_physical_address": (
        "erp.w3_source_row",
        ("receipt_id", "sheet_ref", "source_row_number"),
    ),
}

ACTIVE_PARTIAL_UNIQUE = (
    "uq_w3_source_snapshot_one_active_per_source_date",
    "erp.w3_source_snapshot",
    ("source_type", "target_date"),
    "status = 'ACTIVE'",
)

EXPECTED_PRIMARY_KEYS = {
    "pk_w3_private_content": ("erp.w3_private_content", ("id",)),
    "pk_w3_source_snapshot": ("erp.w3_source_snapshot", ("id",)),
    "pk_w3_source_receipt": ("erp.w3_source_receipt", ("id",)),
    "pk_w3_import_run": ("erp.w3_import_run", ("id",)),
    "pk_w3_import_attempt": ("erp.w3_import_attempt", ("id",)),
    "pk_w3_source_row": ("erp.w3_source_row", ("id",)),
}

EXPECTED_EXPLICIT_INDEXES: dict[str, ExplicitIndexSpec] = {
    "ix_w3_source_receipt_content_id": {
        "table": "erp.w3_source_receipt",
        "access_method": "btree",
        "columns": ("content_id",),
        "include": (),
        "unique": False,
        "predicate": "",
    },
    "ix_w3_import_run_snapshot_id": {
        "table": "erp.w3_import_run",
        "access_method": "btree",
        "columns": ("snapshot_id",),
        "include": (),
        "unique": False,
        "predicate": "",
    },
    "ix_w3_import_attempt_import_run_id": {
        "table": "erp.w3_import_attempt",
        "access_method": "btree",
        "columns": ("import_run_id",),
        "include": (),
        "unique": False,
        "predicate": "",
    },
    "ix_w3_source_row_receipt_id": {
        "table": "erp.w3_source_row",
        "access_method": "btree",
        "columns": ("receipt_id",),
        "include": (),
        "unique": False,
        "predicate": "",
    },
}

EXPECTED_NON_CONSTRAINT_INDEXES: dict[str, ExplicitIndexSpec] = {
    **EXPECTED_EXPLICIT_INDEXES,
    ACTIVE_PARTIAL_UNIQUE[0]: {
        "table": ACTIVE_PARTIAL_UNIQUE[1],
        "access_method": "btree",
        "columns": ACTIVE_PARTIAL_UNIQUE[2],
        "include": (),
        "unique": True,
        "predicate": ACTIVE_PARTIAL_UNIQUE[3],
    },
}

EXPECTED_FOREIGN_KEYS = {
    ("w3_source_snapshot", "fk_w3_source_snapshot_content_identity"): {
        "table": "erp.w3_source_snapshot",
        "columns": ("content_id", "content_digest"),
        "referenced_table": "erp.w3_private_content",
        "referenced_columns": ("id", "content_digest"),
    },
    ("w3_source_receipt", "fk_w3_source_receipt_content_identity"): {
        "table": "erp.w3_source_receipt",
        "columns": ("content_id", "content_digest"),
        "referenced_table": "erp.w3_private_content",
        "referenced_columns": ("id", "content_digest"),
    },
    ("w3_source_receipt", "fk_w3_source_receipt_snapshot_identity"): {
        "table": "erp.w3_source_receipt",
        "columns": ("snapshot_id", "content_id", "content_digest"),
        "referenced_table": "erp.w3_source_snapshot",
        "referenced_columns": ("id", "content_id", "content_digest"),
    },
    ("w3_source_receipt", "fk_w3_source_receipt_actor_account"): {
        "table": "erp.w3_source_receipt",
        "columns": ("actor_account_id",),
        "referenced_table": "erp.user_account",
        "referenced_columns": ("id",),
    },
    ("w3_import_run", "fk_w3_import_run_receipt_lineage"): {
        "table": "erp.w3_import_run",
        "columns": ("receipt_id", "snapshot_id", "content_id", "content_digest"),
        "referenced_table": "erp.w3_source_receipt",
        "referenced_columns": ("id", "snapshot_id", "content_id", "content_digest"),
    },
    ("w3_import_run", "fk_w3_import_run_snapshot_identity"): {
        "table": "erp.w3_import_run",
        "columns": ("snapshot_id", "content_id", "content_digest"),
        "referenced_table": "erp.w3_source_snapshot",
        "referenced_columns": ("id", "content_id", "content_digest"),
    },
    ("w3_import_attempt", "fk_w3_import_attempt_receipt_lineage"): {
        "table": "erp.w3_import_attempt",
        "columns": ("receipt_id", "snapshot_id", "content_id", "content_digest"),
        "referenced_table": "erp.w3_source_receipt",
        "referenced_columns": ("id", "snapshot_id", "content_id", "content_digest"),
    },
    ("w3_import_attempt", "fk_w3_import_attempt_run_lineage"): {
        "table": "erp.w3_import_attempt",
        "columns": ("import_run_id", "snapshot_id", "content_id", "content_digest"),
        "referenced_table": "erp.w3_import_run",
        "referenced_columns": ("id", "snapshot_id", "content_id", "content_digest"),
    },
    ("w3_import_attempt", "fk_w3_import_attempt_snapshot_identity"): {
        "table": "erp.w3_import_attempt",
        "columns": ("snapshot_id", "content_id", "content_digest"),
        "referenced_table": "erp.w3_source_snapshot",
        "referenced_columns": ("id", "content_id", "content_digest"),
    },
    ("w3_source_row", "fk_w3_source_row_receipt"): {
        "table": "erp.w3_source_row",
        "columns": ("receipt_id",),
        "referenced_table": "erp.w3_source_receipt",
        "referenced_columns": ("id",),
    },
}

ERP_APP_APPEND_ONLY_PRIVILEGES = (
    True,  # SELECT
    True,  # INSERT
    False,  # UPDATE
    False,  # DELETE
    False,  # TRUNCATE
    False,  # REFERENCES
    False,  # TRIGGER
    False,  # SELECT WITH GRANT OPTION
    False,  # INSERT WITH GRANT OPTION
    False,  # UPDATE WITH GRANT OPTION
)

_SEQUENCE_TABLES = tuple(sorted(REQUIRED_TABLES))
EXPECTED_IDENTITY_SEQUENCES = {f"{table_name}_id_seq" for table_name in REQUIRED_TABLES}
EXPECTED_W3_RELATION_KINDS: dict[str, str] = {
    **{table_name: "r" for table_name in REQUIRED_TABLES},
    **{sequence_name: "S" for sequence_name in EXPECTED_IDENTITY_SEQUENCES},
}
REQUIRED_RUNTIME_ROLES = ("erp_owner", "erp_app", "erp_backup")
SET_ROLE_SOURCE_ROLES = ("erp_app", "erp_backup")
EXPECTED_ROLE_ATTRIBUTES = {
    "rolsuper": False,
    "rolcreaterole": False,
    "rolcreatedb": False,
    "rolreplication": False,
    "rolbypassrls": False,
    "rolcanlogin": True,
    "rolinherit": True,
}
# Escape the underscore so w3X... names stay outside the W3 inventory.
W3_NAMESPACE_LIKE_SQL = "LIKE 'w3\\_%' ESCAPE '\\'"
PG16_ORDINARY_FK_TRIGGER_COUNT = 4
PG16_IDENTITY_SEQUENCE_OPTIONS = {
    "seqtypid": 20,
    "seqstart": 1,
    "seqincrement": 1,
    "seqmin": 1,
    "seqmax": 9223372036854775807,
    "seqcache": 1,
    "seqcycle": False,
}
PG16_ORDINARY_LOCAL_FK_METADATA = {
    "match_type": "s",
    "is_local": True,
    "inherit_count": 0,
    "no_inherit": True,
    "parent_oid": 0,
}


def _as_names(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _index_key_items(values: Iterable[object]) -> tuple[str, ...]:
    items: list[str] = []
    for value in values:
        item = str(value)
        if len(item) >= 2 and item[0] == '"' and item[-1] == '"':
            item = item[1:-1].replace('""', '"')
        items.append(item)
    return tuple(items)


def required_column_non_owner_acl(
    table_name: str, column_name: str
) -> dict[str, set[tuple[str, bool]]]:
    if expected_app_column_update(table_name, column_name):
        return REQUIRED_STATUS_COLUMN_NON_OWNER_ACL
    return {}


def _exact_acl_drifts(
    *,
    owner: str,
    entries: Iterable[tuple[str, str, str, bool]],
    required_non_owner: dict[str, set[tuple[str, bool]]],
    owner_canonical_privileges: frozenset[str],
) -> list[str]:
    """Fail-closed raw ACL: owner absent or exact PG16 owner set; non-owner allowlist."""

    drifts: list[str] = []
    seen: dict[str, set[tuple[str, bool]]] = {}
    owner_pairs: set[tuple[str, bool]] = set()
    owner_seen = False
    for grantee, grantor, privilege, grantable in entries:
        grantee_name = grantee if grantee else "PUBLIC"
        grantor_name = grantor if grantor else "UNKNOWN"
        if grantee_name == owner:
            owner_seen = True
            if grantor_name != owner:
                drifts.append(
                    f"owner_grantor={grantor_name}:grantee={grantee_name}:"
                    f"privilege={privilege}:grantable={grantable}"
                )
            if grantable:
                drifts.append(
                    f"owner_grantable={grantee_name}:privilege={privilege}:grantable={grantable}"
                )
            owner_pairs.add((privilege, grantable))
            continue
        if grantor_name != owner:
            drifts.append(
                f"unexpected_grantor={grantor_name}:grantee={grantee_name}:"
                f"privilege={privilege}:grantable={grantable}"
            )
        seen.setdefault(grantee_name, set()).add((privilege, grantable))

    if owner_seen:
        expected_owner = {(privilege, False) for privilege in owner_canonical_privileges}
        if owner_pairs != expected_owner:
            drifts.append(
                "owner_privileges:"
                f"expected={sorted(expected_owner)!r}:actual={sorted(owner_pairs)!r}"
            )

    for grantee_name, privileges in seen.items():
        expected = required_non_owner.get(grantee_name)
        if expected is None:
            drifts.append(f"unexpected_grantee={grantee_name}:privileges={sorted(privileges)!r}")
        elif privileges != expected:
            drifts.append(
                f"grantee={grantee_name}:expected={sorted(expected)!r}"
                f":actual={sorted(privileges)!r}"
            )
    for role_name, expected in required_non_owner.items():
        if role_name not in seen:
            drifts.append(f"missing_grantee={role_name}:expected={sorted(expected)!r}")
    return drifts


def _fold_unquoted_sql_case(definition: str) -> str:
    """Lowercase unquoted SQL text; keep quoted literal and identifier bytes."""

    output: list[str] = []
    index = 0
    length = len(definition)
    while index < length:
        character = definition[index]
        if character in ("'", '"'):
            end = _scan_quoted(definition, index, character)
            output.append(definition[index:end])
            index = end
            continue
        output.append(character.lower())
        index += 1
    return "".join(output)


def _canonical_check_definition(definition: str) -> str:
    """Compare exact CHECK logic while ignoring PG16 display-only casts/space."""

    # Strip display-only ``::text`` while keyword boundaries and spaces are
    # still present.  ``_compact_constraint`` first removes whitespace, which
    # would otherwise turn ``::text AND`` into the apparent type name
    # ``textAND`` on the regex-operator fallback path.  Fold only unquoted
    # text so ``IN``/``in`` stay equivalent while ``'NONE'`` and ``'none'``
    # remain distinct catalog values.
    return _fold_unquoted_sql_case(_compact_constraint(_strip_harmless_display_casts(definition)))


def _canonical_predicate(predicate: str | None) -> str:
    """Quote-aware predicate compare; quoted ``ACTIVE`` stays uppercase."""

    if predicate is None:
        return ""
    return _fold_unquoted_sql_case(_compact_constraint(_strip_harmless_display_casts(predicate)))


def _canonical_default(expression: str | None) -> str:
    if expression is None:
        return ""
    return _canonical_predicate(expression)


def expected_app_column_update(table_name: str, column_name: str) -> bool:
    return table_name in MUTABLE_LINEAGE_TABLES and column_name == STATUS_UPDATE_COLUMN


def is_expected_active_partial_unique_conflict(error: BaseException) -> bool:
    """True only for SQLAlchemy IntegrityError 23505 on the one-ACTIVE index."""

    if not isinstance(error, IntegrityError):
        return False
    original = getattr(error, "orig", None)
    if original is None:
        return False
    diagnostic = getattr(original, "diag", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is None:
        sqlstate = getattr(diagnostic, "sqlstate", None)
    if sqlstate is None:
        sqlstate = getattr(original, "pgcode", None)
    if str(sqlstate) != "23505":
        return False
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return constraint_name == ACTIVE_PARTIAL_UNIQUE[0]


def _verify_revision(connection: Connection) -> None:
    revisions = [
        str(value)
        for value in connection.execute(text("SELECT version_num FROM erp.alembic_version"))
        .scalars()
        .all()
    ]
    if revisions != [EXPECTED_REVISION]:
        raise SystemExit(
            f"CURRENT_0028_REVISION_MISMATCH: expected={[EXPECTED_REVISION]} actual={revisions}"
        )


def _verify_tables(connection: Connection) -> None:
    # Privilege-independent inventory. information_schema hides ungranted
    # objects; omit relkind m/S and a hidden matview or standalone sequence
    # can sit beside the six tables unnoticed.
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                f"""
                SELECT relation_row.relname,
                       relation_row.relkind,
                       relation_row.relispartition,
                       relation_row.relpersistence
                  FROM pg_class AS relation_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname {W3_NAMESPACE_LIKE_SQL}
                   AND relation_row.relkind IN ('r', 'p', 'v', 'f', 'm', 'S')
                """
            )
        ).mappings()
    ]
    actual: dict[str, dict[str, object]] = {}
    duplicates: list[str] = []
    for row in fetched:
        name = str(row["relname"])
        if name in actual:
            duplicates.append(name)
        actual[name] = row
    if duplicates:
        raise SystemExit(f"CURRENT_0028_TABLE_DUPLICATE: {sorted(set(duplicates))}")
    expected_names = set(EXPECTED_W3_RELATION_KINDS)
    missing = sorted(expected_names - set(actual))
    extra = sorted(set(actual) - expected_names)
    if missing or extra or len(fetched) != len(EXPECTED_W3_RELATION_KINDS):
        raise SystemExit(
            "CURRENT_0028_TABLE_MISMATCH: "
            f"cardinality_expected={len(EXPECTED_W3_RELATION_KINDS)} "
            f"cardinality_actual={len(fetched)} missing={missing} extra={extra}"
        )
    kind_failures: dict[str, object] = {}
    for name, expected_kind in sorted(EXPECTED_W3_RELATION_KINDS.items()):
        row = actual[name]
        observed = {
            "relkind": str(row["relkind"]),
            "relispartition": bool(row["relispartition"]),
        }
        if observed["relkind"] != expected_kind or observed["relispartition"]:
            kind_failures[name] = {"expected_kind": expected_kind, **observed}
    if kind_failures:
        raise SystemExit(f"CURRENT_0028_TABLE_KIND_MISMATCH: {kind_failures}")

    inherit_rows = [
        (str(row["child_name"]), str(row["parent_name"]))
        for row in connection.execute(
            text(
                """
                SELECT child_relation.relname AS child_name,
                       parent_relation.relname AS parent_name
                  FROM pg_inherits AS inherit_row
                  JOIN pg_class AS child_relation
                    ON child_relation.oid = inherit_row.inhrelid
                  JOIN pg_class AS parent_relation
                    ON parent_relation.oid = inherit_row.inhparent
                  JOIN pg_namespace AS child_namespace
                    ON child_namespace.oid = child_relation.relnamespace
                  JOIN pg_namespace AS parent_namespace
                    ON parent_namespace.oid = parent_relation.relnamespace
                 WHERE (
                         child_namespace.nspname = 'erp'
                         AND child_relation.relname = ANY(:tables)
                       )
                    OR (
                         parent_namespace.nspname = 'erp'
                         AND parent_relation.relname = ANY(:tables)
                       )
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    if inherit_rows:
        raise SystemExit(f"CURRENT_0028_TABLE_INHERITANCE_MISMATCH: {inherit_rows}")


def _verify_columns(connection: Connection) -> None:
    for table_name, required in EXPECTED_COLUMN_CATALOG.items():
        rows = connection.execute(
            text(
                """
                SELECT attribute_row.attname AS column_name,
                       pg_catalog.format_type(
                           attribute_row.atttypid, attribute_row.atttypmod
                       ) AS formatted_type,
                       NOT attribute_row.attnotnull AS nullable,
                       pg_get_expr(default_row.adbin, default_row.adrelid) AS default_expr,
                       attribute_row.attidentity AS identity
                  FROM pg_attribute AS attribute_row
                  JOIN pg_class AS relation_row
                    ON relation_row.oid = attribute_row.attrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                  LEFT JOIN pg_attrdef AS default_row
                    ON default_row.adrelid = attribute_row.attrelid
                   AND default_row.adnum = attribute_row.attnum
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname = :table_name
                   AND attribute_row.attnum > 0
                   AND NOT attribute_row.attisdropped
                 ORDER BY attribute_row.attnum
                """
            ),
            {"table_name": table_name},
        ).mappings()
        actual = {str(row["column_name"]): dict(row) for row in rows}
        actual_names = set(actual)
        required_names = set(required)
        missing = sorted(required_names - actual_names)
        extra = sorted(actual_names - required_names)
        forbidden = sorted(FORBIDDEN_GENERIC_COLUMNS & actual_names)
        mismatches: dict[str, object] = {}
        for column_name, spec in required.items():
            row = actual.get(column_name)
            if row is None:
                continue
            observed = {
                "type": str(row["formatted_type"]),
                "nullable": bool(row["nullable"]),
                "default": _canonical_default(cast(str | None, row["default_expr"])),
                "identity": str(row["identity"] or ""),
            }
            expected = {
                "type": spec["type"],
                "nullable": spec["nullable"],
                "default": _canonical_default(spec["default"]),
                "identity": spec["identity"],
            }
            if observed != expected:
                mismatches[column_name] = {"expected": expected, "actual": observed}
        if missing or extra or forbidden or mismatches:
            raise SystemExit(
                "CURRENT_0028_COLUMN_SET_MISMATCH: "
                f"table={table_name} missing={missing} extra={extra} "
                f"forbidden={forbidden} catalog={mismatches}"
            )


def _verify_no_bytea(connection: Connection) -> None:
    rows = connection.execute(
        text(
            f"""
            SELECT table_name, column_name, data_type, udt_name
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name {W3_NAMESPACE_LIKE_SQL}
               AND (data_type = 'bytea' OR udt_name = 'bytea')
            """
        )
    ).all()
    if rows:
        raise SystemExit(f"CURRENT_0028_BYTEA_PRESENT: {rows!r}")


def _verify_checks(connection: Connection) -> None:
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname AS table_name,
                       con.conname,
                       con.convalidated,
                       pg_get_constraintdef(con.oid, true) AS definition
                  FROM pg_constraint AS con
                  JOIN pg_class AS relation_row ON relation_row.oid = con.conrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname = ANY(:tables)
                   AND con.contype = 'c'
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    actual: dict[tuple[str, str], dict[str, object]] = {}
    duplicates: list[tuple[str, str]] = []
    for row in fetched:
        key = (str(row["table_name"]), str(row["conname"]))
        if key in actual:
            duplicates.append(key)
        actual[key] = row
    if duplicates:
        raise SystemExit(f"CURRENT_0028_CHECK_DUPLICATE: {sorted(set(duplicates))}")
    missing = sorted(set(EXPECTED_CHECKS) - set(actual))
    extra = sorted(set(actual) - set(EXPECTED_CHECKS))
    if missing or extra or len(fetched) != len(EXPECTED_CHECKS):
        raise SystemExit(
            "CURRENT_0028_CHECK_NAME_MISMATCH: "
            f"cardinality_expected={len(EXPECTED_CHECKS)} "
            f"cardinality_actual={len(fetched)} missing={missing} extra={extra}"
        )

    failures: dict[str, object] = {}
    for key, expected_definition in EXPECTED_CHECKS.items():
        row = actual[key]
        observed_definition = str(row["definition"])
        expected_canonical = _canonical_check_definition(expected_definition)
        observed_canonical = _canonical_check_definition(observed_definition)
        if not bool(row["convalidated"]) or observed_canonical != expected_canonical:
            failures[f"{key[0]}.{key[1]}"] = {
                "validated": bool(row["convalidated"]),
                "expected": expected_canonical,
                "actual": observed_canonical,
            }
    if failures:
        raise SystemExit(f"CURRENT_0028_CHECK_MISMATCH: {failures}")


def _verify_uniques(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT index_class.relname AS index_name,
                   namespace_row.nspname || '.' || relation_row.relname AS table_name,
                   index_class.relpersistence,
                   index_row.indisvalid,
                   constraint_row.contype AS constraint_type,
                   constraint_row.convalidated,
                   constraint_row.condeferrable,
                   constraint_row.condeferred,
                   array_agg(attribute_row.attname ORDER BY key.ordinality) AS columns
              FROM pg_index AS index_row
              JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
              JOIN pg_class AS relation_row ON relation_row.oid = index_row.indrelid
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              LEFT JOIN pg_constraint AS constraint_row
                ON constraint_row.conindid = index_row.indexrelid
               AND constraint_row.contype = 'u'
              JOIN LATERAL unnest(index_row.indkey)
                   WITH ORDINALITY AS key(attnum, ordinality) ON true
              JOIN pg_attribute AS attribute_row
                ON attribute_row.attrelid = index_row.indrelid
               AND attribute_row.attnum = key.attnum
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
               AND index_row.indisunique
               AND NOT index_row.indisprimary
               AND index_row.indpred IS NULL
             GROUP BY index_class.relname, namespace_row.nspname, relation_row.relname,
                      index_class.relpersistence, index_row.indisvalid,
                      constraint_row.contype, constraint_row.convalidated,
                      constraint_row.condeferrable, constraint_row.condeferred
            """
        ),
        {"tables": list(REQUIRED_TABLES)},
    ).mappings()
    actual = {str(row["index_name"]): dict(row) for row in rows}
    missing = sorted(set(EXPECTED_UNIQUES) - actual.keys())
    extra = sorted(set(actual) - set(EXPECTED_UNIQUES))
    failures: dict[str, object] = {}
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    for name, (table_name, columns) in EXPECTED_UNIQUES.items():
        row = actual.get(name)
        if row is None:
            continue
        observed = {
            "table": str(row["table_name"]),
            "columns": _as_names(cast(Iterable[object], row["columns"])),
            "valid": bool(row["indisvalid"]),
            "persistence": str(row["relpersistence"]),
            "constraint_type": row["constraint_type"],
            "validated": bool(row["convalidated"]),
            "deferrable": bool(row["condeferrable"]),
            "deferred": bool(row["condeferred"]),
        }
        if (
            observed["table"] != table_name
            or observed["columns"] != columns
            or not observed["valid"]
            or observed["persistence"] != "p"
            or observed["constraint_type"] != "u"
            or not observed["validated"]
            or observed["deferrable"]
            or observed["deferred"]
        ):
            failures[name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0028_UNIQUE_MISMATCH: {failures}")


def _verify_active_partial_unique(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT index_class.relname AS index_name,
                   namespace_row.nspname || '.' || relation_row.relname AS table_name,
                   index_class.relpersistence,
                   index_row.indisunique,
                   index_row.indisvalid,
                   pg_get_expr(index_row.indpred, index_row.indrelid, true) AS predicate,
                   array_agg(attribute_row.attname ORDER BY key.ordinality) AS columns
              FROM pg_index AS index_row
              JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
              JOIN pg_class AS relation_row ON relation_row.oid = index_row.indrelid
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              JOIN LATERAL unnest(index_row.indkey)
                   WITH ORDINALITY AS key(attnum, ordinality) ON true
              JOIN pg_attribute AS attribute_row
                ON attribute_row.attrelid = index_row.indrelid
               AND attribute_row.attnum = key.attnum
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
               AND index_row.indisunique
               AND NOT index_row.indisprimary
               AND index_row.indpred IS NOT NULL
             GROUP BY index_class.relname, namespace_row.nspname, relation_row.relname,
                      index_class.relpersistence, index_row.indisunique,
                      index_row.indisvalid, index_row.indpred, index_row.indrelid
            """
        ),
        {"tables": list(REQUIRED_TABLES)},
    ).mappings()
    actual = {str(row["index_name"]): dict(row) for row in rows}
    name, table_name, columns, predicate = ACTIVE_PARTIAL_UNIQUE
    missing = sorted({name} - set(actual))
    extra = sorted(set(actual) - {name})
    row = actual.get(name)
    if row is None:
        raise SystemExit(
            f"CURRENT_0028_ACTIVE_PARTIAL_UNIQUE_MISMATCH: missing={missing} extra={extra}"
        )
    observed = {
        "table": str(row["table_name"]),
        "columns": _as_names(cast(Iterable[object], row["columns"])),
        "unique": bool(row["indisunique"]),
        "valid": bool(row["indisvalid"]),
        "persistence": str(row["relpersistence"]),
        "predicate": _canonical_predicate(cast(str | None, row["predicate"])),
    }
    if (
        missing
        or extra
        or observed["table"] != table_name
        or observed["columns"] != columns
        or not observed["unique"]
        or not observed["valid"]
        or observed["persistence"] != "p"
        or observed["predicate"] != _canonical_predicate(predicate)
    ):
        raise SystemExit(f"CURRENT_0028_ACTIVE_PARTIAL_UNIQUE_MISMATCH: {observed!r}")


def _verify_primary_keys(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT COALESCE(constraint_row.conname, index_class.relname) AS constraint_name,
                   namespace_row.nspname || '.' || relation_row.relname AS table_name,
                   index_class.relpersistence,
                   index_row.indisvalid,
                   constraint_row.convalidated,
                   constraint_row.condeferrable,
                   constraint_row.condeferred,
                   array_agg(attribute_row.attname ORDER BY key.ordinality) AS columns
              FROM pg_index AS index_row
              JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
              JOIN pg_class AS relation_row ON relation_row.oid = index_row.indrelid
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              LEFT JOIN pg_constraint AS constraint_row
                ON constraint_row.conindid = index_row.indexrelid
               AND constraint_row.contype = 'p'
              JOIN LATERAL unnest(index_row.indkey)
                   WITH ORDINALITY AS key(attnum, ordinality) ON true
              JOIN pg_attribute AS attribute_row
                ON attribute_row.attrelid = index_row.indrelid
               AND attribute_row.attnum = key.attnum
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
               AND index_row.indisprimary
             GROUP BY constraint_row.conname, index_class.relname, namespace_row.nspname,
                      relation_row.relname, index_class.relpersistence, index_row.indisvalid,
                      constraint_row.convalidated, constraint_row.condeferrable,
                      constraint_row.condeferred
            """
        ),
        {"tables": list(REQUIRED_TABLES)},
    ).mappings()
    actual = {str(row["constraint_name"]): dict(row) for row in rows}
    missing = sorted(set(EXPECTED_PRIMARY_KEYS) - actual.keys())
    extra = sorted(set(actual) - set(EXPECTED_PRIMARY_KEYS))
    failures: dict[str, object] = {}
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    for name, (table_name, columns) in EXPECTED_PRIMARY_KEYS.items():
        row = actual.get(name)
        if row is None:
            continue
        observed = {
            "table": str(row["table_name"]),
            "columns": _as_names(cast(Iterable[object], row["columns"])),
            "valid": bool(row["indisvalid"]),
            "persistence": str(row["relpersistence"]),
            "validated": bool(row["convalidated"]),
            "deferrable": bool(row["condeferrable"]),
            "deferred": bool(row["condeferred"]),
        }
        if (
            observed["table"] != table_name
            or observed["columns"] != columns
            or not observed["valid"]
            or observed["persistence"] != "p"
            or not observed["validated"]
            or observed["deferrable"]
            or observed["deferred"]
        ):
            failures[name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0028_PRIMARY_KEY_MISMATCH: {failures}")


def _verify_explicit_indexes(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT index_class.relname AS index_name,
                   namespace_row.nspname || '.' || relation_row.relname AS table_name,
                   access_method.amname AS access_method,
                   index_class.relpersistence,
                   index_row.indisunique,
                   index_row.indisvalid,
                   pg_get_expr(index_row.indpred, index_row.indrelid, true) AS predicate,
                   (
                     SELECT COALESCE(
                       array_agg(
                         pg_get_indexdef(
                             index_row.indexrelid,
                             key_ord.ordinality::integer,
                             true
                         )
                         ORDER BY key_ord.ordinality
                       ),
                       ARRAY[]::text[]
                     )
                     FROM generate_series(1, index_row.indnkeyatts) AS key_ord(ordinality)
                   ) AS key_items,
                   (
                     SELECT COALESCE(
                       array_agg(
                         include_attribute.attname
                         ORDER BY include_key.ordinality
                       ),
                       ARRAY[]::text[]
                     )
                     FROM unnest(index_row.indkey)
                          WITH ORDINALITY AS include_key(attnum, ordinality)
                     JOIN pg_attribute AS include_attribute
                       ON include_attribute.attrelid = index_row.indrelid
                      AND include_attribute.attnum = include_key.attnum
                    WHERE include_key.ordinality > index_row.indnkeyatts
                   ) AS include_columns
              FROM pg_index AS index_row
              JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid
              JOIN pg_class AS relation_row ON relation_row.oid = index_row.indrelid
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              JOIN pg_am AS access_method ON access_method.oid = index_class.relam
              LEFT JOIN pg_constraint AS constraint_row
                ON constraint_row.conindid = index_row.indexrelid
               AND constraint_row.contype IN ('u', 'p')
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
               AND constraint_row.oid IS NULL
            """
        ),
        {"tables": list(REQUIRED_TABLES)},
    ).mappings()
    actual = {str(row["index_name"]): dict(row) for row in rows}
    missing = sorted(set(EXPECTED_NON_CONSTRAINT_INDEXES) - actual.keys())
    extra = sorted(set(actual) - set(EXPECTED_NON_CONSTRAINT_INDEXES))
    failures: dict[str, object] = {}
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    for name, expected in EXPECTED_NON_CONSTRAINT_INDEXES.items():
        row = actual.get(name)
        if row is None:
            continue
        observed = {
            "table": str(row["table_name"]),
            "access_method": str(row["access_method"]),
            "columns": _index_key_items(cast(Iterable[object], row["key_items"] or ())),
            "include": _as_names(cast(Iterable[object], row["include_columns"] or ())),
            "unique": bool(row["indisunique"]),
            "valid": bool(row["indisvalid"]),
            "persistence": str(row["relpersistence"]),
            "predicate": _canonical_predicate(cast(str | None, row["predicate"])),
        }
        if (
            observed["table"] != expected["table"]
            or observed["access_method"] != expected["access_method"]
            or observed["columns"] != expected["columns"]
            or observed["include"] != expected["include"]
            or observed["unique"] != expected["unique"]
            or not observed["valid"]
            or observed["persistence"] != "p"
            or observed["predicate"] != _canonical_predicate(str(expected["predicate"]))
        ):
            failures[name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0028_EXPLICIT_INDEX_MISMATCH: {failures}")


def _verify_foreign_keys(connection: Connection) -> None:
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT constraint_row.conname,
                       local_relation.relname AS relation_name,
                       local_namespace.nspname || '.' || local_relation.relname AS table_name,
                       referenced_namespace.nspname || '.' || referenced_relation.relname
                           AS referenced_table,
                       constraint_row.convalidated,
                       constraint_row.condeferrable,
                       constraint_row.condeferred,
                       constraint_row.confdeltype,
                       constraint_row.confupdtype,
                       constraint_row.confmatchtype,
                       constraint_row.conislocal,
                       constraint_row.coninhcount,
                       constraint_row.connoinherit,
                       constraint_row.conparentid,
                       array_agg(local_column.attname ORDER BY local_key.ordinality)
                           AS local_columns,
                       array_agg(referenced_column.attname ORDER BY local_key.ordinality)
                           AS referenced_columns
                  FROM pg_constraint AS constraint_row
                  JOIN pg_class AS local_relation
                    ON local_relation.oid = constraint_row.conrelid
                  JOIN pg_namespace AS local_namespace
                    ON local_namespace.oid = local_relation.relnamespace
                  JOIN LATERAL unnest(constraint_row.conkey)
                       WITH ORDINALITY AS local_key(attnum, ordinality) ON true
                  JOIN pg_attribute AS local_column
                    ON local_column.attrelid = constraint_row.conrelid
                   AND local_column.attnum = local_key.attnum
                  JOIN LATERAL unnest(constraint_row.confkey)
                       WITH ORDINALITY AS referenced_key(attnum, ordinality)
                    ON referenced_key.ordinality = local_key.ordinality
                  JOIN pg_attribute AS referenced_column
                    ON referenced_column.attrelid = constraint_row.confrelid
                   AND referenced_column.attnum = referenced_key.attnum
                  JOIN pg_class AS referenced_relation
                    ON referenced_relation.oid = constraint_row.confrelid
                  JOIN pg_namespace AS referenced_namespace
                    ON referenced_namespace.oid = referenced_relation.relnamespace
                 WHERE local_namespace.nspname = 'erp'
                   AND local_relation.relname = ANY(:tables)
                   AND constraint_row.contype = 'f'
                 GROUP BY constraint_row.oid, local_namespace.nspname, local_relation.relname,
                          referenced_namespace.nspname, referenced_relation.relname
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    actual: dict[tuple[str, str], dict[str, object]] = {}
    duplicates: list[tuple[str, str]] = []
    for row in fetched:
        key = (str(row["relation_name"]), str(row["conname"]))
        if key in actual:
            duplicates.append(key)
        actual[key] = row
    if duplicates:
        raise SystemExit(f"CURRENT_0028_FOREIGN_KEY_DUPLICATE: {sorted(set(duplicates))}")
    missing = sorted(set(EXPECTED_FOREIGN_KEYS) - set(actual))
    extra = sorted(set(actual) - set(EXPECTED_FOREIGN_KEYS))
    failures: dict[str, object] = {}
    if missing or extra or len(fetched) != len(EXPECTED_FOREIGN_KEYS):
        failures["names"] = {
            "cardinality_expected": len(EXPECTED_FOREIGN_KEYS),
            "cardinality_actual": len(fetched),
            "missing": missing,
            "extra": extra,
        }
    for key, expected in EXPECTED_FOREIGN_KEYS.items():
        catalog_row = actual.get(key)
        if catalog_row is None:
            continue
        parent_oid = catalog_row["conparentid"]
        observed = {
            "table": str(catalog_row["table_name"]),
            "columns": _as_names(cast(Iterable[object], catalog_row["local_columns"])),
            "referenced_table": str(catalog_row["referenced_table"]),
            "referenced_columns": _as_names(
                cast(Iterable[object], catalog_row["referenced_columns"])
            ),
            "delete_action": str(catalog_row["confdeltype"]),
            "update_action": str(catalog_row["confupdtype"]),
            "match_type": str(catalog_row["confmatchtype"]),
            "is_local": bool(catalog_row["conislocal"]),
            "inherit_count": int(cast(int, catalog_row["coninhcount"])),
            "no_inherit": bool(catalog_row["connoinherit"]),
            "parent_oid": int(cast(int, parent_oid)) if parent_oid is not None else None,
            "validated": bool(catalog_row["convalidated"]),
            "deferrable": bool(catalog_row["condeferrable"]),
            "deferred": bool(catalog_row["condeferred"]),
        }
        if (
            observed["table"] != expected["table"]
            or observed["columns"] != expected["columns"]
            or observed["referenced_table"] != expected["referenced_table"]
            or observed["referenced_columns"] != expected["referenced_columns"]
            or observed["delete_action"] != "r"
            or observed["update_action"] != "a"
            or observed["match_type"] != PG16_ORDINARY_LOCAL_FK_METADATA["match_type"]
            or observed["is_local"] is not PG16_ORDINARY_LOCAL_FK_METADATA["is_local"]
            or observed["inherit_count"] != PG16_ORDINARY_LOCAL_FK_METADATA["inherit_count"]
            or observed["no_inherit"] is not PG16_ORDINARY_LOCAL_FK_METADATA["no_inherit"]
            or observed["parent_oid"] != PG16_ORDINARY_LOCAL_FK_METADATA["parent_oid"]
            or not observed["validated"]
            or observed["deferrable"]
            or observed["deferred"]
        ):
            failures[f"{key[0]}.{key[1]}"] = observed
    if failures:
        raise SystemExit(f"CURRENT_0028_FOREIGN_KEY_MISMATCH: {failures}")


def _verify_relation_owners(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT table_row.relname AS table_name,
                   pg_get_userbyid(table_row.relowner) AS table_owner,
                   pg_get_userbyid(sequence_row.relowner) AS sequence_owner,
                   sequence_row.relname AS sequence_name,
                   sequence_row.relkind AS sequence_kind,
                   pg_get_serial_sequence(
                       'erp.' || table_row.relname, 'id'
                   ) AS owned_sequence,
                   identity_depend.deptype AS identity_deptype,
                   identity_column.attname AS owned_column
              FROM pg_class AS table_row
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = table_row.relnamespace
              LEFT JOIN pg_class AS sequence_row
                ON sequence_row.relnamespace = namespace_row.oid
               AND sequence_row.relname = table_row.relname || '_id_seq'
               AND sequence_row.relkind = 'S'
              LEFT JOIN pg_depend AS identity_depend
                ON identity_depend.objid = sequence_row.oid
               AND identity_depend.refobjid = table_row.oid
               AND identity_depend.deptype = 'i'
              LEFT JOIN pg_attribute AS identity_column
                ON identity_column.attrelid = identity_depend.refobjid
               AND identity_column.attnum = identity_depend.refobjsubid
             WHERE namespace_row.nspname = 'erp'
               AND table_row.relname = ANY(:tables)
               AND table_row.relkind = 'r'
            """
        ),
        {"tables": list(REQUIRED_TABLES)},
    ).mappings()
    actual = {str(row["table_name"]): dict(row) for row in rows}
    missing = sorted(REQUIRED_TABLES - set(actual))
    extra = sorted(set(actual) - REQUIRED_TABLES)
    failures: dict[str, object] = {}
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    for table_name in sorted(REQUIRED_TABLES):
        row = actual.get(table_name)
        if row is None:
            continue
        expected_sequence = f"{table_name}_id_seq"
        observed = {
            "table_owner": str(row["table_owner"] or ""),
            "sequence_owner": str(row["sequence_owner"] or ""),
            "sequence_name": str(row["sequence_name"] or ""),
            "sequence_kind": str(row["sequence_kind"] or ""),
            "owned_sequence": str(row["owned_sequence"] or ""),
            "identity_deptype": str(row["identity_deptype"] or ""),
            "owned_column": str(row["owned_column"] or ""),
        }
        if (
            observed["table_owner"] != EXPECTED_OWNER
            or observed["sequence_owner"] != EXPECTED_OWNER
            or observed["sequence_name"] != expected_sequence
            or observed["sequence_kind"] != "S"
            or observed["owned_sequence"] != f"erp.{expected_sequence}"
            or observed["identity_deptype"] != "i"
            or observed["owned_column"] != "id"
        ):
            failures[table_name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0028_RELATION_OWNER_MISMATCH: {failures}")


def _verify_identity_sequence_acl_entries(connection: Connection) -> None:
    rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT sequence_row.relname AS sequence_name,
                       pg_get_userbyid(sequence_row.relowner) AS sequence_owner,
                       CASE
                         WHEN acl.grantee = 0 THEN 'PUBLIC'
                         ELSE grantee.rolname
                       END AS grantee,
                       CASE
                         WHEN acl.grantor = 0 THEN 'PUBLIC'
                         ELSE grantor.rolname
                       END AS grantor,
                       acl.privilege_type,
                       acl.is_grantable
                  FROM pg_class AS sequence_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = sequence_row.relnamespace
                  LEFT JOIN LATERAL aclexplode(sequence_row.relacl) AS acl ON true
                  LEFT JOIN pg_roles AS grantee
                    ON grantee.oid = acl.grantee
                  LEFT JOIN pg_roles AS grantor
                    ON grantor.oid = acl.grantor
                 WHERE namespace_row.nspname = 'erp'
                   AND sequence_row.relkind = 'S'
                   AND sequence_row.relname = ANY(:sequences)
                """
            ),
            {"sequences": [f"{table_name}_id_seq" for table_name in _SEQUENCE_TABLES]},
        ).mappings()
    ]
    actual_names = {str(row["sequence_name"]) for row in rows}
    expected_names = {f"{table_name}_id_seq" for table_name in REQUIRED_TABLES}
    failures: dict[str, object] = {}
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    entries_by_sequence: dict[str, list[tuple[str, str, str, bool]]] = {
        name: [] for name in expected_names
    }
    owners: dict[str, str] = {}
    for row in rows:
        sequence_name = str(row["sequence_name"])
        owners[sequence_name] = str(row["sequence_owner"] or "")
        if row["privilege_type"] is None:
            continue
        entries_by_sequence.setdefault(sequence_name, []).append(
            (
                str(row["grantee"] or "PUBLIC"),
                str(row["grantor"] or "UNKNOWN"),
                str(row["privilege_type"]),
                bool(row["is_grantable"]),
            )
        )
    for sequence_name in sorted(expected_names):
        sequence_owner = owners.get(sequence_name, "")
        if sequence_owner != EXPECTED_OWNER:
            failures[sequence_name] = {"sequence_owner": sequence_owner}
            continue
        drifts = _exact_acl_drifts(
            owner=sequence_owner,
            entries=entries_by_sequence.get(sequence_name, []),
            required_non_owner=REQUIRED_SEQUENCE_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_SEQUENCE_OWNER_PRIVILEGES,
        )
        if drifts:
            failures[sequence_name] = sorted(drifts)
    if failures:
        raise SystemExit(f"CURRENT_0028_SEQUENCE_ACL_MISMATCH: {failures}")


def _verify_shared_schema_acl(connection: Connection) -> None:
    rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT pg_get_userbyid(namespace_row.nspowner) AS schema_owner,
                       CASE
                         WHEN acl.grantee = 0 THEN 'PUBLIC'
                         ELSE grantee.rolname
                       END AS grantee,
                       CASE
                         WHEN acl.grantor = 0 THEN 'PUBLIC'
                         ELSE grantor.rolname
                       END AS grantor,
                       acl.privilege_type,
                       acl.is_grantable
                  FROM pg_namespace AS namespace_row
                  LEFT JOIN LATERAL aclexplode(namespace_row.nspacl) AS acl ON true
                  LEFT JOIN pg_roles AS grantee
                    ON grantee.oid = acl.grantee
                  LEFT JOIN pg_roles AS grantor
                    ON grantor.oid = acl.grantor
                 WHERE namespace_row.nspname = 'erp'
                """
            )
        ).mappings()
    ]
    if not rows:
        raise SystemExit("CURRENT_0028_SCHEMA_ACL_MISMATCH: schema=erp missing")
    schema_owner = str(rows[0]["schema_owner"] or "")
    if schema_owner != EXPECTED_OWNER:
        raise SystemExit(f"CURRENT_0028_SCHEMA_OWNER_MISMATCH: actual={schema_owner!r}")
    entries = [
        (
            str(row["grantee"] or "PUBLIC"),
            str(row["grantor"] or "UNKNOWN"),
            str(row["privilege_type"]),
            bool(row["is_grantable"]),
        )
        for row in rows
        if row["privilege_type"] is not None
    ]
    drifts = _exact_acl_drifts(
        owner=schema_owner,
        entries=entries,
        required_non_owner=REQUIRED_SCHEMA_NON_OWNER_ACL,
        owner_canonical_privileges=PG16_SCHEMA_OWNER_PRIVILEGES,
    )
    if drifts:
        raise SystemExit(f"CURRENT_0028_SCHEMA_ACL_MISMATCH: {sorted(drifts)}")


def _acl_entry_tuple(row: object) -> tuple[str, str, str, bool]:
    mapping = cast(dict[str, object], row)
    return (
        str(mapping["grantee"] or "PUBLIC"),
        str(mapping["grantor"] or "UNKNOWN"),
        str(mapping["privilege_type"]),
        bool(mapping["is_grantable"]),
    )


def _verify_w3_table_relacl_entries(connection: Connection) -> None:
    rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname AS table_name,
                       pg_get_userbyid(relation_row.relowner) AS table_owner,
                       CASE
                         WHEN acl.grantee = 0 THEN 'PUBLIC'
                         ELSE grantee.rolname
                       END AS grantee,
                       CASE
                         WHEN acl.grantor = 0 THEN 'PUBLIC'
                         ELSE grantor.rolname
                       END AS grantor,
                       acl.privilege_type,
                       acl.is_grantable
                  FROM pg_class AS relation_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                  LEFT JOIN LATERAL aclexplode(relation_row.relacl) AS acl ON true
                  LEFT JOIN pg_roles AS grantee
                    ON grantee.oid = acl.grantee
                  LEFT JOIN pg_roles AS grantor
                    ON grantor.oid = acl.grantor
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relkind = 'r'
                   AND relation_row.relname = ANY(:tables)
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    actual_names = {str(row["table_name"]) for row in rows}
    failures: dict[str, object] = {}
    missing = sorted(REQUIRED_TABLES - actual_names)
    extra = sorted(actual_names - REQUIRED_TABLES)
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    entries_by_table: dict[str, list[tuple[str, str, str, bool]]] = {
        name: [] for name in REQUIRED_TABLES
    }
    owners: dict[str, str] = {}
    for row in rows:
        table_name = str(row["table_name"])
        owners[table_name] = str(row["table_owner"] or "")
        if row["privilege_type"] is None:
            continue
        entries_by_table.setdefault(table_name, []).append(_acl_entry_tuple(row))
    for table_name in sorted(REQUIRED_TABLES):
        table_owner = owners.get(table_name, "")
        if table_owner != EXPECTED_OWNER:
            failures[table_name] = {"table_owner": table_owner}
            continue
        entries = entries_by_table.get(table_name, [])
        if any(
            grantee != table_owner and privilege == "UPDATE"
            for grantee, _grantor, privilege, _grantable in entries
        ):
            raise SystemExit(f"CURRENT_0028_TABLE_WIDE_UPDATE_PRESENT: {table_name}")
        drifts = _exact_acl_drifts(
            owner=table_owner,
            entries=entries,
            required_non_owner=REQUIRED_TABLE_NON_OWNER_ACL,
            owner_canonical_privileges=PG16_TABLE_OWNER_PRIVILEGES,
        )
        if drifts:
            failures[table_name] = sorted(drifts)
    if failures:
        raise SystemExit(f"CURRENT_0028_TABLE_RELACL_MISMATCH: {failures}")


def _verify_w3_column_attacl_entries(connection: Connection) -> None:
    rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname AS table_name,
                       attribute_row.attname AS column_name,
                       pg_get_userbyid(relation_row.relowner) AS table_owner,
                       CASE
                         WHEN acl.grantee = 0 THEN 'PUBLIC'
                         ELSE grantee.rolname
                       END AS grantee,
                       CASE
                         WHEN acl.grantor = 0 THEN 'PUBLIC'
                         ELSE grantor.rolname
                       END AS grantor,
                       acl.privilege_type,
                       acl.is_grantable
                  FROM pg_attribute AS attribute_row
                  JOIN pg_class AS relation_row
                    ON relation_row.oid = attribute_row.attrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                  LEFT JOIN LATERAL aclexplode(attribute_row.attacl) AS acl ON true
                  LEFT JOIN pg_roles AS grantee
                    ON grantee.oid = acl.grantee
                  LEFT JOIN pg_roles AS grantor
                    ON grantor.oid = acl.grantor
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relkind = 'r'
                   AND relation_row.relname = ANY(:tables)
                   AND attribute_row.attnum > 0
                   AND NOT attribute_row.attisdropped
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    grouped: dict[tuple[str, str], list[tuple[str, str, str, bool]]] = {}
    owners: dict[str, str] = {}
    for row in rows:
        table_name = str(row["table_name"])
        column_name = str(row["column_name"])
        owners[table_name] = str(row["table_owner"] or "")
        grouped.setdefault((table_name, column_name), [])
        if row["privilege_type"] is None:
            continue
        grouped[(table_name, column_name)].append(_acl_entry_tuple(row))
    failures: dict[str, object] = {}
    for table_name in sorted(REQUIRED_TABLES):
        table_owner = owners.get(table_name, "")
        if table_owner != EXPECTED_OWNER:
            failures[table_name] = {"table_owner": table_owner}
            continue
        for column_name in REQUIRED_COLUMNS[table_name]:
            drifts = _exact_acl_drifts(
                owner=table_owner,
                entries=grouped.get((table_name, column_name), []),
                required_non_owner=required_column_non_owner_acl(table_name, column_name),
                owner_canonical_privileges=PG16_COLUMN_OWNER_PRIVILEGES,
            )
            if drifts:
                failures[f"{table_name}.{column_name}"] = sorted(drifts)
    if failures:
        raise SystemExit(f"CURRENT_0028_UNEXPECTED_COLUMN_GRANT: {failures}")


def _column_privilege(
    connection: Connection,
    role: str,
    table_name: str,
    column_name: str,
    privilege: str,
) -> bool:
    return bool(
        connection.scalar(
            text(
                """
                SELECT has_column_privilege(:role, :table_name, :column_name, :privilege)
                """
            ),
            {
                "role": role,
                "table_name": f"erp.{table_name}",
                "column_name": column_name,
                "privilege": privilege,
            },
        )
    )


def _verify_acl(connection: Connection) -> None:
    _verify_w3_table_relacl_entries(connection)
    for table_name in sorted(REQUIRED_TABLES):
        app_table = _privileges(connection, "erp_app", table_name)
        if table_name in IMMUTABLE_TABLES:
            if app_table != ERP_APP_APPEND_ONLY_PRIVILEGES:
                raise SystemExit(f"CURRENT_0028_APP_APPEND_ONLY_ACL_MISMATCH: {table_name}")
        else:
            if (
                app_table[0] is not True
                or app_table[1] is not True
                or app_table[3] is not False
                or app_table[4] is not False
                or app_table[5] is not False
                or app_table[6] is not False
                or app_table[7] is not False
                or app_table[8] is not False
                or app_table[9] is not False
            ):
                raise SystemExit(f"CURRENT_0028_APP_LINEAGE_ACL_MISMATCH: {table_name} {app_table}")
        if _privileges(connection, "erp_backup", table_name) != ERP_APP_READ_ONLY_PRIVILEGES:
            raise SystemExit(f"CURRENT_0028_BACKUP_TABLE_ACL_MISMATCH: {table_name}")

        reviewed_columns = REQUIRED_COLUMNS[table_name]
        for column_name in reviewed_columns:
            app_update = _column_privilege(connection, "erp_app", table_name, column_name, "UPDATE")
            expected_update = expected_app_column_update(table_name, column_name)
            if app_update is not expected_update:
                raise SystemExit(
                    "CURRENT_0028_APP_COLUMN_UPDATE_ACL_MISMATCH: "
                    f"{table_name}.{column_name} expected={expected_update} actual={app_update}"
                )
            if _column_privilege(connection, "erp_backup", table_name, column_name, "UPDATE"):
                raise SystemExit(
                    f"CURRENT_0028_BACKUP_COLUMN_UPDATE_ACL_MISMATCH: {table_name}.{column_name}"
                )

    _verify_w3_column_attacl_entries(connection)

    for table_name in _SEQUENCE_TABLES:
        sequence_name = f"erp.{table_name}_id_seq"
        if (
            _sequence_privileges(connection, "erp_app", sequence_name)
            != ERP_APP_SEQUENCE_PRIVILEGES
        ):
            raise SystemExit(f"CURRENT_0028_APP_SEQUENCE_ACL_MISMATCH: {sequence_name}")
        if (
            _sequence_privileges(connection, "erp_backup", sequence_name)
            != ERP_BACKUP_SEQUENCE_PRIVILEGES
        ):
            raise SystemExit(f"CURRENT_0028_BACKUP_SEQUENCE_ACL_MISMATCH: {sequence_name}")
    _verify_identity_sequence_acl_entries(connection)
    _verify_shared_schema_acl(connection)


def _replication_setting_values(items: object) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        return [items]
    if isinstance(items, Iterable) and not isinstance(items, (bytes, bytearray)):
        return [str(item) for item in items]
    return [str(items)]


def _non_origin_replication_settings(items: object) -> list[str]:
    found: list[str] = []
    for item in _replication_setting_values(items):
        if not item.startswith("session_replication_role="):
            continue
        value = item.split("=", 1)[1]
        if value != "origin":
            found.append(item)
    return found


def _verify_session_replication_origin(connection: Connection) -> None:
    replication_role = connection.scalar(text("SHOW session_replication_role"))
    if str(replication_role) != "origin":
        raise SystemExit(
            f"CURRENT_0028_REPLICATION_ROLE_MISMATCH: expected=origin actual={replication_role!r}"
        )


def _verify_runtime_roles(connection: Connection) -> None:
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT role_row.rolname,
                       role_row.rolsuper,
                       role_row.rolcreaterole,
                       role_row.rolcreatedb,
                       role_row.rolreplication,
                       role_row.rolbypassrls,
                       role_row.rolcanlogin,
                       role_row.rolinherit
                  FROM pg_roles AS role_row
                 WHERE role_row.rolname = ANY(:roles)
                """
            ),
            {"roles": list(REQUIRED_RUNTIME_ROLES)},
        ).mappings()
    ]
    actual = {str(row["rolname"]): row for row in fetched}
    missing = sorted(set(REQUIRED_RUNTIME_ROLES) - set(actual))
    extra = sorted(set(actual) - set(REQUIRED_RUNTIME_ROLES))
    if missing or extra or len(fetched) != len(REQUIRED_RUNTIME_ROLES):
        raise SystemExit(
            "CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH: "
            f"cardinality_expected={len(REQUIRED_RUNTIME_ROLES)} "
            f"cardinality_actual={len(fetched)} missing={missing} extra={extra}"
        )
    attribute_failures: dict[str, object] = {}
    for role_name in REQUIRED_RUNTIME_ROLES:
        row = actual[role_name]
        observed = {attribute: bool(row[attribute]) for attribute in EXPECTED_ROLE_ATTRIBUTES}
        if observed != EXPECTED_ROLE_ATTRIBUTES:
            attribute_failures[role_name] = {
                "expected": EXPECTED_ROLE_ATTRIBUTES,
                "actual": observed,
            }
    if attribute_failures:
        raise SystemExit(f"CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH: {attribute_failures}")

    has_set_paths = [
        (str(row["source_role"]), str(row["target_role"]))
        for row in connection.execute(
            text(
                """
                SELECT source_role.rolname AS source_role,
                       target_role.rolname AS target_role
                  FROM pg_roles AS source_role
                  JOIN pg_roles AS target_role
                    ON target_role.oid <> source_role.oid
                 WHERE source_role.rolname = ANY(:sources)
                   AND pg_has_role(source_role.oid, target_role.oid, 'SET')
                """
            ),
            {"sources": list(SET_ROLE_SOURCE_ROLES)},
        ).mappings()
    ]
    membership_paths = [
        (str(row["source_role"]), str(row["target_role"]))
        for row in connection.execute(
            text(
                """
                WITH RECURSIVE set_edges AS (
                    SELECT member_role.rolname AS source_role,
                           granted_role.rolname AS target_role,
                           ARRAY[member_role.oid, granted_role.oid] AS walk
                      FROM pg_auth_members AS membership_row
                      JOIN pg_roles AS member_role
                        ON member_role.oid = membership_row.member
                      JOIN pg_roles AS granted_role
                        ON granted_role.oid = membership_row.roleid
                     WHERE member_role.rolname = ANY(:sources)
                       AND membership_row.set_option
                       AND granted_role.oid <> member_role.oid
                    UNION ALL
                    SELECT set_edges.source_role,
                           granted_role.rolname,
                           set_edges.walk || granted_role.oid
                      FROM set_edges
                      JOIN pg_roles AS intermediate_role
                        ON intermediate_role.rolname = set_edges.target_role
                      JOIN pg_auth_members AS membership_row
                        ON membership_row.member = intermediate_role.oid
                      JOIN pg_roles AS granted_role
                        ON granted_role.oid = membership_row.roleid
                     WHERE membership_row.set_option
                       AND NOT granted_role.oid = ANY (set_edges.walk)
                )
                SELECT DISTINCT source_role, target_role
                  FROM set_edges
                """
            ),
            {"sources": list(SET_ROLE_SOURCE_ROLES)},
        ).mappings()
    ]
    if has_set_paths or membership_paths:
        raise SystemExit(
            "CURRENT_0028_SET_ROLE_PATH: "
            f"pg_has_role={sorted(set(has_set_paths))} "
            f"membership={sorted(set(membership_paths))}"
        )

    raw_membership_edges = [
        (
            str(row["granted_role"]),
            str(row["member_role"]),
            bool(row["admin_option"]),
            bool(row["inherit_option"]),
            bool(row["set_option"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT granted_role.rolname AS granted_role,
                       member_role.rolname AS member_role,
                       raw_membership_row.admin_option,
                       raw_membership_row.inherit_option,
                       raw_membership_row.set_option
                  FROM pg_auth_members AS raw_membership_row
                  JOIN pg_roles AS granted_role
                    ON granted_role.oid = raw_membership_row.roleid
                  JOIN pg_roles AS member_role
                    ON member_role.oid = raw_membership_row.member
                 WHERE granted_role.rolname = ANY(:roles)
                    OR member_role.rolname = ANY(:roles)
                """
            ),
            {"roles": list(REQUIRED_RUNTIME_ROLES)},
        ).mappings()
    ]
    if raw_membership_edges:
        raise SystemExit(
            "CURRENT_0028_RAW_ROLE_MEMBERSHIP: "
            f"granted_role,member_role,admin,inherit,set={sorted(set(raw_membership_edges))}"
        )


def _verify_replication_parameter_and_defaults(connection: Connection) -> None:
    parameter_rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT role_name,
                       has_parameter_privilege(
                           role_name, 'session_replication_role', 'SET'
                       ) AS can_set
                  FROM (
                       SELECT unnest(
                           ARRAY['erp_app', 'erp_backup', 'public']
                       ) AS role_name
                  ) AS role_probe
                """
            )
        ).mappings()
    ]
    if len(parameter_rows) != 3:
        raise SystemExit(
            f"CURRENT_0028_REPLICATION_PARAMETER_SET: cardinality_actual={len(parameter_rows)}"
        )
    granted = [str(row["role_name"]) for row in parameter_rows if bool(row["can_set"])]
    if granted:
        raise SystemExit(f"CURRENT_0028_REPLICATION_PARAMETER_SET: {sorted(granted)}")

    role_defaults = [
        (str(row["rolname"]), _non_origin_replication_settings(row["rolconfig"]))
        for row in connection.execute(
            text(
                """
                SELECT role_row.rolname, role_row.rolconfig
                  FROM pg_roles AS role_row
                 WHERE role_row.rolname = ANY(:roles)
                """
            ),
            {"roles": list(REQUIRED_RUNTIME_ROLES)},
        ).mappings()
    ]
    setting_rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT COALESCE(database_row.datname, '') AS database_name,
                       COALESCE(role_row.rolname, '') AS role_name,
                       setting_row.setconfig
                  FROM pg_db_role_setting AS setting_row
                  LEFT JOIN pg_database AS database_row
                    ON database_row.oid = setting_row.setdatabase
                  LEFT JOIN pg_roles AS role_row
                    ON role_row.oid = setting_row.setrole
                 WHERE (
                         setting_row.setdatabase = 0
                         OR database_row.datname = current_database()
                       )
                   AND (
                         setting_row.setrole = 0
                         OR role_row.rolname = ANY(:roles)
                       )
                """
            ),
            {"roles": list(REQUIRED_RUNTIME_ROLES)},
        ).mappings()
    ]
    setting_defaults = [
        (
            str(row["database_name"]),
            str(row["role_name"]),
            _non_origin_replication_settings(row["setconfig"]),
        )
        for row in setting_rows
    ]
    forced = {
        "roles": [
            {"role": role_name, "settings": settings}
            for role_name, settings in role_defaults
            if settings
        ],
        "db_role_settings": [
            {"database": database_name, "role": role_name, "settings": settings}
            for database_name, role_name, settings in setting_defaults
            if settings
        ],
    }
    if forced["roles"] or forced["db_role_settings"]:
        raise SystemExit(f"CURRENT_0028_REPLICATION_DEFAULT: {forced}")


def _verify_fk_triggers_and_replication(connection: Connection) -> None:
    _verify_session_replication_origin(connection)
    _verify_replication_parameter_and_defaults(connection)

    trigger_rows = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT local_relation.relname AS table_name,
                       constraint_row.conname,
                       trigger_row.tgisinternal,
                       trigger_row.tgenabled,
                       trigger_row.tgrelid = constraint_row.conrelid AS tg_on_local,
                       trigger_row.tgrelid = constraint_row.confrelid AS tg_on_referenced,
                       trigger_row.tgconstrrelid = constraint_row.confrelid
                           AS constrrel_is_referenced,
                       trigger_row.tgconstrrelid = constraint_row.conrelid
                           AS constrrel_is_local,
                       trigger_row.tgconstraint = constraint_row.oid
                           AS tgconstraint_matches
                  FROM pg_constraint AS constraint_row
                  JOIN pg_class AS local_relation
                    ON local_relation.oid = constraint_row.conrelid
                  JOIN pg_namespace AS local_namespace
                    ON local_namespace.oid = local_relation.relnamespace
                  LEFT JOIN pg_trigger AS trigger_row
                    ON trigger_row.tgconstraint = constraint_row.oid
                 WHERE local_namespace.nspname = 'erp'
                   AND local_relation.relname = ANY(:tables)
                   AND constraint_row.contype = 'f'
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in trigger_rows:
        if row["tgisinternal"] is None:
            key = (str(row["table_name"]), str(row["conname"]))
            grouped.setdefault(key, [])
            continue
        key = (str(row["table_name"]), str(row["conname"]))
        grouped.setdefault(key, []).append(row)
    missing = sorted(set(EXPECTED_FOREIGN_KEYS) - set(grouped))
    extra = sorted(set(grouped) - set(EXPECTED_FOREIGN_KEYS))
    failures: dict[str, object] = {}
    if missing or extra:
        failures["names"] = {"missing": missing, "extra": extra}
    for key in EXPECTED_FOREIGN_KEYS:
        rows = grouped.get(key, [])
        label = f"{key[0]}.{key[1]}"
        if len(rows) != PG16_ORDINARY_FK_TRIGGER_COUNT:
            failures[label] = {"cardinality": len(rows), "expected": PG16_ORDINARY_FK_TRIGGER_COUNT}
            continue
        on_local = 0
        on_referenced = 0
        row_failures: list[dict[str, object]] = []
        for row in rows:
            local_ok = bool(row["tg_on_local"]) and bool(row["constrrel_is_referenced"])
            referenced_ok = bool(row["tg_on_referenced"]) and bool(row["constrrel_is_local"])
            observed = {
                "tgisinternal": bool(row["tgisinternal"]),
                "tgenabled": str(row["tgenabled"]),
                "tgconstraint_matches": bool(row["tgconstraint_matches"]),
                "local_ok": local_ok,
                "referenced_ok": referenced_ok,
            }
            if (
                not observed["tgisinternal"]
                or observed["tgenabled"] != "O"
                or not observed["tgconstraint_matches"]
                or local_ok == referenced_ok
            ):
                row_failures.append(observed)
                continue
            if local_ok:
                on_local += 1
            else:
                on_referenced += 1
        if row_failures or on_local != 2 or on_referenced != 2:
            failures[label] = {
                "on_local": on_local,
                "on_referenced": on_referenced,
                "invalid": row_failures,
            }
    if failures:
        raise SystemExit(f"CURRENT_0028_FK_TRIGGER_MISMATCH: {failures}")

    noninternal = [
        (str(row["table_name"]), str(row["tgname"]))
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname AS table_name,
                       trigger_row.tgname
                  FROM pg_trigger AS trigger_row
                  JOIN pg_class AS relation_row
                    ON relation_row.oid = trigger_row.tgrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname = ANY(:tables)
                   AND NOT trigger_row.tgisinternal
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    if noninternal:
        raise SystemExit(f"CURRENT_0028_NONINTERNAL_TRIGGER_PRESENT: {sorted(noninternal)}")


def _verify_relation_persistence(connection: Connection) -> None:
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname,
                       relation_row.relkind,
                       relation_row.relpersistence
                  FROM pg_class AS relation_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND (
                         (
                           relation_row.relkind = 'r'
                           AND relation_row.relname = ANY(:tables)
                         )
                         OR (
                           relation_row.relkind = 'S'
                           AND relation_row.relname = ANY(:sequences)
                         )
                       )
                """
            ),
            {
                "tables": list(REQUIRED_TABLES),
                "sequences": sorted(EXPECTED_IDENTITY_SEQUENCES),
            },
        ).mappings()
    ]
    expected_count = len(REQUIRED_TABLES) + len(EXPECTED_IDENTITY_SEQUENCES)
    actual = {str(row["relname"]): row for row in fetched}
    missing = sorted(set(EXPECTED_W3_RELATION_KINDS) - set(actual))
    extra = sorted(set(actual) - set(EXPECTED_W3_RELATION_KINDS))
    if missing or extra or len(fetched) != expected_count:
        raise SystemExit(
            "CURRENT_0028_PERSISTENCE_MISMATCH: "
            f"cardinality_expected={expected_count} cardinality_actual={len(fetched)} "
            f"missing={missing} extra={extra}"
        )
    failures: dict[str, object] = {}
    for name, expected_kind in sorted(EXPECTED_W3_RELATION_KINDS.items()):
        row = actual[name]
        observed = {
            "relkind": str(row["relkind"]),
            "relpersistence": str(row["relpersistence"]),
        }
        if observed["relkind"] != expected_kind or observed["relpersistence"] != "p":
            failures[name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0028_PERSISTENCE_MISMATCH: {failures}")


def _verify_identity_sequence_options(connection: Connection) -> None:
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT sequence_class.relname AS sequence_name,
                       sequence_row.seqtypid,
                       sequence_row.seqstart,
                       sequence_row.seqincrement,
                       sequence_row.seqmin,
                       sequence_row.seqmax,
                       sequence_row.seqcache,
                       sequence_row.seqcycle
                  FROM pg_sequence AS sequence_row
                  JOIN pg_class AS sequence_class
                    ON sequence_class.oid = sequence_row.seqrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = sequence_class.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND sequence_class.relkind = 'S'
                   AND sequence_class.relname = ANY(:sequences)
                """
            ),
            {"sequences": sorted(EXPECTED_IDENTITY_SEQUENCES)},
        ).mappings()
    ]
    actual = {str(row["sequence_name"]): row for row in fetched}
    missing = sorted(EXPECTED_IDENTITY_SEQUENCES - set(actual))
    extra = sorted(set(actual) - EXPECTED_IDENTITY_SEQUENCES)
    if missing or extra or len(fetched) != len(EXPECTED_IDENTITY_SEQUENCES):
        raise SystemExit(
            "CURRENT_0028_SEQUENCE_OPTION_MISMATCH: "
            f"cardinality_expected={len(EXPECTED_IDENTITY_SEQUENCES)} "
            f"cardinality_actual={len(fetched)} missing={missing} extra={extra}"
        )
    failures: dict[str, object] = {}
    for sequence_name in sorted(EXPECTED_IDENTITY_SEQUENCES):
        row = actual[sequence_name]
        observed = {
            "seqtypid": int(row["seqtypid"]),
            "seqstart": int(row["seqstart"]),
            "seqincrement": int(row["seqincrement"]),
            "seqmin": int(row["seqmin"]),
            "seqmax": int(row["seqmax"]),
            "seqcache": int(row["seqcache"]),
            "seqcycle": bool(row["seqcycle"]),
        }
        if observed != PG16_IDENTITY_SEQUENCE_OPTIONS:
            failures[sequence_name] = {
                "expected": PG16_IDENTITY_SEQUENCE_OPTIONS,
                "actual": observed,
            }
    if failures:
        raise SystemExit(f"CURRENT_0028_SEQUENCE_OPTION_MISMATCH: {failures}")


def _verify_rls_absent(connection: Connection) -> None:
    fetched = [
        dict(row)
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname,
                       relation_row.relrowsecurity,
                       relation_row.relforcerowsecurity
                  FROM pg_class AS relation_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relkind = 'r'
                   AND relation_row.relname = ANY(:tables)
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    actual = {str(row["relname"]): row for row in fetched}
    missing = sorted(REQUIRED_TABLES - set(actual))
    extra = sorted(set(actual) - REQUIRED_TABLES)
    if missing or extra or len(fetched) != len(REQUIRED_TABLES):
        raise SystemExit(
            "CURRENT_0028_RLS_PRESENT: "
            f"cardinality_expected={len(REQUIRED_TABLES)} "
            f"cardinality_actual={len(fetched)} missing={missing} extra={extra}"
        )
    flagged = {
        name: {
            "relrowsecurity": bool(row["relrowsecurity"]),
            "relforcerowsecurity": bool(row["relforcerowsecurity"]),
        }
        for name, row in actual.items()
        if bool(row["relrowsecurity"]) or bool(row["relforcerowsecurity"])
    }
    if flagged:
        raise SystemExit(f"CURRENT_0028_RLS_PRESENT: {flagged}")

    policies = [
        (str(row["table_name"]), str(row["polname"]))
        for row in connection.execute(
            text(
                """
                SELECT relation_row.relname AS table_name,
                       policy_row.polname
                  FROM pg_policy AS policy_row
                  JOIN pg_class AS relation_row
                    ON relation_row.oid = policy_row.polrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname = ANY(:tables)
                """
            ),
            {"tables": list(REQUIRED_TABLES)},
        ).mappings()
    ]
    if policies:
        raise SystemExit(f"CURRENT_0028_RLS_PRESENT: policies={sorted(policies)}")


def verify_current_0028(connection: Connection) -> None:
    _verify_revision(connection)
    _verify_session_replication_origin(connection)
    _verify_runtime_roles(connection)
    verify_current_0027(connection, skip_revision=True)
    _verify_tables(connection)
    _verify_relation_persistence(connection)
    _verify_columns(connection)
    _verify_no_bytea(connection)
    _verify_checks(connection)
    _verify_uniques(connection)
    _verify_active_partial_unique(connection)
    _verify_primary_keys(connection)
    _verify_explicit_indexes(connection)
    _verify_foreign_keys(connection)
    _verify_fk_triggers_and_replication(connection)
    _verify_identity_sequence_options(connection)
    _verify_rls_absent(connection)
    _verify_relation_owners(connection)
    _verify_acl(connection)


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("CURRENT_0028_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            verify_current_0028(connection)
    finally:
        engine.dispose()
    print(CURRENT_0028_MARKER)
    print(HEAD_MARKER)


if __name__ == "__main__":
    main()
