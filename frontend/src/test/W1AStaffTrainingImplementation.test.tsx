import './setup';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import StaffPage from '../pages/StaffPage';
import { AUTH_SESSION_CHANGED_EVENT, AUTH_SESSION_READY_EVENT } from '../services/api';

type JsonRecord = Record<string, unknown>;

type RequestRecord = {
  body: unknown;
  method: string;
  path: string;
  signal: AbortSignal | undefined;
};

type CatalogMode = 'success' | 'pending' | 'error' | 'empty';

type FailurePlan = {
  body: JsonRecord;
  method: string;
  path: string;
  status: number;
};

type DeferredResponse = {
  promise: Promise<Response>;
  resolve: (response: Response) => void;
  signal: AbortSignal | undefined;
};

const COURSES = [
  {
    code: 'NEW_HIRE_ORIENTATION',
    display_name: '신규직원교육',
    cycle_type: 'ON_HIRE',
    sort_order: 1,
    active: true,
  },
  {
    code: 'ELDER_RIGHTS',
    display_name: '노인인권',
    cycle_type: 'HALF_YEAR',
    sort_order: 2,
    active: true,
  },
  {
    code: 'DISABLED_ABUSE',
    display_name: '장애인학대 신고의무자교육',
    cycle_type: 'ANNUAL',
    sort_order: 3,
    active: true,
  },
  {
    code: 'ELDER_ABUSE',
    display_name: '노인학대 신고의무자교육',
    cycle_type: 'ANNUAL',
    sort_order: 4,
    active: true,
  },
  {
    code: 'SEXUAL_HARASSMENT',
    display_name: '직장 내 성희롱 예방교육',
    cycle_type: 'ANNUAL',
    sort_order: 5,
    active: true,
  },
  {
    code: 'WORKPLACE_BULLYING',
    display_name: '직장 내 괴롭힘 예방교육',
    cycle_type: 'ANNUAL',
    sort_order: 6,
    active: true,
  },
  {
    code: 'PRIVACY',
    display_name: '개인정보보호교육',
    cycle_type: 'ANNUAL',
    sort_order: 7,
    active: true,
  },
] as const;

const CONTINUING_EDUCATION_COURSE = {
  code: 'CONTINUING_EDUCATION',
  display_name: '보수교육',
  cycle_type: 'BIENNIAL',
  sort_order: 8,
  active: true,
} as const;

const STAFF_A = { id: 71, name: 'W1A 구현 검증 직원 A', employmentId: 701 } as const;
const STAFF_B = { id: 72, name: 'W1A 구현 검증 직원 B', employmentId: 702 } as const;

let requests: RequestRecord[] = [];
let capabilities = { view: true, manage: true };
let catalogMode: CatalogMode = 'success';
let catalogCourses: readonly JsonRecord[] = COURSES;
let onboardingItems = new Map<number, JsonRecord[]>();
let periodicItems = new Map<number, JsonRecord[]>();
let staffPositions = new Map<number, JsonRecord[]>();
let staffLicenses = new Map<number, JsonRecord[]>();
let failurePlans: FailurePlan[] = [];
let delayStaffOnboardingQuery = false;
let delayedOnboardingQuery: DeferredResponse | null = null;
let delayOnboardingMutation = false;
let delayedOnboardingMutation: DeferredResponse | null = null;
let deferredResponses: DeferredResponse[] = [];

function jsonResponse(body: JsonRecord, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://w1a-vs3-implementation.test');
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input), 'http://w1a-vs3-implementation.test');
}

