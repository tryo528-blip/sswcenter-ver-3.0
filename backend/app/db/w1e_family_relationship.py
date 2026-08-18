"""Canonical FAMILY relationship blank-check trim set.

The product contract is the explicit ASCII whitespace set below, not Python
``str.strip()`` and not PostgreSQL ``btrim`` with the default space-only set.

Characters:

* U+0020 SPACE
* U+0009 CHARACTER TABULATION
* U+000A LINE FEED
* U+000D CARRIAGE RETURN
* U+000C FORM FEED
* U+000B LINE TABULATION

Unicode whitespace such as NBSP or ideographic space is significant content
and is not trimmed.  Broadening that set requires an explicit contract change.
"""

from __future__ import annotations

FAMILY_RELATIONSHIP_TRIM_CHARS = " \t\n\r\f\v"

# PostgreSQL E-strings accept \\t \\n \\r \\f, but not \\v.  Vertical tab
# must be written as a hex escape so the CHECK does not trim the letter v.
_TRIM_E_ESCAPES = {
    "\t": "\\t",
    "\n": "\\n",
    "\r": "\\r",
    "\f": "\\f",
    "\v": "\\x0b",
}


def family_relationship_trim_sql_literal(*, e_string: bool = False) -> str:
    if e_string:
        escaped = "".join(
            _TRIM_E_ESCAPES.get(character, character)
            for character in FAMILY_RELATIONSHIP_TRIM_CHARS
        )
        return "E'" + escaped + "'"
    return "'" + FAMILY_RELATIONSHIP_TRIM_CHARS.replace("'", "''") + "'"


def family_relationship_present_predicate_sql(*, e_string: bool = False) -> str:
    literal = family_relationship_trim_sql_literal(e_string=e_string)
    return (
        "assignment_kind <> 'FAMILY' OR "
        "(family_relationship_text IS NOT NULL AND "
        f"btrim(family_relationship_text, {literal}) <> '')"
    )
