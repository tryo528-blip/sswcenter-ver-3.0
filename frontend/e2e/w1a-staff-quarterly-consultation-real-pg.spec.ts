import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { expect, test, type Page } from 'playwright/test';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

const execFileAsync = promisify(execFile);
const realPgHarnessEnabled = process.env.SSWCENTER_W1A_VS5_REAL_PG === '1';

type JsonRecord = Record<string, unknown>;

type StaffFixture = {
  employmentId: number;
  id: number;
  name: string;
};

type RequestCapture = {
  body: JsonRecord;
  method: string;
  url: string;
};

type TrustedConsultationFixture = {
  available: boolean;
  consultationIds: number[];
};

type BrowserApiResult = {
  body: unknown;
  ok: boolean;
  status: number;
};

function bodyRecord(body: unknown): JsonRecord {
  return body && typeof body === 'object' && !Array.isArray(body)
    ? (body as JsonRecord)
    : {};
}

function bodyItems(body: unknown): JsonRecord[] {
  const items = bodyRecord(body).items;
  return Array.isArray(items)
    ? items.filter(
        (item): item is JsonRecord =>
          item !== null && typeof item === 'object' && !Array.isArray(item),
      )
    : [];
}

function parseRequestBody(request: { postData(): string | null }): JsonRecord {
  const raw = request.postData();
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as JsonRecord)
      : {};
  } catch {
    return {};
  }
}

