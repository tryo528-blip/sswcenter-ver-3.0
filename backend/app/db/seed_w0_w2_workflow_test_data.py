from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.auth import BootstrapInput, CurrentAccount, bootstrap_installation
from app.core.settings import Environment, Settings, get_settings
from app.db.models import (
    CareAssignment,
    LicenseType,
    Recipient,
    RecipientBenefitPeriod,
    RecipientCertificationIdentity,
    RecipientCertificationPeriod,
    RecipientContract,
    RecipientGuardian,
    RecipientServicePlanNotice,
    ServiceType,
    Staff,
    StaffEmployment,
    StaffLicense,
    StaffOperationalRolePeriod,
    StaffPositionPeriod,
    StaffSensitiveIdentity,
    StaffServiceQualificationPeriod,
    UserAccount,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.db.w2_models import (
    MonthlyProfessionalAssignment,
    W2OfficialWorkCard,
    W2Schedule,
    W2ScheduleStaff,
)
from app.domains.recipient.schemas import (
    GuardianCreateRequest,
    RecipientCreateRequest,
    RecipientSexCode,
    RecipientStatus,
    RecipientUpdateRequest,
)
from app.domains.recipient.service import RecipientService
from app.domains.staff.schemas import (
    InitialEmploymentRequest,
    InitialOperationalRoleRequest,
    InitialPositionRequest,
    PositionCode,
    StaffCreateRequest,
    StaffCreateSexCode,
    StaffEmploymentCloseRequest,
    StaffLicenseCreateRequest,
    StaffServiceQualificationCreateRequest,
)
from app.domains.staff.service import StaffService
from app.domains.w1c.schemas import (
    BenefitCode,
    BenefitPeriodReplacementRequest,
    CertificationIdentityCreateRequest,
    CertificationPeriodCreateRequest,
    GradeCode,
)
from app.domains.w1c.service import W1CService
from app.domains.w1d.schemas import ContractCreateRequest, ServiceTypeCode
from app.domains.w1d.service import W1DService
from app.domains.w1e.schemas import AssignmentKind, CareAssignmentCreateRequest
from app.domains.w1e.service import W1EService
from app.domains.w2.schemas import (
    ProfessionalAssignmentCreateRequest,
    ScheduleCreateRequest,
    ScheduleStaffInput,
)
from app.domains.w2.service import W2Service

SEED_MARKER = "SSWCENTER_W0_W2_WORKFLOW_TEST_DATA_V1"
SEED_VERSION = 1
_DEFER_COMMIT_KEY = "recipient_detail_batch_defer_commit"
_ORIGINAL_COMMIT_KEY = "sswcenter_workflow_seed_original_commit"
_SEOUL = ZoneInfo("Asia/Seoul")

SERVICE_MONTH = date(2026, 8, 1)
SERVICE_MONTH_END = date(2026, 8, 31)
ACTIVE_START = date(2025, 1, 2)
ENDED_START = date(2023, 3, 1)
ENDED_END = date(2025, 12, 31)
CONTRACT_START = date(2026, 1, 5)
ENDED_CONTRACT_START = date(2024, 1, 2)
CERT_START = date(2025, 6, 1)
CERT_END = date(2027, 5, 31)
LICENSE_ISSUED = date(2024, 3, 1)
CERT_NUMBER_BASE = 9_000_000_001
BENEFIT_START_TEXT = "2026년 1월 5일부터"

ROLE_BY_POSITION = {
    PositionCode.CARE_WORKER: "CARE_SERVICE",
    PositionCode.SOCIAL_WORKER: "SOCIAL_WORK",
    PositionCode.NURSE: "NURSING",
    PositionCode.MANAGER: "MANAGEMENT_FUNCTION",
}

# Official cards / plan notices / replacements / account-owned todos stay out.
BOUNDARY_EXCLUSIONS: tuple[str, ...] = (
    "W2-D01 official work card automatic assignee",
    "W2-D01 service-plan notice generation",
    "W2-D02 replacement lineage",
    "W2 personal todo (ADMIN cannot own; USER would invent credentials)",
    "W3 parser/RFID/import",
    "W4/W5 data",
)

GRAPH_INTEGRITY_DIMENSIONS: tuple[str, ...] = (
    "staff_marker_keys",
    "staff_realistic_fields",
    "staff_sensitive_identity",
    "staff_employment_dates",
    "staff_position_periods",
    "staff_operational_role_periods",
    "staff_licenses",
    "staff_service_qualifications",
    "recipient_marker_keys_status_payer",
    "guardians_relationship",
    "certification_identity_grade_period",
    "current_benefit_code_start_text",
    "service_type_contracts_dates",
    "w1e_assignments_staff_dates_kind",
    "monthly_professionals",
    "w2_schedules_month_service_time_staff",
    "home_bath_two_worker",
    "no_replacement_lineage",
    "no_marked_recipient_official_cards",
    "no_marked_contract_plan_notices",
)


@dataclass(frozen=True)
class StaffScenario:
    key: str
    name: str
    sex_code: StaffCreateSexCode
    birth_date: date
    position_code: PositionCode
    ended: bool
    license_type_code: str | None
    qualification_codes: tuple[str, ...]
    phone_index: int
    address: str


@dataclass(frozen=True)
class RecipientScenario:
    key: str
    name: str
    sex_code: RecipientSexCode
    birth_date: date
    status: RecipientStatus
    benefit_code: BenefitCode
    grade_code: GradeCode
    self_payer: bool
    guardian_relationship: str | None
    guardian_name: str | None
    service_type_codes: tuple[ServiceTypeCode, ...]
    postal_code: str
    road_address: str
    unit_detail: str
    phone_index: int
    cert_offset: int


@dataclass(frozen=True)
class AssignmentSpec:
    recipient_key: str
    service_type_code: str
    staff_key: str
    start_date: date
    end_date: date | None
    assignment_kind: AssignmentKind = AssignmentKind.GENERAL


@dataclass(frozen=True)
class ProfessionalSpec:
    recipient_key: str
    staff_key: str
    service_month: date = SERVICE_MONTH
    start_date: date = SERVICE_MONTH
    end_date: date = SERVICE_MONTH_END


@dataclass(frozen=True)
class ScheduleSpec:
    recipient_key: str
    service_type_code: str
    day: int
    start_hour: int
    end_hour: int
    staff_keys: tuple[str, ...]


@dataclass(frozen=True)
class ObservedStaff:
    key: str
    name: str
    sex_code: str
    birth_date: date
    phone: str | None
    address: str | None
    has_sensitive_identity: bool
    employment_start: date | None
    employment_end: date | None
    end_reason_code: str | None
    position_code: str | None
    position_start: date | None
    position_end: date | None
    role_code: str | None
    role_start: date | None
    role_end: date | None
    license_type_code: str | None
    qualification_codes: tuple[str, ...]


@dataclass(frozen=True)
class ObservedGuardian:
    name: str | None
    relationship_text: str | None


@dataclass(frozen=True)
class ObservedRecipient:
    key: str
    name: str | None
    sex_code: str | None
    birth_date: date | None
    status: str
    phone: str | None
    address: str | None
    self_payer: bool
    guardians: tuple[ObservedGuardian, ...]
    certification_number: str | None
    grade_code: str | None
    cert_start: date | None
    cert_end: date | None
    benefit_code: str | None
    benefit_start_text: str | None
    contract_codes: tuple[str, ...]
    contract_dates: tuple[tuple[str, date, date | None], ...]


@dataclass(frozen=True)
class ObservedAssignment:
    recipient_key: str
    service_type_code: str
    staff_key: str
    start_date: date
    end_date: date | None
    assignment_kind: str


@dataclass(frozen=True)
class ObservedProfessional:
    recipient_key: str
    staff_key: str
    service_month: date
    start_date: date
    end_date: date


@dataclass(frozen=True)
class ObservedSchedule:
    recipient_key: str
    service_type_code: str
    day: int
    start_hour: int
    end_hour: int
    staff_keys: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedInventory:
    staff: int
    active_staff: int
    ended_staff: int
    recipients: int
    active_recipients: int
    waiting_recipients: int
    ended_recipients: int
    guardians: int
    payer_guardians: int
    certification_identities: int
    active_certification_periods: int
    active_benefits: int
    staff_sensitive_identities: int
    staff_licenses: int
    staff_qualifications: int
    contracts: int
    care_assignments: int
    monthly_professional_assignments: int
    schedules: int
    schedule_staff: int
    home_bath_two_worker_schedules: int
    official_work_cards: int
    service_plan_notices: int
    personal_todos: int
    replacement_lineage: int


@dataclass(frozen=True)
class MeasuredInventory:
    staff: int
    active_staff: int
    ended_staff: int
    recipients: int
    active_recipients: int
    waiting_recipients: int
    ended_recipients: int
    guardians: int
    payer_guardians: int
    certification_identities: int
    active_certification_periods: int
    active_benefits: int
    staff_sensitive_identities: int
    staff_licenses: int
    staff_qualifications: int
    contracts: int
    care_assignments: int
    monthly_professional_assignments: int
    schedules: int
    schedule_staff: int
    home_bath_two_worker_schedules: int
    official_work_cards: int
    service_plan_notices: int
    personal_todos_seed_created: int
    replacement_lineage: int
    integrity_errors: tuple[str, ...]


STAFF_SCENARIOS: tuple[StaffScenario, ...] = (
    StaffScenario(
        key="CW_HOME_A",
        name="김은정",
        sex_code=StaffCreateSexCode.FEMALE,
        birth_date=date(1988, 3, 12),
        position_code=PositionCode.CARE_WORKER,
        ended=False,
        license_type_code="CARE_WORKER",
        qualification_codes=("HOME_CARE", "HOME_BATH"),
        phone_index=1,
        address="서울특별시 중구 세종대로 110 시드센터 합성 직원숙소 A-201호",
    ),
    StaffScenario(
        key="CW_HOME_B",
        name="박성호",
        sex_code=StaffCreateSexCode.MALE,
        birth_date=date(1991, 7, 8),
        position_code=PositionCode.CARE_WORKER,
        ended=False,
        license_type_code="CARE_WORKER",
        qualification_codes=("HOME_CARE", "HOME_BATH"),
        phone_index=2,
        address="서울특별시 중구 세종대로 110 시드센터 합성 직원숙소 A-202호",
    ),
    StaffScenario(
        key="CW_OTHER",
        name="최지혜",
        sex_code=StaffCreateSexCode.FEMALE,
        birth_date=date(1985, 11, 21),
        position_code=PositionCode.CARE_WORKER,
        ended=False,
        license_type_code="CARE_WORKER",
        qualification_codes=("TEMP_HOME_CARE", "HOSPITAL_ESCORT", "BARO_CARE"),
        phone_index=3,
        address="서울특별시 서대문구 연세로 50 시드센터 합성 직원숙소 B-105호",
    ),
    StaffScenario(
        key="SW_ACTIVE",
        name="강태현",
        sex_code=StaffCreateSexCode.MALE,
        birth_date=date(1982, 5, 3),
        position_code=PositionCode.SOCIAL_WORKER,
        ended=False,
        license_type_code="SOCIAL_WORKER",
        qualification_codes=(),
        phone_index=4,
        address="서울특별시 마포구 마포대로 109 시드센터 합성 직원숙소 C-301호",
    ),
    StaffScenario(
        key="NU_ACTIVE",
        name="정소연",
        sex_code=StaffCreateSexCode.FEMALE,
        birth_date=date(1980, 9, 18),
        position_code=PositionCode.NURSE,
        ended=False,
        license_type_code="NURSE",
        qualification_codes=(),
        phone_index=5,
        address="서울특별시 마포구 마포대로 109 시드센터 합성 직원숙소 C-302호",
    ),
    StaffScenario(
        key="MG_ACTIVE",
        name="윤재혁",
        sex_code=StaffCreateSexCode.MALE,
        birth_date=date(1976, 2, 27),
        position_code=PositionCode.MANAGER,
        ended=False,
        license_type_code=None,
        qualification_codes=(),
        phone_index=6,
        address="서울특별시 중구 세종대로 110 시드센터 합성 관리실",
    ),
    StaffScenario(
        key="CW_ENDED",
        name="장민호",
        sex_code=StaffCreateSexCode.MALE,
        birth_date=date(1979, 4, 14),
        position_code=PositionCode.CARE_WORKER,
        ended=True,
        license_type_code="CARE_WORKER",
        qualification_codes=("HOME_CARE",),
        phone_index=7,
        address="경기도 수원시 영통구 월드컵로 206 시드센터 합성 퇴사자기록 1호",
    ),
    StaffScenario(
        key="SW_ENDED",
        name="임수진",
        sex_code=StaffCreateSexCode.FEMALE,
        birth_date=date(1984, 8, 9),
        position_code=PositionCode.SOCIAL_WORKER,
        ended=True,
        license_type_code="SOCIAL_WORKER",
        qualification_codes=(),
        phone_index=8,
        address="경기도 수원시 영통구 월드컵로 206 시드센터 합성 퇴사자기록 2호",
    ),
    StaffScenario(
        key="NU_ENDED",
        name="한미경",
        sex_code=StaffCreateSexCode.FEMALE,
        birth_date=date(1987, 12, 2),
        position_code=PositionCode.NURSE,
        ended=True,
        license_type_code="NURSE",
        qualification_codes=(),
        phone_index=9,
        address="경기도 성남시 분당구 판교로 242 시드센터 합성 퇴사자기록 3호",
    ),
    StaffScenario(
        key="MG_ENDED",
        name="오세훈",
        sex_code=StaffCreateSexCode.MALE,
        birth_date=date(1972, 6, 30),
        position_code=PositionCode.MANAGER,
        ended=True,
        license_type_code=None,
        qualification_codes=(),
        phone_index=10,
        address="경기도 성남시 분당구 판교로 242 시드센터 합성 퇴사자기록 4호",
    ),
)

RECIPIENT_SCENARIOS: tuple[RecipientScenario, ...] = (
    RecipientScenario(
        key="R_ACTIVE_HOME_CARE",
        name="김순자",
        sex_code=RecipientSexCode.FEMALE,
        birth_date=date(1942, 3, 5),
        status=RecipientStatus.ACTIVE,
        benefit_code=BenefitCode.GENERAL,
        grade_code=GradeCode.GRADE_1,
        self_payer=True,
        guardian_relationship=None,
        guardian_name=None,
        service_type_codes=(ServiceTypeCode.HOME_CARE,),
        postal_code="04524",
        road_address="서울특별시 중구 세종대로 110",
        unit_detail="시드센터 합성 101동 802호",
        phone_index=21,
        cert_offset=0,
    ),
    RecipientScenario(
        key="R_ACTIVE_HOME_BATH",
        name="이옥분",
        sex_code=RecipientSexCode.FEMALE,
        birth_date=date(1938, 11, 19),
        status=RecipientStatus.ACTIVE,
        benefit_code=BenefitCode.BASIC_LIVELIHOOD,
        grade_code=GradeCode.GRADE_2,
        self_payer=False,
        guardian_relationship="자녀",
        guardian_name="이서연",
        service_type_codes=(ServiceTypeCode.HOME_BATH,),
        postal_code="04158",
        road_address="서울특별시 마포구 마포대로 109",
        unit_detail="시드센터 합성 203동 1501호",
        phone_index=22,
        cert_offset=1,
    ),
    RecipientScenario(
        key="R_ACTIVE_TEMP",
        name="박철수",
        sex_code=RecipientSexCode.MALE,
        birth_date=date(1948, 7, 2),
        status=RecipientStatus.ACTIVE,
        benefit_code=BenefitCode.REDUCTION_6,
        grade_code=GradeCode.GRADE_3,
        self_payer=False,
        guardian_relationship="배우자",
        guardian_name="최영자",
        service_type_codes=(ServiceTypeCode.TEMP_HOME_CARE, ServiceTypeCode.HOSPITAL_ESCORT),
        postal_code="16419",
        road_address="경기도 수원시 영통구 월드컵로 206",
        unit_detail="시드센터 합성 88동 303호",
        phone_index=23,
        cert_offset=2,
    ),
    RecipientScenario(
        key="R_WAITING",
        name="최영자",
        sex_code=RecipientSexCode.FEMALE,
        birth_date=date(1951, 1, 28),
        status=RecipientStatus.WAITING,
        benefit_code=BenefitCode.REDUCTION_9,
        grade_code=GradeCode.GRADE_4,
        self_payer=True,
        guardian_relationship=None,
        guardian_name=None,
        service_type_codes=(),
        postal_code="10442",
        road_address="경기도 고양시 일산동구 중앙로 1286",
        unit_detail="시드센터 합성 대기자 12호",
        phone_index=24,
        cert_offset=3,
    ),
    RecipientScenario(
        # Center service ended. National certification/benefit may remain valid.
        key="R_ENDED",
        name="정만수",
        sex_code=RecipientSexCode.MALE,
        birth_date=date(1935, 9, 14),
        status=RecipientStatus.ENDED,
        benefit_code=BenefitCode.MEDICAL_6,
        grade_code=GradeCode.GRADE_5,
        self_payer=False,
        guardian_relationship="자녀",
        guardian_name="정현우",
        service_type_codes=(ServiceTypeCode.HOME_CARE,),
        postal_code="48058",
        road_address="부산광역시 해운대구 센텀중앙로 79",
        unit_detail="시드센터 합성 종료자 5호",
        phone_index=25,
        cert_offset=4,
    ),
    RecipientScenario(
        key="R_ACTIVE_BARO",
        name="강미자",
        sex_code=RecipientSexCode.FEMALE,
        birth_date=date(1946, 5, 23),
        status=RecipientStatus.ACTIVE,
        benefit_code=BenefitCode.MEDICAL_9,
        grade_code=GradeCode.GRADE_1,
        self_payer=True,
        guardian_relationship="형제",
        guardian_name="강기남",
        service_type_codes=(ServiceTypeCode.BARO_CARE,),
        postal_code="35242",
        road_address="대전광역시 서구 둔산로 100",
        unit_detail="시드센터 합성 707호",
        phone_index=26,
        cert_offset=5,
    ),
)

ASSIGNMENT_SPECS: tuple[AssignmentSpec, ...] = (
    AssignmentSpec("R_ACTIVE_HOME_CARE", "HOME_CARE", "CW_HOME_A", CONTRACT_START, None),
    AssignmentSpec("R_ACTIVE_HOME_BATH", "HOME_BATH", "CW_HOME_A", CONTRACT_START, None),
    AssignmentSpec("R_ACTIVE_HOME_BATH", "HOME_BATH", "CW_HOME_B", CONTRACT_START, None),
    AssignmentSpec("R_ACTIVE_TEMP", "TEMP_HOME_CARE", "CW_OTHER", CONTRACT_START, None),
    AssignmentSpec("R_ENDED", "HOME_CARE", "CW_ENDED", ENDED_CONTRACT_START, ENDED_END),
    AssignmentSpec("R_ACTIVE_TEMP", "HOSPITAL_ESCORT", "CW_OTHER", CONTRACT_START, None),
    AssignmentSpec("R_ACTIVE_BARO", "BARO_CARE", "CW_OTHER", CONTRACT_START, None),
)

PROFESSIONAL_SPECS: tuple[ProfessionalSpec, ...] = (
    ProfessionalSpec("R_ACTIVE_HOME_CARE", "SW_ACTIVE"),
    ProfessionalSpec("R_ACTIVE_HOME_BATH", "NU_ACTIVE"),
)

SCHEDULE_SPECS: tuple[ScheduleSpec, ...] = (
    ScheduleSpec("R_ACTIVE_HOME_CARE", "HOME_CARE", 10, 9, 12, ("CW_HOME_A",)),
    ScheduleSpec("R_ACTIVE_HOME_BATH", "HOME_BATH", 11, 10, 11, ("CW_HOME_A", "CW_HOME_B")),
    ScheduleSpec("R_ACTIVE_TEMP", "TEMP_HOME_CARE", 12, 13, 16, ("CW_OTHER",)),
    ScheduleSpec("R_ACTIVE_BARO", "BARO_CARE", 13, 8, 12, ("CW_OTHER",)),
)

EXPECTED_INVENTORY = ExpectedInventory(
    staff=len(STAFF_SCENARIOS),
    active_staff=sum(0 if item.ended else 1 for item in STAFF_SCENARIOS),
    ended_staff=sum(1 if item.ended else 0 for item in STAFF_SCENARIOS),
    recipients=len(RECIPIENT_SCENARIOS),
    active_recipients=sum(
        1 for item in RECIPIENT_SCENARIOS if item.status is RecipientStatus.ACTIVE
    ),
    waiting_recipients=sum(
        1 for item in RECIPIENT_SCENARIOS if item.status is RecipientStatus.WAITING
    ),
    ended_recipients=sum(1 for item in RECIPIENT_SCENARIOS if item.status is RecipientStatus.ENDED),
    guardians=sum(1 for item in RECIPIENT_SCENARIOS if item.guardian_name is not None),
    payer_guardians=sum(1 for item in RECIPIENT_SCENARIOS if not item.self_payer),
    certification_identities=len(RECIPIENT_SCENARIOS),
    active_certification_periods=len(RECIPIENT_SCENARIOS),
    active_benefits=len(RECIPIENT_SCENARIOS),
    staff_sensitive_identities=len(STAFF_SCENARIOS),
    staff_licenses=sum(1 for item in STAFF_SCENARIOS if item.license_type_code is not None),
    staff_qualifications=sum(len(item.qualification_codes) for item in STAFF_SCENARIOS),
    contracts=sum(len(item.service_type_codes) for item in RECIPIENT_SCENARIOS),
    care_assignments=len(ASSIGNMENT_SPECS),
    monthly_professional_assignments=len(PROFESSIONAL_SPECS),
    schedules=len(SCHEDULE_SPECS),
    schedule_staff=sum(len(item.staff_keys) for item in SCHEDULE_SPECS),
    home_bath_two_worker_schedules=sum(
        1
        for item in SCHEDULE_SPECS
        if item.service_type_code == "HOME_BATH" and len(item.staff_keys) == 2
    ),
    official_work_cards=0,
    service_plan_notices=0,
    personal_todos=0,
    replacement_lineage=0,
)


def _memo(key: str) -> str:
    return f"{SEED_MARKER}|{key}"


def _staff_memos() -> tuple[str, ...]:
    return tuple(_memo(item.key) for item in STAFF_SCENARIOS)


def _recipient_memos() -> tuple[str, ...]:
    return tuple(_memo(item.key) for item in RECIPIENT_SCENARIOS)


def _phone(index: int) -> str:
    return f"010-0700-{index:04d}"


def _compose_address(road: str, detail: str) -> str:
    return f"{road.strip()} {detail.strip()}"


def _synthetic_rrn(birth_date: date, sex_code: StaffCreateSexCode, serial: int) -> str:
    # Generated unique value for the schema-required encrypted identity.
    # Not sourced from any person.
    if birth_date.year >= 2000:
        gender = "3" if sex_code is StaffCreateSexCode.MALE else "4"
    else:
        gender = "1" if sex_code is StaffCreateSexCode.MALE else "2"
    return f"{birth_date:%y%m%d}-{gender}{serial:06d}"


def _seoul_slot(day: int, start_hour: int, end_hour: int) -> tuple[datetime, datetime]:
    return (
        datetime(SERVICE_MONTH.year, SERVICE_MONTH.month, day, start_hour, 0, tzinfo=_SEOUL),
        datetime(SERVICE_MONTH.year, SERVICE_MONTH.month, day, end_hour, 0, tzinfo=_SEOUL),
    )


def _local_database_guard(database_url: str) -> None:
    url = make_url(database_url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("workflow scenario seed only permits a loopback PostgreSQL host")
    database_name = url.database or ""
    if not database_name.endswith(("_dev", "_test", "_review")):
        raise RuntimeError("workflow scenario seed requires a development/test database name")


def _parse_marker_key(memo: str | None) -> str | None:
    prefix = f"{SEED_MARKER}|"
    if memo is None or not memo.startswith(prefix):
        return None
    key = memo[len(prefix) :]
    return key or None


def staff_integrity_errors(scenario: StaffScenario, observed: ObservedStaff | None) -> list[str]:
    if observed is None:
        return [f"missing_staff:{scenario.key}"]
    errors: list[str] = []
    expected_start = ENDED_START if scenario.ended else ACTIVE_START
    expected_end = ENDED_END if scenario.ended else None
    if observed.name != scenario.name:
        errors.append(f"staff_name:{scenario.key}")
    if observed.sex_code != scenario.sex_code.value:
        errors.append(f"staff_sex:{scenario.key}")
    if observed.birth_date != scenario.birth_date:
        errors.append(f"staff_birth:{scenario.key}")
    if observed.phone != _phone(scenario.phone_index):
        errors.append(f"staff_phone:{scenario.key}")
    if observed.address != scenario.address:
        errors.append(f"staff_address:{scenario.key}")
    if not observed.has_sensitive_identity:
        errors.append(f"missing_staff_sensitive_identity:{scenario.key}")
    if observed.employment_start != expected_start or observed.employment_end != expected_end:
        errors.append(f"staff_employment:{scenario.key}")
    if scenario.ended and observed.end_reason_code != "RESIGNED":
        errors.append(f"staff_end_reason:{scenario.key}")
    if not scenario.ended and observed.end_reason_code is not None:
        errors.append(f"staff_end_reason:{scenario.key}")
    if (
        observed.position_code != scenario.position_code.value
        or observed.position_start != expected_start
        or observed.position_end != expected_end
    ):
        errors.append(f"staff_position:{scenario.key}")
    if (
        observed.role_code != ROLE_BY_POSITION[scenario.position_code]
        or observed.role_start != expected_start
        or observed.role_end != expected_end
    ):
        errors.append(f"staff_operational_role:{scenario.key}")
    if observed.license_type_code != scenario.license_type_code:
        errors.append(f"staff_license:{scenario.key}")
    if tuple(sorted(observed.qualification_codes)) != tuple(sorted(scenario.qualification_codes)):
        errors.append(f"staff_qualifications:{scenario.key}")
    return errors


def recipient_integrity_errors(
    scenario: RecipientScenario,
    observed: ObservedRecipient | None,
) -> list[str]:
    if observed is None:
        return [f"missing_recipient:{scenario.key}"]
    errors: list[str] = []
    address = _compose_address(scenario.road_address, scenario.unit_detail)
    if observed.name != scenario.name:
        errors.append(f"recipient_name:{scenario.key}")
    if observed.sex_code != scenario.sex_code.value:
        errors.append(f"recipient_sex:{scenario.key}")
    if observed.birth_date != scenario.birth_date:
        errors.append(f"recipient_birth:{scenario.key}")
    if observed.status != scenario.status.value:
        errors.append(f"recipient_status:{scenario.key}")
    if observed.phone != _phone(scenario.phone_index):
        errors.append(f"recipient_phone:{scenario.key}")
    if observed.address != address:
        errors.append(f"recipient_address:{scenario.key}")
    if observed.self_payer != scenario.self_payer:
        errors.append(f"recipient_payer:{scenario.key}")
    expected_guardians: tuple[ObservedGuardian, ...]
    if scenario.guardian_name is None or scenario.guardian_relationship is None:
        expected_guardians = ()
    else:
        expected_guardians = (
            ObservedGuardian(scenario.guardian_name, scenario.guardian_relationship),
        )
    if observed.guardians != expected_guardians:
        if not expected_guardians:
            errors.append(f"extra_guardian:{scenario.key}")
        elif not observed.guardians:
            errors.append(f"missing_guardian:{scenario.key}")
        else:
            errors.append(f"guardian_mismatch:{scenario.key}")
    expected_cert = f"L{CERT_NUMBER_BASE + scenario.cert_offset:010d}"
    if observed.certification_number != expected_cert:
        errors.append(f"certification_identity:{scenario.key}")
    if (
        observed.grade_code != scenario.grade_code.value
        or observed.cert_start != CERT_START
        or observed.cert_end != CERT_END
    ):
        errors.append(f"certification_period:{scenario.key}")
    if observed.benefit_code != scenario.benefit_code.value:
        errors.append(f"benefit_code:{scenario.key}")
    if observed.benefit_start_text != BENEFIT_START_TEXT:
        errors.append(f"benefit_start_text:{scenario.key}")
    expected_codes = tuple(sorted(code.value for code in scenario.service_type_codes))
    if tuple(sorted(observed.contract_codes)) != expected_codes:
        errors.append(f"contracts:{scenario.key}")
    else:
        for code in expected_codes:
            ended = scenario.status is RecipientStatus.ENDED
            expected_dates = (
                code,
                ENDED_CONTRACT_START if ended else CONTRACT_START,
                ENDED_END if ended else None,
            )
            if expected_dates not in observed.contract_dates:
                errors.append(f"contract_dates:{scenario.key}:{code}")
    return errors


def assignment_integrity_errors(observed: tuple[ObservedAssignment, ...]) -> list[str]:
    expected = {
        (
            item.recipient_key,
            item.service_type_code,
            item.staff_key,
            item.start_date,
            item.end_date,
            item.assignment_kind.value,
        )
        for item in ASSIGNMENT_SPECS
    }
    actual = {
        (
            item.recipient_key,
            item.service_type_code,
            item.staff_key,
            item.start_date,
            item.end_date,
            item.assignment_kind,
        )
        for item in observed
    }
    errors: list[str] = []
    for row in sorted(expected - actual):
        errors.append(f"missing_assignment:{row[0]}:{row[1]}:{row[2]}")
    for row in sorted(actual - expected):
        errors.append(f"extra_assignment:{row[0]}:{row[1]}:{row[2]}")
    return errors


def professional_integrity_errors(observed: tuple[ObservedProfessional, ...]) -> list[str]:
    expected = {
        (item.recipient_key, item.staff_key, item.service_month, item.start_date, item.end_date)
        for item in PROFESSIONAL_SPECS
    }
    actual = {
        (item.recipient_key, item.staff_key, item.service_month, item.start_date, item.end_date)
        for item in observed
    }
    errors: list[str] = []
    for row in sorted(expected - actual):
        errors.append(f"missing_professional:{row[0]}:{row[1]}")
    for row in sorted(actual - expected):
        errors.append(f"extra_professional:{row[0]}:{row[1]}")
    return errors


def schedule_integrity_errors(observed: tuple[ObservedSchedule, ...]) -> list[str]:
    expected = {
        (
            item.recipient_key,
            item.service_type_code,
            item.day,
            item.start_hour,
            item.end_hour,
            tuple(sorted(item.staff_keys)),
        )
        for item in SCHEDULE_SPECS
    }
    actual = {
        (
            item.recipient_key,
            item.service_type_code,
            item.day,
            item.start_hour,
            item.end_hour,
            tuple(sorted(item.staff_keys)),
        )
        for item in observed
    }
    errors: list[str] = []
    for row in sorted(expected - actual):
        errors.append(f"missing_schedule:{row[0]}:{row[1]}")
    for row in sorted(actual - expected):
        errors.append(f"extra_schedule:{row[0]}:{row[1]}")
    return errors


def _zero_measured(*, errors: tuple[str, ...] = ()) -> MeasuredInventory:
    return MeasuredInventory(
        staff=0,
        active_staff=0,
        ended_staff=0,
        recipients=0,
        active_recipients=0,
        waiting_recipients=0,
        ended_recipients=0,
        guardians=0,
        payer_guardians=0,
        certification_identities=0,
        active_certification_periods=0,
        active_benefits=0,
        staff_sensitive_identities=0,
        staff_licenses=0,
        staff_qualifications=0,
        contracts=0,
        care_assignments=0,
        monthly_professional_assignments=0,
        schedules=0,
        schedule_staff=0,
        home_bath_two_worker_schedules=0,
        official_work_cards=0,
        service_plan_notices=0,
        personal_todos_seed_created=0,
        replacement_lineage=0,
        integrity_errors=errors,
    )


def _counts_match_expected(measured: MeasuredInventory) -> bool:
    expected = EXPECTED_INVENTORY
    return (
        measured.staff == expected.staff
        and measured.active_staff == expected.active_staff
        and measured.ended_staff == expected.ended_staff
        and measured.recipients == expected.recipients
        and measured.active_recipients == expected.active_recipients
        and measured.waiting_recipients == expected.waiting_recipients
        and measured.ended_recipients == expected.ended_recipients
        and measured.guardians == expected.guardians
        and measured.payer_guardians == expected.payer_guardians
        and measured.certification_identities == expected.certification_identities
        and measured.active_certification_periods == expected.active_certification_periods
        and measured.active_benefits == expected.active_benefits
        and measured.staff_sensitive_identities == expected.staff_sensitive_identities
        and measured.staff_licenses == expected.staff_licenses
        and measured.staff_qualifications == expected.staff_qualifications
        and measured.contracts == expected.contracts
        and measured.care_assignments == expected.care_assignments
        and measured.monthly_professional_assignments == expected.monthly_professional_assignments
        and measured.schedules == expected.schedules
        and measured.schedule_staff == expected.schedule_staff
        and measured.home_bath_two_worker_schedules == expected.home_bath_two_worker_schedules
        and measured.official_work_cards == expected.official_work_cards
        and measured.service_plan_notices == expected.service_plan_notices
        and measured.personal_todos_seed_created == expected.personal_todos
        and measured.replacement_lineage == expected.replacement_lineage
    )


def classify_measured_inventory(
    measured: MeasuredInventory,
) -> Literal["empty", "complete", "partial"]:
    if measured.integrity_errors:
        return "partial"
    if measured == _zero_measured():
        return "empty"
    if _counts_match_expected(measured):
        return "complete"
    return "partial"


def _service_type_code_map(session: Session) -> dict[int, str]:
    rows = session.execute(select(ServiceType.id, ServiceType.code)).all()
    return {int(type_id): str(code) for type_id, code in rows}


def _staff_key_by_id(session: Session) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for staff in session.scalars(select(Staff).where(Staff.memo.in_(_staff_memos()))).all():
        key = _parse_marker_key(staff.memo)
        if key is not None:
            mapping[staff.id] = key
    return mapping


def _recipient_key_by_id(session: Session) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for recipient in session.scalars(
        select(Recipient).where(Recipient.memo.in_(_recipient_memos()))
    ).all():
        key = _parse_marker_key(recipient.memo)
        if key is not None:
            mapping[recipient.id] = key
    return mapping


def _load_observed_staff(session: Session, staff: Staff) -> ObservedStaff:
    key = _parse_marker_key(staff.memo) or ""
    identity = session.get(StaffSensitiveIdentity, staff.id)
    employment = session.scalar(
        select(StaffEmployment).where(
            StaffEmployment.staff_id == staff.id,
            StaffEmployment.invalidated_at_utc.is_(None),
        )
    )
    position = None
    role = None
    license_code = None
    qualifications: list[str] = []
    if employment is not None:
        position = session.scalar(
            select(StaffPositionPeriod).where(
                StaffPositionPeriod.employment_id == employment.id,
                StaffPositionPeriod.invalidated_at_utc.is_(None),
            )
        )
        role = session.scalar(
            select(StaffOperationalRolePeriod).where(
                StaffOperationalRolePeriod.employment_id == employment.id,
                StaffOperationalRolePeriod.invalidated_at_utc.is_(None),
            )
        )
        license_row = session.execute(
            select(StaffLicense, LicenseType.code)
            .join(LicenseType, LicenseType.id == StaffLicense.license_type_id)
            .where(
                StaffLicense.staff_id == staff.id,
                StaffLicense.invalidated_at_utc.is_(None),
            )
        ).first()
        if license_row is not None:
            license_code = str(license_row[1])
        qualifications = [
            str(code)
            for code in session.scalars(
                select(ServiceType.code)
                .select_from(StaffServiceQualificationPeriod)
                .join(
                    ServiceType, ServiceType.id == StaffServiceQualificationPeriod.service_type_id
                )
                .where(
                    StaffServiceQualificationPeriod.staff_id == staff.id,
                    StaffServiceQualificationPeriod.invalidated_at_utc.is_(None),
                )
            ).all()
        ]
    return ObservedStaff(
        key=key,
        name=staff.name,
        sex_code=staff.sex_code,
        birth_date=staff.birth_date,
        phone=staff.phone,
        address=staff.address,
        has_sensitive_identity=identity is not None,
        employment_start=None if employment is None else employment.start_date,
        employment_end=None if employment is None else employment.end_date,
        end_reason_code=None if employment is None else employment.end_reason_code,
        position_code=None if position is None else position.position_code,
        position_start=None if position is None else position.start_date,
        position_end=None if position is None else position.end_date,
        role_code=None if role is None else role.role_code,
        role_start=None if role is None else role.start_date,
        role_end=None if role is None else role.end_date,
        license_type_code=license_code,
        qualification_codes=tuple(qualifications),
    )


def _load_observed_recipient(session: Session, recipient: Recipient) -> ObservedRecipient:
    key = _parse_marker_key(recipient.memo) or ""
    type_by_id = _service_type_code_map(session)
    guardians = tuple(
        ObservedGuardian(item.name, item.relationship_text)
        for item in session.scalars(
            select(RecipientGuardian)
            .where(RecipientGuardian.recipient_id == recipient.id)
            .order_by(RecipientGuardian.slot_no.asc())
        ).all()
    )
    identity = session.get(RecipientCertificationIdentity, recipient.id)
    period = session.scalar(
        select(RecipientCertificationPeriod).where(
            RecipientCertificationPeriod.recipient_id == recipient.id,
            RecipientCertificationPeriod.invalidated_at_utc.is_(None),
        )
    )
    benefit = session.scalar(
        select(RecipientBenefitPeriod).where(
            RecipientBenefitPeriod.recipient_id == recipient.id,
            RecipientBenefitPeriod.invalidated_at_utc.is_(None),
        )
    )
    contracts = list(
        session.scalars(
            select(RecipientContract).where(
                RecipientContract.recipient_id == recipient.id,
                RecipientContract.invalidated_at_utc.is_(None),
            )
        ).all()
    )
    contract_dates = tuple(
        (type_by_id.get(item.service_type_id, ""), item.start_date, item.end_date)
        for item in contracts
    )
    return ObservedRecipient(
        key=key,
        name=recipient.name,
        sex_code=recipient.sex_code,
        birth_date=recipient.birth_date,
        status=recipient.recipient_status,
        phone=recipient.mobile_phone,
        address=recipient.address,
        self_payer=recipient.payer_guardian_id is None,
        guardians=guardians,
        certification_number=None if identity is None else identity.certification_number,
        grade_code=None if period is None else period.grade_code,
        cert_start=None if period is None else period.start_date,
        cert_end=None if period is None else period.end_date,
        benefit_code=None if benefit is None else benefit.benefit_code,
        benefit_start_text=None if benefit is None else benefit.start_text,
        contract_codes=tuple(code for code, _start, _end in contract_dates),
        contract_dates=contract_dates,
    )


def evaluate_workflow_graph(session: Session) -> MeasuredInventory:
    expected_staff = {item.key: item for item in STAFF_SCENARIOS}
    expected_recipients = {item.key: item for item in RECIPIENT_SCENARIOS}
    staff_rows = list(
        session.scalars(select(Staff).where(func.strpos(Staff.memo, SEED_MARKER) > 0)).all()
    )
    recipient_rows = list(
        session.scalars(select(Recipient).where(func.strpos(Recipient.memo, SEED_MARKER) > 0)).all()
    )
    if not staff_rows and not recipient_rows:
        return _zero_measured()

    errors: list[str] = []
    observed_staff: dict[str, ObservedStaff] = {}
    for staff in staff_rows:
        key = _parse_marker_key(staff.memo)
        if key is None or key not in expected_staff or staff.memo != _memo(key):
            errors.append(f"extra_staff_memo:{staff.memo}")
            continue
        if key in observed_staff:
            errors.append(f"duplicate_staff:{key}")
            continue
        observed_staff[key] = _load_observed_staff(session, staff)
    for key, staff_scenario in expected_staff.items():
        errors.extend(staff_integrity_errors(staff_scenario, observed_staff.get(key)))

    observed_recipients: dict[str, ObservedRecipient] = {}
    for recipient in recipient_rows:
        key = _parse_marker_key(recipient.memo)
        if key is None or key not in expected_recipients or recipient.memo != _memo(key):
            errors.append(f"extra_recipient_memo:{recipient.memo}")
            continue
        if key in observed_recipients:
            errors.append(f"duplicate_recipient:{key}")
            continue
        observed_recipients[key] = _load_observed_recipient(session, recipient)
    for key, recipient_scenario in expected_recipients.items():
        errors.extend(recipient_integrity_errors(recipient_scenario, observed_recipients.get(key)))

    staff_by_id = _staff_key_by_id(session)
    recipient_by_id = _recipient_key_by_id(session)
    type_by_id = _service_type_code_map(session)
    recipient_ids = list(recipient_by_id)
    contract_rows = []
    if recipient_ids:
        contract_rows = list(
            session.scalars(
                select(RecipientContract).where(
                    RecipientContract.recipient_id.in_(recipient_ids),
                    RecipientContract.invalidated_at_utc.is_(None),
                )
            ).all()
        )
    contract_ids = [item.id for item in contract_rows]
    contract_type_by_id = {
        item.id: type_by_id.get(item.service_type_id, "") for item in contract_rows
    }
    contract_recipient_by_id = {
        item.id: recipient_by_id.get(item.recipient_id, "") for item in contract_rows
    }

    assignments: list[ObservedAssignment] = []
    if contract_ids:
        for assignment in session.scalars(
            select(CareAssignment).where(
                CareAssignment.recipient_contract_id.in_(contract_ids),
                CareAssignment.invalidated_at_utc.is_(None),
            )
        ).all():
            assignments.append(
                ObservedAssignment(
                    recipient_key=contract_recipient_by_id.get(
                        assignment.recipient_contract_id, ""
                    ),
                    service_type_code=contract_type_by_id.get(assignment.recipient_contract_id, ""),
                    staff_key=staff_by_id.get(assignment.staff_id, ""),
                    start_date=assignment.start_date,
                    end_date=assignment.end_date,
                    assignment_kind=assignment.assignment_kind,
                )
            )
    errors.extend(assignment_integrity_errors(tuple(assignments)))

    professionals: list[ObservedProfessional] = []
    if recipient_ids:
        for row in session.scalars(
            select(MonthlyProfessionalAssignment).where(
                MonthlyProfessionalAssignment.recipient_id.in_(recipient_ids),
                MonthlyProfessionalAssignment.invalidated_at_utc.is_(None),
            )
        ).all():
            professionals.append(
                ObservedProfessional(
                    recipient_key=recipient_by_id.get(row.recipient_id, ""),
                    staff_key=staff_by_id.get(row.staff_id, ""),
                    service_month=row.service_month,
                    start_date=row.start_date,
                    end_date=row.end_date,
                )
            )
    errors.extend(professional_integrity_errors(tuple(professionals)))

    schedules: list[ObservedSchedule] = []
    schedule_staff_count = 0
    home_bath_two_worker = 0
    if recipient_ids:
        for schedule in session.scalars(
            select(W2Schedule).where(W2Schedule.recipient_id.in_(recipient_ids))
        ).all():
            staff_ids = list(
                session.scalars(
                    select(W2ScheduleStaff.staff_id).where(
                        W2ScheduleStaff.schedule_id == schedule.id
                    )
                ).all()
            )
            schedule_staff_count += len(staff_ids)
            starts = schedule.starts_at_utc.astimezone(_SEOUL)
            ends = schedule.ends_at_utc.astimezone(_SEOUL)
            type_code = type_by_id.get(schedule.service_type_id, "")
            if type_code == "HOME_BATH" and len(staff_ids) == 2:
                home_bath_two_worker += 1
            schedules.append(
                ObservedSchedule(
                    recipient_key=recipient_by_id.get(schedule.recipient_id, ""),
                    service_type_code=type_code,
                    day=starts.day,
                    start_hour=starts.hour,
                    end_hour=ends.hour,
                    staff_keys=tuple(staff_by_id.get(staff_id, "") for staff_id in staff_ids),
                )
            )
    errors.extend(schedule_integrity_errors(tuple(schedules)))

    replacement_count = 0
    official_cards = 0
    plan_notices = 0
    if recipient_ids:
        replacement_count += int(
            session.scalar(
                select(func.count())
                .select_from(RecipientContract)
                .where(
                    RecipientContract.recipient_id.in_(recipient_ids),
                    RecipientContract.replacement_contract_id.is_not(None),
                )
            )
            or 0
        )
        official_cards = int(
            session.scalar(
                select(func.count())
                .select_from(W2OfficialWorkCard)
                .where(W2OfficialWorkCard.recipient_id.in_(recipient_ids))
            )
            or 0
        )
        replacement_count += int(
            session.scalar(
                select(func.count())
                .select_from(MonthlyProfessionalAssignment)
                .where(
                    MonthlyProfessionalAssignment.recipient_id.in_(recipient_ids),
                    MonthlyProfessionalAssignment.replacement_assignment_id.is_not(None),
                )
            )
            or 0
        )
    if contract_ids:
        replacement_count += int(
            session.scalar(
                select(func.count())
                .select_from(CareAssignment)
                .where(
                    CareAssignment.recipient_contract_id.in_(contract_ids),
                    CareAssignment.replacement_assignment_id.is_not(None),
                )
            )
            or 0
        )
        plan_notices = int(
            session.scalar(
                select(func.count())
                .select_from(RecipientServicePlanNotice)
                .where(RecipientServicePlanNotice.recipient_contract_id.in_(contract_ids))
            )
            or 0
        )
    if replacement_count:
        errors.append(f"replacement_lineage:{replacement_count}")
    if official_cards:
        errors.append(f"official_work_cards:{official_cards}")
    if plan_notices:
        errors.append(f"service_plan_notices:{plan_notices}")

    staff_list = list(observed_staff.values())
    recipient_list = list(observed_recipients.values())
    return MeasuredInventory(
        staff=len(staff_list),
        active_staff=sum(1 for item in staff_list if item.employment_end is None),
        ended_staff=sum(1 for item in staff_list if item.employment_end is not None),
        recipients=len(recipient_list),
        active_recipients=sum(
            1 for item in recipient_list if item.status == RecipientStatus.ACTIVE.value
        ),
        waiting_recipients=sum(
            1 for item in recipient_list if item.status == RecipientStatus.WAITING.value
        ),
        ended_recipients=sum(
            1 for item in recipient_list if item.status == RecipientStatus.ENDED.value
        ),
        guardians=sum(len(item.guardians) for item in recipient_list),
        payer_guardians=sum(1 for item in recipient_list if not item.self_payer),
        certification_identities=sum(
            1 for item in recipient_list if item.certification_number is not None
        ),
        active_certification_periods=sum(
            1 for item in recipient_list if item.grade_code is not None
        ),
        active_benefits=sum(1 for item in recipient_list if item.benefit_code is not None),
        staff_sensitive_identities=sum(1 for item in staff_list if item.has_sensitive_identity),
        staff_licenses=sum(1 for item in staff_list if item.license_type_code is not None),
        staff_qualifications=sum(len(item.qualification_codes) for item in staff_list),
        contracts=sum(len(item.contract_codes) for item in recipient_list),
        care_assignments=len(assignments),
        monthly_professional_assignments=len(professionals),
        schedules=len(schedules),
        schedule_staff=schedule_staff_count,
        home_bath_two_worker_schedules=home_bath_two_worker,
        official_work_cards=official_cards,
        service_plan_notices=plan_notices,
        personal_todos_seed_created=0,
        replacement_lineage=replacement_count,
        integrity_errors=tuple(errors),
    )


def _build_summary(
    *,
    status: str,
    created: int,
    measured: MeasuredInventory,
) -> dict[str, int | str]:
    return {
        "status": status,
        "marker": SEED_MARKER,
        "version": SEED_VERSION,
        "created": created,
        "skipped": 1 if created == 0 else 0,
        "staff": measured.staff,
        "active_staff": measured.active_staff,
        "ended_staff": measured.ended_staff,
        "recipients": measured.recipients,
        "active_recipients": measured.active_recipients,
        "waiting_recipients": measured.waiting_recipients,
        "ended_recipients": measured.ended_recipients,
        "guardians": measured.guardians,
        "payer_guardians": measured.payer_guardians,
        "certification_identities": measured.certification_identities,
        "active_certification_periods": measured.active_certification_periods,
        "active_benefits": measured.active_benefits,
        "staff_sensitive_identities": measured.staff_sensitive_identities,
        "staff_licenses": measured.staff_licenses,
        "staff_qualifications": measured.staff_qualifications,
        "contracts": measured.contracts,
        "care_assignments": measured.care_assignments,
        "monthly_professional_assignments": measured.monthly_professional_assignments,
        "schedules": measured.schedules,
        "schedule_staff": measured.schedule_staff,
        "home_bath_two_worker_schedules": measured.home_bath_two_worker_schedules,
        "official_work_cards": measured.official_work_cards,
        "service_plan_notices": measured.service_plan_notices,
        "personal_todos": measured.personal_todos_seed_created,
        "replacement_lineage": measured.replacement_lineage,
        "integrity_error_count": len(measured.integrity_errors),
        "integrity_errors": ",".join(measured.integrity_errors[:12]),
        "service_month": SERVICE_MONTH.isoformat(),
    }


def _staff_create_request(scenario: StaffScenario) -> StaffCreateRequest:
    start_date = ENDED_START if scenario.ended else ACTIVE_START
    end_date = ENDED_END if scenario.ended else None
    return StaffCreateRequest(
        name=scenario.name,
        birth_date=scenario.birth_date,
        sex_code=scenario.sex_code,
        resident_number=_synthetic_rrn(
            scenario.birth_date,
            scenario.sex_code,
            700000 + scenario.phone_index,
        ),
        phone=_phone(scenario.phone_index),
        address=scenario.address,
        display_name=scenario.name,
        memo=_memo(scenario.key),
        initial_employment=InitialEmploymentRequest(
            start_date=start_date,
            initial_positions=[
                InitialPositionRequest(
                    position_code=scenario.position_code,
                    start_date=start_date,
                    end_date=end_date,
                )
            ],
            initial_operational_roles=[
                InitialOperationalRoleRequest(
                    role_code=ROLE_BY_POSITION[scenario.position_code],
                    start_date=start_date,
                    end_date=end_date,
                )
            ],
        ),
    )


def _install_deferred_commits(session: Session) -> None:
    session.info[_DEFER_COMMIT_KEY] = True
    session.info[_ORIGINAL_COMMIT_KEY] = session.commit
    session.commit = session.flush  # type: ignore[method-assign]


def _restore_deferred_commits(session: Session) -> None:
    session.info.pop(_DEFER_COMMIT_KEY, None)
    original = session.info.pop(_ORIGINAL_COMMIT_KEY, None)
    if original is not None:
        session.commit = original  # type: ignore[method-assign]


def _ensure_admin(session: Session, settings: Settings) -> CurrentAccount:
    existing_admin = session.scalar(
        select(UserAccount)
        .where(UserAccount.active.is_(True), UserAccount.role_code == "ADMIN")
        .order_by(UserAccount.id.asc())
    )
    if existing_admin is not None:
        return CurrentAccount(
            existing_admin.id,
            existing_admin.display_name,
            existing_admin.role_code,
        )
    bootstrap_installation(
        session,
        BootstrapInput(
            center_name="합성 W0-W2 시나리오센터",
            admin_name="시드관리자",
            birth_date=date(1980, 3, 15),
            sex_code="TEST",
            start_date=ACTIVE_START,
            pin="100000",
        ),
        settings,
    )
    admin = session.scalar(select(UserAccount).where(UserAccount.account_code == "ADMIN-001"))
    if admin is None:
        raise RuntimeError("workflow bootstrap did not create ADMIN-001")
    return CurrentAccount(admin.id, admin.display_name, admin.role_code)


def _service_type_ids(session: Session) -> dict[str, int]:
    rows = session.execute(select(ServiceType.code, ServiceType.id, ServiceType.active)).all()
    mapping = {str(code): int(type_id) for code, type_id, active in rows if bool(active)}
    missing = [code.value for code in ServiceTypeCode if code.value not in mapping]
    if missing:
        raise RuntimeError(f"service types missing; run migrations first: {missing}")
    return mapping


@dataclass
class _SeededStaff:
    staff_id: int
    employment_id: int


@dataclass
class _SeededRecipient:
    recipient_id: int
    contracts: dict[str, int]


def _create_staff_row(
    *,
    staff_service: StaffService,
    scenario: StaffScenario,
    account: CurrentAccount,
) -> _SeededStaff:
    created = staff_service.create_staff(_staff_create_request(scenario), account)
    employment = created.employments[0]
    employment_version = employment.row_version
    staff_version = created.row_version
    if scenario.license_type_code is not None:
        license_row = staff_service.create_license(
            created.id,
            StaffLicenseCreateRequest(
                license_type_code=scenario.license_type_code,
                license_number=f"SEED-WF-{scenario.key}",
                issued_date=LICENSE_ISSUED,
                expected_row_version=staff_version,
            ),
            account,
        )
        for code in scenario.qualification_codes:
            staff_service.create_service_qualification(
                created.id,
                StaffServiceQualificationCreateRequest(
                    employment_id=employment.id,
                    service_type_code=code,
                    start_date=ENDED_START if scenario.ended else ACTIVE_START,
                    end_date=ENDED_END if scenario.ended else None,
                    source_license_id=license_row.id,
                    expected_row_version=employment_version,
                ),
                account,
            )
            employment_version += 1
    if scenario.ended:
        staff_service.close_employment(
            created.id,
            employment.id,
            StaffEmploymentCloseRequest(
                end_date=ENDED_END,
                end_reason_code="RESIGNED",
                expected_employment_row_version=employment_version,
                open_position_versions=[],
                open_operational_role_versions=[],
            ),
            account,
        )
    return _SeededStaff(staff_id=created.id, employment_id=employment.id)


def _apply_benefit(
    *,
    w1c_service: W1CService,
    recipient_id: int,
    benefit_code: BenefitCode,
    start_text: str,
    account: CurrentAccount,
) -> None:
    existing = w1c_service.list_benefit_periods(recipient_id)
    active = next((item for item in existing.items if item.invalidated_at_utc is None), None)
    if active is None:
        raise RuntimeError("create_recipient must insert an active benefit period")
    if active.benefit_code == benefit_code and active.start_text == start_text:
        return
    w1c_service.replace_benefit_period(
        recipient_id,
        active.id,
        BenefitPeriodReplacementRequest(
            benefit_code=benefit_code,
            start_text=start_text,
            expected_row_version=active.row_version,
        ),
        account,
    )


def _create_recipient_row(
    *,
    recipient_service: RecipientService,
    w1c_service: W1CService,
    w1d_service: W1DService,
    scenario: RecipientScenario,
    account: CurrentAccount,
) -> _SeededRecipient:
    address = _compose_address(scenario.road_address, scenario.unit_detail)
    created = recipient_service.create_recipient(
        RecipientCreateRequest(
            name=scenario.name,
            birth_date=scenario.birth_date,
            sex_code=scenario.sex_code,
            postal_code=scenario.postal_code,
            address=address,
            mobile_phone=_phone(scenario.phone_index),
            memo=_memo(scenario.key),
        ),
        account,
    )
    row_version = created.row_version
    payer_guardian_id: int | None = None
    if scenario.guardian_name is not None and scenario.guardian_relationship is not None:
        guardian = recipient_service.create_guardian(
            created.id,
            GuardianCreateRequest(
                name=scenario.guardian_name,
                phone=_phone(scenario.phone_index + 50),
                relationship_text=scenario.guardian_relationship,
                address=address,
            ),
            account,
        )
        if not scenario.self_payer:
            payer_guardian_id = guardian.id
    if payer_guardian_id is not None or scenario.status is not RecipientStatus.ACTIVE:
        update_kwargs: dict[str, object] = {"expected_row_version": row_version}
        if scenario.status is not RecipientStatus.ACTIVE:
            update_kwargs["recipient_status"] = scenario.status
        if payer_guardian_id is not None:
            update_kwargs["payer_guardian_id"] = payer_guardian_id
        recipient_service.update_recipient(
            created.id,
            RecipientUpdateRequest.model_validate(update_kwargs),
            account,
        )
    _apply_benefit(
        w1c_service=w1c_service,
        recipient_id=created.id,
        benefit_code=scenario.benefit_code,
        start_text=BENEFIT_START_TEXT,
        account=account,
    )
    w1c_service.create_identity(
        created.id,
        CertificationIdentityCreateRequest(
            certification_number=f"L{CERT_NUMBER_BASE + scenario.cert_offset:010d}"
        ),
        account,
    )
    w1c_service.create_certification_period(
        created.id,
        CertificationPeriodCreateRequest(
            grade_code=scenario.grade_code,
            start_date=CERT_START,
            end_date=CERT_END,
        ),
        account,
    )
    contracts: dict[str, int] = {}
    for service_type_code in scenario.service_type_codes:
        ended = scenario.status is RecipientStatus.ENDED
        contract = w1d_service.create_contract(
            created.id,
            ContractCreateRequest(
                service_type_code=service_type_code,
                start_date=ENDED_CONTRACT_START if ended else CONTRACT_START,
                end_date=ENDED_END if ended else None,
                service_start_date=ENDED_CONTRACT_START if ended else CONTRACT_START,
                end_reason_text="계약 종료 시나리오" if ended else None,
            ),
            account,
        )
        contracts[service_type_code.value] = contract.id
    return _SeededRecipient(recipient_id=created.id, contracts=contracts)


def _assign_care(
    *,
    w1e_service: W1EService,
    recipient_id: int,
    contract_id: int,
    staff: _SeededStaff,
    start_date: date,
    end_date: date | None,
    account: CurrentAccount,
) -> None:
    w1e_service.create_assignment(
        recipient_id,
        contract_id,
        CareAssignmentCreateRequest(
            staff_id=staff.staff_id,
            employment_id=staff.employment_id,
            assignment_kind=AssignmentKind.GENERAL,
            start_date=start_date,
            end_date=end_date,
        ),
        account,
    )


def _create_scenario_graph(
    *,
    session: Session,
    settings: Settings,
    account: CurrentAccount,
) -> None:
    recipient_service = RecipientService(session)
    staff_service = StaffService(session, settings)
    w1c_service = W1CService(session)
    w1d_service = W1DService(session, settings)
    w1e_service = W1EService(session)
    w2_service = W2Service(session)
    type_ids = _service_type_ids(session)

    staff_rows = {
        scenario.key: _create_staff_row(
            staff_service=staff_service,
            scenario=scenario,
            account=account,
        )
        for scenario in STAFF_SCENARIOS
    }
    recipient_rows = {
        scenario.key: _create_recipient_row(
            recipient_service=recipient_service,
            w1c_service=w1c_service,
            w1d_service=w1d_service,
            scenario=scenario,
            account=account,
        )
        for scenario in RECIPIENT_SCENARIOS
    }

    for assignment_spec in ASSIGNMENT_SPECS:
        recipient = recipient_rows[assignment_spec.recipient_key]
        _assign_care(
            w1e_service=w1e_service,
            recipient_id=recipient.recipient_id,
            contract_id=recipient.contracts[assignment_spec.service_type_code],
            staff=staff_rows[assignment_spec.staff_key],
            start_date=assignment_spec.start_date,
            end_date=assignment_spec.end_date,
            account=account,
        )

    for professional_spec in PROFESSIONAL_SPECS:
        w2_service.create_professional_assignment(
            recipient_rows[professional_spec.recipient_key].recipient_id,
            professional_spec.service_month,
            ProfessionalAssignmentCreateRequest(
                staff_id=staff_rows[professional_spec.staff_key].staff_id,
                employment_id=staff_rows[professional_spec.staff_key].employment_id,
                start_date=professional_spec.start_date,
                end_date=professional_spec.end_date,
            ),
            account,
        )

    month_version = 1
    for schedule_spec in SCHEDULE_SPECS:
        starts, ends = _seoul_slot(
            schedule_spec.day, schedule_spec.start_hour, schedule_spec.end_hour
        )
        snapshot = w2_service.create_schedule(
            ScheduleCreateRequest(
                schedule_month=SERVICE_MONTH,
                recipient_id=recipient_rows[schedule_spec.recipient_key].recipient_id,
                service_type_id=type_ids[schedule_spec.service_type_code],
                assigned_staff=[
                    ScheduleStaffInput(
                        staff_id=staff_rows[staff_key].staff_id,
                        employment_id=staff_rows[staff_key].employment_id,
                    )
                    for staff_key in schedule_spec.staff_keys
                ],
                starts_at_utc=starts,
                ends_at_utc=ends,
                expected_month_row_version=month_version,
            ),
            account,
        )
        month_version = snapshot.row_version


def _refuse_partial(measured: MeasuredInventory) -> None:
    print(
        "SEED_W0_W2_WORKFLOW_UNEXPECTED_PARTIAL_STATE "
        f"staff={measured.staff} recipients={measured.recipients} "
        f"guardians={measured.guardians} contracts={measured.contracts} "
        f"assignments={measured.care_assignments} schedules={measured.schedules} "
        f"errors={','.join(measured.integrity_errors[:12])}"
    )
    raise RuntimeError(
        "SEED_W0_W2_WORKFLOW_UNEXPECTED_PARTIAL_STATE: "
        f"graph is neither empty nor complete. "
        f"measured staff={measured.staff} recipients={measured.recipients} "
        f"guardians={measured.guardians} integrity_errors={list(measured.integrity_errors)}. "
        "This script will not create, modify, or delete existing data."
    )


def seed_w0_w2_workflow_test_data() -> dict[str, int | str]:
    """Seed the small deterministic W0-W2 browse/workflow scenario.

    Atomicity: service-layer commits are deferred to one final transaction.
    StaffService and W2Service do not honor the shared defer key, so this
    seed also shadows Session.commit with flush for the duration of the run.
    Complete is a no-op only when the full versioned graph still matches.
    """
    settings = get_settings()
    if settings.environment is Environment.PRODUCTION:
        raise RuntimeError("workflow scenario seed is forbidden in production")
    if settings.database_url is None:
        raise RuntimeError("SSWCENTER_DATABASE_URL is required")
    _local_database_guard(settings.database_url)

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            measured = evaluate_workflow_graph(session)
            state = classify_measured_inventory(measured)
            if state == "complete":
                return _build_summary(status="ALREADY_COMPLETE", created=0, measured=measured)
            if state == "partial":
                _refuse_partial(measured)

            _install_deferred_commits(session)
            try:
                account = _ensure_admin(session, settings)
                _create_scenario_graph(session=session, settings=settings, account=account)
                created_measured = evaluate_workflow_graph(session)
                if classify_measured_inventory(created_measured) != "complete":
                    raise RuntimeError(
                        "workflow seed ended with unexpected graph "
                        f"{created_measured.integrity_errors}"
                    )
                _restore_deferred_commits(session)
                session.commit()
            except Exception:
                if session.in_transaction():
                    session.rollback()
                raise
            finally:
                _restore_deferred_commits(session)

            final_measured = evaluate_workflow_graph(session)
            return _build_summary(status="COMPLETE", created=1, measured=final_measured)
    finally:
        engine.dispose()


def main() -> None:
    summary = seed_w0_w2_workflow_test_data()
    rendered = " ".join(f"{key}={value}" for key, value in summary.items())
    print(f"SEED_W0_W2_WORKFLOW_{summary['status']} {rendered}")


if __name__ == "__main__":
    main()
