from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_account, get_db_session
from app.core.auth import CurrentAccount
from app.core.security import csrf_token_signature, generate_csrf_token, generate_session_token
from app.core.settings import get_settings
from app.db.session import build_session_factory, create_postgres_engine
from app.main import app

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
VS4_REVISION = "20260728_0006_w1a_staff_health_check"
FACT_PATH = "/api/v1/staff/{staff_id}/health-checks"
FACT_ITEM_PATH = f"{FACT_PATH}/{{health_check_id}}"
EMPLOYMENT_PATH = "/api/v1/staff/{staff_id}/employments"
REQUIREMENT_PATH = "/api/v1/staff/{staff_id}/health-check-requirements"
REQUIREMENT_ITEM_PATH = f"{REQUIREMENT_PATH}/{{requirement_id}}"
TABLES = {"staff_health_check", "staff_health_check_requirement"}


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
        yield engine
    finally:
        engine.dispose()


def _require_schema(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if revision != VS4_REVISION:
                pytest.fail(
                    "W1A_VS4_MIGRATION_MISSING: 0006 is not the applied revision", pytrace=False
                )
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'erp'
                      AND tablename IN ('staff_health_check', 'staff_health_check_requirement')
                    """
                    )
                )
                .scalars()
                .all()
            )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        pytest.fail("W1A_VS4_HARNESS_FAILURE: revision/table query failed", pytrace=False)
    if set(rows) != TABLES:
        pytest.fail("W1A_VS4_DB_SCHEMA_MISSING: health tables are absent", pytrace=False)


def _require_routes() -> None:
    try:
        paths = set(app.openapi().get("paths", {}))
    except Exception:
        pytest.fail("W1A_VS4_API_HARNESS_FAILURE: OpenAPI route inspection failed", pytrace=False)
    required = {
        FACT_PATH,
        FACT_ITEM_PATH,
        REQUIREMENT_PATH,
        REQUIREMENT_ITEM_PATH,
        f"{FACT_ITEM_PATH}/invalidate",
        f"{REQUIREMENT_ITEM_PATH}/invalidate",
    }
    if not required.issubset(paths):
        pytest.fail("W1A_VS4_API_MISSING: health routes are absent", pytrace=False)


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
                            NULL, :display_name, 'VS4 PostgreSQL synthetic fixture')
                    RETURNING id
                    """
                ),
                {"name": f"VS4 PG {label} {token}", "display_name": f"VS4 PG {label}"},
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
                            'VS4 synthetic hash', :hmac, 1)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": staff_id,
                    "code": f"vs4-pg-{label}-{token}",
                    "display_name": f"VS4 PG {label}",
                    "hmac": f"vs4-pg-{label}-{token}".encode(),
                },
            ).scalar_one()
        )
    return FixtureAccount(CurrentAccount(account_id, f"VS4 PG {label}", "ADMIN"), staff_id)


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


def _insert_requirement(
    engine: Engine,
    fixture: FixtureAccount,
    target_key: str,
    employment_id: int | None = None,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_health_check_requirement
                        (staff_id, employment_id, target_key, target_rule_version_code,
                         status, health_check_id, exempt_reason_text,
                         created_by_account_id, created_at_utc,
                         updated_by_account_id, updated_at_utc, row_version)
                    VALUES (:staff_id, :employment_id, :target_key, 'VS4-SYNTH-1',
                            'INCOMPLETE', NULL, NULL,
                            :account_id, timezone('utc', now()),
                            :account_id, timezone('utc', now()), 1)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "employment_id": employment_id,
                    "target_key": target_key,
                    "account_id": fixture.account.id,
                },
            ).scalar_one()
        )


def _insert_requirement_with_fact_direct(
    engine: Engine,
    fixture: FixtureAccount,
    target_key: str,
    health_check_id: int,
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_health_check_requirement
                        (staff_id, employment_id, target_key, target_rule_version_code,
                         status, health_check_id, exempt_reason_text,
                         created_by_account_id, created_at_utc,
                         updated_by_account_id, updated_at_utc, row_version)
                    VALUES (:staff_id, NULL, :target_key, 'VS4-SYNTH-DB-PROBE',
                            'COMPLETE', :health_check_id, NULL,
                            :account_id, timezone('utc', now()),
                            :account_id, timezone('utc', now()), 1)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "target_key": target_key,
                    "health_check_id": health_check_id,
                    "account_id": fixture.account.id,
                },
            ).scalar_one()
        )


