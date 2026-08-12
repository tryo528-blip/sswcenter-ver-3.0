import { expect, test, type APIRequestContext, type Page } from 'playwright/test';

test.use({
  trace: 'off',
  video: 'off',
  screenshot: 'off',
});

type JsonRecord = Record<string, unknown>;

type BrowserApiResult = {
  body: unknown;
  ok: boolean;
  raw: string;
  status: number;
};

type BrowserApiCall = {
  data?: JsonRecord;
  method?: string;
  path: string;
};

type RequestCapture = {
  body: unknown;
  method: string;
  url: string;
};

type PageErrorCounter = {
  count: number;
};

const EXPECTED_PROJECTS = new Set([
  'chromium-1440x1000',
  'chromium-1440x900',
  'chromium-1366x768',
]);

const API_INTERNAL_LEAK_PATTERN =
  /(?:sqlalchemy|traceback|internalerror|dsn|postgres(?:ql)?|password|secret|stack trace|exception in thread)/i;
const LEGACY_PUBLIC_KEY_PATTERN =
  /(?:legacy_recipient_key|legacy_attachment_key|source_system_code|payer_type|\bSELF\b|\bPRIMARY_GUARDIAN\b)/i;
const PAYER_GUARDIAN_KEY_PATTERN = /(?:payer_type|guardian_id)/i;

function asRecord(value: unknown): JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}



function parseJson(raw: string): unknown {
  try {
    return raw ? (JSON.parse(raw) as unknown) : null;
  } catch {
    return null;
  }
}

function numberField(value: unknown, field: string, marker: string): number {
  const candidate = asRecord(value)[field];
  const parsed = typeof candidate === 'number' ? candidate : Number(candidate);
  expect(Number.isSafeInteger(parsed) && parsed > 0, marker).toBe(true);
  return parsed;
}

function stringField(value: unknown, field: string, marker: string): string {
  const candidate = asRecord(value)[field];
  expect(typeof candidate === 'string' && candidate.length > 0, marker).toBe(true);
  return String(candidate);
}

function errorCode(value: unknown): string | undefined {
  const body = asRecord(value);
  const error = asRecord(body.error);
  const code = error.code ?? asRecord(body.detail).code;
  return typeof code === 'string' ? code : undefined;
}

function errorDetails(value: unknown): JsonRecord {
  return asRecord(asRecord(value).details);
}

function escapedId(id: number): string {
  return encodeURIComponent(String(id));
}

function recipientPath(id: number): string {
  return `/api/v1/recipients/${escapedId(id)}`;
}

function guardianCollectionPath(id: number): string {
  return `${recipientPath(id)}/guardians`;
}

function primaryCollectionPath(id: number): string {
  return `${recipientPath(id)}/primary-guardian-periods`;
}

function payerCollectionPath(id: number): string {
  return `${recipientPath(id)}/payer-snapshots`;
}

function buildRunKey(testInfo: { project: { name: string }; repeatEachIndex: number }): string {
  const project = testInfo.project.name.replace(/[^A-Za-z0-9]+/g, '-');
  return `W1B-${project}-${testInfo.repeatEachIndex}-${Date.now().toString(36)}`;
}

function requestBody(request: { postData(): string | null }): unknown {
  const raw = request.postData();
  return raw ? parseJson(raw) : null;
}

function findRequest(
  captures: RequestCapture[],
  predicate: (capture: RequestCapture) => boolean,
): RequestCapture | undefined {
  return [...captures].reverse().find(predicate);
}

function assertNoKeys(value: unknown, pattern: RegExp, marker: string): void {
  const text = JSON.stringify(value) ?? '';
  expect(pattern.test(text), marker).toBe(false);
}

function assertNoSensitiveSurface(value: unknown, marker: string): void {
  assertNoKeys(value, API_INTERNAL_LEAK_PATTERN, marker);
  assertNoKeys(value, LEGACY_PUBLIC_KEY_PATTERN, `${marker}_LEGACY_KEYS`);
}

function normalizeUtcTimestamps(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => normalizeUtcTimestamps(item));
  if (typeof value !== 'object' || value === null) return value;

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      if (key.endsWith('_at_utc') && typeof item === 'string') {
        const epochMilliseconds = Date.parse(item);
        expect(Number.isNaN(epochMilliseconds), 'W1B_E2E_TIMESTAMP_NORMALIZATION_INVALID').toBe(false);
        return [key, new Date(epochMilliseconds).toISOString()];
      }
      return [key, normalizeUtcTimestamps(item)];
    }),
  );
}

async function browserApi(page: Page, call: BrowserApiCall): Promise<BrowserApiResult> {
  return page.evaluate(
    async ({ data, method = 'GET', path }) => {
      const headers = new Headers();
      if (data !== undefined) headers.set('Content-Type', 'application/json');
      if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method.toUpperCase())) {
        const match = document.cookie.match(/(?:^|; )\s*sswcenter_csrf\s*=\s*([^;]+)/);
        if (!match) {
          return {
            body: { error: { code: 'CSRF_COOKIE_MISSING' } },
            ok: false,
            raw: '',
            status: 0,
          };
        }
        try {
          const token = decodeURIComponent(match[1]);
          if (token) headers.set('X-CSRF-Token', token);
        } catch {
          return {
            body: { error: { code: 'CSRF_COOKIE_MALFORMED' } },
            ok: false,
            raw: '',
            status: 0,
          };
        }
      }
      const response = await fetch(path, {
        body: data === undefined ? undefined : JSON.stringify(data),
        credentials: 'include',
        headers,
        method,
      });
      const raw = await response.text();
      return {
        body: parseJson(raw),
        ok: response.ok,
        raw,
        status: response.status,
      };

      function parseJson(text: string): unknown {
        try {
          return text ? (JSON.parse(text) as unknown) : null;
        } catch {
          return null;
        }
      }
    },
    call,
  );
}

async function browserApiParallel(page: Page, calls: BrowserApiCall[]): Promise<BrowserApiResult[]> {
  return page.evaluate(
    async (requestCalls) => {
      const csrfToken = (() => {
        const match = document.cookie.match(/(?:^|; )\s*sswcenter_csrf\s*=\s*([^;]+)/);
        if (!match) return null;
        try {
          return decodeURIComponent(match[1]);
        } catch {
          return null;
        }
      })();

      return Promise.all(
        requestCalls.map(async ({ data, method = 'GET', path }) => {
          const headers = new Headers();
          if (data !== undefined) headers.set('Content-Type', 'application/json');
          if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method.toUpperCase())) {
            if (csrfToken) headers.set('X-CSRF-Token', csrfToken);
          }
          const response = await fetch(path, {
            body: data === undefined ? undefined : JSON.stringify(data),
            credentials: 'include',
            headers,
            method,
          });
          const raw = await response.text();
          let body: unknown = null;
          try {
            body = raw ? (JSON.parse(raw) as unknown) : null;
          } catch {
            body = null;
          }
          return { body, ok: response.ok, raw, status: response.status };
        }),
      );
    },
    calls,
  );
}

