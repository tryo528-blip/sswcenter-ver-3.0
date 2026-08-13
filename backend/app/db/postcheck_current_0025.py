"""Focused catalog postcheck for the corrected W1/W2 0025 head.

Historical postchecks keep proving their original revision snapshots.  This
module verifies only the current contract after the forward corrections.
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.session import create_postgres_engine

EXPECTED_REVISION = "20260813_0025_w1_relationship_lock_contract_correction"

EXACT_TRAINING_CODES = (
    "NEW_HIRE_ORIENTATION",
    "ELDER_RIGHTS",
    "DISABLED_ABUSE",
    "ELDER_ABUSE",
    "SEXUAL_HARASSMENT",
    "WORKPLACE_BULLYING",
    "PRIVACY",
    "CONTINUING_EDUCATION",
)

REQUIRED_W2_TABLES = {
    "monthly_professional_assignment",
    "w2_schedule_month_control",
    "w2_schedule",
    "w2_schedule_staff",
    "w2_personal_todo_list",
    "w2_personal_todo",
    "w2_official_work_card",
    "w2_service_plan_notice",
}

FORBIDDEN_CURRENT_TABLES = {
    "staff_health_check_requirement",
    "recipient_guardian_primary_period",
    "recipient_payer_snapshot",
    "recipient_grade_period",
}

REQUIRED_TRIGGERS = {
    "biu_recipient_guardian_assign_slot",
    "ct_monthly_professional_assignment_fact_guard",
    "bd_biu_w2_schedule_month_guard",
    "bd_biu_w2_schedule_staff_month_guard",
    "ct_w2_schedule_staff_contract_from_schedule",
    "ct_w2_schedule_staff_contract_from_staff",
    "bu_w2_schedule_month_finalize_guard",
    "ct_w2_service_plan_notice_guard",
    "ct_w2_service_plan_contract_reverse_guard",
    "ct_w2_service_plan_certification_reverse_guard",
    "tr_recipient_plan_notification_read_only",
}

OFFICIAL_CARD_KINDS = {
    "RECOGNITION_EXPIRY",
    "CONTRACT_EXPIRY",
    "PLAN_NOTICE",
    "STAFF_REPLACEMENT_CONSULTATION",
    "NEW_STAFF_WORK",
}


def _columns(connection: Connection, table_name: str) -> dict[str, bool]:
    return {
        str(name): nullable == "YES"
        for name, nullable in connection.execute(
            text(
                """
                SELECT column_name, is_nullable
                  FROM information_schema.columns
                 WHERE table_schema = 'erp' AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).all()
    }


def _require_columns(
    columns: dict[str, bool],
    *,
    required: dict[str, bool],
    forbidden: set[str] = frozenset(),
    label: str,
) -> None:
    missing = sorted(set(required) - columns.keys())
    present_forbidden = sorted(forbidden & columns.keys())
    wrong_nullability = sorted(
        name for name, nullable in required.items() if columns.get(name) != nullable
    )
    if missing or present_forbidden or wrong_nullability:
        raise SystemExit(
            f"{label} column contract mismatch: missing={missing}, "
            f"forbidden={present_forbidden}, nullability={wrong_nullability}"
        )


def _privileges(connection: Connection, role: str, table_name: str) -> tuple[bool, ...]:
    return tuple(
        bool(value)
        for value in connection.execute(
            text(
                """
                SELECT has_table_privilege(:role, :table_name, 'SELECT'),
                       has_table_privilege(:role, :table_name, 'INSERT'),
                       has_table_privilege(:role, :table_name, 'UPDATE'),
                       has_table_privilege(:role, :table_name, 'DELETE'),
                       has_table_privilege(:role, :table_name, 'TRUNCATE')
                """
            ),
            {"role": role, "table_name": f"erp.{table_name}"},
        ).one()
    )


