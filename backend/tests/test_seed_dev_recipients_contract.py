from __future__ import annotations

import inspect
import os
import re
from collections import Counter
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from app.core.auth import BootstrapInput, CurrentAccount, bootstrap_installation
from app.core.settings import Environment, get_settings
from app.db.models import (
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationIdentity,
    RecipientGuardian,
    UserAccount,
)
from app.db.seed_dev_recipients import (
    BENEFIT_CODES,
    CERT_NUMBER_BASE,
    GRADE_CODES,
    NAME_PREFIX,
    SEED_MARKER,
    TARGET_COUNT,
    _apply_seed_benefit,
    _attach_certification_and_grade,
    _benefit_code,
    _benefit_start_text,
    _birth_date,
    _build_batch_request,
    _family_name,
    _grade_code,
    _local_database_guard,
    _recipient_memo,
    _seed_recipient_name,
    dev_seed_integrity_errors,
    seed_dev_recipients,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.w1c.schemas import (
    BenefitCode,
    BenefitPeriodListResponse,
    BenefitPeriodReplacementRequest,
    BenefitPeriodResponse,
    CertificationIdentityCreateRequest,
    CertificationPeriodCreateRequest,
    GradeCode,
)
from app.domains.w1c.service import W1CService

LIVE_ENABLED = os.environ.get("SSWCENTER_SEED_LIVE_PG") == "1"


class _RecordingW1CService:
    """Captures only the W1C calls the seed should make for one recipient."""

    def __init__(self) -> None:
        self.identity_payload: CertificationIdentityCreateRequest | None = None
        self.certification_payload: CertificationPeriodCreateRequest | None = None
        self.grade_period_calls = 0
        self.create_benefit_calls = 0
        self.replace_benefit_calls = 0
        self.list_benefit_calls = 0
        self.replaced_benefit: tuple[int, int, BenefitPeriodReplacementRequest] | None = None

    def create_identity(
        self,
        recipient_id: int,
        payload: CertificationIdentityCreateRequest,
        account: CurrentAccount,
    ) -> None:
        self.identity_payload = payload

    def create_certification_period(
        self,
        recipient_id: int,
        payload: CertificationPeriodCreateRequest,
        account: CurrentAccount,
    ) -> None:
        self.certification_payload = payload

    def create_grade_period(self, *args: object, **kwargs: object) -> None:
        self.grade_period_calls += 1

    def list_benefit_periods(self, recipient_id: int) -> BenefitPeriodListResponse:
        self.list_benefit_calls += 1
        return BenefitPeriodListResponse(
            items=[
                BenefitPeriodResponse(
                    id=11,
                    recipient_id=recipient_id,
                    benefit_code=BenefitCode.GENERAL,
                    start_text="",
                    invalidated_at_utc=None,
                    replacement_benefit_period_id=None,
                    row_version=1,
                )
            ]
        )

    def create_benefit_period(self, *args: object, **kwargs: object) -> None:
        self.create_benefit_calls += 1

    def replace_benefit_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: BenefitPeriodReplacementRequest,
        account: CurrentAccount,
    ) -> None:
        self.replace_benefit_calls += 1
        self.replaced_benefit = (recipient_id, period_id, payload)


def test_batch_request_uses_current_basic_schemas() -> None:
    for index in (0, 1, 2):
        payload = _build_batch_request(index)

        assert "home_phone" not in payload.recipient.model_dump()
        assert payload.recipient.mobile_phone
        assert payload.recipient.memo == _recipient_memo(index)
        assert not hasattr(payload, "benefit_periods")

        if index % 3 == 0:
            assert payload.guardians == []
            assert payload.payer_guardian_slot is None
        elif index % 3 == 1:
            assert len(payload.guardians) == 1
            assert payload.payer_guardian_slot is None
        else:
            assert len(payload.guardians) == 2
            assert payload.payer_guardian_slot == 0


def test_benefit_start_text_is_deterministic_and_human_readable() -> None:
    start = date(2026, 1, 5)
    assert _benefit_start_text(start) == "2026년 1월 5일부터"
    assert _benefit_start_text(start) == _benefit_start_text(start)


