"""Pure contract tests for recipient list + manual recipient_status tag."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.domains.recipient import service as recipient_service_module
from app.domains.recipient.repository import (
    SERVICE_GROUP_ORDER,
    SERVICE_TYPE_ORDER_BY_GROUP,
)
from app.domains.recipient.schemas import (
    RecipientListItem,
    RecipientListResponse,
    RecipientListServiceGroupItem,
    RecipientListServiceTypeItem,
    RecipientListStatusFilter,
    RecipientResponse,
    RecipientSexCode,
    RecipientStatus,
    RecipientUpdateRequest,
)
from app.domains.recipient.service import (
    RecipientService,
    set_today_seoul,
    today_seoul,
)
from app.main import app


@pytest.fixture(autouse=True)
def _restore_today_seoul() -> Any:
    set_today_seoul(None)
    yield
    set_today_seoul(None)


def test_recipient_status_enum_is_strict_manual_tag() -> None:
    assert {item.value for item in RecipientStatus} == {"ACTIVE", "ENDED", "WAITING"}
    with pytest.raises(ValueError):
        RecipientStatus("HISTORY")
    with pytest.raises(ValueError):
        RecipientStatus("active")


def test_list_status_filter_enum_includes_all_tags() -> None:
    assert {item.value for item in RecipientListStatusFilter} == {
        "ALL",
        "ACTIVE",
        "ENDED",
        "WAITING",
    }
    assert "HISTORY" not in RecipientListStatusFilter.__members__
    with pytest.raises(ValueError):
        RecipientListStatusFilter("HISTORY")
    with pytest.raises(ValueError):
        RecipientListStatusFilter("active")


def test_openapi_list_status_query_is_strict_and_defaults_all() -> None:
    paths = app.openapi()["paths"]
    operation = paths["/api/v1/recipients"]["get"]
    parameters = {param["name"]: param for param in operation.get("parameters", [])}
    assert "status" in parameters
    assert "as_of" not in parameters
    status_schema = parameters["status"]["schema"]
    if "$ref" in status_schema:
        ref_name = status_schema["$ref"].rsplit("/", 1)[-1]
        status_schema = app.openapi()["components"]["schemas"][ref_name]
    enums: set[str] = set()
    if "anyOf" in status_schema:
        for branch in status_schema["anyOf"]:
            if "enum" in branch:
                enums.update(branch["enum"])
            if "$ref" in branch:
                ref_name = branch["$ref"].rsplit("/", 1)[-1]
                ref_schema = app.openapi()["components"]["schemas"][ref_name]
                enums.update(ref_schema.get("enum", []))
    else:
        enums = set(status_schema.get("enum", []))
        if not enums:
            for key in ("allOf", "oneOf"):
                for branch in status_schema.get(key, []):
                    if "enum" in branch:
                        enums.update(branch["enum"])
        if not enums:
            components = app.openapi()["components"]["schemas"]
            filter_schema = components.get("RecipientListStatusFilter", {})
            enums = set(filter_schema.get("enum", []))
    assert enums == {"ALL", "ACTIVE", "ENDED", "WAITING"}
    # Omitted API status must default exactly to ALL (UI may still send ACTIVE).
    assert parameters["status"]["schema"].get("default") == "ALL"


def test_openapi_list_item_has_no_list_status_or_row_status() -> None:
    schemas = app.openapi()["components"]["schemas"]
    assert "RecipientListItem" in schemas
    item = schemas["RecipientListItem"]["properties"]
    for field in (
        "id",
        "name",
        "birth_date",
        "sex_code",
        "recipient_no",
        "postal_code",
        "address",
        "home_phone",
        "mobile_phone",
        "memo",
        "row_version",
    ):
        assert field in item
    assert "list_status" not in item
    assert "recipient_status" not in item
    assert "grade_code" in item
    assert "benefit_code" in item
    assert "copayment_rate" in item
    assert "services" in item
    detail = schemas["RecipientResponse"]["properties"]
    assert "recipient_status" in detail
    assert "list_status" not in detail
    assert "services" not in detail
    assert "grade_code" not in detail
    create = schemas["RecipientCreateRequest"]["properties"]
    assert "recipient_status" not in create
    update = schemas["RecipientUpdateRequest"]["properties"]
    assert "recipient_status" in update


def test_list_item_schema_forbids_extra_and_requires_summary_fields() -> None:
    with pytest.raises(ValidationError):
        RecipientListItem(
            id=1,
            name="홍",
            birth_date=date(1950, 1, 1),
            sex_code=RecipientSexCode.MALE,
            recipient_no=None,
            postal_code=None,
            address=None,
            home_phone=None,
            mobile_phone=None,
            memo=None,
            row_version=1,
            grade_code=None,
            benefit_code=None,
            copayment_rate=None,
            services=[],
            unexpected=True,  # type: ignore[call-arg]
        )
    item = RecipientListItem(
        id=1,
        name="홍",
        birth_date=date(1950, 1, 1),
        sex_code=RecipientSexCode.FEMALE,
        recipient_no=None,
        postal_code=None,
        address=None,
        home_phone=None,
        mobile_phone=None,
        memo=None,
        row_version=1,
        grade_code=None,
        benefit_code=None,
        copayment_rate=None,
        services=[],
    )
    assert item.copayment_rate is None
    assert item.services == []
    dumped = item.model_dump()
    assert "list_status" not in dumped
    assert "recipient_status" not in dumped


def test_today_seoul_is_injectable_and_defaults_to_asia_seoul() -> None:
    set_today_seoul(lambda: date(2026, 3, 15))
    assert today_seoul() == date(2026, 3, 15)
    set_today_seoul(None)
    value = today_seoul()
    assert isinstance(value, date)
    assert recipient_service_module._SEOUL.key == "Asia/Seoul"


def test_service_group_catalog_order_constants_match_frozen_contract() -> None:
    assert SERVICE_GROUP_ORDER == ("LONG_TERM_CARE", "LOCAL_CARE", "BARO_CARE")
    assert SERVICE_TYPE_ORDER_BY_GROUP == {
        "LONG_TERM_CARE": ("HOME_CARE", "HOME_BATH"),
        "LOCAL_CARE": ("TEMP_HOME_CARE", "HOSPITAL_ESCORT"),
        "BARO_CARE": ("BARO_CARE",),
    }


def test_build_service_groups_orders_catalog_exactly() -> None:
    raw = [
        ("BARO_CARE", "바로돌봄", "BARO_CARE", "바로돌봄"),
        ("LONG_TERM_CARE", "장기요양", "HOME_BATH", "방문목욕"),
        ("LOCAL_CARE", "지역돌봄 연계", "HOSPITAL_ESCORT", "병원동행"),
        ("LONG_TERM_CARE", "장기요양", "HOME_CARE", "방문요양"),
        ("LOCAL_CARE", "지역돌봄 연계", "TEMP_HOME_CARE", "일시재가"),
    ]
    groups = RecipientService._build_service_groups(raw)
    assert [group.service_group_code for group in groups] == [
        "LONG_TERM_CARE",
        "LOCAL_CARE",
        "BARO_CARE",
    ]
    assert [item.service_type_code for item in groups[0].service_types] == [
        "HOME_CARE",
        "HOME_BATH",
    ]
    assert [item.service_type_code for item in groups[1].service_types] == [
        "TEMP_HOME_CARE",
        "HOSPITAL_ESCORT",
    ]
    assert [item.service_type_code for item in groups[2].service_types] == ["BARO_CARE"]


def test_build_service_groups_empty_when_no_services() -> None:
    assert RecipientService._build_service_groups([]) == []


def _recipient(
    *,
    recipient_id: int,
    name: str,
    birth_date: date = date(1950, 1, 1),
    recipient_status: str = "ACTIVE",
    payer_guardian_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=recipient_id,
        name=name,
        birth_date=birth_date,
        sex_code="MALE",
        recipient_status=recipient_status,
        recipient_no=None,
        postal_code=None,
        address=None,
        home_phone=None,
        mobile_phone=None,
        memo=None,
        payer_guardian_id=payer_guardian_id,
        row_version=1,
    )


def test_list_recipients_projection_independent_of_tag_and_no_list_status() -> None:
    set_today_seoul(lambda: date(2026, 8, 6))
    session = MagicMock()
    service = RecipientService(session)

    tagged_active = _recipient(recipient_id=10, name="가", recipient_status="ACTIVE")
    tagged_waiting = _recipient(recipient_id=20, name="나", recipient_status="WAITING")
    tagged_ended = _recipient(recipient_id=30, name="다", recipient_status="ENDED")
    no_contract = _recipient(recipient_id=40, name="라", recipient_status="ACTIVE")

    service.repository.list_recipients = MagicMock(  # type: ignore[method-assign]
        return_value=([tagged_active, tagged_waiting, tagged_ended, no_contract], 4)
    )
    service.repository.load_effective_contracts_by_recipient = MagicMock(  # type: ignore[method-assign]
        return_value={
            10: [("LONG_TERM_CARE", "장기요양", "HOME_CARE", "방문요양")],
            20: [],
            30: [("LONG_TERM_CARE", "장기요양", "HOME_BATH", "방문목욕")],
            40: [],
        }
    )
    service.repository.load_effective_grade_codes = MagicMock(  # type: ignore[method-assign]
        return_value={10: "3", 20: None, 30: "2", 40: None}
    )
    service.repository.load_effective_benefit_codes = MagicMock(  # type: ignore[method-assign]
        return_value={10: "GENERAL", 20: None, 30: None, 40: None}
    )

    response = service.list_recipients(
        search=None,
        page=1,
        page_size=50,
        status=RecipientListStatusFilter.ALL,
    )
    assert isinstance(response, RecipientListResponse)
    assert response.total == 4
    by_id = {item.id: item for item in response.items}
    assert "list_status" not in by_id[10].model_dump()
    assert by_id[10].grade_code == "3"
    assert by_id[10].benefit_code == "GENERAL"
    assert by_id[10].copayment_rate is None
    assert by_id[10].services[0].service_types[0].service_type_code == "HOME_CARE"
    # Tag does not drive services: ENDED tag can still show effective contract services.
    assert by_id[30].services[0].service_types[0].service_type_code == "HOME_BATH"
    assert by_id[20].services == []
    assert by_id[40].services == []

    call_kwargs = service.repository.list_recipients.call_args.kwargs
    assert call_kwargs["as_of"] == date(2026, 8, 6)
    assert call_kwargs["status"] == "ALL"
    assert call_kwargs["offset"] == 0
    assert call_kwargs["limit"] == 50


def test_list_recipients_passes_exact_tag_filter_and_pagination() -> None:
    set_today_seoul(lambda: date(2026, 1, 1))
    service = RecipientService(MagicMock())
    service.repository.list_recipients = MagicMock(return_value=([], 0))  # type: ignore[method-assign]
    service.repository.load_effective_contracts_by_recipient = MagicMock(return_value={})  # type: ignore[method-assign]
    service.repository.load_effective_grade_codes = MagicMock(return_value={})  # type: ignore[method-assign]
    service.repository.load_effective_benefit_codes = MagicMock(return_value={})  # type: ignore[method-assign]

    for status in (
        RecipientListStatusFilter.ACTIVE,
        RecipientListStatusFilter.ENDED,
        RecipientListStatusFilter.WAITING,
        RecipientListStatusFilter.ALL,
    ):
        service.list_recipients(
            search="김",
            page=2,
            page_size=25,
            status=status,
        )
        kwargs = service.repository.list_recipients.call_args.kwargs
        assert kwargs["status"] == status.value
        assert kwargs["search"] == "김"
        assert kwargs["offset"] == 25
        assert kwargs["limit"] == 25


def test_list_recipients_has_no_write_or_notification_side_effects() -> None:
    set_today_seoul(lambda: date(2026, 8, 6))
    session = MagicMock()
    service = RecipientService(session)
    service.repository.list_recipients = MagicMock(return_value=([], 0))  # type: ignore[method-assign]
    service.repository.load_effective_contracts_by_recipient = MagicMock(return_value={})  # type: ignore[method-assign]
    service.repository.load_effective_grade_codes = MagicMock(return_value={})  # type: ignore[method-assign]
    service.repository.load_effective_benefit_codes = MagicMock(return_value={})  # type: ignore[method-assign]
    service.repository.add = MagicMock()  # type: ignore[method-assign]
    service._commit = MagicMock()  # type: ignore[method-assign]
    service._flush = MagicMock()  # type: ignore[method-assign]
    service._audit = MagicMock()  # type: ignore[method-assign]
    service.create_plan_notification = MagicMock()  # type: ignore[method-assign]

    service.list_recipients(search=None, page=1, page_size=10)

    service.repository.add.assert_not_called()
    service._commit.assert_not_called()
    service._flush.assert_not_called()
    service._audit.assert_not_called()
    service.create_plan_notification.assert_not_called()
    session.commit.assert_not_called()
    session.add.assert_not_called()


def test_detail_recipient_response_includes_status_not_list_fields() -> None:
    recipient = _recipient(recipient_id=7, name="상세", recipient_status="WAITING")
    response = RecipientService._recipient_response(recipient)  # type: ignore[arg-type]
    assert isinstance(response, RecipientResponse)
    dumped = response.model_dump()
    assert dumped["recipient_status"] == RecipientStatus.WAITING
    assert "list_status" not in dumped
    assert "services" not in dumped
    assert "grade_code" not in dumped
    assert dumped["name"] == "상세"


def test_update_request_accepts_recipient_status_and_rejects_invalid() -> None:
    ok = RecipientUpdateRequest(
        expected_row_version=1,
        recipient_status=RecipientStatus.ENDED,
    )
    assert ok.recipient_status == RecipientStatus.ENDED
    assert "recipient_status" in ok.model_fields_set
    with pytest.raises(ValidationError):
        RecipientUpdateRequest(
            expected_row_version=1,
            recipient_status="HISTORY",  # type: ignore[arg-type]
        )
    # Explicit JSON null is rejected (optional-by-omission only).
    with pytest.raises(ValidationError):
        RecipientUpdateRequest.model_validate({"expected_row_version": 1, "recipient_status": None})
    omitted = RecipientUpdateRequest(expected_row_version=1)
    assert "recipient_status" not in omitted.model_fields_set
    assert omitted.recipient_status is None


def test_update_recipient_sets_manual_status_tag() -> None:
    session = MagicMock()
    service = RecipientService(session)
    recipient = _recipient(recipient_id=9, name="패치", recipient_status="ACTIVE")
    service._require_recipient = MagicMock(return_value=recipient)  # type: ignore[method-assign]
    service._require_version = MagicMock()  # type: ignore[method-assign]
    service._audit = MagicMock()  # type: ignore[method-assign]
    service._commit = MagicMock()  # type: ignore[method-assign]

    account = SimpleNamespace(id=1)
    payload = RecipientUpdateRequest(
        expected_row_version=1,
        recipient_status=RecipientStatus.WAITING,
    )
    result = service.update_recipient(9, payload, account)  # type: ignore[arg-type]
    assert recipient.recipient_status == "WAITING"
    assert result.recipient_status == RecipientStatus.WAITING
    service._commit.assert_called_once()
    service._audit.assert_called_once()


def test_list_response_allows_null_copayment_rate_without_formula() -> None:
    item = RecipientListItem(
        id=1,
        name="율",
        birth_date=date(1940, 5, 5),
        sex_code=RecipientSexCode.FEMALE,
        recipient_no="000001",
        postal_code=None,
        address=None,
        home_phone=None,
        mobile_phone=None,
        memo=None,
        row_version=1,
        grade_code="4",
        benefit_code="REDUCTION_6",
        copayment_rate=None,
        services=[
            RecipientListServiceGroupItem(
                service_group_code="LONG_TERM_CARE",
                display_name="장기요양",
                service_types=[
                    RecipientListServiceTypeItem(
                        service_type_code="HOME_CARE",
                        display_name="방문요양",
                    )
                ],
            )
        ],
    )
    assert item.copayment_rate is None
    assert item.benefit_code == "REDUCTION_6"


def test_app_list_route_still_exposes_search_page_page_size() -> None:
    params = {p["name"] for p in app.openapi()["paths"]["/api/v1/recipients"]["get"]["parameters"]}
    assert {"search", "page", "page_size", "status"}.issubset(params)


def test_migration_0015_source_is_linked_and_not_silently_skippable() -> None:
    """Static source contract: revision chain, backfill, NOT NULL/default/check, downgrade."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    migration = (
        repo_root / "backend" / "alembic" / "versions" / "20260806_0015_recipient_status_tag.py"
    )
    assert migration.is_file(), "migration 0015 must exist (not silently skipped)"
    source = migration.read_text(encoding="utf-8")
    assert 'revision: str = "20260806_0015_recipient_status_tag"' in source
    assert 'down_revision: str | None = "20260803_0014_recipient_plan_notification"' in source
    assert "nullable=True" in source
    assert "SET {_COLUMN} = 'ACTIVE' WHERE {_COLUMN} IS NULL" in source or (
        "recipient_status = 'ACTIVE'" in source and "IS NULL" in source
    )
    assert "nullable=False" in source
    assert "server_default=sa.text(\"'ACTIVE'\")" in source
    assert "ck_recipient_recipient_status" in source
    assert "ACTIVE','ENDED','WAITING'" in source or "ACTIVE','ENDED','WAITING" in source
    # Downgrade reverses exactly: drop check then column.
    assert "def downgrade()" in source
    down = source.split("def downgrade()", 1)[1]
    assert "drop_constraint" in down
    assert "drop_column" in down
    assert down.index("drop_constraint") < down.index("drop_column")
    # Lifecycle harness contract (executed only when dedicated opt-in env is set).
    this_source = Path(__file__).read_text(encoding="utf-8")
    assert "SSWCENTER_REC_STATUS_MIG_PG" in this_source
    assert "SSWCENTER_REC_STATUS_MIG_DATABASE_URL" in this_source
    assert "test_migration_0015_lifecycle_upgrade_downgrade_reupgrade" in this_source


