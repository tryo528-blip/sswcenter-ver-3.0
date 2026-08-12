"""Add W1D recipient_contract ledger.

Revision ID: 20260730_0011_w1d_recipient_contract
Revises: 20260730_0010_w1c_certification_ledgers
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260730_0011_w1d_recipient_contract"
down_revision: str | None = "20260730_0010_w1c_certification_ledgers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "recipient_contract"


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
        sa.Column(
            "row_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
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


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("service_type_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "contract_period",
            postgresql.DATERANGE(),
            # NULL end_date → NULL upper bound via SQL NULL propagation on end_date+1
            # → exact unbounded half-open [start,) (not explicit infinity).
            sa.Computed(
                "daterange(start_date, end_date + 1, '[)')",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("service_start_date", sa.Date(), nullable=True),
        sa.Column("end_reason_text", sa.Text(), nullable=True),
        sa.Column("signer_name", sa.Text(), nullable=True),
        sa.Column("signer_relationship_text", sa.Text(), nullable=True),
        sa.Column("signer_phone", sa.Text(), nullable=True),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_contract_id", sa.BigInteger(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name=op.f("ck_recipient_contract_date_order"),
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name=op.f("ck_recipient_contract_row_version_positive"),
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("service_type_id", "="),
            ("contract_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_contract_same_service_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_contract_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_recipient_contract_service_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_contract_id"],
            ["erp.recipient_contract.id"],
            name="fk_recipient_contract_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints(_TABLE),
        sa.PrimaryKeyConstraint("id", name="pk_recipient_contract"),
        schema="erp",
    )

    op.execute(
        """
        CREATE FUNCTION erp.fn_recipient_contract_no_reactivation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.end_date IS NOT NULL AND NEW.end_date IS NULL THEN
                RAISE EXCEPTION 'recipient contract reactivation is forbidden'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_contract_no_reactivation';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE TRIGGER bu_recipient_contract_no_reactivation
        BEFORE UPDATE OF end_date
        ON erp.recipient_contract
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_recipient_contract_no_reactivation();

        CREATE FUNCTION erp.fn_recipient_contract_group_overlap()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            conflict_id bigint;
            new_group_id bigint;
        BEGIN
            IF NEW.invalidated_at_utc IS NOT NULL THEN
                RETURN NEW;
            END IF;

            -- Parent-row lock first (deterministic order; deadlock avoidance).
            PERFORM id FROM erp.recipient WHERE id = NEW.recipient_id FOR UPDATE;

            SELECT st.service_group_id INTO new_group_id
            FROM erp.service_type st
            WHERE st.id = NEW.service_type_id;

            IF new_group_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT c.id INTO conflict_id
            FROM erp.recipient_contract c
            JOIN erp.service_type st ON st.id = c.service_type_id
            WHERE c.recipient_id = NEW.recipient_id
              AND c.invalidated_at_utc IS NULL
              AND c.id IS DISTINCT FROM NEW.id
              AND st.service_group_id IS DISTINCT FROM new_group_id
              AND c.contract_period && NEW.contract_period
            LIMIT 1;

            IF conflict_id IS NOT NULL THEN
                RAISE EXCEPTION
                    'recipient contract cross-group period overlap with id=%',
                    conflict_id
                    USING ERRCODE = '23P01',
                          CONSTRAINT = 'trg_recipient_contract_group_period_overlap';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER trg_recipient_contract_group_period_overlap
        AFTER INSERT OR UPDATE ON erp.recipient_contract
        DEFERRABLE INITIALLY IMMEDIATE
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_recipient_contract_group_overlap();
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE erp.{_TABLE} TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE erp.{_TABLE} FROM erp_app;
                GRANT USAGE, SELECT ON SEQUENCE erp.{_TABLE}_id_seq TO erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE erp.{_TABLE} TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE erp.{_TABLE}
                    FROM erp_backup;
                GRANT SELECT ON SEQUENCE erp.{_TABLE}_id_seq TO erp_backup;
                REVOKE USAGE ON SEQUENCE erp.{_TABLE}_id_seq FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.{_TABLE} FROM erp_app;
                REVOKE USAGE, SELECT ON SEQUENCE erp.{_TABLE}_id_seq FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    erp.{_TABLE} FROM erp_backup;
                REVOKE USAGE, SELECT ON SEQUENCE erp.{_TABLE}_id_seq FROM erp_backup;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_recipient_contract_group_period_overlap
            ON erp.recipient_contract;
        DROP FUNCTION IF EXISTS erp.fn_recipient_contract_group_overlap();
        DROP TRIGGER IF EXISTS bu_recipient_contract_no_reactivation
            ON erp.recipient_contract;
        DROP FUNCTION IF EXISTS erp.fn_recipient_contract_no_reactivation();
        """
    )
    op.drop_table(_TABLE, schema="erp")
