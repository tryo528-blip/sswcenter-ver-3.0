"""W1D real PostgreSQL, API, concurrency, authorization, and audit regressions.

Retired recognition-transition and signer-snapshot tests are intentionally absent.
Requires SSWCENTER_W1D_REAL_PG=1 from the isolated PostgreSQL harness.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import CurrentAccount
from app.domains.w1d.schemas import ContractCreateRequest, ServiceTypeCode

if TYPE_CHECKING:
    from app.domains.w1d.service import W1DService

pytestmark = pytest.mark.skipif(
    os.environ.get("SSWCENTER_W1D_REAL_PG") != "1",
    reason="requires the isolated W1D PostgreSQL harness",
)

RECIPIENT_NO_EXACT_RE = re.compile(r"^[0-9]{6,}$")

W1C_HEAD = "20260730_0010_w1c_certification_ledgers"

W1D_REVISION = "20260730_0011_w1d_recipient_contract"

_RUNTIME_REVISION_ENV = "SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION"

SERVICE_HOME_CARE = ServiceTypeCode.HOME_CARE

SERVICE_HOME_BATH = ServiceTypeCode.HOME_BATH

SERVICE_TEMP = ServiceTypeCode.TEMP_HOME_CARE

SERVICE_BARO = ServiceTypeCode.BARO_CARE

W1D_REVERSE_PERIOD_FIELD_ERRORS = [
    {"field": "end_date", "message": "입력값을 확인하세요."},
]


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _expected_runtime_revision() -> str:
    """Exact runtime Alembic revision required by product/catalog assertions.

    The PowerShell wrapper proves historical 0011 lifecycle separately, then
    upgrades to current head and sets SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION.
    When unset (e.g. isolated local runs still at 0011), fall back to the
    historical W1D revision so exact equality is preserved either way.
    """
    provided = os.environ.get(_RUNTIME_REVISION_ENV)
    if provided is None:
        return W1D_REVISION
    text = str(provided).strip()
    if not text:
        return W1D_REVISION
    return text


@dataclass(frozen=True)
class W1DCase:
    account_id: int
    recipient_id: int
    other_recipient_id: int
    pin: str
    role_code: str


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W1D_HARNESS_DATABASE_URL_MISSING")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def session_factory(database_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=database_engine, expire_on_commit=False, autoflush=False)


def _synthetic_pin_for_staff_id(staff_id: int) -> str:
    if not 0 < staff_id <= 999_999:
        _fail("W1D_HARNESS_SYNTHETIC_PIN_SPACE_EXHAUSTED")
    return f"{staff_id:06d}"


def _require_w1d_catalog(engine: Engine) -> None:
    expected_revision = _expected_runtime_revision()
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM erp.alembic_version")
        ).scalar_one_or_none()
        if revision != expected_revision:
            _fail(
                "W1D_MIGRATION_REVISION_NOT_APPLIED: expected "
                + expected_revision
                + " got "
                + str(revision)
            )
        present = connection.execute(
            text("SELECT to_regclass('erp.recipient_contract') IS NOT NULL")
        ).scalar()
        if present is not True:
            _fail("W1D_TABLE_MISSING: erp.recipient_contract")


def _seed_case(factory: sessionmaker[Session]) -> W1DCase:
    from app.core.security import PinProtector
    from app.db.models import Recipient, Staff, UserAccount

    label = uuid4().hex
    protector = PinProtector(
        os.environ["SSWCENTER_PIN_PEPPER"],
        os.environ["SSWCENTER_PIN_LOOKUP_KEY"],
    )
    with factory() as database_session:
        staff = Staff(
            name=f"W1D STAFF {label}",
            birth_date=date(1990, 1, 1),
            sex_code="TEST",
            display_name=f"W1D {label}",
            row_version=1,
        )
        database_session.add(staff)
        database_session.flush()
        pin = _synthetic_pin_for_staff_id(staff.id)
        account = UserAccount(
            staff_id=staff.id,
            account_code=f"W1D_{label}",
            display_name=f"W1D {label}",
            role_code="ADMIN",
            pin_hash=protector.hash_pin(pin),
            pin_lookup_hmac=protector.lookup_hmac(pin),
            pin_key_version=1,
            row_version=1,
        )
        database_session.add(account)
        database_session.flush()
        recipients = [
            Recipient(
                name=f"W1D RECIPIENT {label} {index}",
                birth_date=date(1950, 1, index),
                sex_code="TEST",
                mobile_phone=f"010-7100-{index:04d}",
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                row_version=1,
            )
            for index in (1, 2)
        ]
        database_session.add_all(recipients)
        database_session.commit()
        return W1DCase(
            account_id=account.id,
            recipient_id=recipients[0].id,
            other_recipient_id=recipients[1].id,
            pin=pin,
            role_code="ADMIN",
        )


def _load_service() -> type[W1DService]:
    try:
        from app.domains.w1d.service import W1DService

        return W1DService
    except Exception:
        _fail("W1D_SERVICE_MODULE_MISSING: W1DService")


class _W1DSchemas(Protocol):
    ContractCreateRequest: type[ContractCreateRequest]


def _load_schemas() -> _W1DSchemas:
    try:
        from app.domains.w1d import schemas as w1d_schemas

        return cast(_W1DSchemas, w1d_schemas)
    except Exception:
        _fail("W1D_DOMAIN_MODULE_MISSING: schemas")


def _current_account(case: W1DCase) -> CurrentAccount:
    return CurrentAccount(case.account_id, f"W1D {case.account_id}", case.role_code)


def _error_code(exc: BaseException) -> str:
    return str(getattr(exc, "code", type(exc).__name__))


def _is_uuid(value: object) -> bool:
    try:
        from uuid import UUID

        UUID(str(value))
        return True
    except Exception:
        return False


def _assert_standard_error_envelope(body: dict[str, Any], *, expect_code: str) -> dict[str, Any]:
    """R4-06: exact top-level ErrorEnvelope (no nested field_errors, no detail)."""
    if not isinstance(body, dict):
        _fail("W1D_API_ENVELOPE_NOT_OBJECT")
    if "detail" in body:
        _fail("W1D_API_ENVELOPE_LEGACY_DETAIL_FORBIDDEN")
    allowed = {"error", "field_errors", "details", "request_id"}
    extra = set(body) - allowed
    if extra:
        _fail("W1D_API_ENVELOPE_EXTRA_KEYS: " + ",".join(sorted(extra)))
    for key in allowed:
        if key not in body:
            _fail("W1D_API_ENVELOPE_KEY_MISSING: " + key)
    err = body["error"]
    if not isinstance(err, dict) or set(err.keys()) - {"code", "message"}:
        _fail("W1D_API_ENVELOPE_ERROR_BODY_SHAPE")
    if err.get("code") != expect_code:
        _fail("W1D_API_ENVELOPE_CODE_MISMATCH: " + str(err.get("code")))
    if not isinstance(err.get("message"), str) or not err.get("message"):
        _fail("W1D_API_ENVELOPE_MESSAGE_MISSING")
    if not isinstance(body["field_errors"], list):
        _fail("W1D_API_ENVELOPE_FIELD_ERRORS_NOT_LIST")
    if not isinstance(body["details"], dict):
        _fail("W1D_API_ENVELOPE_DETAILS_NOT_OBJECT")
    if not _is_uuid(body["request_id"]):
        _fail("W1D_API_ENVELOPE_REQUEST_ID_NOT_UUID: " + str(body.get("request_id")))
    return body


def test_w1d_pg_harness_w1c_head_self_check(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """H3: seed, W1C deps, login/auth shape, audit schema ??no W1D product required."""
    with database_engine.connect() as connection:
        role = connection.execute(text("SELECT current_user")).scalar_one()
        if role != "erp_app":
            _fail("W1D_HARNESS_APP_ROLE_MISMATCH: " + str(role))
        revision = connection.execute(
            text("SELECT version_num FROM erp.alembic_version")
        ).scalar_one_or_none()
        allowed_revisions = {W1C_HEAD, W1D_REVISION, _expected_runtime_revision()}
        if revision not in allowed_revisions:
            _fail("W1D_HARNESS_UNEXPECTED_REVISION: " + str(revision))

        # Catalog seed for service types (W1A) ??W1D contracts depend on these codes.
        codes = {
            str(row[0])
            for row in connection.execute(
                text("SELECT code FROM erp.service_type WHERE active IS TRUE")
            ).all()
        }
        for required_service in (
            SERVICE_HOME_CARE,
            SERVICE_HOME_BATH,
            SERVICE_TEMP,
            SERVICE_BARO,
        ):
            if required_service not in codes:
                _fail("W1D_HARNESS_SERVICE_SEED_MISSING: " + required_service)

        groups = {
            str(row[0])
            for row in connection.execute(
                text("SELECT code FROM erp.service_group WHERE active IS TRUE")
            ).all()
        }
        for required_group in ("LONG_TERM_CARE", "LOCAL_CARE", "BARO_CARE"):
            if required_group not in groups:
                _fail("W1D_HARNESS_SERVICE_GROUP_SEED_MISSING: " + required_group)

        if (
            connection.execute(
                text("SELECT to_regclass('erp.business_number_counter') IS NOT NULL")
            ).scalar()
            is not True
        ):
            _fail("W1D_HARNESS_COUNTER_TABLE_MISSING")

        audit_cols = {
            str(row[0])
            for row in connection.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'erp' AND table_name = 'audit_event'
                    """
                )
            ).all()
        }
        for col in (
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
            "request_id",
            "created_from",
        ):
            if col not in audit_cols:
                _fail("W1D_HARNESS_AUDIT_COLUMN_MISSING: " + col)

        # The retired separate-grade containment triggers must not survive 0022.
        trigger_names = {
            str(row[0])
            for row in connection.execute(
                text(
                    """
                    SELECT tgname FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'erp' AND NOT t.tgisinternal
                    """
                )
            ).all()
        }
        for name in (
            "ct_recipient_certification_grade_containment",
            "ct_recipient_grade_period_containment",
        ):
            if name in trigger_names:
                _fail("W1D_HARNESS_RETIRED_W1C_TRIGGER_PRESENT: " + name)

    # The surviving W1C service creates one recognition period with its grade.
    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradeCode,
        )
        from app.domains.w1c.service import W1CService
    except Exception:
        _fail("W1D_HARNESS_W1C_DEPENDENCY_MISSING")

    case = _seed_case(session_factory)
    account = _current_account(case)
    cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1c.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(certification_number=cert_number),
            account,
        )
        cert = w1c.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                start_date=date(2030, 1, 1),
                end_date=date(2030, 12, 31),
                grade_code=GradeCode.GRADE_3,
            ),
            account,
        )
        database_session.commit()
        if cert.grade_code.value != "3":
            _fail("W1D_HARNESS_W1C_GRADE_CREATE_FAILED")

    # Login / CSRF shape used by product API RED (W1C pattern).
    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING")

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": case.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_FAILED: " + str(login.status_code))
        csrf = client.cookies.get("sswcenter_csrf")
        if not csrf:
            _fail("W1D_HARNESS_CSRF_COOKIE_MISSING")

    # Cleanup residual check for this connection pool (no open transaction).
    with database_engine.connect() as connection:
        idle = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM pg_stat_activity
                WHERE datname = current_database()
                  AND state = 'idle in transaction'
                  AND pid <> pg_backend_pid()
                """
            )
        ).scalar_one()
        if int(idle) != 0:
            _fail("W1D_HARNESS_IDLE_IN_TRANSACTION_RESIDUAL: " + str(idle))


def _counter_sequence(connection: Connection) -> int | None:
    value = connection.execute(
        text(
            """
            SELECT last_sequence FROM erp.business_number_counter
            WHERE number_type = 'RECIPIENT_NO' AND number_year = 0
            """
        )
    ).scalar_one_or_none()
    return None if value is None else int(value)


def _jsonb_encode(raw: Any, *, label: str) -> str:
    """Canonical encode of a jsonb scalar; fail closed on decode/type errors.

    R10-01: callers COALESCE to a JSON array, so raw SQL NULL / driver None is a
    query failure — never soft-pass as the string \"null\" (equal fingerprints).
    """
    if raw is None:
        _fail(f"W1D_HARNESS_SNAPSHOT_NULL_{label}")
    if isinstance(raw, (dict, list)):
        data = raw
    else:
        try:
            data = json.loads(str(raw))
        except Exception as exc:
            _fail(f"W1D_HARNESS_SNAPSHOT_DECODE_{label}: {type(exc).__name__}")
    if not isinstance(data, (dict, list)):
        _fail(f"W1D_HARNESS_SNAPSHOT_TYPE_{label}")
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def _full_ledger_fingerprint(
    connection: Connection,
    recipient_id: int,
) -> str:
    """Fail-closed canonical full-row ledger snapshot (R8-03 / J-H02).

    After catalog is required, query/decode failures raise W1D_HARNESS_*.
    Uses to_jsonb(t.*) ordered by stable keys. Counter and audit are full
    cluster row sets (workers=1 isolated harness).
    """
    parts: list[str] = []
    queries = (
        (
            "recipient",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient t WHERE t.id = :rid),
                '[]'::jsonb
            )
            """,
            True,
        ),
        (
            "identity",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.recipient_id)
                 FROM erp.recipient_certification_identity t
                 WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            True,
        ),
        (
            "cert",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient_certification_period t WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            True,
        ),
        (
            "contract",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient_contract t WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            True,
        ),
        (
            "counter",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.number_type, t.number_year)
                 FROM erp.business_number_counter t),
                '[]'::jsonb
            )
            """,
            False,
        ),
        (
            "audit",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.audit_event t),
                '[]'::jsonb
            )
            """,
            False,
        ),
    )
    for label, sql, bind_rid in queries:
        try:
            if bind_rid:
                raw = connection.execute(text(sql), {"rid": recipient_id}).scalar()
            else:
                raw = connection.execute(text(sql)).scalar()
        except Exception as exc:
            _fail(f"W1D_HARNESS_SNAPSHOT_QUERY_{label}: {type(exc).__name__}")
        parts.append(label + "=" + _jsonb_encode(raw, label=label))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _all_audit_rows(connection: Connection) -> list[dict[str, Any]]:
    """Full cluster audit_event rows via to_jsonb; fail closed (R9-02).

    Never silently drop non-dict elements. Query/decode/type failures raise
    W1D_HARNESS_* markers so two failed snapshots cannot compare equal.
    """
    try:
        raw = connection.execute(
            text(
                """
                SELECT COALESCE(
                    (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                     FROM erp.audit_event t),
                    '[]'::jsonb
                )
                """
            )
        ).scalar()
    except Exception as exc:
        _fail(f"W1D_HARNESS_AUDIT_SNAPSHOT_QUERY: {type(exc).__name__}")
    encoded = _jsonb_encode(raw, label="AUDIT_ROWS")
    try:
        data = json.loads(encoded)
    except Exception as exc:
        _fail(f"W1D_HARNESS_AUDIT_SNAPSHOT_DECODE: {type(exc).__name__}")
    if not isinstance(data, list):
        _fail("W1D_HARNESS_AUDIT_SNAPSHOT_TYPE")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            _fail(f"W1D_HARNESS_AUDIT_SNAPSHOT_NON_DICT: index={idx}")
        out.append(dict(item))
    return out


