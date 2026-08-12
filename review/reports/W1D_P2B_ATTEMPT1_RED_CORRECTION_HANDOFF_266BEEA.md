# W1D P2B attempt 1 RED and correction handoff

- Owner: Regina
- Branch: `codex/w1d-contract-transition`
- HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- First live run: 2026-07-31 KST
- Correction seal: `2026-07-31T10:41:15.8178421Z`
- Status: **runtime RED preserved; corrected candidate not yet live-rerun**

## 1. Pre-run seal

The R12 report and candidate were checked immediately before execution.

- R12 report SHA-256: `4b60c8c4608f176ae4df68680bb8b6299c2686e172fd4587247a9e36a0198265`
- wrapper SHA-256: `0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155`
- wrapper parse errors: `0`
- R12 identities: `32/32` matched after excluding the append-only office log
- listeners on `55442`, `18092`, `14192`: `0`, `0`, `0`
- workspace PostgreSQL/Python/Node runtime processes: `0`
- prior `frontend/dist`, `frontend/test-results`, `frontend/playwright-report`: absent

The sealed wrapper was invoked exactly once, sequentially and exclusively:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\test-w1d-postgres.ps1 -Port 55442 -BackendPort 18092 -FrontendPort 14192
```

The wrapper itself invoked Playwright with `workers=1`.

## 2. Attempt 1 observed result

- parent exit: `1`
- harness self-check: `1 passed`, `18 deselected`, exit `0`
- PG00 stage: `1 passed`, `18 deselected`, exit `0`
- PostgreSQL product remainder: `13 passed`, `4 failed`, `2 deselected`, exit `1`
- browser E2E: `9 passed`, exit `0`
- final product marker: `W1D_PRODUCT_STAGES_FAILED`
- final wrapper marker: `W1D_WRAPPER_PRODUCT_FAILURE: W1D_PRODUCT_STAGES_FAILED`
- no `W1D_POSTGRES_GREEN` was accepted

Observed failures:

1. `test_w1d_pg_05_transition_preview_apply_stale_multiset_fault_audit`
   raised `TypeError` because the dynamic mutation case supplied a fixed keyword and
   the same keyword through `**{field: value}`.
2. `test_w1d_pg_07_token_tamper_expiry_replay_preview_required`
   accepted a token whose final base64url character was textually changed but decoded
   to the same bytes through non-canonical padding bits.
3. `test_w1d_pg_12_list_get_end_contract_api`
   expected `200` while changing a finite `end_date` to another finite date, contrary
   to the sealed open-ended-only end operation; product correctly returned `409`.
4. `test_w1d_pg_13_null_identity_and_free_text_validation`
   made the same finite-to-finite end request and received `409`.

The later PG13 Unicode fixture had the same latent finite-to-finite pattern and was
corrected proactively before another live run.

## 3. Cleanup evidence

Wrapper cleanup markers:

```text
W1D_CLEANUP_LISTENERS pg=0 backend=0 frontend=0
W1D_CLEANUP_PROCESSES pg=0 backend=0 frontend=0
W1D_CLEANUP listener=0 process=0 temp=0 artifact=0 artifact_removed=1
```

Independent post-run checks also found:

- listeners on all three ports: `0`
- workspace runtime processes: `0`
- `%TEMP%\sswcenter-w1d-pg-*` directories: `0`
- `frontend/dist`, `frontend/test-results`, `frontend/playwright-report`: absent
- R12 sealed identities after execution: `32/32` unchanged

## 4. DeepSeek writer correction

The direct DeepSeek writer was limited to these paths:

- `backend/app/domains/w1d/policies.py`
- `backend/tests/test_w1d_postgres.py`

Changes:

- `_b64decode` now re-encodes decoded bytes and rejects any non-canonical unpadded
  base64url segment before signature acceptance.
- PG05 builds a baseline mutation dictionary and overrides the selected field once.
- PG12 preserves the finite create/get/list round trip and uses a separate,
  non-overlapping open-ended contract for successful end and stale-version checks.
- PG13 preserves finite omit/null/empty fixtures, uses a separate open-ended contract
  for explicit empty end-reason behavior, and creates the Unicode end target open-ended.
- Ruff-only cleanup removed one unused variable and normalized a local import block.

No assertion, expected status, wrapper path, governing document, migration, API route,
repository, schema, frontend file, or unrelated product file was changed.

## 5. Corrected candidate seal

| Path | SHA-256 | Bytes |
|---|---|---:|
| `backend/app/domains/w1d/policies.py` | `5c0610f117a514db81b9d187093ea7a9c7865e049552ad56c9787c1b7b8909e3` | 8572 |
| `backend/tests/test_w1d_postgres.py` | `5d973b706b3562637e4387c356c3d8a65d8a7f0050bdf8c1b0530964861536e2` | 307587 |

Of the 32 non-office R12 identities, exactly these two paths changed; the other
`30/30` remain byte-identical. Governing and wrapper hashes remain:

- plan: `155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1`
- wrapper: `0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155`
- R12 report: `4b60c8c4608f176ae4df68680bb8b6299c2686e172fd4587247a9e36a0198265`

## 6. Local correction checks

Run from `C:\sswcenter\2.1\backend` with bytecode/cache writes disabled where
applicable:

- Python AST parse for both changed files: `PASS (2/2)`
- minted canonical token verifies: `PASS`
- final-character textual tamper is rejected: `PASS`
- `python -m ruff check --no-cache app/domains/w1d/policies.py tests/test_w1d_postgres.py`:
  `PASS`
- `python -m pytest -q -p no:cacheprovider tests/test_w1d_contract.py tests/test_w1d_phase2_validation.py`:
  `64 passed`

These are not substitutes for the PostgreSQL wrapper. The corrected candidate remains
**live runtime NOT_RUN** until an independent read-only audit accepts the delta and a
new sealed wrapper attempt is authorized.

## 7. Required independent audit

The auditor must check both changed files against the governing plan and R12 candidate,
with special attention to:

1. canonical base64url rejection without changing valid token format, HMAC, expiry,
   recipient binding, or validation precedence;
2. PG05 mutation coverage not being weakened;
3. PG12 and PG13 using genuinely open-ended, non-overlapping end targets while retaining
   the original finite/null/empty/Unicode assertions;
4. no hidden finite-to-finite `/end` expectation remaining in the touched test regions;
5. exactly two R12 candidate paths changed and the wrapper/governing bytes stayed fixed.

The auditor must return either `APPROVE` or `REQUIRED_CHANGES`. Approval authorizes a
new candidate seal and one new exclusive wrapper attempt; it does not itself establish
runtime GREEN.
