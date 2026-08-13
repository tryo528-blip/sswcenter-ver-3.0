import './setup';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import StaffPage from '../pages/StaffPage';

type JsonRecord = Record<string, unknown>;

type RequestRecord = {
  body: unknown;
  method: string;
  path: string;
};

const STAFF = {
  id: 81,
  name: '직원 검진 계약 테스트',
  employmentId: 801,
} as const;

let canManage = true;
let healthMode: 'success' | 'loading' | 'empty' | 'error' = 'success';
let mutationError = false;
let requests: RequestRecord[] = [];
let healthRows: JsonRecord[] = [];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://staff-health.test');
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input), 'http://staff-health.test');
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  return JSON.parse(body);
}

function healthRow(overrides: JsonRecord = {}): JsonRecord {
  return {
    id: 9001,
    staff_id: STAFF.id,
    check_date: '2026-08-01',
    invalidated_at_utc: null,
    replacement_health_check_id: null,
    created_by_account_id: 1,
    created_at_utc: '2026-08-01T00:00:00Z',
    updated_by_account_id: 1,
    updated_at_utc: '2026-08-01T00:00:00Z',
    row_version: 3,
    ...overrides,
  };
}

function staffDetail(): JsonRecord {
  return {
    id: STAFF.id,
    name: STAFF.name,
    display_name: STAFF.name,
    birth_date: '1990-01-01',
    sex_code: 'FEMALE',
    phone: null,
    address: null,
    memo: null,
    row_version: 1,
    current_employment: {
      id: STAFF.employmentId,
      staff_id: STAFF.id,
      staff_no: 'H-081',
      start_date: '2026-01-01',
      end_date: null,
      end_reason_code: null,
      status: 'ACTIVE',
      row_version: 1,
    },
    employments: [],
    current_positions: [],
    positions: [],
    operational_roles: [],
    licenses: [],
    service_qualifications: [],
  };
}

function installFetchFixture(): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = requestUrl(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const body = parseBody(init?.body);
    requests.push({ body, method, path: url.pathname });

    if (url.pathname === '/api/v1/session-capabilities') {
      return jsonResponse({
        'staff.view': true,
        'staff.manage': canManage,
        'staff.sensitive_identity.reveal': false,
      });
    }
    if (url.pathname === '/api/v1/catalogs/license-types') return jsonResponse({ items: [] });
    if (url.pathname === '/api/v1/catalogs/services') return jsonResponse({ items: [] });
    if (url.pathname === '/api/v1/staff/training-courses') return jsonResponse({ items: [] });
    if (url.pathname === '/api/v1/staff' && method === 'GET') {
      return jsonResponse({
        items: [{ id: STAFF.id, name: STAFF.name, display_name: STAFF.name, current_employment: null }],
        total: 1,
        page: 1,
        page_size: 1,
      });
    }
    if (url.pathname === '/api/v1/staff/' + STAFF.id && method === 'GET') {
      return jsonResponse(staffDetail());
    }
    if (/\/licenses$/.test(url.pathname)) return jsonResponse({ items: [], total: 0 });
    if (/\/service-qualifications$/.test(url.pathname)) {
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
    }
    if (/\/(onboarding-trainings|periodic-trainings|quarterly-consultations)$/.test(url.pathname)) {
      return jsonResponse({ items: [] });
    }

    const healthPath = '/api/v1/staff/' + STAFF.id + '/health-checks';
    if (url.pathname === healthPath && method === 'GET') {
      if (healthMode === 'loading') return new Promise<Response>(() => undefined);
      if (healthMode === 'error') {
        return jsonResponse({ error: { code: 'HEALTH_READ_FAILED', message: '검진 조회 실패' } }, 500);
      }
      return jsonResponse({ items: healthMode === 'empty' ? [] : healthRows });
    }
    if (url.pathname === healthPath && method === 'POST') {
      if (mutationError) {
        return jsonResponse({ error: { code: 'ROW_VERSION_CONFLICT', message: '최신 값을 다시 확인해주세요.' } }, 409);
      }
      const created = healthRow({
        id: 9002,
        check_date: (body as JsonRecord).check_date,
        row_version: 1,
      });
      healthRows = [...healthRows, created];
      return jsonResponse(created, 201);
    }
    const rowMatch = url.pathname.match(new RegExp('^' + healthPath + '/(\\d+)$'));
    if (rowMatch && method === 'PATCH') {
      const current = healthRows.find((item) => item.id === Number(rowMatch[1])) ?? healthRow();
      const updated: JsonRecord = {
        ...current,
        check_date: (body as JsonRecord).check_date,
        row_version: Number(current.row_version) + 1,
      };
      healthRows = healthRows.map((item) => (item.id === updated.id ? updated : item));
      return jsonResponse(updated);
    }
    if (/\/invalidate$/.test(url.pathname) && method === 'POST') {
      return jsonResponse(healthRows[0] ?? healthRow());
    }
    return jsonResponse({ detail: 'not_found' }, 404);
  });
}

