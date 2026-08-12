# Joseph W1D Phase 1 Design + Executable-RED Audit R5 / Grok R15

Date: 2026-07-31 (KST)
Role: independent, read-only Phase 1 design and executable-RED auditor
Scope: current shared bytes at `C:\sswcenter\2.1`

## Verdict

`REQUIRED_CHANGES`.

The current seven Phase-1 bytes are identity-correct and the required static
gates pass. R4 H01/H02 controls are substantially present, and R4 H03 has the
required public fixture and UI controls. However, the executable RED still has
confirmed false-pass/classification gaps:

1. malformed successful W1C setup responses can escape as a generic harness
   seed failure rather than controlled product RED;
2. the W1D fixture normalizer coercively accepts malformed numeric/date values,
   so a malformed product response can compare equal to PostgreSQL;
3. SQLSTATE `08*` is checked only after selected SQLAlchemy subclasses, so a
   transport error can be classified as product schema/data RED;
4. the concurrent STALE loser is asserted by selected counts/rows, not by a
   complete pre/post ledger and audit-rowset proof of write-zero.

These are executable-RED defects, not product implementation findings. Product
implementation remains prohibited.

## Authority and required reading

Read in the requested order: `README.md`; `docs/00_정본_문서_목록.md` and the
current AI 업무분담 운영규정 named there; the W1D assignment packet; all seven
current Phase-1 files; `docs/02_업무규칙_계약_v1.1.md`; `docs/03_UI_API_상호작용_계약_v1.2.md`;
`docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` including §§8 and 10; the R3
and R4 Joseph reports; the 2026-07-30 W1D office log including AUDIT-013 through
AUDIT-019 and ENV-046 through ENV-060; and `review/evidence/w1d/RED.md`.

The governing documents establish: Phase 1 is design plus executable RED only;
the next product migration is a direct child `0011` but must be absent in this
phase; first-contract `recipient_no` is issued once under the counter lock and
then immutable; signer fields are nullable snapshots; transition preview is
write-zero; apply requires confirmation, token/hash, complete replacement
multiset, locks and stale checks, one transaction and one aggregate audit; and
GREEN is not product PASS or Phase-1 approval.

## Identity, Git state, scope, and bytes

Read-only identity probe, repository root cwd:

```text
CWD=C:\sswcenter\2.1
BRANCH=codex/w1d-contract-transition
HEAD=266beeaa2d150371ccd1a0f26f69249eca86ba16
```

Before this report was created: tracked modified delta `0`, staged delta `0`,
and exactly 14 untracked paths. The seven Phase-1 paths were treated as
untracked authoritative bytes; `git diff` was not used as their change detector.

```text
backend/tests/test_w1d_contract.py
backend/tests/test_w1d_postgres.py
frontend/e2e/w1d-contract-transition.spec.ts
frontend/src/test/W1DContractTransition.test.tsx
review/environment/office/2026-07-30_W1D.md
review/evidence/w1d/RED.md
review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md
review/plans/W1D_CONTRACT_TRANSITION_PLAN.md
review/reports/W1D_JOSEPH_DESIGN_AUDIT_R2_266BEEA.md
review/reports/W1D_JOSEPH_DESIGN_AUDIT_R3_R6_266BEEA.md
review/reports/W1D_JOSEPH_DESIGN_AUDIT_R4_R10_266BEEA.md
review/reports/W1D_OPUS_DESIGN_AUDIT_266BEEA.md
review/reports/W1D_OPUS_DESIGN_AUDIT_CORRECTED_266BEEA.md
scripts/test-w1d-postgres.ps1
```

The seven current hashes and byte counts all match the sealed expected values:

| Path | Bytes | SHA-256 |
|---|---:|---|
| `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md` | 42368 | `565587da410857bf9abcb72e14f5bf1e05b09851bbbdcf9849f1cb5a1ced7b5f` |
| `review/evidence/w1d/RED.md` | 9182 | `4a79969c88e065c024062e08cf2386daca5175b9fe97cbb6d655f42ec323d13c` |
| `backend/tests/test_w1d_contract.py` | 31949 | `92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623` |
| `backend/tests/test_w1d_postgres.py` | 213799 | `55f0059fe3a6aeae1d9f534a96e087ea6c8af55be77345dd9e35466e0c527182` |
| `frontend/src/test/W1DContractTransition.test.tsx` | 17518 | `a70935c789332bfede8341a94b81194b8e32d4af176abda89674a023b7f058d7` |
| `frontend/e2e/w1d-contract-transition.spec.ts` | 17017 | `8b2d43cfc46e84a37a0e08f182b9ff569651662124c2a0c6f3780b311b7e6a05` |
| `scripts/test-w1d-postgres.ps1` | 72819 | `188d7e5ffb2ede88e525b94b29be3be10e1b0f11f73c4076ae2fe00a3ee0976b` |

Supporting bytes also match: office log 90513 bytes,
`5e3f87a2d7bb05a2505addd88df877d09a6d28d8059907384f3279f12e06dcfd`;
packet 11451 bytes,
`6a64ed0c62b3c69e26f30ecea07e415f5c66f7055d923fc5a80df98318ba75c9`; R4
report 21745 bytes,
`d0a33aca3514b547d59b3a56bbd287b75a8b09fcd7fda006f5aa95bcc99f61e9`.

The following product paths are absent: `backend/app/domains/w1d`,
`backend/alembic/versions/20260730_0011_w1d_recipient_contract.py`,
`frontend/src/services/w1dApi.ts`, and
`frontend/src/components/recipients/RecipientContractPanel.tsx`. The only
`0011` search hit under the inspected product/script roots is the wrapper’s
expected-revision literal at `scripts/test-w1d-postgres.ps1:22`; no product
revision or implementation path is present.

## Static gates and exact results

All commands below were read-only and were run without starting PostgreSQL,
FastAPI, Vite, or Playwright. The backend commands used cwd
`C:\sswcenter\2.1\backend`; Playwright used cwd
`C:\sswcenter\2.1\frontend`.

| Gate | Command / scope | Exit and result |
|---|---|---|
| Strict source encoding | PowerShell strict UTF-8 decoder plus BOM and `(?m)[ \t]+$` scan over the exact seven paths | exit `0`; `UTF8_BOM_FAIL_COUNT=0`, `TRAIL_WS_COUNT=0`, `UTF8_ERROR_COUNT=0`, `FILES=7` |
| PowerShell AST | `Parser::ParseFile` over `scripts/test-w1d-postgres.ps1` | exit `0`; `PS_AST_ERRORS=0`, `TOKENS=4916` |
| Python AST/compile | backend venv `python.exe -B`, `ast.parse` plus `compile` over both Python tests | exit `0`; `PY_AST_COMPILE_OK files=2` |
| Embedded seed AST/compile | line-based extraction from `$SeedScript = @"` through the later trimmed `"@`, backend venv `ast.parse` plus `compile` | exit `0`; opening marker line `505`, first code line `506`, terminator `1328`, `822` code lines, `35244` bytes including final LF, `SEED_AST_COMPILE_OK` |
| Ruff | `\.venv\Scripts\python.exe -m ruff check --no-cache --config pyproject.toml tests/test_w1d_contract.py tests/test_w1d_postgres.py` | exit `0`; `All checks passed!` |
| Pytest collection | `\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --collect-only tests/test_w1d_contract.py tests/test_w1d_postgres.py` | exit `0`; exactly `27` collected; one existing `StarletteDeprecationWarning` about httpx/Starlette TestClient |
| Playwright listing | `\.\node_modules\.bin\playwright.cmd test e2e/w1d-contract-transition.spec.ts --list --workers=1` | exit `0`; exactly `9` tests in one file across the three configured viewports |
| Tracked whitespace diff | `git diff --check --` | exit `0`, no output |

The R15 RED records the seed extraction as `start=505`; the independent
1-based line audit above distinguishes the opening marker line 505 from the
first embedded source line 506. The byte count and AST result match. This is a
line-number convention difference, not a source-byte discrepancy.

The contract test’s two broad `except Exception` assertion blocks were checked
against the venv’s actual pytest failure type:

```text
PYTEST_FAIL_EXCEPTION_MRO=(<class 'Failed'>, <class '_pytest.outcomes.OutcomeException'>, <class 'BaseException'>, <class 'object'>)
```

