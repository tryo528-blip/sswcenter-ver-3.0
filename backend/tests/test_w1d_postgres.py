"""W1D Phase 1 RED: real PostgreSQL / API / concurrency / transition contracts.

Requires SSWCENTER_W1D_REAL_PG=1 from scripts/test-w1d-postgres.ps1.

- Harness self-check (W1C head) must execute and PASS without W1D product.
- Product tests fail with stable W1D_* markers until migration/domain exist.
- Product vs harness markers remain distinct.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.skipif(
    os.environ.get("SSWCENTER_W1D_REAL_PG") != "1",
    reason="requires the isolated W1D PostgreSQL harness",
)

# W1D-REC-03 / plan §: first-contract recipient_no is zero-padded 6+ decimal digits.
RECIPIENT_NO_EXACT_RE = re.compile(r"^[0-9]{6,}$")

W1C_HEAD = "20260730_0010_w1c_certification_ledgers"
W1D_REVISION = "20260730_0011_w1d_recipient_contract"
# Wrapper (scripts/test-w1d-postgres.ps1) seals the historical 0011 lifecycle,
# then upgrades the runtime DB to current head and exports this exact expected
# runtime revision for ORM/product assertions. Unset falls back to W1D_REVISION.
_RUNTIME_REVISION_ENV = "SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION"
SERVICE_HOME_CARE = "HOME_CARE"
SERVICE_HOME_BATH = "HOME_BATH"
SERVICE_TEMP = "TEMP_HOME_CARE"
SERVICE_BARO = "BARO_CARE"
PII_CANARIES = (
    "TEST_W1D_SIGNER_CANARY",
    "TEST_W1D_SIGNER_PHONE",
    "TEST_W1D_GUARDIAN_NAME",
    "TEST_W1D_PAYER_NAME",
    "TEST_W1D_END_REASON_PII",
)
# R10-04: exact W1B/W1C reverse-period field_errors payload.
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
def database_engine() -> Engine:
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


def _load_service():
    try:
        from app.domains.w1d.service import W1DService  # type: ignore

        return W1DService
    except Exception:
        _fail("W1D_SERVICE_MODULE_MISSING: W1DService")


def _load_schemas():
    try:
        from app.domains.w1d import schemas as w1d_schemas  # type: ignore

        return w1d_schemas
    except Exception:
        _fail("W1D_DOMAIN_MODULE_MISSING: schemas")


def _current_account(case: W1DCase):
    from app.core.auth import CurrentAccount

    return CurrentAccount(case.account_id, f"W1D {case.account_id}", case.role_code)


def _error_code(exc: BaseException) -> str:
    return str(getattr(exc, "code", type(exc).__name__))


def _replacement_items(
    schemas: Any,
    contract_id: int,
    start: date,
    *,
    service_type_code: str = SERVICE_HOME_CARE,
    **extra: Any,
) -> list[Any]:
    # R4-03: extra may override start_date (and any sealed field) without shadowing.
    payload = {
        "ended_contract_id": contract_id,
        "service_type_code": service_type_code,
        "start_date": start,
        "end_date": None,
        "service_start_date": None,
        "signer_name": None,
        "signer_relationship_text": None,
        "signer_phone": None,
        "end_reason_text": None,
    }
    payload.update(extra)
    if hasattr(schemas, "TransitionReplacementItem"):
        return [schemas.TransitionReplacementItem(**payload)]
    return [payload]


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


def _row_count(connection, table: str) -> int:
    return int(connection.execute(text(f"SELECT COUNT(*) FROM erp.{table}")).scalar_one())


# ---------------------------------------------------------------------------
# H3 ??W1C-head harness self-check (must PASS without W1D product)
# ---------------------------------------------------------------------------


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
        for required in (
            SERVICE_HOME_CARE,
            SERVICE_HOME_BATH,
            SERVICE_TEMP,
            SERVICE_BARO,
        ):
            if required not in codes:
                _fail("W1D_HARNESS_SERVICE_SEED_MISSING: " + required)

        groups = {
            str(row[0])
            for row in connection.execute(
                text("SELECT code FROM erp.service_group WHERE active IS TRUE")
            ).all()
        }
        for required in ("LONG_TERM_CARE", "LOCAL_CARE", "BARO_CARE"):
            if required not in groups:
                _fail("W1D_HARNESS_SERVICE_GROUP_SEED_MISSING: " + required)

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

        # W1C containment triggers present (B1 dependency).
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
            if name not in trigger_names:
                _fail("W1D_HARNESS_W1C_CONTAINMENT_TRIGGER_MISSING: " + name)

    # W1C service signature still works (dependency of transition RED).
    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
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
            ),
            account,
        )
        grade = w1c.create_grade_period(
            case.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=cert.id,
                grade_code="3",
                start_date=date(2030, 1, 1),
                end_date=date(2030, 12, 31),
            ),
            account,
        )
        database_session.commit()
        if grade.grade_code.value != "3":
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


# ---------------------------------------------------------------------------
# Product RED (require W1D catalog)
# Definition order is intentional: first-contract race is the first product
# issuance on a fresh isolated cluster (N1 absent-row path).
# ---------------------------------------------------------------------------


def _counter_sequence(connection) -> int | None:
    return connection.execute(
        text(
            """
            SELECT last_sequence FROM erp.business_number_counter
            WHERE number_type = 'RECIPIENT_NO' AND number_year = 0
            """
        )
    ).scalar_one_or_none()


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
    connection,
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
            "grade",
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient_grade_period t WHERE t.recipient_id = :rid),
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


def _all_audit_rows(connection) -> list[dict[str, Any]]:
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


def _write_zero_pair(connection, recipient_id: int) -> tuple[str, str]:
    """Full ledger fingerprint + complete audit row-set (R11 / J-W1D-R4-H01)."""
    fingerprint = _full_ledger_fingerprint(connection, recipient_id)
    audit_canon = _canonical_audit_rows_json(_all_audit_rows(connection))
    return fingerprint, audit_canon


def _assert_write_zero_pair(
    connection,
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


def _jsonb_table_rows(
    connection,
    sql: str,
    params: dict[str, Any] | None,
    *,
    label: str,
) -> list[dict[str, Any]]:
    """Fail-closed decoded to_jsonb array → list[dict] (R16 single-winner)."""
    try:
        if params is None:
            raw = connection.execute(text(sql)).scalar()
        else:
            raw = connection.execute(text(sql), params).scalar()
    except Exception as exc:
        _fail(f"W1D_HARNESS_LEDGER_SNAPSHOT_QUERY_{label}: {type(exc).__name__}")
    encoded = _jsonb_encode(raw, label=label)
    try:
        data = json.loads(encoded)
    except Exception as exc:
        _fail(f"W1D_HARNESS_LEDGER_SNAPSHOT_DECODE_{label}: {type(exc).__name__}")
    if not isinstance(data, list):
        _fail(f"W1D_HARNESS_LEDGER_SNAPSHOT_TYPE_{label}")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            _fail(f"W1D_HARNESS_LEDGER_SNAPSHOT_NON_DICT_{label}: index={idx}")
        out.append(dict(item))
    return out


def _full_ledger_state(connection, recipient_id: int) -> dict[str, list[dict[str, Any]]]:
    """Complete target ledger + global counter + full cluster audit rowset.

    Used by pg_08 concurrent single-winner projection (J-W1D-R5-H04). Each
    component is the full ordered to_jsonb row list — not a hash, not counts.
    """
    rid = {"rid": recipient_id}
    return {
        "recipient": _jsonb_table_rows(
            connection,
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient t WHERE t.id = :rid),
                '[]'::jsonb
            )
            """,
            rid,
            label="recipient",
        ),
        "identity": _jsonb_table_rows(
            connection,
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.recipient_id)
                 FROM erp.recipient_certification_identity t
                 WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            rid,
            label="identity",
        ),
        "cert": _jsonb_table_rows(
            connection,
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient_certification_period t
                 WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            rid,
            label="cert",
        ),
        "grade": _jsonb_table_rows(
            connection,
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient_grade_period t WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            rid,
            label="grade",
        ),
        "contract": _jsonb_table_rows(
            connection,
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.id)
                 FROM erp.recipient_contract t WHERE t.recipient_id = :rid),
                '[]'::jsonb
            )
            """,
            rid,
            label="contract",
        ),
        "counter": _jsonb_table_rows(
            connection,
            """
            SELECT COALESCE(
                (SELECT jsonb_agg(to_jsonb(t) ORDER BY t.number_type, t.number_year)
                 FROM erp.business_number_counter t),
                '[]'::jsonb
            )
            """,
            None,
            label="counter",
        ),
        "audit": _all_audit_rows(connection),
    }


def _canon_row(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _index_rows_by_id(
    rows: list[dict[str, Any]], *, key: str = "id", label: str
) -> dict[Any, dict[str, Any]]:
    out: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if key not in row:
            _fail(f"W1D_TRN03_LEDGER_ROW_KEY_MISSING_{label}")
        kid = row[key]
        if kid in out:
            _fail(f"W1D_TRN03_LEDGER_DUP_ID_{label}")
        out[kid] = row
    return out


def _assert_rows_exact_equal(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    *,
    label: str,
) -> None:
    if _canonical_audit_rows_json(before_rows) != _canonical_audit_rows_json(after_rows):
        _fail(f"W1D_TRN03_SINGLE_WINNER_{label}_MUTATED")


def _date_field_equals(value: Any, expected: date) -> bool:
    return _canonical_date(value) == expected.isoformat()


# Sealed persisted to_jsonb key sets (W1C 0010 + planned W1D 0011 contract).
_W1C_CERT_ROW_KEYS = frozenset(
    {
        "id",
        "recipient_id",
        "start_date",
        "end_date",
        "certification_period",
        "invalidated_at_utc",
        "replacement_certification_period_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
)
_W1C_GRADE_ROW_KEYS = frozenset(
    {
        "id",
        "recipient_id",
        "certification_period_id",
        "grade_code",
        "start_date",
        "end_date",
        "grade_period",
        "invalidated_at_utc",
        "replacement_grade_period_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
)
_W1D_CONTRACT_ROW_KEYS = frozenset(
    {
        "id",
        "recipient_id",
        "service_type_id",
        "start_date",
        "end_date",
        "contract_period",
        "service_start_date",
        "end_reason_text",
        "signer_name",
        "signer_relationship_text",
        "signer_phone",
        "invalidated_at_utc",
        "replacement_contract_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
)
_AUDIT_EVENT_ROW_KEYS = frozenset(
    {
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
    }
)


def _strict_nonbool_int(value: Any, *, label: str) -> int:
    """Reject bool and non-int; no int() coercion (R17 / REGINA-W1D-R16-H01)."""
    if type(value) is not int:
        _fail(f"{label}_NOT_STRICT_INT:{type(value).__name__}")
    return value


def _assert_keyset_exact(row: dict[str, Any], expected_keys: frozenset[str], *, label: str) -> None:
    actual = set(row.keys())
    if actual != set(expected_keys):
        missing = sorted(expected_keys - actual)
        extra = sorted(actual - expected_keys)
        _fail(
            f"{label}_KEYSET: missing={','.join(missing) if missing else '-'} "
            f"extra={','.join(extra) if extra else '-'}"
        )


def _half_open_daterange_json(start: date, end: date) -> str:
    """W1C/W1D half-open stored range: daterange(start, end+1, '[)')."""
    end_exclusive = end + timedelta(days=1)
    return f"[{start.isoformat()},{end_exclusive.isoformat()})"


def _open_ended_daterange_json(start: date) -> str:
    """Sealed unbounded upper half-open form: daterange(start, NULL, '[)') → [start,)."""
    return f"[{start.isoformat()},)"


def _normalize_range_text(value: Any) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        return f"__NON_STR__{type(value).__name__}"
    return value.replace(" ", "")


def _assert_range_matches(value: Any, expected: str, *, label: str) -> None:
    if _normalize_range_text(value) != _normalize_range_text(expected):
        _fail(f"{label}_RANGE")


def _assert_open_ended_range_exact(value: Any, start: date, *, label: str) -> None:
    """Exact [start,) only — reject infinity-containing or prefix-only garbage (R18)."""
    expected = _open_ended_daterange_json(start)
    if _normalize_range_text(value) != expected:
        _fail(f"{label}_OPEN_RANGE_NOT_EXACT")


def _assert_field_canon_equal(after_val: Any, before_val: Any, *, label: str, field: str) -> None:
    if _canon_row({field: after_val}) != _canon_row({field: before_val}):
        _fail(f"{label}_FIELD_{field}")


def _assert_ended_row_exact_projection(
    before_row: dict[str, Any],
    after_row: dict[str, Any],
    *,
    label: str,
    expected_keys: frozenset[str],
    period_key: str,
    proposed_end: date,
    account_id: int,
    sealed_apply_ts: datetime,
    expected_end_reason_text: Any = None,
    end_reason_key: str | None = None,
) -> None:
    """R17/R18: full-row ended projection with exact row_version+1.

    Allowed column deltas only:
    - end_date → proposed_end
    - row_version → before + 1 (strict non-bool int; never == or +2)
    - generated period range recomputed from start_date + proposed_end
    - updated_by_account_id → winner confirmer account_id
    - updated_at_utc → exact sealed_apply_ts and > pre-race value
    - optional end_reason_text when end_reason_key provided
    Every other persisted column must be exactly unchanged. Keyset must match.
    """
    _assert_keyset_exact(before_row, expected_keys, label=f"{label}_BEFORE")
    _assert_keyset_exact(after_row, expected_keys, label=f"{label}_AFTER")

    b_rv = _strict_nonbool_int(before_row.get("row_version"), label=f"{label}_BEFORE_RV")
    a_rv = _strict_nonbool_int(after_row.get("row_version"), label=f"{label}_AFTER_RV")
    if a_rv != b_rv + 1:
        # Rejects unchanged (false pass) and +2 / loser double-write.
        _fail(f"{label}_ROW_VERSION_NOT_EXACT_PLUS_ONE: before={b_rv} after={a_rv}")

    if not _date_field_equals(after_row.get("end_date"), proposed_end):
        _fail(f"{label}_END_DATE")

    start_d = _canonical_date(before_row.get("start_date"))
    if start_d is None:
        _fail(f"{label}_START_DATE_MISSING")
    start_date_obj = date.fromisoformat(start_d)
    _assert_range_matches(
        after_row.get(period_key),
        _half_open_daterange_json(start_date_obj, proposed_end),
        label=f"{label}_PERIOD",
    )

    if (
        _strict_nonbool_int(after_row.get("updated_by_account_id"), label=f"{label}_UPDATED_BY")
        != account_id
    ):
        _fail(f"{label}_UPDATED_BY_ACCOUNT")

    before_ts = _normalize_utc_timestamp(
        before_row.get("updated_at_utc"), label=f"{label}_BEFORE_UPDATED_AT"
    )
    after_ts = _normalize_utc_timestamp(
        after_row.get("updated_at_utc"), label=f"{label}_AFTER_UPDATED_AT"
    )
    # R18/R19: exact sealed apply timestamp + strictly after pre-race (pure predicate).
    ts_err = _validate_old_row_sealed_timestamp(
        before_ts=before_ts,
        after_ts=after_ts,
        sealed_apply_ts=sealed_apply_ts,
    )
    if ts_err is not None:
        _fail(f"{label}_{ts_err}")

    if end_reason_key is not None:
        if _canon_row({end_reason_key: after_row.get(end_reason_key)}) != _canon_row(
            {end_reason_key: expected_end_reason_text}
        ):
            _fail(f"{label}_END_REASON_TEXT")

    allowed_delta = {
        "end_date",
        "row_version",
        period_key,
        "updated_by_account_id",
        "updated_at_utc",
    }
    if end_reason_key is not None:
        allowed_delta.add(end_reason_key)

    for key in expected_keys:
        if key in allowed_delta:
            continue
        _assert_field_canon_equal(after_row.get(key), before_row.get(key), label=label, field=key)


def _assert_new_cert_row_complete(
    row: dict[str, Any],
    *,
    new_cert_id: int,
    recipient_id: int,
    new_start: date,
    new_end: date,
    account_id: int,
    sealed_apply_ts: datetime,
) -> None:
    """Complete W1C certification_period to_jsonb contract (no selected-field gaps)."""
    _assert_keyset_exact(row, _W1C_CERT_ROW_KEYS, label="W1D_TRN03_NEW_CERT")
    if _strict_nonbool_int(row.get("id"), label="W1D_TRN03_NEW_CERT_ID") != new_cert_id:
        _fail("W1D_TRN03_NEW_CERT_ID_VALUE")
    if _strict_nonbool_int(row.get("recipient_id"), label="W1D_TRN03_NEW_CERT_RID") != recipient_id:
        _fail("W1D_TRN03_NEW_CERT_RECIPIENT")
    if not _date_field_equals(row.get("start_date"), new_start):
        _fail("W1D_TRN03_NEW_CERT_START")
    if not _date_field_equals(row.get("end_date"), new_end):
        _fail("W1D_TRN03_NEW_CERT_END")
    _assert_range_matches(
        row.get("certification_period"),
        _half_open_daterange_json(new_start, new_end),
        label="W1D_TRN03_NEW_CERT_PERIOD",
    )
    if row.get("invalidated_at_utc") is not None:
        _fail("W1D_TRN03_NEW_CERT_INVALIDATED")
    if row.get("replacement_certification_period_id") is not None:
        _fail("W1D_TRN03_NEW_CERT_REPLACEMENT")
    if (
        _strict_nonbool_int(row.get("created_by_account_id"), label="W1D_TRN03_NEW_CERT_CB")
        != account_id
    ):
        _fail("W1D_TRN03_NEW_CERT_CREATED_BY")
    if (
        _strict_nonbool_int(row.get("updated_by_account_id"), label="W1D_TRN03_NEW_CERT_UB")
        != account_id
    ):
        _fail("W1D_TRN03_NEW_CERT_UPDATED_BY")
    if _strict_nonbool_int(row.get("row_version"), label="W1D_TRN03_NEW_CERT_RV") != 1:
        _fail("W1D_TRN03_NEW_CERT_ROW_VERSION")
    cat = _normalize_utc_timestamp(row.get("created_at_utc"), label="W1D_TRN03_NEW_CERT_CAT")
    uat = _normalize_utc_timestamp(row.get("updated_at_utc"), label="W1D_TRN03_NEW_CERT_UAT")
    if _validate_ts_exact_equal(cat, sealed_apply_ts) is not None:
        _fail("W1D_TRN03_NEW_CERT_CREATED_TS_NOT_SEALED")
    if _validate_ts_exact_equal(uat, sealed_apply_ts) is not None:
        _fail("W1D_TRN03_NEW_CERT_UPDATED_TS_NOT_SEALED")


def _assert_new_grade_row_complete(
    row: dict[str, Any],
    *,
    new_grade_id: int,
    new_cert_id: int,
    recipient_id: int,
    new_start: date,
    new_end: date,
    new_grade_code: str,
    account_id: int,
    sealed_apply_ts: datetime,
) -> None:
    _assert_keyset_exact(row, _W1C_GRADE_ROW_KEYS, label="W1D_TRN03_NEW_GRADE")
    if _strict_nonbool_int(row.get("id"), label="W1D_TRN03_NEW_GRADE_ID") != new_grade_id:
        _fail("W1D_TRN03_NEW_GRADE_ID_VALUE")
    if (
        _strict_nonbool_int(row.get("recipient_id"), label="W1D_TRN03_NEW_GRADE_RID")
        != recipient_id
    ):
        _fail("W1D_TRN03_NEW_GRADE_RECIPIENT")
    if (
        _strict_nonbool_int(row.get("certification_period_id"), label="W1D_TRN03_NEW_GRADE_PARENT")
        != new_cert_id
    ):
        _fail("W1D_TRN03_NEW_GRADE_PARENT_VALUE")
    if type(row.get("grade_code")) is not str or row.get("grade_code") != str(new_grade_code):
        _fail("W1D_TRN03_NEW_GRADE_CODE")
    if not _date_field_equals(row.get("start_date"), new_start):
        _fail("W1D_TRN03_NEW_GRADE_START")
    if not _date_field_equals(row.get("end_date"), new_end):
        _fail("W1D_TRN03_NEW_GRADE_END")
    _assert_range_matches(
        row.get("grade_period"),
        _half_open_daterange_json(new_start, new_end),
        label="W1D_TRN03_NEW_GRADE_PERIOD",
    )
    if row.get("invalidated_at_utc") is not None:
        _fail("W1D_TRN03_NEW_GRADE_INVALIDATED")
    if row.get("replacement_grade_period_id") is not None:
        _fail("W1D_TRN03_NEW_GRADE_REPLACEMENT")
    if (
        _strict_nonbool_int(row.get("created_by_account_id"), label="W1D_TRN03_NEW_GRADE_CB")
        != account_id
    ):
        _fail("W1D_TRN03_NEW_GRADE_CREATED_BY")
    if (
        _strict_nonbool_int(row.get("updated_by_account_id"), label="W1D_TRN03_NEW_GRADE_UB")
        != account_id
    ):
        _fail("W1D_TRN03_NEW_GRADE_UPDATED_BY")
    if _strict_nonbool_int(row.get("row_version"), label="W1D_TRN03_NEW_GRADE_RV") != 1:
        _fail("W1D_TRN03_NEW_GRADE_ROW_VERSION")
    gcat = _normalize_utc_timestamp(row.get("created_at_utc"), label="W1D_TRN03_NEW_GRADE_CAT")
    guat = _normalize_utc_timestamp(row.get("updated_at_utc"), label="W1D_TRN03_NEW_GRADE_UAT")
    if _validate_ts_exact_equal(gcat, sealed_apply_ts) is not None:
        _fail("W1D_TRN03_NEW_GRADE_CREATED_TS_NOT_SEALED")
    if _validate_ts_exact_equal(guat, sealed_apply_ts) is not None:
        _fail("W1D_TRN03_NEW_GRADE_UPDATED_TS_NOT_SEALED")


def _assert_new_contract_row_complete(
    row: dict[str, Any],
    *,
    new_contract_id: int,
    recipient_id: int,
    service_type_id: int,
    new_start: date,
    account_id: int,
    signer_name: Any,
    signer_relationship_text: Any,
    signer_phone: Any,
    end_reason_text: Any,
    service_start_date: Any,
    sealed_apply_ts: datetime,
) -> None:
    """Complete planned W1D 0011 recipient_contract to_jsonb contract."""
    _assert_keyset_exact(row, _W1D_CONTRACT_ROW_KEYS, label="W1D_TRN03_NEW_CONTRACT")
    if _strict_nonbool_int(row.get("id"), label="W1D_TRN03_NEW_CONTRACT_ID") != new_contract_id:
        _fail("W1D_TRN03_NEW_CONTRACT_ID_VALUE")
    if (
        _strict_nonbool_int(row.get("recipient_id"), label="W1D_TRN03_NEW_CONTRACT_RID")
        != recipient_id
    ):
        _fail("W1D_TRN03_NEW_CONTRACT_RECIPIENT")
    if (
        _strict_nonbool_int(row.get("service_type_id"), label="W1D_TRN03_NEW_CONTRACT_ST")
        != service_type_id
    ):
        _fail("W1D_TRN03_NEW_CONTRACT_SERVICE_TYPE")
    if not _date_field_equals(row.get("start_date"), new_start):
        _fail("W1D_TRN03_NEW_CONTRACT_START")
    if row.get("end_date") is not None:
        _fail("W1D_TRN03_NEW_CONTRACT_END_NOT_NULL")
    # R18: exact unbounded half-open [start,) only (no infinity/prefix garbage).
    _assert_open_ended_range_exact(
        row.get("contract_period"), new_start, label="W1D_TRN03_NEW_CONTRACT"
    )
    if service_start_date is None:
        if row.get("service_start_date") is not None:
            _fail("W1D_TRN03_NEW_CONTRACT_SERVICE_START")
    elif not _date_field_equals(row.get("service_start_date"), service_start_date):
        _fail("W1D_TRN03_NEW_CONTRACT_SERVICE_START_VALUE")
    for field, expected in (
        ("end_reason_text", end_reason_text),
        ("signer_name", signer_name),
        ("signer_relationship_text", signer_relationship_text),
        ("signer_phone", signer_phone),
    ):
        if _canon_row({field: row.get(field)}) != _canon_row({field: expected}):
            _fail(f"W1D_TRN03_NEW_CONTRACT_{field.upper()}")
    if row.get("invalidated_at_utc") is not None:
        _fail("W1D_TRN03_NEW_CONTRACT_INVALIDATED")
    if row.get("replacement_contract_id") is not None:
        _fail("W1D_TRN03_NEW_CONTRACT_REPLACEMENT")
    if (
        _strict_nonbool_int(row.get("created_by_account_id"), label="W1D_TRN03_NEW_CONTRACT_CB")
        != account_id
    ):
        _fail("W1D_TRN03_NEW_CONTRACT_CREATED_BY")
    if (
        _strict_nonbool_int(row.get("updated_by_account_id"), label="W1D_TRN03_NEW_CONTRACT_UB")
        != account_id
    ):
        _fail("W1D_TRN03_NEW_CONTRACT_UPDATED_BY")
    if _strict_nonbool_int(row.get("row_version"), label="W1D_TRN03_NEW_CONTRACT_RV") != 1:
        _fail("W1D_TRN03_NEW_CONTRACT_ROW_VERSION")
    ccat = _normalize_utc_timestamp(row.get("created_at_utc"), label="W1D_TRN03_NEW_CONTRACT_CAT")
    cuat = _normalize_utc_timestamp(row.get("updated_at_utc"), label="W1D_TRN03_NEW_CONTRACT_UAT")
    if _validate_ts_exact_equal(ccat, sealed_apply_ts) is not None:
        _fail("W1D_TRN03_NEW_CONTRACT_CREATED_TS_NOT_SEALED")
    if _validate_ts_exact_equal(cuat, sealed_apply_ts) is not None:
        _fail("W1D_TRN03_NEW_CONTRACT_UPDATED_TS_NOT_SEALED")


def _assert_single_winner_ledger_projection(
    connection,
    recipient_id: int,
    before: dict[str, list[dict[str, Any]]],
    *,
    old_cert_id: int,
    old_grade_id: int,
    old_contract_id: int,
    new_cert_id: int,
    new_grade_id: int,
    new_contract_id: int,
    proposed_end: date,
    new_start: date,
    new_end: date,
    new_grade_code: str,
    correlation: str,
    account_id: int,
    sealed_apply_ts: datetime,
    apply_window_start: datetime,
    apply_window_end: datetime,
    authorized_preview_hash: str,
    expected_before_proj: dict[str, Any],
    expected_after_proj: dict[str, Any],
    replacement_service_type_code: str = SERVICE_HOME_CARE,
    replacement_signer_name: Any = None,
    replacement_signer_relationship_text: Any = None,
    replacement_signer_phone: Any = None,
    replacement_end_reason_text: Any = None,
    replacement_service_start_date: Any = None,
    ended_contract_end_reason_text: Any = None,
) -> None:
    """J-W1D-R5-H04 / R17: exact single-winner full-row projection.

    Loser STALE must write zero. Allowed after-state differences vs pre-race:

    - old cert/grade/contract: exact full-row projection with end_date →
      proposed_end, row_version == before+1 (never == or +2), generated period
      recompute, updated_by = confirmer, updated_at >= before; all other columns
      byte-equal;
    - exactly one new cert, one new grade, one new contract with complete
      persisted keysets (W1C 0010 / W1D 0011) and every column validated from
      sealed inputs (not copied from after-state unchecked);
    - recipient / identity / counter unchanged;
    - audit: exact prefix + one CERTIFICATION_TRANSITION_APPLY full-row check.

    Selected counts alone are never sufficient.
    """
    after = _full_ledger_state(connection, recipient_id)

    _assert_rows_exact_equal(before["recipient"], after["recipient"], label="RECIPIENT")
    _assert_rows_exact_equal(before["identity"], after["identity"], label="IDENTITY")
    _assert_rows_exact_equal(before["counter"], after["counter"], label="COUNTER")

    before_cert = _index_rows_by_id(before["cert"], label="CERT_BEFORE")
    after_cert = _index_rows_by_id(after["cert"], label="CERT_AFTER")
    before_grade = _index_rows_by_id(before["grade"], label="GRADE_BEFORE")
    after_grade = _index_rows_by_id(after["grade"], label="GRADE_AFTER")
    before_ctr = _index_rows_by_id(before["contract"], label="CONTRACT_BEFORE")
    after_ctr = _index_rows_by_id(after["contract"], label="CONTRACT_AFTER")

    expected_cert_ids = set(before_cert) | {new_cert_id}
    expected_grade_ids = set(before_grade) | {new_grade_id}
    expected_ctr_ids = set(before_ctr) | {new_contract_id}
    if set(after_cert) != expected_cert_ids:
        _fail("W1D_TRN03_SINGLE_WINNER_CERT_ID_SET")
    if set(after_grade) != expected_grade_ids:
        _fail("W1D_TRN03_SINGLE_WINNER_GRADE_ID_SET")
    if set(after_ctr) != expected_ctr_ids:
        _fail("W1D_TRN03_SINGLE_WINNER_CONTRACT_ID_SET")

    for cid, brow in before_cert.items():
        if cid not in after_cert:
            _fail("W1D_TRN03_SINGLE_WINNER_CERT_MISSING_BEFORE")
        if cid == old_cert_id:
            _assert_ended_row_exact_projection(
                brow,
                after_cert[cid],
                label="W1D_TRN03_OLD_CERT",
                expected_keys=_W1C_CERT_ROW_KEYS,
                period_key="certification_period",
                proposed_end=proposed_end,
                account_id=account_id,
                sealed_apply_ts=sealed_apply_ts,
            )
        else:
            if _canon_row(brow) != _canon_row(after_cert[cid]):
                _fail("W1D_TRN03_SINGLE_WINNER_CERT_UNEXPECTED_MUTATION")
    for gid, brow in before_grade.items():
        if gid not in after_grade:
            _fail("W1D_TRN03_SINGLE_WINNER_GRADE_MISSING_BEFORE")
        if gid == old_grade_id:
            _assert_ended_row_exact_projection(
                brow,
                after_grade[gid],
                label="W1D_TRN03_OLD_GRADE",
                expected_keys=_W1C_GRADE_ROW_KEYS,
                period_key="grade_period",
                proposed_end=proposed_end,
                account_id=account_id,
                sealed_apply_ts=sealed_apply_ts,
            )
        else:
            if _canon_row(brow) != _canon_row(after_grade[gid]):
                _fail("W1D_TRN03_SINGLE_WINNER_GRADE_UNEXPECTED_MUTATION")
    for tid, brow in before_ctr.items():
        if tid not in after_ctr:
            _fail("W1D_TRN03_SINGLE_WINNER_CONTRACT_MISSING_BEFORE")
        if tid == old_contract_id:
            _assert_ended_row_exact_projection(
                brow,
                after_ctr[tid],
                label="W1D_TRN03_OLD_CONTRACT",
                expected_keys=_W1D_CONTRACT_ROW_KEYS,
                period_key="contract_period",
                proposed_end=proposed_end,
                account_id=account_id,
                sealed_apply_ts=sealed_apply_ts,
                expected_end_reason_text=ended_contract_end_reason_text,
                end_reason_key="end_reason_text",
            )
        else:
            if _canon_row(brow) != _canon_row(after_ctr[tid]):
                _fail("W1D_TRN03_SINGLE_WINNER_CONTRACT_UNEXPECTED_MUTATION")

    # Winner-created rows: complete keyset + every column from sealed inputs.
    try:
        service_type_id = connection.execute(
            text("SELECT id FROM erp.service_type WHERE code = :code LIMIT 1"),
            {"code": replacement_service_type_code},
        ).scalar()
    except Exception as exc:
        _fail("W1D_HARNESS_SERVICE_TYPE_LOOKUP: " + type(exc).__name__)
    if service_type_id is None:
        _fail("W1D_HARNESS_SERVICE_TYPE_MISSING: " + replacement_service_type_code)
    service_type_id = _strict_nonbool_int(service_type_id, label="W1D_TRN03_SERVICE_TYPE_ID")

    if new_cert_id not in after_cert:
        _fail("W1D_TRN03_SINGLE_WINNER_NEW_CERT_MISSING")
    _assert_new_cert_row_complete(
        after_cert[new_cert_id],
        new_cert_id=new_cert_id,
        recipient_id=recipient_id,
        new_start=new_start,
        new_end=new_end,
        account_id=account_id,
        sealed_apply_ts=sealed_apply_ts,
    )
    if new_grade_id not in after_grade:
        _fail("W1D_TRN03_SINGLE_WINNER_NEW_GRADE_MISSING")
    _assert_new_grade_row_complete(
        after_grade[new_grade_id],
        new_grade_id=new_grade_id,
        new_cert_id=new_cert_id,
        recipient_id=recipient_id,
        new_start=new_start,
        new_end=new_end,
        new_grade_code=new_grade_code,
        account_id=account_id,
        sealed_apply_ts=sealed_apply_ts,
    )
    if new_contract_id not in after_ctr:
        _fail("W1D_TRN03_SINGLE_WINNER_NEW_CONTRACT_MISSING")
    _assert_new_contract_row_complete(
        after_ctr[new_contract_id],
        new_contract_id=new_contract_id,
        recipient_id=recipient_id,
        service_type_id=service_type_id,
        new_start=new_start,
        account_id=account_id,
        signer_name=replacement_signer_name,
        signer_relationship_text=replacement_signer_relationship_text,
        signer_phone=replacement_signer_phone,
        end_reason_text=replacement_end_reason_text,
        service_start_date=replacement_service_start_date,
        sealed_apply_ts=sealed_apply_ts,
    )

    # Sealed apply timestamp must fall inside DB clock window (pure predicate).
    win_err = _validate_ts_in_window(sealed_apply_ts, apply_window_start, apply_window_end)
    if win_err is not None:
        _fail("W1D_TRN03_" + win_err)

    # Audit: exact prefix + exactly one winner transition append (full keyset).
    before_audit = before["audit"]
    after_audit = after["audit"]
    if len(after_audit) != len(before_audit) + 1:
        _fail(
            "W1D_TRN03_SINGLE_WINNER_AUDIT_LEN: "
            + f"before={len(before_audit)} after={len(after_audit)}"
        )
    if _canonical_audit_rows_json(before_audit) != _canonical_audit_rows_json(
        after_audit[: len(before_audit)]
    ):
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_PREFIX_MUTATED")
    appended = after_audit[-1]
    _assert_keyset_exact(appended, _AUDIT_EVENT_ROW_KEYS, label="W1D_TRN03_AUDIT_APPEND")
    if appended.get("action_code") != "CERTIFICATION_TRANSITION_APPLY":
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_ACTION")
    if appended.get("entity_type") != "RECIPIENT":
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_ENTITY_TYPE")
    if _strict_nonbool_int(appended.get("entity_pk"), label="W1D_TRN03_AUDIT_EPK") != recipient_id:
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_ENTITY_PK")
    if str(appended.get("request_id")) != str(correlation):
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_CORRELATION")
    if (
        _strict_nonbool_int(appended.get("actor_account_id"), label="W1D_TRN03_AUDIT_ACTOR")
        != account_id
    ):
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_ACTOR")
    if appended.get("actor_kind") != "USER":
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_ACTOR_KIND")
    if appended.get("reason_code") != "USER_CONFIRMED_TRANSITION":
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_REASON")
    if appended.get("reason_text") is not None:
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_REASON_TEXT")
    if appended.get("source_run_id") is not None:
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_SOURCE_RUN")
    if appended.get("created_from") != "API":
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_CREATED_FROM")
    audit_ts = _normalize_utc_timestamp(
        appended.get("occurred_at_utc"), label="W1D_TRN03_AUDIT_OCCURRED"
    )
    eq_err = _validate_ts_exact_equal(audit_ts, sealed_apply_ts)
    if eq_err is not None:
        _fail("W1D_TRN03_AUDIT_TS_NOT_SEALED")
    if _strict_nonbool_int(appended.get("id"), label="W1D_TRN03_AUDIT_ID") <= 0:
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_ID")

    # Exact before/after JSON via shared pure predicate (R19).
    b_err = _validate_exact_audit_projection(
        appended.get("before_json"),
        expected_before_proj,
        authorized_preview_hash=authorized_preview_hash,
        side="before",
    )
    if b_err is not None:
        _fail("W1D_TRN03_" + b_err)
    a_err = _validate_exact_audit_projection(
        appended.get("after_json"),
        expected_after_proj,
        authorized_preview_hash=authorized_preview_hash,
        side="after",
    )
    if a_err is not None:
        _fail("W1D_TRN03_" + a_err)
    apply_delta = [
        r
        for r in after_audit[len(before_audit) :]
        if r.get("action_code") == "CERTIFICATION_TRANSITION_APPLY"
    ]
    if len(apply_delta) != 1:
        _fail("W1D_TRN03_SINGLE_WINNER_AUDIT_APPLY_DELTA: " + str(len(apply_delta)))


# ---------------------------------------------------------------------------
# R19 pure validators (return error code or None; never pytest.fail)
# ---------------------------------------------------------------------------

_WINNER_KEYS = frozenset(
    {
        "status",
        "new_certification_period_id",
        "new_grade_period_id",
        "new_contract_ids",
        "audit_correlation_id",
    }
)


def _validate_structured_winner_shape(value: object) -> str | None:
    """Fail-closed pure winner shape check. None = OK; str = error code.

    Never calls pytest.fail / _fail. Used by assertion and mutant selfcheck.
    Internal structure requires audit_correlation_id type is UUID (not str).
    """
    if type(value) is not dict:
        return "W1D_TRN03_WINNER_NOT_DICT"
    if set(value.keys()) != set(_WINNER_KEYS):
        return "W1D_TRN03_WINNER_KEYSET"
    if value.get("status") != "SUCCESS":
        return "W1D_TRN03_WINNER_STATUS"
    cert = value.get("new_certification_period_id")
    if type(cert) is not int or cert <= 0:
        return "W1D_TRN03_WINNER_CERT_ID"
    grade = value.get("new_grade_period_id")
    if type(grade) is not int or grade <= 0:
        return "W1D_TRN03_WINNER_GRADE_ID"
    cids = value.get("new_contract_ids")
    if type(cids) is not list:
        return "W1D_TRN03_WINNER_CONTRACT_IDS_NOT_LIST"
    if len(cids) != 1:
        return "W1D_TRN03_WINNER_CONTRACT_IDS_LEN"
    if type(cids[0]) is not int or cids[0] <= 0:
        return "W1D_TRN03_WINNER_CONTRACT_ID"
    corr = value.get("audit_correlation_id")
    if type(corr) is not UUID:
        return "W1D_TRN03_WINNER_CORRELATION"
    return None


def _assert_structured_winner_shape(value: object) -> dict[str, Any]:
    err = _validate_structured_winner_shape(value)
    if err is not None:
        _fail(err)
    return value  # type: ignore[return-value]


def _try_pack_structured_winner_result(
    result: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Pure service→worker pack. None error = OK. UUID object only for correlation.

    HTTP JSON wire may carry UUID as string; the direct Python/Pydantic service
    response field and the internal worker structure must be UUID objects.
    No str parse/coercion at this boundary (R20).
    """
    new_cert = getattr(result, "new_certification_period_id", None)
    new_grade = getattr(result, "new_grade_period_id", None)
    new_contracts = getattr(result, "new_contract_ids", None)
    corr = getattr(result, "audit_correlation_id", None)
    if type(new_cert) is not int or new_cert <= 0:
        return None, "W1D_TRN03_WINNER_CERT_ID_TYPE"
    if type(new_grade) is not int or new_grade <= 0:
        return None, "W1D_TRN03_WINNER_GRADE_ID_TYPE"
    if type(new_contracts) is not list:
        return None, "W1D_TRN03_WINNER_CONTRACT_IDS_NOT_LIST"
    if len(new_contracts) != 1:
        return None, "W1D_TRN03_WINNER_CONTRACT_IDS_LEN"
    if type(new_contracts[0]) is not int or new_contracts[0] <= 0:
        return None, "W1D_TRN03_WINNER_CONTRACT_ID_TYPE"
    if type(corr) is not UUID:
        return None, "W1D_TRN03_WINNER_CORRELATION_TYPE"
    packed = {
        "status": "SUCCESS",
        "new_certification_period_id": new_cert,
        "new_grade_period_id": new_grade,
        "new_contract_ids": [new_contracts[0]],
        "audit_correlation_id": corr,
    }
    err = _validate_structured_winner_shape(packed)
    if err is not None:
        return None, err
    return packed, None


