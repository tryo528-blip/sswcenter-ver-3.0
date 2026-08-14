from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.session import create_postgres_engine

WAVE0_REVISION = "20260724_0002"
WAVE0_PERMISSION_COUNT = 4

EXPECTED_TABLES = {
    "access_event",
    "account_permission",
    "alembic_version",
    "audit_event",
    "auth_event",
    "auth_rate_limit_bucket",
    "auth_session",
    "business_number_counter",
    "center",
    "installation_state",
    "permission_definition",
    "staff",
    "staff_employment",
    "staff_operational_role_period",
    "staff_position_period",
    "system_run",
    "system_run_event",
    "user_account",
}


@dataclass(frozen=True)
class ConstraintShape:
    table_schema: str
    table_name: str
    constraint_type: str
    columns: tuple[str, ...]
    referenced_schema: str = ""
    referenced_table: str = ""
    referenced_columns: tuple[str, ...] = ()
    match_type: str = " "
    update_action: str = " "
    delete_action: str = " "
    access_method: str = ""
    index_keys: tuple[str, ...] = ()
    index_collations: tuple[str, ...] = ()
    index_operator_classes: tuple[str, ...] = ()
    index_options: tuple[str, ...] = ()
    included_columns: tuple[str, ...] = ()
    index_is_unique: bool = False
    index_is_valid: bool = False
    index_is_ready: bool = False
    index_is_primary: bool = False
    index_is_exclusion: bool = False
    index_nulls_not_distinct: bool = False
    exclusion_operators: tuple[str, ...] = ()
    expression: str = ""
    predicate: str = ""
    is_deferrable: bool = False
    is_initially_deferred: bool = False
    is_validated: bool = True
    is_no_inherit: bool = False


@dataclass(frozen=True)
class IndexShape:
    table_schema: str
    table_name: str
    keys: tuple[str, ...]
    included_columns: tuple[str, ...]
    predicate: str
    access_method: str = "btree"
    is_unique: bool = True
    is_valid: bool = True
    is_ready: bool = True
    is_primary: bool = False
    is_exclusion: bool = False
    nulls_not_distinct: bool = False


EXPECTED_CONSTRAINT_SHAPES = {
    "ck_installation_state_ck_installation_state_singleton_key_true": ConstraintShape(
        table_schema="erp",
        table_name="installation_state",
        constraint_type="c",
        columns=("singleton_key",),
        expression="singleton_key",
    ),
    "ex_staff_employment_period": ConstraintShape(
        table_schema="erp",
        table_name="staff_employment",
        constraint_type="x",
        columns=("staff_id", "employment_period"),
        access_method="gist",
        index_keys=("staff_id", "employment_period"),
        index_collations=("", ""),
        index_operator_classes=("public.gist_int8_ops", "pg_catalog.range_ops"),
        index_options=("0", "0"),
        index_is_valid=True,
        index_is_ready=True,
        index_is_exclusion=True,
        exclusion_operators=(
            "pg_catalog.=(bigint,bigint)",
            "pg_catalog.&&(anyrange,anyrange)",
        ),
        predicate="invalidated_at_utc IS NULL",
        is_no_inherit=True,
    ),
    "ex_staff_operational_role_period": ConstraintShape(
        table_schema="erp",
        table_name="staff_operational_role_period",
        constraint_type="x",
        columns=("staff_id", "role_code", "role_period"),
        access_method="gist",
        index_keys=("staff_id", "role_code", "role_period"),
        index_collations=("", "pg_catalog.default", ""),
        index_operator_classes=(
            "public.gist_int8_ops",
            "public.gist_text_ops",
            "pg_catalog.range_ops",
        ),
        index_options=("0", "0", "0"),
        index_is_valid=True,
        index_is_ready=True,
        index_is_exclusion=True,
        exclusion_operators=(
            "pg_catalog.=(bigint,bigint)",
            "pg_catalog.=(text,text)",
            "pg_catalog.&&(anyrange,anyrange)",
        ),
        predicate="invalidated_at_utc IS NULL",
        is_no_inherit=True,
    ),
    "ex_staff_position_period": ConstraintShape(
        table_schema="erp",
        table_name="staff_position_period",
        constraint_type="x",
        columns=("staff_id", "position_period"),
        access_method="gist",
        index_keys=("staff_id", "position_period"),
        index_collations=("", ""),
        index_operator_classes=("public.gist_int8_ops", "pg_catalog.range_ops"),
        index_options=("0", "0"),
        index_is_valid=True,
        index_is_ready=True,
        index_is_exclusion=True,
        exclusion_operators=(
            "pg_catalog.=(bigint,bigint)",
            "pg_catalog.&&(anyrange,anyrange)",
        ),
        predicate="invalidated_at_utc IS NULL",
        is_no_inherit=True,
    ),
    "fk_installation_state_first_admin_account_id_user_account": ConstraintShape(
        table_schema="erp",
        table_name="installation_state",
        constraint_type="f",
        columns=("first_admin_account_id",),
        referenced_schema="erp",
        referenced_table="user_account",
        referenced_columns=("id",),
        match_type="s",
        update_action="a",
        delete_action="r",
        is_no_inherit=True,
    ),
}

