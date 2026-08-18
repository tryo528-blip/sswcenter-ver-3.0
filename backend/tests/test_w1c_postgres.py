from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import CurrentAccount
from app.core.security import PinProtector
from app.db.models import AccountPermission, Recipient, Staff, UserAccount
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w1c.schemas import (
    ApprovalAmountPeriodCreateRequest,
    ApprovalAmountPeriodReplacementRequest,
    BenefitCode,
    BenefitPeriodCreateRequest,
    BenefitPeriodReplacementRequest,
    CertificationIdentityCreateRequest,
    CertificationPeriodCreateRequest,
    CertificationPeriodReplacementRequest,
    GradeCode,
)
from app.domains.w1c.service import W1CService

pytestmark = pytest.mark.skipif(
    os.environ.get("SSWCENTER_W1C_REAL_PG") != "1",
    reason="requires the isolated W1C PostgreSQL harness",
)


@dataclass(frozen=True)
class W1CCase:
    account: CurrentAccount
    recipient_id: int
    other_recipient_id: int


@dataclass(frozen=True)
class W1CAuthenticatedCase:
    account_id: int
    recipient_id: int
    pin: str


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    database_url = os.environ["SSWCENTER_DATABASE_URL"]
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
        pytest.fail("W1C_HARNESS_SYNTHETIC_PIN_SPACE_EXHAUSTED", pytrace=False)
    return f"{staff_id:06d}"


def _seed_case(factory: sessionmaker[Session]) -> W1CCase:
    label = uuid4().hex
    with factory() as database_session:
        staff = Staff(
            name=f"W1C STAFF {label}",
            birth_date=date(1990, 1, 1),
            sex_code="TEST",
            display_name=f"W1C {label}",
            row_version=1,
        )
        database_session.add(staff)
        database_session.flush()
        account = UserAccount(
            staff_id=staff.id,
            account_code=f"W1C_{label}",
            display_name=f"W1C {label}",
            role_code="ADMIN",
            pin_hash="w1c-test-pin-hash",
            pin_lookup_hmac=hashlib.sha256(label.encode()).digest(),
            pin_key_version=1,
            row_version=1,
        )
        database_session.add(account)
        database_session.flush()
        recipients = [
            Recipient(
                name=f"W1C RECIPIENT {label} {index}",
                birth_date=date(1950, 1, index),
                sex_code="TEST",
                mobile_phone=f"010-7000-{index:04d}",
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                row_version=1,
            )
            for index in (1, 2)
        ]
        database_session.add_all(recipients)
        database_session.commit()
        return W1CCase(
            account=CurrentAccount(account.id, account.display_name, account.role_code),
            recipient_id=recipients[0].id,
            other_recipient_id=recipients[1].id,
        )


def _seed_authenticated_case(
    factory: sessionmaker[Session],
) -> W1CAuthenticatedCase:
    label = uuid4().hex
    protector = PinProtector(
        os.environ["SSWCENTER_PIN_PEPPER"],
        os.environ["SSWCENTER_PIN_LOOKUP_KEY"],
    )
    with factory() as database_session:
        staff = Staff(
            name=f"W1C AUTH STAFF {label}",
            birth_date=date(1990, 1, 1),
            sex_code="TEST",
            display_name=f"W1C AUTH {label}",
            row_version=1,
        )
        database_session.add(staff)
        database_session.flush()
        pin = _synthetic_pin_for_staff_id(staff.id)
        account = UserAccount(
            staff_id=staff.id,
            account_code=f"W1C_AUTH_{label}",
            display_name=f"W1C AUTH {label}",
            role_code="USER",
            pin_hash=protector.hash_pin(pin),
            pin_lookup_hmac=protector.lookup_hmac(pin),
            pin_key_version=1,
            row_version=1,
        )
        database_session.add(account)
        database_session.flush()
        recipient = Recipient(
            name=f"W1C AUTH RECIPIENT {label}",
            birth_date=date(1950, 1, 1),
            sex_code="TEST",
            mobile_phone="010-7000-9999",
            created_by_account_id=account.id,
            updated_by_account_id=account.id,
            row_version=1,
        )
        database_session.add(recipient)
        database_session.commit()
        return W1CAuthenticatedCase(
            account_id=account.id,
            recipient_id=recipient.id,
            pin=pin,
        )


