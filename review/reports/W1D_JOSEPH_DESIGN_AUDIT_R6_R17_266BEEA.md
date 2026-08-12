# W1D Phase 1 Design + Executable-RED Audit

## Audit identity and verdict

- Auditor: Joseph, independent W1D Phase 1 design and executable-RED auditor.
- Audit date: 2026-07-31 (Asia/Seoul).
- Repository: C:\sswcenter\2.1.
- Required mode: read-only repository audit, with exactly this report as the only authorized new file.
- Final verdict: REQUIRED_CHANGES.

The exact R17 seven-file seals are present, and the static gates are green. H02 and H03 are closed by the current executable checks. However, the executable RED still has confirmed false-pass paths for H01, H04, and M01. Those defects are sufficient to prevent approval of the Phase-1 design/RED package. No product implementation is approved.

## Authority, read order, and state identity

I read the required sources in the requested order: README.md; docs/00_정본_문서_목록.md; the current AI 업무분담 운영규정 named by that index, docs/AI_업무분담_운영규정_v3.5.md; review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md; the W1D office log with AUDIT-020 through AUDIT-022 and ENV-063 through ENV-066; review/reports/W1D_JOSEPH_DESIGN_AUDIT_R5_R15_266BEEA.md; the seven current Phase-1 files; canonical documents 02/03/04 at the referenced sections; and retained R14 evidence metadata only. No live R14 runtime was rerun.

Identity verification, from the actual audit cwd:

| Check | Result |
|---|---|
| cwd | C:\sswcenter\2.1 |
| branch | codex/w1d-contract-transition |
| HEAD | 266beeaa2d150371ccd1a0f26f69249eca86ba16 |
| tracked modified / staged | 0 / 0 |
| untracked before this report | 15, matching the expected pre-report state |
| W1D product revision 0011 and product paths | absent; the only 0011 hits found outside the sealed Phase-1 material were expected constants in backend/tests/test_w1d_contract.py:25-26 |
| office log before this report | 102210 bytes; SHA-256 b7a908b4c7643c9081f2108fde173e2600c42377ce172009c3d58a62cadd95b7 |
| assignment packet | 11451 bytes; SHA-256 6a64ed0c62b3c69e26f30ecea07e415f5c66f7055d923fc5a80df98318ba75c9 |

The initial default PowerShell reads displayed Korean text as mojibake; the affected documents were reread with explicit UTF-8 decoding. This was an observer issue only and did not alter repository bytes.

## R17 seven-file seals

| File | Bytes | SHA-256 |
|---|---:|---|
| review/plans/W1D_CONTRACT_TRANSITION_PLAN.md | 46076 | a1b03023df2358759c56b40ef9e203a16c0bdb6d1e3a2af1eb8ba7d584411b94 |
| review/evidence/w1d/RED.md | 5576 | dd93b680be686c3633d1866ea08aedcfadbfe7d4512c8183e149fe08d1b31eab |
| backend/tests/test_w1d_contract.py | 31949 | 92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623 |
| backend/tests/test_w1d_postgres.py | 239077 | 7a2bd371b63fc017a2ddd85ff761d2a7ce84f6b414413cb322ec71e6636a68d6 |
| frontend/src/test/W1DContractTransition.test.tsx | 17518 | a70935c789332bfede8341a94b81194b8e32d4af176abda89674a023b7f058d7 |
| frontend/e2e/w1d-contract-transition.spec.ts | 17017 | 8b2d43cfc46e84a37a0e08f182b9ff569651662124c2a0c6f3780b311b7e6a05 |
| scripts/test-w1d-postgres.ps1 | 77090 | a98970d4c048b63546a64918e7d3eb994316ce02adef8781f3eef731519f38d0 |

All seven current bytes matched the sealed R17 values before this report was created.

## Closure matrix

| Prior finding | R17 decision | Independent result | Severity |
|---|---|---|---|
| R5 H01 malformed nominal-success W1C responses | claimed closed | OPEN: wrapper validates only selected fields for identity/certification/grade and ignores extra or omitted nominal-success fields | P1 |
| R5 H02 strict 14-key API contract and DB normalization | claimed closed | CLOSED for the tested API response and per-ID DB equality paths; minor non-null timestamp stringification remains a hardening risk | — |
| R5 H03 SQLSTATE 08* harness classification | claimed closed | CLOSED: SQLSTATE 08* is classified as harness before product subclasses; class-only marker is used | — |
| R5 H04 exact concurrent loser write-zero | claimed closed | OPEN: timestamp and range assertions are permissive, and audit JSON is not exact; winner parsing has fallback acceptance | P1 |
| R5 M01 recipient number exact six-plus-digit string | claimed closed | OPEN: .strip() permits whitespace-wrapped values at first, second, and final/re-contract assertions | P1 |

