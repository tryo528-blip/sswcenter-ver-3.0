import { apiRequest, ApiError } from './api';

/** Lossless bigint-safe id as string for URL path segments (W1C pattern). */
export function w1dIdPath(id: number | string): string {
  if (typeof id === 'number') {
    if (!Number.isSafeInteger(id) || id <= 0) {
      throw new Error('W1D_ID_NOT_SAFE_INTEGER');
    }
    return String(id);
  }
  if (typeof id === 'string' && /^[1-9][0-9]*$/.test(id)) {
    return id;
  }
  throw new Error('W1D_ID_INVALID');
}

export type ServiceTypeCode =
  | 'HOME_CARE'
  | 'HOME_BATH'
  | 'TEMP_HOME_CARE'
  | 'HOSPITAL_ESCORT'
  | 'BARO_CARE';

export interface ContractCreateRequest {
  service_type_code: ServiceTypeCode;
  start_date: string;
  end_date?: string | null;
  service_start_date?: string | null;
  end_reason_text?: string | null;
}

export interface ContractEndRequest {
  expected_row_version: number;
  end_date: string;
  end_reason_text?: string | null;
}

export interface ContractResponse {
  id: number;
  recipient_id: number;
  service_type_code: string;
  service_group_code: string | null;
  start_date: string;
  end_date: string | null;
  service_start_date: string | null;
  end_reason_text: string | null;
  invalidated_at_utc: string | null;
  replacement_contract_id: number | null;
  row_version: number;
}

export interface ContractListResponse {
  items: ContractResponse[];
}

export async function listContracts(
  recipientId: number | string,
): Promise<ContractListResponse> {
  return apiRequest(`/api/v1/recipients/${w1dIdPath(recipientId)}/contracts`);
}

export async function createContract(
  recipientId: number | string,
  body: ContractCreateRequest,
): Promise<ContractResponse> {
  return apiRequest(`/api/v1/recipients/${w1dIdPath(recipientId)}/contracts`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function endContract(
  recipientId: number | string,
  contractId: number | string,
  body: ContractEndRequest,
): Promise<ContractResponse> {
  return apiRequest(
    `/api/v1/recipients/${w1dIdPath(recipientId)}/contracts/${w1dIdPath(contractId)}/end`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export { ApiError };