def _snapshot(
    engine: Engine,
    table: str,
    row_id: int,
    marker: str,
) -> tuple[Any, ...]:
    if table == "staff_health_check":
        columns = """
            staff_id, employment_id, check_date, check_type_code, result_note,
            invalidated_at_utc, replacement_health_check_id,
            updated_by_account_id, updated_at_utc, row_version
        """
    elif table == "staff_health_check_requirement":
        columns = """
            staff_id, employment_id, target_key, target_rule_version_code, status,
            health_check_id, exempt_reason_text, invalidated_at_utc,
            replacement_health_check_requirement_id, updated_by_account_id,
            updated_at_utc, row_version
        """
    else:
        pytest.fail(f"W1A_VS4_HARNESS_FAILURE: unsupported snapshot table {table}", pytrace=False)
    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT {columns} FROM erp.{table} WHERE id = :row_id"),
            {"row_id": row_id},
        ).one_or_none()
    if row is None:
        pytest.fail(f"{marker}: product row disappeared", pytrace=False)
    return tuple(row)


def _audit_count(engine: Engine, row_id: int) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM erp.audit_event
                    WHERE entity_pk = :row_id
                      AND lower(entity_type) LIKE 'staff_health_check%'
                    """
                ),
                {"row_id": row_id},
            ).scalar_one()
        )


def _assert_unchanged(
    engine: Engine,
    table: str,
    row_id: int,
    before: tuple[Any, ...],
    audit_before: int,
    marker: str,
) -> None:
    after = _snapshot(engine, table, row_id, marker)
    audit_after = _audit_count(engine, row_id)
    if after != before or audit_after != audit_before:
        pytest.fail(f"{marker}: product row or audit changed after rejected request", pytrace=False)


def _expect_integrity(
    engine: Engine,
    operation: Any,
    marker: str,
) -> None:
    try:
        operation()
    except IntegrityError:
        return
    except SQLAlchemyError:
        pytest.fail(
            "W1A_VS4_HARNESS_FAILURE: unexpected SQL error in invariant probe",
            pytrace=False,
        )
    pytest.fail(marker, pytrace=False)


def _insert_fact_direct(
    engine: Engine,
    fixture: FixtureAccount,
    *,
    check_date: str,
    employment_id: int | None,
    check_type_code: str = "GENERAL",
) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_health_check
                        (staff_id, employment_id, check_date, check_type_code,
                         result_note, created_by_account_id, created_at_utc,
                         updated_by_account_id, updated_at_utc, row_version)
                    VALUES (:staff_id, :employment_id, :check_date, :check_type_code,
                            NULL, :account_id, timezone('utc', now()),
                            :account_id, timezone('utc', now()), 1)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "employment_id": employment_id,
                    "check_date": check_date,
                    "check_type_code": check_type_code,
                    "account_id": fixture.account.id,
                },
            ).scalar_one()
        )


def _install_audit_failure_trigger(engine: Engine) -> tuple[str, str]:
    suffix = uuid4().hex
    function_name = f"fn_vs4_audit_failure_{suffix}"
    trigger_name = f"trg_vs4_audit_failure_{suffix}"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE FUNCTION erp.{function_name}() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF lower(COALESCE(NEW.entity_type, '')) LIKE 'staff_health_check%' THEN
                        RAISE EXCEPTION 'VS4 synthetic audit insert failure';
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
            "W1A_VS4_HARNESS_FAILURE: temporary audit trigger cleanup failed", pytrace=False
        )


@pytest.fixture(autouse=True)
def reset_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_postgres_revision_shape_and_acl_contract(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    with owner_engine.connect() as connection:
        columns = {
            table: {
                row.column_name
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'erp' AND table_name = :table
                        """
                    ),
                    {"table": table},
                )
            }
            for table in TABLES
        }
    if "check_date" not in columns["staff_health_check"]:
        pytest.fail("W1A_VS4_DB_SCHEMA_MISSING: fact check_date is absent", pytrace=False)
    if "target_key" not in columns["staff_health_check_requirement"]:
        pytest.fail("W1A_VS4_DB_SCHEMA_MISSING: requirement target_key is absent", pytrace=False)


