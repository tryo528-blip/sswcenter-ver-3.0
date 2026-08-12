import './setup';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import StaffPage from '../pages/StaffPage';

type JsonRecord = Record<string, unknown>;

type RequestRecord = {
  body: unknown;
  method: string;
  path: string;
  url: string;
};

type ErrorPlan = {
  body: JsonRecord;
  status: number;
};

type Fixture = {
  capabilities: {
    view: boolean;
    manage: boolean;
  };
  delayLicenseGet: boolean;
  licensesByStaff: Record<number, JsonRecord[]>;
  nextLicenseError?: ErrorPlan;
  nextQualificationError?: ErrorPlan;
  qualificationsByStaff: Record<number, JsonRecord[]>;
  requests: RequestRecord[];
  resolveLicenseGet?: () => void;
  staffDetails: Record<number, JsonRecord>;
  staffItems: JsonRecord[];
};

const LICENSE_TYPES = [
  { code: 'CARE_WORKER', display_name: '요양보호사' },
  { code: 'SOCIAL_WORKER', display_name: '사회복지사' },
  { code: 'NURSE', display_name: '간호사' },
] as const;

const SERVICE_TYPES = [
  { group_code: 'LONG_TERM_CARE', group_display_name: '장기요양', code: 'HOME_CARE', display_name: '방문요양' },
  { group_code: 'LONG_TERM_CARE', group_display_name: '장기요양', code: 'HOME_BATH', display_name: '방문목욕' },
  { group_code: 'LOCAL_CARE', group_display_name: '지역돌봄 연계', code: 'TEMP_HOME_CARE', display_name: '일시재가' },
  { group_code: 'LOCAL_CARE', group_display_name: '지역돌봄 연계', code: 'HOSPITAL_ESCORT', display_name: '병원동행' },
  { group_code: 'BARO_CARE', group_display_name: '바로돌봄', code: 'BARO_CARE', display_name: '바로돌봄' },
] as const;

const STAFF_A = { id: 7, name: 'W1A 합성 직원 A', employmentId: 101 } as const;
const STAFF_B = { id: 8, name: 'W1A 합성 직원 B', employmentId: 201 } as const;

let fixture: Fixture;

function makeEmployment(staffId: number, employmentId: number): JsonRecord {
  return {
    id: employmentId,
    staff_id: staffId,
    employment_no: 1,
    staff_no: `W1A-${staffId}`,
    start_date: '2026-01-01',
    end_date: null,
    end_reason_code: null,
    status: 'ACTIVE',
    row_version: 1,
  };
}

function makeStaff(staffId: number, name: string, employmentId: number): JsonRecord {
  const employment = makeEmployment(staffId, employmentId);
  return {
    id: staffId,
    name,
    birth_date: '1990-01-01',
    sex_code: 'MALE',
    phone: null,
    address: 'W1A 합성 주소',
    display_name: null,
    memo: null,
    resident_number_masked: '마스킹-합성',
    row_version: 1,
    current_employment: employment,
    current_positions: [],
    current_operational_roles: [],
  };
}

function createFixture(): Fixture {
  const staffA = makeStaff(STAFF_A.id, STAFF_A.name, STAFF_A.employmentId);
  const staffB = makeStaff(STAFF_B.id, STAFF_B.name, STAFF_B.employmentId);
  const licensesA = [
    {
      id: 301,
      staff_id: STAFF_A.id,
      license_type_code: 'CARE_WORKER',
      license_type_display_name: '요양보호사',
      license_number: 'W1A-LIC-A-1',
      issued_date: '2022-01-01',
      row_version: 1,
    },
    {
      id: 302,
      staff_id: STAFF_A.id,
      license_type_code: 'SOCIAL_WORKER',
      license_type_display_name: '사회복지사',
      license_number: 'W1A-LIC-A-2',
      issued_date: '2023-01-01',
      row_version: 1,
    },
    {
      id: 303,
      staff_id: STAFF_A.id,
      license_type_code: 'NURSE',
      license_type_display_name: '간호사',
      license_number: 'W1A-LIC-A-3',
      issued_date: '2024-01-01',
      row_version: 1,
    },
  ];

  return {
    capabilities: { view: true, manage: true },
    delayLicenseGet: false,
    licensesByStaff: { [STAFF_A.id]: licensesA, [STAFF_B.id]: [] },
    qualificationsByStaff: { [STAFF_A.id]: [], [STAFF_B.id]: [] },
    requests: [],
    staffDetails: {
      [STAFF_A.id]: {
        ...staffA,
        employments: [makeEmployment(STAFF_A.id, STAFF_A.employmentId)],
        positions: [],
        operational_roles: [],
      },
      [STAFF_B.id]: {
        ...staffB,
        employments: [makeEmployment(STAFF_B.id, STAFF_B.employmentId)],
        positions: [],
        operational_roles: [],
      },
    },
    staffItems: [staffA, staffB],
  };
}

