from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.postcheck import verify_wave0_invariants
from app.db.session import create_postgres_engine

W1A_REVISION = "20260726_0003_w1a_staff"
VS2_REVISION = "20260727_0004_w1a_staff_qualifications"
VS3_REVISION = "20260728_0005_w1a_staff_training"
W1B_REVISION = "20260730_0009_w1b_recipient"
W1C_REVISION = "20260730_0010_w1c_certification_ledgers"
W1D_REVISION = "20260730_0011_w1d_recipient_contract"
W1E_REVISION = "20260801_0012_w1e_care_assignment"
CONTINUING_EDUCATION_REVISION = "20260802_0013_staff_continuing_education"
RECIPIENT_PLAN_NOTIFICATION_REVISION = "20260803_0014_recipient_plan_notification"
RECIPIENT_STATUS_TAG_REVISION = "20260806_0015_recipient_status_tag"
RECIPIENT_PAYER_GUARDIAN_REVISION = "20260808_0016_recipient_payer_guardian"
RECIPIENT_GUARDIAN_EMAIL_REVISION = "20260808_0017_recipient_guardian_email"
W1E_LINEAGE_REVISIONS = {
    W1E_REVISION,
    CONTINUING_EDUCATION_REVISION,
    RECIPIENT_PLAN_NOTIFICATION_REVISION,
    RECIPIENT_STATUS_TAG_REVISION,
    RECIPIENT_PAYER_GUARDIAN_REVISION,
    RECIPIENT_GUARDIAN_EMAIL_REVISION,
}
W1A_PERMISSION_CODES = {
    "COPAY_USE",
    "IO_IMPORT_USE",
    "OUTPUT_USE",
    "STAFF_MANAGE",
    "STAFF_VIEW",
    "SW_MENU_USE",
}
W1B_PERMISSION_CODES = W1A_PERMISSION_CODES | {
    "RECIPIENT_MANAGE",
    "RECIPIENT_VIEW",
}
W1B_TABLES = {
    "recipient",
    "recipient_guardian",
    "recipient_guardian_primary_period",
    "recipient_legacy_mapping",
    "recipient_payer_snapshot",
}
W1B_FUNCTIONS = {"fn_recipient_no_immutable"}
W1C_TABLES = {
    "recipient_certification_identity",
    "recipient_certification_period",
    "recipient_grade_period",
    "recipient_benefit_period",
    "recipient_local_approval_amount_period",
}
W1C_FUNCTIONS = {
    "fn_recipient_certification_number_immutable",
    "fn_w1c_assert_grade_containment",
    "fn_w1c_assert_certification_contains_grades",
}
W1D_TABLES = {"recipient_contract"}
W1D_FUNCTIONS = {
    "fn_recipient_contract_no_reactivation",
    "fn_recipient_contract_group_overlap",
}
W1D_CONSTRAINTS = {
    "pk_recipient_contract",
    "ck_recipient_contract_date_order",
    "ck_recipient_contract_row_version_positive",
    "ex_recipient_contract_same_service_period",
    "fk_recipient_contract_recipient",
    "fk_recipient_contract_service_type",
    "fk_recipient_contract_replacement",
    "fk_recipient_contract_created_by_account",
    "fk_recipient_contract_updated_by_account",
}
W1D_TRIGGERS = {
    "bu_recipient_contract_no_reactivation",
    "trg_recipient_contract_group_period_overlap",
}
W1E_TABLES = {"care_assignment"}
W1E_FUNCTIONS = {
    "fn_care_assignment_within_contract",
    "fn_care_assignment_within_employment",
    "fn_care_assignment_within_position",
    "fn_care_assignment_general_care_qualified",
    "fn_recipient_contract_assignment_reverse_guard",
    "fn_staff_position_care_assignment_reverse_guard",
    "fn_staff_service_qualification_assignment_reverse_guard",
}
W1E_CONSTRAINTS = {
    "pk_care_assignment",
    "fk_care_assignment_recipient_contract",
    "fk_care_assignment_employment",
    "fk_care_assignment_replacement",
    "fk_care_assignment_created_by_account",
    "fk_care_assignment_updated_by_account",
    "ck_care_assignment_kind",
    "ck_care_assignment_date_order",
    "ck_care_assignment_row_version_positive",
    "ex_care_assignment_same_contract_staff_period",
}
W1E_TRIGGERS = {
    "ct_care_assignment_within_contract",
    "ct_care_assignment_within_employment",
    "ct_care_assignment_within_position",
    "ct_care_assignment_general_care_qualified",
}
W1E_TRIGGER_CONTRACTS = {
    "ct_care_assignment_within_contract": (
        "care_assignment",
        "fn_care_assignment_within_contract",
    ),
    "ct_care_assignment_within_employment": (
        "care_assignment",
        "fn_care_assignment_within_employment",
    ),
    "ct_care_assignment_within_position": (
        "care_assignment",
        "fn_care_assignment_within_position",
    ),
    "ct_care_assignment_general_care_qualified": (
        "care_assignment",
        "fn_care_assignment_general_care_qualified",
    ),
    "ct_recipient_contract_assignment_reverse_guard": (
        "recipient_contract",
        "fn_recipient_contract_assignment_reverse_guard",
    ),
    "ct_staff_position_care_assignment_reverse_guard": (
        "staff_position_period",
        "fn_staff_position_care_assignment_reverse_guard",
    ),
    "ct_staff_service_qualification_assignment_reverse_guard": (
        "staff_service_qualification_period",
        "fn_staff_service_qualification_assignment_reverse_guard",
    ),
}

SENSITIVE_COLUMNS = {
    "encrypted_at_utc": ("timestamp with time zone", "NO"),
    "resident_number_ciphertext": ("bytea", "NO"),
    "resident_number_key_version": ("integer", "NO"),
    "resident_number_lookup_hmac": ("bytea", "NO"),
    "resident_number_nonce": ("bytea", "NO"),
    "row_version": ("integer", "NO"),
    "staff_id": ("bigint", "NO"),
    "updated_at_utc": ("timestamp with time zone", "NO"),
}

PERIOD_AUDIT_COLUMNS = {
    "staff_employment": {
        "row_version": ("integer", "NO"),
        "updated_at_utc": ("timestamp with time zone", "NO"),
        "updated_by_account_id": ("bigint", "NO"),
    },
    "staff_operational_role_period": {
        "created_by_account_id": ("bigint", "NO"),
        "row_version": ("integer", "NO"),
        "updated_at_utc": ("timestamp with time zone", "NO"),
        "updated_by_account_id": ("bigint", "NO"),
    },
    "staff_position_period": {
        "created_by_account_id": ("bigint", "NO"),
        "row_version": ("integer", "NO"),
        "updated_at_utc": ("timestamp with time zone", "NO"),
        "updated_by_account_id": ("bigint", "NO"),
    },
}

SENSITIVE_CONSTRAINTS = {
    "ck_staff_sensitive_identity_ciphertext_nonempty",
    "ck_staff_sensitive_identity_key_version_positive",
    "ck_staff_sensitive_identity_lookup_hmac_length",
    "ck_staff_sensitive_identity_nonce_length",
    "ck_staff_sensitive_identity_row_version_positive",
    "fk_staff_sensitive_identity_staff_id_staff",
    "pk_staff_sensitive_identity",
    "uq_staff_sensitive_identity_lookup_hmac",
}

W1A_CONSTRAINTS = {
    "ck_staff_employment_row_version_positive",
    "ck_staff_operational_role_period_role_code_format",
    "ck_staff_operational_role_period_row_version_positive",
    "ck_staff_position_period_row_version_positive",
    "ck_staff_sex_code",
    "fk_staff_employment_updated_by_account",
    "fk_staff_position_period_created_by_account",
    "fk_staff_position_period_updated_by_account",
    "fk_staff_role_period_created_by_account",
    "fk_staff_role_period_updated_by_account",
}

W1A_TRIGGERS = {
    "ct_staff_employment_child_periods_reverse_guard",
    "ct_staff_operational_role_within_employment",
    "ct_staff_position_within_employment",
}

W1A_FUNCTIONS = {
    "fn_staff_employment_child_periods_reverse_guard",
    "fn_staff_operational_role_within_employment",
    "fn_staff_position_within_employment",
}

VS2_TABLES = {
    "service_group",
    "service_type",
    "license_type",
    "staff_license",
    "staff_service_qualification_period",
}
VS2_CATALOG_TABLES = {"service_group", "service_type", "license_type"}
VS2_FACT_TABLES = {"staff_license", "staff_service_qualification_period"}
VS2_FUNCTIONS = {
    "fn_staff_service_qualification_source_license_guard",
    "fn_staff_service_qualification_within_employment",
}
VS2_TRIGGERS = {
    "ct_staff_service_qualification_source_license_guard",
    "ct_staff_service_qualification_within_employment",
}
VS2_CONSTRAINTS = {
    "ex_staff_service_qualification_period",
    "fk_staff_license_license_type_id_license_type",
    "fk_staff_license_replacement_license_id_staff_license",
    "fk_staff_license_staff_id_staff",
    "fk_staff_service_qualification_period_employment",
    "fk_staff_service_qualification_service_type",
    "fk_staff_service_qualification_period_source_license",
    "fk_staff_service_qualification_period_staff_id_staff",
    "pk_license_type",
    "pk_service_group",
    "pk_service_type",
    "pk_staff_license",
    "pk_staff_service_qualification_period",
    "uq_service_group_code",
    "uq_service_type_code",
    "uq_staff_license_staff_id_id",
}
VS2_GROUPS = {
    "LONG_TERM_CARE": "장기요양",
    "LOCAL_CARE": "지역돌봄 연계",
    "BARO_CARE": "바로돌봄",
}
VS2_SERVICES = {
    ("LONG_TERM_CARE", "HOME_CARE"): "방문요양",
    ("LONG_TERM_CARE", "HOME_BATH"): "방문목욕",
    ("LOCAL_CARE", "TEMP_HOME_CARE"): "일시재가",
    ("LOCAL_CARE", "HOSPITAL_ESCORT"): "병원동행",
    ("BARO_CARE", "BARO_CARE"): "바로돌봄",
}
VS2_LICENSE_TYPES = {
    "CARE_WORKER": "요양보호사",
    "SOCIAL_WORKER": "사회복지사",
    "NURSE": "간호사",
}

VS3_TABLES = {
    "training_course",
    "staff_onboarding_training",
    "staff_periodic_training_status",
}
VS3_CATALOG_TABLES = {"training_course"}
VS3_FACT_TABLES = {"staff_onboarding_training", "staff_periodic_training_status"}
VS3_FUNCTIONS = {
    "fn_staff_onboarding_training_course_guard",
    "fn_staff_periodic_training_cycle_guard",
}
VS3_TRIGGERS = {
    "ct_staff_onboarding_training_course_guard",
    "ct_staff_periodic_training_cycle_guard",
}
VS3_CONSTRAINTS = {
    "ck_training_course_cycle_type",
    "ck_training_course_sort_order_positive",
    "pk_training_course",
    "uq_training_course_sort_order",
    "ck_staff_onboarding_training_course_code",
    "ck_staff_onboarding_training_row_version_positive",
    "fk_staff_onboarding_training_staff_id_staff",
    "fk_staff_onboarding_training_employment",
    "fk_staff_onboarding_training_course_code",
    "fk_staff_onboarding_training_replacement",
    "fk_staff_onboarding_training_created_by_account",
    "fk_staff_onboarding_training_updated_by_account",
    "pk_staff_onboarding_training",
    "ck_staff_periodic_training_course_code",
    "ck_staff_periodic_training_period_key",
    "ck_staff_periodic_training_row_version_positive",
    "fk_staff_periodic_training_staff_id_staff",
    "fk_staff_periodic_training_course_code",
    "fk_staff_periodic_training_replacement",
    "fk_staff_periodic_training_created_by_account",
    "fk_staff_periodic_training_updated_by_account",
    "pk_staff_periodic_training_status",
}
VS3_COURSES = (
    (1, "NEW_HIRE_ORIENTATION", "신규직원교육", "ON_HIRE"),
    (2, "ELDER_RIGHTS", "노인인권", "HALF_YEAR"),
    (3, "DISABLED_ABUSE", "장애인학대 신고의무자교육", "ANNUAL"),
    (4, "ELDER_ABUSE", "노인학대 신고의무자교육", "ANNUAL"),
    (5, "SEXUAL_HARASSMENT", "직장 내 성희롱 예방교육", "ANNUAL"),
    (6, "WORKPLACE_BULLYING", "직장 내 괴롭힘 예방교육", "ANNUAL"),
    (7, "PRIVACY", "개인정보보호교육", "ANNUAL"),
)
CONTINUING_EDUCATION_COURSE = (8, "CONTINUING_EDUCATION", "보수교육", "BIENNIAL")

SENSITIVE_INDEXES = {
    "pk_staff_sensitive_identity",
    "uq_staff_sensitive_identity_lookup_hmac",
}

ALLOWED_SENSITIVE_COLUMN_NAMES = {
    "resident_number_ciphertext",
    "resident_number_key_version",
    "resident_number_lookup_hmac",
    "resident_number_nonce",
}


