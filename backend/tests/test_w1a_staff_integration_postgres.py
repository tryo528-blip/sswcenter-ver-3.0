from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import PinProtector
from app.core.settings import get_settings
from app.db.models import (
    AccessEvent,
    AccountPermission,
    AuditEvent,
    BusinessNumberCounter,
    Staff,
    StaffEmployment,
    StaffOperationalRolePeriod,
    StaffPositionPeriod,
    StaffSensitiveIdentity,
    UserAccount,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.staff.service import StaffService
from app.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_POSTGRES_TEST") != "1",
    reason="requires the isolated ephemeral PostgreSQL harness",
)

ADMIN_PIN = "123" + "456"
MANAGER_PIN = "234" + "567"
VIEWER_PIN = "345" + "678"
PLAIN_USER_PIN = "456" + "789"
SECOND_MANAGER_PIN = "567" + "890"


def _resident_number(serial: str) -> str:
    return "90010" + "1-1" + serial


def _database_factory() -> sessionmaker[Session]:
    settings = get_settings()
    assert settings.database_url is not None
    return build_session_factory(create_postgres_engine(settings.database_url))


def _csrf_headers(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    token = client.cookies.get(settings.csrf_cookie_name)
    assert token is not None
    return {settings.csrf_header_name: token}


def _login(pin: str, *, raise_server_exceptions: bool = True) -> TestClient:
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    response = client.post("/api/auth/login", json={"pin": pin})
    assert response.status_code == 200
    return client


@pytest.fixture(scope="module")
def admin_client() -> Iterator[TestClient]:
    client = TestClient(app)
    status = client.get("/api/bootstrap/status")
    assert status.status_code == 200
    if status.json()["bootstrap_required"]:
        created = client.post(
            "/api/bootstrap",
            json={
                "center_name": "W1A 합성 센터",
                "admin_name": "W1A 합성 관리자",
                "birth_date": "1990-01-01",
                "sex_code": "TEST",
                "start_date": "2026-01-01",
                "pin": ADMIN_PIN,
            },
        )
        assert created.status_code == 201
    login = client.post("/api/auth/login", json={"pin": ADMIN_PIN})
    assert login.status_code == 200
    yield client
    client.close()


def test_staff_atomic_lifecycle_masking_reveal_and_audit(
    admin_client: TestClient,
) -> None:
    headers = _csrf_headers(admin_client)
    resident_number = _resident_number("2345" + "67")
    create_payload = {
        "name": "합성 직원 일",
        "birth_date": "1990-01-01",
        "sex_code": "MALE",
        "resident_number": resident_number,
        "phone": "+82 10 1234 5678",
        "address": "합성 주소",
        "display_name": "합성 직원",
        "memo": "W1A 통합 테스트",
        "initial_employment": {
            "start_date": "2026-01-01",
            "initial_positions": [
                {
                    "position_code": "CARE_WORKER",
                    "start_date": "2026-01-01",
                }
            ],
            "initial_operational_roles": [
                {
                    "role_code": "CARE_TEAM",
                    "start_date": "2026-01-01",
                }
            ],
        },
    }
    created = admin_client.post("/api/v1/staff", json=create_payload, headers=headers)
    assert created.status_code == 201, created.json()
    body = created.json()
    staff_id = body["id"]
    assert body["resident_number_masked"] == "900101-*******"
    assert "resident_number" not in body
    assert "phone_normalized" not in body
    assert body["display_name"] == "합성 직원"
    assert body["memo"] == "W1A 통합 테스트"

    factory = _database_factory()
    with factory() as database_session:
        staff = database_session.get(Staff, staff_id)
        sensitive = database_session.get(StaffSensitiveIdentity, staff_id)
        assert staff is not None
        assert sensitive is not None
        assert staff.phone == "+82 10 1234 5678"
        assert staff.phone_normalized == "+821012345678"
        assert resident_number.encode("ascii") not in sensitive.resident_number_ciphertext
        assert len(sensitive.resident_number_nonce) == 12
        assert len(sensitive.resident_number_lookup_hmac) == 32
        create_audits = database_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.entity_type == "STAFF",
                AuditEvent.entity_pk == staff_id,
                AuditEvent.action_code == "STAFF_CREATE",
            )
        )
        assert create_audits == 1

    duplicate = admin_client.post("/api/v1/staff", json=create_payload, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "RESIDENT_NUMBER_DUPLICATE"

    listed = admin_client.get("/api/v1/staff", params={"search": "합성 직원"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    listed_item = listed.json()["items"][0]
    assert "resident_number" not in listed_item
    assert "resident_number_ciphertext" not in listed_item
    assert "phone_normalized" not in listed_item

    detail = admin_client.get(f"/api/v1/staff/{staff_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    employment = detail_body["employments"][0]
    position = detail_body["positions"][0]
    role = detail_body["operational_roles"][0]

    no_csrf = admin_client.post(
        f"/api/v1/staff/{staff_id}/employments",
        json={
            "expected_staff_row_version": detail_body["row_version"],
            "start_date": "2027-01-01",
        },
    )
    assert no_csrf.status_code == 403

    with factory() as database_session:
        staff_before_close = database_session.get(Staff, staff_id)
        assert staff_before_close is not None
        staff_before_close_state = (
            staff_before_close.updated_at_utc,
            staff_before_close.row_version,
        )

    closed = admin_client.post(
        f"/api/v1/staff/{staff_id}/employments/{employment['id']}/close",
        headers=headers,
        json={
            "end_date": "2026-05-31",
            "end_reason_code": "SYNTHETIC_END",
            "expected_employment_row_version": employment["row_version"],
            "open_position_versions": [
                {
                    "period_id": position["id"],
                    "expected_row_version": position["row_version"],
                }
            ],
            "open_operational_role_versions": [
                {
                    "period_id": role["id"],
                    "expected_row_version": role["row_version"],
                }
            ],
        },
    )
    assert closed.status_code == 200, closed.json()
    assert closed.json()["end_date"] == "2026-05-31"
    with factory() as database_session:
        staff_after_close = database_session.get(Staff, staff_id)
        assert staff_after_close is not None
        assert (
            staff_after_close.updated_at_utc,
            staff_after_close.row_version,
        ) == staff_before_close_state

    rehire = admin_client.post(
        f"/api/v1/staff/{staff_id}/employments",
        headers=headers,
        json={
            "expected_staff_row_version": detail_body["row_version"],
            "start_date": "2026-06-01",
        },
    )
    assert rehire.status_code == 201, rehire.json()
    assert rehire.json()["id"] != employment["id"]
    assert rehire.json()["staff_no"] != employment["staff_no"]

    stale_rehire = admin_client.post(
        f"/api/v1/staff/{staff_id}/employments",
        headers=headers,
        json={
            "expected_staff_row_version": detail_body["row_version"],
            "start_date": "2027-01-01",
        },
    )
    assert stale_rehire.status_code == 409
    assert stale_rehire.json()["error"]["code"] == "ROW_VERSION_CONFLICT"

    reveal_path = f"/api/v1/staff/{staff_id}/sensitive-identity/reveal"
    with factory() as database_session:
        before_events = database_session.scalar(
            select(func.count())
            .select_from(AccessEvent)
            .where(
                AccessEvent.entity_type == "STAFF",
                AccessEvent.entity_pk == staff_id,
                AccessEvent.access_type == "STAFF_RESIDENT_NUMBER_REVEAL",
            )
        )
    wrong_pin = admin_client.post(
        reveal_path,
        headers=headers,
        json={"current_pin": "999" + "999"},
    )
    assert wrong_pin.status_code == 422
    assert wrong_pin.headers["Cache-Control"] == "no-store"
    assert wrong_pin.json()["error"]["code"] == "CURRENT_PIN_INVALID"

    revealed = admin_client.post(
        reveal_path,
        headers=headers,
        json={"current_pin": ADMIN_PIN},
    )
    assert revealed.status_code == 200, revealed.json()
    assert revealed.headers["Cache-Control"] == "no-store"
    assert revealed.json()["resident_number"] == resident_number
    with factory() as database_session:
        after_events = database_session.scalar(
            select(func.count())
            .select_from(AccessEvent)
            .where(
                AccessEvent.entity_type == "STAFF",
                AccessEvent.entity_pk == staff_id,
                AccessEvent.access_type == "STAFF_RESIDENT_NUMBER_REVEAL",
            )
        )
    assert before_events is not None
    assert after_events is not None
    assert after_events == before_events + 1


def _create_permission_accounts() -> None:
    factory = _database_factory()
    settings = get_settings()
    protector = PinProtector(
        settings.secret_value("pin_pepper"),
        settings.secret_value("pin_lookup_key"),
    )
    with factory() as database_session:
        admin = database_session.scalar(select(UserAccount).where(UserAccount.role_code == "ADMIN"))
        assert admin is not None
        account_specs = [
            ("manager", "권한 관리자", MANAGER_PIN, "STAFF_MANAGE"),
            ("viewer", "권한 조회자", VIEWER_PIN, "STAFF_VIEW"),
            ("plain", "일반 사용자", PLAIN_USER_PIN, None),
        ]
        for account_code, display_name, pin, permission in account_specs:
            staff = Staff(
                name=display_name,
                display_name=display_name,
                birth_date=date(1990, 1, 1),
                sex_code="TEST",
            )
            database_session.add(staff)
            database_session.flush()
            account = UserAccount(
                staff_id=staff.id,
                account_code=f"W1A-{account_code.upper()}",
                display_name=display_name,
                role_code="USER",
                pin_hash=protector.hash_pin(pin),
                pin_lookup_hmac=protector.lookup_hmac(pin),
                pin_key_version=1,
            )
            database_session.add(account)
            database_session.flush()
            if permission is not None:
                database_session.add(
                    AccountPermission(
                        account_id=account.id,
                        permission_code=permission,
                        granted_by_account_id=admin.id,
                    )
                )
        database_session.commit()


def test_staff_permission_matrix_and_capabilities(admin_client: TestClient) -> None:
    _create_permission_accounts()
    assert admin_client.get("/api/v1/staff").status_code == 200
    admin_create = admin_client.post(
        "/api/v1/staff",
        headers=_csrf_headers(admin_client),
        json={
            "name": "ADMIN 검증 대상",
            "birth_date": "1990-01-01",
            "sex_code": "MALE",
            "resident_number": _resident_number("7890" + "12"),
            "initial_employment": {"start_date": "2026-02-15"},
        },
    )
    assert admin_create.status_code == 201
    admin_staff_id = int(admin_create.json()["id"])
    admin_reveal = admin_client.post(
        f"/api/v1/staff/{admin_staff_id}/sensitive-identity/reveal",
        headers=_csrf_headers(admin_client),
        json={"current_pin": ADMIN_PIN},
    )
    assert admin_reveal.status_code == 200
    manager = _login(MANAGER_PIN)
    viewer = _login(VIEWER_PIN)
    plain_user = _login(PLAIN_USER_PIN)
    try:
        manager_capabilities = manager.get("/api/v1/session-capabilities")
        assert manager_capabilities.status_code == 200
        assert manager_capabilities.headers["Cache-Control"] == "no-store"
        assert manager_capabilities.json() == {
            "staff.view": True,
            "staff.manage": True,
            "staff.sensitive_identity.reveal": True,
        }

        viewer_capabilities = viewer.get("/api/v1/session-capabilities")
        assert viewer_capabilities.status_code == 200
        assert viewer_capabilities.json() == {
            "staff.view": True,
            "staff.manage": False,
            "staff.sensitive_identity.reveal": False,
        }
        assert viewer.get("/api/v1/staff").status_code == 200
        viewer_detail = viewer.get(f"/api/v1/staff/{admin_staff_id}")
        assert viewer_detail.status_code == 200
        viewer_reveal = viewer.post(
            f"/api/v1/staff/{admin_staff_id}/sensitive-identity/reveal",
            headers=_csrf_headers(viewer),
            json={"current_pin": VIEWER_PIN},
        )
        assert viewer_reveal.status_code == 403
        assert viewer_reveal.json()["error"]["code"] == "PERMISSION_REQUIRED"

        viewer_create = viewer.post(
            "/api/v1/staff",
            headers=_csrf_headers(viewer),
            json={
                "name": "거부 대상",
                "birth_date": "1990-01-01",
                "sex_code": "MALE",
                "resident_number": _resident_number("3456" + "78"),
                "initial_employment": {"start_date": "2026-01-01"},
            },
        )
        assert viewer_create.status_code == 403
        assert viewer_create.json()["error"]["code"] == "PERMISSION_REQUIRED"

        assert plain_user.get("/api/v1/staff").status_code == 403

        manager_create = manager.post(
            "/api/v1/staff",
            headers=_csrf_headers(manager),
            json={
                "name": "관리자 생성 직원",
                "birth_date": "1990-01-01",
                "sex_code": "MALE",
                "resident_number": _resident_number("4567" + "89"),
                "initial_employment": {"start_date": "2026-02-01"},
            },
        )
        assert manager_create.status_code == 201, manager_create.json()
        manager_staff_id = int(manager_create.json()["id"])
        manager_reveal = manager.post(
            f"/api/v1/staff/{manager_staff_id}/sensitive-identity/reveal",
            headers=_csrf_headers(manager),
            json={"current_pin": MANAGER_PIN},
        )
        assert manager_reveal.status_code == 200
    finally:
        manager.close()
        viewer.close()
        plain_user.close()


def test_deferred_containment_and_reverse_guard_enforce_final_state() -> None:
    factory = _database_factory()
    with factory() as database_session:
        employment = database_session.scalar(
            select(StaffEmployment)
            .join(Staff, Staff.id == StaffEmployment.staff_id)
            .where(Staff.name == "합성 직원 일")
            .order_by(StaffEmployment.start_date.asc())
        )
        admin = database_session.scalar(select(UserAccount).where(UserAccount.role_code == "ADMIN"))
        assert employment is not None
        assert admin is not None
        database_session.add(
            StaffPositionPeriod(
                staff_id=employment.staff_id,
                employment_id=employment.id,
                position_code="OTHER",
                start_date=date(2025, 12, 31),
                end_date=date(2025, 12, 31),
                created_by_account_id=admin.id,
                updated_by_account_id=admin.id,
            )
        )
        with pytest.raises(IntegrityError, match="STAFF_PERIOD_OUTSIDE_EMPLOYMENT"):
            database_session.commit()
        database_session.rollback()

    with factory() as database_session:
        employment = database_session.scalar(
            select(StaffEmployment)
            .join(Staff, Staff.id == StaffEmployment.staff_id)
            .where(
                Staff.name == "합성 직원 일",
                StaffEmployment.end_date.is_not(None),
            )
            .order_by(StaffEmployment.start_date.asc())
        )
        assert employment is not None
        employment.end_date = date(2026, 4, 30)
        with pytest.raises(IntegrityError, match="STAFF_PERIOD_OUTSIDE_EMPLOYMENT"):
            database_session.commit()
        database_session.rollback()


def test_duplicate_identity_and_rehire_concurrency_are_serialized() -> None:
    resident_number = _resident_number("5678" + "90")

    def create_same_staff() -> tuple[int, dict[str, Any]]:
        client = _login(ADMIN_PIN)
        try:
            response = client.post(
                "/api/v1/staff",
                headers=_csrf_headers(client),
                json={
                    "name": "동시성 합성 직원",
                    "birth_date": "1990-01-01",
                    "sex_code": "MALE",
                    "resident_number": resident_number,
                    "initial_employment": {"start_date": "2026-03-01"},
                },
            )
            return response.status_code, response.json()
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        create_results = list(executor.map(lambda _: create_same_staff(), range(2)))
    assert sorted(status for status, _ in create_results) == [201, 409]
    conflict_body = next(body for status, body in create_results if status == 409)
    assert conflict_body["error"]["code"] == "RESIDENT_NUMBER_DUPLICATE"
    created_body = next(body for status, body in create_results if status == 201)
    staff_id = int(created_body["id"])
    employment = created_body["employments"][0]

    admin = _login(ADMIN_PIN)
    try:
        closed = admin.post(
            f"/api/v1/staff/{staff_id}/employments/{employment['id']}/close",
            headers=_csrf_headers(admin),
            json={
                "end_date": "2026-03-31",
                "end_reason_code": "CONCURRENCY_TEST",
                "expected_employment_row_version": employment["row_version"],
                "open_position_versions": [],
                "open_operational_role_versions": [],
            },
        )
        assert closed.status_code == 200
    finally:
        admin.close()

    def rehire_same_staff() -> tuple[int, dict[str, Any]]:
        client = _login(ADMIN_PIN)
        try:
            response = client.post(
                f"/api/v1/staff/{staff_id}/employments",
                headers=_csrf_headers(client),
                json={
                    "expected_staff_row_version": created_body["row_version"],
                    "start_date": "2026-04-01",
                },
            )
            return response.status_code, response.json()
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rehire_results = list(executor.map(lambda _: rehire_same_staff(), range(2)))
    assert sorted(status for status, _ in rehire_results) == [201, 409]
    rehire_conflict = next(body for status, body in rehire_results if status == 409)
    assert rehire_conflict["error"]["code"] == "ROW_VERSION_CONFLICT"


def test_replacement_is_explicit_and_rolls_back_counter_children_and_audit(
    admin_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _database_factory()
    settings = get_settings()
    protector = PinProtector(
        settings.secret_value("pin_pepper"),
        settings.secret_value("pin_lookup_key"),
    )
    with factory() as database_session:
        admin = database_session.scalar(select(UserAccount).where(UserAccount.role_code == "ADMIN"))
        assert admin is not None
        manager_staff = Staff(
            name="교정 담당자",
            display_name="교정 담당자",
            birth_date=date(1990, 1, 1),
            sex_code="TEST",
        )
        database_session.add(manager_staff)
        database_session.flush()
        manager_account = UserAccount(
            staff_id=manager_staff.id,
            account_code="W1A-SECOND-MANAGER",
            display_name="교정 담당자",
            role_code="USER",
            pin_hash=protector.hash_pin(SECOND_MANAGER_PIN),
            pin_lookup_hmac=protector.lookup_hmac(SECOND_MANAGER_PIN),
            pin_key_version=1,
        )
        database_session.add(manager_account)
        database_session.flush()
        database_session.add(
            AccountPermission(
                account_id=manager_account.id,
                permission_code="STAFF_MANAGE",
                granted_by_account_id=admin.id,
            )
        )
        database_session.commit()
        manager_id = manager_account.id

    resident_number = _resident_number("6789" + "01")
    created = admin_client.post(
        "/api/v1/staff",
        headers=_csrf_headers(admin_client),
        json={
            "name": "교체 원본 직원",
            "birth_date": "1990-01-01",
            "sex_code": "MALE",
            "resident_number": resident_number,
            "initial_employment": {
                "start_date": "2026-07-01",
                "initial_positions": [{"position_code": "CARE_WORKER", "start_date": "2026-07-01"}],
                "initial_operational_roles": [
                    {"role_code": "CARE_TEAM", "start_date": "2026-07-01"},
                    {"role_code": "MANAGEMENT_FUNCTION", "start_date": "2026-07-01"},
                ],
            },
        },
    )
    assert created.status_code == 201, created.json()
    staff_id = int(created.json()["id"])
    created_body = created.json()
    original = created_body["employments"][0]
    initial_position = created_body["positions"][0]
    initial_roles = {item["role_code"]: item for item in created_body["operational_roles"]}
    assert set(initial_roles) == {"CARE_TEAM", "MANAGEMENT_FUNCTION"}
    initial_role = initial_roles["CARE_TEAM"]
    second_initial_role = initial_roles["MANAGEMENT_FUNCTION"]

    with factory() as database_session:
        admin_id = database_session.scalar(
            select(UserAccount.id).where(UserAccount.role_code == "ADMIN")
        )
        assert admin_id is not None

    employment_fields = (
        "id",
        "staff_id",
        "employment_no",
        "staff_no",
        "staff_no_year",
        "staff_no_sequence",
        "start_date",
        "end_date",
        "end_reason_code",
        "invalidated_at_utc",
        "replacement_employment_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    )
    period_common_fields = (
        "id",
        "staff_id",
        "employment_id",
        "start_date",
        "end_date",
        "invalidated_at_utc",
        "replacement_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    )
    position_fields = (
        "id",
        "staff_id",
        "employment_id",
        "position_code",
    ) + period_common_fields[3:]
    role_fields = (
        "id",
        "staff_id",
        "employment_id",
        "role_code",
    ) + period_common_fields[3:]
    audit_fields = (
        "id",
        "occurred_at_utc",
        "actor_account_id",
        "actor_kind",
        "action_code",
        "entity_type",
        "entity_pk",
        "before_json",
        "after_json",
        "reason_code",
        "reason_text",
        "source_run_id",
        "request_id",
        "created_from",
    )

    def row_snapshots(rows: Sequence[Any], fields: tuple[str, ...]) -> dict[int, dict[str, Any]]:
        return {int(row.id): {field: getattr(row, field) for field in fields} for row in rows}

    def audit_snapshots(database_session: Session) -> list[dict[str, Any]]:
        return [
            {field: getattr(row, field) for field in audit_fields}
            for row in database_session.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()
        ]

    def state_snapshot() -> dict[str, Any]:
        with factory() as database_session:
            staff = database_session.get(Staff, staff_id)
            assert staff is not None
            counter = database_session.scalar(
                select(BusinessNumberCounter.last_sequence).where(
                    BusinessNumberCounter.number_type == "STAFF_EMPLOYMENT",
                    BusinessNumberCounter.number_year == 2026,
                )
            )
            assert counter is not None
            return {
                "staff": {
                    "id": staff.id,
                    "updated_at_utc": staff.updated_at_utc,
                    "row_version": staff.row_version,
                },
                "counter": int(counter),
                "employments": row_snapshots(
                    database_session.scalars(
                        select(StaffEmployment)
                        .where(StaffEmployment.staff_id == staff_id)
                        .order_by(StaffEmployment.id)
                    ).all(),
                    employment_fields,
                ),
                "positions": row_snapshots(
                    database_session.scalars(
                        select(StaffPositionPeriod)
                        .where(StaffPositionPeriod.staff_id == staff_id)
                        .order_by(StaffPositionPeriod.id)
                    ).all(),
                    position_fields,
                ),
                "roles": row_snapshots(
                    database_session.scalars(
                        select(StaffOperationalRolePeriod)
                        .where(StaffOperationalRolePeriod.staff_id == staff_id)
                        .order_by(StaffOperationalRolePeriod.id)
                    ).all(),
                    role_fields,
                ),
                "audits": audit_snapshots(database_session),
            }

    before = state_snapshot()

    manager = _login(SECOND_MANAGER_PIN, raise_server_exceptions=False)
    try:
        omitted_replacement = manager.post(
            f"/api/v1/staff/{staff_id}/employments/{original['id']}/replacements",
            headers=_csrf_headers(manager),
            json={
                "expected_employment_row_version": original["row_version"],
                "start_date": "2026-07-01",
                "position_replacements": [
                    {
                        "old_period_id": initial_position["id"],
                        "expected_row_version": initial_position["row_version"],
                    }
                ],
                "operational_role_replacements": [
                    {
                        "old_period_id": initial_role["id"],
                        "expected_row_version": initial_role["row_version"],
                        "replacement": None,
                    },
                    {
                        "old_period_id": second_initial_role["id"],
                        "expected_row_version": second_initial_role["row_version"],
                        "replacement": None,
                    },
                ],
            },
        )
        assert omitted_replacement.status_code == 422
        assert omitted_replacement.json()["error"]["code"] == "VALIDATION_ERROR"
        assert state_snapshot() == before

        post_mutation_payload = {
            "expected_employment_row_version": original["row_version"],
            "start_date": "2026-07-01",
            "position_replacements": [
                {
                    "old_period_id": initial_position["id"],
                    "expected_row_version": initial_position["row_version"],
                    "replacement": {
                        "position_code": "OTHER",
                        "start_date": "2026-07-01",
                    },
                }
            ],
            "operational_role_replacements": [
                {
                    "old_period_id": initial_role["id"],
                    "expected_row_version": initial_role["row_version"],
                    "replacement": {
                        "role_code": "CARE_TEAM_CORRECTED",
                        "start_date": "2026-07-01",
                    },
                },
                {
                    "old_period_id": second_initial_role["id"],
                    "expected_row_version": second_initial_role["row_version"],
                    "replacement": {
                        "role_code": "MANAGEMENT_FUNCTION_CORRECTED",
                        "start_date": "2026-07-01",
                    },
                },
            ],
        }

        def fail_after_post_mutation(service: StaffService) -> None:
            service.database_session.flush()
            flushed_employments = service.database_session.scalars(
                select(StaffEmployment)
                .where(StaffEmployment.staff_id == staff_id)
                .order_by(StaffEmployment.id)
            ).all()
            flushed_positions = service.database_session.scalars(
                select(StaffPositionPeriod).where(StaffPositionPeriod.staff_id == staff_id)
            ).all()
            flushed_roles = service.database_session.scalars(
                select(StaffOperationalRolePeriod).where(
                    StaffOperationalRolePeriod.staff_id == staff_id
                )
            ).all()
            flushed_audits = service.database_session.scalar(
                select(func.count()).select_from(AuditEvent)
            )
            flushed_counter = service.database_session.scalar(
                select(BusinessNumberCounter.last_sequence).where(
                    BusinessNumberCounter.number_type == "STAFF_EMPLOYMENT",
                    BusinessNumberCounter.number_year == 2026,
                )
            )
            assert len(flushed_employments) == len(before["employments"]) + 1
            assert len(flushed_positions) == len(before["positions"]) + 1
            assert len(flushed_roles) == len(before["roles"]) + 2
            flushed_old = next(row for row in flushed_employments if row.id == original["id"])
            assert flushed_old.invalidated_at_utc is not None
            assert flushed_old.replacement_employment_id is not None
            assert flushed_counter == before["counter"] + 1
            assert flushed_audits == len(before["audits"]) + 1
            flushed_children = list(flushed_positions) + list(flushed_roles)
            assert all(
                row.created_by_account_id == manager_id
                for row in flushed_children
                if row.employment_id != original["id"]
            )
            assert all(row.updated_by_account_id == manager_id for row in flushed_children)
            raise RuntimeError("synthetic post-mutation replacement failure")

        monkeypatch.setattr(StaffService, "_commit", fail_after_post_mutation)
        failed_after_mutation = manager.post(
            f"/api/v1/staff/{staff_id}/employments/{original['id']}/replacements",
            headers=_csrf_headers(manager),
            json=post_mutation_payload,
        )
        assert failed_after_mutation.status_code == 500
        assert failed_after_mutation.json()["error"]["code"] == "UNEXPECTED_SERVER_ERROR"
        assert state_snapshot() == before
        monkeypatch.undo()

        successful = manager.post(
            f"/api/v1/staff/{staff_id}/employments/{original['id']}/replacements",
            headers=_csrf_headers(manager),
            json={
                "expected_employment_row_version": original["row_version"],
                "start_date": "2026-07-01",
                "position_replacements": [
                    {
                        "old_period_id": initial_position["id"],
                        "expected_row_version": initial_position["row_version"],
                        "replacement": {
                            "position_code": "OTHER",
                            "start_date": "2026-07-01",
                        },
                    }
                ],
                "operational_role_replacements": [
                    {
                        "old_period_id": initial_role["id"],
                        "expected_row_version": initial_role["row_version"],
                        "replacement": {
                            "role_code": "CARE_TEAM_CORRECTED",
                            "start_date": "2026-07-01",
                        },
                    },
                    {
                        "old_period_id": second_initial_role["id"],
                        "expected_row_version": second_initial_role["row_version"],
                        "replacement": None,
                    },
                ],
            },
        )
        assert successful.status_code == 201, successful.json()
        replacement_id = int(successful.json()["id"])

        with factory() as database_session:
            after = state_snapshot()
            assert after["staff"] == before["staff"]
            old = database_session.get(StaffEmployment, original["id"])
            replacement = database_session.get(StaffEmployment, replacement_id)
            assert old is not None and replacement is not None
            assert old.invalidated_at_utc is not None
            assert old.replacement_employment_id == replacement_id
            assert old.created_by_account_id == admin_id
            assert old.updated_by_account_id == manager_id
            assert old.row_version == original["row_version"] + 1
            assert old.updated_at_utc > before["employments"][original["id"]]["updated_at_utc"]
            assert replacement.created_by_account_id == manager_id
            assert replacement.updated_by_account_id == manager_id
            assert replacement.row_version == 1
            assert replacement.created_at_utc is not None
            assert replacement.updated_at_utc >= replacement.created_at_utc
            old_position = database_session.scalar(
                select(StaffPositionPeriod).where(StaffPositionPeriod.id == initial_position["id"])
            )
            old_roles = {
                row.id: row
                for row in database_session.scalars(
                    select(StaffOperationalRolePeriod).where(
                        StaffOperationalRolePeriod.staff_id == staff_id
                    )
                ).all()
            }
            new_positions = database_session.scalars(
                select(StaffPositionPeriod).where(
                    StaffPositionPeriod.employment_id == replacement_id
                )
            ).all()
            new_roles = database_session.scalars(
                select(StaffOperationalRolePeriod).where(
                    StaffOperationalRolePeriod.employment_id == replacement_id
                )
            ).all()
            assert old_position is not None
            assert len(new_positions) == 1
            assert len(new_roles) == 1
            assert old_position.invalidated_at_utc is not None
            assert old_position.created_by_account_id == admin_id
            assert old_position.updated_by_account_id == manager_id
            assert (
                old_position.updated_at_utc > before["positions"][old_position.id]["updated_at_utc"]
            )
            assert (
                old_position.row_version == before["positions"][old_position.id]["row_version"] + 1
            )
            assert old_position.replacement_id == new_positions[0].id
            assert all(
                row.created_by_account_id == manager_id
                and row.updated_by_account_id == manager_id
                and row.row_version == 1
                and row.updated_at_utc >= row.created_at_utc
                for row in list(new_positions) + list(new_roles)
            )
            for role_id, role_before in before["roles"].items():
                role = old_roles[role_id]
                assert role.invalidated_at_utc is not None
                assert role.created_by_account_id == admin_id
                assert role.updated_by_account_id == manager_id
                assert role.updated_at_utc > role_before["updated_at_utc"]
                assert role.row_version == role_before["row_version"] + 1
            assert old_roles[initial_role["id"]].replacement_id == new_roles[0].id
            assert old_roles[second_initial_role["id"]].replacement_id is None
            audit = database_session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.entity_type == "STAFF_EMPLOYMENT",
                    AuditEvent.entity_pk == original["id"],
                    AuditEvent.action_code == "STAFF_EMPLOYMENT_REPLACE",
                )
                .order_by(AuditEvent.id.desc())
            )
            assert audit is not None
            assert audit.actor_account_id == manager_id
            assert audit.after_json is not None
            assert audit.after_json["actor_account_id"] == manager_id
            assert len(after["audits"]) == len(before["audits"]) + 1
            assert after["counter"] == before["counter"] + 1

        detail = manager.get(f"/api/v1/staff/{staff_id}")
        assert detail.status_code == 200
        assert detail.json()["current_employment"]["id"] == replacement_id
        assert len(detail.json()["current_positions"]) == 1
        assert len(detail.json()["current_operational_roles"]) == 1
    finally:
        manager.close()


def test_replacement_rejects_stale_child_versions_after_payload_read(
    admin_client: TestClient,
) -> None:
    """RED: replacement must re-check child versions after the payload is read."""
    resident_number = _resident_number("8901" + "23")
    created = admin_client.post(
        "/api/v1/staff",
        headers=_csrf_headers(admin_client),
        json={
            "name": "자식 버전 경합 직원",
            "birth_date": "1990-01-01",
            "sex_code": "MALE",
            "resident_number": resident_number,
            "initial_employment": {
                "start_date": "2026-08-01",
                "initial_positions": [{"position_code": "CARE_WORKER", "start_date": "2026-08-01"}],
                "initial_operational_roles": [
                    {"role_code": "CARE_TEAM", "start_date": "2026-08-01"}
                ],
            },
        },
    )
    assert created.status_code == 201, created.json()
    staff_id = int(created.json()["id"])
    detail = admin_client.get(f"/api/v1/staff/{staff_id}")
    assert detail.status_code == 200, detail.json()
    detail_body = detail.json()
    employment = detail_body["employments"][0]
    position = detail_body["positions"][0]
    role = detail_body["operational_roles"][0]
    original_payload = {
        "expected_employment_row_version": employment["row_version"],
        "start_date": "2026-08-01",
        "position_replacements": [
            {
                "old_period_id": position["id"],
                "expected_row_version": position["row_version"],
                "replacement": {
                    "position_code": position["position_code"],
                    "start_date": position["start_date"],
                    "end_date": position["end_date"],
                },
            }
        ],
        "operational_role_replacements": [
            {
                "old_period_id": role["id"],
                "expected_row_version": role["row_version"],
                "replacement": {
                    "role_code": role["role_code"],
                    "start_date": role["start_date"],
                    "end_date": role["end_date"],
                },
            }
        ],
    }

    factory = _database_factory()
    with factory() as database_session:
        current_position = database_session.get(StaffPositionPeriod, position["id"])
        current_role = database_session.get(StaffOperationalRolePeriod, role["id"])
        assert current_position is not None
        assert current_role is not None
        current_position.row_version += 1
        current_role.row_version += 1
        database_session.commit()

    stale_replacement = admin_client.post(
        f"/api/v1/staff/{staff_id}/employments/{employment['id']}/replacements",
        headers=_csrf_headers(admin_client),
        json=original_payload,
    )
    assert stale_replacement.status_code == 409, (
        "B2_CHILD_ROW_VERSION_NOT_RECHECKED: stale child payload was accepted"
    )
    assert stale_replacement.json()["error"]["code"] == "ROW_VERSION_CONFLICT"
