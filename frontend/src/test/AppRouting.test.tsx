import './setup';
import { render, screen, waitFor } from '@testing-library/react';
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
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({}),
      } as Response);
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
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
});
