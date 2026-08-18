from collections.abc import Callable
from typing import cast

from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import models as wave0_models  # noqa: F401
from app.db import w2_models as current_w2_models  # noqa: F401
from app.db import w3_models as current_w3_models  # noqa: F401
from app.db.base import Base

EXPECTED_CURRENT_TABLES = {
    "erp.access_event",
    "erp.account_permission",
    "erp.audit_event",
    "erp.auth_event",
    "erp.auth_rate_limit_bucket",
    "erp.auth_session",
    "erp.business_number_counter",
    "erp.care_assignment",
    "erp.center",
    "erp.installation_state",
    "erp.license_type",
    "erp.monthly_professional_assignment",
    "erp.permission_definition",
    "erp.recipient",
    "erp.recipient_benefit_period",
    "erp.recipient_certification_identity",
    "erp.recipient_certification_period",
    "erp.recipient_contract",
    "erp.recipient_guardian",
    "erp.recipient_legacy_mapping",
    "erp.recipient_local_approval_amount_period",
    "erp.recipient_plan_notification",
    "erp.recipient_service_plan_notice",
    "erp.service_group",
    "erp.service_type",
    "erp.staff",
    "erp.staff_employment",
    "erp.staff_health_check",
    "erp.staff_legacy_mapping",
    "erp.staff_license",
    "erp.staff_onboarding_training",
    "erp.staff_operational_role_period",
    "erp.staff_periodic_training_status",
    "erp.staff_position_period",
    "erp.staff_quarterly_consultation",
    "erp.staff_sensitive_identity",
    "erp.staff_service_qualification_period",
    "erp.system_run",
    "erp.system_run_event",
    "erp.training_course",
    "erp.user_account",
    "erp.w2_official_work_card",
    "erp.w2_personal_todo",
    "erp.w2_personal_todo_list",
    "erp.w2_schedule",
    "erp.w2_schedule_month_control",
    "erp.w2_schedule_staff",
    "erp.w2_service_plan_notice",
    "erp.w3_import_attempt",
    "erp.w3_import_run",
    "erp.w3_private_content",
    "erp.w3_source_receipt",
    "erp.w3_source_row",
    "erp.w3_source_snapshot",
}


def test_current_metadata_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_CURRENT_TABLES


def test_current_schema_compiles_for_postgresql() -> None:
    dialect_factory = cast(Callable[[], Dialect], postgresql.dialect)
    dialect = dialect_factory()

    for table in Base.metadata.sorted_tables:
        create_table_sql = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE erp." in create_table_sql
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))
