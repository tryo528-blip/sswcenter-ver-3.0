"""Read-only hardening contract tests for W2 migration 0019."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db import postcheck_w1a_vs1 as postcheck

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ALEMBIC_ROOT = BACKEND_ROOT / "alembic"
MIGRATIONS_ROOT = ALEMBIC_ROOT / "versions"
SCRIPTS_ROOT = REPO_ROOT / "scripts"

W2_PREV_REVISION = "20260808_0017_recipient_guardian_email"
W2_REVISION = "20260809_0018_w2_service_plan_notice"
R0_REVISION = "20260812_0019_r0_w2_read_only"
ALEMBIC_HEADLESS_DB = postcheck.W2_SERVICE_PLAN_NOTICE_REVISION
ALEMBIC_READ_ONLY_DB = postcheck.R0_W2_READ_ONLY_REVISION

ALEMBIC_0018_PATH = MIGRATIONS_ROOT / "20260809_0018_w2_service_plan_notice.py"
ALEMBIC_0019_PATH = MIGRATIONS_ROOT / "20260812_0019_r0_w2_read_only.py"
POSTCHECK_PATH = BACKEND_ROOT / "app" / "db" / "postcheck_w1a_vs1.py"
RESTORE_PATH = REPO_ROOT / "scripts" / "restore-drill.ps1"
VERIFY_PATH = REPO_ROOT / "scripts" / "verify-w1a-vs1-db.ps1"

# Byte-identical R0-A product seals (LF-normalized SHA-256).
# postcheck is merged into the current 3.0 lineage and sealed structurally below.
EXPECTED_HASHES = {
    ALEMBIC_0018_PATH: "AB1A7FB77498CAB7EBD1163084CA98FDF9FD350F5D32A0682F81DC17EE37D716",
    ALEMBIC_0019_PATH: "EF7FC4917015A265D4633EFAE372314B760F193C4CFC2C98240C158CFDFB21AA",
    RESTORE_PATH: "B37B9C26C27CED5794580BA00E0CAE808C94A783B1ECA0BAA0E7A1471829C5AB",
    VERIFY_PATH: "5EB67C21F12F2DAA69E791AA6AB38D64195DF7C59A52A4F85EE63D307E8EB06C",
}
PRODUCT_PRESENCE_PATHS = (POSTCHECK_PATH,)

W1C_CONTAINMENT_TRIGGER_PAIRS = {
    ("ct_recipient_grade_period_containment", "recipient_grade_period"),
    ("ct_recipient_certification_grade_containment", "recipient_certification_period"),
}
W1C_CONTAINMENT_TRIGGER_STATES = {
    ("ct_recipient_grade_period_containment", "recipient_grade_period"): (True, False),
    (
        "ct_recipient_certification_grade_containment",
        "recipient_certification_period",
    ): (True, False),
}
W1C_APP_TABLE_PRIVILEGES = (True, True, True, False, False)
W1C_BACKUP_TABLE_PRIVILEGES = (True, False, False, False, False)
W1C_TRIGGER_RELATED_COLUMNS = {
    "recipient_certification_identity": {
        "recipient_id": ("bigint", "NO"),
        "certification_number": ("text", "NO"),
        "invalidated_at_utc": ("timestamp with time zone", "YES"),
    },
    "recipient_certification_period": {
        "recipient_id": ("bigint", "NO"),
        "certification_period": ("daterange", "YES"),
        "end_date": ("date", "NO"),
        "invalidated_at_utc": ("timestamp with time zone", "YES"),
    },
    "recipient_grade_period": {
        "recipient_id": ("bigint", "NO"),
        "end_date": ("date", "NO"),
        "invalidated_at_utc": ("timestamp with time zone", "YES"),
    },
    "recipient_benefit_period": {
        "recipient_id": ("bigint", "NO"),
        "end_date": ("date", "YES"),
        "invalidated_at_utc": ("timestamp with time zone", "YES"),
        "benefit_period": ("daterange", "YES"),
    },
    "recipient_local_approval_amount_period": {
        "recipient_id": ("bigint", "NO"),
        "end_date": ("date", "YES"),
        "amount_krw": ("bigint", "NO"),
        "invalidated_at_utc": ("timestamp with time zone", "YES"),
        "approval_period": ("daterange", "YES"),
    },
}
W1C_GENERATED_COLUMNS = {
    ("recipient_certification_period", "certification_period"): (
        "daterange",
        "daterange(start_date, (end_date + 1), '[)')",
    ),
    ("recipient_grade_period", "grade_period"): (
        "daterange",
        "daterange(start_date, (end_date + 1), '[)')",
    ),
    ("recipient_benefit_period", "benefit_period"): (
        "daterange",
        "daterange(start_date, (end_date + 1), '[)')",
    ),
    ("recipient_local_approval_amount_period", "approval_period"): (
        "daterange",
        "daterange(start_date, (end_date + 1), '[)')",
    ),
}
W1C_FAKE_CONSTRAINTS = {
    "pk_recipient_certification_identity": ("p", "constraint p"),
    "uq_recipient_certification_identity_certification_number": (
        "u",
        "UNIQUE (certification_number)",
    ),
    "ck_recipient_certification_identity_number": (
        "c",
        "CHECK (certification_number ~ '^l[0-9]{10}$')",
    ),
    "ex_recipient_certification_period": (
        "x",
        "EXCLUDE USING gist (recipient_id WITH =, "
        "certification_period WITH &&, invalidated_at_utc is null WITH =)",
    ),
    "fk_recipient_grade_period_certification": (
        "f",
        "FOREIGN KEY (recipient_certification_identity_id) "
        "REFERENCES erp.recipient_certification_identity(id)",
    ),
    "ck_recipient_grade_period_grade_code": (
        "c",
        "CHECK (grade_code in ('1','2','3','4','5'))",
    ),
    "ex_recipient_grade_period": (
        "x",
        "EXCLUDE USING gist (recipient_id WITH =, "
        "grade_period WITH &&, invalidated_at_utc is null WITH =)",
    ),
    "ck_recipient_benefit_period_benefit_code": (
        "c",
        "CHECK (benefit_code IN "
        "('general', 'basic_livelihood', 'reduction_6', 'reduction_9', 'medical_6', 'medical_9'))",
    ),
    "ex_recipient_benefit_period": (
        "x",
        "EXCLUDE USING gist (recipient_id WITH =, "
        "benefit_period WITH &&, invalidated_at_utc is null WITH =)",
    ),
    "ck_recipient_local_approval_amount_period_amount": (
        "c",
        "CHECK (amount_krw > 0)",
    ),
    "ex_recipient_local_approval_amount_period": (
        "x",
        "EXCLUDE USING gist (recipient_id WITH =, "
        "approval_period WITH &&, invalidated_at_utc is null WITH =)",
    ),
}
W1C_GRADE_CONT_FUNCTION = (
    "CREATE OR REPLACE FUNCTION erp.fn_w1c_assert_grade_containment() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "FROM erp.recipient_certification_period FOR SHARE "
    "IF NOT pg_trigger_depth() > 0 THEN RETURN NEW; END IF; "
    "PERFORM 'ck_recipient_grade_period_containment'; "
    "END; $$;"
)
W1C_IDENTITY_FN = (
    "CREATE OR REPLACE FUNCTION erp.fn_recipient_certification_number_immutable() "
    "RETURNS trigger AS $$ BEGIN "
    "IF OLD.recipient_id IS DISTINCT FROM NEW.recipient_id OR "
    "OLD.certification_number IS DISTINCT FROM NEW.certification_number THEN "
    "RAISE EXCEPTION 'ck_recipient_certification_identity_immutable'; END IF; "
    "RETURN NEW; END; $$;"
)
W1C_IDENTITY_TRIGGER = (
    "CREATE TRIGGER bu_recipient_certification_number_immutable"
    " UPDATE OF recipient_id, certification_number ON erp.recipient_certification_identity"
)


def _to_posix(path: Path) -> str:
    return path.as_posix()


def _lf_normalized_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _to_hash(path: Path) -> str:
    return hashlib.sha256(_lf_normalized_bytes(path)).hexdigest().upper()


def _down_revision_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) is str:
        return (value,)
    if isinstance(value, tuple):
        if not value:
            return ()
        if any(type(item) is not str for item in value):
            pytest.fail("W2_ALEMBIC_DOWN_REVISION_INVALID")
        return value
    if isinstance(value, list):
        if any(type(item) is not str for item in value):
            pytest.fail("W2_ALEMBIC_DOWN_REVISION_INVALID")
        return tuple(value)
    pytest.fail("W2_ALEMBIC_DOWN_REVISION_INVALID")


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ALEMBIC_ROOT))
    return ScriptDirectory.from_config(config)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_r0_w2_read_only_contract_01_chain_and_single_forward_head() -> None:
    script = _script_directory()
    revisions = list(script.walk_revisions())
    by_id = {revision.revision: revision for revision in revisions}

    revision_0018 = by_id.get(ALEMBIC_HEADLESS_DB)
    revision_0019 = by_id.get(ALEMBIC_READ_ONLY_DB)
    if revision_0018 is None:
        pytest.fail("W2_0018_MISSING")
    if revision_0019 is None:
        pytest.fail("W2_0019_MISSING")

    assert revision_0018.revision == W2_REVISION
    assert _down_revision_values(revision_0018.down_revision) == (W2_PREV_REVISION,)

    assert revision_0019.revision == R0_REVISION
    assert _down_revision_values(revision_0019.down_revision) == (W2_REVISION,)

    children = [
        revision
        for revision in revisions
        if W2_REVISION in _down_revision_values(revision.down_revision)
    ]
    if len(children) != 1:
        pytest.fail("W2_CHAIN_DIRECT_CHILD_NOT_UNIQUE")

    heads = tuple(script.get_heads())
    if len(heads) != 1:
        pytest.fail("W2_CHAIN_MULTI_HEAD")
    forward_lineage = {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }
    assert R0_REVISION in forward_lineage


def test_r0_w2_read_only_contract_02_file_hashes_are_expected() -> None:
    for path, expected_hash in EXPECTED_HASHES.items():
        assert path.exists()
        assert _to_hash(path) == expected_hash
    for path in PRODUCT_PRESENCE_PATHS:
        assert path.exists()
        digest = _to_hash(path)
        if len(digest) != 64:
            pytest.fail("W2_POSTCHECK_HASH_SHAPE")


def test_r0_w2_read_only_contract_03_0019_offline_sql_has_exact_guard_trigger_pairs() -> None:
    source = _read_text(ALEMBIC_0019_PATH).lower()

    if "drop function" in source:
        pytest.fail("W2_0019_DROPS_FUNCTIONS")
    if "drop table" in source:
        pytest.fail("W2_0019_DROPS_TABLE")
    if "drop trigger if exists" in source:
        pytest.fail("W2_0019_DROP_TRIGGER_IF_EXISTS")

    drop_pairs = [
        (name, table)
        for name, table in re.findall(
            r"drop\s+trigger\s+([a-z_][a-z0-9_]*)\s+on\s+([a-z_][a-z0-9_.]+)",
            source,
        )
    ]
    expected_pairs = {
        ("ct_service_plan_notice_before_contract_start", "erp.recipient_service_plan_notice"),
        ("ct_service_plan_notice_within_contract", "erp.recipient_service_plan_notice"),
        ("ct_service_plan_notice_within_certification", "erp.recipient_service_plan_notice"),
        ("ct_recipient_contract_service_plan_reverse_guard", "erp.recipient_contract"),
        (
            "ct_recipient_certification_period_service_plan_reverse_guard",
            "erp.recipient_certification_period",
        ),
    }

    if len(drop_pairs) != 5:
        pytest.fail("W2_0019_DROPPED_TRIGGER_COUNT")
    if set(drop_pairs) != expected_pairs:
        pytest.fail("W2_0019_DROPPED_TRIGGER_SET")
    if len(set(name for name, _ in drop_pairs)) != 5:
        pytest.fail("W2_0019_DROPPED_TRIGGER_DUP")

    immutable_pairs = {
        ("ct_recipient_contract_recipient_id_immutable", "erp.recipient_contract"),
        (
            "ct_recipient_certification_period_recipient_id_immutable",
            "erp.recipient_certification_period",
        ),
    }
    if immutable_pairs & set(drop_pairs):
        pytest.fail("W2_0019_IMMUTABLE_TRIGGER_DROPPED")

    if not re.search(
        r"revoke\s+insert,\s*update,\s*delete,\s*truncate\s+on\s+table\s+"
        r"erp\.recipient_service_plan_notice\s+from\s+erp_app",
        source,
        flags=re.IGNORECASE,
    ):
        pytest.fail("W2_0019_APP_REVOKE_MISSING")

    if not re.search(
        r"revoke\s+usage,\s*update\s+on\s+sequence\s+"
        r"erp\.recipient_service_plan_notice_id_seq\s+from\s+erp_app",
        source,
        flags=re.IGNORECASE,
    ):
        pytest.fail("W2_0019_APP_SEQ_REVOKE_MISSING")

    if "grant" in source:
        pytest.fail("W2_0019_GRANT_FOUND")


def test_r0_w2_read_only_contract_04_0019_downgrade_is_forward_only() -> None:
    source = _read_text(ALEMBIC_0019_PATH).lower()
    if "raise runtimeerror" not in source:
        pytest.fail("W2_0019_MISSING_RUNTIME_ERROR")


def test_r0_w2_read_only_contract_05_markers_and_dispatch_in_postcheck() -> None:
    source = _read_text(POSTCHECK_PATH)
    if 'print("W2_SERVICE_PLAN_NOTICE_DB_POSTCHECK_OK")' not in source:
        pytest.fail("W2_POSTCHECK_MISSING_0018_MARKER")
    if 'print("R0_W2_READ_ONLY_DB_POSTCHECK_OK")' not in source:
        pytest.fail("W2_POSTCHECK_MISSING_0019_MARKER")

    marker_block = re.findall(
        r"if current_revision == R0_W2_READ_ONLY_REVISION:\s*\n"
        r"\s*print\(\"R0_W2_READ_ONLY_DB_POSTCHECK_OK\"\)\s*\n"
        r"\s*elif current_revision == W2_SERVICE_PLAN_NOTICE_REVISION:\s*\n"
        r"\s*print\(\"W2_SERVICE_PLAN_NOTICE_DB_POSTCHECK_OK\"\)",
        source,
        flags=re.MULTILINE,
    )
    if not marker_block:
        pytest.fail("W2_POSTCHECK_MISSING_MARKER_DISPATCH")

    if not re.search(
        r"if current_revision in W2_LINEAGE_REVISIONS:\s*\n"
        r"\s*_verify_w2_service_plan_notice_contract\(\s*connection,\s*"
        r"read_only=\(current_revision == R0_W2_READ_ONLY_REVISION\),\s*\)",
        source,
        flags=re.MULTILINE,
    ):
        pytest.fail("W2_POSTCHECK_MISSING_VERIFY_CALL")

    if "contype IN ('p', 'f', 'c')" not in source:
        pytest.fail("W2_POSTCHECK_MISSING_CONTYPE_PFC_FILTER")


def test_r0_w2_read_only_contract_06_restore_dispatch_and_pythonexe_contract() -> None:
    restore_source = _read_text(RESTORE_PATH)

    for revision in (W2_REVISION, R0_REVISION):
        if revision not in restore_source:
            pytest.fail(f"W2_RESTORE_MISSING_REVISION_{revision}")

    if '"R0_W2_READ_ONLY_DB_POSTCHECK_OK"' not in restore_source:
        pytest.fail("W2_RESTORE_MISSING_POSTCHECK_MARKER")
    if '$VerifyArgs["PythonExe"] = $PythonExe' not in restore_source:
        pytest.fail("W2_RESTORE_MISSING_PYTHONEXE_FORWARD")


def _write_fake_python_exe(path: Path, log_path: Path) -> None:
    content = "\n".join(
        [
            "@echo off",
            f'set "LOG={log_path.as_posix()}"',
            'set "LINE=%*"',
            '>>"%LOG%" echo %LINE%',
            "exit /b 0",
        ]
    )
    path.write_text(content, encoding="utf-8")


def test_r0_w2_read_only_contract_07_fake_python_executes_verify_double_invocation() -> None:
    workdir = Path(os.getenv("TEMP", os.getcwd())) / "r0w2-readonly-test"
    fake = workdir / "fake-python.cmd"
    log = workdir / "fake-python.log"
    workdir.mkdir(parents=True, exist_ok=True)
    if log.exists():
        log.unlink()

    _write_fake_python_exe(fake, log)

    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(VERIFY_PATH),
        "-DatabaseUrl",
        "postgresql+psycopg://ci@127.0.0.1/sswcenter_test",
        "-PythonExe",
        str(fake),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT / "backend"),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"VERIFY_WITH_FAKE_PYTHON_EXIT_{result.returncode}")

    calls = [line.strip() for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(calls) != 2:
        pytest.fail("W2_FAKE_PYTHON_INVOKE_COUNT")
    if not any("-m alembic" in call and "current" in call for call in calls):
        pytest.fail("W2_FAKE_PYTHON_MISSING_ALEMBIC_CALL")
    if not any("-m app.db.postcheck_w1a_vs1" in call for call in calls):
        pytest.fail("W2_FAKE_PYTHON_MISSING_POSTCHECK_CALL")


class _FakeRow:
    def __init__(self, fields: tuple[str, ...], values: tuple[Any, ...]):
        self._fields = fields
        self._values = values
        for name, value in zip(fields, values, strict=True):
            setattr(self, name, value)

    def __getitem__(self, index: int) -> Any:
        return self._values[index]

    def __iter__(self):
        return iter(self._values)


class _FakeResult:
    def __init__(self, rows: Iterable[_FakeRow] | None = None, scalar: Any | None = None) -> None:
        self._rows = list(rows or ())
        self._scalar = scalar

    def scalar(self) -> Any:
        if self._rows:
            return self._rows[0][0]
        return self._scalar

    def one(self) -> Any:
        if len(self._rows) != 1:
            raise AssertionError("single row expected")
        return self._rows[0]

    def one_or_none(self) -> Any:
        if not self._rows:
            return None
        return self.one()

    def scalar_one_or_none(self) -> Any:
        if not self._rows:
            return None
        return self.scalar()

    def scalar_one(self) -> Any:
        if len(self._rows) != 1:
            raise AssertionError("exactly one row expected")
        return self.scalar()

    def scalars(self) -> list[Any]:
        return [row[0] for row in self._rows]

    def __iter__(self):
        return iter(self._rows)


class _FakeConnection:
    def __init__(
        self,
        *,
        read_only: bool,
        constraints: Mapping[str, tuple[Any, ...]],
        app_table_privileges: tuple[bool, ...],
        backup_table_privileges: tuple[bool, ...],
        app_sequence_privileges: tuple[bool, ...],
        backup_sequence_privileges: tuple[bool, ...],
        trigger_pairs: set[tuple[str, str]],
        ownership: tuple[str, str, str],
        function_names: Iterable[str],
        columns_with_iur_priv: Iterable[str],
    ) -> None:
        self.read_only = read_only
        self.constraints = dict(constraints)
        self.app_table_privileges = app_table_privileges
        self.backup_table_privileges = backup_table_privileges
        self.app_sequence_privileges = app_sequence_privileges
        self.backup_sequence_privileges = backup_sequence_privileges
        self.trigger_pairs = set(trigger_pairs)
        self.ownership = ownership
        self.function_names = set(function_names)
        self.columns_with_iur_priv = tuple(columns_with_iur_priv)

    def execute(self, statement: Any, parameters: Mapping[str, Any] | None = None) -> _FakeResult:
        sql = getattr(statement, "text", None)
        if sql is None:
            sql = str(statement)
        sql_text = str(sql).lower()
        params = dict(parameters or {})

        if "to_regclass(:qualified) is not null" in sql_text:
            return _FakeResult([_FakeRow(("exists",), (True,))])

        if "select exists" in sql_text and "c.relkind = 's'" in sql_text:
            return _FakeResult([_FakeRow(("exists",), (True,))])

        if "pg_get_userbyid(tbl.relowner)" in sql_text:
            return _FakeResult(
                [
                    _FakeRow(
                        ("table_owner", "sequence_owner", "owned_sequence"),
                        self.ownership,
                    )
                ]
            )

        if "select exists" in sql_text and "d.deptype = 'i'" in sql_text:
            return _FakeResult([_FakeRow(("identity_dependency",), (True,))])

        if "a.attidentity" in sql_text:
            return _FakeResult([_FakeRow(("attidentity",), ("d",))])

        if "from pg_constraint" in sql_text:
            rows: list[_FakeRow] = []
            for name, snapshot in sorted(self.constraints.items()):
                values = snapshot
                rows.append(
                    _FakeRow(
                        (
                            "conname",
                            "contype",
                            "definition",
                            "local_columns",
                            "ref_schema",
                            "ref_table",
                            "ref_columns",
                            "confdeltype",
                            "confupdtype",
                            "confmatchtype",
                            "condeferrable",
                            "condeferred",
                            "convalidated",
                        ),
                        (
                            name,
                            values[0],
                            values[1],
                            values[2],
                            values[3],
                            values[4],
                            values[5],
                            values[6],
                            values[7],
                            values[8],
                            values[9],
                            values[10],
                            values[11],
                        ),
                    )
                )
            return _FakeResult(rows)

        if "from pg_proc" in sql_text:
            names = set(params.get("names", ()))
            rows = [
                _FakeRow(("proname",), (name,))
                for name in sorted(self.function_names)
                if name in names
            ]
            return _FakeResult(rows)

        if "from pg_trigger" in sql_text:
            names = set(params.get("names", ()))
            rows = [
                _FakeRow(("tgname", "relname"), (name, table))
                for name, table in sorted(self.trigger_pairs)
                if not names or name in names
            ]
            return _FakeResult(rows)

        if "has_table_privilege(" in sql_text:
            role = params.get("role_name")
            if role == "erp_app":
                return _FakeResult([
                    _FakeRow(
                        (
                            "select",
                            "insert",
                            "update",
                            "delete",
                            "truncate",
                            "references",
                            "trigger",
                            "maintain",
                        ),
                        self.app_table_privileges,
                    )
                ])
            if role == "erp_backup":
                return _FakeResult([
                    _FakeRow(
                        (
                            "select",
                            "insert",
                            "update",
                            "delete",
                            "truncate",
                            "references",
                            "trigger",
                            "maintain",
                        ),
                        self.backup_table_privileges,
                    )
                ])
            return _FakeResult([
                _FakeRow(
                    (
                        "select",
                        "insert",
                        "update",
                        "delete",
                        "truncate",
                        "references",
                        "trigger",
                        "maintain",
                    ),
                    (False,) * 8,
                )
            ])

        if "a.attacl is not null" in sql_text:
            rows = [_FakeRow(("attname",), (name,)) for name in self.columns_with_iur_priv]
            return _FakeResult(rows)

        if "has_sequence_privilege(\n                       'erp_app'" in sql_text:
            return _FakeResult(
                [_FakeRow(("usage", "select", "update"), self.app_sequence_privileges)]
            )

        if "has_sequence_privilege(\n                       'erp_backup'" in sql_text:
            return _FakeResult(
                [_FakeRow(("usage", "select", "update"), self.backup_sequence_privileges)]
            )

        raise AssertionError(f"Unhandled SQL in fake catalog: {sql_text[:120]}")


class _FakeW1CConnection(_FakeConnection):
    def __init__(
        self,
        *,
        trigger_pairs: set[tuple[str, str]] | None = None,
        trigger_states: Mapping[str, tuple[bool, bool]] | None = None,
    ) -> None:
        self.w1c_trigger_states = dict(W1C_CONTAINMENT_TRIGGER_STATES)
        if trigger_states:
            self.w1c_trigger_states.update(trigger_states)
        trigger_pairs = set(trigger_pairs or W1C_CONTAINMENT_TRIGGER_PAIRS)
        super().__init__(
            read_only=False,
            constraints={},
            app_table_privileges=W1C_APP_TABLE_PRIVILEGES,
            backup_table_privileges=W1C_BACKUP_TABLE_PRIVILEGES,
            app_sequence_privileges=(False, False, False),
            backup_sequence_privileges=(False, False, False),
            trigger_pairs=trigger_pairs,
            ownership=(postcheck.W2_OWNER, postcheck.W2_OWNER, postcheck.W2_OWNED_SEQUENCE),
            function_names=postcheck.W1C_FUNCTIONS,
            columns_with_iur_priv=(),
        )

    def execute(self, statement: Any, parameters: Mapping[str, Any] | None = None) -> _FakeResult:
        sql = getattr(statement, "text", None)
        if sql is None:
            sql = str(statement)
        sql_text = str(sql).lower()
        params = dict(parameters or {})

        if (
            "information_schema.columns" in sql_text
            and "table_name = any(:table_names)" in sql_text
            and "generation_expression" not in sql_text
        ):
            rows = [
                _FakeRow(("column_name",), (column,))
                for table_name in params.get("table_names", ())
                for column in W1C_TRIGGER_RELATED_COLUMNS.get(str(table_name), {})
            ]
            return _FakeResult(rows)

        if (
            "information_schema.columns" in sql_text
            and "is_generated = 'always'" in sql_text
        ):
            table_names = {str(table_name) for table_name in params.get("table_names", ())}
            rows = [
                _FakeRow(
                    ("table_name", "column_name", "udt_name", "generation_expression"),
                    (table_name, column_name, udt_name, generation_expression),
                )
                for (table_name, column_name), (
                    udt_name,
                    generation_expression,
                ) in W1C_GENERATED_COLUMNS.items()
                if table_name in table_names
            ]
            return _FakeResult(rows)

        if (
            "information_schema.columns" in sql_text
            and "table_name = :table_name" in sql_text
        ):
            table_name = str(params.get("table_name"))
            rows = [
                _FakeRow(("column_name", "data_type", "is_nullable"), (name, dtype, nullable))
                for name, (dtype, nullable) in W1C_TRIGGER_RELATED_COLUMNS.get(
                    table_name, {}
                ).items()
            ]
            return _FakeResult(rows)

        if (
            "has_table_privilege('erp_app'" in sql_text
            and "references" not in sql_text
            and "trigger" not in sql_text
        ):
            return _FakeResult(
                [
                    _FakeRow(
                        ("select", "insert", "update", "delete", "truncate"),
                        W1C_APP_TABLE_PRIVILEGES,
                    )
                ]
            )

        if (
            "has_table_privilege('erp_backup'" in sql_text
            and "references" not in sql_text
            and "trigger" not in sql_text
        ):
            return _FakeResult(
                [
                    _FakeRow(
                        ("select", "insert", "update", "delete", "truncate"),
                        W1C_BACKUP_TABLE_PRIVILEGES,
                    )
                ]
            )

        if "from pg_constraint" in sql_text:
            rows = [
                _FakeRow(("conname", "contype", "definition"), (name, contype, definition))
                for name, (contype, definition) in sorted(W1C_FAKE_CONSTRAINTS.items())
            ]
            return _FakeResult(rows)

        if "pg_get_functiondef(" in sql_text:
            if "fn_w1c_assert_grade_containment" in sql_text:
                return _FakeResult(
                    [_FakeRow(("pg_get_functiondef",), (W1C_GRADE_CONT_FUNCTION,))]
                )
            if "fn_recipient_certification_number_immutable" in sql_text:
                return _FakeResult(
                    [_FakeRow(("pg_get_functiondef",), (W1C_IDENTITY_FN,))]
                )

        if (
            "pg_get_triggerdef(oid)" in sql_text
            and "bu_recipient_certification_number_immutable" in sql_text
        ):
            return _FakeResult([_FakeRow(("pg_get_triggerdef",), (W1C_IDENTITY_TRIGGER,))])

        if "from pg_trigger" in sql_text:
            tgname_filters = re.findall(r"tgname\s+in\s*\(([^)]*)\)", sql_text)
            in_clause = set()
            if tgname_filters:
                in_clause = set(re.findall(r"'([^']+)'", tgname_filters[0]))
            names = set(params.get("names", ()))
            rows = [
                _FakeRow(
                    ("tgname", "relname", "tgdeferrable", "tginitdeferred"),
                    (
                        name,
                        table,
                        *self.w1c_trigger_states.get((name, table), (True, False)),
                    ),
                )
                for name, table in sorted(self.trigger_pairs)
                if (not names or name in names)
                and (not in_clause or name in in_clause)
            ]
            return _FakeResult(rows)

        return super().execute(statement, parameters)


def _expected_table_privileges(read_only: bool) -> tuple[bool, ...]:
    return (
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ) if read_only else (
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    )


def _expected_sequence_privileges(read_only: bool) -> tuple[bool, ...]:
    return (False, True, False) if read_only else (True, True, False)


def _expected_ownership() -> tuple[str, str, str]:
    return (
        postcheck.W2_OWNER,
        postcheck.W2_OWNER,
        postcheck.W2_OWNED_SEQUENCE,
    )


def _default_catalog(
    *,
    read_only: bool,
    ownership: tuple[str, str, str] | None = None,
    constraints: Mapping[str, tuple[Any, ...]] | None = None,
    app_table_privileges: tuple[bool, ...] | None = None,
    backup_table_privileges: tuple[bool, ...] | None = None,
    app_sequence_privileges: tuple[bool, ...] | None = None,
    backup_sequence_privileges: tuple[bool, ...] | None = None,
    trigger_pairs: set[tuple[str, str]] | None = None,
    columns_with_iur_priv: Iterable[str] | None = None,
) -> _FakeConnection:
    trigger_pairs = set(trigger_pairs or set())
    if not trigger_pairs:
        trigger_pairs = set(postcheck.W2_IMMUTABLE_TRIGGER_CONTRACTS.items())
        if not read_only:
            trigger_pairs |= set(postcheck.W2_GUARD_TRIGGER_CONTRACTS.items())
    expected_app = app_table_privileges or _expected_table_privileges(read_only)
    expected_backup = backup_table_privileges or (
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )
    expected_app_seq = app_sequence_privileges or _expected_sequence_privileges(read_only)
    expected_backup_seq = backup_sequence_privileges or (False, True, False)

    return _FakeConnection(
        read_only=read_only,
        constraints=dict(constraints or postcheck._W2_SERVICE_PLAN_NOTICE_CONSTRAINTS),
        app_table_privileges=expected_app,
        backup_table_privileges=expected_backup,
        app_sequence_privileges=expected_app_seq,
        backup_sequence_privileges=expected_backup_seq,
        trigger_pairs=set(trigger_pairs),
        ownership=ownership or _expected_ownership(),
        function_names=postcheck.W2_FUNCTIONS,
        columns_with_iur_priv=columns_with_iur_priv or (),
    )


def _default_w1c_catalog(
    *,
    trigger_pairs: set[tuple[str, str]] | None = None,
    trigger_states: Mapping[str, tuple[bool, bool]] | None = None,
) -> _FakeW1CConnection:
    return _FakeW1CConnection(
        trigger_pairs=trigger_pairs or set(W1C_CONTAINMENT_TRIGGER_PAIRS),
        trigger_states=trigger_states,
    )


def _mutate_value(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if value is None:
        return "MUTATED"
    if isinstance(value, str):
        return value + "_mut"
    if isinstance(value, tuple):
        if not value:
            return ("mutated",)
        return (f"{str(value[0])}_mut",) + tuple(value[1:])
    return value


def test_r0_w2_read_only_contract_08_fake_catalog_verifier_hardened() -> None:
    baseline = _default_catalog(read_only=True)
    postcheck._verify_w2_service_plan_notice_contract(baseline, read_only=True)

    for field_index in range(len(_expected_ownership())):
        mutated = list(_expected_ownership())
        mutated[field_index] = _mutate_value(mutated[field_index])
        with pytest.raises(SystemExit):
            postcheck._verify_w2_service_plan_notice_contract(
                _default_catalog(
                    read_only=True,
                    ownership=tuple(mutated),
                ),
                read_only=True,
            )

    for (
        constraint_name,
        constraint_snapshot,
    ) in postcheck._W2_SERVICE_PLAN_NOTICE_CONSTRAINTS.items():
        is_fk = constraint_snapshot[0] == "f"
        for index in range(len(constraint_snapshot)):
            if not is_fk and index in (6, 7, 8):
                continue
            mutated = dict(postcheck._W2_SERVICE_PLAN_NOTICE_CONSTRAINTS)
            values = list(constraint_snapshot)
            values[index] = _mutate_value(values[index])
            mutated[constraint_name] = tuple(values)
            with pytest.raises(SystemExit):
                postcheck._verify_w2_service_plan_notice_contract(
                    _default_catalog(read_only=True, constraints=mutated),
                    read_only=True,
                )

    baseline_table = _expected_table_privileges(True)
    for index in range(len(baseline_table)):
        mutated = list(baseline_table)
        mutated[index] = _mutate_value(mutated[index])
        with pytest.raises(SystemExit):
            postcheck._verify_w2_service_plan_notice_contract(
                _default_catalog(
                    read_only=True,
                    app_table_privileges=tuple(mutated),
                ),
                read_only=True,
            )

    baseline_backup = (True, False, False, False, False, False, False, False)
    for index in range(len(baseline_backup)):
        mutated = list(baseline_backup)
        mutated[index] = _mutate_value(mutated[index])
        with pytest.raises(SystemExit):
            postcheck._verify_w2_service_plan_notice_contract(
                _default_catalog(
                    read_only=True,
                    backup_table_privileges=tuple(mutated),
                ),
                read_only=True,
            )

    if postcheck._W2_SERVICE_PLAN_NOTICE_CONSTRAINTS["ck_service_plan_notice_date_order"][2] != (
        "applied_end_date",
        "applied_start_date",
    ):
        pytest.fail("W2_CK_DATE_ORDER_COLUMN_ORDER_CHANGED")

    for _ in ("insert", "update", "references"):
        with pytest.raises(SystemExit):
            postcheck._verify_w2_service_plan_notice_contract(
                _default_catalog(read_only=True, columns_with_iur_priv=("notification_date",)),
                read_only=True,
            )

    baseline_seq = _expected_sequence_privileges(True)
    for index in range(len(baseline_seq)):
        mutated = list(baseline_seq)
        mutated[index] = _mutate_value(mutated[index])
        with pytest.raises(SystemExit):
            postcheck._verify_w2_service_plan_notice_contract(
                _default_catalog(
                    read_only=True,
                    app_sequence_privileges=tuple(mutated),
                ),
                read_only=True,
            )

    baseline_backup_seq = (False, True, False)
    for index in range(len(baseline_backup_seq)):
        mutated = list(baseline_backup_seq)
        mutated[index] = _mutate_value(mutated[index])
        with pytest.raises(SystemExit):
            postcheck._verify_w2_service_plan_notice_contract(
                _default_catalog(
                    read_only=True,
                    backup_sequence_privileges=tuple(mutated),
                ),
                read_only=True,
            )


def test_r0_w2_read_only_contract_09_trigger_pair_matching_allows_same_name_other_tables() -> None:
    trigger_pairs = set(postcheck.W2_IMMUTABLE_TRIGGER_CONTRACTS.items()) | set(
        postcheck.W2_GUARD_TRIGGER_CONTRACTS.items()
    )
    trigger_pairs.add(("ct_service_plan_notice_before_contract_start", "recipient_contract"))
    trigger_pairs.add(
        ("ct_recipient_contract_service_plan_reverse_guard", "recipient_service_plan_notice")
    )

    postcheck._verify_w2_service_plan_notice_contract(
        _default_catalog(read_only=False, trigger_pairs=trigger_pairs),
        read_only=False,
    )


def test_r0_w2_read_only_contract_10_w1c_containment_trigger_contract_is_targeted() -> None:
    unrelated_pairs = set(W1C_CONTAINMENT_TRIGGER_PAIRS) | {
        ("ct_service_plan_notice_before_contract_start", "recipient_service_plan_notice"),
        ("ct_service_plan_notice_within_contract", "recipient_service_plan_notice"),
        ("ct_recipient_contract_service_plan_reverse_guard", "recipient_contract"),
    }
    postcheck._verify_w1c_contract(_default_w1c_catalog(trigger_pairs=unrelated_pairs))

    missing_pairs = {
        pair
        for pair in W1C_CONTAINMENT_TRIGGER_PAIRS
        if pair != ("ct_recipient_grade_period_containment", "recipient_grade_period")
    }
    with pytest.raises(SystemExit):
        postcheck._verify_w1c_contract(_default_w1c_catalog(trigger_pairs=missing_pairs))

    wrong_table_pairs = {
        ("ct_recipient_grade_period_containment", "recipient_contract"),
        ("ct_recipient_certification_grade_containment", "recipient_grade_period"),
    }
    with pytest.raises(SystemExit):
        postcheck._verify_w1c_contract(_default_w1c_catalog(trigger_pairs=wrong_table_pairs))

    for trigger in W1C_CONTAINMENT_TRIGGER_STATES:
        bad_states = dict(W1C_CONTAINMENT_TRIGGER_STATES)
        baseline_state = W1C_CONTAINMENT_TRIGGER_STATES[trigger]
        bad_states[trigger] = (False, baseline_state[1])
        with pytest.raises(SystemExit):
            postcheck._verify_w1c_contract(_default_w1c_catalog(trigger_states=bad_states))
