from __future__ import annotations

import importlib
import inspect
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NoReturn, cast
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0008_w1a_staff_legacy_mapping.py"
)
DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
APP_DATABASE_URL = os.environ.get("SSWCENTER_APP_DATABASE_URL")
BACKUP_DATABASE_URL = os.environ.get("SSWCENTER_BACKUP_DATABASE_URL")
REVISION = "20260728_0008_w1a_staff_legacy_mapping"
PARENT_REVISION = "20260728_0007_w1a_staff_quarterly_consultation"
TABLE_NAME = "staff_legacy_mapping"
MAPPING_REPLACEMENT_INTERFACE_NAMES = (
    "replace_mapping",
    "replace_legacy_mapping",
    "replace_staff_legacy_mapping",
    "replace_mapping_atomically",
    "invalidate_and_replace_mapping",
)


@dataclass(frozen=True)
class Fixture:
    staff_id: int
    account_id: int
    token: str


def _synthetic_resident_number(birth_date: str, serial: str) -> str:
    return "".join((birth_date, serial))


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _require_product() -> None:
    if not MIGRATION_PATH.is_file():
        _fail("W1A_VS6_MIGRATION_MISSING: 0008 staff legacy mapping migration is absent")


def _owner_engine() -> Engine:
    if not DATABASE_URL:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: SSWCENTER_DATABASE_URL is not configured")
    assert DATABASE_URL is not None
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: isolated PostgreSQL connection failed")


def _require_revision(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if revision != REVISION:
                _fail("W1A_VS6_POSTGRES_MIGRATION_MISSING: 0008 is not the applied revision")
            exists = connection.execute(
                text("SELECT to_regclass(:qualified) IS NOT NULL"),
                {"qualified": f"erp.{TABLE_NAME}"},
            ).scalar()
            if exists is not True:
                _fail("W1A_VS6_DB_SCHEMA_MISSING: mapping table is absent")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: revision/table query failed")


def _fixture(engine: Engine, label: str) -> Fixture:
    token = f"vs6-{label}-{uuid4().hex}"
    try:
        with engine.begin() as connection:
            staff_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.staff
                            (name, birth_date, sex_code, phone, phone_normalized,
                             address, display_name, memo)
                        VALUES (:name, DATE '1990-01-01', 'TEST', NULL, NULL,
                                :address, :display_name, :memo)
                        RETURNING id
                        """
                    ),
                    {
                        "name": f"VS6 synthetic {token}",
                        "address": f"VS6 synthetic address {token}",
                        "display_name": f"VS6 preserved display {token}",
                        "memo": f"VS6 preserved memo {token}",
                    },
                ).scalar_one()
            )
            account_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.user_account
                            (staff_id, account_code, display_name, role_code,
                             pin_hash, pin_lookup_hmac, pin_key_version)
                        VALUES (:staff_id, :account_code, :display_name, 'ADMIN',
                                'VS6 synthetic hash', :pin_lookup_hmac, 1)
                        RETURNING id
                        """
                    ),
                    {
                        "staff_id": staff_id,
                        "account_code": f"vs6-synthetic-{token}",
                        "display_name": f"VS6 synthetic actor {token}",
                        "pin_lookup_hmac": token.encode("ascii"),
                    },
                ).scalar_one()
            )
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: synthetic fixture setup failed")
    return Fixture(staff_id, account_id, token)


def _cleanup_fixture(
    engine: Engine,
    fixture: Fixture,
    *,
    additional_actor_account_ids: tuple[int, ...] = (),
) -> None:
    try:
        with engine.begin() as connection:
            actor_account_ids = (fixture.account_id,) + tuple(
                actor_id
                for actor_id in additional_actor_account_ids
                if actor_id != fixture.account_id
            )
            actor_placeholders = ", ".join(
                f":cleanup_actor_{index}" for index in range(len(actor_account_ids))
            )
            actor_parameters = {
                f"cleanup_actor_{index}": actor_id
                for index, actor_id in enumerate(actor_account_ids)
            }
            staff_ids = {
                fixture.staff_id,
                *(
                    int(row[0])
                    for row in connection.execute(
                        text(
                            f"SELECT DISTINCT staff_id FROM erp.{TABLE_NAME} "
                            "WHERE legacy_staff_key LIKE :prefix"
                        ),
                        {"prefix": f"VS6-SYNTHETIC-%{fixture.token}"},
                    )
                ),
                *(
                    int(row[0])
                    for row in connection.execute(
                        text("SELECT id FROM erp.staff WHERE name LIKE :token"),
                        {"token": f"%{fixture.token}%"},
                    )
                ),
            }
            for staff_id in staff_ids:
                connection.execute(
                    text(
                        f"UPDATE erp.{TABLE_NAME} "
                        "SET replacement_staff_legacy_mapping_id = NULL "
                        "WHERE staff_id = :staff_id"
                    ),
                    {"staff_id": staff_id},
                )
            connection.execute(
                text(
                    "DELETE FROM erp.audit_event "
                    f"WHERE actor_account_id IN ({actor_placeholders}) "
                    "AND created_from = 'LEGACY_IMPORT'"
                ),
                actor_parameters,
            )
            for staff_id in staff_ids:
                connection.execute(
                    text(f"DELETE FROM erp.{TABLE_NAME} WHERE staff_id = :staff_id"),
                    {"staff_id": staff_id},
                )
                connection.execute(
                    text("DELETE FROM erp.staff_license WHERE staff_id = :staff_id"),
                    {"staff_id": staff_id},
                )
                connection.execute(
                    text("DELETE FROM erp.staff_position_period WHERE staff_id = :staff_id"),
                    {"staff_id": staff_id},
                )
                connection.execute(
                    text("DELETE FROM erp.staff_employment WHERE staff_id = :staff_id"),
                    {"staff_id": staff_id},
                )
                connection.execute(
                    text("DELETE FROM erp.staff_sensitive_identity WHERE staff_id = :staff_id"),
                    {"staff_id": staff_id},
                )
            connection.execute(
                text(f"DELETE FROM erp.user_account WHERE id IN ({actor_placeholders})"),
                actor_parameters,
            )
            for staff_id in staff_ids:
                connection.execute(
                    text("DELETE FROM erp.staff WHERE id = :staff_id"),
                    {"staff_id": staff_id},
                )
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: synthetic fixture cleanup failed")


def _insert_mapping(
    connection: Connection,
    *,
    fixture: Fixture,
    key: str,
    staff_id: int | None = None,
) -> int:
    return int(
        connection.execute(
            text(
                f"""
                INSERT INTO erp.{TABLE_NAME}
                    (source_system_code, legacy_staff_key, staff_id,
                     source_row_fingerprint, invalidated_at_utc,
                     replacement_staff_legacy_mapping_id,
                     created_by_account_id, created_at_utc,
                     updated_by_account_id, updated_at_utc, row_version)
                VALUES (:source_system_code, :legacy_staff_key, :staff_id,
                        NULL, NULL, NULL, :account_id, timezone('utc', now()),
                        :account_id, timezone('utc', now()), 1)
                RETURNING id
                """
            ),
            {
                "source_system_code": "VS6_SYNTHETIC_SOURCE",
                "legacy_staff_key": key,
                "staff_id": fixture.staff_id if staff_id is None else staff_id,
                "account_id": fixture.account_id,
            },
        ).scalar_one()
    )


def _load_legacy_importer() -> tuple[Any, Any, Any]:
    try:
        importer = importlib.import_module("app.domains.staff.legacy_import")
        settings_module = importlib.import_module("app.core.settings")
        crypto = importlib.import_module("app.domains.staff.crypto")
        settings = settings_module.get_settings()
    except (ImportError, RuntimeError, ValueError):
        _fail("W1A_VS6_SERVICE_MISSING: internal legacy importer/crypto could not be loaded")
    return importer, settings, crypto


def _resolve_apply(importer: Any) -> Any:
    for name in ("apply", "apply_batch", "apply_import", "execute_import"):
        candidate = getattr(importer, name, None)
        if callable(candidate):
            return candidate
    for name in dir(importer):
        lowered = name.lower()
        if name.startswith("_") or not (
            "apply" in lowered or "execute" in lowered and "import" in lowered
        ):
            continue
        candidate = getattr(importer, name, None)
        if callable(candidate):
            return candidate
    _fail("W1A_VS6_APPLY_MISSING: equivalent internal apply interface is absent")


def _resolve_mapping_replacement(
    importer: Any,
    *,
    marker: str = "W1A_VS6_MAPPING_REPLACEMENT_MISSING",
) -> Any:
    for name in MAPPING_REPLACEMENT_INTERFACE_NAMES:
        candidate = getattr(importer, name, None)
        if callable(candidate):
            return candidate
    for name in dir(importer):
        lowered = name.lower()
        if name.startswith("_") or "mapping" not in lowered or "replace" not in lowered:
            continue
        candidate = getattr(importer, name, None)
        if callable(candidate):
            return candidate
    _fail(marker + ": internal mapping invalidation/replacement interface is absent")


def _require_expected_row_version(replace: Any, marker: str) -> str:
    try:
        parameters = inspect.signature(replace).parameters
    except (TypeError, ValueError):
        _fail(marker + ": replacement signature is unavailable")
    names = ("expected_row_version", "row_version", "expected_version")
    parameter_name = next((name for name in names if name in parameters), None)
    if parameter_name is None or parameters[parameter_name].default is not inspect.Parameter.empty:
        _fail(marker + ": expected_row_version must be a required parameter")
    return parameter_name


def _invoke_apply(
    apply: Any,
    rows: list[dict[str, object]],
    source_system_code: str,
    database_session: Session,
    actor_account_id: int,
    settings: Any,
) -> Any:
    parameters = inspect.signature(apply).parameters
    aliases = {
        "rows": ("rows", "batch", "records", "items", "input_rows"),
        "source_system_code": ("source_system_code", "source_code", "source"),
        "database_session": ("database_session", "session", "db_session"),
        "actor_account_id": ("actor_account_id", "actor_id", "account_id"),
        "settings": ("settings", "config"),
    }
    values: dict[str, object] = {
        "rows": rows,
        "source_system_code": source_system_code,
        "database_session": database_session,
        "actor_account_id": actor_account_id,
        "settings": settings,
    }
    kwargs: dict[str, object] = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    for semantic_name, value in values.items():
        parameter_name = next(
            (alias for alias in aliases[semantic_name] if alias in parameters), None
        )
        if parameter_name is None and accepts_kwargs:
            parameter_name = semantic_name
        if parameter_name is None:
            _fail(f"W1A_VS6_APPLY_MISSING: apply does not accept {semantic_name}")
        kwargs[parameter_name] = value
    return apply(**kwargs)


def _invoke_mapping_replacement(
    replace: Any,
    *,
    mapping_id: int,
    replacement_staff_id: int,
    source_system_code: str,
    legacy_staff_key: str,
    database_session: Session,
    actor_account_id: int,
    settings: Any,
    expected_row_version: int,
) -> Any:
    try:
        parameters = inspect.signature(replace).parameters
    except (TypeError, ValueError):
        _fail("W1A_VS6_MAPPING_REPLACEMENT_MISSING: replacement signature is unavailable")
    aliases = {
        "mapping_id": (
            "mapping_id",
            "old_mapping_id",
            "source_mapping_id",
            "legacy_mapping_id",
            "mapping_pk",
        ),
        "replacement_staff_id": (
            "replacement_staff_id",
            "new_staff_id",
            "target_staff_id",
        ),
        "source_system_code": ("source_system_code", "source_code", "source"),
        "legacy_staff_key": ("legacy_staff_key", "legacy_key", "source_key"),
        "database_session": ("database_session", "session", "db_session"),
        "actor_account_id": ("actor_account_id", "actor_id", "account_id"),
        "settings": ("settings", "config"),
        "expected_row_version": (
            "expected_row_version",
            "row_version",
            "expected_version",
        ),
        "reason": ("reason", "reason_code", "invalidation_reason", "correction_reason"),
    }
    _require_expected_row_version(replace, "W1A_VS6_MAPPING_EXPECTED_VERSION_REQUIRED")
    values: dict[str, object] = {
        "mapping_id": mapping_id,
        "replacement_staff_id": replacement_staff_id,
        "source_system_code": source_system_code,
        "legacy_staff_key": legacy_staff_key,
        "database_session": database_session,
        "actor_account_id": actor_account_id,
        "settings": settings,
        "expected_row_version": expected_row_version,
        "reason": "VS6-SYNTHETIC-MAPPING-CORRECTION",
    }
    kwargs: dict[str, object] = {}
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )
    for semantic_name, value in values.items():
        parameter_name = next(
            (alias for alias in aliases[semantic_name] if alias in parameters), None
        )
        if parameter_name is None and accepts_kwargs:
            parameter_name = semantic_name
        if parameter_name is not None:
            kwargs[parameter_name] = value
    missing_required = [
        name
        for name, parameter in parameters.items()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and parameter.default is inspect.Parameter.empty
        and name not in kwargs
    ]
    if missing_required:
        _fail(
            "W1A_VS6_MAPPING_REPLACEMENT_MISSING: replacement signature lacks semantic aliases: "
            + ",".join(sorted(missing_required))
        )
    return replace(**kwargs)