function parseJsonText(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function buildRunKey(testInfo: { project: { name: string }; repeatEachIndex: number }): string {
  const project = testInfo.project.name.replace(/[^A-Za-z0-9]+/g, '-');
  return `${project}-${testInfo.repeatEachIndex}-${Date.now().toString(36)}`;
}

function buildSyntheticRrn(runKey: string, ordinal: number): string {
  let hash = 0;
  for (const character of `${runKey}-${ordinal}`) {
    hash = (hash * 31 + character.charCodeAt(0)) % 900000;
  }
  const tail = String((Date.now() + hash) % 1000000).padStart(6, '0');
  return `900101-${1}${tail}`;
}

function sqlQuote(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}

async function runTrustedSql(sql: string): Promise<string> {
  const databaseUrl = process.env.SSWCENTER_DATABASE_URL;
  if (!databaseUrl) throw new Error('database environment is missing');
  const normalized = databaseUrl.replace('postgresql+psycopg://', 'postgresql://');
  const parsed = new URL(normalized);
  const psqlPath =
    process.env.SSWCENTER_PSQL_EXE ?? 'C:\\Program Files\\PostgreSQL\\17\\bin\\psql.exe';
  const result = await execFileAsync(
    psqlPath,
    [
      '-h',
      parsed.hostname,
      '-p',
      parsed.port || '5432',
      '-U',
      decodeURIComponent(parsed.username),
      '-d',
      decodeURIComponent(parsed.pathname.replace(/^\//, '')),
      '-q',
      '-At',
      '-v',
      'ON_ERROR_STOP=1',
      '-c',
      sql,
    ],
    {
      env: {
        ...process.env,
        PGPASSWORD: decodeURIComponent(parsed.password),
      },
      maxBuffer: 1024 * 1024,
      windowsHide: true,
    },
  );
  return result.stdout.trim();
}

async function seedTrustedConsultationFixture(
  staff: StaffFixture,
  runKey: string,
): Promise<TrustedConsultationFixture> {
  const relationExists = await runTrustedSql(
    "SELECT to_regclass('erp.staff_quarterly_consultation') IS NOT NULL",
  );
  if (relationExists !== 't') return { available: false, consultationIds: [] };

  const actorId = Number(
    await runTrustedSql(
      "SELECT id FROM erp.user_account WHERE role_code = 'ADMIN' ORDER BY id LIMIT 1",
    ),
  );
  if (!Number.isSafeInteger(actorId)) throw new Error('trusted actor fixture is missing');

  const insert = async (values: string): Promise<number> => {
    const id = Number(
      await runTrustedSql(
        `INSERT INTO erp.staff_quarterly_consultation
          (staff_id, calendar_year, quarter_no, status, counseling_date, content,
           incomplete_reason_text, exempt_reason_text, created_by_account_id,
           updated_by_account_id)
         VALUES (${values}, ${actorId}, ${actorId})
         RETURNING id`,
      ),
    );
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error('trusted consultation id is invalid');
    return id;
  };

  const prefix = `VS5 ${runKey}`;
  const completeId = await insert(
    `${staff.id}, 2026, 1, 'COMPLETE', DATE '2026-01-15', ${sqlQuote(`${prefix} complete`)}, NULL, NULL`,
  );
  const incompleteId = await insert(
    `${staff.id}, 2026, 2, 'INCOMPLETE', NULL, NULL, ${sqlQuote(`${prefix} incomplete`)}, NULL`,
  );
  const exemptId = await insert(
    `${staff.id}, 2026, 3, 'EXEMPT', NULL, NULL, NULL, ${sqlQuote(`${prefix} exempt`)}`,
  );
  return { available: true, consultationIds: [completeId, incompleteId, exemptId] };
}

async function browserApi(
  page: Page,
  path: string,
  method = 'GET',
  data?: JsonRecord,
): Promise<BrowserApiResult> {
  return page.evaluate(
    async ({ data: requestData, method: requestMethod, path: requestPath }) => {
      const headers = new Headers();
      if (requestData !== undefined) headers.set('Content-Type', 'application/json');
      if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(requestMethod.toUpperCase())) {
        const match = document.cookie.match(/(?:^|; )\s*sswcenter_csrf\s*=\s*([^;]+)/);
        if (match) {
          try {
            const csrfToken = decodeURIComponent(match[1]);
            if (csrfToken) headers.set('X-CSRF-Token', csrfToken);
          } catch {
            // Keep the request fail-closed if the browser cookie is malformed.
          }
        }
      }
      const response = await fetch(requestPath, {
        body: requestData === undefined ? undefined : JSON.stringify(requestData),
        credentials: 'include',
        headers,
        method: requestMethod,
      });
      const raw = await response.text();
      let body: unknown = null;
      try {
        body = raw ? JSON.parse(raw) : null;
      } catch {
        body = null;
      }
      return { body, ok: response.ok, status: response.status };
    },
    { data, method, path },
  );
}

async function ensureAuthenticated(page: Page, pin: string, marker: string): Promise<void> {
  const staff = page.getByTestId('page-staff');
  if (!(await staff.isVisible().catch(() => false))) await page.goto('/staff');
  const login = page.getByTestId('login-container');
  await expect(login.or(staff), marker).toBeVisible();
  if (await login.isVisible()) {
    await page.getByTestId('login-pin-input').fill(pin);
    const legacyLoginSubmit = page.getByTestId('login-submit-btn');
    if (await legacyLoginSubmit.count()) await legacyLoginSubmit.click();
  }
  await expect(staff, marker).toBeVisible();
}

async function createProjectStaff(
  page: Page,
  name: string,
  runKey: string,
  ordinal: number,
  marker: string,
): Promise<StaffFixture> {
  await ensureAuthenticated(page, '123456', `${marker}_WORKSPACE_MISSING`);
  await page.getByRole('button', { name: /신규 직원 등록/i }).click();
  await page.getByLabel(/성명/i).fill(name);
  await page.getByLabel(/생년월일/i).fill('1990-01-01');
  await page.getByLabel(/성별/i).selectOption('MALE');
  await page.getByLabel(/주민등록번호/i).fill(buildSyntheticRrn(runKey, ordinal));
  await page.getByLabel(/전화번호/i).fill('010-1234-5678');
  await page.getByLabel(/입사일/i).fill('2025-01-01');
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/staff') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '등록', exact: true }).click();
  const response = await responsePromise;
  expect(response.ok(), `${marker}_CREATE_FAILED`).toBe(true);
  const body = bodyRecord(await response.json());
  const employment = bodyRecord(body.current_employment);
  const staffId = Number(body.id);
  const employmentId = Number(employment.id);
  expect(Number.isSafeInteger(staffId), `${marker}_STAFF_ID_INVALID`).toBe(true);
  expect(Number.isSafeInteger(employmentId), `${marker}_EMPLOYMENT_ID_INVALID`).toBe(true);
  await expect(page.getByTestId('staff-detail-workspace'), `${marker}_DETAIL_MISSING`).toBeVisible();
  return { employmentId, id: staffId, name };
}

async function selectStaffBySearch(page: Page, name: string, marker: string): Promise<void> {
  const search = page.getByLabel('직원 검색', { exact: true });
  await search.fill(name);
  await page.getByRole('button', { name: '검색', exact: true }).click();
  const staffButton = page.locator('.staff-list > button').filter({ hasText: name }).first();
  await expect(staffButton, marker).toBeVisible();
  await staffButton.click();
  await expect(page.getByTestId('staff-detail-workspace'), `${marker}_DETAIL_MISSING`).toBeVisible();
}

async function clickStaffFromCurrentList(page: Page, name: string, marker: string): Promise<void> {
  const staffButton = page.locator('.staff-list > button').filter({ hasText: name }).first();
  await expect(staffButton, marker).toBeVisible();
  await staffButton.evaluate((element) => (element as HTMLElement).click());
  await expect(page.getByTestId('staff-detail-workspace'), `${marker}_DETAIL_MISSING`).toBeVisible();
}

async function assertListContext(
  page: Page,
  captures: RequestCapture[],
  selectedSort: string,
  retainedScrollTop: number,
  searchValue: string,
  marker: string,
): Promise<void> {
  await expect(page.getByLabel('직원 검색', { exact: true }), `${marker}_SEARCH_MISSING`).toHaveValue(searchValue);
  await expect(page.getByLabel(/정렬/), `${marker}_SORT_MISSING`).toHaveValue(selectedSort);
  await expect(page.getByRole('tab', { name: '분기상담', exact: true }), `${marker}_TAB_CONTEXT_LOST`).toHaveAttribute(
    'aria-selected',
    'true',
  );
  const scroll = page.locator('[data-testid="staff-list-scroll"], .staff-list');
  const scrollTop = await scroll.evaluate((element) => element.scrollTop);
  expect(scrollTop, `${marker}_SCROLL_OFFSET_CHANGED`).toBe(retainedScrollTop);
  expect(scrollTop > 0, `${marker}_SCROLL_CONTEXT_LOST`).toBe(true);
  const pageIndicator = page.getByTestId('staff-page-indicator');
  const pageTwoVisible =
    (await pageIndicator.count()) > 0 && /(^|\D)2(\D|$)/.test(await pageIndicator.innerText());
  const pageTwoRequested = captures.some((capture) => /[?&]page=2(?:&|$)/.test(capture.url));
  expect(pageTwoVisible || pageTwoRequested, `${marker}_PAGE_CONTEXT_LOST`).toBe(true);
}

async function expectNoHorizontalOverflow(page: Page, marker: string): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow, marker).toBe(false);
}

