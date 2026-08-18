"""Unit contract for the 0026 FAMILY CHECK exact-compare normalizer."""

from __future__ import annotations

from pathlib import Path

from app.db.postcheck_current_0026 import (
    ERP_APP_SEQUENCE_PRIVILEGES,
    ERP_BACKUP_SEQUENCE_PRIVILEGES,
    EXACT_CARE_ASSIGNMENT_EXCLUSION,
    EXACT_CARE_ASSIGNMENT_FAMILY_CHECK,
    EXACT_CARE_ASSIGNMENT_KIND_CHECK,
    W1E_FORBIDDEN_LOCK_BODY_MARKERS,
    W1E_FORBIDDEN_LOCK_FUNCTION_NAMES,
    W1E_LOCK_FUNCTION_ARGUMENT_OIDS,
    W1E_LOCK_FUNCTION_ARGUMENTS,
    W1E_LOCK_FUNCTIONS,
    W1E_TRIGGER_EXPECTATIONS,
    _compact_constraint,
    _compact_sql,
    _function_body_is_expected,
    _migration_0012_function_bodies,
    _migration_0026_function_bodies,
    _strip_harmless_display_casts,
)
from app.db.w1e_family_relationship import FAMILY_RELATIONSHIP_TRIM_CHARS

_FAMILY_TRIM_CHARS = FAMILY_RELATIONSHIP_TRIM_CHARS


def test_family_check_exact_compare_uses_normalized_semantic_form() -> None:
    expected = _compact_constraint(EXACT_CARE_ASSIGNMENT_FAMILY_CHECK)
    pg_pretty = (
        "CHECK (((assignment_kind)::text <> 'FAMILY'::text) OR "
        "((family_relationship_text IS NOT NULL) AND "
        f"(btrim(family_relationship_text, '{_FAMILY_TRIM_CHARS}'::text) <> ''::text)))"
    )
    pg_pretty_16 = (
        "CHECK (((assignment_kind <> 'FAMILY'::text) OR "
        "((family_relationship_text IS NOT NULL) AND "
        f"(btrim(family_relationship_text, '{_FAMILY_TRIM_CHARS}'::text) <> ''::text))))"
    )
    migration = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "(family_relationship_text IS NOT NULL AND "
        f"btrim(family_relationship_text, '{_FAMILY_TRIM_CHARS}') <> ''))"
    )
    assert _compact_constraint(pg_pretty) == expected
    assert _compact_constraint(pg_pretty_16) == expected
    assert _compact_constraint(migration) == expected
    assert "btrim(family_relationship_text" in expected


def test_strip_harmless_display_casts_preserves_literals_and_quoted_identifiers() -> None:
    assert _strip_harmless_display_casts("'FAMILY::text'") == "'FAMILY::text'"
    assert _strip_harmless_display_casts('"FAMILY::text"') == '"FAMILY::text"'
    assert (
        _strip_harmless_display_casts("assignment_kind::text <> 'FAMILY'::text")
        == "assignment_kind <> 'FAMILY'"
    )


def test_strip_harmless_display_casts_preserves_non_text_casts() -> None:
    assert (
        _strip_harmless_display_casts("family_relationship_text::date IS NOT NULL")
        == "family_relationship_text::date IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts("family_relationship_text::int4 IS NOT NULL")
        == "family_relationship_text::int4 IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts("family_relationship_text::text IS NOT NULL")
        == "family_relationship_text IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts("family_relationship_text::TEXT IS NOT NULL")
        == "family_relationship_text IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts("family_relationship_text::varchar IS NOT NULL")
        == "family_relationship_text::varchar IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts("family_relationship_text::pg_catalog.text IS NOT NULL")
        == "family_relationship_text::pg_catalog.text IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts("family_relationship_text::citext IS NOT NULL")
        == "family_relationship_text::citext IS NOT NULL"
    )
    assert (
        _strip_harmless_display_casts('family_relationship_text::"text" IS NOT NULL')
        == 'family_relationship_text::"text" IS NOT NULL'
    )


def test_family_check_rejects_unquoted_family_cast_and_literal_cast_lookalike() -> None:
    expected = _compact_constraint(EXACT_CARE_ASSIGNMENT_FAMILY_CHECK)
    unquoted_cast = "CHECK (assignment_kind <> FAMILY::text)"
    assert _compact_constraint(unquoted_cast) != expected

    literal_cast_lookalike = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "family_relationship_text IS NOT NULL AND "
        "btrim(family_relationship_text) <> '::text')"
    )
    assert _compact_constraint(literal_cast_lookalike) != expected

    tab_only_trim = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "family_relationship_text IS NOT NULL AND "
        "btrim(family_relationship_text, '\t') <> '')"
    )
    space_only_trim = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "family_relationship_text IS NOT NULL AND "
        "btrim(family_relationship_text, ' ') <> '')"
    )
    assert _compact_constraint(tab_only_trim) != expected
    assert _compact_constraint(space_only_trim) != expected

    four_char_trim = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "family_relationship_text IS NOT NULL AND "
        "btrim(family_relationship_text, ' \t\n\r') <> '')"
    )
    assert _compact_constraint(four_char_trim) != expected


