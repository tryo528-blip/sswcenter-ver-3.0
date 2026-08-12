from __future__ import annotations

from datetime import date
from enum import StrEnum

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.api.dependencies import (
    CsrfAccountDependency,
    CurrentAccountDependency,
    DatabaseSession,
    SettingsDependency,
)
from app.core.auth import (
    AuthenticationFailure,
    BootstrapInput,
    bootstrap_installation,
    bootstrap_required,
    client_context,
    is_loopback_request,
    login,
    revoke_current_session,
)
from app.core.settings import Environment

router = APIRouter(prefix="/api", tags=["authentication"])


class BootstrapSexCode(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    TEST = "TEST"


class BootstrapRequest(BaseModel):
    center_name: str = Field(min_length=1, max_length=200)
    admin_name: str = Field(min_length=1, max_length=100)
    birth_date: date
    sex_code: BootstrapSexCode
    start_date: date
    pin: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class LoginRequest(BaseModel):
    pin: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _raise_auth_failure(
    exc: AuthenticationFailure,
    headers: dict[str, str] | None = None,
) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code},
        headers=headers,
    ) from exc


def _device_cookie_header(cookie_value: str, settings: SettingsDependency) -> str:
    secure = "; Secure" if settings.cookie_secure else ""
    return (
        f"{settings.device_cookie_name}={cookie_value}; Path=/; "
        f"Max-Age={60 * 60 * 24 * 365}; HttpOnly; SameSite=strict{secure}"
    )


def _set_auth_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_cookie: str,
    device_cookie: str,
    settings: SettingsDependency,
) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_cookie,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.device_cookie_name,
        device_cookie,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=60 * 60 * 24 * 365,
    )


@router.get("/bootstrap/status")
def get_bootstrap_status(database_session: DatabaseSession) -> dict[str, bool]:
    return {"bootstrap_required": bootstrap_required(database_session)}


@router.post("/bootstrap", status_code=status.HTTP_201_CREATED)
def post_bootstrap(
    payload: BootstrapRequest,
    request: Request,
    database_session: DatabaseSession,
    settings: SettingsDependency,
) -> dict[str, object]:
    if not is_loopback_request(request, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "bootstrap_loopback_only"},
        )
    if payload.sex_code is BootstrapSexCode.TEST and settings.environment is Environment.PRODUCTION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_sex_code"},
        )
    try:
        account = bootstrap_installation(
            database_session,
            BootstrapInput(
                center_name=payload.center_name,
                admin_name=payload.admin_name,
                birth_date=payload.birth_date,
                sex_code=payload.sex_code.value,
                start_date=payload.start_date,
                pin=payload.pin,
            ),
            settings,
        )
        database_session.commit()
    except AuthenticationFailure as exc:
        database_session.rollback()
        _raise_auth_failure(exc)
    except ValueError as exc:
        database_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_pin", "message": str(exc)},
        ) from exc
    return {
        "status": "created",
        "account": {
            "id": account.id,
            "display_name": account.display_name,
            "role_code": account.role_code,
        },
    }


@router.post("/auth/login")
def post_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    database_session: DatabaseSession,
    settings: SettingsDependency,
) -> dict[str, object]:
    context = client_context(request, settings)
    try:
        issued = login(database_session, payload.pin, context, settings)
        database_session.commit()
    except AuthenticationFailure as exc:
        database_session.commit()
        _raise_auth_failure(
            exc,
            headers={
                "Set-Cookie": _device_cookie_header(context.device_cookie, settings),
            },
        )
    _set_auth_cookies(
        response,
        session_token=issued.session_token,
        csrf_cookie=issued.csrf_cookie,
        device_cookie=context.device_cookie,
        settings=settings,
    )
    return {
        "account": {
            "id": issued.account.id,
            "display_name": issued.account.display_name,
            "role_code": issued.account.role_code,
        }
    }


@router.get("/auth/me")
def get_me(current_account: CurrentAccountDependency) -> dict[str, object]:
    return {
        "account": {
            "id": current_account.id,
            "display_name": current_account.display_name,
            "role_code": current_account.role_code,
        }
    }


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def post_logout(
    request: Request,
    response: Response,
    _current_account: CsrfAccountDependency,
    database_session: DatabaseSession,
    settings: SettingsDependency,
) -> None:
    revoke_current_session(database_session, request, settings)
    database_session.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
