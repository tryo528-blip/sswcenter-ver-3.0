import './setup';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import SchedulePopupPage from '../pages/SchedulePopupPage';
import { AuthContext, type AuthContextType } from '../context/AuthContext';
import { openSchedulePopup, schedulePopupTarget } from '../components/schedule/schedulePopups';

const originalFetch = globalThis.fetch;
const scheduleCss = readFileSync(join(__dirname, '..', 'styles', 'schedule.css'), 'utf-8');

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
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