def _canonical_audit_rows_json(rows: list[dict[str, Any]]) -> str:
    """Deterministic canonical JSON for full audit row-set equality."""
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)


def _write_zero_pair(connection: Connection, recipient_id: int) -> tuple[str, str]:
    """Full ledger fingerprint + complete audit row-set (R11 / J-W1D-R4-H01)."""
    fingerprint = _full_ledger_fingerprint(connection, recipient_id)
    audit_canon = _canonical_audit_rows_json(_all_audit_rows(connection))
    return fingerprint, audit_canon


def _assert_write_zero_pair(
    connection: Connection,
    recipient_id: int,
    before_fp: str,
    before_audit: str,
    *,
    label: str,
) -> None:
    after_fp, after_audit = _write_zero_pair(connection, recipient_id)
    if after_fp != before_fp:
        _fail(label + "_FINGERPRINT_CHANGED")
    if after_audit != before_audit:
        _fail(label + "_AUDIT_ROWSET_CHANGED")


def _assert_recipient_no_exact(value: object, *, label: str) -> str:
    """J-W1D-R5-M01 / R18: type is str + exact ^[0-9]{6,}$ on the raw value.

    No str(), strip(), whitespace normalization, numeric coercion, or subclass.
    """
    if type(value) is not str:
        _fail(label + "_NOT_STR")
    if not RECIPIENT_NO_EXACT_RE.fullmatch(value):
        _fail(label + "_FORMAT")
    return value


def _r18_recipient_no_mutant_selfcheck() -> None:
    """Pure M01 mutants (no DB). Fail closed if acceptance regresses."""

    def _accepts(value: object) -> bool:
        try:
            if type(value) is not str:
                return False
            return bool(RECIPIENT_NO_EXACT_RE.fullmatch(value))
        except Exception:
            return False

    # Must reject.
    for bad in (
        " 000001",
        "000001 ",
        "\t000001",
        1,
        True,
        False,
        None,
        "00001",
        "+000001",
        "000001.0",
        "00000a",
        "",
    ):
        if _accepts(bad):
            _fail(f"W1D_R18_M01_MUTANT_ACCEPTED:{type(bad).__name__}:{bad!r}")
    # Must accept canonical six-plus ASCII digits.
    if not _accepts("000001"):
        _fail("W1D_R18_M01_MUTANT_CANONICAL_REJECTED")
    if not _accepts("1234567890"):
        _fail("W1D_R18_M01_MUTANT_LONG_REJECTED")


def _canonical_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text_value = str(value)
    return text_value[:10] if len(text_value) >= 10 else text_value


