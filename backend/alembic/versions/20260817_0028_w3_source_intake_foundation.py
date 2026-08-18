"""Add the W3 source-intake foundation catalog.

Revision ID: 20260817_0028_w3_source_intake_foundation
Revises: 20260817_0027_w2_official_card_assignee_and_plan_replacement
Create Date: 2026-08-17

Immutable private content metadata, append-only receipts, source snapshots,
import run/attempt lineage, and receipt-local raw row addresses. Raw bytes are
not stored as BYTEA, generic target_type+target_id is not added, and this
slice has no target typed link.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_0028_w3_source_intake_foundation"
down_revision: str | None = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "w3_private_content",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("storage_locator", sa.Text(), nullable=False),
        sa.Column("quarantine_state", sa.Text(), nullable=False),
        sa.Column("legal_hold_state", sa.Text(), nullable=False),
        sa.Column("automatic_gc_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_private_content_digest_sha256"),
        ),
        sa.CheckConstraint("byte_size >= 0", name=op.f("ck_w3_private_content_byte_size")),
        sa.CheckConstraint(
            "btrim(media_type) <> ''",
            name=op.f("ck_w3_private_content_media_type"),
        ),
        sa.CheckConstraint(
            "storage_locator ~ '^w3-private:[0-9a-f]{32,}$' "
            "AND storage_locator NOT LIKE 'http%' "
            "AND position('://' in storage_locator) = 0",
            name=op.f("ck_w3_private_content_storage_locator"),
        ),
        sa.CheckConstraint(
            "quarantine_state IN ('NONE', 'QUARANTINED')",
            name=op.f("ck_w3_private_content_quarantine_state"),
        ),
        sa.CheckConstraint(
            "legal_hold_state IN ('NONE', 'HELD')",
            name=op.f("ck_w3_private_content_legal_hold_state"),
        ),
        sa.CheckConstraint(
            "automatic_gc_enabled IS FALSE",
            name=op.f("ck_w3_private_content_automatic_gc_off"),
        ),
        sa.UniqueConstraint("content_digest", name="uq_w3_private_content_content_digest"),
        sa.UniqueConstraint("id", "content_digest", name="uq_w3_private_content_id_digest"),
        sa.PrimaryKeyConstraint("id", name="pk_w3_private_content"),
        schema="erp",
    )

    op.create_table(
        "w3_source_snapshot",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('RFID', 'NHIS_SCHEDULE')",
            name=op.f("ck_w3_source_snapshot_source_type"),
        ),
        sa.CheckConstraint(
            "status IN ('CANDIDATE', 'ACTIVE', 'SUPERSEDED')",
            name=op.f("ck_w3_source_snapshot_status"),
        ),
        sa.UniqueConstraint(
            "source_type",
            "target_date",
            "content_digest",
            name="uq_w3_source_snapshot_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "content_id",
            "content_digest",
            name="uq_w3_source_snapshot_content_identity",
        ),
        sa.ForeignKeyConstraint(
            ["content_id", "content_digest"],
            ["erp.w3_private_content.id", "erp.w3_private_content.content_digest"],
            name="fk_w3_source_snapshot_content_identity",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_source_snapshot"),
        schema="erp",
    )
    op.create_index(
        "uq_w3_source_snapshot_one_active_per_source_date",
        "w3_source_snapshot",
        ["source_type", "target_date"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "w3_source_receipt",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_account_id", sa.BigInteger(), nullable=True),
        sa.Column("source_context_type", sa.Text(), nullable=False),
        sa.Column(
            "received_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(original_filename) <> ''",
            name=op.f("ck_w3_source_receipt_filename"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('USER_ACCOUNT', 'SYSTEM_RUN')",
            name=op.f("ck_w3_source_receipt_actor_type"),
        ),
        sa.CheckConstraint(
            "(actor_type = 'USER_ACCOUNT' AND actor_account_id IS NOT NULL) "
            "OR (actor_type = 'SYSTEM_RUN' AND actor_account_id IS NULL)",
            name=op.f("ck_w3_source_receipt_actor_pair"),
        ),
        sa.CheckConstraint(
            "source_context_type IN ('RFID_FILE', 'NHIS_SCHEDULE_FILE')",
            name=op.f("ck_w3_source_receipt_source_context_type"),
        ),
        sa.UniqueConstraint(
            "id",
            "snapshot_id",
            "content_id",
            "content_digest",
            name="uq_w3_source_receipt_lineage",
        ),
        sa.ForeignKeyConstraint(
            ["content_id", "content_digest"],
            ["erp.w3_private_content.id", "erp.w3_private_content.content_digest"],
            name="fk_w3_source_receipt_content_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.content_id",
                "erp.w3_source_snapshot.content_digest",
            ],
            name="fk_w3_source_receipt_snapshot_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_source_receipt_actor_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_source_receipt"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_source_receipt_content_id",
        "w3_source_receipt",
        ["content_id"],
        schema="erp",
    )

    op.create_table(
        "w3_import_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("parser_profile_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("apply_idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(parser_profile_version) <> ''",
            name=op.f("ck_w3_import_run_parser_profile_version"),
        ),
        sa.CheckConstraint(
            "status IN ("
            "'RECEIVED', 'PARSING', 'PREVIEW_READY', 'CONFIRMED', "
            "'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED')",
            name=op.f("ck_w3_import_run_status"),
        ),
        sa.CheckConstraint(
            "btrim(apply_idempotency_key) <> ''",
            name=op.f("ck_w3_import_run_apply_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "parser_profile_version",
            name="uq_w3_import_run_snapshot_profile",
        ),
        sa.UniqueConstraint(
            "apply_idempotency_key",
            name="uq_w3_import_run_apply_idempotency_key",
        ),
        sa.UniqueConstraint(
            "id",
            "snapshot_id",
            "content_id",
            "content_digest",
            name="uq_w3_import_run_lineage",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id", "snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_receipt.id",
                "erp.w3_source_receipt.snapshot_id",
                "erp.w3_source_receipt.content_id",
                "erp.w3_source_receipt.content_digest",
            ],
            name="fk_w3_import_run_receipt_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.content_id",
                "erp.w3_source_snapshot.content_digest",
            ],
            name="fk_w3_import_run_snapshot_identity",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_import_run"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_import_run_snapshot_id",
        "w3_import_run",
        ["snapshot_id"],
        schema="erp",
    )

    op.create_table(
        "w3_import_attempt",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("content_id", sa.BigInteger(), nullable=False),
        sa.Column("content_digest", sa.Text(), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("attempt_ordinal > 0", name=op.f("ck_w3_import_attempt_ordinal")),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED_RETRYABLE', 'BLOCKED')",
            name=op.f("ck_w3_import_attempt_status"),
        ),
        sa.UniqueConstraint(
            "import_run_id",
            "attempt_ordinal",
            name="uq_w3_import_attempt_ordinal",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id", "snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_receipt.id",
                "erp.w3_source_receipt.snapshot_id",
                "erp.w3_source_receipt.content_id",
                "erp.w3_source_receipt.content_digest",
            ],
            name="fk_w3_import_attempt_receipt_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id", "snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_import_run.id",
                "erp.w3_import_run.snapshot_id",
                "erp.w3_import_run.content_id",
                "erp.w3_import_run.content_digest",
            ],
            name="fk_w3_import_attempt_run_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.content_id",
                "erp.w3_source_snapshot.content_digest",
            ],
            name="fk_w3_import_attempt_snapshot_identity",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_import_attempt"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_import_attempt_import_run_id",
        "w3_import_attempt",
        ["import_run_id"],
        schema="erp",
    )

    op.create_table(
        "w3_source_row",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column("sheet_ref", sa.Text(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(sheet_ref) <> '' AND position('://' in sheet_ref) = 0",
            name=op.f("ck_w3_source_row_sheet_ref"),
        ),
        sa.CheckConstraint("source_row_number > 0", name=op.f("ck_w3_source_row_number")),
        sa.UniqueConstraint(
            "receipt_id",
            "sheet_ref",
            "source_row_number",
            name="uq_w3_source_row_physical_address",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["erp.w3_source_receipt.id"],
            name="fk_w3_source_row_receipt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_source_row"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_source_row_receipt_id",
        "w3_source_row",
        ["receipt_id"],
        schema="erp",
    )

    # Identity sequences inherit the table owner. Direct sequence ownership
    # changes are rejected for identity sequences (SQLSTATE 0A000).
    op.execute("ALTER TABLE erp.w3_private_content OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_source_snapshot OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_source_receipt OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_import_run OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_import_attempt OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_source_row OWNER TO erp_owner")


def downgrade() -> None:
    op.drop_index("ix_w3_source_row_receipt_id", table_name="w3_source_row", schema="erp")
    op.drop_table("w3_source_row", schema="erp")
    op.drop_index(
        "ix_w3_import_attempt_import_run_id",
        table_name="w3_import_attempt",
        schema="erp",
    )
    op.drop_table("w3_import_attempt", schema="erp")
    op.drop_index("ix_w3_import_run_snapshot_id", table_name="w3_import_run", schema="erp")
    op.drop_table("w3_import_run", schema="erp")
    op.drop_index("ix_w3_source_receipt_content_id", table_name="w3_source_receipt", schema="erp")
    op.drop_table("w3_source_receipt", schema="erp")
    op.drop_index(
        "uq_w3_source_snapshot_one_active_per_source_date",
        table_name="w3_source_snapshot",
        schema="erp",
    )
    op.drop_table("w3_source_snapshot", schema="erp")
    op.drop_table("w3_private_content", schema="erp")