async function installDomLeakObserver(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const install = () => {
      const target = document.documentElement;
      if (!target) return;
      const win = window as unknown as { __w1bDomSurfaces?: string[] };
      win.__w1bDomSurfaces = [];
      const capture = () => {
        if (document.body) win.__w1bDomSurfaces?.push(document.body.innerText);
      };
      capture();
      new MutationObserver(capture).observe(target, {
        characterData: true,
        childList: true,
        subtree: true,
      });
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', install, { once: true });
    } else {
      install();
    }
  });
}

async function snapshotDomAcrossNavigations(
  page: Page,
  domSurfacesAcrossNavigations: string[],
  urlSurfaces: string[],
  marker: string,
): Promise<void> {
  let snapshot: { dom: string[] | null; url: string };
  try {
    snapshot = await page.evaluate(() => {
      const win = window as unknown as { __w1bDomSurfaces?: unknown };
      const surfaces = win.__w1bDomSurfaces;
      return {
        dom: Array.isArray(surfaces)
          ? surfaces.filter((surface): surface is string => typeof surface === 'string')
          : null,
        url: window.location.href,
      };
    });
  } catch {
    expect.soft(false, `${marker}_OBSERVER_UNREADABLE`).toBe(true);
    return;
  }
  expect.soft(Array.isArray(snapshot.dom), `${marker}_OBSERVER_MISSING`).toBe(true);
  expect.soft(snapshot.dom?.length ?? 0, `${marker}_OBSERVER_EMPTY`).toBeGreaterThan(0);
  if (snapshot.dom) domSurfacesAcrossNavigations.push(...snapshot.dom);
  urlSurfaces.push(snapshot.url);
}

async function bootstrapIfRequired(
  request: APIRequestContext,
  pin: string,
  runKey: string,
  responseSurfaces: string[],
): Promise<void> {
  const status = await request.get('/api/bootstrap/status');
  const statusRaw = await status.text();
  responseSurfaces.push(statusRaw);
  expect(status.ok(), 'W1B_E2E_BOOTSTRAP_STATUS_FAILED').toBe(true);
  const statusBody = asRecord(parseJson(statusRaw));
  if (statusBody.bootstrap_required !== true) return;

  const bootstrap = await request.post('/api/bootstrap', {
    data: {
      admin_name: `${runKey} synthetic admin`,
      birth_date: '1980-01-01',
      center_name: `${runKey} synthetic center`,
      pin,
      sex_code: 'MALE',
      start_date: '2025-01-01',
    },
  });
  const bootstrapRaw = await bootstrap.text();
  responseSurfaces.push(bootstrapRaw);
  expect(bootstrap.ok(), 'W1B_E2E_BOOTSTRAP_FAILED').toBe(true);
}

async function loginInBrowser(page: Page, pin: string, pageErrors: PageErrorCounter): Promise<void> {
  await page.goto('/recipients');
  const authLoading = page.getByTestId('auth-loading');
  await expect(authLoading, 'W1B_E2E_AUTH_LOADING_STUCK').toBeHidden();
  await expect(page.getByTestId('bootstrap-container'), 'W1B_E2E_BOOTSTRAP_FORM_UNEXPECTED').toBeHidden();
  const loginContainer = page.getByTestId('login-container');
  if ((await loginContainer.count()) > 0 && (await loginContainer.first().isVisible())) {
    const loginResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/auth/login' &&
        response.request().method() === 'POST',
    );
    await page.getByTestId('login-pin-input').fill(pin);
    const legacyLoginSubmit = page.getByTestId('login-submit-btn');
    if (await legacyLoginSubmit.count()) await legacyLoginSubmit.click();
    const loginResponse = await loginResponsePromise;
    expect(loginResponse.ok(), 'W1B_E2E_LOGIN_REQUEST_FAILED').toBe(true);
    await expect(authLoading, 'W1B_E2E_AUTH_LOADING_STUCK').toBeHidden();
    await expect(loginContainer, 'W1B_E2E_LOGIN_FORM_STILL_VISIBLE').toBeHidden();
  }
  expect(pageErrors.count, 'W1B_E2E_PAGE_RUNTIME_ERROR').toBe(0);
  await expect(page.getByTestId('page-recipients'), 'W1B_E2E_RECIPIENT_ROUTE_MISSING').toBeVisible();
}

async function createRecipientViaUi(
  page: Page,
  name: string,
  requestCaptures: RequestCapture[],
  responseSurfaces: string[],
): Promise<JsonRecord> {
  // Create mode exposes recipient-name-input (no standalone create-form wrapper required).
  const nameInput = page.getByTestId('recipient-name-input');
  if (!(await nameInput.isVisible())) {
    await page.getByTestId('recipient-create-toggle').click();
  }
  await expect(nameInput, 'W1B_E2E_RECIPIENT_CREATE_FORM_MISSING').toBeVisible();
  await nameInput.fill(name);
  await page.getByTestId('recipient-birth-date-input').fill('2000-01-01');
  await page.getByTestId('recipient-sex-code-select').selectOption('MALE');
  await page.getByTestId('recipient-postal-code-input').fill('W1B-POSTAL');
  await page.getByTestId('recipient-address-input').fill(`${name} address`);
  // home_phone is optional on RecipientCreateRequest and has no create-form input.
  await page.getByTestId('recipient-mobile-phone-input').fill('010-1000-0002');

  // Live create posts atomic basic-batch (not plain POST /recipients).
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/v1/recipients/basic-batch' &&
      response.request().method() === 'POST',
  );
  // Live UI uses recipient-create-toggle as the create form's external submit.
  await page.getByTestId('recipient-create-toggle').click();
  const response = await responsePromise;
  const raw = await response.text();
  responseSurfaces.push(raw);
  expect(response.status(), 'W1B_E2E_RECIPIENT_CREATE_STATUS').toBe(201);

  const batchBody = asRecord(parseJson(raw));
  const body = asRecord(batchBody.recipient);
  expect(body.recipient_no, 'W1B_E2E_RECIPIENT_NO_MUST_BE_NULL').toBeNull();
  expect(body.home_phone, 'W1B_E2E_RECIPIENT_HOME_PHONE_READBACK').toBeNull();
  expect(body.mobile_phone, 'W1B_E2E_RECIPIENT_MOBILE_PHONE_READBACK').toBe('010-1000-0002');
  const captured = findRequest(
    requestCaptures,
    (item) =>
      new URL(item.url).pathname === '/api/v1/recipients/basic-batch' && item.method === 'POST',
  );
  expect(captured, 'W1B_E2E_RECIPIENT_CREATE_REQUEST_MISSING').toBeTruthy();
  const capturedRecipient = asRecord(asRecord(captured?.body).recipient);
  expect('recipient_no' in capturedRecipient, 'W1B_E2E_RECIPIENT_NO_INPUT_FORBIDDEN').toBe(false);
  return body;
}