function jsonResponse(body: JsonRecord, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestPath(input: RequestInfo | URL): { path: string; url: string } {
  const url = typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
  return { path: new URL(url, 'http://w1a.test').pathname, url };
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

function recordRequest(path: string, url: string, method: string, body: unknown): void {
  fixture.requests.push({ body, method, path, url });
}

function errorResponse(plan: ErrorPlan): Response {
  return jsonResponse(plan.body, plan.status);
}

function installFetchFixture(): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const { path, url } = requestPath(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const body = parseBody(init?.body);
    recordRequest(path, url, method, body);

    if (path === '/api/v1/session-capabilities') {
      return jsonResponse({
        'staff.view': fixture.capabilities.view,
        'staff.manage': fixture.capabilities.manage,
        'staff.sensitive_identity.reveal': false,
      });
    }
    if (path === '/api/v1/catalogs/license-types') {
      return jsonResponse({ items: LICENSE_TYPES });
    }
    if (path === '/api/v1/catalogs/services') {
      return jsonResponse({ items: SERVICE_TYPES });
    }

    const licenseMatch = path.match(/^\/api\/v1\/staff\/(\d+)\/licenses$/);
    if (licenseMatch) {
      const staffId = Number(licenseMatch[1]);
      if (method === 'GET') {
        if (fixture.delayLicenseGet && staffId === STAFF_A.id) {
          return new Promise<Response>((resolve) => {
            fixture.resolveLicenseGet = () =>
              resolve(jsonResponse({
                items: fixture.licensesByStaff[staffId] ?? [],
                total: (fixture.licensesByStaff[staffId] ?? []).length,
                page: 1,
                page_size: 100,
              }));
          });
        }
        const items = fixture.licensesByStaff[staffId] ?? [];
        return jsonResponse({ items, total: items.length, page: 1, page_size: 100 });
      }
      if (method === 'POST') {
        if (fixture.nextLicenseError) {
          const plan = fixture.nextLicenseError;
          fixture.nextLicenseError = undefined;
          return errorResponse(plan);
        }
        const payload = (body ?? {}) as JsonRecord;
        const next = {
          id: 400 + (fixture.licensesByStaff[staffId] ?? []).length,
          staff_id: staffId,
          ...payload,
          row_version: 1,
        };
        fixture.licensesByStaff[staffId] = [
          ...(fixture.licensesByStaff[staffId] ?? []),
          next,
        ];
        return jsonResponse(next, 201);
      }
    }

    const qualificationMatch = path.match(
      /^\/api\/v1\/staff\/(\d+)\/service-qualifications$/,
    );
    if (qualificationMatch) {
      const staffId = Number(qualificationMatch[1]);
      if (method === 'GET') {
        const items = fixture.qualificationsByStaff[staffId] ?? [];
        return jsonResponse({ items, total: items.length, page: 1, page_size: 100 });
      }
      if (method === 'POST') {
        if (fixture.nextQualificationError) {
          const plan = fixture.nextQualificationError;
          fixture.nextQualificationError = undefined;
          return errorResponse(plan);
        }
        const payload = (body ?? {}) as JsonRecord;
        const next = {
          id: 500 + (fixture.qualificationsByStaff[staffId] ?? []).length,
          staff_id: staffId,
          ...payload,
          row_version: 1,
        };
        fixture.qualificationsByStaff[staffId] = [
          ...(fixture.qualificationsByStaff[staffId] ?? []),
          next,
        ];
        return jsonResponse(next, 201);
      }
    }

    const detailMatch = path.match(/^\/api\/v1\/staff\/(\d+)$/);
    if (detailMatch && method === 'GET') {
      const staffId = Number(detailMatch[1]);
      return jsonResponse({
        ...(fixture.staffDetails[staffId] ?? {}),
        licenses: fixture.licensesByStaff[staffId] ?? [],
        service_qualifications: fixture.qualificationsByStaff[staffId] ?? [],
      });
    }
    if (path === '/api/v1/staff' && method === 'GET') {
      const listUrl = new URL(url, 'http://w1a.test');
      const page = Number(listUrl.searchParams.get('page') ?? '1');
      const pageSize = Number(listUrl.searchParams.get('page_size') ?? '2');
      return jsonResponse({
        items: fixture.staffItems,
        total: Math.max(fixture.staffItems.length, 4),
        page,
        page_size: pageSize,
      });
    }
    return jsonResponse({ detail: 'not_found' }, 404);
  });
}

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderStaffPage(useBrowserHistory = false) {
  const queryClient = createQueryClient();
  const content = (
    <QueryClientProvider client={queryClient}>
      {useBrowserHistory ? (
        <BrowserRouter>
          <StaffPage />
        </BrowserRouter>
      ) : (
        <MemoryRouter>
          <StaffPage />
        </MemoryRouter>
      )}
    </QueryClientProvider>
  );
  return render(content);
}

function mustElement<T extends HTMLElement>(element: T | null, marker: string): T {
  expect(element, marker).not.toBeNull();
  return element as T;
}