def _pack_structured_winner_result(result: Any) -> dict[str, Any]:
    """R20: strict pack via pure boundary; raises ValueError on error only."""
    packed, err = _try_pack_structured_winner_result(result)
    if err is not None or packed is None:
        raise ValueError(err or "W1D_TRN03_WINNER_PACK_FAILED")
    return packed


_TRY_NORMALIZE_CALLS = 0


def _try_normalize_utc_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    """Pure timestamp normalizer: (dt, None) or (None, error_code). Never _fail."""
    global _TRY_NORMALIZE_CALLS
    _TRY_NORMALIZE_CALLS += 1
    if type(value) is datetime:
        if value.tzinfo is None:
            return None, "TIMESTAMP_NAIVE"
        return value.astimezone(UTC), None
    if type(value) is str:
        text_value = value.strip()
        if not text_value:
            return None, "TIMESTAMP_EMPTY"
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text_value)
        except Exception:
            return None, "TIMESTAMP_PARSE"
        if parsed.tzinfo is None:
            return None, "TIMESTAMP_NAIVE"
        return parsed.astimezone(UTC), None
    return None, "TIMESTAMP_TYPE"


def _validate_ts_exact_equal(actual: datetime, sealed: datetime) -> str | None:
    if type(actual) is not datetime or type(sealed) is not datetime:
        return "TS_TYPE"
    if actual.tzinfo is None or sealed.tzinfo is None:
        return "TS_NAIVE"
    if actual.astimezone(UTC) != sealed.astimezone(UTC):
        return "TS_NOT_EQUAL"
    return None


def _validate_ts_strictly_after(before: datetime, after: datetime) -> str | None:
    if type(before) is not datetime or type(after) is not datetime:
        return "TS_TYPE"
    if before.tzinfo is None or after.tzinfo is None:
        return "TS_NAIVE"
    if not (after.astimezone(UTC) > before.astimezone(UTC)):
        return "TS_NOT_STRICTLY_AFTER"
    return None


def _validate_ts_in_window(
    ts: datetime, window_start: datetime, window_end: datetime
) -> str | None:
    if (
        type(ts) is not datetime
        or type(window_start) is not datetime
        or type(window_end) is not datetime
    ):
        return "TS_TYPE"
    if ts.tzinfo is None or window_start.tzinfo is None or window_end.tzinfo is None:
        return "TS_NAIVE"
    t = ts.astimezone(UTC)
    s = window_start.astimezone(UTC)
    e = window_end.astimezone(UTC)
    if t < s:
        return "TS_BEFORE_WINDOW"
    if t > e:
        return "TS_AFTER_WINDOW"
    return None


def _validate_old_row_sealed_timestamp(
    *,
    before_ts: datetime,
    after_ts: datetime,
    sealed_apply_ts: datetime,
) -> str | None:
    """Shared old-row timestamp relation: after == sealed and after > before."""
    eq = _validate_ts_exact_equal(after_ts, sealed_apply_ts)
    if eq is not None:
        return "UPDATED_AT_NOT_SEALED_TS"
    rel = _validate_ts_strictly_after(before_ts, after_ts)
    if rel is not None:
        return "UPDATED_AT_NOT_STRICTLY_AFTER_BEFORE"
    return None


