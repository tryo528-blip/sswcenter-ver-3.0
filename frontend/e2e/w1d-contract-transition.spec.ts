/**
 * W1D live E2E: isolated PostgreSQL + real FastAPI + real frontend.
 * API mocks forbidden. Uses Playwright project viewports exactly
 * (1440x1000, 1440x900, 1366x768) — no setViewportSize overrides (J-M03).
 *
 * Three functional scenarios × three projects = 9 tests, workers=1.
 * Exactly one W1B baseline marker per project/scenario.
 */
import { expect, test, type Page } from 'playwright/test';

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
});

const LIVE = process.env.SSWCENTER_W1D_LIVE_E2E === '1';
const ADMIN_PIN = process.env.SSWCENTER_W1D_E2E_PIN ?? '';

function projectRecipientName(projectName: string, scenario: string): string {
  const override = process.env.SSWCENTER_W1D_E2E_RECIPIENT_NAME;
  const safeProject = projectName.replace(/[^A-Za-z0-9]+/g, '-');
  if (override && override.trim()) {
    return `${override.trim()}-${safeProject}-${scenario}`;
  }
  return `W1D-E2E-${safeProject}-${scenario}`;
}

/** Exact baseline-complete marker consumed by the wrapper (R5-03). */
function emitBaselineOk(projectName: string, scenario: string) {
  // eslint-disable-next-line no-console
  console.log(
    `W1D_E2E_W1B_BASELINE_OK project=${projectName.replace(/\s+/g, '-')} scenario=${scenario}`,
  );
}

test.beforeEach(() => {
  if (!LIVE) {
    throw new Error('W1D_HARNESS_E2E_LIVE_REQUIRED: set SSWCENTER_W1D_LIVE_E2E=1');
  }
  if (!ADMIN_PIN) {
    throw new Error('W1D_HARNESS_E2E_PIN_MISSING');
  }
});

async function loginLive(page: Page) {
  await page.goto('/recipients');
  const authLoading = page.getByTestId('auth-loading');
  await expect(authLoading, 'W1D_HARNESS_E2E_AUTH_LOADING_STUCK').toBeHidden({
    timeout: 20000,
  });
  const login = page.getByTestId('login-container');
  const recipients = page.getByTestId('page-recipients');
  await expect(
    login.or(recipients),
    'W1D_HARNESS_E2E_BASELINE_SURFACE_MISSING',
  ).toBeVisible({ timeout: 20000 });
  if (await login.isVisible().catch(() => false)) {
    await page.getByTestId('login-pin-input').fill(ADMIN_PIN);
    const legacyLoginSubmit = page.getByTestId('login-submit-btn');
    if (await legacyLoginSubmit.count()) await legacyLoginSubmit.click();
    await expect(authLoading, 'W1D_HARNESS_E2E_AUTH_LOADING_STUCK').toBeHidden({
      timeout: 20000,
    });
  }
  await expect(
    page.getByTestId('page-recipients'),
    'W1D_HARNESS_E2E_RECIPIENT_ROUTE_BASELINE',
  ).toBeVisible({ timeout: 20000 });
}

async function openNamedRecipient(
  page: Page,
  name: string,
  projectName: string,
  scenario: string,
) {
  await loginLive(page);
  const search = page.getByTestId('recipient-search-input');
  if (await search.isVisible().catch(() => false)) {
    await search.fill(name);
    await page.keyboard.press('Enter').catch(() => undefined);
  }
  const row = page.getByTestId('recipient-name-option').filter({ hasText: name }).first();
  await expect(row, 'W1D_HARNESS_E2E_SEEDED_RECIPIENT_MISSING').toBeVisible({
    timeout: 20000,
  });
  await row.click();
  await expect(
    page.getByTestId('recipient-detail-workspace'),
    'W1D_HARNESS_E2E_RECIPIENT_DETAIL_BASELINE',
  ).toBeVisible({ timeout: 20000 });
  emitBaselineOk(projectName, scenario);
}

