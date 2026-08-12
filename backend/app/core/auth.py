from __future__ import annotations

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    PinProtector,
    csrf_token_signature,
    generate_csrf_token,
    generate_session_token,
    hash_session_token,
    validate_pin,
    verify_csrf_signature,
)
from app.core.settings import Environment, Settings
from app.db.models import (
    AuthEvent,
    AuthRateLimitBucket,
    AuthSession,
    BusinessNumberCounter,
    Center,
    InstallationState,
    Staff,
    StaffEmployment,
    StaffOperationalRolePeriod,
    StaffPositionPeriod,
    UserAccount,
)

UNKNOWN_WINDOW = timedelta(minutes=15)
UNKNOWN_BLOCK = timedelta(minutes=15)
ACCOUNT_BLOCK = timedelta(minutes=15)
UNKNOWN_LIMITS = {
    "DEVICE_UNKNOWN": 10,
    "IP_UNKNOWN": 10,
    "SERVER_UNKNOWN": 30,
}


@dataclass(frozen=True)
class ClientContext:
    device_id: str
    device_cookie: str
    client_ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class CurrentAccount:
    id: int
    display_name: str
    role_code: str


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_cookie: str
    account: CurrentAccount


@dataclass(frozen=True)
class BootstrapInput:
    center_name: str
    admin_name: str
    birth_date: date
    sex_code: str
    start_date: date
    pin: str


class AuthenticationFailure(Exception):
    def __init__(self, code: str, http_status: int = status.HTTP_401_UNAUTHORIZED) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _sign_value(value: str, key: str) -> str:
    signature = hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{signature}"


def _verify_signed_value(value: str | None, key: str) -> str | None:
    if value is None or "." not in value:
        return None
    raw, signature = value.rsplit(".", 1)
    expected = hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not raw or not hmac.compare_digest(signature, expected):
        return None
    return raw


def _request_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


def client_context(request: Request, settings: Settings) -> ClientContext:
    signing_key = settings.secret_value("csrf_signing_key")
    raw_device_id = _verify_signed_value(
        request.cookies.get(settings.device_cookie_name),
        signing_key,
    )
    if raw_device_id is None:
        raw_device_id = generate_csrf_token()
    user_agent = request.headers.get("user-agent")
    return ClientContext(
        device_id=raw_device_id,
        device_cookie=_sign_value(raw_device_id, signing_key),
        client_ip=_request_ip(request),
        user_agent=user_agent[:500] if user_agent else None,
    )


def is_loopback_request(request: Request, settings: Settings) -> bool:
    if settings.environment is Environment.TEST:
        return True
    request_ip = _request_ip(request)
    return request_ip is not None and ipaddress.ip_address(request_ip).is_loopback


def bootstrap_required(database_session: Session) -> bool:
    state = database_session.scalar(
        select(InstallationState).where(InstallationState.singleton_key.is_(True))
    )
    if state is None:
        raise RuntimeError("installation_state singleton is missing")
    active_accounts = database_session.scalar(
        select(func.count()).select_from(UserAccount).where(UserAccount.active.is_(True))
    )
    return not state.bootstrap_completed and active_accounts == 0


