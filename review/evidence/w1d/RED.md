# W1D Phase 1 RED Evidence — Regina R25 (RED_VALID_PENDING_DESIGN_AUDIT)

## Identity

- Workspace: `C:\sswcenter\2.1`
- Branch: `codex/w1d-contract-transition`
- HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- Phase: design + executable RED only
- R25 mode: **static-only / evidence + I001 import-order correction**
- Status: `RED_VALID_PENDING_DESIGN_AUDIT` — not Phase-1 approval, not product GREEN

## Terminal marker

```text
GROK_W1D_PHASE1_CORRECTION_R25_RESULT=RED_VALID_PENDING_DESIGN_AUDIT
```

Not Phase-1 approval. Not product GREEN. Not implementation authorization.
No live coverage, product implementation, or cleanup certification claim.

## Joseph R8 (retained; report not edited)

```text
review/reports/W1D_JOSEPH_DESIGN_AUDIT_R8_R23_266BEEA.md
sha256=00cc14adf70de614ff779548a1c5269607e1783925fa9da678ac66823f416967
bytes=17658
JOSEPH_W1D_REAUDIT_R8_RESULT=REQUIRED_CHANGES
```

R24 closed the active pg_05 audit and ContractResponse H02 false-pass classes
in executable RED. Those code semantics are retained.

## R25 correction (Regina R24 STATIC_I001)

Office decision: `REGINA_W1D_R24_INTEGRATION_RESULT=REQUIRED_CHANGES_STATIC_I001`.

**False R24 claim retracted:** R24 RED stated the pg_10 fault import I001 was
“fixed (w1c before w1d)” and that Ruff passed. Independent Regina Ruff from
`backend` with:

```text
.venv\Scripts\python.exe -B -m ruff check --no-cache --config pyproject.toml
tests/test_w1d_contract.py tests/test_w1d_postgres.py
```

returned **I001 exit 1** on the w1c-before-w1d order.

**R25 code delta (only this import block):**

```text
from app.domains.w1d import fault as w1d_fault  # type: ignore

from app.domains.w1c.schemas import (
    ...
)
from app.domains.w1c.service import W1CService
```

R25 independent rerun of the same Ruff command: **All checks passed; exit 0**.
No behavior change. No other code change.

## Joseph R7 — same-path two-version race (retained)

| Identity | SHA-256 | bytes | Verdict |
|---|---|---:|---|
| First version | `f4db172fc6207184596a24293495fb451edf058c628b2f2e9d7613e04f8e3a0e` | 24839 | REQUIRED_CHANGES (HTTP P1) |
| Current path | `6615282b4e36a4b72c111b63fdfb85afae5c423126ad897ba673211ecc0acdce` | 15229 | REQUIRED_CHANGES (audit non-JSON + B2) |

## Allowed R25 edit paths (exactly three)

1. `backend/tests/test_w1d_postgres.py` — import-order only
2. `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md`
3. `review/evidence/w1d/RED.md`

Frozen at R24 seals: wrapper, contract test, Vitest, E2E. No office/report/packet/product edits.

## R24 semantics retained

| Area | Status |
|---|---|
| pg_05 shared exact-audit predicate | retained |
| ContractResponse strict 14-key H02 | retained |
| R24 pure mutants | retained |
| Seed H01–H04/M01 + no default=str API↔DB | retained (wrapper frozen) |

## Cleanup / residual honesty (static-only)

- No R25 live cleanup or residual certification.
- R14 cleanup is historical only.
- Existing `backend/.pytest_cache` observation remains historical/ENV only.
- Root `node_modules` and named generated artifact paths absent only as read-only observations.
- **No current runtime-zero claim.**

## History

R13 INVALID · R14 live historical · R16–R20 REQUIRED_CHANGES · R21–R22 static ·
R23 evidence-only · R8 REQUIRED_CHANGES · R24 static package
(Regina REQUIRED_CHANGES_STATIC_I001) · R25 this reseal

## Problems observed

1. R24 independent Ruff I001 exit 1 on w1c-before-w1d — corrected to w1d-before-w1c.
2. R24 false evidence about I001 “passed” — retracted here.
3. Playwright: Node warning `NO_COLOR` ignored due to `FORCE_COLOR` (non-fatal, if shown).
4. pytest/pure import: StarletteDeprecationWarning TestClient/httpx (non-fatal).
5. No product/live/Git mutation in R25.

## Final R25 static evidence

```text
UTF8_BOM_FAIL_COUNT=0 TRAIL_WS_COUNT=0
PS_AST=OK
PY_AST_COMPILE contract+postgres EXIT=0
SEED_AST_COMPILE_OK bytes=46073 lines=1100 chars=46055 SEED_AST_EXIT=0 start=505 first=506 end=1606
RUFF=0 --no-cache (backend: python -B -m ruff check --config pyproject.toml)
pytest -B -q -p no:cacheprovider --collect-only=28 EXIT=0
Playwright list=9 tests in 1 file workers=1 EXIT=0
GIT_DIFF_CHECK=0 HEAD=266beeaa… tracked/staged 0/0 untracked=18 PRODUCT_0011=0
DIRECT_MUTANT_RESULT=PASS
NO LIVE
```

## Final seven SHA-256 / bytes

```text
155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1  review/plans/W1D_CONTRACT_TRANSITION_PLAN.md  bytes=56890
b74b68c3c52dd57a66350d4a36583ee1891fc685b59c26c699838c7effa9c644  backend/tests/test_w1d_postgres.py  bytes=304628
0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155  scripts/test-w1d-postgres.ps1  bytes=83648
92d115181c087362cd6cc12f00e0f5efdef38698ce59e1b8a782537a9e074623  backend/tests/test_w1d_contract.py  bytes=31949
a70935c789332bfede8341a94b81194b8e32d4af176abda89674a023b7f058d7  frontend/src/test/W1DContractTransition.test.tsx  bytes=17518
24e83e1cbd65ca42deb0e6ec7b66297585098564076d2a8b6be52adb18a5971a  frontend/e2e/w1d-contract-transition.spec.ts  bytes=17341
```

RED self-hash reported in writer return only.
Changed from R24: plan, RED, postgres (import-order only). Frozen four seals exact.

## Residual risks

Product absent until 0011. No product GREEN.
