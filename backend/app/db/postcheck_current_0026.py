"""Focused catalog postcheck for the corrected W1/W2 0026 head.

This module verifies the exact current head after the forward W1E FAMILY
relationship lock.  The historical 0025 verifier remains unchanged as
historical evidence; current-head readiness and restore paths must use only
this verifier.
"""

from __future__ import annotations

import re
from collections.abc import Set
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.session import create_postgres_engine
from app.db.w1e_family_relationship import (
    FAMILY_RELATIONSHIP_TRIM_CHARS,
    family_relationship_present_predicate_sql,
)

EXPECTED_REVISION = "20260814_0026_w1e_care_assignment_family_relationship_lock"

EXACT_TRAINING_CODES = (
    "NEW_HIRE_ORIENTATION",
    "ELDER_RIGHTS",
    "DISABLED_ABUSE",
    "ELDER_ABUSE",
    "SEXUAL_HARASSMENT",
    "WORKPLACE_BULLYING",
    "PRIVACY",
    "CONTINUING_EDUCATION",
)

REQUIRED_W2_TABLES = {
    "monthly_professional_assignment",
    "w2_schedule_month_control",
    "w2_schedule",
    "w2_schedule_staff",
    "w2_personal_todo_list",
    "w2_personal_todo",
    "w2_official_work_card",
    "w2_service_plan_notice",
}

FORBIDDEN_CURRENT_TABLES = {
    "staff_health_check_requirement",
    "recipient_guardian_primary_period",
    "recipient_payer_snapshot",
    "recipient_grade_period",
}

REQUIRED_TRIGGERS = {
    "biu_recipient_guardian_assign_slot",
    "ct_care_assignment_within_contract",
    "ct_care_assignment_within_employment",
    "ct_care_assignment_within_position",
    "ct_care_assignment_general_care_qualified",
    "ct_staff_employment_child_periods_reverse_guard",
    "ct_recipient_contract_assignment_reverse_guard",
    "ct_staff_position_care_assignment_reverse_guard",
    "ct_staff_service_qualification_assignment_reverse_guard",
    "ct_monthly_professional_assignment_fact_guard",
    "bd_biu_w2_schedule_month_guard",
    "bd_biu_w2_schedule_staff_month_guard",
    "ct_w2_schedule_staff_contract_from_schedule",
    "ct_w2_schedule_staff_contract_from_staff",
    "bu_w2_schedule_month_finalize_guard",
    "ct_w2_service_plan_notice_guard",
    "ct_w2_service_plan_contract_reverse_guard",
    "ct_w2_service_plan_certification_reverse_guard",
    "tr_recipient_plan_notification_read_only",
}

REQUIRED_W1E_ORIGIN_TRIGGERS = {
    ("care_assignment", "ct_care_assignment_within_contract"),
    ("care_assignment", "ct_care_assignment_within_employment"),
    ("care_assignment", "ct_care_assignment_within_position"),
    ("care_assignment", "ct_care_assignment_general_care_qualified"),
    ("recipient_contract", "ct_recipient_contract_assignment_reverse_guard"),
    ("staff_employment", "ct_staff_employment_child_periods_reverse_guard"),
    ("staff_position_period", "ct_staff_position_care_assignment_reverse_guard"),
    (
        "staff_service_qualification_period",
        "ct_staff_service_qualification_assignment_reverse_guard",
    ),
}

W1E_LOCK_FUNCTIONS: dict[str, int] = {
    "fn_w1e_lock_contract_path": 1,
    "fn_w1e_lock_employment_path": 1,
    "fn_w1e_lock_assignment_path": 2,
    "fn_w1e_lock_contract_assignment_edges": 1,
    "fn_w1e_lock_employment_assignment_edges": 2,
}

# PostgreSQL's built-in bigint OID is stable in the supported catalogs, and the
# ``pg_proc.proargtypes`` oidvector deparses those OIDs as space-separated
# numbers.  Exact OID and argument-name checks prevent an integer overload or a
# renamed argument from evading the expected bigint helper while still passing a
# pronargs-only check.
W1E_LOCK_FUNCTION_ARGUMENT_OIDS: dict[str, tuple[int, ...]] = {
    "fn_w1e_lock_contract_path": (20,),
    "fn_w1e_lock_employment_path": (20,),
    "fn_w1e_lock_assignment_path": (20, 20),
    "fn_w1e_lock_contract_assignment_edges": (20,),
    "fn_w1e_lock_employment_assignment_edges": (20, 20),
}

W1E_LOCK_FUNCTION_ARGUMENTS: dict[str, str] = {
    "fn_w1e_lock_contract_path": "p_contract_id bigint",
    "fn_w1e_lock_employment_path": "p_employment_id bigint",
    "fn_w1e_lock_assignment_path": "p_contract_id bigint, p_employment_id bigint",
    "fn_w1e_lock_contract_assignment_edges": "p_contract_id bigint",
    "fn_w1e_lock_employment_assignment_edges": "p_employment_id bigint, p_staff_id bigint",
}

W1E_FORBIDDEN_LOCK_FUNCTION_NAMES: tuple[str, ...] = ("fn_w1e_lock_global",)
W1E_FORBIDDEN_LOCK_BODY_MARKERS: tuple[str, ...] = (
    "fn_w1e_lock_global",
    "erp.w1e.global",
)


class W1ETriggerExpectation(TypedDict):
    function: str
    tgtype: int
    markers: tuple[str, ...]


W1E_TRIGGER_EXPECTATIONS: dict[tuple[str, str], W1ETriggerExpectation] = {
    ("care_assignment", "ct_care_assignment_within_contract"): {
        "function": "fn_care_assignment_within_contract",
        "tgtype": 21,  # AFTER INSERT OR UPDATE, FOR EACH ROW
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD'",
            (
                "PERFORM erp.fn_w1e_lock_assignment_path("
                "NEW.recipient_contract_id, NEW.employment_id)"
            ),
            "NEW.assignment_period <@ contract.contract_period",
            "FROM erp.recipient_contract contract",
            "contract.invalidated_at_utc IS NULL",
        ),
    },
    ("care_assignment", "ct_care_assignment_within_employment"): {
        "function": "fn_care_assignment_within_employment",
        "tgtype": 21,
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD'",
            (
                "PERFORM erp.fn_w1e_lock_assignment_path("
                "NEW.recipient_contract_id, NEW.employment_id)"
            ),
            "NEW.assignment_period <@ employment.employment_period",
            "FROM erp.staff_employment employment",
            "employment.invalidated_at_utc IS NULL",
        ),
    },
    ("care_assignment", "ct_care_assignment_within_position"): {
        "function": "fn_care_assignment_within_position",
        "tgtype": 21,
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_STAFF_INELIGIBLE'",
            (
                "PERFORM erp.fn_w1e_lock_assignment_path("
                "NEW.recipient_contract_id, NEW.employment_id)"
            ),
            "NEW.assignment_kind = 'GENERAL'",
            "FROM erp.staff_position_period position",
            "position.position_code = 'CARE_WORKER'",
            "range_agg(position.position_period)",
        ),
    },
    ("care_assignment", "ct_care_assignment_general_care_qualified"): {
        "function": "fn_care_assignment_general_care_qualified",
        "tgtype": 21,
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_STAFF_INELIGIBLE'",
            (
                "PERFORM erp.fn_w1e_lock_assignment_path("
                "NEW.recipient_contract_id, NEW.employment_id)"
            ),
            "NEW.assignment_kind = 'GENERAL'",
            "FROM erp.staff_service_qualification_period qualification",
            "qualification.service_type_id = contract.service_type_id",
            "range_agg(qualification.qualification_period)",
        ),
    },
    ("recipient_contract", "ct_recipient_contract_assignment_reverse_guard"): {
        "function": "fn_recipient_contract_assignment_reverse_guard",
        "tgtype": 17,  # AFTER UPDATE, FOR EACH ROW
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN'",
            "PERFORM erp.fn_w1e_lock_contract_assignment_edges(NEW.id)",
            "FROM erp.care_assignment assignment",
            "assignment.recipient_contract_id = NEW.id",
            "assignment.invalidated_at_utc IS NULL",
            "NEW.invalidated_at_utc IS NOT NULL",
            "NOT (assignment.assignment_period <@ NEW.contract_period)",
        ),
    },
    ("staff_employment", "ct_staff_employment_child_periods_reverse_guard"): {
        "function": "fn_staff_employment_child_periods_reverse_guard",
        "tgtype": 17,
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'STAFF_PERIOD_OUTSIDE_EMPLOYMENT'",
            "PERFORM erp.fn_w1e_lock_employment_assignment_edges(NEW.id, NEW.staff_id)",
            "FROM erp.care_assignment child",
            "child.employment_id = NEW.id",
            "child.staff_id = NEW.staff_id",
            "child.invalidated_at_utc IS NULL",
        ),
    },
    ("staff_position_period", "ct_staff_position_care_assignment_reverse_guard"): {
        "function": "fn_staff_position_care_assignment_reverse_guard",
        "tgtype": 17,
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN'",
            "PERFORM erp.fn_w1e_lock_employment_assignment_edges(OLD.employment_id, OLD.staff_id)",
            "FROM erp.care_assignment assignment",
            "assignment.staff_id = OLD.staff_id",
            "assignment.employment_id = OLD.employment_id",
            "assignment.assignment_kind = 'GENERAL'",
            "assignment.invalidated_at_utc IS NULL",
        ),
    },
    (
        "staff_service_qualification_period",
        "ct_staff_service_qualification_assignment_reverse_guard",
    ): {
        "function": "fn_staff_service_qualification_assignment_reverse_guard",
        "tgtype": 17,
        "markers": (
            "RAISE EXCEPTION",
            "ERRCODE = '23514'",
            "MESSAGE = 'CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN'",
            "PERFORM erp.fn_w1e_lock_employment_assignment_edges(OLD.employment_id, OLD.staff_id)",
            "FROM erp.care_assignment assignment",
            "JOIN erp.recipient_contract contract",
            "contract.service_type_id = OLD.service_type_id",
            "assignment.assignment_kind = 'GENERAL'",
            "assignment.invalidated_at_utc IS NULL",
        ),
    },
}