async function createBulkRecipients(
  page: Page,
  runKey: string,
  requestCaptures: RequestCapture[],
  responseSurfaces: string[],
): Promise<void> {
  const total = 102;
  const batchSize = 8;
  for (let offset = 0; offset < total; offset += batchSize) {
    const calls: BrowserApiCall[] = [];
    for (let index = offset; index < Math.min(offset + batchSize, total); index += 1) {
      calls.push({
        data: {
          address: null,
          birth_date: '2000-01-01',
          home_phone: null,
          memo: null,
          mobile_phone: null,
          name: `${runKey}-ROW-${String(index).padStart(3, '0')}`,
          postal_code: null,
          sex_code: index % 2 === 0 ? 'MALE' : 'FEMALE',
        },
        method: 'POST',
        path: '/api/v1/recipients',
      });
    }
    const results = await browserApiParallel(page, calls);
    results.forEach((result, index) => {
      responseSurfaces.push(result.raw);
      expect(result.status, `W1B_E2E_BULK_RECIPIENT_CREATE_${offset + index}`).toBe(201);
      expect(asRecord(result.body).recipient_no, 'W1B_E2E_BULK_RECIPIENT_NO_NULL').toBeNull();
    });
  }
  const listPosts = requestCaptures.filter(
    (item) => new URL(item.url).pathname === '/api/v1/recipients' && item.method === 'POST',
  );
  expect(listPosts.length, 'W1B_E2E_BULK_RECIPIENT_REQUEST_COUNT').toBeGreaterThanOrEqual(total);
}

async function expectRecipientReadback(page: Page, recipientId: number, name: string): Promise<JsonRecord> {
  const detail = await browserApi(page, { path: recipientPath(recipientId) });
  expect(detail.status, 'W1B_E2E_RECIPIENT_DETAIL_STATUS').toBe(200);
  expect(asRecord(detail.body).name, 'W1B_E2E_RECIPIENT_DETAIL_NAME').toBe(name);
  expect(asRecord(detail.body).home_phone, 'W1B_E2E_RECIPIENT_DETAIL_HOME_PHONE').toBeNull();
  expect(asRecord(detail.body).mobile_phone, 'W1B_E2E_RECIPIENT_DETAIL_MOBILE_PHONE').toBe('010-1000-0002');
  return asRecord(detail.body);
}

async function expectApiSuccess(
  result: BrowserApiResult,
  status: number,
  marker: string,
): Promise<JsonRecord> {
  expect(result.status, `${marker}_STATUS`).toBe(status);
  expect(result.ok, `${marker}_OK`).toBe(true);
  return asRecord(result.body);
}

async function expectApiConflict(
  result: BrowserApiResult,
  code: string,
  marker: string,
): Promise<JsonRecord> {
  expect(result.status, `${marker}_STATUS`).toBe(409);
  expect(errorCode(result.body), `${marker}_CODE`).toBe(code);
  return asRecord(result.body);
}

async function createGuardians(
  page: Page,
  recipientId: number,
  responseSurfaces: string[],
): Promise<{ guardianA: JsonRecord; guardianB: JsonRecord }> {
  const guardianAResult = await browserApi(page, {
    data: {
      address: null,
      name: `W1B guardian A ${recipientId}`,
      phone: null,
      relationship_text: null,
    },
    method: 'POST',
    path: guardianCollectionPath(recipientId),
  });
  responseSurfaces.push(guardianAResult.raw);
  const guardianA = await expectApiSuccess(guardianAResult, 201, 'W1B_E2E_GUARDIAN_A_CREATE');

  const guardianBResult = await browserApi(page, {
    data: {
      address: `W1B guardian B address ${recipientId}`,
      name: `W1B guardian B ${recipientId}`,
      phone: '010-2000-0003',
      relationship_text: 'parent',
    },
    method: 'POST',
    path: guardianCollectionPath(recipientId),
  });
  responseSurfaces.push(guardianBResult.raw);
  const guardianB = await expectApiSuccess(guardianBResult, 201, 'W1B_E2E_GUARDIAN_B_CREATE');

  const guardianBId = numberField(guardianB, 'id', 'W1B_E2E_GUARDIAN_B_ID');
  const guardianBVersion = numberField(guardianB, 'row_version', 'W1B_E2E_GUARDIAN_B_VERSION');
  const updateResult = await browserApi(page, {
    data: {
      address: `W1B guardian B updated address ${recipientId}`,
      expected_row_version: guardianBVersion,
      name: `W1B guardian B updated ${recipientId}`,
      phone: '010-2000-0099',
      relationship_text: 'parent-updated',
    },
    method: 'PATCH',
    path: `${guardianCollectionPath(recipientId)}/${escapedId(guardianBId)}`,
  });
  responseSurfaces.push(updateResult.raw);
  const updatedGuardianB = await expectApiSuccess(updateResult, 200, 'W1B_E2E_GUARDIAN_B_UPDATE');

  const listResult = await browserApi(page, { path: guardianCollectionPath(recipientId) });
  responseSurfaces.push(listResult.raw);
  const guardians = asRecord(listResult.body).items;
  expect(Array.isArray(guardians), 'W1B_E2E_GUARDIAN_LIST_SHAPE').toBe(true);
  expect((guardians as unknown[]).length, 'W1B_E2E_GUARDIAN_COUNT').toBe(2);
  expect(JSON.stringify(guardians), 'W1B_E2E_GUARDIAN_OPTIONAL_READBACK').toContain('010-2000-0099');
  expect(JSON.stringify(guardians), 'W1B_E2E_GUARDIAN_RELATIONSHIP_READBACK').toContain('parent-updated');
  expect('birth_date' in asRecord(updatedGuardianB), 'W1B_E2E_GUARDIAN_BIRTH_DATE_FORBIDDEN').toBe(false);
  expect('sex_code' in asRecord(updatedGuardianB), 'W1B_E2E_GUARDIAN_SEX_FORBIDDEN').toBe(false);
  return { guardianA, guardianB: updatedGuardianB };
}

