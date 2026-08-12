# Joseph W1D implementation audit R12 / P2A-R8

## Result and boundary

This is a fresh independent, read-only Joseph audit of the exact uncommitted
P2A-R8 implementation package in the saved checkout. The package is acceptable
for Regina to proceed to P2B static/live planning. This is a static approval
only; it is not PostgreSQL GREEN, API/server GREEN, browser GREEN, wrapper
GREEN, migration-apply approval, cleanup certification, or Git closeout.

The sole persistent write authorized for this audit was this report:

review/reports/W1D_JOSEPH_IMPLEMENTATION_AUDIT_R12_P2A_R8_266BEEA.md

No product, test, migration, plan, RED, wrapper, office, generated-type,
environment, dependency, cache, or unrelated file was edited. No Git mutation,
PostgreSQL connection/runtime, migration apply/rollback, API/server start,
browser/Playwright execution, service start/stop, Computer Use, Grok, or
reviewer CLI was used.

## Checkout, topology, and authority

Measured checkout:

| Item | Observed |
|---|---|
| CWD and Test-Path | C:\sswcenter\2.1; exact match; path exists |
| Git top level | C:/sswcenter/2.1 |
| Branch | codex/w1d-contract-transition |
| HEAD | 266beeaa2d150371ccd1a0f26f69249eca86ba16 |
| Initial and pre-write status | staged/tracked-unstaged/untracked = 0/8/35 |
| Pre-write target report | absent |
| Pre-write frontend/dist | absent |
| Pre-write frontend/test-results | absent |
| Pre-write frontend/playwright-report | absent |
| Pre-write test/Grok process predicate | 0 |
| Pre-write git diff --check | exit 0 |

The eight tracked paths are .env.example, backend/app/api/dependencies.py,
backend/app/core/settings.py, backend/app/db/models.py, backend/app/main.py,
frontend/src/generated/sswcenter-api.ts, frontend/src/pages/RecipientsPage.tsx,
and frontend/src/styles/recipients.css. The untracked count is the task-owned
W1D implementation/evidence package plus the retained governance files; it was
35 at entry and at the final seal. There were no deletions.

Governing inputs and history:

- Design audit R9/R25 is approved only for the Phase-1 design/executable-RED
  boundary and explicitly is not product GREEN.
- R10 was REQUIRED_CHANGES for period validation, strict scalar handling, and
  preview/input invalidation.
- R11 was REQUIRED_CHANGES for incomplete canonical row-state projection, late
  apply-A UI mutation, and replacement ordering.
- Regina's P2A-R8 result is READY_FOR_JOSEPH_R12, not independent approval and
  not live GREEN.
- RED.md:7-19 remains static-only, RED_VALID_PENDING_DESIGN_AUDIT, and makes no
  current runtime-zero claim.

## Exact candidate and frozen seals

All 33 paths below were rehashed and byte-counted in the successful pre-write
seal. Every entry matched.

### Current P2A-R8 candidate paths