EXACT_CARE_ASSIGNMENT_EXCLUSION = (
    "EXCLUDE USING gist (recipient_contract_id WITH =, staff_id WITH =, "
    "assignment_period WITH &&) WHERE (invalidated_at_utc IS NULL)"
)

# PG16 pg_get_constraintdef(oid, true) deparses the historical 0012
# ``CHECK (assignment_kind IN ('GENERAL', 'FAMILY'))`` as an ANY(ARRAY[...])
# expression.  Keep the current-head expectation in that exact deparse form so
# the comparison remains byte-for-byte after display-cast/parenthesis removal.
EXACT_CARE_ASSIGNMENT_KIND_CHECK = "CHECK (assignment_kind = ANY (ARRAY['GENERAL', 'FAMILY']))"

# Canonical ASCII trim set is owned by ``app.db.w1e_family_relationship``.
# PostgreSQL deparses the migration E-string as a standard string literal
# containing those exact control characters, so the exact expected CHECK
# must carry the same bytes rather than the E-string source form.
_FAMILY_RELATIONSHIP_TRIM_CHARS = FAMILY_RELATIONSHIP_TRIM_CHARS

EXACT_CARE_ASSIGNMENT_FAMILY_CHECK = "CHECK (" + family_relationship_present_predicate_sql() + ")"

ERP_APP_WRITE_PRIVILEGES = (
    True,  # SELECT
    True,  # INSERT
    True,  # UPDATE
    False,  # DELETE
    False,  # TRUNCATE
    False,  # REFERENCES
    False,  # TRIGGER
    False,  # SELECT WITH GRANT OPTION
    False,  # INSERT WITH GRANT OPTION
    False,  # UPDATE WITH GRANT OPTION
)

ERP_APP_READ_ONLY_PRIVILEGES = (
    True,  # SELECT
    False,  # INSERT
    False,  # UPDATE
    False,  # DELETE
    False,  # TRUNCATE
    False,  # REFERENCES
    False,  # TRIGGER
    False,  # SELECT WITH GRANT OPTION
    False,  # INSERT WITH GRANT OPTION
    False,  # UPDATE WITH GRANT OPTION
)

# 0012 GRANTs only nextval/currval to erp_app for the care_assignment identity
# and SELECT-only to erp_backup (USAGE revoked). Any setval (UPDATE) or grant
# option is an ACL drift that the current-head postcheck must reject fail-closed.
ERP_APP_SEQUENCE_PRIVILEGES = (
    True,  # USAGE
    True,  # SELECT
    False,  # UPDATE
    False,  # USAGE WITH GRANT OPTION
    False,  # SELECT WITH GRANT OPTION
    False,  # UPDATE WITH GRANT OPTION
)

ERP_BACKUP_SEQUENCE_PRIVILEGES = (
    False,  # USAGE
    True,  # SELECT
    False,  # UPDATE
    False,  # USAGE WITH GRANT OPTION
    False,  # SELECT WITH GRANT OPTION
    False,  # UPDATE WITH GRANT OPTION
)

OFFICIAL_CARD_KINDS = {
    "RECOGNITION_EXPIRY",
    "CONTRACT_EXPIRY",
    "PLAN_NOTICE",
    "STAFF_REPLACEMENT_CONSULTATION",
    "NEW_STAFF_WORK",
}


