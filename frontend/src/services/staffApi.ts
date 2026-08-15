import type { components } from '../generated/sswcenter-api';
import {
  ApiError,
  AUTH_SESSION_CHANGED_EVENT,
  AUTH_UNAUTHORIZED_EVENT,
  beginAuthTransition,
  getCsrfToken,
  apiRequest,
} from './api';

type Schemas = components['schemas'];

export type StaffCreateRequest = Schemas['StaffCreateRequest'];
export type StaffCreateResponse = Schemas['StaffCreateResponse'];
export type StaffDetailResponse = Schemas['StaffDetailResponse'];
export type StaffResponse = Schemas['StaffResponse'];
export type StaffEmploymentCloseRequest = Schemas['StaffEmploymentCloseRequest'];
export type StaffEmploymentCreateRequest = Schemas['StaffEmploymentCreateRequest'];
export type StaffListResponse = Schemas['StaffListResponse'];
export type SensitiveIdentityRevealResponse = Schemas['SensitiveIdentityRevealResponse'];
export type SessionCapabilitiesResponse = Schemas['SessionCapabilitiesResponse'];
export type ServiceCatalogResponse = Schemas['ServiceCatalogResponse'];
export type LicenseTypeListResponse = Schemas['LicenseTypeListResponse'];
export type StaffLicenseCreateRequest = Schemas['StaffLicenseCreateRequest'];
export type StaffLicenseInvalidateRequest = Schemas['StaffLicenseInvalidateRequest'];
export type StaffLicenseListResponse = Schemas['StaffLicenseListResponse'];
export type StaffLicenseReplacementRequest = Schemas['StaffLicenseReplacementRequest'];
export type StaffLicenseResponse = Schemas['StaffLicenseResponse'];
export type StaffServiceQualificationCloseRequest =
  Schemas['StaffServiceQualificationCloseRequest'];
export type StaffServiceQualificationCreateRequest =
  Schemas['StaffServiceQualificationCreateRequest'];
export type StaffServiceQualificationInvalidateRequest =
  Schemas['StaffServiceQualificationInvalidateRequest'];
export type StaffServiceQualificationListResponse =
  Schemas['StaffServiceQualificationListResponse'];
export type StaffServiceQualificationReplacementRequest =
  Schemas['StaffServiceQualificationReplacementRequest'];
export type StaffServiceQualificationResponse =
  Schemas['StaffServiceQualificationResponse'];
export type TrainingCourseListResponse = Schemas['TrainingCourseListResponse'];
export type TrainingCourseResponse = Schemas['TrainingCourseResponse'];
export type StaffOnboardingTrainingListResponse =
  Schemas['StaffOnboardingTrainingListResponse'];
export type StaffOnboardingTrainingResponse = Schemas['StaffOnboardingTrainingResponse'];
export type StaffOnboardingTrainingUpdateRequest =
  Schemas['StaffOnboardingTrainingUpdateRequest'];
export type StaffPeriodicTrainingListResponse =
  Schemas['StaffPeriodicTrainingListResponse'];
export type StaffPeriodicTrainingResponse = Schemas['StaffPeriodicTrainingResponse'];
export type StaffPeriodicTrainingCreateRequest =
  Schemas['StaffPeriodicTrainingCreateRequest'];
export type StaffPeriodicTrainingUpdateRequest =
  Schemas['StaffPeriodicTrainingUpdateRequest'];
export type StaffPeriodicTrainingInvalidateRequest =
  Schemas['StaffPeriodicTrainingInvalidateRequest'];
export type StaffHealthCheckCreateRequest = Schemas['StaffHealthCheckCreateRequest'];
export type StaffHealthCheckListResponse = Schemas['StaffHealthCheckListResponse'];
export type StaffHealthCheckResponse = Schemas['StaffHealthCheckResponse'];
export type StaffHealthCheckUpdateRequest = Schemas['StaffHealthCheckUpdateRequest'];
export type StaffQuarterlyConsultationCreateRequest =
  Schemas['StaffQuarterlyConsultationCreateRequest'];
export type StaffQuarterlyConsultationListResponse =
  Schemas['StaffQuarterlyConsultationListResponse'];
export type StaffQuarterlyConsultationResponse =
  Schemas['StaffQuarterlyConsultationResponse'];
export type StaffQuarterlyConsultationUpdateRequest =
  Schemas['StaffQuarterlyConsultationUpdateRequest'];

export type HealthFieldError = {
  field: string;
  message: string;
};

export class HealthApiError extends ApiError {
  readonly fieldErrors: HealthFieldError[];