function requestSignal(input: RequestInfo | URL, init?: RequestInit): AbortSignal | undefined {
  if (init?.signal) return init.signal;
  return input instanceof Request ? input.signal : undefined;
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

function currentPeriod(cycleType: 'HALF_YEAR' | 'ANNUAL'): string {
  const year = new Date().getFullYear();
  if (cycleType === 'ANNUAL') return String(year);
  return `${year}-${new Date().getMonth() < 6 ? 'H1' : 'H2'}`;
}

function staffDetail(staff: typeof STAFF_A | typeof STAFF_B): JsonRecord {
  const staffNo = staff === STAFF_A ? 'A-STAFF' : 'B-STAFF';
  const positions = staffPositions.get(staff.id) ?? [];
  return {
    id: staff.id,
    name: staff.name,
    birth_date: `${new Date().getFullYear() % 2 === 0 ? 1990 : 1991}-01-01`,
    sex_code: 'MALE',
    row_version: 11,
    current_employment: {
      id: staff.employmentId,
      staff_id: staff.id,
      staff_no: staffNo,
      start_date: '2026-01-01',
      end_date: null,
      status: 'ACTIVE',
      row_version: 1,
    },
    employments: [
      {
        id: staff.employmentId,
        staff_id: staff.id,
        staff_no: staffNo,
        start_date: '2026-01-01',
        end_date: null,
        status: 'ACTIVE',
        row_version: 1,
      },
    ],
    current_positions: positions,
    positions,
    operational_roles: [],
    licenses: [],
    service_qualifications: [],
  };
}

function onboardingTraining(
  staff: typeof STAFF_A | typeof STAFF_B,
  completed: boolean,
  rowVersion: number,
): JsonRecord {
  return {
    id: staff.id + 800,
    staff_id: staff.id,
    employment_id: staff.employmentId,
    course_code: 'NEW_HIRE_ORIENTATION',
    completed,
    invalidated_at_utc: null,
    replacement_onboarding_training_id: null,
    created_by_account_id: 1,
    created_at_utc: '2026-01-01T00:00:00Z',
    updated_by_account_id: 1,
    updated_at_utc: '2026-01-01T00:00:00Z',
    row_version: rowVersion,
  };
}

function periodicTraining(
  staff: typeof STAFF_A | typeof STAFF_B,
  completed: boolean,
  rowVersion: number,
): JsonRecord {
  return {
    id: staff.id + 900,
    staff_id: staff.id,
    course_code: 'ELDER_RIGHTS',
    period_key: currentPeriod('HALF_YEAR'),
    completed,
    invalidated_at_utc: null,
    replacement_periodic_training_id: null,
    created_by_account_id: 1,
    created_at_utc: '2026-01-01T00:00:00Z',
    updated_by_account_id: 1,
    updated_at_utc: '2026-01-01T00:00:00Z',
    row_version: rowVersion,
  };
}

function resetTrainingState(): void {
  onboardingItems = new Map();
  periodicItems = new Map();
  staffPositions = new Map();
  staffLicenses = new Map();
  delayedOnboardingQuery = null;
  delayedOnboardingMutation = null;
  delayStaffOnboardingQuery = false;
  delayOnboardingMutation = false;
  failurePlans = [];
  deferredResponses = [];
}

function makeDeferredResponse(signal: AbortSignal | undefined): DeferredResponse {
  let resolveResponse: (response: Response) => void = () => undefined;
  const promise = new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  });
  const deferred = { promise, resolve: resolveResponse, signal };
  deferredResponses.push(deferred);
  return deferred;
}

function takeFailure(method: string, path: string): FailurePlan | null {
  const index = failurePlans.findIndex(
    (failure) => failure.method === method && failure.path === path,
  );
  if (index < 0) return null;
  return failurePlans.splice(index, 1)[0];
}

function queueFailure(failure: FailurePlan): void {
  failurePlans.push(failure);
}

