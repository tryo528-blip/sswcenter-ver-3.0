import './setup';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createContract, endContract, listContracts } from '../services/w1dApi';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});
describe('W1D contract API adapter', () => {
  test('uses only current contract endpoints and sends no signer fields', async () => {
    const requests: Array<{
      path: string;
      method: string;
      body: Record<string, unknown> | null;
    }> = [];

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      requests.push({
        path: url.pathname,
        method,
        body: init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : null,
      });

      if (method === 'GET') return jsonResponse({ items: [] });
      return jsonResponse({
        id: 1,
        recipient_id: 42,
        service_type_code: 'HOME_CARE',
        service_group_code: null,
        start_date: '2026-08-01',
        end_date: null,
        service_start_date: null,
        end_reason_text: null,
        invalidated_at_utc: null,
        replacement_contract_id: null,
        row_version: 1,
      });
    });

    await listContracts(42);
    await createContract(42, {
      service_type_code: 'HOME_CARE',
      start_date: '2026-08-01',
      end_date: null,
      service_start_date: null,
      end_reason_text: null,
    });
    await endContract(42, 1, {
      expected_row_version: 7,
      end_date: '2026-12-31',
      end_reason_text: '종료',
    });

    expect(requests).toEqual([
      {
        path: '/api/v1/recipients/42/contracts',
        method: 'GET',
        body: null,
      },
      {
        path: '/api/v1/recipients/42/contracts',
        method: 'POST',
        body: {
          service_type_code: 'HOME_CARE',
          start_date: '2026-08-01',
          end_date: null,
          service_start_date: null,
          end_reason_text: null,
        },
      },
      {
        path: '/api/v1/recipients/42/contracts/1/end',
        method: 'POST',
        body: {
          expected_row_version: 7,
          end_date: '2026-12-31',
          end_reason_text: '종료',
        },
      },
    ]);

    for (const request of requests) {
      expect(request.path).not.toContain('certification-transitions');
      if (request.body) {
        expect(request.body).not.toHaveProperty('signer_name');
        expect(request.body).not.toHaveProperty('signer_relationship_text');
      }
    }
  });
});
