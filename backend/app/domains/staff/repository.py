from __future__ import annotations

from sqlalchemy import case, func, inspect, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from app.db.models import (
    BusinessNumberCounter,
    LicenseType,
    ServiceGroup,
    ServiceType,
    Staff,
    StaffEmployment,
    StaffHealthCheck,
    StaffHealthCheckRequirement,
    StaffLicense,
    StaffOnboardingTraining,
    StaffOperationalRolePeriod,
    StaffPeriodicTrainingStatus,
    StaffPositionPeriod,
    StaffQuarterlyConsultation,
    StaffSensitiveIdentity,
    StaffServiceQualificationPeriod,
    TrainingCourse,
)

_SERVICE_CATALOG_ORDER = (
    ("LONG_TERM_CARE", "HOME_CARE"),
    ("LONG_TERM_CARE", "HOME_BATH"),
    ("LOCAL_CARE", "TEMP_HOME_CARE"),
    ("LOCAL_CARE", "HOSPITAL_ESCORT"),
    ("BARO_CARE", "BARO_CARE"),
)

_TRAINING_COURSE_ORDER = (
    "NEW_HIRE_ORIENTATION",
    "ELDER_RIGHTS",
    "DISABLED_ABUSE",
    "ELDER_ABUSE",
    "SEXUAL_HARASSMENT",
    "WORKPLACE_BULLYING",
    "PRIVACY",
    "CONTINUING_EDUCATION",
)