def test_attach_wires_grade_onto_certification_period_without_grade_period_call() -> None:
    recorder = _RecordingW1CService()
    account = CurrentAccount(id=1, display_name="관리자", role_code="ADMIN")
    index = 4

    _attach_certification_and_grade(
        w1c_service=cast(W1CService, recorder),
        recipient_id=77,
        index=index,
        today=date(2026, 8, 9),
        current_account=account,
    )

    assert recorder.identity_payload is not None
    assert recorder.identity_payload.certification_number == f"L{CERT_NUMBER_BASE + index:010d}"
    assert recorder.certification_payload is not None
    assert recorder.certification_payload.grade_code == _grade_code(index)
    assert recorder.certification_payload.start_date < recorder.certification_payload.end_date
    assert recorder.grade_period_calls == 0


def test_seed_covers_all_current_grade_and_benefit_codes() -> None:
    assert set(GRADE_CODES) == set(GradeCode)
    assert set(BENEFIT_CODES) == set(BenefitCode)
    grades = [_grade_code(index) for index in range(TARGET_COUNT)]
    benefits = [_benefit_code(index) for index in range(TARGET_COUNT)]
    assert set(grades) == set(GradeCode)
    assert set(benefits) == set(BenefitCode)
    grade_counts = Counter(grades)
    assert grade_counts[GradeCode.GRADE_3] > grade_counts[GradeCode.GRADE_1]
    assert grade_counts[GradeCode.GRADE_4] > grade_counts[GradeCode.GRADE_2]
    assert grade_counts[GradeCode.GRADE_3] > grade_counts[GradeCode.GRADE_5]
    benefit_counts = Counter(benefits)
    assert benefit_counts[BenefitCode.GENERAL] == max(benefit_counts.values())


def test_realistic_names_phones_addresses_and_marker() -> None:
    korean_name = re.compile(r"^[가-힣]{2,4}$")
    phone = re.compile(r"^010-0701-\d{4}$")
    postal = re.compile(r"^\d{5}$")
    addresses: set[str] = set()
    birth_months: set[int] = set()
    relationships: list[str] = []
    for index in range(TARGET_COUNT):
        payload = _build_batch_request(index)
        name = payload.recipient.name or ""
        if index < 2:
            assert name.startswith("테스트 ")
        else:
            assert korean_name.fullmatch(name)
            assert NAME_PREFIX not in name
            assert not name.endswith(f"-{index:03d}")
        assert payload.recipient.memo == _recipient_memo(index)
        assert payload.recipient.memo.startswith(f"{SEED_MARKER}|")
        assert phone.fullmatch(payload.recipient.mobile_phone)
        assert postal.fullmatch(payload.recipient.postal_code or "")
        assert payload.recipient.address
        assert re.search(r"(특별시|광역시|특별자치시|특별자치도|도) ", payload.recipient.address)
        assert "시드센터 합성" in (payload.recipient.address or "")
        addresses.add(payload.recipient.address or "")
        birth = _birth_date(index)
        assert date(1931, 1, 1) <= birth <= date(1961, 12, 31)
        assert birth.day <= 28
        birth_months.add(birth.month)
        for guardian in payload.guardians:
            guardian_name = guardian.payload.name or ""
            assert korean_name.fullmatch(guardian_name)
            assert not guardian_name.endswith("보호자")
            assert phone.fullmatch(guardian.payload.phone or "")
            relationship = guardian.payload.relationship_text or ""
            relationships.append(relationship)
            if relationship in {"자녀", "손자", "형제", "자매"}:
                assert _family_name(guardian_name) == _family_name(name)
            if relationship in {"배우자", "며느리", "사위"}:
                assert _family_name(guardian_name) != _family_name(name)
            if relationship in {"배우자", "자녀"}:
                assert guardian.payload.address == payload.recipient.address
    assert birth_months == set(range(1, 13))
    assert len(addresses) == TARGET_COUNT
    relationship_counts = Counter(relationships)
    assert relationship_counts["자녀"] == max(relationship_counts.values())
    assert set(relationship_counts) >= set(
        {"배우자", "자녀", "며느리", "사위", "손자", "형제", "자매", "기타"}
    )


