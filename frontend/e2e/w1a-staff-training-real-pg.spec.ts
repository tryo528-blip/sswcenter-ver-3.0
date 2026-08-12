import { expect, test, type Page } from 'playwright/test';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

const realPgHarnessEnabled = process.env.SSWCENTER_W1A_VS3_REAL_PG === '1';

const TRAINING_COURSES = [
  { code: 'NEW_HIRE_ORIENTATION', display_name: '신규직원교육', cycle_type: 'ON_HIRE' },
  { code: 'ELDER_RIGHTS', display_name: '노인인권', cycle_type: 'HALF_YEAR' },
  {
    code: 'DISABLED_ABUSE',
    display_name: '장애인학대 신고의무자교육',
    cycle_type: 'ANNUAL',
  },
  { code: 'ELDER_ABUSE', display_name: '노인학대 신고의무자교육', cycle_type: 'ANNUAL' },
  { code: 'SEXUAL_HARASSMENT', display_name: '직장 내 성희롱 예방교육', cycle_type: 'ANNUAL' },
  { code: 'WORKPLACE_BULLYING', display_name: '직장 내 괴롭힘 예방교육', cycle_type: 'ANNUAL' },
  { code: 'PRIVACY', display_name: '개인정보보호교육', cycle_type: 'ANNUAL' },
] as const;

type JsonRecord = Record<string, unknown>;

type StaffFixture = {
  employmentEnd: string | null;
  employmentId: number;
  employmentStart: string;
  id: number;
  name: string;
};

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

function sameTrainingCourses(actual: unknown): boolean {
  if (!Array.isArray(actual)) return false;
  const observed = actual.map((item) => {
    const record = bodyRecord(item);
    return {
      code: String(record.code ?? ''),
      display_name: String(record.display_name ?? ''),
      cycle_type: String(record.cycle_type ?? ''),
    };
  });
  return JSON.stringify(observed) === JSON.stringify(TRAINING_COURSES);
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

async function expectNoHorizontalOverflow(page: Page, marker: string): Promise<void> {
  const hasOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasOverflow, marker).toBe(false);
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
  return {
    employmentEnd: typeof employment.end_date === 'string' ? employment.end_date : null,
    employmentId,
    employmentStart:
      typeof employment.start_date === 'string' ? employment.start_date : '2025-01-01',
    id: staffId,
    name,
  };
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
  const search = page.getByLabel('직원 검색', { exact: true });
  const sort = page.getByLabel(/정렬/);
  const scroll = page.locator('[data-testid="staff-list-scroll"], .staff-list');
  const tab = page.getByRole('tab', { name: '교육', exact: true });
  expect(await search.inputValue(), `${marker}_SEARCH_CONTEXT_LOST`).toBe(searchValue);
  await expect(sort, `${marker}_SORT_MISSING`).toHaveValue(selectedSort);
  await expect(tab, `${marker}_EDUCATION_TAB_MISSING`).toHaveAttribute('aria-selected', 'true');
  const scrollTop = await scroll.evaluate((element) => element.scrollTop);
  expect(scrollTop, `${marker}_SCROLL_OFFSET_CHANGED`).toBe(retainedScrollTop);
  expect(scrollTop > 0, `${marker}_SCROLL_CONTEXT_LOST`).toBe(true);
  const pageIndicator = page.getByTestId('staff-page-indicator');
  const pageTwoVisible =
    (await pageIndicator.count()) > 0 && /(^|\D)2(\D|$)/.test(await pageIndicator.innerText());
  const pageTwoRequested = captures.some((capture) => /[?&]page=2(?:&|$)/.test(capture.url));
  expect(pageTwoVisible || pageTwoRequested, `${marker}_PAGE_CONTEXT_LOST`).toBe(true);
}

