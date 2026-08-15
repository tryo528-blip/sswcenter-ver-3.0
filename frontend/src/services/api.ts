export interface UserAccount {
  id: number;
  display_name: string;
  role_code: string;
}

export interface BootstrapStatusResponse {
  bootstrap_required: boolean;
}

export interface BootstrapPayload {
  center_name: string;
  admin_name: string;
  birth_date: string;
  sex_code: string;
  start_date: string;
  pin: string;
}

export interface BootstrapResponse {
  status: string;
  account: UserAccount;
}

export interface LoginResponse {
  account: UserAccount;
}

export interface MeResponse {
  account: UserAccount;
}

export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|; )\s*sswcenter_csrf\s*=\s*([^;]+)/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

export function validatePin(pin: string): { isValid: boolean; message?: string } {
  if (!pin) {
    return { isValid: false, message: 'PIN 번호를 입력해주세요.' };
  }
  if (!/^\d+$/.test(pin)) {
    return { isValid: false, message: 'PIN 번호는 숫자만 입력 가능합니다.' };
  }
  if (pin.length !== 6) {
    return { isValid: false, message: 'PIN 번호는 6자리여야 합니다.' };
  }
  return { isValid: true };
}

export const AUTH_UNAUTHORIZED_EVENT = 'sswcenter:unauthorized';
export const AUTH_SESSION_CHANGED_EVENT = 'sswcenter:session-changed';
export const AUTH_SESSION_READY_EVENT = 'sswcenter:session-ready';

let authGeneration = 0;

export function beginAuthTransition(): void {
  authGeneration += 1;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
  }
}

export function markAuthReady(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(AUTH_SESSION_READY_EVENT));
  }
}

function staleRequestError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('Authentication session changed', 'AbortError');
  }
  const error = new Error('Authentication session changed');
  error.name = 'AbortError';
  return error;
}

/** Optional structured error details from the API error envelope. */
export type ApiErrorDetails = {
  current_row_version?: number;
  entity?: string;
  [key: string]: unknown;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: ApiErrorDetails;

  constructor(
    message: string,
    status: number,
    code?: string,
    details?: ApiErrorDetails,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export type ApiResponseDecoder = (response: Response) => Promise<unknown>;

export async function apiRequest<T>(
  url: string,
  options: RequestInit = {},
  decodeResponse?: ApiResponseDecoder,
): Promise<T> {
  const requestGeneration = authGeneration;
  const headers = new Headers(options.headers || {});

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const csrfToken = getCsrfToken();
  if (csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }

  const config: RequestInit = {
    ...options,
    headers,
    credentials: 'include',
  };

  if (options.signal?.aborted) {
    throw staleRequestError();
  }

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (error) {
    if (options.signal?.aborted) {
      throw staleRequestError();
    }
    throw error;
  }

  if (options.signal?.aborted || requestGeneration !== authGeneration) {
    throw staleRequestError();
  }

  if (!response.ok) {
    let errorDetail = '오류가 발생했습니다.';
    let errorCode: string | undefined;
    let errorDetails: ApiErrorDetails | undefined;
    try {
      const errorData = await response.json();
      if (errorData?.error?.code) {
        errorCode = errorData.error.code;
        errorDetail = errorData.error.message || errorCode;
      } else if (errorData?.detail?.message) {
        errorDetail = errorData.detail.message;
      } else if (errorData?.detail?.code) {
        errorCode = errorData.detail.code;
        errorDetail = errorData.detail.code;
      }
      if (errorData?.details && typeof errorData.details === 'object') {
        errorDetails = errorData.details as ApiErrorDetails;
      }
    } catch {
      // ignore json parse error
    }

    if (options.signal?.aborted || requestGeneration !== authGeneration) {
      throw staleRequestError();
    }

    if (
      response.status === 401 &&
      url !== '/api/bootstrap/status' &&
      url !== '/api/auth/login' &&
      url !== '/api/auth/me' &&
      requestGeneration === authGeneration &&
      typeof window !== 'undefined'
    ) {
      beginAuthTransition();
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
    throw new ApiError(errorDetail, response.status, errorCode, errorDetails);
  }

  if (options.signal?.aborted || requestGeneration !== authGeneration) {
    throw staleRequestError();
  }

  if (response.status === 204) {
    return {} as T;
  }

  let data: unknown;
  try {
    data = decodeResponse ? await decodeResponse(response) : await response.json();
  } catch (error) {
    if (options.signal?.aborted) {
      throw staleRequestError();
    }
    throw error;
  }
  if (options.signal?.aborted || requestGeneration !== authGeneration) {
    throw staleRequestError();
  }
  return data as T;
}

export async function fetchBootstrapStatus(): Promise<BootstrapStatusResponse> {
  return apiRequest<BootstrapStatusResponse>('/api/bootstrap/status', { method: 'GET' });
}

export async function postBootstrap(payload: BootstrapPayload): Promise<BootstrapResponse> {
  return apiRequest<BootstrapResponse>('/api/bootstrap', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function postLogin(pin: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ pin }),
  });
}

export async function getMe(): Promise<MeResponse> {
  return apiRequest<MeResponse>('/api/auth/me', { method: 'GET' });
}

export async function postLogout(): Promise<void> {
  return apiRequest<void>('/api/auth/logout', { method: 'POST' });
}
