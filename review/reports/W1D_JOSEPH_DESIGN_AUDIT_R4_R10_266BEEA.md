# Joseph W1D Phase 1 Design + Executable RED Audit R4/R10

Audit date: 2026-07-31 (Asia/Seoul)

Auditor: Joseph, independent from the Grok writer and Regina integrator.

## 1. Identity, scope, and state

Expected repository: `C:\sswcenter\2.1`

Observed repository root: `C:/sswcenter/2.1`

Expected and observed branch: `codex/w1d-contract-transition`

Expected and observed HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`

This was a read-only audit of the current shared tree. The only file written by
this audit is this report. No live PostgreSQL/FastAPI/Vite/Playwright wrapper was
started by Joseph. No product implementation, migration, generated client,
plan, RED file, test, wrapper, stage, commit, push, pull, fetch, rebase, merge,
stash, dependency install, or environment change was performed.

The current Phase 1 classification is product-absent by design: the 0011
migration and W1D product modules are absent. That absence is expected RED
classification, not a defect by itself. It does not substitute for the line
audit of the executable RED or for a future product-green run.

Entry state:

- `git diff --name-only`: 0 tracked paths.
- `git diff --cached --name-only`: 0 staged paths.
- `git status --porcelain=v2 --untracked-files=all`: 13 pre-existing untracked
  paths (the seven sealed files, packet, office log, and prior reports); no
  tracked or staged delta.
- Product-absent checks were true for
  `backend/app/domains/w1d`,
  `backend/alembic/versions/20260730_0011_w1d_recipient_contract.py`,
  `frontend/src/services/w1dApi.ts`, and
  `frontend/src/components/recipients/RecipientContractPanel.tsx`.
- Pre-existing cleanup checks were absent for `node_modules`,
  `frontend/test-results`, and `frontend/playwright-report`.
- R10 ports 55471, 18113, and 14213 had zero listeners at the audit check.

The complete required reading set was inspected: `README.md`,
`docs/00_정본_문서_목록.md`, current `docs/AI_업무분담_운영규정_v3.5.md`,
`review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md`, all seven sealed inputs,
`docs/02_업무규칙_계약_v1.1.md`, `docs/03_UI_API_상호작용_계약_v1.2.md`,
`docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` including sections 8 and 10,
`review/reports/W1D_JOSEPH_DESIGN_AUDIT_R3_R6_266BEEA.md`, and
`review/environment/office/2026-07-30_W1D.md` including AUDIT-009 through
AUDIT-012 and ENV-038 through ENV-045.

### Exact seven-file input seal

| # | Path | SHA-256 | Bytes | Observed mtime (KST) |
|---:|---|---|---:|---|
| 1 | `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md` | `a1792382a24b4bcfd01742b20044e5550e544735b0b033260ba2ca9616de4b5c` | 36645 | 2026-07-31T00:39:52.4927411+09:00 |
| 2 | `review/evidence/w1d/RED.md` | `87038d46da0198efb2b5e53513cf43f26ca074a8258bb974b831d514dbba2db4` | 6647 | 2026-07-31T00:45:10.6368668+09:00 |
| 3 | `backend/tests/test_w1d_contract.py` | `92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623` | 31949 | 2026-07-31T00:39:52.4717418+09:00 |
| 4 | `backend/tests/test_w1d_postgres.py` | `94fae3931daed4fe868bad1bf2c00c8bd39c950ca55986acc9c2f0c36cf25972` | 195270 | 2026-07-31T00:42:14.7009517+09:00 |
| 5 | `frontend/src/test/W1DContractTransition.test.tsx` | `e9c89b69dd7185ca5dc2dde252af7a5a44abcaa19054008d8aa7da593ff07e72` | 17080 | 2026-07-30T22:15:10.8174929+09:00 |
| 6 | `frontend/e2e/w1d-contract-transition.spec.ts` | `a8a781cc129429ddc64182d38cd344667919740c15a7521e9a4010b0e1b0ef24` | 11959 | 2026-07-30T23:27:24.0983256+09:00 |
| 7 | `scripts/test-w1d-postgres.ps1` | `257bc9cae27dcca1dc7b459b5a8f94077ecbda726c2a1c6237cc1a8f85559a57` | 45421 | 2026-07-31T00:22:41.7187454+09:00 |

All seven are untracked in this checkout, so the seven-file byte scanner was
the authoritative whitespace check; `git diff --check` alone would not inspect
them.

## 2. Commands, exits, counts, and warnings

The final corrected static pass used these exact invocations from the expected
root unless a `Push-Location` is stated:

| Gate | Command | Result |
|---|---|---|
| Strict bytes | PowerShell scanner over the exact seven paths using strict UTF-8 decoding and a `[ \t]+$` trailing-whitespace scan | `STRICT_UTF8_ERRORS=0 TRAILING_WS=0 FILES=7` |
| PowerShell AST | `[System.Management.Automation.Language.Parser]::ParseInput((Get-Content -Raw -LiteralPath 'scripts/test-w1d-postgres.ps1'), [ref]$tokens, [ref]$errors)` | `POWERSHELL_AST_ERRORS=0`, exit 0 |
| Python AST | From `backend`: `\.\.venv\Scripts\python.exe -B -c "import ast, pathlib; files=['tests/test_w1d_contract.py','tests/test_w1d_postgres.py']; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p) for p in files]; print('PYTHON_AST_FILES=' + str(len(files)))"` | `PYTHON_AST_FILES=2`, exit 0 |
| Ruff | `backend\.\.venv\Scripts\ruff.exe check --no-cache backend/tests/test_w1d_contract.py backend/tests/test_w1d_postgres.py` | `All checks passed!`, exit 0 |
| pytest collection | From `backend`: `\.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --collect-only tests/test_w1d_contract.py tests/test_w1d_postgres.py` | 26 collected, exit 0 |
| Playwright listing | From `frontend`: `\.\node_modules\.bin\playwright.cmd test e2e/w1d-contract-transition.spec.ts --list --workers=1` | 9 tests in 1 file across 3 projects, exit 0 |
| Tracked diff check | `git diff --check` | exit 0; untracked files covered by the strict scanner |

The pytest collection emitted one environment/dependency warning only:
`StarletteDeprecationWarning` from `fastapi.testclient` about using `httpx`
with `starlette.testclient` and installing `httpx2`. It did not change the
collection exit or create a product result.

Intermediate command problems were recorded and discarded as command-path
errors, not repository findings: an initial Python AST probe ran from the
repository root with `tests/...` paths and exited 1 with `FileNotFoundError`;
two subsequent probes used `venv` instead of the actual `.venv` directory and
exited 1 with `CommandNotFoundException`; a metadata probe also had a
PowerShell subexpression parse error and exited 1. The corrected commands above
were rerun and are the final gate evidence. None of these probes wrote files.

## 3. Independent R8/R9/R10 closure check

The final bytes contain the claimed R10 structural corrections:

- OpenAPI checks bind all six operations to exact success status, request model,
  response model, and every 401/403/404/409/422/500 error to
  `/RecipientErrorEnvelope` in `backend/tests/test_w1d_contract.py:373-613`;
  the plan repeats the exact binding in
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:622-643`.
- The complete preview field set, requiredness, canonical hash, and
  `w1d-transition-v1` serialization version are checked in
  `backend/tests/test_w1d_contract.py:334-370`. Runtime capture is explicitly
  `canonical_hash` only in `backend/tests/test_w1d_postgres.py:611-658` and
  `:1542-1561`; there is no `preview_hash` attribute fallback.