def _seed_identity(
    engine: Engine,
    *,
    fixture: Fixture,
    crypto: Any,
    settings: Any,
    resident_number: str,
) -> None:
    encrypted = crypto.encrypt_resident_number(
        staff_id=fixture.staff_id,
        resident_number=resident_number,
        settings=settings,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO erp.staff_sensitive_identity
                    (staff_id, resident_number_ciphertext, resident_number_nonce,
                     resident_number_key_version, resident_number_lookup_hmac)
                VALUES (:staff_id, :ciphertext, :nonce, :key_version, :lookup_hash)
                """
            ),
            {
                "staff_id": fixture.staff_id,
                "ciphertext": encrypted.ciphertext,
                "nonce": encrypted.nonce,
                "key_version": encrypted.key_version,
                "lookup_hash": encrypted.lookup_hmac,
            },
        )


def _seed_prior_employment(
    engine: Engine,
    *,
    fixture: Fixture,
    employment_no: int,
    staff_no_year: int,
    staff_no_sequence: int,
    start_date: date,
    end_date: date,
    position_code: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO erp.staff_employment
                    (staff_id, employment_no, staff_no, staff_no_year,
                     staff_no_sequence, start_date, end_date,
                     created_by_account_id, updated_by_account_id, row_version)
                VALUES (:staff_id, :employment_no, :staff_no, :staff_no_year,
                        :staff_no_sequence, :start_date, :end_date,
                        :account_id, :account_id, 1)
                RETURNING id
                """
            ),
            {
                "staff_id": fixture.staff_id,
                "employment_no": employment_no,
                "staff_no": f"{staff_no_year}-{staff_no_sequence:06d}",
                "staff_no_year": staff_no_year,
                "staff_no_sequence": staff_no_sequence,
                "start_date": start_date,
                "end_date": end_date,
                "account_id": fixture.account_id,
            },
        )
        employment_id = int(
            connection.execute(
                text(
                    "SELECT id FROM erp.staff_employment "
                    "WHERE staff_id = :staff_id AND employment_no = :employment_no"
                ),
                {"staff_id": fixture.staff_id, "employment_no": employment_no},
            ).scalar_one()
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.staff_position_period
                    (staff_id, employment_id, position_code, start_date, end_date,
                     created_by_account_id, updated_by_account_id, row_version)
                VALUES (:staff_id, :employment_id, :position_code,
                        :start_date, :end_date, :account_id, :account_id, 1)
                """
            ),
            {
                "staff_id": fixture.staff_id,
                "employment_id": employment_id,
                "position_code": position_code,
                "start_date": start_date,
                "end_date": end_date,
                "account_id": fixture.account_id,
            },
        )


def _canonical_license_rows(count: int, token: str) -> list[dict[str, object]]:
    rows = [
        {
            "type": "CARE_WORKER",
            "number": f"VS6-SYNTHETIC-CANONICAL-{token}-1",
            "issued_date": date(2026, 1, 15),
        },
        {
            "type": "SOCIAL_WORKER",
            "number": f"VS6-SYNTHETIC-CANONICAL-{token}-2",
            "issued_date": date(2026, 2, 15),
        },
    ]
    return rows[:count]


def _run_canonical_license_apply_case(count: int, marker: str) -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, f"canonical-license-{count}")
    importer, settings, _crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    resident_number = _synthetic_resident_number(f"90{count + 1:02d}01", "1234567")
    token = f"{count}-{fixture.token}"
    source_system_code = f"VS6_SYNTHETIC_CANONICAL_{count}"
    row = {
        "legacy_staff_key": f"VS6-SYNTHETIC-CANONICAL-APPLY-{token}",
        "name": f"VS6 canonical apply {token}",
        "resident_number": resident_number,
        "address": f"VS6 canonical address {token}",
        "phone": f"010-2000-0{count:03d}",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": date(2026, 12, 31),
        "position": "CARE_WORKER",
        "licenses": _canonical_license_rows(count, token),
    }
    marker_prefix = marker + ": "
    try:
        try:
            with Session(engine) as database_session:
                result = _invoke_apply(
                    apply,
                    [row],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        except Exception:
            _fail(marker_prefix + "canonical apply raised an unexpected error")
        if (
            not isinstance(result, dict)
            or result.get("included_count") != 1
            or result.get("excluded_count") != 0
            or result.get("reason_counts") != {}
        ):
            _fail(marker_prefix + "canonical apply summary was not a success")
        with engine.connect() as connection:
            mapping = connection.execute(
                text(
                    f"SELECT staff_id FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = :source_system_code "
                    "AND legacy_staff_key = :legacy_staff_key "
                    "AND invalidated_at_utc IS NULL"
                ),
                {
                    "source_system_code": source_system_code,
                    "legacy_staff_key": row["legacy_staff_key"],
                },
            ).all()
            if len(mapping) != 1:
                _fail(marker_prefix + "canonical mapping count was not exactly one")
            stored = connection.execute(
                text(
                    """
                    SELECT lt.code, sl.license_number, sl.issued_date
                    FROM erp.staff_license sl
                    JOIN erp.license_type lt ON lt.id = sl.license_type_id
                    WHERE sl.staff_id = :staff_id AND sl.invalidated_at_utc IS NULL
                    ORDER BY sl.id
                    """
                ),
                {"staff_id": int(mapping[0].staff_id)},
            ).all()
            expected = [
                (str(license_row["type"]), str(license_row["number"]), license_row["issued_date"])
                for license_row in _canonical_license_rows(count, token)
            ]
            actual = [
                (str(item.code), str(item.license_number), item.issued_date) for item in stored
            ]
            if len(stored) != count or actual != expected:
                _fail(
                    marker_prefix
                    + "stored license type/number/issued_date or exact row count was incorrect"
                )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail(marker_prefix + "PostgreSQL canonical license probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def _snapshot_staff_import_state(
    connection: Connection,
    *,
    fixture: Fixture,
    source_system_code: str,
    mapping_prefix: str,
    counter_years: tuple[int, ...],
) -> dict[str, tuple[tuple[object, ...], ...]]:
    parameters: dict[str, object] = {
        "fixture_id": fixture.staff_id,
        "actor_id": fixture.account_id,
        "staff_token": f"%{fixture.token}%",
        "source_system_code": source_system_code,
        "mapping_prefix": mapping_prefix,
    }
    staff_scope = (
        "id = :fixture_id OR name LIKE :staff_token OR address LIKE :staff_token "
        "OR display_name LIKE :staff_token OR memo LIKE :staff_token"
    )
    staff_subquery = f"SELECT id FROM erp.staff WHERE {staff_scope}"
    snapshot: dict[str, tuple[tuple[object, ...], ...]] = {}
    snapshot["staff"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, name, birth_date, sex_code, phone, phone_normalized, address, "
                "display_name, memo, created_at_utc, updated_at_utc, row_version "
                "FROM erp.staff WHERE " + staff_scope + " ORDER BY id"
            ),
            parameters,
        ).all()
    )
    snapshot["identity"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT staff_id, resident_number_ciphertext, resident_number_nonce, "
                "resident_number_key_version, resident_number_lookup_hmac, encrypted_at_utc, "
                "updated_at_utc, row_version FROM erp.staff_sensitive_identity "
                "WHERE staff_id IN (" + staff_subquery + ") ORDER BY staff_id"
            ),
            parameters,
        ).all()
    )
    snapshot["employment"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, staff_id, employment_no, staff_no, staff_no_year, "
                "staff_no_sequence, start_date, end_date, invalidated_at_utc, "
                "replacement_employment_id, created_by_account_id, created_at_utc, "
                "updated_by_account_id, updated_at_utc, row_version "
                "FROM erp.staff_employment WHERE staff_id IN ("
                + staff_subquery
                + ") ORDER BY staff_id, id"
            ),
            parameters,
        ).all()
    )
    snapshot["position"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, staff_id, employment_id, position_code, start_date, end_date, "
                "invalidated_at_utc, replacement_id, created_by_account_id, created_at_utc, "
                "updated_by_account_id, updated_at_utc, row_version "
                "FROM erp.staff_position_period WHERE staff_id IN ("
                + staff_subquery
                + ") ORDER BY staff_id, id"
            ),
            parameters,
        ).all()
    )
    snapshot["license"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT sl.id, sl.staff_id, lt.code, sl.license_number, sl.issued_date, "
                "sl.invalidated_at_utc, sl.replacement_license_id, sl.created_by_account_id, "
                "sl.created_at_utc, sl.updated_by_account_id, sl.updated_at_utc, sl.row_version "
                "FROM erp.staff_license sl JOIN erp.license_type lt "
                "ON lt.id = sl.license_type_id WHERE sl.staff_id IN ("
                + staff_subquery
                + ") ORDER BY sl.staff_id, sl.id"
            ),
            parameters,
        ).all()
    )
    snapshot["mapping"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, source_system_code, legacy_staff_key, staff_id, "
                "source_row_fingerprint, invalidated_at_utc, "
                "replacement_staff_legacy_mapping_id, created_by_account_id, created_at_utc, "
                f"updated_by_account_id, updated_at_utc, row_version FROM erp.{TABLE_NAME} "
                "WHERE source_system_code = :source_system_code "
                "AND legacy_staff_key LIKE :mapping_prefix ORDER BY id"
            ),
            parameters,
        ).all()
    )
    snapshot["audit"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, occurred_at_utc, actor_account_id, actor_kind, action_code, "
                "entity_type, entity_pk, before_json, after_json, reason_code, reason_text, "
                "created_from FROM erp.audit_event WHERE actor_account_id = :actor_id "
                "ORDER BY id"
            ),
            parameters,
        ).all()
    )
    year_parameters = {f"counter_year_{index}": year for index, year in enumerate(counter_years)}
    parameters.update(year_parameters)
    year_placeholders = ", ".join(f":counter_year_{index}" for index in range(len(counter_years)))
    snapshot["counter"] = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT number_type, number_year, last_sequence, updated_at_utc "
                "FROM erp.business_number_counter WHERE number_type = 'STAFF_EMPLOYMENT' "
                f"AND number_year IN ({year_placeholders}) ORDER BY number_year"
            ),
            parameters,
        ).all()
    )
    return snapshot


def _create_replacement_staff(engine: Engine, fixture: Fixture, label: str) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff
                        (name, birth_date, sex_code, phone, phone_normalized,
                         address, display_name, memo)
                    VALUES (:name, DATE '1991-01-01', 'TEST', NULL, NULL,
                            :address, :display_name, :memo)
                    RETURNING id
                    """
                ),
                {
                    "name": f"VS6 replacement {label} {fixture.token}",
                    "address": f"VS6 replacement address {label} {fixture.token}",
                    "display_name": f"VS6 replacement display {label} {fixture.token}",
                    "memo": f"VS6 replacement memo {label} {fixture.token}",
                },
            ).scalar_one()
        )