def _column_contract(
    connection: Connection,
    *,
    table_name: str,
) -> dict[str, tuple[str, str]]:
    rows = connection.execute(
        text(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'erp'
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return {str(row.column_name): (str(row.data_type), str(row.is_nullable)) for row in rows}


def _verify_role_acl_fingerprint(connection: Connection) -> None:
    sensitive = connection.execute(
        text(
            """
            SELECT
                has_schema_privilege('erp_app', 'erp', 'USAGE') AS app_schema_usage,
                has_schema_privilege('erp_app', 'erp', 'CREATE') AS app_schema_create,
                has_table_privilege(
                    'erp_app', 'erp.staff_sensitive_identity', 'SELECT'
                ) AS app_select,
                has_table_privilege(
                    'erp_app', 'erp.staff_sensitive_identity', 'INSERT'
                ) AS app_insert,
                has_table_privilege(
                    'erp_app', 'erp.staff_sensitive_identity', 'UPDATE'
                ) AS app_update,
                has_table_privilege(
                    'erp_app', 'erp.staff_sensitive_identity', 'DELETE'
                ) AS app_delete,
                has_table_privilege(
                    'erp_app', 'erp.staff_sensitive_identity', 'TRUNCATE'
                ) AS app_truncate,
                has_table_privilege(
                    'erp_backup', 'erp.staff_sensitive_identity', 'SELECT'
                ) AS backup_select,
                has_table_privilege(
                    'erp_backup', 'erp.staff_sensitive_identity', 'INSERT'
                ) AS backup_insert
            """
        )
    ).one()
    expected_sensitive = (True, False, True, True, True, False, False, True, False)
    if tuple(sensitive) != expected_sensitive:
        raise SystemExit(f"Unexpected W1A sensitive ACL fingerprint: {tuple(sensitive)}")

    sequences = connection.execute(
        text(
            """
            SELECT
                bool_and(
                    has_sequence_privilege(
                        'erp_app', format('erp.%I', c.relname), 'USAGE'
                    )
                    AND has_sequence_privilege(
                        'erp_app', format('erp.%I', c.relname), 'SELECT'
                    )
                    AND NOT has_sequence_privilege(
                        'erp_app', format('erp.%I', c.relname), 'UPDATE'
                    )
                ) AS app_exact,
                bool_and(
                    has_sequence_privilege(
                        'erp_backup', format('erp.%I', c.relname), 'SELECT'
                    )
                    AND NOT has_sequence_privilege(
                        'erp_backup', format('erp.%I', c.relname), 'USAGE'
                    )
                ) AS backup_exact
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'erp' AND c.relkind = 'S'
            """
        )
    ).one()
    if sequences.app_exact is not True or sequences.backup_exact is not True:
        raise SystemExit("Unexpected W1A sequence ACL fingerprint")


def _verify_vs2_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in VS2_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1A-VS2 tables: {sorted(missing_tables)}")

    groups: dict[str, str] = {
        str(row[0]): str(row[1])
        for row in connection.execute(text("SELECT code, display_name FROM erp.service_group"))
    }
    services = {
        (row.group_code, row.service_code): row.display_name
        for row in connection.execute(
            text(
                """
                SELECT g.code AS group_code,
                       s.code AS service_code,
                       s.display_name
                FROM erp.service_type AS s
                JOIN erp.service_group AS g ON g.id = s.service_group_id
                """
            )
        )
    }
    license_types: dict[str, str] = {
        str(row[0]): str(row[1])
        for row in connection.execute(text("SELECT code, display_name FROM erp.license_type"))
    }
    if groups != VS2_GROUPS or services != VS2_SERVICES or license_types != VS2_LICENSE_TYPES:
        raise SystemExit("Unexpected W1A-VS2 catalog seed")

    service_type_columns = {
        str(row.column_name)
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'erp' AND table_name = 'service_type'
                """
            )
        )
    }
    license_columns = {
        str(row.column_name)
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'erp' AND table_name = 'staff_license'
                """
            )
        )
    }
    qualification_columns = {
        str(row.column_name)
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND table_name = 'staff_service_qualification_period'
                """
            )
        )
    }
    if "service_group_id" not in service_type_columns or "group_code" in service_type_columns:
        raise SystemExit("Invalid W1A-VS2 service_type group relationship")
    if not {"license_number", "issued_date", "invalidated_at_utc"}.issubset(license_columns):
        raise SystemExit("Invalid W1A-VS2 license fact columns")
    if {"start_date", "end_date", "expiry_date"}.intersection(license_columns):
        raise SystemExit("W1A-VS2 license fact contains period columns")
    if not {
        "staff_id",
        "employment_id",
        "service_type_id",
        "start_date",
        "end_date",
        "source_license_id",
    }.issubset(qualification_columns):
        raise SystemExit("Invalid W1A-VS2 qualification fact columns")
    if {"license_number", "issued_date"}.intersection(qualification_columns):
        raise SystemExit("W1A-VS2 qualification fact duplicates license columns")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                """
            )
        ).scalars()
    )
    missing_constraints = sorted(VS2_CONSTRAINTS - constraints)
    if missing_constraints:
        raise SystemExit(f"Missing W1A-VS2 constraints: {missing_constraints}")

    check_definitions = [
        (str(row.table_name), str(row.definition))
        for row in connection.execute(
            text(
                """
                SELECT c.relname AS table_name,
                       pg_get_constraintdef(pg_constraint.oid) AS definition
                FROM pg_constraint
                JOIN pg_class AS c ON c.oid = conrelid
                WHERE connamespace = 'erp'::regnamespace
                  AND contype = 'c'
                  AND conrelid IN (
                      'erp.staff_license'::regclass,
                      'erp.staff_service_qualification_period'::regclass
                  )
                """
            )
        )
    ]
    if not any(
        table_name == "staff_license" and "row_version > 0" in definition
        for table_name, definition in check_definitions
    ):
        raise SystemExit("W1A-VS2 license row-version check is missing")
    if not any(
        table_name == "staff_service_qualification_period" and "row_version > 0" in definition
        for table_name, definition in check_definitions
    ):
        raise SystemExit("W1A-VS2 qualification row-version check is missing")
    if not any(
        table_name == "staff_service_qualification_period"
        and "start_date <= end_date" in definition
        for table_name, definition in check_definitions
    ):
        raise SystemExit("W1A-VS2 qualification date-order check is missing")

    trigger_rows = connection.execute(
        text(
            """
            SELECT tgname, tgdeferrable, tginitdeferred
            FROM pg_trigger
            WHERE tgrelid = 'erp.staff_service_qualification_period'::regclass
              AND NOT tgisinternal
            """
        )
    )
    triggers = {
        str(row.tgname): (bool(row.tgdeferrable), bool(row.tginitdeferred)) for row in trigger_rows
    }
    if not VS2_TRIGGERS.issubset(triggers):
        raise SystemExit(f"Missing W1A-VS2 triggers: {sorted(VS2_TRIGGERS - set(triggers))}")
    if any(triggers[name] != (True, True) for name in VS2_TRIGGERS):
        raise SystemExit("W1A-VS2 qualification guards must be deferred and deferrable")

    for table_name in sorted(VS2_CATALOG_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, False, False, False, False):
            raise SystemExit("W1A-VS2 catalog ACL is not SELECT-only")
    for table_name in sorted(VS2_FACT_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, True, True, False, False):
            raise SystemExit("W1A-VS2 fact ACL is not write-without-delete")
    for table_name in sorted(VS2_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_backup', :table_name, 'SELECT'),
                       has_table_privilege('erp_backup', :table_name, 'INSERT'),
                       has_table_privilege('erp_backup', :table_name, 'UPDATE'),
                       has_table_privilege('erp_backup', :table_name, 'DELETE'),
                       has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, False, False, False, False):
            raise SystemExit("W1A-VS2 backup ACL is not SELECT-only")


