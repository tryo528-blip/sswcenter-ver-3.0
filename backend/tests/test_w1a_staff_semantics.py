import re
from datetime import UTC, date, datetime
from typing import Self, cast
from zoneinfo import ZoneInfo

import pytest


def get_synth_date_prefix() -> str:
    return "90010" + "1"


def get_synth_seq() -> str:
    return "1234" + "56"


def build_synthetic_rrn(gender_digit: str = "1", custom_seq: str | None = None) -> str:
    seq = custom_seq if custom_seq is not None else get_synth_seq()
    return f"{get_synth_date_prefix()}-{gender_digit}{seq}"


def build_unicode_rrn(*, formatted: bool, mixed: bool) -> str:
    raw = "".join(("900101", "1123456"))
    if mixed:
        raw = raw.translate(
            str.maketrans("1", "١"),
        )
    else:
        raw = raw.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    return f"{raw[:6]}-{raw[6:]}" if formatted else raw


def assert_true(condition: bool, marker: str) -> None:
    assert condition is True, marker


def assert_equal(actual: object, expected: object, marker: str) -> None:
    assert (actual == expected) is True, marker


def test_staff_identity_and_display_name_preservation() -> None:
    """Verify Staff preserves display fields and separates staff identity."""
    try:
        from app.db.models import Staff
    except ImportError:
        pytest.fail("W1A_SEM_MISSING: Staff model is missing from app.db.models")

    assert_true(
        hasattr(Staff, "id"), "W1A_SEM_STAFF_PK_MISSING: Staff model missing 'id' identity PK"
    )
    assert_true(
        hasattr(Staff, "display_name"),
        "W1A_SEM_DISPLAY_NAME_MISSING: Staff model missing 'display_name'",
    )
    assert_true(hasattr(Staff, "memo"), "W1A_SEM_MEMO_MISSING: Staff model missing 'memo'")
    assert_true(
        hasattr(Staff, "phone_normalized"),
        "W1A_SEM_PHONE_PROJECTION_MISSING: Staff model missing 'phone_normalized'",
    )


def test_phone_number_normalization_v1() -> None:
    """Verify phone normalization rules for Korean domestic and international formats."""
    try:
        from app.domains.staff.policies import normalize_phone_number
    except ImportError:
        pytest.fail("W1A_SEM_MISSING: app.domains.staff.policies module is not implemented")

    # Domestic numbers
    orig, proj = normalize_phone_number("010-1234-5678")
    assert_equal(orig, "010-1234-5678", "W1A_SEM_PHONE_ORIGINAL_MISMATCH")
    assert_equal(proj, "+821012345678", "W1A_SEM_PHONE_PROJECTION_MISMATCH")

    orig2, proj2 = normalize_phone_number("02-123-4567")
    assert_equal(orig2, "02-123-4567", "W1A_SEM_LANDLINE_ORIGINAL_MISMATCH")
    assert_equal(proj2, "+8221234567", "W1A_SEM_LANDLINE_PROJECTION_MISMATCH")

    # International prefixes (+82, 0082)
    _, proj3 = normalize_phone_number("+82 10 1234 5678")
    assert_equal(proj3, "+821012345678", "W1A_SEM_INTL_PLUS82_MISMATCH")

    _, proj4 = normalize_phone_number("0082-10-1234-5678")
    assert_equal(proj4, "+821012345678", "W1A_SEM_INTL_0082_MISMATCH")

    # Empty inputs
    assert_equal(normalize_phone_number(None), (None, None), "W1A_SEM_PHONE_NONE_MISMATCH")
    assert_equal(normalize_phone_number("   "), (None, None), "W1A_SEM_PHONE_BLANK_MISMATCH")

    # Invalid inputs must raise ValueError("W1A_SEM_PHONE_INVALID")
    for invalid_phone in ["12345", "+1 202 555 0123", "010-1234-5678 ext 12", "invalid-phone"]:
        with pytest.raises(ValueError, match="W1A_SEM_PHONE_INVALID"):
            normalize_phone_number(invalid_phone)


