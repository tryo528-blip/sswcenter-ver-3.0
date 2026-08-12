# Joseph W1D implementation audit R10 / P2A-R3

Audit date: 2026-07-31 KST  
Role: independent read-only implementation auditor  
Checkout: C:/sswcenter/2.1  
Branch: codex/w1d-contract-transition  
HEAD: 266beeaa2d150371ccd1a0f26f69249eca86ba16

## Boundary and exact state

The saved dirty checkout was preserved. No pull, fetch, checkout, switch, stash,
reset, clean, add, stage, commit, push, merge, branch, dependency installation,
product/test/plan/RED/wrapper/office edit, service launch, live wrapper, browser,
PostgreSQL, API, or cleanup action was performed. The only workspace write in
this audit is this report.

The first path preflight compared C:/sswcenter/2.1 with Git's
C:/sswcenter/2.1 slash-normalized spelling and exited 1; this was an observer
path-normalization failure, not a checkout failure. The canonicalized rerun
exited 0 and found:

| Check | Result before report write |
|---|---:|
| Actual PowerShell cwd | C:/sswcenter/2.1 |
| Git top-level, canonicalized | same checkout |
| Branch | exact |
| HEAD | exact |
| Staged paths | 0 |
| Tracked modified files | 8 |
| Untracked files (git ls-files --others --exclude-standard) | 31 |
| Grok processes | 0 |
| Required report | absent |
| frontend/dist | absent |
| frontend/test-results | absent |
| frontend/playwright-report | absent |

The untracked W1D files, frozen inputs, prior review reports, wrapper, and office
record are all within the declared W1D review scope. No unrelated changed path
was found. backend/.pytest_cache and
frontend/node_modules/.tmp/tsconfig.app.tsbuildinfo were observed as existing
residuals; their timestamps predate this audit and they were not removed.

## Candidate and frozen byte seals

The final pre-write PowerShell SHA-256/byte-count loop exited 0; all 29/29
paths matched. Hashes are lowercase.

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
| backend/app/domains/w1d/policies.py | fa0ecedeb5d51befb47277d6fed59eacb576362a1c56122c91cf7c0cc0f50464 | 5416 |
| backend/app/domains/w1d/repository.py | f6fdb74b40e9d6381a37461f39613cbf6aadc7ff335a5a2efcda6d200f6196cd | 6599 |
| backend/app/domains/w1d/schemas.py | 4aa7942de6c66f93105752f776585477b0fedf8f5e7821121882aed7cdbff250 | 3700 |
| backend/app/domains/w1d/service.py | 4b3f9ac921f012dbdf47891e92a7b7d5164d40dbc9af325bb3b1c237c553ee1c | 35034 |
| backend/app/api/w1d.py | 4d66450525b9ce29fcffaa84f38fe8db4be6763cb6706be89aa5e25e7505d85b | 4496 |
| backend/app/api/dependencies.py | fe68419b07905eef03acd233b8bbf2d3f6536723af09c46b54b9af31a8c588ba | 8789 |
| backend/app/main.py | 17a39faa7fc314b7ec609446bbce24b32339070bb70a5a15ec70844d8aa240db | 1793 |
| frontend/src/services/w1dApi.ts | f960827b735cd02829a6daf517889b0d10f825867503054312736827e20c6539 | 3551 |
| frontend/src/components/recipients/RecipientContractPanel.tsx | f76acc064856b348675c19e186a8fe671509ea0cf99c1374533d071a5953d37a | 13510 |
| frontend/src/pages/RecipientsPage.tsx | b6ec8f559b7385c71293e5393e74271578d3cd2a14dff4763bfd0a69defb7117 | 71565 |
| frontend/src/styles/recipients.css | 3f7608a9efc3f58f6e20196f48470afe073904ceb1072f97023df34aaec47bb0 | 14940 |
| frontend/src/generated/sswcenter-api.ts | a41e6f856f17556f7ad4d816b5a0fd2fc3f7f6a64768f90a372dfe2cee1fd73b | 349207 |
| frontend/e2e/w1d-contract-transition.spec.ts | 4e27e166412d74e0f680c53027e7b7d6de1b505a727abe9649073776400c9404 | 17804 |
| frontend/src/test/W1DContractTransition.test.tsx | 357243d4ec37038e1aef724d34fbd0947b6924f7b8fd28f3e6bc0a564d1b4770 | 17433 |
| backend/tests/test_w1d_contract.py | 92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623 | 31949 |
| backend/tests/test_w1d_postgres.py | b74b68c3c52dd57a66350d4a36583ee1891fc685b59c26c699838c7effa9c644 | 304628 |
| review/plans/W1D_CONTRACT_TRANSITION_PLAN.md | 155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1 | 56890 |
| review/evidence/w1d/RED.md | 842049a4a2afce3cbd7cdbe90e8958add946a921e429596a4498bf626d8aefb2 | 5242 |
| scripts/test-w1d-postgres.ps1 | 0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155 | 83648 |
| review/reports/W1D_JOSEPH_DESIGN_AUDIT_R9_R25_266BEEA.md | b3f75e6fb301786cfb1d7c7fddf6968697376857ef9e4f7393cab27654e5f505 | 22104 |
| review/environment/office/2026-07-30_W1D.md | 30fce3c5a9a55138d366e3843ae860108c10203addc110ff781a3187f026f974 | 182828 |