def _grant_recipient_permission(
    factory: sessionmaker[Session],
    case: W1CAuthenticatedCase,
    permission_code: str,
) -> None:
    with factory() as database_session:
        database_session.add(
            AccountPermission(
                account_id=case.account_id,
                permission_code=permission_code,
                granted_by_account_id=case.account_id,
            )
        )
        database_session.commit()


def _assert_domain_error(
    expected_code: str,
    action: object,
) -> RecipientDomainError:
    assert callable(action)
    with pytest.raises(RecipientDomainError) as captured:
        action()
    assert captured.value.code == expected_code
    return captured.value


def _seed_certification_period(
    factory: sessionmaker[Session],
) -> tuple[W1CCase, int]:
    case = _seed_case(factory)
    certification_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
    with factory() as database_session:
        service = W1CService(database_session)
        service.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(
                certification_number=certification_number,
            ),
            case.account,
        )
        certification = service.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                grade_code=GradeCode.GRADE_3,
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 30),
            ),
            case.account,
        )
    return case, certification.id


def _wait_for_lock_or_completion(
    database_engine: Engine,
    application_name: str,
    future: Future[str | None],
) -> None:
    deadline = time.monotonic() + 5
    while not future.done():
        with database_engine.connect() as monitor:
            waiting_for_lock = bool(
                monitor.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_stat_activity
                            WHERE application_name = :application_name
                              AND wait_event_type = 'Lock'
                        )
                        """
                    ),
                    {"application_name": application_name},
                ).scalar_one()
            )
        if waiting_for_lock:
            return
        if time.monotonic() >= deadline:
            pytest.fail(f"{application_name} neither completed nor waited for a lock")
        time.sleep(0.01)


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def test_w1c_identity_certification_and_grade_invariants(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    case = _seed_case(session_factory)
    with session_factory() as database_session:
        service = W1CService(database_session)
        identity = service.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(certification_number=" l1234567890-100 "),
            case.account,
        )
        assert identity.certification_number == "L1234567890"
        assert (
            service.create_identity(
                case.recipient_id,
                CertificationIdentityCreateRequest(certification_number="L1234567890-101"),
                case.account,
            )
            == identity
        )
        _assert_domain_error(
            "RECIPIENT_CERTIFICATION_NUMBER_FIXED",
            lambda: service.create_identity(
                case.recipient_id,
                CertificationIdentityCreateRequest(certification_number="L9999999999"),
                case.account,
            ),
        )
        _assert_domain_error(
            "CERTIFICATION_NUMBER_IN_USE",
            lambda: service.create_identity(
                case.other_recipient_id,
                CertificationIdentityCreateRequest(certification_number="l1234567890-102"),
                case.account,
            ),
        )

        july = service.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                grade_code=GradeCode.GRADE_3,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
            ),
            case.account,
        )
        assert july.grade_code.value == "3"
        _assert_domain_error(
            "CERTIFICATION_PERIOD_CONFLICT",
            lambda: service.create_certification_period(
                case.recipient_id,
                CertificationPeriodCreateRequest(
                    grade_code=GradeCode.GRADE_4,
                    start_date=date(2026, 7, 31),
                    end_date=date(2026, 8, 15),
                ),
                case.account,
            ),
        )
        august = service.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                grade_code=GradeCode.GRADE_4,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
            ),
            case.account,
        )
        assert august.start_date == july.end_date + timedelta(days=1)
        assert august.grade_code.value == "4"

    with database_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT grade_code, start_date, end_date
                FROM erp.recipient_certification_period
                WHERE id = :period_id
                """
                ),
                {"period_id": july.id},
            )
            .mappings()
            .one()
        )
        assert dict(row) == {
            "grade_code": "3",
            "start_date": date(2026, 7, 1),
            "end_date": date(2026, 7, 31),
        }
        connection.rollback()

        for statement, expected_constraint in (
            (
                """
                UPDATE erp.recipient_certification_identity
                SET certification_number = 'L9999999999'
                WHERE recipient_id = :recipient_id
                """,
                "ck_recipient_certification_identity_immutable",
            ),
            (
                """
                UPDATE erp.recipient_certification_identity
                SET recipient_id = :other_recipient_id
                WHERE recipient_id = :recipient_id
                """,
                "ck_recipient_certification_identity_immutable",
            ),
            (
                """
                UPDATE erp.recipient_certification_period
                SET grade_code = '9'
                WHERE id = :period_id
                """,
                "ck_recipient_certification_period_grade_code",
            ),
        ):
            transaction = connection.begin()
            try:
                with pytest.raises(IntegrityError) as captured:
                    connection.execute(
                        text(statement),
                        {
                            "recipient_id": case.recipient_id,
                            "other_recipient_id": case.other_recipient_id,
                            "period_id": july.id,
                        },
                    )
                assert _constraint_name(captured.value) == expected_constraint
            finally:
                transaction.rollback()


