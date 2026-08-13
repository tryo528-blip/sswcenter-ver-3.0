from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

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
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DATERANGE, INET, JSONB, ExcludeConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import TextClause, conv

from app.db.base import Base


class _TrainingPartialPredicate(TextClause):
    def __repr__(self) -> str:
        return str(self)


def _training_partial_unique_index(name: str, *columns: str) -> Index:
    index = Index(
        name,
        *columns,
        unique=True,
        postgresql_where=_TrainingPartialPredicate("invalidated_at_utc IS NULL"),
    )
    index.dialect_options = {"postgresql": dict(index.dialect_options["postgresql"])}
    return index


class Center(Base):
    __tablename__ = "center"
    __table_args__ = (
        Index(
            "uq_center_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    center_code: Mapped[str] = mapped_column(Text, unique=True)
    center_name: Mapped[str] = mapped_column(Text)
    business_no: Mapped[str | None] = mapped_column(Text)
    representative_name: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class BusinessNumberCounter(Base):
    __tablename__ = "business_number_counter"
    __table_args__ = (CheckConstraint("last_sequence >= 0", name="last_sequence_nonnegative"),)

    number_type: Mapped[str] = mapped_column(Text, primary_key=True)
    number_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Staff(Base):
    __tablename__ = "staff"
    __table_args__ = (CheckConstraint("sex_code IN ('MALE','FEMALE','TEST')", name="sex_code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    birth_date: Mapped[date] = mapped_column(Date)
    sex_code: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    phone_normalized: Mapped[str | None] = mapped_column(Text, index=True)
    address: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffSensitiveIdentity(Base):
    __tablename__ = "staff_sensitive_identity"
    __table_args__ = (
        CheckConstraint(
            "octet_length(resident_number_ciphertext) > 0",
            name="ciphertext_nonempty",
        ),
        CheckConstraint(
            "octet_length(resident_number_nonce) = 12",
            name="nonce_length",
        ),
        CheckConstraint(
            "resident_number_key_version > 0",
            name="key_version_positive",
        ),
        CheckConstraint(
            "octet_length(resident_number_lookup_hmac) = 32",
            name="lookup_hmac_length",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        UniqueConstraint(
            "resident_number_lookup_hmac",
            name="uq_staff_sensitive_identity_lookup_hmac",
        ),
    )

    staff_id: Mapped[int] = mapped_column(
        ForeignKey("erp.staff.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    resident_number_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    resident_number_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    resident_number_key_version: Mapped[int] = mapped_column(Integer)
    resident_number_lookup_hmac: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint("role_code IN ('ADMIN','USER')", name="role_code"),
        CheckConstraint("failed_count >= 0", name="failed_count_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("erp.staff.id", ondelete="RESTRICT"), unique=True
    )
    account_code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    role_code: Mapped[str] = mapped_column(Text)
    pin_hash: Mapped[str] = mapped_column(Text)
    pin_lookup_hmac: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    pin_key_version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    login_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    failed_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    locked_until_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_login_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class PermissionDefinition(Base):
    __tablename__ = "permission_definition"

    permission_code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class AccountPermission(Base):
    __tablename__ = "account_permission"
    __table_args__ = (
        Index(
            "uq_account_permission_active",
            "account_id",
            "permission_code",
            unique=True,
            postgresql_where=text("revoked_at_utc IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("erp.user_account.id", ondelete="RESTRICT"))
    permission_code: Mapped[str] = mapped_column(
        ForeignKey("erp.permission_definition.permission_code", ondelete="RESTRICT")
    )
    granted_by_account_id: Mapped[int] = mapped_column(
        ForeignKey("erp.user_account.id", ondelete="RESTRICT")
    )
    granted_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("erp.user_account.id", ondelete="RESTRICT"))
    session_token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    account_session_version: Mapped[int] = mapped_column(Integer)
    issued_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    client_fingerprint_hash: Mapped[bytes | None] = mapped_column(LargeBinary)


class AuthEvent(Base):
    __tablename__ = "auth_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.user_account.id", ondelete="RESTRICT")
    )
    client_device_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    event_type: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean)
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    client_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)


class AuthRateLimitBucket(Base):
    __tablename__ = "auth_rate_limit_bucket"
    __table_args__ = (
        CheckConstraint(
            "bucket_type IN ('DEVICE_UNKNOWN','IP_UNKNOWN','SERVER_UNKNOWN')",
            name="bucket_type",
        ),
        CheckConstraint("failure_count >= 0", name="failure_count_nonnegative"),
        UniqueConstraint("bucket_type", "bucket_key_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    bucket_type: Mapped[str] = mapped_column(Text)
    bucket_key_hash: Mapped[bytes] = mapped_column(LargeBinary)
    window_started_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    blocked_until_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StaffEmployment(Base):
    __tablename__ = "staff_employment"
    __table_args__ = (
        UniqueConstraint("staff_id", "employment_no"),
        UniqueConstraint("staff_id", "id"),
        UniqueConstraint("staff_no_year", "staff_no_sequence"),
        CheckConstraint("end_date IS NULL OR start_date <= end_date", name="date_order"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        ExcludeConstraint(
            ("staff_id", "="),
            ("employment_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_employment_period",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("erp.staff.id", ondelete="RESTRICT"))
    employment_no: Mapped[int] = mapped_column(Integer)
    staff_no: Mapped[str] = mapped_column(Text, unique=True)
    staff_no_year: Mapped[int] = mapped_column(Integer)
    staff_no_sequence: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    employment_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    end_reason_code: Mapped[str | None] = mapped_column(Text)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_employment_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.staff_employment.id", ondelete="RESTRICT")
    )
    created_by_account_id: Mapped[int] = mapped_column(
        ForeignKey("erp.user_account.id", ondelete="RESTRICT")
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_staff_employment_updated_by_account",
            ondelete="RESTRICT",
        )
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffPositionPeriod(Base):
    __tablename__ = "staff_position_period"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "position_code IN ('CARE_WORKER','SOCIAL_WORKER','MANAGER','NURSE','OTHER')",
            name="position_code",
        ),
        CheckConstraint("end_date IS NULL OR start_date <= end_date", name="date_order"),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        ExcludeConstraint(
            ("staff_id", "="),
            ("position_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_position_period",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("erp.staff.id", ondelete="RESTRICT"))
    employment_id: Mapped[int] = mapped_column(BigInteger)
    position_code: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    position_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.staff_position_period.id", ondelete="RESTRICT")
    )
    created_by_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_staff_position_period_created_by_account",
            ondelete="RESTRICT",
        )
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_staff_position_period_updated_by_account",
            ondelete="RESTRICT",
        )
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffOperationalRolePeriod(Base):
    __tablename__ = "staff_operational_role_period"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("end_date IS NULL OR start_date <= end_date", name="date_order"),
        CheckConstraint(
            "role_code ~ '^[A-Z][A-Z0-9_]{0,49}$'",
            name="role_code_format",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        ExcludeConstraint(
            ("staff_id", "="),
            ("role_code", "="),
            ("role_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_operational_role_period",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("erp.staff.id", ondelete="RESTRICT"))
    employment_id: Mapped[int] = mapped_column(BigInteger)
    role_code: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    role_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.staff_operational_role_period.id", ondelete="RESTRICT")
    )
    created_by_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_staff_role_period_created_by_account",
            ondelete="RESTRICT",
        )
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "erp.user_account.id",
            name="fk_staff_role_period_updated_by_account",
            ondelete="RESTRICT",
        )
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class TrainingCourse(Base):
    __tablename__ = "training_course"
    __table_args__ = (
        CheckConstraint(
            "cycle_type IN ('ON_HIRE','HALF_YEAR','ANNUAL','BIENNIAL')",
            name="ck_training_course_cycle_type",
        ),
        CheckConstraint("sort_order > 0", name="ck_training_course_sort_order_positive"),
        UniqueConstraint("sort_order", name="uq_training_course_sort_order"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text)
    cycle_type: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer)


class StaffOnboardingTraining(Base):
    __tablename__ = "staff_onboarding_training"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_onboarding_training_employment",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "course_code = 'NEW_HIRE_ORIENTATION'",
            name="ck_staff_onboarding_training_course_code",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_staff_onboarding_training_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_onboarding_training_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_code"],
            ["erp.training_course.code"],
            name="fk_staff_onboarding_training_course_code",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_onboarding_training_id"],
            ["erp.staff_onboarding_training.id"],
            name="fk_staff_onboarding_training_replacement",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_onboarding_training_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_onboarding_training_updated_by_account",
            ondelete="RESTRICT",
        ),
        _training_partial_unique_index(
            "uq_staff_onboarding_training_active",
            "staff_id",
            "employment_id",
            "course_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    employment_id: Mapped[int] = mapped_column(BigInteger)
    course_code: Mapped[str] = mapped_column(Text)
    completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_onboarding_training_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffPeriodicTrainingStatus(Base):
    __tablename__ = "staff_periodic_training_status"
    __table_args__ = (
        CheckConstraint(
            "course_code <> 'NEW_HIRE_ORIENTATION'",
            name="ck_staff_periodic_training_course_code",
        ),
        CheckConstraint(
            "period_key ~ '^[0-9]{4}$' OR period_key ~ '^[0-9]{4}-H[12]$'",
            name="ck_staff_periodic_training_period_key",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_staff_periodic_training_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_periodic_training_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["course_code"],
            ["erp.training_course.code"],
            name="fk_staff_periodic_training_course_code",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_periodic_training_id"],
            ["erp.staff_periodic_training_status.id"],
            name="fk_staff_periodic_training_replacement",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_periodic_training_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_periodic_training_updated_by_account",
            ondelete="RESTRICT",
        ),
        _training_partial_unique_index(
            "uq_staff_periodic_training_active",
            "staff_id",
            "course_code",
            "period_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    course_code: Mapped[str] = mapped_column(Text)
    period_key: Mapped[str] = mapped_column(Text)
    completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_periodic_training_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class ServiceGroup(Base):
    __tablename__ = "service_group"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ServiceType(Base):
    __tablename__ = "service_type"
    __table_args__ = (
        ForeignKeyConstraint(
            ["service_group_id"],
            ["erp.service_group.id"],
            name="fk_service_type_service_group_id_service_group",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    service_group_id: Mapped[int] = mapped_column(BigInteger)
    code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class LicenseType(Base):
    __tablename__ = "license_type"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class StaffLicense(Base):
    __tablename__ = "staff_license"
    __table_args__ = (
        CheckConstraint("row_version > 0", name="row_version_positive"),
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_license_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["license_type_id"],
            ["erp.license_type.id"],
            name="fk_staff_license_license_type_id_license_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_license_id"],
            ["erp.staff_license.id"],
            name="fk_staff_license_replacement_license_id_staff_license",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_license_created_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_license_updated_by_account_id_user_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("staff_id", "id", name="uq_staff_license_staff_id_id"),
        Index(
            "uq_staff_license_type_number_active",
            "license_type_id",
            "license_number",
            unique=True,
            postgresql_where=text("invalidated_at_utc IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    license_type_id: Mapped[int] = mapped_column(BigInteger)
    license_number: Mapped[str] = mapped_column(Text)
    issued_date: Mapped[date] = mapped_column(Date)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_license_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffServiceQualificationPeriod(Base):
    __tablename__ = "staff_service_qualification_period"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_service_qualification_period_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_service_qualification_period_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_staff_service_qualification_service_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "source_license_id"],
            ["erp.staff_license.staff_id", "erp.staff_license.id"],
            name="fk_staff_service_qualification_period_source_license",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_qualification_id"],
            ["erp.staff_service_qualification_period.id"],
            name="fk_staff_service_qualification_period_replacement",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_service_qualification_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_service_qualification_updated_by_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="date_order",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        ExcludeConstraint(
            ("staff_id", "="),
            ("service_type_id", "="),
            ("qualification_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_staff_service_qualification_period",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    employment_id: Mapped[int] = mapped_column(BigInteger)
    service_type_id: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    qualification_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    source_license_id: Mapped[int | None] = mapped_column(BigInteger)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_qualification_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class SystemRun(Base):
    __tablename__ = "system_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','SUCCEEDED','WARNING','FAILED','CANCELED')",
            name="status",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        Index(
            "uq_system_run_idempotency",
            "run_type",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_type: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    queued_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    requested_by_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.user_account.id", ondelete="RESTRICT")
    )
    request_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    result_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)
    finished_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class SystemRunEvent(Base):
    __tablename__ = "system_run_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    system_run_id: Mapped[int] = mapped_column(ForeignKey("erp.system_run.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    attempt_no: Mapped[int | None] = mapped_column(Integer)
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('USER','SYSTEM','IMPORT','OCR','MIGRATION')",
            name="actor_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.user_account.id", ondelete="RESTRICT")
    )
    actor_kind: Mapped[str] = mapped_column(Text)
    action_code: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_pk: Mapped[int | None] = mapped_column(BigInteger)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_text: Mapped[str | None] = mapped_column(Text)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.system_run.id", ondelete="RESTRICT")
    )
    request_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_from: Mapped[str] = mapped_column(Text)


class AccessEvent(Base):
    __tablename__ = "access_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    account_id: Mapped[int] = mapped_column(ForeignKey("erp.user_account.id", ondelete="RESTRICT"))
    access_type: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_pk: Mapped[int | None] = mapped_column(BigInteger)
    # Wave 5 adds the document FKs when their target tables exist.
    document_record_id: Mapped[int | None] = mapped_column(BigInteger)
    generated_document_id: Mapped[int | None] = mapped_column(BigInteger)
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class InstallationState(Base):
    __tablename__ = "installation_state"
    __table_args__ = (CheckConstraint("singleton_key", name="singleton_key_true"),)

    singleton_key: Mapped[bool] = mapped_column(
        Boolean, primary_key=True, server_default=text("true")
    )
    bootstrap_completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    bootstrap_completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_admin_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("erp.user_account.id", ondelete="RESTRICT")
    )
    installed_app_version: Mapped[str | None] = mapped_column(String(100))


class StaffHealthCheck(Base):
    __tablename__ = "staff_health_check"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_health_check_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_staff_health_check_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_health_check_id"],
            ["erp.staff_health_check.id"],
            name="fk_staff_health_check_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_health_check_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_health_check_updated_by_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_staff_health_check_row_version_positive",
        ),
        UniqueConstraint("staff_id", "id", name="uq_staff_health_check_staff_id_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    employment_id: Mapped[int | None] = mapped_column(BigInteger)
    check_date: Mapped[date] = mapped_column(Date)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_health_check_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffQuarterlyConsultation(Base):
    __tablename__ = "staff_quarterly_consultation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_quarterly_consultation_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_quarterly_consultation_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_quarterly_consultation_updated_by_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "quarter_no IN (1, 2, 3, 4)",
            name="ck_staff_quarterly_consultation_quarter_no",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_staff_quarterly_consultation_row_version_positive",
        ),
        UniqueConstraint(
            "staff_id",
            "calendar_year",
            "quarter_no",
            name="uq_staff_quarterly_consultation_staff_year_quarter",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    calendar_year: Mapped[int] = mapped_column(Integer)
    quarter_no: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class StaffLegacyMapping(Base):
    __tablename__ = "staff_legacy_mapping"
    __table_args__ = (
        ForeignKeyConstraint(
            ["staff_id"],
            ["erp.staff.id"],
            name="fk_staff_legacy_mapping_staff_id_staff",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_staff_legacy_mapping_id"],
            ["erp.staff_legacy_mapping.id"],
            name="fk_staff_legacy_mapping_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_legacy_mapping_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_staff_legacy_mapping_updated_by_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "btrim(source_system_code) <> ''",
            name="ck_staff_legacy_mapping_source_system_code_nonblank",
        ),
        CheckConstraint(
            "btrim(legacy_staff_key) <> ''",
            name="ck_staff_legacy_mapping_legacy_staff_key_nonblank",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_staff_legacy_mapping_row_version_positive",
        ),
        Index(
            "uq_staff_legacy_mapping_active",
            "source_system_code",
            "legacy_staff_key",
            unique=True,
            postgresql_where=text("invalidated_at_utc IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_system_code: Mapped[str] = mapped_column(Text)
    legacy_staff_key: Mapped[str] = mapped_column(Text)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    source_row_fingerprint: Mapped[bytes | None] = mapped_column(LargeBinary)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_staff_legacy_mapping_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class Recipient(Base):
    __tablename__ = "recipient"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_recipient_name_nonblank"),
        CheckConstraint(
            "sex_code IN ('MALE','FEMALE','TEST')",
            name="ck_recipient_sex_code",
        ),
        CheckConstraint(
            "recipient_status IN ('ACTIVE','ENDED','WAITING')",
            name="recipient_status",
        ),
        CheckConstraint(
            "btrim(mobile_phone) <> ''",
            name=conv("ck_recipient_mobile_phone_required"),
        ),
        CheckConstraint("row_version > 0", name="ck_recipient_row_version_positive"),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_updated_by_account",
            ondelete="RESTRICT",
        ),
        # Same-recipient payer guardian: NULL = self; non-null must be this recipient's guardian.
        ForeignKeyConstraint(
            ["id", "payer_guardian_id"],
            ["erp.recipient_guardian.recipient_id", "erp.recipient_guardian.id"],
            name="fk_recipient_payer_guardian_same_recipient",
            ondelete="SET NULL (payer_guardian_id)",
        ),
        UniqueConstraint("recipient_no", name="uq_recipient_recipient_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex_code: Mapped[str | None] = mapped_column(Text)
    recipient_status: Mapped[str] = mapped_column(Text, server_default=text("'ACTIVE'"))
    recipient_no: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    mobile_phone: Mapped[str] = mapped_column(Text)
    # NULL = recipient self is payer; positive id = that guardian (same recipient via composite FK).
    payer_guardian_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientPlanNotification(Base):
    __tablename__ = "recipient_plan_notification"
    __table_args__ = (
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_plan_notification_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_plan_notification_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_plan_notification_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_plan_notification_updated_by_account",
            ondelete="RESTRICT",
        ),
        Index("ix_recipient_plan_notification_recipient_id", "recipient_id"),
        Index("ix_recipient_plan_notification_notified_date", "notified_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    notified_date: Mapped[date] = mapped_column(Date)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientGuardian(Base):
    __tablename__ = "recipient_guardian"
    __table_args__ = (
        CheckConstraint(
            "btrim(name) <> ''",
            name="ck_recipient_guardian_name_nonblank",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_guardian_row_version_positive",
        ),
        CheckConstraint(
            "slot_no IN (1, 2)",
            name="slot_no",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_guardian_recipient_id_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_guardian_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_guardian_updated_by_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "recipient_id",
            "id",
            name="uq_recipient_guardian_recipient_id_id",
        ),
        UniqueConstraint(
            "recipient_id",
            "slot_no",
            name="uq_recipient_guardian_recipient_slot",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    slot_no: Mapped[int] = mapped_column(SmallInteger)
    name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    relationship_text: Mapped[str | None] = mapped_column(Text)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientLegacyMapping(Base):
    __tablename__ = "recipient_legacy_mapping"
    __table_args__ = (
        CheckConstraint(
            "btrim(source_system_code) <> ''",
            name="ck_recipient_legacy_mapping_source_system_code_nonblank",
        ),
        CheckConstraint(
            "legacy_recipient_key IS NOT NULL OR legacy_attachment_key IS NOT NULL",
            name="ck_recipient_legacy_mapping_key_present",
        ),
        CheckConstraint(
            "legacy_recipient_key IS NULL OR btrim(legacy_recipient_key) <> ''",
            name="ck_recipient_legacy_mapping_recipient_key_nonblank",
        ),
        CheckConstraint(
            "legacy_attachment_key IS NULL OR btrim(legacy_attachment_key) <> ''",
            name="ck_recipient_legacy_mapping_attachment_key_nonblank",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_legacy_mapping_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_legacy_mapping_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_recipient_legacy_mapping_id"],
            ["erp.recipient_legacy_mapping.id"],
            name="fk_recipient_legacy_mapping_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_legacy_mapping_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_legacy_mapping_updated_by_account",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_recipient_legacy_mapping_active_recipient_key",
            "source_system_code",
            "legacy_recipient_key",
            unique=True,
            postgresql_where=text(
                "invalidated_at_utc IS NULL AND legacy_recipient_key IS NOT NULL"
            ),
        ),
        Index(
            "uq_recipient_legacy_mapping_active_attachment_key",
            "source_system_code",
            "legacy_attachment_key",
            unique=True,
            postgresql_where=text(
                "invalidated_at_utc IS NULL AND legacy_attachment_key IS NOT NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_system_code: Mapped[str] = mapped_column(Text)
    legacy_recipient_key: Mapped[str | None] = mapped_column(Text)
    legacy_attachment_key: Mapped[str | None] = mapped_column(Text)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    source_row_fingerprint: Mapped[bytes | None] = mapped_column(LargeBinary)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_recipient_legacy_mapping_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientCertificationIdentity(Base):
    __tablename__ = "recipient_certification_identity"
    __table_args__ = (
        CheckConstraint(
            "certification_number ~ '^L[0-9]{10}$'",
            name="ck_recipient_certification_identity_number",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_certification_identity_row_version_positive",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_certification_identity_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_certification_identity_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_certification_identity_updated_by_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "certification_number",
            name="uq_recipient_certification_identity_certification_number",
        ),
    )

    recipient_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    certification_number: Mapped[str] = mapped_column(Text)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientCertificationPeriod(Base):
    __tablename__ = "recipient_certification_period"
    __table_args__ = (
        CheckConstraint(
            "start_date <= end_date",
            name="ck_recipient_certification_period_date_order",
        ),
        CheckConstraint(
            "grade_code IN ('1','2','3','4','5')",
            name=conv("ck_recipient_certification_period_grade_code"),
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_certification_period_row_version_positive",
        ),
        ExcludeConstraint(
            ("recipient_id", "="),
            ("certification_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_certification_period",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient_certification_identity.recipient_id"],
            name="fk_recipient_certification_period_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_certification_period_id"],
            ["erp.recipient_certification_period.id"],
            name="fk_recipient_certification_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_certification_period_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_certification_period_updated_by_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "recipient_id",
            "id",
            name="uq_recipient_certification_period_recipient_id_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    grade_code: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    certification_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_certification_period_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientBenefitPeriod(Base):
    __tablename__ = "recipient_benefit_period"
    __table_args__ = (
        CheckConstraint(
            """
            benefit_code IN (
                'GENERAL',
                'BASIC_LIVELIHOOD',
                'REDUCTION_6',
                'REDUCTION_9',
                'MEDICAL_6',
                'MEDICAL_9'
            )
            """,
            name="ck_recipient_benefit_period_benefit_code",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_benefit_period_row_version_positive",
        ),
        Index(
            "uq_recipient_benefit_period_active_recipient",
            "recipient_id",
            unique=True,
            postgresql_where=text("invalidated_at_utc IS NULL"),
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_benefit_period_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_benefit_period_id"],
            ["erp.recipient_benefit_period.id"],
            name="fk_recipient_benefit_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_benefit_period_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_benefit_period_updated_by_account",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    benefit_code: Mapped[str] = mapped_column(Text)
    start_text: Mapped[str] = mapped_column(Text, server_default=text("''"))
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_benefit_period_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientLocalApprovalAmountPeriod(Base):
    __tablename__ = "recipient_local_approval_amount_period"
    __table_args__ = (
        CheckConstraint(
            "amount_krw >= 0",
            name="ck_recipient_local_approval_amount_period_amount",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_recipient_local_approval_amount_period_date_order",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_local_approval_amount_period_row_version_positive",
        ),
        ExcludeConstraint(
            ("recipient_id", "="),
            ("approval_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_local_approval_amount_period",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_local_approval_amount_period_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_local_approval_amount_period_id"],
            ["erp.recipient_local_approval_amount_period.id"],
            name="fk_recipient_local_approval_amount_period_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_local_approval_amount_period_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_local_approval_amount_period_updated_by_account",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    amount_krw: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    approval_period: Mapped[Any] = mapped_column(
        DATERANGE,
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_local_approval_amount_period_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientContract(Base):
    __tablename__ = "recipient_contract"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="ck_recipient_contract_date_order",
        ),
        CheckConstraint(
            "row_version > 0",
            name="ck_recipient_contract_row_version_positive",
        ),
        ExcludeConstraint(
            ("recipient_id", "="),
            ("service_type_id", "="),
            ("contract_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_recipient_contract_same_service_period",
        ),
        ForeignKeyConstraint(
            ["recipient_id"],
            ["erp.recipient.id"],
            name="fk_recipient_contract_recipient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["service_type_id"],
            ["erp.service_type.id"],
            name="fk_recipient_contract_service_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_contract_id"],
            ["erp.recipient_contract.id"],
            name="fk_recipient_contract_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_contract_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_recipient_contract_updated_by_account",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger)
    service_type_id: Mapped[int] = mapped_column(BigInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    contract_period: Mapped[Any] = mapped_column(
        DATERANGE,
        # NULL end_date → NULL upper via end_date+1 → exact [start,) unbounded.
        Computed("daterange(start_date, end_date + 1, '[)')", persisted=True),
    )
    service_start_date: Mapped[date | None] = mapped_column(Date)
    end_reason_text: Mapped[str | None] = mapped_column(Text)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_contract_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by_account_id: Mapped[int] = mapped_column(BigInteger)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class RecipientServicePlanNotice(Base):
    __tablename__ = "recipient_service_plan_notice"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_recipient_service_plan_notice"),
        ForeignKeyConstraint(
            ["recipient_contract_id"],
            ["erp.recipient_contract.id"],
            name="fk_service_plan_notice_recipient_contract",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_service_plan_notice_id"],
            ["erp.recipient_service_plan_notice.id"],
            name="fk_service_plan_notice_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_service_plan_notice_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_service_plan_notice_updated_by_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "applied_end_date >= applied_start_date",
            name=conv("ck_service_plan_notice_date_order"),
        ),
        CheckConstraint(
            "row_version > 0",
            name=conv("ck_service_plan_notice_row_version_positive"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
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


class CareAssignment(Base):
    __tablename__ = "care_assignment"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_care_assignment"),
        ForeignKeyConstraint(
            ["recipient_contract_id"],
            ["erp.recipient_contract.id"],
            name="fk_care_assignment_recipient_contract",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["staff_id", "employment_id"],
            ["erp.staff_employment.staff_id", "erp.staff_employment.id"],
            name="fk_care_assignment_employment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["replacement_assignment_id"],
            ["erp.care_assignment.id"],
            name="fk_care_assignment_replacement",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["created_by_account_id"],
            ["erp.user_account.id"],
            name="fk_care_assignment_created_by_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["erp.user_account.id"],
            name="fk_care_assignment_updated_by_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "assignment_kind IN ('GENERAL','FAMILY')",
            name=conv("ck_care_assignment_kind"),
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name=conv("ck_care_assignment_date_order"),
        ),
        CheckConstraint(
            "row_version > 0",
            name=conv("ck_care_assignment_row_version_positive"),
        ),
        ExcludeConstraint(
            ("recipient_contract_id", "="),
            ("staff_id", "="),
            ("assignment_period", "&&"),
            where=text("invalidated_at_utc IS NULL"),
            using="gist",
            name="ex_care_assignment_same_contract_staff_period",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    recipient_contract_id: Mapped[int] = mapped_column(BigInteger)
    staff_id: Mapped[int] = mapped_column(BigInteger)
    employment_id: Mapped[int] = mapped_column(BigInteger)
    assignment_kind: Mapped[str] = mapped_column(Text)
    family_relationship_text: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
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