  constructor(
    message: string,
    status: number,
    code: string | undefined,
    fieldErrors: HealthFieldError[] = [],
  ) {
    super(message, status, code);
    this.name = 'HealthApiError';
    this.fieldErrors = fieldErrors;
  }
}

export type ConsultationFieldError = {
  field: string;
  message: string;
};

export class ConsultationApiError extends ApiError {
  readonly fieldErrors: ConsultationFieldError[];

  constructor(
    message: string,
    status: number,
    code: string | undefined,
    fieldErrors: ConsultationFieldError[] = [],
  ) {
    super(message, status, code);
    this.name = 'ConsultationApiError';
    this.fieldErrors = fieldErrors;
  }
}

let healthSessionGeneration = 0;
let healthSessionListenerInstalled = false;
let consultationSessionGeneration = 0;
let consultationSessionListenerInstalled = false;

function ensureHealthSessionListener(): void {
  if (healthSessionListenerInstalled || typeof window === 'undefined') return;
  window.addEventListener(AUTH_SESSION_CHANGED_EVENT, () => {
    healthSessionGeneration += 1;
  });
  healthSessionListenerInstalled = true;
}

function ensureConsultationSessionListener(): void {
  if (consultationSessionListenerInstalled || typeof window === 'undefined') return;
  window.addEventListener(AUTH_SESSION_CHANGED_EVENT, () => {
    consultationSessionGeneration += 1;
  });
  consultationSessionListenerInstalled = true;
}

function staleHealthRequestError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('Health-check session changed', 'AbortError');
  }
  const error = new Error('Health-check session changed');
  error.name = 'AbortError';
  return error;
}

function staleConsultationRequestError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('Quarterly consultation session changed', 'AbortError');
  }
  const error = new Error('Quarterly consultation session changed');
  error.name = 'AbortError';
  return error;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

async function healthRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  ensureHealthSessionListener();
  const requestGeneration = healthSessionGeneration;
  const headers = new Headers(options.headers || {});

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const csrfToken = getCsrfToken();
  if (csrfToken) headers.set('X-CSRF-Token', csrfToken);

  const config: RequestInit = {
    ...options,
    credentials: 'include',
    headers,
  };

  if (options.signal?.aborted) throw staleHealthRequestError();

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (error) {
    if (options.signal?.aborted || requestGeneration !== healthSessionGeneration) {
      throw staleHealthRequestError();
    }
    throw error;
  }

  if (options.signal?.aborted || requestGeneration !== healthSessionGeneration) {
    throw staleHealthRequestError();
  }

  if (!response.ok) {
    let body: Record<string, unknown> = {};
    try {
      body = recordValue(await response.json());
    } catch {
      // Keep the public error generic when the server does not return JSON.
    }
    const errorBody = recordValue(body.error);
    const detail = recordValue(body.detail);
    const fieldErrors = Array.isArray(body.field_errors)
      ? body.field_errors.flatMap((candidate) => {
          const item = recordValue(candidate);
          const field = stringValue(item.field);
          const message = stringValue(item.message);
          return field && message ? [{ field, message }] : [];
        })
      : [];
    const errorCode = stringValue(errorBody.code) ?? stringValue(detail.code);
    const message =
      stringValue(errorBody.message) ??
      stringValue(detail.message) ??
      '검진 요청을 처리하지 못했습니다.';

    if (
      response.status === 401 &&
      requestGeneration === healthSessionGeneration &&
      typeof window !== 'undefined'
    ) {
      beginAuthTransition();
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
    throw new HealthApiError(message, response.status, errorCode, fieldErrors);
  }

  if (options.signal?.aborted || requestGeneration !== healthSessionGeneration) {
    throw staleHealthRequestError();
  }
  if (response.status === 204) return {} as T;

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error('검진 응답을 처리하지 못했습니다.');
  }
}