def _verify_vs3_contract(
    connection: Connection, *, include_continuing_education: bool = False
) -> None:
    missing_tables = {
        table_name
        for table_name in VS3_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1A-VS3 tables: {sorted(missing_tables)}")

    courses = [
        tuple(row)
        for row in connection.execute(
            text(
                """
                SELECT sort_order, code, display_name, cycle_type
                FROM erp.training_course
                WHERE active IS TRUE
                ORDER BY sort_order, code
                """
            )
        )
    ]
    expected_courses = list(VS3_COURSES)
    if include_continuing_education:
        expected_courses.append(CONTINUING_EDUCATION_COURSE)
    if courses != expected_courses:
        raise SystemExit("Unexpected W1A-VS3 training course seed")

    table_columns = {
        table_name: {
            str(row.column_name)
            for row in connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'erp' AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
        }
        for table_name in VS3_TABLES
    }
    required_columns = {
        "training_course": {"code", "display_name", "cycle_type", "active", "sort_order"},
        "staff_onboarding_training": {
            "staff_id",
            "employment_id",
            "course_code",
            "completed",
            "created_by_account_id",
            "created_at_utc",
            "updated_by_account_id",
            "updated_at_utc",
            "row_version",
            "invalidated_at_utc",
        },
        "staff_periodic_training_status": {
            "staff_id",
            "course_code",
            "period_key",
            "completed",
            "created_by_account_id",
            "created_at_utc",
            "updated_by_account_id",
            "updated_at_utc",
            "row_version",
            "invalidated_at_utc",
        },
    }
    for table_name, expected in required_columns.items():
        if not expected.issubset(table_columns[table_name]):
            raise SystemExit(f"Invalid W1A-VS3 columns: {table_name}")
    if "employment_id" in table_columns["staff_periodic_training_status"]:
        raise SystemExit("W1A-VS3 periodic training must not reference employment")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                """
            )
        ).scalars()
    )
    missing_constraints = sorted(VS3_CONSTRAINTS - constraints)
    if missing_constraints:
        raise SystemExit(f"Missing W1A-VS3 constraints: {missing_constraints}")

    check_definitions = {
        str(row.conname): str(row.definition)
        for row in connection.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conname = ANY(:constraint_names)
                """
            ),
            {"constraint_names": list(VS3_CONSTRAINTS)},
        )
    }
    course_cycle_check = check_definitions.get("ck_training_course_cycle_type", "")
    if "ON_HIRE" not in course_cycle_check:
        raise SystemExit("W1A-VS3 course cycle check is missing")
    if include_continuing_education and "BIENNIAL" not in course_cycle_check:
        raise SystemExit("Continuing-education cycle is missing")
    if "NEW_HIRE_ORIENTATION" not in check_definitions.get(
        "ck_staff_onboarding_training_course_code", ""
    ):
        raise SystemExit("W1A-VS3 onboarding course check is missing")
    if "period_key" not in check_definitions.get("ck_staff_periodic_training_period_key", ""):
        raise SystemExit("W1A-VS3 periodic period check is missing")

    index_rows = connection.execute(
        text(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'erp'
              AND tablename IN ('staff_onboarding_training', 'staff_periodic_training_status')
            """
        )
    )
    indexes = {str(row.indexname): str(row.indexdef) for row in index_rows}
    for index_name in (
        "uq_staff_onboarding_training_active",
        "uq_staff_periodic_training_active",
    ):
        definition = indexes.get(index_name, "")
        if "UNIQUE" not in definition or "invalidated_at_utc IS NULL" not in definition:
            raise SystemExit(f"W1A-VS3 active unique index is invalid: {index_name}")

    trigger_rows = connection.execute(
        text(
            """
            SELECT tgname, tgdeferrable, tginitdeferred
            FROM pg_trigger
            WHERE tgrelid IN (
                'erp.staff_onboarding_training'::regclass,
                'erp.staff_periodic_training_status'::regclass
            )
              AND NOT tgisinternal
            """
        )
    )
    triggers = {
        str(row.tgname): (bool(row.tgdeferrable), bool(row.tginitdeferred)) for row in trigger_rows
    }
    if not VS3_TRIGGERS.issubset(triggers):
        raise SystemExit(f"Missing W1A-VS3 triggers: {sorted(VS3_TRIGGERS - set(triggers))}")
    if any(triggers[name] != (True, True) for name in VS3_TRIGGERS):
        raise SystemExit("W1A-VS3 training guards must be deferred and deferrable")

    for table_name in sorted(VS3_CATALOG_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, False, False, False, False):
            raise SystemExit("W1A-VS3 catalog ACL is not SELECT-only")
    for table_name in sorted(VS3_FACT_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, True, True, False, False):
            raise SystemExit("W1A-VS3 fact ACL is not write-without-delete")
    for table_name in sorted(VS3_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_backup', :table_name, 'SELECT'),
                       has_table_privilege('erp_backup', :table_name, 'INSERT'),
                       has_table_privilege('erp_backup', :table_name, 'UPDATE'),
                       has_table_privilege('erp_backup', :table_name, 'DELETE'),
                       has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, False, False, False, False):
            raise SystemExit("W1A-VS3 backup ACL is not SELECT-only")


def main() -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("SSWCENTER_DATABASE_URL is required")

    engine = create_postgres_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one_or_none()
            if current_revision not in {
                W1A_REVISION,
                VS2_REVISION,
                VS3_REVISION,
                VS4_REVISION,
                VS5_REVISION,
                VS6_REVISION,
                W1B_REVISION,
                W1C_REVISION,
                W1D_REVISION,
                W1E_REVISION,
                CONTINUING_EDUCATION_REVISION,
                RECIPIENT_PLAN_NOTIFICATION_REVISION,
                RECIPIENT_STATUS_TAG_REVISION,
                RECIPIENT_PAYER_GUARDIAN_REVISION,
                RECIPIENT_GUARDIAN_EMAIL_REVISION,
            }:
                raise SystemExit("Unexpected W1A migration revision")
            verify_wave0_invariants(
                connection,
                expected_revision=str(current_revision),
                expected_permission_count=len(
                    W1B_PERMISSION_CODES
                    if current_revision
                    in {
                        W1B_REVISION,
                        W1C_REVISION,
                        W1D_REVISION,
                        *W1E_LINEAGE_REVISIONS,
                    }
                    else W1A_PERMISSION_CODES
                ),
            )
            _verify_role_acl_fingerprint(connection)

            sensitive_columns = _column_contract(
                connection,
                table_name="staff_sensitive_identity",
            )
            if sensitive_columns != SENSITIVE_COLUMNS:
                raise SystemExit(
                    "Unexpected staff_sensitive_identity column contract: "
                    f"{sorted(sensitive_columns)}"
                )

            staff_phone_column = connection.execute(
                text(
                    """
                    SELECT data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'erp'
                      AND table_name = 'staff'
                      AND column_name = 'phone_normalized'
                    """
                )
            ).one_or_none()
            if staff_phone_column is None or tuple(staff_phone_column) != ("text", "YES"):
                raise SystemExit("staff.phone_normalized column contract is invalid")

            for table_name, expected_columns in PERIOD_AUDIT_COLUMNS.items():
                actual_columns = _column_contract(connection, table_name=table_name)
                actual_audit_columns = {name: actual_columns.get(name) for name in expected_columns}
                if actual_audit_columns != expected_columns:
                    raise SystemExit(f"Unexpected {table_name} audit/version column contract")

            sensitive_constraints = set(
                connection.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE connamespace = 'erp'::regnamespace
                          AND conrelid = 'erp.staff_sensitive_identity'::regclass
                        """
                    )
                ).scalars()
            )
            if sensitive_constraints != SENSITIVE_CONSTRAINTS:
                raise SystemExit(
                    "Unexpected staff_sensitive_identity constraints: "
                    f"{sorted(sensitive_constraints)}"
                )

            constraints = set(
                connection.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE connamespace = 'erp'::regnamespace
                        """
                    )
                ).scalars()
            )
            missing_constraints = sorted(W1A_CONSTRAINTS - constraints)
            if missing_constraints:
                raise SystemExit(f"Missing W1A constraints: {missing_constraints}")

            constraint_definitions = {
                str(row.conname): str(row.definition)
                for row in connection.execute(
                    text(
                        """
                        SELECT conname, pg_get_constraintdef(oid) AS definition
                        FROM pg_constraint
                        WHERE connamespace = 'erp'::regnamespace
                          AND conname IN (
                              'ck_staff_sex_code',
                              'ck_staff_operational_role_period_role_code_format'
                          )
                        """
                    )
                )
            }
            sex_definition = constraint_definitions.get("ck_staff_sex_code", "")
            if not all(value in sex_definition for value in ("MALE", "FEMALE", "TEST")):
                raise SystemExit("staff.sex_code must allow exactly MALE, FEMALE, and TEST")
            role_definition = constraint_definitions.get(
                "ck_staff_operational_role_period_role_code_format", ""
            )
            if "^[A-Z][A-Z0-9_]{0,49}$" not in role_definition:
                raise SystemExit("staff operational role code format constraint is invalid")

            trigger_rows = connection.execute(
                text(
                    """
                    SELECT tgname, tgdeferrable, tginitdeferred
                    FROM pg_trigger
                    WHERE tgrelid IN (
                        'erp.staff_employment'::regclass,
                        'erp.staff_operational_role_period'::regclass,
                        'erp.staff_position_period'::regclass
                    )
                      AND NOT tgisinternal
                    """
                )
            )
            triggers = {
                str(row.tgname): (bool(row.tgdeferrable), bool(row.tginitdeferred))
                for row in trigger_rows
            }
            expected_w1a_triggers = W1A_TRIGGERS | (
                {"ct_staff_position_care_assignment_reverse_guard"}
                if current_revision in W1E_LINEAGE_REVISIONS
                else set()
            )
            if set(triggers) != expected_w1a_triggers:
                raise SystemExit(f"Unexpected W1A triggers: {sorted(triggers)}")
            if any(state != (True, True) for state in triggers.values()):
                raise SystemExit("W1A constraint triggers must be deferred and deferrable")

            functions = set(
                connection.execute(
                    text(
                        """
                        SELECT proname
                        FROM pg_proc
                        WHERE pronamespace = 'erp'::regnamespace
                        """
                    )
                ).scalars()
            )
            expected_functions = (
                W1A_FUNCTIONS
                | VS2_FUNCTIONS
                | VS3_FUNCTIONS
                | VS4_FUNCTIONS
                | VS5_FUNCTIONS
                | VS6_FUNCTIONS
                | W1B_FUNCTIONS
                | W1C_FUNCTIONS
                | W1D_FUNCTIONS
                | W1E_FUNCTIONS
                if current_revision in W1E_LINEAGE_REVISIONS
                else W1A_FUNCTIONS
                | VS2_FUNCTIONS
                | VS3_FUNCTIONS
                | VS4_FUNCTIONS
                | VS5_FUNCTIONS
                | VS6_FUNCTIONS
                | W1B_FUNCTIONS
                | W1C_FUNCTIONS
                | W1D_FUNCTIONS
                if current_revision == W1D_REVISION
                else W1A_FUNCTIONS
                | VS2_FUNCTIONS
                | VS3_FUNCTIONS
                | VS4_FUNCTIONS
                | VS5_FUNCTIONS
                | VS6_FUNCTIONS
                | W1B_FUNCTIONS
                | W1C_FUNCTIONS
                if current_revision == W1C_REVISION
                else W1A_FUNCTIONS
                | VS2_FUNCTIONS
                | VS3_FUNCTIONS
                | VS4_FUNCTIONS
                | VS5_FUNCTIONS
                | VS6_FUNCTIONS
                | W1B_FUNCTIONS
                if current_revision == W1B_REVISION
                else W1A_FUNCTIONS | VS2_FUNCTIONS | VS3_FUNCTIONS | VS4_FUNCTIONS | VS5_FUNCTIONS
                if current_revision == VS5_REVISION
                else W1A_FUNCTIONS
                | VS2_FUNCTIONS
                | VS3_FUNCTIONS
                | VS4_FUNCTIONS
                | VS5_FUNCTIONS
                | VS6_FUNCTIONS
                if current_revision == VS6_REVISION
                else W1A_FUNCTIONS | VS2_FUNCTIONS | VS3_FUNCTIONS | VS4_FUNCTIONS
                if current_revision == VS4_REVISION
                else W1A_FUNCTIONS | VS2_FUNCTIONS | VS3_FUNCTIONS
                if current_revision == VS3_REVISION
                else W1A_FUNCTIONS | VS2_FUNCTIONS
                if current_revision == VS2_REVISION
                else W1A_FUNCTIONS
            )
            if functions != expected_functions:
                raise SystemExit(f"Unexpected W1A functions: {sorted(functions)}")

            if current_revision == VS2_REVISION:
                _verify_vs2_contract(connection)
            if current_revision == VS3_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
            if current_revision == VS4_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
                _verify_vs4_contract(connection)
            if current_revision == VS5_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
                _verify_vs4_contract(connection)
                _verify_vs5_contract(connection)
            if current_revision == VS6_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
                _verify_vs4_contract(connection)
                _verify_vs5_contract(connection)
                _verify_vs6_contract(connection)
            if current_revision == W1B_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
                _verify_vs4_contract(connection)
                _verify_vs5_contract(connection)
                _verify_vs6_contract(connection)
                _verify_w1b_contract(connection)
            if current_revision == W1C_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
                _verify_vs4_contract(connection)
                _verify_vs5_contract(connection)
                _verify_vs6_contract(connection)
                _verify_w1b_contract(connection)
                _verify_w1c_contract(connection)
            if current_revision == W1D_REVISION:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(connection)
                _verify_vs4_contract(connection)
                _verify_vs5_contract(connection)
                _verify_vs6_contract(connection)
                _verify_w1b_contract(connection)
                _verify_w1c_contract(connection)
                _verify_w1d_contract(connection)
            if current_revision in W1E_LINEAGE_REVISIONS:
                _verify_vs2_contract(connection)
                _verify_vs3_contract(
                    connection,
                    include_continuing_education=(
                        current_revision
                        in {
                            CONTINUING_EDUCATION_REVISION,
                            RECIPIENT_PLAN_NOTIFICATION_REVISION,
                            RECIPIENT_STATUS_TAG_REVISION,
                            RECIPIENT_PAYER_GUARDIAN_REVISION,
                            RECIPIENT_GUARDIAN_EMAIL_REVISION,
                        }
                    ),
                )
                _verify_vs4_contract(connection)
                _verify_vs5_contract(connection)
                _verify_vs6_contract(connection)
                _verify_w1b_contract(connection)
                _verify_w1c_contract(connection)
                _verify_w1d_contract(connection)
                _verify_w1e_contract(connection)
                if current_revision in {
                    RECIPIENT_PLAN_NOTIFICATION_REVISION,
                    RECIPIENT_STATUS_TAG_REVISION,
                    RECIPIENT_PAYER_GUARDIAN_REVISION,
                    RECIPIENT_GUARDIAN_EMAIL_REVISION,
                }:
                    _verify_recipient_plan_notification_contract(connection)
                if current_revision in {
                    RECIPIENT_STATUS_TAG_REVISION,
                    RECIPIENT_PAYER_GUARDIAN_REVISION,
                    RECIPIENT_GUARDIAN_EMAIL_REVISION,
                }:
                    # 0015 status tag remains required through the 0017 head.
                    _verify_recipient_status_tag_contract(connection)
                if current_revision in {
                    RECIPIENT_PAYER_GUARDIAN_REVISION,
                    RECIPIENT_GUARDIAN_EMAIL_REVISION,
                }:
                    # 0016 payer guardian remains required through the 0017 head.
                    _verify_recipient_payer_guardian_contract(connection)
                if current_revision == RECIPIENT_GUARDIAN_EMAIL_REVISION:
                    _verify_recipient_guardian_email_contract(connection)

            sensitive_indexes = set(
                connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'erp'
                          AND tablename = 'staff_sensitive_identity'
                        """
                    )
                ).scalars()
            )
            if sensitive_indexes != SENSITIVE_INDEXES:
                raise SystemExit(
                    f"Unexpected staff_sensitive_identity indexes: {sorted(sensitive_indexes)}"
                )

            phone_index = connection.execute(
                text(
                    """
                    SELECT i.indisunique, pg_get_indexdef(i.indexrelid)
                    FROM pg_index i
                    WHERE i.indexrelid = 'erp.ix_staff_phone_normalized'::regclass
                    """
                )
            ).one_or_none()
            if (
                phone_index is None
                or bool(phone_index.indisunique)
                or "(phone_normalized)" not in str(phone_index.pg_get_indexdef)
            ):
                raise SystemExit("ix_staff_phone_normalized contract is invalid")

            permission_rows = connection.execute(
                text(
                    """
                    SELECT permission_code, active
                    FROM erp.permission_definition
                    """
                )
            )
            permissions = {str(row.permission_code): bool(row.active) for row in permission_rows}
            expected_permissions = (
                W1B_PERMISSION_CODES
                if current_revision
                in {
                    W1B_REVISION,
                    W1C_REVISION,
                    W1D_REVISION,
                    *W1E_LINEAGE_REVISIONS,
                }
                else W1A_PERMISSION_CODES
            )
            if set(permissions) != expected_permissions:
                raise SystemExit(f"Unexpected permission definitions: {sorted(permissions)}")
            if not all(permissions.values()):
                raise SystemExit("All permission definitions must be active")

            suspicious_columns = connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'erp'
                      AND (
                          lower(column_name) LIKE '%rrn%'
                          OR lower(column_name) LIKE '%resident_number%'
                          OR lower(column_name) LIKE '%jumin%'
                      )
                    ORDER BY table_name, column_name
                    """
                )
            ).all()
            plaintext_columns = [
                row
                for row in suspicious_columns
                if row.column_name not in ALLOWED_SENSITIVE_COLUMN_NAMES
            ]
            if plaintext_columns:
                raise SystemExit(
                    f"Plaintext resident-number columns are forbidden: {plaintext_columns}"
                )
    finally:
        engine.dispose()

    if current_revision == RECIPIENT_GUARDIAN_EMAIL_REVISION:
        print("RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK")
    elif current_revision == RECIPIENT_PAYER_GUARDIAN_REVISION:
        print("RECIPIENT_PAYER_GUARDIAN_DB_POSTCHECK_OK")
    elif current_revision == RECIPIENT_STATUS_TAG_REVISION:
        print("RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK")
    elif current_revision == RECIPIENT_PLAN_NOTIFICATION_REVISION:
        print("RECIPIENT_PLAN_NOTIFICATION_DB_POSTCHECK_OK")
    elif current_revision == CONTINUING_EDUCATION_REVISION:
        print("STAFF_CONTINUING_EDUCATION_DB_POSTCHECK_OK")
    elif current_revision == W1E_REVISION:
        print("W1E_DB_POSTCHECK_OK")
    elif current_revision == W1D_REVISION:
        print("W1D_DB_POSTCHECK_OK")
    elif current_revision == W1C_REVISION:
        print("W1C_DB_POSTCHECK_OK")
    elif current_revision == W1B_REVISION:
        print("W1B_DB_POSTCHECK_OK")
    elif current_revision == VS6_REVISION:
        print("W1A_VS6_DB_POSTCHECK_OK")
    elif current_revision == VS5_REVISION:
        print("W1A_VS5_DB_POSTCHECK_OK")
    elif current_revision == VS4_REVISION:
        print("W1A_VS4_DB_POSTCHECK_OK")
    elif current_revision == VS3_REVISION:
        print("W1A_VS3_DB_POSTCHECK_OK")
    elif current_revision == VS2_REVISION:
        print("W1A_VS2_DB_POSTCHECK_OK")
    else:
        print("W1A_VS1_DB_POSTCHECK_OK")


VS4_REVISION = "20260728_0006_w1a_staff_health_check"
VS5_REVISION = "20260728_0007_w1a_staff_quarterly_consultation"
VS6_REVISION = "20260728_0008_w1a_staff_legacy_mapping"
VS4_TABLES = {"staff_health_check", "staff_health_check_requirement"}
VS4_FACT_TABLES = set(VS4_TABLES)
VS4_FUNCTIONS = {
    "fn_staff_health_check_requirement_fact_guard",
    "fn_staff_health_check_requirement_reverse_guard",
}
VS4_TRIGGERS = {
    "ct_staff_health_check_requirement_fact_guard",
    "ct_staff_health_check_requirement_reverse_guard",
}
VS4_CONSTRAINTS = {
    "ck_staff_health_check_row_version_positive",
    "pk_staff_health_check",
    "uq_staff_health_check_staff_id_id",
    "fk_staff_health_check_staff_id_staff",
    "fk_staff_health_check_employment",
    "fk_staff_health_check_replacement",
    "fk_staff_health_check_created_by_account",
    "fk_staff_health_check_updated_by_account",
    "ck_staff_health_check_requirement_target_key_nonblank",
    "ck_staff_health_check_requirement_rule_version_nonblank",
    "ck_staff_health_check_requirement_status",
    "ck_staff_health_check_requirement_status_truth",
    "ck_staff_health_check_requirement_row_version_positive",
    "pk_staff_health_check_requirement",
    "fk_staff_health_check_requirement_staff_id_staff",
    "fk_staff_health_check_requirement_employment",
    "fk_staff_health_check_requirement_health_check",
    "fk_staff_health_check_requirement_replacement",
    "fk_staff_health_check_requirement_created_by_account",
    "fk_staff_health_check_requirement_updated_by_account",
}

VS5_TABLES = {"staff_quarterly_consultation"}
VS5_FACT_TABLES = set(VS5_TABLES)
VS5_FUNCTIONS: set[str] = set()
VS5_TRIGGERS: set[str] = set()
VS5_CONSTRAINTS = {
    "ck_staff_quarterly_consultation_quarter_no",
    "ck_staff_quarterly_consultation_status",
    "ck_staff_quarterly_consultation_status_truth",
    "ck_staff_quarterly_consultation_text_length",
    "ck_staff_quarterly_consultation_row_version_positive",
    "pk_staff_quarterly_consultation",
    "fk_staff_quarterly_consultation_staff_id_staff",
    "fk_staff_quarterly_consultation_replacement",
    "fk_staff_quarterly_consultation_created_by_account",
    "fk_staff_quarterly_consultation_updated_by_account",
}

VS6_TABLES = {"staff_legacy_mapping"}
VS6_FUNCTIONS: set[str] = set()
VS6_TRIGGERS: set[str] = set()
VS6_CONSTRAINTS = {
    "ck_staff_legacy_mapping_source_system_code_nonblank",
    "ck_staff_legacy_mapping_legacy_staff_key_nonblank",
    "ck_staff_legacy_mapping_row_version_positive",
    "pk_staff_legacy_mapping",
    "fk_staff_legacy_mapping_staff_id_staff",
    "fk_staff_legacy_mapping_replacement",
    "fk_staff_legacy_mapping_created_by_account",
    "fk_staff_legacy_mapping_updated_by_account",
}


def _verify_vs4_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in VS4_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1A-VS4 tables: {sorted(missing_tables)}")

    table_columns = {
        table_name: {
            str(row.column_name)
            for row in connection.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'erp' AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
        }
        for table_name in VS4_TABLES
    }
    required_columns = {
        "staff_health_check": {
            "id",
            "staff_id",
            "employment_id",
            "check_date",
            "check_type_code",
            "result_note",
            "created_by_account_id",
            "created_at_utc",
            "updated_by_account_id",
            "updated_at_utc",
            "row_version",
            "invalidated_at_utc",
            "replacement_health_check_id",
        },
        "staff_health_check_requirement": {
            "id",
            "staff_id",
            "employment_id",
            "target_key",
            "target_rule_version_code",
            "status",
            "health_check_id",
            "exempt_reason_text",
            "created_by_account_id",
            "created_at_utc",
            "updated_by_account_id",
            "updated_at_utc",
            "row_version",
            "invalidated_at_utc",
            "replacement_health_check_requirement_id",
        },
    }
    for table_name, expected in required_columns.items():
        if not expected.issubset(table_columns[table_name]):
            raise SystemExit(f"Invalid W1A-VS4 columns: {table_name}")
    for table_name in VS4_TABLES:
        if any(
            forbidden in table_columns[table_name]
            for forbidden in {"d_day", "task_id", "file_id", "attachment_id", "evidence_file_id"}
        ):
            raise SystemExit(f"Forbidden W1A-VS4 column: {table_name}")

    nullable_rows = connection.execute(
        text(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'erp'
              AND ((table_name = 'staff_health_check' AND column_name = 'check_date')
                   OR (table_name = 'staff_health_check_requirement'
                       AND column_name IN ('employment_id', 'health_check_id')))
            """
        )
    )
    nullable = {
        (str(row.table_name), str(row.column_name)): str(row.is_nullable) for row in nullable_rows
    }
    if nullable.get(("staff_health_check", "check_date")) != "NO":
        raise SystemExit("W1A-VS4 check_date must be required")
    if nullable.get(("staff_health_check_requirement", "employment_id")) != "YES":
        raise SystemExit("W1A-VS4 requirement employment_id must be nullable")
    if nullable.get(("staff_health_check_requirement", "health_check_id")) != "YES":
        raise SystemExit("W1A-VS4 requirement health_check_id must be nullable")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                """
            )
        ).scalars()
    )
    missing_constraints = sorted(VS4_CONSTRAINTS - constraints)
    if missing_constraints:
        raise SystemExit(f"Missing W1A-VS4 constraints: {missing_constraints}")

    definitions = {
        str(row.conname): str(row.definition)
        for row in connection.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conname = ANY(:constraint_names)
                """
            ),
            {"constraint_names": list(VS4_CONSTRAINTS)},
        )
    }
    truth_definition = definitions.get("ck_staff_health_check_requirement_status_truth", "")
    if not all(status in truth_definition for status in ("COMPLETE", "INCOMPLETE", "EXEMPT")):
        raise SystemExit("W1A-VS4 status truth table is incomplete")
    if "staff_id" not in definitions.get("fk_staff_health_check_requirement_health_check", ""):
        raise SystemExit("W1A-VS4 health fact same-staff FK is missing")
    if "staff_id" not in definitions.get("fk_staff_health_check_employment", ""):
        raise SystemExit("W1A-VS4 fact employment same-staff FK is missing")

    indexes = {
        str(row.indexname): str(row.indexdef)
        for row in connection.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'erp'
                  AND tablename = 'staff_health_check_requirement'
                """
            )
        )
    }
    active_index = indexes.get("uq_staff_health_check_requirement_active", "")
    if (
        "UNIQUE" not in active_index
        or "staff_id" not in active_index
        or "target_key" not in active_index
        or "invalidated_at_utc IS NULL" not in active_index
    ):
        raise SystemExit("W1A-VS4 active target unique index is invalid")

    trigger_rows = connection.execute(
        text(
            """
            SELECT tgname, tgdeferrable, tginitdeferred
            FROM pg_trigger
            WHERE tgrelid IN (
                'erp.staff_health_check'::regclass,
                'erp.staff_health_check_requirement'::regclass
            )
              AND NOT tgisinternal
            """
        )
    )
    triggers = {
        str(row.tgname): (bool(row.tgdeferrable), bool(row.tginitdeferred)) for row in trigger_rows
    }
    if not VS4_TRIGGERS.issubset(triggers):
        raise SystemExit(f"Missing W1A-VS4 triggers: {sorted(VS4_TRIGGERS - set(triggers))}")
    if any(triggers[name] != (True, True) for name in VS4_TRIGGERS):
        raise SystemExit("W1A-VS4 health guards must be deferred and deferrable")

    for table_name in sorted(VS4_FACT_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, True, True, False, False):
            raise SystemExit("W1A-VS4 fact ACL is not write-without-delete")
    for table_name in sorted(VS4_TABLES):
        privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_backup', :table_name, 'SELECT'),
                       has_table_privilege('erp_backup', :table_name, 'INSERT'),
                       has_table_privilege('erp_backup', :table_name, 'UPDATE'),
                       has_table_privilege('erp_backup', :table_name, 'DELETE'),
                       has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(privileges) != (True, False, False, False, False):
            raise SystemExit("W1A-VS4 backup ACL is not SELECT-only")


def _verify_vs5_contract(connection: Connection) -> None:
    if (
        connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": "erp.staff_quarterly_consultation"},
        ).scalar()
        is not True
    ):
        raise SystemExit("Missing W1A-VS5 quarterly consultation table")

    columns = {
        str(row.column_name): (str(row.data_type), str(row.is_nullable))
        for row in connection.execute(
            text(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND table_name = 'staff_quarterly_consultation'
                """
            )
        )
    }
    required_columns = {
        "id",
        "staff_id",
        "calendar_year",
        "quarter_no",
        "status",
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    }
    if not required_columns.issubset(columns):
        raise SystemExit("Invalid W1A-VS5 quarterly consultation columns")
    if any(
        forbidden in columns
        for forbidden in {
            "care_change_id",
            "care_change_case_id",
            "care_change_consultation_id",
            "file_id",
            "file_key",
            "attachment_id",
            "evidence_file_id",
            "evidence_id",
        }
    ):
        raise SystemExit("Forbidden W1A-VS5 quarterly consultation column")
    for name in (
        "calendar_year",
        "quarter_no",
        "status",
        "row_version",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
    ):
        if columns[name][1] != "NO":
            raise SystemExit(f"W1A-VS5 {name} must be NOT NULL")
    for name in (
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    ):
        if columns[name][1] != "YES":
            raise SystemExit(f"W1A-VS5 {name} must be nullable")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid = 'erp.staff_quarterly_consultation'::regclass
                """
            )
        ).scalars()
    )
    missing_constraints = sorted(VS5_CONSTRAINTS - constraints)
    if missing_constraints:
        raise SystemExit(f"Missing W1A-VS5 constraints: {missing_constraints}")

    definitions = {
        str(row.conname): str(row.definition)
        for row in connection.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid = 'erp.staff_quarterly_consultation'::regclass
                """
            )
        )
    }
    truth_definition = definitions["ck_staff_quarterly_consultation_status_truth"].upper()
    if not all(
        value in truth_definition
        for value in (
            "COMPLETE",
            "INCOMPLETE",
            "EXEMPT",
            "BTRIM",
            "CONTENT IS NOT NULL",
            "INCOMPLETE_REASON_TEXT IS NOT NULL",
            "EXEMPT_REASON_TEXT IS NOT NULL",
        )
    ):
        raise SystemExit("W1A-VS5 status truth table is incomplete")
    quarter_definition = definitions["ck_staff_quarterly_consultation_quarter_no"]
    if not all(value in quarter_definition for value in ("1", "2", "3", "4")):
        raise SystemExit("W1A-VS5 quarter check is invalid")
    if "staff_id" not in definitions["fk_staff_quarterly_consultation_staff_id_staff"]:
        raise SystemExit("W1A-VS5 staff foreign key is missing")

    active_index = connection.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'erp'
              AND tablename = 'staff_quarterly_consultation'
              AND indexname = 'uq_staff_quarterly_consultation_active'
            """
        )
    ).scalar_one_or_none()
    active_index_text = str(active_index or "").upper()
    if not all(
        value in active_index_text
        for value in (
            "UNIQUE",
            "STAFF_ID",
            "CALENDAR_YEAR",
            "QUARTER_NO",
            "INVALIDATED_AT_UTC IS NULL",
        )
    ):
        raise SystemExit("W1A-VS5 active unique index is invalid")

    privileges = connection.execute(
        text(
            """
            SELECT has_table_privilege('erp_app', 'erp.staff_quarterly_consultation', 'SELECT'),
                   has_table_privilege('erp_app', 'erp.staff_quarterly_consultation', 'INSERT'),
                   has_table_privilege('erp_app', 'erp.staff_quarterly_consultation', 'UPDATE'),
                   has_table_privilege('erp_app', 'erp.staff_quarterly_consultation', 'DELETE'),
                   has_table_privilege('erp_app', 'erp.staff_quarterly_consultation', 'TRUNCATE')
            """
        )
    ).one()
    if tuple(privileges) != (True, True, True, False, False):
        raise SystemExit("W1A-VS5 app ACL is not write-without-delete")
    backup_privileges = connection.execute(
        text(
            """
            SELECT has_table_privilege('erp_backup', 'erp.staff_quarterly_consultation', 'SELECT'),
                   has_table_privilege('erp_backup', 'erp.staff_quarterly_consultation', 'INSERT'),
                   has_table_privilege('erp_backup', 'erp.staff_quarterly_consultation', 'UPDATE'),
                   has_table_privilege('erp_backup', 'erp.staff_quarterly_consultation', 'DELETE'),
                   has_table_privilege('erp_backup', 'erp.staff_quarterly_consultation', 'TRUNCATE')
            """
        )
    ).one()
    if tuple(backup_privileges) != (True, False, False, False, False):
        raise SystemExit("W1A-VS5 backup ACL is not SELECT-only")


def _verify_vs6_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in VS6_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1A-VS6 tables: {sorted(missing_tables)}")

    columns = {
        str(row.column_name): (str(row.data_type), str(row.is_nullable))
        for row in connection.execute(
            text(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND table_name = 'staff_legacy_mapping'
                """
            )
        )
    }
    required = {
        "id",
        "source_system_code",
        "legacy_staff_key",
        "staff_id",
        "source_row_fingerprint",
        "invalidated_at_utc",
        "replacement_staff_legacy_mapping_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if not required.issubset(columns):
        raise SystemExit("Invalid W1A-VS6 staff legacy mapping columns")
    for name in (
        "source_system_code",
        "legacy_staff_key",
        "staff_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    ):
        if columns[name][1] != "NO":
            raise SystemExit(f"W1A-VS6 {name} must be NOT NULL")
    for name in (
        "source_row_fingerprint",
        "invalidated_at_utc",
        "replacement_staff_legacy_mapping_id",
    ):
        if columns[name][1] != "YES":
            raise SystemExit(f"W1A-VS6 {name} must be nullable")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid = 'erp.staff_legacy_mapping'::regclass
                """
            )
        ).scalars()
    )
    missing_constraints = sorted(VS6_CONSTRAINTS - constraints)
    if missing_constraints:
        raise SystemExit(f"Missing W1A-VS6 constraints: {missing_constraints}")

    definitions = {
        str(row.conname): str(row.definition)
        for row in connection.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid = 'erp.staff_legacy_mapping'::regclass
                """
            )
        )
    }
    if "staff_id" not in definitions["fk_staff_legacy_mapping_staff_id_staff"]:
        raise SystemExit("W1A-VS6 staff foreign key is missing")
    if "row_version > 0" not in definitions["ck_staff_legacy_mapping_row_version_positive"]:
        raise SystemExit("W1A-VS6 row version check is invalid")

    active_index = connection.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'erp'
              AND tablename = 'staff_legacy_mapping'
              AND indexname = 'uq_staff_legacy_mapping_active'
            """
        )
    ).scalar_one_or_none()
    active_index_text = str(active_index or "").upper()
    if not all(
        value in active_index_text
        for value in (
            "UNIQUE",
            "SOURCE_SYSTEM_CODE",
            "LEGACY_STAFF_KEY",
            "INVALIDATED_AT_UTC IS NULL",
        )
    ):
        raise SystemExit("W1A-VS6 active mapping unique index is invalid")

    app_privileges = connection.execute(
        text(
            """
            SELECT has_table_privilege('erp_app', 'erp.staff_legacy_mapping', 'SELECT'),
                   has_table_privilege('erp_app', 'erp.staff_legacy_mapping', 'INSERT'),
                   has_table_privilege('erp_app', 'erp.staff_legacy_mapping', 'UPDATE'),
                   has_table_privilege('erp_app', 'erp.staff_legacy_mapping', 'DELETE'),
                   has_table_privilege('erp_app', 'erp.staff_legacy_mapping', 'TRUNCATE')
            """
        )
    ).one()
    if tuple(app_privileges) != (True, True, True, False, False):
        raise SystemExit("W1A-VS6 app ACL is not write-without-delete")
    backup_privileges = connection.execute(
        text(
            """
            SELECT has_table_privilege('erp_backup', 'erp.staff_legacy_mapping', 'SELECT'),
                   has_table_privilege('erp_backup', 'erp.staff_legacy_mapping', 'INSERT'),
                   has_table_privilege('erp_backup', 'erp.staff_legacy_mapping', 'UPDATE'),
                   has_table_privilege('erp_backup', 'erp.staff_legacy_mapping', 'DELETE'),
                   has_table_privilege('erp_backup', 'erp.staff_legacy_mapping', 'TRUNCATE')
            """
        )
    ).one()
    if tuple(backup_privileges) != (True, False, False, False, False):
        raise SystemExit("W1A-VS6 backup ACL is not SELECT-only")


def _verify_w1b_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in W1B_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1B tables: {sorted(missing_tables)}")

    recipient_columns = _column_contract(connection, table_name="recipient")
    required_recipient_columns = {
        "id",
        "name",
        "birth_date",
        "sex_code",
        "recipient_no",
        "memo",
        "postal_code",
        "address",
        "home_phone",
        "mobile_phone",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if not required_recipient_columns.issubset(recipient_columns):
        raise SystemExit("Invalid W1B recipient columns")
    for name in ("name", "birth_date", "sex_code"):
        if recipient_columns[name][1] != "NO":
            raise SystemExit(f"W1B recipient.{name} must be NOT NULL")
    for name in (
        "recipient_no",
        "memo",
        "postal_code",
        "address",
        "home_phone",
        "mobile_phone",
    ):
        if recipient_columns[name][1] != "YES":
            raise SystemExit(f"W1B recipient.{name} must be nullable")

    payer_columns = _column_contract(connection, table_name="recipient_payer_snapshot")
    if "payer_type" in payer_columns or "guardian_id" in payer_columns:
        raise SystemExit("W1B payer snapshots must remain independent")
    for name in ("name", "phone", "address", "relationship_text"):
        expected_nullable = "NO" if name == "name" else "YES"
        if payer_columns.get(name, (None, None))[1] != expected_nullable:
            raise SystemExit(f"Invalid W1B payer snapshot {name} contract")

    mapping_columns = _column_contract(connection, table_name="recipient_legacy_mapping")
    for name in ("legacy_recipient_key", "legacy_attachment_key"):
        if mapping_columns.get(name, (None, None))[1] != "YES":
            raise SystemExit(f"W1B legacy mapping {name} must be nullable")

    generated_periods = {
        str(row.table_name): (str(row.udt_name), str(row.generation_expression))
        for row in connection.execute(
            text(
                """
                SELECT table_name, udt_name, generation_expression
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND column_name = 'effective_period'
                  AND table_name IN (
                      'recipient_guardian_primary_period',
                      'recipient_payer_snapshot'
                  )
                  AND is_generated = 'ALWAYS'
                """
            )
        )
    }
    if set(generated_periods) != {
        "recipient_guardian_primary_period",
        "recipient_payer_snapshot",
    }:
        raise SystemExit("W1B generated effective periods are missing")
    for udt_name, expression in generated_periods.values():
        normalized = expression.replace(" ", "").lower()
        if udt_name != "daterange" or not all(
            token in normalized for token in ("daterange(start_date,(end_date+1),'[)'",)
        ):
            raise SystemExit("W1B generated effective period is invalid")

    constraints = {
        str(row.conname): (str(row.contype), str(row.definition))
        for row in connection.execute(
            text(
                """
                SELECT conname, contype, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid IN (
                      'erp.recipient'::regclass,
                      'erp.recipient_guardian'::regclass,
                      'erp.recipient_guardian_primary_period'::regclass,
                      'erp.recipient_payer_snapshot'::regclass,
                      'erp.recipient_legacy_mapping'::regclass
                  )
                """
            )
        )
    }
    required_constraints = {
        "uq_recipient_recipient_no",
        "fk_recipient_guardian_primary_period_recipient_guardian",
        "ex_recipient_guardian_primary_period",
        "ex_recipient_payer_snapshot_period",
        "fk_recipient_guardian_primary_period_replacement",
        "fk_recipient_payer_snapshot_replacement",
        "fk_recipient_legacy_mapping_replacement",
    }
    missing_constraints = sorted(required_constraints - constraints.keys())
    if missing_constraints:
        raise SystemExit(f"Missing W1B constraints: {missing_constraints}")

    composite_fk = constraints["fk_recipient_guardian_primary_period_recipient_guardian"][1].lower()
    if not all(
        token in composite_fk
        for token in (
            "foreign key (recipient_id, guardian_id)",
            "recipient_guardian(recipient_id, id)",
        )
    ):
        raise SystemExit("W1B primary guardian composite foreign key is invalid")

    for name in (
        "ex_recipient_guardian_primary_period",
        "ex_recipient_payer_snapshot_period",
    ):
        constraint_type, definition = constraints[name]
        normalized = definition.lower()
        if constraint_type != "x" or not all(
            token in normalized
            for token in (
                "recipient_id with =",
                "effective_period with &&",
                "invalidated_at_utc is null",
            )
        ):
            raise SystemExit(f"W1B exclusion constraint is invalid: {name}")

    active_indexes = {
        str(row.indexname): str(row.indexdef).lower()
        for row in connection.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'erp'
                  AND tablename = 'recipient_legacy_mapping'
                  AND indexname IN (
                      'uq_recipient_legacy_mapping_active_recipient_key',
                      'uq_recipient_legacy_mapping_active_attachment_key'
                  )
                """
            )
        )
    }
    if set(active_indexes) != {
        "uq_recipient_legacy_mapping_active_recipient_key",
        "uq_recipient_legacy_mapping_active_attachment_key",
    }:
        raise SystemExit("W1B active legacy mapping indexes are missing")
    for name, key in (
        ("uq_recipient_legacy_mapping_active_recipient_key", "legacy_recipient_key"),
        ("uq_recipient_legacy_mapping_active_attachment_key", "legacy_attachment_key"),
    ):
        definition = active_indexes[name]
        if not all(
            token in definition
            for token in (
                "unique",
                "source_system_code",
                key,
                "invalidated_at_utc is null",
                f"{key} is not null",
            )
        ):
            raise SystemExit(f"W1B active mapping index is invalid: {name}")

    trigger_definition = connection.execute(
        text(
            """
            SELECT pg_get_triggerdef(t.oid)
            FROM pg_trigger t
            WHERE t.tgrelid = 'erp.recipient'::regclass
              AND t.tgname = 'bu_recipient_no_immutable'
              AND NOT t.tgisinternal
            """
        )
    ).scalar_one_or_none()
    function_definition = connection.execute(
        text(
            """
            SELECT pg_get_functiondef(p.oid)
            FROM pg_proc p
            WHERE p.pronamespace = 'erp'::regnamespace
              AND p.proname = 'fn_recipient_no_immutable'
            """
        )
    ).scalar_one_or_none()
    immutable_contract = str(function_definition or "").lower()
    if trigger_definition is None or not all(
        token in immutable_contract
        for token in (
            "old.recipient_no",
            "new.recipient_no",
            "is distinct from",
            "raise",
        )
    ):
        raise SystemExit("W1B recipient number immutability trigger is invalid")

    for table_name in W1B_TABLES:
        app_privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(app_privileges) != (True, True, True, False, False):
            raise SystemExit(f"W1B app ACL is invalid: {table_name}")
        backup_privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_backup', :table_name, 'SELECT'),
                       has_table_privilege('erp_backup', :table_name, 'INSERT'),
                       has_table_privilege('erp_backup', :table_name, 'UPDATE'),
                       has_table_privilege('erp_backup', :table_name, 'DELETE'),
                       has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(backup_privileges) != (True, False, False, False, False):
            raise SystemExit(f"W1B backup ACL is invalid: {table_name}")


