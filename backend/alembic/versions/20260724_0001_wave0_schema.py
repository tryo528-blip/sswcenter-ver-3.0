"""Create the Wave 0 schema and singleton foundation.

Revision ID: 20260724_0001
Revises:
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS erp")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "center",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("center_code", sa.Text(), nullable=False),
        sa.Column("center_name", sa.Text(), nullable=False),
        sa.Column("business_no", sa.Text(), nullable=True),
        sa.Column("representative_name", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_center"),
        sa.UniqueConstraint("center_code", name="uq_center_center_code"),
        schema="erp",
    )
    op.create_index(
        "uq_center_single_active",
        "center",
        [sa.literal_column("(true)")],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "business_number_counter",
        sa.Column("number_type", sa.Text(), nullable=False),
        sa.Column("number_year", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name="ck_business_number_counter_last_sequence_nonnegative",
        ),
        sa.PrimaryKeyConstraint(
            "number_type",
            "number_year",
            name="pk_business_number_counter",
        ),
        schema="erp",
    )

    op.create_table(
        "installation_state",
        sa.Column(
            "singleton_key",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "bootstrap_completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("bootstrap_completed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_admin_account_id", sa.BigInteger(), nullable=True),
        sa.Column("installed_app_version", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "singleton_key",
            name="ck_installation_state_singleton_key_true",
        ),
        sa.PrimaryKeyConstraint("singleton_key", name="pk_installation_state"),
        schema="erp",
    )
    op.execute(
        """
        INSERT INTO erp.installation_state (singleton_key, bootstrap_completed)
        VALUES (true, false)
        ON CONFLICT (singleton_key) DO NOTHING
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT count(*) FROM erp.installation_state) <> 1 THEN
                RAISE EXCEPTION 'installation_state must contain exactly one row';
            END IF;
            IF to_regclass('erp.uq_center_single_active') IS NULL THEN
                RAISE EXCEPTION 'single-active-center index is missing';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_table("installation_state", schema="erp")
    op.drop_table("business_number_counter", schema="erp")
    op.drop_index("uq_center_single_active", table_name="center", schema="erp")
    op.drop_table("center", schema="erp")
    # Keep the schema because it contains Alembic's own version table.
