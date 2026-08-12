import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  fetchAllStaff,
  fetchStaffList,
  type StaffListResponse,
} from '../services/staffApi';

type StaffItem = StaffListResponse['items'][number];
type RequestRecord = { url: URL; init: RequestInit };

const originalFetch = globalThis.fetch;

function staff(id: number): StaffItem {
  return { id } as StaffItem;
}

function page(
  items: StaffItem[],
  total: number,
  pageNumber: number,
  pageSize = 200,
): StaffListResponse {
  return { items, total, page: pageNumber, page_size: pageSize };
}

function response(payload: StaffListResponse): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installPagingFetch(pages: Map<number, StaffListResponse>): RequestRecord[] {
  const requests: RequestRecord[] = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const inputUrl =
      typeof input === 'string' ? input : input instanceof Request ? input.url : input.toString();
    const url = new URL(inputUrl, 'http://localhost');
    requests.push({ url, init: init ?? {} });

    const pageNumber = Number(url.searchParams.get('page'));
    const payload = pages.get(pageNumber);
    if (!payload) throw new Error(`Unexpected staff page ${pageNumber}`);
    return Promise.resolve(response(payload));
  }) as typeof globalThis.fetch;
  return requests;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe('staff API pagination', () => {
  it('preserves fetchStaffList signature, page_size=1 URL, and signal', async () => {
    const controller = new AbortController();
    const requests = installPagingFetch(new Map([[4, page([], 0, 4, 1)]]));

    await fetchStaffList('  김민수  ', controller.signal, 4);

    expect(requests).toHaveLength(1);
    expect(requests[0].url.pathname).toBe('/api/v1/staff');
    expect(requests[0].url.searchParams.get('page')).toBe('4');
    expect(requests[0].url.searchParams.get('page_size')).toBe('1');
    expect(requests[0].url.searchParams.get('search')).toBe('김민수');
    expect(requests[0].init.signal).toBe(controller.signal);
  });

  it('deduplicates overlapping pages by stable staff id and advances page numbers', async () => {
    const controller = new AbortController();
    const requests = installPagingFetch(
      new Map([
        [1, page([staff(1), staff(2)], 4, 1)],
        [2, page([staff(2), staff(3)], 4, 2)],
        [3, page([staff(4)], 4, 3)],
      ]),
    );

    const result = await fetchAllStaff(controller.signal);

    expect(result.items.map((item) => item.id)).toEqual([1, 2, 3, 4]);
    expect(result.total).toBe(4);
    expect(requests.map(({ url }) => url.searchParams.get('page'))).toEqual(['1', '2', '3']);
    expect(requests.every(({ init }) => init.signal === controller.signal)).toBe(true);
  });

  it('continues after a short middle page until unique staff reaches total', async () => {
    const controller = new AbortController();
    const firstPageItems = Array.from({ length: 200 }, (_, index) => staff(index + 1));
    const requests = installPagingFetch(
      new Map([
        [1, page(firstPageItems, 203, 1)],
        [2, page([staff(201)], 203, 2)],
        [3, page([staff(202), staff(203)], 203, 3)],
      ]),
    );

    const result = await fetchAllStaff(controller.signal);

    expect(result.items).toHaveLength(203);
    expect(new Set(result.items.map((item) => item.id)).size).toBe(203);
    expect(result.items.slice(-3).map((item) => item.id)).toEqual([201, 202, 203]);
    expect(requests.map(({ url }) => url.searchParams.get('page'))).toEqual(['1', '2', '3']);
    expect(requests.every(({ init }) => init.signal === controller.signal)).toBe(true);
  });
});
