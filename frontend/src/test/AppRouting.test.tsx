import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import App from '../App';

describe('App Routing Integration', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (urlStr.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            account: { id: 1, display_name: '테스트관리자', role_code: 'ADMIN' },
          }),
        } as Response);
      }
      if (urlStr === '/api/v1/schedules?month=2026-08-01') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            schedule_month: '2026-08-01',
            finalized: false,
            finalized_at_utc: null,
            row_version: 1,
            items: [],
          }),
        } as Response);
      }
      if (urlStr === '/api/v1/official-work-cards') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ as_of_date: '2026-08-13', groups: [] }),
        } as Response);
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({}),
      } as Response);
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    window.history.replaceState({}, '', '/');
  });

  it('renders app shell and defaults to dashboard route when authenticated', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('app-shell')).toBeInTheDocument();
      expect(screen.getByTestId('app-sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('app-header')).toBeInTheDocument();
      expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
      expect(screen.getByTestId('header-user-name')).toHaveTextContent('테스트관리자');
    });
  });

  it('renders SchedulePopupPage through the real authenticated App route', async () => {
    window.history.replaceState({}, '', '/schedules/social-worker?month=2026-08');
    render(<App />);

    expect(await screen.findByTestId('schedule-popup-social-worker')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '월간 일정표' })).toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/v1/schedules?month=2026-08-01',
        expect.objectContaining({ method: 'GET' }),
      );
    });
  });

  it('opens the real schedule route from the social-worker menu navigation', async () => {
    const focus = vi.fn();
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window);
    window.history.replaceState({}, '', '/social-workers');
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: '사회복지사 일정표 열기' }));
    expect(open).toHaveBeenCalledWith(
      expect.stringMatching(/^\/schedules\/social-worker\?month=\d{4}-\d{2}$/),
      'sswcenter-schedule-social-worker-1',
      expect.stringContaining('popup=yes'),
    );
    expect(focus).toHaveBeenCalledOnce();
  });
});