## Findings

### P1 — Transition period and replacement-date validation is missing

Evidence:

- backend/app/domains/w1d/schemas.py:85-92 and :113-116 define the
  transition request fields but no period-order or containment validators.
- backend/app/domains/w1d/service.py:189-190 validates reverse dates only for
  ordinary contract creation; :294-295 validates only ordinary contract end.
  The transition preview path at :506-602 does not validate
  new_start_date/new_end_date, grade dates, or replacement dates.
- _validate_replacement_multiset at
  backend/app/domains/w1d/service.py:604-621 checks only count, duplicate/known
  ended IDs, and matching service code. It does not require
  replacement.start_date == new_start_date or validate replacement period order.
- Apply parses the signed dates at backend/app/domains/w1d/service.py:691-707
  and then inserts the new certification, grade, and contracts at :752-812
  without the required semantic checks. Existing DB checks at
  backend/app/db/models.py:1627-1634 and :1699-1709 can reject reverse
  periods, but _map_integrity_error at backend/app/domains/w1d/service.py:75-105
  maps those unrecognized constraints to UNEXPECTED_SERVER_ERROR/500.
- A read-only Pydantic probe exited 0 with
  INVALID_TRANSITION_DATES_SCHEMA_ACCEPTED for a reversed new certification,
  reversed new grade, and reversed replacement item. The accepted model is
  enough to reach preview/token generation because the service has no later
  preview validation.

This conflicts with the frozen plan at
review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:120-125,133,321,660-665:
period-order input is VALIDATION_ERROR/422, grade dates must be inside the new
certification period, and replacement starts must match the new start.
An input with a different but valid replacement start can pass the current
multiset check and persist a contract that is not aligned to the transition;
reverse dates instead risk a 500 after the apply transaction has begun.

Required correction: validate all transition and replacement period order,
grade containment, and exact replacement start alignment before hashing/minting
the preview and again before apply mutation; return the exact 422 validation
envelope and preserve write-zero behavior for rejected input. Add frozen-style
runtime coverage for reversed new/grade/replacement periods and mismatched
replacement starts.

### P2 — Apply confirmation is not a strict JSON boolean

StrictModel at backend/app/domains/w1d/schemas.py:11-13 forbids extra keys but
does not enable strict scalar parsing. Consequently the confirmed: bool field
at :114 accepts JSON numeric 1 and converts it to Python True. The direct
read-only probe exited 0 with
CONFIRMED_INPUT_TYPE=bool;VALUE=True for confirmed=1.

The plan requires a non-null boolean at
review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:156-162, and the service's exact
confirmed is True check at backend/app/domains/w1d/service.py:629-631 is
therefore reached for a non-boolean wire value. Make this request field strict
(and review the positive version fields for the same bool/int coercion), then
add raw JSON boundary tests for 1, 0, and string booleans.

