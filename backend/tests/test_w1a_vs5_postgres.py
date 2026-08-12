from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_account, get_db_session
from app.core.auth import CurrentAccount
from app.core.security import csrf_token_signature, generate_csrf_token, generate_session_token
from app.core.settings import get_settings
from app.db.session import build_session_factory, create_postgres_engine
from app.main import app

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
VS5_REVISION = "20260728_0007_w1a_staff_quarterly_consultation"
TABLE_NAME = "staff_quarterly_consultation"
COLLECTION_PATH = "/api/v1/staff/{staff_id}/quarterly-consultations"
ITEM_PATH = f"{COLLECTION_PATH}/{{consultation_id}}"
INVALIDATE_PATH = f"{ITEM_PATH}/invalidate"


@dataclass(frozen=True)
class FixtureAccount:
    account: CurrentAccount
    staff_id: int


@pytest.fixture(scope="module")
def owner_engine() -> Iterator[Engine]:
    if not DATABASE_URL:
        pytest.skip("isolated PostgreSQL harness is required")
    engine = create_postgres_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield engine
    except Exception:
        pytest.fail("W1A_VS5_PG_HARNESS_FAILURE: database setup failed", pytrace=False)
    finally:
        engine.dispose()


def _require_schema(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if revision != VS5_REVISION:
                pytest.fail(
                    "W1A_VS5_MIGRATION_MISSING: 0007 is not the applied revision",
                    pytrace=False,
                )
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'erp'
                      AND tablename = :table_name
                    """
                    ),
                    {"table_name": TABLE_NAME},
                )
                .scalars()
                .all()
            )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        pytest.fail("W1A_VS5_PG_HARNESS_FAILURE: revision/table query failed", pytrace=False)
    if set(rows) != {TABLE_NAME}:
        pytest.fail("W1A_VS5_DB_SCHEMA_MISSING: consultation table is absent", pytrace=False)


def _require_routes() -> None:
    try:
        paths = app.openapi().get("paths", {})
    except Exception:
        pytest.fail("W1A_VS5_PG_HARNESS_FAILURE: OpenAPI route inspection failed", pytrace=False)
    if not isinstance(paths, dict):
        pytest.fail("W1A_VS5_PG_HARNESS_FAILURE: OpenAPI paths are not an object", pytrace=False)
    required = {
        COLLECTION_PATH: {"get", "post"},
        ITEM_PATH: {"patch"},
        INVALIDATE_PATH: {"post"},
    }
    if any(
        not isinstance(paths.get(path), dict) or not methods.issubset(paths[path])
        for path, methods in required.items()
    ):
        pytest.fail("W1A_VS5_API_MISSING: quarterly-consultation routes are absent", pytrace=False)


def _fixture_account(engine: Engine, label: str) -> FixtureAccount:
    token = uuid4().hex
    with engine.begin() as connection:
        staff_id = int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff
                        (name, birth_date, sex_code, phone, phone_normalized,
                         address, display_name, memo)
                    VALUES (:name, DATE '1990-01-01', 'TEST', NULL, NULL,
                            NULL, :display_name, 'VS5 PostgreSQL synthetic fixture')
                    RETURNING id
                    """
                ),
                {"name": f"VS5 PG {label} {token}", "display_name": f"VS5 PG {label}"},
            ).scalar_one()
        )
        account_id = int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.user_account
                        (staff_id, account_code, display_name, role_code,
                         pin_hash, pin_lookup_hmac, pin_key_version)
                    VALUES (:staff_id, :code, :display_name, 'ADMIN',
                            'VS5 synthetic hash', :hmac, 1)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": staff_id,
                    "code": f"vs5-pg-{label}-{token}",
                    "display_name": f"VS5 PG {label}",
                    "hmac": f"vs5-pg-{label}-{token}".encode(),
                },
            ).scalar_one()
        )
    return FixtureAccount(CurrentAccount(account_id, f"VS5 PG {label}", "ADMIN"), staff_id)