def _proj_decode(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Pure decode of audit JSONB projection field."""
    proj: Any = raw
    if type(proj) is str:
        try:
            proj = json.loads(proj)
        except Exception:
            return None, "AUDIT_PROJ_DECODE"
    if type(proj) is not dict:
        return None, "AUDIT_PROJ_TYPE"
    return proj, None


def _is_json_domain_value(value: Any) -> bool:
    """Recursive JSON/JSONB domain only (R21/R22).

    Accepts None/bool/str/int/finite float/list/dict-with-str-keys recursively.
    Rejects non-finite floats (NaN, +inf, -inf), UUID/date/datetime, tuple/set,
    custom objects, non-string dict keys, and nested non-JSON values.
    """
    if value is None or type(value) is bool or type(value) is str:
        return True
    if type(value) is int:  # rejects bool (already handled above)
        return True
    if type(value) is float:
        # JSON has no NaN/Infinity; keep exact float equality for finite only.
        return value == value and abs(value) != float("inf")
    if type(value) is list:
        return all(_is_json_domain_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _is_json_domain_value(item) for key, item in value.items())
    return False


def _json_domain_values_equal(left: Any, right: Any) -> bool:
    """Exact structure/type/value equality without default=str coercion (R21/B1)."""
    if not _is_json_domain_value(left) or not _is_json_domain_value(right):
        return False
    if type(left) is not type(right):
        # JSON null only matches None; bool is not int.
        return False
    if type(left) is list:
        if len(left) != len(right):
            return False
        return all(_json_domain_values_equal(a, b) for a, b in zip(left, right, strict=True))
    if type(left) is dict:
        if set(left.keys()) != set(right.keys()):
            return False
        return all(_json_domain_values_equal(left[k], right[k]) for k in left)
    return left == right


def _validate_exact_audit_projection(
    actual_raw: Any,
    expected: dict[str, Any],
    *,
    authorized_preview_hash: str,
    side: str,
) -> str | None:
    """Pure exact audit before_json/after_json predicate. None = OK.

    Requires exact JSON structure/types/values vs expected, exact authorized
    preview_hash, before omits new_ids, after has dict new_ids.
    """
    if type(expected) is not dict:
        return f"AUDIT_{side.upper()}_EXPECTED_TYPE"
    actual, err = _proj_decode(actual_raw)
    if err is not None:
        return f"AUDIT_{side.upper()}_{err}"
    assert actual is not None
    # R21/Joseph R7 B1: JSON-domain only — no default=str (date/tuple false-pass).
    if not _json_domain_values_equal(actual, expected):
        return f"AUDIT_{side.upper()}_JSON_NOT_EXACT"
    if actual.get("preview_hash") != authorized_preview_hash:
        return f"AUDIT_{side.upper()}_PREVIEW_HASH"
    if type(authorized_preview_hash) is not str or len(authorized_preview_hash) != 64:
        return f"AUDIT_{side.upper()}_PREVIEW_HASH_SHAPE"
    if side == "before":
        if "new_ids" in actual:
            return "AUDIT_BEFORE_HAS_NEW_IDS"
    elif side == "after":
        if "new_ids" not in actual or type(actual.get("new_ids")) is not dict:
            return "AUDIT_AFTER_NEW_IDS_MISSING"
        # nested containers required in sealed projection
        for key in (
            "certification_periods",
            "grade_periods",
            "contracts",
            "service_multiset",
        ):
            if key not in actual:
                return f"AUDIT_AFTER_MISSING_{key}"
            if key == "service_multiset":
                if type(actual[key]) is not list:
                    return "AUDIT_AFTER_MULTISET_TYPE"
            elif type(actual[key]) is not list:
                return f"AUDIT_AFTER_{key.upper()}_TYPE"
    else:
        return "AUDIT_SIDE_UNKNOWN"
    return None


def _r19_winner_mutant_selfcheck() -> None:
    """R19: pure winner mutants via shared validator (never catch BaseException)."""
    good = {
        "status": "SUCCESS",
        "new_certification_period_id": 1,
        "new_grade_period_id": 2,
        "new_contract_ids": [3],
        "audit_correlation_id": UUID("12345678-1234-5678-1234-567812345678"),
    }
    if _validate_structured_winner_shape(good) is not None:
        _fail("W1D_R19_WINNER_MUTANT_GOOD_REJECTED")
    mutants: list[tuple[object, str]] = [
        ("ok:1:2:[3]:x", "text_payload"),
        ({**good, "new_certification_period_id": "1"}, "string_id"),
        ({**good, "new_certification_period_id": True}, "bool_id"),
        ({**good, "new_certification_period_id": 0}, "nonpositive"),
        ({**good, "new_contract_ids": 3}, "scalar_cids"),
        ({**good, "new_contract_ids": (3,)}, "tuple_cids"),
        ({**good, "new_contract_ids": ["3"]}, "str_member"),
        ({**good, "new_contract_ids": [3, 4]}, "len2"),
        ({**good, "new_contract_ids": []}, "len0"),
        ({**good, "audit_correlation_id": "12345678-1234-5678-1234-567812345678"}, "str_uuid"),
        ({**good, "audit_correlation_id": "not-a-uuid"}, "bad_uuid"),
        ({**good, "status": "OK"}, "wrong_status"),
        ({k: v for k, v in good.items() if k != "status"}, "missing_key"),
        ({**good, "extra": 1}, "extra_key"),
        ({"status": "SUCCESS"}, "incomplete"),
        (None, "none"),
        (42, "int_container"),
    ]
    for payload, tag in mutants:
        if _validate_structured_winner_shape(payload) is None:
            _fail(f"W1D_R19_WINNER_MUTANT_ACCEPTED:{tag}")


def _r19_timestamp_mutant_selfcheck() -> None:
    """R19: pure timestamp relation mutants shared with actual assertions."""
    sealed = datetime(2035, 7, 1, 12, 0, 0, tzinfo=UTC)
    before = datetime(2035, 7, 1, 11, 0, 0, tzinfo=UTC)
    after = sealed
    window_start = datetime(2035, 7, 1, 11, 59, 0, tzinfo=UTC)
    window_end = datetime(2035, 7, 1, 12, 1, 0, tzinfo=UTC)
    # Valid control.
    if (
        _validate_old_row_sealed_timestamp(before_ts=before, after_ts=after, sealed_apply_ts=sealed)
        is not None
    ):
        _fail("W1D_R19_TS_MUTANT_GOOD_OLD_REJECTED")
    if _validate_ts_in_window(sealed, window_start, window_end) is not None:
        _fail("W1D_R19_TS_MUTANT_GOOD_WINDOW_REJECTED")
    if _validate_ts_exact_equal(sealed, sealed) is not None:
        _fail("W1D_R19_TS_MUTANT_GOOD_EQUAL_REJECTED")
    # Unequal row/audit timestamp.
    if _validate_ts_exact_equal(datetime(2035, 7, 1, 12, 0, 1, tzinfo=UTC), sealed) is None:
        _fail("W1D_R19_TS_MUTANT_UNEQUAL_ACCEPTED")
    # Equality / not strictly after old.
    if _validate_ts_strictly_after(before, before) is None:
        _fail("W1D_R19_TS_MUTANT_EQUAL_OLD_ACCEPTED")
    if _validate_ts_strictly_after(sealed, before) is None:
        _fail("W1D_R19_TS_MUTANT_BEFORE_OLD_ACCEPTED")
    # Window edges.
    if (
        _validate_ts_in_window(
            datetime(2035, 7, 1, 11, 58, 0, tzinfo=UTC), window_start, window_end
        )
        is None
    ):
        _fail("W1D_R19_TS_MUTANT_BEFORE_WINDOW_ACCEPTED")
    if (
        _validate_ts_in_window(datetime(2035, 7, 1, 12, 2, 0, tzinfo=UTC), window_start, window_end)
        is None
    ):
        _fail("W1D_R19_TS_MUTANT_AFTER_WINDOW_ACCEPTED")
    # Naive / wrong type.
    naive = datetime(2035, 7, 1, 12, 0, 0)
    if _try_normalize_utc_timestamp(naive)[1] is None:
        _fail("W1D_R19_TS_MUTANT_NAIVE_ACCEPTED")
    if _try_normalize_utc_timestamp(123)[1] is None:
        _fail("W1D_R19_TS_MUTANT_INT_ACCEPTED")
    if _validate_ts_exact_equal(naive, sealed) is None:  # type: ignore[arg-type]
        _fail("W1D_R19_TS_MUTANT_NAIVE_EQUAL_ACCEPTED")


def _r19_open_range_mutant_selfcheck() -> None:
    start = date(2035, 7, 1)
    exact = _open_ended_daterange_json(start)
    if _normalize_range_text(exact) != "[2035-07-01,)":
        _fail("W1D_R19_OPEN_RANGE_CANON")
    for bad in (
        "[2035-07-01,infinity)",
        "[2035-07-01,not-a-valid-upper-infinity)",
        "[2035-07-01,2036-01-01)",
        "2035-07-01",
        None,
        1,
    ):
        if _normalize_range_text(bad) == exact:
            _fail(f"W1D_R19_OPEN_RANGE_MUTANT_ACCEPTED:{bad!r}")


def _r19_audit_proj_mutant_selfcheck() -> None:
    """R19/R20: every mutant invokes shared _validate_exact_audit_projection."""
    ph = "a" * 64
    before_ok = {
        "preview_hash": ph,
        "certification_periods": [{"id": 1, "row_version": 1}],
        "grade_periods": [{"id": 10, "grade_code": "3"}],
        "contracts": [{"id": 100, "service_type_code": "HOME_CARE"}],
        "service_multiset": ["HOME_CARE"],
    }
    after_ok = {
        "preview_hash": ph,
        "certification_periods": [
            {"id": 1, "row_version": 2},
            {"id": 2, "row_version": 1},
        ],
        "grade_periods": [
            {"id": 10, "grade_code": "3"},
            {"id": 3, "grade_code": "4"},
        ],
        "contracts": [
            {"id": 100, "service_type_code": "HOME_CARE"},
            {"id": 4, "service_type_code": "HOME_CARE"},
        ],
        "service_multiset": ["HOME_CARE"],
        "new_ids": {
            "certification_period_id": 2,
            "grade_period_id": 3,
            "contract_ids": [4],
        },
    }

    def _rej(actual: Any, expected: dict[str, Any], *, side: str, tag: str) -> None:
        if (
            _validate_exact_audit_projection(
                actual, expected, authorized_preview_hash=ph, side=side
            )
            is None
        ):
            _fail(f"W1D_R20_AUDIT_MUTANT_ACCEPTED:{tag}")

    def _acc(actual: Any, expected: dict[str, Any], *, side: str, tag: str) -> None:
        if (
            _validate_exact_audit_projection(
                actual, expected, authorized_preview_hash=ph, side=side
            )
            is not None
        ):
            _fail(f"W1D_R20_AUDIT_MUTANT_GOOD_REJECTED:{tag}")

    _acc(before_ok, before_ok, side="before", tag="before_control")
    _acc(after_ok, after_ok, side="after", tag="after_control")
    # Top-level missing/extra
    _rej(
        {**before_ok, "extra": 1},
        before_ok,
        side="before",
        tag="top_extra",
    )
    _rej(
        {k: v for k, v in before_ok.items() if k != "preview_hash"},
        before_ok,
        side="before",
        tag="top_missing_preview",
    )
    _rej(
        {**before_ok, "preview_hash": "b" * 64},
        before_ok,
        side="before",
        tag="wrong_preview_hash",
    )
    # new_ids: missing whole / wrong members / extra member / wrong types
    _rej(before_ok, after_ok, side="after", tag="missing_whole_new_ids")
    _rej({**after_ok, "new_ids": "x"}, after_ok, side="after", tag="new_ids_type")
    bad_cert = dict(after_ok)
    bad_cert["new_ids"] = {
        **after_ok["new_ids"],
        "certification_period_id": 999,
    }
    _rej(bad_cert, after_ok, side="after", tag="wrong_cert_id")
    bad_grade = dict(after_ok)
    bad_grade["new_ids"] = {**after_ok["new_ids"], "grade_period_id": 999}
    _rej(bad_grade, after_ok, side="after", tag="wrong_grade_id")
    bad_cids = dict(after_ok)
    bad_cids["new_ids"] = {**after_ok["new_ids"], "contract_ids": [999]}
    _rej(bad_cids, after_ok, side="after", tag="wrong_contract_ids_value")
    bad_cids_t = dict(after_ok)
    bad_cids_t["new_ids"] = {**after_ok["new_ids"], "contract_ids": 4}
    _rej(bad_cids_t, after_ok, side="after", tag="wrong_contract_ids_type")
    bad_cids_m = dict(after_ok)
    bad_cids_m["new_ids"] = {**after_ok["new_ids"], "contract_ids": ["4"]}
    _rej(bad_cids_m, after_ok, side="after", tag="wrong_contract_ids_member")
    for member in (
        "certification_period_id",
        "grade_period_id",
        "contract_ids",
    ):
        nid = dict(after_ok["new_ids"])
        del nid[member]
        _rej(
            {**after_ok, "new_ids": nid},
            after_ok,
            side="after",
            tag=f"missing_new_ids_{member}",
        )
    nid_extra = {**after_ok["new_ids"], "extra_member": 1}
    _rej(
        {**after_ok, "new_ids": nid_extra},
        after_ok,
        side="after",
        tag="extra_new_ids_member",
    )
    # Nested period/contract/multiset value and key/container
    bad_nested = dict(after_ok)
    bad_nested["contracts"] = [
        {"id": 100, "service_type_code": "HOME_CARE"},
        {"id": 999, "service_type_code": "HOME_CARE"},
    ]
    _rej(bad_nested, after_ok, side="after", tag="nested_contract_value")
    bad_period = dict(after_ok)
    bad_period["certification_periods"] = [
        {"id": 1, "row_version": 2},
        {"id": 2, "row_version": 9},
    ]
    _rej(bad_period, after_ok, side="after", tag="nested_period_value")
    bad_ms = dict(after_ok)
    bad_ms["service_multiset"] = ["HOME_BATH"]
    _rej(bad_ms, after_ok, side="after", tag="multiset_value")
    # Missing/extra nested row key
    bad_row_key = dict(after_ok)
    bad_row_key["contracts"] = [
        {"id": 100, "service_type_code": "HOME_CARE"},
        {"id": 4, "service_type_code": "HOME_CARE", "extra": 1},
    ]
    _rej(bad_row_key, after_ok, side="after", tag="nested_extra_row_key")
    bad_row_missing = dict(after_ok)
    bad_row_missing["contracts"] = [
        {"id": 100, "service_type_code": "HOME_CARE"},
        {"id": 4},
    ]
    _rej(bad_row_missing, after_ok, side="after", tag="nested_missing_row_key")
    # Wrong nested/container type
    bad_type = dict(after_ok)
    bad_type["contracts"] = {"id": 4}
    _rej(bad_type, after_ok, side="after", tag="nested_container_type")
    bad_list_item = dict(after_ok)
    bad_list_item["grade_periods"] = ["not-a-dict"]
    _rej(bad_list_item, after_ok, side="after", tag="nested_item_type")
    # Decode/type top-level
    _rej("{not-json", before_ok, side="before", tag="decode")
    _rej([1, 2], before_ok, side="before", tag="list_top")
    # Joseph R7 B1: non-JSON domain must not pass via default=str/tuple coercion.
    date_mut = dict(before_ok)
    date_mut["certification_periods"] = [{"id": 1, "start": date(2035, 1, 1)}]
    exp_date = dict(before_ok)
    exp_date["certification_periods"] = [{"id": 1, "start": "2035-01-01"}]
    _rej(date_mut, exp_date, side="before", tag="non_json_date")
    tup_mut = dict(before_ok)
    tup_mut["contracts"] = tuple(before_ok["contracts"])  # type: ignore[assignment]
    _rej(tup_mut, before_ok, side="before", tag="tuple_container")

    # R22: every non-JSON domain mutant still goes through shared predicate only.
    class _CustomAuditObj:
        pass

    custom_mut = dict(before_ok)
    custom_mut["certification_periods"] = [{"id": 1, "row_version": 1, "x": _CustomAuditObj()}]
    _rej(custom_mut, before_ok, side="before", tag="non_json_custom_object")
    uuid_mut = dict(before_ok)
    uuid_mut["certification_periods"] = [
        {
            "id": 1,
            "row_version": 1,
            "x": UUID("12345678-1234-5678-1234-567812345678"),
        }
    ]
    _rej(uuid_mut, before_ok, side="before", tag="non_json_uuid")
    nan_actual = dict(before_ok)
    nan_actual["certification_periods"] = [{"id": 1, "row_version": float("nan")}]
    nan_expected = dict(before_ok)
    nan_expected["certification_periods"] = [{"id": 1, "row_version": float("nan")}]
    _rej(nan_actual, nan_expected, side="before", tag="non_json_nan")
    pinf_actual = dict(before_ok)
    pinf_actual["certification_periods"] = [{"id": 1, "row_version": float("inf")}]
    pinf_expected = dict(before_ok)
    pinf_expected["certification_periods"] = [{"id": 1, "row_version": float("inf")}]
    _rej(pinf_actual, pinf_expected, side="before", tag="non_json_pos_inf")
    ninf_actual = dict(before_ok)
    ninf_actual["certification_periods"] = [{"id": 1, "row_version": float("-inf")}]
    ninf_expected = dict(before_ok)
    ninf_expected["certification_periods"] = [{"id": 1, "row_version": float("-inf")}]
    _rej(ninf_actual, ninf_expected, side="before", tag="non_json_neg_inf")
    nonstr_key_mut = dict(before_ok)
    nonstr_key_mut["certification_periods"] = [
        {1: "bad", "id": 1, "row_version": 1}  # type: ignore[dict-item]
    ]
    _rej(nonstr_key_mut, before_ok, side="before", tag="non_json_nonstr_key")
    nested_set_mut = dict(before_ok)
    nested_set_mut["certification_periods"] = [{"id": 1, "row_version": 1, "tags": {1, 2}}]
    _rej(nested_set_mut, before_ok, side="before", tag="nested_non_json_set")
    # Finite float remains JSON-domain when structure/types match exactly.
    fin_ok = dict(before_ok)
    fin_ok["certification_periods"] = [{"id": 1, "row_version": 1.5}]
    _acc(fin_ok, fin_ok, side="before", tag="finite_float_control")


def _r20_pack_mutant_selfcheck() -> None:
    """R20: pack boundary accepts UUID object only; rejects UUID string."""

    class _Fake:
        def __init__(self, **kw: Any) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    good_uuid = UUID("12345678-1234-5678-1234-567812345678")
    good = _Fake(
        new_certification_period_id=1,
        new_grade_period_id=2,
        new_contract_ids=[3],
        audit_correlation_id=good_uuid,
    )
    packed, err = _try_pack_structured_winner_result(good)
    if err is not None or packed is None:
        _fail("W1D_R20_PACK_MUTANT_GOOD_REJECTED")
    if type(packed["audit_correlation_id"]) is not UUID:
        _fail("W1D_R20_PACK_MUTANT_GOOD_NOT_UUID")
    # Valid UUID string must REJECT (no coercion).
    str_uuid = _Fake(
        new_certification_period_id=1,
        new_grade_period_id=2,
        new_contract_ids=[3],
        audit_correlation_id="12345678-1234-5678-1234-567812345678",
    )
    _p, e = _try_pack_structured_winner_result(str_uuid)
    if e is None:
        _fail("W1D_R20_PACK_MUTANT_UUID_STRING_ACCEPTED")
    for tag, obj in (
        (
            "invalid_str",
            _Fake(
                new_certification_period_id=1,
                new_grade_period_id=2,
                new_contract_ids=[3],
                audit_correlation_id="not-a-uuid",
            ),
        ),
        (
            "none_corr",
            _Fake(
                new_certification_period_id=1,
                new_grade_period_id=2,
                new_contract_ids=[3],
                audit_correlation_id=None,
            ),
        ),
        (
            "int_corr",
            _Fake(
                new_certification_period_id=1,
                new_grade_period_id=2,
                new_contract_ids=[3],
                audit_correlation_id=1,
            ),
        ),
        (
            "bool_corr",
            _Fake(
                new_certification_period_id=1,
                new_grade_period_id=2,
                new_contract_ids=[3],
                audit_correlation_id=True,
            ),
        ),
        (
            "bad_cert",
            _Fake(
                new_certification_period_id="1",
                new_grade_period_id=2,
                new_contract_ids=[3],
                audit_correlation_id=good_uuid,
            ),
        ),
        (
            "bad_list",
            _Fake(
                new_certification_period_id=1,
                new_grade_period_id=2,
                new_contract_ids=3,
                audit_correlation_id=good_uuid,
            ),
        ),
        (
            "bad_member",
            _Fake(
                new_certification_period_id=1,
                new_grade_period_id=2,
                new_contract_ids=["3"],
                audit_correlation_id=good_uuid,
            ),
        ),
    ):
        _pp, ee = _try_pack_structured_winner_result(obj)
        if ee is None:
            _fail(f"W1D_R20_PACK_MUTANT_ACCEPTED:{tag}")


def _r20_normalizer_coupling_selfcheck() -> None:
    """Prove actual _normalize_utc_timestamp delegates to pure helper."""
    import inspect

    src = inspect.getsource(_normalize_utc_timestamp)
    if "_try_normalize_utc_timestamp(" not in src:
        _fail("W1D_R20_NORMALIZER_SOURCE_NOT_DELEGATING")
    before = _TRY_NORMALIZE_CALLS
    got = _normalize_utc_timestamp(datetime(2035, 1, 1, 0, 0, 0, tzinfo=UTC), label="r20_coupling")
    if got.tzinfo is None:
        _fail("W1D_R20_NORMALIZER_COUPLING_NAIVE")
    if _TRY_NORMALIZE_CALLS <= before:
        _fail("W1D_R20_NORMALIZER_PURE_NOT_CALLED")
    # Pure path still rejects naive via same function.
    dt, err = _try_normalize_utc_timestamp(datetime(2035, 1, 1, 0, 0, 0))
    if err is None or dt is not None:
        _fail("W1D_R20_NORMALIZER_PURE_NAIVE_ACCEPTED")


_HTTP_APPLY_RESPONSE_KEYS = frozenset(
    {
        "recipient_id",
        "ended_certification_period_ids",
        "ended_grade_period_ids",
        "ended_contract_ids",
        "new_certification_period_id",
        "new_grade_period_id",
        "new_contract_ids",
        "audit_correlation_id",
        "recipient_no",
    }
)
_CANONICAL_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _canonical_uuid_str(value: object) -> str | None:
    """HTTP wire correlation: already-canonical lowercase UUID string only.

    Never lowercases or coerces; uppercase/noncanonical/malformed reject.
    """
    if type(value) is not str:
        return None
    if not _CANONICAL_UUID_RE.fullmatch(value):
        return None
    return value


def _canonical_audit_request_id(raw: object) -> str | None:
    """Same-apply audit request_id → exact canonical lowercase UUID string.

    Accept raw UUID object via exact str(uuid) only, or an already-canonical
    lowercase UUID string. Never .lower()/.coerce string forms (R22).
    """
    if type(raw) is UUID:
        return _canonical_uuid_str(str(raw))
    if type(raw) is str:
        return _canonical_uuid_str(raw)
    return None


def _strict_positive_int_list(value: object, *, exact_len: int | None = None) -> bool:
    if type(value) is not list:
        return False
    if exact_len is not None and len(value) != exact_len:
        return False
    if len(value) < 1:
        return False
    if any(type(x) is not int or x <= 0 for x in value):
        return False
    if len(set(value)) != len(value):
        return False
    return True


def _strict_nonneg_int_list(value: object) -> bool:
    """Strict list of unique positive ints; empty allowed for ended-* only."""
    if type(value) is not list:
        return False
    if any(type(x) is not int or x <= 0 for x in value):
        return False
    if len(set(value)) != len(value):
        return False
    return True


def _validate_http_apply_success_response(
    body: object,
    *,
    expected_recipient_id: int,
    expected_recipient_no: str,
    expected_audit_request_id: str,
    expected_ended_certification_period_ids: list[int],
    expected_ended_grade_period_ids: list[int],
    expected_ended_contract_ids: list[int],
    expected_new_certification_period_id: int,
    expected_new_grade_period_id: int,
    expected_new_contract_ids: list[int],
) -> str | None:
    """Pure HTTP CertificationTransitionApplyResponse gate (R21/R22).

    None = OK. Never pytest.fail. Shared by assertion + mutant selfcheck.
    Actual path requires exact ended IDs, exact new IDs (list type/order/values),
    recipient_id/recipient_no, and audit_correlation_id equal to the exact
    canonical same-apply audit request_id. No optional/count-only binding.
    """
    if type(body) is not dict:
        return "HTTP_APPLY_NOT_DICT"
    if set(body.keys()) != set(_HTTP_APPLY_RESPONSE_KEYS):
        return "HTTP_APPLY_KEYSET"
    rid = body.get("recipient_id")
    if type(rid) is not int or rid <= 0:
        return "HTTP_APPLY_RECIPIENT_ID"
    if type(expected_recipient_id) is not int or expected_recipient_id <= 0:
        return "HTTP_APPLY_EXPECTED_RECIPIENT_ID"
    if rid != expected_recipient_id:
        return "HTTP_APPLY_RECIPIENT_ID_VALUE"
    for list_key, expected in (
        (
            "ended_certification_period_ids",
            expected_ended_certification_period_ids,
        ),
        ("ended_grade_period_ids", expected_ended_grade_period_ids),
        ("ended_contract_ids", expected_ended_contract_ids),
    ):
        v = body.get(list_key)
        if not _strict_nonneg_int_list(v):
            return f"HTTP_APPLY_{list_key.upper()}_TYPE"
        if type(expected) is not list or not _strict_nonneg_int_list(expected):
            return f"HTTP_APPLY_{list_key.upper()}_EXPECTED"
        if v != expected:
            return f"HTTP_APPLY_{list_key.upper()}_VALUE"
    ncert = body.get("new_certification_period_id")
    if type(ncert) is not int or ncert <= 0:
        return "HTTP_APPLY_NEW_CERT_ID"
    if (
        type(expected_new_certification_period_id) is not int
        or expected_new_certification_period_id <= 0
    ):
        return "HTTP_APPLY_EXPECTED_NEW_CERT_ID"
    if ncert != expected_new_certification_period_id:
        return "HTTP_APPLY_NEW_CERT_ID_VALUE"
    ngrade = body.get("new_grade_period_id")
    if type(ngrade) is not int or ngrade <= 0:
        return "HTTP_APPLY_NEW_GRADE_ID"
    if type(expected_new_grade_period_id) is not int or expected_new_grade_period_id <= 0:
        return "HTTP_APPLY_EXPECTED_NEW_GRADE_ID"
    if ngrade != expected_new_grade_period_id:
        return "HTTP_APPLY_NEW_GRADE_ID_VALUE"
    ncids = body.get("new_contract_ids")
    if type(expected_new_contract_ids) is not list or not _strict_positive_int_list(
        expected_new_contract_ids,
        exact_len=len(expected_new_contract_ids)
        if type(expected_new_contract_ids) is list
        else None,
    ):
        return "HTTP_APPLY_EXPECTED_NEW_CONTRACT_IDS"
    if not _strict_positive_int_list(ncids, exact_len=len(expected_new_contract_ids)):
        if type(ncids) is not list:
            return "HTTP_APPLY_NEW_CONTRACT_IDS_TYPE"
        return "HTTP_APPLY_NEW_CONTRACT_IDS"
    if ncids != expected_new_contract_ids:
        return "HTTP_APPLY_NEW_CONTRACT_IDS_VALUE"
    corr = _canonical_uuid_str(body.get("audit_correlation_id"))
    if corr is None:
        return "HTTP_APPLY_CORRELATION"
    exp = _canonical_uuid_str(expected_audit_request_id)
    if exp is None:
        return "HTTP_APPLY_AUDIT_REQUEST_ID_SHAPE"
    if corr != exp:
        return "HTTP_APPLY_CORRELATION_AUDIT_MISMATCH"
    rno = body.get("recipient_no")
    if type(rno) is not str or not RECIPIENT_NO_EXACT_RE.fullmatch(rno):
        return "HTTP_APPLY_RECIPIENT_NO"
    if type(expected_recipient_no) is not str or not RECIPIENT_NO_EXACT_RE.fullmatch(
        expected_recipient_no
    ):
        return "HTTP_APPLY_EXPECTED_RECIPIENT_NO"
    if rno != expected_recipient_no:
        return "HTTP_APPLY_RECIPIENT_NO_VALUE"
    return None


def _assert_http_apply_success_response(
    body: object,
    *,
    expected_recipient_id: int,
    expected_recipient_no: str,
    expected_audit_request_id: str,
    expected_ended_certification_period_ids: list[int],
    expected_ended_grade_period_ids: list[int],
    expected_ended_contract_ids: list[int],
    expected_new_certification_period_id: int,
    expected_new_grade_period_id: int,
    expected_new_contract_ids: list[int],
) -> dict[str, Any]:
    err = _validate_http_apply_success_response(
        body,
        expected_recipient_id=expected_recipient_id,
        expected_recipient_no=expected_recipient_no,
        expected_audit_request_id=expected_audit_request_id,
        expected_ended_certification_period_ids=expected_ended_certification_period_ids,
        expected_ended_grade_period_ids=expected_ended_grade_period_ids,
        expected_ended_contract_ids=expected_ended_contract_ids,
        expected_new_certification_period_id=expected_new_certification_period_id,
        expected_new_grade_period_id=expected_new_grade_period_id,
        expected_new_contract_ids=expected_new_contract_ids,
    )
    if err is not None:
        _fail(err)
    return body  # type: ignore[return-value]


def _r21_http_apply_mutant_selfcheck() -> None:
    """R21/R22: pure HTTP apply response/ID-binding mutants (no BaseException catch)."""
    good_corr = "a2345678-1234-5678-1234-567812345678"
    good = {
        "recipient_id": 1,
        "ended_certification_period_ids": [10],
        "ended_grade_period_ids": [11],
        "ended_contract_ids": [12, 13],
        "new_certification_period_id": 20,
        "new_grade_period_id": 21,
        "new_contract_ids": [30, 31],
        "audit_correlation_id": good_corr,
        "recipient_no": "000001",
    }
    expect_kw: dict[str, Any] = {
        "expected_recipient_id": 1,
        "expected_recipient_no": "000001",
        "expected_audit_request_id": good_corr,
        "expected_ended_certification_period_ids": [10],
        "expected_ended_grade_period_ids": [11],
        "expected_ended_contract_ids": [12, 13],
        "expected_new_certification_period_id": 20,
        "expected_new_grade_period_id": 21,
        "expected_new_contract_ids": [30, 31],
    }
    if _validate_http_apply_success_response(good, **expect_kw) is not None:
        _fail("W1D_R21_HTTP_MUTANT_GOOD_REJECTED")
    # Divergent but syntactically valid UUID vs audit.
    bad_exp = dict(expect_kw)
    bad_exp["expected_audit_request_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    if _validate_http_apply_success_response(good, **bad_exp) is None:
        _fail("W1D_R21_HTTP_MUTANT_DIVERGENT_UUID_ACCEPTED")
    # R22: noncanonical expected audit request_id must fail (no lower/coerce).
    noncanon_exp = dict(expect_kw)
    noncanon_exp["expected_audit_request_id"] = good_corr.upper()
    if _validate_http_apply_success_response(good, **noncanon_exp) is None:
        _fail("W1D_R22_HTTP_MUTANT_NONCANON_EXPECTED_ACCEPTED")
    # R22: audit request_id helper rejects uppercase/malformed/non-string.
    if _canonical_audit_request_id(good_corr.upper()) is not None:
        _fail("W1D_R22_AUDIT_REQ_ID_UPPER_ACCEPTED")
    if _canonical_audit_request_id("not-a-uuid") is not None:
        _fail("W1D_R22_AUDIT_REQ_ID_MALFORMED_ACCEPTED")
    if _canonical_audit_request_id(1) is not None:
        _fail("W1D_R22_AUDIT_REQ_ID_INT_ACCEPTED")
    if _canonical_audit_request_id(UUID(good_corr)) != good_corr:
        _fail("W1D_R22_AUDIT_REQ_ID_UUID_OBJECT_REJECTED")
    if _canonical_audit_request_id(good_corr) != good_corr:
        _fail("W1D_R22_AUDIT_REQ_ID_CANON_STR_REJECTED")
    upper_corr = good_corr.upper()
    mutants: list[tuple[object, str]] = [
        ({**good, "audit_correlation_id": upper_corr}, "uppercase_uuid"),
        ({**good, "audit_correlation_id": "not-a-uuid"}, "malformed_uuid"),
        ({k: v for k, v in good.items() if k != "audit_correlation_id"}, "missing_corr"),
        ({**good, "audit_correlation_id": UUID(good_corr)}, "uuid_object"),
        ({**good, "audit_correlation_id": 1}, "int_corr"),
        ({**good, "audit_correlation_id": True}, "bool_corr"),
        ({**good, "audit_correlation_id": None}, "none_corr"),
        ({k: v for k, v in good.items() if k != "recipient_id"}, "missing_key"),
        ({**good, "extra": 1}, "extra_key"),
        ({**good, "new_certification_period_id": "20"}, "string_id"),
        ({**good, "new_grade_period_id": True}, "bool_id"),
        ({**good, "new_certification_period_id": 0}, "zero_id"),
        ({**good, "new_grade_period_id": -1}, "neg_id"),
        ({**good, "new_contract_ids": 30}, "scalar_cids"),
        ({**good, "new_contract_ids": (30, 31)}, "tuple_cids"),
        ({**good, "new_contract_ids": ["30", 31]}, "str_member"),
        ({**good, "new_contract_ids": []}, "empty_cids"),
        ({**good, "new_contract_ids": [30, 30]}, "dup_cids"),
        # R22: each ended list / new ID differs with other valid positive ints.
        ({**good, "ended_certification_period_ids": [999]}, "wrong_ended_cert"),
        ({**good, "ended_grade_period_ids": [999]}, "wrong_ended_grade"),
        ({**good, "ended_contract_ids": [999, 13]}, "wrong_ended_contract"),
        ({**good, "ended_contract_ids": [13, 12]}, "wrong_ended_contract_order"),
        ({**good, "new_certification_period_id": 999}, "wrong_new_cert"),
        ({**good, "new_grade_period_id": 999}, "wrong_new_grade"),
        ({**good, "new_contract_ids": [99, 98]}, "wrong_new_cids"),
        ({**good, "new_contract_ids": [31, 30]}, "wrong_new_cids_order"),
        ({**good, "recipient_id": 2}, "wrong_recipient_id"),
        ({**good, "recipient_no": "000002"}, "wrong_recipient_no"),
        ({**good, "ended_certification_period_ids": [True]}, "bool_ended_member"),
        ({**good, "ended_contract_ids": ["12", 13]}, "str_ended_member"),
        ("not-dict", "container"),
    ]
    for payload, tag in mutants:
        if _validate_http_apply_success_response(payload, **expect_kw) is None:
            _fail(f"W1D_R21_HTTP_MUTANT_ACCEPTED:{tag}")


def _r19_all_pure_mutant_selfchecks() -> str:
    """Run every R19–R24 pure mutant selfcheck; return 'PASS' or raise via _fail."""
    _r19_winner_mutant_selfcheck()
    _r19_timestamp_mutant_selfcheck()
    _r19_open_range_mutant_selfcheck()
    _r19_audit_proj_mutant_selfcheck()
    _r20_pack_mutant_selfcheck()
    _r20_normalizer_coupling_selfcheck()
    _r21_http_apply_mutant_selfcheck()
    _r18_recipient_no_mutant_selfcheck()
    _r24_contract_response_mutant_selfcheck()
    _r24_pg05_audit_path_source_selfcheck()
    return "PASS"


def _assert_preview_hash_shape(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"W1D_TRN04_PREVIEW_HASH_TYPE: {label}")
    if len(value) != 64 or value != value.lower():
        _fail(f"W1D_TRN04_PREVIEW_HASH_SHAPE: {label}")
    if any(ch not in "0123456789abcdef" for ch in value):
        _fail(f"W1D_TRN04_PREVIEW_HASH_HEX: {label}")
    return value


def _normalize_utc_timestamp(value: Any, *, label: str) -> datetime:
    """Fail-closed normalizer: delegates to pure _try_normalize_utc_timestamp (R20)."""
    dt, err = _try_normalize_utc_timestamp(value)
    if err is None and dt is not None:
        return dt
    if err == "TIMESTAMP_NAIVE":
        _fail(f"W1D_HARNESS_TIMESTAMP_NAIVE: {label}")
    if err == "TIMESTAMP_EMPTY":
        _fail(f"W1D_HARNESS_TIMESTAMP_EMPTY: {label}")
    if err == "TIMESTAMP_PARSE":
        _fail(f"W1D_HARNESS_TIMESTAMP_PARSE: {label}")
    _fail(f"W1D_HARNESS_TIMESTAMP_TYPE: {label}:{type(value).__name__}")


def _capture_authorized_preview(preview: Any, *, label: str) -> str:
    """R10-02: exact named fields only — no preview_hash attribute fallback."""
    try:
        canonical = preview.canonical_hash
    except AttributeError:
        _fail(f"W1D_TRN_CANONICAL_HASH_ATTR_MISSING: {label}")
    auth = _assert_preview_hash_shape(canonical, label=label + ".canonical_hash")
    try:
        version = preview.serialization_version
    except AttributeError:
        version = None
    if version != "w1d-transition-v1":
        _fail(f"W1D_TRN_SERIALIZATION_VERSION: {label}:{version!r}")
    try:
        token = preview.preview_token
    except AttributeError:
        token = None
    if not token:
        _fail(f"W1D_TRN_PREVIEW_TOKEN_MISSING: {label}")
    return auth


def _canonical_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text_value = str(value)
    return text_value[:10] if len(text_value) >= 10 else text_value


def _canonical_transition_projection(
    connection,
    recipient_id: int,
    *,
    preview_hash: str,
    include_new_ids: bool,
    new_cert_id: int | None = None,
    new_grade_id: int | None = None,
    new_contract_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Persisted-row audit projection with sealed authorization preview_hash (R9-01).

    preview_hash is an explicit input — the exact token.preview_hash /
    preview.canonical_hash from the authorized pre-apply preview. This helper
    never invents a second post-state serializer under that name.
    Projection field schema matches plan § audit before_json/after_json
    (no invalidated_at_utc key).
    """
    auth_hash = _assert_preview_hash_shape(preview_hash, label="projection_input")
    try:
        cert_rows = (
            connection.execute(
                text(
                    """
                SELECT id, start_date, end_date, row_version, invalidated_at_utc
                FROM erp.recipient_certification_period
                WHERE recipient_id = :rid
                ORDER BY id
                """
                ),
                {"rid": recipient_id},
            )
            .mappings()
            .all()
        )
        grade_rows = (
            connection.execute(
                text(
                    """
                SELECT id, certification_period_id, grade_code, start_date, end_date,
                       row_version, invalidated_at_utc
                FROM erp.recipient_grade_period
                WHERE recipient_id = :rid
                ORDER BY id
                """
                ),
                {"rid": recipient_id},
            )
            .mappings()
            .all()
        )
        contract_rows = (
            connection.execute(
                text(
                    """
                SELECT c.id, st.code AS service_type_code, sg.code AS service_group_code,
                       c.start_date, c.end_date, c.row_version, c.invalidated_at_utc
                FROM erp.recipient_contract c
                JOIN erp.service_type st ON st.id = c.service_type_id
                LEFT JOIN erp.service_group sg ON sg.id = st.service_group_id
                WHERE c.recipient_id = :rid
                ORDER BY c.id
                """
                ),
                {"rid": recipient_id},
            )
            .mappings()
            .all()
        )
    except Exception as exc:
        _fail(f"W1D_HARNESS_PROJECTION_QUERY: {type(exc).__name__}")

    def period_list(rows: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {}
            for field in fields:
                value = row[field]
                if field.endswith("date"):
                    item[field] = _canonical_date(value)
                else:
                    item[field] = value
            out.append(item)
        return out

    # Active multiset: non-invalidated contracts only (invalidated_at_utc is
    # filter input, not a projection key — plan § schema).
    active_contracts = [r for r in contract_rows if r["invalidated_at_utc"] is None]
    multiset = sorted(str(r["service_type_code"]) for r in active_contracts)
    projection: dict[str, Any] = {
        "preview_hash": auth_hash,
        "certification_periods": period_list(
            cert_rows, ("id", "start_date", "end_date", "row_version")
        ),
        "grade_periods": period_list(
            grade_rows,
            (
                "id",
                "certification_period_id",
                "grade_code",
                "start_date",
                "end_date",
                "row_version",
            ),
        ),
        "contracts": period_list(
            contract_rows,
            (
                "id",
                "service_type_code",
                "service_group_code",
                "start_date",
                "end_date",
                "row_version",
            ),
        ),
        "service_multiset": multiset,
    }
    if include_new_ids:
        projection["new_ids"] = {
            "certification_period_id": new_cert_id,
            "grade_period_id": new_grade_id,
            "contract_ids": list(new_contract_ids or []),
        }
    return projection


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

    def worker(service_code: str) -> str:
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
        from app.domains.w1d import fault as w1d_fault  # type: ignore
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
    if getattr(created, "signer_name", "missing") is not None:
        _fail("W1D_SIG01_SIGNER_NOT_NULL_ON_EMPTY")
    if hasattr(created, "contract_no"):
        _fail("W1D_ABS08_CONTRACT_NO_ON_RESPONSE")

    with database_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT service_start_date, end_date, end_reason_text,
                           signer_name, signer_relationship_text, signer_phone
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

    def create(service_code: str, start: date, end: date | None):
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


def test_w1d_pg_04_signer_snapshot_independence(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """W1-SIG-01 / M3: empty, partial, full; mutate existing guardian+payer."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    with session_factory() as database_session:
        service = service_cls(database_session)
        empty = service.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2027, 1, 1),
                end_date=date(2027, 1, 31),
            ),
            account,
        )
        partial = service.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_BATH,
                start_date=date(2027, 1, 1),
                end_date=date(2027, 1, 31),
                signer_name="TEST_W1D_PARTIAL_SIGNER",
            ),
            account,
        )
        full = service.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_TEMP,
                start_date=date(2027, 3, 1),
                end_date=date(2027, 3, 31),
                signer_name="TEST_W1D_SIGNER_CANARY",
                signer_relationship_text="TEST_REL",
                signer_phone="TEST_W1D_SIGNER_PHONE",
            ),
            account,
        )
        database_session.commit()
        empty_id, partial_id, full_id = empty.id, partial.id, full.id

    # Create guardian + payer then mutate the existing rows (not only insert).
    with database_engine.connect() as connection:
        guardian_id = connection.execute(
            text(
                """
                INSERT INTO erp.recipient_guardian (
                    recipient_id, name, phone, address, relationship_text,
                    created_by_account_id, updated_by_account_id, row_version
                ) VALUES (
                    :rid, 'TEST_W1D_GUARDIAN_NAME', '010-1111-1111', 'ADDR1', 'REL1',
                    :aid, :aid, 1
                ) RETURNING id
                """
            ),
            {"rid": case.recipient_id, "aid": case.account_id},
        ).scalar_one()
        payer_id = connection.execute(
            text(
                """
                INSERT INTO erp.recipient_payer_snapshot (
                    recipient_id, name, phone, address, relationship_text,
                    start_date, end_date,
                    created_by_account_id, updated_by_account_id, row_version
                ) VALUES (
                    :rid, 'TEST_W1D_PAYER_NAME', '010-2222-2222', 'PADDR', 'PREL',
                    DATE '2020-01-01', NULL,
                    :aid, :aid, 1
                ) RETURNING id
                """
            ),
            {"rid": case.recipient_id, "aid": case.account_id},
        ).scalar_one()
        connection.execute(
            text(
                """
                UPDATE erp.recipient_guardian
                SET name = 'TEST_W1D_GUARDIAN_MUTATED',
                    phone = '010-9999-9999',
                    address = 'MUTATED_ADDR',
                    relationship_text = 'MUTATED_REL',
                    row_version = row_version + 1
                WHERE id = :id
                """
            ),
            {"id": guardian_id},
        )
        connection.execute(
            text(
                """
                UPDATE erp.recipient_payer_snapshot
                SET name = 'TEST_W1D_PAYER_MUTATED',
                    phone = '010-8888-8888',
                    address = 'MUTATED_PADDR',
                    relationship_text = 'MUTATED_PREL',
                    row_version = row_version + 1
                WHERE id = :id
                """
            ),
            {"id": payer_id},
        )
        connection.commit()

    with database_engine.connect() as connection:
        empty_row = (
            connection.execute(
                text(
                    """
                    SELECT signer_name, signer_relationship_text, signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                ),
                {"id": empty_id},
            )
            .mappings()
            .one()
        )
        if any(empty_row[k] is not None for k in empty_row):
            _fail("W1D_SIG01_EMPTY_SNAPSHOT_NOT_PRESERVED")
        partial_row = (
            connection.execute(
                text(
                    """
                    SELECT signer_name, signer_relationship_text, signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                ),
                {"id": partial_id},
            )
            .mappings()
            .one()
        )
        if partial_row["signer_name"] != "TEST_W1D_PARTIAL_SIGNER":
            _fail("W1D_SIG01_PARTIAL_SNAPSHOT_MUTATED")
        if partial_row["signer_relationship_text"] is not None:
            _fail("W1D_SIG01_PARTIAL_RELATIONSHIP_UNEXPECTED")
        if partial_row["signer_phone"] is not None:
            _fail("W1D_SIG01_PARTIAL_PHONE_UNEXPECTED")
        full_row = (
            connection.execute(
                text(
                    """
                    SELECT signer_name, signer_relationship_text, signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                ),
                {"id": full_id},
            )
            .mappings()
            .one()
        )
        if full_row["signer_name"] != "TEST_W1D_SIGNER_CANARY":
            _fail("W1D_SIG01_FULL_SNAPSHOT_MUTATED_AFTER_GUARDIAN_PAYER_UPDATE")
        if full_row["signer_relationship_text"] != "TEST_REL":
            _fail("W1D_SIG01_FULL_RELATIONSHIP_MUTATED")
        if full_row["signer_phone"] != "TEST_W1D_SIGNER_PHONE":
            _fail("W1D_SIG01_FULL_PHONE_MUTATED")
        # Empty/partial/full exact triples after guardian/payer mutation (M06).
        if (
            empty_row["signer_name"],
            empty_row["signer_relationship_text"],
            empty_row["signer_phone"],
        ) != (None, None, None):
            _fail("W1D_SIG01_EMPTY_TUPLE_DRIFT")
        if (
            partial_row["signer_name"],
            partial_row["signer_relationship_text"],
            partial_row["signer_phone"],
        ) != ("TEST_W1D_PARTIAL_SIGNER", None, None):
            _fail("W1D_SIG01_PARTIAL_TUPLE_DRIFT")
        if (
            full_row["signer_name"],
            full_row["signer_relationship_text"],
            full_row["signer_phone"],
        ) != ("TEST_W1D_SIGNER_CANARY", "TEST_REL", "TEST_W1D_SIGNER_PHONE"):
            _fail("W1D_SIG01_FULL_TUPLE_DRIFT")


