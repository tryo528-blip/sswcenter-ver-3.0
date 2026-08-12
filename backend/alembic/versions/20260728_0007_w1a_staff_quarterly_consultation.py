"""Add W1A staff quarterly consultation facts and statuses.

Revision ID: 20260728_0007_w1a_staff_quarterly_consultation
Revises: 20260728_0006_w1a_staff_health_check
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0007_w1a_staff_quarterly_consultation"
down_revision: str | None = "20260728_0006_w1a_staff_health_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUARTERLY_CONSULTATION_STATUSES = ("COMPLETE", "INCOMPLETE", "EXEMPT")


def _create_consultation_table() -> None:
    op.create_table(
        "staff_quarterly_consultation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("calendar_year", sa.Integer(), nullable=False),
        sa.Column("quarter_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("counseling_date", sa.Date(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("incomplete_reason_text", sa.Text(), nullable=True),
        sa.Column("exempt_reason_text", sa.Text(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_staff_quarterly_consultation_id",
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
            "quarter_no IN (1, 2, 3, 4)",
            name=op.f("ck_staff_quarterly_consultation_quarter_no"),
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETE', 'INCOMPLETE', 'EXEMPT')",
            name=op.f("ck_staff_quarterly_consultation_status"),
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETE' AND counseling_date IS NOT NULL "
            "AND content IS NOT NULL AND btrim(content) <> '' "
            "AND incomplete_reason_text IS NULL "
            "AND exempt_reason_text IS NULL)"
            " OR (status = 'INCOMPLETE' AND counseling_date IS NULL "
            "AND content IS NULL AND incomplete_reason_text IS NOT NULL "
            "AND btrim(incomplete_reason_text) <> '' "
            "AND exempt_reason_text IS NULL)"
            " OR (status = 'EXEMPT' AND counseling_date IS NULL "
            "AND content IS NULL AND incomplete_reason_text IS NULL "
            "AND exempt_reason_text IS NOT NULL AND btrim(exempt_reason_text) <> '')",
            name=op.f("ck_staff_quarterly_consultation_status_truth"),
        ),
        sa.CheckConstraint(
            "(content IS NULL OR length(content) <= 4000)"
            " AND (incomplete_reason_text IS NULL OR length(incomplete_reason_text) <= 4000)"
            " AND (exempt_reason_text IS NULL OR length(exempt_reason_text) <= 4000)",
            name=op.f("ck_staff_quarterly_consultation_text_length"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_quarterly_consultation_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_quarterly_consultation_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_staff_quarterly_consultation_id"],
            ["erp.staff_quarterly_consultation.id"],
            name="fk_staff_quarterly_consultation_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_quarterly_consultation_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_quarterly_consultation_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_quarterly_consultation"),
        schema="erp",
    )

    op.create_index(
        "uq_staff_quarterly_consultation_active",
        "staff_quarterly_consultation",
        ["staff_id", "calendar_year", "quarter_no"],
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
                    erp.staff_quarterly_consultation
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.staff_quarterly_consultation
                FROM erp_app;
                GRANT USAGE, SELECT ON SEQUENCE
                    erp.staff_quarterly_consultation_id_seq
                TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    erp.staff_quarterly_consultation
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_quarterly_consultation
                FROM erp_backup;
                GRANT SELECT ON SEQUENCE
                    erp.staff_quarterly_consultation_id_seq
                TO erp_backup;
                REVOKE USAGE ON SEQUENCE
                    erp.staff_quarterly_consultation_id_seq
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_consultation_table()
    _grant_runtime_roles()


def _revoke_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_quarterly_consultation
                FROM erp_app;
                REVOKE USAGE, SELECT ON SEQUENCE
                    erp.staff_quarterly_consultation_id_seq
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_quarterly_consultation
                FROM erp_backup;
                REVOKE USAGE, SELECT ON SEQUENCE
                    erp.staff_quarterly_consultation_id_seq
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    _revoke_runtime_roles()
    op.drop_index(
        "uq_staff_quarterly_consultation_active",
        table_name="staff_quarterly_consultation",
        schema="erp",
    )
    op.drop_table("staff_quarterly_consultation", schema="erp")
