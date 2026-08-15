from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.db.models import Recipient
from app.domains.recipient.schemas import (
    RecipientCreateRequest,
    RecipientInputSexCode,
    RecipientSexCode,
    RecipientUpdateRequest,
)
from app.domains.recipient.service import RecipientService


def test_recipient_test_sex_code_is_response_only_and_round_trips() -> None:
    payload = RecipientCreateRequest(
        name="일반 수급자",
        birth_date=date(1990, 1, 1),
        sex_code=RecipientInputSexCode.FEMALE,
        mobile_phone="010-0000-0000",
    )
    assert payload.sex_code is RecipientInputSexCode.FEMALE

    with pytest.raises(ValidationError):
        RecipientCreateRequest(
            name="합성 수급자",
            birth_date=date(1990, 1, 1),
            sex_code="TEST",
            mobile_phone="010-0000-0000",
        )
    with pytest.raises(ValidationError):
        RecipientUpdateRequest(expected_row_version=1, sex_code="TEST")

    now = datetime.now(UTC)
    recipient = Recipient(
        id=1,
        name=payload.name,
        birth_date=payload.birth_date,
        sex_code=RecipientSexCode.TEST.value,
        recipient_status="ACTIVE",
        recipient_no=None,
        memo=None,
        postal_code=None,
        address=None,
        mobile_phone=payload.mobile_phone,
        payer_guardian_id=None,
        created_by_account_id=1,
        created_at_utc=now,
        updated_by_account_id=1,
        updated_at_utc=now,
        row_version=1,
    )

    response = RecipientService._recipient_response(recipient)
    assert response.sex_code is RecipientSexCode.TEST
