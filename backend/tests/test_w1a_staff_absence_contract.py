import pytest


def test_forbidden_legacy_and_status_properties_absent() -> None:
    """Verify legacy fields and standalone work-status columns are absent."""
    try:
        from app.db.models import Staff, StaffEmployment
    except ImportError:
        pytest.fail("W1A_ABS_MISSING: Staff / StaffEmployment models missing in app.db.models")

    # Standalone work status columns must NOT exist in DB models
    assert not hasattr(Staff, "work_status"), (
        "W1A_ABS_STAFF_WORK_STATUS_FOUND: Staff model must not have 'work_status'"
    )
    assert not hasattr(Staff, "employment_status"), (
        "W1A_ABS_STAFF_EMP_STATUS_FOUND: Staff model must not have 'employment_status'"
    )
    assert not hasattr(StaffEmployment, "work_status"), (
        "W1A_ABS_EMPLOYMENT_WORK_STATUS_FOUND: StaffEmployment must not have 'work_status'"
    )

    # Plaintext RRN must NOT exist on Staff model
    assert not hasattr(Staff, "resident_number"), (
        "W1A_ABS_STAFF_PLAINTEXT_RRN_FOUND: Staff model must not have 'resident_number'"
    )
    assert not hasattr(Staff, "rrn"), "W1A_ABS_STAFF_RRN_FOUND: Staff model must not have 'rrn'"

    # Legacy mapping columns must NOT exist on Staff model in W1A-VS1
    assert not hasattr(Staff, "legacy_id"), (
        "W1A_ABS_STAFF_LEGACY_ID_FOUND: Staff model must not have 'legacy_id'"
    )
    assert not hasattr(Staff, "staff_legacy_mapping"), (
        "W1A_ABS_STAFF_LEGACY_MAPPING_FOUND: Staff model must not have 'staff_legacy_mapping'"
    )


def test_preserved_wave0_columns_present() -> None:
    """Verify Wave 0 staff.display_name and staff.memo are preserved."""
    try:
        from app.db.models import Staff
    except ImportError:
        pytest.fail("W1A_ABS_MISSING: Staff model missing in app.db.models")

    assert hasattr(Staff, "display_name"), (
        "W1A_ABS_DISPLAY_NAME_REMOVED: Wave 0 'display_name' must be preserved"
    )
    assert hasattr(Staff, "memo"), "W1A_ABS_MEMO_REMOVED: Wave 0 'memo' must be preserved"


def test_phone_normalized_absent_from_general_dto() -> None:
    """Verify phone_normalized is internal/DB-only and absent from general public DTOs."""
    try:
        from app.domains.staff.schemas import StaffDetailResponse, StaffResponse
    except ImportError:
        pytest.fail("W1A_ABS_MISSING: W1A staff DTOs missing in app.domains.staff.schemas")

    assert "phone_normalized" not in StaffResponse.model_fields, (
        "W1A_ABS_PHONE_NORMALIZED_LEAK_RESPONSE: StaffResponse exposes 'phone_normalized'"
    )
    assert "phone_normalized" not in StaffDetailResponse.model_fields, (
        "W1A_ABS_PHONE_NORMALIZED_LEAK_DETAIL: StaffDetailResponse exposes 'phone_normalized'"
    )
    assert "resident_number" not in StaffResponse.model_fields, (
        "W1A_ABS_RRN_LEAK_RESPONSE: StaffResponse exposes 'resident_number'"
    )
    assert "resident_number" not in StaffDetailResponse.model_fields, (
        "W1A_ABS_RRN_LEAK_DETAIL: StaffDetailResponse exposes 'resident_number'"
    )
