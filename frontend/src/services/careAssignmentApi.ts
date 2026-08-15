import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];

export type AssignmentKind = Schemas['AssignmentKind'];
export type CareAssignment = Schemas['CareAssignmentResponse'];
export type CareAssignmentCreateRequest = Schemas['CareAssignmentCreateRequest'];
export type CareAssignmentReplaceRequest = Schemas['CareAssignmentReplaceRequest'];

export type RecipientId = number | string;

function assignmentPath(
  recipientId: RecipientId,
  contractId: RecipientId,
): string {
  return `/api/v1/recipients/${encodeURIComponent(String(recipientId))}/contracts/${encodeURIComponent(String(contractId))}/care-assignments`;
}

export function listCareAssignments(
  recipientId: RecipientId,
  contractId: RecipientId,
  signal?: AbortSignal,
): Promise<Schemas['CareAssignmentListResponse']> {
  return apiRequest<Schemas['CareAssignmentListResponse']>(
    assignmentPath(recipientId, contractId),
    { method: 'GET', signal },
  );
}

export function createCareAssignment(
  recipientId: RecipientId,
  contractId: RecipientId,
  payload: CareAssignmentCreateRequest,
  signal?: AbortSignal,
): Promise<CareAssignment> {
  return apiRequest<CareAssignment>(assignmentPath(recipientId, contractId), {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export function replaceCareAssignment(
  recipientId: RecipientId,
  contractId: RecipientId,
  assignmentId: RecipientId,
  payload: CareAssignmentReplaceRequest,
  signal?: AbortSignal,
): Promise<CareAssignment> {
  return apiRequest<CareAssignment>(
    `${assignmentPath(recipientId, contractId)}/${encodeURIComponent(String(assignmentId))}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
      signal,
    },
  );
}
