import { expect, test, type Page } from 'playwright/test';

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
});

const realPgHarnessEnabled = process.env.SSWCENTER_W1A_VS2_REAL_PG === '1';
const LICENSE_CODES = ['CARE_WORKER', 'SOCIAL_WORKER', 'NURSE'] as const;
const LICENSE_DISPLAY_NAMES = ['요양보호사', '사회복지사', '간호사'] as const;
const SERVICE_PAIRS = [
  { code: 'HOME_CARE', display_name: '방문요양' },
  { code: 'HOME_BATH', display_name: '방문목욕' },
  { code: 'TEMP_HOME_CARE', display_name: '일시재가' },
  { code: 'HOSPITAL_ESCORT', display_name: '병원동행' },
  { code: 'BARO_CARE', display_name: '바로돌봄' },
] as const;

type JsonRecord = Record<string, unknown>;

type RequestCapture = {
  body: JsonRecord;
  method: string;
  url: string;
};

type BrowserApiResult = {
  body: unknown;
  ok: boolean;
  status: number;
};

type StaffFixture = {
  employmentEnd: string | null;
  employmentId: number;
  employmentStart: string;
  id: number;
  name: string;
};

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

function samePairs(
  actual: unknown,
  expected: readonly { code: string; display_name: string }[],
): boolean {
  if (!Array.isArray(actual)) return false;
  const pairs = actual
    .filter(
      (item): item is JsonRecord =>
        item !== null && typeof item === 'object' && !Array.isArray(item),
    )
    .map((item) => ({
      code: String(item.code ?? ''),
      display_name: String(item.display_name ?? ''),
    }));
  return JSON.stringify(pairs) === JSON.stringify(expected);
}

function expectNoKeys(body: JsonRecord, keys: string[], marker: string): void {
  expect(keys.every((key) => !(key in body)), marker).toBe(true);
}