def _verify_w1c_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in W1C_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1C tables: {sorted(missing_tables)}")

    all_columns = {
        str(row.column_name)
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND table_name = ANY(:table_names)
                """
            ),
            {"table_names": sorted(W1C_TABLES)},
        )
    }
    forbidden_columns = {
        "issued_date",
        "grade_changed_date",
        "benefit_rate",
        "monthly_maximum",
    }
    leaked_columns = sorted(forbidden_columns & all_columns)
    if leaked_columns:
        raise SystemExit(f"Forbidden W1C columns exist: {leaked_columns}")

    identity_columns = _column_contract(
        connection,
        table_name="recipient_certification_identity",
    )
    if identity_columns.get("recipient_id") != ("bigint", "NO"):
        raise SystemExit("W1C certification identity recipient_id is invalid")
    if identity_columns.get("certification_number") != ("text", "NO"):
        raise SystemExit("W1C certification identity number is invalid")

    period_columns = {
        table_name: _column_contract(connection, table_name=table_name)
        for table_name in (
            "recipient_certification_period",
            "recipient_grade_period",
            "recipient_benefit_period",
            "recipient_local_approval_amount_period",
        )
    }
    if period_columns["recipient_certification_period"].get("end_date", (None, None))[1] != "NO":
        raise SystemExit("W1C certification end_date must be required")
    if period_columns["recipient_grade_period"].get("end_date", (None, None))[1] != "NO":
        raise SystemExit("W1C grade end_date must be required")
    for table_name in (
        "recipient_benefit_period",
        "recipient_local_approval_amount_period",
    ):
        if period_columns[table_name].get("end_date", (None, None))[1] != "YES":
            raise SystemExit(f"W1C {table_name}.end_date must be nullable")
    if period_columns["recipient_local_approval_amount_period"].get("amount_krw") != (
        "bigint",
        "NO",
    ):
        raise SystemExit("W1C approval amount must be required bigint")

    generated_ranges = {
        (str(row.table_name), str(row.column_name)): (
            str(row.udt_name),
            str(row.generation_expression).replace(" ", "").lower(),
        )
        for row in connection.execute(
            text(
                """
                SELECT table_name, column_name, udt_name, generation_expression
                FROM information_schema.columns
                WHERE table_schema = 'erp'
                  AND table_name = ANY(:table_names)
                  AND is_generated = 'ALWAYS'
                """
            ),
            {
                "table_names": [
                    "recipient_certification_period",
                    "recipient_grade_period",
                    "recipient_benefit_period",
                    "recipient_local_approval_amount_period",
                ]
            },
        )
    }
    expected_ranges = {
        ("recipient_certification_period", "certification_period"),
        ("recipient_grade_period", "grade_period"),
        ("recipient_benefit_period", "benefit_period"),
        ("recipient_local_approval_amount_period", "approval_period"),
    }
    if set(generated_ranges) != expected_ranges:
        raise SystemExit("W1C generated dateranges are incomplete")
    for udt_name, expression in generated_ranges.values():
        if udt_name != "daterange" or not all(
            token in expression for token in ("daterange(start_date,(end_date+1),'[)'",)
        ):
            raise SystemExit("W1C generated daterange expression is invalid")

    constraints = {
        str(row.conname): (str(row.contype), str(row.definition).lower())
        for row in connection.execute(
            text(
                """
                SELECT conname, contype, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid IN (
                      'erp.recipient_certification_identity'::regclass,
                      'erp.recipient_certification_period'::regclass,
                      'erp.recipient_grade_period'::regclass,
                      'erp.recipient_benefit_period'::regclass,
                      'erp.recipient_local_approval_amount_period'::regclass
                  )
                """
            )
        )
    }
    required_constraints = {
        "pk_recipient_certification_identity",
        "uq_recipient_certification_identity_certification_number",
        "ck_recipient_certification_identity_number",
        "ex_recipient_certification_period",
        "fk_recipient_grade_period_certification",
        "ck_recipient_grade_period_grade_code",
        "ex_recipient_grade_period",
        "ck_recipient_benefit_period_benefit_code",
        "ex_recipient_benefit_period",
        "ck_recipient_local_approval_amount_period_amount",
        "ex_recipient_local_approval_amount_period",
    }
    missing_constraints = sorted(required_constraints - constraints.keys())
    if missing_constraints:
        raise SystemExit(f"Missing W1C constraints: {missing_constraints}")

    identity_check = constraints["ck_recipient_certification_identity_number"][1]
    if "^l[0-9]{10}$" not in identity_check:
        raise SystemExit("W1C canonical certification check is invalid")
    grade_check = constraints["ck_recipient_grade_period_grade_code"][1]
    if any(f"'{grade}'" not in grade_check for grade in ("1", "2", "3", "4", "5")):
        raise SystemExit("W1C grade check does not contain exact grades")
    benefit_check = constraints["ck_recipient_benefit_period_benefit_code"][1]
    benefit_codes = {
        "general",
        "basic_livelihood",
        "reduction_6",
        "reduction_9",
        "medical_6",
        "medical_9",
    }
    if any(f"'{code}'" not in benefit_check for code in benefit_codes):
        raise SystemExit("W1C benefit check does not contain the six codes")

    exclusion_columns = {
        "ex_recipient_certification_period": "certification_period with &&",
        "ex_recipient_grade_period": "grade_period with &&",
        "ex_recipient_benefit_period": "benefit_period with &&",
        "ex_recipient_local_approval_amount_period": "approval_period with &&",
    }
    for constraint_name, period_fragment in exclusion_columns.items():
        constraint_type, definition = constraints[constraint_name]
        if constraint_type != "x" or not all(
            fragment in definition
            for fragment in (
                "recipient_id with =",
                period_fragment,
                "invalidated_at_utc is null",
            )
        ):
            raise SystemExit(f"W1C exclusion is invalid: {constraint_name}")
    if "benefit_code with" in constraints["ex_recipient_benefit_period"][1]:
        raise SystemExit("W1C benefit exclusion must be recipient-wide across codes")

    containment_triggers = {
        str(row.tgname): (bool(row.tgdeferrable), bool(row.tginitdeferred))
        for row in connection.execute(
            text(
                """
                SELECT tgname, tgdeferrable, tginitdeferred
                FROM pg_trigger
                WHERE tgrelid IN (
                    'erp.recipient_certification_period'::regclass,
                    'erp.recipient_grade_period'::regclass
                )
                  AND NOT tgisinternal
                """
            )
        )
    }
    if containment_triggers != {
        "ct_recipient_grade_period_containment": (True, False),
        "ct_recipient_certification_grade_containment": (True, False),
    }:
        raise SystemExit("W1C containment triggers are invalid")

    grade_containment_function = connection.execute(
        text(
            """
            SELECT pg_get_functiondef(
                'erp.fn_w1c_assert_grade_containment()'::regprocedure
            )
            """
        )
    ).scalar_one()
    grade_containment_definition = str(grade_containment_function).lower()
    if not all(
        fragment in grade_containment_definition
        for fragment in (
            "from erp.recipient_certification_period",
            "for share",
            "ck_recipient_grade_period_containment",
        )
    ):
        raise SystemExit("W1C grade containment parent lock is invalid")

    identity_trigger = connection.execute(
        text(
            """
            SELECT pg_get_triggerdef(oid)
            FROM pg_trigger
            WHERE tgrelid = 'erp.recipient_certification_identity'::regclass
              AND tgname = 'bu_recipient_certification_number_immutable'
              AND NOT tgisinternal
            """
        )
    ).scalar_one_or_none()
    if (
        identity_trigger is None
        or "update of recipient_id, certification_number" not in str(identity_trigger).lower()
    ):
        raise SystemExit("W1C certification identity immutability trigger is invalid")
    identity_function = connection.execute(
        text(
            """
            SELECT pg_get_functiondef(
                'erp.fn_recipient_certification_number_immutable()'::regprocedure
            )
            """
        )
    ).scalar_one()
    identity_function_definition = str(identity_function).lower()
    if not all(
        fragment in identity_function_definition
        for fragment in (
            "old.recipient_id is distinct from new.recipient_id",
            "old.certification_number is distinct from new.certification_number",
            "ck_recipient_certification_identity_immutable",
        )
    ):
        raise SystemExit("W1C certification identity immutability function is invalid")

    for table_name in W1C_TABLES:
        app_privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(app_privileges) != (True, True, True, False, False):
            raise SystemExit(f"W1C app ACL is invalid: {table_name}")
        backup_privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_backup', :table_name, 'SELECT'),
                       has_table_privilege('erp_backup', :table_name, 'INSERT'),
                       has_table_privilege('erp_backup', :table_name, 'UPDATE'),
                       has_table_privilege('erp_backup', :table_name, 'DELETE'),
                       has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(backup_privileges) != (True, False, False, False, False):
            raise SystemExit(f"W1C backup ACL is invalid: {table_name}")


def _verify_table_acl(
    connection: Connection,
    *,
    tables: set[str],
    label: str,
) -> None:
    for table_name in sorted(tables):
        app_privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :table_name, 'SELECT'),
                       has_table_privilege('erp_app', :table_name, 'INSERT'),
                       has_table_privilege('erp_app', :table_name, 'UPDATE'),
                       has_table_privilege('erp_app', :table_name, 'DELETE'),
                       has_table_privilege('erp_app', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(app_privileges) != (True, True, True, False, False):
            raise SystemExit(f"{label} app ACL is not write-without-delete: {table_name}")
        backup_privileges = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_backup', :table_name, 'SELECT'),
                       has_table_privilege('erp_backup', :table_name, 'INSERT'),
                       has_table_privilege('erp_backup', :table_name, 'UPDATE'),
                       has_table_privilege('erp_backup', :table_name, 'DELETE'),
                       has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                """
            ),
            {"table_name": f"erp.{table_name}"},
        ).one()
        if tuple(backup_privileges) != (True, False, False, False, False):
            raise SystemExit(f"{label} backup ACL is not SELECT-only: {table_name}")


