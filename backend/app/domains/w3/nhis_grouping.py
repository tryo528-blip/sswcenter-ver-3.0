"""Deterministic derived groups over immutable NHIS source rows."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256

from app.domains.w3.workbook_parser import NhisScheduleRow


@dataclass(frozen=True, slots=True)
class NhisDerivedGroup:
    group_signature: str
    service_date_iso: str
    planned_start_iso: str
    planned_end_iso: str
    declared_minutes: int
    recipient_certification_number: str
    staff_external_number: str
    service_category: str
    source_row_numbers: tuple[int, ...]
    source_occurrence_identities: tuple[str, ...]
    automatic_row_delete_count: int = 0


def _group_key(row: NhisScheduleRow) -> tuple[str, ...]:
    return (
        row.service_date.isoformat(),
        row.planned_start.isoformat(timespec="minutes"),
        row.planned_end.isoformat(timespec="minutes"),
        row.recipient_certification_number,
        row.staff_external_number,
        row.service_category,
    )


def _group_signature(key: tuple[str, ...]) -> str:
    canonical = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def derive_nhis_groups(rows: tuple[NhisScheduleRow, ...]) -> tuple[NhisDerivedGroup, ...]:
    """Group only exact approved identity/time/service keys; never remove a raw row."""

    grouped: dict[tuple[str, ...], list[NhisScheduleRow]] = defaultdict(list)
    seen_occurrences: set[str] = set()
    for row in rows:
        if row.occurrence_identity in seen_occurrences:
            raise ValueError("source occurrence identity must be unique")
        seen_occurrences.add(row.occurrence_identity)
        grouped[_group_key(row)].append(row)

    derived: list[NhisDerivedGroup] = []
    for key in sorted(grouped):
        members = sorted(
            grouped[key],
            key=lambda row: (row.source_row_number, row.occurrence_identity),
        )
        declared_minutes = {row.declared_minutes for row in members}
        if len(declared_minutes) != 1:
            raise ValueError("exact group key cannot contain conflicting planned durations")
        derived.append(
            NhisDerivedGroup(
                group_signature=_group_signature(key),
                service_date_iso=key[0],
                planned_start_iso=key[1],
                planned_end_iso=key[2],
                declared_minutes=declared_minutes.pop(),
                recipient_certification_number=key[3],
                staff_external_number=key[4],
                service_category=key[5],
                source_row_numbers=tuple(row.source_row_number for row in members),
                source_occurrence_identities=tuple(row.occurrence_identity for row in members),
            )
        )
    return tuple(derived)
