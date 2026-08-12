# W1D Spark XHigh repaired-candidate regression R1

## Candidate and execution boundary

- Candidate: `ee905fd2dc9859fa83090bb7fa316b9748cf06f8`.
- Parent: `a64f6eda267274febb50578cbd317081e3771877`.
- Spark task: `019fb81e-d66f-7183-90ca-d360d9b05223`.
- Model/effort: `gpt-5.3-codex-spark` / xhigh.
- Delegated worktree: `C:\Users\USER\.codex\worktrees\987d\2.1`.
- Execution checkout: `C:\sswcenter\2.1`, used only after exact SHA and clean
  state were independently verified because the delegated worktree had no
  `.venv` or `node_modules` junctions.
- Mode: verification only, no agents, no tracked edits, and no live wrapper
  after a pre-live failure.

The execution checkout began and ended clean at the exact candidate with
staged/tracked/untracked counts `0/0/0`. The candidate had 14 changed paths
against its parent.

## Passing gates

- PostgreSQL test parent blob: `307587` bytes; candidate delta append-only
  (`313` added diff lines, zero deleted).
- Ruff check for focused W1D tests and the append-only PostgreSQL file: exit
  `0`. Focused Ruff format check excluding the append-only file: exit `0`.
- Focused W1D pytest: `67 passed / 20 skipped / 1 warning`, exit `0`.
- App mypy: `53` source files, no issues, exit `0`.
- Alembic heads/history/history-verbose: exits `0`.
- Alembic offline upgrade SQL with an explicit PostgreSQL URL: exit `0`.
- OpenAPI generated types: `OPENAPI_TYPES_UP_TO_DATE`, exit `0`.
- Frontend Vitest: `111 passed` in `18` files, exit `0`.
- TypeScript build mode, oxlint, and production build: exits `0`.
- Playwright listing: `66` tests in `10` files, exit `0`.
- Generated frontend artifact paths were absent after an exact-target cleanup
  dry-run/remove/postcheck; final Git state remained clean.

## Blocking pre-live test failure

The full non-live backend command, excluding the live PostgreSQL file, stopped
at:

```text
backend/tests/test_schema_contract.py::test_current_metadata_contains_expected_tables
1 failed / 10 passed / 2 skipped / 1 warning / exit 1
```

The exact assertion reported the W1D table `erp.recipient_contract` as extra in
current SQLAlchemy metadata. Product metadata and the W1D focused contract
correctly contained the table; the global exact-set fixture had not been
updated when W1D added it. This is a blocking test-contract omission, not proof
that the product table is extraneous.

`alembic check` also exited `1` because the non-live shell did not have a valid
runtime `SSWCENTER_DATABASE_URL`/PostgreSQL connection. Heads/history and
offline SQL passed. This is retained as an environment-bound unavailable live
check and is not independently classified as a product defect.

## Live and cleanup proof

The pre-live failure prohibited the wrapper. Live wrapper invocation count was
zero; no process matched the wrapper path, reserved listeners on
`55442/18092/14192` were zero, and no named frontend artifacts remained.
Existing unrelated PostgreSQL/Node services were observed but did not own the
reserved ports.

Operational troubles retained: the first delegated worktree lacked dependency
junctions; one PowerShell quoting error interrupted an early byte-prefix probe;
a cleanup command failed from quoting/policy interpretation; execution moved to
the exact clean main checkout under an explicit handoff; and exact-target
`git clean -ndX/-fdX` ultimately found no remaining artifacts.

SPARK_W1D_REPAIRED_CANDIDATE_REGRESSION=FAIL
