"""Stable 409 mapping for W1E deferred reverse-guard integrity errors.

These tests prove that the W1D contract end path and the Staff position /
qualification period paths no longer fall through to a 500 when PostgreSQL
raises the 0012 reverse-guard messages.  The mapping must key on both the
constraint trigger name and the error message because different PostgreSQL
drivers expose ``diag.constraint_name`` or ``message_primary`` differently.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy.exc import IntegrityError, OperationalError

from app.domains.staff.service import StaffService
from app.domains.w1d.service import W1DService
from app.domains.w1e.errors import is_w1e_advisory_lock_loss
from app.domains.w1e.service import W1EService


class _Diagnostic:
    def __init__(self, constraint_name: str, sqlstate: str, message: str | None) -> None:
        self.constraint_name = constraint_name
        self.sqlstate = sqlstate
        self.message_primary = message


class _Original(Exception):
    def __init__(self, diagnostic: _Diagnostic, message: str) -> None:
        super().__init__(message)
        self.diag: _Diagnostic | None = diagnostic
        self.sqlstate = diagnostic.sqlstate
        self._message = message

    def __str__(self) -> str:
        return self._message


def _integrity_error(constraint_name: str, message: str) -> IntegrityError:
    diagnostic = _Diagnostic(constraint_name, "23514", message)
    original = _Original(diagnostic, message)
    return IntegrityError("SELECT", {}, original)


def test_w1d_maps_contract_orphan_guard_to_409() -> None:
    error = _integrity_error(
        "ct_recipient_contract_assignment_reverse_guard",
        "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
    )
    mapped = W1DService._map_integrity_error(error)
    assert mapped.code == "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN"
    assert mapped.status_code == 409


def test_w1d_maps_contract_orphan_message_to_409() -> None:
    error = _integrity_error("", "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN")
    mapped = W1DService._map_integrity_error(error)
    assert mapped.code == "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN"
    assert mapped.status_code == 409


def test_staff_maps_position_orphan_guard_to_409() -> None:
    service = StaffService.__new__(StaffService)
    error = _integrity_error(
        "ct_staff_position_care_assignment_reverse_guard",
        "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
    )
    mapped = StaffService._map_integrity_error(service, error)
    assert mapped.code == "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN"
    assert mapped.status_code == 409


def test_staff_maps_position_orphan_message_to_409() -> None:
    service = StaffService.__new__(StaffService)
    error = _integrity_error("", "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN")
    mapped = StaffService._map_integrity_error(service, error)
    assert mapped.code == "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN"
    assert mapped.status_code == 409


def test_staff_maps_qualification_orphan_guard_to_409() -> None:
    service = StaffService.__new__(StaffService)
    error = _integrity_error(
        "ct_staff_service_qualification_assignment_reverse_guard",
        "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
    )
    mapped = StaffService._map_integrity_error(service, error)
    assert mapped.code == "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN"
    assert mapped.status_code == 409


def test_staff_maps_qualification_orphan_message_to_409() -> None:
    service = StaffService.__new__(StaffService)
    error = _integrity_error("", "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN")
    mapped = StaffService._map_integrity_error(service, error)
    assert mapped.code == "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN"
    assert mapped.status_code == 409


def _deadlock_error() -> OperationalError:
    diagnostic = _Diagnostic("", "40P01", "deadlock detected")
    original = _Original(diagnostic, "deadlock detected")
    return OperationalError("SELECT", {}, original)


def _lock_conflict_error() -> OperationalError:
    diagnostic = _Diagnostic("", "55P03", "CARE_ASSIGNMENT_CONCURRENT_CONFLICT")
    original = _Original(diagnostic, "CARE_ASSIGNMENT_CONCURRENT_CONFLICT")
    return OperationalError("SELECT", {}, original)


def _lock_timeout_error() -> OperationalError:
    diagnostic = _Diagnostic("", "55P03", "canceling statement due to lock timeout")
    original = _Original(diagnostic, "canceling statement due to lock timeout")
    return OperationalError("SELECT", {}, original)


def _nowait_lock_error() -> OperationalError:
    diagnostic = _Diagnostic(
        "",
        "55P03",
        'could not obtain lock on row in relation "staff_employment"',
    )
    original = _Original(
        diagnostic,
        'could not obtain lock on row in relation "staff_employment"',
    )
    return OperationalError("SELECT", {}, original)


def _lock_conflict_error_via_cause() -> OperationalError:
    inner = _Original(
        _Diagnostic("", "55P03", "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"),
        "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
    )
    wrapped = OperationalError("SELECT", {}, cast(BaseException, None))
    wrapped.__cause__ = inner
    return wrapped


def test_w1e_maps_40p01_operational_error_to_409() -> None:
    mapped = W1EService._map_sqlalchemy_error(_deadlock_error())
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_w1e_maps_40p01_integrity_wrapper_to_409() -> None:
    diagnostic = _Diagnostic("", "40P01", "deadlock detected")
    original = _Original(diagnostic, "deadlock detected")
    mapped = W1EService._map_integrity_error(IntegrityError("SELECT", {}, original))
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_w1e_maps_55p03_operational_error_to_409() -> None:
    mapped = W1EService._map_sqlalchemy_error(_lock_conflict_error())
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_w1e_maps_nested_cause_55p03_lock_loss_to_409() -> None:
    mapped = W1EService._map_sqlalchemy_error(_lock_conflict_error_via_cause())
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_w1e_does_not_relabel_unrelated_55p03_as_assignment_conflict() -> None:
    timeout_mapped = W1EService._map_sqlalchemy_error(_lock_timeout_error())
    assert timeout_mapped.code == "UNEXPECTED_SERVER_ERROR"
    assert timeout_mapped.status_code == 500
    nowait_mapped = W1EService._map_sqlalchemy_error(_nowait_lock_error())
    assert nowait_mapped.code == "UNEXPECTED_SERVER_ERROR"
    assert nowait_mapped.status_code == 500
    assert is_w1e_advisory_lock_loss(_lock_conflict_error()) is True
    assert is_w1e_advisory_lock_loss(_lock_timeout_error()) is False
    assert is_w1e_advisory_lock_loss(_nowait_lock_error()) is False


def _lock_timeout_error_with_conflict_code_in_wrapper() -> OperationalError:
    diagnostic = _Diagnostic("", "55P03", None)
    original = _Original(
        diagnostic,
        "canceling statement due to lock timeout\n"
        "[SQL: SELECT 1 /* CARE_ASSIGNMENT_CONCURRENT_CONFLICT */]",
    )
    assert original.diag is diagnostic
    diagnostic.message_primary = None
    return OperationalError("SELECT", {}, original)


def _lock_conflict_error_without_diag_first_line() -> OperationalError:
    original = _Original(_Diagnostic("", "55P03", None), "")
    original.diag = None
    original.sqlstate = "55P03"
    original._message = "(psycopg.errors.LockNotAvailable) CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    return OperationalError("SELECT", {}, original)


def test_w1e_does_not_treat_wrapper_substring_as_lock_loss_message() -> None:
    wrapped = _lock_timeout_error_with_conflict_code_in_wrapper()
    assert is_w1e_advisory_lock_loss(wrapped) is False
    mapped = W1EService._map_sqlalchemy_error(wrapped)
    assert mapped.code == "UNEXPECTED_SERVER_ERROR"
    assert mapped.status_code == 500


def test_w1e_recognizes_exact_sqlalchemy_first_line_lock_loss() -> None:
    wrapped = _lock_conflict_error_without_diag_first_line()
    assert is_w1e_advisory_lock_loss(wrapped) is True
    mapped = W1EService._map_sqlalchemy_error(wrapped)
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_w1e_maps_assignment_guard_race_to_409_concurrent_conflict() -> None:
    for constraint_name in (
        "ct_care_assignment_within_contract",
        "ct_care_assignment_within_employment",
        "ct_care_assignment_within_position",
        "ct_care_assignment_general_care_qualified",
    ):
        mapped = W1EService._map_integrity_error(
            _integrity_error(constraint_name, "CARE_ASSIGNMENT_STAFF_INELIGIBLE")
        )
        assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT", constraint_name
        assert mapped.status_code == 409, constraint_name


def test_w1e_maps_deferred_guard_messages_without_constraint_name_to_409() -> None:
    for message in (
        "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
        "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
        "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
    ):
        mapped = W1EService._map_integrity_error(_integrity_error("", message))
        assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT", message
        assert mapped.status_code == 409, message


def test_w1d_maps_55p03_parent_guard_lock_loss_to_409() -> None:
    w1d = W1DService.__new__(W1DService)
    mapped = w1d._map_sqlalchemy_error(_lock_conflict_error())
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_staff_maps_55p03_parent_guard_lock_loss_to_409() -> None:
    staff = StaffService.__new__(StaffService)
    mapped = StaffService._map_sqlalchemy_error(staff, _lock_conflict_error())
    assert mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert mapped.status_code == 409


def test_w1d_and_staff_do_not_relabel_unrelated_55p03_as_assignment_conflict() -> None:
    w1d = W1DService.__new__(W1DService)
    w1d_timeout = w1d._map_sqlalchemy_error(_lock_timeout_error())
    assert w1d_timeout.code == "UNEXPECTED_SERVER_ERROR"
    assert w1d_timeout.status_code == 500
    w1d_nowait = w1d._map_sqlalchemy_error(_nowait_lock_error())
    assert w1d_nowait.code == "UNEXPECTED_SERVER_ERROR"
    assert w1d_nowait.status_code == 500
    staff = StaffService.__new__(StaffService)
    staff_timeout = StaffService._map_sqlalchemy_error(staff, _lock_timeout_error())
    assert staff_timeout.code == "UNEXPECTED_SERVER_ERROR"
    assert staff_timeout.status_code == 500
    staff_nowait = StaffService._map_sqlalchemy_error(staff, _nowait_lock_error())
    assert staff_nowait.code == "UNEXPECTED_SERVER_ERROR"
    assert staff_nowait.status_code == 500


def test_w1d_and_staff_map_integrity_wrapped_lock_loss_to_409() -> None:
    original = _lock_conflict_error().orig
    assert isinstance(original, BaseException)
    wrapped = IntegrityError("SELECT", {}, original)
    w1d_mapped = W1DService._map_integrity_error(wrapped)
    assert w1d_mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert w1d_mapped.status_code == 409
    staff = StaffService.__new__(StaffService)
    staff_mapped = StaffService._map_integrity_error(staff, wrapped)
    assert staff_mapped.code == "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    assert staff_mapped.status_code == 409


def test_w1d_and_staff_do_not_relabel_40p01_as_w1e_assignment_conflict() -> None:
    # SQLSTATE 40P01 on W1D/Staff cannot be attributed to W1E locks alone.
    # The fine-grained 55P03 W1E lock loss maps to CARE_ASSIGNMENT_CONCURRENT_CONFLICT,
    # but a generic deadlock remains 500 on these surfaces.
    diagnostic = _Diagnostic("", "40P01", "deadlock detected")
    original = _Original(diagnostic, "deadlock detected")
    wrapped = IntegrityError("SELECT", {}, original)
    w1d_mapped = W1DService._map_integrity_error(wrapped)
    assert w1d_mapped.code == "UNEXPECTED_SERVER_ERROR"
    assert w1d_mapped.status_code == 500
    staff = StaffService.__new__(StaffService)
    staff_mapped = StaffService._map_integrity_error(staff, wrapped)
    assert staff_mapped.code == "UNEXPECTED_SERVER_ERROR"
    assert staff_mapped.status_code == 500


def test_openapi_documents_reverse_guard_orphan_codes() -> None:
    from app.main import app

    spec = app.openapi()
    blob = str(spec)
    for code in (
        "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
        "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
    ):
        assert code in blob, code