R13 is invalid historical evidence for the current package. R14 is retained historical metadata only. The current package is static Phase 1 evidence; it does not establish product GREEN and does not authorize product implementation.

## Confirmed defects

### H01 — nominal-success W1C identity/certification/grade schemas are not exact

The embedded seed is the W1C baseline and does reach the W1B baseline assertions. The controlled product-RED continuation is also correctly wired: the malformed identity/certification/grade response is consumed as a controlled product RED and the seed later emits W1D_E2E_SEED_OK.

The defect is that the wrapper does not prove every malformed nominal-success response is rejected as required:

- scripts/test-w1d-postgres.ps1:720-727 parses only JSON objects.
- :758-798 checks the identity response’s recipient id, certification number type/value, and row version, but does not reject extra keys or prove an exact top-level keyset.
- :800-833 checks only selected certification-period fields and ignores recipient_id, invalidated_at_utc, replacement_certification_period_id, and row_version; extra keys are accepted.
- :835-884 has the analogous gap for grade-period responses, ignoring recipient id, invalidation/replacement fields, row version, and extra keys.
- The corresponding W1C product schema fields are defined in backend/app/domains/w1c/schemas.py:54-57, :69-76, and :99-108.

Therefore an adversarial nominal-success response can contain a wrong, missing, or extra field and still pass the wrapper’s selected checks before the later product-RED marker. This is a confirmed executable false-pass path, not merely a theoretical API concern. Transport and genuine non-2xx availability remain harness outcomes, as required; the defect is limited to nominal-success shape/content validation.

### H04-A — “full” row proof allows unconstrained timestamp and range values

The race helper does compare the full pre/post ledger state and exact id sets. It checks old rows for exact keysets, exact row_version = before + 1, the proposed end date/range, updated_by, and equality of the remaining captured columns (scripts/test-w1d-postgres.ps1:917-997). It checks complete keysets and most persisted values for newly created rows (:1000-1188). It also checks recipient, identity, counter, and audit prefix/append structure.

Those checks are not strict enough for the R17 claim that every persisted value is truly constrained:

- Existing-row updated_at is accepted whenever it is non-null, timezone-aware, and >= its pre-race value (:967-974). A loser or duplicate write that changes only that allowed field can therefore evade the “no loser write” assertion.
- New certification, grade, and contract timestamps are parsed for type/shape but are not compared to exact expected values or to a sealed pre/post transaction relation (:1043-1044, :1102-1103, :1187-1188).
- New contract range validation checks only the required lower-date prefix and allows infinity or an empty upper component (:1143-1153). It does not establish the exact range representation that the Phase-1 contract claims.
- Race-audit occurred_at is parsed only as a timezone-aware timestamp (:1406-1408); no exact relation to the single winner/apply event is proved.

I tested the validation logic with an in-memory mutant, without modifying repository files or starting a database. A new contract range of [2035-07-01,not-a-valid-upper-infinity) still passed the prefix/infinity predicate (MUTANT_OPEN_RANGE_PREFIX_ACCEPT=True). This demonstrates an executable acceptance gap.

### H04-B — audit before/after JSON is presence-only, and winner parsing accepts malformed payloads

The race helper requires the audit rows to have object-shaped before_json and after_json and requires five top-level keys to be present (scripts/test-w1d-postgres.ps1:1411-1429). It does not require exact object keysets, exact nested row projections, exact values, matching preview hashes, or the declared new-id projections. Thus an audit row can retain the required names while omitting or altering material fields without failing the proof.

The race uses a deterministic dual-lock and waits for two app connections to reach a lock wait (:3414-3507), then requires exactly one ok: result and one exact STALE result (:3669-3678). That is useful concurrency evidence, but it does not repair the incomplete ledger/audit projection checks.

The winner response is serialized as text (:3464-3471) and later parsed with int() plus ast.literal_eval/integer fallback and a digit-regex fallback (:3683-3720). I ran a read-only in-memory mutant using a malformed winner payload containing an integer token; it produced MUTANT_WINNER_FALLBACK_IDS=[42]. This is a confirmed false-pass path for malformed winner IDs. The parser must accept only the sealed structured response, with strict types and exact fields, and must fail closed on any malformed payload.

### H04 scope attack — benefit/approval and other recipient-ledger tables

