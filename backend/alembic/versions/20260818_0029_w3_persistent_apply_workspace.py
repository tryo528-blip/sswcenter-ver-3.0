"""Add W3 persistent normalization, typed matching, and atomic apply ledgers.

Revision ID: 20260818_0029_w3_persistent_apply_workspace
Revises: 20260817_0028_w3_source_intake_foundation
Create Date: 2026-08-18

This revision deliberately adds no generic polymorphic target pair and no
database-stored binary payload. Every business edge is a named W1/W2 foreign key.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260818_0029_w3_persistent_apply_workspace"
down_revision: str | None = "20260817_0028_w3_source_intake_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "w3_import_run",
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        schema="erp",
    )
    op.create_check_constraint(
        op.f("ck_w3_import_run_row_version"),
        "w3_import_run",
        "row_version > 0",
        schema="erp",
    )
    op.create_unique_constraint(
        "uq_w3_source_snapshot_id_source_date",
        "w3_source_snapshot",
        ["id", "source_type", "target_date"],
        schema="erp",
    )
    op.create_unique_constraint(
        "uq_w3_import_run_id_snapshot",
        "w3_import_run",
        ["id", "snapshot_id"],
        schema="erp",
    )

    op.create_table(
        "w3_import_run_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("event_ordinal", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_account_id", sa.BigInteger(), nullable=False),
        sa.Column("event_digest", sa.Text(), nullable=False),
        sa.Column("command_idempotency_key", sa.Text(), nullable=True),
        sa.Column("command_digest", sa.Text(), nullable=True),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("event_ordinal > 0", name=op.f("ck_w3_import_run_event_ordinal")),
        sa.CheckConstraint(
            "event_type IN ("
            "'PREVIEW_CREATED', 'CONFIRMED', 'APPLY_STARTED', 'APPLIED', "
            "'BLOCKED', 'FAILED', 'MANUAL_DECISION')",
            name=op.f("ck_w3_import_run_event_type"),
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ("
            "'RECEIVED', 'PARSING', 'PREVIEW_READY', 'CONFIRMED', "
            "'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED')",
            name=op.f("ck_w3_import_run_event_from_status"),
        ),
        sa.CheckConstraint(
            "to_status IN ("
            "'RECEIVED', 'PARSING', 'PREVIEW_READY', 'CONFIRMED', "
            "'APPLYING', 'APPLIED', 'BLOCKED', 'FAILED')",
            name=op.f("ck_w3_import_run_event_to_status"),
        ),
        sa.CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_import_run_event_digest"),
        ),
        sa.CheckConstraint(
            "(command_idempotency_key IS NULL AND command_digest IS NULL) OR "
            "(btrim(command_idempotency_key) <> '' AND "
            "command_digest ~ '^[0-9a-f]{64}$')",
            name=op.f("ck_w3_import_run_event_command_pair"),
        ),
        sa.UniqueConstraint(
            "import_run_id", "event_ordinal", name="uq_w3_import_run_event_ordinal"
        ),
        sa.UniqueConstraint(
            "import_run_id",
            "command_idempotency_key",
            name="uq_w3_import_run_event_command_key",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_import_run_event_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_import_run_event_actor_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_import_run_event"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_import_run_event_run",
        "w3_import_run_event",
        ["import_run_id", "event_ordinal"],
        schema="erp",
    )

    op.create_table(
        "w3_normalized_nhis_row",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_id", sa.BigInteger(), nullable=False),
        sa.Column("occurrence_signature", sa.Text(), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
        sa.Column("normalized_digest", sa.Text(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("planned_start", sa.Time(), nullable=False),
        sa.Column("planned_end", sa.Time(), nullable=False),
        sa.Column("declared_minutes", sa.Integer(), nullable=False),
        sa.Column("recipient_certification_number", sa.Text(), nullable=False),
        sa.Column("staff_external_number", sa.Text(), nullable=False),
        sa.Column("worker_category", sa.Text(), nullable=False),
        sa.Column("family_flag", sa.Text(), nullable=False),
        sa.Column("family_relationship", sa.Text(), nullable=True),
        sa.Column("service_category", sa.Text(), nullable=False),
        sa.Column("fee_code", sa.Text(), nullable=False),
        sa.Column("fee_name", sa.Text(), nullable=False),
        sa.Column("fee_amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "occurrence_ordinal > 0", name=op.f("ck_w3_nhis_occurrence_ordinal")
        ),
        sa.CheckConstraint(
            "declared_minutes > 0", name=op.f("ck_w3_nhis_declared_minutes")
        ),
        sa.CheckConstraint("fee_amount >= 0", name=op.f("ck_w3_nhis_fee_amount")),
        sa.CheckConstraint(
            "occurrence_signature ~ '^[0-9a-f]{64}$' AND "
            "normalized_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_nhis_digests"),
        ),
        sa.CheckConstraint(
            "family_flag IN ('Y', 'N') AND "
            "((family_flag = 'Y' AND family_relationship IS NOT NULL) OR "
            "(family_flag = 'N' AND family_relationship IS NULL))",
            name=op.f("ck_w3_nhis_family_pair"),
        ),
        sa.CheckConstraint(
            "service_category IN ('방문요양', '방문목욕')",
            name=op.f("ck_w3_nhis_service_category"),
        ),
        sa.UniqueConstraint(
            "import_run_id", "source_row_id", name="uq_w3_normalized_nhis_source_row"
        ),
        sa.UniqueConstraint(
            "import_run_id",
            "occurrence_signature",
            "occurrence_ordinal",
            name="uq_w3_normalized_nhis_occurrence",
        ),
        sa.UniqueConstraint("id", "import_run_id", name="uq_w3_normalized_nhis_id_run"),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_normalized_nhis_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id"],
            ["erp.w3_source_row.id"],
            name="fk_w3_normalized_nhis_source_row",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_normalized_nhis_row"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_normalized_nhis_run",
        "w3_normalized_nhis_row",
        ["import_run_id", "id"],
        schema="erp",
    )

    op.create_table(
        "w3_normalized_rfid_row",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_id", sa.BigInteger(), nullable=False),
        sa.Column("target_selected", sa.Boolean(), nullable=False),
        sa.Column("occurrence_signature", sa.Text(), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
        sa.Column("normalized_digest", sa.Text(), nullable=False),
        sa.Column("transmission_kind", sa.Text(), nullable=False),
        sa.Column("recipient_certification_number", sa.Text(), nullable=False),
        sa.Column("service_category", sa.Text(), nullable=False),
        sa.Column("reference_minutes", sa.Integer(), nullable=False),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_seconds", sa.Integer(), nullable=True),
        sa.Column("use_state", sa.Text(), nullable=False),
        sa.Column("event_state", sa.Text(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "occurrence_ordinal > 0", name=op.f("ck_w3_rfid_occurrence_ordinal")
        ),
        sa.CheckConstraint(
            "reference_minutes >= 0", name=op.f("ck_w3_rfid_reference_minutes")
        ),
        sa.CheckConstraint(
            "occurrence_signature ~ '^[0-9a-f]{64}$' AND "
            "normalized_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_rfid_digests"),
        ),
        sa.CheckConstraint(
            "service_category IN ('방문요양', '방문목욕')",
            name=op.f("ck_w3_rfid_service_category"),
        ),
        sa.CheckConstraint(
            "event_state IN ('COMPLETE', 'START_ONLY')",
            name=op.f("ck_w3_rfid_event_state"),
        ),
        sa.CheckConstraint(
            "(event_state = 'COMPLETE' AND actual_end IS NOT NULL AND "
            "actual_end > actual_start AND actual_seconds > 0) OR "
            "(event_state = 'START_ONLY' AND actual_end IS NULL AND actual_seconds IS NULL)",
            name=op.f("ck_w3_rfid_actual_pair"),
        ),
        sa.UniqueConstraint(
            "import_run_id", "source_row_id", name="uq_w3_normalized_rfid_source_row"
        ),
        sa.UniqueConstraint(
            "import_run_id",
            "occurrence_signature",
            "occurrence_ordinal",
            name="uq_w3_normalized_rfid_occurrence",
        ),
        sa.UniqueConstraint("id", "import_run_id", name="uq_w3_normalized_rfid_id_run"),
        sa.UniqueConstraint(
            "id",
            "import_run_id",
            "occurrence_signature",
            "occurrence_ordinal",
            name="uq_w3_normalized_rfid_actual_link",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_normalized_rfid_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id"],
            ["erp.w3_source_row.id"],
            name="fk_w3_normalized_rfid_source_row",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_normalized_rfid_row"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_normalized_rfid_run",
        "w3_normalized_rfid_row",
        ["import_run_id", "id"],
        schema="erp",
    )

    op.create_table(
        "w3_nhis_group",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("group_signature", sa.Text(), nullable=False),
        sa.Column("normalized_digest", sa.Text(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("planned_start", sa.Time(), nullable=False),
        sa.Column("planned_end", sa.Time(), nullable=False),
        sa.Column("declared_minutes", sa.Integer(), nullable=False),
        sa.Column("recipient_certification_number", sa.Text(), nullable=False),
        sa.Column("staff_external_number", sa.Text(), nullable=False),
        sa.Column("service_category", sa.Text(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "declared_minutes > 0", name=op.f("ck_w3_nhis_group_minutes")
        ),
        sa.CheckConstraint(
            "group_signature ~ '^[0-9a-f]{64}$' AND "
            "normalized_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_nhis_group_digests"),
        ),
        sa.CheckConstraint(
            "service_category IN ('방문요양', '방문목욕')",
            name=op.f("ck_w3_nhis_group_service_category"),
        ),
        sa.UniqueConstraint(
            "import_run_id", "group_signature", name="uq_w3_nhis_group_signature"
        ),
        sa.UniqueConstraint("id", "import_run_id", name="uq_w3_nhis_group_id_run"),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_nhis_group_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_nhis_group"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_nhis_group_run",
        "w3_nhis_group",
        ["import_run_id", "id"],
        schema="erp",
    )

    op.create_table(
        "w3_nhis_group_member",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("nhis_group_id", sa.BigInteger(), nullable=False),
        sa.Column("normalized_nhis_row_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "nhis_group_id",
            "normalized_nhis_row_id",
            name="uq_w3_nhis_group_member_pair",
        ),
        sa.UniqueConstraint(
            "import_run_id",
            "normalized_nhis_row_id",
            name="uq_w3_nhis_group_member_row_once",
        ),
        sa.ForeignKeyConstraint(
            ["nhis_group_id", "import_run_id"],
            ["erp.w3_nhis_group.id", "erp.w3_nhis_group.import_run_id"],
            name="fk_w3_nhis_group_member_group_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_nhis_row_id", "import_run_id"],
            ["erp.w3_normalized_nhis_row.id", "erp.w3_normalized_nhis_row.import_run_id"],
            name="fk_w3_nhis_group_member_row_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_row_id"],
            ["erp.w3_source_row.id"],
            name="fk_w3_nhis_group_member_source_row",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_nhis_group_member"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_nhis_group_member_group",
        "w3_nhis_group_member",
        ["nhis_group_id", "id"],
        schema="erp",
    )

    _create_match_decision()
    _create_apply_and_revision_tables()

    op.execute(
        """
        INSERT INTO erp.permission_definition (permission_code, name, description, active)
        VALUES
            ('W3_VIEW', '입출력 조회', 'W3 원본 접수와 적용상태 조회', true),
            ('W3_MANAGE', '입출력 관리', 'W3 파일 확인, 적용, 보완과 계획정정', true)
        ON CONFLICT (permission_code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description,
            active = true
        """
    )

    op.execute("ALTER TABLE erp.w3_import_run_event OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_normalized_nhis_row OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_normalized_rfid_row OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_nhis_group OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_nhis_group_member OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_match_decision OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_apply_control OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_actual_work_revision OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_manual_supplement_event OWNER TO erp_owner")
    op.execute("ALTER TABLE erp.w3_plan_adjustment_event OWNER TO erp_owner")


def _create_match_decision() -> None:
    op.create_table(
        "w3_match_decision",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_occurrence_identity", sa.Text(), nullable=False),
        sa.Column("nhis_group_id", sa.BigInteger(), nullable=True),
        sa.Column("normalized_rfid_row_id", sa.BigInteger(), nullable=True),
        sa.Column("decision_revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_decision_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("decision_digest", sa.Text(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=True),
        sa.Column("certification_period_id", sa.BigInteger(), nullable=True),
        sa.Column("staff_id", sa.BigInteger(), nullable=True),
        sa.Column("employment_id", sa.BigInteger(), nullable=True),
        sa.Column("staff_legacy_mapping_id", sa.BigInteger(), nullable=True),
        sa.Column("service_type_id", sa.BigInteger(), nullable=True),
        sa.Column("recipient_contract_id", sa.BigInteger(), nullable=True),
        sa.Column("care_assignment_id", sa.BigInteger(), nullable=True),
        sa.Column("w2_schedule_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision_revision > 0", name=op.f("ck_w3_match_decision_revision")
        ),
        sa.CheckConstraint(
            "source_type IN ('RFID', 'NHIS_SCHEDULE')",
            name=op.f("ck_w3_match_decision_source_type"),
        ),
        sa.CheckConstraint(
            "status IN ('AUTO_MATCH', 'MANUAL_MATCH', 'REVIEW_PENDING', 'BLOCKED')",
            name=op.f("ck_w3_match_decision_status"),
        ),
        sa.CheckConstraint(
            "decision_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_match_decision_digest"),
        ),
        sa.CheckConstraint(
            "(source_type = 'NHIS_SCHEDULE' AND nhis_group_id IS NOT NULL "
            "AND normalized_rfid_row_id IS NULL) OR "
            "(source_type = 'RFID' AND normalized_rfid_row_id IS NOT NULL "
            "AND nhis_group_id IS NULL)",
            name=op.f("ck_w3_match_decision_subject"),
        ),
        sa.CheckConstraint(
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
            name=op.f("ck_w3_match_decision_typed_bundle"),
        ),
        sa.UniqueConstraint(
            "import_run_id",
            "source_occurrence_identity",
            "decision_revision",
            name="uq_w3_match_decision_revision",
        ),
        sa.UniqueConstraint(
            "id",
            "import_run_id",
            "source_occurrence_identity",
            name="uq_w3_match_decision_id_run_subject",
        ),
        sa.UniqueConstraint(
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
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["erp.w3_import_run.id"],
            name="fk_w3_match_decision_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["nhis_group_id", "import_run_id"],
            ["erp.w3_nhis_group.id", "erp.w3_nhis_group.import_run_id"],
            name="fk_w3_match_decision_nhis_group_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_rfid_row_id", "import_run_id"],
            ["erp.w3_normalized_rfid_row.id", "erp.w3_normalized_rfid_row.import_run_id"],
            name="fk_w3_match_decision_rfid_row_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_decision_id", "import_run_id", "source_occurrence_identity"],
            [
                "erp.w3_match_decision.id",
                "erp.w3_match_decision.import_run_id",
                "erp.w3_match_decision.source_occurrence_identity",
            ],
            name="fk_w3_match_decision_supersedes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "certification_period_id"],
            [
                "erp.recipient_certification_period.recipient_id",
                "erp.recipient_certification_period.id",
            ],
            name="fk_w3_match_decision_certification_period",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_w3_match_decision_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_legacy_mapping_id"],
            ["erp.staff_legacy_mapping.id"],
            name="fk_w3_match_decision_staff_mapping",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_w3_match_decision_service_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "recipient_contract_id"],
            ["erp.recipient_contract.recipient_id", "erp.recipient_contract.id"],
            name="fk_w3_match_decision_contract",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["care_assignment_id"],
            ["erp.care_assignment.id"],
            name="fk_w3_match_decision_care_assignment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["w2_schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w3_match_decision_schedule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_match_decision_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_match_decision"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_match_decision_run_subject",
        "w3_match_decision",
        ["import_run_id", "source_occurrence_identity", "decision_revision"],
        schema="erp",
    )


def _create_apply_and_revision_tables() -> None:
    op.create_table(
        "w3_apply_control",
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("active_snapshot_id", sa.BigInteger(), nullable=True),
        sa.Column("active_import_run_id", sa.BigInteger(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('RFID', 'NHIS_SCHEDULE')",
            name=op.f("ck_w3_apply_control_source_type"),
        ),
        sa.CheckConstraint("row_version > 0", name=op.f("ck_w3_apply_control_row_version")),
        sa.CheckConstraint(
            "(active_snapshot_id IS NULL) = (active_import_run_id IS NULL)",
            name=op.f("ck_w3_apply_control_active_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["active_snapshot_id", "source_type", "target_date"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.source_type",
                "erp.w3_source_snapshot.target_date",
            ],
            name="fk_w3_apply_control_active_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["active_import_run_id", "active_snapshot_id"],
            ["erp.w3_import_run.id", "erp.w3_import_run.snapshot_id"],
            name="fk_w3_apply_control_active_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_apply_control_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "source_type", "target_date", name="pk_w3_apply_control"
        ),
        schema="erp",
    )
    op.execute(
        """
        INSERT INTO erp.w3_apply_control (
            source_type,
            target_date,
            active_snapshot_id,
            active_import_run_id,
            row_version,
            updated_by_account_id,
            updated_at_utc
        )
        SELECT
            snapshot.source_type,
            snapshot.target_date,
            snapshot.id,
            active_run.import_run_id,
            1,
            active_run.actor_account_id,
            now()
        FROM erp.w3_source_snapshot AS snapshot
        JOIN LATERAL (
            SELECT
                run.id AS import_run_id,
                receipt.actor_account_id
            FROM erp.w3_import_run AS run
            JOIN erp.w3_source_receipt AS receipt
              ON receipt.id = run.receipt_id
            WHERE run.snapshot_id = snapshot.id
              AND run.status = 'APPLIED'
              AND receipt.actor_account_id IS NOT NULL
            ORDER BY run.id DESC
            LIMIT 1
        ) AS active_run ON true
        WHERE snapshot.status = 'ACTIVE'
        """
    )

    op.create_table(
        "w3_actual_work_revision",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("import_run_id", sa.BigInteger(), nullable=False),
        sa.Column("normalized_rfid_row_id", sa.BigInteger(), nullable=False),
        sa.Column("match_decision_id", sa.BigInteger(), nullable=False),
        sa.Column("source_occurrence_identity", sa.Text(), nullable=False),
        sa.Column("occurrence_signature", sa.Text(), nullable=False),
        sa.Column("occurrence_ordinal", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("certification_period_id", sa.BigInteger(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        sa.Column("service_type_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_contract_id", sa.BigInteger(), nullable=False),
        sa.Column("care_assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("w2_schedule_id", sa.BigInteger(), nullable=False),
        sa.Column("source_event_state", sa.Text(), nullable=False),
        sa.Column("reference_minutes", sa.Integer(), nullable=False),
        sa.Column("actual_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_seconds", sa.Integer(), nullable=True),
        sa.Column("fact_digest", sa.Text(), nullable=False),
        sa.Column("prior_revision_id", sa.BigInteger(), nullable=True),
        sa.Column("superseded_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("source_type = 'RFID'", name=op.f("ck_w3_actual_work_source_type")),
        sa.CheckConstraint(
            "occurrence_ordinal > 0", name=op.f("ck_w3_actual_work_occurrence_ordinal")
        ),
        sa.CheckConstraint(
            "occurrence_signature ~ '^[0-9a-f]{64}$' AND "
            "fact_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_actual_work_digests"),
        ),
        sa.CheckConstraint(
            "source_event_state IN ('COMPLETE', 'START_ONLY')",
            name=op.f("ck_w3_actual_work_event_state"),
        ),
        sa.CheckConstraint(
            "(source_event_state = 'COMPLETE' AND actual_end IS NOT NULL "
            "AND actual_end > actual_start AND actual_seconds > 0) OR "
            "(source_event_state = 'START_ONLY' AND actual_end IS NULL "
            "AND actual_seconds IS NULL)",
            name=op.f("ck_w3_actual_work_actual_pair"),
        ),
        sa.CheckConstraint(
            "reference_minutes >= 0", name=op.f("ck_w3_actual_work_reference_minutes")
        ),
        sa.UniqueConstraint("id", "target_date", name="uq_w3_actual_work_id_target_date"),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "source_type", "target_date"],
            [
                "erp.w3_source_snapshot.id",
                "erp.w3_source_snapshot.source_type",
                "erp.w3_source_snapshot.target_date",
            ],
            name="fk_w3_actual_work_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id", "snapshot_id"],
            ["erp.w3_import_run.id", "erp.w3_import_run.snapshot_id"],
            name="fk_w3_actual_work_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["prior_revision_id", "target_date"],
            ["erp.w3_actual_work_revision.id", "erp.w3_actual_work_revision.target_date"],
            name="fk_w3_actual_work_prior_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "certification_period_id"],
            [
                "erp.recipient_certification_period.recipient_id",
                "erp.recipient_certification_period.id",
            ],
            name="fk_w3_actual_work_certification_period",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_w3_actual_work_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_w3_actual_work_service_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id", "recipient_contract_id"],
            ["erp.recipient_contract.recipient_id", "erp.recipient_contract.id"],
            name="fk_w3_actual_work_contract",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["care_assignment_id"],
            ["erp.care_assignment.id"],
            name="fk_w3_actual_work_care_assignment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["w2_schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w3_actual_work_schedule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_actual_work_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_actual_work_revision"),
        schema="erp",
    )
    op.create_index(
        "uq_w3_actual_work_current_occurrence",
        "w3_actual_work_revision",
        ["target_date", "source_occurrence_identity"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("superseded_at_utc IS NULL"),
    )
    op.create_index(
        "ix_w3_actual_work_schedule",
        "w3_actual_work_revision",
        ["w2_schedule_id", "target_date", "id"],
        schema="erp",
    )

    _create_command_event_tables()


def _create_command_event_tables() -> None:
    op.create_table(
        "w3_manual_supplement_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actual_work_revision_id", sa.BigInteger(), nullable=False),
        sa.Column("supplement_version", sa.Integer(), nullable=False),
        sa.Column("prior_event_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("proposed_actual_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_digest", sa.Text(), nullable=False),
        sa.Column("command_idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "supplement_version > 0", name=op.f("ck_w3_manual_supplement_version")
        ),
        sa.CheckConstraint(
            "action IN ('CREATE', 'CANCEL', 'REPLACE')",
            name=op.f("ck_w3_manual_supplement_action"),
        ),
        sa.CheckConstraint(
            "(action = 'CANCEL' AND proposed_actual_end IS NULL) OR "
            "(action IN ('CREATE', 'REPLACE') AND proposed_actual_end IS NOT NULL)",
            name=op.f("ck_w3_manual_supplement_end_pair"),
        ),
        sa.CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$' AND btrim(reason) <> ''",
            name=op.f("ck_w3_manual_supplement_payload"),
        ),
        sa.CheckConstraint(
            "btrim(command_idempotency_key) <> ''",
            name=op.f("ck_w3_manual_supplement_command_key"),
        ),
        sa.UniqueConstraint(
            "actual_work_revision_id",
            "supplement_version",
            name="uq_w3_manual_supplement_version",
        ),
        sa.UniqueConstraint(
            "command_idempotency_key",
            name="uq_w3_manual_supplement_command_key",
        ),
        sa.ForeignKeyConstraint(
            ["actual_work_revision_id"],
            ["erp.w3_actual_work_revision.id"],
            name="fk_w3_manual_supplement_actual_work",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_event_id"],
            ["erp.w3_manual_supplement_event.id"],
            name="fk_w3_manual_supplement_prior_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_manual_supplement_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_manual_supplement_event"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_manual_supplement_actual_work",
        "w3_manual_supplement_event",
        ["actual_work_revision_id", "supplement_version"],
        schema="erp",
    )

    op.create_table(
        "w3_plan_adjustment_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actual_work_revision_id", sa.BigInteger(), nullable=False),
        sa.Column("w2_schedule_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("prior_planned_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prior_planned_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adopted_planned_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adopted_planned_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_schedule_row_version", sa.Integer(), nullable=False),
        sa.Column("adopted_schedule_row_version", sa.Integer(), nullable=False),
        sa.Column("expected_month_row_version", sa.Integer(), nullable=False),
        sa.Column("adopted_month_row_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_digest", sa.Text(), nullable=False),
        sa.Column("command_idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(rule_version) <> '' AND btrim(reason) <> ''",
            name=op.f("ck_w3_plan_adjustment_text"),
        ),
        sa.CheckConstraint(
            "prior_planned_start < prior_planned_end AND "
            "adopted_planned_start < adopted_planned_end",
            name=op.f("ck_w3_plan_adjustment_time_order"),
        ),
        sa.CheckConstraint(
            "expected_schedule_row_version > 0 AND adopted_schedule_row_version > 0 AND "
            "expected_month_row_version > 0 AND adopted_month_row_version > 0",
            name=op.f("ck_w3_plan_adjustment_versions"),
        ),
        sa.CheckConstraint(
            "event_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_w3_plan_adjustment_digest"),
        ),
        sa.CheckConstraint(
            "btrim(command_idempotency_key) <> ''",
            name=op.f("ck_w3_plan_adjustment_command_key"),
        ),
        sa.UniqueConstraint(
            "actual_work_revision_id",
            "adopted_schedule_row_version",
            name="uq_w3_plan_adjustment_adoption",
        ),
        sa.UniqueConstraint(
            "command_idempotency_key",
            name="uq_w3_plan_adjustment_command_key",
        ),
        sa.ForeignKeyConstraint(
            ["actual_work_revision_id"],
            ["erp.w3_actual_work_revision.id"],
            name="fk_w3_plan_adjustment_actual_work",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["w2_schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w3_plan_adjustment_schedule",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w3_plan_adjustment_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w3_plan_adjustment_event"),
        schema="erp",
    )
    op.create_index(
        "ix_w3_plan_adjustment_schedule",
        "w3_plan_adjustment_event",
        ["w2_schedule_id", "id"],
        schema="erp",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM erp.account_permission "
        "WHERE permission_code IN ('W3_VIEW', 'W3_MANAGE')"
    )
    op.execute(
        "DELETE FROM erp.permission_definition "
        "WHERE permission_code IN ('W3_VIEW', 'W3_MANAGE')"
    )

    op.drop_index(
        "ix_w3_plan_adjustment_schedule",
        table_name="w3_plan_adjustment_event",
        schema="erp",
    )
    op.drop_table("w3_plan_adjustment_event", schema="erp")
    op.drop_index(
        "ix_w3_manual_supplement_actual_work",
        table_name="w3_manual_supplement_event",
        schema="erp",
    )
    op.drop_table("w3_manual_supplement_event", schema="erp")
    op.drop_index(
        "ix_w3_actual_work_schedule", table_name="w3_actual_work_revision", schema="erp"
    )
    op.drop_index(
        "uq_w3_actual_work_current_occurrence",
        table_name="w3_actual_work_revision",
        schema="erp",
    )
    op.drop_table("w3_actual_work_revision", schema="erp")
    op.drop_table("w3_apply_control", schema="erp")
    op.drop_index(
        "ix_w3_match_decision_run_subject", table_name="w3_match_decision", schema="erp"
    )
    op.drop_table("w3_match_decision", schema="erp")
    op.drop_index(
        "ix_w3_nhis_group_member_group", table_name="w3_nhis_group_member", schema="erp"
    )
    op.drop_table("w3_nhis_group_member", schema="erp")
    op.drop_index("ix_w3_nhis_group_run", table_name="w3_nhis_group", schema="erp")
    op.drop_table("w3_nhis_group", schema="erp")
    op.drop_index(
        "ix_w3_normalized_rfid_run", table_name="w3_normalized_rfid_row", schema="erp"
    )
    op.drop_table("w3_normalized_rfid_row", schema="erp")
    op.drop_index(
        "ix_w3_normalized_nhis_run", table_name="w3_normalized_nhis_row", schema="erp"
    )
    op.drop_table("w3_normalized_nhis_row", schema="erp")
    op.drop_index(
        "ix_w3_import_run_event_run", table_name="w3_import_run_event", schema="erp"
    )
    op.drop_table("w3_import_run_event", schema="erp")
    op.drop_constraint(
        "uq_w3_import_run_id_snapshot",
        "w3_import_run",
        schema="erp",
        type_="unique",
    )
    op.drop_constraint(
        "uq_w3_source_snapshot_id_source_date",
        "w3_source_snapshot",
        schema="erp",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_w3_import_run_row_version"),
        "w3_import_run",
        schema="erp",
        type_="check",
    )
    op.drop_column("w3_import_run", "row_version", schema="erp")