async function exercisePrimaryHistory(
  page: Page,
  recipientId: number,
  guardianA: JsonRecord,
  guardianB: JsonRecord,
  responseSurfaces: string[],
): Promise<void> {
  const guardianAId = numberField(guardianA, 'id', 'W1B_E2E_PRIMARY_GUARDIAN_A_ID');
  const guardianBId = numberField(guardianB, 'id', 'W1B_E2E_PRIMARY_GUARDIAN_B_ID');

  const finitePeriodResult = await browserApi(page, {
    data: { end_date: '2026-02-28', guardian_id: guardianAId, start_date: '2026-01-01' },
    method: 'POST',
    path: primaryCollectionPath(recipientId),
  });
  responseSurfaces.push(finitePeriodResult.raw);
  await expectApiSuccess(finitePeriodResult, 201, 'W1B_E2E_PRIMARY_FINITE_CREATE');

  const concurrent = await browserApiParallel(page, [
    {
      data: { end_date: null, guardian_id: guardianAId, start_date: '2026-03-01' },
      method: 'POST',
      path: primaryCollectionPath(recipientId),
    },
    {
      data: { end_date: null, guardian_id: guardianBId, start_date: '2026-03-01' },
      method: 'POST',
      path: primaryCollectionPath(recipientId),
    },
  ]);
  concurrent.forEach((result) => responseSurfaces.push(result.raw));
  const created = concurrent.filter((result) => result.status === 201);
  const conflicts = concurrent.filter((result) => result.status === 409);
  expect(created.length, 'W1B_E2E_PRIMARY_CONCURRENT_ONE_SUCCESS').toBe(1);
  expect(conflicts.length, 'W1B_E2E_PRIMARY_CONCURRENT_ONE_CONFLICT').toBe(1);
  await expectApiConflict(
    conflicts[0],
    'PRIMARY_GUARDIAN_PERIOD_CONFLICT',
    'W1B_E2E_PRIMARY_CONCURRENT_CONFLICT',
  );

  const current = asRecord(created[0].body);
  const currentId = numberField(current, 'id', 'W1B_E2E_PRIMARY_CURRENT_ID');
  const currentVersion = numberField(current, 'row_version', 'W1B_E2E_PRIMARY_CURRENT_VERSION');
  const replacementResult = await browserApi(page, {
    data: {
      end_date: null,
      expected_row_version: currentVersion,
      guardian_id: guardianBId,
      start_date: '2026-04-01',
    },
    method: 'POST',
    path: `${primaryCollectionPath(recipientId)}/${escapedId(currentId)}/replacements`,
  });
  responseSurfaces.push(replacementResult.raw);
  const replacement = await expectApiSuccess(replacementResult, 201, 'W1B_E2E_PRIMARY_REPLACE');
  const original = asRecord(replacement.original);
  const newPeriod = asRecord(replacement.replacement);
  expect(original.invalidated_at_utc, 'W1B_E2E_PRIMARY_ORIGINAL_INVALIDATED').not.toBeNull();
  expect(original.replacement_primary_guardian_period_id, 'W1B_E2E_PRIMARY_LINKAGE').toBe(
    newPeriod.id,
  );

  const staleResult = await browserApi(page, {
    data: {
      end_date: null,
      expected_row_version: currentVersion,
      guardian_id: guardianAId,
      start_date: '2026-05-01',
    },
    method: 'POST',
    path: `${primaryCollectionPath(recipientId)}/${escapedId(currentId)}/replacements`,
  });
  responseSurfaces.push(staleResult.raw);
  const staleBody = await expectApiConflict(staleResult, 'ROW_VERSION_CONFLICT', 'W1B_E2E_PRIMARY_STALE');
  expect(errorDetails(staleBody).current_row_version, 'W1B_E2E_PRIMARY_STALE_VERSION_DETAIL').toBeGreaterThan(
    currentVersion,
  );

  const replacementId = numberField(newPeriod, 'id', 'W1B_E2E_PRIMARY_REPLACEMENT_ID');
  const replacementVersion = numberField(newPeriod, 'row_version', 'W1B_E2E_PRIMARY_REPLACEMENT_VERSION');
  const invalidateResult = await browserApi(page, {
    data: { expected_row_version: replacementVersion },
    method: 'POST',
    path: `${primaryCollectionPath(recipientId)}/${escapedId(replacementId)}/invalidate`,
  });
  responseSurfaces.push(invalidateResult.raw);
  const invalidated = await expectApiSuccess(invalidateResult, 200, 'W1B_E2E_PRIMARY_INVALIDATE');
  expect(invalidated.invalidated_at_utc, 'W1B_E2E_PRIMARY_INVALIDATED_AT').not.toBeNull();

  const historyResult = await browserApi(page, { path: primaryCollectionPath(recipientId) });
  responseSurfaces.push(historyResult.raw);
  const history = asRecord(historyResult.body).items;
  expect(Array.isArray(history), 'W1B_E2E_PRIMARY_HISTORY_SHAPE').toBe(true);
  expect((history as unknown[]).length, 'W1B_E2E_PRIMARY_HISTORY_COUNT').toBeGreaterThanOrEqual(3);
  expect(JSON.stringify(history), 'W1B_E2E_PRIMARY_HISTORY_LINK').toContain(String(newPeriod.id));
}

