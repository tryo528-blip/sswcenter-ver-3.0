from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import (
    CurrentAccount,
    authenticate_session,
    is_loopback_request,
    verify_request_csrf,
)
from app.core.settings import Environment, Settings, get_settings
from app.db.models import AccountPermission, UserAccount
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.recipient.service import RecipientService
from app.domains.staff.service import StaffService
from app.domains.w1c.service import W1CService
from app.domains.w1d.service import W1DService

SettingsDependency = Annotated[Settings, Depends(get_settings)]


@lru_cache(maxsize=8)
def _database_runtime(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_postgres_engine(database_url)
    return engine, build_session_factory(engine)


def get_db_session(settings: SettingsDependency) -> Iterator[Session]:
    if settings.database_url is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_not_configured"},
        )
    _, factory = _database_runtime(settings.database_url)
    database_session = factory()
    try:
        yield database_session
    finally:
        database_session.rollback()
        database_session.close()


DatabaseSession = Annotated[Session, Depends(get_db_session)]


def get_current_account(
    request: Request,
    database_session: DatabaseSession,
    settings: SettingsDependency,
) -> CurrentAccount:
    try:
        # The development preview is intentionally explicit and loopback-only
        # at the process level. It still resolves a real seeded ADMIN account so
        # protected list/detail APIs work after a frontend reload without a
        # browser session cookie. Production rejects this setting in Settings.
        if (
            settings.environment is Environment.DEVELOPMENT
            and settings.dev_login_bypass
            and is_loopback_request(request, settings)
        ):
            bypass_account = database_session.scalar(
                select(UserAccount)
                .where(
                    UserAccount.active.is_(True),
                    UserAccount.role_code == "ADMIN",
                )
                .order_by(UserAccount.id.asc())
            )
            if bypass_account is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "development_bypass_account_missing"},
                )
            return CurrentAccount(
                bypass_account.id,
                bypass_account.display_name,
                bypass_account.role_code,
            )
        current_account = authenticate_session(database_session, request, settings)
        database_session.commit()
        return current_account
    except Exception:
        database_session.rollback()
        raise


CurrentAccountDependency = Annotated[CurrentAccount, Depends(get_current_account)]


def require_csrf(
    request: Request,
    current_account: CurrentAccountDependency,
    settings: SettingsDependency,
) -> CurrentAccount:
    if (
        settings.environment is Environment.DEVELOPMENT
        and settings.dev_login_bypass
        and is_loopback_request(request, settings)
    ):
        return current_account
    verify_request_csrf(request, settings)
    return current_account


CsrfAccountDependency = Annotated[CurrentAccount, Depends(require_csrf)]


def require_admin(current_account: CurrentAccountDependency) -> CurrentAccount:
    if current_account.role_code != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "admin_required"},
        )
    return current_account


AdminAccountDependency = Annotated[CurrentAccount, Depends(require_admin)]


def permission_dependency(permission_code: str) -> object:
    def require_permission(
        current_account: CurrentAccountDependency,
        database_session: DatabaseSession,
    ) -> CurrentAccount:
        if current_account.role_code == "ADMIN":
            return current_account
        permission = database_session.scalar(
            select(AccountPermission.id).where(
                AccountPermission.account_id == current_account.id,
                AccountPermission.permission_code == permission_code,
                AccountPermission.revoked_at_utc.is_(None),
            )
        )
        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "permission_required", "permission": permission_code},
            )
        return current_account

    return Depends(require_permission)


def _has_any_permission(
    database_session: Session,
    current_account: CurrentAccount,
    permission_codes: set[str],
) -> bool:
    if current_account.role_code == "ADMIN":
        return True
    permission = database_session.scalar(
        select(AccountPermission.id).where(
            AccountPermission.account_id == current_account.id,
            AccountPermission.permission_code.in_(permission_codes),
            AccountPermission.revoked_at_utc.is_(None),
        )
    )
    return permission is not None


def require_staff_view(
    current_account: CurrentAccountDependency,
    database_session: DatabaseSession,
) -> CurrentAccount:
    if not _has_any_permission(
        database_session,
        current_account,
        {"STAFF_VIEW", "STAFF_MANAGE"},
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_REQUIRED", "permission": "STAFF_VIEW"},
        )
    return current_account