| Path | SHA-256 | Bytes |
|---|---|---:|
| .env.example | e5a9952f3482b2817fa1212d04138b34ff28f41ac64047f9b5709d2fb3aef86c | 816 |
| backend/alembic/versions/20260730_0011_w1d_recipient_contract.py | 6fa513f878e021f41eca5270b92577cd1894aab1fa04dda1ff52fd025489c673 | 9276 |
| backend/app/core/settings.py | f45c2a9657f7f3736f53c6d8b866238bf3a6f5dc1a9f22c6b029bcb1538c3400 | 6804 |
| backend/app/db/models.py | b8c773641f13113cd2d69058609a18dbc0d73efad63039918bd8d4904d4e5f62 | 82629 |
| backend/app/domains/w1d/__init__.py | cb3b904864d856ef3f7d7987c67eb28489b9414aaf078cd7ea43c2dbb9479b48 | 66 |
| backend/app/domains/w1d/clock.py | 3174653605f096835436099d671d214395eadcb194ce118316dfda18c2d1b97d | 1168 |
| backend/app/domains/w1d/errors.py | 752d259538be681d06bf8bf41e2f84c5ec95d16cad88a73494bf4b2f147eff3b | 2894 |
| backend/app/domains/w1d/fault.py | 8d4601a140e4e7b2e87b4b382a5942a1095defdf15b2a5efdd581a140a849b47 | 680 |
| backend/app/domains/w1d/policies.py | 5241880099277a58161447b56d5ea13dee26db2902960ccd46181fc2a5b6924d | 8291 |
| backend/app/domains/w1d/repository.py | f6fdb74b40e9d6381a37461f39613cbf6aadc7ff335a5a2efcda6d200f6196cd | 6599 |
| backend/app/domains/w1d/schemas.py | 13196475862505ab1afab3defa75d17e27e71f3ec06c738c5c10dbd00ed13321 | 6859 |
| backend/app/domains/w1d/service.py | 557c0c806a645ea166e16b7cafcf769204b1e01eab1a468a3f2150bc8d3488b3 | 41565 |
| backend/app/api/w1d.py | 4d66450525b9ce29fcffaa84f38fe8db4be6763cb6706be89aa5e25e7505d85b | 4496 |
| backend/app/api/dependencies.py | fe68419b07905eef03acd233b8bbf2d3f6536723af09c46b54b9af31a8c588ba | 8789 |
| backend/app/main.py | 17a39faa7fc314b7ec609446bbce24b32339070bb70a5a15ec70844d8aa240db | 1793 |
| frontend/src/services/w1dApi.ts | f960827b735cd02829a6daf517889b0d10f825867503054312736827e20c6539 | 3551 |
| frontend/src/components/recipients/RecipientContractPanel.tsx | f5170bb4bb1281069c59cd8c7592b7f7b7644e2b224afc2c62bd0fbdc0be2784 | 18429 |
| frontend/src/pages/RecipientsPage.tsx | b6ec8f559b7385c71293e5393e74271578d3cd2a14dff4763bfd0a69defb7117 | 71565 |
| frontend/src/styles/recipients.css | 3f7608a9efc3f58f6e20196f48470afe073904ceb1072f97023df34aaec47bb0 | 14940 |
| frontend/src/generated/sswcenter-api.ts | a41e6f856f17556f7ad4d816b5a0fd2fc3f7f6a64768f90a372dfe2cee1fd73b | 349207 |
| frontend/e2e/w1d-contract-transition.spec.ts | 4e27e166412d74e0f680c53027e7b7d6de1b505a727abe9649073776400c9404 | 17804 |
| frontend/src/test/W1DContractTransition.test.tsx | 357243d4ec37038e1aef724d34fbd0947b6924f7b8fd28f3e6bc0a564d1b4770 | 17433 |
| backend/tests/test_w1d_phase2_validation.py | 5db3db3454d95a809fd133fe3110d48c7c80d095d2f810ef59dcf57599e84df9 | 26436 |
| frontend/src/test/RecipientContractPanelState.test.tsx | ea34cbad7c377883d52806d90b39cf0aa58e1c8421f373de1da9c5bb4e347e4d | 19387 |
| backend/tests/test_w1d_postgres.py | abfb4f06f966b0183b1f436d319c19f34f2f484f450c07a5b3e725f6caf1198f | 313091 |

### Frozen governing paths

