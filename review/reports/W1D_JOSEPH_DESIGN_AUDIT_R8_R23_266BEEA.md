# W1D Joseph R8 exact-byte design and executable-RED audit

## Verdict

The exact R23 package is not Phase-1 design/RED approvable. The required
corrections are narrow and confined to active RED assertion paths; no product
implementation is authorized by this report.

The R22/R23 shared winner, HTTP, and JSON-domain gates close the two reported
R7 findings on their intended paths, but two active PostgreSQL test paths still
accept values through coercion:

1. test_w1d_pg_05 compares audit projections with json.dumps(..., default=str)
   at backend/tests/test_w1d_postgres.py:3990-3997. An in-memory date and an
   equivalent tuple both pass this claimed exact comparison.
2. The active ContractResponse comparison helper at
   backend/tests/test_w1d_postgres.py:5951-5987 converts API IDs and dates
   before comparing them with the database row. The helper accepts string IDs
   and a date object, while the H02 contract requires exact JSON primitive
   types with no API-side coercion.

These are executable false-pass paths, not a live product GREEN claim. The
minimum correction is to route these active assertions through the existing
strict predicates/normalizers: use the shared exact audit projection predicate
and strict new-id checks in pg_05, and add a strict API ContractResponse gate
before the per-ID database comparison (with normalization limited to the DB
driver side). Remove the API-side int/date/default-str coercions. Do not
broaden the correction into product implementation.

## Audit identity and hard boundary

This was a fresh, independent, static-only R8 audit in C:\sswcenter\2.1.
The repository was not edited except for this unique report path. No product,
test, plan, RED, wrapper, packet, office log, prior report, configuration,
dependency, cache, environment, or generated artifact was edited. No process
was stopped and no stage, commit, push, pull, fetch, merge, rebase, stash,
branch/worktree switch, cleanup, installation, formatting, live PostgreSQL,
wrapper, backend, frontend, or browser campaign was run.

Start identity, observed before report creation:

| Check | Observed |
|---|---|
| cwd | C:\sswcenter\2.1 |
| branch | codex/w1d-contract-transition |
| HEAD | 266beeaa2d150371ccd1a0f26f69249eca86ba16 |
| tracked dirty / staged | 0 / 0 |
| untracked count | 17 |
| W1D revision 0011/domain/frontend product paths | absent |
| report target | absent and not tracked |
| office SHA-256 / bytes | 36fcefaf7efb69b717b46221f076c3ab1663e41b8b10898515e93fba5b349290 / 144339 |

The initial 17 untracked paths were the seven package inputs, office log,
packet, plan, five prior Joseph/Opus reports, and the wrapper/test files
listed by the identity observer. The report target was not in that list.

## Read authority and package seals

I read in the requested order: README.md; docs/00_정본_문서_목록.md and the
named AI 업무분담 운영규정; the W1D packet; canonical documents 02/03/04
and the transition anchors; the office log through ENV-088/AUDIT-030; the
frozen R6 report; the current filesystem R7 report and RED two-version race;
and the current R23 inputs. Korean authority files were reread with explicit
UTF-8 decoding after the first default PowerShell rendering was mojibake.

All seven supplied R23 input seals matched before this report was written:

| File | SHA-256 | bytes |
|---|---|---:|
| review/plans/W1D_CONTRACT_TRANSITION_PLAN.md | 66abc6caad122492b89c3da8eeb76cce4badd0a0cb6ea95f1571aeaa09fd42dc | 54366 |
| review/evidence/w1d/RED.md | 1520c9486d6abb5180d05b01e416c3919c9c02461ad4430bc4f8499fc2d4d333 | 6126 |
| backend/tests/test_w1d_contract.py | 92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623 | 31949 |
| backend/tests/test_w1d_postgres.py | b2184924d6410e2e2cdca607c70909f4ca404904f9d60fd058741af096a1a773 | 299723 |
| frontend/src/test/W1DContractTransition.test.tsx | a70935c789332bfede8341a94b81194b8e32d4af176abda89674a023b7f058d7 | 17518 |
| frontend/e2e/w1d-contract-transition.spec.ts | 24e83e1cbd65ca42deb0e6ec7b66297585098564076d2a8b6be52adb18a5971a | 17341 |
| scripts/test-w1d-postgres.ps1 | 4f3e24cd60fd21599a2c070b397ffd545bf2059322937220d6de69399d1c4689 | 83702 |