def _columns(connection: Connection, table_name: str) -> dict[str, bool]:
    return {
        str(name): nullable == "YES"
        for name, nullable in connection.execute(
            text(
                """
                SELECT column_name, is_nullable
                  FROM information_schema.columns
                 WHERE table_schema = 'erp' AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).all()
    }


def _require_columns(
    columns: dict[str, bool],
    *,
    required: dict[str, bool],
    forbidden: Set[str] = frozenset(),
    label: str,
) -> None:
    missing = sorted(set(required) - columns.keys())
    present_forbidden = sorted(forbidden & columns.keys())
    wrong_nullability = sorted(
        name for name, nullable in required.items() if columns.get(name) != nullable
    )
    if missing or present_forbidden or wrong_nullability:
        raise SystemExit(
            f"{label} column contract mismatch: missing={missing}, "
            f"forbidden={present_forbidden}, nullability={wrong_nullability}"
        )


def _privileges(connection: Connection, role: str, table_name: str) -> tuple[bool, ...]:
    return tuple(
        bool(value)
        for value in connection.execute(
            text(
                """
                SELECT has_table_privilege(:role, :table_name, 'SELECT'),
                       has_table_privilege(:role, :table_name, 'INSERT'),
                       has_table_privilege(:role, :table_name, 'UPDATE'),
                       has_table_privilege(:role, :table_name, 'DELETE'),
                       has_table_privilege(:role, :table_name, 'TRUNCATE'),
                       has_table_privilege(:role, :table_name, 'REFERENCES'),
                       has_table_privilege(:role, :table_name, 'TRIGGER'),
                       has_table_privilege(
                           :role, :table_name, 'SELECT WITH GRANT OPTION'
                       ),
                       has_table_privilege(
                           :role, :table_name, 'INSERT WITH GRANT OPTION'
                       ),
                       has_table_privilege(
                           :role, :table_name, 'UPDATE WITH GRANT OPTION'
                       )
                """
            ),
            {"role": role, "table_name": f"erp.{table_name}"},
        ).one()
    )


def _sequence_privileges(
    connection: Connection,
    role: str,
    sequence_name: str,
) -> tuple[bool, ...]:
    return tuple(
        bool(value)
        for value in connection.execute(
            text(
                """
                SELECT has_sequence_privilege(:role, :sequence_name, 'USAGE'),
                       has_sequence_privilege(:role, :sequence_name, 'SELECT'),
                       has_sequence_privilege(:role, :sequence_name, 'UPDATE'),
                       has_sequence_privilege(
                           :role, :sequence_name, 'USAGE WITH GRANT OPTION'
                       ),
                       has_sequence_privilege(
                           :role, :sequence_name, 'SELECT WITH GRANT OPTION'
                       ),
                       has_sequence_privilege(
                           :role, :sequence_name, 'UPDATE WITH GRANT OPTION'
                       )
                """
            ),
            {"role": role, "sequence_name": sequence_name},
        ).one()
    )


# PostgreSQL 16.14 pg_trigger.tgtype bits (src/include/catalog/pg_trigger.h).
_TG_TYPE_ROW = 1
_TG_TYPE_BEFORE = 2
_TG_TYPE_INSERT = 4
_TG_TYPE_DELETE = 8
_TG_TYPE_UPDATE = 16
_TG_TYPE_TRUNCATE = 32
_TG_TYPE_INSTEAD = 64


_NON_CALL_KEYWORDS = frozenset(
    {
        "and",
        "or",
        "not",
        "in",
        "is",
        "null",
        "where",
        "on",
        "using",
        "check",
        "exclude",
        "when",
        "then",
        "else",
        "case",
        "between",
    }
)


def _identifier_before(expression: str, open_index: int) -> str:
    end = open_index
    start = end
    while start > 0 and (expression[start - 1].isalnum() or expression[start - 1] == "_"):
        start -= 1
    return expression[start:end]


def _scan_quoted(expression: str, start: int, quote: str) -> int:
    """Return the index just past a single/double quoted SQL literal/identifier.

    Doubled quote characters inside the quoted span are treated as escaped
    quote characters and are never interpreted as the closing delimiter.
    """

    end = start + 1
    while end < len(expression):
        if expression[end] == quote:
            if end + 1 < len(expression) and expression[end + 1] == quote:
                end += 2
                continue
            return end + 1
        end += 1
    return len(expression)


def _strip_harmless_display_casts(compact: str) -> str:
    """Remove only PG16 pretty-printing ``::text`` casts.

    PostgreSQL ``pg_get_constraintdef(oid, true)`` inserts display-only
    ``::text`` casts for literal/identifier pretty-printing.  Any other cast,
    for example ``family_relationship_text::date``, is semantically meaningful
    and must be preserved so a different CHECK predicate cannot normalize to
    the expected semantic form.  The scan is token-aware so ``::type`` inside a
    single-quoted string literal or quoted identifier is preserved
    byte-for-byte.
    """

    output: list[str] = []
    index = 0
    length = len(compact)
    while index < length:
        character = compact[index]
        if character in ("'", '"'):
            end = _scan_quoted(compact, index, character)
            output.append(compact[index:end])
            index = end
            continue
        if compact.startswith("::", index):
            cursor = index + 2
            while cursor < length and (compact[cursor].isalnum() or compact[cursor] == "_"):
                cursor += 1
            type_name = compact[index + 2 : cursor]
            if type_name.lower() == "text":
                index = cursor
                continue
        output.append(character)
        index += 1
    return "".join(output)


def _collapse_constraint_whitespace_preserving_literals(definition: str) -> str:
    """Collapse display whitespace without touching literals/quoted identifiers.

    ``pg_get_constraintdef(oid, true)`` can contain real tab/newline/carriage
    return characters inside string literals (for example the FAMILY trim set).
    Generic whitespace normalization must not rewrite those bytes, otherwise a
    check that trims a different character set could compare equal to the
    expected FAMILY check.
    """

    output: list[str] = []
    index = 0
    length = len(definition)
    pending_space = False
    while index < length:
        character = definition[index]
        if character.isspace():
            if output and output[-1] != " ":
                pending_space = True
            index += 1
            continue
        if character in ("'", '"'):
            if pending_space:
                output.append(" ")
                pending_space = False
            end = _scan_quoted(definition, index, character)
            output.append(definition[index:end])
            index = end
            continue
        if pending_space:
            output.append(" ")
            pending_space = False
        output.append(character)
        index += 1
    return "".join(output).strip()


def _strip_exclude_display_parentheses(expression: str) -> str:
    """Normalize EXCLUDE element-list and outer WHERE predicate parentheses.

    ``EXCLUDE USING gist (...)`` is an index-element list, not a function call,
    and must be preserved.  The outer ``WHERE (...)`` wrapper is display-only.
    """

    keep = [False] * len(expression)
    stack: list[int] = []
    for index, character in enumerate(expression):
        if character == "(":
            stack.append(index)
        elif character == ")" and stack:
            open_index = stack.pop()
            identifier = _identifier_before(expression, open_index)
            if identifier and identifier.lower() not in _NON_CALL_KEYWORDS:
                keep[open_index] = True
                keep[index] = True
    return "".join(
        character
        for index, character in enumerate(expression)
        if character not in "()" or keep[index]
    )


_BOOLEAN_OPERATORS = ("<>", "!=", "<=", ">=", "=", "<", ">")
_BOOLEAN_PRECEDENCE = {"or": 1, "and": 2, "not": 3, "raw": 4}


def _tokenize_boolean_expression(expression: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(expression):
        character = expression[index]
        if character.isspace():
            index += 1
            continue
        if character == "'":
            end = index + 1
            while end < len(expression):
                if expression[end] == "'":
                    if end + 1 < len(expression) and expression[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            tokens.append(expression[index:end])
            index = end
        elif character in "()":
            tokens.append(character)
            index += 1
        elif character.isalpha() or character == "_":
            end = index + 1
            while end < len(expression) and (expression[end].isalnum() or expression[end] in "_$"):
                end += 1
            tokens.append(expression[index:end])
            index = end
        elif character.isdigit():
            end = index + 1
            while end < len(expression) and (expression[end].isdigit() or expression[end] == "."):
                end += 1
            tokens.append(expression[index:end])
            index = end
        else:
            for operator in _BOOLEAN_OPERATORS:
                if expression.startswith(operator, index):
                    tokens.append(operator)
                    index += len(operator)
                    break
            else:
                tokens.append(character)
                index += 1
    return tokens


def _is_identifier_token(token: str) -> bool:
    return bool(token) and (token[0].isalpha() or token[0] == "_")


@dataclass(frozen=True)
class _BooleanNode:
    kind: str
    value: str | None = None
    children: tuple[_BooleanNode, ...] = ()


class _BooleanExpressionParser:
    def __init__(self, expression: str) -> None:
        self.tokens = _tokenize_boolean_expression(expression)
        self.position = 0

    def parse(self) -> str:
        node = self._parse_or()
        if self.position != len(self.tokens):
            raise ValueError("trailing tokens in boolean expression")
        return _render_boolean_node(node, 0)

    def _peek(self) -> str | None:
        if self.position >= len(self.tokens):
            return None
        return self.tokens[self.position]

    def _peek_upper(self) -> str | None:
        token = self._peek()
        return None if token is None else token.upper()

    def _consume(self) -> str:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of boolean expression")
        self.position += 1
        return token

    def _expect(self, token: str) -> None:
        if self._peek() != token:
            raise ValueError(f"expected {token!r}")
        self.position += 1

    def _parse_or(self) -> _BooleanNode:
        node = self._parse_and()
        while self._peek_upper() == "OR":
            self.position += 1
            node = _BooleanNode("or", children=(node, self._parse_and()))
        return node

    def _parse_and(self) -> _BooleanNode:
        node = self._parse_not()
        while self._peek_upper() == "AND":
            self.position += 1
            node = _BooleanNode("and", children=(node, self._parse_not()))
        return node

    def _parse_not(self) -> _BooleanNode:
        if self._peek_upper() == "NOT":
            self.position += 1
            return _BooleanNode("not", children=(self._parse_not(),))
        return self._parse_predicate()

    def _parse_predicate(self) -> _BooleanNode:
        left = self._parse_value()
        if left.kind == "group" and not (
            self._peek_upper() == "IS" or self._peek() in _BOOLEAN_OPERATORS
        ):
            return left
        if self._peek_upper() == "IS":
            self.position += 1
            not_part = ""
            if self._peek_upper() == "NOT":
                not_part = self._consume()
            right_token = self._consume()
            return _BooleanNode(
                "raw",
                value=_render_boolean_node(left, 4) + "IS" + not_part + right_token,
            )
        for operator in _BOOLEAN_OPERATORS:
            if self._peek() == operator:
                self.position += 1
                right_node = self._parse_value()
                return _BooleanNode(
                    "raw",
                    value=(
                        _render_boolean_node(left, 4)
                        + operator
                        + _render_boolean_node(right_node, 4)
                    ),
                )
        return _BooleanNode("raw", value=_render_boolean_node(left, 4))

    def _parse_value(self) -> _BooleanNode:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of boolean expression")
        if token == "(":
            self.position += 1
            child = self._parse_or()
            self._expect(")")
            return _BooleanNode("group", children=(child,))
        if _is_identifier_token(token):
            self.position += 1
            if self._peek() == "(":
                return _BooleanNode("raw", value=self._consume_function_call(token))
            return _BooleanNode("raw", value=token)
        self.position += 1
        return _BooleanNode("raw", value=token)

    def _consume_function_call(self, identifier: str) -> str:
        parts = [identifier, "("]
        self.position += 1
        depth = 1
        while self.position < len(self.tokens) and depth > 0:
            token = self.tokens[self.position]
            self.position += 1
            parts.append(token)
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
        if depth != 0:
            raise ValueError("unbalanced function call parentheses")
        return "".join(parts)


def _node_precedence(node: _BooleanNode) -> int:
    if node.kind == "group":
        return _node_precedence(node.children[0])
    return _BOOLEAN_PRECEDENCE.get(node.kind, 4)


def _render_boolean_node(node: _BooleanNode, parent_precedence: int) -> str:
    if node.kind == "raw":
        return node.value or ""
    if node.kind == "group":
        child = node.children[0]
        rendered = _render_boolean_node(child, 0)
        if _node_precedence(child) < parent_precedence:
            return "(" + rendered + ")"
        return rendered
    if node.kind == "not":
        return "NOT" + _render_boolean_node(node.children[0], _BOOLEAN_PRECEDENCE["not"])
    if node.kind == "and":
        return (
            _render_boolean_node(node.children[0], _BOOLEAN_PRECEDENCE["and"])
            + "AND"
            + _render_boolean_node(node.children[1], _BOOLEAN_PRECEDENCE["and"])
        )
    if node.kind == "or":
        return (
            _render_boolean_node(node.children[0], _BOOLEAN_PRECEDENCE["or"])
            + "OR"
            + _render_boolean_node(node.children[1], _BOOLEAN_PRECEDENCE["or"])
        )
    raise ValueError(f"unknown boolean node kind: {node.kind!r}")


def _strip_grouping_parentheses(expression: str) -> str:
    """Remove only redundant display parentheses.

    Function-call parentheses and boolean grouping parentheses that change
    operator precedence are preserved, so PG16 pretty-printed CHECK predicates
    normalize to the migration semantic form without collapsing
    ``(A OR B) AND C`` into ``A OR (B AND C)``.
    """

    return _BooleanExpressionParser(expression).parse()


def _normalize_check_constraint(compact: str) -> str:
    open_index = compact.find("(")
    if open_index < 0:
        raise ValueError("CHECK constraint without parenthesized expression")
    depth = 0
    for index in range(open_index, len(compact)):
        character = compact[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                inner = compact[open_index + 1 : index]
                suffix = re.sub(r"\s+", "", compact[index + 1 :])
                return "check" + _strip_grouping_parentheses(inner) + suffix
    raise ValueError("CHECK constraint has unbalanced parentheses")


def _compact_constraint(definition: str) -> str:
    """Normalize PG 16.14 CHECK/EXCLUDE display to the migration semantic form.

    ``pg_get_constraintdef(oid, true)`` may insert ``::text`` casts and extra
    grouping parentheses.  Display casts and redundant predicate parentheses
    are removed, but boolean grouping parentheses and function-call parentheses
    are preserved so the comparison remains exact.
    """

    compact = re.sub(r"\s+", "", definition)
    compact = _strip_harmless_display_casts(compact)
    upper = compact.upper()
    try:
        if upper.startswith("CHECK"):
            spaced = _collapse_constraint_whitespace_preserving_literals(definition)
            return _normalize_check_constraint(_strip_harmless_display_casts(spaced))
        if upper.startswith("EXCLUDE"):
            return _strip_exclude_display_parentheses(compact)
        spaced = _collapse_constraint_whitespace_preserving_literals(definition)
        return _strip_grouping_parentheses(_strip_harmless_display_casts(spaced))
    except ValueError:
        return compact


_SQL_COMPACT_OPERATORS = (
    "::",
    ":=",
    "->>",
    "#>>",
    "#>",
    "->",
    "<@",
    "@>",
    "&&",
    "||",
    "<=",
    ">=",
    "<>",
    "!=",
    "!~*",
    "!~",
    "~*",
    "<<",
    ">>",
    "=",
    "<",
    ">",
    "+",
    "-",
    "*",
    "/",
    "%",
    "^",
    "|",
    "&",
    ".",
    ",",
    ";",
    "(",
    ")",
)


def _compact_sql(definition: str) -> str:
    """Normalize SQL/PLpgSQL for exact token-boundary comparison.

    ``pg_get_functiondef``/``pg_proc.prosrc`` may vary in whitespace, comments,
    and keyword case.  Whitespace and comments are removed, but adjacent tokens
    remain separated in the compact form so ``NOT EXISTS`` never collapses to
    ``NOTEXISTS`` and ``RETURN NEW`` never collapses to ``RETURNNEW``.
    String literals and quoted identifiers are preserved exactly.
    """

    tokens: list[str] = []
    index = 0
    length = len(definition)
    while index < length:
        character = definition[index]
        if character.isspace():
            index += 1
            continue
        if definition.startswith("--", index):
            newline = definition.find("\n", index + 2)
            if newline < 0:
                break
            index = newline + 1
            continue
        if definition.startswith("/*", index):
            end = definition.find("*/", index + 2)
            if end < 0:
                break
            index = end + 2
            continue
        if character == "'":
            end = index + 1
            while end < length:
                if definition[end] == "'":
                    if end + 1 < length and definition[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            tokens.append(definition[index:end])
            index = end
            continue
        if character == '"':
            end = index + 1
            while end < length:
                if definition[end] == '"':
                    if end + 1 < length and definition[end + 1] == '"':
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            tokens.append(definition[index:end])
            index = end
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < length and (definition[end].isalnum() or definition[end] in "_$"):
                end += 1
            tokens.append(definition[index:end].lower())
            index = end
            continue
        if character.isdigit():
            end = index + 1
            while end < length and (definition[end].isdigit() or definition[end] == "."):
                end += 1
            tokens.append(definition[index:end])
            index = end
            continue
        for operator in _SQL_COMPACT_OPERATORS:
            if definition.startswith(operator, index):
                tokens.append(operator)
                index += len(operator)
                break
        else:
            tokens.append(character)
            index += 1
    return " ".join(tokens)


_MIGRATION_0012_FILE = Path("alembic/versions/20260801_0012_w1e_care_assignment.py")
_MIGRATION_0026_FILE = Path(
    "alembic/versions/20260814_0026_w1e_care_assignment_family_relationship_lock.py"
)


@lru_cache(maxsize=1)
def _migration_0012_function_bodies() -> dict[str, str]:
    """Return the exact erp trigger function bodies from the 0012 migration."""

    migration_path = Path(__file__).resolve().parents[2] / _MIGRATION_0012_FILE
    if not migration_path.is_file():
        raise SystemExit(f"CURRENT_0026_W1E_EXPECTED_BODY_SOURCE_MISSING: {migration_path}")
    source = migration_path.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for expected in W1E_TRIGGER_EXPECTATIONS.values():
        function_name = str(expected["function"])
        pattern = re.compile(
            r"CREATE(?:\s+OR\s+REPLACE)?\s+FUNCTION\s+erp\."
            + re.escape(function_name)
            + r"\s*\(\s*\)\s+RETURNS\s+trigger\s+LANGUAGE\s+plpgsql\s+AS\s+\$\$"
            r"(?P<body>.*?)\$\$\s*;",
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(source)
        if match is None:
            raise SystemExit(f"CURRENT_0026_W1E_EXPECTED_BODY_MISSING: {function_name}")
        bodies[function_name] = match.group("body")
    return bodies


@lru_cache(maxsize=1)
def _migration_0026_function_bodies() -> dict[str, str]:
    """Return exact current-head erp function bodies from the 0026 migration."""

    migration_path = Path(__file__).resolve().parents[2] / _MIGRATION_0026_FILE
    if not migration_path.is_file():
        raise SystemExit(f"CURRENT_0026_W1E_EXPECTED_BODY_SOURCE_MISSING: {migration_path}")
    source = migration_path.read_text(encoding="utf-8")
    function_names = {
        str(expected["function"]) for expected in W1E_TRIGGER_EXPECTATIONS.values()
    } | set(W1E_LOCK_FUNCTIONS)
    bodies: dict[str, str] = {}
    for function_name in sorted(function_names):
        pattern = re.compile(
            r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+erp\."
            + re.escape(function_name)
            + r"\s*\((?P<args>[^)]*)\)\s+RETURNS\s+\w+\s+LANGUAGE\s+plpgsql\s+AS\s+\$\$"
            r"(?P<body>.*?)\$\$\s*;",
            re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(source)
        if match is None:
            raise SystemExit(f"CURRENT_0026_W1E_EXPECTED_BODY_MISSING: {function_name}")
        bodies[function_name] = match.group("body")
    return bodies


def _function_body_is_expected(function_name: str, prosrc: str) -> bool:
    """Fail-closed exact normalized comparison against the current migration body."""

    expected_bodies = _migration_0026_function_bodies()
    if function_name not in expected_bodies:
        raise SystemExit(f"CURRENT_0026_W1E_EXPECTED_BODY_UNKNOWN_FUNCTION: {function_name}")
    return _compact_sql(prosrc) == _compact_sql(expected_bodies[function_name])


def _verify_w1e_lock_functions(connection: Connection) -> None:
    """Fail closed on the exact current-head W1E advisory lock helpers.

    The catalog query deliberately returns every erp function with an expected
    lock-helper name instead of collapsing by ``proname``.  A single pronargs
    check would let an integer overload coexist with the expected bigint helper
    and satisfy a name-keyed dictionary, after which an assignment-side call can
    still fail with SQLSTATE 42883.  Each name must therefore have exactly one
    overload and that overload must match the exact bigint argument OID vector
    and argument names/types.  The exact bodies must use the non-waiting
    ``pg_try_advisory_xact_lock`` acquisition and raise SQLSTATE 55P03 with the
    stable ``CARE_ASSIGNMENT_CONCURRENT_CONFLICT`` message on a lost key, and
    the edge helpers must keep the empty-edge parent-domain fallback; a
    committed-edge-only body would still compare as a single bigint helper while
    racing an uncommitted assignment INSERT.
    """

    rows = connection.execute(
        text(
            """
            SELECT p.oid AS function_oid,
                   p.proname AS function_name,
                   pn.nspname AS function_schema,
                   (p.prorettype = 'void'::regtype) AS returns_void,
                   p.proretset AS returns_set,
                   p.pronargs AS pronargs,
                   p.prokind AS prokind,
                   p.prosrc AS function_body,
                   p.proargtypes::text AS argument_type_oids,
                   pg_get_function_arguments(p.oid) AS argument_arguments,
                   pg_get_userbyid(p.proowner) AS function_owner,
                   pg_get_userbyid(
                       (SELECT c.relowner
                          FROM pg_class AS c
                         WHERE c.oid = 'erp.care_assignment'::regclass)
                   ) AS table_owner,
                   l.lanname AS function_language,
                   p.prosecdef AS function_security_definer,
                   p.proconfig AS function_proconfig,
                   p.provolatile AS function_volatility,
                   p.proisstrict AS function_is_strict,
                   p.proparallel AS function_parallel,
                   p.proleakproof AS function_leakproof,
                   p.proacl::text AS function_acl,
                   has_function_privilege(
                       :erp_app_role, p.oid, 'EXECUTE'
                   ) AS erp_app_can_execute,
                   has_function_privilege(
                       :erp_app_role, p.oid, 'EXECUTE WITH GRANT OPTION'
                   ) AS erp_app_execute_with_grant
              FROM pg_proc AS p
              JOIN pg_namespace AS pn ON pn.oid = p.pronamespace
              JOIN pg_language AS l ON l.oid = p.prolang
             WHERE pn.nspname = 'erp'
               AND p.proname = ANY(:function_names)
             ORDER BY p.proname, p.oid
            """
        ),
        {
            "function_names": list(W1E_LOCK_FUNCTIONS),
            "erp_app_role": "erp_app",
        },
    ).mappings()
    lock_catalog: dict[str, list[dict[str, object]]] = {}
    for catalog_row in rows:
        function_name = str(catalog_row["function_name"])
        lock_catalog.setdefault(function_name, []).append(dict(catalog_row))

    mismatches: list[str] = []
    for function_name, expected_pronargs in sorted(W1E_LOCK_FUNCTIONS.items()):
        overloads = lock_catalog.get(function_name, [])
        if not overloads:
            mismatches.append(f"missing:{function_name}")
            continue
        if len(overloads) != 1:
            mismatches.append(f"overloads:{function_name}:count={len(overloads)}")
            continue
        row = overloads[0]

        function_oid = row["function_oid"]
        function_schema = row["function_schema"]
        returns_void = row["returns_void"]
        returns_set = row["returns_set"]
        pronargs = row["pronargs"]
        prokind = row["prokind"]
        function_body = row["function_body"]
        function_owner = row["function_owner"]
        table_owner = row["table_owner"]
        function_language = row["function_language"]
        function_security_definer = row["function_security_definer"]
        function_proconfig = row["function_proconfig"]
        function_volatility = row["function_volatility"]
        function_is_strict = row["function_is_strict"]
        function_parallel = row["function_parallel"]
        function_leakproof = row["function_leakproof"]
        function_acl = row["function_acl"]
        erp_app_can_execute = row["erp_app_can_execute"]
        erp_app_execute_with_grant = row["erp_app_execute_with_grant"]
        argument_type_oids = row["argument_type_oids"]
        argument_arguments = row["argument_arguments"]

        if not isinstance(function_oid, int) or function_oid <= 0:
            mismatches.append(f"oid:{function_name}:{function_oid!r}")
        if str(function_schema) != "erp":
            mismatches.append(f"schema:{function_name}:{function_schema!r}")
        if bool(returns_void) is not True:
            mismatches.append(f"returns_void:{function_name}:{returns_void!r}")
        if returns_set is not False:
            mismatches.append(f"returns_set:{function_name}:{returns_set!r}")
        if not isinstance(pronargs, int) or pronargs != expected_pronargs:
            mismatches.append(
                f"pronargs:{function_name}:expected={expected_pronargs} actual={pronargs!r}"
            )
        if str(prokind) != "f":
            mismatches.append(f"prokind:{function_name}:{prokind!r}")
        if function_language != "plpgsql":
            mismatches.append(f"language:{function_name}:{function_language!r}")
        if function_security_definer is not False:
            mismatches.append(f"security_definer:{function_name}:{function_security_definer!r}")
        if function_proconfig is not None:
            mismatches.append(f"proconfig:{function_name}:{function_proconfig!r}")
        if str(function_volatility) != "v":
            mismatches.append(f"volatility:{function_name}:{function_volatility!r}")
        if function_is_strict is not False:
            mismatches.append(f"is_strict:{function_name}:{function_is_strict!r}")
        if str(function_parallel) != "u":
            mismatches.append(f"parallel:{function_name}:{function_parallel!r}")
        if function_leakproof is not False:
            mismatches.append(f"leakproof:{function_name}:{function_leakproof!r}")
        if function_acl is not None:
            mismatches.append(f"acl:{function_name}:{function_acl!r}")
        if bool(erp_app_can_execute) is not True:
            mismatches.append(
                f"execute_acl:{function_name}:erp_app_can_execute={erp_app_can_execute!r}"
            )
        if erp_app_execute_with_grant is not False:
            mismatches.append(
                f"execute_acl:{function_name}:"
                f"erp_app_execute_with_grant={erp_app_execute_with_grant!r}"
            )

        try:
            actual_oids = tuple(int(part) for part in str(argument_type_oids or "").split() if part)
        except ValueError:
            actual_oids = ()
            mismatches.append(f"argument_oids_unparseable:{function_name}:{argument_type_oids!r}")
        else:
            expected_oids = W1E_LOCK_FUNCTION_ARGUMENT_OIDS[function_name]
            if actual_oids != expected_oids:
                mismatches.append(
                    f"argument_oids:{function_name}:"
                    f"expected={expected_oids!r} actual={actual_oids!r}"
                )

        expected_arguments = W1E_LOCK_FUNCTION_ARGUMENTS[function_name]
        if _compact_sql(str(argument_arguments or "")) != _compact_sql(expected_arguments):
            mismatches.append(
                f"arguments:{function_name}:"
                f"expected={expected_arguments!r} actual={argument_arguments!r}"
            )

        if (
            not isinstance(table_owner, str)
            or not isinstance(function_owner, str)
            or table_owner != function_owner
        ):
            mismatches.append(
                f"owner:{function_name}:table={table_owner!r} function={function_owner!r}"
            )
        if not _function_body_is_expected(function_name, str(function_body or "")):
            mismatches.append(f"body:{function_name}:normalized_mismatch")

    if mismatches:
        raise SystemExit("CURRENT_0026_W1E_LOCK_CONTRACT_MISMATCH: " + "; ".join(mismatches))


def _verify_w1e_forbidden_lock_remnants(connection: Connection) -> None:
    """Fail closed if the obsolete global helper or key is resurrected."""

    remnant_rows = connection.execute(
        text(
            """
            SELECT p.proname AS function_name,
                   pg_get_function_identity_arguments(p.oid) AS identity_arguments,
                   p.prosrc AS function_body
              FROM pg_proc AS p
              JOIN pg_namespace AS n ON n.oid = p.pronamespace
             WHERE n.nspname = 'erp'
               AND (
                   p.proname = ANY(:forbidden_names)
                   OR p.prosrc LIKE :global_helper_marker
                   OR p.prosrc LIKE :global_key_marker
               )
             ORDER BY p.proname, p.oid
            """
        ),
        {
            "forbidden_names": list(W1E_FORBIDDEN_LOCK_FUNCTION_NAMES),
            "global_helper_marker": "%fn_w1e_lock_global%",
            "global_key_marker": "%erp.w1e.global%",
        },
    ).mappings()
    remnants: list[str] = []
    for remnant in remnant_rows:
        function_name = str(remnant["function_name"])
        identity_arguments = str(remnant["identity_arguments"] or "")
        body = str(remnant["function_body"] or "")
        if function_name in W1E_FORBIDDEN_LOCK_FUNCTION_NAMES:
            remnants.append(f"function:{function_name}({identity_arguments})")
        for marker in W1E_FORBIDDEN_LOCK_BODY_MARKERS:
            if marker in body:
                remnants.append(f"body:{function_name}:{marker}")
    if remnants:
        raise SystemExit("CURRENT_0026_W1E_FORBIDDEN_LOCK_REMNANT: " + "; ".join(remnants))


def _verify_w1e_constraint_triggers(connection: Connection) -> None:
    """Fail closed on the erp trigger catalog.

    Each W1E guard must be a real deferrable row-level constraint trigger bound
    to the expected erp trigger function, that function must still contain the
    guard's core error path markers, and the catalog must not carry unexpected
    non-internal user triggers on ``erp.care_assignment`` beyond the W1E origin
    set.  Expected trigger functions must also be owned by their table owner,
    use ``plpgsql``, run as ``SECURITY INVOKER``, carry no ``proconfig``, and
    keep the migration's exact catalog attributes: ``VOLATILE`` (provolatile
    ``v``), not strict, ``PARALLEL UNSAFE``, not leakproof, not set-returning,
    and a null ``proacl``.  ``erp_app`` must keep effective EXECUTE without
    grant option.
    """

    rows = connection.execute(
        text(
            """
            SELECT c.relname AS relname,
                   t.tgname AS tgname,
                   t.tgenabled AS tgenabled,
                   t.tgdeferrable AS tgdeferrable,
                   t.tginitdeferred AS tginitdeferred,
                   t.tgtype AS tgtype,
                   (t.tgconstraint <> 0) AS is_constraint_trigger,
                   t.tgfoid AS tgfoid,
                   t.tgattr::text AS tgattr,
                   pg_get_expr(t.tgqual, t.tgrelid) AS tgqual,
                   t.tgnargs AS tgnargs,
                   octet_length(t.tgargs) AS tgargs_octets,
                   p.oid AS function_oid,
                   p.proname AS function_name,
                   pn.nspname AS function_schema,
                   (p.prorettype = 'trigger'::regtype) AS returns_trigger,
                   p.proretset AS returns_set,
                   p.pronargs AS pronargs,
                   p.prokind AS prokind,
                   p.prosrc AS function_body,
                   pg_get_userbyid(c.relowner) AS table_owner,
                   pg_get_userbyid(p.proowner) AS function_owner,
                   l.lanname AS function_language,
                   p.prosecdef AS function_security_definer,
                   p.proconfig AS function_proconfig,
                   p.provolatile AS function_volatility,
                   p.proisstrict AS function_is_strict,
                   p.proparallel AS function_parallel,
                   p.proleakproof AS function_leakproof,
                   p.proacl::text AS function_acl,
                   has_function_privilege(
                       :erp_app_role, p.oid, 'EXECUTE'
                   ) AS erp_app_can_execute,
                   has_function_privilege(
                       :erp_app_role, p.oid, 'EXECUTE WITH GRANT OPTION'
                   ) AS erp_app_execute_with_grant
              FROM pg_trigger AS t
              JOIN pg_class AS c ON c.oid = t.tgrelid
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
              JOIN pg_proc AS p ON p.oid = t.tgfoid
              JOIN pg_namespace AS pn ON pn.oid = p.pronamespace
              JOIN pg_language AS l ON l.oid = p.prolang
             WHERE n.nspname = 'erp' AND NOT t.tgisinternal
            """
        ),
        {"erp_app_role": "erp_app"},
    ).mappings()
    trigger_catalog = {(str(row["relname"]), str(row["tgname"])): row for row in rows}

    expected_care_assignment_triggers = {
        trigger_name
        for table_name, trigger_name in REQUIRED_W1E_ORIGIN_TRIGGERS
        if table_name == "care_assignment"
    }
    actual_care_assignment_triggers = {
        trigger_name
        for table_name, trigger_name in trigger_catalog
        if table_name == "care_assignment"
    }
    unexpected_care_assignment_triggers = sorted(
        actual_care_assignment_triggers - expected_care_assignment_triggers
    )

    mismatches: list[str] = []
    if unexpected_care_assignment_triggers:
        mismatches.append(
            "unexpected_care_assignment_triggers:" + ",".join(unexpected_care_assignment_triggers)
        )
    for (table_name, trigger_name), expected in sorted(W1E_TRIGGER_EXPECTATIONS.items()):
        row = trigger_catalog.get((table_name, trigger_name))
        if row is None:
            mismatches.append(f"missing:{table_name}.{trigger_name}")
            continue

        expected_function = str(expected["function"])
        expected_tgtype = int(expected["tgtype"])
        actual_table = str(row["relname"])
        actual_trigger = str(row["tgname"])
        enabled = row["tgenabled"]
        deferrable = row["tgdeferrable"]
        initially_deferred = row["tginitdeferred"]
        tgtype_value = int(row["tgtype"])
        is_constraint_trigger = row["is_constraint_trigger"]
        tgfoid = row["tgfoid"]
        tgattr = row["tgattr"]
        tgqual = row["tgqual"]
        tgnargs = row["tgnargs"]
        tgargs_octets = row["tgargs_octets"]
        function_oid = row["function_oid"]
        function_name = row["function_name"]
        function_schema = row["function_schema"]
        returns_trigger = row["returns_trigger"]
        returns_set = row["returns_set"]
        pronargs = row["pronargs"]
        prokind = row["prokind"]
        function_body = row["function_body"]
        table_owner = row["table_owner"]
        function_owner = row["function_owner"]
        function_language = row["function_language"]
        function_security_definer = row["function_security_definer"]
        function_proconfig = row["function_proconfig"]
        function_volatility = row["function_volatility"]
        function_is_strict = row["function_is_strict"]
        function_parallel = row["function_parallel"]
        function_leakproof = row["function_leakproof"]
        function_acl = row["function_acl"]
        erp_app_can_execute = row["erp_app_can_execute"]
        erp_app_execute_with_grant = row["erp_app_execute_with_grant"]

        if actual_table != table_name or actual_trigger != trigger_name:
            mismatches.append(
                f"binding:{table_name}.{trigger_name}:{actual_table}.{actual_trigger}"
            )
        if str(enabled) != "O":
            mismatches.append(f"enabled:{table_name}.{trigger_name}:{enabled!r}")
        if bool(deferrable) is not True:
            mismatches.append(f"deferrable:{table_name}.{trigger_name}:{deferrable!r}")
        if bool(initially_deferred) is not True:
            mismatches.append(
                f"initially_deferred:{table_name}.{trigger_name}:{initially_deferred!r}"
            )
        if tgtype_value != expected_tgtype:
            mismatches.append(
                f"tgtype:{table_name}.{trigger_name}:expected={expected_tgtype} "
                f"actual={tgtype_value}"
            )
        row_level = bool(tgtype_value & _TG_TYPE_ROW)
        before = bool(tgtype_value & _TG_TYPE_BEFORE)
        instead = bool(tgtype_value & _TG_TYPE_INSTEAD)
        has_insert = bool(tgtype_value & _TG_TYPE_INSERT)
        has_delete = bool(tgtype_value & _TG_TYPE_DELETE)
        has_update = bool(tgtype_value & _TG_TYPE_UPDATE)
        has_truncate = bool(tgtype_value & _TG_TYPE_TRUNCATE)
        if (
            row_level is not True
            or before
            or instead
            or has_insert != bool(expected_tgtype & _TG_TYPE_INSERT)
            or has_delete != bool(expected_tgtype & _TG_TYPE_DELETE)
            or has_update != bool(expected_tgtype & _TG_TYPE_UPDATE)
            or has_truncate != bool(expected_tgtype & _TG_TYPE_TRUNCATE)
        ):
            mismatches.append(f"event_row:{table_name}.{trigger_name}:tgtype={tgtype_value}")
        if bool(is_constraint_trigger) is not True:
            mismatches.append(f"constraint_trigger:{table_name}.{trigger_name}:false")
        if type(tgfoid) is not int or tgfoid <= 0 or int(function_oid) != tgfoid:
            mismatches.append(f"tgfoid:{table_name}.{trigger_name}:{tgfoid!r}/{function_oid!r}")
        if str(tgattr) != "":
            mismatches.append(f"tgattr:{table_name}.{trigger_name}:{tgattr!r}")
        if tgqual is not None:
            mismatches.append(f"tgqual:{table_name}.{trigger_name}:{tgqual!r}")
        if int(tgnargs) != 0 or int(tgargs_octets) != 0:
            mismatches.append(
                f"tgargs:{table_name}.{trigger_name}:tgnargs={tgnargs!r} octets={tgargs_octets!r}"
            )
        if str(function_name) != expected_function or str(function_schema) != "erp":
            mismatches.append(
                f"function:{table_name}.{trigger_name}:{function_schema}.{function_name}"
            )
        if bool(returns_trigger) is not True or int(pronargs) != 0 or str(prokind) != "f":
            mismatches.append(
                f"function_signature:{table_name}.{trigger_name}:"
                f"returns_trigger={returns_trigger!r} pronargs={pronargs!r} "
                f"prokind={prokind!r}"
            )
        if returns_set is not False:
            mismatches.append(f"returns_set:{table_name}.{trigger_name}:{returns_set!r}")
        if (
            not isinstance(table_owner, str)
            or not isinstance(function_owner, str)
            or table_owner != function_owner
        ):
            mismatches.append(
                f"owner:{table_name}.{trigger_name}:"
                f"table={table_owner!r} function={function_owner!r}"
            )
        if function_language != "plpgsql":
            mismatches.append(f"language:{table_name}.{trigger_name}:{function_language!r}")
        if function_security_definer is not False:
            mismatches.append(
                f"security_definer:{table_name}.{trigger_name}:{function_security_definer!r}"
            )
        if function_proconfig is not None:
            mismatches.append(f"proconfig:{table_name}.{trigger_name}:{function_proconfig!r}")
        if str(function_volatility) != "v":
            mismatches.append(f"volatility:{table_name}.{trigger_name}:{function_volatility!r}")
        if function_is_strict is not False:
            mismatches.append(f"is_strict:{table_name}.{trigger_name}:{function_is_strict!r}")
        if str(function_parallel) != "u":
            mismatches.append(f"parallel:{table_name}.{trigger_name}:{function_parallel!r}")
        if function_leakproof is not False:
            mismatches.append(f"leakproof:{table_name}.{trigger_name}:{function_leakproof!r}")
        if function_acl is not None:
            mismatches.append(f"acl:{table_name}.{trigger_name}:{function_acl!r}")
        if bool(erp_app_can_execute) is not True:
            mismatches.append(
                f"execute_acl:{table_name}.{trigger_name}:"
                f"erp_app_can_execute={erp_app_can_execute!r}"
            )
        if erp_app_execute_with_grant is not False:
            mismatches.append(
                f"execute_acl:{table_name}.{trigger_name}:"
                f"erp_app_execute_with_grant={erp_app_execute_with_grant!r}"
            )

        compact_body = _compact_sql(str(function_body or ""))
        missing_markers = [
            marker
            for marker in expected["markers"]
            if _compact_sql(str(marker)) not in compact_body
        ]
        if missing_markers:
            mismatches.append(f"markers:{table_name}.{trigger_name}:{','.join(missing_markers)}")
        if not _function_body_is_expected(expected_function, str(function_body or "")):
            mismatches.append(f"body:{table_name}.{trigger_name}:normalized_mismatch")

    if mismatches:
        raise SystemExit("CURRENT_0026_W1E_TRIGGER_CONTRACT_MISMATCH: " + "; ".join(mismatches))


def _care_assignment_sequence_acl_entries(
    connection: Connection,
) -> list[tuple[int, int, str, bool]]:
    """Return (grantee_oid, grantor_oid, privilege, grantable) ACL entries."""

    rows = connection.execute(
        text(
            """
            SELECT acl.grantee AS grantee_oid,
                   acl.grantor AS grantor_oid,
                   acl.privilege_type AS privilege_type,
                   acl.is_grantable AS is_grantable
              FROM pg_class AS seq
              JOIN pg_namespace AS n ON n.oid = seq.relnamespace
              CROSS JOIN LATERAL aclexplode(seq.relacl) AS acl
             WHERE n.nspname = 'erp'
               AND seq.relname = 'care_assignment_id_seq'
             ORDER BY acl.grantee, acl.privilege_type
            """
        )
    ).all()
    return [
        (int(grantee), int(grantor), str(privilege), bool(grantable))
        for grantee, grantor, privilege, grantable in rows
    ]


def _verify_care_assignment_sequence_acl_entries(
    connection: Connection,
    sequence_owner_oid: int,
) -> None:
    """Fail closed on relacl/aclexplode drift outside the 0012 contract.

    The identity sequence may carry only the conditional erp_app
    (USAGE+SELECT, no grant option) and erp_backup (SELECT only, USAGE
    revoked, no grant option) entries.  An explicit owner entry is allowed
    only when it is the sequence owner's own materialized implicit privilege
    set: grantee=sequence_owner, grantor=sequence_owner, and no grant option.
    An owner row granted by any other role is rejected, so owner-grantee rows
    are never skipped without verifying owner semantics.  PUBLIC or any
    third-role grant is rejected fail-closed.  Non-owner entries must be
    granted by the sequence owner.  Effective privilege checks cannot
    substitute for this exact ACL set: each allowed role must appear with
    exactly those privileges, and no other grantee may appear.
    """

    app_oid = connection.scalar(text("SELECT oid FROM pg_roles WHERE rolname = 'erp_app'"))
    backup_oid = connection.scalar(text("SELECT oid FROM pg_roles WHERE rolname = 'erp_backup'"))
    allowed_entries: dict[int, set[tuple[str, bool]]] = {}
    if app_oid is not None and int(app_oid) != sequence_owner_oid:
        allowed_entries[int(app_oid)] = {("SELECT", False), ("USAGE", False)}
    if backup_oid is not None and int(backup_oid) != sequence_owner_oid:
        allowed_entries[int(backup_oid)] = {("SELECT", False)}

    seen: dict[int, set[tuple[str, bool]]] = {}
    drifts: list[str] = []
    for grantee_oid, grantor_oid, privilege, grantable in _care_assignment_sequence_acl_entries(
        connection
    ):
        if grantee_oid == sequence_owner_oid:
            # An owner ACL row is only legitimate when it is the owner's own
            # materialized implicit privilege set.  A row granted by a third
            # role, or an owner row carrying WITH GRANT OPTION, is an ACL
            # drift and must fail closed just like any non-owner grant.
            if grantor_oid != sequence_owner_oid:
                drifts.append(
                    f"owner_grantor={grantor_oid}:grantee={grantee_oid}:"
                    f"privilege={privilege}:grantable={grantable}"
                )
            if grantable:
                drifts.append(
                    f"owner_grantable={grantee_oid}:privilege={privilege}:grantable={grantable}"
                )
            continue
        if grantor_oid != sequence_owner_oid:
            drifts.append(
                f"grantor={grantor_oid}:grantee={grantee_oid}:"
                f"privilege={privilege}:grantable={grantable}"
            )
        seen.setdefault(grantee_oid, set()).add((privilege, grantable))

    for grantee_oid, privileges in seen.items():
        expected_privileges = allowed_entries.get(grantee_oid)
        if expected_privileges is None:
            drifts.append(f"unexpected_grantee={grantee_oid}:privileges={sorted(privileges)!r}")
        elif privileges != expected_privileges:
            drifts.append(
                f"grantee={grantee_oid}:expected={sorted(expected_privileges)!r}"
                f":actual={sorted(privileges)!r}"
            )

    for role_oid, expected_privileges in allowed_entries.items():
        if role_oid not in seen:
            drifts.append(f"missing_grantee={role_oid}:expected={sorted(expected_privileges)!r}")
    if drifts:
        raise SystemExit(
            "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_ACL_MISMATCH: " + "; ".join(sorted(drifts))
        )


def _verify_care_assignment_sequence_acl(connection: Connection) -> None:
    """Fail closed on the exact 0012 care_assignment identity sequence contract.

    ``erp.care_assignment_id_seq`` must be an ``erp`` sequence owned by the
    same role as ``erp.care_assignment``. ``erp_app`` must have exactly
    USAGE+SELECT with no UPDATE/grant-option drift. When ``erp_backup``
    exists it must have exactly SELECT, matching the 0012
    ``GRANT SELECT`` / ``REVOKE USAGE`` pair.  ``relacl``/``aclexplode`` is
    then inspected so PUBLIC or a third-role grant cannot pass on the
    effective-privilege check alone.  Non-owner ACL rows must be granted by
    the sequence owner and must match the exact privilege set for each
    existing role; missing required entries fail closed.
    """

    row = (
        connection.execute(
            text(
                """
            SELECT seq.relkind AS sequence_kind,
                   seq.relowner AS sequence_owner_oid,
                   tbl.relowner AS table_owner_oid,
                   seq.relacl IS NULL AS sequence_acl_is_null,
                   pg_get_userbyid(seq.relowner) AS sequence_owner,
                   pg_get_userbyid(tbl.relowner) AS table_owner
              FROM pg_class AS seq
              JOIN pg_namespace AS n ON n.oid = seq.relnamespace
              JOIN pg_class AS tbl
                ON tbl.oid = 'erp.care_assignment'::regclass
             WHERE n.nspname = 'erp'
               AND seq.relname = 'care_assignment_id_seq'
            """
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SystemExit("CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_MISSING")
    if str(row["sequence_kind"]) != "S":
        raise SystemExit(
            f"CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_KIND_MISMATCH: {row['sequence_kind']!r}"
        )
    sequence_owner = row["sequence_owner"]
    table_owner = row["table_owner"]
    if (
        not isinstance(sequence_owner, str)
        or not isinstance(table_owner, str)
        or sequence_owner != table_owner
    ):
        raise SystemExit(
            "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_OWNER_MISMATCH: "
            f"sequence={sequence_owner!r} table={table_owner!r}"
        )
    actual_privileges = _sequence_privileges(
        connection,
        "erp_app",
        "erp.care_assignment_id_seq",
    )
    if actual_privileges != ERP_APP_SEQUENCE_PRIVILEGES:
        raise SystemExit(
            "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_APP_ACL_MISMATCH: "
            f"expected={ERP_APP_SEQUENCE_PRIVILEGES!r} actual={actual_privileges!r}"
        )
    backup_role_exists = bool(
        connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='erp_backup')"))
    )
    if backup_role_exists:
        backup_privileges = _sequence_privileges(
            connection,
            "erp_backup",
            "erp.care_assignment_id_seq",
        )
        if backup_privileges != ERP_BACKUP_SEQUENCE_PRIVILEGES:
            raise SystemExit(
                "CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_BACKUP_ACL_MISMATCH: "
                f"expected={ERP_BACKUP_SEQUENCE_PRIVILEGES!r} actual={backup_privileges!r}"
            )
    _verify_care_assignment_sequence_acl_entries(
        connection,
        int(row["sequence_owner_oid"]),
    )


def verify_current_0026(
    connection: Connection,
    *,
    expected_revision: str | None = None,
    extra_required_triggers: frozenset[str] | set[str] = frozenset(),
    skip_revision: bool = False,
) -> None:
    replication_role = connection.scalar(text("SHOW session_replication_role"))
    if replication_role != "origin":
        raise SystemExit(
            "CURRENT_0026_POSTCHECK_REPLICATION_ROLE_MISMATCH: "
            f"expected=origin actual={replication_role!r}"
        )

    revision = connection.scalar(text("SELECT version_num FROM erp.alembic_version"))
    required_revision = expected_revision or EXPECTED_REVISION
    if not skip_revision and revision != required_revision:
        raise SystemExit(
            f"CURRENT_0026_REVISION_MISMATCH: expected={required_revision} actual={revision}"
        )

    role_exists = bool(
        connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='erp_app')"))
    )
    if not role_exists:
        raise SystemExit("CURRENT_0026_ERP_APP_ROLE_MISSING")

    tables = {
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT tablename
                  FROM pg_tables
                 WHERE schemaname = 'erp'
                """
            )
        )
    }
    missing_w2 = sorted(REQUIRED_W2_TABLES - tables)
    forbidden_present = sorted(FORBIDDEN_CURRENT_TABLES & tables)
    if missing_w2 or forbidden_present:
        raise SystemExit(
            f"CURRENT_0026_TABLE_MISMATCH: missing={missing_w2} forbidden={forbidden_present}"
        )

    _require_columns(
        _columns(connection, "recipient"),
        required={
            "name": True,
            "birth_date": True,
            "sex_code": True,
            "mobile_phone": False,
            "payer_guardian_id": True,
        },
        forbidden={"home_phone"},
        label="recipient",
    )
    _require_columns(
        _columns(connection, "recipient_guardian"),
        required={
            "slot_no": False,
            "name": True,
            "relationship_text": True,
            "phone": True,
            "address": True,
            "email": True,
        },
        label="recipient_guardian",
    )
    _require_columns(
        _columns(connection, "recipient_contract"),
        required={"recipient_id": False, "start_date": False, "end_date": True},
        forbidden={"signer_name", "signer_relationship_text", "signer_phone"},
        label="recipient_contract",
    )
    _require_columns(
        _columns(connection, "recipient_certification_period"),
        required={"grade_code": False, "start_date": False, "end_date": False},
        label="recipient_certification_period",
    )
    _require_columns(
        _columns(connection, "recipient_benefit_period"),
        required={"benefit_code": False, "start_text": False},
        forbidden={"start_date", "end_date", "benefit_period"},
        label="recipient_benefit_period",
    )
    _require_columns(
        _columns(connection, "staff_health_check"),
        required={"staff_id": False, "employment_id": True, "check_date": False},
        forbidden={"check_type_code", "result_note"},
        label="staff_health_check",
    )
    _require_columns(
        _columns(connection, "care_assignment"),
        required={
            "recipient_contract_id": False,
            "staff_id": False,
            "employment_id": False,
            "assignment_kind": False,
            "family_relationship_text": True,
            "start_date": False,
            "end_date": True,
            "assignment_period": False,
        },
        label="care_assignment",
    )

    relationship_constraints = {
        str(name): str(definition).replace("erp.", "")
        for name, definition in connection.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid, true)
                  FROM pg_constraint
                 WHERE conrelid IN (
                    'erp.recipient'::regclass,
                    'erp.recipient_guardian'::regclass,
                    'erp.staff_health_check'::regclass
                 )
                """
            )
        ).all()
    }
    expected_constraint_fragments = {
        "ck_recipient_guardian_slot_no": "CHECK (slot_no = ANY (ARRAY[1, 2]))",
        "uq_recipient_guardian_recipient_slot": "UNIQUE (recipient_id, slot_no)",
        "fk_recipient_payer_guardian_same_recipient": ("ON DELETE SET NULL (payer_guardian_id)"),
        "fk_staff_health_check_employment": (
            "FOREIGN KEY (staff_id, employment_id) REFERENCES staff_employment(staff_id, id)"
        ),
    }
    wrong_relationship_constraints = sorted(
        name
        for name, fragment in expected_constraint_fragments.items()
        if fragment not in relationship_constraints.get(name, "")
    )
    if wrong_relationship_constraints:
        raise SystemExit(
            f"CURRENT_0026_RELATIONSHIP_CONSTRAINT_MISMATCH: {wrong_relationship_constraints}"
        )

    care_assignment_constraints = {
        str(name): (str(definition), bool(deferrable), bool(deferred))
        for name, definition, deferrable, deferred in connection.execute(
            text(
                """
                SELECT conname,
                       pg_get_constraintdef(oid, true),
                       condeferrable,
                       condeferred
                  FROM pg_constraint
                 WHERE conrelid = 'erp.care_assignment'::regclass
                """
            )
        ).all()
    }
    family_check = care_assignment_constraints.get(
        "ck_care_assignment_family_relationship_present",
        ("", False, False),
    )[0]
    if _compact_constraint(family_check) != _compact_constraint(EXACT_CARE_ASSIGNMENT_FAMILY_CHECK):
        raise SystemExit(
            f"CURRENT_0026_CARE_ASSIGNMENT_FAMILY_CHECK_MISMATCH: actual={family_check!r}"
        )

    kind_check = care_assignment_constraints.get(
        "ck_care_assignment_kind",
        ("", False, False),
    )[0]
    if _compact_constraint(kind_check) != _compact_constraint(EXACT_CARE_ASSIGNMENT_KIND_CHECK):
        raise SystemExit(f"CURRENT_0026_CARE_ASSIGNMENT_KIND_CHECK_MISMATCH: actual={kind_check!r}")

    exclusion = care_assignment_constraints.get(
        "ex_care_assignment_same_contract_staff_period",
        ("", False, False),
    )
    exclusion_definition, exclusion_deferrable, exclusion_deferred = exclusion
    if (
        _compact_constraint(exclusion_definition).lower()
        != _compact_constraint(EXACT_CARE_ASSIGNMENT_EXCLUSION).lower()
        or exclusion_deferrable
        or exclusion_deferred
    ):
        raise SystemExit(
            "CURRENT_0026_CARE_ASSIGNMENT_EXCLUSION_MISMATCH: "
            f"definition={exclusion_definition!r} "
            f"deferrable={exclusion_deferrable} deferred={exclusion_deferred}"
        )

    _require_columns(
        _columns(connection, "staff_quarterly_consultation"),
        required={
            "staff_id": False,
            "calendar_year": False,
            "quarter_no": False,
            "completed": False,
        },
        forbidden={
            "status",
            "counseling_date",
            "content",
            "incomplete_reason_text",
            "exempt_reason_text",
        },
        label="staff_quarterly_consultation",
    )

    training_codes = tuple(
        str(value)
        for value in connection.scalars(
            text("SELECT code FROM erp.training_course ORDER BY sort_order")
        )
    )
    if training_codes != EXACT_TRAINING_CODES:
        raise SystemExit(f"CURRENT_0026_TRAINING_CODES_MISMATCH: {training_codes}")

    trigger_rows = connection.execute(
        text(
            """
            SELECT c.relname, t.tgname, t.tgenabled
              FROM pg_trigger AS t
              JOIN pg_class AS c ON c.oid = t.tgrelid
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = 'erp' AND NOT t.tgisinternal
            """
        )
    ).all()
    triggers = {str(name) for _, name, _ in trigger_rows}
    missing_triggers = sorted((REQUIRED_TRIGGERS | set(extra_required_triggers)) - triggers)
    if missing_triggers:
        raise SystemExit(f"CURRENT_0026_TRIGGER_MISSING: {missing_triggers}")

    trigger_states = {
        (str(table_name), str(trigger_name)): str(enabled)
        for table_name, trigger_name, enabled in trigger_rows
    }
    wrong_w1e_trigger_states = {
        f"{table_name}.{trigger_name}": trigger_states.get((table_name, trigger_name))
        for table_name, trigger_name in sorted(REQUIRED_W1E_ORIGIN_TRIGGERS)
        if trigger_states.get((table_name, trigger_name)) != "O"
    }
    if wrong_w1e_trigger_states:
        raise SystemExit(f"CURRENT_0026_W1E_TRIGGER_STATE_MISMATCH: {wrong_w1e_trigger_states}")

    _verify_w1e_constraint_triggers(connection)
    _verify_w1e_lock_functions(connection)
    _verify_w1e_forbidden_lock_remnants(connection)

    card_constraints = " ".join(
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT pg_get_constraintdef(oid, true)
                  FROM pg_constraint
                 WHERE conrelid = 'erp.w2_official_work_card'::regclass
                   AND contype = 'c'
                """
            )
        )
    )
    actual_kinds = set(re.findall(r"'([A-Z_]+)'", card_constraints))
    if actual_kinds != OFFICIAL_CARD_KINDS:
        raise SystemExit(f"CURRENT_0026_CARD_KIND_MISMATCH: {sorted(actual_kinds)}")

    if _privileges(connection, "erp_app", "care_assignment") != ERP_APP_WRITE_PRIVILEGES:
        raise SystemExit("CURRENT_0026_CARE_ASSIGNMENT_APP_ACL_MISMATCH")
    if _privileges(connection, "erp_app", "w2_service_plan_notice") != ERP_APP_WRITE_PRIVILEGES:
        raise SystemExit("CURRENT_0026_SERVICE_PLAN_APP_ACL_MISMATCH")
    for legacy_table in (
        "recipient_plan_notification",
        "recipient_service_plan_notice",
    ):
        if _privileges(connection, "erp_app", legacy_table) != ERP_APP_READ_ONLY_PRIVILEGES:
            raise SystemExit(f"CURRENT_0026_LEGACY_ACL_MISMATCH: {legacy_table}")
    _verify_care_assignment_sequence_acl(connection)


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("CURRENT_0026_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            verify_current_0026(connection)
    finally:
        engine.dispose()
    print("SSWCENTER_CURRENT_0026_DB_POSTCHECK_OK")


if __name__ == "__main__":
    main()
