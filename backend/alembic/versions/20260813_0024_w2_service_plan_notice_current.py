"""Create the corrected writable W2 service-plan notice ledger.

Revision ID: 20260813_0024_w2_service_plan_notice_current
Revises: 20260813_0023_w2_core_ledgers
Create Date: 2026-08-13

The historical ``recipient_service_plan_notice`` table remains read-only after
0019.  This migration intentionally creates a separate operating ledger and
does not copy historical rows into it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0024_w2_service_plan_notice_current"
down_revision: str | None = "20260813_0023_w2_core_ledgers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_table() -> None:
    op.create_table(
        "w2_service_plan_notice",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_contract_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_date", sa.Date(), nullable=False),
        sa.Column("applied_start_date", sa.Date(), nullable=False),
        sa.Column("applied_end_date", sa.Date(), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_service_plan_notice_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by_account_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint(
            "applied_start_date <= applied_end_date",
            name="w2_service_plan_notice_date_order",
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name="w2_service_plan_notice_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_contract_id"],
            ["erp.recipient_contract.id"],
            name="fk_w2_service_plan_notice_contract",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_service_plan_notice_id"],
            ["erp.w2_service_plan_notice.id"],
            name="fk_w2_service_plan_notice_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_service_plan_notice_created_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_service_plan_notice_updated_by",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w2_service_plan_notice"),
        schema="erp",
    )
    op.create_index(
        "ix_w2_service_plan_notice_contract_notification",
        "w2_service_plan_notice",
        ["recipient_contract_id", "notification_date", "id"],
        schema="erp",
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_w2_service_plan_notice_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.invalidated_at_utc IS NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                      FROM erp.recipient_contract contract
                     WHERE contract.id = NEW.recipient_contract_id
                       AND contract.invalidated_at_utc IS NULL
                       AND contract.start_date <= NEW.applied_start_date
                       AND (
                           contract.end_date IS NULL
                           OR contract.end_date >= NEW.applied_end_date
                       )
                ) THEN
                    RAISE EXCEPTION 'W2_SERVICE_PLAN_OUTSIDE_CONTRACT'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ct_w2_service_plan_notice_contract_guard';
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                      FROM erp.recipient_contract contract
                      JOIN erp.recipient_certification_period certification
                        ON certification.recipient_id = contract.recipient_id
                       AND certification.invalidated_at_utc IS NULL
                       AND certification.start_date <= NEW.applied_start_date
                       AND certification.end_date >= NEW.applied_end_date
                     WHERE contract.id = NEW.recipient_contract_id
                ) THEN
                    RAISE EXCEPTION 'W2_SERVICE_PLAN_OUTSIDE_CERTIFICATION'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ct_w2_service_plan_notice_cert_guard';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE FUNCTION erp.fn_w2_service_plan_contract_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM erp.w2_service_plan_notice plan
                 WHERE plan.recipient_contract_id = NEW.id
                   AND plan.invalidated_at_utc IS NULL
                   AND (
                       NEW.invalidated_at_utc IS NOT NULL
                       OR OLD.recipient_id IS DISTINCT FROM NEW.recipient_id
                       OR NEW.start_date > plan.applied_start_date
                       OR (
                           NEW.end_date IS NOT NULL
                           AND NEW.end_date < plan.applied_end_date
                       )
                   )
            ) THEN
                RAISE EXCEPTION 'W2_SERVICE_PLAN_OUTSIDE_CONTRACT'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_w2_service_plan_contract_reverse_guard';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE FUNCTION erp.fn_w2_service_plan_certification_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            recipient_ids bigint[];
            recipient_id_value bigint;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                recipient_ids := ARRAY[NEW.recipient_id];
            ELSIF TG_OP = 'DELETE' THEN
                recipient_ids := ARRAY[OLD.recipient_id];
            ELSE
                recipient_ids := ARRAY[OLD.recipient_id, NEW.recipient_id];
            END IF;

            FOREACH recipient_id_value IN ARRAY recipient_ids LOOP
                IF EXISTS (
                    SELECT 1
                      FROM erp.w2_service_plan_notice plan
                      JOIN erp.recipient_contract contract
                        ON contract.id = plan.recipient_contract_id
                     WHERE contract.recipient_id = recipient_id_value
                       AND plan.invalidated_at_utc IS NULL
                       AND NOT EXISTS (
                           SELECT 1
                             FROM erp.recipient_certification_period certification
                            WHERE certification.recipient_id = recipient_id_value
                              AND certification.invalidated_at_utc IS NULL
                              AND certification.start_date <= plan.applied_start_date
                              AND certification.end_date >= plan.applied_end_date
                       )
                ) THEN
                    RAISE EXCEPTION 'W2_SERVICE_PLAN_OUTSIDE_CERTIFICATION'
                        USING ERRCODE = '23514',
                              CONSTRAINT =
                                  'ct_w2_service_plan_certification_reverse_guard';
                END IF;
            END LOOP;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_w2_service_plan_notice_guard
        AFTER INSERT OR UPDATE ON erp.w2_service_plan_notice
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_w2_service_plan_notice_guard();

        CREATE CONSTRAINT TRIGGER ct_w2_service_plan_contract_reverse_guard
        AFTER UPDATE ON erp.recipient_contract
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_w2_service_plan_contract_reverse_guard();

        CREATE CONSTRAINT TRIGGER ct_w2_service_plan_certification_reverse_guard
        AFTER INSERT OR UPDATE OR DELETE ON erp.recipient_certification_period
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_w2_service_plan_certification_reverse_guard();
        """
    )


def _grant_runtime_roles() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT SELECT, INSERT, UPDATE
                    ON TABLE erp.w2_service_plan_notice TO erp_app;
                REVOKE DELETE, TRUNCATE
                    ON TABLE erp.w2_service_plan_notice FROM erp_app;
                GRANT USAGE, SELECT
                    ON SEQUENCE erp.w2_service_plan_notice_id_seq TO erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT SELECT
                    ON TABLE erp.w2_service_plan_notice TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE
                    ON TABLE erp.w2_service_plan_notice FROM erp_backup;
                GRANT SELECT
                    ON SEQUENCE erp.w2_service_plan_notice_id_seq TO erp_backup;
                REVOKE USAGE
                    ON SEQUENCE erp.w2_service_plan_notice_id_seq FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def _retire_legacy_plan_notification_writes() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_recipient_plan_notification_read_only()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'RECIPIENT_PLAN_NOTIFICATION_READ_ONLY'
                USING ERRCODE = '55000';
        END
        $$;

        CREATE TRIGGER tr_recipient_plan_notification_read_only
        BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
        ON erp.recipient_plan_notification
        FOR EACH STATEMENT
        EXECUTE FUNCTION erp.fn_recipient_plan_notification_read_only();

        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE
                    ON TABLE erp.recipient_plan_notification FROM erp_app;
                IF to_regclass('erp.recipient_plan_notification_id_seq') IS NOT NULL THEN
                    REVOKE USAGE, UPDATE
                        ON SEQUENCE erp.recipient_plan_notification_id_seq FROM erp_app;
                END IF;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_table()
    _create_guards()
    _grant_runtime_roles()
    _retire_legacy_plan_notification_writes()


def downgrade() -> None:
    raise RuntimeError(
        "20260813_0024_w2_service_plan_notice_current is forward-only because "
        "downgrading would either delete current operating rows or leave the "
        "database schema inconsistent; restore a verified pre-upgrade backup"
    )