| Path | SHA-256 | Bytes |
|---|---|---:|
| backend/tests/test_w1d_contract.py | 92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623 | 31949 |
| review/plans/W1D_CONTRACT_TRANSITION_PLAN.md | 155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1 | 56890 |
| review/evidence/w1d/RED.md | 842049a4a2afce3cbd7cdbe90e8958add946a921e429596a4498bf626d8aefb2 | 5242 |
| scripts/test-w1d-postgres.ps1 | 0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155 | 83648 |
| review/reports/W1D_JOSEPH_DESIGN_AUDIT_R9_R25_266BEEA.md | b3f75e6fb301786cfb1d7c7fddf6968697376857ef9e4f7393cab27654e5f505 | 22104 |
| review/reports/W1D_JOSEPH_IMPLEMENTATION_AUDIT_R10_P2A_R3_266BEEA.md | d454fbddb6ebd5909939b8243207de22f20e275c371069b245a3bb21e9a5d9d7 | 17055 |
| review/reports/W1D_JOSEPH_IMPLEMENTATION_AUDIT_R11_P2A_R6_266BEEA.md | 76b55a78115c2d9316a1808d41fbb6e1f20089974e13d5aabfa31d9ea35b21d5 | 17567 |
| review/environment/office/2026-07-30_W1D.md | 2298d5b75b24e2f2dd9ac38eb467c5e6e0b4e1ea71b258707d6fcd4baf0ad59c | 216099 |

## R10, R11, and R8 semantic closure

### R10 period and strict scalar findings

R10-01 is closed in source. Positive IDs and row versions use strict Pydantic
integer fields that reject bool/coercion, and confirmation uses strict JSON
boolean validation: backend/app/domains/w1d/schemas.py:31-35. The service
still requires the runtime value to be exactly True at
backend/app/domains/w1d/service.py:729-734.

R10-02 is closed in source and tests. The shared pure validator rejects
reversed certification, grade, and replacement periods, grade start before
certification start, grade start beyond a finite certification end even with a
null grade end, grade end beyond a finite certification end, and replacement
starts not aligned to the new start:
backend/app/domains/w1d/schemas.py:38-75. The preview schema invokes it at
schemas.py:134-152. Apply parses the signed transition and performs the same
semantic validation only after STALE and request/token replacement MISMATCH,
before the first mutation, at service.py:799-838. The focused tests cover the
finite-cert/null-grade-end boundary at
backend/tests/test_w1d_phase2_validation.py:96-130, 163-225, and
244-320.

R10-03 is closed. Every transition input edit increments the preview generation
and discards preview, confirmation, bound replacements, and stale state at
frontend/src/components/recipients/RecipientContractPanel.tsx:93-105.
Recipient changes perform the same reset and invalidate both list and preview
generations at lines 135-147.

### R11 canonical row-state projection

R11-P1 is closed in source and static evidence. The actual hash path sorts
active certification, grade, and LTC rows by ID at
backend/app/domains/w1d/service.py:402-405 and builds the projection at
service.py:407-504. The projection contains:

- recipient ID and current certification number;
- recipient aggregate ID, row_version, and updated_at_utc;
- identity recipient ID, certification number, row_version, and updated_at_utc;
- active certification rows with ID, dates, row_version, invalidation,
  replacement certification FK, and updated_at_utc;
- active grade rows with ID, parent certification ID, grade code, dates,
  row_version, invalidation, replacement grade FK, and updated_at_utc;
- active LTC rows with ID, canonical service type and group codes, start/end
  dates including service_start_date, row_version, invalidation, replacement
  contract FK, and updated_at_utc;
- a sorted service-code multiset, normalized transition input, and sorted
  non-sensitive replacement subset.

The pure canonical builder fixes the top-level serialization version, key
ordering inputs, nulls, date/datetime serialization, and sorted service
multiset at backend/app/domains/w1d/policies.py:19-113. The non-sensitive
replacement projection contains only ended_contract_id, service_type_code,
start_date, end_date, and service_start_date at policies.py:130-145.
Signer name, relationship, phone, and end-reason text are included only in the
full HMAC-bound replacement set at policies.py:148-169 and do not enter the
hash input. The independent focused projection assertions at
backend/tests/test_w1d_phase2_validation.py:494-672 verify the field set,
PII absence, state-drift mutations, service-code representation, and
replacement permutation equality.

The additive PostgreSQL test exercises recipient aggregate, identity
aggregate, contract replacement/update state, and certification-period
updated-state drift. Each original token must return exact STALE and the
complete ledger plus complete audit row-set must remain unchanged:
backend/tests/test_w1d_postgres.py:7525-7743. It is collection-only in this
audit and was not executed.

