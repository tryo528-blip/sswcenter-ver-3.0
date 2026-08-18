from __future__ import annotations

import inspect
import os
import re
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.settings import Environment, get_settings
from app.db.models import (
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationPeriod,
    RecipientContract,
    Staff,
    StaffEmployment,
    StaffPositionPeriod,
)
from app.db.seed_extreme_test_data import (
    ACTIVE_BENEFIT_COUNT,
    ADDRESS_SHAPES,
    ADMIN_MARKED_STAFF_COUNT,
    CURRENT_CARE_WORKER_COUNT,
    CURRENT_MANAGER_COUNT,
    CURRENT_NURSE_COUNT,
    CURRENT_RECIPIENT_COUNT,
    CURRENT_SOCIAL_WORKER_COUNT,
    ENDED_CARE_WORKER_COUNT,
    ENDED_MANAGER_COUNT,
    ENDED_NURSE_COUNT,
    ENDED_RECIPIENT_COUNT,
    ENDED_SOCIAL_WORKER_COUNT,
    FAMILY_NAMES,
    MARKED_RECIPIENT_COUNT,
    MARKED_STAFF_COUNT,
    RECIPIENT_GIVEN_NAMES,
    SEED_MARKER,
    STAFF_GIVEN_NAMES,
    SYNTHETIC_UNIT_MARK,
    _build_benefit_period,
    _build_certification_period,
    _build_contract,
    _build_recipient,
    _grade_code,
    _local_database_guard,
    _phone,
    _pseudonym,
    _recipient_postal_and_address,
    _staff_address,
    _staff_phones,
    mixed_database_error,
    seed_extreme_test_data,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.staff.policies import normalize_phone_number

_KOREAN_NAME = re.compile(r"^[가-힣]{2,4}$")
_POSTAL_SHAPE = re.compile(r"^\d{5}$")
_ADMIN_DIVISION_SHAPE = re.compile(r"(특별시|광역시|특별자치시|특별자치도|도) ")
_ROAD_NUMBER_SHAPE = re.compile(r"(로|길)\s+\d+")
_GENERIC_ADDRESS = "시드센터 합성 테스트 주소"

LIVE_ENABLED = os.environ.get("SSWCENTER_SEED_LIVE_PG") == "1"


def test_extreme_current_schema_has_no_home_phone_or_signer_fields() -> None:
    assert "home_phone" not in Recipient.__table__.c
    assert "mobile_phone" in Recipient.__table__.c
    assert "grade_code" in RecipientCertificationPeriod.__table__.c
    assert "signer_name" not in RecipientContract.__table__.c
    assert "signer_relationship_text" not in RecipientContract.__table__.c
    assert "signer_phone" not in RecipientContract.__table__.c
    assert "recipient_status" in Recipient.__table__.c


def test_extreme_builders_match_current_constructors() -> None:
    active = _build_recipient(account_id=1, name_index=3, sequence=4, ended=False)
    assert active.mobile_phone.startswith("010-9000-")
    assert active.memo == SEED_MARKER
    assert active.recipient_status == "ACTIVE"
    assert not hasattr(active, "home_phone")
    assert _POSTAL_SHAPE.fullmatch(active.postal_code or "")
    assert active.address
    assert SYNTHETIC_UNIT_MARK in active.address
    assert _GENERIC_ADDRESS not in active.address

    ended = _build_recipient(account_id=1, name_index=5, sequence=6, ended=True)
    assert ended.recipient_status == "ENDED"
    assert ended.address != active.address
    assert ended.postal_code != "00000"

    contract = _build_contract(
        recipient_id=9,
        account_id=1,
        service_type_id=3,
        start_date=date(2026, 1, 1),
        end_date=None,
        ended=False,
    )
    assert contract.end_reason_text is None
    assert not hasattr(contract, "signer_name")

    period = _build_certification_period(
        recipient_id=9,
        account_id=1,
        sequence=4,
        start_date=date(2026, 1, 1),
        end_date=date(2099, 12, 31),
    )
    assert period.grade_code == "4"
    assert period.grade_code in {"1", "2", "3", "4", "5"}

    benefit = _build_benefit_period(recipient_id=9, account_id=1, ended=False)
    assert benefit.benefit_code == "GENERAL"
    assert benefit.start_text == "2026년 1월 1일부터"


def test_extreme_grade_codes_cover_all_current_values() -> None:
    assert {_grade_code(sequence) for sequence in range(1, 6)} == {"1", "2", "3", "4", "5"}


def test_extreme_source_does_not_reintroduce_removed_columns() -> None:
    import app.db.seed_extreme_test_data as extreme

    module_source = inspect.getsource(extreme)
    assert "home_phone" not in module_source
    assert "signer_name" not in module_source
    assert "signer_relationship_text" not in module_source
    assert "signer_phone" not in module_source
    assert "grade_code" in module_source
    assert "recipient_status" in module_source
    assert "RecipientBenefitPeriod" in module_source
    assert "normalize_phone_number" in module_source
    assert "database_session.add" in inspect.getsource(extreme._add_recipient)
    assert "rollback_session" not in module_source
    assert "_install_deferred_commits" in module_source
    assert "_restore_deferred_commits" in module_source
    assert _GENERIC_ADDRESS not in module_source
    assert 'postal_code="00000"' not in module_source
    assert "_staff_address" in inspect.getsource(extreme._add_staff)
    assert "_recipient_postal_and_address" in inspect.getsource(extreme._build_recipient)


def test_extreme_local_database_guard() -> None:
    _local_database_guard("postgresql://ssw:ssw@127.0.0.1:5432/sswcenter_review")
    with pytest.raises(RuntimeError, match="loopback"):
        _local_database_guard("postgresql://ssw:ssw@192.168.1.10:5432/sswcenter_test")
    with pytest.raises(RuntimeError, match="development/test"):
        _local_database_guard("postgresql://ssw:ssw@127.0.0.1:5432/sswcenter")


def test_extreme_seed_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.db.seed_extreme_test_data.get_settings",
        lambda: SimpleNamespace(
            environment=Environment.PRODUCTION,
            database_url="postgresql://ssw:ssw@127.0.0.1:5432/sswcenter_test",
        ),
    )
    with pytest.raises(RuntimeError, match="production"):
        seed_extreme_test_data()