def test_w1d_pg_00_first_contract_recipient_no_race_and_rollback(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """J-H01/N1/N2: virgin counter absent; first product issuance; re-contract."""
    _require_w1d_catalog(database_engine)
    _r18_recipient_no_mutant_selfcheck()
    case = _seed_case(session_factory)
    case_second = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()

    with database_engine.connect() as connection:
        if (
            connection.execute(
                text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
                {"id": case.recipient_id},
            ).scalar_one()
            is not None
        ):
            _fail("W1D_REC03_PRECONDITION_RECIPIENT_NO_ALREADY_SET")
        # J-H01: virgin cluster MUST have absent counter row ??never DELETE/reset.
        before_counter = _counter_sequence(connection)
        if before_counter is not None:
            _fail("W1D_REC03_COUNTER_NOT_VIRGIN: expected None got " + str(before_counter))
        expected_after = 1

    def worker(service_code: ServiceTypeCode) -> str:
        engine = create_engine(os.environ["SSWCENTER_DATABASE_URL"], pool_pre_ping=True)
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        try:
            with factory() as database_session:
                service = service_cls(database_session)
                service.create_contract(
                    case.recipient_id,
                    schemas.ContractCreateRequest(
                        service_type_code=service_code,
                        start_date=date(2026, 11, 1),
                        end_date=date(2026, 11, 30),
                    ),
                    _current_account(case),
                )
                database_session.commit()
                return "ok"
        except Exception as exc:
            return _error_code(exc)
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(worker, SERVICE_HOME_CARE),
            pool.submit(worker, SERVICE_HOME_BATH),
        ]
        results = [future.result(timeout=30) for future in futures]

    successes = [item for item in results if item == "ok"]
    if len(successes) != 2:
        _fail("W1D_REC03_FIRST_CONTRACT_RACE_SUCCESS_COUNT: " + ",".join(results))

    with database_engine.connect() as connection:
        recipient_no = connection.execute(
            text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
            {"id": case.recipient_id},
        ).scalar_one()
        # J-W1D-R5-M01: exact decimal format on first issuance (not merely non-empty).
        recipient_no = _assert_recipient_no_exact(
            recipient_no, label="W1D_REC03_RECIPIENT_NO_FIRST"
        )
        contract_count = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.recipient_contract
                WHERE recipient_id = :id AND invalidated_at_utc IS NULL
                """
            ),
            {"id": case.recipient_id},
        ).scalar_one()
        if int(contract_count) != 2:
            _fail("W1D_REC03_CONTRACT_COUNT_AFTER_RACE: " + str(contract_count))
        after_counter = _counter_sequence(connection)
        if after_counter is None or int(after_counter) != expected_after:
            _fail(
                "W1D_REC03_COUNTER_DELTA_INVALID: before="
                + str(before_counter)
                + " after="
                + str(after_counter)
                + " expected="
                + str(expected_after)
            )
        counter_after_race = int(after_counter)
        # Global uniqueness of the issued number.
        dup = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.recipient
                WHERE recipient_no = :no
                """
            ),
            {"no": recipient_no},
        ).scalar_one()
        if int(dup) != 1:
            _fail("W1D_REC03_RECIPIENT_NO_NOT_GLOBALLY_UNIQUE: " + str(dup))

    # J-H01: second recipient first-contract advances counter 1 ??2 (monotonic).
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.create_contract(
                case_second.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2026, 11, 1),
                    end_date=date(2026, 11, 30),
                ),
                _current_account(case_second),
            )
            database_session.commit()
        except Exception as exc:
            _fail("W1D_REC03_SECOND_RECIPIENT_ISSUE_FAILED: " + _error_code(exc))
    with database_engine.connect() as connection:
        second_no = connection.execute(
            text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
            {"id": case_second.recipient_id},
        ).scalar_one()
        # J-W1D-R5-M01: exact format on second recipient issuance + inequality.
        second_no = _assert_recipient_no_exact(second_no, label="W1D_REC03_SECOND_RECIPIENT_NO")
        if second_no == recipient_no:
            _fail("W1D_REC03_SECOND_RECIPIENT_NO_NOT_DISTINCT")
        after_second = _counter_sequence(connection)
        if after_second is None or int(after_second) != 2:
            _fail("W1D_REC03_COUNTER_NOT_2_AFTER_SECOND: " + str(after_second))
        counter_after_race = 2  # baseline for re-contract on first recipient

    # N2: re-contract after closed race period; non-overlapping; no number change.
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.create_contract(
                case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2026, 12, 1),
                    end_date=date(2026, 12, 31),
                ),
                _current_account(case),
            )
            database_session.commit()
        except Exception as exc:
            _fail("W1D_REC03_RECONTRACT_FAILED: " + _error_code(exc))

    with database_engine.connect() as connection:
        again = connection.execute(
            text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
            {"id": case.recipient_id},
        ).scalar_one()
        # J-W1D-R5-M01: final persisted + immutable re-contract value exact format.
        again = _assert_recipient_no_exact(again, label="W1D_REC03_RECIPIENT_NO_RECONTRACT")
        if again != recipient_no:
            _fail("W1D_REC03_RECIPIENT_NO_MUTATED_ON_RECONTRACT")
        counter_after_re = _counter_sequence(connection)
        if counter_after_re is None or int(counter_after_re) != counter_after_race:
            _fail(
                "W1D_REC03_COUNTER_ADVANCED_ON_RECONTRACT: "
                + f"{counter_after_race}->{counter_after_re}"
            )

    # Fault injection rollback (create path seam after_contract_insert).
    case2 = _seed_case(session_factory)
    try:
        from app.domains.w1d import fault as w1d_fault
    except Exception:
        _fail("W1D_FAULT_SEAM_MISSING: app.domains.w1d.fault")
    set_fault = getattr(w1d_fault, "set_fault_point", None) or getattr(w1d_fault, "install", None)
    if set_fault is None:
        _fail("W1D_FAULT_SEAM_MISSING: install/set_fault_point")
    with database_engine.connect() as connection:
        before_fault_counter = _counter_sequence(connection)
    set_fault("after_contract_insert")
    try:
        with session_factory() as database_session:
            service = service_cls(database_session)
            try:
                service.create_contract(
                    case2.recipient_id,
                    schemas.ContractCreateRequest(
                        service_type_code=SERVICE_HOME_CARE,
                        start_date=date(2028, 1, 1),
                        end_date=date(2028, 1, 31),
                    ),
                    _current_account(case2),
                )
                database_session.commit()
                _fail("W1D_REC03_FAULT_DID_NOT_RAISE")
            except Exception as exc:
                database_session.rollback()
                text_exc = f"{type(exc).__name__}:{exc}"
                if "W1D_FAULT:after_contract_insert" not in text_exc:
                    _fail("W1D_REC03_FAULT_WRONG_EXCEPTION: " + text_exc[:200])
    finally:
        set_fault(None)
    with database_engine.connect() as connection:
        if (
            connection.execute(
                text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
                {"id": case2.recipient_id},
            ).scalar_one()
            is not None
        ):
            _fail("W1D_REC03_FAULT_LEFT_RECIPIENT_NO")
        if (
            int(
                connection.execute(
                    text("SELECT COUNT(*) FROM erp.recipient_contract WHERE recipient_id = :id"),
                    {"id": case2.recipient_id},
                ).scalar_one()
            )
            != 0
        ):
            _fail("W1D_REC03_FAULT_LEFT_CONTRACT")
        after_fault_counter = _counter_sequence(connection)
        if after_fault_counter != before_fault_counter:
            _fail(
                "W1D_REC03_FAULT_ADVANCED_COUNTER: "
                + f"{before_fault_counter}->{after_fault_counter}"
            )


def test_w1d_pg_01_catalog_revision_and_nullable_round_trip(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """W1-CON-01: catalog + minimal nullable contract round trip."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()

    with session_factory() as database_session:
        service = service_cls(database_session)
        created = service.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2026, 7, 1),
            ),
            _current_account(case),
        )
        database_session.commit()

    if getattr(created, "service_start_date", "missing") is not None:
        _fail("W1D_CON01_SERVICE_START_NOT_NULL_ON_MINIMAL")
    if hasattr(created, "signer_name"):
        _fail("W1D_SIG01_RETIRED_SIGNER_ON_RESPONSE")
    if hasattr(created, "contract_no"):
        _fail("W1D_ABS08_CONTRACT_NO_ON_RESPONSE")

    with database_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT service_start_date, end_date, end_reason_text
                    FROM erp.recipient_contract WHERE id = :id
                    """
                ),
                {"id": created.id},
            )
            .mappings()
            .one()
        )
        for column in row:
            if row[column] is not None:
                _fail("W1D_CON01_DB_NULLABLE_ROUND_TRIP_FAILED: " + column)


def test_w1d_pg_02_period_conflicts_and_same_group_allow(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """W1-CON-04 period matrix."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    def create(
        service_code: ServiceTypeCode,
        start: date,
        end: date | None,
    ) -> tuple[str, object]:
        with session_factory() as database_session:
            service = service_cls(database_session)
            try:
                result = service.create_contract(
                    case.recipient_id,
                    schemas.ContractCreateRequest(
                        service_type_code=service_code,
                        start_date=start,
                        end_date=end,
                    ),
                    account,
                )
                database_session.commit()
                return ("ok", result)
            except Exception as exc:
                database_session.rollback()
                return ("err", _error_code(exc))

    first = create(SERVICE_HOME_CARE, date(2026, 8, 1), date(2026, 8, 31))
    if first[0] != "ok":
        _fail("W1D_CON04_BASE_CONTRACT_CREATE_FAILED: " + str(first[1]))
    same_service = create(SERVICE_HOME_CARE, date(2026, 8, 31), date(2026, 9, 15))
    if same_service != ("err", "CONTRACT_SERVICE_PERIOD_CONFLICT"):
        _fail("W1D_CON04_SAME_SERVICE_CONFLICT_MISSING: " + str(same_service))
    adjacent = create(SERVICE_HOME_CARE, date(2026, 9, 1), date(2026, 9, 30))
    if adjacent[0] != "ok":
        _fail("W1D_CON04_NEXT_DAY_ADJACENCY_REJECTED: " + str(adjacent[1]))
    same_group = create(SERVICE_HOME_BATH, date(2026, 8, 10), date(2026, 8, 20))
    if same_group[0] != "ok":
        _fail("W1D_CON04_SAME_GROUP_DIFFERENT_SERVICE_REJECTED: " + str(same_group[1]))
    cross = create(SERVICE_TEMP, date(2026, 8, 15), date(2026, 8, 25))
    if cross != ("err", "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT"):
        _fail("W1D_CON04_CROSS_GROUP_CONFLICT_MISSING: " + str(cross))
    reverse = create(SERVICE_BARO, date(2026, 10, 10), date(2026, 10, 1))
    if reverse[0] != "err":
        _fail("W1D_CON04_REVERSE_PERIOD_ACCEPTED")

    # J-M05: open-ended base then same-service / cross-group conflict; same-group allow.
    open_case = _seed_case(session_factory)
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.create_contract(
                open_case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2032, 1, 1),
                    end_date=None,
                ),
                account,
            )
            database_session.commit()
        except Exception as exc:
            _fail("W1D_CON04_OPEN_ENDED_BASE_FAILED: " + _error_code(exc))
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.create_contract(
                open_case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2032, 6, 1),
                    end_date=date(2032, 6, 30),
                ),
                account,
            )
            database_session.commit()
            _fail("W1D_CON04_OPEN_ENDED_SAME_SERVICE_ACCEPTED")
        except Exception as exc:
            database_session.rollback()
            if _error_code(exc) != "CONTRACT_SERVICE_PERIOD_CONFLICT":
                _fail("W1D_CON04_OPEN_ENDED_SAME_SERVICE_CODE: " + _error_code(exc))
        try:
            service.create_contract(
                open_case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_TEMP,
                    start_date=date(2032, 3, 1),
                    end_date=date(2032, 3, 31),
                ),
                account,
            )
            database_session.commit()
            _fail("W1D_CON04_OPEN_ENDED_CROSS_GROUP_ACCEPTED")
        except Exception as exc:
            database_session.rollback()
            if _error_code(exc) != "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT":
                _fail("W1D_CON04_OPEN_ENDED_CROSS_GROUP_CODE: " + _error_code(exc))
        try:
            service.create_contract(
                open_case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_BATH,
                    start_date=date(2032, 2, 1),
                    end_date=date(2032, 2, 28),
                ),
                account,
            )
            database_session.commit()
        except Exception as exc:
            _fail("W1D_CON04_OPEN_ENDED_SAME_GROUP_REJECTED: " + _error_code(exc))


def test_w1d_pg_03_reactivation_forbidden_and_new_contract(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """W1-CON-03 reactivation guard."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    with session_factory() as database_session:
        service = service_cls(database_session)
        created = service.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            ),
            account,
        )
        database_session.commit()
        contract_id = created.id

    with database_engine.connect() as connection:
        transaction = connection.begin()
        try:
            try:
                connection.execute(
                    text("UPDATE erp.recipient_contract SET end_date = NULL WHERE id = :id"),
                    {"id": contract_id},
                )
                transaction.commit()
                _fail("W1D_CON03_REACTIVATION_ALLOWED")
            except Exception:
                transaction.rollback()
        finally:
            if transaction.is_active:
                transaction.rollback()

    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.create_contract(
                case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2026, 2, 1),
                    end_date=date(2026, 2, 28),
                ),
                account,
            )
            database_session.commit()
        except Exception as exc:
            _fail("W1D_CON03_NEW_CONTRACT_AFTER_END_FAILED: " + _error_code(exc))