def test_postgres_same_date_fact_and_same_staff_links_use_real_api(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    _require_routes()
    fixture = _fixture_account(owner_engine, "fact")
    other = _fixture_account(owner_engine, "employment")
    client_account = fixture.account
    with _real_api(owner_engine, client_account) as client:
        payload = {"check_date": "2026-07-28", "check_type_code": "GENERAL"}
        first = client.post(
            FACT_PATH.format(staff_id=fixture.staff_id), json=payload, headers=_csrf_headers(client)
        )
        second = client.post(
            FACT_PATH.format(staff_id=fixture.staff_id), json=payload, headers=_csrf_headers(client)
        )
        if first.status_code // 100 != 2 or second.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: same-date facts are not both accepted", pytrace=False
            )
        if first.json().get("id") == second.json().get("id"):
            pytest.fail("W1A_VS4_POSTGRES_MISSING: same-date facts are not distinct", pytrace=False)
        employment = client.post(
            EMPLOYMENT_PATH.format(staff_id=other.staff_id),
            json={"start_date": "2026-01-01", "expected_staff_row_version": 1},
            headers=_csrf_headers(client),
        )
        if employment.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: employment fixture path is absent", pytrace=False
            )
        wrong_staff_employment = employment.json().get("id")
        mismatch = client.post(
            FACT_PATH.format(staff_id=fixture.staff_id),
            json={**payload, "employment_id": wrong_staff_employment},
            headers=_csrf_headers(client),
        )
        if mismatch.status_code not in {409, 422}:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: fact wrong-staff employment is not 409/422",
                pytrace=False,
            )
    first_fact_id = int(first.json()["id"])
    if (
        _snapshot(
            owner_engine,
            "staff_health_check",
            first_fact_id,
            "W1A_VS4_POSTGRES_MISSING: nullable fact employment",
        )[1]
        is not None
    ):
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: nullable fact employment was not preserved",
            pytrace=False,
        )
    _expect_integrity(
        owner_engine,
        lambda: _insert_fact_direct(
            owner_engine,
            fixture,
            check_date="2026-07-29",
            employment_id=int(wrong_staff_employment),
            check_type_code="WRONG_STAFF_DB_PROBE",
        ),
        "W1A_VS4_POSTGRES_MISSING: DB accepted wrong-staff fact employment",
    )