def test_family_check_rejects_semantic_date_cast_mutation() -> None:
    expected = _compact_constraint(EXACT_CARE_ASSIGNMENT_FAMILY_CHECK)
    date_cast_mutation = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "(family_relationship_text::date IS NOT NULL AND "
        "btrim(family_relationship_text) <> ''))"
    )
    assert _compact_constraint(date_cast_mutation) != expected
    assert "::date" in _compact_constraint(date_cast_mutation)

    varchar_cast_mutation = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "(family_relationship_text::varchar IS NOT NULL AND "
        f"btrim(family_relationship_text, '{_FAMILY_TRIM_CHARS}') <> ''))"
    )
    catalog_text_cast_mutation = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "(family_relationship_text::pg_catalog.text IS NOT NULL AND "
        f"btrim(family_relationship_text, '{_FAMILY_TRIM_CHARS}') <> ''))"
    )
    assert _compact_constraint(varchar_cast_mutation) != expected
    assert _compact_constraint(catalog_text_cast_mutation) != expected
    assert "::varchar" in _compact_constraint(varchar_cast_mutation)
    assert "::pg_catalog.text" in _compact_constraint(catalog_text_cast_mutation)


def test_kind_check_exact_compare_matches_pg16_any_array_deparse() -> None:
    expected = _compact_constraint(EXACT_CARE_ASSIGNMENT_KIND_CHECK)
    pg_pretty = "CHECK (assignment_kind = ANY (ARRAY['GENERAL'::text, 'FAMILY'::text]))"
    assert _compact_constraint(pg_pretty) == expected
    assert "assignment_kind=ANY" in expected
    assert "ARRAY['GENERAL','FAMILY']" in expected
    assert _compact_constraint("CHECK (assignment_kind = ANY (ARRAY['GENERAL'::text]))") != expected


def test_family_check_exact_compare_rejects_fragment_only_lookalikes() -> None:
    expected = _compact_constraint(EXACT_CARE_ASSIGNMENT_FAMILY_CHECK)
    weaker = "CHECK (assignment_kind <> 'FAMILY' OR family_relationship_text IS NOT NULL)"
    fragment_superset = (
        "CHECK (assignment_kind <> 'FAMILY' OR "
        "family_relationship_text IS NOT NULL AND "
        "btrim(family_relationship_text) <> '' OR TRUE)"
    )
    assert _compact_constraint(weaker) != expected
    assert _compact_constraint(fragment_superset) != expected


def test_family_check_exact_compare_preserves_boolean_grouping_parentheses() -> None:
    and_of_or = _compact_constraint("CHECK ((A OR B) AND C)")
    or_of_and = _compact_constraint("CHECK (A OR (B AND C))")
    assert and_of_or != or_of_and
    assert and_of_or == "check(AORB)ANDC"
    assert or_of_and == "checkAORBANDC"


def test_exclusion_compact_keeps_gist_predicate() -> None:
    pg_pretty = (
        "EXCLUDE USING gist (recipient_contract_id WITH =, staff_id WITH =, "
        "assignment_period WITH &&) WHERE ((invalidated_at_utc IS NULL))"
    )
    assert (
        _compact_constraint(pg_pretty).lower()
        == _compact_constraint(EXACT_CARE_ASSIGNMENT_EXCLUSION).lower()
    )


def test_compact_sql_preserves_keyword_token_boundaries() -> None:
    assert _compact_sql("NOT EXISTS") == "not exists"
    assert _compact_sql("NOTEXISTS") == "notexists"
    assert _compact_sql("NOT EXISTS") != _compact_sql("NOTEXISTS")

    assert _compact_sql("RETURN NEW") == "return new"
    assert _compact_sql("RETURNNEW") == "returnnew"
    assert _compact_sql("RETURN NEW") != _compact_sql("RETURNNEW")


def test_compact_sql_normalizes_formatting_without_losing_tokens() -> None:
    assert _compact_sql("RETURN  NEW") == "return new"
    assert _compact_sql("return\nnew") == "return new"
    assert _compact_sql("RETURN /* keep */ NEW") == "return new"
    assert _compact_sql("RAISE -- line comment\nEXCEPTION") == "raise exception"
    assert _compact_sql("a <@ b") == "a <@ b"
    assert _compact_sql("a<@b") == "a <@ b"