def test_postcheck_0015_recipient_status_source_and_marker_contract() -> None:
    """Source-level: 0015 postcheck proves exact ACTIVE default, CHECK set, convalidated, marker."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    postcheck = repo_root / "backend" / "app" / "db" / "postcheck_w1a_vs1.py"
    source = postcheck.read_text(encoding="utf-8")
    assert 'RECIPIENT_STATUS_TAG_REVISION = "20260806_0015_recipient_status_tag"' in source
    assert 'print("RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK")' in source
    assert "def _verify_recipient_status_tag_contract" in source
    assert "def _normalize_recipient_status_sql" in source
    assert "_RECIPIENT_STATUS_CANONICAL_DEFAULTS" in source
    assert "_RECIPIENT_STATUS_CANONICAL_CHECK_DEFS" in source
    fn_src = source.split("def _verify_recipient_status_tag_contract", 1)[1].split("\ndef _", 1)[0]
    # Complete canonical default ACTIVE (not cast-stripping / token splitting).
    assert "server default must be exactly ACTIVE" in fn_src
    assert "canonical complete expression" in fn_src
    assert "must be NOT NULL" in fn_src
    # Reject weak token extraction / cast discard patterns inside the verifier body.
    assert "default_core" not in fn_src
    assert 'split("::"' not in fn_src
    assert "re.findall" not in fn_src
    assert "quoted_tokens" not in fn_src
    # Exact CHECK complete predicate {ACTIVE, ENDED, WAITING} + convalidated.
    assert "must accept exactly" in fn_src
    assert "canonical complete CHECK" in fn_src
    assert "ACTIVE" in fn_src and "ENDED" in fn_src and "WAITING" in fn_src
    assert "convalidated" in fn_src
    assert "must be validated/convalidated" in fn_src
    # Canonical frozensets must include sealed literals (and not open-ended suffixes).
    assert "\"'ACTIVE'::text\"" in source or "'ACTIVE'::text" in source
    assert "CHECK (recipient_status IN ('ACTIVE', 'ENDED', 'WAITING'))" in source
    # Restore-drill / backup callers depend on this exact marker string.
    restore_drill = repo_root / "scripts" / "restore-drill.ps1"
    assert restore_drill.is_file()
    drill = restore_drill.read_text(encoding="utf-8")
    assert "RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK" in drill
    assert "20260806_0015_recipient_status_tag" in drill


def test_postcheck_0015_rejects_noncanonical_default_and_check_expressions() -> None:
    """Source-level: non-canonical complete expressions must not be members of allowlists."""
    from app.db import postcheck_w1a_vs1 as postcheck_mod

    defaults = postcheck_mod._RECIPIENT_STATUS_CANONICAL_DEFAULTS
    checks = postcheck_mod._RECIPIENT_STATUS_CANONICAL_CHECK_DEFS
    normalize = postcheck_mod._normalize_recipient_status_sql

    # Suffix / OR TRUE / extra cast-adjacent garbage must not normalize into allowlist.
    for bad_default in (
        "'ACTIVE'::text OR TRUE",
        "'INACTIVE'::text",
        "'ACTIVE'::text || ''",
        "'ACTIVE'::text::text",
        "('ACTIVE'::text) OR TRUE",
    ):
        assert normalize(bad_default) not in defaults

    for bad_check in (
        "CHECK (recipient_status IN ('ACTIVE', 'ENDED', 'WAITING') OR TRUE)",
        "CHECK (recipient_status IN ('ACTIVE', 'ENDED', 'WAITING', 'DELETED'))",
        "CHECK (TRUE OR recipient_status IN ('ACTIVE', 'ENDED', 'WAITING'))",
        "CHECK (recipient_status IN ('ACTIVE', 'ENDED'))",
    ):
        assert normalize(bad_check) not in checks

    # Canonical sealed forms remain accepted.
    assert normalize("'ACTIVE'::text") in defaults
    assert normalize("CHECK (recipient_status IN ('ACTIVE', 'ENDED', 'WAITING'))") in checks


def test_model_recipient_status_check_name_matches_convention_and_migration() -> None:
    from app.db.models import Recipient

    check_names = {
        constraint.name
        for constraint in Recipient.__table__.constraints
        if constraint.name is not None
    }
    # Convention token "recipient_status" must emit exactly this final name.
    assert "ck_recipient_recipient_status" in check_names
    # Must not double-prefix under ck_%(table_name)s_%(constraint_name)s.
    assert "ck_recipient_ck_recipient_recipient_status" not in check_names

    column = Recipient.__table__.c.recipient_status
    assert column.nullable is False
    assert column.server_default is not None
    default_text = str(column.server_default.arg)
    assert "ACTIVE" in default_text


def test_openapi_update_status_optional_non_null_and_create_has_no_status() -> None:
    schemas = app.openapi()["components"]["schemas"]
    update_props = schemas["RecipientUpdateRequest"]["properties"]
    assert "recipient_status" in update_props
    status_schema = update_props["recipient_status"]
    # Optional (not required) but not nullable union.
    assert "recipient_status" not in schemas["RecipientUpdateRequest"].get("required", [])
    # Direct $ref or allOf to RecipientStatus — no null branch.
    dumped = str(status_schema)
    assert "null" not in dumped.lower() or status_schema.get("type") != "null"
    if "anyOf" in status_schema:
        assert not any(branch.get("type") == "null" for branch in status_schema["anyOf"])
    create_props = schemas["RecipientCreateRequest"]["properties"]
    assert "recipient_status" not in create_props
    # List status query default remains ALL.
    status_param = next(
        p
        for p in app.openapi()["paths"]["/api/v1/recipients"]["get"]["parameters"]
        if p["name"] == "status"
    )
    assert status_param["schema"].get("default") == "ALL"


def test_create_recipient_forces_active_without_status_input() -> None:
    from app.domains.recipient.schemas import RecipientCreateRequest

    assert "recipient_status" not in RecipientCreateRequest.model_fields

    session = MagicMock()
    service = RecipientService(session)
    captured: dict[str, Any] = {}

    def _capture_add(instance: object) -> None:
        captured["instance"] = instance

    def _fake_flush() -> None:
        instance = captured.get("instance")
        if instance is None:
            return
        if getattr(instance, "id", None) is None:  # noqa: B009
            instance.id = 10_015  # type: ignore[attr-defined]
        if getattr(instance, "row_version", None) is None:  # noqa: B009
            instance.row_version = 1  # type: ignore[attr-defined]

    service.repository.add = MagicMock(side_effect=_capture_add)  # type: ignore[method-assign]
    service._flush = MagicMock(side_effect=_fake_flush)  # type: ignore[method-assign]
    service._audit = MagicMock()  # type: ignore[method-assign]
    service._commit = MagicMock()  # type: ignore[method-assign]

    account = SimpleNamespace(id=7)
    payload = RecipientCreateRequest(
        name="신규",
        birth_date=date(1955, 2, 2),
        sex_code=RecipientSexCode.FEMALE,
    )
    response = service.create_recipient(payload, account)  # type: ignore[arg-type]
    instance = captured["instance"]
    assert instance.recipient_status == RecipientStatus.ACTIVE.value  # type: ignore[attr-defined]
    assert instance.id == 10_015  # type: ignore[attr-defined]
    assert instance.row_version == 1  # type: ignore[attr-defined]
    assert response.recipient_status == RecipientStatus.ACTIVE
    assert response.id == 10_015
    assert response.row_version == 1


def test_repository_status_predicate_applied_to_items_and_count() -> None:
    """List total/count must use the same manual-tag predicate as item query."""
    from pathlib import Path

    repo_path = (
        Path(__file__).resolve().parents[1] / "app" / "domains" / "recipient" / "repository.py"
    )
    source = repo_path.read_text(encoding="utf-8")
    assert "Recipient.recipient_status ==" in source
    assert "statement = statement.where(tag_predicate)" in source
    assert "count_statement = count_statement.where(tag_predicate)" in source
    # Must not derive status from contracts.
    assert "_has_effective_contract_exists" not in source
    assert 'status == "ACTIVE"' not in source or "recipient_status" in source


def test_openapi_list_status_default_is_exactly_all_not_active() -> None:
    parameters = {
        param["name"]: param
        for param in app.openapi()["paths"]["/api/v1/recipients"]["get"]["parameters"]
    }
    assert parameters["status"]["schema"]["default"] == "ALL"
    assert parameters["status"]["schema"]["default"] != "ACTIVE"


# --- 0015 migration lifecycle (dedicated disposable DB only) ---

_REV_0014 = "20260803_0014_recipient_plan_notification"
_REV_0015 = "20260806_0015_recipient_status_tag"
_MIG_OPT_IN = "SSWCENTER_REC_STATUS_MIG_PG"
_MIG_URL_ENV = "SSWCENTER_REC_STATUS_MIG_DATABASE_URL"


def test_migration_0015_lifecycle_upgrade_downgrade_reupgrade() -> None:
    """Execute real 0014→0015→0014→0015 against an isolated disposable PostgreSQL DB.

    Opt-in only:
      SSWCENTER_REC_STATUS_MIG_PG=1
      SSWCENTER_REC_STATUS_MIG_DATABASE_URL=postgresql+psycopg://.../*_test|*_review

    Never uses the normal REC-LIST app harness URL (SSWCENTER_DATABASE_URL) as the
    lifecycle target. When the opt-in flag is unset, the external harness is
    unavailable and this test skips. When the flag is set, missing/unsafe URL
    or failed transitions fail hard (no silent pass).
    """
    import os
    from datetime import UTC, datetime
    from pathlib import Path
    from uuid import uuid4

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.exc import IntegrityError

    from app.core.settings import assert_safe_test_database_url, get_settings

    # Fail-closed opt-in: absent → skip; present but not exactly "1" → fail.
    opt_in_raw = os.environ.get(_MIG_OPT_IN)
    if opt_in_raw is None:
        pytest.skip(
            f"requires {_MIG_OPT_IN}=1 and disposable {_MIG_URL_ENV} "
            "(isolated migration lifecycle harness)"
        )
    if opt_in_raw != "1":
        pytest.fail(
            f"{_MIG_OPT_IN} must be exactly '1' to run the migration lifecycle "
            f"(got {opt_in_raw!r}); use unset to skip as unavailable harness"
        )

    mig_url = os.environ.get(_MIG_URL_ENV)
    if not mig_url:
        pytest.fail(
            f"{_MIG_URL_ENV} is required when {_MIG_OPT_IN}=1 "
            "(must be a disposable database ending in _test or _review)"
        )
    try:
        assert_safe_test_database_url(mig_url)
    except ValueError as exc:
        pytest.fail(f"{_MIG_URL_ENV} is not a disposable test/review database: {exc}")

    def _pg_target_identity(database_url: str) -> tuple[str, int, str]:
        """Effective PostgreSQL target: host, port (default 5432), database name."""
        parsed = make_url(database_url)
        host = (parsed.host or "").lower()
        port = int(parsed.port) if parsed.port is not None else 5432
        database = parsed.database or ""
        return (host, port, database)

    # Refuse lifecycle when mig URL effectively targets the same DB as the app URL.
    # Do not connect to the app DB; compare normalized identity only.
    rec_list_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if rec_list_url:
        try:
            mig_identity = _pg_target_identity(mig_url)
            app_identity = _pg_target_identity(rec_list_url)
        except Exception as exc:  # noqa: BLE001 — fail closed on unparseable URLs
            pytest.fail(f"unable to normalize database URLs for target comparison: {exc}")
        if mig_identity == app_identity:
            pytest.fail(
                "lifecycle must use a dedicated disposable URL "
                f"({_MIG_URL_ENV}), not the same effective PostgreSQL target as "
                "SSWCENTER_DATABASE_URL "
                f"(host={mig_identity[0]!r} port={mig_identity[1]} db={mig_identity[2]!r})"
            )
    backend_root = Path(__file__).resolve().parents[1]

    def _alembic(target: str, *, direction: str) -> None:
        from alembic.config import Config

        from alembic import command

        previous_url = os.environ.get("SSWCENTER_DATABASE_URL")
        previous_env = os.environ.get("SSWCENTER_ENVIRONMENT")
        old_cwd = os.getcwd()
        try:
            os.environ["SSWCENTER_DATABASE_URL"] = mig_url
            os.environ.setdefault("SSWCENTER_ENVIRONMENT", "development")
            get_settings.cache_clear()
            os.chdir(backend_root)
            cfg = Config(str(backend_root / "alembic.ini"))
            if direction == "upgrade":
                command.upgrade(cfg, target)
            elif direction == "downgrade":
                command.downgrade(cfg, target)
            else:  # pragma: no cover
                raise AssertionError(f"unknown alembic direction {direction}")
        finally:
            os.chdir(old_cwd)
            if previous_url is None:
                os.environ.pop("SSWCENTER_DATABASE_URL", None)
            else:
                os.environ["SSWCENTER_DATABASE_URL"] = previous_url
            if previous_env is None:
                os.environ.pop("SSWCENTER_ENVIRONMENT", None)
            else:
                os.environ["SSWCENTER_ENVIRONMENT"] = previous_env
            get_settings.cache_clear()

    def _revision(connection) -> str | None:  # type: ignore[no-untyped-def]
        has_erp = connection.execute(
            text("SELECT to_regclass('erp.alembic_version') IS NOT NULL")
        ).scalar()
        if not has_erp:
            return None
        return connection.execute(text("SELECT version_num FROM erp.alembic_version")).scalar()

    def _has_status_column(connection) -> bool:  # type: ignore[no-untyped-def]
        return (
            connection.execute(
                text(
                    """
                    SELECT 1
                      FROM information_schema.columns
                     WHERE table_schema = 'erp'
                       AND table_name = 'recipient'
                       AND column_name = 'recipient_status'
                    """
                )
            ).scalar()
            is not None
        )

    engine = create_engine(mig_url, pool_pre_ping=True)
    token = uuid4().hex[:10]
    try:
        # Inspect starting revision only; never run Alembic while a transaction is open.
        with engine.begin() as connection:
            current = _revision(connection)

        # Fail-closed: wrapper must provide None (empty), 0014, or 0015 only.
        if current is None:
            _alembic(_REV_0014, direction="upgrade")
        elif current == _REV_0015:
            _alembic(_REV_0014, direction="downgrade")
        elif current == _REV_0014:
            pass
        else:
            pytest.fail(
                "lifecycle disposable DB must start at None, "
                f"{_REV_0014}, or {_REV_0015}; got unexpected revision {current!r}"
            )

        with engine.begin() as connection:
            rev = _revision(connection)
            if rev != _REV_0014:
                pytest.fail(f"expected revision {_REV_0014} before lifecycle upgrade, got {rev!r}")
            if _has_status_column(connection):
                pytest.fail("recipient_status must not exist at 0014 before lifecycle upgrade")

            # Seed actor + pre-existing recipient without the new column.
            staff_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.staff
                            (name, birth_date, sex_code, phone, address, display_name, memo)
                        VALUES
                            (:name, DATE '1990-01-01', 'TEST', NULL, NULL, :name, 'mig-0015')
                        RETURNING id
                        """
                    ),
                    {"name": f"MIG0015_staff_{token}"},
                ).scalar_one()
            )
            account_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.user_account
                            (staff_id, account_code, display_name, role_code,
                             pin_hash, pin_lookup_hmac, pin_key_version)
                        VALUES
                            (:staff_id, :code, :name, 'ADMIN',
                             'mig-hash', :hmac, 1)
                        RETURNING id
                        """
                    ),
                    {
                        "staff_id": staff_id,
                        "code": f"mig-0015-{token}",
                        "name": f"MIG0015_actor_{token}",
                        "hmac": f"mig-0015-{token}".encode(),
                    },
                ).scalar_one()
            )
            now = datetime.now(UTC)
            recipient_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.recipient (
                            name, birth_date, sex_code,
                            created_by_account_id, created_at_utc,
                            updated_by_account_id, updated_at_utc, row_version
                        ) VALUES (
                            :name, DATE '1950-01-01', 'MALE',
                            :account_id, :now,
                            :account_id, :now, 1
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "name": f"MIG0015_pre_{token}",
                        "account_id": account_id,
                        "now": now,
                    },
                ).scalar_one()
            )

        # 1) Upgrade to 0015 and assert backfill + constraints.
        _alembic(_REV_0015, direction="upgrade")
        # Read-only assertions on their own connection (no nested begin after SELECTs).
        with engine.connect() as connection:
            rev = _revision(connection)
            if rev != _REV_0015:
                pytest.fail(f"upgrade to {_REV_0015} failed; revision={rev!r}")
            if not _has_status_column(connection):
                pytest.fail("recipient_status column missing after upgrade to 0015")

            col = (
                connection.execute(
                    text(
                        """
                    SELECT is_nullable, column_default
                      FROM information_schema.columns
                     WHERE table_schema = 'erp'
                       AND table_name = 'recipient'
                       AND column_name = 'recipient_status'
                    """
                    )
                )
                .mappings()
                .one()
            )
            assert col["is_nullable"] == "NO"
            assert col["column_default"] is not None
            assert "ACTIVE" in str(col["column_default"])

            status = connection.execute(
                text("SELECT recipient_status FROM erp.recipient WHERE id = :id"),
                {"id": recipient_id},
            ).scalar_one()
            assert status == "ACTIVE"

            check = (
                connection.execute(
                    text(
                        """
                    SELECT conname, pg_get_constraintdef(oid, true) AS definition
                      FROM pg_constraint
                     WHERE conrelid = 'erp.recipient'::regclass
                       AND contype = 'c'
                       AND conname = 'ck_recipient_recipient_status'
                    """
                    )
                )
                .mappings()
                .one()
            )
            assert check["conname"] == "ck_recipient_recipient_status"
            definition = str(check["definition"])
            assert "ACTIVE" in definition and "ENDED" in definition and "WAITING" in definition

        # Invalid write on a fresh begin() block (not nested after prior SELECTs).
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE erp.recipient
                           SET recipient_status = 'NOT_A_STATUS'
                         WHERE id = :id
                        """
                    ),
                    {"id": recipient_id},
                )
        except IntegrityError:
            pass
        else:
            pytest.fail("check constraint must reject invalid recipient_status")

        # 2) Downgrade to 0014: column and check must disappear.
        _alembic(_REV_0014, direction="downgrade")
        with engine.begin() as connection:
            rev = _revision(connection)
            if rev != _REV_0014:
                pytest.fail(f"downgrade to {_REV_0014} failed; revision={rev!r}")
            if _has_status_column(connection):
                pytest.fail("recipient_status column still present after downgrade to 0014")
            check_gone = connection.execute(
                text(
                    """
                    SELECT 1
                      FROM pg_constraint
                     WHERE conrelid = 'erp.recipient'::regclass
                       AND contype = 'c'
                       AND conname = 'ck_recipient_recipient_status'
                    """
                )
            ).scalar()
            assert check_gone is None

        # 3) Re-upgrade to 0015 and leave disposable DB at expected head.
        _alembic(_REV_0015, direction="upgrade")
        with engine.begin() as connection:
            rev = _revision(connection)
            if rev != _REV_0015:
                pytest.fail(f"re-upgrade to {_REV_0015} failed; revision={rev!r}")
            if not _has_status_column(connection):
                pytest.fail("recipient_status missing after re-upgrade to 0015")
            status = connection.execute(
                text("SELECT recipient_status FROM erp.recipient WHERE id = :id"),
                {"id": recipient_id},
            ).scalar_one()
            assert status == "ACTIVE"
    finally:
        engine.dispose()
