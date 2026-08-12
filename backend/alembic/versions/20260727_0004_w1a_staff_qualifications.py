"""Add W1A service catalogs, license facts, and qualification periods.

Revision ID: 20260727_0004_w1a_staff_qualifications
Revises: 20260726_0003_w1a_staff
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260727_0004_w1a_staff_qualifications"
down_revision: str | None = "20260726_0003_w1a_staff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERVICE_GROUP_SEED = (
    {"code": "LONG_TERM_CARE", "display_name": "장기요양"},
    {"code": "LOCAL_CARE", "display_name": "지역돌봄 연계"},
    {"code": "BARO_CARE", "display_name": "바로돌봄"},
)
SERVICE_TYPE_SEED = (
    {"group_code": "LONG_TERM_CARE", "code": "HOME_CARE", "display_name": "방문요양"},
    {"group_code": "LONG_TERM_CARE", "code": "HOME_BATH", "display_name": "방문목욕"},
    {"group_code": "LOCAL_CARE", "code": "TEMP_HOME_CARE", "display_name": "일시재가"},
    {"group_code": "LOCAL_CARE", "code": "HOSPITAL_ESCORT", "display_name": "병원동행"},
    {"group_code": "BARO_CARE", "code": "BARO_CARE", "display_name": "바로돌봄"},
)
LICENSE_TYPE_SEED = (
    {"code": "CARE_WORKER", "display_name": "요양보호사"},
    {"code": "SOCIAL_WORKER", "display_name": "사회복지사"},
    {"code": "NURSE", "display_name": "간호사"},
)

# Stable service-layer codes are kept here as migration evidence as well as in
# the domain error contract.  They must not be replaced with raw SQL errors.
VS2_STABLE_ERROR_CODES = (
    "STAFF_LICENSE_DUPLICATE",
    "STAFF_LICENSE_NOT_FOUND",
    "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH",
    "STAFF_SERVICE_QUALIFICATION_CONFLICT",
)
VS2_AUDIT_TABLE = "audit_event"


def _create_catalog_tables() -> None:
    op.create_table(
        "service_group",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_service_group"),
        sa.UniqueConstraint("code", name="uq_service_group_code"),
        schema="erp",
    )
    op.create_table(
        "service_type",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("service_group_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_group_id"],
            ["erp.service_group.id"],
            name="fk_service_type_service_group_id_service_group",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_type"),
        sa.UniqueConstraint("code", name="uq_service_type_code"),
        schema="erp",
    )
    op.create_table(
        "license_type",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_license_type"),
        sa.UniqueConstraint("code", name="uq_license_type_code"),
        schema="erp",
    )


def _create_fact_tables() -> None:
    op.create_table(
        "staff_license",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("license_type_id", sa.BigInteger(), nullable=False),
        sa.Column("license_number", sa.Text(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_license_id", sa.BigInteger(), nullable=True),
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
            name=op.f("ck_staff_license_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_license_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["license_type_id"],
            ["erp.license_type.id"],
            name="fk_staff_license_license_type_id_license_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_license_id"],
            ["erp.staff_license.id"],
            name="fk_staff_license_replacement_license_id_staff_license",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_license_created_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_license_updated_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_license"),
        sa.UniqueConstraint("staff_id", "id", name="uq_staff_license_staff_id_id"),
        schema="erp",
    )
    op.create_index(
        "uq_staff_license_type_number_active",
        "staff_license",
        ["license_type_id", "license_number"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL"),
    )

    op.create_table(
        "staff_service_qualification_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        sa.Column("service_type_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "qualification_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("source_license_id", sa.BigInteger(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_qualification_id", sa.BigInteger(), nullable=True),
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
            "end_date IS NULL OR start_date <= end_date",
            name=op.f("ck_staff_service_qualification_period_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_service_qualification_period_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("staff_id", "="),
            ("service_type_id", "="),
            ("qualification_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_service_qualification_period",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_service_qualification_period_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_service_qualification_period_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_staff_service_qualification_service_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "source_license_id"],
            ["erp.staff_license.staff_id", "erp.staff_license.id"],
            name="fk_staff_service_qualification_period_source_license",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_qualification_id"],
            ["erp.staff_service_qualification_period.id"],
            name="fk_staff_service_qualification_period_replacement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_service_qualification_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_service_qualification_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_service_qualification_period"),
        schema="erp",
    )


def _seed_catalog() -> None:
    op.execute(
        """
        INSERT INTO erp.service_group (code, display_name, active)
        VALUES
            ('LONG_TERM_CARE', '장기요양', true),
            ('LOCAL_CARE', '지역돌봄 연계', true),
            ('BARO_CARE', '바로돌봄', true);

        INSERT INTO erp.service_type (service_group_id, code, display_name, active)
        SELECT g.id, v.code, v.display_name, true
        FROM (
            VALUES
                ('LONG_TERM_CARE', 'HOME_CARE', '방문요양'),
                ('LONG_TERM_CARE', 'HOME_BATH', '방문목욕'),
                ('LOCAL_CARE', 'TEMP_HOME_CARE', '일시재가'),
                ('LOCAL_CARE', 'HOSPITAL_ESCORT', '병원동행'),
                ('BARO_CARE', 'BARO_CARE', '바로돌봄')
        ) AS v(group_code, code, display_name)
        JOIN erp.service_group AS g ON g.code = v.group_code;

        INSERT INTO erp.license_type (code, display_name, active)
        VALUES
            ('CARE_WORKER', '요양보호사', true),
            ('SOCIAL_WORKER', '사회복지사', true),
            ('NURSE', '간호사', true);
        """
    )


def _create_qualification_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_staff_service_qualification_within_employment()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_start date;
            parent_end date;
        BEGIN
            IF NEW.invalidated_at_utc IS NOT NULL THEN
                RETURN NEW;
            END IF;

            SELECT start_date, end_date
            INTO parent_start, parent_end
            FROM erp.staff_employment
            WHERE id = NEW.employment_id
              AND staff_id = NEW.staff_id
              AND invalidated_at_utc IS NULL;

            IF NOT FOUND
               OR NEW.start_date < parent_start
               OR (
                    parent_end IS NOT NULL
                    AND (NEW.end_date IS NULL OR NEW.end_date > parent_end)
               )
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_PERIOD_OUTSIDE_EMPLOYMENT';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_staff_service_qualification_within_employment
        AFTER INSERT OR UPDATE
        ON erp.staff_service_qualification_period
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_service_qualification_within_employment();

        CREATE FUNCTION erp.fn_staff_service_qualification_source_license_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_invalidated_at timestamptz;
        BEGIN
            IF NEW.source_license_id IS NULL OR NEW.invalidated_at_utc IS NOT NULL THEN
                RETURN NEW;
            END IF;

            SELECT invalidated_at_utc
            INTO source_invalidated_at
            FROM erp.staff_license
            WHERE staff_id = NEW.staff_id
              AND id = NEW.source_license_id;

            IF NOT FOUND OR source_invalidated_at IS NOT NULL THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_staff_service_qualification_source_license_guard
        AFTER INSERT OR UPDATE
        ON erp.staff_service_qualification_period
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_service_qualification_source_license_guard();
        """
    )

    # Extend ct_staff_employment_child_periods_reverse_guard without changing
    # the existing trigger name or its DEFERRABLE INITIALLY DEFERRED behavior.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION erp.fn_staff_employment_child_periods_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM erp.staff_position_period child
                WHERE child.employment_id = NEW.id
                  AND child.staff_id = NEW.staff_id
                  AND child.invalidated_at_utc IS NULL
                  AND (
                      NEW.invalidated_at_utc IS NOT NULL
                      OR child.start_date < NEW.start_date
                      OR (
                          NEW.end_date IS NOT NULL
                          AND (child.end_date IS NULL OR child.end_date > NEW.end_date)
                      )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM erp.staff_operational_role_period child
                WHERE child.employment_id = NEW.id
                  AND child.staff_id = NEW.staff_id
                  AND child.invalidated_at_utc IS NULL
                  AND (
                      NEW.invalidated_at_utc IS NOT NULL
                      OR child.start_date < NEW.start_date
                      OR (
                          NEW.end_date IS NOT NULL
                          AND (child.end_date IS NULL OR child.end_date > NEW.end_date)
                      )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM erp.staff_service_qualification_period child
                WHERE child.employment_id = NEW.id
                  AND child.staff_id = NEW.staff_id
                  AND child.invalidated_at_utc IS NULL
                  AND (
                      NEW.invalidated_at_utc IS NOT NULL
                      OR child.start_date < NEW.start_date
                      OR (
                          NEW.end_date IS NOT NULL
                          AND (child.end_date IS NULL OR child.end_date > NEW.end_date)
                      )
                  )
            )
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_PERIOD_OUTSIDE_EMPLOYMENT';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )


def _grant_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT ON TABLE
                    erp.service_group,
                    erp.service_type,
                    erp.license_type,
                    erp.staff_license,
                    erp.staff_service_qualification_period
                TO erp_app;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.service_group,
                    erp.service_type,
                    erp.license_type
                FROM erp_app;
                GRANT INSERT, UPDATE ON TABLE
                    erp.staff_license,
                    erp.staff_service_qualification_period
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.staff_license,
                    erp.staff_service_qualification_period
                FROM erp_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    erp.service_group,
                    erp.service_type,
                    erp.license_type,
                    erp.staff_license,
                    erp.staff_service_qualification_period
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.service_group,
                    erp.service_type,
                    erp.license_type,
                    erp.staff_license,
                    erp.staff_service_qualification_period
                FROM erp_backup;
                GRANT SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_backup;
                REVOKE USAGE ON ALL SEQUENCES IN SCHEMA erp FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def _resize_alembic_version_column(*, length: int) -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32 if length > 32 else 64),
        type_=sa.String(length=length),
        schema="erp",
    )