test.describe('W1A-VS5 staff quarterly-consultation real PostgreSQL RED contract', () => {
  test('requires exact states, lifecycle mutations, A-B context, session isolation, and leak-safe UI', async ({
    page,
    request,
  }, testInfo) => {
    let popupCount = 0;
    const requestCaptures: RequestCapture[] = [];
    const responseSurfaces: string[] = [];
    const responsePromises: Promise<void>[] = [];

    page.on('popup', (popup) => {
      popupCount += 1;
      void popup.close();
    });
    page.on('request', (event) => {
      if (event.url().includes('/api/')) {
        requestCaptures.push({ body: parseRequestBody(event), method: event.method(), url: event.url() });
      }
    });
    page.on('response', (response) => {
      if (!response.url().includes('/api/')) return;
      const capture = response
        .text()
        .then((text) => responseSurfaces.push(text))
        .catch(() => undefined);
      responsePromises.push(capture);
    });

    test.skip(
      !realPgHarnessEnabled,
      'W1A_VS5_PG_DEPENDENCY_BLOCKER: authenticated real-PostgreSQL harness is not provisioned',
    );
    expect(
      ['chromium-1440x1000', 'chromium-1440x900', 'chromium-1366x768'].includes(
        testInfo.project.name,
      ),
      'W1A_VS5_VIEWPORT_PROJECT_MISSING',
    ).toBe(true);

    const bootstrapStatus = await request.get('/api/bootstrap/status');
    const bootstrapRaw = await bootstrapStatus.text();
    responseSurfaces.push(bootstrapRaw);
    expect(bootstrapStatus.ok(), 'W1A_VS5_BOOTSTRAP_STATUS_FAILED').toBe(true);
    if (bodyRecord(parseJsonText(bootstrapRaw)).bootstrap_required === true) {
      const bootstrap = await request.post('/api/bootstrap', {
        data: {
          admin_name: 'W1A-VS5 합성 관리자',
          birth_date: '1980-01-01',
          center_name: 'W1A-VS5 합성 센터',
          pin: '123456',
          sex_code: 'MALE',
          start_date: '2025-01-01',
        },
      });
      responseSurfaces.push(await bootstrap.text());
      expect(bootstrap.ok(), 'W1A_VS5_BOOTSTRAP_FAILED').toBe(true);
    }

    await ensureAuthenticated(page, '123456', 'W1A_VS5_BROWSER_LOGIN_MISSING');
    await expectNoHorizontalOverflow(page, 'W1A_VS5_SHELL_HORIZONTAL_OVERFLOW');
    const runKey = buildRunKey(testInfo);
    const staffA = await createProjectStaff(page, `W1A-VS5-${runKey}-A`, runKey, 1, 'W1A_VS5_STAFF_A');
    const staffB = await createProjectStaff(page, `W1A-VS5-${runKey}-B`, runKey, 2, 'W1A_VS5_STAFF_B');
    expect(staffA.id !== staffB.id, 'W1A_VS5_STAFF_PROJECT_ISOLATION_MISSING').toBe(true);

    await selectStaffBySearch(page, staffA.name, 'W1A_VS5_STAFF_A_SELECTION');
    const consultationTab = page.getByRole('tab', { name: '분기상담', exact: true });
    await expect(consultationTab, 'W1A_VS5_E2E_QUARTERLY_CONSULTATION_TAB_MISSING').toBeVisible();

    let trustedFixture: TrustedConsultationFixture;
    try {
      trustedFixture = await seedTrustedConsultationFixture(staffA, runKey);
    } catch {
      expect(false, 'W1A_VS5_TRUSTED_FIXTURE_HARNESS_FAILURE').toBe(true);
      return;
    }
    expect(trustedFixture.available, 'W1A_VS5_E2E_TRUSTED_QUARTERLY_TABLE_MISSING').toBe(true);
    expect(trustedFixture.consultationIds, 'W1A_VS5_E2E_TRUSTED_QUARTERLY_FIXTURE_MISSING').toHaveLength(3);
    await consultationTab.click();

    await expect(
      page.getByTestId('staff-quarterly-consultation-panel'),
      'W1A_VS5_E2E_QUARTERLY_PANEL_MISSING',
    ).toBeVisible();
    await expect(page.getByTestId('quarterly-consultation-row'), 'W1A_VS5_E2E_QUARTERLY_ROWS_MISSING').toHaveCount(3);
    for (const status of ['COMPLETE', 'INCOMPLETE', 'EXEMPT']) {
      await expect(
        page.locator(`[data-testid="quarterly-consultation-row"][data-status="${status}"]`),
        `W1A_VS5_E2E_${status}_ROW_MISSING`,
      ).toHaveCount(1);
    }
    const completeRow = page.locator('[data-testid="quarterly-consultation-row"][data-status="COMPLETE"]');
    const incompleteRow = page.locator('[data-testid="quarterly-consultation-row"][data-status="INCOMPLETE"]');
    const exemptRow = page.locator('[data-testid="quarterly-consultation-row"][data-status="EXEMPT"]');
    await expect(completeRow.getByLabel('상담일'), 'W1A_VS5_E2E_COMPLETE_DATE_MISSING').toBeVisible();
    await expect(completeRow.getByLabel('처리내용'), 'W1A_VS5_E2E_COMPLETE_CONTENT_MISSING').toBeVisible();
    await expect(incompleteRow.getByLabel('미완료 사유'), 'W1A_VS5_E2E_INCOMPLETE_REASON_MISSING').toBeVisible();
    await expect(exemptRow.getByLabel('면제 사유'), 'W1A_VS5_E2E_EXEMPT_REASON_MISSING').toBeVisible();

    const capabilities = await browserApi(page, '/api/v1/session-capabilities');
    expect(capabilities.ok, 'W1A_VS5_E2E_CAPABILITIES_MISSING').toBe(true);
    await expect(page.getByRole('button', { name: /분기상담.*(추가|등록)/ }), 'W1A_VS5_E2E_MANAGE_CONTROL_MISSING').toBeVisible();
    await page.getByRole('button', { name: /분기상담.*(추가|등록)/ }).click();
    await page.getByLabel('연도').fill('2026');
    await page.getByLabel('분기').selectOption('4');
    await page.getByLabel('상태').selectOption('COMPLETE');
    await page.getByLabel('상담일').fill('2026-04-15');
    await page.getByLabel('처리내용').fill('VS5 E2E complete create');
    const createResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/quarterly-consultations`) &&
        response.request().method() === 'POST',
    );
    const createRefetchPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/quarterly-consultations`) &&
        response.request().method() === 'GET',
    );
    await page.getByRole('button', { name: /분기상담 저장|저장/ }).click();
    const createResponse = await createResponsePromise;
    expect(createResponse.ok(), 'W1A_VS5_E2E_CREATE_FAILED').toBe(true);
    const created = bodyRecord(await createResponse.json());
    expect(Number(created.staff_id), 'W1A_VS5_E2E_CREATE_STAFF_MISMATCH').toBe(staffA.id);
    expect(Number(created.calendar_year), 'W1A_VS5_E2E_CREATE_YEAR_MISMATCH').toBe(2026);
    expect(Number(created.quarter_no), 'W1A_VS5_E2E_CREATE_QUARTER_MISMATCH').toBe(4);
    expect(created.status, 'W1A_VS5_E2E_CREATE_STATUS_MISMATCH').toBe('COMPLETE');
    expect(Number(created.row_version), 'W1A_VS5_E2E_CREATE_VERSION_MISSING').toBe(1);
    const createCapture = requestCaptures
      .filter((capture) => capture.method === 'POST' && /quarterly-consultations$/.test(capture.url))
      .at(-1);
    expect(createCapture?.body, 'W1A_VS5_E2E_CREATE_PAYLOAD_MISMATCH').toEqual({
      calendar_year: 2026,
      quarter_no: 4,
      status: 'COMPLETE',
      counseling_date: '2026-04-15',
      content: 'VS5 E2E complete create',
      incomplete_reason_text: null,
      exempt_reason_text: null,
    });
    const createList = bodyRecord(await (await createRefetchPromise).json());
    expect(
      bodyItems(createList).some(
        (item) => Number(item.calendar_year) === 2026 && Number(item.quarter_no) === 4,
      ),
      'W1A_VS5_E2E_CREATE_GET_MISMATCH',
    ).toBe(true);

    const updateRow = page.locator('[data-testid="quarterly-consultation-row"][data-status="COMPLETE"]').filter({ hasText: '1분기' }).first();
    await updateRow.getByRole('button', { name: /수정/ }).click();
    await updateRow.getByRole('combobox', { name: '상태' }).selectOption('INCOMPLETE');
    await updateRow.getByLabel('미완료 사유').fill('VS5 E2E incomplete update');
    await expect(updateRow.getByLabel('상담일')).toHaveCount(0);
    await expect(updateRow.getByLabel('처리내용')).toHaveCount(0);
    const updateResponsePromise = page.waitForResponse(
      (response) =>
        /quarterly-consultations\/\d+$/.test(response.url()) && response.request().method() === 'PATCH',
    );
    const updateRefetchPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/quarterly-consultations`) &&
        response.request().method() === 'GET',
    );
    await updateRow.getByRole('button', { name: /저장/ }).click();
    const updateResponse = await updateResponsePromise;
    expect(updateResponse.ok(), 'W1A_VS5_E2E_UPDATE_FAILED').toBe(true);
    const updated = bodyRecord(await updateResponse.json());
    expect(updated.status, 'W1A_VS5_E2E_UPDATE_STATUS_MISMATCH').toBe('INCOMPLETE');
    expect(Number(updated.row_version), 'W1A_VS5_E2E_UPDATE_VERSION_MISSING').toBe(2);
    const updateCapture = requestCaptures
      .filter((capture) => capture.method === 'PATCH' && /quarterly-consultations\/\d+$/.test(capture.url))
      .at(-1);
    expect(updateCapture?.body, 'W1A_VS5_E2E_UPDATE_PAYLOAD_MISMATCH').toEqual({
      status: 'INCOMPLETE',
      counseling_date: null,
      content: null,
      incomplete_reason_text: 'VS5 E2E incomplete update',
      exempt_reason_text: null,
      expected_row_version: 1,
    });
    const updateList = bodyRecord(await (await updateRefetchPromise).json());
    expect(
      bodyItems(updateList).some((item) => item.status === 'INCOMPLETE' && item.incomplete_reason_text),
      'W1A_VS5_E2E_UPDATE_GET_MISMATCH',
    ).toBe(true);

    const invalidateRow = page.locator('[data-testid="quarterly-consultation-row"]').filter({ hasText: '1분기' }).first();
    await invalidateRow.getByRole('button', { name: /무효화/ }).click();
    await page.getByLabel('상태').selectOption('EXEMPT');
    await page.getByLabel('면제 사유').fill('VS5 E2E replacement exemption');
    const invalidateResponsePromise = page.waitForResponse(
      (response) =>
        /quarterly-consultations\/\d+\/invalidate$/.test(response.url()) &&
        response.request().method() === 'POST',
    );
    const invalidateRefetchPromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/quarterly-consultations`) &&
        response.request().method() === 'GET',
    );
    await page.getByRole('button', { name: /무효화 확정|대체 저장|저장/ }).click();
    const invalidateResponse = await invalidateResponsePromise;
    expect(invalidateResponse.ok(), 'W1A_VS5_E2E_INVALIDATE_FAILED').toBe(true);
    const invalidated = bodyRecord(await invalidateResponse.json());
    const replacementId = Number(invalidated.replacement_staff_quarterly_consultation_id);
    expect(
      typeof invalidated.invalidated_at_utc === 'string' && invalidated.invalidated_at_utc.length > 0,
      'W1A_VS5_E2E_INVALIDATE_TIMESTAMP_MISSING',
    ).toBe(true);
    expect(Number.isSafeInteger(replacementId) && replacementId > 0, 'W1A_VS5_E2E_REPLACEMENT_ID_MISSING').toBe(true);
    const invalidatedList = bodyRecord(await (await invalidateRefetchPromise).json());
    const activeItems = bodyItems(invalidatedList);
    expect(activeItems.some((item) => Number(item.id) === replacementId), 'W1A_VS5_E2E_REPLACEMENT_GET_MISSING').toBe(true);
    expect(activeItems.every((item) => Number(item.id) !== Number(invalidated.id)), 'W1A_VS5_E2E_ORIGINAL_STILL_ACTIVE').toBe(true);

    const search = page.getByLabel('직원 검색', { exact: true });
    await search.fill(runKey);
    await page.getByRole('button', { name: '검색', exact: true }).click();
    const sort = page.getByLabel(/정렬/);
    const sortOptions = await sort.locator('option').evaluateAll((options) =>
      options.map((option) => option.value).filter(Boolean),
    );
    const selectedSort = sortOptions.find((value) => value === 'staff_no') ?? sortOptions[0] ?? '';
    await sort.selectOption(selectedSort);
    const pageTwoResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        response.url().includes('/api/v1/staff') &&
        /[?&]page=2(?:&|$)/.test(response.url()),
    );
    await page.getByRole('button', { name: /다음 페이지|next/i }).click();
    const pageTwoResponse = await pageTwoResponsePromise;
    expect(
      bodyItems(await pageTwoResponse.json()).some((item) => Number(item.id) === staffB.id),
      'W1A_VS5_E2E_PAGE_TWO_B_MISMATCH',
    ).toBe(true);
    await expect(page.getByTestId('staff-page-indicator')).toHaveText('2');
    const scroll = page.locator('[data-testid="staff-list-scroll"], .staff-list');
    const scrollStyle = await scroll.evaluate((element) => ({
      height: element.style.height,
      maxHeight: element.style.maxHeight,
      overflowY: element.style.overflowY,
    }));
    const scrollFixture = await page.addStyleTag({
      content:
        '[data-testid="staff-list-scroll"] { height: 8px !important; max-height: 8px !important; overflow-y: auto !important; }',
    });
    try {
      const metrics = await scroll.evaluate((element) => ({
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
      }));
      expect(metrics.scrollHeight > metrics.clientHeight, 'W1A_VS5_E2E_SCROLL_OVERFLOW_MISSING').toBe(true);
      const retainedScrollTop = await scroll.evaluate((element) => {
        element.scrollTop = 1;
        element.dispatchEvent(new Event('scroll', { bubbles: true }));
        return element.scrollTop;
      });
      expect(retainedScrollTop > 0, 'W1A_VS5_E2E_SCROLL_EVENT_NOT_RETAINED').toBe(true);
      await expect(
        page.locator('.staff-list > button').filter({ hasText: staffB.name }).first(),
        'W1A_VS5_CONTEXT_STAFF_B_ROW_MISSING',
      ).toBeVisible();
      await clickStaffFromCurrentList(page, staffB.name, 'W1A_VS5_CONTEXT_STAFF_B');
      await page.getByRole('tab', { name: '분기상담', exact: true }).click();
      await assertListContext(page, requestCaptures, selectedSort, retainedScrollTop, runKey, 'W1A_VS5_CONTEXT_AFTER_B');
      await expect(page.getByTestId('staff-detail-workspace'), 'W1A_VS5_CONTEXT_B_DETAIL_MISSING').toContainText(staffB.name);
      await page.goBack();
      await expect(page.getByTestId('staff-detail-workspace'), 'W1A_VS5_CONTEXT_BACK_A_DETAIL_MISSING').toContainText(staffA.name);
      await assertListContext(page, requestCaptures, selectedSort, retainedScrollTop, runKey, 'W1A_VS5_CONTEXT_AFTER_BACK');
    } finally {
      await scroll.evaluate((element, style) => {
        element.style.height = style.height;
        element.style.maxHeight = style.maxHeight;
        element.style.overflowY = style.overflowY;
      }, scrollStyle);
      await scrollFixture.evaluate((element) => element.remove());
    }

    const logoutRequest = page.waitForRequest(
      (requestEvent) => requestEvent.url().endsWith('/api/auth/logout') && requestEvent.method() === 'POST',
    );
    await page.getByTestId('header-btn-logout').click();
    await logoutRequest;
    await expect(page.getByTestId('login-form'), 'W1A_VS5_LOGOUT_SESSION_NOT_CLEARED').toBeVisible();
    await expect(page.getByTestId('auth-loading')).toHaveCount(0);

    await Promise.all(responsePromises);
    const forbidden = /교체상담|실제급여제공|Day\s*14|Day\s*15|첨부|attachment|file_id|evidence_id|task_id|care-change/i;
    const surfaces = `${responseSurfaces.join('\n')}\n${JSON.stringify(requestCaptures)}\n${await page.locator('body').innerText()}`;
    expect(forbidden.test(surfaces), 'W1A_VS5_E2E_FORBIDDEN_SURFACE_EXPOSED').toBe(false);
    expect(/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(surfaces), 'W1A_VS5_E2E_INTERNAL_ERROR_OR_SECRET_LEAKED').toBe(false);
    expect(popupCount, 'W1A_VS5_E2E_UNEXPECTED_POPUP').toBe(0);
    await expectNoHorizontalOverflow(page, 'W1A_VS5_E2E_FINAL_HORIZONTAL_OVERFLOW');
  });
});
