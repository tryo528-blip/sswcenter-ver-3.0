"""SQLAlchemy mappings for W3 source intake and persistent apply evidence.

The 0028 foundation records immutable content and raw-row lineage. The 0029
extension records normalized rows, typed W1/W2 links, apply control, and
append-only correction evidence without a generic polymorphic target pair.
"""

from __future__ import annotations

from datetime import date, datetime, time

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
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from app.db.base import Base

FOUNDATION_HAS_TARGET_LINK = False
PERSISTENCE_HAS_TYPED_LINK = True


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
        UniqueConstraint(
            "id",
            "source_type",
            "target_date",
            name="uq_w3_source_snapshot_id_source_date",
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
        CheckConstraint(
            "row_version > 0",
            name=conv("ck_w3_import_run_row_version"),
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
        UniqueConstraint(
            "id",
            "snapshot_id",
            name="uq_w3_import_run_id_snapshot",
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
    row_version: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
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


class W3ImportRunEvent(Base):
    """Immutable state/command evidence for one import run."""

    __tablename__ = "w3_import_run_event"
    __table_args__ = (
        CheckConstraint(
            "event_ordinal > 0",
            name=conv("ck_w3_import_run_event_ordinal"),
        ),
        CheckConstraint(
            "event_type IN ("
            "'PREVIEW_CREATED', 'CONFIRMED', 'APPLY_STARTED', 'APPLIED', "
            "'BLOCKED', 'FAILED', 'MANUAL_DECISION')",
            name=conv("ck_w3_import_run_event_type"),
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ("
            "'RECEIVED', 'PARSING', 'PREVIEW_READY', 'CONFIRMED', "
            "'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED')",
            name=conv("ck_w3_import_run_event_from_status"),
        ),
        CheckConstraint(
            "to_status IN ("
            "'RECEIVED', 'PARSING', 'PREVIEW_READY', 'CONFIRMED', "
            "'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED')",
            name=conv("ck_w3_import_run_event_to_status"),
        ),
        CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_import_run_event_digest"),
        ),
        CheckConstraint(
            "(command_idempotency_key IS NULL AND command_digest IS NULL) OR "
            "(btrim(command_idempotency_key) <> '' AND "
            "command_digest ~ '^[0-9a-f]{64}$')",
            name=conv("ck_w3_import_run_event_command_pair"),
        ),
        UniqueConstraint(
            "import_run_id",
            "event_ordinal",
            name="uq_w3_import_run_event_ordinal",
        ),
        UniqueConstraint(
            "import_run_id",
            "command_idempotency_key",
            name="uq_w3_import_run_event_command_key",
        ),
        ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_import_run_event_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_import_run_event_actor_account",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_import_run_event_run", "import_run_id", "event_ordinal"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_digest: Mapped[str] = mapped_column(Text, nullable=False)
    command_idempotency_key: Mapped[str | None] = mapped_column(Text)
    command_digest: Mapped[str | None] = mapped_column(Text)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3NormalizedNhisRow(Base):
    """Immutable approved-profile normalization of one NHIS physical row."""

    __tablename__ = "w3_normalized_nhis_row"
    __table_args__ = (
        CheckConstraint("occurrence_ordinal > 0", name=conv("ck_w3_nhis_occurrence_ordinal")),
        CheckConstraint("declared_minutes > 0", name=conv("ck_w3_nhis_declared_minutes")),
        CheckConstraint("fee_amount >= 0", name=conv("ck_w3_nhis_fee_amount")),
        CheckConstraint(
            "occurrence_signature ~ '^[0-9a-f]{64}$' AND "
            "normalized_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_nhis_digests"),
        ),
        CheckConstraint(
            "family_flag IN ('Y', 'N') AND "
            "((family_flag = 'Y' AND family_relationship IS NOT NULL) OR "
            "(family_flag = 'N' AND family_relationship IS NULL))",
            name=conv("ck_w3_nhis_family_pair"),
        ),
        CheckConstraint(
            "service_category IN ('방문요양', '방문목욕')",
            name=conv("ck_w3_nhis_service_category"),
        ),
        UniqueConstraint(
            "import_run_id",
            "source_row_id",
            name="uq_w3_normalized_nhis_source_row",
        ),
        UniqueConstraint(
            "import_run_id",
            "occurrence_signature",
            "occurrence_ordinal",
            name="uq_w3_normalized_nhis_occurrence",
        ),
        UniqueConstraint("id", "import_run_id", name="uq_w3_normalized_nhis_id_run"),
        ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_normalized_nhis_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_row_id"],
            ["erp.w3_source_row.id"],
            name="fk_w3_normalized_nhis_source_row",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_normalized_nhis_run", "import_run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurrence_signature: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_digest: Mapped[str] = mapped_column(Text, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_start: Mapped[time] = mapped_column(Time, nullable=False)
    planned_end: Mapped[time] = mapped_column(Time, nullable=False)
    declared_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_certification_number: Mapped[str] = mapped_column(Text, nullable=False)
    staff_external_number: Mapped[str] = mapped_column(Text, nullable=False)
    worker_category: Mapped[str] = mapped_column(Text, nullable=False)
    family_flag: Mapped[str] = mapped_column(Text, nullable=False)
    family_relationship: Mapped[str | None] = mapped_column(Text)
    service_category: Mapped[str] = mapped_column(Text, nullable=False)
    fee_code: Mapped[str] = mapped_column(Text, nullable=False)
    fee_name: Mapped[str] = mapped_column(Text, nullable=False)
    fee_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3NormalizedRfidRow(Base):
    """Immutable approved-profile normalization of one RFID physical row."""

    __tablename__ = "w3_normalized_rfid_row"
    __table_args__ = (
        CheckConstraint("occurrence_ordinal > 0", name=conv("ck_w3_rfid_occurrence_ordinal")),
        CheckConstraint("reference_minutes >= 0", name=conv("ck_w3_rfid_reference_minutes")),
        CheckConstraint(
            "occurrence_signature ~ '^[0-9a-f]{64}$' AND "
            "normalized_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_rfid_digests"),
        ),
        CheckConstraint(
            "service_category IN ('방문요양', '방문목욕')",
            name=conv("ck_w3_rfid_service_category"),
        ),
        CheckConstraint(
            "event_state IN ('COMPLETE', 'START_ONLY')",
            name=conv("ck_w3_rfid_event_state"),
        ),
        CheckConstraint(
            "(event_state = 'COMPLETE' AND actual_end IS NOT NULL AND "
            "actual_end > actual_start AND actual_seconds > 0) OR "
            "(event_state = 'START_ONLY' AND actual_end IS NULL AND actual_seconds IS NULL)",
            name=conv("ck_w3_rfid_actual_pair"),
        ),
        UniqueConstraint(
            "import_run_id",
            "source_row_id",
            name="uq_w3_normalized_rfid_source_row",
        ),
        UniqueConstraint(
            "import_run_id",
            "occurrence_signature",
            "occurrence_ordinal",
            name="uq_w3_normalized_rfid_occurrence",
        ),
        UniqueConstraint("id", "import_run_id", name="uq_w3_normalized_rfid_id_run"),
        UniqueConstraint(
            "id",
            "import_run_id",
            "occurrence_signature",
            "occurrence_ordinal",
            name="uq_w3_normalized_rfid_actual_link",
        ),
        ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_normalized_rfid_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_row_id"],
            ["erp.w3_source_row.id"],
            name="fk_w3_normalized_rfid_source_row",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_normalized_rfid_run", "import_run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurrence_signature: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_digest: Mapped[str] = mapped_column(Text, nullable=False)
    transmission_kind: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_certification_number: Mapped[str] = mapped_column(Text, nullable=False)
    service_category: Mapped[str] = mapped_column(Text, nullable=False)
    reference_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_seconds: Mapped[int | None] = mapped_column(Integer)
    use_state: Mapped[str] = mapped_column(Text, nullable=False)
    event_state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3NhisGroup(Base):
    """Deterministic derived group; member rows remain separately immutable."""

    __tablename__ = "w3_nhis_group"
    __table_args__ = (
        CheckConstraint("declared_minutes > 0", name=conv("ck_w3_nhis_group_minutes")),
        CheckConstraint(
            "group_signature ~ '^[0-9a-f]{64}$' AND "
            "normalized_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_nhis_group_digests"),
        ),
        CheckConstraint(
            "service_category IN ('방문요양', '방문목욕')",
            name=conv("ck_w3_nhis_group_service_category"),
        ),
        UniqueConstraint(
            "import_run_id",
            "group_signature",
            name="uq_w3_nhis_group_signature",
        ),
        UniqueConstraint("id", "import_run_id", name="uq_w3_nhis_group_id_run"),
        ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_nhis_group_run",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_nhis_group_run", "import_run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_signature: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_digest: Mapped[str] = mapped_column(Text, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_start: Mapped[time] = mapped_column(Time, nullable=False)
    planned_end: Mapped[time] = mapped_column(Time, nullable=False)
    declared_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_certification_number: Mapped[str] = mapped_column(Text, nullable=False)
    staff_external_number: Mapped[str] = mapped_column(Text, nullable=False)
    service_category: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3NhisGroupMember(Base):
    __tablename__ = "w3_nhis_group_member"
    __table_args__ = (
        UniqueConstraint(
            "nhis_group_id",
            "normalized_nhis_row_id",
            name="uq_w3_nhis_group_member_pair",
        ),
        UniqueConstraint(
            "import_run_id",
            "normalized_nhis_row_id",
            name="uq_w3_nhis_group_member_row_once",
        ),
        ForeignKeyConstraint(
            ["nhis_group_id", "import_run_id"],
            ["erp.w3_nhis_group.id", "erp.w3_nhis_group.import_run_id"],
            name="fk_w3_nhis_group_member_group_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["normalized_nhis_row_id", "import_run_id"],
            ["erp.w3_normalized_nhis_row.id", "erp.w3_normalized_nhis_row.import_run_id"],
            name="fk_w3_nhis_group_member_row_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_row_id"],
            ["erp.w3_source_row.id"],
            name="fk_w3_nhis_group_member_source_row",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_nhis_group_member_group", "nhis_group_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nhis_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    normalized_nhis_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3MatchDecision(Base):
    """Append-only matcher outcome with explicit W1/W2 typed links."""

    __tablename__ = "w3_match_decision"
    __table_args__ = (
        CheckConstraint("decision_revision > 0", name=conv("ck_w3_match_decision_revision")),
        CheckConstraint(
            "source_type IN ('RFID', 'NHIS_SCHEDULE')",
            name=conv("ck_w3_match_decision_source_type"),
        ),
        CheckConstraint(
            "status IN ('AUTO_MATCH', 'MANUAL_MATCH', 'REVIEW_PENDING', 'BLOCKED')",
            name=conv("ck_w3_match_decision_status"),
        ),
        CheckConstraint(
            "decision_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_match_decision_digest"),
        ),
        CheckConstraint(
            "(source_type = 'NHIS_SCHEDULE' AND nhis_group_id IS NOT NULL "
            "AND normalized_rfid_row_id IS NULL) OR "
            "(source_type = 'RFID' AND normalized_rfid_row_id IS NOT NULL "
            "AND nhis_group_id IS NULL)",
            name=conv("ck_w3_match_decision_subject"),
        ),
        CheckConstraint(
            "(status = 'AUTO_MATCH' AND recipient_id IS NOT NULL "
            "AND certification_period_id IS NOT NULL AND staff_id IS NOT NULL "
            "AND employment_id IS NOT NULL AND staff_legacy_mapping_id IS NOT NULL "
            "AND service_type_id IS NOT NULL AND recipient_contract_id IS NOT NULL "
            "AND care_assignment_id IS NOT NULL AND w2_schedule_id IS NOT NULL) OR "
            "(status = 'MANUAL_MATCH' AND recipient_id IS NOT NULL "
            "AND certification_period_id IS NOT NULL AND staff_id IS NOT NULL "
            "AND employment_id IS NOT NULL AND service_type_id IS NOT NULL "
            "AND recipient_contract_id IS NOT NULL AND care_assignment_id IS NOT NULL "
            "AND w2_schedule_id IS NOT NULL) OR "
            "(status IN ('REVIEW_PENDING', 'BLOCKED') AND recipient_id IS NULL "
            "AND certification_period_id IS NULL AND staff_id IS NULL "
            "AND employment_id IS NULL AND staff_legacy_mapping_id IS NULL "
            "AND service_type_id IS NULL AND recipient_contract_id IS NULL "
            "AND care_assignment_id IS NULL AND w2_schedule_id IS NULL)",
            name=conv("ck_w3_match_decision_typed_bundle"),
        ),
        UniqueConstraint(
            "import_run_id",
            "source_occurrence_identity",
            "decision_revision",
            name="uq_w3_match_decision_revision",
        ),
        UniqueConstraint(
            "id",
            "import_run_id",
            "source_occurrence_identity",
            name="uq_w3_match_decision_id_run_subject",
        ),
        UniqueConstraint(
            "id",
            "import_run_id",
            "source_occurrence_identity",
            "normalized_rfid_row_id",
            "recipient_id",
            "certification_period_id",
            "staff_id",
            "employment_id",
            "service_type_id",
            "recipient_contract_id",
            "care_assignment_id",
            "w2_schedule_id",
            name="uq_w3_match_decision_actual_link",
        ),
        ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_match_decision_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["nhis_group_id", "import_run_id"],
            ["erp.w3_nhis_group.id", "erp.w3_nhis_group.import_run_id"],
            name="fk_w3_match_decision_nhis_group_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["normalized_rfid_row_id", "import_run_id"],
            ["erp.w3_normalized_rfid_row.id", "erp.w3_normalized_rfid_row.import_run_id"],
            name="fk_w3_match_decision_rfid_row_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["supersedes_decision_id", "import_run_id", "source_occurrence_identity"],
            [
                "erp.w3_match_decision.id",
                "erp.w3_match_decision.import_run_id",
                "erp.w3_match_decision.source_occurrence_identity",
            ],
            name="fk_w3_match_decision_supersedes",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "certification_period_id"],
            [
                "erp.recipient_certification_period.recipient_id",
                "erp.recipient_certification_period.id",
            ],
            name="fk_w3_match_decision_certification_period",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_w3_match_decision_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_legacy_mapping_id"],
            ["erp.staff_legacy_mapping.id"],
            name="fk_w3_match_decision_staff_mapping",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_w3_match_decision_service_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "recipient_contract_id"],
            ["erp.recipient_contract.recipient_id", "erp.recipient_contract.id"],
            name="fk_w3_match_decision_contract",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["care_assignment_id"],
            ["erp.care_assignment.id"],
            name="fk_w3_match_decision_care_assignment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["w2_schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w3_match_decision_schedule",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_match_decision_created_by_account",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_w3_match_decision_run_subject",
            "import_run_id",
            "source_occurrence_identity",
            "decision_revision",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_occurrence_identity: Mapped[str] = mapped_column(Text, nullable=False)
    nhis_group_id: Mapped[int | None] = mapped_column(BigInteger)
    normalized_rfid_row_id: Mapped[int | None] = mapped_column(BigInteger)
    decision_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_decision_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    decision_digest: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_id: Mapped[int | None] = mapped_column(BigInteger)
    certification_period_id: Mapped[int | None] = mapped_column(BigInteger)
    staff_id: Mapped[int | None] = mapped_column(BigInteger)
    employment_id: Mapped[int | None] = mapped_column(BigInteger)
    staff_legacy_mapping_id: Mapped[int | None] = mapped_column(BigInteger)
    service_type_id: Mapped[int | None] = mapped_column(BigInteger)
    recipient_contract_id: Mapped[int | None] = mapped_column(BigInteger)
    care_assignment_id: Mapped[int | None] = mapped_column(BigInteger)
    w2_schedule_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3ApplyControl(Base):
    """One lock row per source/date; the sole current snapshot/run projection."""

    __tablename__ = "w3_apply_control"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('RFID', 'NHIS_SCHEDULE')",
            name=conv("ck_w3_apply_control_source_type"),
        ),
        CheckConstraint("row_version > 0", name=conv("ck_w3_apply_control_row_version")),
        CheckConstraint(
            "(active_snapshot_id IS NULL) = (active_import_run_id IS NULL)",
            name=conv("ck_w3_apply_control_active_pair"),
        ),
        ForeignKeyConstraint(
            ["active_snapshot_id", "source_type", "target_date"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.source_type",
                "erp.w3_source_snapshot.target_date",
            ],
            name="fk_w3_apply_control_active_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["active_import_run_id", "active_snapshot_id"],
            ["erp.w3_import_run.id", "erp.w3_import_run.snapshot_id"],
            name="fk_w3_apply_control_active_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_apply_control_updated_by_account",
            ondelete="RESTRICT",
        ),
    )

    source_type: Mapped[str] = mapped_column(Text, primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, primary_key=True)
    active_snapshot_id: Mapped[int | None] = mapped_column(BigInteger)
    active_import_run_id: Mapped[int | None] = mapped_column(BigInteger)
    row_version: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), nullable=False
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3ActualWorkRevision(Base):
    """Versioned RFID actual-work evidence; source times are never rewritten."""

    __tablename__ = "w3_actual_work_revision"
    __table_args__ = (
        CheckConstraint(
            "source_type = 'RFID'",
            name=conv("ck_w3_actual_work_source_type"),
        ),
        CheckConstraint(
            "occurrence_ordinal > 0",
            name=conv("ck_w3_actual_work_occurrence_ordinal"),
        ),
        CheckConstraint(
            "occurrence_signature ~ '^[0-9a-f]{64}$' AND "
            "fact_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_actual_work_digests"),
        ),
        CheckConstraint(
            "source_event_state IN ('COMPLETE', 'START_ONLY')",
            name=conv("ck_w3_actual_work_event_state"),
        ),
        CheckConstraint(
            "(source_event_state = 'COMPLETE' AND actual_end IS NOT NULL "
            "AND actual_end > actual_start AND actual_seconds > 0) OR "
            "(source_event_state = 'START_ONLY' AND actual_end IS NULL "
            "AND actual_seconds IS NULL)",
            name=conv("ck_w3_actual_work_actual_pair"),
        ),
        CheckConstraint(
            "reference_minutes >= 0",
            name=conv("ck_w3_actual_work_reference_minutes"),
        ),
        UniqueConstraint("id", "target_date", name="uq_w3_actual_work_id_target_date"),
        ForeignKeyConstraint(
            ["snapshot_id", "source_type", "target_date"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.source_type",
                "erp.w3_source_snapshot.target_date",
            ],
            name="fk_w3_actual_work_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["import_run_id", "snapshot_id"],
            ["erp.w3_import_run.id", "erp.w3_import_run.snapshot_id"],
            name="fk_w3_actual_work_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "normalized_rfid_row_id",
                "import_run_id",
                "occurrence_signature",
                "occurrence_ordinal",
            ],
            [
                "erp.w3_normalized_rfid_row.id",
                "erp.w3_normalized_rfid_row.import_run_id",
                "erp.w3_normalized_rfid_row.occurrence_signature",
                "erp.w3_normalized_rfid_row.occurrence_ordinal",
            ],
            name="fk_w3_actual_work_normalized_rfid_row",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "match_decision_id",
                "import_run_id",
                "source_occurrence_identity",
                "normalized_rfid_row_id",
                "recipient_id",
                "certification_period_id",
                "staff_id",
                "employment_id",
                "service_type_id",
                "recipient_contract_id",
                "care_assignment_id",
                "w2_schedule_id",
            ],
            [
                "erp.w3_match_decision.id",
                "erp.w3_match_decision.import_run_id",
                "erp.w3_match_decision.source_occurrence_identity",
                "erp.w3_match_decision.normalized_rfid_row_id",
                "erp.w3_match_decision.recipient_id",
                "erp.w3_match_decision.certification_period_id",
                "erp.w3_match_decision.staff_id",
                "erp.w3_match_decision.employment_id",
                "erp.w3_match_decision.service_type_id",
                "erp.w3_match_decision.recipient_contract_id",
                "erp.w3_match_decision.care_assignment_id",
                "erp.w3_match_decision.w2_schedule_id",
            ],
            name="fk_w3_actual_work_match_decision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["prior_revision_id", "target_date"],
            ["erp.w3_actual_work_revision.id", "erp.w3_actual_work_revision.target_date"],
            name="fk_w3_actual_work_prior_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "certification_period_id"],
            [
                "erp.recipient_certification_period.recipient_id",
                "erp.recipient_certification_period.id",
            ],
            name="fk_w3_actual_work_certification_period",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_w3_actual_work_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_w3_actual_work_service_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "recipient_contract_id"],
            ["erp.recipient_contract.recipient_id", "erp.recipient_contract.id"],
            name="fk_w3_actual_work_contract",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["care_assignment_id"],
            ["erp.care_assignment.id"],
            name="fk_w3_actual_work_care_assignment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["w2_schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w3_actual_work_schedule",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_actual_work_created_by_account",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_w3_actual_work_current_occurrence",
            "target_date",
            "source_occurrence_identity",
            unique=True,
            postgresql_where=text("superseded_at_utc IS NULL"),
        ),
        Index("ix_w3_actual_work_schedule", "w2_schedule_id", "target_date", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    import_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    normalized_rfid_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    match_decision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_occurrence_identity: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_signature: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    certification_period_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    staff_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    employment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    service_type_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recipient_contract_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    care_assignment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    w2_schedule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_event_state: Mapped[str] = mapped_column(Text, nullable=False)
    reference_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_seconds: Mapped[int | None] = mapped_column(Integer)
    fact_digest: Mapped[str] = mapped_column(Text, nullable=False)
    prior_revision_id: Mapped[int | None] = mapped_column(BigInteger)
    superseded_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3ManualSupplementEvent(Base):
    __tablename__ = "w3_manual_supplement_event"
    __table_args__ = (
        CheckConstraint(
            "supplement_version > 0",
            name=conv("ck_w3_manual_supplement_version"),
        ),
        CheckConstraint(
            "action IN ('CREATE', 'CANCEL', 'REPLACE')",
            name=conv("ck_w3_manual_supplement_action"),
        ),
        CheckConstraint(
            "(action = 'CANCEL' AND proposed_actual_end IS NULL) OR "
            "(action IN ('CREATE', 'REPLACE') AND proposed_actual_end IS NOT NULL)",
            name=conv("ck_w3_manual_supplement_end_pair"),
        ),
        CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$' AND btrim(reason) <> ''",
            name=conv("ck_w3_manual_supplement_payload"),
        ),
        CheckConstraint(
            "btrim(command_idempotency_key) <> ''",
            name=conv("ck_w3_manual_supplement_command_key"),
        ),
        UniqueConstraint(
            "actual_work_revision_id",
            "supplement_version",
            name="uq_w3_manual_supplement_version",
        ),
        UniqueConstraint(
            "command_idempotency_key",
            name="uq_w3_manual_supplement_command_key",
        ),
        ForeignKeyConstraint(
            ["actual_work_revision_id"],
            ["erp.w3_actual_work_revision.id"],
            name="fk_w3_manual_supplement_actual_work",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["prior_event_id"],
            ["erp.w3_manual_supplement_event.id"],
            name="fk_w3_manual_supplement_prior_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_manual_supplement_created_by_account",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_w3_manual_supplement_actual_work",
            "actual_work_revision_id",
            "supplement_version",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actual_work_revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplement_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_event_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    event_digest: Mapped[str] = mapped_column(Text, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class W3PlanAdjustmentEvent(Base):
    __tablename__ = "w3_plan_adjustment_event"
    __table_args__ = (
        CheckConstraint(
            "btrim(rule_version) <> '' AND btrim(reason) <> ''",
            name=conv("ck_w3_plan_adjustment_text"),
        ),
        CheckConstraint(
            "prior_planned_start < prior_planned_end AND "
            "adopted_planned_start < adopted_planned_end",
            name=conv("ck_w3_plan_adjustment_time_order"),
        ),
        CheckConstraint(
            "expected_schedule_row_version > 0 AND adopted_schedule_row_version > 0 AND "
            "expected_month_row_version > 0 AND adopted_month_row_version > 0",
            name=conv("ck_w3_plan_adjustment_versions"),
        ),
        CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$'",
            name=conv("ck_w3_plan_adjustment_digest"),
        ),
        CheckConstraint(
            "btrim(command_idempotency_key) <> ''",
            name=conv("ck_w3_plan_adjustment_command_key"),
        ),
        UniqueConstraint(
            "actual_work_revision_id",
            "adopted_schedule_row_version",
            name="uq_w3_plan_adjustment_adoption",
        ),
        UniqueConstraint(
            "command_idempotency_key",
            name="uq_w3_plan_adjustment_command_key",
        ),
        ForeignKeyConstraint(
            ["actual_work_revision_id"],
            ["erp.w3_actual_work_revision.id"],
            name="fk_w3_plan_adjustment_actual_work",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["w2_schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w3_plan_adjustment_schedule",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_plan_adjustment_created_by_account",
            ondelete="RESTRICT",
        ),
        Index("ix_w3_plan_adjustment_schedule", "w2_schedule_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actual_work_revision_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    w2_schedule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    prior_planned_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prior_planned_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    adopted_planned_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    adopted_planned_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_schedule_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    adopted_schedule_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_month_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    adopted_month_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    event_digest: Mapped[str] = mapped_column(Text, nullable=False)
    command_idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
