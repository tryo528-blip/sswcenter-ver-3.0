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

SEED_MARKER = "SSWCENTER_EXTREME_TEST_DATA_V1"
ACTIVE_START = date(2026, 1, 1)
ENDED_START = date(2020, 1, 1)
ENDED_DATE = date(2025, 12, 31)
ACTIVE_CERTIFICATION_END = date(2099, 12, 31)

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

GIVEN_NAMES = (
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

ROLE_BY_POSITION = {
    "CARE_WORKER": "CARE_SERVICE",
    "SOCIAL_WORKER": "SOCIAL_WORK",
    "NURSE": "NURSING",
    "MANAGER": "MANAGEMENT_FUNCTION",
}


def _pseudonym(index: int) -> str:
    if index == 0:
        return "홍길동"
    zero_based = index - 1
    return FAMILY_NAMES[zero_based // len(GIVEN_NAMES)] + GIVEN_NAMES[zero_based % len(GIVEN_NAMES)]


def _birth_date(index: int, *, staff: bool) -> date:
    year_start = 1968 if staff else 1938
    year = year_start + (index % (24 if staff else 32))
    month = (index % 12) + 1
    day = (index % 27) + 1
    return date(year, month, day)


def _phone(index: int) -> str:
    return f"010-9000-{index:04d}"


def _local_database_guard(database_url: str) -> None:
    url = make_url(database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("extreme synthetic seed only permits a loopback PostgreSQL host")
    database_name = url.database or ""
    if not database_name.endswith(("_dev", "_test", "_review")):
        raise RuntimeError("extreme synthetic seed requires a development/test database name")


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
    staff = Staff(
        name=_pseudonym(name_index),
        birth_date=_birth_date(name_index, staff=True),
        sex_code="TEST",
        phone=_phone(sequence),
        phone_normalized=f"0109000{sequence:04d}",
        address="합성 테스트 주소",
        display_name=_pseudonym(name_index),
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
    recipient = Recipient(
        name=_pseudonym(name_index),
        birth_date=_birth_date(name_index, staff=False),
        sex_code="MALE" if sequence % 2 else "FEMALE",
        recipient_no=f"EXTREME-R-{sequence:04d}",
        memo=SEED_MARKER,
        postal_code="00000",
        address="합성 테스트 주소",
        mobile_phone=_phone(500 + sequence),
        created_by_account_id=account_id,
        updated_by_account_id=account_id,
    )
    database_session.add(recipient)
    database_session.flush()

    database_session.add(
        RecipientContract(
            recipient_id=recipient.id,
            service_type_id=service_type_id,
            start_date=start_date,
            end_date=end_date,
            service_start_date=start_date,
            end_reason_text="합성 테스트 종료" if ended else None,
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
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
        RecipientCertificationPeriod(
            recipient_id=recipient.id,
            start_date=start_date,
            end_date=end_date if ended else ACTIVE_CERTIFICATION_END,
            created_by_account_id=account_id,
            updated_by_account_id=account_id,
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

            total_staff = int(database_session.scalar(select(func.count()).select_from(Staff)) or 0)
            total_recipients = int(
                database_session.scalar(select(func.count()).select_from(Recipient)) or 0
            )
            if total_staff > 1 or total_recipients > 0:
                raise RuntimeError(
                    "refusing to mix extreme synthetic data into an existing non-empty database"
                )

            admin = _ensure_admin(database_session, settings)
            admin_staff = database_session.get(Staff, admin.staff_id)
            if admin_staff is None:
                raise RuntimeError("admin staff row is missing")
            admin_staff.memo = SEED_MARKER
            admin_staff.phone = _phone(0)
            admin_staff.phone_normalized = "01090000000"
            admin_staff.address = "합성 테스트 주소"

            staff_sequence = 1
            staff_name_index = 1
            for position_code, count in (
                ("CARE_WORKER", 150),
                ("SOCIAL_WORKER", 4),
                ("NURSE", 2),
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
                ("CARE_WORKER", 200),
                ("SOCIAL_WORKER", 5),
                ("NURSE", 1),
                ("MANAGER", 1),
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
            for ended, count in ((False, 150), (True, 200)):
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

            database_session.commit()
            return {
                "current_recipients": 150,
                "ended_recipients": 200,
                "current_care_workers": 150,
                "current_social_workers": 4,
                "current_nurses": 2,
                "current_managers": 1,
                "ended_care_workers": 200,
                "ended_social_workers": 5,
                "ended_nurses": 1,
                "ended_managers": 1,
            }
    except Exception:
        with factory() as rollback_session:
            rollback_session.rollback()
        raise
    finally:
        engine.dispose()


def main() -> None:
    summary = seed_extreme_test_data()
    print("EXTREME_TEST_DATA_SEED_OK")
    for key, value in summary.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