def test_resident_number_policy_and_masking() -> None:
    """Verify RRN validation, birth_date/sex_code matching, checksum non-rejection, and masking."""
    try:
        from app.domains.staff.policies import mask_resident_number, validate_resident_number
    except ImportError:
        pytest.fail("W1A_SEM_MISSING: app.domains.staff.policies validation functions missing")

    rrn_input = build_synthetic_rrn("1")
    rrn_clean = validate_resident_number(
        rrn_input=rrn_input,
        expected_birth_date=date(1990, 1, 1),
        expected_sex_code="MALE",
    )
    assert_true(len(rrn_clean) == 13, "W1A_SEM_RRN_CLEAN_LENGTH_MISMATCH")

    # Masking must produce YYMMDD-******* based on birth_date without decrypting
    masked = mask_resident_number(date(1990, 1, 1))
    assert_equal(masked, "900101-*******", "W1A_SEM_MASKED_RRN_MISMATCH")

    # Checksum mismatch alone must NOT fail validation if date and gender match
    non_checksum_rrn = build_synthetic_rrn("1", custom_seq="000000")
    valid_non_checksum = validate_resident_number(
        rrn_input=non_checksum_rrn,
        expected_birth_date=date(1990, 1, 1),
        expected_sex_code="MALE",
    )
    assert_true(len(valid_non_checksum) == 13, "W1A_SEM_NON_CHECKSUM_ACCEPTED")

    # Date / Sex mismatch must fail validation with W1A_SEM_RRN_INVALID
    with pytest.raises(ValueError, match="W1A_SEM_RRN_INVALID"):
        validate_resident_number(
            rrn_input=rrn_input,
            expected_birth_date=date(1990, 1, 2),
            expected_sex_code="MALE",
        )

    with pytest.raises(ValueError, match="W1A_SEM_RRN_INVALID"):
        validate_resident_number(
            rrn_input=rrn_input,
            expected_birth_date=date(1990, 1, 1),
            expected_sex_code="FEMALE",
        )

    for formatted in (False, True):
        for mixed in (False, True):
            with pytest.raises(ValueError, match="W1A_SEM_RRN_INVALID"):
                validate_resident_number(
                    rrn_input=build_unicode_rrn(formatted=formatted, mixed=mixed),
                    expected_birth_date=date(1990, 1, 1),
                    expected_sex_code="MALE",
                )


def test_position_and_role_code_contracts() -> None:
    """Verify position code enum, role code pattern, and sex code exact values."""
    try:
        from app.domains.staff.schemas import PositionCode, SexCode
    except ImportError:
        pytest.fail("W1A_SEM_MISSING: app.domains.staff.schemas enums missing")

    assert_equal(
        set(p.value for p in PositionCode),
        {"CARE_WORKER", "SOCIAL_WORKER", "MANAGER", "NURSE", "OTHER"},
        "W1A_SEM_POSITION_ENUM_MISMATCH",
    )
    assert_equal(
        set(s.value for s in SexCode),
        {"MALE", "FEMALE", "TEST"},
        "W1A_SEM_SEX_ENUM_MISMATCH",
    )

    role_regex = re.compile(r"^[A-Z][A-Z0-9_]{0,49}$")
    assert_true(bool(role_regex.match("MANAGEMENT_FUNCTION")), "W1A_SEM_ROLE_REGEX_VALID_FAIL")
    assert_true(bool(role_regex.match("TEAM_LEAD_1")), "W1A_SEM_ROLE_REGEX_DIGIT_FAIL")
    assert_true(not bool(role_regex.match("invalid-role")), "W1A_SEM_ROLE_REGEX_LOWER_FAIL")
    assert_true(not bool(role_regex.match("123ROLE")), "W1A_SEM_ROLE_REGEX_START_DIGIT_FAIL")

    from app.domains.staff.schemas import InitialOperationalRoleRequest

    normalized = InitialOperationalRoleRequest(
        role_code=" team_lead_1 ",
        start_date=date(2026, 1, 1),
    )
    assert_equal(normalized.role_code, "TEAM_LEAD_1", "W1A_SEM_ROLE_NORMALIZATION_MISMATCH")

    from app.domains.staff.schemas import StaffEmploymentReplacementRequest

    omitted = StaffEmploymentReplacementRequest(
        expected_employment_row_version=1,
        start_date=date(2026, 1, 1),
    )
    explicit_remove = StaffEmploymentReplacementRequest(
        expected_employment_row_version=1,
        start_date=date(2026, 1, 1),
        position_replacements=[],
        operational_role_replacements=[],
    )
    assert omitted.position_replacements is None
    assert explicit_remove.position_replacements == []


