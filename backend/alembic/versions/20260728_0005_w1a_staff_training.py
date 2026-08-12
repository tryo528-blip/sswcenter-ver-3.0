"""Add W1A staff onboarding and periodic training facts.

Revision ID: 20260728_0005_w1a_staff_training
Revises: 20260727_0004_w1a_staff_qualifications
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0005_w1a_staff_training"
down_revision: str | None = "20260727_0004_w1a_staff_qualifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRAINING_COURSE_SEED = (
    {
        "sort_order": 1,
        "code": "NEW_HIRE_ORIENTATION",
        "display_name": "신규직원교육",
        "cycle_type": "ON_HIRE",
    },
    {
        "sort_order": 2,
        "code": "ELDER_RIGHTS",
        "display_name": "노인인권",
        "cycle_type": "HALF_YEAR",
    },
    {
        "sort_order": 3,
        "code": "DISABLED_ABUSE",
        "display_name": "장애인학대 신고의무자교육",
        "cycle_type": "ANNUAL",
    },
    {
        "sort_order": 4,
        "code": "ELDER_ABUSE",
        "display_name": "노인학대 신고의무자교육",
        "cycle_type": "ANNUAL",
    },
    {
        "sort_order": 5,
        "code": "SEXUAL_HARASSMENT",
        "display_name": "직장 내 성희롱 예방교육",
        "cycle_type": "ANNUAL",
    },
    {
        "sort_order": 6,
        "code": "WORKPLACE_BULLYING",
        "display_name": "직장 내 괴롭힘 예방교육",
        "cycle_type": "ANNUAL",
    },
    {
        "sort_order": 7,
        "code": "PRIVACY",
        "display_name": "개인정보보호교육",
        "cycle_type": "ANNUAL",
    },
)


def _create_catalog_table() -> None:
    op.create_table(
        "training_course",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("cycle_type", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "cycle_type IN ('ON_HIRE','HALF_YEAR','ANNUAL')",
            name=op.f("ck_training_course_cycle_type"),
        ),
        sa.CheckConstraint("sort_order > 0", name=op.f("ck_training_course_sort_order_positive")),
        sa.PrimaryKeyConstraint("code", name="pk_training_course"),
        sa.UniqueConstraint("sort_order", name="uq_training_course_sort_order"),
        schema="erp",
    )


def _create_fact_tables() -> None:
    op.create_table(
        "staff_onboarding_training",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        sa.Column("course_code", sa.Text(), nullable=False),
        sa.Column("completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_onboarding_training_id", sa.BigInteger(), nullable=True),
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
            "course_code = 'NEW_HIRE_ORIENTATION'",
            name=op.f("ck_staff_onboarding_training_course_code"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_onboarding_training_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_onboarding_training_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_onboarding_training_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_code"],
            ["erp.training_course.code"],
            name="fk_staff_onboarding_training_course_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_onboarding_training_id"],
            ["erp.staff_onboarding_training.id"],
            name="fk_staff_onboarding_training_replacement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_onboarding_training_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_onboarding_training_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_onboarding_training"),
        schema="erp",
    )
    op.create_index(
        "uq_staff_onboarding_training_active",
        "staff_onboarding_training",
        ["staff_id", "employment_id", "course_code"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL"),
    )

    op.create_table(
        "staff_periodic_training_status",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("course_code", sa.Text(), nullable=False),
        sa.Column("period_key", sa.Text(), nullable=False),
        sa.Column("completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_periodic_training_id", sa.BigInteger(), nullable=True),
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
            "course_code <> 'NEW_HIRE_ORIENTATION'",
            name=op.f("ck_staff_periodic_training_course_code"),
        ),
        sa.CheckConstraint(
            "period_key ~ '^[0-9]{4}$' OR period_key ~ '^[0-9]{4}-H[12]$'",
            name=op.f("ck_staff_periodic_training_period_key"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_periodic_training_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_periodic_training_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_code"],
            ["erp.training_course.code"],
            name="fk_staff_periodic_training_course_code",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_periodic_training_id"],
            ["erp.staff_periodic_training_status.id"],
            name="fk_staff_periodic_training_replacement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_periodic_training_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_periodic_training_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_periodic_training_status"),
        schema="erp",
    )
    op.create_index(
        "uq_staff_periodic_training_active",
        "staff_periodic_training_status",
        ["staff_id", "course_code", "period_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL"),
    )


def _seed_catalog() -> None:
    op.bulk_insert(
        sa.table(
            "training_course",
            sa.column("sort_order", sa.Integer()),
            sa.column("code", sa.Text()),
            sa.column("display_name", sa.Text()),
            sa.column("cycle_type", sa.Text()),
            sa.column("active", sa.Boolean()),
            schema="erp",
        ),
        [
            {
                **record,
                "active": True,
            }
            for record in TRAINING_COURSE_SEED
        ],
    )


def _create_cycle_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_staff_onboarding_training_course_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            course_cycle text;
        BEGIN
            SELECT cycle_type
            INTO course_cycle
            FROM erp.training_course
            WHERE code = NEW.course_code
              AND active IS TRUE;

            IF course_cycle IS DISTINCT FROM 'ON_HIRE' THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_TRAINING_INVALID_CYCLE';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_staff_onboarding_training_course_guard
        AFTER INSERT OR UPDATE
        ON erp.staff_onboarding_training
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_onboarding_training_course_guard();

        CREATE FUNCTION erp.fn_staff_periodic_training_cycle_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            course_cycle text;
        BEGIN
            SELECT cycle_type
            INTO course_cycle
            FROM erp.training_course
            WHERE code = NEW.course_code
              AND active IS TRUE;

            IF course_cycle IS NULL OR course_cycle = 'ON_HIRE' THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_TRAINING_INVALID_CYCLE';
            END IF;
            IF course_cycle = 'HALF_YEAR'
               AND NEW.period_key !~ '^[0-9]{4}-H[12]$'
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_TRAINING_PERIOD_INVALID';
            END IF;
            IF course_cycle = 'ANNUAL'
               AND NEW.period_key !~ '^[0-9]{4}$'
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_TRAINING_PERIOD_INVALID';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_staff_periodic_training_cycle_guard
        AFTER INSERT OR UPDATE
        ON erp.staff_periodic_training_status
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_periodic_training_cycle_guard();
        """
    )


