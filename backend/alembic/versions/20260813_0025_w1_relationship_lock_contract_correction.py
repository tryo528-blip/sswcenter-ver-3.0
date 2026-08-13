"""Restore approved W1 relationship links and locked-month HTTP contract.

Revision ID: 20260813_0025_w1_relationship_lock_contract_correction
Revises: 20260813_0024_w2_service_plan_notice_current
Create Date: 2026-08-13

This forward correction gives the two guardian records stable slots, makes a
deleted payer guardian fall back to recipient-self payment, and restores the
nullable same-staff employment link on health-check date facts.  No historical
employment link is guessed when the earlier revision removed that value.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0025_w1_relationship_lock_contract_correction"
down_revision: str | None = "20260813_0024_w2_service_plan_notice_current"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _correct_guardian_slots_and_payer_delete() -> None:
    op.execute("DROP TRIGGER biu_recipient_guardian_max_two ON erp.recipient_guardian")
    op.execute("DROP FUNCTION erp.fn_recipient_guardian_max_two()")

    op.add_column(
        "recipient_guardian",
        sa.Column("slot_no", sa.SmallInteger(), nullable=True),
        schema="erp",
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (PARTITION BY recipient_id ORDER BY id) AS slot_no
              FROM erp.recipient_guardian
        )
        UPDATE erp.recipient_guardian AS guardian
           SET slot_no = ranked.slot_no
          FROM ranked
         WHERE guardian.id = ranked.id;
        """
    )
    op.alter_column(
        "recipient_guardian",
        "slot_no",
        existing_type=sa.SmallInteger(),
        nullable=False,
        schema="erp",
    )
    op.create_check_constraint(
        op.f("ck_recipient_guardian_slot_no"),
        "recipient_guardian",
        "slot_no IN (1, 2)",
        schema="erp",
    )
    op.create_unique_constraint(
        "uq_recipient_guardian_recipient_slot",
        "recipient_guardian",
        ["recipient_id", "slot_no"],
        schema="erp",
    )
    op.execute(
        """
        CREATE FUNCTION erp.fn_recipient_guardian_assign_slot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            available_slot smallint;
        BEGIN
            PERFORM id
              FROM erp.recipient
             WHERE id = NEW.recipient_id
             FOR UPDATE;

            IF NEW.slot_no IS NULL THEN
                SELECT candidate.slot_no
                  INTO available_slot
                  FROM (VALUES (1::smallint), (2::smallint)) AS candidate(slot_no)
                 WHERE NOT EXISTS (
                    SELECT 1
                      FROM erp.recipient_guardian AS existing
                     WHERE existing.recipient_id = NEW.recipient_id
                       AND existing.slot_no = candidate.slot_no
                       AND existing.id IS DISTINCT FROM NEW.id
                 )
                 ORDER BY candidate.slot_no
                 LIMIT 1;

                IF available_slot IS NULL THEN
                    RAISE EXCEPTION 'a recipient may have at most two guardian slots'
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ck_recipient_guardian_max_two';
                END IF;
                NEW.slot_no := available_slot;
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE TRIGGER biu_recipient_guardian_assign_slot
        BEFORE INSERT OR UPDATE OF recipient_id, slot_no
        ON erp.recipient_guardian
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_recipient_guardian_assign_slot();
        """
    )

    op.drop_constraint(
        "fk_recipient_payer_guardian_same_recipient",
        "recipient",
        schema="erp",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_recipient_payer_guardian_same_recipient",
        "recipient",
        "recipient_guardian",
        ["id", "payer_guardian_id"],
        ["recipient_id", "id"],
        source_schema="erp",
        referent_schema="erp",
        ondelete="SET NULL (payer_guardian_id)",
    )


def _restore_health_check_employment_link() -> None:
    op.add_column(
        "staff_health_check",
        sa.Column("employment_id", sa.BigInteger(), nullable=True),
        schema="erp",
    )
    op.create_foreign_key(
        "fk_staff_health_check_employment",
        "staff_health_check",
        "staff_employment",
        ["staff_id", "employment_id"],
        ["staff_id", "id"],
        source_schema="erp",
        referent_schema="erp",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    _correct_guardian_slots_and_payer_delete()
    _restore_health_check_employment_link()


def downgrade() -> None:
    raise RuntimeError(
        "20260813_0025_w1_relationship_lock_contract_correction is forward-only; "
        "restore a verified pre-upgrade backup instead"
    )
