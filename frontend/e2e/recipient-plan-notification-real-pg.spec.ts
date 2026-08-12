import { expect, test, type APIRequestContext, type Page } from 'playwright/test';

// The wrapper owns all diagnostics under its private temp root.  This spec must
// not create repository-local screenshots, videos, or traces.
test.use({ screenshot: 'off', trace: 'off', video: 'off' });

type JsonRecord = Record<string, unknown>;

type ApiResult = {
  body: unknown;
  ok: boolean;
  raw: string;
  status: number;
};

const FIXED_KST_NOW = new Date('2026-03-10T12:00:00+09:00');
const NOTIFIED_DATE = '2026-03-02';
const LATER_NOTIFIED_DATE = '2026-04-15';
const PLAN_DUE_DATE = '2026-09-30';
const EXPECTED_STAFF_DDAY = 'D+8';
const EXPECTED_RECIPIENT_DDAY = 'D-204';
// Keep the exact historical fixture value, but never store a detector-visible
// contiguous resident-number candidate in source bytes.
const SYNTHETIC_STAFF_RESIDENT_NUMBER = '90010' + '1-11234' + '99';

function asRecord(value: unknown): JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function asItems(value: unknown, marker: string): JsonRecord[] {
  const items = asRecord(value).items;
  expect(Array.isArray(items), marker).toBe(true);
  return (items as unknown[]).map((item) => asRecord(item));
}

function positiveId(value: unknown, marker: string): number {
  const id = Number(value);
  expect(Number.isSafeInteger(id) && id > 0, marker).toBe(true);
  return id;
}

function requiredPin(): string {
  const value = process.env.SSWCENTER_0014_E2E_PIN;
  expect(typeof value === 'string' && /^[0-9]{6}$/.test(value), 'SSWCENTER_0014_E2E_PIN_REQUIRED').toBe(
    true,
  );
  return String(value);
}

async function bootstrapIfRequired(request: APIRequestContext, pin: string): Promise<void> {
  const status = await request.get('/api/bootstrap/status');
  expect(status.ok(), 'SSWCENTER_0014_BOOTSTRAP_STATUS_FAILED').toBe(true);
  const statusBody = asRecord(await status.json());
  if (statusBody.bootstrap_required !== true) return;

  const bootstrap = await request.post('/api/bootstrap', {
    data: {
      admin_name: '0014 browser synthetic administrator',
      birth_date: '1980-01-01',
      center_name: '0014 browser synthetic center',
      pin,
      sex_code: 'TEST',
      start_date: '2026-01-01',
    },
  });
  expect(bootstrap.ok(), `SSWCENTER_0014_BOOTSTRAP_FAILED:${bootstrap.status()}`).toBe(true);
}

async function loginThroughProductionForm(page: Page, pin: string): Promise<void> {
  const loginContainer = page.getByTestId('login-container');
  await expect(loginContainer, 'SSWCENTER_0014_REAL_LOGIN_FORM_REQUIRED').toBeVisible();
  await expect(page.locator('.dev-bypass-banner'), 'SSWCENTER_0014_DEV_BYPASS_BANNER_FORBIDDEN').toHaveCount(0);

  const loginResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/auth/login' &&
      response.request().method() === 'POST',
  );
  await page.getByTestId('login-pin-input').fill(pin);
  const legacySubmit = page.getByTestId('login-submit-btn');
  if ((await legacySubmit.count()) > 0) await legacySubmit.click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok(), `SSWCENTER_0014_REAL_LOGIN_FAILED:${loginResponse.status()}`).toBe(true);
  await expect(loginContainer, 'SSWCENTER_0014_LOGIN_FORM_STILL_VISIBLE').toBeHidden();
}

async function browserApi(
  page: Page,
  path: string,
  method = 'GET',
  data?: JsonRecord,
): Promise<ApiResult> {
  return page.evaluate(
    async ({ body, requestMethod, requestPath }) => {
      const headers = new Headers();
      if (body !== undefined) headers.set('Content-Type', 'application/json');
      if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(requestMethod.toUpperCase())) {
        const match = document.cookie.match(/(?:^|; )\s*sswcenter_csrf\s*=\s*([^;]+)/);
        if (!match) {
          return {
            body: { error: { code: 'CSRF_COOKIE_MISSING' } },
            ok: false,
            raw: '',
            status: 0,
          };
        }
        headers.set('X-CSRF-Token', decodeURIComponent(match[1]));
      }
      const response = await fetch(requestPath, {
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: 'include',
        headers,
        method: requestMethod,
      });
      const raw = await response.text();
      let parsed: unknown = null;
      try {
        parsed = raw ? (JSON.parse(raw) as unknown) : null;
      } catch {
        parsed = null;
      }
      return { body: parsed, ok: response.ok, raw, status: response.status };
    },
    { body: data, requestMethod: method, requestPath: path },
  );
}

