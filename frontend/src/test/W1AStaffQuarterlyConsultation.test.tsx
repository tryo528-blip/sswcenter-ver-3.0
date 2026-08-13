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
  id: 91,
  name: '직원 분기상담 계약 테스트',
  employmentId: 901,
} as const;

let canManage = true;
let consultationMode: 'success' | 'loading' | 'empty' | 'error' = 'success';
let requests: RequestRecord[] = [];
let consultationRows: JsonRecord[] = [];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://staff-consultation.test');
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input), 'http://staff-consultation.test');
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  return JSON.parse(body);
}

function consultationRow(overrides: JsonRecord = {}): JsonRecord {
  return {
    id: 9101,
    staff_id: STAFF.id,
    calendar_year: 2026,
    quarter_no: 1,
    completed: false,
    created_by_account_id: 1,
    created_at_utc: '2026-01-01T00:00:00Z',
    updated_by_account_id: 1,
    updated_at_utc: '2026-01-01T00:00:00Z',
    row_version: 4,
    ...overrides,
  };
}

function staffDetail(): JsonRecord {
  return {
    id: STAFF.id,
    name: STAFF.name,
    display_name: STAFF.name,
    birth_date: '1990-01-01',
    sex_code: 'MALE',
    phone: null,
    address: null,
    memo: null,
    row_version: 1,
    current_employment: {
      id: STAFF.employmentId,
      staff_id: STAFF.id,
      staff_no: 'Q-091',
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
    if (/\/(onboarding-trainings|periodic-trainings|health-checks)$/.test(url.pathname)) {
      return jsonResponse({ items: [] });
    }

    const consultationPath = '/api/v1/staff/' + STAFF.id + '/quarterly-consultations';
    if (url.pathname === consultationPath && method === 'GET') {
      if (consultationMode === 'loading') return new Promise<Response>(() => undefined);
      if (consultationMode === 'error') {
        return jsonResponse({ error: { code: 'CONSULTATION_READ_FAILED', message: '분기상담 조회 실패' } }, 500);
      }
      return jsonResponse({ items: consultationMode === 'empty' ? [] : consultationRows });
    }
    if (url.pathname === consultationPath && method === 'POST') {
      const payload = body as JsonRecord;
      const created = consultationRow({
        id: 9102,
        calendar_year: payload.calendar_year,
        quarter_no: payload.quarter_no,
        completed: payload.completed,
        row_version: 1,
      });
      consultationRows = [...consultationRows, created];
      return jsonResponse(created, 201);
    }
    const rowMatch = url.pathname.match(new RegExp('^' + consultationPath + '/(\\d+)$'));
    if (rowMatch && method === 'PATCH') {
      const current =
        consultationRows.find((item) => item.id === Number(rowMatch[1])) ?? consultationRow();
      const updated: JsonRecord = {
        ...current,
        completed: (body as JsonRecord).completed,
        row_version: Number(current.row_version) + 1,
      };
      consultationRows = consultationRows.map((item) =>
        item.id === updated.id ? updated : item,
      );
      return jsonResponse(updated);
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

async function openConsultationTab(): Promise<void> {
  renderStaffPage();
  await waitFor(() => expect(screen.getAllByText(STAFF.name).length).toBeGreaterThan(0));
  fireEvent.click(screen.getByRole('tab', { name: '분기상담' }));
  await screen.findByTestId('staff-quarterly-consultation-panel');
}

async function latestRequest(method: string, path: string): Promise<RequestRecord> {
  await waitFor(() =>
    expect(requests.some((request) => request.method === method && request.path === path)).toBe(true),
  );
  return requests.filter((request) => request.method === method && request.path === path).at(-1) as RequestRecord;
}

beforeEach(() => {
  canManage = true;
  consultationMode = 'success';
  requests = [];
  consultationRows = [
    consultationRow(),
    consultationRow({ id: 9103, quarter_no: 2, completed: true, row_version: 2 }),
  ];
  installFetchFixture();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('W1 직원 분기상담 프론트 계약', () => {
  test('연도·분기별 완료 boolean 토글만 표시한다', async () => {
    await openConsultationTab();

    const rows = await screen.findAllByTestId('quarterly-consultation-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole('checkbox')).not.toBeChecked();
    expect(within(rows[1]).getByRole('checkbox')).toBeChecked();
    for (const row of rows) {
      expect(row.querySelectorAll('input, select, textarea')).toHaveLength(1);
    }
  });

  test('추가 요청은 연도·분기·완료값만 전송한다', async () => {
    await openConsultationTab();
    fireEvent.click(screen.getByTestId('quarterly-consultation-add'));

    const form = screen.getByTestId('quarterly-consultation-create-form');
    expect(form.querySelectorAll('input, select, textarea')).toHaveLength(3);
    fireEvent.change(within(form).getByLabelText('연도'), { target: { value: '2027' } });
    fireEvent.change(within(form).getByLabelText('분기'), { target: { value: '3' } });
    fireEvent.click(within(form).getByRole('checkbox', { name: '완료' }));
    fireEvent.click(within(form).getByRole('button', { name: '분기상담 저장' }));

    const request = await latestRequest(
      'POST',
      '/api/v1/staff/' + STAFF.id + '/quarterly-consultations',
    );
    expect(request.body).toEqual({
      calendar_year: 2027,
      quarter_no: 3,
      completed: true,
    });
  });

  test('행 토글은 완료값과 행 버전만 전송한다', async () => {
    await openConsultationTab();
    const checkbox = await screen.findByRole('checkbox', { name: '2026년 1분기 완료' });
    fireEvent.click(checkbox);

    const request = await latestRequest(
      'PATCH',
      '/api/v1/staff/' + STAFF.id + '/quarterly-consultations/9101',
    );
    expect(request.body).toEqual({
      completed: true,
      expected_row_version: 4,
    });
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: '2026년 1분기 완료' })).toBeChecked(),
    );
  });

  test('조회 전용 사용자는 토글과 추가를 실행할 수 없다', async () => {
    canManage = false;
    await openConsultationTab();

    expect(screen.queryByTestId('quarterly-consultation-add')).toBeNull();
    const checkboxes = await screen.findAllByRole('checkbox');
    expect(checkboxes.every((checkbox) => checkbox.hasAttribute('disabled'))).toBe(true);
  });

  test('빈 목록을 표시한다', async () => {
    consultationMode = 'empty';
    await openConsultationTab();
    expect(await screen.findByText('등록된 분기상담이 없습니다.')).toBeInTheDocument();
  });

  test('로딩을 표시한다', async () => {
    consultationMode = 'loading';
    await openConsultationTab();
    expect(screen.getByText('분기상담을 불러오는 중…')).toBeInTheDocument();
  });

  test('조회 오류를 표시한다', async () => {
    consultationMode = 'error';
    await openConsultationTab();
    expect(await screen.findByText('분기상담 정보를 불러오지 못했습니다.')).toBeInTheDocument();
  });
});