The current filesystem R7 report was independently sealed as
6615282b4e36a4b72c111b63fdfb85afae5c423126ad897ba673211ecc0acdce /
15229 bytes. The first asynchronous R7 identity retained by RED and the
office log is f4db172fc6207184596a24293495fb451edf058c628b2f2e9d7613e04f8e3a0e /
24839 bytes. Neither R7 report was overwritten or recreated.

## R7 union reattack

The union is preserved exactly:

- first R7 version: HTTP wire correlation versus the audit request_id;
- current filesystem R7 version: audit non-JSON false-pass and plan/RED
  status, evidence, and cleanup contradictions.

The HTTP and R22 shared JSON-domain work is real, but the active pg_05
assertion described below means the union is not fully closed.

### A. Internal winner and HTTP response correlation

The internal service/worker boundary is strict on the inspected path.
backend/tests/test_w1d_postgres.py:1537-1576 requires exactly five winner keys,
SUCCESS, strict positive non-bool integer IDs, one strict contract ID, and a
raw UUID object. The packer at 1586-1621 rejects UUID strings and calls the
same structured validator. The R20 pack mutants at 2121-2197 cover UUID
object acceptance, UUID string/malformed/None/int/bool rejection, malformed
IDs, scalar/list/member substitutions.

The HTTP gate at 2291-2390 requires the exact nine-key response, exact
recipient_id and recipient_no, exact ended certification/grade/contract lists
including order, exact new certification/grade/contract IDs, strict positive
non-bool integers, and canonical lowercase UUID correlation. The canonical
helper at 2239-2248 never lowercases or coerces. The R21/R22 mutant set at
2423-2508 attacks divergent valid UUIDs, uppercase/malformed/missing/UUID
object/int/bool/null correlation, missing/extra keys, string/bool/zero/
negative/scalar/tuple/duplicate IDs, wrong ended IDs/order, wrong new IDs/order,
and wrong recipient/recipient_no.

pg_16 at 7042-7384 is a real FastAPI TestClient preview/apply transaction,
not a mock. It verifies the one appended audit prefix/cardinality/action/entity,
canonical audit request_id, after_json.new_ids, exact HTTP-to-audit
correlation, exact HTTP-to-audit new IDs, old/new separation, cardinality,
recipient chain, parent/service/date properties, and the expected new persisted
rows. This closes the R7 HTTP finding on that path.

The browser apply/readback assertions at
frontend/e2e/w1d-contract-transition.spec.ts:328-366 require strict positive
integer values and exact GET id equality without Number/int/string conversion;
string and boolean IDs fail those checks. A residual hardening risk remains in
the preview-only assertions at lines 258-317, which still use Number() for
affected_contract_ids and String() for service values. That is not the
confirmed blocker here because the mandatory apply/readback path is strict,
but it must be hardened before a browser GREEN campaign.

### B. Audit JSON-domain and exact projection

The shared recursive domain predicate at
backend/tests/test_w1d_postgres.py:1727-1748 accepts only None, exact bool,
str, int, finite float, list, and dict with string keys recursively. It
rejects date, datetime, UUID, custom objects, tuple, set, non-string keys, and
NaN/positive-infinity/negative-infinity. The equality helper at 1751-1768 is
exact type/structure/value equality without default-str. The exact projection
gate at 1771-1818 retains exact top-level/hash/new_ids/nested
key/value/container rules. The actual concurrent winner assertion calls it
for before and after at 1507-1523. The R19/R20 mutants at 1918-2118 send
top-level, hash, new_ids, nested key/value/container, date, tuple, custom,
UUID, non-finite, non-string-key, and nested-set forms through that shared
predicate; the finite-float control is accepted. The mutant call path has no
Exception or BaseException catch around expected rejection.

The corrected direct pure aggregate returned:

DIRECT_PURE_AGGREGATE=PASS DB_CONNECTION_CALLED=NO
JSON_DOMAIN_ATTACKS_REJECTED=10
JSON_DOMAIN_FINITE_FLOAT_CONTROL=PASS

However, the active nominal transition test pg_05 does not use that predicate
for its own exact audit comparison. At lines 3911-3945 it performs manual
shape checks, at 3954-3958 it converts audit new IDs with int(), and at
3990-3997 it compares before/after using json.dumps(..., default=str). A
read-only in-memory reproduction returned:

