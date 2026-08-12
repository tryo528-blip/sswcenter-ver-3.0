import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];

export type Recipient = Schemas['RecipientResponse'];
export type RecipientCreateRequest = Schemas['RecipientCreateRequest'];
export type RecipientUpdateRequest = Schemas['RecipientUpdateRequest'];
export type RecipientListItem = Schemas['RecipientListItem'];
export type RecipientListResponse = Schemas['RecipientListResponse'];
export type RecipientStatus = Schemas['RecipientStatus'];
export type RecipientListStatusFilter = Schemas['RecipientListStatusFilter'];
export type RecipientListServiceGroupItem = Schemas['RecipientListServiceGroupItem'];
export type RecipientListServiceTypeItem = Schemas['RecipientListServiceTypeItem'];
export type RecipientSexCode = Schemas['RecipientSexCode'];

/** Sealed manual-tag values for detail validation (ACTIVE|ENDED|WAITING). */
export const RECIPIENT_STATUS_VALUES = ['ACTIVE', 'ENDED', 'WAITING'] as const;

export function isRecipientStatus(value: unknown): value is RecipientStatus {
  return (
    value === 'ACTIVE' ||
    value === 'ENDED' ||
    value === 'WAITING'
  );
}
export type Guardian = Schemas['GuardianResponse'];
export type GuardianCreateRequest = Schemas['GuardianCreateRequest'];
export type GuardianUpdateRequest = Schemas['GuardianUpdateRequest'];
export type GuardianListResponse = Schemas['GuardianListResponse'];
export type PrimaryGuardianPeriod = Schemas['PrimaryGuardianPeriodResponse'];
export type PrimaryGuardianPeriodListResponse = Schemas['PrimaryGuardianPeriodListResponse'];
export type PrimaryGuardianPeriodCreateRequest =
  Schemas['PrimaryGuardianPeriodCreateRequest'];
export type PrimaryGuardianPeriodReplacementRequest =
  Schemas['PrimaryGuardianPeriodReplacementRequest'];
export type PrimaryGuardianPeriodReplacementResponse =
  Schemas['PrimaryGuardianPeriodReplacementResponse'];
export type PayerSnapshot = Schemas['PayerSnapshotResponse'];
export type PayerSnapshotListResponse = Schemas['PayerSnapshotListResponse'];
export type PayerSnapshotCreateRequest = Schemas['PayerSnapshotCreateRequest'];
export type PayerSnapshotReplacementRequest = Schemas['PayerSnapshotReplacementRequest'];
export type PayerSnapshotReplacementResponse = Schemas['PayerSnapshotReplacementResponse'];
export type HistoryInvalidateRequest = Schemas['HistoryInvalidateRequest'];
export type PlanNotification = Schemas['PlanNotificationResponse'];
export type PlanNotificationCreateRequest = Schemas['PlanNotificationCreateRequest'];
export type PlanNotificationListResponse = Schemas['PlanNotificationListResponse'];

export type RecipientDeadlineKind = 'CERTIFICATION_EXPIRY' | 'CONTRACT_EXPIRY' | 'PLAN_RENEWAL';

