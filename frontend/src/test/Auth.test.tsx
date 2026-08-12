import './setup';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import App from '../App';
import {
  apiRequest,
  AUTH_SESSION_READY_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  beginAuthTransition,
  validatePin,
  getCsrfToken,
} from '../services/api';

describe('PIN Validation Logic', () => {
  it('rejects empty, non-numeric, or short PINs', () => {
    expect(validatePin('').isValid).toBe(false);
    expect(validatePin('12345').isValid).toBe(false);
    expect(validatePin('abcdef').isValid).toBe(false);
    expect(validatePin('123a56').isValid).toBe(false);
  });

  it('accepts exactly six numeric PIN digits', () => {
    expect(validatePin('123456').isValid).toBe(true);
    expect(validatePin('000000').isValid).toBe(true);
    expect(validatePin('12345').isValid).toBe(false);
    expect(validatePin('1234567').isValid).toBe(false);
  });
});

describe('CSRF Token Helper', () => {
  it('extracts sswcenter_csrf from document.cookie', () => {
    document.cookie = 'sswcenter_csrf=token_12345; path=/';
    expect(getCsrfToken()).toBe('token_12345');
    document.cookie = 'sswcenter_csrf=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
  });
});

describe('Authentication request generations', () => {
  it('ignores a delayed stale 401 after the account transition', async () => {
    let resolveRequest: ((response: Response) => void) | undefined;
    const unauthorized = vi.fn();
    window.addEventListener('sswcenter:unauthorized', unauthorized);
    globalThis.fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveRequest = resolve;
        }),
    );

    const request = apiRequest('/api/v1/staff', { method: 'GET' });
    beginAuthTransition();
    resolveRequest?.(
      new Response(JSON.stringify({ error: { code: 'SESSION_REQUIRED' } }), { status: 401 }),
    );

    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(unauthorized).not.toHaveBeenCalled();
    window.removeEventListener('sswcenter:unauthorized', unauthorized);
  });

  it('rejects a response that becomes stale while response.json is still parsing', async () => {
    let resolveJson: ((value: unknown) => void) | undefined;
    const json = vi.fn(
      () =>
        new Promise<unknown>((resolve) => {
          resolveJson = resolve;
        }),
    );
    const response = new Response(null, { status: 200 });
    Object.defineProperty(response, 'json', { value: json });
    globalThis.fetch = vi.fn().mockResolvedValue(response);

    const request = apiRequest('/api/v1/staff', { method: 'GET' });
    await waitFor(() => expect(json).toHaveBeenCalledTimes(1));

    beginAuthTransition();
    resolveJson?.({ account: { id: 99, display_name: 'stale-json', role_code: 'ADMIN' } });

    await expect(
      request,
      'F3_API_REQUEST_STALE_DURING_JSON_PARSE',
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('Auth Gate & Bootstrap / Login / Logout Flow', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    document.cookie = 'sswcenter_csrf=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    window.history.replaceState({}, '', '/');
  });

  it('renders BootstrapForm when bootstrap_required is true', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: true }),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('bootstrap-container')).toBeInTheDocument();
    });

    expect(screen.getByTestId('bootstrap-center-name')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-admin-name')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-birth-date')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-sex-code')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-start-date')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-pin')).toBeInTheDocument();
    expect(screen.getByTestId('bootstrap-confirm-pin')).toBeInTheDocument();
  });

  it('validates PIN mismatch in BootstrapForm', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: true }),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('bootstrap-form')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('bootstrap-center-name'), { target: { value: '행복주간보호센터' } });
    fireEvent.change(screen.getByTestId('bootstrap-admin-name'), { target: { value: '김관리' } });
    fireEvent.change(screen.getByTestId('bootstrap-sex-code'), { target: { value: 'FEMALE' } });
    fireEvent.change(screen.getByTestId('bootstrap-birth-date'), { target: { value: '1980-01-01' } });
    fireEvent.change(screen.getByTestId('bootstrap-start-date'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByTestId('bootstrap-pin'), { target: { value: '123456' } });
    fireEvent.change(screen.getByTestId('bootstrap-confirm-pin'), { target: { value: '654321' } });

    fireEvent.click(screen.getByTestId('bootstrap-submit-btn'));

    expect(screen.getByTestId('bootstrap-error')).toHaveTextContent('PIN 번호가 일치하지 않습니다.');
  });

  it('submits BootstrapForm with credentials: include and X-CSRF-Token, then transitions to PIN login screen', async () => {
    document.cookie = 'sswcenter_csrf=csrf_abc123; path=/';
    let bootstrapPayload: any = null;
    let requestHeaders: Headers | null = null;
    let fetchCredentials: string | null = null;

    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: true }),
        } as Response);
      }
      if (url.includes('/api/bootstrap')) {
        bootstrapPayload = JSON.parse(init?.body as string);
        requestHeaders = new Headers(init?.headers);
        fetchCredentials = (init?.credentials as string) || null;
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () => Promise.resolve({
            status: 'created',
            account: { id: 10, display_name: '김관리', role_code: 'ADMIN' },
          }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('bootstrap-form')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('bootstrap-center-name'), { target: { value: '행복주간보호센터' } });
    fireEvent.change(screen.getByTestId('bootstrap-admin-name'), { target: { value: '김관리' } });
    fireEvent.change(screen.getByTestId('bootstrap-sex-code'), { target: { value: 'FEMALE' } });
    fireEvent.change(screen.getByTestId('bootstrap-birth-date'), { target: { value: '1980-01-01' } });
    fireEvent.change(screen.getByTestId('bootstrap-start-date'), { target: { value: '2026-01-01' } });
    fireEvent.change(screen.getByTestId('bootstrap-pin'), { target: { value: '123456' } });
    fireEvent.change(screen.getByTestId('bootstrap-confirm-pin'), { target: { value: '123456' } });

    fireEvent.click(screen.getByTestId('bootstrap-submit-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('login-container')).toBeInTheDocument();
    });

    expect(bootstrapPayload).toEqual({
      center_name: '행복주간보호센터',
      admin_name: '김관리',
      birth_date: '1980-01-01',
      sex_code: 'FEMALE',
      start_date: '2026-01-01',
      pin: '123456',
    });
    expect(requestHeaders?.get('X-CSRF-Token')).toBe('csrf_abc123');
    expect(fetchCredentials).toBe('include');
  });

  it('handles 401 on login silently without leaking sensitive logs', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
      }
      if (url.includes('/api/auth/login')) {
        return Promise.resolve({
          ok: false,
          status: 401,
          json: () => Promise.resolve({ detail: { code: 'authentication_failed' } }),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('login-form')).toBeInTheDocument();
    });
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-submit-btn')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('login-pin-input'), { target: { value: '999999' } });

    await waitFor(() => {
      expect(
        vi.mocked(globalThis.fetch).mock.calls.some(([url]) => String(url).includes('/api/auth/login')),
      ).toBe(true);
    });
    expect(screen.queryByTestId('login-error')).not.toBeInTheDocument();
    expect(screen.getByTestId('login-pin-input')).toHaveValue('999999');
    expect(screen.getByTestId('login-pin-input')).not.toHaveClass('auth-login-input-error');
    expect(screen.getByTestId('login-pin-input')).toHaveAttribute('aria-invalid', 'false');

    // Ensure PIN was not logged to console
    const loggedStr = consoleSpy.mock.calls.flat().join(' ');
    expect(loggedStr).not.toContain('999999');

    consoleSpy.mockRestore();
  });

  it('has no form or Enter submit path and submits only on the sixth digit', async () => {
    let loginCalls = 0;
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
      }
      if (url.includes('/api/auth/login')) {
        loginCalls += 1;
        return Promise.resolve({
          ok: false,
          status: 401,
          json: () => Promise.resolve({ detail: { code: 'authentication_failed' } }),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);
    const loginPanel = await screen.findByTestId('login-form');
    const pinInput = screen.getByTestId('login-pin-input');

    fireEvent.change(pinInput, { target: { value: '12345' } });
    fireEvent.keyDown(pinInput, { key: 'Enter', code: 'Enter' });
    await Promise.resolve();
    expect(loginCalls).toBe(0);

    fireEvent.change(pinInput, { target: { value: '123456' } });
    await waitFor(() => expect(loginCalls).toBe(1));

    fireEvent.submit(loginPanel);
    await Promise.resolve();
    expect(loginCalls).toBe(1);
    expect(loginPanel.tagName).toBe('DIV');
  });

  it('treats the initial /api/auth/me 401 as anonymous without broadcasting unauthorized', async () => {
    const unauthorized = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorized);

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('login-form')).toBeInTheDocument();
    });
    expect(unauthorized).not.toHaveBeenCalled();

    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorized);
  });

  it('does not install a delayed login response after an account transition', async () => {
    let resolveLogin: ((response: Response) => void) | undefined;

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
      }
      if (url.includes('/api/auth/login')) {
        return new Promise<Response>((resolve) => {
          resolveLogin = resolve;
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('login-form')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('login-pin-input'), { target: { value: '123456' } });
    await waitFor(() => expect(resolveLogin).toBeDefined());

    beginAuthTransition();
    resolveLogin?.(
      new Response(
        JSON.stringify({
          account: { id: 99, display_name: 'stale-account', role_code: 'ADMIN' },
        }),
        { status: 200 },
      ),
    );

    await waitFor(() => {
      expect(screen.getByTestId('login-form')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('app-shell')).not.toBeInTheDocument();
    expect(screen.queryByText('stale-account')).not.toBeInTheDocument();
  });

  it('performs full login and logout sequence', async () => {
    document.cookie = 'sswcenter_csrf=csrf_xyz789; path=/';
    let loggedIn = false;
    let logoutCalled = false;

    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        if (loggedIn) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve({
              account: { id: 1, display_name: '홍길동 원장', role_code: 'ADMIN' },
            }),
          } as Response);
        }
        return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) } as Response);
      }
      if (url.includes('/api/auth/login')) {
        loggedIn = true;
        const headers = new Headers(init?.headers);
        expect(headers.get('X-CSRF-Token')).toBe('csrf_xyz789');
        expect(init?.credentials).toBe('include');

        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            account: { id: 1, display_name: '홍길동 원장', role_code: 'ADMIN' },
          }),
        } as Response);
      }
      if (url.includes('/api/auth/logout')) {
        logoutCalled = true;
        loggedIn = false;
        const headers = new Headers(init?.headers);
        expect(headers.get('X-CSRF-Token')).toBe('csrf_xyz789');
        expect(init?.credentials).toBe('include');

        return Promise.resolve({
          ok: true,
          status: 204,
          json: () => Promise.resolve({}),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('login-form')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('login-pin-input'), { target: { value: '123456' } });

    await waitFor(() => {
      expect(screen.getByTestId('app-shell')).toBeInTheDocument();
    });

    expect(screen.getByTestId('header-user-name')).toHaveTextContent('홍길동 원장');

    // Click logout button
    fireEvent.click(screen.getByTestId('sidebar-logout'));

    await waitFor(() => {
      expect(screen.getByTestId('login-form')).toBeInTheDocument();
    });

    expect(logoutCalled).toBe(true);
  });

  it('ends the auth loading state when the actual logout receives 401', async () => {
    const residentNumber = ['900', '101', '-', '123', '4567'].join('');
    let resolveLogout: ((response: Response) => void) | undefined;
    const unauthorized = vi.fn();
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorized);

    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            account: { id: 1, display_name: '홍길동 원장', role_code: 'ADMIN' },
          }),
        } as Response);
      }
      if (url.includes('/api/v1/session-capabilities')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
        } as Response);
      }
      if (url.includes('/api/v1/staff')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 100 }),
        } as Response);
      }
      if (url.includes('/api/auth/logout')) {
        return new Promise<Response>((resolve) => {
          resolveLogout = resolve;
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    window.history.replaceState({}, '', '/staff');
    render(<App />);
    await waitFor(() => expect(screen.getByTestId('app-shell')).toBeInTheDocument());
    await screen.findByRole('button', { name: /신규 직원 등록/i });
    fireEvent.click(screen.getByRole('button', { name: /신규 직원 등록/i }));
    fireEvent.change(screen.getByLabelText('주민등록번호'), {
      target: { value: residentNumber },
    });

    fireEvent.click(screen.getByTestId('sidebar-logout'));
    await waitFor(() => expect(resolveLogout).toBeDefined());
    expect(screen.getByTestId('auth-loading')).toBeInTheDocument();
    expect(screen.queryByDisplayValue(residentNumber)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(residentNumber);

    resolveLogout?.(
      new Response(JSON.stringify({ detail: { code: 'SESSION_REQUIRED' } }), { status: 401 }),
    );

    await waitFor(() => expect(screen.getByTestId('login-form')).toBeInTheDocument());
    expect(screen.queryByTestId('auth-loading')).not.toBeInTheDocument();
    expect(unauthorized).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, unauthorized);
  });

  it('restores the session-ready state after an actual logout 5xx failure', async () => {
    const ready = vi.fn();
    window.addEventListener(AUTH_SESSION_READY_EVENT, ready);
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            account: { id: 1, display_name: '홍길동 원장', role_code: 'ADMIN' },
          }),
        } as Response);
      }
      if (url.includes('/api/auth/logout')) {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: () => Promise.resolve({ detail: { code: 'logout_unavailable' } }),
        } as Response);
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);
    await waitFor(() => expect(screen.getByTestId('app-shell')).toBeInTheDocument());
    expect(screen.getByTestId('header-user-name')).toHaveTextContent('홍길동 원장');

    fireEvent.click(screen.getByTestId('sidebar-logout'));

    await waitFor(() => {
      expect(screen.getByTestId('app-header')).toHaveTextContent(
        '로그아웃에 실패했습니다. 연결을 확인한 뒤 다시 시도해주세요.',
      );
    });
    expect(screen.getByTestId('app-shell')).toBeInTheDocument();
    expect(screen.getByTestId('header-user-name')).toHaveTextContent('홍길동 원장');
    expect(screen.queryByTestId('auth-loading')).not.toBeInTheDocument();
    expect(ready).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_SESSION_READY_EVENT, ready);
  });

  it('restores the session-ready state after an actual logout network failure', async () => {
    const ready = vi.fn();
    window.addEventListener(AUTH_SESSION_READY_EVENT, ready);
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            account: { id: 1, display_name: '홍길동 원장', role_code: 'ADMIN' },
          }),
        } as Response);
      }
      if (url.includes('/api/auth/logout')) {
        return Promise.reject(new Error('network unavailable'));
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
    });

    render(<App />);
    await waitFor(() => expect(screen.getByTestId('app-shell')).toBeInTheDocument());
    expect(screen.getByTestId('header-user-name')).toHaveTextContent('홍길동 원장');

    fireEvent.click(screen.getByTestId('sidebar-logout'));

    await waitFor(() => {
      expect(screen.getByTestId('app-header')).toHaveTextContent(
        '로그아웃에 실패했습니다. 연결을 확인한 뒤 다시 시도해주세요.',
      );
    });
    expect(screen.getByTestId('app-shell')).toBeInTheDocument();
    expect(screen.getByTestId('header-user-name')).toHaveTextContent('홍길동 원장');
    expect(screen.queryByTestId('auth-loading')).not.toBeInTheDocument();
    expect(ready).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_SESSION_READY_EVENT, ready);
  });

  it('hides ADMIN settings from USER and redirects direct access', async () => {
    globalThis.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/api/bootstrap/status')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ bootstrap_required: false }),
        } as Response);
      }
      if (url.includes('/api/auth/me')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              account: { id: 2, display_name: '합성 일반 사용자', role_code: 'USER' },
            }),
        } as Response);
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({}),
      } as Response);
    });
    window.history.replaceState({}, '', '/settings');

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('page-dashboard')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('sidebar-item-settings')).not.toBeInTheDocument();
    expect(screen.queryByTestId('page-settings')).not.toBeInTheDocument();
    expect(window.location.pathname).toBe('/dashboard');
  });
});
