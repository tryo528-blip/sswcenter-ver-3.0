# W1B-F2 RED Evidence

## Correction identity and scope

- F2 correction identifier: `W1B-F2-RED-R1-REQUIRED-OPTION-SET-20260729`
- Workstream: `W1B-F2-RED`
- Packet: `review/packets/W1B_ASSIGNMENT_PACKET_v1.0.md`
- Basis HEAD: `e204023a7277e486018f3057653fe8aebf7b7fcf`
- This is a sealed RED correction after R1 Marco round 1 `REQUIRED_CHANGES`.
- F2 write scope is exactly these three files:
  - `frontend/src/test/W1BRecipientsRed.test.tsx`
  - `frontend/e2e/w1b-recipients-red.spec.ts`
  - `review/evidence/w1b/F2_RED.md`
- No product code, generated TypeScript, Playwright config, backend, canonical document,
  packet, dependency, or Git history was changed by F2. A concurrent B2 change at
  `backend/tests/test_w1b_red.py` is preserved and is not part of this F2 correction.
- All fixtures remain synthetic (`TEST_RECIPIENT_*`, `TEST_GUARDIAN_*`, `TEST_ADMIN`).

## RED contract correction

The existing required-fields test remains one Vitest test and one Playwright contract;
the suite remains 8 Vitest tests and 7 browser contracts. The correction adds semantic
gates rather than another test.

- Recipient `name`, `birth_date`, and `sex_code` must expose required semantics.
  Vitest uses `toBeRequired`; Playwright evaluates rendered controls for native
  `:required` or `aria-required="true"`.
- Recipient `postal_code`, `address`, `home_phone`, and `mobile_phone` must not expose
  required semantics in either runner.
- The current RED surface covers `guardian-phone-input`; it remains optional in both
  runners. Guardian address/relationship controls are not currently surfaced by this
  RED contract, so no new selectors were invented. Guardian name-only remains the
  canonical handoff contract when that surface is implemented.
- Both runners inspect the rendered `sex_code` option controls and require the exact
  value set `MALE` and `FEMALE`; fixture values alone are not used as proof. Sorting is
  only for order independence, while the exact two-value array rejects `TEST`, empty,
  duplicate, or any other option.

### Added gate locations

- Vitest required/optional semantics: `frontend/src/test/W1BRecipientsRed.test.tsx:152-158`.
- Vitest rendered `sex_code` option set: `frontend/src/test/W1BRecipientsRed.test.tsx:160-163`.
- Vitest existing guardian optional-phone surface: `frontend/src/test/W1BRecipientsRed.test.tsx:208-212`.
- Playwright required-semantics helper: `frontend/e2e/w1b-recipients-red.spec.ts:48-52`.
- Playwright required/optional semantics: `frontend/e2e/w1b-recipients-red.spec.ts:165-191`.
- Playwright rendered `sex_code` option set: `frontend/e2e/w1b-recipients-red.spec.ts:192-194`.
- Playwright existing guardian optional-phone surface: `frontend/e2e/w1b-recipients-red.spec.ts:234-238`.

Previously closed contracts remain in place: create POST has no `recipient_no` key;
`NULL` recipient numbers display exact `미부여`; the list root and detail-workspace
root each reject all three existing recipient-number selector families; the real
recipient browser request has no recipient mock; native `page.goBack()` is retained
for list context; payer-type absence is checked only after payer surface presence;
detail stays in the same workspace; `window.open`/popup count remains zero; and the
selective mock contracts remain separate from the real-PG handoff.

## Validation

### Vitest

Exact command, run from `frontend`:

```text
npm.cmd exec -- vitest run src/test/W1BRecipientsRed.test.tsx --environment jsdom
```

Observed result: `exit 1`.

- Test files: `1 failed`.
- Tests: `8 failed / 8 total`.
- Passed: `0`.
- Skipped: `0`.
- First named marker: `W1B_F2_API_RECIPIENT_LIST_MISSING`.
- Collection/config/environment error: `0 observed`.

The placeholder product fails the existing product-absence marker before the newly
added field-semantic and option-set assertions; those later assertions are staged RED
contracts, not product PASS evidence.

### Playwright

Exact command, run from `frontend`:

```text
npm.cmd exec -- playwright test e2e/w1b-recipients-red.spec.ts
```

Observed runner result: `exit 124` from the local command timeout after `240416 ms`.
The runner printed `Running 21 tests using 1 worker` and executed all 21 contracts:
7 contracts in each of `chromium-1440x1000`, `chromium-1440x900`, and
`chromium-1366x768`; all 21 were failures (`21/21`), with `0` passed and `0`
skipped. No collection, configuration, or browser-start error was observed. The
runner teardown timeout described below was observed, so this evidence does not
claim the expected clean Playwright exit code or an environment-clean run.

- First named marker confirmed in the generated failure context:
  `W1B_F2_API_RECIPIENT_LIST_MISSING_REAL_BROWSER_REQUEST`.
- The timeout is a runner teardown/environment blocker after the 21 failures, not a
  product GREEN result.

P0 later attempted one controlled recheck with `--workers=1` and the unique output
path `C:\tmp\sswcenter-w1b-playwright-p0-20260729-2005`. The call exceeded the
300-second bound without returning buffered runner output, and the unique artifact
directory was not created. P0 stopped only that invocation and then removed only its
two exact launch-time child PIDs (`25208`, `26364`); both were confirmed absent
afterward. This recheck is `INCONCLUSIVE_ENVIRONMENT` and does not replace or weaken
the earlier 21/21 executed RED evidence. No unrelated or older Node process was
terminated, and no ACL, TEMP, Playwright config, dependency, or global setting was
changed.

### TypeScript

Exact no-emit check, run from `frontend`:

```text
npm.cmd exec -- tsc --noEmit -p tsconfig.app.json --pretty false
```

Observed result: `exit 0`.

### Diff and Git checks

The required `git diff --check` was run against the three F2-owned files after the
evidence update:

```text
git diff --check -- frontend/src/test/W1BRecipientsRed.test.tsx frontend/e2e/w1b-recipients-red.spec.ts review/evidence/w1b/F2_RED.md
exit 0
```

The product-path diff check (`backend/app/**`, `backend/alembic/**`, and frontend
product/generated source paths) returned no paths, exit `0`. No stage, commit, push,
pull, reset, rebase, checkout, stash, dependency install, or PostgreSQL harness was
run.

## Handoff and deferred gates

- RED status: `RED_VALID_PENDING_PRODUCT`.
- Real PostgreSQL create/readback: `NOT_RUN_PENDING_PRODUCT`.
- Focused 3-viewport GREEN against implemented product: `NOT_RUN_PENDING_PRODUCT`.
- `REC-03` full issuance/competition/rollback: `NOT_RUN / DEFERRED_TO_W1D`.
- `SIG-01` full: `NOT_RUN / DEFERRED_TO_W1D`; the absence guard is not an ID PASS/SKIP.
- The Vitest fetch stub and selective Playwright recipient mocks are synthetic staged
  contracts only. The dedicated real recipient request remains unmocked; no mock result
  is claimed as real API or real-PG evidence.
- Next handoff is the remaining Grok/Marco/Regina read-only RED review chain. B1/F1
  product implementation remains locked until that chain approves; focused GREEN and
  real-PG/browser validation then remain required before `W1B_PASS`.