class StaffRepository:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def add(self, instance: object) -> None:
        self.database_session.add(instance)

    def flush(self) -> None:
        self.database_session.flush()

    def training_schema_available(self) -> bool:
        try:
            return bool(
                inspect(self.database_session.get_bind()).has_table(
                    "training_course",
                    schema="erp",
                )
            )
        except Exception:
            return False

    def get_staff(self, staff_id: int, *, for_update: bool = False) -> Staff | None:
        statement = select(Staff).where(Staff.id == staff_id)
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_staff(
        self,
        *,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Staff], int]:
        filters = []
        if search:
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    Staff.name.ilike(pattern, escape="\\"),
                    Staff.display_name.ilike(pattern, escape="\\"),
                )
            )

        count_statement = select(func.count()).select_from(Staff)
        statement = select(Staff)
        if filters:
            count_statement = count_statement.where(*filters)
            statement = statement.where(*filters)
        total = int(self.database_session.scalar(count_statement) or 0)
        items = list(
            self.database_session.scalars(
                statement.order_by(Staff.name.asc(), Staff.id.asc()).offset(offset).limit(limit)
            )
        )
        return items, total

    def get_sensitive_identity(
        self,
        staff_id: int,
        *,
        for_update: bool = False,
    ) -> StaffSensitiveIdentity | None:
        statement = select(StaffSensitiveIdentity).where(
            StaffSensitiveIdentity.staff_id == staff_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_employments(self, staff_id: int) -> list[StaffEmployment]:
        return list(
            self.database_session.scalars(
                select(StaffEmployment)
                .where(
                    StaffEmployment.staff_id == staff_id,
                    StaffEmployment.invalidated_at_utc.is_(None),
                )
                .order_by(StaffEmployment.start_date.desc(), StaffEmployment.id.desc())
            )
        )

    def get_employment(
        self,
        staff_id: int,
        employment_id: int,
        *,
        for_update: bool = False,
    ) -> StaffEmployment | None:
        statement = select(StaffEmployment).where(
            StaffEmployment.id == employment_id,
            StaffEmployment.staff_id == staff_id,
            StaffEmployment.invalidated_at_utc.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_employment_by_id(
        self,
        employment_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffEmployment | None:
        statement = select(StaffEmployment).where(StaffEmployment.id == employment_id)
        if active_only:
            statement = statement.where(StaffEmployment.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_positions(
        self,
        staff_id: int,
        *,
        employment_id: int | None = None,
        for_update: bool = False,
    ) -> list[StaffPositionPeriod]:
        statement = select(StaffPositionPeriod).where(
            StaffPositionPeriod.staff_id == staff_id,
            StaffPositionPeriod.invalidated_at_utc.is_(None),
        )
        if employment_id is not None:
            statement = statement.where(StaffPositionPeriod.employment_id == employment_id)
        if for_update:
            statement = statement.with_for_update()
        return list(
            self.database_session.scalars(
                statement.order_by(
                    StaffPositionPeriod.start_date.desc(),
                    StaffPositionPeriod.id.desc(),
                )
            )
        )

    def get_position(
        self,
        staff_id: int,
        employment_id: int,
        period_id: int,
        *,
        for_update: bool = False,
    ) -> StaffPositionPeriod | None:
        statement = select(StaffPositionPeriod).where(
            StaffPositionPeriod.id == period_id,
            StaffPositionPeriod.staff_id == staff_id,
            StaffPositionPeriod.employment_id == employment_id,
            StaffPositionPeriod.invalidated_at_utc.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_operational_roles(
        self,
        staff_id: int,
        *,
        employment_id: int | None = None,
        for_update: bool = False,
    ) -> list[StaffOperationalRolePeriod]:
        statement = select(StaffOperationalRolePeriod).where(
            StaffOperationalRolePeriod.staff_id == staff_id,
            StaffOperationalRolePeriod.invalidated_at_utc.is_(None),
        )
        if employment_id is not None:
            statement = statement.where(StaffOperationalRolePeriod.employment_id == employment_id)
        if for_update:
            statement = statement.with_for_update()
        return list(
            self.database_session.scalars(
                statement.order_by(
                    StaffOperationalRolePeriod.start_date.desc(),
                    StaffOperationalRolePeriod.role_code.asc(),
                    StaffOperationalRolePeriod.id.desc(),
                )
            )
        )

    def get_operational_role(
        self,
        staff_id: int,
        employment_id: int,
        period_id: int,
        *,
        for_update: bool = False,
    ) -> StaffOperationalRolePeriod | None:
        statement = select(StaffOperationalRolePeriod).where(
            StaffOperationalRolePeriod.id == period_id,
            StaffOperationalRolePeriod.staff_id == staff_id,
            StaffOperationalRolePeriod.employment_id == employment_id,
            StaffOperationalRolePeriod.invalidated_at_utc.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_service_catalog(self) -> list[tuple[ServiceGroup, ServiceType]]:
        catalog_order = case(
            *(
                (
                    (ServiceGroup.code == group_code) & (ServiceType.code == service_code),
                    order,
                )
                for order, (group_code, service_code) in enumerate(_SERVICE_CATALOG_ORDER)
            ),
            else_=len(_SERVICE_CATALOG_ORDER),
        )
        return list(
            self.database_session.execute(
                select(ServiceGroup, ServiceType)
                .join(ServiceType, ServiceType.service_group_id == ServiceGroup.id)
                .where(ServiceGroup.active.is_(True), ServiceType.active.is_(True))
                .order_by(
                    catalog_order.asc(),
                    ServiceGroup.code.asc(),
                    ServiceType.code.asc(),
                    ServiceGroup.id.asc(),
                    ServiceType.id.asc(),
                )
            ).tuples()
        )

    def list_license_types(self) -> list[LicenseType]:
        return list(
            self.database_session.scalars(
                select(LicenseType)
                .where(LicenseType.active.is_(True))
                .order_by(LicenseType.id.asc())
            )
        )

    def list_training_courses(self) -> list[TrainingCourse]:
        catalog_order = case(
            *(
                (TrainingCourse.code == code, order)
                for order, code in enumerate(_TRAINING_COURSE_ORDER)
            ),
            else_=len(_TRAINING_COURSE_ORDER),
        )
        return list(
            self.database_session.scalars(
                select(TrainingCourse)
                .where(TrainingCourse.active.is_(True))
                .order_by(
                    catalog_order.asc(),
                    TrainingCourse.code.asc(),
                )
            )
        )

    def get_training_course(self, code: str) -> TrainingCourse | None:
        return self.database_session.scalar(
            select(TrainingCourse).where(
                TrainingCourse.code == code,
                TrainingCourse.active.is_(True),
            )
        )

    def list_onboarding_trainings(self, staff_id: int) -> list[StaffOnboardingTraining]:
        return list(
            self.database_session.scalars(
                select(StaffOnboardingTraining)
                .where(
                    StaffOnboardingTraining.staff_id == staff_id,
                    StaffOnboardingTraining.invalidated_at_utc.is_(None),
                )
                .order_by(
                    StaffOnboardingTraining.employment_id.asc(),
                    StaffOnboardingTraining.id.asc(),
                )
            )
        )

    def get_onboarding_training(
        self,
        staff_id: int,
        training_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffOnboardingTraining | None:
        statement = select(StaffOnboardingTraining).where(
            StaffOnboardingTraining.staff_id == staff_id,
            StaffOnboardingTraining.id == training_id,
        )
        if active_only:
            statement = statement.where(StaffOnboardingTraining.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_onboarding_training_by_id(
        self,
        training_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffOnboardingTraining | None:
        statement = select(StaffOnboardingTraining).where(StaffOnboardingTraining.id == training_id)
        if active_only:
            statement = statement.where(StaffOnboardingTraining.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_periodic_trainings(self, staff_id: int) -> list[StaffPeriodicTrainingStatus]:
        return list(
            self.database_session.scalars(
                select(StaffPeriodicTrainingStatus)
                .where(
                    StaffPeriodicTrainingStatus.staff_id == staff_id,
                    StaffPeriodicTrainingStatus.invalidated_at_utc.is_(None),
                )
                .order_by(
                    StaffPeriodicTrainingStatus.period_key.desc(),
                    StaffPeriodicTrainingStatus.course_code.asc(),
                    StaffPeriodicTrainingStatus.id.asc(),
                )
            )
        )

    def get_periodic_training(
        self,
        staff_id: int,
        training_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffPeriodicTrainingStatus | None:
        statement = select(StaffPeriodicTrainingStatus).where(
            StaffPeriodicTrainingStatus.staff_id == staff_id,
            StaffPeriodicTrainingStatus.id == training_id,
        )
        if active_only:
            statement = statement.where(StaffPeriodicTrainingStatus.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_periodic_training_by_id(
        self,
        training_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffPeriodicTrainingStatus | None:
        statement = select(StaffPeriodicTrainingStatus).where(
            StaffPeriodicTrainingStatus.id == training_id
        )
        if active_only:
            statement = statement.where(StaffPeriodicTrainingStatus.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_license_type(self, code: str) -> LicenseType | None:
        return self.database_session.scalar(
            select(LicenseType).where(
                LicenseType.code == code,
                LicenseType.active.is_(True),
            )
        )

    def get_service_type(self, code: str) -> ServiceType | None:
        return self.database_session.scalar(
            select(ServiceType)
            .join(ServiceGroup, ServiceGroup.id == ServiceType.service_group_id)
            .where(
                ServiceType.code == code,
                ServiceType.active.is_(True),
                ServiceGroup.active.is_(True),
            )
        )

    def get_service_type_by_id(self, service_type_id: int) -> ServiceType | None:
        return self.database_session.scalar(
            select(ServiceType).where(ServiceType.id == service_type_id)
        )

    def get_service_group_by_id(self, service_group_id: int) -> ServiceGroup | None:
        return self.database_session.get(ServiceGroup, service_group_id)

    def list_licenses(self, staff_id: int) -> list[tuple[StaffLicense, LicenseType]]:
        return list(
            self.database_session.execute(
                select(StaffLicense, LicenseType)
                .join(LicenseType, LicenseType.id == StaffLicense.license_type_id)
                .where(StaffLicense.staff_id == staff_id)
                .order_by(StaffLicense.id.asc())
            ).tuples()
        )

    def get_license(
        self,
        staff_id: int,
        license_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> StaffLicense | None:
        statement = select(StaffLicense).where(
            StaffLicense.staff_id == staff_id,
            StaffLicense.id == license_id,
        )
        if active_only:
            statement = statement.where(StaffLicense.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_active_license(self, staff_id: int, license_id: int) -> StaffLicense | None:
        return self.get_license(staff_id, license_id, active_only=True)

    def list_qualifications(
        self,
        staff_id: int,
    ) -> list[tuple[StaffServiceQualificationPeriod, ServiceType, ServiceGroup]]:
        return list(
            self.database_session.execute(
                select(StaffServiceQualificationPeriod, ServiceType, ServiceGroup)
                .join(
                    ServiceType,
                    ServiceType.id == StaffServiceQualificationPeriod.service_type_id,
                )
                .join(ServiceGroup, ServiceGroup.id == ServiceType.service_group_id)
                .where(StaffServiceQualificationPeriod.staff_id == staff_id)
                .order_by(
                    StaffServiceQualificationPeriod.start_date.desc(),
                    StaffServiceQualificationPeriod.id.desc(),
                )
            ).tuples()
        )

    def get_qualification(
        self,
        staff_id: int,
        qualification_id: int,
        *,
        for_update: bool = False,
        active_only: bool = False,
    ) -> StaffServiceQualificationPeriod | None:
        statement = select(StaffServiceQualificationPeriod).where(
            StaffServiceQualificationPeriod.staff_id == staff_id,
            StaffServiceQualificationPeriod.id == qualification_id,
        )
        if active_only:
            statement = statement.where(
                StaffServiceQualificationPeriod.invalidated_at_utc.is_(None)
            )
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def next_staff_number(self, year: int) -> int:
        self.database_session.execute(
            postgres_insert(BusinessNumberCounter)
            .values(
                number_type="STAFF_EMPLOYMENT",
                number_year=year,
                last_sequence=0,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    BusinessNumberCounter.number_type,
                    BusinessNumberCounter.number_year,
                ]
            )
        )
        counter = self.database_session.get(
            BusinessNumberCounter,
            ("STAFF_EMPLOYMENT", year),
            with_for_update=True,
        )
        if counter is None:
            raise RuntimeError("staff employment counter was not created")
        counter.last_sequence += 1
        return counter.last_sequence

    def next_employment_number(self, staff_id: int) -> int:
        current_max = self.database_session.scalar(
            select(func.max(StaffEmployment.employment_no)).where(
                StaffEmployment.staff_id == staff_id
            )
        )
        return int(current_max or 0) + 1

    def list_health_checks(self, staff_id: int) -> list[StaffHealthCheck]:
        return list(
            self.database_session.scalars(
                select(StaffHealthCheck)
                .where(
                    StaffHealthCheck.staff_id == staff_id,
                    StaffHealthCheck.invalidated_at_utc.is_(None),
                )
                .order_by(StaffHealthCheck.check_date.desc(), StaffHealthCheck.id.desc())
            )
        )

    def get_health_check(
        self,
        staff_id: int,
        health_check_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffHealthCheck | None:
        statement = select(StaffHealthCheck).where(
            StaffHealthCheck.staff_id == staff_id,
            StaffHealthCheck.id == health_check_id,
        )
        if active_only:
            statement = statement.where(StaffHealthCheck.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_health_check_by_id(
        self,
        health_check_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffHealthCheck | None:
        statement = select(StaffHealthCheck).where(StaffHealthCheck.id == health_check_id)
        if active_only:
            statement = statement.where(StaffHealthCheck.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_health_check_requirements(
        self,
        staff_id: int,
    ) -> list[StaffHealthCheckRequirement]:
        return list(
            self.database_session.scalars(
                select(StaffHealthCheckRequirement)
                .where(
                    StaffHealthCheckRequirement.staff_id == staff_id,
                    StaffHealthCheckRequirement.invalidated_at_utc.is_(None),
                )
                .order_by(
                    StaffHealthCheckRequirement.target_key.asc(),
                    StaffHealthCheckRequirement.id.asc(),
                )
            )
        )

    def get_health_check_requirement(
        self,
        staff_id: int,
        requirement_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffHealthCheckRequirement | None:
        statement = select(StaffHealthCheckRequirement).where(
            StaffHealthCheckRequirement.staff_id == staff_id,
            StaffHealthCheckRequirement.id == requirement_id,
        )
        if active_only:
            statement = statement.where(StaffHealthCheckRequirement.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_health_check_requirement_by_id(
        self,
        requirement_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffHealthCheckRequirement | None:
        statement = select(StaffHealthCheckRequirement).where(
            StaffHealthCheckRequirement.id == requirement_id
        )
        if active_only:
            statement = statement.where(StaffHealthCheckRequirement.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def list_quarterly_consultations(
        self,
        staff_id: int,
    ) -> list[StaffQuarterlyConsultation]:
        return list(
            self.database_session.scalars(
                select(StaffQuarterlyConsultation)
                .where(
                    StaffQuarterlyConsultation.staff_id == staff_id,
                    StaffQuarterlyConsultation.invalidated_at_utc.is_(None),
                )
                .order_by(
                    StaffQuarterlyConsultation.calendar_year.desc(),
                    StaffQuarterlyConsultation.quarter_no.desc(),
                    StaffQuarterlyConsultation.id.desc(),
                )
            )
        )

    def get_quarterly_consultation(
        self,
        staff_id: int,
        consultation_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffQuarterlyConsultation | None:
        statement = select(StaffQuarterlyConsultation).where(
            StaffQuarterlyConsultation.staff_id == staff_id,
            StaffQuarterlyConsultation.id == consultation_id,
        )
        if active_only:
            statement = statement.where(StaffQuarterlyConsultation.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)

    def get_quarterly_consultation_by_id(
        self,
        consultation_id: int,
        *,
        for_update: bool = False,
        active_only: bool = True,
    ) -> StaffQuarterlyConsultation | None:
        statement = select(StaffQuarterlyConsultation).where(
            StaffQuarterlyConsultation.id == consultation_id
        )
        if active_only:
            statement = statement.where(StaffQuarterlyConsultation.invalidated_at_utc.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.database_session.scalar(statement)
