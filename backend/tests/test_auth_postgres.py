from __future__ import annotations

import os
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import require_admin
from app.core.auth import CurrentAccount, utc_now
from app.core.security import PinProtector, hash_session_token
from app.core.settings import get_settings
from app.db.models import AuthRateLimitBucket, AuthSession, UserAccount
from app.db.session import build_session_factory, create_postgres_engine
from app.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_POSTGRES_TEST") != "1",
    reason="requires the isolated ephemeral PostgreSQL harness",
)


def _database_factory() -> sessionmaker[Session]:
    settings = get_settings()
    assert settings.database_url is not None
    engine = create_postgres_engine(settings.database_url)
    return build_session_factory(engine)


def test_wave0_authentication_contract() -> None:
    client = TestClient(app)
    settings = get_settings()

    assert client.get("/api/bootstrap/status").json() == {"bootstrap_required": True}
    invalid_bootstrap = client.post(
        "/api/bootstrap",
        json={
            "center_name": "테스트 돌봄센터",
            "admin_name": "합성 관리자",
            "birth_date": "1990-01-01",
            "sex_code": "TEST",
            "start_date": "2026-07-24",
            "pin": "12345",
        },
    )
    assert invalid_bootstrap.status_code == 422

    bootstrap = client.post(
        "/api/bootstrap",
        json={
            "center_name": "테스트 돌봄센터",
            "admin_name": "합성 관리자",
            "birth_date": "1990-01-01",
            "sex_code": "TEST",
            "start_date": "2026-07-24",
            "pin": "123456",
        },
    )
    assert bootstrap.status_code == 201
    assert bootstrap.json()["account"]["role_code"] == "ADMIN"
    assert (
        client.post(
            "/api/bootstrap",
            json={
                "center_name": "재실행 금지",
                "admin_name": "재실행 금지",
                "birth_date": "1990-01-01",
                "sex_code": "TEST",
                "start_date": "2026-07-24",
                "pin": "654321",
            },
        ).status_code
        == 409
    )

    assert TestClient(app).get("/api/auth/me").status_code == 401

    unknown_client = TestClient(app)
    for _ in range(10):
        assert unknown_client.post("/api/auth/login", json={"pin": "999999"}).status_code == 401
    assert unknown_client.cookies.get(settings.device_cookie_name) is not None
    assert unknown_client.post("/api/auth/login", json={"pin": "999999"}).status_code == 429

    factory = _database_factory()
    with factory() as database_session:
        database_session.execute(delete(AuthRateLimitBucket))
        database_session.commit()

    login = client.post("/api/auth/login", json={"pin": "123456"})
    assert login.status_code == 200
    assert login.json()["account"]["role_code"] == "ADMIN"
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 403

    csrf_cookie = client.cookies.get(settings.csrf_cookie_name)
    assert csrf_cookie is not None
    assert (
        client.post(
            "/api/auth/logout",
            headers={
                settings.csrf_header_name: csrf_cookie,
                "Origin": "https://cross-origin.invalid",
            },
        ).status_code
        == 403
    )
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.post(
            "/api/auth/logout",
            headers={
                settings.csrf_header_name: csrf_cookie,
                "Origin": "https://testserver",
            },
        ).status_code
        == 403
    )
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.post(
            "/api/auth/logout",
            headers={settings.csrf_header_name: csrf_cookie},
        ).status_code
        == 204
    )
    assert client.get("/api/auth/me").status_code == 401

    protector = PinProtector(
        settings.secret_value("pin_pepper"),
        settings.secret_value("pin_lookup_key"),
    )
    with factory() as database_session:
        account = database_session.scalar(
            select(UserAccount).where(UserAccount.role_code == "ADMIN")
        )
        assert account is not None
        account.pin_hash = protector.hash_pin("654321")
        database_session.commit()

    lock_client = TestClient(app)
    for _ in range(5):
        assert lock_client.post("/api/auth/login", json={"pin": "123456"}).status_code == 401
    assert lock_client.post("/api/auth/login", json={"pin": "123456"}).status_code == 423

    with factory() as database_session:
        account = database_session.scalar(
            select(UserAccount).where(UserAccount.role_code == "ADMIN")
        )
        assert account is not None
        account.pin_hash = protector.hash_pin("123456")
        account.failed_count = 0
        account.locked_until_utc = None
        database_session.commit()

    expiry_client = TestClient(app)
    assert expiry_client.post("/api/auth/login", json={"pin": "123456"}).status_code == 200
    session_token = expiry_client.cookies.get(settings.session_cookie_name)
    assert session_token is not None
    with factory() as database_session:
        auth_session = database_session.scalar(
            select(AuthSession).where(
                AuthSession.session_token_hash == hash_session_token(session_token)
            )
        )
        assert auth_session is not None
        auth_session.idle_expires_at_utc = utc_now() - timedelta(seconds=1)
        database_session.commit()
    expired = expiry_client.get("/api/auth/me")
    assert expired.status_code == 401
    assert expired.json()["detail"]["code"] == "idle_expired"

    absolute_client = TestClient(app)
    assert absolute_client.post("/api/auth/login", json={"pin": "123456"}).status_code == 200
    absolute_token = absolute_client.cookies.get(settings.session_cookie_name)
    assert absolute_token is not None
    with factory() as database_session:
        auth_session = database_session.scalar(
            select(AuthSession).where(
                AuthSession.session_token_hash == hash_session_token(absolute_token)
            )
        )
        assert auth_session is not None
        auth_session.idle_expires_at_utc = utc_now() + timedelta(minutes=1)
        auth_session.absolute_expires_at_utc = utc_now() - timedelta(seconds=1)
        database_session.commit()
    absolute_expired = absolute_client.get("/api/auth/me")
    assert absolute_expired.status_code == 401
    assert absolute_expired.json()["detail"]["code"] == "absolute_expired"


def test_admin_and_user_roles_are_distinct() -> None:
    admin = CurrentAccount(id=1, display_name="관리자", role_code="ADMIN")
    user = CurrentAccount(id=2, display_name="사용자", role_code="USER")

    assert require_admin(admin) == admin
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user)
    assert exc_info.value.status_code == 403