def _verify_w1d_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in W1D_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1D tables: {sorted(missing_tables)}")

    columns = _column_contract(connection, table_name="recipient_contract")
    required_columns = {
        "id",
        "recipient_id",
        "service_type_id",
        "start_date",
        "end_date",
        "contract_period",
        "invalidated_at_utc",
        "replacement_contract_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if not required_columns.issubset(columns):
        raise SystemExit("Invalid W1D recipient_contract columns")
    if columns["start_date"][1] != "NO":
        raise SystemExit("W1D recipient_contract.start_date must be required")
    if columns["end_date"][1] != "YES":
        raise SystemExit("W1D recipient_contract.end_date must be nullable")

    constraints = {
        str(row.conname): (str(row.contype), str(row.definition).lower())
        for row in connection.execute(
            text(
                """
                SELECT conname, contype, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid = 'erp.recipient_contract'::regclass
                """
            )
        )
    }
    missing_constraints = sorted(W1D_CONSTRAINTS - constraints.keys())
    if missing_constraints:
        raise SystemExit(f"Missing W1D constraints: {missing_constraints}")
    exclusion_type, exclusion_definition = constraints["ex_recipient_contract_same_service_period"]
    if exclusion_type != "x" or not all(
        fragment in exclusion_definition
        for fragment in (
            "recipient_id with =",
            "service_type_id with =",
            "contract_period with &&",
            "invalidated_at_utc is null",
        )
    ):
        raise SystemExit("W1D recipient_contract exclusion constraint is invalid")

    generated = connection.execute(
        text(
            """
            SELECT udt_name, generation_expression
            FROM information_schema.columns
            WHERE table_schema = 'erp'
              AND table_name = 'recipient_contract'
              AND column_name = 'contract_period'
              AND is_generated = 'ALWAYS'
            """
        )
    ).one_or_none()
    if generated is None or str(generated.udt_name) != "daterange":
        raise SystemExit("W1D contract_period generated daterange is missing")
    if (
        "daterange(start_date,(end_date+1),'[)'"
        not in str(generated.generation_expression).replace(" ", "").lower()
    ):
        raise SystemExit("W1D contract_period generation expression is invalid")

    triggers = {
        str(row.tgname)
        for row in connection.execute(
            text(
                """
                SELECT tgname
                FROM pg_trigger
                WHERE tgrelid = 'erp.recipient_contract'::regclass
                  AND NOT tgisinternal
                """
            )
        )
    }
    missing_triggers = sorted(W1D_TRIGGERS - triggers)
    if missing_triggers:
        raise SystemExit(f"Missing W1D triggers: {missing_triggers}")

    functions = set(
        connection.execute(
            text(
                """
                SELECT proname
                FROM pg_proc
                WHERE pronamespace = 'erp'::regnamespace
                  AND proname = ANY(:names)
                """
            ),
            {"names": sorted(W1D_FUNCTIONS)},
        ).scalars()
    )
    missing_functions = sorted(W1D_FUNCTIONS - functions)
    if missing_functions:
        raise SystemExit(f"Missing W1D functions: {missing_functions}")

    _verify_table_acl(connection, tables=W1D_TABLES, label="W1D")


def _verify_w1e_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in W1E_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing W1E tables: {sorted(missing_tables)}")

    columns = _column_contract(connection, table_name="care_assignment")
    required_columns = {
        "id",
        "recipient_contract_id",
        "staff_id",
        "employment_id",
        "assignment_kind",
        "family_relationship_text",
        "start_date",
        "end_date",
        "assignment_period",
        "invalidated_at_utc",
        "replacement_assignment_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if not required_columns.issubset(columns):
        raise SystemExit("Invalid W1E care_assignment columns")
    if columns["start_date"][1] != "NO":
        raise SystemExit("W1E care_assignment.start_date must be required")
    if columns["end_date"][1] != "YES":
        raise SystemExit("W1E care_assignment.end_date must be nullable")

    constraints = {
        str(row.conname): (str(row.contype), str(row.definition).lower())
        for row in connection.execute(
            text(
                """
                SELECT conname, contype, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                  AND conrelid = 'erp.care_assignment'::regclass
                """
            )
        )
    }
    missing_constraints = sorted(W1E_CONSTRAINTS - constraints.keys())
    if missing_constraints:
        raise SystemExit(f"Missing W1E constraints: {missing_constraints}")
    kind_type, kind_definition = constraints["ck_care_assignment_kind"]
    if kind_type != "c" or not all(token in kind_definition for token in ("'general'", "'family'")):
        raise SystemExit("W1E care_assignment kind check is invalid")
    exclusion_type, exclusion_definition = constraints[
        "ex_care_assignment_same_contract_staff_period"
    ]
    if exclusion_type != "x" or not all(
        fragment in exclusion_definition
        for fragment in (
            "recipient_contract_id with =",
            "staff_id with =",
            "assignment_period with &&",
            "invalidated_at_utc is null",
        )
    ):
        raise SystemExit("W1E care_assignment exclusion constraint is invalid")
    employment_fk = constraints["fk_care_assignment_employment"][1]
    if not all(token in employment_fk for token in ("foreign key (staff_id, employment_id)",)):
        raise SystemExit("W1E care_assignment employment composite FK is invalid")

    generated = connection.execute(
        text(
            """
            SELECT udt_name, generation_expression
            FROM information_schema.columns
            WHERE table_schema = 'erp'
              AND table_name = 'care_assignment'
              AND column_name = 'assignment_period'
              AND is_generated = 'ALWAYS'
            """
        )
    ).one_or_none()
    if generated is None or str(generated.udt_name) != "daterange":
        raise SystemExit("W1E assignment_period generated daterange is missing")
    if (
        "daterange(start_date,(end_date+1),'[)'"
        not in str(generated.generation_expression).replace(" ", "").lower()
    ):
        raise SystemExit("W1E assignment_period generation expression is invalid")

    trigger_contracts = {
        (
            str(row.tgname),
            str(row.table_name),
            str(row.function_name),
            bool(row.tgdeferrable),
            bool(row.tginitdeferred),
        )
        for row in connection.execute(
            text(
                """
                SELECT t.tgname,
                       table_class.relname AS table_name,
                       trigger_function.proname AS function_name,
                       t.tgdeferrable,
                       t.tginitdeferred
                FROM pg_trigger t
                JOIN pg_class table_class ON table_class.oid = t.tgrelid
                JOIN pg_namespace table_namespace
                  ON table_namespace.oid = table_class.relnamespace
                JOIN pg_proc trigger_function ON trigger_function.oid = t.tgfoid
                JOIN pg_namespace function_namespace
                  ON function_namespace.oid = trigger_function.pronamespace
                WHERE table_namespace.nspname = 'erp'
                  AND function_namespace.nspname = 'erp'
                  AND t.tgname = ANY(:names)
                  AND NOT t.tgisinternal
                """
            ),
            {"names": sorted(W1E_TRIGGER_CONTRACTS)},
        )
    }
    expected_trigger_contracts = {
        (trigger_name, table_name, function_name, True, True)
        for trigger_name, (table_name, function_name) in W1E_TRIGGER_CONTRACTS.items()
    }
    if trigger_contracts != expected_trigger_contracts:
        missing_triggers = sorted(expected_trigger_contracts - trigger_contracts)
        unexpected_triggers = sorted(trigger_contracts - expected_trigger_contracts)
        raise SystemExit(
            "W1E trigger contracts are invalid: "
            f"missing={missing_triggers}; unexpected={unexpected_triggers}"
        )

    functions = set(
        connection.execute(
            text(
                """
                SELECT proname
                FROM pg_proc
                WHERE pronamespace = 'erp'::regnamespace
                  AND proname = ANY(:names)
                """
            ),
            {"names": sorted(W1E_FUNCTIONS)},
        ).scalars()
    )
    missing_functions = sorted(W1E_FUNCTIONS - functions)
    if missing_functions:
        raise SystemExit(f"Missing W1E functions: {missing_functions}")

    _verify_table_acl(connection, tables=W1E_TABLES, label="W1E")


RECIPIENT_PLAN_NOTIFICATION_TABLES = {"recipient_plan_notification"}

# ---- recipient_plan_notification catalog snapshot ----

# Ownership: (table_owner, sequence_owner, owned_sequence)
_RECIPIENT_PLAN_NOTIFICATION_OWNERSHIP = (
    "erp_owner",
    "erp_owner",
    "erp.recipient_plan_notification_id_seq",
)

# Columns: ordered tuple of (name, format_type, attnotnull, attidentity, default_normalized)
# attidentity: '' for none, 'd' for GENERATED BY DEFAULT AS IDENTITY
_RECIPIENT_PLAN_NOTIFICATION_COLUMNS = (
    ("id", "bigint", True, "d", None),
    ("recipient_id", "bigint", True, "", None),
    ("notified_date", "date", True, "", None),
    ("invalidated_at_utc", "timestamp with time zone", False, "", None),
    ("created_by_account_id", "bigint", True, "", None),
    ("created_at_utc", "timestamp with time zone", True, "", "now()"),
    ("updated_by_account_id", "bigint", True, "", None),
    ("updated_at_utc", "timestamp with time zone", True, "", "now()"),
    ("row_version", "integer", True, "", "1"),
)

# 12-field constraint snapshot type alias used by expected dict, validator, and runtime dict.
_ConstraintSnapshot = tuple[
    str,  # contype
    str | None,  # definition (pg_get_constraintdef for p/c; None for f)
    tuple[str, ...],  # local_columns: ordered local column names
    str | None,  # ref_schema: referenced schema (None for p/c)
    str | None,  # ref_table: referenced table (None for p/c)
    tuple[str, ...],  # ref_columns: ordered referenced column names (empty for p/c)
    str | None,  # confdeltype: ON DELETE action code (None for p/c)
    str | None,  # confupdtype: ON UPDATE action code (None for p/c)
    str | None,  # confmatchtype: FK match type (None for p/c)
    bool,  # condeferrable
    bool,  # condeferred
    bool,  # convalidated
]

_RECIPIENT_PLAN_NOTIFICATION_CONSTRAINTS: dict[str, _ConstraintSnapshot] = {
    "pk_recipient_plan_notification": (
        "p",
        "PRIMARY KEY (id)",
        ("id",),
        None,
        None,
        (),
        None,
        None,
        None,
        False,
        False,
        True,
    ),
    "ck_recipient_plan_notification_row_version_positive": (
        "c",
        "CHECK (row_version > 0)",
        ("row_version",),
        None,
        None,
        (),
        None,
        None,
        None,
        False,
        False,
        True,
    ),
    "fk_recipient_plan_notification_created_by_account": (
        "f",
        None,
        ("created_by_account_id",),
        "erp",
        "user_account",
        ("id",),
        "r",
        "a",
        "s",
        False,
        False,
        True,
    ),
    "fk_recipient_plan_notification_recipient": (
        "f",
        None,
        ("recipient_id",),
        "erp",
        "recipient",
        ("id",),
        "r",
        "a",
        "s",
        False,
        False,
        True,
    ),
    "fk_recipient_plan_notification_updated_by_account": (
        "f",
        None,
        ("updated_by_account_id",),
        "erp",
        "user_account",
        ("id",),
        "r",
        "a",
        "s",
        False,
        False,
        True,
    ),
}

# Indexes: dict name -> (indisunique, indisprimary, indisvalid, indisready,
#                        normalized indexdef, normalized predicate)
_RECIPIENT_PLAN_NOTIFICATION_INDEXES: dict[str, tuple[bool, bool, bool, bool, str, str | None]] = {
    "pk_recipient_plan_notification": (
        True,
        True,
        True,
        True,
        (
            "CREATE UNIQUE INDEX pk_recipient_plan_notification "
            "ON erp.recipient_plan_notification USING btree (id)"
        ),
        None,
    ),
    "ix_recipient_plan_notification_notified_date": (
        False,
        False,
        True,
        True,
        (
            "CREATE INDEX ix_recipient_plan_notification_notified_date "
            "ON erp.recipient_plan_notification USING btree (notified_date)"
        ),
        None,
    ),
    "ix_recipient_plan_notification_recipient_id": (
        False,
        False,
        True,
        True,
        (
            "CREATE INDEX ix_recipient_plan_notification_recipient_id "
            "ON erp.recipient_plan_notification USING btree (recipient_id)"
        ),
        None,
    ),
}


def _normalize_recipient_plan_catalog_sql(sql_text: str | None) -> str | None:
    """Collapse whitespace only; keep semantic tokens."""
    if sql_text is None:
        return None
    return " ".join(sql_text.split())


def _verify_recipient_plan_notification_catalog_snapshot(
    ownership: tuple[str, str, str | None],
    columns: list[tuple[str, str, bool, str, str | None]],
    constraints: dict[str, _ConstraintSnapshot],
    indexes: dict[str, tuple[bool, bool, bool, bool, str, str | None]],
) -> None:
    """Pure validator: compare actual catalog snapshots against expected immutable values."""
    # Verify ownership
    if ownership != _RECIPIENT_PLAN_NOTIFICATION_OWNERSHIP:
        raise SystemExit(
            "recipient-plan-notification ownership mismatch: "
            f"expected {_RECIPIENT_PLAN_NOTIFICATION_OWNERSHIP}, got {ownership}"
        )

    # Verify columns
    if len(columns) != len(_RECIPIENT_PLAN_NOTIFICATION_COLUMNS):
        raise SystemExit(
            "recipient-plan-notification column count mismatch: "
            f"expected {len(_RECIPIENT_PLAN_NOTIFICATION_COLUMNS)}, got {len(columns)}"
        )

    for i, (expected, actual) in enumerate(
        zip(_RECIPIENT_PLAN_NOTIFICATION_COLUMNS, columns, strict=True)
    ):
        exp_name, exp_type, exp_notnull, exp_identity, exp_default = expected
        act_name, act_type, act_notnull, act_identity, act_default = actual

        if exp_name != act_name:
            raise SystemExit(
                f"recipient-plan-notification column name mismatch at position {i}: "
                f"expected {exp_name!r}, got {act_name!r}"
            )
        if exp_type != act_type:
            raise SystemExit(
                f"recipient-plan-notification column {exp_name} type mismatch: "
                f"expected {exp_type!r}, got {act_type!r}"
            )
        if exp_notnull != act_notnull:
            raise SystemExit(
                f"recipient-plan-notification column {exp_name} not-null mismatch: "
                f"expected {exp_notnull}, got {act_notnull}"
            )
        if exp_identity != act_identity:
            raise SystemExit(
                f"recipient-plan-notification column {exp_name} identity mismatch: "
                f"expected {exp_identity!r}, got {act_identity!r}"
            )
        if exp_default != act_default:
            raise SystemExit(
                f"recipient-plan-notification column {exp_name} default mismatch: "
                f"expected {exp_default!r}, got {act_default!r}"
            )

    # Verify constraints
    if set(constraints) != set(_RECIPIENT_PLAN_NOTIFICATION_CONSTRAINTS):
        missing = sorted(set(_RECIPIENT_PLAN_NOTIFICATION_CONSTRAINTS) - set(constraints))
        extra = sorted(set(constraints) - set(_RECIPIENT_PLAN_NOTIFICATION_CONSTRAINTS))
        raise SystemExit(
            f"recipient-plan-notification constraint set mismatch: missing={missing}, extra={extra}"
        )

    for name, expected_tuple in _RECIPIENT_PLAN_NOTIFICATION_CONSTRAINTS.items():
        (
            exp_contype,
            exp_def,
            exp_local_cols,
            exp_ref_schema,
            exp_ref_table,
            exp_ref_cols,
            exp_confdeltype,
            exp_confupdtype,
            exp_confmatchtype,
            exp_condeferrable,
            exp_condeferred,
            exp_convalidated,
        ) = expected_tuple
        (
            act_contype,
            act_def,
            act_local_cols,
            act_ref_schema,
            act_ref_table,
            act_ref_cols,
            act_confdeltype,
            act_confupdtype,
            act_confmatchtype,
            act_condeferrable,
            act_condeferred,
            act_convalidated,
        ) = constraints[name]

        if exp_contype != act_contype:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} type mismatch: "
                f"expected {exp_contype!r}, got {act_contype!r}"
            )

        if exp_def != act_def:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} definition mismatch: "
                f"expected {exp_def!r}, got {act_def!r}"
            )
        if exp_local_cols != act_local_cols:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} local columns mismatch: "
                f"expected {exp_local_cols!r}, got {act_local_cols!r}"
            )
        if exp_ref_schema != act_ref_schema:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} referenced schema mismatch: "
                f"expected {exp_ref_schema!r}, got {act_ref_schema!r}"
            )
        if exp_ref_table != act_ref_table:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} referenced table mismatch: "
                f"expected {exp_ref_table!r}, got {act_ref_table!r}"
            )
        if exp_ref_cols != act_ref_cols:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} referenced columns mismatch: "
                f"expected {exp_ref_cols!r}, got {act_ref_cols!r}"
            )
        if exp_confdeltype != act_confdeltype:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} delete action mismatch: "
                f"expected {exp_confdeltype!r}, got {act_confdeltype!r}"
            )
        if exp_confupdtype != act_confupdtype:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} update action mismatch: "
                f"expected {exp_confupdtype!r}, got {act_confupdtype!r}"
            )
        if exp_confmatchtype != act_confmatchtype:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} match type mismatch: "
                f"expected {exp_confmatchtype!r}, got {act_confmatchtype!r}"
            )
        if exp_condeferrable != act_condeferrable:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} deferrable mismatch: "
                f"expected {exp_condeferrable}, got {act_condeferrable}"
            )
        if exp_condeferred != act_condeferred:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} initially deferred mismatch: "
                f"expected {exp_condeferred}, got {act_condeferred}"
            )
        if exp_convalidated != act_convalidated:
            raise SystemExit(
                f"recipient-plan-notification constraint {name} validated mismatch: "
                f"expected {exp_convalidated}, got {act_convalidated}"
            )

    # Verify indexes
    if set(indexes) != set(_RECIPIENT_PLAN_NOTIFICATION_INDEXES):
        missing = sorted(set(_RECIPIENT_PLAN_NOTIFICATION_INDEXES) - set(indexes))
        extra = sorted(set(indexes) - set(_RECIPIENT_PLAN_NOTIFICATION_INDEXES))
        raise SystemExit(
            f"recipient-plan-notification index set mismatch: missing={missing}, extra={extra}"
        )

    for name, expected_idx_tuple in _RECIPIENT_PLAN_NOTIFICATION_INDEXES.items():
        exp_unique, exp_primary, exp_valid, exp_ready, exp_def, exp_pred = expected_idx_tuple
        actual_idx_tuple = indexes[name]
        act_unique, act_primary, act_valid, act_ready, act_def, act_pred = actual_idx_tuple

        if exp_unique != act_unique:
            raise SystemExit(
                f"recipient-plan-notification index {name} uniqueness mismatch: "
                f"expected {exp_unique}, got {act_unique}"
            )
        if exp_primary != act_primary:
            raise SystemExit(
                f"recipient-plan-notification index {name} primary mismatch: "
                f"expected {exp_primary}, got {act_primary}"
            )
        if exp_valid != act_valid:
            raise SystemExit(
                f"recipient-plan-notification index {name} validity mismatch: "
                f"expected {exp_valid}, got {act_valid}"
            )
        if exp_ready != act_ready:
            raise SystemExit(
                f"recipient-plan-notification index {name} readiness mismatch: "
                f"expected {exp_ready}, got {act_ready}"
            )
        if exp_def != act_def:
            raise SystemExit(
                f"recipient-plan-notification index {name} definition mismatch: "
                f"expected {exp_def!r}, got {act_def!r}"
            )
        if exp_pred != act_pred:
            raise SystemExit(
                f"recipient-plan-notification index {name} predicate mismatch: "
                f"expected {exp_pred!r}, got {act_pred!r}"
            )