async function exercisePayerHistory(
  page: Page,
  recipientId: number,
  guardianId: number,
  responseSurfaces: string[],
): Promise<void> {
  const firstResult = await browserApi(page, {
    data: {
      address: null,
      end_date: null,
      name: `W1B payer null ${recipientId}`,
      phone: null,
      relationship_text: null,
      start_date: '2026-01-01',
    },
    method: 'POST',
    path: payerCollectionPath(recipientId),
  });
  responseSurfaces.push(firstResult.raw);
  const first = await expectApiSuccess(firstResult, 201, 'W1B_E2E_PAYER_NULL_CREATE');
  expect(first.phone, 'W1B_E2E_PAYER_NULL_PHONE').toBeNull();
  expect(first.address, 'W1B_E2E_PAYER_NULL_ADDRESS').toBeNull();
  expect(first.relationship_text, 'W1B_E2E_PAYER_NULL_RELATIONSHIP').toBeNull();
  assertNoKeys(first, PAYER_GUARDIAN_KEY_PATTERN, 'W1B_E2E_PAYER_NULL_FORBIDDEN_FK');

  const firstId = numberField(first, 'id', 'W1B_E2E_PAYER_FIRST_ID');
  const firstVersion = numberField(first, 'row_version', 'W1B_E2E_PAYER_FIRST_VERSION');
  const conflictResult = await browserApi(page, {
    data: {
      address: null,
      end_date: null,
      name: `W1B payer conflict ${recipientId}`,
      phone: null,
      relationship_text: null,
      start_date: '2026-02-01',
    },
    method: 'POST',
    path: payerCollectionPath(recipientId),
  });
  responseSurfaces.push(conflictResult.raw);
  await expectApiConflict(conflictResult, 'CURRENT_PAYER_CONFLICT', 'W1B_E2E_PAYER_CURRENT_CONFLICT');

  const replacementResult = await browserApi(page, {
    data: {
      address: `W1B payer address ${recipientId}`,
      end_date: null,
      expected_row_version: firstVersion,
      name: `W1B payer populated ${recipientId}`,
      phone: '010-3000-0004',
      relationship_text: 'guardian contact',
      start_date: '2026-03-01',
    },
    method: 'POST',
    path: `${payerCollectionPath(recipientId)}/${escapedId(firstId)}/replacements`,
  });
  responseSurfaces.push(replacementResult.raw);
  const replacement = await expectApiSuccess(replacementResult, 201, 'W1B_E2E_PAYER_REPLACE');
  const original = asRecord(replacement.original);
  const current = asRecord(replacement.replacement);
  expect(original.invalidated_at_utc, 'W1B_E2E_PAYER_ORIGINAL_INVALIDATED').not.toBeNull();
  expect(original.replacement_payer_snapshot_id, 'W1B_E2E_PAYER_LINKAGE').toBe(current.id);
  expect(current.phone, 'W1B_E2E_PAYER_PHONE_READBACK').toBe('010-3000-0004');
  expect(current.address, 'W1B_E2E_PAYER_ADDRESS_READBACK').toBe(`W1B payer address ${recipientId}`);
  expect(current.relationship_text, 'W1B_E2E_PAYER_RELATIONSHIP_READBACK').toBe('guardian contact');
  assertNoKeys(replacement, PAYER_GUARDIAN_KEY_PATTERN, 'W1B_E2E_PAYER_REPLACEMENT_FORBIDDEN_FK');

  const staleResult = await browserApi(page, {
    data: {
      address: null,
      end_date: null,
      expected_row_version: firstVersion,
      name: `W1B payer stale ${recipientId}`,
      phone: null,
      relationship_text: null,
      start_date: '2026-05-01',
    },
    method: 'POST',
    path: `${payerCollectionPath(recipientId)}/${escapedId(firstId)}/replacements`,
  });
  responseSurfaces.push(staleResult.raw);
  await expectApiConflict(staleResult, 'ROW_VERSION_CONFLICT', 'W1B_E2E_PAYER_STALE');

  const currentId = numberField(current, 'id', 'W1B_E2E_PAYER_CURRENT_ID');
  const currentVersion = numberField(current, 'row_version', 'W1B_E2E_PAYER_CURRENT_VERSION');
  const invalidateResult = await browserApi(page, {
    data: { expected_row_version: currentVersion },
    method: 'POST',
    path: `${payerCollectionPath(recipientId)}/${escapedId(currentId)}/invalidate`,
  });
  responseSurfaces.push(invalidateResult.raw);
  await expectApiSuccess(invalidateResult, 200, 'W1B_E2E_PAYER_INVALIDATE');

  const recreateResult = await browserApi(page, {
    data: {
      address: null,
      end_date: null,
      name: `W1B payer recreated ${recipientId}`,
      phone: null,
      relationship_text: null,
      start_date: '2026-06-01',
    },
    method: 'POST',
    path: payerCollectionPath(recipientId),
  });
  responseSurfaces.push(recreateResult.raw);
  const recreated = await expectApiSuccess(recreateResult, 201, 'W1B_E2E_PAYER_RECREATE');
  expect(recreated.invalidated_at_utc, 'W1B_E2E_PAYER_RECREATE_CURRENT').toBeNull();

  const payerListBefore = await browserApi(page, { path: payerCollectionPath(recipientId) });
  responseSurfaces.push(payerListBefore.raw);
  const payerBefore = normalizeUtcTimestamps(payerListBefore.body);
  expect(JSON.stringify(payerBefore), 'W1B_E2E_PAYER_GUARDIAN_INDEPENDENT_BASELINE').toContain(
    'W1B payer recreated',
  );

  const guardianMutation = await browserApi(page, {
    data: {
      address: `W1B guardian after payer ${recipientId}`,
      expected_row_version: 1,
      name: `W1B guardian after payer ${recipientId}`,
      phone: '010-3999-9999',
      relationship_text: 'independent',
    },
    method: 'PATCH',
    path: `${guardianCollectionPath(recipientId)}/${escapedId(guardianId)}`,
  });
  responseSurfaces.push(guardianMutation.raw);
  expect(guardianMutation.status, 'W1B_E2E_PAYER_GUARDIAN_MUTATION_STATUS').toBe(200);

  const payerListAfter = await browserApi(page, { path: payerCollectionPath(recipientId) });
  responseSurfaces.push(payerListAfter.raw);
  expect(
    normalizeUtcTimestamps(payerListAfter.body),
    'W1B_E2E_PAYER_GUARDIAN_INDEPENDENT_AFTER',
  ).toEqual(payerBefore);
  assertNoKeys(payerListAfter.body, PAYER_GUARDIAN_KEY_PATTERN, 'W1B_E2E_PAYER_LIST_FORBIDDEN_FK');
}