async function browserApi(
  page: Page,
  path: string,
  method = 'GET',
  data?: JsonRecord,
): Promise<BrowserApiResult> {
  return page.evaluate(
    async ({ data: requestData, method: requestMethod, path: requestPath }) => {
      const response = await fetch(requestPath, {
        body: requestData === undefined ? undefined : JSON.stringify(requestData),
        headers: requestData === undefined ? undefined : { 'Content-Type': 'application/json' },
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

async function expectNoHorizontalOverflow(page: Page, marker: string): Promise<void> {
  const hasOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasOverflow, marker).toBe(false);
}

async function ensureForm(
  page: Page,
  testId: string,
  addName: RegExp,
  marker: string,
): Promise<ReturnType<Page['getByTestId']>> {
  const form = page.getByTestId(testId);
  if ((await form.count()) === 0) {
    const addButton = page.getByRole('button', { name: addName });
    await expect(addButton, marker).toBeVisible();
    await addButton.click();
  }
  await expect(form, marker).toBeVisible();
  return form;
}

async function fillLicenseForm(
  form: ReturnType<Page['getByTestId']>,
  code: string,
  number: string,
): Promise<void> {
  await form.locator('select[name="license_type_code"]').selectOption(code);
  await form.locator('input[name="license_number"]').fill(number);
  await form.locator('input[name="issued_date"]').fill('2025-01-01');
}

async function fillQualificationForm(
  form: ReturnType<Page['getByTestId']>,
  employmentId: number,
  startDate: string,
  sourceLicenseValue?: string,
): Promise<void> {
  await form.locator('select[name="employment_id"]').selectOption(String(employmentId));
  await form.locator('select[name="service_type_code"]').selectOption('HOME_CARE');
  await form.locator('input[name="start_date"]').fill(startDate);
  const source = form.locator('select[name="source_license_id"]');
  if (sourceLicenseValue !== undefined) {
    await source.selectOption(sourceLicenseValue);
  }
}

function dateInsideEmployment(startDate: string, endDate: string | null): string {
  const preferred = '2025-02-01';
  if (preferred >= startDate && (endDate === null || preferred <= endDate)) {
    return preferred;
  }
  return startDate;
}

function dateAfter(startDate: string): string {
  const value = new Date(`${startDate}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
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

async function ensureAuthenticated(page: Page, pin: string, marker: string): Promise<void> {
  const staff = page.getByTestId('page-staff');
  if (!(await staff.isVisible().catch(() => false))) {
    await page.goto('/staff');
  }
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
  const registerButton = page.getByRole('button', { name: /신규 직원 등록/i });
  await expect(registerButton, `${marker}_REGISTER_CONTROL_MISSING`).toBeVisible();
  await registerButton.click();
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
  const currentEmployment = bodyRecord(body.current_employment);
  const staffId = Number(body.id);
  const employmentId = Number(currentEmployment.id);
  expect(Number.isSafeInteger(staffId), `${marker}_STAFF_ID_INVALID`).toBe(true);
  expect(Number.isSafeInteger(employmentId), `${marker}_EMPLOYMENT_ID_INVALID`).toBe(true);
  await expect(page.getByTestId('staff-detail-workspace'), `${marker}_DETAIL_MISSING`).toBeVisible();
  return {
    employmentEnd:
      typeof currentEmployment.end_date === 'string' ? currentEmployment.end_date : null,
    employmentId,
    employmentStart:
      typeof currentEmployment.start_date === 'string'
        ? currentEmployment.start_date
        : '2025-01-01',
    id: staffId,
    name,
  };
}

async function clickStaffFromCurrentList(
  page: Page,
  name: string,
  marker: string,
): Promise<void> {
  const staffButton = page.locator('.staff-list > button').filter({ hasText: name }).first();
  await expect(staffButton, marker).toBeVisible();
  await staffButton.click();
  await expect(page.getByTestId('staff-detail-workspace'), `${marker}_DETAIL_MISSING`).toBeVisible();
}

async function selectStaffBySearch(page: Page, name: string, marker: string): Promise<void> {
  const search = page.getByLabel('직원 검색', { exact: true });
  await search.fill(name);
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await clickStaffFromCurrentList(page, name, marker);
}

function qualificationTab(page: Page): ReturnType<Page['getByRole']> {
  return page.getByRole('tab', { name: '서비스 제공자격', exact: true });
}

function licenseTab(page: Page): ReturnType<Page['getByRole']> {
  return page.getByRole('tab', { name: '자격증', exact: true });
}

function listRequests(captures: RequestCapture[]): RequestCapture[] {
  return captures.filter(
    (capture) =>
      capture.method === 'GET' && /\/api\/v1\/staff(?:\?|$)/.test(capture.url),
  );
}

async function assertListContext(
  page: Page,
  capturesSinceTransition: RequestCapture[],
  sortValue: string,
  expectedScrollTop: number,
  searchValue: string,
  marker: string,
): Promise<void> {
  const search = page.getByLabel('직원 검색', { exact: true });
  const sort = page.getByLabel(/정렬/);
  const scroll = page.locator('[data-testid="staff-list-scroll"], .staff-list');
  const tab = qualificationTab(page);
  await expect(search, `${marker}_SEARCH_MISSING`).toBeVisible();
  await expect(sort, `${marker}_SORT_MISSING`).toHaveValue(sortValue);
  await expect(scroll, `${marker}_SCROLL_MISSING`).toBeVisible();
  expect(
    await search.inputValue(),
    `${marker}_SEARCH_CONTEXT_LOST`,
  ).toBe(searchValue);
  const currentScrollTop = await scroll.evaluate((element) => element.scrollTop);
  expect(currentScrollTop > 0, `${marker}_SCROLL_CONTEXT_LOST`).toBe(true);
  expect(currentScrollTop, `${marker}_SCROLL_OFFSET_CHANGED`).toBe(expectedScrollTop);
  expect(
    await tab.getAttribute('aria-selected'),
    `${marker}_SELECTED_TAB_CONTEXT_LOST`,
  ).toBe('true');

  const pageIndicator = page.getByTestId('staff-page-indicator');
  const pageDisplayMatches =
    (await pageIndicator.count()) > 0 &&
    /(^|\D)2(\D|$)/.test(await pageIndicator.innerText());
  const pageRequestMatches = capturesSinceTransition.some((capture) =>
    /[?&]page=2(?:&|$)/.test(capture.url),
  );
  expect(
    pageDisplayMatches || pageRequestMatches,
    `${marker}_PAGE_CONTEXT_LOST`,
  ).toBe(true);
}

test.describe('W1A-VS2 staff qualifications real PostgreSQL E2E', () => {
  test('creates isolated licenses and qualifications, then retains live list context', async ({
    page,
    request,
  }, testInfo) => {
    let popupCount = 0;
    const requestCaptures: RequestCapture[] = [];
    const responseSurfaces: string[] = [];
    const responseSurfacePromises: Promise<void>[] = [];

    // Install popup and leak observers before bootstrap, login, navigation, or any UI action.
    page.on('popup', (popup) => {
      popupCount += 1;
      void popup.close();
    });
    page.on('request', (requestEvent) => {
      if (requestEvent.url().includes('/api/')) {
        requestCaptures.push({
          body: parseRequestBody(requestEvent),
          method: requestEvent.method(),
          url: requestEvent.url(),
        });
      }
    });
    page.on('response', (response) => {
      if (!response.url().includes('/api/')) return;
      const capture = response
        .text()
        .then((text) => {
          responseSurfaces.push(text);
        })
        .catch(() => undefined);
      responseSurfacePromises.push(capture);
    });

    test.skip(
      !realPgHarnessEnabled,
      'W1A_VS2_PG_DEPENDENCY_BLOCKER: authenticated real-PostgreSQL harness is not provisioned',
    );

    expect(
      ['chromium-1440x1000', 'chromium-1440x900', 'chromium-1366x768'].includes(
        testInfo.project.name,
      ),
      'W1A_VS2_VIEWPORT_PROJECT_MISSING',
    ).toBe(true);

    // Bootstrap is intentionally the only direct request-fixture operation. Its response is
    // added manually because Playwright page listeners cannot observe request-fixture traffic.
    const bootstrapStatus = await request.get('/api/bootstrap/status');
    const bootstrapStatusRaw = await bootstrapStatus.text();
    responseSurfaces.push(bootstrapStatusRaw);
    expect(bootstrapStatus.ok(), 'W1A_VS2_BOOTSTRAP_STATUS_FAILED').toBe(true);
    const bootstrapStatusBody = bodyRecord(parseJsonText(bootstrapStatusRaw));
    if (bootstrapStatusBody.bootstrap_required === true) {
      const bootstrap = await request.post('/api/bootstrap', {
        data: {
          birth_date: '1980-01-01',
          center_name: 'W1A 합성 센터',
          admin_name: 'W1A-VS2 합성 관리자',
          pin: '123456',
          sex_code: 'MALE',
          start_date: '2025-01-01',
        },
      });
      const bootstrapRaw = await bootstrap.text();
      responseSurfaces.push(bootstrapRaw);
      expect(bootstrap.ok(), 'W1A_VS2_BOOTSTRAP_FAILED').toBe(true);
    }

    await ensureAuthenticated(page, '123456', 'W1A_VS2_AUTHENTICATED_BROWSER_LOGIN_MISSING');
    await expectNoHorizontalOverflow(page, 'W1A_VS2_E2E_SHELL_HORIZONTAL_OVERFLOW');

    const runKey = buildRunKey(testInfo);
    const staffA = await createProjectStaff(
      page,
      `W1A-VS2-${runKey}-A`,
      runKey,
      1,
      'W1A_VS2_PROJECT_STAFF_A',
    );
    const staffB = await createProjectStaff(
      page,
      `W1A-VS2-${runKey}-B`,
      runKey,
      2,
      'W1A_VS2_PROJECT_STAFF_B',
    );
    expect(staffA.id !== staffB.id, 'W1A_VS2_PROJECT_STAFF_IDS_NOT_ISOLATED').toBe(true);
    expect(staffA.name !== staffB.name, 'W1A_VS2_PROJECT_STAFF_NAMES_NOT_ISOLATED').toBe(true);

    await selectStaffBySearch(page, staffA.name, 'W1A_VS2_STAFF_A_SELECTION');
    const servicesResponse = await browserApi(page, '/api/v1/catalogs/services');
    expect(servicesResponse.ok, 'W1A_VS2_SERVICE_CATALOG_ROUTE_MISSING').toBe(true);
    expect(
      samePairs(bodyItems(servicesResponse.body), SERVICE_PAIRS),
      'W1A_VS2_SERVICE_CATALOG_MISMATCH',
    ).toBe(true);
    const licenseTypesResponse = await browserApi(page, '/api/v1/catalogs/license-types');
    expect(licenseTypesResponse.ok, 'W1A_VS2_LICENSE_CATALOG_ROUTE_MISSING').toBe(true);
    expect(
      samePairs(
        bodyItems(licenseTypesResponse.body),
        LICENSE_CODES.map((code, index) => ({
          code,
          display_name: LICENSE_DISPLAY_NAMES[index],
        })),
      ),
      'W1A_VS2_LICENSE_CATALOG_CODE_DISPLAY_MISMATCH',
    ).toBe(true);

    // Staff A: create three project-unique license facts through the authenticated browser UI.
    const staffALicenseTab = licenseTab(page);
    const staffAQualificationTab = qualificationTab(page);
    await expect(staffALicenseTab, 'W1A_VS2_E2E_LICENSE_TAB_MISSING').toBeVisible();
    await expect(staffAQualificationTab, 'W1A_VS2_E2E_QUALIFICATION_TAB_MISSING').toBeVisible();
    await staffALicenseTab.click();
    const licenseForm = await ensureForm(
      page,
      'staff-license-form',
      /자격증.*(?:추가|등록)/,
      'W1A_VS2_E2E_LICENSE_FORM_MISSING',
    );
    expect(
      (await licenseForm.locator('[name="expiry_date"], [name="start_date"], [name="end_date"]').count()) === 0,
      'W1A_VS2_E2E_LICENSE_PERIOD_FIELDS_FORBIDDEN',
    ).toBe(true);
    const licenseTypeSelect = licenseForm.locator('select[name="license_type_code"]');
    await expect
      .poll(
        () =>
          licenseTypeSelect.evaluate(
            (element) => (element as HTMLSelectElement).options.length - 1,
          ),
        { message: 'W1A_VS2_E2E_LICENSE_OPTIONS_NOT_READY', timeout: 10000 },
      )
      .toBe(LICENSE_CODES.length);
    const licenseOptionPairs = await licenseTypeSelect.evaluate((element) =>
      Array.from((element as HTMLSelectElement).options)
        .filter((option) => option.value)
        .map((option) => ({ code: option.value, display_name: option.textContent?.trim() ?? '' })),
    );
    expect(
      samePairs(licenseOptionPairs, LICENSE_CODES.map((code, index) => ({
        code,
        display_name: LICENSE_DISPLAY_NAMES[index],
      }))),
      'W1A_VS2_E2E_LICENSE_OPTIONS_MISMATCH',
    ).toBe(true);

    for (const [index, code] of LICENSE_CODES.entries()) {
      const currentForm = await ensureForm(
        page,
        'staff-license-form',
        /자격증.*(?:추가|등록)/,
        'W1A_VS2_E2E_LICENSE_FORM_MISSING',
      );
      await fillLicenseForm(currentForm, code, `W1A-VS2-${runKey}-LICENSE-${index + 1}`);
      const responsePromise = page.waitForResponse(
        (response) =>
          response.url().includes(`/api/v1/staff/${staffA.id}/licenses`) &&
          response.request().method() === 'POST',
      );
      await currentForm.getByRole('button', { name: /등록|추가|저장/ }).click();
      const response = await responsePromise;
      expect(response.ok(), 'W1A_VS2_E2E_LICENSE_CREATE_FAILED').toBe(true);
    }
    await expect(
      page.getByTestId('staff-license-row'),
      'W1A_VS2_E2E_THREE_LICENSE_FACTS_MISSING',
    ).toHaveCount(3);
    const storedLicensesResponse = await browserApi(
      page,
      `/api/v1/staff/${staffA.id}/licenses`,
    );
    expect(storedLicensesResponse.ok, 'W1A_VS2_E2E_LICENSE_GET_RECHECK_FAILED').toBe(true);
    const storedLicenses = bodyItems(storedLicensesResponse.body);
    expect(storedLicenses.length === 3, 'W1A_VS2_E2E_THREE_LICENSES_NOT_STORED').toBe(true);
    expect(
      storedLicenses.every((item) => Number(item.staff_id) === staffA.id),
      'W1A_VS2_E2E_LICENSE_STAFF_ID_MISMATCH',
    ).toBe(true);
    expect(
      new Set(storedLicenses.map((item) => String(item.license_number ?? ''))).size === 3,
      'W1A_VS2_E2E_LICENSE_NUMBERS_NOT_UNIQUE',
    ).toBe(true);
    const sourceLicenseId = Number(storedLicenses[0]?.id);
    expect(Number.isSafeInteger(sourceLicenseId), 'W1A_VS2_E2E_SOURCE_LICENSE_ID_INVALID').toBe(true);
    const licenseCaptures = requestCaptures.filter(
      (capture) => capture.method === 'POST' && capture.url.includes(`/staff/${staffA.id}/licenses`),
    );
    expect(licenseCaptures.length === 3, 'W1A_VS2_E2E_LICENSE_REQUEST_COUNT_MISMATCH').toBe(true);
    for (const capture of licenseCaptures) {
      expectNoKeys(
        capture.body,
        ['employment_id', 'service_type_code', 'source_license_id', 'start_date', 'end_date'],
        'W1A_VS2_E2E_LICENSE_REQUEST_MIXES_QUALIFICATION_FIELDS',
      );
    }
    await expectNoHorizontalOverflow(page, 'W1A_VS2_E2E_LICENSE_HORIZONTAL_OVERFLOW');

    // Staff B has no license, but can create a qualification without a source license.
    await selectStaffBySearch(page, staffB.name, 'W1A_VS2_STAFF_B_SELECTION');
    const staffBLicensesResponse = await browserApi(
      page,
      `/api/v1/staff/${staffB.id}/licenses`,
    );
    expect(staffBLicensesResponse.ok, 'W1A_VS2_E2E_STAFF_B_LICENSE_READ_FAILED').toBe(true);
    const staffBLicenses = bodyItems(staffBLicensesResponse.body);
    expect(staffBLicenses.length === 0, 'W1A_VS2_E2E_STAFF_B_LICENSE_NOT_EMPTY').toBe(true);
    const staffBQualificationTab = qualificationTab(page);
    await expect(staffBQualificationTab, 'W1A_VS2_E2E_QUALIFICATION_TAB_MISSING_B').toBeVisible();
    await staffBQualificationTab.click();
    const noSourceForm = await ensureForm(
      page,
      'staff-qualification-form',
      /서비스 제공자격.*(?:추가|등록)/,
      'W1A_VS2_E2E_QUALIFICATION_FORM_MISSING',
    );
    const noSource = noSourceForm.getByLabel(/근거.*자격증/);
    await expect(noSource, 'W1A_VS2_E2E_OPTIONAL_SOURCE_LICENSE_FIELD_MISSING').toBeVisible();
    expect(await noSource.getAttribute('required'), 'W1A_VS2_E2E_SOURCE_IS_REQUIRED').toBeNull();
    const staffBStartDate = dateInsideEmployment(staffB.employmentStart, staffB.employmentEnd);
    await fillQualificationForm(noSourceForm, staffB.employmentId, staffBStartDate);
    const noSourceResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/staff/${staffB.id}/service-qualifications`) &&
        response.request().method() === 'POST',
    );
    await noSourceForm.getByRole('button', { name: /등록|추가|저장/ }).click();
    const noSourceResponse = await noSourceResponsePromise;
    expect(noSourceResponse.ok(), 'W1A_VS2_E2E_QUALIFICATION_WITHOUT_SOURCE_FAILED').toBe(true);
    const noSourceCapture = requestCaptures
      .filter(
        (capture) =>
          capture.method === 'POST' &&
          capture.url.includes(`/staff/${staffB.id}/service-qualifications`),
      )
      .at(-1);
    expect(noSourceCapture !== undefined, 'W1A_VS2_E2E_QUALIFICATION_REQUEST_MISSING').toBe(true);
    const noSourceBody = noSourceCapture?.body ?? {};
    expect(noSourceBody.source_license_id == null, 'W1A_VS2_E2E_SOURCE_NOT_OPTIONAL').toBe(true);
    expectNoKeys(
      noSourceBody,
      ['license_number', 'issued_date'],
      'W1A_VS2_E2E_QUALIFICATION_DUPLICATES_LICENSE_FACTS',
    );
    const storedBQualificationsResponse = await browserApi(
      page,
      `/api/v1/staff/${staffB.id}/service-qualifications`,
    );
    expect(
      storedBQualificationsResponse.ok,
      'W1A_VS2_E2E_QUALIFICATION_GET_RECHECK_FAILED',
    ).toBe(true);
    const storedBQualifications = bodyItems(storedBQualificationsResponse.body);
    expect(
      storedBQualifications.length === 1,
      'W1A_VS2_E2E_QUALIFICATION_WITHOUT_SOURCE_NOT_STORED',
    ).toBe(true);
    const storedBQualification = storedBQualifications[0] ?? {};
    expect(
      Number(storedBQualification.staff_id) === staffB.id &&
        Number(storedBQualification.employment_id) === staffB.employmentId &&
        storedBQualification.start_date === staffBStartDate &&
        storedBQualification.source_license_id == null,
      'W1A_VS2_E2E_QUALIFICATION_WITHOUT_SOURCE_FIELDS_MISMATCH',
    ).toBe(true);
    await expect(page.getByTestId('staff-qualification-row'), 'W1A_VS2_E2E_QUALIFICATION_DOM_REFETCH_MISSING').toHaveCount(1);

    // Staff A: close employment, re-enter, then reuse only a same-staff source license.
    await selectStaffBySearch(page, staffA.name, 'W1A_VS2_STAFF_A_REENTRY_SELECTION');
    const closeButton = page.getByRole('button', { name: /재직 종료/ });
    await expect(closeButton, 'W1A_VS2_E2E_CLOSE_EMPLOYMENT_CONTROL_MISSING').toBeVisible();
    await closeButton.click();
    await page.getByLabel(/퇴사일/).fill('2025-03-01');
    const closeResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/staff/${staffA.id}/employments/${staffA.employmentId}/close`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /종료 확정/ }).click();
    const closeResponse = await closeResponsePromise;
    expect(closeResponse.ok(), 'W1A_VS2_E2E_CLOSE_EMPLOYMENT_FAILED').toBe(true);
    const rehireButton = page.getByRole('button', { name: /재입사/ });
    await expect(rehireButton, 'W1A_VS2_E2E_REHIRE_CONTROL_MISSING').toBeVisible();
    await rehireButton.click();
    await page.getByLabel(/재입사일/).fill('2025-04-01');
    const rehireResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/employments`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /재입사 등록/ }).click();
    const rehireResponse = await rehireResponsePromise;
    expect(rehireResponse.ok(), 'W1A_VS2_E2E_REHIRE_FAILED').toBe(true);
    const rehireBody = bodyRecord(await rehireResponse.json());
    const rehireEmploymentId = Number(rehireBody.id);
    const rehireStartDate = String(rehireBody.start_date ?? '');
    expect(Number.isSafeInteger(rehireEmploymentId), 'W1A_VS2_E2E_REHIRE_EMPLOYMENT_ID_INVALID').toBe(true);
    expect(rehireStartDate === '2025-04-01', 'W1A_VS2_E2E_REHIRE_START_DATE_MISSING').toBe(true);
    expect(rehireEmploymentId !== staffA.employmentId, 'W1A_VS2_E2E_REHIRE_EMPLOYMENT_ID_REUSED').toBe(true);
    const rehireStaffResponse = await browserApi(page, `/api/v1/staff/${staffA.id}`);
    expect(rehireStaffResponse.ok, 'W1A_VS2_E2E_REHIRE_GET_RECHECK_FAILED').toBe(true);
    const rehireCurrentEmployment = bodyRecord(bodyRecord(rehireStaffResponse.body).current_employment);
    expect(
      Number(rehireCurrentEmployment.staff_id) === staffA.id &&
        Number(rehireCurrentEmployment.id) === rehireEmploymentId &&
        rehireCurrentEmployment.start_date === rehireStartDate &&
        rehireCurrentEmployment.end_date == null,
      'W1A_VS2_E2E_REHIRE_FIELDS_MISMATCH',
    ).toBe(true);

    const staffAReentryQualificationTab = qualificationTab(page);
    await staffAReentryQualificationTab.click();
    const sourceForm = await ensureForm(
      page,
      'staff-qualification-form',
      /서비스 제공자격.*(?:추가|등록)/,
      'W1A_VS2_E2E_QUALIFICATION_FORM_MISSING_REENTRY',
    );
    const sourceSelect = sourceForm.getByLabel(/근거.*자격증/);
    const sourceValues = await sourceSelect.locator('option').evaluateAll((options) =>
      options.map((option) => option.value).filter(Boolean),
    );
    expect(
      sourceValues.includes(String(sourceLicenseId)),
      'W1A_VS2_E2E_SAME_STAFF_SOURCE_OPTION_MISSING',
    ).toBe(true);
    const reentryQualificationStart = dateAfter(rehireStartDate);
    await fillQualificationForm(
      sourceForm,
      rehireEmploymentId,
      reentryQualificationStart,
      String(sourceLicenseId),
    );
    const sourceResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/staff/${staffA.id}/service-qualifications`) &&
        response.request().method() === 'POST',
    );
    await sourceForm.getByRole('button', { name: /등록|추가|저장/ }).click();
    const sourceResponse = await sourceResponsePromise;
    expect(sourceResponse.ok(), 'W1A_VS2_E2E_REENTRY_SOURCE_REUSE_FAILED').toBe(true);
    const sourceCapture = requestCaptures
      .filter(
        (capture) =>
          capture.method === 'POST' &&
          capture.url.includes(`/staff/${staffA.id}/service-qualifications`),
      )
      .at(-1);
    expect(sourceCapture !== undefined, 'W1A_VS2_E2E_REENTRY_SOURCE_REQUEST_MISSING').toBe(true);
    expect(
      Number(sourceCapture?.body.employment_id) === rehireEmploymentId &&
        Number(sourceCapture?.body.source_license_id) === sourceLicenseId,
      'W1A_VS2_E2E_REENTRY_SOURCE_REQUEST_FIELDS_MISMATCH',
    ).toBe(true);
    expectNoKeys(
      sourceCapture?.body ?? {},
      ['license_number', 'issued_date'],
      'W1A_VS2_E2E_QUALIFICATION_DUPLICATES_LICENSE_FACTS',
    );
    const storedAQualificationsResponse = await browserApi(
      page,
      `/api/v1/staff/${staffA.id}/service-qualifications`,
    );
    expect(
      storedAQualificationsResponse.ok,
      'W1A_VS2_E2E_REENTRY_QUALIFICATION_GET_RECHECK_FAILED',
    ).toBe(true);
    const storedAQualifications = bodyItems(storedAQualificationsResponse.body);
    expect(storedAQualifications.length === 1, 'W1A_VS2_E2E_REENTRY_QUALIFICATION_NOT_STORED').toBe(true);
    const storedAQualification = storedAQualifications[0] ?? {};
    expect(
      Number(storedAQualification.staff_id) === staffA.id &&
        Number(storedAQualification.employment_id) === rehireEmploymentId &&
        storedAQualification.start_date === reentryQualificationStart &&
        Number(storedAQualification.source_license_id) === sourceLicenseId,
      'W1A_VS2_E2E_REENTRY_QUALIFICATION_FIELDS_MISMATCH',
    ).toBe(true);
    await expect(page.getByTestId('staff-qualification-row'), 'W1A_VS2_E2E_REENTRY_DOM_REFETCH_MISSING').toHaveCount(1);
    await expectNoHorizontalOverflow(page, 'W1A_VS2_E2E_REENTRY_HORIZONTAL_OVERFLOW');

    // Start A -> B -> browser-back from a known project search without touching existing rows.
    await selectStaffBySearch(page, staffB.name, 'W1A_VS2_CONTEXT_HISTORY_SEED_B');
    await selectStaffBySearch(page, staffA.name, 'W1A_VS2_CONTEXT_STAFF_A_SELECTION');
    const contextQualificationTabA = qualificationTab(page);
    await contextQualificationTabA.click();
    const search = page.getByLabel('직원 검색', { exact: true });
    await search.fill(runKey);
    await page.getByRole('button', { name: '검색', exact: true }).click();
    const sort = page.getByLabel(/정렬/);
    await expect(sort, 'W1A_VS2_E2E_LIST_SORT_CONTROL_MISSING').toBeVisible();
    const sortOptions = await sort.locator('option').evaluateAll((options) =>
      options.map((option) => option.value).filter(Boolean),
    );
    expect(sortOptions.length > 1, 'W1A_VS2_E2E_LIST_SORT_OPTIONS_MISSING').toBe(true);
    const selectedSortValue = sortOptions[1] ?? '';
    await sort.selectOption(selectedSortValue);
    const nextPage = page.getByRole('button', { name: /다음 페이지|next/i });
    await expect(nextPage, 'W1A_VS2_E2E_LIST_PAGINATION_CONTROL_MISSING').toBeVisible();
    const pageTwoResponsePromise = page
      .waitForResponse(
        (response) =>
          /\/api\/v1\/staff(?:\?|$)/.test(response.url()) &&
          /[?&]page=2(?:&|$)/.test(response.url()) &&
          response.request().method() === 'GET',
        { timeout: 5000 },
      )
      .catch(() => null);
    await nextPage.click();
    const pageTwoResponse = await pageTwoResponsePromise;
    expect(
      pageTwoResponse !== null || listRequests(requestCaptures).some((capture) => /[?&]page=2(?:&|$)/.test(capture.url)),
      'W1A_VS2_E2E_LIST_PAGE_REQUEST_MISSING',
    ).toBe(true);
    const listScroll = page.locator('[data-testid="staff-list-scroll"], .staff-list');
    await expect(listScroll, 'W1A_VS2_E2E_LIST_SCROLL_SURFACE_MISSING').toBeVisible();
    await expect(
      listScroll.locator(':scope > button'),
      'W1A_VS2_E2E_LIST_SCROLL_REAL_ROW_MISSING',
    ).toHaveCount(1);
    const originalListScrollStyle = await listScroll.evaluate((element) => {
      const original = {
        height: element.style.height,
        maxHeight: element.style.maxHeight,
      };
      element.style.height = '64px';
      element.style.maxHeight = '64px';
      return original;
    });
    const listScrollMetrics = await listScroll.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }));
    expect(
      listScrollMetrics.scrollHeight > listScrollMetrics.clientHeight,
      'W1A_VS2_E2E_LIST_SCROLL_OVERFLOW_MISSING',
    ).toBe(true);
    const retainedScrollTop = await listScroll.evaluate((element) => {
      const maxScrollTop = element.scrollHeight - element.clientHeight;
      element.scrollTop = Math.min(32, maxScrollTop);
      element.dispatchEvent(new Event('scroll', { bubbles: true }));
      return element.scrollTop;
    });
    expect(
      retainedScrollTop > 0,
      'W1A_VS2_E2E_LIST_SCROLL_NOT_RETAINED',
    ).toBe(true);

    const listRequestCountBeforeB = listRequests(requestCaptures).length;
    await clickStaffFromCurrentList(page, staffB.name, 'W1A_VS2_CONTEXT_STAFF_B_SELECTION');
    const contextQualificationTabB = qualificationTab(page);
    await contextQualificationTabB.click();
    await assertListContext(
      page,
      listRequests(requestCaptures).slice(listRequestCountBeforeB),
      selectedSortValue,
      retainedScrollTop,
      runKey,
      'W1A_VS2_E2E_CONTEXT_AFTER_B',
    );
    await expect(page.getByTestId('staff-detail-workspace'), 'W1A_VS2_E2E_B_DETAIL_MISSING').toContainText(
      staffB.name,
    );

    const listRequestCountBeforeBack = listRequests(requestCaptures).length;
    await page.goBack();
    await expect(page.getByTestId('staff-detail-workspace'), 'W1A_VS2_E2E_BACK_TARGET_A_MISSING').toContainText(
      staffA.name,
    );
    await assertListContext(
      page,
      listRequests(requestCaptures).slice(listRequestCountBeforeBack),
      selectedSortValue,
      retainedScrollTop,
      runKey,
      'W1A_VS2_E2E_CONTEXT_AFTER_BACK',
    );

    await Promise.all(responseSurfacePromises);
    const responseSurface = responseSurfaces.join('\n');
    const requestSurface = JSON.stringify(requestCaptures);
    const domSurface = await page.locator('body').innerText();
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(
        `${responseSurface}\n${requestSurface}\n${domSurface}`,
      ),
      'W1A_VS2_E2E_INTERNAL_ERROR_OR_SECRET_LEAKED',
    ).toBe(true);
    expect(popupCount, 'W1A_VS2_E2E_UNEXPECTED_POPUP').toBe(0);
    await expectNoHorizontalOverflow(page, 'W1A_VS2_E2E_FINAL_HORIZONTAL_OVERFLOW');
    await listScroll.evaluate((element, original) => {
      element.style.height = original.height;
      element.style.maxHeight = original.maxHeight;
    }, originalListScrollStyle);
  });
});
