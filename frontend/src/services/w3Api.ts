import { apiRequest, ApiError } from './api';

export type W3SourceType = 'NHIS_SCHEDULE' | 'RFID';
export type W3RunStatus =
  | 'RECEIVED'
  | 'PARSING'
  | 'PREVIEW_READY'
  | 'CONFIRMED'
  | 'APPLYING'
  | 'APPLIED'
  | 'BLOCKED'
  | 'FAILED';
export type W3MatchStatus =
  | 'AUTO_MATCH'
  | 'MANUAL_MATCH'
  | 'REVIEW_PENDING'
  | 'BLOCKED';

export interface W3RunCounts {
  readonly raw_rows: number;
  readonly normalized_rows: number;
  readonly target_rows: number;
  readonly derived_groups: number;
  readonly auto_matches: number;
  readonly manual_matches: number;
  readonly review_pending: number;
  readonly blocked: number;
}

export interface W3DecisionItem {
  readonly id: number;
  readonly source_occurrence_identity: string;
  readonly status: W3MatchStatus;
  readonly reason_code: string;
  readonly source_row_number: number | null;
  readonly service_date: string;
  readonly service_category: string;
  readonly event_state: string | null;
  readonly end_display: string | null;
  readonly row_version: number;
}

export interface W3RunSummary {
  readonly id: number;
  readonly source_type: W3SourceType;
  readonly target_date: string;
  readonly original_filename: string;
  readonly parser_profile_version: string;
  readonly status: W3RunStatus;
  readonly row_version: number;
  readonly preview_digest: string | null;
  readonly warning_codes: readonly string[];
  readonly counts: W3RunCounts;
  readonly decisions: readonly W3DecisionItem[];
  readonly created_at_utc: string;
  readonly can_confirm: boolean;
  readonly can_apply: boolean;
}

export interface W3ActiveSnapshot {
  readonly snapshot_id: number;
  readonly import_run_id: number;
  readonly source_type: W3SourceType;
  readonly target_date: string;
  readonly row_version: number;
}

export interface W3WorkspaceResponse {
  readonly source_type: W3SourceType;
  readonly target_date: string;
  readonly active: W3ActiveSnapshot | null;
  readonly latest_run: W3RunSummary | null;
  readonly recent_runs: readonly W3RunSummary[];
}

export interface W3ResolveDecisionInput {
  readonly expected_run_row_version: number;
  readonly recipient_id: number;
  readonly certification_period_id: number;
  readonly staff_id: number;
  readonly employment_id: number;
  readonly service_type_id: number;
  readonly recipient_contract_id: number;
  readonly care_assignment_id: number;
  readonly w2_schedule_id: number;
}

export const W3_ENDPOINTS = {
  workspace: '/api/v1/w3/workspace',
  importRuns: '/api/v1/w3/import-runs',
  confirm: (runId: number) => `/api/v1/w3/import-runs/${runId}/confirm`,
  apply: (runId: number) => `/api/v1/w3/import-runs/${runId}/apply`,
  resolve: (runId: number, decisionId: number) =>
    `/api/v1/w3/import-runs/${runId}/decisions/${decisionId}/resolve`,
} as const;

export function newW3CommandKey(kind: string): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `w3-${kind}-${suffix}`;
}

export async function getW3Workspace(
  sourceType: W3SourceType,
  targetDate: string,
  signal?: AbortSignal,
): Promise<W3WorkspaceResponse> {
  const query = new URLSearchParams({
    source_type: sourceType,
    target_date: targetDate,
  });
  return apiRequest<W3WorkspaceResponse>(
    `${W3_ENDPOINTS.workspace}?${query.toString()}`,
    { method: 'GET', signal },
  );
}

export async function uploadW3Workbook(input: {
  sourceType: W3SourceType;
  targetDate: string;
  file: File;
}): Promise<W3WorkspaceResponse> {
  const body = new FormData();
  body.set('source_type', input.sourceType);
  body.set('target_date', input.targetDate);
  body.set('file', input.file, input.file.name);
  return apiRequest<W3WorkspaceResponse>(W3_ENDPOINTS.importRuns, {
    method: 'POST',
    body,
  });
}

export async function confirmW3ImportRun(
  run: Pick<W3RunSummary, 'id' | 'row_version' | 'preview_digest'>,
  commandIdempotencyKey = newW3CommandKey('confirm'),
): Promise<W3WorkspaceResponse> {
  if (!run.preview_digest) throw new Error('확인할 미리보기 식별값이 없습니다.');
  return apiRequest<W3WorkspaceResponse>(W3_ENDPOINTS.confirm(run.id), {
    method: 'POST',
    body: JSON.stringify({
      expected_row_version: run.row_version,
      preview_digest: run.preview_digest,
      command_idempotency_key: commandIdempotencyKey,
    }),
  });
}

export async function applyW3ImportRun(
  run: Pick<W3RunSummary, 'id' | 'row_version'>,
  commandIdempotencyKey = newW3CommandKey('apply'),
): Promise<W3WorkspaceResponse> {
  return apiRequest<W3WorkspaceResponse>(W3_ENDPOINTS.apply(run.id), {
    method: 'POST',
    body: JSON.stringify({
      expected_row_version: run.row_version,
      command_idempotency_key: commandIdempotencyKey,
    }),
  });
}

export async function resolveW3MatchDecision(
  runId: number,
  decisionId: number,
  input: W3ResolveDecisionInput,
  commandIdempotencyKey = newW3CommandKey('resolve'),
): Promise<W3WorkspaceResponse> {
  return apiRequest<W3WorkspaceResponse>(W3_ENDPOINTS.resolve(runId, decisionId), {
    method: 'POST',
    body: JSON.stringify({
      ...input,
      command_idempotency_key: commandIdempotencyKey,
    }),
  });
}

export function latestW3WorkspaceFromError(error: unknown): W3WorkspaceResponse | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const latest = error.details?.latest;
  if (!latest || typeof latest !== 'object' || Array.isArray(latest)) return null;
  return latest as W3WorkspaceResponse;
}

export { ApiError };
