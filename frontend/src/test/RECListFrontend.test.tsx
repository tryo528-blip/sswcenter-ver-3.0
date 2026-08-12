import './setup';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import RecipientsPage from '../pages/RecipientsPage';
import { listRecipients } from '../services/recipientApi';
import type { RecipientListItem, RecipientListResponse } from '../services/recipientApi';

const recipientsCssPath = resolve(dirname(fileURLToPath(import.meta.url)), '../styles/recipients.css');

type ListQuery = {
  search: string | null;
  status: string | null;
  page: string | null;
  page_size: string | null;
};

const originalFetch = globalThis.fetch;

function listItem(overrides: Partial<RecipientListItem> = {}): RecipientListItem {
  return {
    id: 1,
    name: '김수급',
    birth_date: '1950-03-15',
    sex_code: 'FEMALE',
    recipient_no: 'R-001',
    postal_code: '06236',
    address: '서울시 강남구',
    home_phone: '02-111-2222',
    mobile_phone: '010-1111-2222',
    memo: null,
    row_version: 1,
    grade_code: '3',
    benefit_code: 'BASIC',
    copayment_rate: 15,
    services: [
      {
        service_group_code: 'VISIT',
        display_name: '방문요양',
        service_types: [
          { service_type_code: 'V1', display_name: '일반방문' },
          { service_type_code: 'V2', display_name: '야간방문' },
        ],
      },
      {
        service_group_code: 'BATH',
        display_name: '방문목욕',
        service_types: [{ service_type_code: 'B1', display_name: '차량목욕' }],
      },
    ],
    ...overrides,
  };
}

function listResponse(
  items: RecipientListItem[],
  total = items.length,
  page = 1,
  pageSize = 100,
): RecipientListResponse {
  return { items, total, page, page_size: pageSize };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function parseListQuery(url: URL): ListQuery {
  return {
    search: url.searchParams.get('search'),
    status: url.searchParams.get('status'),
    page: url.searchParams.get('page'),
    page_size: url.searchParams.get('page_size'),
  };
}

/** Atomic basic-create batch: POST /api/v1/recipients/basic-batch */
function isBasicCreateBatch(url: URL, method: string): boolean {
  return method === 'POST' && url.pathname === '/api/v1/recipients/basic-batch';
}

/** Atomic basic-update batch: POST /api/v1/recipients/{id}/basic-batch */
function isBasicUpdateBatch(url: URL, method: string): boolean {
  return method === 'POST' && /^\/api\/v1\/recipients\/\d+\/basic-batch$/.test(url.pathname);
}

function parseJsonBody(init?: RequestInit): Record<string, unknown> {
  return JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
}

/** Exact recipient name via row strong text (avoids accessible-name clashes e.g. 이용중행 vs 이용중행2). */
function hasRecipientRowWithExactName(name: string): boolean {
  return screen
    .queryAllByTestId('recipient-name-option')
    .some((row) => row.querySelector('strong')?.textContent === name);
}

function installRecipientListFetch(
  resolveList: (query: ListQuery) => RecipientListResponse,
): { requests: ListQuery[] } {
  const requests: ListQuery[] = [];

  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl =
      typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
    const url = new URL(rawUrl, 'http://localhost');
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

    if (url.pathname === '/api/v1/recipients' && method === 'GET') {
      const query = parseListQuery(url);
      requests.push(query);
      return jsonResponse(resolveList(query));
    }

    if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
      const id = Number(url.pathname.split('/').pop());
      const item = listItem({ id: Number.isFinite(id) ? id : 1 });
      if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      return jsonResponse({
        id: item.id,
        name: item.name,
        birth_date: item.birth_date,
        sex_code: item.sex_code,
        recipient_status: 'ACTIVE' as const,
        recipient_no: item.recipient_no,
        postal_code: item.postal_code,
        address: item.address,
        home_phone: item.home_phone,
        mobile_phone: item.mobile_phone,
        memo: item.memo,
        payer_guardian_id: null,
        row_version: item.row_version,
      });
    }

    return jsonResponse({ detail: { code: 'not_found' } }, 404);
  }) as typeof globalThis.fetch;

  return { requests };
}

/** Fire scroll near the bottom of the list panel (not window). */
function enterBasicEdit() {
  const edit = screen.queryByTestId('recipient-basic-edit');
  if (edit) fireEvent.click(edit);
}

function scrollListNearBottom() {
  const scroller = screen.getByTestId('recipient-list-scroll');
  Object.defineProperty(scroller, 'scrollHeight', { configurable: true, value: 1000 });
  Object.defineProperty(scroller, 'clientHeight', { configurable: true, value: 200 });
  Object.defineProperty(scroller, 'scrollTop', {
    configurable: true,
    writable: true,
    value: 750,
  });
  fireEvent.scroll(scroller);
}