def test_w1d_pg_05_transition_preview_apply_stale_multiset_fault_audit(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """B1/B2/M2/TRN: grade-first end, mismatch!=stale, single non-PII audit, fault."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
    except Exception:
        _fail("W1D_HARNESS_W1C_DEPENDENCY_MISSING")

    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1d = service_cls(database_session)
        cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
        w1c.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(certification_number=cert_number),
            account,
        )
        cert = w1c.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
            ),
            account,
        )
        grade = w1c.create_grade_period(
            case.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=cert.id,
                grade_code="3",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
            ),
            account,
        )
        contract = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2026, 1, 1),
                signer_name="TEST_W1D_SIGNER_CANARY",
                signer_phone="TEST_W1D_SIGNER_PHONE",
            ),
            account,
        )
        # Second LTC contract so ALL_MISSING vs PARTIAL are distinct (R4-03).
        contract_b = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_BATH,
                start_date=date(2026, 1, 1),
            ),
            account,
        )
        database_session.commit()
        cert_id, grade_id, contract_id = cert.id, grade.id, contract.id
        contract_b_id = contract_b.id

    with database_engine.connect() as connection:
        before_hash = _full_ledger_fingerprint(connection, case.recipient_id)

    proposed_end = date(2026, 6, 30)
    replacements = _replacement_items(
        schemas,
        contract_id,
        date(2026, 7, 1),
        signer_name="TEST_W1D_SIGNER_CANARY",
        signer_phone="TEST_W1D_SIGNER_PHONE",
        end_reason_text="TEST_W1D_END_REASON_PII",
    ) + _replacement_items(
        schemas,
        contract_b_id,
        date(2026, 7, 1),
        service_type_code=SERVICE_HOME_BATH,
    )
    preview_request = schemas.CertificationTransitionPreviewRequest(
        new_start_date=date(2026, 7, 1),
        new_end_date=date(2027, 6, 30),
        new_grade_code="4",
        new_grade_start_date=date(2026, 7, 1),
        new_grade_end_date=date(2027, 6, 30),
        replacement_contracts=replacements,
    )

    with session_factory() as database_session:
        service = service_cls(database_session)
        preview = service.preview_certification_transition(
            case.recipient_id, preview_request, account
        )
        database_session.commit()

    if getattr(preview, "proposed_end_date", None) != proposed_end:
        _fail(
            "W1D_TRN01_PROPOSED_END_DATE_MISMATCH: "
            + str(getattr(preview, "proposed_end_date", None))
        )
    # R10-02: exact named preview fields (canonical_hash only; no fallback).
    auth_preview_hash = _capture_authorized_preview(preview, label="trn01_preview")
    # Seeded two-contract success: exact affected IDs + sorted multiset.
    affected_certs = list(getattr(preview, "affected_certification_period_ids", None) or [])
    affected_grades = list(getattr(preview, "affected_grade_period_ids", None) or [])
    affected_contracts = list(getattr(preview, "affected_contract_ids", None) or [])
    if [int(x) for x in affected_certs] != [int(cert_id)]:
        _fail("W1D_TRN01_AFFECTED_CERT_IDS: " + repr(affected_certs))
    if [int(x) for x in affected_grades] != [int(grade_id)]:
        _fail("W1D_TRN01_AFFECTED_GRADE_IDS: " + repr(affected_grades))
    if sorted(int(x) for x in affected_contracts) != sorted([int(contract_id), int(contract_b_id)]):
        _fail("W1D_TRN01_AFFECTED_CONTRACT_IDS: " + repr(affected_contracts))
    multiset = list(getattr(preview, "service_multiset", None) or [])
    if sorted(str(x) for x in multiset) != sorted([SERVICE_HOME_CARE, SERVICE_HOME_BATH]):
        _fail("W1D_TRN01_SERVICE_MULTISET: " + repr(multiset))
    if getattr(preview, "replacement_preview", None) is None:
        _fail("W1D_TRN01_REPLACEMENT_PREVIEW_MISSING")
    del auth_preview_hash  # used only for shape/version seal above
    with database_engine.connect() as connection:
        if _full_ledger_fingerprint(connection, case.recipient_id) != before_hash:
            _fail("W1D_TRN01_PREVIEW_WROTE_ROWS")

    # Unconfirmed apply — R11 H01: full ledger + complete audit write-zero.
    with database_engine.connect() as connection:
        unc_fp, unc_audit = _write_zero_pair(connection, case.recipient_id)
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.apply_certification_transition(
                case.recipient_id,
                schemas.CertificationTransitionApplyRequest(
                    preview_token=preview.preview_token,
                    confirmed=False,
                    replacement_contracts=replacements,
                ),
                account,
            )
            database_session.commit()
            _fail("W1D_TRN01_UNCONFIRMED_APPLY_ACCEPTED")
        except Exception as exc:
            database_session.rollback()
            if _error_code(exc) != "CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED":
                _fail("W1D_TRN01_CONFIRMATION_CODE_MISMATCH: " + _error_code(exc))
    with database_engine.connect() as connection:
        _assert_write_zero_pair(
            connection,
            case.recipient_id,
            unc_fp,
            unc_audit,
            label="W1D_TRN01_UNCONFIRMED",
        )

    # J-H04: full replacement mismatch matrix; each exact MISMATCH + write-zero.
    def assert_mismatch(label: str, bad_reps: Any) -> None:
        with database_engine.connect() as connection:
            fp0, audit0 = _write_zero_pair(connection, case.recipient_id)
        with session_factory() as database_session:
            service = service_cls(database_session)
            try:
                service.apply_certification_transition(
                    case.recipient_id,
                    schemas.CertificationTransitionApplyRequest(
                        preview_token=preview.preview_token,
                        confirmed=True,
                        replacement_contracts=bad_reps,
                    ),
                    account,
                )
                database_session.commit()
                _fail(label + "_MISMATCH_ACCEPTED")
            except Exception as exc:
                database_session.rollback()
                code = _error_code(exc)
                if code == "CERTIFICATION_TRANSITION_STALE":
                    _fail(label + "_CLASSIFIED_AS_STALE")
                if code == "CERTIFICATION_TRANSITION_TOKEN_INVALID":
                    _fail(label + "_CLASSIFIED_AS_TOKEN_INVALID")
                if code != "CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH":
                    _fail(label + "_CODE: " + code)
        with database_engine.connect() as connection:
            _assert_write_zero_pair(connection, case.recipient_id, fp0, audit0, label=label)

    # R4-03: ALL_MISSING vs PARTIAL must differ (two bound contracts in preview).
    assert_mismatch("W1D_TRN02_ALL_MISSING", [])
    partial_only_first = _replacement_items(
        schemas,
        contract_id,
        date(2026, 7, 1),
        signer_name="TEST_W1D_SIGNER_CANARY",
        signer_phone="TEST_W1D_SIGNER_PHONE",
        end_reason_text="TEST_W1D_END_REASON_PII",
    )
    assert_mismatch("W1D_TRN02_PARTIAL", partial_only_first)
    extra = list(replacements) + _replacement_items(schemas, contract_id + 99999, date(2026, 7, 1))
    assert_mismatch("W1D_TRN02_ADDITIONAL", extra)
    dup = list(replacements) + list(replacements)
    assert_mismatch("W1D_TRN02_DUPLICATE", dup)
    wrong_svc = _replacement_items(
        schemas,
        contract_id,
        date(2026, 7, 1),
        service_type_code=SERVICE_HOME_BATH,
        signer_name="TEST_W1D_SIGNER_CANARY",
        signer_phone="TEST_W1D_SIGNER_PHONE",
        end_reason_text="TEST_W1D_END_REASON_PII",
    ) + _replacement_items(
        schemas, contract_b_id, date(2026, 7, 1), service_type_code=SERVICE_HOME_BATH
    )
    assert_mismatch("W1D_TRN02_WRONG_SERVICE", wrong_svc)
    wrong_id = _replacement_items(
        schemas, contract_id + 777, date(2026, 7, 1)
    ) + _replacement_items(
        schemas, contract_b_id, date(2026, 7, 1), service_type_code=SERVICE_HOME_BATH
    )
    assert_mismatch("W1D_TRN02_WRONG_ENDED_ID", wrong_id)
    for field, value in (
        ("signer_name", "MUTATED_SIGNER"),
        ("signer_phone", "MUTATED_PHONE"),
        ("signer_relationship_text", "MUTATED_REL"),
        ("end_reason_text", "MUTATED_REASON"),
        ("service_start_date", date(2026, 8, 1)),
        ("end_date", date(2026, 12, 31)),
        ("start_date", date(2026, 8, 1)),
    ):
        extra: dict[str, Any] = {
            "signer_name": "TEST_W1D_SIGNER_CANARY",
            "signer_phone": "TEST_W1D_SIGNER_PHONE",
            "end_reason_text": "TEST_W1D_END_REASON_PII",
        }
        extra[field] = value
        first = _replacement_items(
            schemas,
            contract_id,
            date(2026, 7, 1),
            **extra,
        )
        second = _replacement_items(
            schemas, contract_b_id, date(2026, 7, 1), service_type_code=SERVICE_HOME_BATH
        )
        assert_mismatch("W1D_TRN02_FIELD_" + field.upper(), first + second)

    # Grade-stale path: intentional setup first, then pre-reject write-zero (R11 H01).
    with session_factory() as database_session:
        database_session.execute(
            text(
                """
                UPDATE erp.recipient_grade_period
                SET grade_code = '2',
                    row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"id": grade_id},
        )
        database_session.commit()
    with database_engine.connect() as connection:
        grade_stale_fp, grade_stale_audit = _write_zero_pair(connection, case.recipient_id)
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.apply_certification_transition(
                case.recipient_id,
                schemas.CertificationTransitionApplyRequest(
                    preview_token=preview.preview_token,
                    confirmed=True,
                    replacement_contracts=replacements,
                ),
                account,
            )
            database_session.commit()
            _fail("W1D_TRN03_STALE_APPLY_ACCEPTED")
        except Exception as exc:
            database_session.rollback()
            if _error_code(exc) != "CERTIFICATION_TRANSITION_STALE":
                _fail("W1D_TRN03_STALE_CODE_MISMATCH: " + _error_code(exc))
    with database_engine.connect() as connection:
        _assert_write_zero_pair(
            connection,
            case.recipient_id,
            grade_stale_fp,
            grade_stale_audit,
            label="W1D_TRN03_GRADE_STALE",
        )

    # Restore grade for success path.
    with session_factory() as database_session:
        database_session.execute(
            text(
                """
                UPDATE erp.recipient_grade_period
                SET grade_code = '3',
                    row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"id": grade_id},
        )
        database_session.commit()

    # R10-02: authorized canonical_hash only + full audit row set before apply.
    with session_factory() as database_session:
        service = service_cls(database_session)
        preview2 = service.preview_certification_transition(
            case.recipient_id, preview_request, account
        )
        authorized_preview_hash = _capture_authorized_preview(
            preview2, label="trn04_pre_apply_preview"
        )
        with database_engine.connect() as connection:
            audit_rows_before = _all_audit_rows(connection)
            expected_before_proj = _canonical_transition_projection(
                connection,
                case.recipient_id,
                preview_hash=authorized_preview_hash,
                include_new_ids=False,
            )
        # R6-03 / R10-03: clock window starts immediately before apply.
        apply_window_start = database_session.execute(text("SELECT clock_timestamp()")).scalar_one()
        applied = service.apply_certification_transition(
            case.recipient_id,
            schemas.CertificationTransitionApplyRequest(
                preview_token=preview2.preview_token,
                confirmed=True,
                replacement_contracts=replacements,
            ),
            account,
        )
        database_session.commit()
        correlation = getattr(applied, "audit_correlation_id", None)
        resp_new_cert = getattr(applied, "new_certification_period_id", None)
        resp_new_grade = getattr(applied, "new_grade_period_id", None)
        resp_new_contracts = getattr(applied, "new_contract_ids", None)
        apply_window_end = database_session.execute(text("SELECT clock_timestamp()")).scalar_one()

    # B1 / R6-04: exact end dates + exact success rows for two replacements.
    with database_engine.connect() as connection:
        grade_end = connection.execute(
            text("SELECT end_date FROM erp.recipient_grade_period WHERE id = :id"),
            {"id": grade_id},
        ).scalar_one()
        cert_end = connection.execute(
            text("SELECT end_date FROM erp.recipient_certification_period WHERE id = :id"),
            {"id": cert_id},
        ).scalar_one()
        if grade_end != proposed_end:
            _fail("W1D_TRN04_GRADE_END_NOT_PROPOSED: " + str(grade_end))
        if cert_end != proposed_end:
            _fail("W1D_TRN04_CERT_END_NOT_PROPOSED: " + str(cert_end))
        for original_id, label in (
            (contract_id, "CONTRACT_A"),
            (contract_b_id, "CONTRACT_B"),
        ):
            original_end = connection.execute(
                text("SELECT end_date FROM erp.recipient_contract WHERE id = :id"),
                {"id": original_id},
            ).scalar_one()
            if original_end != proposed_end:
                _fail(f"W1D_TRN04_{label}_NOT_ENDED_AT_PROPOSED: " + str(original_end))

        # R24: strict response ID types (no int() coercion on apply response).
        if type(resp_new_contracts) is not list:
            _fail("W1D_TRN04_RESPONSE_CONTRACT_IDS_MISSING")
        if any(type(x) is not int or x <= 0 for x in resp_new_contracts):
            _fail("W1D_TRN04_RESPONSE_CONTRACT_IDS_TYPE")
        resp_contract_ids = list(resp_new_contracts)
        if len(resp_contract_ids) != 2 or len(set(resp_contract_ids)) != 2:
            _fail("W1D_TRN04_RESPONSE_CONTRACT_IDS_SHAPE: " + repr(resp_contract_ids))
        if type(resp_new_cert) is not int or resp_new_cert <= 0:
            _fail("W1D_TRN04_RESPONSE_NEW_CERT_ID_MISSING")
        if type(resp_new_grade) is not int or resp_new_grade <= 0:
            _fail("W1D_TRN04_RESPONSE_NEW_GRADE_ID_MISSING")

        # Exactly one new certification for recipient with exact dates + response ID.
        new_cert_rows = (
            connection.execute(
                text(
                    """
                SELECT id, start_date, end_date, invalidated_at_utc
                FROM erp.recipient_certification_period
                WHERE recipient_id = :rid
                  AND start_date = DATE '2026-07-01'
                  AND invalidated_at_utc IS NULL
                ORDER BY id
                """
                ),
                {"rid": case.recipient_id},
            )
            .mappings()
            .all()
        )
        if len(new_cert_rows) != 1:
            _fail("W1D_TRN04_NEW_CERT_COUNT: " + str(len(new_cert_rows)))
        if new_cert_rows[0]["id"] != resp_new_cert:
            _fail("W1D_TRN04_NEW_CERT_ID_MISMATCH")
        if new_cert_rows[0]["end_date"] != date(2027, 6, 30):
            _fail("W1D_TRN04_NEW_CERT_END_MISMATCH: " + str(new_cert_rows[0]["end_date"]))

        # Exactly one new grade under that certification.
        new_grade_rows = (
            connection.execute(
                text(
                    """
                SELECT id, certification_period_id, grade_code, start_date, end_date,
                       invalidated_at_utc
                FROM erp.recipient_grade_period
                WHERE recipient_id = :rid
                  AND start_date = DATE '2026-07-01'
                  AND invalidated_at_utc IS NULL
                ORDER BY id
                """
                ),
                {"rid": case.recipient_id},
            )
            .mappings()
            .all()
        )
        if len(new_grade_rows) != 1:
            _fail("W1D_TRN04_NEW_GRADE_COUNT: " + str(len(new_grade_rows)))
        if new_grade_rows[0]["id"] != resp_new_grade:
            _fail("W1D_TRN04_NEW_GRADE_ID_MISMATCH")
        if new_grade_rows[0]["certification_period_id"] != resp_new_cert:
            _fail("W1D_TRN04_NEW_GRADE_PARENT_MISMATCH")
        if str(new_grade_rows[0]["grade_code"]) != "4":
            _fail("W1D_TRN04_NEW_GRADE_CODE_MISMATCH")
        if new_grade_rows[0]["end_date"] != date(2027, 6, 30):
            _fail("W1D_TRN04_NEW_GRADE_END_MISMATCH: " + str(new_grade_rows[0]["end_date"]))

        # Exactly two new contracts by response IDs: HOME_CARE + HOME_BATH multiset.
        new_ctr_rows = (
            connection.execute(
                text(
                    """
                SELECT c.id, c.recipient_id, c.start_date, c.end_date,
                       c.invalidated_at_utc, st.code AS service_code
                FROM erp.recipient_contract c
                JOIN erp.service_type st ON st.id = c.service_type_id
                WHERE c.id IN (:id0, :id1)
                ORDER BY c.id
                """
                ),
                {"id0": resp_contract_ids[0], "id1": resp_contract_ids[1]},
            )
            .mappings()
            .all()
        )
        if len(new_ctr_rows) != 2:
            _fail("W1D_TRN04_NEW_CONTRACT_ROW_COUNT: " + str(len(new_ctr_rows)))
        found_ids = {int(r["id"]) for r in new_ctr_rows}
        if found_ids != set(resp_contract_ids):
            _fail("W1D_TRN04_NEW_CONTRACT_ID_SET_MISMATCH")
        service_codes = sorted(str(r["service_code"]) for r in new_ctr_rows)
        if service_codes != sorted([SERVICE_HOME_CARE, SERVICE_HOME_BATH]):
            _fail("W1D_TRN04_NEW_CONTRACT_SERVICE_MULTISET: " + ",".join(service_codes))
        for crow in new_ctr_rows:
            if int(crow["recipient_id"]) != case.recipient_id:
                _fail("W1D_TRN04_NEW_CONTRACT_RECIPIENT_MISMATCH")
            if crow["start_date"] != date(2026, 7, 1):
                _fail("W1D_TRN04_NEW_CONTRACT_START_MISMATCH")
            if crow["end_date"] is not None:
                _fail("W1D_TRN04_NEW_CONTRACT_END_NOT_NULL: " + str(crow["end_date"]))
            if crow["invalidated_at_utc"] is not None:
                _fail("W1D_TRN04_NEW_CONTRACT_INVALIDATED")
        # No extra open contracts at new start beyond the two response IDs.
        extra_new = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.recipient_contract
                WHERE recipient_id = :rid
                  AND start_date = DATE '2026-07-01'
                  AND invalidated_at_utc IS NULL
                  AND id NOT IN (:id0, :id1)
                """
            ),
            {
                "rid": case.recipient_id,
                "id0": resp_contract_ids[0],
                "id1": resp_contract_ids[1],
            },
        ).scalar_one()
        if int(extra_new) != 0:
            _fail("W1D_TRN04_EXTRA_NEW_CONTRACTS: " + str(extra_new))

        # R9-02: entire audit_event row set is append-only (no MAX(id) window).
        audit_rows_after = _all_audit_rows(connection)
        if len(audit_rows_after) != len(audit_rows_before) + 1:
            _fail(
                "W1D_TRN04_AUDIT_APPEND_LEN: "
                f"before={len(audit_rows_before)} after={len(audit_rows_after)}"
            )
        before_canon = _canonical_audit_rows_json(audit_rows_before)
        prefix_canon = _canonical_audit_rows_json(audit_rows_after[: len(audit_rows_before)])
        if before_canon != prefix_canon:
            _fail("W1D_TRN04_AUDIT_PREEXISTING_MUTATED_OR_REORDERED")
        row = audit_rows_after[-1]
        if row.get("action_code") != "CERTIFICATION_TRANSITION_APPLY":
            _fail("W1D_TRN04_AUDIT_APPENDED_ACTION: " + str(row.get("action_code")))
        if row.get("entity_type") != "RECIPIENT":
            _fail("W1D_TRN04_AUDIT_APPENDED_ENTITY_TYPE: " + str(row.get("entity_type")))
        if int(row.get("entity_pk", -1)) != case.recipient_id:
            _fail("W1D_TRN04_AUDIT_ENTITY_PK")
        # Exactly one CERTIFICATION_TRANSITION_APPLY for this recipient in delta.
        apply_delta = [
            r
            for r in audit_rows_after[len(audit_rows_before) :]
            if r.get("action_code") == "CERTIFICATION_TRANSITION_APPLY"
        ]
        if len(apply_delta) != 1:
            _fail("W1D_TRN04_AUDIT_EVENT_COUNT: " + str(len(apply_delta)))
        blob = json.dumps(
            {"before": row.get("before_json"), "after": row.get("after_json")},
            ensure_ascii=False,
        )
        for canary in PII_CANARIES:
            if canary in blob:
                _fail("W1D_TRN04_AUDIT_PII_CANARY: " + canary)
        # R24: canonical request_id (UUID object via str(uuid) or already-canonical
        # lowercase string only). No str()/lower() coerce on noncanonical forms.
        corr_canon = _canonical_audit_request_id(correlation)
        if corr_canon is None:
            _fail("W1D_TRN04_AUDIT_CORRELATION_MISSING")
        req_canon = _canonical_audit_request_id(row.get("request_id"))
        if req_canon is None or req_canon != corr_canon:
            _fail("W1D_TRN04_AUDIT_REQUEST_ID_MISMATCH")
        if row.get("actor_account_id") != case.account_id:
            _fail("W1D_TRN04_AUDIT_CONFIRMER_MISMATCH")
        if row.get("actor_kind") != "USER":
            _fail("W1D_TRN04_AUDIT_ACTOR_KIND")
        if row.get("reason_code") != "USER_CONFIRMED_TRANSITION":
            _fail("W1D_TRN04_AUDIT_REASON_CODE")
        if row.get("created_from") != "API":
            _fail("W1D_TRN04_AUDIT_CREATED_FROM")
        if row.get("occurred_at_utc") is None:
            _fail("W1D_TRN04_AUDIT_TIMESTAMP_MISSING")
        # R10-03: exact inclusive DB clock window after fail-closed normalization.
        occurred_utc = _normalize_utc_timestamp(
            row["occurred_at_utc"], label="audit.occurred_at_utc"
        )
        window_start_utc = _normalize_utc_timestamp(apply_window_start, label="apply_window_start")
        window_end_utc = _normalize_utc_timestamp(apply_window_end, label="apply_window_end")
        if not (window_start_utc <= occurred_utc <= window_end_utc):
            _fail(
                "W1D_TRN04_AUDIT_TIMESTAMP_OUT_OF_WINDOW: "
                + f"{occurred_utc.isoformat()} not in "
                + f"[{window_start_utc.isoformat()}, {window_end_utc.isoformat()}]"
            )
        # R24/Joseph R8: shared exact audit projection + JSON-domain predicate.
        # No int() on new_ids; no json.dumps default-str projection compare.
        expected_after = _canonical_transition_projection(
            connection,
            case.recipient_id,
            preview_hash=authorized_preview_hash,
            include_new_ids=True,
            new_cert_id=resp_new_cert,
            new_grade_id=resp_new_grade,
            new_contract_ids=list(resp_contract_ids),
        )
        b_err = _validate_exact_audit_projection(
            row.get("before_json"),
            expected_before_proj,
            authorized_preview_hash=authorized_preview_hash,
            side="before",
        )
        if b_err is not None:
            _fail("W1D_TRN04_" + b_err)
        a_err = _validate_exact_audit_projection(
            row.get("after_json"),
            expected_after,
            authorized_preview_hash=authorized_preview_hash,
            side="after",
        )
        if a_err is not None:
            _fail("W1D_TRN04_" + a_err)
        # Explicit new_ids exact types/order/values vs apply response (no int()).
        after_proj, after_dec_err = _proj_decode(row.get("after_json"))
        if after_dec_err is not None or after_proj is None:
            _fail("W1D_TRN04_AFTER_JSON_DECODE")
        new_ids = after_proj.get("new_ids")
        if type(new_ids) is not dict:
            _fail("W1D_TRN04_AUDIT_AFTER_NEW_IDS_TYPE")
        if set(new_ids.keys()) != {
            "certification_period_id",
            "grade_period_id",
            "contract_ids",
        }:
            _fail("W1D_TRN04_AUDIT_NEW_IDS_KEYSET")
        if (
            type(new_ids.get("certification_period_id")) is not int
            or new_ids["certification_period_id"] != resp_new_cert
        ):
            _fail("W1D_TRN04_AUDIT_NEW_CERT_ID_MISMATCH")
        if (
            type(new_ids.get("grade_period_id")) is not int
            or new_ids["grade_period_id"] != resp_new_grade
        ):
            _fail("W1D_TRN04_AUDIT_NEW_GRADE_ID_MISMATCH")
        audit_contract_ids = new_ids.get("contract_ids")
        if type(audit_contract_ids) is not list:
            _fail("W1D_TRN04_AUDIT_CONTRACT_IDS_TYPE")
        if any(type(x) is not int or x <= 0 for x in audit_contract_ids):
            _fail("W1D_TRN04_AUDIT_CONTRACT_IDS_MEMBER")
        if audit_contract_ids != resp_contract_ids:
            _fail(
                "W1D_TRN04_AUDIT_CONTRACT_IDS_ORDER_MISMATCH: "
                + f"audit={audit_contract_ids!r} resp={resp_contract_ids!r}"
            )
        # Plan schema: no invalidated_at_utc inside period objects (fail-closed).
        for side_name, proj_obj in (
            ("before", expected_before_proj),
            ("after", after_proj),
        ):
            for list_key in ("certification_periods", "grade_periods", "contracts"):
                for item in proj_obj.get(list_key) or []:
                    if type(item) is dict and "invalidated_at_utc" in item:
                        _fail(
                            "W1D_TRN04_AUDIT_PROJECTION_FORBIDDEN_KEY: "
                            + side_name
                            + "."
                            + list_key
                            + ".invalidated_at_utc"
                        )

    # Fault after_end_grade (B1 order) full rollback.
    case3 = _seed_case(session_factory)
    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1d = service_cls(database_session)
        cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
        w1c.create_identity(
            case3.recipient_id,
            CertificationIdentityCreateRequest(certification_number=cert_number),
            account,
        )
        cert = w1c.create_certification_period(
            case3.recipient_id,
            CertificationPeriodCreateRequest(
                start_date=date(2028, 1, 1),
                end_date=date(2028, 12, 31),
            ),
            account,
        )
        w1c.create_grade_period(
            case3.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=cert.id,
                grade_code="2",
                start_date=date(2028, 1, 1),
                end_date=date(2028, 12, 31),
            ),
            account,
        )
        contract = w1d.create_contract(
            case3.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2028, 1, 1),
            ),
            account,
        )
        database_session.commit()
        c_id = contract.id

    try:
        from app.domains.w1d import fault as w1d_fault  # type: ignore

        set_fault = getattr(w1d_fault, "set_fault_point", None) or w1d_fault.install
    except Exception:
        _fail("W1D_FAULT_SEAM_MISSING: transition fault")

    rep = _replacement_items(schemas, c_id, date(2028, 7, 1))
    req = schemas.CertificationTransitionPreviewRequest(
        new_start_date=date(2028, 7, 1),
        new_end_date=date(2029, 6, 30),
        new_grade_code="3",
        new_grade_start_date=date(2028, 7, 1),
        new_grade_end_date=date(2029, 6, 30),
        replacement_contracts=rep,
    )

    def fp(rid: int) -> str:
        with database_engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT 'c', id, row_version, end_date::text
                    FROM erp.recipient_certification_period WHERE recipient_id = :rid
                    UNION ALL
                    SELECT 'g', id, row_version, end_date::text
                    FROM erp.recipient_grade_period WHERE recipient_id = :rid
                    UNION ALL
                    SELECT 't', id, row_version, end_date::text
                    FROM erp.recipient_contract WHERE recipient_id = :rid
                    ORDER BY 1, 2
                    """
                ),
                {"rid": rid},
            ).all()
            return hashlib.sha256(str(rows).encode()).hexdigest()

    with database_engine.connect() as connection:
        before_full = _full_ledger_fingerprint(connection, case3.recipient_id)
    before_fp = fp(case3.recipient_id)
    set_fault("after_end_grade")
    try:
        with session_factory() as database_session:
            service = service_cls(database_session)
            preview3 = service.preview_certification_transition(case3.recipient_id, req, account)
            try:
                service.apply_certification_transition(
                    case3.recipient_id,
                    schemas.CertificationTransitionApplyRequest(
                        preview_token=preview3.preview_token,
                        confirmed=True,
                        replacement_contracts=rep,
                    ),
                    account,
                )
                database_session.commit()
                _fail("W1D_TRN04_FAULT_DID_NOT_RAISE")
            except Exception as exc:
                database_session.rollback()
                # R4-04: exact seam marker required — reject unrelated exceptions.
                text_exc = f"{type(exc).__name__}:{exc}:{getattr(exc, 'code', '')}"
                if "W1D_FAULT:after_end_grade" not in text_exc:
                    _fail("W1D_TRN04_FAULT_after_end_grade_WRONG_EXCEPTION: " + text_exc[:200])
    finally:
        set_fault(None)
    if fp(case3.recipient_id) != before_fp:
        _fail("W1D_TRN04_FAULT_PARTIAL_SUCCESS")
    with database_engine.connect() as connection:
        if _full_ledger_fingerprint(connection, case3.recipient_id) != before_full:
            _fail("W1D_TRN04_FAULT_after_end_grade_FINGERPRINT_CHANGED")
        audit_delta = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.audit_event
                WHERE action_code = 'CERTIFICATION_TRANSITION_APPLY'
                  AND entity_pk = :rid
                """
            ),
            {"rid": case3.recipient_id},
        ).scalar_one()
        if int(audit_delta) != 0:
            _fail("W1D_TRN04_FAULT_after_end_grade_AUDIT_DELTA")


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