def _install(factory: sessionmaker[Session], account: CurrentAccount) -> None:
    def db_override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    app.dependency_overrides[get_current_account] = lambda account=account: account
    app.dependency_overrides[get_db_session] = db_override


def _csrf_headers(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    signature = csrf_token_signature(
        session_token, csrf_token, settings.secret_value("csrf_signing_key")
    )
    cookie = f"{csrf_token}.{signature}"
    client.cookies.set(settings.session_cookie_name, session_token)
    client.cookies.set(settings.csrf_cookie_name, cookie)
    return {settings.csrf_header_name: cookie}


@contextmanager
def _real_api(engine: Engine, account: CurrentAccount) -> Iterator[TestClient]:
    factory = build_session_factory(engine)
    _install(factory, account)
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def _safe_response(response: Any, marker: str) -> None:
    lowered = response.text.lower()
    if any(
        word in lowered
        for word in ("integrityerror", "sqlalchemy", "psycopg", "constraint", "traceback")
    ):
        pytest.fail(marker + ": raw database diagnostics leaked", pytrace=False)


def _insert_direct(
    engine: Engine,
    fixture: FixtureAccount,
    *,
    calendar_year: int,
    quarter_no: int,
    status: str,
    counseling_date: str | None = None,
    content: str | None = None,
    incomplete_reason_text: str | None = None,
    exempt_reason_text: str | None = None,
    row_version: int = 1,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    f"""
                    INSERT INTO erp.{TABLE_NAME}
                        (staff_id, calendar_year, quarter_no, status,
                         counseling_date, content, incomplete_reason_text,
                         exempt_reason_text, created_by_account_id, created_at_utc,
                         updated_by_account_id, updated_at_utc, row_version)
                    VALUES (:staff_id, :calendar_year, :quarter_no, :status,
                            :counseling_date, :content, :incomplete_reason_text,
                            :exempt_reason_text, :account_id, timezone('utc', now()),
                            :account_id, timezone('utc', now()), :row_version)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "calendar_year": calendar_year,
                    "quarter_no": quarter_no,
                    "status": status,
                    "counseling_date": counseling_date,
                    "content": content,
                    "incomplete_reason_text": incomplete_reason_text,
                    "exempt_reason_text": exempt_reason_text,
                    "account_id": fixture.account.id,
                    "row_version": row_version,
                },
            ).scalar_one()
        )


def _expect_integrity(engine: Engine, operation: Callable[[], object], marker: str) -> None:
    try:
        operation()
    except IntegrityError:
        return
    except SQLAlchemyError:
        pytest.fail(
            "W1A_VS5_PG_HARNESS_FAILURE: unexpected SQL error in invariant probe", pytrace=False
        )
    pytest.fail(marker, pytrace=False)


def _snapshot(engine: Engine, row_id: int, marker: str) -> tuple[Any, ...]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f"""
                SELECT staff_id, calendar_year, quarter_no, status,
                       counseling_date, content, incomplete_reason_text,
                       exempt_reason_text, invalidated_at_utc,
                       replacement_staff_quarterly_consultation_id,
                       updated_by_account_id, updated_at_utc, row_version
                FROM erp.{TABLE_NAME}
                WHERE id = :row_id
                """
            ),
            {"row_id": row_id},
        ).one_or_none()
    if row is None:
        pytest.fail(marker + ": product row disappeared", pytrace=False)
    return tuple(row)


def _active_count(engine: Engine, fixture: FixtureAccount, year: int, quarter: int) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    f"""
                    SELECT count(*) FROM erp.{TABLE_NAME}
                    WHERE staff_id = :staff_id
                      AND calendar_year = :calendar_year
                      AND quarter_no = :quarter_no
                      AND invalidated_at_utc IS NULL
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "calendar_year": year,
                    "quarter_no": quarter,
                },
            ).scalar_one()
        )


