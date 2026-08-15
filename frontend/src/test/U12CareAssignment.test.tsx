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

const staff2 = {
  ...staff,
  id: 30,
  name: '이요양',
  current_employment: {
    ...staff.current_employment,
    id: 31,
    staff_id: 30,
  },
  current_positions: [
    {
      ...staff.current_positions[0],
      id: 32,
      staff_id: 30,
      employment_id: 31,
    },
  ],
};

const staffPeriodEnded = {
  ...staff2,
  id: 40,
  name: '기간부족 요양',
  current_employment: {
    ...staff2.current_employment,
    id: 41,
    staff_id: 40,
    end_date: '2026-06-30',
  },
  current_positions: [
    {
      ...staff2.current_positions[0],
      id: 42,
      staff_id: 40,
      employment_id: 41,
      end_date: '2026-06-30',
    },
  ],
};

const staffUnqualified = {
  ...staff2,
  id: 50,
  name: '자격없는 요양',
  current_employment: {
    ...staff2.current_employment,
    id: 51,
    staff_id: 50,
  },
  current_positions: [
    {
      ...staff2.current_positions[0],
      id: 52,
      staff_id: 50,
      employment_id: 51,
    },
  ],
};

function staffDetailResponse(item: typeof staff | typeof staff2): Record<string, unknown> {
  return {
    ...item,
    employments: [item.current_employment],
    positions: item.current_positions,
    operational_roles: [],
  };
}

function qualificationResponse(staffId: number, employmentId: number): Record<string, unknown> {
  return {
    items: [
      {
        id: staffId * 10,
        staff_id: staffId,
        employment_id: employmentId,
        service_type_code: 'HOME_CARE',
        service_type_display_name: '방문요양',
        service_group_code: 'HOME_CARE',
        start_date: '2026-01-01',
        end_date: null,
        source_license_id: null,
        invalidated_at_utc: null,
        replacement_qualification_id: null,
        row_version: 1,
      },
    ],
  };
}

