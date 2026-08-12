from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

PIN_PATTERN = re.compile(r"^[0-9]{6}$")


def validate_pin(pin: str) -> None:
    if PIN_PATTERN.fullmatch(pin) is None:
        raise ValueError("PIN must contain exactly 6 ASCII digits")


class PinProtector:
    def __init__(self, pepper: str, lookup_key: str) -> None:
        if not pepper or not lookup_key:
            raise ValueError("PIN pepper and lookup key are required")
        self._pepper = pepper
        self._lookup_key = lookup_key.encode("utf-8")
        self._hasher = PasswordHasher()

    def hash_pin(self, pin: str) -> str:
        validate_pin(pin)
        return self._hasher.hash(self._peppered(pin))

    def verify_pin(self, stored_hash: str, pin: str) -> bool:
        validate_pin(pin)
        try:
            return self._hasher.verify(stored_hash, self._peppered(pin))
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def lookup_hmac(self, pin: str) -> bytes:
        validate_pin(pin)
        return hmac.new(self._lookup_key, pin.encode("utf-8"), hashlib.sha256).digest()

    def _peppered(self, pin: str) -> str:
        return f"{pin}\x00{self._pepper}"


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_token_signature(session_token: str, csrf_token: str, signing_key: str) -> str:
    message = f"{session_token}\x00{csrf_token}".encode()
    return hmac.new(signing_key.encode(), message, hashlib.sha256).hexdigest()


def verify_csrf_signature(
    session_token: str,
    csrf_token: str,
    signature: str,
    signing_key: str,
) -> bool:
    expected = csrf_token_signature(session_token, csrf_token, signing_key)
    return hmac.compare_digest(expected, signature)
