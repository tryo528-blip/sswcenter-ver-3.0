"""Create Wave 0 staff bootstrap, auth, audit, and worker ledgers.

Revision ID: 20260724_0002
Revises: 20260724_0001
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260724_0002"
down_revision: str | None = "20260724_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staff",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("sex_code", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_staff"),
        schema="erp",
    )

    op.create_table(
        "user_account",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("account_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role_code", sa.Text(), nullable=False),
        sa.Column("pin_hash", sa.Text(), nullable=False),
        sa.Column("pin_lookup_hmac", sa.LargeBinary(), nullable=False),
        sa.Column("pin_key_version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("login_allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_login_at_utc", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "role_code IN ('ADMIN','USER')",
            name="ck_user_account_role_code",
        ),
        sa.CheckConstraint(
            "failed_count >= 0",
            name="ck_user_account_failed_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_user_account_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_account"),
        sa.UniqueConstraint("account_code", name="uq_user_account_account_code"),
        sa.UniqueConstraint("pin_lookup_hmac", name="uq_user_account_pin_lookup_hmac"),
        sa.UniqueConstraint("staff_id", name="uq_user_account_staff_id"),
        schema="erp",
    )

    op.create_table(
        "permission_definition",
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("permission_code", name="pk_permission_definition"),
        schema="erp",
    )
    op.execute(
        """
        INSERT INTO erp.permission_definition
            (permission_code, name, description, active)
        VALUES
            ('COPAY_USE', '본인부담금 사용', NULL, true),
            ('IO_IMPORT_USE', '입출력 사용', NULL, true),
            ('OUTPUT_USE', '출력물 사용', NULL, true),
            ('SW_MENU_USE', '사회복지사 메뉴 사용', NULL, true)
        ON CONFLICT (permission_code) DO NOTHING
        """
    )

    op.create_table(
        "account_permission",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.Column("granted_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "granted_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["erp.user_account.id"],
            name="fk_account_permission_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_account_id"],
            ["erp.user_account.id"],
            name="fk_account_permission_granted_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            ["erp.permission_definition.permission_code"],
            name="fk_account_permission_permission_code_permission_definition",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_permission"),
        schema="erp",
    )
    op.create_index(
        "uq_account_permission_active",
        "account_permission",
        ["account_id", "permission_code"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("revoked_at_utc IS NULL"),
    )

    op.create_table(
        "auth_session",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("session_token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("account_session_version", sa.Integer(), nullable=False),
        sa.Column("issued_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("client_fingerprint_hash", sa.LargeBinary(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["erp.user_account.id"],
            name="fk_auth_session_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_session"),
        sa.UniqueConstraint(
            "session_token_hash",
            name="uq_auth_session_session_token_hash",
        ),
        schema="erp",
    )

    op.create_table(
        "auth_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("client_device_hash", sa.LargeBinary(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["erp.user_account.id"],
            name="fk_auth_event_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_event"),
        schema="erp",
    )

    op.create_table(
        "auth_rate_limit_bucket",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("bucket_type", sa.Text(), nullable=False),
        sa.Column("bucket_key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("window_started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("blocked_until_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "bucket_type IN ('DEVICE_UNKNOWN','IP_UNKNOWN','SERVER_UNKNOWN')",
            name="ck_auth_rate_limit_bucket_bucket_type",
        ),
        sa.CheckConstraint(
            "failure_count >= 0",
            name="ck_auth_rate_limit_bucket_failure_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_rate_limit_bucket"),
        sa.UniqueConstraint(
            "bucket_type",
            "bucket_key_hash",
            name="uq_auth_rate_limit_bucket_bucket_type",
        ),
        schema="erp",
    )

    op.create_table(
        "staff_employment",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_no", sa.Integer(), nullable=False),
        sa.Column("staff_no", sa.Text(), nullable=False),
        sa.Column("staff_no_year", sa.Integer(), nullable=False),
        sa.Column("staff_no_sequence", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "employment_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("end_reason_code", sa.Text(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_employment_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_staff_employment_date_order",
        ),
        postgresql.ExcludeConstraint(
            ("staff_id", "="),
            ("employment_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_employment_period",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_employment_created_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_employment_id"],
            ["erp.staff_employment.id"],
            name="fk_staff_employment_replacement_employment_id_staff_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_employment_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_employment"),
        sa.UniqueConstraint("staff_id", "employment_no", name="uq_staff_employment_no"),
        sa.UniqueConstraint("staff_id", "id", name="uq_staff_employment_staff_id_id"),
        sa.UniqueConstraint(
            "staff_no_year",
            "staff_no_sequence",
            name="uq_staff_employment_year_sequence",
        ),
        sa.UniqueConstraint("staff_no", name="uq_staff_employment_staff_no"),
        schema="erp",
    )

    op.create_table(
        "staff_position_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        sa.Column("position_code", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "position_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_staff_position_period_date_order",
        ),
        sa.CheckConstraint(
            "position_code IN ('CARE_WORKER','SOCIAL_WORKER','MANAGER','NURSE','OTHER')",
            name="ck_staff_position_period_position_code",
        ),
        postgresql.ExcludeConstraint(
            ("staff_id", "="),
            ("position_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_position_period",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_position_period_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_id"],
            ["erp.staff_position_period.id"],
            name="fk_staff_position_period_replacement_id_staff_position_period",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_position_period_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_position_period"),
        schema="erp",
    )

    op.create_table(
        "staff_operational_role_period",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        sa.Column("role_code", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "role_period",
            postgresql.DATERANGE(),
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_staff_operational_role_period_date_order",
        ),
        postgresql.ExcludeConstraint(
            ("staff_id", "="),
            ("role_code", "="),
            ("role_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_operational_role_period",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_operational_role_period_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_id"],
            ["erp.staff_operational_role_period.id"],
            name="fk_staff_role_period_replacement",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_operational_role_period_staff_id_staff",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_operational_role_period"),
        schema="erp",
    )

    op.create_table(
        "system_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_type", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "queued_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_attempt_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("requested_by_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "request_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_system_run_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name="ck_system_run_max_attempts_positive",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','WARNING','FAILED','CANCELED')",
            name="ck_system_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_account_id"],
            ["erp.user_account.id"],
            name="fk_system_run_requested_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_system_run"),
        schema="erp",
    )
    op.create_index(
        "uq_system_run_idempotency",
        "system_run",
        ["run_type", "idempotency_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "system_run_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("system_run_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=True),
        sa.Column(
            "detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "occurred_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["system_run_id"],
            ["erp.system_run.id"],
            name="fk_system_run_event_system_run_id_system_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_system_run_event"),
        schema="erp",
    )

    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_account_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("action_code", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_pk", sa.BigInteger(), nullable=True),
        sa.Column(
            "before_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("source_run_id", sa.BigInteger(), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_from", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "actor_kind IN ('USER','SYSTEM','IMPORT','OCR','MIGRATION')",
            name="ck_audit_event_actor_kind",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["erp.user_account.id"],
            name="fk_audit_event_actor_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["erp.system_run.id"],
            name="fk_audit_event_source_run_id_system_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_event"),
        schema="erp",
    )

    op.create_table(
        "access_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("access_type", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_pk", sa.BigInteger(), nullable=True),
        sa.Column("document_record_id", sa.BigInteger(), nullable=True),
        sa.Column("generated_document_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["erp.user_account.id"],
            name="fk_access_event_account_id_user_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_event"),
        schema="erp",
    )

    op.create_foreign_key(
        "fk_installation_state_first_admin_account_id_user_account",
        "installation_state",
        "user_account",
        ["first_admin_account_id"],
        ["id"],
        source_schema="erp",
        referent_schema="erp",
        ondelete="RESTRICT",
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('erp.auth_session') IS NULL THEN
                RAISE EXCEPTION 'auth_session table is missing';
            END IF;
            IF to_regclass('erp.system_run') IS NULL THEN
                RAISE EXCEPTION 'system_run table is missing';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_extension
                WHERE extname = 'btree_gist'
            ) THEN
                RAISE EXCEPTION 'btree_gist extension is missing';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_installation_state_first_admin_account_id_user_account",
        "installation_state",
        schema="erp",
        type_="foreignkey",
    )
    op.drop_table("access_event", schema="erp")
    op.drop_table("audit_event", schema="erp")
    op.drop_table("system_run_event", schema="erp")
    op.drop_index("uq_system_run_idempotency", table_name="system_run", schema="erp")
    op.drop_table("system_run", schema="erp")
    op.drop_table("staff_operational_role_period", schema="erp")
    op.drop_table("staff_position_period", schema="erp")
    op.drop_table("staff_employment", schema="erp")
    op.drop_table("auth_rate_limit_bucket", schema="erp")
    op.drop_table("auth_event", schema="erp")
    op.drop_table("auth_session", schema="erp")
    op.drop_index(
        "uq_account_permission_active",
        table_name="account_permission",
        schema="erp",
    )
    op.drop_table("account_permission", schema="erp")
    op.drop_table("permission_definition", schema="erp")
    op.drop_table("user_account", schema="erp")
    op.drop_table("staff", schema="erp")
