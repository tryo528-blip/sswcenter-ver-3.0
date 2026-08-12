"""Add manual recipient_status tag on recipient.

Revision ID: 20260806_0015_recipient_status_tag
Revises: 20260803_0014_recipient_plan_notification
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "20260806_0015_recipient_status_tag"
down_revision: str | None = "20260803_0014_recipient_plan_notification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "recipient"
_COLUMN = "recipient_status"
_CHECK = "ck_recipient_recipient_status"


def upgrade() -> None:
    # 1) Add nullable column so existing rows can be backfilled safely.
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Text(), nullable=True),
        schema="erp",
    )
    # 2) Backfill every existing row to ACTIVE (manual tag default).
    op.execute(sa.text(f"UPDATE erp.{_TABLE} SET {_COLUMN} = 'ACTIVE' WHERE {_COLUMN} IS NULL"))
    # 3) Enforce non-null + server default for new inserts.
    op.alter_column(
        _TABLE,
        _COLUMN,
        existing_type=sa.Text(),
        nullable=False,
        server_default=sa.text("'ACTIVE'"),
        schema="erp",
    )
    # 4) Accept only the sealed manual-tag values.
    op.create_check_constraint(
        op.f(_CHECK),
        _TABLE,
        f"{_COLUMN} IN ('ACTIVE','ENDED','WAITING')",
        schema="erp",
    )


def downgrade() -> None:
    # Fail-closed in Alembic offline mode: data validation is impossible.
    if context.is_offline_mode():
        raise RuntimeError(
            "Downgrade blocked: Alembic is running in offline mode. "
            "Data validation cannot be performed; downgrade is not allowed."
        )

    conn = op.get_bind()

    # Acquire a write-blocking table lock so concurrent INSERT/UPDATE cannot
    # sneak in ENDED/WAITING between the status check and the DDL drops.
    # SHARE ROW EXCLUSIVE blocks concurrent data changes but allows reads.
    conn.execute(sa.text(f"LOCK TABLE erp.{_TABLE} IN SHARE ROW EXCLUSIVE MODE"))

    # Fail-closed guard: only allow downgrade when every recipient_status is ACTIVE.
    non_active = conn.execute(
        sa.text(
            f"SELECT 1 FROM erp.{_TABLE} WHERE {_COLUMN} IS NULL OR {_COLUMN} != 'ACTIVE' LIMIT 1"
        )
    ).scalar()
    if non_active is not None:
        raise RuntimeError(
            "Downgrade blocked: erp.recipient contains non-ACTIVE recipient_status "
            "values (ENDED, WAITING, NULL, or other). All rows must be ACTIVE before "
            "the column can be dropped."
        )

    op.drop_constraint(op.f(_CHECK), _TABLE, schema="erp", type_="check")
    op.drop_column(_TABLE, _COLUMN, schema="erp")