def test_apply_seed_benefit_replaces_auto_general_instead_of_second_create() -> None:
    recorder = _RecordingW1CService()
    account = CurrentAccount(id=1, display_name="관리자", role_code="ADMIN")
    _apply_seed_benefit(
        w1c_service=cast(W1CService, recorder),
        recipient_id=77,
        index=1,
        today=date(2026, 8, 9),
        current_account=account,
    )
    assert recorder.list_benefit_calls == 1
    assert recorder.create_benefit_calls == 0
    assert recorder.replace_benefit_calls == 1
    assert recorder.replaced_benefit is not None
    recipient_id, period_id, payload = recorder.replaced_benefit
    assert recipient_id == 77
    assert period_id == 11
    assert payload.benefit_code == _benefit_code(1)
    assert payload.start_text.endswith("일부터")


def test_apply_seed_benefit_replaces_blank_general_start_text() -> None:
    recorder = _RecordingW1CService()
    account = CurrentAccount(id=1, display_name="관리자", role_code="ADMIN")
    general_index = next(
        index for index in range(TARGET_COUNT) if _benefit_code(index) is BenefitCode.GENERAL
    )
    _apply_seed_benefit(
        w1c_service=cast(W1CService, recorder),
        recipient_id=88,
        index=general_index,
        today=date(2026, 8, 9),
        current_account=account,
    )
    assert recorder.replace_benefit_calls == 1
    assert recorder.replaced_benefit is not None
    payload = recorder.replaced_benefit[2]
    assert payload.benefit_code is BenefitCode.GENERAL
    assert payload.start_text


def test_local_database_guard_accepts_only_loopback_suffixed_names() -> None:
    _local_database_guard("postgresql://ssw:ssw@127.0.0.1:5432/sswcenter_dev")
    _local_database_guard("postgresql://ssw:ssw@localhost:5432/sswcenter_test")
    _local_database_guard("postgresql://ssw:ssw@[::1]:5432/sswcenter_review")
    with pytest.raises(RuntimeError, match="loopback"):
        _local_database_guard("postgresql://ssw:ssw@10.0.0.8:5432/sswcenter_dev")
    with pytest.raises(RuntimeError, match="development/test"):
        _local_database_guard("postgresql://ssw:ssw@127.0.0.1:5432/sswcenter")


def test_seed_dev_recipients_refuses_production_and_missing_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.db.seed_dev_recipients.get_settings",
        lambda: SimpleNamespace(
            environment=Environment.PRODUCTION,
            database_url="postgresql://ssw:ssw@127.0.0.1:5432/sswcenter_dev",
        ),
    )
    with pytest.raises(RuntimeError, match="production"):
        seed_dev_recipients()

    monkeypatch.setattr(
        "app.db.seed_dev_recipients.get_settings",
        lambda: SimpleNamespace(environment=Environment.DEVELOPMENT, database_url=None),
    )
    with pytest.raises(RuntimeError, match="SSWCENTER_DATABASE_URL"):
        seed_dev_recipients()


def test_dev_seed_keeps_single_transaction_and_exact_complete_contract() -> None:
    import app.db.seed_dev_recipients as dev_seed

    source = inspect.getsource(dev_seed) + inspect.getsource(seed_dev_recipients)
    assert "TARGET_COUNT" in source
    assert "ALREADY_COMPLETE" in source
    assert "SEED_DEV_RECIPIENTS_UNEXPECTED_PARTIAL_STATE" in source
    assert "recipient_detail_batch_defer_commit" in source
    assert "rollback" in source
    assert "today_seoul" in source
    assert "dev_seed_integrity_errors" in source
    assert ">= TARGET_COUNT" not in source
    assert TARGET_COUNT == 200
    assert SEED_MARKER == "SSWCENTER_DEV_RECIPIENTS_V1"
    assert re.fullmatch(r"^[가-힣]{2,4}$", _seed_recipient_name(3))


