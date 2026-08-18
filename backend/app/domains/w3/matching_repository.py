"""Read-only W1/W2 candidate resolver for approved W3 stable keys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, literal, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import (
    CareAssignment,
    RecipientCertificationIdentity,
    RecipientCertificationPeriod,
    RecipientContract,
    ServiceType,
    StaffEmployment,
    StaffLegacyMapping,
    StaffPositionPeriod,
    StaffServiceQualificationPeriod,
)
from app.db.w2_models import W2Schedule, W2ScheduleMonthControl, W2ScheduleStaff

KST = ZoneInfo("Asia/Seoul")
SERVICE_CODE_BY_SOURCE = {
    "방문요양": "HOME_CARE",
    "방문목욕": "HOME_BATH",
}


@dataclass(frozen=True, slots=True)
class W3TypedLink:
    recipient_id: int
    certification_period_id: int
    staff_id: int
    employment_id: int
    staff_legacy_mapping_id: int | None
    service_type_id: int
    recipient_contract_id: int
    care_assignment_id: int
    w2_schedule_id: int


def _date_valid(start: Any, end: Any, target: date) -> ColumnElement[bool]:
    return and_(start <= target, or_(end.is_(None), end >= target))


def _planned_utc(service_date: date, value: time) -> datetime:
    return datetime.combine(service_date, value, tzinfo=KST).astimezone(ZoneInfo("UTC"))


class W3MatchingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def automatic_nhis_links(
        self,
        *,
        service_date: date,
        planned_start: time,
        planned_end: time,
        recipient_certification_number: str,
        staff_external_number: str,
        service_category: str,
    ) -> tuple[W3TypedLink, ...]:
        service_code = SERVICE_CODE_BY_SOURCE[service_category]
        starts_at_utc = _planned_utc(service_date, planned_start)
        ends_at_utc = _planned_utc(service_date, planned_end)
        month = service_date.replace(day=1)

        statement = (
            select(
                RecipientCertificationIdentity.recipient_id,
                RecipientCertificationPeriod.id,
                StaffEmployment.staff_id,
                StaffEmployment.id,
                StaffLegacyMapping.id,
                ServiceType.id,
                RecipientContract.id,
                CareAssignment.id,
                W2Schedule.id,
            )
            .select_from(RecipientCertificationIdentity)
            .join(
                RecipientCertificationPeriod,
                RecipientCertificationPeriod.recipient_id
                == RecipientCertificationIdentity.recipient_id,
            )
            .join(ServiceType, ServiceType.code == service_code)
            .join(
                RecipientContract,
                and_(
                    RecipientContract.recipient_id
                    == RecipientCertificationIdentity.recipient_id,
                    RecipientContract.service_type_id == ServiceType.id,
                ),
            )
            .join(
                W2Schedule,
                and_(
                    W2Schedule.recipient_id == RecipientCertificationIdentity.recipient_id,
                    W2Schedule.service_type_id == ServiceType.id,
                    W2Schedule.schedule_month == month,
                    W2Schedule.starts_at_utc == starts_at_utc,
                    W2Schedule.ends_at_utc == ends_at_utc,
                ),
            )
            .join(W2ScheduleStaff, W2ScheduleStaff.schedule_id == W2Schedule.id)
            .join(
                StaffLegacyMapping,
                and_(
                    StaffLegacyMapping.staff_id == W2ScheduleStaff.staff_id,
                    StaffLegacyMapping.source_system_code == "NHIS_SCHEDULE",
                    StaffLegacyMapping.legacy_staff_key == staff_external_number,
                    StaffLegacyMapping.invalidated_at_utc.is_(None),
                ),
            )
            .join(
                StaffEmployment,
                and_(
                    StaffEmployment.id == W2ScheduleStaff.employment_id,
                    StaffEmployment.staff_id == W2ScheduleStaff.staff_id,
                ),
            )
            .join(
                StaffPositionPeriod,
                and_(
                    StaffPositionPeriod.staff_id == StaffEmployment.staff_id,
                    StaffPositionPeriod.employment_id == StaffEmployment.id,
                    StaffPositionPeriod.position_code == "CARE_WORKER",
                ),
            )
            .join(
                StaffServiceQualificationPeriod,
                and_(
                    StaffServiceQualificationPeriod.staff_id == StaffEmployment.staff_id,
                    StaffServiceQualificationPeriod.employment_id == StaffEmployment.id,
                    StaffServiceQualificationPeriod.service_type_id == ServiceType.id,
                ),
            )
            .join(
                CareAssignment,
                and_(
                    CareAssignment.recipient_contract_id == RecipientContract.id,
                    CareAssignment.staff_id == StaffEmployment.staff_id,
                    CareAssignment.employment_id == StaffEmployment.id,
                ),
            )
            .join(
                W2ScheduleMonthControl,
                W2ScheduleMonthControl.schedule_month == W2Schedule.schedule_month,
            )
            .where(
                RecipientCertificationIdentity.certification_number
                == recipient_certification_number,
                RecipientCertificationPeriod.invalidated_at_utc.is_(None),
                RecipientCertificationPeriod.start_date <= service_date,
                RecipientCertificationPeriod.end_date >= service_date,
                RecipientContract.invalidated_at_utc.is_(None),
                _date_valid(
                    RecipientContract.start_date,
                    RecipientContract.end_date,
                    service_date,
                ),
                StaffEmployment.invalidated_at_utc.is_(None),
                _date_valid(StaffEmployment.start_date, StaffEmployment.end_date, service_date),
                StaffPositionPeriod.invalidated_at_utc.is_(None),
                _date_valid(
                    StaffPositionPeriod.start_date,
                    StaffPositionPeriod.end_date,
                    service_date,
                ),
                StaffServiceQualificationPeriod.invalidated_at_utc.is_(None),
                _date_valid(
                    StaffServiceQualificationPeriod.start_date,
                    StaffServiceQualificationPeriod.end_date,
                    service_date,
                ),
                CareAssignment.invalidated_at_utc.is_(None),
                _date_valid(CareAssignment.start_date, CareAssignment.end_date, service_date),
                W2ScheduleMonthControl.finalized_at_utc.is_(None),
                ServiceType.active.is_(True),
            )
            .distinct()
            .order_by(W2Schedule.id, StaffEmployment.staff_id)
        )
        return tuple(W3TypedLink(*map(int, row)) for row in self.session.execute(statement))

    def validated_manual_link(
        self,
        *,
        service_date: date,
        recipient_certification_number: str,
        service_category: str,
        staff_external_number: str | None,
        planned_start: time | None,
        planned_end: time | None,
        recipient_id: int,
        certification_period_id: int,
        staff_id: int,
        employment_id: int,
        service_type_id: int,
        recipient_contract_id: int,
        care_assignment_id: int,
        w2_schedule_id: int,
    ) -> W3TypedLink | None:
        if (planned_start is None) != (planned_end is None):
            raise ValueError("planned_start and planned_end must be supplied together")
        service_code = SERVICE_CODE_BY_SOURCE[service_category]
        schedule_month = service_date.replace(day=1)
        service_day_start_utc = datetime.combine(
            service_date,
            time.min,
            tzinfo=KST,
        ).astimezone(ZoneInfo("UTC"))
        service_day_end_utc = service_day_start_utc + timedelta(days=1)
        mapping_id_column = (
            StaffLegacyMapping.id
            if staff_external_number is not None
            else literal(None)
        )
        statement = (
            select(
                RecipientCertificationIdentity.recipient_id,
                RecipientCertificationPeriod.id,
                StaffEmployment.staff_id,
                StaffEmployment.id,
                mapping_id_column,
                ServiceType.id,
                RecipientContract.id,
                CareAssignment.id,
                W2Schedule.id,
            )
            .select_from(W2Schedule)
            .join(
                W2ScheduleStaff,
                and_(
                    W2ScheduleStaff.schedule_id == W2Schedule.id,
                    W2ScheduleStaff.staff_id == staff_id,
                    W2ScheduleStaff.employment_id == employment_id,
                ),
            )
            .join(ServiceType, ServiceType.id == W2Schedule.service_type_id)
            .join(
                RecipientCertificationIdentity,
                RecipientCertificationIdentity.recipient_id == W2Schedule.recipient_id,
            )
            .join(
                RecipientCertificationPeriod,
                RecipientCertificationPeriod.recipient_id == W2Schedule.recipient_id,
            )
            .join(
                RecipientContract,
                and_(
                    RecipientContract.id == recipient_contract_id,
                    RecipientContract.recipient_id == W2Schedule.recipient_id,
                    RecipientContract.service_type_id == W2Schedule.service_type_id,
                ),
            )
            .join(
                CareAssignment,
                and_(
                    CareAssignment.id == care_assignment_id,
                    CareAssignment.recipient_contract_id == RecipientContract.id,
                    CareAssignment.staff_id == W2ScheduleStaff.staff_id,
                    CareAssignment.employment_id == W2ScheduleStaff.employment_id,
                ),
            )
            .join(
                StaffEmployment,
                and_(
                    StaffEmployment.id == W2ScheduleStaff.employment_id,
                    StaffEmployment.staff_id == W2ScheduleStaff.staff_id,
                ),
            )
            .join(
                StaffPositionPeriod,
                and_(
                    StaffPositionPeriod.staff_id == StaffEmployment.staff_id,
                    StaffPositionPeriod.employment_id == StaffEmployment.id,
                    StaffPositionPeriod.position_code == "CARE_WORKER",
                ),
            )
            .join(
                StaffServiceQualificationPeriod,
                and_(
                    StaffServiceQualificationPeriod.staff_id == StaffEmployment.staff_id,
                    StaffServiceQualificationPeriod.employment_id == StaffEmployment.id,
                    StaffServiceQualificationPeriod.service_type_id == ServiceType.id,
                ),
            )
            .join(
                W2ScheduleMonthControl,
                W2ScheduleMonthControl.schedule_month == W2Schedule.schedule_month,
            )
            .where(
                W2Schedule.id == w2_schedule_id,
                W2Schedule.schedule_month == schedule_month,
                W2Schedule.starts_at_utc >= service_day_start_utc,
                W2Schedule.starts_at_utc < service_day_end_utc,
                W2Schedule.recipient_id == recipient_id,
                W2ScheduleStaff.staff_id == staff_id,
                W2ScheduleStaff.employment_id == employment_id,
                W2Schedule.service_type_id == service_type_id,
                RecipientCertificationIdentity.certification_number
                == recipient_certification_number,
                RecipientCertificationPeriod.id == certification_period_id,
                RecipientCertificationPeriod.invalidated_at_utc.is_(None),
                RecipientCertificationPeriod.start_date <= service_date,
                RecipientCertificationPeriod.end_date >= service_date,
                RecipientContract.invalidated_at_utc.is_(None),
                _date_valid(
                    RecipientContract.start_date,
                    RecipientContract.end_date,
                    service_date,
                ),
                CareAssignment.invalidated_at_utc.is_(None),
                _date_valid(CareAssignment.start_date, CareAssignment.end_date, service_date),
                StaffEmployment.invalidated_at_utc.is_(None),
                _date_valid(StaffEmployment.start_date, StaffEmployment.end_date, service_date),
                StaffPositionPeriod.invalidated_at_utc.is_(None),
                _date_valid(
                    StaffPositionPeriod.start_date,
                    StaffPositionPeriod.end_date,
                    service_date,
                ),
                StaffServiceQualificationPeriod.invalidated_at_utc.is_(None),
                _date_valid(
                    StaffServiceQualificationPeriod.start_date,
                    StaffServiceQualificationPeriod.end_date,
                    service_date,
                ),
                W2ScheduleMonthControl.finalized_at_utc.is_(None),
                ServiceType.active.is_(True),
                ServiceType.code == service_code,
            )
            .distinct()
        )
        if staff_external_number is not None:
            statement = statement.join(
                StaffLegacyMapping,
                and_(
                    StaffLegacyMapping.staff_id == W2ScheduleStaff.staff_id,
                    StaffLegacyMapping.source_system_code == "NHIS_SCHEDULE",
                    StaffLegacyMapping.legacy_staff_key == staff_external_number,
                    StaffLegacyMapping.invalidated_at_utc.is_(None),
                ),
            )
        if planned_start is not None and planned_end is not None:
            statement = statement.where(
                W2Schedule.starts_at_utc == _planned_utc(service_date, planned_start),
                W2Schedule.ends_at_utc == _planned_utc(service_date, planned_end),
            )
        rows = self.session.execute(statement).all()
        if len(rows) != 1:
            return None
        row = rows[0]
        return W3TypedLink(
            recipient_id=int(row[0]),
            certification_period_id=int(row[1]),
            staff_id=int(row[2]),
            employment_id=int(row[3]),
            staff_legacy_mapping_id=None if row[4] is None else int(row[4]),
            service_type_id=int(row[5]),
            recipient_contract_id=int(row[6]),
            care_assignment_id=int(row[7]),
            w2_schedule_id=int(row[8]),
        )
