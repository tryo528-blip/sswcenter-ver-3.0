import pytest
from pydantic import BaseModel, ValidationError

from app.api.auth import BootstrapRequest, LoginRequest
from app.core.security import (
    PinProtector,
    csrf_token_signature,
    generate_csrf_token,
    generate_session_token,
    hash_session_token,
    validate_pin,
    verify_csrf_signature,
)
from app.domains.staff.schemas import SensitiveIdentityRevealRequest


@pytest.mark.parametrize("pin", ["12345", "1234567", "12a456", "１２３４５６", "123 456"])
def test_invalid_pin_is_rejected(pin: str) -> None:
    with pytest.raises(ValueError):
        validate_pin(pin)


def test_server_pin_request_schemas_require_exactly_six_ascii_digits() -> None:
    request_specs: tuple[tuple[type[BaseModel], dict[str, object], str], ...] = (
        (
            BootstrapRequest,
            {
                "center_name": "Test center",
                "admin_name": "Test admin",
                "birth_date": "1990-01-01",
                "sex_code": "TEST",
                "start_date": "2026-01-01",
            },
            "pin",
        ),
        (LoginRequest, {}, "pin"),
        (SensitiveIdentityRevealRequest, {}, "current_pin"),
    )

    for request_model, base_payload, field_name in request_specs:
        request_model.model_validate({**base_payload, field_name: "123456"})
        for invalid_pin in ("12345", "1234567", "１２３４５６"):
            with pytest.raises(ValidationError):
                request_model.model_validate({**base_payload, field_name: invalid_pin})


def test_pin_hash_and_lookup_do_not_store_plaintext() -> None:
    protector = PinProtector(pepper="development-pepper", lookup_key="lookup-key")

    stored_hash = protector.hash_pin("123456")
    lookup = protector.lookup_hmac("123456")

    assert "123456" not in stored_hash
    assert protector.verify_pin(stored_hash, "123456")
    assert not protector.verify_pin(stored_hash, "654321")
    assert lookup == protector.lookup_hmac("123456")


def test_session_and_csrf_tokens_are_rotatable() -> None:
    first_session = generate_session_token()
    second_session = generate_session_token()
    csrf_token = generate_csrf_token()
    signature = csrf_token_signature(first_session, csrf_token, "signing-key")

    assert first_session != second_session
    assert hash_session_token(first_session) != hash_session_token(second_session)
    assert verify_csrf_signature(first_session, csrf_token, signature, "signing-key")
    assert not verify_csrf_signature(second_session, csrf_token, signature, "signing-key")
