import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];

export type ProfessionalAssignment = Schemas['ProfessionalAssignmentResponse'];
export type ProfessionalAssignmentHistory = Schemas['ProfessionalAssignmentHistoryResponse'];

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
