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
type ConsultationMode = 'success' | 'loading' | 'empty' | 'error' | 'forbidden';
type MutationMode = 'success' | 'forbidden' | 'conflict' | 'invalid';

type RequestRecord = {
  body: unknown;
  method: string;
  path: string;
  signal: AbortSignal | undefined;
};

type StaffFixture = {
  employmentId: number;
  id: number;
  name: string;
};

type DeferredResponse = {
  promise: Promise<Response>;
  resolve: (response: Response) => void;
  signal: AbortSignal | undefined;
};

const STAFF_A: StaffFixture = {
  id: 91,
  name: 'W1A-VS5 합성 직원 A',
  employmentId: 901,
};
const STAFF_B: StaffFixture = {
  id: 92,
  name: 'W1A-VS5 합성 직원 B',
  employmentId: 902,
};

const CONSULTATIONS = [
  {
    id: 2101,
    calendar_year: 2026,
    quarter_no: 1,
    status: 'COMPLETE' as const,
    counseling_date: '2026-01-15',
    content: 'VS5 synthetic complete',
    incomplete_reason_text: null,
    exempt_reason_text: null,
  },
  {
    id: 2102,
    calendar_year: 2026,
    quarter_no: 2,
    status: 'INCOMPLETE' as const,
    counseling_date: null,
    content: null,
    incomplete_reason_text: 'VS5 synthetic incomplete',
    exempt_reason_text: null,
  },
  {
    id: 2103,
    calendar_year: 2026,
    quarter_no: 3,
    status: 'EXEMPT' as const,
    counseling_date: null,
    content: null,
    incomplete_reason_text: null,
    exempt_reason_text: 'VS5 synthetic exempt',
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
let consultationMode: ConsultationMode = 'success';
let mutationMode: MutationMode = 'success';
let consultationsByStaff = new Map<number, JsonRecord[]>();
let nextConsultationId = 2200;
let delayedConsultationQueries: DeferredResponse[] = [];
let delayedLogoutResolvers: Array<(response: Response) => void> = [];
let abortedConsultationSignals: AbortSignal[] = [];

function jsonResponse(body: JsonRecord, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://w1a-vs5.test');
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input), 'http://w1a-vs5.test');
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

function bodyRecord(body: unknown): JsonRecord {
  return body && typeof body === 'object' && !Array.isArray(body)
    ? (body as JsonRecord)
    : {};
}

function staffDetail(staff: StaffFixture): JsonRecord {
  const staffNo = staff === STAFF_A ? 'VS5-A-STAFF' : 'VS5-B-STAFF';
  return {
    id: staff.id,
    name: staff.name,
    display_name: staff.name,
    birth_date: '1990-01-01',
    sex_code: 'MALE',
    row_version: 1,
    current_employment: {
      id: staff.employmentId,
      staff_id: staff.id,
      staff_no: staffNo,
      start_date: '2026-01-01',
      end_date: null,
      status: 'ACTIVE',
      row_version: 1,
    },
    employments: [
      {
        id: staff.employmentId,
        staff_id: staff.id,
        staff_no: staffNo,
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

function consultationRow(
  staff: StaffFixture,
  source: (typeof CONSULTATIONS)[number],
  rowVersion = 1,
): JsonRecord {
  return {
    id: source.id,
    staff_id: staff.id,
    calendar_year: source.calendar_year,
    quarter_no: source.quarter_no,
    status: source.status,
    counseling_date: source.counseling_date,
    content: source.content,
    incomplete_reason_text: source.incomplete_reason_text,
    exempt_reason_text: source.exempt_reason_text,
    invalidated_at_utc: null,
    replacement_staff_quarterly_consultation_id: null,
    created_by_account_id: 1,
    created_at_utc: '2026-01-01T00:00:00Z',
    updated_by_account_id: 1,
    updated_at_utc: '2026-01-01T00:00:00Z',
    row_version: rowVersion,
  };
}

function consultationFailure(mode: ConsultationMode | MutationMode): Response | null {
  if (mode === 'error') {
    return jsonResponse({ error: { code: 'CONSULTATION_READ_FAILED', message: '분기상담 조회 오류' } }, 500);
  }
  if (mode === 'forbidden') {
    return jsonResponse(
      { error: { code: 'FORBIDDEN', message: '분기상담 권한이 없습니다.' }, request_id: 'vs5-forbidden' },
      403,
    );
  }
  if (mode === 'conflict') {
    return jsonResponse(
      { error: { code: 'ROW_VERSION_CONFLICT', message: '최신 분기상담 상태를 다시 확인해주세요.' }, request_id: 'vs5-conflict' },
      409,
    );
  }
  if (mode === 'invalid') {
    return jsonResponse(
      {
        error: { code: 'VALIDATION_ERROR', message: '입력값을 확인해주세요.' },
        field_errors: [{ field: 'content', message: '처리내용을 입력해주세요.' }],
        request_id: 'vs5-invalid',
      },
      422,
    );
  }
  if (mode === 'empty') return jsonResponse({ items: [], total: 0 });
  return null;
}

function consultationResponse(staffId: number): Response {
  const failure = consultationFailure(consultationMode);
  if (failure) return failure;
  const items = (consultationsByStaff.get(staffId) ?? []).filter(
    (item) => item.invalidated_at_utc == null,
  );
  return jsonResponse({ items, total: items.length });
}

function createOrUpdateConsultation(
  path: string,
  method: string,
  staffId: number,
  body: JsonRecord,
): Response {
  const failure = consultationFailure(mutationMode);
  if (failure) return failure;
  const rows = consultationsByStaff.get(staffId) ?? [];
  const invalidating = path.endsWith('/invalidate');
  const replacing = path.endsWith('/replace');
  const idMatch = path.match(/quarterly-consultations\/(\d+)/);
  const id = idMatch ? Number(idMatch[1]) : null;

  if (method === 'POST' && id === null) {
    const created: JsonRecord = {
      id: nextConsultationId++,
      staff_id: staffId,
      calendar_year: body.calendar_year,
      quarter_no: body.quarter_no,
      status: body.status,
      counseling_date: body.counseling_date ?? null,
      content: body.content ?? null,
      incomplete_reason_text: body.incomplete_reason_text ?? null,
      exempt_reason_text: body.exempt_reason_text ?? null,
      invalidated_at_utc: null,
      replacement_staff_quarterly_consultation_id: null,
      row_version: 1,
    };
    rows.push(created);
    consultationsByStaff.set(staffId, rows);
    return jsonResponse(created, 201);
  }

  const current = rows.find((row) => Number(row.id) === id);
  if (!current) return jsonResponse({ error: { code: 'NOT_FOUND', message: '분기상담을 찾을 수 없습니다.' } }, 404);
  if (invalidating || replacing) {
    current.invalidated_at_utc = '2026-04-16T00:00:00Z';
    current.row_version = Number(current.row_version ?? 1) + 1;
    const replacement: JsonRecord = {
      ...current,
      id: nextConsultationId++,
      invalidated_at_utc: null,
      replacement_staff_quarterly_consultation_id: null,
      row_version: 1,
      status: body.status ?? current.status,
      counseling_date: body.counseling_date ?? null,
      content: body.content ?? null,
      incomplete_reason_text: body.incomplete_reason_text ?? null,
      exempt_reason_text: body.exempt_reason_text ?? null,
    };
    current.replacement_staff_quarterly_consultation_id = replacement.id;
    rows.push(replacement);
    return jsonResponse({ ...current, replacement_staff_quarterly_consultation_id: replacement.id });
  }

  current.status = body.status ?? current.status;
  current.counseling_date = body.counseling_date ?? null;
  current.content = body.content ?? null;
  current.incomplete_reason_text = body.incomplete_reason_text ?? null;
  current.exempt_reason_text = body.exempt_reason_text ?? null;
  current.row_version = Number(current.row_version ?? 1) + 1;
  return jsonResponse(current);
}

function makeDeferredResponse(signal: AbortSignal | undefined): DeferredResponse {
  let resolveResponse: (response: Response) => void = () => undefined;
  const promise = new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  });
  const deferred = { promise, resolve: resolveResponse, signal };
  const onAbort = () => {
    abortedConsultationSignals.push(signal as AbortSignal);
  };
  signal?.addEventListener('abort', onAbort, { once: true });
  delayedConsultationQueries.push(deferred);
  return deferred;
}

function resolveDelayedConsultationQueries(): void {
  const deferred = delayedConsultationQueries;
  delayedConsultationQueries = [];
  for (const item of deferred) item.resolve(consultationResponse(STAFF_A.id));
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
    const signal = requestSignal(input, init);
    const path = url.pathname;
    requests.push({ body: parseBody(init?.body), method, path, signal });

    if (path === '/api/v1/session-capabilities') {
      return jsonResponse({
        'staff.view': capabilities.view,
        'staff.manage': capabilities.manage,
        'staff.sensitive_identity.reveal': false,
      });
    }
    if (path === '/api/bootstrap/status') return jsonResponse({ bootstrap_required: false });
    if (path === '/api/auth/me') {
      return jsonResponse({ account: { id: 1, display_name: 'W1A-VS5 합성 관리자', role_code: 'ADMIN' } });
    }
    if (path === '/api/auth/logout' && method === 'POST') {
      return new Promise<Response>((resolve) => delayedLogoutResolvers.push(resolve));
    }
    if (path === '/api/v1/catalogs/license-types' || path === '/api/v1/catalogs/services') {
      return jsonResponse({ items: [] });
    }
    if (path === '/api/v1/staff/training-courses') return jsonResponse({ items: [] });
    if (path === '/api/v1/staff' && method === 'GET') {
      const search = url.searchParams.get('search')?.trim() ?? '';
      const page = Number(url.searchParams.get('page') ?? '1');
      const all = [STAFF_A, STAFF_B];
      const filtered = search ? all.filter((staff) => staff.name.includes(search)) : all;
      const items = search && filtered.length === 2 ? [filtered[page - 1] ?? filtered[0]] : filtered;
      return jsonResponse({
        items: items.map((staff) => ({
          id: staff.id,
          name: staff.name,
          display_name: staff.name,
          current_employment: { id: staff.employmentId, staff_no: staff === STAFF_A ? 'VS5-A-STAFF' : 'VS5-B-STAFF' },
        })),
        total: filtered.length,
        page,
        page_size: 1,
      });
    }
    const detailMatch = path.match(/^\/api\/v1\/staff\/(\d+)$/);
    if (detailMatch && method === 'GET') {
      return jsonResponse(Number(detailMatch[1]) === STAFF_B.id ? staffDetail(STAFF_B) : staffDetail(STAFF_A));
    }
    if (path.match(/^\/api\/v1\/staff\/\d+\/(licenses|service-qualifications)$/)) {
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
    }
    if (path.includes('/onboarding-trainings') || path.includes('/periodic-trainings')) {
      return jsonResponse({ items: [], total: 0 });
    }

    const consultationMatch = path.match(
      /^\/api\/v1\/staff\/(\d+)\/quarterly-consultations(?:\/(\d+)(?:\/(invalidate|replace))?)?$/,
    );
    if (consultationMatch) {
      const staffId = Number(consultationMatch[1]);
      if (method === 'GET') {
        if (consultationMode === 'loading') {
          return makeDeferredResponse(signal).promise;
        }
        return consultationResponse(staffId);
      }
      return createOrUpdateConsultation(path, method, staffId, bodyRecord(parseBody(init?.body)));
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

async function selectStaff(staff: StaffFixture, marker: string): Promise<void> {
  await waitFor(() =>
    expect(screen.queryAllByText(staff.name, { exact: true }).length > 0, marker).toBe(true),
  );
  fireEvent.click(screen.getAllByText(staff.name, { exact: true })[0] as HTMLElement);
  await waitFor(() => expect(screen.queryByTestId('staff-detail-workspace'), marker).not.toBeNull());
}

async function openQuarterlyTab(
  marker: string,
  staff: StaffFixture = STAFF_A,
  useBrowserHistory = false,
): Promise<QueryClient> {
  const queryClient = renderStaffPage(useBrowserHistory);
  await selectStaff(staff, `${marker}_STAFF_DETAIL_MISSING`);
  const tab = screen.queryByRole('tab', { name: '분기상담' });
  expect(tab, marker).not.toBeNull();
  if (!tab) throw new Error(marker);
  fireEvent.click(tab);
  return queryClient;
}

function consultationQueries(queryClient: QueryClient) {
  return queryClient.getQueryCache().getAll().filter((query) =>
    JSON.stringify(query.queryKey).includes('quarterly-consultation'),
  );
}

function consultationMutations(queryClient: QueryClient) {
  return queryClient.getMutationCache().getAll().filter((mutation) =>
    JSON.stringify({
      key: mutation.options.mutationKey,
      variables: mutation.state.variables,
      data: mutation.state.data,
      error: mutation.state.error,
    }).includes('quarterly'),
  );
}

beforeEach(() => {
  requests = [];
  capabilities = { view: true, manage: true };
  consultationMode = 'success';
  mutationMode = 'success';
  consultationsByStaff = new Map([
    [STAFF_A.id, CONSULTATIONS.map((consultation) => consultationRow(STAFF_A, consultation))],
    [STAFF_B.id, []],
  ]);
  nextConsultationId = 2200;
  delayedConsultationQueries = [];
  delayedLogoutResolvers = [];
  abortedConsultationSignals = [];
  installFetchFixture();
});

afterEach(() => {
  resolveDelayedConsultationQueries();
  resolveDelayedLogout();
  vi.restoreAllMocks();
});

describe('W1A-VS5 staff quarterly-consultation frontend RED contract', () => {
  test('renders an independent tab with exact three-state conditional fields', async () => {
    await openQuarterlyTab('W1A_VS5_UI_QUARTERLY_CONSULTATION_TAB_MISSING');
    const panel = screen.getByTestId('staff-quarterly-consultation-panel');
    expect(panel, 'W1A_VS5_UI_QUARTERLY_CONSULTATION_PANEL_MISSING').toBeInTheDocument();
    const rows = within(panel).getAllByTestId('quarterly-consultation-row');
    expect(rows, 'W1A_VS5_UI_QUARTERLY_CONSULTATION_ROWS_MISSING').toHaveLength(3);

    const complete = rows.find((row) => row.getAttribute('data-status') === 'COMPLETE');
    const incomplete = rows.find((row) => row.getAttribute('data-status') === 'INCOMPLETE');
    const exempt = rows.find((row) => row.getAttribute('data-status') === 'EXEMPT');
    expect(complete, 'W1A_VS5_UI_COMPLETE_ROW_MISSING').toBeDefined();
    expect(incomplete, 'W1A_VS5_UI_INCOMPLETE_ROW_MISSING').toBeDefined();
    expect(exempt, 'W1A_VS5_UI_EXEMPT_ROW_MISSING').toBeDefined();
    if (!complete || !incomplete || !exempt) return;

    expect(within(complete).getByText('2026')).toBeInTheDocument();
    expect(within(complete).getByText('1분기')).toBeInTheDocument();
    expect(within(complete).getByLabelText('상담일')).toBeVisible();
    expect(within(complete).getByLabelText('처리내용')).toBeVisible();
    expect(within(complete).queryByLabelText('미완료 사유')).toBeNull();
    expect(within(complete).queryByLabelText('면제 사유')).toBeNull();

    expect(within(incomplete).getByText('2분기')).toBeInTheDocument();
    expect(within(incomplete).getByLabelText('미완료 사유')).toBeVisible();
    expect(within(incomplete).queryByLabelText('상담일')).toBeNull();
    expect(within(incomplete).queryByLabelText('처리내용')).toBeNull();
    expect(within(incomplete).queryByLabelText('면제 사유')).toBeNull();

    expect(within(exempt).getByText('3분기')).toBeInTheDocument();
    expect(within(exempt).getByLabelText('면제 사유')).toBeVisible();
    expect(within(exempt).queryByLabelText('상담일')).toBeNull();
    expect(within(exempt).queryByLabelText('처리내용')).toBeNull();
    expect(within(exempt).queryByLabelText('미완료 사유')).toBeNull();
  });

  test('requires named generated models and a staff-scoped quarterly adapter', () => {
    const modelNames = [
      'QuarterlyConsultationStatus',
      'StaffQuarterlyConsultationCreateRequest',
      'StaffQuarterlyConsultationUpdateRequest',
      'StaffQuarterlyConsultationReplaceRequest',
      'StaffQuarterlyConsultationResponse',
      'StaffQuarterlyConsultationListResponse',
    ];
    expect(
      modelNames.every((name) => GENERATED_OPENAPI_SOURCE.includes(name)),
      'W1A_VS5_GENERATED_QUARTERLY_MODELS_MISSING',
    ).toBe(true);
    expect(
      STAFF_API_SOURCE.includes('/quarterly-consultations') &&
        modelNames.slice(1).every((name) => STAFF_API_SOURCE.includes(name)),
      'W1A_VS5_QUARTERLY_ADAPTER_ROUTES_MISSING',
    ).toBe(true);
  });

  test('renders loading, empty, error, and forbidden consultation states', async () => {
    consultationMode = 'loading';
    await openQuarterlyTab('W1A_VS5_LOADING_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/불러오는 중|loading/i),
        'W1A_VS5_LOADING_STATE_MISSING',
      ).not.toBeNull(),
    );
    consultationMode = 'success';
    resolveDelayedConsultationQueries();
    await waitFor(() =>
      expect(screen.getAllByTestId('quarterly-consultation-row'), 'W1A_VS5_LOADING_SUCCESS_MISSING').toHaveLength(3),
    );

    cleanup();
    consultationMode = 'empty';
    await openQuarterlyTab('W1A_VS5_EMPTY_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/분기상담.*없|등록된.*없|empty/i),
        'W1A_VS5_EMPTY_STATE_MISSING',
      ).not.toBeNull(),
    );

    cleanup();
    consultationMode = 'error';
    await openQuarterlyTab('W1A_VS5_ERROR_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/분기상담.*오류|불러오지 못했|error/i),
        'W1A_VS5_ERROR_STATE_MISSING',
      ).not.toBeNull(),
    );

    cleanup();
    consultationMode = 'forbidden';
    await openQuarterlyTab('W1A_VS5_FORBIDDEN_TAB_MISSING');
    await waitFor(() =>
      expect(
        screen.queryByText(/권한|접근|403|forbidden/i),
        'W1A_VS5_FORBIDDEN_STATE_MISSING',
      ).not.toBeNull(),
    );
  });

  test('separates VIEW and MANAGE, clears conditional fields, and refetches after writes', async () => {
    capabilities = { view: true, manage: false };
    await openQuarterlyTab('W1A_VS5_VIEW_QUARTERLY_TAB_MISSING');
    expect(screen.queryByRole('button', { name: /분기상담.*(추가|등록)/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /저장|무효화|대체/ })).toBeNull();
    expect(
      requests.some((request) => request.method === 'GET' && request.path.includes('/quarterly-consultations')),
      'W1A_VS5_QUARTERLY_FETCH_NOT_OBSERVED',
    ).toBe(true);

    cleanup();
    capabilities = { view: true, manage: true };
    const manageQueryClient = await openQuarterlyTab('W1A_VS5_MANAGE_QUARTERLY_TAB_MISSING');
    const add = screen.getByRole('button', { name: /분기상담.*(추가|등록)/ });
    fireEvent.click(add);
    fireEvent.change(screen.getByLabelText('연도'), { target: { value: '2026' } });
    fireEvent.change(screen.getByLabelText('분기'), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText('상태'), { target: { value: 'COMPLETE' } });
    fireEvent.change(screen.getByLabelText('상담일'), { target: { value: '2026-04-15' } });
    fireEvent.change(screen.getByLabelText('처리내용'), { target: { value: 'VS5 unit create' } });
    fireEvent.click(screen.getByRole('button', { name: /분기상담 저장|저장/ }));
    await waitFor(() =>
      expect(
        requests.some((request) => request.method === 'POST' && /quarterly-consultations$/.test(request.path)),
        'W1A_VS5_CREATE_REQUEST_MISSING',
      ).toBe(true),
    );
    const createRequest = requests
      .filter((request) => request.method === 'POST' && /quarterly-consultations$/.test(request.path))
      .at(-1);
    expect(createRequest?.body, 'W1A_VS5_CREATE_PAYLOAD_MISMATCH').toEqual({
      calendar_year: 2026,
      quarter_no: 4,
      status: 'COMPLETE',
      counseling_date: '2026-04-15',
      content: 'VS5 unit create',
      incomplete_reason_text: null,
      exempt_reason_text: null,
    });
    await waitFor(() =>
      expect(
        requests.filter((request) => request.method === 'GET' && /quarterly-consultations$/.test(request.path)).length,
        'W1A_VS5_CREATE_REFETCH_MISSING',
      ).toBeGreaterThan(1),
    );

    const completeRow = screen
      .getAllByTestId('quarterly-consultation-row')
      .find((row) => row.getAttribute('data-status') === 'COMPLETE');
    expect(completeRow, 'W1A_VS5_UPDATE_TARGET_MISSING').toBeDefined();
    if (!completeRow) return;
    fireEvent.click(within(completeRow).getByRole('button', { name: /수정/ }));
    fireEvent.change(within(completeRow).getByRole('combobox', { name: '상태' }), {
      target: { value: 'INCOMPLETE' },
    });
    fireEvent.change(within(completeRow).getByLabelText('미완료 사유'), {
      target: { value: 'VS5 unit incomplete' },
    });
    expect(within(completeRow).queryByLabelText('상담일')).toBeNull();
    expect(within(completeRow).queryByLabelText('처리내용')).toBeNull();
    fireEvent.click(within(completeRow).getByRole('button', { name: /저장/ }));
    await waitFor(() =>
      expect(
        requests.some((request) => request.method === 'PATCH' && /quarterly-consultations\/\d+$/.test(request.path)),
        'W1A_VS5_UPDATE_REQUEST_MISSING',
      ).toBe(true),
    );
    const updateRequest = requests
      .filter((request) => request.method === 'PATCH' && /quarterly-consultations\/\d+$/.test(request.path))
      .at(-1);
    expect(updateRequest?.body, 'W1A_VS5_INCOMPLETE_PAYLOAD_MISMATCH').toEqual({
      status: 'INCOMPLETE',
      counseling_date: null,
      content: null,
      incomplete_reason_text: 'VS5 unit incomplete',
      exempt_reason_text: null,
      expected_row_version: 1,
    });
    await waitFor(() =>
      expect(
        requests.filter((request) => request.method === 'GET' && /quarterly-consultations$/.test(request.path)).length,
        'W1A_VS5_UPDATE_REFETCH_MISSING',
      ).toBeGreaterThan(2),
    );
    expect(
      consultationMutations(manageQueryClient),
      'W1A_VS5_SUCCESS_MUTATION_CACHE_RETAINED',
    ).toHaveLength(0);
  });

  test('preserves error form state and isolates stale A data, cache, session, and forbidden surfaces', async () => {
    consultationMode = 'loading';
    const queryClient = await openQuarterlyTab('W1A_VS5_STALE_A_TAB_MISSING', STAFF_A, true);
    await waitFor(() => expect(screen.queryByText(/불러오는 중|loading/i)).not.toBeNull());
    consultationMode = 'success';
    await selectStaff(STAFF_B, 'W1A_VS5_STALE_B_SELECTION_MISSING');
    resolveDelayedConsultationQueries();
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'GET' && request.path === `/api/v1/staff/${STAFF_B.id}/quarterly-consultations`,
        ),
        'W1A_VS5_STALE_B_FETCH_MISSING',
      ).toBe(true),
    );
    expect(abortedConsultationSignals.some((signal) => signal.aborted), 'W1A_VS5_STALE_A_ABORT_MISSING').toBe(true);
    expect(document.body.textContent).not.toContain('VS5 synthetic complete');
    expect(
      consultationQueries(queryClient).some((query) => JSON.stringify(query.queryKey).includes(String(STAFF_A.id))),
      'W1A_VS5_STALE_A_QUERY_CACHE_RETAINED',
    ).toBe(false);
    expect(consultationMutations(queryClient), 'W1A_VS5_STALE_MUTATION_CACHE_RETAINED').toHaveLength(0);

    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
    await waitFor(() =>
      expect(
        consultationQueries(queryClient).some((query) => JSON.stringify(query.queryKey).includes(String(STAFF_B.id))),
        'W1A_VS5_SESSION_QUERY_CACHE_RETAINED',
      ).toBe(false),
    );
    expect(
      !/(?:sqlalchemy|constraint|dsn|select|postgres|password)/i.test(document.body.textContent ?? ''),
      'W1A_VS5_INTERNAL_ERROR_OR_SECRET_LEAKED',
    ).toBe(true);
    expect(
      /교체상담|실제급여제공|Day\s*14|Day\s*15|file|evidence|attachment|care-change/i.test(
        document.body.textContent ?? '',
      ),
      'W1A_VS5_FORBIDDEN_SURFACE_EXPOSED',
    ).toBe(false);

    cleanup();
    consultationMode = 'success';
    mutationMode = 'conflict';
    const browserQueryClient = await openQuarterlyTab('W1A_VS5_409_TAB_MISSING');
    const add = screen.getByRole('button', { name: /분기상담.*(추가|등록)/ });
    fireEvent.click(add);
    const date = screen.getByLabelText('상담일') as HTMLInputElement;
    fireEvent.change(date, { target: { value: '2026-04-15' } });
    fireEvent.click(screen.getByRole('button', { name: /저장/ }));
    await waitFor(() => expect(screen.getByRole('alert'), 'W1A_VS5_409_ALERT_MISSING').toBeInTheDocument());
    expect(date.value, 'W1A_VS5_409_INPUT_NOT_PRESERVED').toBe('2026-04-15');

    mutationMode = 'invalid';
    fireEvent.click(screen.getByRole('button', { name: /저장/ }));
    await waitFor(() =>
      expect(screen.getByText('처리내용을 입력해주세요.'), 'W1A_VS5_422_FIELD_UI_MISSING').toBeInTheDocument(),
    );
    expect(date.value, 'W1A_VS5_422_INPUT_NOT_PRESERVED').toBe('2026-04-15');

    mutationMode = 'forbidden';
    fireEvent.click(screen.getByRole('button', { name: /저장/ }));
    await waitFor(() => expect(screen.getByRole('alert'), 'W1A_VS5_403_ALERT_MISSING').toBeInTheDocument());
    expect(date.value, 'W1A_VS5_403_INPUT_NOT_PRESERVED').toBe('2026-04-15');
    expect(browserQueryClient.getQueryCache().getAll().some((query) => query.state.error), 'W1A_VS5_FAILED_QUERY_CACHE_RETAINED').toBe(false);
  });

  test('keeps browser-back list context and logout response delayed without forbidden UI', async () => {
    window.history.replaceState({}, '', '/staff?context=before');
    window.history.pushState({}, '', '/staff?context=detail');
    const queryClient = await openQuarterlyTab('W1A_VS5_CONTEXT_TAB_MISSING', STAFF_A, true);
    const search = screen.getByLabelText('직원 검색', { exact: true }) as HTMLInputElement;
    const sort = screen.getByLabelText(/정렬/) as HTMLSelectElement;
    const scroll = screen.getByTestId('staff-list-scroll') as HTMLElement;
    fireEvent.change(search, { target: { value: 'W1A-VS5' } });
    fireEvent.change(sort, { target: { value: 'staff_no' } });
    scroll.style.height = '8px';
    scroll.style.overflowY = 'auto';
    scroll.scrollTop = 1;
    fireEvent.scroll(scroll);
    const retainedSearch = search.value;
    const retainedSort = sort.value;
    const retainedScrollTop = scroll.scrollTop;
    fireEvent.click(screen.getByRole('tab', { name: '분기상담' }));
    window.history.back();
    await waitFor(() => expect(window.location.search).toContain('context=before'));
    expect((screen.getByLabelText('직원 검색', { exact: true }) as HTMLInputElement).value).toBe(retainedSearch);
    expect((screen.getByLabelText(/정렬/) as HTMLSelectElement).value).toBe(retainedSort);
    expect((screen.getByTestId('staff-list-scroll') as HTMLElement).scrollTop).toBe(retainedScrollTop);
    expect(queryClient.getQueryCache().getAll()).toBeDefined();

    cleanup();
    render(<App />);
    await waitFor(() => expect(screen.getByTestId('app-shell')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('sidebar-logout'));
    await waitFor(() =>
      expect(
        requests.some((request) => request.method === 'POST' && request.path === '/api/auth/logout'),
        'W1A_VS5_LOGOUT_REQUEST_MISSING',
      ).toBe(true),
    );
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument();
    resolveDelayedLogout();
    await waitFor(() => expect(screen.getByTestId('login-form')).toBeInTheDocument());
    expect(screen.queryByTestId('auth-loading')).toBeNull();
  });
});
