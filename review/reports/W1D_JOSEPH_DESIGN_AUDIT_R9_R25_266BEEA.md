# W1D Phase-1 design and executable-RED audit R9

## Verdict

**APPROVE for Regina Phase-2 scope reseal.** The exact R25 design/executable-RED package is internally consistent for its declared Phase-1 static-only boundary. The two R8 closure defects are closed on the active collected paths, the earlier H01/H03/H04/M01 and HTTP/E2E obligations remain fail-closed, all required static gates reproduced, and no W1D product implementation is present.

This is not a product GREEN, live PostgreSQL, wrapper, browser, cleanup, or Phase-2 implementation approval. The package remains `RED_VALID_PENDING_DESIGN_AUDIT` until the next governance decision. No R25 correction packet is required for this audit. One inherited preview-only browser coercion is recorded as pre-GREEN hardening below.

## Identity and exact review boundary

Fresh independent review target: `C:\sswcenter\2.1`.

| Item | Observed value |
|---|---|
| cwd | `C:\sswcenter\2.1` |
| branch | `codex/w1d-contract-transition` |
| HEAD | `266beeaa2d150371ccd1a0f26f69249eca86ba16` |
| pre-write staged | `0` |
| pre-write tracked dirty | `0` |
| pre-write untracked | `18` |
| authorized report before review | absent |
| expected after report write | tracked/staged `0/0`, untracked `19` |

Read-only boundary was followed for the repository. The only authorized write was the new report at this path, written once after review completion. No prior report, office log, plan, RED, test, wrapper, product, configuration, dependency, cache, environment file, or generated artifact was edited. No Git mutation, live DB connection, wrapper/live/product test, browser launch, process/listener start or stop, or cleanup action was performed. No reviewer was delegated.

## Exact input seals

All hashes and byte lengths below were independently recomputed immediately before the report write. SHA-256 values are lowercase.

### R25 seven-file candidate

| Path | SHA-256 | bytes |
|---|---|---:|
| `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md` | `155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1` | 56890 |
| `review/evidence/w1d/RED.md` | `842049a4a2afce3cbd7cdbe90e8958add946a921e429596a4498bf626d8aefb2` | 5242 |
| `backend/tests/test_w1d_contract.py` | `92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623` | 31949 |
| `backend/tests/test_w1d_postgres.py` | `b74b68c3c52dd57a66350d4a36583ee1891fc685b59c26c699838c7effa9c644` | 304628 |
| `frontend/src/test/W1DContractTransition.test.tsx` | `a70935c789332bfede8341a94b81194b8e32d4af176abda89674a023b7f058d7` | 17518 |
| `frontend/e2e/w1d-contract-transition.spec.ts` | `24e83e1cbd65ca42deb0e6ec7b66297585098564076d2a8b6be52adb18a5971a` | 17341 |
| `scripts/test-w1d-postgres.ps1` | `0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155` | 83648 |

### Office and prior Joseph R8 seals

| Path | SHA-256 | bytes |
|---|---|---:|
| `review/environment/office/2026-07-30_W1D.md` | `3262bff466c86d4547145f799a60c4decc8a96ce1bc7ef5ecd3453f1ba67277a` | 156089 |
| `review/reports/W1D_JOSEPH_DESIGN_AUDIT_R8_R23_266BEEA.md` | `00cc14adf70de614ff779548a1c5269607e1783925fa9da678ac66823f416967` | 17658 |

The immutable R8 report remains `JOSEPH_W1D_REAUDIT_R8_RESULT=REQUIRED_CHANGES`. RED retains both historical R7 identities: first version `f4db172fc6207184596a24293495fb451edf058c628b2f2e9d7613e04f8e3a0e` / 24839 bytes (`HTTP P1`), and current R7 path `6615282b4e36a4b72c111b63fdfb85afae5c423126ad897ba673211ecc0acdce` / 15229 bytes (`audit non-JSON + B2`). The first historical R7 path is not present in the checkout, so its retained identity was not rehashed as a current input; the current R7 report path was independently sealed through the retained RED/office history.

## Canonical reconciliation

The canonical-document index at `docs/00_정본_문서_목록.md:1-71` keeps review files as evidence rather than product authority. The W1D package aligns with the canonical contracts as follows:

- `docs/02_업무규칙_계약_v1.1.md:299-327` requires the existing certification end, existing LTC contracts end, then new certification/grade and per-service contracts, with preview, affected-row/multiset confirmation, proposed end equal to new start minus one day, locks, stale `409`, mismatch `422`, and zero writes on rejection. The contract rules at `:332-353` retain same-service non-overlap, cross-service same-group allowance, cross-group non-overlap, required start date, nullable optionals, no `contract_no`, and no reactivation.
- `docs/03_UI_API_상호작용_계약_v1.2.md:328-340` requires preview-before-apply, mismatch `422`, stale `409` with preview confirmation cleared, and no partial state. The frozen Vitest/E2E package expresses the UI gates while the live behavior remains deliberately unrun.
- `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md:60-86,548-617,661-696` defines bigint identity, date/timestamptz UTC, inclusive business periods represented as half-open ranges, positive row versions, invalidation/replacement semantics, the recipient-contract columns and forbidden fields, the canonical transition input set, exact hash comparison, lock/recompute/apply sequence, one audit append, and rollback on stale/mismatch/failure.
- The plan’s transition ledger is recipient, identity, certification, grade, contracts, counter, and one authorized audit append. Benefit, approval, guardian, payer, and assignment rows remain explicitly outside this transition target; excluding them is not a defect.
- The plan’s document banner `PHASE1_DESIGN_RED_DRAFT` is a document-status label, while its R24/R25 sections (`review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:964-990`) and RED status (`review/evidence/w1d/RED.md:1-20`) consistently identify the package as `RED_VALID_PENDING_DESIGN_AUDIT`, static-only, not approved, and not product GREEN.

## Findings by priority

### P0/P1/P2 closure findings

None. No closure-blocking defect was found in the exact R25 package.

### OBS-01 — preview-only browser coercion remains before any GREEN campaign

`frontend/e2e/w1d-contract-transition.spec.ts:258-317` still uses `Number()` for preview affected IDs and `String()` for preview service values. The mandatory apply/readback path at `:328-366` is independently strict: exact positive integer checks, canonical lowercase UUID syntax, exact two-item new-contract list, and `GET` readback `getBody.id === cid` without coercion. This is the same inherited hardening note preserved by R8; it is outside the claimed R25 E2E apply-ID strictness obligation and does not block Phase-1 design/RED reseal. Harden it before browser GREEN.

### OBS-02 — ancillary setup conversions are not H02 matcher defects

Several collected PostgreSQL tests use `int(created.json()["id"])` for later mutation/setup plumbing, including `backend/tests/test_w1d_postgres.py:6466,6502,6538,6616-6617,6931`. Those conversions occur before the exact H02 row comparison or only to build a subsequent URL/query. They are not used to normalize an API body before equality. The claimed H02 paths at `:6221-6327` and `:7065-7136` pass the strict gate first, and the direct mutant probe proves string IDs and date objects fail. This distinction was checked explicitly and is not a closure defect.

### Residual environment observation

Existing ignored state was observed but not changed: root `.pytest_cache` and `.ruff_cache`, `backend/.pytest_cache` and `.ruff_cache`, and `frontend/node_modules` were present; `frontend/test-results`, `frontend/playwright-report`, root `node_modules`, `frontend/.vite`, and `frontend/.cache` were absent. No current runtime-zero or cleanup claim is made.

## R8 defect re-audit

### pg_05 exact audit and JSON-domain path

The active nominal `test_w1d_pg_05_transition_preview_apply_stale_multiset_fault_audit` now checks the complete audit append at `backend/tests/test_w1d_postgres.py:3849-3995`:

- `:3849-3861` obtains the entire audit row set, requires exactly one append, and compares the complete pre-existing prefix.
- `:3862-3919` checks the action, entity, recipient binding, one apply delta, actor/reason/source fields, canonical request ID, and inclusive apply timestamp window.
- `:3920-3946` builds the expected after projection from the authorized preview hash and sends both before and after values through the shared `_validate_exact_audit_projection` predicate.
- `:3947-3979` decodes `after_json`, requires exactly `certification_period_id`, `grade_period_id`, and `contract_ids`, requires exact integer ID types, exact response values, list type, positive integer members, and exact response order. There is no `int()` conversion of `new_ids` and no `json.dumps(..., default=str)` projection comparison.
- `:3980-3995` rejects the forbidden `invalidated_at_utc` projection key.