/**
 * Product mounts contract / certification-transition panels only after the user
 * expands detail extras (detailExtrasOpen=false by default).
 * Expand via the real accessible control (role+name primary; testid secondary).
 */
async function expandDetailExtras(page: Page) {
  const toggle = page.getByRole('button', { name: /상세|기본정보/ });
  await expect(toggle, 'W1D_E2E_DETAIL_EXTRAS_TOGGLE_MISSING').toBeVisible({
    timeout: 10000,
  });
  // Secondary identity only — not a substitute for role/name selection.
  await expect(toggle, 'W1D_E2E_DETAIL_EXTRAS_TOGGLE_TESTID').toHaveAttribute(
    'data-testid',
    'recipient-detail-toggle',
  );
  await expect(toggle, 'W1D_E2E_DETAIL_EXTRAS_ALREADY_EXPANDED').toHaveAttribute(
    'aria-expanded',
    'false',
  );
  await toggle.click();
  await expect(toggle, 'W1D_E2E_DETAIL_EXTRAS_NOT_EXPANDED_AFTER_CLICK').toHaveAttribute(
    'aria-expanded',
    'true',
  );
  // Strict mode: do not OR unique testids — all three mount and would match together.
  const extras = page.getByTestId('recipient-detail-extra-sections');
  await expect(
    extras,
    'W1D_E2E_EXTRA_PANELS_NOT_REVEALED_AFTER_TOGGLE_EXTRAS',
  ).toBeVisible({ timeout: 10000 });
  await expect(
    page.getByTestId('recipient-contract-panel'),
    'W1D_E2E_EXTRA_PANELS_NOT_REVEALED_AFTER_TOGGLE_CONTRACT',
  ).toBeVisible({ timeout: 10000 });
  await expect(
    page.getByTestId('certification-transition-panel'),
    'W1D_E2E_EXTRA_PANELS_NOT_REVEALED_AFTER_TOGGLE_TRANSITION',
  ).toBeVisible({ timeout: 10000 });
}