test.describe('W1A-VS3 staff training real PostgreSQL RED contract', () => {
  test('requires training contract, lifecycle state, context retention, and leak-safe UI', async ({
    page,
    request,
  }, testInfo) => {
    let popupCount = 0;
    const requestCaptures: RequestCapture[] = [];
    const responseSurfaces: string[] = [];
    const responsePromises: Promise<void>[] = [];

    // Install all observers before bootstrap, login, navigation, or any UI action.
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
      'W1A_VS3_PG_DEPENDENCY_BLOCKER: authenticated real-PostgreSQL harness is not provisioned',
    );
    expect(
      ['chromium-1440x1000', 'chromium-1440x900', 'chromium-1366x768'].includes(
        testInfo.project.name,
      ),
      'W1A_VS3_VIEWPORT_PROJECT_MISSING',
    ).toBe(true);

    const bootstrapStatus = await request.get('/api/bootstrap/status');
    const bootstrapStatusRaw = await bootstrapStatus.text();
    responseSurfaces.push(bootstrapStatusRaw);
    expect(bootstrapStatus.ok(), 'W1A_VS3_BOOTSTRAP_STATUS_FAILED').toBe(true);
    if (bodyRecord(parseJsonText(bootstrapStatusRaw)).bootstrap_required === true) {
      const bootstrap = await request.post('/api/bootstrap', {
        data: {
          admin_name: 'W1A-VS3 합성 관리자',
          birth_date: '1980-01-01',
          center_name: 'W1A-VS3 합성 센터',
          pin: '123456',
          sex_code: 'MALE',
          start_date: '2025-01-01',
        },
      });
      responseSurfaces.push(await bootstrap.text());
      expect(bootstrap.ok(), 'W1A_VS3_BOOTSTRAP_FAILED').toBe(true);
    }

    await ensureAuthenticated(page, '123456', 'W1A_VS3_BROWSER_LOGIN_MISSING');
    await expectNoHorizontalOverflow(page, 'W1A_VS3_SHELL_HORIZONTAL_OVERFLOW');
    const runKey = buildRunKey(testInfo);
    const staffA = await createProjectStaff(
      page,
      `W1A-VS3-${runKey}-A`,
      runKey,
      1,
      'W1A_VS3_STAFF_A',
    );
    const staffB = await createProjectStaff(
      page,
      `W1A-VS3-${runKey}-B`,
      runKey,
      2,
      'W1A_VS3_STAFF_B',
    );
    expect(staffA.id !== staffB.id, 'W1A_VS3_STAFF_PROJECT_ISOLATION_MISSING').toBe(true);

    await selectStaffBySearch(page, staffA.name, 'W1A_VS3_STAFF_A_SELECTION');
    const educationTab = page.getByRole('tab', { name: '교육', exact: true });
    await expect(educationTab, 'W1A_VS3_E2E_EDUCATION_TAB_MISSING').toBeVisible();
    await educationTab.click();

    const coursesResponse = await browserApi(page, '/api/v1/staff/training-courses');
    expect(coursesResponse.ok, 'W1A_VS3_E2E_COURSE_ROUTE_MISSING').toBe(true);
    expect(
      sameTrainingCourses(bodyItems(coursesResponse.body)),
      'W1A_VS3_E2E_EXACT_COURSE_ORDER_MISMATCH',
    ).toBe(true);
    await expect(page.getByTestId('staff-onboarding-training-panel'), 'W1A_VS3_E2E_ONBOARDING_PANEL_MISSING').toBeVisible();
    await expect(page.getByTestId('staff-periodic-training-panel'), 'W1A_VS3_E2E_PERIODIC_PANEL_MISSING').toBeVisible();
    await expect(page.getByTestId('training-course-row'), 'W1A_VS3_E2E_COURSE_ROWS_MISSING').toHaveCount(7);

    const onboardingResponse = await browserApi(
      page,
      `/api/v1/staff/${staffA.id}/onboarding-trainings`,
    );
    expect(onboardingResponse.ok, 'W1A_VS3_E2E_ONBOARDING_GET_MISSING').toBe(true);
    const onboardingItems = bodyItems(onboardingResponse.body);
    expect(onboardingItems.length === 1, 'W1A_VS3_E2E_ONBOARDING_INITIAL_ROW_MISSING').toBe(true);
    const initialOnboarding = onboardingItems[0] ?? {};
    expect(
      Number(initialOnboarding.staff_id) === staffA.id &&
        Number(initialOnboarding.employment_id) === staffA.employmentId &&
        initialOnboarding.course_code === 'NEW_HIRE_ORIENTATION' &&
        initialOnboarding.completed === false,
      'W1A_VS3_E2E_ONBOARDING_FIELDS_MISMATCH',
    ).toBe(true);

    const periodicCreate = await browserApi(
      page,
      `/api/v1/staff/${staffA.id}/periodic-trainings`,
      'POST',
      {
        course_code: 'ELDER_RIGHTS',
        expected_row_version: 1,
        period_key: '2026-H1',
      },
    );
    expect(periodicCreate.ok, 'W1A_VS3_E2E_PERIODIC_CREATE_MISSING').toBe(true);
    const periodicItem = bodyRecord(periodicCreate.body);
    expect(
      Number(periodicItem.staff_id) === staffA.id &&
        periodicItem.course_code === 'ELDER_RIGHTS' &&
        periodicItem.period_key === '2026-H1',
      'W1A_VS3_E2E_PERIODIC_FIELDS_MISMATCH',
    ).toBe(true);

    const forbiddenKeys = [
      'training_hours',
      'completed_date',
      'completion_date',
      'completion_center',
      'file_id',
      'evidence_file_id',
      'task_id',
      'assignment_id',
    ];
    expectNoKeys(periodicItem, forbiddenKeys, 'W1A_VS3_E2E_FORBIDDEN_TRAINING_KEYS_EXPOSED');
    const onboardingBody = bodyRecord(onboardingResponse.body);
    expectNoKeys(onboardingBody, forbiddenKeys, 'W1A_VS3_E2E_ONBOARDING_FORBIDDEN_KEYS_EXPOSED');
    const pageText = await page.locator('body').textContent();
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(
        `${JSON.stringify(periodicCreate.body)}\n${pageText ?? ''}`,
      ),
      'W1A_VS3_E2E_INTERNAL_ERROR_OR_SECRET_LEAKED',
    ).toBe(true);

    // Re-entry must create a new onboarding row while the same periodic period survives.
    await page.getByRole('button', { name: /재직 종료/ }).click();
    await page.getByLabel(/퇴사일/).fill('2026-03-01');
    const closeResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/staff/${staffA.id}/employments/`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /종료 확정/ }).click();
    expect((await closeResponsePromise).ok(), 'W1A_VS3_E2E_CLOSE_EMPLOYMENT_FAILED').toBe(true);
    await page.getByRole('button', { name: /재입사/ }).click();
    await page.getByLabel(/재입사일/).fill('2026-04-01');
    const rehireResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/employments`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /재입사 등록/ }).click();
    const rehireResponse = await rehireResponsePromise;
    expect(rehireResponse.ok(), 'W1A_VS3_E2E_REHIRE_FAILED').toBe(true);
    const rehireEmploymentId = Number(bodyRecord(await rehireResponse.json()).id);
    expect(rehireEmploymentId !== staffA.employmentId, 'W1A_VS3_E2E_REHIRE_EMPLOYMENT_REUSED').toBe(true);
    const onboardingAfterRehire = await browserApi(
      page,
      `/api/v1/staff/${staffA.id}/onboarding-trainings`,
    );
    expect(onboardingAfterRehire.ok, 'W1A_VS3_E2E_REENTRY_ONBOARDING_GET_MISSING').toBe(true);
    expect(
      bodyItems(onboardingAfterRehire.body).some(
        (item) => Number(item.employment_id) === rehireEmploymentId && item.completed === false,
      ),
      'W1A_VS3_E2E_REENTRY_NEW_ONBOARDING_MISSING',
    ).toBe(true);
    const periodicAfterRehire = await browserApi(
      page,
      `/api/v1/staff/${staffA.id}/periodic-trainings`,
    );
    expect(periodicAfterRehire.ok, 'W1A_VS3_E2E_REENTRY_PERIODIC_GET_MISSING').toBe(true);
    expect(
      bodyItems(periodicAfterRehire.body).some(
        (item) =>
          item.course_code === 'ELDER_RIGHTS' &&
          item.period_key === '2026-H1' &&
          item.completed === true,
      ),
      'W1A_VS3_E2E_PERIODIC_SAME_PERIOD_NOT_RETAINED',
    ).toBe(true);

    // Live A -> B -> browser-back context, with a real overflow fixture and fresh locators.
    await selectStaffBySearch(page, staffB.name, 'W1A_VS3_CONTEXT_SEED_B');
    await selectStaffBySearch(page, staffA.name, 'W1A_VS3_CONTEXT_STAFF_A');
    await page.getByRole('tab', { name: '교육', exact: true }).click();
    const search = page.getByLabel('직원 검색', { exact: true });
    await search.fill(runKey);
    await page.getByRole('button', { name: '검색', exact: true }).click();
    const sort = page.getByLabel(/정렬/);
    const sortOptions = await sort.locator('option').evaluateAll((options) =>
      options.map((option) => option.value).filter(Boolean),
    );
    const selectedSort = sortOptions[1] ?? sortOptions[0] ?? '';
    await sort.selectOption(selectedSort);
    const nextPage = page.getByRole('button', { name: /다음 페이지|next/i });
    const pageTwoResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        response.url().includes('/api/v1/staff') &&
        /[?&]page=2(?:&|$)/.test(response.url()),
    );
    await nextPage.click();
    const pageTwoResponse = await pageTwoResponsePromise;
    const pageTwoBody = bodyRecord(await pageTwoResponse.json());
    expect(
      bodyItems(pageTwoBody).some((item) => Number(item.id) === staffB.id),
      'W1A_VS3_E2E_PAGE_TWO_RESPONSE_MISMATCH',
    ).toBe(true);
    await expect(page.getByTestId('staff-page-indicator')).toHaveText('2');
    await expect(
      page.locator('.staff-list > button').filter({ hasText: staffB.name }).first(),
      'W1A_VS3_E2E_PAGE_TWO_B_ROW_NOT_READY',
    ).toBeVisible();
    await expect(page.locator('.staff-list > button').filter({ hasText: staffA.name })).toHaveCount(0);
    const scroll = page.locator('[data-testid="staff-list-scroll"], .staff-list');
    const originalStyle = await scroll.evaluate((element) => ({
      height: element.style.height,
      maxHeight: element.style.maxHeight,
    }));
    const scrollFixture = await page.addStyleTag({
      content:
        '[data-testid="staff-list-scroll"] { height: 8px !important; max-height: 8px !important; overflow-y: auto !important; }',
    });
    const metrics = await scroll.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    }));
    expect(metrics.scrollHeight > metrics.clientHeight, 'W1A_VS3_E2E_SCROLL_OVERFLOW_MISSING').toBe(true);
    const retainedScrollTop = await scroll.evaluate((element) => {
      element.scrollTop = 1;
      element.dispatchEvent(new Event('scroll', { bubbles: true }));
      return element.scrollTop;
    });
    expect(retainedScrollTop > 0, 'W1A_VS3_E2E_SCROLL_EVENT_NOT_RETAINED').toBe(true);
    await clickStaffFromCurrentList(page, staffB.name, 'W1A_VS3_CONTEXT_STAFF_B');
    await page.getByRole('tab', { name: '교육', exact: true }).click();
    await assertListContext(
      page,
      requestCaptures,
      selectedSort,
      retainedScrollTop,
      runKey,
      'W1A_VS3_CONTEXT_AFTER_B',
    );
    await expect(page.getByTestId('staff-detail-workspace'), 'W1A_VS3_CONTEXT_B_DETAIL_MISSING').toContainText(
      staffB.name,
    );
    await page.goBack();
    await expect(page.getByTestId('staff-detail-workspace'), 'W1A_VS3_BACK_TARGET_A_DETAIL_MISSING').toContainText(
      staffA.name,
    );
    await assertListContext(
      page,
      requestCaptures,
      selectedSort,
      retainedScrollTop,
      runKey,
      'W1A_VS3_CONTEXT_AFTER_BACK',
    );
    await Promise.all(responsePromises);
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(
        `${responseSurfaces.join('\n')}\n${JSON.stringify(requestCaptures)}\n${await page.locator('body').innerText()}`,
      ),
      'W1A_VS3_E2E_RESPONSE_DOM_LEAK',
    ).toBe(true);
    expect(popupCount, 'W1A_VS3_E2E_UNEXPECTED_POPUP').toBe(0);
    await expectNoHorizontalOverflow(page, 'W1A_VS3_E2E_FINAL_HORIZONTAL_OVERFLOW');
    await scroll.evaluate((element, style) => {
      element.style.height = style.height;
      element.style.maxHeight = style.maxHeight;
    }, originalStyle);
    await scrollFixture.evaluate((element) => element.remove());
  });
});
