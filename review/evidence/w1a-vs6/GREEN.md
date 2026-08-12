# W1A-VS6 GREEN Verification

## Decision

`GREEN_VALID`

This is a pre-commit WIP evidence record. No stage, commit, push, reset, or
rebase was performed.

## Candidate and baseline

- Base HEAD: `cb5f49937e2abbb2373f52ee4564f790101ca21f`
- `backend/app/domains/staff/legacy_import.py`:
  `1470390AAE9C4D1D083654B30A8868CBCFF5CECE417ECBB29CA100C6AFC16104`
- `backend/tests/test_w1a_vs6_import_contract.py`:
  `8DD16C69025FD9B03752316725610F634DE08FCCFCC6483006846B3944D58DCA`
- `backend/tests/test_w1a_vs6_postgres.py`:
  `7D1F042E5DC1866BAF8794CF91E85C28EA94FF0B4E6062A59A3D6EC3D258A3EB`
- `scripts/test-w1a-vs6-postgres.ps1`:
  `1224092AB972A361BD1F3EE08D5141807D499EF8496AA25EAEBE51EEA4AEAD3D`

The product and import-contract hashes are unchanged. The final worktree
status is six modified tracked files (the pre-existing product/schema/VS5
changes plus the import test, PG test, and wrapper), staged `0`, and one
untracked evidence file (`GREEN.md`). No unrelated file was edited by this
verification lane.

## R1 evidence-gap closure

- Post-mutation rollback: the replacement path uses a real replacement staff.
  A PostgreSQL `AFTER INSERT` trigger raises after the replacement INSERT is
  reached and the old row was invalidated at `row_version=2`; its diagnostic contains the exact old mapping
  and replacement staff IDs. The SQLAlchemy `handle_error` probe requires the
  `W1A_VS6_TRIGGER_REPLACEMENT_INSERT_REACHED` marker, then compares the full
  mapping-key rows and actor mapping-audit rows before/after. Trigger/function
  removal is asserted in `finally` with zero remaining catalog rows. This path
  passed as part of the 39/39 PG run.
- Thread infrastructure: the previous pre-summary warning surface could be
  treated as green. `Test-HarnessOutput` now fail-closes on
  `PytestUnhandledThreadExceptionWarning` and `Exception in thread` while
  retaining the atexit/Fatal/unraisable checks. Synthetic output proves
  `SYNTHETIC_THREAD_WARNING_WOULD_EMIT_GREEN=False`,
  `W1A_VS6_SYNTHETIC_THREAD_WARNING_HARNESS_FAILURE=True`, and
  `W1A_VS6_SYNTHETIC_THREAD_WARNING_SELF_CHECK_OK=True`.
- Runtime artifact scan: the binary cluster/backup remain under the isolated
  `sswcenter-w1a-vs6-pg-*` TempRoot. PostgreSQL log, offline SQL, and main /
  restore data-root logs are under the dedicated
  `sswcenter-w1a-vs6-artifacts-*` root and are scanned before cleanup through
  an explicit `-ArtifactRoot`. The initial wrapper artifact-scan invocation
  failed closed at its path boundary; the final dedicated-root run passed with
  scan exit `0`, marker
  `W1A_LEAK_GATE_GREEN`, and `239` scanned runtime files. `Invoke-Psql` SQL
  files remained under `ArtifactRoot` until this scan; immediately before the
  scan `W1A_VS6_PSQL_ARTIFACT_COUNT_BEFORE_LEAK_SCAN=1` and
  `W1A_VS6_PSQL_ARTIFACT_ASSERTION=1` were emitted. Validated ArtifactRoot
  cleanup then removed them with runtime-artifact remaining `0`.

## Static and collection checks

All commands used the primary checkout runtime
`C:\Users\USER\Documents\sswcenter-ver-2.1 2\backend\.venv\Scripts\python.exe`.

| Check | Result |
| --- | --- |
| Ruff format check on app and owned W1A-VS6 Python tests | exit `0` |
| Ruff check on app and owned W1A-VS6 Python tests | exit `0` |
| `mypy app` | exit `0`, 30 source files |
| mypy on owned W1A-VS6 PG/import tests | exit `0`, 2 source files |
| compileall app and owned W1A-VS6 Python tests | exit `0` |
| pytest collect-only for the four wrapper files | exit `0`, 39 collected |
| PowerShell AST parse of `scripts/test-w1a-vs6-postgres.ps1` | exit `0`, 0 parse errors |
| `git diff --check` | exit `0` |

## Outer-log safety probe

