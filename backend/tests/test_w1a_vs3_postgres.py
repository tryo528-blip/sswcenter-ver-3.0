from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_account, get_db_session
from app.core.auth import CurrentAccount
from app.core.security import (
    csrf_token_signature,
    generate_csrf_token,
    generate_session_token,
)
from app.core.settings import get_settings
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.staff.schemas import (
    StaffEmploymentCloseRequest,
    StaffEmploymentCreateRequest,
)
from app.domains.staff.service import StaffService
from app.main import app

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
VS3_REVISION = "20260728_0005_w1a_staff_training"
EXPECTED_COURSES = (
    (1, "NEW_HIRE_ORIENTATION", "신규직원교육", "ON_HIRE"),
    (2, "ELDER_RIGHTS", "노인인권", "HALF_YEAR"),
    (3, "DISABLED_ABUSE", "장애인학대 신고의무자교육", "ANNUAL"),
    (4, "ELDER_ABUSE", "노인학대 신고의무자교육", "ANNUAL"),
    (5, "SEXUAL_HARASSMENT", "직장 내 성희롱 예방교육", "ANNUAL"),
    (6, "WORKPLACE_BULLYING", "직장 내 괴롭힘 예방교육", "ANNUAL"),
    (7, "PRIVACY", "개인정보보호교육", "ANNUAL"),
)
VS3_TABLES = {
    "training_course",
    "staff_onboarding_training",
    "staff_periodic_training_status",
}
COURSE_PATH = "/api/v1/staff/training-courses"
PERIODIC_PATH = "/api/v1/staff/{staff_id}/periodic-trainings"
PERIODIC_ITEM_PATH = f"{PERIODIC_PATH}/{{training_id}}"
PERIODIC_PAYLOAD = {
    "course_code": "ELDER_RIGHTS",
    "period_key": "2026-H1",
    "completed": False,
    "expected_row_version": 1,
}

pytestmark = pytest.mark.skipif(
    DATABASE_URL is None,
    reason="W1A_VS3_PG_PREREQ_MISSING: requires the isolated ephemeral PostgreSQL harness",
)


class _SyntheticRollback(RuntimeError):
    pass


def _require_vs3_schema(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if revision != VS3_REVISION:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: 0005 training migration is not applied",
                    pytrace=False,
                )
            missing = {
                table
                for table in VS3_TABLES
                if connection.execute(
                    text("SELECT to_regclass(:qualified) IS NOT NULL"),
                    {"qualified": f"erp.{table}"},
                ).scalar()
                is not True
            }
            if missing:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: training tables are absent",
                    pytrace=False,
                )
    except pytest.fail.Exception:
        raise
    except Exception:
        pytest.fail("W1A_VS3_HARNESS_FAILURE: revision/table query failed", pytrace=False)