EXPECTED_INDEX_SHAPES = {
    "uq_account_permission_active": IndexShape(
        table_schema="erp",
        table_name="account_permission",
        keys=("account_id", "permission_code"),
        included_columns=(),
        predicate="revoked_at_utc IS NULL",
    ),
    "uq_center_single_active": IndexShape(
        table_schema="erp",
        table_name="center",
        keys=("true",),
        included_columns=(),
        predicate="active",
    ),
    "uq_system_run_idempotency": IndexShape(
        table_schema="erp",
        table_name="system_run",
        keys=("run_type", "idempotency_key"),
        included_columns=(),
        predicate="idempotency_key IS NOT NULL",
    ),
}

EXPECTED_CONSTRAINTS = set(EXPECTED_CONSTRAINT_SHAPES)
EXPECTED_INDEXES = set(EXPECTED_INDEX_SHAPES)

_DOLLAR_QUOTE_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _collapse_sql_whitespace(value: object) -> str:
    if value is None:
        return ""

    source = str(value).strip()
    output: list[str] = []
    pending_space = False
    quote: str | None = None
    dollar_tag: str | None = None
    index = 0

    while index < len(source):
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                output.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                output.append(source[index])
                index += 1
            continue

        character = source[index]
        if quote is not None:
            output.append(character)
            if character == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    output.append(quote)
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in {"'", '"'}:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            quote = character
            output.append(character)
            index += 1
            continue

        if character == "$":
            match = _DOLLAR_QUOTE_RE.match(source, index)
            if match is not None:
                if pending_space and output:
                    output.append(" ")
                pending_space = False
                dollar_tag = match.group(0)
                output.append(dollar_tag)
                index = match.end()
                continue

        if character.isspace():
            pending_space = True
            index += 1
            continue

        if pending_space and output:
            output.append(" ")
        pending_space = False
        output.append(character)
        index += 1

    return "".join(output).strip()


def _has_single_outer_parentheses(source: str) -> bool:
    if len(source) < 2 or source[0] != "(" or source[-1] != ")":
        return False

    depth = 0
    quote: str | None = None
    dollar_tag: str | None = None
    index = 0
    while index < len(source):
        if dollar_tag is not None:
            if source.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue

        character = source[index]
        if quote is not None:
            if character == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in {"'", '"'}:
            quote = character
            index += 1
            continue

        if character == "$":
            match = _DOLLAR_QUOTE_RE.match(source, index)
            if match is not None:
                dollar_tag = match.group(0)
                index = match.end()
                continue

        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0 or (depth == 0 and index != len(source) - 1):
                return False
        index += 1

    return depth == 0 and quote is None and dollar_tag is None


def _canonical_sql(value: object) -> str:
    canonical = _collapse_sql_whitespace(value)
    while _has_single_outer_parentheses(canonical):
        canonical = canonical[1:-1].strip()
    return canonical


def _text_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise SystemExit(f"Unexpected Wave 0 catalog field type: {field}")
    return tuple(value)


