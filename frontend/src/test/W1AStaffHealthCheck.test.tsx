import './setup';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { BrowserRouter, MemoryRouter } from 'react-router';
import App from '../App';
import StaffPage from '../pages/StaffPage';
import { AUTH_SESSION_CHANGED_EVENT } from '../services/api';

type JsonRecord = Record<string, unknown>;

type RequestRecord = {
  body: unknown;
  method: string;
  path: string;
  signal: AbortSignal | undefined;
};

type HealthMode =
  | 'loading'
  | 'success'
  | 'empty'
  | 'error'
  | 'forbidden'
  | 'conflict'
  | 'invalid';

const STAFF_A = { id: 81, name: 'W1A-VS4 합성 직원 A', employmentId: 801 } as const;
const STAFF_B = { id: 82, name: 'W1A-VS4 합성 직원 B', employmentId: 802 } as const;

const HEALTH_FACTS = [
  {
    id: 1801,
    staff_id: STAFF_A.id,
    employment_id: STAFF_A.employmentId,
    check_date: '2026-01-15',
    check_type_code: 'GENERAL',
    result_note: 'VS4 synthetic fact one',
  },
  {
    id: 1802,
    staff_id: STAFF_A.id,
    employment_id: STAFF_A.employmentId,
    check_date: '2026-01-15',
    check_type_code: 'GENERAL',
    result_note: 'VS4 synthetic fact two',
  },
] as const;

const HEALTH_REQUIREMENTS = [
  {
    id: 1901,
    staff_id: STAFF_A.id,
    employment_id: STAFF_A.employmentId,
    target_key: 'VS4_SYNTHETIC_COMPLETE',
    target_rule_version_code: 'VS4_RULE_1',
    status: 'COMPLETE',
    health_check_id: HEALTH_FACTS[0].id,
    exempt_reason_text: null,
  },
  {
    id: 1902,
    staff_id: STAFF_A.id,
    employment_id: STAFF_A.employmentId,
    target_key: 'VS4_SYNTHETIC_INCOMPLETE',
    target_rule_version_code: 'VS4_RULE_1',
    status: 'INCOMPLETE',
    health_check_id: null,
    exempt_reason_text: null,
  },
  {
    id: 1903,
    staff_id: STAFF_A.id,
    employment_id: STAFF_A.employmentId,
    target_key: 'VS4_SYNTHETIC_EXEMPT',
    target_rule_version_code: 'VS4_RULE_1',
    status: 'EXEMPT',
    health_check_id: null,
    exempt_reason_text: 'VS4 synthetic exemption',
  },
] as const;

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const STAFF_API_SOURCE = readFileSync(
  resolve(REPO_ROOT, 'frontend/src/services/staffApi.ts'),
  'utf8',
);
const GENERATED_OPENAPI_SOURCE = readFileSync(
  resolve(REPO_ROOT, 'frontend/src/generated/sswcenter-api.ts'),
  'utf8',
);

let requests: RequestRecord[] = [];
let capabilities = { view: true, manage: true };
let healthMode: HealthMode = 'success';
let mutationMode: HealthMode = 'success';
let factsByStaff = new Map<number, JsonRecord[]>();
let requirementsByStaff = new Map<number, JsonRecord[]>();
let nextFactId = 2000;
let delayedHealthResolvers: Array<() => void> = [];
let delayedHealthStaffId: number | null = null;
let abortedHealthSignals: AbortSignal[] = [];
let delayedLogoutResolvers: Array<(response: Response) => void> = [];

function jsonResponse(body: JsonRecord, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://w1a-vs4.test');
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input), 'http://w1a-vs4.test');
}

