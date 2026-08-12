from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies import get_staff_service, require_staff_manage
from app.core.auth import CurrentAccount
from app.core.settings import Environment, Settings
from app.domains.staff.service import StaffService
from app.main import app


def _unicode_rrn_cases() -> list[str]:
    raw = "".join(("900101", "1123456"))
    all_unicode = raw.translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    mixed = raw.translate(
        str.maketrans({"1": "١"}),
    )
    return [
        all_unicode,
        f"{all_unicode[:6]}-{all_unicode[6:]}",
        mixed,
        f"{mixed[:6]}-{mixed[6:]}",
    ]


def _staff_create_payload(resident_number: str) -> dict[str, object]:
    return {
        "name": "Unicode RRN API test",
        "birth_date": "1990-01-01",
        "sex_code": "MALE",
        "resident_number": resident_number,
        "initial_employment": {"start_date": "2026-01-01"},
    }


@pytest.fixture(autouse=True)
def reset_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_unicode_resident_numbers_are_422_not_500() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    validation_only_service = StaffService(
        cast(Session, object()),
        Settings(environment=Environment.DEVELOPMENT),
    )
    app.dependency_overrides[get_staff_service] = lambda: validation_only_service
    app.dependency_overrides[require_staff_manage] = lambda: CurrentAccount(
        id=2,
        display_name="Manager",
        role_code="USER",
    )

    for resident_number in _unicode_rrn_cases():
        response = client.post(
            "/api/v1/staff",
            json=_staff_create_payload(resident_number),
        )

        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "RESIDENT_NUMBER_INVALID"
        assert resident_number not in response.text
