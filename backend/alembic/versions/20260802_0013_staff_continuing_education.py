"""Add biennial care-worker continuing education.

Revision ID: 20260802_0013_staff_continuing_education
Revises: 20260801_0012_w1e_care_assignment
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0013_staff_continuing_education"
down_revision: str | None = "20260801_0012_w1e_care_assignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "training_course"
_CYCLE_CONSTRAINT = "ck_training_course_cycle_type"


def upgrade() -> None:
    op.drop_constraint(op.f(_CYCLE_CONSTRAINT), _TABLE, schema="erp", type_="check")
    op.create_check_constraint(
        op.f(_CYCLE_CONSTRAINT),
        _TABLE,
        "cycle_type IN ('ON_HIRE','HALF_YEAR','ANNUAL','BIENNIAL')",
        schema="erp",
    )
    op.execute(
        sa.text(
            """
            INSERT INTO erp.training_course
                (code, display_name, cycle_type, active, sort_order)
            VALUES
                ('CONTINUING_EDUCATION', '보수교육', 'BIENNIAL', TRUE, 8)
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM erp.staff_periodic_training_status
            WHERE course_code = 'CONTINUING_EDUCATION'
            """
        )
    )
    op.execute(sa.text("DELETE FROM erp.training_course WHERE code = 'CONTINUING_EDUCATION'"))
    op.drop_constraint(op.f(_CYCLE_CONSTRAINT), _TABLE, schema="erp", type_="check")
    op.create_check_constraint(
        op.f(_CYCLE_CONSTRAINT),
        _TABLE,
        "cycle_type IN ('ON_HIRE','HALF_YEAR','ANNUAL')",
        schema="erp",
    )
