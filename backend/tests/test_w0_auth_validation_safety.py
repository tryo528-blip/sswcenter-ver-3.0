from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response

from app.api.dependencies import get_db_session
from app.main import app

ERRORS_PATH = Path(__file__).resolve().parents[1] / "app" / "api" / "w1a_errors.py"
SECRET_PIN = "654321"


def _override_db_session() -> Iterator[object]:
    yield object()


def _assert_auth_validation_is_safe(response: Response, *, secret: str) -> None:
    assert response.status_code == 422
    payload = response.json()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert secret not in serialized
    assert "input" not in serialized.lower()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["message"] == "입력값을 확인하세요."
    for item in payload.get("field_errors", []):
        assert secret not in json.dumps(item, ensure_ascii=False)
        assert "input" not in item


def test_auth_validation_handler_is_dedicated_and_omits_input() -> None:
    source = ERRORS_PATH.read_text(encoding="utf-8")
    assert "_is_auth_api_path" in source
    assert "/api/auth" in source
    assert "/api/bootstrap" in source
    assert "input" not in source.split("_safe_validation_fields")[1].split("def ")[0]


def test_login_validation_does_not_reexpose_pin_or_input() -> None:
    app.dependency_overrides[get_db_session] = _override_db_session
    try:
        client = TestClient(app)
        overlong = client.post("/api/auth/login", json={"pin": SECRET_PIN + "0"})
        short = client.post("/api/auth/login", json={"pin": SECRET_PIN[:5]})
        as_object = client.post("/api/auth/login", json={"pin": {"value": SECRET_PIN}})
        as_list = client.post("/api/auth/login", json={"pin": [SECRET_PIN]})
    finally:
        app.dependency_overrides.clear()

    _assert_auth_validation_is_safe(overlong, secret=SECRET_PIN)
    _assert_auth_validation_is_safe(short, secret=SECRET_PIN[:5])
    _assert_auth_validation_is_safe(as_object, secret=SECRET_PIN)
    _assert_auth_validation_is_safe(as_list, secret=SECRET_PIN)


def test_bootstrap_validation_does_not_reexpose_pin_or_input() -> None:
    app.dependency_overrides[get_db_session] = _override_db_session
    try:
        client = TestClient(app)
        response = client.post(
            "/api/bootstrap",
            json={
                "center_name": "합성센터",
                "admin_name": "합성관리자",
                "birth_date": "1980-01-01",
                "sex_code": "FEMALE",
                "start_date": "2026-01-01",
                "pin": SECRET_PIN + "9",
            },
        )
    finally:
        app.dependency_overrides.clear()
    _assert_auth_validation_is_safe(response, secret=SECRET_PIN)