def test_w1d_pg_07_token_tamper_expiry_replay_preview_required(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """H1: tamper, injectable expiry, cross-recipient replay, preview-required; write 0."""
    _require_w1d_catalog(database_engine)
    case_a = _seed_case(session_factory)
    case_b = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case_a)

    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
    except Exception:
        _fail("W1D_HARNESS_W1C_DEPENDENCY_MISSING")

    def seed_transition(case: W1DCase) -> tuple[int, Any]:
        with session_factory() as database_session:
            w1c = W1CService(database_session)
            w1d = service_cls(database_session)
            cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
            w1c.create_identity(
                case.recipient_id,
                CertificationIdentityCreateRequest(certification_number=cert_number),
                account,
            )
            cert = w1c.create_certification_period(
                case.recipient_id,
                CertificationPeriodCreateRequest(
                    start_date=date(2031, 1, 1),
                    end_date=date(2031, 12, 31),
                ),
                account,
            )
            w1c.create_grade_period(
                case.recipient_id,
                GradePeriodCreateRequest(
                    certification_period_id=cert.id,
                    grade_code="1",
                    start_date=date(2031, 1, 1),
                    end_date=date(2031, 12, 31),
                ),
                account,
            )
            contract = w1d.create_contract(
                case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2031, 1, 1),
                ),
                account,
            )
            database_session.commit()
            return contract.id, None

    contract_a, _ = seed_transition(case_a)
    seed_transition(case_b)
    rep = _replacement_items(schemas, contract_a, date(2031, 7, 1))
    preview_req = schemas.CertificationTransitionPreviewRequest(
        new_start_date=date(2031, 7, 1),
        new_end_date=date(2032, 6, 30),
        new_grade_code="2",
        new_grade_start_date=date(2031, 7, 1),
        new_grade_end_date=date(2032, 6, 30),
        replacement_contracts=rep,
    )

    with session_factory() as database_session:
        service = service_cls(database_session)
        preview = service.preview_certification_transition(
            case_a.recipient_id, preview_req, account
        )
        database_session.commit()
        token = preview.preview_token

    def _fp(rid: int) -> str:
        with database_engine.connect() as connection:
            return _full_ledger_fingerprint(connection, rid)

    def expect_invalid(
        label: str,
        rid: int,
        token_value: object,
        *,
        expect_code: str,
        also_seal_rid: int | None = None,
    ) -> None:
        """R9-03: each rejection path has its own full ledger before/after fingerprint."""
        snap_primary = _fp(rid)
        snap_secondary = _fp(also_seal_rid) if also_seal_rid is not None else None
        with session_factory() as database_session:
            service = service_cls(database_session)
            try:
                service.apply_certification_transition(
                    rid,
                    schemas.CertificationTransitionApplyRequest(
                        preview_token=token_value,
                        confirmed=True,
                        replacement_contracts=rep,
                    ),
                    account,
                )
                database_session.commit()
                _fail(label + "_ACCEPTED")
            except Exception as exc:
                database_session.rollback()
                code = _error_code(exc)
                if code != expect_code:
                    if code == "CERTIFICATION_TRANSITION_STALE":
                        _fail(label + "_CLASSIFIED_AS_STALE")
                    if code == "CERTIFICATION_TRANSITION_TOKEN_INVALID" and (
                        expect_code == "CERTIFICATION_TRANSITION_PREVIEW_REQUIRED"
                    ):
                        _fail(label + "_CLASSIFIED_AS_TOKEN_INVALID")
                    _fail(label + "_CODE: " + code)
        if _fp(rid) != snap_primary:
            _fail(label + "_FINGERPRINT_CHANGED")
        if also_seal_rid is not None and snap_secondary is not None:
            if _fp(also_seal_rid) != snap_secondary:
                _fail(label + "_SECONDARY_FINGERPRINT_CHANGED")

    # Tamper → TOKEN_INVALID + full write-zero on A
    tampered = str(token)[:-1] + ("0" if not str(token).endswith("0") else "1")
    expect_invalid(
        "W1D_TRN_TOKEN_TAMPER",
        case_a.recipient_id,
        tampered,
        expect_code="CERTIFICATION_TRANSITION_TOKEN_INVALID",
    )

    # Expiry via injectable clock → TOKEN_INVALID
    try:
        from app.domains.w1d import clock as w1d_clock  # type: ignore
    except Exception:
        _fail("W1D_CLOCK_SEAM_MISSING: app.domains.w1d.clock")
    set_now = getattr(w1d_clock, "set_now_utc", None)
    if set_now is None:
        _fail("W1D_CLOCK_SEAM_MISSING: set_now_utc")
    set_now(datetime.now(UTC) + timedelta(hours=2))
    try:
        expect_invalid(
            "W1D_TRN_TOKEN_EXPIRED",
            case_a.recipient_id,
            token,
            expect_code="CERTIFICATION_TRANSITION_TOKEN_INVALID",
        )
    finally:
        set_now(None)

    # Cross-recipient replay: seal BOTH A and B around the one call.
    expect_invalid(
        "W1D_TRN_TOKEN_CROSS_RECIPIENT",
        case_b.recipient_id,
        token,
        expect_code="CERTIFICATION_TRANSITION_TOKEN_INVALID",
        also_seal_rid=case_a.recipient_id,
    )

    # Explicit null → PREVIEW_REQUIRED (not TOKEN_INVALID).
    expect_invalid(
        "W1D_TRN_PREVIEW_REQUIRED_NULL",
        case_a.recipient_id,
        None,
        expect_code="CERTIFICATION_TRANSITION_PREVIEW_REQUIRED",
    )
    # Explicit empty string → PREVIEW_REQUIRED only.
    expect_invalid(
        "W1D_TRN_PREVIEW_REQUIRED_EMPTY",
        case_a.recipient_id,
        "",
        expect_code="CERTIFICATION_TRANSITION_PREVIEW_REQUIRED",
    )


