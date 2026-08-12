# W1D Opus P2B correction audit R1

- Auditor: Claude Opus via Claude Code `2.1.217`
- Mode: independent read-only workspace audit
- Branch: `codex/w1d-contract-transition`
- HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- Result: **APPROVE**
- Meaning: one new sealed exclusive wrapper attempt is authorized; runtime GREEN
  and W1D PASS are not established by this report

## Invocation boundary

- model: `opus`
- effort: `high`
- permission mode: `dontAsk`
- allowed tools: `Read`, `Grep`, `Glob`
- denied tools: `Bash`, `Edit`, `Write`, `NotebookEdit`, `Agent`, `Task`,
  `WebFetch`, `WebSearch`
- safe mode and no session persistence enabled
- parent exit: `0`
- permission denials: `0`
- web requests: `0`
- turns: `13`
- reported cost: `$1.090573`

## Candidate reviewed

| Path | SHA-256 | Bytes |
|---|---|---:|
| `backend/app/domains/w1d/policies.py` | `5c0610f117a514db81b9d187093ea7a9c7865e049552ad56c9787c1b7b8909e3` | 8572 |
| `backend/tests/test_w1d_postgres.py` | `5d973b706b3562637e4387c356c3d8a65d8a7f0050bdf8c1b0530964861536e2` | 307587 |

The auditor relied on Regina's independent byte seal for SHA-256 equality and read
the source semantics directly from the workspace.

## Findings

No blocking or correctness findings were reported.

1. Canonical unpadded base64url validation correctly rejects alternate textual
   encodings before HMAC acceptance while preserving minted token format, HMAC
   SHA-256, constant-time comparison, expiry, recipient binding, and apply
   precedence.
2. PG05 now overrides one mutation field through one dictionary and preserves all
   nine replacement-field mismatch dimensions without duplicate keywords.
3. PG12 preserves the finite create/get/list/database round trip and uses a separate
   open-ended, non-overlapping contract for successful end and stale row-version
   behavior.
4. PG13 preserves omit/null/empty and Unicode assertions, uses open-ended targets
   for empty and Unicode end reasons, and introduces no period overlap.
5. No expected status, error envelope, write-zero assertion, or test branch was
   weakened or skipped.
6. The handoff correctly keeps attempt-1 runtime RED, local correction PASS, and
   corrected-candidate runtime NOT_RUN distinct.

## Residual runtime risk

- PG05/07/12/13 corrected behavior remains live runtime NOT_RUN.
- PG12's stale assertion intentionally depends on row-version conflict precedence;
  any product ordering drift must surface as a new RED, not be normalized away.
- SHA-256 and cleanup evidence remain Regina-owned checks.

## Authorized next action

Re-seal the two changed files and unchanged wrapper/governing paths, confirm zero
listeners/processes/temp/artifacts, and run exactly one new sequential exclusive
PostgreSQL wrapper attempt on ports `55442`, `18092`, `14192` with `workers=1`.

`OPUS_W1D_P2B_CORRECTION_AUDIT_R1_RESULT=APPROVE`
