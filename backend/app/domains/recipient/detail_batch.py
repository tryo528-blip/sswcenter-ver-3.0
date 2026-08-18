from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.domains.recipient.schemas import (
    GuardianCreateRequest,
    GuardianResponse,
    GuardianUpdateRequest,
    RecipientCreateRequest,
    RecipientResponse,
    RecipientUpdateRequest,
)
from app.domains.w1c.schemas import (
    ApprovalAmountPeriodCreateRequest,
    ApprovalAmountPeriodReplacementRequest,
    BenefitPeriodCreateRequest,
    BenefitPeriodReplacementRequest,
    CertificationIdentityCreateRequest,
    CertificationPeriodCreateRequest,
    CertificationPeriodReplacementRequest,
)
from app.domains.w1d.schemas import ContractCreateRequest


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CertificationPeriodMutation(StrictModel):
    period_id: int | None = Field(default=None, gt=0)
    payload: CertificationPeriodCreateRequest | CertificationPeriodReplacementRequest

    @model_validator(mode="after")
    def validate_mode(self) -> CertificationPeriodMutation:
        replacing = isinstance(self.payload, CertificationPeriodReplacementRequest)
        if replacing != (self.period_id is not None):
            raise ValueError("period_id and expected_row_version must be supplied together")
        return self


class BenefitPeriodMutation(StrictModel):
    period_id: int | None = Field(default=None, gt=0)
    payload: BenefitPeriodCreateRequest | BenefitPeriodReplacementRequest

    @model_validator(mode="after")
    def validate_mode(self) -> BenefitPeriodMutation:
        replacing = isinstance(self.payload, BenefitPeriodReplacementRequest)
        if replacing != (self.period_id is not None):
            raise ValueError("period_id and expected_row_version must be supplied together")
        return self


class ApprovalAmountPeriodMutation(StrictModel):
    period_id: int | None = Field(default=None, gt=0)
    payload: ApprovalAmountPeriodCreateRequest | ApprovalAmountPeriodReplacementRequest

    @model_validator(mode="after")
    def validate_mode(self) -> ApprovalAmountPeriodMutation:
        replacing = isinstance(self.payload, ApprovalAmountPeriodReplacementRequest)
        if replacing != (self.period_id is not None):
            raise ValueError("period_id and expected_row_version must be supplied together")
        return self


class RecipientDetailBatchRequest(StrictModel):
    certification_identity: CertificationIdentityCreateRequest | None = None
    certification_period: CertificationPeriodMutation | None = None
    benefit_period: BenefitPeriodMutation | None = None
    approval_amount_period: ApprovalAmountPeriodMutation | None = None
    contract: ContractCreateRequest | None = None

    @model_validator(mode="after")
    def require_operation(self) -> RecipientDetailBatchRequest:
        if not any(getattr(self, name) is not None for name in type(self).model_fields):
            raise ValueError("at least one detail operation is required")
        return self


class RecipientDetailBatchResponse(StrictModel):
    recipient_id: int
    saved_sections: list[str]


class BasicGuardianMutation(StrictModel):
    slot: Literal[0, 1]
    guardian_id: int | None = Field(default=None, gt=0)
    payload: GuardianCreateRequest | GuardianUpdateRequest

    @model_validator(mode="after")
    def validate_mode(self) -> BasicGuardianMutation:
        replacing = isinstance(self.payload, GuardianUpdateRequest)
        if replacing != (self.guardian_id is not None):
            raise ValueError("guardian_id and expected_row_version must be supplied together")
        return self


class RecipientBasicCreateBatchRequest(StrictModel):
    recipient: RecipientCreateRequest
    guardians: list[BasicGuardianMutation] = Field(default_factory=list, max_length=2)
    payer_guardian_slot: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def validate_guardians(self) -> RecipientBasicCreateBatchRequest:
        slots = [mutation.slot for mutation in self.guardians]
        if len(slots) != len(set(slots)):
            raise ValueError("guardian slots must be unique")
        if any(mutation.guardian_id is not None for mutation in self.guardians):
            raise ValueError("new recipients cannot update an existing guardian")
        if self.payer_guardian_slot is not None and self.payer_guardian_slot not in slots:
            raise ValueError("payer guardian slot must be included in guardians")
        return self


