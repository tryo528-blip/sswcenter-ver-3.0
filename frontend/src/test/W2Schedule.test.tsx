import './setup';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import SchedulePopupPage from '../pages/SchedulePopupPage';
import { ScheduleLedger } from '../components/schedule/ScheduleLedger';
import { AuthContext, type AuthContextType } from '../context/AuthContext';
import { openSchedulePopup, schedulePopupTarget } from '../components/schedule/schedulePopups';
import * as w2Api from '../services/w2Api';
import { type ScheduleMonthSnapshot } from '../services/w2Api';

const originalFetch = globalThis.fetch;
const scheduleCss = readFileSync(join(__dirname, '..', 'styles', 'schedule.css'), 'utf-8');

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function authValue(roleCode: 'ADMIN' | 'USER'): AuthContextType {
  return {
    user: {
      id: 41,
      display_name: roleCode === 'ADMIN' ? '관리자' : '사회복지사',
      role_code: roleCode,
    },
    bootstrapRequired: false,
    isLoading: false,
    isInitialized: true,
    error: null,
    checkAuthStatus: vi.fn(async () => undefined),
    submitBootstrap: vi.fn(async () => true),
    login: vi.fn(async () => true),
    logout: vi.fn(async () => undefined),
    clearError: vi.fn(),
  };
}

function renderPopup(
  kind: 'recipient' | 'care-worker' | 'social-worker',
  role: 'ADMIN' | 'USER' = 'USER',
) {
  return render(
    <AuthContext.Provider value={authValue(role)}>
      <MemoryRouter initialEntries={[`/schedules/${kind}?month=2026-08`]}>
        <Routes>
          <Route path="/schedules/:scheduleKind" element={<SchedulePopupPage />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

function baseScheduleSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    schedule_month: '2026-08-01',
    finalized: false,
    finalized_at_utc: null,
    row_version: 5,
    items: [{
      id: 9,
      schedule_month: '2026-08-01',
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 12,
      starts_at_utc: '2026-08-10T00:00:00Z',
      ends_at_utc: '2026-08-10T01:00:00Z',
      row_version: 2,
    }],
    ...overrides,
  };
}

function clientScheduleItem(
  overrides: Partial<ScheduleMonthSnapshot['items'][number]> = {},
): ScheduleMonthSnapshot['items'][number] {
  return {
    id: 9,
    scheduleMonth: '2026-08-01',
    recipientId: 10,
    assignedStaff: [{ staffId: 11, employmentId: 21 }],
    serviceTypeId: 12,
    startsAtUtc: '2026-08-10T00:00:00Z',
    endsAtUtc: '2026-08-10T01:00:00Z',
    rowVersion: 2,
    ...overrides,
  };
}

function clientScheduleSnapshot(overrides: Partial<ScheduleMonthSnapshot> = {}): ScheduleMonthSnapshot {
  return {
    scheduleMonth: '2026-08-01',
    finalized: false,
    finalizedAtUtc: null,
    rowVersion: 5,
    items: [clientScheduleItem()],
    ...overrides,
  };
}

function queueListSchedules() {
  const calls: Array<{
    params: Parameters<typeof w2Api.listSchedules>[0];
    resolve: (value: ScheduleMonthSnapshot) => void;
    reject: (reason?: unknown) => void;
  }> = [];
  const spy = vi.spyOn(w2Api, 'listSchedules').mockImplementation((params) => {
    if (params.signal?.aborted) {
      const error = new Error('The operation was aborted.');
      error.name = 'AbortError';
      return Promise.reject(error);
    }
    const next = deferred<ScheduleMonthSnapshot>();
    calls.push({ params, ...next });
    return next.promise;
  });
  return { spy, calls };
}

function queueCreateSchedule() {
  const pending = deferred<ScheduleMonthSnapshot>();
  const spy = vi.spyOn(w2Api, 'createSchedule').mockImplementation(() => pending.promise);
  return { spy, pending };
}

function scheduleItemPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 9,
    schedule_month: '2026-08-01',
    recipient_id: 10,
    assigned_staff: [{ staff_id: 11, employment_id: 21 }],
    service_type_id: 12,
    starts_at_utc: '2026-08-10T00:00:00Z',
    ends_at_utc: '2026-08-10T01:00:00Z',
    row_version: 2,
    ...overrides,
  };
}

function scheduleMutationCalls(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.filter(([, init]) => {
    const method = String(init?.method ?? 'GET');
    return method === 'POST' || method === 'PUT' || method === 'DELETE';
  });
}

function fillRequiredDraft(
  values: {
    recipientId?: string;
    staffId?: string;
    employmentId?: string;
    serviceTypeId?: string;
  } = {},
) {
  fireEvent.change(screen.getByLabelText('수급자 ID', { selector: 'input' }), {
    target: { value: values.recipientId ?? '10' },
  });
  fireEvent.change(screen.getByLabelText('담당 직원 1 ID', { selector: 'input' }), {
    target: { value: values.staffId ?? '11' },
  });
  fireEvent.change(screen.getByLabelText('담당 직원 1 재직 ID'), {
    target: { value: values.employmentId ?? '21' },
  });
  fireEvent.change(screen.getByLabelText('서비스 유형 ID'), {
    target: { value: values.serviceTypeId ?? '12' },
  });
}

function applyNumericFilter(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: '조회' }));
}