@pytest.fixture(scope="module")
def owner_engine() -> Iterator[Engine]:
    assert DATABASE_URL is not None
    engine = create_postgres_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_staff(connection: Connection, token: str) -> int:
    return int(
        connection.execute(
            text(
                """
                INSERT INTO erp.staff
                    (name, birth_date, sex_code, phone, phone_normalized,
                     address, display_name, memo)
                VALUES (:name, DATE '1990-01-01', 'TEST', NULL, NULL,
                        NULL, :display_name, 'VS3 synthetic fixture')
                RETURNING id
                """
            ),
            {"name": f"VS3 synthetic {token}", "display_name": f"VS3 {token}"},
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
                        'VS3 synthetic hash', :pin_lookup_hmac, 1)
                RETURNING id
                """
            ),
            {
                "staff_id": staff_id,
                "account_code": f"vs3-synthetic-{token}",
                "display_name": f"VS3 synthetic actor {token}",
                "pin_lookup_hmac": f"vs3-synthetic-{token}".encode(),
            },
        ).scalar_one()
    )


def _service_factory(engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(engine)


def _service_create_employment(
    engine: Engine,
    *,
    staff_id: int,
    account_id: int,
    expected_staff_row_version: int,
    start_date: date,
) -> int:
    factory = _service_factory(engine)
    with factory() as database_session:
        service = StaffService(database_session, get_settings())
        response = service.create_employment(
            staff_id,
            StaffEmploymentCreateRequest(
                expected_staff_row_version=expected_staff_row_version,
                start_date=start_date,
            ),
            CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN"),
        )
        return int(response.id)


def _service_close_employment(
    engine: Engine,
    *,
    staff_id: int,
    employment_id: int,
    account_id: int,
    expected_row_version: int,
    end_date: date,
) -> None:
    factory = _service_factory(engine)
    with factory() as database_session:
        service = StaffService(database_session, get_settings())
        service.close_employment(
            staff_id,
            employment_id,
            StaffEmploymentCloseRequest(
                end_date=end_date,
                expected_employment_row_version=expected_row_version,
                open_position_versions=[],
                open_operational_role_versions=[],
            ),
            CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN"),
        )


@contextmanager
def _real_api(engine: Engine, account: CurrentAccount) -> Iterator[None]:
    factory = _service_factory(engine)

    def db_override() -> Iterator[Session]:
        database_session = factory()
        try:
            yield database_session
        finally:
            database_session.rollback()
            database_session.close()

    app.dependency_overrides[get_current_account] = lambda account=account: account
    app.dependency_overrides[get_db_session] = db_override
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _csrf_headers(client: TestClient) -> dict[str, str]:
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


def _new_staff_and_account(engine: Engine, token: str) -> tuple[int, int]:
    with engine.begin() as connection:
        staff_id = _insert_staff(connection, token)
        account_id = _insert_account(connection, staff_id, token)
    return staff_id, account_id


def _post_periodic(
    client: TestClient,
    *,
    staff_id: int,
    period_key: str,
    course_code: str = "ELDER_RIGHTS",
) -> Any:
    return client.post(
        PERIODIC_PATH.format(staff_id=staff_id),
        json={
            **PERIODIC_PAYLOAD,
            "course_code": course_code,
            "period_key": period_key,
        },
        headers=_csrf_headers(client),
    )


def _row_snapshot(engine: Engine, table: str, row_id: int) -> tuple[Any, ...]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f"""
                SELECT completed, updated_by_account_id, updated_at_utc, row_version
                FROM erp.{table}
                WHERE id = :row_id
                """
            ),
            {"row_id": row_id},
        ).one_or_none()
    if row is None:
        pytest.fail("W1A_VS3_POSTGRES_MISSING: training row disappeared", pytrace=False)
    return tuple(row)


def test_postgres_revision_and_exact_course_seed(owner_engine: Engine) -> None:
    _require_vs3_schema(owner_engine)
    with owner_engine.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(
                text(
                    """
                    SELECT sort_order, code, display_name, cycle_type
                    FROM erp.training_course
                    ORDER BY sort_order
                    """
                )
            ).all()
        ]
    if rows != list(EXPECTED_COURSES):
        pytest.fail("W1A_VS3_POSTGRES_MISSING: exact seven training courses are absent")


def test_postgres_training_shape_fk_unique_cycle_and_forbidden_fields(
    owner_engine: Engine,
) -> None:
    _require_vs3_schema(owner_engine)
    required = {
        "training_course": {"code", "display_name", "cycle_type", "sort_order", "active"},
        "staff_onboarding_training": {
            "staff_id",
            "employment_id",
            "course_code",
            "completed",
            "row_version",
            "invalidated_at_utc",
        },
        "staff_periodic_training_status": {
            "staff_id",
            "course_code",
            "period_key",
            "completed",
            "row_version",
            "invalidated_at_utc",
        },
    }
    with owner_engine.connect() as connection:
        for table, expected in required.items():
            actual = {
                str(row.column_name)
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'erp' AND table_name = :table
                        """
                    ),
                    {"table": table},
                )
            }
            if not expected.issubset(actual):
                pytest.fail("W1A_VS3_POSTGRES_MISSING: training columns are incomplete")
            if actual.intersection(
                {"training_hours", "completion_date", "training_center", "file_id", "task_id"}
            ):
                pytest.fail("W1A_VS3_FORBIDDEN_DB_FIELD_FOUND: forbidden training column exists")