- The canonical input and token binding rules, including exclusion of signer
  and end-reason display text from the hash and exact full-field HMAC binding,
  are explicit in `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:229-276`.
- The fail-closed full-row ledger helper covers recipient, W1C identity,
  certification, grade, contract, all counter rows, and all audit rows in
  `backend/tests/test_w1d_postgres.py:448-568`. The entire audit row-set and
  exact append-only prefix are checked at `:1905-1955`, with exact persisted
  projection checks continuing through `:2050`.
- The DB-clock timestamp normalizer and inclusive apply window are checked at
  `backend/tests/test_w1d_postgres.py:621-640` and `:1956-1971`.
- Null identity and validation precedence are represented at
  `backend/tests/test_w1d_postgres.py:4326-4393` and in the plan at
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:194-210`.
- The exact reverse-period field error is asserted at
  `backend/tests/test_w1d_postgres.py:4596-4620`.
- Raw cross-group/same-group dual lock orchestration, exact `23P01`, exact
  `trg_recipient_contract_group_period_overlap`, and residual-session checks
  are present at `backend/tests/test_w1d_postgres.py:3309-3695`.
- pg_08 has two distinct lock waiters, winner/STALE classification, winner IDs,
  correlation, final rows, and teardown at `backend/tests/test_w1d_postgres.py:2549-2885`.
- Mutation ACL/CSRF/error precedence is covered at
  `backend/tests/test_w1d_postgres.py:4623-4778`; read ACL coverage is a new
  finding below.
- Playwright project viewports are defined at
  `frontend/playwright.config.ts:30-50`; winner response status, IDs, and GET
  readback are specified in
  `frontend/e2e/w1d-contract-transition.spec.ts:199-260`. The fixture defect
  prevents this from being a complete executable-green closure.
- The wrapper has bounded child-process tree handling at
  `scripts/test-w1d-postgres.ps1:186-236`, hard cleanup failure handling at
  `:871-947`, and emits GREEN only after all residual gates at `:1135-1168`.

## 4. Re-audit of all 15 R3 findings

`CLOSED` means the original R3 defect was corrected in the current bytes. It
does not mean product runtime was exercised while 0011 is absent. `PARTIAL`
means the original correction exists but the required executable evidence is
still incomplete.

| R3 finding | Status | Current evidence and conclusion |
|---|---|---|
| J-W1D-R3-B01: pg_08 lock monitor used undefined `time` | CLOSED | `time` is imported at `backend/tests/test_w1d_postgres.py:16`; the dual-wait monitor and finally teardown are implemented at `:2549-2808`, including two distinct application names and zero residual sessions. |
| J-W1D-R3-B02: wrapper could report GREEN before cleanup / soften cleanup failures | CLOSED | Timed tree cleanup is at `scripts/test-w1d-postgres.ps1:186-236`; cleanup exceptions set a hard harness failure at `:876-947`; GREEN is gated after listener/process/temp/artifact checks at `:1135-1168`. R10 log cleanup was zero. |
| J-W1D-R3-H01: raw cross-group concurrency did not prove actual overlap / accepted broad errors | CLOSED | Workers begin together, wait on the same blocker, monitor two lock waiters, and require one exact `23P01` plus exact constraint for cross-group; same-group requires two successes at `backend/tests/test_w1d_postgres.py:3309-3695`. |
| J-W1D-R3-H02: ledger fingerprint incomplete / no per-case write-zero | PARTIAL | The full fail-closed helper and all-row audit snapshot now exist at `backend/tests/test_w1d_postgres.py:448-608`, and mismatch/fault cases compare them. The unconfirmed apply at `:1566-1585` and grade-stale apply at `:1675-1707` still do not capture and compare a full before/after fingerprint. See new H01. |
| J-W1D-R3-H03: aggregate audit exactness was partial | CLOSED | The entire audit row-set is captured before and after, prefix equality and exactly one aggregate event are asserted at `backend/tests/test_w1d_postgres.py:1905-1955`; projections and persisted row equality are asserted through `:2050`. |
| J-W1D-R3-H04: transition/end ACL and CSRF were absent | CLOSED for the original mutation scope | All four mutations have unauthenticated 401, no-permission/VIEW 403, admin-without-CSRF 403, standard envelopes, and write-zero checks at `backend/tests/test_w1d_postgres.py:4623-4778`. Read list/get ACL is a separate new H02 gap. |
| J-W1D-R3-H05: wrapper lacked child timeout / process-tree control | CLOSED | `Invoke-W1dTimedCommand` has bounded waits, full descendant-tree handling, timeout markers, and verification at `scripts/test-w1d-postgres.ps1:186-236`. |
| J-W1D-R3-H06: canonical hash definition conflicted with the plan | CLOSED | The canonical input, version, sensitive-field exclusion, token binding, and runtime `canonical_hash` capture are consistent across `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:229-276`, `backend/tests/test_w1d_contract.py:334-370`, and `backend/tests/test_w1d_postgres.py:611-658`. |
| J-W1D-R3-M01: OpenAPI status/ref checks were loose | CLOSED | Exact operation/status/request/ref checks and all standard error refs are enforced at `backend/tests/test_w1d_contract.py:450-613`; the final contract test is byte-sealed. |
| J-W1D-R3-M02: list/get/end runtime contract was absent | CLOSED for the original field/behavior scope | `pg_12` covers list, GET, end, exact response-to-row projection, missing targets, stale end, Unicode end reason, and write-zero at `backend/tests/test_w1d_postgres.py:4120-4323`. Runtime is intentionally product-absent in R10; read authorization coverage is separately incomplete. |
| J-W1D-R3-M03: E2E lacked viewport and winner readback precision | PARTIAL | The three exact Playwright projects and 9-test listing are present; the spec asserts 200, UUID, new IDs, winner contract IDs, and GET readback at `frontend/e2e/w1d-contract-transition.spec.ts:199-260`. The transition fixture does not seed the W1C identity/period data needed to reach this path. See new H03. |
| J-W1D-R3-M04: null identity behavior was inconsistent and unsealed | CLOSED | The plan places identity existence before token HMAC, and `pg_13` requires exact 404 `CERTIFICATION_IDENTITY_NOT_FOUND` even for garbage token plus full write-zero at `backend/tests/test_w1d_postgres.py:4326-4393`. |
| J-W1D-R3-M05: free-text, Unicode, and exact error behavior were incomplete | CLOSED | Null/omitted/empty preservation, Unicode signer/end reason persistence, and exact reverse-period `field_errors` are checked at `backend/tests/test_w1d_postgres.py:4400-4620`. |
| J-W1D-R3-M06: signer relationship snapshot was not independently proven | CLOSED | Empty, partial, and full signer triples are persisted as snapshots after guardian/payer mutation at `backend/tests/test_w1d_postgres.py:1246-1425`; forbidden FK/UI surfaces are also sealed in the contract and Vitest files. |
| J-W1D-R3-L01: RED command/evidence/marker contract was inconsistent | CLOSED | Current `review/evidence/w1d/RED.md:61-172` records exact static commands, counts, product-absent markers, wrapper exit, E2E baseline, cleanup, and Git residual state. Joseph independently reran the static commands and confirmed the seven-byte scanner. |

## 5. New findings

### HIGH: J-W1D-R4-H01 — per-case full write-zero is still missing for unconfirmed and grade-stale apply

Evidence:

- `backend/tests/test_w1d_postgres.py:1566-1585` invokes unconfirmed apply,
  rolls back the SQLAlchemy session, and checks only the error code. There is no
  full ledger fingerprint immediately before and after the rejected call.
- `backend/tests/test_w1d_postgres.py:1675-1707` mutates the grade to create a
  stale case, invokes apply, rolls back, and checks only
  `CERTIFICATION_TRANSITION_STALE`; it likewise has no full before/after
  fingerprint.
- The plan requires each failed precedence/stale path to have write zero at
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:194-210` and the audit contract
  requires failed transition paths not to append or mutate rows at
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:549-569`.

False-pass mechanism: a future service could mutate a counter, W1C row, audit
row, or unrelated cluster row before raising the expected confirmation or
stale error. These cases would still pass because they inspect only the error
code and session rollback, not the full database ledger. The existing helper is
adequate; its required use is incomplete.

Required correction: capture `_full_ledger_fingerprint` and the full audit row
set immediately before each unconfirmed and grade-stale apply, compare after
the failure, and fail closed on any difference. Apply the same assertion to
every stale dimension required by the plan, including certification, grade,
contract-period, and service-multiset drift.

### HIGH: J-W1D-R4-H02 — list/get read ACL is not tested for unauthenticated, no-permission, or VIEW accounts

Evidence:

- The plan requires `RECIPIENT_VIEW` or ADMIN for both list and GET at
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:57-69`.
- `test_w1d_pg_12_list_get_end_contract_api` logs in only as the seeded admin
  and exercises read operations at `backend/tests/test_w1d_postgres.py:4120-4197`.
