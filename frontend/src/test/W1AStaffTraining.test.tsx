import './setup';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { BrowserRouter, MemoryRouter } from 'react-router';
import StaffPage from '../pages/StaffPage';

type JsonRecord = Record<string, unknown>;

type RequestRecord = {
  body: unknown;
  method: string;
  path: string;
};

const COURSES = [
  { code: 'NEW_HIRE_ORIENTATION', display_name: '신규직원교육', cycle_type: 'ON_HIRE' },
  { code: 'ELDER_RIGHTS', display_name: '노인인권', cycle_type: 'HALF_YEAR' },
  {
    code: 'DISABLED_ABUSE',
    display_name: '장애인학대 신고의무자교육',
    cycle_type: 'ANNUAL',
  },
  { code: 'ELDER_ABUSE', display_name: '노인학대 신고의무자교육', cycle_type: 'ANNUAL' },
  { code: 'SEXUAL_HARASSMENT', display_name: '직장 내 성희롱 예방교육', cycle_type: 'ANNUAL' },
  { code: 'WORKPLACE_BULLYING', display_name: '직장 내 괴롭힘 예방교육', cycle_type: 'ANNUAL' },
  { code: 'PRIVACY', display_name: '개인정보보호교육', cycle_type: 'ANNUAL' },
] as const;

const STAFF_A = { id: 71, name: 'W1A-VS3 합성 직원 A', employmentId: 701 } as const;
const STAFF_B = { id: 72, name: 'W1A-VS3 합성 직원 B', employmentId: 702 } as const;

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const STAFF_API_SOURCE = readFileSync(
  resolve(REPO_ROOT, 'frontend/src/services/staffApi.ts'),
  'utf8',
);
const GENERATED_OPENAPI_SOURCE = readFileSync(
  resolve(REPO_ROOT, 'frontend/src/generated/sswcenter-api.ts'),
  'utf8',
);

let requests: RequestRecord[] = [];
let capabilities = { view: true, manage: true };

function jsonResponse(body: JsonRecord, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (typeof input === 'string') return new URL(input, 'http://w1a-vs3.test');
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input), 'http://w1a-vs3.test');
}

function parseBody(body: BodyInit | null | undefined): unknown {
  if (typeof body !== 'string') return undefined;
  try {
    return JSON.parse(body);
  } catch {
    return undefined;
  }
}

function staffDetail(staff: typeof STAFF_A | typeof STAFF_B): JsonRecord {
  return {
    id: staff.id,
    name: staff.name,
    birth_date: '1990-01-01',
    current_employment: {
      id: staff.employmentId,
      staff_id: staff.id,
      start_date: '2026-01-01',
      end_date: null,
      status: 'ACTIVE',
      row_version: 1,
    },
    employments: [
      {
        id: staff.employmentId,
        staff_id: staff.id,
        start_date: '2026-01-01',
        end_date: null,
        status: 'ACTIVE',
        row_version: 1,
      },
    ],
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
    requests.push({ body: parseBody(init?.body), method, path: url.pathname });

    if (url.pathname === '/api/v1/session-capabilities') {
      return jsonResponse({
        'staff.view': capabilities.view,
        'staff.manage': capabilities.manage,
        'staff.sensitive_identity.reveal': false,
      });
    }
    if (url.pathname === '/api/v1/catalogs/license-types') {
      return jsonResponse({ items: [] });
    }
    if (url.pathname === '/api/v1/catalogs/services') {
      return jsonResponse({ items: [] });
    }
    if (url.pathname === '/api/v1/staff' && method === 'GET') {
      return jsonResponse({
        items: [
          { id: STAFF_A.id, name: STAFF_A.name, current_employment: { id: STAFF_A.employmentId } },
          { id: STAFF_B.id, name: STAFF_B.name, current_employment: { id: STAFF_B.employmentId } },
        ],
        total: 4,
        page: Number(url.searchParams.get('page') ?? '1'),
        page_size: Number(url.searchParams.get('page_size') ?? '1'),
      });
    }
    const detailMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)$/);
    if (detailMatch && method === 'GET') {
      const staff = Number(detailMatch[1]) === STAFF_B.id ? STAFF_B : STAFF_A;
      return jsonResponse(staffDetail(staff));
    }
    const licenseMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)\/licenses$/);
    if (licenseMatch && method === 'GET') return jsonResponse({ items: [], total: 0 });
    const qualificationMatch = url.pathname.match(
      /^\/api\/v1\/staff\/(\d+)\/service-qualifications$/,
    );
    if (qualificationMatch && method === 'GET') {
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
    }
    if (url.pathname === '/api/v1/staff/training-courses' && method === 'GET') {
      return jsonResponse({ items: COURSES });
    }
    if (url.pathname.includes('/onboarding-trainings') || url.pathname.includes('/periodic-trainings')) {
      return jsonResponse({ items: [] });
    }
    return jsonResponse({ detail: 'not_found' }, 404);
  });
}

function renderStaffPage(useBrowserHistory = false): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = useBrowserHistory ? (
    <BrowserRouter>
      <StaffPage />
    </BrowserRouter>
  ) : (
    <MemoryRouter>
      <StaffPage />
    </MemoryRouter>
  );
  render(<QueryClientProvider client={queryClient}>{router}</QueryClientProvider>);
}