Therefore `_fail()` is not swallowed by those handlers at
`backend/tests/test_w1d_contract.py:320` or `:704`.

## R4 H01-H03 closure matrix

| Finding | Current evidence | Closure |
|---|---|---|
| H01 rejected-apply write-zero | `_write_zero_pair`/`_assert_write_zero_pair` at `backend/tests/test_w1d_postgres.py:611-630`; unconfirmed apply at `:1588-1615`; grade stale at `:1745-1751`; cert-date, grade-code, contract-period and service-multiset stale cases at `:3104-3325` snapshot after setup mutation and assert full ledger plus complete audit row set | The enumerated R4 H01 cases are closed. The separate concurrent loser proof remains incomplete; see `J-W1D-R5-H04`. |
| H02 list/item ACL and purity | `pg_15` starts at `:4850`; unauthenticated and no-permission list/item gates use exact 401/403 envelopes and write-zero pairs; VIEW list enforces exact top-level `{items}` at `:5066`, full normalized collection equality at `:5127`, item equality at `:5166`, and requested-missing-recipient fingerprints at `:5200+`. Admin create/list/get/end field checks remain in `pg_12`. | Closed for the R4 ACL matrix. A narrow ended-response timestamp coverage risk remains below; it does not reopen the active VIEW ACL closure. |
| H03 deterministic transition-stale fixture | Wrapper seed uses public W1C identity/cert/grade APIs, public W1D `HOME_CARE` then `HOME_BATH` creates, exact 14-field set, format/immutability checks and per-ID API↔DB equality before Playwright; E2E requires all five controls, dual preview equality, 200 winner and 409 stale. | Partial. Fixture structure and controls are present, but malformed W1C responses and coercive W1D normalization can escape the required product-RED gate (`J-W1D-R5-H01/H02`). |

## Confirmed defects requiring correction

### J-W1D-R5-H01 — malformed W1C 2xx response is misclassified as harness HIGH

In the embedded seed, after only checking status, the W1C setup parses and
coerces response data at `scripts/test-w1d-postgres.ps1:702,
723-724,741-742`. A malformed 2xx JSON body, non-object body, missing `id`, or
invalid value can raise `JSONDecodeError`, `AttributeError`, `KeyError`, or a
conversion exception outside the controlled W1D product-RED branch. The wrapper
then emits generic `W1D_HARNESS_E2E_SEED_FAILED` at `:1379-1380` rather than a
`W1D_E2E_TRANSITION_PRODUCT_*` marker. The required contract explicitly says
malformed product response is product RED; W1C transport/non-2xx baseline
failures may remain harness.

Minimal correction: add a non-PII W1C 2xx response validator around identity,
certification-period and grade-period bodies. Convert only validated fields;
emit controlled product-RED markers for malformed body/shape/value, while
retaining harness classification for transport and genuine W1C baseline
availability failures.

### J-W1D-R5-H02 — coercive W1D response normalization permits malformed data HIGH

`safe_int` at `scripts/test-w1d-postgres.ps1:758-765` calls `int(value)` for
arbitrary JSON numeric/string values. `normalize_contract_response` at
`:777-818` uses it for `id`, `recipient_id`, and `row_version`, and truncates
date-like values with `str(value)[:10]`. The create path reuses this at
`:896` and `:938`, then performs per-ID JSON equality at `:1147-1160` against a
similarly normalized DB object. For example, JSON `row_version: 1.5` becomes
`1` and can equal the persisted integer; a malformed numeric ID with a
fractional part can likewise be truncated. This is a false pass of the claimed
exact ContractResponse/product-response gate.

Minimal correction: require strict JSON field types (non-bool integers, exact
date strings, exact nullable timestamp representation, and exact string/null
fields) before normalization; do not truncate or coerce malformed values.
Emit `W1D_E2E_TRANSITION_PRODUCT_*` for every rejected shape/value.

### J-W1D-R5-H03 — SQLSTATE 08 transport classification order HIGH