def test_w1d_pg_06_api_auth_csrf_and_error_envelope(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """M1: unauth 401, CSRF exact 403 + write 0, independent payloads, conflicts."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)

    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING")

    collection = f"/api/v1/recipients/{case.recipient_id}/contracts"
    payload_a = {
        "service_type_code": SERVICE_HOME_CARE,
        "start_date": "2029-01-01",
        "end_date": "2029-01-31",
    }
    payload_b = {
        "service_type_code": SERVICE_HOME_BATH,
        "start_date": "2029-02-01",
        "end_date": "2029-02-28",
    }

    with TestClient(app) as client:
        with database_engine.connect() as connection:
            snap_u = _full_ledger_fingerprint(connection, case.recipient_id)
        unauth = client.post(collection, json=payload_a)
        if unauth.status_code != 401:
            _fail("W1D_API_UNAUTH_NOT_401: " + str(unauth.status_code))
        _assert_standard_error_envelope(unauth.json(), expect_code="AUTHENTICATION_REQUIRED")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_u:
                _fail("W1D_API_UNAUTH_WROTE_ROWS")

        login = client.post("/api/auth/login", json={"pin": case.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_FAILED: " + str(login.status_code))
        csrf = client.cookies.get("sswcenter_csrf")
        if not csrf:
            _fail("W1D_HARNESS_CSRF_COOKIE_MISSING")

        with database_engine.connect() as connection:
            before_contracts = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM erp.recipient_contract WHERE recipient_id = :id"),
                    {"id": case.recipient_id},
                ).scalar_one()
            )

        # Independent no-CSRF payload (M1): exact 403 CSRF_REQUIRED, top-level envelope, write 0.
        with database_engine.connect() as connection:
            snap_csrf = _full_ledger_fingerprint(connection, case.recipient_id)
        no_csrf = client.post(collection, json=payload_a)
        if no_csrf.status_code != 403:
            _fail("W1D_API_CSRF_NOT_403: " + str(no_csrf.status_code))
        _assert_standard_error_envelope(no_csrf.json(), expect_code="CSRF_REQUIRED")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_csrf:
                _fail("W1D_API_CSRF_LEFT_DB_WRITES")
            after_no_csrf = int(
                connection.execute(
                    text("SELECT COUNT(*) FROM erp.recipient_contract WHERE recipient_id = :id"),
                    {"id": case.recipient_id},
                ).scalar_one()
            )
        if after_no_csrf != before_contracts:
            _fail("W1D_API_CSRF_LEFT_DB_WRITES_COUNT")

        headers = {"X-CSRF-Token": csrf}
        created = client.post(collection, json=payload_b, headers=headers)
        if created.status_code != 201:
            _fail("W1D_API_MINIMAL_CREATE_NOT_201: " + str(created.status_code))
        body = created.json()
        if "contract_no" in body:
            _fail("W1D_ABS08_API_CONTRACT_NO_PRESENT")

        conflict = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_BATH,
                "start_date": "2029-02-15",
                "end_date": "2029-03-01",
            },
            headers=headers,
        )
        if conflict.status_code != 409:
            _fail("W1D_API_SERVICE_CONFLICT_NOT_409: " + str(conflict.status_code))
        _assert_standard_error_envelope(
            conflict.json(), expect_code="CONTRACT_SERVICE_PERIOD_CONFLICT"
        )


def test_w1d_pg_09_raw_cross_group_insert_serialization(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """R8-06: external blocker + dual Lock wait; exact 23P01+constraint pair."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    with database_engine.connect() as connection:
        home = int(
            connection.execute(
                text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE'")
            ).scalar_one()
        )
        temp = int(
            connection.execute(
                text("SELECT id FROM erp.service_type WHERE code = 'TEMP_HOME_CARE'")
            ).scalar_one()
        )
        bath = int(
            connection.execute(
                text("SELECT id FROM erp.service_type WHERE code = 'HOME_BATH'")
            ).scalar_one()
        )

    def concurrent_raw_inserts(
        *,
        recipient_id: int,
        account_id: int,
        stid_a: int,
        stid_b: int,
        name_a: str,
        name_b: str,
        start_date: date,
        end_date: date,
        expect_ok: int,
        fail_label: str,
        require_exact_cross_group_fail: bool,
    ) -> list[str]:
        """Blocker dual Lock wait; fail-closed teardown never swallows cleanup (R10-05)."""
        results: dict[str, str] = {}
        results_lock = threading.Lock()
        harness_errors: list[str] = []
        ready_barrier = threading.Barrier(3, timeout=20)  # 2 workers + main
        both_waiting = threading.Event()
        stop_monitor = threading.Event()
        monitor_errors: list[str] = []
        blocker_name = "w1d-raw-blocker"
        mon: threading.Thread | None = None
        t1: threading.Thread | None = None
        t2: threading.Thread | None = None
        blocker_engine = None
        blocker_conn = None
        blocker_tx = None
        blocker_done = False
        fail_marker: str | None = None

        def _record_harness(msg: str) -> None:
            with results_lock:
                harness_errors.append(msg)

        def worker(stid: int, app_name: str) -> None:
            engine = None
            conn = None
            tx = None
            try:
                engine = create_engine(
                    os.environ["SSWCENTER_DATABASE_URL"],
                    pool_pre_ping=True,
                    connect_args={"options": f"-c application_name={app_name}"},
                )
                conn = engine.connect()
                tx = conn.begin()
                ready_barrier.wait()
                try:
                    conn.execute(
                        text("SELECT id FROM erp.recipient WHERE id = :id FOR UPDATE"),
                        {"id": recipient_id},
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO erp.recipient_contract (
                                recipient_id, service_type_id, start_date, end_date,
                                created_by_account_id, updated_by_account_id, row_version
                            ) VALUES (
                                :rid, :stid, :start_d, :end_d, :aid, :aid, 1
                            )
                            """
                        ),
                        {
                            "rid": recipient_id,
                            "stid": stid,
                            "start_d": start_date,
                            "end_d": end_date,
                            "aid": account_id,
                        },
                    )
                    tx.commit()
                    tx = None
                    with results_lock:
                        results[app_name] = "ok"
                except Exception as exc:
                    # Expected product path may raise 23P01; cleanup errors still recorded.
                    if tx is not None:
                        try:
                            tx.rollback()
                        except Exception as rb_exc:
                            _record_harness(f"{app_name}:rollback:{type(rb_exc).__name__}")
                        tx = None
                    orig = getattr(exc, "orig", None)
                    sqlstate = getattr(orig, "sqlstate", None) or getattr(
                        getattr(orig, "diag", None), "sqlstate", None
                    )
                    cname = getattr(getattr(orig, "diag", None), "constraint_name", None)
                    with results_lock:
                        results[app_name] = f"err:{sqlstate}:{cname}"
                    # Non-product exceptions (setup/unexpected) also go to harness channel.
                    if sqlstate != "23P01" and require_exact_cross_group_fail is False:
                        pass  # same-group expects ok only; unexpected recorded below
                    if sqlstate is None and cname is None:
                        _record_harness(f"{app_name}:insert:{type(exc).__name__}:{exc}")
            except Exception as exc:
                _record_harness(f"{app_name}:setup:{type(exc).__name__}:{exc}")
            finally:
                if tx is not None:
                    try:
                        tx.rollback()
                    except Exception as rb_exc:
                        _record_harness(f"{app_name}:final_rollback:{type(rb_exc).__name__}")
                if conn is not None:
                    try:
                        conn.close()
                    except Exception as cl_exc:
                        _record_harness(f"{app_name}:close:{type(cl_exc).__name__}")
                if engine is not None:
                    try:
                        engine.dispose()
                    except Exception as ds_exc:
                        _record_harness(f"{app_name}:dispose:{type(ds_exc).__name__}")

        def monitor() -> None:
            try:
                deadline = time.time() + 25
                while time.time() < deadline and not stop_monitor.is_set():
                    with database_engine.connect() as connection:
                        waiting = connection.execute(
                            text(
                                """
                                SELECT COUNT(DISTINCT application_name)
                                FROM pg_stat_activity
                                WHERE application_name IN (:a, :b)
                                  AND wait_event_type = 'Lock'
                                """
                            ),
                            {"a": name_a, "b": name_b},
                        ).scalar_one()
                        if int(waiting) >= 2:
                            both_waiting.set()
                            return
                    time.sleep(0.01)
            except Exception as exc:
                monitor_errors.append(f"{type(exc).__name__}:{exc}")

        def _release_blocker(*, commit: bool) -> None:
            """Attempt commit/rollback, close, dispose; record every failure (R10-05)."""
            nonlocal blocker_done, blocker_tx, blocker_conn, blocker_engine
            if blocker_done:
                return
            errors: list[str] = []
            if blocker_tx is not None:
                try:
                    if commit:
                        blocker_tx.commit()
                    else:
                        blocker_tx.rollback()
                except Exception as exc:
                    errors.append(f"tx:{type(exc).__name__}:{exc}")
                    try:
                        blocker_tx.rollback()
                    except Exception as rb_exc:
                        errors.append(f"tx_rollback:{type(rb_exc).__name__}")
                blocker_tx = None
            if blocker_conn is not None:
                try:
                    blocker_conn.close()
                except Exception as exc:
                    errors.append(f"close:{type(exc).__name__}")
                blocker_conn = None
            if blocker_engine is not None:
                try:
                    blocker_engine.dispose()
                except Exception as exc:
                    errors.append(f"dispose:{type(exc).__name__}")
                blocker_engine = None
            blocker_done = True
            if errors:
                _record_harness("blocker:" + ";".join(errors))

        def _assert_no_residual_sessions() -> None:
            try:
                with database_engine.connect() as connection:
                    residual = (
                        connection.execute(
                            text(
                                """
                            SELECT application_name, COUNT(*) AS n
                            FROM pg_stat_activity
                            WHERE application_name IN (:a, :b, :blocker)
                            GROUP BY application_name
                            """
                            ),
                            {"a": name_a, "b": name_b, "blocker": blocker_name},
                        )
                        .mappings()
                        .all()
                    )
            except Exception as exc:
                _fail(fail_label + "_SESSION_QUERY_FAILED: " + type(exc).__name__)
            if residual:
                detail = ",".join(f"{r['application_name']}={r['n']}" for r in residual)
                _fail(fail_label + "_SESSION_RESIDUAL: " + detail)

        try:
            blocker_engine = create_engine(
                os.environ["SSWCENTER_DATABASE_URL"],
                pool_pre_ping=True,
                connect_args={"options": f"-c application_name={blocker_name}"},
            )
            blocker_conn = blocker_engine.connect()
            blocker_tx = blocker_conn.begin()
            blocker_conn.execute(
                text("SELECT id FROM erp.recipient WHERE id = :id FOR UPDATE"),
                {"id": recipient_id},
            )

            mon = threading.Thread(target=monitor, daemon=True)
            mon.start()
            t1 = threading.Thread(target=worker, args=(stid_a, name_a), daemon=True)
            t2 = threading.Thread(target=worker, args=(stid_b, name_b), daemon=True)
            t1.start()
            t2.start()
            try:
                ready_barrier.wait()
            except Exception as exc:
                fail_marker = fail_label + "_READY_BARRIER: " + type(exc).__name__
                raise RuntimeError(fail_marker) from exc

            observed = both_waiting.wait(timeout=20)
            if not observed:
                fail_marker = fail_label + "_DUAL_LOCK_WAIT_NOT_OBSERVED"
                raise RuntimeError(fail_marker)

            _release_blocker(commit=True)

            if mon is not None:
                mon.join(timeout=3)
            if mon is not None and mon.is_alive():
                fail_marker = fail_label + "_LOCK_MONITOR_JOIN_TIMEOUT"
                raise RuntimeError(fail_marker)
            if monitor_errors:
                fail_marker = fail_label + "_LOCK_MONITOR_EXCEPTION: " + monitor_errors[0][:200]
                raise RuntimeError(fail_marker)
            if t1 is not None:
                t1.join(timeout=60)
            if t2 is not None:
                t2.join(timeout=60)
            if (t1 is not None and t1.is_alive()) or (t2 is not None and t2.is_alive()):
                fail_marker = fail_label + "_WORKER_JOIN_TIMEOUT"
                raise RuntimeError(fail_marker)
            with results_lock:
                he = list(harness_errors)
            if he:
                fail_marker = fail_label + "_CLEANUP_OR_SETUP: " + he[0][:200]
                raise RuntimeError(fail_marker)
            ordered = [results.get(name_a, "missing"), results.get(name_b, "missing")]
            ok = sum(1 for r in ordered if r == "ok")
            if ok != expect_ok:
                fail_marker = (
                    fail_label + "_OK_COUNT: " + ",".join(ordered) + f" ok={ok} expect={expect_ok}"
                )
                raise RuntimeError(fail_marker)
            if require_exact_cross_group_fail:
                sealed = [
                    r
                    for r in ordered
                    if r.startswith("err:")
                    and r.split(":", 2)[1] == "23P01"
                    and r.split(":", 2)[2] == "trg_recipient_contract_group_period_overlap"
                ]
                if len(sealed) != 1:
                    fail_marker = fail_label + "_FAIL_SHAPE: " + ",".join(ordered)
                    raise RuntimeError(fail_marker)
            _assert_no_residual_sessions()
            return ordered
        except Exception as exc:
            if fail_marker is None:
                fail_marker = fail_label + "_ORCHESTRATION: " + type(exc).__name__
            raise
        finally:
            stop_monitor.set()
            _release_blocker(commit=False)
            if mon is not None:
                mon.join(timeout=3)
            if t1 is not None:
                t1.join(timeout=5)
            if t2 is not None:
                t2.join(timeout=5)
            with results_lock:
                he = list(harness_errors)
            if he and fail_marker is None:
                fail_marker = fail_label + "_CLEANUP_OR_SETUP: " + he[0][:200]
            try:
                with database_engine.connect() as connection:
                    residual = connection.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM pg_stat_activity
                            WHERE application_name IN (:a, :b, :blocker)
                            """
                        ),
                        {
                            "a": name_a,
                            "b": name_b,
                            "blocker": blocker_name,
                        },
                    ).scalar_one()
                if int(residual) != 0:
                    fail_marker = fail_label + "_SESSION_RESIDUAL_FINALLY"
            except Exception:
                if fail_marker is None:
                    fail_marker = fail_label + "_SESSION_CHECK_FAILED"
            if mon is not None and mon.is_alive():
                fail_marker = fail_label + "_LOCK_MONITOR_JOIN_TIMEOUT"
            elif t1 is not None and t1.is_alive():
                fail_marker = fail_label + "_WORKER_JOIN_TIMEOUT"
            elif t2 is not None and t2.is_alive():
                fail_marker = fail_label + "_WORKER_JOIN_TIMEOUT"
            elif monitor_errors and (fail_marker is None or "_LOCK_MONITOR" not in fail_marker):
                fail_marker = fail_label + "_LOCK_MONITOR_EXCEPTION: " + monitor_errors[0][:200]
            if fail_marker is not None:
                _fail(fail_marker)

    concurrent_raw_inserts(
        recipient_id=case.recipient_id,
        account_id=case.account_id,
        stid_a=home,
        stid_b=temp,
        name_a="w1d-xgroup-a",
        name_b="w1d-xgroup-b",
        start_date=date(2040, 1, 1),
        end_date=date(2040, 6, 30),
        expect_ok=1,
        fail_label="W1D_CON04_RAW_CROSS_GROUP",
        require_exact_cross_group_fail=True,
    )
    with database_engine.connect() as connection:
        n = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.recipient_contract
                WHERE recipient_id = :rid AND start_date = DATE '2040-01-01'
                """
            ),
            {"rid": case.recipient_id},
        ).scalar_one()
        if int(n) != 1:
            _fail("W1D_CON04_RAW_CROSS_GROUP_ROW_COUNT: " + str(n))

    case2 = _seed_case(session_factory)
    results2 = concurrent_raw_inserts(
        recipient_id=case2.recipient_id,
        account_id=case2.account_id,
        stid_a=home,
        stid_b=bath,
        name_a="w1d-sgroup-a",
        name_b="w1d-sgroup-b",
        start_date=date(2041, 1, 1),
        end_date=date(2041, 6, 30),
        expect_ok=2,
        fail_label="W1D_CON04_RAW_SAME_GROUP",
        require_exact_cross_group_fail=False,
    )
    if sum(1 for r in results2 if r == "ok") != 2:
        _fail("W1D_CON04_RAW_SAME_GROUP_OK_COUNT: " + ",".join(results2))
    with database_engine.connect() as connection:
        n2 = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.recipient_contract
                WHERE recipient_id = :rid AND start_date = DATE '2041-01-01'
                """
            ),
            {"rid": case2.recipient_id},
        ).scalar_one()
        if int(n2) != 2:
            _fail("W1D_CON04_RAW_SAME_GROUP_ROW_COUNT: " + str(n2))


