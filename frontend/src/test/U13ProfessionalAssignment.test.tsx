import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';
import ProfessionalAssignmentWorkspace from '../components/social-workers/ProfessionalAssignmentWorkspace';
import {
  createProfessionalAssignment,
  listProfessionalAssignments,
  replaceProfessionalAssignment,
} from '../services/professionalAssignmentApi';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const recipient = {
  id: 1,
  name: '수급자1',
  birth_date: '1940-01-01',
  sex_code: 'FEMALE',
  recipient_no: '000001',
  postal_code: null,
  address: null,
  mobile_phone: '010-0000-0000',
  memo: null,
  row_version: 1,
  grade_code: null,
  benefit_code: null,
  copayment_rate: null,
  services: [],
};

const professionalStaff = {
  id: 20,
  name: '사회복지사1',
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
      position_code: 'SOCIAL_WORKER',
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

describe('U13 professional assignment client and workspace', () => {
  test('uses the current list/create/replace endpoints and payload names', async () => {
    const requests: Array<{ path: string; method: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      requests.push({
        path: `${url.pathname}${url.search}`,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });
      if (method === 'GET') return jsonResponse({ items: [] });
      return jsonResponse({
        id: 1,
        recipient_id: 42,
        service_month: '2026-08-01',
        staff_id: 20,
        employment_id: 21,
        start_date: '2026-08-01',
        end_date: '2026-08-31',
        invalidated_at_utc: null,
        replacement_assignment_id: null,
        row_version: 1,
      });
    });

    await listProfessionalAssignments(42, '2026-08-01');
    await createProfessionalAssignment(42, '2026-08-01', {
      staff_id: 20,
      employment_id: 21,
      start_date: '2026-08-01',
      end_date: '2026-08-31',
    });
    await replaceProfessionalAssignment(42, '2026-08-01', 1, {
      staff_id: 20,
      employment_id: 21,
      start_date: '2026-08-10',
      end_date: '2026-08-31',
      expected_row_version: 1,
    });

    expect(requests).toEqual([
      {
        path: '/api/v1/professional-assignments/42?service_month=2026-08-01',
        method: 'GET',
        body: null,
      },
      {
        path: '/api/v1/professional-assignments/42/2026-08-01',
        method: 'POST',
        body: {
          staff_id: 20,
          employment_id: 21,
          start_date: '2026-08-01',
          end_date: '2026-08-31',
        },
      },
      {
        path: '/api/v1/professional-assignments/42/2026-08-01/1',
        method: 'PUT',
        body: {
          staff_id: 20,
          employment_id: 21,
          start_date: '2026-08-10',
          end_date: '2026-08-31',
          expected_row_version: 1,
        },
      },
    ]);
  });

  test('loads one shared recipient-month workspace and posts a professional assignment', async () => {
    const posted: Record<string, unknown>[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        return jsonResponse({ items: [professionalStaff], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/1' && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname === '/api/v1/professional-assignments/1/2026-08-01' && method === 'POST') {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posted.push(body);
        return jsonResponse(
          {
            id: 30,
            recipient_id: 1,
            service_month: '2026-08-01',
            ...body,
            invalidated_at_utc: null,
            replacement_assignment_id: null,
            row_version: 1,
          },
          201,
        );
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    await waitFor(() => {
      expect(screen.getByTestId('professional-assignment-recipient-select')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('professional-assignment-recipient-select'), {
      target: { value: '1' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('professional-assignment-staff-select')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByTestId('professional-assignment-staff-select'), {
      target: { value: '20:21' },
    });
    fireEvent.click(screen.getByRole('button', { name: '담당 추가' }));

    await waitFor(() => {
      expect(posted).toEqual([
        {
          staff_id: 20,
          employment_id: 21,
          start_date: '2026-08-01',
          end_date: '2026-08-31',
        },
      ]);
    });
  });
});