function installFetchFixture(): void {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = requestUrl(input);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const signal = requestSignal(input, init);
    const path = url.pathname;
    requests.push({ body: parseBody(init?.body), method, path, signal });

    if (path === '/api/v1/session-capabilities') {
      return jsonResponse({
        'staff.view': capabilities.view,
        'staff.manage': capabilities.manage,
        'staff.sensitive_identity.reveal': false,
      });
    }
    if (path === '/api/v1/catalogs/license-types' || path === '/api/v1/catalogs/services') {
      return jsonResponse({ items: [] });
    }
    if (path === '/api/v1/staff' && method === 'GET') {
      return jsonResponse({
        items: [
          {
            id: STAFF_A.id,
            name: STAFF_A.name,
            current_employment: { id: STAFF_A.employmentId, staff_no: 'A-STAFF', status: 'ACTIVE' },
          },
          {
            id: STAFF_B.id,
            name: STAFF_B.name,
            current_employment: { id: STAFF_B.employmentId, staff_no: 'B-STAFF', status: 'ACTIVE' },
          },
        ],
        total: 2,
        page: Number(url.searchParams.get('page') ?? '1'),
        page_size: Number(url.searchParams.get('page_size') ?? '1'),
      });
    }
    if (path === '/api/v1/staff/training-courses' && method === 'GET') {
      if (catalogMode === 'pending') {
        const deferred = makeDeferredResponse(signal);
        return deferred.promise;
      }
      if (catalogMode === 'error') {
        return jsonResponse(
          { error: { code: 'TRAINING_CATALOG_UNAVAILABLE', message: '교육과목을 불러오지 못했습니다.' } },
          500,
        );
      }
      return jsonResponse({ items: catalogMode === 'empty' ? [] : catalogCourses });
    }

    const detailMatch = path.match(/^\/api\/v1\/staff\/(\d+)$/);
    if (detailMatch && method === 'GET') {
      return jsonResponse(Number(detailMatch[1]) === STAFF_B.id ? staffDetail(STAFF_B) : staffDetail(STAFF_A));
    }

    const onboardingMatch = path.match(/^\/api\/v1\/staff\/(\d+)\/onboarding-trainings(?:\/(\d+))?$/);
    if (onboardingMatch) {
      const staffId = Number(onboardingMatch[1]);
      const trainingId = onboardingMatch[2] ? Number(onboardingMatch[2]) : null;
      if (method === 'GET' && delayStaffOnboardingQuery && staffId === STAFF_A.id) {
        delayedOnboardingQuery = makeDeferredResponse(signal);
        delayStaffOnboardingQuery = false;
        return delayedOnboardingQuery.promise;
      }
      if (method === 'GET') {
        return jsonResponse({ items: onboardingItems.get(staffId) ?? [] });
      }
      if (method === 'PATCH' && trainingId !== null) {
        const failure = takeFailure(method, path);
        if (failure) return jsonResponse(failure.body, failure.status);
        if (delayOnboardingMutation && staffId === STAFF_A.id) {
          delayedOnboardingMutation = makeDeferredResponse(signal);
          delayOnboardingMutation = false;
          return delayedOnboardingMutation.promise;
        }
        const body = parseBody(init?.body) as JsonRecord;
        const current = (onboardingItems.get(staffId) ?? []).find(
          (item) => item.id === trainingId,
        );
        if (!current) return jsonResponse({ error: { message: '교육 상태를 찾을 수 없습니다.' } }, 404);
        const updated = {
          ...current,
          completed: body.completed,
          row_version: Number(current.row_version) + 1,
        };
        onboardingItems.set(staffId, [updated]);
        return jsonResponse(updated);
      }
    }

    const periodicMatch = path.match(/^\/api\/v1\/staff\/(\d+)\/periodic-trainings(?:\/(\d+))?$/);
    if (periodicMatch) {
      const staffId = Number(periodicMatch[1]);
      const trainingId = periodicMatch[2] ? Number(periodicMatch[2]) : null;
      if (method === 'GET') {
        return jsonResponse({ items: periodicItems.get(staffId) ?? [] });
      }
      if (method === 'PATCH' && trainingId !== null) {
        const failure = takeFailure(method, path);
        if (failure) return jsonResponse(failure.body, failure.status);
        const body = parseBody(init?.body) as JsonRecord;
        const current = (periodicItems.get(staffId) ?? []).find((item) => item.id === trainingId);
        if (!current) return jsonResponse({ error: { message: '정기교육 상태를 찾을 수 없습니다.' } }, 404);
        const updated = {
          ...current,
          completed: body.completed,
          row_version: Number(current.row_version) + 1,
        };
        periodicItems.set(staffId, [updated]);
        return jsonResponse(updated);
      }
    }

    const licensesMatch = path.match(/^\/api\/v1\/staff\/(\d+)\/licenses$/);
    if (licensesMatch && method === 'GET') {
      const staffId = Number(licensesMatch[1]);
      const items = staffLicenses.get(staffId) ?? [];
      return jsonResponse({ items, total: items.length });
    }
    const qualificationsMatch = path.match(
      /^\/api\/v1\/staff\/(\d+)\/service-qualifications$/,
    );
    if (qualificationsMatch && method === 'GET') {
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
    }
    return jsonResponse({ detail: 'not_found' }, 404);
  });
}

function renderStaffPage(): { queryClient: QueryClient; unmount: () => void } {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StaffPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { queryClient, unmount: result.unmount };
}

async function openEducation(staff: typeof STAFF_A | typeof STAFF_B = STAFF_A): Promise<void> {
  await waitFor(() =>
    expect(screen.getAllByText(staff.name, { exact: true }).length).toBeGreaterThan(0),
  );
  fireEvent.click(screen.getAllByText(staff.name, { exact: true })[0]);
  await screen.findByRole('heading', { level: 2, name: staff.name });
  fireEvent.click(await screen.findByRole('tab', { name: '교육' }));
}