### P2 — Preview and confirmation survive recipient/input changes

Evidence:

- frontend/src/components/recipients/RecipientContractPanel.tsx:29-53 stores
  recipient-specific create fields, transition inputs, preview, confirmation,
  stale state, and bound replacements locally.
- Its only recipientId effect at :55-67 reloads the contract list. There is
  no effect that discards the preview, confirmation, or form state when
  recipientId changes.
- Transition input handlers at :318-365 only update the input state. They do
  not invalidate an already generated preview. Apply at :151-158 submits the
  stored token and boundReplacements, not the current visible transition
  inputs.
- The parent changes recipients in place at
  frontend/src/pages/RecipientsPage.tsx:958-966 and renders the panel without
  a recipient key at :1739-1751, so React preserves the child state across a
  recipient switch.

Thus a confirmed preview for recipient A can remain displayed while recipient B
is selected, and a changed transition form can still apply the old preview
intent. The backend token binding should reject the cross-recipient call, but
the UI shows stale impact/confirmation and permits a misleading request; create
form drafts also leak between recipients. This conflicts with the plan's
preview/confirmation discard requirement at
review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:618-620.

Required correction: invalidate preview, confirmation, stale banner, and bound
replacement state on recipient changes and on every input that contributes to
the preview token; either reset or explicitly preserve create drafts by
recipient. Add a component test for recipient switching and editing any
transition input after preview/confirmation.

### Non-blocking typing observation

The generated OpenAPI file is byte-sealed and generator reproducibility passed,
but frontend/src/services/w1dApi.ts:1-69,116 manually redeclares W1D request/
response types and uses Record<string, unknown> for replacement payloads,
where frontend/src/services/w1cApi.ts:1-4 derives types from generated
components. This is a type-safety/convention gap, not used as an additional
decision blocker because the wire schema and generated file themselves match.

## Implementation areas independently checked

| Area | Static result |
|---|---|
| Migration graph, generated half-open range, same-service exclusion, parent-lock cross-group trigger, no-reactivation trigger, grants | Match the frozen plan and ORM; no mismatch found |
| ORM identity/constraints, nullable fields, signer/history fields, no contract_no | Match the frozen contract and generated schemas |
| Recipient counter and first-contract transaction | Recipient lock then counter lock, absent-row ON CONFLICT path, audit and rollback path present |
| Apply lock order and fault points | Recipient/identity/cert/grade/contract lock order and all required labels are present; pure fault probe passed |
| Token key/TTL/HMAC/precedence/stale/mismatch | Dedicated key, 30-minute injectable clock, signed full replacement binding, constant-time hash comparison, and precedence match; pure tamper/expiry/replay primitives passed |
| Audit before/after projection and UUID correlation | Exact projection keys and UUID response field are present; no invalidated_at_utc projection mismatch found |
| ACL, ADMIN inheritance, CSRF, API error envelope | Static dependency/router/OpenAPI bindings match the frozen contract |
| Generated OpenAPI provenance | Frozen contract test's generator check passed; generated file seal matches |
| Frontend LTC multiset, confirmation/stale handling, list/detail refresh, no reactivation, strict E2E assertions | LTC filtering, stale discard, parent refresh, no reactivation control, and strict raw ID assertions present; P2 state-reset finding remains |

## Commands and results

All commands were read-only and run in the stated checkout. -p
no:cacheprovider, --no-cache, and --no-incremental were used where applicable.

