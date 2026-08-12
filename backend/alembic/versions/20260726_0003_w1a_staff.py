"""Add the W1A staff vertical-slice schema and database guards.

Revision ID: 20260726_0003_w1a_staff
Revises: 20260724_0002
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260726_0003_w1a_staff"
down_revision: str | None = "20260724_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_period_audit_columns(table_name: str, *, include_created_by: bool) -> None:
    if include_created_by:
        op.add_column(
            table_name,
            sa.Column("created_by_account_id", sa.BigInteger(), nullable=True),
            schema="erp",
        )
    op.add_column(
        table_name,
        sa.Column("updated_by_account_id", sa.BigInteger(), nullable=True),
        schema="erp",
    )
    op.add_column(
        table_name,
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        schema="erp",
    )
    op.add_column(
        table_name,
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=True),
        schema="erp",
    )


def _seal_period_audit_columns(table_name: str, *, include_created_by: bool) -> None:
    actor_fk_stem = {
        "staff_employment": "fk_staff_employment",
        "staff_position_period": "fk_staff_position_period",
        "staff_operational_role_period": "fk_staff_role_period",
    }[table_name]
    if include_created_by:
        op.alter_column(table_name, "created_by_account_id", nullable=False, schema="erp")
        op.create_foreign_key(
            f"{actor_fk_stem}_created_by_account",
            table_name,
            "user_account",
            ["created_by_account_id"],
            ["id"],
            source_schema="erp",
            referent_schema="erp",
            ondelete="RESTRICT",
        )
    op.alter_column(table_name, "updated_by_account_id", nullable=False, schema="erp")
    op.alter_column(table_name, "updated_at_utc", nullable=False, schema="erp")
    op.alter_column(table_name, "row_version", nullable=False, schema="erp")
    op.create_foreign_key(
        f"{actor_fk_stem}_updated_by_account",
        table_name,
        "user_account",
        ["updated_by_account_id"],
        ["id"],
        source_schema="erp",
        referent_schema="erp",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f(f"ck_{table_name}_row_version_positive"),
        table_name,
        "row_version > 0",
        schema="erp",
    )


def _create_period_containment_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_staff_position_within_employment()
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

        CREATE CONSTRAINT TRIGGER ct_staff_position_within_employment
        AFTER INSERT OR UPDATE
        ON erp.staff_position_period
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_position_within_employment();
        """
    )
    op.execute(
        """
        CREATE FUNCTION erp.fn_staff_operational_role_within_employment()
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

        CREATE CONSTRAINT TRIGGER ct_staff_operational_role_within_employment
        AFTER INSERT OR UPDATE
        ON erp.staff_operational_role_period
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_operational_role_within_employment();
        """
    )
    op.execute(
        """
        CREATE FUNCTION erp.fn_staff_employment_child_periods_reverse_guard()
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

        CREATE CONSTRAINT TRIGGER ct_staff_employment_child_periods_reverse_guard
        AFTER UPDATE
        ON erp.staff_employment
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_staff_employment_child_periods_reverse_guard();
        """
    )


