"""Add the internal W1A staff legacy mapping ledger.

Revision ID: 20260728_0008_w1a_staff_legacy_mapping
Revises: 20260728_0007_w1a_staff_quarterly_consultation
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0008_w1a_staff_legacy_mapping"
down_revision: str | None = "20260728_0007_w1a_staff_quarterly_consultation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MAPPING_AUDIT_ACTIONS = (
    "STAFF_LEGACY_MAPPING_CREATE",
    "STAFF_LEGACY_MAPPING_INVALIDATE",
    "STAFF_LEGACY_MAPPING_REPLACEMENT_CREATE",
)


def _create_mapping_table() -> None:
    op.create_table(
        "staff_legacy_mapping",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_system_code", sa.Text(), nullable=False),
        sa.Column("legacy_staff_key", sa.Text(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_fingerprint", sa.LargeBinary(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_staff_legacy_mapping_id",
            sa.BigInteger(),
            nullable=True,
        ),
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
        sa.CheckConstraint(
            "btrim(source_system_code) <> ''",
            name=op.f("ck_staff_legacy_mapping_source_system_code_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(legacy_staff_key) <> ''",
            name=op.f("ck_staff_legacy_mapping_legacy_staff_key_nonblank"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_legacy_mapping_row_version_positive"),
        ),
        # The staff FK is deliberately ON DELETE RESTRICT.
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_legacy_mapping_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_staff_legacy_mapping_id"],
            ["erp.staff_legacy_mapping.id"],
            name="fk_staff_legacy_mapping_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_legacy_mapping_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_legacy_mapping_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_legacy_mapping"),
        schema="erp",
    )
    op.create_index(
        "uq_staff_legacy_mapping_active",
        "staff_legacy_mapping",
        ["source_system_code", "legacy_staff_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL"),
    )


def _grant_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    erp.staff_legacy_mapping
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.staff_legacy_mapping
                FROM erp_app;
                GRANT USAGE, SELECT ON SEQUENCE
                    erp.staff_legacy_mapping_id_seq
                TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    erp.staff_legacy_mapping
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_legacy_mapping
                FROM erp_backup;
                GRANT SELECT ON SEQUENCE
                    erp.staff_legacy_mapping_id_seq
                TO erp_backup;
                REVOKE USAGE ON SEQUENCE
                    erp.staff_legacy_mapping_id_seq
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_mapping_table()
    _grant_runtime_roles()


def _revoke_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_legacy_mapping
                FROM erp_app;
                REVOKE USAGE, SELECT ON SEQUENCE
                    erp.staff_legacy_mapping_id_seq
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_legacy_mapping
                FROM erp_backup;
                REVOKE USAGE, SELECT ON SEQUENCE
                    erp.staff_legacy_mapping_id_seq
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    _revoke_runtime_roles()
    op.drop_index(
        "uq_staff_legacy_mapping_active",
        table_name="staff_legacy_mapping",
        schema="erp",
    )
    op.drop_table("staff_legacy_mapping", schema="erp")