function attemptBlockedMutations() {
  fireEvent.submit(screen.getByRole('form', { name: '일정 임시입력' }));
  fireEvent.click(screen.getByRole('button', { name: '월 확정' }));
  fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
}

describe('W2 schedule popup', () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => { globalThis.fetch = originalFetch; });

  it('shows personal todos only inside the signed-in social-worker calendar', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/personal-todos') {
        return json({
          list_revision: 3,
          items: [{
            id: 1,
            title: '내 할 일',
            completed: false,
            sort_order: 0,
            row_version: 1,
          }],
        });
      }
      throw new Error(`Unexpected request ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('social-worker');
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('내 할 일')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '내 할 일 순서 변경' })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/schedules?month=2026-08-01',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/personal-todos',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('does not request or render personal todos for an administrator', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      throw new Error(`Unexpected request ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('social-worker', 'ADMIN');
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '개인 할 일' })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/personal-todos'))).toBe(false);
  });

  it('uses the recipient projection UI over the same unlabelled schedules API', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      throw new Error(`Unexpected request ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    expect(await screen.findByRole('button', { name: /서비스 12.*직원 11/ }))
      .toBeInTheDocument();
    expect(screen.getByLabelText('수급자 ID 조회')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '개인 할 일' })).not.toBeInTheDocument();
  });

  it('keeps the unsaved draft and displays details.latest on 409 without auto-merge', async () => {
    const latest = baseScheduleSnapshot({
      row_version: 6,
      items: [{
        id: 77,
        schedule_month: '2026-08-01',
        recipient_id: 90,
        assigned_staff: [{ staff_id: 91, employment_id: 191 }],
        service_type_id: 99,
        starts_at_utc: '2026-08-01T00:00:00Z',
        ends_at_utc: '2026-08-01T01:00:00Z',
        row_version: 1,
      }],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return json({
          error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 저장됨' },
          details: { latest },
        }, 409);
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    await screen.findByText('등록된 일정이 없습니다.');
    fireEvent.change(screen.getByLabelText('수급자 ID', { selector: 'input' }), {
      target: { value: '10' },
    });
    fireEvent.change(screen.getByLabelText('담당 직원 1 ID', { selector: 'input' }), {
      target: { value: '11' },
    });
    fireEvent.change(screen.getByLabelText('담당 직원 1 재직 ID'), {
      target: { value: '21' },
    });
    fireEvent.change(screen.getByLabelText('서비스 유형 ID'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));

    expect(await screen.findByTestId('schedule-latest-snapshot')).toHaveTextContent('서비스 99');
    expect(screen.getByLabelText('수급자 ID', { selector: 'input' })).toHaveValue('10');
    expect(screen.getByLabelText('담당 직원 1 ID', { selector: 'input' })).toHaveValue('11');
    expect(screen.getByLabelText('담당 직원 1 재직 ID')).toHaveValue('21');
    expect(screen.getByLabelText('서비스 유형 ID')).toHaveValue('12');
    expect(screen.queryByText('서비스 99', { selector: '.schedule-calendar-entry strong' }))
      .not.toBeInTheDocument();

    const saveCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    expect(JSON.parse(String(saveCall?.[1]?.body))).toEqual({
      schedule_month: '2026-08-01',
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 12,
      starts_at_utc: '2026-08-01T00:00:00.000Z',
      ends_at_utc: '2026-08-01T01:00:00.000Z',
      expected_month_row_version: 5,
    });
  });

  it('replaces a selected schedule with PUT and no schedule_month payload', async () => {
    const replacedItem = {
      id: 9,
      schedule_month: '2026-08-01',
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 13,
      starts_at_utc: '2026-08-10T00:00:00Z',
      ends_at_utc: '2026-08-10T01:00:00Z',
      row_version: 3,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules/9' && init?.method === 'PUT') {
        return json(baseScheduleSnapshot({ row_version: 6, items: [replacedItem] }));
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('care-worker');
    fireEvent.click(await screen.findByRole('button', { name: /서비스 12/ }));
    fireEvent.change(screen.getByLabelText('서비스 유형 ID'), { target: { value: '13' } });
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));

    expect(await screen.findByText('서비스 13')).toBeInTheDocument();
    const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT');
    const body = JSON.parse(String(putCall?.[1]?.body));
    expect(body).toMatchObject({
      expected_month_row_version: 5,
      expected_row_version: 2,
      recipient_id: 10,
      assigned_staff: [{ staff_id: 11, employment_id: 21 }],
      service_type_id: 13,
    });
    expect(body).not.toHaveProperty('schedule_month');
  });

  it('deletes a selected schedule with exact row and month versions', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules/9' && init?.method === 'DELETE') {
        return json(baseScheduleSnapshot({ row_version: 6, items: [] }));
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('care-worker');
    fireEvent.click(await screen.findByRole('button', { name: /서비스 12/ }));
    fireEvent.click(screen.getByRole('button', { name: '일정 삭제' }));

    await screen.findByText('등록된 일정이 없습니다.');
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE');
    expect(JSON.parse(String(deleteCall?.[1]?.body))).toEqual({
      expected_month_row_version: 5,
      expected_row_version: 2,
    });
  });

  it('finalizes through the schedule-month endpoint and uses the returned snapshot', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedule-months/2026-08-01/finalize') {
        return json(baseScheduleSnapshot({ row_version: 6, finalized: true }));
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    fireEvent.click(await screen.findByRole('button', { name: '월 확정' }));
    expect(await screen.findByRole('button', { name: '확정됨' })).toBeDisabled();
    const finalizeCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/finalize'));
    expect(JSON.parse(String(finalizeCall?.[1]?.body))).toEqual({
      expected_month_row_version: 5,
    });
  });

  it('hides stale rows while a new query is pending and blocks handler mutations', async () => {
    const pendingQuery = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules?month=2026-08-01&recipient_id=10') {
        return pendingQuery.promise;
      }
      throw new Error(`Unexpected request ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    fillRequiredDraft();
    applyNumericFilter('수급자 ID 조회', '10');

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/schedules?month=2026-08-01&recipient_id=10',
      expect.objectContaining({ method: 'GET' }),
    ));
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();
    expect(screen.getByLabelText('수급자 ID', { selector: 'input' })).toHaveValue('10');
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '월 확정' })).toBeDisabled();

    const mutationsBefore = scheduleMutationCalls(fetchMock).length;
    attemptBlockedMutations();
    expect(scheduleMutationCalls(fetchMock)).toHaveLength(mutationsBefore);

    pendingQuery.resolve(json(baseScheduleSnapshot({ row_version: 6, items: [] })));
    await waitFor(() => expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled());
    expect(screen.getByLabelText('수급자 ID', { selector: 'input' })).toHaveValue('10');
    expect(screen.getByText('등록된 일정이 없습니다.')).toBeInTheDocument();
  });

  it('keeps ownership unproven and mutations blocked after the current GET fails', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules?month=2026-08-01&recipient_id=10') {
        return json({
          error: { code: 'SCHEDULE_LIST_FAILED', message: '필터 조회 실패' },
        }, 500);
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    applyNumericFilter('수급자 ID 조회', '10');

    expect(await screen.findByRole('alert')).toHaveTextContent('필터 조회 실패');
    expect(screen.queryByText('일정을 불러오는 중…')).not.toBeInTheDocument();
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '월 확정' })).toBeDisabled();

    attemptBlockedMutations();
    expect(scheduleMutationCalls(fetchMock)).toHaveLength(0);
  });

  it('ignores an out-of-order old schedule success after a newer query', async () => {
    const oldQuery = deferred<ScheduleMonthSnapshot>();
    const newQuery = deferred<ScheduleMonthSnapshot>();
    const listSchedulesSpy = vi.spyOn(w2Api, 'listSchedules')
      .mockImplementationOnce(() => oldQuery.promise)
      .mockImplementationOnce(() => newQuery.promise);

    renderPopup('recipient');
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(1));

    applyNumericFilter('수급자 ID 조회', '10');
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();

    newQuery.resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [{
        id: 77,
        scheduleMonth: '2026-08-01',
        recipientId: 10,
        assignedStaff: [{ staffId: 11, employmentId: 21 }],
        serviceTypeId: 99,
        startsAtUtc: '2026-08-11T00:00:00Z',
        endsAtUtc: '2026-08-11T01:00:00Z',
        rowVersion: 1,
      }],
    }));
    expect(await screen.findByText('서비스 99')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();

    oldQuery.resolve(clientScheduleSnapshot());
    await waitFor(() => expect(screen.queryByText('서비스 12')).not.toBeInTheDocument());
    expect(screen.getByText('서비스 99')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('ignores an out-of-order old schedule error and finally while a newer query is pending', async () => {
    const oldQuery = deferred<ScheduleMonthSnapshot>();
    const newQuery = deferred<ScheduleMonthSnapshot>();
    const listSchedulesSpy = vi.spyOn(w2Api, 'listSchedules')
      .mockImplementationOnce(() => oldQuery.promise)
      .mockImplementationOnce(() => newQuery.promise);

    renderPopup('recipient');
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(1));

    applyNumericFilter('수급자 ID 조회', '10');
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(2));

    oldQuery.reject(new Error('이전 조회 실패'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '월 확정' })).toBeDisabled();

    newQuery.resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [{
        id: 77,
        scheduleMonth: '2026-08-01',
        recipientId: 10,
        assignedStaff: [{ staffId: 11, employmentId: 21 }],
        serviceTypeId: 99,
        startsAtUtc: '2026-08-11T00:00:00Z',
        endsAtUtc: '2026-08-11T01:00:00Z',
        rowVersion: 1,
      }],
    }));
    expect(await screen.findByText('서비스 99')).toBeInTheDocument();
    expect(screen.queryByText('이전 조회 실패')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('projects a full-month mutation snapshot onto the active recipient filter without changing ownership', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules?month=2026-08-01&recipient_id=10') {
        return json(baseScheduleSnapshot({
          items: [scheduleItemPayload()],
        }));
      }
      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return json(baseScheduleSnapshot({
          row_version: 7,
          items: [
            scheduleItemPayload(),
            scheduleItemPayload({
              id: 88,
              recipient_id: 90,
              assigned_staff: [{ staff_id: 99, employment_id: 191 }],
              service_type_id: 99,
              starts_at_utc: '2026-08-11T00:00:00Z',
              ends_at_utc: '2026-08-11T01:00:00Z',
              row_version: 1,
            }),
          ],
        }));
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    applyNumericFilter('수급자 ID 조회', '10');
    await waitFor(() => expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled());

    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));

    await waitFor(() => expect(screen.getByText('공용 schedules 원장 · version 7')).toBeInTheDocument());
    expect(screen.getByText('서비스 12')).toBeInTheDocument();
    expect(screen.queryByText('서비스 99')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();

    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(scheduleMutationCalls(fetchMock)).toHaveLength(2));
    expect(screen.queryByText('서비스 99')).not.toBeInTheDocument();
  });

  it('projects a full-month mutation snapshot onto the active staff filter', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules?month=2026-08-01&staff_id=11') {
        return json(baseScheduleSnapshot({ items: [scheduleItemPayload()] }));
      }
      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return json(baseScheduleSnapshot({
          row_version: 7,
          items: [
            scheduleItemPayload(),
            scheduleItemPayload({
              id: 88,
              recipient_id: 90,
              assigned_staff: [{ staff_id: 99, employment_id: 191 }],
              service_type_id: 99,
              starts_at_utc: '2026-08-11T00:00:00Z',
              ends_at_utc: '2026-08-11T01:00:00Z',
              row_version: 1,
            }),
          ],
        }));
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('care-worker');
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    applyNumericFilter('직원 ID 조회', '11');
    await waitFor(() => expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled());

    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));

    await waitFor(() => expect(screen.getByText('공용 schedules 원장 · version 7')).toBeInTheDocument());
    expect(screen.getByText('서비스 12')).toBeInTheDocument();
    expect(screen.queryByText('서비스 99')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('ignores a mutation success that started before a newer month query', async () => {
    const pendingPost = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/schedules?month=2026-08-01' && method === 'GET') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules?month=2026-09-01' && method === 'GET') {
        return json(baseScheduleSnapshot({
          schedule_month: '2026-09-01',
          items: [scheduleItemPayload({
            id: 50,
            schedule_month: '2026-09-01',
            service_type_id: 55,
            starts_at_utc: '2026-09-10T00:00:00Z',
            ends_at_utc: '2026-09-10T01:00:00Z',
          })],
        }));
      }
      if (url === '/api/v1/schedules' && method === 'POST') {
        return pendingPost.promise;
      }
      throw new Error(`Unexpected request ${method} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(scheduleMutationCalls(fetchMock)).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();

    pendingPost.resolve(json(baseScheduleSnapshot({
      row_version: 9,
      items: [scheduleItemPayload({
        id: 70,
        service_type_id: 70,
        starts_at_utc: '2026-08-20T00:00:00Z',
        ends_at_utc: '2026-08-20T01:00:00Z',
      })],
    })));

    await waitFor(() => expect(screen.queryByText('서비스 70')).not.toBeInTheDocument());
    expect(screen.getByText('서비스 55')).toBeInTheDocument();
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
  });

  it('ignores conflict latest from a mutation that started before a newer month query', async () => {
    const pendingPost = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/schedules?month=2026-08-01' && method === 'GET') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules?month=2026-09-01' && method === 'GET') {
        return json(baseScheduleSnapshot({
          schedule_month: '2026-09-01',
          items: [scheduleItemPayload({
            id: 50,
            schedule_month: '2026-09-01',
            service_type_id: 55,
            starts_at_utc: '2026-09-10T00:00:00Z',
            ends_at_utc: '2026-09-10T01:00:00Z',
          })],
        }));
      }
      if (url === '/api/v1/schedules' && method === 'POST') {
        return pendingPost.promise;
      }
      throw new Error(`Unexpected request ${method} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(scheduleMutationCalls(fetchMock)).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();

    pendingPost.resolve(json({
      error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 저장됨' },
      details: {
        latest: baseScheduleSnapshot({
          row_version: 11,
          items: [scheduleItemPayload({
            id: 88,
            recipient_id: 90,
            service_type_id: 99,
            starts_at_utc: '2026-08-01T00:00:00Z',
            ends_at_utc: '2026-08-01T01:00:00Z',
          })],
        }),
      },
    }, 409));

    await waitFor(() => {
      expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
    });
    expect(screen.getByText('서비스 55')).toBeInTheDocument();
    expect(screen.queryByText('서비스 99')).not.toBeInTheDocument();
    expect(screen.queryByText(/다른 요청이 먼저 저장되었습니다/)).not.toBeInTheDocument();
  });

  it('filters conflict latest to the current recipient query before display and accept', async () => {
    const latest = baseScheduleSnapshot({
      row_version: 8,
      items: [
        scheduleItemPayload(),
        scheduleItemPayload({
          id: 88,
          recipient_id: 90,
          assigned_staff: [{ staff_id: 99, employment_id: 191 }],
          service_type_id: 99,
          starts_at_utc: '2026-08-11T00:00:00Z',
          ends_at_utc: '2026-08-11T01:00:00Z',
          row_version: 1,
        }),
      ],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules?month=2026-08-01&recipient_id=10') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return json({
          error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 저장됨' },
          details: { latest },
        }, 409);
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    await screen.findByText('등록된 일정이 없습니다.');
    applyNumericFilter('수급자 ID 조회', '10');
    await waitFor(() => expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled());
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));

    const latestBox = await screen.findByTestId('schedule-latest-snapshot');
    expect(latestBox).toHaveTextContent('서비스 12');
    expect(latestBox).not.toHaveTextContent('서비스 99');
    expect(screen.getByLabelText('수급자 ID', { selector: 'input' })).toHaveValue('10');
    expect(screen.queryByText('서비스 12', { selector: '.schedule-calendar-entry strong' }))
      .not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '최신본 기준으로 계속 편집' }));
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
    expect(screen.getByText('서비스 12')).toBeInTheDocument();
    expect(screen.queryByText('서비스 99')).not.toBeInTheDocument();
    expect(screen.getByLabelText('수급자 ID', { selector: 'input' })).toHaveValue('10');
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('filters conflict latest to the current staff query before display and accept', async () => {
    const latest = baseScheduleSnapshot({
      row_version: 8,
      items: [
        scheduleItemPayload(),
        scheduleItemPayload({
          id: 88,
          recipient_id: 90,
          assigned_staff: [{ staff_id: 99, employment_id: 191 }],
          service_type_id: 99,
          starts_at_utc: '2026-08-11T00:00:00Z',
          ends_at_utc: '2026-08-11T01:00:00Z',
          row_version: 1,
        }),
      ],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules?month=2026-08-01&staff_id=11') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return json({
          error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 저장됨' },
          details: { latest },
        }, 409);
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('care-worker');
    await screen.findByText('등록된 일정이 없습니다.');
    applyNumericFilter('직원 ID 조회', '11');
    await waitFor(() => expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled());
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));

    const latestBox = await screen.findByTestId('schedule-latest-snapshot');
    expect(within(latestBox).getByText(/서비스 12/)).toBeInTheDocument();
    expect(within(latestBox).queryByText(/서비스 99/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '최신본 기준으로 계속 편집' }));
    expect(screen.getByText('서비스 12')).toBeInTheDocument();
    expect(screen.queryByText('서비스 99')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('does not start a filter query while a mutation is saving', async () => {
    const pendingPost = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/schedules' && init?.method === 'POST') {
        return pendingPost.promise;
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(scheduleMutationCalls(fetchMock)).toHaveLength(1));

    fireEvent.change(screen.getByLabelText('수급자 ID 조회'), { target: { value: '10' } });
    fireEvent.submit(screen.getByLabelText('수급자 ID 조회').closest('form') as HTMLFormElement);
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes('recipient_id=10')),
    ).toBe(false);

    pendingPost.resolve(json(baseScheduleSnapshot({
      row_version: 6,
      items: [scheduleItemPayload()],
    })));
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
  });

  it('keeps a revisited A query unproven when the fresh A refetch fails', async () => {
    const firstA = deferred<ScheduleMonthSnapshot>();
    const queryB = deferred<ScheduleMonthSnapshot>();
    const secondA = deferred<ScheduleMonthSnapshot>();
    const listSchedulesSpy = vi.spyOn(w2Api, 'listSchedules')
      .mockImplementationOnce(() => firstA.promise)
      .mockImplementationOnce(() => queryB.promise)
      .mockImplementationOnce(() => secondA.promise);

    renderPopup('recipient');
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(1));
    firstA.resolve(clientScheduleSnapshot());
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();

    applyNumericFilter('수급자 ID 조회', '10');
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText('수급자 ID 조회'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '조회' }));
    await waitFor(() => expect(listSchedulesSpy).toHaveBeenCalledTimes(3));

    secondA.reject(new Error('두 번째 A 조회 실패'));
    expect(await screen.findByRole('alert')).toHaveTextContent('두 번째 A 조회 실패');
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '월 확정' })).toBeDisabled();

    queryB.resolve(clientScheduleSnapshot({
      items: [{
        id: 66,
        scheduleMonth: '2026-08-01',
        recipientId: 10,
        assignedStaff: [{ staffId: 11, employmentId: 21 }],
        serviceTypeId: 66,
        startsAtUtc: '2026-08-12T00:00:00Z',
        endsAtUtc: '2026-08-12T01:00:00Z',
        rowVersion: 1,
      }],
    }));
    await waitFor(() => expect(screen.queryByText('서비스 66')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
  });

  it('does not let the first A GET success prove a revisited A after A-B-A', async () => {
    const { spy, calls } = queueListSchedules();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(spy).toHaveBeenCalledTimes(3);
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();

    calls[0].resolve(clientScheduleSnapshot());
    await waitFor(() => expect(screen.queryByText('서비스 12')).not.toBeInTheDocument());
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    calls[2].resolve(clientScheduleSnapshot({
      rowVersion: 9,
      items: [clientScheduleItem({
        id: 88,
        serviceTypeId: 88,
        startsAtUtc: '2026-08-18T00:00:00Z',
        endsAtUtc: '2026-08-18T01:00:00Z',
        rowVersion: 4,
      })],
    }));
    expect(await screen.findByText('서비스 88')).toBeInTheDocument();
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('does not let the first A GET error or finally affect a pending revisited A', async () => {
    const { calls } = queueListSchedules();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));

    calls[0].reject(new Error('첫 번째 A 조회 실패'));
    await waitFor(() => expect(screen.queryByText('첫 번째 A 조회 실패')).not.toBeInTheDocument());
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '월 확정' })).toBeDisabled();

    calls[2].resolve(clientScheduleSnapshot({
      rowVersion: 9,
      items: [clientScheduleItem({
        id: 88,
        serviceTypeId: 88,
        startsAtUtc: '2026-08-18T00:00:00Z',
        endsAtUtc: '2026-08-18T01:00:00Z',
        rowVersion: 4,
      })],
    }));
    expect(await screen.findByText('서비스 88')).toBeInTheDocument();
    expect(screen.queryByText('첫 번째 A 조회 실패')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('refetches a revisited A after an old mutation commits over a stale pre-commit GET', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [clientScheduleItem({
        id: 55,
        scheduleMonth: '2026-09-01',
        serviceTypeId: 55,
        startsAtUtc: '2026-09-10T00:00:00Z',
        endsAtUtc: '2026-09-10T01:00:00Z',
      })],
    }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    calls[2].resolve(clientScheduleSnapshot({
      rowVersion: 5,
      items: [clientScheduleItem()],
    }));
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    expect(screen.getByText('공용 schedules 원장 · version 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled();

    fireEvent.submit(screen.getByRole('form', { name: '일정 임시입력' }));
    fireEvent.click(screen.getByRole('button', { name: '월 확정' }));
    fireEvent.click(screen.getByRole('button', { name: '저장 중…' }));
    expect(createSpy).toHaveBeenCalledTimes(1);

    pendingCreate.resolve(clientScheduleSnapshot({
      rowVersion: 6,
      finalizedAtUtc: '2026-08-15T01:00:00Z',
      items: [clientScheduleItem({
        id: 70,
        serviceTypeId: 70,
        startsAtUtc: '2026-08-20T00:00:00Z',
        endsAtUtc: '2026-08-20T01:00:00Z',
      })],
    }));

    await waitFor(() => expect(calls).toHaveLength(4));
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.queryByText('서비스 70')).not.toBeInTheDocument();
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();

    calls[3].resolve(clientScheduleSnapshot({
      rowVersion: 6,
      finalizedAtUtc: '2026-08-15T01:00:00Z',
      items: [clientScheduleItem({
        id: 70,
        serviceTypeId: 70,
        startsAtUtc: '2026-08-20T00:00:00Z',
        endsAtUtc: '2026-08-20T01:00:00Z',
      })],
    }));
    expect(await screen.findByText('서비스 70')).toBeInTheDocument();
    expect(screen.getByText('공용 schedules 원장 · version 6')).toBeInTheDocument();
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('does not let a revisited pre-commit GET that resolves after mutation success overwrite the refetch', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [clientScheduleItem({
        id: 55,
        scheduleMonth: '2026-09-01',
        serviceTypeId: 55,
        startsAtUtc: '2026-09-10T00:00:00Z',
        endsAtUtc: '2026-09-10T01:00:00Z',
      })],
    }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(screen.getByRole('button', { name: '저장 중…' })).toBeDisabled();

    pendingCreate.resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [clientScheduleItem({
        id: 70,
        serviceTypeId: 70,
        startsAtUtc: '2026-08-20T00:00:00Z',
        endsAtUtc: '2026-08-20T01:00:00Z',
      })],
    }));
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();

    calls[2].resolve(clientScheduleSnapshot({
      rowVersion: 5,
      items: [clientScheduleItem()],
    }));
    await waitFor(() => expect(screen.queryByText('서비스 12')).not.toBeInTheDocument());
    expect(screen.getByText('일정을 불러오는 중…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeDisabled();

    calls[3].resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [clientScheduleItem({
        id: 70,
        serviceTypeId: 70,
        startsAtUtc: '2026-08-20T00:00:00Z',
        endsAtUtc: '2026-08-20T01:00:00Z',
      })],
    }));
    expect(await screen.findByText('서비스 70')).toBeInTheDocument();
    expect(screen.queryByText('서비스 12')).not.toBeInTheDocument();
    expect(screen.getByText('공용 schedules 원장 · version 6')).toBeInTheDocument();
  });

  it('surfaces an old A 409 with embedded latest on a revisited A visit and accepts it', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [],
    }));
    await screen.findByText('등록된 일정이 없습니다.');
    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    calls[2].resolve(clientScheduleSnapshot({
      rowVersion: 9,
      items: [clientScheduleItem({
        id: 88,
        serviceTypeId: 88,
        startsAtUtc: '2026-08-18T00:00:00Z',
        endsAtUtc: '2026-08-18T01:00:00Z',
        rowVersion: 4,
      })],
    }));
    expect(await screen.findByText('서비스 88')).toBeInTheDocument();

    pendingCreate.reject(new w2Api.W2ConflictError('예전 A 충돌', {
      latestScheduleSnapshot: clientScheduleSnapshot({
        rowVersion: 6,
        items: [clientScheduleItem({
          id: 66,
          serviceTypeId: 66,
          startsAtUtc: '2026-08-16T00:00:00Z',
          endsAtUtc: '2026-08-16T01:00:00Z',
        })],
      }),
    }));

    const latestBox = await screen.findByTestId('schedule-latest-snapshot');
    expect(latestBox).toHaveTextContent('서비스 66');
    expect(screen.getByText(/다른 요청이 먼저 저장되었습니다/)).toBeInTheDocument();
    expect(screen.getByText('서비스 88')).toBeInTheDocument();
    expect(screen.queryByText('서비스 66', { selector: '.schedule-calendar-entry strong' }))
      .not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '최신본 기준으로 계속 편집' }));
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
    expect(await screen.findByText('서비스 66')).toBeInTheDocument();
    expect(screen.queryByText('서비스 88')).not.toBeInTheDocument();
    expect(screen.getByText('공용 schedules 원장 · version 6')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('uses a fresh latest-missing fallback after A-B-A and surfaces it on the revisited visit', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [],
    }));
    await screen.findByText('등록된 일정이 없습니다.');
    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    calls[2].resolve(clientScheduleSnapshot({
      rowVersion: 9,
      items: [clientScheduleItem({
        id: 88,
        serviceTypeId: 88,
        startsAtUtc: '2026-08-18T00:00:00Z',
        endsAtUtc: '2026-08-18T01:00:00Z',
        rowVersion: 4,
      })],
    }));
    expect(await screen.findByText('서비스 88')).toBeInTheDocument();

    pendingCreate.reject(new w2Api.W2ConflictError('최신본 없음'));
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(calls[3].params.signal?.aborted).toBe(false);
    expect(calls[3].params.month).toBe('2026-08-01');

    calls[3].resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [clientScheduleItem({
        id: 66,
        serviceTypeId: 66,
        startsAtUtc: '2026-08-16T00:00:00Z',
        endsAtUtc: '2026-08-16T01:00:00Z',
      })],
    }));
    const latestBox = await screen.findByTestId('schedule-latest-snapshot');
    expect(latestBox).toHaveTextContent('서비스 66');
    expect(screen.getByText(/다른 요청이 먼저 저장되었습니다/)).toBeInTheDocument();
    expect(screen.getByText('서비스 88')).toBeInTheDocument();
  });

  it('starts a fresh latest-missing fallback after A-B-A and aborts it on the next query change', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [clientScheduleItem({
        id: 55,
        scheduleMonth: '2026-09-01',
        serviceTypeId: 55,
        startsAtUtc: '2026-09-10T00:00:00Z',
        endsAtUtc: '2026-09-10T01:00:00Z',
      })],
    }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    calls[2].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');

    pendingCreate.reject(new w2Api.W2ConflictError('최신본 없음'));
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(calls[3].params.signal?.aborted).toBe(false);
    expect(calls[3].params.month).toBe('2026-08-01');

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(5));
    expect(calls[3].params.signal?.aborted).toBe(true);
    calls[4].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [clientScheduleItem({
        id: 55,
        scheduleMonth: '2026-09-01',
        serviceTypeId: 55,
        startsAtUtc: '2026-09-10T00:00:00Z',
        endsAtUtc: '2026-09-10T01:00:00Z',
      })],
    }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();

    calls[3].resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [clientScheduleItem({
        id: 66,
        serviceTypeId: 66,
        startsAtUtc: '2026-08-16T00:00:00Z',
        endsAtUtc: '2026-08-16T01:00:00Z',
      })],
    }));
    await waitFor(() => expect(screen.queryByText('서비스 66')).not.toBeInTheDocument());
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
    expect(screen.getByText('서비스 55')).toBeInTheDocument();
  });

  it('surfaces a non-conflict failure from an old A mutation after A-B-A', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    await waitFor(() => expect(calls).toHaveLength(2));
    calls[1].resolve(clientScheduleSnapshot({
      scheduleMonth: '2026-09-01',
      items: [],
    }));
    await screen.findByText('등록된 일정이 없습니다.');
    fireEvent.click(screen.getByRole('button', { name: '이전 달' }));
    await waitFor(() => expect(calls).toHaveLength(3));
    calls[2].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');

    pendingCreate.reject(new Error('네트워크 저장 실패'));
    expect(await screen.findByRole('alert')).toHaveTextContent('네트워크 저장 실패');
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled();
  });

  it('clears the applied filter when the schedule kind changes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot());
      }
      if (url === '/api/v1/schedules?month=2026-08-01&recipient_id=10') {
        return json(baseScheduleSnapshot({ items: [scheduleItemPayload()] }));
      }
      if (url === '/api/v1/schedules?month=2026-08-01&staff_id=10') {
        return json(baseScheduleSnapshot({ items: [scheduleItemPayload()] }));
      }
      throw new Error(`Unexpected request ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { rerender } = render(<ScheduleLedger kind="recipient" month="2026-08" />);
    expect(await screen.findByText('서비스 12')).toBeInTheDocument();
    applyNumericFilter('수급자 ID 조회', '10');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/schedules?month=2026-08-01&recipient_id=10',
      expect.objectContaining({ method: 'GET' }),
    ));

    rerender(<ScheduleLedger kind="care-worker" month="2026-08" />);
    expect(screen.getByLabelText('직원 ID 조회')).toHaveValue('');
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/schedules?month=2026-08-01',
      expect.objectContaining({ method: 'GET' }),
    ));
    expect(await screen.findByRole('button', { name: /서비스 12.*수급자 10/ })).toBeInTheDocument();
  });

  it('does not apply a pending mutation or missing-latest fallback after unmount', async () => {
    const { calls } = queueListSchedules();
    const { spy: createSpy, pending: pendingCreate } = queueCreateSchedule();
    const { unmount } = renderPopup('recipient');
    await waitFor(() => expect(calls).toHaveLength(1));
    calls[0].resolve(clientScheduleSnapshot({ items: [] }));
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));

    pendingCreate.reject(new w2Api.W2ConflictError('최신본 없음'));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].params.signal?.aborted).toBe(false);

    unmount();
    expect(calls[1].params.signal?.aborted).toBe(true);
    calls[1].resolve(clientScheduleSnapshot({
      rowVersion: 6,
      items: [clientScheduleItem({
        id: 66,
        serviceTypeId: 66,
        startsAtUtc: '2026-08-16T00:00:00Z',
        endsAtUtc: '2026-08-16T01:00:00Z',
      })],
    }));
    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
    expect(screen.queryByText(/다른 요청이 먼저 저장되었습니다/)).not.toBeInTheDocument();
  });

  it('aborts a latest-missing conflict fallback when the query visit changes', async () => {
    const pendingFallback = deferred<Response>();
    let augustReads = 0;
    let fallbackSignal: AbortSignal | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/schedules?month=2026-08-01' && method === 'GET') {
        augustReads += 1;
        if (augustReads === 1) return json(baseScheduleSnapshot({ items: [] }));
        fallbackSignal = init?.signal ?? null;
        return pendingFallback.promise;
      }
      if (url === '/api/v1/schedules?month=2026-09-01' && method === 'GET') {
        return json(baseScheduleSnapshot({
          schedule_month: '2026-09-01',
          items: [scheduleItemPayload({
            id: 55,
            schedule_month: '2026-09-01',
            service_type_id: 55,
            starts_at_utc: '2026-09-10T00:00:00Z',
            ends_at_utc: '2026-09-10T01:00:00Z',
          })],
        }));
      }
      if (url === '/api/v1/schedules' && method === 'POST') {
        return json({
          error: { code: 'ROW_VERSION_CONFLICT', message: '최신본 없음' },
          details: {},
        }, 409);
      }
      throw new Error(`Unexpected request ${method} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    renderPopup('recipient');
    await screen.findByText('등록된 일정이 없습니다.');
    fillRequiredDraft();
    fireEvent.click(screen.getByRole('button', { name: '임시저장' }));
    await waitFor(() => expect(augustReads).toBe(2));
    expect(fallbackSignal).not.toBeNull();
    expect(fallbackSignal?.aborted).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '다음 달' }));
    expect(await screen.findByText('서비스 55')).toBeInTheDocument();
    expect(fallbackSignal?.aborted).toBe(true);

    pendingFallback.resolve(json(baseScheduleSnapshot({
      row_version: 6,
      items: [scheduleItemPayload({ service_type_id: 66 })],
    })));
    await waitFor(() => expect(screen.getByRole('button', { name: '임시저장' })).toBeEnabled());
    expect(screen.getByText('서비스 55')).toBeInTheDocument();
    expect(screen.queryByText('서비스 66')).not.toBeInTheDocument();
    expect(screen.queryByTestId('schedule-latest-snapshot')).not.toBeInTheDocument();
  });

  it('uses boolean toggle, full list revisions, hard delete, and no localStorage', async () => {
    const initialTodo = {
      id: 1,
      title: '서류 확인',
      completed: false,
      sort_order: 0,
      row_version: 1,
    };
    const completedTodo = { ...initialTodo, completed: true, row_version: 2 };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/v1/schedules?month=2026-08-01') {
        return json(baseScheduleSnapshot({ items: [] }));
      }
      if (url === '/api/v1/personal-todos' && (init?.method ?? 'GET') === 'GET') {
        return json({ list_revision: 1, items: [initialTodo] });
      }
      if (url === '/api/v1/personal-todos/1' && init?.method === 'PATCH') {
        return json({ list_revision: 2, items: [completedTodo] });
      }
      if (url === '/api/v1/personal-todos/1' && init?.method === 'DELETE') {
        return json({ list_revision: 3, items: [] });
      }
      throw new Error(`Unexpected request ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    renderPopup('social-worker');
    fireEvent.click(await screen.findByRole('button', { name: '할 일 완료로 전환' }));
    expect(await screen.findByRole('button', { name: '할 일 미완료로 전환' }))
      .toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: '서류 확인 삭제' }));
    await screen.findByText('등록된 개인 할 일이 없습니다.');

    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'DELETE');
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
      expected_list_revision: 1,
      expected_row_version: 1,
      completed: true,
    });
    expect(JSON.parse(String(deleteCall?.[1]?.body))).toEqual({
      expected_list_revision: 2,
      expected_row_version: 2,
    });
    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });

  it('styles completed personal todos as light gray', () => {
    expect(scheduleCss).toMatch(
      /\.schedule-todo-item\.is-complete\s*\{[^}]*color\s*:\s*#a7a7a7[^}]*opacity\s*:\s*0\.48/,
    );
  });
});

describe('social-worker popup target', () => {
  it('reuses one named target per account and separates different accounts', () => {
    expect(schedulePopupTarget('social-worker', 41)).toBe(
      schedulePopupTarget('social-worker', 41),
    );
    expect(schedulePopupTarget('social-worker', 41)).not.toBe(
      schedulePopupTarget('social-worker', 42),
    );
  });

  it('opens and focuses the same social-worker target for repeated calls', () => {
    const focus = vi.fn();
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window);
    openSchedulePopup('social-worker', '2026-08', 41);
    openSchedulePopup('social-worker', '2026-09', 41);
    expect(open.mock.calls[0][1]).toBe('sswcenter-schedule-social-worker-41');
    expect(open.mock.calls[1][1]).toBe('sswcenter-schedule-social-worker-41');
    expect(focus).toHaveBeenCalledTimes(2);
  });
});
