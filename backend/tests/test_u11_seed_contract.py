from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.core.auth import CurrentAccount
from app.db import seed_dev_recipients, seed_extreme_test_data
from app.db.models import Recipient, RecipientCertificationPeriod, RecipientContract
from app.domains.w1c.schemas import CertificationPeriodCreateRequest


class RecordingSession:
    def __init__(self) -> None:
        self.objects: list[object] = []

    def add(self, value: object) -> None:
        self.objects.append(value)

    def flush(self) -> None:
        return None


def test_dev_recipient_seed_matches_current_recipient_and_benefit_shapes() -> None:
    today = date(2026, 8, 15)
    payload = seed_dev_recipients._build_batch_request(0)

    recipient_data = payload.recipient.model_dump()
    assert "home_phone" not in recipient_data
    assert recipient_data["mobile_phone"]

    benefit_payload = seed_dev_recipients._build_benefit_request(0, today=today)
    assert benefit_payload.start_text == (date(2026, 7, 16)).isoformat()
    assert "start_date" not in benefit_payload.model_dump()
    assert "end_date" not in benefit_payload.model_dump()


def test_extreme_seed_matches_current_recipient_contract_shapes() -> None:
    session = RecordingSession()
    recipient = seed_extreme_test_data._add_recipient(
        session,
        account_id=1,
        service_type_id=2,
        name_index=0,
        sequence=1,
        ended=False,
    )

    saved_recipient = next(value for value in session.objects if isinstance(value, Recipient))
    saved_contract = next(
        value for value in session.objects if isinstance(value, RecipientContract)
    )
    saved_certification = next(
        value for value in session.objects if isinstance(value, RecipientCertificationPeriod)
    )
    assert saved_recipient is recipient
    assert saved_recipient.mobile_phone == "010-9000-0501"
    assert not hasattr(saved_recipient, "home_phone")
    assert saved_contract.service_start_date == date(2026, 1, 1)
    assert saved_certification.grade_code == "1"
    assert not hasattr(saved_contract, "signer_name")
    assert not hasattr(saved_contract, "signer_relationship_text")
    assert not hasattr(saved_contract, "signer_phone")


def test_dev_seed_places_grade_on_current_certification_period_request() -> None:
    class RecordingW1C:
        def __init__(self) -> None:
            self.certification_payload: CertificationPeriodCreateRequest | None = None

        def create_identity(
            self, recipient_id: int, payload: object, account: CurrentAccount
        ) -> None:
            return None

        def create_certification_period(
            self,
            recipient_id: int,
            payload: CertificationPeriodCreateRequest,
            account: CurrentAccount,
        ) -> SimpleNamespace:
            self.certification_payload = payload
            return SimpleNamespace(id=1)

        def create_grade_period(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("grade must be part of the certification period request")

    service = RecordingW1C()
    seed_dev_recipients._attach_certification_and_grade(
        w1c_service=service,
        recipient_id=1,
        index=0,
        today=date(2026, 8, 15),
        current_account=CurrentAccount(1, "seed", "ADMIN"),
    )

    assert service.certification_payload is not None
    assert service.certification_payload.grade_code.value == "1"