def require_staff_manage(
    current_account: CsrfAccountDependency,
    database_session: DatabaseSession,
) -> CurrentAccount:
    if not _has_any_permission(
        database_session,
        current_account,
        {"STAFF_MANAGE"},
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_REQUIRED", "permission": "STAFF_MANAGE"},
        )
    return current_account


StaffViewAccountDependency = Annotated[CurrentAccount, Depends(require_staff_view)]
StaffManageAccountDependency = Annotated[CurrentAccount, Depends(require_staff_manage)]


def staff_capabilities(
    current_account: CurrentAccountDependency,
    database_session: DatabaseSession,
) -> dict[str, bool]:
    can_view = _has_any_permission(
        database_session,
        current_account,
        {"STAFF_VIEW", "STAFF_MANAGE"},
    )
    can_manage = _has_any_permission(
        database_session,
        current_account,
        {"STAFF_MANAGE"},
    )
    can_recipient_view = _has_any_permission(
        database_session,
        current_account,
        {"RECIPIENT_VIEW", "RECIPIENT_MANAGE"},
    )
    can_recipient_manage = _has_any_permission(
        database_session,
        current_account,
        {"RECIPIENT_MANAGE"},
    )
    return {
        "staff.view": can_view,
        "staff.manage": can_manage,
        "staff.sensitive_identity.reveal": can_manage,
        "recipient.view": can_recipient_view,
        "recipient.manage": can_recipient_manage,
    }


def get_staff_service(
    request: Request,
    database_session: DatabaseSession,
    settings: SettingsDependency,
) -> StaffService:
    request_id = getattr(request.state, "request_id", None)
    return StaffService(
        database_session,
        settings,
        request_id=request_id if isinstance(request_id, UUID) else None,
    )


StaffServiceDependency = Annotated[StaffService, Depends(get_staff_service)]


def require_recipient_view(
    current_account: CurrentAccountDependency,
    database_session: DatabaseSession,
) -> CurrentAccount:
    if not _has_any_permission(
        database_session,
        current_account,
        {"RECIPIENT_VIEW", "RECIPIENT_MANAGE"},
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_REQUIRED", "permission": "RECIPIENT_VIEW"},
        )
    return current_account


def require_recipient_manage(
    current_account: CsrfAccountDependency,
    database_session: DatabaseSession,
) -> CurrentAccount:
    if not _has_any_permission(
        database_session,
        current_account,
        {"RECIPIENT_MANAGE"},
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PERMISSION_REQUIRED", "permission": "RECIPIENT_MANAGE"},
        )
    return current_account


RecipientViewAccountDependency = Annotated[
    CurrentAccount,
    Depends(require_recipient_view),
]
RecipientManageAccountDependency = Annotated[
    CurrentAccount,
    Depends(require_recipient_manage),
]


def get_recipient_service(
    request: Request,
    database_session: DatabaseSession,
) -> RecipientService:
    request_id = getattr(request.state, "request_id", None)
    return RecipientService(
        database_session,
        request_id=request_id if isinstance(request_id, UUID) else None,
    )


RecipientServiceDependency = Annotated[
    RecipientService,
    Depends(get_recipient_service),
]


def get_w1c_service(
    request: Request,
    database_session: DatabaseSession,
) -> W1CService:
    request_id = getattr(request.state, "request_id", None)
    return W1CService(
        database_session,
        request_id=request_id if isinstance(request_id, UUID) else None,
    )


W1CServiceDependency = Annotated[
    W1CService,
    Depends(get_w1c_service),
]


def get_w1d_service(
    request: Request,
    database_session: DatabaseSession,
    settings: SettingsDependency,
) -> W1DService:
    request_id = getattr(request.state, "request_id", None)
    return W1DService(
        database_session,
        settings,
        request_id=request_id if isinstance(request_id, UUID) else None,
    )


W1DServiceDependency = Annotated[
    W1DService,
    Depends(get_w1d_service),
]