def test_postgres_fact_invalidation_audit_and_stale_rollback(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    _require_routes()
    fixture = _fixture_account(owner_engine, "invalidation")
    with _real_api(owner_engine, fixture.account) as client:
        created = client.post(
            FACT_PATH.format(staff_id=fixture.staff_id),
            json={"check_date": "2026-07-28", "check_type_code": "GENERAL"},
            headers=_csrf_headers(client),
        )
        if created.status_code // 100 != 2:
            pytest.fail("W1A_VS4_POSTGRES_MISSING: fact create path is absent", pytrace=False)
        fact_id = created.json().get("id")
        if not isinstance(fact_id, int):
            pytest.fail("W1A_VS4_POSTGRES_MISSING: fact id is absent", pytrace=False)
        invalidate_path = (
            f"{FACT_ITEM_PATH.format(staff_id=fixture.staff_id, health_check_id=fact_id)}"
            "/invalidate"
        )
        invalidated = client.post(
            invalidate_path,
            json={"expected_row_version": 1},
            headers=_csrf_headers(client),
        )
        if invalidated.status_code // 100 != 2:
            pytest.fail("W1A_VS4_POSTGRES_MISSING: fact invalidation path is absent", pytrace=False)
        invalidated_snapshot = _snapshot(
            owner_engine,
            "staff_health_check",
            fact_id,
            "W1A_VS4_POSTGRES_MISSING: fact invalidation",
        )
        if (
            invalidated_snapshot[5] is None
            or invalidated_snapshot[7] != fixture.account.id
            or invalidated_snapshot[8] is None
            or invalidated_snapshot[9] != 2
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: fact invalidation actor/UTC/version is absent",
                pytrace=False,
            )
        stale_before = invalidated_snapshot
        stale_audits = _audit_count(owner_engine, fact_id)
        stale = client.post(
            invalidate_path,
            json={"expected_row_version": 1},
            headers=_csrf_headers(client),
        )
        if stale.status_code != 409 or "ROW_VERSION_CONFLICT" not in stale.text:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: stale invalidation is not stable 409", pytrace=False
            )
    _assert_unchanged(
        owner_engine,
        "staff_health_check",
        fact_id,
        stale_before,
        stale_audits,
        "W1A_VS4_POSTGRES_MISSING: stale fact invalidation rollback",
    )
    with owner_engine.connect() as connection:
        audits = connection.execute(
            text(
                """
                SELECT action_code, entity_type, actor_account_id, occurred_at_utc,
                       before_json, after_json
                FROM erp.audit_event
                WHERE entity_pk = :id
                  AND lower(entity_type) = 'staff_health_check'
                ORDER BY id
                """
            ),
            {"id": fact_id},
        ).all()
    invalidate_audit = next(
        (audit for audit in audits if audit.action_code == "STAFF_HEALTH_CHECK_INVALIDATE"),
        None,
    )
    if invalidate_audit is None:
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: fact invalidate audit action is absent", pytrace=False
        )
    if (
        invalidate_audit.entity_type != "STAFF_HEALTH_CHECK"
        or invalidate_audit.actor_account_id != fixture.account.id
        or invalidate_audit.occurred_at_utc is None
        or invalidate_audit.occurred_at_utc.tzinfo is None
        or not isinstance(invalidate_audit.before_json, dict)
        or not isinstance(invalidate_audit.after_json, dict)
        or invalidate_audit.before_json.get("invalidated_at_utc") is not None
        or invalidate_audit.before_json.get("row_version") != 1
        or invalidate_audit.after_json.get("invalidated_at_utc") is None
        or invalidate_audit.after_json.get("row_version") != 2
    ):
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: fact invalidate audit before/after is incomplete",
            pytrace=False,
        )

    with _real_api(owner_engine, fixture.account) as client:
        second = client.post(
            FACT_PATH.format(staff_id=fixture.staff_id),
            json={"check_date": "2026-07-29", "check_type_code": "GENERAL"},
            headers=_csrf_headers(client),
        )
        if second.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: fact rollback setup path is absent", pytrace=False
            )
        second_id = second.json().get("id")
        if not isinstance(second_id, int):
            pytest.fail("W1A_VS4_POSTGRES_MISSING: fact rollback id is absent", pytrace=False)
        before = _snapshot(
            owner_engine,
            "staff_health_check",
            second_id,
            "W1A_VS4_POSTGRES_MISSING: fact rollback setup",
        )
        before_audits = _audit_count(owner_engine, second_id)
        trigger_names = _install_audit_failure_trigger(owner_engine)
        try:
            failed_update = client.patch(
                FACT_ITEM_PATH.format(staff_id=fixture.staff_id, health_check_id=second_id),
                json={
                    "check_type_code": "AUDIT_FAILURE_UPDATE",
                    "result_note": "synthetic audit rollback",
                    "expected_row_version": 1,
                },
                headers=_csrf_headers(client),
            )
            if failed_update.status_code < 500:
                pytest.fail(
                    "W1A_VS4_POSTGRES_MISSING: audit failure did not reach fact mutation",
                    pytrace=False,
                )
        finally:
            _remove_audit_failure_trigger(owner_engine, trigger_names)
        _assert_unchanged(
            owner_engine,
            "staff_health_check",
            second_id,
            before,
            before_audits,
            "W1A_VS4_POSTGRES_MISSING: fact/audit failure rollback",
        )

    requirement_id = _insert_requirement(owner_engine, fixture, f"VS4-INVALIDATE-{uuid4().hex}")
    with _real_api(owner_engine, fixture.account) as client:
        requirement_path = REQUIREMENT_ITEM_PATH.format(
            staff_id=fixture.staff_id,
            requirement_id=requirement_id,
        )
        invalidated_requirement = client.post(
            f"{requirement_path}/invalidate",
            json={"expected_row_version": 1},
            headers=_csrf_headers(client),
        )
        if invalidated_requirement.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement invalidation path is absent",
                pytrace=False,
            )
        requirement_snapshot = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            requirement_id,
            "W1A_VS4_POSTGRES_MISSING: requirement invalidation",
        )
        replacement_id = requirement_snapshot[8]
        if (
            requirement_snapshot[7] is None
            or requirement_snapshot[9] != fixture.account.id
            or requirement_snapshot[10] is None
            or requirement_snapshot[11] != 2
            or not isinstance(replacement_id, int)
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement replacement/actor/UTC/version is absent",
                pytrace=False,
            )
        replacement_snapshot = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            replacement_id,
            "W1A_VS4_POSTGRES_MISSING: requirement replacement",
        )
        if (
            replacement_snapshot[0] != fixture.staff_id
            or replacement_snapshot[2] != requirement_snapshot[2]
            or replacement_snapshot[7] is not None
            or replacement_snapshot[4] != "INCOMPLETE"
            or replacement_snapshot[9] != fixture.account.id
            or replacement_snapshot[10] is None
            or replacement_snapshot[11] != 1
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement replacement row is not exact",
                pytrace=False,
            )
        invalidate_before = requirement_snapshot
        invalidate_audits = _audit_count(owner_engine, requirement_id)
        replacement_audits = _audit_count(owner_engine, replacement_id)
        stale_requirement = client.post(
            f"{requirement_path}/invalidate",
            json={"expected_row_version": 1},
            headers=_csrf_headers(client),
        )
        if (
            stale_requirement.status_code != 409
            or "ROW_VERSION_CONFLICT" not in stale_requirement.text
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: stale requirement invalidation is not stable 409",
                pytrace=False,
            )
        _assert_unchanged(
            owner_engine,
            "staff_health_check_requirement",
            requirement_id,
            invalidate_before,
            invalidate_audits,
            "W1A_VS4_POSTGRES_MISSING: stale requirement invalidation rollback",
        )
        _assert_unchanged(
            owner_engine,
            "staff_health_check_requirement",
            replacement_id,
            replacement_snapshot,
            replacement_audits,
            "W1A_VS4_POSTGRES_MISSING: stale requirement replacement rollback",
        )
    with owner_engine.connect() as connection:
        requirement_audits = connection.execute(
            text(
                """
                SELECT action_code, entity_type, actor_account_id, occurred_at_utc,
                       before_json, after_json
                FROM erp.audit_event
                WHERE entity_pk = :id
                  AND lower(entity_type) = 'staff_health_check_requirement'
                ORDER BY id
                """
            ),
            {"id": requirement_id},
        ).all()
    requirement_invalidate_audit = next(
        (
            audit
            for audit in requirement_audits
            if audit.action_code == "STAFF_HEALTH_CHECK_REQUIREMENT_INVALIDATE"
        ),
        None,
    )
    if requirement_invalidate_audit is None:
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: requirement invalidate audit action is absent",
            pytrace=False,
        )
    if (
        requirement_invalidate_audit.entity_type != "STAFF_HEALTH_CHECK_REQUIREMENT"
        or requirement_invalidate_audit.actor_account_id != fixture.account.id
        or requirement_invalidate_audit.occurred_at_utc is None
        or requirement_invalidate_audit.occurred_at_utc.tzinfo is None
        or not isinstance(requirement_invalidate_audit.before_json, dict)
        or not isinstance(requirement_invalidate_audit.after_json, dict)
        or requirement_invalidate_audit.before_json.get("status") != "INCOMPLETE"
        or requirement_invalidate_audit.before_json.get("row_version") != 1
        or requirement_invalidate_audit.after_json.get("invalidated_at_utc") is None
        or requirement_invalidate_audit.after_json.get("replacement_health_check_requirement_id")
        != replacement_id
        or requirement_invalidate_audit.after_json.get("row_version") != 2
    ):
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: requirement invalidate audit before/after is incomplete",
            pytrace=False,
        )

    rollback_requirement_id = _insert_requirement(
        owner_engine,
        fixture,
        f"VS4-REQUIREMENT-AUDIT-FAILURE-{uuid4().hex}",
    )
    with _real_api(owner_engine, fixture.account) as client:
        before = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            rollback_requirement_id,
            "W1A_VS4_POSTGRES_MISSING: requirement rollback setup",
        )
        before_audits = _audit_count(owner_engine, rollback_requirement_id)
        trigger_names = _install_audit_failure_trigger(owner_engine)
        try:
            failed_requirement_update = client.patch(
                REQUIREMENT_ITEM_PATH.format(
                    staff_id=fixture.staff_id,
                    requirement_id=rollback_requirement_id,
                ),
                json={
                    "status": "EXEMPT",
                    "health_check_id": None,
                    "exempt_reason_text": "synthetic audit rollback",
                    "expected_row_version": 1,
                },
                headers=_csrf_headers(client),
            )
            if failed_requirement_update.status_code < 500:
                pytest.fail(
                    "W1A_VS4_POSTGRES_MISSING: audit failure did not reach requirement mutation",
                    pytrace=False,
                )
        finally:
            _remove_audit_failure_trigger(owner_engine, trigger_names)
        _assert_unchanged(
            owner_engine,
            "staff_health_check_requirement",
            rollback_requirement_id,
            before,
            before_audits,
            "W1A_VS4_POSTGRES_MISSING: requirement/audit failure rollback",
        )

    rollback_replacement_id = _insert_requirement(
        owner_engine,
        fixture,
        f"VS4-REPLACEMENT-AUDIT-FAILURE-{uuid4().hex}",
    )
    rollback_replacement_before = _snapshot(
        owner_engine,
        "staff_health_check_requirement",
        rollback_replacement_id,
        "W1A_VS4_POSTGRES_MISSING: replacement rollback setup",
    )
    rollback_replacement_audits = _audit_count(owner_engine, rollback_replacement_id)
    with owner_engine.connect() as connection:
        rollback_replacement_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM erp.staff_health_check_requirement
                    WHERE staff_id = :staff_id AND target_key = :target_key
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "target_key": rollback_replacement_before[2],
                },
            ).scalar_one()
        )
    with _real_api(owner_engine, fixture.account) as client:
        trigger_names = _install_audit_failure_trigger(owner_engine)
        try:
            invalidate_replacement_path = (
                REQUIREMENT_ITEM_PATH.format(
                    staff_id=fixture.staff_id,
                    requirement_id=rollback_replacement_id,
                )
                + "/invalidate"
            )
            failed_invalidation = client.post(
                invalidate_replacement_path,
                json={"expected_row_version": 1},
                headers=_csrf_headers(client),
            )
            if failed_invalidation.status_code < 500:
                pytest.fail(
                    "W1A_VS4_POSTGRES_MISSING: audit failure did not reach replacement mutation",
                    pytrace=False,
                )
        finally:
            _remove_audit_failure_trigger(owner_engine, trigger_names)
    _assert_unchanged(
        owner_engine,
        "staff_health_check_requirement",
        rollback_replacement_id,
        rollback_replacement_before,
        rollback_replacement_audits,
        "W1A_VS4_POSTGRES_MISSING: replacement invalidation rollback",
    )
    with owner_engine.connect() as connection:
        after_rollback_replacement_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM erp.staff_health_check_requirement
                    WHERE staff_id = :staff_id AND target_key = :target_key
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "target_key": rollback_replacement_before[2],
                },
            ).scalar_one()
        )
    if after_rollback_replacement_count != rollback_replacement_count:
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: replacement row was not rolled back exactly",
            pytrace=False,
        )