PG05_DEFAULT_STR_DATE_FALSE_PASS=True
PG05_DEFAULT_STR_TUPLE_FALSE_PASS=True
PG05_INT_STRING_NEW_ID_FALSE_PASS=True

This is the same class of executable non-JSON false-pass that R7 identified,
left in a collected active path. It is a confirmed RED assertion defect even
though normal PostgreSQL JSONB rows are JSON-domain values; the requirement is
that the checker itself fail closed.

### C. Plan, RED, evidence, and cleanup truthfulness

The R23 plan is explicit at lines 950-962 and 1017-1019: static-only,
RED_VALID_PENDING_DESIGN_AUDIT, no approval/GREEN, R14 cleanup historical,
existing backend/.pytest_cache observed, root node_modules and named artifact
absence read-only only, and product implementation zero. RED.md lines 1,
9-19, 54-76, and 88-122 states the same. Both R7 report identities and their
union findings are represented at RED.md:29-32 and 45-49.

The corrected seed evidence is exact: wrapper opener line 505, first embedded
Python line 506, terminator line 1608; 1102 lines, 46109 characters, and
46127 UTF-8 bytes. There is no current 46112 claim in final R23 evidence.
The final collection evidence used the required no-cache-provider command,
not cache-clear. The office log records the earlier Grok --cache-clear as
observer/environment history only, including the pre-existing
backend/.pytest_cache observation. R13 is invalid, R14 is historical, R21/R22
corrections are historical/static evidence, and no product bytes are present.

## Earlier closure regression matrix

| Closure | Independent result |
|---|---|
| H01 W1C nominal success | No regression found. Wrapper seed validators at 704-810 require exact identity/certification/grade keysets, strict types, exact values/nulls, row_version 1, named product-RED routing, and W1B continuation. |
| H02 ContractResponse | Wrapper strict_api_contract_response at scripts/test-w1d-postgres.ps1:1043-1110 remains strict and its DB normalizer is separate. But active backend helpers are not closed: _assert_contract_response_shape at 5937-5948 checks keys only, while _assert_contract_response_matches_row at 5951-5987 coerces API IDs and dates. A direct no-DB call accepted string IDs and a date object and returned H02_BACKEND_MATCHER_ACCEPTS_STRING_IDS_DATE_OBJECT=TRUE. |
| H03 SQLSTATE 08* | No regression found. Wrapper lines 1445-1497 classify SQLSTATE 08* before product DBAPI subclasses and use class-only markers. |
| H04 dual-lock winner | pg_08 and _assert_single_winner_ledger_projection retain deterministic dual-lock winner/STALE, full old/new ledger, exact row_version/end/range/timestamp/audit prefix and one append, no loser write, and shared JSON predicate. The pg_05 active exact-audit path remains a separate fail-open coverage defect, so the package-wide H04/audit claim is not approvable. |
| M01 recipient_no | No regression found. backend/tests/test_w1d_postgres.py:637-646 and wrapper lines 1224-1235 use raw strict string matching, no strip/str coercion, with inequality/immutability checks. |

Canonical docs 02/03/04 and the transition plan reconcile the target ledger as
recipient, identity, certification, grade, contracts, counter, and one
authorized audit append. Benefit, approval, guardian, payer, and assignment
rows are explicitly outside this transition target and were not classified as
defects.

## Static gates and exact evidence

All commands below were read-only and run in the stated checkout.

| cwd | Exact command/check | Result |
|---|---|---|
| C:\sswcenter\2.1 | strict UTF-8 decode, BOM, trailing horizontal whitespace over the seven sealed inputs | UTF8_ERRORS=0, BOM=0, TRAILING_WS=0; exit 0 |
| C:\sswcenter\2.1 | PowerShell Parser.ParseFile on scripts/test-w1d-postgres.ps1 | PS_AST_ERRORS=0, TOKENS=4916; exit 0 |
| C:\sswcenter\2.1 | backend Python AST/compile for test_w1d_contract.py and test_w1d_postgres.py | both OK; exit 0 |
| C:\sswcenter\2.1 | newline-preserving embedded SeedScript extraction, AST, compile | opener=505, first=506, terminator=1608, lines=1102, chars=46109, bytes=46127; exit 0 |
| C:\sswcenter\2.1\backend | bundled Python -B direct pure aggregate and mutant probe | PASS, no DB connection, JSON attacks 10, HTTP mutation summary 11, UUID pack object pass/string reject; exit 0 |
| C:\sswcenter\2.1\backend | bundled Python -B -m ruff check --no-cache --config pyproject.toml tests/test_w1d_contract.py tests/test_w1d_postgres.py | All checks passed; exit 0 |
| C:\sswcenter\2.1\backend | bundled Python -B -m pytest -q -p no:cacheprovider --collect-only tests/test_w1d_contract.py tests/test_w1d_postgres.py | 28 tests collected in 0.84s; exit 0 |
| C:\sswcenter\2.1\frontend | .\node_modules\.bin\playwright.cmd test e2e/w1d-contract-transition.spec.ts --list --workers=1 | 9 tests in 1 file; exit 0 |
| C:\sswcenter\2.1 | git diff --check -- | no output; exit 0 |
| C:\sswcenter\2.1 | product path Test-Path and git ls-files checks | all named 0011/W1D product paths absent; tracked product count 0 |

