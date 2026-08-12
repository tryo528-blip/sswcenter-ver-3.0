import { apiRequest } from './api';
import type {
  Guardian,
  GuardianCreateRequest,
  GuardianUpdateRequest,
  Recipient,
  RecipientCreateRequest,
  RecipientUpdateRequest,
} from './recipientApi';

type PeriodMutation<T> = {
  period_id?: number;
  payload: T & { expected_row_version?: number };
};

export interface RecipientDetailBatchRequest {
  certification_identity?: { certification_number: string };
  certification_period?: PeriodMutation<{ start_date: string; end_date: string }>;
  grade_period?: PeriodMutation<{
    certification_period_id: number;
    grade_code: string;
    start_date: string;
    end_date: string;
  }>;
  benefit_period?: PeriodMutation<{
    benefit_code: string;
    start_date: string;
    end_date?: string | null;
  }>;
  approval_amount_period?: PeriodMutation<{
    amount_krw: number;
    start_date: string;
    end_date?: string | null;
  }>;
  plan_notification?: { notified_date: string };
  contract?: {
    service_type_code: string;
    start_date: string;
    end_date?: string | null;
    service_start_date?: string | null;
    signer_name?: string | null;
    signer_relationship_text?: string | null;
    signer_phone?: string | null;
    end_reason_text?: string | null;
  };
}

export interface RecipientDetailBatchResponse {
    recipient_id: number;
    saved_sections: string[];
}

export type BasicGuardianMutation = {
  slot: 0 | 1;
  guardian_id?: number;
  payload: GuardianCreateRequest | GuardianUpdateRequest;
};

export type BasicBenefitPeriodMutation = PeriodMutation<{
  benefit_code: string;
  start_date: string;
  end_date?: string | null;
}>;

export interface RecipientBasicCreateBatchRequest {
  recipient: RecipientCreateRequest;
  guardians: BasicGuardianMutation[];
  payer_guardian_slot: 0 | 1 | null;
  benefit_periods: BasicBenefitPeriodMutation[];
}

export interface RecipientBasicUpdateBatchRequest {
  recipient: RecipientUpdateRequest;
  guardians: BasicGuardianMutation[];
  payer_guardian_slot: 0 | 1 | null;
  preserve_payer: boolean;
  benefit_periods: BasicBenefitPeriodMutation[];
}

export interface RecipientBasicBatchResponse {
  recipient: Recipient;
  guardians: Guardian[];
  saved_sections: string[];
}

export function saveRecipientDetailBatch(
  recipientId: number,
  payload: RecipientDetailBatchRequest,
): Promise<RecipientDetailBatchResponse> {
  if (!Number.isSafeInteger(recipientId) || recipientId <= 0) {
    throw new Error('RECIPIENT_ID_INVALID');
  }
  return apiRequest(`/api/v1/recipients/${recipientId}/detail-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createRecipientBasicBatch(
  payload: RecipientBasicCreateBatchRequest,
): Promise<RecipientBasicBatchResponse> {
  return apiRequest('/api/v1/recipients/basic-batch', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateRecipientBasicBatch(
  recipientId: number,
  payload: RecipientBasicUpdateBatchRequest,
): Promise<RecipientBasicBatchResponse> {
  if (!Number.isSafeInteger(recipientId) || recipientId <= 0) {
    throw new Error('RECIPIENT_ID_INVALID');
  }
  return apiRequest(`/api/v1/recipients/${recipientId}/basic-batch`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
