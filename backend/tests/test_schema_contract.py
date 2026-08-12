from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import models as wave0_models  # noqa: F401
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
    "erp.permission_definition",
    "erp.recipient",
    "erp.recipient_benefit_period",
    "erp.recipient_certification_identity",
    "erp.recipient_certification_period",
    "erp.recipient_contract",
    "erp.recipient_grade_period",
    "erp.recipient_guardian",
    "erp.recipient_guardian_primary_period",
    "erp.recipient_legacy_mapping",
    "erp.recipient_local_approval_amount_period",
    "erp.recipient_payer_snapshot",
    "erp.recipient_plan_notification",
    "erp.license_type",
    "erp.service_group",
    "erp.service_type",
    "erp.staff",
    "erp.staff_employment",
    "erp.staff_legacy_mapping",
    "erp.staff_license",
    "erp.staff_health_check",
    "erp.staff_health_check_requirement",
    "erp.staff_onboarding_training",
    "erp.staff_operational_role_period",
    "erp.staff_periodic_training_status",
    "erp.staff_position_period",
    "erp.staff_quarterly_consultation",
    "erp.staff_service_qualification_period",
    "erp.staff_sensitive_identity",
    "erp.system_run",
    "erp.system_run_event",
    "erp.training_course",
    "erp.user_account",
}


def test_current_metadata_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_CURRENT_TABLES


def test_current_schema_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()

    for table in Base.metadata.sorted_tables:
        create_table_sql = str(CreateTable(table).compile(dialect=dialect))
        assert "CREATE TABLE erp." in create_table_sql
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))