def test_w1d_pg_08_concurrent_apply_and_multidim_stale(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """N3 / W1-TRN-03: concurrent apply 1 success + 1 STALE; cert-date and contract stale."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
    except Exception:
        _fail("W1D_HARNESS_W1C_DEPENDENCY_MISSING")

    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1d = service_cls(database_session)
        cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
        w1c.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(certification_number=cert_number),
            account,
        )
        cert = w1c.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                start_date=date(2035, 1, 1),
                end_date=date(2035, 12, 31),
            ),
            account,
        )
        grade = w1c.create_grade_period(
            case.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=cert.id,
                grade_code="3",
                start_date=date(2035, 1, 1),
                end_date=date(2035, 12, 31),
            ),
            account,
        )
        contract = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2035, 1, 1),
                end_date=None,
            ),
            account,
        )
        database_session.commit()
        cert_id, grade_id, contract_id = cert.id, grade.id, contract.id

    proposed_end = date(2035, 6, 30)
    rep = _replacement_items(schemas, contract_id, date(2035, 7, 1))
    preview_req = schemas.CertificationTransitionPreviewRequest(
        new_start_date=date(2035, 7, 1),
        new_end_date=date(2036, 6, 30),
        new_grade_code="4",
        new_grade_start_date=date(2035, 7, 1),
        new_grade_end_date=date(2036, 6, 30),
        replacement_contracts=rep,
    )

    with session_factory() as database_session:
        service = service_cls(database_session)
        preview_a = service.preview_certification_transition(
            case.recipient_id, preview_req, account
        )
        preview_b = service.preview_certification_transition(
            case.recipient_id, preview_req, account
        )
        database_session.commit()
        token_a = preview_a.preview_token
        token_b = preview_b.preview_token

    # R18: authorized preview hashes A==B; canonical before projection pre-race.
    auth_hash_a = _capture_authorized_preview(preview_a, label="trn03_preview_a")
    auth_hash_b = _capture_authorized_preview(preview_b, label="trn03_preview_b")
    if auth_hash_a != auth_hash_b:
        _fail("W1D_TRN03_PREVIEW_HASH_A_B_MISMATCH")
    authorized_preview_hash = auth_hash_a

    # J-W1D-R5-H04 / R18: complete pre-race ledger + before projection + clock window.
    with database_engine.connect() as connection:
        pre_race_ledger = _full_ledger_state(connection, case.recipient_id)
        expected_before_proj = _canonical_transition_projection(
            connection,
            case.recipient_id,
            preview_hash=authorized_preview_hash,
            include_new_ids=False,
        )

    apply_window_start: datetime | None = None

    # R10-06 / J-W1D-R3-B01: dual DISTINCT Lock wait; finally-style teardown.
    name_a = "w1d-apply-a"
    name_b = "w1d-apply-b"
    blocker_name = "w1d-apply-blocker"
    barrier = threading.Barrier(3, timeout=20)  # 2 workers + main
    both_waiting = threading.Event()
    stop_monitor = threading.Event()
    monitor_errors: list[str] = []
    harness_errors: list[str] = []
    results_lock = threading.Lock()
    worker_results: dict[str, Any] = {}
    apply_results: list[Any] = []
    mon: threading.Thread | None = None
    t1: threading.Thread | None = None
    t2: threading.Thread | None = None
    blocker_engine = None
    blocker_conn = None
    blocker_tx = None
    blocker_done = False
    fail_marker: str | None = None

    def _record(msg: str) -> None:
        with results_lock:
            harness_errors.append(msg)

    def apply_worker(token: str, app_name: str) -> None:
        engine = None
        try:
            engine = create_engine(
                os.environ["SSWCENTER_DATABASE_URL"],
                pool_pre_ping=True,
                connect_args={"options": f"-c application_name={app_name}"},
            )
            factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
            barrier.wait()
            with factory() as database_session:
                service = service_cls(database_session)
                try:
                    result = service.apply_certification_transition(
                        case.recipient_id,
                        schemas.CertificationTransitionApplyRequest(
                            preview_token=token,
                            confirmed=True,
                            replacement_contracts=rep,
                        ),
                        account,
                    )
                    database_session.commit()
                    # R18: structured winner only (no ok: text serialization).
                    try:
                        packed = _pack_structured_winner_result(result)
                    except ValueError as ve:
                        with results_lock:
                            worker_results[app_name] = str(ve)
                    else:
                        with results_lock:
                            worker_results[app_name] = packed
                except Exception as exc:
                    try:
                        database_session.rollback()
                    except Exception as rb_exc:
                        _record(f"{app_name}:rollback:{type(rb_exc).__name__}")
                    with results_lock:
                        worker_results[app_name] = _error_code(exc)
        except Exception as exc:
            _record(f"{app_name}:setup:{type(exc).__name__}:{exc}")
        finally:
            if engine is not None:
                try:
                    engine.dispose()
                except Exception as ds_exc:
                    _record(f"{app_name}:dispose:{type(ds_exc).__name__}")

    def monitor_both_waiting() -> None:
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
                errors.append(f"tx:{type(exc).__name__}")
                try:
                    blocker_tx.rollback()
                except Exception as rb_exc:
                    errors.append(f"tx_rb:{type(rb_exc).__name__}")
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
            _record("blocker:" + ";".join(errors))

    def _assert_no_apply_sessions() -> None:
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
            _fail("W1D_TRN03_SESSION_QUERY_FAILED: " + type(exc).__name__)
        if residual:
            detail = ",".join(f"{r['application_name']}={r['n']}" for r in residual)
            _fail("W1D_TRN03_SESSION_RESIDUAL: " + detail)

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
            {"id": case.recipient_id},
        )
        mon = threading.Thread(target=monitor_both_waiting, daemon=True)
        mon.start()
        t1 = threading.Thread(target=apply_worker, args=(token_a, name_a), daemon=True)
        t2 = threading.Thread(target=apply_worker, args=(token_b, name_b), daemon=True)
        t1.start()
        t2.start()
        try:
            barrier.wait()
        except Exception as exc:
            fail_marker = "W1D_TRN03_READY_BARRIER: " + type(exc).__name__
            raise RuntimeError(fail_marker) from exc
        observed = both_waiting.wait(timeout=20)
        if not observed:
            fail_marker = "W1D_TRN03_LOCK_WAIT_NOT_OBSERVED"
            raise RuntimeError(fail_marker)
        # R18: DB clock window starts immediately before blocker release.
        with database_engine.connect() as connection:
            apply_window_start = _normalize_utc_timestamp(
                connection.execute(text("SELECT clock_timestamp()")).scalar(),
                label="trn03_window_start",
            )
        _release_blocker(commit=True)
        if mon is not None:
            mon.join(timeout=3)
        if mon is not None and mon.is_alive():
            fail_marker = "W1D_TRN03_LOCK_MONITOR_JOIN_TIMEOUT"
            raise RuntimeError(fail_marker)
        if monitor_errors:
            fail_marker = "W1D_TRN03_LOCK_MONITOR_EXCEPTION: " + monitor_errors[0][:200]
            raise RuntimeError(fail_marker)
        if t1 is not None:
            t1.join(timeout=60)
        if t2 is not None:
            t2.join(timeout=60)
        if (t1 is not None and t1.is_alive()) or (t2 is not None and t2.is_alive()):
            fail_marker = "W1D_TRN03_WORKER_JOIN_TIMEOUT"
            raise RuntimeError(fail_marker)
        with results_lock:
            he = list(harness_errors)
            apply_results = [
                worker_results.get(name_a, "missing"),
                worker_results.get(name_b, "missing"),
            ]
        if he:
            fail_marker = "W1D_TRN03_CLEANUP_OR_SETUP: " + he[0][:200]
            raise RuntimeError(fail_marker)
        _assert_no_apply_sessions()
    except Exception as exc:
        if fail_marker is None:
            fail_marker = "W1D_TRN03_ORCHESTRATION: " + type(exc).__name__
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
            if not apply_results:
                apply_results = [
                    worker_results.get(name_a, "missing"),
                    worker_results.get(name_b, "missing"),
                ]
        if he and fail_marker is None:
            fail_marker = "W1D_TRN03_CLEANUP_OR_SETUP: " + he[0][:200]
        try:
            with database_engine.connect() as connection:
                residual = connection.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM pg_stat_activity
                        WHERE application_name IN (:a, :b, :blocker)
                        """
                    ),
                    {"a": name_a, "b": name_b, "blocker": blocker_name},
                ).scalar_one()
            if int(residual) != 0:
                fail_marker = "W1D_TRN03_SESSION_RESIDUAL_FINALLY"
        except Exception:
            if fail_marker is None:
                fail_marker = "W1D_TRN03_SESSION_CHECK_FAILED"
        if mon is not None and mon.is_alive():
            fail_marker = "W1D_TRN03_LOCK_MONITOR_JOIN_TIMEOUT"
        elif t1 is not None and t1.is_alive():
            fail_marker = "W1D_TRN03_WORKER_JOIN_TIMEOUT"
        elif t2 is not None and t2.is_alive():
            fail_marker = "W1D_TRN03_WORKER_JOIN_TIMEOUT"
        if fail_marker is not None:
            _fail(fail_marker)

    # R19 pure mutants (always run in pg_08 product path; never catch BaseException).
    if _r19_all_pure_mutant_selfchecks() != "PASS":
        _fail("W1D_R19_PURE_MUTANT_SELFCHECK_FAILED")

    ok_items = [
        item for item in apply_results if type(item) is dict and item.get("status") == "SUCCESS"
    ]
    stale_count = sum(1 for item in apply_results if item == "CERTIFICATION_TRANSITION_STALE")
    if len(ok_items) != 1 or stale_count != 1:
        _fail(
            "W1D_TRN03_CONCURRENT_APPLY_RESULT: "
            + ",".join(repr(x) for x in apply_results)
            + f" ok={len(ok_items)} stale={stale_count}"
        )
    winner = _assert_structured_winner_shape(ok_items[0])
    new_cert_id = winner["new_certification_period_id"]
    new_grade_id = winner["new_grade_period_id"]
    winner_contract_id = winner["new_contract_ids"][0]
    corr_s = winner["audit_correlation_id"]
    if apply_window_start is None:
        _fail("W1D_TRN03_WINDOW_START_MISSING")

    # J-W1D-R5-H04 / R18: full single-winner projection with sealed timestamp.
    with database_engine.connect() as connection:
        apply_window_end = _normalize_utc_timestamp(
            connection.execute(text("SELECT clock_timestamp()")).scalar(),
            label="trn03_window_end",
        )
        # Derive sealed apply timestamp from the single audit append occurred_at
        # after confirming append cardinality, then enforce equality everywhere.
        after_audit_probe = _all_audit_rows(connection)
        before_audit_n = len(pre_race_ledger["audit"])
        if len(after_audit_probe) != before_audit_n + 1:
            _fail("W1D_TRN03_AUDIT_LEN_PRE_SEAL")
        sealed_apply_ts = _normalize_utc_timestamp(
            after_audit_probe[-1].get("occurred_at_utc"),
            label="trn03_sealed_apply_ts",
        )
        expected_after_proj = _canonical_transition_projection(
            connection,
            case.recipient_id,
            preview_hash=authorized_preview_hash,
            include_new_ids=True,
            new_cert_id=new_cert_id,
            new_grade_id=new_grade_id,
            new_contract_ids=[winner_contract_id],
        )
        _assert_single_winner_ledger_projection(
            connection,
            case.recipient_id,
            pre_race_ledger,
            old_cert_id=cert_id,
            old_grade_id=grade_id,
            old_contract_id=contract_id,
            new_cert_id=new_cert_id,
            new_grade_id=new_grade_id,
            new_contract_id=winner_contract_id,
            proposed_end=proposed_end,
            new_start=date(2035, 7, 1),
            new_end=date(2036, 6, 30),
            new_grade_code="4",
            correlation=str(corr_s),
            account_id=case.account_id,
            sealed_apply_ts=sealed_apply_ts,
            apply_window_start=apply_window_start,
            apply_window_end=apply_window_end,
            authorized_preview_hash=authorized_preview_hash,
            expected_before_proj=expected_before_proj,
            expected_after_proj=expected_after_proj,
        )
        residual = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM pg_stat_activity
                WHERE application_name IN (:a, :b, :blocker)
                """
            ),
            {"a": name_a, "b": name_b, "blocker": blocker_name},
        ).scalar_one()
        if int(residual) != 0:
            _fail("W1D_TRN03_SESSION_RESIDUAL_POST: " + str(residual))

    # --- Separate multi-dimension stale cases (fresh recipient each) ---
    def seed_for_stale() -> tuple[W1DCase, int, int, int, Any, list[Any]]:
        local = _seed_case(session_factory)
        with session_factory() as database_session:
            w1c = W1CService(database_session)
            w1d = service_cls(database_session)
            number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
            w1c.create_identity(
                local.recipient_id,
                CertificationIdentityCreateRequest(certification_number=number),
                account,
            )
            c_period = w1c.create_certification_period(
                local.recipient_id,
                CertificationPeriodCreateRequest(
                    start_date=date(2036, 1, 1),
                    end_date=date(2036, 12, 31),
                ),
                account,
            )
            g_period = w1c.create_grade_period(
                local.recipient_id,
                GradePeriodCreateRequest(
                    certification_period_id=c_period.id,
                    grade_code="2",
                    start_date=date(2036, 1, 1),
                    end_date=date(2036, 12, 31),
                ),
                account,
            )
            ctr = w1d.create_contract(
                local.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2036, 1, 1),
                ),
                account,
            )
            database_session.commit()
            local_rep = _replacement_items(schemas, ctr.id, date(2036, 7, 1))
            local_req = schemas.CertificationTransitionPreviewRequest(
                new_start_date=date(2036, 7, 1),
                new_end_date=date(2037, 6, 30),
                new_grade_code="3",
                new_grade_start_date=date(2036, 7, 1),
                new_grade_end_date=date(2037, 6, 30),
                replacement_contracts=local_rep,
            )
            preview = service_cls(database_session).preview_certification_transition(
                local.recipient_id, local_req, account
            )
            database_session.commit()
            return local, c_period.id, g_period.id, ctr.id, preview.preview_token, local_rep

    def run_stale_dimension(
        label: str,
        mutate_sql: str,
        id_param_name: str,
        id_from_seed: str,
    ) -> None:
        local, c_id, g_id, ctr_id, token, local_rep = seed_for_stale()
        id_map = {"cert": c_id, "grade": g_id, "contract": ctr_id}
        mutate_id = id_map[id_from_seed]
        with session_factory() as database_session:
            result = database_session.execute(text(mutate_sql), {id_param_name: mutate_id})
            # J-B01: setup mutation must commit successfully (rowcount >= 1).
            if getattr(result, "rowcount", 1) == 0:
                _fail(label + "_SETUP_MUTATION_NO_ROWS")
            database_session.commit()
        # Post-setup snapshots only (not pre-mutation); full write-zero after STALE.
        with database_engine.connect() as connection:
            post_fp, post_audit = _write_zero_pair(connection, local.recipient_id)
        with session_factory() as database_session:
            service = service_cls(database_session)
            try:
                service.apply_certification_transition(
                    local.recipient_id,
                    schemas.CertificationTransitionApplyRequest(
                        preview_token=token,
                        confirmed=True,
                        replacement_contracts=local_rep,
                    ),
                    account,
                )
                database_session.commit()
                _fail(label + "_STALE_APPLY_ACCEPTED")
            except Exception as exc:
                database_session.rollback()
                if _error_code(exc) != "CERTIFICATION_TRANSITION_STALE":
                    _fail(label + "_STALE_CODE: " + _error_code(exc))
        with database_engine.connect() as connection:
            _assert_write_zero_pair(
                connection,
                local.recipient_id,
                post_fp,
                post_audit,
                label=label + "_STALE",
            )
            new_c = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM erp.recipient_contract
                    WHERE recipient_id = :rid AND start_date = DATE '2036-07-01'
                    """
                ),
                {"rid": local.recipient_id},
            ).scalar_one()
            if int(new_c) != 0:
                _fail(label + "_PARTIAL_NEW_CONTRACT")
            new_grade = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM erp.recipient_grade_period
                    WHERE recipient_id = :rid AND start_date = DATE '2036-07-01'
                    """
                ),
                {"rid": local.recipient_id},
            ).scalar_one()
            if int(new_grade) != 0:
                _fail(label + "_PARTIAL_NEW_GRADE")
            # Transition proposed_end must not have been applied on originals.
            if label != "W1D_TRN03_STALE_CERT_DATE":
                c_end = connection.execute(
                    text("SELECT end_date FROM erp.recipient_certification_period WHERE id = :id"),
                    {"id": c_id},
                ).scalar_one()
                if c_end != date(2036, 12, 31):
                    _fail(label + "_CERT_PARTIALLY_ENDED: " + str(c_end))
            else:
                c_end = connection.execute(
                    text("SELECT end_date FROM erp.recipient_certification_period WHERE id = :id"),
                    {"id": c_id},
                ).scalar_one()
                if c_end == date(2036, 6, 30):
                    _fail(label + "_APPLY_ENDED_CERT_ON_STALE")
                if c_end != date(2037, 1, 31):
                    _fail(label + "_CERT_MUTATE_NOT_RETAINED: " + str(c_end))
            if label != "W1D_TRN03_STALE_CONTRACT_PERIOD":
                t_end = connection.execute(
                    text("SELECT end_date FROM erp.recipient_contract WHERE id = :id"),
                    {"id": ctr_id},
                ).scalar_one()
                if t_end is not None and t_end == date(2036, 6, 30):
                    _fail(label + "_CONTRACT_PARTIALLY_ENDED")

    # J-B01: certification-date mutation must preserve grade containment
    # (extend end_date, do NOT shrink inside active grade range).
    run_stale_dimension(
        "W1D_TRN03_STALE_CERT_DATE",
        """
        UPDATE erp.recipient_certification_period
        SET end_date = DATE '2037-01-31',
            row_version = row_version + 1,
            updated_at_utc = clock_timestamp()
        WHERE id = :id
        """,
        "id",
        "cert",
    )
    run_stale_dimension(
        "W1D_TRN03_STALE_GRADE",
        """
        UPDATE erp.recipient_grade_period
        SET grade_code = '5',
            row_version = row_version + 1,
            updated_at_utc = clock_timestamp()
        WHERE id = :id
        """,
        "id",
        "grade",
    )
    run_stale_dimension(
        "W1D_TRN03_STALE_CONTRACT_PERIOD",
        """
        UPDATE erp.recipient_contract
        SET end_date = DATE '2036-03-31',
            row_version = row_version + 1,
            updated_at_utc = clock_timestamp()
        WHERE id = :id
        """,
        "id",
        "contract",
    )
    # J-M01 / R4-05: service multiset must actually differ before/after setup.
    local_ms, c_id_ms, g_id_ms, ctr_id_ms, token_ms, rep_ms = seed_for_stale()
    with database_engine.connect() as connection:
        home_id = connection.execute(
            text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE'")
        ).scalar_one()
        bath_id = connection.execute(
            text("SELECT id FROM erp.service_type WHERE code = 'HOME_BATH'")
        ).scalar_one()
        before_ms = connection.execute(
            text(
                """
                SELECT service_type_id FROM erp.recipient_contract
                WHERE recipient_id = :rid AND invalidated_at_utc IS NULL
                ORDER BY service_type_id, id
                """
            ),
            {"rid": local_ms.recipient_id},
        ).all()
        before_multiset = tuple(int(r[0]) for r in before_ms)
        if home_id not in before_multiset:
            _fail("W1D_TRN03_STALE_SERVICE_MULTISET_SETUP_HOME_MISSING")
    with session_factory() as database_session:
        result = database_session.execute(
            text(
                """
                UPDATE erp.recipient_contract
                SET service_type_id = :bath,
                    row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"bath": int(bath_id), "id": ctr_id_ms},
        )
        if getattr(result, "rowcount", 1) == 0:
            _fail("W1D_TRN03_STALE_SERVICE_MULTISET_SETUP_MUTATION_NO_ROWS")
        database_session.commit()
    with database_engine.connect() as connection:
        after_ms = connection.execute(
            text(
                """
                SELECT service_type_id FROM erp.recipient_contract
                WHERE recipient_id = :rid AND invalidated_at_utc IS NULL
                ORDER BY service_type_id, id
                """
            ),
            {"rid": local_ms.recipient_id},
        ).all()
        after_multiset = tuple(int(r[0]) for r in after_ms)
        if after_multiset == before_multiset:
            _fail(
                "W1D_TRN03_STALE_SERVICE_MULTISET_NOT_CHANGED: "
                + f"before={before_multiset} after={after_multiset}"
            )
        if int(bath_id) not in after_multiset:
            _fail("W1D_TRN03_STALE_SERVICE_MULTISET_BATH_MISSING")
        post_fp_ms, post_audit_ms = _write_zero_pair(connection, local_ms.recipient_id)
    with session_factory() as database_session:
        service = service_cls(database_session)
        try:
            service.apply_certification_transition(
                local_ms.recipient_id,
                schemas.CertificationTransitionApplyRequest(
                    preview_token=token_ms,
                    confirmed=True,
                    replacement_contracts=rep_ms,
                ),
                account,
            )
            database_session.commit()
            _fail("W1D_TRN03_STALE_SERVICE_MULTISET_STALE_APPLY_ACCEPTED")
        except Exception as exc:
            database_session.rollback()
            if _error_code(exc) != "CERTIFICATION_TRANSITION_STALE":
                _fail("W1D_TRN03_STALE_SERVICE_MULTISET_STALE_CODE: " + _error_code(exc))
    with database_engine.connect() as connection:
        _assert_write_zero_pair(
            connection,
            local_ms.recipient_id,
            post_fp_ms,
            post_audit_ms,
            label="W1D_TRN03_STALE_SERVICE_MULTISET",
        )
        new_c = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM erp.recipient_contract
                WHERE recipient_id = :rid AND start_date = DATE '2036-07-01'
                """
            ),
            {"rid": local_ms.recipient_id},
        ).scalar_one()
        if int(new_c) != 0:
            _fail("W1D_TRN03_STALE_SERVICE_MULTISET_PARTIAL_NEW_CONTRACT")


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


def test_w1d_pg_10_apply_fault_labels_full_matrix(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """J-H05: all ten sealed apply fault labels full fingerprint rollback."""
    _require_w1d_catalog(database_engine)
    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
        from app.domains.w1d import fault as w1d_fault  # type: ignore
    except Exception:
        _fail("W1D_FAULT_SEAM_MISSING_OR_W1C")

    set_fault = getattr(w1d_fault, "set_fault_point", None) or getattr(w1d_fault, "install", None)
    if set_fault is None:
        _fail("W1D_FAULT_SEAM_MISSING: set_fault_point")

    labels = (
        "after_lock",
        "after_hash",
        "after_end_grade",
        "after_end_cert",
        "after_end_contracts",
        "after_create_cert",
        "after_create_grade",
        "after_create_contracts",
        "after_audit",
        "before_commit",
    )
    service_cls = _load_service()
    schemas = _load_schemas()

    for label in labels:
        case = _seed_case(session_factory)
        account = _current_account(case)
        with session_factory() as database_session:
            w1c = W1CService(database_session)
            w1d = service_cls(database_session)
            num = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
            w1c.create_identity(
                case.recipient_id,
                CertificationIdentityCreateRequest(certification_number=num),
                account,
            )
            cert = w1c.create_certification_period(
                case.recipient_id,
                CertificationPeriodCreateRequest(
                    start_date=date(2042, 1, 1),
                    end_date=date(2042, 12, 31),
                ),
                account,
            )
            w1c.create_grade_period(
                case.recipient_id,
                GradePeriodCreateRequest(
                    certification_period_id=cert.id,
                    grade_code="1",
                    start_date=date(2042, 1, 1),
                    end_date=date(2042, 12, 31),
                ),
                account,
            )
            ctr = w1d.create_contract(
                case.recipient_id,
                schemas.ContractCreateRequest(
                    service_type_code=SERVICE_HOME_CARE,
                    start_date=date(2042, 1, 1),
                ),
                account,
            )
            database_session.commit()
            rep = _replacement_items(schemas, ctr.id, date(2042, 7, 1))
            req = schemas.CertificationTransitionPreviewRequest(
                new_start_date=date(2042, 7, 1),
                new_end_date=date(2043, 6, 30),
                new_grade_code="2",
                new_grade_start_date=date(2042, 7, 1),
                new_grade_end_date=date(2043, 6, 30),
                replacement_contracts=rep,
            )
            preview = service_cls(database_session).preview_certification_transition(
                case.recipient_id, req, account
            )
            database_session.commit()
            token = preview.preview_token

        with database_engine.connect() as connection:
            snap = _full_ledger_fingerprint(connection, case.recipient_id)
        set_fault(label)
        try:
            with session_factory() as database_session:
                service = service_cls(database_session)
                try:
                    service.apply_certification_transition(
                        case.recipient_id,
                        schemas.CertificationTransitionApplyRequest(
                            preview_token=token,
                            confirmed=True,
                            replacement_contracts=rep,
                        ),
                        account,
                    )
                    database_session.commit()
                    _fail(f"W1D_TRN04_FAULT_{label}_DID_NOT_RAISE")
                except Exception as exc:
                    database_session.rollback()
                    # R4-04: exact injected seam marker required; reject unrelated.
                    text_exc = f"{type(exc).__name__}:{exc}:{getattr(exc, 'code', '')}"
                    marker = f"W1D_FAULT:{label}"
                    if marker not in text_exc:
                        _fail(f"W1D_TRN04_FAULT_{label}_WRONG_EXCEPTION: " + text_exc[:200])
        finally:
            set_fault(None)
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap:
                _fail(f"W1D_TRN04_FAULT_{label}_PARTIAL_SUCCESS")
            audit_delta = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM erp.audit_event
                    WHERE action_code = 'CERTIFICATION_TRANSITION_APPLY'
                      AND entity_pk = :rid
                    """
                ),
                {"rid": case.recipient_id},
            ).scalar_one()
            if int(audit_delta) != 0:
                _fail(f"W1D_TRN04_FAULT_{label}_AUDIT_DELTA")


def test_w1d_pg_11_api_acl_csrf_token_envelopes(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """J-M03/M06: ACL, VIEW-only, CSRF, omit/null/blank token API envelopes."""
    _require_w1d_catalog(database_engine)
    admin = _seed_case(session_factory)
    # Build USER with no permissions and VIEW-only.
    from app.core.security import PinProtector
    from app.db.models import AccountPermission, Staff, UserAccount

    label = uuid4().hex
    protector = PinProtector(
        os.environ["SSWCENTER_PIN_PEPPER"],
        os.environ["SSWCENTER_PIN_LOOKUP_KEY"],
    )
    with session_factory() as database_session:
        staff_v = Staff(
            name=f"W1D VIEW {label}",
            birth_date=date(1991, 1, 1),
            sex_code="TEST",
            display_name=f"VIEW {label}",
            row_version=1,
        )
        staff_n = Staff(
            name=f"W1D NONE {label}",
            birth_date=date(1992, 1, 1),
            sex_code="TEST",
            display_name=f"NONE {label}",
            row_version=1,
        )
        database_session.add_all([staff_v, staff_n])
        database_session.flush()
        pin_view = _synthetic_pin_for_staff_id(staff_v.id)
        pin_none = _synthetic_pin_for_staff_id(staff_n.id)
        acc_v = UserAccount(
            staff_id=staff_v.id,
            account_code=f"W1D_VIEW_{label}",
            display_name=f"VIEW {label}",
            role_code="USER",
            pin_hash=protector.hash_pin(pin_view),
            pin_lookup_hmac=protector.lookup_hmac(pin_view),
            pin_key_version=1,
            row_version=1,
        )
        acc_n = UserAccount(
            staff_id=staff_n.id,
            account_code=f"W1D_NONE_{label}",
            display_name=f"NONE {label}",
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

    path = f"/api/v1/recipients/{admin.recipient_id}/contracts"
    apply_path = f"/api/v1/recipients/{admin.recipient_id}/certification-transitions/apply"
    payload = {
        "service_type_code": SERVICE_HOME_CARE,
        "start_date": "2045-01-01",
        "end_date": "2045-01-31",
    }

    with TestClient(app) as client:
        with database_engine.connect() as connection:
            snap0 = _full_ledger_fingerprint(connection, admin.recipient_id)

        # unauthenticated — exact AUTHENTICATION_REQUIRED envelope, write 0 (R8-09).
        r = client.post(path, json=payload)
        if r.status_code != 401:
            _fail("W1D_API_UNAUTH_NOT_401: " + str(r.status_code))
        _assert_standard_error_envelope(r.json(), expect_code="AUTHENTICATION_REQUIRED")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, admin.recipient_id) != snap0:
                _fail("W1D_API_UNAUTH_WROTE_ROWS")

        # no-permission USER
        login_n = client.post("/api/auth/login", json={"pin": pin_none})
        if login_n.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_NONE_FAILED")
        csrf_n = client.cookies.get("sswcenter_csrf")
        with database_engine.connect() as connection:
            snap_n = _full_ledger_fingerprint(connection, admin.recipient_id)
        r = client.post(path, json=payload, headers={"X-CSRF-Token": csrf_n or ""})
        if r.status_code != 403:
            _fail("W1D_API_NOPERM_NOT_403: " + str(r.status_code))
        _assert_standard_error_envelope(r.json(), expect_code="PERMISSION_REQUIRED")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, admin.recipient_id) != snap_n:
                _fail("W1D_API_NOPERM_WROTE_ROWS")

        # VIEW-only mutation forbidden
        client.cookies.clear()
        login_v = client.post("/api/auth/login", json={"pin": pin_view})
        if login_v.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_VIEW_FAILED")
        csrf_v = client.cookies.get("sswcenter_csrf")
        with database_engine.connect() as connection:
            snap_v = _full_ledger_fingerprint(connection, admin.recipient_id)
        r = client.post(path, json=payload, headers={"X-CSRF-Token": csrf_v or ""})
        if r.status_code != 403:
            _fail("W1D_API_VIEW_MUTATION_NOT_403: " + str(r.status_code))
        _assert_standard_error_envelope(r.json(), expect_code="PERMISSION_REQUIRED")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, admin.recipient_id) != snap_v:
                _fail("W1D_API_VIEW_WROTE_ROWS")

        # admin token envelope matrix (R5-05: each path independent write-zero)
        client.cookies.clear()
        login_a = client.post("/api/auth/login", json={"pin": admin.pin})
        if login_a.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_ADMIN_FAILED")
        csrf = client.cookies.get("sswcenter_csrf")
        headers = {"X-CSRF-Token": csrf or ""}

        # omit preview_token key
        with database_engine.connect() as connection:
            snap_omit = _full_ledger_fingerprint(connection, admin.recipient_id)
        r = client.post(
            apply_path,
            json={"confirmed": True, "replacement_contracts": []},
            headers=headers,
        )
        if r.status_code != 422:
            _fail("W1D_API_TOKEN_OMIT_NOT_422: " + str(r.status_code))
        env = _assert_standard_error_envelope(r.json(), expect_code="VALIDATION_ERROR")
        fields = [str(item.get("field", "")) for item in env["field_errors"]]
        if not any("preview_token" in f for f in fields):
            _fail("W1D_API_TOKEN_OMIT_FIELD_ERROR_MISSING: " + str(fields))
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, admin.recipient_id) != snap_omit:
                _fail("W1D_API_TOKEN_OMIT_WROTE_ROWS")

        # explicit null preview_token
        with database_engine.connect() as connection:
            snap_null = _full_ledger_fingerprint(connection, admin.recipient_id)
        r = client.post(
            apply_path,
            json={
                "preview_token": None,
                "confirmed": True,
                "replacement_contracts": [],
            },
            headers=headers,
        )
        if r.status_code != 422:
            _fail("W1D_API_TOKEN_NULL_NOT_422: " + str(r.status_code))
        _assert_standard_error_envelope(
            r.json(), expect_code="CERTIFICATION_TRANSITION_PREVIEW_REQUIRED"
        )
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, admin.recipient_id) != snap_null:
                _fail("W1D_API_TOKEN_NULL_WROTE_ROWS")

        # blank preview_token
        with database_engine.connect() as connection:
            snap_blank = _full_ledger_fingerprint(connection, admin.recipient_id)
        r = client.post(
            apply_path,
            json={
                "preview_token": "",
                "confirmed": True,
                "replacement_contracts": [],
            },
            headers=headers,
        )
        if r.status_code != 422:
            _fail("W1D_API_TOKEN_BLANK_NOT_422: " + str(r.status_code))
        _assert_standard_error_envelope(
            r.json(), expect_code="CERTIFICATION_TRANSITION_PREVIEW_REQUIRED"
        )
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, admin.recipient_id) != snap_blank:
                _fail("W1D_API_TOKEN_BLANK_WROTE_ROWS")


