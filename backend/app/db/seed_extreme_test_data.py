from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.auth import BootstrapInput, bootstrap_installation
from app.core.settings import Environment, Settings, get_settings
from app.db.models import (
    InstallationState,
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationIdentity,
    RecipientCertificationPeriod,
    RecipientContract,
    ServiceType,
    Staff,
    StaffEmployment,
    StaffOperationalRolePeriod,
    StaffPositionPeriod,
    UserAccount,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.staff.policies import normalize_phone_number

SEED_MARKER = "SSWCENTER_EXTREME_TEST_DATA_V1"
ACTIVE_START = date(2026, 1, 1)
ENDED_START = date(2020, 1, 1)
ENDED_DATE = date(2025, 12, 31)
ACTIVE_CERTIFICATION_END = date(2099, 12, 31)
_ORIGINAL_COMMIT_KEY = "sswcenter_extreme_seed_original_commit"

FAMILY_NAMES = (
    "김",
    "이",
    "박",
    "최",
    "정",
    "강",
    "조",
    "윤",
    "장",
    "임",
    "한",
    "오",
    "서",
    "신",
    "권",
    "황",
    "안",
    "송",
    "류",
    "전",
    "홍",
    "문",
    "양",
    "손",
    "배",
    "백",
    "허",
    "남",
    "심",
    "노",
    "하",
    "곽",
)

STAFF_GIVEN_NAMES = (
    "민준",
    "서연",
    "지훈",
    "수빈",
    "도윤",
    "예은",
    "현우",
    "지민",
    "준서",
    "은지",
    "하준",
    "유진",
    "시우",
    "채원",
    "건우",
    "다은",
    "태윤",
    "소율",
    "재현",
    "나연",
)

RECIPIENT_GIVEN_NAMES = (
    "순자",
    "영자",
    "옥순",
    "정숙",
    "미자",
    "철수",
    "영수",
    "만수",
    "순이",
    "정자",
    "광수",
    "병철",
    "숙자",
    "명자",
    "해자",
    "동식",
    "기남",
    "점례",
    "춘자",
    "말자",
)

ROLE_BY_POSITION = {
    "CARE_WORKER": "CARE_SERVICE",
    "SOCIAL_WORKER": "SOCIAL_WORK",
    "NURSE": "NURSING",
    "MANAGER": "MANAGEMENT_FUNCTION",
}

CURRENT_RECIPIENT_COUNT = 150
ENDED_RECIPIENT_COUNT = 200
MARKED_RECIPIENT_COUNT = CURRENT_RECIPIENT_COUNT + ENDED_RECIPIENT_COUNT
ACTIVE_BENEFIT_COUNT = MARKED_RECIPIENT_COUNT
CURRENT_CARE_WORKER_COUNT = 150
CURRENT_SOCIAL_WORKER_COUNT = 4
CURRENT_NURSE_COUNT = 2
CURRENT_MANAGER_COUNT = 1
ENDED_CARE_WORKER_COUNT = 200
ENDED_SOCIAL_WORKER_COUNT = 5
ENDED_NURSE_COUNT = 1
ENDED_MANAGER_COUNT = 1
ADMIN_MARKED_STAFF_COUNT = 1
MARKED_STAFF_COUNT = (
    ADMIN_MARKED_STAFF_COUNT
    + CURRENT_CARE_WORKER_COUNT
    + CURRENT_SOCIAL_WORKER_COUNT
    + CURRENT_NURSE_COUNT
    + ENDED_CARE_WORKER_COUNT
    + ENDED_SOCIAL_WORKER_COUNT
    + ENDED_NURSE_COUNT
    + ENDED_MANAGER_COUNT
)
SYNTHETIC_UNIT_MARK = "시드센터 합성"

# Public-place roads as shape only. Unit/details stay clearly synthetic.
ADDRESS_SHAPES: tuple[tuple[str, str], ...] = (
    ("04524", "서울특별시 중구 세종대로 110"),
    ("06236", "서울특별시 강남구 테헤란로 152"),
    ("03722", "서울특별시 서대문구 연세로 50"),
    ("04158", "서울특별시 마포구 마포대로 109"),
    ("48058", "부산광역시 해운대구 센텀중앙로 79"),
    ("49201", "부산광역시 서구 구덕로 179"),
    ("21554", "인천광역시 남동구 정각로 29"),
    ("21984", "인천광역시 연수구 컨벤시아대로 165"),
    ("41911", "대구광역시 중구 공평로 88"),
    ("41560", "대구광역시 북구 대학로 80"),
    ("35242", "대전광역시 서구 둔산로 100"),
    ("34126", "대전광역시 유성구 대학로 99"),
    ("61475", "광주광역시 동구 중앙로196번길 5"),
    ("61186", "광주광역시 북구 용봉로 77"),
    ("44691", "울산광역시 남구 중앙로 201"),
    ("44919", "울산광역시 울주군 언양읍 유니스트길 50"),
    ("30120", "세종특별자치시 한누리대로 2130"),
    ("16419", "경기도 수원시 영통구 월드컵로 206"),
    ("10442", "경기도 고양시 일산동구 중앙로 1286"),
    ("13487", "경기도 성남시 분당구 판교로 242"),
    ("24232", "강원특별자치도 춘천시 강원대학길 1"),
    ("26464", "강원특별자치도 원주시 흥업면 남원로 150"),
    ("28644", "충청북도 청주시 서원구 충대로 1"),
    ("27136", "충청북도 충주시 충열로 15"),
    ("31156", "충청남도 천안시 동남구 단대로 119"),
    ("32588", "충청남도 공주시 공주대학로 56"),
    ("54896", "전북특별자치도 전주시 덕진구 백제대로 567"),
    ("54538", "전북특별자치도 익산시 익산대로 460"),
    ("58554", "전라남도 목포시 대학로 166"),
    ("59626", "전라남도 순천시 중앙로 255"),
    ("37673", "경상북도 포항시 남구 청암로 77"),
    ("38541", "경상북도 경주시 태종로 677"),
    ("51508", "경상남도 창원시 의창구 창이대로 71"),
    ("52828", "경상남도 진주시 진주대로 501"),
    ("63243", "제주특별자치도 제주시 제주대학로 102"),
    ("63589", "제주특별자치도 서귀포시 중앙로 105"),
)


def _pseudonym(index: int, *, staff: bool) -> str:
    given_names = STAFF_GIVEN_NAMES if staff else RECIPIENT_GIVEN_NAMES
    zero_based = index % (len(FAMILY_NAMES) * len(given_names))
    return FAMILY_NAMES[zero_based // len(given_names)] + given_names[zero_based % len(given_names)]


def _birth_date(index: int, *, staff: bool) -> date:
    year_start = 1968 if staff else 1931
    year = year_start + (index % (24 if staff else 30))
    month = (index % 12) + 1
    day = (index % 27) + 1
    return date(year, month, day)


def _phone(index: int) -> str:
    return f"010-9000-{index:04d}"


def _staff_phones(index: int) -> tuple[str, str]:
    original, normalized = normalize_phone_number(_phone(index))
    if original is None or normalized is None:
        raise RuntimeError(f"extreme seed phone {index} failed normalization")
    return original, normalized


def _compose_address(road: str, detail: str) -> str:
    return f"{road.strip()} {detail.strip()}"


def _address_shape(index: int) -> tuple[str, str]:
    return ADDRESS_SHAPES[index % len(ADDRESS_SHAPES)]


def _unit_detail(index: int, *, kind: str) -> str:
    dong = (index % 20) + 1
    ho = 100 + index
    return f"{SYNTHETIC_UNIT_MARK} {kind} {dong}동 {ho}호"


def _staff_address(index: int) -> str:
    road = _address_shape(index)[1]
    if index == 0:
        return _compose_address(road, f"{SYNTHETIC_UNIT_MARK} 관리실")
    return _compose_address(road, _unit_detail(index, kind="직원숙소"))


def _recipient_postal_and_address(index: int) -> tuple[str, str]:
    postal_code, road = _address_shape(index)
    return postal_code, _compose_address(road, _unit_detail(index, kind="수급자"))


def _local_database_guard(database_url: str) -> None:
    url = make_url(database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("extreme synthetic seed only permits a loopback PostgreSQL host")
    database_name = url.database or ""
    if not database_name.endswith(("_dev", "_test", "_review")):
        raise RuntimeError("extreme synthetic seed requires a development/test database name")


def mixed_database_error(
    *,
    total_staff: int,
    total_recipients: int,
    admin_staff_id: int | None,
    only_staff_id: int | None,
) -> str | None:
    if total_recipients > 0:
        return "refusing to mix extreme synthetic data into an existing non-empty database"
    if total_staff == 0:
        return None
    if (
        total_staff == 1
        and admin_staff_id is not None
        and only_staff_id is not None
        and only_staff_id == admin_staff_id
    ):
        return None
    if total_staff == 1:
        return "refusing orphan staff that is not the active admin staff row"
    return "refusing to mix extreme synthetic data into an existing non-empty database"


def _refuse_unrelated_rows(database_session: Session) -> None:
    total_staff = int(database_session.scalar(select(func.count()).select_from(Staff)) or 0)
    total_recipients = int(
        database_session.scalar(select(func.count()).select_from(Recipient)) or 0
    )
    admin = database_session.scalar(
        select(UserAccount)
        .where(UserAccount.active.is_(True), UserAccount.role_code == "ADMIN")
        .order_by(UserAccount.id.asc())
    )
    only_staff = None
    if total_staff == 1:
        only_staff = database_session.scalar(select(Staff.id))
    error = mixed_database_error(
        total_staff=total_staff,
        total_recipients=total_recipients,
        admin_staff_id=None if admin is None else admin.staff_id,
        only_staff_id=None if only_staff is None else int(only_staff),
    )
    if error is not None:
        raise RuntimeError(error)


def _ensure_admin(database_session: Session, settings: Settings) -> UserAccount:
    state = database_session.scalar(
        select(InstallationState).where(InstallationState.singleton_key.is_(True))
    )
    if state is None:
        raise RuntimeError("installation_state singleton is missing; run migrations first")

    existing_admin = database_session.scalar(
        select(UserAccount)
        .where(UserAccount.active.is_(True), UserAccount.role_code == "ADMIN")
        .order_by(UserAccount.id.asc())
    )
    if existing_admin is not None:
        return existing_admin

    active_accounts = int(
        database_session.scalar(
            select(func.count()).select_from(UserAccount).where(UserAccount.active.is_(True))
        )
        or 0
    )
    if state.bootstrap_completed or active_accounts != 0:
        raise RuntimeError("an active non-admin account already exists; refusing mixed seed data")

    bootstrap_installation(
        database_session,
        BootstrapInput(
            center_name="극한 합성 테스트센터",
            admin_name="홍길동",
            birth_date=date(1980, 1, 1),
            sex_code="TEST",
            start_date=ACTIVE_START,
            pin="100000",
        ),
        settings,
    )
    admin = database_session.scalar(
        select(UserAccount).where(UserAccount.account_code == "ADMIN-001")
    )
    if admin is None:
        raise RuntimeError("bootstrap did not create ADMIN-001")
    return admin


def _install_deferred_commits(session: Session) -> None:
    session.info[_ORIGINAL_COMMIT_KEY] = session.commit
    session.commit = session.flush  # type: ignore[method-assign]


def _restore_deferred_commits(session: Session) -> None:
    original = session.info.pop(_ORIGINAL_COMMIT_KEY, None)
    if original is not None:
        session.commit = original  # type: ignore[method-assign]


def _add_staff(
    database_session: Session,
    *,
    account_id: int,
    name_index: int,
    sequence: int,
    position_code: str,
    ended: bool,
) -> Staff:
    start_date = ENDED_START if ended else ACTIVE_START
    end_date = ENDED_DATE if ended else None
    phone, phone_normalized = _staff_phones(sequence)
    staff = Staff(
        name=_pseudonym(name_index, staff=True),
        birth_date=_birth_date(name_index, staff=True),
        sex_code="TEST",
        phone=phone,
        phone_normalized=phone_normalized,
        address=_staff_address(sequence),
        display_name=_pseudonym(name_index, staff=True),
        memo=SEED_MARKER,
    )
    database_session.add(staff)
    database_session.flush()

    employment = StaffEmployment(
        staff_id=staff.id,
        employment_no=1,
        staff_no=f"EXTREME-2026-{sequence:04d}",
        staff_no_year=2026,
        staff_no_sequence=100000 + sequence,
        start_date=start_date,
        end_date=end_date,
        end_reason_code="RESIGNED" if ended else None,
        created_by_account_id=account_id,
        updated_by_account_id=account_id,
    )
    database_session.add(employment)
    database_session.flush()

    database_session.add(
        StaffPositionPeriod(
            staff_id=staff.id,
            employment_id=employment.id,
            position_code=position_code,
            start_date=start_date,
            end_date=end_date,
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
        )
    )
    database_session.add(
        StaffOperationalRolePeriod(
            staff_id=staff.id,
            employment_id=employment.id,
            role_code=ROLE_BY_POSITION[position_code],
            start_date=start_date,
            end_date=end_date,
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
        )
    )
    return staff


def _grade_code(sequence: int) -> str:
    return str(((sequence - 1) % 5) + 1)


def _build_recipient(
    *,
    account_id: int,
    name_index: int,
    sequence: int,
    ended: bool = False,
) -> Recipient:
    postal_code, address = _recipient_postal_and_address(sequence)
    return Recipient(
        name=_pseudonym(name_index, staff=False),
        birth_date=_birth_date(name_index, staff=False),
        sex_code="MALE" if sequence % 2 else "FEMALE",
        recipient_status="ENDED" if ended else "ACTIVE",
        recipient_no=f"EXTREME-R-{sequence:04d}",
        memo=SEED_MARKER,
        postal_code=postal_code,
        address=address,
        mobile_phone=_phone(500 + sequence),
        created_by_account_id=account_id,
        updated_by_account_id=account_id,
    )


def _build_contract(
    *,
    recipient_id: int,
    account_id: int,
    service_type_id: int,
    start_date: date,
    end_date: date | None,
    ended: bool,
) -> RecipientContract:
    return RecipientContract(
        recipient_id=recipient_id,
        service_type_id=service_type_id,
        start_date=start_date,
        end_date=end_date,
        service_start_date=start_date,
        end_reason_text="합성 테스트 종료" if ended else None,
        created_by_account_id=account_id,
        updated_by_account_id=account_id,
    )


def _build_certification_period(
    *,
    recipient_id: int,
    account_id: int,
    sequence: int,
    start_date: date,
    end_date: date,
) -> RecipientCertificationPeriod:
    return RecipientCertificationPeriod(
        recipient_id=recipient_id,
        grade_code=_grade_code(sequence),
        start_date=start_date,
        end_date=end_date,
        created_by_account_id=account_id,
        updated_by_account_id=account_id,
    )


def _build_benefit_period(
    *,
    recipient_id: int,
    account_id: int,
    ended: bool,
) -> RecipientBenefitPeriod:
    start_text = "2020년 1월 1일부터" if ended else "2026년 1월 1일부터"
    return RecipientBenefitPeriod(
        recipient_id=recipient_id,
        benefit_code="GENERAL",
        start_text=start_text,
        created_by_account_id=account_id,
        updated_by_account_id=account_id,
    )


def _add_recipient(
    database_session: Session,
    *,
    account_id: int,
    service_type_id: int,
    name_index: int,
    sequence: int,
    ended: bool,
) -> Recipient:
    start_date = ENDED_START if ended else ACTIVE_START
    end_date = ENDED_DATE if ended else None
    recipient = _build_recipient(
        account_id=account_id,
        name_index=name_index,
        sequence=sequence,
        ended=ended,
    )
    database_session.add(recipient)
    database_session.flush()

    database_session.add(
        _build_contract(
            recipient_id=recipient.id,
            account_id=account_id,
            service_type_id=service_type_id,
            start_date=start_date,
            end_date=end_date,
            ended=ended,
        )
    )
    database_session.add(
        RecipientCertificationIdentity(
            recipient_id=recipient.id,
            certification_number=f"L{sequence:010d}",
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
        )
    )
    database_session.flush()
    database_session.add(
        _build_certification_period(
            recipient_id=recipient.id,
            account_id=account_id,
            sequence=sequence,
            start_date=start_date,
            end_date=ACTIVE_CERTIFICATION_END,
        )
    )
    database_session.add(
        _build_benefit_period(
            recipient_id=recipient.id,
            account_id=account_id,
            ended=ended,
        )
    )
    return recipient


def seed_extreme_test_data() -> dict[str, int]:
    settings = get_settings()
    if settings.environment is Environment.PRODUCTION:
        raise RuntimeError("extreme synthetic seed is forbidden in production")
    if settings.database_url is None:
        raise RuntimeError("SSWCENTER_DATABASE_URL is required")
    _local_database_guard(settings.database_url)

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as database_session:
            marked_staff = int(
                database_session.scalar(
                    select(func.count()).select_from(Staff).where(Staff.memo == SEED_MARKER)
                )
                or 0
            )
            marked_recipients = int(
                database_session.scalar(
                    select(func.count()).select_from(Recipient).where(Recipient.memo == SEED_MARKER)
                )
                or 0
            )
            if marked_staff or marked_recipients:
                raise RuntimeError(
                    "extreme seed already exists: "
                    f"staff={marked_staff}, recipients={marked_recipients}"
                )

            _refuse_unrelated_rows(database_session)
            _install_deferred_commits(database_session)
            try:
                admin = _ensure_admin(database_session, settings)
                admin_staff = database_session.get(Staff, admin.staff_id)
                if admin_staff is None:
                    raise RuntimeError("admin staff row is missing")
                admin_phone, admin_normalized = _staff_phones(0)
                admin_staff.memo = SEED_MARKER
                admin_staff.phone = admin_phone
                admin_staff.phone_normalized = admin_normalized
                admin_staff.address = _staff_address(0)

                staff_sequence = 1
                staff_name_index = 1
                for position_code, count in (
                    ("CARE_WORKER", CURRENT_CARE_WORKER_COUNT),
                    ("SOCIAL_WORKER", CURRENT_SOCIAL_WORKER_COUNT),
                    ("NURSE", CURRENT_NURSE_COUNT),
                ):
                    for _ in range(count):
                        _add_staff(
                            database_session,
                            account_id=admin.id,
                            name_index=staff_name_index,
                            sequence=staff_sequence,
                            position_code=position_code,
                            ended=False,
                        )
                        staff_name_index += 1
                        staff_sequence += 1

                for position_code, count in (
                    ("CARE_WORKER", ENDED_CARE_WORKER_COUNT),
                    ("SOCIAL_WORKER", ENDED_SOCIAL_WORKER_COUNT),
                    ("NURSE", ENDED_NURSE_COUNT),
                    ("MANAGER", ENDED_MANAGER_COUNT),
                ):
                    for _ in range(count):
                        _add_staff(
                            database_session,
                            account_id=admin.id,
                            name_index=staff_name_index,
                            sequence=staff_sequence,
                            position_code=position_code,
                            ended=True,
                        )
                        staff_name_index += 1
                        staff_sequence += 1

                service_type = database_session.scalar(
                    select(ServiceType).where(ServiceType.code == "HOME_CARE")
                )
                if service_type is None:
                    raise RuntimeError("HOME_CARE service type is missing; run migrations first")

                recipient_sequence = 1
                for ended, count in (
                    (False, CURRENT_RECIPIENT_COUNT),
                    (True, ENDED_RECIPIENT_COUNT),
                ):
                    for _ in range(count):
                        _add_recipient(
                            database_session,
                            account_id=admin.id,
                            service_type_id=service_type.id,
                            name_index=recipient_sequence - 1,
                            sequence=recipient_sequence,
                            ended=ended,
                        )
                        recipient_sequence += 1

                _restore_deferred_commits(database_session)
                database_session.commit()
            except Exception:
                if database_session.in_transaction():
                    database_session.rollback()
                raise
            finally:
                _restore_deferred_commits(database_session)
            return {
                "current_recipients": CURRENT_RECIPIENT_COUNT,
                "ended_recipients": ENDED_RECIPIENT_COUNT,
                "current_care_workers": CURRENT_CARE_WORKER_COUNT,
                "current_social_workers": CURRENT_SOCIAL_WORKER_COUNT,
                "current_nurses": CURRENT_NURSE_COUNT,
                "current_managers": CURRENT_MANAGER_COUNT,
                "ended_care_workers": ENDED_CARE_WORKER_COUNT,
                "ended_social_workers": ENDED_SOCIAL_WORKER_COUNT,
                "ended_nurses": ENDED_NURSE_COUNT,
                "ended_managers": ENDED_MANAGER_COUNT,
            }
    finally:
        engine.dispose()


def main() -> None:
    summary = seed_extreme_test_data()
    print("EXTREME_TEST_DATA_SEED_OK")
    for key, value in summary.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