def _create_actor_for_staff(engine: Engine, fixture: Fixture, staff_id: int, label: str) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(
                text(
                    """
                    INSERT INTO erp.user_account
                        (staff_id, account_code, display_name, role_code,
                         pin_hash, pin_lookup_hmac, pin_key_version)
                    VALUES (:staff_id, :account_code, :display_name, 'ADMIN',
                            'VS6 replacement actor hash', :pin_lookup_hmac, 1)
                    RETURNING id
                    """
                ),
                {
                    "staff_id": staff_id,
                    "account_code": f"vs6-replacement-{label}-{fixture.token}",
                    "display_name": f"VS6 replacement actor {label} {fixture.token}",
                    "pin_lookup_hmac": f"{fixture.token}-{label}".encode("ascii"),
                },
            ).scalar_one()
        )


def _seed_mapping_with_apply(
    engine: Engine,
    *,
    fixture: Fixture,
    settings: Any,
    apply: Any,
    source_system_code: str,
    legacy_staff_key: str,
    marker: str,
) -> Any:
    row = {
        "legacy_staff_key": legacy_staff_key,
        "name": f"VS6 mapping seed {fixture.token}",
        "resident_number": _synthetic_resident_number("900501", "1234567"),
        "address": f"VS6 mapping seed address {fixture.token}",
        "phone": "010-2000-0121",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": date(2026, 12, 31),
        "position": "CARE_WORKER",
        "licenses": [],
    }
    try:
        with Session(engine) as database_session:
            result = _invoke_apply(
                apply,
                [row],
                source_system_code,
                database_session,
                fixture.account_id,
                settings,
            )
    except Exception:
        _fail(marker + ": mapping seed command failed")
    if not isinstance(result, dict) or result.get("included_count") != 1:
        _fail(marker + ": mapping seed was not applied")
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT id, source_system_code, legacy_staff_key, staff_id, "
                "source_row_fingerprint, invalidated_at_utc, "
                "replacement_staff_legacy_mapping_id, created_by_account_id, created_at_utc, "
                f"updated_by_account_id, updated_at_utc, row_version FROM erp.{TABLE_NAME} "
                "WHERE source_system_code = :source_system_code "
                "AND legacy_staff_key = :legacy_staff_key"
            ),
            {
                "source_system_code": source_system_code,
                "legacy_staff_key": legacy_staff_key,
            },
        ).one()


def _mapping_key_snapshot(
    connection: Connection,
    *,
    source_system_code: str,
    legacy_staff_key: str,
    actor_account_id: int,
) -> tuple[
    tuple[tuple[object, ...], ...],
    tuple[tuple[object, ...], ...],
]:
    mappings = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, source_system_code, legacy_staff_key, staff_id, "
                "source_row_fingerprint, invalidated_at_utc, "
                "replacement_staff_legacy_mapping_id, created_by_account_id, created_at_utc, "
                f"updated_by_account_id, updated_at_utc, row_version FROM erp.{TABLE_NAME} "
                "WHERE source_system_code = :source_system_code "
                "AND legacy_staff_key = :legacy_staff_key ORDER BY id"
            ),
            {
                "source_system_code": source_system_code,
                "legacy_staff_key": legacy_staff_key,
            },
        ).all()
    )
    audits = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT id, occurred_at_utc, actor_account_id, actor_kind, action_code, "
                "entity_type, entity_pk, before_json, after_json, reason_code, reason_text, "
                "created_from FROM erp.audit_event "
                "WHERE actor_account_id = :actor_account_id "
                "AND entity_type = 'STAFF_LEGACY_MAPPING' "
                "AND created_from = 'LEGACY_IMPORT' ORDER BY id"
            ),
            {"actor_account_id": actor_account_id},
        ).all()
    )
    return mappings, audits


def _promote_mapping_row_version(
    engine: Engine,
    *,
    mapping_id: int,
    marker: str,
) -> None:
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    f"UPDATE erp.{TABLE_NAME} SET row_version = 2 "
                    "WHERE id = :mapping_id AND row_version = 1"
                ),
                {"mapping_id": mapping_id},
            )
            if result.rowcount != 1:
                _fail(marker + ": fixture version promotion did not affect one row")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail(marker + ": fixture version promotion failed")


def test_vs6_00_postgres_revision_shape_and_active_guard() -> None:
    _require_product()
    engine = _owner_engine()
    try:
        _require_revision(engine)
        with engine.connect() as connection:
            columns = {
                (row.column_name, row.data_type, row.is_nullable)
                for row in connection.execute(
                    text(
                        """
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'erp' AND table_name = :table_name
                        """
                    ),
                    {"table_name": TABLE_NAME},
                )
            }
            required = {
                ("id", "bigint", "NO"),
                ("source_system_code", "text", "NO"),
                ("legacy_staff_key", "text", "NO"),
                ("staff_id", "bigint", "NO"),
                ("invalidated_at_utc", "timestamp with time zone", "YES"),
                ("row_version", "integer", "NO"),
            }
            if not required.issubset(columns):
                _fail("W1A_VS6_DB_SCHEMA_MISSING: PostgreSQL column shape is incomplete")
            index_definition = connection.execute(
                text(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = 'erp'
                      AND tablename = :table_name
                      AND indexdef ILIKE '%UNIQUE%'
                      AND indexdef ILIKE '%source_system_code%'
                      AND indexdef ILIKE '%legacy_staff_key%'
                      AND indexdef ILIKE '%invalidated_at_utc IS NULL%'
                    """
                ),
                {"table_name": TABLE_NAME},
            ).scalar_one_or_none()
            if index_definition is None or "UNIQUE" not in index_definition.upper():
                _fail("W1A_VS6_ACTIVE_UNIQUE_MISSING: PostgreSQL active unique index is absent")
            if "INVALIDATED_AT_UTC IS NULL" not in index_definition.upper():
                _fail("W1A_VS6_ACTIVE_UNIQUE_MISSING: active unique predicate is absent")
            fk_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.table_constraints
                    WHERE table_schema = 'erp'
                      AND table_name = :table_name
                      AND constraint_type = 'FOREIGN KEY'
                    """
                ),
                {"table_name": TABLE_NAME},
            ).scalar_one()
            if int(fk_count) < 2:
                _fail("W1A_VS6_FK_MISSING: staff/replacement foreign keys are incomplete")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: PostgreSQL shape probe failed")
    finally:
        engine.dispose()