# Canonical complete expressions for recipient_status (whitespace-normalized only).
# Rejects cast-stripping false positives (e.g. 'ACTIVE'::text OR TRUE) and token-set
# false positives (e.g. CHECK (... IN (...) OR TRUE) / extra values / extra clauses).
_RECIPIENT_STATUS_CANONICAL_DEFAULTS = frozenset(
    {
        "'ACTIVE'::text",
        "'ACTIVE'",
        "('ACTIVE'::text)",
        "('ACTIVE')",
    }
)
_RECIPIENT_STATUS_CANONICAL_CHECK_DEFS = frozenset(
    {
        "CHECK (recipient_status IN ('ACTIVE', 'ENDED', 'WAITING'))",
        "CHECK (recipient_status IN ('ACTIVE'::text, 'ENDED'::text, 'WAITING'::text))",
        "CHECK ((recipient_status = ANY (ARRAY['ACTIVE'::text, 'ENDED'::text, 'WAITING'::text])))",
        "CHECK (recipient_status = ANY (ARRAY['ACTIVE'::text, 'ENDED'::text, 'WAITING'::text]))",
    }
)


def _normalize_recipient_status_sql(sql_text: str | None) -> str | None:
    """Collapse whitespace only; keep casts and every semantic token."""
    if sql_text is None:
        return None
    return " ".join(str(sql_text).split())