class RecipientBasicUpdateBatchRequest(StrictModel):
    recipient: RecipientUpdateRequest
    guardians: list[BasicGuardianMutation] = Field(default_factory=list, max_length=2)
    payer_guardian_slot: Literal[0, 1] | None = None
    preserve_payer: bool = False
    benefit_period: BenefitPeriodMutation | None = None

    @model_validator(mode="after")
    def validate_guardians(self) -> RecipientBasicUpdateBatchRequest:
        slots = [mutation.slot for mutation in self.guardians]
        if len(slots) != len(set(slots)):
            raise ValueError("guardian slots must be unique")
        if self.preserve_payer and self.payer_guardian_slot is not None:
            raise ValueError("preserve_payer cannot select a new payer guardian")
        if self.payer_guardian_slot is not None and self.payer_guardian_slot not in slots:
            raise ValueError("payer guardian slot must be included in guardians")
        return self


class RecipientBasicBatchResponse(StrictModel):
    recipient: RecipientResponse
    guardians: list[GuardianResponse]
    saved_sections: list[str]


class RecipientDetailBatchService:
    """Coordinate ordinary detail drafts in one shared SQLAlchemy transaction."""

    def __init__(
        self,
        *,
        recipient_service: Any,
        w1c_service: Any,
        w1d_service: Any,
    ) -> None:
        session = recipient_service.database_session
        if w1c_service.database_session is not session or w1d_service.session is not session:
            raise RuntimeError("recipient detail services must share one database session")
        self._session = session
        self._recipient_service = recipient_service
        self._w1c_service = w1c_service
        self._w1d_service = w1d_service

    def _apply_basic_guardians(
        self,
        *,
        recipient_id: int,
        mutations: list[BasicGuardianMutation],
        current_account: Any,
    ) -> dict[int, GuardianResponse]:
        saved: dict[int, GuardianResponse] = {}
        for mutation in sorted(mutations, key=lambda item: item.slot):
            if mutation.guardian_id is None:
                guardian = self._recipient_service.create_guardian(
                    recipient_id,
                    mutation.payload,
                    current_account,
                    slot_no=mutation.slot + 1,
                )
            else:
                guardian = self._recipient_service.update_guardian(
                    recipient_id,
                    mutation.guardian_id,
                    mutation.payload,
                    current_account,
                )
            saved[mutation.slot] = guardian
        return saved

    def _apply_basic_benefit(
        self,
        *,
        recipient_id: int,
        mutation: BenefitPeriodMutation | None,
        current_account: Any,
    ) -> None:
        if mutation is None:
            return
        if mutation.period_id is None:
            self._w1c_service.create_benefit_period(
                recipient_id,
                mutation.payload,
                current_account,
            )
        else:
            self._w1c_service.replace_benefit_period(
                recipient_id,
                mutation.period_id,
                mutation.payload,
                current_account,
            )

    def create_basic(
        self,
        *,
        payload: RecipientBasicCreateBatchRequest,
        current_account: Any,
    ) -> RecipientBasicBatchResponse:
        marker = "recipient_detail_batch_defer_commit"
        if self._session.info.get(marker):
            raise RuntimeError("nested recipient detail batch is not allowed")

        self._session.info[marker] = True
        try:
            recipient = self._recipient_service.create_recipient(payload.recipient, current_account)
            guardians = self._apply_basic_guardians(
                recipient_id=recipient.id,
                mutations=payload.guardians,
                current_account=current_account,
            )
            if payload.payer_guardian_slot is not None:
                recipient = self._recipient_service.update_recipient(
                    recipient.id,
                    RecipientUpdateRequest(
                        expected_row_version=recipient.row_version,
                        payer_guardian_id=guardians[payload.payer_guardian_slot].id,
                    ),
                    current_account,
                )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise self._recipient_service._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise RuntimeError("recipient basic batch commit failed") from None
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._session.info.pop(marker, None)

        saved_sections = ["recipient"]
        if payload.guardians:
            saved_sections.append("guardians")
        if payload.payer_guardian_slot is not None:
            saved_sections.append("payer")
        return RecipientBasicBatchResponse(
            recipient=recipient,
            guardians=[guardians[slot] for slot in sorted(guardians)],
            saved_sections=saved_sections,
        )

    def update_basic(
        self,
        *,
        recipient_id: int,
        payload: RecipientBasicUpdateBatchRequest,
        current_account: Any,
    ) -> RecipientBasicBatchResponse:
        marker = "recipient_detail_batch_defer_commit"
        if self._session.info.get(marker):
            raise RuntimeError("nested recipient detail batch is not allowed")

        self._session.info[marker] = True
        try:
            guardians = self._apply_basic_guardians(
                recipient_id=recipient_id,
                mutations=payload.guardians,
                current_account=current_account,
            )
            recipient_values = payload.recipient.model_dump(
                exclude_unset=True,
                exclude={"payer_guardian_id"},
            )
            if not payload.preserve_payer:
                recipient_values["payer_guardian_id"] = (
                    guardians[payload.payer_guardian_slot].id
                    if payload.payer_guardian_slot is not None
                    else None
                )
            recipient = self._recipient_service.update_recipient(
                recipient_id,
                RecipientUpdateRequest.model_validate(recipient_values),
                current_account,
            )
            self._apply_basic_benefit(
                recipient_id=recipient_id,
                mutation=payload.benefit_period,
                current_account=current_account,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise self._recipient_service._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self._session.rollback()
            raise RuntimeError("recipient basic batch commit failed") from None
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._session.info.pop(marker, None)

        saved_sections = ["recipient"]
        if payload.guardians:
            saved_sections.append("guardians")
        if not payload.preserve_payer:
            saved_sections.append("payer")
        if payload.benefit_period is not None:
            saved_sections.append("benefit_period")
        return RecipientBasicBatchResponse(
            recipient=recipient,
            guardians=[guardians[slot] for slot in sorted(guardians)],
            saved_sections=saved_sections,
        )

    def save(
        self,
        *,
        recipient_id: int,
        payload: RecipientDetailBatchRequest,
        current_account: Any,
    ) -> RecipientDetailBatchResponse:
        marker = "recipient_detail_batch_defer_commit"
        if self._session.info.get(marker):
            raise RuntimeError("nested recipient detail batch is not allowed")

        saved_sections: list[str] = []
        self._session.info[marker] = True
        try:
            if payload.certification_identity is not None:
                self._w1c_service.create_identity(
                    recipient_id,
                    payload.certification_identity,
                    current_account,
                )
                saved_sections.append("certification_identity")

            if payload.certification_period is not None:
                certification_mutation = payload.certification_period
                if certification_mutation.period_id is None:
                    self._w1c_service.create_certification_period(
                        recipient_id,
                        certification_mutation.payload,
                        current_account,
                    )
                else:
                    self._w1c_service.replace_certification_period(
                        recipient_id,
                        certification_mutation.period_id,
                        certification_mutation.payload,
                        current_account,
                    )
                saved_sections.append("certification_period")

            if payload.benefit_period is not None:
                benefit_mutation = payload.benefit_period
                if benefit_mutation.period_id is None:
                    self._w1c_service.create_benefit_period(
                        recipient_id,
                        benefit_mutation.payload,
                        current_account,
                    )
                else:
                    self._w1c_service.replace_benefit_period(
                        recipient_id,
                        benefit_mutation.period_id,
                        benefit_mutation.payload,
                        current_account,
                    )
                saved_sections.append("benefit_period")

            if payload.approval_amount_period is not None:
                approval_mutation = payload.approval_amount_period
                if approval_mutation.period_id is None:
                    self._w1c_service.create_approval_amount_period(
                        recipient_id,
                        approval_mutation.payload,
                        current_account,
                    )
                else:
                    self._w1c_service.replace_approval_amount_period(
                        recipient_id,
                        approval_mutation.period_id,
                        approval_mutation.payload,
                        current_account,
                    )
                saved_sections.append("approval_amount_period")

            if payload.contract is not None:
                self._w1d_service.create_contract(
                    recipient_id,
                    payload.contract,
                    current_account,
                )
                saved_sections.append("contract")

            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            if payload.contract is not None:
                raise self._w1d_service._map_integrity_error(exc) from None
            raise self._recipient_service._map_integrity_error(exc) from None
        except SQLAlchemyError as exc:
            self._session.rollback()
            if payload.contract is not None:
                raise self._w1d_service._map_sqlalchemy_error(exc) from None
            raise RuntimeError("recipient detail batch commit failed") from None
        except Exception:
            self._session.rollback()
            raise
        finally:
            self._session.info.pop(marker, None)

        return RecipientDetailBatchResponse(
            recipient_id=recipient_id,
            saved_sections=saved_sections,
        )