def test_extreme_staff_phone_uses_normalize_phone_number() -> None:
    original, normalized = _staff_phones(1)
    expected_original, expected_normalized = normalize_phone_number("010-9000-0001")
    assert original == expected_original
    assert normalized == expected_normalized
    assert normalized == "+821090000001"


def test_extreme_names_are_age_coherent() -> None:
    staff_name = _pseudonym(3, staff=True)
    recipient_name = _pseudonym(3, staff=False)
    assert staff_name != recipient_name
    assert any(staff_name.endswith(given) for given in STAFF_GIVEN_NAMES)
    assert any(recipient_name.endswith(given) for given in RECIPIENT_GIVEN_NAMES)
    assert _KOREAN_NAME.fullmatch(staff_name)
    assert _KOREAN_NAME.fullmatch(recipient_name)
    assert staff_name[0] in FAMILY_NAMES
    assert recipient_name[0] in FAMILY_NAMES


def test_extreme_isolation_refuses_orphan_and_allows_admin_or_empty() -> None:
    assert (
        mixed_database_error(
            total_staff=0,
            total_recipients=0,
            admin_staff_id=None,
            only_staff_id=None,
        )
        is None
    )
    assert (
        mixed_database_error(
            total_staff=1,
            total_recipients=0,
            admin_staff_id=9,
            only_staff_id=9,
        )
        is None
    )
    orphan = mixed_database_error(
        total_staff=1,
        total_recipients=0,
        admin_staff_id=None,
        only_staff_id=4,
    )
    assert orphan is not None
    assert "orphan" in orphan
    mixed = mixed_database_error(
        total_staff=2,
        total_recipients=0,
        admin_staff_id=1,
        only_staff_id=1,
    )
    assert mixed is not None
    assert "mix" in mixed


def test_extreme_counts_preserve_current_and_ended_semantics() -> None:
    assert MARKED_STAFF_COUNT == 364
    assert MARKED_RECIPIENT_COUNT == 350
    assert ACTIVE_BENEFIT_COUNT == 350
    assert CURRENT_RECIPIENT_COUNT == 150
    assert ENDED_RECIPIENT_COUNT == 200
    assert CURRENT_CARE_WORKER_COUNT == 150
    assert CURRENT_SOCIAL_WORKER_COUNT == 4
    assert CURRENT_NURSE_COUNT == 2
    assert CURRENT_MANAGER_COUNT == 1
    assert ENDED_CARE_WORKER_COUNT == 200
    assert ENDED_SOCIAL_WORKER_COUNT == 5
    assert ENDED_NURSE_COUNT == 1
    assert ENDED_MANAGER_COUNT == 1
    assert ADMIN_MARKED_STAFF_COUNT == 1
    assert (
        CURRENT_CARE_WORKER_COUNT
        + CURRENT_SOCIAL_WORKER_COUNT
        + CURRENT_NURSE_COUNT
        + CURRENT_MANAGER_COUNT
        + ENDED_CARE_WORKER_COUNT
        + ENDED_SOCIAL_WORKER_COUNT
        + ENDED_NURSE_COUNT
        + ENDED_MANAGER_COUNT
        == MARKED_STAFF_COUNT
    )

    import app.db.seed_extreme_test_data as extreme

    add_staff_source = inspect.getsource(extreme._add_staff)
    add_recipient_source = inspect.getsource(extreme._add_recipient)
    seed_source = inspect.getsource(extreme.seed_extreme_test_data)
    assert "ENDED_START if ended else ACTIVE_START" in add_staff_source
    assert "ENDED_DATE if ended else None" in add_staff_source
    assert "ENDED_START if ended else ACTIVE_START" in add_recipient_source
    assert "CURRENT_CARE_WORKER_COUNT" in seed_source
    assert "ENDED_CARE_WORKER_COUNT" in seed_source
    assert "CURRENT_RECIPIENT_COUNT" in seed_source
    assert "ENDED_RECIPIENT_COUNT" in seed_source
    assert "ended=False" in seed_source
    assert "ended=True" in seed_source

    ended_benefit = _build_benefit_period(recipient_id=1, account_id=1, ended=True)
    assert ended_benefit.start_text == "2020년 1월 1일부터"
    ended_contract = _build_contract(
        recipient_id=1,
        account_id=1,
        service_type_id=3,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 12, 31),
        ended=True,
    )
    assert ended_contract.end_reason_text == "합성 테스트 종료"


