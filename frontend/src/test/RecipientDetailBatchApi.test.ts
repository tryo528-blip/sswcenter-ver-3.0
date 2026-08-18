import './setup';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { saveRecipientDetailBatch } from '../services/recipientDetailBatchApi';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('recipient detail batch API adapter', () => {
  test('serializes the PostgreSQL bigint maximum as an exact JSON integer', async () => {
    let postedBody = '';
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      postedBody = String(init?.body ?? '');
      return new Response(
        JSON.stringify({ recipient_id: 42, saved_sections: ['approval_amount_period'] }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });

    await saveRecipientDetailBatch(42, {
      approval_amount_period: {
        payload: {
          amount_krw: '9223372036854775807',
          start_date: '2026-08-01',
          end_date: null,
        },
      },
    });

    expect(postedBody).toContain('"amount_krw":9223372036854775807');
    expect(postedBody).not.toContain('"amount_krw":"9223372036854775807"');
  });

  test('rejects an amount outside the PostgreSQL bigint range before fetch', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    expect(() =>
      saveRecipientDetailBatch(42, {
        approval_amount_period: {
          payload: {
            amount_krw: '9223372036854775808',
            start_date: '2026-08-01',
          },
        },
      }),
    ).toThrow('amount_krw must be a PostgreSQL bigint');
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
