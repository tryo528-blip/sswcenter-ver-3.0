# Joseph W1D Phase-1 exact-byte design/RED re-audit R7/R20

## Decision

**REQUIRED_CHANGES**. R20 closes the R6 H01, H04, and M01 design attacks in the
JSON/DB-domain cases exercised by its self-checks, and H02/H03 did not regress.
It is not approvable as sealed because the shared audit-projection predicate
can accept malformed non-JSON Python values, and the plan/RED package has stale
status/seal wording. No product implementation was found or changed.

This is a static Phase-1 design/RED decision only. It is not product GREEN,
runtime PASS, PostgreSQL PASS, backend PASS, frontend PASS, or browser PASS.

## Authority, checkout identity, and boundary

I followed the requested read order: `README.md`; `docs/00_정본_문서_목록.md`
and the named `docs/AI_업무분담_운영규정_v3.5.md`; the W1D assignment packet;
canonical docs 02/03/04 at the cited W1D/W1C/audit/recipient/contract/
transition sections; Joseph R6; the office log through ENV-076; then the
seven R20 files. This was a standalone read-only reviewer pass. I did not
invoke the live wrapper, PostgreSQL cluster, backend, frontend, or browser,
and made no Git mutation.

| Observation | Exact value |
|---|---|
| cwd | `C:\sswcenter\2.1` |
| branch | `codex/w1d-contract-transition` |
| HEAD | `266beeaa2d150371ccd1a0f26f69249eca86ba16` |
| tracked delta before report | 0 |
| staged delta before report | 0 |
| untracked before report | 16 |
| product W1D revision/domain | absent |

The 16 pre-existing untracked paths were the seven R20 package paths, the
office log, the assignment packet, five prior Joseph reports, and two prior
Opus reports exactly as shown by `git status --porcelain`.
They were preserved. This report is the only new path authorized by the
assignment.

## Exact input seals

The seven supplied R20 seals matched exactly at the audit snapshot:

| Path | Bytes | SHA-256 |
|---|---:|---|
| `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md` | 51127 | `cb151974e2680962888e748e9cc02d27ad9627479bd7e812ca6fcf205edbac12` |
| `review/evidence/w1d/RED.md` | 3028 | `d1729dc131b543ca42f5bd3f8bcb703fa37775f1972d0380688eeebff6c5f7ed` |
| `backend/tests/test_w1d_contract.py` | 31949 | `92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623` |
| `backend/tests/test_w1d_postgres.py` | 266392 | `2b2c337101abaa437f9f7365f1a693b816d42092be79f32c7cca677e65da34b6` |
| `frontend/src/test/W1DContractTransition.test.tsx` | 17518 | `a70935c789332bfede8341a94b81194b8e32d4af176abda89674a023b7f058d7` |
| `frontend/e2e/w1d-contract-transition.spec.ts` | 17017 | `8b2d43cfc46e84a37a0e08f182b9ff569651662124c2a0c6f3780b311b7e6a05` |
| `scripts/test-w1d-postgres.ps1` | 83702 | `4f3e24cd60fd21599a2c070b397ffd545bf2059322937220d6de69399d1c4689` |

The frozen Joseph R6 input also matched: `review/reports/W1D_JOSEPH_DESIGN_AUDIT_R6_R17_266BEEA.md`, 18861 bytes, SHA-256 `3683621bf6e9b4593e55cd5f88b8800e76c4710508deb0deb11b91e4ca4b0748`.

The supplied office input seal after ENV-076 was verified as the 123331-byte
prefix with SHA-256
`7749b8d8e6213dbca1e43f8d2132c6b65dde0306c07c53a8b6f9aeef62ad4dd3` after
removing the single separator LF immediately before the later
`## OFFICE-W1D-ENV-077` append. The append-only office file continued to
contain ENV-077 through ENV-079 during this task, so its full-file hash is not
the supplied ENV-076 input seal.

## Re-audit of prior blockers and R20 corrections

### H01 — W1C nominal-success projections: closed for Phase-1 design

The embedded seed validators in `scripts/test-w1d-postgres.ps1:734-810`
require exact top-level keysets (identity 3, certification 7, grade 9), strict
non-bool integers, exact IDs/dates/strings/nulls, and `row_version == 1`.
The AST-extracted H01 helper probe selected seven seed functions and ran the
built-in mutant self-check successfully. The expanded direct in-memory probe
also rejected all 20 missing/extra/type/bool/value mutants. No expected
rejection was swallowed by an `Exception`/`BaseException` catch.

### M01 — raw `recipient_no`: closed for Phase-1 design

`backend/tests/test_w1d_postgres.py:637-646` checks `type(value) is str` and
the raw `^[0-9]{6,}$` value. The self-check rejects whitespace, integer, bool,
short, sign, decimal, empty, and other coercion cases. There is no `strip()`
or `str()` path. The wrapper's raw seed assertion at lines 1224-1233 agrees.

### H02 — exact contract API/DB identity: no regression found

