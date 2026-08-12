"""Private synthetic-safe recipient legacy import operations.

The module is intentionally not mounted in HTTP or OpenAPI.  It accepts only
in-memory rows and writes recipients plus their internal mapping ledger in one
transaction.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.models import AuditEvent, Recipient, RecipientLegacyMapping
from app.domains.recipient.policies import clean_optional_text, clean_required_text

_ROW_FIELDS = frozenset(
    {
        "legacy_recipient_key",
        "legacy_attachment_key",
        "name",
        "birth_date",
        "sex_code",
        "postal_code",
        "address",
        "home_phone",
        "mobile_phone",
        "source_memo",
    }
)


class LegacyImportError(RuntimeError):
    def __init__(self, code: str = "UNEXPECTED_SERVER_ERROR") -> None:
        self.code = code
        super().__init__(code)


class _RejectedRow(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _PreparedRow:
    legacy_recipient_key: str | None
    legacy_attachment_key: str | None
    name: str
    birth_date: date
    sex_code: str
    postal_code: str | None
    address: str | None
    home_phone: str | None
    mobile_phone: str | None
    source_memo: str | None


def _summary(included_count: int, excluded_count: int, reasons: Counter[str]) -> dict[str, object]:
    return {
        "included_count": included_count,
        "excluded_count": excluded_count,
        "reason_counts": dict(sorted(reasons.items())),
    }


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return clean_optional_text(value)


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


def _active_key_set(values: Iterable[object]) -> set[str]:
    keys: set[str] = set()
    for value in values:
        if isinstance(value, tuple) and len(value) == 2:
            value = value[1]
        cleaned = _text(value)
        if cleaned is not None:
            keys.add(cleaned)
    return keys


def _prepare_one(row: Mapping[str, object]) -> _PreparedRow:
    if set(row) - _ROW_FIELDS:
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    name_value = row.get("name")
    try:
        name = clean_required_text(name_value if isinstance(name_value, str) else "")
    except ValueError:
        raise _RejectedRow("INVALID_REQUIRED_FIELD") from None
    birth_date = _date_value(row.get("birth_date"))
    sex_code = _text(row.get("sex_code"))
    recipient_key = _text(row.get("legacy_recipient_key"))
    attachment_key = _text(row.get("legacy_attachment_key"))
    if (
        birth_date is None
        or sex_code not in {"MALE", "FEMALE", "TEST"}
        or (recipient_key is None and attachment_key is None)
    ):
        raise _RejectedRow("INVALID_REQUIRED_FIELD")
    optional_values: dict[str, str | None] = {}
    for field_name in (
        "postal_code",
        "address",
        "home_phone",
        "mobile_phone",
        "source_memo",
    ):
        raw = row.get(field_name)
        if raw is not None and not isinstance(raw, str):
            raise _RejectedRow("INVALID_REQUIRED_FIELD")
        optional_values[field_name] = _text(raw)
    return _PreparedRow(
        legacy_recipient_key=recipient_key,
        legacy_attachment_key=attachment_key,
        name=name,
        birth_date=birth_date,
        sex_code=sex_code,
        postal_code=optional_values["postal_code"],
        address=optional_values["address"],
        home_phone=optional_values["home_phone"],
        mobile_phone=optional_values["mobile_phone"],
        source_memo=optional_values["source_memo"],
    )


def _prepare_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    source_system_code: str,
    active_legacy_recipient_keys: Iterable[object],
    active_legacy_attachment_keys: Iterable[object],
) -> tuple[list[_PreparedRow], dict[str, object]]:
    if _text(source_system_code) is None:
        raise ValueError("source_system_code is required")
    raw_rows = list(rows)
    recipient_keys = [
        _text(row.get("legacy_recipient_key")) if isinstance(row, Mapping) else None
        for row in raw_rows
    ]
    attachment_keys = [
        _text(row.get("legacy_attachment_key")) if isinstance(row, Mapping) else None
        for row in raw_rows
    ]
    recipient_counts = Counter(key for key in recipient_keys if key is not None)
    attachment_counts = Counter(key for key in attachment_keys if key is not None)
    active_recipient = _active_key_set(active_legacy_recipient_keys)
    active_attachment = _active_key_set(active_legacy_attachment_keys)
    prepared: list[_PreparedRow] = []
    reasons: Counter[str] = Counter()
    for row, recipient_key, attachment_key in zip(
        raw_rows,
        recipient_keys,
        attachment_keys,
        strict=True,
    ):
        if not isinstance(row, Mapping):
            reasons["INVALID_REQUIRED_FIELD"] += 1
            continue
        if recipient_key is not None and recipient_counts[recipient_key] > 1:
            reasons["DUPLICATE_SOURCE_KEY"] += 1
            continue
        if attachment_key is not None and attachment_counts[attachment_key] > 1:
            reasons["DUPLICATE_ATTACHMENT_KEY"] += 1
            continue
        if recipient_key is not None and recipient_key in active_recipient:
            reasons["ALREADY_MAPPED"] += 1
            continue
        if attachment_key is not None and attachment_key in active_attachment:
            reasons["ATTACHMENT_ALREADY_MAPPED"] += 1
            continue
        try:
            prepared.append(_prepare_one(row))
        except _RejectedRow as exc:
            reasons[exc.reason] += 1
    return prepared, _summary(len(prepared), len(raw_rows) - len(prepared), reasons)


def prepare(
    rows: Iterable[Mapping[str, object]],
    source_system_code: str,
    active_legacy_recipient_keys: Iterable[object],
    active_legacy_attachment_keys: Iterable[object],
) -> dict[str, object]:
    _prepared, summary = _prepare_rows(
        rows,
        source_system_code=source_system_code,
        active_legacy_recipient_keys=active_legacy_recipient_keys,
        active_legacy_attachment_keys=active_legacy_attachment_keys,
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


def _safe_rollback(database_session: Session) -> None:
    try:
        database_session.rollback()
    except Exception:
        pass


def _integrity_error_code(error: IntegrityError) -> str:
    original = getattr(error, "orig", None)
    diagnostics = getattr(original, "diag", None)
    constraint_name = getattr(diagnostics, "constraint_name", None)
    return {
        "uq_recipient_legacy_mapping_active_recipient_key": (
            "RECIPIENT_LEGACY_MAPPING_ALREADY_ACTIVE"
        ),
        "uq_recipient_legacy_mapping_active_attachment_key": (
            "RECIPIENT_LEGACY_ATTACHMENT_ALREADY_ACTIVE"
        ),
        "fk_recipient_legacy_mapping_recipient": "RECIPIENT_NOT_FOUND",
        "fk_recipient_legacy_mapping_replacement": ("RECIPIENT_LEGACY_MAPPING_REPLACEMENT_INVALID"),
    }.get(str(constraint_name), "UNEXPECTED_SERVER_ERROR")


def _run_atomic(
    database_session: Session,
    operation: Callable[[Session], object],
) -> object:
    try:
        with database_session.begin():
            return operation(database_session)
    except IntegrityError as exc:
        error_code = _integrity_error_code(exc)
    except LegacyImportError as exc:
        error_code = exc.code
    except SQLAlchemyError:
        error_code = "UNEXPECTED_SERVER_ERROR"
    except Exception:
        error_code = "UNEXPECTED_SERVER_ERROR"
    _safe_rollback(database_session)
    raise LegacyImportError(error_code) from None


def _run_with_factory(
    session_factory: sessionmaker[Session],
    operation: Callable[[Session], object],
) -> object:
    try:
        managed_session = session_factory()
    except Exception:
        raise LegacyImportError("UNEXPECTED_SERVER_ERROR") from None
    try:
        return _run_atomic(managed_session, operation)
    finally:
        try:
            managed_session.close()
        except Exception:
            pass


def _selected_session(
    database_session: Session | None,
    session: Session | None,
) -> Session | None:
    if database_session is not None and session is not None and database_session is not session:
        raise ValueError("provide one database session")
    return database_session or session


def _source_memo(source_system_code: str, source_memo: str | None) -> str:
    return (
        f"[{source_system_code}] {source_memo}"
        if source_memo is not None
        else f"[{source_system_code}]"
    )


def _apply_rows(
    database_session: Session,
    *,
    prepared: list[_PreparedRow],
    source_system_code: str,
    actor_account_id: int,
) -> None:
    for row in prepared:
        now = datetime.now(UTC)
        recipient = Recipient(
            name=row.name,
            birth_date=row.birth_date,
            sex_code=row.sex_code,
            recipient_no=None,
            memo=_source_memo(source_system_code, row.source_memo),
            postal_code=row.postal_code,
            address=row.address,
            home_phone=row.home_phone,
            mobile_phone=row.mobile_phone,
            created_by_account_id=actor_account_id,
            created_at_utc=now,
            updated_by_account_id=actor_account_id,
            updated_at_utc=now,
        )
        database_session.add(recipient)
        database_session.flush()
        _audit(
            database_session,
            actor_account_id=actor_account_id,
            action_code="RECIPIENT_CREATE",
            entity_type="RECIPIENT",
            entity_pk=recipient.id,
            after={"row_version": recipient.row_version},
            occurred_at_utc=now,
        )
        mapping = RecipientLegacyMapping(
            source_system_code=source_system_code,
            legacy_recipient_key=row.legacy_recipient_key,
            legacy_attachment_key=row.legacy_attachment_key,
            recipient_id=recipient.id,
            source_row_fingerprint=None,
            created_by_account_id=actor_account_id,
            created_at_utc=now,
            updated_by_account_id=actor_account_id,
            updated_at_utc=now,
        )
        database_session.add(mapping)
        database_session.flush()
        _audit(
            database_session,
            actor_account_id=actor_account_id,
            action_code="RECIPIENT_LEGACY_MAPPING_CREATE",
            entity_type="RECIPIENT_LEGACY_MAPPING",
            entity_pk=mapping.id,
            after={"recipient_id": recipient.id, "row_version": mapping.row_version},
            occurred_at_utc=now,
        )


def apply(
    rows: Iterable[Mapping[str, object]],
    source_system_code: str,
    *,
    active_legacy_recipient_keys: Iterable[object] = (),
    active_legacy_attachment_keys: Iterable[object] = (),
    database_session: Session | None = None,
    session: Session | None = None,
    session_factory: sessionmaker[Session] | None = None,
    actor_account_id: int | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    del settings
    if actor_account_id is None or actor_account_id <= 0:
        raise ValueError("actor_account_id is required")
    selected_session = _selected_session(database_session, session)
    if selected_session is None and session_factory is None:
        raise ValueError("database session or session factory is required")
    source_code = _text(source_system_code)
    if source_code is None:
        raise ValueError("source_system_code is required")

    def execute(current_session: Session) -> dict[str, object]:
        database_recipient_keys = set(
            current_session.scalars(
                select(RecipientLegacyMapping.legacy_recipient_key).where(
                    RecipientLegacyMapping.source_system_code == source_code,
                    RecipientLegacyMapping.legacy_recipient_key.is_not(None),
                    RecipientLegacyMapping.invalidated_at_utc.is_(None),
                )
            )
        )
        database_attachment_keys = set(
            current_session.scalars(
                select(RecipientLegacyMapping.legacy_attachment_key).where(
                    RecipientLegacyMapping.source_system_code == source_code,
                    RecipientLegacyMapping.legacy_attachment_key.is_not(None),
                    RecipientLegacyMapping.invalidated_at_utc.is_(None),
                )
            )
        )
        prepared_rows, summary = _prepare_rows(
            rows,
            source_system_code=source_code,
            active_legacy_recipient_keys=(
                set(active_legacy_recipient_keys) | database_recipient_keys
            ),
            active_legacy_attachment_keys=(
                set(active_legacy_attachment_keys) | database_attachment_keys
            ),
        )
        _apply_rows(
            current_session,
            prepared=prepared_rows,
            source_system_code=source_code,
            actor_account_id=actor_account_id,
        )
        return summary

    if selected_session is not None:
        return _run_atomic(selected_session, execute)  # type: ignore[return-value]
    assert session_factory is not None
    return _run_with_factory(session_factory, execute)  # type: ignore[return-value]


def _mapping_snapshot(mapping: RecipientLegacyMapping) -> dict[str, object]:
    return {
        "mapping_id": mapping.id,
        "recipient_id": mapping.recipient_id,
        "row_version": mapping.row_version,
        "invalidated_at_utc": (
            mapping.invalidated_at_utc.isoformat()
            if mapping.invalidated_at_utc is not None
            else None
        ),
        "replacement_mapping_id": mapping.replacement_recipient_legacy_mapping_id,
    }


def _lock_active_mapping(
    database_session: Session,
    mapping_id: int,
) -> RecipientLegacyMapping:
    mapping = database_session.scalar(
        select(RecipientLegacyMapping)
        .where(
            RecipientLegacyMapping.id == mapping_id,
            RecipientLegacyMapping.invalidated_at_utc.is_(None),
        )
        .with_for_update()
    )
    if mapping is None:
        historical = database_session.scalar(
            select(RecipientLegacyMapping.id).where(RecipientLegacyMapping.id == mapping_id)
        )
        if historical is not None:
            raise LegacyImportError("ROW_VERSION_CONFLICT")
        raise LegacyImportError("RECIPIENT_LEGACY_MAPPING_NOT_FOUND")
    return mapping


def _validate_mapping(
    mapping: RecipientLegacyMapping,
    *,
    source_system_code: str | None,
    legacy_recipient_key: str | None,
    expected_row_version: int,
) -> None:
    if expected_row_version <= 0 or mapping.row_version != expected_row_version:
        raise LegacyImportError("ROW_VERSION_CONFLICT")
    if source_system_code is not None and _text(source_system_code) != mapping.source_system_code:
        raise LegacyImportError("RECIPIENT_LEGACY_MAPPING_IDENTITY_MISMATCH")
    if (
        legacy_recipient_key is not None
        and _text(legacy_recipient_key) != mapping.legacy_recipient_key
    ):
        raise LegacyImportError("RECIPIENT_LEGACY_MAPPING_IDENTITY_MISMATCH")


def invalidate_mapping(
    mapping_id: int,
    *,
    source_system_code: str | None = None,
    legacy_recipient_key: str | None = None,
    database_session: Session | None = None,
    session: Session | None = None,
    session_factory: sessionmaker[Session] | None = None,
    actor_account_id: int | None = None,
    settings: Settings | None = None,
    expected_row_version: int,
) -> dict[str, object]:
    del settings
    if actor_account_id is None or actor_account_id <= 0:
        raise ValueError("actor_account_id is required")
    selected_session = _selected_session(database_session, session)

    def execute(current_session: Session) -> dict[str, object]:
        mapping = _lock_active_mapping(current_session, mapping_id)
        _validate_mapping(
            mapping,
            source_system_code=source_system_code,
            legacy_recipient_key=legacy_recipient_key,
            expected_row_version=expected_row_version,
        )
        before = _mapping_snapshot(mapping)
        now = datetime.now(UTC)
        mapping.invalidated_at_utc = now
        mapping.updated_by_account_id = actor_account_id
        mapping.updated_at_utc = now
        mapping.row_version += 1
        current_session.flush()
        _audit(
            current_session,
            actor_account_id=actor_account_id,
            action_code="RECIPIENT_LEGACY_MAPPING_INVALIDATE",
            entity_type="RECIPIENT_LEGACY_MAPPING",
            entity_pk=mapping.id,
            before=before,
            after=_mapping_snapshot(mapping),
            occurred_at_utc=now,
        )
        return {
            "mapping_id": mapping.id,
            "row_version": mapping.row_version,
            "invalidated_at_utc": now.isoformat(),
        }

    if selected_session is not None:
        return _run_atomic(selected_session, execute)  # type: ignore[return-value]
    if session_factory is None:
        raise ValueError("database session or session factory is required")
    return _run_with_factory(session_factory, execute)  # type: ignore[return-value]


def replace_mapping(
    mapping_id: int,
    replacement_recipient_id: int,
    *,
    source_system_code: str | None = None,
    legacy_recipient_key: str | None = None,
    database_session: Session | None = None,
    session: Session | None = None,
    session_factory: sessionmaker[Session] | None = None,
    actor_account_id: int | None = None,
    settings: Settings | None = None,
    expected_row_version: int,
) -> dict[str, object]:
    del settings
    if actor_account_id is None or actor_account_id <= 0:
        raise ValueError("actor_account_id is required")
    selected_session = _selected_session(database_session, session)

    def execute(current_session: Session) -> dict[str, object]:
        mapping = _lock_active_mapping(current_session, mapping_id)
        _validate_mapping(
            mapping,
            source_system_code=source_system_code,
            legacy_recipient_key=legacy_recipient_key,
            expected_row_version=expected_row_version,
        )
        replacement_recipient = current_session.scalar(
            select(Recipient).where(Recipient.id == replacement_recipient_id).with_for_update()
        )
        if replacement_recipient is None:
            raise LegacyImportError("RECIPIENT_NOT_FOUND")
        before = _mapping_snapshot(mapping)
        now = datetime.now(UTC)
        mapping.invalidated_at_utc = now
        mapping.updated_by_account_id = actor_account_id
        mapping.updated_at_utc = now
        mapping.row_version += 1
        current_session.flush()
        replacement = RecipientLegacyMapping(
            source_system_code=mapping.source_system_code,
            legacy_recipient_key=mapping.legacy_recipient_key,
            legacy_attachment_key=mapping.legacy_attachment_key,
            recipient_id=replacement_recipient.id,
            source_row_fingerprint=mapping.source_row_fingerprint,
            created_by_account_id=actor_account_id,
            created_at_utc=now,
            updated_by_account_id=actor_account_id,
            updated_at_utc=now,
            row_version=1,
        )
        current_session.add(replacement)
        current_session.flush()
        mapping.replacement_recipient_legacy_mapping_id = replacement.id
        current_session.flush()
        _audit(
            current_session,
            actor_account_id=actor_account_id,
            action_code="RECIPIENT_LEGACY_MAPPING_INVALIDATE",
            entity_type="RECIPIENT_LEGACY_MAPPING",
            entity_pk=mapping.id,
            before=before,
            after=_mapping_snapshot(mapping),
            occurred_at_utc=now,
        )
        _audit(
            current_session,
            actor_account_id=actor_account_id,
            action_code="RECIPIENT_LEGACY_MAPPING_REPLACEMENT_CREATE",
            entity_type="RECIPIENT_LEGACY_MAPPING",
            entity_pk=replacement.id,
            after={
                "recipient_id": replacement.recipient_id,
                "replacement_of_mapping_id": mapping.id,
                "row_version": replacement.row_version,
            },
            occurred_at_utc=now,
        )
        return {
            "mapping_id": mapping.id,
            "replacement_mapping_id": replacement.id,
            "row_version": mapping.row_version,
        }

    if selected_session is not None:
        return _run_atomic(selected_session, execute)  # type: ignore[return-value]
    if session_factory is None:
        raise ValueError("database session or session factory is required")
    return _run_with_factory(session_factory, execute)  # type: ignore[return-value]
