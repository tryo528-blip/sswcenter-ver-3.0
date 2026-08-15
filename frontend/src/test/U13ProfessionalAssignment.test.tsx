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

const recipient2 = { ...recipient, id: 2, name: '수급자2', recipient_no: '000002' };
const professionalStaff2 = {
  ...professionalStaff,
  id: 30,
  name: '간호사1',
  current_employment: { ...professionalStaff.current_employment, id: 31, staff_id: 30 },
  current_positions: [
    {
      ...professionalStaff.current_positions[0],
      id: 32,
      staff_id: 30,
      employment_id: 31,
      position_code: 'NURSE',
    },
  ],
};

const professionalStaffOption = {
  id: professionalStaff.id,
  name: professionalStaff.name,
  display_name: professionalStaff.display_name,
  employments: [professionalStaff.current_employment],
  positions: professionalStaff.current_positions,
};

const professionalStaffOption2 = {
  id: professionalStaff2.id,
  name: professionalStaff2.name,
  display_name: professionalStaff2.display_name,
  employments: [professionalStaff2.current_employment],
  positions: professionalStaff2.current_positions,
};

const recipientCapabilities = {
  'staff.view': true,
  'staff.manage': true,
  'staff.sensitive_identity.reveal': true,
  'recipient.view': true,
  'recipient.manage': true,
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
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ items: [professionalStaffOption], total: 1, page: 1, page_size: 200 });
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

  test('keeps assignment history available when staff permission is denied', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ detail: { code: 'permission_required' } }, 403);
      }
      if (url.pathname === '/api/v1/professional-assignments/1' && method === 'GET') {
        return jsonResponse({ items: [] });
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
    await waitFor(() => expect(screen.getByText('담당 없음')).toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('loads recipient and staff pages beyond the first page', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return url.searchParams.get('page') === '2'
          ? jsonResponse({ items: [recipient2], total: 2, page: 2, page_size: 200 })
          : jsonResponse({ items: [recipient], total: 2, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return url.searchParams.get('page') === '2'
          ? jsonResponse({ items: [professionalStaffOption2], total: 2, page: 2, page_size: 200 })
          : jsonResponse({ items: [professionalStaffOption], total: 2, page: 1, page_size: 200 });
      }
      if (url.pathname.endsWith('/professional-assignments/1') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    await waitFor(() => expect(screen.getByText(/수급자2/)).toBeInTheDocument());
    expect(screen.getByTestId('professional-assignment-recipient-select')).toHaveValue('');
  });

  test('ignores a slower assignment response after recipient selection changes', async () => {
    let resolveFirst: ((response: Response) => void) | undefined;
    const assignment = (recipientId: number, staffId: number) => ({
      id: recipientId,
      recipient_id: recipientId,
      service_month: '2026-08-01',
      staff_id: staffId,
      employment_id: 21,
      start_date: '2026-08-01',
      end_date: '2026-08-31',
      invalidated_at_utc: null,
      replacement_assignment_id: null,
      row_version: 1,
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient, recipient2], total: 2, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ detail: { code: 'permission_required' } }, 403);
      }
      if (url.pathname === '/api/v1/professional-assignments/1' && method === 'GET') {
        return new Promise<Response>((resolve) => {
          resolveFirst = resolve;
        });
      }
      if (url.pathname === '/api/v1/professional-assignments/2' && method === 'GET') {
        return jsonResponse({ items: [assignment(2, 30)] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    await waitFor(() => expect(screen.getByText(/수급자2/)).toBeInTheDocument());
    const recipientSelect = screen.getByTestId('professional-assignment-recipient-select');
    fireEvent.change(recipientSelect, { target: { value: '1' } });
    await waitFor(() => expect(resolveFirst).toBeDefined());
    fireEvent.change(recipientSelect, { target: { value: '2' } });
    await waitFor(() => expect(screen.getByTestId('professional-assignment-row-2')).toBeInTheDocument());
    resolveFirst?.(jsonResponse({ items: [assignment(1, 20)] }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByTestId('professional-assignment-row-1')).not.toBeInTheDocument();
  });

  test('only exposes staff whose employment and professional position cover the full range', async () => {
    const partialStaffOption = {
      ...professionalStaffOption,
      id: 40,
      name: '부분 기간 직원',
      employments: [{ ...professionalStaffOption.employments[0], id: 41, staff_id: 40 }],
      positions: [{
        ...professionalStaffOption.positions[0],
        id: 42,
        staff_id: 40,
        employment_id: 41,
        start_date: '2026-08-15',
      }],
    };
    const stitchedStaffOption = {
      ...professionalStaffOption,
      id: 50,
      name: '연속 기간 직원',
      employments: [{ ...professionalStaffOption.employments[0], id: 51, staff_id: 50 }],
      positions: [
        {
          ...professionalStaffOption.positions[0],
          id: 52,
          staff_id: 50,
          employment_id: 51,
          start_date: '2026-08-01',
          end_date: '2026-08-14',
        },
        {
          ...professionalStaffOption.positions[0],
          id: 53,
          staff_id: 50,
          employment_id: 51,
          start_date: '2026-08-15',
          end_date: '2026-08-31',
        },
      ],
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({
          items: [partialStaffOption, stitchedStaffOption],
          total: 2,
          page: 1,
          page_size: 200,
        });
      }
      if (url.pathname === '/api/v1/professional-assignments/1' && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    await waitFor(() => expect(screen.getByTestId('professional-assignment-recipient-select')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('professional-assignment-recipient-select'), {
      target: { value: '1' },
    });
    const staffSelect = await screen.findByTestId('professional-assignment-staff-select');
    await waitFor(() => expect(staffSelect.querySelectorAll('option')).toHaveLength(2));
    expect(staffSelect).toHaveValue('');
    expect(staffSelect.querySelector('option[value="50:51"]')).toBeInTheDocument();
    expect(staffSelect.querySelector('option[value="40:41"]')).not.toBeInTheDocument();
  });

  test('hides management controls and renders every uncovered assignment interval for view-only users', async () => {
    const viewOnlyCapabilities = {
      ...recipientCapabilities,
      'recipient.manage': false,
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(viewOnlyCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ items: [professionalStaffOption], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/1' && method === 'GET') {
        return jsonResponse({
          items: [{
            id: 90,
            recipient_id: 1,
            service_month: '2026-08-01',
            staff_id: 20,
            employment_id: 21,
            start_date: '2026-08-10',
            end_date: '2026-08-20',
            invalidated_at_utc: null,
            replacement_assignment_id: null,
            row_version: 1,
          }],
        });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    fireEvent.change(await screen.findByTestId('professional-assignment-recipient-select'), {
      target: { value: '1' },
    });
    await waitFor(() => expect(screen.getByTestId('professional-assignment-row-90')).toBeInTheDocument());
    expect(screen.queryByTestId('professional-assignment-staff-select')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '정정' })).not.toBeInTheDocument();
    expect(screen.getAllByTestId('professional-assignment-gap')).toHaveLength(2);
  });

  test('clears saving when the recipient context changes during a pending mutation', async () => {
    let resolvePost: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient, recipient2], total: 2, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ items: [professionalStaffOption], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname.endsWith('/professional-assignments/1') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname.endsWith('/professional-assignments/2') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname === '/api/v1/professional-assignments/1/2026-08-01' && method === 'POST') {
        return new Promise<Response>((resolve) => {
          resolvePost = resolve;
        });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    await waitFor(() => expect(screen.getByText(/수급자2/)).toBeInTheDocument());
    const recipientSelect = screen.getByTestId('professional-assignment-recipient-select');
    fireEvent.change(recipientSelect, { target: { value: '1' } });
    const staffSelect = await screen.findByTestId('professional-assignment-staff-select');
    fireEvent.change(staffSelect, { target: { value: '20:21' } });
    fireEvent.click(screen.getByRole('button', { name: '담당 추가' }));
    await waitFor(() => expect(resolvePost).toBeDefined());

    fireEvent.change(recipientSelect, { target: { value: '2' } });
    expect(screen.getByTestId('professional-assignment-staff-select')).toBeEnabled();
    expect(screen.getByRole('button', { name: '담당 추가' })).toBeEnabled();
    resolvePost?.(jsonResponse({ items: [] }));
  });

  test('clears a selected staff member when the edited dates leave its coverage', async () => {
    const partialStaffOption = {
      ...professionalStaffOption,
      id: 40,
      name: '기간 한정 직원',
      employments: [{ ...professionalStaffOption.employments[0], id: 41, staff_id: 40, start_date: '2026-08-15' }],
      positions: [{
        ...professionalStaffOption.positions[0],
        id: 42,
        staff_id: 40,
        employment_id: 41,
        start_date: '2026-08-15',
      }],
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ items: [partialStaffOption], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/1' && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    fireEvent.change(await screen.findByTestId('professional-assignment-recipient-select'), {
      target: { value: '1' },
    });
    const startInput = await screen.findByDisplayValue('2026-08-01');
    fireEvent.change(startInput, { target: { value: '2026-08-15' } });
    const staffSelect = await screen.findByTestId('professional-assignment-staff-select');
    await waitFor(() => expect(staffSelect.querySelector('option[value="40:41"]')).toBeInTheDocument());
    fireEvent.change(staffSelect, { target: { value: '40:41' } });
    expect(staffSelect).toHaveValue('40:41');

    fireEvent.change(startInput, { target: { value: '2026-08-01' } });
    await waitFor(() => expect(staffSelect).toHaveValue(''));
  });

  test('reports a failed save after returning to the same recipient context', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/session-capabilities' && method === 'GET') {
        return jsonResponse(recipientCapabilities);
      }
      if (url.pathname === '/api/v1/recipients' && method === 'GET') {
        return jsonResponse({ items: [recipient, recipient2], total: 2, page: 1, page_size: 200 });
      }
      if (url.pathname === '/api/v1/professional-assignments/staff-options' && method === 'GET') {
        return jsonResponse({ items: [professionalStaffOption], total: 1, page: 1, page_size: 200 });
      }
      if (url.pathname.endsWith('/professional-assignments/1') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname.endsWith('/professional-assignments/2') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      if (url.pathname === '/api/v1/professional-assignments/1/2026-08-01' && method === 'POST') {
        throw new Error('save failed');
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<ProfessionalAssignmentWorkspace />);
    await waitFor(() => expect(screen.getByText(/수급자2/)).toBeInTheDocument());
    const recipientSelect = screen.getByTestId('professional-assignment-recipient-select');
    fireEvent.change(recipientSelect, { target: { value: '1' } });
    const staffSelect = await screen.findByTestId('professional-assignment-staff-select');
    fireEvent.change(staffSelect, { target: { value: '20:21' } });
    fireEvent.click(screen.getByRole('button', { name: '담당 추가' }));
    fireEvent.change(recipientSelect, { target: { value: '2' } });
    fireEvent.change(recipientSelect, { target: { value: '1' } });

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('save failed'));
  });
});