def test_postgres_employment_service_atomicity_rehire_and_periodic_retention(
    owner_engine: Engine,
) -> None:
    _require_vs3_schema(owner_engine)
    token = uuid4().hex
    staff_id, account_id = _new_staff_and_account(owner_engine, token)
    with owner_engine.connect() as connection:
        before_staff = connection.execute(
            text("SELECT row_version FROM erp.staff WHERE id = :staff_id"),
            {"staff_id": staff_id},
        ).scalar_one()
        before_employments = connection.execute(
            text("SELECT count(*) FROM erp.staff_employment WHERE staff_id = :staff_id"),
            {"staff_id": staff_id},
        ).scalar_one()
        before_onboarding = connection.execute(
            text("SELECT count(*) FROM erp.staff_onboarding_training WHERE staff_id = :staff_id"),
            {"staff_id": staff_id},
        ).scalar_one()
        before_audits = connection.execute(
            text("SELECT count(*) FROM erp.audit_event WHERE actor_account_id = :account_id"),
            {"account_id": account_id},
        ).scalar_one()
        before_counter = connection.execute(
            text(
                """
                SELECT number_year, last_sequence
                FROM erp.business_number_counter
                WHERE number_type = 'STAFF_EMPLOYMENT' AND number_year = 2026
                """
            ),
        ).all()

    state = {"onboarding_flushed": False}
    factory = _service_factory(owner_engine)
    with factory() as database_session:

        def fail_after_onboarding_flush(session: Session, _flush_context: object) -> None:
            if any(
                type(instance).__name__ == "StaffOnboardingTraining" for instance in session.new
            ):
                state["onboarding_flushed"] = True
                raise _SyntheticRollback("VS3 synthetic onboarding rollback")

        event.listen(database_session, "after_flush", fail_after_onboarding_flush)
        try:
            with pytest.raises(_SyntheticRollback):
                StaffService(database_session, get_settings()).create_employment(
                    staff_id,
                    StaffEmploymentCreateRequest(
                        expected_staff_row_version=int(before_staff),
                        start_date=date(2026, 1, 1),
                    ),
                    CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN"),
                )
        finally:
            event.remove(database_session, "after_flush", fail_after_onboarding_flush)
            database_session.rollback()
    if not state["onboarding_flushed"]:
        pytest.fail(
            "W1A_VS3_POSTGRES_MISSING: employment path did not flush automatic onboarding",
            pytrace=False,
        )

    with owner_engine.connect() as connection:
        after_staff = connection.execute(
            text("SELECT row_version FROM erp.staff WHERE id = :staff_id"),
            {"staff_id": staff_id},
        ).scalar_one()
        after_employments = connection.execute(
            text("SELECT count(*) FROM erp.staff_employment WHERE staff_id = :staff_id"),
            {"staff_id": staff_id},
        ).scalar_one()
        after_onboarding = connection.execute(
            text("SELECT count(*) FROM erp.staff_onboarding_training WHERE staff_id = :staff_id"),
            {"staff_id": staff_id},
        ).scalar_one()
        after_audits = connection.execute(
            text("SELECT count(*) FROM erp.audit_event WHERE actor_account_id = :account_id"),
            {"account_id": account_id},
        ).scalar_one()
        after_counter = connection.execute(
            text(
                """
                SELECT number_year, last_sequence
                FROM erp.business_number_counter
                WHERE number_type = 'STAFF_EMPLOYMENT' AND number_year = 2026
                """
            ),
        ).all()
    if (
        after_staff != before_staff
        or after_employments != before_employments
        or after_onboarding != before_onboarding
        or after_audits != before_audits
        or after_counter != before_counter
    ):
        pytest.fail(
            "W1A_VS3_POSTGRES_MISSING: employment/onboarding rollback is not exact",
            pytrace=False,
        )

    first_employment = _service_create_employment(
        owner_engine,
        staff_id=staff_id,
        account_id=account_id,
        expected_staff_row_version=int(before_staff),
        start_date=date(2026, 1, 1),
    )
    with owner_engine.connect() as connection:
        first_training = connection.execute(
            text(
                """
                SELECT id, completed, created_by_account_id, updated_by_account_id,
                       created_at_utc, updated_at_utc, row_version
                FROM erp.staff_onboarding_training
                WHERE staff_id = :staff_id AND employment_id = :employment_id
                  AND invalidated_at_utc IS NULL
                """
            ),
            {"staff_id": staff_id, "employment_id": first_employment},
        ).one_or_none()
        first_staff_version = int(
            connection.execute(
                text("SELECT row_version FROM erp.staff WHERE id = :staff_id"),
                {"staff_id": staff_id},
            ).scalar_one()
        )
        employment_version = int(
            connection.execute(
                text("SELECT row_version FROM erp.staff_employment WHERE id = :id"),
                {"id": first_employment},
            ).scalar_one()
        )
        if first_training is None:
            pytest.fail(
                "W1A_VS3_POSTGRES_MISSING: employment did not create onboarding",
                pytrace=False,
            )
        first_training_id = int(first_training.id)
        if (
            first_training.completed is not False
            or first_training.created_by_account_id != account_id
            or first_training.updated_by_account_id != account_id
            or first_training.created_at_utc is None
            or first_training.updated_at_utc is None
            or first_training.row_version != 1
        ):
            pytest.fail(
                "W1A_VS3_POSTGRES_MISSING: onboarding actor/time/version contract is absent",
                pytrace=False,
            )

    with _real_api(
        owner_engine,
        CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN"),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        periodic = _post_periodic(client, staff_id=staff_id, period_key="2026-H1")
        if periodic.status_code // 100 != 2:
            pytest.fail(
                "W1A_VS3_POSTGRES_MISSING: periodic create product path is absent",
                pytrace=False,
            )
        periodic_body = periodic.json()
        periodic_id = periodic_body.get("id")
        if not isinstance(periodic_id, int):
            pytest.fail("W1A_VS3_POSTGRES_MISSING: periodic response has no id", pytrace=False)

    _service_close_employment(
        owner_engine,
        staff_id=staff_id,
        employment_id=first_employment,
        account_id=account_id,
        expected_row_version=employment_version,
        end_date=date(2026, 5, 31),
    )
    second_employment = _service_create_employment(
        owner_engine,
        staff_id=staff_id,
        account_id=account_id,
        expected_staff_row_version=first_staff_version,
        start_date=date(2026, 6, 1),
    )
    with owner_engine.connect() as connection:
        onboarding_rows = connection.execute(
            text(
                """
                SELECT id, employment_id, completed
                FROM erp.staff_onboarding_training
                WHERE staff_id = :staff_id AND invalidated_at_utc IS NULL
                ORDER BY id
                """
            ),
            {"staff_id": staff_id},
        ).all()
        periodic_rows = connection.execute(
            text(
                """
                SELECT id, completed, course_code, period_key
                FROM erp.staff_periodic_training_status
                WHERE staff_id = :staff_id AND invalidated_at_utc IS NULL
                """
            ),
            {"staff_id": staff_id},
        ).all()
    if len(onboarding_rows) != 2 or {int(row.employment_id) for row in onboarding_rows} != {
        first_employment,
        second_employment,
    }:
        pytest.fail(
            "W1A_VS3_POSTGRES_MISSING: rehire did not create a new onboarding row",
            pytrace=False,
        )
    onboarding_ids = {int(row.id) for row in onboarding_rows}
    replacement_onboarding_ids = onboarding_ids - {first_training_id}
    if (
        len(onboarding_ids) != 2
        or len(replacement_onboarding_ids) != 1
        or any(row.completed is not False for row in onboarding_rows)
        or len(periodic_rows) != 1
    ):
        pytest.fail(
            "W1A_VS3_POSTGRES_MISSING: prior onboarding/periodic state was not retained",
            pytrace=False,
        )
    if periodic_rows[0].id != periodic_id or periodic_rows[0].completed is not False:
        pytest.fail(
            "W1A_VS3_POSTGRES_MISSING: periodic state changed across rehire",
            pytrace=False,
        )


def test_postgres_cycle_period_truth_table_uses_real_create_path(owner_engine: Engine) -> None:
    _require_vs3_schema(owner_engine)
    staff_id, account_id = _new_staff_and_account(owner_engine, uuid4().hex)
    actor = CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN")
    with _real_api(owner_engine, actor):
        client = TestClient(app, raise_server_exceptions=False)
        accepted = [
            _post_periodic(client, staff_id=staff_id, period_key="2026-H1"),
            _post_periodic(client, staff_id=staff_id, period_key="2026-H2"),
            _post_periodic(
                client,
                staff_id=staff_id,
                period_key="2026",
                course_code="DISABLED_ABUSE",
            ),
        ]
        if any(response.status_code // 100 != 2 for response in accepted):
            pytest.fail(
                "W1A_VS3_POSTGRES_MISSING: valid HALF_YEAR/ANNUAL period cases are rejected",
                pytrace=False,
            )
        rejected = [
            _post_periodic(client, staff_id=staff_id, period_key="2030"),
            _post_periodic(
                client,
                staff_id=staff_id,
                period_key="2030-H1",
                course_code="DISABLED_ABUSE",
            ),
            _post_periodic(
                client,
                staff_id=staff_id,
                period_key="2027-H1",
                course_code="NEW_HIRE_ORIENTATION",
            ),
        ]
        if any(response.status_code not in {409, 422} for response in rejected):
            pytest.fail(
                "W1A_VS3_POSTGRES_MISSING: invalid cycle/period cases are not rejected",
                pytrace=False,
            )


def test_postgres_periodic_product_duplicate_race_and_optimistic_lock(
    owner_engine: Engine,
) -> None:
    _require_vs3_schema(owner_engine)
    staff_id, account_id = _new_staff_and_account(owner_engine, uuid4().hex)
    actor = CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN")

    with _real_api(owner_engine, actor):

        def create_duplicate(_index: int) -> int:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = _post_periodic(client, staff_id=staff_id, period_key="2028-H1")
                return int(response.status_code)

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(create_duplicate, range(2)))

        if sum(status // 100 == 2 for status in statuses) != 1 or statuses.count(409) != 1:
            pytest.fail(
                "W1A_VS3_POSTGRES_MISSING: product duplicate race did not yield one success/409",
                pytrace=False,
            )

        with owner_engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, row_version
                    FROM erp.staff_periodic_training_status
                    WHERE staff_id = :staff_id AND course_code = 'ELDER_RIGHTS'
                      AND period_key = '2028-H1' AND invalidated_at_utc IS NULL
                    """
                ),
                {"staff_id": staff_id},
            ).one_or_none()
        if row is None:
            pytest.fail("W1A_VS3_POSTGRES_MISSING: duplicate race created no fact", pytrace=False)

        with TestClient(app, raise_server_exceptions=False) as client:
            path = PERIODIC_ITEM_PATH.format(staff_id=staff_id, training_id=row.id)
            updated = client.patch(
                path,
                json={"completed": True, "expected_row_version": int(row.row_version)},
                headers=_csrf_headers(client),
            )
            if updated.status_code // 100 != 2:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: product optimistic-lock winner failed",
                    pytrace=False,
                )
            stale = client.patch(
                path,
                json={"completed": False, "expected_row_version": int(row.row_version)},
                headers=_csrf_headers(client),
            )
            if stale.status_code != 409 or "ROW_VERSION_CONFLICT" not in stale.text:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: product stale version is not stable 409",
                    pytrace=False,
                )
    snapshot = _row_snapshot(owner_engine, "staff_periodic_training_status", int(row.id))
    if snapshot[0] is not True or snapshot[3] != int(row.row_version) + 1:
        pytest.fail(
            "W1A_VS3_POSTGRES_MISSING: stale request mutated the periodic fact",
            pytrace=False,
        )


def test_postgres_completion_audit_transitions_and_failure_rollback(
    owner_engine: Engine,
) -> None:
    _require_vs3_schema(owner_engine)
    staff_id, account_id = _new_staff_and_account(owner_engine, uuid4().hex)
    actor = CurrentAccount(account_id, "VS3 synthetic actor", "ADMIN")
    with _real_api(owner_engine, actor):
        with TestClient(app, raise_server_exceptions=False) as client:
            created = _post_periodic(client, staff_id=staff_id, period_key="2029-H1")
            if created.status_code // 100 != 2:
                pytest.fail("W1A_VS3_POSTGRES_MISSING: periodic create is absent", pytrace=False)
            body = created.json()
            training_id = body.get("id")
            if not isinstance(training_id, int):
                pytest.fail("W1A_VS3_POSTGRES_MISSING: periodic id is absent", pytrace=False)
            path = PERIODIC_ITEM_PATH.format(staff_id=staff_id, training_id=training_id)
            first = client.patch(
                path,
                json={"completed": True, "expected_row_version": 1},
                headers=_csrf_headers(client),
            )
            second = client.patch(
                path,
                json={"completed": False, "expected_row_version": 2},
                headers=_csrf_headers(client),
            )
            if first.status_code // 100 != 2 or second.status_code // 100 != 2:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: true/false completion path is absent",
                    pytrace=False,
                )

            with owner_engine.connect() as connection:
                fact = connection.execute(
                    text(
                        """
                        SELECT completed, created_by_account_id, updated_by_account_id,
                               created_at_utc, updated_at_utc, row_version
                        FROM erp.staff_periodic_training_status
                        WHERE id = :id
                        """
                    ),
                    {"id": training_id},
                ).one()
                audits = connection.execute(
                    text(
                        """
                        SELECT action_code, before_json, after_json,
                               actor_account_id, occurred_at_utc
                        FROM erp.audit_event
                        WHERE entity_pk = :id
                          AND lower(action_code) LIKE '%train%'
                        ORDER BY id
                        """
                    ),
                    {"id": training_id},
                ).all()
            if (
                fact.completed is not False
                or fact.created_by_account_id != account_id
                or fact.updated_by_account_id != account_id
                or fact.created_at_utc is None
                or fact.updated_at_utc is None
                or fact.row_version != 3
            ):
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: completion actor/UTC/version is absent",
                    pytrace=False,
                )
            if len(audits) < 2:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: completion audit transitions are absent",
                    pytrace=False,
                )
            transitions = audits[-2:]
            for audit in transitions:
                if (
                    not audit.action_code
                    or audit.actor_account_id != account_id
                    or audit.occurred_at_utc is None
                    or audit.occurred_at_utc.tzinfo is None
                    or not isinstance(audit.before_json, dict)
                    or not isinstance(audit.after_json, dict)
                ):
                    pytest.fail(
                        "W1A_VS3_POSTGRES_MISSING: audit detail/actor/UTC is incomplete",
                        pytrace=False,
                    )
            if (
                transitions[0].before_json.get("completed") is not False
                or transitions[0].after_json.get("completed") is not True
            ):
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: false-to-true audit before/after is absent",
                    pytrace=False,
                )
            if (
                transitions[1].before_json.get("completed") is not True
                or transitions[1].after_json.get("completed") is not False
            ):
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: true-to-false audit before/after is absent",
                    pytrace=False,
                )

            before_fact = _row_snapshot(owner_engine, "staff_periodic_training_status", training_id)
            with owner_engine.connect() as connection:
                before_audit_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM erp.audit_event
                        WHERE entity_pk = :id AND lower(action_code) LIKE '%train%'
                        """
                    ),
                    {"id": training_id},
                ).scalar_one()
            state = {"audit_insert_attempted": False}

            def fail_on_training_audit(
                _connection: Any,
                _cursor: Any,
                statement: Any,
                _parameters: Any,
                _context: Any,
                _executemany: Any,
            ) -> None:
                statement_text = str(statement).lower()
                if "insert" in statement_text and "audit_event" in statement_text:
                    state["audit_insert_attempted"] = True
                    raise _SyntheticRollback("VS3 synthetic audit rollback")

            event.listen(owner_engine, "before_cursor_execute", fail_on_training_audit)
            try:
                failed = client.patch(
                    path,
                    json={"completed": True, "expected_row_version": 3},
                    headers=_csrf_headers(client),
                )
            finally:
                event.remove(owner_engine, "before_cursor_execute", fail_on_training_audit)
            if not state["audit_insert_attempted"] or failed.status_code // 100 == 2:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: audit failure seam did not fail after mutation",
                    pytrace=False,
                )

            after_fact = _row_snapshot(owner_engine, "staff_periodic_training_status", training_id)
            with owner_engine.connect() as connection:
                after_audit_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM erp.audit_event
                        WHERE entity_pk = :id AND lower(action_code) LIKE '%train%'
                        """
                    ),
                    {"id": training_id},
                ).scalar_one()
            if after_fact != before_fact or after_audit_count != before_audit_count:
                pytest.fail(
                    "W1A_VS3_POSTGRES_MISSING: fact/audit failure rollback is not exact",
                    pytrace=False,
                )