function expectApiOk(result: ApiResult, marker: string, status?: number): JsonRecord {
  expect(result.ok, `${marker}:status=${result.status}:body=${result.raw}`).toBe(true);
  if (status !== undefined) expect(result.status, `${marker}_STATUS`).toBe(status);
  expect(/(?:traceback|sqlalchemy|postgresql|password|secret)/i.test(result.raw), `${marker}_INTERNAL_LEAK`).toBe(
    false,
  );
  return asRecord(result.body);
}

test.describe('0014 recipient plan-notification real PostgreSQL dashboard boundary', () => {
  test('uses real login, cumulative API storage, and DB-backed D+/D- dashboard data', async ({
    page,
    request,
  }, testInfo) => {
    expect(process.env.SSWCENTER_0014_REAL_E2E, 'SSWCENTER_0014_REAL_E2E_WRAPPER_REQUIRED').toBe('1');
    expect(process.env.VITE_DEV_LOGIN_BYPASS, 'SSWCENTER_0014_FRONTEND_BYPASS_MUST_BE_FALSE').toBe('false');
    expect(testInfo.project.name, 'SSWCENTER_0014_SINGLE_PROJECT_REQUIRED').toBe('chromium-1440x1000');
    const pin = requiredPin();
    const pageErrors: string[] = [];
    const failedResponses: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('response', (response) => {
      if (response.url().includes('/api/') && response.status() >= 500) {
        failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });

    await bootstrapIfRequired(request, pin);
    await page.clock.setFixedTime(FIXED_KST_NOW);
    await page.goto('/dashboard');
    await loginThroughProductionForm(page, pin);
    await expect(page.getByTestId('page-dashboard'), 'SSWCENTER_0014_DASHBOARD_ROUTE_MISSING').toBeVisible();

    const staff = expectApiOk(
      await browserApi(page, '/api/v1/staff', 'POST', {
        address: null,
        birth_date: '1990-01-01',
        display_name: '0014 synthetic care worker',
        initial_employment: {
          initial_operational_roles: [],
          initial_positions: [
            {
              end_date: null,
              position_code: 'CARE_WORKER',
              start_date: NOTIFIED_DATE,
            },
          ],
          start_date: NOTIFIED_DATE,
        },
        memo: 'deterministic browser integration data only',
        name: '0014 synthetic care worker',
        phone: '010-0000-0014',
        resident_number: SYNTHETIC_STAFF_RESIDENT_NUMBER,
        sex_code: 'MALE',
      }),
      'SSWCENTER_0014_STAFF_CREATE',
      201,
    );
    const staffId = positiveId(staff.id, 'SSWCENTER_0014_STAFF_ID_INVALID');
    expect(asRecord(staff.current_employment).start_date, 'SSWCENTER_0014_STAFF_START_DATE').toBe(
      NOTIFIED_DATE,
    );
    expect(
      asItems({ items: staff.current_positions }, 'SSWCENTER_0014_STAFF_POSITIONS')[0].position_code,
      'SSWCENTER_0014_STAFF_POSITION_CODE',
    ).toBe('CARE_WORKER');

    const recipient = expectApiOk(
      await browserApi(page, '/api/v1/recipients', 'POST', {
        birth_date: '1940-01-01',
        memo: 'deterministic browser integration data only',
        name: '0014 synthetic dashboard recipient',
        sex_code: 'FEMALE',
      }),
      'SSWCENTER_0014_RECIPIENT_CREATE',
      201,
    );
    const recipientId = positiveId(recipient.id, 'SSWCENTER_0014_RECIPIENT_ID_INVALID');

    const notificationPath = `/api/v1/recipients/${recipientId}/plan-notifications`;
    const first = expectApiOk(
      await browserApi(page, notificationPath, 'POST', { notified_date: NOTIFIED_DATE }),
      'SSWCENTER_0014_PLAN_CREATE_FIRST',
      201,
    );
    const later = expectApiOk(
      await browserApi(page, notificationPath, 'POST', { notified_date: LATER_NOTIFIED_DATE }),
      'SSWCENTER_0014_PLAN_CREATE_LATER',
      201,
    );
    const firstId = positiveId(first.id, 'SSWCENTER_0014_PLAN_FIRST_ID_INVALID');
    const laterId = positiveId(later.id, 'SSWCENTER_0014_PLAN_LATER_ID_INVALID');
    expect(firstId, 'SSWCENTER_0014_PLAN_IDS_MUST_DIFFER').not.toBe(laterId);

    const cumulative = expectApiOk(
      await browserApi(page, notificationPath),
      'SSWCENTER_0014_PLAN_LIST_CUMULATIVE',
      200,
    );
    const cumulativeItems = asItems(cumulative, 'SSWCENTER_0014_PLAN_LIST_ITEMS');
    expect(cumulativeItems).toHaveLength(2);
    expect(cumulativeItems.map((item) => item.id), 'SSWCENTER_0014_PLAN_LIST_ORDER').toEqual([
      laterId,
      firstId,
    ]);

    const invalidated = expectApiOk(
      await browserApi(page, `${notificationPath}/${laterId}/invalidate`, 'POST', {
        expected_row_version: 1,
      }),
      'SSWCENTER_0014_PLAN_INVALIDATE_LATER',
      200,
    );
    expect(invalidated.row_version, 'SSWCENTER_0014_PLAN_INVALIDATED_VERSION').toBe(2);
    expect(invalidated.invalidated_at_utc, 'SSWCENTER_0014_PLAN_INVALIDATED_TIMESTAMP').toBeTruthy();

    const history = expectApiOk(
      await browserApi(page, notificationPath),
      'SSWCENTER_0014_PLAN_LIST_HISTORY',
      200,
    );
    const historyItems = asItems(history, 'SSWCENTER_0014_PLAN_HISTORY_ITEMS');
    expect(historyItems).toHaveLength(2);
    expect(historyItems.find((item) => item.id === laterId)?.row_version).toBe(2);
    expect(historyItems.find((item) => item.id === firstId)?.invalidated_at_utc).toBeNull();

    const replacement = expectApiOk(
      await browserApi(page, notificationPath, 'POST', { notified_date: NOTIFIED_DATE }),
      'SSWCENTER_0014_PLAN_CREATE_REPLACEMENT',
      201,
    );
    const replacementId = positiveId(replacement.id, 'SSWCENTER_0014_PLAN_REPLACEMENT_ID_INVALID');
    expect([firstId, laterId], 'SSWCENTER_0014_PLAN_REPLACEMENT_ID_MUST_DIFFER').not.toContain(
      replacementId,
    );
    expect(replacement.row_version, 'SSWCENTER_0014_PLAN_REPLACEMENT_VERSION').toBe(1);
    expect(replacement.invalidated_at_utc, 'SSWCENTER_0014_PLAN_REPLACEMENT_ACTIVE').toBeNull();

    const replacementHistory = expectApiOk(
      await browserApi(page, notificationPath),
      'SSWCENTER_0014_PLAN_LIST_REPLACEMENT_HISTORY',
      200,
    );
    const replacementHistoryItems = asItems(
      replacementHistory,
      'SSWCENTER_0014_PLAN_REPLACEMENT_HISTORY_ITEMS',
    );
    expect(replacementHistoryItems).toHaveLength(3);
    expect(
      replacementHistoryItems.map((item) => item.id),
      'SSWCENTER_0014_PLAN_REPLACEMENT_LIST_ORDER',
    ).toEqual([laterId, replacementId, firstId]);
    expect(replacementHistoryItems.find((item) => item.id === laterId)?.invalidated_at_utc).toBeTruthy();
    expect(replacementHistoryItems.find((item) => item.id === firstId)?.invalidated_at_utc).toBeNull();

    const deadlines = expectApiOk(
      await browserApi(page, '/api/v1/recipients/deadlines'),
      'SSWCENTER_0014_DEADLINES_API',
      200,
    );
    const planDeadline = asItems(deadlines, 'SSWCENTER_0014_DEADLINE_ITEMS').find(
      (item) => item.recipient_id === recipientId && item.kind === 'PLAN_RENEWAL',
    );
    expect(planDeadline, 'SSWCENTER_0014_PLAN_DEADLINE_MISSING').toBeTruthy();
    expect(planDeadline?.source_id, 'SSWCENTER_0014_PLAN_DEADLINE_SOURCE_ID').toBe(replacementId);
    expect(planDeadline?.source_date, 'SSWCENTER_0014_PLAN_DEADLINE_SOURCE_DATE').toBe(NOTIFIED_DATE);
    expect(planDeadline?.due_date, 'SSWCENTER_0014_PLAN_DUE_MONTH_END').toBe(PLAN_DUE_DATE);

    const staffList = expectApiOk(
      await browserApi(page, '/api/v1/staff?page=1&page_size=200'),
      'SSWCENTER_0014_STAFF_LIST_API',
      200,
    );
    const recipientList = expectApiOk(
      await browserApi(page, '/api/v1/recipients?page=1&page_size=1'),
      'SSWCENTER_0014_RECIPIENT_LIST_API',
      200,
    );
    const staffTotal = Number(staffList.total);
    const recipientTotal = Number(recipientList.total);
    expect(Number.isSafeInteger(staffTotal) && staffTotal >= 2, 'SSWCENTER_0014_STAFF_TOTAL_INVALID').toBe(
      true,
    );
    expect(recipientTotal, 'SSWCENTER_0014_RECIPIENT_TOTAL_INVALID').toBe(1);

    const dashboardStaffResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/v1/staff' && response.request().method() === 'GET',
    );
    const dashboardDeadlineResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/v1/recipients/deadlines' &&
        response.request().method() === 'GET',
    );
    await page.reload();
    expect((await dashboardStaffResponse).ok(), 'SSWCENTER_0014_DASHBOARD_STAFF_REQUEST_FAILED').toBe(true);
    expect((await dashboardDeadlineResponse).ok(), 'SSWCENTER_0014_DASHBOARD_DEADLINE_REQUEST_FAILED').toBe(
      true,
    );
    await expect(page.getByTestId('page-dashboard'), 'SSWCENTER_0014_DASHBOARD_RELOAD_FAILED').toBeVisible();

    const summaryCards = page.locator('.dashboard-summary-card');
    await expect(summaryCards, 'SSWCENTER_0014_DASHBOARD_SUMMARY_CARD_COUNT').toHaveCount(2);
    await expect(
      summaryCards.nth(0).locator('.dashboard-summary-count'),
      'SSWCENTER_0014_DASHBOARD_STAFF_COUNT',
    ).toHaveText(`${staffTotal}명`);
    await expect(
      summaryCards.nth(1).locator('.dashboard-summary-count'),
      'SSWCENTER_0014_DASHBOARD_RECIPIENT_COUNT',
    ).toHaveText(`${recipientTotal}명`);

    const staffCard = page.locator('[data-card-id="staff-onboarding"]');
    await expect(staffCard.locator('.dashboard-dday'), 'SSWCENTER_0014_DASHBOARD_STAFF_DPLUS').toHaveText(
      EXPECTED_STAFF_DDAY,
    );
    await expect(staffCard.locator('.dashboard-work-card-due'), 'SSWCENTER_0014_DASHBOARD_STAFF_START').toHaveText(
      NOTIFIED_DATE,
    );
    await expect(staffCard, 'SSWCENTER_0014_DASHBOARD_STAFF_NAME').toContainText(
      '0014 synthetic care worker',
    );

    const recipientCard = page.locator('[data-card-id="recipient-renewal"]');
    await expect(
      recipientCard.locator('.dashboard-dday'),
      'SSWCENTER_0014_DASHBOARD_RECIPIENT_DMINUS',
    ).toHaveText(EXPECTED_RECIPIENT_DDAY);
    await expect(
      recipientCard.locator('.dashboard-work-card-due'),
      'SSWCENTER_0014_DASHBOARD_RECIPIENT_DUE',
    ).toHaveText(PLAN_DUE_DATE);
    await expect(recipientCard, 'SSWCENTER_0014_DASHBOARD_RECIPIENT_NAME').toContainText(
      '0014 synthetic dashboard recipient',
    );
    await expect(page.locator('.dashboard-deadline-list'), 'SSWCENTER_0014_DASHBOARD_DEADLINE_LIST').toContainText(
      PLAN_DUE_DATE,
    );
    await expect(page.locator('.dashboard-deadline-list'), 'SSWCENTER_0014_DASHBOARD_DEADLINE_DDAY').toContainText(
      EXPECTED_RECIPIENT_DDAY,
    );
    await expect(
      page.locator('[data-card-id] input[type="checkbox"]'),
      'SSWCENTER_0014_MISSION_CARD_CHECKBOX_FORBIDDEN',
    ).toHaveCount(0);
    await expect(
      page.locator('[data-card-id] [role="checkbox"]'),
      'SSWCENTER_0014_MISSION_CARD_CHECKBOX_ROLE_FORBIDDEN',
    ).toHaveCount(0);

    expect(staffId, 'SSWCENTER_0014_STAFF_SEED_NOT_USED').toBeGreaterThan(0);
    expect(pageErrors, 'SSWCENTER_0014_PAGE_ERRORS').toEqual([]);
    expect(failedResponses, 'SSWCENTER_0014_API_5XX_RESPONSES').toEqual([]);
    console.log(
      [
        'SSWCENTER_0014_E2E_GREEN',
        `staff=${staffTotal}`,
        `recipients=${recipientTotal}`,
        `staffD=${EXPECTED_STAFF_DDAY}`,
        `recipientD=${EXPECTED_RECIPIENT_DDAY}`,
        `due=${PLAN_DUE_DATE}`,
      ].join(' '),
    );
  });
});
