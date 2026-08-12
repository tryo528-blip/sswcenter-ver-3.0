import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { expect, test, type Page } from 'playwright/test';

test.use({ trace: 'off', video: 'off', screenshot: 'off' });

const execFileAsync = promisify(execFile);
const realPgHarnessEnabled = process.env.SSWCENTER_W1A_VS4_REAL_PG === '1';

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

type TrustedHealthFixture = {
  available: boolean;
  factIds: number[];
  requirementIds: number[];
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

async function seedTrustedHealthFixture(
  staff: StaffFixture,
  runKey: string,
): Promise<TrustedHealthFixture> {
  const relationExists = await runTrustedSql(
    "SELECT to_regclass('erp.staff_health_check_requirement') IS NOT NULL",
  );
  if (relationExists !== 't') return { available: false, factIds: [], requirementIds: [] };

  const actorId = Number(
    await runTrustedSql(
      "SELECT id FROM erp.user_account WHERE role_code = 'ADMIN' ORDER BY id LIMIT 1",
    ),
  );
  if (!Number.isSafeInteger(actorId)) throw new Error('trusted actor fixture is missing');

  const firstFactId = Number(
    await runTrustedSql(
      `INSERT INTO erp.staff_health_check
        (staff_id, employment_id, check_date, check_type_code, result_note,
         created_by_account_id, updated_by_account_id)
       VALUES (${staff.id}, ${staff.employmentId}, DATE '2026-01-15', 'GENERAL',
         ${sqlQuote(`VS4 ${runKey} fact one`)}, ${actorId}, ${actorId})
       RETURNING id`,
    ),
  );
  const secondFactId = Number(
    await runTrustedSql(
      `INSERT INTO erp.staff_health_check
        (staff_id, employment_id, check_date, check_type_code, result_note,
         created_by_account_id, updated_by_account_id)
       VALUES (${staff.id}, ${staff.employmentId}, DATE '2026-01-15', 'GENERAL',
         ${sqlQuote(`VS4 ${runKey} fact two`)}, ${actorId}, ${actorId})
       RETURNING id`,
    ),
  );
  const targetPrefix = `VS4_${runKey.replace(/[^A-Za-z0-9]+/g, '_')}`;
  const completeId = Number(
    await runTrustedSql(
      `INSERT INTO erp.staff_health_check_requirement
        (staff_id, employment_id, target_key, target_rule_version_code, status,
         health_check_id, exempt_reason_text, created_by_account_id, updated_by_account_id)
       VALUES (${staff.id}, ${staff.employmentId}, ${sqlQuote(`${targetPrefix}_COMPLETE`)},
         'VS4_RULE_1', 'COMPLETE', ${firstFactId}, NULL, ${actorId}, ${actorId})
       RETURNING id`,
    ),
  );
  const incompleteId = Number(
    await runTrustedSql(
      `INSERT INTO erp.staff_health_check_requirement
        (staff_id, employment_id, target_key, target_rule_version_code, status,
         health_check_id, exempt_reason_text, created_by_account_id, updated_by_account_id)
       VALUES (${staff.id}, ${staff.employmentId}, ${sqlQuote(`${targetPrefix}_INCOMPLETE`)},
         'VS4_RULE_1', 'INCOMPLETE', NULL, NULL, ${actorId}, ${actorId})
       RETURNING id`,
    ),
  );
  const exemptId = Number(
    await runTrustedSql(
      `INSERT INTO erp.staff_health_check_requirement
        (staff_id, employment_id, target_key, target_rule_version_code, status,
         health_check_id, exempt_reason_text, created_by_account_id, updated_by_account_id)
       VALUES (${staff.id}, ${staff.employmentId}, ${sqlQuote(`${targetPrefix}_EXEMPT`)},
         'VS4_RULE_1', 'EXEMPT', NULL, ${sqlQuote(`VS4 ${runKey} exemption`)},
         ${actorId}, ${actorId})
       RETURNING id`,
    ),
  );
  const ids = [firstFactId, secondFactId, completeId, incompleteId, exemptId];
  if (ids.some((id) => !Number.isSafeInteger(id))) {
    throw new Error('trusted health fixture returned an invalid id');
  }
  return {
    available: true,
    factIds: [firstFactId, secondFactId],
    requirementIds: [completeId, incompleteId, exemptId],
  };
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
            // Do not expose malformed cookie contents.
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
  const tab = page.getByRole('tab', { name: '검진', exact: true });
  expect(await search.inputValue(), `${marker}_SEARCH_CONTEXT_LOST`).toBe(searchValue);
  await expect(sort, `${marker}_SORT_MISSING`).toHaveValue(selectedSort);
  await expect(tab, `${marker}_HEALTH_TAB_CONTEXT_LOST`).toHaveAttribute('aria-selected', 'true');
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

test.describe('W1A-VS4 staff health-check real PostgreSQL RED contract', () => {
  test('requires separated health ledgers, trusted states, context, and leak-safe UI', async ({
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

    if (!realPgHarnessEnabled) {
      throw new Error(
        'W1A_VS4_PG_DEPENDENCY_BLOCKER: authenticated real-PostgreSQL harness is not provisioned',
      );
    }
    expect(
      ['chromium-1440x1000', 'chromium-1440x900', 'chromium-1366x768'].includes(
        testInfo.project.name,
      ),
      'W1A_VS4_VIEWPORT_PROJECT_MISSING',
    ).toBe(true);

    const bootstrapStatus = await request.get('/api/bootstrap/status');
    const bootstrapStatusRaw = await bootstrapStatus.text();
    responseSurfaces.push(bootstrapStatusRaw);
    expect(bootstrapStatus.ok(), 'W1A_VS4_BOOTSTRAP_STATUS_FAILED').toBe(true);
    if (bodyRecord(parseJsonText(bootstrapStatusRaw)).bootstrap_required === true) {
      const bootstrap = await request.post('/api/bootstrap', {
        data: {
          admin_name: 'W1A-VS4 합성 관리자',
          birth_date: '1980-01-01',
          center_name: 'W1A-VS4 합성 센터',
          pin: '123456',
          sex_code: 'MALE',
          start_date: '2025-01-01',
        },
      });
      responseSurfaces.push(await bootstrap.text());
      expect(bootstrap.ok(), 'W1A_VS4_BOOTSTRAP_FAILED').toBe(true);
    }

    await ensureAuthenticated(page, '123456', 'W1A_VS4_BROWSER_LOGIN_MISSING');
    await expectNoHorizontalOverflow(page, 'W1A_VS4_SHELL_HORIZONTAL_OVERFLOW');
    const runKey = buildRunKey(testInfo);
    const staffA = await createProjectStaff(
      page,
      `W1A-VS4-${runKey}-A`,
      runKey,
      1,
      'W1A_VS4_STAFF_A',
    );
    const staffB = await createProjectStaff(
      page,
      `W1A-VS4-${runKey}-B`,
      runKey,
      2,
      'W1A_VS4_STAFF_B',
    );
    expect(staffA.id !== staffB.id, 'W1A_VS4_STAFF_PROJECT_ISOLATION_MISSING').toBe(true);

    let trustedFixture: TrustedHealthFixture;
    try {
      trustedFixture = await seedTrustedHealthFixture(staffA, runKey);
    } catch {
      expect(false, 'W1A_VS4_TRUSTED_FIXTURE_HARNESS_FAILURE').toBe(true);
      return;
    }

    await selectStaffBySearch(page, staffA.name, 'W1A_VS4_STAFF_A_SELECTION');
    const healthTab = page.getByRole('tab', { name: '검진', exact: true });
    await expect(healthTab, 'W1A_VS4_E2E_HEALTH_TAB_MISSING').toBeVisible();
    await healthTab.click();
    expect(trustedFixture.available, 'W1A_VS4_E2E_TRUSTED_REQUIREMENT_FIXTURE_MISSING').toBe(true);
    expect(trustedFixture.factIds.length, 'W1A_VS4_E2E_FACT_FIXTURE_MISSING').toBe(2);
    expect(trustedFixture.requirementIds.length, 'W1A_VS4_E2E_REQUIREMENT_FIXTURE_MISSING').toBe(3);

    await expect(
      page.getByTestId('staff-health-check-facts-panel'),
      'W1A_VS4_E2E_FACT_LEDGER_PANEL_MISSING',
    ).toBeVisible();
    await expect(
      page.getByTestId('staff-health-check-requirements-panel'),
      'W1A_VS4_E2E_REQUIREMENT_LEDGER_PANEL_MISSING',
    ).toBeVisible();
    await expect(page.getByTestId('health-check-fact-row')).toHaveCount(2);
    await expect(page.getByTestId('health-check-requirement-row')).toHaveCount(3);
    await expect(page.getByTestId('health-status-COMPLETE')).toHaveAttribute(
      'data-health-check-id',
      String(trustedFixture.factIds[0]),
    );
    await expect(page.getByTestId('health-status-INCOMPLETE')).not.toHaveAttribute('data-health-check-id');
    await expect(page.getByTestId('health-status-EXEMPT')).toHaveAttribute(
      'data-exempt-reason',
      /.+/,
    );

    const capabilities = await browserApi(page, '/api/v1/session-capabilities');
    expect(capabilities.ok, 'W1A_VS4_E2E_CAPABILITIES_MISSING').toBe(true);
    await expect(page.getByTestId('health-check-fact-add'), 'W1A_VS4_E2E_FACT_WRITE_CONTROL_MISSING').toBeVisible();
    await page.getByTestId('health-check-fact-add').click();
    await page.getByLabel(/검진일/).fill('2026-01-15');
    await page.getByRole('combobox', { name: /재직/ }).selectOption(String(staffA.employmentId));
    await page.getByRole('combobox', { name: /검진 유형|검진유형/ }).selectOption('GENERAL');
    await page.getByLabel(/결과메모/).fill('VS4 E2E fact create');
    const createFactResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/health-checks') && response.request().method() === 'POST',
    );
    const createFactRefetch = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/health-checks`) &&
        response.request().method() === 'GET',
    );
    await page.getByRole('button', { name: /검진사실 저장/ }).click();
    const createdFactResponse = await createFactResponse;
    expect(createdFactResponse.ok(), 'W1A_VS4_E2E_FACT_CREATE_FAILED').toBe(true);
    const createdFact = bodyRecord(await createdFactResponse.json());
    expect(Number(createdFact.staff_id), 'W1A_VS4_E2E_FACT_CREATE_STAFF_MISMATCH').toBe(staffA.id);
    expect(Number(createdFact.employment_id), 'W1A_VS4_E2E_FACT_CREATE_EMPLOYMENT_MISMATCH').toBe(
      staffA.employmentId,
    );
    expect(Number(createdFact.row_version), 'W1A_VS4_E2E_FACT_CREATE_VERSION_MISSING').toBe(1);
    const createCapture = requestCaptures
      .filter((capture) => capture.method === 'POST' && capture.url.endsWith('/health-checks'))
      .at(-1);
    expect(createCapture?.body, 'W1A_VS4_E2E_FACT_CREATE_PAYLOAD_MISMATCH').toEqual({
      check_date: '2026-01-15',
      check_type_code: 'GENERAL',
      employment_id: staffA.employmentId,
      result_note: 'VS4 E2E fact create',
    });
    const createdFactList = bodyRecord(await (await createFactRefetch).json());
    const createdFactItems = Array.isArray(createdFactList.items) ? createdFactList.items : [];
    expect(
      createdFactItems.some(
        (item) =>
          Number(bodyRecord(item).staff_id) === staffA.id &&
          Number(bodyRecord(item).employment_id) === staffA.employmentId,
      ),
      'W1A_VS4_E2E_FACT_CREATE_GET_MISMATCH',
    ).toBe(true);
    await expect(page.getByTestId('health-check-fact-row')).toHaveCount(3);

    const factRow = page
      .getByTestId('health-check-fact-row')
      .filter({ hasText: `VS4 ${runKey} fact two` })
      .first();
    await factRow.getByRole('button', { name: /검진사실 수정/ }).click();
    await page.getByLabel(/검진일/).fill('2026-01-15');
    await page.getByLabel(/결과메모/).fill('VS4 E2E fact update');
    const updateFactResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/health-checks/') && response.request().method() === 'PATCH',
    );
    const updateFactRefetch = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/health-checks`) &&
        response.request().method() === 'GET',
    );
    await page.getByRole('button', { name: /검진사실 저장/ }).click();
    const updatedFactResponse = await updateFactResponse;
    expect(updatedFactResponse.ok(), 'W1A_VS4_E2E_FACT_UPDATE_FAILED').toBe(true);
    const updatedFact = bodyRecord(await updatedFactResponse.json());
    expect(Number(updatedFact.staff_id), 'W1A_VS4_E2E_FACT_UPDATE_STAFF_MISMATCH').toBe(staffA.id);
    expect(Number(updatedFact.employment_id), 'W1A_VS4_E2E_FACT_UPDATE_EMPLOYMENT_MISMATCH').toBe(
      staffA.employmentId,
    );
    expect(Number(updatedFact.row_version), 'W1A_VS4_E2E_FACT_UPDATE_VERSION_MISSING').toBe(2);
    const updateCapture = requestCaptures
      .filter((capture) => capture.method === 'PATCH' && /\/health-checks\/\d+$/.test(capture.url))
      .at(-1);
    expect(updateCapture?.body, 'W1A_VS4_E2E_FACT_UPDATE_PAYLOAD_MISMATCH').toEqual({
      check_date: '2026-01-15',
      check_type_code: 'GENERAL',
      employment_id: staffA.employmentId,
      result_note: 'VS4 E2E fact update',
      expected_row_version: 1,
    });
    const updatedFactList = bodyRecord(await (await updateFactRefetch).json());
    const updatedFactItems = Array.isArray(updatedFactList.items) ? updatedFactList.items : [];
    expect(
      updatedFactItems.some((item) => bodyRecord(item).result_note === 'VS4 E2E fact update'),
      'W1A_VS4_E2E_FACT_UPDATE_GET_MISMATCH',
    ).toBe(true);

    await page
      .getByTestId('health-check-fact-row')
      .filter({ hasText: 'VS4 E2E fact update' })
      .first()
      .getByRole('button', { name: /검진사실 무효화/ })
      .click();
    const invalidateFactResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/health-checks/') &&
        response.url().endsWith('/invalidate') &&
        response.request().method() === 'POST',
    );
    const invalidateFactRefetch = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/health-checks`) &&
        response.request().method() === 'GET',
    );
    await page.getByRole('button', { name: /검진사실 무효화 확정/ }).click();
    const invalidatedFactResponse = await invalidateFactResponse;
    expect(invalidatedFactResponse.ok(), 'W1A_VS4_E2E_FACT_INVALIDATE_FAILED').toBe(true);
    const invalidatedFact = bodyRecord(await invalidatedFactResponse.json());
    expect(Number(invalidatedFact.row_version), 'W1A_VS4_E2E_FACT_INVALIDATE_VERSION_MISSING').toBe(3);
    const invalidatedFactId = Number(invalidatedFact.id);
    expect(
      Number.isSafeInteger(invalidatedFactId) && invalidatedFactId > 0,
      'W1A_VS4_E2E_FACT_INVALIDATE_ID_MISSING',
    ).toBe(true);
    expect(
      typeof invalidatedFact.invalidated_at_utc === 'string' &&
        invalidatedFact.invalidated_at_utc.length > 0,
      'W1A_VS4_E2E_FACT_INVALIDATE_TIMESTAMP_MISSING',
    ).toBe(true);
    const replacementHealthCheckId = Number(invalidatedFact.replacement_health_check_id);
    expect(
      Number.isSafeInteger(replacementHealthCheckId) && replacementHealthCheckId > 0,
      'W1A_VS4_E2E_FACT_INVALIDATE_REPLACEMENT_ID_MISSING',
    ).toBe(true);
    const invalidateCapture = requestCaptures
      .filter(
        (capture) =>
          capture.method === 'POST' && /\/health-checks\/\d+\/invalidate$/.test(capture.url),
      )
      .at(-1);
    expect(invalidateCapture?.body, 'W1A_VS4_E2E_FACT_INVALIDATE_PAYLOAD_MISMATCH').toEqual({
      expected_row_version: 2,
    });
    const invalidatedFactList = bodyRecord(await (await invalidateFactRefetch).json());
    const activeFactItems = Array.isArray(invalidatedFactList.items)
      ? invalidatedFactList.items
      : [];
    expect(
      activeFactItems.some(
        (item) => Number(bodyRecord(item).id) === replacementHealthCheckId,
      ),
      'W1A_VS4_E2E_FACT_INVALIDATE_GET_MISMATCH',
    ).toBe(true);
    expect(
      activeFactItems.every((item) => Number(bodyRecord(item).id) !== invalidatedFactId),
      'W1A_VS4_E2E_FACT_INVALIDATE_ORIGINAL_STILL_ACTIVE',
    ).toBe(true);

    const completeRequirement = page
      .getByTestId('health-check-requirement-row')
      .filter({ hasText: /_COMPLETE/ })
      .first();
    await completeRequirement.getByRole('combobox', { name: /상태/ }).selectOption('INCOMPLETE');
    const incompleteRequirementResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/health-check-requirements/') &&
        response.request().method() === 'PATCH',
    );
    const incompleteRequirementRefetch = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/health-check-requirements`) &&
        response.request().method() === 'GET',
    );
    await completeRequirement.getByRole('button', { name: /상태 저장/ }).click();
    const incompleteResponse = await incompleteRequirementResponse;
    expect(incompleteResponse.ok(), 'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_FAILED').toBe(true);
    const incompleteBody = bodyRecord(await incompleteResponse.json());
    expect(Number(incompleteBody.staff_id), 'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_STAFF_MISMATCH').toBe(staffA.id);
    expect(Number(incompleteBody.employment_id), 'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_EMPLOYMENT_MISMATCH').toBe(
      staffA.employmentId,
    );
    expect(incompleteBody.status, 'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_STATUS_MISMATCH').toBe('INCOMPLETE');
    expect(Number(incompleteBody.row_version), 'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_VERSION_MISSING').toBe(2);
    const incompleteCapture = requestCaptures
      .filter(
        (capture) =>
          capture.method === 'PATCH' && /\/health-check-requirements\/\d+$/.test(capture.url),
      )
      .at(-1);
    expect(incompleteCapture?.body, 'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_PAYLOAD_MISMATCH').toEqual({
      status: 'INCOMPLETE',
      health_check_id: null,
      exempt_reason_text: null,
      expected_row_version: 1,
    });
    const incompleteList = bodyRecord(await (await incompleteRequirementRefetch).json());
    expect(
      (Array.isArray(incompleteList.items) ? incompleteList.items : []).some(
        (item) => bodyRecord(item).status === 'INCOMPLETE',
      ),
      'W1A_VS4_E2E_REQUIREMENT_INCOMPLETE_GET_MISMATCH',
    ).toBe(true);

    const exemptRequirement = page
      .getByTestId('health-check-requirement-row')
      .filter({ hasText: /_COMPLETE/ })
      .first();
    await exemptRequirement.getByRole('combobox', { name: /상태/ }).selectOption('EXEMPT');
    await exemptRequirement.getByLabel(/면제사유/).fill('VS4 E2E exemption');
    const exemptRequirementResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/health-check-requirements/') &&
        response.request().method() === 'PATCH',
    );
    const exemptRequirementRefetch = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/v1/staff/${staffA.id}/health-check-requirements`) &&
        response.request().method() === 'GET',
    );
    await exemptRequirement.getByRole('button', { name: /상태 저장/ }).click();
    const exemptResponse = await exemptRequirementResponse;
    expect(exemptResponse.ok(), 'W1A_VS4_E2E_REQUIREMENT_EXEMPT_FAILED').toBe(true);
    const exemptBody = bodyRecord(await exemptResponse.json());
    expect(exemptBody.status, 'W1A_VS4_E2E_REQUIREMENT_EXEMPT_STATUS_MISMATCH').toBe('EXEMPT');
    expect(Number(exemptBody.row_version), 'W1A_VS4_E2E_REQUIREMENT_EXEMPT_VERSION_MISSING').toBe(3);
    const exemptCapture = requestCaptures
      .filter(
        (capture) =>
          capture.method === 'PATCH' && /\/health-check-requirements\/\d+$/.test(capture.url),
      )
      .at(-1);
    expect(exemptCapture?.body, 'W1A_VS4_E2E_REQUIREMENT_EXEMPT_PAYLOAD_MISMATCH').toEqual({
      status: 'EXEMPT',
      health_check_id: null,
      exempt_reason_text: 'VS4 E2E exemption',
      expected_row_version: 2,
    });
    const exemptList = bodyRecord(await (await exemptRequirementRefetch).json());
    expect(
      (Array.isArray(exemptList.items) ? exemptList.items : []).some(
        (item) => bodyRecord(item).status === 'EXEMPT' && bodyRecord(item).exempt_reason_text,
      ),
      'W1A_VS4_E2E_REQUIREMENT_EXEMPT_GET_MISMATCH',
    ).toBe(true);

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
    const pageTwoResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'GET' &&
        response.url().includes('/api/v1/staff') &&
        /[?&]page=2(?:&|$)/.test(response.url()),
    );
    await nextPage.click();
    await pageTwoResponse;
    await expect(page.getByTestId('staff-page-indicator')).toHaveText('2');
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
    expect(metrics.scrollHeight > metrics.clientHeight, 'W1A_VS4_E2E_SCROLL_OVERFLOW_MISSING').toBe(true);
    const retainedScrollTop = await scroll.evaluate((element) => {
      element.scrollTop = 1;
      element.dispatchEvent(new Event('scroll', { bubbles: true }));
      return element.scrollTop;
    });
    expect(retainedScrollTop > 0, 'W1A_VS4_E2E_SCROLL_EVENT_NOT_RETAINED').toBe(true);

    const staffBButton = page
      .locator('.staff-list > button')
      .filter({ hasText: staffB.name })
      .first();
    await expect(staffBButton, 'W1A_VS4_CONTEXT_STAFF_B').toBeVisible();
    await staffBButton.dispatchEvent('click');
    await expect(
      page.getByTestId('staff-detail-workspace'),
      'W1A_VS4_CONTEXT_STAFF_B_DETAIL_MISSING',
    ).toBeVisible();
    await page.getByRole('tab', { name: '검진', exact: true }).click();
    await assertListContext(
      page,
      requestCaptures,
      selectedSort,
      retainedScrollTop,
      runKey,
      'W1A_VS4_CONTEXT_AFTER_B',
    );
    await expect(page.getByTestId('staff-detail-workspace')).toContainText(staffB.name);
    await page.goBack();
    await expect(page.getByTestId('staff-detail-workspace')).toContainText(staffA.name);
    await assertListContext(
      page,
      requestCaptures,
      selectedSort,
      retainedScrollTop,
      runKey,
      'W1A_VS4_CONTEXT_AFTER_BACK',
    );

    await Promise.all(responsePromises);
    const forbidden = /자동대상|D-day|업무카드|첨부|attachment|file_id|evidence_id|task_id/i;
    const visibleSurfaces = `${responseSurfaces.join('\n')}\n${await page.locator('body').innerText()}`;
    expect(forbidden.test(visibleSurfaces), 'W1A_VS4_E2E_FORBIDDEN_HEALTH_SURFACE_EXPOSED').toBe(false);
    expect(
      /(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(visibleSurfaces),
      'W1A_VS4_E2E_INTERNAL_ERROR_OR_SECRET_LEAKED',
    ).toBe(false);
    expect(popupCount, 'W1A_VS4_E2E_UNEXPECTED_POPUP').toBe(0);
    await expectNoHorizontalOverflow(page, 'W1A_VS4_E2E_FINAL_HORIZONTAL_OVERFLOW');
    await scroll.evaluate((element, style) => {
      element.style.height = style.height;
      element.style.maxHeight = style.maxHeight;
    }, originalStyle);
    await scrollFixture.evaluate((element) => element.remove());
  });
});