The shared predicate is the one at `:1727-1818`: recursive JSON-domain validation accepts only exact `None`, bool, str, int, finite float, list, and string-keyed dict values; it rejects date, datetime, UUID, custom objects, tuple, set, non-string keys, NaN, positive infinity, negative infinity, and nested non-JSON values. Equality is exact type/structure/value equality at `:1751-1768`. The authorized hash, before-without-`new_ids`, after-with-`new_ids`, and required nested lists are checked at `:1771-1818`.

The exact active-path source self-check at `:6162-6176` requires the shared predicate and rejects source regressions containing `default=str`, `int(new_ids)`, list-member int coercion, or projection dumps. The aggregate at `:2511-2523`, invoked by the collected pure gate at `:4767`, includes the audit mutants as well as the winner, timestamp, open-range, pack, request-ID, HTTP, recipient-number, and H02 mutants.

The direct no-DB probe rejected all 13 focused audit mutations: date, datetime, UUID, custom object, tuple, set, non-string key, NaN, `+inf`, `-inf`, string certification ID, string grade ID, and string contract ID. No DB connection and no `TestClient` construction occurred in that probe.

### ContractResponse H02 active call-site trace

The exact 14-field set is frozen at `backend/tests/test_w1d_postgres.py:5906-5920`; forbidden legacy or non-contract fields are listed at `:5922-5931`. `_validate_contract_response_strict` at `:5944-5992` gates the complete keyset before any row comparison, rejects forbidden keys, uses exact non-bool positive integer types for IDs/replacement/row version, exact string/null rules for service fields and text, and exact `YYYY-MM-DD` string rules for dates. It does not coerce API-side string IDs or date/datetime objects.

The matcher at `:6078-6093` calls `_assert_contract_response_shape` first, then calls `_normalize_db_contract_row_for_api` at `:6001-6075` only on DB-driver values, and finally performs exact field equality. There is no API-side `int()`, date conversion, `str()` slicing, or default-string serialization in the matcher.

All active collected matcher paths were traced:

| Active path | Strict gate and row binding |
|---|---|
| `pg_12` create/get/list/end | shape gates at `:6221,6238,6248,6254,6291`; DB row equality at `:6276,6327` |
| `pg_15` VIEW list/item | each item shape gate and DB-only expected normalization at `:7065-7073`; list and item row equality at `:7100,7136`; item GET shape at `:7108` |
| wrapper embedded seed | exact API gate at `scripts/test-w1d-postgres.ps1:1043-1110`, DB-only normalizer at `:1112-1169`, exact per-ID comparison at `:1395-1421` |

The pure R24 H02 self-check at `:6096-6160` accepts the valid 14-key body, rejects string IDs, string recipient IDs, date/datetime objects, bool IDs/row versions, zero/negative IDs, extra/missing/forbidden keys, and verifies DB-driver date normalization separately. The focused no-DB result was `H02_VALID=PASS` and `H02_MUTANTS_REJECTED=5/5` for string ID, date object, datetime object, bool ID, and extra-key attacks. This closes the R8 active matcher defect.

## Earlier closure matrix