function requestSignal(input: RequestInfo | URL, init?: RequestInit): AbortSignal | undefined {
  if (init?.signal) return init.signal;
  return input instanceof Request ? input.signal : undefined;
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

function staffDetail(staff: typeof STAFF_A | typeof STAFF_B): JsonRecord {
  return {
    id: staff.id,
    name: staff.name,
    birth_date: '1990-01-01',
    current_employment: {
      id: staff.employmentId,
      staff_id: staff.id,
      start_date: '2026-01-01',
      end_date: null,
      status: 'ACTIVE',
      row_version: 1,
    },
    employments: [
      {
        id: staff.employmentId,
        staff_id: staff.id,
        start_date: '2026-01-01',
        end_date: null,
        status: 'ACTIVE',
        row_version: 1,
      },
    ],
    positions: [],
    operational_roles: [],
    licenses: [],
    service_qualifications: [],
  };
}

function healthFailureResponse(mode: HealthMode): Response | null {
  if (mode === 'error') return jsonResponse({ error: { message: '검진 조회 오류' } }, 500);
  if (mode === 'forbidden') {
    return jsonResponse(
      {
        error: { code: 'FORBIDDEN', message: '검진 조회 권한이 없습니다.' },
        request_id: 'vs4-forbidden',
      },
      403,
    );
  }
  if (mode === 'conflict') {
    return jsonResponse(
      {
        error: { code: 'ROW_VERSION_CONFLICT', message: '최신 검진 상태를 다시 확인해주세요.' },
        request_id: 'vs4-conflict',
      },
      409,
    );
  }
  if (mode === 'invalid') {
    return jsonResponse(
      {
        error: { code: 'VALIDATION_ERROR', message: '입력값을 확인해주세요.' },
        field_errors: [{ field: 'check_date', message: '검진일을 입력해주세요.' }],
        request_id: 'vs4-invalid',
      },
      422,
    );
  }
  if (mode === 'empty') return jsonResponse({ items: [], total: 0 });
  return null;
}

function healthResponse(path: string, staffId: number): Response {
  const failure = healthFailureResponse(healthMode);
  if (failure) return failure;
  const isRequirement = path.includes('/health-check-requirements');
  const items = isRequirement
    ? requirementsByStaff.get(staffId) ?? []
    : factsByStaff.get(staffId) ?? [];
  return jsonResponse({ items, total: items.length });
}

function mutationResponse(path: string, method: string, body: JsonRecord): Response {
  const failure = healthFailureResponse(mutationMode);
  if (failure) return failure;
  const isRequirement = path.includes('/health-check-requirements');
  const isInvalidate = path.endsWith('/invalidate');
  const staffMatch = path.match(/\/staff\/(\d+)\//);
  const staffId = Number(staffMatch?.[1]);
  const idMatch = path.match(/\/(?:health-checks|health-check-requirements)\/(\d+)/);
  const rowId = idMatch ? Number(idMatch[1]) : null;
  const rows = isRequirement
    ? requirementsByStaff.get(staffId) ?? []
    : factsByStaff.get(staffId) ?? [];

  if (!isRequirement && method === 'POST' && !isInvalidate && rowId === null) {
    const created: JsonRecord = {
      check_date: String(body.check_date ?? ''),
      check_type_code: body.check_type_code ?? null,
      employment_id: body.employment_id ?? null,
      id: nextFactId++,
      result_note: body.result_note ?? null,
      row_version: 1,
      staff_id: staffId,
    };
    rows.push(created);
    factsByStaff.set(staffId, rows);
    return jsonResponse(created, 201);
  }

  const row = rows.find((candidate) => Number(candidate.id) === rowId);
  if (!row) return jsonResponse({ error: { code: 'NOT_FOUND' } }, 404);
  if (isInvalidate) {
    row.invalidated_at_utc = '2026-01-16T00:00:00Z';
  } else if (isRequirement) {
    row.exempt_reason_text = body.exempt_reason_text ?? null;
    row.health_check_id = body.health_check_id ?? null;
    row.status = body.status;
  } else {
    row.check_date = body.check_date ?? row.check_date;
    row.check_type_code = body.check_type_code ?? row.check_type_code;
    row.employment_id = body.employment_id ?? row.employment_id;
    row.result_note = body.result_note ?? row.result_note;
  }
  row.row_version = Number(row.row_version ?? 1) + 1;
  return jsonResponse(row);
}

function delayedHealthResponse(path: string, staffId: number, signal?: AbortSignal): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    delayedHealthResolvers.push(() => resolve(healthResponse(path, staffId)));
    delayedHealthStaffId = staffId;
    const onAbort = () => {
      if (signal) abortedHealthSignals.push(signal);
      reject(new DOMException('health request aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

function resolveDelayedHealthQueries(): void {
  const resolvers = delayedHealthResolvers;
  delayedHealthResolvers = [];
  delayedHealthStaffId = null;
  for (const resolve of resolvers) resolve();
}

function resolveDelayedLogout(): void {
  const resolvers = delayedLogoutResolvers;
  delayedLogoutResolvers = [];
  for (const resolve of resolvers) resolve(new Response(null, { status: 204 }));
}

function installFetchFixture(): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = requestUrl(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    requests.push({ body: parseBody(init?.body), method, path: url.pathname, signal: requestSignal(input, init) });

    if (url.pathname === '/api/v1/session-capabilities') {
      return jsonResponse({
        'staff.view': capabilities.view,
        'staff.manage': capabilities.manage,
        'staff.sensitive_identity.reveal': false,
      });
    }
    if (url.pathname === '/api/bootstrap/status') {
      return jsonResponse({ bootstrap_required: false });
    }
    if (url.pathname === '/api/auth/me') {
      return jsonResponse({
        account: { id: 1, display_name: 'W1A-VS4 합성 관리자', role_code: 'ADMIN' },
      });
    }
    if (url.pathname === '/api/auth/logout' && method === 'POST') {
      return new Promise<Response>((resolve) => delayedLogoutResolvers.push(resolve));
    }
    if (url.pathname === '/api/v1/catalogs/license-types') return jsonResponse({ items: [] });
    if (url.pathname === '/api/v1/catalogs/services') return jsonResponse({ items: [] });
    if (url.pathname === '/api/v1/staff' && method === 'GET') {
      return jsonResponse({
        items: [
          { id: STAFF_A.id, name: STAFF_A.name, current_employment: { id: STAFF_A.employmentId } },
          { id: STAFF_B.id, name: STAFF_B.name, current_employment: { id: STAFF_B.employmentId } },
        ],
        total: 4,
        page: Number(url.searchParams.get('page') ?? '1'),
        page_size: Number(url.searchParams.get('page_size') ?? '1'),
      });
    }
    const detailMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)$/);
    if (detailMatch && method === 'GET') {
      const staff = Number(detailMatch[1]) === STAFF_B.id ? STAFF_B : STAFF_A;
      return jsonResponse(staffDetail(staff));
    }
    if (url.pathname.match(/^\/api\/v1\/staff\/\d+\/licenses$/)) {
      return jsonResponse({ items: [], total: 0 });
    }
    if (url.pathname.match(/^\/api\/v1\/staff\/\d+\/service-qualifications$/)) {
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
    }
    const healthMatch = url.pathname.match(
      /^\/api\/v1\/staff\/(\d+)\/(health-checks|health-check-requirements)(?:\/\d+|\/invalidate)?$/,
    );
    if (healthMatch) {
      const staffId = Number(healthMatch[1]);
      if (method === 'GET') {
        if (healthMode === 'loading' && delayedHealthStaffId === staffId) {
          return delayedHealthResponse(url.pathname, staffId, requestSignal(input, init));
        }
        return healthResponse(url.pathname, staffId);
      }
      return mutationResponse(url.pathname, method, (parseBody(init?.body) as JsonRecord) ?? {});
    }
    if (url.pathname.includes('/onboarding-trainings') || url.pathname.includes('/periodic-trainings')) {
      return jsonResponse({ items: [] });
    }
    return jsonResponse({ detail: 'not_found' }, 404);
  });
}

function renderStaffPage(useBrowserHistory = false): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = useBrowserHistory ? (
    <BrowserRouter>
      <StaffPage />
    </BrowserRouter>
  ) : (
    <MemoryRouter>
      <StaffPage />
    </MemoryRouter>
  );
  render(<QueryClientProvider client={queryClient}>{router}</QueryClientProvider>);
  return queryClient;
}

