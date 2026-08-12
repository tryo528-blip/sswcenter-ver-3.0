from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.settings import Environment, Settings, get_settings


@dataclass(frozen=True)
class EncryptedResidentNumber:
    ciphertext: bytes
    nonce: bytes
    key_version: int
    lookup_hmac: bytes


def _decode_key(value: str, *, setting_name: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError(f"{setting_name} must be valid base64") from exc
    if len(decoded) != 32:
        raise RuntimeError(f"{setting_name} must decode to exactly 32 bytes")
    return decoded


def _synthetic_key(settings: Settings, purpose: str) -> bytes:
    label = f"sswcenter-{settings.environment.value}-{purpose}-synthetic-only"
    return hashlib.sha256(label.encode("utf-8")).digest()


def _keyring(settings: Settings) -> tuple[dict[int, bytes], bytes, int]:
    configured_encryption_key = settings.resident_number_key_v1
    configured_lookup_key = settings.resident_number_lookup_key
    if configured_encryption_key is None:
        if settings.environment is Environment.PRODUCTION:
            raise RuntimeError("resident-number encryption key is required")
        encryption_key = _synthetic_key(settings, "resident-number-key-v1")
    else:
        encryption_key = _decode_key(
            configured_encryption_key.get_secret_value(),
            setting_name="SSWCENTER_RESIDENT_NUMBER_KEY_V1",
        )

    if configured_lookup_key is None:
        if settings.environment is Environment.PRODUCTION:
            raise RuntimeError("resident-number lookup key is required")
        lookup_key = _synthetic_key(settings, "resident-number-lookup-key")
    else:
        lookup_key = _decode_key(
            configured_lookup_key.get_secret_value(),
            setting_name="SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY",
        )
    return {1: encryption_key}, lookup_key, settings.resident_number_active_key_version


def _aad(staff_id: int, key_version: int) -> bytes:
    return f"staff:{staff_id}:resident-number:v{key_version}".encode()


def _is_ascii_resident_number(value: str) -> bool:
    return len(value) == 13 and value.isascii() and value.isdecimal()


def encrypt_resident_number(
    *,
    staff_id: int,
    resident_number: str,
    key_version: int | None = None,
    settings: Settings | None = None,
) -> EncryptedResidentNumber:
    active_settings = settings or get_settings()
    keys, lookup_key, active_version = _keyring(active_settings)
    selected_version = active_version if key_version is None else key_version
    key = keys.get(selected_version)
    if key is None:
        raise ValueError("W1A_SEM_CRYPTO_KEY_VERSION_MISSING")
    if not _is_ascii_resident_number(resident_number):
        raise ValueError("W1A_SEM_RRN_INVALID")

    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        resident_number.encode("ascii"),
        _aad(staff_id, selected_version),
    )
    lookup_hmac = hmac.new(
        lookup_key,
        resident_number.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return EncryptedResidentNumber(
        ciphertext=ciphertext,
        nonce=nonce,
        key_version=selected_version,
        lookup_hmac=lookup_hmac,
    )


def decrypt_resident_number(
    *,
    staff_id: int,
    ciphertext: bytes,
    nonce: bytes,
    key_version: int,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    keys, _, _ = _keyring(active_settings)
    key = keys.get(key_version)
    if key is None or len(nonce) != 12:
        raise ValueError("W1A_SEM_CRYPTO_AAD_MISMATCH")
    try:
        plaintext = AESGCM(key).decrypt(
            nonce,
            ciphertext,
            _aad(staff_id, key_version),
        )
        resident_number = plaintext.decode("ascii")
    except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("W1A_SEM_CRYPTO_AAD_MISMATCH") from exc
    if not _is_ascii_resident_number(resident_number):
        raise ValueError("W1A_SEM_CRYPTO_AAD_MISMATCH")
    return resident_number