def bootstrap_installation(
    database_session: Session,
    payload: BootstrapInput,
    settings: Settings,
) -> CurrentAccount:
    validate_pin(payload.pin)
    if not payload.center_name.strip() or not payload.admin_name.strip():
        raise ValueError("center and administrator names must not be blank")
    state = database_session.scalar(
        select(InstallationState).where(InstallationState.singleton_key.is_(True)).with_for_update()
    )
    if state is None:
        raise RuntimeError("installation_state singleton is missing")
    active_accounts = database_session.scalar(
        select(func.count()).select_from(UserAccount).where(UserAccount.active.is_(True))
    )
    if state.bootstrap_completed or active_accounts != 0:
        raise AuthenticationFailure("bootstrap_already_completed", status.HTTP_409_CONFLICT)

    protector = PinProtector(
        settings.secret_value("pin_pepper"),
        settings.secret_value("pin_lookup_key"),
    )
    center = Center(center_code="CENTER-001", center_name=payload.center_name.strip())
    staff = Staff(
        name=payload.admin_name.strip(),
        display_name=payload.admin_name.strip(),
        birth_date=payload.birth_date,
        sex_code=payload.sex_code,
    )
    database_session.add_all([center, staff])
    database_session.flush()

    account = UserAccount(
        staff_id=staff.id,
        account_code="ADMIN-001",
        display_name=payload.admin_name.strip(),
        role_code="ADMIN",
        pin_hash=protector.hash_pin(payload.pin),
        pin_lookup_hmac=protector.lookup_hmac(payload.pin),
        pin_key_version=1,
    )
    database_session.add(account)
    database_session.flush()

    counter = database_session.get(
        BusinessNumberCounter,
        ("STAFF_EMPLOYMENT", payload.start_date.year),
        with_for_update=True,
    )
    if counter is None:
        counter = BusinessNumberCounter(
            number_type="STAFF_EMPLOYMENT",
            number_year=payload.start_date.year,
            last_sequence=1,
        )
        database_session.add(counter)
        sequence = 1
    else:
        counter.last_sequence += 1
        counter.updated_at_utc = utc_now()
        sequence = counter.last_sequence

    employment = StaffEmployment(
        staff_id=staff.id,
        employment_no=1,
        staff_no=f"{payload.start_date.year}-{sequence:03d}",
        staff_no_year=payload.start_date.year,
        staff_no_sequence=sequence,
        start_date=payload.start_date,
        created_by_account_id=account.id,
        updated_by_account_id=account.id,
    )
    database_session.add(employment)
    database_session.flush()
    database_session.add_all(
        [
            StaffPositionPeriod(
                staff_id=staff.id,
                employment_id=employment.id,
                position_code="MANAGER",
                start_date=payload.start_date,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
            ),
            StaffOperationalRolePeriod(
                staff_id=staff.id,
                employment_id=employment.id,
                role_code="MANAGEMENT_FUNCTION",
                start_date=payload.start_date,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
            ),
        ]
    )
    state.bootstrap_completed = True
    state.bootstrap_completed_at_utc = utc_now()
    state.first_admin_account_id = account.id
    state.installed_app_version = settings.app_version
    try:
        database_session.flush()
    except IntegrityError as exc:
        raise AuthenticationFailure("bootstrap_conflict", status.HTTP_409_CONFLICT) from exc
    return CurrentAccount(account.id, account.display_name, account.role_code)


def _rate_bucket_key(bucket_type: str, context: ClientContext) -> bytes:
    if bucket_type == "DEVICE_UNKNOWN":
        return _sha256(context.device_id)
    if bucket_type == "IP_UNKNOWN":
        return _sha256(context.client_ip or "no-ip")
    return _sha256("sswcenter-server")


def _rate_bucket(
    database_session: Session,
    bucket_type: str,
    context: ClientContext,
) -> AuthRateLimitBucket | None:
    return database_session.scalar(
        select(AuthRateLimitBucket)
        .where(
            AuthRateLimitBucket.bucket_type == bucket_type,
            AuthRateLimitBucket.bucket_key_hash == _rate_bucket_key(bucket_type, context),
        )
        .with_for_update()
    )


def _check_unknown_rate_limits(
    database_session: Session,
    context: ClientContext,
    now: datetime,
) -> None:
    for bucket_type in UNKNOWN_LIMITS:
        bucket = _rate_bucket(database_session, bucket_type, context)
        if bucket is not None and bucket.blocked_until_utc is not None:
            if bucket.blocked_until_utc > now:
                raise AuthenticationFailure("login_rate_limited", status.HTTP_429_TOO_MANY_REQUESTS)


