from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.core.settings import Environment, get_settings
from app.db.models import (
    Recipient,
    UserAccount,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.recipient.detail_batch import (
    BasicGuardianMutation,
    RecipientBasicCreateBatchRequest,
)
from app.domains.recipient.schemas import (
    GuardianCreateRequest,
    GuardianResponse,
    RecipientCreateRequest,
    RecipientSexCode,
    RecipientUpdateRequest,
)
from app.domains.recipient.service import RecipientService
from app.domains.w1c.schemas import (
    BenefitCode,
    BenefitPeriodCreateRequest,
    BenefitPeriodReplacementRequest,
    CertificationIdentityCreateRequest,
    CertificationPeriodCreateRequest,
    GradeCode,
)
from app.domains.w1c.service import W1CService

SEED_MARKER = "SSWCENTER_DEV_RECIPIENTS_V1"
NAME_PREFIX = "테스트시드-"
TARGET_COUNT = 200
# Shared with RecipientService / W1CService: when set, _commit() only flushes.
_DEFER_COMMIT_KEY = "recipient_detail_batch_defer_commit"

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

# Real Korean city/province addresses: (postal_code, road_address, detail_address)
ADDRESSES: tuple[tuple[str, str, str], ...] = (
    ("04524", "서울특별시 중구 세종대로 110", "시청 1층"),
    ("06236", "서울특별시 강남구 테헤란로 152", "14층"),
    ("03722", "서울특별시 서대문구 연세로 50", "본관 201호"),
    ("48058", "부산광역시 해운대구 센텀중앙로 79", "센텀시티 902호"),
    ("49201", "부산광역시 서구 구덕로 179", "3층"),
    ("21554", "인천광역시 남동구 정각로 29", "501호"),
    ("21984", "인천광역시 연수구 컨벤시아대로 165", "301호"),
    ("41911", "대구광역시 중구 공평로 88", "1202호"),
    ("41560", "대구광역시 북구 대학로 80", "502호"),
    ("35242", "대전광역시 서구 둔산로 100", "808호"),
    ("34126", "대전광역시 유성구 대학로 99", "B동 201호"),
    ("61475", "광주광역시 동구 중앙로196번길 5", "403호"),
    ("61186", "광주광역시 북구 용봉로 77", "103동 1201호"),
    ("44691", "울산광역시 남구 중앙로 201", "701호"),
    ("44919", "울산광역시 울주군 언양읍 유니스트길 50", "게스트하우스 201호"),
    ("30120", "세종특별자치시 한누리대로 2130", "101호"),
    ("16419", "경기도 수원시 영통구 월드컵로 206", "805호"),
    ("10442", "경기도 고양시 일산동구 중앙로 1286", "703호"),
    ("13487", "경기도 성남시 분당구 판교로 242", "12층"),
    ("24232", "강원특별자치도 춘천시 강원대학길 1", "교수회관 101호"),
    ("26464", "강원특별자치도 원주시 흥업면 남원로 150", "205호"),
    ("28644", "충청북도 청주시 서원구 충대로 1", "2층"),
    ("27136", "충청북도 충주시 충열로 15", "302호"),
    ("31156", "충청남도 천안시 동남구 단대로 119", "기숙사 A동"),
    ("32588", "충청남도 공주시 공주대학로 56", "학생회관 1층"),
    ("54896", "전북특별자치도 전주시 덕진구 백제대로 567", "305호"),
    ("54538", "전북특별자치도 익산시 익산대로 460", "B동 1102호"),
    ("58554", "전라남도 목포시 대학로 166", "201호"),
    ("59626", "전라남도 순천시 중앙로 255", "604호"),
    ("37673", "경상북도 포항시 남구 청암로 77", "연구동 3층"),
    ("38541", "경상북도 경주시 태종로 677", "102동 1501호"),
    ("51508", "경상남도 창원시 의창구 창이대로 71", "1202호"),
    ("52828", "경상남도 진주시 진주대로 501", "공학관 4층"),
    ("63243", "제주특별자치도 제주시 제주대학로 102", "학생회관 2층"),
    ("63589", "제주특별자치도 서귀포시 중앙로 105", "3층"),
)

BENEFIT_CODES: tuple[BenefitCode, ...] = (
    BenefitCode.GENERAL,
    BenefitCode.BASIC_LIVELIHOOD,
    BenefitCode.MEDICAL_6,
    BenefitCode.MEDICAL_9,
)

GRADE_CODES: tuple[GradeCode, ...] = (
    GradeCode.GRADE_1,
    GradeCode.GRADE_2,
    GradeCode.GRADE_3,
    GradeCode.GRADE_4,
    GradeCode.GRADE_5,
)

# High L8… range avoids collision with extreme seed numbers (L0000000001…).
CERT_NUMBER_BASE = 8_000_000_000

RELATIONSHIP_TEXTS = (
    "배우자",
    "자녀",
    "며느리",
    "사위",
    "손자",
    "형제",
    "자매",
    "기타",
)

# Fixed fixtures that must appear among the 200 recipients.
SPECIAL_RECIPIENTS: tuple[dict[str, str], ...] = (
    {
        "name": "테스트 김하늘",
        "postal_code": "04158",
        "address": "서울특별시 마포구 마포대로 109",
        "address_detail": "101동 802호",
    },
    {
        "name": "테스트 박선우",
        "postal_code": "48058",
        "address": "부산광역시 해운대구 센텀중앙로 97",
        "address_detail": "1203호",
    },
)


def _pseudonym(index: int) -> str:
    zero_based = index % (len(FAMILY_NAMES) * len(GIVEN_NAMES))
    return FAMILY_NAMES[zero_based // len(GIVEN_NAMES)] + GIVEN_NAMES[zero_based % len(GIVEN_NAMES)]


def _birth_date(index: int) -> date:
    year = 1938 + (index % 40)
    month = (index % 12) + 1
    day = (index % 27) + 1
    return date(year, month, day)


def _phone(index: int) -> str:
    return f"010-{(8100 + (index % 900)):04d}-{(index % 10000):04d}"


def _compose_address(road: str, detail: str) -> str:
    road = road.strip()
    detail = detail.strip()
    if not detail:
        return road
    return f"{road} {detail}"


def _local_database_guard(database_url: str) -> None:
    url = make_url(database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("dev recipient seed only permits a loopback PostgreSQL host")
    database_name = url.database or ""
    if not database_name.endswith(("_dev", "_test", "_review")):
        raise RuntimeError("dev recipient seed requires a development/test database name")


def _require_admin_account(database_session: Session) -> CurrentAccount:
    admin = database_session.scalar(
        select(UserAccount)
        .where(UserAccount.active.is_(True), UserAccount.role_code == "ADMIN")
        .order_by(UserAccount.id.asc())
    )
    if admin is None:
        raise RuntimeError("active ADMIN account is required; bootstrap installation first")
    return CurrentAccount(admin.id, admin.display_name, admin.role_code)


def _benefit_start_text(index: int, *, today: date) -> str:
    # Keep the opaque display value immediately effective without treating it as a date in the API.
    offset_days = 30 + (index % 700)
    return (today - timedelta(days=offset_days)).isoformat()


def _build_guardians(index: int) -> list[BasicGuardianMutation]:
    # Roughly two-thirds of recipients get 1–2 guardians so mixed cases exist.
    mode = index % 3
    if mode == 0:
        return []

    guardians: list[BasicGuardianMutation] = [
        BasicGuardianMutation(
            slot=0,
            guardian_id=None,
            payload=GuardianCreateRequest(
                name=f"{_pseudonym(index + 17)}보호자",
                phone=_phone(2000 + index),
                relationship_text=RELATIONSHIP_TEXTS[index % len(RELATIONSHIP_TEXTS)],
                address=_compose_address(*ADDRESSES[index % len(ADDRESSES)][1:]),
            ),
        )
    ]
    if mode == 2:
        guardians.append(
            BasicGuardianMutation(
                slot=1,
                guardian_id=None,
                payload=GuardianCreateRequest(
                    name=f"{_pseudonym(index + 53)}보호자",
                    phone=_phone(3000 + index),
                    relationship_text=RELATIONSHIP_TEXTS[(index + 3) % len(RELATIONSHIP_TEXTS)],
                    address=_compose_address(*ADDRESSES[(index + 5) % len(ADDRESSES)][1:]),
                ),
            )
        )
    return guardians


def _attach_certification_and_grade(
    *,
    w1c_service: W1CService,
    recipient_id: int,
    index: int,
    today: date,
    current_account: CurrentAccount,
) -> None:
    """Attach diverse certification number + grade via the W1C service layer."""
    cert_number = f"L{CERT_NUMBER_BASE + index:010d}"
    cert_start = today - timedelta(days=365 + (index % 400))
    cert_end = today + timedelta(days=365 + (index % 200))
    grade_code = GRADE_CODES[index % len(GRADE_CODES)]

    w1c_service.create_identity(
        recipient_id,
        CertificationIdentityCreateRequest(certification_number=cert_number),
        current_account,
    )
    w1c_service.create_certification_period(
        recipient_id,
        CertificationPeriodCreateRequest(
            grade_code=grade_code,
            start_date=cert_start,
            end_date=cert_end,
        ),
        current_account,
    )


def _seed_recipient_name(index: int) -> str:
    if index < len(SPECIAL_RECIPIENTS):
        return SPECIAL_RECIPIENTS[index]["name"]
    return f"{NAME_PREFIX}{_pseudonym(index)}-{index:03d}"


def _build_batch_request(index: int) -> RecipientBasicCreateBatchRequest:
    sex_code = RecipientSexCode.MALE if index % 2 == 0 else RecipientSexCode.FEMALE
    guardians = _build_guardians(index)
    payer_slot: Literal[0, 1] | None
    if guardians:
        payer_slot = 0
    else:
        payer_slot = None

    if index < len(SPECIAL_RECIPIENTS):
        special = SPECIAL_RECIPIENTS[index]
        name = special["name"]
        postal_code = special["postal_code"]
        address = _compose_address(special["address"], special["address_detail"])
    else:
        postal_code, road, detail = ADDRESSES[index % len(ADDRESSES)]
        name = _seed_recipient_name(index)
        address = _compose_address(road, detail)

    return RecipientBasicCreateBatchRequest(
        recipient=RecipientCreateRequest(
            name=name,
            birth_date=_birth_date(index),
            sex_code=sex_code,
            postal_code=postal_code,
            address=address,
            mobile_phone=_phone(index),
            memo=SEED_MARKER,
        ),
        guardians=guardians,
        payer_guardian_slot=payer_slot,
    )


def _build_benefit_request(index: int, *, today: date) -> BenefitPeriodCreateRequest:
    return BenefitPeriodCreateRequest(
        benefit_code=BENEFIT_CODES[index % len(BENEFIT_CODES)],
        start_text=_benefit_start_text(index, today=today),
    )


def _count_seed_recipients(database_session: Session) -> int:
    return int(
        database_session.scalar(
            select(func.count()).select_from(Recipient).where(Recipient.memo == SEED_MARKER)
        )
        or 0
    )


def _create_seed_recipient(
    *,
    recipient_service: RecipientService,
    w1c_service: W1CService,
    index: int,
    today: date,
    current_account: CurrentAccount,
) -> None:
    """Create one full recipient (basic + cert/grade) without intermediate commits.

    Caller must set session.info[_DEFER_COMMIT_KEY] so service _commit() only flushes,
    then perform a single final commit for the whole seed run.
    """
    payload = _build_batch_request(index)
    recipient = recipient_service.create_recipient(payload.recipient, current_account)
    guardians: dict[int, GuardianResponse] = {}
    for mutation in sorted(payload.guardians, key=lambda item: item.slot):
        # Seed path only creates guardians (never updates).
        create_payload = cast(GuardianCreateRequest, mutation.payload)
        guardians[mutation.slot] = recipient_service.create_guardian(
            recipient.id,
            create_payload,
            current_account,
        )
    if payload.payer_guardian_slot is not None:
        recipient_service.update_recipient(
            recipient.id,
            RecipientUpdateRequest(
                expected_row_version=recipient.row_version,
                payer_guardian_id=guardians[payload.payer_guardian_slot].id,
            ),
            current_account,
        )
    # RecipientService creates the initial GENERAL benefit atomically with
    # the recipient. Replace that row instead of inserting a second active
    # benefit, which would violate the one-active-benefit constraint.
    initial_benefits = w1c_service.list_benefit_periods(recipient.id).items
    if len(initial_benefits) != 1:
        raise RuntimeError("SEED_RECIPIENT_INITIAL_BENEFIT_SHAPE_INVALID")
    initial_benefit = initial_benefits[0]
    desired_benefit = _build_benefit_request(index, today=today)
    w1c_service.replace_benefit_period(
        recipient.id,
        initial_benefit.id,
        BenefitPeriodReplacementRequest(
            expected_row_version=initial_benefit.row_version,
            benefit_code=desired_benefit.benefit_code,
            start_text=desired_benefit.start_text,
        ),
        current_account,
    )
    _attach_certification_and_grade(
        w1c_service=w1c_service,
        recipient_id=recipient.id,
        index=index,
        today=today,
        current_account=current_account,
    )


def seed_dev_recipients() -> dict[str, int | str]:
    """Seed TARGET_COUNT dev recipients in a single transaction, or no-op.

    Atomicity: all creates flush under _DEFER_COMMIT_KEY and commit once at the
    end. Failure rolls back the whole run, so this script cannot leave a partial
    marker set. Decision tree is therefore only marker count:

    - count >= TARGET_COUNT → already complete (no-op)
    - count == 0 → create all TARGET_COUNT recipients
    - 0 < count < TARGET_COUNT → anomalous external/legacy state; refuse and exit
    """
    settings = get_settings()
    if settings.environment is Environment.PRODUCTION:
        raise RuntimeError("dev recipient seed is forbidden in production")
    if settings.database_url is None:
        raise RuntimeError("SSWCENTER_DATABASE_URL is required")
    _local_database_guard(settings.database_url)

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as database_session:
            existing = _count_seed_recipients(database_session)
            if existing >= TARGET_COUNT:
                return {
                    "count": existing,
                    "created": 0,
                    "skipped": 1,
                    "status": "ALREADY_COMPLETE",
                }

            if existing > 0:
                # Impossible under this script's single-transaction model.
                # Do not create, modify, or delete — leave for human inspection.
                print(f"SEED_DEV_RECIPIENTS_UNEXPECTED_PARTIAL_STATE count={existing}")
                raise RuntimeError(
                    "SEED_DEV_RECIPIENTS_UNEXPECTED_PARTIAL_STATE: "
                    f"found {existing} marker-tagged recipients "
                    f"(0 < count < TARGET_COUNT={TARGET_COUNT}). "
                    "Single-transaction seeding cannot leave partial rows; "
                    "this is an anomalous state from another version or an external "
                    "factor. Inspect manually; this script will not create, modify, "
                    "or delete existing data."
                )

            current_account = _require_admin_account(database_session)
            recipient_service = RecipientService(database_session)
            w1c_service = W1CService(database_session)
            today = date.today()
            created = 0

            # Defer all service-layer commits; one final commit covers the whole run.
            database_session.info[_DEFER_COMMIT_KEY] = True
            try:
                for index in range(TARGET_COUNT):
                    name = _seed_recipient_name(index)
                    try:
                        _create_seed_recipient(
                            recipient_service=recipient_service,
                            w1c_service=w1c_service,
                            index=index,
                            today=today,
                            current_account=current_account,
                        )
                    except Exception as exc:
                        database_session.rollback()
                        raise RuntimeError(
                            "dev recipient seed failed mid-run; "
                            "rolled back all uncommitted work from this execution "
                            f"(index={index}, name={name!r}, "
                            f"flushed_before_failure={created}). cause={exc}"
                        ) from exc
                    created += 1

                database_session.commit()
            except Exception:
                if database_session.in_transaction():
                    database_session.rollback()
                raise
            finally:
                database_session.info.pop(_DEFER_COMMIT_KEY, None)

            final_count = _count_seed_recipients(database_session)
            if final_count < TARGET_COUNT:
                raise RuntimeError(
                    f"seed ended with marker_count={final_count} < TARGET_COUNT={TARGET_COUNT}"
                )

            return {
                "count": final_count,
                "created": created,
                "skipped": 0,
                "status": "COMPLETE",
            }
    finally:
        engine.dispose()


def main() -> None:
    summary = seed_dev_recipients()
    print(
        f"SEED_DEV_RECIPIENTS_{summary['status']} "
        f"count={summary['count']} created={summary['created']} skipped={summary['skipped']}"
    )


if __name__ == "__main__":
    main()
