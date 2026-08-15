import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import RecipientCareAssignmentPanel from '../components/recipients/RecipientCareAssignmentPanel';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const contract = {
  id: 10,
  recipient_id: 1,
  service_type_code: 'HOME_CARE',
  service_group_code: 'HOME_CARE',
  start_date: '2026-08-01',
  end_date: null,
  service_start_date: null,
  end_reason_text: null,
  invalidated_at_utc: null,
  replacement_contract_id: null,
  row_version: 1,
};

const staff = {
  id: 20,
  name: '김요양',
  birth_date: '1980-01-01',
  sex_code: 'FEMALE',
  phone: null,
  address: null,
  display_name: null,
  memo: null,
  resident_number_masked: null,
  row_version: 1,
  current_employment: {
    id: 21,
    staff_id: 20,
    employment_no: 1,
    staff_no: 'S-001',
    start_date: '2026-01-01',
    end_date: null,
    end_reason_code: null,
    status: 'ACTIVE',
    row_version: 1,
  },
  current_positions: [
    {
      id: 22,
      staff_id: 20,
      employment_id: 21,
      position_code: 'CARE_WORKER',
      start_date: '2026-01-01',
      end_date: null,
      row_version: 1,
    },
  ],
  current_operational_roles: [],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('U12 caregiver assignment panel', () => {
  test('loads contract/staff context and creates a GENERAL period assignment', async () => {
    const posted: Record<string, unknown>[] = [];
    let assignments: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: [contract] });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        return jsonResponse({ items: [staff], total: 1, page: 1, page_size: 200 });
      }
      if (
        url.pathname === '/api/v1/recipients/1/contracts/10/care-assignments'
        && method === 'GET'
      ) {
        return jsonResponse({ items: assignments });
      }
      if (
        url.pathname === '/api/v1/recipients/1/contracts/10/care-assignments'
        && method === 'POST'
      ) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posted.push(body);
        assignments = [
          {
            id: 30,
            recipient_id: 1,
            recipient_contract_id: 10,
            ...body,
            invalidated_at_utc: null,
            replacement_assignment_id: null,
            row_version: 1,
          },
        ];
        return jsonResponse(assignments[0], 201);
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientCareAssignmentPanel recipientId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId('care-assignment-form')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('care-assignment-staff-select'), {
      target: { value: '20:21' },
    });
    fireEvent.change(screen.getByTestId('care-assignment-start-date-input'), {
      target: { value: '2026-08-01' },
    });
    fireEvent.click(screen.getByRole('button', { name: '배정 추가' }));

    await waitFor(() => {
      expect(posted).toEqual([
        {
          staff_id: 20,
          employment_id: 21,
          assignment_kind: 'GENERAL',
          family_relationship_text: null,
          start_date: '2026-08-01',
          end_date: null,
        },
      ]);
      expect(screen.getByTestId('care-assignment-row-30')).toBeInTheDocument();
    });
  });

  test('requires a relationship snapshot for FAMILY before posting', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: [contract] });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        return jsonResponse({ items: [staff], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname.endsWith('/care-assignments') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'UNEXPECTED', message: 'unexpected' } }, 500);
    });

    render(<RecipientCareAssignmentPanel recipientId={1} />);
    await waitFor(() => expect(screen.getByTestId('care-assignment-form')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('care-assignment-staff-select'), {
      target: { value: '20:21' },
    });
    fireEvent.change(screen.getByTestId('care-assignment-kind-select'), {
      target: { value: 'FAMILY' },
    });
    fireEvent.change(screen.getByTestId('care-assignment-start-date-input'), {
      target: { value: '2026-08-01' },
    });
    fireEvent.submit(screen.getByTestId('care-assignment-form'));
    expect(await screen.findByTestId('care-assignment-error')).toHaveTextContent(
      '가족요양은 관계 snapshot을 입력해야 합니다.',
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining('/care-assignments'),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
