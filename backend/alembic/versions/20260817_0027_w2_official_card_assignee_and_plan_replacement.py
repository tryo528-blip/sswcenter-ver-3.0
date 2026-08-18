"""Seal W2 recipient-local service-plan replacement links declaratively.

Revision ID: 20260817_0027_w2_official_card_assignee_and_plan_replacement
Revises: 20260814_0026_w1e_care_assignment_family_relationship_lock
Create Date: 2026-08-17

``w2_service_plan_notice`` originally carried only a contract id. A pair of
0027 constraint triggers tried to infer the recipient through that contract,
which made the same-recipient replacement invariant procedural and fragile.
This forward migration denormalizes the already-known recipient id into the
operating ledger, validates/backfills it, and makes both edges composite foreign
keys. Therefore a direct SQL update, a final deferred transaction state, and
concurrent writers all see the same database-enforced invariant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
down_revision: str | None = "20260814_0026_w1e_care_assignment_family_relationship_lock"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        -- The prior incomplete 0027 candidate was never applied, but remove its
        -- exact objects defensively so a disposable catalog cannot retain a
        -- procedural shadow of the declarative invariant.
        DROP TRIGGER IF EXISTS ct_w2_service_plan_replacement_contract_reverse
            ON erp.recipient_contract;
        DROP TRIGGER IF EXISTS ct_w2_service_plan_replacement_same_recipient
            ON erp.w2_service_plan_notice;
        DROP FUNCTION IF EXISTS
            erp.fn_w2_service_plan_replacement_contract_reverse();
        DROP FUNCTION IF EXISTS
            erp.fn_w2_service_plan_replacement_same_recipient();

        ALTER TABLE erp.w2_service_plan_notice
            ADD COLUMN recipient_id BIGINT;

        UPDATE erp.w2_service_plan_notice AS notice
           SET recipient_id = contract.recipient_id
          FROM erp.recipient_contract AS contract
         WHERE contract.id = notice.recipient_contract_id;

        -- 0026's simple self FK is initially deferred.  Updating a legacy
        -- row can queue its trigger even where the replacement id is NULL;
        -- drain that queue before later ALTER TABLE statements replace it.
        SET CONSTRAINTS ALL IMMEDIATE;

        -- Fail before NOT NULL/foreign-key DDL if legacy or manually altered
        -- rows cannot be represented by the new exact recipient-local graph.
        DO $$
        DECLARE
            invalid_count bigint;
        BEGIN
            SELECT count(*)
              INTO invalid_count
              FROM erp.w2_service_plan_notice AS source
              LEFT JOIN erp.recipient_contract AS source_contract
                ON source_contract.id = source.recipient_contract_id
              LEFT JOIN erp.w2_service_plan_notice AS target
                ON target.id = source.replacement_service_plan_notice_id
             WHERE source.recipient_id IS NULL
                OR source_contract.id IS NULL
                OR source.recipient_id IS DISTINCT FROM source_contract.recipient_id
                OR (
                    source.replacement_service_plan_notice_id IS NOT NULL
                    AND (
                        target.id IS NULL
                        OR source.recipient_id IS DISTINCT FROM target.recipient_id
                    )
                );
            IF invalid_count <> 0 THEN
                RAISE EXCEPTION
                    'W2_SERVICE_PLAN_NOTICE_RECIPIENT_BACKFILL_INVALID: %',
                    invalid_count
                    USING ERRCODE = '23514',
                          CONSTRAINT =
                              'ck_w2_service_plan_notice_recipient_backfill';
            END IF;
        END
        $$;

        ALTER TABLE erp.w2_service_plan_notice
            ALTER COLUMN recipient_id SET NOT NULL;

        -- PostgreSQL requires a non-partial exact unique key for the referenced
        -- columns even though each table also has an id primary key.
        ALTER TABLE erp.recipient_contract
            ADD CONSTRAINT uq_recipient_contract_recipient_id_id
            UNIQUE (recipient_id, id);
        ALTER TABLE erp.w2_service_plan_notice
            ADD CONSTRAINT uq_w2_service_plan_notice_recipient_id_id
            UNIQUE (recipient_id, id);

        -- Replace the old independent edges only after both referenced unique
        -- keys exist. The replacement FK remains deferred to allow one
        -- transaction to correct its final recipient-local graph.
        ALTER TABLE erp.w2_service_plan_notice
            DROP CONSTRAINT fk_w2_service_plan_notice_replacement;
        ALTER TABLE erp.w2_service_plan_notice
            DROP CONSTRAINT fk_w2_service_plan_notice_contract;
        ALTER TABLE erp.w2_service_plan_notice
            ADD CONSTRAINT fk_w2_service_plan_notice_contract_same_recipient
            FOREIGN KEY (recipient_id, recipient_contract_id)
            REFERENCES erp.recipient_contract (recipient_id, id)
            ON DELETE RESTRICT;
        ALTER TABLE erp.w2_service_plan_notice
            ADD CONSTRAINT fk_w2_service_plan_notice_replacement_same_recipient
            FOREIGN KEY (recipient_id, replacement_service_plan_notice_id)
            REFERENCES erp.w2_service_plan_notice (recipient_id, id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        -- Restore the exact 0026 shape in dependency order: child composite
        -- edges, their unique keys, then the old simple edges and finally the
        -- denormalized column. This makes 0026 -> 0027 -> 0026 -> 0027 a
        -- supported lifecycle for the disposable verification harness.
        ALTER TABLE erp.w2_service_plan_notice
            DROP CONSTRAINT IF EXISTS
                fk_w2_service_plan_notice_replacement_same_recipient;
        ALTER TABLE erp.w2_service_plan_notice
            DROP CONSTRAINT IF EXISTS
                fk_w2_service_plan_notice_contract_same_recipient;
        ALTER TABLE erp.w2_service_plan_notice
            DROP CONSTRAINT IF EXISTS uq_w2_service_plan_notice_recipient_id_id;
        ALTER TABLE erp.recipient_contract
            DROP CONSTRAINT IF EXISTS uq_recipient_contract_recipient_id_id;

        ALTER TABLE erp.w2_service_plan_notice
            ADD CONSTRAINT fk_w2_service_plan_notice_contract
            FOREIGN KEY (recipient_contract_id)
            REFERENCES erp.recipient_contract (id)
            ON DELETE RESTRICT;
        ALTER TABLE erp.w2_service_plan_notice
            ADD CONSTRAINT fk_w2_service_plan_notice_replacement
            FOREIGN KEY (replacement_service_plan_notice_id)
            REFERENCES erp.w2_service_plan_notice (id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;

        ALTER TABLE erp.w2_service_plan_notice
            DROP COLUMN recipient_id;

        DROP TRIGGER IF EXISTS ct_w2_service_plan_replacement_contract_reverse
            ON erp.recipient_contract;
        DROP TRIGGER IF EXISTS ct_w2_service_plan_replacement_same_recipient
            ON erp.w2_service_plan_notice;
        DROP FUNCTION IF EXISTS
            erp.fn_w2_service_plan_replacement_contract_reverse();
        DROP FUNCTION IF EXISTS
            erp.fn_w2_service_plan_replacement_same_recipient();
        """
    )