### R11 replacement ordering and precedence

R11-P3 is closed. sort_replacements_by_ended_id is the single defensive
ended_contract_id ASC sort at policies.py:116-127. Both non-sensitive hash
input and full HMAC binding use it at policies.py:130-169. Preview sorts before
minting the hash/token and before returning replacement_preview at
service.py:639-701. Apply sorts both request and token-bound values before exact
comparison at service.py:788-797. The focused permutation assertions are at
backend/tests/test_w1d_phase2_validation.py:569-607.

Apply ordering is fail-closed as required: confirmation/token prerequisites
come first, locked current state is hashed and compared with
constant_time_hash_equal, STALE is raised before full replacement MISMATCH,
and semantic revalidation follows both checks:
backend/app/domains/w1d/service.py:723-838. The constant-time helper uses
hmac.compare_digest at backend/app/domains/w1d/policies.py:247-252.

### R11 late apply response finding

R11-P2 is closed. handleApply captures both the token and a new
preview-generation value, and every post-await success/error mutation is
guarded by the same-recipient and generation predicate at
frontend/src/components/recipients/RecipientContractPanel.tsx:249-293.
List and preview await paths have corresponding recipient/generation guards at
lines 107-147 and 192-246. The state test covers delayed apply-A success,
delayed 409, and delayed non-409 error while same-recipient preview B is
current at frontend/src/test/RecipientContractPanelState.test.tsx:407-585.
The same test also covers old preview response discard and fresh-token
confirmation at lines 317-405.

### R8 timestamp correction

R8 is closed. canonicalize_utc_timestamp parses ISO strings, maps trailing Z
to an explicit offset, treats naive datetimes as UTC, converts aware
datetimes to UTC, emits exactly +00:00, and raises ValueError for invalid
strings at backend/app/domains/w1d/policies.py:41-73. The focused tests cover
Z, +00:00, +09:00, aware datetime, naive datetime, null, and invalid strings
at backend/tests/test_w1d_phase2_validation.py:680-710. An additional direct
no-DB probe reproduced all six equivalent forms as the exact string
2030-01-01T00:00:00+00:00 and rejected four invalid strings.

## Package-level static audit

Migration and ORM:

- The migration is linear from W1C 0010 to W1D 0011 at
  backend/alembic/versions/20260730_0011_w1d_recipient_contract.py:1-18.
- The contract table, positive row-version/date checks, same-service exclusion,
  recipient/service/replacement/actor FKs, no-reactivation trigger, cross-group
  overlap trigger, and app/backup ACL statements are present at migration.py:
  65-227.
- ORM shape matches the migration, including generated half-open range,
  nullable service_start_date, invalidation/replacement state, actor columns,
  and constraints at backend/app/db/models.py:1925-2003.

API, ACL, CSRF, and read purity:

- List and GET use view dependency; create, end, preview, and apply use the
  manage dependency. Each W1D operation binds the error envelope at
  backend/app/api/w1d.py:26-138.
- RECIPIENT_VIEW and RECIPIENT_MANAGE permission checks and CSRF for manage
  operations are wired at backend/app/api/dependencies.py:203-242.
- The W1D router is included by the application at backend/app/main.py:16-41.
- list/get are read-only service paths at backend/app/domains/w1d/service.py:165-184;
  preview only reads current rows, constructs hash/token data, and returns a
  response at service.py:591-702.

Create/end/transition, audit, fault, and rollback:

- Contract create/end map DB constraint diagnostics to stable domain errors,
  lock the recipient, update row versions/timestamps, append audit events, and
  commit through the service at service.py:78-128 and 186-331.
- Transition apply ends grades, certification periods, and LTC contracts in
  the declared order, creates the new rows, appends one audit event, and
  commits only after all fault points at service.py:840-983.
- The outer apply exception path rolls back any open transaction at
  service.py:984-990. The dedicated fault seam is present at
  backend/app/domains/w1d/fault.py:1-32 and the injectable UTC clock at
  backend/app/domains/w1d/clock.py:1-43.

