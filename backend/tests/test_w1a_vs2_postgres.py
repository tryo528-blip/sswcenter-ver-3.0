from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
APP_DATABASE_URL = os.environ.get("SSWCENTER_APP_DATABASE_URL")
BACKUP_DATABASE_URL = os.environ.get("SSWCENTER_BACKUP_DATABASE_URL")
VS2_REVISION = "20260727_0004_w1a_staff_qualifications"
EXPECTED_GROUPS = {
    "LONG_TERM_CARE": "장기요양",
    "LOCAL_CARE": "지역돌봄 연계",
    "BARO_CARE": "바로돌봄",
}
EXPECTED_SERVICES = {
    ("LONG_TERM_CARE", "HOME_CARE"): "방문요양",
    ("LONG_TERM_CARE", "HOME_BATH"): "방문목욕",
    ("LOCAL_CARE", "TEMP_HOME_CARE"): "일시재가",
    ("LOCAL_CARE", "HOSPITAL_ESCORT"): "병원동행",
    ("BARO_CARE", "BARO_CARE"): "바로돌봄",
}
EXPECTED_LICENSE_TYPES = {
    "CARE_WORKER": "요양보호사",
    "SOCIAL_WORKER": "사회복지사",
    "NURSE": "간호사",
}
FORBIDDEN_CATALOG_VALUES = {
    "CARE_WORKER_LEVEL",
    "SOCIAL_WORKER_LEVEL",
    "NURSING_ASSISTANT",
    "FACILITY_MANAGER",
}
VS2_TABLES = {
    "service_group",
    "service_type",
    "license_type",
    "staff_license",
    "staff_service_qualification_period",
}
CATALOG_TABLES = {"service_group", "service_type", "license_type"}
FACT_TABLES = {"staff_license", "staff_service_qualification_period"}


def _pg_required() -> None:
    if not DATABASE_URL:
        pytest.skip("W1A_VS2_PG_PREREQ_MISSING: SSWCENTER_DATABASE_URL")


@pytest.fixture(scope="module")
def owner_engine() -> Iterator[Engine]:
    _pg_required()
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def _require_vs2_revision_and_tables(engine: Engine) -> None:
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM erp.alembic_version")
        ).scalar_one_or_none()
        if revision != VS2_REVISION:
            pytest.fail("W1A_VS2_POSTGRES_MISSING: VS2 migration head is not applied")
        missing = {
            table
            for table in VS2_TABLES
            if connection.execute(
                text("SELECT to_regclass(:qualified) IS NOT NULL"),
                {"qualified": f"erp.{table}"},
            ).scalar()
            is not True
        }
        if missing:
            pytest.fail("W1A_VS2_POSTGRES_MISSING: VS2 tables are absent")


def _expect_integrity(
    connection: Connection,
    operation: Callable[[Connection], None],
    marker: str,
) -> None:
    try:
        with connection.begin_nested():
            operation(connection)
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    except IntegrityError:
        return
    except SQLAlchemyError:
        pytest.fail("W1A_VS2_HARNESS_FAILURE: unexpected SQL error during rejection probe")
    pytest.fail(marker)


def _insert_staff(connection: Connection, token: str) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO erp.staff
                    (name, birth_date, sex_code, phone, phone_normalized,
                     address, display_name, memo)
                VALUES (:name, :birth_date, 'TEST', NULL, NULL,
                        NULL, :display_name, 'VS2 synthetic fixture')
                RETURNING id
                """
            ),
            {
                "name": f"VS2 synthetic {token}",
                "birth_date": date(1990, 1, 1),
                "display_name": f"VS2 synthetic {token}",
            },
        ).scalar_one()
    )


def _insert_account(connection: Connection, staff_id: int, token: str) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO erp.user_account
                    (staff_id, account_code, display_name, role_code,
                     pin_hash, pin_lookup_hmac, pin_key_version)
                VALUES (:staff_id, :account_code, :display_name, 'ADMIN',
                        'VS2 synthetic hash', :pin_lookup_hmac, 1)
                RETURNING id
                """
            ),
            {
                "staff_id": staff_id,
                "account_code": f"vs2-synthetic-{token}",
                "display_name": f"VS2 synthetic actor {token}",
                "pin_lookup_hmac": f"vs2-synthetic-{token}".encode(),
            },
        ).scalar_one()
    )


