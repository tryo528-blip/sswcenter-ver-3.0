"""Correct the W1 recipient, guardian, payer, and contract schema.

Revision ID: 20260813_0021_w1_recipient_contract_correction
Revises: 20260813_0020_w1_staff_contract_correction
Create Date: 2026-08-13

This is a canonical forward-only correction.  Removed primary-guardian,
payer-snapshot, home-phone, and contract-signer data is recoverable only from
the pre-upgrade database backup.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0021_w1_recipient_contract_correction"
down_revision: str | None = "20260813_0020_w1_staff_contract_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fail_closed_preflight() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM erp.recipient
                WHERE mobile_phone IS NULL OR btrim(mobile_phone) = ''
            ) THEN
                RAISE EXCEPTION
                    'recipient mobile_phone is required by the corrected W1 contract'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_mobile_phone_required';
            END IF;

            IF EXISTS (
                SELECT recipient_id
                FROM erp.recipient_guardian
                GROUP BY recipient_id
                HAVING count(*) > 2
            ) THEN
                RAISE EXCEPTION
                    'a recipient has more than two guardians'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_guardian_max_two';
            END IF;
        END
        $$;
        """
    )


def _correct_recipient_columns() -> None:
    op.alter_column(
        "recipient",
        "name",
        existing_type=sa.Text(),
        nullable=True,
        schema="erp",
    )
    op.alter_column(
        "recipient",
        "birth_date",
        existing_type=sa.Date(),
        nullable=True,
        schema="erp",
    )
    op.alter_column(
        "recipient",
        "sex_code",
        existing_type=sa.Text(),
        nullable=True,
        schema="erp",
    )
    op.alter_column(
        "recipient",
        "mobile_phone",
        existing_type=sa.Text(),
        nullable=False,
        schema="erp",
    )
    op.create_check_constraint(
        op.f("ck_recipient_mobile_phone_required"),
        "recipient",
        "btrim(mobile_phone) <> ''",
        schema="erp",
    )
    op.drop_column("recipient", "home_phone", schema="erp")


def _correct_guardians() -> None:
    op.alter_column(
        "recipient_guardian",
        "name",
        existing_type=sa.Text(),
        nullable=True,
        schema="erp",
    )
    op.execute(
        """
        CREATE FUNCTION erp.fn_recipient_guardian_max_two()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            other_guardian_count integer;
        BEGIN
            -- Serialize guardian creation per recipient so concurrent inserts
            -- cannot both pass the cardinality check.
            PERFORM id
            FROM erp.recipient
            WHERE id = NEW.recipient_id
            FOR UPDATE;

            SELECT count(*)
            INTO other_guardian_count
            FROM erp.recipient_guardian guardian
            WHERE guardian.recipient_id = NEW.recipient_id
              AND guardian.id IS DISTINCT FROM NEW.id;

            IF other_guardian_count >= 2 THEN
                RAISE EXCEPTION 'a recipient may have at most two guardians'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_recipient_guardian_max_two';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE TRIGGER biu_recipient_guardian_max_two
        BEFORE INSERT OR UPDATE OF recipient_id
        ON erp.recipient_guardian
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_recipient_guardian_max_two();
        """
    )


def _remove_retired_ledgers_and_fields() -> None:
    op.drop_table("recipient_payer_snapshot", schema="erp")
    op.drop_table("recipient_guardian_primary_period", schema="erp")

    op.drop_column("recipient_contract", "signer_phone", schema="erp")
    op.drop_column("recipient_contract", "signer_relationship_text", schema="erp")
    op.drop_column("recipient_contract", "signer_name", schema="erp")

    op.execute(
        """
        UPDATE erp.permission_definition
        SET name = '수급자정보 조회',
            description = '수급자와 최대 두 명의 보호자 및 납부자 선택 조회',
            active = true
        WHERE permission_code = 'RECIPIENT_VIEW';

        UPDATE erp.permission_definition
        SET name = '수급자정보 관리',
            description = '수급자와 최대 두 명의 보호자 및 납부자 선택 관리',
            active = true
        WHERE permission_code = 'RECIPIENT_MANAGE';
        """
    )


def upgrade() -> None:
    _fail_closed_preflight()
    _remove_retired_ledgers_and_fields()
    _correct_recipient_columns()
    _correct_guardians()


def downgrade() -> None:
    raise RuntimeError(
        "20260813_0021_w1_recipient_contract_correction is a canonical "
        "forward-only migration; operational rollback is pre-upgrade backup restore"
    )
