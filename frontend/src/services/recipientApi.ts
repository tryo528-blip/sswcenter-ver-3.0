import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];

export type RecipientStatus = Schemas['RecipientStatus'];
export type RecipientListStatusFilter = Schemas['RecipientListStatusFilter'];
export type RecipientListServiceGroupItem = Schemas['RecipientListServiceGroupItem'];
export type RecipientListServiceTypeItem = Schemas['RecipientListServiceTypeItem'];
export type RecipientInputSexCode = Schemas['RecipientInputSexCode'];
export type RecipientSexCode = Schemas['RecipientSexCode'];

// These recipient contracts intentionally mirror the current backend schema.
// The checked-in generated file is regenerated globally by the coordinator and
// can temporarily describe the superseded W1 contract while this slice lands.
export interface RecipientCreateRequest {
  name?: string | null;
  birth_date?: string | null;
  sex_code?: RecipientInputSexCode | null;
  postal_code?: string | null;
  address?: string | null;
  mobile_phone: string;
  memo?: string | null;
}

export interface RecipientUpdateRequest {
  expected_row_version: number;
  name?: string | null;
  birth_date?: string | null;
  sex_code?: RecipientInputSexCode | null;
  recipient_status?: RecipientStatus;
  postal_code?: string | null;
  address?: string | null;
  mobile_phone?: string;
  memo?: string | null;
  /** Omit = preserve, null = recipient self, positive id = guardian payer. */
  payer_guardian_id?: number | null;
}

export interface Recipient {
  id: number;
  name: string | null;
  birth_date: string | null;
  sex_code: RecipientSexCode | null;
  recipient_status: RecipientStatus;
  recipient_no: string | null;
  postal_code: string | null;
  address: string | null;
  mobile_phone: string;
  memo: string | null;
  payer_guardian_id: number | null;
  row_version: number;
}

export interface RecipientListItem {
  id: number;
  name: string | null;
  birth_date: string | null;
  sex_code: RecipientSexCode | null;
  recipient_no: string | null;
  postal_code: string | null;
  address: string | null;
  mobile_phone: string;
  memo: string | null;
  row_version: number;
  grade_code: string | null;
  benefit_code: string | null;
  copayment_rate: number | null;
  services: RecipientListServiceGroupItem[];
}

export interface RecipientListResponse {
  items: RecipientListItem[];
  total: number;
  page: number;
  page_size: number;
}

/** Sealed manual-tag values for detail validation (ACTIVE|ENDED|WAITING). */
export const RECIPIENT_STATUS_VALUES = ['ACTIVE', 'ENDED', 'WAITING'] as const;

export function isRecipientStatus(value: unknown): value is RecipientStatus {
  return (
    value === 'ACTIVE' ||
    value === 'ENDED' ||
    value === 'WAITING'
  );
}
export interface GuardianCreateRequest {
  name?: string | null;
  relationship_text?: string | null;
  phone?: string | null;
  address?: string | null;
  email?: string | null;
}

export interface GuardianUpdateRequest extends GuardianCreateRequest {
  expected_row_version: number;
}

export interface Guardian {
  id: number;
  recipient_id: number;
  slot_no?: 1 | 2;
  name: string | null;
  relationship_text: string | null;
  phone: string | null;
  address: string | null;
  email: string | null;
  row_version: number;
}

export interface GuardianListResponse {
  items: Guardian[];
}
export type RecipientDeadlineKind = 'CERTIFICATION_EXPIRY' | 'CONTRACT_EXPIRY' | 'PLAN_RENEWAL';

export interface RecipientDeadlineItem {
  recipient_id: number;
  recipient_name: string | null;
  kind: RecipientDeadlineKind;
  source_id: number | null;
  source_date: string;
  due_date: string;
}

export interface RecipientDeadlineListResponse {
  items: RecipientDeadlineItem[];
}