def _insert_employment(
    connection: Connection,
    *,
    staff_id: int,
    account_id: int,
    token: str,
    employment_no: int,
    start_date: date,
    end_date: date | None,
) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO erp.staff_employment
                    (staff_id, employment_no, staff_no, staff_no_year,
                     staff_no_sequence, start_date, end_date,
                     created_by_account_id, updated_by_account_id)
                VALUES (:staff_id, :employment_no, :staff_no, 2099,
                        :staff_no_sequence, :start_date, :end_date,
                        :account_id, :account_id)
                RETURNING id
                """
            ),
            {
                "staff_id": staff_id,
                "employment_no": employment_no,
                "staff_no": f"VS2-SYNTH-{token}",
                "staff_no_sequence": abs(hash(token)) % 100000 + 1,
                "start_date": start_date,
                "end_date": end_date,
                "account_id": account_id,
            },
        ).scalar_one()
    )


def _insert_license(
    connection: Connection,
    *,
    staff_id: int,
    license_type_id: int,
    number: str,
    account_id: int,
    replacement_license_id: int | None = None,
    invalidated: bool = False,
) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO erp.staff_license
                    (staff_id, license_type_id, license_number, issued_date,
                     invalidated_at_utc, replacement_license_id,
                     created_by_account_id, updated_by_account_id, row_version)
                VALUES (:staff_id, :license_type_id, :license_number,
                        DATE '2026-01-01',
                        CASE WHEN :invalidated THEN TIMESTAMPTZ '2026-02-01 00:00:00+00'
                             ELSE NULL END,
                        :replacement_license_id, :account_id, :account_id, 1)
                RETURNING id
                """
            ),
            {
                "staff_id": staff_id,
                "license_type_id": license_type_id,
                "license_number": number,
                "invalidated": invalidated,
                "replacement_license_id": replacement_license_id,
                "account_id": account_id,
            },
        ).scalar_one()
    )


def _insert_qualification(
    connection: Connection,
    *,
    staff_id: int,
    employment_id: int,
    service_type_id: int,
    start_date: date,
    end_date: date | None,
    account_id: int,
    source_license_id: int | None = None,
) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO erp.staff_service_qualification_period
                    (staff_id, employment_id, service_type_id, start_date,
                     end_date, source_license_id, created_by_account_id,
                     updated_by_account_id, row_version)
                VALUES (:staff_id, :employment_id, :service_type_id,
                        :start_date, :end_date, :source_license_id,
                        :account_id, :account_id, 1)
                RETURNING id
                """
            ),
            {
                "staff_id": staff_id,
                "employment_id": employment_id,
                "service_type_id": service_type_id,
                "start_date": start_date,
                "end_date": end_date,
                "source_license_id": source_license_id,
                "account_id": account_id,
            },
        ).scalar_one()
    )


def _assert_fact_metadata(
    connection: Connection,
    *,
    table_name: str,
    fact_id: int,
    created_actor_id: int,
    updated_actor_id: int,
    minimum_row_version: int = 1,
) -> tuple[int, object]:
    row = connection.execute(
        text(
            f"SELECT created_by_account_id, updated_by_account_id, "
            f"created_at_utc, updated_at_utc, row_version "
            f"FROM erp.{table_name} WHERE id = :fact_id"
        ),
        {"fact_id": fact_id},
    ).one_or_none()
    if row is None or row.created_by_account_id != created_actor_id:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: fact created actor is not persisted")
    if row.updated_by_account_id != updated_actor_id:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: fact updated actor is not persisted")
    if (
        row.created_at_utc is None
        or row.updated_at_utc is None
        or row.created_at_utc.tzinfo is None
        or row.updated_at_utc.tzinfo is None
        or row.row_version < minimum_row_version
    ):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: fact UTC/version metadata is invalid")
    return row.row_version, row.updated_at_utc


def _insert_audit_event(
    connection: Connection,
    *,
    actor_id: int,
    entity_type: str,
    entity_id: int,
    action_code: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO erp.audit_event
                (occurred_at_utc, actor_account_id, actor_kind, action_code,
                 entity_type, entity_pk, before_json, after_json, created_from)
            VALUES (timezone('utc', now()), :actor_id, 'USER', :action_code,
                    :entity_type, :entity_id, '{}'::jsonb, '{}'::jsonb,
                    'VS2_SYNTHETIC_TEST')
            """
        ),
        {
            "actor_id": actor_id,
            "action_code": action_code,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    )