def _verify_recipient_guardian_email_contract(connection: Connection) -> None:
    """Assert recipient_guardian.email is nullable text for revision 0017.

    Marker RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK is the head success signal.
    """
    col = (
        connection.execute(
            text(
                """
            SELECT is_nullable, data_type, udt_name
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = 'recipient_guardian'
               AND column_name = 'email'
            """
            )
        )
        .mappings()
        .one_or_none()
    )
    if col is None:
        raise SystemExit("email column missing on erp.recipient_guardian")
    if col["is_nullable"] != "YES":
        raise SystemExit("recipient_guardian.email must be NULLABLE")
    # text
    data_type = str(col["data_type"] or "").lower()
    udt_name = str(col["udt_name"] or "").lower()
    if "text" not in data_type and udt_name not in {"text"}:
        raise SystemExit(
            f"recipient_guardian.email must be TEXT; got data_type={col['data_type']!r} "
            f"udt_name={col['udt_name']!r}"
        )


def _verify_recipient_payer_guardian_contract(connection: Connection) -> None:
    """Assert recipient.payer_guardian_id + same-recipient composite FK for revision 0016.

    NULL means recipient self is payer. Non-null values must reference a guardian
    of the same recipient via composite FK
    (recipient.id, recipient.payer_guardian_id) -> (guardian.recipient_id, guardian.id).
    Marker RECIPIENT_PAYER_GUARDIAN_DB_POSTCHECK_OK is the head success signal.
    """
    col = (
        connection.execute(
            text(
                """
            SELECT is_nullable, data_type, udt_name
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = 'recipient'
               AND column_name = 'payer_guardian_id'
            """
            )
        )
        .mappings()
        .one_or_none()
    )
    if col is None:
        raise SystemExit("payer_guardian_id column missing on erp.recipient")
    if col["is_nullable"] != "YES":
        raise SystemExit("payer_guardian_id must be NULLABLE (NULL = self payer)")
    # bigint / int8
    data_type = str(col["data_type"] or "").lower()
    udt_name = str(col["udt_name"] or "").lower()
    if "bigint" not in data_type and udt_name not in {"int8", "bigint"}:
        raise SystemExit(
            f"payer_guardian_id must be BIGINT; got data_type={col['data_type']!r} "
            f"udt_name={col['udt_name']!r}"
        )

    fk_row = (
        connection.execute(
            text(
                """
            SELECT
                c.conname,
                c.confdeltype,
                pg_get_constraintdef(c.oid, true) AS definition,
                ARRAY(
                    SELECT a.attname
                      FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                      JOIN pg_attribute a
                        ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                     ORDER BY k.ord
                ) AS src_cols,
                ARRAY(
                    SELECT a.attname
                      FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                      JOIN pg_attribute a
                        ON a.attrelid = c.confrelid AND a.attnum = k.attnum
                     ORDER BY k.ord
                ) AS ref_cols,
                confrel.relname AS ref_table
              FROM pg_constraint c
              JOIN pg_class confrel ON confrel.oid = c.confrelid
             WHERE c.conrelid = 'erp.recipient'::regclass
               AND c.contype = 'f'
               AND c.conname = 'fk_recipient_payer_guardian_same_recipient'
            """
            )
        )
        .mappings()
        .one_or_none()
    )
    if fk_row is None:
        raise SystemExit(
            "fk_recipient_payer_guardian_same_recipient foreign key missing on erp.recipient"
        )
    if str(fk_row["ref_table"]) != "recipient_guardian":
        raise SystemExit(
            "payer_guardian composite FK must reference recipient_guardian; "
            f"got {fk_row['ref_table']!r}"
        )
    src_cols = [str(name) for name in (fk_row["src_cols"] or [])]
    ref_cols = [str(name) for name in (fk_row["ref_cols"] or [])]
    if src_cols != ["id", "payer_guardian_id"] or ref_cols != ["recipient_id", "id"]:
        raise SystemExit(
            "payer_guardian composite FK columns must be "
            "(id, payer_guardian_id) -> (recipient_id, id); "
            f"got {src_cols} -> {ref_cols}"
        )
    # confdeltype: a=NO ACTION, r=RESTRICT, c=CASCADE, n=SET NULL, d=SET DEFAULT
    if str(fk_row["confdeltype"]) not in {"r", "a"}:
        # RESTRICT and NO ACTION are equivalent for our purpose; require non-cascade.
        raise SystemExit(
            "fk_recipient_payer_guardian_same_recipient must be ON DELETE RESTRICT "
            f"(or NO ACTION); got confdeltype={fk_row['confdeltype']!r}"
        )
    definition = str(fk_row["definition"] or "")
    if "recipient_guardian" not in definition:
        raise SystemExit(
            f"fk_recipient_payer_guardian_same_recipient definition invalid: {definition!r}"
        )