def verify_current_0025(connection: Connection) -> None:
    revision = connection.scalar(text("SELECT version_num FROM erp.alembic_version"))
    if revision != EXPECTED_REVISION:
        raise SystemExit(
            f"CURRENT_0025_REVISION_MISMATCH: expected={EXPECTED_REVISION} actual={revision}"
        )

    tables = {
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT tablename
                  FROM pg_tables
                 WHERE schemaname = 'erp'
                """
            )
        )
    }
    missing_w2 = sorted(REQUIRED_W2_TABLES - tables)
    forbidden_present = sorted(FORBIDDEN_CURRENT_TABLES & tables)
    if missing_w2 or forbidden_present:
        raise SystemExit(
            f"CURRENT_0025_TABLE_MISMATCH: missing={missing_w2} "
            f"forbidden={forbidden_present}"
        )

    _require_columns(
        _columns(connection, "recipient"),
        required={
            "name": True,
            "birth_date": True,
            "sex_code": True,
            "mobile_phone": False,
            "payer_guardian_id": True,
        },
        forbidden={"home_phone"},
        label="recipient",
    )
    _require_columns(
        _columns(connection, "recipient_guardian"),
        required={
            "slot_no": False,
            "name": True,
            "relationship_text": True,
            "phone": True,
            "address": True,
            "email": True,
        },
        label="recipient_guardian",
    )
    _require_columns(
        _columns(connection, "recipient_contract"),
        required={"recipient_id": False, "start_date": False, "end_date": True},
        forbidden={"signer_name", "signer_relationship_text", "signer_phone"},
        label="recipient_contract",
    )
    _require_columns(
        _columns(connection, "recipient_certification_period"),
        required={"grade_code": False, "start_date": False, "end_date": False},
        label="recipient_certification_period",
    )
    _require_columns(
        _columns(connection, "recipient_benefit_period"),
        required={"benefit_code": False, "start_text": False},
        forbidden={"start_date", "end_date", "benefit_period"},
        label="recipient_benefit_period",
    )
    _require_columns(
        _columns(connection, "staff_health_check"),
        required={"staff_id": False, "employment_id": True, "check_date": False},
        forbidden={"check_type_code", "result_note"},
        label="staff_health_check",
    )
    relationship_constraints = {
        str(name): str(definition)
        for name, definition in connection.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid, true)
                  FROM pg_constraint
                 WHERE conrelid IN (
                    'erp.recipient'::regclass,
                    'erp.recipient_guardian'::regclass,
                    'erp.staff_health_check'::regclass
                 )
                """
            )
        ).all()
    }
    expected_constraint_fragments = {
        "ck_recipient_guardian_slot_no": "CHECK (slot_no = ANY (ARRAY[1, 2]))",
        "uq_recipient_guardian_recipient_slot": "UNIQUE (recipient_id, slot_no)",
        "fk_recipient_payer_guardian_same_recipient": (
            "ON DELETE SET NULL (payer_guardian_id)"
        ),
        "fk_staff_health_check_employment": (
            "FOREIGN KEY (staff_id, employment_id) REFERENCES staff_employment(staff_id, id)"
        ),
    }
    wrong_relationship_constraints = sorted(
        name
        for name, fragment in expected_constraint_fragments.items()
        if fragment not in relationship_constraints.get(name, "")
    )
    if wrong_relationship_constraints:
        raise SystemExit(
            "CURRENT_0025_RELATIONSHIP_CONSTRAINT_MISMATCH: "
            f"{wrong_relationship_constraints}"
        )
    _require_columns(
        _columns(connection, "staff_quarterly_consultation"),
        required={
            "staff_id": False,
            "calendar_year": False,
            "quarter_no": False,
            "completed": False,
        },
        forbidden={
            "status",
            "counseling_date",
            "content",
            "incomplete_reason_text",
            "exempt_reason_text",
        },
        label="staff_quarterly_consultation",
    )

    training_codes = tuple(
        str(value)
        for value in connection.scalars(
            text("SELECT code FROM erp.training_course ORDER BY sort_order")
        )
    )
    if training_codes != EXACT_TRAINING_CODES:
        raise SystemExit(f"CURRENT_0025_TRAINING_CODES_MISMATCH: {training_codes}")

    triggers = {
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT t.tgname
                  FROM pg_trigger AS t
                  JOIN pg_class AS c ON c.oid = t.tgrelid
                  JOIN pg_namespace AS n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'erp' AND NOT t.tgisinternal
                """
            )
        )
    }
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)
    if missing_triggers:
        raise SystemExit(f"CURRENT_0025_TRIGGER_MISSING: {missing_triggers}")

    card_constraints = " ".join(
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT pg_get_constraintdef(oid, true)
                  FROM pg_constraint
                 WHERE conrelid = 'erp.w2_official_work_card'::regclass
                   AND contype = 'c'
                """
            )
        )
    )
    actual_kinds = set(re.findall(r"'([A-Z_]+)'", card_constraints))
    if actual_kinds != OFFICIAL_CARD_KINDS:
        raise SystemExit(f"CURRENT_0025_CARD_KIND_MISMATCH: {sorted(actual_kinds)}")

    role_exists = bool(
        connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='erp_app')"))
    )
    if role_exists:
        if _privileges(connection, "erp_app", "w2_service_plan_notice") != (
            True,
            True,
            True,
            False,
            False,
        ):
            raise SystemExit("CURRENT_0025_SERVICE_PLAN_APP_ACL_MISMATCH")
        for legacy_table in (
            "recipient_plan_notification",
            "recipient_service_plan_notice",
        ):
            if _privileges(connection, "erp_app", legacy_table) != (
                True,
                False,
                False,
                False,
                False,
            ):
                raise SystemExit(f"CURRENT_0025_LEGACY_ACL_MISMATCH: {legacy_table}")


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("CURRENT_0025_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            verify_current_0025(connection)
    finally:
        engine.dispose()
    print("SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK")


if __name__ == "__main__":
    main()