| Obligation | Static result and evidence |
|---|---|
| H01 W1C exact 2xx | PASS. Wrapper validators at `scripts/test-w1d-postgres.ps1:704-810` require exact identity/cert/grade keysets, strict values/types/nulls, and row version 1; `:812-911` exercises missing/extra/wrong-type/bool/value mutants; malformed 2xx routing is at `:942-1041`. |
| H03 SQLSTATE `08*` | PASS. Wrapper `:1445-1495` extracts `orig.sqlstate`/`pgcode`, classifies `OperationalError` and SQLSTATE `08*` as harness before ProgrammingError/DataError/IntegrityError product branches, and emits class-only markers. |
| H04 concurrency winner/STALE | PASS as executable RED design. `pg_08` uses a dual blocker/wait arrangement, requires one success and one exact `CERTIFICATION_TRANSITION_STALE`, and then runs the full projection; no live race was run. |
| H04 full ledger | PASS. `_assert_single_winner_ledger_projection` at `backend/tests/test_w1d_postgres.py:1264-1531` checks unchanged recipient/identity/counter, complete old/new keysets, exact old row versions/end/ranges/metadata, complete new rows, exact audit prefix and one append, and zero loser mutation. |
| H04 timestamp/range/clock | PASS. Sealed timestamp equality/window and strict-before relations are checked at `:1449-1455` and helper predicates `:1635-1711`; open range validation and its mutants are included in the aggregate. DB timestamp normalization delegates to the pure normalizer at `:2536-2547`. |
| M01 raw `recipient_no` | PASS. `backend/tests/test_w1d_postgres.py:637-681` and wrapper `scripts/test-w1d-postgres.ps1:1224-1235` require raw `str` plus `^[0-9]{6,}$`, preserve the issued value, and reject whitespace/int/bool/short/sign/decimal mutations. |
| Token/fault/clock | PASS as RED coverage. Token tamper, injectable expiry, cross-recipient replay, null, and empty preview-token cases are isolated with full write-zero fingerprints in `backend/tests/test_w1d_postgres.py:4222-4401`; pg_10 has all ten fault labels with rollback/audit-zero checks at `:5572-5708`. |
| Canonical projection/date semantics | PASS. `_canonical_transition_projection` uses ordered DB-derived certification/grade/contract projections and service multiset at the canonical projection helpers; DB-driver date/timestamp normalization is separate from API validation. The plan and canonical DB document agree on inclusive business periods represented as half-open ranges. |
| Canonical request ID | PASS. `_canonical_audit_request_id` at `backend/tests/test_w1d_postgres.py:2251-2261` accepts only a UUID object rendered canonically or an already-canonical lowercase UUID string; uppercase, malformed, integer, and other forms are rejected by the pure mutants. |
| HTTP apply correlation and full ID binding | PASS as executable RED design. `pg_16` at `backend/tests/test_w1d_postgres.py:7181-7523` binds the exact response IDs, recipient ID/number, canonical correlation, same-apply audit request ID, exact before/after new-ID map, row properties, and cardinality. |
| E2E apply-ID strictness | PASS. `frontend/e2e/w1d-contract-transition.spec.ts:328-366` requires positive integers, two unique contract IDs, canonical lowercase UUID, positive recipient ID, and exact GET ID equality without coercion. The preview-only note is OBS-01. |
| No unauthorized product implementation | PASS. Named W1D migration/domain/API/UI/generated paths are absent and no semantic W1D product references were found outside the RED/test/evidence package. `PRODUCT_NAMED_PRESENT_COUNT=0`; tracked product count is `0`. |

## Plan, RED, history, and scope truthfulness

The plan R24/R25 sections at `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:964-990` accurately record the R8 semantic closures, the R25 correction limited to the pg_10 import order, the required order (`w1d` fault import, blank line, then W1C imports), the frozen paths, and the static-only/non-GREEN status. The Phase-1 self-check at `:1038-1049` keeps product implementation absent and records the R25 correction.

`review/evidence/w1d/RED.md:1-20,33-120` truthfully retains the R24 I001 retraction, R7 dual-version identities, R8/R24 history, exact R25 allowlist, static-only/no-cleanup wording, no current runtime-zero claim, seed extraction facts, and the final static evidence. The office R25 readiness entry records exactly three changed allowlisted paths, the seven current seals, the reproduced static counts, and the prohibition on live/Phase-2/product/Git action before this review.

The embedded seed in `scripts/test-w1d-postgres.ps1` was extracted without rewriting bytes. The wrapper is BOM-free UTF-8 with LF newlines; opener is line `505`, first embedded Python line `506`, terminator is line `1606`, and the seed is `46073` bytes / `46055` characters / `1100` content lines, ending with a newline. These facts match RED and office evidence.

The frozen contract test and Vitest were not edited or regenerated. The generated OpenAPI/product paths remain absent. R25’s exact delta is the required `pg_10` import order only; no product implementation or unrelated package change is present.

## Static commands and evidence

All commands below were read-only and run in the stated checkout. Collection/listing is not product execution.