def _verify_recipient_status_tag_contract(connection: Connection) -> None:
    """Assert recipient.recipient_status column contract for revision 0015.

    Proves the complete canonical normalized default expression is exactly ACTIVE,
    column is NOT NULL, the complete CHECK predicate is exactly
    {ACTIVE, ENDED, WAITING}, and the constraint is convalidated.
    Marker RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK remains the restore-drill success signal.
    """
    col = (
        connection.execute(
            text(
                """
            SELECT is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = 'recipient'
               AND column_name = 'recipient_status'
            """
            )
        )
        .mappings()
        .one_or_none()
    )
    if col is None:
        raise SystemExit("recipient_status column missing on erp.recipient")
    if col["is_nullable"] != "NO":
        raise SystemExit("recipient_status must be NOT NULL")
    default_raw = col["column_default"]
    if default_raw is None:
        raise SystemExit("recipient_status server default must be exactly ACTIVE")
    # Complete expression only — no cast stripping, no suffix tolerance.
    default_norm = _normalize_recipient_status_sql(str(default_raw))
    if default_norm not in _RECIPIENT_STATUS_CANONICAL_DEFAULTS:
        raise SystemExit(
            "recipient_status server default must be exactly ACTIVE "
            f"(canonical complete expression); got {default_raw!r}"
        )
    check_row = (
        connection.execute(
            text(
                """
            SELECT pg_get_constraintdef(oid, true) AS definition, convalidated
              FROM pg_constraint
             WHERE conrelid = 'erp.recipient'::regclass
               AND contype = 'c'
               AND conname = 'ck_recipient_recipient_status'
            """
            )
        )
        .mappings()
        .one_or_none()
    )
    if check_row is None:
        raise SystemExit("ck_recipient_recipient_status check constraint missing")
    if check_row["convalidated"] is not True:
        raise SystemExit("ck_recipient_recipient_status must be validated/convalidated")
    definition = str(check_row["definition"])
    definition_norm = _normalize_recipient_status_sql(definition)
    if definition_norm not in _RECIPIENT_STATUS_CANONICAL_CHECK_DEFS:
        raise SystemExit(
            "ck_recipient_recipient_status must accept exactly "
            f"ACTIVE,ENDED,WAITING (canonical complete CHECK); got {definition!r}"
        )


def _verify_recipient_plan_notification_contract(connection: Connection) -> None:
    missing_tables = {
        table_name
        for table_name in RECIPIENT_PLAN_NOTIFICATION_TABLES
        if connection.execute(
            text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"erp.{table_name}"},
        ).scalar()
        is not True
    }
    if missing_tables:
        raise SystemExit(f"Missing recipient-plan-notification tables: {sorted(missing_tables)}")

    # Ownership snapshot
    ownership_row = connection.execute(
        text(
            """
            SELECT
                pg_get_userbyid(tbl.relowner) AS table_owner,
                pg_get_userbyid(seq.relowner) AS sequence_owner,
                pg_get_serial_sequence('erp.recipient_plan_notification', 'id') AS owned_sequence
            FROM pg_class tbl
            JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
            LEFT JOIN pg_class seq ON seq.relnamespace = ns.oid
                AND seq.relname = 'recipient_plan_notification_id_seq'
                AND seq.relkind = 'S'
            WHERE ns.nspname = 'erp'
              AND tbl.relname = 'recipient_plan_notification'
              AND tbl.relkind = 'r'
            """
        )
    ).one()
    table_owner: str = ownership_row.table_owner or ""
    sequence_owner: str = ownership_row.sequence_owner or ""
    owned_sequence: str | None = ownership_row.owned_sequence
    ownership: tuple[str, str, str | None] = (table_owner, sequence_owner, owned_sequence)

    # Columns snapshot
    column_rows = connection.execute(
        text(
            """
            SELECT
                a.attname,
                format_type(a.atttypid, a.atttypmod) AS data_type,
                a.attnotnull,
                a.attidentity,
                pg_get_expr(d.adbin, d.adrelid) AS default_expr
            FROM pg_attribute a
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attrelid = 'erp.recipient_plan_notification'::regclass
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
    )
    columns: list[tuple[str, str, bool, str, str | None]] = [
        (
            str(row.attname),
            str(row.data_type),
            bool(row.attnotnull),
            str(row.attidentity),
            _normalize_recipient_plan_catalog_sql(row.default_expr),
        )
        for row in column_rows
    ]

    # Constraints snapshot: search_path-independent structured FK resolution
    constraint_rows = connection.execute(
        text(
            """
            SELECT
                c.conname,
                c.contype,
                CASE WHEN c.contype = 'f' THEN NULL
                     ELSE pg_get_constraintdef(c.oid, true)
                END AS definition,
                c.confdeltype,
                c.confupdtype,
                c.confmatchtype,
                c.condeferrable,
                c.condeferred,
                c.convalidated,
                -- ordered local column names via pg_attribute with ordinality
                ARRAY(
                    SELECT la.attname
                    FROM unnest(c.conkey) WITH ORDINALITY AS kc(attnum, ord)
                    JOIN pg_attribute la
                      ON la.attrelid = c.conrelid
                     AND la.attnum = kc.attnum
                    ORDER BY kc.ord
                ) AS local_columns,
                -- referenced schema (NULL for non-FK)
                (SELECT rn.nspname
                 FROM pg_class rc
                 JOIN pg_namespace rn ON rn.oid = rc.relnamespace
                 WHERE c.contype = 'f' AND rc.oid = c.confrelid
                ) AS ref_schema,
                -- referenced table (NULL for non-FK)
                (SELECT rc.relname
                 FROM pg_class rc
                 WHERE c.contype = 'f' AND rc.oid = c.confrelid
                ) AS ref_table,
                -- ordered referenced column names via pg_attribute with ordinality
                ARRAY(
                    SELECT ra.attname
                    FROM unnest(c.confkey) WITH ORDINALITY AS kc(attnum, ord)
                    JOIN pg_attribute ra
                      ON ra.attrelid = c.confrelid
                     AND ra.attnum = kc.attnum
                    WHERE c.contype = 'f'
                    ORDER BY kc.ord
                ) AS ref_columns
            FROM pg_constraint c
            WHERE c.conrelid = 'erp.recipient_plan_notification'::regclass
            ORDER BY c.conname
            """
        )
    )
    constraints: dict[str, _ConstraintSnapshot] = {}
    for row in constraint_rows:
        conname = str(row.conname)
        contype = str(row.contype)
        definition = _normalize_recipient_plan_catalog_sql(row.definition)
        local_columns: tuple[str, ...] = tuple(str(col) for col in (row.local_columns or []))
        ref_schema: str | None = str(row.ref_schema) if row.ref_schema else None
        ref_table: str | None = str(row.ref_table) if row.ref_table else None
        ref_columns: tuple[str, ...] = tuple(str(col) for col in (row.ref_columns or []))
        confdeltype: str | None = (
            str(row.confdeltype) if contype == "f" and row.confdeltype else None
        )
        confupdtype: str | None = (
            str(row.confupdtype) if contype == "f" and row.confupdtype else None
        )
        confmatchtype: str | None = (
            str(row.confmatchtype) if contype == "f" and row.confmatchtype else None
        )
        condeferrable: bool = bool(row.condeferrable)
        condeferred: bool = bool(row.condeferred)
        convalidated: bool = bool(row.convalidated)
        if contype != "f" and definition is None:
            raise SystemExit(
                f"recipient-plan-notification constraint {conname!r} definition missing"
            )
        constraints[conname] = (
            contype,
            definition,
            local_columns,
            ref_schema,
            ref_table,
            ref_columns,
            confdeltype,
            confupdtype,
            confmatchtype,
            condeferrable,
            condeferred,
            convalidated,
        )

    # Indexes snapshot
    index_rows = connection.execute(
        text(
            """
            SELECT
                idx.relname AS index_name,
                i.indisunique,
                i.indisprimary,
                i.indisvalid,
                i.indisready,
                pg_get_indexdef(idx.oid) AS indexdef,
                pg_get_expr(i.indpred, i.indrelid) AS predicate
            FROM pg_index i
            JOIN pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_class tbl ON tbl.oid = i.indrelid
            JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = 'erp'
              AND tbl.relname = 'recipient_plan_notification'
            ORDER BY idx.relname
            """
        )
    )
    indexes: dict[str, tuple[bool, bool, bool, bool, str, str | None]] = {}
    for row in index_rows:
        indexdef = _normalize_recipient_plan_catalog_sql(row.indexdef)
        if indexdef is None:
            raise SystemExit(
                f"recipient-plan-notification index {row.index_name!r} definition missing"
            )
        indexes[str(row.index_name)] = (
            bool(row.indisunique),
            bool(row.indisprimary),
            bool(row.indisvalid),
            bool(row.indisready),
            indexdef,
            _normalize_recipient_plan_catalog_sql(row.predicate),
        )

    _verify_recipient_plan_notification_catalog_snapshot(ownership, columns, constraints, indexes)

    user_triggers = (
        connection.execute(
            text(
                """
            SELECT tgname
            FROM pg_trigger
            WHERE tgrelid = 'erp.recipient_plan_notification'::regclass
              AND NOT tgisinternal
            """
            )
        )
        .scalars()
        .all()
    )
    if user_triggers:
        raise SystemExit(
            f"recipient-plan-notification must have no user triggers: {list(user_triggers)}"
        )

    app_privileges = connection.execute(
        text(
            """
            SELECT has_table_privilege('erp_app', 'erp.recipient_plan_notification', 'SELECT'),
                   has_table_privilege('erp_app', 'erp.recipient_plan_notification', 'INSERT'),
                   has_table_privilege('erp_app', 'erp.recipient_plan_notification', 'UPDATE'),
                   has_table_privilege('erp_app', 'erp.recipient_plan_notification', 'DELETE'),
                   has_table_privilege('erp_app', 'erp.recipient_plan_notification', 'TRUNCATE')
            """
        )
    ).one()
    if tuple(app_privileges) != (True, True, True, False, False):
        raise SystemExit("recipient-plan-notification app ACL is not write-without-delete")

    backup_privileges = connection.execute(
        text(
            """
            SELECT has_table_privilege('erp_backup', 'erp.recipient_plan_notification', 'SELECT'),
                   has_table_privilege('erp_backup', 'erp.recipient_plan_notification', 'INSERT'),
                   has_table_privilege('erp_backup', 'erp.recipient_plan_notification', 'UPDATE'),
                   has_table_privilege('erp_backup', 'erp.recipient_plan_notification', 'DELETE'),
                   has_table_privilege('erp_backup', 'erp.recipient_plan_notification', 'TRUNCATE')
            """
        )
    ).one()
    if tuple(backup_privileges) != (True, False, False, False, False):
        raise SystemExit("recipient-plan-notification backup ACL is not SELECT-only")

    app_seq = connection.execute(
        text(
            """
            SELECT has_sequence_privilege(
                       'erp_app', 'erp.recipient_plan_notification_id_seq', 'USAGE'
                   ),
                   has_sequence_privilege(
                       'erp_app', 'erp.recipient_plan_notification_id_seq', 'SELECT'
                   )
            """
        )
    ).one()
    if tuple(app_seq) != (True, True):
        raise SystemExit("recipient-plan-notification app sequence ACL is invalid")

    backup_seq = connection.execute(
        text(
            """
            SELECT has_sequence_privilege(
                       'erp_backup', 'erp.recipient_plan_notification_id_seq', 'USAGE'
                   ),
                   has_sequence_privilege(
                       'erp_backup', 'erp.recipient_plan_notification_id_seq', 'SELECT'
                   )
            """
        )
    ).one()
    if tuple(backup_seq) != (False, True):
        raise SystemExit("recipient-plan-notification backup sequence ACL is invalid")


if __name__ == "__main__":
    main()