def _audit_actions(engine: Engine, row_id: int) -> list[str]:
    with engine.connect() as connection:
        return [
            str(value)
            for value in connection.execute(
                text(
                    """
                    SELECT action_code
                    FROM erp.audit_event
                    WHERE entity_type = 'STAFF_QUARTERLY_CONSULTATION'
                      AND entity_pk = :row_id
                    ORDER BY id
                    """
                ),
                {"row_id": row_id},
            ).scalars()
        ]


def _install_audit_failure_trigger(engine: Engine) -> tuple[str, str]:
    suffix = uuid4().hex
    function_name = f"fn_vs5_audit_failure_{suffix}"
    trigger_name = f"trg_vs5_audit_failure_{suffix}"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE FUNCTION erp.{function_name}() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF upper(COALESCE(NEW.entity_type, '')) =
                       'STAFF_QUARTERLY_CONSULTATION' THEN
                        RAISE EXCEPTION 'VS5 synthetic audit insert failure';
                    END IF;
                    RETURN NEW;
                END
                $$;
                CREATE TRIGGER {trigger_name}
                BEFORE INSERT ON erp.audit_event
                FOR EACH ROW EXECUTE FUNCTION erp.{function_name}();
                """
            )
        )
    return function_name, trigger_name


def _remove_audit_failure_trigger(engine: Engine, names: tuple[str, str]) -> None:
    function_name, trigger_name = names
    try:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON erp.audit_event"))
            connection.execute(text(f"DROP FUNCTION IF EXISTS erp.{function_name}()"))
    except SQLAlchemyError:
        pytest.fail(
            "W1A_VS5_PG_HARNESS_FAILURE: temporary audit trigger cleanup failed", pytrace=False
        )


@pytest.fixture(autouse=True)
def reset_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_postgres_revision_shape_truth_table_and_nonblank_constraints(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    with owner_engine.connect() as connection:
        column_rows = (
            connection.execute(
                text(
                    """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'erp' AND table_name = :table_name
                """
                ),
                {"table_name": TABLE_NAME},
            )
            .mappings()
            .all()
        )
        index_defs = (
            connection.execute(
                text(
                    """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = 'erp' AND tablename = :table_name
                """
                ),
                {"table_name": TABLE_NAME},
            )
            .scalars()
            .all()
        )
        constraint_defs = (
            connection.execute(
                text(
                    """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'erp.staff_quarterly_consultation'::regclass
                """
                )
            )
            .scalars()
            .all()
        )
        foreign_key_defs = (
            connection.execute(
                text(
                    """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'erp.staff_quarterly_consultation'::regclass
                  AND contype = 'f'
                """
                )
            )
            .scalars()
            .all()
        )
    columns = {str(row["column_name"]): row for row in column_rows}
    required = {
        "id",
        "staff_id",
        "calendar_year",
        "quarter_no",
        "status",
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    }
    missing = sorted(required - set(columns))
    if missing:
        pytest.fail(
            "W1A_VS5_DB_SCHEMA_MISSING: columns are absent: " + ",".join(missing), pytrace=False
        )
    for name in ("calendar_year", "quarter_no", "status", "row_version"):
        if columns[name]["is_nullable"] != "NO":
            pytest.fail(f"W1A_VS5_DB_SCHEMA_MISSING: {name} is nullable", pytrace=False)
    for name in (
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
    ):
        if columns[name]["is_nullable"] != "YES":
            pytest.fail(f"W1A_VS5_DB_SCHEMA_MISSING: {name} is not nullable", pytrace=False)
    lowered_indexes = [str(value).lower() for value in index_defs]
    if not any(
        "unique" in value
        and "staff_id, calendar_year, quarter_no" in value
        and "invalidated_at_utc" in value
        and "is null" in value
        for value in lowered_indexes
    ):
        pytest.fail(
            "W1A_VS5_ACTIVE_UNIQUE_MISSING: PostgreSQL active unique is absent", pytrace=False
        )
    lowered_constraints = [str(value).lower() for value in constraint_defs]
    if not any(
        "quarter_no" in value and "1" in value and "4" in value for value in lowered_constraints
    ):
        pytest.fail(
            "W1A_VS5_QUARTER_CHECK_MISSING: PostgreSQL quarter check is absent", pytrace=False
        )
    truth_text = " ".join(lowered_constraints)
    if "btrim" not in truth_text or not all(
        field in truth_text
        for field in ("counseling_date", "content", "incomplete_reason_text", "exempt_reason_text")
    ):
        pytest.fail(
            "W1A_VS5_TRUTH_TABLE_MISSING: PostgreSQL nonblank truth checks are absent",
            pytrace=False,
        )
    if not any(
        "foreign key (staff_id)" in str(value).lower() and "erp.staff" in str(value).lower()
        for value in foreign_key_defs
    ):
        pytest.fail("W1A_VS5_SAME_STAFF_FK_MISSING: staff foreign key is absent", pytrace=False)

    fixture = _fixture_account(owner_engine, "truth")
    _require_routes()
    with _real_api(owner_engine, fixture.account) as client:
        cases = (
            (
                "COMPLETE",
                2050,
                1,
                {
                    "counseling_date": "2026-07-28",
                    "content": "VS5 PostgreSQL complete synthetic content",
                    "incomplete_reason_text": None,
                    "exempt_reason_text": None,
                },
            ),
            (
                "INCOMPLETE",
                2050,
                2,
                {
                    "counseling_date": None,
                    "content": None,
                    "incomplete_reason_text": "VS5 PostgreSQL incomplete synthetic reason",
                    "exempt_reason_text": None,
                },
            ),
            (
                "EXEMPT",
                2050,
                3,
                {
                    "counseling_date": None,
                    "content": None,
                    "incomplete_reason_text": None,
                    "exempt_reason_text": "VS5 PostgreSQL exempt synthetic reason",
                },
            ),
        )
        row_ids: list[int] = []
        for status, year, quarter, fields in cases:
            response = client.post(
                COLLECTION_PATH.format(staff_id=fixture.staff_id),
                json={
                    "calendar_year": year,
                    "quarter_no": quarter,
                    "status": status,
                    **fields,
                },
                headers=_csrf_headers(client),
            )
            if response.status_code // 100 != 2:
                _safe_response(response, "W1A_VS5_POSTGRES_MISSING: valid status path failed")
                pytest.fail("W1A_VS5_POSTGRES_MISSING: valid status path is absent", pytrace=False)
            row_ids.append(int(response.json()["id"]))
        with owner_engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT status, counseling_date, content,
                           incomplete_reason_text, exempt_reason_text
                    FROM erp.{TABLE_NAME}
                    WHERE id IN :row_ids
                    ORDER BY id
                    """
                ).bindparams(bindparam("row_ids", expanding=True)),
                {"row_ids": row_ids},
            ).all()
        if [str(row[0]) for row in rows] != ["COMPLETE", "INCOMPLETE", "EXEMPT"]:
            pytest.fail(
                "W1A_VS5_TRUTH_TABLE_MISSING: valid status values were not stored exactly",
                pytrace=False,
            )
        if (
            rows[0][1] is None
            or rows[0][2] != "VS5 PostgreSQL complete synthetic content"
            or rows[0][3] is not None
            or rows[0][4] is not None
        ):
            pytest.fail("W1A_VS5_TRUTH_TABLE_MISSING: COMPLETE fields are not exact", pytrace=False)
        if (
            rows[1][1] is not None
            or rows[1][2] is not None
            or rows[1][3] != "VS5 PostgreSQL incomplete synthetic reason"
            or rows[1][4] is not None
        ):
            pytest.fail(
                "W1A_VS5_TRUTH_TABLE_MISSING: INCOMPLETE fields are not exact", pytrace=False
            )
        if (
            rows[2][1] is not None
            or rows[2][2] is not None
            or rows[2][3] is not None
            or rows[2][4] != "VS5 PostgreSQL exempt synthetic reason"
        ):
            pytest.fail("W1A_VS5_TRUTH_TABLE_MISSING: EXEMPT fields are not exact", pytrace=False)

    invalid_rows = (
        ("COMPLETE", None, None, None, None, 2060, 1, 1),
        ("COMPLETE", "2026-07-28", "   ", None, None, 2060, 2, 1),
        ("INCOMPLETE", None, None, "   ", None, 2060, 3, 1),
        ("INCOMPLETE", "2026-07-28", None, "VS5 invalid reason", None, 2060, 4, 1),
        ("INCOMPLETE", None, "VS5 invalid content", "VS5 invalid reason", None, 2061, 1, 1),
        ("EXEMPT", None, None, None, "   ", 2061, 2, 1),
        ("EXEMPT", "2026-07-28", "VS5 invalid content", None, "VS5 invalid reason", 2061, 3, 1),
        ("OTHER", None, None, None, None, 2061, 4, 1),
        ("INCOMPLETE", None, None, "VS5 invalid quarter", None, 2062, 0, 1),
        ("INCOMPLETE", None, None, "VS5 invalid version", None, 2062, 1, 0),
    )
    for status, date_value, content, incomplete, exempt, year, quarter, version in invalid_rows:
        probe_invalid = partial(
            _insert_direct,
            owner_engine,
            fixture,
            calendar_year=year,
            quarter_no=quarter,
            status=status,
            counseling_date=date_value,
            content=content,
            incomplete_reason_text=incomplete,
            exempt_reason_text=exempt,
            row_version=version,
        )
        _expect_integrity(
            owner_engine,
            probe_invalid,
            "W1A_VS5_TRUTH_TABLE_MISSING: invalid state was accepted by PostgreSQL",
        )
    _expect_integrity(
        owner_engine,
        lambda: _insert_direct(
            owner_engine,
            fixture,
            calendar_year=2050,
            quarter_no=1,
            status="INCOMPLETE",
            incomplete_reason_text="VS5 duplicate synthetic reason",
        ),
        "W1A_VS5_ACTIVE_UNIQUE_MISSING: active duplicate was accepted",
    )


