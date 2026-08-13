import './setup';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import RecipientsPage from '../pages/RecipientsPage';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function recipientDetail(id: number, name: string | null, payerGuardianId: number | null = null) {
  return {
    id,
    name,
    birth_date: null,
    sex_code: null,
    recipient_status: 'ACTIVE',
    recipient_no: null,
    postal_code: null,
    address: null,
    mobile_phone: '010-1000-0000',
    memo: null,
    payer_guardian_id: payerGuardianId,
    row_version: 1,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

describe('W1 recipient corrected basic contract', () => {
  test('mobile_phone is the only required recipient field and blank optional values can be created', async () => {
    window.history.replaceState({}, '', '/recipients');
    let posted: Record<string, unknown> | null = null;
    const createdRecipient = recipientDetail(99, null, 501);
    const createdGuardian = {
      id: 501,
      recipient_id: 99,
      name: null,
      relationship_text: null,
      phone: null,
      address: null,
      email: null,
      row_version: 1,
    };

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
      }
      if (url.pathname === '/api/v1/recipients/basic-batch' && method === 'POST') {
        posted = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return jsonResponse(
          {
            recipient: createdRecipient,
            guardians: [createdGuardian],
            saved_sections: ['recipient', 'guardians', 'payer', 'benefit_period'],
          },
          201,
        );
      }
      if (url.pathname === '/api/v1/recipients/99' && method === 'GET') {
        return jsonResponse(createdRecipient);
      }
      if (url.pathname === '/api/v1/recipients/99/guardians' && method === 'GET') {
        return jsonResponse({ items: [createdGuardian] });
      }
      if (url.pathname === '/api/v1/recipients/99/benefit-periods' && method === 'GET') {
        return jsonResponse({
          items: [
            {
              id: 701,
              recipient_id: 99,
              benefit_code: 'GENERAL',
              start_text: '',
              invalidated_at_utc: null,
              replacement_benefit_period_id: null,
              row_version: 1,
            },
          ],
        });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientsPage />);
    fireEvent.click(await screen.findByTestId('recipient-create-toggle'));
    const form = screen.getByTestId('recipient-create-form');

    const optionalControls = [
      'recipient-name-input',
      'recipient-birth-date-input',
      'recipient-sex-code-select',
      'recipient-postal-code-input',
      'recipient-address-input',
      'recipient-memo-input',
    ];
    for (const testId of optionalControls) {
      expect(within(form).getByTestId(testId)).not.toBeRequired();
    }
    const mobile = within(form).getByTestId('recipient-mobile-phone-input');
    expect(mobile).toBeRequired();

    for (const slot of [1, 2]) {
      const guardianSection = screen.getByTestId(`recipient-guardian-${slot}-section`);
      const expected = [
        `guardian-${slot}-name-input`,
        `guardian-${slot}-relationship-input`,
        `guardian-${slot}-phone-input`,
        `guardian-${slot}-address-input`,
        `guardian-${slot}-email-input`,
      ];
      for (const testId of expected) {
        expect(within(guardianSection).getByTestId(testId)).not.toBeRequired();
      }
      expect(within(guardianSection).queryByTestId(`guardian-${slot}-postal-code-input`)).toBeNull();
      expect(within(guardianSection).queryByTestId(`guardian-${slot}-address-detail-input`)).toBeNull();
    }
    expect(screen.queryByTestId('recipient-guardian-3-section')).toBeNull();

    fireEvent.change(mobile, { target: { value: '01010000000' } });
    fireEvent.click(screen.getByTestId('guardian-1-payer-checkbox'));
    fireEvent.click(screen.getByTestId('recipient-create-toggle'));

    await waitFor(() => expect(posted).not.toBeNull());
    const body = posted as unknown as Record<string, unknown>;
    expect(body).toEqual({
      recipient: {
        name: null,
        birth_date: null,
        sex_code: null,
        postal_code: null,
        address: null,
        mobile_phone: '010-1000-0000',
        memo: null,
      },
      guardians: [
        {
          slot: 0,
          payload: {
            name: null,
            relationship_text: null,
            phone: null,
            address: null,
            email: null,
          },
        },
      ],
      payer_guardian_slot: 0,
    });
    expect(body).not.toHaveProperty('benefit_period');
  });

  test('null and blank stored names display exactly 미입력 without issuing a write', async () => {
    window.history.replaceState({}, '', '/recipients');
    const writes: string[] = [];
    const detail = recipientDetail(7, '   ');

    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method !== 'GET') writes.push(`${method} ${url.pathname}`);
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({
          items: [
            {
              id: 7,
              name: null,
              birth_date: null,
              sex_code: null,
              recipient_no: null,
              postal_code: null,
              address: null,
              mobile_phone: '010-1000-0000',
              memo: null,
              row_version: 1,
              grade_code: null,
              benefit_code: 'GENERAL',
              copayment_rate: null,
              services: [],
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        });
      }
      if (url.pathname === '/api/v1/recipients/7' && method === 'GET') {
        return jsonResponse(detail);
      }
      if (url.pathname === '/api/v1/recipients/7/guardians' && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname === '/api/v1/recipients/7/benefit-periods' && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientsPage />);

    const row = await screen.findByTestId('recipient-name-option');
    expect(row.querySelector('strong')).toHaveTextContent(/^미입력$/);
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '미입력' })).toBeInTheDocument();
      expect(screen.getByTestId('recipient-detail-name-input')).toHaveValue('   ');
    });
    expect(writes).toEqual([]);
  });
});
