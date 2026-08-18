import './setup';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import DashboardPage from '../pages/DashboardPage';
import { AuthContext, type AuthContextType } from '../context/AuthContext';
import { UpcomingDeadlines } from '../components/dashboard/UpcomingDeadlines';
import type { RecipientDeadlineItem } from '../services/recipientApi';

const originalFetch = globalThis.fetch;
const appCss = readFileSync(join(__dirname, '..', 'App.css'), 'utf-8');
const editorialCss = readFileSync(join(__dirname, '..', 'styles', 'editorial.css'), 'utf-8');

function json(data: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: status === 204 ? undefined : { 'Content-Type': 'application/json' },
  });
}

function workCard(overrides: Record<string, unknown> = {}) {
  const base = {
    id: 3,
    row_version: 3,
    kind: 'RECOGNITION_EXPIRY',
    assignee_staff_id: 11,
    assignee_staff_name: '박복지',
    display: {
      work_title: '인정만료',
      target_name: '김수급',
      detail: '인정 갱신 준비',
      due_date: '2026-09-30',
      d_day: 48,
    },
  };
  const display = typeof overrides.display === 'object' && overrides.display !== null
    ? overrides.display as Record<string, unknown>
    : {};
  return { ...base, ...overrides, display: { ...base.display, ...display } };
}

function officialResponse(items: unknown[] = []) {
  return {
    as_of_date: '2026-08-13',
    groups: items.length === 0 ? [] : [{ staff_id: 11, staff_name: '박복지', items }],
  };
}

function installDashboardFetch(cards: unknown = officialResponse(), deadlines: unknown[] = []) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith('/api/v1/staff?')) return json({ items: [], total: 0, page: 1, page_size: 200 });
    if (url === '/api/v1/recipients/deadlines') return json({ items: deadlines });
    if (url.startsWith('/api/v1/recipients?')) return json({ items: [], total: 0, page: 1, page_size: 1 });
    if (url === '/api/v1/official-work-cards' && (init?.method ?? 'GET') === 'GET') {
      return json(cards);
    }
    if (url === '/api/v1/official-work-cards/3/close' && init?.method === 'POST') {
      return json(officialResponse());
    }
    if (url === '/api/v1/official-work-cards/eligible-assignees' && (init?.method ?? 'GET') === 'GET') {
      return json({
        as_of_date: '2026-08-13',
        items: [
          { staff_id: 11, staff_name: '박복지' },
          { staff_id: 12, staff_name: '이간호' },
        ],
      });
    }
    if (url === '/api/v1/official-work-cards/3/reassign' && init?.method === 'POST') {
      return json({
        as_of_date: '2026-08-13',
        groups: [{
          staff_id: 12,
          staff_name: '이간호',
          items: [workCard({ assignee_staff_id: 12, assignee_staff_name: '이간호', row_version: 4 })],
        }],
      });
    }
    throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
  });
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
}