The collection observer showed the existing StarletteDeprecationWarning about
httpx and starlette.testclient; it was non-fatal. The pytest cache directory
existed before and after the no-cache-provider collection with the same observed
mtime 2026-07-31T04:51:32.3246261+09:00.

## Read-only process, listener, and artifact observation

The exact W1D candidate listeners checked were ports 14192, 14221, 18092,
18121, 55442, and 55479: count 0. An exact W1D process filter excluding the
observer returned count 0. A broader observer found the existing shared
PostgreSQL listener on port 5432, owned by PID 24640; it was not started,
stopped, or used by this audit. Known W1D temp roots under C:\Windows\Temp
matched count 0.

Read-only artifact observations: root node_modules absent; frontend/node_modules
present as an existing dependency tree; frontend/test-results absent;
frontend/playwright-report absent; backend/.pytest_cache present. These are
observations only, not a current live cleanup certification.

## Observer issues and retries

1. Two early Windows PowerShell observer forms piped a foreach block directly
   and produced Empty pipe element parser errors, exit 1. A later form assigned
   the foreach result to an array before formatting and passed. One early
   product-path form also used the unsupported Windows PowerShell || operator;
   it was replaced with an explicit count/if form.
2. The first default PowerShell authority read rendered Korean text as
   mojibake while exiting 0. The files were reread with Get-Content
   -Encoding UTF8; those explicit-encoding reads are the evidence used here.
3. The first direct pure import probe did not register the dynamically loaded
   module in sys.modules, causing a dataclass import error. The retry inserted
   the module before exec_module and passed.
4. Two source-range observers were first run from backend with a
   root-relative backend/tests path and failed with path-not-found. They were
   rerun from backend with tests/test_w1d_postgres.py and passed.
5. The first H02 in-memory helper probe used a malformed PowerShell executable
   path and failed command resolution. A Join-Path-resolved bundled Python
   retry passed and produced the coercion evidence above.
6. The historical office observer records an earlier Grok --cache-clear
   collection and the resulting pre-existing backend/.pytest_cache metadata.
   This audit did not repeat that command; the final collection used
   -p no:cacheprovider.

No observer issue changed repository bytes, and no retry wrote a temporary
file or altered a process.

## Narrow correction and required reseal

Only the following narrow RED assertion corrections are required before a new
exact-byte audit:

1. In pg_05, replace the manual audit new_ids/int and
   json.dumps(default=str) comparison with the existing shared
   _validate_exact_audit_projection path, including exact authorized hash,
   before/after structure, exact new-id types/order/values, and prefix plus
   one-append checks.
2. In the active ContractResponse API tests, add the strict 14-key/type/value/
   null gate before _assert_contract_response_matches_row and keep driver
   normalization on the DB side only. Remove API-side int/date coercion from
   the exact comparison path.

The writer should then rerun the required static gates and obtain a fresh
Regina exact-byte reseal. Joseph implemented neither correction. Product
implementation remains prohibited until the design/RED package is corrected
and independently resealed; a later separately authorized Phase-2 runtime
campaign is required for any product GREEN decision.

## Post-write state

After adding this report, the expected state is tracked/staged 0/0 and
untracked 18, with the only new path
review/reports/W1D_JOSEPH_DESIGN_AUDIT_R8_R23_266BEEA.md. The final external
SHA-256 and byte length were computed by a read-only post-write
Get-FileHash/Get-Item observer and are provided in the task handoff. A
self-digest is intentionally not embedded in this file because embedding it
would change the file bytes.

JOSEPH_W1D_REAUDIT_R8_RESULT=REQUIRED_CHANGES
