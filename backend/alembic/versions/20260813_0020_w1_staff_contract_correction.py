"""Correct W1 staff health-check and quarterly-consultation contracts.

Revision ID: 20260813_0020_w1_staff_contract_correction
Revises: 20260812_0019_r0_w2_read_only
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0020_w1_staff_contract_correction"
down_revision: str | None = "20260812_0019_r0_w2_read_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assert_exact_training_catalog() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            actual_codes text[];
        BEGIN
            SELECT array_agg(code ORDER BY sort_order)
              INTO actual_codes
              FROM erp.training_course;

            IF actual_codes IS DISTINCT FROM ARRAY[
                'NEW_HIRE_ORIENTATION',
                'ELDER_RIGHTS',
                'DISABLED_ABUSE',
                'ELDER_ABUSE',
                'SEXUAL_HARASSMENT',
                'WORKPLACE_BULLYING',
                'PRIVACY',
                'CONTINUING_EDUCATION'
            ]::text[] THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'W1_STAFF_TRAINING_CATALOG_MUST_HAVE_EXACTLY_EIGHT_COURSES';
            END IF;
        END
        $$;
        """
    )

def _remove_health_check_requirement_ledger() -> None:
    op.execute(
        """
        DROP TRIGGER ct_staff_health_check_requirement_reverse_guard
            ON erp.staff_health_check;
        DROP TRIGGER ct_staff_health_check_requirement_fact_guard
            ON erp.staff_health_check_requirement;
        DROP FUNCTION erp.fn_staff_health_check_requirement_reverse_guard();
        DROP FUNCTION erp.fn_staff_health_check_requirement_fact_guard();
        """
    )
    op.drop_index(
        "uq_staff_health_check_requirement_active",
        table_name="staff_health_check_requirement",
        schema="erp",
    )
    op.drop_table("staff_health_check_requirement", schema="erp")


def _reduce_health_check_to_date_fact() -> None:
    op.drop_constraint(
        "fk_staff_health_check_employment",
        "staff_health_check",
        schema="erp",
        type_="foreignkey",
    )
    op.drop_column("staff_health_check", "employment_id", schema="erp")
    op.drop_column("staff_health_check", "check_type_code", schema="erp")
    op.drop_column("staff_health_check", "result_note", schema="erp")


def _reduce_quarterly_consultation_to_toggle() -> None:
    op.drop_constraint(
        "fk_staff_quarterly_consultation_replacement",
        "staff_quarterly_consultation",
        schema="erp",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_staff_quarterly_consultation_active",
        table_name="staff_quarterly_consultation",
        schema="erp",
    )
    op.add_column(
        "staff_quarterly_consultation",
        sa.Column("completed", sa.Boolean(), nullable=True),
        schema="erp",
    )
    op.execute(
        """
        UPDATE erp.staff_quarterly_consultation
           SET completed = (status = 'COMPLETE');

        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY staff_id, calendar_year, quarter_no
                       ORDER BY (invalidated_at_utc IS NULL) DESC,
                                updated_at_utc DESC,
                                id DESC
                   ) AS row_rank
              FROM erp.staff_quarterly_consultation
        )
        DELETE FROM erp.staff_quarterly_consultation AS consultation
         USING ranked
         WHERE consultation.id = ranked.id
           AND ranked.row_rank > 1;
        """
    )

    op.drop_constraint(
        op.f("ck_staff_quarterly_consultation_status_truth"),
        "staff_quarterly_consultation",
        schema="erp",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_staff_quarterly_consultation_text_length"),
        "staff_quarterly_consultation",
        schema="erp",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_staff_quarterly_consultation_status"),
        "staff_quarterly_consultation",
        schema="erp",
        type_="check",
    )
    for column_name in (
        "status",
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    ):
        op.drop_column("staff_quarterly_consultation", column_name, schema="erp")

    op.alter_column(
        "staff_quarterly_consultation",
        "completed",
        schema="erp",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )
    op.create_unique_constraint(
        "uq_staff_quarterly_consultation_staff_year_quarter",
        "staff_quarterly_consultation",
        ["staff_id", "calendar_year", "quarter_no"],
        schema="erp",
    )


def upgrade() -> None:
    _assert_exact_training_catalog()
    _remove_health_check_requirement_ledger()
    _reduce_health_check_to_date_fact()
    _reduce_quarterly_consultation_to_toggle()


def downgrade() -> None:
    raise RuntimeError(
        "20260813_0020_w1_staff_contract_correction is forward-only because the removed "
        "requirement and consultation detail ledgers cannot be reconstructed"
    )