| CWD | Exact command/result |
|---|---|
| root | Initial slash-sensitive preflight: exit 1 (observer-only path comparison); canonicalized cwd/top-level rerun: exit 0, exact identity/state above |
| root | SHA-256/byte loop over the 29 declared paths: exit 0, PACKAGE_COUNT=29, FAILURES=0 |
| backend | & .venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml app/core/settings.py app/db/models.py app/domains/w1d app/api/dependencies.py app/api/w1d.py app/main.py: exit 0 |
| backend | Same Ruff check including both frozen W1D tests: exit 1; one I001 at tests/test_w1d_postgres.py:5579-5586 |
| backend | & .venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml tests/test_w1d_contract.py: exit 0 |
| backend | & .venv\Scripts\python.exe -B -m ruff format --check --no-cache --config pyproject.toml app/core/settings.py app/db/models.py app/domains/w1d app/api/dependencies.py app/api/w1d.py app/main.py: exit 0, 13 files formatted |
| backend | Ruff format check including frozen contract test: exit 1; frozen tests/test_w1d_contract.py would be reformatted |
| backend | & .venv\Scripts\python.exe -B -m mypy --no-incremental app: exit 0, 53 source files |
| backend | Combined mypy over app plus both frozen W1D tests: exit 1, 72 diagnostics in the frozen test files; no product app diagnostics |
| backend | & .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q tests/test_w1d_contract.py: exit 0, 10 passed |
| backend | & .venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --collect-only -q tests/test_w1d_postgres.py: exit 0, 18 collected; one pre-existing Starlette/httpx deprecation warning |
| backend | Read-only AST parser over candidate backend and frozen W1D tests: exit 0, 15 files |
| backend | Pure policy/token/clock/fault probe: exit 0, PURE_POLICY_TOKEN_FAULT_PASS |
| backend | Reversed transition/replacement Pydantic probe: exit 0, INVALID_TRANSITION_DATES_SCHEMA_ACCEPTED (finding P1) |
| backend | Non-strict confirmation probe with confirmed=1: exit 0, CONFIRMED_INPUT_TYPE=bool;VALUE=True (finding P2) |
| frontend | npm.cmd exec vitest -- --run src/test/W1DContractTransition.test.tsx: exit 1, expected jsdom environment missing (document is not defined) |
| frontend | npm.cmd exec vitest -- --run src/test/W1DContractTransition.test.tsx --environment jsdom --maxWorkers=1: exit 0, 5 passed |
| frontend | npm.cmd test: exit 0, 17 files / 103 tests passed |
| frontend | npm.cmd exec tsc -- --noEmit --incremental false -p tsconfig.app.json: exit 0 |
| frontend | npm.cmd exec oxlint -- src: exit 0 |
| frontend | npm.cmd exec playwright -- test e2e/w1d-contract-transition.spec.ts --list: exit 0, 9 tests listed across 3 viewports |
| root | git diff --check: exit 0; only CRLF normalization warnings for existing tracked W1D files |
| root | First artifact/process verification command: exit 1 due observer PowerShell parenthesis syntax; corrected verification: exit 0, report/dist/test-results/playwright-report absent and Grok count 0 |

The contract pytest run internally exercised the approved OpenAPI generator
check using temporary files and cleaned its temporary outputs; no workspace
generated artifact was left by that run. The frozen Ruff/mypy/format failures
above were not repaired because those exact frozen files are outside the
authorized write boundary.

## Live gates explicitly not run

The following remain NOT_RUN by instruction and are not represented as runtime
evidence: full PostgreSQL tests/test_w1d_postgres.py execution;
scripts/test-w1d-postgres.ps1; direct PostgreSQL migration/constraint and
concurrency execution; live FastAPI/API HTTP campaign; browser/Playwright
execution; service/bootstrap/listener launch; frontend npm build (forbidden
because it creates frontend/dist); and runtime cleanup/zero-state
certification. Static passing results do not establish runtime GREEN and do not
authorize P2B.

## Final cleanup and residual state

No cleanup was authorized or performed. Immediately before this report write,
the exact candidate/frozen seal loop and Git/artifact/process checks were all
clean as recorded above. After this report is written, the expected sole state
delta is this new untracked report: staged 0, tracked modified 8, untracked
files 32, HEAD and branch unchanged, and the three named frontend artifact
paths absent. Existing backend/.pytest_cache and the pre-audit frontend
TypeScript build-info files remain untouched.

The P1 transition validation defect and P2 schema/UI defects are actionable and
must be corrected and independently resealed before any runtime campaign.

JOSEPH_W1D_IMPLEMENTATION_AUDIT_R10_RESULT=REQUIRED_CHANGES

