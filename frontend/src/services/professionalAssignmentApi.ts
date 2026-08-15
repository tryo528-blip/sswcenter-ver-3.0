import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];

export type ProfessionalAssignment = Schemas['ProfessionalAssignmentResponse'];
export type ProfessionalAssignmentHistory = Schemas['ProfessionalAssignmentHistoryResponse'];
export type ProfessionalAssignmentStaffOptions =
  Schemas['ProfessionalAssignmentStaffOptionListResponse'];
export type ProfessionalAssignmentStaffOption =
  Schemas['ProfessionalAssignmentStaffOptionResponse'];

export type ProfessionalAssignmentInput = {
  staff_id: number;
  employment_id: number;
  start_date: string;
  end_date: string;
};

export type ProfessionalAssignmentReplaceInput = ProfessionalAssignmentInput & {
  expected_row_version: number;
};

function assignmentPath(recipientId: number | string, serviceMonth: string): string {
  return `/api/v1/professional-assignments/${encodeURIComponent(String(recipientId))}/${encodeURIComponent(serviceMonth)}`;
}

export function listProfessionalAssignments(
  recipientId: number | string,
  serviceMonth: string,
  signal?: AbortSignal,
): Promise<ProfessionalAssignmentHistory> {
  const query = new URLSearchParams({ service_month: serviceMonth });
  return apiRequest<ProfessionalAssignmentHistory>(
    `/api/v1/professional-assignments/${encodeURIComponent(String(recipientId))}?${query.toString()}`,
    { method: 'GET', signal },
  );
}

export function listProfessionalAssignmentStaffOptions(
  options: {
    page?: number;
    pageSize?: number;
    search?: string;
    signal?: AbortSignal;
  } = {},
): Promise<ProfessionalAssignmentStaffOptions> {
  const query = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 200),
  });
  if (options.search?.trim()) query.set('search', options.search.trim());
  return apiRequest<ProfessionalAssignmentStaffOptions>(
    `/api/v1/professional-assignments/staff-options?${query.toString()}`,
    { method: 'GET', signal: options.signal },
  );
}

export async function fetchAllProfessionalAssignmentStaffOptions(
  signal?: AbortSignal,
): Promise<{ items: ProfessionalAssignmentStaffOptions['items']; total: number }> {
  const pageSize = 200;
  const maxPages = 1_000;
  const first = await listProfessionalAssignmentStaffOptions({ page: 1, pageSize, signal });
  const uniqueItems = new Map<number, ProfessionalAssignmentStaffOptions['items'][number]>();
  for (const item of first.items) {
    if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item);
  }
  const total = first.total;
  let page = 2;
  while (uniqueItems.size < total && page <= maxPages) {
    const response = await listProfessionalAssignmentStaffOptions({ page, pageSize, signal });
    for (const item of response.items) {
      if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item);
    }
    if (!response.items.length) break;
    page += 1;
  }
  return { items: [...uniqueItems.values()], total };
}

export function createProfessionalAssignment(
  recipientId: number | string,
  serviceMonth: string,
  payload: ProfessionalAssignmentInput,
): Promise<ProfessionalAssignment> {
  return apiRequest<ProfessionalAssignment>(assignmentPath(recipientId, serviceMonth), {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function replaceProfessionalAssignment(
  recipientId: number | string,
  serviceMonth: string,
  assignmentId: number | string,
  payload: ProfessionalAssignmentReplaceInput,
): Promise<ProfessionalAssignment> {
  return apiRequest<ProfessionalAssignment>(
    `${assignmentPath(recipientId, serviceMonth)}/${encodeURIComponent(String(assignmentId))}`,
    { method: 'PUT', body: JSON.stringify(payload) },
  );
}
