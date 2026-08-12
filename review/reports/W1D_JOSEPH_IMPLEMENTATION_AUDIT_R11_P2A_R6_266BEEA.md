# W1D P2A-R6 implementation audit R11

- Auditor: Joseph, independent read-only implementation re-auditor
- Audit date: 2026-07-31 (Asia/Seoul)
- Checkout: `C:\sswcenter\2.1`
- Branch: `codex/w1d-contract-transition`
- HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- Scope: exact uncommitted P2A-R6 package, frozen governing inputs, R10 findings, approved R9/R25 design/plan/RED, and static code/test conventions
- Authority boundary: no checkout or dependency changes, no product/test/plan/RED/wrapper/office edits, no database/API/server/browser/live wrapper/build, and no cleanup. This file is the sole authorized write.

## Result

The exact 24-file P2A-R6 candidate bytes are intact and all permitted static gates were run. The implementation is not suitable for Regina to seal as a P2B candidate yet. Three confirmed static contract issues remain; the first two are the blocking findings. Static results are not runtime GREEN.

## Confirmed findings

### P1 — preview hash projection is not the frozen canonical row-state projection

The frozen plan requires the canonical preview input to bind the active certification/grade/contract rows, service codes, dates, row versions, invalidation/replacement state, updated state, aggregate row version, and normalized transition/replacement input (`review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:236-251`; `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md:665-677`). The implementation used by both preview and apply does not serialize that exact state:

- `backend/app/domains/w1d/service.py:388-391` serializes certification periods without `replacement_certification_period_id` or `updated_at_utc`.
- `backend/app/domains/w1d/service.py:392-402` serializes grade periods without `replacement_grade_period_id` or `updated_at_utc`.
- `backend/app/domains/w1d/service.py:404-414` serializes contracts without `replacement_contract_id`, and uses `service_type_id` in the per-row projection rather than the required canonical service-code representation. The separate sorted multiset at `service.py:384-416` does not provide per-row service-code state.
- The projection is minted at `backend/app/domains/w1d/service.py:565-583` and recomputed for STALE at `service.py:661-683`, so the same incomplete serializer controls both sides of the stale decision.

This is a confirmed source-versus-frozen-contract mismatch, independent of live database proof. It weakens the intended stale-token binding and makes the emitted hash non-canonical for the approved input set. The frozen contract test only checks that the projection helpers and serialization version exist (`backend/tests/test_w1d_contract.py:359-370`); it does not assert the independent field set or a state-drift vector. Required action: align the projection with the frozen field/state contract, preserve the specified ordering and service-code representation, and add an independent serializer assertion plus runtime state-drift coverage before P2B.

### P2 — a late apply response can clear a newer preview/token

R6 correctly added recipient and preview-generation guards for list and preview responses (`frontend/src/components/recipients/RecipientContractPanel.tsx:76-147,192-246`). `handleApply` does not capture or compare a preview/apply generation. After any same-recipient apply response, success unconditionally calls `discardPreview`, clears stale state, and reloads (`frontend/src/components/recipients/RecipientContractPanel.tsx:249-265`); errors likewise clear or set stale/error state after only the recipient check (`RecipientContractPanel.tsx:266-280`).

Reproduction by state ordering: start apply with token A; edit a token-contributing field or start preview B while A is pending; let B resolve and become the current preview; then let A resolve. A's late success/error response still clears or changes B because `previewGenerationRef` is not checked in `handleApply`. This violates the latest-response/latest-token state contract even though the backend token prevents an unauthorized old request from being accepted. The R6 test covers immediate discard and deferred re-preview (`frontend/src/test/RecipientContractPanelState.test.tsx:317-405`) but has no deferred apply-completion interleaving. Required action: capture an apply generation/token identity and gate every post-await success/error/stale/load state mutation on the still-current generation and recipient; add deferred success, 409, and non-409 late-apply tests.

### P2 — replacement list order is accepted and signed without canonicalization

The frozen token contract requires `bound_replacements` in `ended_contract_id ASC` order (`review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:256-272`). The preview path retains caller order when building both the hash input and HMAC-bound list (`backend/app/domains/w1d/service.py:553-583`), while `_validate_replacement_multiset` checks cardinality, identity, uniqueness, and service-code matching but does not enforce order (`service.py:605-622`). A valid reversed request therefore receives a valid HMAC token with a non-canonical list and a different hash. Required action: sort before every canonical/hash/token projection or reject non-canonical order, and add an order-permutation contract test.

## R10/R6 closure checks

