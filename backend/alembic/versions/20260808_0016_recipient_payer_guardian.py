"""Add recipient.payer_guardian_id with same-recipient composite FK.

Revision ID: 20260808_0016_recipient_payer_guardian
Revises: 20260806_0015_recipient_status_tag
Create Date: 2026-08-08

NULL payer_guardian_id means the recipient self is the payer.
A non-null value must reference a guardian that belongs to the same recipient
(composite FK to recipient_guardian(recipient_id, id)).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260808_0016_recipient_payer_guardian"
down_revision: str | None = "20260806_0015_recipient_status_tag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "recipient"
_COLUMN = "payer_guardian_id"
_FK = "fk_recipient_payer_guardian_same_recipient"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.BigInteger(), nullable=True),
        schema="erp",
    )
    # Composite FK: recipient(id, payer_guardian_id) -> guardian(recipient_id, id)
    # so a recipient cannot point at another recipient's guardian.
    # MATCH SIMPLE: NULL payer_guardian_id skips the FK check (self payer).
    op.create_foreign_key(
        op.f(_FK),
        _TABLE,
        "recipient_guardian",
        ["id", _COLUMN],
        ["recipient_id", "id"],
        source_schema="erp",
        referent_schema="erp",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_FK), _TABLE, schema="erp", type_="foreignkey")
    op.drop_column(_TABLE, _COLUMN, schema="erp")