- `test_w1d_pg_14_transition_acl_csrf_all_mutations` covers only POST create,
  POST end, POST preview, and POST apply at
  `backend/tests/test_w1d_postgres.py:4623-4778`; it contains no GET list or
  GET item request for unauthenticated, no-permission, or VIEW accounts.

False-pass mechanism: a router or dependency could accidentally expose the
contract collection or item to unauthenticated/no-permission users, or deny a
legitimate VIEW user, while all current ACL tests remain green because they
exercise mutation routes only.

Required correction: add collection and item GET cases for unauthenticated
401, no-permission 403, VIEW success, and missing recipient/item behavior;
assert the standard envelope, exact permission code, and full write-zero on
denied reads. Keep the existing admin field/row equality checks.

### HIGH: J-W1D-R4-H03 — E2E transition-stale fixture never seeds W1C identity, periods, or active contracts

Evidence:

- The wrapper seed names `transition-stale` at
  `scripts/test-w1d-postgres.ps1:504-522`, but the API seed at `:611-641`
  creates recipients only.
- The only subsequent seed work at `scripts/test-w1d-postgres.ps1:643-722`
  inserts ended contracts for the `ended-new-only` recipients. It does not
  seed certification identity, certification period, grade period, or active
  transition contracts for `transition-stale`.