UI and integration:

- The W1D panel is mounted by RecipientsPage, uses the generated API surface,
  clears token state on recipient/input changes, and keeps async list/preview/
  apply results recipient- and generation-bound. Relevant source is
  RecipientContractPanel.tsx:76-293.
- OpenAPI generator -Check reports OPENAPI_TYPES_UP_TO_DATE. The generated
  source target remained byte-identical to its sealed candidate identity; it
  was not hand-edited.
- Playwright collection found the W1D tests and all configured test files
  without executing a browser.

## Static gate ledger

All paths below are read-only audit commands unless noted as a transient
generator output. CWD is explicit for each row.

| Command | CWD | Exit/result |
|---|---|---|
| .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q tests/test_w1d_phase2_validation.py tests/test_w1d_contract.py | backend | 0; 64 passed |
| .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --collect-only -q tests/test_w1d_postgres.py | backend | 0; 19 collected; only Starlette/httpx deprecation warning |
| .venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml on product/candidate Python paths | backend | 0; all checks passed |
| .venv\Scripts\python.exe -B -m ruff format --check --no-cache --config pyproject.toml on product/candidate Python paths | backend | 0; 15 files already formatted |
| .venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml tests/test_w1d_contract.py tests/test_w1d_postgres.py | backend | 1; known frozen-only I001 at test_w1d_postgres.py:5579 |
| .venv\Scripts\python.exe -B -m ruff format --check --no-cache --config pyproject.toml tests/test_w1d_contract.py tests/test_w1d_postgres.py | backend | 1; known frozen-only format drift in both frozen tests; not modified |
| .venv\Scripts\python.exe -B -m mypy app --no-incremental | backend | 0; 53 source files, no issues |
| Python AST parse and compile observer over 17 W1D/migration/test files | backend | 0; AST_COMPILE_OK 17 |
| PowerShell Parser.ParseFile scripts/test-w1d-postgres.ps1 | repository root | 0; 0 errors, 4916 tokens |
| .venv\Scripts\python.exe -B -m alembic heads | backend | 0; 0011 W1D sole head |
| .venv\Scripts\python.exe -B -m alembic history --verbose | backend | 0; linear 0010 -> 0011 history |
| Alembic offline upgrade 0010:0011 --sql with dummy 127.0.0.1:59999 review URL | backend | 0; 132 lines, schema/table/function/grant markers; no connection |
| powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate-openapi-types.ps1 -Check | repository root | 0; OPENAPI_TYPES_UP_TO_DATE; two temporary files removed and verified absent |
| npm.cmd exec vitest -- run src/test/W1DContractTransition.test.tsx src/test/RecipientContractPanelState.test.tsx --environment jsdom --maxWorkers=1 | frontend | 0; 2 files, 12 passed |
| npm.cmd exec vitest -- run src/test --environment jsdom --maxWorkers=1 | frontend | 0; 18 files, 110 passed |
| npm.cmd exec tsc -- -p tsconfig.app.json --noEmit --pretty false | frontend | 0 |
| npm.cmd exec tsc -- -p tsconfig.node.json --noEmit --pretty false | frontend | 0 |
| npm.cmd exec oxlint -- src | frontend | 0 |
| npm.cmd exec playwright -- test --list --workers=1 | frontend | 0; 66 tests in 10 files; list-only |
| git diff --check | repository root | 0; seven known CRLF normalization warnings only |
| Direct pure canonical/token/validation probe | backend | 0; UTC forms, invalid timestamp rejection, ordering, PII absence, and finite/null-grade boundary all verified |
| Strict UTF-8/BOM/trailing-whitespace observer over 33 exact paths | repository root | 0; 0 UTF-8 decode errors, 0 BOM; four pre-existing trailing-whitespace lines only in frozen R10 report lines 3-6 |

The optional production build was not run in this Joseph audit. No build
artifact was present before or after the audit. The prior office static reseal
is not used as runtime evidence.

## PostgreSQL test append-only proof

