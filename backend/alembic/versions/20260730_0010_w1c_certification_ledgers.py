"""Add W1C certification, grade, benefit, and approval ledgers.

Revision ID: 20260730_0010_w1c_certification_ledgers
Revises: 20260730_0009_w1b_recipient
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260730_0010_w1c_certification_ledgers"
down_revision: str | None = "20260730_0009_w1b_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "recipient_certification_identity",
    "recipient_certification_period",
    "recipient_grade_period",
    "recipient_benefit_period",
    "recipient_local_approval_amount_period",
)
_SEQUENCE_TABLES = _TABLES[1:]


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


def _create_certification_identity_table() -> None:
    op.create_table(
        "recipient_certification_identity",
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("certification_number", sa.Text(), nullable=False),
        *_actor_columns(),
        sa.CheckConstraint(
            "certification_number ~ '^L[0-9]{10}$'",
            name=op.f("ck_recipient_certification_identity_number"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_certification_identity_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_certification_identity_recipient",
            ondelete="RESTRICT",
        ),
        *_actor_constraints("recipient_certification_identity"),
        sa.PrimaryKeyConstraint(
            "recipient_id",
            name="pk_recipient_certification_identity",
        ),
        sa.UniqueConstraint(
            "certification_number",
            name="uq_recipient_certification_identity_certification_number",
        ),
        schema="erp",
    )
    op.execute(
        """
        CREATE FUNCTION erp.fn_recipient_certification_number_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.recipient_id IS DISTINCT FROM NEW.recipient_id
               OR OLD.certification_number IS DISTINCT FROM NEW.certification_number THEN
                RAISE EXCEPTION 'recipient certification identity is immutable'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_certification_identity_immutable';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE TRIGGER bu_recipient_certification_number_immutable
        BEFORE UPDATE OF recipient_id, certification_number
        ON erp.recipient_certification_identity
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_recipient_certification_number_immutable();
        """
    )


def _create_certification_period_table() -> None:
    op.create_table(
        "recipient_certification_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "certification_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_certification_period_id",
            sa.BigInteger(),
            nullable=True,
        ),
        *_actor_columns(),
        sa.CheckConstraint(
            "start_date <= end_date",
            name=op.f("ck_recipient_certification_period_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_certification_period_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("certification_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_certification_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient_certification_identity.recipient_id"],
            name="fk_recipient_certification_period_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_certification_period_id"],
            ["erp.recipient_certification_period.id"],
            name="fk_recipient_certification_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_certification_period"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_certification_period"),
        sa.UniqueConstraint(
            "recipient_id",
            "id",
            name="uq_recipient_certification_period_recipient_id_id",
        ),
        schema="erp",
    )


def _create_grade_period_table() -> None:
    op.create_table(
        "recipient_grade_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("certification_period_id", sa.BigInteger(), nullable=False),
        sa.Column("grade_code", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "grade_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_grade_period_id", sa.BigInteger(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "grade_code IN ('1','2','3','4','5')",
            name=op.f("ck_recipient_grade_period_grade_code"),
        ),
        sa.CheckConstraint(
            "start_date <= end_date",
            name=op.f("ck_recipient_grade_period_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_grade_period_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("grade_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_grade_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "certification_period_id"],
            [
                "erp.recipient_certification_period.recipient_id",
                "erp.recipient_certification_period.id",
            ],
            name="fk_recipient_grade_period_certification",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_grade_period_id"],
            ["erp.recipient_grade_period.id"],
            name="fk_recipient_grade_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_grade_period"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_grade_period"),
        schema="erp",
    )

    op.execute(
        """
        CREATE FUNCTION erp.fn_w1c_assert_grade_containment()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            certification_row erp.recipient_certification_period%ROWTYPE;
        BEGIN
            IF NEW.invalidated_at_utc IS NOT NULL THEN
                RETURN NULL;
            END IF;

            SELECT *
            INTO certification_row
            FROM erp.recipient_certification_period
            WHERE id = NEW.certification_period_id
              AND recipient_id = NEW.recipient_id
            FOR SHARE;

            IF NOT FOUND
               OR certification_row.invalidated_at_utc IS NOT NULL
               OR NEW.start_date < certification_row.start_date
               OR NEW.end_date > certification_row.end_date THEN
                RAISE EXCEPTION 'grade period must be inside an active certification period'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_grade_period_containment';
            END IF;
            RETURN NULL;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_recipient_grade_period_containment
        AFTER INSERT OR UPDATE ON erp.recipient_grade_period
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_w1c_assert_grade_containment();

        CREATE FUNCTION erp.fn_w1c_assert_certification_contains_grades()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM erp.recipient_grade_period grade
                WHERE grade.certification_period_id = NEW.id
                  AND grade.recipient_id = NEW.recipient_id
                  AND grade.invalidated_at_utc IS NULL
                  AND (
                      NEW.invalidated_at_utc IS NOT NULL
                      OR grade.start_date < NEW.start_date
                      OR grade.end_date > NEW.end_date
                  )
            ) THEN
                RAISE EXCEPTION 'certification period must contain all active grade periods'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_certification_period_grade_containment';
            END IF;
            RETURN NULL;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_recipient_certification_grade_containment
        AFTER INSERT OR UPDATE ON erp.recipient_certification_period
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_w1c_assert_certification_contains_grades();
        """
    )


def _create_benefit_period_table() -> None:
    op.create_table(
        "recipient_benefit_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("benefit_code", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "benefit_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_benefit_period_id", sa.BigInteger(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            """
            benefit_code IN (
                'GENERAL',
                'BASIC_LIVELIHOOD',
                'REDUCTION_6',
                'REDUCTION_9',
                'MEDICAL_6',
                'MEDICAL_9'
            )
            """,
            name=op.f("ck_recipient_benefit_period_benefit_code"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name=op.f("ck_recipient_benefit_period_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_benefit_period_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("benefit_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_benefit_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_benefit_period_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_benefit_period_id"],
            ["erp.recipient_benefit_period.id"],
            name="fk_recipient_benefit_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_benefit_period"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_benefit_period"),
        schema="erp",
    )


def _create_approval_amount_period_table() -> None:
    op.create_table(
        "recipient_local_approval_amount_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_krw", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "approval_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_local_approval_amount_period_id",
            sa.BigInteger(),
            nullable=True,
        ),
        *_actor_columns(),
        sa.CheckConstraint(
            "amount_krw >= 0",
            name=op.f("ck_recipient_local_approval_amount_period_amount"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name=op.f("ck_recipient_local_approval_amount_period_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_local_approval_amount_period_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("approval_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_local_approval_amount_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_local_approval_amount_period_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_local_approval_amount_period_id"],
            ["erp.recipient_local_approval_amount_period.id"],
            name="fk_recipient_local_approval_amount_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_local_approval_amount_period"),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_recipient_local_approval_amount_period",
        ),
        schema="erp",
    )


def _grant_runtime_roles() -> None:
    table_list = ",\n                    ".join(f"erp.{name}" for name in _TABLES)
    sequence_list = ",\n                    ".join(
        f"erp.{name}_id_seq" for name in _SEQUENCE_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    {table_list}
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_app;
                GRANT USAGE, SELECT ON SEQUENCE
                    {sequence_list}
                TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    {table_list}
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_backup;
                GRANT SELECT ON SEQUENCE
                    {sequence_list}
                TO erp_backup;
                REVOKE USAGE ON SEQUENCE
                    {sequence_list}
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_certification_identity_table()
    _create_certification_period_table()
    _create_grade_period_table()
    _create_benefit_period_table()
    _create_approval_amount_period_table()
    _grant_runtime_roles()


def _revoke_runtime_roles() -> None:
    table_list = ",\n                    ".join(f"erp.{name}" for name in _TABLES)
    sequence_list = ",\n                    ".join(
        f"erp.{name}_id_seq" for name in _SEQUENCE_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_app;
                REVOKE USAGE, SELECT ON SEQUENCE
                    {sequence_list}
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_backup;
                REVOKE USAGE, SELECT ON SEQUENCE
                    {sequence_list}
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    _revoke_runtime_roles()
    op.drop_table("recipient_local_approval_amount_period", schema="erp")
    op.drop_table("recipient_benefit_period", schema="erp")
    op.execute(
        """
        DROP TRIGGER ct_recipient_certification_grade_containment
        ON erp.recipient_certification_period;
        DROP FUNCTION erp.fn_w1c_assert_certification_contains_grades();
        DROP TRIGGER ct_recipient_grade_period_containment
        ON erp.recipient_grade_period;
        DROP FUNCTION erp.fn_w1c_assert_grade_containment();
        """
    )
    op.drop_table("recipient_grade_period", schema="erp")
    op.drop_table("recipient_certification_period", schema="erp")
    op.execute(
        """
        DROP TRIGGER bu_recipient_certification_number_immutable
        ON erp.recipient_certification_identity;
        DROP FUNCTION erp.fn_recipient_certification_number_immutable();
        """
    )
    op.drop_table("recipient_certification_identity", schema="erp")
