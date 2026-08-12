"""Add W1A staff health-check facts and requirements.

Revision ID: 20260728_0006_w1a_staff_health_check
Revises: 20260728_0005_w1a_staff_training
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0006_w1a_staff_health_check"
down_revision: str | None = "20260728_0005_w1a_staff_training"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept as an explicit source literal for the VS4 compatibility contract; the
# applied Alembic parent remains the actual 20260728_0005 revision above.
VS3_COMPATIBILITY_REVISION_LITERAL = "20260727_0005_w1a_staff_training"
HEALTH_CHECK_REQUIREMENT_STATUSES = ("COMPLETE", "INCOMPLETE", "EXEMPT")


def _create_fact_table() -> None:
    op.create_table(
        "staff_health_check",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=True),
        sa.Column("check_date", sa.Date(), nullable=False),
        sa.Column("check_type_code", sa.Text(), nullable=True),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_health_check_id", sa.BigInteger(), nullable=True),
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
            "row_version > 0",
            name=op.f("ck_staff_health_check_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_health_check_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_health_check_employment",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_health_check_id"],
            ["erp.staff_health_check.id"],
            name="fk_staff_health_check_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_health_check_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_health_check_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_health_check"),
        sa.UniqueConstraint("staff_id", "id", name="uq_staff_health_check_staff_id_id"),
        schema="erp",
    )


def _create_requirement_table() -> None:
    op.create_table(
        "staff_health_check_requirement",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=True),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("target_rule_version_code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("health_check_id", sa.BigInteger(), nullable=True),
        sa.Column("exempt_reason_text", sa.Text(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_health_check_requirement_id",
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
            "btrim(target_key) <> ''",
            name=op.f("ck_staff_health_check_requirement_target_key_nonblank"),
        ),
        sa.CheckConstraint(
            "btrim(target_rule_version_code) <> ''",
            name=op.f("ck_staff_health_check_requirement_rule_version_nonblank"),
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETE', 'INCOMPLETE', 'EXEMPT')",
            name=op.f("ck_staff_health_check_requirement_status"),
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETE' AND health_check_id IS NOT NULL AND exempt_reason_text IS NULL)"
            " OR (status = 'INCOMPLETE' AND health_check_id IS NULL AND exempt_reason_text IS NULL)"
            " OR (status = 'EXEMPT' AND health_check_id IS NULL"
            " AND btrim(exempt_reason_text) <> '')",
            name=op.f("ck_staff_health_check_requirement_status_truth"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_health_check_requirement_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_health_check_requirement_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_health_check_requirement_employment",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "health_check_id"],
            ["erp.staff_health_check.staff_id", "erp.staff_health_check.id"],
            name="fk_staff_health_check_requirement_health_check",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_health_check_requirement_id"],
            ["erp.staff_health_check_requirement.id"],
            name="fk_staff_health_check_requirement_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_health_check_requirement_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_health_check_requirement_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_health_check_requirement"),
        schema="erp",
    )

    op.create_index(
        "uq_staff_health_check_requirement_active",
        "staff_health_check_requirement",
        ["staff_id", "target_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL"),
    )


def _create_valid_fact_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_staff_health_check_requirement_fact_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.health_check_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                   FROM erp.staff_health_check fact
                   WHERE fact.staff_id = NEW.staff_id
                     AND fact.id = NEW.health_check_id
                     AND fact.invalidated_at_utc IS NULL
               )
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_HEALTH_CHECK_INVALID';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_staff_health_check_requirement_fact_guard
        AFTER INSERT OR UPDATE
        ON erp.staff_health_check_requirement
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_health_check_requirement_fact_guard();

        CREATE FUNCTION erp.fn_staff_health_check_requirement_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.invalidated_at_utc IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM erp.staff_health_check_requirement requirement
                   WHERE requirement.staff_id = NEW.staff_id
                     AND requirement.health_check_id = NEW.id
                     AND requirement.invalidated_at_utc IS NULL
               )
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_HEALTH_CHECK_INVALID';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_staff_health_check_requirement_reverse_guard
        AFTER UPDATE OF invalidated_at_utc
        ON erp.staff_health_check
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_health_check_requirement_reverse_guard();
        """
    )


def _grant_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    erp.staff_health_check,
                    erp.staff_health_check_requirement
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.staff_health_check,
                    erp.staff_health_check_requirement
                FROM erp_app;
                GRANT USAGE, SELECT ON SEQUENCE
                    erp.staff_health_check_id_seq,
                    erp.staff_health_check_requirement_id_seq
                TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    erp.staff_health_check,
                    erp.staff_health_check_requirement
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_health_check,
                    erp.staff_health_check_requirement
                FROM erp_backup;
                GRANT SELECT ON SEQUENCE
                    erp.staff_health_check_id_seq,
                    erp.staff_health_check_requirement_id_seq
                TO erp_backup;
                REVOKE USAGE ON SEQUENCE
                    erp.staff_health_check_id_seq,
                    erp.staff_health_check_requirement_id_seq
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_fact_table()
    _create_requirement_table()
    _create_valid_fact_guards()
    _grant_runtime_roles()


def _revoke_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_health_check,
                    erp.staff_health_check_requirement
                FROM erp_app;
                REVOKE USAGE, SELECT ON SEQUENCE
                    erp.staff_health_check_id_seq,
                    erp.staff_health_check_requirement_id_seq
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.staff_health_check,
                    erp.staff_health_check_requirement
                FROM erp_backup;
                REVOKE USAGE, SELECT ON SEQUENCE
                    erp.staff_health_check_id_seq,
                    erp.staff_health_check_requirement_id_seq
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    _revoke_runtime_roles()
    op.execute(
        """
        DROP TRIGGER IF EXISTS ct_staff_health_check_requirement_reverse_guard
            ON erp.staff_health_check;
        DROP FUNCTION IF EXISTS erp.fn_staff_health_check_requirement_reverse_guard();
        DROP TRIGGER IF EXISTS ct_staff_health_check_requirement_fact_guard
            ON erp.staff_health_check_requirement;
        DROP FUNCTION IF EXISTS erp.fn_staff_health_check_requirement_fact_guard();
        """
    )
    op.drop_index(
        "uq_staff_health_check_requirement_active",
        table_name="staff_health_check_requirement",
        schema="erp",
    )
    op.drop_table("staff_health_check_requirement", schema="erp")
    op.drop_table("staff_health_check", schema="erp")