def test_postgres_active_duplicate_race_and_stale_update(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    _require_routes()
    fixture = _fixture_account(owner_engine, "race")
    year, quarter = 2070, 1

    def insert_once() -> str:
        try:
            _insert_direct(
                owner_engine,
                fixture,
                calendar_year=year,
                quarter_no=quarter,
                status="INCOMPLETE",
                incomplete_reason_text="VS5 race synthetic reason",
            )
            return "success"
        except IntegrityError:
            return "integrity_error"
        except SQLAlchemyError:
            return "unexpected_sql_error"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: insert_once(), range(2)))
    if "unexpected_sql_error" in outcomes:
        pytest.fail(
            "W1A_VS5_PG_HARNESS_FAILURE: unexpected SQL error in duplicate race", pytrace=False
        )
    if sorted(outcomes) != ["integrity_error", "success"]:
        pytest.fail(
            "W1A_VS5_ACTIVE_UNIQUE_MISSING: race did not produce one success "
            "and one 409-equivalent conflict",
            pytrace=False,
        )
    if _active_count(owner_engine, fixture, year, quarter) != 1:
        pytest.fail(
            "W1A_VS5_ACTIVE_UNIQUE_MISSING: race left more than one active row", pytrace=False
        )

    stale_id = _insert_direct(
        owner_engine,
        fixture,
        calendar_year=2070,
        quarter_no=2,
        status="COMPLETE",
        counseling_date="2026-07-28",
        content="VS5 stale synthetic content",
    )
    with _real_api(owner_engine, fixture.account) as client:
        path = ITEM_PATH.format(staff_id=fixture.staff_id, consultation_id=stale_id)
        winner = client.patch(
            path,
            json={
                "status": "INCOMPLETE",
                "counseling_date": None,
                "content": None,
                "incomplete_reason_text": "VS5 stale winner reason",
                "exempt_reason_text": None,
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if winner.status_code // 100 != 2:
            _safe_response(winner, "W1A_VS5_POSTGRES_STALE_MISSING")
            pytest.fail(
                "W1A_VS5_POSTGRES_STALE_MISSING: winner update path is absent", pytrace=False
            )
        before = _snapshot(owner_engine, stale_id, "W1A_VS5_POSTGRES_STALE_MISSING")
        before_audits = _audit_actions(owner_engine, stale_id)
        stale = client.patch(
            path,
            json={
                "status": "EXEMPT",
                "counseling_date": None,
                "content": None,
                "incomplete_reason_text": None,
                "exempt_reason_text": "VS5 stale loser reason",
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if stale.status_code != 409:
            _safe_response(stale, "W1A_VS5_POSTGRES_STALE_MISSING")
            pytest.fail(
                "W1A_VS5_POSTGRES_STALE_MISSING: stale update is not stable 409", pytrace=False
            )
        _safe_response(stale, "W1A_VS5_POSTGRES_STALE_MISSING")
        if (
            _snapshot(owner_engine, stale_id, "W1A_VS5_POSTGRES_STALE_MISSING") != before
            or _audit_actions(owner_engine, stale_id) != before_audits
        ):
            pytest.fail(
                "W1A_VS5_POSTGRES_STALE_MISSING: stale request mutated row or audit", pytrace=False
            )


def test_postgres_replacement_audit_and_exact_audit_failure_rollback(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    _require_routes()
    fixture = _fixture_account(owner_engine, "audit")
    consultation_id = _insert_direct(
        owner_engine,
        fixture,
        calendar_year=2080,
        quarter_no=1,
        status="COMPLETE",
        counseling_date="2026-07-28",
        content="VS5 replacement synthetic content",
    )
    with _real_api(owner_engine, fixture.account) as client:
        path = ITEM_PATH.format(staff_id=fixture.staff_id, consultation_id=consultation_id)
        updated = client.patch(
            path,
            json={
                "status": "INCOMPLETE",
                "counseling_date": None,
                "content": None,
                "incomplete_reason_text": "VS5 update audit synthetic reason",
                "exempt_reason_text": None,
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if updated.status_code // 100 != 2:
            _safe_response(updated, "W1A_VS5_POSTGRES_AUDIT_MISSING")
            pytest.fail("W1A_VS5_POSTGRES_AUDIT_MISSING: update path is absent", pytrace=False)
        update_version = int(updated.json().get("row_version", 2))
        actions_after_update = _audit_actions(owner_engine, consultation_id)
        if "STAFF_QUARTERLY_CONSULTATION_UPDATE" not in actions_after_update:
            pytest.fail(
                "W1A_VS5_POSTGRES_AUDIT_MISSING: update audit action is absent", pytrace=False
            )
        replaced = client.post(
            f"{path}/invalidate",
            json={
                "status": "EXEMPT",
                "counseling_date": None,
                "content": None,
                "incomplete_reason_text": None,
                "exempt_reason_text": "VS5 replacement audit synthetic reason",
                "expected_row_version": update_version,
            },
            headers=_csrf_headers(client),
        )
        if replaced.status_code // 100 != 2:
            _safe_response(replaced, "W1A_VS5_POSTGRES_REPLACEMENT_MISSING")
            pytest.fail(
                "W1A_VS5_POSTGRES_REPLACEMENT_MISSING: replacement path is absent", pytrace=False
            )
    with owner_engine.connect() as connection:
        old_row = connection.execute(
            text(
                f"""
                SELECT invalidated_at_utc, replacement_staff_quarterly_consultation_id
                FROM erp.{TABLE_NAME} WHERE id = :row_id
                """
            ),
            {"row_id": consultation_id},
        ).one()
        replacement_row = connection.execute(
            text(
                f"""
                SELECT id, status, invalidated_at_utc, calendar_year, quarter_no,
                       counseling_date, content, incomplete_reason_text, exempt_reason_text
                FROM erp.{TABLE_NAME}
                WHERE staff_id = :staff_id AND calendar_year = 2080 AND quarter_no = 1
                  AND invalidated_at_utc IS NULL
                """
            ),
            {"staff_id": fixture.staff_id},
        ).one_or_none()
    if old_row[0] is None or old_row[1] is None or replacement_row is None:
        pytest.fail(
            "W1A_VS5_POSTGRES_REPLACEMENT_MISSING: old/replacement linkage is not exact",
            pytrace=False,
        )
    if (
        replacement_row[1] != "EXEMPT"
        or replacement_row[2] is not None
        or replacement_row[3:5] != (2080, 1)
        or replacement_row[5] is not None
        or replacement_row[6] is not None
        or replacement_row[7] is not None
        or replacement_row[8] != "VS5 replacement audit synthetic reason"
    ):
        pytest.fail(
            "W1A_VS5_POSTGRES_REPLACEMENT_MISSING: replacement truth is not exact", pytrace=False
        )
    replacement_id = int(replacement_row[0])
    actions = _audit_actions(owner_engine, consultation_id) + _audit_actions(
        owner_engine, replacement_id
    )
    if (
        "STAFF_QUARTERLY_CONSULTATION_INVALIDATE" not in actions
        or "STAFF_QUARTERLY_CONSULTATION_REPLACEMENT_CREATE" not in actions
    ):
        pytest.fail(
            "W1A_VS5_POSTGRES_AUDIT_MISSING: replacement requires two named audits", pytrace=False
        )

    rollback_id = _insert_direct(
        owner_engine,
        fixture,
        calendar_year=2080,
        quarter_no=2,
        status="COMPLETE",
        counseling_date="2026-07-28",
        content="VS5 rollback synthetic content",
    )
    before = _snapshot(owner_engine, rollback_id, "W1A_VS5_POSTGRES_ROLLBACK_MISSING")
    before_audits = _audit_actions(owner_engine, rollback_id)
    trigger_names = _install_audit_failure_trigger(owner_engine)
    try:
        with _real_api(owner_engine, fixture.account) as client:
            response = client.post(
                INVALIDATE_PATH.format(staff_id=fixture.staff_id, consultation_id=rollback_id),
                json={
                    "status": "INCOMPLETE",
                    "counseling_date": None,
                    "content": None,
                    "incomplete_reason_text": "VS5 rollback synthetic replacement",
                    "exempt_reason_text": None,
                    "expected_row_version": 1,
                },
                headers=_csrf_headers(client),
            )
            if not 500 <= response.status_code < 600:
                _safe_response(response, "W1A_VS5_POSTGRES_ROLLBACK_MISSING")
                pytest.fail(
                    "W1A_VS5_POSTGRES_ROLLBACK_MISSING: audit failure was not an internal failure",
                    pytrace=False,
                )
            _safe_response(response, "W1A_VS5_POSTGRES_ROLLBACK_MISSING")
    finally:
        _remove_audit_failure_trigger(owner_engine, trigger_names)
    if _snapshot(owner_engine, rollback_id, "W1A_VS5_POSTGRES_ROLLBACK_MISSING") != before:
        pytest.fail(
            "W1A_VS5_POSTGRES_ROLLBACK_MISSING: old row changed after audit failure", pytrace=False
        )
    if _audit_actions(owner_engine, rollback_id) != before_audits:
        pytest.fail(
            "W1A_VS5_POSTGRES_ROLLBACK_MISSING: audit row survived failed transaction",
            pytrace=False,
        )
    if _active_count(owner_engine, fixture, 2080, 2) != 1:
        pytest.fail(
            "W1A_VS5_POSTGRES_ROLLBACK_MISSING: replacement survived failed transaction",
            pytrace=False,
        )