_CONTRACT_RESPONSE_FIELDS = (
    "id",
    "recipient_id",
    "service_type_code",
    "service_group_code",
    "start_date",
    "end_date",
    "service_start_date",
    "end_reason_text",
    "invalidated_at_utc",
    "replacement_contract_id",
    "row_version",
)

_CONTRACT_FORBIDDEN_FIELDS = (
    "contract_no",
    "contract_sequence",
    "signer_name",
    "signer_relationship_text",
    "signer_phone",
    "signer_guardian_id",
    "signer_payer_id",
    "signer_birth_date",
    "signer_address",
    "end_reason_code",
    "discharge_date",
)

_API_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _strict_api_date_str(value: object) -> str | None:
    """Exact YYYY-MM-DD string only; no date object or str()/slice coercion."""
    if type(value) is not str:
        return None
    if not _API_DATE_RE.fullmatch(value):
        return None
    return value


def _validate_contract_response_strict(body: object) -> str | None:
    """Pure strict 14-key ContractResponse gate (R24 / Joseph R8 H02).

    None = OK. Never pytest.fail. No int()/date coercion on API values.
    Rejects string IDs, date objects, wrong keyset, forbidden fields, bool ints.
    """
    if type(body) is not dict:
        return "CONTRACT_RESP_NOT_DICT"
    if set(body.keys()) != set(_CONTRACT_RESPONSE_FIELDS):
        return "CONTRACT_RESP_KEYSET"
    for fk in _CONTRACT_FORBIDDEN_FIELDS:
        if fk in body:
            return f"CONTRACT_RESP_FORBIDDEN:{fk}"
    cid = body.get("id")
    if type(cid) is not int or cid <= 0:
        return "CONTRACT_RESP_ID"
    rid = body.get("recipient_id")
    if type(rid) is not int or rid <= 0:
        return "CONTRACT_RESP_RECIPIENT_ID"
    if type(body.get("service_type_code")) is not str:
        return "CONTRACT_RESP_SERVICE_TYPE"
    sgc = body.get("service_group_code")
    if sgc is not None and type(sgc) is not str:
        return "CONTRACT_RESP_SERVICE_GROUP"
    if _strict_api_date_str(body.get("start_date")) is None:
        return "CONTRACT_RESP_START_DATE"
    for dkey in ("end_date", "service_start_date"):
        dv = body.get(dkey)
        if dv is not None and _strict_api_date_str(dv) is None:
            return f"CONTRACT_RESP_{dkey.upper()}"
    for tkey in ("end_reason_text",):
        tv = body.get(tkey)
        if tv is not None and type(tv) is not str:
            return f"CONTRACT_RESP_{tkey.upper()}"
    inv = body.get("invalidated_at_utc")
    if inv is not None and type(inv) is not str:
        return "CONTRACT_RESP_INVALIDATED_TYPE"
    rep = body.get("replacement_contract_id")
    if rep is not None and (type(rep) is not int or rep <= 0):
        return "CONTRACT_RESP_REPLACEMENT_ID"
    rv = body.get("row_version")
    if type(rv) is not int or rv < 1:
        return "CONTRACT_RESP_ROW_VERSION"
    return None


def _assert_contract_response_shape(body: object, *, label: str) -> None:
    err = _validate_contract_response_strict(body)
    if err is not None:
        _fail(f"W1D_API_{label}_{err}")


def _db_normalize_int(value: Any, *, label: str) -> int:
    """DB-side only: accept strict int; reject bool; no API-path use."""
    if type(value) is bool or type(value) is not int:
        _fail(f"{label}_DB_INT_TYPE:{type(value).__name__}")
    return value