describe('REC-LIST frontend contract', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/recipients');
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
    window.history.replaceState({}, '', '/');
  });

  test('listRecipients sends search/status/page/page_size as GET query params', async () => {
    const { requests } = installRecipientListFetch(() => listResponse([]));

    await listRecipients({
      search: ' 김수급 ',
      status: 'WAITING',
      page: 2,
      pageSize: 25,
    });

    expect(requests).toHaveLength(1);
    expect(requests[0]).toEqual({
      search: '김수급',
      status: 'WAITING',
      page: '2',
      page_size: '25',
    });
  });

  test('filter order is ACTIVE/ALL/ENDED/WAITING; default URL and request are ACTIVE', async () => {
    const { requests } = installRecipientListFetch(() =>
      listResponse([listItem({ id: 10, name: '필터대상' })]),
    );

    render(<RecipientsPage />);

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    // First screen explicitly uses status=ACTIVE (API helper may omit; page always sends ACTIVE default).
    expect(requests[0].status).toBe('ACTIVE');
    await waitFor(() => expect(window.location.search).toMatch(/status=ACTIVE/));

    const select = screen.getByTestId('recipient-filter-select');
    const options = within(select).getAllByRole('option').map((node) => node.textContent);
    expect(options).toEqual(['이용중', '전체', '계약종료', '대기중']);
    expect(within(select).getAllByRole('option').map((node) => (node as HTMLOptionElement).value)).toEqual([
      'ACTIVE',
      'ALL',
      'ENDED',
      'WAITING',
    ]);

    fireEvent.change(select, { target: { value: 'ALL' } });
    await waitFor(() => expect(requests.at(-1)?.status).toBe('ALL'));

    fireEvent.change(select, { target: { value: 'ENDED' } });
    await waitFor(() => expect(requests.at(-1)?.status).toBe('ENDED'));

    fireEvent.change(select, { target: { value: 'WAITING' } });
    await waitFor(() => expect(requests.at(-1)?.status).toBe('WAITING'));

    fireEvent.change(select, { target: { value: 'ACTIVE' } });
    await waitFor(() => expect(requests.at(-1)?.status).toBe('ACTIVE'));

    expect(requests.every((request) => request.status !== 'HISTORY')).toBe(true);
  });

  test('listRecipients omits status when not provided so API default remains ALL', async () => {
    const { requests } = installRecipientListFetch(() => listResponse([]));
    await listRecipients({ search: 'x', page: 1, pageSize: 10 });
    expect(requests).toHaveLength(1);
    expect(requests[0].status).toBeNull();
  });

  test('list rows do not display 이용중/계약종료/대기중 status text', async () => {
    installRecipientListFetch(() =>
      listResponse([listItem({ id: 10, name: '상태미표시' })]),
    );
    render(<RecipientsPage />);
    const row = await screen.findByRole('button', { name: /상태미표시/ });
    expect(row.textContent).not.toMatch(/이용중|계약종료|대기중/);
    expect(within(row).queryByText('이용중')).toBeNull();
    expect(within(row).queryByText('계약종료')).toBeNull();
    expect(within(row).queryByText('대기중')).toBeNull();
  });

  test('detail name save goes through basic-batch and shows success/error', async () => {
    const batchBodies: Array<Record<string, unknown>> = [];
    let detailName = '상태저장';
    let detailRowVersion = 1;
    let forceBatchError = false;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 21, name: detailName })]));
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        if (forceBatchError) {
          return jsonResponse(
            {
              error: { code: 'VALIDATION_ERROR', message: '상태 오류' },
              field_errors: [],
              details: {},
              request_id: 't-status-err',
            },
            422,
          );
        }
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (typeof recipientBody.name === 'string') detailName = recipientBody.name;
        detailRowVersion = Number(recipientBody.expected_row_version ?? detailRowVersion) + 1;
        const recipient = {
          id: 21,
          name: detailName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-001',
          postal_code: '06236',
          address: '서울시 강남구',
          home_phone: '02-111-2222',
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: detailRowVersion,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 21,
          name: detailName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-001',
          postal_code: '06236',
          address: '서울시 강남구',
          home_phone: '02-111-2222',
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: detailRowVersion,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /상태저장/ }));

    // Basic form has no recipient_status control (status is list-filter only).
    expect(screen.queryByTestId('recipient-detail-status-select')).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('상태저장'),
    );

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '상태저장수정' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchBodies.length).toBeGreaterThan(0));
    expect(batchBodies[0].recipient).toEqual(
      expect.objectContaining({
        name: '상태저장수정',
        expected_row_version: 1,
      }),
    );
    await waitFor(() =>
      expect(screen.getByText('수급자·보호자·본인부담금을 저장했습니다.')).toBeInTheDocument(),
    );

    // Error path: force 422 and assert role=alert error (draft preserved).
    forceBatchError = true;
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).not.toBeDisabled());
    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '오류이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    const errorAlert = await screen.findByRole('alert');
    expect(errorAlert).toHaveClass('recipient-inline-error');
    expect(errorAlert.textContent).toMatch(/상태 오류|저장하지 못했습니다/);
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('오류이름');

    // Create form has no status selector.
    fireEvent.click(screen.getByTestId('recipient-create-toggle'));
    expect(
      document.querySelector('#recipient-create-form [data-testid="recipient-detail-status-select"]'),
    ).toBeNull();
    expect(document.querySelector('#recipient-create-form select[name="recipient_status"]')).toBeNull();
  });

  test('delayed detail GET: status/save not usable until GET resolves with real server tag', async () => {
    type PendingDetail = { resolve: (response: Response) => void };
    const pendingDetail: PendingDetail[] = [];
    const batchBodies: Array<Record<string, unknown>> = [];

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 41, name: '지연상세' })]));
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        const recipient = {
          id: 41,
          name: typeof recipientBody.name === 'string' ? recipientBody.name : '지연상세',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ENDED' as const,
          recipient_no: 'R-041',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: Number(recipientBody.expected_row_version ?? 7) + 1,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        // Primary detail GET is deferred (not related collection GETs).
        if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname)) {
          return new Promise<Response>((resolve) => {
            pendingDetail.push({ resolve });
          });
        }
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /지연상세/ }));

    // While detail GET is pending: loading note, no save, edit locked (list cannot invent baseline).
    await waitFor(() => {
      expect(screen.getByText('상세 정보를 불러오는 중입니다.')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
    expect(screen.getByTestId('recipient-basic-edit')).toBeDisabled();
    expect(batchBodies).toHaveLength(0);

    expect(pendingDetail.length).toBeGreaterThan(0);
    pendingDetail[pendingDetail.length - 1].resolve(
      jsonResponse({
        id: 41,
        name: '지연상세',
        birth_date: '1950-03-15',
        sex_code: 'FEMALE',
        recipient_status: 'ENDED',
        recipient_no: 'R-041',
        postal_code: null,
        address: null,
        home_phone: null,
        mobile_phone: '010-1111-2222',
        memo: null,
        payer_guardian_id: null,
        row_version: 7,
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('지연상세'),
    );
    enterBasicEdit();
    const saveButton = screen.getByTestId('recipient-basic-save');
    // no-op: successful detail GET with no user edits → Save stays disabled (baseline === draft).
    expect(saveButton).toBeDisabled();

    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '지연상세수정' },
    });
    expect(saveButton).not.toBeDisabled();
    fireEvent.click(saveButton);
    await waitFor(() => expect(batchBodies.length).toBe(1));
    expect(batchBodies[0].recipient).toEqual(
      expect.objectContaining({
        name: '지연상세수정',
        expected_row_version: 7,
      }),
    );
  });

  test('rejected detail GET: visible error and zero PATCH (no ACTIVE overwrite from list)', async () => {
    const patchBodies: unknown[] = [];

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 42, name: '실패상세' })]));
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init?.body ?? '{}')));
        return jsonResponse({ detail: { code: 'should_not_patch' } }, 500);
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname)) {
          return jsonResponse(
            {
              error: { code: 'RECIPIENT_NOT_FOUND', message: '수급자를 찾을 수 없습니다.' },
              field_errors: [],
              details: {},
              request_id: 't-detail-fail',
            },
            404,
          );
        }
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /실패상세/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveClass('recipient-inline-error');
    expect(alert.textContent).toBeTruthy();
    expect(screen.queryByTestId('recipient-detail-status-select')).toBeNull();
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
    expect(patchBodies).toHaveLength(0);
  });

  test('ROW_VERSION_CONFLICT reloads latest detail, preserves draft, reapplies with latest row_version', async () => {
    // Different-field conflict: user changes mobile only; concurrent server changes name only.
    const batchBodies: Array<Record<string, unknown>> = [];
    const reapplyBodies: Array<Record<string, unknown>> = [];
    let detailGets = 0;
    let serverRowVersion = 1;
    let serverName = '충돌원본';
    let serverMobile = '010-1111-2222';

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([listItem({ id: 31, name: serverName, row_version: serverRowVersion })]),
        );
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (Number(recipientBody.expected_row_version) !== serverRowVersion) {
          return jsonResponse(
            {
              error: {
                code: 'ROW_VERSION_CONFLICT',
                message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
              },
              field_errors: [],
              details: { current_row_version: serverRowVersion },
              request_id: 't-conflict',
            },
            409,
          );
        }
        if (typeof recipientBody.name === 'string') serverName = recipientBody.name;
        if (typeof recipientBody.mobile_phone === 'string') serverMobile = recipientBody.mobile_phone;
        serverRowVersion = Number(recipientBody.expected_row_version) + 1;
        const recipient = {
          id: 31,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-031',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        const body = parseJsonBody(init);
        reapplyBodies.push(body);
        if (typeof body.name === 'string') serverName = body.name;
        if (typeof body.mobile_phone === 'string') serverMobile = body.mobile_phone;
        serverRowVersion = Number(body.expected_row_version) + 1;
        return jsonResponse({
          id: 31,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-031',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        detailGets += 1;
        return jsonResponse({
          id: 31,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-031',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /충돌원본/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('충돌원본'));

    // Concurrent server changes name only (different field from user's mobile edit).
    serverRowVersion = 5;
    serverName = '서버최신이름';

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-mobile-phone-input'), {
      target: { value: '010-9999-8888' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    const conflictAlerts = await screen.findAllByRole('alert');
    expect(conflictAlerts).toHaveLength(1);
    expect(conflictAlerts[0].textContent).toBe(
      '다른 사용자가 먼저 변경했습니다. 최신 서버값을 확인하고 필요한 변경만 다시 적용해주세요.',
    );
    await waitFor(() => expect(screen.getByTestId('recipient-stale-latest-value')).toHaveTextContent('서버최신이름'));
    // User mobile draft preserved; server name applied onto the form baseline.
    expect(screen.getByTestId('recipient-detail-mobile-phone-input')).toHaveValue('010-9999-8888');
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('서버최신이름');
    expect(detailGets).toBeGreaterThan(1);

    // Post-conflict re-edit: change mobile again before reapply; PATCH must carry new value.
    fireEvent.change(screen.getByTestId('recipient-detail-mobile-phone-input'), {
      target: { value: '010-7777-6666' },
    });
    fireEvent.click(screen.getByTestId('recipient-stale-reapply'));
    await waitFor(() =>
      expect(reapplyBodies.some((body) => body.expected_row_version === 5)).toBe(true),
    );
    const reapplyBody = reapplyBodies.find((body) => body.expected_row_version === 5);
    expect(reapplyBody).toEqual({
      expected_row_version: 5,
      mobile_phone: '010-7777-6666',
    });
    expect(reapplyBody).not.toHaveProperty('name');
    await waitFor(() =>
      expect(screen.getByText('최신 버전에 변경 내용을 다시 적용했습니다.')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('recipient-stale-reapply')).toBeNull();
    expect(batchBodies).toHaveLength(1);
  });

  test('ROW_VERSION_CONFLICT reapply omits untouched sex_code so concurrent sex change is preserved', async () => {
    // User edits only name; concurrent server sets sex MALE only (different field).
    const batchBodies: Array<Record<string, unknown>> = [];
    const reapplyBodies: Array<Record<string, unknown>> = [];
    let serverRowVersion = 1;
    let serverName = '상태충돌원본';
    let serverSex: 'MALE' | 'FEMALE' = 'FEMALE';

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([listItem({ id: 32, name: serverName, row_version: serverRowVersion })]),
        );
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (Number(recipientBody.expected_row_version) !== serverRowVersion) {
          return jsonResponse(
            {
              error: {
                code: 'ROW_VERSION_CONFLICT',
                message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
              },
              field_errors: [],
              details: { current_row_version: serverRowVersion },
              request_id: 't-conflict-status-preserve',
            },
            409,
          );
        }
        if (typeof recipientBody.name === 'string') serverName = recipientBody.name;
        if (recipientBody.sex_code === 'MALE' || recipientBody.sex_code === 'FEMALE') {
          serverSex = recipientBody.sex_code;
        }
        serverRowVersion = Number(recipientBody.expected_row_version) + 1;
        const recipient = {
          id: 32,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: serverSex,
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-032',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        const body = parseJsonBody(init);
        reapplyBodies.push(body);
        if (typeof body.name === 'string') serverName = body.name;
        if (body.sex_code === 'MALE' || body.sex_code === 'FEMALE') serverSex = body.sex_code;
        serverRowVersion = Number(body.expected_row_version) + 1;
        return jsonResponse({
          id: 32,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: serverSex,
          recipient_status: 'ACTIVE',
          recipient_no: 'R-032',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 32,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: serverSex,
          recipient_status: 'ACTIVE',
          recipient_no: 'R-032',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /상태충돌원본/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('상태충돌원본'));
    expect(screen.getByTestId('recipient-detail-sex-code-select')).toHaveValue('FEMALE');

    // Concurrent server: sex MALE only; name unchanged so no same-field collision on name.
    serverRowVersion = 5;
    serverSex = 'MALE';

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '이름만수정' },
    });
    expect(screen.getByTestId('recipient-detail-sex-code-select')).toHaveValue('FEMALE');
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    const conflictAlerts = await screen.findAllByRole('alert');
    expect(conflictAlerts).toHaveLength(1);
    expect(conflictAlerts[0].textContent).toBe(
      '다른 사용자가 먼저 변경했습니다. 최신 서버값을 확인하고 필요한 변경만 다시 적용해주세요.',
    );
    await waitFor(() =>
      expect(screen.getByTestId('recipient-stale-latest-value')).toHaveTextContent('상태충돌원본'),
    );
    // User name preserved; form shows server MALE for sex (merged baseline).
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('이름만수정');
    expect(screen.getByTestId('recipient-detail-sex-code-select')).toHaveValue('MALE');

    // Re-edit name after conflict; reapply must send re-edited value, not the pre-conflict draft alone.
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '재편집이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-stale-reapply'));
    await waitFor(() =>
      expect(reapplyBodies.some((body) => body.expected_row_version === 5)).toBe(true),
    );
    const reapplyBody = reapplyBodies.find((body) => body.expected_row_version === 5);
    expect(reapplyBody).toEqual({
      expected_row_version: 5,
      name: '재편집이름',
    });
    expect(reapplyBody).not.toHaveProperty('sex_code');

    await waitFor(() =>
      expect(screen.getByText('최신 버전에 변경 내용을 다시 적용했습니다.')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('recipient-detail-sex-code-select')).toHaveValue('MALE');
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('재편집이름');
    expect(serverSex).toBe('MALE');
    expect(batchBodies).toHaveLength(1);
  });

  test('same-field ROW_VERSION_CONFLICT shows exact alert, separate conflict log, no reapply', async () => {
    const batchBodies: Array<Record<string, unknown>> = [];
    let serverRowVersion = 1;
    let serverName = '동일필드충돌';

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([listItem({ id: 33, name: serverName, row_version: serverRowVersion })]),
        );
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (Number(recipientBody.expected_row_version) !== serverRowVersion) {
          return jsonResponse(
            {
              error: {
                code: 'ROW_VERSION_CONFLICT',
                message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
              },
              field_errors: [],
              details: { current_row_version: serverRowVersion },
              request_id: 't-same-field',
            },
            409,
          );
        }
        if (typeof recipientBody.name === 'string') serverName = recipientBody.name;
        serverRowVersion = Number(recipientBody.expected_row_version) + 1;
        const recipient = {
          id: 33,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE' as const,
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-033',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 33,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-033',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /동일필드충돌/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('동일필드충돌'));

    // Concurrent server also changed name (same field as user draft).
    serverRowVersion = 5;
    serverName = '서버이름';

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '사용자이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toBe('이미 수정되었습니다');
    // Latest server values + conflict log must sit outside the alert.
    expect(alerts[0].textContent).not.toContain('사용자이름');
    expect(alerts[0].textContent).not.toContain('서버이름');
    expect(screen.getByTestId('recipient-stale-latest-value')).toHaveTextContent('서버이름');
    const conflictLog = screen.getByTestId('recipient-same-field-conflict-log');
    expect(conflictLog).toBeInTheDocument();
    expect(conflictLog).not.toHaveAttribute('role', 'alert');
    expect(screen.getByTestId('recipient-conflict-field-name')).toHaveTextContent('이름');
    expect(screen.getByTestId('recipient-conflict-field-name')).toHaveTextContent('사용자이름');
    expect(screen.getByTestId('recipient-conflict-field-name')).toHaveTextContent('서버이름');
    // Form field set to server latest; no automatic reapply.
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('서버이름');
    expect(screen.queryByTestId('recipient-stale-reapply')).toBeNull();
    // Only the initial failing basic-batch; no auto reapply.
    expect(batchBodies).toHaveLength(1);

    // User must re-edit the latest baseline before saving the conflicting field.
    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '재편집후이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    expect(batchBodies[1].recipient).toEqual({
      expected_row_version: 5,
      name: '재편집후이름',
    });
    // Name-only re-save must not invent a copay CREATE (activeCopayPeriod null + dirty-unaware
    // buildCopayBenefitMutations would otherwise open a new benefit period every save).
    expect(batchBodies[1].benefit_periods).toEqual([]);
    expect(batchBodies[1].preserve_payer).toBe(false);
  });

  test('mixed same-field + disjoint ROW_VERSION_CONFLICT preserves non-conflicting user edit', async () => {
    // User changes name + mobile; server changes only name → name→server, mobile preserved.
    const batchBodies: Array<Record<string, unknown>> = [];
    let serverRowVersion = 1;
    let serverName = '혼합충돌원본';
    let serverMobile = '010-1111-2222';

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([listItem({ id: 36, name: serverName, row_version: serverRowVersion })]),
        );
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (Number(recipientBody.expected_row_version) !== serverRowVersion) {
          return jsonResponse(
            {
              error: {
                code: 'ROW_VERSION_CONFLICT',
                message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
              },
              field_errors: [],
              details: { current_row_version: serverRowVersion },
              request_id: 't-mixed-conflict',
            },
            409,
          );
        }
        if (typeof recipientBody.name === 'string') serverName = recipientBody.name;
        if (typeof recipientBody.mobile_phone === 'string') serverMobile = recipientBody.mobile_phone;
        serverRowVersion = Number(recipientBody.expected_row_version) + 1;
        const recipient = {
          id: 36,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE' as const,
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-036',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 36,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-036',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverRowVersion,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /혼합충돌원본/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('혼합충돌원본'));

    serverRowVersion = 7;
    serverName = '서버혼합이름';

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '사용자혼합이름' },
    });
    fireEvent.change(screen.getByTestId('recipient-detail-mobile-phone-input'), {
      target: { value: '010-3333-4444' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    const alerts = await screen.findAllByRole('alert');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toBe('이미 수정되었습니다');
    expect(screen.getByTestId('recipient-conflict-field-name')).toHaveTextContent('사용자혼합이름');
    expect(screen.getByTestId('recipient-conflict-field-name')).toHaveTextContent('서버혼합이름');
    // Same-field name → server; disjoint mobile → preserved.
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('서버혼합이름');
    expect(screen.getByTestId('recipient-detail-mobile-phone-input')).toHaveValue('010-3333-4444');
    expect(screen.queryByTestId('recipient-stale-reapply')).toBeNull();
    expect(batchBodies).toHaveLength(1);

    // Save remaining disjoint edit against latest row_version (no stale draft resend of name).
    enterBasicEdit();
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    expect(batchBodies[1].recipient).toEqual({
      expected_row_version: 7,
      mobile_phone: '010-3333-4444',
    });
    expect(batchBodies[1].recipient as Record<string, unknown>).not.toHaveProperty('name');
  });

  test('no-op Save is disabled and sends zero basic-batch; exact keys for name/mobile/both; whitespace no-op', async () => {
    const batchBodies: Array<Record<string, unknown>> = [];
    let serverName = '변경감지';
    let serverMobile = '010-1111-2222';
    let serverVersion = 1;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 34, name: serverName })]));
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (typeof recipientBody.name === 'string') serverName = recipientBody.name;
        if (typeof recipientBody.mobile_phone === 'string') serverMobile = recipientBody.mobile_phone;
        serverVersion = Number(recipientBody.expected_row_version) + 1;
        const recipient = {
          id: 34,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE' as const,
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-034',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverVersion,
        };
        return jsonResponse({ recipient, guardians: [], saved_sections: ['recipient'] });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 34,
          name: serverName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-034',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: serverMobile,
          memo: null,
          payer_guardian_id: null,
          row_version: serverVersion,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /변경감지/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('변경감지'));

    enterBasicEdit();
    const save = screen.getByTestId('recipient-basic-save');
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(batchBodies).toHaveLength(0);

    // Trailing whitespace on name that trims equal to baseline → no-op (disabled Save, zero batch).
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '변경감지   ' },
    });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(batchBodies).toHaveLength(0);

    // Name-only — exact recipient key set
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '이름변경' },
    });
    expect(save).not.toBeDisabled();
    fireEvent.click(save);
    await waitFor(() => expect(batchBodies.length).toBe(1));
    expect(Object.keys(batchBodies[0].recipient as object).sort()).toEqual(
      ['expected_row_version', 'name'].sort(),
    );
    expect(batchBodies[0].recipient).toEqual({ name: '이름변경', expected_row_version: 1 });

    // After success form matches server; re-enter edit with no changes → save disabled again.
    await waitFor(() => expect(screen.queryByTestId('recipient-basic-save')).toBeNull());
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).not.toBeDisabled());
    enterBasicEdit();
    expect(screen.getByTestId('recipient-basic-save')).toBeDisabled();

    // Mobile-only — exact recipient key set
    fireEvent.change(screen.getByTestId('recipient-detail-mobile-phone-input'), {
      target: { value: '010-2222-3333' },
    });
    expect(screen.getByTestId('recipient-basic-save')).not.toBeDisabled();
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    expect(Object.keys(batchBodies[1].recipient as object).sort()).toEqual(
      ['expected_row_version', 'mobile_phone'].sort(),
    );
    expect(batchBodies[1].recipient).toEqual({
      mobile_phone: '010-2222-3333',
      expected_row_version: 2,
    });
    await waitFor(() => expect(screen.queryByTestId('recipient-basic-save')).toBeNull());
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).not.toBeDisabled());
    enterBasicEdit();

    // Both — exact key set
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '둘다' },
    });
    fireEvent.change(screen.getByTestId('recipient-detail-mobile-phone-input'), {
      target: { value: '010-4444-5555' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(3));
    expect(Object.keys(batchBodies[2].recipient as object).sort()).toEqual(
      ['expected_row_version', 'mobile_phone', 'name'].sort(),
    );
    expect(batchBodies[2].recipient).toEqual({
      name: '둘다',
      mobile_phone: '010-4444-5555',
      expected_row_version: 3,
    });
    await waitFor(() => expect(screen.queryByTestId('recipient-basic-save')).toBeNull());
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).not.toBeDisabled());
    enterBasicEdit();

    // Revert-to-original disables Save without batch
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '임시' },
    });
    expect(screen.getByTestId('recipient-basic-save')).not.toBeDisabled();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '둘다' },
    });
    expect(screen.getByTestId('recipient-basic-save')).toBeDisabled();
    expect(batchBodies).toHaveLength(3);
  });

  test('malformed detail (null recipient_status) blocks editor and Save/PATCH', async () => {
    const patchBodies: unknown[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 35, name: '불량상세' })]));
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init?.body ?? '{}')));
        return jsonResponse({ detail: { code: 'no' } }, 500);
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 35,
          name: '불량상세',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: null,
          recipient_no: 'R-035',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /불량상세/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/올바르지 않아|불러오지 못/);
    expect(screen.queryByTestId('recipient-detail-status-select')).toBeNull();
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
    expect(patchBodies).toHaveLength(0);
  });

  test('malformed detail (wrong recipient id) blocks editor and Save/PATCH', async () => {
    const patchBodies: unknown[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 36, name: '잘못된아이디' })]));
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init?.body ?? '{}')));
        return jsonResponse({ detail: { code: 'no' } }, 500);
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 9999,
          name: '잘못된아이디',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-036',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /잘못된아이디/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/올바르지 않아|불러오지 못/);
    expect(screen.queryByTestId('recipient-detail-status-select')).toBeNull();
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
    expect(patchBodies).toHaveLength(0);
  });

  test('malformed detail (missing recipient_status) blocks editor and Save/PATCH', async () => {
    const patchBodies: unknown[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 37, name: '상태누락' })]));
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init?.body ?? '{}')));
        return jsonResponse({ detail: { code: 'no' } }, 500);
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 37,
          name: '상태누락',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_no: 'R-037',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /상태누락/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/올바르지 않아|불러오지 못/);
    expect(screen.queryByTestId('recipient-detail-status-select')).toBeNull();
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
    expect(patchBodies).toHaveLength(0);
  });

  test('malformed detail (invalid recipient_status) blocks editor and Save/PATCH', async () => {
    const patchBodies: unknown[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 38, name: '상태무효' })]));
      }
      if (/^\/api\/v1\/recipients\/\d+$/.test(url.pathname) && method === 'PATCH') {
        patchBodies.push(JSON.parse(String(init?.body ?? '{}')));
        return jsonResponse({ detail: { code: 'no' } }, 500);
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 38,
          name: '상태무효',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'HISTORY',
          recipient_no: 'R-038',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /상태무효/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/올바르지 않아|불러오지 못/);
    expect(screen.queryByTestId('recipient-detail-status-select')).toBeNull();
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
    expect(patchBodies).toHaveLength(0);
  });

  test('detail inputs and Save disabled while save in flight', async () => {
    const batchBodies: unknown[] = [];
    let releaseBatch: ((value: Response) => void) | null = null;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 39, name: '저장중잠금' })]));
      }
      if (isBasicUpdateBatch(url, method)) {
        batchBodies.push(parseJsonBody(init));
        return new Promise<Response>((resolve) => {
          releaseBatch = resolve;
        });
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 39,
          name: '저장중잠금',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-039',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /저장중잠금/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('저장중잠금'));

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '저장중이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchBodies).toHaveLength(1));
    // Every detail input/select and Save must be disabled while save is in flight.
    expect(screen.getByTestId('recipient-detail-name-input')).toBeDisabled();
    expect(screen.getByTestId('recipient-detail-birth-date-input')).toBeDisabled();
    expect(screen.getByTestId('recipient-detail-sex-code-select')).toBeDisabled();
    expect(screen.getByTestId('recipient-detail-mobile-phone-input')).toBeDisabled();
    const detailForm = screen.getByTestId('recipient-detail-name-input').closest('form');
    expect(detailForm).not.toBeNull();
    const pendingInputs = detailForm!.querySelectorAll('input, select, textarea');
    expect(pendingInputs.length).toBeGreaterThanOrEqual(8);
    pendingInputs.forEach((node) => {
      expect(node).toBeDisabled();
    });
    expect(screen.getByTestId('recipient-basic-save')).toBeDisabled();

    releaseBatch?.(
      jsonResponse({
        recipient: {
          id: 39,
          name: '저장중이름',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-039',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 2,
        },
        guardians: [],
        saved_sections: ['recipient'],
      }),
    );
    await waitFor(() => expect(screen.queryByTestId('recipient-basic-save')).toBeNull());
    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('저장중이름'),
    );
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).not.toBeDisabled());
    enterBasicEdit();
    expect(screen.getByTestId('recipient-basic-save')).toBeDisabled();
  });

  test('create basic-batch payload has no recipient_status field', async () => {
    const postBodies: Array<Record<string, unknown>> = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([]));
      }
      if (isBasicCreateBatch(url, method)) {
        const body = parseJsonBody(init);
        postBodies.push(body);
        // Mirror backend RecipientBasicCreateBatchRequest.require_benefit_periods:
        // empty benefit_periods is a validation error (422), not a successful create.
        const benefitPeriods = body.benefit_periods;
        if (!Array.isArray(benefitPeriods) || benefitPeriods.length === 0) {
          return jsonResponse(
            {
              error: { code: 'VALIDATION_ERROR', message: '입력값을 확인하세요.' },
              field_errors: [
                {
                  field: 'benefit_periods',
                  message: 'at least one benefit period is required',
                },
              ],
              details: {},
              request_id: 't-create-benefit-required',
            },
            422,
          );
        }
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        const recipient = {
          id: 99,
          name: recipientBody.name,
          birth_date: recipientBody.birth_date,
          sex_code: recipientBody.sex_code,
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: recipientBody.postal_code ?? null,
          address: recipientBody.address ?? null,
          home_phone: recipientBody.home_phone ?? null,
          mobile_phone: recipientBody.mobile_phone ?? null,
          memo: recipientBody.memo ?? null,
          payer_guardian_id: null,
          row_version: 1,
        };
        // Match backend create_basic saved_sections order.
        const saved_sections = ['recipient'];
        const guardiansBody = body.guardians;
        if (Array.isArray(guardiansBody) && guardiansBody.length > 0) {
          saved_sections.push('guardians');
        }
        if (body.payer_guardian_slot !== null && body.payer_guardian_slot !== undefined) {
          saved_sections.push('payer');
        }
        saved_sections.push('benefit_periods');
        return jsonResponse({ recipient, guardians: [], saved_sections }, 201);
      }
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 99,
          name: '생성수급',
          birth_date: '1960-01-01',
          sex_code: 'MALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1000-0002',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByTestId('recipient-create-toggle'));
    const createForm = document.getElementById('recipient-create-form');
    expect(createForm).toBeTruthy();
    // Create form focuses on mobile (no separate home-phone field on basic form).
    const mobilePhoneInput = within(createForm!).getByTestId('recipient-mobile-phone-input');
    expect(within(createForm!).queryByTestId('recipient-home-phone-input')).toBeNull();

    // Focusing an empty live mobile input must not inject a 010- prefix (W1B paste/fill race).
    expect(mobilePhoneInput).toHaveValue('');
    fireEvent.focus(mobilePhoneInput);
    expect(mobilePhoneInput).toHaveValue('');

    fireEvent.change(screen.getByTestId('recipient-name-input'), { target: { value: '생성수급' } });
    fireEvent.change(screen.getByTestId('recipient-birth-date-input'), {
      target: { value: '1960-01-01' },
    });
    fireEvent.change(mobilePhoneInput, {
      target: { value: '010-1000-0002' },
    });
    expect(mobilePhoneInput).toHaveValue('010-1000-0002');
    // After createOpen, the same toggle is the live external submit control.
    const submitToggle = screen.getByTestId('recipient-create-toggle');
    expect(submitToggle).toHaveAttribute('form', 'recipient-create-form');
    expect(submitToggle).toHaveAttribute('type', 'submit');
    fireEvent.click(submitToggle);

    await waitFor(() => expect(postBodies.length).toBe(1));
    const body = postBodies[0];
    const recipientBody = body.recipient as Record<string, unknown>;
    expect(recipientBody).not.toHaveProperty('recipient_status');
    expect(Object.keys(recipientBody)).not.toContain('recipient_status');
    expect(recipientBody.name).toBe('생성수급');
    expect(recipientBody.mobile_phone).toBe('010-1000-0002');
    expect(body).toHaveProperty('benefit_periods');
    expect(Array.isArray(body.benefit_periods)).toBe(true);
    expect((body.benefit_periods as unknown[]).length).toBeGreaterThan(0);
    const firstBenefit = (body.benefit_periods as Array<Record<string, unknown>>)[0];
    expect(firstBenefit).toEqual(
      expect.objectContaining({
        payload: expect.objectContaining({
          benefit_code: expect.any(String),
          start_date: expect.any(String),
        }),
      }),
    );
    expect(body).toHaveProperty('guardians');
  });

  test('renders grade_code, benefit_code, copayment_rate, and multi services from server response', async () => {
    installRecipientListFetch(() =>
      listResponse([
        listItem({
          id: 7,
          name: '표시검증',
          grade_code: '4',
          benefit_code: 'REDUCED',
          copayment_rate: 7.5,
          services: [
            {
              service_group_code: 'DAY',
              display_name: '주야간보호',
              service_types: [
                { service_type_code: 'D1', display_name: '주간' },
                { service_type_code: 'D2', display_name: '야간' },
              ],
            },
            {
              service_group_code: 'NURSE',
              display_name: '방문간호',
              service_types: [{ service_type_code: 'N1', display_name: '기본간호' }],
            },
          ],
        }),
      ]),
    );

    render(<RecipientsPage />);

    const row = await screen.findByRole('button', { name: /표시검증/ });
    expect(within(row).getByTestId('recipient-list-grade')).toHaveTextContent('4등급');
    expect(within(row).getByTestId('recipient-list-benefit')).toHaveTextContent('REDUCED');
    expect(within(row).getByTestId('recipient-list-copay-rate')).toHaveTextContent('7.5%');
    expect(within(row).getByTestId('recipient-list-services')).toHaveTextContent('주야간보호');
    expect(within(row).getByTestId('recipient-list-services')).toHaveTextContent('주간');
    expect(within(row).getByTestId('recipient-list-services')).toHaveTextContent('야간');
    expect(within(row).getByTestId('recipient-list-services')).toHaveTextContent('방문간호');
    expect(within(row).getByTestId('recipient-list-services')).toHaveTextContent('기본간호');
  });

  test('null projection fields render honest empty labels without inventing values', async () => {
    installRecipientListFetch(() =>
      listResponse([
        listItem({
          id: 3,
          name: '널표시',
          grade_code: null,
          benefit_code: null,
          copayment_rate: null,
          services: [],
        }),
      ]),
    );

    render(<RecipientsPage />);

    const row = await screen.findByRole('button', { name: /널표시/ });
    expect(within(row).getByTestId('recipient-list-grade')).toHaveTextContent('미지정');
    expect(within(row).getByTestId('recipient-list-benefit')).toHaveTextContent('없음');
    // null copayment_rate must not invent 일반/0% — honest empty label.
    expect(within(row).getByTestId('recipient-list-copay-rate')).toHaveTextContent('미지정');
    expect(within(row).getByTestId('recipient-list-services')).toHaveTextContent('없음');
  });

  test('list keeps five columns and has no prev/next/page indicator', async () => {
    installRecipientListFetch(() =>
      listResponse([listItem({ id: 1, name: '컬럼검증' })]),
    );
    render(<RecipientsPage />);
    await screen.findByRole('button', { name: /컬럼검증/ });

    const header = screen.getByTestId('recipient-list-header');
    const headerLabels = within(header)
      .getAllByText(/./)
      .map((node) => node.textContent?.trim())
      .filter(Boolean);
    // Header is five direct spans: 등급, 이름, 나이, 본·부%, 제공중 서비스.
    expect(header.children).toHaveLength(5);
    expect(Array.from(header.children).map((node) => node.textContent)).toEqual([
      '등급',
      '이름',
      '나이',
      '본·부%',
      '제공중 서비스',
    ]);
    expect(headerLabels).toEqual(['등급', '이름', '나이', '본·부%', '제공중 서비스']);

    expect(screen.queryByTestId('recipient-page-prev')).toBeNull();
    expect(screen.queryByTestId('recipient-page-next')).toBeNull();
    expect(screen.queryByTestId('recipient-page-indicator')).toBeNull();
    expect(document.querySelector('.recipient-list-footer')).toBeNull();
  });

  test('search resets to page 1; scroll appends page 2 without replacing prior rows', async () => {
    const { requests } = installRecipientListFetch((query) => {
      const page = Number(query.page ?? '1');
      if (query.search === '검색어') {
        return listResponse(
          [listItem({ id: 99, name: '서버검색결과', grade_code: '2' })],
          1,
          1,
          100,
        );
      }
      if (page === 2) {
        return listResponse(
          [listItem({ id: 20, name: '페이지2행', grade_code: '1' })],
          3,
          2,
          2,
        );
      }
      // Deliberately reverse of name ASC so client sort would fail the assertion.
      return listResponse(
        [
          listItem({ id: 2, name: '홍길동', grade_code: '5' }),
          listItem({ id: 1, name: '가나다', grade_code: '3' }),
        ],
        3,
        1,
        2,
      );
    });

    render(<RecipientsPage />);

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(requests[0].page).toBe('1');
    const namesOnFirstPaint = screen
      .getAllByTestId('recipient-name-option')
      .map((node) => node.textContent ?? '');
    expect(namesOnFirstPaint[0]).toContain('홍길동');
    expect(namesOnFirstPaint[1]).toContain('가나다');

    fireEvent.change(screen.getByTestId('recipient-search-input'), {
      target: { value: '검색어' },
    });

    await waitFor(() => {
      expect(requests.at(-1)?.search).toBe('검색어');
      expect(requests.at(-1)?.page).toBe('1');
    });
    expect(await screen.findByRole('button', { name: /서버검색결과/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /홍길동/ })).toBeNull();

    // Reset search so infinite-scroll uses the multi-page total fixture.
    fireEvent.change(screen.getByTestId('recipient-search-input'), {
      target: { value: '' },
    });
    await waitFor(() => {
      expect(requests.at(-1)?.search).toBeNull();
      expect(requests.at(-1)?.page).toBe('1');
    });
    expect(await screen.findByRole('button', { name: /홍길동/ })).toBeInTheDocument();

    const beforeAppend = requests.length;
    scrollListNearBottom();

    await waitFor(() => expect(requests.at(-1)?.page).toBe('2'));
    expect(requests.length).toBe(beforeAppend + 1);
    expect(await screen.findByRole('button', { name: /페이지2행/ })).toBeInTheDocument();
    // Append keeps page-1 rows.
    expect(screen.getByRole('button', { name: /홍길동/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /가나다/ })).toBeInTheDocument();
  });

  test('infinite scroll dedupes by id, stops at total, and guards concurrent load-more', async () => {
    const { requests } = installRecipientListFetch((query) => {
      const page = Number(query.page ?? '1');
      const pageSize = 2;
      const all = [
        listItem({ id: 1, name: 'A수급' }),
        listItem({ id: 2, name: 'B수급' }),
        listItem({ id: 3, name: 'C수급' }),
        listItem({ id: 4, name: 'D수급' }),
        listItem({ id: 5, name: 'E수급' }),
      ];
      if (page === 1) {
        return listResponse(all.slice(0, 2), all.length, 1, pageSize);
      }
      if (page === 2) {
        // Intentionally include id 2 again so the client must dedupe on append.
        return listResponse(
          [listItem({ id: 2, name: 'B수급-중복' }), listItem({ id: 3, name: 'C수급' })],
          all.length,
          2,
          pageSize,
        );
      }
      if (page === 3) {
        return listResponse(all.slice(3, 5), all.length, 3, pageSize);
      }
      // Past total: empty page must not be requested by the client after hasMore=false.
      return listResponse([], all.length, page, pageSize);
    });

    render(<RecipientsPage />);
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(requests[0]).toEqual(
      expect.objectContaining({ page: '1', page_size: '100', status: 'ACTIVE' }),
    );
    expect(await screen.findByRole('button', { name: /A수급/ })).toBeInTheDocument();
    expect(screen.getAllByTestId('recipient-name-option')).toHaveLength(2);

    // Concurrent near-bottom scrolls must not fire multiple page-2 requests.
    scrollListNearBottom();
    scrollListNearBottom();
    scrollListNearBottom();

    await waitFor(() => expect(requests.some((request) => request.page === '2')).toBe(true));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /C수급/ })).toBeInTheDocument();
    });
    const page2Count = requests.filter((request) => request.page === '2').length;
    expect(page2Count).toBe(1);
    // id=2 kept once (first occurrence), not replaced by duplicate page-2 payload name.
    const rowsAfterPage2 = screen.getAllByTestId('recipient-name-option');
    expect(rowsAfterPage2).toHaveLength(3);
    expect(rowsAfterPage2.map((node) => node.textContent ?? '').join('|')).toContain('B수급');
    expect(rowsAfterPage2.map((node) => node.textContent ?? '').join('|')).not.toContain('B수급-중복');

    scrollListNearBottom();
    await waitFor(() => expect(requests.some((request) => request.page === '3')).toBe(true));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /E수급/ })).toBeInTheDocument();
    });
    // items.length (5) >= total (5) → no further page requests.
    const afterTotal = requests.length;
    scrollListNearBottom();
    scrollListNearBottom();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(requests.length).toBe(afterTotal);
    expect(requests.filter((request) => request.page === '4')).toHaveLength(0);
    expect(screen.getAllByTestId('recipient-name-option')).toHaveLength(5);
  });

  test('status change resets rows to page 1; stale delayed page-2 does not overwrite', async () => {
    type Pending = {
      query: ListQuery;
      resolve: (response: Response) => void;
      signal?: AbortSignal | null;
    };
    const pending: Pending[] = [];
    const requests: ListQuery[] = [];
    // Sentinel: increments when the late ACTIVE page-2 body is actually decoded (json()).
    // DOM-only waitFor can pass before page-2 settles; this observes real continuation.
    let latePage2Settled = 0;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        const query = parseListQuery(url);
        requests.push(query);
        return new Promise<Response>((resolve, reject) => {
          const entry: Pending = { query, resolve, signal: init?.signal ?? null };
          // page-2: uncooperative server — observe abort via signal.aborted but do not
          // reject the promise, so a late resolve can still reach generation/stale guards.
          // page-1 (initial ACTIVE + new ENDED): keep cooperative abort + manual resolve.
          if (query.page === '2') {
            pending.push(entry);
            return;
          }
          const onAbort = () => {
            const abortError = new Error('Aborted');
            abortError.name = 'AbortError';
            reject(abortError);
          };
          if (init?.signal?.aborted) {
            onAbort();
            return;
          }
          init?.signal?.addEventListener('abort', onAbort, { once: true });
          pending.push(entry);
        });
      }

      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        return jsonResponse({
          id: 1,
          name: '지연행',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE' as const,
          recipient_no: 'R-001',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    await waitFor(() => expect(pending.length).toBe(1));
    pending[0].resolve(
      jsonResponse(
        listResponse(
          [listItem({ id: 1, name: '이용중행' }), listItem({ id: 2, name: '이용중행2' })],
          4,
          1,
          2,
        ),
      ),
    );
    // Exact strong name: must not match '이용중행2' (substring/accessible-name clash).
    await waitFor(() => {
      expect(hasRecipientRowWithExactName('이용중행')).toBe(true);
    });

    scrollListNearBottom();
    await waitFor(() => expect(requests.some((request) => request.page === '2')).toBe(true));
    const page2Pending = pending.filter((entry) => entry.query.page === '2');
    expect(page2Pending.length).toBe(1);
    const page2Signal = page2Pending[0].signal;
    expect(page2Signal).toBeTruthy();
    // Still in flight before filter change.
    expect(page2Signal!.aborted).toBe(false);

    // Change status before page-2 resolves → reset to page 1 under new status.
    fireEvent.change(screen.getByTestId('recipient-filter-select'), {
      target: { value: 'ENDED' },
    });
    await waitFor(() =>
      expect(requests.some((request) => request.status === 'ENDED' && request.page === '1')).toBe(
        true,
      ),
    );
    await waitFor(() => {
      expect(hasRecipientRowWithExactName('이용중행')).toBe(false);
      expect(screen.getByTestId('recipient-list-loading')).toBeInTheDocument();
    });

    // Abort evidence first: filter reset must abort the in-flight load-more signal.
    await waitFor(() => {
      expect(page2Signal!.aborted).toBe(true);
    });
    // Real abort was true. Temporarily force aborted=false so apiRequest processes the late
    // body fully — this isolates generation/stale guard from the abort-only short-circuit.
    expect(page2Signal!.aborted).toBe(true);
    Object.defineProperty(page2Signal!, 'aborted', {
      configurable: true,
      enumerable: true,
      get: () => false,
    });
    expect(page2Signal!.aborted).toBe(false);

    // Apply new ENDED page-1 first so the list is non-null before the late page-2 arrives.
    // (If page-2 resolved while current===null, !current replace could mask missing guards.)
    const endedPage1 = pending.filter(
      (entry) => entry.query.status === 'ENDED' && entry.query.page === '1',
    );
    expect(endedPage1.length).toBeGreaterThan(0);
    endedPage1[endedPage1.length - 1].resolve(
      jsonResponse(listResponse([listItem({ id: 30, name: '계약종료행' })], 1, 1, 100)),
    );

    expect(await screen.findByRole('button', { name: /계약종료행/ })).toBeInTheDocument();
    expect(screen.getAllByTestId('recipient-name-option')).toHaveLength(1);
    expect(hasRecipientRowWithExactName('이용중행')).toBe(false);
    expect(hasRecipientRowWithExactName('늦은페이지2')).toBe(false);

    // Late page-2 (old ACTIVE filter) must not append into the already-applied ENDED list.
    // Response-like fixture: count json decode so waitFor cannot succeed before continuation.
    page2Pending[0].resolve({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => {
        latePage2Settled += 1;
        return listResponse([listItem({ id: 90, name: '늦은페이지2' })], 4, 2, 2);
      },
    } as Response);

    // First: observe real late page-2 decode/continuation (not pre-true DOM conditions).
    await waitFor(() => expect(latePage2Settled).toBe(1));

    // Then: final DOM — generation guard must have dropped the stale append.
    // If the guard is removed, late page-2 appends and this assertion fails.
    expect(screen.getAllByTestId('recipient-name-option')).toHaveLength(1);
    expect(hasRecipientRowWithExactName('계약종료행')).toBe(true);
    expect(screen.queryByRole('button', { name: /늦은페이지2/ })).toBeNull();
    expect(hasRecipientRowWithExactName('늦은페이지2')).toBe(false);
  });

  test('list row keeps full multi-line service and copay text in the DOM (M1)', async () => {
    const longServices = [
      {
        service_group_code: 'VISIT',
        display_name: '방문요양',
        service_types: [
          { service_type_code: 'V1', display_name: '일반방문요양서비스' },
          { service_type_code: 'V2', display_name: '야간방문요양서비스' },
          { service_type_code: 'V3', display_name: '휴일방문요양서비스' },
        ],
      },
      {
        service_group_code: 'BATH',
        display_name: '방문목욕',
        service_types: [
          { service_type_code: 'B1', display_name: '차량목욕서비스' },
          { service_type_code: 'B2', display_name: '가정내목욕서비스' },
        ],
      },
      {
        service_group_code: 'NURSE',
        display_name: '방문간호',
        service_types: [{ service_type_code: 'N1', display_name: '기본간호서비스' }],
      },
    ];
    const expectedServices =
      '방문요양: 일반방문요양서비스, 야간방문요양서비스, 휴일방문요양서비스 · 방문목욕: 차량목욕서비스, 가정내목욕서비스 · 방문간호: 기본간호서비스';

    installRecipientListFetch(() =>
      listResponse([
        listItem({
          id: 42,
          name: '긴서비스행',
          benefit_code: 'REDUCED_SPECIAL',
          copayment_rate: 7.5,
          services: longServices,
        }),
      ]),
    );

    render(<RecipientsPage />);

    const row = await screen.findByRole('button', { name: /긴서비스행/ });
    const servicesCell = within(row).getByTestId('recipient-list-services');
    const copayCell = within(row).getByTestId('recipient-list-copay');

    expect(servicesCell).toHaveTextContent(expectedServices);
    expect(servicesCell.textContent).toBe(expectedServices);
    expect(within(row).getByTestId('recipient-list-benefit')).toHaveTextContent('REDUCED_SPECIAL');
    expect(within(row).getByTestId('recipient-list-copay-rate')).toHaveTextContent('7.5%');
    expect(copayCell).toHaveTextContent('REDUCED_SPECIAL');
    expect(copayCell).toHaveTextContent('7.5%');
    expect(servicesCell.className).toContain('recipient-list-services');
    expect(copayCell.className).toContain('recipient-list-copay');
  });

  test('recipient-list-row CSS does not clip multi-line service/copay with fixed height (M1)', () => {
    const css = readFileSync(recipientsCssPath, 'utf8');
    // Prefer the sizing rule (min-height) over the shared grid template rule.
    const rowRules = [...css.matchAll(/button\.recipient-list-row\s*\{[^}]+\}/g)].map((match) => match[0]);
    const sizingRule = rowRules.find((rule) => /min-height\s*:/.test(rule));
    expect(sizingRule, 'button.recipient-list-row sizing rule missing').toBeTruthy();

    expect(sizingRule!).toMatch(/(?:^|[^\w-])height:\s*auto/);
    expect(sizingRule!).toMatch(/min-height:\s*45px/);
    expect(sizingRule!).toMatch(/overflow:\s*visible/);
    // Reject fixed row height (do not match min-height:45px).
    expect(sizingRule!).not.toMatch(/(?:^|[^\w-])height:\s*45px\b/);
    expect(sizingRule!).not.toMatch(/overflow:\s*hidden/);

    const servicesRuleMatch = css.match(/\.recipient-list-services\s*\{[^}]+\}/);
    expect(servicesRuleMatch, '.recipient-list-services rule missing').toBeTruthy();
    expect(servicesRuleMatch![0]).toMatch(/white-space:\s*normal/);
    expect(servicesRuleMatch![0]).toMatch(/overflow:\s*visible/);

    const copayRuleMatch = css.match(/\.recipient-list-copay\s*\{[^}]+\}/);
    expect(copayRuleMatch, '.recipient-list-copay rule missing').toBeTruthy();
    expect(copayRuleMatch![0]).toMatch(/white-space:\s*normal/);
    expect(copayRuleMatch![0]).toMatch(/overflow:\s*visible/);
  });

  test('detail and create summary never show a fabricated certification number (M2)', async () => {
    installRecipientListFetch(() =>
      listResponse([listItem({ id: 11, name: '인정번호검증', recipient_no: 'R-FAKE-001' })]),
    );

    render(<RecipientsPage />);

    fireEvent.click(await screen.findByRole('button', { name: /인정번호검증/ }));
    const detailCert = await screen.findByTestId('recipient-detail-certification-number');
    expect(detailCert).toHaveTextContent('미지정');
    expect(screen.queryByText('L1234567890')).toBeNull();
    // Do not reuse recipient_no or other IDs as 인정번호.
    expect(detailCert).not.toHaveTextContent('R-FAKE-001');
    expect(detailCert).not.toHaveTextContent('11');

    fireEvent.click(screen.getByTestId('recipient-create-toggle'));
    const createCert = await screen.findByTestId('recipient-create-certification-number');
    expect(createCert).toHaveTextContent('미지정');
    expect(screen.queryByText('L1234567890')).toBeNull();
  });

  test('status/error CSS does not reintroduce ancestor display:none hiding (MAJ-1/MAJ-2)', () => {
    const css = readFileSync(recipientsCssPath, 'utf8');

    // Collect rule blocks: selector { declarations }. Handles multi-selector rules.
    const ruleBlocks = [
      ...css.matchAll(/([^{}@][^{]*)\{([^}]*)\}/g),
    ].map((match) => ({
      selector: match[1].replace(/\s+/g, ' ').trim(),
      body: match[2],
    }));

    const hidesWithDisplayNone = (body: string) => /display\s*:\s*none/i.test(body);

    // Regression that caused false-green: only searching `.recipients-page ….<class>`
    // missed bare `.recipient-page-heading { display:none }` which hid the status chip.
    for (const rule of ruleBlocks) {
      if (!hidesWithDisplayNone(rule.body)) continue;

      // Entire heading must not be display:none (status chip is a descendant).
      const headingSubjects = rule.selector
        .split(',')
        .map((part) => part.trim())
        .filter((part) => /(^|[\s>+~])\.recipient-page-heading(\s|$|:|,|$)/.test(part) || part === '.recipient-page-heading');
      for (const subject of headingSubjects) {
        // Allow hiding only non-status children, e.g. `.recipient-page-heading > :not(.recipient-page-status)`.
        if (/\.recipient-page-heading\s*>/.test(subject) || /\.recipient-page-heading\s+/.test(subject)) {
          continue;
        }
        if (/(^|[\s>+~])\.recipient-page-heading$/.test(subject) || subject === '.recipient-page-heading') {
          expect.fail(
            `MAJ-1 regression: .recipient-page-heading must not use display:none (hides status chip). Rule: ${rule.selector} { ${rule.body.trim()} }`,
          );
        }
      }

      // Status / error surfaces themselves must not be hidden.
      // Ignore :not(.class) mentions — those are exclusions, not subjects being hidden.
      const selectorWithoutNots = rule.selector.replace(/:not\([^)]*\)/g, '');
      const protectedClasses = [
        'recipient-page-status',
        'recipient-status',
        'recipient-status-loading',
        'recipient-status-error',
        'recipient-inline-error',
        'recipient-save-error',
        'recipient-state-error',
      ];
      for (const className of protectedClasses) {
        const classRe = new RegExp(`\\.${className}\\b`);
        if (!classRe.test(selectorWithoutNots)) continue;
        // Ignore :empty empty-state hide — still ban bare display:none on the surface.
        if (new RegExp(`\\.${className}\\s*:empty\\b`).test(rule.selector)) continue;
        expect.fail(
          `MAJ-1 regression: .${className} must not use display:none. Rule: ${rule.selector} { ${rule.body.trim()} }`,
        );
      }
    }

    // Base error text color must remain visible styling (not a hide rule).
    const inlineErrorColor = css.match(/\.recipient-inline-error[^{]*\{[^}]*\}/);
    expect(inlineErrorColor, '.recipient-inline-error color rule missing').toBeTruthy();
    expect(inlineErrorColor![0]).not.toMatch(/display\s*:\s*none/);
  });

  test('list error text renders with role=alert (DOM only; jsdom does not compute CSS layout) (MAJ-2)', async () => {
    // Honest limitation: jsdom does not apply CSS layout/visibility. This asserts
    // error copy is present in the accessibility tree / DOM when list load fails.
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ detail: { code: 'server_error', message: '목록 실패' } }, 500);
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveClass('recipient-inline-error');
    expect(alert.textContent).toBeTruthy();

    // Status chip for list error must also be in the DOM (CSS visibility not asserted here).
    const status = await screen.findByTestId('recipient-list-status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(within(status).getByText('목록 확인 필요')).toBeTruthy();
  });

  test('detail summary grade/copay follow matching list projection for active detail id', async () => {
    installRecipientListFetch(() =>
      listResponse([
        listItem({
          id: 15,
          name: '등급본인부담',
          grade_code: '3',
          benefit_code: 'BASIC_LIVELIHOOD',
          copayment_rate: 15,
        }),
      ]),
    );

    render(<RecipientsPage />);

    fireEvent.click(await screen.findByRole('button', { name: /등급본인부담/ }));

    // Grade still comes from list projection; copay control is benefit-code select (일반/기초/6%/9%).
    const grade = await screen.findByTestId('recipient-detail-grade');
    const copay = screen.getByTestId('recipient-detail-copay');
    expect(grade).toHaveTextContent('3등급');
    expect(copay).toHaveValue('BASIC_LIVELIHOOD');
    // List row: 15% general rate maps to 일반 label.
    const row = screen.getByRole('button', { name: /등급본인부담/ });
    expect(within(row).getByTestId('recipient-list-grade')).toHaveTextContent('3등급');
    expect(within(row).getByTestId('recipient-list-copay-rate')).toHaveTextContent('일반');
  });

  test('detail grade/copay use 미지정/GENERAL when active detail id is not in the current list page', async () => {
    installRecipientListFetch(() =>
      listResponse([listItem({ id: 1, name: '현재페이지수급', grade_code: '2', copayment_rate: 20 })]),
    );

    // selected/detail point at an id not in the current list page → no matching list projection.
    window.history.replaceState({}, '', '/recipients?selected=999&detail=999');
    render(<RecipientsPage />);

    const grade = await screen.findByTestId('recipient-detail-grade');
    const copay = screen.getByTestId('recipient-detail-copay');
    expect(grade).toHaveTextContent('미지정');
    // Without list projection / active period, benefit select defaults to GENERAL (not list row values).
    expect(copay).toHaveValue('GENERAL');
    // Must not invent values from the unrelated list row.
    expect(grade).not.toHaveTextContent('2등급');
    expect(copay).not.toHaveValue('REDUCTION_6');
  });

  test('detail grade/copay do not mis-attribute first list row when deep-link targets another id (MAJ-3)', async () => {
    // A is first list row (selectedRecipient fallback when selected is absent).
    // B is detail deep-link target with different grade/copay.
    installRecipientListFetch(() =>
      listResponse([
        listItem({
          id: 1,
          name: 'A수급',
          grade_code: '1',
          benefit_code: 'GENERAL',
          copayment_rate: 20,
        }),
        listItem({
          id: 2,
          name: 'B수급',
          grade_code: '5',
          benefit_code: 'REDUCTION_6',
          copayment_rate: 7.5,
        }),
      ]),
    );

    // selected absent → selectedRecipient falls back to A; detail=B is the active target.
    window.history.replaceState({}, '', '/recipients?detail=2');
    render(<RecipientsPage />);

    const grade = await screen.findByTestId('recipient-detail-grade');
    const copay = screen.getByTestId('recipient-detail-copay');
    // Must show B's list projection, never A's (old selectedRecipient bug).
    expect(grade).toHaveTextContent('5등급');
    expect(copay).toHaveValue('REDUCTION_6');
    expect(grade).not.toHaveTextContent('1등급');
    expect(copay).not.toHaveValue('GENERAL');
  });

  test('create form grade is read-only 미지정; copay is benefit-code select defaulting to 일반 (MAJ-4)', async () => {
    installRecipientListFetch(() => listResponse([listItem({ id: 1, name: '김수급' })]));
    render(<RecipientsPage />);

    fireEvent.click(await screen.findByTestId('recipient-create-toggle'));

    // Grade remains non-savable read-only (not on RecipientCreateRequest as free text).
    expect(screen.queryByTestId('recipient-grade-select')).toBeNull();
    expect(await screen.findByTestId('recipient-create-grade')).toHaveTextContent('미지정');
    // Copay is intentionally savable as 일반/기초/6%/9% with default 일반.
    const createCopay = screen.getByTestId('recipient-create-copay');
    expect(createCopay.tagName).toBe('SELECT');
    expect(createCopay).toHaveValue('GENERAL');
    expect(within(createCopay).getAllByRole('option').map((n) => n.textContent)).toEqual([
      '일반',
      '기초',
      '6%',
      '9%',
    ]);
  });

  test('idle CSS does not hide create actions or all heading buttons (MAJ-A static CSS)', () => {
    // Static CSS contract only — jsdom does not compute layout/visibility.
    const css = readFileSync(recipientsCssPath, 'utf8');
    const ruleBlocks = [...css.matchAll(/([^{}@][^{]*)\{([^}]*)\}/g)].map((match) => ({
      selector: match[1].replace(/\s+/g, ' ').trim(),
      body: match[2],
    }));

    const hidesWithDisplayNone = (body: string) => /display\s*:\s*none/i.test(body);

    for (const rule of ruleBlocks) {
      if (!hidesWithDisplayNone(rule.body)) continue;

      for (const part of rule.selector.split(',').map((s) => s.trim())) {
        if (!/\.recipient-detail-panel\.is-idle\b/.test(part)) continue;

        // Ban hiding the whole create action group (blocks 수급자 등록 with empty list).
        // Subject is the group itself, not a descendant of it.
        const withoutNots = part.replace(/:not\([^)]*\)/g, '');
        if (/\.recipient-create-actions\s*$/.test(withoutNots) || /\.recipient-create-actions:[^\s]*\s*$/.test(withoutNots)) {
          expect.fail(
            `MAJ-A regression: idle must not hide .recipient-create-actions entirely. Rule: ${rule.selector} { ${rule.body.trim()} }`,
          );
        }

        // Ban blanket heading button hide; allow only specific toggles (e.g. detail-toggle).
        if (
          /\.recipient-detail-heading\b/.test(part) &&
          /(^|[\s>+~])button(\s|$|:)/.test(withoutNots) &&
          !/\.recipient-detail-toggle\b/.test(part)
        ) {
          expect.fail(
            `MAJ-A regression: idle must not hide all heading buttons. Rule: ${rule.selector} { ${rule.body.trim()} }`,
          );
        }
      }
    }

    // Positive contract: create-open idle path carves out the form host section.
    const idleCreatingRule = ruleBlocks.find((rule) =>
      /\.recipient-detail-panel\.is-idle\.is-creating\b/.test(rule.selector),
    );
    expect(
      idleCreatingRule,
      'MAJ-A: expected .recipient-detail-panel.is-idle.is-creating exception rule for create form visibility',
    ).toBeTruthy();
    expect(idleCreatingRule!.selector).toMatch(/recipient-basic-section/);
  });

  test('empty list: create toggle opens form; empty mobile uses popup alert not inline role=alert (MAJ-A DOM)', async () => {
    // DOM contract only — does not assert computed CSS visibility/layout in jsdom.
    installRecipientListFetch(() => listResponse([], 0));
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});

    render(<RecipientsPage />);

    // Wait for empty list settle; create toggle must be present without a selected row.
    const createToggle = await screen.findByTestId('recipient-create-toggle');
    expect(createToggle).toHaveTextContent('수급자 등록');

    const workspace = screen.getByTestId('recipient-detail-workspace');
    expect(workspace.className).toMatch(/\bis-idle\b/);
    expect(workspace.className).not.toMatch(/\bis-creating\b/);

    fireEvent.click(createToggle);

    // createOpen → form mounts; panel marked is-creating so CSS idle hide does not cover it.
    expect(await screen.findByTestId('recipient-name-input')).toBeTruthy();
    const createForm = document.getElementById('recipient-create-form');
    expect(createForm).toBeTruthy();
    expect(workspace.className).toMatch(/\bis-creating\b/);
    expect(workspace.className).toMatch(/\bis-idle\b/);

    // Empty mobile on save uses a small popup alert (not a persistent inline role=alert).
    fireEvent.submit(createForm!);
    await waitFor(() => expect(alertSpy).toHaveBeenCalled());
    expect(String(alertSpy.mock.calls[0]?.[0] ?? '')).toMatch(/휴대전화/);
    expect(screen.queryByRole('alert')).toBeNull();
    alertSpy.mockRestore();
  });

  test('list age uses 세는나이 (year-diff+1), detail uses 만 나이 with birthday boundary', async () => {
    // Fixed clock at a UTC/KST boundary: 2025-06-15 15:30 UTC is already 2025-06-16 in Asia/Seoul.
    const fixedNow = new Date('2025-06-15T15:30:00.000Z');
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(fixedNow);
    const OriginalDateTimeFormat = Intl.DateTimeFormat;
    const dateTimeFormatSpy = vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(
      function MockDateTimeFormat(
        this: Intl.DateTimeFormat,
        ...args: ConstructorParameters<typeof Intl.DateTimeFormat>
      ) {
        return Reflect.construct(OriginalDateTimeFormat, args);
      } as typeof Intl.DateTimeFormat,
    );
    try {
      // Seoul calendar day 2025-06-16.
      const onSeoulBirthday = '1995-06-16';
      const notYetSeoulBirthday = '1995-06-17';
      // 세는나이 is year-diff+1 regardless of birthday → both 31세 on list.
      const countingAge = '31세';

      installRecipientListFetch(() =>
        listResponse([
          listItem({ id: 1, name: '생일당일', birth_date: onSeoulBirthday }),
          listItem({ id: 2, name: '생일전', birth_date: notYetSeoulBirthday }),
        ]),
      );

      render(<RecipientsPage />);

      const onBirthdayRow = await screen.findByRole('button', { name: /생일당일/ });
      const beforeBirthdayRow = await screen.findByRole('button', { name: /생일전/ });

      expect(within(onBirthdayRow).getByTestId('recipient-list-age')).toHaveTextContent(countingAge);
      expect(within(beforeBirthdayRow).getByTestId('recipient-list-age')).toHaveTextContent(countingAge);
      // List must not use 만 나이 (30/29) — that belongs on the detail panel.
      expect(within(onBirthdayRow).getByTestId('recipient-list-age')).not.toHaveTextContent('30세');
      expect(within(beforeBirthdayRow).getByTestId('recipient-list-age')).not.toHaveTextContent('29세');
      // Production must pass timeZone Asia/Seoul to the formatter for counting age year.
      expect(dateTimeFormatSpy).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ timeZone: 'Asia/Seoul' }),
      );
    } finally {
      dateTimeFormatSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  test('query change clears old rows/total while loading; failure clears list projection', async () => {
    type Pending = {
      query: ListQuery;
      resolve: (response: Response) => void;
    };
    const pending: Pending[] = [];
    const requests: ListQuery[] = [];

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        const query = parseListQuery(url);
        requests.push(query);
        return new Promise<Response>((resolve) => {
          pending.push({ query, resolve });
        });
      }

      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        const id = Number(url.pathname.split('/').pop());
        const item = listItem({ id: Number.isFinite(id) ? id : 1 });
        return jsonResponse({
          id: item.id,
          name: item.name,
          birth_date: item.birth_date,
          sex_code: item.sex_code,
          recipient_status: 'ACTIVE' as const,
          recipient_no: item.recipient_no,
          postal_code: item.postal_code,
          address: item.address,
          home_phone: item.home_phone,
          mobile_phone: item.mobile_phone,
          memo: item.memo,
          payer_guardian_id: null,
          row_version: item.row_version,
        });
      }

      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);

    await waitFor(() => expect(pending.length).toBe(1));
    pending[0].resolve(
      jsonResponse(listResponse([listItem({ id: 1, name: '이전목록행' })], 7, 1, 100)),
    );

    expect(await screen.findByRole('button', { name: /이전목록행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 7명');

    fireEvent.change(screen.getByTestId('recipient-search-input'), {
      target: { value: '신규검색' },
    });

    await waitFor(() => expect(requests.some((request) => request.search === '신규검색')).toBe(true));
    // Stale projection must not remain under the new query while loading.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /이전목록행/ })).toBeNull();
      expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 0명');
      expect(screen.getByTestId('recipient-list-loading')).toBeInTheDocument();
    });

    const searchPending = pending.filter((entry) => entry.query.search === '신규검색');
    expect(searchPending.length).toBeGreaterThan(0);
    searchPending[searchPending.length - 1].resolve(
      jsonResponse(listResponse([listItem({ id: 2, name: '검색결과행' })], 4, 1, 100)),
    );
    expect(await screen.findByRole('button', { name: /검색결과행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 4명');

    // Status change must also drop prior rows/total while the deferred response is pending.
    fireEvent.change(screen.getByTestId('recipient-filter-select'), {
      target: { value: 'ENDED' },
    });
    await waitFor(() => expect(requests.some((request) => request.status === 'ENDED')).toBe(true));
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /검색결과행/ })).toBeNull();
      expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 0명');
      expect(screen.getByTestId('recipient-list-loading')).toBeInTheDocument();
    });
    const statusPending = pending.filter((entry) => entry.query.status === 'ENDED');
    expect(statusPending.length).toBeGreaterThan(0);
    statusPending[statusPending.length - 1].resolve(
      jsonResponse(listResponse([listItem({ id: 3, name: '상태결과행' })], 5, 1, 2)),
    );
    expect(await screen.findByRole('button', { name: /상태결과행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 5명');

    // Append (page 2) failure keeps already-loaded rows; surface error without clearing projection.
    scrollListNearBottom();
    await waitFor(() => expect(requests.some((request) => request.page === '2')).toBe(true));
    // Existing rows remain visible while the append request is in flight.
    expect(screen.getByRole('button', { name: /상태결과행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 5명');

    const pagePending = pending.filter((entry) => entry.query.page === '2');
    expect(pagePending.length).toBeGreaterThan(0);
    pagePending[pagePending.length - 1].resolve(
      jsonResponse({ detail: { code: 'server_error', message: '목록 실패' } }, 500),
    );

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveClass('recipient-inline-error');
    // Page-1 projection is preserved after append failure (not replaced by empty).
    expect(screen.getByRole('button', { name: /상태결과행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 5명');
    expect(screen.queryByRole('button', { name: /이전목록행/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /검색결과행/ })).toBeNull();
  });

  test('same-query listReload failure clears rows/total after successful projection', async () => {
    type Pending = {
      query: ListQuery;
      resolve: (response: Response) => void;
    };
    const pending: Pending[] = [];
    const requests: ListQuery[] = [];

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        const query = parseListQuery(url);
        requests.push(query);
        return new Promise<Response>((resolve) => {
          pending.push({ query, resolve });
        });
      }

      // Detail save bumps listReload (same search/status/page) after a successful basic-batch.
      if (isBasicUpdateBatch(url, method)) {
        const idMatch = url.pathname.match(/\/recipients\/(\d+)\/basic-batch$/);
        const id = Number(idMatch?.[1] ?? 1);
        const item = listItem({ id: Number.isFinite(id) ? id : 1, name: '성공목록행수정' });
        return jsonResponse({
          recipient: {
            id: item.id,
            name: item.name,
            birth_date: item.birth_date,
            sex_code: item.sex_code,
            recipient_status: 'ACTIVE' as const,
            recipient_no: item.recipient_no,
            postal_code: item.postal_code,
            address: item.address,
            home_phone: item.home_phone,
            mobile_phone: item.mobile_phone,
            memo: item.memo,
            payer_guardian_id: null,
            row_version: item.row_version + 1,
          },
          guardians: [],
          saved_sections: ['recipient'],
        });
      }

      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        if (url.pathname.endsWith('/guardians')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/primary-guardian-periods')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/payer-snapshots')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
        if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
        const id = Number(url.pathname.split('/').pop());
        const item = listItem({ id: Number.isFinite(id) ? id : 1, name: '성공목록행' });
        return jsonResponse({
          id: item.id,
          name: item.name,
          birth_date: item.birth_date,
          sex_code: item.sex_code,
          recipient_status: 'ACTIVE' as const,
          recipient_no: item.recipient_no,
          postal_code: item.postal_code,
          address: item.address,
          home_phone: item.home_phone,
          mobile_phone: item.mobile_phone,
          memo: item.memo,
          payer_guardian_id: null,
          row_version: item.row_version,
        });
      }

      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);

    await waitFor(() => expect(pending.length).toBe(1));
    pending[0].resolve(
      jsonResponse(listResponse([listItem({ id: 1, name: '성공목록행' })], 3, 1, 100)),
    );

    expect(await screen.findByRole('button', { name: /성공목록행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 3명');

    // Editable form appears only after successful detail GET (not list-only identity).
    await waitFor(() => {
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('성공목록행');
    });

    // No-op save is disabled; change a field so save can trigger listReload (same query key).
    enterBasicEdit();
    const saveButton = screen.getByTestId('recipient-basic-save');
    expect(saveButton).toBeDisabled();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '성공목록행수정' },
    });
    expect(saveButton).not.toBeDisabled();
    fireEvent.click(saveButton);

    await waitFor(() => expect(pending.length).toBeGreaterThan(1));
    const reloadPending = pending[pending.length - 1];
    // Same query as the successful projection (no search/status/page change).
    expect(reloadPending.query).toEqual(requests[0]);
    // Same-query reload keeps prior rows until the response settles; catch must clear them.
    expect(screen.getByRole('button', { name: /성공목록행/ })).toBeInTheDocument();
    expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 3명');

    reloadPending.resolve(
      jsonResponse({ detail: { code: 'server_error', message: '목록 실패' } }, 500),
    );

    // Deleting catch-side setListData(null) would leave rows/total from the prior success.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /성공목록행/ })).toBeNull();
      expect(screen.getByTestId('recipient-count')).toHaveTextContent('총 0명');
    });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveClass('recipient-inline-error');
    expect(screen.queryByTestId('recipient-list-loading')).toBeNull();
  });

  test('after query change, selected/detail absent from new page is cleared (first-row policy; no prior detail)', async () => {
    const { requests } = installRecipientListFetch((query) => {
      if (query.search === '다른필터') {
        return listResponse(
          [
            listItem({
              id: 50,
              name: '새페이지수급',
              grade_code: '1',
              benefit_code: 'GENERAL',
              copayment_rate: 20,
            }),
          ],
          1,
        );
      }
      return listResponse(
        [
          listItem({
            id: 10,
            name: '이전선택수급',
            grade_code: '3',
            benefit_code: 'BASIC_LIVELIHOOD',
            copayment_rate: 15,
          }),
          listItem({
            id: 11,
            name: '이전다른수급',
            grade_code: '4',
            benefit_code: 'REDUCTION_6',
            copayment_rate: 7.5,
          }),
        ],
        2,
      );
    });

    window.history.replaceState({}, '', '/recipients?selected=10&detail=10');
    render(<RecipientsPage />);

    fireEvent.click(await screen.findByRole('button', { name: /이전선택수급/ }));
    expect(await screen.findByTestId('recipient-detail-grade')).toHaveTextContent('3등급');
    expect(screen.getByTestId('recipient-detail-copay')).toHaveValue('BASIC_LIVELIHOOD');

    fireEvent.change(screen.getByTestId('recipient-search-input'), {
      target: { value: '다른필터' },
    });

    await waitFor(() => expect(requests.at(-1)?.search).toBe('다른필터'));
    expect(await screen.findByRole('button', { name: /새페이지수급/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /이전선택수급/ })).toBeNull();

    // Prior page detail must not remain; first-row policy selects the only new row.
    await waitFor(() => {
      expect(window.location.search).toMatch(/selected=50/);
      expect(window.location.search).not.toMatch(/detail=10/);
      expect(window.location.search).not.toMatch(/selected=10/);
    });
    // Search is preserved; status/page defaults remain.
    expect(window.location.search).toMatch(/search=/);

    await waitFor(() => {
      expect(screen.getByTestId('recipient-detail-grade')).toHaveTextContent('1등급');
      expect(screen.getByTestId('recipient-detail-copay')).toHaveValue('GENERAL');
    });
    expect(screen.getByTestId('recipient-detail-grade')).not.toHaveTextContent('3등급');
    expect(screen.getByTestId('recipient-detail-copay')).not.toHaveValue('BASIC_LIVELIHOOD');
    expect(screen.getByTestId('recipient-selected-name')).toHaveTextContent('새페이지수급');
  });
});