function cachedHealthQueries(queryClient: QueryClient) {
  return queryClient.getQueryCache().getAll().filter((query) =>
    /health/i.test(JSON.stringify(query.queryKey)),
  );
}

function cachedHealthMutations(queryClient: QueryClient) {
  return queryClient.getMutationCache().getAll().filter((mutation) => {
    const serialized = JSON.stringify({
      key: mutation.options.mutationKey,
      variables: mutation.state.variables,
      data: mutation.state.data,
      error: mutation.state.error,
      status: mutation.state.status,
    });
    return /health/i.test(serialized);
  });
}

function queryCacheContains(queryClient: QueryClient, marker: string): boolean {
  return queryClient.getQueryCache().getAll().some((query) =>
    JSON.stringify({ key: query.queryKey, data: query.state.data, error: query.state.error }).includes(
      marker,
    ),
  );
}

async function selectStaff(staff: typeof STAFF_A | typeof STAFF_B, marker: string): Promise<void> {
  await waitFor(() =>
    expect(screen.queryAllByText(staff.name, { exact: true }).length > 0, marker).toBe(true),
  );
  fireEvent.click(screen.getAllByText(staff.name, { exact: true })[0] as HTMLElement);
  await waitFor(() =>
    expect(screen.queryByTestId('staff-detail-workspace'), marker).not.toBeNull(),
  );
}

async function openHealthTab(
  marker: string,
  staff: typeof STAFF_A | typeof STAFF_B = STAFF_A,
): Promise<QueryClient> {
  const queryClient = renderStaffPage();
  await selectStaff(staff, `${marker}_STAFF_DETAIL_MISSING`);
  const tab = screen.queryByRole('tab', { name: '검진' });
  expect(tab, marker).not.toBeNull();
  if (!tab) throw new Error(marker);
  fireEvent.click(tab);
  return queryClient;
}

