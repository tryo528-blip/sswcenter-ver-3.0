"""SQLAlchemy mappings for the W3 source-intake foundation.

This slice records immutable content metadata, append-only receipts, source
snapshots, import lineage, and receipt-local raw row addresses. It does not
add a target typed link; matcher/APPLY slices own that later.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from app.db.base import Base

FOUNDATION_HAS_TARGET_LINK = False


class W3PrivateContent(Base):
    __tablename__ = "w3_private_content"
    __table_args__ = (
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_private_content_digest_sha256"),
        ),
        CheckConstraint("byte_size >= 0", name=conv("ck_w3_private_content_byte_size")),
        CheckConstraint(
            "btrim(media_type) <> ''",
            name=conv("ck_w3_private_content_media_type"),
        ),
        CheckConstraint(
            "storage_locator ~ '^w3-private:[0-9a-f]{32,}$' "
            "AND storage_locator NOT LIKE 'http%' "
            "AND position('://' in storage_locator) = 0",
            name=conv("ck_w3_private_content_storage_locator"),
        ),
        CheckConstraint(
            "quarantine_state IN ('NONE', 'QUARANTINED')",
            name=conv("ck_w3_private_content_quarantine_state"),
        ),
        CheckConstraint(
            "legal_hold_state IN ('NONE', 'HELD')",
            name=conv("ck_w3_private_content_legal_hold_state"),
        ),
        CheckConstraint(
            "automatic_gc_enabled IS FALSE",
            name=conv("ck_w3_private_content_automatic_gc_off"),
        ),
        UniqueConstraint("content_digest", name="uq_w3_private_content_content_digest"),
        UniqueConstraint("id", "content_digest", name="uq_w3_private_content_id_digest"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_locator: Mapped[str] = mapped_column(Text, nullable=False)
    quarantine_state: Mapped[str] = mapped_column(Text, nullable=False)
    legal_hold_state: Mapped[str] = mapped_column(Text, nullable=False)
    automatic_gc_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3SourceSnapshot(Base):
    __tablename__ = "w3_source_snapshot"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('RFID', 'NHIS_SCHEDULE')",
            name=conv("ck_w3_source_snapshot_source_type"),
        ),
        CheckConstraint(
            "status IN ('CANDIDATE', 'ACTIVE', 'SUPERSEDED')",
            name=conv("ck_w3_source_snapshot_status"),
        ),
        UniqueConstraint(
            "source_type",
            "target_date",
            "content_digest",
            name="uq_w3_source_snapshot_identity",
        ),
        UniqueConstraint(
            "id",
            "content_id",
            "content_digest",
            name="uq_w3_source_snapshot_content_identity",
        ),
        ForeignKeyConstraint(
            ["content_id", "content_digest"],
            ["erp.w3_private_content.id", "erp.w3_private_content.content_digest"],
            name="fk_w3_source_snapshot_content_identity",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_w3_source_snapshot_one_active_per_source_date",
            "source_type",
            "target_date",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3SourceReceipt(Base):
    __tablename__ = "w3_source_receipt"
    __table_args__ = (
        CheckConstraint(
            "btrim(original_filename) <> ''",
            name=conv("ck_w3_source_receipt_filename"),
        ),
        CheckConstraint(
            "actor_type IN ('USER_ACCOUNT', 'SYSTEM_RUN')",
            name=conv("ck_w3_source_receipt_actor_type"),
        ),
        CheckConstraint(
            "(actor_type = 'USER_ACCOUNT' AND actor_account_id IS NOT NULL) "
            "OR (actor_type = 'SYSTEM_RUN' AND actor_account_id IS NULL)",
            name=conv("ck_w3_source_receipt_actor_pair"),
        ),
        CheckConstraint(
            "source_context_type IN ('RFID_FILE', 'NHIS_SCHEDULE_FILE')",
            name=conv("ck_w3_source_receipt_source_context_type"),
        ),
        UniqueConstraint(
            "id",
            "snapshot_id",
            "content_id",
            "content_digest",
            name="uq_w3_source_receipt_lineage",
        ),
        ForeignKeyConstraint(
            ["content_id", "content_digest"],
            ["erp.w3_private_content.id", "erp.w3_private_content.content_digest"],
            name="fk_w3_source_receipt_content_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.content_id",
                "erp.w3_source_snapshot.content_digest",
            ],
            name="fk_w3_source_receipt_snapshot_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_source_receipt_actor_account",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_source_receipt_content_id", "content_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(BigInteger)
    source_context_type: Mapped[str] = mapped_column(Text, nullable=False)
    received_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3ImportRun(Base):
    __tablename__ = "w3_import_run"
    __table_args__ = (
        CheckConstraint(
            "btrim(parser_profile_version) <> ''",
            name=conv("ck_w3_import_run_parser_profile_version"),
        ),
        CheckConstraint(
            "status IN ("
            "'RECEIVED', 'PARSING', 'PREVIEW_READY', 'CONFIRMED', "
            "'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED')",
            name=conv("ck_w3_import_run_status"),
        ),
        CheckConstraint(
            "btrim(apply_idempotency_key) <> ''",
            name=conv("ck_w3_import_run_apply_idempotency_key"),
        ),
        UniqueConstraint(
            "snapshot_id",
            "parser_profile_version",
            name="uq_w3_import_run_snapshot_profile",
        ),
        UniqueConstraint(
            "apply_idempotency_key",
            name="uq_w3_import_run_apply_idempotency_key",
        ),
        UniqueConstraint(
            "id",
            "snapshot_id",
            "content_id",
            "content_digest",
            name="uq_w3_import_run_lineage",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.content_id",
                "erp.w3_source_snapshot.content_digest",
            ],
            name="fk_w3_import_run_snapshot_identity",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_import_run_snapshot_id", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    parser_profile_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    apply_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3ImportAttempt(Base):
    __tablename__ = "w3_import_attempt"
    __table_args__ = (
        CheckConstraint("attempt_ordinal > 0", name=conv("ck_w3_import_attempt_ordinal")),
        CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED_RETRYABLE', 'BLOCKED')",
            name=conv("ck_w3_import_attempt_status"),
        ),
        UniqueConstraint(
            "import_run_id",
            "attempt_ordinal",
            name="uq_w3_import_attempt_ordinal",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["snapshot_id", "content_id", "content_digest"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.content_id",
                "erp.w3_source_snapshot.content_digest",
            ],
            name="fk_w3_import_attempt_snapshot_identity",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_import_attempt_import_run_id", "import_run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3SourceRow(Base):
    __tablename__ = "w3_source_row"
    __table_args__ = (
        CheckConstraint(
            "btrim(sheet_ref) <> '' AND position('://' in sheet_ref) = 0",
            name=conv("ck_w3_source_row_sheet_ref"),
        ),
        CheckConstraint("source_row_number > 0", name=conv("ck_w3_source_row_number")),
        UniqueConstraint(
            "receipt_id",
            "sheet_ref",
            "source_row_number",
            name="uq_w3_source_row_physical_address",
        ),
        ForeignKeyConstraint(
            ["receipt_id"],
            ["erp.w3_source_receipt.id"],
            name="fk_w3_source_row_receipt",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_source_row_receipt_id", "receipt_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sheet_ref: Mapped[str] = mapped_column(Text, nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