`test_vs6_10_database_session_sqlalchemy_surfaces_are_safe` and
`test_vs6_11_session_factory_sqlalchemy_surfaces_are_safe` remain sealed at
the frozen import-test hash and pass in both environments. Each environment
reports outer observer `count=1`, importer probe `count=1`, and zero leakage
for all seven synthetic vectors; DATA_ROOT cleanup is complete. The handler
is root-only, the dedicated pre-redaction observer is separate, and importer
DEBUG/propagate state is restored in `finally`.

## Regression harness

- Non-PG backend regression (`--ignore=tests/test_w1a_vs6_postgres.py`):
  `122 passed, 38 skipped, 1 warning`, exit `0`.

## Isolated PostgreSQL harness

Command:

```powershell
$env:SSWCENTER_PYTHON_EXE = 'C:\Users\USER\Documents\sswcenter-ver-2.1 2\backend\.venv\Scripts\python.exe'
powershell.exe -NoProfile -File .\scripts\test-w1a-vs6-postgres.ps1 -ExpectGreen
```

Result: wrapper exit `0`, `W1A_VS6_GREEN`.

- Offline apply: `database:0 apply:0 verify:0`.
- Migration lifecycle: `down:0 up:0 down_again:0 up_again:0`.
- Actual pytest run: `collected:39 passed:39 failed:0 skipped:0 errors:0`.
- Postcheck: exit `0`, `W1A_VS6_POSTCHECK_OK=1`.
- Restore: `dump:0 database:0 restore:0 verify:0 postcheck:0`.
- PSQL artifact preservation: count before leak scan `1`, assertion `1`.
- Runtime artifact leak: explicit gate exit `0`, scanned `239`,
  `W1A_LEAK_GATE_GREEN`.
- Drop/stop/cleanup: offline drop `0`, restore drop `0`, PG stop `0`,
  temp-cluster/listener/artifact/media/runtime-artifact remaining `0`.
- Synthetic harness self-check:
  `SYNTHETIC_ATEXIT_TRACEBACK_WOULD_EMIT_RED_VALID=False`,
  `W1A_VS6_SYNTHETIC_ATEXIT_HARNESS_FAILURE=True`,
  `W1A_VS6_SYNTHETIC_ATEXIT_SELF_CHECK_OK=True`,
  `SYNTHETIC_THREAD_WARNING_WOULD_EMIT_GREEN=False`,
  `W1A_VS6_SYNTHETIC_THREAD_WARNING_HARNESS_FAILURE=True`,
  `W1A_VS6_SYNTHETIC_THREAD_WARNING_SELF_CHECK_OK=True`.

The sealed expected RED contract remains independently reported by the
wrapper as `collected:39 run_exit:1 passed:23 failed:16 skipped:0 errors:0`
with these 16 exact markers:

1. `W1A_VS6_ALLOWLIST_MISSING`
2. `W1A_VS6_LICENSE_CANONICAL_APPLY_ONE_MISSING`
3. `W1A_VS6_LICENSE_CANONICAL_APPLY_TWO_MISSING`
4. `W1A_VS6_LICENSE_CANONICAL_PREPARE_ONE_MISSING`
5. `W1A_VS6_LICENSE_CANONICAL_PREPARE_TWO_MISSING`
6. `W1A_VS6_LICENSE_LEGACY_ALIAS_ACCEPTED`
7. `W1A_VS6_MAPPING_ACTIVE_LOCK_MISSING`
8. `W1A_VS6_MAPPING_CONCURRENT_VERSIONING_MISSING`
9. `W1A_VS6_MAPPING_EXPECTED_VERSION_REQUIRED`
10. `W1A_VS6_MAPPING_REPLACEMENT_MISSING`
11. `W1A_VS6_MAPPING_STALE_VERSION_REJECTED`
12. `W1A_VS6_PII_DATABASE_SESSION_EXCEPTION_CAUSE_LINKED`
13. `W1A_VS6_PII_EXCEPTION_CAUSE_LINKED`
14. `W1A_VS6_PII_SESSION_FACTORY_EXCEPTION_CAUSE_LINKED`
15. `W1A_VS6_REHIRE_EMPLOYMENT_MISSING`
16. `W1A_VS6_REHIRE_LICENSE_ROLLBACK_EXACT_MISSING`

## Leak gate

The commands were run sequentially after the PG wrapper:

1. Normal mode: exit `0`, scanned `234`, `W1A_LEAK_GATE_GREEN`.
2. `-SelfTest`: exit `0`, `W1A_LEAK_GATE_SELF_TEST_OK`.

## Final WIP state

All required gates passed. The evidence file was updated only after those
passes. No commit was created; all changes remain unstaged WIP.