The wrapper's `strict_api_contract_response` at
`scripts/test-w1d-postgres.ps1:1058-1110` retains the exact 14-field
`ContractResponse` contract, forbidden-field rejection, strict integer/date
handling, exact service/group values, and exact null fields. The W1D backend
test retains per-ID and DB projection checks. No H02 regression was found.

### H03 — SQLSTATE `08*` harness classification: no regression found

The wrapper still extracts `orig.sqlstate`/`pgcode` and classifies `08*` as a
harness/connectivity result before the product DBAPI subclasses at
`scripts/test-w1d-postgres.ps1:1448-1497`. No H03 regression was found. This
was inspected only; no database was started or exercised.

### H04 — structured winner, timestamp, range, row, and audit paths

The R18/R19 failures were independently confirmed from source: the old winner
self-check caught only `Exception`, timestamp logic was duplicated, UUID-like
strings crossed the internal boundary, and the audit mutant set did not cover
all exact `new_ids`/nested forms. R20 has the following real corrections:

- `_try_pack_structured_winner_result` at
  `backend/tests/test_w1d_postgres.py:1586-1621` requires positive strict
  integer IDs, a list of exactly one strict positive integer contract ID, and
  `type(corr) is UUID`. A UUID-looking string is rejected. The packed internal
  result has exactly five keys, with `status == "SUCCESS"`; the wire layer may
  serialize the UUID as a JSON string. The direct pack probe returned
  `PACK_UUID_OBJECT_PASS=True` and `PACK_UUID_STRING_REJECTED=True`.
- `_normalize_utc_timestamp` at lines 2144-2155 delegates to
  `_try_normalize_utc_timestamp`; the coupling probe returned
  `ACTUAL_NORMALIZER_USES_PURE=True`. The timestamp mutant self-check rejects
  naive/wrong-type values, equal/non-after old timestamps, and outside-window
  values. The inclusive window control passed (`TS_WINDOW_INCLUSIVE=True`),
  while equal strict-after was rejected.
- `_assert_open_ended_range_exact` at lines 953-965 rejects infinity,
  malformed upper bounds, and prefix-only ranges and requires the exact
  normalized `[new_start,)` range.
- `_full_ledger_state` at lines 714-801 captures full recipient, identity,
  certification, grade, contract, counter, and audit row projections. The
  winner assertion at lines 1264-1530 enforces complete old/new keysets,
  exact old `row_version + 1`, exact end/period/metadata deltas, all other old
  columns unchanged, complete new rows from sealed values, exact timestamps,
  one audit append, and unchanged recipient/identity/counter state. `pg_08`
  reaches that assertion at line 4430 after the concurrent winner/STALE race.
- `_r19_audit_proj_mutant_selfcheck` at lines 1875-2020 sends top-level,
  authorized-hash, missing/wrong/extra `new_ids`, nested key/value/container,
  and decode/type mutants through the same
  `_validate_exact_audit_projection` predicate used by the single-winner
  assertion. The JSON-domain mutant aggregate returned `PASS`.

The frontend E2E contract checks the correlation UUID on the JSON wire as a
string UUID. The E2E file remains static-only here; its numeric ID assertions
are weaker than the backend exact pack/projection checks and remain a residual
browser-checker risk, not evidence of a runtime pass.

## Confirmed approval blockers

### B1 — audit exactness predicate false-passes malformed non-JSON values

`backend/tests/test_w1d_postgres.py:1745-1747` compares actual and expected
projections using `json.dumps(..., default=str)`. The R20 mutants cover
malformed JSON-domain dict/list/string/int shapes, but the predicate itself is
not fail-closed for arbitrary in-memory values:

1. Replacing an expected nested date string with
   `datetime.date(2035, 1, 1)` returned `None` (accepted) because `default=str`
   renders it as the expected date text.
2. Replacing the `before` `contracts` list with an equivalent tuple returned
   `None` (accepted) because JSON encoding converts the tuple to a list before
   comparison.

The intentional detector command exited 2 after printing
`AUDIT_NON_JSON_DATE_RESULT=None` and `AUDIT_TUPLE_CONTAINER_RESULT=None`.
PostgreSQL JSONB normally returns JSON-domain primitives, so the direct
production reach is limited; nevertheless the sealed pure predicate is the
claimed exact structure/type/value gate and the assignment explicitly
requires malformed-data false-pass resistance. This is a confirmed design/RED
checker blocker, not a claim that a live product row was observed.

### B2 — plan/RED status and evidence wording is not exact

- The assignment packet requires `RED_VALID_PENDING_DESIGN_AUDIT` or `BLOCK`
  at `review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md:284,292`, while the final
  Phase-1 self-check in the sealed plan says
  `RED_VALID_PENDING_REAUDIT` at
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:990`. This is a stale status
  contradiction in the approval package.
- `review/evidence/w1d/RED.md:76` cites the historical office seal
  `78b388b4…8df8 / 119299`. The requested current input after ENV-076 is
  `7749b8d8…ad4dd3 / 123331` (verified above). If the historical seal is
  intentionally retained, RED must label it historical and also identify the
  current append-only prefix; otherwise it must be resealed.
- The plan's cleanup checkbox at
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:988` claims zero residuals,
  while RED explicitly says R20 is static-only/no live at lines 9 and 62.
  Root `node_modules` and the expected seed/test-result artifact paths were
  absent, but `backend/.pytest_cache` already existed and no live wrapper
  cleanup was run. The checkbox must be marked as a prior observer result or
  static-only limitation rather than current runtime evidence.

