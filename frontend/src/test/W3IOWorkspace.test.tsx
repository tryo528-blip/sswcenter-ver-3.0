import './setup';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import IOPage from '../pages/IOPage';
import {
  uploadW3Workbook,
  type W3DecisionItem,
  type W3RunStatus,
  type W3WorkspaceResponse,
} from '../services/w3Api';

const originalFetch = globalThis.fetch;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function decision(overrides: Partial<W3DecisionItem> = {}): W3DecisionItem {
  return {
    id: 51,
    source_occurrence_identity: 'rfid-row-7',
    status: 'REVIEW_PENDING',
    reason_code: 'MULTIPLE_SCHEDULE_CANDIDATES',
    source_row_number: 7,
    service_date: '2026-08-18',
    service_category: '방문요양',
    event_state: 'PAIRED',
    end_display: '10:00',
    row_version: 1,
    ...overrides,
  };
}

function workspace(
  status: W3RunStatus = 'PREVIEW_READY',
  options: {
    runVersion?: number;
    decisions?: readonly W3DecisionItem[];
    canConfirm?: boolean;
    canApply?: boolean;
  } = {},
): W3WorkspaceResponse {
  const decisions = options.decisions ?? [];
  const reviewPending = decisions.filter((item) => item.status === 'REVIEW_PENDING').length;
  const blocked = decisions.filter((item) => item.status === 'BLOCKED').length;
  const latestRun = {
    id: 31,
    source_type: 'RFID' as const,
    target_date: '2026-08-18',
    original_filename: 'rfid-sample.xlsx',
    parser_profile_version: 'rfid-v1',
    status,
    row_version: options.runVersion ?? 2,
    preview_digest: 'a'.repeat(64),
    warning_codes: [],
    counts: {
      raw_rows: 4,
      normalized_rows: 4,
      target_rows: 4,
      derived_groups: 0,
      auto_matches: 4 - decisions.length,
      manual_matches: 0,
      review_pending: reviewPending,
      blocked,
    },
    decisions,
    created_at_utc: '2026-08-18T02:00:00Z',
    can_confirm: options.canConfirm ?? status === 'PREVIEW_READY',
    can_apply: options.canApply ?? status === 'CONFIRMED',
  };
  return {
    source_type: 'RFID',
    target_date: '2026-08-18',
    active: status === 'APPLIED' ? {
      snapshot_id: 21,
      import_run_id: 31,
      source_type: 'RFID',
      target_date: '2026-08-18',
      row_version: 2,
    } : null,
    latest_run: latestRun,
    recent_runs: [latestRun],
  };
}

describe('W3 FILE_ONLY workspace', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('uploads an xlsx as multipart without overriding the browser boundary header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(workspace()));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const file = new File(['xlsx'], 'rfid.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    await uploadW3Workbook({ sourceType: 'RFID', targetDate: '2026-08-18', file });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/w3/import-runs');
    expect(init.method).toBe('POST');
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
    const body = init.body as FormData;
    expect(body.get('source_type')).toBe('RFID');
    expect(body.get('target_date')).toBe('2026-08-18');
    expect((body.get('file') as File).name).toBe('rfid.xlsx');
  });

  it('keeps preview confirmation and atomic apply in one stateful screen', async () => {
    const preview = workspace('PREVIEW_READY', { canConfirm: true, canApply: false });
    const confirmed = workspace('CONFIRMED', {
      runVersion: 3,
      canConfirm: false,
      canApply: true,
    });
    const applied = workspace('APPLIED', {
      runVersion: 4,
      canConfirm: false,
      canApply: false,
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/v1/w3/workspace?')) return json(preview);
      if (url.endsWith('/31/confirm') && init?.method === 'POST') return json(confirmed);
      if (url.endsWith('/31/apply') && init?.method === 'POST') return json(applied);
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<IOPage />);
    expect(await screen.findByText('rfid-sample.xlsx')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '미리보기 확인' }));
    expect(await screen.findByText(/미리보기를 확인했습니다/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '업무자료 적용' }));
    expect(await screen.findByText('업무자료 적용이 완료되었습니다.')).toBeInTheDocument();

    const confirmCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/31/confirm'));
    const applyCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/31/apply'));
    expect(JSON.parse(String(confirmCall?.[1]?.body))).toMatchObject({
      expected_row_version: 2,
      preview_digest: 'a'.repeat(64),
    });
    expect(JSON.parse(String(applyCall?.[1]?.body))).toMatchObject({
      expected_row_version: 3,
    });
    expect(screen.getAllByText('적용 완료')).toHaveLength(2);
    expect(screen.getByText('현재 적용본')).toBeInTheDocument();
    expect(screen.getByText('스냅샷 #21')).toBeInTheDocument();
    expect(screen.getByText('실행 #31')).toBeInTheDocument();
    expect(screen.getByText('제어 버전 2')).toBeInTheDocument();
  });

  it('preserves the selected review row and typed IDs when a 409 refreshes latest state', async () => {
    const pending = workspace('PREVIEW_READY', {
      decisions: [decision()],
      canConfirm: false,
      canApply: false,
    });
    const latest = workspace('PREVIEW_READY', {
      runVersion: 3,
      decisions: [decision({ row_version: 2 })],
      canConfirm: false,
      canApply: false,
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/v1/w3/workspace?')) return json(pending);
      if (url.endsWith('/decisions/51/resolve')) {
        return json({
          error: { code: 'W3_ROW_VERSION_CONFLICT', message: '최신 상태를 확인하세요.' },
          details: { latest },
        }, 409);
      }
      throw new Error(`Unexpected request: ${init?.method ?? 'GET'} ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<IOPage />);
    fireEvent.click(await screen.findByRole('button', { name: '연결 입력' }));
    for (const label of [
      '수급자 ID',
      '인정기간 ID',
      '직원 ID',
      '재직 ID',
      '서비스유형 ID',
      '계약 ID',
      '배정 ID',
      '일정 ID',
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: '7' } });
    }
    fireEvent.click(screen.getByRole('button', { name: '수동 연결 저장' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('최신 상태를 확인하세요.');
    expect(screen.getByText('검토 항목 #51 연결')).toBeInTheDocument();
    expect(screen.getByLabelText('수급자 ID')).toHaveValue(7);
    await waitFor(() => {
      const resolveCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/resolve'));
      expect(JSON.parse(String(resolveCall?.[1]?.body))).toMatchObject({
        expected_run_row_version: 2,
        recipient_id: 7,
        w2_schedule_id: 7,
      });
    });
  });

  it('contains a narrow-screen layout contract for 390px devices', () => {
    const css = readFileSync(join(__dirname, '..', 'styles', 'io.css'), 'utf-8');
    expect(css).toContain('@media (max-width: 520px)');
    expect(css).toContain('grid-template-columns: minmax(0, 1fr)');
  });
});
