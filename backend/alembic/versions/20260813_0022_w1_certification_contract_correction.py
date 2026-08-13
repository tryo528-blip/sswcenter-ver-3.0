"""Merge grade into certification and make benefit start text opaque.

Revision ID: 20260813_0022_w1_certification_contract_correction
Revises: 20260813_0021_w1_recipient_contract_correction
Create Date: 2026-08-13

The migration refuses to infer a grade.  Every historical certification row
must have exactly one grade row with the same recipient, dates, and active/
invalidated state before the separate grade ledger can be removed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0022_w1_certification_contract_correction"
down_revision: str | None = "20260813_0021_w1_recipient_contract_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fail_closed_grade_preflight() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT certification.id
                FROM erp.recipient_certification_period certification
                LEFT JOIN erp.recipient_grade_period grade
                  ON grade.recipient_id = certification.recipient_id
                 AND grade.certification_period_id = certification.id
                GROUP BY
                    certification.id,
                    certification.start_date,
                    certification.end_date,
                    certification.invalidated_at_utc
                HAVING count(grade.id) <> 1
                    OR count(grade.id) FILTER (
                        WHERE grade.start_date = certification.start_date
                          AND grade.end_date = certification.end_date
                          AND (grade.invalidated_at_utc IS NULL)
                              = (certification.invalidated_at_utc IS NULL)
                    ) <> 1
            ) THEN
                RAISE EXCEPTION
                    'certification and grade rows are not exact one-to-one matches'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_w1_certification_grade_exact_one_to_one';
            END IF;
        END
        $$;
        """
    )
def _merge_grade_into_certification() -> None:
    op.add_column(
        "recipient_certification_period",
        sa.Column("grade_code", sa.Text(), nullable=True),
        schema="erp",
    )
    op.execute(
        """
        UPDATE erp.recipient_certification_period certification
        SET grade_code = grade.grade_code
        FROM erp.recipient_grade_period grade
        WHERE grade.recipient_id = certification.recipient_id
          AND grade.certification_period_id = certification.id;
        """
    )
    op.alter_column(
        "recipient_certification_period",
        "grade_code",
        existing_type=sa.Text(),
        nullable=False,
        schema="erp",
    )
    op.create_check_constraint(
        op.f("ck_recipient_certification_period_grade_code"),
        "recipient_certification_period",
        "grade_code IN ('1','2','3','4','5')",
        schema="erp",
    )
    op.execute(
        """
        DROP TRIGGER ct_recipient_certification_grade_containment
            ON erp.recipient_certification_period;
        DROP TRIGGER ct_recipient_grade_period_containment
            ON erp.recipient_grade_period;
        DROP FUNCTION erp.fn_w1c_assert_certification_contains_grades();
        DROP FUNCTION erp.fn_w1c_assert_grade_containment();
        """
    )
    op.drop_table("recipient_grade_period", schema="erp")


def _make_benefit_start_text_opaque() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT recipient_id
                FROM erp.recipient_benefit_period
                WHERE invalidated_at_utc IS NULL
                GROUP BY recipient_id
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'multiple active benefit rows cannot be converted without date semantics'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'uq_recipient_benefit_period_active_recipient';
            END IF;
        END
        $$;
        """
    )

    op.add_column(
        "recipient_benefit_period",
        sa.Column(
            "start_text",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        schema="erp",
    )
    # The retired date has no meaning in the corrected contract. Existing and
    # newly created rows keep the display-only value at the empty-string default.
    op.execute(
        """
        ALTER TABLE erp.recipient_benefit_period
        DROP CONSTRAINT ex_recipient_benefit_period;
        """
    )
    op.drop_constraint(
        op.f("ck_recipient_benefit_period_date_order"),
        "recipient_benefit_period",
        schema="erp",
        type_="check",
    )
    op.drop_column("recipient_benefit_period", "benefit_period", schema="erp")
    op.drop_column("recipient_benefit_period", "end_date", schema="erp")
    op.drop_column("recipient_benefit_period", "start_date", schema="erp")
    op.create_index(
        "uq_recipient_benefit_period_active_recipient",
        "recipient_benefit_period",
        ["recipient_id"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL"),
    )


def upgrade() -> None:
    _fail_closed_grade_preflight()
    _merge_grade_into_certification()
    _make_benefit_start_text_opaque()


def downgrade() -> None:
    raise RuntimeError(
        "20260813_0022_w1_certification_contract_correction is a canonical "
        "forward-only migration; operational rollback is pre-upgrade backup restore"
    )