| cwd | Command/check | Result |
|---|---|---|
| `C:\sswcenter\2.1` | identity/status, `git branch --show-current`, `git rev-parse HEAD`, cached/working/untracked name queries | branch and HEAD exact; staged `0`, tracked dirty `0`, untracked `18`; exit `0` on final corrected observer |
| `C:\sswcenter\2.1` | SHA-256/byte observer for office, seven candidate paths, and R8 report | all values equal the input-seal tables; exit `0` |
| `C:\sswcenter\2.1` | strict UTF-8 decode, BOM scan, trailing-horizontal-whitespace scan over the seven candidate inputs using bundled Python `-B` | `UTF8_ERRORS=0`, `BOM_COUNT=0`, `TRAILING_WS_COUNT=0`; exit `0` |
| `C:\sswcenter\2.1` | PowerShell `Parser.ParseFile` over `scripts/test-w1d-postgres.ps1` | `PS_AST_ERRORS=0`, `TOKENS=4916`; exit `0` |
| `C:\sswcenter\2.1` | Python `ast.parse` + `compile` for both Python test files and extracted embedded seed | both tests OK; seed `opener=505 first=506 terminator=1606 content_lines=1100 chars=46055 bytes=46073`; exit `0` |
| `C:\sswcenter\2.1` | direct pure import/self-check probe with bundled `backend\.venv\Scripts\python.exe -B -` | `DIRECT_PURE_AGGREGATE=PASS`, `DB_CONNECTION_CALLED=NO`, `TESTCLIENT_CALLED=NO`, audit attacks `13/13` rejected, H02 valid/mutant checks pass; exit `0` |
| `C:\sswcenter\2.1\backend` | `\.venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml tests/test_w1d_contract.py tests/test_w1d_postgres.py` | `All checks passed!`; exit `0` |
| `C:\sswcenter\2.1\backend` | `\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --collect-only tests/test_w1d_contract.py tests/test_w1d_postgres.py` | `28 tests collected`; exit `0`; one non-fatal existing Starlette TestClient deprecation warning |
| `C:\sswcenter\2.1\frontend` | `\.\node_modules\.bin\playwright.cmd test e2e/w1d-contract-transition.spec.ts --list --workers=1` | `Total: 9 tests in 1 file`; exit `0`; list only, no browser launch |
| `C:\sswcenter\2.1` | `git diff --check --` | exit `0` |
| `C:\sswcenter\2.1` | named product-path `Test-Path` and tracked-file absence checks | `PRODUCT_NAMED_PRESENT_COUNT=0`, tracked product count `0`; exit `0` |

No live PostgreSQL, wrapper, application, Playwright browser, process, listener, or cleanup command was run by this audit. Therefore no live GREEN or current runtime-zero conclusion is inferred from the static results.

## Observer issues and retries

Every failed or misleading observer was recorded here; none changed repository bytes or external state.

| Observer issue | Retry/result |
|---|---|
| Initial status summarizer classified all `??` entries as staged and printed staged `18`. | Replaced the classification with independent `git diff --cached --name-only`, `git diff --name-only`, and `git ls-files --others --exclude-standard`; final state is staged `0`, tracked dirty `0`, untracked `18`. |
| A corrected status command had a PowerShell parser error from a missing closing parenthesis in the `diff_check_exit` output expression. | Reran the read-only status/diff observer without the malformed expression; exit `0`. |
| First seed extraction used the automatic `$matches` variable and failed with a null-valued expression. | Retried with a different variable; the next substring calculation failed with a negative length. A third raw-byte/string extraction succeeded with exact opener/terminator, bytes, characters, lines, and newline facts. |
| A combined nested PowerShell/Python AST observer exited without emitting the expected PowerShell AST line. | Reran PowerShell AST directly; `PS_AST_ERRORS=0 TOKENS=4916`, exit `0`. Python/seed AST was independently run and passed. |
| First pure probe was launched from `C:\sswcenter\2.1\backend` while resolving `backend/.venv/Scripts/python.exe`, so the path was not found. | Reran from repository root with the correct bundled interpreter path; pure aggregate and focused mutants passed with no DB/TestClient calls. |

The direct probes emitted only the existing non-fatal Starlette TestClient/httpx deprecation warning. No retry invoked a live service, wrote a file, changed a cache, started/stopped a process, or altered Git state.

## Post-write state and closeout

The report was written once at the authorized path. Post-write verification confirmed:

- branch `codex/w1d-contract-transition` and HEAD `266beeaa2d150371ccd1a0f26f69249eca86ba16` unchanged;
- tracked dirty `0`, staged `0`, untracked `19`, with this report as the sole new path;
- all seven R25 candidate seals, office seal, and immutable R8 seal unchanged;
- `git diff --check --` exit `0`;
- named W1D product paths still absent and no tracked product delta;
- no cache/temp/process/listener cleanup or runtime-zero certification was attempted.

The report’s own SHA-256 is intentionally not embedded. It is computed independently in the final handoff together with its byte length.

JOSEPH_W1D_REAUDIT_R9_RESULT=APPROVE