async function exercisePayerGuardianSelection(
  page: Page,
  recipientId: number,
  guardianAId: number,
  guardianBId: number,
  responseSurfaces: string[],
): Promise<void> {
  await page.reload();
  await expect(page.getByTestId('page-recipients'), 'W1B_E2E_PAYER_UI_PAGE_READY').toBeVisible();
  await expect(page.getByTestId('recipient-detail-workspace'), 'W1B_E2E_PAYER_UI_DETAIL_READY').toBeVisible();
  const editButton = page.getByTestId('recipient-basic-edit');
  const saveButton = page.getByTestId('recipient-basic-save');
  const payerA = page.getByTestId('guardian-1-payer-checkbox');
  const payerB = page.getByTestId('guardian-2-payer-checkbox');
  const payerLabel = page.getByTestId('recipient-payer-current-label');
  await expect(editButton, 'W1B_E2E_PAYER_UI_EDIT_READY').toBeVisible();
  await editButton.click();
  await expect(payerA, 'W1B_E2E_PAYER_UI_A_READY').toBeEnabled();
  await expect(payerB, 'W1B_E2E_PAYER_UI_B_READY').toBeEnabled();

  // Assign guardian A through the visible UI (basic-batch slot 0 / 1, not PATCH payer_guardian_id).
  const basicBatchPath = `${recipientPath(recipientId)}/basic-batch`;
  const current = await browserApi(page, { path: recipientPath(recipientId) });
  responseSurfaces.push(current.raw);
  const currentBody = asRecord(current.body);
  const version1 = numberField(currentBody, 'row_version', 'W1B_E2E_PAYER_G_VERSION_1');
  await payerA.check();
  await expect(payerA, 'W1B_E2E_PAYER_UI_A_CHECKED').toBeChecked();
  await expect(payerB, 'W1B_E2E_PAYER_UI_B_EXCLUDED_BY_A').not.toBeChecked();
  const setAResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === basicBatchPath &&
      response.request().method() === 'POST',
  );
  await saveButton.click();
  const setAResponse = await setAResponsePromise;
  const setARaw = await setAResponse.text();
  responseSurfaces.push(setARaw);
  expect(setAResponse.status(), 'W1B_E2E_PAYER_G_SET_A_STATUS').toBe(200);
  const setARequest = asRecord(parseJson(setAResponse.request().postData() ?? ''));
  expect(asRecord(setARequest.recipient).expected_row_version, 'W1B_E2E_PAYER_G_SET_A_VERSION').toBe(
    version1,
  );
  expect(setARequest.payer_guardian_slot, 'W1B_E2E_PAYER_G_SET_A_SLOT').toBe(0);
  const payerUiBodyA = asRecord(asRecord(parseJson(setARaw)).recipient);
  expect(payerUiBodyA.payer_guardian_id, 'W1B_E2E_PAYER_G_SET_A_VALUE').toBe(guardianAId);
  await expect(payerLabel, 'W1B_E2E_PAYER_G_SET_A_LABEL').toContainText('보호자1');
  const readA = await browserApi(page, { path: recipientPath(recipientId) });
  responseSurfaces.push(readA.raw);
  expect(asRecord(readA.body).payer_guardian_id, 'W1B_E2E_PAYER_G_READ_A').toBe(guardianAId);

  const bodyA = payerUiBodyA;

  // Switch to guardian B (save closes edit mode; re-enter before the next mutation).
  const version2 = numberField(bodyA, 'row_version', 'W1B_E2E_PAYER_G_VERSION_2');
  await editButton.click();
  await expect(payerB, 'W1B_E2E_PAYER_UI_B_READY_AGAIN').toBeEnabled();
  await payerB.check();
  await expect(payerB, 'W1B_E2E_PAYER_UI_B_CHECKED').toBeChecked();
  await expect(payerA, 'W1B_E2E_PAYER_UI_A_EXCLUDED_BY_B').not.toBeChecked();
  const setBResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === basicBatchPath &&
      response.request().method() === 'POST',
  );
  await saveButton.click();
  const setBResponse = await setBResponsePromise;
  const setBRaw = await setBResponse.text();
  responseSurfaces.push(setBRaw);
  expect(setBResponse.status(), 'W1B_E2E_PAYER_G_SET_B_STATUS').toBe(200);
  const setBRequest = asRecord(parseJson(setBResponse.request().postData() ?? ''));
  expect(asRecord(setBRequest.recipient).expected_row_version, 'W1B_E2E_PAYER_G_SET_B_VERSION').toBe(
    version2,
  );
  expect(setBRequest.payer_guardian_slot, 'W1B_E2E_PAYER_G_SET_B_SLOT').toBe(1);
  const payerUiBodyB = asRecord(asRecord(parseJson(setBRaw)).recipient);
  expect(payerUiBodyB.payer_guardian_id, 'W1B_E2E_PAYER_G_SET_B_VALUE').toBe(guardianBId);
  await expect(payerLabel, 'W1B_E2E_PAYER_G_SET_B_LABEL').toContainText('보호자2');
  const readB = await browserApi(page, { path: recipientPath(recipientId) });
  responseSurfaces.push(readB.raw);
  expect(asRecord(readB.body).payer_guardian_id, 'W1B_E2E_PAYER_G_READ_B').toBe(guardianBId);
  const bodyB = payerUiBodyB;

  const version3 = numberField(bodyB, 'row_version', 'W1B_E2E_PAYER_G_VERSION_3');
  await editButton.click();
  await expect(payerB, 'W1B_E2E_PAYER_UI_B_READY_CLEAR').toBeEnabled();
  await payerB.uncheck();
  await expect(payerA, 'W1B_E2E_PAYER_UI_A_CLEAR_FOR_SELF').not.toBeChecked();
  await expect(payerB, 'W1B_E2E_PAYER_UI_B_CLEAR_FOR_SELF').not.toBeChecked();
  const setSelfResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === basicBatchPath &&
      response.request().method() === 'POST',
  );
  await saveButton.click();
  const setSelfResponse = await setSelfResponsePromise;
  const setSelfRaw = await setSelfResponse.text();
  responseSurfaces.push(setSelfRaw);
  expect(setSelfResponse.status(), 'W1B_E2E_PAYER_G_SET_SELF_STATUS').toBe(200);
  const setSelfRequest = asRecord(parseJson(setSelfResponse.request().postData() ?? ''));
  expect(
    asRecord(setSelfRequest.recipient).expected_row_version,
    'W1B_E2E_PAYER_G_SET_SELF_VERSION',
  ).toBe(version3);
  expect(setSelfRequest.payer_guardian_slot, 'W1B_E2E_PAYER_G_SET_SELF_SLOT').toBeNull();
  const bodySelf = asRecord(asRecord(parseJson(setSelfRaw)).recipient);
  expect(bodySelf.payer_guardian_id, 'W1B_E2E_PAYER_G_SET_SELF_VALUE').toBeNull();
  await expect(payerLabel, 'W1B_E2E_PAYER_G_SET_SELF_LABEL').toContainText('수급자 본인');
  const reread = await browserApi(page, { path: recipientPath(recipientId) });
  responseSurfaces.push(reread.raw);
  expect(asRecord(reread.body).payer_guardian_id, 'W1B_E2E_PAYER_G_REREAD_SELF').toBeNull();

  // Cross-recipient rejection: create second recipient and try to use its guardian id.
  const otherCreate = await browserApi(page, {
    data: {
      birth_date: '1990-01-01',
      name: `W1B cross payer ${recipientId}`,
      sex_code: 'MALE',
    },
    method: 'POST',
    path: '/api/v1/recipients',
  });
  responseSurfaces.push(otherCreate.raw);
  const other = await expectApiSuccess(otherCreate, 201, 'W1B_E2E_PAYER_G_OTHER_RECIPIENT');
  const otherId = numberField(other, 'id', 'W1B_E2E_PAYER_G_OTHER_ID');
  const otherGuardianCreate = await browserApi(page, {
    data: { name: `W1B foreign guardian ${otherId}` },
    method: 'POST',
    path: guardianCollectionPath(otherId),
  });
  responseSurfaces.push(otherGuardianCreate.raw);
  const otherGuardian = await expectApiSuccess(
    otherGuardianCreate,
    201,
    'W1B_E2E_PAYER_G_FOREIGN_GUARDIAN',
  );
  const foreignGuardianId = numberField(otherGuardian, 'id', 'W1B_E2E_PAYER_G_FOREIGN_ID');
  const selfAgain = await browserApi(page, { path: recipientPath(recipientId) });
  responseSurfaces.push(selfAgain.raw);
  const selfVersion = numberField(
    asRecord(selfAgain.body),
    'row_version',
    'W1B_E2E_PAYER_G_CROSS_VERSION',
  );
  const cross = await browserApi(page, {
    data: { expected_row_version: selfVersion, payer_guardian_id: foreignGuardianId },
    method: 'PATCH',
    path: recipientPath(recipientId),
  });
  responseSurfaces.push(cross.raw);
  expect(cross.status, 'W1B_E2E_PAYER_G_CROSS_STATUS').toBe(404);
  expect(errorCode(cross.body), 'W1B_E2E_PAYER_G_CROSS_CODE').toBe('RECIPIENT_GUARDIAN_NOT_FOUND');
}

