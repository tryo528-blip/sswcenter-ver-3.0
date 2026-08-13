import './setup';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import RecipientContractPanel from '../components/recipients/RecipientContractPanel';
import type { ContractResponse } from '../services/w1dApi';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function contract(
  id: number,
  recipientId: number,
  serviceType = 'HOME_CARE',
): ContractResponse {
  return {
    id,
    recipient_id: recipientId,
    service_type_code: serviceType,
    service_group_code: null,
    start_date: '2026-08-01',
    end_date: null,
    service_start_date: null,
    end_reason_text: null,
    invalidated_at_utc: null,
    replacement_contract_id: null,
    row_version: 1,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RecipientContractPanel current contract', () => {
  test('creates a contract without signer or certification-transition fields', async () => {
    const posted: Record<string, unknown>[] = [];
    const onRecipientMutated = vi.fn();
    let rows = [contract(10, 1)];

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: rows });
      }
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'POST') {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posted.push(body);
        const created = {
          ...contract(11, 1, String(body.service_type_code)),
          start_date: String(body.start_date),
          end_date: body.end_date as string | null,
          service_start_date: body.service_start_date as string | null,
          end_reason_text: body.end_reason_text as string | null,
        };
        rows = [...rows, created];
        return jsonResponse(created, 201);
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    const { container } = render(
      <RecipientContractPanel
        recipientId={1}
        recipientNo="R-001"
        onRecipientMutated={onRecipientMutated}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('contract-row-10')).toBeInTheDocument();
    });

    expect(container.querySelector('[data-testid*="transition"]')).toBeNull();
    expect(container.querySelector('[data-testid*="signer"]')).toBeNull();
    expect(screen.queryByText(/계약자|서명자|등급 전환/)).toBeNull();

    fireEvent.change(screen.getByTestId('contract-service-type-select'), {
      target: { value: 'HOME_BATH' },
    });
    fireEvent.change(screen.getByTestId('contract-start-date-input'), {
      target: { value: '2026-09-01' },
    });
    fireEvent.change(screen.getByTestId('contract-end-date-input'), {
      target: { value: '2026-12-31' },
    });
    fireEvent.change(screen.getByTestId('contract-service-start-date-input'), {
      target: { value: '2026-09-02' },
    });
    fireEvent.change(screen.getByTestId('contract-end-reason-input'), {
      target: { value: '기관 요청' },
    });
    fireEvent.click(screen.getByRole('button', { name: '새 계약' }));

    await waitFor(() => {
      expect(posted).toEqual([
        {
          service_type_code: 'HOME_BATH',
          start_date: '2026-09-01',
          end_date: '2026-12-31',
          service_start_date: '2026-09-02',
          end_reason_text: '기관 요청',
        },
      ]);
      expect(screen.getByTestId('contract-row-11')).toBeInTheDocument();
      expect(onRecipientMutated).toHaveBeenCalledTimes(1);
    });
    expect(posted[0]).not.toHaveProperty('signer_name');
    expect(posted[0]).not.toHaveProperty('signer_relationship_text');
  });

  test('recipient switch resets the draft and ignores a late old list response', async () => {
    const oldList = deferred<Response>();

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'GET' && url.pathname === '/api/v1/recipients/1/contracts') {
        return oldList.promise;
      }
      if (method === 'GET' && url.pathname === '/api/v1/recipients/2/contracts') {
        return jsonResponse({ items: [contract(20, 2, 'BARO_CARE')] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    const { rerender } = render(
      <RecipientContractPanel recipientId={1} recipientNo="R-001" />,
    );
    fireEvent.change(screen.getByTestId('contract-start-date-input'), {
      target: { value: '2026-10-01' },
    });
    fireEvent.change(screen.getByTestId('contract-end-reason-input'), {
      target: { value: 'old draft' },
    });

    rerender(<RecipientContractPanel recipientId={2} recipientNo="R-002" />);

    await waitFor(() => {
      expect(screen.getByTestId('contract-row-20')).toBeInTheDocument();
      expect(screen.getByTestId('contract-recipient-no-display')).toHaveTextContent('R-002');
    });
    expect(screen.getByTestId('contract-start-date-input')).toHaveValue('');
    expect(screen.getByTestId('contract-end-reason-input')).toHaveValue('');

    await act(async () => {
      oldList.resolve(jsonResponse({ items: [contract(10, 1)] }));
      await oldList.promise;
    });

    expect(screen.queryByTestId('contract-row-10')).toBeNull();
    expect(screen.getByTestId('contract-row-20')).toBeInTheDocument();
  });

  test('list failures remain accessible', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse(
        { error: { code: 'CONTRACT_LIST_FAILED', message: '계약 조회 실패' } },
        500,
      ),
    );

    render(<RecipientContractPanel recipientId={1} recipientNo={null} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('계약 조회 실패');
    expect(alert).toHaveAttribute('aria-live', 'assertive');
  });
});