def test_postgres_revision_and_exact_catalog_seed(owner_engine: Engine) -> None:
    _require_vs2_revision_and_tables(owner_engine)
    try:
        with owner_engine.connect() as connection:
            groups = dict(
                connection.execute(text("SELECT code, display_name FROM erp.service_group")).all()
            )
            services = {
                (row.group_code, row.service_code): row.display_name
                for row in connection.execute(
                    text(
                        """
                        SELECT g.code AS group_code,
                               s.code AS service_code,
                               s.display_name
                        FROM erp.service_type AS s
                        JOIN erp.service_group AS g
                          ON g.id = s.service_group_id
                        """
                    )
                )
            }
            license_types = dict(
                connection.execute(text("SELECT code, display_name FROM erp.license_type")).all()
            )
            service_type_columns = {
                row.column_name
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'erp' AND table_name = 'service_type'
                        """
                    )
                )
            }
    except SQLAlchemyError:
        pytest.fail("W1A_VS2_HARNESS_FAILURE: exact catalog query failed")
    if groups != EXPECTED_GROUPS or services != EXPECTED_SERVICES:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: catalog is not exact 3-group/5-service")
    if license_types != EXPECTED_LICENSE_TYPES:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: license type seed is not exact 3-type")
    if "service_group_id" not in service_type_columns or "group_code" in service_type_columns:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: service_type group FK contract is absent")
    catalog_values = set(groups) | set(services) | set(license_types)
    catalog_labels = set(groups.values()) | set(services.values()) | set(license_types.values())
    if FORBIDDEN_CATALOG_VALUES.intersection(catalog_values) or any(
        "관리책임" in label for label in catalog_labels
    ):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: excluded catalog seed is present")


def test_postgres_duplicate_overlap_fk_and_deferred_guard_contract(
    owner_engine: Engine,
) -> None:
    _require_vs2_revision_and_tables(owner_engine)
    with owner_engine.connect() as connection:
        constraints = set(
            connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE connamespace = 'erp'::regnamespace
                    """
                )
            ).scalars()
        )
        triggers = {
            row.tgname: row
            for row in connection.execute(
                text(
                    """
                    SELECT tgname, tgdeferrable, tginitdeferred
                    FROM pg_trigger
                    WHERE tgrelid IN (
                        'erp.staff_service_qualification_period'::regclass,
                        'erp.staff_employment'::regclass
                    )
                      AND tgname IN (
                          'ct_staff_service_qualification_within_employment',
                          'ct_staff_employment_child_periods_reverse_guard'
                      )
                    """
                )
            )
        }
        definitions = set(
            connection.execute(
                text(
                    """
                    SELECT pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE connamespace = 'erp'::regnamespace
                    """
                )
            ).scalars()
        )
        index_rows = list(
            connection.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'erp' AND tablename = 'staff_license'
                    """
                )
            )
        )
    required_constraints = {
        "ex_staff_service_qualification_period",
        "ct_staff_service_qualification_within_employment",
        "ct_staff_employment_child_periods_reverse_guard",
    }
    if not required_constraints.issubset(constraints | set(triggers)):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: duplicate/overlap guard is absent")
    if not any(
        "source_license_id" in definition and "staff_id" in definition for definition in definitions
    ):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: same-staff source license FK is absent")
    if not any("DEFERRABLE" in definition.upper() for definition in definitions):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: deferrable parent/child guard is absent")
    if not triggers or not all(
        row.tgdeferrable and row.tginitdeferred for row in triggers.values()
    ):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: guard is not initially deferred")

    normalized_indexes = []
    for row in index_rows:
        normalized = re.sub(r"\s+", "", row.indexdef).lower()
        normalized = re.sub(
            r"where\(+invalidated_at_utcisnull\)+",
            "whereinvalidated_at_utcisnull",
            normalized,
        )
        normalized_indexes.append(normalized)
    if not any(
        row.indexname == "uq_staff_license_type_number_active"
        and "createuniqueindex" in definition
        and "(license_type_id,license_number)" in definition
        and "whereinvalidated_at_utcisnull" in definition
        for row, definition in zip(index_rows, normalized_indexes, strict=True)
    ):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: active license partial unique index is absent")
    if not any(
        row.indexname == "uq_staff_license_staff_id_id"
        and "createuniqueindex" in definition
        and "(staff_id,id)" in definition
        for row, definition in zip(index_rows, normalized_indexes, strict=True)
    ):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: same-staff license unique key is absent")


def test_postgres_license_and_qualification_columns_forbid_duplicate_facts(
    owner_engine: Engine,
) -> None:
    _require_vs2_revision_and_tables(owner_engine)
    with owner_engine.connect() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'erp'
                      AND table_name IN (
                          'staff_license',
                          'staff_service_qualification_period'
                      )
                    """
                )
            )
        )
        columns: dict[str, set[str]] = {}
        for row in rows:
            columns.setdefault(row.table_name, set()).add(row.column_name)
    license_columns = columns.get("staff_license", set())
    qualification_columns = columns.get("staff_service_qualification_period", set())
    if {"license_number", "issued_date"} - license_columns:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: license fact columns are absent")
    required_qualification_columns = {
        "staff_id",
        "employment_id",
        "service_type_id",
        "start_date",
        "end_date",
    }
    if required_qualification_columns - qualification_columns:
        pytest.fail("W1A_VS2_POSTGRES_MISSING: qualification period columns are absent")
    if {"license_number", "issued_date"}.intersection(qualification_columns):
        pytest.fail("W1A_VS2_POSTGRES_MISSING: qualification duplicates license facts")


