# W1D P2B attempt 2 GREEN handoff

- Owner: Regina
- Branch: `codex/w1d-contract-transition`
- HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- Attempt: corrected candidate, live wrapper attempt 2
- Post-run seal: `2026-07-31T10:49:02.0290723Z`
- Status: **wrapper GREEN observed; independent runtime audit pending**

## 1. Authorization and candidate

Opus R1 approved exactly one new sealed wrapper attempt:

`OPUS_W1D_P2B_CORRECTION_AUDIT_R1_RESULT=APPROVE`

The approved changed files were:

| Path | SHA-256 | Bytes |
|---|---|---:|
| `backend/app/domains/w1d/policies.py` | `5c0610f117a514db81b9d187093ea7a9c7865e049552ad56c9787c1b7b8909e3` | 8572 |
| `backend/tests/test_w1d_postgres.py` | `5d973b706b3562637e4387c356c3d8a65d8a7f0050bdf8c1b0530964861536e2` | 307587 |

The other 30 non-office R12 paths were byte-identical. Fixed governing bytes:

- wrapper SHA-256: `0a1a459f2fabf99ad02e55e18291fd215c403ad1438c28f182807a2357c3c155`
- plan SHA-256: `155812301b5e30cc88089bd537278166a4a900a6b4528da92de218c2875c15d1`
- R12 report SHA-256: `4b60c8c4608f176ae4df68680bb8b6299c2686e172fd4587247a9e36a0198265`

Immediate preflight found wrapper parse errors `0`, listeners `0`, workspace runtime
processes `0`, W1D temp directories `0`, and prior frontend artifacts absent.

## 2. Exact invocation

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\test-w1d-postgres.ps1 -Port 55442 -BackendPort 18092 -FrontendPort 14192
```

The wrapper invoked Playwright with `workers=1` and ran sequentially/exclusively.

## 3. Runtime result

- parent exit: `0`
- observed migration head: `20260730_0011_w1d_recipient_contract`
- application role: `W1D_APP_ROLE_OK`
- migration sequence: base-to-head upgrade, W1D downgrade to W1C head, W1D re-upgrade
- harness self-check: `1 passed`, `18 deselected`, exit `0`
- PG00 stage: `1 passed`, `18 deselected`, exit `0`
- PostgreSQL product remainder: `17 passed`, `2 deselected`, exit `0`
- browser E2E: `9 passed`, exit `0`
- E2E baseline marker count: `9`
- accepted final marker: `W1D_POSTGRES_GREEN`
- wrapper parent marker: `W1D_ATTEMPT2_WRAPPER_PARENT_EXIT=0`

The only repeated warning was Starlette's deprecation warning for the current
`httpx`/`TestClient` integration. It did not change stage exits or counts.

## 4. Wrapper cleanup markers

```text
W1D_CLEANUP_PW_TEST_RESULTS_REMOVED
W1D_CLEANUP_LISTENERS pg=0 backend=0 frontend=0
W1D_CLEANUP_PROCESSES pg=0 backend=0 frontend=0
W1D_CLEANUP listener=0 process=0 temp=0 artifact=0 artifact_removed=1
W1D_POSTGRES_GREEN
```

The GREEN marker occurred after the cleanup markers.

## 5. Independent post-run checks

After the wrapper exited:

- listeners on `55442`, `18092`, `14192`: `0`, `0`, `0`
- workspace PostgreSQL/Python/Node/Claude processes: `0`
- `%TEMP%\sswcenter-w1d-pg-*` directories: `0`
- `frontend/dist`: absent
- `frontend/test-results`: absent
- `frontend/playwright-report`: absent
- branch and HEAD unchanged
- both corrected file hashes unchanged from the R1-approved seal
- wrapper, plan, and R12 report hashes unchanged
- R12 identity comparison remained exactly `30` unchanged plus the same `2`
  approved changed paths

## 6. Audit boundary

This handoff supports a P2B runtime GREEN determination only after an independent
auditor verifies that the wrapper's marker order is fail-closed and that the counts,
exit, cleanup, and candidate identity are internally consistent. It does not by itself
authorize staging, commit, push, merge, or broader W1D closeout.

Required terminal marker:

- `OPUS_W1D_P2B_RUNTIME_AUDIT_R2_RESULT=APPROVE`, or
- `OPUS_W1D_P2B_RUNTIME_AUDIT_R2_RESULT=REQUIRED_CHANGES`
