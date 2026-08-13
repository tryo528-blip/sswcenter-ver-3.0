import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];
type RecipientId = number | string;
type PeriodId = number | string;

export type CertificationIdentity = Schemas['CertificationIdentityResponse'];
export type CertificationIdentityCreateRequest =
  Schemas['CertificationIdentityCreateRequest'];
export type GradeCode = '1' | '2' | '3' | '4' | '5';
export type BenefitCode =
  | 'GENERAL'
  | 'BASIC_LIVELIHOOD'
  | 'REDUCTION_6'
  | 'REDUCTION_9'
  | 'MEDICAL_6'
  | 'MEDICAL_9';

// Current backend W1 certification schema keeps grade on the certification period.
export interface CertificationPeriodCreateRequest {
  grade_code: GradeCode;
  start_date: string;
  end_date: string;
}

export interface CertificationPeriodReplacementRequest
  extends CertificationPeriodCreateRequest {
  expected_row_version: number;
}

export interface CertificationPeriod {
  id: number;
  recipient_id: number;
  grade_code: GradeCode;
  start_date: string;
  end_date: string;
  invalidated_at_utc: string | null;
  replacement_certification_period_id: number | null;
  row_version: number;
}

export interface CertificationPeriodReplacementResponse {
  original: CertificationPeriod;
  replacement: CertificationPeriod;
}

// start_text is opaque display text. It is never parsed, ordered, or validated
// as a date by the frontend.
export interface BenefitPeriodCreateRequest {
  benefit_code: BenefitCode;
  start_text?: string;
}

export interface BenefitPeriodReplacementRequest
  extends BenefitPeriodCreateRequest {
  expected_row_version: number;
}

export interface BenefitPeriod {
  id: number;
  recipient_id: number;
  benefit_code: BenefitCode;
  start_text: string;
  invalidated_at_utc: string | null;
  replacement_benefit_period_id: number | null;
  row_version: number;
}

export interface BenefitPeriodReplacementResponse {
  original: BenefitPeriod;
  replacement: BenefitPeriod;
}
type GeneratedApprovalAmountPeriod = Schemas['ApprovalAmountPeriodResponse'];
export type ApprovalAmountPeriod = Omit<
  GeneratedApprovalAmountPeriod,
  'amount_krw'
> & {
  amount_krw: string;
};
export type ApprovalAmountPeriodCreateRequest = Omit<
  Schemas['ApprovalAmountPeriodCreateRequest'],
  'amount_krw'
> & {
  amount_krw: string;
};
export type ApprovalAmountPeriodReplacementRequest = Omit<
  Schemas['ApprovalAmountPeriodReplacementRequest'],
  'amount_krw'
> & {
  amount_krw: string;
};
export type ApprovalAmountPeriodReplacementResponse = {
  original: ApprovalAmountPeriod;
  replacement: ApprovalAmountPeriod;
};
export type HistoryInvalidateRequest = Schemas['HistoryInvalidateRequest'];

const POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807n;

function recipientPath(recipientId: RecipientId): string {
  return `/api/v1/recipients/${encodeURIComponent(String(recipientId))}`;
}

function collectionPath(recipientId: RecipientId, collection: string): string {
  return `${recipientPath(recipientId)}/${collection}`;
}

function periodPath(
  recipientId: RecipientId,
  collection: string,
  periodId: PeriodId,
): string {
  return `${collectionPath(recipientId, collection)}/${encodeURIComponent(String(periodId))}`;
}

export function normalizeApprovalAmountKrw(value: string): string | null {
  const trimmed = value.trim();
  if (!/^[0-9]+$/.test(trimmed)) return null;
  try {
    const amount = BigInt(trimmed);
    if (amount > POSTGRES_BIGINT_MAX) return null;
    return amount.toString();
  } catch {
    return null;
  }
}

export function parseApprovalAmountJson(text: string): unknown {
  let transformed = '';
  let index = 0;

  while (index < text.length) {
    if (text[index] !== '"') {
      transformed += text[index];
      index += 1;
      continue;
    }

    let stringEnd = index + 1;
    let escaped = false;
    while (stringEnd < text.length) {
      const character = text[stringEnd];
      if (escaped) {
        escaped = false;
      } else if (character === '\\') {
        escaped = true;
      } else if (character === '"') {
        break;
      }
      stringEnd += 1;
    }
    if (stringEnd >= text.length) {
      throw new SyntaxError('Unterminated JSON string');
    }

    const stringToken = text.slice(index, stringEnd + 1);
    if (stringToken === '"amount_krw"') {
      let cursor = stringEnd + 1;
      while (/\s/.test(text[cursor] ?? '')) cursor += 1;
      if (text[cursor] === ':') {
        cursor += 1;
        while (/\s/.test(text[cursor] ?? '')) cursor += 1;
        const numberStart = cursor;
        if (text[cursor] === '-') cursor += 1;
        const digitStart = cursor;
        while (/[0-9]/.test(text[cursor] ?? '')) cursor += 1;
        const hasDigits = cursor > digitStart;
        const delimiter = text[cursor];
        const hasValidDelimiter =
          delimiter === undefined || /[\s,\]}]/.test(delimiter);
        if (hasDigits && hasValidDelimiter) {
          transformed += text.slice(index, numberStart);
          transformed += JSON.stringify(text.slice(numberStart, cursor));
          index = cursor;
          continue;
        }
      }
    }

    transformed += stringToken;
    index = stringEnd + 1;
  }

  return JSON.parse(transformed) as unknown;
}