beforeEach(() => {
  requests = [];
  capabilities = { view: true, manage: true };
  healthMode = 'success';
  mutationMode = 'success';
  factsByStaff = new Map([
    [STAFF_A.id, HEALTH_FACTS.map((fact) => ({ ...fact, row_version: 1 }))],
    [STAFF_B.id, []],
  ]);
  requirementsByStaff = new Map([
    [STAFF_A.id, HEALTH_REQUIREMENTS.map((requirement) => ({ ...requirement, row_version: 1 }))],
    [STAFF_B.id, []],
  ]);
  nextFactId = 2000;
  delayedHealthResolvers = [];
  delayedHealthStaffId = null;
  abortedHealthSignals = [];
  delayedLogoutResolvers = [];
  installFetchFixture();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('W1A-VS4 staff health-check frontend RED contract', () => {
  test('renders an independent health tab with two separated ledgers', async () => {
    await openHealthTab('W1A_VS4_UI_HEALTH_TAB_MISSING');
    expect(screen.getByRole('region', { name: '검진사실' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '대상별 상태' })).toBeInTheDocument();
  });

  test('requires generated named models and separated fact/requirement adapters', () => {
    expect(
      GENERATED_OPENAPI_SOURCE.includes('StaffHealthCheck') &&
        GENERATED_OPENAPI_SOURCE.includes('StaffHealthCheckRequirement'),
      'W1A_VS4_GENERATED_HEALTH_MODELS_MISSING',
    ).toBe(true);
    expect(
      STAFF_API_SOURCE.includes('/health-checks') &&
        STAFF_API_SOURCE.includes('/health-check-requirements') &&
        STAFF_API_SOURCE.includes('StaffHealthCheck') &&
        STAFF_API_SOURCE.includes('StaffHealthCheckRequirement'),
      'W1A_VS4_HEALTH_ADAPTER_ROUTES_MISSING',
    ).toBe(true);
  });

  test('renders same-date facts and observes loading, empty, error, and forbidden states', async () => {
    healthMode = 'loading';
    delayedHealthStaffId = STAFF_A.id;
    renderStaffPage();
    await selectStaff(STAFF_A, 'W1A_VS4_UI_FACT_STAFF_DETAIL_MISSING');
    const loadingTab = screen.queryByRole('tab', { name: '검진' });
    expect(loadingTab, 'W1A_VS4_UI_FACT_LEDGER_MISSING').not.toBeNull();
    if (!loadingTab) throw new Error('W1A_VS4_UI_FACT_LEDGER_MISSING');
    fireEvent.click(loadingTab);
    await waitFor(() =>
      expect(
        screen.queryByText(/불러오는 중|loading/i),
        'W1A_VS4_HEALTH_LOADING_STATE_MISSING',
      ).not.toBeNull(),
    );
    healthMode = 'success';
    resolveDelayedHealthQueries();
    await waitFor(() =>
      expect(screen.getAllByTestId('health-check-fact-row'), 'W1A_VS4_HEALTH_SUCCESS_STATE_MISSING').toHaveLength(2),
    );
    const facts = screen.getAllByTestId('health-check-fact-row');
    expect(facts, 'W1A_VS4_UI_SAME_DATE_FACTS_MISSING').toHaveLength(2);
    expect(screen.getAllByTestId('health-check-requirement-row')).toHaveLength(3);
    expect(screen.getByTestId('health-status-COMPLETE')).toHaveAttribute(
      'data-health-check-id',
      String(HEALTH_FACTS[0].id),
    );
    expect(screen.getByTestId('health-status-INCOMPLETE')).not.toHaveAttribute('data-health-check-id');
    expect(screen.getByTestId('health-status-EXEMPT')).toHaveTextContent('VS4 synthetic exemption');

    cleanup();
    healthMode = 'empty';
    await openHealthTab('W1A_VS4_HEALTH_EMPTY_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/검진사실이 없습니다|등록된 검진이 없습니다|empty/i),
        'W1A_VS4_HEALTH_EMPTY_STATE_MISSING',
      ).not.toBeNull(),
    );

    cleanup();
    healthMode = 'error';
    await openHealthTab('W1A_VS4_HEALTH_ERROR_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/검진.*오류|불러오지 못했습니다|error/i),
        'W1A_VS4_HEALTH_ERROR_STATE_MISSING',
      ).not.toBeNull(),
    );

    cleanup();
    healthMode = 'forbidden';
    await openHealthTab('W1A_VS4_HEALTH_FORBIDDEN_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/권한|접근|403|forbidden/i),
        'W1A_VS4_HEALTH_FORBIDDEN_STATE_MISSING',
      ).not.toBeNull(),
    );
  });

  test('separates VIEW from MANAGE writes and preserves 403/409/422 form state', async () => {
    capabilities = { view: true, manage: false };
    await openHealthTab('W1A_VS4_VIEW_HEALTH_TAB_MISSING');
    expect(screen.queryByTestId('health-check-fact-add'), 'W1A_VS4_VIEW_FACT_WRITE_VISIBLE').toBeNull();
    expect(screen.queryByRole('button', { name: /상태 저장/ }), 'W1A_VS4_VIEW_STATUS_WRITE_VISIBLE').toBeNull();
    expect(
      requests.some((request) => request.path.includes('/health-check')),
      'W1A_VS4_HEALTH_FETCH_NOT_OBSERVED',
    ).toBe(true);

    cleanup();
    capabilities = { view: true, manage: true };
    mutationMode = 'success';
    await openHealthTab('W1A_VS4_MANAGE_HEALTH_TAB_MISSING');
    fireEvent.click(screen.getByTestId('health-check-fact-add'));
    const createDate = screen.getByLabelText(/^검진일$/) as HTMLInputElement;
    const createEmployment = screen.getByRole('combobox', { name: /재직/ }) as HTMLSelectElement;
    const createType = screen.getByRole('combobox', { name: /검진 유형|검진유형/ }) as HTMLSelectElement;
    const createNote = screen.getByLabelText(/결과메모/) as HTMLTextAreaElement;
    fireEvent.change(createDate, { target: { value: '2026-01-16' } });
    fireEvent.change(createEmployment, { target: { value: String(STAFF_A.employmentId) } });
    fireEvent.change(createType, { target: { value: 'GENERAL' } });
    fireEvent.change(createNote, { target: { value: 'VS4 unit create' } });
    fireEvent.click(screen.getByRole('button', { name: /검진사실 저장/ }));
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'POST' && /\/health-checks$/.test(request.path),
        ),
        'W1A_VS4_FACT_CREATE_REQUEST_MISSING',
      ).toBe(true),
    );
    const createRequest = requests
      .filter((request) => request.method === 'POST' && /\/health-checks$/.test(request.path))
      .at(-1);
    expect(createRequest?.body, 'W1A_VS4_FACT_CREATE_PAYLOAD_MISMATCH').toEqual({
      check_date: '2026-01-16',
      check_type_code: 'GENERAL',
      employment_id: STAFF_A.employmentId,
      result_note: 'VS4 unit create',
    });
    await waitFor(() =>
      expect(screen.getAllByTestId('health-check-fact-row'), 'W1A_VS4_FACT_CREATE_REFETCH_MISSING').toHaveLength(3),
    );

    const factRow = screen
      .getAllByTestId('health-check-fact-row')
      .find((row) => row.textContent?.includes(HEALTH_FACTS[0].result_note));
    expect(factRow, 'W1A_VS4_FACT_UPDATE_TARGET_MISSING').not.toBeUndefined();
    if (!factRow) throw new Error('W1A_VS4_FACT_UPDATE_TARGET_MISSING');
    fireEvent.click(within(factRow).getByRole('button', { name: /검진사실 수정/ }));
    const updateNote = screen.getByLabelText(/결과메모/) as HTMLTextAreaElement;
    fireEvent.change(updateNote, { target: { value: 'VS4 unit update' } });
    fireEvent.click(screen.getByRole('button', { name: /검진사실 저장/ }));
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'PATCH' && /\/health-checks\/\d+$/.test(request.path),
        ),
        'W1A_VS4_FACT_UPDATE_REQUEST_MISSING',
      ).toBe(true),
    );
    const updateRequest = requests
      .filter((request) => request.method === 'PATCH' && /\/health-checks\/\d+$/.test(request.path))
      .at(-1);
    expect(updateRequest?.body, 'W1A_VS4_FACT_UPDATE_PAYLOAD_MISMATCH').toEqual({
      check_date: '2026-01-15',
      check_type_code: 'GENERAL',
      employment_id: STAFF_A.employmentId,
      result_note: 'VS4 unit update',
      expected_row_version: 1,
    });
    await waitFor(() =>
      expect(
        requests.filter((request) => request.method === 'GET' && /\/health-checks$/.test(request.path)).length,
        'W1A_VS4_FACT_UPDATE_REFETCH_MISSING',
      ).toBeGreaterThan(2),
    );
    const updatedFactRow = screen
      .getAllByTestId('health-check-fact-row')
      .find((row) => row.textContent?.includes('VS4 unit update'));
    expect(updatedFactRow, 'W1A_VS4_FACT_INVALIDATE_TARGET_MISSING').not.toBeUndefined();
    if (!updatedFactRow) throw new Error('W1A_VS4_FACT_INVALIDATE_TARGET_MISSING');
    fireEvent.click(within(updatedFactRow).getByRole('button', { name: /검진사실 무효화/ }));
    const factGetCountBeforeInvalidate = requests.filter(
      (request) => request.method === 'GET' && /\/health-checks$/.test(request.path),
    ).length;
    fireEvent.click(screen.getByRole('button', { name: /검진사실 무효화 확정/ }));
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'POST' && /\/health-checks\/\d+\/invalidate$/.test(request.path),
        ),
        'W1A_VS4_FACT_INVALIDATE_REQUEST_MISSING',
      ).toBe(true),
    );
    const invalidateRequest = requests
      .filter(
        (request) => request.method === 'POST' && /\/health-checks\/\d+\/invalidate$/.test(request.path),
      )
      .at(-1);
    expect(invalidateRequest?.body, 'W1A_VS4_FACT_INVALIDATE_PAYLOAD_MISMATCH').toEqual({
      expected_row_version: 2,
    });
    await waitFor(() =>
      expect(
        requests.filter((request) => request.method === 'GET' && /\/health-checks$/.test(request.path)).length,
        'W1A_VS4_FACT_INVALIDATE_REFETCH_MISSING',
      ).toBeGreaterThan(factGetCountBeforeInvalidate),
    );

    const completeRow = screen
      .getAllByTestId('health-check-requirement-row')
      .find((row) => row.textContent?.includes(HEALTH_REQUIREMENTS[0].target_key));
    expect(completeRow, 'W1A_VS4_REQUIREMENT_UPDATE_TARGET_MISSING').not.toBeUndefined();
    if (!completeRow) throw new Error('W1A_VS4_REQUIREMENT_UPDATE_TARGET_MISSING');
    fireEvent.change(within(completeRow).getByRole('combobox', { name: /상태/ }), {
      target: { value: 'INCOMPLETE' },
    });
    fireEvent.click(within(completeRow).getByRole('button', { name: /상태 저장/ }));
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'PATCH' && /\/health-check-requirements\/\d+$/.test(request.path),
        ),
        'W1A_VS4_REQUIREMENT_UPDATE_REQUEST_MISSING',
      ).toBe(true),
    );
    const incompleteRequest = requests
      .filter(
        (request) => request.method === 'PATCH' && /\/health-check-requirements\/\d+$/.test(request.path),
      )
      .at(-1);
    expect(incompleteRequest?.body, 'W1A_VS4_REQUIREMENT_INCOMPLETE_PAYLOAD_MISMATCH').toEqual({
      status: 'INCOMPLETE',
      health_check_id: null,
      exempt_reason_text: null,
      expected_row_version: 1,
    });
    await waitFor(() =>
      expect(
        requests.filter(
          (request) => request.method === 'GET' && /\/health-check-requirements$/.test(request.path),
        ).length,
        'W1A_VS4_REQUIREMENT_REFETCH_MISSING',
      ).toBeGreaterThan(2),
    );

    const exemptRow = screen
      .getAllByTestId('health-check-requirement-row')
      .find((row) => row.textContent?.includes(HEALTH_REQUIREMENTS[0].target_key));
    expect(exemptRow, 'W1A_VS4_REQUIREMENT_EXEMPT_TARGET_MISSING').not.toBeUndefined();
    if (!exemptRow) throw new Error('W1A_VS4_REQUIREMENT_EXEMPT_TARGET_MISSING');
    fireEvent.change(within(exemptRow).getByRole('combobox', { name: /상태/ }), {
      target: { value: 'EXEMPT' },
    });
    fireEvent.change(within(exemptRow).getByLabelText(/면제사유/), {
      target: { value: 'VS4 unit exemption' },
    });
    fireEvent.click(within(exemptRow).getByRole('button', { name: /상태 저장/ }));
    await waitFor(() =>
      expect(
        requests.filter(
          (request) => request.method === 'PATCH' && /\/health-check-requirements\/\d+$/.test(request.path),
        ).length,
        'W1A_VS4_REQUIREMENT_EXEMPT_REQUEST_MISSING',
      ).toBeGreaterThan(1),
    );
    const exemptRequest = requests
      .filter(
        (request) => request.method === 'PATCH' && /\/health-check-requirements\/\d+$/.test(request.path),
      )
      .at(-1);
    expect(exemptRequest?.body, 'W1A_VS4_REQUIREMENT_EXEMPT_PAYLOAD_MISMATCH').toEqual({
      status: 'EXEMPT',
      health_check_id: null,
      exempt_reason_text: 'VS4 unit exemption',
      expected_row_version: 2,
    });

    cleanup();
    mutationMode = 'conflict';
    const healthQueryClient = await openHealthTab('W1A_VS4_409_HEALTH_TAB_MISSING');
    fireEvent.click(screen.getByTestId('health-check-fact-add'));
    const conflictDate = screen.getByLabelText(/^검진일$/) as HTMLInputElement;
    const conflictEmployment = screen.getByRole('combobox', { name: /재직/ }) as HTMLSelectElement;
    fireEvent.change(conflictDate, { target: { value: '2026-02-01' } });
    fireEvent.change(conflictEmployment, { target: { value: String(STAFF_A.employmentId) } });
    fireEvent.click(screen.getByRole('button', { name: /검진사실 저장/ }));
    await waitFor(() =>
      expect(
        screen.getByRole('alert'),
        'W1A_VS4_409_STABLE_UI_MISSING',
      ).toBeInTheDocument(),
    );
    expect(conflictDate.value, 'W1A_VS4_409_INPUT_NOT_PRESERVED').toBe('2026-02-01');
    expect(conflictEmployment.value, 'W1A_VS4_409_SELECTION_NOT_PRESERVED').toBe(
      String(STAFF_A.employmentId),
    );

    mutationMode = 'invalid';
    fireEvent.click(screen.getByRole('button', { name: /검진사실 저장/ }));
    await waitFor(() =>
      expect(screen.getByText('검진일을 입력해주세요.'), 'W1A_VS4_422_FIELD_UI_MISSING').toBeInTheDocument(),
    );
    expect(conflictDate.value, 'W1A_VS4_422_INPUT_NOT_PRESERVED').toBe('2026-02-01');

    mutationMode = 'forbidden';
    fireEvent.click(screen.getByRole('button', { name: /검진사실 저장/ }));
    await waitFor(() =>
      expect(screen.getByRole('alert'), 'W1A_VS4_403_STABLE_UI_MISSING').toBeInTheDocument(),
    );
    expect(conflictDate.value, 'W1A_VS4_403_INPUT_NOT_PRESERVED').toBe('2026-02-01');
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(document.body.textContent ?? ''),
      'W1A_VS4_INTERNAL_ERROR_LEAKED_IN_DOM',
    ).toBe(true);
    expect(
      cachedHealthMutations(healthQueryClient).length,
      'W1A_VS4_FAILED_HEALTH_MUTATION_CACHE_RETAINED',
    ).toBe(0);
  });

  test('aborts stale A queries on B, preserves list context, and purges session/cache on logout', async () => {
    healthMode = 'loading';
    delayedHealthStaffId = STAFF_A.id;
    const staffQueryClient = renderStaffPage(true);
    await selectStaff(STAFF_A, 'W1A_VS4_STALE_A_DETAIL_MISSING');
    const delayedTab = screen.queryByRole('tab', { name: '검진' });
    expect(delayedTab, 'W1A_VS4_STALE_A_HEALTH_TAB_MISSING').not.toBeNull();
    if (!delayedTab) throw new Error('W1A_VS4_STALE_A_HEALTH_TAB_MISSING');
    fireEvent.click(delayedTab);
    await waitFor(() =>
      expect(screen.queryByText(/불러오는 중|loading/i), 'W1A_VS4_STALE_A_LOADING_MISSING').not.toBeNull(),
    );
    healthMode = 'success';
    await selectStaff(STAFF_B, 'W1A_VS4_STALE_B_SELECTION_MISSING');
    resolveDelayedHealthQueries();
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'GET' && request.path.startsWith(`/api/v1/staff/${STAFF_B.id}/health-`),
        ),
        'W1A_VS4_STALE_B_HEALTH_FETCH_MISSING',
      ).toBe(true),
    );
    expect(
      abortedHealthSignals.some((signal) => signal.aborted),
      'W1A_VS4_STALE_A_ABORT_SIGNAL_MISSING',
    ).toBe(true);
    expect(screen.queryByText(HEALTH_FACTS[0].result_note)).toBeNull();
    expect(screen.queryByText(HEALTH_REQUIREMENTS[0].target_key)).toBeNull();
    expect(
      cachedHealthQueries(staffQueryClient).some((query) =>
        JSON.stringify(query.queryKey).includes(String(STAFF_A.id)),
      ),
      'W1A_VS4_QUERY_CACHE_A_HEALTH_RETAINED',
    ).toBe(false);
    expect(
      queryCacheContains(staffQueryClient, HEALTH_FACTS[0].result_note) ||
        queryCacheContains(staffQueryClient, HEALTH_REQUIREMENTS[0].target_key),
      'W1A_VS4_QUERY_CACHE_A_DATA_RETAINED',
    ).toBe(false);
    expect(
      cachedHealthMutations(staffQueryClient).length,
      'W1A_VS4_STALE_HEALTH_MUTATION_CACHE_RETAINED',
    ).toBe(0);

    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
    await waitFor(() => {
      expect(
        cachedHealthQueries(staffQueryClient).some((query) =>
          JSON.stringify(query.queryKey).includes(String(STAFF_A.id)),
        ),
        'W1A_VS4_SESSION_QUERY_CACHE_A_RETAINED',
      ).toBe(false);
      expect(
        queryCacheContains(staffQueryClient, HEALTH_FACTS[0].result_note) ||
          queryCacheContains(staffQueryClient, HEALTH_REQUIREMENTS[0].target_key),
        'W1A_VS4_SESSION_QUERY_CACHE_A_DATA_RETAINED',
      ).toBe(false);
      expect(
        cachedHealthMutations(staffQueryClient).length,
        'W1A_VS4_SESSION_MUTATION_CACHE_HEALTH_RETAINED',
      ).toBe(0);
    });

    cleanup();
    window.history.replaceState({}, '', '/staff?context=before');
    window.history.pushState({}, '', '/staff?context=detail');
    healthMode = 'success';
    renderStaffPage(true);
    await selectStaff(STAFF_A, 'W1A_VS4_CONTEXT_STAFF_DETAIL_MISSING');
    const tab = screen.queryByRole('tab', { name: '검진' });
    expect(tab, 'W1A_VS4_CONTEXT_HEALTH_TAB_MISSING').not.toBeNull();
    if (!tab) throw new Error('W1A_VS4_CONTEXT_HEALTH_TAB_MISSING');
    fireEvent.click(tab);
    const search = screen.getByLabelText(/^직원 검색$/) as HTMLInputElement;
    const sort = screen.getByLabelText(/정렬/) as HTMLSelectElement;
    const scroll = screen.getByTestId('staff-list-scroll') as HTMLElement;
    fireEvent.change(search, { target: { value: 'W1A-VS4' } });
    fireEvent.change(sort, { target: { value: sort.options[1]?.value ?? sort.value } });
    scroll.scrollTop = 32;
    fireEvent.scroll(scroll);
    expect(scroll.scrollTop > 0, 'W1A_VS4_CONTEXT_SCROLL_NOT_RETAINED').toBe(true);
    const retainedSearch = search.value;
    const retainedSort = sort.value;
    const retainedScrollTop = scroll.scrollTop;
    window.history.back();
    await waitFor(() =>
      expect(window.location.search.includes('context=before'), 'W1A_VS4_CONTEXT_BACK_NOT_PERFORMED').toBe(true),
    );
    expect((screen.getByLabelText(/^직원 검색$/) as HTMLInputElement).value).toBe(retainedSearch);
    expect((screen.getByLabelText(/정렬/) as HTMLSelectElement).value).toBe(retainedSort);
    expect((screen.getByTestId('staff-list-scroll') as HTMLElement).scrollTop).toBe(retainedScrollTop);
    expect(screen.getByRole('tab', { name: '검진' })).toHaveAttribute('aria-selected', 'true');
    expect(
      /자동대상|D-day|업무카드|첨부|attachment|file_id|evidence_id|task_id/i.test(
        document.body.textContent ?? '',
      ),
      'W1A_VS4_ABS_FORBIDDEN_HEALTH_UI_EXPOSED',
    ).toBe(false);

    cleanup();
    window.history.replaceState({}, '', '/staff');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTestId('app-shell'), 'W1A_VS4_SESSION_APP_SHELL_MISSING').toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('sidebar-logout'));
    await waitFor(() =>
      expect(
        requests.some((request) => request.method === 'POST' && request.path === '/api/auth/logout'),
        'W1A_VS4_LOGOUT_REQUEST_MISSING',
      ).toBe(true),
    );
    expect(screen.getByTestId('auth-loading'), 'W1A_VS4_LOGOUT_LOADING_MISSING').toBeInTheDocument();
    expect(document.body.textContent).not.toContain(HEALTH_FACTS[0].result_note);
    resolveDelayedLogout();
    await waitFor(() =>
      expect(screen.getByTestId('login-form'), 'W1A_VS4_LOGOUT_SESSION_NOT_CLEARED').toBeInTheDocument(),
    );
    expect(screen.queryByTestId('auth-loading')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(HEALTH_FACTS[0].result_note);
  });
});