- Strict positive versions/IDs reject booleans and coercion; apply confirmation is strict boolean (`backend/app/domains/w1d/schemas.py:31-35,174-177`).
- Period semantics now reject reversed certification/grade/replacement periods, grade-before-certification, grade beyond a finite certification end even when grade end is null, and replacement starts not aligned to the new certification start (`backend/app/domains/w1d/schemas.py:38-75`). Apply repeats semantic validation only after exact STALE and request/token MISMATCH checks and before the first mutation (`backend/app/domains/w1d/service.py:661-731`).
- Recipient/input/re-preview invalidation and latest list/preview response guards are present (`frontend/src/components/recipients/RecipientContractPanel.tsx:76-147,192-246`), and the R6 state test asserts the old impact/token/confirmation are dropped before the newer preview returns (`frontend/src/test/RecipientContractPanelState.test.tsx:317-405`). The late mutation path remains open as described above.
- Migration and ORM shape, no-reactivation and group-overlap triggers, recipient lock ordering, counter insert/select lock, audit sequencing, fault seams, rollback, API response bindings, view/manage/CSRF dependencies, OpenAPI generation, and frontend route/UI integration were statically inspected. No additional confirmed defect was found in those areas beyond the findings above. Live database behavior, trigger execution, ACL enforcement, and browser behavior were not run.

## Static gates and evidence

All commands below were read-only under the audit boundary. Exit codes are PowerShell process exit codes.