describe('recipient payer guardian UI contract', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/recipients');
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  test('basic screen shows recipient and two guardians; no per-guardian save; no primary/payer snapshot UI', async () => {
    const requested: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      requested.push(`${method} ${url.pathname}`);
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 501, name: '납부자UI' })]));
      }
      if (url.pathname.endsWith('/guardians')) {
        return jsonResponse({
          items: [
            {
              id: 11,
              recipient_id: 501,
              name: '보호자갑',
              phone: '010-1',
              address: null,
              relationship_text: '자녀',
              row_version: 1,
            },
            {
              id: 22,
              recipient_id: 501,
              name: '보호자을',
              phone: '010-2',
              address: null,
              relationship_text: '배우자',
              row_version: 1,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.startsWith('/api/v1/recipients/') && method === 'GET') {
        return jsonResponse({
          id: 501,
          name: '납부자UI',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: 'R-501',
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /납부자UI/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-guardian-1-section')).toBeInTheDocument());
    expect(screen.getByTestId('recipient-guardian-2-section')).toBeInTheDocument();
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('보호자갑');
    expect(screen.getByTestId('guardian-2-name-input')).toHaveValue('보호자을');
    expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent('수급자 본인');
    expect(screen.queryByTestId('guardian-1-save-button')).toBeNull();
    expect(screen.queryByTestId('guardian-2-save-button')).toBeNull();
    expect(screen.queryByTestId('recipient-primary-guardian-form')).toBeNull();
    expect(screen.queryByTestId('recipient-payer-snapshot-section')).toBeNull();
    expect(screen.getByTestId('recipient-detail-toggle')).toHaveTextContent('상세');
    expect(requested.some((r) => r.includes('/payer-snapshots'))).toBe(false);
    expect(requested.some((r) => r.includes('/primary-guardian-periods'))).toBe(false);
  });

  test('single edit mode mutual-exclusive payer checkboxes and cancel restore', async () => {
    let payerId: number | null = null;
    const patchBodies: Array<Record<string, unknown>> = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 502, name: '체크박스' })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        return jsonResponse({
          items: [
            {
              id: 11,
              recipient_id: 502,
              name: '가드1',
              phone: null,
              address: null,
              relationship_text: null,
              row_version: 1,
            },
            {
              id: 22,
              recipient_id: 502,
              name: '가드2',
              phone: null,
              address: null,
              relationship_text: null,
              row_version: 1,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/502' && method === 'GET') {
        return jsonResponse({
          id: 502,
          name: '체크박스',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: payerId,
          row_version: 1,
        });
      }
      if (url.pathname === '/api/v1/recipients/502' && method === 'PATCH') {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
        patchBodies.push(body);
        if ('payer_guardian_id' in body) {
          payerId = body.payer_guardian_id as number | null;
        }
        return jsonResponse({
          id: 502,
          name: typeof body.name === 'string' ? body.name : '체크박스',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: payerId,
          row_version: 2,
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /체크박스/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).toBeInTheDocument());
    enterBasicEdit();
    expect(screen.getByTestId('recipient-basic-save')).toBeInTheDocument();
    expect(screen.getByTestId('recipient-basic-cancel')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('guardian-1-payer-checkbox'));
    expect(screen.getByTestId('guardian-1-payer-checkbox')).toBeChecked();
    expect(screen.getByTestId('guardian-2-payer-checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByTestId('guardian-2-payer-checkbox'));
    expect(screen.getByTestId('guardian-2-payer-checkbox')).toBeChecked();
    expect(screen.getByTestId('guardian-1-payer-checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByTestId('guardian-2-payer-checkbox'));
    expect(screen.getByTestId('guardian-1-payer-checkbox')).not.toBeChecked();
    expect(screen.getByTestId('guardian-2-payer-checkbox')).not.toBeChecked();
    expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent('수급자 본인');

    fireEvent.click(screen.getByTestId('guardian-1-payer-checkbox'));
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '임시이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-cancel'));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('체크박스'),
    );
    expect(screen.getByTestId('guardian-1-payer-checkbox')).not.toBeChecked();
    expect(screen.queryByTestId('recipient-basic-save')).toBeNull();
  });

  test('new guardian id is used for payer slot in basic-batch; save locks inputs', async () => {
    const batchBodies: Array<Record<string, unknown>> = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 503, name: '신규납부' })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/503' && method === 'GET') {
        return jsonResponse({
          id: 503,
          name: '신규납부',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const guardians = [
          {
            id: 77,
            recipient_id: 503,
            name: '신규보호자',
            phone: null,
            address: null,
            relationship_text: null,
            row_version: 1,
          },
        ];
        return jsonResponse({
          recipient: {
            id: 503,
            name: '신규납부',
            birth_date: '1950-03-15',
            sex_code: 'FEMALE',
            recipient_status: 'ACTIVE',
            recipient_no: null,
            postal_code: null,
            address: null,
            home_phone: null,
            mobile_phone: '010-1111-2222',
            memo: null,
            payer_guardian_id: 77,
            row_version: 2,
          },
          guardians,
          saved_sections: ['recipient', 'guardians'],
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /신규납부/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).toBeInTheDocument());
    enterBasicEdit();
    fireEvent.change(screen.getByTestId('guardian-1-name-input'), { target: { value: '신규보호자' } });
    fireEvent.click(screen.getByTestId('guardian-1-payer-checkbox'));
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(1));
    expect(batchBodies[0].payer_guardian_slot).toBe(0);
    expect(batchBodies[0].guardians).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          slot: 0,
          payload: expect.objectContaining({ name: '신규보호자' }),
        }),
      ]),
    );
    await waitFor(() =>
      expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent('납부자 · 보호자1'),
    );
  });

  test('detail toggle keeps existing extras component contract', async () => {
    installRecipientListFetch(() => listResponse([listItem({ id: 504, name: '상세토글' })]));
    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /상세토글/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-detail-toggle')).toHaveTextContent('상세'));
    fireEvent.click(screen.getByTestId('recipient-detail-toggle'));
    expect(screen.getByTestId('recipient-detail-toggle')).toHaveTextContent('기본정보');
    expect(screen.getByTestId('recipient-detail-extra-sections')).toBeInTheDocument();
  });

  test('unlisted payer preserved on name-only save; self button clears payer', async () => {
    let recipientName = '목록외납부자';
    let payerId: number | null = 33;
    let rowVersion = 1;
    const batchBodies: Array<Record<string, unknown>> = [];
    const listedGuardians = [
      {
        id: 11,
        recipient_id: 505,
        name: '가드1',
        phone: null,
        address: null,
        relationship_text: null,
        row_version: 1,
      },
      {
        id: 22,
        recipient_id: 505,
        name: '가드2',
        phone: null,
        address: null,
        relationship_text: null,
        row_version: 1,
      },
    ];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 505, name: recipientName })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        return jsonResponse({ items: listedGuardians });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/505' && method === 'GET') {
        return jsonResponse({
          id: 505,
          name: recipientName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: payerId,
          row_version: rowVersion,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        if (typeof recipientBody.name === 'string') recipientName = recipientBody.name;
        if (body.preserve_payer === true) {
          // keep payerId
        } else if (body.payer_guardian_slot === null || body.payer_guardian_slot === undefined) {
          payerId = null;
        }
        if (typeof recipientBody.expected_row_version === 'number') {
          rowVersion = recipientBody.expected_row_version + 1;
        }
        return jsonResponse({
          recipient: {
            id: 505,
            name: recipientName,
            birth_date: '1950-03-15',
            sex_code: 'FEMALE',
            recipient_status: 'ACTIVE',
            recipient_no: null,
            postal_code: null,
            address: null,
            home_phone: null,
            mobile_phone: '010-1111-2222',
            memo: null,
            payer_guardian_id: payerId,
            row_version: rowVersion,
          },
          guardians: listedGuardians,
          saved_sections: ['recipient'],
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /목록외납부자/ }));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent(
        '납부자 · 목록 외 보호자',
      ),
    );
    expect(screen.getByTestId('guardian-1-payer-checkbox')).not.toBeChecked();
    expect(screen.getByTestId('guardian-2-payer-checkbox')).not.toBeChecked();

    enterBasicEdit();
    expect(screen.getByTestId('recipient-payer-self-button')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('recipient-payer-self-button'));
    fireEvent.click(screen.getByTestId('recipient-basic-cancel'));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent(
        '납부자 · 목록 외 보호자',
      ),
    );
    expect(screen.queryByTestId('recipient-payer-self-button')).toBeNull();
    expect(screen.getByTestId('guardian-1-payer-checkbox')).not.toBeChecked();
    expect(screen.getByTestId('guardian-2-payer-checkbox')).not.toBeChecked();

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '목록외납부자수정' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(1));
    expect(batchBodies[0].recipient).toMatchObject({
      expected_row_version: 1,
      name: '목록외납부자수정',
    });
    expect(batchBodies[0].preserve_payer).toBe(true);
    expect(batchBodies[0].payer_guardian_slot).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent(
        '납부자 · 목록 외 보호자',
      ),
    );

    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).not.toBeDisabled());
    enterBasicEdit();
    expect(screen.getByTestId('recipient-payer-self-button')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('recipient-payer-self-button'));
    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    expect(batchBodies[1].preserve_payer).toBe(false);
    expect(batchBodies[1].payer_guardian_slot).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent('수급자 본인'),
    );
  });

  test('atomic basic-batch failure keeps guardian draft; retry resends full guardian payload', async () => {
    // Atomic save: no partial guardian create. First batch fails entirely; retry sends same create again.
    const batchBodies: Array<Record<string, unknown>> = [];
    let failOnce = true;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 510, name: '재시도신규' })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/510' && method === 'GET') {
        return jsonResponse({
          id: 510,
          name: '재시도신규',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        if (failOnce) {
          failOnce = false;
          return jsonResponse(
            { error: { code: 'INTERNAL_ERROR', message: '서버 오류' }, field_errors: [] },
            500,
          );
        }
        return jsonResponse({
          recipient: {
            id: 510,
            name: '재시도신규',
            birth_date: '1950-03-15',
            sex_code: 'FEMALE',
            recipient_status: 'ACTIVE',
            recipient_no: null,
            postal_code: null,
            address: null,
            home_phone: null,
            mobile_phone: '010-1111-2222',
            memo: null,
            payer_guardian_id: 88,
            row_version: 2,
          },
          guardians: [
            {
              id: 88,
              recipient_id: 510,
              name: '신규보호자',
              phone: null,
              address: null,
              relationship_text: null,
              row_version: 1,
            },
          ],
          saved_sections: ['recipient', 'guardians'],
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /재시도신규/ }));
    await waitFor(() => expect(screen.getByTestId('recipient-basic-edit')).toBeInTheDocument());
    enterBasicEdit();
    fireEvent.change(screen.getByTestId('guardian-1-name-input'), { target: { value: '신규보호자' } });
    fireEvent.click(screen.getByTestId('guardian-1-payer-checkbox'));
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchBodies.length).toBe(1));
    // Draft remains dirty after atomic failure.
    await waitFor(() => expect(screen.getByTestId('recipient-basic-save')).not.toBeDisabled());
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('신규보호자');

    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    // Retry resends create (no guardian_id) because first batch rolled back.
    expect(batchBodies[0].guardians).toEqual(batchBodies[1].guardians);
    expect(batchBodies[1].payer_guardian_slot).toBe(0);
    expect(
      (batchBodies[1].guardians as Array<Record<string, unknown>>)[0],
    ).not.toHaveProperty('guardian_id');
    await waitFor(() =>
      expect(screen.getByText('수급자·보호자·본인부담금을 저장했습니다.')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('recipient-payer-current-label')).toHaveTextContent('납부자 · 보호자1');
  });

  test('atomic basic-batch failure keeps recipient+guardian draft; retry resends both', async () => {
    const batchBodies: Array<Record<string, unknown>> = [];
    let failOnce = true;
    let guardianName = '기존가드';
    let guardianRowVersion = 1;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 511, name: '재시도기존' })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        return jsonResponse({
          items: [
            {
              id: 41,
              recipient_id: 511,
              name: guardianName,
              phone: null,
              address: null,
              relationship_text: null,
              row_version: guardianRowVersion,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/511' && method === 'GET') {
        return jsonResponse({
          id: 511,
          name: '재시도기존',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        if (failOnce) {
          failOnce = false;
          return jsonResponse(
            { error: { code: 'INTERNAL_ERROR', message: '서버 오류' }, field_errors: [] },
            500,
          );
        }
        const recipientBody = (body.recipient as Record<string, unknown> | undefined) ?? {};
        const guardians = body.guardians as Array<Record<string, unknown>>;
        const gPayload = (guardians[0]?.payload as Record<string, unknown> | undefined) ?? {};
        if (typeof gPayload.name === 'string') guardianName = gPayload.name;
        guardianRowVersion = Number(gPayload.expected_row_version ?? guardianRowVersion) + 1;
        return jsonResponse({
          recipient: {
            id: 511,
            name: typeof recipientBody.name === 'string' ? recipientBody.name : '재시도기존',
            birth_date: '1950-03-15',
            sex_code: 'FEMALE',
            recipient_status: 'ACTIVE',
            recipient_no: null,
            postal_code: null,
            address: null,
            home_phone: null,
            mobile_phone: '010-1111-2222',
            memo: null,
            payer_guardian_id: null,
            row_version: 2,
          },
          guardians: [
            {
              id: 41,
              recipient_id: 511,
              name: guardianName,
              phone: null,
              address: null,
              relationship_text: null,
              row_version: guardianRowVersion,
            },
          ],
          saved_sections: ['recipient', 'guardians'],
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /재시도기존/ }));
    await waitFor(() => expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('기존가드'));
    enterBasicEdit();
    fireEvent.change(screen.getByTestId('guardian-1-name-input'), {
      target: { value: '기존가드수정' },
    });
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '재시도기존수정' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchBodies.length).toBe(1));
    await waitFor(() => expect(screen.getByTestId('recipient-basic-save')).not.toBeDisabled());
    // Atomic failure: both drafts remain.
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('기존가드수정');
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('재시도기존수정');

    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    expect(batchBodies[1].recipient).toMatchObject({
      expected_row_version: 1,
      name: '재시도기존수정',
    });
    expect(batchBodies[1].guardians).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          slot: 0,
          guardian_id: 41,
          payload: expect.objectContaining({
            name: '기존가드수정',
            expected_row_version: 1,
          }),
        }),
      ]),
    );
    await waitFor(() =>
      expect(screen.getByText('수급자·보호자·본인부담금을 저장했습니다.')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('기존가드수정');
  });

  test('guardian ROW_VERSION_CONFLICT reloads guardians and shows guardian error not recipient stale panel', async () => {
    let guardianListGets = 0;
    let batchCount = 0;
    let serverGuardianName = '충돌보호자';
    let serverGuardianRowVersion = 1;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 512, name: '보호자충돌' })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        guardianListGets += 1;
        return jsonResponse({
          items: [
            {
              id: 55,
              recipient_id: 512,
              name: serverGuardianName,
              phone: null,
              address: null,
              relationship_text: '자녀',
              row_version: serverGuardianRowVersion,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/512' && method === 'GET') {
        return jsonResponse({
          id: 512,
          name: '보호자충돌',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        batchCount += 1;
        return jsonResponse(
          {
            error: {
              code: 'ROW_VERSION_CONFLICT',
              message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
            },
            field_errors: [],
            details: { current_row_version: serverGuardianRowVersion },
            request_id: 'g-conflict',
          },
          409,
        );
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /보호자충돌/ }));
    await waitFor(() =>
      expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('충돌보호자'),
    );
    expect(guardianListGets).toBe(1);

    // Concurrent edit elsewhere advances server guardian before our batch.
    serverGuardianName = '서버최신보호자';
    serverGuardianRowVersion = 9;

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('guardian-1-name-input'), {
      target: { value: '내쪽수정이름' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchCount).toBe(1));
    await waitFor(() => expect(guardianListGets).toBe(2));
    await waitFor(() =>
      expect(
        screen.getAllByText('보호자 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.').length,
      ).toBeGreaterThan(0),
    );
    expect(screen.queryByTestId('recipient-stale-conflict-message')).toBeNull();
    expect(screen.queryByTestId('recipient-stale-reapply')).toBeNull();
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('서버최신보호자');
  });

  test('entity=guardian conflict routes to guardian reload even when only recipient draft changed', async () => {
    // Local draft inference would pick recipient (recipient draft dirty, guardian clean),
    // but server entity must win and reload guardians instead of the recipient stale panel.
    let guardianListGets = 0;
    let detailGets = 0;
    let batchCount = 0;
    let serverGuardianName = '엔티티가드원본';
    let serverGuardianRowVersion = 1;
    let serverRecipientName = '엔티티가드수신';
    let serverRecipientRowVersion = 1;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([
            listItem({
              id: 520,
              name: serverRecipientName,
              row_version: serverRecipientRowVersion,
            }),
          ]),
        );
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        guardianListGets += 1;
        return jsonResponse({
          items: [
            {
              id: 70,
              recipient_id: 520,
              name: serverGuardianName,
              phone: null,
              address: null,
              relationship_text: '자녀',
              row_version: serverGuardianRowVersion,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/520' && method === 'GET') {
        detailGets += 1;
        return jsonResponse({
          id: 520,
          name: serverRecipientName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRecipientRowVersion,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        batchCount += 1;
        return jsonResponse(
          {
            error: {
              code: 'ROW_VERSION_CONFLICT',
              message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
            },
            field_errors: [],
            details: { current_row_version: serverGuardianRowVersion, entity: 'guardian' },
            request_id: 'entity-guardian-conflict',
          },
          409,
        );
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /엔티티가드수신/ }));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('엔티티가드수신'),
    );
    await waitFor(() =>
      expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('엔티티가드원본'),
    );
    const detailGetsBefore = detailGets;
    const guardianGetsBefore = guardianListGets;

    // Concurrent guardian change on server; user only edits recipient (local inference opposite).
    serverGuardianName = '서버최신가드엔티티';
    serverGuardianRowVersion = 8;

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-name-input'), {
      target: { value: '수신자만수정' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchCount).toBe(1));
    await waitFor(() => expect(guardianListGets).toBe(guardianGetsBefore + 1));
    await waitFor(() =>
      expect(
        screen.getAllByText('보호자 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.').length,
      ).toBeGreaterThan(0),
    );
    // Must not take recipient stale path despite recipient-only draft.
    expect(detailGets).toBe(detailGetsBefore);
    expect(screen.queryByTestId('recipient-stale-conflict-message')).toBeNull();
    expect(screen.queryByTestId('recipient-stale-reapply')).toBeNull();
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('서버최신가드엔티티');
    // Recipient draft is left as-is (guardian path does not overwrite recipient form).
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('수신자만수정');
  });

  test('entity=recipient conflict routes to recipient stale panel even when only guardian draft changed', async () => {
    // Local draft inference would pick guardian (guardian draft dirty, recipient clean),
    // but server entity must win and open the recipient stale panel.
    let guardianListGets = 0;
    let detailGets = 0;
    let batchCount = 0;
    let serverGuardianName = '엔티티수신가드';
    let serverRecipientName = '엔티티수신원본';
    let serverRecipientRowVersion = 1;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([
            listItem({
              id: 521,
              name: serverRecipientName,
              row_version: serverRecipientRowVersion,
            }),
          ]),
        );
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        guardianListGets += 1;
        return jsonResponse({
          items: [
            {
              id: 71,
              recipient_id: 521,
              name: serverGuardianName,
              phone: null,
              address: null,
              relationship_text: '자녀',
              row_version: 1,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/521' && method === 'GET') {
        detailGets += 1;
        return jsonResponse({
          id: 521,
          name: serverRecipientName,
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: serverRecipientRowVersion,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        batchCount += 1;
        return jsonResponse(
          {
            error: {
              code: 'ROW_VERSION_CONFLICT',
              message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
            },
            field_errors: [],
            details: { current_row_version: serverRecipientRowVersion, entity: 'recipient' },
            request_id: 'entity-recipient-conflict',
          },
          409,
        );
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /엔티티수신원본/ }));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('엔티티수신원본'),
    );
    await waitFor(() =>
      expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('엔티티수신가드'),
    );
    const detailGetsBefore = detailGets;
    const guardianGetsBefore = guardianListGets;

    // Concurrent recipient change on server; user only edits guardian (local inference opposite).
    serverRecipientName = '서버최신수신엔티티';
    serverRecipientRowVersion = 7;

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('guardian-1-name-input'), {
      target: { value: '가드만수정' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchCount).toBe(1));
    await waitFor(() => expect(detailGets).toBe(detailGetsBefore + 1));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-stale-latest-value')).toHaveTextContent(
        '서버최신수신엔티티',
      ),
    );
    // Must not take guardian reload path despite guardian-only draft.
    expect(guardianListGets).toBe(guardianGetsBefore);
    expect(
      screen.queryByText('보호자 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.'),
    ).toBeNull();
    // Recipient form shows server latest; guardian draft left as user typed (stale path is recipient-only).
    expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('서버최신수신엔티티');
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('가드만수정');
  });

  test('entity=benefit_period conflict reloads copay periods not recipient/guardian paths', async () => {
    let guardianListGets = 0;
    let detailGets = 0;
    let benefitListGets = 0;
    let batchCount = 0;
    let serverBenefitCode = 'GENERAL';
    let serverBenefitRowVersion = 1;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(
          listResponse([
            listItem({
              id: 522,
              name: '본인부담충돌',
              benefit_code: serverBenefitCode,
              copayment_rate: 15,
            }),
          ]),
        );
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        guardianListGets += 1;
        return jsonResponse({ items: [] });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods') && method === 'GET') {
        benefitListGets += 1;
        return jsonResponse({
          items: [
            {
              id: 90,
              recipient_id: 522,
              benefit_code: serverBenefitCode,
              start_date: '2020-01-01',
              end_date: null,
              invalidated_at_utc: null,
              row_version: serverBenefitRowVersion,
            },
          ],
        });
      }
      if (url.pathname === '/api/v1/recipients/522' && method === 'GET') {
        detailGets += 1;
        return jsonResponse({
          id: 522,
          name: '본인부담충돌',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        batchCount += 1;
        return jsonResponse(
          {
            error: {
              code: 'ROW_VERSION_CONFLICT',
              message: '다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.',
            },
            field_errors: [],
            details: { current_row_version: serverBenefitRowVersion, entity: 'benefit_period' },
            request_id: 'entity-benefit-conflict',
          },
          409,
        );
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /본인부담충돌/ }));
    await waitFor(() =>
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('본인부담충돌'),
    );
    await waitFor(() => expect(screen.getByTestId('recipient-detail-copay')).toHaveValue('GENERAL'));
    const detailGetsBefore = detailGets;
    const guardianGetsBefore = guardianListGets;
    const benefitGetsBefore = benefitListGets;

    // Concurrent benefit change on server; user only changes copay draft.
    serverBenefitCode = 'BASIC_LIVELIHOOD';
    serverBenefitRowVersion = 4;

    enterBasicEdit();
    fireEvent.change(screen.getByTestId('recipient-detail-copay'), {
      target: { value: 'REDUCTION_6' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchCount).toBe(1));
    await waitFor(() => expect(benefitListGets).toBe(benefitGetsBefore + 1));
    await waitFor(() =>
      expect(
        screen.getByText('본인부담금 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.'),
      ).toBeInTheDocument(),
    );
    // Must not open recipient stale panel or reload guardians.
    expect(detailGets).toBe(detailGetsBefore);
    expect(guardianListGets).toBe(guardianGetsBefore);
    expect(screen.queryByTestId('recipient-stale-conflict-message')).toBeNull();
    expect(screen.queryByTestId('recipient-stale-reapply')).toBeNull();
    expect(
      screen.queryByText('보호자 정보가 다른 곳에서 변경되어 최신 정보를 불러왔습니다.'),
    ).toBeNull();
    // Copay control reflects latest server benefit period, not the rejected draft.
    expect(screen.getByTestId('recipient-detail-copay')).toHaveValue('BASIC_LIVELIHOOD');
  });

  test('atomic batch failure with two guardians keeps both drafts dirty; retry resends both', async () => {
    // Atomic semantics: no partial guardian save. Failure keeps both drafts; retry sends both.
    const batchBodies: Array<Record<string, unknown>> = [];
    let failOnce = true;
    let guardian1Name = '보호자일';
    let guardian1RowVersion = 1;
    let guardian2Name = '보호자이';
    let guardian2RowVersion = 1;

    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const rawUrl =
        typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse(listResponse([listItem({ id: 513, name: '쌍보호자부분저장' })]));
      }
      if (url.pathname.endsWith('/guardians') && method === 'GET') {
        return jsonResponse({
          items: [
            {
              id: 61,
              recipient_id: 513,
              name: guardian1Name,
              phone: null,
              address: null,
              relationship_text: null,
              row_version: guardian1RowVersion,
            },
            {
              id: 62,
              recipient_id: 513,
              name: guardian2Name,
              phone: null,
              address: null,
              relationship_text: null,
              row_version: guardian2RowVersion,
            },
          ],
        });
      }
      if (url.pathname.endsWith('/plan-notifications')) return jsonResponse({ items: [] });
      if (url.pathname.endsWith('/benefit-periods')) return jsonResponse({ items: [] });
      if (url.pathname === '/api/v1/recipients/513' && method === 'GET') {
        return jsonResponse({
          id: 513,
          name: '쌍보호자부분저장',
          birth_date: '1950-03-15',
          sex_code: 'FEMALE',
          recipient_status: 'ACTIVE',
          recipient_no: null,
          postal_code: null,
          address: null,
          home_phone: null,
          mobile_phone: '010-1111-2222',
          memo: null,
          payer_guardian_id: null,
          row_version: 1,
        });
      }
      if (isBasicUpdateBatch(url, method)) {
        const body = parseJsonBody(init);
        batchBodies.push(body);
        if (failOnce) {
          failOnce = false;
          return jsonResponse(
            { error: { code: 'INTERNAL_ERROR', message: '서버 오류' }, field_errors: [] },
            500,
          );
        }
        const guardians = body.guardians as Array<Record<string, unknown>>;
        for (const g of guardians) {
          const payload = (g.payload as Record<string, unknown> | undefined) ?? {};
          if (g.slot === 0 && typeof payload.name === 'string') {
            guardian1Name = payload.name;
            guardian1RowVersion = Number(payload.expected_row_version) + 1;
          }
          if (g.slot === 1 && typeof payload.name === 'string') {
            guardian2Name = payload.name;
            guardian2RowVersion = Number(payload.expected_row_version) + 1;
          }
        }
        return jsonResponse({
          recipient: {
            id: 513,
            name: '쌍보호자부분저장',
            birth_date: '1950-03-15',
            sex_code: 'FEMALE',
            recipient_status: 'ACTIVE',
            recipient_no: null,
            postal_code: null,
            address: null,
            home_phone: null,
            mobile_phone: '010-1111-2222',
            memo: null,
            payer_guardian_id: null,
            row_version: 1,
          },
          guardians: [
            {
              id: 61,
              recipient_id: 513,
              name: guardian1Name,
              phone: null,
              address: null,
              relationship_text: null,
              row_version: guardian1RowVersion,
            },
            {
              id: 62,
              recipient_id: 513,
              name: guardian2Name,
              phone: null,
              address: null,
              relationship_text: null,
              row_version: guardian2RowVersion,
            },
          ],
          saved_sections: ['guardians'],
        });
      }
      return jsonResponse({ detail: { code: 'not_found' } }, 404);
    }) as typeof globalThis.fetch;

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByRole('button', { name: /쌍보호자부분저장/ }));
    await waitFor(() => expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('보호자일'));
    await waitFor(() => expect(screen.getByTestId('guardian-2-name-input')).toHaveValue('보호자이'));
    enterBasicEdit();
    fireEvent.change(screen.getByTestId('guardian-1-name-input'), {
      target: { value: '보호자일수정' },
    });
    fireEvent.change(screen.getByTestId('guardian-2-name-input'), {
      target: { value: '보호자이수정' },
    });
    fireEvent.click(screen.getByTestId('recipient-basic-save'));

    await waitFor(() => expect(batchBodies.length).toBe(1));
    // Both drafts stay dirty after atomic failure.
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('보호자일수정');
    expect(screen.getByTestId('guardian-2-name-input')).toHaveValue('보호자이수정');
    await waitFor(() => expect(screen.getByTestId('recipient-basic-save')).not.toBeDisabled());

    fireEvent.click(screen.getByTestId('recipient-basic-save'));
    await waitFor(() => expect(batchBodies.length).toBe(2));
    // Retry resends both guardian slots (no partial skip).
    expect(batchBodies[1].guardians).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          slot: 0,
          guardian_id: 61,
          payload: expect.objectContaining({
            name: '보호자일수정',
            expected_row_version: 1,
          }),
        }),
        expect.objectContaining({
          slot: 1,
          guardian_id: 62,
          payload: expect.objectContaining({
            name: '보호자이수정',
            expected_row_version: 1,
          }),
        }),
      ]),
    );
    await waitFor(() =>
      expect(screen.getByText('수급자·보호자·본인부담금을 저장했습니다.')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('guardian-1-name-input')).toHaveValue('보호자일수정');
    expect(screen.getByTestId('guardian-2-name-input')).toHaveValue('보호자이수정');
    expect(guardian1Name).toBe('보호자일수정');
    expect(guardian2Name).toBe('보호자이수정');
  });
});
