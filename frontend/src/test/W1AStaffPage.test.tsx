import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, test, vi } from 'vitest';
import StaffPage from '../pages/StaffPage';
import { AUTH_SESSION_CHANGED_EVENT, beginAuthTransition } from '../services/api';

const employment = {
  id: 11,
  staff_id: 7,
  employment_no: 1,
  staff_no: '2026-001',
  start_date: '2026-01-01',
  end_date: null,
  end_reason_code: null,
  status: 'ACTIVE',
  row_version: 1,
};

const staffItem = {
  id: 7,
  name: '홍길동',
  birth_date: '1990-01-01',
  sex_code: 'MALE',
  phone: '010-1234-5678',
  address: '합성 주소',
  display_name: null,
  memo: '합성 메모',
  resident_number_masked: '900101-*******',
  row_version: 1,
  current_employment: employment,
  current_positions: [],
  current_operational_roles: [],
};

const staffDetail = {
  ...staffItem,
  employments: [employment],
  positions: [
    {
      id: 21,
      staff_id: 7,
      employment_id: 11,
      position_code: 'CARE_WORKER',
      start_date: '2026-01-01',
      end_date: null,
      row_version: 1,
    },
  ],
  operational_roles: [
    {
      id: 31,
      staff_id: 7,
      employment_id: 11,
      role_code: 'CARE_TEAM',
      start_date: '2026-01-01',
      end_date: null,
      row_version: 1,
    },
  ],
};

const buildSyntheticResidentNumber = (suffix: string) => '90010' + '1-11234' + suffix;

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

function renderPage() {
  const queryClient = createTestQueryClient();
  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StaffPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...rendered, queryClient };
}

function fillCreateForm(residentNumber: string): void {
  fireEvent.change(screen.getByLabelText('성명'), { target: { value: '지연 등록 직원' } });
  fireEvent.change(screen.getByLabelText('생년월일'), { target: { value: '1990-01-01' } });
  fireEvent.change(screen.getByLabelText('주민등록번호'), { target: { value: residentNumber } });
  fireEvent.change(screen.getByLabelText('입사일'), { target: { value: '2026-07-27' } });
}

function countSensitiveMutationCacheMarkers(queryClient: QueryClient, markers: string[]): number {
  return queryClient.getMutationCache().getAll().reduce((count, mutation) => {
    const serialized = JSON.stringify({
      variables: mutation.state.variables,
      data: mutation.state.data,
    });
    return count + markers.filter((marker) => serialized.includes(marker)).length;
  }, 0);
}