def test_postgres_runtime_acl_is_least_privilege(owner_engine: Engine) -> None:
    _require_vs2_revision_and_tables(owner_engine)
    if not APP_DATABASE_URL or not BACKUP_DATABASE_URL:
        pytest.fail("W1A_VS2_PG_PREREQ_MISSING: app and backup role URLs")

    app_engine = create_engine(APP_DATABASE_URL, pool_pre_ping=True)
    backup_engine = create_engine(BACKUP_DATABASE_URL, pool_pre_ping=True)
    try:
        with app_engine.connect() as connection:
            for table in sorted(CATALOG_TABLES):
                select_ok, insert_ok, update_ok, delete_ok = connection.execute(
                    text(
                        "SELECT has_table_privilege(current_user, :table_name, 'SELECT'), "
                        "has_table_privilege(current_user, :table_name, 'INSERT'), "
                        "has_table_privilege(current_user, :table_name, 'UPDATE'), "
                        "has_table_privilege(current_user, :table_name, 'DELETE')"
                    ),
                    {"table_name": f"erp.{table}"},
                ).one()
                if not select_ok or insert_ok or update_ok or delete_ok:
                    pytest.fail("W1A_VS2_POSTGRES_MISSING: catalog ACL is not SELECT-only")
            for table in sorted(FACT_TABLES):
                select_ok, insert_ok, update_ok, delete_ok = connection.execute(
                    text(
                        "SELECT has_table_privilege(current_user, :table_name, 'SELECT'), "
                        "has_table_privilege(current_user, :table_name, 'INSERT'), "
                        "has_table_privilege(current_user, :table_name, 'UPDATE'), "
                        "has_table_privilege(current_user, :table_name, 'DELETE')"
                    ),
                    {"table_name": f"erp.{table}"},
                ).one()
                if not (select_ok and insert_ok and update_ok) or delete_ok:
                    pytest.fail("W1A_VS2_POSTGRES_MISSING: fact ACL is not write-without-delete")
        with backup_engine.connect() as connection:
            for table in sorted(VS2_TABLES):
                select_ok, insert_ok, update_ok, delete_ok = connection.execute(
                    text(
                        "SELECT has_table_privilege(current_user, :table_name, 'SELECT'), "
                        "has_table_privilege(current_user, :table_name, 'INSERT'), "
                        "has_table_privilege(current_user, :table_name, 'UPDATE'), "
                        "has_table_privilege(current_user, :table_name, 'DELETE')"
                    ),
                    {"table_name": f"erp.{table}"},
                ).one()
                if not select_ok or insert_ok or update_ok or delete_ok:
                    pytest.fail("W1A_VS2_POSTGRES_MISSING: backup ACL is not SELECT-only")
    finally:
        app_engine.dispose()
        backup_engine.dispose()