function onboardingCheckbox(): HTMLInputElement {
  return screen.getByRole('checkbox', { name: /신규직원교육/ }) as HTMLInputElement;
}

function periodicCheckbox(): HTMLInputElement {
  return screen.getByRole('checkbox', { name: /노인인권/ }) as HTMLInputElement;
}

async function latestRequest(method: string, path: string): Promise<RequestRecord> {
  await waitFor(() =>
    expect(
      requests.some((request) => request.method === method && request.path === path),
    ).toBe(true),
  );
  const matches = requests.filter(
    (request) => request.method === method && request.path === path,
  );
  return matches[matches.length - 1];
}

beforeEach(() => {
  requests = [];
  capabilities = { view: true, manage: true };
  catalogMode = 'success';
  catalogCourses = COURSES;
  resetTrainingState();
  installFetchFixture();
});

afterEach(() => {
  for (const deferred of deferredResponses) {
    deferred.resolve(jsonResponse({ items: [] }));
  }
  vi.restoreAllMocks();
});

describe('W1A-VS3 staff training implementation behavior', () => {
  test('keeps unresolved catalog loading with zero synthetic rows', async () => {
    catalogMode = 'pending';
    renderStaffPage();
    await openEducation();

    expect(await screen.findByText('교육과목을 불러오는 중…')).toBeInTheDocument();
    expect(screen.queryAllByTestId('training-course-row')).toHaveLength(0);
  });

  test('renders catalog error and successful empty state without synthetic rows', async () => {
    catalogMode = 'error';
    const errorRender = renderStaffPage();
    await openEducation();
    expect(await screen.findByText('교육과목을 불러오지 못했습니다.')).toBeInTheDocument();
    expect(screen.queryAllByTestId('training-course-row')).toHaveLength(0);

    errorRender.unmount();
    catalogMode = 'empty';
    renderStaffPage();
    await openEducation();
    expect(await screen.findByText('등록된 교육과목이 없습니다.')).toBeInTheDocument();
    expect(screen.queryAllByTestId('training-course-row')).toHaveLength(0);
  });

  test('uses only the successful server catalog response as row source', async () => {
    catalogCourses = [
      {
        code: 'SERVER_ONLY_COURSE',
        display_name: '서버가 반환한 과목',
        cycle_type: 'ANNUAL',
        sort_order: 1,
        active: true,
      },
    ];
    renderStaffPage();
    await openEducation();

    const rows = await screen.findAllByTestId('training-course-row');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute('data-course-code', 'SERVER_ONLY_COURSE');
    expect(rows[0]).toHaveTextContent('서버가 반환한 과목');
    const courseList = rows[0].parentElement;
    expect(courseList).not.toBeNull();
    if (!courseList) throw new Error('W1A_VS3_IMPL_COURSE_LIST_MISSING');
    expect(within(courseList).queryByText('신규직원교육')).not.toBeInTheDocument();
  });

  test('accepts the exact eight-course catalog including continuing education', async () => {
    catalogCourses = [...COURSES, CONTINUING_EDUCATION_COURSE];
    renderStaffPage();
    await openEducation();

    const rows = await screen.findAllByTestId('training-course-row');
    expect(rows).toHaveLength(8);
    expect(
      rows.some((row) => row.getAttribute('data-course-code') === 'CONTINUING_EDUCATION'),
    ).toBe(true);
  });

  test('shows biennial continuing education only for a current care worker', async () => {
    const targetYear = new Date().getFullYear();
    catalogCourses = [...COURSES, CONTINUING_EDUCATION_COURSE];
    staffPositions.set(STAFF_A.id, [
      {
        id: 1701,
        staff_id: STAFF_A.id,
        employment_id: STAFF_A.employmentId,
        position_code: 'CARE_WORKER',
        start_date: '2026-01-01',
        end_date: null,
        row_version: 1,
      },
    ]);
    staffLicenses.set(STAFF_A.id, [
      {
        id: 1801,
        staff_id: STAFF_A.id,
        license_type_code: 'CARE_WORKER',
        license_no: 'CARE-WORKER-TEST',
        issued_date: `${targetYear - 3}-01-01`,
        invalidated_at_utc: null,
        row_version: 1,
      },
    ]);

    renderStaffPage();
    await openEducation();

    const panel = await screen.findByTestId('staff-continuing-education-panel');
    expect(within(panel).getByText(`${targetYear}년 대상`)).toBeInTheDocument();
    expect(within(panel).getByTestId('staff-continuing-education-checkbox')).toBeEnabled();
  });

  test('keeps STAFF_VIEW training controls read-only and sends no mutation', async () => {
    capabilities = { view: true, manage: false };
    onboardingItems.set(STAFF_A.id, [onboardingTraining(STAFF_A, false, 7)]);
    periodicItems.set(STAFF_A.id, [periodicTraining(STAFF_A, true, 9)]);
    renderStaffPage();
    await openEducation();

    const checkboxes = await screen.findAllByRole('checkbox');
    expect(checkboxes.length).toBeGreaterThan(1);
    expect(checkboxes.every((checkbox) => (checkbox as HTMLInputElement).disabled)).toBe(true);
    expect(screen.queryByRole('button', { name: '신규 직원 등록' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '재직 종료' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '무효화' })).not.toBeInTheDocument();

    fireEvent.click(onboardingCheckbox());
    await waitFor(() =>
      expect(
        requests.some(
          (request) => request.method === 'PATCH' || request.method === 'POST',
        ),
        'W1A_VS3_IMPL_VIEW_MUTATION_SENT',
      ).toBe(false),
    );
  });

  test('allows manage/admin write path and refetches both completion directions with row versions', async () => {
    onboardingItems.set(STAFF_A.id, [onboardingTraining(STAFF_A, false, 7)]);
    periodicItems.set(STAFF_A.id, [periodicTraining(STAFF_A, true, 9)]);
    renderStaffPage();
    await openEducation();

    const onboardingPath = `/api/v1/staff/${STAFF_A.id}/onboarding-trainings/${STAFF_A.id + 800}`;
    const periodicPath = `/api/v1/staff/${STAFF_A.id}/periodic-trainings/${STAFF_A.id + 900}`;
    const firstOnboarding = onboardingCheckbox();
    expect(firstOnboarding).not.toBeDisabled();
    fireEvent.click(firstOnboarding);
    const enableOnboarding = await latestRequest('PATCH', onboardingPath);
    expect(enableOnboarding.signal).toBeDefined();
    expect(enableOnboarding.body).toEqual({ completed: true, expected_row_version: 7 });
    await waitFor(() => expect(onboardingCheckbox()).toBeChecked());

    fireEvent.click(onboardingCheckbox());
    const disableOnboarding = await latestRequest('PATCH', onboardingPath);
    expect(disableOnboarding.body).toEqual({ completed: false, expected_row_version: 8 });
    await waitFor(() => expect(onboardingCheckbox()).not.toBeChecked());

    fireEvent.click(periodicCheckbox());
    const disablePeriodic = await latestRequest('PATCH', periodicPath);
    expect(disablePeriodic.signal).toBeDefined();
    expect(disablePeriodic.body).toEqual({ completed: false, expected_row_version: 9 });
    await waitFor(() => expect(periodicCheckbox()).not.toBeChecked());

    fireEvent.click(periodicCheckbox());
    const enablePeriodic = await latestRequest('PATCH', periodicPath);
    expect(enablePeriodic.body).toEqual({ completed: true, expected_row_version: 10 });
    await waitFor(() => expect(periodicCheckbox()).toBeChecked());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('preserves selection, tab, period, and checkbox state across 403, 409, and field-level 422', async () => {
    onboardingItems.set(STAFF_A.id, [onboardingTraining(STAFF_A, false, 7)]);
    periodicItems.set(STAFF_A.id, [periodicTraining(STAFF_A, true, 9)]);
    const onboardingPath = `/api/v1/staff/${STAFF_A.id}/onboarding-trainings/${STAFF_A.id + 800}`;
    const periodicPath = `/api/v1/staff/${STAFF_A.id}/periodic-trainings/${STAFF_A.id + 900}`;
    queueFailure({
      method: 'PATCH',
      path: onboardingPath,
      status: 409,
      body: {
        error: { code: 'ROW_VERSION_CONFLICT', message: '최신 교육 상태를 확인해 다시 시도하세요.' },
        field_errors: [],
        details: {},
      },
    });
    queueFailure({
      method: 'PATCH',
      path: periodicPath,
      status: 422,
      body: {
        error: { code: 'VALIDATION_ERROR', message: '입력값을 확인하세요.' },
        field_errors: [{ field: 'expected_row_version', message: '입력값을 확인하세요.' }],
        details: {},
      },
    });
    queueFailure({
      method: 'PATCH',
      path: periodicPath,
      status: 403,
      body: { error: { code: 'FORBIDDEN', message: '교육 상태를 변경할 권한이 없습니다.' } },
    });

    renderStaffPage();
    await openEducation();
    const halfYearPeriod = screen.getByRole('combobox', { name: '반기 대상기간' }) as HTMLSelectElement;
    const retainedPeriod = halfYearPeriod.value;

    fireEvent.click(onboardingCheckbox());
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '최신 교육 상태를 확인해 다시 시도하세요.',
    );
    expect(onboardingCheckbox()).not.toBeChecked();
    expect(screen.getByRole('tab', { name: '교육' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { level: 2, name: STAFF_A.name })).toBeInTheDocument();
    expect(halfYearPeriod).toHaveValue(retainedPeriod);

    fireEvent.click(periodicCheckbox());
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('입력값을 확인하세요.'),
    );
    expect(periodicCheckbox()).toBeChecked();
    expect(halfYearPeriod).toHaveValue(retainedPeriod);

    fireEvent.click(periodicCheckbox());
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('교육 상태를 변경할 권한이 없습니다.'),
    );
    expect(periodicCheckbox()).toBeChecked();
  });

  test('cancels delayed A query before B can receive stale A training data', async () => {
    onboardingItems.set(STAFF_B.id, [onboardingTraining(STAFF_B, true, 3)]);
    delayStaffOnboardingQuery = true;
    const { queryClient } = renderStaffPage();
    await openEducation();
    await waitFor(() => expect(delayedOnboardingQuery).not.toBeNull());

    fireEvent.click(screen.getAllByText(STAFF_B.name, { exact: true })[0]);
    await screen.findByRole('heading', { level: 2, name: STAFF_B.name });
    const trainingPanel = screen.getByTestId('staff-onboarding-training-panel');
    await waitFor(() => expect(within(trainingPanel).getByText(/B-STAFF/)).toBeInTheDocument());
    await waitFor(() => expect(delayedOnboardingQuery?.signal?.aborted).toBe(true));

    delayedOnboardingQuery?.resolve(
      jsonResponse({ items: [onboardingTraining(STAFF_A, true, 99)] }),
    );
    await waitFor(() => expect(within(trainingPanel).queryByText(/A-STAFF/)).not.toBeInTheDocument());
    expect(queryClient.getQueryData(['staff-onboarding-trainings', STAFF_A.id])).toBeUndefined();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('removes delayed A mutation and cache across session change before the new session is ready', async () => {
    onboardingItems.set(STAFF_A.id, [onboardingTraining(STAFF_A, false, 7)]);
    delayOnboardingMutation = true;
    const { queryClient } = renderStaffPage();
    await openEducation();

    fireEvent.click(onboardingCheckbox());
    const onboardingPath = `/api/v1/staff/${STAFF_A.id}/onboarding-trainings/${STAFF_A.id + 800}`;
    await latestRequest('PATCH', onboardingPath);
    await waitFor(() => expect(delayedOnboardingMutation).not.toBeNull());

    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
    expect(await screen.findByText('세션을 전환하는 중입니다…')).toBeInTheDocument();
    await waitFor(() => expect(delayedOnboardingMutation?.signal?.aborted).toBe(true));
    expect(queryClient.getQueryData(['staff-onboarding-trainings', STAFF_A.id])).toBeUndefined();
    expect(
      queryClient
        .getMutationCache()
        .getAll()
        .some((mutation) => mutation.options.mutationKey?.[0] === 'staff-training-onboarding-update'),
    ).toBe(false);

    delayedOnboardingMutation?.resolve(
      jsonResponse({
        ...onboardingTraining(STAFF_A, true, 8),
      }),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    window.dispatchEvent(new Event(AUTH_SESSION_READY_EVENT));
    await screen.findByRole('heading', { level: 2, name: STAFF_A.name });
    fireEvent.click(await screen.findByRole('tab', { name: '교육' }));
    await waitFor(() => expect(onboardingCheckbox()).not.toBeChecked());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