test.describe('W1B-F2 real PostgreSQL recipient GREEN contract', () => {
  test('runs one real API/PG scenario per configured viewport', async ({ page, request }, testInfo) => {
    expect(EXPECTED_PROJECTS.has(testInfo.project.name), 'W1B_E2E_VIEWPORT_PROJECT_MISSING').toBe(true);
    expect(process.env.SSWCENTER_W1B_REAL_PG, 'W1B_E2E_REAL_PG_HARNESS_REQUIRED').toBe('1');
    const syntheticPin = process.env.SSWCENTER_W1B_SYNTHETIC_PIN;
    expect(
      typeof syntheticPin === 'string' && /^[0-9]{6}$/.test(syntheticPin),
      'W1B_E2E_SYNTHETIC_PIN_ENV_REQUIRED',
    ).toBe(true);
    const pin = String(syntheticPin);
    const runKey = buildRunKey(testInfo);
    const requestCaptures: RequestCapture[] = [];
    const responseSurfaces: string[] = [];
    const responsePromises: Promise<void>[] = [];
    const domSurfacesAcrossNavigations: string[] = [];
    const urlSurfaces: string[] = [page.url()];
    const pageErrors: PageErrorCounter = { count: 0 };
    let popupCount = 0;

    // This harness intentionally pins the database to the W1B migration.
    // Keep later W1C/W1D reads from reaching tables that do not exist at that revision.
    await page.route(
      /\/api\/v1\/recipients\/\d+\/certification-identity(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() !== 'GET') {
          await route.continue();
          return;
        }
        await route.fulfill({
          status: 404,
          json: {
            error: {
              code: 'CERTIFICATION_IDENTITY_NOT_FOUND',
              message: 'W1C is outside the isolated W1B scenario.',
            },
          },
        });
      },
    );
    await page.route(
      /\/api\/v1\/recipients\/\d+\/(?:certification-periods|grade-periods|benefit-periods|approval-amount-periods)(?:\?.*)?$/,
      async (route) => {
        if (route.request().method() !== 'GET') {
          await route.continue();
          return;
        }
        await route.fulfill({ status: 200, json: { items: [] } });
      },
    );
    await page.route(/\/api\/v1\/recipients\/\d+\/contracts(?:\?.*)?$/, async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue();
        return;
      }
      await route.fulfill({ status: 200, json: { items: [] } });
    });

    await installDomLeakObserver(page);
    page.on('pageerror', () => {
      pageErrors.count += 1;
    });
    page.on('framenavigated', (frame) => {
      if (frame === page.mainFrame()) urlSurfaces.push(frame.url());
    });
    page.on('popup', (popup) => {
      popupCount += 1;
      void popup.close();
    });
    page.on('request', (event) => {
      if (!event.url().includes('/api/')) return;
      requestCaptures.push({ body: requestBody(event), method: event.method(), url: event.url() });
    });
    page.on('response', (response) => {
      if (!response.url().includes('/api/')) return;
      responsePromises.push(
        response
          .text()
          .then((raw) => {
            responseSurfaces.push(raw);
          })
          .catch(() => {
            responseSurfaces.push('W1B_E2E_RESPONSE_BODY_UNAVAILABLE');
          }),
      );
    });

    await bootstrapIfRequired(request, pin, runKey, responseSurfaces);
    await loginInBrowser(page, pin, pageErrors);
    const created = await createRecipientViaUi(
      page,
      `${runKey}-A`,
      requestCaptures,
      responseSurfaces,
    );
    const recipientId = numberField(created, 'id', 'W1B_E2E_RECIPIENT_ID');
    const recipientName = stringField(created, 'name', 'W1B_E2E_RECIPIENT_NAME');
    await expect(page.getByTestId('recipient-detail-workspace'), 'W1B_E2E_RECIPIENT_DETAIL_WORKSPACE').toContainText(
      recipientName,
    );
    // Create form has no home_phone input; detail shows formatNullable → "없음".
    await expect(page.getByTestId('recipient-detail-home-phone'), 'W1B_E2E_RECIPIENT_DETAIL_HOME_UI').toContainText(
      '없음',
    );
    // After create, detail view uses the inert edit input (not the read-only strong).
    await expect(
      page.getByTestId('recipient-detail-mobile-phone-input'),
      'W1B_E2E_RECIPIENT_DETAIL_MOBILE_UI',
    ).toHaveValue('010-1000-0002');

    await expectRecipientReadback(page, recipientId, recipientName);
    const listReadback = await browserApi(page, {
      path: `/api/v1/recipients?search=${encodeURIComponent(recipientName)}&page=1&page_size=100`,
    });
    responseSurfaces.push(listReadback.raw);
    expect(listReadback.status, 'W1B_E2E_RECIPIENT_LIST_STATUS').toBe(200);
    expect(JSON.stringify(listReadback.body), 'W1B_E2E_RECIPIENT_LIST_READBACK').toContain(recipientName);

    await createBulkRecipients(page, runKey, requestCaptures, responseSurfaces);
    const recipientBeforeStale = await expectRecipientReadback(page, recipientId, recipientName);
    const staleVersion = numberField(
      recipientBeforeStale,
      'row_version',
      'W1B_E2E_RECIPIENT_STALE_VERSION',
    );
    const externalName = `${recipientName}-EXTERNAL`;
    const externalUpdate = await browserApi(page, {
      data: { expected_row_version: staleVersion, name: externalName },
      method: 'PATCH',
      path: recipientPath(recipientId),
    });
    responseSurfaces.push(externalUpdate.raw);
    const externallyUpdated = await expectApiSuccess(
      externalUpdate,
      200,
      'W1B_E2E_RECIPIENT_EXTERNAL_UPDATE',
    );
    const externalVersion = numberField(
      externallyUpdated,
      'row_version',
      'W1B_E2E_RECIPIENT_EXTERNAL_VERSION',
    );

    const staleInput = `${recipientName}-USER-STALE`;
    const basicBatchPath = `${recipientPath(recipientId)}/basic-batch`;
    await page.getByTestId('recipient-basic-edit').click();
    await page.getByTestId('recipient-detail-name-input').fill(staleInput);
    // Live basic save posts atomic basic-batch (not plain PATCH /recipients/{id}).
    const staleUiResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === basicBatchPath &&
        response.request().method() === 'POST',
    );
    await page.getByTestId('recipient-basic-save').click();
    const staleUi = await staleUiResponse;
    const staleUiRaw = await staleUi.text();
    responseSurfaces.push(staleUiRaw);
    const staleUiBody = parseJson(staleUiRaw);
    expect(staleUi.status(), 'W1B_E2E_STALE_UI_STATUS').toBe(409);
    expect(errorCode(staleUiBody), 'W1B_E2E_STALE_UI_CODE').toBe('ROW_VERSION_CONFLICT');
    const latestValue = page.getByTestId('recipient-stale-latest-value');
    const conflictLog = page.getByTestId('recipient-same-field-conflict-log');
    const nameInput = page.getByTestId('recipient-detail-name-input');
    await expect(latestValue, 'W1B_E2E_STALE_LATEST_VALUE_MISSING').toBeVisible();
    await expect(latestValue, 'W1B_E2E_STALE_LATEST_VALUE').toContainText(externalName);
    await expect(conflictLog, 'W1B_E2E_STALE_SAME_FIELD_LOG_MISSING').toBeVisible();
    await expect(conflictLog, 'W1B_E2E_STALE_SAME_FIELD_USER').toContainText(staleInput);
    await expect(conflictLog, 'W1B_E2E_STALE_SAME_FIELD_SERVER').toContainText(externalName);
    await expect(nameInput, 'W1B_E2E_STALE_SERVER_VALUE_WINS').toHaveValue(externalName);
    await expect(page.getByTestId('recipient-stale-reapply'), 'W1B_E2E_STALE_REAPPLY_FORBIDDEN').toHaveCount(0);

    await nameInput.fill(staleInput);
    const reapplyResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === basicBatchPath &&
        response.request().method() === 'POST',
    );
    await page.getByTestId('recipient-basic-save').click();
    const reapplied = await reapplyResponse;
    const reappliedRaw = await reapplied.text();
    responseSurfaces.push(reappliedRaw);
    expect(reapplied.status(), 'W1B_E2E_STALE_REAPPLY_STATUS').toBe(200);
    const reapplyRequest = findRequest(
      requestCaptures,
      (capture) =>
        new URL(capture.url).pathname === basicBatchPath &&
        capture.method === 'POST' &&
        asRecord(asRecord(capture.body).recipient).name === staleInput,
    );
    expect(reapplyRequest, 'W1B_E2E_STALE_REAPPLY_REQUEST_MISSING').toBeDefined();
    expect(asRecord(reapplyRequest?.body), 'W1B_E2E_STALE_REAPPLY_PARTIAL_PAYLOAD').toEqual(
      expect.objectContaining({
        recipient: {
          expected_row_version: externalVersion,
          name: staleInput,
        },
        // Name-only reapply must not send a copay CREATE (open-period exclusion constraint).
        benefit_periods: [],
      }),
    );
    const reappliedReadback = await browserApi(page, { path: recipientPath(recipientId) });
    responseSurfaces.push(reappliedReadback.raw);
    expect(asRecord(reappliedReadback.body).name, 'W1B_E2E_STALE_REAPPLY_READBACK').toBe(staleInput);

    const { guardianA, guardianB } = await createGuardians(page, recipientId, responseSurfaces);
    const guardianAId = numberField(guardianA, 'id', 'W1B_E2E_GUARDIAN_A_FINAL_ID');
    const guardianBId = numberField(guardianB, 'id', 'W1B_E2E_GUARDIAN_B_FINAL_ID');
    // Historical primary/payer snapshot APIs remain available (compatibility); exercised via API.
    await exercisePrimaryHistory(page, recipientId, guardianA, guardianB, responseSurfaces);
    await exercisePayerHistory(page, recipientId, guardianAId, responseSurfaces);
    await exercisePayerGuardianSelection(
      page,
      recipientId,
      guardianAId,
      guardianBId,
      responseSurfaces,
    );

    await snapshotDomAcrossNavigations(
      page,
      domSurfacesAcrossNavigations,
      urlSurfaces,
      'W1B_E2E_DOM_BEFORE_RELOAD',
    );
    await page.reload();
    await expect(page.getByTestId('page-recipients'), 'W1B_E2E_POST_HISTORY_PAGE').toBeVisible();
    await expect(page.getByTestId('recipient-guardian-1-section'), 'W1B_E2E_GUARDIAN_UI_READBACK').toBeVisible();
    await expect(page.getByTestId('recipient-guardian-2-section'), 'W1B_E2E_GUARDIAN2_UI_READBACK').toBeVisible();

    await snapshotDomAcrossNavigations(
      page,
      domSurfacesAcrossNavigations,
      urlSurfaces,
      'W1B_E2E_DOM_AFTER_RELOAD_BEFORE_GOTO',
    );
    await page.goto('/recipients');
    await expect(page.getByTestId('page-recipients'), 'W1B_E2E_CONTEXT_PAGE_READY').toBeVisible();
    const pageOneResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === '/api/v1/recipients' &&
        response.request().method() === 'GET' &&
        url.searchParams.get('search') === runKey &&
        url.searchParams.get('page') === '1'
      );
    });
    await page.getByTestId('recipient-search-input').fill(runKey);
    const pageOneResponse = await pageOneResponsePromise;
    await pageOneResponse.finished();
    expect(pageOneResponse.ok(), 'W1B_E2E_CONTEXT_PAGE_ONE_RESPONSE').toBe(true);
    await expect(page, 'W1B_E2E_CONTEXT_SEARCH_URL_READY').toHaveURL(
      (url) =>
        url.searchParams.get('search') === runKey &&
        url.searchParams.get('status') === 'ACTIVE' &&
        !url.searchParams.has('page'),
    );
    await expect(page.getByTestId('recipient-page-indicator'), 'W1B_E2E_CONTEXT_PAGE_INDICATOR_FORBIDDEN').toHaveCount(0);
    await expect(page.getByRole('button', { name: '이전', exact: true }), 'W1B_E2E_CONTEXT_PREVIOUS_FORBIDDEN').toHaveCount(0);
    await expect(page.getByRole('button', { name: '다음', exact: true }), 'W1B_E2E_CONTEXT_NEXT_FORBIDDEN').toHaveCount(0);
    await expect(page.getByTestId('recipient-sort-select'), 'W1B_E2E_CONTEXT_SORT_FORBIDDEN').toHaveCount(0);
    const rows = page.getByTestId('recipient-name-option');
    await expect(rows, 'W1B_E2E_CONTEXT_PAGE_ONE_ROWS').toHaveCount(100);
    const pageTwoResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === '/api/v1/recipients' &&
        response.request().method() === 'GET' &&
        url.searchParams.get('search') === runKey &&
        url.searchParams.get('page') === '2'
      );
    });
    const scrollBefore = await page.getByTestId('recipient-list-scroll').evaluate((node) => {
      const element = node as HTMLElement;
      element.scrollTop = element.scrollHeight;
      element.dispatchEvent(new Event('scroll', { bubbles: true }));
      return { clientHeight: element.clientHeight, scrollHeight: element.scrollHeight, scrollTop: element.scrollTop };
    });
    expect(scrollBefore.scrollHeight > scrollBefore.clientHeight, 'W1B_E2E_CONTEXT_SCROLL_REQUIRED').toBe(true);
    expect(scrollBefore.scrollTop, 'W1B_E2E_CONTEXT_SCROLL_SET').toBeGreaterThan(0);
    const pageTwoResponse = await pageTwoResponsePromise;
    await pageTwoResponse.finished();
    expect(pageTwoResponse.ok(), 'W1B_E2E_CONTEXT_PAGE_TWO_RESPONSE').toBe(true);
    await expect(rows, 'W1B_E2E_CONTEXT_APPENDED_ROWS').toHaveCount(103);
    await expect(page, 'W1B_E2E_CONTEXT_PAGE_NOT_EXPOSED').toHaveURL(
      (url) => !url.searchParams.has('page'),
    );



    await Promise.all(responsePromises);
    await snapshotDomAcrossNavigations(page, domSurfacesAcrossNavigations, urlSurfaces, 'W1B_E2E_DOM_FINAL');
    const finalDom = await page.locator('body').innerText();
    assertNoSensitiveSurface(responseSurfaces, 'W1B_E2E_RESPONSE_INTERNAL_LEAK');
    assertNoSensitiveSurface(requestCaptures, 'W1B_E2E_REQUEST_INTERNAL_LEAK');
    assertNoSensitiveSurface(domSurfacesAcrossNavigations, 'W1B_E2E_DOM_OBSERVER_LEAK');
    assertNoSensitiveSurface(finalDom, 'W1B_E2E_DOM_FINAL_LEAK');
    assertNoSensitiveSurface(urlSurfaces, 'W1B_E2E_URL_SURFACE_LEAK');
    expect(/(?:legacy_|payer_type|SELF|PRIMARY_GUARDIAN)/i.test(page.url()), 'W1B_E2E_URL_LEGACY_LEAK').toBe(
      false,
    );
    expect(popupCount, 'W1B_E2E_UNEXPECTED_POPUP').toBe(0);
    expect(pageErrors.count, 'W1B_E2E_PAGE_RUNTIME_ERROR_FINAL').toBe(0);
    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(horizontalOverflow, 'W1B_E2E_HORIZONTAL_OVERFLOW').toBe(false);
  });
});
