from __future__ import annotations

import json
from collections import Counter
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.domains.w3.workbook_parser import (
    NHIS_SCHEDULE_PROFILE_V1,
    RFID_PROFILE_V1,
    RfidEventState,
    WorkbookParseBlocked,
    parse_nhis_schedule_workbook,
    parse_rfid_workbook,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "w3"
WORKBOOK_ROOT = FIXTURE_ROOT / "workbooks"
EXPECTED = json.loads(
    (FIXTURE_ROOT / "expected" / "workbook_profile_v1.json").read_text(encoding="utf-8")
)
NHIS_BYTES = (WORKBOOK_ROOT / "nhis_schedule_202607_v1.xlsx").read_bytes()
RFID_BYTES = (WORKBOOK_ROOT / "rfid_202607_v1.xlsx").read_bytes()
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _rewrite_package(
    source: bytes,
    *,
    replacements: dict[str, bytes] | None = None,
    additions: dict[str, bytes] | None = None,
) -> bytes:
    replacements = replacements or {}
    additions = additions or {}
    output = BytesIO()
    with ZipFile(BytesIO(source)) as archive, ZipFile(output, "w", ZIP_DEFLATED) as rewritten:
        for entry in archive.infolist():
            rewritten.writestr(entry, replacements.get(entry.filename, archive.read(entry)))
        for name, payload in additions.items():
            rewritten.writestr(name, payload)
    return output.getvalue()


def _mutate_sheet(source: bytes, mutate: object) -> bytes:
    with ZipFile(BytesIO(source)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    assert callable(mutate)
    mutate(sheet)
    return _rewrite_package(
        source,
        replacements={
            "xl/worksheets/sheet1.xml": ET.tostring(
                sheet,
                encoding="utf-8",
                xml_declaration=True,
            )
        },
    )


def test_approved_profiles_are_exact_and_historical_blocked_profiles_remain() -> None:
    nhis = json.loads(
        (FIXTURE_ROOT / "profiles" / "nhis_schedule_v1.approved.json").read_text(encoding="utf-8")
    )
    rfid = json.loads(
        (FIXTURE_ROOT / "profiles" / "rfid_v1.approved.json").read_text(encoding="utf-8")
    )

    assert nhis["headers"] == list(NHIS_SCHEDULE_PROFILE_V1.headers)
    assert rfid["headers"] == list(RFID_PROFILE_V1.headers)
    assert nhis["status"] == rfid["status"] == "APPROVED_PSEUDONYMOUS_REAL_SHAPE"
    assert nhis["contains_pii"] is rfid["contains_pii"] is False
    assert nhis["filename_is_business_key"] is rfid["filename_is_business_key"] is False
    for historical in ("nhis_schedule_v0.blocked.json", "rfid_v0.blocked.json"):
        profile = json.loads((FIXTURE_ROOT / "profiles" / historical).read_text(encoding="utf-8"))
        assert profile["status"] == "BLOCKED_HEADER_PROFILE_MISSING"


def test_fixture_bytes_and_declared_pseudonymous_aggregates_are_exact() -> None:
    for key, payload in (("nhis_schedule", NHIS_BYTES), ("rfid", RFID_BYTES)):
        expected = EXPECTED[key]
        assert sha256(payload).hexdigest() == expected["sha256"]
        assert len(payload) == expected["bytes"]


def test_nhis_parser_preserves_every_physical_row_and_duplicate_occurrence() -> None:
    result = parse_nhis_schedule_workbook(
        NHIS_BYTES,
        target_month=date(2026, 7, 1),
        original_filename="일정계획_202607.xlsx",
    )
    expected = EXPECTED["nhis_schedule"]

    assert result.profile_version == "nhis-schedule-xlsx-v1"
    assert result.sheet_ref == "일정계획"
    assert len(result.raw_rows) == len(result.parsed_rows) == len(result.target_rows) == 910
    assert result.raw_rows[0].source_row_number == expected["first_source_row"]
    assert result.raw_rows[-1].source_row_number == expected["last_source_row"]
    assert len({row.physical_address for row in result.raw_rows}) == 910
    assert (
        min(row.service_date for row in result.target_rows).isoformat() == expected["minimum_date"]
    )
    assert (
        max(row.service_date for row in result.target_rows).isoformat() == expected["maximum_date"]
    )
    assert Counter(row.declared_minutes for row in result.target_rows) == {
        int(minutes): count for minutes, count in expected["duration_minutes"].items()
    }
    assert sum(row.family_relationship is None for row in result.target_rows) == 623
    assert any(row.occurrence_ordinal > 1 for row in result.target_rows)
    assert result.business_write_count == 0


def test_nhis_parser_blocks_wrong_target_month_without_partial_result() -> None:
    with pytest.raises(WorkbookParseBlocked, match="TARGET_MONTH_MISMATCH") as caught:
        parse_nhis_schedule_workbook(NHIS_BYTES, target_month=date(2026, 8, 1))

    assert caught.value.business_write_count == 0


def test_rfid_parser_preserves_range_export_but_selects_exact_target_day() -> None:
    result = parse_rfid_workbook(
        RFID_BYTES,
        target_date=date(2026, 7, 6),
        original_filename="실시간전송내용 (1).xlsx",
    )

    assert result.profile_version == "rfid-xlsx-v1"
    assert result.sheet_ref == "실시간전송내용"
    assert len(result.raw_rows) == len(result.parsed_rows) == 314
    assert len(result.target_rows) == 36
    assert all(row.actual_start.date() == date(2026, 7, 6) for row in result.target_rows)
    assert sum(row.event_state is RfidEventState.START_ONLY for row in result.parsed_rows) == 3
    assert sum(row.event_state is RfidEventState.START_ONLY for row in result.target_rows) == 1
    start_only = next(
        row for row in result.target_rows if row.event_state is RfidEventState.START_ONLY
    )
    assert start_only.actual_end is None
    assert start_only.end_display.startswith("종료X · ")
    assert any(row.actual_start.second != 0 for row in result.target_rows)
    assert "EXPORT_CONTAINS_OTHER_DATES" in result.warning_codes
    assert result.business_write_count == 0


def test_rfid_filename_suffix_is_not_an_identity_input() -> None:
    first = parse_rfid_workbook(
        RFID_BYTES,
        target_date=date(2026, 7, 1),
        original_filename="실시간전송내용.xlsx",
    )
    second = parse_rfid_workbook(
        RFID_BYTES,
        target_date=date(2026, 7, 1),
        original_filename="실시간전송내용 (9).xlsx",
    )

    assert first.content_digest == second.content_digest
    assert [row.occurrence_identity for row in first.target_rows] == [
        row.occurrence_identity for row in second.target_rows
    ]


def test_two_pseudonymous_shape_workbooks_do_not_invent_cross_identity_mapping() -> None:
    nhis = parse_nhis_schedule_workbook(NHIS_BYTES, target_month=date(2026, 7, 1))
    rfid = parse_rfid_workbook(RFID_BYTES, target_date=date(2026, 7, 1))
    expected = EXPECTED["cross_workbook"]

    assert (
        len(
            {row.recipient_certification_number for row in nhis.parsed_rows}
            & {row.recipient_certification_number for row in rfid.parsed_rows}
        )
        == expected["recipient_certification_number_intersection"]
        == 0
    )
    assert (
        len(
            {row.recipient_name for row in nhis.parsed_rows}
            & {row.recipient_name for row in rfid.parsed_rows}
        )
        == expected["recipient_name_intersection"]
        == 0
    )
    assert expected["automatic_match_expectation"] == "REVIEW_PENDING"


def test_rfid_parser_blocks_missing_target_day_without_partial_result() -> None:
    with pytest.raises(WorkbookParseBlocked, match="TARGET_DATE_NOT_FOUND") as caught:
        parse_rfid_workbook(RFID_BYTES, target_date=date(2026, 7, 31))

    assert caught.value.business_write_count == 0


def test_parser_rejects_macro_or_path_traversal_package_before_workbook_load() -> None:
    macro = _rewrite_package(NHIS_BYTES, additions={"xl/vbaProject.bin": b"not-a-macro"})
    traversal = _rewrite_package(NHIS_BYTES, additions={"../escape.xml": b"<x/>"})

    with pytest.raises(WorkbookParseBlocked, match="ACTIVE_CONTENT_BLOCKED"):
        parse_nhis_schedule_workbook(macro, target_month=date(2026, 7, 1))
    with pytest.raises(WorkbookParseBlocked, match="UNSAFE_PACKAGE_PATH"):
        parse_nhis_schedule_workbook(traversal, target_month=date(2026, 7, 1))


def test_parser_rejects_disguised_active_content_by_declared_type_or_relationship() -> None:
    with ZipFile(BytesIO(NHIS_BYTES)) as archive:
        content_types = archive.read("[Content_Types].xml")
        relationships = archive.read("xl/_rels/workbook.xml.rels")
    disguised_type = content_types.replace(
        b"</Types>",
        (
            b'<Override PartName="/xl/opaque.dat" '
            b'ContentType="application/vnd.ms-office.vbaProject"/></Types>'
        ),
    )
    disguised_relationship = relationships.replace(
        b"</Relationships>",
        (
            b'<Relationship Id="rIdOpaque" '
            b'Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" '
            b'Target="opaque.dat"/></Relationships>'
        ),
    )
    by_type = _rewrite_package(
        NHIS_BYTES,
        replacements={"[Content_Types].xml": disguised_type},
        additions={"xl/opaque.dat": b"not-a-real-project"},
    )
    by_relationship = _rewrite_package(
        NHIS_BYTES,
        replacements={"xl/_rels/workbook.xml.rels": disguised_relationship},
        additions={"xl/opaque.dat": b"not-a-real-project"},
    )

    with pytest.raises(WorkbookParseBlocked, match="ACTIVE_CONTENT_BLOCKED"):
        parse_nhis_schedule_workbook(by_type, target_month=date(2026, 7, 1))
    with pytest.raises(WorkbookParseBlocked, match="ACTIVE_CONTENT_BLOCKED"):
        parse_nhis_schedule_workbook(by_relationship, target_month=date(2026, 7, 1))


def test_parser_rejects_external_relationship_dtd_and_compression_bomb() -> None:
    with ZipFile(BytesIO(NHIS_BYTES)) as archive:
        relationships = archive.read("xl/_rels/workbook.xml.rels")
        workbook_xml = archive.read("xl/workbook.xml")
    external_relationship = relationships.replace(
        b"</Relationships>",
        (
            b'<Relationship Id="rIdExternal" '
            b'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            b'relationships/externalLink" Target="https://invalid.example/" '
            b'TargetMode="External"/></Relationships>'
        ),
    )
    external = _rewrite_package(
        NHIS_BYTES,
        replacements={"xl/_rels/workbook.xml.rels": external_relationship},
    )
    dtd = _rewrite_package(
        NHIS_BYTES,
        replacements={
            "xl/workbook.xml": b'<!DOCTYPE workbook [<!ENTITY x "blocked">]>' + workbook_xml
        },
    )
    compressed_bomb = _rewrite_package(
        NHIS_BYTES,
        additions={"xl/media/high-ratio.dat": b"0" * (1024 * 1024)},
    )

    with pytest.raises(WorkbookParseBlocked, match="EXTERNAL_RELATIONSHIP_BLOCKED"):
        parse_nhis_schedule_workbook(external, target_month=date(2026, 7, 1))
    with pytest.raises(WorkbookParseBlocked, match="XML_ENTITY_BLOCKED"):
        parse_nhis_schedule_workbook(dtd, target_month=date(2026, 7, 1))
    with pytest.raises(WorkbookParseBlocked, match="XLSX_PACKAGE_LIMIT"):
        parse_nhis_schedule_workbook(compressed_bomb, target_month=date(2026, 7, 1))


def test_parser_rejects_formula_header_drift_and_wrong_cell_type() -> None:
    def add_formula(root: ET.Element) -> None:
        cell = root.find(f".//{{{MAIN_NS}}}c[@r='A2']")
        assert cell is not None
        formula = ET.Element(f"{{{MAIN_NS}}}f")
        formula.text = "1+1"
        cell.insert(0, formula)

    def make_start_numeric(root: ET.Element) -> None:
        cell = root.find(f".//{{{MAIN_NS}}}c[@r='B2']")
        assert cell is not None
        cell.attrib["t"] = "n"
        value = cell.find(f"{{{MAIN_NS}}}v")
        assert value is not None
        value.text = "0.5"

    formula = _mutate_sheet(NHIS_BYTES, add_formula)
    wrong_type = _mutate_sheet(NHIS_BYTES, make_start_numeric)
    with ZipFile(BytesIO(NHIS_BYTES)) as archive:
        shared = archive.read("xl/sharedStrings.xml")
    wrong_header = _rewrite_package(
        NHIS_BYTES,
        replacements={"xl/sharedStrings.xml": shared.replace("일자".encode(), "날짜".encode(), 1)},
    )

    with pytest.raises(WorkbookParseBlocked, match="FORMULA_BLOCKED"):
        parse_nhis_schedule_workbook(formula, target_month=date(2026, 7, 1))
    with pytest.raises(WorkbookParseBlocked, match="HEADER_MISMATCH"):
        parse_nhis_schedule_workbook(wrong_header, target_month=date(2026, 7, 1))
    with pytest.raises(WorkbookParseBlocked, match="CELL_TYPE_MISMATCH"):
        parse_nhis_schedule_workbook(wrong_type, target_month=date(2026, 7, 1))


def test_parser_rejects_missing_required_cell_without_partial_result() -> None:
    def remove_required_cell(root: ET.Element) -> None:
        source_row = root.find(f".//{{{MAIN_NS}}}row[@r='2']")
        assert source_row is not None
        cell = source_row.find(f"{{{MAIN_NS}}}c[@r='A2']")
        assert cell is not None
        source_row.remove(cell)

    missing = _mutate_sheet(NHIS_BYTES, remove_required_cell)
    with pytest.raises(WorkbookParseBlocked, match="CELL_TYPE_MISMATCH") as caught:
        parse_nhis_schedule_workbook(missing, target_month=date(2026, 7, 1))

    assert caught.value.business_write_count == 0


def test_parser_rejects_invalid_or_non_xlsx_bytes() -> None:
    with pytest.raises(WorkbookParseBlocked, match="INVALID_XLSX_PACKAGE"):
        parse_rfid_workbook(b"not an xlsx", target_date=date(2026, 7, 1))