def _db_normalize_date_str(value: Any, *, label: str) -> str | None:
    """DB-side only date → YYYY-MM-DD string or None."""
    if value is None:
        return None
    if type(value) is date:  # exact date; datetime is a subclass and excluded
        return value.isoformat()
    if type(value) is str and _API_DATE_RE.fullmatch(value):
        return value
    canon = _canonical_date(value)
    if canon is None or not _API_DATE_RE.fullmatch(canon):
        _fail(f"{label}_DB_DATE_TYPE:{type(value).__name__}")
    return canon


def _db_normalize_ts_str(value: Any, *, label: str) -> str | None:
    """DB-side only timestamp → non-empty string or None (nullability exact)."""
    if value is None:
        return None
    if type(value) is str and value:
        return value
    if type(value) is datetime:
        return value.isoformat()
    _fail(f"{label}_DB_TS_TYPE:{type(value).__name__}")


def _normalize_db_contract_row_for_api(row: Any, *, label: str) -> dict[str, Any]:
    """DB-driver values only → JSON-primitive ContractResponse field set."""
    rep_raw = row["replacement_contract_id"]
    rep = None if rep_raw is None else _db_normalize_int(rep_raw, label=f"{label}_REP")
    sgc_raw = row["service_group_code"]
    if sgc_raw is not None and type(sgc_raw) is not str:
        _fail(f"{label}_DB_SERVICE_GROUP_TYPE")
    stc = row["service_type_code"]
    if type(stc) is not str:
        _fail(f"{label}_DB_SERVICE_TYPE")
    for tkey in ("end_reason_text",):
        tv = row[tkey]
        if tv is not None and type(tv) is not str:
            _fail(f"{label}_DB_TEXT_TYPE:{tkey}")
    return {
        "id": _db_normalize_int(row["id"], label=f"{label}_ID"),
        "recipient_id": _db_normalize_int(row["recipient_id"], label=f"{label}_RID"),
        "service_type_code": stc,
        "service_group_code": sgc_raw,
        "start_date": _db_normalize_date_str(row["start_date"], label=f"{label}_START"),
        "end_date": _db_normalize_date_str(row["end_date"], label=f"{label}_END"),
        "service_start_date": _db_normalize_date_str(
            row["service_start_date"], label=f"{label}_SSD"
        ),
        "end_reason_text": row["end_reason_text"],
        "invalidated_at_utc": _db_normalize_ts_str(row["invalidated_at_utc"], label=f"{label}_INV"),
        "replacement_contract_id": rep,
        "row_version": _db_normalize_int(row["row_version"], label=f"{label}_RV"),
    }


def _assert_contract_response_matches_row(
    body: object,
    row: Any,
    *,
    label: str,
) -> None:
    """Strict API gate first; DB-side normalizer only for row; exact equality."""
    _assert_contract_response_shape(body, label=label)
    assert type(body) is dict
    expected = _normalize_db_contract_row_for_api(row, label=label)
    # No int()/date coercion on API body — exact JSON primitive equality.
    for key in _CONTRACT_RESPONSE_FIELDS:
        if body[key] != expected[key]:
            _fail(f"W1D_API_{label}_ROW_MISMATCH:{key}:{body[key]!r}!={expected[key]!r}")


def test_w1d_pg_12_list_get_end_contract_api(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """J-W1D-R3-M02 / R8-07: list/GET/end field-exact + 404 envelopes + write-zero."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING")
    collection = f"/api/v1/recipients/{case.recipient_id}/contracts"
    missing_item = f"/api/v1/recipients/{case.recipient_id}/contracts/999999991"
    missing_recipient = "/api/v1/recipients/999999992/contracts"
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": case.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_FAILED")
        csrf = client.cookies.get("sswcenter_csrf")
        headers = {"X-CSRF-Token": csrf or ""}
        listed = client.get(collection)
        if listed.status_code != 200:
            _fail("W1D_API_LIST_NOT_200: " + str(listed.status_code))
        body = listed.json()
        if "items" not in body or not isinstance(body["items"], list):
            _fail("W1D_API_LIST_SHAPE")
        created = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_CARE,
                "start_date": "2050-01-01",
                "end_date": "2050-12-31",
                "service_start_date": None,
                "end_reason_text": None,
            },
            headers=headers,
        )
        if created.status_code != 201:
            _fail("W1D_API_CREATE_NOT_201: " + str(created.status_code))
        created_body = created.json()
        _assert_contract_response_shape(created_body, label="CREATE")
        # After strict gate, IDs are exact ints — no int() coercion.
        cid = created_body["id"]
        if created_body.get("end_reason_text") is not None:
            _fail("W1D_API_CREATE_END_REASON_NOT_NULL")
        if created_body.get("end_date") != "2050-12-31":
            _fail("W1D_API_CREATE_END_DATE")
        if created_body["recipient_id"] != case.recipient_id:
            _fail("W1D_API_CREATE_RECIPIENT_ID")
        if created_body.get("service_type_code") != SERVICE_HOME_CARE:
            _fail("W1D_API_CREATE_SERVICE_TYPE")

        got = client.get(f"{collection}/{cid}")
        if got.status_code != 200:
            _fail("W1D_API_GET_NOT_200: " + str(got.status_code))
        got_body = got.json()
        _assert_contract_response_shape(got_body, label="GET")
        if got_body != created_body:
            _fail("W1D_API_GET_NE_CREATE_BODY")

        listed2 = client.get(collection)
        if listed2.status_code != 200:
            _fail("W1D_API_LIST2_NOT_200: " + str(listed2.status_code))
        items = listed2.json().get("items") or []
        match = []
        for it in items:
            _assert_contract_response_shape(it, label="LIST_SCAN")
            if it["id"] == cid:
                match.append(it)
        if len(match) != 1:
            _fail("W1D_API_LIST_ITEM_MISSING")
        list_item = match[0]
        _assert_contract_response_shape(list_item, label="LIST_ITEM")
        if list_item != got_body:
            _fail("W1D_API_LIST_ITEM_NE_GET")
        with database_engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT c.id, c.recipient_id, st.code AS service_type_code,
                           sg.code AS service_group_code,
                           c.start_date, c.end_date, c.service_start_date,
                           c.end_reason_text, c.invalidated_at_utc,
                           c.replacement_contract_id, c.row_version,
                           c.updated_by_account_id, c.updated_at_utc
                    FROM erp.recipient_contract c
                    JOIN erp.service_type st ON st.id = c.service_type_id
                    LEFT JOIN erp.service_group sg ON sg.id = st.service_group_id
                    WHERE c.id = :id
                    """
                    ),
                    {"id": cid},
                )
                .mappings()
                .one()
            )
        _assert_contract_response_matches_row(got_body, row, label="GET")

        # Create a separate open-ended HOME_CARE contract as the /end target.
        end_target = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_CARE,
                "start_date": "2051-01-01",
                "service_start_date": None,
                "end_reason_text": None,
            },
            headers=headers,
        )
        if end_target.status_code != 201:
            _fail("W1D_API_END_TARGET_CREATE_NOT_201: " + str(end_target.status_code))
        end_target_body = end_target.json()
        _assert_contract_response_shape(end_target_body, label="END_TARGET")
        cid_end = end_target_body["id"]
        rv_end = end_target_body["row_version"]
        if end_target_body.get("end_date") is not None:
            _fail("W1D_API_END_TARGET_NOT_OPEN_ENDED")
        if end_target_body.get("end_reason_text") is not None:
            _fail("W1D_API_END_TARGET_END_REASON_NOT_NULL")

        end_reason = "종료-TEST_END-😀"
        ended = client.post(
            f"{collection}/{cid_end}/end",
            json={
                "end_date": "2051-06-30",
                "expected_row_version": rv_end,
                "end_reason_text": end_reason,
            },
            headers=headers,
        )
        if ended.status_code != 200:
            _fail("W1D_API_END_NOT_200: " + str(ended.status_code))
        ended_body = ended.json()
        _assert_contract_response_shape(ended_body, label="END")
        if ended_body.get("end_date") != "2051-06-30":
            _fail("W1D_API_END_DATE_MISMATCH: " + str(ended_body.get("end_date")))
        if ended_body.get("end_reason_text") != end_reason:
            _fail("W1D_API_END_REASON_MISMATCH")
        if ended_body["row_version"] != rv_end + 1:
            _fail("W1D_API_END_ROW_VERSION_NOT_INCREMENTED")
        with database_engine.connect() as connection:
            erow = (
                connection.execute(
                    text(
                        """
                    SELECT c.id, c.recipient_id, st.code AS service_type_code,
                           sg.code AS service_group_code,
                           c.start_date, c.end_date, c.service_start_date,
                           c.end_reason_text, c.invalidated_at_utc,
                           c.replacement_contract_id, c.row_version,
                           c.updated_by_account_id, c.updated_at_utc
                    FROM erp.recipient_contract c
                    JOIN erp.service_type st ON st.id = c.service_type_id
                    LEFT JOIN erp.service_group sg ON sg.id = st.service_group_id
                    WHERE c.id = :id
                    """
                    ),
                    {"id": cid_end},
                )
                .mappings()
                .one()
            )
            if _canonical_date(erow["end_date"]) != "2051-06-30":
                _fail("W1D_API_END_PERSISTED_DATE")
            if erow["end_reason_text"] != end_reason:
                _fail("W1D_API_END_PERSISTED_REASON")
            if int(erow["row_version"]) != rv_end + 1:
                _fail("W1D_API_END_PERSISTED_ROW_VERSION")
            if int(erow["updated_by_account_id"]) != case.account_id:
                _fail("W1D_API_END_ACTOR_MISMATCH")
            if erow["updated_at_utc"] is None:
                _fail("W1D_API_END_UPDATED_AT_MISSING")
        _assert_contract_response_matches_row(ended_body, erow, label="END")

        with database_engine.connect() as connection:
            snap_stale = _full_ledger_fingerprint(connection, case.recipient_id)
        stale = client.post(
            f"{collection}/{cid_end}/end",
            json={"end_date": "2051-07-31", "expected_row_version": rv_end},
            headers=headers,
        )
        if stale.status_code != 409:
            _fail("W1D_API_END_STALE_NOT_409: " + str(stale.status_code))
        _assert_standard_error_envelope(stale.json(), expect_code="ROW_VERSION_CONFLICT")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_stale:
                _fail("W1D_API_END_STALE_WROTE_ROWS")

        with database_engine.connect() as connection:
            snap_nf = _full_ledger_fingerprint(connection, case.recipient_id)
        nf = client.get(missing_item)
        if nf.status_code != 404:
            _fail("W1D_API_GET_MISSING_NOT_404: " + str(nf.status_code))
        _assert_standard_error_envelope(nf.json(), expect_code="CONTRACT_NOT_FOUND")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_nf:
                _fail("W1D_API_GET_MISSING_WROTE_ROWS")

        with database_engine.connect() as connection:
            snap_end_nf = _full_ledger_fingerprint(connection, case.recipient_id)
        end_nf = client.post(
            f"{missing_item}/end",
            json={"end_date": "2050-08-31", "expected_row_version": 1},
            headers=headers,
        )
        if end_nf.status_code != 404:
            _fail("W1D_API_END_MISSING_NOT_404: " + str(end_nf.status_code))
        _assert_standard_error_envelope(end_nf.json(), expect_code="CONTRACT_NOT_FOUND")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_end_nf:
                _fail("W1D_API_END_MISSING_WROTE_ROWS")

        with database_engine.connect() as connection:
            snap_nr = _full_ledger_fingerprint(connection, case.recipient_id)
        nr = client.get(missing_recipient)
        if nr.status_code != 404:
            _fail("W1D_API_LIST_MISSING_RECIPIENT_NOT_404: " + str(nr.status_code))
        _assert_standard_error_envelope(nr.json(), expect_code="RECIPIENT_NOT_FOUND")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_nr:
                _fail("W1D_API_LIST_MISSING_RECIPIENT_WROTE_ROWS")