def test_postgres_requirement_truth_table_and_same_staff_fact(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    _require_routes()
    fixture = _fixture_account(owner_engine, "requirement")
    other = _fixture_account(owner_engine, "other")
    requirement_id = _insert_requirement(owner_engine, fixture, "VS4-TARGET-1")
    second_requirement_id = _insert_requirement(owner_engine, fixture, "VS4-TARGET-2")
    invalid_requirement_id = _insert_requirement(owner_engine, fixture, "VS4-TARGET-3")
    with _real_api(owner_engine, fixture.account) as client:
        other_employment = client.post(
            EMPLOYMENT_PATH.format(staff_id=other.staff_id),
            json={"start_date": "2026-01-01", "expected_staff_row_version": 1},
            headers=_csrf_headers(client),
        )
        if other_employment.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement employment fixture path is absent",
                pytrace=False,
            )
        other_employment_id = other_employment.json().get("id")
        if not isinstance(other_employment_id, int):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement employment fixture id is absent",
                pytrace=False,
            )
        _expect_integrity(
            owner_engine,
            lambda: _insert_requirement(
                owner_engine,
                fixture,
                f"VS4-WRONG-EMPLOYMENT-DB-{uuid4().hex}",
                employment_id=other_employment_id,
            ),
            "W1A_VS4_POSTGRES_MISSING: DB accepted wrong-staff requirement employment",
        )
        fact = client.post(
            FACT_PATH.format(staff_id=fixture.staff_id),
            json={"check_date": "2026-07-28"},
            headers=_csrf_headers(client),
        )
        other_fact = client.post(
            FACT_PATH.format(staff_id=other.staff_id),
            json={"check_date": "2026-07-28"},
            headers=_csrf_headers(client),
        )
        if fact.status_code // 100 != 2 or other_fact.status_code // 100 != 2:
            pytest.fail("W1A_VS4_POSTGRES_MISSING: fact setup path is absent", pytrace=False)
        fact_id = fact.json().get("id")
        other_fact_id = other_fact.json().get("id")
        path = REQUIREMENT_ITEM_PATH.format(
            staff_id=fixture.staff_id, requirement_id=requirement_id
        )
        if not isinstance(fact_id, int) or not isinstance(other_fact_id, int):
            pytest.fail("W1A_VS4_POSTGRES_MISSING: fact setup ids are absent", pytrace=False)
        _expect_integrity(
            owner_engine,
            lambda: _insert_requirement_with_fact_direct(
                owner_engine,
                fixture,
                f"VS4-WRONG-STAFF-DB-{uuid4().hex}",
                other_fact_id,
            ),
            "W1A_VS4_POSTGRES_MISSING: DB accepted wrong-staff requirement fact",
        )

        def assert_rejected_without_mutation(
            requirement_row_id: int,
            response: Any,
            expected_statuses: set[int],
            label: str,
        ) -> None:
            status_code = int(response.status_code)
            if status_code not in expected_statuses:
                pytest.fail(f"{label}: unexpected status", pytrace=False)
            _assert_unchanged(
                owner_engine,
                "staff_health_check_requirement",
                requirement_row_id,
                requirement_before,
                requirement_audits,
                label,
            )

        complete = client.patch(
            path,
            json={
                "status": "COMPLETE",
                "health_check_id": fact_id,
                "exempt_reason_text": None,
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if complete.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: COMPLETE truth-table path is absent", pytrace=False
            )
        complete_snapshot = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            requirement_id,
            "W1A_VS4_POSTGRES_MISSING: valid COMPLETE state",
        )
        if (
            complete_snapshot[4] != "COMPLETE"
            or complete_snapshot[5] != fact_id
            or complete_snapshot[6] is not None
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: COMPLETE fields were not exact",
                pytrace=False,
            )
        requirement_before = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            requirement_id,
            "W1A_VS4_POSTGRES_MISSING: requirement complete",
        )
        requirement_audits = _audit_count(owner_engine, requirement_id)
        wrong_staff = client.patch(
            path,
            json={
                "status": "COMPLETE",
                "health_check_id": other_fact_id,
                "expected_row_version": 2,
            },
            headers=_csrf_headers(client),
        )
        assert_rejected_without_mutation(
            requirement_id,
            wrong_staff,
            {409, 422},
            "W1A_VS4_POSTGRES_MISSING: requirement wrong-staff rollback",
        )
        exempt = client.patch(
            REQUIREMENT_ITEM_PATH.format(
                staff_id=fixture.staff_id, requirement_id=second_requirement_id
            ),
            json={
                "status": "EXEMPT",
                "health_check_id": None,
                "exempt_reason_text": "synthetic policy exemption",
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if exempt.status_code // 100 != 2:
            pytest.fail("W1A_VS4_POSTGRES_MISSING: valid EXEMPT state is absent", pytrace=False)
        exempt_snapshot = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            second_requirement_id,
            "W1A_VS4_POSTGRES_MISSING: valid EXEMPT state",
        )
        if (
            exempt_snapshot[4] != "EXEMPT"
            or exempt_snapshot[5] is not None
            or exempt_snapshot[6] != "synthetic policy exemption"
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: EXEMPT fields were not exact",
                pytrace=False,
            )
        incomplete = client.patch(
            REQUIREMENT_ITEM_PATH.format(
                staff_id=fixture.staff_id, requirement_id=second_requirement_id
            ),
            json={
                "status": "INCOMPLETE",
                "health_check_id": None,
                "exempt_reason_text": None,
                "expected_row_version": 2,
            },
            headers=_csrf_headers(client),
        )
        if incomplete.status_code // 100 != 2:
            pytest.fail("W1A_VS4_POSTGRES_MISSING: valid INCOMPLETE state is absent", pytrace=False)
        second_snapshot = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            second_requirement_id,
            "W1A_VS4_POSTGRES_MISSING: valid INCOMPLETE state",
        )
        if (
            second_snapshot[4] != "INCOMPLETE"
            or second_snapshot[5] is not None
            or second_snapshot[6] is not None
        ):
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: INCOMPLETE fields were not exact",
                pytrace=False,
            )
        requirement_before = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            invalid_requirement_id,
            "W1A_VS4_POSTGRES_MISSING: invalid requirement setup",
        )
        requirement_audits = _audit_count(owner_engine, invalid_requirement_id)
        invalid_complete = client.patch(
            REQUIREMENT_ITEM_PATH.format(
                staff_id=fixture.staff_id, requirement_id=invalid_requirement_id
            ),
            json={
                "status": "COMPLETE",
                "health_check_id": None,
                "exempt_reason_text": None,
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        assert_rejected_without_mutation(
            invalid_requirement_id,
            invalid_complete,
            {422},
            "W1A_VS4_POSTGRES_MISSING: COMPLETE without fact rollback",
        )
        invalid_incomplete = client.patch(
            REQUIREMENT_ITEM_PATH.format(
                staff_id=fixture.staff_id, requirement_id=invalid_requirement_id
            ),
            json={
                "status": "INCOMPLETE",
                "health_check_id": fact_id,
                "exempt_reason_text": None,
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        assert_rejected_without_mutation(
            invalid_requirement_id,
            invalid_incomplete,
            {422},
            "W1A_VS4_POSTGRES_MISSING: INCOMPLETE with fact rollback",
        )
        invalid_exempt = client.patch(
            REQUIREMENT_ITEM_PATH.format(
                staff_id=fixture.staff_id, requirement_id=invalid_requirement_id
            ),
            json={
                "status": "EXEMPT",
                "health_check_id": None,
                "exempt_reason_text": "",
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        assert_rejected_without_mutation(
            invalid_requirement_id,
            invalid_exempt,
            {422},
            "W1A_VS4_POSTGRES_MISSING: EXEMPT blank reason rollback",
        )


def test_postgres_active_target_duplicate_race_and_stale_update(owner_engine: Engine) -> None:
    _require_schema(owner_engine)
    _require_routes()
    fixture = _fixture_account(owner_engine, "race")
    target_key = f"VS4-RACE-{uuid4().hex}"

    def insert_once() -> str:
        try:
            _insert_requirement(owner_engine, fixture, target_key)
            return "success"
        except IntegrityError:
            return "integrity_error"
        except SQLAlchemyError:
            return "unexpected_error"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: insert_once(), range(2)))
    if "unexpected_error" in outcomes:
        pytest.fail(
            "W1A_VS4_HARNESS_FAILURE: unexpected SQL error in duplicate race", pytrace=False
        )
    if sorted(outcomes) != ["integrity_error", "success"]:
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: active target duplicate race is not "
            "one-success-one-conflict",
            pytrace=False,
        )
    with owner_engine.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT count(*) FROM erp.staff_health_check_requirement
                WHERE staff_id = :staff_id AND target_key = :target_key
                  AND invalidated_at_utc IS NULL
                """
            ),
            {"staff_id": fixture.staff_id, "target_key": target_key},
        ).scalar_one()
    if count != 1:
        pytest.fail(
            "W1A_VS4_POSTGRES_MISSING: duplicate race did not leave exactly one active row",
            pytrace=False,
        )

    stale_requirement_id = _insert_requirement(
        owner_engine,
        fixture,
        f"VS4-STALE-{uuid4().hex}",
    )
    with _real_api(owner_engine, fixture.account) as client:
        requirement_path = REQUIREMENT_ITEM_PATH.format(
            staff_id=fixture.staff_id,
            requirement_id=stale_requirement_id,
        )
        winner = client.patch(
            requirement_path,
            json={
                "status": "EXEMPT",
                "health_check_id": None,
                "exempt_reason_text": "synthetic stale-version winner",
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if winner.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement update winner path is absent",
                pytrace=False,
            )
        before = _snapshot(
            owner_engine,
            "staff_health_check_requirement",
            stale_requirement_id,
            "W1A_VS4_POSTGRES_MISSING: stale requirement winner",
        )
        before_audits = _audit_count(owner_engine, stale_requirement_id)
        stale = client.patch(
            requirement_path,
            json={
                "status": "INCOMPLETE",
                "health_check_id": None,
                "exempt_reason_text": None,
                "expected_row_version": 1,
            },
            headers=_csrf_headers(client),
        )
        if stale.status_code != 409 or "ROW_VERSION_CONFLICT" not in stale.text:
            pytest.fail(
                "W1A_VS4_POSTGRES_MISSING: requirement stale update is not stable 409",
                pytrace=False,
            )
        _assert_unchanged(
            owner_engine,
            "staff_health_check_requirement",
            stale_requirement_id,
            before,
            before_audits,
            "W1A_VS4_POSTGRES_MISSING: requirement stale update rollback",
        )