function requestExists(method: string, pathPart: string): boolean {
  return fixture.requests.some(
    (request) => request.method === method && request.path.includes(pathPart),
  );
}

function latestRequest(method: string, pathPart: string, marker: string): RequestRecord {
  const matching = fixture.requests.filter(
    (request) => request.method === method && request.path.includes(pathPart),
  );
  expect(matching.length > 0, marker).toBe(true);
  return matching[matching.length - 1] as RequestRecord;
}

function bodyRecord(request: RequestRecord, marker: string): JsonRecord {
  expect(typeof request.body === 'object' && request.body !== null, marker).toBe(true);
  return request.body as JsonRecord;
}

function expectKeysAbsent(record: JsonRecord, keys: string[], marker: string): void {
  expect(keys.every((key) => !(key in record)), marker).toBe(true);
}

async function selectStaff(name: string, marker: string): Promise<void> {
  await waitFor(() =>
    expect(screen.queryAllByText(name, { exact: true }).length > 0, marker).toBe(true),
  );
  const matches = screen.getAllByText(name, { exact: true });
  fireEvent.click(matches[0]);
  await waitFor(() =>
    expect(screen.queryByTestId('staff-detail-workspace'), marker).not.toBeNull(),
  );
}

async function openTab(name: RegExp, marker: string): Promise<HTMLElement> {
  const tab = mustElement(screen.queryByRole('tab', { name }), marker);
  fireEvent.click(tab);
  return tab;
}

async function openForm(
  formTestId: string,
  addButton: RegExp,
  marker: string,
): Promise<HTMLElement> {
  let form = screen.queryByTestId(formTestId);
  if (!form) {
    const add = mustElement(screen.queryByRole('button', { name: addButton }), marker);
    fireEvent.click(add);
  }
  await waitFor(() =>
    expect(screen.queryByTestId(formTestId), marker).not.toBeNull(),
  );
  form = screen.queryByTestId(formTestId);
  return mustElement(form, marker);
}

function labelled(form: HTMLElement, label: RegExp, marker: string): HTMLElement {
  return mustElement(within(form).queryByLabelText(label), marker);
}

function submitButton(form: HTMLElement, marker: string): HTMLElement {
  return mustElement(
    within(form).queryByRole('button', { name: /등록|추가|저장|제출/ }),
    marker,
  );
}

function fillLicenseForm(form: HTMLElement, code: string, number: string): void {
  fireEvent.change(labelled(form, /^자격종류$/, 'W1A_VS2_LICENSE_TYPE_FIELD_MISSING'), {
    target: { value: code },
  });
  fireEvent.change(labelled(form, /^자격번호$/, 'W1A_VS2_LICENSE_NUMBER_FIELD_MISSING'), {
    target: { value: number },
  });
  fireEvent.change(labelled(form, /^발급일$/, 'W1A_VS2_LICENSE_ISSUED_DATE_FIELD_MISSING'), {
    target: { value: '2025-01-01' },
  });
}

function fillQualificationForm(
  form: HTMLElement,
  sourceValue = '',
  employmentId: number = STAFF_A.employmentId,
): void {
  const employment = labelled(form, /^재직$/, 'W1A_VS2_QUALIFICATION_EMPLOYMENT_FIELD_MISSING');
  const service = labelled(form, /^서비스종류$/, 'W1A_VS2_QUALIFICATION_SERVICE_FIELD_MISSING');
  const start = labelled(form, /^시작일$/, 'W1A_VS2_QUALIFICATION_START_FIELD_MISSING');
  const source = labelled(form, /근거.*자격증/, 'W1A_VS2_QUALIFICATION_SOURCE_FIELD_MISSING');
  fireEvent.change(employment, { target: { value: String(employmentId) } });
  fireEvent.change(service, { target: { value: 'HOME_CARE' } });
  fireEvent.change(start, { target: { value: '2025-02-01' } });
  fireEvent.change(source, { target: { value: sourceValue } });
}

beforeEach(() => {
  fixture = createFixture();
  installFetchFixture();
});

afterEach(() => {
  window.history.replaceState({}, '', '/');
  vi.restoreAllMocks();
});

