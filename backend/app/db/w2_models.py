"""SQLAlchemy mappings for the independent W2 core ledgers.

This module is intentionally separate from ``app.db.models``.  Integration must
import it once at application/Alembic startup so the shared ``Base.metadata``
contains these tables.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, TSTZRANGE, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MonthlyProfessionalAssignment(Base):
    __tablename__ = "monthly_professional_assignment"
    __table_args__ = (
        CheckConstraint(
            "service_month = date_trunc('month', service_month)::date",
            name="monthly_professional_assignment_month_start",
        ),
        CheckConstraint(
            "start_date <= end_date",
            name="monthly_professional_assignment_date_order",
        ),
        CheckConstraint(
            "start_date >= service_month AND end_date < (service_month + INTERVAL '1 month')::date",
            name="monthly_professional_assignment_inside_month",
        ),
        CheckConstraint(
            "row_version > 0",
            name="monthly_professional_assignment_row_version_positive",
        ),
        ExcludeConstraint(
            ("recipient_id", "="),
            ("service_month", "="),
            ("assignment_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_monthly_professional_assignment_current_period",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_monthly_professional_assignment_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_monthly_professional_assignment_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_assignment_id"],
            ["erp.monthly_professional_assignment.id"],
            name="fk_monthly_professional_assignment_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_monthly_professional_assignment_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_monthly_professional_assignment_updated_by_account",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_monthly_professional_assignment_recipient_month",
            "recipient_id",
            "service_month",
            "id",
        ),
        Index(
            "ix_monthly_professional_assignment_staff_month",
            "staff_id",
            "service_month",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    service_month: Mapped[date] = mapped_column(Date)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    employment_id: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    assignment_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_assignment_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class W2ScheduleMonthControl(Base):
    __tablename__ = "w2_schedule_month_control"
    __table_args__ = (
        CheckConstraint(
            "schedule_month = date_trunc('month', schedule_month)::date",
            name="w2_schedule_month_control_month_start",
        ),
        CheckConstraint(
            "(finalized_at_utc IS NULL) = (finalized_by_account_id IS NULL)",
            name="w2_schedule_month_control_finalized_pair",
        ),
        CheckConstraint(
            "row_version > 0",
            name="w2_schedule_month_control_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_month_control_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_month_control_updated_by_account",
            ondelete="RESTRICT",
        ),
    )

    schedule_month: Mapped[date] = mapped_column(Date, primary_key=True)
    finalized_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by_account_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_w2_schedule_month_control_finalized_by_account",
            ondelete="RESTRICT",
        )
    )
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class W2Schedule(Base):
    __tablename__ = "w2_schedule"
    __table_args__ = (
        CheckConstraint("starts_at_utc < ends_at_utc", name="w2_schedule_time_order"),
        CheckConstraint(
            "starts_at_utc >= (schedule_month::timestamp AT TIME ZONE 'Asia/Seoul') "
            "AND ends_at_utc <= "
            "((schedule_month + INTERVAL '1 month') AT TIME ZONE 'Asia/Seoul')",
            name="w2_schedule_inside_month",
        ),
        CheckConstraint("row_version > 0", name="w2_schedule_row_version_positive"),
        ExcludeConstraint(
            ("recipient_id", "="),
            ("schedule_period", "&&"),
            using="gist",
            name="ex_w2_schedule_recipient_overlap",
        ),
        ForeignKeyConstraint(
            ["schedule_month"],
            ["erp.w2_schedule_month_control.schedule_month"],
            name="fk_w2_schedule_month_control",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_w2_schedule_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_w2_schedule_service_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_updated_by_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "recipient_id",
            "service_type_id",
            "starts_at_utc",
            "ends_at_utc",
            name="uq_w2_schedule_exact",
        ),
        Index("ix_w2_schedule_month_recipient", "schedule_month", "recipient_id"),
        Index(
            "ix_w2_schedule_month_period",
            "schedule_month",
            "starts_at_utc",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    schedule_month: Mapped[date] = mapped_column(Date)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    service_type_id: Mapped[int] = mapped_column(BigInteger)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    schedule_period: Mapped[Any] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(starts_at_utc, ends_at_utc, '[)')", persisted=True),
    )
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class W2ScheduleStaff(Base):
    __tablename__ = "w2_schedule_staff"
    __table_args__ = (
        CheckConstraint(
            "row_version > 0",
            name="w2_schedule_staff_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["schedule_id"],
            ["erp.w2_schedule.id"],
            name="fk_w2_schedule_staff_schedule",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_w2_schedule_staff_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_staff_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_schedule_staff_updated_by_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "schedule_id",
            "staff_id",
            name="uq_w2_schedule_staff_distinct",
        ),
        Index(
            "ix_w2_schedule_staff_staff_schedule",
            "staff_id",
            "schedule_id",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    schedule_id: Mapped[int] = mapped_column(BigInteger)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    employment_id: Mapped[int] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class W2PersonalTodoList(Base):
    __tablename__ = "w2_personal_todo_list"
    __table_args__ = (
        CheckConstraint(
            "list_revision > 0",
            name="w2_personal_todo_list_revision_positive",
        ),
    )

    owner_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_w2_personal_todo_list_owner_account",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    list_revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class W2PersonalTodo(Base):
    __tablename__ = "w2_personal_todo"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''", name="w2_personal_todo_title_nonblank"),
        CheckConstraint(
            "sort_order >= 0",
            name="w2_personal_todo_sort_order_nonnegative",
        ),
        CheckConstraint(
            "row_version > 0",
            name="w2_personal_todo_row_version_positive",
        ),
        UniqueConstraint(
            "owner_account_id",
            "sort_order",
            name="uq_w2_personal_todo_owner_sort_order",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_w2_personal_todo_owner_id", "owner_account_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    owner_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.w2_personal_todo_list.owner_account_id",
            name="fk_w2_personal_todo_owner_list",
            ondelete="CASCADE",
        )
    )
    title: Mapped[str] = mapped_column(Text)
    completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class W2OfficialWorkCard(Base):
    __tablename__ = "w2_official_work_card"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('RECOGNITION_EXPIRY','CONTRACT_EXPIRY','PLAN_NOTICE',"
            "'STAFF_REPLACEMENT_CONSULTATION','NEW_STAFF_WORK')",
            name="w2_official_work_card_kind",
        ),
        CheckConstraint(
            "btrim(work_title) <> '' AND btrim(target_name) <> '' "
            "AND btrim(detail) <> '' AND btrim(occurrence_key) <> ''",
            name="w2_official_work_card_nonblank",
        ),
        CheckConstraint(
            "renewal_key IS NULL OR btrim(renewal_key) <> ''",
            name="w2_official_work_card_renewal_key_nonblank",
        ),
        CheckConstraint(
            "closed_at_utc IS NOT NULL OR closed_by_account_id IS NULL",
            name="w2_official_work_card_closed_pair",
        ),
        CheckConstraint(
            "row_version > 0",
            name="w2_official_work_card_row_version_positive",
        ),
        UniqueConstraint(
            "occurrence_key",
            name="uq_w2_official_work_card_occurrence_key",
        ),
        Index(
            "uq_w2_official_work_card_open_renewal",
            "renewal_key",
            unique=True,
            postgresql_where=text("closed_at_utc IS NULL AND renewal_key IS NOT NULL"),
        ),
        Index(
            "ix_w2_official_work_card_assignee_open_due",
            "assignee_staff_id",
            "due_date",
            "id",
            postgresql_where=text("closed_at_utc IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    work_title: Mapped[str] = mapped_column(Text)
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "erp.recipient.id",
            name="fk_w2_official_work_card_recipient",
            ondelete="RESTRICT",
        )
    )
    target_name: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    occurrence_key: Mapped[str] = mapped_column(Text)
    renewal_key: Mapped[str | None] = mapped_column(Text)
    assignee_staff_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.staff.id",
            name="fk_w2_official_work_card_assignee_staff",
            ondelete="RESTRICT",
        )
    )
    closed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_account_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_w2_official_work_card_closed_by_account",
            ondelete="RESTRICT",
        )
    )
    created_by_account_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_w2_official_work_card_created_by_account",
            ondelete="RESTRICT",
        )
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_w2_official_work_card_updated_by_account",
            ondelete="RESTRICT",
        )
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class W2ServicePlanNotice(Base):
    __tablename__ = "w2_service_plan_notice"
    __table_args__ = (
        CheckConstraint(
            "applied_start_date <= applied_end_date",
            name="w2_service_plan_notice_date_order",
        ),
        CheckConstraint(
            "row_version > 0",
            name="w2_service_plan_notice_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "recipient_contract_id"],
            ["erp.recipient_contract.recipient_id", "erp.recipient_contract.id"],
            name="fk_w2_service_plan_notice_contract_same_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "replacement_service_plan_notice_id"],
            [
                "erp.w2_service_plan_notice.recipient_id",
                "erp.w2_service_plan_notice.id",
            ],
            name="fk_w2_service_plan_notice_replacement_same_recipient",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_service_plan_notice_created_by",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_w2_service_plan_notice_updated_by",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "recipient_id",
            "id",
            name="uq_w2_service_plan_notice_recipient_id_id",
        ),
        Index(
            "ix_w2_service_plan_notice_contract_notification",
            "recipient_contract_id",
            "notification_date",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Recipient ownership is written only by W2 service code after it validates
    # the contract/path parameter; no client request schema exposes this field.
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    recipient_contract_id: Mapped[int] = mapped_column(BigInteger)
    notification_date: Mapped[date] = mapped_column(Date)
    applied_start_date: Mapped[date] = mapped_column(Date)
    applied_end_date: Mapped[date] = mapped_column(Date)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_service_plan_notice_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
