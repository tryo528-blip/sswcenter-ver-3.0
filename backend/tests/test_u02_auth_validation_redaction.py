from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import BootstrapRequest, LoginRequest
from app.api.w1a_errors import install_w1a_error_contract


def _validation_app() -> FastAPI:
    application = FastAPI()
    install_w1a_error_contract(application)

    @application.post("/api/auth/login")
    def login(payload: LoginRequest) -> dict[str, bool]:
        del payload
        return {"ok": True}

    @application.post("/api/bootstrap")
    def bootstrap(payload: BootstrapRequest) -> dict[str, bool]:
        del payload
        return {"ok": True}

    return application


def test_login_validation_uses_redacted_error_envelope() -> None:
    response = TestClient(_validation_app()).post(
        "/api/auth/login",
        json={"pin": "123"},
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error", "field_errors", "details", "request_id"}
    assert body["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "입력값을 확인하세요.",
    }
    assert body["field_errors"] == [
        {"field": "pin", "message": "입력값을 확인하세요."}
    ]
    assert body["details"] == {}
    assert "input" not in response.text
    assert "123" not in response.text


def test_bootstrap_validation_does_not_echo_pin_or_request_body() -> None:
    submitted_pin = "654321x"
    submitted_center = "SENSITIVE_CENTER_123"
    response = TestClient(_validation_app()).post(
        "/api/bootstrap",
        json={
            "center_name": submitted_center,
            "admin_name": "합성 관리자",
            "birth_date": "1990-01-01",
            "sex_code": "TEST",
            "start_date": "2026-08-15",
            "pin": submitted_pin,
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert {item["field"] for item in body["field_errors"]} == {"pin"}
    assert "input" not in response.text
    assert submitted_pin not in response.text
    assert submitted_center not in response.text


def test_non_auth_validation_keeps_its_existing_default_handler_scope() -> None:
    application = _validation_app()

    @application.post("/api/other")
    def other(payload: LoginRequest) -> dict[str, bool]:
        del payload
        return {"ok": True}

    response = TestClient(application).post("/api/other", json={"pin": "123"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "123"