def _record_unknown_failure(
    database_session: Session,
    context: ClientContext,
    now: datetime,
) -> None:
    for bucket_type, limit in UNKNOWN_LIMITS.items():
        within_window = AuthRateLimitBucket.window_started_at_utc > now - UNKNOWN_WINDOW
        next_failure_count = case(
            (within_window, AuthRateLimitBucket.failure_count + 1),
            else_=1,
        )
        next_blocked_until = case(
            (next_failure_count >= limit, now + UNKNOWN_BLOCK),
            (within_window, AuthRateLimitBucket.blocked_until_utc),
            else_=None,
        )
        statement = postgres_insert(AuthRateLimitBucket).values(
            bucket_type=bucket_type,
            bucket_key_hash=_rate_bucket_key(bucket_type, context),
            window_started_at_utc=now,
            failure_count=1,
            blocked_until_utc=None,
            updated_at_utc=now,
        )
        database_session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    AuthRateLimitBucket.bucket_type,
                    AuthRateLimitBucket.bucket_key_hash,
                ],
                set_={
                    "window_started_at_utc": case(
                        (within_window, AuthRateLimitBucket.window_started_at_utc),
                        else_=now,
                    ),
                    "failure_count": next_failure_count,
                    "blocked_until_utc": next_blocked_until,
                    "updated_at_utc": now,
                },
            )
        )


def _auth_event(
    database_session: Session,
    context: ClientContext,
    now: datetime,
    *,
    success: bool,
    account_id: int | None = None,
    reason: str | None = None,
) -> None:
    database_session.add(
        AuthEvent(
            account_id=account_id,
            client_device_hash=_sha256(context.device_id),
            event_type="LOGIN",
            success=success,
            occurred_at_utc=now,
            client_ip=context.client_ip,
            user_agent=context.user_agent,
            reason_code=reason,
        )
    )


def login(
    database_session: Session,
    pin: str,
    context: ClientContext,
    settings: Settings,
) -> IssuedSession:
    now = utc_now()
    _check_unknown_rate_limits(database_session, context, now)
    protector = PinProtector(
        settings.secret_value("pin_pepper"),
        settings.secret_value("pin_lookup_key"),
    )
    try:
        validate_pin(pin)
    except ValueError as exc:
        _record_unknown_failure(database_session, context, now)
        _auth_event(database_session, context, now, success=False, reason="INVALID_PIN")
        raise AuthenticationFailure("invalid_credentials") from exc

    account = database_session.scalar(
        select(UserAccount)
        .where(UserAccount.pin_lookup_hmac == protector.lookup_hmac(pin))
        .with_for_update()
    )
    if account is None:
        _record_unknown_failure(database_session, context, now)
        _auth_event(database_session, context, now, success=False, reason="UNKNOWN_PIN")
        raise AuthenticationFailure("invalid_credentials")

    if account.locked_until_utc is not None and account.locked_until_utc > now:
        _auth_event(
            database_session,
            context,
            now,
            success=False,
            account_id=account.id,
            reason="ACCOUNT_LOCKED",
        )
        raise AuthenticationFailure("account_locked", status.HTTP_423_LOCKED)
    if not account.active or not account.login_allowed:
        _auth_event(
            database_session,
            context,
            now,
            success=False,
            account_id=account.id,
            reason="ACCOUNT_DISABLED",
        )
        raise AuthenticationFailure("invalid_credentials")
    if not protector.verify_pin(account.pin_hash, pin):
        account.failed_count += 1
        if account.failed_count >= 5:
            account.locked_until_utc = now + ACCOUNT_BLOCK
        _auth_event(
            database_session,
            context,
            now,
            success=False,
            account_id=account.id,
            reason="HASH_MISMATCH",
        )
        raise AuthenticationFailure("invalid_credentials")

    account.failed_count = 0
    account.locked_until_utc = None
    account.last_login_at_utc = now
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    csrf_signature = csrf_token_signature(
        session_token,
        csrf_token,
        settings.secret_value("csrf_signing_key"),
    )
    absolute_expires = now + timedelta(minutes=settings.session_absolute_minutes)
    idle_expires = min(
        now + timedelta(minutes=settings.session_idle_minutes),
        absolute_expires,
    )
    database_session.add(
        AuthSession(
            account_id=account.id,
            session_token_hash=hash_session_token(session_token),
            account_session_version=account.session_version,
            issued_at_utc=now,
            idle_expires_at_utc=idle_expires,
            absolute_expires_at_utc=absolute_expires,
            last_seen_at_utc=now,
            client_fingerprint_hash=_sha256(f"{context.device_id}\x00{context.user_agent or ''}"),
        )
    )
    _auth_event(database_session, context, now, success=True, account_id=account.id)
    return IssuedSession(
        session_token=session_token,
        csrf_cookie=f"{csrf_token}.{csrf_signature}",
        account=CurrentAccount(account.id, account.display_name, account.role_code),
    )


