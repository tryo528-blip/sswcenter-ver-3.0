"""Forward W1E FAMILY relationship snapshot and deterministic path locks.

Revision ID: 20260814_0026_w1e_care_assignment_family_relationship_lock
Revises: 20260813_0025_w1_relationship_lock_contract_correction
Create Date: 2026-08-14

Historical migration 0012 intentionally allowed a nullable relationship text
while the W1E product was absent.  This linear correction enforces the approved
``FAMILY`` relationship snapshot at database level for current data without
rewriting or weakening the historical 0012 evidence.

The same forward migration also closes the 0012 write-skew window.  The 0012
constraint triggers used plain SELECT reads for parent containment and reverse
guards, so an assignment INSERT and a parent period shrink could both pass
against each other's uncommitted state.  The current head replaces the previous
single ``erp.w1e.global`` transaction mutex with a fine-grained optimistic,
fail-fast commit protocol.

Every W1E care-assignment and parent reverse-guard path acquires transaction-scoped
advisory locks on only the exact contract-domain or employment-domain keys it
touches.  Acquisition uses ``pg_try_advisory_xact_lock`` (non-waiting): if any
relevant domain key is already owned by another transaction, the helper raises
SQLSTATE ``55P03`` with the stable message ``CARE_ASSIGNMENT_CONCURRENT_CONFLICT``
immediately and the whole transaction rolls back.  No W1E transaction waits
while holding a partial set of domain locks, so multi-row assignment
transactions and multi-edge parent paths cannot form ``40P01`` cycles.

After the relevant domain keys are acquired, each guard re-runs its validation
query against the latest committed state (READ COMMITTED snapshot).  Because
every writer honors the same advisory keys, a transaction that commits before
the lock acquisition is visible to that final validation, and a transaction
that tries to commit after the lock acquisition fails fast instead of racing
the final check.  Unrelated contract/employment domains proceed concurrently.

The per-path domain order remains contract-domain locks before employment-domain
locks, and each domain's keys are ascending:

* assignment INSERT/UPDATE locks contract id then employment id;
* recipient_contract reverse guard acquires every distinct contract-domain
  lock for the affected contract in ascending contract id order first, then
  every distinct employment-domain lock for the same committed active
  assignment edges in ascending employment id order; when no committed edge
  exists it keeps the contract parent-domain lock;
* staff_employment / staff_position_period / staff_service_qualification_period
  reverse guards acquire every distinct contract-domain lock for the affected
  staff+employment committed active assignment edges in ascending contract id
  order first, then always acquire the fixed employment-domain lock for
  ``p_employment_id``.

An uncommitted assignment is invisible to the parent SELECT, so a parent that
locked only committed edges would take no lock and race the INSERT.  The
contract-side helper keeps its parent-domain fallback for the empty case; the
employment-side helper always takes the fixed employment lock after the
contract locks because ``p_employment_id`` is invariant for that path.
"""

from collections.abc import Sequence

from alembic import op
from app.db.w1e_family_relationship import (
    family_relationship_present_predicate_sql,
    family_relationship_trim_sql_literal,
)

revision: str = "20260814_0026_w1e_care_assignment_family_relationship_lock"
down_revision: str | None = "20260813_0025_w1_relationship_lock_contract_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_care_assignment_family_relationship_present"