def test_w1d_pg_13_null_identity_and_free_text_validation(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """R8-10: null/empty end reason, Unicode preservation, and reverse-date 422."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING")
    collection = f"/api/v1/recipients/{case.recipient_id}/contracts"
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": case.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_FAILED")
        csrf = client.cookies.get("sswcenter_csrf")
        if not csrf:
            _fail("W1D_HARNESS_CSRF_COOKIE_MISSING")
        headers = {"X-CSRF-Token": csrf}

        # Omitted -> NULL, explicit null -> NULL, explicit empty string preserved.
        omit = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_CARE,
                "start_date": "2062-01-01",
                "end_date": "2062-03-31",
            },
            headers=headers,
        )
        if omit.status_code != 201:
            _fail("W1D_API_OMIT_CREATE_NOT_201: " + str(omit.status_code))
        omit_id = int(omit.json()["id"])
        if omit.json().get("end_reason_text") is not None:
            _fail("W1D_API_OMIT_END_REASON_NOT_NULL")
        with database_engine.connect() as connection:
            end_reason = connection.execute(
                text("SELECT end_reason_text FROM erp.recipient_contract WHERE id = :id"),
                {"id": omit_id},
            ).scalar_one()
            if end_reason is not None:
                _fail("W1D_API_OMIT_PERSISTED_END_REASON")

        null_body = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_BATH,
                "start_date": "2062-04-01",
                "end_date": "2062-06-30",
                "end_reason_text": None,
            },
            headers=headers,
        )
        if null_body.status_code != 201:
            _fail("W1D_API_NULL_CREATE_NOT_201: " + str(null_body.status_code))
        null_id = int(null_body.json()["id"])
        with database_engine.connect() as connection:
            end_reason = connection.execute(
                text("SELECT end_reason_text FROM erp.recipient_contract WHERE id = :id"),
                {"id": null_id},
            ).scalar_one()
            if end_reason is not None:
                _fail("W1D_API_NULL_PERSISTED_END_REASON_TEXT")

        empty_body = client.post(
            collection,
            json={
                "service_type_code": SERVICE_TEMP,
                "start_date": "2062-07-01",
                "end_date": "2062-09-30",
                "end_reason_text": "",
            },
            headers=headers,
        )
        if empty_body.status_code != 201:
            _fail("W1D_API_EMPTY_CREATE_NOT_201: " + str(empty_body.status_code))
        empty_id = int(empty_body.json()["id"])
        if empty_body.json().get("end_reason_text") != "":
            _fail("W1D_API_EMPTY_END_REASON_RESPONSE")
        with database_engine.connect() as connection:
            end_reason = connection.execute(
                text("SELECT end_reason_text FROM erp.recipient_contract WHERE id = :id"),
                {"id": empty_id},
            ).scalar_one()
            if end_reason != "":
                _fail("W1D_API_EMPTY_PERSISTED_END_REASON_TEXT: " + repr(end_reason))
            # No automatic "사망" substitution.
            death = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM erp.recipient_contract
                    WHERE id = :id AND end_reason_text = '사망'
                    """
                ),
                {"id": empty_id},
            ).scalar_one()
            if int(death) != 0:
                _fail("W1D_API_EMPTY_DEATH_DEFAULT_APPLIED")

        # Create a separate open-ended HOME_CARE end target for empty-reason /end.
        end_target_empty = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_CARE,
                "start_date": "2062-10-01",
                "service_start_date": None,
                "end_reason_text": None,
            },
            headers=headers,
        )
        if end_target_empty.status_code != 201:
            _fail("W1D_API_END_EMPTY_TARGET_CREATE_NOT_201: " + str(end_target_empty.status_code))
        _assert_contract_response_shape(end_target_empty.json(), label="END_EMPTY_TARGET")
        end_empty_id = end_target_empty.json()["id"]
        end_empty_rv = end_target_empty.json()["row_version"]

        # Initial empty end-reason behavior on end: explicit "" stays "".
        end_empty = client.post(
            f"{collection}/{end_empty_id}/end",
            json={
                "end_date": "2062-12-31",
                "expected_row_version": end_empty_rv,
                "end_reason_text": "",
            },
            headers=headers,
        )
        if end_empty.status_code != 200:
            _fail("W1D_API_END_EMPTY_REASON_NOT_200: " + str(end_empty.status_code))
        if end_empty.json().get("end_reason_text") != "":
            _fail("W1D_API_END_EMPTY_REASON_RESPONSE")
        with database_engine.connect() as connection:
            er = connection.execute(
                text("SELECT end_reason_text FROM erp.recipient_contract WHERE id = :id"),
                {"id": end_empty_id},
            ).scalar_one()
            if er != "":
                _fail("W1D_API_END_EMPTY_REASON_PERSISTED: " + repr(er))

        # Unicode free-text preserve.
        created = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_CARE,
                "start_date": "2063-01-01",
            },
            headers=headers,
        )
        if created.status_code != 201:
            _fail("W1D_API_UNICODE_CREATE_NOT_201: " + str(created.status_code))
        cid = int(created.json()["id"])
        rv = int(created.json().get("row_version", 1))
        ended = client.post(
            f"{collection}/{cid}/end",
            json={
                "end_date": "2063-06-30",
                "expected_row_version": rv,
                "end_reason_text": "종료사유-自由文本-😀",
            },
            headers=headers,
        )
        if ended.status_code != 200:
            _fail("W1D_API_UNICODE_END_NOT_200: " + str(ended.status_code))
        with database_engine.connect() as connection:
            reason = connection.execute(
                text("SELECT end_reason_text FROM erp.recipient_contract WHERE id = :id"),
                {"id": cid},
            ).scalar_one()
            if reason != "종료사유-自由文本-😀":
                _fail("W1D_CON02_UNICODE_END_REASON_NOT_PRESERVED")

        with database_engine.connect() as connection:
            snap_rev = _full_ledger_fingerprint(connection, case.recipient_id)
        rev = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_BATH,
                "start_date": "2064-12-31",
                "end_date": "2064-01-01",
            },
            headers=headers,
        )
        if rev.status_code != 422:
            _fail("W1D_API_REVERSE_PERIOD_NOT_422: " + str(rev.status_code))
        rev_env = _assert_standard_error_envelope(rev.json(), expect_code="VALIDATION_ERROR")
        # R10-04: exact one-item JSON equality with W1C _domain_error message.
        field_errors = rev_env["field_errors"]
        if field_errors != W1D_REVERSE_PERIOD_FIELD_ERRORS:
            _fail(
                "W1D_API_REVERSE_PERIOD_FIELD_ERRORS_NOT_EXACT: "
                + json.dumps(field_errors, ensure_ascii=False)
            )
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_rev:
                _fail("W1D_API_REVERSE_PERIOD_WROTE_ROWS")


