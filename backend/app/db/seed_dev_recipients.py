from __future__ import annotations

from datetime import date, timedelta
from typing import Literal, TypeVar, cast

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.core.settings import Environment, get_settings
from app.db.models import (
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationIdentity,
    RecipientCertificationPeriod,
    RecipientGuardian,
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
from app.domains.recipient.service import RecipientService, today_seoul
from app.domains.w1c.schemas import (
    BenefitCode,
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

T = TypeVar("T")

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

# Long-term-care-aged given names. Combined with FAMILY_NAMES they stay unique
# across TARGET_COUNT without a numeric suffix.
GIVEN_NAMES = (
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

# Public-place roads plus clearly synthetic residential units.
ADDRESSES: tuple[tuple[str, str, str], ...] = (
    ("04524", "서울특별시 중구 세종대로 110", "시드센터 합성 101동 102호"),
    ("06236", "서울특별시 강남구 테헤란로 152", "시드센터 합성 1403호"),
    ("03722", "서울특별시 서대문구 연세로 50", "시드센터 합성 본관 201호"),
    ("48058", "부산광역시 해운대구 센텀중앙로 79", "시드센터 합성 902호"),
    ("49201", "부산광역시 서구 구덕로 179", "시드센터 합성 3층 301호"),
    ("21554", "인천광역시 남동구 정각로 29", "시드센터 합성 501호"),
    ("21984", "인천광역시 연수구 컨벤시아대로 165", "시드센터 합성 301호"),
    ("41911", "대구광역시 중구 공평로 88", "시드센터 합성 1202호"),
    ("41560", "대구광역시 북구 대학로 80", "시드센터 합성 502호"),
    ("35242", "대전광역시 서구 둔산로 100", "시드센터 합성 808호"),
    ("34126", "대전광역시 유성구 대학로 99", "시드센터 합성 B동 201호"),
    ("61475", "광주광역시 동구 중앙로196번길 5", "시드센터 합성 403호"),
    ("61186", "광주광역시 북구 용봉로 77", "시드센터 합성 103동 1201호"),
    ("44691", "울산광역시 남구 중앙로 201", "시드센터 합성 701호"),
    ("44919", "울산광역시 울주군 언양읍 유니스트길 50", "시드센터 합성 201호"),
    ("30120", "세종특별자치시 한누리대로 2130", "시드센터 합성 101호"),
    ("16419", "경기도 수원시 영통구 월드컵로 206", "시드센터 합성 805호"),
    ("10442", "경기도 고양시 일산동구 중앙로 1286", "시드센터 합성 703호"),
    ("13487", "경기도 성남시 분당구 판교로 242", "시드센터 합성 12층 1201호"),
    ("24232", "강원특별자치도 춘천시 강원대학길 1", "시드센터 합성 101호"),
    ("26464", "강원특별자치도 원주시 흥업면 남원로 150", "시드센터 합성 205호"),
    ("28644", "충청북도 청주시 서원구 충대로 1", "시드센터 합성 2층 201호"),
    ("27136", "충청북도 충주시 충열로 15", "시드센터 합성 302호"),
    ("31156", "충청남도 천안시 동남구 단대로 119", "시드센터 합성 A동 415호"),
    ("32588", "충청남도 공주시 공주대학로 56", "시드센터 합성 1층 102호"),
    ("54896", "전북특별자치도 전주시 덕진구 백제대로 567", "시드센터 합성 305호"),
    ("54538", "전북특별자치도 익산시 익산대로 460", "시드센터 합성 B동 1102호"),
    ("58554", "전라남도 목포시 대학로 166", "시드센터 합성 201호"),
    ("59626", "전라남도 순천시 중앙로 255", "시드센터 합성 604호"),
    ("37673", "경상북도 포항시 남구 청암로 77", "시드센터 합성 3층 305호"),
    ("38541", "경상북도 경주시 태종로 677", "시드센터 합성 102동 1501호"),
    ("51508", "경상남도 창원시 의창구 창이대로 71", "시드센터 합성 1202호"),
    ("52828", "경상남도 진주시 진주대로 501", "시드센터 합성 4층 401호"),
    ("63243", "제주특별자치도 제주시 제주대학로 102", "시드센터 합성 2층 203호"),
    ("63589", "제주특별자치도 서귀포시 중앙로 105", "시드센터 합성 3층 301호"),
)

BENEFIT_CODES: tuple[BenefitCode, ...] = (
    BenefitCode.GENERAL,
    BenefitCode.BASIC_LIVELIHOOD,
    BenefitCode.REDUCTION_6,
    BenefitCode.REDUCTION_9,
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

_SHARE_SURNAME = frozenset({"자녀", "손자", "형제", "자매"})

# Fixed fixtures that must appear among the 200 recipients.
SPECIAL_RECIPIENTS: tuple[dict[str, str], ...] = (
    {
        "name": "테스트 김하늘",
        "postal_code": "04158",
        "address": "서울특별시 마포구 마포대로 109",
    },
    {
        "name": "테스트 박선우",
        "postal_code": "48058",
        "address": "부산광역시 해운대구 센텀중앙로 97",
    },
)


def _weighted_cycle(pairs: tuple[tuple[T, int], ...]) -> tuple[T, ...]:
    items: list[T] = []
    for value, weight in pairs:
        items.extend([value] * weight)
    return tuple(items)


# Weighted toward typical long-term-care ages. Not official statistics.
_AGE_YEARS: tuple[int, ...] = tuple(
    year
    for min_age, max_age, weight in (
        (65, 69, 1),
        (70, 74, 2),
        (75, 79, 3),
        (80, 84, 4),
        (85, 89, 4),
        (90, 95, 2),
    )
    for year in range(2026 - max_age, 2026 - min_age + 1)
    for _ in range(weight)
)

_GRADE_CYCLE = _weighted_cycle(
    (
        (GradeCode.GRADE_1, 1),
        (GradeCode.GRADE_2, 2),
        (GradeCode.GRADE_3, 5),
        (GradeCode.GRADE_4, 5),
        (GradeCode.GRADE_5, 2),
    )
)

_BENEFIT_CYCLE = _weighted_cycle(
    (
        (BenefitCode.GENERAL, 8),
        (BenefitCode.BASIC_LIVELIHOOD, 2),
        (BenefitCode.REDUCTION_6, 2),
        (BenefitCode.REDUCTION_9, 2),
        (BenefitCode.MEDICAL_6, 1),
        (BenefitCode.MEDICAL_9, 1),
    )
)

_RELATIONSHIP_CYCLE = _weighted_cycle(
    (
        ("자녀", 6),
        ("배우자", 5),
        ("며느리", 2),
        ("사위", 1),
        ("손자", 1),
        ("형제", 1),
        ("자매", 1),
        ("기타", 1),
    )
)


def _recipient_memo(index: int) -> str:
    return f"{SEED_MARKER}|{index:03d}"


def _expected_memos() -> tuple[str, ...]:
    return tuple(_recipient_memo(index) for index in range(TARGET_COUNT))


def _pseudonym(index: int) -> str:
    zero_based = index % (len(FAMILY_NAMES) * len(GIVEN_NAMES))
    return FAMILY_NAMES[zero_based // len(GIVEN_NAMES)] + GIVEN_NAMES[zero_based % len(GIVEN_NAMES)]


def _family_name(name: str) -> str:
    compact = name.replace("테스트 ", "").replace(NAME_PREFIX, "").strip()
    return compact[0] if compact else "김"


def _birth_date(index: int) -> date:
    year = _AGE_YEARS[index % len(_AGE_YEARS)]
    month = (index % 12) + 1
    day = (index % 28) + 1
    return date(year, month, day)


def _phone(index: int) -> str:
    return f"010-0701-{index:04d}"


def _compose_address(road: str, detail: str) -> str:
    road = road.strip()
    detail = detail.strip()
    if not detail:
        return road
    return f"{road} {detail}"


def _unit_detail(index: int) -> str:
    dong = (index % 20) + 1
    ho = 100 + index
    return f"시드센터 합성 {dong}동 {ho}호"


def _recipient_address(index: int) -> tuple[str, str]:
    unit = _unit_detail(index)
    if index < len(SPECIAL_RECIPIENTS):
        special = SPECIAL_RECIPIENTS[index]
        return special["postal_code"], _compose_address(special["address"], unit)
    postal_code, road, _ignored = ADDRESSES[index % len(ADDRESSES)]
    return postal_code, _compose_address(road, unit)


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


def _benefit_start_date(index: int, *, today: date) -> date:
    offset_days = 30 + (index % 700)
    return today - timedelta(days=offset_days)


def _benefit_start_text(start_date: date) -> str:
    return f"{start_date.year}년 {start_date.month}월 {start_date.day}일부터"


def _grade_code(index: int) -> GradeCode:
    return _GRADE_CYCLE[index % len(_GRADE_CYCLE)]


def _benefit_code(index: int) -> BenefitCode:
    return _BENEFIT_CYCLE[index % len(_BENEFIT_CYCLE)]


def _relationship_text(index: int, slot: int) -> str:
    return _RELATIONSHIP_CYCLE[(index + slot * 7) % len(_RELATIONSHIP_CYCLE)]


def _guardian_name(recipient_name: str, index: int, relationship_text: str) -> str:
    family = _family_name(recipient_name)
    given = GIVEN_NAMES[(index + 17) % len(GIVEN_NAMES)]
    if relationship_text in _SHARE_SURNAME:
        return family + given
    other_family = FAMILY_NAMES[(index + 11) % len(FAMILY_NAMES)]
    if other_family == family:
        other_family = FAMILY_NAMES[(index + 12) % len(FAMILY_NAMES)]
    return other_family + given


def _build_guardian_payload(
    *,
    index: int,
    recipient_name: str,
    recipient_address: str,
    slot: int,
) -> GuardianCreateRequest:
    relationship_text = _relationship_text(index, slot)
    same_house = relationship_text in {"배우자", "자녀"}
    if same_house:
        address = recipient_address
    else:
        address = _compose_address(*ADDRESSES[(index + 5 + slot) % len(ADDRESSES)][1:])
        if "시드센터 합성" not in address:
            address = f"{address} 시드센터 합성 별거 {index:03d}호"
    return GuardianCreateRequest(
        name=_guardian_name(recipient_name, index + slot * 31, relationship_text),
        phone=_phone(2000 + index + slot * 1000),
        relationship_text=relationship_text,
        address=address,
    )


def _build_guardians(
    index: int,
    *,
    recipient_name: str,
    recipient_address: str,
) -> list[BasicGuardianMutation]:
    mode = index % 3
    if mode == 0:
        return []

    guardians: list[BasicGuardianMutation] = [
        BasicGuardianMutation(
            slot=0,
            guardian_id=None,
            payload=_build_guardian_payload(
                index=index,
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                slot=0,
            ),
        )
    ]
    if mode == 2:
        guardians.append(
            BasicGuardianMutation(
                slot=1,
                guardian_id=None,
                payload=_build_guardian_payload(
                    index=index,
                    recipient_name=recipient_name,
                    recipient_address=recipient_address,
                    slot=1,
                ),
            )
        )
    return guardians


def _payer_guardian_slot(index: int, guardian_count: int) -> Literal[0, 1] | None:
    if guardian_count == 0:
        return None
    # Recipients with guardians still include self-payers.
    if index % 3 == 1:
        return None
    return 0


def _attach_certification_and_grade(
    *,
    w1c_service: W1CService,
    recipient_id: int,
    index: int,
    today: date,
    current_account: CurrentAccount,
) -> None:
    cert_number = f"L{CERT_NUMBER_BASE + index:010d}"
    cert_start = today - timedelta(days=365 + (index % 400))
    cert_end = today + timedelta(days=365 + (index % 200))
    w1c_service.create_identity(
        recipient_id,
        CertificationIdentityCreateRequest(certification_number=cert_number),
        current_account,
    )
    w1c_service.create_certification_period(
        recipient_id,
        CertificationPeriodCreateRequest(
            grade_code=_grade_code(index),
            start_date=cert_start,
            end_date=cert_end,
        ),
        current_account,
    )


def _seed_recipient_name(index: int) -> str:
    if index < len(SPECIAL_RECIPIENTS):
        return SPECIAL_RECIPIENTS[index]["name"]
    return _pseudonym(index)


def _apply_seed_benefit(
    *,
    w1c_service: W1CService,
    recipient_id: int,
    index: int,
    today: date,
    current_account: CurrentAccount,
) -> None:
    """Replace the auto-inserted GENERAL benefit with the intended seed code.

    RecipientService.create_recipient always inserts an active GENERAL period.
    A second create would violate the one-active-benefit unique index, so the
    seed uses the official replace path and keeps start_text display-only.
    Code equality alone must not keep a blank start_text.
    """
    existing = w1c_service.list_benefit_periods(recipient_id)
    active = next((item for item in existing.items if item.invalidated_at_utc is None), None)
    if active is None:
        raise RuntimeError("create_recipient must insert an active benefit period")
    intended = _benefit_code(index)
    start_text = _benefit_start_text(_benefit_start_date(index, today=today))
    if active.benefit_code == intended and active.start_text == start_text:
        return
    w1c_service.replace_benefit_period(
        recipient_id,
        active.id,
        BenefitPeriodReplacementRequest(
            benefit_code=intended,
            start_text=start_text,
            expected_row_version=active.row_version,
        ),
        current_account,
    )


def _build_batch_request(index: int) -> RecipientBasicCreateBatchRequest:
    sex_code = RecipientSexCode.MALE if index % 2 == 0 else RecipientSexCode.FEMALE
    name = _seed_recipient_name(index)
    postal_code, address = _recipient_address(index)
    guardians = _build_guardians(
        index,
        recipient_name=name,
        recipient_address=address,
    )
    return RecipientBasicCreateBatchRequest(
        recipient=RecipientCreateRequest(
            name=name,
            birth_date=_birth_date(index),
            sex_code=sex_code,
            postal_code=postal_code,
            address=address,
            mobile_phone=_phone(index),
            memo=_recipient_memo(index),
        ),
        guardians=guardians,
        payer_guardian_slot=_payer_guardian_slot(index, len(guardians)),
    )


def _load_expected_recipients(database_session: Session) -> list[Recipient]:
    return list(
        database_session.scalars(
            select(Recipient).where(Recipient.memo.in_(_expected_memos()))
        ).all()
    )


def _load_extra_marked_recipients(database_session: Session) -> list[Recipient]:
    return list(
        database_session.scalars(
            select(Recipient).where(
                Recipient.memo.is_not(None),
                func.strpos(Recipient.memo, SEED_MARKER) > 0,
                Recipient.memo.notin_(_expected_memos()),
            )
        ).all()
    )


def _recipient_by_memo(rows: list[Recipient]) -> dict[str, list[Recipient]]:
    grouped: dict[str, list[Recipient]] = {}
    for row in rows:
        grouped.setdefault(row.memo or "", []).append(row)
    return grouped


def dev_seed_integrity_errors(database_session: Session) -> tuple[str, ...]:
    rows = _load_expected_recipients(database_session)
    extras = _load_extra_marked_recipients(database_session)
    errors: list[str] = []
    if extras:
        errors.append(f"extra_marked:{len(extras)}")
    grouped = _recipient_by_memo(rows)
    for memo, group in grouped.items():
        if len(group) > 1:
            errors.append(f"duplicate_memo:{memo}")
    if len(grouped) > TARGET_COUNT:
        errors.append(f"count:{len(rows)}")
    for index in range(TARGET_COUNT):
        memo = _recipient_memo(index)
        matches = grouped.get(memo, [])
        if not matches:
            errors.append(f"missing_recipient:{index:03d}")
            continue
        if len(matches) != 1:
            continue
        errors.extend(_validate_expected_recipient(database_session, matches[0], index))
    return tuple(errors)


def _validate_expected_recipient(
    database_session: Session,
    recipient: Recipient,
    index: int,
) -> list[str]:
    payload = _build_batch_request(index)
    errors: list[str] = []
    expected = payload.recipient
    if recipient.name != expected.name:
        errors.append(f"name:{index:03d}")
    if recipient.birth_date != expected.birth_date:
        errors.append(f"birth:{index:03d}")
    if recipient.mobile_phone != expected.mobile_phone:
        errors.append(f"phone:{index:03d}")
    if recipient.address != expected.address:
        errors.append(f"address:{index:03d}")
    guardians = list(
        database_session.scalars(
            select(RecipientGuardian)
            .where(RecipientGuardian.recipient_id == recipient.id)
            .order_by(RecipientGuardian.slot_no.asc())
        ).all()
    )
    if len(guardians) != len(payload.guardians):
        errors.append(f"guardian_count:{index:03d}")
    else:
        for mutation, guardian in zip(payload.guardians, guardians, strict=True):
            create_payload = cast(GuardianCreateRequest, mutation.payload)
            if (
                guardian.name != create_payload.name
                or guardian.relationship_text != create_payload.relationship_text
            ):
                errors.append(f"guardian:{index:03d}:{mutation.slot}")
    if payload.payer_guardian_slot is None:
        if recipient.payer_guardian_id is not None:
            errors.append(f"payer:{index:03d}")
    elif not guardians:
        errors.append(f"payer:{index:03d}")
    elif recipient.payer_guardian_id != guardians[payload.payer_guardian_slot].id:
        errors.append(f"payer:{index:03d}")
    identity = database_session.get(RecipientCertificationIdentity, recipient.id)
    expected_number = f"L{CERT_NUMBER_BASE + index:010d}"
    if identity is None or identity.certification_number != expected_number:
        errors.append(f"cert_identity:{index:03d}")
    period = database_session.scalar(
        select(RecipientCertificationPeriod).where(
            RecipientCertificationPeriod.recipient_id == recipient.id,
            RecipientCertificationPeriod.invalidated_at_utc.is_(None),
        )
    )
    if period is None or period.grade_code != _grade_code(index).value:
        errors.append(f"cert_period:{index:03d}")
    benefit = database_session.scalar(
        select(RecipientBenefitPeriod).where(
            RecipientBenefitPeriod.recipient_id == recipient.id,
            RecipientBenefitPeriod.invalidated_at_utc.is_(None),
        )
    )
    if benefit is None:
        errors.append(f"benefit:{index:03d}")
    else:
        if benefit.benefit_code != _benefit_code(index).value:
            errors.append(f"benefit_code:{index:03d}")
        if not (benefit.start_text or "").strip():
            errors.append(f"benefit_start_text:{index:03d}")
    return errors


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
    _apply_seed_benefit(
        w1c_service=w1c_service,
        recipient_id=recipient.id,
        index=index,
        today=today,
        current_account=current_account,
    )
    _attach_certification_and_grade(
        w1c_service=w1c_service,
        recipient_id=recipient.id,
        index=index,
        today=today,
        current_account=current_account,
    )


def _refuse(message: str) -> None:
    print(message)
    raise RuntimeError(message)


def seed_dev_recipients() -> dict[str, int | str]:
    """Seed TARGET_COUNT dev recipients in a single transaction, or no-op.

    Complete is exactly 200 valid expected-marker recipients. 201, missing,
    extra, duplicate, or a broken subordinate graph fail closed.
    Existing unmarked rows may remain; this seed only supplements them.
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
            expected_rows = _load_expected_recipients(database_session)
            extras = _load_extra_marked_recipients(database_session)
            expected_count = len(expected_rows)
            extra_count = len(extras)
            if extra_count or expected_count > TARGET_COUNT:
                _refuse(
                    "SEED_DEV_RECIPIENTS_UNEXPECTED_PARTIAL_STATE "
                    f"count={expected_count} extras={extra_count} "
                    f"(complete requires exactly {TARGET_COUNT} expected marker rows)"
                )
            if expected_count == TARGET_COUNT:
                errors = dev_seed_integrity_errors(database_session)
                if errors:
                    _refuse(
                        "SEED_DEV_RECIPIENTS_UNEXPECTED_PARTIAL_STATE "
                        f"count={expected_count} integrity_errors={list(errors[:12])}"
                    )
                return {
                    "count": expected_count,
                    "created": 0,
                    "skipped": 1,
                    "status": "ALREADY_COMPLETE",
                }
            if expected_count > 0:
                _refuse(
                    "SEED_DEV_RECIPIENTS_UNEXPECTED_PARTIAL_STATE: "
                    f"found {expected_count} marker-tagged recipients "
                    f"(0 < count < TARGET_COUNT={TARGET_COUNT}). "
                    "Single-transaction seeding cannot leave partial rows; "
                    "this is an anomalous state from another version or an external "
                    "factor. Inspect manually; this script will not create, modify, "
                    "or delete existing data."
                )

            current_account = _require_admin_account(database_session)
            recipient_service = RecipientService(database_session)
            w1c_service = W1CService(database_session)
            today = today_seoul()
            created = 0

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

                errors = dev_seed_integrity_errors(database_session)
                final_count = len(_load_expected_recipients(database_session))
                extra_after = _load_extra_marked_recipients(database_session)
                if errors or final_count != TARGET_COUNT or extra_after:
                    raise RuntimeError(
                        "seed ended with invalid marker graph "
                        f"count={final_count} extras={len(extra_after)} "
                        f"errors={list(errors[:12])}"
                    )
                database_session.commit()
            except Exception:
                if database_session.in_transaction():
                    database_session.rollback()
                raise
            finally:
                database_session.info.pop(_DEFER_COMMIT_KEY, None)

            return {
                "count": TARGET_COUNT,
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
