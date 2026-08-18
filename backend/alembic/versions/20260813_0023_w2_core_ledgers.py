"""Add the independently implementable W2 core ledgers.

Revision ID: 20260813_0023_w2_core_ledgers
Revises: 20260813_0022_w1_certification_contract_correction
Create Date: 2026-08-13
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0023_w2_core_ledgers"
down_revision: str | None = "20260813_0022_w1_certification_contract_correction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITY_TABLES = (
    "monthly_professional_assignment",
    "w2_schedule",
    "w2_schedule_staff",
    "w2_personal_todo",
    "w2_official_work_card",
)
_ALL_TABLES = (
    "monthly_professional_assignment",
    "w2_schedule_month_control",
    "w2_schedule",
    "w2_schedule_staff",
    "w2_personal_todo_list",
    "w2_personal_todo",
    "w2_official_work_card",
)


def _actor_columns() -> tuple[sa.Column[Any], ...]:
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
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
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


def _create_monthly_professional_assignment() -> None:
    op.create_table(
        "monthly_professional_assignment",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("service_month", sa.Date(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "assignment_period",
            postgresql.DATERANGE(),
            sa.Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
            nullable=False,
        ),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replacement_assignment_id", sa.BigInteger(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "service_month = date_trunc('month', service_month)::date",
            name="ck_monthly_professional_assignment_month_start",
        ),
        sa.CheckConstraint(
            "start_date <= end_date",
            name="ck_monthly_professional_assignment_date_order",
        ),
        sa.CheckConstraint(
            "start_date >= service_month AND end_date < (service_month + INTERVAL '1 month')::date",
            name="ck_monthly_professional_assignment_inside_month",
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name="ck_monthly_professional_assignment_row_version_positive",
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("service_month", "="),
            ("assignment_period", "&&"),
            where=sa.text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_monthly_professional_assignment_current_period",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_monthly_professional_assignment_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_monthly_professional_assignment_employment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_assignment_id"],
            ["erp.monthly_professional_assignment.id"],
            name="fk_monthly_professional_assignment_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        *_actor_constraints("monthly_professional_assignment"),
        sa.PrimaryKeyConstraint("id", name="pk_monthly_professional_assignment"),
        schema="erp",
    )
    op.create_index(
        "ix_monthly_professional_assignment_recipient_month",
        "monthly_professional_assignment",
        ["recipient_id", "service_month", "id"],
        schema="erp",
    )
    op.create_index(
        "ix_monthly_professional_assignment_staff_month",
        "monthly_professional_assignment",
        ["staff_id", "service_month", "id"],
        schema="erp",
    )


def _create_monthly_professional_assignment_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_monthly_professional_assignment_fact_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.invalidated_at_utc IS NOT NULL THEN
                RETURN NEW;
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM erp.staff_employment employment
                 WHERE employment.id = NEW.employment_id
                   AND employment.staff_id = NEW.staff_id
                   AND employment.invalidated_at_utc IS NULL
                   AND NEW.assignment_period <@ employment.employment_period
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'PROFESSIONAL_ASSIGNMENT_OUTSIDE_EMPLOYMENT';
            END IF;
            IF NOT (
                NEW.assignment_period <@ COALESCE(
                    (
                        SELECT range_agg(position.position_period)
                          FROM erp.staff_position_period position
                         WHERE position.staff_id = NEW.staff_id
                           AND position.employment_id = NEW.employment_id
                           AND position.position_code IN ('SOCIAL_WORKER', 'NURSE')
                           AND position.invalidated_at_utc IS NULL
                    ),
                    '{}'::datemultirange
                )
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'PROFESSIONAL_ASSIGNMENT_POSITION_REQUIRED';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_monthly_professional_assignment_fact_guard
        AFTER INSERT OR UPDATE ON erp.monthly_professional_assignment
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_monthly_professional_assignment_fact_guard();

        CREATE FUNCTION erp.fn_monthly_professional_assignment_employment_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM erp.monthly_professional_assignment assignment
                 WHERE assignment.staff_id = OLD.staff_id
                   AND assignment.employment_id = OLD.id
                   AND assignment.invalidated_at_utc IS NULL
                   AND (
                       NEW.staff_id IS DISTINCT FROM OLD.staff_id
                       OR NEW.invalidated_at_utc IS NOT NULL
                       OR NOT (assignment.assignment_period <@ NEW.employment_period)
                   )
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'PROFESSIONAL_ASSIGNMENT_EMPLOYMENT_ORPHAN_FORBIDDEN';
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_monthly_professional_assignment_employment_reverse_guard
        AFTER UPDATE ON erp.staff_employment
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION
            erp.fn_monthly_professional_assignment_employment_reverse_guard();

        CREATE FUNCTION erp.fn_monthly_professional_assignment_position_reverse_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM erp.monthly_professional_assignment assignment
                 WHERE assignment.staff_id = OLD.staff_id
                   AND assignment.employment_id = OLD.employment_id
                   AND assignment.invalidated_at_utc IS NULL
                   AND NOT (
                       assignment.assignment_period <@ COALESCE(
                           (
                               SELECT range_agg(position.position_period)
                                 FROM erp.staff_position_period position
                                WHERE position.staff_id = assignment.staff_id
                                  AND position.employment_id = assignment.employment_id
                                  AND position.position_code IN ('SOCIAL_WORKER', 'NURSE')
                                  AND position.invalidated_at_utc IS NULL
                           ),
                           '{}'::datemultirange
                       )
                   )
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'PROFESSIONAL_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_monthly_professional_assignment_position_reverse_guard
        AFTER UPDATE OR DELETE ON erp.staff_position_period
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION erp.fn_monthly_professional_assignment_position_reverse_guard();
        """
    )


