"""Canonical transition projection, hash, and HMAC preview token."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from app.domains.w1d.clock import now_utc

SERIALIZATION_VERSION = "w1d-transition-v1"
TOKEN_TTL = timedelta(minutes=30)


def _json_default(value: Any) -> Any:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return canonicalize_utc_timestamp(value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"non-canonical type: {type(value)!r}")


def canonicalize_date(value: date | datetime | str | None) -> str | None:
    """Dates as exact YYYY-MM-DD; null stays null."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def canonicalize_utc_timestamp(value: datetime | str | None) -> str | None:
    """Single UTC representation for timestamps; null stays null.

    Accepts datetime or ISO-8601 strings (including trailing uppercase Z and
    standard offset forms). Every accepted instant is normalized to UTC and
    emitted exactly as ``...+00:00`` (never Z, never a passthrough string).
    Naive datetimes are treated as already-UTC. Invalid strings fail closed.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("invalid timestamp string: empty")
        # Python fromisoformat accepts +00:00 offsets; map trailing Z first.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"invalid timestamp string: {value!r}") from exc
        if type(parsed) is not datetime:
            raise ValueError(f"invalid timestamp string: {value!r}")
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    # Force a single offset form: never leave a trailing Z from platform quirks.
    out = value.isoformat()
    if out.endswith("Z"):
        out = out[:-1] + "+00:00"
    return out


def sha256_canonical(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_canonical_projection(
    *,
    recipient_id: int,
    certification_number: str | None,
    recipient_aggregate: dict[str, Any],
    identity_aggregate: dict[str, Any],
    certification_periods: list[dict[str, Any]],
    grade_periods: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    service_multiset: list[str],
    transition: dict[str, Any],
    replacements_non_sensitive: list[dict[str, Any]],
) -> dict[str, Any]:
    """PII-free deterministic preview_hash input (plan §2.3 / DB doc §10.1)."""
    return {
        "v": SERIALIZATION_VERSION,
        "recipient_id": recipient_id,
        "certification_number": certification_number,
        "recipient_aggregate": recipient_aggregate,
        "identity_aggregate": identity_aggregate,
        "certification_periods": certification_periods,
        "grade_periods": grade_periods,
        "contracts": contracts,
        "service_multiset": sorted(service_multiset),
        "transition": transition,
        "replacements": replacements_non_sensitive,
    }


def _ended_contract_id_key(item: dict[str, Any]) -> int:
    raw = item.get("ended_contract_id")
    if type(raw) is bool or raw is None:
        raise TypeError("ended_contract_id must be a positive int")
    return int(raw)


def sort_replacements_by_ended_id(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Defensive stable sort: ended_contract_id ASC (token / hash contract)."""
    return sorted(items, key=_ended_contract_id_key)


def non_sensitive_replacements(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalized non-sensitive replacement projection, ended_contract_id ASC."""
    out: list[dict[str, Any]] = []
    for item in sort_replacements_by_ended_id(items):
        out.append(
            {
                "ended_contract_id": int(item["ended_contract_id"]),
                "service_type_code": item["service_type_code"],
                "start_date": item["start_date"],
                "end_date": item.get("end_date"),
                "service_start_date": item.get("service_start_date"),
            }
        )
    return out


def full_bound_replacements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Full bound replacement set for HMAC, ended_contract_id ASC."""
    keys = (
        "ended_contract_id",
        "service_type_code",
        "start_date",
        "end_date",
        "service_start_date",
        "signer_name",
        "signer_relationship_text",
        "signer_phone",
        "end_reason_text",
    )
    out: list[dict[str, Any]] = []
    for item in sort_replacements_by_ended_id(items):
        row: dict[str, Any] = {}
        for key in keys:
            row[key] = item.get(key)
        if row.get("ended_contract_id") is not None:
            row["ended_contract_id"] = int(row["ended_contract_id"])
        out.append(row)
    return out


def mint_preview_token(
    *,
    key: bytes,
    recipient_id: int,
    preview_hash: str,
    bound_replacements: list[dict[str, Any]],
    transition: dict[str, Any],
) -> str:
    exp = int((now_utc() + TOKEN_TTL).timestamp())
    body = {
        "v": SERIALIZATION_VERSION,
        "recipient_id": recipient_id,
        "preview_hash": preview_hash,
        "exp": exp,
        "bound_replacements": bound_replacements,
        "transition": transition,
    }
    payload = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    )


def _b64decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    decoded = base64.urlsafe_b64decode(segment + pad)
    # Reject non-canonical unpadded base64url: re-encode without padding
    # must match the original segment byte-for-byte.
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != segment:
        raise ValueError("non-canonical base64url")
    return decoded


def verify_preview_token(
    *,
    key: bytes,
    token: str,
    recipient_id: int,
) -> dict[str, Any] | None:
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64decode(payload_b64)
        sig = _b64decode(sig_b64)
    except Exception:
        return None
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        body = json.loads(payload.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    if body.get("v") != SERIALIZATION_VERSION:
        return None
    if body.get("recipient_id") != recipient_id:
        return None
    exp = body.get("exp")
    if type(exp) is not int:
        return None
    if int(now_utc().timestamp()) >= exp:
        return None
    ph = body.get("preview_hash")
    if type(ph) is not str or len(ph) != 64:
        return None
    if type(body.get("bound_replacements")) is not list:
        return None
    return body


def constant_time_hash_equal(left: str, right: str) -> bool:
    if type(left) is not str or type(right) is not str:
        return False
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def replacements_exact_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    if len(left) != len(right):
        return False
    return json.dumps(left, sort_keys=True, default=_json_default) == json.dumps(
        right, sort_keys=True, default=_json_default
    )