describe('W1AStaffPage component and DOM contracts', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200, headers: { 'Cache-Control': 'no-store' } },
        );
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });
  });

  test('renders a master-detail workspace without popups', async () => {
    const windowOpenSpy = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderPage();

    expect(screen.getByTestId('page-staff')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/직원 검색/i)).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: /신규 직원 등록/i }),
    ).toBeInTheDocument();

    const staffNames = await screen.findAllByText('홍길동');
    fireEvent.click(staffNames[0]);
    expect(windowOpenSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId('staff-detail-workspace')).toBeInTheDocument();
  });

  test('shows masked identity and separate employment, position, and role sections', async () => {
    renderPage();

    expect(await screen.findByText('900101-*******')).toBeInTheDocument();
    expect(screen.getByText('재직 이력')).toBeInTheDocument();
    expect(screen.getByText('직종 이력')).toBeInTheDocument();
    expect(screen.getByText('업무역할 이력')).toBeInTheDocument();
  });

  test('uses a PIN step-up modal and purges local sensitive state on close', async () => {
    renderPage();

    const revealButton = await screen.findByRole('button', { name: /주민번호 보기/i });
    fireEvent.click(revealButton);
    const pinInput = screen.getByPlaceholderText(/현재 PIN/i);
    expect(pinInput).toBeInTheDocument();

    const closeButtons = screen.getAllByRole('button', { name: /닫기/i });
    fireEvent.click(closeButtons[0]);
    expect(screen.queryByPlaceholderText(/현재 PIN/i)).not.toBeInTheDocument();
  });

  test('does not render legacy keys, internal phone projection, or work status', async () => {
    const { container } = renderPage();
    await screen.findByText('900101-*******');

    const htmlContent = container.innerHTML;
    expect(htmlContent).not.toMatch(/legacy_id/i);
    expect(htmlContent).not.toMatch(/work_status/i);
    expect(htmlContent).not.toMatch(/phone_normalized/i);
  });

  test('passes query AbortSignal and purges staff data on session transition', async () => {
    let listSignal: AbortSignal | undefined;
    let resolveList: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/api/v1/staff?')) {
        listSignal = init?.signal;
        return new Promise<Response>((resolve) => {
          resolveList = resolve;
        });
      }
      return new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 100 }));
    });

    const rendered = renderPage();
    await waitFor(() => expect(listSignal).toBeDefined());
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT));
    expect(listSignal?.aborted).toBe(true);

    rendered.unmount();
    resolveList?.(
      new Response(JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 })),
    );
    expect(document.body.textContent).not.toContain('홍길동');
  });

  test('closes create, close, and rehire forms on a direct account transition', async () => {
    const createPage = renderPage();
    await screen.findByRole('button', { name: /신규 직원 등록/i });
    fireEvent.click(screen.getByRole('button', { name: /신규 직원 등록/i }));
    expect(screen.getByRole('heading', { name: '신규 직원 등록' })).toBeInTheDocument();

    beginAuthTransition();
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: '신규 직원 등록' })).not.toBeInTheDocument();
    });
    createPage.unmount();

    const closePage = renderPage();
    await screen.findByRole('button', { name: '재직 종료' });
    fireEvent.click(screen.getByRole('button', { name: '재직 종료' }));
    expect(screen.getByRole('heading', { name: '재직 종료' })).toBeInTheDocument();

    beginAuthTransition();
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: '재직 종료' })).not.toBeInTheDocument();
    });
    closePage.unmount();

    const noCurrentEmployment = { ...staffDetail, current_employment: null };
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(noCurrentEmployment), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rehirePage = renderPage();
    await screen.findByRole('button', { name: '재입사' });
    fireEvent.click(screen.getByRole('button', { name: '재입사' }));
    expect(screen.getByRole('heading', { name: '재입사' })).toBeInTheDocument();

    beginAuthTransition();
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: '재입사' })).not.toBeInTheDocument();
    });
    rehirePage.unmount();
  });

  test('purges a delayed create success, its form, and plaintext mutation inputs on session change', async () => {
    const residentNumber = buildSyntheticResidentNumber('74');
    let createSignal: AbortSignal | undefined;
    let resolveCreate: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url === '/api/v1/staff' && init?.method === 'POST') {
        createSignal = init.signal;
        return new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByRole('button', { name: /신규 직원 등록/i });
    fireEvent.click(screen.getByRole('button', { name: /신규 직원 등록/i }));
    fillCreateForm(residentNumber);
    fireEvent.click(screen.getByRole('button', { name: '등록' }));
    await waitFor(() => expect(createSignal).toBeDefined());

    expect(screen.getByDisplayValue(residentNumber)).toBeInTheDocument();
    expect(countSensitiveMutationCacheMarkers(rendered.queryClient, [residentNumber])).toBe(0);

    beginAuthTransition();
    await waitFor(() => expect(createSignal?.aborted).toBe(true));
    expect(screen.queryByDisplayValue(residentNumber)).not.toBeInTheDocument();
    expect(countSensitiveMutationCacheMarkers(rendered.queryClient, [residentNumber])).toBe(0);
    expect(JSON.stringify(rendered.queryClient.getQueryCache().getAll())).not.toContain(residentNumber);

    resolveCreate?.(
      new Response(JSON.stringify({ id: 99 }), { status: 201 }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(residentNumber);
    expect(countSensitiveMutationCacheMarkers(rendered.queryClient, [residentNumber])).toBe(0);

    rendered.unmount();
  });

  test('ignores a delayed create 401 after direct account transition without unauthorized broadcast or banner', async () => {
    const residentNumber = buildSyntheticResidentNumber('85');
    let createSignal: AbortSignal | undefined;
    let resolveCreate: ((response: Response) => void) | undefined;
    const unauthorized = vi.fn();
    window.addEventListener('sswcenter:unauthorized', unauthorized);
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url === '/api/v1/staff' && init?.method === 'POST') {
        createSignal = init.signal;
        return new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByRole('button', { name: /신규 직원 등록/i });
    fireEvent.click(screen.getByRole('button', { name: /신규 직원 등록/i }));
    fillCreateForm(residentNumber);
    fireEvent.click(screen.getByRole('button', { name: '등록' }));
    await waitFor(() => expect(createSignal).toBeDefined());

    beginAuthTransition();
    await waitFor(() => expect(createSignal?.aborted).toBe(true));
    resolveCreate?.(
      new Response(JSON.stringify({ detail: { code: 'SESSION_REQUIRED' } }), { status: 401 }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(unauthorized).not.toHaveBeenCalled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(residentNumber);
    expect(countSensitiveMutationCacheMarkers(rendered.queryClient, [residentNumber])).toBe(0);
    window.removeEventListener('sswcenter:unauthorized', unauthorized);
    rendered.unmount();
  });

  test('aborts a delayed create error on route exit without an error banner or cache residue', async () => {
    const residentNumber = buildSyntheticResidentNumber('96');
    let createSignal: AbortSignal | undefined;
    let resolveCreate: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url === '/api/v1/staff' && init?.method === 'POST') {
        createSignal = init.signal;
        return new Promise<Response>((resolve) => {
          resolveCreate = resolve;
        });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByRole('button', { name: /신규 직원 등록/i });
    fireEvent.click(screen.getByRole('button', { name: /신규 직원 등록/i }));
    fillCreateForm(residentNumber);
    fireEvent.click(screen.getByRole('button', { name: '등록' }));
    await waitFor(() => expect(createSignal).toBeDefined());

    rendered.unmount();
    expect(createSignal?.aborted).toBe(true);
    resolveCreate?.(
      new Response(JSON.stringify({ detail: { code: 'SERVER_ERROR' } }), { status: 500 }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.body.textContent).not.toContain(residentNumber);
    expect(countSensitiveMutationCacheMarkers(rendered.queryClient, [residentNumber])).toBe(0);
  });

  test('uses current_employment as the employment boundary instead of inferring from history', async () => {
    const detailWithoutCurrentEmployment = {
      ...staffDetail,
      current_employment: null,
    };
    vi.mocked(globalThis.fetch).mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(detailWithoutCurrentEmployment), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    renderPage();

    expect(await screen.findByRole('button', { name: '재입사' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '재직 종료' })).not.toBeInTheDocument();
  });

  test('removes staff query cache and ignores delayed reveal plaintext after session change', async () => {
    const residentNumber = buildSyntheticResidentNumber('67');
    let revealSignal: AbortSignal | undefined;
    let resolveReveal: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/sensitive-identity/reveal')) {
        revealSignal = init?.signal;
        return new Promise<Response>((resolve) => {
          resolveReveal = resolve;
        });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByText('900101-*******');
    expect(rendered.queryClient.getQueryData(['staff-detail', 7])).toBeDefined();

    fireEvent.click(await screen.findByRole('button', { name: '주민번호 보기' }));
    fireEvent.change(screen.getByPlaceholderText('현재 PIN'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: '조회' }));
    await waitFor(() => expect(revealSignal).toBeDefined());

    beginAuthTransition();
    await waitFor(() => {
      expect(rendered.queryClient.getQueryData(['staff-detail', 7])).toBeUndefined();
    });
    expect(revealSignal?.aborted).toBe(true);
    expect(document.body.textContent).not.toContain(residentNumber);

    resolveReveal?.(
      new Response(JSON.stringify({ resident_number: residentNumber }), { status: 200 }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByTestId('revealed-rrn')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(residentNumber);
    expect(JSON.stringify(rendered.queryClient.getQueryCache().getAll())).not.toContain(residentNumber);

    rendered.unmount();
  });

  test('aborts a delayed reveal on unmount and ignores its response', async () => {
    const residentNumber = buildSyntheticResidentNumber('21');
    let revealSignal: AbortSignal | undefined;
    let resolveReveal: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/sensitive-identity/reveal')) {
        revealSignal = init?.signal;
        return new Promise<Response>((resolve) => {
          resolveReveal = resolve;
        });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByText('900101-*******');
    fireEvent.click(await screen.findByRole('button', { name: '주민번호 보기' }));
    fireEvent.change(screen.getByPlaceholderText('현재 PIN'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: '조회' }));
    await waitFor(() => expect(revealSignal).toBeDefined());

    rendered.unmount();
    expect(revealSignal?.aborted).toBe(true);

    resolveReveal?.(
      new Response(JSON.stringify({ resident_number: residentNumber }), { status: 200 }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.body.textContent).not.toContain(residentNumber);
  });

  test('clears PIN and resident number from mutation cache after successful reveal close', async () => {
    const pin = '654321';
    const residentNumber = buildSyntheticResidentNumber('67');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/sensitive-identity/reveal')) {
        return new Response(JSON.stringify({ resident_number: residentNumber }), { status: 200 });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByText('900101-*******');
    fireEvent.click(await screen.findByRole('button', { name: '주민번호 보기' }));
    fireEvent.change(screen.getByPlaceholderText('현재 PIN'), { target: { value: pin } });
    fireEvent.click(screen.getByRole('button', { name: '조회' }));
    expect(await screen.findByTestId('revealed-rrn')).toHaveTextContent(residentNumber);

    const revealCloseButtons = screen.getAllByRole('button', { name: '닫기' });
    fireEvent.click(revealCloseButtons[revealCloseButtons.length - 1]);
    expect(screen.queryByTestId('revealed-rrn')).not.toBeInTheDocument();
    expect(
      countSensitiveMutationCacheMarkers(rendered.queryClient, [pin, residentNumber]),
      'B1_REVEAL_CLOSE_MUTATION_CACHE_PLAINTEXT',
    ).toBe(0);
  });

  test('clears PIN and resident number from mutation cache when the page unmounts', async () => {
    const pin = '765432';
    const residentNumber = buildSyntheticResidentNumber('21');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/sensitive-identity/reveal')) {
        return new Response(JSON.stringify({ resident_number: residentNumber }), { status: 200 });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByText('900101-*******');
    fireEvent.click(await screen.findByRole('button', { name: '주민번호 보기' }));
    fireEvent.change(screen.getByPlaceholderText('현재 PIN'), { target: { value: pin } });
    fireEvent.click(screen.getByRole('button', { name: '조회' }));
    expect(await screen.findByTestId('revealed-rrn')).toHaveTextContent(residentNumber);

    rendered.unmount();
    expect(
      countSensitiveMutationCacheMarkers(rendered.queryClient, [pin, residentNumber]),
      'B1_PAGE_UNMOUNT_MUTATION_CACHE_PLAINTEXT',
    ).toBe(0);
  });

  test('clears PIN and resident number from mutation cache on logout account transition', async () => {
    const pin = '876543';
    const residentNumber = buildSyntheticResidentNumber('32');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = typeof input === 'string' ? input : (input as Request).url;
      if (url.includes('/api/v1/session-capabilities')) {
        return new Response(
          JSON.stringify({
            'staff.view': true,
            'staff.manage': true,
            'staff.sensitive_identity.reveal': true,
          }),
          { status: 200 },
        );
      }
      if (url.includes('/sensitive-identity/reveal')) {
        return new Response(JSON.stringify({ resident_number: residentNumber }), { status: 200 });
      }
      if (url.includes('/api/v1/staff/7')) {
        return new Response(JSON.stringify(staffDetail), { status: 200 });
      }
      if (url.includes('/api/v1/staff')) {
        return new Response(
          JSON.stringify({ items: [staffItem], total: 1, page: 1, page_size: 100 }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
    });

    const rendered = renderPage();
    await screen.findByText('900101-*******');
    fireEvent.click(await screen.findByRole('button', { name: '주민번호 보기' }));
    fireEvent.change(screen.getByPlaceholderText('현재 PIN'), { target: { value: pin } });
    fireEvent.click(screen.getByRole('button', { name: '조회' }));
    expect(await screen.findByTestId('revealed-rrn')).toHaveTextContent(residentNumber);

    beginAuthTransition();
    expect(
      countSensitiveMutationCacheMarkers(rendered.queryClient, [pin, residentNumber]),
      'B1_LOGOUT_ACCOUNT_TRANSITION_MUTATION_CACHE_PLAINTEXT',
    ).toBe(0);
  });
});