def authenticate_session(
    database_session: Session,
    request: Request,
    settings: Settings,
) -> CurrentAccount:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required"},
        )
    auth_session = database_session.scalar(
        select(AuthSession)
        .where(AuthSession.session_token_hash == hash_session_token(raw_token))
        .with_for_update()
    )
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_session"},
        )
    account = database_session.get(UserAccount, auth_session.account_id)
    now = utc_now()
    reason: str | None = None
    if auth_session.revoked_at_utc is not None:
        reason = "revoked_session"
    elif auth_session.idle_expires_at_utc <= now:
        reason = "idle_expired"
    elif auth_session.absolute_expires_at_utc <= now:
        reason = "absolute_expired"
    elif account is None or not account.active or not account.login_allowed:
        reason = "account_disabled"
    elif account.session_version != auth_session.account_session_version:
        reason = "session_version_changed"
    if reason is not None:
        if auth_session.revoked_at_utc is None:
            auth_session.revoked_at_utc = now
            auth_session.revoke_reason = reason
            database_session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": reason},
        )
    if account is None:
        raise RuntimeError("authenticated account unexpectedly missing")
    auth_session.last_seen_at_utc = now
    auth_session.idle_expires_at_utc = min(
        now + timedelta(minutes=settings.session_idle_minutes),
        auth_session.absolute_expires_at_utc,
    )
    return CurrentAccount(account.id, account.display_name, account.role_code)


def verify_request_csrf(request: Request, settings: Settings) -> None:
    session_token = request.cookies.get(settings.session_cookie_name)
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    csrf_header = request.headers.get(settings.csrf_header_name)
    if session_token is None or csrf_cookie is None or csrf_header is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_required"},
        )
    if not hmac.compare_digest(csrf_cookie, csrf_header) or "." not in csrf_cookie:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_mismatch"},
        )
    csrf_token, signature = csrf_cookie.rsplit(".", 1)
    if not verify_csrf_signature(
        session_token,
        csrf_token,
        signature,
        settings.secret_value("csrf_signing_key"),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_invalid"},
        )
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        request_origin = urlsplit(str(request.url))
        try:
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            request_port = request_origin.port or (443 if request_origin.scheme == "https" else 80)
        except ValueError:
            origin_port = -1
            request_port = -2
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname is None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.scheme != request_origin.scheme
            or parsed.hostname.lower() != (request_origin.hostname or "").lower()
            or origin_port != request_port
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "cross_origin_forbidden"},
            )


def revoke_current_session(
    database_session: Session,
    request: Request,
    settings: Settings,
) -> None:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        return
    auth_session = database_session.scalar(
        select(AuthSession).where(AuthSession.session_token_hash == hash_session_token(raw_token))
    )
    if auth_session is not None and auth_session.revoked_at_utc is None:
        auth_session.revoked_at_utc = utc_now()
        auth_session.revoke_reason = "logout"