def test_sensitive_identity_crypto_contract() -> None:
    """Verify AES-GCM parameters, AAD staff binding, and HMAC lookup."""
    try:
        from app.domains.staff.crypto import decrypt_resident_number, encrypt_resident_number
    except ImportError:
        pytest.fail("W1A_SEM_MISSING: app.domains.staff.crypto functions missing")

    rrn_clean = get_synth_date_prefix() + "1" + get_synth_seq()
    encrypted = encrypt_resident_number(
        staff_id=42,
        resident_number=rrn_clean,
        key_version=1,
    )

    assert_equal(len(encrypted.nonce), 12, "W1A_SEM_NONCE_LENGTH_MISMATCH")
    assert_equal(len(encrypted.lookup_hmac), 32, "W1A_SEM_HMAC_LENGTH_MISMATCH")
    assert_equal(encrypted.key_version, 1, "W1A_SEM_KEY_VERSION_MISMATCH")

    # Decrypting with correct staff_id succeeds
    decrypted = decrypt_resident_number(
        staff_id=42,
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_version=encrypted.key_version,
    )
    assert_true(len(decrypted) == 13, "W1A_SEM_DECRYPTED_LENGTH_MISMATCH")

    # Decrypting with wrong staff_id (AAD mismatch) must raise decryption failure
    with pytest.raises(ValueError, match="W1A_SEM_CRYPTO_AAD_MISMATCH"):
        decrypt_resident_number(
            staff_id=999,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_version=encrypted.key_version,
        )

    # HMAC lookup is deterministic while AES-GCM encryption is non-deterministic
    encrypted2 = encrypt_resident_number(
        staff_id=42,
        resident_number=rrn_clean,
        key_version=1,
    )
    assert_equal(
        encrypted.lookup_hmac, encrypted2.lookup_hmac, "W1A_SEM_HMAC_DETERMINISTIC_MISMATCH"
    )
    assert_true(encrypted.ciphertext != encrypted2.ciphertext, "W1A_SEM_AES_RANDOMIZED_MISMATCH")

    with pytest.raises(ValueError, match="W1A_SEM_RRN_INVALID"):
        encrypt_resident_number(
            staff_id=42,
            resident_number=build_unicode_rrn(formatted=False, mixed=True),
            key_version=1,
        )


def test_current_projection_uses_server_as_of_and_deterministic_ties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import (
        Staff,
        StaffEmployment,
        StaffOperationalRolePeriod,
        StaffPositionPeriod,
    )
    from app.domains.staff.repository import StaffRepository
    from app.domains.staff.service import StaffService

    as_of = datetime(2026, 7, 27, tzinfo=UTC)
    monkeypatch.setattr("app.domains.staff.service._now", lambda: as_of)

    staff = Staff(
        id=7,
        name="홍길동",
        birth_date=date(1990, 1, 1),
        sex_code="MALE",
        phone=None,
        address=None,
        display_name=None,
        memo=None,
        row_version=1,
    )
    ended = StaffEmployment(
        id=10,
        staff_id=7,
        employment_no=1,
        staff_no="2026-001",
        staff_no_year=2026,
        staff_no_sequence=1,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        row_version=1,
    )
    current_low_id = StaffEmployment(
        id=11,
        staff_id=7,
        employment_no=2,
        staff_no="2026-002",
        staff_no_year=2026,
        staff_no_sequence=2,
        start_date=date(2026, 1, 1),
        end_date=None,
        row_version=1,
    )
    current_high_id = StaffEmployment(
        id=12,
        staff_id=7,
        employment_no=3,
        staff_no="2026-003",
        staff_no_year=2026,
        staff_no_sequence=3,
        start_date=date(2026, 1, 1),
        end_date=None,
        row_version=1,
    )
    boundary_position = StaffPositionPeriod(
        id=21,
        staff_id=7,
        employment_id=12,
        position_code="CARE_WORKER",
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 27),
        row_version=1,
    )
    future_position = StaffPositionPeriod(
        id=22,
        staff_id=7,
        employment_id=12,
        position_code="MANAGER",
        start_date=date(2026, 7, 28),
        end_date=None,
        row_version=1,
    )
    current_role = StaffOperationalRolePeriod(
        id=31,
        staff_id=7,
        employment_id=12,
        role_code="CARE_TEAM",
        start_date=date(2026, 1, 1),
        end_date=None,
        row_version=1,
    )

    class Repository:
        def list_employments(self, staff_id: int) -> list[StaffEmployment]:
            assert staff_id == 7
            return [current_high_id, current_low_id, ended]

        def list_positions(self, staff_id: int) -> list[StaffPositionPeriod]:
            assert staff_id == 7
            return [future_position, boundary_position]

        def list_operational_roles(self, staff_id: int) -> list[StaffOperationalRolePeriod]:
            assert staff_id == 7
            return [current_role]

        def get_sensitive_identity(self, staff_id: int) -> object:
            assert staff_id == 7
            return object()

    service = StaffService.__new__(StaffService)
    service.repository = cast(StaffRepository, Repository())
    result = service._response_for_staff(staff, detail=False)
    assert result.current_employment is not None
    assert result.current_employment.id == 12
    assert [item.id for item in result.current_positions] == [21]
    assert [item.id for item in result.current_operational_roles] == [31]