function staffContextResponse(pathname: string): Response | null {
  const detailMatch = pathname.match(/^\/api\/v1\/staff\/(\d+)$/);
  if (detailMatch) {
    const item = Number(detailMatch[1]) === staff2.id ? staff2 : staff;
    return jsonResponse(staffDetailResponse(item));
  }
  const qualificationMatch = pathname.match(/^\/api\/v1\/staff\/(\d+)\/service-qualifications$/);
  if (qualificationMatch) {
    const item = Number(qualificationMatch[1]) === staff2.id ? staff2 : staff;
    return jsonResponse(qualificationResponse(item.id, item.current_employment.id));
  }
  return null;
}

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
      const staffContext = staffContextResponse(url.pathname);
      if (staffContext && method === 'GET') return staffContext;
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
      const staffContext = staffContextResponse(url.pathname);
      if (staffContext && method === 'GET') return staffContext;
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

  test('keeps authorized assignment history visible when staff lookup is forbidden', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: [contract] });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        return jsonResponse({ detail: { code: 'permission_required' } }, 403);
      }
      if (
        url.pathname === '/api/v1/recipients/1/contracts/10/care-assignments'
        && method === 'GET'
      ) {
        return jsonResponse({
          items: [
            {
              id: 30,
              recipient_id: 1,
              recipient_contract_id: 10,
              staff_id: 20,
              employment_id: 21,
              assignment_kind: 'GENERAL',
              family_relationship_text: null,
              start_date: '2026-08-01',
              end_date: null,
              invalidated_at_utc: null,
              replacement_assignment_id: null,
              row_version: 1,
            },
          ],
        });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientCareAssignmentPanel recipientId={1} />);

    await waitFor(() => {
      expect(screen.getByTestId('care-assignment-row-30')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('care-assignment-error')).not.toBeInTheDocument();
  });

  test('loads every staff page before building the caregiver selector', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: [contract] });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        const page = url.searchParams.get('page');
        return page === '2'
          ? jsonResponse({ items: [staff2], total: 2, page: 2, page_size: 200 })
          : jsonResponse({ items: [staff], total: 2, page: 1, page_size: 200 });
      }
      const staffContext = staffContextResponse(url.pathname);
      if (staffContext && method === 'GET') return staffContext;
      if (url.pathname.endsWith('/care-assignments') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientCareAssignmentPanel recipientId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId('care-assignment-staff-select')).toBeInTheDocument();
    });
    expect(screen.getByRole('option', { name: /이요양/ })).toBeInTheDocument();
  });

  test('requires full assignment-period coverage and GENERAL service qualification', async () => {
    const staffItems = [staff, staffPeriodEnded, staffUnqualified];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: [{ ...contract, end_date: '2026-12-31' }] });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        return jsonResponse({ items: staffItems, total: staffItems.length, page: 1, page_size: 200 });
      }
      const detailMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)$/);
      if (detailMatch && method === 'GET') {
        const item = staffItems.find((candidate) => candidate.id === Number(detailMatch[1]));
        return item
          ? jsonResponse(staffDetailResponse(item))
          : jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
      }
      const qualificationMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)\/service-qualifications$/);
      if (qualificationMatch && method === 'GET') {
        const item = staffItems.find((candidate) => candidate.id === Number(qualificationMatch[1]));
        if (!item) return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
        return item.id === staffUnqualified.id
          ? jsonResponse({ items: [] })
          : jsonResponse(qualificationResponse(item.id, item.current_employment.id));
      }
      if (url.pathname.endsWith('/care-assignments') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientCareAssignmentPanel recipientId={1} />);
    await waitFor(() => expect(screen.getByTestId('care-assignment-staff-select')).toBeInTheDocument());

    expect(screen.getByRole('option', { name: /김요양/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /기간부족 요양/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /자격없는 요양/ })).not.toBeInTheDocument();
  });

  test('bounds staff detail fan-out before building the selector', async () => {
    const manyStaff = Array.from({ length: 8 }, (_, index) => {
      const staffId = 100 + index;
      const employmentId = 200 + index;
      return {
        ...staff,
        id: staffId,
        name: `요양${index}`,
        current_employment: {
          ...staff.current_employment,
          id: employmentId,
          staff_id: staffId,
        },
        current_positions: [
          {
            ...staff.current_positions[0],
            id: 300 + index,
            staff_id: staffId,
            employment_id: employmentId,
          },
        ],
      };
    });
    let activeDetailRequests = 0;
    let maxDetailRequests = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const rawUrl = typeof input === 'string' ? input : (input as Request).url;
      const url = new URL(rawUrl, 'http://localhost');
      const method = (init?.method ?? 'GET').toUpperCase();
      if (url.pathname === '/api/v1/recipients/1/contracts' && method === 'GET') {
        return jsonResponse({ items: [contract] });
      }
      if (url.pathname === '/api/v1/staff' && method === 'GET') {
        return jsonResponse({ items: manyStaff, total: manyStaff.length, page: 1, page_size: 200 });
      }
      const detailMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)$/);
      if (detailMatch && method === 'GET') {
        const item = manyStaff.find((candidate) => candidate.id === Number(detailMatch[1]));
        if (!item) return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
        activeDetailRequests += 1;
        maxDetailRequests = Math.max(maxDetailRequests, activeDetailRequests);
        await new Promise((resolve) => setTimeout(resolve, 5));
        activeDetailRequests -= 1;
        return jsonResponse(staffDetailResponse(item));
      }
      const qualificationMatch = url.pathname.match(/^\/api\/v1\/staff\/(\d+)\/service-qualifications$/);
      if (qualificationMatch && method === 'GET') {
        const item = manyStaff.find((candidate) => candidate.id === Number(qualificationMatch[1]));
        return item
          ? jsonResponse(qualificationResponse(item.id, item.current_employment.id))
          : jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
      }
      if (url.pathname.endsWith('/care-assignments') && method === 'GET') {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ error: { code: 'NOT_FOUND', message: 'not found' } }, 404);
    });

    render(<RecipientCareAssignmentPanel recipientId={1} />);
    await waitFor(() => expect(screen.getByRole('option', { name: /요양0/ })).toBeInTheDocument());
    expect(maxDetailRequests).toBeLessThanOrEqual(6);
  });
});