The wrapper checks `OperationalError` at `scripts/test-w1d-postgres.ps1:1187`
but classifies `ProgrammingError`, `DataError`, and `IntegrityError` as product
RED at `:1193-1196` before it inspects `DBAPIError.orig.sqlstate` at
`:1197-1204`. A DBAPI exception carrying SQLSTATE `08*` but wrapped in one of
those subclasses therefore becomes `W1D_E2E_TRANSITION_PRODUCT_DB_PROGRAMMING`
instead of a harness connection/transport failure. That violates R14-02’s
explicit `OperationalError or SQLSTATE 08*` rule even though it cannot produce a
GREEN result.

Minimal correction: for every `DBAPIError`, extract and test SQLSTATE `08*`
first; classify it as harness before the product schema/data/cardinality
subclasses. Keep output to exception class and non-PII marker only.

### J-W1D-R5-H04 — concurrent loser write-zero is not full-ledger/audit HIGH

`pg_08` records worker strings and requires one `ok:` plus one exact
`CERTIFICATION_TRANSITION_STALE` at `backend/tests/test_w1d_postgres.py:2849-2857`.
It then checks selected winner period rows, selected counts, one transition audit
row and only `active_new_certs == 1` at `:2917-3048`. There is no full ledger
snapshot before the race and no complete post-race ledger/audit-rowset equality
proving that the rejected loser wrote zero. A loser-side mutation to another
target column or audit action can escape these selected checks while the test
still accepts one winner and one stale loser.

Minimal correction: seal the full target ledger and complete audit rowset for
the race, and assert the final state against an exact single-winner expected
projection/rowset (including no extra audit actions or target rows), rather than
selected counts only. Keep the deterministic dual-lock observation and exact
winner/loser result checks.

### J-W1D-R5-M01 — standalone recipient-number gate is too weak MEDIUM

The required format is zero-padded six-or-more decimal characters at
`review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:403`. `pg_00` only checks
non-empty at `backend/tests/test_w1d_postgres.py:881-882` and checks the second
number only for non-empty and inequality at `:939-940`. Thus the standalone
W1D-REC-03 test can pass `ABC` or `1`. The wrapper’s H03 fixture separately
checks `^[0-9]{6,}$`, so this is a gate-specific false pass, not a current
overall-wrapper GREEN path.

Minimal correction: assert the exact decimal regex on first issuance, second
recipient issuance, final persisted value, and immutable re-contract value in
`pg_00`.

## Residual implementation/test risks (not additional R4 blockers)

- `_assert_contract_response_matches_row` compares `invalidated_at_utc` only by
  nullability at `backend/tests/test_w1d_postgres.py:4183-4186`. Active VIEW
  `pg_15` rows are exact because the DB value is null, but the ended ADMIN
  response path in `pg_12` does not compare the exact non-null timestamp value.
- The E2E success readback at `frontend/e2e/w1d-contract-transition.spec.ts:352-359`
  checks status and returned ID for each new contract, not all 14 response fields
  against PostgreSQL. The wrapper fixture and PostgreSQL tests cover important
  create/transition equality, but this browser assertion is narrower than a
  full response contract.
- `pg_12` initially checks only that a list body contains an `items` list at
  `backend/tests/test_w1d_postgres.py:4212-4214`; the exact top-level collection
  gate is correctly added to VIEW `pg_15` at `:5066`. ADMIN list top-level shape
  is not independently sealed.
- Error-body `.json()` calls in several PostgreSQL tests are not all converted
  to controlled product markers. They fail the test rather than false-pass, so
  they are robustness/classification debt rather than a GREEN bypass.

## R11-R15 correction closure

| Revision/correction | Independent result |
|---|---|
| R11 | Full H01 snapshots, replacement mismatch matrix, ACL write-zero, deterministic fixture requirements and five UI controls are present. The malformed-response and concurrent-loser gaps above mean R11 is not fully executable-RED sealed. |
| R12 | Exact `L` plus 10-digit W1C identity fixture, public W1C/W1D setup, exact 14-key response, recipient-number checks in the wrapper, dual-preview equality and requested-ID missing-ledger fingerprints are present. W1C response handling and strict response typing remain open. |
| R13 | The R13 live result remains explicitly `INVALID/STALE`; it is not reused. Current RED states no R15 live run and does not claim product GREEN. |
| R14 | Per-ID response-to-DB mapping and class-only W1D DB exception reporting are now present; R14’s retained live seal is independently hash/byte/marker consistent. SQLSTATE precedence and concurrent loser proof remain open. |
| R15 | Static-only byte reseal is valid: exact seven hashes, all requested static gates, 27 collection, 9 Playwright listing, no product `0011`, no runtime. R15 is `RED_VALID_PENDING_DESIGN_AUDIT`, not product PASS. |