- The current recipient create service creates only the recipient row and
  recipient audit at `backend/app/domains/recipient/service.py:297-339`.
  W1C identity and period creation are separate routes at
  `backend/app/api/w1c.py:52-177`.
- The E2E scenario requires the transition panel and a non-empty impact preview
  at `frontend/e2e/w1d-contract-transition.spec.ts:130-182`. Under the sealed
  null-identity contract, the same recipient has no identity and preview must
  return `CERTIFICATION_IDENTITY_NOT_FOUND`, not an impact list; that precedence
  is explicit in `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:205-210` and
  `backend/tests/test_w1d_postgres.py:4326-4393`.

False-pass mechanism: while product is absent, the wrapper stops at the
0011-vs-0010 product RED gate and the 9-test listing/baseline marker does not
  exercise scenario B. Once product exists, the scenario will fail before the
  dual-page winner/STALE race, so it cannot certify the required behavior.

Required correction: seed each transition-stale recipient with a W1C identity,
one valid certification period, one grade period, and the active LTC contract
multiset needed by the preview, then emit and verify a deterministic setup
marker before Playwright starts. Keep the ended-only fixture separate and
verify the seeded IDs/row counts for each viewport-specific recipient.

## 6. R10 live evidence relevance and cleanup

The only R10 candidate log inspected was:

`C:\Users\USER\.grok\sessions\C%3A%5Csswcenter%5C2.1\019fb28c-7c3a-7153-8d29-fce6329a4365\terminal\call-21509e06-0625-4e90-b183-8a6c97d39c76-156.log`

Its external metadata is 9043 bytes, mtime
`2026-07-31T00:44:35.3787218+09:00`, SHA-256
`7b2153651e24802299c7cf335c30a447028822e7395f4dd910b0f7858aaae644`.
All six non-self inputs used by R10 had mtimes before the log (`0` inputs
after log mtime), and their current hashes match the final RED/office seals:
plan, contract test, PostgreSQL test, Vitest, E2E, and wrapper.

The log records:

- `WRAPPER_EXIT=1`.
- `W1D_STAGE_HARNESS_EXIT=0` and
  `W1D_HARNESS_W1C_HEAD_SELF_CHECK_OK`.
- Observed `20260730_0010_w1c_certification_ledgers`; expected
  `20260730_0011_w1d_recipient_contract`.
- pg00 exit 1 plus `W1D_STAGE_PG00_PRODUCT_RED`.
- Remaining PostgreSQL stage exit 1 plus `W1D_STAGE_PRODUCT_REST_RED`.
- E2E exit 1, `W1D_E2E_BASELINE_MARKER_COUNT=9`, and
  `W1D_STAGE_E2E_PRODUCT_RED`.
- Cleanup: `W1D_CLEANUP_LISTENERS pg=0 backend=0 frontend=0`,
  `W1D_CLEANUP_PROCESSES pg=0 backend=0 frontend=0`, and
  `W1D_CLEANUP listener=0 process=0 temp=0 artifact=0 artifact_removed=1`.

This is relevant and valid evidence for the product-absent Phase 1 RED
classification and for wrapper teardown. It is not product-GREEN evidence and
does not exercise the W1D product body. The migration 0011 absence is expected
in this phase and is not counted as a defect.

## 7. Confirmed defects versus residual implementation risk

Confirmed defects requiring correction are exactly the three HIGH findings in
section 5. They are executable RED/design coverage defects, independent of the
expected absence of product implementation.

Residual implementation risk, not a confirmed current defect:

- No W1D product implementation or 0011 migration exists, so service-level
  token, lock, transaction, audit, and UI behavior remain unexecuted in this
  audit. A future product run must be isolated and must not be inferred from
  static collection or the product-absent R10 log.
- The one pytest collection deprecation warning is environment/dependency
  hygiene, not a W1D contract failure.
- After H01-H03 are corrected, the full wrapper must be rerun and independently
  inspected for product/harness classification, exact winner/STALE behavior,
  all write-zero cases, read ACL, and final cleanup before any GREEN/PASS claim.

## 8. Final verdict

The exact seven-byte seal, static gates, R10 product-absent classification, and
most R3/R8/R9/R10 structural corrections are verified. Approval is withheld
because the executable RED still has three confirmed HIGH coverage/design
defects: two missing full write-zero assertions, missing read ACL tests, and an
unseeded transition E2E fixture.

JOSEPH_W1D_REAUDIT_R4_RESULT=REQUIRED_CHANGES