def test_extreme_names_and_phones_are_deterministic_and_unique() -> None:
    staff_names = [_pseudonym(index, staff=True) for index in range(1, MARKED_STAFF_COUNT)]
    recipient_names = [_pseudonym(index, staff=False) for index in range(MARKED_RECIPIENT_COUNT)]
    assert staff_names[40] == _pseudonym(41, staff=True)
    assert recipient_names[17] == _pseudonym(17, staff=False)
    assert all(_KOREAN_NAME.fullmatch(name) for name in staff_names)
    assert all(_KOREAN_NAME.fullmatch(name) for name in recipient_names)
    assert len(set(staff_names)) == len(staff_names)
    assert len(set(recipient_names)) == len(recipient_names)

    staff_phones = [_staff_phones(index) for index in range(MARKED_STAFF_COUNT)]
    originals = [original for original, _normalized in staff_phones]
    normalized = [value for _original, value in staff_phones]
    assert len(set(originals)) == MARKED_STAFF_COUNT
    assert len(set(normalized)) == MARKED_STAFF_COUNT
    assert all(value.startswith("+82") for value in normalized)
    assert all(original == _phone(index) for index, original in enumerate(originals))
    recipient_mobiles = [
        _phone(500 + sequence) for sequence in range(1, MARKED_RECIPIENT_COUNT + 1)
    ]
    assert len(set(recipient_mobiles)) == MARKED_RECIPIENT_COUNT
    assert set(originals).isdisjoint(recipient_mobiles)


def test_extreme_addresses_are_varied_labeled_and_road_shaped() -> None:
    assert len(ADDRESS_SHAPES) > 1
    staff_addresses = [_staff_address(index) for index in range(MARKED_STAFF_COUNT)]
    recipient_rows = [
        _recipient_postal_and_address(sequence) for sequence in range(1, MARKED_RECIPIENT_COUNT + 1)
    ]
    recipient_postals = [postal for postal, _address in recipient_rows]
    recipient_addresses = [address for _postal, address in recipient_rows]

    assert len(set(staff_addresses)) == MARKED_STAFF_COUNT
    assert len(set(recipient_addresses)) == MARKED_RECIPIENT_COUNT
    assert staff_addresses[0] == _staff_address(0)
    assert recipient_rows[8] == _recipient_postal_and_address(9)
    assert SYNTHETIC_UNIT_MARK in staff_addresses[0]
    assert staff_addresses[0].endswith("관리실")
    assert all(SYNTHETIC_UNIT_MARK in address for address in staff_addresses)
    assert all(SYNTHETIC_UNIT_MARK in address for address in recipient_addresses)
    assert _GENERIC_ADDRESS not in staff_addresses
    assert _GENERIC_ADDRESS not in recipient_addresses
    assert all(_ADMIN_DIVISION_SHAPE.search(address) for address in staff_addresses)
    assert all(_ADMIN_DIVISION_SHAPE.search(address) for address in recipient_addresses)
    assert all(_ROAD_NUMBER_SHAPE.search(address) for address in staff_addresses)
    assert all(_ROAD_NUMBER_SHAPE.search(address) for address in recipient_addresses)
    assert all(_POSTAL_SHAPE.fullmatch(postal) for postal in recipient_postals)
    assert "00000" not in recipient_postals
    assert len(set(recipient_postals)) > 1
    assert len({address.split(" 시드센터")[0] for address in recipient_addresses}) > 1

    built = [
        _build_recipient(account_id=1, name_index=index, sequence=index + 1)
        for index in range(MARKED_RECIPIENT_COUNT)
    ]
    assert {row.address for row in built} == set(recipient_addresses)
    assert all(row.postal_code in recipient_postals for row in built)