async function decodeApprovalAmountResponse(response: Response): Promise<unknown> {
  return parseApprovalAmountJson(await response.text());
}

function serializeApprovalAmountPayload(
  payload:
    | ApprovalAmountPeriodCreateRequest
    | ApprovalAmountPeriodReplacementRequest,
): string {
  const normalized = normalizeApprovalAmountKrw(payload.amount_krw);
  if (normalized === null) {
    throw new RangeError('amount_krw must be a PostgreSQL bigint');
  }
  return JSON.stringify({ ...payload, amount_krw: null }).replace(
    '"amount_krw":null',
    `"amount_krw":${normalized}`,
  );
}

export function getCertificationIdentity(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<CertificationIdentity> {
  return apiRequest<CertificationIdentity>(
    `${recipientPath(recipientId)}/certification-identity`,
    { method: 'GET', signal },
  );
}

export function createCertificationIdentity(
  recipientId: RecipientId,
  payload: CertificationIdentityCreateRequest,
  signal?: AbortSignal,
): Promise<CertificationIdentity> {
  return apiRequest<CertificationIdentity>(
    `${recipientPath(recipientId)}/certification-identity`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export async function listCertificationPeriods(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<CertificationPeriod[]> {
  const response = await apiRequest<{ items: CertificationPeriod[] }>(
    collectionPath(recipientId, 'certification-periods'),
    { method: 'GET', signal },
  );
  return response.items;
}

export function createCertificationPeriod(
  recipientId: RecipientId,
  payload: CertificationPeriodCreateRequest,
  signal?: AbortSignal,
): Promise<CertificationPeriod> {
  return apiRequest<CertificationPeriod>(
    collectionPath(recipientId, 'certification-periods'),
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function invalidateCertificationPeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<CertificationPeriod> {
  return apiRequest<CertificationPeriod>(
    `${periodPath(recipientId, 'certification-periods', periodId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function replaceCertificationPeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: CertificationPeriodReplacementRequest,
  signal?: AbortSignal,
): Promise<CertificationPeriodReplacementResponse> {
  return apiRequest<CertificationPeriodReplacementResponse>(
    `${periodPath(recipientId, 'certification-periods', periodId)}/replacements`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export async function listBenefitPeriods(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<BenefitPeriod[]> {
  const response = await apiRequest<{ items: BenefitPeriod[] }>(
    collectionPath(recipientId, 'benefit-periods'),
    { method: 'GET', signal },
  );
  return response.items;
}

export function createBenefitPeriod(
  recipientId: RecipientId,
  payload: BenefitPeriodCreateRequest,
  signal?: AbortSignal,
): Promise<BenefitPeriod> {
  return apiRequest<BenefitPeriod>(collectionPath(recipientId, 'benefit-periods'), {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export function invalidateBenefitPeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<BenefitPeriod> {
  return apiRequest<BenefitPeriod>(
    `${periodPath(recipientId, 'benefit-periods', periodId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function replaceBenefitPeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: BenefitPeriodReplacementRequest,
  signal?: AbortSignal,
): Promise<BenefitPeriodReplacementResponse> {
  return apiRequest<BenefitPeriodReplacementResponse>(
    `${periodPath(recipientId, 'benefit-periods', periodId)}/replacements`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export async function listApprovalAmountPeriods(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<ApprovalAmountPeriod[]> {
  const response = await apiRequest<{ items: ApprovalAmountPeriod[] }>(
    collectionPath(recipientId, 'approval-amount-periods'),
    { method: 'GET', signal },
    decodeApprovalAmountResponse,
  );
  return response.items;
}

export function createApprovalAmountPeriod(
  recipientId: RecipientId,
  payload: ApprovalAmountPeriodCreateRequest,
  signal?: AbortSignal,
): Promise<ApprovalAmountPeriod> {
  return apiRequest<ApprovalAmountPeriod>(
    collectionPath(recipientId, 'approval-amount-periods'),
    { method: 'POST', body: serializeApprovalAmountPayload(payload), signal },
    decodeApprovalAmountResponse,
  );
}

export function invalidateApprovalAmountPeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<ApprovalAmountPeriod> {
  return apiRequest<ApprovalAmountPeriod>(
    `${periodPath(recipientId, 'approval-amount-periods', periodId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
    decodeApprovalAmountResponse,
  );
}

export function replaceApprovalAmountPeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: ApprovalAmountPeriodReplacementRequest,
  signal?: AbortSignal,
): Promise<ApprovalAmountPeriodReplacementResponse> {
  return apiRequest<ApprovalAmountPeriodReplacementResponse>(
    `${periodPath(recipientId, 'approval-amount-periods', periodId)}/replacements`,
    { method: 'POST', body: serializeApprovalAmountPayload(payload), signal },
    decodeApprovalAmountResponse,
  );
}