backend/tests/test_w1d_postgres.py was independently measured at 313091 bytes.
Bytes 0 through 304627 inclusive were hashed as exactly 304628 bytes:

b74b68c3c52dd57a66350d4a36583ee1891fc685b59c26c699838c7effa9c644

This equals the prior exact R6 prefix hash. The current suffix from byte 304628
through EOF is exactly 8463 bytes. The suffix is the additive
test_w1d_pg_17_preview_hash_canonical_state_drift test at
test_w1d_postgres.py:7525-7743. No PostgreSQL test was executed.

## Confirmed defects

None found in the exact sealed P2A-R8 package.

The frozen-only Ruff I001 and format drift are known governance/frozen-test
observations, not product defects, and were not changed. The four trailing
whitespace lines are in the frozen R10 report, not the candidate product/test
paths. The Git CRLF messages are read-observer warnings, not source changes.

## Residual and live risk

The following remain deliberately NOT_RUN and must be covered by P2B/live
execution before runtime GREEN:

- isolated PostgreSQL migration apply/rollback and all 19 PostgreSQL tests;
- trigger/exclusion/ACL enforcement, concurrent winner/STALE behavior, and
  complete write-zero verification at runtime;
- live FastAPI API/auth/CSRF/error-envelope behavior;
- browser execution of the 66 Playwright tests;
- wrapper execution, cleanup/listener/process checks, and production build
  artifact lifecycle;
- runtime audit-row equality, timestamp windows, and rollback fault matrix.

frontend/node_modules/.tmp/tsconfig.app.tsbuildinfo and
frontend/node_modules/.tmp/tsconfig.node.tsbuildinfo were observed as existing
ignored temporary TypeScript state and were not cleaned. No named frontend
artifact, test process, Grok process, or workspace runtime process remained.
No current runtime-zero claim is made.

## Observer errors, warnings, retries, and cleanup record

- The first source-display helper failed with PowerShell
  InvalidReferenceVariable because a colon in a diagnostic interpolated string
  was parsed as a drive-qualified variable. It was corrected and rerun; no
  file was touched.
- The first broad Alembic env/config search returned exit 1 because two guessed
  config paths did not exist. The exact env.py and backend/alembic.ini paths
  were then read successfully.
- The first Alembic offline run returned a terminating PowerShell
  NativeCommandError because ErrorActionPreference=Stop promoted normal
  Alembic INFO stderr to an error. A second run captured stderr, used the
  dummy nonconnecting URL, and exited 0.
- The first strict-file scan ran from backend with root-relative paths and
  returned FileNotFoundError for .env.example. It was rerun from the
  repository root and exited 0.
- The initial exact identity observer exited 0 but contained two
  operator-entered expected-string transcription errors for the migration and
  R10 report. The corrected exact table above matched all 33 paths; no source
  mismatch occurred.
- The first final-seal observer completed all identity/prefix/suffix checks but
  exited 1 when Git CRLF stderr was promoted by PowerShell
  ErrorActionPreference=Stop. The successful final seal captured the warnings,
  matched all 33 identities, and recorded test/Grok process count 0.
- Git status/diff observers emitted the seven known CRLF-to-LF normalization
  warnings. They did not change the worktree.
- The OpenAPI generator created two files in the Windows temp directory and
  removed them in its finally block; both exact paths were checked absent.
- No material deletion or cleanup action was performed. Pre-existing ignored
  caches/temp state was preserved.

## Successful pre-write seal

Immediately before this report write:

- CWD exact and existing; branch and HEAD exact.
- staged/tracked-unstaged/untracked = 0/8/35.
- target report absent.
- frontend/dist, frontend/test-results, and frontend/playwright-report absent.
- all 33 exact path hashes/byte lengths matched.
- PostgreSQL prefix hash and 8463-byte suffix matched.
- test/Grok process predicate = 0; six relevant processes were Codex MCP
  node helpers only.
- git diff --check exit 0.

JOSEPH_W1D_IMPLEMENTATION_AUDIT_R12_RESULT=APPROVE