def test_w1d_pg_15_list_get_read_acl_and_purity(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """J-W1D-R4-H02: GET list/item unauth 401, no-perm 403, VIEW 200 no CSRF, 404s."""
    _require_w1d_catalog(database_engine)
    admin = _seed_case(session_factory)
    from app.core.security import PinProtector
    from app.db.models import AccountPermission, Staff, UserAccount

    label = uuid4().hex
    protector = PinProtector(
        os.environ["SSWCENTER_PIN_PEPPER"],
        os.environ["SSWCENTER_PIN_LOOKUP_KEY"],
    )
    with session_factory() as database_session:
        staff_v = Staff(
            name=f"W1D VIEW_R {label}",
            birth_date=date(1991, 1, 1),
            sex_code="TEST",
            display_name=f"VIEW_R {label}",
            row_version=1,
        )
        staff_n = Staff(
            name=f"W1D NONE_R {label}",
            birth_date=date(1992, 1, 1),
            sex_code="TEST",
            display_name=f"NONE_R {label}",
            row_version=1,
        )
        database_session.add_all([staff_v, staff_n])
        database_session.flush()
        pin_view = _synthetic_pin_for_staff_id(staff_v.id)
        pin_none = _synthetic_pin_for_staff_id(staff_n.id)
        acc_v = UserAccount(
            staff_id=staff_v.id,
            account_code=f"W1D_VIEW_R_{label}",
            display_name=f"VIEW_R {label}",
            role_code="USER",
            pin_hash=protector.hash_pin(pin_view),
            pin_lookup_hmac=protector.lookup_hmac(pin_view),
            pin_key_version=1,
            row_version=1,
        )
        acc_n = UserAccount(
            staff_id=staff_n.id,
            account_code=f"W1D_NONE_R_{label}",
            display_name=f"NONE_R {label}",
            role_code="USER",
            pin_hash=protector.hash_pin(pin_none),
            pin_lookup_hmac=protector.lookup_hmac(pin_none),
            pin_key_version=1,
            row_version=1,
        )
        database_session.add_all([acc_v, acc_n])
        database_session.flush()
        database_session.add(
            AccountPermission(
                account_id=acc_v.id,
                permission_code="RECIPIENT_VIEW",
                granted_by_account_id=admin.account_id,
            )
        )
        database_session.commit()

    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING")

    collection = f"/api/v1/recipients/{admin.recipient_id}/contracts"
    missing_recipient_list = "/api/v1/recipients/999999981/contracts"
    missing_item = f"/api/v1/recipients/{admin.recipient_id}/contracts/999999982"
    missing_recipient_item = "/api/v1/recipients/999999983/contracts/1"

    with TestClient(app) as client:
        # Seed one contract as ADMIN for VIEW success/readback.
        login_a = client.post("/api/auth/login", json={"pin": admin.pin})
        if login_a.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_ADMIN_FAILED")
        csrf = client.cookies.get("sswcenter_csrf")
        created = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_CARE,
                "start_date": "2080-01-01",
                "end_date": "2080-12-31",
            },
            headers={"X-CSRF-Token": csrf or ""},
        )
        if created.status_code != 201:
            _fail("W1D_API_READ_ACL_SEED_CREATE_NOT_201: " + str(created.status_code))
        cid = int(created.json()["id"])
        client.cookies.clear()

        def _gate(
            method_label: str,
            response: Response,
            *,
            expect_status: int,
            expect_code: str | None,
            rid: int,
            before_fp: str,
            before_audit: str,
        ) -> dict[str, Any]:
            if response.status_code != expect_status:
                _fail(f"W1D_API_READ_{method_label}_STATUS: " + str(response.status_code))
            body = cast(dict[str, Any], response.json())
            if expect_code is not None:
                _assert_standard_error_envelope(body, expect_code=expect_code)
            with database_engine.connect() as connection:
                _assert_write_zero_pair(
                    connection,
                    rid,
                    before_fp,
                    before_audit,
                    label=f"W1D_API_READ_{method_label}",
                )
            return body

        # 1) Unauthenticated list + item -> 401 AUTHENTICATION_REQUIRED
        with database_engine.connect() as connection:
            u_fp, u_audit = _write_zero_pair(connection, admin.recipient_id)
        r = client.get(collection)
        _gate(
            "LIST_UNAUTH",
            r,
            expect_status=401,
            expect_code="AUTHENTICATION_REQUIRED",
            rid=admin.recipient_id,
            before_fp=u_fp,
            before_audit=u_audit,
        )
        with database_engine.connect() as connection:
            u2_fp, u2_audit = _write_zero_pair(connection, admin.recipient_id)
        r = client.get(f"{collection}/{cid}")
        _gate(
            "ITEM_UNAUTH",
            r,
            expect_status=401,
            expect_code="AUTHENTICATION_REQUIRED",
            rid=admin.recipient_id,
            before_fp=u2_fp,
            before_audit=u2_audit,
        )

        # 2) No-permission USER -> 403 PERMISSION_REQUIRED
        login_n = client.post("/api/auth/login", json={"pin": pin_none})
        if login_n.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_NONE_FAILED")
        with database_engine.connect() as connection:
            n_fp, n_audit = _write_zero_pair(connection, admin.recipient_id)
        r = client.get(collection)
        _gate(
            "LIST_NOPERM",
            r,
            expect_status=403,
            expect_code="PERMISSION_REQUIRED",
            rid=admin.recipient_id,
            before_fp=n_fp,
            before_audit=n_audit,
        )
        with database_engine.connect() as connection:
            n2_fp, n2_audit = _write_zero_pair(connection, admin.recipient_id)
        r = client.get(f"{collection}/{cid}")
        _gate(
            "ITEM_NOPERM",
            r,
            expect_status=403,
            expect_code="PERMISSION_REQUIRED",
            rid=admin.recipient_id,
            before_fp=n2_fp,
            before_audit=n2_audit,
        )

        # 3) VIEW success without CSRF (GET purity) — exact full collection.
        client.cookies.clear()
        login_v = client.post("/api/auth/login", json={"pin": pin_view})
        if login_v.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_VIEW_FAILED")
        # Explicitly no X-CSRF-Token header.
        with database_engine.connect() as connection:
            v_fp, v_audit = _write_zero_pair(connection, admin.recipient_id)
            # Sealed list order: contract id ASC for this recipient.
            db_rows = (
                connection.execute(
                    text(
                        """
                    SELECT c.id, c.recipient_id, st.code AS service_type_code,
                           sg.code AS service_group_code,
                           c.start_date, c.end_date, c.service_start_date,
                           c.end_reason_text, c.invalidated_at_utc,
                           c.replacement_contract_id, c.row_version
                    FROM erp.recipient_contract c
                    JOIN erp.service_type st ON st.id = c.service_type_id
                    LEFT JOIN erp.service_group sg ON sg.id = st.service_group_id
                    WHERE c.recipient_id = :rid
                    ORDER BY c.id ASC
                    """
                    ),
                    {"rid": admin.recipient_id},
                )
                .mappings()
                .all()
            )
        listed = client.get(collection)
        if listed.status_code != 200:
            _fail("W1D_API_READ_LIST_VIEW_NOT_200: " + str(listed.status_code))
        list_body = listed.json()
        # R13-03: exact top-level key set {items} only — no silent discard of extras.
        if not isinstance(list_body, dict) or set(list_body) != {"items"}:
            keys_repr = (
                sorted(list_body.keys())
                if isinstance(list_body, dict)
                else type(list_body).__name__
            )
            _fail("W1D_API_READ_LIST_VIEW_TOP_LEVEL: " + repr(keys_repr))
        if not isinstance(list_body["items"], list):
            _fail("W1D_API_READ_LIST_VIEW_SHAPE")
        items = list_body["items"]
        if len(items) != len(db_rows):
            _fail("W1D_API_READ_LIST_VIEW_COUNT: " + f"api={len(items)} db={len(db_rows)}")
        for item in items:
            _assert_contract_response_shape(item, label="READ_LIST_VIEW_ITEM")
        # R24: DB-side normalizer only; no API int/date/default=str coercion.
        expected_items = [
            _normalize_db_contract_row_for_api(row, label="READ_LIST_DB") for row in db_rows
        ]
        expected_response = {"items": expected_items}
        if list_body != expected_response:
            _fail("W1D_API_READ_LIST_VIEW_COLLECTION_NOT_EXACT")
        list_item = next(it for it in items if it["id"] == cid)
        with database_engine.connect() as connection:
            _assert_write_zero_pair(
                connection,
                admin.recipient_id,
                v_fp,
                v_audit,
                label="W1D_API_READ_LIST_VIEW",
            )
            row = (
                connection.execute(
                    text(
                        """
                    SELECT c.id, c.recipient_id, st.code AS service_type_code,
                           sg.code AS service_group_code,
                           c.start_date, c.end_date, c.service_start_date,
                           c.end_reason_text, c.invalidated_at_utc,
                           c.replacement_contract_id, c.row_version
                    FROM erp.recipient_contract c
                    JOIN erp.service_type st ON st.id = c.service_type_id
                    LEFT JOIN erp.service_group sg ON sg.id = st.service_group_id
                    WHERE c.recipient_id = :rid AND c.id = :id
                    """
                    ),
                    {"rid": admin.recipient_id, "id": cid},
                )
                .mappings()
                .one()
            )
        _assert_contract_response_matches_row(list_item, row, label="READ_LIST_VIEW")

        with database_engine.connect() as connection:
            vi_fp, vi_audit = _write_zero_pair(connection, admin.recipient_id)
        got = client.get(f"{collection}/{cid}")
        if got.status_code != 200:
            _fail("W1D_API_READ_ITEM_VIEW_NOT_200: " + str(got.status_code))
        got_body = got.json()
        _assert_contract_response_shape(got_body, label="READ_ITEM_VIEW")
        if got_body != list_item:
            _fail("W1D_API_READ_ITEM_VIEW_NE_LIST")
        with database_engine.connect() as connection:
            _assert_write_zero_pair(
                connection,
                admin.recipient_id,
                vi_fp,
                vi_audit,
                label="W1D_API_READ_ITEM_VIEW",
            )
            row2 = (
                connection.execute(
                    text(
                        """
                    SELECT c.id, c.recipient_id, st.code AS service_type_code,
                           sg.code AS service_group_code,
                           c.start_date, c.end_date, c.service_start_date,
                           c.end_reason_text, c.invalidated_at_utc,
                           c.replacement_contract_id, c.row_version
                    FROM erp.recipient_contract c
                    JOIN erp.service_type st ON st.id = c.service_type_id
                    LEFT JOIN erp.service_group sg ON sg.id = st.service_group_id
                    WHERE c.recipient_id = :rid AND c.id = :id
                    """
                    ),
                    {"rid": admin.recipient_id, "id": cid},
                )
                .mappings()
                .one()
            )
        _assert_contract_response_matches_row(got_body, row2, label="READ_ITEM_VIEW")

        # 4) VIEW missing recipient: write-zero scoped to the missing recipient id.
        missing_rid_list = 999999981
        missing_rid_item = 999999983
        with database_engine.connect() as connection:
            mr_fp, mr_audit = _write_zero_pair(connection, missing_rid_list)
        r = client.get(missing_recipient_list)
        _gate(
            "LIST_MISSING_RECIPIENT",
            r,
            expect_status=404,
            expect_code="RECIPIENT_NOT_FOUND",
            rid=missing_rid_list,
            before_fp=mr_fp,
            before_audit=mr_audit,
        )
        with database_engine.connect() as connection:
            mri_fp, mri_audit = _write_zero_pair(connection, missing_rid_item)
        r = client.get(missing_recipient_item)
        _gate(
            "ITEM_MISSING_RECIPIENT",
            r,
            expect_status=404,
            expect_code="RECIPIENT_NOT_FOUND",
            rid=missing_rid_item,
            before_fp=mri_fp,
            before_audit=mri_audit,
        )

        # 5) VIEW missing contract item -> CONTRACT_NOT_FOUND
        with database_engine.connect() as connection:
            mc_fp, mc_audit = _write_zero_pair(connection, admin.recipient_id)
        r = client.get(missing_item)
        _gate(
            "ITEM_MISSING_CONTRACT",
            r,
            expect_status=404,
            expect_code="CONTRACT_NOT_FOUND",
            rid=admin.recipient_id,
            before_fp=mc_fp,
            before_audit=mc_audit,
        )
