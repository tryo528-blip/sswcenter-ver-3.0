"""W1D contract and certification-transition service."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth import CurrentAccount
from app.core.settings import Settings, get_settings
from app.db.models import (
    RecipientCertificationPeriod,
    RecipientContract,
    RecipientGradePeriod,
    ServiceGroup,
    ServiceType,
)
from app.domains.w1d import clock as w1d_clock
from app.domains.w1d import fault as w1d_fault
from app.domains.w1d.errors import domain_error
from app.domains.w1d.policies import (
    SERIALIZATION_VERSION,
    build_canonical_projection,
    canonicalize_date,
    canonicalize_utc_timestamp,
    constant_time_hash_equal,
    full_bound_replacements,
    mint_preview_token,
    non_sensitive_replacements,
    replacements_exact_equal,
    sha256_canonical,
    verify_preview_token,
)
from app.domains.w1d.repository import W1DRepository
from app.domains.w1d.schemas import (
    CertificationTransitionApplyRequest,
    CertificationTransitionApplyResponse,
    CertificationTransitionPreviewRequest,
    CertificationTransitionPreviewResponse,
    ContractCreateRequest,
    ContractEndRequest,
    ContractListResponse,
    ContractResponse,
    ReplacementPreviewItem,
    TransitionReplacementItem,
    validate_transition_period_semantics,
)

LTC_GROUP_CODE = "LONG_TERM_CARE"


class W1DService:
    def __init__(
        self,
        database_session: Session,
        settings: Settings | None = None,
        *,
        request_id: UUID | None = None,
    ) -> None:
        self.session = database_session
        self.settings = settings if settings is not None else get_settings()
        self.request_id = request_id
        self.repo = W1DRepository(database_session)

    def _token_key(self) -> bytes:
        secret = self.settings.transition_token_key
        if secret is None:
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500)
        return secret.get_secret_value().encode("utf-8")

    def _now(self) -> datetime:
        return w1d_clock.now_utc()

    @staticmethod
    def _map_integrity_error(error: IntegrityError) -> Any:
        original = getattr(error, "orig", None)
        diagnostics = getattr(original, "diag", None)
        constraint_name = getattr(diagnostics, "constraint_name", None)
        mapping = {
            "ex_recipient_contract_same_service_period": (
                "CONTRACT_SERVICE_PERIOD_CONFLICT",
                409,
            ),
            "trg_recipient_contract_group_period_overlap": (
                "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT",
                409,
            ),
            "ck_recipient_contract_no_reactivation": (
                "CONTRACT_REACTIVATION_FORBIDDEN",
                409,
            ),
        }
        mapped = mapping.get(constraint_name) if isinstance(constraint_name, str) else None
        if mapped is not None:
            return domain_error(mapped[0], mapped[1])
        # Fallback message scan for constraint trigger names without diag.
        msg = str(original or error).lower()
        if "same_service" in msg or "ex_recipient_contract_same_service" in msg:
            return domain_error("CONTRACT_SERVICE_PERIOD_CONFLICT", 409)
        if "group_period_overlap" in msg or "cross-group" in msg:
            return domain_error("CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT", 409)
        if "reactivation" in msg:
            return domain_error("CONTRACT_REACTIVATION_FORBIDDEN", 409)
        return domain_error("UNEXPECTED_SERVER_ERROR", 500)

    def _flush(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.session.rollback()
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _commit(self) -> None:
        if self.session.info.get("recipient_detail_batch_defer_commit"):
            self.session.flush()
            return
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._map_integrity_error(exc) from None
        except SQLAlchemyError:
            self.session.rollback()
            raise domain_error("UNEXPECTED_SERVER_ERROR", 500) from None

    def _service_meta(
        self,
    ) -> tuple[dict[int, ServiceType], dict[str, ServiceType], dict[int, str]]:
        types = list(self.session.scalars(select(ServiceType)).all())
        groups = {g.id: g.code for g in self.session.scalars(select(ServiceGroup)).all()}
        by_id = {t.id: t for t in types}
        by_code = {t.code: t for t in types}
        group_by_type = {t.id: groups.get(t.service_group_id, "") for t in types}
        return by_id, by_code, group_by_type

    def _to_response(
        self,
        row: RecipientContract,
        *,
        by_id: dict[int, ServiceType],
        group_by_type: dict[int, str],
    ) -> ContractResponse:
        st = by_id.get(row.service_type_id)
        return ContractResponse(
            id=row.id,
            recipient_id=row.recipient_id,
            service_type_code=st.code if st else "",
            service_group_code=group_by_type.get(row.service_type_id) or None,
            start_date=row.start_date,
            end_date=row.end_date,
            service_start_date=row.service_start_date,
            signer_name=row.signer_name,
            signer_relationship_text=row.signer_relationship_text,
            signer_phone=row.signer_phone,
            end_reason_text=row.end_reason_text,
            invalidated_at_utc=row.invalidated_at_utc,
            replacement_contract_id=row.replacement_contract_id,
            row_version=row.row_version,
        )

    def list_contracts(self, recipient_id: int) -> ContractListResponse:
        recipient = self.repo.get_recipient(recipient_id)
        if recipient is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        by_id, _, group_by_type = self._service_meta()
        items = [
            self._to_response(row, by_id=by_id, group_by_type=group_by_type)
            for row in self.repo.list_contracts(recipient_id)
        ]
        return ContractListResponse(items=items)

    def get_contract(self, recipient_id: int, contract_id: int) -> ContractResponse:
        recipient = self.repo.get_recipient(recipient_id)
        if recipient is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        row = self.repo.get_contract(recipient_id, contract_id)
        if row is None:
            raise domain_error("CONTRACT_NOT_FOUND", 404)
        by_id, _, group_by_type = self._service_meta()
        return self._to_response(row, by_id=by_id, group_by_type=group_by_type)

    def create_contract(
        self,
        recipient_id: int,
        payload: ContractCreateRequest,
        account: CurrentAccount,
    ) -> ContractResponse:
        if payload.end_date is not None and payload.start_date > payload.end_date:
            raise domain_error("VALIDATION_ERROR", 422, field="end_date")
        try:
            recipient = self.repo.get_recipient_for_update(recipient_id)
            if recipient is None:
                raise domain_error("RECIPIENT_NOT_FOUND", 404)
            by_id, by_code, group_by_type = self._service_meta()
            st = by_code.get(payload.service_type_code.value)
            if st is None or not st.active:
                raise domain_error("SERVICE_TYPE_NOT_FOUND", 422, field="service_type_code")

            issue_no = recipient.recipient_no is None
            counter = None
            if issue_no:
                counter = self.repo.lock_or_create_recipient_no_counter()

            now = self._now()
            row = RecipientContract(
                recipient_id=recipient_id,
                service_type_id=st.id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                service_start_date=payload.service_start_date,
                end_reason_text=payload.end_reason_text,
                signer_name=payload.signer_name,
                signer_relationship_text=payload.signer_relationship_text,
                signer_phone=payload.signer_phone,
                invalidated_at_utc=None,
                replacement_contract_id=None,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                created_at_utc=now,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(row)
            self._flush()
            w1d_fault.raise_if("after_contract_insert")

            if issue_no and counter is not None:
                counter.last_sequence = int(counter.last_sequence) + 1
                assigned = f"{counter.last_sequence:06d}"
                recipient.recipient_no = assigned
                recipient.updated_by_account_id = account.id
                recipient.updated_at_utc = now
                recipient.row_version = int(recipient.row_version) + 1
                self._flush()
                self.repo.append_audit(
                    actor_account_id=account.id,
                    action_code="RECIPIENT_NO_ASSIGN",
                    entity_type="RECIPIENT",
                    entity_pk=recipient_id,
                    before_json={"recipient_no": None},
                    after_json={"recipient_no": assigned},
                    reason_code="FIRST_CONTRACT",
                    request_id=self.request_id,
                    occurred_at_utc=now,
                )

            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="RECIPIENT_CONTRACT_CREATE",
                entity_type="RECIPIENT_CONTRACT",
                entity_pk=row.id,
                before_json=None,
                after_json={
                    "id": row.id,
                    "recipient_id": recipient_id,
                    "service_type_code": st.code,
                    "start_date": payload.start_date.isoformat(),
                    "end_date": (payload.end_date.isoformat() if payload.end_date else None),
                },
                reason_code="USER_CREATE",
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._flush()
            self._commit()
            return self._to_response(row, by_id=by_id, group_by_type=group_by_type)
        except Exception:
            if self.session.in_transaction():
                try:
                    self.session.rollback()
                except Exception:
                    pass
            raise

    def end_contract(
        self,
        recipient_id: int,
        contract_id: int,
        payload: ContractEndRequest,
        account: CurrentAccount,
    ) -> ContractResponse:
        try:
            recipient = self.repo.get_recipient_for_update(recipient_id)
            if recipient is None:
                raise domain_error("RECIPIENT_NOT_FOUND", 404)
            row = self.repo.get_contract(recipient_id, contract_id)
            if row is None or row.invalidated_at_utc is not None:
                raise domain_error("CONTRACT_NOT_FOUND", 404)
            if row.row_version != payload.expected_row_version:
                raise domain_error("ROW_VERSION_CONFLICT", 409)
            if row.end_date is not None:
                raise domain_error("CONTRACT_REACTIVATION_FORBIDDEN", 409)
            if payload.end_date < row.start_date:
                raise domain_error("VALIDATION_ERROR", 422, field="end_date")
            now = self._now()
            before = {"end_date": None, "row_version": row.row_version}
            row.end_date = payload.end_date
            row.end_reason_text = payload.end_reason_text
            row.updated_by_account_id = account.id
            row.updated_at_utc = now
            row.row_version = int(row.row_version) + 1
            self._flush()
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="RECIPIENT_CONTRACT_END",
                entity_type="RECIPIENT_CONTRACT",
                entity_pk=row.id,
                before_json=before,
                after_json={
                    "end_date": payload.end_date.isoformat(),
                    "row_version": row.row_version,
                },
                reason_code="USER_END",
                request_id=self.request_id,
                occurred_at_utc=now,
            )
            self._flush()
            self._commit()
            by_id, _, group_by_type = self._service_meta()
            return self._to_response(row, by_id=by_id, group_by_type=group_by_type)
        except Exception:
            if self.session.in_transaction():
                try:
                    self.session.rollback()
                except Exception:
                    pass
            raise

    def _active_ltc_contracts(
        self,
        contracts: list[RecipientContract],
        by_id: dict[int, ServiceType],
        group_by_type: dict[int, str],
    ) -> list[RecipientContract]:
        return [
            c
            for c in contracts
            if c.invalidated_at_utc is None
            and c.end_date is None
            and group_by_type.get(c.service_type_id) == LTC_GROUP_CODE
        ]

    @staticmethod
    def _date_str(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        text = str(value)
        return text[:10] if len(text) >= 10 else text

    @staticmethod
    def _effective_periods(rows: list[Any], proposed_end: date) -> list[Any]:
        """Rows effective on proposed_end (inclusive) — mutation/hash targets.

        Only periods effective on proposed_end (= new_start_date - 1 day) are
        ended/affected: row.start_date <= proposed_end and (row.end_date is None
        or row.end_date >= proposed_end). Older historical rows that already end
        before proposed_end stay byte-for-byte unchanged. Locking still covers
        the full non-invalidated sets for concurrency (callers decide).
        """
        return [
            r
            for r in rows
            if r.start_date <= proposed_end and (r.end_date is None or r.end_date >= proposed_end)
        ]

    def _build_hash_projection(
        self,
        *,
        recipient: Any,
        identity: Any,
        recipient_id: int,
        identity_number: str | None,
        certs: list[RecipientCertificationPeriod],
        grades: list[RecipientGradePeriod],
        ltc: list[RecipientContract],
        by_id: dict[int, ServiceType],
        group_by_type: dict[int, str],
        transition: dict[str, Any],
        replacements_non_sensitive: list[dict[str, Any]],
    ) -> str:
        """Plan §2.3 / DB §10.1 PII-free canonical preview_hash projection.

        Binds recipient/identity aggregate row_version+updated_at_utc, active
        cert/grade/LTC rows (id ASC) with replacement FKs and updated_at_utc,
        per-row service_type_code/service_group_code (never numeric service_type_id
        as the semantic code), sorted multiset, transition, and sorted
        non-sensitive replacements.
        """

        def _canon_value(field: str, value: Any) -> Any:
            if field.endswith("_at_utc"):
                return canonicalize_utc_timestamp(value if isinstance(value, datetime) else value)
            if field.endswith("date") or field in {
                "start_date",
                "end_date",
                "service_start_date",
            }:
                return canonicalize_date(value)
            if field in {
                "id",
                "row_version",
                "certification_period_id",
                "replacement_contract_id",
            } or field.endswith("_id"):
                if value is None:
                    return None
                if type(value) is bool:
                    raise TypeError(f"bool not allowed for {field}")
                return int(value)
            return value

        # Active rows defensive ID ASC (callers already order; enforce contract).
        certs_sorted = sorted(certs, key=lambda r: int(r.id))
        grades_sorted = sorted(grades, key=lambda r: int(r.id))
        ltc_sorted = sorted(ltc, key=lambda r: int(r.id))

        cert_rows: list[dict[str, Any]] = []
        for cert_row in certs_sorted:
            cert_rows.append(
                {
                    "id": _canon_value("id", cert_row.id),
                    "start_date": _canon_value("start_date", cert_row.start_date),
                    "end_date": _canon_value("end_date", cert_row.end_date),
                    "row_version": _canon_value("row_version", cert_row.row_version),
                    "invalidated_at_utc": _canon_value(
                        "invalidated_at_utc", cert_row.invalidated_at_utc
                    ),
                    "replacement_certification_period_id": _canon_value(
                        "replacement_certification_period_id",
                        cert_row.replacement_certification_period_id,
                    ),
                    "updated_at_utc": _canon_value("updated_at_utc", cert_row.updated_at_utc),
                }
            )

        grade_rows: list[dict[str, Any]] = []
        for grade_row in grades_sorted:
            grade_rows.append(
                {
                    "id": _canon_value("id", grade_row.id),
                    "certification_period_id": _canon_value(
                        "certification_period_id", grade_row.certification_period_id
                    ),
                    "grade_code": str(grade_row.grade_code),
                    "start_date": _canon_value("start_date", grade_row.start_date),
                    "end_date": _canon_value("end_date", grade_row.end_date),
                    "row_version": _canon_value("row_version", grade_row.row_version),
                    "invalidated_at_utc": _canon_value(
                        "invalidated_at_utc", grade_row.invalidated_at_utc
                    ),
                    "replacement_grade_period_id": _canon_value(
                        "replacement_grade_period_id",
                        grade_row.replacement_grade_period_id,
                    ),
                    "updated_at_utc": _canon_value("updated_at_utc", grade_row.updated_at_utc),
                }
            )

        contract_rows: list[dict[str, Any]] = []
        multiset: list[str] = []
        for contract_row in ltc_sorted:
            st = by_id.get(contract_row.service_type_id)
            code = st.code if st is not None else None
            group = group_by_type.get(contract_row.service_type_id)
            if code is None:
                raise ValueError("missing service_type_code for LTC contract")
            multiset.append(code)
            contract_rows.append(
                {
                    "id": _canon_value("id", contract_row.id),
                    "service_type_code": code,
                    "service_group_code": group,
                    "start_date": _canon_value("start_date", contract_row.start_date),
                    "end_date": _canon_value("end_date", contract_row.end_date),
                    "service_start_date": _canon_value(
                        "service_start_date", contract_row.service_start_date
                    ),
                    "row_version": _canon_value("row_version", contract_row.row_version),
                    "invalidated_at_utc": _canon_value(
                        "invalidated_at_utc", contract_row.invalidated_at_utc
                    ),
                    "replacement_contract_id": _canon_value(
                        "replacement_contract_id",
                        contract_row.replacement_contract_id,
                    ),
                    "updated_at_utc": _canon_value("updated_at_utc", contract_row.updated_at_utc),
                }
            )

        recipient_aggregate = {
            "id": _canon_value("id", recipient.id),
            "row_version": _canon_value("row_version", recipient.row_version),
            "updated_at_utc": _canon_value("updated_at_utc", recipient.updated_at_utc),
        }
        identity_aggregate = {
            "recipient_id": _canon_value("recipient_id", identity.recipient_id),
            "certification_number": identity_number,
            "row_version": _canon_value("row_version", identity.row_version),
            "updated_at_utc": _canon_value("updated_at_utc", identity.updated_at_utc),
        }

        projection = build_canonical_projection(
            recipient_id=recipient_id,
            certification_number=identity_number,
            recipient_aggregate=recipient_aggregate,
            identity_aggregate=identity_aggregate,
            certification_periods=cert_rows,
            grade_periods=grade_rows,
            contracts=contract_rows,
            service_multiset=multiset,
            transition=transition,
            replacements_non_sensitive=replacements_non_sensitive,
        )
        return sha256_canonical(projection)

    def _audit_projection(
        self,
        recipient_id: int,
        *,
        preview_hash: str,
        include_new_ids: bool,
        new_cert_id: int | None = None,
        new_grade_id: int | None = None,
        new_contract_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Exact schema matching tests._canonical_transition_projection."""
        by_id, _, group_by_type = self._service_meta()
        cert_rows = list(
            self.session.scalars(
                select(RecipientCertificationPeriod)
                .where(RecipientCertificationPeriod.recipient_id == recipient_id)
                .order_by(RecipientCertificationPeriod.id)
            ).all()
        )
        grade_rows = list(
            self.session.scalars(
                select(RecipientGradePeriod)
                .where(RecipientGradePeriod.recipient_id == recipient_id)
                .order_by(RecipientGradePeriod.id)
            ).all()
        )
        contract_rows = list(
            self.session.scalars(
                select(RecipientContract)
                .where(RecipientContract.recipient_id == recipient_id)
                .order_by(RecipientContract.id)
            ).all()
        )
        certs = [
            {
                "id": r.id,
                "start_date": self._date_str(r.start_date),
                "end_date": self._date_str(r.end_date),
                "row_version": r.row_version,
            }
            for r in cert_rows
        ]
        grades = [
            {
                "id": r.id,
                "certification_period_id": r.certification_period_id,
                "grade_code": r.grade_code,
                "start_date": self._date_str(r.start_date),
                "end_date": self._date_str(r.end_date),
                "row_version": r.row_version,
            }
            for r in grade_rows
        ]
        contracts = []
        for r in contract_rows:
            st = by_id.get(r.service_type_id)
            contracts.append(
                {
                    "id": r.id,
                    "service_type_code": st.code if st else "",
                    "service_group_code": group_by_type.get(r.service_type_id) or None,
                    "start_date": self._date_str(r.start_date),
                    "end_date": self._date_str(r.end_date),
                    "row_version": r.row_version,
                }
            )
        active = [r for r in contract_rows if r.invalidated_at_utc is None]
        multiset = sorted(
            by_id[r.service_type_id].code for r in active if r.service_type_id in by_id
        )
        projection: dict[str, Any] = {
            "preview_hash": preview_hash,
            "certification_periods": certs,
            "grade_periods": grades,
            "contracts": contracts,
            "service_multiset": multiset,
        }
        if include_new_ids:
            projection["new_ids"] = {
                "certification_period_id": new_cert_id,
                "grade_period_id": new_grade_id,
                "contract_ids": list(new_contract_ids or []),
            }
        return projection

    def preview_certification_transition(
        self,
        recipient_id: int,
        payload: CertificationTransitionPreviewRequest,
        account: CurrentAccount,
    ) -> CertificationTransitionPreviewResponse:
        del account
        recipient = self.repo.get_recipient(recipient_id)
        if recipient is None:
            raise domain_error("RECIPIENT_NOT_FOUND", 404)
        identity = self.repo.get_identity(recipient_id)
        if identity is None:
            raise domain_error("CERTIFICATION_IDENTITY_NOT_FOUND", 404)

        by_id, _, group_by_type = self._service_meta()
        certs = list(
            self.session.scalars(
                select(RecipientCertificationPeriod)
                .where(
                    RecipientCertificationPeriod.recipient_id == recipient_id,
                    RecipientCertificationPeriod.invalidated_at_utc.is_(None),
                )
                .order_by(RecipientCertificationPeriod.id)
            ).all()
        )
        grades = list(
            self.session.scalars(
                select(RecipientGradePeriod)
                .where(
                    RecipientGradePeriod.recipient_id == recipient_id,
                    RecipientGradePeriod.invalidated_at_utc.is_(None),
                )
                .order_by(RecipientGradePeriod.id)
            ).all()
        )
        contracts = list(
            self.session.scalars(
                select(RecipientContract)
                .where(
                    RecipientContract.recipient_id == recipient_id,
                    RecipientContract.invalidated_at_utc.is_(None),
                )
                .order_by(RecipientContract.id)
            ).all()
        )
        proposed_end = payload.new_start_date - timedelta(days=1)
        certs = self._effective_periods(certs, proposed_end)
        grades = self._effective_periods(grades, proposed_end)
        ltc = self._active_ltc_contracts(contracts, by_id, group_by_type)
        ltc = self._effective_periods(ltc, proposed_end)
        self._validate_replacement_multiset(ltc, payload.replacement_contracts, by_id)

        replacements = [item.model_dump(mode="json") for item in payload.replacement_contracts]
        # Canonical ended_contract_id ASC for hash, token, and preview output.
        bound = full_bound_replacements(replacements)
        non_sens = non_sensitive_replacements(replacements)
        transition = {
            "new_start_date": payload.new_start_date.isoformat(),
            "new_end_date": payload.new_end_date.isoformat(),
            "new_grade_code": payload.new_grade_code.value,
            "new_grade_start_date": payload.new_grade_start_date.isoformat(),
            "new_grade_end_date": payload.new_grade_end_date.isoformat(),
        }
        preview_hash = self._build_hash_projection(
            recipient=recipient,
            identity=identity,
            recipient_id=recipient_id,
            identity_number=identity.certification_number,
            certs=certs,
            grades=grades,
            ltc=ltc,
            by_id=by_id,
            group_by_type=group_by_type,
            transition=transition,
            replacements_non_sensitive=non_sens,
        )
        multiset = sorted(by_id[c.service_type_id].code for c in ltc if c.service_type_id in by_id)
        token = mint_preview_token(
            key=self._token_key(),
            recipient_id=recipient_id,
            preview_hash=preview_hash,
            bound_replacements=bound,
            transition=transition,
        )
        return CertificationTransitionPreviewResponse(
            preview_token=token,
            canonical_hash=preview_hash,
            serialization_version=SERIALIZATION_VERSION,
            proposed_end_date=proposed_end,
            affected_certification_period_ids=[c.id for c in certs],
            affected_grade_period_ids=[g.id for g in grades],
            affected_contract_ids=[c.id for c in ltc],
            service_multiset=multiset,
            replacement_preview=[
                ReplacementPreviewItem(
                    ended_contract_id=int(item["ended_contract_id"]),
                    service_type_code=str(item["service_type_code"]),
                    start_date=date.fromisoformat(str(item["start_date"]))
                    if not isinstance(item["start_date"], date)
                    else item["start_date"],
                    end_date=(
                        None
                        if item.get("end_date") is None
                        else (
                            item["end_date"]
                            if isinstance(item["end_date"], date)
                            else date.fromisoformat(str(item["end_date"]))
                        )
                    ),
                )
                for item in bound
            ],
        )

    def _validate_replacement_multiset(
        self,
        ltc: list[RecipientContract],
        replacements: list[TransitionReplacementItem],
        by_id: dict[int, ServiceType],
    ) -> None:
        if len(replacements) != len(ltc):
            raise domain_error("CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH", 422)
        ltc_by_id = {c.id: c for c in ltc}
        used: set[int] = set()
        for item in replacements:
            row = ltc_by_id.get(item.ended_contract_id)
            if row is None or item.ended_contract_id in used:
                raise domain_error("CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH", 422)
            used.add(item.ended_contract_id)
            st = by_id.get(row.service_type_id)
            if st is None or st.code != item.service_type_code.value:
                raise domain_error("CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH", 422)

    def apply_certification_transition(
        self,
        recipient_id: int,
        payload: CertificationTransitionApplyRequest,
        account: CurrentAccount,
    ) -> CertificationTransitionApplyResponse:
        # Exact apply precedence (plan §2.3 / AUDIT-036).
        if payload.confirmed is not True:
            raise domain_error("CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED", 422)
        token_raw = payload.preview_token
        if token_raw is None or not str(token_raw).strip():
            raise domain_error("CERTIFICATION_TRANSITION_PREVIEW_REQUIRED", 422)

        try:
            recipient = self.repo.get_recipient_for_update(recipient_id)
            if recipient is None:
                raise domain_error("RECIPIENT_NOT_FOUND", 404)
            identity = self.repo.get_identity_for_update(recipient_id)
            if identity is None:
                raise domain_error("CERTIFICATION_IDENTITY_NOT_FOUND", 404)

            token_body = verify_preview_token(
                key=self._token_key(),
                token=str(token_raw).strip(),
                recipient_id=recipient_id,
            )
            if token_body is None:
                raise domain_error("CERTIFICATION_TRANSITION_TOKEN_INVALID", 422)

            # Parse the signed transition dates early: proposed_end
            # (= new_start_date - 1 day) defines the effective-on-proposed-end
            # target rows for both hash recomputation and mutation below.
            # This stays inside the sealed token-verification region; a malformed
            # signed body is TOKEN_INVALID before any STALE / MISMATCH decision.
            try:
                bound = token_body["bound_replacements"]
                transition = token_body["transition"]
                if type(bound) is not list or type(transition) is not dict:
                    raise TypeError("token body structure")
                new_start = date.fromisoformat(str(transition["new_start_date"]))
                new_end = date.fromisoformat(str(transition["new_end_date"]))
                new_grade_code = str(transition["new_grade_code"])
                new_grade_start = date.fromisoformat(str(transition["new_grade_start_date"]))
                new_grade_end = date.fromisoformat(str(transition["new_grade_end_date"]))
                proposed_end = new_start - timedelta(days=1)
            except (KeyError, TypeError, ValueError) as exc:
                raise domain_error("CERTIFICATION_TRANSITION_TOKEN_INVALID", 422) from exc

            by_id, by_code, group_by_type = self._service_meta()
            # Lock the full non-invalidated sets (concurrency), but define hash
            # and mutation target rows as only the periods effective on
            # proposed_end so older history is never rewritten.
            certs_all = self.repo.list_active_cert_periods_for_update(recipient_id)
            grades_all = self.repo.list_active_grade_periods_for_update(recipient_id)
            contracts_all = self.repo.list_active_contracts_for_update(recipient_id)
            ltc_all = self._active_ltc_contracts(contracts_all, by_id, group_by_type)
            certs = self._effective_periods(certs_all, proposed_end)
            grades = self._effective_periods(grades_all, proposed_end)
            ltc = self._effective_periods(ltc_all, proposed_end)

            w1d_fault.raise_if("after_lock")

            # STALE: current locked DB + SIGNED token-bound non-sensitive
            # replacements + signed transition only (never request replacements).
            try:
                non_sens = non_sensitive_replacements(bound)
                recomputed = self._build_hash_projection(
                    recipient=recipient,
                    identity=identity,
                    recipient_id=recipient_id,
                    identity_number=identity.certification_number,
                    certs=certs,
                    grades=grades,
                    ltc=ltc,
                    by_id=by_id,
                    group_by_type=group_by_type,
                    transition=transition,
                    replacements_non_sensitive=non_sens,
                )
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise domain_error("CERTIFICATION_TRANSITION_TOKEN_INVALID", 422) from exc

            if not constant_time_hash_equal(recomputed, str(token_body.get("preview_hash", ""))):
                raise domain_error("CERTIFICATION_TRANSITION_STALE", 409)
            w1d_fault.raise_if("after_hash")

            # Only after STALE: full request vs token-bound MISMATCH.
            # Canonicalize both sides (ended_contract_id ASC) so semantic
            # permutations compare equal while multiset/id rules still hold.
            apply_items = full_bound_replacements(
                [item.model_dump(mode="json") for item in payload.replacement_contracts]
            )
            bound_norm = full_bound_replacements(list(bound))
            if not replacements_exact_equal(apply_items, bound_norm):
                raise domain_error("CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH", 422)
            self._validate_replacement_multiset(ltc, payload.replacement_contracts, by_id)

            # After STALE + MISMATCH: semantic revalidation of signed transition
            # and request/bound replacement periods (write-zero on failure).
            try:
                rep_starts: list[date] = []
                rep_ends: list[date | None] = []
                for item in payload.replacement_contracts:
                    rep_starts.append(item.start_date)
                    rep_ends.append(item.end_date)
                validate_transition_period_semantics(
                    new_start_date=new_start,
                    new_end_date=new_end,
                    new_grade_start_date=new_grade_start,
                    new_grade_end_date=new_grade_end,
                    replacement_starts=rep_starts,
                    replacement_ends=rep_ends,
                )
            except ValueError as exc:
                raise domain_error(
                    "VALIDATION_ERROR",
                    422,
                    details={"reason": str(exc)},
                ) from exc

            authorized_hash = str(token_body["preview_hash"])
            # Capture BEFORE projection before any mutation.
            before_proj = self._audit_projection(
                recipient_id,
                preview_hash=authorized_hash,
                include_new_ids=False,
            )

            correlation = self.request_id or uuid4()
            now = self._now()

            # End grades first (B1), then certs, then contracts.
            ended_grade_ids: list[int] = []
            for grade in grades:
                grade.end_date = proposed_end
                grade.updated_by_account_id = account.id
                grade.updated_at_utc = now
                grade.row_version = int(grade.row_version) + 1
                ended_grade_ids.append(grade.id)
            self._flush()
            w1d_fault.raise_if("after_end_grade")

            ended_cert_ids: list[int] = []
            for cert in certs:
                cert.end_date = proposed_end
                cert.updated_by_account_id = account.id
                cert.updated_at_utc = now
                cert.row_version = int(cert.row_version) + 1
                ended_cert_ids.append(cert.id)
            self._flush()
            w1d_fault.raise_if("after_end_cert")

            ended_contract_ids: list[int] = []
            for contract in ltc:
                contract.end_date = proposed_end
                contract.updated_by_account_id = account.id
                contract.updated_at_utc = now
                contract.row_version = int(contract.row_version) + 1
                ended_contract_ids.append(contract.id)
            self._flush()
            w1d_fault.raise_if("after_end_contracts")

            new_cert = RecipientCertificationPeriod(
                recipient_id=recipient_id,
                start_date=new_start,
                end_date=new_end,
                invalidated_at_utc=None,
                replacement_certification_period_id=None,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                created_at_utc=now,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(new_cert)
            self._flush()
            w1d_fault.raise_if("after_create_cert")

            new_grade = RecipientGradePeriod(
                recipient_id=recipient_id,
                certification_period_id=new_cert.id,
                grade_code=new_grade_code,
                start_date=new_grade_start,
                end_date=new_grade_end,
                invalidated_at_utc=None,
                replacement_grade_period_id=None,
                created_by_account_id=account.id,
                updated_by_account_id=account.id,
                created_at_utc=now,
                updated_at_utc=now,
                row_version=1,
            )
            self.session.add(new_grade)
            self._flush()
            w1d_fault.raise_if("after_create_grade")

            new_contract_ids: list[int] = []
            for item in payload.replacement_contracts:
                st = by_code[item.service_type_code.value]
                nrow = RecipientContract(
                    recipient_id=recipient_id,
                    service_type_id=st.id,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    service_start_date=item.service_start_date,
                    end_reason_text=item.end_reason_text,
                    signer_name=item.signer_name,
                    signer_relationship_text=item.signer_relationship_text,
                    signer_phone=item.signer_phone,
                    invalidated_at_utc=None,
                    replacement_contract_id=None,
                    created_by_account_id=account.id,
                    updated_by_account_id=account.id,
                    created_at_utc=now,
                    updated_at_utc=now,
                    row_version=1,
                )
                self.session.add(nrow)
                self._flush()
                # Transition is not a history-correction replacement: leave old
                # replacement_contract_id / cert / grade replacement FKs unchanged.
                new_contract_ids.append(nrow.id)
            w1d_fault.raise_if("after_create_contracts")

            after_proj = self._audit_projection(
                recipient_id,
                preview_hash=authorized_hash,
                include_new_ids=True,
                new_cert_id=new_cert.id,
                new_grade_id=new_grade.id,
                new_contract_ids=list(new_contract_ids),
            )
            self.repo.append_audit(
                actor_account_id=account.id,
                action_code="CERTIFICATION_TRANSITION_APPLY",
                entity_type="RECIPIENT",
                entity_pk=recipient_id,
                before_json=before_proj,
                after_json=after_proj,
                reason_code="USER_CONFIRMED_TRANSITION",
                request_id=correlation,
                occurred_at_utc=now,
            )
            self._flush()
            w1d_fault.raise_if("after_audit")
            w1d_fault.raise_if("before_commit")
            self._commit()

            rno = recipient.recipient_no
            if type(rno) is not str or not rno:
                rno = ""

            return CertificationTransitionApplyResponse(
                recipient_id=recipient_id,
                ended_certification_period_ids=ended_cert_ids,
                ended_grade_period_ids=ended_grade_ids,
                ended_contract_ids=ended_contract_ids,
                new_certification_period_id=new_cert.id,
                new_grade_period_id=new_grade.id,
                new_contract_ids=new_contract_ids,
                audit_correlation_id=correlation,
                recipient_no=rno,
            )
        except Exception:
            if self.session.in_transaction():
                try:
                    self.session.rollback()
                except Exception:
                    pass
            raise