async function consultationRequest<T>(url: string, options: RequestInit = {}): Promise<T> {
  ensureConsultationSessionListener();
  const requestGeneration = consultationSessionGeneration;
  const headers = new Headers(options.headers || {});

  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const csrfToken = getCsrfToken();
  if (csrfToken) headers.set('X-CSRF-Token', csrfToken);

  const config: RequestInit = {
    ...options,
    credentials: 'include',
    headers,
  };

  if (options.signal?.aborted) throw staleConsultationRequestError();

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (error) {
    if (options.signal?.aborted || requestGeneration !== consultationSessionGeneration) {
      throw staleConsultationRequestError();
    }
    throw error;
  }

  if (options.signal?.aborted || requestGeneration !== consultationSessionGeneration) {
    throw staleConsultationRequestError();
  }

  if (!response.ok) {
    let body: Record<string, unknown> = {};
    try {
      body = recordValue(await response.json());
    } catch {
      // Keep the public error generic when the server does not return JSON.
    }
    const errorBody = recordValue(body.error);
    const detail = recordValue(body.detail);
    const fieldErrors = Array.isArray(body.field_errors)
      ? body.field_errors.flatMap((candidate) => {
          const item = recordValue(candidate);
          const field = stringValue(item.field);
          const message = stringValue(item.message);
          return field && message ? [{ field, message }] : [];
        })
      : [];
    const errorCode = stringValue(errorBody.code) ?? stringValue(detail.code);
    const message =
      stringValue(errorBody.message) ??
      stringValue(detail.message) ??
      '분기상담 요청을 처리하지 못했습니다.';

    if (
      response.status === 401 &&
      requestGeneration === consultationSessionGeneration &&
      typeof window !== 'undefined'
    ) {
      beginAuthTransition();
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
    }
    throw new ConsultationApiError(message, response.status, errorCode, fieldErrors);
  }

  if (options.signal?.aborted || requestGeneration !== consultationSessionGeneration) {
    throw staleConsultationRequestError();
  }
  if (response.status === 204) return {} as T;

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error('분기상담 응답을 처리하지 못했습니다.');
  }
}

export async function fetchSessionCapabilities(
  signal?: AbortSignal,
): Promise<SessionCapabilitiesResponse> {
  return apiRequest<SessionCapabilitiesResponse>('/api/v1/session-capabilities', {
    method: 'GET',
    cache: 'no-store',
    signal,
  });
}

export async function fetchStaffList(
  search: string,
  signal?: AbortSignal,
  page = 1,
): Promise<StaffListResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: '1' });
  if (search.trim()) {
    params.set('search', search.trim());
  }
  return apiRequest<StaffListResponse>(`/api/v1/staff?${params.toString()}`, {
    method: 'GET',
    signal,
  });
}

export interface StaffPageOptions {
  search?: string;
  page?: number;
  pageSize?: number;
  signal?: AbortSignal;
}

/**
 * Fetch a single page of staff with configurable page size.
 * Keeps existing fetchStaffList compatible while allowing callers
 * to request larger (or smaller) pages.
 */
export async function fetchStaffPage(
  options: StaffPageOptions = {},
): Promise<StaffListResponse> {
  const { search = '', page = 1, pageSize, signal } = options;
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize ?? 100),
  });
  if (search.trim()) {
    params.set('search', search.trim());
  }
  return apiRequest<StaffListResponse>(`/api/v1/staff?${params.toString()}`, {
    method: 'GET',
    signal,
  });
}

/**
 * Fetch all staff items by iterating pages until the total is reached.
 * This is a convenience helper for dashboards that need the full list
 * (e.g. to compute aggregate CARE_WORKER statistics).
 * Returns unique items in first-seen order plus total from the first page.
 */
export async function fetchAllStaff(
  signal?: AbortSignal,
): Promise<{ items: StaffListResponse['items']; total: number }> {
  const pageSize = 200;
  const maxPages = 1_000;
  const first = await fetchStaffPage({ page: 1, pageSize, signal });
  const uniqueItems = new Map<number, StaffListResponse['items'][number]>();
  for (const item of first.items) {
    if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item);
  }
  const total = first.total;
  let page = 2;

  while (uniqueItems.size < total && page <= maxPages) {
    const nextPage = await fetchStaffPage({
      page,
      pageSize,
      signal,
    });
    if (nextPage.items.length === 0) break;
    for (const item of nextPage.items) {
      if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item);
    }
    page += 1;
  }

  return { items: [...uniqueItems.values()], total };
}

export async function fetchServiceCatalog(signal?: AbortSignal): Promise<ServiceCatalogResponse> {
  return apiRequest<ServiceCatalogResponse>('/api/v1/catalogs/services', {
    method: 'GET',
    signal,
  });
}

export async function fetchLicenseTypes(signal?: AbortSignal): Promise<LicenseTypeListResponse> {
  return apiRequest<LicenseTypeListResponse>('/api/v1/catalogs/license-types', {
    method: 'GET',
    signal,
  });
}

export async function fetchTrainingCourses(
  signal?: AbortSignal,
): Promise<TrainingCourseListResponse> {
  return apiRequest<TrainingCourseListResponse>('/api/v1/staff/training-courses', {
    method: 'GET',
    signal,
  });
}