def _grant_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT ON ALL TABLES IN SCHEMA erp TO erp_app;
                GRANT INSERT, UPDATE ON TABLE
                    erp.center,
                    erp.business_number_counter,
                    erp.staff,
                    erp.staff_sensitive_identity,
                    erp.user_account,
                    erp.account_permission,
                    erp.auth_session,
                    erp.auth_event,
                    erp.auth_rate_limit_bucket,
                    erp.staff_employment,
                    erp.staff_position_period,
                    erp.staff_operational_role_period,
                    erp.audit_event,
                    erp.access_event,
                    erp.installation_state
                TO erp_app;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_app;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON ALL TABLES IN SCHEMA erp TO erp_backup;
                GRANT SELECT ON ALL SEQUENCES IN SCHEMA erp TO erp_backup;
                REVOKE USAGE ON ALL SEQUENCES IN SCHEMA erp FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    op.add_column("staff", sa.Column("phone_normalized", sa.Text(), nullable=True), schema="erp")
    op.create_index(
        "ix_staff_phone_normalized",
        "staff",
        ["phone_normalized"],
        unique=False,
        schema="erp",
    )
    op.create_check_constraint(
        op.f("ck_staff_sex_code"),
        "staff",
        "sex_code IN ('MALE','FEMALE','TEST')",
        schema="erp",
    )

    op.create_table(
        "staff_sensitive_identity",
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("resident_number_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("resident_number_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("resident_number_key_version", sa.Integer(), nullable=False),
        sa.Column("resident_number_lookup_hmac", sa.LargeBinary(), nullable=False),
        sa.Column(
            "encrypted_at_utc",
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
        sa.CheckConstraint(
            "octet_length(resident_number_ciphertext) > 0",
            name=op.f("ck_staff_sensitive_identity_ciphertext_nonempty"),
        ),
        sa.CheckConstraint(
            "octet_length(resident_number_nonce) = 12",
            name=op.f("ck_staff_sensitive_identity_nonce_length"),
        ),
        sa.CheckConstraint(
            "resident_number_key_version > 0",
            name=op.f("ck_staff_sensitive_identity_key_version_positive"),
        ),
        sa.CheckConstraint(
            "octet_length(resident_number_lookup_hmac) = 32",
            name=op.f("ck_staff_sensitive_identity_lookup_hmac_length"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_staff_sensitive_identity_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_sensitive_identity_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("staff_id", name="pk_staff_sensitive_identity"),
        sa.UniqueConstraint(
            "resident_number_lookup_hmac",
            name=op.f("uq_staff_sensitive_identity_lookup_hmac"),
        ),
        schema="erp",
    )

    _add_period_audit_columns("staff_employment", include_created_by=False)
    _add_period_audit_columns("staff_position_period", include_created_by=True)
    _add_period_audit_columns("staff_operational_role_period", include_created_by=True)

    op.execute(
        """
        UPDATE erp.staff_employment
        SET updated_by_account_id = created_by_account_id,
            updated_at_utc = created_at_utc,
            row_version = 1;

        UPDATE erp.staff_position_period child
        SET created_by_account_id = parent.created_by_account_id,
            updated_by_account_id = parent.created_by_account_id,
            updated_at_utc = child.created_at_utc,
            row_version = 1
        FROM erp.staff_employment parent
        WHERE parent.id = child.employment_id
          AND parent.staff_id = child.staff_id;

        UPDATE erp.staff_operational_role_period child
        SET created_by_account_id = parent.created_by_account_id,
            updated_by_account_id = parent.created_by_account_id,
            updated_at_utc = child.created_at_utc,
            row_version = 1
        FROM erp.staff_employment parent
        WHERE parent.id = child.employment_id
          AND parent.staff_id = child.staff_id;
        """
    )

    _seal_period_audit_columns("staff_employment", include_created_by=False)
    _seal_period_audit_columns("staff_position_period", include_created_by=True)
    _seal_period_audit_columns("staff_operational_role_period", include_created_by=True)

    op.create_check_constraint(
        op.f("ck_staff_operational_role_period_role_code_format"),
        "staff_operational_role_period",
        "role_code ~ '^[A-Z][A-Z0-9_]{0,49}$'",
        schema="erp",
    )

    _create_period_containment_guards()

    op.execute(
        """
        INSERT INTO erp.permission_definition
            (permission_code, name, description, active)
        VALUES
            (
                'STAFF_VIEW',
                '직원정보 조회',
                '직원 목록과 상세의 마스킹된 정보 조회',
                true
            ),
            (
                'STAFF_MANAGE',
                '직원정보 관리',
                '직원정보와 재직·직종·업무역할 관리 및 민감정보 단계인증 조회',
                true
            )
        ON CONFLICT (permission_code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            active = true;
        """
    )

    _grant_runtime_roles()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT ON ALL TABLES IN SCHEMA erp FROM erp_app;
                REVOKE INSERT, UPDATE ON TABLE
                    erp.center,
                    erp.business_number_counter,
                    erp.staff,
                    erp.staff_sensitive_identity,
                    erp.user_account,
                    erp.account_permission,
                    erp.auth_session,
                    erp.auth_event,
                    erp.auth_rate_limit_bucket,
                    erp.staff_employment,
                    erp.staff_position_period,
                    erp.staff_operational_role_period,
                    erp.audit_event,
                    erp.access_event,
                    erp.installation_state
                FROM erp_app;
                REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA erp FROM erp_app;
                REVOKE USAGE ON SCHEMA erp FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT ON ALL TABLES IN SCHEMA erp FROM erp_backup;
                REVOKE SELECT ON ALL SEQUENCES IN SCHEMA erp FROM erp_backup;
                REVOKE USAGE ON SCHEMA erp FROM erp_backup;
            END IF;
        END
        $$;
        """
    )
    # account_permission has RESTRICT FKs to permission_definition.  Remove
    # dependent assignments before removing the W1A seed rows so downgrade is
    # reversible even when the application has assigned these permissions.
    op.execute(
        """
        DELETE FROM erp.account_permission
        WHERE permission_code IN ('STAFF_VIEW', 'STAFF_MANAGE');

        DELETE FROM erp.permission_definition
        WHERE permission_code IN ('STAFF_VIEW', 'STAFF_MANAGE')
        """
    )

    op.execute(
        "DROP TRIGGER ct_staff_employment_child_periods_reverse_guard ON erp.staff_employment"
    )
    op.execute("DROP FUNCTION erp.fn_staff_employment_child_periods_reverse_guard()")
    op.execute(
        "DROP TRIGGER ct_staff_operational_role_within_employment "
        "ON erp.staff_operational_role_period"
    )
    op.execute("DROP FUNCTION erp.fn_staff_operational_role_within_employment()")
    op.execute("DROP TRIGGER ct_staff_position_within_employment ON erp.staff_position_period")
    op.execute("DROP FUNCTION erp.fn_staff_position_within_employment()")

    op.drop_constraint(
        op.f("ck_staff_operational_role_period_role_code_format"),
        "staff_operational_role_period",
        schema="erp",
        type_="check",
    )

    for table_name, include_created_by in (
        ("staff_operational_role_period", True),
        ("staff_position_period", True),
        ("staff_employment", False),
    ):
        actor_fk_stem = {
            "staff_employment": "fk_staff_employment",
            "staff_position_period": "fk_staff_position_period",
            "staff_operational_role_period": "fk_staff_role_period",
        }[table_name]
        op.drop_constraint(
            op.f(f"ck_{table_name}_row_version_positive"),
            table_name,
            schema="erp",
            type_="check",
        )
        op.drop_constraint(
            f"{actor_fk_stem}_updated_by_account",
            table_name,
            schema="erp",
            type_="foreignkey",
        )
        if include_created_by:
            op.drop_constraint(
                f"{actor_fk_stem}_created_by_account",
                table_name,
                schema="erp",
                type_="foreignkey",
            )
        op.drop_column(table_name, "row_version", schema="erp")
        op.drop_column(table_name, "updated_at_utc", schema="erp")
        op.drop_column(table_name, "updated_by_account_id", schema="erp")
        if include_created_by:
            op.drop_column(table_name, "created_by_account_id", schema="erp")

    op.drop_table("staff_sensitive_identity", schema="erp")
    op.drop_constraint(op.f("ck_staff_sex_code"), "staff", schema="erp", type_="check")
    op.drop_index("ix_staff_phone_normalized", table_name="staff", schema="erp")
    op.drop_column("staff", "phone_normalized", schema="erp")