_CONTRACT_RESPONSE_FIELDS = (
    "id",
    "recipient_id",
    "service_type_code",
    "service_group_code",
    "start_date",
    "end_date",
    "service_start_date",
    "signer_name",
    "signer_relationship_text",
    "signer_phone",
    "end_reason_text",
    "invalidated_at_utc",
    "replacement_contract_id",
    "row_version",
)
_CONTRACT_FORBIDDEN_FIELDS = (
    "contract_no",
    "contract_sequence",
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
    for tkey in (
        "signer_name",
        "signer_relationship_text",
        "signer_phone",
        "end_reason_text",
    ):
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
    for tkey in (
        "signer_name",
        "signer_relationship_text",
        "signer_phone",
        "end_reason_text",
    ):
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
        "signer_name": row["signer_name"],
        "signer_relationship_text": row["signer_relationship_text"],
        "signer_phone": row["signer_phone"],
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


def _r24_contract_response_mutant_selfcheck() -> None:
    """R24/H02: string IDs and date objects rejected; valid body accepted."""
    good: dict[str, Any] = {
        "id": 1,
        "recipient_id": 2,
        "service_type_code": "HOME_CARE",
        "service_group_code": "LONG_TERM_CARE",
        "start_date": "2040-01-01",
        "end_date": None,
        "service_start_date": None,
        "signer_name": None,
        "signer_relationship_text": None,
        "signer_phone": None,
        "end_reason_text": None,
        "invalidated_at_utc": None,
        "replacement_contract_id": None,
        "row_version": 1,
    }
    if _validate_contract_response_strict(good) is not None:
        _fail("W1D_R24_CONTRACT_RESP_GOOD_REJECTED")
    mutants: list[tuple[object, str]] = [
        ({**good, "id": "1"}, "string_id"),
        ({**good, "recipient_id": "2"}, "string_rid"),
        ({**good, "start_date": date(2040, 1, 1)}, "date_object"),
        ({**good, "end_date": date(2040, 6, 1)}, "end_date_object"),
        ({**good, "row_version": True}, "bool_rv"),
        ({**good, "id": 0}, "zero_id"),
        ({**good, "id": True}, "bool_id"),
        ({**good, "contract_no": "X"}, "forbidden"),
        ({k: v for k, v in good.items() if k != "id"}, "missing_id"),
        ({**good, "extra": 1}, "extra_key"),
    ]
    for payload, tag in mutants:
        if _validate_contract_response_strict(payload) is None:
            _fail(f"W1D_R24_CONTRACT_RESP_ACCEPTED:{tag}")
    # DB normalizer produces exact JSON primitives matching valid API body.
    row = {
        "id": 1,
        "recipient_id": 2,
        "service_type_code": "HOME_CARE",
        "service_group_code": "LONG_TERM_CARE",
        "start_date": date(2040, 1, 1),
        "end_date": None,
        "service_start_date": None,
        "signer_name": None,
        "signer_relationship_text": None,
        "signer_phone": None,
        "end_reason_text": None,
        "invalidated_at_utc": None,
        "replacement_contract_id": None,
        "row_version": 1,
    }
    expected = _normalize_db_contract_row_for_api(row, label="R24_DB")
    if expected != good:
        _fail(f"W1D_R24_DB_NORMALIZE_MISMATCH:{expected!r}")
    # Matcher equality path uses strict API + DB normalizer only (no API int()).
    _assert_contract_response_matches_row(good, row, label="R24_GOOD")
    # Pure shape rejects string id / date object before any row compare.
    if _validate_contract_response_strict({**good, "id": "1"}) is None:
        _fail("W1D_R24_CONTRACT_MATCH_STRING_ID_GATE")
    if _validate_contract_response_strict({**good, "start_date": date(2040, 1, 1)}) is None:
        _fail("W1D_R24_CONTRACT_MATCH_DATE_OBJECT_GATE")


def _r24_pg05_audit_path_source_selfcheck() -> None:
    """Prove active pg_05 uses shared exact-audit predicate (no default=str/int new_ids)."""
    import inspect

    src = inspect.getsource(test_w1d_pg_05_transition_preview_apply_stale_multiset_fault_audit)
    if "_validate_exact_audit_projection" not in src:
        _fail("W1D_R24_PG05_MISSING_SHARED_AUDIT_PREDICATE")
    if re.search(r"json\.dumps\([^;\n]*default\s*=\s*str", src):
        _fail("W1D_R24_PG05_STILL_USES_DEFAULT_STR")
    if "int(new_ids" in src or "int(x) for x in (new_ids" in src:
        _fail("W1D_R24_PG05_STILL_INT_COERCES_NEW_IDS")
    if "json.dumps(before_proj" in src or "json.dumps(after_proj" in src:
        _fail("W1D_R24_PG05_STILL_DUMPS_PROJECTION")


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
                "signer_name": None,
                "signer_relationship_text": None,
                "signer_phone": None,
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
                           c.signer_name, c.signer_relationship_text, c.signer_phone,
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
                "signer_name": None,
                "signer_relationship_text": None,
                "signer_phone": None,
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
                           c.signer_name, c.signer_relationship_text, c.signer_phone,
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
    """R8-08/10: HTTP null-identity 404; null/empty free-text; Unicode; reverse 422."""
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    try:
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_APP_IMPORT_MISSING")
    collection = f"/api/v1/recipients/{case.recipient_id}/contracts"
    preview_path = f"/api/v1/recipients/{case.recipient_id}/certification-transitions/preview"
    apply_path = f"/api/v1/recipients/{case.recipient_id}/certification-transitions/apply"
    preview_payload = {
        "new_start_date": "2060-07-01",
        "new_end_date": "2061-06-30",
        "new_grade_code": "1",
        "new_grade_start_date": "2060-07-01",
        "new_grade_end_date": "2061-06-30",
        "replacement_contracts": [],
    }
    # R8-08: sealed order places identity existence before token crypto, so even
    # a garbage preview_token must yield CERTIFICATION_IDENTITY_NOT_FOUND (not
    # TOKEN_INVALID) for a recipient with no W1C identity.
    apply_payload = {
        "preview_token": "deadbeef-not-a-valid-token",
        "confirmed": True,
        "replacement_contracts": [],
    }
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": case.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_FAILED")
        csrf = client.cookies.get("sswcenter_csrf")
        if not csrf:
            _fail("W1D_HARNESS_CSRF_COOKIE_MISSING")
        headers = {"X-CSRF-Token": csrf}

        with database_engine.connect() as connection:
            snap_prev = _full_ledger_fingerprint(connection, case.recipient_id)
        prev = client.post(preview_path, json=preview_payload, headers=headers)
        if prev.status_code != 404:
            _fail("W1D_TRN_NULL_IDENTITY_PREVIEW_NOT_404: " + str(prev.status_code))
        _assert_standard_error_envelope(prev.json(), expect_code="CERTIFICATION_IDENTITY_NOT_FOUND")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_prev:
                _fail("W1D_TRN_NULL_IDENTITY_PREVIEW_WROTE_ROWS")

        with database_engine.connect() as connection:
            snap_apply = _full_ledger_fingerprint(connection, case.recipient_id)
        app_r = client.post(apply_path, json=apply_payload, headers=headers)
        if app_r.status_code != 404:
            _fail("W1D_TRN_NULL_IDENTITY_APPLY_NOT_404: " + str(app_r.status_code))
        _assert_standard_error_envelope(
            app_r.json(), expect_code="CERTIFICATION_IDENTITY_NOT_FOUND"
        )
        # Must not collapse to TOKEN_INVALID under sealed precedence.
        if app_r.json()["error"]["code"] == "CERTIFICATION_TRANSITION_TOKEN_INVALID":
            _fail("W1D_TRN_NULL_IDENTITY_APPLY_BECAME_TOKEN_INVALID")
        with database_engine.connect() as connection:
            if _full_ledger_fingerprint(connection, case.recipient_id) != snap_apply:
                _fail("W1D_TRN_NULL_IDENTITY_APPLY_WROTE_ROWS")

        # R8-10: omitted → NULL, explicit null → NULL, explicit "" → "".
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
        if omit.json().get("signer_name") is not None:
            _fail("W1D_API_OMIT_SIGNER_NOT_NULL")
        with database_engine.connect() as connection:
            o_row = (
                connection.execute(
                    text(
                        """
                    SELECT end_reason_text, signer_name, signer_relationship_text,
                           signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                    ),
                    {"id": omit_id},
                )
                .mappings()
                .one()
            )
            if o_row["end_reason_text"] is not None:
                _fail("W1D_API_OMIT_PERSISTED_END_REASON")
            if o_row["signer_name"] is not None:
                _fail("W1D_API_OMIT_PERSISTED_SIGNER")

        null_body = client.post(
            collection,
            json={
                "service_type_code": SERVICE_HOME_BATH,
                "start_date": "2062-04-01",
                "end_date": "2062-06-30",
                "signer_name": None,
                "signer_relationship_text": None,
                "signer_phone": None,
                "end_reason_text": None,
            },
            headers=headers,
        )
        if null_body.status_code != 201:
            _fail("W1D_API_NULL_CREATE_NOT_201: " + str(null_body.status_code))
        null_id = int(null_body.json()["id"])
        with database_engine.connect() as connection:
            n_row = (
                connection.execute(
                    text(
                        """
                    SELECT end_reason_text, signer_name, signer_relationship_text,
                           signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                    ),
                    {"id": null_id},
                )
                .mappings()
                .one()
            )
            for col in (
                "end_reason_text",
                "signer_name",
                "signer_relationship_text",
                "signer_phone",
            ):
                if n_row[col] is not None:
                    _fail(f"W1D_API_NULL_PERSISTED_{col.upper()}")

        empty_body = client.post(
            collection,
            json={
                "service_type_code": SERVICE_TEMP,
                "start_date": "2062-07-01",
                "end_date": "2062-09-30",
                "signer_name": "",
                "signer_relationship_text": "",
                "signer_phone": "",
                "end_reason_text": "",
            },
            headers=headers,
        )
        if empty_body.status_code != 201:
            _fail("W1D_API_EMPTY_CREATE_NOT_201: " + str(empty_body.status_code))
        empty_id = int(empty_body.json()["id"])
        if empty_body.json().get("end_reason_text") != "":
            _fail("W1D_API_EMPTY_END_REASON_RESPONSE")
        if empty_body.json().get("signer_name") != "":
            _fail("W1D_API_EMPTY_SIGNER_RESPONSE")
        with database_engine.connect() as connection:
            e_row = (
                connection.execute(
                    text(
                        """
                    SELECT end_reason_text, signer_name, signer_relationship_text,
                           signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                    ),
                    {"id": empty_id},
                )
                .mappings()
                .one()
            )
            for col in (
                "end_reason_text",
                "signer_name",
                "signer_relationship_text",
                "signer_phone",
            ):
                if e_row[col] != "":
                    _fail(f"W1D_API_EMPTY_PERSISTED_{col.upper()}: {e_row[col]!r}")
            # No automatic "사망" substitution.
            death = connection.execute(
                text(
                    """
                    SELECT COUNT(*) FROM erp.recipient_contract
                    WHERE id = :id AND (
                        end_reason_text = '사망' OR signer_name = '사망'
                    )
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
                "signer_name": None,
                "signer_relationship_text": None,
                "signer_phone": None,
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
                "signer_name": "유니코드서명자",
                "signer_relationship_text": "관계-한글",
                "signer_phone": "010-0000-0000",
            },
            headers=headers,
        )
        if created.status_code != 201:
            _fail("W1D_API_UNICODE_CREATE_NOT_201: " + str(created.status_code))
        cid = int(created.json()["id"])
        rv = int(created.json().get("row_version", 1))
        with database_engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    SELECT signer_name, signer_relationship_text, signer_phone
                    FROM erp.recipient_contract WHERE id = :id
                    """
                    ),
                    {"id": cid},
                )
                .mappings()
                .one()
            )
            if row["signer_name"] != "유니코드서명자":
                _fail("W1D_CON02_UNICODE_SIGNER_NOT_PRESERVED")
            if row["signer_relationship_text"] != "관계-한글":
                _fail("W1D_CON02_UNICODE_REL_NOT_PRESERVED")
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


def test_w1d_pg_14_transition_acl_csrf_all_mutations(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """J-W1D-R3-H04: create/end/preview/apply unauth 401, no-perm/VIEW 403, CSRF 403."""
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
            name=f"W1D VIEW2 {label}",
            birth_date=date(1991, 1, 1),
            sex_code="TEST",
            display_name=f"VIEW2 {label}",
            row_version=1,
        )
        staff_n = Staff(
            name=f"W1D NONE2 {label}",
            birth_date=date(1992, 1, 1),
            sex_code="TEST",
            display_name=f"NONE2 {label}",
            row_version=1,
        )
        database_session.add_all([staff_v, staff_n])
        database_session.flush()
        pin_view = _synthetic_pin_for_staff_id(staff_v.id)
        pin_none = _synthetic_pin_for_staff_id(staff_n.id)
        acc_v = UserAccount(
            staff_id=staff_v.id,
            account_code=f"W1D_VIEW2_{label}",
            display_name=f"VIEW2 {label}",
            role_code="USER",
            pin_hash=protector.hash_pin(pin_view),
            pin_lookup_hmac=protector.lookup_hmac(pin_view),
            pin_key_version=1,
            row_version=1,
        )
        acc_n = UserAccount(
            staff_id=staff_n.id,
            account_code=f"W1D_NONE2_{label}",
            display_name=f"NONE2 {label}",
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

    paths = {
        "create": f"/api/v1/recipients/{admin.recipient_id}/contracts",
        "end": f"/api/v1/recipients/{admin.recipient_id}/contracts/1/end",
        "preview": (f"/api/v1/recipients/{admin.recipient_id}/certification-transitions/preview"),
        "apply": (f"/api/v1/recipients/{admin.recipient_id}/certification-transitions/apply"),
    }
    payload = {
        "create": {
            "service_type_code": SERVICE_HOME_CARE,
            "start_date": "2070-01-01",
            "end_date": "2070-01-31",
        },
        "end": {"end_date": "2070-01-15", "expected_row_version": 1},
        "preview": {
            "new_start_date": "2070-07-01",
            "new_end_date": "2071-06-30",
            "new_grade_code": "1",
            "new_grade_start_date": "2070-07-01",
            "new_grade_end_date": "2071-06-30",
            "replacement_contracts": [],
        },
        "apply": {
            "preview_token": "x",
            "confirmed": True,
            "replacement_contracts": [],
        },
    }
    with TestClient(app) as client:
        for key, path in paths.items():
            with database_engine.connect() as connection:
                snap = _full_ledger_fingerprint(connection, admin.recipient_id)
            r = client.post(path, json=payload[key])
            if r.status_code != 401:
                _fail(f"W1D_API_{key.upper()}_UNAUTH_NOT_401: " + str(r.status_code))
            _assert_standard_error_envelope(r.json(), expect_code="AUTHENTICATION_REQUIRED")
            with database_engine.connect() as connection:
                if _full_ledger_fingerprint(connection, admin.recipient_id) != snap:
                    _fail(f"W1D_API_{key.upper()}_UNAUTH_WROTE_ROWS")

        for pin, tag in ((pin_none, "NOPERM"), (pin_view, "VIEW")):
            client.cookies.clear()
            login = client.post("/api/auth/login", json={"pin": pin})
            if login.status_code != 200:
                _fail(f"W1D_HARNESS_LOGIN_{tag}_FAILED")
            csrf = client.cookies.get("sswcenter_csrf")
            for key, path in paths.items():
                with database_engine.connect() as connection:
                    snap = _full_ledger_fingerprint(connection, admin.recipient_id)
                r = client.post(path, json=payload[key], headers={"X-CSRF-Token": csrf or ""})
                if r.status_code != 403:
                    _fail(f"W1D_API_{key.upper()}_{tag}_NOT_403: " + str(r.status_code))
                _assert_standard_error_envelope(r.json(), expect_code="PERMISSION_REQUIRED")
                with database_engine.connect() as connection:
                    if _full_ledger_fingerprint(connection, admin.recipient_id) != snap:
                        _fail(f"W1D_API_{key.upper()}_{tag}_WROTE_ROWS")

        # Admin missing CSRF on each mutation.
        client.cookies.clear()
        login = client.post("/api/auth/login", json={"pin": admin.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_LOGIN_ADMIN_FAILED")
        for key, path in paths.items():
            with database_engine.connect() as connection:
                snap = _full_ledger_fingerprint(connection, admin.recipient_id)
            r = client.post(path, json=payload[key])
            if r.status_code != 403:
                _fail(f"W1D_API_{key.upper()}_CSRF_NOT_403: " + str(r.status_code))
            _assert_standard_error_envelope(r.json(), expect_code="CSRF_REQUIRED")
            with database_engine.connect() as connection:
                if _full_ledger_fingerprint(connection, admin.recipient_id) != snap:
                    _fail(f"W1D_API_{key.upper()}_CSRF_WROTE_ROWS")


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
            response,
            *,
            expect_status: int,
            expect_code: str | None,
            rid: int,
            before_fp: str,
            before_audit: str,
        ) -> dict[str, Any]:
            if response.status_code != expect_status:
                _fail(f"W1D_API_READ_{method_label}_STATUS: " + str(response.status_code))
            body = response.json()
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
                           c.signer_name, c.signer_relationship_text, c.signer_phone,
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
                           c.signer_name, c.signer_relationship_text, c.signer_phone,
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
                           c.signer_name, c.signer_relationship_text, c.signer_phone,
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


def test_w1d_pg_16_http_apply_success_correlation_audit(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """R21/R22: real TestClient apply 200; full same-transaction ID binding.

    Chain: internal UUID-object pack (R20) + HTTP wire correlation exact-equal to
    the single appended CERTIFICATION_TRANSITION_APPLY request_id (UUID object via
    str(uuid) or already-canonical lowercase string only; never .lower() coerce).
    Response ended/new IDs exact-bound to seeded old IDs and audit after_json.new_ids.
    No fabricated/mocked API responses.
    """
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
        from app.main import app
    except Exception:
        _fail("W1D_HARNESS_HTTP_APPLY_IMPORT")

    new_start = date(2040, 7, 1)
    new_end = date(2041, 6, 30)
    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1d = service_cls(database_session)
        cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
        w1c.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(certification_number=cert_number),
            account,
        )
        cert = w1c.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                start_date=date(2040, 1, 1),
                end_date=date(2040, 12, 31),
            ),
            account,
        )
        grade = w1c.create_grade_period(
            case.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=cert.id,
                grade_code="3",
                start_date=date(2040, 1, 1),
                end_date=date(2040, 12, 31),
            ),
            account,
        )
        c1 = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2040, 1, 1),
            ),
            account,
        )
        c2 = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_BATH,
                start_date=date(2040, 1, 1),
            ),
            account,
        )
        database_session.commit()
        # Retain seeded old IDs for exact ended-list binding (R22).
        old_cert_id = cert.id
        old_grade_id = grade.id
        old_c1_id = c1.id
        old_c2_id = c2.id
        if type(old_cert_id) is not int or old_cert_id <= 0:
            _fail("W1D_HTTP_APPLY_SEED_CERT_ID")
        if type(old_grade_id) is not int or old_grade_id <= 0:
            _fail("W1D_HTTP_APPLY_SEED_GRADE_ID")
        if type(old_c1_id) is not int or old_c1_id <= 0:
            _fail("W1D_HTTP_APPLY_SEED_C1_ID")
        if type(old_c2_id) is not int or old_c2_id <= 0:
            _fail("W1D_HTTP_APPLY_SEED_C2_ID")
        preview_body = {
            "new_start_date": "2040-07-01",
            "new_end_date": "2041-06-30",
            "new_grade_code": "4",
            "new_grade_start_date": "2040-07-01",
            "new_grade_end_date": "2041-06-30",
            "replacement_contracts": [
                {
                    "ended_contract_id": old_c1_id,
                    "service_type_code": SERVICE_HOME_CARE,
                    "start_date": "2040-07-01",
                    "end_date": None,
                    "service_start_date": None,
                    "signer_name": None,
                    "signer_relationship_text": None,
                    "signer_phone": None,
                    "end_reason_text": None,
                },
                {
                    "ended_contract_id": old_c2_id,
                    "service_type_code": SERVICE_HOME_BATH,
                    "start_date": "2040-07-01",
                    "end_date": None,
                    "service_start_date": None,
                    "signer_name": None,
                    "signer_relationship_text": None,
                    "signer_phone": None,
                    "end_reason_text": None,
                },
            ],
        }

    with database_engine.connect() as connection:
        audit_before = _all_audit_rows(connection)
        before_n = len(audit_before)
        seed_recipient_no = connection.execute(
            text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
            {"id": case.recipient_id},
        ).scalar_one()
        seed_recipient_no = _assert_recipient_no_exact(
            seed_recipient_no, label="W1D_HTTP_APPLY_SEED_RECIPIENT_NO"
        )

    preview_path = f"/api/v1/recipients/{case.recipient_id}/certification-transitions/preview"
    apply_path = f"/api/v1/recipients/{case.recipient_id}/certification-transitions/apply"

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"pin": case.pin})
        if login.status_code != 200:
            _fail("W1D_HARNESS_HTTP_APPLY_LOGIN: " + str(login.status_code))
        csrf = client.cookies.get("sswcenter_csrf")
        if not csrf:
            _fail("W1D_HARNESS_HTTP_APPLY_CSRF_MISSING")
        headers = {"X-CSRF-Token": csrf}
        prev = client.post(preview_path, json=preview_body, headers=headers)
        if prev.status_code != 200:
            _fail("W1D_HTTP_APPLY_PREVIEW_NOT_200: " + str(prev.status_code))
        prev_json = prev.json()
        token = prev_json.get("preview_token")
        if type(token) is not str or not token:
            _fail("W1D_HTTP_APPLY_PREVIEW_TOKEN")
        apply_payload = {
            "preview_token": token,
            "confirmed": True,
            "replacement_contracts": preview_body["replacement_contracts"],
        }
        apply_resp = client.post(apply_path, json=apply_payload, headers=headers)
        if apply_resp.status_code != 200:
            _fail("W1D_HTTP_APPLY_NOT_200: " + str(apply_resp.status_code))
        http_body = apply_resp.json()

    with database_engine.connect() as connection:
        audit_after = _all_audit_rows(connection)
        if len(audit_after) != before_n + 1:
            _fail(
                "W1D_HTTP_APPLY_AUDIT_CARDINALITY: " + f"before={before_n} after={len(audit_after)}"
            )
        if _canonical_audit_rows_json(audit_before) != _canonical_audit_rows_json(
            audit_after[:before_n]
        ):
            _fail("W1D_HTTP_APPLY_AUDIT_PREFIX_MUTATED")
        appended = audit_after[-1]
        if appended.get("action_code") != "CERTIFICATION_TRANSITION_APPLY":
            _fail("W1D_HTTP_APPLY_AUDIT_ACTION")
        if appended.get("entity_type") != "RECIPIENT":
            _fail("W1D_HTTP_APPLY_AUDIT_ENTITY_TYPE")
        if int(appended.get("entity_pk", -1)) != case.recipient_id:
            _fail("W1D_HTTP_APPLY_AUDIT_ENTITY_PK")
        # R22: never lowercase/coerce string-form audit request_id.
        audit_corr_canon = _canonical_audit_request_id(appended.get("request_id"))
        if audit_corr_canon is None:
            _fail("W1D_HTTP_APPLY_AUDIT_REQUEST_ID_SHAPE")

        # Decode after_json fail-closed as dict; bind new_ids before response gate
        # so expected new IDs are the same-transaction audit evidence (R22).
        after_proj, after_err = _proj_decode(appended.get("after_json"))
        if after_err is not None or after_proj is None:
            _fail("W1D_HTTP_APPLY_AFTER_JSON_DECODE: " + str(after_err))
        if type(after_proj) is not dict:
            _fail("W1D_HTTP_APPLY_AFTER_JSON_TYPE")
        new_ids = after_proj.get("new_ids")
        if type(new_ids) is not dict:
            _fail("W1D_HTTP_APPLY_AFTER_NEW_IDS_TYPE")
        if set(new_ids.keys()) != {
            "certification_period_id",
            "grade_period_id",
            "contract_ids",
        }:
            _fail("W1D_HTTP_APPLY_AFTER_NEW_IDS_KEYSET")
        audit_new_cert = new_ids.get("certification_period_id")
        audit_new_grade = new_ids.get("grade_period_id")
        audit_new_cids = new_ids.get("contract_ids")
        if type(audit_new_cert) is not int or audit_new_cert <= 0:
            _fail("W1D_HTTP_APPLY_AFTER_NEW_CERT_TYPE")
        if type(audit_new_grade) is not int or audit_new_grade <= 0:
            _fail("W1D_HTTP_APPLY_AFTER_NEW_GRADE_TYPE")
        if not _strict_positive_int_list(audit_new_cids, exact_len=2):
            _fail("W1D_HTTP_APPLY_AFTER_NEW_CIDS_TYPE")

        _assert_http_apply_success_response(
            http_body,
            expected_recipient_id=case.recipient_id,
            expected_recipient_no=seed_recipient_no,
            expected_audit_request_id=audit_corr_canon,
            expected_ended_certification_period_ids=[old_cert_id],
            expected_ended_grade_period_ids=[old_grade_id],
            expected_ended_contract_ids=[old_c1_id, old_c2_id],
            expected_new_certification_period_id=audit_new_cert,
            expected_new_grade_period_id=audit_new_grade,
            expected_new_contract_ids=list(audit_new_cids),  # type: ignore[arg-type]
        )
        # Explicit chain: HTTP wire string == audit request_id of this single append.
        http_corr = http_body.get("audit_correlation_id")
        if type(http_corr) is not str or http_corr != audit_corr_canon:
            _fail("W1D_HTTP_APPLY_CORRELATION_CHAIN_MISMATCH")
        ncert = http_body["new_certification_period_id"]
        ngrade = http_body["new_grade_period_id"]
        ncids = http_body["new_contract_ids"]
        # Fail-closed exact equality to audit new_ids (no int()/sort/coerce).
        if ncert != audit_new_cert or type(ncert) is not int:
            _fail("W1D_HTTP_APPLY_NEW_CERT_AUDIT_MISMATCH")
        if ngrade != audit_new_grade or type(ngrade) is not int:
            _fail("W1D_HTTP_APPLY_NEW_GRADE_AUDIT_MISMATCH")
        if ncids != audit_new_cids or type(ncids) is not list:
            _fail("W1D_HTTP_APPLY_NEW_CIDS_AUDIT_MISMATCH")
        # Genuinely new for this recipient — not old IDs, exact cardinality 2.
        if ncert == old_cert_id:
            _fail("W1D_HTTP_APPLY_NEW_CERT_NOT_NEW")
        if ngrade == old_grade_id:
            _fail("W1D_HTTP_APPLY_NEW_GRADE_NOT_NEW")
        if ncert in (old_c1_id, old_c2_id) or ngrade in (old_c1_id, old_c2_id):
            _fail("W1D_HTTP_APPLY_NEW_ID_COLLIDES_OLD_CONTRACT")
        if any(cid in (old_c1_id, old_c2_id, old_cert_id, old_grade_id) for cid in ncids):
            _fail("W1D_HTTP_APPLY_NEW_CONTRACT_NOT_NEW")
        if len(ncids) != 2:
            _fail("W1D_HTTP_APPLY_NEW_CONTRACT_CARDINALITY")
        apply_delta = [
            r
            for r in audit_after[before_n:]
            if r.get("action_code") == "CERTIFICATION_TRANSITION_APPLY"
            and int(r.get("entity_pk", -1)) == case.recipient_id
        ]
        if len(apply_delta) != 1:
            _fail("W1D_HTTP_APPLY_AUDIT_DELTA_COUNT: " + str(len(apply_delta)))
        delta_canon = _canonical_audit_request_id(apply_delta[0].get("request_id"))
        if delta_canon is None or delta_canon != audit_corr_canon:
            _fail("W1D_HTTP_APPLY_AUDIT_DELTA_REQUEST_ID")
        # Exact newly created row properties / parent / service projection.
        cert_row = (
            connection.execute(
                text(
                    """
                SELECT id, start_date, end_date, recipient_id
                FROM erp.recipient_certification_period
                WHERE id = :id AND recipient_id = :rid
                """
                ),
                {"id": ncert, "rid": case.recipient_id},
            )
            .mappings()
            .one_or_none()
        )
        if cert_row is None:
            _fail("W1D_HTTP_APPLY_NEW_CERT_ROW_MISSING")
        if _canonical_date(cert_row["start_date"]) != new_start.isoformat():
            _fail("W1D_HTTP_APPLY_NEW_CERT_START")
        if _canonical_date(cert_row["end_date"]) != new_end.isoformat():
            _fail("W1D_HTTP_APPLY_NEW_CERT_END")
        grade_row = (
            connection.execute(
                text(
                    """
                SELECT id, certification_period_id, grade_code, start_date, end_date,
                       recipient_id
                FROM erp.recipient_grade_period
                WHERE id = :id AND recipient_id = :rid
                """
                ),
                {"id": ngrade, "rid": case.recipient_id},
            )
            .mappings()
            .one_or_none()
        )
        if grade_row is None:
            _fail("W1D_HTTP_APPLY_NEW_GRADE_ROW_MISSING")
        if grade_row["certification_period_id"] != ncert:
            _fail("W1D_HTTP_APPLY_NEW_GRADE_PARENT")
        if grade_row["grade_code"] != "4":
            _fail("W1D_HTTP_APPLY_NEW_GRADE_CODE")
        if _canonical_date(grade_row["start_date"]) != new_start.isoformat():
            _fail("W1D_HTTP_APPLY_NEW_GRADE_START")
        if _canonical_date(grade_row["end_date"]) != new_end.isoformat():
            _fail("W1D_HTTP_APPLY_NEW_GRADE_END")
        # Old rows still present (ended) and distinct from new IDs.
        old_cert_present = connection.execute(
            text(
                """
                SELECT id FROM erp.recipient_certification_period
                WHERE id = :id AND recipient_id = :rid
                """
            ),
            {"id": old_cert_id, "rid": case.recipient_id},
        ).scalar_one_or_none()
        if old_cert_present is None:
            _fail("W1D_HTTP_APPLY_OLD_CERT_MISSING")
        expected_services = [SERVICE_HOME_CARE, SERVICE_HOME_BATH]
        for cid, exp_svc in zip(ncids, expected_services, strict=True):
            crow = (
                connection.execute(
                    text(
                        """
                    SELECT c.id, c.start_date, c.end_date, st.code AS service_type_code
                    FROM erp.recipient_contract c
                    JOIN erp.service_type st ON st.id = c.service_type_id
                    WHERE c.id = :id AND c.recipient_id = :rid
                    """
                    ),
                    {"id": cid, "rid": case.recipient_id},
                )
                .mappings()
                .one_or_none()
            )
            if crow is None:
                _fail("W1D_HTTP_APPLY_NEW_CONTRACT_ROW_MISSING")
            if crow["service_type_code"] != exp_svc:
                _fail("W1D_HTTP_APPLY_NEW_CONTRACT_SERVICE: " + str(cid))
            if _canonical_date(crow["start_date"]) != new_start.isoformat():
                _fail("W1D_HTTP_APPLY_NEW_CONTRACT_START: " + str(cid))
            if crow["end_date"] is not None:
                _fail("W1D_HTTP_APPLY_NEW_CONTRACT_END_NOT_OPEN: " + str(cid))
        # Unrelated same-recipient false-pass guard: old contract IDs are not
        # accepted as the new list (already checked) and remain distinct rows.
        for old_cid in (old_c1_id, old_c2_id):
            if old_cid in ncids:
                _fail("W1D_HTTP_APPLY_OLD_CONTRACT_AS_NEW")
        db_rno = connection.execute(
            text("SELECT recipient_no FROM erp.recipient WHERE id = :id"),
            {"id": case.recipient_id},
        ).scalar_one()
        db_rno = _assert_recipient_no_exact(db_rno, label="W1D_HTTP_APPLY_DB_RECIPIENT_NO")
        if db_rno != seed_recipient_no or http_body.get("recipient_no") != db_rno:
            _fail("W1D_HTTP_APPLY_RECIPIENT_NO_CHAIN")


def test_w1d_pg_17_preview_hash_canonical_state_drift(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """R7 / R11-P1: canonical preview_hash must STALE on aggregate + row-state drift.

    Dimensions previously omitted from the incomplete serializer (aggregate
    row_version/updated_at_utc, contract replacement/update state) must change
    the authorized hash. For each dimension: re-preview, mutate only that
    dimension, apply original token → CERTIFICATION_TRANSITION_STALE with full
    ledger + complete-audit write-zero vs the post-setup snapshot. No sleeps.
    Collection-only under P2A; live under P2B wrapper.
    """
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
    except Exception:
        _fail("W1D_HARNESS_W1C_DEPENDENCY_MISSING")

    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1d = service_cls(database_session)
        cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
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
            ),
            account,
        )
        grade = w1c.create_grade_period(
            case.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=cert.id,
                grade_code="3",
                start_date=date(2030, 1, 1),
                end_date=date(2030, 12, 31),
            ),
            account,
        )
        contract = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2030, 1, 1),
            ),
            account,
        )
        contract_b = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_BATH,
                start_date=date(2030, 1, 1),
            ),
            account,
        )
        database_session.commit()
        cert_id, grade_id = cert.id, grade.id
        contract_id, contract_b_id = contract.id, contract_b.id

    def _preview_and_token() -> tuple[Any, list[Any]]:
        replacements = _replacement_items(
            schemas, contract_id, date(2031, 1, 1)
        ) + _replacement_items(
            schemas,
            contract_b_id,
            date(2031, 1, 1),
            service_type_code=SERVICE_HOME_BATH,
        )
        preview_request = schemas.CertificationTransitionPreviewRequest(
            new_start_date=date(2031, 1, 1),
            new_end_date=date(2031, 12, 31),
            new_grade_code="4",
            new_grade_start_date=date(2031, 1, 1),
            new_grade_end_date=date(2031, 12, 31),
            replacement_contracts=replacements,
        )
        with session_factory() as database_session:
            service = service_cls(database_session)
            preview = service.preview_certification_transition(
                case.recipient_id, preview_request, account
            )
            database_session.commit()
        return preview, replacements

    def _assert_stale_write_zero(label: str, preview: Any, replacements: list[Any]) -> None:
        with database_engine.connect() as connection:
            fp0, audit0 = _write_zero_pair(connection, case.recipient_id)
        with session_factory() as database_session:
            service = service_cls(database_session)
            try:
                service.apply_certification_transition(
                    case.recipient_id,
                    schemas.CertificationTransitionApplyRequest(
                        preview_token=preview.preview_token,
                        confirmed=True,
                        replacement_contracts=replacements,
                    ),
                    account,
                )
                database_session.commit()
                _fail(label + "_STALE_APPLY_ACCEPTED")
            except Exception as exc:
                database_session.rollback()
                if _error_code(exc) != "CERTIFICATION_TRANSITION_STALE":
                    _fail(label + "_STALE_CODE_MISMATCH: " + _error_code(exc))
        with database_engine.connect() as connection:
            _assert_write_zero_pair(
                connection,
                case.recipient_id,
                fp0,
                audit0,
                label=label,
            )

    # Dimension 1: recipient aggregate row_version + updated_at_utc (previously omitted).
    preview, replacements = _preview_and_token()
    with session_factory() as database_session:
        database_session.execute(
            text(
                """
                UPDATE erp.recipient
                SET row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"id": case.recipient_id},
        )
        database_session.commit()
    _assert_stale_write_zero("W1D_PG17_AGG_RECIPIENT", preview, replacements)

    # Dimension 2: identity aggregate row_version + updated_at_utc.
    preview, replacements = _preview_and_token()
    with session_factory() as database_session:
        database_session.execute(
            text(
                """
                UPDATE erp.recipient_certification_identity
                SET row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE recipient_id = :id
                """
            ),
            {"id": case.recipient_id},
        )
        database_session.commit()
    _assert_stale_write_zero("W1D_PG17_AGG_IDENTITY", preview, replacements)

    # Dimension 3: LTC contract replacement FK + row_version/updated_at (row-state).
    preview, replacements = _preview_and_token()
    with session_factory() as database_session:
        # Point replacement_contract_id at the sibling active LTC row (same recipient).
        database_session.execute(
            text(
                """
                UPDATE erp.recipient_contract
                SET replacement_contract_id = :other,
                    row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"id": contract_id, "other": contract_b_id},
        )
        database_session.commit()
    _assert_stale_write_zero("W1D_PG17_CONTRACT_REPLACEMENT_STATE", preview, replacements)

    # Restore contract replacement FK for harness hygiene.
    with session_factory() as database_session:
        database_session.execute(
            text(
                """
                UPDATE erp.recipient_contract
                SET replacement_contract_id = NULL,
                    row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"id": contract_id},
        )
        database_session.commit()

    # Dimension 4: cert-period updated_at_utc + row_version (replacement-adjacent state).
    preview, replacements = _preview_and_token()
    with session_factory() as database_session:
        database_session.execute(
            text(
                """
                UPDATE erp.recipient_certification_period
                SET row_version = row_version + 1,
                    updated_at_utc = clock_timestamp()
                WHERE id = :id
                """
            ),
            {"id": cert_id},
        )
        database_session.commit()
    _assert_stale_write_zero("W1D_PG17_CERT_UPDATED_STATE", preview, replacements)

    del grade_id  # seeded; unused beyond setup integrity