// Short aliases keep the page payload names readable while remaining anchored
// to the generator output above.
export type RecipientCreate = RecipientCreateRequest;
export type RecipientUpdate = RecipientUpdateRequest;
export type GuardianCreate = GuardianCreateRequest;

export type RecipientId = number | string;

export interface RecipientListOptions {
  search?: string;
  status?: RecipientListStatusFilter;
  page?: number;
  pageSize?: number;
  signal?: AbortSignal;
}

function recipientPath(recipientId: RecipientId): string {
  return `/api/v1/recipients/${encodeURIComponent(String(recipientId))}`;
}

function guardianPath(recipientId: RecipientId, guardianId: RecipientId): string {
  return `${recipientPath(recipientId)}/guardians/${encodeURIComponent(String(guardianId))}`;
}

export async function listRecipients(
  options: RecipientListOptions = {},
): Promise<RecipientListResponse> {
  const params = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 100),
  });
  if (options.search?.trim()) params.set('search', options.search.trim());
  if (options.status) params.set('status', options.status);
  return apiRequest<RecipientListResponse>(`/api/v1/recipients?${params.toString()}`, {
    method: 'GET',
    signal: options.signal,
  });
}

export async function fetchAllRecipients(
  signal?: AbortSignal,
): Promise<{ items: RecipientListItem[]; total: number }> {
  const pageSize = 200;
  const maxPages = 1_000;
  const first = await listRecipients({ page: 1, pageSize, signal });
  const uniqueItems = new Map<number, RecipientListItem>();
  for (const item of first.items) {
    if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item);
  }
  const total = first.total;
  let page = 2;
  while (uniqueItems.size < total && page <= maxPages) {
    const nextPage = await listRecipients({ page, pageSize, signal });
    if (nextPage.items.length === 0) break;
    for (const item of nextPage.items) {
      if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item);
    }
    page += 1;
  }
  return { items: [...uniqueItems.values()], total };
}

export function getRecipient(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<Recipient> {
  return apiRequest<Recipient>(recipientPath(recipientId), {
    method: 'GET',
    signal,
  });
}

export function createRecipient(
  payload: RecipientCreateRequest,
  signal?: AbortSignal,
): Promise<Recipient> {
  return apiRequest<Recipient>('/api/v1/recipients', {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export function updateRecipient(
  recipientId: RecipientId,
  payload: RecipientUpdateRequest,
  signal?: AbortSignal,
): Promise<Recipient> {
  return apiRequest<Recipient>(recipientPath(recipientId), {
    method: 'PATCH',
    body: JSON.stringify(payload),
    signal,
  });
}

export function listGuardians(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<GuardianListResponse> {
  return apiRequest<GuardianListResponse>(
    `${recipientPath(recipientId)}/guardians`,
    { method: 'GET', signal },
  );
}

export function getGuardian(
  recipientId: RecipientId,
  guardianId: RecipientId,
  signal?: AbortSignal,
): Promise<Guardian> {
  return apiRequest<Guardian>(guardianPath(recipientId, guardianId), { method: 'GET', signal });
}

export function createGuardian(
  recipientId: RecipientId,
  payload: GuardianCreateRequest,
  signal?: AbortSignal,
): Promise<Guardian> {
  return apiRequest<Guardian>(`${recipientPath(recipientId)}/guardians`, {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export function updateGuardian(
  recipientId: RecipientId,
  guardianId: RecipientId,
  payload: GuardianUpdateRequest,
  signal?: AbortSignal,
): Promise<Guardian> {
  return apiRequest<Guardian>(guardianPath(recipientId, guardianId), {
    method: 'PATCH',
    body: JSON.stringify(payload),
    signal,
  });
}

export function listRecipientDeadlines(
  signal?: AbortSignal,
): Promise<RecipientDeadlineListResponse> {
  return apiRequest<RecipientDeadlineListResponse>('/api/v1/recipients/deadlines', {
    method: 'GET',
    signal,
  });
}