_LOCK_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_contract_path(p_contract_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT pg_try_advisory_xact_lock(
        hashtextextended('erp.w1e.contract', p_contract_id)
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55P03',
            MESSAGE = 'CARE_ASSIGNMENT_CONCURRENT_CONFLICT';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_employment_path(p_employment_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT pg_try_advisory_xact_lock(
        hashtextextended('erp.w1e.employment', p_employment_id)
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55P03',
            MESSAGE = 'CARE_ASSIGNMENT_CONCURRENT_CONFLICT';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_assignment_path(
    p_contract_id bigint,
    p_employment_id bigint
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_contract_path(p_contract_id);
    PERFORM erp.fn_w1e_lock_employment_path(p_employment_id);
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_contract_assignment_edges(
    p_contract_id bigint
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    edge record;
    locked_edge boolean := false;
BEGIN
    FOR edge IN
        SELECT DISTINCT assignment.recipient_contract_id
          FROM erp.care_assignment assignment
         WHERE assignment.recipient_contract_id = p_contract_id
           AND assignment.invalidated_at_utc IS NULL
         ORDER BY assignment.recipient_contract_id
    LOOP
        PERFORM erp.fn_w1e_lock_contract_path(
            edge.recipient_contract_id
        );
        locked_edge := true;
    END LOOP;
    IF NOT locked_edge THEN
        PERFORM erp.fn_w1e_lock_contract_path(p_contract_id);
    END IF;
    FOR edge IN
        SELECT DISTINCT assignment.employment_id
          FROM erp.care_assignment assignment
         WHERE assignment.recipient_contract_id = p_contract_id
           AND assignment.invalidated_at_utc IS NULL
         ORDER BY assignment.employment_id
    LOOP
        PERFORM erp.fn_w1e_lock_employment_path(
            edge.employment_id
        );
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_employment_assignment_edges(
    p_employment_id bigint,
    p_staff_id bigint
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    edge record;
BEGIN
    FOR edge IN
        SELECT DISTINCT assignment.recipient_contract_id
          FROM erp.care_assignment assignment
         WHERE assignment.employment_id = p_employment_id
           AND assignment.staff_id = p_staff_id
           AND assignment.invalidated_at_utc IS NULL
         ORDER BY assignment.recipient_contract_id
    LOOP
        PERFORM erp.fn_w1e_lock_contract_path(
            edge.recipient_contract_id
        );
    END LOOP;
    PERFORM erp.fn_w1e_lock_employment_path(p_employment_id);
END
$$;
"""

_REPLACE_W1E_GUARD_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_assignment_path(
        NEW.recipient_contract_id,
        NEW.employment_id
    );
    IF NEW.invalidated_at_utc IS NULL AND NOT EXISTS (
        SELECT 1
        FROM erp.recipient_contract contract
        WHERE contract.id = NEW.recipient_contract_id
          AND contract.invalidated_at_utc IS NULL
          AND NEW.assignment_period <@ contract.contract_period
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_employment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_assignment_path(
        NEW.recipient_contract_id,
        NEW.employment_id
    );
    IF NEW.invalidated_at_utc IS NULL AND NOT EXISTS (
        SELECT 1
        FROM erp.staff_employment employment
        WHERE employment.id = NEW.employment_id
          AND employment.staff_id = NEW.staff_id
          AND employment.invalidated_at_utc IS NULL
          AND NEW.assignment_period <@ employment.employment_period
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_position()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_assignment_path(
        NEW.recipient_contract_id,
        NEW.employment_id
    );
    IF NEW.invalidated_at_utc IS NULL
       AND NEW.assignment_kind = 'GENERAL'
       AND NOT (
           NEW.assignment_period <@ COALESCE(
               (
                   SELECT range_agg(position.position_period)
                   FROM erp.staff_position_period position
                   WHERE position.staff_id = NEW.staff_id
                     AND position.employment_id = NEW.employment_id
                     AND position.position_code = 'CARE_WORKER'
                     AND position.invalidated_at_utc IS NULL
               ), '{}'::datemultirange
           )
       )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_STAFF_INELIGIBLE';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_care_assignment_general_care_qualified()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_assignment_path(
        NEW.recipient_contract_id,
        NEW.employment_id
    );
    IF NEW.invalidated_at_utc IS NULL
       AND NEW.assignment_kind = 'GENERAL'
       AND EXISTS (
           SELECT 1
           FROM erp.recipient_contract contract
           WHERE contract.id = NEW.recipient_contract_id
             AND contract.invalidated_at_utc IS NULL
             AND NOT (
                 NEW.assignment_period <@ COALESCE(
                     (
                         SELECT range_agg(qualification.qualification_period)
                         FROM erp.staff_service_qualification_period qualification
                         WHERE qualification.staff_id = NEW.staff_id
                           AND qualification.employment_id = NEW.employment_id
                           AND qualification.service_type_id = contract.service_type_id
                           AND qualification.invalidated_at_utc IS NULL
                     ), '{}'::datemultirange
                 )
             )
       )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_STAFF_INELIGIBLE';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_recipient_contract_assignment_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_contract_assignment_edges(NEW.id);
    IF EXISTS (
        SELECT 1
        FROM erp.care_assignment assignment
        WHERE assignment.recipient_contract_id = NEW.id
          AND assignment.invalidated_at_utc IS NULL
          AND (
              NEW.invalidated_at_utc IS NOT NULL
              OR NOT (assignment.assignment_period <@ NEW.contract_period)
              OR (
                  assignment.assignment_kind = 'GENERAL'
                  AND NOT (
                      assignment.assignment_period <@ COALESCE(
                          (
                              SELECT range_agg(
                                  qualification.qualification_period
                              )
                              FROM erp.staff_service_qualification_period
                                  qualification
                              WHERE qualification.staff_id = assignment.staff_id
                                AND qualification.employment_id =
                                    assignment.employment_id
                                AND qualification.service_type_id =
                                    NEW.service_type_id
                                AND qualification.invalidated_at_utc IS NULL
                          ), '{}'::datemultirange
                      )
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_staff_employment_child_periods_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_employment_assignment_edges(NEW.id, NEW.staff_id);
    IF EXISTS (
        SELECT 1 FROM erp.staff_position_period child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    ) OR EXISTS (
        SELECT 1 FROM erp.staff_operational_role_period child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    ) OR EXISTS (
        SELECT 1 FROM erp.staff_service_qualification_period child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    ) OR EXISTS (
        SELECT 1 FROM erp.care_assignment child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'STAFF_PERIOD_OUTSIDE_EMPLOYMENT';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_staff_position_care_assignment_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_employment_assignment_edges(
        OLD.employment_id,
        OLD.staff_id
    );
    IF EXISTS (
        SELECT 1 FROM erp.care_assignment assignment
        WHERE assignment.staff_id = OLD.staff_id
          AND assignment.employment_id = OLD.employment_id
          AND assignment.assignment_kind = 'GENERAL'
          AND assignment.invalidated_at_utc IS NULL
          AND NOT (
              assignment.assignment_period <@ COALESCE(
                  (
                      SELECT range_agg(position.position_period)
                      FROM erp.staff_position_period position
                      WHERE position.staff_id = assignment.staff_id
                        AND position.employment_id = assignment.employment_id
                        AND position.position_code = 'CARE_WORKER'
                        AND position.invalidated_at_utc IS NULL
                  ), '{}'::datemultirange
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_staff_service_qualification_assignment_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM erp.fn_w1e_lock_employment_assignment_edges(
        OLD.employment_id,
        OLD.staff_id
    );
    IF EXISTS (
        SELECT 1
        FROM erp.care_assignment assignment
        JOIN erp.recipient_contract contract
          ON contract.id = assignment.recipient_contract_id
        WHERE assignment.staff_id = OLD.staff_id
          AND assignment.employment_id = OLD.employment_id
          AND assignment.assignment_kind = 'GENERAL'
          AND assignment.invalidated_at_utc IS NULL
          AND contract.invalidated_at_utc IS NULL
          AND contract.service_type_id = OLD.service_type_id
          AND NOT (
              assignment.assignment_period <@ COALESCE(
                  (
                      SELECT range_agg(qualification.qualification_period)
                      FROM erp.staff_service_qualification_period qualification
                      WHERE qualification.staff_id = assignment.staff_id
                        AND qualification.employment_id = assignment.employment_id
                        AND qualification.service_type_id = contract.service_type_id
                        AND qualification.invalidated_at_utc IS NULL
                  ), '{}'::datemultirange
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN';
    END IF;
    RETURN NEW;
END
$$;
"""

_RESTORE_0012_GUARD_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.invalidated_at_utc IS NULL AND NOT EXISTS (
        SELECT 1
        FROM erp.recipient_contract contract
        WHERE contract.id = NEW.recipient_contract_id
          AND contract.invalidated_at_utc IS NULL
          AND NEW.assignment_period <@ contract.contract_period
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_employment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.invalidated_at_utc IS NULL AND NOT EXISTS (
        SELECT 1
        FROM erp.staff_employment employment
        WHERE employment.id = NEW.employment_id
          AND employment.staff_id = NEW.staff_id
          AND employment.invalidated_at_utc IS NULL
          AND NEW.assignment_period <@ employment.employment_period
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_position()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.invalidated_at_utc IS NULL
       AND NEW.assignment_kind = 'GENERAL'
       AND NOT (
           NEW.assignment_period <@ COALESCE(
               (
                   SELECT range_agg(position.position_period)
                   FROM erp.staff_position_period position
                   WHERE position.staff_id = NEW.staff_id
                     AND position.employment_id = NEW.employment_id
                     AND position.position_code = 'CARE_WORKER'
                     AND position.invalidated_at_utc IS NULL
               ), '{}'::datemultirange
           )
       )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_STAFF_INELIGIBLE';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_care_assignment_general_care_qualified()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.invalidated_at_utc IS NULL
       AND NEW.assignment_kind = 'GENERAL'
       AND EXISTS (
           SELECT 1
           FROM erp.recipient_contract contract
           WHERE contract.id = NEW.recipient_contract_id
             AND contract.invalidated_at_utc IS NULL
             AND NOT (
                 NEW.assignment_period <@ COALESCE(
                     (
                         SELECT range_agg(qualification.qualification_period)
                         FROM erp.staff_service_qualification_period qualification
                         WHERE qualification.staff_id = NEW.staff_id
                           AND qualification.employment_id = NEW.employment_id
                           AND qualification.service_type_id = contract.service_type_id
                           AND qualification.invalidated_at_utc IS NULL
                     ), '{}'::datemultirange
                 )
             )
       )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_STAFF_INELIGIBLE';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_recipient_contract_assignment_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM erp.care_assignment assignment
        WHERE assignment.recipient_contract_id = NEW.id
          AND assignment.invalidated_at_utc IS NULL
          AND (
              NEW.invalidated_at_utc IS NOT NULL
              OR NOT (assignment.assignment_period <@ NEW.contract_period)
              OR (
                  assignment.assignment_kind = 'GENERAL'
                  AND NOT (
                      assignment.assignment_period <@ COALESCE(
                          (
                              SELECT range_agg(
                                  qualification.qualification_period
                              )
                              FROM erp.staff_service_qualification_period
                                  qualification
                              WHERE qualification.staff_id = assignment.staff_id
                                AND qualification.employment_id =
                                    assignment.employment_id
                                AND qualification.service_type_id =
                                    NEW.service_type_id
                                AND qualification.invalidated_at_utc IS NULL
                          ), '{}'::datemultirange
                      )
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_staff_employment_child_periods_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM erp.staff_position_period child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    ) OR EXISTS (
        SELECT 1 FROM erp.staff_operational_role_period child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    ) OR EXISTS (
        SELECT 1 FROM erp.staff_service_qualification_period child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    ) OR EXISTS (
        SELECT 1 FROM erp.care_assignment child
        WHERE child.employment_id = NEW.id AND child.staff_id = NEW.staff_id
          AND child.invalidated_at_utc IS NULL
          AND (NEW.invalidated_at_utc IS NOT NULL
               OR child.start_date < NEW.start_date
               OR (NEW.end_date IS NOT NULL
                   AND (child.end_date IS NULL OR child.end_date > NEW.end_date)))
    )
    THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'STAFF_PERIOD_OUTSIDE_EMPLOYMENT';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_staff_position_care_assignment_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM erp.care_assignment assignment
        WHERE assignment.staff_id = OLD.staff_id
          AND assignment.employment_id = OLD.employment_id
          AND assignment.assignment_kind = 'GENERAL'
          AND assignment.invalidated_at_utc IS NULL
          AND NOT (
              assignment.assignment_period <@ COALESCE(
                  (
                      SELECT range_agg(position.position_period)
                      FROM erp.staff_position_period position
                      WHERE position.staff_id = assignment.staff_id
                        AND position.employment_id = assignment.employment_id
                        AND position.position_code = 'CARE_WORKER'
                        AND position.invalidated_at_utc IS NULL
                  ), '{}'::datemultirange
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION erp.fn_staff_service_qualification_assignment_reverse_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM erp.care_assignment assignment
        JOIN erp.recipient_contract contract
          ON contract.id = assignment.recipient_contract_id
        WHERE assignment.staff_id = OLD.staff_id
          AND assignment.employment_id = OLD.employment_id
          AND assignment.assignment_kind = 'GENERAL'
          AND assignment.invalidated_at_utc IS NULL
          AND contract.invalidated_at_utc IS NULL
          AND contract.service_type_id = OLD.service_type_id
          AND NOT (
              assignment.assignment_period <@ COALESCE(
                  (
                      SELECT range_agg(qualification.qualification_period)
                      FROM erp.staff_service_qualification_period qualification
                      WHERE qualification.staff_id = assignment.staff_id
                        AND qualification.employment_id = assignment.employment_id
                        AND qualification.service_type_id = contract.service_type_id
                        AND qualification.invalidated_at_utc IS NULL
                  ), '{}'::datemultirange
              )
          )
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN';
    END IF;
    RETURN NEW;
END
$$;
"""


def upgrade() -> None:
    # Fail closed if any current FAMILY row lacks a meaningful snapshot instead
    # of guessing a backfill for a period-fact ledger.
    family_trim_literal = family_relationship_trim_sql_literal(e_string=True)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM erp.care_assignment
                WHERE assignment_kind = 'FAMILY'
                  AND (
                      family_relationship_text IS NULL
                      OR btrim(family_relationship_text, {family_trim_literal}) = ''
                  )
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED';
            END IF;
        END
        $$;
        """
    )
    op.create_check_constraint(
        op.f(_CONSTRAINT_NAME),
        "care_assignment",
        family_relationship_present_predicate_sql(e_string=True),
        schema="erp",
    )
    op.execute(_LOCK_FUNCTIONS_SQL)
    op.execute(_REPLACE_W1E_GUARD_FUNCTIONS_SQL)


def downgrade() -> None:
    op.execute(_RESTORE_0012_GUARD_FUNCTIONS_SQL)
    op.execute(
        """
        DROP FUNCTION IF EXISTS erp.fn_w1e_lock_assignment_path(bigint, bigint);
        DROP FUNCTION IF EXISTS erp.fn_w1e_lock_contract_assignment_edges(bigint);
        DROP FUNCTION IF EXISTS erp.fn_w1e_lock_employment_assignment_edges(bigint, bigint);
        DROP FUNCTION IF EXISTS erp.fn_w1e_lock_employment_path(bigint);
        DROP FUNCTION IF EXISTS erp.fn_w1e_lock_contract_path(bigint);
        DROP FUNCTION IF EXISTS erp.fn_w1e_lock_global();
        """
    )
    op.drop_constraint(
        op.f(_CONSTRAINT_NAME),
        "care_assignment",
        schema="erp",
        type_="check",
    )