function renderStaffPage(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StaffPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openHealthTab(): Promise<void> {
  renderStaffPage();
  await waitFor(() => expect(screen.getAllByText(STAFF.name).length).toBeGreaterThan(0));
  fireEvent.click(screen.getByRole('tab', { name: '검진' }));
  await screen.findByTestId('staff-health-check-facts-panel');
}

async function latestRequest(method: string, path: string): Promise<RequestRecord> {
  await waitFor(() =>
    expect(requests.some((request) => request.method === method && request.path === path)).toBe(true),
  );
  return requests.filter((request) => request.method === method && request.path === path).at(-1) as RequestRecord;
}

beforeEach(() => {
  canManage = true;
  healthMode = 'success';
  mutationError = false;
  requests = [];
  healthRows = [healthRow()];
  installFetchFixture();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('W1 직원 건강검진 프론트 계약', () => {
  test('검진일 목록과 단일 입력만 표시한다', async () => {
    await openHealthTab();

    const row = await screen.findByTestId('health-check-fact-row');
    expect(row).toHaveTextContent('2026-08-01');
    expect(row.querySelectorAll('span')).toHaveLength(0);

    fireEvent.click(screen.getByTestId('health-check-fact-add'));
    const form = screen.getByTestId('health-check-fact-form');
    expect(form.querySelectorAll('input, select, textarea')).toHaveLength(1);
    expect(within(form).getByLabelText('검진일')).toHaveAttribute('type', 'date');

    const healthRequests = requests.filter((request) => request.path.includes('/health-check'));
    expect(healthRequests.every((request) => /\/health-checks(?:\/\d+|\/\d+\/invalidate)?$/.test(request.path))).toBe(true);
  });

  test('등록 요청은 검진일 하나만 전송한다', async () => {
    await openHealthTab();
    fireEvent.click(screen.getByTestId('health-check-fact-add'));
    fireEvent.change(screen.getByLabelText('검진일'), { target: { value: '2026-08-12' } });
    fireEvent.click(screen.getByRole('button', { name: '검진사실 저장' }));

    const request = await latestRequest('POST', '/api/v1/staff/' + STAFF.id + '/health-checks');
    expect(request.body).toEqual({ check_date: '2026-08-12' });
    await waitFor(() => expect(screen.getByText('2026-08-12')).toBeInTheDocument());
  });

  test('수정 요청은 검진일과 행 버전만 전송한다', async () => {
    await openHealthTab();
    await screen.findByText('2026-08-01');
    fireEvent.click(screen.getByRole('button', { name: '검진사실 수정' }));
    fireEvent.change(screen.getByLabelText('검진일'), { target: { value: '2026-08-10' } });
    fireEvent.click(screen.getByRole('button', { name: '검진사실 저장' }));

    const request = await latestRequest('PATCH', '/api/v1/staff/' + STAFF.id + '/health-checks/9001');
    expect(request.body).toEqual({
      check_date: '2026-08-10',
      expected_row_version: 3,
    });
  });

  test('조회 전용 사용자는 목록만 보고 변경할 수 없다', async () => {
    canManage = false;
    await openHealthTab();

    expect(await screen.findByText('2026-08-01')).toBeInTheDocument();
    expect(screen.queryByTestId('health-check-fact-add')).toBeNull();
    expect(screen.queryByRole('button', { name: '검진사실 수정' })).toBeNull();
    expect(screen.queryByRole('button', { name: '검진사실 무효화' })).toBeNull();
  });

  test('로딩을 표시한다', async () => {
    healthMode = 'loading';
    await openHealthTab();
    expect(screen.getByText('검진사실을 불러오는 중…')).toBeInTheDocument();
  });

  test('빈 목록을 표시한다', async () => {
    healthMode = 'empty';
    await openHealthTab();
    expect(await screen.findByText('등록된 검진이 없습니다.')).toBeInTheDocument();
  });

  test('조회 오류를 표시한다', async () => {
    healthMode = 'error';
    await openHealthTab();
    expect(await screen.findByText('검진 정보를 불러오지 못했습니다.')).toBeInTheDocument();
  });
});