def _grant_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT ON TABLE erp.training_course TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    erp.staff_onboarding_training,
                    erp.staff_periodic_training_status
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.training_course,
                    erp.staff_onboarding_training,
                    erp.staff_periodic_training_status
                FROM erp_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    erp.training_course,
                    erp.staff_onboarding_training,
                    erp.staff_periodic_training_status
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.training_course,
                    erp.staff_onboarding_training,
                    erp.staff_periodic_training_status
                FROM erp_backup;
                GRANT SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_backup;
                REVOKE USAGE ON ALL SEQUENCES IN SCHEMA erp FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_catalog_table()
    _create_fact_tables()
    _seed_catalog()
    _create_cycle_guards()
    _grant_runtime_roles()


def _revoke_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.training_course,
                    erp.staff_onboarding_training,
                    erp.staff_periodic_training_status
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.training_course,
                    erp.staff_onboarding_training,
                    erp.staff_periodic_training_status
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
        DROP TRIGGER IF EXISTS ct_staff_periodic_training_cycle_guard
            ON erp.staff_periodic_training_status;
        DROP FUNCTION IF EXISTS erp.fn_staff_periodic_training_cycle_guard();
        DROP TRIGGER IF EXISTS ct_staff_onboarding_training_course_guard
            ON erp.staff_onboarding_training;
        DROP FUNCTION IF EXISTS erp.fn_staff_onboarding_training_course_guard();
        """
    )
    op.drop_index(
        "uq_staff_periodic_training_active",
        table_name="staff_periodic_training_status",
        schema="erp",
    )
    op.drop_table("staff_periodic_training_status", schema="erp")
    op.drop_index(
        "uq_staff_onboarding_training_active",
        table_name="staff_onboarding_training",
        schema="erp",
    )
    op.drop_table("staff_onboarding_training", schema="erp")
    op.drop_table("training_course", schema="erp")
