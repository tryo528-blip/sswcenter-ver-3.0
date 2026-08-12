import { apiRequest, ApiError } from './api';
import type { components } from '../generated/sswcenter-api';

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

type W1DSchemas = components['schemas'];

export type ContractCreateRequest = W1DSchemas['ContractCreateRequest'];
export type ContractEndRequest = W1DSchemas['ContractEndRequest'];
export type ContractResponse = W1DSchemas['ContractResponse'];
export type ContractListResponse = W1DSchemas['ContractListResponse'];
export type TransitionReplacementItem = W1DSchemas['TransitionReplacementItem'];
export type TransitionPreviewRequest =
  W1DSchemas['CertificationTransitionPreviewRequest'];
export type TransitionPreviewResponse =
  W1DSchemas['CertificationTransitionPreviewResponse'];
export type TransitionApplyRequest =
  W1DSchemas['CertificationTransitionApplyRequest'];
export type TransitionApplyResponse =
  W1DSchemas['CertificationTransitionApplyResponse'];

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

export async function previewCertificationTransition(
  recipientId: number | string,
  body: TransitionPreviewRequest,
): Promise<TransitionPreviewResponse> {
  return apiRequest(
    `/api/v1/recipients/${w1dIdPath(recipientId)}/certification-transitions/preview`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export async function applyCertificationTransition(
  recipientId: number | string,
  body: TransitionApplyRequest,
): Promise<TransitionApplyResponse> {
  return apiRequest(
    `/api/v1/recipients/${w1dIdPath(recipientId)}/certification-transitions/apply`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export { ApiError };