| Area | Command/evidence | Exit/result |
|---|---|---|
| Backend focused tests | From `backend`: `.venv\\Scripts\\python.exe -B -m pytest -p no:cacheprovider -q tests/test_w1d_phase2_validation.py tests/test_w1d_contract.py` | 0; 42 passed in 12.54s |
| PostgreSQL test collection only | From `backend`: `.venv\\Scripts\\python.exe -B -m pytest -p no:cacheprovider --collect-only -q tests/test_w1d_postgres.py` | 0; 18 collected; existing Starlette/httpx deprecation warning |
| Product Ruff | `ruff check --no-cache app/core/settings.py app/db/models.py app/domains/w1d app/api/dependencies.py app/api/w1d.py app/main.py` | 0; all checks passed |
| Candidate validation Ruff | `ruff check --no-cache tests/test_w1d_phase2_validation.py` | 0 |
| Frozen W1D-test Ruff | `ruff check --no-cache tests/test_w1d_contract.py tests/test_w1d_postgres.py` | 1; frozen `tests/test_w1d_postgres.py:5579-5586` I001 import-order finding |
| Product format | `ruff format --check` over the product source set | 0; 13 files already formatted |
| Candidate-test format | `ruff format --check tests/test_w1d_phase2_validation.py` | 0 |
| Frozen-test format | `ruff format --check tests/test_w1d_contract.py tests/test_w1d_postgres.py` | 1; both frozen files would be reformatted |
| App typing | From `backend`: `.venv\\Scripts\\python.exe -B -m mypy --no-incremental app` | 0; 53 source files |
| Focused panel Vitest | `npm.cmd exec vitest -- --run src/test/RecipientContractPanelState.test.tsx --environment jsdom --maxWorkers=1` | 0; 1 file, 4 tests |
| Focused contract Vitest | `npm.cmd exec vitest -- --run src/test/W1DContractTransition.test.tsx --environment jsdom --maxWorkers=1` | 0; 1 file, 5 tests |
| Frontend full Vitest | `npm.cmd test` | 0; 18 files, 107 tests |
| Frontend typecheck | `npm.cmd exec tsc -- --noEmit --incremental false -p tsconfig.app.json` | 0 |
| Frontend lint | `npm.cmd exec oxlint -- src` | 0 |
| E2E collection only | `npm.cmd exec playwright -- test e2e/w1d-contract-transition.spec.ts --list --workers=1` | 0; 9 tests across 3 viewports; no browser execution |
| Generated OpenAPI check | From repo root: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\generate-openapi-types.ps1 -Check` | 0; `OPENAPI_TYPES_UP_TO_DATE`; temporary output removed by the generator |
| Pure policy/period/scalar/fault probe | Backend Python stdin probe covering token valid/tampered/cross-recipient/expiry, hash equality, finite-cert/null-grade boundary, strict bool/positive version, and fault seam | 0; `DIRECT_PURE_POLICY_PERIOD_SCALAR_FAULT_PASS` |
| Python syntax/AST | Python AST/compile pass over 17 candidate/frozen backend files | 0 |
| PowerShell syntax/AST | `Parser::ParseFile` over `scripts/test-w1d-postgres.ps1` | 0; `PS_AST_ERRORS=0`, `PS_AST_TOKENS=4916` |
| Diff whitespace | `git diff --check` | 0 |

The product/static green results above do not override the confirmed contract findings or authorize runtime approval.

## Explicitly not run

- PostgreSQL runtime, migration apply/rollback, database isolation/locking/counter/audit/fault harness, live ACL/CSRF, API/server, or wrapper execution.
- Playwright/browser execution, frontend build, or any command that would create `frontend/dist`.
- Any cleanup of pre-existing caches, temporary roots, test artifacts, processes, or other residuals.

## Observer issues and retries

Every issue below was read-only and caused no workspace mutation:

1. The first identity-check attempt used an invalid inline PowerShell `if` expression; it was rerun with an explicit label variable.
2. The next identity-check attempt had an unterminated quote around the office hash; it was rerun with tab-delimited output and passed all 32 identities.
3. A broad `rg`/PowerShell pipeline search returned exit 1 because of Windows glob/pipeline behavior and partial output; direct targeted source inspections were rerun successfully.
4. The frozen contract source observer used a repo-root-relative path while already in `backend`; it was rerun from the correct directory.
5. The combined Python-AST/PowerShell-wrapper observer passed Python but used the wrong wrapper path from `backend`; PowerShell parsing was rerun from the repo root and passed.
6. The first pre-write measurement was piped into a nested PowerShell process and returned exit 0 with no stdout; the measurement was rerun directly and produced the complete state and identity record below.
7. The dispatch packet said no `grok.exe`; the actual path `C:\Users\USER\.grok\bin\grok.exe` exists (139,159,368 bytes, version output empty), with zero running `grok` processes. It was not executed or modified.
8. Git emitted CRLF-to-LF working-copy warnings for seven pre-existing modified files during status/hash checks. `git diff --check` still passed; no file was touched.

## Pre-write exact state and scope integrity

The final pre-write measurement was run immediately before this report was created:

- cwd: `C:\sswcenter\2.1`
- branch: `codex/w1d-contract-transition`
- HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- staged paths: 0
- tracked modified paths: 8
- untracked paths: 34
- authorized report existed before write: false
- `frontend/dist`: absent
- `frontend/test-results`: absent
- `frontend/playwright-report`: absent
- candidate/frozen identity rows: 32
- identity mismatches: 0

The eight tracked modifications remained the expected pre-existing set: `.env.example`, `backend/app/api/dependencies.py`, `backend/app/core/settings.py`, `backend/app/db/models.py`, `backend/app/main.py`, `frontend/src/generated/sswcenter-api.ts`, `frontend/src/pages/RecipientsPage.tsx`, and `frontend/src/styles/recipients.css`. No tracked path was edited, staged, or otherwise changed by this audit.

### Exact P2A-R6 candidate identities (24)

SHA-256 and byte length were measured immediately before the report write.

| Path | SHA-256 | Bytes |
|---|---|---:|
| `.env.example` | `e5a9952f3482b2817fa1212d04138b34ff28f41ac64047f9b5709d2fb3aef86c` | 816 |
| `backend/alembic/versions/20260730_0011_w1d_recipient_contract.py` | `6fa513f878e021f41eca5270b92577cd1894aab1fa04dda1ff52fd025489c673` | 9276 |
| `backend/app/core/settings.py` | `f45c2a9657f7f3736f53c6d8b866238bf3a6f5dc1a9f22c6b029bcb1538c3400` | 6804 |
| `backend/app/db/models.py` | `b8c773641f13113cd2d69058609a18dbc0d73efad63039918bd8d4904d4e5f62` | 82629 |
| `backend/app/domains/w1d/__init__.py` | `cb3b904864d856ef3f7d7987c67eb28489b9414aaf078cd7ea43c2dbb9479b48` | 66 |
| `backend/app/domains/w1d/clock.py` | `3174653605f096835436099d671d214395eadcb194ce118316dfda18c2d1b97d` | 1168 |
| `backend/app/domains/w1d/errors.py` | `752d259538be681d06bf8bf41e2f84c5ec95d16cad88a73494bf4b2f147eff3b` | 2894 |
| `backend/app/domains/w1d/fault.py` | `8d4601a140e4e7b2e87b4b382a5942a1095defdf15b2a5efdd581a140a849b47` | 680 |
| `backend/app/domains/w1d/policies.py` | `fa0ecedeb5d51befb47277d6fed59eacb576362a1c56122c91cf7c0cc0f50464` | 5416 |
| `backend/app/domains/w1d/repository.py` | `f6fdb74b40e9d6381a37461f39613cbf6aadc7ff335a5a2efcda6d200f6196cd` | 6599 |
| `backend/app/domains/w1d/schemas.py` | `13196475862505ab1afab3defa75d17e27e71f3ec06c738c5c10dbd00ed13321` | 6859 |
| `backend/app/domains/w1d/service.py` | `04bbd130d1ab24601adf8717dcf5e9a3d13b259b4de8e23ec1ee508a5185f721` | 36096 |
| `backend/app/api/w1d.py` | `4d66450525b9ce29fcffaa84f38fe8db4be6763cb6706be89aa5e25e7505d85b` | 4496 |
| `backend/app/api/dependencies.py` | `fe68419b07905eef03acd233b8bbf2d3f6536723af09c46b54b9af31a8c588ba` | 8789 |
| `backend/app/main.py` | `17a39faa7fc314b7ec609446bbce24b32339070bb70a5a15ec70844d8aa240db` | 1793 |
| `frontend/src/services/w1dApi.ts` | `f960827b735cd02829a6daf517889b0d10f825867503054312736827e20c6539` | 3551 |
| `frontend/src/components/recipients/RecipientContractPanel.tsx` | `c45690e17e17b70b9f16e2f489cd4e1c063d8bce13e2c4f78712bb28c07b68ef` | 17995 |
| `frontend/src/pages/RecipientsPage.tsx` | `b6ec8f559b7385c71293e5393e74271578d3cd2a14dff4763bfd0a69defb7117` | 71565 |
| `frontend/src/styles/recipients.css` | `3f7608a9efc3f58f6e20196f48470afe073904ceb1072f97023df34aaec47bb0` | 14940 |
| `frontend/src/generated/sswcenter-api.ts` | `a41e6f856f17556f7ad4d816b5a0fd2fc3f7f6a64768f90a372dfe2cee1fd73b` | 349207 |
| `frontend/e2e/w1d-contract-transition.spec.ts` | `4e27e166412d74e0f680c53027e7b7d6de1b505a727abe9649073776400c9404` | 17804 |
| `frontend/src/test/W1DContractTransition.test.tsx` | `357243d4ec37038e1aef724d34fbd0947b6924f7b8fd28f3e6bc0a564d1b4770` | 17433 |
| `backend/tests/test_w1d_phase2_validation.py` | `e00581f616ce94b1afd56ee0d5b80cc242fd615d0b32a4ff412aadc238fa3b09` | 14476 |
| `frontend/src/test/RecipientContractPanelState.test.tsx` | `3980e4cf2ee7856218108b0736e7a0168277a8fb225b5d4a2212d2403f606e8b` | 13292 |

### Exact frozen governing identities (8)

| Path | SHA-256 | Bytes |
|---|---|---:|
| `backend/tests/test_w1d_contract.py` | `92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623` | 31949 |
| `backend/tests/test_w1d_postgres.py` | `b74b68c3c52dd57a66350d4a36583ee1891fc685b59c26c699838c7effa9c644` | 304628 |
| `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md` | `155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1` | 56890 |
| `review/evidence/w1d/RED.md` | `842049a4a2afce3cbd7cdbe90e8958add946a921e429596a4498bf626d8aefb2` | 5242 |
| `scripts/test-w1d-postgres.ps1` | `0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155` | 83648 |
| `review/reports/W1D_JOSEPH_DESIGN_AUDIT_R9_R25_266BEEA.md` | `b3f75e6fb301786cfb1d7c7fddf6968697376857ef9e4f7393cab27654e5f505` | 22104 |
| `review/reports/W1D_JOSEPH_IMPLEMENTATION_AUDIT_R10_P2A_R3_266BEEA.md` | `d454fbddb6ebd5909939b8243207de22f20e275c371069b245a3bb21e9a5d9d7` | 17055 |
| `review/environment/office/2026-07-30_W1D.md` | `92454a5e9dedf7f456aacaf440e8296bac9b41cd1328e2099312c7cc32862bf9` | 200902 |

## Residual state and handoff boundary

The following residual paths were present and intentionally not cleaned: `backend/.pytest_cache`, `backend/.ruff_cache`, `frontend/node_modules/.tmp`, `frontend/node_modules/.tmp/tsconfig.app.tsbuildinfo`, root `.pytest_cache`, and root `.ruff_cache`. The audit did not run a cleanup command. No `frontend/dist`, `frontend/test-results`, or `frontend/playwright-report` directory was present at the pre-write measurement. No process was left running by the audit.

The report write itself is the only authorized new workspace file. No stage, commit, push, branch, checkout, dependency, product, test, plan, RED, wrapper, office, database, server, browser, or build mutation was performed.

JOSEPH_W1D_IMPLEMENTATION_AUDIT_R11_RESULT=REQUIRED_CHANGES