describe('W1A-VS2 staff license and service qualification RED contract', () => {
  test('renders separate tabs, exact catalog options, three rows, and a fourth license', async () => {
    renderStaffPage();
    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_DETAIL_MISSING');

    const licenseTab = await openTab(/자격증/, 'W1A_VS2_DOM_LICENSE_TAB_MISSING');
    await openTab(/서비스 제공자격/, 'W1A_VS2_DOM_QUALIFICATION_TAB_MISSING');
    fireEvent.click(licenseTab);
    const form = await openForm(
      'staff-license-form',
      /자격증.*(?:추가|등록)/,
      'W1A_VS2_DOM_LICENSE_FORM_MISSING',
    );
    const licenseType = labelled(form, /^자격종류$/, 'W1A_VS2_LICENSE_TYPE_FIELD_MISSING') as HTMLSelectElement;
    const observedOptions = Array.from(licenseType.options)
      .filter((option) => option.value)
      .map((option) => ({ code: option.value, display_name: option.textContent?.trim() ?? '' }));
    expect(
      JSON.stringify(observedOptions) === JSON.stringify(LICENSE_TYPES),
      'W1A_VS2_DOM_LICENSE_CATALOG_OPTIONS_MISMATCH',
    ).toBe(true);
    await waitFor(() =>
      expect(
        document.querySelectorAll('[data-testid="staff-license-row"]').length >= 3,
        'W1A_VS2_DOM_THREE_LICENSES_MISSING',
      ).toBe(true),
    );
    expect(
      form.querySelector('[name="expiry_date"], [name="start_date"], [name="end_date"]') === null,
      'W1A_VS2_DOM_LICENSE_PERIOD_FIELDS_FORBIDDEN',
    ).toBe(true);

    fillLicenseForm(form, 'CARE_WORKER', 'W1A-LIC-A-4');
    fireEvent.click(submitButton(form, 'W1A_VS2_DOM_LICENSE_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(requestExists('POST', `/staff/${STAFF_A.id}/licenses`), 'W1A_VS2_LICENSE_CREATE_REQUEST_MISSING').toBe(
        true,
      ),
    );
    await waitFor(() =>
      expect(
        document.querySelectorAll('[data-testid="staff-license-row"]').length >= 4,
        'W1A_VS2_DOM_FOURTH_LICENSE_NOT_ADDABLE',
      ).toBe(true),
    );
  });

  test('creates qualification without a license and accepts an optional same-staff source', async () => {
    renderStaffPage();
    await selectStaff(STAFF_B.name, 'W1A_VS2_DOM_STAFF_B_DETAIL_MISSING');
    await openTab(/자격증/, 'W1A_VS2_DOM_LICENSE_TAB_MISSING');
    const qualificationTab = await openTab(
      /서비스 제공자격/,
      'W1A_VS2_DOM_QUALIFICATION_TAB_MISSING',
    );
    fireEvent.click(qualificationTab);
    const formWithoutSource = await openForm(
      'staff-qualification-form',
      /서비스 제공자격.*(?:추가|등록)/,
      'W1A_VS2_DOM_QUALIFICATION_FORM_MISSING',
    );
    const sourceWithoutLicense = labelled(
      formWithoutSource,
      /근거.*자격증/,
      'W1A_VS2_QUALIFICATION_SOURCE_FIELD_MISSING',
    ) as HTMLSelectElement;
    expect(
      sourceWithoutLicense.required === false && sourceWithoutLicense.value === '',
      'W1A_VS2_QUALIFICATION_SOURCE_MUST_BE_OPTIONAL',
    ).toBe(true);
    fillQualificationForm(formWithoutSource, '', STAFF_B.employmentId);
    fireEvent.click(submitButton(formWithoutSource, 'W1A_VS2_QUALIFICATION_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(
        requestExists('POST', `/staff/${STAFF_B.id}/service-qualifications`),
        'W1A_VS2_QUALIFICATION_WITHOUT_LICENSE_REQUEST_MISSING',
      ).toBe(true),
    );
    const noSourceBody = bodyRecord(
      latestRequest(
        'POST',
        `/staff/${STAFF_B.id}/service-qualifications`,
        'W1A_VS2_QUALIFICATION_WITHOUT_LICENSE_REQUEST_MISSING',
      ),
      'W1A_VS2_QUALIFICATION_REQUEST_BODY_MISSING',
    );
    expect(
      noSourceBody.source_license_id == null,
      'W1A_VS2_QUALIFICATION_SOURCE_NOT_OPTIONAL',
    ).toBe(true);
    expectKeysAbsent(
      noSourceBody,
      ['license_number', 'issued_date'],
      'W1A_VS2_QUALIFICATION_DUPLICATES_LICENSE_FACTS',
    );

    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_A_DETAIL_MISSING');
    const sourceForm = await openForm(
      'staff-qualification-form',
      /서비스 제공자격.*(?:추가|등록)/,
      'W1A_VS2_DOM_QUALIFICATION_FORM_MISSING',
    );
    const sourceSelect = labelled(
      sourceForm,
      /근거.*자격증/,
      'W1A_VS2_QUALIFICATION_SOURCE_FIELD_MISSING',
    ) as HTMLSelectElement;
    const sourceOption = Array.from(sourceSelect.options).find((option) => option.value);
    expect(sourceOption !== undefined, 'W1A_VS2_SAME_STAFF_SOURCE_OPTION_MISSING').toBe(true);
    fillQualificationForm(sourceForm, sourceOption?.value ?? '');
    fireEvent.click(submitButton(sourceForm, 'W1A_VS2_QUALIFICATION_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(
        requestExists('POST', `/staff/${STAFF_A.id}/service-qualifications`),
        'W1A_VS2_SAME_STAFF_SOURCE_REQUEST_MISSING',
      ).toBe(true),
    );
    const sourceBody = bodyRecord(
      latestRequest(
        'POST',
        `/staff/${STAFF_A.id}/service-qualifications`,
        'W1A_VS2_SAME_STAFF_SOURCE_REQUEST_MISSING',
      ),
      'W1A_VS2_SAME_STAFF_SOURCE_BODY_MISSING',
    );
    expect(
      typeof sourceBody.source_license_id === 'number' || typeof sourceBody.source_license_id === 'string',
      'W1A_VS2_SAME_STAFF_SOURCE_NOT_SENT',
    ).toBe(true);
    expectKeysAbsent(
      sourceBody,
      ['license_number', 'issued_date'],
      'W1A_VS2_QUALIFICATION_DUPLICATES_LICENSE_FACTS',
    );
  });

  test('keeps STAFF_VIEW read-only and hides all mutation controls from USER', async () => {
    fixture.capabilities = { view: true, manage: false };
    const viewPage = renderStaffPage();
    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_DETAIL_MISSING');
    await openTab(/자격증/, 'W1A_VS2_DOM_LICENSE_TAB_MISSING');
    expect(
      screen.queryByRole('button', { name: /자격증.*(?:추가|등록)/ }),
      'W1A_VS2_STAFF_VIEW_MUTATION_CONTROL_VISIBLE',
    ).toBeNull();
    await openTab(/서비스 제공자격/, 'W1A_VS2_DOM_QUALIFICATION_TAB_MISSING');
    expect(
      screen.queryByRole('button', { name: /서비스 제공자격.*(?:추가|등록)/ }),
      'W1A_VS2_STAFF_VIEW_QUALIFICATION_MUTATION_VISIBLE',
    ).toBeNull();
    viewPage.unmount();

    fixture.capabilities = { view: false, manage: false };
    renderStaffPage();
    expect(
      screen.queryByRole('button', { name: /자격증.*(?:추가|등록)/ }),
      'W1A_VS2_USER_LICENSE_MUTATION_VISIBLE',
    ).toBeNull();
    expect(
      screen.queryByRole('button', { name: /서비스 제공자격.*(?:추가|등록)/ }),
      'W1A_VS2_USER_QUALIFICATION_MUTATION_VISIBLE',
    ).toBeNull();
  });

  test('shows loading and empty states for the license list', async () => {
    fixture.delayLicenseGet = true;
    fixture.licensesByStaff[STAFF_A.id] = [];
    renderStaffPage();
    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_DETAIL_MISSING');
    await openTab(/자격증/, 'W1A_VS2_DOM_LICENSE_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/불러오는 중|loading/i) !== null,
        'W1A_VS2_LICENSE_LOADING_STATE_MISSING',
      ).toBe(true),
    );
    fixture.resolveLicenseGet?.();
    await waitFor(() =>
      expect(
        screen.queryByText(/등록된 자격증이 없습니다|empty/i) !== null,
        'W1A_VS2_LICENSE_EMPTY_STATE_MISSING',
      ).toBe(true),
    );
  });

  test('preserves fields across structured 409 and 422 errors without internal response leakage', async () => {
    fixture.nextLicenseError = {
      status: 409,
      body: {
        error: { code: 'ROW_VERSION_CONFLICT', message: '최신 정보를 확인해 다시 시도하세요.' },
        details: { internal: 'sqlalchemy constraint DSN SELECT' },
      },
    };
    renderStaffPage();
    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_DETAIL_MISSING');
    await openTab(/자격증/, 'W1A_VS2_DOM_LICENSE_TAB_MISSING');
    const licenseForm = await openForm(
      'staff-license-form',
      /자격증.*(?:추가|등록)/,
      'W1A_VS2_DOM_LICENSE_FORM_MISSING',
    );
    fillLicenseForm(licenseForm, 'CARE_WORKER', 'W1A-LIC-CONFLICT');
    fireEvent.click(submitButton(licenseForm, 'W1A_VS2_LICENSE_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(requestExists('POST', `/staff/${STAFF_A.id}/licenses`), 'W1A_VS2_LICENSE_409_REQUEST_MISSING').toBe(
        true,
      ),
    );
    const licenseNumber = labelled(
      licenseForm,
      /^자격번호$/,
      'W1A_VS2_LICENSE_NUMBER_FIELD_MISSING',
    ) as HTMLInputElement;
    expect(licenseNumber.value === 'W1A-LIC-CONFLICT', 'W1A_VS2_409_INPUT_NOT_PRESERVED').toBe(true);
    const conflictAlert = screen.queryByRole('alert');
    expect(conflictAlert !== null, 'W1A_VS2_409_STRUCTURED_ERROR_UI_MISSING').toBe(true);
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(conflictAlert?.textContent ?? ''),
      'W1A_VS2_INTERNAL_ERROR_LEAKED_IN_DOM',
    ).toBe(true);

    fixture.nextQualificationError = {
      status: 422,
      body: {
        error: { code: 'VALIDATION_ERROR', message: '입력값을 확인하세요.' },
        field_errors: [{ field: 'start_date', message: '재직기간 안의 날짜를 입력하세요.' }],
        details: { internal: 'sqlalchemy constraint DSN SELECT' },
      },
    };
    await openTab(/서비스 제공자격/, 'W1A_VS2_DOM_QUALIFICATION_TAB_MISSING');
    const qualificationForm = await openForm(
      'staff-qualification-form',
      /서비스 제공자격.*(?:추가|등록)/,
      'W1A_VS2_DOM_QUALIFICATION_FORM_MISSING',
    );
    fillQualificationForm(qualificationForm);
    fireEvent.click(submitButton(qualificationForm, 'W1A_VS2_QUALIFICATION_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(
        requestExists('POST', `/staff/${STAFF_A.id}/service-qualifications`),
        'W1A_VS2_QUALIFICATION_422_REQUEST_MISSING',
      ).toBe(true),
    );
    const startDate = labelled(
      qualificationForm,
      /^시작일$/,
      'W1A_VS2_QUALIFICATION_START_FIELD_MISSING',
    ) as HTMLInputElement;
    expect(startDate.value === '2025-02-01', 'W1A_VS2_422_INPUT_NOT_PRESERVED').toBe(true);
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(document.body.textContent ?? ''),
      'W1A_VS2_INTERNAL_ERROR_LEAKED_IN_DOM',
    ).toBe(true);
  });

  test('preserves search, sort, page, scroll, selected tab, and A-to-B-back context by interaction', async () => {
    window.history.replaceState({}, '', '/staff?context=before');
    window.history.pushState({}, '', '/staff?context=detail');
    renderStaffPage(true);
    const search = (await screen.findByLabelText(/^직원 검색$/)) as HTMLInputElement;
    fireEvent.change(search, { target: { value: 'W1A 합성' } });
    const searchForm = mustElement(search.closest('form'), 'W1A_VS2_LIST_SEARCH_FORM_MISSING');
    fireEvent.submit(searchForm);
    await waitFor(() =>
      expect(
        fixture.requests.some((request) => request.method === 'GET' && request.url.includes('search=')),
        'W1A_VS2_LIST_SEARCH_REQUEST_MISSING',
      ).toBe(true),
    );

    const sort = mustElement(
      screen.queryByLabelText(/정렬/),
      'W1A_VS2_LIST_SORT_CONTROL_MISSING',
    ) as HTMLSelectElement;
    const sortOption = Array.from(sort.options).find((option) => option.value && option.value !== sort.value);
    expect(sortOption !== undefined, 'W1A_VS2_LIST_SORT_OPTIONS_MISSING').toBe(true);
    fireEvent.change(sort, { target: { value: sortOption?.value ?? '' } });
    const nextPage = mustElement(
      screen.queryByRole('button', { name: /다음 페이지|next/i }),
      'W1A_VS2_LIST_PAGINATION_CONTROL_MISSING',
    );
    fireEvent.click(nextPage);
    await waitFor(() =>
      expect(
        fixture.requests.some((request) => request.method === 'GET' && /[?&]page=2(?:&|$)/.test(request.url)),
        'W1A_VS2_LIST_PAGE_REQUEST_MISSING',
      ).toBe(true),
    );

    const scrollContainer = mustElement(
      document.querySelector<HTMLElement>('[data-testid="staff-list-scroll"], .staff-list'),
      'W1A_VS2_LIST_SCROLL_SURFACE_MISSING',
    );
    scrollContainer.scrollTop = 32;
    fireEvent.scroll(scrollContainer);
    expect(scrollContainer.scrollTop > 0, 'W1A_VS2_LIST_SCROLL_NOT_RETAINED').toBe(true);

    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_A_DETAIL_MISSING');
    await openTab(/서비스 제공자격/, 'W1A_VS2_DOM_QUALIFICATION_TAB_MISSING');
    await selectStaff(STAFF_B.name, 'W1A_VS2_DOM_STAFF_B_DETAIL_MISSING');
    const searchAfterB = mustElement(
      screen.queryByLabelText(/^직원 검색$/),
      'W1A_VS2_LIST_SEARCH_SURFACE_MISSING_AFTER_B',
    ) as HTMLInputElement;
    const sortAfterB = mustElement(
      screen.queryByLabelText(/정렬/),
      'W1A_VS2_LIST_SORT_SURFACE_MISSING_AFTER_B',
    ) as HTMLSelectElement;
    const scrollAfterB = mustElement(
      document.querySelector<HTMLElement>('[data-testid="staff-list-scroll"], .staff-list'),
      'W1A_VS2_LIST_SCROLL_SURFACE_MISSING_AFTER_B',
    );
    const latestListRequestAfterB = fixture.requests
      .filter((request) => request.method === 'GET' && request.path === '/api/v1/staff')
      .at(-1);
    const qualificationTabAfterB = mustElement(
      screen.queryByRole('tab', { name: /서비스 제공자격/ }),
      'W1A_VS2_QUALIFICATION_TAB_SURFACE_MISSING_AFTER_B',
    );
    const currentPageAfterB = mustElement(
      screen.queryByTestId('staff-page-indicator'),
      'W1A_VS2_LIST_PAGE_DISPLAY_MISSING_AFTER_B',
    );
    expect(
      searchAfterB.value === 'W1A 합성',
      'W1A_VS2_LIST_SEARCH_CONTEXT_LOST_A_TO_B',
    ).toBe(true);
    expect(
      sortAfterB.value === sortOption?.value,
      'W1A_VS2_LIST_SORT_CONTEXT_LOST_A_TO_B',
    ).toBe(true);
    expect(
      qualificationTabAfterB.getAttribute('aria-selected') === 'true',
      'W1A_VS2_SELECTED_TAB_CONTEXT_LOST_A_TO_B',
    ).toBe(true);
    expect(scrollAfterB.scrollTop > 0, 'W1A_VS2_LIST_SCROLL_CONTEXT_LOST_A_TO_B').toBe(true);
    expect(
      latestListRequestAfterB?.url.includes('page=2') === true &&
        /(^|\D)2(\D|$)/.test(currentPageAfterB.textContent ?? ''),
      'W1A_VS2_LIST_PAGE_CONTEXT_LOST_A_TO_B',
    ).toBe(true);

    window.history.back();
    await waitFor(() =>
      expect(window.location.search.includes('context=before'), 'W1A_VS2_BACK_NAVIGATION_NOT_PERFORMED').toBe(
        true,
      ),
    );
    const searchAfterBack = mustElement(
      screen.queryByLabelText(/^직원 검색$/),
      'W1A_VS2_LIST_SEARCH_SURFACE_MISSING_AFTER_BACK',
    ) as HTMLInputElement;
    const sortAfterBack = mustElement(
      screen.queryByLabelText(/정렬/),
      'W1A_VS2_LIST_SORT_SURFACE_MISSING_AFTER_BACK',
    ) as HTMLSelectElement;
    const scrollAfterBack = mustElement(
      document.querySelector<HTMLElement>('[data-testid="staff-list-scroll"], .staff-list'),
      'W1A_VS2_LIST_SCROLL_SURFACE_MISSING_AFTER_BACK',
    );
    const qualificationTabAfterBack = mustElement(
      screen.queryByRole('tab', { name: /서비스 제공자격/ }),
      'W1A_VS2_QUALIFICATION_TAB_SURFACE_MISSING_AFTER_BACK',
    );
    const currentPageAfterBack = mustElement(
      screen.queryByTestId('staff-page-indicator'),
      'W1A_VS2_LIST_PAGE_DISPLAY_MISSING_AFTER_BACK',
    );
    const latestListRequestAfterBack = fixture.requests
      .filter((request) => request.method === 'GET' && request.path === '/api/v1/staff')
      .at(-1);
    expect(searchAfterBack.value === 'W1A 합성', 'W1A_VS2_LIST_CONTEXT_LOST_AFTER_BACK').toBe(true);
    expect(sortAfterBack.value === sortOption?.value, 'W1A_VS2_LIST_SORT_LOST_AFTER_BACK').toBe(true);
    expect(scrollAfterBack.scrollTop > 0, 'W1A_VS2_LIST_SCROLL_LOST_AFTER_BACK').toBe(true);
    expect(
      qualificationTabAfterBack.getAttribute('aria-selected') === 'true',
      'W1A_VS2_SELECTED_TAB_LOST_AFTER_BACK',
    ).toBe(true);
    expect(
      latestListRequestAfterBack?.url.includes('page=2') === true &&
        /(^|\D)2(\D|$)/.test(currentPageAfterBack.textContent ?? ''),
      'W1A_VS2_LIST_PAGE_LOST_AFTER_BACK',
    ).toBe(true);
  });

  test('restores A after A-to-B browser back when page two only lists B', async () => {
    window.history.replaceState({}, '', '/staff');
    renderStaffPage(true);
    await selectStaff(STAFF_A.name, 'W1A_VS2_BACK_TARGET_A_INITIAL_DETAIL_MISSING');

    fixture.staffItems = fixture.staffItems.filter((item) => item.id === STAFF_B.id);
    const nextPage = mustElement(
      screen.queryByRole('button', { name: /다음 페이지|next/i }),
      'W1A_VS2_BACK_TARGET_PAGE_CONTROL_MISSING',
    );
    fireEvent.click(nextPage);
    await waitFor(() =>
      expect(
        fixture.requests.some(
          (request) => request.method === 'GET' && /[?&]page=2(?:&|$)/.test(request.url),
        ),
        'W1A_VS2_BACK_TARGET_PAGE_TWO_REQUEST_MISSING',
      ).toBe(true),
    );
    await waitFor(() =>
      expect(
        screen.queryByTestId('staff-page-indicator')?.textContent === '2' &&
          screen.queryAllByText(STAFF_B.name, { exact: true }).length > 0,
        'W1A_VS2_BACK_TARGET_PAGE_TWO_B_MISSING',
      ).toBe(true),
    );

    await selectStaff(STAFF_B.name, 'W1A_VS2_BACK_TARGET_B_DETAIL_MISSING');
    await waitFor(() =>
      expect(
        new URLSearchParams(window.location.search).get('staff_id') === String(STAFF_B.id),
        'W1A_VS2_BACK_TARGET_B_URL_MISSING',
      ).toBe(true),
    );

    window.history.back();
    await waitFor(() =>
      expect(
        new URLSearchParams(window.location.search).get('staff_id') === String(STAFF_A.id),
        'W1A_VS2_BACK_TARGET_A_URL_NOT_RESTORED',
      ).toBe(true),
    );
    await waitFor(() =>
      expect(
        screen.getByTestId('staff-detail-workspace').textContent?.includes(STAFF_A.name),
        'W1A_VS2_BACK_TARGET_A_DETAIL_NOT_RESTORED',
      ).toBe(true),
    );
  });

  test('keeps license and qualification request bodies separate and never opens a popup', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderStaffPage();
    await selectStaff(STAFF_A.name, 'W1A_VS2_DOM_STAFF_DETAIL_MISSING');
    await openTab(/자격증/, 'W1A_VS2_DOM_LICENSE_TAB_MISSING');
    const licenseForm = await openForm(
      'staff-license-form',
      /자격증.*(?:추가|등록)/,
      'W1A_VS2_DOM_LICENSE_FORM_MISSING',
    );
    fillLicenseForm(licenseForm, 'NURSE', 'W1A-LIC-SEPARATE');
    fireEvent.click(submitButton(licenseForm, 'W1A_VS2_LICENSE_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(requestExists('POST', `/staff/${STAFF_A.id}/licenses`), 'W1A_VS2_LICENSE_ROUTE_REQUEST_MISSING').toBe(
        true,
      ),
    );
    const licenseBody = bodyRecord(
      latestRequest('POST', `/staff/${STAFF_A.id}/licenses`, 'W1A_VS2_LICENSE_ROUTE_REQUEST_MISSING'),
      'W1A_VS2_LICENSE_REQUEST_BODY_MISSING',
    );
    expect(
      typeof licenseBody.license_type_code === 'string' &&
        typeof licenseBody.license_number === 'string' &&
        typeof licenseBody.issued_date === 'string',
      'W1A_VS2_LICENSE_REQUEST_BODY_FIELDS_MISSING',
    ).toBe(true);
    expectKeysAbsent(
      licenseBody,
      ['employment_id', 'service_type_code', 'source_license_id', 'expiry_date'],
      'W1A_VS2_LICENSE_REQUEST_MIXES_QUALIFICATION_FIELDS',
    );

    await openTab(/서비스 제공자격/, 'W1A_VS2_DOM_QUALIFICATION_TAB_MISSING');
    const qualificationForm = await openForm(
      'staff-qualification-form',
      /서비스 제공자격.*(?:추가|등록)/,
      'W1A_VS2_DOM_QUALIFICATION_FORM_MISSING',
    );
    fillQualificationForm(qualificationForm);
    fireEvent.click(submitButton(qualificationForm, 'W1A_VS2_QUALIFICATION_SUBMIT_MISSING'));
    await waitFor(() =>
      expect(
        requestExists('POST', `/staff/${STAFF_A.id}/service-qualifications`),
        'W1A_VS2_QUALIFICATION_ROUTE_REQUEST_MISSING',
      ).toBe(true),
    );
    const qualificationBody = bodyRecord(
      latestRequest(
        'POST',
        `/staff/${STAFF_A.id}/service-qualifications`,
        'W1A_VS2_QUALIFICATION_ROUTE_REQUEST_MISSING',
      ),
      'W1A_VS2_QUALIFICATION_REQUEST_BODY_MISSING',
    );
    expect(
      typeof qualificationBody.employment_id === 'number' || typeof qualificationBody.employment_id === 'string',
      'W1A_VS2_QUALIFICATION_REQUEST_FIELDS_MISSING',
    ).toBe(true);
    expect(
      typeof qualificationBody.service_type_code === 'string' &&
        typeof qualificationBody.start_date === 'string',
      'W1A_VS2_QUALIFICATION_REQUEST_FIELDS_MISSING',
    ).toBe(true);
    expectKeysAbsent(
      qualificationBody,
      ['license_number', 'issued_date', 'expiry_date', 'schedule_id', 'assignment_id', 'file_id'],
      'W1A_VS2_QUALIFICATION_REQUEST_MIXES_LICENSE_OR_FUTURE_FIELDS',
    );
    expect(windowOpen, 'W1A_VS2_POPUP_FORBIDDEN').not.toHaveBeenCalled();
    const requestSurface = JSON.stringify(fixture.requests);
    const domSurface = document.body.textContent ?? '';
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(`${requestSurface}\n${domSurface}`),
      'W1A_VS2_INTERNAL_ERROR_OR_SECRET_LEAKED',
    ).toBe(true);
  });
});