def test_vs6_01_postgres_runtime_and_backup_acl_are_least_privilege() -> None:
    _require_product()
    if not APP_DATABASE_URL or not BACKUP_DATABASE_URL:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: app/backup role URLs are not configured")
    for role_url, expected in (
        (APP_DATABASE_URL, (True, False, True, True, True, False, False, True)),
        (BACKUP_DATABASE_URL, (True, False, True, False, False, False, False, False)),
    ):
        assert role_url is not None
        engine = create_engine(role_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                values = tuple(
                    connection.execute(
                        text(
                            """
                            SELECT
                                has_schema_privilege(current_user, 'erp', 'USAGE'),
                                has_schema_privilege(current_user, 'erp', 'CREATE'),
                                has_table_privilege(current_user, :table_name, 'SELECT'),
                                has_table_privilege(current_user, :table_name, 'INSERT'),
                                has_table_privilege(current_user, :table_name, 'UPDATE'),
                                has_table_privilege(current_user, :table_name, 'DELETE'),
                                has_table_privilege(current_user, :table_name, 'TRUNCATE'),
                                has_sequence_privilege(current_user, :sequence_name, 'USAGE')
                            """
                        ),
                        {
                            "table_name": f"erp.{TABLE_NAME}",
                            "sequence_name": f"erp.{TABLE_NAME}_id_seq",
                        },
                    ).one()
                )
                normalized = tuple(bool(value) for value in values)
                if normalized != expected:
                    _fail("W1A_VS6_ACL_MISSING: runtime role privileges are not least-privilege")
        except pytest.fail.Exception:
            raise
        except SQLAlchemyError:
            _fail("W1A_VS6_PG_HARNESS_FAILURE: role ACL probe failed")
        finally:
            engine.dispose()


def test_vs6_02_postgres_fk_partial_unique_invalidation_and_race() -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "race")
    key = f"VS6-SYNTHETIC-RACE-{fixture.token}"
    barrier = threading.Barrier(2)

    def insert_in_race() -> str:
        connection = engine.connect()
        transaction = connection.begin()
        try:
            barrier.wait(timeout=10)
            _insert_mapping(connection, fixture=fixture, key=key)
            transaction.commit()
            return "committed"
        except IntegrityError:
            transaction.rollback()
            return "conflict"
        except (SQLAlchemyError, threading.BrokenBarrierError):
            transaction.rollback()
            return "harness_error"
        finally:
            connection.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: insert_in_race(), (1, 2)))
        if sorted(results) != ["committed", "conflict"]:
            _fail("W1A_VS6_PG_HARNESS_FAILURE: partial unique race did not complete")
        with engine.begin() as connection:
            active_count = connection.execute(
                text(
                    f"SELECT count(*) FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = 'VS6_SYNTHETIC_SOURCE' "
                    "AND legacy_staff_key = :key AND invalidated_at_utc IS NULL"
                ),
                {"key": key},
            ).scalar_one()
            if int(active_count) != 1:
                _fail("W1A_VS6_ACTIVE_UNIQUE_MISSING: race left more than one active mapping")
            original_id = connection.execute(
                text(
                    f"SELECT id FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = 'VS6_SYNTHETIC_SOURCE' "
                    "AND legacy_staff_key = :key AND invalidated_at_utc IS NULL"
                ),
                {"key": key},
            ).scalar_one()
            connection.execute(
                text(
                    f"UPDATE erp.{TABLE_NAME} SET invalidated_at_utc = timezone('utc', now()), "
                    "updated_at_utc = timezone('utc', now()), row_version = row_version + 1 "
                    "WHERE id = :mapping_id"
                ),
                {"mapping_id": original_id},
            )
            replacement_id = _insert_mapping(
                connection,
                fixture=fixture,
                key=key,
            )
            connection.execute(
                text(
                    f"UPDATE erp.{TABLE_NAME} "
                    "SET replacement_staff_legacy_mapping_id = :replacement_id "
                    "WHERE id = :mapping_id"
                ),
                {"mapping_id": original_id, "replacement_id": replacement_id},
            )
            invalidated, replacement = connection.execute(
                text(
                    f"SELECT invalidated_at_utc IS NOT NULL, "
                    "replacement_staff_legacy_mapping_id "
                    f"FROM erp.{TABLE_NAME} WHERE id = :mapping_id"
                ),
                {"mapping_id": original_id},
            ).one()
            if not invalidated or int(replacement) != int(replacement_id):
                _fail("W1A_VS6_REPLACEMENT_PATH_MISSING: invalidation replacement was not linked")
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    _insert_mapping(
                        connection,
                        fixture=fixture,
                        key=f"VS6-SYNTHETIC-FK-{fixture.token}",
                        staff_id=-1,
                    )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: FK/unique/invalidation probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_03_postgres_atomic_rollback_hash_shape_and_three_general_licenses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rollback")
    source_system_code = "VS6_SYNTHETIC_APPLY"
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    existing_resident_number = _synthetic_resident_number("900101", "1234567")
    new_resident_number = _synthetic_resident_number("900102", "1234567")
    valid_existing = {
        "legacy_staff_key": f"VS6-SYNTHETIC-APPLY-EXISTING-{fixture.token}",
        "name": f"VS6 applied existing {fixture.token}",
        "resident_number": existing_resident_number,
        "address": f"VS6 applied address {fixture.token}",
        "phone": "010-2000-0001",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": None,
        "position": "CARE_WORKER",
        "licenses": [],
    }
    valid_new = {
        "legacy_staff_key": f"VS6-SYNTHETIC-APPLY-NEW-{fixture.token}",
        "name": f"VS6 applied new {fixture.token}",
        "resident_number": new_resident_number,
        "address": f"VS6 applied new address {fixture.token}",
        "phone": "010-2000-0002",
        "employment_start_date": date(2026, 1, 1),
        "employment_end_date": None,
        "position": "CARE_WORKER",
        "licenses": [],
    }
    try:
        with engine.connect() as connection:
            before_values = connection.execute(
                text(
                    "SELECT name, address, display_name, memo FROM erp.staff WHERE id = :staff_id"
                ),
                {"staff_id": fixture.staff_id},
            ).one()
            encrypted = crypto.encrypt_resident_number(
                staff_id=fixture.staff_id,
                resident_number=existing_resident_number,
                settings=settings,
            )
            connection.commit()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO erp.staff_sensitive_identity "
                    "(staff_id, resident_number_ciphertext, resident_number_nonce, "
                    "resident_number_key_version, resident_number_lookup_hmac) "
                    "VALUES (:staff_id, :ciphertext, :nonce, :key_version, :lookup_hash)"
                ),
                {
                    "staff_id": fixture.staff_id,
                    "ciphertext": encrypted.ciphertext,
                    "nonce": encrypted.nonce,
                    "key_version": encrypted.key_version,
                    "lookup_hash": encrypted.lookup_hmac,
                },
            )
        with Session(engine) as database_session:
            result = _invoke_apply(
                apply,
                [valid_existing, valid_new],
                source_system_code,
                database_session,
                fixture.account_id,
                settings,
            )
        if (
            not isinstance(result, dict)
            or result.get("included_count") != 2
            or result.get("excluded_count") != 0
            or not isinstance(result.get("reason_counts"), dict)
        ):
            _fail("W1A_VS6_APPLY_SUMMARY_MISSING: successful apply summary is incorrect")
        with Session(engine) as database_session:
            rerun_result = _invoke_apply(
                apply,
                [valid_existing],
                source_system_code,
                database_session,
                fixture.account_id,
                settings,
            )
        rerun_reasons = (
            rerun_result.get("reason_counts") if isinstance(rerun_result, dict) else None
        )
        if (
            not isinstance(rerun_result, dict)
            or rerun_result.get("included_count") != 0
            or rerun_result.get("excluded_count") != 1
            or not isinstance(rerun_reasons, dict)
            or rerun_reasons.get("ALREADY_MAPPED") != 1
        ):
            _fail("W1A_VS6_RERUN_GUARD_MISSING: apply rerun was not ALREADY_MAPPED")
        with engine.connect() as connection:
            after_values = connection.execute(
                text(
                    "SELECT name, address, display_name, memo FROM erp.staff WHERE id = :staff_id"
                ),
                {"staff_id": fixture.staff_id},
            ).one()
            if tuple(after_values[2:]) != tuple(before_values[2:]):
                _fail("W1A_VS6_DISPLAY_MEMO_PRESERVE_MISSING: display_name/memo changed")
            mappings = connection.execute(
                text(
                    f"SELECT legacy_staff_key, staff_id FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = :source_system_code "
                    "AND legacy_staff_key LIKE :prefix ORDER BY legacy_staff_key"
                ),
                {
                    "source_system_code": source_system_code,
                    "prefix": f"VS6-SYNTHETIC-APPLY-%{fixture.token}",
                },
            ).all()
            if len(mappings) != 2 or int(mappings[0].staff_id) != fixture.staff_id:
                _fail("W1A_VS6_MAPPING_APPLY_MISSING: successful mapping rows are incomplete")
            new_staff_id = int(mappings[1].staff_id)
            audit_count = connection.execute(
                text(
                    "SELECT count(*) FROM erp.audit_event "
                    "WHERE actor_account_id = :account_id "
                    "AND action_code = 'STAFF_LEGACY_MAPPING_CREATE' "
                    "AND created_from = 'LEGACY_IMPORT'"
                ),
                {"account_id": fixture.account_id},
            ).scalar_one()
            if int(audit_count) != 2:
                _fail("W1A_VS6_AUDIT_PATH_MISSING: successful mapping audit rows are incomplete")
            identity = connection.execute(
                text(
                    "SELECT resident_number_ciphertext, resident_number_nonce, "
                    "resident_number_key_version, octet_length(resident_number_lookup_hmac) "
                    "FROM erp.staff_sensitive_identity WHERE staff_id = :staff_id"
                ),
                {"staff_id": new_staff_id},
            ).one()
            if (
                int(identity[3]) != 32
                or len(bytes(identity[0])) == 0
                or len(bytes(identity[1])) != 12
                or new_resident_number.encode("ascii") in bytes(identity[0])
            ):
                _fail("W1A_VS6_CRYPTO_SHAPE_MISSING: encrypted identity shape is invalid")
            decrypted = crypto.decrypt_resident_number(
                staff_id=new_staff_id,
                ciphertext=bytes(identity[0]),
                nonce=bytes(identity[1]),
                key_version=int(identity[2]),
                settings=settings,
            )
            if decrypted != new_resident_number:
                _fail("W1A_VS6_CRYPTO_PATH_MISSING: imported resident number did not decrypt")
        bad_valid = dict(valid_new)
        bad_valid["legacy_staff_key"] = f"VS6-SYNTHETIC-ROLLBACK-VALID-{fixture.token}"
        bad_valid["name"] = f"VS6 rollback valid {fixture.token}"
        bad_valid["resident_number"] = _synthetic_resident_number("900103", "1234567")
        bad_invalid = dict(valid_new)
        bad_invalid["legacy_staff_key"] = f"VS6-SYNTHETIC-ROLLBACK-BAD-{fixture.token}"
        bad_invalid["name"] = f"VS6 rollback bad {fixture.token}"
        bad_invalid["resident_number"] = _synthetic_resident_number("900104", "1234567")
        bad_invalid["licenses"] = [
            {
                "type": "VS6_UNKNOWN_LICENSE",
                "number": f"VS6-SYNTHETIC-BAD-LICENSE-{fixture.token}",
                "issued_date": date(2026, 1, 1),
            }
        ]
        try:
            audit_calls = 0

            def fail_after_first_audit(*args: object, **kwargs: object) -> None:
                nonlocal audit_calls
                audit_calls += 1
                if audit_calls >= 2:
                    raise SQLAlchemyError("VS6 synthetic atomic audit failure")

            with monkeypatch.context() as patch:
                patch.setattr(importer, "_audit", fail_after_first_audit)
                with pytest.raises(error_type):
                    with Session(engine) as database_session:
                        _invoke_apply(
                            apply,
                            [bad_valid, bad_invalid],
                            source_system_code,
                            database_session,
                            fixture.account_id,
                            settings,
                        )
        except pytest.fail.Exception:
            _fail("W1A_VS6_ATOMIC_APPLY_MISSING: failed apply batch did not rollback")
        with engine.connect() as connection:
            rollback_mapping_count = connection.execute(
                text(
                    f"SELECT count(*) FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = :source_system_code "
                    "AND legacy_staff_key LIKE :prefix"
                ),
                {
                    "source_system_code": source_system_code,
                    "prefix": f"VS6-SYNTHETIC-ROLLBACK-%{fixture.token}",
                },
            ).scalar_one()
            rollback_staff_count = connection.execute(
                text("SELECT count(*) FROM erp.staff WHERE name LIKE :prefix"),
                {"prefix": f"VS6 rollback %{fixture.token}"},
            ).scalar_one()
            if int(rollback_mapping_count) != 0 or int(rollback_staff_count) != 0:
                _fail("W1A_VS6_ATOMIC_APPLY_MISSING: failed batch left persisted rows")

        with engine.begin() as connection:
            license_type_id = connection.execute(
                text("SELECT id FROM erp.license_type ORDER BY id LIMIT 1")
            ).scalar_one_or_none()
            if license_type_id is None:
                _fail("W1A_VS6_PG_HARNESS_FAILURE: license type seed is absent")
            for number in range(3):
                connection.execute(
                    text(
                        "INSERT INTO erp.staff_license "
                        "(staff_id, license_type_id, license_number, issued_date, "
                        "created_by_account_id, updated_by_account_id, row_version) "
                        "VALUES (:staff_id, :license_type_id, :license_number, "
                        "DATE '2026-01-01', :account_id, :account_id, 1)"
                    ),
                    {
                        "staff_id": fixture.staff_id,
                        "license_type_id": license_type_id,
                        "license_number": f"VS6-SYNTHETIC-LICENSE-{fixture.token}-{number}",
                        "account_id": fixture.account_id,
                    },
                )
            license_count = connection.execute(
                text(
                    "SELECT count(*) FROM erp.staff_license WHERE staff_id = :staff_id "
                    "AND license_number LIKE :prefix"
                ),
                {
                    "staff_id": fixture.staff_id,
                    "prefix": f"VS6-SYNTHETIC-LICENSE-{fixture.token}-%",
                },
            ).scalar_one()
            if int(license_count) != 3:
                _fail("W1A_VS6_GENERAL_LICENSE_CONTRACT_MISSING: three licenses were not stored")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: rollback/crypto/license probe failed")
    except (AttributeError, TypeError, ValueError, RuntimeError):
        _fail("W1A_VS6_APPLY_PATH_MISSING: internal apply runtime contract failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_03a_postgres_apply_accepts_zero_canonical_licenses() -> None:
    _run_canonical_license_apply_case(
        0,
        "W1A_VS6_LICENSE_CANONICAL_APPLY_ZERO_MISSING",
    )


def test_vs6_03b_postgres_apply_accepts_one_canonical_license() -> None:
    _run_canonical_license_apply_case(
        1,
        "W1A_VS6_LICENSE_CANONICAL_APPLY_ONE_MISSING",
    )


def test_vs6_03c_postgres_apply_accepts_two_canonical_licenses() -> None:
    _run_canonical_license_apply_case(
        2,
        "W1A_VS6_LICENSE_CANONICAL_APPLY_TWO_MISSING",
    )


def test_vs6_04a_postgres_rehire_exact_period_reuses_employment_and_counter() -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rehire-exact")
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    source_system_code = "VS6_SYNTHETIC_REHIRE_EXACT"
    resident_number = _synthetic_resident_number("900101", "1234567")
    staff_number = 950000
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.business_number_counter
                        (number_type, number_year, last_sequence)
                    VALUES ('STAFF_EMPLOYMENT', 2026, :last_sequence)
                    ON CONFLICT (number_type, number_year) DO UPDATE
                    SET last_sequence = EXCLUDED.last_sequence,
                        updated_at_utc = timezone('utc', now())
                    """
                ),
                {"last_sequence": staff_number},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_employment
                        (staff_id, employment_no, staff_no, staff_no_year,
                         staff_no_sequence, start_date, end_date,
                         created_by_account_id, updated_by_account_id, row_version)
                    VALUES (:staff_id, 7, :staff_no, 2026, :staff_no_sequence,
                            DATE '2026-01-01', DATE '2026-12-31',
                            :account_id, :account_id, 1)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "staff_no": f"2026-{staff_number:03d}",
                    "staff_no_sequence": staff_number,
                    "account_id": fixture.account_id,
                },
            )
            employment_id = int(
                connection.execute(
                    text(
                        "SELECT id FROM erp.staff_employment "
                        "WHERE staff_id = :staff_id AND employment_no = 7"
                    ),
                    {"staff_id": fixture.staff_id},
                ).scalar_one()
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_position_period
                        (staff_id, employment_id, position_code, start_date, end_date,
                         created_by_account_id, updated_by_account_id, row_version)
                    VALUES (:staff_id, :employment_id, 'CARE_WORKER',
                            DATE '2026-01-01', DATE '2026-12-31',
                            :account_id, :account_id, 1)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "employment_id": employment_id,
                    "account_id": fixture.account_id,
                },
            )
        _seed_identity(
            engine,
            fixture=fixture,
            crypto=crypto,
            settings=settings,
            resident_number=resident_number,
        )
        with engine.connect() as connection:
            before = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-EXACT-%",
                counter_years=(2026,),
            )
        row = {
            "legacy_staff_key": f"VS6-SYNTHETIC-REHIRE-EXACT-{fixture.token}",
            "name": f"VS6 exact rehire {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 exact rehire address {fixture.token}",
            "phone": "010-2000-0061",
            "employment_start_date": date(2026, 1, 1),
            "employment_end_date": date(2026, 12, 31),
            "position": "CARE_WORKER",
            "licenses": [],
        }
        with Session(engine) as database_session:
            result = _invoke_apply(
                apply,
                [row],
                source_system_code,
                database_session,
                fixture.account_id,
                settings,
            )
        if not isinstance(result, dict) or result.get("included_count") != 1:
            _fail("W1A_VS6_REHIRE_EXACT_REUSE_MISSING: exact-period apply did not succeed")
        with engine.connect() as connection:
            after = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-EXACT-%",
                counter_years=(2026,),
            )
        if before["employment"] != after["employment"]:
            _fail("W1A_VS6_REHIRE_EXACT_EMPLOYMENT_MUTATED")
        if before["position"] != after["position"]:
            _fail("W1A_VS6_REHIRE_EXACT_POSITION_MUTATED")
        if before["counter"] != after["counter"]:
            _fail("W1A_VS6_REHIRE_EXACT_COUNTER_MUTATED")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_REHIRE_EXACT_REUSE_MISSING: exact-period probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_04_postgres_rehire_uses_exact_period_new_number_position_and_counter_rollback() -> (
    None
):
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rehire")
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_REHIRE"
    resident_number = _synthetic_resident_number("900106", "1234567")
    counter_year = 2026
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.business_number_counter
                        (number_type, number_year, last_sequence)
                    VALUES ('STAFF_EMPLOYMENT', :number_year, 900000)
                    ON CONFLICT (number_type, number_year) DO UPDATE
                    SET last_sequence = GREATEST(
                        erp.business_number_counter.last_sequence, EXCLUDED.last_sequence
                    )
                    """
                ),
                {"number_year": counter_year},
            )
            counter_before = int(
                connection.execute(
                    text(
                        "SELECT last_sequence FROM erp.business_number_counter "
                        "WHERE number_type = 'STAFF_EMPLOYMENT' AND number_year = :number_year"
                    ),
                    {"number_year": counter_year},
                ).scalar_one()
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_employment
                        (staff_id, employment_no, staff_no, staff_no_year,
                         staff_no_sequence, start_date, end_date,
                         created_by_account_id, updated_by_account_id, row_version)
                    VALUES (:staff_id, 1, :staff_no, 2024, 900000,
                            DATE '2024-01-01', DATE '2024-12-31',
                            :account_id, :account_id, 1)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "staff_no": f"VS6-SYNTHETIC-OLD-EMPLOYMENT-{fixture.token}",
                    "account_id": fixture.account_id,
                },
            )
        encrypted = crypto.encrypt_resident_number(
            staff_id=fixture.staff_id,
            resident_number=resident_number,
            settings=settings,
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_sensitive_identity
                        (staff_id, resident_number_ciphertext, resident_number_nonce,
                         resident_number_key_version, resident_number_lookup_hmac)
                    VALUES (:staff_id, :ciphertext, :nonce, :key_version, :lookup_hash)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "ciphertext": encrypted.ciphertext,
                    "nonce": encrypted.nonce,
                    "key_version": encrypted.key_version,
                    "lookup_hash": encrypted.lookup_hmac,
                },
            )
        rehire_row = {
            "legacy_staff_key": f"VS6-SYNTHETIC-REHIRE-{fixture.token}",
            "name": f"VS6 rehire {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 rehire address {fixture.token}",
            "phone": "010-2000-0106",
            "employment_start_date": date(2026, 1, 1),
            "employment_end_date": date(2026, 12, 31),
            "position": "SOCIAL_WORKER",
            "licenses": [],
        }
        try:
            with Session(engine) as database_session:
                result = _invoke_apply(
                    apply,
                    [rehire_row],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        except error_type:
            _fail(
                "W1A_VS6_REHIRE_EMPLOYMENT_MISSING: "
                "exact nonmatching period did not create a new employment"
            )
        except Exception:
            _fail("W1A_VS6_REHIRE_EMPLOYMENT_MISSING: rehire apply escaped its contract")
        if (
            not isinstance(result, dict)
            or result.get("included_count") != 1
            or result.get("excluded_count") != 0
        ):
            _fail("W1A_VS6_REHIRE_EMPLOYMENT_MISSING: rehire apply summary is incorrect")

        with engine.connect() as connection:
            employments = connection.execute(
                text(
                    """
                    SELECT id, staff_id, employment_no, staff_no, staff_no_year,
                           staff_no_sequence,
                           start_date, end_date
                    FROM erp.staff_employment
                    WHERE staff_id = :staff_id AND invalidated_at_utc IS NULL
                    ORDER BY start_date, id
                    """
                ),
                {"staff_id": fixture.staff_id},
            ).all()
            if len(employments) != 2:
                _fail(
                    "W1A_VS6_REHIRE_EMPLOYMENT_MISSING: existing staff did not receive a "
                    "separate employment"
                )
            old_employment, new_employment = employments
            if (
                int(old_employment.id) == int(new_employment.id)
                or int(new_employment.staff_id) != fixture.staff_id
                or int(new_employment.employment_no) != 2
                or int(new_employment.staff_no_year) != 2026
                or new_employment.start_date.isoformat() != "2026-01-01"
                or new_employment.end_date.isoformat() != "2026-12-31"
                or int(new_employment.staff_no_sequence) <= int(old_employment.staff_no_sequence)
            ):
                _fail("W1A_VS6_REHIRE_EMPLOYMENT_MISSING: new employment identity/period is wrong")
            position = connection.execute(
                text(
                    """
                    SELECT position_code, start_date, end_date
                    FROM erp.staff_position_period
                    WHERE staff_id = :staff_id AND employment_id = :employment_id
                      AND invalidated_at_utc IS NULL
                    """
                ),
                {"staff_id": fixture.staff_id, "employment_id": new_employment.id},
            ).one_or_none()
            if (
                position is None
                or position.position_code != "SOCIAL_WORKER"
                or position.start_date.isoformat() != "2026-01-01"
                or position.end_date.isoformat() != "2026-12-31"
            ):
                _fail("W1A_VS6_REHIRE_POSITION_MISSING: position is not attached to new employment")
            counter_after = int(
                connection.execute(
                    text(
                        "SELECT last_sequence FROM erp.business_number_counter "
                        "WHERE number_type = 'STAFF_EMPLOYMENT' AND number_year = :number_year"
                    ),
                    {"number_year": counter_year},
                ).scalar_one()
            )
            if (
                counter_after != counter_before + 1
                or int(new_employment.staff_no_sequence) != counter_after
                or str(new_employment.staff_no) != f"2026-{counter_after:03d}"
            ):
                _fail("W1A_VS6_REHIRE_COUNTER_MISSING: new employment did not consume one counter")

        rollback_valid = dict(rehire_row)
        rollback_valid["legacy_staff_key"] = f"VS6-SYNTHETIC-REHIRE-ROLLBACK-VALID-{fixture.token}"
        rollback_valid["employment_start_date"] = date(2027, 1, 1)
        rollback_valid["employment_end_date"] = date(2027, 12, 31)
        rollback_valid["position"] = "NURSE"
        rollback_invalid = dict(rehire_row)
        rollback_invalid["legacy_staff_key"] = (
            f"VS6-SYNTHETIC-REHIRE-ROLLBACK-INVALID-{fixture.token}"
        )
        rollback_invalid["name"] = f"VS6 rehire rollback invalid {fixture.token}"
        rollback_invalid["resident_number"] = _synthetic_resident_number("900107", "1234567")
        rollback_invalid["licenses"] = [
            {
                "type": "VS6_UNKNOWN_LICENSE",
                "number": f"VS6-SYNTHETIC-ROLLBACK-LICENSE-{fixture.token}",
                "issued_date": date(2027, 1, 1),
            }
        ]
        with engine.connect() as connection:
            rollback_before = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-ROLLBACK-%",
                counter_years=(2026, 2027),
            )
        with pytest.raises(error_type):
            with Session(engine) as database_session:
                _invoke_apply(
                    apply,
                    [rollback_valid, rollback_invalid],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        with engine.connect() as connection:
            rollback_after = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-ROLLBACK-%",
                counter_years=(2026, 2027),
            )
        if rollback_before != rollback_after:
            _fail("W1A_VS6_REHIRE_ROLLBACK_MISSING: rehire failure did not rollback exactly")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: rehire/counter probe failed")
    except (AttributeError, TypeError, ValueError, RuntimeError):
        _fail("W1A_VS6_REHIRE_EMPLOYMENT_MISSING: internal rehire runtime contract failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_04b_postgres_rehire_overlap_is_stable_error_and_exact_rollback() -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rehire-overlap")
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_REHIRE_OVERLAP"
    resident_number = _synthetic_resident_number("900201", "1234567")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_employment
                        (staff_id, employment_no, staff_no, staff_no_year,
                         staff_no_sequence, start_date, end_date,
                         created_by_account_id, updated_by_account_id, row_version)
                    VALUES (:staff_id, 1, :staff_no, 2025, 950101,
                            DATE '2025-01-01', DATE '2026-06-30',
                            :account_id, :account_id, 1)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "staff_no": f"2025-950101-{fixture.token}",
                    "account_id": fixture.account_id,
                },
            )
            employment_id = int(
                connection.execute(
                    text(
                        "SELECT id FROM erp.staff_employment "
                        "WHERE staff_id = :staff_id AND employment_no = 1"
                    ),
                    {"staff_id": fixture.staff_id},
                ).scalar_one()
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_position_period
                        (staff_id, employment_id, position_code, start_date, end_date,
                         created_by_account_id, updated_by_account_id, row_version)
                    VALUES (:staff_id, :employment_id, 'CARE_WORKER',
                            DATE '2025-01-01', DATE '2026-06-30',
                            :account_id, :account_id, 1)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "employment_id": employment_id,
                    "account_id": fixture.account_id,
                },
            )
        _seed_identity(
            engine,
            fixture=fixture,
            crypto=crypto,
            settings=settings,
            resident_number=resident_number,
        )
        with engine.connect() as connection:
            before = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-OVERLAP-%",
                counter_years=(2025, 2026),
            )
        row = {
            "legacy_staff_key": f"VS6-SYNTHETIC-REHIRE-OVERLAP-{fixture.token}",
            "name": f"VS6 overlap rehire {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 overlap address {fixture.token}",
            "phone": "010-2000-0071",
            "employment_start_date": date(2026, 1, 1),
            "employment_end_date": date(2026, 12, 31),
            "position": "SOCIAL_WORKER",
            "licenses": [],
        }
        failed_with_stable_error = False
        try:
            with Session(engine) as database_session:
                _invoke_apply(
                    apply,
                    [row],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        except error_type:
            failed_with_stable_error = True
        except Exception:
            _fail("W1A_VS6_REHIRE_OVERLAP_STABLE_ERROR_MISSING: raw error escaped")
        if not failed_with_stable_error:
            _fail("W1A_VS6_REHIRE_OVERLAP_STABLE_ERROR_MISSING: overlap was accepted")
        with engine.connect() as connection:
            after = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-OVERLAP-%",
                counter_years=(2025, 2026),
            )
        if before != after:
            _fail("W1A_VS6_REHIRE_OVERLAP_ROLLBACK_EXACT_MISSING")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_REHIRE_OVERLAP_STABLE_ERROR_MISSING: overlap probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_04c_postgres_rehire_license_failure_restores_exact_snapshot() -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rehire-license-rollback")
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_REHIRE_LICENSE_ROLLBACK"
    resident_number = _synthetic_resident_number("900301", "1234567")
    try:
        _seed_identity(
            engine,
            fixture=fixture,
            crypto=crypto,
            settings=settings,
            resident_number=resident_number,
        )
        _seed_prior_employment(
            engine,
            fixture=fixture,
            employment_no=1,
            staff_no_year=2026,
            staff_no_sequence=950301,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            position_code="CARE_WORKER",
        )
        with engine.connect() as connection:
            before = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-LICENSE-ROLLBACK-%",
                counter_years=(2026, 2027),
            )
        row = {
            "legacy_staff_key": f"VS6-SYNTHETIC-REHIRE-LICENSE-ROLLBACK-{fixture.token}",
            "name": f"VS6 license rollback {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 license rollback address {fixture.token}",
            "phone": "010-2000-0081",
            "employment_start_date": date(2027, 1, 1),
            "employment_end_date": date(2027, 12, 31),
            "position": "NURSE",
            "licenses": [
                {
                    "type": "VS6_UNKNOWN_LICENSE",
                    "number": f"VS6-SYNTHETIC-UNKNOWN-LICENSE-{fixture.token}",
                    "issued_date": date(2027, 1, 1),
                }
            ],
        }
        failed_with_stable_error = False
        try:
            with Session(engine) as database_session:
                _invoke_apply(
                    apply,
                    [row],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        except error_type:
            failed_with_stable_error = True
        except Exception:
            _fail("W1A_VS6_REHIRE_LICENSE_ROLLBACK_EXACT_MISSING: raw error escaped")
        if not failed_with_stable_error:
            _fail(
                "W1A_VS6_REHIRE_LICENSE_ROLLBACK_EXACT_MISSING: forced license failure was accepted"
            )
        with engine.connect() as connection:
            after = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-LICENSE-ROLLBACK-%",
                counter_years=(2026, 2027),
            )
        if before != after:
            _fail("W1A_VS6_REHIRE_LICENSE_ROLLBACK_EXACT_MISSING")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_REHIRE_LICENSE_ROLLBACK_EXACT_MISSING: license rollback probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_04d_postgres_rehire_mapping_failure_restores_exact_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rehire-mapping-rollback")
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_REHIRE_MAPPING_ROLLBACK"
    resident_number = _synthetic_resident_number("900501", "1234567")
    try:
        _seed_identity(
            engine,
            fixture=fixture,
            crypto=crypto,
            settings=settings,
            resident_number=resident_number,
        )
        _seed_prior_employment(
            engine,
            fixture=fixture,
            employment_no=1,
            staff_no_year=2028,
            staff_no_sequence=950401,
            start_date=date(2028, 1, 1),
            end_date=date(2028, 12, 31),
            position_code="CARE_WORKER",
        )
        with engine.connect() as connection:
            before = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-MAPPING-ROLLBACK-%",
                counter_years=(2028, 2029),
            )

        row = {
            "legacy_staff_key": f"VS6-SYNTHETIC-REHIRE-MAPPING-ROLLBACK-{fixture.token}",
            "name": f"VS6 mapping rollback {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 mapping rollback address {fixture.token}",
            "phone": "010-2000-0111",
            "employment_start_date": date(2029, 1, 1),
            "employment_end_date": date(2029, 12, 31),
            "position": "MANAGER",
            "licenses": [],
        }
        failed_with_stable_error = False
        try:
            with Session(engine) as database_session:
                original_add = database_session.add
                mapping_type = importer.StaffLegacyMapping

                def failing_add(instance: object, _warn: bool = True) -> None:
                    if isinstance(instance, mapping_type):
                        raise SQLAlchemyError("VS6 synthetic mapping failure")
                    original_add(instance, _warn=_warn)

                monkeypatch.setattr(database_session, "add", failing_add)
                _invoke_apply(
                    apply,
                    [row],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        except error_type:
            failed_with_stable_error = True
        except Exception:
            _fail("W1A_VS6_REHIRE_MAPPING_ROLLBACK_EXACT_MISSING: raw error escaped")
        if not failed_with_stable_error:
            _fail("W1A_VS6_REHIRE_MAPPING_ROLLBACK_EXACT_MISSING: forced mapping failure accepted")
        with engine.connect() as connection:
            after = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-MAPPING-ROLLBACK-%",
                counter_years=(2028, 2029),
            )
        if before != after:
            _fail("W1A_VS6_REHIRE_MAPPING_ROLLBACK_EXACT_MISSING")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_REHIRE_MAPPING_ROLLBACK_EXACT_MISSING: mapping rollback probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_04e_postgres_rehire_audit_failure_restores_exact_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "rehire-audit-rollback")
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_REHIRE_AUDIT_ROLLBACK"
    resident_number = _synthetic_resident_number("900101", "1234567")
    try:
        _seed_identity(
            engine,
            fixture=fixture,
            crypto=crypto,
            settings=settings,
            resident_number=resident_number,
        )
        _seed_prior_employment(
            engine,
            fixture=fixture,
            employment_no=1,
            staff_no_year=2027,
            staff_no_sequence=950501,
            start_date=date(2027, 1, 1),
            end_date=date(2027, 12, 31),
            position_code="CARE_WORKER",
        )
        with engine.connect() as connection:
            before = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-AUDIT-ROLLBACK-%",
                counter_years=(2027, 2028),
            )

        def failing_audit(*args: object, **kwargs: object) -> None:
            raise SQLAlchemyError("VS6 synthetic audit failure")

        monkeypatch.setattr(importer, "_audit", failing_audit)
        row = {
            "legacy_staff_key": f"VS6-SYNTHETIC-REHIRE-AUDIT-ROLLBACK-{fixture.token}",
            "name": f"VS6 audit rollback {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 audit rollback address {fixture.token}",
            "phone": "010-2000-0101",
            "employment_start_date": date(2028, 1, 1),
            "employment_end_date": date(2028, 12, 31),
            "position": "MANAGER",
            "licenses": [],
        }
        failed_with_stable_error = False
        try:
            with Session(engine) as database_session:
                _invoke_apply(
                    apply,
                    [row],
                    source_system_code,
                    database_session,
                    fixture.account_id,
                    settings,
                )
        except error_type:
            failed_with_stable_error = True
        except Exception:
            _fail("W1A_VS6_REHIRE_AUDIT_ROLLBACK_EXACT_MISSING: raw error escaped")
        if not failed_with_stable_error:
            _fail("W1A_VS6_REHIRE_AUDIT_ROLLBACK_EXACT_MISSING: forced audit failure was accepted")
        with engine.connect() as connection:
            after = _snapshot_staff_import_state(
                connection,
                fixture=fixture,
                source_system_code=source_system_code,
                mapping_prefix="VS6-SYNTHETIC-REHIRE-AUDIT-ROLLBACK-%",
                counter_years=(2027, 2028),
            )
        if before != after:
            _fail("W1A_VS6_REHIRE_AUDIT_ROLLBACK_EXACT_MISSING")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_REHIRE_AUDIT_ROLLBACK_EXACT_MISSING: audit rollback probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_05_postgres_mapping_replacement_is_atomic_versioned_and_audited() -> None:
    _require_product()
    importer, settings, crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    replace = _resolve_mapping_replacement(importer)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    engine = _owner_engine()
    fixture = _fixture(engine, "mapping-replacement")
    source_system_code = "VS6_SYNTHETIC_MAPPING"
    resident_number = _synthetic_resident_number("900108", "1234567")
    replacement_actor_id: int | None = None
    try:
        encrypted = crypto.encrypt_resident_number(
            staff_id=fixture.staff_id,
            resident_number=resident_number,
            settings=settings,
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO erp.staff_sensitive_identity
                        (staff_id, resident_number_ciphertext, resident_number_nonce,
                         resident_number_key_version, resident_number_lookup_hmac)
                    VALUES (:staff_id, :ciphertext, :nonce, :key_version, :lookup_hash)
                    """
                ),
                {
                    "staff_id": fixture.staff_id,
                    "ciphertext": encrypted.ciphertext,
                    "nonce": encrypted.nonce,
                    "key_version": encrypted.key_version,
                    "lookup_hash": encrypted.lookup_hmac,
                },
            )
            replacement_staff_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.staff
                            (name, birth_date, sex_code, phone, phone_normalized,
                             address, display_name, memo)
                        VALUES (:name, DATE '1991-01-01', 'TEST', NULL, NULL,
                                :address, :display_name, :memo)
                        RETURNING id
                        """
                    ),
                    {
                        "name": f"VS6 replacement target {fixture.token}",
                        "address": f"VS6 replacement address {fixture.token}",
                        "display_name": f"VS6 replacement display {fixture.token}",
                        "memo": f"VS6 replacement memo {fixture.token}",
                    },
                ).scalar_one()
            )
        replacement_actor_id = _create_actor_for_staff(
            engine, fixture, replacement_staff_id, "mapping-replacement"
        )
        original_key = f"VS6-SYNTHETIC-MAPPING-ORIGINAL-{fixture.token}"
        seed_row = {
            "legacy_staff_key": original_key,
            "name": f"VS6 mapping source {fixture.token}",
            "resident_number": resident_number,
            "address": f"VS6 mapping source address {fixture.token}",
            "phone": "010-2000-0108",
            "employment_start_date": date(2026, 1, 1),
            "employment_end_date": None,
            "position": "CARE_WORKER",
            "licenses": [],
        }
        with Session(engine) as database_session:
            seed_result = _invoke_apply(
                apply,
                [seed_row],
                source_system_code,
                database_session,
                fixture.account_id,
                settings,
            )
        if not isinstance(seed_result, dict) or seed_result.get("included_count") != 1:
            _fail("W1A_VS6_MAPPING_APPLY_MISSING: mapping seed did not apply")
        with engine.connect() as connection:
            original = connection.execute(
                text(
                    f"""
                    SELECT id, row_version, created_at_utc, updated_at_utc,
                           invalidated_at_utc, replacement_staff_legacy_mapping_id,
                           created_by_account_id, updated_by_account_id
                    FROM erp.{TABLE_NAME}
                    WHERE source_system_code = :source_system_code
                      AND legacy_staff_key = :legacy_staff_key
                    """
                ),
                {
                    "source_system_code": source_system_code,
                    "legacy_staff_key": original_key,
                },
            ).one()
        try:
            with Session(engine) as database_session:
                _invoke_mapping_replacement(
                    replace,
                    mapping_id=int(original.id),
                    replacement_staff_id=replacement_staff_id,
                    source_system_code=source_system_code,
                    legacy_staff_key=original_key,
                    database_session=database_session,
                    actor_account_id=replacement_actor_id,
                    settings=settings,
                    expected_row_version=int(original.row_version),
                )
        except Exception:
            _fail("W1A_VS6_MAPPING_REPLACEMENT_MISSING: replacement command did not apply")
        with engine.connect() as connection:
            replacement_state = connection.execute(
                text(
                    f"""
                    SELECT old.id AS old_id, old.row_version AS old_row_version,
                           old.invalidated_at_utc AS old_invalidated_at_utc,
                           old.replacement_staff_legacy_mapping_id AS old_replacement_id,
                           old.updated_by_account_id AS old_updated_by,
                           old.updated_at_utc AS old_updated_at,
                           replacement.id AS replacement_id,
                           replacement.staff_id AS replacement_staff_id,
                           replacement.row_version AS replacement_row_version,
                           replacement.source_system_code AS replacement_source_system_code,
                           replacement.legacy_staff_key AS replacement_legacy_staff_key,
                           replacement.created_by_account_id AS replacement_created_by,
                           replacement.updated_by_account_id AS replacement_updated_by,
                           replacement.created_at_utc AS replacement_created_at,
                           replacement.updated_at_utc AS replacement_updated_at
                    FROM erp.{TABLE_NAME} old
                    JOIN erp.{TABLE_NAME} replacement
                      ON replacement.id = old.replacement_staff_legacy_mapping_id
                    WHERE old.id = :mapping_id
                      AND replacement.invalidated_at_utc IS NULL
                    """
                ),
                {"mapping_id": int(original.id)},
            ).one()
            active_count = connection.execute(
                text(
                    f"SELECT count(*) FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = :source_system_code "
                    "AND legacy_staff_key = :legacy_staff_key "
                    "AND invalidated_at_utc IS NULL"
                ),
                {"source_system_code": source_system_code, "legacy_staff_key": original_key},
            ).scalar_one()
            actions: dict[str, int] = {
                str(row.action_code): int(row[1])
                for row in connection.execute(
                    text(
                        """
                        SELECT action_code, count(*)
                        FROM erp.audit_event
                        WHERE actor_account_id IN (:seed_actor_id, :replacement_actor_id)
                          AND entity_type = 'STAFF_LEGACY_MAPPING'
                          AND created_from = 'LEGACY_IMPORT'
                        GROUP BY action_code
                        """
                    ),
                    {
                        "seed_actor_id": fixture.account_id,
                        "replacement_actor_id": replacement_actor_id,
                    },
                ).all()
            }
            audit_rows = connection.execute(
                text(
                    """
                    SELECT action_code, actor_account_id, entity_type, entity_pk,
                           before_json, after_json, created_from, occurred_at_utc
                    FROM erp.audit_event
                    WHERE actor_account_id IN (:seed_actor_id, :replacement_actor_id)
                      AND entity_type = 'STAFF_LEGACY_MAPPING'
                      AND created_from = 'LEGACY_IMPORT'
                    ORDER BY id
                    """
                ),
                {
                    "seed_actor_id": fixture.account_id,
                    "replacement_actor_id": replacement_actor_id,
                },
            ).all()
            if (
                int(replacement_state.old_id) != int(original.id)
                or int(replacement_state.old_row_version) != int(original.row_version) + 1
                or replacement_state.old_invalidated_at_utc is None
                or int(replacement_state.old_replacement_id)
                != int(replacement_state.replacement_id)
                or int(replacement_state.old_updated_by) != replacement_actor_id
                or replacement_state.old_updated_at <= original.updated_at_utc
                or int(replacement_state.replacement_staff_id) != replacement_staff_id
                or int(replacement_state.replacement_row_version) != 1
                or str(replacement_state.replacement_source_system_code) != source_system_code
                or str(replacement_state.replacement_legacy_staff_key) != original_key
                or int(replacement_state.replacement_created_by) != replacement_actor_id
                or int(replacement_state.replacement_updated_by) != replacement_actor_id
                or replacement_state.replacement_created_at is None
                or replacement_state.replacement_updated_at is None
                or int(active_count) != 1
            ):
                _fail(
                    "W1A_VS6_MAPPING_REPLACEMENT_MISSING: "
                    "invalidation/link/version/actor/time state is incorrect"
                )
            if actions != {
                "STAFF_LEGACY_MAPPING_CREATE": 1,
                "STAFF_LEGACY_MAPPING_INVALIDATE": 1,
                "STAFF_LEGACY_MAPPING_REPLACEMENT_CREATE": 1,
            }:
                _fail(
                    "W1A_VS6_MAPPING_AUDIT_MISSING: "
                    "create/invalidate/replacement audit is incomplete"
                )
            expected_audits = [
                (
                    "STAFF_LEGACY_MAPPING_CREATE",
                    fixture.account_id,
                    "STAFF_LEGACY_MAPPING",
                    int(original.id),
                    False,
                    True,
                    "LEGACY_IMPORT",
                ),
                (
                    "STAFF_LEGACY_MAPPING_INVALIDATE",
                    replacement_actor_id,
                    "STAFF_LEGACY_MAPPING",
                    int(original.id),
                    True,
                    True,
                    "LEGACY_IMPORT",
                ),
                (
                    "STAFF_LEGACY_MAPPING_REPLACEMENT_CREATE",
                    replacement_actor_id,
                    "STAFF_LEGACY_MAPPING",
                    int(replacement_state.replacement_id),
                    False,
                    True,
                    "LEGACY_IMPORT",
                ),
            ]
            actual_audits = [
                (
                    str(row.action_code),
                    int(row.actor_account_id),
                    str(row.entity_type),
                    int(row.entity_pk),
                    row.before_json is not None,
                    row.after_json is not None,
                    str(row.created_from),
                )
                for row in audit_rows
            ]
            if actual_audits != expected_audits or any(
                row.occurred_at_utc is None for row in audit_rows
            ):
                _fail("W1A_VS6_MAPPING_AUDIT_EXACT_MISSING")

        rollback_key = f"VS6-SYNTHETIC-MAPPING-ROLLBACK-{fixture.token}"
        rollback_row = dict(seed_row)
        rollback_row["legacy_staff_key"] = rollback_key
        with Session(engine) as database_session:
            _invoke_apply(
                apply,
                [rollback_row],
                source_system_code,
                database_session,
                fixture.account_id,
                settings,
            )
        with engine.connect() as connection:
            rollback_mappings_before, rollback_audits_before = _mapping_key_snapshot(
                connection,
                source_system_code=source_system_code,
                legacy_staff_key=rollback_key,
                actor_account_id=fixture.account_id,
            )
        if len(rollback_mappings_before) != 1:
            _fail("W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: seed row count was not one")
        rollback_original = rollback_mappings_before[0]
        rollback_mapping_id = int(cast(Any, rollback_original[0]))
        rollback_row_version = int(cast(Any, rollback_original[-1]))
        replacement_staff_id = _create_replacement_staff(engine, fixture, "mapping-rollback")
        trigger_suffix = uuid4().hex
        trigger_function_name = f"vs6_fail_mapping_insert_{trigger_suffix}"
        trigger_name = f"vs6_fail_mapping_insert_trigger_{trigger_suffix}"
        trigger_state = {"fired": False, "old_flush_missing": False}
        trigger_installed = False
        handle_error_installed = False

        def capture_trigger_error(exception_context: Any) -> None:
            original_exception = exception_context.original_exception
            diagnostic = getattr(original_exception, "diag", None)
            detail = str(getattr(diagnostic, "message_detail", "") or "")
            expected_detail = (
                f"old_mapping_id={rollback_mapping_id};replacement_staff_id={replacement_staff_id}"
            )
            if (
                "W1A_VS6_TRIGGER_REPLACEMENT_INSERT_REACHED" in str(original_exception)
                and expected_detail in detail
            ):
                trigger_state["fired"] = True
            if (
                "W1A_VS6_TRIGGER_OLD_FLUSH_MISSING" in str(original_exception)
                and expected_detail in detail
            ):
                trigger_state["old_flush_missing"] = True

        escaped_source_system_code = source_system_code.replace("'", "''")
        escaped_rollback_key = rollback_key.replace("'", "''")

        with engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    CREATE OR REPLACE FUNCTION erp.{trigger_function_name}()
                    RETURNS trigger
                    LANGUAGE plpgsql
                    AS $$
                    BEGIN
                        IF NEW.source_system_code = '{escaped_source_system_code}'
                           AND NEW.legacy_staff_key = '{escaped_rollback_key}'
                           AND NEW.staff_id = {replacement_staff_id} THEN
                            IF EXISTS (
                                SELECT 1
                                FROM erp.{TABLE_NAME}
                                WHERE id = {rollback_mapping_id}
                                  AND invalidated_at_utc IS NOT NULL
                                  AND row_version = 2
                            ) THEN
                                RAISE EXCEPTION
                                    USING MESSAGE =
                                        'W1A_VS6_TRIGGER_REPLACEMENT_INSERT_REACHED',
                                    DETAIL = format(
                                        'old_mapping_id=%s;replacement_staff_id=%s',
                                        {rollback_mapping_id}, NEW.staff_id
                                    );
                            END IF;
                            RAISE EXCEPTION USING
                                MESSAGE = 'W1A_VS6_TRIGGER_OLD_FLUSH_MISSING',
                                DETAIL = format(
                                    'old_mapping_id=%s;replacement_staff_id=%s',
                                    {rollback_mapping_id}, NEW.staff_id
                                );
                        END IF;
                        RETURN NEW;
                    END;
                    $$
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    CREATE TRIGGER {trigger_name}
                    AFTER INSERT ON erp.{TABLE_NAME}
                    FOR EACH ROW
                    EXECUTE FUNCTION erp.{trigger_function_name}()
                    """
                )
            )
        trigger_installed = True
        event.listen(engine, "handle_error", capture_trigger_error)
        handle_error_installed = True
        replacement_failed = False
        try:
            with Session(engine) as database_session:
                _invoke_mapping_replacement(
                    replace,
                    mapping_id=rollback_mapping_id,
                    replacement_staff_id=replacement_staff_id,
                    source_system_code=source_system_code,
                    legacy_staff_key=rollback_key,
                    database_session=database_session,
                    actor_account_id=fixture.account_id,
                    settings=settings,
                    expected_row_version=rollback_row_version,
                )
        except error_type:
            replacement_failed = True
        except Exception:
            _fail("W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: failure leaked raw database error")
        if not replacement_failed:
            _fail("W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: trigger failure did not occur")
        if not trigger_state["fired"]:
            _fail(
                "W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: "
                "replacement INSERT trigger marker was not observed"
            )
        if trigger_state["old_flush_missing"]:
            _fail(
                "W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: "
                "replacement INSERT did not observe old mapping flush"
            )
        with engine.connect() as connection:
            rollback_mappings_after, rollback_audits_after = _mapping_key_snapshot(
                connection,
                source_system_code=source_system_code,
                legacy_staff_key=rollback_key,
                actor_account_id=fixture.account_id,
            )
            if (
                len(rollback_mappings_after) != 1
                or len(rollback_audits_after) != len(rollback_audits_before)
                or rollback_mappings_after != rollback_mappings_before
                or rollback_audits_after != rollback_audits_before
            ):
                _fail("W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: failed replace was not atomic")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_PG_HARNESS_FAILURE: mapping replacement probe failed")
    except (AttributeError, TypeError, ValueError, RuntimeError):
        _fail("W1A_VS6_MAPPING_REPLACEMENT_MISSING: internal replacement runtime contract failed")
    finally:
        if "handle_error_installed" in locals() and handle_error_installed:
            event.remove(engine, "handle_error", capture_trigger_error)
        if "trigger_function_name" in locals():
            try:
                with engine.begin() as connection:
                    if "trigger_name" in locals():
                        connection.execute(
                            text(f"DROP TRIGGER IF EXISTS {trigger_name} ON erp.{TABLE_NAME}")
                        )
                    connection.execute(
                        text(f"DROP FUNCTION IF EXISTS erp.{trigger_function_name}()")
                    )
                with engine.connect() as connection:
                    remaining_trigger = connection.execute(
                        text("SELECT count(*) FROM pg_trigger WHERE tgname = :trigger_name"),
                        {"trigger_name": trigger_name},
                    ).scalar_one()
                    remaining_function = connection.execute(
                        text("SELECT count(*) FROM pg_proc WHERE proname = :function_name"),
                        {"function_name": trigger_function_name},
                    ).scalar_one()
                    if int(remaining_trigger) != 0 or int(remaining_function) != 0:
                        _fail(
                            "W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: "
                            "trigger cleanup was incomplete"
                        )
            except pytest.fail.Exception:
                raise
            except SQLAlchemyError:
                _fail("W1A_VS6_MAPPING_REPLACEMENT_ROLLBACK_MISSING: trigger cleanup failed")
        _cleanup_fixture(
            engine,
            fixture,
            additional_actor_account_ids=()
            if replacement_actor_id is None
            else (replacement_actor_id,),
        )
        engine.dispose()


def test_vs6_05a_mapping_replacement_requires_expected_row_version() -> None:
    _require_product()
    importer, _settings, _crypto = _load_legacy_importer()
    replace = _resolve_mapping_replacement(
        importer,
        marker="W1A_VS6_MAPPING_EXPECTED_VERSION_REQUIRED",
    )
    _require_expected_row_version(replace, "W1A_VS6_MAPPING_EXPECTED_VERSION_REQUIRED")


def test_vs6_05b_mapping_replacement_rejects_stale_version_without_mutation() -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "mapping-stale")
    importer, settings, _crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    replace = _resolve_mapping_replacement(
        importer,
        marker="W1A_VS6_MAPPING_STALE_VERSION_REJECTED",
    )
    _require_expected_row_version(replace, "W1A_VS6_MAPPING_STALE_VERSION_REJECTED")
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_MAPPING_STALE"
    legacy_staff_key = f"VS6-SYNTHETIC-MAPPING-STALE-{fixture.token}"
    try:
        original = _seed_mapping_with_apply(
            engine,
            fixture=fixture,
            settings=settings,
            apply=apply,
            source_system_code=source_system_code,
            legacy_staff_key=legacy_staff_key,
            marker="W1A_VS6_MAPPING_STALE_VERSION_REJECTED",
        )
        replacement_staff_id = _create_replacement_staff(engine, fixture, "stale")
        _promote_mapping_row_version(
            engine,
            mapping_id=int(original.id),
            marker="W1A_VS6_MAPPING_STALE_VERSION_REJECTED",
        )
        with engine.connect() as connection:
            actual_row_version = int(
                connection.execute(
                    text(f"SELECT row_version FROM erp.{TABLE_NAME} WHERE id = :mapping_id"),
                    {"mapping_id": int(original.id)},
                ).scalar_one()
            )
        if actual_row_version != 2:
            _fail(
                "W1A_VS6_MAPPING_STALE_VERSION_REJECTED: "
                "fixture did not establish the actual positive version 2"
            )
        with engine.connect() as connection:
            before_mappings, before_audits = _mapping_key_snapshot(
                connection,
                source_system_code=source_system_code,
                legacy_staff_key=legacy_staff_key,
                actor_account_id=fixture.account_id,
            )
        if len(before_mappings) != 1:
            _fail("W1A_VS6_MAPPING_STALE_VERSION_MUTATION_MISSING: seed row count was not one")
        failed_with_stable_error = False
        try:
            with Session(engine) as database_session:
                _invoke_mapping_replacement(
                    replace,
                    mapping_id=int(original.id),
                    replacement_staff_id=replacement_staff_id,
                    source_system_code=source_system_code,
                    legacy_staff_key=legacy_staff_key,
                    database_session=database_session,
                    actor_account_id=fixture.account_id,
                    settings=settings,
                    expected_row_version=actual_row_version - 1,
                )
        except error_type:
            failed_with_stable_error = True
        except Exception:
            _fail("W1A_VS6_MAPPING_STALE_VERSION_REJECTED: raw stale-version error escaped")
        if not failed_with_stable_error:
            _fail("W1A_VS6_MAPPING_STALE_VERSION_REJECTED: stale version was accepted")
        with engine.connect() as connection:
            after_mappings, after_audits = _mapping_key_snapshot(
                connection,
                source_system_code=source_system_code,
                legacy_staff_key=legacy_staff_key,
                actor_account_id=fixture.account_id,
            )
        if (
            len(after_mappings) != 1
            or len(after_audits) != len(before_audits)
            or after_mappings != before_mappings
            or after_audits != before_audits
        ):
            _fail("W1A_VS6_MAPPING_STALE_VERSION_MUTATION_MISSING")
        try:
            with Session(engine) as database_session:
                _invoke_mapping_replacement(
                    replace,
                    mapping_id=int(original.id),
                    replacement_staff_id=replacement_staff_id,
                    source_system_code=source_system_code,
                    legacy_staff_key=legacy_staff_key,
                    database_session=database_session,
                    actor_account_id=fixture.account_id,
                    settings=settings,
                    expected_row_version=actual_row_version,
                )
        except error_type:
            _fail("W1A_VS6_MAPPING_STALE_VERSION_REJECTED: current version was rejected")
        except Exception:
            _fail("W1A_VS6_MAPPING_STALE_VERSION_REJECTED: current version escaped raw error")
        with engine.connect() as connection:
            final_mappings, final_audits = _mapping_key_snapshot(
                connection,
                source_system_code=source_system_code,
                legacy_staff_key=legacy_staff_key,
                actor_account_id=fixture.account_id,
            )
        active_rows = [row for row in final_mappings if row[5] is None]
        if (
            len(final_mappings) != 2
            or len(active_rows) != 1
            or len(final_audits) != len(before_audits) + 2
            or int(cast(Any, final_mappings[0][11])) != actual_row_version + 1
            or int(cast(Any, final_mappings[0][6])) != int(cast(Any, final_mappings[1][0]))
            or int(cast(Any, final_mappings[1][3])) != replacement_staff_id
        ):
            _fail("W1A_VS6_MAPPING_STALE_VERSION_REJECTED: current version success was incomplete")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_MAPPING_STALE_VERSION_REJECTED: stale-version probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_05c_mapping_replacement_concurrent_expected_version_allows_one_success() -> None:
    _require_product()
    engine = _owner_engine()
    fixture = _fixture(engine, "mapping-concurrent")
    importer, settings, _crypto = _load_legacy_importer()
    apply = _resolve_apply(importer)
    replace = _resolve_mapping_replacement(
        importer,
        marker="W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING",
    )
    _require_expected_row_version(replace, "W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING")
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    source_system_code = "VS6_SYNTHETIC_MAPPING_CONCURRENT"
    legacy_staff_key = f"VS6-SYNTHETIC-MAPPING-CONCURRENT-{fixture.token}"
    try:
        original = _seed_mapping_with_apply(
            engine,
            fixture=fixture,
            settings=settings,
            apply=apply,
            source_system_code=source_system_code,
            legacy_staff_key=legacy_staff_key,
            marker="W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING",
        )
        _promote_mapping_row_version(
            engine,
            mapping_id=int(original.id),
            marker="W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING",
        )
        with engine.connect() as connection:
            actual_row_version = int(
                connection.execute(
                    text(f"SELECT row_version FROM erp.{TABLE_NAME} WHERE id = :mapping_id"),
                    {"mapping_id": int(original.id)},
                ).scalar_one()
            )
        if actual_row_version != 2:
            _fail("W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING: actual version was not 2")
        target_ids = (
            _create_replacement_staff(engine, fixture, "concurrent-one"),
            _create_replacement_staff(engine, fixture, "concurrent-two"),
        )
        barrier = threading.Barrier(2)

        def attempt(target_staff_id: int) -> tuple[str, bool]:
            try:
                barrier.wait(timeout=10)
                with Session(engine) as database_session:
                    _invoke_mapping_replacement(
                        replace,
                        mapping_id=int(original.id),
                        replacement_staff_id=target_staff_id,
                        source_system_code=source_system_code,
                        legacy_staff_key=legacy_staff_key,
                        database_session=database_session,
                        actor_account_id=fixture.account_id,
                        settings=settings,
                        expected_row_version=actual_row_version,
                    )
                return "success", False
            except error_type as raised:
                error_text = str(raised).lower()
                return (
                    "stable_error",
                    any(
                        token in error_text
                        for token in ("version", "row_version", "stale", "optimistic")
                    ),
                )
            except Exception:
                return "raw_error", False

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt, target_ids))
        statuses = sorted(outcome[0] for outcome in outcomes)
        if statuses != ["stable_error", "success"]:
            _fail("W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING: concurrency outcome was unstable")
        if not any(outcome[1] for outcome in outcomes):
            _fail(
                "W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING: "
                "loser did not expose stable expected-version semantics"
            )
        with engine.connect() as connection:
            state = connection.execute(
                text(
                    f"SELECT old.row_version, old.invalidated_at_utc, "
                    "old.replacement_staff_legacy_mapping_id, replacement.staff_id "
                    f"FROM erp.{TABLE_NAME} old JOIN erp.{TABLE_NAME} replacement "
                    "ON replacement.id = old.replacement_staff_legacy_mapping_id "
                    "WHERE old.id = :mapping_id AND replacement.invalidated_at_utc IS NULL"
                ),
                {"mapping_id": int(original.id)},
            ).one_or_none()
            active_count = connection.execute(
                text(
                    f"SELECT count(*) FROM erp.{TABLE_NAME} "
                    "WHERE source_system_code = :source_system_code "
                    "AND legacy_staff_key = :legacy_staff_key "
                    "AND invalidated_at_utc IS NULL"
                ),
                {
                    "source_system_code": source_system_code,
                    "legacy_staff_key": legacy_staff_key,
                },
            ).scalar_one()
            audit_counts = connection.execute(
                text(
                    """
                    SELECT action_code, count(*) AS count
                    FROM erp.audit_event
                    WHERE actor_account_id = :account_id
                      AND entity_type = 'STAFF_LEGACY_MAPPING'
                      AND created_from = 'LEGACY_IMPORT'
                    GROUP BY action_code
                    ORDER BY action_code
                    """
                ),
                {"account_id": fixture.account_id},
            ).all()
        if (
            state is None
            or int(state.row_version) != actual_row_version + 1
            or state.invalidated_at_utc is None
            or int(state.replacement_staff_legacy_mapping_id) <= 0
            or int(state.staff_id) not in target_ids
            or int(active_count) != 1
            or {str(row.action_code): int(row[1]) for row in audit_counts}
            != {
                "STAFF_LEGACY_MAPPING_CREATE": 1,
                "STAFF_LEGACY_MAPPING_INVALIDATE": 1,
                "STAFF_LEGACY_MAPPING_REPLACEMENT_CREATE": 1,
            }
        ):
            _fail("W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING: final state was not atomic")
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail("W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING: concurrency probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()


def test_vs6_05d_mapping_replacement_locks_active_row() -> None:
    marker = "W1A_VS6_MAPPING_ACTIVE_LOCK_MISSING"
    _require_product()
    importer, settings, _crypto = _load_legacy_importer()
    replace = _resolve_mapping_replacement(importer, marker=marker)
    _require_expected_row_version(replace, marker)
    error_type = getattr(importer, "LegacyImportError", None)
    if not isinstance(error_type, type) or not issubclass(error_type, Exception):
        _fail("W1A_VS6_SERVICE_MISSING: importer error type is not available")
    engine = _owner_engine()
    fixture = _fixture(engine, "mapping-active-lock")
    source_system_code = "VS6_SYNTHETIC_MAPPING_ACTIVE_LOCK"
    legacy_staff_key = f"VS6-SYNTHETIC-MAPPING-ACTIVE-LOCK-{fixture.token}"
    try:
        original = _seed_mapping_with_apply(
            engine,
            fixture=fixture,
            settings=settings,
            apply=_resolve_apply(importer),
            source_system_code=source_system_code,
            legacy_staff_key=legacy_staff_key,
            marker=marker,
        )
        replacement_staff_id = _create_replacement_staff(engine, fixture, "active-lock")
        statement_trace: list[tuple[str, bool, bool, bool, bool]] = []

        def parameter_values(parameters: object) -> list[object]:
            if isinstance(parameters, dict):
                return list(parameters.values())
            if isinstance(parameters, (tuple, list)):
                return list(parameters)
            return []

        def capture_for_update(*args: Any, **kwargs: Any) -> None:
            if len(args) < 4:
                return
            normalized = " ".join(str(args[2]).split()).lower()
            if "staff_legacy_mapping" not in normalized:
                return
            values = parameter_values(args[3])
            contains_original_id = any(str(value) == str(original.id) for value in values)
            is_select = normalized.startswith("select")
            is_update = normalized.startswith("update")
            has_active_predicate = "invalidated_at_utc is null" in normalized
            has_for_update = "for update" in normalized
            if contains_original_id and (is_select or is_update):
                statement_trace.append(
                    (
                        normalized,
                        contains_original_id,
                        has_active_predicate,
                        has_for_update,
                        is_update,
                    )
                )

        event.listen(engine, "before_cursor_execute", capture_for_update)
        try:
            try:
                with Session(engine) as database_session:
                    _invoke_mapping_replacement(
                        replace,
                        mapping_id=int(original.id),
                        replacement_staff_id=replacement_staff_id,
                        source_system_code=source_system_code,
                        legacy_staff_key=legacy_staff_key,
                        database_session=database_session,
                        actor_account_id=fixture.account_id,
                        settings=settings,
                        expected_row_version=int(original.row_version),
                    )
            except error_type:
                _fail(marker + ": replacement command failed before lock assertion")
            except Exception:
                _fail(marker + ": raw replacement error escaped")
        finally:
            event.remove(engine, "before_cursor_execute", capture_for_update)
        target_lock_positions = [
            index
            for index, (_sql, has_id, active, for_update, is_update) in enumerate(statement_trace)
            if has_id and active and for_update and not is_update
        ]
        target_update_positions = [
            index
            for index, (_sql, has_id, _active, _for_update, is_update) in enumerate(statement_trace)
            if has_id and is_update
        ]
        if (
            not target_lock_positions
            or not target_update_positions
            or min(target_lock_positions) >= min(target_update_positions)
        ):
            _fail(
                marker
                + ": target active-row SELECT FOR UPDATE with original id parameters "
                + "did not precede replacement UPDATE"
            )
    except pytest.fail.Exception:
        raise
    except SQLAlchemyError:
        _fail(marker + ": active-row lock probe failed")
    finally:
        _cleanup_fixture(engine, fixture)
        engine.dispose()