export async function fetchStaffOnboardingTrainings(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffOnboardingTrainingListResponse> {
  return apiRequest<StaffOnboardingTrainingListResponse>(
    `/api/v1/staff/${staffId}/onboarding-trainings`,
    {
      method: 'GET',
      signal,
    },
  );
}

export async function updateStaffOnboardingTraining(
  staffId: number,
  trainingId: number,
  payload: StaffOnboardingTrainingUpdateRequest,
  signal?: AbortSignal,
): Promise<StaffOnboardingTrainingResponse> {
  return apiRequest<StaffOnboardingTrainingResponse>(
    `/api/v1/staff/${staffId}/onboarding-trainings/${trainingId}`,
    {
      method: 'PATCH',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchStaffPeriodicTrainings(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffPeriodicTrainingListResponse> {
  return apiRequest<StaffPeriodicTrainingListResponse>(
    `/api/v1/staff/${staffId}/periodic-trainings`,
    {
      method: 'GET',
      signal,
    },
  );
}

export async function createStaffPeriodicTraining(
  staffId: number,
  payload: StaffPeriodicTrainingCreateRequest,
  signal?: AbortSignal,
): Promise<StaffPeriodicTrainingResponse> {
  return apiRequest<StaffPeriodicTrainingResponse>(
    `/api/v1/staff/${staffId}/periodic-trainings`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function updateStaffPeriodicTraining(
  staffId: number,
  trainingId: number,
  payload: StaffPeriodicTrainingUpdateRequest,
  signal?: AbortSignal,
): Promise<StaffPeriodicTrainingResponse> {
  return apiRequest<StaffPeriodicTrainingResponse>(
    `/api/v1/staff/${staffId}/periodic-trainings/${trainingId}`,
    {
      method: 'PATCH',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function invalidateStaffPeriodicTraining(
  staffId: number,
  trainingId: number,
  payload: StaffPeriodicTrainingInvalidateRequest,
  signal?: AbortSignal,
): Promise<StaffPeriodicTrainingResponse> {
  return apiRequest<StaffPeriodicTrainingResponse>(
    `/api/v1/staff/${staffId}/periodic-trainings/${trainingId}/invalidate`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchStaffHealthChecks(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffHealthCheckListResponse> {
  return healthRequest<StaffHealthCheckListResponse>(
    `/api/v1/staff/${staffId}/health-checks`,
    {
      method: 'GET',
      signal,
    },
  );
}

export async function createStaffHealthCheck(
  staffId: number,
  payload: StaffHealthCheckCreateRequest,
  signal?: AbortSignal,
): Promise<StaffHealthCheckResponse> {
  return healthRequest<StaffHealthCheckResponse>(
    `/api/v1/staff/${staffId}/health-checks`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function updateStaffHealthCheck(
  staffId: number,
  healthCheckId: number,
  payload: StaffHealthCheckUpdateRequest,
  signal?: AbortSignal,
): Promise<StaffHealthCheckResponse> {
  return healthRequest<StaffHealthCheckResponse>(
    `/api/v1/staff/${staffId}/health-checks/${healthCheckId}`,
    {
      method: 'PATCH',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function invalidateStaffHealthCheck(
  staffId: number,
  healthCheckId: number,
  payload: Pick<StaffHealthCheckUpdateRequest, 'expected_row_version'>,
  signal?: AbortSignal,
): Promise<StaffHealthCheckResponse> {
  return healthRequest<StaffHealthCheckResponse>(
    `/api/v1/staff/${staffId}/health-checks/${healthCheckId}/invalidate`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchStaffQuarterlyConsultations(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffQuarterlyConsultationListResponse> {
  return consultationRequest<StaffQuarterlyConsultationListResponse>(
    `/api/v1/staff/${staffId}/quarterly-consultations`,
    {
      method: 'GET',
      signal,
    },
  );
}

export async function createStaffQuarterlyConsultation(
  staffId: number,
  payload: StaffQuarterlyConsultationCreateRequest,
  signal?: AbortSignal,
): Promise<StaffQuarterlyConsultationResponse> {
  return consultationRequest<StaffQuarterlyConsultationResponse>(
    `/api/v1/staff/${staffId}/quarterly-consultations`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function updateStaffQuarterlyConsultation(
  staffId: number,
  consultationId: number,
  payload: StaffQuarterlyConsultationUpdateRequest,
  signal?: AbortSignal,
): Promise<StaffQuarterlyConsultationResponse> {
  return consultationRequest<StaffQuarterlyConsultationResponse>(
    `/api/v1/staff/${staffId}/quarterly-consultations/${consultationId}`,
    {
      method: 'PATCH',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchStaffLicenses(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffLicenseListResponse> {
  return apiRequest<StaffLicenseListResponse>(`/api/v1/staff/${staffId}/licenses`, {
    method: 'GET',
    signal,
  });
}

export async function createStaffLicense(
  staffId: number,
  payload: StaffLicenseCreateRequest,
  signal?: AbortSignal,
): Promise<StaffLicenseResponse> {
  return apiRequest<StaffLicenseResponse>(`/api/v1/staff/${staffId}/licenses`, {
    method: 'POST',
    signal,
    body: JSON.stringify(payload),
  });
}

export async function replaceStaffLicense(
  staffId: number,
  licenseId: number,
  payload: StaffLicenseReplacementRequest,
  signal?: AbortSignal,
): Promise<StaffLicenseResponse> {
  return apiRequest<StaffLicenseResponse>(
    `/api/v1/staff/${staffId}/licenses/${licenseId}/replacements`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function invalidateStaffLicense(
  staffId: number,
  licenseId: number,
  payload: StaffLicenseInvalidateRequest,
  signal?: AbortSignal,
): Promise<StaffLicenseResponse> {
  return apiRequest<StaffLicenseResponse>(
    `/api/v1/staff/${staffId}/licenses/${licenseId}/invalidate`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchStaffServiceQualifications(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffServiceQualificationListResponse> {
  return apiRequest<StaffServiceQualificationListResponse>(
    `/api/v1/staff/${staffId}/service-qualifications`,
    {
      method: 'GET',
      signal,
    },
  );
}

export async function createStaffServiceQualification(
  staffId: number,
  payload: StaffServiceQualificationCreateRequest,
  signal?: AbortSignal,
): Promise<StaffServiceQualificationResponse> {
  return apiRequest<StaffServiceQualificationResponse>(
    `/api/v1/staff/${staffId}/service-qualifications`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function closeStaffServiceQualification(
  staffId: number,
  qualificationId: number,
  payload: StaffServiceQualificationCloseRequest,
  signal?: AbortSignal,
): Promise<StaffServiceQualificationResponse> {
  return apiRequest<StaffServiceQualificationResponse>(
    `/api/v1/staff/${staffId}/service-qualifications/${qualificationId}/close`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function replaceStaffServiceQualification(
  staffId: number,
  qualificationId: number,
  payload: StaffServiceQualificationReplacementRequest,
  signal?: AbortSignal,
): Promise<StaffServiceQualificationResponse> {
  return apiRequest<StaffServiceQualificationResponse>(
    `/api/v1/staff/${staffId}/service-qualifications/${qualificationId}/replacements`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function invalidateStaffServiceQualification(
  staffId: number,
  qualificationId: number,
  payload: StaffServiceQualificationInvalidateRequest,
  signal?: AbortSignal,
): Promise<StaffServiceQualificationResponse> {
  return apiRequest<StaffServiceQualificationResponse>(
    `/api/v1/staff/${staffId}/service-qualifications/${qualificationId}/invalidate`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchStaffDetail(
  staffId: number,
  signal?: AbortSignal,
): Promise<StaffDetailResponse> {
  return apiRequest<StaffDetailResponse>(`/api/v1/staff/${staffId}`, {
    method: 'GET',
    signal,
  });
}

export async function createStaff(
  payload: StaffCreateRequest,
  signal?: AbortSignal,
): Promise<StaffCreateResponse> {
  return apiRequest<StaffCreateResponse>('/api/v1/staff', {
    method: 'POST',
    signal,
    body: JSON.stringify(payload),
  });
}

export async function closeEmployment(
  staffId: number,
  employmentId: number,
  payload: StaffEmploymentCloseRequest,
  signal?: AbortSignal,
): Promise<Schemas['StaffEmploymentResponse']> {
  return apiRequest<Schemas['StaffEmploymentResponse']>(
    `/api/v1/staff/${staffId}/employments/${employmentId}/close`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function createEmployment(
  staffId: number,
  payload: StaffEmploymentCreateRequest,
  signal?: AbortSignal,
): Promise<Schemas['StaffEmploymentResponse']> {
  return apiRequest<Schemas['StaffEmploymentResponse']>(
    `/api/v1/staff/${staffId}/employments`,
    {
      method: 'POST',
      signal,
      body: JSON.stringify(payload),
    },
  );
}

export async function revealSensitiveIdentity(
  staffId: number,
  currentPin: string,
  signal?: AbortSignal,
): Promise<SensitiveIdentityRevealResponse> {
  return apiRequest<SensitiveIdentityRevealResponse>(
    `/api/v1/staff/${staffId}/sensitive-identity/reveal`,
    {
      method: 'POST',
      cache: 'no-store',
      signal,
      body: JSON.stringify({ current_pin: currentPin }),
    },
  );
}