function authValue(roleCode: 'ADMIN' | 'USER'): AuthContextType {
  return {
    user: { id: 7, display_name: roleCode === 'ADMIN' ? '관리자' : '사회복지사', role_code: roleCode },
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

function renderDashboard(roleCode: 'ADMIN' | 'USER' = 'USER') {
  return render(
    <AuthContext.Provider value={authValue(roleCode)}>
      <BrowserRouter><DashboardPage /></BrowserRouter>
    </AuthContext.Provider>,
  );
}

function deadline(index: number): RecipientDeadlineItem {
  return {
    recipient_id: index,
    recipient_name: index === 1 ? '   ' : `수급자${index}`,
    kind: 'CONTRACT_EXPIRY',
    source_id: index,
    source_date: '2026-10-31',
    due_date: '2026-09-16',
  };
}

describe('Dashboard W2 contract', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('loads official cards and renders exactly the five display fields', async () => {
    installDashboardFetch(officialResponse([workCard()]));
    renderDashboard();

    const card = await screen.findByTestId('official-work-card');
    expect(card.querySelectorAll('dt')).toHaveLength(5);
    expect(Array.from(card.querySelectorAll('dt')).map((node) => node.textContent)).toEqual([
      '업무제목', '대상자이름', '상세업무', '마감일', 'D-day',
    ]);
    expect(card).toHaveTextContent('김수급');
    expect(card).not.toHaveTextContent('진행률');
    expect(card).not.toHaveTextContent('상태');
    expect(card).not.toHaveTextContent('재개방');
    expect(card.querySelector('input')).not.toBeInTheDocument();
  });

  it('keeps close as a separate control and submits expected row version', async () => {
    const fetchMock = installDashboardFetch(officialResponse([workCard()]));
    renderDashboard('USER');

    fireEvent.click(await screen.findByRole('button', { name: '닫기' }));
    await waitFor(() => expect(screen.getByText('열린 업무카드가 없습니다.')).toBeInTheDocument());

    const closeCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/3/close'));
    expect(closeCall).toBeDefined();
    expect(closeCall?.[1]?.method).toBe('POST');
    expect(JSON.parse(String(closeCall?.[1]?.body))).toEqual({ expected_row_version: 3 });
  });

  it('renders admin groups without close/create/delete/reopen and opens reassignment confirm', async () => {
    const fetchMock = installDashboardFetch({
      as_of_date: '2026-08-13',
      groups: [{ staff_id: 11, staff_name: '박복지', items: [workCard()] }],
    });
    renderDashboard('ADMIN');

    expect(await screen.findByText('박복지')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '닫기' })).not.toBeInTheDocument();
    expect(screen.queryByText('생성')).not.toBeInTheDocument();
    expect(screen.queryByText('삭제')).not.toBeInTheDocument();
    expect(screen.queryByText('재개방')).not.toBeInTheDocument();
    const card = screen.getByTestId('official-work-card');
    expect(card.querySelectorAll('dt')).toHaveLength(5);
    expect(card).not.toHaveTextContent('현재 담당자');

    fireEvent.click(screen.getByRole('button', { name: '담당자 변경' }));
    const dialog = await screen.findByTestId('official-work-card-reassign-dialog');
    expect(dialog).toHaveTextContent('인정만료');
    expect(dialog).toHaveTextContent('김수급');
    expect(dialog).toHaveTextContent('인정 갱신 준비');
    expect(dialog).toHaveTextContent('2026-09-30');
    expect(dialog).toHaveTextContent('박복지');
    fireEvent.change(screen.getByTestId('official-work-card-new-assignee'), {
      target: { value: '12' },
    });
    fireEvent.click(screen.getByTestId('official-work-card-reassign-confirm'));
    await waitFor(() => expect(screen.getByText('이간호')).toBeInTheDocument());
    const reassignCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/3/reassign'));
    expect(reassignCall?.[1]?.method).toBe('POST');
    expect(JSON.parse(String(reassignCall?.[1]?.body))).toEqual({
      expected_row_version: 3,
      assignee_staff_id: 12,
    });
  });

  it('keeps the reassignment dialog and selected assignee on 409 latest snapshot', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) return json({ items: [], total: 0, page: 1, page_size: 200 });
      if (url === '/api/v1/recipients/deadlines') return json({ items: [] });
      if (url.startsWith('/api/v1/recipients?')) return json({ items: [], total: 0, page: 1, page_size: 1 });
      if (url === '/api/v1/official-work-cards' && (init?.method ?? 'GET') === 'GET') {
        return json(officialResponse([workCard()]));
      }
      if (url === '/api/v1/official-work-cards/eligible-assignees') {
        return json({
          as_of_date: '2026-08-13',
          items: [
            { staff_id: 11, staff_name: '박복지' },
            { staff_id: 12, staff_name: '이간호' },
          ],
        });
      }
      if (url === '/api/v1/official-work-cards/3/reassign' && init?.method === 'POST') {
        return json({
          error: { code: 'ROW_VERSION_CONFLICT', message: '먼저 변경됨' },
          details: {
            latest: officialResponse([
              workCard({ row_version: 9, assignee_staff_id: 11, assignee_staff_name: '박복지' }),
            ]),
          },
        }, 409);
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderDashboard('ADMIN');

    fireEvent.click(await screen.findByRole('button', { name: '담당자 변경' }));
    fireEvent.change(await screen.findByTestId('official-work-card-new-assignee'), {
      target: { value: '12' },
    });
    fireEvent.click(screen.getByTestId('official-work-card-reassign-confirm'));

    expect(await screen.findByText('먼저 변경됨')).toBeInTheDocument();
    expect(screen.getByTestId('official-work-card-reassign-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('official-work-card-new-assignee')).toHaveValue('12');
  });

  it('closes an absent-card 409 dialog, announces completion, and leaves no repeat submit control', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) return json({ items: [], total: 0, page: 1, page_size: 200 });
      if (url === '/api/v1/recipients/deadlines') return json({ items: [] });
      if (url.startsWith('/api/v1/recipients?')) return json({ items: [], total: 0, page: 1, page_size: 1 });
      if (url === '/api/v1/official-work-cards') return json(officialResponse([workCard()]));
      if (url === '/api/v1/official-work-cards/eligible-assignees') {
        return json({ as_of_date: '2026-08-13', items: [{ staff_id: 12, staff_name: '이간호' }] });
      }
      if (url === '/api/v1/official-work-cards/3/reassign' && init?.method === 'POST') {
        return json({
          error: { code: 'CARD_ALREADY_CLOSED', message: '이미 완료되었습니다.' },
          details: { latest: officialResponse() },
        }, 409);
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    renderDashboard('ADMIN');

    fireEvent.click(await screen.findByRole('button', { name: '담당자 변경' }));
    const select = await screen.findByTestId('official-work-card-new-assignee');
    await waitFor(() => expect(select).not.toBeDisabled());
    fireEvent.change(select, { target: { value: '12' } });
    fireEvent.click(screen.getByTestId('official-work-card-reassign-confirm'));

    expect(await screen.findByRole('status')).toHaveTextContent('이미 완료되었습니다');
    expect(screen.queryByTestId('official-work-card-reassign-dialog')).not.toBeInTheDocument();
    expect(screen.queryByTestId('official-work-card-reassign-confirm')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/3/reassign'))).toHaveLength(1);
  });

  it('filters the current assignee and makes a current-only candidate list non-submittable', async () => {
    const fetchMock = installDashboardFetch(officialResponse([workCard()]));
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) return json({ items: [], total: 0, page: 1, page_size: 200 });
      if (url === '/api/v1/recipients/deadlines') return json({ items: [] });
      if (url.startsWith('/api/v1/recipients?')) return json({ items: [], total: 0, page: 1, page_size: 1 });
      if (url === '/api/v1/official-work-cards') return json(officialResponse([workCard()]));
      if (url === '/api/v1/official-work-cards/eligible-assignees') {
        return json({ as_of_date: '2026-08-13', items: [{ staff_id: 11, staff_name: '박복지' }] });
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });
    renderDashboard('ADMIN');

    fireEvent.click(await screen.findByRole('button', { name: '담당자 변경' }));
    const select = await screen.findByTestId('official-work-card-new-assignee');
    await waitFor(() => expect(select).toBeDisabled());
    expect(screen.queryByRole('option', { name: '박복지' })).not.toBeInTheDocument();
    expect(screen.getByTestId('official-work-card-reassign-confirm')).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/3/reassign'))).toBe(false);
  });

  it('keeps the dialog safe and cancellable when candidate loading fails', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) return json({ items: [], total: 0, page: 1, page_size: 200 });
      if (url === '/api/v1/recipients/deadlines') return json({ items: [] });
      if (url.startsWith('/api/v1/recipients?')) return json({ items: [], total: 0, page: 1, page_size: 1 });
      if (url === '/api/v1/official-work-cards') return json(officialResponse([workCard()]));
      if (url === '/api/v1/official-work-cards/eligible-assignees') {
        return json({ error: { code: 'UPSTREAM', message: '후보 목록 실패' } }, 503);
      }
      throw new Error(`Unexpected request: ${url}`);
    }) as unknown as typeof fetch;
    renderDashboard('ADMIN');

    fireEvent.click(await screen.findByRole('button', { name: '담당자 변경' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('후보 목록 실패');
    expect(screen.getByTestId('official-work-card-new-assignee')).toBeDisabled();
    expect(screen.getByTestId('official-work-card-reassign-confirm')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    await waitFor(() => expect(screen.queryByTestId('official-work-card-reassign-dialog')).not.toBeInTheDocument());
  });

  it('ignores a canceled stale candidate response and keeps the newer dialog choices', async () => {
    const pending: Array<{ resolve: (response: Response) => void; signal?: AbortSignal }> = [];
    globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) return Promise.resolve(json({ items: [], total: 0, page: 1, page_size: 200 }));
      if (url === '/api/v1/recipients/deadlines') return Promise.resolve(json({ items: [] }));
      if (url.startsWith('/api/v1/recipients?')) return Promise.resolve(json({ items: [], total: 0, page: 1, page_size: 1 }));
      if (url === '/api/v1/official-work-cards') {
        return Promise.resolve(json(officialResponse([workCard(), workCard({ id: 4 })])));
      }
      if (url === '/api/v1/official-work-cards/eligible-assignees') {
        return new Promise<Response>((resolve) => pending.push({ resolve, signal: init?.signal ?? undefined }));
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    }) as unknown as typeof fetch;
    renderDashboard('ADMIN');

    const buttons = await screen.findAllByRole('button', { name: '담당자 변경' });
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(pending).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(pending[0].signal?.aborted).toBe(true);
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(pending).toHaveLength(2));
    await act(async () => {
      pending[1].resolve(json({ as_of_date: '2026-08-13', items: [{ staff_id: 13, staff_name: '최신간호' }] }));
    });
    expect(await screen.findByRole('option', { name: '최신간호' })).toBeInTheDocument();
    await act(async () => {
      pending[0].resolve(json({ as_of_date: '2026-08-13', items: [{ staff_id: 12, staff_name: '오래된간호' }] }));
    });
    expect(screen.queryByRole('option', { name: '오래된간호' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: '최신간호' })).toBeInTheDocument();
  });

  it('contains modal focus, restores the opening button, and marks the background inert', async () => {
    installDashboardFetch(officialResponse([workCard()]));
    renderDashboard('ADMIN');
    const trigger = await screen.findByRole('button', { name: '담당자 변경' });
    fireEvent.click(trigger);
    const dialog = await screen.findByTestId('official-work-card-reassign-dialog');
    const select = screen.getByTestId('official-work-card-new-assignee');
    await waitFor(() => expect(select).not.toBeDisabled());
    expect(document.querySelector('.dashboard-content-grid-w2')).toHaveAttribute('inert');
    expect(Array.from(dialog.querySelectorAll('dt')).map((node) => node.textContent)).toEqual([
      '업무종류', '대상자', '상세업무', '마감일', '현재 담당자',
    ]);
    expect(dialog).toHaveTextContent('인정만료');
    expect(select).toHaveFocus();
    const cancel = screen.getByRole('button', { name: '취소' });
    cancel.focus();
    fireEvent.keyDown(cancel, { key: 'Tab' });
    expect(select).toHaveFocus();
    fireEvent.keyDown(select, { key: 'Tab', shiftKey: true });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('official-work-card-reassign-dialog')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it('shows whitespace-only recipient names as 미입력', async () => {
    installDashboardFetch(officialResponse([workCard({ display: { target_name: '   ' } })]));
    renderDashboard();
    expect(await screen.findByText('미입력')).toBeInTheDocument();
  });

  it('contains no dashboard personal todo or localStorage implementation', async () => {
    installDashboardFetch();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    renderDashboard();

    await screen.findByText('공식 업무카드');
    expect(screen.queryByLabelText('내할일')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText('할일 입력')).not.toBeInTheDocument();
    expect(setItem).not.toHaveBeenCalled();
    expect(getItem).not.toHaveBeenCalled();
  });

  it('starts all four dashboard reads without a waterfall', async () => {
    const started: string[] = [];
    const pending = new Map<string, (response: Response) => void>();
    globalThis.fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      started.push(url);
      return new Promise<Response>((resolve) => pending.set(url, resolve));
    }) as unknown as typeof fetch;

    renderDashboard();
    await waitFor(() => expect(started).toHaveLength(4));
    expect(new Set(started)).toEqual(new Set([
      '/api/v1/staff?page=1&page_size=200',
      '/api/v1/recipients?page=1&page_size=1',
      '/api/v1/recipients/deadlines',
      '/api/v1/official-work-cards',
    ]));

    pending.get('/api/v1/staff?page=1&page_size=200')?.(
      json({ items: [], total: 0, page: 1, page_size: 200 }),
    );
    pending.get('/api/v1/recipients?page=1&page_size=1')?.(
      json({ items: [], total: 9, page: 1, page_size: 1 }),
    );
    pending.get('/api/v1/recipients/deadlines')?.(json({ items: [] }));
    pending.get('/api/v1/official-work-cards')?.(json(officialResponse()));

    await waitFor(() => {
      const summaryCards = document.querySelectorAll('.dashboard-summary-card');
      expect(summaryCards[0].querySelector('.dashboard-summary-count')).toHaveTextContent('0명');
      expect(summaryCards[1].querySelector('.dashboard-summary-count')).toHaveTextContent('9명');
    });
  });

  it('preserves staff and recipient summary links', async () => {
    installDashboardFetch();
    renderDashboard();
    expect(screen.getByRole('link', { name: '직원' })).toHaveAttribute('href', '/staff');
    expect(screen.getByRole('link', { name: '수급자' })).toHaveAttribute('href', '/recipients');
  });

  it('keeps the deadline rail tall enough for at least fifteen rows', () => {
    expect(appCss).toMatch(/\.dashboard-content-grid-w2 \.dashboard-deadline-card\s*\{[^}]*min-height\s*:\s*560px/);
  });

  it('renders summary task grids with a desktop 3-column structure', () => {
    installDashboardFetch();
    renderDashboard();
    const grids = Array.from(document.querySelectorAll('.dashboard-task-grid'));
    expect(grids).toHaveLength(2);
    expect(grids.every((grid) => grid.classList.contains('dashboard-task-grid'))).toBe(true);
  });

  it('preserves the upcoming deadlines section', async () => {
    installDashboardFetch();
    renderDashboard();
    expect(screen.getByText('다가오는 마감일')).toBeInTheDocument();
    expect(await screen.findByText('등록된 수급자 마감일이 없습니다.')).toBeInTheDocument();
    expect(screen.queryByText('센터 시설 안전 점검')).not.toBeInTheDocument();
  });

  it('defines 3-column task grid in CSS source', () => {
    expect(editorialCss).toMatch(
      /\.dashboard-task-grid\s*\{[^}]*grid-template-columns\s*:\s*repeat\(3\s*,\s*minmax\(0\s*,\s*1fr\)\)/,
    );
  });

  it('defines narrow-screen reflow media rule for task grid', () => {
    expect(editorialCss).toMatch(
      /@media\s*\(max-width:\s*780px\)\s*\{[^}]*\.dashboard-task-grid\s*\{[^}]*grid-template-columns\s*:\s*minmax\(0\s*,\s*1fr\)/,
    );
  });

  it('defines app-shell-dashboard min-width:0 override in CSS source', () => {
    expect(editorialCss).toMatch(/\.app-shell-dashboard\s*\{[^}]*min-width\s*:\s*0/);
  });

  it('defines narrow-screen 1-column summary grid at max-width 900px', () => {
    expect(editorialCss).toMatch(
      /@media\s*\(max-width:\s*900px\)\s*\{[^}]*\.dashboard-summary-grid\s*\{[^}]*grid-template-columns\s*:\s*minmax\(0\s*,\s*1fr\)/,
    );
  });

  it('preserves grid-template-areas on summary grid narrow reflow', () => {
    expect(editorialCss).toMatch(
      /@media\s*\(max-width:\s*900px\)\s*\{[^}]*\.dashboard-summary-grid\s*\{[^}]*grid-template-areas\s*:\s*"staff"\s*"recipient"/,
    );
  });

  it('retains successful dashboard data when one of four reads fails', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) {
        return json({ items: [{ id: 2, name: '박성공' }], total: 1, page: 1, page_size: 200 });
      }
      if (url === '/api/v1/recipients/deadlines') {
        return json({ items: [deadline(3)] });
      }
      if (url.startsWith('/api/v1/recipients?')) {
        return json({ error: { code: 'UPSTREAM', message: 'recipient-total-failed' } }, 502);
      }
      if (url === '/api/v1/official-work-cards') {
        return json(officialResponse([workCard()]));
      }
      throw new Error(`Unexpected request ${url}`);
    }) as unknown as typeof fetch;

    renderDashboard();
    await waitFor(() => {
      const summaryCards = document.querySelectorAll('.dashboard-summary-card');
      expect(summaryCards[0].querySelector('.dashboard-summary-count')).toHaveTextContent('1명');
      expect(summaryCards[1].querySelector('.dashboard-summary-count')).toHaveTextContent('…');
    });
    expect(await screen.findByText(/수급자3 · 계약 만료/)).toBeInTheDocument();
    expect(screen.getByTestId('official-work-card')).toHaveTextContent('김수급');
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent('recipient-total-failed');
    expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
  });

  it('renders one alert and de-duplicates messages when multiple reads fail', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith('/api/v1/staff?')) {
        return json({ error: { code: 'STAFF_DOWN', message: 'shared-failure' } }, 502);
      }
      if (url === '/api/v1/recipients/deadlines') {
        return json({ error: { code: 'DEADLINE_DOWN', message: 'shared-failure' } }, 502);
      }
      if (url.startsWith('/api/v1/recipients?')) {
        return json({ error: { code: 'RECIPIENT_DOWN', message: 'recipient-failure' } }, 502);
      }
      if (url === '/api/v1/official-work-cards') {
        return json({ error: { code: 'CARD_DOWN', message: 'card-failure' } }, 502);
      }
      throw new Error(`Unexpected request ${url}`);
    }) as unknown as typeof fetch;

    renderDashboard();
    const alert = await screen.findByRole('alert');
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(alert).toHaveTextContent('shared-failure');
    expect(alert).toHaveTextContent('recipient-failure');
    expect(alert).toHaveTextContent('card-failure');
    expect((alert.textContent ?? '').match(/shared-failure/g)).toHaveLength(1);
  });

  it('does not consume settled dashboard data after unmount and abort', async () => {
    const pending = new Map<string, (response: Response) => void>();
    const capturedSignals: AbortSignal[] = [];
    globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.signal) capturedSignals.push(init.signal);
      return new Promise<Response>((resolve) => pending.set(url, resolve));
    }) as unknown as typeof fetch;

    const { unmount } = renderDashboard();
    await waitFor(() => expect(pending.size).toBe(4));
    expect(capturedSignals).toHaveLength(4);
    expect(capturedSignals.every((signal) => !signal.aborted)).toBe(true);
    unmount();
    expect(capturedSignals.every((signal) => signal.aborted)).toBe(true);

    for (const signal of capturedSignals) {
      Object.defineProperty(signal, 'aborted', {
        configurable: true,
        get: () => false,
      });
    }

    let lateTotalReadCount = 0;
    let decoded = 0;
    const responseLike = (body: unknown) => ({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => {
        decoded += 1;
        return body;
      },
    }) as unknown as Response;
    const lateRecipientBody = {
      items: [],
      page: 1,
      page_size: 1,
      get total() {
        lateTotalReadCount += 1;
        return 88;
      },
    };

    pending.get('/api/v1/staff?page=1&page_size=200')?.(
      responseLike({ items: [], total: 0, page: 1, page_size: 200 }),
    );
    pending.get('/api/v1/recipients?page=1&page_size=1')?.(responseLike(lateRecipientBody));
    pending.get('/api/v1/recipients/deadlines')?.(responseLike({ items: [] }));
    pending.get('/api/v1/official-work-cards')?.(responseLike(officialResponse()));

    await waitFor(() => expect(decoded).toBe(4));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(lateTotalReadCount).toBe(0);
  });

  it('makes dashboard API errors visible instead of CSS-hidden', () => {
    expect(editorialCss).toMatch(/\.dashboard-api-error\s*\{[^}]*display\s*:\s*block/);
    expect(editorialCss).not.toMatch(/\.dashboard-api-error\s*\{[^}]*display\s*:\s*none/);
  });

  it('renders staff and recipient task rows as display-only literal placeholders', () => {
    installDashboardFetch();
    renderDashboard();
    for (const label of [
      '보수교육', '직원상담', '인권교육', '연간교육', '건강검진', '신규교육',
      '상담반영', '반기평가', '서류미비', '인정만료', '계약만료',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText('1nn/1mm')).toHaveLength(7);
    expect(screen.getByText('1nn명')).toBeInTheDocument();
    expect(screen.getAllByText('1nn건')).toHaveLength(3);
    expect(document.querySelectorAll('div.dashboard-task-row')).toHaveLength(11);
    expect(document.querySelectorAll('button.dashboard-task-row-button')).toHaveLength(0);
    expect(screen.queryByTestId('dashboard-ce-incomplete-panel')).not.toBeInTheDocument();
  });

  it('does not lazy-fetch licenses or periodic trainings on dashboard render', async () => {
    const calledUrls: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calledUrls.push(url);
      if (url.startsWith('/api/v1/staff?')) {
        return json({ items: [{ id: 11, name: '초기요양' }], total: 1, page: 1, page_size: 200 });
      }
      if (url === '/api/v1/recipients/deadlines') return json({ items: [] });
      if (url.startsWith('/api/v1/recipients?')) {
        return json({ items: [], total: 0, page: 1, page_size: 1 });
      }
      if (url === '/api/v1/official-work-cards') return json(officialResponse());
      throw new Error(`Unexpected request ${url}`);
    }) as unknown as typeof fetch;

    renderDashboard();
    await waitFor(() => {
      const staffCount = document.querySelector('.dashboard-summary-count');
      expect(staffCount).toHaveTextContent('1명');
    });
    expect(calledUrls.some((url) => url.includes('/licenses'))).toBe(false);
    expect(calledUrls.some((url) => url.includes('/periodic-trainings'))).toBe(false);
    expect(screen.queryByTestId('dashboard-ce-incomplete-panel')).not.toBeInTheDocument();
    expect(screen.getByText('보수교육')).toBeInTheDocument();
  });

  it('retains focus-visible CSS for the dormant task-row button contract', () => {
    expect(editorialCss).toMatch(
      /button\.dashboard-task-row-button:focus-visible\s*\{[^}]*outline\s*:/,
    );
  });
});

describe('UpcomingDeadlines pagination', () => {
  it('shows all fifteen rows without pagination controls', () => {
    render(<UpcomingDeadlines items={Array.from({ length: 15 }, (_, index) => deadline(index + 1))} />);
    expect(screen.getAllByText(/계약 만료$/)).toHaveLength(15);
    expect(screen.queryByRole('navigation', { name: '마감일 페이지' })).not.toBeInTheDocument();
    expect(screen.getByText(/미입력/)).toBeInTheDocument();
  });

  it('shows pagination only beyond fifteen and moves to the next page', () => {
    render(<UpcomingDeadlines items={Array.from({ length: 16 }, (_, index) => deadline(index + 1))} />);
    expect(screen.getByRole('navigation', { name: '마감일 페이지' })).toBeInTheDocument();
    expect(screen.getAllByText(/계약 만료$/)).toHaveLength(15);
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(screen.getAllByText(/계약 만료$/)).toHaveLength(1);
  });
});
