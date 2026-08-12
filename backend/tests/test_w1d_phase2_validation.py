"""W1D Phase-2 P2A-R4/R5: focused no-DB period semantics + strict scalar validation.

Does not touch PostgreSQL. Exercises Pydantic preview/apply schemas and the pure
validate_transition_period_semantics helper used on the apply signed path.
Certification and grade ends are required finite dates; replacement-contract
ends remain nullable.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domains.w1d.schemas import (
    CertificationTransitionApplyRequest,
    CertificationTransitionPreviewRequest,
    ContractEndRequest,
    PositiveVersion,
    StrictBool,
    TransitionReplacementItem,
    validate_transition_period_semantics,
)


def _replacement(
    *,
    ended_contract_id: int = 1,
    service_type_code: str = "HOME_CARE",
    start_date: str = "2026-07-01",
    end_date: str | None = None,
) -> dict[str, Any]:
    return {
        "ended_contract_id": ended_contract_id,
        "service_type_code": service_type_code,
        "start_date": start_date,
        "end_date": end_date,
        "service_start_date": None,
        "signer_name": None,
        "signer_relationship_text": None,
        "signer_phone": None,
        "end_reason_text": None,
    }


def _valid_preview(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "new_start_date": "2026-07-01",
        "new_end_date": "2027-06-30",
        "new_grade_code": "4",
        "new_grade_start_date": "2026-07-01",
        "new_grade_end_date": "2027-06-30",
        "replacement_contracts": [_replacement()],
    }
    body.update(overrides)
    return body


def _valid_apply(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "preview_token": "token-for-schema-only",
        "confirmed": True,
        "replacement_contracts": [_replacement()],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Pure semantic helper (apply-side signed values probe)
# ---------------------------------------------------------------------------


def test_semantic_helper_accepts_canonical_finite_periods_and_open_replacements() -> None:
    validate_transition_period_semantics(
        new_start_date=date(2026, 7, 1),
        new_end_date=date(2027, 6, 30),
        new_grade_start_date=date(2026, 7, 1),
        new_grade_end_date=date(2027, 6, 30),
        replacement_starts=[date(2026, 7, 1)],
        replacement_ends=[None],
    )
    # Certification/grade ends remain finite while replacement contracts may be open.
    validate_transition_period_semantics(
        new_start_date=date(2026, 7, 1),
        new_end_date=date(2028, 6, 30),
        new_grade_start_date=date(2026, 7, 1),
        new_grade_end_date=date(2028, 6, 30),
        replacement_starts=[date(2026, 7, 1), date(2026, 7, 1)],
        replacement_ends=[None, date(2026, 12, 31)],
    )


def test_semantic_helper_accepts_finite_boundaries() -> None:
    # Grade may start at either certification boundary when its end remains contained.
    validate_transition_period_semantics(
        new_start_date=date(2026, 7, 1),
        new_end_date=date(2027, 6, 30),
        new_grade_start_date=date(2026, 7, 1),
        new_grade_end_date=date(2027, 6, 30),
        replacement_starts=[date(2026, 7, 1)],
        replacement_ends=[None],
    )
    validate_transition_period_semantics(
        new_start_date=date(2026, 7, 1),
        new_end_date=date(2027, 6, 30),
        new_grade_start_date=date(2027, 6, 30),
        new_grade_end_date=date(2027, 6, 30),
        replacement_starts=[date(2026, 7, 1)],
        replacement_ends=[None],
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        # Reversed certification
        {
            "new_start_date": date(2027, 1, 1),
            "new_end_date": date(2026, 1, 1),
            "new_grade_start_date": date(2027, 1, 1),
            "new_grade_end_date": date(2026, 6, 1),
            "replacement_starts": [date(2027, 1, 1)],
            "replacement_ends": [None],
        },
        # Reversed grade
        {
            "new_start_date": date(2026, 7, 1),
            "new_end_date": date(2027, 6, 30),
            "new_grade_start_date": date(2027, 1, 1),
            "new_grade_end_date": date(2026, 8, 1),
            "replacement_starts": [date(2026, 7, 1)],
            "replacement_ends": [None],
        },
        # Grade start before cert start
        {
            "new_start_date": date(2026, 7, 1),
            "new_end_date": date(2027, 6, 30),
            "new_grade_start_date": date(2026, 6, 1),
            "new_grade_end_date": date(2027, 6, 30),
            "replacement_starts": [date(2026, 7, 1)],
            "replacement_ends": [None],
        },
        # Grade end after finite cert end
        {
            "new_start_date": date(2026, 7, 1),
            "new_end_date": date(2027, 6, 30),
            "new_grade_start_date": date(2026, 7, 1),
            "new_grade_end_date": date(2027, 12, 31),
            "replacement_starts": [date(2026, 7, 1)],
            "replacement_ends": [None],
        },
        # Grade start after finite certification end.
        {
            "new_start_date": date(2026, 7, 1),
            "new_end_date": date(2027, 6, 30),
            "new_grade_start_date": date(2028, 1, 1),
            "new_grade_end_date": date(2028, 6, 30),
            "replacement_starts": [date(2026, 7, 1)],
            "replacement_ends": [None],
        },
        # Reversed replacement
        {
            "new_start_date": date(2026, 7, 1),
            "new_end_date": date(2027, 6, 30),
            "new_grade_start_date": date(2026, 7, 1),
            "new_grade_end_date": date(2027, 6, 30),
            "replacement_starts": [date(2026, 7, 1)],
            "replacement_ends": [date(2026, 1, 1)],
        },
        # Replacement start != new_start
        {
            "new_start_date": date(2026, 7, 1),
            "new_end_date": date(2027, 6, 30),
            "new_grade_start_date": date(2026, 7, 1),
            "new_grade_end_date": date(2027, 6, 30),
            "replacement_starts": [date(2026, 8, 1)],
            "replacement_ends": [None],
        },
    ],
)
def test_semantic_helper_rejects_bad_periods(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_transition_period_semantics(**kwargs)


def test_semantic_helper_rejects_grade_start_after_finite_cert_end() -> None:
    """Finite certification end cannot contain a later finite grade period."""
    with pytest.raises(ValueError, match="grade start must not exceed"):
        validate_transition_period_semantics(
            new_start_date=date(2026, 7, 1),
            new_end_date=date(2027, 6, 30),
            new_grade_start_date=date(2028, 1, 1),
            new_grade_end_date=date(2028, 6, 30),
            replacement_starts=[date(2026, 7, 1)],
            replacement_ends=[None],
        )


# ---------------------------------------------------------------------------
# Preview request: accept canonical, reject period defects
# ---------------------------------------------------------------------------


def test_preview_accepts_canonical_finite_periods() -> None:
    CertificationTransitionPreviewRequest.model_validate(_valid_preview())


@pytest.mark.parametrize("field", ["new_end_date", "new_grade_end_date"])
@pytest.mark.parametrize("mode", ["missing", "null"])
def test_preview_requires_non_null_certification_and_grade_ends(field: str, mode: str) -> None:
    body = _valid_preview()
    if mode == "missing":
        del body[field]
    else:
        body[field] = None
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(body)


def test_preview_accepts_exact_finite_boundary_grade() -> None:
    CertificationTransitionPreviewRequest.model_validate(
        _valid_preview(
            new_grade_start_date="2027-06-30",
            new_grade_end_date="2027-06-30",
        )
    )


def test_preview_rejects_grade_start_after_finite_cert_end() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(
                new_end_date="2027-06-30",
                new_grade_start_date="2028-01-01",
                new_grade_end_date="2028-06-30",
            )
        )


def test_preview_rejects_reversed_certification() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(
                new_start_date="2027-07-01",
                new_end_date="2026-07-01",
                new_grade_start_date="2027-07-01",
                new_grade_end_date="2026-12-01",
                replacement_contracts=[_replacement(start_date="2027-07-01")],
            )
        )


def test_preview_rejects_reversed_grade() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(
                new_grade_start_date="2027-01-01",
                new_grade_end_date="2026-08-01",
            )
        )


def test_preview_rejects_grade_outside_certification() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(new_grade_start_date="2026-06-01")
        )
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(new_grade_end_date="2028-01-01")
        )


def test_preview_rejects_reversed_replacement() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(
                replacement_contracts=[_replacement(start_date="2026-07-01", end_date="2026-01-01")]
            )
        )


def test_preview_rejects_replacement_start_mismatch() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionPreviewRequest.model_validate(
            _valid_preview(replacement_contracts=[_replacement(start_date="2026-08-15")])
        )


# ---------------------------------------------------------------------------
# Apply request: strict confirmed + replacement item periods
# ---------------------------------------------------------------------------


def test_apply_accepts_canonical_true_and_replacements() -> None:
    parsed = CertificationTransitionApplyRequest.model_validate(_valid_apply())
    assert parsed.confirmed is True
    assert parsed.preview_token == "token-for-schema-only"


@pytest.mark.parametrize("bad_confirmed", [1, 0, "true", "false", "True", "1"])
def test_apply_rejects_non_strict_confirmed(bad_confirmed: Any) -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionApplyRequest.model_validate(_valid_apply(confirmed=bad_confirmed))


def test_apply_accepts_confirmed_false_at_schema() -> None:
    # Schema accepts JSON false; service later maps confirmed is not True →
    # CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED. Strictness still holds.
    parsed = CertificationTransitionApplyRequest.model_validate(_valid_apply(confirmed=False))
    assert parsed.confirmed is False


def test_apply_rejects_reversed_replacement_item() -> None:
    with pytest.raises(ValidationError):
        CertificationTransitionApplyRequest.model_validate(
            _valid_apply(
                replacement_contracts=[_replacement(start_date="2026-07-01", end_date="2026-01-01")]
            )
        )


# ---------------------------------------------------------------------------
# PositiveVersion / StrictBool type adapters + ContractEndRequest path
# ---------------------------------------------------------------------------


def test_positive_version_accepts_positive_int_rejects_bool() -> None:
    adapter = TypeAdapter(PositiveVersion)
    assert adapter.validate_python(1) == 1
    assert adapter.validate_python(42) == 42
    for bad in (True, False, 0, -1, "1", 1.5):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_strict_bool_accepts_only_bool() -> None:
    adapter = TypeAdapter(StrictBool)
    assert adapter.validate_python(True) is True
    assert adapter.validate_python(False) is False
    for bad in (1, 0, "true", "false", None):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)


def test_contract_end_expected_row_version_rejects_bool() -> None:
    with pytest.raises(ValidationError):
        ContractEndRequest.model_validate({"expected_row_version": True, "end_date": "2026-07-01"})
    with pytest.raises(ValidationError):
        ContractEndRequest.model_validate({"expected_row_version": False, "end_date": "2026-07-01"})
    parsed = ContractEndRequest.model_validate(
        {"expected_row_version": 3, "end_date": "2026-07-01"}
    )
    assert parsed.expected_row_version == 3


def test_transition_replacement_item_period_order() -> None:
    TransitionReplacementItem.model_validate(_replacement(end_date=None))
    with pytest.raises(ValidationError):
        TransitionReplacementItem.model_validate(
            _replacement(start_date="2026-07-01", end_date="2026-01-01")
        )


# ---------------------------------------------------------------------------
# R7: canonical preview projection, order, no-PII, hash drift mutants
# ---------------------------------------------------------------------------


def _base_projection_parts() -> dict[str, Any]:
    return {
        "recipient_id": 10,
        "certification_number": "L1234567890",
        "recipient_aggregate": {
            "id": 10,
            "row_version": 3,
            "updated_at_utc": "2026-01-01T00:00:00+00:00",
        },
        "identity_aggregate": {
            "recipient_id": 10,
            "certification_number": "L1234567890",
            "row_version": 2,
            "updated_at_utc": "2026-01-02T00:00:00+00:00",
        },
        "certification_periods": [
            {
                "id": 1,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "row_version": 1,
                "invalidated_at_utc": None,
                "replacement_certification_period_id": None,
                "updated_at_utc": "2026-01-01T00:00:00+00:00",
            }
        ],
        "grade_periods": [
            {
                "id": 5,
                "certification_period_id": 1,
                "grade_code": "3",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "row_version": 1,
                "invalidated_at_utc": None,
                "replacement_grade_period_id": None,
                "updated_at_utc": "2026-01-01T00:00:00+00:00",
            }
        ],
        "contracts": [
            {
                "id": 1,
                "service_type_code": "HOME_CARE",
                "service_group_code": "LONG_TERM_CARE",
                "start_date": "2026-01-01",
                "end_date": None,
                "service_start_date": None,
                "row_version": 1,
                "invalidated_at_utc": None,
                "replacement_contract_id": None,
                "updated_at_utc": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": 2,
                "service_type_code": "HOME_BATH",
                "service_group_code": "LONG_TERM_CARE",
                "start_date": "2026-01-01",
                "end_date": None,
                "service_start_date": None,
                "row_version": 1,
                "invalidated_at_utc": None,
                "replacement_contract_id": None,
                "updated_at_utc": "2026-01-01T00:00:00+00:00",
            },
        ],
        "service_multiset": ["HOME_BATH", "HOME_CARE"],
        "transition": {
            "new_start_date": "2026-07-01",
            "new_end_date": "2027-06-30",
            "new_grade_code": "4",
            "new_grade_start_date": "2026-07-01",
            "new_grade_end_date": "2027-06-30",
        },
        "replacements_non_sensitive": [
            {
                "ended_contract_id": 1,
                "service_type_code": "HOME_CARE",
                "start_date": "2026-07-01",
                "end_date": None,
                "service_start_date": None,
            },
            {
                "ended_contract_id": 2,
                "service_type_code": "HOME_BATH",
                "start_date": "2026-07-01",
                "end_date": None,
                "service_start_date": None,
            },
        ],
    }


def test_canonical_projection_key_order_and_no_pii() -> None:
    from app.domains.w1d.policies import (
        SERIALIZATION_VERSION,
        build_canonical_projection,
        full_bound_replacements,
        non_sensitive_replacements,
        sha256_canonical,
    )

    parts = _base_projection_parts()
    proj = build_canonical_projection(**parts)
    # Exact top-level key set (plan §2.3 / R7).
    assert set(proj.keys()) == {
        "v",
        "recipient_id",
        "certification_number",
        "recipient_aggregate",
        "identity_aggregate",
        "certification_periods",
        "grade_periods",
        "contracts",
        "service_multiset",
        "transition",
        "replacements",
    }
    assert proj["v"] == SERIALIZATION_VERSION
    # Multiset sorted.
    assert proj["service_multiset"] == ["HOME_BATH", "HOME_CARE"]
    # Contracts carry stable codes, never service_type_id.
    for row in proj["contracts"]:
        assert "service_type_id" not in row
        assert "service_type_code" in row
        assert "service_group_code" in row
        assert "replacement_contract_id" in row
        assert "updated_at_utc" in row
        assert "signer_name" not in row
        assert "signer_phone" not in row
        assert "end_reason_text" not in row
    # Aggregate omits PII (name/address/phone).
    assert set(proj["recipient_aggregate"].keys()) == {
        "id",
        "row_version",
        "updated_at_utc",
    }
    # Cert/grade include replacement FK + updated_at_utc.
    assert "replacement_certification_period_id" in proj["certification_periods"][0]
    assert "updated_at_utc" in proj["certification_periods"][0]
    assert "replacement_grade_period_id" in proj["grade_periods"][0]
    assert "updated_at_utc" in proj["grade_periods"][0]
    # Non-sensitive replacements only.
    for rep in proj["replacements"]:
        assert set(rep.keys()) == {
            "ended_contract_id",
            "service_type_code",
            "start_date",
            "end_date",
            "service_start_date",
        }
        assert "signer_name" not in rep
    import json as _json

    raw = _json.dumps(proj, sort_keys=True, separators=(",", ":"))
    for pii in (
        "TEST_W1D_SIGNER",
        "signer_name",
        "signer_phone",
        "end_reason_text",
        "recipient_name",
        "address",
        "mobile_phone",
    ):
        assert pii not in raw
    h = sha256_canonical(proj)
    assert len(h) == 64 and h == h.lower()

    # Order permutations of replacements → same non-sensitive + full-bound + hash.
    rev = [
        {
            "ended_contract_id": 2,
            "service_type_code": "HOME_BATH",
            "start_date": "2026-07-01",
            "end_date": None,
            "service_start_date": None,
            "signer_name": "SECRET",
            "signer_relationship_text": None,
            "signer_phone": "010",
            "end_reason_text": "reason",
        },
        {
            "ended_contract_id": 1,
            "service_type_code": "HOME_CARE",
            "start_date": "2026-07-01",
            "end_date": None,
            "service_start_date": None,
            "signer_name": None,
            "signer_relationship_text": None,
            "signer_phone": None,
            "end_reason_text": None,
        },
    ]
    fwd = list(reversed(rev))
    ns_a = non_sensitive_replacements(rev)
    ns_b = non_sensitive_replacements(fwd)
    assert ns_a == ns_b
    assert [r["ended_contract_id"] for r in ns_a] == [1, 2]
    full_a = full_bound_replacements(rev)
    full_b = full_bound_replacements(fwd)
    assert full_a == full_b
    assert [r["ended_contract_id"] for r in full_a] == [1, 2]
    parts_a = {**parts, "replacements_non_sensitive": ns_a}
    parts_b = {**parts, "replacements_non_sensitive": ns_b}
    assert sha256_canonical(build_canonical_projection(**parts_a)) == sha256_canonical(
        build_canonical_projection(**parts_b)
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p["recipient_aggregate"].__setitem__("row_version", 99),
        lambda p: p["recipient_aggregate"].__setitem__(
            "updated_at_utc", "2026-12-31T00:00:00+00:00"
        ),
        lambda p: p["identity_aggregate"].__setitem__("row_version", 99),
        lambda p: p["identity_aggregate"].__setitem__(
            "updated_at_utc", "2026-12-31T00:00:00+00:00"
        ),
        lambda p: p["identity_aggregate"].__setitem__("certification_number", "L9999999999"),
        lambda p: p["certification_periods"][0].__setitem__("row_version", 9),
        lambda p: p["certification_periods"][0].__setitem__(
            "updated_at_utc", "2026-12-31T00:00:00+00:00"
        ),
        lambda p: p["certification_periods"][0].__setitem__(
            "replacement_certification_period_id", 77
        ),
        lambda p: p["grade_periods"][0].__setitem__("row_version", 9),
        lambda p: p["grade_periods"][0].__setitem__("updated_at_utc", "2026-12-31T00:00:00+00:00"),
        lambda p: p["grade_periods"][0].__setitem__("replacement_grade_period_id", 88),
        lambda p: p["contracts"][0].__setitem__("row_version", 9),
        lambda p: p["contracts"][0].__setitem__("updated_at_utc", "2026-12-31T00:00:00+00:00"),
        lambda p: p["contracts"][0].__setitem__("replacement_contract_id", 55),
        lambda p: p["contracts"][0].__setitem__("service_type_code", "BARO_CARE"),
        lambda p: p["contracts"][0].__setitem__("service_group_code", "OTHER"),
        lambda p: p["replacements_non_sensitive"][0].__setitem__("start_date", "2026-08-01"),
        lambda p: p["transition"].__setitem__("new_grade_code", "5"),
    ],
)
def test_canonical_hash_drifts_on_aggregate_update_replacement_service_fields(
    mutator: Any,
) -> None:
    import copy

    from app.domains.w1d.policies import build_canonical_projection, sha256_canonical

    base = _base_projection_parts()
    base_hash = sha256_canonical(build_canonical_projection(**base))
    mutant = copy.deepcopy(base)
    mutator(mutant)
    mutant_hash = sha256_canonical(build_canonical_projection(**mutant))
    assert mutant_hash != base_hash
    assert len(mutant_hash) == 64


def test_service_type_id_must_not_be_semantic_contract_code() -> None:
    """Contracts projection must use service_type_code, not numeric service_type_id."""
    import copy

    from app.domains.w1d.policies import build_canonical_projection, sha256_canonical

    parts = _base_projection_parts()
    h1 = sha256_canonical(build_canonical_projection(**parts))
    bad = copy.deepcopy(parts)
    # Inject numeric id field — must not appear in canonical contracts as semantic code.
    for row in bad["contracts"]:
        row["service_type_id"] = 999
    # Extra keys still change JSON; ensure official builder never emits service_type_id.
    proj = build_canonical_projection(**parts)
    assert all("service_type_id" not in c for c in proj["contracts"])
    assert h1 == sha256_canonical(proj)


# ---------------------------------------------------------------------------
# R8: single canonical UTC timestamp representation
# ---------------------------------------------------------------------------


def test_canonicalize_utc_timestamp_unifies_equivalent_instants() -> None:
    """Z / +00:00 / +09:00 strings and aware/naive datetimes → one +00:00 form."""
    from datetime import UTC, datetime, timedelta, timezone

    from app.domains.w1d.policies import canonicalize_utc_timestamp

    expected = "2030-01-01T00:00:00+00:00"
    samples: list[datetime | str] = [
        "2030-01-01T00:00:00Z",
        "2030-01-01T00:00:00+00:00",
        "2030-01-01T09:00:00+09:00",
        datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2030, 1, 1, 9, 0, 0, tzinfo=timezone(timedelta(hours=9))),
        # Naive treated as UTC.
        datetime(2030, 1, 1, 0, 0, 0),
    ]
    canonicalized = [canonicalize_utc_timestamp(sample) for sample in samples]
    assert all(item == expected for item in canonicalized)
    assert len(set(canonicalized)) == 1
    # Never emit trailing Z.
    assert not expected.endswith("Z")
    assert expected.endswith("+00:00")


def test_canonicalize_utc_timestamp_invalid_string_fails_closed() -> None:
    from app.domains.w1d.policies import canonicalize_utc_timestamp

    for bad in ("", "   ", "not-a-timestamp", "2030-13-01T00:00:00Z", "garbage+00:00"):
        with pytest.raises(ValueError):
            canonicalize_utc_timestamp(bad)
    assert canonicalize_utc_timestamp(None) is None