async function selectStaff(staff: typeof STAFF_A | typeof STAFF_B, marker: string): Promise<void> {
  await waitFor(() =>
    expect(screen.queryAllByText(staff.name, { exact: true }).length > 0, marker).toBe(true),
  );
  fireEvent.click(screen.getAllByText(staff.name, { exact: true })[0] as HTMLElement);
  await waitFor(() =>
    expect(screen.queryByTestId('staff-detail-workspace'), marker).not.toBeNull(),
  );
}

async function expectEducationTab(marker: string): Promise<HTMLElement> {
  const tab = screen.queryByRole('tab', { name: '교육' });
  expect(tab, marker).not.toBeNull();
  if (!tab) throw new Error(marker);
  return tab;
}

beforeEach(() => {
  requests = [];
  capabilities = { view: true, manage: true };
  installFetchFixture();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('W1A-VS3 staff training frontend RED contract', () => {
  test('renders an independent education tab with exact seven course labels and cycles', async () => {
    renderStaffPage();
    await selectStaff(STAFF_A, 'W1A_VS3_UI_STAFF_DETAIL_MISSING');
    const tab = await expectEducationTab('W1A_VS3_UI_EDUCATION_TAB_MISSING');
    fireEvent.click(tab);
    const rows = screen.getAllByTestId('training-course-row');
    const observed = rows.map((row) => ({
      code: row.getAttribute('data-course-code'),
      cycle_type: row.getAttribute('data-cycle-type'),
      display_name: row.textContent?.trim() ?? '',
    }));
    expect(observed, 'W1A_VS3_UI_EXACT_COURSE_ORDER_MISMATCH').toEqual(COURSES);
    expect(screen.getByRole('region', { name: '신규직원교육' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '정기교육' })).toBeInTheDocument();
  });

  test('uses generated named models and separate training adapter routes', () => {
    expect(
      GENERATED_OPENAPI_SOURCE.includes('TrainingCourse') &&
        GENERATED_OPENAPI_SOURCE.includes('StaffOnboardingTraining') &&
        GENERATED_OPENAPI_SOURCE.includes('StaffPeriodicTraining'),
      'W1A_VS3_GENERATED_OPENAPI_TRAINING_MODELS_MISSING',
    ).toBe(true);
    expect(
      STAFF_API_SOURCE.includes('/training-courses') &&
        STAFF_API_SOURCE.includes('/onboarding-trainings') &&
        STAFF_API_SOURCE.includes('/periodic-trainings') &&
        STAFF_API_SOURCE.includes('StaffOnboardingTraining') &&
        STAFF_API_SOURCE.includes('StaffPeriodicTraining'),
      'W1A_VS3_GENERATED_ADAPTER_ROUTES_MISSING',
    ).toBe(true);
  });

  test('separates onboarding and periodic state while hiding forbidden fields', async () => {
    renderStaffPage();
    await selectStaff(STAFF_A, 'W1A_VS3_STATE_STAFF_DETAIL_MISSING');
    const tab = await expectEducationTab('W1A_VS3_STATE_EDUCATION_TAB_MISSING');
    fireEvent.click(tab);
    expect(screen.getByTestId('staff-onboarding-training-panel')).toBeInTheDocument();
    expect(screen.getByTestId('staff-periodic-training-panel')).toBeInTheDocument();
    const forbidden = /교육시간|이수일자|이수센터|첨부|파일|업무카드|task|file/i;
    expect(forbidden.test(document.body.textContent ?? ''), 'W1A_VS3_FORBIDDEN_TRAINING_FIELDS_VISIBLE').toBe(
      false,
    );
  });

  test('preserves loading/error/permission/session transitions and list browser-back context', async () => {
    window.history.replaceState({}, '', '/staff?context=before');
    window.history.pushState({}, '', '/staff?context=detail');
    renderStaffPage(true);
    await selectStaff(STAFF_A, 'W1A_VS3_CONTEXT_STAFF_DETAIL_MISSING');
    const tab = await expectEducationTab('W1A_VS3_CONTEXT_EDUCATION_TAB_MISSING');
    fireEvent.click(tab);
    const search = screen.getByLabelText(/^직원 검색$/) as HTMLInputElement;
    const sort = screen.getByLabelText(/정렬/) as HTMLSelectElement;
    const scroll = screen.getByTestId('staff-list-scroll') as HTMLElement;
    expect(search, 'W1A_VS3_CONTEXT_SEARCH_SURFACE_MISSING').toBeInTheDocument();
    expect(sort, 'W1A_VS3_CONTEXT_SORT_SURFACE_MISSING').toBeInTheDocument();
    scroll.scrollTop = 32;
    fireEvent.scroll(scroll);
    expect(scroll.scrollTop > 0, 'W1A_VS3_CONTEXT_SCROLL_NOT_RETAINED').toBe(true);
    window.history.back();
    await waitFor(() =>
      expect(window.location.search.includes('context=before'), 'W1A_VS3_CONTEXT_BACK_NOT_PERFORMED').toBe(
        true,
      ),
    );
    expect(screen.getByRole('tab', { name: '교육' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(requests.some((request) => request.path.includes('/training-')),
      'W1A_VS3_TRAINING_ROUTE_NOT_REQUESTED').toBe(true);
  });
});