def test_w1d_pg_18_repeat_transition_preserves_ended_history(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    """A second transition targets only periods effective on proposed_end.

    The first transition's already-ended predecessor rows are historical
    records. A later transition must exclude them from preview/apply and leave
    every persisted byte unchanged while ending only the first replacement
    rows and appending one new transition audit event.
    """
    _require_w1d_catalog(database_engine)
    case = _seed_case(session_factory)
    service_cls = _load_service()
    schemas = _load_schemas()
    account = _current_account(case)

    try:
        from app.domains.w1c.schemas import (
            CertificationIdentityCreateRequest,
            CertificationPeriodCreateRequest,
            GradePeriodCreateRequest,
        )
        from app.domains.w1c.service import W1CService
    except Exception:
        _fail("W1D_HARNESS_W1C_DEPENDENCY_MISSING")

    with session_factory() as database_session:
        w1c = W1CService(database_session)
        w1d = service_cls(database_session)
        cert_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
        w1c.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(certification_number=cert_number),
            account,
        )
        original_cert = w1c.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                start_date=date(2030, 1, 1),
                end_date=date(2033, 12, 31),
            ),
            account,
        )
        original_grade = w1c.create_grade_period(
            case.recipient_id,
            GradePeriodCreateRequest(
                certification_period_id=original_cert.id,
                grade_code="3",
                start_date=date(2030, 1, 1),
                end_date=date(2033, 12, 31),
            ),
            account,
        )
        original_contract = w1d.create_contract(
            case.recipient_id,
            schemas.ContractCreateRequest(
                service_type_code=SERVICE_HOME_CARE,
                start_date=date(2030, 1, 1),
            ),
            account,
        )
        database_session.commit()
        original_cert_id = original_cert.id
        original_grade_id = original_grade.id
        original_contract_id = original_contract.id

    first_start = date(2031, 1, 1)
    first_end = date(2032, 12, 31)
    first_replacements = _replacement_items(schemas, original_contract_id, first_start)
    first_request = schemas.CertificationTransitionPreviewRequest(
        new_start_date=first_start,
        new_end_date=first_end,
        new_grade_code="4",
        new_grade_start_date=first_start,
        new_grade_end_date=first_end,
        replacement_contracts=first_replacements,
    )
    with session_factory() as database_session:
        service = service_cls(database_session)
        first_preview = service.preview_certification_transition(
            case.recipient_id, first_request, account
        )
        if list(first_preview.affected_certification_period_ids) != [original_cert_id]:
            _fail("W1D_PG18_FIRST_PREVIEW_CERT_IDS")
        if list(first_preview.affected_grade_period_ids) != [original_grade_id]:
            _fail("W1D_PG18_FIRST_PREVIEW_GRADE_IDS")
        if list(first_preview.affected_contract_ids) != [original_contract_id]:
            _fail("W1D_PG18_FIRST_PREVIEW_CONTRACT_IDS")
        first_applied = service.apply_certification_transition(
            case.recipient_id,
            schemas.CertificationTransitionApplyRequest(
                preview_token=first_preview.preview_token,
                confirmed=True,
                replacement_contracts=first_replacements,
            ),
            account,
        )
        database_session.commit()

    first_cert_id = first_applied.new_certification_period_id
    first_grade_id = first_applied.new_grade_period_id
    if type(first_applied.new_contract_ids) is not list or len(first_applied.new_contract_ids) != 1:
        _fail("W1D_PG18_FIRST_NEW_CONTRACT_IDS")
    first_contract_id = first_applied.new_contract_ids[0]
    if any(
        type(value) is not int or value <= 0
        for value in (first_cert_id, first_grade_id, first_contract_id)
    ):
        _fail("W1D_PG18_FIRST_NEW_IDS_TYPE")

    with database_engine.connect() as connection:
        after_first = _full_ledger_state(connection, case.recipient_id)

    second_start = date(2032, 1, 1)
    second_end = date(2034, 12, 31)
    second_proposed_end = date(2031, 12, 31)
    second_replacements = _replacement_items(schemas, first_contract_id, second_start)
    second_request = schemas.CertificationTransitionPreviewRequest(
        new_start_date=second_start,
        new_end_date=second_end,
        new_grade_code="2",
        new_grade_start_date=second_start,
        new_grade_end_date=second_end,
        replacement_contracts=second_replacements,
    )
    with session_factory() as database_session:
        service = service_cls(database_session)
        second_preview = service.preview_certification_transition(
            case.recipient_id, second_request, account
        )
        if second_preview.proposed_end_date != second_proposed_end:
            _fail("W1D_PG18_SECOND_PROPOSED_END")
        if list(second_preview.affected_certification_period_ids) != [first_cert_id]:
            _fail("W1D_PG18_SECOND_PREVIEW_CERT_IDS")
        if list(second_preview.affected_grade_period_ids) != [first_grade_id]:
            _fail("W1D_PG18_SECOND_PREVIEW_GRADE_IDS")
        if list(second_preview.affected_contract_ids) != [first_contract_id]:
            _fail("W1D_PG18_SECOND_PREVIEW_CONTRACT_IDS")
        second_applied = service.apply_certification_transition(
            case.recipient_id,
            schemas.CertificationTransitionApplyRequest(
                preview_token=second_preview.preview_token,
                confirmed=True,
                replacement_contracts=second_replacements,
            ),
            account,
        )
        database_session.commit()

    if list(second_applied.ended_certification_period_ids) != [first_cert_id]:
        _fail("W1D_PG18_SECOND_ENDED_CERT_IDS")
    if list(second_applied.ended_grade_period_ids) != [first_grade_id]:
        _fail("W1D_PG18_SECOND_ENDED_GRADE_IDS")
    if list(second_applied.ended_contract_ids) != [first_contract_id]:
        _fail("W1D_PG18_SECOND_ENDED_CONTRACT_IDS")
    second_cert_id = second_applied.new_certification_period_id
    second_grade_id = second_applied.new_grade_period_id
    if (
        type(second_applied.new_contract_ids) is not list
        or len(second_applied.new_contract_ids) != 1
    ):
        _fail("W1D_PG18_SECOND_NEW_CONTRACT_IDS")
    second_contract_id = second_applied.new_contract_ids[0]
    if any(
        type(value) is not int or value <= 0
        for value in (second_cert_id, second_grade_id, second_contract_id)
    ):
        _fail("W1D_PG18_SECOND_NEW_IDS_TYPE")

    with database_engine.connect() as connection:
        after_second = _full_ledger_state(connection, case.recipient_id)
        service_type_id = connection.execute(
            text("SELECT id FROM erp.service_type WHERE code = :code LIMIT 1"),
            {"code": SERVICE_HOME_CARE},
        ).scalar_one()

    _assert_rows_exact_equal(
        after_first["recipient"], after_second["recipient"], label="PG18_RECIPIENT"
    )
    _assert_rows_exact_equal(
        after_first["identity"], after_second["identity"], label="PG18_IDENTITY"
    )
    _assert_rows_exact_equal(after_first["counter"], after_second["counter"], label="PG18_COUNTER")

    before_cert = _index_rows_by_id(after_first["cert"], label="PG18_CERT_BEFORE")
    after_cert = _index_rows_by_id(after_second["cert"], label="PG18_CERT_AFTER")
    before_grade = _index_rows_by_id(after_first["grade"], label="PG18_GRADE_BEFORE")
    after_grade = _index_rows_by_id(after_second["grade"], label="PG18_GRADE_AFTER")
    before_contract = _index_rows_by_id(after_first["contract"], label="PG18_CONTRACT_BEFORE")
    after_contract = _index_rows_by_id(after_second["contract"], label="PG18_CONTRACT_AFTER")
    if set(after_cert) != set(before_cert) | {second_cert_id}:
        _fail("W1D_PG18_SECOND_CERT_ID_SET")
    if set(after_grade) != set(before_grade) | {second_grade_id}:
        _fail("W1D_PG18_SECOND_GRADE_ID_SET")
    if set(after_contract) != set(before_contract) | {second_contract_id}:
        _fail("W1D_PG18_SECOND_CONTRACT_ID_SET")

    for before_rows, after_rows, historical_id, label in (
        (before_cert, after_cert, original_cert_id, "CERT"),
        (before_grade, after_grade, original_grade_id, "GRADE"),
        (before_contract, after_contract, original_contract_id, "CONTRACT"),
    ):
        if _canon_row(before_rows[historical_id]) != _canon_row(after_rows[historical_id]):
            _fail(f"W1D_PG18_HISTORICAL_{label}_MUTATED")

    before_audit = after_first["audit"]
    after_audit = after_second["audit"]
    if len(after_audit) != len(before_audit) + 1:
        _fail("W1D_PG18_AUDIT_DELTA")
    if _canonical_audit_rows_json(before_audit) != _canonical_audit_rows_json(after_audit[:-1]):
        _fail("W1D_PG18_AUDIT_PREFIX_MUTATED")
    appended_audit = after_audit[-1]
    if appended_audit.get("action_code") != "CERTIFICATION_TRANSITION_APPLY":
        _fail("W1D_PG18_AUDIT_ACTION")
    if appended_audit.get("entity_type") != "RECIPIENT":
        _fail("W1D_PG18_AUDIT_ENTITY_TYPE")
    if (
        _strict_nonbool_int(appended_audit.get("entity_pk"), label="W1D_PG18_AUDIT_ENTITY_PK")
        != case.recipient_id
    ):
        _fail("W1D_PG18_AUDIT_ENTITY_PK")
    if str(appended_audit.get("request_id")) != str(second_applied.audit_correlation_id):
        _fail("W1D_PG18_AUDIT_CORRELATION")
    sealed_apply_ts = _normalize_utc_timestamp(
        appended_audit.get("occurred_at_utc"), label="W1D_PG18_APPLY_TS"
    )

    _assert_ended_row_exact_projection(
        before_cert[first_cert_id],
        after_cert[first_cert_id],
        label="W1D_PG18_FIRST_CERT",
        expected_keys=_W1C_CERT_ROW_KEYS,
        period_key="certification_period",
        proposed_end=second_proposed_end,
        account_id=case.account_id,
        sealed_apply_ts=sealed_apply_ts,
    )
    _assert_ended_row_exact_projection(
        before_grade[first_grade_id],
        after_grade[first_grade_id],
        label="W1D_PG18_FIRST_GRADE",
        expected_keys=_W1C_GRADE_ROW_KEYS,
        period_key="grade_period",
        proposed_end=second_proposed_end,
        account_id=case.account_id,
        sealed_apply_ts=sealed_apply_ts,
    )
    _assert_ended_row_exact_projection(
        before_contract[first_contract_id],
        after_contract[first_contract_id],
        label="W1D_PG18_FIRST_CONTRACT",
        expected_keys=_W1D_CONTRACT_ROW_KEYS,
        period_key="contract_period",
        proposed_end=second_proposed_end,
        account_id=case.account_id,
        sealed_apply_ts=sealed_apply_ts,
        expected_end_reason_text=None,
        end_reason_key="end_reason_text",
    )
    _assert_new_cert_row_complete(
        after_cert[second_cert_id],
        new_cert_id=second_cert_id,
        recipient_id=case.recipient_id,
        new_start=second_start,
        new_end=second_end,
        account_id=case.account_id,
        sealed_apply_ts=sealed_apply_ts,
    )
    _assert_new_grade_row_complete(
        after_grade[second_grade_id],
        new_grade_id=second_grade_id,
        new_cert_id=second_cert_id,
        recipient_id=case.recipient_id,
        new_start=second_start,
        new_end=second_end,
        new_grade_code="2",
        account_id=case.account_id,
        sealed_apply_ts=sealed_apply_ts,
    )
    _assert_new_contract_row_complete(
        after_contract[second_contract_id],
        new_contract_id=second_contract_id,
        recipient_id=case.recipient_id,
        service_type_id=service_type_id,
        new_start=second_start,
        account_id=case.account_id,
        signer_name=None,
        signer_relationship_text=None,
        signer_phone=None,
        end_reason_text=None,
        service_start_date=None,
        sealed_apply_ts=sealed_apply_ts,
    )