## Canonical target ledger and exclusions

I reconciled the plan's R17/R18 ledger against canonical docs 02/03/04. The
transition target is the recipient/identity/certification/grade/contract
state, counter, and one authorized audit append, with the exact old/new
projections and service multiset described in plan §2.8/R17. The canonical
scope explicitly excludes benefit, approval, guardian, payer, and assignment
rows from this transition. I did not reclassify those exclusions as defects.
The plan also preserves the required nullable signer snapshot and prohibited
`contract_no`/guardian/payer/birth/address structures.

## Product absence and static gates

Known product paths were absent: `backend/app/domains/w1d`,
`backend/app/api/w1d.py`, the `0011` migration, the W1D frontend service, and
the W1D recipient contract component all returned `False` from `Test-Path`.
The only product-tree `W1D` pattern hits were test files. No product revision,
API implementation, migration, or UI implementation was created.

| Command/check | Result |
|---|---|
| strict UTF-8 decode over seven files | 7/7; exit 0 |
| BOM and trailing horizontal whitespace | BOM 0; trailing-space lines 0; exit 0 |
| PowerShell AST parse of wrapper | 0 parser errors, 4916 tokens; exit 0 |
| Python AST/compile of two backend tests | both OK; raw bytes 31949 and 266392; exit 0 |
| embedded seed AST/compile | runtime source 46127 bytes; OK; exit 0 |
| Ruff, `--no-cache` | All checks passed; exit 0 |
| pytest collect-only, `-p no:cacheprovider` | 27 collected; exit 0 |
| Playwright `--list --workers=1` | 9 tests in 1 file; exit 0 |
| `git diff --check --` | exit 0 |
| direct pure aggregate/self-check probe | `PASS`; exit 0 |
| direct H01 AST-helper self-check | PASS; exit 0 |
| non-JSON audit false-pass detector | both malformed cases accepted; intentional detector exit 2 |

No live wrapper/DB/server/browser claim is made. The static Python/pytest
imports emitted the existing Starlette warning that `httpx` with
`starlette.testclient` is deprecated. A read-only process/listener observer
saw 15 existing `node`/`postgres` processes and 48 listeners, including the
existing PostgreSQL listener on port 5432; none was started, stopped, or
altered. No `seed_e2e.py`, root `node_modules`, `frontend/test-results`, or
`frontend/playwright-report` artifact was created by this audit. The existing
`backend/.pytest_cache` was not touched or removed.

## Observer problems and retries

Every observer issue was recorded and retried without editing the checkout:

1. The first default PowerShell read of Korean authority files rendered
   mojibake while exiting 0. All authority files were reread with explicit
   UTF-8 decoding; those reads are the basis of this report.
2. A Python AST command was first run from the repository root, where
   `\.venv\Scripts\python.exe` does not exist. The shell wrapper misleadingly
   returned 0 after the command-not-found; it was rerun from `backend` with
   the bundled runtime and passed.
3. The first seed extractor assumed `@'`; inspection showed the wrapper uses
   `@"`. One retry also had a Python regex quoting error (exit 1). The final
   `@"` extractor and runtime-source AST/compile passed.
4. An office-prefix PowerShell helper first hit an `empty pipe element`
   parser error (exit 1). The byte search/hash was rerun in memory and
   verified the supplied 123331-byte prefix.
5. A Windows glob read using `docs/02_*.md`-style paths failed (exit 1);
   the canonical files were reread using their exact Korean filenames.
6. One attempted temporary-file hash helper was not executed by the Desktop
   command wrapper; it was replaced with an in-memory hash observer. No temp
   file was created by that attempt.

## Narrow correction packet

Before Regina reseal/approval, the writer should make only these corrections
and rerun the static gates; Joseph made none of them:

1. Replace the plan's stale `RED_VALID_PENDING_REAUDIT` with the packet's
   required `RED_VALID_PENDING_DESIGN_AUDIT`, or explicitly explain and reseal
   the historical wording.
2. Reconcile RED's office reference with the supplied ENV-076 prefix seal,
   clearly distinguishing the historical pre-ENV-076 office snapshot from the
   append-only current log.
3. Mark cleanup as static-only/not-run unless a separately authorized live
   cleanup observation exists; do not make a static R20 package claim that
   live residuals were zero.
4. Make `_validate_exact_audit_projection` reject non-JSON Python types and
   container substitutions without `default=str` (or with an explicit
   recursive JSON-domain/type validator), add date/tuple/custom malformed
   mutants, and ensure those mutants still call the exact predicate used by
   `pg_08`.

No product implementation is authorized by this report. After the narrow
package correction and independent reseal, a new exact-byte design audit is
required; only a later separately authorized runtime campaign can establish
product GREEN.

JOSEPH_W1D_REAUDIT_R7_RESULT=REQUIRED_CHANGES