The full-ledger helper includes recipient, identity, certification periods, grade periods, recipient contract, the global recipient counter, and the complete audit table (scripts/test-w1d-postgres.ps1:677-760). It does not include benefit/approval, guardian, payer, or assignment tables.

This omission is not itself a confirmed R17 defect: canonical document 04 §10.2 and the plan explicitly scope the transition apply to the transition-target ledger and state that benefit/approval is not part of the transition lock/end/create operation (review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:287-293, :466; canonical document 04 lines 517-544 versus 584-617 and 661-695). The helper is complete for the sealed Phase-1 transition target, not for every recipient-owned table. If the product scope is expanded to mutate those tables, the plan, RED, and exact ledger projection must be resealed before implementation. On the current sealed scope this is residual scope risk, not the approval blocker.

### M01 — recipient number validation trims values before exact regex

The helper uses str(value).strip() before applying the ^[0-9]{6,}$ regex (scripts/test-w1d-postgres.ps1:637-644). The first-value assertion is at :1687-1690, the second allocation at :1747-1752, and the re-contract/final assertion at :1782-1787; inequality and counter behavior are otherwise checked. The wrapper has the same trimming behavior at :1067-1075 and :1102-1108.

A read-only in-memory mutant confirmed MUTANT_RECIPIENT_TRIM_MATCH=True for a whitespace-wrapped recipient number. This violates the required exact string contract at the first, second, and final values. Remove trimming and coercion from the assertion path and require the direct string value itself to match ^[0-9]{6,}$, while preserving the immutability and inequality checks.

## H02 and H03 independent recheck

H02 is closed for the sealed paths. The API contract checker at scripts/test-w1d-postgres.ps1:886-953 enforces the exact 14-key set, exact primitive types (including rejecting bool as int), exact values, strict date strings, and null active fields. DB normalization is separate at :955-1012, and per-ID full equality is checked at :1238-1266, preventing a row swap from satisfying the comparison. A minor residual hardening concern is that db_ts_to_str_or_none uses str() for non-null DB values; the active null equality and exact key/value assertions prevent this from being an observed GREEN false-pass in the current baseline.

H03 is closed. OperationalError is harness at scripts/test-w1d-postgres.ps1:1311-1316; DBAPIError extracts the direct psycopg SQLSTATE/pgcode at :1300-1308; SQLSTATE beginning with 08 is classified as harness at :1317-1324 before product subclasses at :1325-1330. The emitted marker is class-only. The installed psycopg3 source was inspected read-only and exposes .sqlstate on the relevant error hierarchy.

## Cross-file consistency and product-absent truthfulness

The plan, RED, backend tests, frontend unit tests, E2E spec, and wrapper consistently describe a static Phase-1 contract-transition package with no product implementation. The frontend unit tests cover contract UI and stale/conflict paths (frontend/src/test/W1DContractTransition.test.tsx:175-237, :264-333, :335-431, :433-443). The Playwright spec uses real application paths with no API mocks and defines three scenarios across three viewports for nine listed tests (frontend/e2e/w1d-contract-transition.spec.ts:1-8, :37-44, :95-420). Its Number()/String() display parsing is a residual E2E hardening concern, but it does not override the stronger backend/wrapper findings.

No W1D product module, migration 0011, frontend API service, or contract panel was present. The current RED does not claim product GREEN. The required implementation hold therefore remains truthful, but the static RED itself is not sufficient for approval.

## Static gates

All gates below were run read-only; no file was modified to make a gate pass.

| Gate | cwd | Command/result | Exit |
|---|---|---|---:|
| strict UTF-8, BOM, trailing whitespace | C:\sswcenter\2.1 | seven files; UTF8_BOM_FAIL_COUNT=0 TRAIL_WS_COUNT=0 UTF8_ERROR_COUNT=0 FILES=7 | 0 |
| PowerShell AST | C:\sswcenter\2.1 | PS_AST_ERRORS=0 TOKENS=4916 | 0 |
| Python AST + compile | C:\sswcenter\2.1\backend | PY_AST_COMPILE_OK files=2 for both W1D Python test files | 0 |
| embedded SeedScript AST + compile | C:\sswcenter\2.1 | SEED_AST_COMPILE_OK start=505 first=506 end=1450 lines=944 bytes=39515 | 0 |
| Ruff | C:\sswcenter\2.1\backend | .\.venv\Scripts\python.exe -m ruff check --no-cache --config pyproject.toml tests/test_w1d_contract.py tests/test_w1d_postgres.py; All checks passed! | 0 |
| pytest collect-only | C:\sswcenter\2.1\backend | .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --collect-only tests/test_w1d_contract.py tests/test_w1d_postgres.py; 27 tests collected in 0.91s | 0 |
| Playwright list | C:\sswcenter\2.1\frontend | .\node_modules\.bin\playwright.cmd test e2e/w1d-contract-transition.spec.ts --list --workers=1; Total: 9 tests in 1 file | 0 |
| git diff --check -- | C:\sswcenter\2.1 | no output | 0 |