def _ensure_live_admin() -> int:
    settings = get_settings()
    assert settings.database_url is not None
    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            admin = session.scalar(
                select(UserAccount)
                .where(UserAccount.active.is_(True), UserAccount.role_code == "ADMIN")
                .order_by(UserAccount.id.asc())
            )
            if admin is None:
                bootstrap_installation(
                    session,
                    BootstrapInput(
                        center_name="합성 개발시드센터",
                        admin_name="시드관리자",
                        birth_date=date(1980, 3, 15),
                        sex_code="TEST",
                        start_date=date(2025, 1, 2),
                        pin="100000",
                    ),
                    settings,
                )
                session.commit()
                admin = session.scalar(
                    select(UserAccount).where(UserAccount.account_code == "ADMIN-001")
                )
            assert admin is not None
            return int(admin.id)
    finally:
        engine.dispose()


@pytest.mark.skipif(not LIVE_ENABLED, reason="requires isolated seed live PostgreSQL")
def test_dev_live_exact_200_rerun_distributions_and_fail_closed() -> None:
    get_settings.cache_clear()
    admin_id = _ensure_live_admin()
    first = seed_dev_recipients()
    assert first["status"] == "COMPLETE"
    assert first["count"] == 200
    assert first["created"] == 200

    second = seed_dev_recipients()
    assert second["status"] == "ALREADY_COMPLETE"
    assert second["created"] == 0

    settings = get_settings()
    assert settings.database_url is not None
    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            rows = list(
                session.scalars(
                    select(Recipient).where(
                        Recipient.memo.in_(
                            [_recipient_memo(index) for index in range(TARGET_COUNT)]
                        )
                    )
                ).all()
            )
            assert len(rows) == 200
            months = {row.birth_date.month for row in rows if row.birth_date is not None}
            assert months == set(range(1, 13))
            addresses = {row.address for row in rows}
            assert len(addresses) == 200
            assert all(row.address and "시드센터 합성" in row.address for row in rows)
            grades = list(
                session.scalars(select(RecipientCertificationIdentity.recipient_id)).all()
            )
            assert len(grades) == 200
            benefits = list(
                session.scalars(
                    select(RecipientBenefitPeriod).where(
                        RecipientBenefitPeriod.invalidated_at_utc.is_(None)
                    )
                ).all()
            )
            marked_ids = {row.id for row in rows}
            marked_benefits = [item for item in benefits if item.recipient_id in marked_ids]
            assert len(marked_benefits) == 200
            assert all((item.start_text or "").strip() for item in marked_benefits)
            benefit_counts = Counter(item.benefit_code for item in marked_benefits)
            assert benefit_counts["GENERAL"] == max(benefit_counts.values())
            assert set(benefit_counts) == {
                "GENERAL",
                "BASIC_LIVELIHOOD",
                "REDUCTION_6",
                "REDUCTION_9",
                "MEDICAL_6",
                "MEDICAL_9",
            }
            session.add(
                Recipient(
                    name="초과시드",
                    birth_date=date(1940, 1, 1),
                    sex_code="FEMALE",
                    recipient_status="ACTIVE",
                    memo=f"{SEED_MARKER}|200",
                    postal_code="00000",
                    address="시드센터 합성 초과 1호",
                    mobile_phone="010-0701-9999",
                    created_by_account_id=admin_id,
                    updated_by_account_id=admin_id,
                )
            )
            session.commit()
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="PARTIAL"):
        seed_dev_recipients()

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            session.execute(delete(Recipient).where(Recipient.memo == f"{SEED_MARKER}|200"))
            session.commit()
    finally:
        engine.dispose()

    restored = seed_dev_recipients()
    assert restored["status"] == "ALREADY_COMPLETE"

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            guardian_recipient = session.scalar(
                select(Recipient).where(Recipient.memo == _recipient_memo(2))
            )
            assert guardian_recipient is not None
            deleted = cast(
                CursorResult[Any],
                session.execute(
                    delete(RecipientGuardian).where(
                        RecipientGuardian.recipient_id == guardian_recipient.id
                    )
                ),
            )
            assert deleted.rowcount >= 1
            session.commit()
            errors = dev_seed_integrity_errors(session)
            assert any(item.startswith("guardian") for item in errors)
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="PARTIAL"):
        seed_dev_recipients()