@pytest.mark.skipif(not LIVE_ENABLED, reason="requires isolated seed live PostgreSQL")
def test_extreme_live_active_ended_benefit_phone_and_second_run_refused() -> None:
    get_settings.cache_clear()
    first = seed_extreme_test_data()
    assert first["current_recipients"] == CURRENT_RECIPIENT_COUNT
    assert first["ended_recipients"] == ENDED_RECIPIENT_COUNT
    assert first["current_care_workers"] == CURRENT_CARE_WORKER_COUNT
    assert first["ended_care_workers"] == ENDED_CARE_WORKER_COUNT

    settings = get_settings()
    assert settings.database_url is not None
    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            marked_recipients = list(
                session.scalars(select(Recipient).where(Recipient.memo == SEED_MARKER)).all()
            )
            assert len(marked_recipients) == MARKED_RECIPIENT_COUNT
            active = [row for row in marked_recipients if row.recipient_status == "ACTIVE"]
            ended = [row for row in marked_recipients if row.recipient_status == "ENDED"]
            assert len(active) == CURRENT_RECIPIENT_COUNT
            assert len(ended) == ENDED_RECIPIENT_COUNT
            benefits = int(
                session.scalar(
                    select(func.count())
                    .select_from(RecipientBenefitPeriod)
                    .where(RecipientBenefitPeriod.invalidated_at_utc.is_(None))
                )
                or 0
            )
            assert benefits == ACTIVE_BENEFIT_COUNT
            staff_rows = list(session.scalars(select(Staff).where(Staff.memo == SEED_MARKER)).all())
            assert len(staff_rows) == MARKED_STAFF_COUNT
            assert all(
                (row.phone_normalized or "").startswith("+82") for row in staff_rows if row.phone
            )
            assert len({row.phone_normalized for row in staff_rows}) == MARKED_STAFF_COUNT
            staff_addresses = {row.address for row in staff_rows}
            recipient_addresses = {row.address for row in marked_recipients}
            assert len(staff_addresses) == MARKED_STAFF_COUNT
            assert len(recipient_addresses) == MARKED_RECIPIENT_COUNT
            assert all(row.address and SYNTHETIC_UNIT_MARK in row.address for row in staff_rows)
            assert all(
                row.address and SYNTHETIC_UNIT_MARK in row.address for row in marked_recipients
            )
            assert all(_POSTAL_SHAPE.fullmatch(row.postal_code or "") for row in marked_recipients)
            assert all(row.postal_code != "00000" for row in marked_recipients)
            staff_ids = [row.id for row in staff_rows]
            current_counts: dict[str, int] = dict(
                session.execute(
                    select(StaffPositionPeriod.position_code, func.count())
                    .join(
                        StaffEmployment,
                        StaffEmployment.id == StaffPositionPeriod.employment_id,
                    )
                    .where(
                        StaffEmployment.staff_id.in_(staff_ids),
                        StaffEmployment.invalidated_at_utc.is_(None),
                        StaffEmployment.end_date.is_(None),
                        StaffPositionPeriod.invalidated_at_utc.is_(None),
                        StaffPositionPeriod.end_date.is_(None),
                    )
                    .group_by(StaffPositionPeriod.position_code)
                ).tuples()
            )
            ended_counts: dict[str, int] = dict(
                session.execute(
                    select(StaffPositionPeriod.position_code, func.count())
                    .join(
                        StaffEmployment,
                        StaffEmployment.id == StaffPositionPeriod.employment_id,
                    )
                    .where(
                        StaffEmployment.staff_id.in_(staff_ids),
                        StaffEmployment.invalidated_at_utc.is_(None),
                        StaffEmployment.end_date.is_not(None),
                        StaffPositionPeriod.invalidated_at_utc.is_(None),
                        StaffPositionPeriod.end_date.is_not(None),
                    )
                    .group_by(StaffPositionPeriod.position_code)
                ).tuples()
            )
            assert current_counts.get("CARE_WORKER") == CURRENT_CARE_WORKER_COUNT
            assert current_counts.get("SOCIAL_WORKER") == CURRENT_SOCIAL_WORKER_COUNT
            assert current_counts.get("NURSE") == CURRENT_NURSE_COUNT
            assert current_counts.get("MANAGER") == CURRENT_MANAGER_COUNT
            assert ended_counts.get("CARE_WORKER") == ENDED_CARE_WORKER_COUNT
            assert ended_counts.get("SOCIAL_WORKER") == ENDED_SOCIAL_WORKER_COUNT
            assert ended_counts.get("NURSE") == ENDED_NURSE_COUNT
            assert ended_counts.get("MANAGER") == ENDED_MANAGER_COUNT
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="already exists"):
        seed_extreme_test_data()