The pytest collection emitted one existing StarletteDeprecationWarning; collection still exited 0. No runtime PostgreSQL, browser, or shared wrapper was run by this audit.

## Retained evidence and cleanup/state

Retained R14 evidence metadata was read directly and not executed:

- C:\WINDOWS\TEMP\w1d-r14-live.out: 63718 bytes; SHA-256 932c073dc4ab4a4bad408943ac6dc07a2c4673ec1cf2e1b375d573dbd6cbfedf.
- C:\Users\USER\.grok\sessions\C%3A%5Csswcenter%5C2.1\019fb28c-7c3a-7153-8d29-fce6329a4365\terminal\call-a872ca4b-c09b-4668-91df-26f37cfff405-26.log: 32073 bytes; SHA-256 d33ebe89a9e7301c4cd911bf1f8a644b927bb82672404fb9127fa3261f7014b8.

The first fail-closed cleanup probe exited 2 because access to C:\WINDOWS\TEMP was denied. A second independent probe exited 1 with:

- exact W1D ports 55479, 18121, and 14221 listening: 0;
- W1D artifact directories present: 0 (frontend/test-results, frontend/playwright-report, and review/evidence/w1d/artifacts absent);
- process match count: 13, consisting of shared Node MCP processes and an existing PostgreSQL/pg_ctl tree on port 5432. These are not W1D exact-port processes and were preserved; no process was stopped.

No live runtime was launched by this audit, so there were no Joseph-created runtime artifacts to clean. Before creating this report, tracked modified and staged counts were both zero, untracked count was 15, and all seven sealed files and product-absence checks matched. After the authorized report write, the only intended new path is this report; final byte/hash/state verification is recorded in the handoff after creation.

## Observer/command issues recorded

1. The first combined packet/office/prior-report read command had a PowerShell parser error from a missing parenthesis (exit 1); the reads were rerun with simpler commands.
2. Default PowerShell decoding rendered Korean documents as mojibake (exit 0); the affected documents were reread with explicit UTF-8.
3. A first Python AST probe was launched from the backend cwd while resolving backend/.venv/Scripts/python.exe, causing path/invocation errors; its stale $LASTEXITCODE appeared as exit 0. The probe was rerun from the correct cwd with the correct interpreter.
4. A second AST probe had quote stripping that caused a Python SyntaxError (exit 1); it was rerun through stdin.
5. The first cleanup probe could not enumerate C:\WINDOWS\TEMP because of UnauthorizedAccessException (exit 2); the exact-port/process/artifact checks were rerun independently.
6. The independent cleanup probe exited 1 because of 13 shared-environment process matches; the processes were inspected and preserved.
7. One W1C search used the invalid glob path backend/tests/test_w1c* and exited 1; the search was rerun with explicit paths.
8. The first in-memory mutant probe had an unmatched Python parenthesis from quote composition (exit 1); the mutants were rerun with simplified expressions and produced the stated acceptance results.

## Narrow minimum correction packet

Before any Regina reseal or product implementation:

1. H01: make identity, certification-period, and grade-period nominal-success responses strict exact schemas: exact top-level keysets, exact primitive types, exact values, and explicit rejection of missing/extra/wrong fields. Keep transport and genuine non-2xx responses as harness outcomes and preserve the W1B seed baseline.
2. H04: require a strict structured winner response with no string/int/regex fallback; require exact old/new row keysets and values, exact permitted timestamp relationships or sealed timestamp projections, exact contract ranges, exact recipient/identity/counter state, exact audit prefix plus one append, and exact before/after JSON projections including hashes/new-id projections. Add a mutation test proving each rejected form.
3. M01: remove .strip() and coercion from first, second, and final/re-contract recipient-number assertions; require the direct value to be a string matching ^[0-9]{6,}$, retaining immutability and inequality checks.
4. Rerun all static gates and obtain a fresh independent exact-byte audit. Live PostgreSQL/browser evidence remains a separate authorized gate and must not be implied by this static audit.

No correction was implemented by Joseph. Product implementation remains prohibited until Regina reseals the corrected scope.

JOSEPH_W1D_REAUDIT_R6_RESULT=REQUIRED_CHANGES
