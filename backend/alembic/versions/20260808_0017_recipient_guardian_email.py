"""Add recipient guardian email.

Revision ID: 20260808_0017_recipient_guardian_email
Revises: 20260808_0016_recipient_payer_guardian
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0017_recipient_guardian_email"
down_revision: str | None = "20260808_0016_recipient_payer_guardian"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recipient_guardian",
        sa.Column("email", sa.Text(), nullable=True),
        schema="erp",
    )


def downgrade() -> None:
    op.drop_column("recipient_guardian", "email", schema="erp")
