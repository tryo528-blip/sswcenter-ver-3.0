"""Private, memory-only one-off staff legacy import helpers.

This module deliberately has no API, HTTP, OpenAPI, or persistence surface of
its own.  ``prepare`` returns counts only; ``apply`` owns one transaction for
the complete included batch.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings, get_settings
from app.db.models import (
    AuditEvent,
    LicenseType,
    Staff,
    StaffEmployment,
    StaffLegacyMapping,
    StaffLicense,
    StaffPositionPeriod,
    StaffSensitiveIdentity,
)
from app.domains.staff.crypto import encrypt_resident_number
from app.domains.staff.policies import normalize_phone_number, validate_resident_number
from app.domains.staff.repository import StaffRepository

_ROW_FIELDS = frozenset(
    {
        "legacy_staff_key",
        "name",
        "resident_number",
        "address",
        "phone",
        "employment_start_date",
        "employment_end_date",
        "position",
        "licenses",
    }
)
_LICENSE_FIELDS = frozenset({"type", "number", "issued_date"})
_POSITION_CODES = frozenset({"CARE_WORKER", "SOCIAL_WORKER", "MANAGER", "NURSE", "OTHER"})
_PRESERVED_STAFF_FIELDS = ("display_name", "memo")
_REASON_CODES = frozenset(
    {
        "ALREADY_MAPPED",
        "DUPLICATE_SOURCE_KEY",
        "INVALID_REQUIRED_FIELD",
        "INVALID_DATE_RANGE",
        "TOO_MANY_LICENSES",
        "STAFF_MATCH_MISSING",
        "STAFF_MATCH_AMBIGUOUS",
    }
)
_MAPPING_AUDIT_ACTIONS = (
    "STAFF_LEGACY_MAPPING_CREATE",
    "STAFF_LEGACY_MAPPING_INVALIDATE",
    "STAFF_LEGACY_MAPPING_REPLACEMENT_CREATE",
)
# Keep the ledger relation name explicit for the private import contract.
_STAFF_LEGACY_MAPPING_TABLE = "staff_legacy_mapping"


class LegacyImportError(RuntimeError):
    """Stable internal failure without source-row or database diagnostics."""

    def __init__(self, code: str = "UNEXPECTED_SERVER_ERROR") -> None:
        self.code = code
        super().__init__(code)


class _RejectedRow(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


@dataclass(frozen=True)
class _PreparedLicense:
    license_type: str
    license_number: str
    issued_date: date


@dataclass(frozen=True)
class _PreparedRow:
    legacy_staff_key: str
    name: str
    resident_number: str
    birth_date: date
    sex_code: str
    address: str | None
    phone: str | None
    phone_normalized: str | None
    employment_start_date: date
    employment_end_date: date | None
    position: str
    licenses: tuple[_PreparedLicense, ...]


def _summary(included_count: int, excluded_count: int, reasons: Counter[str]) -> dict[str, object]:
    return {
        "included_count": included_count,
        "excluded_count": excluded_count,
        "reason_counts": dict(sorted(reasons.items())),
    }


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _resident_parts(value: object) -> tuple[str, date, str] | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    normalized = raw.replace("-", "")
    if len(normalized) != 13 or not normalized.isascii() or not normalized.isdecimal():
        return None
    century_by_code = {
        "0": 1800,
        "1": 1900,
        "2": 1900,
        "3": 2000,
        "4": 2000,
        "5": 1900,
        "6": 1900,
        "7": 2000,
        "8": 2000,
        "9": 1800,
    }
    century = century_by_code.get(normalized[6])
    if century is None:
        return None
    try:
        birth_date = date(
            century + int(normalized[:2]),
            int(normalized[2:4]),
            int(normalized[4:6]),
        )
    except ValueError:
        return None
    sex_code = "MALE" if int(normalized[6]) % 2 else "FEMALE"
    try:
        validated = validate_resident_number(
            rrn_input=raw,
            expected_birth_date=birth_date,
            expected_sex_code=sex_code,
        )
    except ValueError:
        return None
    return validated, birth_date, sex_code


def _prepare_one(row: Mapping[str, object]) -> _PreparedRow:
    if set(row) - _ROW_FIELDS:
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    for field in (
        "legacy_staff_key",
        "name",
        "resident_number",
        "employment_start_date",
        "position",
    ):
        if field not in row:
            raise _RejectedRow("INVALID_REQUIRED_FIELD")

    legacy_staff_key = _text(row.get("legacy_staff_key"))
    name = _text(row.get("name"))
    resident_parts = _resident_parts(row.get("resident_number"))
    start_date = _date_value(row.get("employment_start_date"))
    position = _text(row.get("position"))
    if (
        legacy_staff_key is None
        or name is None
        or resident_parts is None
        or start_date is None
        or position is None
        or position.upper() not in _POSITION_CODES
    ):
        raise _RejectedRow("INVALID_REQUIRED_FIELD")

    end_value = row.get("employment_end_date")
    end_date = None if end_value is None else _date_value(end_value)
    if end_value is not None and end_date is None:
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    if end_date is not None and start_date > end_date:
        raise _RejectedRow("INVALID_DATE_RANGE")

    address_value = row.get("address")
    if address_value is not None and not isinstance(address_value, str):
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    address = address_value.strip() if isinstance(address_value, str) else None

    phone_value = row.get("phone")
    if phone_value is not None and not isinstance(phone_value, str):
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    try:
        phone, phone_normalized = normalize_phone_number(phone_value)
    except ValueError:
        raise _RejectedRow("INVALID_REQUIRED_FIELD") from None

    licenses_value = row.get("licenses", [])
    if not isinstance(licenses_value, list):
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    if len(licenses_value) > 2:
        raise _RejectedRow("TOO_MANY_LICENSES")
    licenses: list[_PreparedLicense] = []
    for license_row in licenses_value:
        if not isinstance(license_row, Mapping) or set(license_row) != _LICENSE_FIELDS:
            raise _RejectedRow("INVALID_REQUIRED_FIELD")
        license_type = _text(license_row.get("type"))
        license_number = _text(license_row.get("number"))
        issued_date = _date_value(license_row.get("issued_date"))
        if license_type is None or license_number is None or issued_date is None:
            raise _RejectedRow("INVALID_REQUIRED_FIELD")
        licenses.append(
            _PreparedLicense(
                license_type=license_type.upper(),
                license_number=license_number,
                issued_date=issued_date,
            )
        )

    normalized_resident, birth_date, sex_code = resident_parts
    return _PreparedRow(
        legacy_staff_key=legacy_staff_key,
        name=name,
        resident_number=normalized_resident,
        birth_date=birth_date,
        sex_code=sex_code,
        address=address,
        phone=phone,
        phone_normalized=phone_normalized,
        employment_start_date=start_date,
        employment_end_date=end_date,
        position=position.upper(),
        licenses=tuple(licenses),
    )


def _active_key_set(active_legacy_staff_keys: Iterable[object]) -> set[str]:
    keys: set[str] = set()
    for value in active_legacy_staff_keys:
        if isinstance(value, tuple) and len(value) == 2:
            value = value[1]
        if isinstance(value, str) and value.strip():
            keys.add(value.strip())
    return keys


def _prepare_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    source_system_code: str,
    active_legacy_staff_keys: Iterable[object],
) -> tuple[list[_PreparedRow], dict[str, object]]:
    source_code = _text(source_system_code)
    if source_code is None:
        raise ValueError("source_system_code is required")
    raw_rows = list(rows)
    active_keys = _active_key_set(active_legacy_staff_keys)
    candidate_keys: list[str | None] = []
    for row in raw_rows:
        if not isinstance(row, Mapping) or set(row) - _ROW_FIELDS:
            candidate_keys.append(None)
            continue
        key = _text(row.get("legacy_staff_key"))
        candidate_keys.append(key)
    duplicate_counts = Counter(key for key in candidate_keys if key is not None)

    prepared: list[_PreparedRow] = []
    reasons: Counter[str] = Counter()
    for row, candidate_key in zip(raw_rows, candidate_keys, strict=True):
        if candidate_key is None:
            reasons["INVALID_REQUIRED_FIELD"] += 1
            continue
        if duplicate_counts[candidate_key] > 1:
            reasons["DUPLICATE_SOURCE_KEY"] += 1
            continue
        if candidate_key in active_keys:
            reasons["ALREADY_MAPPED"] += 1
            continue
        try:
            prepared.append(_prepare_one(row))
        except _RejectedRow as exc:
            reasons[exc.reason] += 1
    return prepared, _summary(len(prepared), len(raw_rows) - len(prepared), reasons)


def prepare(
    rows: Iterable[Mapping[str, object]],
    source_system_code: str,
    active_legacy_staff_keys: Iterable[object],
) -> dict[str, object]:
    """Validate an in-memory batch and return only safe counts and reasons."""

    _prepared, summary = _prepare_rows(
        rows,
        source_system_code=source_system_code,
        active_legacy_staff_keys=active_legacy_staff_keys,
    )
    return summary


def _audit(
    database_session: Session,
    *,
    actor_account_id: int,
    action_code: str,
    entity_type: str,
    entity_pk: int,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    occurred_at_utc: datetime | None = None,
) -> None:
    database_session.add(
        AuditEvent(
            occurred_at_utc=occurred_at_utc or datetime.now(UTC),
            actor_account_id=actor_account_id,
            actor_kind="USER",
            action_code=action_code,
            entity_type=entity_type,
            entity_pk=entity_pk,
            before_json=before,
            after_json=after,
            created_from="LEGACY_IMPORT",
        )
    )


def _find_staff(
    database_session: Session,
    *,
    prepared: _PreparedRow,
    settings: Settings,
    actor_account_id: int,
) -> Staff:
    lookup = encrypt_resident_number(
        staff_id=0,
        resident_number=prepared.resident_number,
        settings=settings,
    )
    identity = database_session.scalar(
        select(StaffSensitiveIdentity)
        .where(StaffSensitiveIdentity.resident_number_lookup_hmac == lookup.lookup_hmac)
        .with_for_update()
    )
    if identity is not None:
        staff = database_session.scalar(
            select(Staff).where(Staff.id == identity.staff_id).with_for_update()
        )
        if staff is None:
            raise LegacyImportError("STAFF_MATCH_MISSING")
        staff.name = prepared.name
        staff.address = prepared.address
        staff.phone = prepared.phone
        staff.phone_normalized = prepared.phone_normalized
        staff.updated_at_utc = datetime.now(UTC)
        staff.row_version += 1
        return staff

    staff = Staff(
        name=prepared.name,
        birth_date=prepared.birth_date,
        sex_code=prepared.sex_code,
        phone=prepared.phone,
        phone_normalized=prepared.phone_normalized,
        address=prepared.address,
    )
    database_session.add(staff)
    database_session.flush()
    encrypted = encrypt_resident_number(
        staff_id=staff.id,
        resident_number=prepared.resident_number,
        settings=settings,
    )
    database_session.add(
        StaffSensitiveIdentity(
            staff_id=staff.id,
            resident_number_ciphertext=encrypted.ciphertext,
            resident_number_nonce=encrypted.nonce,
            resident_number_key_version=encrypted.key_version,
            resident_number_lookup_hmac=encrypted.lookup_hmac,
        )
    )
    _audit(
        database_session,
        actor_account_id=actor_account_id,
        action_code="STAFF_CREATE",
        entity_type="STAFF",
        entity_pk=staff.id,
        after={"staff_id": staff.id},
    )
    return staff


def _find_or_create_employment(
    database_session: Session,
    *,
    staff: Staff,
    prepared: _PreparedRow,
    actor_account_id: int,
) -> StaffEmployment:
    repository = StaffRepository(database_session)
    employments = repository.list_employments(staff.id)
    for employment in employments:
        if (
            employment.start_date == prepared.employment_start_date
            and employment.end_date == prepared.employment_end_date
        ):
            return employment
    staff_number = repository.next_staff_number(prepared.employment_start_date.year)
    employment = StaffEmployment(
        staff_id=staff.id,
        employment_no=repository.next_employment_number(staff.id),
        staff_no=f"{prepared.employment_start_date.year}-{staff_number:03d}",
        staff_no_year=prepared.employment_start_date.year,
        staff_no_sequence=staff_number,
        start_date=prepared.employment_start_date,
        end_date=prepared.employment_end_date,
        created_by_account_id=actor_account_id,
        updated_by_account_id=actor_account_id,
    )
    database_session.add(employment)
    database_session.flush()
    return employment


def _ensure_position(
    database_session: Session,
    *,
    staff: Staff,
    employment: StaffEmployment,
    prepared: _PreparedRow,
    actor_account_id: int,
) -> None:
    existing = database_session.scalar(
        select(StaffPositionPeriod).where(
            StaffPositionPeriod.staff_id == staff.id,
            StaffPositionPeriod.employment_id == employment.id,
            StaffPositionPeriod.position_code == prepared.position,
            StaffPositionPeriod.invalidated_at_utc.is_(None),
        )
    )
    if existing is not None:
        return
    start_date = max(prepared.employment_start_date, employment.start_date)
    end_date = prepared.employment_end_date or employment.end_date
    if end_date is not None and start_date > end_date:
        raise LegacyImportError("INVALID_DATE_RANGE")
    database_session.add(
        StaffPositionPeriod(
            staff_id=staff.id,
            employment_id=employment.id,
            position_code=prepared.position,
            start_date=start_date,
            end_date=end_date,
            created_by_account_id=actor_account_id,
            updated_by_account_id=actor_account_id,
        )
    )
    database_session.flush()


def _ensure_licenses(
    database_session: Session,
    *,
    staff: Staff,
    licenses: tuple[_PreparedLicense, ...],
    actor_account_id: int,
) -> None:
    for license_row in licenses:
        license_type = database_session.scalar(
            select(LicenseType).where(
                LicenseType.code == license_row.license_type,
                LicenseType.active.is_(True),
            )
        )
        if license_type is None:
            raise LegacyImportError("STAFF_LICENSE_TYPE_NOT_FOUND")
        existing = database_session.scalar(
            select(StaffLicense).where(
                StaffLicense.staff_id == staff.id,
                StaffLicense.license_type_id == license_type.id,
                StaffLicense.license_number == license_row.license_number,
                StaffLicense.invalidated_at_utc.is_(None),
            )
        )
        if existing is not None:
            continue
        database_session.add(
            StaffLicense(
                staff_id=staff.id,
                license_type_id=license_type.id,
                license_number=license_row.license_number,
                issued_date=license_row.issued_date,
                created_by_account_id=actor_account_id,
                updated_by_account_id=actor_account_id,
            )
        )
        database_session.flush()


def _apply_in_transaction(
    database_session: Session,
    *,
    prepared: list[_PreparedRow],
    source_system_code: str,
    actor_account_id: int,
    settings: Settings,
) -> None:
    for row in prepared:
        staff = _find_staff(
            database_session,
            prepared=row,
            settings=settings,
            actor_account_id=actor_account_id,
        )
        employment = _find_or_create_employment(
            database_session,
            staff=staff,
            prepared=row,
            actor_account_id=actor_account_id,
        )
        _ensure_position(
            database_session,
            staff=staff,
            employment=employment,
            prepared=row,
            actor_account_id=actor_account_id,
        )
        _ensure_licenses(
            database_session,
            staff=staff,
            licenses=row.licenses,
            actor_account_id=actor_account_id,
        )
        mapping = StaffLegacyMapping(
            source_system_code=source_system_code,
            legacy_staff_key=row.legacy_staff_key,
            staff_id=staff.id,
            source_row_fingerprint=None,
            invalidated_at_utc=None,
            created_by_account_id=actor_account_id,
            updated_by_account_id=actor_account_id,
        )
        database_session.add(mapping)
        database_session.flush()
        _audit(
            database_session,
            actor_account_id=actor_account_id,
            action_code="STAFF_LEGACY_MAPPING_CREATE",
            entity_type="STAFF_LEGACY_MAPPING",
            entity_pk=mapping.id,
            after={"staff_id": staff.id, "row_version": mapping.row_version},
        )


def _safe_rollback(database_session: Session) -> None:
    try:
        database_session.rollback()
    except Exception:
        # A failed rollback must never replace the stable importer error.
        pass


def _integrity_error_code(error: IntegrityError) -> str:
    original = getattr(error, "orig", None)
    diagnostics = getattr(original, "diag", None)
    constraint_name = getattr(diagnostics, "constraint_name", None)
    if not isinstance(constraint_name, str):
        return "UNEXPECTED_SERVER_ERROR"
    return {
        "ex_staff_employment_period": "STAFF_EMPLOYMENT_PERIOD_CONFLICT",
        "ex_staff_position_period": "STAFF_PERIOD_CONFLICT",
        "uq_staff_license_type_number_active": "STAFF_LICENSE_DUPLICATE",
        "uq_staff_legacy_mapping_active": "STAFF_LEGACY_MAPPING_ALREADY_ACTIVE",
        "fk_staff_legacy_mapping_staff_id_staff": "STAFF_MATCH_MISSING",
        "fk_staff_legacy_mapping_replacement": "STAFF_LEGACY_MAPPING_REPLACEMENT_INVALID",
    }.get(constraint_name, "UNEXPECTED_SERVER_ERROR")


def _run_atomic(
    database_session: Session,
    operation: Callable[[Session], object],
) -> object:
    result: object | None = None
    error_code: str | None = None
    try:
        with database_session.begin():
            result = operation(database_session)
    except IntegrityError as exc:
        error_code = _integrity_error_code(exc)
    except SQLAlchemyError:
        error_code = "UNEXPECTED_SERVER_ERROR"
    except LegacyImportError as exc:
        error_code = exc.code
    except Exception:
        error_code = "UNEXPECTED_SERVER_ERROR"

    if error_code is not None:
        _safe_rollback(database_session)
        raise LegacyImportError(error_code) from None
    return result


def _run_with_factory(
    session_factory: sessionmaker[Session],
    operation: Callable[[Session], object],
) -> object:
    try:
        managed_session = session_factory()
    except SQLAlchemyError:
        raise LegacyImportError("UNEXPECTED_SERVER_ERROR") from None
    except Exception:
        raise LegacyImportError("UNEXPECTED_SERVER_ERROR") from None
    try:
        return _run_atomic(managed_session, operation)
    finally:
        try:
            managed_session.close()
        except Exception:
            pass


def _mapping_audit_snapshot(mapping: StaffLegacyMapping) -> dict[str, object]:
    return {
        "mapping_id": mapping.id,
        "staff_id": mapping.staff_id,
        "row_version": mapping.row_version,
        "invalidated_at_utc": (
            mapping.invalidated_at_utc.isoformat()
            if mapping.invalidated_at_utc is not None
            else None
        ),
        "replacement_mapping_id": mapping.replacement_staff_legacy_mapping_id,
        "updated_by_account_id": mapping.updated_by_account_id,
        "updated_at_utc": (
            mapping.updated_at_utc.isoformat() if mapping.updated_at_utc is not None else None
        ),
    }


def _lock_active_mapping(
    database_session: Session,
    *,
    mapping_id: int,
) -> StaffLegacyMapping:
    mapping = database_session.scalar(
        select(StaffLegacyMapping)
        .where(
            StaffLegacyMapping.id == mapping_id,
            StaffLegacyMapping.invalidated_at_utc.is_(None),
        )
        .with_for_update()
    )
    if mapping is None:
        historical_id = database_session.scalar(
            select(StaffLegacyMapping.id).where(StaffLegacyMapping.id == mapping_id)
        )
        if historical_id is not None:
            raise LegacyImportError("ROW_VERSION_CONFLICT")
        raise LegacyImportError("STAFF_LEGACY_MAPPING_NOT_FOUND")
    return mapping


def _validate_mapping_request(
    mapping: StaffLegacyMapping,
    *,
    source_system_code: str | None,
    legacy_staff_key: str | None,
    expected_row_version: int,
) -> None:
    if not isinstance(expected_row_version, int) or expected_row_version <= 0:
        raise LegacyImportError("ROW_VERSION_CONFLICT")
    if mapping.row_version != expected_row_version:
        raise LegacyImportError("ROW_VERSION_CONFLICT")
    if source_system_code is not None and _text(source_system_code) != mapping.source_system_code:
        raise LegacyImportError("STAFF_LEGACY_MAPPING_IDENTITY_MISMATCH")
    if legacy_staff_key is not None and _text(legacy_staff_key) != mapping.legacy_staff_key:
        raise LegacyImportError("STAFF_LEGACY_MAPPING_IDENTITY_MISMATCH")


def _invalidate_mapping_in_transaction(
    database_session: Session,
    *,
    mapping_id: int,
    source_system_code: str | None,
    legacy_staff_key: str | None,
    actor_account_id: int,
    expected_row_version: int,
) -> dict[str, object]:
    mapping = _lock_active_mapping(database_session, mapping_id=mapping_id)
    _validate_mapping_request(
        mapping,
        source_system_code=source_system_code,
        legacy_staff_key=legacy_staff_key,
        expected_row_version=expected_row_version,
    )
    now = datetime.now(UTC)
    before = _mapping_audit_snapshot(mapping)
    mapping.invalidated_at_utc = now
    mapping.updated_by_account_id = actor_account_id
    mapping.updated_at_utc = now
    mapping.row_version += 1
    database_session.flush()
    _audit(
        database_session,
        actor_account_id=actor_account_id,
        action_code="STAFF_LEGACY_MAPPING_INVALIDATE",
        entity_type="STAFF_LEGACY_MAPPING",
        entity_pk=mapping.id,
        before=before,
        after=_mapping_audit_snapshot(mapping),
        occurred_at_utc=now,
    )
    database_session.flush()
    return {
        "mapping_id": mapping.id,
        "row_version": mapping.row_version,
        "invalidated_at_utc": now.isoformat(),
    }


def invalidate_mapping(
    mapping_id: int,
    *,
    source_system_code: str | None = None,
    legacy_staff_key: str | None = None,
    database_session: Session | None = None,
    session: Session | None = None,
    session_factory: sessionmaker[Session] | None = None,
    actor_account_id: int | None = None,
    settings: Settings | None = None,
    expected_row_version: int,
) -> dict[str, object]:
    """Invalidate one active internal mapping with optimistic locking."""

    del settings
    if actor_account_id is None or actor_account_id <= 0:
        raise ValueError("actor_account_id is required")
    if database_session is not None and session is not None:
        raise ValueError("provide one database session")
    database_session = database_session or session

    def execute(current_session: Session) -> object:
        return _invalidate_mapping_in_transaction(
            current_session,
            mapping_id=mapping_id,
            source_system_code=source_system_code,
            legacy_staff_key=legacy_staff_key,
            actor_account_id=actor_account_id,
            expected_row_version=expected_row_version,
        )

    if database_session is not None:
        return _run_atomic(database_session, execute)  # type: ignore[return-value]
    if session_factory is None:
        raise ValueError("database session or session factory is required")
    return _run_with_factory(session_factory, execute)  # type: ignore[return-value]


def _replace_mapping_in_transaction(
    database_session: Session,
    *,
    mapping_id: int,
    replacement_staff_id: int,
    source_system_code: str | None,
    legacy_staff_key: str | None,
    actor_account_id: int,
    expected_row_version: int,
) -> dict[str, object]:
    mapping = _lock_active_mapping(database_session, mapping_id=mapping_id)
    _validate_mapping_request(
        mapping,
        source_system_code=source_system_code,
        legacy_staff_key=legacy_staff_key,
        expected_row_version=expected_row_version,
    )
    replacement_staff = database_session.scalar(
        select(Staff).where(Staff.id == replacement_staff_id).with_for_update()
    )
    if replacement_staff is None:
        raise LegacyImportError("STAFF_MATCH_MISSING")

    now = datetime.now(UTC)
    before = _mapping_audit_snapshot(mapping)
    mapping.invalidated_at_utc = now
    mapping.updated_by_account_id = actor_account_id
    mapping.updated_at_utc = now
    mapping.row_version += 1
    database_session.flush()

    replacement = StaffLegacyMapping(
        source_system_code=mapping.source_system_code,
        legacy_staff_key=mapping.legacy_staff_key,
        staff_id=replacement_staff.id,
        source_row_fingerprint=mapping.source_row_fingerprint,
        invalidated_at_utc=None,
        created_by_account_id=actor_account_id,
        created_at_utc=now,
        updated_by_account_id=actor_account_id,
        updated_at_utc=now,
        row_version=1,
    )
    database_session.add(replacement)
    database_session.flush()
    mapping.replacement_staff_legacy_mapping_id = replacement.id
    database_session.flush()

    _audit(
        database_session,
        actor_account_id=actor_account_id,
        action_code="STAFF_LEGACY_MAPPING_INVALIDATE",
        entity_type="STAFF_LEGACY_MAPPING",
        entity_pk=mapping.id,
        before=before,
        after=_mapping_audit_snapshot(mapping),
        occurred_at_utc=now,
    )
    database_session.flush()
    _audit(
        database_session,
        actor_account_id=actor_account_id,
        action_code="STAFF_LEGACY_MAPPING_REPLACEMENT_CREATE",
        entity_type="STAFF_LEGACY_MAPPING",
        entity_pk=replacement.id,
        after={
            "mapping_id": replacement.id,
            "staff_id": replacement.staff_id,
            "row_version": replacement.row_version,
            "replacement_of_mapping_id": mapping.id,
            "created_by_account_id": replacement.created_by_account_id,
            "created_at_utc": now.isoformat(),
            "updated_by_account_id": replacement.updated_by_account_id,
            "updated_at_utc": now.isoformat(),
        },
        occurred_at_utc=now,
    )
    database_session.flush()
    return {
        "mapping_id": mapping.id,
        "replacement_mapping_id": replacement.id,
        "row_version": mapping.row_version,
    }


def replace_mapping(
    mapping_id: int,
    replacement_staff_id: int,
    *,
    source_system_code: str | None = None,
    legacy_staff_key: str | None = None,
    database_session: Session | None = None,
    session: Session | None = None,
    session_factory: sessionmaker[Session] | None = None,
    actor_account_id: int | None = None,
    settings: Settings | None = None,
    expected_row_version: int,
) -> dict[str, object]:
    """Atomically invalidate and replace one active internal mapping."""

    del settings
    if actor_account_id is None or actor_account_id <= 0:
        raise ValueError("actor_account_id is required")
    if database_session is not None and session is not None:
        raise ValueError("provide one database session")
    database_session = database_session or session

    def execute(current_session: Session) -> object:
        return _replace_mapping_in_transaction(
            current_session,
            mapping_id=mapping_id,
            replacement_staff_id=replacement_staff_id,
            source_system_code=source_system_code,
            legacy_staff_key=legacy_staff_key,
            actor_account_id=actor_account_id,
            expected_row_version=expected_row_version,
        )

    if database_session is not None:
        return _run_atomic(database_session, execute)  # type: ignore[return-value]
    if session_factory is None:
        raise ValueError("database session or session factory is required")
    return _run_with_factory(session_factory, execute)  # type: ignore[return-value]


def apply(
    rows: Iterable[Mapping[str, object]],
    source_system_code: str,
    *,
    database_session: Session | None = None,
    session: Session | None = None,
    session_factory: sessionmaker[Session] | None = None,
    actor_account_id: int | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Apply an included batch atomically using the existing staff data path."""

    if actor_account_id is None or actor_account_id <= 0:
        raise ValueError("actor_account_id is required")
    if database_session is not None and session is not None:
        raise ValueError("provide one database session")
    database_session = database_session or session
    if database_session is None and session_factory is None:
        raise ValueError("database session or session factory is required")
    source_code = _text(source_system_code)
    if source_code is None:
        raise ValueError("source_system_code is required")

    def execute(current_session: Session) -> dict[str, object]:
        active_keys = set(
            current_session.scalars(
                select(StaffLegacyMapping.legacy_staff_key).where(
                    StaffLegacyMapping.source_system_code == source_code,
                    StaffLegacyMapping.invalidated_at_utc.is_(None),
                )
            )
        )
        active_rows, summary = _prepare_rows(
            rows,
            source_system_code=source_code,
            active_legacy_staff_keys=active_keys,
        )
        _apply_in_transaction(
            current_session,
            prepared=active_rows,
            source_system_code=source_code,
            actor_account_id=actor_account_id,
            settings=settings or get_settings(),
        )
        return summary

    if database_session is not None:
        return _run_atomic(database_session, execute)  # type: ignore[return-value]

    if session_factory is None:
        raise ValueError("database session or session factory is required")
    return _run_with_factory(session_factory, execute)  # type: ignore[return-value]