def test_compact_sql_preserves_string_and_quoted_identifier_case() -> None:
    message_compact = _compact_sql("MESSAGE = 'CARE_ASSIGNMENT'")
    assert message_compact == "message = 'CARE_ASSIGNMENT'"
    assert "'care_assignment'" not in message_compact
    assert _compact_sql('"CareAssignment"') != _compact_sql('"careassignment"')


def test_marker_carrying_dead_code_mutation_is_rejected_by_exact_body_compare() -> None:
    expected_bodies = _migration_0026_function_bodies()
    function_name = "fn_care_assignment_within_contract"
    expected_body = expected_bodies[function_name]
    dead_code = """
BEGIN
    IF FALSE THEN
        PERFORM erp.fn_w1e_lock_assignment_path(
            NEW.recipient_contract_id,
            NEW.employment_id
        );
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD';
        PERFORM NEW.assignment_period <@ contract.contract_period
            FROM erp.recipient_contract contract
            WHERE contract.invalidated_at_utc IS NULL;
    END IF;
    RETURN NEW;
END
"""
    markers = W1E_TRIGGER_EXPECTATIONS[("care_assignment", "ct_care_assignment_within_contract")][
        "markers"
    ]
    compact_dead_code = _compact_sql(dead_code)
    assert all(_compact_sql(marker) in compact_dead_code for marker in markers)
    assert not _function_body_is_expected(function_name, dead_code)
    assert _function_body_is_expected(function_name, expected_body)


def test_care_assignment_sequence_acl_matches_0012_app_and_backup_contract() -> None:
    assert ERP_APP_SEQUENCE_PRIVILEGES == (True, True, False, False, False, False)
    assert ERP_BACKUP_SEQUENCE_PRIVILEGES == (False, True, False, False, False, False)