def test_postgres_actual_mutation_guards_and_rollback(owner_engine: Engine) -> None:
    _require_vs2_revision_and_tables(owner_engine)
    token = f"vs2-{uuid4().hex}"
    with owner_engine.begin() as connection:
        try:
            staff_a = _insert_staff(connection, f"{token}-a")
            staff_b = _insert_staff(connection, f"{token}-b")
            account_id = _insert_account(connection, staff_a, token)
            staff_b_account = _insert_account(connection, staff_b, f"{token}-b")
            type_ids = dict(connection.execute(text("SELECT code, id FROM erp.license_type")).all())
            service_ids = dict(
                connection.execute(
                    text(
                        """
                        SELECT s.code, s.id
                        FROM erp.service_type AS s
                        JOIN erp.service_group AS g ON g.id = s.service_group_id
                        """
                    )
                ).all()
            )
            employment_a = _insert_employment(
                connection,
                staff_id=staff_a,
                account_id=account_id,
                token=f"{token}-a",
                employment_no=1,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 6, 30),
            )
            license_ids = [
                _insert_license(
                    connection,
                    staff_id=staff_a,
                    license_type_id=type_ids[code],
                    number=f"VS2-{token}-{code}",
                    account_id=account_id,
                )
                for code in ("CARE_WORKER", "SOCIAL_WORKER", "NURSE")
            ]
            if len(license_ids) != 3:
                pytest.fail("W1A_VS2_POSTGRES_MISSING: three license rows were not stored")
            for license_id in license_ids:
                _assert_fact_metadata(
                    connection,
                    table_name="staff_license",
                    fact_id=license_id,
                    created_actor_id=account_id,
                    updated_actor_id=account_id,
                )

            _expect_integrity(
                connection,
                lambda conn: _insert_license(
                    conn,
                    staff_id=staff_a,
                    license_type_id=type_ids["CARE_WORKER"],
                    number=f"VS2-{token}-CARE_WORKER",
                    account_id=account_id,
                ),
                "W1A_VS2_POSTGRES_MISSING: active license duplicate was accepted",
            )
            _insert_license(
                connection,
                staff_id=staff_a,
                license_type_id=type_ids["CARE_WORKER"],
                number=f"VS2-{token}-CARE_WORKER",
                account_id=account_id,
                invalidated=True,
            )

            wrong_staff_license = _insert_license(
                connection,
                staff_id=staff_b,
                license_type_id=type_ids["NURSE"],
                number=f"VS2-{token}-WRONG-STAFF",
                account_id=staff_b_account,
            )
            service_codes = sorted(service_ids)
            valid_service = service_ids[service_codes[0]]
            alternate_service = service_ids[service_codes[1]]
            no_end_service = service_ids[service_codes[2]]
            employment_open = _insert_employment(
                connection,
                staff_id=staff_b,
                account_id=staff_b_account,
                token=f"{token}-open",
                employment_no=1,
                start_date=date(2026, 7, 1),
                end_date=None,
            )
            no_end_qualification = _insert_qualification(
                connection,
                staff_id=staff_b,
                employment_id=employment_open,
                service_type_id=no_end_service,
                start_date=date(2026, 7, 1),
                end_date=None,
                account_id=staff_b_account,
            )
            _assert_fact_metadata(
                connection,
                table_name="staff_service_qualification_period",
                fact_id=no_end_qualification,
                created_actor_id=staff_b_account,
                updated_actor_id=staff_b_account,
            )
            _insert_qualification(
                connection,
                staff_id=staff_a,
                employment_id=employment_a,
                service_type_id=alternate_service,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 3, 31),
                account_id=account_id,
            )
            _expect_integrity(
                connection,
                lambda conn: _insert_qualification(
                    conn,
                    staff_id=staff_a,
                    employment_id=employment_a,
                    service_type_id=valid_service,
                    start_date=date(2025, 12, 1),
                    end_date=date(2026, 1, 31),
                    account_id=account_id,
                    source_license_id=license_ids[0],
                ),
                "W1A_VS2_POSTGRES_MISSING: employment containment accepted an outside period",
            )
            qualification_id = _insert_qualification(
                connection,
                staff_id=staff_a,
                employment_id=employment_a,
                service_type_id=valid_service,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 6, 30),
                account_id=account_id,
                source_license_id=license_ids[0],
            )
            qualification_version, qualification_updated_at = _assert_fact_metadata(
                connection,
                table_name="staff_service_qualification_period",
                fact_id=qualification_id,
                created_actor_id=account_id,
                updated_actor_id=account_id,
            )
            _expect_integrity(
                connection,
                lambda conn: _insert_qualification(
                    conn,
                    staff_id=staff_a,
                    employment_id=employment_a,
                    service_type_id=valid_service,
                    start_date=date(2026, 5, 1),
                    end_date=date(2026, 6, 15),
                    account_id=account_id,
                    source_license_id=license_ids[0],
                ),
                "W1A_VS2_POSTGRES_MISSING: overlapping qualification was accepted",
            )
            _expect_integrity(
                connection,
                lambda conn: _insert_qualification(
                    conn,
                    staff_id=staff_a,
                    employment_id=employment_a,
                    service_type_id=valid_service,
                    start_date=date(2026, 5, 1),
                    end_date=date(2026, 6, 15),
                    account_id=account_id,
                    source_license_id=wrong_staff_license,
                ),
                "W1A_VS2_POSTGRES_MISSING: wrong-staff source license was accepted",
            )
            employment_rehire = _insert_employment(
                connection,
                staff_id=staff_a,
                account_id=account_id,
                token=f"{token}-rehire",
                employment_no=3,
                start_date=date(2027, 1, 1),
                end_date=date(2027, 12, 31),
            )
            _insert_qualification(
                connection,
                staff_id=staff_a,
                employment_id=employment_rehire,
                service_type_id=valid_service,
                start_date=date(2027, 1, 1),
                end_date=date(2027, 3, 31),
                account_id=account_id,
                source_license_id=license_ids[0],
            )
            _expect_integrity(
                connection,
                lambda conn: conn.execute(
                    text(
                        "UPDATE erp.staff_employment "
                        "SET end_date = DATE '2026-05-31' "
                        "WHERE id = :employment_id"
                    ),
                    {"employment_id": employment_a},
                ),
                "W1A_VS2_POSTGRES_MISSING: reverse employment guard was not enforced",
            )

            connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            connection.execute(
                text(
                    "UPDATE erp.staff_service_qualification_period "
                    "SET end_date = DATE '2026-12-31', "
                    "updated_by_account_id = :actor_id, "
                    "updated_at_utc = clock_timestamp(), "
                    "row_version = row_version + 1 "
                    "WHERE id = :qualification_id"
                ),
                {"actor_id": staff_b_account, "qualification_id": qualification_id},
            )
            connection.execute(
                text(
                    "UPDATE erp.staff_employment "
                    "SET end_date = DATE '2026-12-31', "
                    "updated_by_account_id = :actor_id, "
                    "updated_at_utc = clock_timestamp(), "
                    "row_version = row_version + 1 "
                    "WHERE id = :employment_id"
                ),
                {"actor_id": staff_b_account, "employment_id": employment_a},
            )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            updated_version, updated_at = _assert_fact_metadata(
                connection,
                table_name="staff_service_qualification_period",
                fact_id=qualification_id,
                created_actor_id=account_id,
                updated_actor_id=staff_b_account,
                minimum_row_version=qualification_version + 1,
            )
            if (
                updated_version != qualification_version + 1
                or updated_at <= qualification_updated_at
            ):
                pytest.fail("W1A_VS2_POSTGRES_MISSING: qualification version did not increase")

            original = connection.execute(
                text(
                    "SELECT invalidated_at_utc, replacement_license_id, row_version, "
                    "updated_at_utc FROM erp.staff_license WHERE id = :license_id"
                ),
                {"license_id": license_ids[0]},
            ).one()
            audit_before = connection.execute(
                text(
                    "SELECT count(*) FROM erp.audit_event "
                    "WHERE entity_type = 'STAFF_LICENSE' AND entity_pk = :license_id"
                ),
                {"license_id": license_ids[0]},
            ).scalar_one()
            rollback_number = f"VS2-{token}-REPLACEMENT-ROLLBACK"
            try:
                with connection.begin_nested():
                    candidate_id = _insert_license(
                        connection,
                        staff_id=staff_a,
                        license_type_id=type_ids["SOCIAL_WORKER"],
                        number=rollback_number,
                        account_id=staff_b_account,
                    )
                    connection.execute(
                        text(
                            "UPDATE erp.staff_license "
                            "SET invalidated_at_utc = clock_timestamp(), "
                            "replacement_license_id = :candidate_id, "
                            "updated_by_account_id = :actor_id, "
                            "updated_at_utc = clock_timestamp(), "
                            "row_version = row_version + 1 "
                            "WHERE id = :license_id"
                        ),
                        {
                            "candidate_id": candidate_id,
                            "actor_id": staff_b_account,
                            "license_id": license_ids[0],
                        },
                    )
                    _insert_audit_event(
                        connection,
                        actor_id=staff_b_account,
                        entity_type="STAFF_LICENSE",
                        entity_id=license_ids[0],
                        action_code="VS2_LICENSE_REPLACE",
                    )
                    connection.execute(text("SELECT CAST('VS2 rollback failure' AS integer)"))
            except DataError:
                pass
            else:
                pytest.fail("W1A_VS2_POSTGRES_MISSING: replacement failure did not rollback")
            restored = connection.execute(
                text(
                    "SELECT invalidated_at_utc, replacement_license_id, row_version, "
                    "updated_at_utc FROM erp.staff_license WHERE id = :license_id"
                ),
                {"license_id": license_ids[0]},
            ).one()
            rollback_count = connection.execute(
                text("SELECT count(*) FROM erp.staff_license WHERE license_number = :number"),
                {"number": rollback_number},
            ).scalar_one()
            audit_after_rollback = connection.execute(
                text(
                    "SELECT count(*) FROM erp.audit_event "
                    "WHERE entity_type = 'STAFF_LICENSE' AND entity_pk = :license_id"
                ),
                {"license_id": license_ids[0]},
            ).scalar_one()
            if restored != original or rollback_count != 0 or audit_after_rollback != audit_before:
                pytest.fail("W1A_VS2_POSTGRES_MISSING: replacement rollback was not exact")

            replacement_id = _insert_license(
                connection,
                staff_id=staff_a,
                license_type_id=type_ids["SOCIAL_WORKER"],
                number=f"VS2-{token}-REPLACEMENT",
                account_id=staff_b_account,
            )
            connection.execute(
                text(
                    "UPDATE erp.staff_license "
                    "SET invalidated_at_utc = clock_timestamp(), "
                    "replacement_license_id = :replacement_id, "
                    "updated_by_account_id = :actor_id, "
                    "updated_at_utc = clock_timestamp(), "
                    "row_version = row_version + 1 "
                    "WHERE id = :license_id"
                ),
                {
                    "replacement_id": replacement_id,
                    "actor_id": staff_b_account,
                    "license_id": license_ids[0],
                },
            )
            _insert_audit_event(
                connection,
                actor_id=staff_b_account,
                entity_type="STAFF_LICENSE",
                entity_id=license_ids[0],
                action_code="VS2_LICENSE_REPLACE",
            )
            replacement_version, replacement_updated_at = _assert_fact_metadata(
                connection,
                table_name="staff_license",
                fact_id=license_ids[0],
                created_actor_id=account_id,
                updated_actor_id=staff_b_account,
                minimum_row_version=original.row_version + 1,
            )
            if (
                replacement_version != original.row_version + 1
                or replacement_updated_at <= original.updated_at_utc
            ):
                pytest.fail("W1A_VS2_POSTGRES_MISSING: license version did not increase")
            audit = connection.execute(
                text(
                    "SELECT actor_account_id, occurred_at_utc FROM erp.audit_event "
                    "WHERE entity_type = 'STAFF_LICENSE' AND entity_pk = :license_id "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"license_id": license_ids[0]},
            ).one_or_none()
            if (
                audit is None
                or audit.actor_account_id != staff_b_account
                or audit.occurred_at_utc.tzinfo is None
            ):
                pytest.fail("W1A_VS2_POSTGRES_MISSING: replacement audit actor/time is absent")
        except IntegrityError:
            pytest.fail("W1A_VS2_HARNESS_FAILURE: valid synthetic SQL mutation failed")
        except SQLAlchemyError:
            pytest.fail("W1A_VS2_HARNESS_FAILURE: synthetic SQL mutation fixture failed")

    barrier = threading.Barrier(2)

    def concurrent_insert(parameters: tuple[int, int, int, str]) -> str:
        assert DATABASE_URL is not None
        staff_id, license_type_id, account_id, license_number = parameters
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    barrier.wait(timeout=5)
                    connection.execute(
                        text(
                            """
                            INSERT INTO erp.staff_license
                                (staff_id, license_type_id, license_number,
                                 issued_date, created_by_account_id,
                                 updated_by_account_id, row_version)
                            VALUES (:staff_id, :license_type_id, :license_number,
                                    DATE '2026-01-01', :account_id, :account_id, 1)
                            """
                        ),
                        {
                            "staff_id": staff_id,
                            "license_type_id": license_type_id,
                            "license_number": license_number,
                            "account_id": account_id,
                        },
                    )
                    transaction.commit()
                    return "committed"
                except IntegrityError:
                    transaction.rollback()
                    return "conflict"
                except (SQLAlchemyError, threading.BrokenBarrierError):
                    transaction.rollback()
                    return "error"
        finally:
            engine.dispose()

    concurrent_parameters = (
        staff_a,
        type_ids["NURSE"],
        account_id,
        f"VS2-{token}-CONCURRENT-ACTIVE",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(concurrent_insert, (concurrent_parameters,) * 2))
    if sorted(results) != ["committed", "conflict"]:
        pytest.fail("W1A_VS2_HARNESS_FAILURE: concurrent SQL operation did not complete")