def _rows_by_expected_scope(
    rows: Sequence[Mapping[str, object]],
    *,
    name_field: str,
    expected_scopes: Mapping[str, tuple[str, str]],
) -> dict[str, Mapping[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        name = str(row[name_field])
        expected_scope = expected_scopes.get(name)
        if expected_scope is None:
            continue
        actual_scope = (str(row["table_schema"]), str(row["table_name"]))
        if actual_scope != expected_scope:
            continue
        grouped.setdefault(name, []).append(row)

    duplicates = sorted(name for name, matches in grouped.items() if len(matches) != 1)
    if duplicates:
        raise SystemExit(f"Duplicate Wave 0 catalog objects: {duplicates}")
    return {name: matches[0] for name, matches in grouped.items()}


def _verify_constraint_shapes(rows: Sequence[Mapping[str, object]]) -> None:
    by_name = _rows_by_expected_scope(
        rows,
        name_field="constraint_name",
        expected_scopes={
            name: (shape.table_schema, shape.table_name)
            for name, shape in EXPECTED_CONSTRAINT_SHAPES.items()
        },
    )
    missing = sorted(EXPECTED_CONSTRAINTS - by_name.keys())
    if missing:
        raise SystemExit(f"Missing Wave 0 constraints: {missing}")

    for name, expected in EXPECTED_CONSTRAINT_SHAPES.items():
        row = by_name[name]
        actual = ConstraintShape(
            table_schema=str(row["table_schema"]),
            table_name=str(row["table_name"]),
            constraint_type=str(row["constraint_type"]),
            columns=_text_tuple(row["columns"], field=f"{name}.columns"),
            referenced_schema=str(row["referenced_schema"] or ""),
            referenced_table=str(row["referenced_table"] or ""),
            referenced_columns=_text_tuple(
                row["referenced_columns"],
                field=f"{name}.referenced_columns",
            ),
            match_type=str(row["match_type"]),
            update_action=str(row["update_action"]),
            delete_action=str(row["delete_action"]),
            access_method=str(row["access_method"] or ""),
            index_keys=tuple(
                _canonical_sql(key)
                for key in _text_tuple(row["index_keys"], field=f"{name}.index_keys")
            ),
            index_collations=_text_tuple(
                row["index_collations"],
                field=f"{name}.index_collations",
            ),
            index_operator_classes=_text_tuple(
                row["index_operator_classes"],
                field=f"{name}.index_operator_classes",
            ),
            index_options=_text_tuple(
                row["index_options"],
                field=f"{name}.index_options",
            ),
            included_columns=tuple(
                _canonical_sql(column)
                for column in _text_tuple(
                    row["included_columns"],
                    field=f"{name}.included_columns",
                )
            ),
            index_is_unique=bool(row["index_is_unique"]),
            index_is_valid=bool(row["index_is_valid"]),
            index_is_ready=bool(row["index_is_ready"]),
            index_is_primary=bool(row["index_is_primary"]),
            index_is_exclusion=bool(row["index_is_exclusion"]),
            index_nulls_not_distinct=bool(row["index_nulls_not_distinct"]),
            exclusion_operators=_text_tuple(
                row["exclusion_operators"],
                field=f"{name}.exclusion_operators",
            ),
            expression=_canonical_sql(row["expression"]),
            predicate=_canonical_sql(row["predicate"]),
            is_deferrable=bool(row["is_deferrable"]),
            is_initially_deferred=bool(row["is_initially_deferred"]),
            is_validated=bool(row["is_validated"]),
            is_no_inherit=bool(row["is_no_inherit"]),
        )
        if actual != expected:
            raise SystemExit(
                f"Unexpected Wave 0 constraint definition: {name} "
                f"(actual={actual!r}, expected={expected!r})"
            )


def _verify_index_shapes(rows: Sequence[Mapping[str, object]]) -> None:
    by_name = _rows_by_expected_scope(
        rows,
        name_field="index_name",
        expected_scopes={
            name: (shape.table_schema, shape.table_name)
            for name, shape in EXPECTED_INDEX_SHAPES.items()
        },
    )
    missing = sorted(EXPECTED_INDEXES - by_name.keys())
    if missing:
        raise SystemExit(f"Missing Wave 0 indexes: {missing}")

    for name, expected in EXPECTED_INDEX_SHAPES.items():
        row = by_name[name]
        actual = IndexShape(
            table_schema=str(row["table_schema"]),
            table_name=str(row["table_name"]),
            keys=tuple(
                _canonical_sql(key)
                for key in _text_tuple(row["keys"], field=f"{name}.keys")
            ),
            included_columns=tuple(
                _canonical_sql(column)
                for column in _text_tuple(
                    row["included_columns"],
                    field=f"{name}.included_columns",
                )
            ),
            predicate=_canonical_sql(row["predicate"]),
            access_method=str(row["access_method"]),
            is_unique=bool(row["is_unique"]),
            is_valid=bool(row["is_valid"]),
            is_ready=bool(row["is_ready"]),
            is_primary=bool(row["is_primary"]),
            is_exclusion=bool(row["is_exclusion"]),
            nulls_not_distinct=bool(row["nulls_not_distinct"]),
        )
        if actual != expected:
            raise SystemExit(
                f"Unexpected Wave 0 index definition: {name} "
                f"(actual={actual!r}, expected={expected!r})"
            )


def verify_wave0_invariants(
    connection: Connection,
    *,
    expected_revision: str,
    expected_permission_count: int,
) -> None:
    database_name, server_port, search_path = connection.execute(
        text(
            """
            SELECT
                current_database(),
                inet_server_port(),
                current_setting('search_path')
            """
        )
    ).one()
    tables = set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'erp'")
        ).scalars()
    )
    missing_tables = sorted(EXPECTED_TABLES - tables)
    if missing_tables:
        raise SystemExit(
            "Missing Wave 0 tables "
            f"(database={database_name}, port={server_port}, "
            f"search_path={search_path}): {missing_tables}"
        )

    revision = connection.execute(text("SELECT version_num FROM erp.alembic_version")).scalar_one()
    if revision != expected_revision:
        raise SystemExit(f"Unexpected Alembic revision: {revision}")

    singleton_count, singleton_key_is_true = connection.execute(
        text(
            """
            SELECT count(*), coalesce(bool_and(singleton_key), false)
            FROM erp.installation_state
            """
        )
    ).one()
    if singleton_count != 1 or singleton_key_is_true is not True:
        raise SystemExit("installation_state singleton postcheck failed")

    extension_exists = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'btree_gist')")
    ).scalar_one()
    if not extension_exists:
        raise SystemExit("btree_gist extension is missing")

    constraint_rows = connection.execute(
        text(
            """
            SELECT
                constraint_record.conname AS constraint_name,
                namespace_record.nspname AS table_schema,
                table_record.relname AS table_name,
                constraint_record.contype AS constraint_type,
                constraint_record.condeferrable AS is_deferrable,
                constraint_record.condeferred AS is_initially_deferred,
                constraint_record.convalidated AS is_validated,
                constraint_record.connoinherit AS is_no_inherit,
                ARRAY(
                    SELECT attribute_record.attname
                    FROM unnest(constraint_record.conkey)
                        WITH ORDINALITY AS key_record(attnum, position)
                    JOIN pg_attribute attribute_record
                      ON attribute_record.attrelid = constraint_record.conrelid
                     AND attribute_record.attnum = key_record.attnum
                    ORDER BY key_record.position
                ) AS columns,
                coalesce(referenced_namespace.nspname, '') AS referenced_schema,
                coalesce(referenced_table.relname, '') AS referenced_table,
                ARRAY(
                    SELECT attribute_record.attname
                    FROM unnest(constraint_record.confkey)
                        WITH ORDINALITY AS key_record(attnum, position)
                    JOIN pg_attribute attribute_record
                      ON attribute_record.attrelid = constraint_record.confrelid
                     AND attribute_record.attnum = key_record.attnum
                    ORDER BY key_record.position
                ) AS referenced_columns,
                constraint_record.confmatchtype AS match_type,
                constraint_record.confupdtype AS update_action,
                constraint_record.confdeltype AS delete_action,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(access_method.amname, '')
                    ELSE ''
                END AS access_method,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN ARRAY(
                        SELECT pg_get_indexdef(
                            supporting_index.indexrelid,
                            key_position,
                            true
                        )
                        FROM generate_series(
                            1,
                            supporting_index.indnkeyatts
                        ) AS key_position
                        ORDER BY key_position
                    )
                    ELSE ARRAY[]::text[]
                END AS index_keys,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN ARRAY(
                        SELECT CASE
                            WHEN collation_record.oid IS NULL THEN ''
                            ELSE collation_namespace.nspname || '.' ||
                                 collation_record.collname
                        END
                        FROM unnest(supporting_index.indcollation)
                            WITH ORDINALITY AS collation_key(collation_oid, position)
                        LEFT JOIN pg_collation collation_record
                          ON collation_record.oid = collation_key.collation_oid
                        LEFT JOIN pg_namespace collation_namespace
                          ON collation_namespace.oid = collation_record.collnamespace
                        ORDER BY collation_key.position
                    )
                    ELSE ARRAY[]::text[]
                END AS index_collations,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN ARRAY(
                        SELECT operator_class_namespace.nspname || '.' ||
                               operator_class_record.opcname
                        FROM unnest(supporting_index.indclass)
                            WITH ORDINALITY AS operator_class_key(
                                operator_class_oid,
                                position
                            )
                        JOIN pg_opclass operator_class_record
                          ON operator_class_record.oid =
                             operator_class_key.operator_class_oid
                        JOIN pg_namespace operator_class_namespace
                          ON operator_class_namespace.oid =
                             operator_class_record.opcnamespace
                        ORDER BY operator_class_key.position
                    )
                    ELSE ARRAY[]::text[]
                END AS index_operator_classes,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN ARRAY(
                        SELECT option_value::text
                        FROM unnest(supporting_index.indoption)
                            WITH ORDINALITY AS option_key(option_value, position)
                        ORDER BY option_key.position
                    )
                    ELSE ARRAY[]::text[]
                END AS index_options,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN ARRAY(
                        SELECT pg_get_indexdef(
                            supporting_index.indexrelid,
                            include_position,
                            true
                        )
                        FROM generate_series(
                            supporting_index.indnkeyatts + 1,
                            supporting_index.indnatts
                        ) AS include_position
                        ORDER BY include_position
                    )
                    ELSE ARRAY[]::text[]
                END AS included_columns,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(supporting_index.indisunique, false)
                    ELSE false
                END AS index_is_unique,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(supporting_index.indisvalid, false)
                    ELSE false
                END AS index_is_valid,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(supporting_index.indisready, false)
                    ELSE false
                END AS index_is_ready,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(supporting_index.indisprimary, false)
                    ELSE false
                END AS index_is_primary,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(supporting_index.indisexclusion, false)
                    ELSE false
                END AS index_is_exclusion,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN coalesce(supporting_index.indnullsnotdistinct, false)
                    ELSE false
                END AS index_nulls_not_distinct,
                ARRAY(
                    SELECT
                        operator_namespace.nspname || '.' ||
                        operator_record.oprname || '(' ||
                        pg_catalog.format_type(operator_record.oprleft, NULL) || ',' ||
                        pg_catalog.format_type(operator_record.oprright, NULL) || ')'
                    FROM unnest(constraint_record.conexclop)
                        WITH ORDINALITY AS operator_key(operator_oid, position)
                    JOIN pg_operator operator_record
                      ON operator_record.oid = operator_key.operator_oid
                    JOIN pg_namespace operator_namespace
                      ON operator_namespace.oid = operator_record.oprnamespace
                    ORDER BY operator_key.position
                ) AS exclusion_operators,
                pg_get_expr(
                    constraint_record.conbin,
                    constraint_record.conrelid,
                    true
                ) AS expression,
                CASE
                    WHEN constraint_record.contype = 'x'
                    THEN pg_get_expr(
                        supporting_index.indpred,
                        supporting_index.indrelid,
                        true
                    )
                    ELSE NULL
                END AS predicate
            FROM pg_constraint constraint_record
            JOIN pg_class table_record
              ON table_record.oid = constraint_record.conrelid
            JOIN pg_namespace namespace_record
              ON namespace_record.oid = table_record.relnamespace
            LEFT JOIN pg_class referenced_table
              ON referenced_table.oid = constraint_record.confrelid
            LEFT JOIN pg_namespace referenced_namespace
              ON referenced_namespace.oid = referenced_table.relnamespace
            LEFT JOIN pg_index supporting_index
              ON supporting_index.indexrelid = constraint_record.conindid
            LEFT JOIN pg_class supporting_index_record
              ON supporting_index_record.oid = supporting_index.indexrelid
            LEFT JOIN pg_am access_method
              ON access_method.oid = supporting_index_record.relam
            WHERE namespace_record.nspname = 'erp'
            """
        )
    ).mappings().all()
    _verify_constraint_shapes(
        cast(Sequence[Mapping[str, object]], constraint_rows)
    )

    index_rows = connection.execute(
        text(
            """
            SELECT
                index_record.relname AS index_name,
                namespace_record.nspname AS table_schema,
                table_record.relname AS table_name,
                access_method.amname AS access_method,
                index_catalog.indisunique AS is_unique,
                index_catalog.indisvalid AS is_valid,
                index_catalog.indisready AS is_ready,
                index_catalog.indisprimary AS is_primary,
                index_catalog.indisexclusion AS is_exclusion,
                index_catalog.indnullsnotdistinct AS nulls_not_distinct,
                ARRAY(
                    SELECT pg_get_indexdef(
                        index_catalog.indexrelid,
                        key_position,
                        true
                    )
                    FROM generate_series(
                        1,
                        index_catalog.indnkeyatts
                    ) AS key_position
                    ORDER BY key_position
                ) AS keys,
                ARRAY(
                    SELECT pg_get_indexdef(
                        index_catalog.indexrelid,
                        include_position,
                        true
                    )
                    FROM generate_series(
                        index_catalog.indnkeyatts + 1,
                        index_catalog.indnatts
                    ) AS include_position
                    ORDER BY include_position
                ) AS included_columns,
                pg_get_expr(
                    index_catalog.indpred,
                    index_catalog.indrelid,
                    true
                ) AS predicate
            FROM pg_index index_catalog
            JOIN pg_class index_record
              ON index_record.oid = index_catalog.indexrelid
            JOIN pg_class table_record
              ON table_record.oid = index_catalog.indrelid
            JOIN pg_namespace namespace_record
              ON namespace_record.oid = index_record.relnamespace
            JOIN pg_am access_method
              ON access_method.oid = index_record.relam
            WHERE namespace_record.nspname = 'erp'
            """
        )
    ).mappings().all()
    _verify_index_shapes(cast(Sequence[Mapping[str, object]], index_rows))

    permission_count = connection.execute(
        text("SELECT count(*) FROM erp.permission_definition")
    ).scalar_one()
    if permission_count != expected_permission_count:
        raise SystemExit(
            "Unexpected permission seed count: "
            f"{permission_count} (expected {expected_permission_count})"
        )

    timezone = connection.execute(text("SHOW timezone")).scalar_one()
    if timezone != "UTC":
        raise SystemExit(f"Database session timezone is not UTC: {timezone}")


def run_postcheck(
    *,
    expected_revision: str = WAVE0_REVISION,
    expected_permission_count: int = WAVE0_PERMISSION_COUNT,
    success_marker: str = "WAVE0_DB_POSTCHECK_OK",
) -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("SSWCENTER_DATABASE_URL is required")

    engine = create_postgres_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            verify_wave0_invariants(
                connection,
                expected_revision=expected_revision,
                expected_permission_count=expected_permission_count,
            )
    finally:
        engine.dispose()

    print(success_marker)


def main() -> None:
    run_postcheck()


if __name__ == "__main__":
    main()