## R14 retained live seal and current cleanup

R14 was not rerun. The retained exclusive live is relevant historical evidence
only and remains product-absent RED:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `C:\WINDOWS\TEMP\w1d-r14-live.out` | 63718 | `932c073dc4ab4a4bad408943ac6dc07a2c4673ec1cf2e1b375d573dbd6cbfedf` |
| `C:\Users\USER\.grok\sessions\C%3A%5Csswcenter%5C2.1\019fb28c-7c3a-7153-8d29-fce6329a4365\terminal\call-a872ca4b-c09b-4668-91df-26f37cfff405-26.log` | 32073 | `d33ebe89a9e7301c4cd911bf1f8a644b927bb82672404fb9127fa3261f7014b8` |

Observed retained markers include revision `0010` versus expected `0011`, W1C
harness exit `0`, product-RED stages, transition/ended-table absence markers,
baseline marker count `9`, wrapper product failure, cleanup listener/process/temp/
artifact zeros, and no GREEN marker. Neither R14 nor R15 claims W1D product PASS.

Current read-only cleanup probes, after no Joseph runtime launch:

```text
Get-NetTCPConnection -State Listen filtered to 55479/18121/14221: COUNT=0
W1D process snapshot (postgres/pg_ctl/python/node/npm/playwright filtered): COUNT=0
TEMP_CLUSTER_COUNT=0 under C:\WINDOWS\TEMP\ (sswcenter-w1d-pg-*)
frontend/test-results: absent
frontend/playwright-report: absent
review/evidence/w1d/artifacts: absent
```

Existing `.pytest_cache` and `.ruff_cache` were preserved; no cleanup, deletion,
runtime, dependency, environment, Git, or product operation was performed.

## Intermediate probe problems and corrections

Every observer/probe problem was recorded and corrected or independently
classified; none changed workspace bytes:

1. The first identity command used PowerShell 5.1 `||`; it stopped at parser
   validation before executing a command. It was rerun with PowerShell-compatible
   branching.
2. An initial candidate-file search included nonexistent `tests` and `app` roots
   and emitted path errors; existing `backend/tests` and `backend/app` roots were
   then used.
3. The first R4-report read orchestration had a JavaScript syntax error; the
   report was reread successfully.
4. The first embedded-seed probe used backend cwd with a root-relative `scripts`
   path and got `DirectoryNotFoundException`; it was rerun from the repository
   root.
5. A PowerShell pipeline added U+FEFF to the extracted seed and Python correctly
   reported a non-printable-character `SyntaxError`; extraction was rerun
   file/line-based without the pipeline artifact.
6. Two early inline Python helpers were broken by PowerShell quote interpolation;
   one also used `:=`, unsupported by the bundled Python. They were replaced by
   compatible read-only helpers; the final seed AST/compile gate passed.
7. A false frontend `rg` path prefixed `frontend/` while already in the frontend
   cwd; the corrected relative query passed.
8. One focused `rg` regex had an unterminated PowerShell quote; a literal
   `Select-String`/narrowed `rg` probe produced the required line evidence.
9. The first seed-locator regex treated `$` as PowerShell interpolation; the
   literal `Select-String -SimpleMatch` locator confirmed opening marker line 505
   and terminator line 1328.

These are observer/command issues, not product defects, and no live command was
used as a substitute for the required static audit.

## Required correction before reseal

Keep the current branch/HEAD and product-absent scope. Correct only the RED
writer-owned test/wrapper paths for H01-H04 and M01 above, then recompute all
seven hashes, rerun the exact static gates, and obtain a fresh independent
Joseph audit. Do not begin product implementation from this report.

JOSEPH_W1D_REAUDIT_R5_RESULT=REQUIRED_CHANGES