def test_current_0026_lock_functions_are_exact_and_present_in_migration() -> None:
    bodies = _migration_0026_function_bodies()
    assert set(W1E_LOCK_FUNCTIONS) <= set(bodies)
    assert set(W1E_LOCK_FUNCTION_ARGUMENT_OIDS) == set(W1E_LOCK_FUNCTIONS)
    assert set(W1E_LOCK_FUNCTION_ARGUMENTS) == set(W1E_LOCK_FUNCTIONS)
    assert W1E_LOCK_FUNCTION_ARGUMENT_OIDS["fn_w1e_lock_contract_path"] == (20,)
    assert W1E_LOCK_FUNCTION_ARGUMENT_OIDS["fn_w1e_lock_assignment_path"] == (20, 20)
    assert W1E_LOCK_FUNCTION_ARGUMENTS["fn_w1e_lock_employment_assignment_edges"] == (
        "p_employment_id bigint, p_staff_id bigint"
    )
    assert _function_body_is_expected(
        "fn_w1e_lock_assignment_path",
        bodies["fn_w1e_lock_assignment_path"],
    )
    assert "fn_w1e_lock_global" not in bodies
    assert "erp.w1e.global" not in str(bodies)
    assert W1E_FORBIDDEN_LOCK_FUNCTION_NAMES == ("fn_w1e_lock_global",)
    assert W1E_FORBIDDEN_LOCK_BODY_MARKERS == (
        "fn_w1e_lock_global",
        "erp.w1e.global",
    )

    contract_lock = _compact_sql(bodies["fn_w1e_lock_contract_path"])
    assert "pg_try_advisory_xact_lock" in contract_lock
    assert "'erp.w1e.contract'" in contract_lock
    assert "'55P03'" in contract_lock
    assert "'CARE_ASSIGNMENT_CONCURRENT_CONFLICT'" in contract_lock
    assert "fn_w1e_lock_global" not in contract_lock
    assert _function_body_is_expected(
        "fn_w1e_lock_contract_path", bodies["fn_w1e_lock_contract_path"]
    )

    employment_lock = _compact_sql(bodies["fn_w1e_lock_employment_path"])
    assert "pg_try_advisory_xact_lock" in employment_lock
    assert "'erp.w1e.employment'" in employment_lock
    assert "'55P03'" in employment_lock
    assert "'CARE_ASSIGNMENT_CONCURRENT_CONFLICT'" in employment_lock
    assert "fn_w1e_lock_global" not in employment_lock
    assert _function_body_is_expected(
        "fn_w1e_lock_employment_path", bodies["fn_w1e_lock_employment_path"]
    )

    assignment_lock = _compact_sql(bodies["fn_w1e_lock_assignment_path"])
    assert "fn_w1e_lock_contract_path" in assignment_lock
    assert "fn_w1e_lock_employment_path" in assignment_lock
    assert assignment_lock.index("fn_w1e_lock_contract_path") < assignment_lock.index(
        "fn_w1e_lock_employment_path"
    )
    assert "fn_w1e_lock_global" not in assignment_lock

    contract_edges_lock = _compact_sql(bodies["fn_w1e_lock_contract_assignment_edges"])
    assert "fn_w1e_lock_global" not in contract_edges_lock
    assert "fn_w1e_lock_contract_path" in contract_edges_lock
    assert "fn_w1e_lock_employment_path" in contract_edges_lock
    assert "fn_w1e_lock_assignment_path" not in contract_edges_lock
    assert "select distinct assignment . recipient_contract_id" in contract_edges_lock
    assert "select distinct assignment . employment_id" in contract_edges_lock
    assert "order by assignment . recipient_contract_id" in contract_edges_lock
    assert "order by assignment . employment_id" in contract_edges_lock
    assert contract_edges_lock.count("fn_w1e_lock_contract_path") == 2
    assert contract_edges_lock.count("fn_w1e_lock_employment_path") == 1
    assert contract_edges_lock.index("for edge in") < contract_edges_lock.index(
        "if not locked_edge then"
    )
    assert contract_edges_lock.index("if not locked_edge then") < contract_edges_lock.index(
        "fn_w1e_lock_employment_path"
    )
    assert (
        "if not locked_edge then perform erp . fn_w1e_lock_contract_path ( p_contract_id ) ; end if"
    ) in contract_edges_lock

    employment_edges_lock = _compact_sql(bodies["fn_w1e_lock_employment_assignment_edges"])
    assert "fn_w1e_lock_global" not in employment_edges_lock
    assert "fn_w1e_lock_contract_path" in employment_edges_lock
    assert "fn_w1e_lock_employment_path" in employment_edges_lock
    assert "fn_w1e_lock_assignment_path" not in employment_edges_lock
    assert "select distinct assignment . recipient_contract_id" in employment_edges_lock
    assert "select distinct assignment . employment_id" not in employment_edges_lock
    assert "order by assignment . recipient_contract_id" in employment_edges_lock
    assert "order by assignment . employment_id" not in employment_edges_lock
    assert employment_edges_lock.count("fn_w1e_lock_contract_path") == 1
    assert employment_edges_lock.count("fn_w1e_lock_employment_path") == 1
    assert "locked_edge" not in employment_edges_lock
    assert "if not locked_edge then" not in employment_edges_lock
    assert employment_edges_lock.index("fn_w1e_lock_contract_path") < employment_edges_lock.index(
        "fn_w1e_lock_employment_path"
    )
    assert (
        "perform erp . fn_w1e_lock_employment_path ( p_employment_id ) ;"
    ) in employment_edges_lock


def test_historical_0012_oracle_is_preserved() -> None:
    historical_bodies = _migration_0012_function_bodies()
    current_bodies = _migration_0026_function_bodies()
    for function_name in (
        "fn_care_assignment_within_contract",
        "fn_care_assignment_within_employment",
        "fn_care_assignment_within_position",
        "fn_care_assignment_general_care_qualified",
        "fn_recipient_contract_assignment_reverse_guard",
        "fn_staff_employment_child_periods_reverse_guard",
        "fn_staff_position_care_assignment_reverse_guard",
        "fn_staff_service_qualification_assignment_reverse_guard",
    ):
        assert function_name in historical_bodies
        assert function_name in current_bodies
        assert _compact_sql(historical_bodies[function_name]) != _compact_sql(
            current_bodies[function_name]
        )


def test_ubuntu_restore_tooling_is_cross_platform_path_aware() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    postgres_tools = (repo_root / "scripts" / "PostgresTools.psm1").read_text(encoding="utf-8")
    restore_drill = (repo_root / "scripts" / "restore-drill.ps1").read_text(encoding="utf-8")

    assert "Win32NT" in postgres_tools
    assert ".exe" in postgres_tools
    assert ".venv/bin/python" in restore_drill
    assert ".venv\\Scripts\\python.exe" in restore_drill


def test_w1e_harness_manifest_includes_postgres_tools_module() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    harness = (repo_root / "scripts" / "test-w1e-0026-postgres-linux.ps1").read_text(
        encoding="utf-8"
    )
    assert '"scripts/PostgresTools.psm1"' in harness
    assert '"scripts/RuntimeVersion.psm1"' in harness