def test_w1c_certification_writes_are_serialized(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    case = _seed_case(session_factory)
    certification_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
    with session_factory() as database_session:
        W1CService(database_session).create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(
                certification_number=certification_number,
            ),
            case.account,
        )

    barrier = threading.Barrier(2)
    insert = text(
        """
        INSERT INTO erp.recipient_certification_period (
            recipient_id,
            grade_code,
            start_date,
            end_date,
            created_by_account_id,
            updated_by_account_id,
            row_version
        )
        VALUES (
            :recipient_id,
            :grade_code,
            DATE '2026-09-01',
            DATE '2026-09-30',
            :account_id,
            :account_id,
            1
        )
        """
    )

    def worker(grade_code: str) -> str:
        with database_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                barrier.wait(timeout=5)
                connection.execute(
                    insert,
                    {
                        "recipient_id": case.recipient_id,
                        "grade_code": grade_code,
                        "account_id": case.account.id,
                    },
                )
                transaction.commit()
                return "ok"
            except IntegrityError as error:
                transaction.rollback()
                return str(_constraint_name(error))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(worker, ("2", "3")))

    assert outcomes == ["ex_recipient_certification_period", "ok"]
    with database_engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                SELECT grade_code
                FROM erp.recipient_certification_period
                WHERE recipient_id = :recipient_id
                  AND start_date = DATE '2026-09-01'
                  AND invalidated_at_utc IS NULL
                """
                ),
                {"recipient_id": case.recipient_id},
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0] in {"2", "3"}


def test_w1c_benefit_and_approval_ledgers_are_independent(
    session_factory: sessionmaker[Session],
) -> None:
    case = _seed_case(session_factory)
    with session_factory() as database_session:
        service = W1CService(database_session)
        assert service.list_benefit_periods(case.recipient_id).items == []

        benefit = service.create_benefit_period(
            case.recipient_id,
            BenefitPeriodCreateRequest(
                benefit_code=BenefitCode.MEDICAL_6,
                start_text="표시 전용 / 날짜 아님",
            ),
            case.account,
        )
        assert benefit.start_text == "표시 전용 / 날짜 아님"
        assert benefit.benefit_code is BenefitCode.MEDICAL_6

        _assert_domain_error(
            "BENEFIT_PERIOD_CONFLICT",
            lambda: service.create_benefit_period(
                case.recipient_id,
                BenefitPeriodCreateRequest(
                    benefit_code=BenefitCode.MEDICAL_9,
                    start_text="다른 표시값",
                ),
                case.account,
            ),
        )

        replacement = service.replace_benefit_period(
            case.recipient_id,
            benefit.id,
            BenefitPeriodReplacementRequest(
                benefit_code=BenefitCode.BASIC_LIVELIHOOD,
                start_text="",
                expected_row_version=benefit.row_version,
            ),
            case.account,
        )
        assert replacement.original.invalidated_at_utc is not None
        assert replacement.replacement.benefit_code is BenefitCode.BASIC_LIVELIHOOD
        assert replacement.replacement.start_text == ""
        _assert_domain_error(
            "ROW_VERSION_CONFLICT",
            lambda: service.replace_benefit_period(
                case.recipient_id,
                benefit.id,
                BenefitPeriodReplacementRequest(
                    benefit_code=BenefitCode.GENERAL,
                    start_text="stale",
                    expected_row_version=benefit.row_version,
                ),
                case.account,
            ),
        )

        first_approval = service.create_approval_amount_period(
            case.recipient_id,
            ApprovalAmountPeriodCreateRequest(
                amount_krw=1_000_000,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            ),
            case.account,
        )
        second_approval = service.create_approval_amount_period(
            case.recipient_id,
            ApprovalAmountPeriodCreateRequest(
                amount_krw=2_000_000,
                start_date=date(2026, 2, 1),
                end_date=None,
            ),
            case.account,
        )
        assert first_approval.amount_krw == 1_000_000
        assert second_approval.amount_krw == 2_000_000
        assert len(service.list_approval_amount_periods(case.recipient_id).items) == 2


def test_w1c_replacements_audit_original_and_new_facts(
    session_factory: sessionmaker[Session],
) -> None:
    case = _seed_case(session_factory)
    request_id = uuid4()
    certification_number = f"L{int(uuid4().hex[:10], 16) % 10_000_000_000:010d}"
    with session_factory() as database_session:
        service = W1CService(database_session, request_id=request_id)
        service.create_identity(
            case.recipient_id,
            CertificationIdentityCreateRequest(
                certification_number=certification_number,
            ),
            case.account,
        )
        certification = service.create_certification_period(
            case.recipient_id,
            CertificationPeriodCreateRequest(
                grade_code=GradeCode.GRADE_2,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
            ),
            case.account,
        )
        benefit = service.create_benefit_period(
            case.recipient_id,
            BenefitPeriodCreateRequest(
                benefit_code=BenefitCode.MEDICAL_6,
                start_text="old",
            ),
            case.account,
        )
        approval = service.create_approval_amount_period(
            case.recipient_id,
            ApprovalAmountPeriodCreateRequest(
                amount_krw=1,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            ),
            case.account,
        )

        certification_replacement = service.replace_certification_period(
            case.recipient_id,
            certification.id,
            CertificationPeriodReplacementRequest(
                grade_code=GradeCode.GRADE_3,
                start_date=certification.start_date,
                end_date=certification.end_date,
                expected_row_version=certification.row_version,
            ),
            case.account,
        )
        benefit_replacement = service.replace_benefit_period(
            case.recipient_id,
            benefit.id,
            BenefitPeriodReplacementRequest(
                benefit_code=BenefitCode.BASIC_LIVELIHOOD,
                start_text="new",
                expected_row_version=benefit.row_version,
            ),
            case.account,
        )
        approval_replacement = service.replace_approval_amount_period(
            case.recipient_id,
            approval.id,
            ApprovalAmountPeriodReplacementRequest(
                amount_krw=9_223_372_036_854_775_807,
                start_date=approval.start_date,
                end_date=approval.end_date,
                expected_row_version=approval.row_version,
            ),
            case.account,
        )

        audit_rows = (
            database_session.execute(
                text(
                    """
                    SELECT action_code, entity_pk, before_json, after_json,
                           occurred_at_utc, request_id
                    FROM erp.audit_event
                    WHERE request_id = :request_id
                      AND action_code LIKE '%REPLACE%'
                    """
                ),
                {"request_id": request_id},
            )
            .mappings()
            .all()
        )
        rows_by_action = {str(row["action_code"]): row for row in audit_rows}
        expected_pairs = (
            (
                "RECIPIENT_CERTIFICATION_PERIOD_REPLACE",
                certification_replacement.original.id,
                "RECIPIENT_CERTIFICATION_PERIOD_REPLACEMENT_CREATE",
                certification_replacement.replacement.id,
            ),
            (
                "RECIPIENT_BENEFIT_PERIOD_REPLACE",
                benefit_replacement.original.id,
                "RECIPIENT_BENEFIT_PERIOD_REPLACEMENT_CREATE",
                benefit_replacement.replacement.id,
            ),
            (
                "RECIPIENT_APPROVAL_AMOUNT_PERIOD_REPLACE",
                approval_replacement.original.id,
                "RECIPIENT_APPROVAL_AMOUNT_PERIOD_REPLACEMENT_CREATE",
                approval_replacement.replacement.id,
            ),
        )
        for old_action, old_id, new_action, new_id in expected_pairs:
            original_audit = rows_by_action[old_action]
            replacement_audit = rows_by_action[new_action]
            assert int(original_audit["entity_pk"]) == old_id
            assert original_audit["before_json"] is not None
            assert int(replacement_audit["entity_pk"]) == new_id
            assert replacement_audit["before_json"] is None
            assert int(replacement_audit["after_json"]["id"]) == new_id
            assert original_audit["occurred_at_utc"] == replacement_audit["occurred_at_utc"]
            assert original_audit["request_id"] == replacement_audit["request_id"] == request_id

        assert certification_replacement.replacement.grade_code.value == "3"
        assert benefit_replacement.replacement.start_text == "new"
        assert approval_replacement.replacement.amount_krw == 9_223_372_036_854_775_807


def test_w1c_catalog_and_http_error_contracts(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    with database_engine.connect() as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'erp'
                      AND table_name LIKE 'recipient_%'
                    """
                )
            )
        }
        assert {
            "recipient_certification_identity",
            "recipient_certification_period",
            "recipient_benefit_period",
            "recipient_local_approval_amount_period",
        } <= table_names
        assert "recipient_grade_period" not in table_names

        columns = {
            (str(row.table_name), str(row.column_name))
            for row in connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'erp'
                      AND table_name = ANY(:tables)
                    """
                ),
                {
                    "tables": [
                        "recipient_certification_identity",
                        "recipient_certification_period",
                        "recipient_benefit_period",
                        "recipient_local_approval_amount_period",
                    ]
                },
            )
        }
        assert ("recipient_certification_period", "grade_code") in columns
        assert ("recipient_benefit_period", "start_text") in columns
        assert {
            ("recipient_benefit_period", "start_date"),
            ("recipient_benefit_period", "end_date"),
            ("recipient_benefit_period", "benefit_period"),
        }.isdisjoint(columns)

        constraints = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE connamespace = 'erp'::regnamespace
                    """
                )
            )
        }
        assert {
            "ex_recipient_certification_period",
            "ck_recipient_certification_period_grade_code",
            "ex_recipient_local_approval_amount_period",
        } <= constraints
        assert "ex_recipient_grade_period" not in constraints
        assert "ex_recipient_benefit_period" not in constraints

        indexes = {
            row[0]
            for row in connection.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'erp'
                    """
                )
            )
        }
        assert "uq_recipient_benefit_period_active_recipient" in indexes

    case = _seed_case(session_factory)
    from app.api.dependencies import (
        get_db_session,
        require_recipient_manage,
        require_recipient_view,
    )
    from app.main import app

    def override_database_session() -> object:
        database_session = session_factory()
        try:
            yield database_session
        finally:
            database_session.rollback()
            database_session.close()

    app.dependency_overrides[get_db_session] = override_database_session
    app.dependency_overrides[require_recipient_view] = lambda: case.account
    app.dependency_overrides[require_recipient_manage] = lambda: case.account
    try:
        with TestClient(app) as client:
            identity = client.post(
                f"/api/v1/recipients/{case.recipient_id}/certification-identity",
                json={"certification_number": "l5555555555-100"},
            )
            assert identity.status_code == 201
            assert identity.json()["certification_number"] == "L5555555555"

            created = client.post(
                f"/api/v1/recipients/{case.recipient_id}/certification-periods",
                json={
                    "grade_code": "3",
                    "start_date": "2026-03-01",
                    "end_date": "2026-03-31",
                },
            )
            assert created.status_code == 201
            assert created.json()["grade_code"] == "3"
            conflict = client.post(
                f"/api/v1/recipients/{case.recipient_id}/certification-periods",
                json={
                    "grade_code": "4",
                    "start_date": "2026-03-31",
                    "end_date": "2026-04-30",
                },
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "CERTIFICATION_PERIOD_CONFLICT"

            empty_benefits = client.get(f"/api/v1/recipients/{case.recipient_id}/benefit-periods")
            assert empty_benefits.status_code == 200
            assert empty_benefits.json() == {"items": []}

            retired_grade = client.get(f"/api/v1/recipients/{case.recipient_id}/grade-periods")
            retired_effective = client.get(
                f"/api/v1/recipients/{case.recipient_id}/benefit-periods/effective",
                params={"on_date": "2026-03-15"},
            )
            assert retired_grade.status_code == 404
            assert retired_effective.status_code == 404

            invalid_grade = client.post(
                f"/api/v1/recipients/{case.recipient_id}/certification-periods",
                json={
                    "grade_code": "COGNITIVE_SUPPORT",
                    "start_date": "2026-05-01",
                    "end_date": "2026-05-31",
                },
            )
            assert invalid_grade.status_code == 422
            assert invalid_grade.json()["error"]["code"] == "VALIDATION_ERROR"

            for invalid_amount in (
                -1,
                9_223_372_036_854_775_808,
                "1000",
                1000.5,
                True,
            ):
                invalid_approval = client.post(
                    f"/api/v1/recipients/{case.recipient_id}/approval-amount-periods",
                    json={
                        "amount_krw": invalid_amount,
                        "start_date": "2026-03-01",
                        "end_date": None,
                    },
                )
                assert invalid_approval.status_code == 422
                assert invalid_approval.json()["error"]["code"] == "VALIDATION_ERROR"

            exact_bigint_approval = client.post(
                f"/api/v1/recipients/{case.recipient_id}/approval-amount-periods",
                json={
                    "amount_krw": 9_223_372_036_854_775_807,
                    "start_date": "2026-05-01",
                    "end_date": None,
                },
            )
            assert exact_bigint_approval.status_code == 201
            assert '"amount_krw":9223372036854775807' in exact_bigint_approval.text
            unsafe = str(conflict.json()).lower()
            assert "constraint" not in unsafe
            assert "sqlalchemy" not in unsafe
            assert "psycopg" not in unsafe
    finally:
        app.dependency_overrides.clear()


def test_w1c_real_app_role_auth_permission_and_csrf_gate(
    session_factory: sessionmaker[Session],
    database_engine: Engine,
) -> None:
    assert os.environ["SSWCENTER_DATABASE_URL"] == os.environ["SSWCENTER_APP_DATABASE_URL"]
    with database_engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == "erp_app"
        privileges = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        current_user,
                        'erp.recipient_certification_identity',
                        'SELECT'
                    ),
                    has_table_privilege(
                        current_user,
                        'erp.recipient_certification_identity',
                        'INSERT'
                    ),
                    has_table_privilege(
                        current_user,
                        'erp.recipient_certification_identity',
                        'UPDATE'
                    ),
                    has_table_privilege(
                        current_user,
                        'erp.recipient_certification_identity',
                        'DELETE'
                    ),
                    has_table_privilege(
                        current_user,
                        'erp.recipient_certification_identity',
                        'TRUNCATE'
                    )
                """
            )
        ).one()
        assert tuple(privileges) == (True, True, True, False, False)

    case = _seed_authenticated_case(session_factory)
    from app.main import app

    assert app.dependency_overrides == {}
    benefits_path = f"/api/v1/recipients/{case.recipient_id}/benefit-periods"
    identity_path = f"/api/v1/recipients/{case.recipient_id}/certification-identity"
    identity_payload = {"certification_number": "l6666666666-100"}

    with TestClient(app) as client:
        unauthenticated = client.get(benefits_path)
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

        login_response = client.post("/api/auth/login", json={"pin": case.pin})
        assert login_response.status_code == 200
        assert login_response.json()["account"]["role_code"] == "USER"

        no_permission = client.get(benefits_path)
        assert no_permission.status_code == 403
        assert no_permission.json()["error"]["code"] == "PERMISSION_REQUIRED"

        _grant_recipient_permission(session_factory, case, "RECIPIENT_VIEW")
        view_allowed = client.get(benefits_path)
        assert view_allowed.status_code == 200
        assert view_allowed.json() == {"items": []}

        missing_csrf = client.post(identity_path, json=identity_payload)
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "CSRF_REQUIRED"

        csrf_cookie = client.cookies.get("sswcenter_csrf")
        assert csrf_cookie is not None
        view_cannot_manage = client.post(
            identity_path,
            json=identity_payload,
            headers={"X-CSRF-Token": csrf_cookie},
        )
        assert view_cannot_manage.status_code == 403
        assert view_cannot_manage.json()["error"]["code"] == "PERMISSION_REQUIRED"

        _grant_recipient_permission(session_factory, case, "RECIPIENT_MANAGE")
        created = client.post(
            identity_path,
            json=identity_payload,
            headers={"X-CSRF-Token": csrf_cookie},
        )
        assert created.status_code == 201
        assert created.json()["certification_number"] == "L6666666666"

    with database_engine.connect() as connection:
        persisted_owner = connection.execute(
            text(
                """
                SELECT recipient_id
                FROM erp.recipient_certification_identity
                WHERE certification_number = 'L6666666666'
                """
            )
        ).scalar_one()
        assert persisted_owner == case.recipient_id
