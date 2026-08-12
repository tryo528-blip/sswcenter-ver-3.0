"""Add per-recipient previous plan notification dates.

Revision ID: 20260803_0014_recipient_plan_notification
Revises: 20260802_0013_staff_continuing_education
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260803_0014_recipient_plan_notification"
down_revision: str | None = "20260802_0013_staff_continuing_education"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "recipient_plan_notification"


def _actor_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def _actor_constraints(table_name: str) -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name=f"fk_{table_name}_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name=f"fk_{table_name}_updated_by_account",
            ondelete="RESTRICT",
        ),
    )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("notified_date", sa.Date(), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_plan_notification_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_plan_notification_recipient",
            ondelete="RESTRICT",
        ),
        *_actor_constraints(_TABLE),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_plan_notification"),
        schema="erp",
    )
    op.create_index(
        "ix_recipient_plan_notification_recipient_id",
        _TABLE,
        ["recipient_id"],
        schema="erp",
    )
    op.create_index(
        "ix_recipient_plan_notification_notified_date",
        _TABLE,
        ["notified_date"],
        schema="erp",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    erp.recipient_plan_notification TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.recipient_plan_notification FROM erp_app;
                IF to_regclass('erp.recipient_plan_notification_id_seq') IS NOT NULL THEN
                    GRANT USAGE, SELECT ON SEQUENCE
                        erp.recipient_plan_notification_id_seq TO erp_app;
                END IF;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE erp.recipient_plan_notification TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.recipient_plan_notification FROM erp_backup;
                IF to_regclass('erp.recipient_plan_notification_id_seq') IS NOT NULL THEN
                    GRANT SELECT ON SEQUENCE
                        erp.recipient_plan_notification_id_seq TO erp_backup;
                    REVOKE USAGE ON SEQUENCE
                        erp.recipient_plan_notification_id_seq FROM erp_backup;
                END IF;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.recipient_plan_notification FROM erp_app;
                IF to_regclass('erp.recipient_plan_notification_id_seq') IS NOT NULL THEN
                    REVOKE USAGE, SELECT ON SEQUENCE
                        erp.recipient_plan_notification_id_seq FROM erp_app;
                END IF;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.recipient_plan_notification FROM erp_backup;
                IF to_regclass('erp.recipient_plan_notification_id_seq') IS NOT NULL THEN
                    REVOKE USAGE, SELECT ON SEQUENCE
                        erp.recipient_plan_notification_id_seq FROM erp_backup;
                END IF;
            END IF;
        END
        $$;
        """
    )
    op.drop_index(
        "ix_recipient_plan_notification_notified_date",
        table_name=_TABLE,
        schema="erp",
    )
    op.drop_index(
        "ix_recipient_plan_notification_recipient_id",
        table_name=_TABLE,
        schema="erp",
    )
    op.drop_table(_TABLE, schema="erp")
