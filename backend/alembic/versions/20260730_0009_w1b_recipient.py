"""Add the W1B recipient, guardian, payer, and internal mapping ledgers.

Revision ID: 20260730_0009_w1b_recipient
Revises: 20260728_0008_w1a_staff_legacy_mapping
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260730_0009_w1b_recipient"
down_revision: str | None = "20260728_0008_w1a_staff_legacy_mapping"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "recipient",
    "recipient_legacy_mapping",
    "recipient_guardian",
    "recipient_guardian_primary_period",
    "recipient_payer_snapshot",
)


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


def _create_recipient_table() -> None:
    op.create_table(
        "recipient",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("sex_code", sa.Text(), nullable=False),
        sa.Column("recipient_no", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("home_phone", sa.Text(), nullable=True),
        sa.Column("mobile_phone", sa.Text(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "btrim(name) <> ''",
            name=op.f("ck_recipient_name_nonblank"),
        ),
        sa.CheckConstraint(
            "sex_code IN ('MALE','FEMALE','TEST')",
            name=op.f("ck_recipient_sex_code"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_row_version_positive"),
        ),
        *_actor_constraints("recipient"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient"),
        sa.UniqueConstraint("recipient_no", name="uq_recipient_recipient_no"),
        schema="erp",
    )
    op.execute(
        """
        CREATE FUNCTION erp.fn_recipient_no_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.recipient_no IS NOT NULL
               AND NEW.recipient_no IS DISTINCT FROM OLD.recipient_no THEN
                RAISE EXCEPTION 'recipient_no is immutable after issuance'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE TRIGGER bu_recipient_no_immutable
        BEFORE UPDATE OF recipient_no ON erp.recipient
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_recipient_no_immutable();
        """
    )


def _create_guardian_table() -> None:
    op.create_table(
        "recipient_guardian",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("relationship_text", sa.Text(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "btrim(name) <> ''",
            name=op.f("ck_recipient_guardian_name_nonblank"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_guardian_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_guardian_recipient_id_recipient",
            ondelete="RESTRICT",
        ),
        *_actor_constraints("recipient_guardian"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_guardian"),
        sa.UniqueConstraint(
            "recipient_id",
            "id",
            name="uq_recipient_guardian_recipient_id_id",
        ),
        schema="erp",
    )


def _create_primary_period_table() -> None:
    op.create_table(
        "recipient_guardian_primary_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("guardian_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "effective_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_primary_guardian_period_id",
            sa.BigInteger(),
            nullable=True,
        ),
        *_actor_columns(),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name=op.f("ck_recipient_guardian_primary_period_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_guardian_primary_period_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("effective_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_guardian_primary_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_guardian_primary_period_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["guardian_id"],
            ["erp.recipient_guardian.id"],
            name="fk_recipient_guardian_primary_period_guardian",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "guardian_id"],
            ["erp.recipient_guardian.recipient_id", "erp.recipient_guardian.id"],
            name="fk_recipient_guardian_primary_period_recipient_guardian",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_primary_guardian_period_id"],
            ["erp.recipient_guardian_primary_period.id"],
            name="fk_recipient_guardian_primary_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_guardian_primary_period"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_guardian_primary_period"),
        schema="erp",
    )


def _create_payer_snapshot_table() -> None:
    op.create_table(
        "recipient_payer_snapshot",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("relationship_text", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "effective_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_payer_snapshot_id", sa.BigInteger(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "btrim(name) <> ''",
            name=op.f("ck_recipient_payer_snapshot_name_nonblank"),
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name=op.f("ck_recipient_payer_snapshot_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_payer_snapshot_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("effective_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_payer_snapshot_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_payer_snapshot_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_payer_snapshot_id"],
            ["erp.recipient_payer_snapshot.id"],
            name="fk_recipient_payer_snapshot_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_payer_snapshot"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_payer_snapshot"),
        schema="erp",
    )


def _create_legacy_mapping_table() -> None:
    op.create_table(
        "recipient_legacy_mapping",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_system_code", sa.Text(), nullable=False),
        sa.Column("legacy_recipient_key", sa.Text(), nullable=True),
        sa.Column("legacy_attachment_key", sa.Text(), nullable=True),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_fingerprint", sa.LargeBinary(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replacement_recipient_legacy_mapping_id",
            sa.BigInteger(),
            nullable=True,
        ),
        *_actor_columns(),
        sa.CheckConstraint(
            "btrim(source_system_code) <> ''",
            name=op.f("ck_recipient_legacy_mapping_source_system_code_nonblank"),
        ),
        sa.CheckConstraint(
            "legacy_recipient_key IS NOT NULL OR legacy_attachment_key IS NOT NULL",
            name=op.f("ck_recipient_legacy_mapping_key_present"),
        ),
        sa.CheckConstraint(
            "legacy_recipient_key IS NULL OR btrim(legacy_recipient_key) <> ''",
            name=op.f("ck_recipient_legacy_mapping_recipient_key_nonblank"),
        ),
        sa.CheckConstraint(
            "legacy_attachment_key IS NULL OR btrim(legacy_attachment_key) <> ''",
            name=op.f("ck_recipient_legacy_mapping_attachment_key_nonblank"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_legacy_mapping_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_legacy_mapping_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_recipient_legacy_mapping_id"],
            ["erp.recipient_legacy_mapping.id"],
            name="fk_recipient_legacy_mapping_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("recipient_legacy_mapping"),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_legacy_mapping"),
        schema="erp",
    )
    op.create_index(
        "uq_recipient_legacy_mapping_active_recipient_key",
        "recipient_legacy_mapping",
        ["source_system_code", "legacy_recipient_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("invalidated_at_utc IS NULL AND legacy_recipient_key IS NOT NULL"),
    )
    op.create_index(
        "uq_recipient_legacy_mapping_active_attachment_key",
        "recipient_legacy_mapping",
        ["source_system_code", "legacy_attachment_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text(
            "invalidated_at_utc IS NULL AND legacy_attachment_key IS NOT NULL"
        ),
    )


def _seed_permissions() -> None:
    op.execute(
        """
        INSERT INTO erp.permission_definition
            (permission_code, name, description, active)
        VALUES
            (
                'RECIPIENT_VIEW',
                '수급자정보 조회',
                '수급자와 보호자 및 납부자 이력 조회',
                true
            ),
            (
                'RECIPIENT_MANAGE',
                '수급자정보 관리',
                '수급자와 보호자 및 대표·납부자 이력 관리',
                true
            )
        ON CONFLICT (permission_code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            active = true;
        """
    )


def _grant_runtime_roles() -> None:
    table_list = ",\n                    ".join(f"erp.{name}" for name in _TABLES)
    sequence_list = ",\n                    ".join(f"erp.{name}_id_seq" for name in _TABLES)
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
    _create_recipient_table()
    _create_guardian_table()
    _create_primary_period_table()
    _create_payer_snapshot_table()
    _create_legacy_mapping_table()
    _seed_permissions()
    _grant_runtime_roles()


def _revoke_runtime_roles() -> None:
    table_list = ",\n                    ".join(f"erp.{name}" for name in _TABLES)
    sequence_list = ",\n                    ".join(f"erp.{name}_id_seq" for name in _TABLES)
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
    op.execute(
        """
        DELETE FROM erp.account_permission
        WHERE permission_code IN ('RECIPIENT_VIEW', 'RECIPIENT_MANAGE');

        DELETE FROM erp.permission_definition
        WHERE permission_code IN ('RECIPIENT_VIEW', 'RECIPIENT_MANAGE');
        """
    )
    op.drop_index(
        "uq_recipient_legacy_mapping_active_attachment_key",
        table_name="recipient_legacy_mapping",
        schema="erp",
    )
    op.drop_index(
        "uq_recipient_legacy_mapping_active_recipient_key",
        table_name="recipient_legacy_mapping",
        schema="erp",
    )
    op.drop_table("recipient_legacy_mapping", schema="erp")
    op.drop_table("recipient_payer_snapshot", schema="erp")
    op.drop_table("recipient_guardian_primary_period", schema="erp")
    op.drop_table("recipient_guardian", schema="erp")
    op.execute("DROP TRIGGER bu_recipient_no_immutable ON erp.recipient")
    op.execute("DROP FUNCTION erp.fn_recipient_no_immutable()")
    op.drop_table("recipient", schema="erp")