test.describe('W1D live contract transition E2E', () => {
  // Scenario A: first-contract / recipient_no issuance surface.
  test('scenario-contract-create: baseline then contract surface', async ({ page }, testInfo) => {
    const scenario = 'contract-create';
    const name = projectRecipientName(testInfo.project.name, scenario);
    await openNamedRecipient(page, name, testInfo.project.name, scenario);
    await expandDetailExtras(page);
    // contract-create-form's fields are non-interactive (opacity + pointer-
    // events:none) until detailBatchEditing is entered via recipient-basic-edit;
    // the form's own submit button stays suppressed regardless of that state
    // (see the note further below where it is submitted via the batch toolbar).
    await page.getByTestId('recipient-basic-edit').click();

    const panel = page.getByTestId('recipient-contract-panel');
    await expect(panel, 'W1D_E2E_CONTRACT_PANEL_MISSING').toBeVisible({ timeout: 10000 });
    await expect(
      panel.locator('input[name="contract_no"], [data-testid="contract-no-input"]'),
      'W1D_E2E_ABS08_CONTRACT_NO',
    ).toHaveCount(0);

    const form = panel.getByTestId('contract-create-form');
    await expect(
      form.getByTestId('contract-service-type-select'),
      'W1D_E2E_CON01_SERVICE',
    ).toBeVisible();
    await form.getByTestId('contract-service-type-select').selectOption({ index: 1 });
    await form.getByTestId('contract-start-date-input').fill('2026-07-01');
    // The form's own submit is intentionally suppressed while detail batch-edit
    // mode is active (CSS + a document-level capture handler both block it);
    // contract creation goes through the consolidated batch save button, which
    // reads these same field values (see handleDetailBatchSave).
    await page
      .getByTestId('recipient-detail-batch-toolbar')
      .getByRole('button', { name: '저장' })
      .click();

    await expect
      .poll(
        async () => {
          const text = await page.getByTestId('recipient-list-recipient-no').first().textContent();
          return text ?? '';
        },
        { timeout: 15000, message: 'W1D_E2E_REC03_NUMBER_NOT_ISSUED' },
      )
      .not.toMatch(/미부여/);
  });

  // Scenario B: dual-page stale invalidation (shared fixture context inherits baseURL).
  test('scenario-transition-stale: dual-page winner then STALE', async ({ page, context }, testInfo) => {
    const scenario = 'transition-stale';
    const name = projectRecipientName(testInfo.project.name, scenario);
    await openNamedRecipient(page, name, testInfo.project.name, scenario);
    await expandDetailExtras(page);

    const transitionA = page.getByTestId('certification-transition-panel');
    await expect(transitionA, 'W1D_E2E_TRANSITION_PANEL_MISSING').toBeVisible({
      timeout: 10000,
    });

    const pageB = await context.newPage();
    try {
      await pageB.goto('/recipients');
      await expect(
        pageB.getByTestId('page-recipients'),
        'W1D_HARNESS_E2E_RECIPIENT_ROUTE_BASELINE',
      ).toBeVisible({ timeout: 20000 });
      const searchB = pageB.getByTestId('recipient-search-input');
      if (await searchB.isVisible().catch(() => false)) {
        await searchB.fill(name);
        await pageB.keyboard.press('Enter').catch(() => undefined);
      }
      const rowB = pageB
        .getByTestId('recipient-name-option')
        .filter({ hasText: name })
        .first();
      await expect(rowB, 'W1D_HARNESS_E2E_SEEDED_RECIPIENT_MISSING').toBeVisible({
        timeout: 20000,
      });
      await rowB.click();
      await expect(
        pageB.getByTestId('recipient-detail-workspace'),
        'W1D_HARNESS_E2E_RECIPIENT_DETAIL_BASELINE',
      ).toBeVisible({ timeout: 20000 });
      await expandDetailExtras(pageB);

      const transitionB = pageB.getByTestId('certification-transition-panel');
      await expect(transitionB, 'W1D_E2E_TRANSITION_PANEL_MISSING').toBeVisible({
        timeout: 10000,
      });

      // R12-03: all five transition controls required; no silent skip.
      const yearByProject: Record<string, number> = {
        'chromium-1440x1000': 2030,
        'chromium-1440x900': 2031,
        'chromium-1366x768': 2032,
      };
      const y = yearByProject[testInfo.project.name] ?? 2030;
      const fillTransitionRequired = async (panel: typeof transitionA) => {
        const start = panel.getByTestId('transition-new-start-date');
        const end = panel.getByTestId('transition-new-end-date');
        const grade = panel.getByTestId('transition-new-grade-code');
        const gStart = panel.getByTestId('transition-new-grade-start-date');
        const gEnd = panel.getByTestId('transition-new-grade-end-date');
        await expect(start, 'W1D_E2E_TRN_CONTROL_START_MISSING').toBeVisible({
          timeout: 10000,
        });
        await expect(end, 'W1D_E2E_TRN_CONTROL_END_MISSING').toBeVisible({
          timeout: 10000,
        });
        await expect(grade, 'W1D_E2E_TRN_CONTROL_GRADE_MISSING').toBeVisible({
          timeout: 10000,
        });
        await expect(gStart, 'W1D_E2E_TRN_CONTROL_GRADE_START_MISSING').toBeVisible({
          timeout: 10000,
        });
        await expect(gEnd, 'W1D_E2E_TRN_CONTROL_GRADE_END_MISSING').toBeVisible({
          timeout: 10000,
        });
        await start.fill(`${y}-07-01`);
        await end.fill(`${y + 1}-06-30`);
        await grade.selectOption({ value: '4' });
        await gStart.fill(`${y}-07-01`);
        await gEnd.fill(`${y + 1}-06-30`);
      };
      await fillTransitionRequired(transitionA);
      await fillTransitionRequired(transitionB);

      const isPreviewPost = (response: {
        url: () => string;
        request: () => { method: () => string };
      }) => {
        try {
          const pathname = new URL(response.url()).pathname;
          return (
            pathname.includes('/certification-transitions/preview') &&
            response.request().method() === 'POST'
          );
        } catch {
          return false;
        }
      };
      const isApplyPost = (response: {
        url: () => string;
        request: () => { method: () => string };
      }) => {
        try {
          const pathname = new URL(response.url()).pathname;
          return (
            pathname.includes('/certification-transitions/apply') &&
            response.request().method() === 'POST'
          );
        } catch {
          return false;
        }
      };

      const previewAPromise = page.waitForResponse(isPreviewPost, { timeout: 30000 });
      await transitionA.getByTestId('transition-preview-button').click();
      const previewAResp = await previewAPromise;
      expect(previewAResp.status(), 'W1D_E2E_TRN01_PREVIEW_A_STATUS').toBe(200);
      const previewABody = (await previewAResp.json()) as Record<string, unknown>;
      await expect(
        transitionA.getByTestId('transition-impact-list'),
        'W1D_E2E_TRN01_IMPACT',
      ).toBeVisible();
      await transitionA.getByTestId('transition-confirm-checkbox').check();

      const previewBPromise = pageB.waitForResponse(isPreviewPost, { timeout: 30000 });
      await transitionB.getByTestId('transition-preview-button').click();
      const previewBResp = await previewBPromise;
      expect(previewBResp.status(), 'W1D_E2E_TRN01_PREVIEW_B_STATUS').toBe(200);
      const previewBBody = (await previewBResp.json()) as Record<string, unknown>;
      await expect(
        transitionB.getByTestId('transition-impact-list'),
        'W1D_E2E_TRN01_IMPACT',
      ).toBeVisible();
      await transitionB.getByTestId('transition-confirm-checkbox').check();

      // R9 OBS-01: strict raw JSON type/value assertions (no Number()/String() coerce).
      const isStrictPosInt = (v: unknown): v is number =>
        typeof v === 'number' && Number.isInteger(v) && v > 0 && !Object.is(v, -0);
      const assertPreviewBody = (body: Record<string, unknown>, label: string) => {
        const affected = body.affected_contract_ids;
        expect(Array.isArray(affected), `${label}_AFFECTED_CONTRACT_IDS_TYPE`).toBe(true);
        const affectedArr = affected as unknown[];
        expect(affectedArr.length, `${label}_AFFECTED_CONTRACT_IDS_LEN`).toBe(2);
        expect(
          affectedArr.every((id) => isStrictPosInt(id)),
          `${label}_AFFECTED_CONTRACT_IDS_MEMBERS`,
        ).toBe(true);
        expect(new Set(affectedArr as number[]).size, `${label}_AFFECTED_UNIQUE`).toBe(2);
        const multiset = body.service_multiset;
        expect(Array.isArray(multiset), `${label}_SERVICE_MULTISET_TYPE`).toBe(true);
        const ms = multiset as unknown[];
        expect(
          ms.every((v) => typeof v === 'string'),
          `${label}_SERVICE_MULTISET_STRINGS`,
        ).toBe(true);
        const sortedMs = [...(ms as string[])].sort();
        expect(sortedMs, `${label}_SERVICE_MULTISET`).toEqual(['HOME_BATH', 'HOME_CARE']);
        const replacements = body.replacement_preview;
        expect(
          Array.isArray(replacements) && replacements.length === 2,
          `${label}_REPLACEMENT_PREVIEW_COUNT`,
        ).toBe(true);
        if (Array.isArray(replacements)) {
          const services = replacements
            .map((item) => {
              if (!item || typeof item !== 'object') return null;
              const code = (item as Record<string, unknown>).service_type_code;
              return typeof code === 'string' ? code : null;
            })
            .filter((v): v is string => v !== null)
            .sort();
          expect(services, `${label}_REPLACEMENT_SERVICES`).toEqual([
            'HOME_BATH',
            'HOME_CARE',
          ]);
        }
        const hash = body.canonical_hash;
        expect(
          typeof hash === 'string' &&
            hash.length === 64 &&
            /^[0-9a-f]{64}$/.test(hash),
          `${label}_CANONICAL_HASH`,
        ).toBe(true);
        expect(body.serialization_version, `${label}_VERSION`).toBe('w1d-transition-v1');
      };
      assertPreviewBody(previewABody, 'W1D_E2E_TRN01_PREVIEW_A');
      assertPreviewBody(previewBBody, 'W1D_E2E_TRN01_PREVIEW_B');
      expect(
        previewABody.canonical_hash,
        'W1D_E2E_TRN01_PREVIEW_HASH_MISMATCH',
      ).toBe(previewBBody.canonical_hash);
      const affectedA = [
        ...((previewABody.affected_contract_ids as number[]) ?? []),
      ].sort((a, b) => a - b);
      const affectedB = [
        ...((previewBBody.affected_contract_ids as number[]) ?? []),
      ].sort((a, b) => a - b);
      expect(affectedA, 'W1D_E2E_TRN01_PREVIEW_AFFECTED_MISMATCH').toEqual(affectedB);

      const applyA = transitionA.getByTestId('transition-apply-button');
      await expect(applyA, 'W1D_E2E_TRN01_APPLY_STILL_DISABLED').toBeEnabled();
      const applyARespPromise = page.waitForResponse(isApplyPost, { timeout: 30000 });
      await applyA.click();
      const applyAResp = await applyARespPromise;
      // M01/M03: exact sealed apply success status is 200 only.
      expect(applyAResp.status(), 'W1D_E2E_TRN04_APPLY_SUCCESS_STATUS').toBe(200);
      const applyABody = (await applyAResp.json()) as Record<string, unknown>;
      // R21: exact positive integers + canonical UUID string (no Number() coercion).
      const corr = applyABody.audit_correlation_id;
      expect(
        typeof corr === 'string' &&
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(corr),
        'W1D_E2E_TRN04_APPLY_CORRELATION_UUID',
      ).toBe(true);
      expect(
        isStrictPosInt(applyABody.new_certification_period_id),
        'W1D_E2E_TRN04_APPLY_NEW_CERT_ID',
      ).toBe(true);
      expect(
        isStrictPosInt(applyABody.new_grade_period_id),
        'W1D_E2E_TRN04_APPLY_NEW_GRADE_ID',
      ).toBe(true);
      const newContractIds = applyABody.new_contract_ids;
      expect(
        Array.isArray(newContractIds) &&
          newContractIds.length === 2 &&
          newContractIds.every((id) => isStrictPosInt(id)) &&
          new Set(newContractIds as number[]).size === 2,
        'W1D_E2E_TRN04_APPLY_NEW_CONTRACT_IDS',
      ).toBe(true);
      // Live readback against real contract item API for each new id.
      const recipientId = applyABody.recipient_id;
      expect(isStrictPosInt(recipientId), 'W1D_E2E_TRN04_APPLY_RECIPIENT_ID').toBe(true);
      for (const cid of newContractIds as number[]) {
        const getResp = await page.request.get(
          `/api/v1/recipients/${recipientId}/contracts/${cid}`,
        );
        expect(getResp.status(), 'W1D_E2E_TRN04_CONTRACT_GET_STATUS').toBe(200);
        const getBody = (await getResp.json()) as Record<string, unknown>;
        expect(isStrictPosInt(getBody.id), 'W1D_E2E_TRN04_CONTRACT_GET_ID_TYPE').toBe(
          true,
        );
        expect(getBody.id, 'W1D_E2E_TRN04_CONTRACT_GET_ID').toBe(cid);
      }
      await expect(transitionA.getByTestId('transition-partial-success')).toHaveCount(0);

      const applyB = transitionB.getByTestId('transition-apply-button');
      await expect(applyB, 'W1D_E2E_TRN01_APPLY_STILL_DISABLED').toBeEnabled();
      const applyBRespPromise = pageB.waitForResponse(isApplyPost, { timeout: 30000 });
      await applyB.click();
      const applyBResp = await applyBRespPromise;
      expect(applyBResp.status(), 'W1D_E2E_TRN03_STALE_HTTP_STATUS').toBe(409);
      const staleBody = (await applyBResp.json()) as {
        error?: { code?: string };
        detail?: unknown;
      };
      expect(staleBody.detail, 'W1D_E2E_TRN03_STALE_LEGACY_DETAIL_FORBIDDEN').toBeUndefined();
      expect(staleBody.error?.code, 'W1D_E2E_TRN03_STALE_CODE').toBe(
        'CERTIFICATION_TRANSITION_STALE',
      );

      await expect(
        transitionB.getByTestId('transition-stale-banner'),
        'W1D_E2E_TRN03_STALE_BANNER_MISSING',
      ).toBeVisible({ timeout: 15000 });
      const confirmB = transitionB.getByTestId('transition-confirm-checkbox');
      await expect(confirmB, 'W1D_E2E_TRN03_CONFIRM_NOT_CLEARED').not.toBeChecked();
      await expect(applyB, 'W1D_E2E_TRN03_APPLY_NOT_DISABLED').toBeDisabled();
      await expect(
        transitionB.getByTestId('transition-impact-list'),
        'W1D_E2E_TRN03_PREVIEW_NOT_DISCARDED',
      ).toHaveCount(0);
      await expect(
        transitionB.getByText(/다시 미리보기|미리보기/),
        'W1D_E2E_TRN03_REPREVIEW_GUIDANCE_MISSING',
      ).toBeVisible();
      await expect(
        transitionB.getByTestId('transition-preview-button'),
        'W1D_E2E_TRN03_REPREVIEW_CONTROL_MISSING',
      ).toBeVisible();
    } finally {
      await pageB.close().catch(() => undefined);
    }
  });

  // Scenario C: ended contract shows new-contract-only flow (no reactivate).
  test('scenario-ended-new-only: ended contract new-contract flow', async ({ page }, testInfo) => {
    const scenario = 'ended-new-only';
    const name = projectRecipientName(testInfo.project.name, scenario);
    await openNamedRecipient(page, name, testInfo.project.name, scenario);
    await expandDetailExtras(page);
    // contract-create-form's fields are non-interactive (opacity + pointer-
    // events:none) until detailBatchEditing is entered via recipient-basic-edit;
    // the form's own submit button stays suppressed regardless of that state.
    await page.getByTestId('recipient-basic-edit').click();

    const panel = page.getByTestId('recipient-contract-panel');
    await expect(panel, 'W1D_E2E_CONTRACT_PANEL_MISSING').toBeVisible({ timeout: 10000 });
    // Wait for the seeded ended contract (2025-01-01~2025-06-30) to actually
    // load before asserting on reactivate/new-contract affordances — the
    // create form's fields render unconditionally regardless of list-load
    // state, so asserting on them alone would pass even if the ended-contract
    // row never arrived.
    await expect(
      panel.getByTestId('contract-list').getByText('2025-01-01 ~ 2025-06-30'),
      'W1D_E2E_CON03_ENDED_CONTRACT_ROW_MISSING',
    ).toBeVisible({ timeout: 10000 });
    await expect(
      panel.getByTestId('contract-reactivate-button'),
      'W1D_E2E_CON03_REACTIVATE',
    ).toHaveCount(0);
    // The individual submit button (contract-new-button) stays suppressed
    // regardless of detail batch-edit mode (see scenario-contract-create);
    // the new-contract affordance is the create form's own fields, which
    // detailBatchEditing makes interactive and which submit through the
    // consolidated batch save button.
    await expect(
      panel.getByTestId('contract-create-form').getByTestId('contract-service-type-select'),
      'W1D_E2E_CON03_NEW_CONTRACT_FLOW',
    ).toBeVisible();
  });
});
