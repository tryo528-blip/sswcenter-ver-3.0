"""R0 W2 service plan notice read-only retirement.

Revision ID: 20260812_0019_r0_w2_read_only
Revises: 20260809_0018_w2_service_plan_notice
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260812_0019_r0_w2_read_only"
down_revision: str | None = "20260809_0018_w2_service_plan_notice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail closed if any of the five W2 guard triggers is missing (no IF EXISTS).
    op.execute(
        """
        DROP TRIGGER ct_service_plan_notice_before_contract_start
            ON erp.recipient_service_plan_notice;
        DROP TRIGGER ct_service_plan_notice_within_contract
            ON erp.recipient_service_plan_notice;
        DROP TRIGGER ct_service_plan_notice_within_certification
            ON erp.recipient_service_plan_notice;
        DROP TRIGGER ct_recipient_contract_service_plan_reverse_guard
            ON erp.recipient_contract;
        DROP TRIGGER ct_recipient_certification_period_service_plan_reverse_guard
            ON erp.recipient_certification_period;
        """
    )

    # Conditional revoke: fresh/dev without erp_app must not fail.
    op.execute(
        """
        DO $$
        BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='erp_app') THEN
          REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON TABLE erp.recipient_service_plan_notice FROM erp_app;
          REVOKE USAGE, UPDATE
            ON SEQUENCE erp.recipient_service_plan_notice_id_seq FROM erp_app;
        END IF;
        END $$
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260812_0019_r0_w2_read_only is a canonical forward-only migration; "
        "operational rollback is pre-upgrade backup restore"
    )