def _create_schedule_ledgers() -> None:
    op.create_table(
        "w2_schedule_month_control",
        sa.Column("schedule_month", sa.Date(), nullable=False),
        sa.Column("finalized_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_account_id", sa.BigInteger(), nullable=True),
        *_actor_columns(),
        sa.CheckConstraint(
            "schedule_month = date_trunc('month', schedule_month)::date",
            name="ck_w2_schedule_month_control_month_start",
        ),
        sa.CheckConstraint(
            "(finalized_at_utc IS NULL) = (finalized_by_account_id IS NULL)",
            name="ck_w2_schedule_month_control_finalized_pair",
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name="ck_w2_schedule_month_control_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_month_control_finalized_by_account",
            ondelete="RESTRICT",
        ),
        *_actor_constraints("w2_schedule_month_control"),
        sa.PrimaryKeyConstraint("schedule_month", name="pk_w2_schedule_month_control"),
        schema="erp",
    )
    op.create_table(
        "w2_schedule",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("schedule_month", sa.Date(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("service_type_id", sa.BigInteger(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "schedule_period",
            postgresql.TSTZRANGE(),
            sa.Computed("tstzrange(starts_at_utc, ends_at_utc, '[)')", persisted=True),
            nullable=False,
        ),
        *_actor_columns(),
        sa.CheckConstraint(
            "starts_at_utc < ends_at_utc",
            name="ck_w2_schedule_time_order",
        ),
        sa.CheckConstraint(
            "starts_at_utc >= (schedule_month::timestamp AT TIME ZONE 'Asia/Seoul') "
            "AND ends_at_utc <= "
            "((schedule_month + INTERVAL '1 month') AT TIME ZONE 'Asia/Seoul')",
            name="ck_w2_schedule_inside_month",
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name="ck_w2_schedule_row_version_positive",
        ),
        postgresql.ExcludeConstraint(
            ("recipient_id", "="),
            ("schedule_period", "&&"),
            using="gist",
            name="ex_w2_schedule_recipient_overlap",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_month"],
            ["erp.w2_schedule_month_control.schedule_month"],
            name="fk_w2_schedule_month_control",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_w2_schedule_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_w2_schedule_service_type",
            ondelete="RESTRICT",
        ),
        *_actor_constraints("w2_schedule"),
        sa.PrimaryKeyConstraint("id", name="pk_w2_schedule"),
        sa.UniqueConstraint(
            "recipient_id",
            "service_type_id",
            "starts_at_utc",
            "ends_at_utc",
            name="uq_w2_schedule_exact",
        ),
        schema="erp",
    )
    op.create_index(
        "ix_w2_schedule_month_recipient",
        "w2_schedule",
        ["schedule_month", "recipient_id"],
        schema="erp",
    )
    op.create_index(
        "ix_w2_schedule_month_period",
        "w2_schedule",
        ["schedule_month", "starts_at_utc", "id"],
        schema="erp",
    )
    op.create_table(
        "w2_schedule_staff",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("schedule_id", sa.BigInteger(), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("employment_id", sa.BigInteger(), nullable=False),
        *_actor_columns(),
        sa.CheckConstraint(
            "row_version > 0",
            name="ck_w2_schedule_staff_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w2_schedule_staff_schedule",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_w2_schedule_staff_employment",
            ondelete="RESTRICT",
        ),
        *_actor_constraints("w2_schedule_staff"),
        sa.PrimaryKeyConstraint("id", name="pk_w2_schedule_staff"),
        sa.UniqueConstraint(
            "schedule_id",
            "staff_id",
            name="uq_w2_schedule_staff_distinct",
        ),
        schema="erp",
    )
    op.create_index(
        "ix_w2_schedule_staff_staff_schedule",
        "w2_schedule_staff",
        ["staff_id", "schedule_id", "id"],
        schema="erp",
    )


def _create_schedule_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION erp.fn_w2_schedule_write_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_month date;
            finalized_at timestamptz;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.schedule_month <> OLD.schedule_month THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'SCHEDULE_MONTH_IMMUTABLE';
            END IF;
            target_month := CASE WHEN TG_OP = 'DELETE'
                                 THEN OLD.schedule_month ELSE NEW.schedule_month END;
            SELECT control.finalized_at_utc
              INTO finalized_at
              FROM erp.w2_schedule_month_control control
             WHERE control.schedule_month = target_month
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23503',
                    MESSAGE = 'SCHEDULE_MONTH_CONTROL_NOT_FOUND';
            END IF;
            IF finalized_at IS NOT NULL THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'SCHEDULE_MONTH_FINALIZED';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END
        $$;

        CREATE TRIGGER bd_biu_w2_schedule_month_guard
        BEFORE INSERT OR UPDATE OR DELETE ON erp.w2_schedule
        FOR EACH ROW EXECUTE FUNCTION erp.fn_w2_schedule_write_guard();

        CREATE FUNCTION erp.fn_w2_schedule_staff_write_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_schedule_id bigint;
            finalized_at timestamptz;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.schedule_id <> OLD.schedule_id THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'SCHEDULE_STAFF_PARENT_IMMUTABLE';
            END IF;
            target_schedule_id := CASE WHEN TG_OP = 'DELETE'
                                       THEN OLD.schedule_id ELSE NEW.schedule_id END;
            SELECT control.finalized_at_utc
              INTO finalized_at
              FROM erp.w2_schedule schedule
              JOIN erp.w2_schedule_month_control control
                ON control.schedule_month = schedule.schedule_month
             WHERE schedule.id = target_schedule_id
             FOR UPDATE OF control;
            IF NOT FOUND THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION USING
                    ERRCODE = '23503',
                    MESSAGE = 'SCHEDULE_NOT_FOUND';
            END IF;
            IF finalized_at IS NOT NULL THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'SCHEDULE_MONTH_FINALIZED';
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END
        $$;

        CREATE TRIGGER bd_biu_w2_schedule_staff_month_guard
        BEFORE INSERT OR UPDATE OR DELETE ON erp.w2_schedule_staff
        FOR EACH ROW EXECUTE FUNCTION erp.fn_w2_schedule_staff_write_guard();

        CREATE FUNCTION erp.fn_w2_schedule_staff_contract_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_schedule_id bigint;
            expected_count integer;
            actual_count integer;
        BEGIN
            IF TG_RELID = 'erp.w2_schedule'::regclass THEN
                IF TG_OP = 'DELETE' THEN
                    target_schedule_id := OLD.id;
                ELSE
                    target_schedule_id := NEW.id;
                END IF;
            ELSE
                IF TG_OP = 'DELETE' THEN
                    target_schedule_id := OLD.schedule_id;
                ELSE
                    target_schedule_id := NEW.schedule_id;
                END IF;
            END IF;
            SELECT CASE WHEN service_type.code = 'HOME_BATH' THEN 2 ELSE 1 END
              INTO expected_count
              FROM erp.w2_schedule schedule
              JOIN erp.service_type service_type
                ON service_type.id = schedule.service_type_id
             WHERE schedule.id = target_schedule_id;
            IF NOT FOUND THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            SELECT count(*)
              INTO actual_count
              FROM erp.w2_schedule_staff assigned
             WHERE assigned.schedule_id = target_schedule_id;
            IF actual_count <> expected_count THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'SCHEDULE_STAFF_COUNT_INVALID';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM erp.w2_schedule_staff assigned
                  JOIN erp.w2_schedule schedule
                    ON schedule.id = assigned.schedule_id
                  JOIN erp.w2_schedule_staff other_assigned
                    ON other_assigned.staff_id = assigned.staff_id
                   AND other_assigned.schedule_id <> assigned.schedule_id
                  JOIN erp.w2_schedule other_schedule
                    ON other_schedule.id = other_assigned.schedule_id
                 WHERE assigned.schedule_id = target_schedule_id
                   AND schedule.schedule_period && other_schedule.schedule_period
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23P01',
                    MESSAGE = 'SCHEDULE_STAFF_OVERLAP';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE CONSTRAINT TRIGGER ct_w2_schedule_staff_contract_from_schedule
        AFTER INSERT OR UPDATE ON erp.w2_schedule
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION erp.fn_w2_schedule_staff_contract_guard();

        CREATE CONSTRAINT TRIGGER ct_w2_schedule_staff_contract_from_staff
        AFTER INSERT OR UPDATE OR DELETE ON erp.w2_schedule_staff
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION erp.fn_w2_schedule_staff_contract_guard();

        CREATE FUNCTION erp.fn_w2_schedule_month_finalize_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.finalized_at_utc IS NOT NULL
               AND NEW.finalized_at_utc IS DISTINCT FROM OLD.finalized_at_utc THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'SCHEDULE_MONTH_REOPEN_FORBIDDEN';
            END IF;
            IF OLD.finalized_at_utc IS NULL AND NEW.finalized_at_utc IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1
                      FROM erp.w2_schedule schedule
                      JOIN erp.w2_schedule_staff assigned
                        ON assigned.schedule_id = schedule.id
                     WHERE schedule.schedule_month = NEW.schedule_month
                       AND NOT EXISTS (
                           SELECT 1
                             FROM erp.staff_employment employment
                            WHERE employment.id = assigned.employment_id
                              AND employment.staff_id = assigned.staff_id
                              AND employment.invalidated_at_utc IS NULL
                              AND daterange(
                                  (schedule.starts_at_utc AT TIME ZONE 'Asia/Seoul')::date,
                                  ((schedule.ends_at_utc - INTERVAL '1 microsecond')
                                      AT TIME ZONE 'Asia/Seoul')::date + 1,
                                  '[)'
                              ) <@ employment.employment_period
                       )
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'SCHEDULE_OUTSIDE_EMPLOYMENT';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM erp.w2_schedule schedule
                      JOIN erp.w2_schedule_staff assigned
                        ON assigned.schedule_id = schedule.id
                     WHERE schedule.schedule_month = NEW.schedule_month
                       AND NOT (
                           daterange(
                               (schedule.starts_at_utc AT TIME ZONE 'Asia/Seoul')::date,
                               ((schedule.ends_at_utc - INTERVAL '1 microsecond')
                                   AT TIME ZONE 'Asia/Seoul')::date + 1,
                               '[)'
                           ) <@ COALESCE(
                               (
                                   SELECT range_agg(position.position_period)
                                     FROM erp.staff_position_period position
                                    WHERE position.staff_id = assigned.staff_id
                                      AND position.employment_id = assigned.employment_id
                                      AND position.position_code = 'CARE_WORKER'
                                      AND position.invalidated_at_utc IS NULL
                               ),
                               '{}'::datemultirange
                           )
                       )
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'SCHEDULE_CARE_WORKER_POSITION_REQUIRED';
                END IF;
                IF EXISTS (
                    SELECT 1
                      FROM erp.w2_schedule schedule
                      JOIN erp.w2_schedule_staff assigned
                        ON assigned.schedule_id = schedule.id
                     WHERE schedule.schedule_month = NEW.schedule_month
                       AND NOT (
                           daterange(
                               (schedule.starts_at_utc AT TIME ZONE 'Asia/Seoul')::date,
                               ((schedule.ends_at_utc - INTERVAL '1 microsecond')
                                   AT TIME ZONE 'Asia/Seoul')::date + 1,
                               '[)'
                           ) <@ COALESCE(
                               (
                                   SELECT range_agg(qualification.qualification_period)
                                     FROM erp.staff_service_qualification_period qualification
                                    WHERE qualification.staff_id = assigned.staff_id
                                      AND qualification.employment_id = assigned.employment_id
                                      AND qualification.service_type_id = schedule.service_type_id
                                      AND qualification.invalidated_at_utc IS NULL
                               ),
                               '{}'::datemultirange
                           )
                       )
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'SCHEDULE_OUTSIDE_QUALIFICATION';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;

        CREATE TRIGGER bu_w2_schedule_month_finalize_guard
        BEFORE UPDATE OF finalized_at_utc ON erp.w2_schedule_month_control
        FOR EACH ROW EXECUTE FUNCTION erp.fn_w2_schedule_month_finalize_guard();
        """
    )


def _create_personal_todos() -> None:
    op.create_table(
        "w2_personal_todo_list",
        sa.Column("owner_account_id", sa.BigInteger(), nullable=False),
        sa.Column("list_revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "list_revision > 0",
            name="ck_w2_personal_todo_list_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_personal_todo_list_owner_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("owner_account_id", name="pk_w2_personal_todo_list"),
        schema="erp",
    )
    op.create_table(
        "w2_personal_todo",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("owner_account_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("btrim(title) <> ''", name="ck_w2_personal_todo_title_nonblank"),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_w2_personal_todo_sort_order_nonnegative",
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name="ck_w2_personal_todo_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["erp.w2_personal_todo_list.owner_account_id"],
            name="fk_w2_personal_todo_owner_list",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w2_personal_todo"),
        sa.UniqueConstraint(
            "owner_account_id",
            "sort_order",
            name="uq_w2_personal_todo_owner_sort_order",
            deferrable=True,
            initially="DEFERRED",
        ),
        schema="erp",
    )
    op.create_index(
        "ix_w2_personal_todo_owner_id",
        "w2_personal_todo",
        ["owner_account_id", "id"],
        schema="erp",
    )


def _create_official_cards() -> None:
    op.create_table(
        "w2_official_work_card",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("work_title", sa.Text(), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=True),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("occurrence_key", sa.Text(), nullable=False),
        sa.Column("renewal_key", sa.Text(), nullable=True),
        sa.Column("assignee_staff_id", sa.BigInteger(), nullable=False),
        sa.Column("closed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_account_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('RECOGNITION_EXPIRY','CONTRACT_EXPIRY','PLAN_NOTICE',"
            "'STAFF_REPLACEMENT_CONSULTATION','NEW_STAFF_WORK')",
            name="ck_w2_official_work_card_kind",
        ),
        sa.CheckConstraint(
            "btrim(work_title) <> '' AND btrim(target_name) <> '' "
            "AND btrim(detail) <> '' AND btrim(occurrence_key) <> ''",
            name="ck_w2_official_work_card_nonblank",
        ),
        sa.CheckConstraint(
            "renewal_key IS NULL OR btrim(renewal_key) <> ''",
            name="ck_w2_official_work_card_renewal_key_nonblank",
        ),
        sa.CheckConstraint(
            "closed_at_utc IS NOT NULL OR closed_by_account_id IS NULL",
            name="ck_w2_official_work_card_closed_pair",
        ),
        sa.CheckConstraint(
            "row_version > 0",
            name="ck_w2_official_work_card_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_w2_official_work_card_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_staff_id"],
            ["erp.staff.id"],
            name="fk_w2_official_work_card_assignee_staff",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_official_work_card_closed_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_official_work_card_created_by_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_official_work_card_updated_by_account",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_w2_official_work_card"),
        sa.UniqueConstraint(
            "occurrence_key",
            name="uq_w2_official_work_card_occurrence_key",
        ),
        schema="erp",
    )
    op.create_index(
        "uq_w2_official_work_card_open_renewal",
        "w2_official_work_card",
        ["renewal_key"],
        unique=True,
        schema="erp",
        postgresql_where=sa.text("closed_at_utc IS NULL AND renewal_key IS NOT NULL"),
    )
    op.create_index(
        "ix_w2_official_work_card_assignee_open_due",
        "w2_official_work_card",
        ["assignee_staff_id", "due_date", "id"],
        schema="erp",
        postgresql_where=sa.text("closed_at_utc IS NULL"),
    )


def _grant_runtime_roles() -> None:
    table_list = ",\n                    ".join(f"erp.{name}" for name in _ALL_TABLES)
    sequence_list = ",\n                    ".join(
        f"erp.{name}_id_seq" for name in _IDENTITY_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                GRANT USAGE ON SCHEMA erp TO erp_app;
                GRANT SELECT, INSERT, UPDATE ON TABLE
                    {table_list}
                TO erp_app;
                GRANT DELETE ON TABLE
                    erp.w2_schedule,
                    erp.w2_schedule_staff,
                    erp.w2_personal_todo
                TO erp_app;
                REVOKE DELETE, TRUNCATE ON TABLE
                    erp.monthly_professional_assignment,
                    erp.w2_schedule_month_control,
                    erp.w2_personal_todo_list,
                    erp.w2_official_work_card
                FROM erp_app;
                GRANT USAGE, SELECT ON SEQUENCE
                    {sequence_list}
                TO erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                GRANT USAGE ON SCHEMA erp TO erp_backup;
                GRANT SELECT ON TABLE
                    {table_list}
                TO erp_backup;
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_backup;
                GRANT SELECT ON SEQUENCE
                    {sequence_list}
                TO erp_backup;
                REVOKE USAGE ON SEQUENCE
                    {sequence_list}
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_monthly_professional_assignment()
    _create_monthly_professional_assignment_guards()
    _create_schedule_ledgers()
    _create_schedule_guards()
    _create_personal_todos()
    _create_official_cards()
    _grant_runtime_roles()


def downgrade() -> None:
    table_list = ",\n                    ".join(f"erp.{name}" for name in _ALL_TABLES)
    sequence_list = ",\n                    ".join(
        f"erp.{name}_id_seq" for name in _IDENTITY_TABLES
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_app') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_app;
                REVOKE USAGE, SELECT ON SEQUENCE
                    {sequence_list}
                FROM erp_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_backup') THEN
                REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
                    {table_list}
                FROM erp_backup;
                REVOKE USAGE, SELECT ON SEQUENCE
                    {sequence_list}
                FROM erp_backup;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS bu_w2_schedule_month_finalize_guard
            ON erp.w2_schedule_month_control;
        DROP TRIGGER IF EXISTS ct_w2_schedule_staff_contract_from_staff
            ON erp.w2_schedule_staff;
        DROP TRIGGER IF EXISTS ct_w2_schedule_staff_contract_from_schedule
            ON erp.w2_schedule;
        DROP TRIGGER IF EXISTS bd_biu_w2_schedule_staff_month_guard
            ON erp.w2_schedule_staff;
        DROP TRIGGER IF EXISTS bd_biu_w2_schedule_month_guard ON erp.w2_schedule;
        DROP FUNCTION IF EXISTS erp.fn_w2_schedule_month_finalize_guard();
        DROP FUNCTION IF EXISTS erp.fn_w2_schedule_staff_contract_guard();
        DROP FUNCTION IF EXISTS erp.fn_w2_schedule_staff_write_guard();
        DROP FUNCTION IF EXISTS erp.fn_w2_schedule_write_guard();

        DROP TRIGGER IF EXISTS
            ct_monthly_professional_assignment_position_reverse_guard
            ON erp.staff_position_period;
        DROP TRIGGER IF EXISTS
            ct_monthly_professional_assignment_employment_reverse_guard
            ON erp.staff_employment;
        DROP TRIGGER IF EXISTS ct_monthly_professional_assignment_fact_guard
            ON erp.monthly_professional_assignment;
        DROP FUNCTION IF EXISTS
            erp.fn_monthly_professional_assignment_position_reverse_guard();
        DROP FUNCTION IF EXISTS
            erp.fn_monthly_professional_assignment_employment_reverse_guard();
        DROP FUNCTION IF EXISTS erp.fn_monthly_professional_assignment_fact_guard();
        """
    )
    op.drop_table("w2_official_work_card", schema="erp")
    op.drop_table("w2_personal_todo", schema="erp")
    op.drop_table("w2_personal_todo_list", schema="erp")
    op.drop_table("w2_schedule_staff", schema="erp")
    op.drop_table("w2_schedule", schema="erp")
    op.drop_table("w2_schedule_month_control", schema="erp")
    op.drop_table("monthly_professional_assignment", schema="erp")
