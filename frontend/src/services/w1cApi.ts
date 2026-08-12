import type { components } from '../generated/sswcenter-api';
import { apiRequest } from './api';

type Schemas = components['schemas'];
type RecipientId = number | string;
type PeriodId = number | string;

export type CertificationIdentity = Schemas['CertificationIdentityResponse'];
export type CertificationIdentityCreateRequest =
  Schemas['CertificationIdentityCreateRequest'];
export type CertificationPeriod = Schemas['CertificationPeriodResponse'];
export type CertificationPeriodCreateRequest =
  Schemas['CertificationPeriodCreateRequest'];
export type CertificationPeriodReplacementRequest =
  Schemas['CertificationPeriodReplacementRequest'];
export type CertificationPeriodReplacementResponse =
  Schemas['CertificationPeriodReplacementResponse'];
export type GradePeriod = Schemas['GradePeriodResponse'];
export type GradePeriodCreateRequest = Schemas['GradePeriodCreateRequest'];
export type GradePeriodReplacementRequest =
  Schemas['GradePeriodReplacementRequest'];
export type GradePeriodReplacementResponse =
  Schemas['GradePeriodReplacementResponse'];
export type GradeCode = Schemas['GradeCode'];
export type BenefitPeriod = Schemas['BenefitPeriodResponse'];
export type BenefitPeriodCreateRequest = Schemas['BenefitPeriodCreateRequest'];
export type BenefitPeriodReplacementRequest =
  Schemas['BenefitPeriodReplacementRequest'];
export type BenefitPeriodReplacementResponse =
  Schemas['BenefitPeriodReplacementResponse'];
export type BenefitCode = Schemas['BenefitCode'];
export type EffectiveBenefit = Schemas['EffectiveBenefitResponse'];
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
  const response = await apiRequest<Schemas['CertificationPeriodListResponse']>(
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

export async function listGradePeriods(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<GradePeriod[]> {
  const response = await apiRequest<Schemas['GradePeriodListResponse']>(
    collectionPath(recipientId, 'grade-periods'),
    { method: 'GET', signal },
  );
  return response.items;
}

export function createGradePeriod(
  recipientId: RecipientId,
  payload: GradePeriodCreateRequest,
  signal?: AbortSignal,
): Promise<GradePeriod> {
  return apiRequest<GradePeriod>(collectionPath(recipientId, 'grade-periods'), {
    method: 'POST',
    body: JSON.stringify(payload),
    signal,
  });
}

export function invalidateGradePeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: HistoryInvalidateRequest,
  signal?: AbortSignal,
): Promise<GradePeriod> {
  return apiRequest<GradePeriod>(
    `${periodPath(recipientId, 'grade-periods', periodId)}/invalidate`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export function replaceGradePeriod(
  recipientId: RecipientId,
  periodId: PeriodId,
  payload: GradePeriodReplacementRequest,
  signal?: AbortSignal,
): Promise<GradePeriodReplacementResponse> {
  return apiRequest<GradePeriodReplacementResponse>(
    `${periodPath(recipientId, 'grade-periods', periodId)}/replacements`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  );
}

export async function listBenefitPeriods(
  recipientId: RecipientId,
  signal?: AbortSignal,
): Promise<BenefitPeriod[]> {
  const response = await apiRequest<Schemas['BenefitPeriodListResponse']>(
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

export function getEffectiveBenefit(
  recipientId: RecipientId,
  onDate: string,
  signal?: AbortSignal,
): Promise<EffectiveBenefit> {
  const query = new URLSearchParams({ on_date: onDate });
  return apiRequest<EffectiveBenefit>(
    `${collectionPath(recipientId, 'benefit-periods')}/effective?${query.toString()}`,
    { method: 'GET', signal },
  );
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