export interface RecipientDeadlineItem {
  recipient_id: number;
  recipient_name: string;
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
export type PrimaryGuardianPeriodCreate = PrimaryGuardianPeriodCreateRequest;
export type PayerSnapshotCreate = PayerSnapshotCreateRequest;

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

function primaryPeriodPath(recipientId: RecipientId, periodId: RecipientId): string {
  return `${recipientPath(recipientId)}/primary-guardian-periods/${encodeURIComponent(String(periodId))}`;
}

function payerSnapshotPath(recipientId: RecipientId, snapshotId: RecipientId): string {
  return `${recipientPath(recipientId)}/payer-snapshots/${encodeURIComponent(String(snapshotId))}`;
}

function planNotificationPath(recipientId: RecipientId, notificationId: RecipientId): string {
  return `${recipientPath(recipientId)}/plan-notifications/${encodeURIComponent(String(notificationId))}`;
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
): Promise<Schemas['GuardianListResponse']> {
  return apiRequest<Schemas['GuardianListResponse']>(
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

export function listPrimaryGuardianPeriods(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<Schemas['PrimaryGuardianPeriodListResponse']> {
  return apiRequest<Schemas['PrimaryGuardianPeriodListResponse']>(
    `${recipientPath(recipientId)}/primary-guardian-periods`,
    { method: 'GET', signal },
  );
}

export function getPrimaryGuardianPeriod(
  recipientId: RecipientId,
  periodId: RecipientId,
  signal?: AbortSignal,
): Promise<PrimaryGuardianPeriod> {
  return apiRequest<PrimaryGuardianPeriod>(primaryPeriodPath(recipientId, periodId), {
    method: 'GET',
    signal,
  });
}

export function createPrimaryGuardianPeriod(
  recipientId: RecipientId,
  payload: PrimaryGuardianPeriodCreateRequest,
  signal?: AbortSignal,
): Promise<PrimaryGuardianPeriod> {
  return apiRequest<PrimaryGuardianPeriod>(
    `${recipientPath(recipientId)}/primary-guardian-periods`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function invalidatePrimaryGuardianPeriod(
  recipientId: RecipientId,
  periodId: RecipientId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<PrimaryGuardianPeriod> {
  return apiRequest<PrimaryGuardianPeriod>(
    `${primaryPeriodPath(recipientId, periodId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function replacePrimaryGuardianPeriod(
  recipientId: RecipientId,
  periodId: RecipientId,
  payload: PrimaryGuardianPeriodReplacementRequest,
  signal?: AbortSignal,
): Promise<PrimaryGuardianPeriodReplacementResponse> {
  return apiRequest<PrimaryGuardianPeriodReplacementResponse>(
    `${primaryPeriodPath(recipientId, periodId)}/replacements`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function listPayerSnapshots(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<PayerSnapshotListResponse> {
  return apiRequest<PayerSnapshotListResponse>(
    `${recipientPath(recipientId)}/payer-snapshots`,
    { method: 'GET', signal },
  );
}

export function getPayerSnapshot(
  recipientId: RecipientId,
  snapshotId: RecipientId,
  signal?: AbortSignal,
): Promise<PayerSnapshot> {
  return apiRequest<PayerSnapshot>(payerSnapshotPath(recipientId, snapshotId), {
    method: 'GET',
    signal,
  });
}

export function createPayerSnapshot(
  recipientId: RecipientId,
  payload: PayerSnapshotCreateRequest,
  signal?: AbortSignal,
): Promise<PayerSnapshot> {
  return apiRequest<PayerSnapshot>(
    `${recipientPath(recipientId)}/payer-snapshots`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function invalidatePayerSnapshot(
  recipientId: RecipientId,
  snapshotId: RecipientId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<PayerSnapshot> {
  return apiRequest<PayerSnapshot>(
    `${payerSnapshotPath(recipientId, snapshotId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function replacePayerSnapshot(
  recipientId: RecipientId,
  snapshotId: RecipientId,
  payload: PayerSnapshotReplacementRequest,
  signal?: AbortSignal,
): Promise<PayerSnapshotReplacementResponse> {
  return apiRequest<PayerSnapshotReplacementResponse>(
    `${payerSnapshotPath(recipientId, snapshotId)}/replacements`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function listPlanNotifications(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<PlanNotificationListResponse> {
  return apiRequest<PlanNotificationListResponse>(
    `${recipientPath(recipientId)}/plan-notifications`,
    { method: 'GET', signal },
  );
}

export function createPlanNotification(
  recipientId: RecipientId,
  payload: PlanNotificationCreateRequest,
  signal?: AbortSignal,
): Promise<PlanNotification> {
  return apiRequest<PlanNotification>(
    `${recipientPath(recipientId)}/plan-notifications`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function invalidatePlanNotification(
  recipientId: RecipientId,
  notificationId: RecipientId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<PlanNotification> {
  return apiRequest<PlanNotification>(
    `${planNotificationPath(recipientId, notificationId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function listRecipientDeadlines(
  signal?: AbortSignal,
): Promise<RecipientDeadlineListResponse> {
  return apiRequest<RecipientDeadlineListResponse>('/api/v1/recipients/deadlines', {
    method: 'GET',
    signal,
  });
}