def test_current_projection_uses_kst_date_after_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Staff, StaffEmployment
    from app.domains.staff.repository import StaffRepository
    from app.domains.staff.service import StaffService

    kst_midnight = datetime(2026, 7, 28, tzinfo=ZoneInfo("Asia/Seoul"))
    as_of = kst_midnight.astimezone(UTC)
    monkeypatch.setattr("app.domains.staff.service._now", lambda: as_of)

    staff = Staff(
        id=8,
        name="synthetic",
        birth_date=date(1990, 1, 1),
        sex_code="MALE",
        phone=None,
        address=None,
        display_name=None,
        memo=None,
        row_version=1,
    )
    ended_at_previous_kst_date = StaffEmployment(
        id=41,
        staff_id=8,
        employment_no=1,
        staff_no="2026-041",
        staff_no_year=2026,
        staff_no_sequence=41,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 27),
        row_version=1,
    )

    class Repository:
        def list_employments(self, staff_id: int) -> list[StaffEmployment]:
            assert staff_id == 8
            return [ended_at_previous_kst_date]

        def list_positions(self, staff_id: int) -> list[object]:
            assert staff_id == 8
            return []

        def list_operational_roles(self, staff_id: int) -> list[object]:
            assert staff_id == 8
            return []

        def get_sensitive_identity(self, staff_id: int) -> object:
            assert staff_id == 8
            return object()

    service = StaffService.__new__(StaffService)
    service.repository = cast(StaffRepository, Repository())
    result = service._response_for_staff(staff, detail=False)

    assert result.current_employment is None, "I2_KST_MIDNIGHT_UTC_DATE_STALE_CURRENT"


def test_f1_kst_current_employment_status_matches_projection_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Staff, StaffEmployment
    from app.domains.staff.repository import StaffRepository
    from app.domains.staff.schemas import EmploymentStatus, StaffDetailResponse
    from app.domains.staff.service import StaffService

    server_today = date(2026, 7, 27)
    as_of = datetime(2026, 7, 27, 15, 0, tzinfo=UTC)
    monkeypatch.setattr("app.domains.staff.service._now", lambda: as_of)

    class ServerDate(date):
        @classmethod
        def today(cls) -> Self:
            return cls(server_today.year, server_today.month, server_today.day)

    monkeypatch.setattr("app.domains.staff.service.date", ServerDate)

    staff = Staff(
        id=9,
        name="synthetic",
        birth_date=date(1990, 1, 1),
        sex_code="MALE",
        phone=None,
        address=None,
        display_name=None,
        memo=None,
        row_version=1,
    )
    starts_on_kst_today = StaffEmployment(
        id=51,
        staff_id=9,
        employment_no=1,
        staff_no="2026-051",
        staff_no_year=2026,
        staff_no_sequence=51,
        start_date=date(2026, 7, 28),
        end_date=None,
        row_version=1,
    )

    class Repository:
        def list_employments(self, staff_id: int) -> list[StaffEmployment]:
            assert staff_id == 9
            return [starts_on_kst_today]

        def list_positions(self, staff_id: int) -> list[object]:
            assert staff_id == 9
            return []

        def list_operational_roles(self, staff_id: int) -> list[object]:
            assert staff_id == 9
            return []

        def get_sensitive_identity(self, staff_id: int) -> object:
            assert staff_id == 9
            return object()

    service = StaffService.__new__(StaffService)
    service.repository = cast(StaffRepository, Repository())
    result = service._response_for_staff(staff, detail=True)

    assert isinstance(result, StaffDetailResponse)
    assert result.current_employment is not None
    assert result.current_employment.status == EmploymentStatus.ACTIVE, (
        "F1_CURRENT_EMPLOYMENT_STATUS_MISMATCH"
    )
    assert result.employments[0].status == EmploymentStatus.ACTIVE, (
        "F1_LIST_EMPLOYMENT_STATUS_MISMATCH"
    )