def upgrade() -> None:
    _resize_alembic_version_column(length=64)
    _create_catalog_tables()
    _create_fact_tables()
    _seed_catalog()
    _create_qualification_guards()
    _grant_runtime_roles()


def _restore_w1a_vs1_reverse_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION erp.fn_staff_employment_child_periods_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM erp.staff_position_period child
                WHERE child.employment_id = NEW.id
                  AND child.staff_id = NEW.staff_id
                  AND child.invalidated_at_utc IS NULL
                  AND (
                      NEW.invalidated_at_utc IS NOT NULL
                      OR child.start_date < NEW.start_date
                      OR (
                          NEW.end_date IS NOT NULL
                          AND (child.end_date IS NULL OR child.end_date > NEW.end_date)
                      )
                  )
            ) OR EXISTS (
                SELECT 1
                FROM erp.staff_operational_role_period child
                WHERE child.employment_id = NEW.id
                  AND child.staff_id = NEW.staff_id
                  AND child.invalidated_at_utc IS NULL
                  AND (
                      NEW.invalidated_at_utc IS NOT NULL
                      OR child.start_date < NEW.start_date
                      OR (
                          NEW.end_date IS NOT NULL
                          AND (child.end_date IS NULL OR child.end_date > NEW.end_date)
                      )
                  )
            )
            THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'STAFF_PERIOD_OUTSIDE_EMPLOYMENT';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )


def _revoke_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.service_group,
                    erp.service_type,
                    erp.license_type,
                    erp.staff_license,
                    erp.staff_service_qualification_period
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.service_group,
                    erp.service_type,
                    erp.license_type,
                    erp.staff_license,
                    erp.staff_service_qualification_period
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    _revoke_runtime_roles()
    op.execute(
        "DROP TRIGGER IF EXISTS ct_staff_service_qualification_source_license_guard "
        "ON erp.staff_service_qualification_period"
    )
    op.execute("DROP FUNCTION IF EXISTS erp.fn_staff_service_qualification_source_license_guard()")
    op.execute(
        "DROP TRIGGER IF EXISTS ct_staff_service_qualification_within_employment "
        "ON erp.staff_service_qualification_period"
    )
    op.execute("DROP FUNCTION IF EXISTS erp.fn_staff_service_qualification_within_employment()")
    op.drop_table("staff_service_qualification_period", schema="erp")
    op.drop_index(
        "uq_staff_license_type_number_active",
        table_name="staff_license",
        schema="erp",
    )
    op.drop_table("staff_license", schema="erp")
    op.drop_table("license_type", schema="erp")
    op.drop_table("service_type", schema="erp")
    op.drop_table("service_group", schema="erp")
    _restore_w1a_vs1_reverse_guard()
